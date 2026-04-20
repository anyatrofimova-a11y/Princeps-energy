"""
app/routers/dockets.py — Princeps Dockets router.

The docket is the primary unit of UK energy proceedings. Every endpoint
in this router operates on a single docket OR the filterable library of
dockets.

All list endpoints support cursor pagination (``cursor`` is an opaque
base64 of ``updated_at + docket_id`` — callers should treat it as
opaque).

SSE endpoints:
- POST /{id}/summary/refresh   — Claude Sonnet exec summary rebuild.
- POST /{id}/question          — streamed QA with `[n]` citations +
                                  write-through to docket_qa_cache.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import time
from datetime import date, datetime
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.deps import get_pool, get_claude, get_current_user
from app.dockets.exec_summary import refresh_stream, MODEL_SONNET

log = logging.getLogger("princeps.routers.dockets")

router = APIRouter(prefix="/api/dockets", tags=["dockets"])


# ── Helpers ────────────────────────────────────────────────────────────

_SHARE_SECRET = os.environ.get(
    "PRINCEPS_SHARE_SECRET", "princeps-dev-secret-change-me"
).encode()


def _sign_docket_share(docket_id: str, expires_ts: int) -> str:
    payload = f"docket.{docket_id}.{expires_ts}".encode()
    sig = hmac.new(_SHARE_SECRET, payload, hashlib.sha256).digest()[:12]
    token = base64.urlsafe_b64encode(payload + b"." + sig).decode().rstrip("=")
    return token


def _verify_docket_share(token: str) -> str | None:
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        kind_b, docket_id_b, expires_b, sig = raw.rsplit(b".", 3)
        if kind_b != b"docket":
            return None
        docket_id = docket_id_b.decode()
        expires_ts = int(expires_b.decode())
        expected = hmac.new(
            _SHARE_SECRET,
            f"docket.{docket_id}.{expires_ts}".encode(),
            hashlib.sha256,
        ).digest()[:12]
        if not hmac.compare_digest(sig, expected):
            return None
        if time.time() > expires_ts:
            return None
        return docket_id
    except Exception:
        return None


def _encode_cursor(updated_at: datetime | None, docket_id: UUID) -> str:
    payload = {
        "u": updated_at.isoformat() if updated_at else None,
        "d": str(docket_id),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, default=str).encode()
    ).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if not cursor:
        return None, None
    try:
        pad = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad))
        ua_raw = payload.get("u")
        ua = datetime.fromisoformat(ua_raw) if ua_raw else None
        return ua, payload.get("d")
    except Exception:
        return None, None


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


async def _require_docket(conn: asyncpg.Connection, docket_id: str) -> dict[str, Any]:
    try:
        did = UUID(docket_id)
    except ValueError:
        raise HTTPException(400, "docket_id must be a UUID")
    row = await conn.fetchrow(
        """SELECT d.*, a.name AS publisher_name, a.acronym AS publisher_acronym,
                  a.logo_url AS publisher_logo
           FROM dockets d LEFT JOIN authorities a ON a.id = d.publisher_id
           WHERE d.docket_id = $1""",
        did,
    )
    if not row:
        raise HTTPException(404, "docket not found")
    return dict(row)


def _docket_summary_dict(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "docket_id":            str(r["docket_id"]),
        "source":               r["source"],
        "source_docket_id":     r["source_docket_id"],
        "title":                r["title"],
        "description":          r.get("description"),
        "case_type":            r["case_type"],
        "industry":             r.get("industry"),
        "status":               r.get("status"),
        "stage":                r.get("stage"),
        "applicant_name":       r.get("applicant_name"),
        "statutory_deadline":   r["statutory_deadline"].isoformat()
            if r.get("statutory_deadline") else None,
        "opened_at":            r["opened_at"].isoformat()
            if r.get("opened_at") else None,
        "updated_at":           r["updated_at"].isoformat()
            if r.get("updated_at") else None,
        "publisher": ({
            "name":     r.get("publisher_name"),
            "acronym":  r.get("publisher_acronym"),
            "logo_url": r.get("publisher_logo"),
        } if r.get("publisher_name") else None),
    }


# ═══════════════════════════════════════════════════════════════════════
# 1) GET /api/dockets/library — filtered list
# ═══════════════════════════════════════════════════════════════════════

@router.get("/library")
async def library(
    request: Request,
    case_type: str | None = Query(None),
    publisher: str | None = Query(None, description="Authority slug."),
    status: str | None = Query(None),
    region: str | None = Query(None, description="UK region / devolved nation (E/W/S/NI)."),
    industry: str | None = Query(None),
    tech: str | None = Query(None, description="(reserved — tech tag not yet on dockets table)"),
    capacity_band: str | None = Query(None, description="s|m|l|xl — reserved"),
    date_from: date | None = Query(None),
    q: str | None = Query(None, description="free-text on title + applicant"),
    cursor: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Filtered library view with keyset pagination."""
    where: list[str] = ["1=1"]
    params: list[Any] = []

    def _next_param(val: Any) -> str:
        params.append(val)
        return f"${len(params)}"

    if case_type:
        where.append(f"d.case_type = {_next_param(case_type)}")
    if industry:
        where.append(f"d.industry = {_next_param(industry)}")
    if status:
        where.append(f"d.status = {_next_param(status)}")
    if publisher:
        where.append(f"a.slug = {_next_param(publisher)}")
    if region:
        where.append(f"a.jurisdiction = {_next_param(region)}")
    if date_from:
        where.append(f"d.opened_at >= {_next_param(date_from)}")
    if q:
        where.append(
            f"(d.title ILIKE {_next_param(f'%{q}%')} "
            f"OR d.applicant_name ILIKE {_next_param(f'%{q}%')})"
        )

    cursor_ua, cursor_did = _decode_cursor(cursor)
    if cursor_ua and cursor_did:
        where.append(
            f"(d.updated_at, d.docket_id) < ({_next_param(cursor_ua)}, "
            f"{_next_param(UUID(cursor_did))})"
        )

    sql = f"""
        SELECT d.*, a.name AS publisher_name, a.acronym AS publisher_acronym,
               a.logo_url AS publisher_logo,
               (SELECT count(*) FROM documents dc WHERE dc.docket_id = d.docket_id)
                 AS n_documents
        FROM dockets d LEFT JOIN authorities a ON a.id = d.publisher_id
        WHERE {' AND '.join(where)}
        ORDER BY d.updated_at DESC NULLS LAST, d.docket_id DESC
        LIMIT {limit + 1}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    items: list[dict[str, Any]] = []
    for r in rows[:limit]:
        base = _docket_summary_dict(dict(r))
        base["n_documents"] = int(r["n_documents"] or 0)
        items.append(base)

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["updated_at"], last["docket_id"])

    return {
        "items": items,
        "next_cursor": next_cursor,
        "count": len(items),
    }


# ═══════════════════════════════════════════════════════════════════════
# 2) GET /api/dockets/{docket_id}
# ═══════════════════════════════════════════════════════════════════════

@router.get("/{docket_id}")
async def docket_detail(
    docket_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Detail view: docket row + next 3 deadlines + stakeholder roles
    + document count."""
    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        # Next 3 forward-looking deadlines.
        deadlines = await conn.fetch(
            """SELECT event_type, event_at, summary_text, deadline_at,
                      forward_looking
               FROM docket_timeline_events
               WHERE docket_id = $1
                 AND (forward_looking = true OR event_at >= $2)
               ORDER BY event_at ASC LIMIT 3""",
            did, date.today(),
        )

        # Stakeholder role breakdown.
        role_rows = await conn.fetch(
            """SELECT role, position, count(*) AS n
               FROM stakeholders
               WHERE docket_id = $1
               GROUP BY role, position
               ORDER BY n DESC""",
            did,
        )

        n_docs = await conn.fetchval(
            "SELECT count(*) FROM documents WHERE docket_id = $1", did,
        ) or 0

    role_breakdown: dict[str, dict[str, int]] = {}
    for r in role_rows:
        role_breakdown.setdefault(r["role"], {})[r["position"] or "unknown"] = int(r["n"])

    return {
        **_docket_summary_dict(d),
        "exec_summary_text":       d.get("exec_summary_text"),
        "exec_summary_cached_at":  d["exec_summary_cached_at"].isoformat()
            if d.get("exec_summary_cached_at") else None,
        "next_deadlines": [
            {
                "event_type":   r["event_type"],
                "event_at":     r["event_at"].isoformat() if r["event_at"] else None,
                "summary_text": r["summary_text"],
                "deadline_at":  r["deadline_at"].isoformat() if r["deadline_at"] else None,
                "forward_looking": bool(r["forward_looking"]),
            }
            for r in deadlines
        ],
        "stakeholder_role_breakdown": role_breakdown,
        "n_documents":                int(n_docs),
    }


