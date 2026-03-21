"""Bankable yield assessment API — solar/wind energy yield with P50/P75/P90 bands.

Investment-grade yield estimates for lender due diligence, with full uncertainty
quantification, degradation modelling, and technology comparison.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.bankable_yield import (
    solar_yield_bankable,
    wind_yield_bankable,
    yield_comparison,
    uncertainty_analysis,
    degradation_schedule,
)

router = APIRouter(prefix="/api/yield", tags=["yield-assessment"])


@router.get("/solar")
async def solar_yield(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mwp: float = Query(..., ge=0.1, description="Installed DC capacity in MWp"),
    tilt: float | None = Query(None, ge=0, le=90, description="Panel tilt degrees (None = optimal)"),
    azimuth: float = Query(180.0, ge=0, le=360, description="Panel azimuth (180 = south)"),
    tracking: str = Query("fixed", description="Tracking: fixed, single_axis, dual_axis"),
):
    """Bankable solar yield assessment with P50/P75/P90 exceedance bands."""
    return solar_yield_bankable(
        lat=lat,
        lon=lon,
        capacity_mwp=capacity_mwp,
        tilt=tilt,
        azimuth=azimuth,
        tracking=tracking,
    )


@router.get("/wind")
async def wind_yield(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mw: float = Query(..., ge=0.1, description="Installed capacity in MW"),
    hub_height: float = Query(80.0, ge=30, le=200, description="Hub height in metres"),
    turbine_class: str = Query("IEC2", description="IEC turbine class: IEC1, IEC2, IEC3"),
    num_turbines: int = Query(1, ge=1, description="Number of turbines"),
):
    """Bankable wind yield assessment with Weibull distribution and AEP."""
    return wind_yield_bankable(
        lat=lat,
        lon=lon,
        capacity_mw=capacity_mw,
        hub_height=hub_height,
        turbine_class=turbine_class,
        num_turbines=num_turbines,
    )


@router.get("/compare")
async def compare_yield(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mw: float = Query(..., ge=0.1, description="Capacity in MW/MWp"),
):
    """Compare solar vs wind vs hybrid yield at the same location."""
    return yield_comparison(lat=lat, lon=lon, capacity_mw=capacity_mw)


@router.get("/uncertainty")
async def yield_uncertainty(
    technology: str = Query(..., description="Technology: solar or wind"),
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mw: float = Query(..., ge=0.1, description="Capacity in MW/MWp"),
):
    """Detailed uncertainty analysis with exceedance probabilities."""
    return uncertainty_analysis(
        technology=technology,
        lat=lat,
        lon=lon,
        capacity_mw=capacity_mw,
    )


@router.get("/degradation")
async def yield_degradation(
    capacity_mwp: float = Query(..., ge=0.1, description="Installed capacity in MWp"),
    annual_yield_mwh: float = Query(..., ge=0, description="Year-1 P50 yield in MWh"),
    years: int = Query(25, ge=1, le=40, description="Project lifetime in years"),
    degradation_rate: float = Query(0.5, ge=0, le=5, description="Annual degradation rate (%)"),
):
    """Year-by-year degradation schedule with cumulative lifetime yield."""
    return degradation_schedule(
        capacity_mwp=capacity_mwp,
        annual_yield_mwh=annual_yield_mwh,
        years=years,
        degradation_rate=degradation_rate,
    )
