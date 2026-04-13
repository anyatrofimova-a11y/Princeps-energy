"""Analysis router — PyPSA, pvlib, whitebox-tools, constraint checker, layout engine."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Body, Query, Depends, HTTPException
import asyncpg

from app.deps import get_pool

log = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])

GRID_PYTHON = os.environ.get("GRID_PYTHON", os.path.join(os.path.dirname(__file__), "..", "..", ".venv-grid", "bin", "python"))
UTILS = os.path.join(os.path.dirname(__file__), "..", "..", "utils")


async def _run_subprocess(python: str, script: str, payload: dict, timeout: float = 120) -> dict:
    """Run a subprocess bridge script with JSON stdin/stdout."""
    proc = await asyncio.create_subprocess_exec(
        python, script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdin_bytes = json.dumps(payload).encode()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=stdin_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="Analysis timed out")

    if proc.returncode != 0:
        err = stderr.decode()[:500] if stderr else "Unknown error"
        log.error("Subprocess %s failed: %s", script, err)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {err}")

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid response from analysis subprocess")


# ── PyPSA ─────────────────────────────────────────────────────────────────

@router.post("/api/analysis/pypsa-opf")
async def pypsa_opf(body: dict = Body(...)):
    """Run PyPSA Optimal Power Flow."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pypsa_runner.py"), {"action": "opf", "params": body})


@router.post("/api/analysis/pypsa-lopf")
async def pypsa_lopf(body: dict = Body(...)):
    """Run PyPSA Linear OPF with investment optimization."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pypsa_runner.py"), {"action": "lopf", "params": body})


@router.post("/api/analysis/pypsa-expansion")
async def pypsa_expansion(body: dict = Body(...)):
    """Run PyPSA network expansion planning."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pypsa_runner.py"), {"action": "expansion", "params": body})


@router.post("/api/analysis/hosting-capacity")
async def pypsa_hosting(body: dict = Body(...)):
    """Binary search for max hosting capacity at a bus."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pypsa_runner.py"), {"action": "hosting_capacity", "params": body}, timeout=300)


# ── pvlib ─────────────────────────────────────────────────────────────────

@router.post("/api/analysis/pvlib-simulate")
async def pvlib_simulate(body: dict = Body(...)):
    """Full PV simulation with CEC module database."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pvlib_runner.py"), {"action": "simulate", "params": body})


@router.post("/api/analysis/pvlib-bifacial")
async def pvlib_bifacial(body: dict = Body(...)):
    """Bifacial yield estimation."""
    return await _run_subprocess(GRID_PYTHON, os.path.join(UTILS, "pvlib_runner.py"), {"action": "bifacial", "params": body})


# ── Whitebox-tools ────────────────────────────────────────────────────────

@router.post("/api/analysis/viewshed")
async def viewshed_analysis(body: dict = Body(...)):
    """Viewshed analysis from observer point."""
    return await _run_subprocess("python3", os.path.join(UTILS, "whitebox_runner.py"), {"action": "viewshed", "params": body})


@router.post("/api/analysis/terrain-slope")
async def terrain_slope(body: dict = Body(...)):
    """Slope analysis from DEM."""
    return await _run_subprocess("python3", os.path.join(UTILS, "whitebox_runner.py"), {"action": "slope", "params": body})


# ── Constraint Checker ────────────────────────────────────────────────────

@router.post("/api/analysis/constraint-check")
async def constraint_check(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(2.0, ge=0.5, le=10),
):
    """Run all UK planning constraint checks at a location."""
    from utils.constraint_checker import check_all_constraints
    return await check_all_constraints(lat, lon, radius_km)


# ── Layout Engine ─────────────────────────────────────────────────────────

@router.post("/api/design/auto-layout")
async def auto_layout(body: dict = Body(...)):
    """Auto-generate site layout from boundary polygon and design profile."""
    from utils.layout_engine import generate_hybrid_layout, generate_solar_layout, generate_bess_layout, generate_dc_layout

    layout_type = body.get("type", "hybrid")
    boundary = body.get("boundary")
    exclusions = body.get("exclusions", [])

    if not boundary:
        raise HTTPException(status_code=400, detail="boundary GeoJSON required")

    if layout_type == "solar":
        return generate_solar_layout(boundary, exclusions, body.get("profile"))
    elif layout_type == "bess":
        return generate_bess_layout(boundary, exclusions, body.get("profile"))
    elif layout_type == "dc":
        return generate_dc_layout(boundary, exclusions, body.get("profile"))
    else:
        return generate_hybrid_layout(boundary, exclusions, body.get("config"))


