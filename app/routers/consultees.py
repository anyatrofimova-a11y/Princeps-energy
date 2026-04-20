"""
app/routers/consultees.py — consultee resolver endpoints.

GET /api/consultees             — **THE MOAT**. Returns the full list
                                   of UK authorities a project must
                                   consult, derived from geometry +
                                   case_type + tech + capacity.
POST /api/consultees/{authority_id}/draft-letter
                                — SSE. Streams a Claude-drafted
                                   consultation letter with statutory
                                   hook pre-populated (Reg 8/10, s.42,
                                   s.38 post-DCO).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.deps import get_pool, get_claude
from utils.consultee_resolver import resolve_consultees

log = logging.getLogger("princeps.routers.consultees")

router = APIRouter(prefix="/api/consultees", tags=["consultees"])


MODEL_SONNET = os.environ.get("CLAUDE_DOCKET_MODEL", "claude-sonnet-4-6")


# ─── GET /api/consultees ──────────────────────────────────────────────

@router.get("")
async def list_consultees(
    case_type: str = Query(..., description="nsip_dco | lpa_planning | cmp | gc | …"),
    geometry_wkt: str | None = Query(None, description="Site WKT (SRID 4326)."),
    tech: str | None = Query(None, description="solar | wind | bess | dc | any"),
    capacity_mw: float | None = Query(None, ge=0),
    capacity_mwh: float | None = Query(None, ge=0),
    docket_id: str | None = Query(None, description="Optional — overlay live stakeholder status."),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Resolve full consultee list for a (geometry, case_type, tech, capacity) tuple."""
    try:
        result = await resolve_consultees(
            pool,
            geometry_wkt=geometry_wkt,
            case_type=case_type,
            tech=tech,
            capacity_mw=capacity_mw,
            capacity_mwh=capacity_mwh,
            docket_id=docket_id,
        )
    except Exception as exc:
        log.exception("consultee resolve failed: %s", exc)
        raise HTTPException(500, f"consultee resolve failed: {exc}")
    return result


# ─── POST /api/consultees/{authority_id}/draft-letter ──────────────────

class DraftLetterRequest(BaseModel):
    project_id: str
    tone: str | None = "formal"
    key_points: list[str] | None = None


_DRAFT_SYSTEM = """You are a UK energy development paralegal.
Draft a formal consultation letter to a statutory consultee. Obey:

- Start with your client's letterhead placeholder: [APPLICANT NAME]
  [ADDRESS].
- Include the statutory hook verbatim if supplied (Reg 8/10 Planning Act
  2008, Section 42, Section 38 post-DCO, DMPO 2015 Sch.4, etc.).
- Include project particulars: site name, lat/lon, capacity MW,
  technology.
- Specify the consultation period (e.g. 28 days for NSIP Reg 8/10,
  21 days for LPA under DMPO).
- Offer to provide further information, schedule a PEIR meeting, or
  respond to questions.
- Sign off with [APPLICANT SIGNATORY] / [DATE].

Do NOT insert markdown. Plain letter only, UK English, no emojis."""


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


@router.post("/{authority_id}/draft-letter")
async def draft_letter(
    authority_id: str,
    body: DraftLetterRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """SSE-stream a Claude-drafted consultation letter."""
    try:
        auth_uuid = UUID(authority_id)
    except ValueError:
        raise HTTPException(400, "authority_id must be a UUID")

    async with pool.acquire() as conn:
        auth = await conn.fetchrow(
            """SELECT id, slug, name, acronym, type, jurisdiction
               FROM authorities WHERE id = $1""",
            auth_uuid,
        )
        if not auth:
            raise HTTPException(404, "authority not found")

        # Pull project context — best-effort.
        try:
            proj_uuid = UUID(body.project_id)
            project = await conn.fetchrow(
                """SELECT project_id, name, technology, capacity_mw,
                          lat, lon, stage
                   FROM projects WHERE project_id = $1""",
                proj_uuid,
            )
        except Exception:
            project = None

    async def _stream():
        yield _sse({"type": "progress", "stage": "composing", "authority": auth["name"]})

        project_block = "No project context provided."
        if project:
            project_block = (
                f"- Project name: {project['name']}\n"
                f"- Technology: {project['technology'] or 'n/a'}\n"
                f"- Capacity: {project['capacity_mw'] or 0} MW\n"
                f"- Location: {project['lat']}, {project['lon']}\n"
                f"- Development stage: {project['stage'] or 'n/a'}"
            )

        key_points_block = ""
        if body.key_points:
            key_points_block = (
                "\nKey points to include:\n- "
                + "\n- ".join(body.key_points)
            )

        user_msg = (
            f"Draft a consultation letter to:\n"
            f"  {auth['name']} ({auth['acronym'] or ''}, {auth['type']}, "
            f"{auth['jurisdiction']})\n\n"
            f"Project:\n{project_block}\n\n"
            f"Tone: {body.tone or 'formal'}\n"
            f"{key_points_block}"
        )

        try:
            async with claude.messages.stream(
                model=MODEL_SONNET,
                max_tokens=1500,
                system=_DRAFT_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "content_block_delta":
                        delta = getattr(event.delta, "text", None)
                        if delta:
                            yield _sse({"type": "text_delta", "content": delta})
        except Exception as exc:
            log.exception("draft_letter: claude failed: %s", exc)
            yield _sse({"type": "error", "message": str(exc)[:500]})

        yield _sse({"type": "done"})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
