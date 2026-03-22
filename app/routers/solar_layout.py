"""Solar farm auto-layout API — generates optimal panel layouts from site boundaries.

Endpoints:
  POST /api/solar-layout/generate  — full layout from GeoJSON boundary
  GET  /api/solar-layout/presets   — panel manufacturer presets
  GET  /api/solar-layout/quick     — quick layout from point + area
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from utils.solar_layout_engine import (
    generate_layout,
    quick_layout_from_point,
    get_panel_presets,
)

router = APIRouter(prefix="/api/solar-layout", tags=["solar-layout"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ExclusionZone(BaseModel):
    """A polygon ring to exclude from the layout."""
    coordinates: list[list[float]] = Field(
        ..., description="Ring of [lon, lat] pairs defining the exclusion zone"
    )


class LayoutRequest(BaseModel):
    """Request body for full layout generation."""
    boundary: dict[str, Any] = Field(
        ...,
        description="GeoJSON Polygon geometry or just coordinates ring [[lon, lat], ...]",
    )
    panel_type: str = Field("landscape", description="'landscape' or 'portrait'")
    panel_watts: int = Field(600, ge=100, le=1000, description="Module Wp rating")
    panel_width_m: float | None = Field(None, ge=0.5, le=5.0, description="Module width (m)")
    panel_height_m: float | None = Field(None, ge=0.5, le=5.0, description="Module height (m)")
    modules_per_string: int = Field(24, ge=4, le=40, description="Modules per string")
    tilt_deg: float | None = Field(None, ge=0, le=60, description="Tilt angle (None = auto from latitude)")
    azimuth_deg: float = Field(180.0, ge=0, le=360, description="Panel azimuth (180 = south)")
    gcr_target: float = Field(0.40, ge=0.15, le=0.65, description="Ground coverage ratio target")
    setback_m: float = Field(5.0, ge=0, le=50, description="Boundary setback (m)")
    row_gap_min_m: float = Field(2.0, ge=0.5, le=10, description="Minimum maintenance access gap (m)")
    tracking: str = Field("fixed", description="'fixed', 'single_axis', or 'dual_axis'")
    exclusion_zones: list[ExclusionZone] | None = Field(None, description="Polygons to exclude")
    tables_high: int = Field(2, ge=1, le=6, description="Module rows per table")
    tables_wide: int = Field(2, ge=1, le=6, description="Modules across per table")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate")
async def generate_solar_layout(req: LayoutRequest):
    """Generate a complete solar farm layout from a boundary polygon.

    Accepts either a GeoJSON Polygon geometry object or a raw coordinate ring.
    Returns panel table features, summary stats, yield estimate, and cost breakdown.
    """
    # Extract coordinates from boundary
    boundary = req.boundary
    if isinstance(boundary, dict):
        if "coordinates" in boundary:
            # GeoJSON Polygon geometry — take outer ring
            coords = boundary["coordinates"]
            if isinstance(coords[0][0], (list, tuple)):
                # Nested ring: [[ring], [holes...]]
                coords = coords[0]
            boundary_coords = coords
        elif "geometry" in boundary:
            # GeoJSON Feature
            boundary_coords = boundary["geometry"]["coordinates"][0]
        else:
            # Assume raw coordinate list
            boundary_coords = list(boundary.values())[0] if not isinstance(boundary, list) else boundary
    else:
        boundary_coords = boundary

    # Convert exclusion zones
    excl = None
    if req.exclusion_zones:
        excl = [ez.coordinates for ez in req.exclusion_zones]

    # Build kwargs, omitting None values
    kwargs: dict[str, Any] = {
        "panel_type": req.panel_type,
        "panel_watts": req.panel_watts,
        "modules_per_string": req.modules_per_string,
        "azimuth_deg": req.azimuth_deg,
        "gcr_target": req.gcr_target,
        "setback_m": req.setback_m,
        "row_gap_min_m": req.row_gap_min_m,
        "tracking": req.tracking,
        "exclusion_zones": excl,
        "tables_high": req.tables_high,
        "tables_wide": req.tables_wide,
    }
    if req.panel_width_m is not None:
        kwargs["panel_width_m"] = req.panel_width_m
    if req.panel_height_m is not None:
        kwargs["panel_height_m"] = req.panel_height_m
    if req.tilt_deg is not None:
        kwargs["tilt_deg"] = req.tilt_deg

    result = generate_layout(boundary_coords, **kwargs)
    return result


@router.get("/presets")
async def list_panel_presets():
    """Return available panel manufacturer presets (Jinko, Trina, LONGi, etc.)."""
    return {"presets": get_panel_presets()}


@router.get("/quick")
async def quick_layout(
    lat: float = Query(..., description="Site centre latitude"),
    lon: float = Query(..., description="Site centre longitude"),
    area_ha: float = Query(50.0, ge=0.5, le=500, description="Site area in hectares"),
    capacity_mwp: float | None = Query(None, ge=0.1, le=500, description="Target DC capacity (MWp)"),
    panel_watts: int = Query(600, ge=100, le=1000, description="Module Wp rating"),
    tracking: str = Query("fixed", description="Tracking type"),
    gcr_target: float = Query(0.40, ge=0.15, le=0.65, description="GCR target"),
    tilt_deg: float | None = Query(None, ge=0, le=60, description="Tilt angle"),
    setback_m: float = Query(5.0, ge=0, le=50, description="Boundary setback (m)"),
):
    """Quick layout from a centre point and area — creates a rectangular site boundary."""
    kwargs: dict[str, Any] = {
        "panel_watts": panel_watts,
        "tracking": tracking,
        "gcr_target": gcr_target,
        "setback_m": setback_m,
    }
    if tilt_deg is not None:
        kwargs["tilt_deg"] = tilt_deg

    result = quick_layout_from_point(
        lat=lat,
        lon=lon,
        area_ha=area_ha,
        capacity_mwp=capacity_mwp,
        **kwargs,
    )
    return result
