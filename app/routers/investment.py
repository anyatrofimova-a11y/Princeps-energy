"""Investment readiness and due diligence router (Phase 12)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Query

# ── Subprocess scripts ──
_APPRAISAL_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "investment_appraisal.py")
_SCENARIO_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "scenario_engine.py")
_DD_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "due_diligence.py")
_REPORT_SCRIPT = str(Path(__file__).resolve().parent.parent.parent / "utils" / "report_generator.py")


async def _run_phase12_subprocess(script: str, payload: dict) -> dict:
    """Run a Phase 12 utility subprocess."""
    import asyncio as _aio
    proc = await _aio.create_subprocess_exec(
        sys.executable, script,
        stdin=_aio.subprocess.PIPE, stdout=_aio.subprocess.PIPE,
        stderr=_aio.subprocess.PIPE,
    )
    raw_in = json.dumps(payload).encode()
    stdout, stderr = await _aio.wait_for(proc.communicate(raw_in), timeout=120)
    return json.loads(stdout)


router = APIRouter(tags=["investment"])


# ── Finance ──

@router.get("/api/investment/finance/project")
async def api_investment_project_finance(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    ppa_price: float = Query(55),
):
    return await _run_phase12_subprocess(_APPRAISAL_SCRIPT, {
        "command": "project_finance", "capacity_mw": capacity_mw,
        "technology": technology, "region": region, "ppa_price": ppa_price,
    })


@router.get("/api/investment/finance/debt")
async def api_investment_debt_structure(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    target_dscr: float = Query(1.3),
    gearing: float = Query(0.7),
    ppa_price: float = Query(55),
):
    return await _run_phase12_subprocess(_APPRAISAL_SCRIPT, {
        "command": "debt_structure", "capacity_mw": capacity_mw,
        "technology": technology, "target_dscr": target_dscr,
        "gearing": gearing, "ppa_price": ppa_price,
    })


@router.get("/api/investment/finance/equity")
async def api_investment_equity_returns(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    gearing: float = Query(0.7),
    ppa_price: float = Query(55),
    tax_rate: float = Query(0.25),
):
    return await _run_phase12_subprocess(_APPRAISAL_SCRIPT, {
        "command": "equity_returns", "capacity_mw": capacity_mw,
        "technology": technology, "gearing": gearing,
        "ppa_price": ppa_price, "tax_rate": tax_rate,
    })


# ── Scenarios ──

@router.get("/api/investment/scenario/stress-test")
async def api_investment_stress_test(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    gearing: float = Query(0.7),
):
    return await _run_phase12_subprocess(_SCENARIO_SCRIPT, {
        "command": "stress_test", "capacity_mw": capacity_mw,
        "technology": technology, "gearing": gearing,
    })


@router.get("/api/investment/scenario/montecarlo")
async def api_investment_montecarlo(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    n_sims: int = Query(2000),
    gearing: float = Query(0.7),
):
    return await _run_phase12_subprocess(_SCENARIO_SCRIPT, {
        "command": "correlated_montecarlo", "capacity_mw": capacity_mw,
        "technology": technology, "n_sims": n_sims, "gearing": gearing,
    })


@router.get("/api/investment/scenario/break-even")
async def api_investment_break_even(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    gearing: float = Query(0.7),
):
    return await _run_phase12_subprocess(_SCENARIO_SCRIPT, {
        "command": "break_even", "capacity_mw": capacity_mw,
        "technology": technology, "gearing": gearing,
    })


# ── Due Diligence ──

@router.get("/api/investment/dd/checklist")
async def api_investment_dd_checklist(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_phase12_subprocess(_DD_SCRIPT, {
        "command": "dd_checklist", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/investment/dd/technical")
async def api_investment_dd_technical(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
):
    return await _run_phase12_subprocess(_DD_SCRIPT, {
        "command": "technical_dd", "capacity_mw": capacity_mw,
        "technology": technology,
    })


@router.get("/api/investment/dd/commercial")
async def api_investment_dd_commercial(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    ppa_price: float = Query(55),
):
    return await _run_phase12_subprocess(_DD_SCRIPT, {
        "command": "commercial_dd", "capacity_mw": capacity_mw,
        "technology": technology, "ppa_price": ppa_price,
    })


# ── Report ──

@router.get("/api/investment/report/memo")
async def api_investment_memo(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
    ppa_price: float = Query(55),
    gearing: float = Query(0.7),
):
    return await _run_phase12_subprocess(_REPORT_SCRIPT, {
        "command": "investment_memo", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
        "ppa_price": ppa_price, "gearing": gearing,
    })


@router.get("/api/investment/report/risk-matrix")
async def api_investment_risk_matrix(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_phase12_subprocess(_REPORT_SCRIPT, {
        "command": "risk_matrix", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })


@router.get("/api/investment/report/action-plan")
async def api_investment_action_plan(
    capacity_mw: float = Query(50),
    technology: str = Query("wind"),
    region: str = Query("Scotland"),
):
    return await _run_phase12_subprocess(_REPORT_SCRIPT, {
        "command": "action_plan", "capacity_mw": capacity_mw,
        "technology": technology, "region": region,
    })
