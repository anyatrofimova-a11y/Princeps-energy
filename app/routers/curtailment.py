"""Curtailment Intelligence router — analyse / portfolio screen / scenarios."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool
from utils.curtailment_intelligence import (
    analyse,
    screen_portfolio,
    list_scenarios,
    get_stats,
    compute_sensitivity_for_asset,
    estimate_curtailment_pct,
    get_queue_rank,
    get_profile,
)

router = APIRouter(tags=["curtailment"], prefix="/api/curtailment")


@router.post("/analyse")
async def analyse_project(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Full curtailment analysis — accepts lat/lon/capacity/tech/project_id/scenario."""
    lat = body.get("lat")
    lon = body.get("lon")
    capacity_mw = body.get("capacity_mw")
    technology = body.get("technology", "solar")
    project_id = body.get("project_id")
    scenario = body.get("scenario", "base")

    if lat is None or lon is None or capacity_mw is None:
        raise HTTPException(400, "lat, lon, capacity_mw required")

    return await analyse(
        pool,
        lat=float(lat),
        lon=float(lon),
        capacity_mw=float(capacity_mw),
        technology=technology,
        project_id=project_id,
        scenario=scenario,
    )


@router.get("/analyse")
async def analyse_get(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(...),
    technology: str = Query("solar"),
    project_id: str | None = Query(None),
    scenario: str = Query("base"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GET-style analyse for quick browser calls."""
    return await analyse(
        pool, lat=lat, lon=lon, capacity_mw=capacity_mw,
        technology=technology, project_id=project_id, scenario=scenario,
    )


@router.post("/portfolio/screen")
async def portfolio_screen(
    scenario: str = Query("base"),
    limit: int = Query(200, ge=1, le=1000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Batch-screen every project in the portfolio — the league table data."""
    return await screen_portfolio(pool, scenario=scenario, limit=limit)


@router.get("/constraints/near")
async def constraints_near(
    lat: float = Query(...),
    lon: float = Query(...),
    limit: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Binding constraints near a point with sensitivity factors."""
    return await compute_sensitivity_for_asset(pool, f"query:{lat},{lon}", lat, lon, max_constraints=limit)


@router.get("/queue-rank/{project_id}")
async def queue_rank(
    project_id: str,
    constraint_group: str = Query(""),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """LIFO queue rank for a project in a given constraint group."""
    return await get_queue_rank(pool, project_id=project_id, constraint_group=constraint_group)


@router.get("/scenarios")
async def scenarios(pool: asyncpg.Pool = Depends(get_pool)):
    """List available curtailment scenarios."""
    return await list_scenarios(pool)


@router.get("/profiles/{profile_id}")
async def profile(profile_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Fetch a generator profile (8760 hourly factors)."""
    p = await get_profile(pool, profile_id)
    if not p:
        raise HTTPException(404, f"Profile {profile_id} not found")
    return p


@router.get("/stats")
async def stats(pool: asyncpg.Pool = Depends(get_pool)):
    """Summary stats for the Pulse header strip."""
    return await get_stats(pool)
