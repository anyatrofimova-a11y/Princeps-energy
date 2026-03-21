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
from utils.report_renderer import generate_report
from utils.xlsx_export import generate_xlsx
from utils.g99_pack_generator import generate_g99_pack
from utils.report_grid_connection import generate_grid_connection_report
from utils.report_financial import generate_financial_report

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
