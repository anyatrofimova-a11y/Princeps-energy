"""
app/dockets/timeline_extractor.py — Claude-assisted docket timeline extraction.

Pull forward-looking deadlines, hearing dates, decision windows and
statutory clocks out of a document batch. Results validate against
``DocketTimelineEvent`` before persistence.

Used by:
- ``exec_summary.refresh()`` — embedded JSON schema within the summary call.
- Standalone batch ingesters — call ``extract_events_from_docs()`` for
  a focused pass that writes to ``docket_timeline_events`` without touching
  the exec summary.

Statutory clocks encoded as reason strings for the router to annotate:
- ExA examination clock: 6 months from Preliminary Meeting (Planning Act 2008 s.98)
- SoS decision clock:    3 months from ExA report (Planning Act 2008 s.107)
- Ofgem code mod:        28-day minimum consultation (Electricity Act s.49)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

import anthropic
import asyncpg

from app.models.intelligence import DocketTimelineEvent

log = logging.getLogger("princeps.dockets.timeline_extractor")

MODEL_SONNET = os.environ.get("CLAUDE_DOCKET_MODEL", "claude-sonnet-4-6")


STATUTORY_CLOCKS: dict[str, dict[str, Any]] = {
    "exa_examination": {
        "label": "ExA examination (6 months)",
        "days": 183,
        "basis": "Planning Act 2008 s.98",
    },
    "sos_decision": {
        "label": "SoS decision (3 months from ExA report)",
        "days": 92,
        "basis": "Planning Act 2008 s.107",
    },
    "ofgem_code_mod": {
        "label": "Ofgem code modification consultation (28 days)",
        "days": 28,
        "basis": "Electricity Act 1989 s.49",
    },
    "lpa_determination": {
        "label": "LPA determination (8 weeks minor / 13 weeks major / 16 weeks EIA)",
        "days": 91,
        "basis": "DMPO 2015 art.34",
    },
    "dns_welsh": {
        "label": "DNS Welsh Ministers decision (36 weeks)",
        "days": 252,
        "basis": "Welsh DNS Order 2016",
    },
}


_SYSTEM = """You extract dated events from UK energy proceedings documents.
Output strict JSON. For every dated event in the supplied batch, emit one
entry:
  {"event_type": "relrep_deadline|preliminary_meeting|dl1|dl2|..."
                 "|exa_report|sos_decision|examination_start|"
                 "consultation_deadline|decision|acceptance|rule_8|",
   "event_at":    "YYYY-MM-DD",
   "summary_text": "one-line",
   "forward_looking": true/false,
   "deadline_at": "YYYY-MM-DD or null",
   "citation_doc_index": integer}

Be conservative: don't invent dates. Preserve whether the date is past
(forward_looking=false) or future (forward_looking=true) from today's
perspective. Use the provided [n] indices for citations."""

_USER = """Today: {today}

{doc_block}

Return JSON: {{"events": [...]}}"""


@dataclass
class TimelineExtractionResult:
    docket_id: str
    events: list[dict[str, Any]]
    n_docs_used: int
    annotated_clocks: list[dict[str, Any]]


def _fmt_doc_block(docs: list[dict[str, Any]], chars_per_doc: int = 1500) -> str:
    chunks: list[str] = []
    for i, d in enumerate(docs):
        body = (d.get("body_text") or "")[:chars_per_doc]
        published = d.get("published_at")
        ps = published.isoformat() if hasattr(published, "isoformat") else (str(published or ""))
        chunks.append(
            f"[{i}] {d.get('title','(untitled)')}\n"
            f"    published={ps} type={d.get('filing_type','')}\n"
            f"    {body}\n"
        )
    return "\n".join(chunks)


def _annotate_clocks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a human-readable statutory clock hint to each event whose
    event_type / summary_text matches one of the known clocks. Pure —
    doesn't touch the DB."""
    annotated: list[dict[str, Any]] = []
    for ev in events:
        et = (ev.get("event_type") or "").lower()
        summary = (ev.get("summary_text") or "").lower()
        clock_key: str | None = None
        if et in ("preliminary_meeting", "examination_start"):
            clock_key = "exa_examination"
        elif et in ("exa_report",):
            clock_key = "sos_decision"
        elif et in ("consultation_deadline",) and "ofgem" in summary:
            clock_key = "ofgem_code_mod"
        elif et in ("lpa_determination", "target_decision_date"):
            clock_key = "lpa_determination"
        elif et in ("dns_decision",):
            clock_key = "dns_welsh"

        if clock_key:
            annotated.append({
                **ev,
                "statutory_clock": STATUTORY_CLOCKS[clock_key] | {"key": clock_key},
            })
        else:
            annotated.append(ev)
    return annotated


