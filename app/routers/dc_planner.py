"""DC Planner router — capacity planning, telemetry, facility design."""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.dc_planner import plan_facility, simulate_telemetry

router = APIRouter(tags=["dc-planner"])


@router.get("/api/dc/plan")
async def api_dc_plan(
    it_load_kw: float = Query(10000, description="IT load in kW"),
    redundancy: str = Query("N+1", description="N, N+1, 2N, 2N+1"),
    cooling_type: str = Query("hybrid", description="mechanical, free_cooling, hybrid, evaporative"),
    rack_density_kw: float = Query(8.0, description="Average kW per rack"),
    target_pue: float = Query(1.3),
    tier: int = Query(3, ge=1, le=4, description="Uptime Institute Tier 1-4"),
    lat: float = Query(52.5),
):
    """Generate a complete DC facility plan from IT load."""
    return plan_facility(
        it_load_kw=it_load_kw,
        redundancy=redundancy,
        cooling_type=cooling_type,
        rack_density_kw=rack_density_kw,
        target_pue=target_pue,
        tier=tier,
        lat=lat,
    )


@router.get("/api/dc/telemetry")
async def api_dc_telemetry(
    it_load_kw: float = Query(10000),
    rack_count: int = Query(100),
    cooling_type: str = Query("hybrid"),
):
    """Get simulated real-time DC telemetry snapshot."""
    return simulate_telemetry(
        it_load_kw=it_load_kw,
        rack_count=rack_count,
        cooling_type=cooling_type,
    )
