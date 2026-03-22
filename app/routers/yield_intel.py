"""Solar yield intelligence API — row shading, layout comparison, hourly profiles."""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.yield_intelligence import (
    annual_shade_loss,
    compare_layouts,
    hourly_generation_profile,
)

router = APIRouter(prefix="/api/yield-intel", tags=["yield-intelligence"])


@router.get("/shade-analysis")
async def shade_analysis(
    row_pitch_m: float = Query(..., gt=0, description="Row pitch (centre-to-centre) in metres"),
    panel_height_m: float = Query(1.134, gt=0, description="Panel height in metres"),
    tilt_deg: float = Query(25, ge=0, le=90, description="Panel tilt in degrees"),
    latitude: float = Query(..., ge=-90, le=90, description="Site latitude (WGS84)"),
):
    """Annual inter-row shading loss with monthly breakdown."""
    return annual_shade_loss(row_pitch_m, panel_height_m, tilt_deg, latitude)


@router.get("/compare-layouts")
async def compare_layouts_endpoint(
    latitude: float = Query(..., ge=-90, le=90, description="Site latitude (WGS84)"),
    site_area_ha: float = Query(..., gt=0, description="Site area in hectares"),
    panel_watts: int = Query(600, ge=100, le=1000, description="Panel wattage (Wp)"),
    panel_width_m: float = Query(2.278, gt=0, description="Panel width in metres"),
    panel_height_m: float = Query(1.134, gt=0, description="Panel height in metres"),
):
    """Compare layout variants — fixed vs tracker, portrait vs landscape, different GCR."""
    return compare_layouts(
        latitude=latitude,
        site_area_ha=site_area_ha,
        panel_watts=panel_watts,
        panel_width_m=panel_width_m,
        panel_height_m=panel_height_m,
    )


@router.get("/hourly-profile")
async def hourly_profile(
    capacity_mwp: float = Query(..., gt=0, description="Installed DC capacity in MWp"),
    latitude: float = Query(..., ge=-90, le=90, description="Site latitude (WGS84)"),
    tilt_deg: float = Query(25, ge=0, le=90, description="Panel tilt in degrees"),
    tracking: str = Query("fixed", description="Tracking type: fixed or single_axis"),
    month: int = Query(6, ge=1, le=12, description="Month (1-12)"),
):
    """Hourly power output profile for a given month."""
    return hourly_generation_profile(
        capacity_mwp=capacity_mwp,
        latitude=latitude,
        tilt_deg=tilt_deg,
        tracking=tracking,
        month=month,
    )
