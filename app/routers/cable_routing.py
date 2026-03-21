"""Cable routing router — route optimisation, cost estimation, voltage comparison."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import asyncpg

from app.deps import get_pool
from utils.cable_route_optimiser import (
    optimise_route,
    find_best_route,
    quick_cost_estimate,
    voltage_options,
)

router = APIRouter(prefix="/api/cable", tags=["cable-routing"])


@router.get("/route")
async def cable_route(
    site_lat: float = Query(..., description="Site latitude"),
    site_lon: float = Query(..., description="Site longitude"),
    sub_lat: float = Query(..., description="Substation latitude"),
    sub_lon: float = Query(..., description="Substation longitude"),
    capacity_mw: float = Query(..., ge=0.1, description="Project capacity in MW"),
    voltage_kv: int | None = Query(None, description="Force voltage (11/33/66/132); auto-selected if omitted"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Compute optimal cable route from site to a specific substation.

    Returns route GeoJSON LineString, cost breakdown (P10/P50/P90),
    terrain segments, voltage selection, and total distance.
    """
    return await optimise_route(
        site_lat, site_lon, sub_lat, sub_lon,
        capacity_mw, voltage_kv=voltage_kv, pool=pool,
    )


@router.get("/best-route")
async def cable_best_route(
    lat: float = Query(..., description="Site latitude"),
    lon: float = Query(..., description="Site longitude"),
    capacity_mw: float = Query(..., ge=0.1, description="Project capacity in MW"),
    radius_km: float = Query(20.0, ge=1, le=50, description="Search radius for substations (km)"),
    max_candidates: int = Query(5, ge=1, le=10, description="Max substations to evaluate"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find best cable route from site to nearest substations.

    Queries nearby substations, computes route to each, and returns
    ranked by total P50 cost with trade-off annotations.
    """
    return await find_best_route(
        lat, lon, capacity_mw, pool,
        search_radius_km=radius_km,
        max_candidates=max_candidates,
    )


@router.get("/cost-estimate")
async def cable_cost_estimate(
    distance_km: float = Query(..., ge=0.1, description="Cable route distance in km"),
    voltage_kv: int = Query(33, description="Voltage level (11/33/66/132)"),
    terrain: str = Query("rural", description="Terrain type: rural, urban, mixed, woodland"),
):
    """Quick cable cost lookup without route computation.

    Returns cost breakdown with P10/P50/P90 bands for given
    distance, voltage, and terrain type.
    """
    return quick_cost_estimate(distance_km, voltage_kv, terrain)


@router.get("/voltage-options")
async def cable_voltage_options(
    capacity_mw: float = Query(..., ge=0.1, description="Project capacity in MW"),
    distance_km: float = Query(5.0, ge=0.1, description="Assumed cable distance for cost comparison"),
):
    """Compare voltage options for a given capacity with cost implications.

    Shows all voltage levels (11/33/66/132kV), highlights the recommended
    option, and provides cost comparison at the specified distance.
    """
    return voltage_options(capacity_mw, distance_km)
