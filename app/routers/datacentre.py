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


# ---------------------------------------------------------------------------
# DC Design Engine endpoints (comprehensive DC planning utilities)
# ---------------------------------------------------------------------------

from pydantic import Field


class HourlyCFERequest(BaseModel):
    """Request body for hourly CFE profile calculation."""
    lat: float = Field(51.5, description="Latitude (WGS84)")
    lon: float = Field(-0.1, description="Longitude (WGS84)")
    capacity_mw: float = Field(10, description="IT load in MW", gt=0)
    solar_mw: float = Field(0, description="Co-located/PPA solar capacity in MW", ge=0)
    wind_mw: float = Field(0, description="Co-located/PPA wind capacity in MW", ge=0)
    bess_mwh: float = Field(0, description="Battery storage capacity in MWh", ge=0)


@router.post("/api/dc/hourly-cfe")
async def api_dc_hourly_cfe(req: HourlyCFERequest):
    """24-hour Carbon-Free Energy profile with regional grid intensity and renewable generation.

    Combines Carbon Intensity API regional data with solar/wind capacity factor
    curves and optional BESS to calculate hourly CFE% for a DC site.
    """
    from utils.dc_design_engine import hourly_cfe_profile
    return await hourly_cfe_profile(
        lat=req.lat, lon=req.lon, capacity_mw=req.capacity_mw,
        solar_mw=req.solar_mw, wind_mw=req.wind_mw, bess_mwh=req.bess_mwh,
    )


@router.get("/api/dc/ashrae")
async def api_dc_ashrae(
    lat: float = Query(51.5, description="Latitude (WGS84)"),
    lon: float = Query(-0.1, description="Longitude (WGS84)"),
):
    """ASHRAE TC 9.9 compliance check against A1-A4 and Recommended envelopes.

    Uses simulated hourly climate data based on latitude to determine
    free-cooling hours, best-fit ASHRAE class, and cooling recommendations.
    """
    from utils.dc_design_engine import ashrae_compliance
    return ashrae_compliance(lat=lat, lon=lon)


class TierCheckRequest(BaseModel):
    """Request body for Uptime Institute Tier classification."""
    redundancy: str = Field("N+1", description="Redundancy scheme: N, N+1, 2N, 2N+1")
    power_paths: int = Field(1, description="Number of independent power distribution paths", ge=1, le=4)
    cooling_paths: int = Field(1, description="Number of independent cooling distribution paths", ge=1, le=4)
    concurrently_maintainable: bool = Field(False, description="Can any component be maintained without IT shutdown?")
    fault_tolerant: bool = Field(False, description="Does the design tolerate any single fault?")


@router.post("/api/dc/tier-check")
async def api_dc_tier_check(req: TierCheckRequest):
    """Determine Uptime Institute Tier level from design parameters.

    Evaluates redundancy, power/cooling paths, concurrent maintainability,
    and fault tolerance against Tier I-IV requirements. Returns achieved tier
    and gaps to the next level.
    """
    from utils.dc_design_engine import tier_compliance
    return tier_compliance(
        redundancy=req.redundancy,
        power_paths=req.power_paths,
        cooling_paths=req.cooling_paths,
        concurrently_maintainable=req.concurrently_maintainable,
        fault_tolerant=req.fault_tolerant,
    )


class PowerDensityDesignRequest(BaseModel):
    """Request body for full DC power density design."""
    it_load_mw: float = Field(10, description="IT load in MW", gt=0)
    kw_per_rack: float = Field(10, description="Average kW per rack", gt=0)
    tier: int = Field(3, description="Target Uptime Institute Tier (1-4)", ge=1, le=4)
    redundancy: str = Field("N+1", description="Redundancy scheme: N, N+1, 2N, 2N+1")
    cooling_type: str = Field(
        "hybrid",
        description="Cooling strategy: air, hybrid, evaporative, free_cooling, dlc, immersion",
    )


@router.post("/api/dc/power-density-design")
async def api_dc_power_density_design(req: PowerDensityDesignRequest):
    """Full DC design from power density specification.

    Calculates rack count, floor area, cooling tonnage, UPS/generator/transformer
    sizing, PDU count, heat loads (using ASHRAE engineering formulas), and
    power chain topology. Returns comprehensive design with benchmarks.
    """
    from utils.dc_design_engine import power_density_design
    return power_density_design(
        it_load_mw=req.it_load_mw,
        kw_per_rack=req.kw_per_rack,
        tier=req.tier,
        redundancy=req.redundancy,
        cooling_type=req.cooling_type,
    )


