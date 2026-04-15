"""Gu-inspired capability router — 10 endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
import asyncpg

from app.deps import get_pool
from utils.gu_capabilities import (
    probabilistic_lric,
    reliability_weighted_hosting,
    carbon_adjusted_lcoe,
    tcl_frequency_response_revenue,
    drl_bess_dispatch_preview,
    tso_dso_prosumer_simulation,
    dro_climate_resilience,
    water_vector_dc_scoring,
    hydrogen_curtailment_opportunity,
    seed_regulation_corpus,
    regulatory_retrieve,
    regulatory_answer,
    ingest_regulation_pdf,
    bulk_ingest_accessible_pdfs,
)
from utils.dno_opendata_ingester import (
    ingest_dno,
    ingest_all_dnos,
    get_ingest_status,
    get_large_demand_geojson,
    DNO_ADAPTERS,
)

router = APIRouter(tags=["gu-capabilities"], prefix="/api/gu")


# ────────────────────────── R3 Probabilistic LRIC ──────────────────────────

@router.post("/lric")
async def lric(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R3 — Probabilistic LRIC grid connection cost (GBM + LRIC + reliability)."""
    return await probabilistic_lric(
        pool,
        capacity_mw=float(body["capacity_mw"]),
        base_reinforcement_cost_gbp=float(body.get("base_reinforcement_cost_gbp", 25_000_000)),
        existing_headroom_mw=float(body.get("existing_headroom_mw", 50)),
        asset_utilisation_pct=float(body.get("asset_utilisation_pct", 65)),
        horizon_years=int(body.get("horizon_years", 20)),
        load_growth_mu=float(body.get("load_growth_mu", 0.035)),
        load_growth_sigma=float(body.get("load_growth_sigma", 0.055)),
        discount_rate=float(body.get("discount_rate", 0.065)),
        reliability_uplift_pct=float(body.get("reliability_uplift_pct", 8.0)),
        n_paths=int(body.get("n_paths", 500)),
        site_id=body.get("site_id"),
        lat=body.get("lat"),
        lon=body.get("lon"),
    )


# ────────────────────────── R4 Reliability-weighted hosting ──────────────────

