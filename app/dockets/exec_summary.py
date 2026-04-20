"""
app/dockets/exec_summary.py — Claude-driven executive-summary refresh.

A docket grows every day — new relreps, deadline extensions, stakeholder
responses, authority decisions. Users need a 30-second read that they
can trust. ``refresh(docket_id)`` collects up to 40 recent documents,
ships them to Claude Sonnet in JSON-mode, and persists the result:

- ``dockets.exec_summary_text`` / ``exec_summary_cached_at``
- ``docket_timeline_events`` — any forward-looking deadlines Claude picks up
- ``docket_qa_cache``         — pre-computed answers to the questions
                                Claude suggests

The returned ``DocketExecSummary`` is what the router sends to the
frontend, including progress events when called from an SSE endpoint.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, AsyncIterator
from uuid import UUID

import anthropic
import asyncpg

log = logging.getLogger("princeps.dockets.exec_summary")

MODEL_SONNET = os.environ.get("CLAUDE_DOCKET_MODEL", "claude-sonnet-4-6")

MAX_DOCS_PER_RUN = 40
CHARS_PER_DOC    = 2000


@dataclass
class DocketExecSummary:
    docket_id: str
    exec_summary_text: str
    stakeholders_extracted: list[dict[str, Any]] = field(default_factory=list)
    timeline_events_extracted: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)
    n_docs_used: int = 0


_SYSTEM_PROMPT = """You are a UK energy-sector regulatory analyst. You summarise
proceedings (NSIP DCOs, Ofgem code modifications, LPA planning, CfD rounds,
s36, DCO Examinations). Output strict JSON matching the supplied schema.
Tone: precise, concise, no marketing language. When a date appears in the
source text, preserve ISO 8601. When you cite a document, use the numeric
index [n] that the user provided."""


_USER_TEMPLATE = """Here is the most-recent document batch for a single docket.
Each entry is prefixed with [n] — use that index when you cite.

---
{doc_block}
---

Return strictly valid JSON in this shape:

{{
  "exec_summary_text": "1000-char executive summary. Cover: what it is, stage, key applicant, latest movement, statutory deadline, biggest contested issue. End with a one-sentence 'why the reader should care'.",
  "stakeholders_extracted": [
    {{"display_name": "...", "role": "applicant|statutory_consultee|lpa|...",
      "position": "for|against|conditions|neutral|unknown", "citation_doc_index": 2}}
  ],
  "timeline_events_extracted": [
    {{"event_type": "deadline|decision|acceptance|relrep_deadline|...",
      "event_at": "YYYY-MM-DD", "summary_text": "...",
      "forward_looking": true, "deadline_at": "YYYY-MM-DD or null",
      "citation_doc_index": 1}}
  ],
  "questions": [
    {{"question": "What is the 2026 examination timetable?",
      "answer": "The ExA issued Rule 8 on 2026-03-15 with DL1 on 2026-04-07...",
      "citations": [0, 3]}}
  ]
}}

Emit 3-6 questions covering the most common developer/lender/advisor concerns:
next deadline, key objections, contested issue, decision likelihood."""


def _fmt_doc_block(docs: list[dict[str, Any]]) -> str:
    """Inline up to MAX_DOCS_PER_RUN docs, truncated to CHARS_PER_DOC."""
    chunks: list[str] = []
    for i, d in enumerate(docs):
        body = d.get("body_text") or ""
        if len(body) > CHARS_PER_DOC:
            body = body[:CHARS_PER_DOC] + "…"
        published = d.get("published_at")
        published_str = published.isoformat() if hasattr(published, "isoformat") else str(published or "")
        filing_type = d.get("filing_type") or ""
        stage = d.get("procedural_stage") or ""
        title = (d.get("title") or "").strip()
        chunks.append(
            f"[{i}] {title}\n"
            f"    published={published_str} type={filing_type} stage={stage}\n"
            f"    {body}\n"
        )
    return "\n".join(chunks)


async def _fetch_doc_batch(
    conn: asyncpg.Connection, docket_id: UUID, limit: int = MAX_DOCS_PER_RUN
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT doc_id, title, body_text, filing_type, procedural_stage,
               published_at, source_url
        FROM documents
        WHERE docket_id = $1
        ORDER BY published_at DESC NULLS LAST, ingested_at DESC
        LIMIT $2
        """,
        docket_id, limit,
    )
    return [dict(r) for r in rows]


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


