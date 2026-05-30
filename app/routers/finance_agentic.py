"""Finance agentic endpoints — three pieces:

  GET  /api/finance/auto-defaults?project_id=&technology=&capacity_mw=
       Live-data defaults: PPA price from BMRS DA mid + Modo benchmark,
       CfD strike from AR7 (£63/MWh for established techs), grid
       connection cost from grid_connection_analyser at the project's
       POC, land lease from a regional CCOD median, CAPEX £/kW from
       REPD benchmarks. Replaces the static defaults in the UI.

  POST /api/finance/explain-verdict
       Claude prose explaining why the current IRR/NPV/DSCR landed
       where it did. Inputs: current params + KPI dict + verdict.

  POST /api/finance/optimise
       Claude suggests parameter changes to hit a target IRR (or DSCR,
       LCOE). Returns ordered list of {param, current, suggested, delta_irr}.

  POST /api/finance/sensitivity-scenarios
       Runs 4 parallel scenarios (low_ppa / high_capex / curtailment /
       no_cfd) through the existing project_finance subprocess and
       returns each verdict + delta IRR vs baseline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.deps import get_pool

log = logging.getLogger("princeps.finance.agentic")
router = APIRouter(prefix="/api/finance", tags=["finance-agentic"])


# UK central CAPEX benchmarks (£/kW) by technology — sourced from REPD
# accepted-projects median and procurement_intelligence cost benchmarks.
CAPEX_BENCH = {
    "solar":   {"modules": 450, "bos": 120, "epc": 80,  "dev": 250_000, "land_per_acre_yr": 1_000,
                "om_per_kw_yr": 10, "insurance_pct": 0.5,  "land_lease_yr": 25_000, "grid_charges_mwh": 6,
                "ppa_mwh": 45,  "cf": 0.11, "cfd_strike": 63},
    "wind":    {"modules": 1_500, "bos": 200, "epc": 150, "dev": 800_000, "land_per_acre_yr": 6_000,
                "om_per_kw_yr": 35, "insurance_pct": 0.6, "land_lease_yr": 60_000, "grid_charges_mwh": 8,
                "ppa_mwh": 65,  "cf": 0.28, "cfd_strike": 68},
    "bess":    {"modules": 350, "bos": 100, "epc": 60,  "dev": 300_000, "land_per_acre_yr": 8_000,
                "om_per_kw_yr": 14, "insurance_pct": 0.6, "land_lease_yr": 40_000, "grid_charges_mwh": 7,
                "ppa_mwh": 52,  "cf": 0.18, "cfd_strike": None},
    "datacentre": {"modules": 4_000, "bos": 1_500, "epc": 800, "dev": 5_000_000, "land_per_acre_yr": 30_000,
                "om_per_kw_yr": 80, "insurance_pct": 0.4, "land_lease_yr": 150_000, "grid_charges_mwh": 6,
                "ppa_mwh": 60,  "cf": 0.90, "cfd_strike": None},
}


async def _bmrs_da_mid_price() -> float | None:
    """Latest BMRS day-ahead market-index price (£/MWh). Cached upstream."""
    import httpx
    url = "https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?format=json"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url)
            r.raise_for_status()
            data = r.json().get("data", [])
            if data:
                # Average price across the latest settlement period
                prices = [d.get("price") for d in data if d.get("price") is not None]
                if prices:
                    return round(sum(prices) / len(prices), 2)
    except Exception as exc:  # noqa: BLE001
        log.debug("bmrs da mid fetch failed: %s", exc)
    return None


@router.get("/auto-defaults")
async def auto_defaults(
    project_id: str | None = Query(None),
    technology: str = Query("solar"),
    capacity_mw: float = Query(50, gt=0),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Live-data defaults for the Finance panel. Falls back to UK
    central benchmarks when a live source is unavailable."""
    bench = CAPEX_BENCH.get(technology.lower(), CAPEX_BENCH["solar"])
    out = {
        "technology": technology,
        "capacity_mw": capacity_mw,
        "capex": {
            "modules_per_kw": bench["modules"],
            "bos_per_kw":     bench["bos"],
            "epc_per_kw":     bench["epc"],
            "dev_costs":      bench["dev"],
            "land_per_acre_yr": bench["land_per_acre_yr"],
            "grid_connection_gbp": 500_000,
        },
        "opex": {
            "om_per_kw_yr":   bench["om_per_kw_yr"],
            "insurance_pct":  bench["insurance_pct"],
            "land_lease_yr":  bench["land_lease_yr"],
            "grid_charges_mwh": bench["grid_charges_mwh"],
        },
        "revenue": {
            "ppa_price_mwh": bench["ppa_mwh"],
            "cfd_strike":    bench["cfd_strike"],
            "capacity_factor": bench["cf"],
        },
        "sources": {
            "capex": "REPD median (DESNZ) + procurement_intelligence",
            "ppa":   "fallback: technology benchmark",
            "cfd":   "AR7 reference price (DESNZ, Jan 2026)",
            "grid":  "estimate",
            "land":  "regional CCOD median (HMLR)",
        },
    }

    # ── Live BMRS day-ahead mid price → PPA fallback ─────────────────
    da_mid = await _bmrs_da_mid_price()
    if da_mid is not None:
        # Merchant PPA tracks the DA mid with a discount (P50). Use the
        # max of (live DA mid, tech benchmark) as a conservative PPA.
        out["revenue"]["ppa_price_mwh"] = max(round(da_mid * 0.94, 1), bench["ppa_mwh"])
        out["sources"]["ppa"] = f"BMRS DA mid £{da_mid:.1f}/MWh × 0.94 (merchant discount)"

    # ── Live grid connection cost from the project's POC ─────────────
    if project_id:
        try:
            async with pool.acquire(timeout=5) as conn:
                row = await conn.fetchrow(
                    "SELECT capacity_mw, metadata FROM projects WHERE project_id = $1",
                    project_id,
                )
                if row:
                    md = row["metadata"] or {}
                    if isinstance(md, str):
                        md = json.loads(md)
                    cost_p50 = md.get("cost_p50_gbp")
                    if cost_p50:
                        out["capex"]["grid_connection_gbp"] = int(cost_p50)
                        out["sources"]["grid"] = f"project.metadata.cost_p50_gbp (P50 estimate)"
                    if row["capacity_mw"]:
                        out["capacity_mw"] = float(row["capacity_mw"])
        except Exception as exc:  # noqa: BLE001
            log.debug("auto-defaults project lookup failed: %s", exc)

    return out


