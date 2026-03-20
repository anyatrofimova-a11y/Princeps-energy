"""PDF report generation endpoints."""

from __future__ import annotations

import logging
import re

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.deps import get_pool
from utils.report_renderer import generate_report

log = logging.getLogger("princeps.reports")
router = APIRouter(tags=["reports"])


def _safe_filename(name: str) -> str:
    """Sanitise site name for use in filename."""
    clean = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
    return clean[:60] or "site"


@router.post("/api/reports/site-assessment")
async def api_site_assessment_report(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    site_name: str = Query("Site", description="Site name for report title"),
    capacity_mw: float = Query(50.0, description="Proposed capacity in MW"),
    template: str = Query("full", description="Report template: full or dashboard"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a branded PDF site assessment report."""
    try:
        async with pool.acquire() as conn:
            pdf_bytes = await generate_report(
                conn, lat, lon, site_name, capacity_mw, template,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Report generation failed")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    filename = f"princeps-report-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
