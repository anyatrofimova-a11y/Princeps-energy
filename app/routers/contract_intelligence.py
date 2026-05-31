"""Contract Intelligence router — Phase A-G surface for the workspace UI.

Endpoints
---------
POST   /api/contracts/documents                  — create Document record
GET    /api/contracts/documents                  — list (filter by project)
POST   /api/contracts/documents/{rid}/drafts     — upload PDF → new draft
GET    /api/contracts/documents/{rid}/drafts     — list drafts
GET    /api/contracts/drafts/{rid}/clauses       — list clauses (paginated)
POST   /api/contracts/cite                       — citation lookup (Phase C)
POST   /api/contracts/diff                       — multi-draft diff (Phase E)
POST   /api/contracts/extract-obligations        — obligation extraction (Phase F)
GET    /api/contracts/drafts/{rid}/obligations   — list obligations
POST   /api/contracts/chat/verdict               — record a ConfidenceVerdict
GET    /api/contracts/projects/{rid}/alerts      — change-alert feed
POST   /api/contracts/projects/{rid}/scan        — manually trigger watcher
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.deps import get_pool
from utils.clause_diff import diff_drafts
from utils.clause_search import cite_clauses
from utils.document_ingester import ingest_document_draft
from utils.obligation_extractor import extract_obligations

log = logging.getLogger("princeps.contracts")
router = APIRouter(prefix="/api/contracts", tags=["contracts"])


# ── Document CRUD ───────────────────────────────────────────────────────────

class DocumentCreate(BaseModel):
    project_rid: str | None = None
    kind: str = "OTHER"
    title: str
    party_first: str | None = None
    party_second: str | None = None


@router.post("/documents")
async def create_document(
    payload: DocumentCreate,
    pool: asyncpg.Pool = Depends(get_pool),
):
    row = await pool.fetchrow(
        """
        INSERT INTO contracts.documents
            (project_rid, kind, title, party_first, party_second)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING document_rid, project_rid, kind, title,
                  party_first, party_second, status, created_at
        """,
        payload.project_rid, payload.kind, payload.title,
        payload.party_first, payload.party_second,
    )
    return dict(row)


@router.get("/documents")
async def list_documents(
    project_rid: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    if project_rid:
        rows = await pool.fetch(
            "SELECT d.*, "
            "(SELECT count(*) FROM contracts.document_drafts WHERE document_rid=d.document_rid) AS draft_count "
            "FROM contracts.documents d "
            "WHERE d.project_rid = $1 ORDER BY d.created_at DESC",
            project_rid,
        )
    else:
        rows = await pool.fetch(
            "SELECT d.*, "
            "(SELECT count(*) FROM contracts.document_drafts WHERE document_rid=d.document_rid) AS draft_count "
            "FROM contracts.documents d ORDER BY d.created_at DESC LIMIT 200",
        )
    return {"items": [dict(r) for r in rows]}


# ── Draft upload + ingestion ────────────────────────────────────────────────

@router.post("/documents/{document_rid}/drafts")
async def upload_draft(
    document_rid: str,
    file: UploadFile = File(...),
    version_label: str = Form("v1"),
    draft_date: str | None = Form(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Accept a PDF; parse clauses; return ingest summary + draft_rid."""
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "empty upload")
    from datetime import date as _date
    dd = None
    if draft_date:
        try: dd = _date.fromisoformat(draft_date)
        except Exception: dd = None
    result = await ingest_document_draft(
        pool,
        document_rid=document_rid,
        version_label=version_label,
        pdf_bytes=pdf_bytes,
        draft_date=dd,
        source_path=f"uploads/{file.filename}",
    )
    return result


