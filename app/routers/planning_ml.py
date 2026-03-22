"""Planning Intelligence & Regulatory ML — prediction, compliance, constraints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import asyncpg

from app.deps import get_pool

router = APIRouter(tags=["planning-ml"])


class PlanningPredictRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    capacity_mw: float = Field(50, ge=0.1, le=5000)
    technology: str = Field("solar", pattern="^(solar|wind|bess|dc|hybrid)$")
    land_area_ha: float = Field(None, ge=0)
    is_greenfield: bool = True
    description: str = None


@router.post("/api/planning/predict")
async def predict_planning_outcome(req: PlanningPredictRequest):
    """Predict planning application outcome using XGBoost model trained on REPD data.

    Returns probability of approval/refusal, top risk factors (SHAP-based),
    comparable past decisions, and actionable recommendations.
    """
    from utils.planning_intelligence import predict_planning_outcome as _predict
    return await _predict({
        "lat": req.lat, "lon": req.lon,
        "capacity_mw": req.capacity_mw,
        "technology": req.technology,
        "land_area_ha": req.land_area_ha,
        "is_greenfield": req.is_greenfield,
        "description": req.description,
    })


@router.get("/api/planning/constraints")
async def get_planning_constraints(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(2000, ge=100, le=10000),
):
    """Fetch environmental and planning constraint layers around a point.

    Checks: SSSI, SAC, SPA, AONB, Ancient Woodland, Listed Buildings,
    Conservation Areas, Scheduled Monuments, Flood Zones, Green Belt, ALC.
    """
    from utils.planning_intelligence import fetch_planning_constraints
    return await fetch_planning_constraints(lat, lon, radius_m)


@router.get("/api/planning/compliance")
async def check_compliance(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    land_area_ha: float = Query(None),
):
    """Regulatory compliance check against NPPF, EN-1/EN-3, EIA, BNG, CDM."""
    from utils.planning_intelligence import (
        fetch_planning_constraints, check_regulatory_compliance,
    )
    constraints = await fetch_planning_constraints(lat, lon, 2000)
    project = {
        "lat": lat, "lon": lon, "capacity_mw": capacity_mw,
        "technology": technology, "land_area_ha": land_area_ha,
    }
    return check_regulatory_compliance(project, constraints)


@router.get("/api/planning/authority-profile")
async def authority_profile(
    name: str = Query(..., description="Local authority name"),
    technology: str = Query("solar"),
):
    """Intelligence profile for a local planning authority.

    Approval rate, average determination time, common refusal reasons,
    capacity approved/refused by year.
    """
    from utils.planning_intelligence import local_authority_profile
    return local_authority_profile(name, technology)


@router.get("/api/planning/comparable-decisions")
async def comparable_decisions(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    radius_km: float = Query(20),
    limit: int = Query(10),
):
    """Find similar past planning decisions near the site."""
    from utils.planning_intelligence import find_comparable_decisions
    return find_comparable_decisions(
        lat, lon, capacity_mw, technology, radius_km, limit,
    )


@router.post("/api/planning/train")
async def retrain_model():
    """Retrain the planning prediction model on latest REPD data."""
    from utils.planning_intelligence import get_predictor
    predictor = await get_predictor()
    predictor._trained = False
    predictor.model = None
    await get_predictor()  # Re-initialises and trains
    return {"status": "retrained", "features": len(predictor.feature_names)}


@router.get("/api/planning/model-status")
async def model_status():
    """Check model training status and accuracy metrics."""
    try:
        from utils.planning_intelligence import PlanningPredictor
        predictor = PlanningPredictor()
        return {
            "trained": predictor._trained,
            "feature_count": len(predictor.feature_names),
            "features": predictor.feature_names[:20],
            "modules": {
                "planning_intelligence": True,
                "planning_predictor": True,
            },
        }
    except Exception as e:
        return {"trained": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  REPD ML Predictor — GradientBoosting on 13,995 real projects
# ═══════════════════════════════════════════════════════════════

@router.get("/api/planning/predict-repd")
async def predict_approval_ml(
    lat: float = Query(..., ge=49, le=61, description="Latitude (WGS84)"),
    lon: float = Query(..., ge=-8, le=2, description="Longitude (WGS84)"),
    technology: str = Query("solar"),
    capacity_mw: float = Query(50, ge=0.1, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Predict planning approval probability using GradientBoosting trained on REPD.

    Returns approval_probability, predicted_months_to_decision, confidence,
    risk_factors, and top model features.
    """
    from utils.planning_predictor import get_predictor
    predictor = await get_predictor(pool)
    return await predictor.predict(pool, lat, lon, technology, capacity_mw)