def _coerce_date(val: Any) -> date | None:
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str) and val:
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


async def extract_events_from_docs(
    pool: asyncpg.Pool,
    claude: anthropic.AsyncAnthropic,
    docket_id: UUID | str,
    doc_limit: int = 40,
    persist: bool = True,
) -> TimelineExtractionResult:
    """Pull timeline events from the most-recent ``doc_limit`` docs on a
    docket. Persists to ``docket_timeline_events`` unless ``persist=False``.
    """
    if isinstance(docket_id, str):
        docket_id = UUID(docket_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT doc_id, title, body_text, filing_type, published_at
               FROM documents
               WHERE docket_id = $1
               ORDER BY published_at DESC NULLS LAST, ingested_at DESC
               LIMIT $2""",
            docket_id, doc_limit,
        )
    docs = [dict(r) for r in rows]
    if not docs:
        return TimelineExtractionResult(str(docket_id), [], 0, [])

    try:
        resp = await claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=2000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _USER.format(
                today=date.today().isoformat(),
                doc_block=_fmt_doc_block(docs),
            )}],
        )
        raw = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", "") == "text"
        )
    except Exception as exc:
        log.warning("timeline extraction: Claude call failed: %s", exc)
        return TimelineExtractionResult(str(docket_id), [], len(docs), [])

    try:
        events = json.loads(_strip_fence(raw)).get("events") or []
    except Exception:
        log.debug("timeline extract: JSON parse failed on %s chars", len(raw))
        events = []

    annotated = _annotate_clocks(events)

    if persist:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for ev in events:
                    ev_at = _coerce_date(ev.get("event_at"))
                    if not ev_at:
                        continue
                    deadline_at = _coerce_date(ev.get("deadline_at"))
                    idx = ev.get("citation_doc_index")
                    cite_doc_id: UUID | None = None
                    if isinstance(idx, int) and 0 <= idx < len(docs):
                        cite_doc_id = docs[idx].get("doc_id")

                    # Model-level validation (best-effort).
                    try:
                        DocketTimelineEvent(
                            docket_id=docket_id,
                            event_type=str(ev.get("event_type") or "event"),
                            event_at=ev_at,
                            summary_text=ev.get("summary_text"),
                            doc_id=cite_doc_id,
                            forward_looking=bool(ev.get("forward_looking", False)),
                            deadline_at=deadline_at,
                        )
                    except Exception as ve:
                        log.debug("timeline: pydantic reject: %s", ve)
                        continue

                    try:
                        await conn.execute(
                            """
                            INSERT INTO docket_timeline_events
                                (docket_id, event_type, event_at, summary_text,
                                 doc_id, forward_looking, deadline_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            docket_id,
                            str(ev.get("event_type") or "event"),
                            ev_at,
                            ev.get("summary_text"),
                            cite_doc_id,
                            bool(ev.get("forward_looking", False)),
                            deadline_at,
                        )
                    except Exception as exc:
                        log.debug("timeline insert skipped: %s", exc)

    return TimelineExtractionResult(
        str(docket_id), annotated, len(docs), annotated,
    )


def _strip_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        parts = s.split("```", 2)
        if len(parts) >= 2:
            body = parts[1]
            if body.lstrip().startswith("json"):
                body = body.split("\n", 1)[1] if "\n" in body else ""
            return body.split("```", 1)[0]
    return s


__all__ = [
    "extract_events_from_docs",
    "TimelineExtractionResult",
    "STATUTORY_CLOCKS",
]