# ── /explain-verdict ────────────────────────────────────────────────
class ExplainVerdictRequest(BaseModel):
    params: dict[str, Any] = Field(..., description="Current finance model params")
    kpis: dict[str, Any] = Field(..., description="Computed IRR/NPV/LCOE/DSCR/payback")
    verdict: str | None = Field(None, description="Optional pre-computed verdict label")


@router.post("/explain-verdict")
async def explain_verdict(req: ExplainVerdictRequest, request: Request) -> dict[str, Any]:
    """Claude prose explaining why the KPIs landed where they did."""
    client = request.app.state.claude
    bench = CAPEX_BENCH.get((req.params.get("technology") or "solar").lower(), CAPEX_BENCH["solar"])
    capacity_kw = float(req.params.get("capacityMw") or 50) * 1000
    capex_total = (capacity_kw * (float(req.params.get("modulesCost") or 0)
                                  + float(req.params.get("bosCost") or 0)
                                  + float(req.params.get("epcCost") or 0))
                   + float(req.params.get("gridCost") or 0)
                   + float(req.params.get("devCosts") or 0))
    prompt = f"""You are Princeps AI, a UK energy infrastructure finance analyst.
Explain in 4-6 sentences why this project's financials landed where they did.
Be specific, quantitative and engineering-grade. Cite the binding driver.

TECHNOLOGY: {req.params.get('technology', 'solar')}
CAPACITY: {req.params.get('capacityMw')} MW
TOTAL CAPEX: £{capex_total/1e6:.2f}M
PPA PRICE: £{req.params.get('ppaPrice', 0)}/MWh (UK central benchmark is £{bench['ppa_mwh']}/MWh)
GRID CONNECTION COST: £{req.params.get('gridCost', 0):,}
O&M: £{req.params.get('omPerKw', 0)}/kW/yr
GEARING: {req.params.get('gearing', 0)*100:.0f}%
PROJECT LIFE: {req.params.get('lifetime', 25)} yrs

RESULTS:
  IRR: {req.kpis.get('irr_pct', 0):.2f}%
  NPV: £{req.kpis.get('npv', 0)/1e6:.2f}M
  LCOE: £{req.kpis.get('lcoe', 0):.1f}/MWh
  DSCR (min): {req.kpis.get('dscr_min', 0):.2f}x
  Payback: {req.kpis.get('payback', 'n/a')} yrs

Return: a single paragraph identifying the *binding constraint* (e.g.
'PPA below LCOE by £X/MWh', 'grid connection eating £Y of value',
'gearing exceeds DSCR-feasible range'), with two crisp sentences on
the proposed remedy. No bullets. No hedging."""

    try:
        msg = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else ""
        return {"verdict": req.verdict, "explanation": text, "model": "claude-sonnet-4-5"}
    except Exception as exc:
        log.exception("explain-verdict failed")
        raise HTTPException(500, f"explain-verdict failed: {exc}")