@router.get("/documents/{document_rid}/drafts")
async def list_drafts(
    document_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rows = await pool.fetch(
        "SELECT * FROM contracts.document_drafts "
        "WHERE document_rid = $1 ORDER BY draft_date DESC NULLS LAST, uploaded_at DESC",
        document_rid,
    )
    return {"items": [dict(r) for r in rows]}


@router.get("/drafts/{draft_rid}/clauses")
async def list_clauses(
    draft_rid: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    rows = await pool.fetch(
        "SELECT clause_rid, section, heading, page, span_start, span_end, "
        "left(text, 800) AS preview "
        "FROM contracts.clauses WHERE draft_rid = $1 "
        "ORDER BY page, span_start LIMIT $2 OFFSET $3",
        draft_rid, limit, offset,
    )
    return {"items": [dict(r) for r in rows]}


# ── Phase C: cite ───────────────────────────────────────────────────────────

class CiteRequest(BaseModel):
    query: str
    project_rid: str | None = None
    document_rid: str | None = None
    draft_rid: str | None = None
    top_k: int = 5


@router.post("/cite")
async def cite_endpoint(
    payload: CiteRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    results = await cite_clauses(
        pool,
        project_rid=payload.project_rid,
        document_rid=payload.document_rid,
        draft_rid=payload.draft_rid,
        query=payload.query,
        top_k=payload.top_k,
    )
    return {"citations": results}


# ── Phase E: diff ───────────────────────────────────────────────────────────

class DiffRequest(BaseModel):
    draft_rid_a: str
    draft_rid_b: str


@router.post("/diff")
async def diff_endpoint(
    payload: DiffRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    return await diff_drafts(pool, payload.draft_rid_a, payload.draft_rid_b)


# ── Phase F: extract obligations ────────────────────────────────────────────

class ExtractRequest(BaseModel):
    draft_rid: str
    max_clauses: int = 100


@router.post("/extract-obligations")
async def extract_endpoint(
    payload: ExtractRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    return await extract_obligations(
        pool, payload.draft_rid, max_clauses=payload.max_clauses,
    )


@router.get("/drafts/{draft_rid}/obligations")
async def list_obligations(
    draft_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rows = await pool.fetch(
        "SELECT o.*, c.section, c.heading, c.page "
        "FROM contracts.obligations o "
        "JOIN contracts.clauses c ON o.clause_rid = c.clause_rid "
        "WHERE o.draft_rid = $1 ORDER BY c.page, c.span_start",
        draft_rid,
    )
    return {"items": [dict(r) for r in rows]}


# ── Phase D: ConfidenceVerdict persistence ──────────────────────────────────

class VerdictRecord(BaseModel):
    message_id: str
    session_id: str
    project_rid: str | None = None
    rating: str
    coverage: float | None = None
    justification: str | None = None
    bounds: list[str] = []


@router.post("/chat/verdict")
async def record_verdict(
    payload: VerdictRecord,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rid = await pool.fetchval(
        """
        INSERT INTO contracts.chat_verdicts
            (message_id, session_id, project_rid, rating, coverage,
             justification, bounds)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING verdict_rid
        """,
        payload.message_id, payload.session_id, payload.project_rid,
        payload.rating, payload.coverage, payload.justification,
        list(payload.bounds),
    )
    return {"verdict_rid": rid}


# ── Phase G: watcher / alerts ───────────────────────────────────────────────

@router.get("/projects/{project_rid}/alerts")
async def list_alerts(
    project_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rows = await pool.fetch(
        """
        SELECT a.*
          FROM contracts.change_alerts a
          JOIN contracts.documents d ON a.document_rid = d.document_rid
         WHERE d.project_rid = $1
         ORDER BY a.created_at DESC LIMIT 50
        """,
        project_rid,
    )
    return {"items": [dict(r) for r in rows]}


@router.post("/projects/{project_rid}/scan")
async def project_scan(
    project_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Manual trigger — for each document in the project with ≥2 drafts,
    diff the two most recent drafts + extract obligations + emit a
    change_alert if anything changed."""
    docs = await pool.fetch(
        "SELECT document_rid, title FROM contracts.documents WHERE project_rid = $1",
        project_rid,
    )
    alerts: list[dict[str, Any]] = []
    for d in docs:
        drafts = await pool.fetch(
            "SELECT draft_rid, version_label, draft_date, uploaded_at "
            "FROM contracts.document_drafts WHERE document_rid = $1 "
            "ORDER BY draft_date DESC NULLS LAST, uploaded_at DESC LIMIT 2",
            d["document_rid"],
        )
        if len(drafts) < 2:
            continue
        b, a = drafts[0], drafts[1]   # b = newest
        delta = await diff_drafts(pool, a["draft_rid"], b["draft_rid"])
        s = delta["summary"]
        if s["modified"] == 0 and s["added"] == 0 and s["removed"] == 0:
            continue
        summary_line = (
            f"{d['title']}: {s['modified']} modified, "
            f"{s['added']} added, {s['removed']} removed clauses between "
            f"{a['version_label']} and {b['version_label']}"
        )
        rid = await pool.fetchval(
            """
            INSERT INTO contracts.change_alerts
                (document_rid, draft_rid_a, draft_rid_b, summary, delta)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING alert_rid
            """,
            d["document_rid"], a["draft_rid"], b["draft_rid"],
            summary_line, __import__("json").dumps({"summary": s}),
        )
        alerts.append({"alert_rid": rid, "summary": summary_line, "delta": s})
        # Best-effort obligation extraction for new draft (non-blocking)
        try:
            await asyncio.wait_for(
                extract_obligations(pool, b["draft_rid"], max_clauses=80),
                timeout=120,
            )
        except Exception:
            pass

    return {"scanned": len(docs), "alerts": alerts}