# ═══════════════════════════════════════════════════════════════════════
# 3) GET /api/dockets/{docket_id}/stakeholders — React Flow shape
# ═══════════════════════════════════════════════════════════════════════

@router.get("/{docket_id}/stakeholders")
async def docket_stakeholders(
    docket_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Graph payload: `{nodes, edges, roles}`.

    - ``nodes``: per-stakeholder — display_name, role, position,
      submission_count, authority logo.
    - ``edges``: A→B if B's submission references a doc authored by A
      (proxy: same docket + author chain via documents.stakeholder_id
      and stakeholder_submissions).
    - ``roles``: aggregate count per role (for the legend).
    """
    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        stake_rows = await conn.fetch(
            """SELECT s.id, s.display_name, s.role, s.position,
                      s.submission_count, s.first_submission_at,
                      s.last_submission_at, s.authority_id,
                      a.name AS authority_name, a.logo_url AS authority_logo
               FROM stakeholders s
               LEFT JOIN authorities a ON a.id = s.authority_id
               WHERE s.docket_id = $1
               ORDER BY s.submission_count DESC NULLS LAST""",
            did,
        )
        nodes = [
            {
                "id":               str(r["id"]),
                "display_name":     r["display_name"],
                "role":             r["role"],
                "position":         r["position"],
                "submission_count": int(r["submission_count"] or 0),
                "first_submission_at": r["first_submission_at"].isoformat()
                    if r["first_submission_at"] else None,
                "last_submission_at":  r["last_submission_at"].isoformat()
                    if r["last_submission_at"] else None,
                "authority": ({
                    "id":       str(r["authority_id"]),
                    "name":     r["authority_name"],
                    "logo_url": r["authority_logo"],
                } if r["authority_id"] else None),
            }
            for r in stake_rows
        ]

        # Edges: where B's submission cites A's doc. Heuristic:
        #   if stakeholder B submitted a doc whose body_text contains
        #   the display_name of stakeholder A, add edge A -> B.
        # Lightweight version: join via documents table +
        # position_change in stakeholder_submissions.
        edge_rows = await conn.fetch(
            """
            WITH sub AS (
                SELECT ss.stakeholder_id AS b_id, ss.doc_id, ss.submitted_at,
                       s_b.display_name AS b_name
                FROM stakeholder_submissions ss
                JOIN stakeholders s_b ON s_b.id = ss.stakeholder_id
                WHERE s_b.docket_id = $1
            )
            SELECT DISTINCT s_a.id AS a_id, sub.b_id
            FROM sub
            JOIN documents d ON d.doc_id = sub.doc_id
            JOIN stakeholders s_a ON s_a.docket_id = $1
              AND s_a.id <> sub.b_id
              AND d.body_text IS NOT NULL
              AND position(lower(s_a.display_name) IN lower(d.body_text)) > 0
            """,
            did,
        )
        edges = [
            {"id": f"{r['a_id']}->{r['b_id']}",
             "source": str(r["a_id"]), "target": str(r["b_id"])}
            for r in edge_rows
        ]

        role_agg = await conn.fetch(
            """SELECT role, count(*) AS n FROM stakeholders
               WHERE docket_id = $1 GROUP BY role ORDER BY n DESC""",
            did,
        )
        roles = [{"role": r["role"], "count": int(r["n"])} for r in role_agg]

    return {"nodes": nodes, "edges": edges, "roles": roles}


# ═══════════════════════════════════════════════════════════════════════
# 4) GET /api/dockets/{id}/timeline
# ═══════════════════════════════════════════════════════════════════════

_STATUTORY_CLOCKS_ANNOTATIONS = {
    "exa_examination": "ExA examination — 6-month clock (PA 2008 s.98)",
    "sos_decision":    "SoS decision — 3-month clock (PA 2008 s.107)",
    "ofgem_code_mod":  "Ofgem code modification — 28-day consultation minimum",
    "lpa_determination": "LPA determination — 8/13/16-week DMPO clock",
}


@router.get("/{docket_id}/timeline")
async def docket_timeline(
    docket_id: str,
    window: str = Query("all", pattern="^(past|upcoming|all)$"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        where = "docket_id = $1"
        params: list[Any] = [did]
        if window == "past":
            where += " AND event_at < $2"
            params.append(date.today())
        elif window == "upcoming":
            where += " AND (event_at >= $2 OR forward_looking = true)"
            params.append(date.today())

        rows = await conn.fetch(
            f"""SELECT id, event_type, event_at, summary_text, doc_id,
                       forward_looking, deadline_at
                FROM docket_timeline_events
                WHERE {where}
                ORDER BY event_at ASC""",
            *params,
        )

    def _annotate(r: dict[str, Any]) -> str | None:
        et = (r["event_type"] or "").lower()
        if et in ("preliminary_meeting", "examination_start"):
            return _STATUTORY_CLOCKS_ANNOTATIONS["exa_examination"]
        if et == "exa_report":
            return _STATUTORY_CLOCKS_ANNOTATIONS["sos_decision"]
        if et == "consultation_deadline":
            return _STATUTORY_CLOCKS_ANNOTATIONS["ofgem_code_mod"]
        if et in ("lpa_determination", "target_decision_date"):
            return _STATUTORY_CLOCKS_ANNOTATIONS["lpa_determination"]
        return None

    return {
        "items": [
            {
                "id":               str(r["id"]),
                "event_type":       r["event_type"],
                "event_at":         r["event_at"].isoformat() if r["event_at"] else None,
                "summary_text":     r["summary_text"],
                "doc_id":           str(r["doc_id"]) if r["doc_id"] else None,
                "forward_looking":  bool(r["forward_looking"]),
                "deadline_at":      r["deadline_at"].isoformat() if r["deadline_at"] else None,
                "statutory_clock":  _annotate(dict(r)),
            }
            for r in rows
        ],
        "window": window,
    }


# ═══════════════════════════════════════════════════════════════════════
# 5) GET /api/dockets/{id}/documents
# ═══════════════════════════════════════════════════════════════════════

@router.get("/{docket_id}/documents")
async def docket_documents(
    docket_id: str,
    stage: str | None = Query(None),
    stakeholder_id: str | None = Query(None),
    type: str | None = Query(None, description="filing_type filter"),
    q: str | None = Query(None, description="full-text via tsv"),
    cursor: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        where = ["docket_id = $1"]
        params: list[Any] = [did]

        def _next(v: Any) -> str:
            params.append(v)
            return f"${len(params)}"

        if stage:
            where.append(f"procedural_stage = {_next(stage)}")
        if type:
            where.append(f"filing_type = {_next(type)}")
        if stakeholder_id:
            try:
                where.append(f"stakeholder_id = {_next(UUID(stakeholder_id))}")
            except ValueError:
                raise HTTPException(400, "stakeholder_id must be a UUID")
        if q:
            where.append(f"tsv @@ plainto_tsquery('english', {_next(q)})")

        cur_ua, cur_id = _decode_cursor(cursor)
        if cur_ua and cur_id:
            where.append(
                f"(coalesce(published_at, ingested_at), doc_id) < "
                f"({_next(cur_ua)}, {_next(UUID(cur_id))})"
            )

        sql = f"""
            SELECT doc_id, source, source_url, filing_type, procedural_stage,
                   title, published_at, ingested_at, stakeholder_id, pages
            FROM documents
            WHERE {' AND '.join(where)}
            ORDER BY coalesce(published_at, ingested_at) DESC NULLS LAST, doc_id DESC
            LIMIT {limit + 1}
        """
        rows = await conn.fetch(sql, *params)

    items = []
    for r in rows[:limit]:
        items.append({
            "doc_id":           str(r["doc_id"]),
            "source":           r["source"],
            "source_url":       r["source_url"],
            "filing_type":      r["filing_type"],
            "procedural_stage": r["procedural_stage"],
            "title":            r["title"],
            "published_at":     r["published_at"].isoformat() if r["published_at"] else None,
            "ingested_at":      r["ingested_at"].isoformat() if r["ingested_at"] else None,
            "stakeholder_id":   str(r["stakeholder_id"]) if r["stakeholder_id"] else None,
            "pages":            r["pages"],
        })
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(
            last["published_at"] or last["ingested_at"], last["doc_id"]
        )
    return {"items": items, "next_cursor": next_cursor}


# ═══════════════════════════════════════════════════════════════════════
# 6) POST /api/dockets/{id}/summary/refresh (SSE)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/{docket_id}/summary/refresh")
async def summary_refresh(
    docket_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    async with pool.acquire() as conn:
        await _require_docket(conn, docket_id)

    return StreamingResponse(
        refresh_stream(pool, claude, docket_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════
# 7) POST /api/dockets/{id}/question (SSE, with qa_cache)
# ═══════════════════════════════════════════════════════════════════════

class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, Any]] | None = None


_QA_SYSTEM = """You are a UK energy regulatory analyst. Answer questions about
a single docket. Cite every factual claim with [n] where n is the index
of the document in the provided batch. UK English. No markdown tables.
No marketing language. If the documents don't support an answer, say so
and suggest what documents would resolve it."""


@router.post("/{docket_id}/question")
async def docket_question(
    docket_id: str,
    body: QuestionRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """SSE-streamed Q&A. Writes-through to docket_qa_cache. Returns the
    cached answer synchronously (single SSE frame) on duplicate question."""
    question = body.question.strip()

    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        # Cache hit?
        cached = await conn.fetchrow(
            """SELECT answer, citations, generated_at
               FROM docket_qa_cache
               WHERE docket_id = $1 AND question = $2""",
            did, question,
        )

        if cached:
            async def _replay():
                yield _sse({"type": "cache_hit",
                            "generated_at": cached["generated_at"].isoformat()
                                if cached["generated_at"] else None})
                yield _sse({"type": "text_delta", "content": cached["answer"]})
                yield _sse({"type": "final", "payload": {
                    "answer": cached["answer"],
                    "citations": cached["citations"],
                    "cached": True,
                }})
                yield _sse({"type": "done"})
            return StreamingResponse(
                _replay(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # Pull a fresh batch of docs for citation context.
        doc_rows = await conn.fetch(
            """SELECT doc_id, title, body_text, filing_type, published_at
               FROM documents
               WHERE docket_id = $1
               ORDER BY published_at DESC NULLS LAST
               LIMIT 30""",
            did,
        )
    docs = [dict(r) for r in doc_rows]

    async def _stream():
        if not docs:
            yield _sse({"type": "error", "message": "No documents on this docket yet — cannot answer."})
            yield _sse({"type": "done"})
            return

        # Build context block.
        context_chunks: list[str] = []
        for i, dx in enumerate(docs):
            body_txt = (dx.get("body_text") or "")[:1500]
            context_chunks.append(f"[{i}] {dx['title']}\n    {body_txt}")
        ctx = "\n\n".join(context_chunks)

        messages: list[dict[str, Any]] = []
        for h in (body.history or [])[-6:]:
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append({
            "role": "user",
            "content": f"Docket documents:\n{ctx}\n\nQuestion: {question}",
        })

        yield _sse({"type": "progress", "stage": "streaming"})

        chunks: list[str] = []
        try:
            async with claude.messages.stream(
                model=MODEL_SONNET,
                max_tokens=1500,
                system=_QA_SYSTEM,
                messages=messages,
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "content_block_delta":
                        delta = getattr(event.delta, "text", None)
                        if delta:
                            chunks.append(delta)
                            yield _sse({"type": "text_delta", "content": delta})
        except Exception as exc:
            log.exception("docket_question: claude failed: %s", exc)
            yield _sse({"type": "error", "message": str(exc)[:400]})
            yield _sse({"type": "done"})
            return

        answer = "".join(chunks).strip()

        # Extract citation indices.
        import re as _re
        indices = sorted({int(m) for m in _re.findall(r"\[(\d+)\]", answer)})
        citation_doc_ids = [
            str(docs[i]["doc_id"]) for i in indices if 0 <= i < len(docs)
        ]

        # Write-through.
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO docket_qa_cache
                          (docket_id, question, answer, citations)
                       VALUES ($1, $2, $3, $4::jsonb)
                       ON CONFLICT (docket_id, question) DO UPDATE SET
                          answer = EXCLUDED.answer,
                          citations = EXCLUDED.citations,
                          generated_at = now()""",
                    did, question, answer,
                    json.dumps({"doc_ids": citation_doc_ids, "indices": indices}),
                )
        except Exception as exc:
            log.warning("qa_cache write failed: %s", exc)

        yield _sse({
            "type": "final",
            "payload": {
                "answer": answer,
                "citations": {"doc_ids": citation_doc_ids, "indices": indices},
                "cached": False,
            },
        })
        yield _sse({"type": "done"})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════
