"""Dispatch model router — PyPSA-based GB dispatch with analytical fallback.

Provides system-level dispatch snapshot, forecasts, zonal prices,
curtailment analysis, site impact assessment, and revenue projections.
Uses analytical merit-order model (Phase 7 fallback); upgrades to PyPSA LOPF
when conda environment is configured.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.helpers import _run_generic_subprocess

router = APIRouter(prefix="/api/dispatch-model", tags=["dispatch-model"])

_DISPATCH_SCRIPT = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "..", "..", "utils", "pypsa_dispatch_runner.py"
)


# ─── Helpers ───────────────────────────────────────────────────────────────

async def _run_dispatch(payload: dict) -> dict:
    """Run the dispatch runner subprocess with JSON stdin/stdout bridge."""
    return await _run_generic_subprocess(_DISPATCH_SCRIPT, payload, timeout=60)


# ─── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/snapshot")
async def dispatch_snapshot(
    demand_gw: float = Query(None, description="Override demand (GW). Omit for analytical profile."),
    wind_cf: float = Query(None, description="Override wind capacity factor (0-1)."),
    solar_cf: float = Query(None, description="Override solar capacity factor (0-1)."),
    timestamp: str = Query(None, description="ISO timestamp. Omit for current time."),
    gas_price_pence_therm: float = Query(None, description="Gas price override (p/therm)."),
    carbon_price_gbp: float = Query(None, description="Carbon price override (GBP/tCO2)."),
):
    """Current GB dispatch state — single-timestamp merit-order snapshot.

    Returns generation by fuel type, system marginal price, carbon intensity,
    curtailment, and renewable percentage.
    """
    return await _run_dispatch({
        "command": "dispatch_snapshot",
        "demand_gw": demand_gw,
        "wind_cf": wind_cf,
        "solar_cf": solar_cf,
        "timestamp": timestamp,
        "gas_price_pence_therm": gas_price_pence_therm,
        "carbon_price_gbp": carbon_price_gbp,
    })


@router.get("/forecast")
async def dispatch_forecast(
    hours: int = Query(48, ge=1, le=168, description="Forecast horizon (hours)."),
    start_date: str = Query(None, description="Forecast start (ISO). Omit for now."),
    gas_price_pence_therm: float = Query(None, description="Gas price override (p/therm)."),
    carbon_price_gbp: float = Query(None, description="Carbon price override (GBP/tCO2)."),
):
    """Hourly dispatch forecast for N hours ahead.

    Returns hourly SMP, carbon intensity, curtailment, and generation mix
    with an aggregated summary.
    """
    return await _run_dispatch({
        "command": "dispatch_forecast",
        "hours": hours,
        "start_date": start_date,
        "gas_price_pence_therm": gas_price_pence_therm,
        "carbon_price_gbp": carbon_price_gbp,
    })


@router.get("/zonal-prices")
async def zonal_prices(
    hours: int = Query(48, ge=1, le=168, description="Forecast horizon (hours)."),
    zones: str = Query(None, description="Comma-separated zones (e.g. 'Scotland,Midlands'). Omit for all."),
    start_date: str = Query(None, description="Forecast start (ISO)."),
    gas_price_pence_therm: float = Query(None, description="Gas price override."),
    carbon_price_gbp: float = Query(None, description="Carbon price override."),
):
    """Zonal wholesale price forecast for GB regions.

    Applies locational adjustments to system marginal price based on
    renewable penetration and transmission constraints.
    """
    zone_list = [z.strip() for z in zones.split(",")] if zones else None
    return await _run_dispatch({
        "command": "zonal_prices",
        "hours": hours,
        "zones": zone_list,
        "start_date": start_date,
        "gas_price_pence_therm": gas_price_pence_therm,
        "carbon_price_gbp": carbon_price_gbp,
    })


@router.get("/curtailment")
async def curtailment_forecast(
    hours: int = Query(48, ge=1, le=168),
    technology: str = Query("solar", description="Generation technology."),
    capacity_mw: float = Query(50, gt=0),
    region: str = Query("Midlands", description="GB region."),
    connection_type: str = Query("firm", description="Connection type: firm, non_firm, anm, flexible."),
    start_date: str = Query(None),
):
    """Curtailment forecast for a specific site/technology.

    Estimates periods when a site would be curtailed based on system
    conditions, regional constraints, and connection type.
    """
    return await _run_dispatch({
        "command": "curtailment_forecast",
        "hours": hours,
        "technology": technology,
        "capacity_mw": capacity_mw,
        "region": region,
        "connection_type": connection_type,
        "start_date": start_date,
    })


@router.get("/site-impact")
async def site_impact(
    lat: float = Query(52.5, description="Site latitude."),
    lon: float = Query(-1.5, description="Site longitude."),
    capacity_mw: float = Query(50, gt=0, description="Site capacity (MW)."),
    technology: str = Query("solar", description="Generation technology."),
    region: str = Query(None, description="GB region. Auto-inferred from lat if omitted."),
):
    """Assess how connecting a new generation site affects local prices and curtailment.

    Returns wholesale price impact, curtailment exposure, and annual revenue estimate.
    """
    return await _run_dispatch({
        "command": "site_impact",
        "lat": lat,
        "lon": lon,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
    })


@router.get("/revenue-forecast")
async def revenue_forecast(
    capacity_mw: float = Query(50, gt=0),
    technology: str = Query("solar"),
    region: str = Query("Midlands"),
    ppa_price_gbp_mwh: float = Query(None, description="PPA price. Omit for merchant."),
    years: int = Query(25, ge=1, le=40, description="Project life (years)."),
    degradation_pct_pa: float = Query(0.5, ge=0, le=3, description="Annual degradation (%)."),
):
    """Projected annual revenue from wholesale + BM based on dispatch model.

    Returns low/central/high price scenarios with NPV, curtailment-adjusted
    generation, and cumulative revenue projections.
    """
    return await _run_dispatch({
        "command": "revenue_forecast",
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "ppa_price_gbp_mwh": ppa_price_gbp_mwh,
        "years": years,
        "degradation_pct_pa": degradation_pct_pa,
    })