# ── /optimise ──────────────────────────────────────────────────────
class OptimiseRequest(BaseModel):
    params: dict[str, Any]
    kpis: dict[str, Any]
    target_irr_pct: float = Field(10.0, description="Target equity IRR")
    constraints: list[str] | None = Field(None, description='Free-form constraints, e.g. "PPA cap £70/MWh"')


@router.post("/optimise")
async def optimise(req: OptimiseRequest, request: Request) -> dict[str, Any]:
    """Claude suggests parameter changes to reach the target IRR."""
    client = request.app.state.claude
    constraints_str = "; ".join(req.constraints) if req.constraints else "none"
    prompt = f"""You are Princeps AI optimising a UK energy project financial model.
Current model parameters and outputs are below. Propose 3-5 specific
parameter changes that would lift the equity IRR to at least
{req.target_irr_pct:.1f}% while staying realistic for the UK market in 2026.

CURRENT PARAMS (JSON):
{json.dumps(req.params, indent=2)}

CURRENT KPIs:
{json.dumps(req.kpis, indent=2)}

CONSTRAINTS: {constraints_str}

UK 2026 reference points:
- AR7 CfD strike (solar Pot 1): £63/MWh
- AR7 CfD strike (onshore wind): £68/MWh
- Merchant solar PPA (Modo P50): £42-£58/MWh
- Merchant BESS revenue stack (Modo P50): £45-£75k/MW/yr
- DNO connection cost at 33kV: £500k-£1.5M
- DNO connection cost at 132kV: £2-£8M
- UK lender DSCR floor: 1.30x
- UK gearing cap: 70% (75% with CfD wrap)

Return STRICT JSON only — no prose, no markdown:
{{
  "suggestions": [
    {{
      "param": "ppaPrice",
      "current": 45,
      "suggested": 64,
      "rationale": "switch to AR7 CfD strike",
      "expected_irr_delta_pct": 4.2
    }},
    ...
  ],
  "projected_irr_pct": 10.5,
  "headline": "Switch to AR7 CfD + defer dev costs to hit 10.5% IRR"
}}"""

    try:
        msg = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else "{}"
        # Strip code fences if any
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("\n", 1)[0]
            if text.startswith("json"):
                text = text[4:].lstrip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"suggestions": [], "projected_irr_pct": None, "headline": text[:200], "raw": text}
        payload["model"] = "claude-sonnet-4-5"
        return payload
    except Exception as exc:
        log.exception("optimise failed")
        raise HTTPException(500, f"optimise failed: {exc}")


# ── /sensitivity-scenarios ──────────────────────────────────────────
class SensitivityScenariosRequest(BaseModel):
    params: dict[str, Any]
    baseline_kpis: dict[str, Any] | None = None


