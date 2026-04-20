"""
app/alerts/digest_worker.py — cadence-driven digest runner.

Public entry points:
  * ``run_digest(pool, alert_id, claude=None, force=False) -> dict``
      Run a single alert now: select matching documents since ``last_run``,
      call Claude Haiku with the alert's ``llm_prompt`` for the summary, persist
      an ``alert_digests`` row, and deliver to every active subscription.
  * ``run_all_due_digests(pool, claude=None) -> dict``
      Loop over every alert whose cadence is due relative to the most recent
      ``alert_digests.run_at`` and call ``run_digest`` on each. Intended to be
      called from ``app.ingestion.scheduler`` or any cron wrapper.

Design notes
------------
- ``source_filter`` is a *forgiving* JSONB predicate. Supported keys:
    - ``source``            — exact match on ``documents.source``
    - ``source_in``         — list, matches any
    - ``filing_type``       — exact match on ``documents.filing_type``
    - ``filing_type_in``    — list, matches any
    - ``commission_authority``
    - ``case_type_in``      — joins via ``dockets`` and filters on ``case_type``
    - ``topic_tags_any``    — any of the tags must be present in the JSONB
                              ``documents.topic_tags`` (list form)
    - ``min_capacity_mw``   — soft filter inside ``extracted_fields``
  Unknown keys are ignored rather than erroring — lets the ingestion layer
  add new tags without breaking the worker.

- Claude model: ``claude-haiku-4-5-20251001`` per task spec. If the claude
  client is not provided the worker still stores a digest row so the
  ``/api/alerts/digest`` endpoint has something to return — the ``llm_extract``
  is just a deterministic summary listing the document titles.

- Cadence → due-interval in minutes, used only when deciding whether to run
  a given alert on the all-due sweep:
    realtime   = 5
    daily      = 24h
    weekday    = 24h (Mon-Fri)
    weekly_*   = 7d
    biweekly   = 14d
    monthly    = 30d
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID

import asyncpg

from app.alerts.delivery import deliver as deliver_digest

log = logging.getLogger("princeps.alerts.digest_worker")

DIGEST_MODEL = "claude-haiku-4-5-20251001"

_CADENCE_MIN_INTERVAL = {
    "realtime":   timedelta(minutes=5),
    "daily":      timedelta(hours=23),
    "weekday":    timedelta(hours=23),
    "weekly_mon": timedelta(days=6, hours=23),
    "weekly_tue": timedelta(days=6, hours=23),
    "weekly_wed": timedelta(days=6, hours=23),
    "weekly_thu": timedelta(days=6, hours=23),
    "weekly_fri": timedelta(days=6, hours=23),
    "biweekly":   timedelta(days=13, hours=23),
    "monthly":    timedelta(days=29, hours=23),
}


# ---------------------------------------------------------------------------
# Source-filter → SQL
# ---------------------------------------------------------------------------

def _build_doc_query(
    source_filter: Mapping[str, Any],
    since: datetime,
) -> tuple[str, list[Any]]:
    """Translate a source_filter JSON dict to (SQL, params).

    Generated SQL selects the minimal set of fields the digest + delivery
    layers need. Always filters ``published_at > since``.
    """
    conditions: list[str] = ["d.published_at IS NOT NULL", "d.published_at > $1"]
    params: list[Any] = [since]
    next_idx = 2

    src = source_filter.get("source")
    if isinstance(src, str) and src:
        conditions.append(f"d.source = ${next_idx}")
        params.append(src)
        next_idx += 1

    src_in = source_filter.get("source_in")
    if isinstance(src_in, (list, tuple)) and src_in:
        conditions.append(f"d.source = ANY(${next_idx}::text[])")
        params.append(list(src_in))
        next_idx += 1

    ft = source_filter.get("filing_type")
    if isinstance(ft, str) and ft:
        conditions.append(f"d.filing_type = ${next_idx}")
        params.append(ft)
        next_idx += 1

    ft_in = source_filter.get("filing_type_in")
    if isinstance(ft_in, (list, tuple)) and ft_in:
        conditions.append(f"d.filing_type = ANY(${next_idx}::text[])")
        params.append(list(ft_in))
        next_idx += 1

    ca = source_filter.get("commission_authority")
    if isinstance(ca, str) and ca:
        conditions.append(f"d.commission_authority = ${next_idx}")
        params.append(ca)
        next_idx += 1

    tags_any = source_filter.get("topic_tags_any")
    if isinstance(tags_any, (list, tuple)) and tags_any:
        # Match documents whose topic_tags JSONB array contains any of tags_any.
        # Works for both array-shaped and object-shaped JSONB: we coerce to
        # jsonb_array_elements_text and check ANY.
        conditions.append(
            f"""EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(
                    CASE jsonb_typeof(d.topic_tags)
                         WHEN 'array' THEN d.topic_tags
                         ELSE '[]'::jsonb
                    END
                ) t(tag)
                 WHERE t.tag = ANY(${next_idx}::text[])
            )"""
        )
        params.append(list(tags_any))
        next_idx += 1

    case_types = source_filter.get("case_type_in")
    extra_join = ""
    if isinstance(case_types, (list, tuple)) and case_types:
        extra_join = "LEFT JOIN dockets k ON k.docket_id = d.docket_id"
        conditions.append(f"k.case_type = ANY(${next_idx}::text[])")
        params.append(list(case_types))
        next_idx += 1

    case_type_single = source_filter.get("case_type")
    if isinstance(case_type_single, str) and case_type_single:
        if "k." not in extra_join:
            extra_join = "LEFT JOIN dockets k ON k.docket_id = d.docket_id"
        conditions.append(f"k.case_type = ${next_idx}")
        params.append(case_type_single)
        next_idx += 1

    min_mw = source_filter.get("min_capacity_mw")
    if isinstance(min_mw, (int, float)) and min_mw > 0:
        # Soft-match on extracted_fields.capacity_mw if present.
        conditions.append(
            f"""(
                d.extracted_fields IS NULL
                OR COALESCE(
                    (d.extracted_fields->>'capacity_mw')::numeric,
                    (d.extracted_fields->>'mw')::numeric,
                    0
                ) >= ${next_idx}
            )"""
        )
        params.append(float(min_mw))
        next_idx += 1

    sql = f"""
        SELECT d.doc_id, d.title, d.source, d.filing_type, d.source_url,
               d.published_at, d.pages, d.docket_id
          FROM documents d
          {extra_join}
         WHERE {' AND '.join(conditions)}
         ORDER BY d.published_at DESC
         LIMIT 200
    """
    return sql, params


# ---------------------------------------------------------------------------
# LLM summary
# ---------------------------------------------------------------------------

async def _llm_summarise(
    claude: Any,
    alert: Mapping[str, Any],
    docs: list[Mapping[str, Any]],
) -> str:
    """Call Claude Haiku to summarise the matched documents.

    Returns a plain-text summary. Falls back to a deterministic bullet list
    if ``claude`` is None or the API errors — the digest row is still written
    so the user-facing ``/digest`` endpoint keeps working.
    """
    if not docs:
        return "No new documents matched this alert during the current run."

    fallback = _fallback_summary(alert, docs)
    if claude is None:
        return fallback

    prompt = alert.get("llm_prompt") or "Summarise the documents below for a UK energy operator."
    bullets = []
    for i, d in enumerate(docs[:50], start=1):
        published = d.get("published_at")
        published_str = published.isoformat() if hasattr(published, "isoformat") else str(published or "")
        bullets.append(
            f"[{i}] {d.get('title') or '(untitled)'}"
            f"\n    source={d.get('source')} filing_type={d.get('filing_type') or '—'}"
            f"\n    published={published_str} url={d.get('source_url')}"
        )
    user_content = (
        f"Alert: {alert.get('title') or alert.get('slug')}\n"
        f"Instruction: {prompt}\n\n"
        f"Documents ({len(docs)} matched, showing up to 50):\n"
        + "\n".join(bullets)
        + "\n\nWrite a concise digest (<=400 words, no markdown tables, no emojis)."
    )

    try:
        resp = await claude.messages.create(
            model=DIGEST_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_content}],
        )
        out_parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                out_parts.append(block.text)
        text = "\n".join(out_parts).strip()
        return text or fallback
    except Exception as exc:
        log.warning("digest LLM call failed for alert=%s: %s", alert.get("slug"), exc)
        return fallback


def _fallback_summary(alert: Mapping[str, Any], docs: list[Mapping[str, Any]]) -> str:
    lines = [
        f"Digest for {alert.get('title') or alert.get('slug')}",
        f"{len(docs)} new document(s) matched this alert.",
        "",
    ]
    for i, d in enumerate(docs[:20], start=1):
        published = d.get("published_at")
        published_str = published.isoformat() if hasattr(published, "isoformat") else str(published or "")
        lines.append(f"  {i}. {d.get('title') or '(untitled)'} — {d.get('source')} — {published_str}")
    if len(docs) > 20:
        lines.append(f"  … and {len(docs) - 20} more.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

async def run_digest(
    pool: asyncpg.Pool,
    alert_id: str | UUID,
    *,
    claude: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run the digest for *alert_id* once.

    When ``force=False`` (the default) an alert is skipped if a prior digest
    for it ran more recently than its cadence allows. ``force=True`` bypasses
    that check — used by the manual ``POST /api/alerts/run-digest`` dev hook.
    """
    alert_uuid = UUID(str(alert_id))
    async with pool.acquire() as conn:
        alert = await conn.fetchrow(
            """
            SELECT id, slug, title, description, cluster, source_filter,
                   llm_prompt, cadence, est_docs_per_digest, icp_tags
              FROM alert_definitions
             WHERE id = $1
            """,
            alert_uuid,
        )
    if not alert:
        return {"alert_id": str(alert_uuid), "status": "not_found"}

    alert_dict = dict(alert)
    cadence = alert_dict.get("cadence") or "daily"

    # Parse JSONB source_filter — asyncpg returns it as a JSON string.
    sf_raw = alert_dict.get("source_filter")
    if isinstance(sf_raw, str):
        try:
            source_filter = json.loads(sf_raw)
        except Exception:
            source_filter = {}
    elif isinstance(sf_raw, dict):
        source_filter = sf_raw
    else:
        source_filter = {}

    now = datetime.now(timezone.utc)

    # Find the most recent previous run — used as both the cadence gate and
    # the watermark for `published_at > since`.
    async with pool.acquire() as conn:
        last_row = await conn.fetchrow(
            """
            SELECT run_at FROM alert_digests
             WHERE alert_id = $1
             ORDER BY run_at DESC
             LIMIT 1
            """,
            alert_uuid,
        )
    last_run = last_row["run_at"] if last_row else None
    since = last_run or (now - timedelta(days=30))

    if not force and last_run:
        interval = _CADENCE_MIN_INTERVAL.get(cadence, timedelta(hours=23))
        if (now - last_run) < interval:
            return {
                "alert_id": str(alert_uuid),
                "slug": alert_dict.get("slug"),
                "status": "skipped",
                "reason": "not_due",
                "next_due_at": (last_run + interval).isoformat(),
            }

    # Query matching documents
    sql, params = _build_doc_query(source_filter, since)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception as exc:
        log.warning("digest doc query failed for alert=%s: %s", alert_dict.get("slug"), exc)
        rows = []
    docs = [dict(r) for r in rows]

    # LLM extract
    summary = await _llm_summarise(claude, alert_dict, docs)

    # Persist the digest row
    doc_ids = [d["doc_id"] for d in docs]
    async with pool.acquire() as conn:
        digest_row = await conn.fetchrow(
            """
            INSERT INTO alert_digests
                (alert_id, run_at, document_ids, llm_extract, llm_structured)
            VALUES ($1, $2, $3::uuid[], $4, $5::jsonb)
            RETURNING id, alert_id, run_at, document_ids, llm_extract, sent_at
            """,
            alert_uuid,
            now,
            doc_ids,
            summary,
            json.dumps({
                "document_count": len(docs),
                "titles": [d.get("title") for d in docs[:20]],
                "cadence": cadence,
                "source_filter": source_filter,
            }),
        )
    digest_dict = dict(digest_row)

    # Deliver to every active subscription
    delivery_results: list[dict[str, Any]] = []
    sent_count = 0
    try:
        async with pool.acquire() as conn:
            subs = await conn.fetch(
                """
                SELECT s.id AS sub_id, s.user_id, s.delivery_channels,
                       s.pinned_project_id
                  FROM alert_subscriptions s
                 WHERE s.alert_id = $1
                   AND s.muted = FALSE
                """,
                alert_uuid,
            )
        for s in subs:
            channels_raw = s["delivery_channels"]
            if isinstance(channels_raw, str):
                try:
                    channels = json.loads(channels_raw)
                except Exception:
                    channels = {"email": True, "in_app": True, "slack": False}
            elif isinstance(channels_raw, dict):
                channels = channels_raw
            else:
                channels = {"email": True, "in_app": True, "slack": False}

            try:
                r = await deliver_digest(
                    pool,
                    user_id=s["user_id"],
                    alert=alert_dict,
                    digest=digest_dict,
                    delivery_channels=channels,
                    slack_webhook_url=channels.get("slack_webhook_url"),
                )
                delivery_results.extend(r)
                sent_count += 1
            except Exception as exc:
                log.warning("delivery failed for sub=%s: %s", s["sub_id"], exc)
    except Exception as exc:
        log.warning("sub-fanout query failed for alert=%s: %s", alert_dict.get("slug"), exc)

    # Mark sent_at on the digest row if anything was delivered
    if sent_count:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE alert_digests SET sent_at = NOW() WHERE id = $1",
                    digest_dict["id"],
                )
        except Exception:
            pass

    return {
        "alert_id": str(alert_uuid),
        "slug": alert_dict.get("slug"),
        "status": "ok",
        "digest_id": str(digest_dict["id"]),
        "document_count": len(docs),
        "subscriptions_delivered": sent_count,
        "delivery_results": delivery_results,
    }