@router.post("/api/design/buildable-area")
async def buildable_area(body: dict = Body(...)):
    """Compute buildable vs excluded areas given constraint layers."""
    from utils.layout_engine import compute_buildable_area

    boundary = body.get("boundary")
    if not boundary:
        raise HTTPException(status_code=400, detail="boundary GeoJSON required")

    return compute_buildable_area(boundary, body.get("constraints", {}))


# ── #1 Flexible Interconnection ───────────────────────────────────────────

@router.post("/api/grid/operating-envelope")
async def operating_envelope(lat: float = Query(...), lon: float = Query(...), capacity_mw: float = Query(50), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.flexible_interconnection import compute_operating_envelope
    async with pool.acquire() as conn:
        return await compute_operating_envelope(conn, lat, lon, capacity_mw)


@router.post("/api/grid/curtailment-estimate")
async def curtailment_estimate(body: dict = Body(...)):
    from utils.flexible_interconnection import estimate_curtailment
    return estimate_curtailment(body["envelope_mw"], body["generation_profile_24h"], body["capacity_mw"], body.get("electricity_price", 50))


@router.post("/api/grid/connection-strategies")
async def connection_strategies(lat: float = Query(...), lon: float = Query(...), capacity_mw: float = Query(50), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.flexible_interconnection import compare_connection_strategies
    async with pool.acquire() as conn:
        return await compare_connection_strategies(conn, lat, lon, capacity_mw)


# ── #2 CFE Matching ───────────────────────────────────────────────────────

@router.post("/api/analysis/cfe-score")
async def cfe_score(body: dict = Body(...)):
    from utils.cfe_matching import compute_cfe_score
    return compute_cfe_score(**body)


@router.post("/api/analysis/cfe-gap")
async def cfe_gap(body: dict = Body(...)):
    from utils.cfe_matching import compute_cfe_score, gap_analysis
    result = compute_cfe_score(**body.get("cfe_params", {}))
    return gap_analysis(body.get("load_mw", 50), result, body.get("target_pct", 90))


@router.post("/api/analysis/cfe-optimize")
async def cfe_optimize(body: dict = Body(...)):
    from utils.cfe_matching import optimal_cfe_portfolio
    return optimal_cfe_portfolio(**body)


# ── #3 Water Stress ───────────────────────────────────────────────────────

@router.post("/api/analysis/water-stress")
async def water_stress(lat: float = Query(...), lon: float = Query(...)):
    from utils.water_stress_analyser import assess_water_stress
    return await assess_water_stress(lat, lon)


@router.post("/api/analysis/cooling-strategy")
async def cooling_strategy(body: dict = Body(...)):
    from utils.water_stress_analyser import compare_cooling_strategies
    return compare_cooling_strategies(body.get("it_load_mw", 50), body.get("lat", 52), body.get("lon", -1.5))


@router.post("/api/analysis/water-budget")
async def water_budget_api(body: dict = Body(...)):
    from utils.water_stress_analyser import assess_water_stress, water_budget
    stress = await assess_water_stress(body.get("lat", 52), body.get("lon", -1.5))
    return water_budget(body.get("it_load_mw", 50), body.get("cooling_type", "hybrid"), stress)


# ── #4 Connectivity ───────────────────────────────────────────────────────

@router.post("/api/analysis/connectivity-score")
async def connectivity_score(lat: float = Query(...), lon: float = Query(...)):
    from utils.connectivity_scorer import score_connectivity
    return await score_connectivity(lat, lon)


@router.get("/api/analysis/nearest-ixps")
async def nearest_ixps(lat: float = Query(...), lon: float = Query(...), limit: int = Query(10)):
    from utils.connectivity_scorer import find_nearest_ixps
    return await find_nearest_ixps(lat, lon, limit)


@router.get("/api/analysis/fiber-routes")
async def fiber_routes(lat: float = Query(...), lon: float = Query(...), radius_km: float = Query(10)):
    from utils.connectivity_scorer import find_fiber_routes
    return await find_fiber_routes(lat, lon, radius_km)


# ── #5 System Optimizer ───────────────────────────────────────────────────

@router.post("/api/analysis/optimize-system")
async def optimize_system(body: dict = Body(...)):
    from utils.system_optimizer import optimize_system
    return optimize_system(body)


# ── #6 Regulatory Search ─────────────────────────────────────────────────

@router.post("/api/regulatory/search")
async def regulatory_search(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.regulatory_search import search_regulatory
    async with pool.acquire() as conn:
        return await search_regulatory(conn, body["query"], body.get("limit", 10), body.get("source"), body.get("doc_type"))


@router.post("/api/regulatory/ingest")
async def regulatory_ingest(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.regulatory_search import ingest_document
    async with pool.acquire() as conn:
        return await ingest_document(conn, body["url"], body["source"], body["doc_type"], body.get("title"))


# ── #7 Parcel Search ─────────────────────────────────────────────────────

@router.post("/api/parcels/search")
async def parcels_search(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.parcel_search import search_parcels
    async with pool.acquire() as conn:
        return await search_parcels(conn, body)


@router.post("/api/parcels/score")
async def parcels_score(lat: float = Query(...), lon: float = Query(...), area_ha: float = Query(None), pool: asyncpg.Pool = Depends(get_pool)):
    from utils.parcel_search import score_parcel
    async with pool.acquire() as conn:
        return await score_parcel(conn, lat, lon, area_ha)


# ── #8 BTM Power ─────────────────────────────────────────────────────────

@router.post("/api/analysis/btm-dispatch")
async def btm_dispatch(body: dict = Body(...)):
    from utils.btm_power_model import simulate_btm_dispatch
    return simulate_btm_dispatch(body)


@router.post("/api/analysis/btm-reliability")
async def btm_reliability(body: dict = Body(...)):
    from utils.btm_power_model import assess_reliability
    return assess_reliability(body)


@router.post("/api/analysis/btm-sankey")
async def btm_sankey(body: dict = Body(...)):
    from utils.btm_power_model import simulate_btm_dispatch, power_flow_sankey
    result = simulate_btm_dispatch(body)
    return power_flow_sankey(result["dispatch_24h"])


# ── #9 Construction Risk ─────────────────────────────────────────────────

@router.post("/api/analysis/construction-timeline")
async def construction_timeline(body: dict = Body(...)):
    from utils.construction_risk import estimate_construction_timeline
    return estimate_construction_timeline(body.get("project_type", "dc"), body.get("capacity_mw", 50))


@router.post("/api/analysis/construction-monte-carlo")
async def construction_mc(body: dict = Body(...)):
    from utils.construction_risk import monte_carlo_schedule
    return monte_carlo_schedule(body.get("project_type", "dc"), body.get("capacity_mw", 50), body.get("simulations", 1000))


@router.post("/api/analysis/supply-chain")
async def supply_chain(body: dict = Body(...)):
    from utils.construction_risk import assess_supply_chain
    return assess_supply_chain(body.get("project_type", "dc"), body.get("capacity_mw", 50))


@router.post("/api/analysis/construction-cost")
async def construction_cost(body: dict = Body(...)):
    from utils.construction_risk import estimate_construction_cost
    return estimate_construction_cost(body.get("project_type", "dc"), body.get("capacity_mw", 50))


# ── #10 Multi-Country ────────────────────────────────────────────────────

@router.get("/api/analysis/countries")
async def list_countries():
    from utils.country_adapter import list_countries
    return list_countries()


@router.get("/api/analysis/country/{code}")
async def get_country(code: str):
    from utils.country_adapter import get_adapter
    a = get_adapter(code)
    return {"code": a.code, "name": a.name, "currency": a.currency, "srid": a.srid,
            "voltage_levels": a.voltage_levels, "electricity_price_avg": a.electricity_price_avg,
            "grid_connection_costs": a.grid_connection_costs, "planning_constraints": a.planning_constraints}