async def _persist(
    pool: asyncpg.Pool,
    docket_id: UUID,
    result: DocketExecSummary,
    docs: list[dict[str, Any]],
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. dockets row
            await conn.execute(
                """UPDATE dockets
                   SET exec_summary_text = $1,
                       exec_summary_cached_at = now(),
                       updated_at = now()
                   WHERE docket_id = $2""",
                result.exec_summary_text, docket_id,
            )

            # 2. timeline events — upsert forward-looking ones.
            for ev in result.timeline_events_extracted:
                ev_at = _coerce_date(ev.get("event_at"))
                if not ev_at:
                    continue
                deadline_at = _coerce_date(ev.get("deadline_at"))
                citation_idx = ev.get("citation_doc_index")
                cite_doc_id: UUID | None = None
                if isinstance(citation_idx, int) and 0 <= citation_idx < len(docs):
                    cite_doc_id = docs[citation_idx].get("doc_id")

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
                    log.debug("timeline upsert skipped: %s", exc)

            # 3. QA cache — precompute answers the exec summary generated.
            for q in result.questions:
                question = (q.get("question") or "").strip()
                answer = (q.get("answer") or "").strip()
                if not question or not answer:
                    continue
                citations = q.get("citations") or []
                citation_doc_ids: list[str] = []
                for idx in citations:
                    if isinstance(idx, int) and 0 <= idx < len(docs):
                        doc_id_v = docs[idx].get("doc_id")
                        if doc_id_v:
                            citation_doc_ids.append(str(doc_id_v))
                try:
                    await conn.execute(
                        """
                        INSERT INTO docket_qa_cache
                            (docket_id, question, answer, citations)
                        VALUES ($1, $2, $3, $4::jsonb)
                        ON CONFLICT (docket_id, question) DO UPDATE SET
                            answer = EXCLUDED.answer,
                            citations = EXCLUDED.citations,
                            generated_at = now()
                        """,
                        docket_id,
                        question,
                        answer,
                        json.dumps({"doc_ids": citation_doc_ids, "indices": citations}),
                    )
                except Exception as exc:
                    log.debug("qa_cache upsert skipped: %s", exc)


async def refresh(
    pool: asyncpg.Pool,
    claude: anthropic.AsyncAnthropic,
    docket_id: UUID | str,
) -> DocketExecSummary:
    """One-shot refresh: returns the structured result (non-streaming).

    For the streaming router use ``refresh_stream`` which yields SSE
    progress events before the final payload.
    """
    if isinstance(docket_id, str):
        docket_id = UUID(docket_id)

    async with pool.acquire() as conn:
        docs = await _fetch_doc_batch(conn, docket_id)
    if not docs:
        empty = DocketExecSummary(
            docket_id=str(docket_id),
            exec_summary_text="(No documents ingested for this docket yet.)",
            n_docs_used=0,
        )
        return empty

    user_msg = _USER_TEMPLATE.format(doc_block=_fmt_doc_block(docs))
    resp = await claude.messages.create(
        model=MODEL_SONNET,
        max_tokens=2500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
    )

    data = _parse_json_lenient(raw)
    result = DocketExecSummary(
        docket_id=str(docket_id),
        exec_summary_text=(data.get("exec_summary_text") or "").strip()
            or "(Summary unavailable — model output did not include exec_summary_text.)",
        stakeholders_extracted=data.get("stakeholders_extracted") or [],
        timeline_events_extracted=data.get("timeline_events_extracted") or [],
        questions=data.get("questions") or [],
        n_docs_used=len(docs),
    )

    await _persist(pool, docket_id, result, docs)
    return result


def _parse_json_lenient(raw: str) -> dict[str, Any]:
    """Claude sometimes wraps JSON in ```json ... ``` fences. Be forgiving."""
    if not raw:
        return {}
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)
        if len(s) >= 2:
            body = s[1]
            if body.lstrip().startswith("json"):
                body = body.split("\n", 1)[1] if "\n" in body else ""
            # rejoin remaining fences if any
            s = body.split("```", 1)[0]
        else:
            s = raw
    try:
        return json.loads(s)
    except Exception:
        # Last-ditch: find the first { ... } block.
        import re as _re
        m = _re.search(r"\{.*\}", s, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}