# 8) POST / DELETE /api/dockets/{id}/pin
# ═══════════════════════════════════════════════════════════════════════

class PinRequest(BaseModel):
    project_id: str
    note: str | None = None


@router.post("/{docket_id}/pin")
async def pin_docket(
    docket_id: str,
    body: PinRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    try:
        project_uuid = UUID(body.project_id)
        docket_uuid = UUID(docket_id)
    except ValueError:
        raise HTTPException(400, "invalid UUID")

    async with pool.acquire() as conn:
        await _require_docket(conn, docket_id)
        await conn.execute(
            """INSERT INTO project_docket_pins
                  (project_id, docket_id, pinned_by, note)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (project_id, docket_id) DO UPDATE SET
                  note = EXCLUDED.note,
                  pinned_by = EXCLUDED.pinned_by""",
            project_uuid, docket_uuid, user.get("email") or user.get("user_id") or "anonymous",
            body.note,
        )

    # Fire-and-forget AgentVerdict refresh.
    asyncio.create_task(_refresh_agent_verdict(pool, body.project_id))

    return {"pinned": True, "project_id": body.project_id, "docket_id": docket_id}


@router.delete("/{docket_id}/pin/{project_id}")
async def unpin_docket(
    docket_id: str,
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    try:
        project_uuid = UUID(project_id)
        docket_uuid = UUID(docket_id)
    except ValueError:
        raise HTTPException(400, "invalid UUID")

    async with pool.acquire() as conn:
        res = await conn.execute(
            """DELETE FROM project_docket_pins
               WHERE project_id = $1 AND docket_id = $2""",
            project_uuid, docket_uuid,
        )
    # Fire-and-forget AgentVerdict refresh.
    asyncio.create_task(_refresh_agent_verdict(pool, project_id))
    return {"unpinned": res.endswith("1")}


async def _refresh_agent_verdict(pool: asyncpg.Pool, project_id: str) -> None:
    """Fire-and-forget: tell AgentVerdict the pin graph changed. This is
    best-effort — if the refresh hook isn't wired yet, log and return."""
    try:
        # Soft import so a missing follow-up task doesn't break this router.
        from app.agent import refresh_verdict_for_project  # type: ignore
    except Exception:
        log.debug("_refresh_agent_verdict: refresh_verdict_for_project not wired — skipping")
        return
    try:
        await refresh_verdict_for_project(pool, project_id)
    except Exception as exc:
        log.debug("_refresh_agent_verdict: failed for %s: %s", project_id, exc)


# ═══════════════════════════════════════════════════════════════════════
# 9) POST / DELETE /api/dockets/{id}/watch
# ═══════════════════════════════════════════════════════════════════════

class WatchRequest(BaseModel):
    cadence: str = "daily"   # realtime | daily | weekly | on_deadline
    channels: dict[str, bool] | None = None
    filters: dict[str, Any] | None = None


@router.post("/{docket_id}/watch")
async def watch_docket(
    docket_id: str,
    body: WatchRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    if body.cadence not in ("realtime", "daily", "weekly", "on_deadline"):
        raise HTTPException(400, "invalid cadence")
    try:
        docket_uuid = UUID(docket_id)
    except ValueError:
        raise HTTPException(400, "invalid docket_id")

    channels_json = json.dumps(body.channels or {"email": True, "in_app": True, "slack": False})
    filters_json = json.dumps(body.filters or {}) if body.filters is not None else None

    async with pool.acquire() as conn:
        await _require_docket(conn, docket_id)
        await conn.execute(
            """INSERT INTO docket_watches
                  (user_id, docket_id, cadence, channels, filters)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
               ON CONFLICT (user_id, docket_id) DO UPDATE SET
                   cadence = EXCLUDED.cadence,
                   channels = EXCLUDED.channels,
                   filters = EXCLUDED.filters""",
            str(user.get("user_id") or user.get("email") or "anonymous"),
            docket_uuid, body.cadence, channels_json, filters_json,
        )
    return {"watching": True, "docket_id": docket_id, "cadence": body.cadence}


@router.delete("/{docket_id}/watch")
async def unwatch_docket(
    docket_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    try:
        docket_uuid = UUID(docket_id)
    except ValueError:
        raise HTTPException(400, "invalid docket_id")
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM docket_watches WHERE user_id = $1 AND docket_id = $2",
            str(user.get("user_id") or user.get("email") or "anonymous"),
            docket_uuid,
        )
    return {"unwatched": res.endswith("1")}


# ═══════════════════════════════════════════════════════════════════════
# 10) POST /api/dockets/custom
# ═══════════════════════════════════════════════════════════════════════

class CustomDocketRequest(BaseModel):
    name: str
    description: str | None = None
    visibility: str = "private"     # private | team | public
    seed_doc_ids: list[str] = Field(default_factory=list)
    seed_stakeholder_ids: list[str] = Field(default_factory=list)
    geometry_wkt: str | None = None
    automation: dict[str, Any] | None = None


@router.post("/custom")
async def create_custom_docket(
    body: CustomDocketRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    """Create a virtual docket with source='custom'. Seeds documents and
    stakeholders if UUIDs were supplied."""
    async with pool.acquire() as conn:
        # Resolve stable-ish source_docket_id from user id + name so
        # re-posting produces the same docket (idempotent).
        user_key = str(user.get("user_id") or user.get("email") or "anon")
        source_id = f"custom:{user_key}:{body.name[:80]}"

        # Build the INSERT — safely handle the optional geometry param.
        if body.geometry_wkt:
            row = await conn.fetchrow(
                """INSERT INTO dockets
                        (source, source_docket_id, title, description,
                         case_type, industry, geometry)
                    VALUES ('custom', $1, $2, $3, 'misc', 'electricity',
                            ST_SetSRID(ST_GeomFromText($4), 4326)::geography)
                    ON CONFLICT (source, source_docket_id) DO UPDATE
                        SET title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            updated_at = now()
                    RETURNING docket_id""",
                source_id, body.name, body.description,
                body.geometry_wkt,
            )
        else:
            row = await conn.fetchrow(
                """INSERT INTO dockets
                        (source, source_docket_id, title, description,
                         case_type, industry)
                    VALUES ('custom', $1, $2, $3, 'misc', 'electricity')
                    ON CONFLICT (source, source_docket_id) DO UPDATE
                        SET title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            updated_at = now()
                    RETURNING docket_id""",
                source_id, body.name, body.description,
            )
        did = row["docket_id"]

        # Attach seed documents.
        for doc_id_str in body.seed_doc_ids:
            try:
                doc_uuid = UUID(doc_id_str)
            except ValueError:
                continue
            try:
                await conn.execute(
                    "UPDATE documents SET docket_id = $1 WHERE doc_id = $2",
                    did, doc_uuid,
                )
            except Exception as exc:
                log.debug("custom docket doc seed skipped: %s", exc)

        # Copy seed stakeholders (from other dockets) into this one.
        for s_id_str in body.seed_stakeholder_ids:
            try:
                s_uuid = UUID(s_id_str)
            except ValueError:
                continue
            try:
                await conn.execute(
                    """INSERT INTO stakeholders
                          (docket_id, authority_id, company_number, person_name,
                           display_name, role, position)
                       SELECT $1, authority_id, company_number, person_name,
                              display_name, role, position
                       FROM stakeholders WHERE id = $2
                       ON CONFLICT (docket_id, display_name) DO NOTHING""",
                    did, s_uuid,
                )
            except Exception as exc:
                log.debug("custom docket stakeholder seed skipped: %s", exc)

    return {
        "docket_id": str(did),
        "visibility": body.visibility,
        "automation": body.automation or {},
    }


# ═══════════════════════════════════════════════════════════════════════
# 11) GET /api/dockets/{id}/export?format=pdf|csv|json
# ═══════════════════════════════════════════════════════════════════════

@router.get("/{docket_id}/export")
async def docket_export(
    docket_id: str,
    format: str = Query("json", pattern="^(json|csv|pdf)$"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        d = await _require_docket(conn, docket_id)
        did = d["docket_id"]

        docs = await conn.fetch(
            """SELECT doc_id, source, source_url, title, filing_type,
                      procedural_stage, published_at
               FROM documents WHERE docket_id = $1
               ORDER BY published_at DESC NULLS LAST""",
            did,
        )
        stakes = await conn.fetch(
            """SELECT display_name, role, position, submission_count,
                      last_submission_at
               FROM stakeholders WHERE docket_id = $1
               ORDER BY submission_count DESC NULLS LAST""",
            did,
        )
        events = await conn.fetch(
            """SELECT event_type, event_at, summary_text, forward_looking,
                      deadline_at
               FROM docket_timeline_events WHERE docket_id = $1
               ORDER BY event_at""",
            did,
        )

    payload = {
        "docket":       _docket_summary_dict(d) | {
            "exec_summary_text": d.get("exec_summary_text")
        },
        "documents":    [dict(r) for r in docs],
        "stakeholders": [dict(r) for r in stakes],
        "timeline":     [dict(r) for r in events],
    }

    if format == "json":
        return StreamingResponse(
            io.BytesIO(json.dumps(payload, default=str, indent=2).encode()),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="docket-{docket_id}.json"',
            },
        )

    if format == "csv":
        buf = io.StringIO()
        buf.write(f"# Docket: {d['title']}\n# ID: {docket_id}\n\n")
        buf.write("## Documents\n")
        buf.write("doc_id,title,filing_type,stage,published_at,source_url\n")
        for r in docs:
            buf.write(",".join(_csv_escape(v) for v in (
                str(r["doc_id"]), r["title"] or "", r["filing_type"] or "",
                r["procedural_stage"] or "",
                r["published_at"].isoformat() if r["published_at"] else "",
                r["source_url"] or "",
            )) + "\n")
        buf.write("\n## Stakeholders\n")
        buf.write("display_name,role,position,submissions,last_submission\n")
        for r in stakes:
            buf.write(",".join(_csv_escape(v) for v in (
                r["display_name"] or "", r["role"] or "", r["position"] or "",
                str(r["submission_count"] or 0),
                r["last_submission_at"].isoformat() if r["last_submission_at"] else "",
            )) + "\n")
        buf.write("\n## Timeline\n")
        buf.write("event_type,event_at,forward_looking,deadline_at,summary\n")
        for r in events:
            buf.write(",".join(_csv_escape(v) for v in (
                r["event_type"] or "",
                r["event_at"].isoformat() if r["event_at"] else "",
                "true" if r["forward_looking"] else "false",
                r["deadline_at"].isoformat() if r["deadline_at"] else "",
                r["summary_text"] or "",
            )) + "\n")
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode()),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="docket-{docket_id}.csv"',
            },
        )

    # PDF path — we don't own a PDF renderer here; the app has Jinja2 +
    # Playwright wired elsewhere. Return a minimal text-only PDF via
    # reportlab if available; otherwise return JSON with a clear hint.
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except ImportError:
        raise HTTPException(
            501,
            "PDF export needs the reportlab dependency; use format=json "
            "or format=csv in the meantime.",
        )

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    width, height = A4
    y = height - 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, y, f"Docket: {d['title'][:80]}")
    y -= 8 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"ID: {docket_id}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Source: {d['source']}  Case: {d['case_type'] or 'n/a'}  Stage: {d['stage'] or 'n/a'}")
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Executive summary")
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    for line in (d.get("exec_summary_text") or "(no summary)").splitlines()[:40]:
        c.drawString(20 * mm, y, line[:110])
        y -= 4 * mm
        if y < 20 * mm:
            c.showPage()
            y = height - 20 * mm
    c.showPage()
    c.save()
    pdf_buf.seek(0)
    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="docket-{docket_id}.pdf"',
        },
    )


def _csv_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    if any(c in s for c in (",", "\"", "\n")):
        s = s.replace('"', '""')
        return f'"{s}"'
    return s


# ═══════════════════════════════════════════════════════════════════════
# 12) POST /api/dockets/{id}/share
# ═══════════════════════════════════════════════════════════════════════

class DocketShareRequest(BaseModel):
    ttl_days: int = 30


@router.post("/{docket_id}/share")
async def docket_share(
    docket_id: str,
    body: DocketShareRequest | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        await _require_docket(conn, docket_id)
    ttl = max(1, min(365, (body.ttl_days if body else 30)))
    expires_ts = int(time.time()) + ttl * 86400
    token = _sign_docket_share(docket_id, expires_ts)
    return {
        "share_token": token,
        "url": f"/d/{token}",
        "expires_at": expires_ts,
    }


__all__ = ["router"]
