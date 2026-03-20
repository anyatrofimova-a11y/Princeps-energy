"""Scoring, BESS Optimiser, and Land Classification router."""

from __future__ import annotations

import json

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.deps import get_pool
from utils.site_prospector import score_candidate_site
from utils.bess_optimiser import (
    score_bess_site,
    calculate_optimal_sizing,
    model_revenue_stacking,
    bess_financial_model,
    assess_colocation_value,
    bess_regional_scan,
    BESS_CAPEX_GBP_PER_MWH,
    UK_REVENUE_STREAMS,
)
from utils.land_classifier import (
    classify_grid,
    assess_retrofitting,
    forecast_land_use,
    classification_to_map_geojson,
    ENRICHED_TAXONOMY,
)

router = APIRouter(tags=["scoring"])


# ---------------------------------------------------------------------------
# Embedding Similarity Search (pgvector)
# ---------------------------------------------------------------------------

@router.get("/sites/similar")
async def api_sites_similar(
    lat: float = Query(...),
    lon: float = Query(...),
    k: int = Query(5, ge=1, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find similar sites using pgvector KNN on foundation embeddings."""
    # Check if pgvector is available
    async with pool.acquire() as conn:
        has_vector = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')"
        )
        if not has_vector:
            return {
                "error": "pgvector extension not installed. Install with: brew install pgvector && psql -d feasibly -c 'CREATE EXTENSION vector;'",
                "fallback": f"/prospector/similar?lat={lat}&lon={lon}&radius_km=50&technology=solar",
            }
        # First get or generate reference embedding
        ref = await conn.fetchrow(
            """
            SELECT embedding FROM geeflow_extractions
            WHERE embedding IS NOT NULL
              AND abs(lat - $1) < 0.02 AND abs(lon - $2) < 0.02
            ORDER BY created_at DESC LIMIT 1
            """,
            lat, lon,
        )
        if not ref or ref["embedding"] is None:
            return {
                "error": "No embedding found for reference location. Run foundation_embeddings GeoAI mode first.",
                "hint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=foundation_embeddings",
            }

        # KNN search using cosine distance
        rows = await conn.fetch(
            """
            SELECT lat, lon, radius_km, mode, result_data, created_at,
                   embedding <=> $1::vector AS distance
            FROM geeflow_extractions
            WHERE embedding IS NOT NULL
              AND NOT (abs(lat - $2) < 0.02 AND abs(lon - $3) < 0.02)
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            str(ref["embedding"]), lat, lon, k,
        )
        results = []
        for r in rows:
            rd = r["result_data"]
            if isinstance(rd, str):
                rd = json.loads(rd)
            results.append({
                "lat": r["lat"],
                "lon": r["lon"],
                "cosine_distance": round(float(r["distance"]), 4),
                "similarity": round(1 - float(r["distance"]), 4),
                "mode": r["mode"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
        return {
            "reference": {"lat": lat, "lon": lon},
            "k": k,
            "matches": results,
            "method": "pgvector cosine KNN on Prithvi-768 embeddings",
        }


# ---------------------------------------------------------------------------
# Learned Scoring
# ---------------------------------------------------------------------------

@router.get("/scoring/learned")
async def api_learned_scoring(
    lat: float = Query(...),
    lon: float = Query(...),
):
    """Get both rule-based and learned site scores."""
    from utils.learned_scorer import learned_score, extract_features

    # Rule-based score from site_prospector
    rule_based = score_candidate_site(lat, lon, "solar")

    # Learned score (XGBoost + SHAP)
    learned = learned_score(lat, lon)

    return {
        "lat": lat,
        "lon": lon,
        "rule_based": rule_based,
        "learned": learned,
    }


# ---------------------------------------------------------------------------
# BESS Optimiser
# ---------------------------------------------------------------------------

@router.get("/bess/score")
async def api_bess_score(
    lat: float = Query(...),
    lon: float = Query(...),
    land_area_m2: float = Query(None),
    grid_distance_km: float = Query(None),
    grid_headroom_mw: float = Query(None),
    grid_voltage_kv: float = Query(None),
):
    """Score a site for BESS deployment suitability."""
    grid_data = {}
    if grid_distance_km is not None:
        grid_data["distance_km"] = grid_distance_km
    if grid_headroom_mw is not None:
        grid_data["headroom_mw"] = grid_headroom_mw
    if grid_voltage_kv is not None:
        grid_data["voltage_kv"] = grid_voltage_kv
    return score_bess_site(lat, lon, grid_data or None, land_area_m2)


class BESSSizingRequest(BaseModel):
    capacity_mw: float
    revenue_strategy: str = "hybrid"
    grid_constraint_mw: float | None = None
    duration_options: list[int] | None = None


@router.post("/bess/sizing")
async def api_bess_sizing(req: BESSSizingRequest):
    """Calculate optimal BESS sizing across duration options."""
    return calculate_optimal_sizing(
        req.capacity_mw, req.duration_options, req.revenue_strategy, req.grid_constraint_mw,
    )


class BESSRevenueRequest(BaseModel):
    power_mw: float
    energy_mwh: float
    strategy: str = "hybrid"


@router.post("/bess/revenue")
async def api_bess_revenue(req: BESSRevenueRequest):
    """Model revenue stacking for a BESS configuration."""
    return model_revenue_stacking(req.power_mw, req.energy_mwh, req.strategy)


class BESSFinancialRequest(BaseModel):
    capex_gbp: float
    annual_revenue_gbp: float
    opex_pct: float | None = None
    years: int = 20
    discount_rate: float = 0.08


@router.post("/bess/financial")
async def api_bess_financial(req: BESSFinancialRequest):
    """Run BESS financial model (NPV, IRR, payback, LCOES)."""
    kwargs = {"capex_gbp": req.capex_gbp, "annual_revenue_gbp": req.annual_revenue_gbp,
              "years": req.years, "discount_rate": req.discount_rate}
    if req.opex_pct is not None:
        kwargs["opex_pct"] = req.opex_pct
    return bess_financial_model(**kwargs)


@router.get("/bess/colocation")
async def api_bess_colocation(
    solar_kw: float = Query(...),
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
):
    """Assess value-add from co-locating BESS with solar PV."""
    return assess_colocation_value(solar_kw, location_data={"lat": lat, "lon": lon})


@router.get("/bess/scan")
async def api_bess_scan(
    region: str = Query("south_west"),
    min_mw: float = Query(10, ge=1),
    max_mw: float = Query(100, le=500),
):
    """Scan a UK region for BESS deployment opportunities."""
    return bess_regional_scan(region, min_mw, max_mw)


@router.get("/bess/benchmarks")
async def api_bess_benchmarks():
    """Return UK BESS market benchmarks."""
    return {
        "capex_gbp_per_mwh": BESS_CAPEX_GBP_PER_MWH,
        "revenue_streams": UK_REVENUE_STREAMS,
    }


# ---------------------------------------------------------------------------
# BESS Bidder — multi-market battery bidding (BessBidder integration)
# ---------------------------------------------------------------------------

from utils.bess_bidder import (
    run_bidding_simulation,
    optimize_day_ahead,
    rolling_intrinsic,
    coordinated_dispatch,
    simulate_uk_prices,
    BatterySpec,
)


@router.get("/bess/bidder/simulate")
async def api_bess_bidder_simulate(
    power_mw: float = Query(50.0, ge=1, le=500),
    energy_mwh: float = Query(100.0, ge=1, le=2000),
    strategy: str = Query("coordinated"),
    hours: int = Query(24, ge=1, le=168),
    efficiency: float = Query(0.86, ge=0.5, le=1.0),
):
    """Run a complete BESS bidding simulation with simulated UK prices.

    Strategies: day_ahead, rolling_intrinsic, coordinated
    """
    return run_bidding_simulation(power_mw, energy_mwh, strategy, hours, efficiency)


class BidderOptimizeRequest(BaseModel):
    prices_forecast: list[float]
    prices_realised: list[float] | None = None
    power_mw: float = 50.0
    energy_mwh: float = 100.0
    efficiency: float = 0.86
    max_cycles_per_day: float = 1.5


@router.post("/bess/bidder/day-ahead")
async def api_bess_bidder_da(req: BidderOptimizeRequest):
    """Optimise day-ahead arbitrage schedule using MILP.

    Provide hourly price forecasts (£/MWh) and optionally realised prices.
    """
    battery = BatterySpec(
        power_mw=req.power_mw,
        energy_mwh=req.energy_mwh,
        round_trip_efficiency=req.efficiency,
        max_cycles_per_day=req.max_cycles_per_day,
    )
    return optimize_day_ahead(req.prices_forecast, battery, req.prices_realised)


class BidderIntradayRequest(BaseModel):
    prices: list[float]
    power_mw: float = 50.0
    energy_mwh: float = 100.0
    efficiency: float = 0.86
    bucket_size_hours: float = 0.25
    discount_rate: float = 0.02
    existing_positions: list[float] | None = None


@router.post("/bess/bidder/intraday")
async def api_bess_bidder_intraday(req: BidderIntradayRequest):
    """Run rolling intrinsic intraday strategy.

    Provide quarter-hourly prices and optionally existing DA positions.
    """
    battery = BatterySpec(
        power_mw=req.power_mw,
        energy_mwh=req.energy_mwh,
        round_trip_efficiency=req.efficiency,
    )
    return rolling_intrinsic(
        req.prices, battery, req.bucket_size_hours,
        req.discount_rate, req.existing_positions,
    )


class BidderCoordinatedRequest(BaseModel):
    da_prices: list[float]
    id_prices: list[float] | None = None
    power_mw: float = 50.0
    energy_mwh: float = 100.0
    efficiency: float = 0.86
    lambda_da: float = 0.5


@router.post("/bess/bidder/coordinated")
async def api_bess_bidder_coordinated(req: BidderCoordinatedRequest):
    """Coordinated multi-market dispatch (DA MILP + intraday rolling intrinsic).

    Based on BessBidder framework (Miskiw et al., ACM e-Energy 2025).
    """
    battery = BatterySpec(
        power_mw=req.power_mw,
        energy_mwh=req.energy_mwh,
        round_trip_efficiency=req.efficiency,
    )
    return coordinated_dispatch(
        req.da_prices, req.id_prices, battery, req.lambda_da,
    )


@router.get("/bess/bidder/prices")
async def api_bess_bidder_prices(
    hours: int = Query(24, ge=1, le=168),
):
    """Generate simulated UK wholesale electricity prices."""
    return simulate_uk_prices(hours)


# ---------------------------------------------------------------------------
# Land Classification
# ---------------------------------------------------------------------------

@router.get("/classify/land-use")
async def api_classify_land_use(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(2.0, ge=0.5, le=20),
    grid_size: int = Query(10, ge=3, le=30),
):
    """Run enriched 21-class land use classification over a grid."""
    result = classify_grid(lat, lon, radius_km, grid_size)
    return result


@router.get("/classify/map-overlay")
async def api_classify_map_overlay(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(2.0, ge=0.5, le=20),
):
    """Get Mapbox-ready GeoJSON with labels and energy badges."""
    classification = classify_grid(lat, lon, radius_km)
    return classification_to_map_geojson(classification, include_labels=True)


@router.get("/classify/retrofitting")
async def api_classify_retrofitting(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(2.0, ge=0.5, le=20),
):
    """Assess retrofitting potential for solar/BESS/EV."""
    classification = classify_grid(lat, lon, radius_km)
    return assess_retrofitting(classification)


@router.get("/classify/forecast")
async def api_classify_forecast(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(2.0, ge=0.5, le=20),
    forecast_years: int = Query(5, ge=1, le=15),
):
    """Forecast land use change trends."""
    return forecast_land_use(lat, lon, radius_km, forecast_years=forecast_years)


@router.get("/classify/taxonomy")
async def api_classify_taxonomy():
    """Return the enriched 21-class taxonomy with energy tags."""
    return ENRICHED_TAXONOMY