@router.post("/hosting-capacity")
async def hosting(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R4 — Reliability-weighted PV/BESS hosting capacity score."""
    return await reliability_weighted_hosting(
        pool,
        substation_mrid=body.get("substation_mrid"),
        voltage_kv=float(body.get("voltage_kv", 33)),
        baseline_headroom_mw=float(body.get("baseline_headroom_mw", 0)),
        ci_per_100=float(body.get("ci_per_100", 18)),
        cml_minutes=float(body.get("cml_minutes", 36)),
        sensitivity_index=float(body.get("sensitivity_index", 0.5)),
    )


# ────────────────────────── R8 Carbon-adjusted LCOE ──────────────────────────

@router.post("/carbon-lcoe")
async def lcoe(body: dict = Body(...)):
    """R8 — Carbon-responsibility LCOE per Li/Gu 2024."""
    return carbon_adjusted_lcoe(
        base_lcoe_gbp_per_mwh=float(body["base_lcoe_gbp_per_mwh"]),
        annual_generation_mwh=float(body.get("annual_generation_mwh", 0)),
        annual_import_mwh=float(body.get("annual_import_mwh", 0)),
        grid_carbon_g_per_kwh=float(body.get("grid_carbon_g_per_kwh", 140)),
        carbon_price_gbp_per_tco2=float(body.get("carbon_price_gbp_per_tco2", 85)),
        onsite_emissions_t_per_mwh=float(body.get("onsite_emissions_t_per_mwh", 0)),
        allocation_method=body.get("allocation_method", "pro_rata"),
    )


# ────────────────────────── R9 Thermostatic FR revenue ──────────────────────

@router.post("/tcl-revenue")
async def tcl(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R9 — Thermostatic-load frequency response revenue stack."""
    return await tcl_frequency_response_revenue(
        pool,
        site_id=body.get("site_id", "adhoc"),
        flex_mw=float(body["flex_mw"]),
        availability_hours_per_day=float(body.get("availability_hours_per_day", 16)),
        dfs_price_gbp_per_mwh=float(body.get("dfs_price_gbp_per_mwh", 2500)),
        dc_low_price_gbp_per_mw_year=float(body.get("dc_low_price_gbp_per_mw_year", 65_000)),
        firm_freq_price_gbp_per_mw_year=float(body.get("firm_freq_price_gbp_per_mw_year", 45_000)),
        participation_factor=float(body.get("participation_factor", 0.6)),
        cluster_count=int(body.get("cluster_count", 20)),
    )


# ────────────────────────── R1 DRL BESS dispatch preview ─────────────────────

@router.post("/drl-bess")
async def drl_bess(body: dict = Body(...)):
    """R1 — Degradation-aware DRL BESS dispatch (analytical preview)."""
    return await drl_bess_dispatch_preview(
        power_mw=float(body["power_mw"]),
        capacity_mwh=float(body["capacity_mwh"]),
        price_series_gbp_per_mwh=body["price_series_gbp_per_mwh"],
        rte_pct=float(body.get("rte_pct", 88)),
        chemistry=body.get("chemistry", "LFP"),
        temperature_c=float(body.get("temperature_c", 25)),
    )


# ────────────────────────── R2 TSO-DSO-prosumer market sim ───────────────────

@router.post("/market-sim")
async def market_sim(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R2 — TSO-DSO-prosumer carbon-aware market simulation."""
    return await tso_dso_prosumer_simulation(
        pool,
        site_id=body.get("site_id", "adhoc"),
        site_generation_mw=float(body["site_generation_mw"]),
        site_demand_mw=float(body["site_demand_mw"]),
        neighbour_count=int(body.get("neighbour_count", 5)),
        carbon_price_gbp_per_tco2=float(body.get("carbon_price_gbp_per_tco2", 85)),
        base_lmp_gbp_per_mwh=float(body.get("base_lmp_gbp_per_mwh", 75)),
        scenario=body.get("scenario", "base"),
    )


# ────────────────────────── R5 DRO climate resilience ────────────────────────

@router.post("/climate-resilience")
async def climate(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R5 — Two-stage DRO climate-resilience scoring."""
    return await dro_climate_resilience(
        pool,
        site_id=body.get("site_id", "adhoc"),
        lat=float(body["lat"]),
        lon=float(body["lon"]),
        wind_return_period_mph=float(body.get("wind_return_period_mph", 90)),
        flood_zone=int(body.get("flood_zone", 1)),
        heat_return_period_c=float(body.get("heat_return_period_c", 38)),
        asset_fragility=float(body.get("asset_fragility", 0.35)),
    )


# ────────────────────────── R6 Water-vector DC siting ────────────────────────

@router.post("/water-nexus")
async def water(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R6 — Water-vector DC siting (DQN+MOEA/D analytical preview)."""
    return await water_vector_dc_scoring(
        pool,
        site_id=body.get("site_id", "adhoc"),
        lat=float(body["lat"]),
        lon=float(body["lon"]),
        capacity_mva=float(body["capacity_mva"]),
        cooling_strategy=body.get("cooling_strategy", "air"),
        grid_headroom_mw=float(body.get("grid_headroom_mw", 0)),
    )


# ────────────────────────── R7 Hydrogen monetisation ─────────────────────────

@router.post("/hydrogen")
async def hydrogen(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R7 — Hydrogen curtailment monetisation (robust P2G)."""
    return await hydrogen_curtailment_opportunity(
        pool,
        project_id=body.get("project_id", "adhoc"),
        lat=float(body["lat"]),
        lon=float(body["lon"]),
        curtailed_mwh_per_year=float(body["curtailed_mwh_per_year"]),
        gas_grid_distance_km=float(body.get("gas_grid_distance_km", 5)),
        electrolyser_cost_per_mw_gbp=float(body.get("electrolyser_cost_per_mw_gbp", 1_200_000)),
        h2_price_gbp_per_kg=float(body.get("h2_price_gbp_per_kg", 4.50)),
    )


# ────────────────────────── R10 LLM regulatory copilot ───────────────────────

@router.post("/regulatory/seed")
async def reg_seed(pool: asyncpg.Pool = Depends(get_pool)):
    """R10 — Seed the UK regulatory corpus with known ENA / Ofgem / NESO docs."""
    return await seed_regulation_corpus(pool)


@router.get("/regulatory/search")
async def reg_search(
    q: str = Query(...),
    k: int = Query(5, ge=1, le=20),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """R10 — Keyword retrieval against the regulatory corpus."""
    return await regulatory_retrieve(pool, q, k=k)


@router.post("/regulatory/answer")
async def reg_answer(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R10 — Structured regulatory compliance answer with citations."""
    return await regulatory_answer(pool, question=body["question"], context=body.get("context"))


@router.post("/regulatory/ingest-pdf")
async def reg_ingest_pdf(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """R10 — Download + extract + chunk + index a single regulatory PDF."""
    return await ingest_regulation_pdf(
        pool,
        doc_id=body["doc_id"],
        url=body["url"],
        source=body["source"],
        doc_type=body["doc_type"],
        title=body["title"],
        version=body.get("version"),
        publication_date=body.get("publication_date"),
    )


@router.post("/regulatory/bulk-ingest")
async def reg_bulk_ingest(pool: asyncpg.Pool = Depends(get_pool)):
    """R10 — Ingest the curated list of publicly-accessible NESO regulatory PDFs."""
    return await bulk_ingest_accessible_pdfs(pool)


# ────────────────────────── Multi-DNO OpenDataSoft (support) ─────────────────

@router.post("/dno/ingest")
async def dno_ingest(
    dno: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ingest all datasets for one DNO (or all) using OpenDataSoft API keys from env."""
    if dno:
        return await ingest_dno(pool, dno.upper())
    return await ingest_all_dnos(pool)


@router.get("/dno/status")
async def dno_status(pool: asyncpg.Pool = Depends(get_pool)):
    """Per-DNO ingest status — last run, row counts, auth failures."""
    return await get_ingest_status(pool)


@router.get("/dno/adapters")
async def dno_adapters():
    """List the configured DNO adapters and their dataset counts."""
    return {
        dno: {
            "name": a["name"],
            "base_url": a["base_url"],
            "api": a["api"],
            "datasets": list(a["datasets"].keys()),
            "dataset_count": len(a["datasets"]),
        }
        for dno, a in DNO_ADAPTERS.items()
    }


@router.get("/dno/large-demand.geojson")
async def large_demand_geojson(
    dno: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """UKPN / other DNO Large Demand List projects as GeoJSON."""
    return await get_large_demand_geojson(pool, dno=dno)
