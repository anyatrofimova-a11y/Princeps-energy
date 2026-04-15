"""NESO098 DC Optimiser router — 9-criteria scorecard + demand forecast + queue dedup + consolidated estate."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, Query
import asyncpg

from app.deps import get_pool
from utils.neso098_dc_optimiser import (
    score_site,
    it_to_total_power,
    LATENCY_CLASSES,
    DC_TYPES,
    CRITERIA_WEIGHTS,
    build_forecast_matrix,
    attrition_analysis,
    dedupe_queue,
    upsert_dc_record,
    estate_summary,
    estate_geojson,
    populate_estate_from_ukpn,
    enrich_estate_coordinates,
)

router = APIRouter(tags=["neso098"], prefix="/api/neso098")


# ─────────────────── 9-criteria site scoring ───────────────────

@router.post("/score-site")
async def site_score(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Compute the NESO 9-criteria location score for a candidate DC site."""
    return await score_site(
        pool,
        site_id=body.get("site_id", "ad-hoc"),
        lat=float(body["lat"]),
        lon=float(body["lon"]),
        capacity_mva=float(body.get("capacity_mw", body.get("capacity_mva", 100))),
        dc_type=body.get("dc_type", "hyperscaler"),
        latency_class=body.get("latency_class", "regionally_constrained"),
        power_cost_gbp_per_mwh=body.get("power_cost_gbp_per_mwh"),
        months_to_power=body.get("months_to_power"),
        fibre_pops_within_10km=body.get("fibre_pops_within_10km"),
        population_within_50km=body.get("population_within_50km"),
        avg_construction_wage_gbp=body.get("avg_construction_wage_gbp"),
        land_cost_gbp_per_ha=body.get("land_cost_gbp_per_ha"),
        lpa_policy_stance=body.get("lpa_policy_stance"),
        water_stress_index=body.get("water_stress_index"),
        carbon_intensity_g_per_kwh=body.get("carbon_intensity_g_per_kwh"),
        summer_design_temp_c=body.get("summer_design_temp_c"),
    )


@router.get("/criteria")
async def criteria():
    """Return the 9 criteria + default weights + latency classes + DC types."""
    return {
        "criteria": CRITERIA_WEIGHTS,
        "latency_classes": LATENCY_CLASSES,
        "dc_types": DC_TYPES,
        "source": "NIA2_NESO098 NESO × McKinsey (Dec 2024 – Feb 2025)",
    }


# ─────────────────── IT vs total power disambiguation ───────────────────

@router.get("/power")
async def power_disambig(
    it_power_mw: float = Query(...),
    dc_type: str = Query("hyperscaler"),
    pue_override: float | None = Query(None),
):
    """Convert IT-only power to total facility power (PUE × IT)."""
    return it_to_total_power(it_power_mw, dc_type=dc_type, pue_override=pue_override)


# ─────────────────── Demand forecast matrix ───────────────────

@router.post("/forecast/build")
async def forecast_build(
    scenario: str = Query("moderate"),
    start_year: int = Query(2024),
    end_year: int = Query(2040),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Build the top-down 2024-2040 DC demand forecast matrix."""
    rows = await build_forecast_matrix(pool, scenario=scenario, start_year=start_year, end_year=end_year)
    return {"scenario": scenario, "rows": len(rows), "sample": rows[:10]}


@router.get("/forecast")
async def forecast_read(
    scenario: str = Query("moderate"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Read an already-built forecast matrix."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT year, dc_type, latency_class, mw_demand, mw_supply, gap_mw
            FROM neso098_demand_forecast
            WHERE scenario = $1
            ORDER BY year, dc_type, latency_class
            """,
            scenario,
        )
    return {"scenario": scenario, "rows": [dict(r) for r in rows]}


# ─────────────────── Queue dedup + attrition ───────────────────

@router.post("/queue/dedupe")
async def queue_dedupe(body: dict = Body(...)):
    """Deduplicate a list of DC connection applications."""
    return dedupe_queue(body.get("applications", []))


@router.post("/queue/attrition")
async def queue_attrition(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Run dedup + stage attrition on a batch of DC applications."""
    return await attrition_analysis(pool, body.get("applications", []))


# ─────────────────── Consolidated DC estate ───────────────────

@router.post("/estate/upsert")
async def estate_upsert(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Insert / update a DC record in the consolidated estate."""
    target_e = body.get("target_energisation")
    if target_e and isinstance(target_e, str):
        try:
            target_e = date.fromisoformat(target_e)
        except Exception:
            target_e = None
    return await upsert_dc_record(
        pool,
        dc_id=body["dc_id"],
        name=body.get("name"),
        operator=body.get("operator"),
        dc_type=body.get("dc_type", "colocation"),
        latency_class=body.get("latency_class", "regionally_constrained"),
        status=body.get("status", "applied"),
        it_power_mw=body.get("it_power_mw"),
        lat=body.get("lat"),
        lon=body.get("lon"),
        local_authority=body.get("local_authority"),
        licence_area=body.get("licence_area"),
        grid_supply_point=body.get("grid_supply_point"),
        connection_voltage_kv=body.get("connection_voltage_kv"),
        target_energisation=target_e,
        data_source=body.get("data_source", "manual"),
        raw=body.get("raw"),
    )


@router.get("/estate/summary")
async def estate_summary_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """Aggregate summary of the consolidated DC estate."""
    return await estate_summary(pool)


@router.get("/estate.geojson")
async def estate_geojson_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """Consolidated DC estate as GeoJSON for the map."""
    return await estate_geojson(pool)


@router.post("/estate/populate-from-ukpn")
async def estate_populate_from_ukpn(pool: asyncpg.Pool = Depends(get_pool)):
    """Populate the consolidated estate from UKPN ingested datasets
    (data_centres_by_la + large_demand_list).
    """
    return await populate_estate_from_ukpn(pool)


@router.post("/estate/enrich-coords")
async def estate_enrich_coords(pool: asyncpg.Pool = Depends(get_pool)):
    """Fuzzy-match estate records to grid primary sites + ONS LA centroids
    to fill in lat/lon for records that lack coordinates.
    """
    return await enrich_estate_coordinates(pool)
