"""Sustainability router -- Carbon, ESG, Portfolio, Community, Decommissioning (Phase 11)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from app.helpers import _run_generic_subprocess

router = APIRouter(tags=["sustainability"])

# ---------------------------------------------------------------------------
# Subprocess script paths
# ---------------------------------------------------------------------------
_CARBON_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "carbon_esg_tracker.py")
_PORTFOLIO_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "portfolio_analytics.py")
_COMMUNITY_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "community_benefit.py")
_DECOM_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "decommissioning_planner.py")


# ── Carbon & ESG ──────────────────────────────────────────────────────────

@router.get("/api/sustainability/carbon/footprint")
async def api_carbon_footprint(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    project_life_years: int = Query(25),
):
    return await _run_generic_subprocess(_CARBON_SCRIPT, {
        "command": "carbon_footprint", "capacity_mw": capacity_mw,
        "technology": technology, "project_life_years": project_life_years,
    })


@router.get("/api/sustainability/carbon/displacement")
async def api_grid_displacement(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    project_life_years: int = Query(25),
):
    return await _run_generic_subprocess(_CARBON_SCRIPT, {
        "command": "grid_displacement", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "project_life_years": project_life_years,
    })


@router.get("/api/sustainability/esg/score")
async def api_esg_score(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    community_fund: bool = Query(True),
    shared_ownership: bool = Query(False),
    biodiversity_net_gain: bool = Query(True),
):
    return await _run_generic_subprocess(_CARBON_SCRIPT, {
        "command": "esg_score", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "community_fund": community_fund,
        "shared_ownership": shared_ownership,
        "biodiversity_net_gain": biodiversity_net_gain,
    })


# ── Portfolio ─────────────────────────────────────────────────────────────

@router.post("/api/sustainability/portfolio/summary")
async def api_portfolio_summary(req: dict):
    return await _run_generic_subprocess(_PORTFOLIO_SCRIPT, {
        "command": "portfolio_summary", "sites": req.get("sites", []),
    })


@router.post("/api/sustainability/portfolio/diversification")
async def api_portfolio_diversification(req: dict):
    return await _run_generic_subprocess(_PORTFOLIO_SCRIPT, {
        "command": "diversification_analysis", "sites": req.get("sites", []),
    })


@router.get("/api/sustainability/portfolio/optimisation")
async def api_portfolio_optimisation(
    budget_mw: float = Query(200),
    target: str = Query("max_revenue"),
):
    return await _run_generic_subprocess(_PORTFOLIO_SCRIPT, {
        "command": "portfolio_optimisation", "budget_mw": budget_mw,
        "target": target,
    })


# ── Community ─────────────────────────────────────────────────────────────

@router.get("/api/sustainability/community/package")
async def api_community_package(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    community_fund: bool = Query(True),
    shared_ownership_pct: float = Query(0),
):
    return await _run_generic_subprocess(_COMMUNITY_SCRIPT, {
        "command": "benefit_package", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "community_fund": community_fund,
        "shared_ownership_pct": shared_ownership_pct,
    })


@router.get("/api/sustainability/community/shared-ownership")
async def api_shared_ownership(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    community_stake_pct: float = Query(25),
):
    return await _run_generic_subprocess(_COMMUNITY_SCRIPT, {
        "command": "shared_ownership", "capacity_mw": capacity_mw,
        "technology": technology,
        "community_stake_pct": community_stake_pct,
    })


@router.get("/api/sustainability/community/social-value")
async def api_social_value(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    community_fund: bool = Query(True),
    apprenticeships: int = Query(3),
):
    return await _run_generic_subprocess(_COMMUNITY_SCRIPT, {
        "command": "social_value", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "community_fund": community_fund,
        "apprenticeships": apprenticeships,
    })


# ── Decommissioning ──────────────────────────────────────────────────────

@router.get("/api/sustainability/decom/estimate")
async def api_decom_estimate(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    age_years: int = Query(25),
):
    return await _run_generic_subprocess(_DECOM_SCRIPT, {
        "command": "decommission_estimate", "capacity_mw": capacity_mw,
        "technology": technology, "age_years": age_years,
    })


@router.get("/api/sustainability/decom/repowering")
async def api_repowering(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_generic_subprocess(_DECOM_SCRIPT, {
        "command": "repowering_comparison", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/sustainability/decom/material-recovery")
async def api_material_recovery(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
):
    return await _run_generic_subprocess(_DECOM_SCRIPT, {
        "command": "material_recovery", "capacity_mw": capacity_mw,
        "technology": technology,
    })
