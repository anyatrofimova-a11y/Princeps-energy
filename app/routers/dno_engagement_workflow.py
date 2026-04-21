"""
app/routers/dno_engagement_workflow.py — DNO engagement workflow API.

Endpoints (Task #20, council-approved architecture):

    POST /api/dno-engagement/{engagement_id}/response
        Body: {channel, raw_body, raw_pdf_path}
        Parses the raw response via Claude (app.ingestion.dno_response_parser)
        and writes a row into `dno_engagement_responses`. Flips the parent
        engagement's status to 'responded'.

    GET  /api/dno-engagement/project/{project_id}/history
        Returns every pack version ever created for the project, ordered
        by pack_version DESC, each with a summary of the latest response
        on that version.

    GET  /api/intelligence/engagements?status=&team=
        Cross-project list for the Intelligence tab. Filters: status,
        team (tenant_id shorthand). Used by EngagementsIndex.jsx.

This router DOES NOT implement outbound email — Princeps is not the sender
per council decision. The client-side ``SendEngagementModal`` drafts a
mailto: link and the user's own mail client sends it. The `sent_at` /
`sent_by` / `recipient_email` fields are populated by the "I've sent it"
confirm step, not by this router. That confirm endpoint lives in the
sibling ``utils/dno_engagement/`` engine package and mutates the row
directly — we read-only here.

Phase 7f scaffolding: the `channel='email'` branch is reserved for the
Postmark inbound-webhook hookup at `engage-{uuid}@princeps.energy`. The
webhook handler is deliberately NOT wired yet — the `POST …/response`
route is today the only write path.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_claude, get_current_user, get_pool

log = logging.getLogger("princeps.routers.dno_engagement_workflow")

router = APIRouter(prefix="/api", tags=["dno-engagement"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ResponseIngestBody(BaseModel):
    channel: Literal["email", "upload", "api", "manual"]
    raw_body: str | None = Field(
        None,
        description="Raw response text — email body or the full extracted "
                    "text from the attached PDF. At least one of raw_body or "
                    "raw_pdf_path must be supplied.",
    )
    raw_pdf_path: str | None = Field(
        None,
        description="Path on the Princeps filesystem to the raw DNO response "
                    "PDF. Stored for provenance — the parser reads from "
                    "raw_body when both are supplied.",
    )


class EngagementResponseOut(BaseModel):
    id: str
    engagement_id: str
    received_at: str
    channel: str
    structured_extract: dict | None
    acknowledgement_sent_at: str | None
    triggered_verdict_recompute: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_engagement_summary(row: asyncpg.Record, latest_response: asyncpg.Record | None) -> dict[str, Any]:
    """Shape a row from project_dno_engagements for JSON output."""
    return {
        "id":              str(row["id"]),
        "project_id":      str(row["project_id"]),
        "tenant_id":       str(row["tenant_id"]) if row["tenant_id"] else None,
        "dno_slug":        row["dno_slug"],
        "pack_version":    int(row["pack_version"]),
        "pdf_sha256":      row["pdf_sha256"],
        "pdf_path":        row["pdf_path"],
        "sent_at":         row["sent_at"].isoformat() if row["sent_at"] else None,
        "sent_by":         str(row["sent_by"]) if row["sent_by"] else None,
        "recipient_email": row["recipient_email"],
        "status":          row["status"],
        "created_at":      row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at":      row["updated_at"].isoformat() if row["updated_at"] else None,
        "latest_response": (
            {
                "id":          str(latest_response["id"]),
                "received_at": latest_response["received_at"].isoformat()
                    if latest_response["received_at"] else None,
                "channel":     latest_response["channel"],
                "acknowledged":
                    latest_response["acknowledgement_sent_at"] is not None,
                "triggered_verdict_recompute":
                    bool(latest_response["triggered_verdict_recompute"]),
            }
            if latest_response is not None else None
        ),
    }


async def _fetch_latest_response(
    conn: asyncpg.Connection, engagement_id: UUID
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, received_at, channel, acknowledgement_sent_at,
               triggered_verdict_recompute
        FROM dno_engagement_responses
        WHERE engagement_id = $1
        ORDER BY received_at DESC
        LIMIT 1
        """,
        engagement_id,
    )


# ---------------------------------------------------------------------------
# POST /api/dno-engagement/{engagement_id}/response
# ---------------------------------------------------------------------------

