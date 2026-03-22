"""Planning Intelligence & Regulatory ML — prediction, compliance, constraints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import asyncpg

from app.deps import get_pool, get_current_user

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


# ═══════════════════════════════════════════════════════════════
#  Market Intelligence — generational capabilities
# ═══════════════════════════════════════════════════════════════

class AlertSubscribeRequest(BaseModel):
    technology: str = Field("any", description="Technology filter: solar, wind, bess, any")
    min_mw: float = Field(5, ge=0.1, le=5000)
    max_mw: float = Field(500, ge=0.1, le=5000)
    regions: list[str] = Field(default_factory=list, description="UK regions to monitor")
    irr_hurdle: float = Field(8.0, ge=0, le=50, description="Minimum IRR threshold (%)")
    email: str = Field(None, description="Email address for alerts")
    webhook_url: str = Field(None, description="Webhook URL for JSON alert delivery")
    frequency: str = Field("daily", pattern="^(daily|instant)$")


@router.post("/api/alerts/subscribe")
async def subscribe_to_alerts(
    req: AlertSubscribeRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    """Subscribe to opportunity alerts via email or webhook.

    Princeps continuously monitors grid capacity releases, competitor
    withdrawals, and reinforcement plans. When opportunities matching
    your criteria are detected, you'll be notified immediately or daily.
    """
    from utils.market_intelligence import create_alert_subscription
    return await create_alert_subscription(pool, user["user_id"], req.model_dump())


@router.get("/api/alerts/check")
async def check_alerts(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Manually trigger alert check for all active subscribers.

    Runs the full opportunity scan for each subscriber and dispatches
    alerts via email/webhook. Normally called by the nightly refresh job.
    Returns {sent, skipped, errors}.
    """
    from utils.market_intelligence import check_and_send_alerts
    return await check_and_send_alerts(pool)


class G99GenerateRequest(BaseModel):
    name: str = Field(..., description="Project name")
    capacity_mw: float = Field(..., ge=0.001, le=5000, description="Proposed capacity in MW")
    technology: str = Field("solar", description="Technology: solar, wind, bess, hybrid")
    lat: float = Field(..., ge=49, le=61, description="Site latitude (WGS84)")
    lon: float = Field(..., ge=-8, le=2, description="Site longitude (WGS84)")
    developer: str = Field(None, description="Developer / applicant company name")
    contact_name: str = Field(None, description="Contact person")
    email: str = Field(None, description="Contact email")
    phone: str = Field(None, description="Contact phone")
    company_number: str = Field(None, description="Companies House number")
    company_address: str = Field(None, description="Registered address")
    mpan: str = Field(None, description="MPAN if existing connection")
    land_area_ha: float = Field(None, ge=0, description="Site area in hectares")
    nearest_substation: str = Field(None, description="Nearest grid substation name")
    nearest_substation_distance_km: float = Field(3.0, ge=0, description="Distance to nearest substation (km)")
    headroom_mw: float = Field(None, ge=0, description="Available generation headroom (MW)")
    land_use: str = Field(None, description="Land classification (e.g. agricultural, brownfield)")
    format: str = Field("json", pattern="^(json|html)$", description="Output format: json or html (for PDF)")


@router.post("/api/g99/generate")
async def generate_g99(req: G99GenerateRequest):
    """Auto-generate a pre-filled G99/G100 grid connection application.

    Uses ENA Engineering Recommendation G99 Issue 2 (2023) format.
    All fields are pre-filled from Princeps site assessment data.
    Returns JSON with all form sections, or HTML suitable for PDF rendering.
    """
    from utils.market_intelligence import generate_g99_application, g99_to_pdf_html

    project = {
        "name": req.name,
        "capacity_mw": req.capacity_mw,
        "technology": req.technology,
        "lat": req.lat,
        "lon": req.lon,
        "developer": req.developer,
        "contact_name": req.contact_name,
        "email": req.email,
        "phone": req.phone,
        "company_number": req.company_number,
        "company_address": req.company_address,
        "mpan": req.mpan,
        "land_area_ha": req.land_area_ha,
    }
    grid_context = {
        "nearest_substation": req.nearest_substation or "",
        "nearest_substation_distance_km": req.nearest_substation_distance_km,
        "headroom_mw": req.headroom_mw,
    }
    site_context = {
        "site_name": req.name,
        "land_area_ha": req.land_area_ha,
        "land_use": req.land_use,
    }

    application = generate_g99_application(project, grid_context, site_context)

    if req.format == "html":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=g99_to_pdf_html(application))

    return application


@router.get("/api/land/ownership")
async def land_ownership(
    lat: float = Query(..., ge=49, le=61, description="Latitude (WGS84)"),
    lon: float = Query(..., ge=-8, le=2, description="Longitude (WGS84)"),
    radius_m: int = Query(500, ge=100, le=5000, description="Search radius in metres"),
):
    """Look up land ownership near coordinates using Companies House API.

    Reverse geocodes the location to a postcode, then searches Companies House
    for active companies registered nearby. Filters by SIC codes to identify
    probable landowners (agriculture, real estate) and energy competitors.

    Requires COMPANIES_HOUSE_API_KEY env var for live data; returns mock
    structure otherwise.
    """
    from utils.market_intelligence import lookup_land_ownership
    return await lookup_land_ownership(lat, lon, radius_m)


@router.get("/api/competitive/heatmap")
async def competitive_heatmap(
    technology: str = Query(None, description="Filter by technology (solar, wind, bess)"),
    min_lon: float = Query(None, ge=-10, le=5),
    min_lat: float = Query(None, ge=49, le=62),
    max_lon: float = Query(None, ge=-10, le=5),
    max_lat: float = Query(None, ge=49, le=62),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate competitive density heat map from REPD pipeline data.

    Returns GeoJSON FeatureCollection of ~10km grid cells with:
    project_count, total_mw, developer_count, competitive_pressure
    (LOW/MEDIUM/HIGH/VERY_HIGH).

    Use this to identify underserved areas with grid capacity but
    low developer competition.
    """
    from utils.market_intelligence import competitive_heat_map
    bbox = None
    if all(v is not None for v in [min_lon, min_lat, max_lon, max_lat]):
        bbox = [min_lon, min_lat, max_lon, max_lat]
    return await competitive_heat_map(pool, technology, bbox)


@router.get("/api/market/timing")
async def market_timing(
    capacity_mw: float = Query(..., ge=0.1, le=5000, description="Proposed capacity in MW"),
    technology: str = Query("solar", description="Technology: solar, onshore_wind, bess"),
    region: str = Query("England", description="UK region"),
):
    """Market timing analysis — optimal dates for grid, planning, PPA, and CfD.

    Analyses CfD allocation round timing, PPA forward curve seasonality,
    grid queue merit-based scoring, planning authority seasonality, and
    construction material price trends to recommend an optimal development
    timeline.

    Returns recommended_timeline, irr_sensitivity, market_signals.
    """
    from utils.market_intelligence import market_timing_analysis
    return market_timing_analysis(capacity_mw, technology, region)