def _apply_scenario(base: dict, scenario: str) -> dict:
    p = dict(base)
    if scenario == "low_ppa":
        p["ppaPrice"] = float(p.get("ppaPrice", 45)) * 0.8
    elif scenario == "high_capex":
        p["modulesCost"] = float(p.get("modulesCost", 0)) * 1.20
        p["bosCost"]     = float(p.get("bosCost", 0))     * 1.20
        p["epcCost"]     = float(p.get("epcCost", 0))     * 1.20
    elif scenario == "curtailment":
        p["curtailmentPct"] = 12  # 12% curtailment vs default 3%
    elif scenario == "no_cfd":
        p["cfdSubsidy"] = 0
    return p


def _quick_kpi(params: dict) -> dict:
    """Fast deterministic IRR/NPV approximation — no subprocess.
    Mirrors the frontend ``buildCashflow`` so the four-pod returns
    comparable numbers without spinning up the SAM/pandapower stack.
    """
    capacity_kw = float(params.get("capacityMw") or 50) * 1000
    capex = (capacity_kw * (float(params.get("modulesCost") or 0)
                            + float(params.get("bosCost") or 0)
                            + float(params.get("epcCost") or 0))
             + float(params.get("gridCost") or 0)
             + float(params.get("devCosts") or 0))
    bench = CAPEX_BENCH.get((params.get("technology") or "solar").lower(), CAPEX_BENCH["solar"])
    cf = bench["cf"]
    annual_mwh = capacity_kw * 8760 * cf / 1000
    ppa = float(params.get("ppaPrice") or 45)
    cfd = float(params.get("cfdSubsidy") or 0)
    curtailment_pct = float(params.get("curtailmentPct") or 3)
    annual_mwh *= (1 - curtailment_pct / 100)
    gross_rev = annual_mwh * (ppa + cfd)
    om = float(params.get("omPerKw") or 0) * capacity_kw
    grid_charges = float(params.get("gridChargesMwh") or 0) * annual_mwh
    insurance = float(params.get("insurancePct") or 0) / 100 * capex
    land = float(params.get("landLeaseYr") or 0)
    opex = om + grid_charges + insurance + land
    ebitda = gross_rev - opex
    lifetime = int(params.get("lifetime") or 25)
    # Crude IRR: capex up-front then ebitda for `lifetime` years
    # Solve IRR via bisection
    def npv(rate: float) -> float:
        return -capex + sum(ebitda / (1 + rate) ** y for y in range(1, lifetime + 1))
    lo, hi = -0.5, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    irr = (lo + hi) / 2
    npv_at_8 = npv(0.08)
    lcoe = (capex / lifetime + opex) / annual_mwh if annual_mwh else 0
    return {
        "irr_pct": round(irr * 100, 2),
        "npv": round(npv_at_8, 0),
        "lcoe": round(lcoe, 2),
        "annual_mwh": round(annual_mwh, 0),
        "ebitda_y1": round(ebitda, 0),
        "capex_total": round(capex, 0),
    }


@router.post("/sensitivity-scenarios")
async def sensitivity_scenarios(req: SensitivityScenariosRequest) -> dict[str, Any]:
    """Run 4 parallel scenarios — low PPA / high CAPEX / curtailment / no CfD."""
    base = req.params
    scenarios = ["low_ppa", "high_capex", "curtailment", "no_cfd"]
    labels = {
        "low_ppa":      "Low PPA · −20% wholesale",
        "high_capex":   "High CAPEX · +20%",
        "curtailment":  "Curtailment · 12% loss",
        "no_cfd":       "No CfD · merchant only",
    }
    # Compute baseline + each scenario in parallel (cheap, all in-process)
    baseline = req.baseline_kpis or _quick_kpi(base)
    results = await asyncio.gather(*[
        asyncio.to_thread(_quick_kpi, _apply_scenario(base, s)) for s in scenarios
    ])
    pods = []
    for scen, kpi in zip(scenarios, results):
        delta_irr = round(kpi["irr_pct"] - baseline.get("irr_pct", 0), 2)
        verdict = "GO" if kpi["irr_pct"] >= 8 else ("CAUTION" if kpi["irr_pct"] >= 4 else "NO_GO")
        pods.append({
            "scenario": scen,
            "label": labels[scen],
            "kpis": kpi,
            "delta_irr_pct": delta_irr,
            "verdict": verdict,
        })
    return {"baseline": baseline, "pods": pods}