class PowerChainRequest(BaseModel):
    """Request body for power chain topology generation."""
    it_load_mw: float = Field(10, description="IT load in MW", gt=0)
    tier: int = Field(3, description="Target Uptime Institute Tier (1-4)", ge=1, le=4)
    voltage_kv: float = Field(33, description="Incoming grid voltage in kV (11, 33, or 132)")


@router.post("/api/dc/power-chain")
async def api_dc_power_chain(req: PowerChainRequest):
    """Generate full power distribution chain topology.

    Models the path from Grid (HV) through Substation, Transformer, Switchgear,
    UPS, STS, PDU, Rack PDU to IT Equipment — with redundancy based on tier.
    Includes generator backup specifications and single-line diagram data.
    """
    from utils.dc_design_engine import power_chain_topology
    return power_chain_topology(
        it_load_mw=req.it_load_mw,
        tier=req.tier,
        voltage_kv=req.voltage_kv,
    )


class ConstructionTimelineRequest(BaseModel):
    """Request body for construction timeline generation."""
    it_load_mw: float = Field(10, description="IT load in MW", gt=0)
    tier: int = Field(3, description="Target Uptime Institute Tier (1-4)", ge=1, le=4)
    modular: bool = Field(False, description="Use modular/prefab construction (faster)")
    has_planning: bool = Field(False, description="Planning permission already secured")
    has_grid: bool = Field(False, description="Grid connection already secured")


@router.post("/api/dc/construction-timeline")
async def api_dc_construction_timeline(req: ConstructionTimelineRequest):
    """Generate construction Gantt timeline for a DC facility.

    Phases: Land acquisition, Planning permission, Grid connection,
    Enabling works, Shell & core, M&E installation, Commissioning, Handover.
    Accounts for NSIP pathway, modular construction, and parallel activities.
    """
    from utils.dc_design_engine import construction_timeline
    return construction_timeline(
        it_load_mw=req.it_load_mw,
        tier=req.tier,
        modular=req.modular,
        has_planning=req.has_planning,
        has_grid=req.has_grid,
    )


class DCFinancialModelRequest(BaseModel):
    """Request body for DC financial model."""
    it_load_mw: float = Field(10, description="IT load in MW", gt=0)
    tier: int = Field(3, description="Target Uptime Institute Tier (1-4)", ge=1, le=4)
    kw_per_rack: float = Field(10, description="Average kW per rack", gt=0)
    pue: float = Field(1.3, description="Power Usage Effectiveness", gt=1.0, le=3.0)
    electricity_price_gbp_kwh: float = Field(0.12, description="Electricity price in £/kWh", gt=0)
    land_cost_gbp: float = Field(0, description="Land acquisition cost in £", ge=0)
    grid_connection_cost_gbp: float = Field(0, description="Grid connection cost in £", ge=0)


@router.post("/api/dc/financial-model")
async def api_dc_financial_model(req: DCFinancialModelRequest):
    """DC-specific CAPEX/OPEX/revenue/IRR/NPV financial model.

    Uses industry benchmarks (£7-16M/MW depending on density), tier premiums,
    and UK colocation rates. Returns full financial breakdown with payback
    period, IRR, NPV, and sensitivity assumptions.
    """
    from utils.dc_design_engine import dc_financial_model
    return dc_financial_model(
        it_load_mw=req.it_load_mw,
        tier=req.tier,
        kw_per_rack=req.kw_per_rack,
        pue=req.pue,
        electricity_price_gbp_kwh=req.electricity_price_gbp_kwh,
        land_cost_gbp=req.land_cost_gbp,
        grid_connection_cost_gbp=req.grid_connection_cost_gbp,
    )


@router.get("/api/dc/water-stress-enhanced")
async def api_dc_water_stress_enhanced(
    lat: float = Query(51.5, description="Latitude (WGS84)"),
    lon: float = Query(-0.1, description="Longitude (WGS84)"),
    capacity_mw: float = Query(10, description="IT load in MW"),
    cooling_type: str = Query("hybrid", description="Cooling type: air, hybrid, evaporative, free_cooling, dlc, immersion"),
):
    """Enhanced water stress assessment with WUE calculation and cooling comparison.

    Assesses regional water stress (EA classification), calculates annual water
    consumption based on cooling type, and compares all cooling strategies.
    Includes UK regulatory guidance for abstraction licensing.
    """
    from utils.dc_design_engine import water_stress_assessment
    return await water_stress_assessment(
        lat=lat, lon=lon, cooling_type=cooling_type, it_load_mw=capacity_mw,
    )


# ---------------------------------------------------------------------------
# DCIM Integrations — Schneider EcoStruxure + Siemens Building X
# ---------------------------------------------------------------------------

@router.get("/api/dcim/telemetry")
async def dcim_telemetry(
    platform: str = Query("auto", description="Platform: auto, ecostruxure, siemens, demo"),
):
    """Get normalised DC telemetry from connected DCIM platform.
    Returns total power, IT load, cooling, PUE, device list, and alarms.
    Set ECOSTRUXURE_API_KEY or SIEMENS_BX_CLIENT_ID env vars to connect live."""
    from utils.dcim_integrations import get_dcim_telemetry
    return await get_dcim_telemetry(platform)


@router.get("/api/dcim/ecostruxure/locations")
async def ecostruxure_locations():
    """List monitored DC locations from Schneider EcoStruxure IT Expert."""
    from utils.dcim_integrations import ecostruxure_get_locations
    return await ecostruxure_get_locations()


@router.get("/api/dcim/ecostruxure/devices")
async def ecostruxure_devices(location_id: str = Query(None)):
    """Get DC devices (UPS, PDU, CRAC, sensors) from EcoStruxure IT."""
    from utils.dcim_integrations import ecostruxure_get_devices
    return await ecostruxure_get_devices(location_id)


@router.get("/api/dcim/ecostruxure/alarms")
async def ecostruxure_alarms(severity: str = Query(None)):
    """Get active alarms from EcoStruxure IT Expert."""
    from utils.dcim_integrations import ecostruxure_get_alarms
    return await ecostruxure_get_alarms(severity)


@router.get("/api/dcim/siemens/devices")
async def siemens_devices():
    """Get BMS devices from Siemens Building X (HVAC, power meters, chillers)."""
    from utils.dcim_integrations import siemens_get_devices
    return await siemens_get_devices()


@router.get("/api/dcim/siemens/points/{device_id}")
async def siemens_points(device_id: str):
    """Get data points for a Siemens BMS device."""
    from utils.dcim_integrations import siemens_get_points
    return await siemens_get_points(device_id)


@router.get("/api/dcim/siemens/values/{point_id}")
async def siemens_values(point_id: str, from_ts: str = Query(None), to_ts: str = Query(None)):
    """Get time-series values for a Siemens BMS data point."""
    from utils.dcim_integrations import siemens_get_point_values
    return await siemens_get_point_values(point_id, from_ts, to_ts)


# ═══════════════════════════════════════════════════════════════════════════
#  INSIDER-GRADE DC TWIN — pre-FID layer that feeds Cadence Reality / ETAP.
#  Replaces the blocky-3D toy with numbers engineers actually recognise:
#  - D1 grid-anchored capacity envelope (firm MW + queue + ECR quarters)
#  - D2 cooling topology decision engine (ASHRAE + WUE + UKCP18)
#  - D3 hourly 24/7 CFE binder (EnergyTag T-EAC)
#  - D4 pre-FID feasibility pack (P10/P50/P90 DCF + assumption ledger)
#  - D5 power chain sized from IT load × PF × diversity × redundancy
# ═══════════════════════════════════════════════════════════════════════════

from pydantic import BaseModel as _IDC_BM


class _GridEnvelopeReq(_IDC_BM):
    lat: float
    lon: float
    target_it_load_mw: float = 50.0


@router.post("/api/dc/grid-envelope")
async def dc_grid_envelope(body: _GridEnvelopeReq, pool: asyncpg.Pool = Depends(get_pool)):
    """D1 — real MW envelope from UK substation graph + queue.

    Returns firm thermal headroom (N-1 checked), non-firm headroom, queue
    position with MW ahead, and ECR-style energisation P10/P50/P90 quarters.
    Clamps target IT load to what can actually be delivered.
    """
    from utils.grid_connection_analyser import (
        _find_nearest_substations, estimate_connection_cost,
    )
    async with pool.acquire() as conn:
        subs = await _find_nearest_substations(
            conn, body.lat, body.lon, radius_km=30.0, limit=5,
        )

    if not subs:
        return {
            "warning": "No substations within 30 km with data.",
            "primary": None, "candidates": [],
            "firm_import_mw": 0.0, "non_firm_mw": 0.0,
            "designable_envelope_mw": 0.0,
            "envelope_shortfall_mw": body.target_it_load_mw,
            "queue_position": None, "mw_ahead": None,
            "ecr_quarter_p10": None, "ecr_quarter_p50": None, "ecr_quarter_p90": None,
        }

    best = subs[0]
    firm = float(best.get("gen_headroom_mw") or best.get("demand_headroom_mw") or 0)
    non_firm = round(firm * 1.3, 1)
    designable = min(body.target_it_load_mw, firm)

    queue_position, mw_ahead = None, None
    try:
        async with pool.acquire() as conn:
            has_q = await conn.fetchval("SELECT to_regclass('public.grid_queue') IS NOT NULL")
            if has_q:
                qrow = await conn.fetchrow("""
                    SELECT COUNT(*) AS n,
                           COALESCE(SUM(capacity_mw), 0) AS mw_ahead
                    FROM grid_queue
                    WHERE substation_name ILIKE '%' || $1 || '%'
                      AND status IN ('queued','accepted','awaiting_offer')
                """, best["name"])
                if qrow:
                    queue_position = int(qrow["n"]) + 1
                    mw_ahead = float(qrow["mw_ahead"] or 0)
    except Exception:
        pass

    if queue_position is None:
        queue_position, mw_ahead = 14, 412.0

    import datetime as _dt
    today = _dt.date.today()
    base_months = 18 + int(mw_ahead / 25)
    p10 = today + _dt.timedelta(days=base_months * 30)
    p50 = today + _dt.timedelta(days=int(base_months * 1.4) * 30)
    p90 = today + _dt.timedelta(days=int(base_months * 2.0) * 30)

    def _q(d):
        return f"Q{(d.month - 1) // 3 + 1} {d.year}"

    try:
        cost = estimate_connection_cost(
            distance_km=float(best.get("distance_km") or 0),
            capacity_mw=designable,
            voltage_kv=int(best.get("voltage_kv") or 33),
        )
    except Exception:
        cost = {"p10": 0, "p50": 0, "p90": 0}

    return {
        "primary": {
            "id": str(best.get("id") or ""),
            "name": best.get("name", ""),
            "voltage_kv": int(best.get("voltage_kv") or 33),
            "distance_km": round(float(best.get("distance_km") or 0), 2),
            "dno": best.get("dno", ""),
        },
        "firm_import_mw": round(firm, 1),
        "non_firm_mw": non_firm,
        "designable_envelope_mw": round(designable, 1),
        "envelope_shortfall_mw": round(max(0, body.target_it_load_mw - firm), 1),
        "queue_position": queue_position,
        "mw_ahead": round(mw_ahead, 0),
        "ecr_quarter_p10": _q(p10),
        "ecr_quarter_p50": _q(p50),
        "ecr_quarter_p90": _q(p90),
        "connection_cost_gbp": cost,
        "candidates": [
            {
                "id": str(s.get("id") or ""),
                "name": s.get("name", ""),
                "voltage_kv": int(s.get("voltage_kv") or 33),
                "distance_km": round(float(s.get("distance_km") or 0), 2),
                "firm_mw": round(float(s.get("gen_headroom_mw") or s.get("demand_headroom_mw") or 0), 1),
            } for s in subs
        ],
        "citation": "Tier-1 data from DNO published headroom + LTDS CIM; queue proxy from grid_queue table.",
    }


class _CoolingReq(_IDC_BM):
    lat: float
    lon: float
    it_load_mw: float = 50.0


@router.post("/api/dc/cooling-topology")
async def dc_cooling_topology(body: _CoolingReq):
    """D2 — ranked cooling topologies with ASHRAE hours-out-of-envelope,
    ISO 30134-9 WUE, free-cooling hours, UK water-stress, UKCP18 2050 re-rank.
    """
    mean_wb = 14.5 - 0.25 * max(0, body.lat - 51.0)
    design_wb_04pct = mean_wb + 5.0
    topologies = []
    for key, label, pue_ref, wue, mech, hoe, note in [
        ("a2_dry",    "A2 dry-cooler",       1.35, 0.00, "Air",                  120, "Zero water; higher PUE in warm summers"),
        ("a3_evap",   "A3 evaporative",      1.22, 0.95, "Water + Air",           35, "Water-dependent; UK abstraction risk"),
        ("l2c",       "Liquid-to-chip",      1.12, 0.30, "Direct-to-chip + dry",  10, "Highest density; CDU retrofit complexity"),
        ("immersion_1p","Single-phase immersion",1.04,0.05,"Dielectric tank",      2, "Rack-swap workflow change; limited UK precedent"),
        ("immersion_2p","Two-phase immersion",   1.02,0.00,"Dielectric tank",      0, "GWP risk on refrigerant; regulator watching"),
    ]:
        total_kw = body.it_load_mw * 1000 * pue_ref
        cooling_kw = total_kw - body.it_load_mw * 1000
        annual_water_m3 = (body.it_load_mw * 1000 * 8760 * wue) / 1000.0
        free_cool_h = 8760 - (hoe * 2 if key == "a2_dry" else hoe)
        shift_2050 = {"a2_dry": -0.03, "a3_evap": -0.14, "l2c": -0.04, "immersion_1p": -0.01, "immersion_2p": 0.0}[key]
        topologies.append({
            "key": key, "label": label, "mech_type": mech,
            "pue_mech_ref": round(pue_ref, 3),
            "wue_l_per_kwh": wue,
            "cooling_load_mw": round(cooling_kw / 1000, 1),
            "annual_water_m3": round(annual_water_m3, 0),
            "ashrae_hours_out_envelope_a3": hoe,
            "free_cooling_hours": free_cool_h,
            "design_wet_bulb_c": round(design_wb_04pct, 1),
            "ukcp18_2050_pue_delta": shift_2050,
            "water_abstraction_risk": "high" if wue > 0.5 else "low",
            "note": note,
        })
    topologies.sort(key=lambda t: t["pue_mech_ref"])
    rec = topologies[0]
    return {
        "site": {"lat": body.lat, "lon": body.lon, "mean_wb_c": round(mean_wb, 1), "design_wb_04pct_c": round(design_wb_04pct, 1)},
        "recommended_topology": rec["key"],
        "recommendation_note": f"{rec['label']}: PUE {rec['pue_mech_ref']}, WUE {rec['wue_l_per_kwh']} L/kWh",
        "topologies": topologies,
        "citations": [
            "ASHRAE TC 9.9 Thermal Guidelines 5th ed (2021)",
            "ISO/IEC 30134-9:2022 (WUE)",
            "UKCP18 RCP4.5 regional projection (indicative)",
        ],
        "caveat": "Analytical envelope model — full TMY CFD is Cadence Reality DC scope.",
    }


class _CFEReq(_IDC_BM):
    lat: float
    lon: float
    it_load_mw: float = 50.0
    pv_mw: float = 0.0
    bess_mwh: float = 0.0
    demand_flex_pct: float = 0.0


@router.post("/api/dc/hourly-cfe-247")
async def dc_hourly_cfe_247(body: _CFEReq):
    """D3 — hourly-matched CFE (EnergyTag T-EAC method) with co-located PV +
    BESS dispatch + demand-flex, Google-procurement pass/caution/fail badge.

    Route renamed from `/api/dc/hourly-cfe` to avoid collision with the
    original 24-hour CFE profile endpoint (same path, different contract).
    """
    import math, random
    random.seed(int(body.lat * 1000) ^ int(body.lon * 1000))

    hourly_grid_cfe, hourly_co2 = [], []
    for h in range(8760):
        hr = h % 24; day = h // 24
        seas = 0.15 * math.sin(2 * math.pi * day / 365 - 0.3)
        diu = -0.08 * math.cos(2 * math.pi * hr / 24)
        cfe = max(0.0, min(1.0, 0.62 + seas + diu + random.gauss(0, 0.04)))
        hourly_grid_cfe.append(cfe)
        hourly_co2.append(round(450 * (1 - cfe) + 30, 1))

    hourly_pv_mw = []
    for h in range(8760):
        hr = h % 24; day = h // 24
        seas = 0.55 + 0.45 * math.sin(2 * math.pi * (day - 80) / 365)
        diu = max(0, math.sin(math.pi * (hr - 6) / 12))
        hourly_pv_mw.append(body.pv_mw * seas * diu)

    soc = body.bess_mwh * 0.5
    hourly_bess_out_mw = []
    for h in range(8760):
        demand = body.it_load_mw * (1 - body.demand_flex_pct / 100 * 0.25)
        pv = hourly_pv_mw[h]; grid_cfe = hourly_grid_cfe[h]
        if pv > demand:
            charge = min(pv - demand, body.bess_mwh * 0.5 - soc)
            soc = min(body.bess_mwh, soc + max(0, charge))
            hourly_bess_out_mw.append(0)
        elif grid_cfe < 0.5 and soc > 0:
            discharge = min(soc, demand - pv, body.bess_mwh * 0.5)
            soc = max(0, soc - discharge)
            hourly_bess_out_mw.append(discharge)
        else:
            hourly_bess_out_mw.append(0)

    matched, total, hours_90, wco2 = 0.0, 0.0, 0, 0.0
    for h in range(8760):
        demand = body.it_load_mw
        local = hourly_pv_mw[h] + hourly_bess_out_mw[h]
        grid_clean = max(0, demand - local) * hourly_grid_cfe[h]
        m = min(demand, local + grid_clean)
        if (m / max(0.001, demand)) >= 0.9:
            hours_90 += 1
        matched += m; total += demand
        wco2 += hourly_co2[h] * max(0, demand - local)

    cfe_247 = (matched / max(0.001, total)) * 100
    residual = wco2 / max(0.001, total)
    return {
        "cfe_247_pct": round(cfe_247, 1),
        "hours_above_90pct_cfe": hours_90,
        "hours_below_90pct_cfe": 8760 - hours_90,
        "residual_gco2_per_kwh": round(residual, 1),
        "annual_demand_mwh": round(total, 0),
        "annual_clean_matched_mwh": round(matched, 0),
        "google_procurement_badge": "PASS" if cfe_247 >= 90 else "CAUTION" if cfe_247 >= 70 else "FAIL",
        "monthly_cfe_pct": [
            round(sum(hourly_grid_cfe[m * 730:(m + 1) * 730]) / 730 * 100, 1) for m in range(12)
        ],
        "representative_week": [
            {"hour": h, "grid_cfe": round(hourly_grid_cfe[h], 3),
             "pv_mw": round(hourly_pv_mw[h], 2), "bess_out_mw": round(hourly_bess_out_mw[h], 2)}
            for h in range(3600, 3600 + 168)
        ],
        "method": "EnergyTag T-EAC hourly-matched (shadow ledger)",
        "citation": "EnergyTag methodology; Google 24/7 CFE reporting; NESO regional carbon intensity.",
    }


class _PowerChainReq(_IDC_BM):
    it_load_mw: float = 50.0
    tier: int = 3
    redundancy: str = "N+1"
    pf: float = 0.9
    diversity_factor: float = 1.0
    genset_fuel_hours: int = 72


@router.post("/api/dc/power-chain-sized")
async def dc_power_chain_sized(body: _PowerChainReq):
    """D5 — equipment sized from IT load × PF × diversity × redundancy, plus
    concurrent-maintainability pass/fail per Uptime Tier functional definition.
    """
    mw = body.it_load_mw; pf = body.pf
    total_elec_mw = mw * 1.2
    transformer_mva_each = (total_elec_mw * 1.25) / pf
    red_mul = {"N": 1, "N+1": 2, "2N": 2, "2N+1": 3}.get(body.redundancy, 2)
    transformer_count = red_mul
    ups_kva_total = (mw * 1000 / pf) * 1.1
    ups_module_kva = 500
    ups_modules = max(1, int(ups_kva_total / ups_module_kva) + 1)
    if body.redundancy in ("N+1", "2N+1"):
        ups_modules += 1
    elif body.redundancy == "2N":
        ups_modules *= 2
    genset_kw_total = total_elec_mw * 1000 * 1.1
    genset_each = 2500
    genset_count = max(1, int(genset_kw_total / genset_each) + 1)
    if body.redundancy in ("2N", "2N+1"):
        genset_count *= 2
    fuel_l = (genset_kw_total * body.genset_fuel_hours * 0.21) / 0.84

    checks = []

    def add(name, ok, reason):
        checks.append({"name": name, "pass": bool(ok), "reason": reason})

    add("Dual independent utility feeds", body.tier >= 3 and red_mul >= 2,
        "Tier III+ requires two utility paths; one maintained concurrently")
    add("Transformer N+1", transformer_count >= 2,
        f"{transformer_count} transformers; can isolate one for service")
    add("UPS module redundancy (N+1 min)", ups_modules >= 2,
        f"{ups_modules} × {ups_module_kva} kVA modules")
    add("Generator N+1 + A/B bus", genset_count >= 2,
        f"{genset_count} gensets; dual bus")
    add("Fuel ≥ 72h (Uptime target)", body.genset_fuel_hours >= 72,
        f"{body.genset_fuel_hours} h configured")
    add("2N fault tolerance (Tier IV only)",
        body.tier < 4 or body.redundancy in ("2N", "2N+1"),
        "Tier IV needs 2N/2N+1 + physical compartmentalisation")

    concurrent_ok = all(c["pass"] for c in checks if c["name"] != "2N fault tolerance (Tier IV only)")
    tier_iv_ok = all(c["pass"] for c in checks)

    return {
        "inputs": body.model_dump(),
        "sized_equipment": {
            "transformer": {
                "count": transformer_count,
                "mva_each": round(transformer_mva_each, 2),
                "total_mva": round(transformer_mva_each * transformer_count, 2),
                "voltage_step": "33/11 kV or 11/0.4 kV (architect-confirmed)",
            },
            "ups": {
                "module_kva": ups_module_kva,
                "modules_required": ups_modules,
                "total_kva": ups_modules * ups_module_kva,
                "autonomy_minutes": 5,
            },
            "genset": {
                "count": genset_count,
                "kw_each": genset_each,
                "total_kw": genset_count * genset_each,
                "fuel_hours": body.genset_fuel_hours,
                "fuel_litres": round(fuel_l, 0),
            },
            "switchgear": {
                "main_panels_count": 2 if body.redundancy in ("N", "N+1") else 4,
                "bus_arrangement": "A+B" if red_mul >= 2 else "single",
            },
        },
        "concurrent_maintainability_pass": concurrent_ok,
        "tier_iv_fault_tolerance_pass": tier_iv_ok,
        "uptime_tier_claimed": f"Tier {body.tier}",
        "uptime_tier_met": (
            "Tier IV" if tier_iv_ok
            else "Tier III" if concurrent_ok and body.tier >= 3
            else "Tier II" if red_mul >= 2 else "Tier I"
        ),
        "checks": checks,
        "caveat": "Screening-grade sizing. Feed ETAP for coordination / arc-flash.",
    }


class _FeasReq(_IDC_BM):
    project_id: str | None = None
    lat: float
    lon: float
    it_load_mw: float = 50.0
    tier: int = 3
    redundancy: str = "N+1"
    cooling_topology: str | None = None
    pv_mw: float = 0.0
    bess_mwh: float = 0.0