@router.post("/dno-engagement/{engagement_id}/response")
async def ingest_response(
    engagement_id: str,
    body: ResponseIngestBody,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Ingest a DNO response, parse it via Claude, and persist.

    Writes exactly one row into `dno_engagement_responses` and flips the
    parent engagement's `status` to 'responded'. Does NOT send any email
    acknowledgement — that's a sibling action in the engine package.
    """
    try:
        eng_uuid = UUID(engagement_id)
    except ValueError:
        raise HTTPException(400, "engagement_id must be a UUID")

    if not body.raw_body and not body.raw_pdf_path:
        raise HTTPException(
            400, "At least one of raw_body or raw_pdf_path must be provided"
        )

    # Parse via Claude (dno_response_parser). Failures fall back to a
    # minimal stub so the row still lands — the frontend can show "parse
    # failed, open raw" instead of silently dropping the response.
    structured_extract: dict | None = None
    try:
        from app.ingestion.dno_response_parser import parse_dno_response
        structured_extract = await parse_dno_response(
            claude=claude,
            raw_body=body.raw_body,
            raw_pdf_path=body.raw_pdf_path,
        )
    except Exception as e:
        log.warning("DNO response parser failed for engagement %s: %s", engagement_id, e)
        structured_extract = {
            "sentiment": "unknown",
            "requested_info": [],
            "proposed_poc": None,
            "firm_split_delta": None,
            "timeline_revision": None,
            "parse_error": str(e)[:500],
        }

    async with pool.acquire() as conn:
        async with conn.transaction():
            parent = await conn.fetchrow(
                "SELECT id, project_id, status FROM project_dno_engagements WHERE id = $1",
                eng_uuid,
            )
            if parent is None:
                raise HTTPException(404, "engagement not found")

            resp_id = await conn.fetchval(
                """
                INSERT INTO dno_engagement_responses
                    (engagement_id, channel, raw_body, raw_pdf_path,
                     structured_extract)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id
                """,
                eng_uuid, body.channel, body.raw_body, body.raw_pdf_path,
                _json_or_null(structured_extract),
            )

            # Flip parent status — only move sent → responded; don't clobber
            # withdrawn/superseded rows that landed a late response.
            if parent["status"] == "sent":
                await conn.execute(
                    "UPDATE project_dno_engagements SET status='responded' WHERE id = $1",
                    eng_uuid,
                )

    return {
        "id": str(resp_id),
        "engagement_id": str(eng_uuid),
        "channel": body.channel,
        "structured_extract": structured_extract,
    }


# ---------------------------------------------------------------------------
# GET /api/dno-engagement/project/{project_id}/history
# ---------------------------------------------------------------------------

@router.get("/dno-engagement/project/{project_id}/history")
async def project_history(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Return every pack version ever created for the project, newest first."""
    try:
        proj_uuid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "project_id must be a UUID")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, project_id, tenant_id, dno_slug, pack_version,
                   pdf_sha256, pdf_path, sent_at, sent_by, recipient_email,
                   status, created_at, updated_at
            FROM project_dno_engagements
            WHERE project_id = $1
            ORDER BY pack_version DESC
            """,
            proj_uuid,
        )

        items: list[dict[str, Any]] = []
        for r in rows:
            latest = await _fetch_latest_response(conn, r["id"])
            items.append(_row_to_engagement_summary(r, latest))

    return {
        "project_id": str(proj_uuid),
        "engagements": items,
        "count": len(items),
    }


# ---------------------------------------------------------------------------
# GET /api/intelligence/engagements
# ---------------------------------------------------------------------------

@router.get("/intelligence/engagements")
async def list_engagements(
    status: str | None = Query(
        None,
        description="Optional status filter: drafting, previewing, sent, "
                    "responded, withdrawn, superseded. Comma-separated for "
                    "multiple values.",
    ),
    team: str | None = Query(
        None,
        description="Optional team filter — tenant UUID. If absent, all "
                    "tenants visible to the caller are returned.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """List engagements across projects for the Intelligence tab."""
    filters: list[str] = []
    params: list[Any] = []

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            params.append(statuses)
            filters.append(f"status = ANY(${len(params)})")

    if team:
        try:
            team_uuid = UUID(team)
        except ValueError:
            raise HTTPException(400, "team must be a UUID")
        params.append(team_uuid)
        filters.append(f"tenant_id = ${len(params)}")

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    params.append(limit)
    params.append(offset)

    sql = f"""
        SELECT id, project_id, tenant_id, dno_slug, pack_version,
               pdf_sha256, pdf_path, sent_at, sent_by, recipient_email,
               status, created_at, updated_at
        FROM project_dno_engagements
        {where_clause}
        ORDER BY COALESCE(sent_at, updated_at) DESC NULLS LAST
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        items: list[dict[str, Any]] = []
        for r in rows:
            latest = await _fetch_latest_response(conn, r["id"])
            items.append(_row_to_engagement_summary(r, latest))

    return {
        "engagements": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Internal JSON helper — asyncpg expects a JSON-serialised string for jsonb.
# ---------------------------------------------------------------------------

def _json_or_null(value: Any) -> str | None:
    if value is None:
        return None
    import json as _json
    try:
        return _json.dumps(value, default=str)
    except Exception:
        return None
