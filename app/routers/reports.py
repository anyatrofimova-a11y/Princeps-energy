"""Report generation endpoints — PDF + XLSX exports."""

from __future__ import annotations

import logging
import re

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.deps import get_pool
from utils.ml_site_classifier import predict_site, train_and_save, ensemble_score, FEATURE_NAMES
from utils.ml_real_training import run_full_retrain
from utils.report_renderer import generate_report
from utils.xlsx_export import generate_xlsx
from utils.g99_pack_generator import generate_g99_pack
from utils.report_grid_connection import generate_grid_connection_report
from utils.report_financial import generate_financial_report
from utils.constraint_report_generator import generate_constraint_report
from utils.sld_generator import generate_sld
from utils.loss_budget import calculate_loss_budget, calculate_lifetime_profile
from utils.multi_tech_optimizer import optimize_site
from utils.one_click_report import generate_one_click_report

log = logging.getLogger("princeps.reports")
router = APIRouter(tags=["reports"])


def _safe_filename(name: str) -> str:
    """Sanitise site name for use in filename."""
    clean = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
    return clean[:60] or "site"


@router.post("/api/reports/site-assessment")
async def api_site_assessment_report(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    site_name: str = Query("Site", description="Site name for report title"),
    capacity_mw: float = Query(50.0, description="Proposed capacity in MW"),
    template: str = Query("full", description="Report template: full or dashboard"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a branded PDF site assessment report."""
    try:
        async with pool.acquire() as conn:
            pdf_bytes = await generate_report(
                conn, lat, lon, site_name, capacity_mw, template,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Report generation failed")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

    filename = f"princeps-report-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class XlsxExportRequest(BaseModel):
    """Data payload for XLSX financial export."""
    site: dict = {}
    verdict: dict = {}
    yield_data: dict = {}
    grid: dict = {}
    financials: dict = {}
    constraints: dict = {}
    satellite: dict = {}
    placed_assets: list = []


@router.post("/api/reports/financial-xlsx")
async def api_financial_xlsx(req: XlsxExportRequest):
    """Generate a multi-tab XLSX financial input workbook.
    Tabs: Summary, Yield, Grid, Financials, Constraints, Satellite, Assets."""
    try:
        xlsx_bytes = generate_xlsx(req.model_dump())
    except Exception as e:
        log.exception("XLSX generation failed")
        raise HTTPException(status_code=500, detail=f"XLSX generation failed: {e}")

    site_name = req.site.get("name", "site")
    filename = f"princeps-financial-{_safe_filename(site_name)}.xlsx"

    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/reports/grid-connection")
async def grid_connection_report(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    site_name: str = Query("Site", description="Site name for report title"),
    capacity_mw: float = Query(50.0, description="Proposed generation capacity in MW"),
    technology: str = Query("solar", description="Technology type: solar, wind, bess"),
    run_power_flow: bool = Query(False, description="Run Tier 2 pandapower analysis"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a branded PDF grid connection assessment report.

    Performs a full Tier 1 data-driven grid connection assessment including:
    - Nearest substation identification with headroom analysis
    - P10/P50/P90 connection cost estimates for multiple voltage options
    - Queue depth and wait time analysis
    - Actionable recommendations (connection voltage, flexible connection, BESS)
    - Optional Tier 2 pandapower power flow validation

    Returns a downloadable PDF with professional Princeps branding.
    """
    try:
        async with pool.acquire() as conn:
            pdf_bytes = await generate_grid_connection_report(
                conn,
                lat=lat,
                lon=lon,
                capacity_mw=capacity_mw,
                site_name=site_name,
                technology=technology,
                run_power_flow=run_power_flow,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Grid connection report generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Grid connection report generation failed: {e}",
        )

    filename = f"princeps-grid-connection-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class G99PackRequest(BaseModel):
    """Data payload for G99 application pack generation."""
    site: dict = {}
    capacity: dict = {}
    grid: dict = {}
    technology: dict = {}
    agent_result: dict = {}


@router.post("/api/reports/g99-pack")
async def api_g99_pack(req: G99PackRequest):
    """Generate a pre-filled G99 application pack with all form fields,
    compliance checks, and connection parameters from Princeps assessment.
    Returns JSON with form_data + HTML for PDF rendering."""
    try:
        result = generate_g99_pack(req.model_dump())
    except Exception as e:
        log.exception("G99 pack generation failed")
        raise HTTPException(status_code=500, detail=f"G99 pack generation failed: {e}")
    return result


@router.post("/api/reports/g99-pdf")
async def api_g99_pdf(req: G99PackRequest):
    """Generate a G99 application pack as downloadable PDF.
    Uses Playwright for HTML-to-PDF conversion."""
    try:
        result = generate_g99_pack(req.model_dump())
        html = result["html"]
        filename = result["filename"]

        # Try Playwright PDF, fallback to HTML download
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.set_content(html, wait_until="networkidle")
                pdf_bytes = await page.pdf(format="A4", print_background=True, margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"})
                await browser.close()
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except ImportError:
            # Playwright not installed — return HTML instead
            return StreamingResponse(
                iter([html.encode()]),
                media_type="text/html",
                headers={"Content-Disposition": f'attachment; filename="{filename.replace(".pdf", ".html")}"'},
            )
    except Exception as e:
        log.exception("G99 PDF generation failed")
        raise HTTPException(status_code=500, detail=f"G99 PDF generation failed: {e}")


@router.post("/api/reports/financial")
async def financial_report(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    site_name: str = Query("Site", description="Site name for report title"),
    capacity_mw: float = Query(50.0, ge=0.1, le=5000, description="Proposed capacity in MW"),
    technology: str = Query("solar", description="Technology: solar, wind, offshore_wind, bess"),
    ppa_price: float = Query(55.0, ge=1, le=500, description="PPA price in £/MWh"),
):
    """Generate a comprehensive Financial Viability Assessment PDF.

    Runs a full 25-year DCF model with:
    - CAPEX/OPEX breakdown by component
    - Revenue projection with degradation and CPI escalation
    - Annual cashflow table with cumulative tracking
    - IRR sensitivity analysis (PPA price, CAPEX, capacity factor, discount rate)
    - Senior debt sizing with sculpted repayment and DSCR profile
    - Equity returns (pre/post-tax IRR, cash-on-cash yield, equity multiple)
    - Risk register with likelihood/impact/mitigation
    - CB7 reference parameters appendix

    Uses investment_appraisal.py subprocess bridge for DCF calculations.
    Returns a branded Princeps PDF via Playwright Chromium.
    """
    valid_technologies = {"solar", "wind", "offshore_wind", "bess"}
    if technology not in valid_technologies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid technology '{technology}'. Must be one of: {', '.join(sorted(valid_technologies))}",
        )

    try:
        pdf_bytes = await generate_financial_report(
            lat=lat,
            lon=lon,
            site_name=site_name,
            capacity_mw=capacity_mw,
            technology=technology,
            ppa_price=ppa_price,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Financial report generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Financial report generation failed: {e}",
        )

    filename = f"princeps-financial-viability-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Planning Constraint Report
# ---------------------------------------------------------------------------


@router.post("/api/reports/constraint-report")
async def constraint_report(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    capacity_mw: float = Query(50.0, ge=0.1, le=5000, description="Proposed capacity in MW"),
    technology: str = Query("solar", description="Technology: solar, wind, bess, solar+bess"),
    site_name: str = Query("Site", description="Site name for report title"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a professional planning constraint report PDF.

    Produces a comprehensive constraint screening covering:
    - Environmental designations (SSSI, AONB, SAC, SPA, Ramsar, Green Belt)
    - Flood risk assessment (EA flood zones and areas)
    - Heritage constraints (listed buildings, conservation areas, scheduled monuments)
    - Agricultural land classification (BMV screening)
    - Planning risk score (ML-predicted from REPD data)
    - Grid connection feasibility forecast
    - Shadow flicker, noise, and landscape/visual impact summaries
    - Actionable recommendations

    This replaces manual constraint screening that planning consultants
    typically charge GBP 5-20K for.

    Returns a branded Princeps PDF via Playwright Chromium.
    """
    valid_technologies = {"solar", "wind", "bess", "solar+bess", "onshore_wind", "offshore_wind"}
    if technology not in valid_technologies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid technology '{technology}'. Must be one of: {', '.join(sorted(valid_technologies))}",
        )

    try:
        pdf_bytes = await generate_constraint_report(
            pool,
            lat=lat,
            lon=lon,
            capacity_mw=capacity_mw,
            technology=technology,
            site_name=site_name,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("Constraint report generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Constraint report generation failed: {e}",
        )

    filename = f"princeps-constraint-report-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# ML Site Viability Classifier
# ---------------------------------------------------------------------------


class MLSiteScoreRequest(BaseModel):
    """17 features for ML site viability prediction."""
    ghi_kwh_m2_yr: float = 1000.0
    wind_speed_ms: float = 6.0
    slope_mean_deg: float = 5.0
    slope_p90_deg: float = 8.0
    south_facing_pct: float = 40.0
    elevation_m: float = 100.0
    developable_pct: float = 55.0
    built_pct: float = 12.0
    trees_pct: float = 13.0
    water_pct: float = 3.0
    grid_distance_km: float = 5.0
    grid_headroom_mw: float = 5.0
    flood_risk_score: float = 10.0
    ndvi_mean: float = 0.45
    ndvi_trend_slope: float = 0.0
    sar_vv_mean_db: float = -12.0
    cloud_clear_pct: float = 42.0
    # Optional ensemble inputs
    rule_score: float | None = None
    agent_confidence: float | None = None


@router.post("/api/ml/site-score")
async def ml_site_score(req: MLSiteScoreRequest):
    """Predict site viability using XGBoost classifier + regressor.

    Returns GO/CAUTION/NO-GO verdict, 0-100 score, confidence %,
    SHAP feature importance values, and top contributing factors.

    If rule_score or agent_confidence are provided, also returns an
    ensemble meta-score blending rule + ML + agent signals.
    """
    features = {name: getattr(req, name) for name in FEATURE_NAMES}
    result = predict_site(features)

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    # Ensemble if extra signals provided
    if req.rule_score is not None or req.agent_confidence is not None:
        ens = ensemble_score(
            rule_score=req.rule_score if req.rule_score is not None else result["score"],
            ml_result=result,
            agent_confidence=req.agent_confidence,
        )
        result["ensemble"] = ens

    return result


@router.post("/api/ml/train")
async def ml_train(n_samples: int = Query(1000, ge=100, le=10000)):
    """Retrain XGBoost site viability models on synthetic data."""
    from utils.ml_site_classifier import _invalidate_cache
    try:
        meta = train_and_save(n_samples=n_samples)
        _invalidate_cache()
        return {"status": "ok", **meta}
    except Exception as e:
        log.exception("ML training failed")
        raise HTTPException(status_code=500, detail=f"Training failed: {e}")


@router.post("/api/ml/retrain-real")
async def ml_retrain_real(pool: asyncpg.Pool = Depends(get_pool)):
    """Retrain ML models on REAL UK REPD data instead of synthetic samples.

    Extracts training data from the repd_projects table (~14,000 real UK
    renewable energy projects with planning outcomes), then trains:
    1. Site viability classifier (GO / CAUTION / NO-GO) + regressor (0-100)
    2. Planning risk model (APPROVED / CONDITIONAL / REFUSED)

    Returns metrics for both models plus a comparison with the synthetic
    baseline. If the real-trained model performs well, it is automatically
    promoted to the primary model used by /api/ml/site-score.

    Falls back to hybrid training (real + synthetic augmentation) if fewer
    than 500 REPD projects are available.
    """
    try:
        result = await run_full_retrain(pool)
        return result
    except Exception as e:
        log.exception("Real-data ML retraining failed")
        raise HTTPException(status_code=500, detail=f"Real-data retraining failed: {e}")


# ---------------------------------------------------------------------------
# Advanced ML Models — Planning Risk, Financial IRR, Site Ranking
# ---------------------------------------------------------------------------

@router.post("/api/ml/planning-risk")
async def ml_planning_risk(
    distance_to_residential_km: float = Query(1.5),
    num_nearby_solar_farms: int = Query(2),
    aonb_proximity_km: float = Query(10),
    green_belt: bool = Query(False),
    flood_zone: int = Query(1),
    agricultural_grade: int = Query(3),
    local_authority_approval_rate: float = Query(0.85),
    capacity_mw: float = Query(5),
    height_above_ground_m: float = Query(3),
    landscape_sensitivity: int = Query(2),
):
    """Predict planning outcome using XGBoost classifier.
    Returns APPROVED / CONDITIONAL / REFUSED with probability + SHAP explanation."""
    from utils.ml_advanced_models import predict_planning_risk
    features = {
        "distance_to_residential_km": distance_to_residential_km,
        "num_nearby_solar_farms": num_nearby_solar_farms,
        "aonb_proximity_km": aonb_proximity_km,
        "green_belt": int(green_belt),
        "flood_zone": flood_zone,
        "agricultural_grade": agricultural_grade,
        "local_authority_approval_rate": local_authority_approval_rate,
        "capacity_mw": capacity_mw,
        "height_above_ground_m": height_above_ground_m,
        "landscape_sensitivity": landscape_sensitivity,
    }
    return predict_planning_risk(features)


@router.post("/api/ml/financial-irr")
async def ml_financial_irr(
    capacity_mw: float = Query(5),
    annual_yield_mwh: float = Query(5475),
    grid_distance_km: float = Query(2),
    connection_cost_gbp: float = Query(300000),
    ppa_price_gbp_mwh: float = Query(55),
    capex_per_kw: float = Query(650),
    opex_per_kw_yr: float = Query(10),
    degradation_pct: float = Query(0.5),
    project_life_years: int = Query(25),
    wacc_pct: float = Query(6.0),
    land_rent_per_ha: float = Query(1200),
):
    """Predict project IRR (%) using XGBoost regressor.
    Returns predicted IRR, viability band (STRONG/VIABLE/MARGINAL/UNVIABLE), + SHAP factors."""
    from utils.ml_advanced_models import predict_financial_irr
    features = {
        "capacity_mw": capacity_mw, "annual_yield_mwh": annual_yield_mwh,
        "grid_distance_km": grid_distance_km, "connection_cost_gbp": connection_cost_gbp,
        "ppa_price_gbp_mwh": ppa_price_gbp_mwh, "capex_per_kw": capex_per_kw,
        "opex_per_kw_yr": opex_per_kw_yr, "degradation_pct": degradation_pct,
        "project_life_years": project_life_years, "wacc_pct": wacc_pct,
        "land_rent_per_ha": land_rent_per_ha,
    }
    return predict_financial_irr(features)


class RankSitesRequest(BaseModel):
    sites: list[dict]


@router.post("/api/ml/rank-sites")
async def ml_rank_sites(req: RankSitesRequest):
    """Rank candidate sites by composite ML quality score.
    Combines site viability + planning risk + financial IRR into a unified ranking.
    Returns sites sorted by composite score with tier labels (A/B/C)."""
    from utils.ml_advanced_models import rank_sites
    if not req.sites:
        raise HTTPException(400, "Empty site list")
    if len(req.sites) > 100:
        raise HTTPException(400, "Maximum 100 sites per ranking request")
    return {"ranked_sites": rank_sites(req.sites), "count": len(req.sites)}


class MLEnhancedReportRequest(BaseModel):
    site: dict = {}
    verdict: dict = {}
    yield_data: dict = {}
    grid: dict = {}
    satellite: dict = {}
    features: dict = {}
    comparison_sites: list[dict] = []


@router.post("/api/reports/ml-enhanced")
async def ml_enhanced_report(req: MLEnhancedReportRequest):
    """Generate an ML-enhanced site assessment report with SHAP explanations,
    ensemble verdicts, and site comparison tables. Returns HTML (or PDF if Playwright available)."""
    from utils.ml_report_section import render_ml_enhanced_report
    from utils.ml_site_classifier import predict_site, ensemble_score

    # Run ML prediction
    ml_result = predict_site(req.features) if req.features else {"verdict": "—", "score": 0, "confidence": 0, "top_factors": []}
    ensemble = None
    if req.verdict.get("confidence"):
        ensemble = ensemble_score(
            rule_score=req.verdict.get("rule_score"),
            ml_result=ml_result,
            agent_confidence=req.verdict.get("confidence"),
        )

    # Render report
    html = render_ml_enhanced_report(
        site=req.site,
        ml_result=ml_result,
        ensemble=ensemble,
        yield_data=req.yield_data,
        grid=req.grid,
        satellite=req.satellite,
        comparison_sites=req.comparison_sites,
    )

    site_name = req.site.get("name", "site")
    filename = f"princeps-ml-report-{_safe_filename(site_name)}"

    # Try PDF, fallback to HTML
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            await browser.close()
        return StreamingResponse(
            iter([pdf_bytes]), media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )
    except ImportError:
        return StreamingResponse(
            iter([html.encode()]), media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
        )


# ---------------------------------------------------------------------------
# Single Line Diagram (SLD) Generator
# ---------------------------------------------------------------------------


class SLDRequest(BaseModel):
    """Assets and parameters for Single Line Diagram generation."""
    assets: list[dict] = []
    capacity_kw: float = 5000.0
    voltage_kv: float = 33.0


@router.post("/api/design/sld")
async def api_generate_sld(req: SLDRequest):
    """Generate an SVG Single Line Diagram from placed assets.

    Takes solar arrays, BESS, inverters, transformers and produces:
    - Professional IEC-standard SVG single line diagram (800x400)
    - Structured component list with voltages and stages
    - Auto-calculated cable schedule with sizing

    Flow: Generation -> Combiner -> Inverter -> Transformer -> Protection -> Grid
    """
    if req.capacity_kw <= 0:
        raise HTTPException(status_code=422, detail="capacity_kw must be positive")
    if req.voltage_kv <= 0:
        raise HTTPException(status_code=422, detail="voltage_kv must be positive")

    try:
        result = generate_sld(
            assets=req.assets,
            capacity_kw=req.capacity_kw,
            voltage_kv=req.voltage_kv,
        )
    except Exception as e:
        log.exception("SLD generation failed")
        raise HTTPException(status_code=500, detail=f"SLD generation failed: {e}")

    return result


# ---------------------------------------------------------------------------
# Solar Loss Budget Calculator (DNV GL bankable standard)
# ---------------------------------------------------------------------------


class LossBudgetRequest(BaseModel):
    """Input parameters for DNV GL-standard solar loss budget."""
    capacity_kw: float = 1000.0
    lat: float = 52.0
    lon: float = -1.0
    tilt_deg: float = 25.0
    azimuth_deg: float = 180.0
    row_spacing_m: float | None = None
    panel_height_m: float = 2.384
    dc_ac_ratio: float = 1.20
    inverter_efficiency: float = 0.98
    year: int = 1
    region: str | None = None
    terrain_shading_pct: float | None = None
    monthly_temps_c: list[float] | None = None
    annual_ghi_kwh_m2: float | None = None
    temp_coeff: float = -0.40
    noct_offset: float = 25.0
    iam_b0: float = 0.05
    module_quality_pct: float = 1.5
    module_mismatch_pct: float = 0.4
    lid_pct: float = 1.5
    annual_degradation_pct: float = 0.50
    dc_wiring_pct: float = 1.0
    ac_wiring_pct: float = 0.4
    auxiliary_pct: float = 0.5
    planned_downtime_pct: float = 0.5
    unplanned_downtime_pct: float = 1.0
    curtailment_pct: float | None = None
    anm_scheme: bool = False
    export_limit_pct: float | None = None
    # Lifetime profile
    include_lifetime: bool = False
    project_life_years: int = 25


@router.post("/api/design/loss-budget")
async def api_loss_budget(req: LossBudgetRequest):
    """Calculate a comprehensive DNV GL-standard solar energy loss budget.

    Computes 16 individual loss categories applied as a multiplicative
    waterfall from gross POA energy down to net export energy:

    1. Far shading (horizon/terrain)
    2. Near shading (inter-row)
    3. Soiling (UK regional rainfall model)
    4. IAM / Reflection (ASHRAE incidence angle modifier)
    5. Temperature (cell temp from NOCT + ambient)
    6. Module quality / nameplate tolerance
    7. Module mismatch
    8. LID + annual degradation (cumulative)
    9. DC wiring I²R losses
    10. Inverter efficiency (partial-load derating)
    11. Inverter clipping (DC/AC ratio dependent)
    12. Transformer iron + copper losses
    13. AC wiring losses
    14. Auxiliary consumption (tracking, monitoring, HVAC)
    15. Availability (planned + unplanned downtime)
    16. Grid curtailment (ANM / export limitation)

    Returns performance ratio, specific yield, capacity factor, per-category
    breakdown, and waterfall chart data for Sankey/cascade visualisation.

    Optionally includes a 25-year lifetime degradation profile with
    P50/P90 annual energy estimates.
    """
    if req.capacity_kw <= 0:
        raise HTTPException(status_code=422, detail="capacity_kw must be positive")
    if not (-90 <= req.lat <= 90):
        raise HTTPException(status_code=422, detail="lat must be between -90 and 90")
    if not (-180 <= req.lon <= 180):
        raise HTTPException(status_code=422, detail="lon must be between -180 and 180")
    if req.dc_ac_ratio < 0.5 or req.dc_ac_ratio > 2.5:
        raise HTTPException(status_code=422, detail="dc_ac_ratio must be between 0.5 and 2.5")

    try:
        params = req.model_dump(exclude={"include_lifetime", "project_life_years"})
        result = calculate_loss_budget(params)

        if req.include_lifetime:
            lifetime = calculate_lifetime_profile(params, req.project_life_years)
            result["lifetime"] = lifetime

    except Exception as e:
        log.exception("Loss budget calculation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Loss budget calculation failed: {e}",
        )

    return result


# ---------------------------------------------------------------------------
# Multi-Technology Site Optimization
# ---------------------------------------------------------------------------


class OptimizeSiteRequest(BaseModel):
    """Input parameters for multi-technology site optimization."""
    lat: float = 52.0
    lon: float = -1.0
    area_ha: float = 40.0
    grid_headroom_mw: float = 30.0
    ghi: float = 1000.0
    wind_speed: float = 5.5
    grid_distance_km: float = 3.0
    objective: str = "maximize_irr"
    ppa_price: float = 55.0
    bess_revenue_per_mw: float = 90000.0
    discount_rate: float = 0.07
    project_life: int = 30
    degradation: float = 0.005
    cpi: float = 0.025


@router.post("/api/design/optimize-site")
async def api_optimize_site(req: OptimizeSiteRequest):
    """Multi-technology site optimization engine.

    Evaluates 8 technology scenarios for a single site and ranks them by
    configurable objective. No competitor offers single-call comparison of
    ALL technology options with full financial appraisal.

    Scenarios evaluated:
    1. Solar PV (fixed tilt)
    2. Solar PV (single-axis tracker)
    3. Solar + BESS (co-located)
    4. BESS only (standalone)
    5. Wind only (if wind speed > 5 m/s)
    6. Solar + Wind hybrid
    7. Solar + Wind + BESS
    8. Data Centre + Solar + BESS

    Each scenario returns: optimal capacity, annual yield, capacity factor,
    LCOE, IRR, NPV, CAPEX, annual revenue, carbon displacement,
    grid curtailment risk, and planning risk.

    Ranking objectives: maximize_irr (default), minimize_lcoe,
    maximize_carbon, maximize_revenue.

    Returns ranked scenarios with winner, runner-up, and recommendation narrative.
    """
    valid_objectives = {"maximize_irr", "minimize_lcoe", "maximize_carbon", "maximize_revenue"}
    if req.objective not in valid_objectives:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid objective '{req.objective}'. Must be one of: {', '.join(sorted(valid_objectives))}",
        )
    if req.area_ha <= 0:
        raise HTTPException(status_code=422, detail="area_ha must be positive")
    if req.grid_headroom_mw <= 0:
        raise HTTPException(status_code=422, detail="grid_headroom_mw must be positive")

    try:
        result = optimize_site(
            lat=req.lat,
            lon=req.lon,
            area_ha=req.area_ha,
            grid_headroom_mw=req.grid_headroom_mw,
            ghi=req.ghi,
            wind_speed=req.wind_speed,
            grid_distance_km=req.grid_distance_km,
            objective=req.objective,
            ppa_price=req.ppa_price,
            bess_revenue_per_mw=req.bess_revenue_per_mw,
            discount_rate=req.discount_rate,
            project_life=req.project_life,
            degradation=req.degradation,
            cpi=req.cpi,
        )
    except Exception as e:
        log.exception("Site optimization failed")
        raise HTTPException(
            status_code=500,
            detail=f"Site optimization failed: {e}",
        )

    return result


# ---------------------------------------------------------------------------
# One-Click Comprehensive Feasibility Report
# ---------------------------------------------------------------------------


@router.post("/api/reports/one-click")
async def one_click_report(
    lat: float = Query(..., description="Site latitude (WGS84)"),
    lon: float = Query(..., description="Site longitude (WGS84)"),
    capacity_mw: float = Query(50.0, ge=0.1, le=5000, description="Proposed capacity in MW"),
    technology: str = Query("solar", description="Technology: solar, wind, bess, solar+bess"),
    site_name: str = Query("Site", description="Site name for report branding"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a one-click comprehensive feasibility report.

    Drop a pin on the map, click one button, get a 30-page institutional-grade
    PDF covering everything -- in 60 seconds.

    Orchestrates ALL Princeps modules in parallel:
    - Site data aggregation (PostGIS: substations, GeeFlow, parcels, demand)
    - Solar yield via NREL PvWattsv8 (SAM subprocess)
    - Grid connection assessment (Tier 1 data-driven + P10/P50/P90 cost)
    - Environmental constraints (SSSI, SAC, AONB, Green Belt, flood, ALC)
    - ML site viability (XGBoost + SHAP explainability)
    - DNV GL 16-category loss budget waterfall
    - 25-year DCF financial model (IRR, NPV, LCOE, payback, debt sizing)
    - Multi-technology comparison (solar, wind, BESS, solar+BESS)
    - BNG biodiversity net gain baseline estimate
    - Planning risk prediction (ML from REPD data)
    - Demand forecast (nearest GSP)
    - Carbon intensity (National Grid ESO)

    Returns a branded Princeps PDF with:
    - Cover page + legal disclaimer + document control
    - Executive summary with GO/CAUTION/NO-GO verdict
    - P50/P75/P90/P95/P99 energy exceedance table
    - 11 detailed sections with charts
    - Appendices: SHAP factors, financial sensitivity, loss waterfall
    """
    valid_technologies = {"solar", "wind", "bess", "solar+bess"}
    if technology not in valid_technologies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid technology '{technology}'. Must be one of: {', '.join(sorted(valid_technologies))}",
        )

    try:
        pdf_bytes = await generate_one_click_report(
            pool=pool,
            lat=lat,
            lon=lon,
            capacity_mw=capacity_mw,
            technology=technology,
            site_name=site_name,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("One-click report generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"One-click report generation failed: {e}",
        )

    filename = f"princeps-feasibility-{_safe_filename(site_name)}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# PV Auto-Layout Engine
# ---------------------------------------------------------------------------


class AutoLayoutRequest(BaseModel):
    """Input parameters for automated PV layout generation."""
    lat: float = 52.0
    lon: float = -1.0
    capacity_mw: float = 50.0
    area_ha: float | None = None
    boundary_coords: list[list[float]] | None = None
    technology: str = "fixed_tilt"
    tilt_deg: float | None = None
    gcr_target: float | None = None
    module_watts: int = 580
    module_width_m: float = 1.05
    module_height_m: float = 2.10
    setback_m: float = 10.0
    dc_ac_ratio: float = 1.25
    modules_per_string: int = 28
    terrain: dict | None = None
    constraints: dict | None = None
    grid_connection_point: list[float] | None = None


@router.post("/api/design/auto-layout")
async def api_auto_layout(req: AutoLayoutRequest):
    """Generate an optimised PV layout for a utility-scale solar site.

    RatedPower / PVcase-class automated layout engine that produces:
    - Panel row placement with optimal row spacing (winter solstice shading)
    - Block decomposition with 4 m access roads every 500 m
    - Terrain-aware exclusions: slope >15 deg, north-facing, flood, buildings + 50 m buffer
    - Infrastructure: inverter stations (1/5MW), combiner boxes (1/1MW),
      transformers (1/10MW), substation at perimeter
    - Full BOM with cable lengths, mounting structures, fencing
    - CAPEX/OPEX financial inputs with UK cost benchmarks
    - GeoJSON FeatureCollection for map visualisation

    Module spec: 2.1 m x 1.05 m, 580 W bifacial (configurable).
    Technologies: fixed_tilt (GCR 0.35-0.45) or single_axis_tracker (GCR 0.25-0.35).

    Returns layout, BOM, financial_inputs, buildable_area_ha,
    total_site_area_ha, utilization_pct, geojson, statistics.
    """
    from utils.pv_layout_engine import generate_pv_layout

    valid_technologies = {"fixed_tilt", "single_axis_tracker"}
    if req.technology not in valid_technologies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid technology '{req.technology}'. Must be one of: {', '.join(sorted(valid_technologies))}",
        )
    if req.capacity_mw <= 0:
        raise HTTPException(status_code=422, detail="capacity_mw must be positive")
    if not (-90 <= req.lat <= 90):
        raise HTTPException(status_code=422, detail="lat must be between -90 and 90")
    if not (-180 <= req.lon <= 180):
        raise HTTPException(status_code=422, detail="lon must be between -180 and 180")

    try:
        result = generate_pv_layout(
            lat=req.lat,
            lon=req.lon,
            capacity_mw=req.capacity_mw,
            area_ha=req.area_ha,
            boundary_coords=req.boundary_coords,
            technology=req.technology,
            tilt_deg=req.tilt_deg,
            gcr_target=req.gcr_target,
            module_watts=req.module_watts,
            module_width_m=req.module_width_m,
            module_height_m=req.module_height_m,
            setback_m=req.setback_m,
            terrain=req.terrain,
            constraints=req.constraints,
            grid_connection_point=req.grid_connection_point,
            dc_ac_ratio=req.dc_ac_ratio,
            modules_per_string=req.modules_per_string,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.exception("PV auto-layout generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"PV auto-layout generation failed: {e}",
        )

    return result
