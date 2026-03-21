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
    """Retrain XGBoost site viability models on synthetic data.

    Use this endpoint to regenerate models after code changes or
    to increase training set size.
    """
    from utils.ml_site_classifier import _invalidate_cache
    try:
        meta = train_and_save(n_samples=n_samples)
        _invalidate_cache()
        return {"status": "ok", **meta}
    except Exception as e:
        log.exception("ML training failed")
        raise HTTPException(status_code=500, detail=f"Training failed: {e}")
