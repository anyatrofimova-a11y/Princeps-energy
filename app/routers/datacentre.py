"""Data centre co-location router — scoring, scanning, infrastructure, capacity map,
   comparison, CFE, cooling, constraints, incentives, regulatory, reports, prospecting."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool
from utils.dc_colocation_scorer import (
    score_dc_site,
    scan_dc_sites,
    dc_capacity_map_geojson,
    get_facility_profiles,
)

log = logging.getLogger("princeps.dc_router")
router = APIRouter(tags=["datacentre"])


# ---------------------------------------------------------------------------
# Existing endpoints (unchanged)
# ---------------------------------------------------------------------------

@router.post("/api/dc/score")
async def api_dc_score(
    lat: float = Query(51.5, description="Latitude (WGS84)"),
    lon: float = Query(-0.1, description="Longitude (WGS84)"),
    capacity_mw: float = Query(10, description="Required IT load in MW"),
    profile: str = Query("colocation", description="Facility profile: google_hyperscale, hyperscale, colocation, edge, custom"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Score a single site for data centre co-location suitability."""
    async with pool.acquire() as conn:
        result = await score_dc_site(conn, lat, lon, capacity_mw, profile)
    return result


@router.post("/api/dc/scan")
async def api_dc_scan(
    profile: str = Query("colocation"),
    capacity_mw: float = Query(10),
    min_headroom_mw: float = Query(None, description="Minimum demand headroom filter (MW)"),
    west: float = Query(None), south: float = Query(None),
    east: float = Query(None), north: float = Query(None),
    limit: int = Query(50, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Batch scan substations for DC site suitability."""
    bbox = None
    if all(v is not None for v in (west, south, east, north)):
        bbox = {"west": west, "south": south, "east": east, "north": north}
    async with pool.acquire() as conn:
        result = await scan_dc_sites(conn, profile, capacity_mw, bbox, min_headroom_mw, limit)
    return result


@router.get("/api/dc/infrastructure")
async def api_dc_infrastructure(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    radius_km: float = Query(20, description="Search radius in km"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Get fibre/IXP/water/DC proximity for a location."""
    radius_m = radius_km * 1000
    async with pool.acquire() as conn:
        fibre = await conn.fetch("""
            SELECT name, operator, pop_type,
                   ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km,
                   lat, lon
            FROM dc_fibre_pops
            WHERE ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), $3)
            ORDER BY dist_km LIMIT 20
        """, lon, lat, radius_m)

        ixps = await conn.fetch("""
            SELECT name, city, participants,
                   ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km,
                   lat, lon
            FROM dc_ixp_nodes
            ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 5
        """, lon, lat)

        water = await conn.fetch("""
            SELECT name, water_type,
                   ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km,
                   lat, lon
            FROM dc_water_bodies
            WHERE ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), $3)
            ORDER BY dist_km LIMIT 10
        """, lon, lat, radius_m)

        dcs = await conn.fetch("""
            SELECT name, operator,
                   ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km,
                   lat, lon
            FROM dc_facilities
            WHERE ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), $3)
            ORDER BY dist_km LIMIT 10
        """, lon, lat, radius_m)

    return {
        "fibre_pops": [dict(r) for r in fibre],
        "ixp_nodes": [dict(r) for r in ixps],
        "water_bodies": [dict(r) for r in water],
        "dc_facilities": [dict(r) for r in dcs],
    }


@router.get("/api/dc/profiles")
async def api_dc_profiles():
    """Available facility profiles with default weights and gates."""
    return get_facility_profiles()


@router.get("/api/dc/capacity-map")
async def api_dc_capacity_map(
    profile: str = Query("colocation"),
    min_headroom_mw: float = Query(5),
    west: float = Query(None), south: float = Query(None),
    east: float = Query(None), north: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON of substations colored by DC suitability."""
    bbox = None
    if all(v is not None for v in (west, south, east, north)):
        bbox = {"west": west, "south": south, "east": east, "north": north}
    async with pool.acquire() as conn:
        return await dc_capacity_map_geojson(conn, profile, min_headroom_mw, bbox)


# ---------------------------------------------------------------------------
# NEW endpoints — Phase 3
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    sites: list[dict]  # [{"lat": float, "lon": float, "name": str}]
    capacity_mw: float = 100
    profile: str = "google_hyperscale"
    custom_weights: dict | None = None


@router.post("/api/dc/compare")
async def api_dc_compare(req: CompareRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Multi-site comparison with full 15-dimension scoring."""
    from utils.dc_site_comparator import compare_dc_sites
    async with pool.acquire() as conn:
        return await compare_dc_sites(conn, req.sites, req.capacity_mw, req.profile, req.custom_weights)


@router.get("/api/dc/cfe")
async def api_dc_cfe(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(100),
    target_cfe_pct: float = Query(90.0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """24/7 CFE% assessment for a location."""
    from utils.dc_cfe_scorer import score_cfe
    async with pool.acquire() as conn:
        return await score_cfe(conn, lat, lon, capacity_mw, target_cfe_pct)


@router.get("/api/dc/cooling")
async def api_dc_cooling(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(10),
    cooling_type: str = Query("hybrid"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Cooling analysis — PUE/WUE/free cooling hours."""
    from utils.dc_cooling_analyser import analyse_cooling
    async with pool.acquire() as conn:
        return await analyse_cooling(conn, lat, lon, capacity_mw, cooling_type)


@router.get("/api/dc/constraints")
async def api_dc_constraints(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    radius_m: float = Query(1000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Constraint overlay check — SSSI, AONB, Green Belt, flood zones."""
    from utils.dc_constraint_overlay import check_constraints
    async with pool.acquire() as conn:
        return await check_constraints(conn, lat, lon, radius_m)


@router.get("/api/dc/water-stress")
async def api_dc_water_stress(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(10),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Water stress assessment for cooling strategy."""
    from utils.dc_water_stress import assess_water_stress
    async with pool.acquire() as conn:
        return await assess_water_stress(conn, lat, lon, capacity_mw)


@router.get("/api/dc/incentives")
async def api_dc_incentives(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Enterprise zone / freeport / investment zone check."""
    from utils.dc_incentives import score_incentives
    async with pool.acquire() as conn:
        return await score_incentives(conn, lat, lon, capacity_mw)


@router.get("/api/dc/regulatory")
async def api_dc_regulatory(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """NSIP eligibility + TM04+ gate status + planning authority."""
    from utils.dc_regulatory_intel import assess_regulatory
    async with pool.acquire() as conn:
        return await assess_regulatory(conn, lat, lon, capacity_mw)


@router.post("/api/dc/report")
async def api_dc_report(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    site_name: str = Query("Candidate Site"),
    capacity_mw: float = Query(100),
    profile: str = Query("google_hyperscale"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate executive PDF report for a DC site assessment."""
    from utils.dc_report_generator import generate_dc_report
    async with pool.acquire() as conn:
        pdf_bytes = await generate_dc_report(conn, lat, lon, site_name, capacity_mw, profile)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="dc-report-{site_name.replace(" ", "-").lower()}.pdf"'},
    )


@router.get("/api/dc/google-sites")
async def api_dc_google_sites(
    capacity_mw: float = Query(100),
    profile: str = Query("google_hyperscale"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Pre-scored Google UK sites (Waltham Cross, North Weald, Purfleet, Teesside)."""
    from utils.dc_site_comparator import score_google_sites
    async with pool.acquire() as conn:
        return await score_google_sites(conn, capacity_mw, profile)


class ProspectRequest(BaseModel):
    query: str = "Find 200+ acre sites near London with >100MW headroom"
    capacity_mw: float = 100
    profile: str = "google_hyperscale"
    min_headroom_mw: float = 50
    limit: int = 20


@router.post("/api/dc/prospect")
async def api_dc_prospect(req: ProspectRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """AI-driven site discovery from natural language query."""
    # Parse query for constraints, then run scan with extended scoring
    from utils.dc_site_comparator import score_dc_site_extended
    async with pool.acquire() as conn:
        # Use scan_dc_sites as base, then extend top results
        base = await scan_dc_sites(
            conn, req.profile, req.capacity_mw,
            min_headroom_mw=req.min_headroom_mw, limit=req.limit,
        )
        # Extend top results with 15-dimension scoring
        extended_sites = []
        for site in base.get("sites", [])[:req.limit]:
            try:
                ext = await score_dc_site_extended(
                    conn, site["lat"], site["lon"], req.capacity_mw, req.profile,
                )
                ext["substation_name"] = site.get("substation_name")
                extended_sites.append(ext)
            except Exception as e:
                log.warning("Extended scoring failed for %s: %s", site.get("substation_name"), e)
                extended_sites.append(site)

        extended_sites.sort(key=lambda s: s.get("dc_score", 0), reverse=True)

    return {
        "query": req.query,
        "profile": req.profile,
        "capacity_mw": req.capacity_mw,
        "count": len(extended_sites),
        "sites": extended_sites,
    }


@router.post("/api/dc/score-extended")
async def api_dc_score_extended(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    capacity_mw: float = Query(100),
    profile: str = Query("google_hyperscale"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Full 15-dimension extended scoring for a single site."""
    from utils.dc_site_comparator import score_dc_site_extended
    async with pool.acquire() as conn:
        return await score_dc_site_extended(conn, lat, lon, capacity_mw, profile)


# ---------------------------------------------------------------------------
# SustainDC Physics Engine (HPE dc-rl integration)
# ---------------------------------------------------------------------------

import asyncio
import json as _json
import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_GRID_PYTHON = os.environ.get("GRID_PYTHON", os.path.join(_PROJECT_ROOT, ".venv-grid", "bin", "python"))
_DC_RL_RUNNER = os.path.join(_PROJECT_ROOT, "utils", "dc_rl_runner.py")


async def _run_dc_rl(command: str, params: dict) -> dict:
    """Subprocess bridge to dc_rl_runner.py (runs in .venv-grid/)."""
    proc = await asyncio.create_subprocess_exec(
        _GRID_PYTHON, _DC_RL_RUNNER, command, _json.dumps(params),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_PROJECT_ROOT,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error("dc_rl_runner %s failed: %s", command, stderr.decode())
        return {"error": stderr.decode().strip()}
    return _json.loads(stdout.decode())


class DCSimulateRequest(BaseModel):
    it_load_pct: float = 60
    ambient_temp_c: float = 18
    crac_setpoint_c: float = 18
    capacity_mw: float = 1.0


@router.post("/api/dc/simulate")
async def api_dc_simulate(req: DCSimulateRequest):
    """Single-timestep physics simulation using HPE SustainDC thermal model.
    Returns IT power, HVAC breakdown (CRAC/chiller/CT/pumps), PUE, temperatures, water usage."""
    return await _run_dc_rl("simulate", req.model_dump())


class DCSimulate24hRequest(BaseModel):
    it_load_mw: float = 50
    hourly_ambient_c: list[float] = [15] * 24
    hourly_it_load_pct: list[float] = [60] * 24
    hourly_carbon_gco2_kwh: list[float] = [200] * 24
    crac_setpoint_c: float = 18
    battery_mwh: float = 0
    battery_soc_pct: float = 50


@router.post("/api/dc/simulate-24h")
async def api_dc_simulate_24h(req: DCSimulate24hRequest):
    """24-hour hourly physics simulation with weather, carbon intensity, and optional battery.
    Returns hourly IT/HVAC/PUE/carbon/water metrics + daily summary."""
    return await _run_dc_rl("simulate_24h", req.model_dump())


@router.post("/api/dc/optimise")
async def api_dc_optimise(req: DCSimulate24hRequest):
    """Carbon-optimised 24h simulation — compares baseline (no battery) vs optimised (battery
    shifts demand to low-carbon periods). Returns savings in carbon, energy, and water."""
    return await _run_dc_rl("optimise", req.model_dump())


class DCBatteryRequest(BaseModel):
    capacity_mwh: float = 100
    soc_pct: float = 50
    action_mw: float = 0
    dt_hours: float = 1.0
    eff_charge: float = 0.95
    eff_discharge: float = 0.95
    max_c_rate: float = 0.5
    max_d_rate: float = 1.0


@router.post("/api/dc/battery")
async def api_dc_battery(req: DCBatteryRequest):
    """Standalone battery physics step — charge/discharge with efficiency curves, C-rate limits.
    Based on dc-rl Battery2 model (CLC lithium NMC cell model)."""
    return await _run_dc_rl("battery", req.model_dump())


class DCPowerCurveRequest(BaseModel):
    model: str = "linear"
    max_power_w: float = 500
    idle_power_w: float = 200
    num_servers: int = 1000
    calibration: float = 1.4
    asym_util: float = 0.3
    dvfs: bool = False


@router.post("/api/dc/power-curve")
async def api_dc_power_curve(req: DCPowerCurveRequest):
    """Generate a server power consumption curve using OpenDC power models.
    8 models: constant, linear, square, cubic, sqrt, mse, asymptotic, interpolate."""
    return await _run_dc_rl("power_curve", req.model_dump())


class DCLifecycleCarbonRequest(BaseModel):
    annual_energy_mwh: float = 50000
    grid_carbon_gco2_kwh: float = 200
    num_servers: int = 1000
    server_type: str = "standard_1u"
    facility_lifetime_years: int = 25


@router.post("/api/dc/lifecycle-carbon")
async def api_dc_lifecycle_carbon(req: DCLifecycleCarbonRequest):
    """Calculate full lifecycle carbon (operational + embodied hardware manufacturing).
    Embodied carbon data from OpenDC (TU Delft) research, MIT licensed."""
    return await _run_dc_rl("lifecycle_carbon", req.model_dump())