# ── Streaming variant for SSE routers ──────────────────────────────────

async def refresh_stream(
    pool: asyncpg.Pool,
    claude: anthropic.AsyncAnthropic,
    docket_id: UUID | str,
) -> AsyncIterator[str]:
    """Yield SSE-formatted progress events + final payload.

    The route handler wraps this in a ``StreamingResponse``."""
    yield _sse({"type": "progress", "stage": "loading_docs"})

    if isinstance(docket_id, str):
        docket_id = UUID(docket_id)

    async with pool.acquire() as conn:
        docs = await _fetch_doc_batch(conn, docket_id)

    yield _sse({"type": "progress", "stage": "prompting_claude", "n_docs": len(docs)})

    if not docs:
        yield _sse({"type": "final", "payload": {
            "docket_id": str(docket_id),
            "exec_summary_text": "(No documents ingested yet.)",
            "n_docs_used": 0,
            "stakeholders_extracted": [],
            "timeline_events_extracted": [],
            "questions": [],
        }})
        yield _sse({"type": "done"})
        return

    user_msg = _USER_TEMPLATE.format(doc_block=_fmt_doc_block(docs))

    # Stream text so we can surface a "thinking" signal to the UI, but we
    # still need the full text to parse JSON at the end.
    chunks: list[str] = []
    try:
        async with claude.messages.stream(
            model=MODEL_SONNET,
            max_tokens=2500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        ) as stream:
            async for event in stream:
                et = getattr(event, "type", None)
                if et == "content_block_delta":
                    delta = getattr(event.delta, "text", None)
                    if delta:
                        chunks.append(delta)
                        yield _sse({"type": "text_delta", "content": delta})
    except Exception as exc:
        log.exception("refresh_stream: claude failed: %s", exc)
        yield _sse({"type": "error", "message": str(exc)[:500]})
        yield _sse({"type": "done"})
        return

    raw = "".join(chunks)
    data = _parse_json_lenient(raw)
    result = DocketExecSummary(
        docket_id=str(docket_id),
        exec_summary_text=(data.get("exec_summary_text") or "").strip()
            or "(Summary unavailable.)",
        stakeholders_extracted=data.get("stakeholders_extracted") or [],
        timeline_events_extracted=data.get("timeline_events_extracted") or [],
        questions=data.get("questions") or [],
        n_docs_used=len(docs),
    )

    yield _sse({"type": "progress", "stage": "persisting"})
    try:
        await _persist(pool, docket_id, result, docs)
    except Exception as exc:
        log.exception("refresh_stream: persist failed: %s", exc)
        yield _sse({"type": "error", "message": f"persist failed: {exc}"})

    yield _sse({
        "type": "final",
        "payload": {
            "docket_id": result.docket_id,
            "exec_summary_text": result.exec_summary_text,
            "n_docs_used": result.n_docs_used,
            "stakeholders_extracted": result.stakeholders_extracted,
            "timeline_events_extracted": result.timeline_events_extracted,
            "questions": result.questions,
        },
    })
    yield _sse({"type": "done"})


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


__all__ = ["refresh", "refresh_stream", "DocketExecSummary", "MODEL_SONNET"]
