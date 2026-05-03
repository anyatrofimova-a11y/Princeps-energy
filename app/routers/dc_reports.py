"""DC report endpoints — lender Information Memorandum, etc.

Sits next to ``app/routers/reports.py`` and ``reports_fva.py`` but holds
the data-centre-specific report endpoints so the regular reports router
stays focused on solar / wind / BESS lender packs.

Currently exports:
  * ``GET /api/dc/lender-im-pdf?project_id=<uuid>`` — 30-page lender IM.
"""
from __future__ import annotations

import io
import logging
import re
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.deps import get_pool
from app.reports.lender_im import generate_lender_im

log = logging.getLogger("princeps.routers.dc_reports")
router = APIRouter(tags=["dc-reports"])


def _safe_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
    return clean[:60] or "site"


@router.get("/api/dc/lender-im-pdf")
async def dc_lender_im_pdf(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Stream a 30-page lender-grade Information Memorandum PDF for a UK
    Data Centre project.

    The IM orchestrator (``app.reports.lender_im.generate_lender_im``)
    fans out in parallel across:
      * the ``/api/dc/feasibility-pack`` D1-D5 stack (grid envelope,
        cooling topology, 24/7 CFE, power chain, P10/P50/P90 DCF);
      * the queue-rank Poisson model
        (``utils.queue_rank_poisson.forecast_async``);
      * the REPD / LPA precedent + designations PostGIS lookups.

    Targets sub-10 s end-to-end response from a warm worker. Designed
    for direct delivery to a UK pension-fund / insurance-placer credit
    committee.
    """
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"project_id must be a UUID, got {project_id!r}",
        )

    try:
        pdf_bytes = await generate_lender_im(project_id=pid, pool=pool)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        log.exception("Lender IM generation failed (runtime)")
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        log.exception("Lender IM generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Lender IM generation failed: {exc}",
        )

    # Best-effort filename — fetch the project name for the Content-Disposition header.
    name = project_id
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name FROM projects WHERE project_id = $1", pid,
            )
            if row and row["name"]:
                name = row["name"]
    except Exception:
        pass

    filename = f"princeps-lender-im-{_safe_filename(name)}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
