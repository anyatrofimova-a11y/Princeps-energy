"""Design API — automated PV layout generation and site design tools.

Endpoints:
  POST /api/design/auto-layout  — generate optimised PV layout from site boundary
  GET  /api/design/modules      — list available module types
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from utils.pv_layout_engine import generate_pv_layout, list_modules

router = APIRouter(prefix="/api/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AutoLayoutRequest(BaseModel):
    """Request body for PV auto-layout generation."""

    # Site definition — provide ONE of these three options:
    boundary_coords: list[list[float]] | None = Field(
        None,
        description="Polygon ring [[lon, lat], ...] in WGS84. At least 3 vertices.",
    )
    bbox: list[float] | None = Field(
        None,
        description="Bounding box [min_lon, min_lat, max_lon, max_lat].",
    )
    centre_lat: float | None = Field(None, description="Site centre latitude (with centre_lon + radius_m).")
    centre_lon: float | None = Field(None, description="Site centre longitude.")
    radius_m: float | None = Field(None, ge=50, le=5000, description="Site radius in metres.")

    # Target
    capacity_mw: float | None = Field(None, ge=0.01, le=500, description="Target DC capacity (MW).")

    # Layout parameters
    tilt_deg: float | None = Field(None, ge=0, le=60, description="Panel tilt (None = auto from latitude).")
    azimuth_deg: float = Field(180.0, ge=0, le=360, description="Panel azimuth (180 = south).")
    module_key: str = Field("longi_himo6_550", description="Module from catalogue (see GET /api/design/modules).")
    modules_per_string: int = Field(28, ge=4, le=40, description="Modules per electrical string.")
    gcr_target: float | None = Field(None, ge=0.15, le=0.65, description="Ground coverage ratio (None = auto).")
    setback_m: float = Field(10.0, ge=0, le=100, description="Boundary setback (m).")
    access_road_width_m: float = Field(6.0, ge=3, le=12, description="Access road width (m).")
    access_road_interval: int = Field(10, ge=3, le=50, description="Access road every N rows.")
    dc_ac_ratio: float = Field(1.25, ge=1.0, le=1.6, description="DC/AC ratio for inverter sizing.")
    strings_per_inverter: int | None = Field(None, ge=1, le=50, description="Override strings per inverter.")
    inverters_per_transformer: int | None = Field(None, ge=1, le=50, description="Override inverters per transformer.")
    heightmap: list[list[float]] | None = Field(None, description="Optional terrain heightmap grid (reserved).")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/auto-layout")
async def auto_layout(req: AutoLayoutRequest):
    """Generate an optimised PV layout for a site.

    Provide a site boundary (polygon, bbox, or centre+radius), optional target
    capacity, and module/layout parameters. Returns the full electrical hierarchy
    (rows, strings, inverters, transformers), GeoJSON panel geometry, statistics,
    and bill of quantities.
    """
    result = generate_pv_layout(
        boundary_coords=req.boundary_coords,
        bbox=req.bbox,
        centre_lat=req.centre_lat,
        centre_lon=req.centre_lon,
        radius_m=req.radius_m,
        capacity_mw=req.capacity_mw,
        tilt_deg=req.tilt_deg,
        azimuth_deg=req.azimuth_deg,
        module_key=req.module_key,
        modules_per_string=req.modules_per_string,
        gcr_target=req.gcr_target,
        setback_m=req.setback_m,
        access_road_width_m=req.access_road_width_m,
        access_road_interval=req.access_road_interval,
        dc_ac_ratio=req.dc_ac_ratio,
        strings_per_inverter=req.strings_per_inverter,
        inverters_per_transformer=req.inverters_per_transformer,
        heightmap=req.heightmap,
    )
    return result


@router.get("/modules")
async def get_modules():
    """List available PV module types from the built-in catalogue."""
    return {"modules": list_modules()}