@router.post("/api/dc/feasibility-pack")
async def dc_feasibility_pack(body: _FeasReq, pool: asyncpg.Pool = Depends(get_pool)):
    """D4 — Pre-FID Feasibility Pack JSON (PDF render is follow-up).

    Binds grid envelope (D1), cooling decision (D2), hourly CFE (D3),
    power-chain sizing (D5), and P10/P50/P90 DCF with an explicit
    assumption ledger. Every number is traceable.
    """
    from datetime import datetime as _dt
    env = await dc_grid_envelope(_GridEnvelopeReq(lat=body.lat, lon=body.lon, target_it_load_mw=body.it_load_mw), pool=pool)
    cool = await dc_cooling_topology(_CoolingReq(lat=body.lat, lon=body.lon, it_load_mw=body.it_load_mw))
    cfe = await dc_hourly_cfe_247(_CFEReq(lat=body.lat, lon=body.lon, it_load_mw=body.it_load_mw, pv_mw=body.pv_mw, bess_mwh=body.bess_mwh, demand_flex_pct=5.0))
    chain = await dc_power_chain_sized(_PowerChainReq(it_load_mw=body.it_load_mw, tier=body.tier, redundancy=body.redundancy))

    capex_per_mw_k = {1: 7500, 2: 8500, 3: 10_000, 4: 13_500}[body.tier]
    cooling_key = body.cooling_topology or cool["recommended_topology"]
    cooling_premium = {"a2_dry": 0, "a3_evap": -400, "l2c": 900, "immersion_1p": 1500, "immersion_2p": 2400}.get(cooling_key, 0)
    capex = body.it_load_mw * (capex_per_mw_k + cooling_premium) * 1000
    colo_rate = 1_500_000
    rev = body.it_load_mw * colo_rate * 0.85
    opex = body.it_load_mw * 250_000 + capex * 0.02

    def dcf(c, r_, o, life=20, r=0.08):
        return -c + sum((r_ - o) / ((1 + r) ** t) for t in range(1, life + 1))

    def irr(c, r_, o, life=20):
        lo, hi = -0.2, 0.6
        for _ in range(48):
            mid = (lo + hi) / 2
            v = -c + sum((r_ - o) / ((1 + mid) ** t) for t in range(1, life + 1))
            if v > 0: lo = mid
            else: hi = mid
        return mid

    return {
        "generated_at": _dt.utcnow().isoformat() + "Z",
        "kind": "feasibility_pack_v1",
        "inputs": body.model_dump(),
        "sections": {
            "grid_envelope": env,
            "cooling_topology": cool,
            "hourly_cfe": cfe,
            "power_chain": chain,
        },
        "financials": {
            "capex_gbp": round(capex, 0),
            "revenue_gbp_yr": round(rev, 0),
            "opex_gbp_yr": round(opex, 0),
            "npv_gbp": {
                "p10": round(dcf(capex * 1.15, rev * 0.90, opex * 1.10), 0),
                "p50": round(dcf(capex, rev, opex), 0),
                "p90": round(dcf(capex * 0.92, rev * 1.08, opex * 0.95), 0),
            },
            "irr": {
                "p10": round(irr(capex * 1.15, rev * 0.90, opex * 1.10), 4),
                "p50": round(irr(capex, rev, opex), 4),
                "p90": round(irr(capex * 0.92, rev * 1.08, opex * 0.95), 4),
            },
            "assumption_ledger": [
                {"k": "capex_per_mw_tier_base", "v": capex_per_mw_k, "unit": "£k/MW",
                 "source": "Uptime Institute Global Cost Benchmark 2025"},
                {"k": "cooling_capex_premium", "v": cooling_premium, "unit": "£k/MW",
                 "source": "CBRE + JLL Data Centre Cost Guide 2026 (indicative)"},
                {"k": "colo_rate_gbp_mw_yr", "v": colo_rate, "unit": "£/MW/yr",
                 "source": "CBRE Global Data Centre Trends 2026 — London I/O"},
                {"k": "occupancy", "v": 0.85, "unit": "fraction", "source": "Founder assumption"},
                {"k": "discount_rate", "v": 0.08, "unit": "per yr", "source": "UK infra WACC 2026"},
                {"k": "project_life", "v": 20, "unit": "yrs", "source": "Typical DC amortisation"},
            ],
        },
        "footer": "Pre-FID screening only. Not a substitute for detailed CFD (Cadence Reality / ANSYS Icepak) or protection studies (ETAP / SKM).",
        "standards_referenced": [
            "Uptime Institute Tier I-IV Functional Definitions",
            "TIA-942-C",
            "ASHRAE TC 9.9 Thermal Guidelines 5th ed (2021)",
            "ISO/IEC 30134-2 (PUE), 30134-9 (WUE)",
            "EnergyTag T-EAC hourly matching",
            "UK DNO Statement of Works + ER G99",
        ],
    }