@router.get("/api/planning/comparable-repd")
async def comparable_projects_ml(
    lat: float = Query(..., ge=49, le=61),
    lon: float = Query(..., ge=-8, le=2),
    technology: str = Query("solar"),
    capacity_mw: float = Query(50, ge=0.1, le=5000),
    radius_km: float = Query(20, ge=1, le=100),
    limit: int = Query(15, ge=1, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find comparable REPD projects nearby with their planning outcomes."""
    from utils.planning_predictor import get_predictor
    predictor = await get_predictor(pool)
    return await predictor.find_comparable(
        pool, lat, lon, technology, capacity_mw, radius_km, limit,
    )


@router.get("/api/planning/authority-stats")
async def authority_stats_ml(
    planning_authority: str = Query(..., description="Local planning authority name"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Detailed approval stats for a planning authority — rates, timelines, tech breakdown, yearly trend."""
    from utils.planning_predictor import get_predictor
    predictor = await get_predictor(pool)
    return await predictor.authority_stats(pool, planning_authority)


@router.post("/api/planning/retrain")
async def retrain_repd_model(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Force retrain the REPD GradientBoosting model on latest data."""
    from utils.planning_predictor import retrain
    result = await retrain(pool)
    return {"status": "retrained", **result}


# ═══════════════════════════════════════════════════════════════
#  REPD ML v2 — GradientBoosting on 13,995 real repd_project rows
#  Uses utils/repd_ml_model.py with real PostGIS spatial features
# ═══════════════════════════════════════════════════════════════

class PredictApprovalRequest(BaseModel):
    lat: float = Field(..., ge=49, le=61, description="Latitude (WGS84)")
    lon: float = Field(..., ge=-8, le=2, description="Longitude (WGS84)")
    capacity_mw: float = Field(50, ge=0.1, le=5000, description="Proposed capacity in MW")
    technology: str = Field("solar", description="Technology: solar, wind, bess, battery, biomass, hydrogen")


@router.post("/api/planning/predict-approval")
async def predict_approval_v2(
    req: PredictApprovalRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """ML-predicted planning approval probability based on 14K real REPD outcomes.

    Trains a GradientBoostingClassifier on first call (~30s), then cached.
    Features include nearby project density, local authority approval rate,
    technology, capacity, region — all from real PostGIS spatial queries.

    Returns approval_probability (0-1), verdict, confidence, risk_factors,
    feature_contributions, comparable_projects, and model_stats.
    """
    from utils.repd_ml_model import predict_approval
    return await predict_approval(pool, req.lat, req.lon, req.capacity_mw, req.technology)


@router.get("/api/planning/model-stats")
async def model_stats_v2(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Model accuracy, feature importances, confusion matrix, training info.

    Returns the performance metrics of the REPD GradientBoosting model
    trained on 13,995 real UK planning outcomes.
    """
    from utils.repd_ml_model import get_model_stats
    return await get_model_stats(pool)


@router.post("/api/planning/retrain-v2")
async def retrain_model_v2(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Force retrain the REPD ML model on latest data."""
    from utils.repd_ml_model import train_model
    # Clear the cached model
    import utils.repd_ml_model as _mod
    _mod._model_data = None
    result = await train_model(pool)
    return {"status": "retrained", **result}


@router.get("/api/planning/comparable-projects")
async def comparable_projects_v2(
    lat: float = Query(..., ge=49, le=61),
    lon: float = Query(..., ge=-8, le=2),
    capacity_mw: float = Query(50, ge=0.1, le=5000),
    technology: str = Query("solar"),
    limit: int = Query(10, ge=1, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find most similar REPD projects by technology, capacity, and location."""
    from utils.repd_ml_model import get_comparable_projects
    return await get_comparable_projects(pool, lat, lon, capacity_mw, technology, limit)


# ═══════════════════════════════════════════════════════════════
#  Site Benchmarking — compare against 14K real REPD projects
# ═══════════════════════════════════════════════════════════════

class BenchmarkSiteRequest(BaseModel):
    lat: float = Field(..., ge=49, le=61, description="Latitude (WGS84)")
    lon: float = Field(..., ge=-8, le=2, description="Longitude (WGS84)")
    capacity_mw: float = Field(50, ge=0.1, le=5000, description="Proposed capacity in MW")
    technology: str = Field("solar", description="Technology: solar, wind, bess, battery")


@router.post("/api/planning/benchmark-site")
async def benchmark_site_endpoint(
    req: BenchmarkSiteRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Benchmark a proposed site against 13,995 real REPD projects.

    For each metric (grid headroom, grid distance, local density,
    approval rate, capacity), shows the site's percentile rank
    among all operational UK projects of the same technology.

    Returns overall percentile, verdict (EXCELLENT / ABOVE AVERAGE /
    AVERAGE / BELOW AVERAGE / POOR), metric breakdowns, comparable
    approved and refused projects, and summary narrative.
    """
    from utils.site_benchmarker import benchmark_site
    return await benchmark_site(
        pool, req.lat, req.lon, req.capacity_mw, req.technology,
    )


# ═══════════════════════════════════════════════════════════════
#  BMRS Datasets — live grid intelligence
# ═══════════════════════════════════════════════════════════════

@router.get("/api/bmrs/wind-solar")
async def bmrs_wind_solar():
    """Actual wind and solar generation from BMRS AGWS dataset."""
    from utils.bmrs_datasets import wind_solar_summary
    return await wind_solar_summary()


@router.get("/api/bmrs/wind-forecast")
async def bmrs_wind_forecast():
    """24-hour wind generation forecast from BMRS WINDFOR."""
    from utils.bmrs_datasets import wind_forecast_24h
    return await wind_forecast_24h()


@router.get("/api/bmrs/warnings")
async def bmrs_warnings():
    """Active system warnings from BMRS SYSWARN."""
    from utils.bmrs_datasets import fetch_system_warnings
    return await fetch_system_warnings() or []


@router.get("/api/bmrs/temperature")
async def bmrs_temperature():
    """Temperature data from BMRS TEMP dataset."""
    from utils.bmrs_datasets import fetch_temperature
    return await fetch_temperature() or []


@router.get("/api/bmrs/frequency")
async def bmrs_frequency():
    """Current system frequency from BMRS FREQ."""
    from utils.bmrs_datasets import fetch_frequency
    return await fetch_frequency() or {"frequency_hz": 50.0}


@router.get("/api/bmrs/generation")
async def bmrs_generation():
    """Current generation by fuel type from BMRS FUELINST."""
    from utils.bmrs_datasets import fetch_generation_current
    return await fetch_generation_current() or {}


@router.get("/api/bmrs/snapshot")
async def bmrs_full_snapshot():
    """Full grid intelligence snapshot — all BMRS feeds combined."""
    from utils.bmrs_datasets import full_grid_snapshot
    return await full_grid_snapshot()


# ═══════════════════════════════════════════════════════════════
#  Tender Intelligence — Find a Tender + Contracts Finder
# ═══════════════════════════════════════════════════════════════

@router.get("/api/tenders/energy")
async def energy_tenders(
    days_back: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    keywords: str = Query(None, description="Comma-separated keywords"),
):
    """Fetch energy infrastructure tenders from Find a Tender + Contracts Finder.

    Searches for solar, BESS, wind, data centre, grid connection tenders.
    """
    from utils.bmrs_datasets import fetch_energy_tenders
    kw_list = keywords.split(",") if keywords else None
    return await fetch_energy_tenders(kw_list, days_back, limit)


# ═══════════════════════════════════════════════════════════════
#  Autonomous Prospector — proactive opportunity detection
# ═══════════════════════════════════════════════════════════════

@router.get("/api/opportunities/scan")
async def scan_opportunities(
    technology: str = Query(None),
    min_mw: float = Query(5),
    max_mw: float = Query(500),
    region: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Run autonomous opportunity scan across all data sources.

    Detects: grid capacity releases, competitor exits, reinforcement plans.
    Returns ranked opportunities with scores and action packages.
    """
    from utils.autonomous_prospector import run_full_scan
    prefs = {"min_mw": min_mw, "max_mw": max_mw}
    if technology:
        prefs["technology"] = technology
    if region:
        prefs["regions"] = [region]
    return await run_full_scan(pool, prefs)


@router.post("/api/opportunities/action-package")
async def opportunity_action_package(
    opportunity: dict = {},
    capacity_mw: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate complete action package for a specific opportunity."""
    from utils.autonomous_prospector import generate_action_package
    return await generate_action_package(pool, opportunity, capacity_mw)
