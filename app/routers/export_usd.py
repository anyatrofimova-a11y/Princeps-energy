"""OpenUSD export endpoints for NVIDIA Omniverse integration."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from utils.usd_exporter import generate_usd_scene, generate_metadata

log = logging.getLogger("princeps.export_usd")
router = APIRouter(tags=["export"])


def _safe_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
    return clean[:60] or "site"


class UsdExportRequest(BaseModel):
    """Payload for OpenUSD scene export."""
    site: dict = {}
    substations: list[dict] = []
    assets: list[dict] = []
    heightmap: dict | None = None
    power_lines: list[dict] | None = None


@router.post("/api/export/usd")
async def export_usd(req: UsdExportRequest):
    """Generate an OpenUSD (USDA) scene file for NVIDIA Omniverse.

    Exports a complete 3D scene containing:
    - Terrain ground plane (from LiDAR heightmap or flat default)
    - Substations as scaled Cube prims positioned at real lat/lon
    - Placed assets (solar arrays, BESS, transformers, DC buildings)
    - Power lines as BasisCurves connecting substations
    - PBR materials with Princeps colour scheme
    - Site metadata (name, capacity, verdict, coordinates)

    Returns a downloadable .usda file compatible with Omniverse DSX Blueprint.
    """
    try:
        usda = generate_usd_scene(
            site=req.site,
            substations=req.substations,
            assets=req.assets,
            heightmap=req.heightmap,
            power_lines=req.power_lines,
        )
    except Exception as e:
        log.exception("USD scene generation failed")
        raise HTTPException(status_code=500, detail=f"USD export failed: {e}")

    site_name = req.site.get("name", "site")
    filename = f"princeps-scene-{_safe_filename(site_name)}.usda"

    return StreamingResponse(
        iter([usda.encode("utf-8")]),
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Princeps-Format": "USDA 1.0",
        },
    )


@router.post("/api/export/usd-metadata")
async def export_usd_metadata(req: UsdExportRequest):
    """Generate companion JSON metadata for an OpenUSD scene export.

    Returns a JSON document with site coordinates, asset inventory,
    substation list, and coordinate reference information for
    Omniverse integration and downstream tooling.
    """
    try:
        meta = generate_metadata(
            site=req.site,
            substations=req.substations,
            assets=req.assets,
            power_lines=req.power_lines,
        )
    except Exception as e:
        log.exception("USD metadata generation failed")
        raise HTTPException(status_code=500, detail=f"USD metadata export failed: {e}")

    return JSONResponse(content=meta)