async def run_all_due_digests(
    pool: asyncpg.Pool,
    *,
    claude: Any = None,
    cadences: list[str] | None = None,
) -> dict[str, Any]:
    """Scan every alert definition and run the digest for each that is due.

    Pass ``cadences=['daily']`` (or similar) to only run a subset — useful
    when the ingestion scheduler wants to split the sweep across crons.
    """
    try:
        async with pool.acquire() as conn:
            if cadences:
                alert_rows = await conn.fetch(
                    "SELECT id, slug, cadence FROM alert_definitions WHERE cadence = ANY($1::text[])",
                    list(cadences),
                )
            else:
                alert_rows = await conn.fetch(
                    "SELECT id, slug, cadence FROM alert_definitions"
                )
    except Exception as exc:
        log.warning("run_all_due_digests: alert enumeration failed: %s", exc)
        return {"status": "failed", "reason": str(exc)[:200], "results": []}

    results = []
    for r in alert_rows:
        try:
            res = await run_digest(pool, r["id"], claude=claude, force=False)
        except Exception as exc:
            log.exception("run_digest failed for %s: %s", r["slug"], exc)
            res = {"alert_id": str(r["id"]), "slug": r["slug"], "status": "error", "reason": str(exc)[:200]}
        results.append(res)

    ok = sum(1 for r in results if r.get("status") == "ok")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    errored = sum(1 for r in results if r.get("status") not in ("ok", "skipped"))
    return {
        "status": "ok",
        "total": len(results),
        "ran": ok,
        "skipped": skipped,
        "errored": errored,
        "results": results,
    }


__all__ = [
    "DIGEST_MODEL",
    "run_digest",
    "run_all_due_digests",
]
