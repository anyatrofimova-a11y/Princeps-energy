"""Export endpoints — PVsyst .PRJ etc."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.deps import get_pool
from utils.pvsyst_export import export_pvsyst_project

log = logging.getLogger("princeps.exports")

router = APIRouter(prefix="/api/export", tags=["exports"])


@router.get("/pvsyst/{layout_id}")
async def export_pvsyst(
    layout_id: UUID,
    project_name: str | None = Query(None),
    capacity_mw_dc: float | None = Query(None),
    tilt_deg: float | None = Query(None),
    azimuth_deg: float | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Emit a PVsyst-compatible .PRJ for a saved site layout."""
    tmp = Path(tempfile.mkdtemp(prefix="princeps-pvsyst-")) / f"{project_name or layout_id}.PRJ"
    try:
        path = await export_pvsyst_project(
            site_id=str(layout_id),
            layout_id=layout_id,
            out_path=tmp,
            pool=pool,
            project_name=project_name,
            capacity_mw_dc=capacity_mw_dc,
            tilt_deg=tilt_deg,
            azimuth_deg=azimuth_deg,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("pvsyst export failed: %s", e)
        raise HTTPException(500, f"PVsyst export failed: {e}")
    return FileResponse(
        str(path),
        media_type="text/plain",
        filename=path.name,
    )
