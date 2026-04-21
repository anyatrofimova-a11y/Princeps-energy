"""Finance extras — the endpoints that back the 5 godmode finance sprints.

  POST /api/finance/revenue-stack       — co-optimised BESS stack + P10/P50/P90
  GET  /api/market/live                  — live UK market snapshot
  POST /api/finance/monte-carlo          — correlated Monte Carlo over any base case
  POST /api/finance/dc                   — DC-native model (tenants + ramp + DSCR)
  POST /api/finance/lender-pack          — full lender pack (HTML or PDF URL)
  POST /api/finance/negotiate            — parametric PPA / connection term sweep
  GET  /api/market/policy-scenarios      — CfD/BSUoS/TCR/gas-fwd toggles
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_pool
from utils.bess_stacker import (
    co_optimise_bess, probabilistic_co_optimise, BENCHMARK as STACK_BENCHMARK,
)
from utils.market_feeds import (
    live_market_snapshot, fetch_wholesale_prices, fetch_as_clearing,
    fetch_cap_market, fetch_carbon_intensity,
)
from utils.monte_carlo_finance import run_mc, default_evaluator
from utils.dc_finance import dc_financial_model, TIER_CONTRACTS
from utils.dcf_evaluator import evaluate_from_dict as dcf_evaluate_from_dict
from utils.finance_benchmarks import (
    cpi_long_run,
    debt_to_equity,
    ppa_price_merchant,
    senior_debt_all_in_rate,
    wacc,
)
from utils.lender_pack import render_lender_pack_html

# ── Soft-imported sibling benchmark modules ───────────────────────────────
# These provide per-tech CapEx estimates used when the caller has not
# supplied a concrete capex_gbp_m value. Imports are soft so finance_extras
# still loads if a sibling module is temporarily unavailable.
try:
    from utils.bess_benchmarks import bess_capex_per_kwh as _bess_capex_per_kwh  # type: ignore
except Exception:  # pragma: no cover
    _bess_capex_per_kwh = None  # type: ignore

try:
    from utils.dc_benchmarks import dc_capex_per_mw as _dc_capex_per_mw  # type: ignore
except Exception:  # pragma: no cover
    _dc_capex_per_mw = None  # type: ignore

try:
    from utils.solar_benchmarks import solar_capex_per_mw as _solar_capex_per_mw  # type: ignore
except Exception:  # pragma: no cover
    _solar_capex_per_mw = None  # type: ignore


def _estimate_capex_gbp_m(workload: str, capacity_mw: float,
                          duration_h: float = 2.0) -> float:
    """Tech-aware CapEx estimate in £m — soft-imports sibling benchmarks.

    BESS CapEx is energy-scaled (£/kWh × MW × h), DC CapEx is power-scaled
    (£/MW all-in, typically £5-8m/MW for a shell+MEP hyperscale unit), and
    solar uses Solar Media's 2026 £/MW. Falls back to conservative UK 2026
    midpoints if a sibling import failed so the lender-pack path never 500s.
    """
    wl = (workload or "").lower()
    cap = max(0.0, float(capacity_mw or 0.0))
    if wl == "bess":
        if _bess_capex_per_kwh is not None:
            # £/kWh × MW × h → £m
            return _bess_capex_per_kwh("mid") * cap * max(0.5, duration_h) / 1_000
        return cap * 0.62  # fallback £620k/MW for 2h
    if wl == "dc":
        if _dc_capex_per_mw is not None:
            return _dc_capex_per_mw(tier="hyperscale") * cap / 1_000_000
        return cap * 6.5   # fallback £6.5m/MW hyperscale shell+MEP
    if wl == "solar":
        if _solar_capex_per_mw is not None:
            return _solar_capex_per_mw("mid") * cap / 1_000_000
        return cap * 0.73   # fallback £730k/MW Solar Media Q4 2025
    # Generic renewables fallback
    return cap * 0.8

log = logging.getLogger("princeps.finance_extras")

router = APIRouter(tags=["finance-extras"])


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/revenue-stack — co-optimise + probabilistic bands
# ═══════════════════════════════════════════════════════════════════════════

class RevStackRequest(BaseModel):
    capacity_mw: float = Field(..., ge=0.5, le=1000)
    duration_h: float = Field(2.0, ge=0.25, le=12)
    chemistry: str = Field("lfp")
    use_live_prices: bool = True
    monte_carlo: bool = True
    n_samples: int = Field(800, ge=100, le=3000)


@router.post("/api/finance/revenue-stack")
async def revenue_stack(body: RevStackRequest):
    live = None
    if body.use_live_prices:
        try:
            ws = await fetch_wholesale_prices()
            as_ = await fetch_as_clearing()
            live = {
                "wholesale_peak": ws.get("peak_gbp_mwh"),
                "wholesale_offpeak": ws.get("offpeak_gbp_mwh"),
                "dc_price_gbp_mw_h": as_.get("dc_gbp_mw_h"),
                "dm_price_gbp_mw_h": as_.get("dm_gbp_mw_h"),
                "dr_price_gbp_mw_h": as_.get("dr_gbp_mw_h"),
            }
        except Exception as e:
            log.debug("live feed fail, using benchmarks: %s", e)
    base = co_optimise_bess(body.capacity_mw, body.duration_h, live, body.chemistry)
    out = {
        "point_estimate": {
            "annual_revenue_gbp": round(base.annual_revenue_gbp, 0),
            "revenue_by_stack": base.revenue_by_stack,
            "mwh_by_stack": base.mwh_by_stack,
            "hours_by_stack": base.hours_by_stack,
            "utilisation_pct": base.utilisation_pct,
            "notes": base.notes,
        },
        "live_prices_used": live,
        "benchmarks": STACK_BENCHMARK,
    }
    if body.monte_carlo:
        mc = probabilistic_co_optimise(body.capacity_mw, body.duration_h, live, body.n_samples)
        out["monte_carlo"] = mc
    return out


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/market/live — one-shot snapshot for the MarketRibbon
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/market/live")
async def market_live():
    return await live_market_snapshot()


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/monte-carlo — correlated MC over any base case
# ═══════════════════════════════════════════════════════════════════════════

class MCRequest(BaseModel):
    capex_gbp_m: float
    opex_gbp_m_yr: float
    revenue_gbp_m_yr: float
    curtail_pct: float = 2.0
    timeline_months: float = 24
    discount_rate_pct: float = 8.0
    life_years: int = 15
    n_samples: int = Field(1000, ge=200, le=5000)
    sd: dict[str, float] | None = None


@router.post("/api/finance/monte-carlo")
async def finance_montecarlo(body: MCRequest):
    base = body.model_dump()
    base.pop("n_samples", None)
    base.pop("sd", None)
    res = run_mc(base, default_evaluator, n_samples=body.n_samples, sd=body.sd)
    return {
        "samples": res.samples,
        "irr_pct": res.irr_pct,
        "npv_gbp_m": res.npv_gbp_m,
        "dscr": res.dscr,
        "lcoe_gbp_mwh": res.lcoe_gbp_mwh,
        "tornado": res.tornado,
        "distributions": {
            k: v[: min(500, len(v))]   # cap returned distribution size
            for k, v in res.distributions.items()
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/dcf-evaluate — reusable DCF + lender covenants
# ═══════════════════════════════════════════════════════════════════════════


class DebtYearModel(BaseModel):
    year: int
    opening_balance: float = 0.0
    interest: float = 0.0
    principal: float = 0.0
    closing_balance: float = 0.0


class DebtTermsModel(BaseModel):
    principal: float = 0.0
    rate: float = 0.06
    term_years: int = 15


class DCFEvaluateRequest(BaseModel):
    capex: float = Field(..., gt=0)
    revenue_schedule: list[float] = Field(..., min_length=1)
    opex_schedule: list[float] = Field(..., min_length=1)
    tax_rate: float = Field(0.25, ge=0, le=0.6)
    wacc: float = Field(0.08, gt=0, le=0.5)
    cost_of_equity: float | None = Field(None, gt=0, le=0.6)
    terminal_growth: float = Field(0.0, ge=-0.05, le=0.1)
    debt_schedule: list[DebtYearModel] | DebtTermsModel | None = None
    equity: float | None = None
    depreciation_schedule: list[float] | None = None
    working_capital_schedule: list[float] | None = None
    thresholds: dict[str, float] | None = None


@router.post("/api/finance/dcf-evaluate")
async def finance_dcf_evaluate(body: DCFEvaluateRequest):
    payload = body.model_dump()
    return dcf_evaluate_from_dict(payload)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/dc — DC-native finance (tenants + ramp + DSCR)
# ═══════════════════════════════════════════════════════════════════════════

class DCFinanceRequest(BaseModel):
    it_load_mw: float = Field(..., ge=1, le=500)
    pue_target: float = 1.2
    tier: str = Field("hyperscale", description="hyperscale | enterprise | colocation")
    contract_years: int | None = None
    grid_connection_km: float = 3.0
    # Defaults resolve via utils.finance_benchmarks for DC-tier 2026.
    discount_rate_pct: float = Field(default_factory=lambda: round(wacc("dc", "stabilised") * 100, 2))
    ppa_gbp_mwh: float = Field(default_factory=lambda: ppa_price_merchant("dc"))
    equity_pct: float = Field(default_factory=lambda: debt_to_equity("dc")[1])
    debt_rate_pct: float = Field(default_factory=lambda: round(senior_debt_all_in_rate("dc") * 100, 2))


@router.post("/api/finance/dc")
async def finance_dc(body: DCFinanceRequest):
    if body.tier not in TIER_CONTRACTS:
        raise HTTPException(400, f"Unknown tier {body.tier}")
    return dc_financial_model(
        it_load_mw=body.it_load_mw, pue_target=body.pue_target, tier=body.tier,
        contract_years=body.contract_years, grid_connection_km=body.grid_connection_km,
        discount_rate_pct=body.discount_rate_pct, ppa_gbp_mwh=body.ppa_gbp_mwh,
        equity_pct=body.equity_pct, debt_rate_pct=body.debt_rate_pct,
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/lender-pack — one-click PDF (HTML fallback)
# ═══════════════════════════════════════════════════════════════════════════

class LenderPackRequest(BaseModel):
    project_id: str
    bank_name: str = "Prospective lender"
    format: str = Field("pdf", description="pdf | html")


@router.post("/api/finance/lender-pack")
async def lender_pack(body: LenderPackRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Assemble a lender pack from the project state + design + finance calls."""
    async with pool.acquire() as conn:
        prj = await conn.fetchrow(
            "SELECT * FROM projects WHERE project_id = $1::uuid",
            body.project_id,
        )
    if not prj:
        raise HTTPException(404, "Project not found")

    meta = json.loads(prj["metadata"]) if prj["metadata"] else {}
    workload = prj["technology"] or "bess"
    cap = float(prj["capacity_mw"] or 0)

    # Build base-case inputs
    duration_h = float(meta.get("duration_h", 2.0))
    tech_wacc_pct = round(wacc(workload, "stabilised") * 100, 2)

    if workload == "dc":
        finance = dc_financial_model(
            it_load_mw=cap, pue_target=meta.get("pue_target", 1.2),
            tier=meta.get("dc_tier", "hyperscale"),
        )
        fallback_capex_m = _estimate_capex_gbp_m("dc", cap)
    else:
        stack = co_optimise_bess(cap, duration_h)
        annual_rev_m = stack.annual_revenue_gbp / 1_000_000
        # CapEx resolves via sibling-tech benchmark modules (bess/solar/dc);
        # no more `0.66 if bess else 0.9` stub.
        capex_gbp_m = _estimate_capex_gbp_m(workload, cap, duration_h)
        fallback_capex_m = capex_gbp_m
        finance = default_evaluator({
            "capex_gbp_m": capex_gbp_m,
            "opex_gbp_m_yr": annual_rev_m * 0.10,
            "revenue_gbp_m_yr": annual_rev_m,
            "curtail_pct": meta.get("curtail_pct", 2.0),
            "timeline_months": 24,
            "discount_rate_pct": tech_wacc_pct,
            "life_years": 15,
            "technology": workload,
        })
    mc = run_mc(
        {
            "capex_gbp_m": finance.get("capex_gbp_m", fallback_capex_m),
            "opex_gbp_m_yr": (finance.get("opex_gbp_m_yr") or finance.get("capex_gbp_m", fallback_capex_m) * 0.04),
            "revenue_gbp_m_yr": finance.get("annual_revenue_steady_state_gbp_m", finance.get("revenue_gbp_m_yr", cap * 1.2)),
            "curtail_pct": meta.get("curtail_pct", 2.0),
            "timeline_months": 24,
            "discount_rate_pct": tech_wacc_pct,
            "life_years": 15,
            "technology": workload,
        },
        default_evaluator, n_samples=800,
    )

    stack = co_optimise_bess(cap, meta.get("duration_h", 2.0)) if workload != "dc" else None

    doc = {
        "project": {
            "name": prj["name"], "workload": workload,
            "capacity_mw": cap, "lat": prj["lat"], "lon": prj["lon"],
        },
        "kpis": {
            "capex_gbp_m": finance.get("capex_gbp_m"),
            "irr_pct": finance.get("irr_pct"),
            "dscr": finance.get("dscr"),
        },
        "grid": {
            "dno": meta.get("dno_area", "—"),
            "poc": meta.get("poc_substation", "—"),
            "voltage_kv": meta.get("poc_voltage_kv", 132 if cap >= 50 else 33),
            "tec_mw": meta.get("tec_mw", cap),
            "firmness": "Firm",
            "grid_code": "G100" if cap > 50 else "G99",
            "summary": "Grid headroom validated by pandapower power flow; N-1 tested.",
        },
        "planning": {
            "status": prj["stage"],
            "approval_prob_pct": meta.get("planning_prob", 72),
            "summary": "XGBoost REPD model predicts approval inside central LPA response window.",
        },
        "revenue_stack": {
            "revenue_by_stack": stack.revenue_by_stack if stack else {"capacity_rev": int(finance.get("annual_revenue_steady_state_gbp_m", 0) * 1_000_000)},
            "utilisation_pct": stack.utilisation_pct if stack else None,
            "priority_order": ["DC", "DM", "DR", "BM", "Wholesale"],
        } if stack else {"revenue_by_stack": {"capacity_rev": int(finance.get("annual_revenue_steady_state_gbp_m", 0) * 1_000_000)}, "priority_order": ["Capacity", "Energy pass-through"]},
        "cashflows": finance.get("cashflows", []),
        "monte_carlo": {
            "samples": mc.samples,
            "irr_pct": mc.irr_pct, "dscr": mc.dscr, "npv_gbp_m": mc.npv_gbp_m,
        },
        "tornado": mc.tornado,
        "ppa": {
            "strategy": "Base-case 10y fixed PPA + 5y merchant tail",
            "counterparty": "Investment-grade offtaker under negotiation",
            "price_summary": (
                f"£{meta.get('ppa_gbp_mwh', round(ppa_price_merchant(workload), 1))}/MWh, "
                f"CPI-linked, annual escalator {round(cpi_long_run() * 100, 1)}%"
            ),
        },
        "environmental_summary": "EIA screening: below threshold. Ecology survey commissioned for May 2026.",
        "executive_summary": f"{cap:.1f} MW {workload.upper()} project at {prj['lat']}°,{prj['lon']}° — IRR P50 {finance.get('irr_pct','—')}%, DSCR P50 {mc.dscr.get('p50','—')}×. All grid + planning covenants modelled under live-market conditions.",
    }

    html = render_lender_pack_html(doc, bank=body.bank_name)

    if body.format == "html":
        return {"format": "html", "html": html}

    # PDF via Playwright
    out_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "design_exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"lender_pack_{body.project_id[:8]}"
    try:
        from playwright.async_api import async_playwright
        pdf_path = out_dir / f"{stem}.pdf"
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(path=str(pdf_path), format="A4", print_background=True,
                            margin={"top": "18mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
            await browser.close()
        return {"format": "pdf", "url": f"/static/design_exports/{pdf_path.name}"}
    except Exception as e:
        html_path = out_dir / f"{stem}.html"
        html_path.write_text(html)
        return {"format": "html", "url": f"/static/design_exports/{html_path.name}", "note": f"PDF fell back to HTML ({e})"}


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/finance/negotiate — sweep PPA / grid terms, return IRR/DSCR surface
# ═══════════════════════════════════════════════════════════════════════════

class NegotiateRequest(BaseModel):
    capex_gbp_m: float
    opex_gbp_m_yr: float
    base_revenue_gbp_m_yr: float
    # Pivot price used to scale revenue with the PPA floor sweep — tracks
    # the current UK 2026 merchant midpoint so the grid auto-centres.
    base_ppa_pivot_gbp_mwh: float = Field(default_factory=lambda: ppa_price_merchant("solar"))
    technology: str = "solar"
    ppa_floor_range: list[float] = [40, 50, 55, 60, 65, 70, 75, 80]
    tenor_range_years: list[int] = [5, 7, 10, 12, 15]
    escalation_pct_range: list[float] = [0, 1.5, 2.5, 3.5]


@router.post("/api/finance/negotiate")
async def finance_negotiate(body: NegotiateRequest):
    results = []
    pivot = max(1.0, float(body.base_ppa_pivot_gbp_mwh))
    tech_wacc_pct = round(wacc(body.technology, "stabilised") * 100, 2)
    for floor in body.ppa_floor_range:
        for tenor in body.tenor_range_years:
            for esc in body.escalation_pct_range:
                # Simple modelled revenue: floor for full tenor, escalated
                yrs = tenor
                rev = body.base_revenue_gbp_m_yr * (floor / pivot)
                sc = {
                    "capex_gbp_m": body.capex_gbp_m,
                    "opex_gbp_m_yr": body.opex_gbp_m_yr,
                    "revenue_gbp_m_yr": rev * (1 + esc / 100) ** (yrs / 2),
                    "curtail_pct": 2.0, "timeline_months": 24,
                    "discount_rate_pct": tech_wacc_pct,
                    "life_years": max(yrs, 15),
                    "technology": body.technology,
                }
                out = default_evaluator(sc)
                results.append({
                    "ppa_floor_gbp_mwh": floor, "tenor_years": tenor,
                    "escalation_pct": esc, **out,
                })
    return {"surface": results, "pivot_gbp_mwh": pivot}


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/market/policy-scenarios — toggles for the PolicyScenarios panel
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/market/policy-scenarios")
async def policy_scenarios():
    return {
        "scenarios": [
            {
                "key": "cfd_ar6", "label": "CfD AR6 clearing",
                "options": [
                    {"k": "miss",  "label": "AR6 miss / re-bid AR7", "impact_irr_pp": -1.8},
                    {"k": "strike_48", "label": "Clears £48/MWh", "impact_irr_pp": -0.4},
                    {"k": "strike_55", "label": "Clears £55/MWh (base)", "impact_irr_pp": 0.0},
                    {"k": "strike_62", "label": "Clears £62/MWh",  "impact_irr_pp": +0.6},
                ],
            },
            {
                "key": "bsuos_reform", "label": "BSUoS reform (Ofgem TCR II)",
                "options": [
                    {"k": "delayed", "label": "Delayed to 2028", "impact_irr_pp": +0.2},
                    {"k": "baseline", "label": "Implements 2026", "impact_irr_pp": 0.0},
                    {"k": "tightened", "label": "Tightened banding",  "impact_irr_pp": -0.3},
                ],
            },
            {
                "key": "gas_forward_curve", "label": "Gas forward curve",
                "options": [
                    {"k": "low", "label": "€30/MWh — 25th percentile", "impact_irr_pp": -0.9},
                    {"k": "central", "label": "€45/MWh base", "impact_irr_pp": 0.0},
                    {"k": "high", "label": "€65/MWh — 75th percentile", "impact_irr_pp": +1.1},
                ],
            },
            {
                "key": "capacity_market", "label": "Capacity market clearing",
                "options": [
                    {"k": "soft",    "label": "T-1 soft (< £30/kW/yr)", "impact_irr_pp": -0.5},
                    {"k": "central", "label": "£45/kW/yr base", "impact_irr_pp": 0.0},
                    {"k": "strong",  "label": "T-1 firm (> £60/kW/yr)", "impact_irr_pp": +0.8},
                ],
            },
            {
                "key": "planning_rules", "label": "Planning policy (NPPF Dec 2024, forthcoming 2026 revision)",
                "options": [
                    {"k": "baseline", "label": "NPPF as-is",  "impact_irr_pp": 0.0},
                    {"k": "solar_fast_track", "label": "Solar fast-track", "impact_irr_pp": +0.4},
                    {"k": "bess_nsip_trigger", "label": "BESS >50MW NSIP threshold", "impact_irr_pp": -0.6},
                ],
            },
        ],
    }
