"""Grid Queue Intelligence router — TEC register analysis, timeline prediction,
cost benchmarking, and opportunity identification."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from utils.grid_queue_intelligence import (
    analyse_queue,
    predict_offer_timeline,
    connection_cost_benchmark,
    find_opportunities,
    queue_summary,
)

router = APIRouter(prefix="/api/grid-queue", tags=["grid-queue"])


@router.get("/analyse/{connection_site}")
async def api_analyse_queue(request: Request, connection_site: str):
    """Deep queue analysis for a connection site."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        return await analyse_queue(conn, connection_site)


@router.get("/predict")
async def api_predict_timeline(
    request: Request,
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mw: float = Query(..., ge=0.1, description="Project capacity in MW"),
    technology: str = Query("solar", description="Technology type"),
    voltage_kv: float | None = Query(None, description="Target voltage kV (auto if omitted)"),
    radius_km: float = Query(30.0, ge=1, le=100, description="Search radius km"),
):
    """Predict connection offer timeline with P10/P50/P90."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        return await predict_offer_timeline(
            conn,
            lat=lat,
            lon=lon,
            capacity_mw=capacity_mw,
            technology=technology,
            voltage_kv=voltage_kv,
            search_radius_km=radius_km,
        )


@router.get("/benchmark")
async def api_cost_benchmark(
    capacity_mw: float = Query(..., ge=0.1, description="Project capacity MW"),
    voltage_kv: float = Query(33, description="Connection voltage kV"),
    distance_km: float = Query(5.0, ge=0.1, description="Cable distance km"),
    region: str | None = Query(None, description="UK region for cost adjustment"),
):
    """Connection cost benchmarking with P10/P50/P90."""
    return connection_cost_benchmark(
        capacity_mw=capacity_mw,
        voltage_kv=voltage_kv,
        distance_km=distance_km,
        region=region,
    )


@router.get("/opportunities")
async def api_find_opportunities(
    request: Request,
    region: str | None = Query(None, description="UK region filter"),
    technology: str | None = Query(None, description="Technology filter"),
    min_headroom_mw: float = Query(10.0, ge=0, description="Minimum headroom MW"),
    limit: int = Query(30, ge=1, le=100, description="Max results per category"),
):
    """Find grid queue opportunities — withdrawn capacity, low-queue sites."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        return await find_opportunities(
            conn,
            region=region,
            technology=technology,
            min_headroom_mw=min_headroom_mw,
            limit=limit,
        )


@router.get("/summary")
async def api_queue_summary(request: Request):
    """UK-wide TEC queue statistics."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        return await queue_summary(conn)
