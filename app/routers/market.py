"""Route-to-market + dispatch optimisation endpoints (Phase 9 & 10)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query

from app.helpers import _run_generic_subprocess

router = APIRouter(tags=["market"])

# ── Script paths ──────────────────────────────────────────────────────────────
_UTILS_DIR = str(Path(__file__).resolve().parent.parent.parent / "utils")
_PPA_SCRIPT = str(Path(_UTILS_DIR) / "ppa_modeller.py")
_OFFTAKE_SCRIPT = str(Path(_UTILS_DIR) / "offtake_matcher.py")
_RTM_SCRIPT = str(Path(_UTILS_DIR) / "route_to_market.py")
_RISK_SCRIPT = str(Path(_UTILS_DIR) / "project_risk_model.py")
_CONSTRAINT_FORECASTER = str(Path(_UTILS_DIR) / "constraint_forecaster.py")
_DISPATCH_SCHEDULER = str(Path(_UTILS_DIR) / "dispatch_scheduler.py")
_BALANCING_MECHANISM = str(Path(_UTILS_DIR) / "balancing_mechanism.py")
_REVENUE_TRACKER = str(Path(_UTILS_DIR) / "revenue_tracker.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTE-TO-MARKET — PPA, Offtake, Routes, Risk (Phase 10)
# ═══════════════════════════════════════════════════════════════════════════════

# ── PPA Modeller ──

@router.get("/api/rtm/ppa/price")
async def api_ppa_price(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    structure: str = Query("fixed"),
    term_years: int = Query(15),
    credit_tier: str = Query("investment_grade"),
):
    return await _run_generic_subprocess(_PPA_SCRIPT, {
        "command": "ppa_price", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "structure": structure, "term_years": term_years,
        "credit_tier": credit_tier,
    })


@router.get("/api/rtm/ppa/term-analysis")
async def api_ppa_term_analysis(
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    region: str = Query("Midlands"),
    structure: str = Query("fixed"),
):
    return await _run_generic_subprocess(_PPA_SCRIPT, {
        "command": "term_analysis", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "structure": structure,
    })


@router.get("/api/rtm/ppa/structures")
async def api_ppa_structures(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    term_years: int = Query(15),
):
    return await _run_generic_subprocess(_PPA_SCRIPT, {
        "command": "structure_comparison", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "term_years": term_years,
    })


# ── Offtake Matcher ──

@router.get("/api/rtm/offtake/match")
async def api_offtake_match(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_generic_subprocess(_OFFTAKE_SCRIPT, {
        "command": "match_buyers", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/rtm/offtake/buyer")
async def api_offtake_buyer(buyer_type: str = Query("data_centre")):
    return await _run_generic_subprocess(_OFFTAKE_SCRIPT, {
        "command": "buyer_profile", "buyer_type": buyer_type,
    })


@router.get("/api/rtm/offtake/correlation")
async def api_offtake_correlation(
    technology: str = Query("wind"),
    buyer_type: str = Query("industrial"),
):
    return await _run_generic_subprocess(_OFFTAKE_SCRIPT, {
        "command": "demand_correlation", "technology": technology,
        "buyer_type": buyer_type,
    })


# ── Route-to-Market ──

@router.get("/api/rtm/routes/compare")
async def api_rtm_compare(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_generic_subprocess(_RTM_SCRIPT, {
        "command": "compare_routes", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/rtm/routes/detail")
async def api_rtm_detail(
    route: str = Query("cfd"),
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
):
    return await _run_generic_subprocess(_RTM_SCRIPT, {
        "command": "route_detail", "route": route,
        "capacity_mw": capacity_mw, "technology": technology,
    })


@router.get("/api/rtm/routes/bankability")
async def api_rtm_bankability(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    route: str = Query("corporate_ppa"),
):
    return await _run_generic_subprocess(_RTM_SCRIPT, {
        "command": "bankability_score", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "route": route,
    })


# ── Project Risk ──

@router.get("/api/rtm/risk/assessment")
async def api_risk_assessment(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    route: str = Query("cfd"),
):
    return await _run_generic_subprocess(_RISK_SCRIPT, {
        "command": "risk_assessment", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "route": route,
    })


@router.get("/api/rtm/risk/sensitivity")
async def api_risk_sensitivity(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    route: str = Query("cfd"),
):
    return await _run_generic_subprocess(_RISK_SCRIPT, {
        "command": "sensitivity_analysis", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "route": route,
    })


@router.get("/api/rtm/risk/bankability")
async def api_risk_bankability(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    route: str = Query("corporate_ppa"),
):
    return await _run_generic_subprocess(_RISK_SCRIPT, {
        "command": "bankability_report", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "route": route,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPATCH OPTIMISATION — Constraints, Dispatch, BM, Revenue (Phase 9)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Constraint Forecaster ──

@router.get("/api/dispatch/constraints/forecast")
async def api_constraint_forecast(
    hours_ahead: int = Query(48),
    date: str = Query(None),
):
    return await _run_generic_subprocess(_CONSTRAINT_FORECASTER, {
        "command": "forecast", "hours_ahead": hours_ahead, "date": date,
    })


@router.get("/api/dispatch/constraints/boundary")
async def api_constraint_boundary(
    boundary_id: str = Query("B1"),
    hours_ahead: int = Query(48),
    date: str = Query(None),
):
    return await _run_generic_subprocess(_CONSTRAINT_FORECASTER, {
        "command": "boundary_forecast", "boundary_id": boundary_id,
        "hours_ahead": hours_ahead, "date": date,
    })


@router.get("/api/dispatch/constraints/windows")
async def api_constraint_windows(
    hours_ahead: int = Query(48),
    threshold: float = Query(0.5),
    date: str = Query(None),
):
    return await _run_generic_subprocess(_CONSTRAINT_FORECASTER, {
        "command": "constraint_windows", "hours_ahead": hours_ahead,
        "threshold": threshold, "date": date,
    })


# ── Dispatch Scheduler ──

@router.get("/api/dispatch/schedule")
async def api_dispatch_schedule(
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    region: str = Query("Midlands"),
    connection_type: str = Query("anm"),
    headroom_mw: float = Query(30),
    hours_ahead: int = Query(24),
    month: int = Query(1),
):
    return await _run_generic_subprocess(_DISPATCH_SCHEDULER, {
        "command": "schedule", "capacity_mw": capacity_mw, "technology": technology,
        "region": region, "connection_type": connection_type,
        "headroom_mw": headroom_mw, "hours_ahead": hours_ahead, "month": month,
    })


@router.post("/api/dispatch/bess-schedule")
async def api_bess_schedule(body: dict):
    return await _run_generic_subprocess(_DISPATCH_SCHEDULER, {
        "command": "bess_schedule",
        "power_mw": body.get("power_mw", 25),
        "energy_mwh": body.get("energy_mwh", 50),
        "soc_pct": body.get("soc_pct", 50),
        "region": body.get("region", "Midlands"),
        "hours_ahead": body.get("hours_ahead", 24),
        "month": body.get("month", 1),
    })


@router.get("/api/dispatch/revenue-comparison")
async def api_dispatch_revenue_comparison(
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    region: str = Query("Midlands"),
):
    return await _run_generic_subprocess(_DISPATCH_SCHEDULER, {
        "command": "revenue_comparison", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


# ── Balancing Mechanism ──

@router.get("/api/dispatch/bm/revenue")
async def api_bm_revenue(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_generic_subprocess(_BALANCING_MECHANISM, {
        "command": "bm_revenue", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/dispatch/bm/boa-profile")
async def api_bm_boa_profile(
    capacity_mw: float = Query(50),
    region: str = Query("Scotland"),
    technology: str = Query("wind"),
    hours_ahead: int = Query(24),
    month: int = Query(1),
):
    return await _run_generic_subprocess(_BALANCING_MECHANISM, {
        "command": "boa_profile", "capacity_mw": capacity_mw, "region": region,
        "technology": technology, "hours_ahead": hours_ahead, "month": month,
    })


@router.get("/api/dispatch/bm/system-prices")
async def api_bm_system_prices(date: str = Query("2025-01-15")):
    return await _run_generic_subprocess(_BALANCING_MECHANISM, {
        "command": "system_prices", "date": date,
    })


# ── Revenue Tracker ──

@router.get("/api/dispatch/revenue/stack")
async def api_revenue_stack(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    connection_type: str = Query("anm"),
    headroom_mw: float = Query(30),
    cfd_enabled: bool = Query(True),
):
    return await _run_generic_subprocess(_REVENUE_TRACKER, {
        "command": "revenue_stack", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "connection_type": connection_type, "headroom_mw": headroom_mw,
        "cfd_enabled": cfd_enabled,
    })


@router.get("/api/dispatch/revenue/monthly")
async def api_revenue_monthly(
    capacity_mw: float = Query(50),
    technology: str = Query("solar"),
    region: str = Query("Midlands"),
    connection_type: str = Query("anm"),
    headroom_mw: float = Query(30),
):
    return await _run_generic_subprocess(_REVENUE_TRACKER, {
        "command": "monthly_breakdown", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "connection_type": connection_type, "headroom_mw": headroom_mw,
    })


@router.get("/api/dispatch/revenue/scenarios")
async def api_revenue_scenarios(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_generic_subprocess(_REVENUE_TRACKER, {
        "command": "scenario_comparison", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })
