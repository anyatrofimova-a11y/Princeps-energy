"""DC Layout router — auto-generate data centre campus layouts from boundary polygons."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from utils.dc_layout_engine import (
    DC_MODULES,
    TIER_SPECS,
    generate_dc_layout,
    boundary_from_point,
)

router = APIRouter(tags=["dc-layout"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class DCLayoutRequest(BaseModel):
    boundary: dict = Field(..., description="GeoJSON Polygon geometry with coordinates ring")
    it_load_mw: float = Field(10, ge=0.5, le=500, description="IT load in MW")
    tier: int = Field(3, ge=1, le=4, description="Uptime Institute Tier 1-4")
    cooling_type: str = Field("hybrid", description="mechanical, free_cooling, hybrid, evaporative")
    pue_target: float = Field(1.3, ge=1.0, le=2.5, description="Target PUE")


# ---------------------------------------------------------------------------
# POST /api/dc-layout/generate — full layout from boundary polygon
# ---------------------------------------------------------------------------

@router.post("/api/dc-layout/generate")
async def api_dc_layout_generate(req: DCLayoutRequest):
    """Generate a complete DC campus layout within a boundary polygon.

    Accepts a GeoJSON Polygon geometry and returns a FeatureCollection of
    3D building footprints with height, colour, and type metadata suitable
    for rendering with deck.gl PolygonLayer / SolidPolygonLayer.
    """
    # Extract coordinates ring from GeoJSON geometry
    coords = req.boundary.get("coordinates", [[]])[0]
    if not coords or len(coords) < 4:
        return {"error": "boundary must be a GeoJSON Polygon with at least 4 coordinate pairs"}

    return generate_dc_layout(
        boundary_coords=coords,
        it_load_mw=req.it_load_mw,
        tier=req.tier,
        cooling_type=req.cooling_type,
        pue_target=req.pue_target,
    )


# ---------------------------------------------------------------------------
# GET /api/dc-layout/modules — list building module types
# ---------------------------------------------------------------------------

@router.get("/api/dc-layout/modules")
async def api_dc_layout_modules():
    """List all available DC building module types with dimensions and colours."""
    return {
        key: {
            "label": mod["label"],
            "width_m": mod["width_m"],
            "depth_m": mod["depth_m"],
            "height_m": mod["height_m"],
            "area_m2": mod["width_m"] * mod["depth_m"],
            "color": mod["color"],
            **({"power_density_mw": mod["power_density_mw"]} if "power_density_mw" in mod else {}),
        }
        for key, mod in DC_MODULES.items()
    }


# ---------------------------------------------------------------------------
# GET /api/dc-layout/tiers — tier specifications
# ---------------------------------------------------------------------------

@router.get("/api/dc-layout/tiers")
async def api_dc_layout_tiers():
    """List Uptime Institute Tier specifications (1-4)."""
    return {
        str(k): v for k, v in TIER_SPECS.items()
    }


# ---------------------------------------------------------------------------
# GET /api/dc-layout/quick — generate from point + area (convenience)
# ---------------------------------------------------------------------------

@router.get("/api/dc-layout/quick")
async def api_dc_layout_quick(
    lat: float = Query(52.5, description="Centre latitude"),
    lon: float = Query(-1.5, description="Centre longitude"),
    it_load_mw: float = Query(10, ge=0.5, le=500, description="IT load in MW"),
    tier: int = Query(3, ge=1, le=4, description="Uptime Institute Tier 1-4"),
    site_area_ha: float = Query(5, ge=0.5, le=100, description="Site area in hectares"),
    cooling_type: str = Query("hybrid", description="mechanical, free_cooling, hybrid, evaporative"),
    pue_target: float = Query(1.3, ge=1.0, le=2.5, description="Target PUE"),
):
    """Quick layout generation from a centre point + site area.

    Auto-creates a rectangular boundary and returns the full layout.
    Useful for rapid exploration before drawing a precise boundary.
    """
    boundary_coords = boundary_from_point(lat, lon, site_area_ha)
    return generate_dc_layout(
        boundary_coords=boundary_coords,
        it_load_mw=it_load_mw,
        tier=tier,
        cooling_type=cooling_type,
        pue_target=pue_target,
    )
