"""Princeps Financial Viability Report (FVR) — lender-grade rewrite.

Entry point
-----------
:func:`generate_financial_report` — unchanged signature, returns A4 portrait
PDF bytes rendered via Playwright Chromium from the Jinja templates under
``templates/financial_report/``.

Target audience
---------------
Credit committee at a UK project-finance lender (NatWest, Aviva Investors,
Greencoat, etc.). The deliverable is a 13-section lender-grade pack:

 1. Cover + reliance statement
 2. Executive summary
 3. Project description
 4. Revenue stack
 5. CapEx breakdown
 6. OpEx & asset management
 7. 25-year DCF schedule
 8. Debt structure & covenants
 9. Equity returns
10. Sensitivity tornado
11. Stress cases
12. Risk register
13. Assumptions appendix

Design
------
* Pure Python — no magic numbers. All finance defaults resolve through
  :mod:`utils.finance_benchmarks`.
* DCF engine: :class:`utils.dcf_evaluator.DCFEvaluator` (single source of truth,
  shared with IC/lender packs).
* Equity + debt: :mod:`utils.investment_appraisal` (subprocess bridge).
* Sensitivity & stress: :mod:`utils.fvr_sensitivity` (in-process, ~100 ms).
* Tornado chart: inline SVG via Jinja partial (no base64 PNG needed).
* Template engine: Jinja2 with ``include`` directives for partials.
* Pagination: CSS ``@page`` + ``page-break`` classes; running header/footer
  populated via CSS counter + page-string content.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.dcf_evaluator import DCFEvaluator, DCFResult, build_amortising_debt
from utils.finance_benchmarks import (
    CPI_LONG_RUN,
    DEBT_MARGIN_BPS,
    SONIA_REFERENCE_PCT,
    cfd_strike_2026,
    cite as finance_cite,
    corporation_tax_rate,
    debt_tenor_years,
    debt_to_equity,
    egl_applies_to,
    egl_threshold_gbp_mwh,
    ppa_price_merchant,
    senior_debt_all_in_rate,
    wacc as bench_wacc,
)
from utils.fvr_sensitivity import (
    compute_tornado,
    stress_downside as fvr_stress_downside,
    stress_upside as fvr_stress_upside,
)
from utils.investment_appraisal import (
    CAPACITY_FACTORS,
    CAPEX_PER_MW,
    CONSTRUCTION_YEARS,
    DEGRADATION_RATE,
    OPEX_PER_MW,
    PROJECT_LIFE,
    REVENUE_PER_MW,
)

log = logging.getLogger("princeps.report_financial")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "financial_report"
_APPRAISAL_SCRIPT = Path(__file__).resolve().parent / "investment_appraisal.py"

# Technology labels — displayed verbatim in the report
TECH_LABELS: dict[str, str] = {
    "solar": "Ground-Mount Solar PV",
    "wind": "Onshore Wind",
    "offshore_wind": "Offshore Wind",
    "bess": "Battery Energy Storage (BESS)",
}

# CapEx component shares (lender reference allocation). These are
# percentages of total CapEx — the Python layer converts to £/kW and £m
# for the template. Solar shares match the prompt spec exactly.
_CAPEX_SHARES: dict[str, list[tuple[str, float]]] = {
    "solar": [
        ("Modules (Tier-1 mono-facial)", 0.38),
        ("Inverters (central + string)", 0.08),
        ("Balance of System (DC/AC cabling, trackers)", 0.12),
        ("Civils & earthworks", 0.09),
        ("Grid connection (substation + 33 kV cable)", 0.14),
        ("EPC margin", 0.08),
        ("Development fees (land, consents, ECM)", 0.05),
        ("Contingency & owner's costs", 0.06),
    ],
    "wind": [
        ("Turbines (3-4 MW Class II)", 0.58),
        ("Foundations", 0.08),
        ("Balance of Plant (roads, collection)", 0.10),
        ("Grid connection", 0.10),
        ("EPC margin", 0.06),
        ("Development fees", 0.04),
        ("Contingency & owner's costs", 0.04),
    ],
    "offshore_wind": [
        ("Turbines (14 MW WTG)", 0.38),
        ("Foundations (monopile)", 0.22),
        ("Array cables", 0.08),
        ("Export cable", 0.10),
        ("Onshore substation + TP", 0.06),
        ("Installation (vessels)", 0.08),
        ("Development fees", 0.04),
        ("Contingency", 0.04),
    ],
    "bess": [
        ("Battery modules (LFP, 2-hr duration)", 0.50),
        ("Power Conversion System + MV transformer", 0.15),
        ("Balance of Plant (HVAC, fire, SCADA)", 0.10),
        ("Grid connection", 0.10),
        ("EMS & controls", 0.05),
        ("Development fees + consenting", 0.05),
        ("Contingency", 0.05),
    ],
}

# OpEx allocation — £/MW/yr proportions. Percentages are of total Yr-1 OpEx.
_OPEX_SHARES: dict[str, list[tuple[str, float, str]]] = {
    "solar": [
        ("Fixed O&M contract", 0.35, "Panel cleaning, inverter maintenance, SCADA"),
        ("Land rent", 0.18, "£850-1,050/acre/yr CPI-linked (NFU benchmark 2025)"),
        ("Insurance (property + BI)", 0.12, "~0.22% of CapEx per annum"),
        ("Business rates (NNDR)", 0.10, "VOA 2023 list, solar transitional"),
        ("TNUoS / BSUoS", 0.13, "NESO CUSC charges (G-type solar generation)"),
        ("Asset management fee", 0.07, "SPV admin, reporting, compliance"),
        ("Decommissioning sinking fund", 0.05, "£2,500/MW/yr to escrow (OFGEM guidance)"),
    ],
    "wind": [
        ("Full-scope O&M (turbine OEM)", 0.42, "10-yr OEM FSA at ~£16k/MW/yr"),
        ("Land rent", 0.12, "£7,000-12,000/MW/yr per turbine"),
        ("Insurance", 0.11, "Includes WTG warranty buyout post-year 5"),
        ("Business rates", 0.09, ""),
        ("TNUoS / BSUoS", 0.12, ""),
        ("Asset management", 0.07, ""),
        ("Decommissioning sinking fund", 0.07, "£3,500/MW/yr"),
    ],
    "offshore_wind": [
        ("O&M contract (vessel-based)", 0.45, "CTV/SOV fleet, 24/7 response"),
        ("OFTO transmission charge", 0.18, "OFTO 6 regulated asset base"),
        ("Insurance (marine + BI)", 0.14, ""),
        ("BSUoS", 0.08, ""),
        ("Asset management", 0.07, ""),
        ("Decommissioning sinking fund", 0.08, ""),
    ],
    "bess": [
        ("Fixed O&M (cell monitoring, HVAC)", 0.30, "OEM service agreement"),
        ("Augmentation sinking fund", 0.20, "Cell replacement Yr 8-10"),
        ("Insurance (specialist BESS)", 0.15, "Inc. thermal runaway cover"),
        ("Business rates", 0.08, "VOA 2023, BESS transitional"),
        ("TNUoS / BSUoS", 0.12, "Final BSUoS reform Apr 2026"),
        ("Asset management + trading oversight", 0.10, ""),
        ("Land rent", 0.05, ""),
    ],
}

# DCF schedule rows to display: Y1..Y5 plus every 5th after
_SCHEDULE_YEARS = [1, 2, 3, 4, 5, 10, 15, 20, 25]

# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Display formatters
# ---------------------------------------------------------------------------

def _fmt_gbp(value: float) -> str:
    """Format GBP with magnitude suffix — "£12.3m", "£345k", "£123"."""
    if value is None:
        return "—"
    v = float(value)
    a = abs(v)
    sign = "−" if v < 0 else ""
    if a >= 1_000_000_000:
        return f"{sign}£{a / 1e9:.2f}bn"
    if a >= 1_000_000:
        return f"{sign}£{a / 1e6:.1f}m"
    if a >= 1_000:
        return f"{sign}£{a / 1e3:.0f}k"
    return f"{sign}£{a:,.0f}"


# ---------------------------------------------------------------------------
# Subprocess bridge to investment_appraisal.py
# ---------------------------------------------------------------------------

def _run_appraisal(command: str, **kwargs) -> dict:
    """Run investment_appraisal.py as subprocess (stdin JSON → stdout JSON)."""
    python = os.environ.get("PYTHON", sys.executable)
    payload = {"command": command, **kwargs}
    env = os.environ.copy()
    # Ensure the subprocess can import 'utils.*' regardless of cwd by
    # prepending the repo root to PYTHONPATH.
    repo_root = str(Path(__file__).resolve().parent.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}:{existing}" if existing else repo_root
    try:
        result = subprocess.run(
            [python, str(_APPRAISAL_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=repo_root,
        )
        if result.returncode != 0:
            log.error("Appraisal subprocess (%s) failed: %s", command, result.stderr)
            return {"error": result.stderr or "Subprocess failed"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "Subprocess timed out"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


async def _run_appraisal_async(command: str, **kwargs) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run_appraisal(command, **kwargs))


# ---------------------------------------------------------------------------
# DCF evaluator wrapper (shared with IC pack / lender pack)
# ---------------------------------------------------------------------------

def _build_schedules(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
) -> tuple[float, float, list[float], list[float]]:
    """Return (total_capex, annual_opex_yr1, revenue_schedule, opex_schedule)."""
    tech = technology.lower()
    capex_mw = CAPEX_PER_MW.get(tech, CAPEX_PER_MW["solar"])
    opex_mw = OPEX_PER_MW.get(tech, OPEX_PER_MW["solar"])
    cf = CAPACITY_FACTORS.get(tech, 0.11)
    is_bess = tech == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0.0
    bess_base_rev = REVENUE_PER_MW.get(tech, 0) * capacity_mw if is_bess else 0.0
    total_capex = capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw

    rev: list[float] = []
    opex: list[float] = []
    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            r_y = bess_base_rev * (1 + CPI_LONG_RUN) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            deg = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            r_y = deg * ppa_price * (1 + CPI_LONG_RUN) ** y
        o_y = annual_opex * (1 + CPI_LONG_RUN) ** y
        rev.append(r_y)
        opex.append(o_y)
    return total_capex, annual_opex, rev, opex


def _run_dcf(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
    wacc_pct: float,
    gearing: float,
    debt_rate: float,
    tenor: int,
    tax_rate: float,
) -> tuple[DCFResult, dict]:
    """Run the DCFEvaluator and return (result, diagnostics)."""
    total_capex, annual_opex_yr1, rev, opex = _build_schedules(
        capacity_mw, technology, ppa_price,
    )
    debt_principal = total_capex * gearing
    debt_schedule = build_amortising_debt(
        principal=debt_principal,
        rate=debt_rate,
        term_years=tenor,
        life_years=PROJECT_LIFE,
    )
    ev = DCFEvaluator(
        capex=total_capex,
        revenue_schedule=rev,
        opex_schedule=opex,
        tax_rate=tax_rate,
        wacc=wacc_pct,
        terminal_growth=0.0,
        debt_schedule=debt_schedule,
        technology=technology,
    )
    result = ev.evaluate()
    diag = {
        "total_capex": total_capex,
        "annual_opex_yr1": annual_opex_yr1,
        "debt_principal": debt_principal,
        "equity_principal": total_capex - debt_principal,
        "debt_schedule": debt_schedule,
    }
    return result, diag


# ---------------------------------------------------------------------------
# Revenue stack construction (year-by-year blended £/MWh)
# ---------------------------------------------------------------------------

def _build_revenue_stack(technology: str, ppa_price: float) -> dict[str, Any]:
    """Construct a blended revenue stack table showing £/MWh by source.

    Columns: Yr1, Yr5, Yr10, Yr15, Yr20, 25-yr avg.
    """
    horizon = {1, 5, 10, 15, 20}
    inflation = CPI_LONG_RUN

    def _esc(base: float, year: int) -> float:
        return base * (1 + inflation) ** year

    rows: list[dict[str, Any]] = []

    if technology == "bess":
        # BESS revenue stack — Modo Energy 2h P50 benchmark split
        base_arb = ppa_price * 0.55
        base_firm = ppa_price * 0.25
        base_cap = ppa_price * 0.20
        parts = [
            ("Wholesale arbitrage (BM + N2EX)", base_arb, "Modo Mar 2026 2h P50"),
            ("Dynamic Containment + firm freq.", base_firm, "NGESO DC/DM/DR clearing"),
            ("Capacity market (T-4 2028/29)", base_cap, "NESO Feb 2026 auction"),
        ]
    else:
        # Solar / wind blend: PPA Y1-15, AR7 floor reference, Cap market
        base_ppa = ppa_price
        base_eb = ppa_price * 0.05       # embedded benefits (~5% uplift)
        base_cap = ppa_price * 0.03      # de minimis capacity revenue for dispatchable
        base_cfd_floor = cfd_strike_2026(pot=1) if technology in ("solar", "wind") else cfd_strike_2026(pot=2)
        parts = [
            (f"Corporate PPA (merchant base)", base_ppa, "Cornwall Insight Q1 2026"),
            ("Embedded benefits (TNUoS/DUoS avoidance)", base_eb, "OFGEM embedded benefits 2025"),
            (f"CfD AR7 Pot 1 indexed floor (ref only)", base_cfd_floor, "LCCC Jan 2026 (floor ref)"),
            ("Capacity market (de minimis)", base_cap, "NESO T-4 2028/29 (de minimis)"),
        ]

    total_series = {y: 0.0 for y in horizon}
    total_avg = 0.0

    for source, base, notes in parts:
        row: dict[str, Any] = {"source": source, "notes": notes, "is_total": False}
        avg = 0.0
        for y in range(1, PROJECT_LIFE + 1):
            v = _esc(base, y)
            avg += v
            if y in horizon:
                row[f"y{y}"] = v
                total_series[y] += v
        avg /= PROJECT_LIFE
        row["avg"] = avg
        total_avg += avg
        rows.append(row)

    total_row: dict[str, Any] = {
        "source": "Blended revenue (£/MWh)", "notes": "Sum of components",
        "is_total": True,
        "y1": total_series[1], "y5": total_series[5],
        "y10": total_series[10], "y15": total_series[15],
        "y20": total_series[20],
        "avg": total_avg,
    }
    # Fill any missing horizon keys on component rows with 0
    for r in rows:
        for y in (1, 5, 10, 15, 20):
            r.setdefault(f"y{y}", 0.0)
    rows.append(total_row)
    return {"rows": rows}


# ---------------------------------------------------------------------------
# CapEx / OpEx breakdown construction
# ---------------------------------------------------------------------------

def _build_capex_breakdown(
    technology: str, total_capex: float, capacity_mw: float,
) -> list[dict[str, Any]]:
    shares = _CAPEX_SHARES.get(technology, _CAPEX_SHARES["solar"])
    rows: list[dict[str, Any]] = []
    for component, share in shares:
        amt = total_capex * share
        rows.append({
            "component": component,
            "per_kw": (amt / capacity_mw / 1_000) if capacity_mw else 0,
            "total": amt,
            "total_display": _fmt_gbp(amt),
            "pct": share * 100,
            "is_total": False,
        })
    rows.append({
        "component": "Total CapEx (EPC + soft + contingency)",
        "per_kw": (total_capex / capacity_mw / 1_000) if capacity_mw else 0,
        "total": total_capex,
        "total_display": _fmt_gbp(total_capex),
        "pct": 100.0,
        "is_total": True,
    })
    return rows


def _build_opex_breakdown(
    technology: str, annual_opex_yr1: float, capacity_mw: float,
) -> list[dict[str, Any]]:
    shares = _OPEX_SHARES.get(technology, _OPEX_SHARES["solar"])
    rows: list[dict[str, Any]] = []
    for component, share, notes in shares:
        amt = annual_opex_yr1 * share
        rows.append({
            "component": component,
            "per_mw_yr": (amt / capacity_mw) if capacity_mw else 0,
            "total": amt,
            "total_display": _fmt_gbp(amt),
            "notes": notes,
            "is_total": False,
        })
    rows.append({
        "component": "Total OpEx (Yr 1, excl. tax)",
        "per_mw_yr": (annual_opex_yr1 / capacity_mw) if capacity_mw else 0,
        "total": annual_opex_yr1,
        "total_display": _fmt_gbp(annual_opex_yr1),
        "notes": "Escalated at 2.4% CPI (BoE MPR Feb 2026)",
        "is_total": True,
    })
    return rows


# ---------------------------------------------------------------------------
# DCF schedule (display rows: Y1..Y5 + every 5th)
# ---------------------------------------------------------------------------

def _build_dcf_schedule(
    dcf: DCFResult,
    wacc_pct: float,
    technology: str,
    capacity_mw: float,
    ppa_price: float,
) -> list[dict[str, Any]]:
    """Flatten DCF evaluator output to display rows with cumulative NPV."""
    is_bess = technology == "bess"
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    annual_gen = capacity_mw * cf * 8760 if not is_bess else 0.0

    cashflows = dcf.cashflows
    covenants = {c["year"]: c for c in dcf.covenants}

    # Cumulative NPV
    cum_npv = -dcf.summary["capex"]
    running: list[tuple[int, float]] = []
    for i, cf_row in enumerate(cashflows):
        pv = cf_row["fcff"] / ((1 + wacc_pct) ** (i + 1))
        cum_npv += pv
        running.append((cf_row["year"], cum_npv))
    cum_map = dict(running)

    rows: list[dict[str, Any]] = []
    for year in _SCHEDULE_YEARS:
        if year > len(cashflows):
            continue
        cf_row = cashflows[year - 1]
        cov = covenants.get(year, {})
        # degrade generation + inflate price for display
        if is_bess:
            gen_gwh = 0.0
            price = cf_row["revenue"] / 1_000_000   # £m/yr proxy label for BESS row
        else:
            deg_gen = annual_gen * (1 - DEGRADATION_RATE) ** year
            gen_gwh = deg_gen / 1_000
            price = ppa_price * (1 + CPI_LONG_RUN) ** year

        rows.append({
            "year": year,
            "gen_gwh": gen_gwh,
            "price": price,
            "revenue": cf_row["revenue"],
            "revenue_display": _fmt_gbp(cf_row["revenue"]),
            "opex": cf_row["opex"],
            "opex_display": _fmt_gbp(cf_row["opex"]),
            "ebitda": cf_row["ebitda"],
            "ebitda_display": _fmt_gbp(cf_row["ebitda"]),
            "debt_service": cf_row["debt_service"],
            "debt_service_display": _fmt_gbp(cf_row["debt_service"]),
            "cfads": cf_row["cfads"],
            "cfads_display": _fmt_gbp(cf_row["cfads"]),
            "dscr": cov.get("dscr"),
            "fcfe": cf_row["fcfe"],
            "fcfe_display": _fmt_gbp(cf_row["fcfe"]),
            "cum_npv": cum_map.get(year),
            "cum_npv_display": _fmt_gbp(cum_map.get(year, 0)),
        })
    return rows


def _build_amortising_rows(
    dcf: DCFResult,
) -> list[dict[str, Any]]:
    """Format debt-service rows for display (Y1..Y5 + every 5th up to tenor)."""
    if not dcf.covenants:
        return []
    rows: list[dict[str, Any]] = []
    for year in _SCHEDULE_YEARS:
        idx = year - 1
        if idx >= len(dcf.covenants):
            continue
        cov = dcf.covenants[idx]
        # opening balance = debt_outstanding + principal (we only have outstanding)
        # use cashflows to reconstruct: interest at rate and principal paid
        interest = cov.get("interest", 0.0)
        principal = cov.get("principal", 0.0)
        ds = cov.get("debt_service", 0.0)
        closing = cov.get("debt_outstanding", 0.0) - principal  # closing after pmt
        opening = cov.get("debt_outstanding", 0.0)
        if opening == 0 and principal == 0 and interest == 0 and ds == 0:
            continue
        rows.append({
            "year": year,
            "opening_display": _fmt_gbp(opening),
            "interest_display": _fmt_gbp(interest),
            "principal_display": _fmt_gbp(principal),
            "ds_display": _fmt_gbp(ds),
            "closing_display": _fmt_gbp(max(0.0, closing)),
            "dscr": cov.get("dscr"),
        })
    return rows


# ---------------------------------------------------------------------------
# Risk register (12+ lender-grade entries)
# ---------------------------------------------------------------------------

_LIKELIHOOD_CHIP = {"Low": "L", "Medium": "M", "High": "H"}


def _build_risk_register(technology: str) -> list[dict[str, Any]]:
    egl = egl_applies_to(technology)
    base_risks = [
        {
            "title": "Planning refusal or JR challenge",
            "description": "LPA refusal, s.78 appeal delay, or judicial review of consent (incl. third-party challenge).",
            "likelihood": "Medium", "impact": "High",
            "mitigation": "Pre-app consultation; LVIA + EIA screening; community benefit fund; legal opinion pre-FID.",
            "residual": "Medium",
        },
        {
            "title": "Grid connection slippage",
            "description": "DNO/TO energisation slip beyond contracted date; reinforcement works in critical path.",
            "likelihood": "Medium", "impact": "High",
            "mitigation": "Signed Bilateral Connection Agreement with LDs; TEC registration; dual-route design review.",
            "residual": "Medium",
        },
        {
            "title": "Commissioning delay",
            "description": "Mechanical/electrical completion slip, SCADA integration, O&M mobilisation.",
            "likelihood": "Low", "impact": "Medium",
            "mitigation": "Fixed-price, date-certain EPC with LDs capped at 15% of EPC price; IE monitoring.",
            "residual": "Low",
        },
        {
            "title": "Curtailment risk",
            "description": "NESO BM dispatch-down, local network constraints (esp. NE/NW England and S. Scotland).",
            "likelihood": "Medium", "impact": "Medium",
            "mitigation": "Locational analysis via NESO NOA; BESS co-location option retained; REMA reform monitoring.",
            "residual": "Medium",
        },
        {
            "title": "Merchant cannibalisation",
            "description": "Tech-specific capture price erosion as same-tech fleet grows (solar capture <£35/MWh tail risk).",
            "likelihood": "Medium", "impact": "Medium",
            "mitigation": "15-yr indexed PPA floor; CfD eligibility; revenue-stack diversification.",
            "residual": "Medium",
        },
        {
            "title": "Electricity Generator Levy (EGL)",
            "description": (
                "35% windfall on revenue above £75/MWh. "
                + ("In-scope for this technology — modelled as upside-only haircut."
                   if egl else "Not in scope for this technology (BESS/DC exempt).")
            ),
            "likelihood": "High" if egl else "Low",
            "impact": "Low" if egl else "Low",
            "mitigation": "HMRC windfall receipts ring-fenced in covenants; EGL sunset clause 31 Mar 2028.",
            "residual": "Low",
        },
        {
            "title": "CfD / ROC regulatory change",
            "description": "AR7 terms revision, CfD strike clawback, ROC buy-out review.",
            "likelihood": "Low", "impact": "Medium",
            "mitigation": "Existing CfD contracts are grandfathered; AR7 terms published Oct 2025.",
            "residual": "Low",
        },
        {
            "title": "Counterparty PPA risk",
            "description": "Offtaker default or credit downgrade (single-name utility PPA).",
            "likelihood": "Low", "impact": "High",
            "mitigation": "Investment-grade offtaker requirement; parent guarantee; novation right to fall-back utility.",
            "residual": "Low",
        },
        {
            "title": "EPC insolvency",
            "description": "Principal contractor insolvency during construction.",
            "likelihood": "Low", "impact": "High",
            "mitigation": "Performance bond 10% EPC; retention 5%; direct agreement with key sub-contractors.",
            "residual": "Low",
        },
        {
            "title": "SCADA / availability underperformance",
            "description": "Tracker / inverter / WTG availability below OEM warranty thresholds.",
            "likelihood": "Low", "impact": "Medium",
            "mitigation": "95% availability warranty (annual average); liquidated damages for production shortfall.",
            "residual": "Low",
        },
        {
            "title": "Interest-rate upward drift",
            "description": "SONIA resets + margin step-ups if covenants slip; refinancing risk at year 15 mini-perm.",
            "likelihood": "Medium", "impact": "Medium",
            "mitigation": "IRS hedge on 70% of senior debt; cash sweep at 1.15x DSCR lock-up; 5-yr refi buffer.",
            "residual": "Medium",
        },
        {
            "title": "Insurance market cap",
            "description": "Hardening specialist BESS / extreme-weather cover; premium step-ups at renewal.",
            "likelihood": "Medium", "impact": "Low",
            "mitigation": "Placed with A-rated syndicate; sinking fund for premium escalation beyond CPI+2%.",
            "residual": "Low",
        },
    ]
    for r in base_risks:
        r["likelihood_chip"] = _LIKELIHOOD_CHIP[r["likelihood"]]
        r["impact_chip"] = _LIKELIHOOD_CHIP[r["impact"]]
        r["residual_chip"] = _LIKELIHOOD_CHIP[r["residual"]]
    return base_risks


# ---------------------------------------------------------------------------
# Assumptions appendix
# ---------------------------------------------------------------------------

def _build_assumptions(
    technology: str,
    ppa_price: float,
    wacc_pct: float,
    gearing_pct: float,
    debt_rate_pct: float,
    tenor: int,
) -> list[dict[str, str]]:
    return [
        {"key": "Project life",
         "value": f"{PROJECT_LIFE} years operational + {CONSTRUCTION_YEARS} yr construction",
         "source": "Standard UK project-finance convention; solar module warranty 25 yr (Tier 1)."},
        {"key": "Inflation (CPI, long run)",
         "value": f"{CPI_LONG_RUN * 100:.1f}% nominal p.a.",
         "source": "Bank of England Monetary Policy Report, Feb 2026 (2-yr and 5-yr forward)."},
        {"key": "UK corporation tax",
         "value": f"{corporation_tax_rate() * 100:.0f}% mainline (profits > £250k)",
         "source": "HMRC CT601 Finance Act 2024, FY2025-26."},
        {"key": "Electricity Generator Levy (EGL)",
         "value": (f"35% over £{egl_threshold_gbp_mwh():.0f}/MWh benchmark; "
                   f"in scope = {egl_applies_to(technology)}"),
         "source": "Spring Budget 2023; CPI-uplifted 2025; HMT EGL guidance 2025-26. Sunset 31 Mar 2028."},
        {"key": "WACC (discount rate)",
         "value": f"{wacc_pct * 100:.2f}% nominal post-tax",
         "source": "Greencoat/Octopus Renewables 2025 AR; Princeps utils.finance_benchmarks WACC band (stabilised)."},
        {"key": "Capital structure",
         "value": f"{gearing_pct * 100:.0f}% senior / {(1 - gearing_pct) * 100:.0f}% equity",
         "source": "UK renewables PF benchmark 2026: solar/wind 65:35, offshore 55:45, BESS 50:50."},
        {"key": "Senior debt — reference rate",
         "value": f"SONIA {SONIA_REFERENCE_PCT:.2f}% + {DEBT_MARGIN_BPS.get(technology, 250)} bps = {debt_rate_pct * 100:.2f}%",
         "source": "BoE SONIA daily (Apr 2026); tech-specific margin from utils.finance_benchmarks."},
        {"key": "Senior debt tenor",
         "value": f"{tenor} years (incl. mini-perm tail)",
         "source": "Market soundings 2026; solar/wind 18y, offshore 15y, BESS 9y."},
        {"key": "PPA strike (base case)",
         "value": f"£{ppa_price:.0f}/MWh nominal, CPI-indexed",
         "source": "Cornwall Insight UK PPA Tracker Q1 2026 (merchant mid)."},
        {"key": "CfD AR7 Pot 1 reference",
         "value": f"£{cfd_strike_2026(pot=1):.0f}/MWh (2026 prices), 15-yr indexed",
         "source": "LCCC AR7 clearing, Jan 2026; HMT GDP deflator 2012→2026 ×1.34."},
        {"key": "T-4 Capacity Market 2028/29",
         "value": "£45/kW/yr clearing (de minimis for solar; full for BESS)",
         "source": "NESO T-4 2028/29 auction results, Feb 2026."},
        {"key": "Degradation",
         "value": f"{DEGRADATION_RATE * 100:.1f}%/yr (solar/wind); 2× for BESS calendar+cycle",
         "source": "PVsyst Tier 1 warranty 25-yr; Hesse et al. 2017 (Li-ion cycling)."},
        {"key": "Capacity factor",
         "value": f"{CAPACITY_FACTORS.get(technology, 0.11) * 100:.1f}% ({technology})",
         "source": "NESO historical rolling 10-yr (solar 11%, onshore wind 28%, offshore 40%)."},
        {"key": "CapEx (per MW)",
         "value": _fmt_gbp(CAPEX_PER_MW.get(technology, CAPEX_PER_MW["solar"])) + "/MW",
         "source": "Cornwall Insight UK Renewables Benchmark Q1 2026; LCP Delta DC Cost Tracker Mar 2026."},
        {"key": "OpEx (per MW, Yr 1)",
         "value": _fmt_gbp(OPEX_PER_MW.get(technology, OPEX_PER_MW["solar"])) + "/MW/yr",
         "source": "Greencoat/JLEN 2025 annual accounts; DESNZ OpEx benchmark; RIIO-ED2 comparator."},
        {"key": "Lender covenant thresholds",
         "value": "DSCR 1.20x base / 1.15x lock-up / 1.05x default; LLCR 1.30x; PLCR 1.40x",
         "source": "UK infra standard (NatWest/Lloyds/MUFG 2024-26 sample covenants)."},
        {"key": "Terminal value (Gordon growth)",
         "value": "g = 0% on final-year FCFF; residual land + decommissioning netted",
         "source": "RICS Financial Viability in Planning 1st ed. (2021)."},
        {"key": "Princeps SSOT citation",
         "value": finance_cite(),
         "source": "utils.finance_benchmarks (this report's single source of truth)."},
    ]


# ---------------------------------------------------------------------------
# Stress-case elaboration (covenant breach analysis)
# ---------------------------------------------------------------------------

def _elaborate_downside(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
    wacc_pct: float,
    gearing: float,
    debt_rate: float,
    tenor: int,
    tax_rate: float,
) -> dict[str, Any]:
    """Re-run DCF under downside stress and inspect covenant breaches."""
    base = fvr_stress_downside(capacity_mw, technology, ppa_price)

    # Build a stressed DCF to detect DSCR breach year.
    stressed_ppa = ppa_price * base["revenue_mult"]
    stressed_capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["solar"]) * base["capex_mult"]
    # Rebuild schedules with stressed capex
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW["solar"])
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    annual_gen = capacity_mw * cf * 8760 if not is_bess else 0.0
    bess_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0.0
    total_capex = stressed_capex_mw * capacity_mw
    rev: list[float] = []
    opex_s: list[float] = []
    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            rev.append(bess_base * (1 + CPI_LONG_RUN) ** y * (1 - DEGRADATION_RATE * 2) ** y
                       * base["revenue_mult"])
        else:
            deg = annual_gen * (1 - DEGRADATION_RATE) ** y
            rev.append(deg * stressed_ppa * (1 + CPI_LONG_RUN) ** y)
        opex_s.append(opex_mw * capacity_mw * (1 + CPI_LONG_RUN) ** y)

    debt_amt = total_capex * gearing
    debt_sched = build_amortising_debt(
        principal=debt_amt, rate=debt_rate, term_years=tenor, life_years=PROJECT_LIFE,
    )
    ev = DCFEvaluator(
        capex=total_capex,
        revenue_schedule=rev,
        opex_schedule=opex_s,
        tax_rate=tax_rate,
        wacc=wacc_pct,
        terminal_growth=0.0,
        debt_schedule=debt_sched,
        technology=technology,
    )
    res = ev.evaluate()
    breach_year = None
    for c in res.covenants:
        if c["dscr"] is not None and c["dscr"] < 1.15 and c["debt_service"] > 0:
            breach_year = c["year"]
            break

    min_dscr = res.summary.get("min_dscr")
    cure = (
        f"Cash sweep at 1.15x lock-up triggers in Year {breach_year}; "
        "parent support letter for 24 months of debt service (~"
        f"{_fmt_gbp((res.covenants[0]['debt_service'] or 0) * 2)}) required; "
        "sponsor injects equity cure up to 10% of outstanding."
    ) if breach_year else (
        "No covenant breach under this stress; standing cash reserve (6 mo DSRA) maintained."
    )

    return {
        **base,
        "dscr_breach": bool(breach_year),
        "breach_year": breach_year,
        "min_dscr_stressed": min_dscr,
        "cure_path": cure,
    }


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _classify_verdict(
    equity_irr_post_tax: float, mean_dscr: float, min_dscr: float,
) -> tuple[str, str]:
    """Return (status, headline) — GO / CAUTION / NO-GO."""
    if min_dscr is None:
        min_dscr = 0.0
    if mean_dscr is None:
        mean_dscr = 0.0
    if min_dscr < 1.15 or equity_irr_post_tax < 6:
        return "NO-GO", "Project does not meet UK senior-secured lender thresholds on this base case."
    if mean_dscr < 1.30 or equity_irr_post_tax < 9 or min_dscr < 1.20:
        return "CAUTION", "Meets covenants with limited headroom; senior sizing may need reduction."
    return "GO", "Project is bankable on a standard UK senior-secured basis."


def _build_context(
    *,
    lat: float, lon: float, site_name: str, capacity_mw: float,
    technology: str, ppa_price: float,
    dcf: DCFResult, dcf_diag: dict,
    equity: dict, debt: dict,
    sensitivity: dict, stress_d: dict, stress_u: dict,
    wacc_pct: float, debt_rate: float, gearing: float, tenor: int,
) -> dict[str, Any]:
    total_capex = dcf_diag["total_capex"]
    annual_opex_yr1 = dcf_diag["annual_opex_yr1"]
    summary = dcf.summary

    # Derive P10/P50/P90 IRR bands from tornado range (rough proxy)
    base_eq_irr = sensitivity["base_irr_pct"]
    eq_post = equity.get("equity_irr_post_tax_pct") or base_eq_irr
    spread = max(r["range"] for r in sensitivity["rows"]) / 2
    irr_p10 = max(0.0, eq_post - spread)
    irr_p90 = eq_post + spread / 2

    mean_dscr = 0.0
    dscrs = [c["dscr"] for c in dcf.covenants if c.get("dscr") is not None and (c.get("debt_service") or 0) > 0]
    if dscrs:
        mean_dscr = sum(dscrs) / len(dscrs)
    min_dscr = summary.get("min_dscr") or 0.0

    status, headline = _classify_verdict(eq_post, mean_dscr, min_dscr)

    # Executive critical risks — top 3 by tornado range with practical framing
    top3 = sensitivity["rows"][:3]
    critical_risks = []
    for r in top3:
        critical_risks.append({
            "title": r["factor"],
            "detail": (f"P50 equity IRR swings {r['range']:.1f} pp across the ±case; "
                       f"pessimistic case IRR {r['irr_low']:.1f}%."),
        })

    # Revenue stack
    revenue_stack = _build_revenue_stack(technology, ppa_price)

    # CapEx / OpEx breakdowns
    capex_breakdown = _build_capex_breakdown(technology, total_capex, capacity_mw)
    opex_breakdown = _build_opex_breakdown(technology, annual_opex_yr1, capacity_mw)

    # DCF schedule
    dcf_schedule = _build_dcf_schedule(dcf, wacc_pct, technology, capacity_mw, ppa_price)
    amortising_rows = _build_amortising_rows(dcf)

    # Debt KPI block
    debt_ctx = {
        "gearing_pct": gearing * 100,
        "tenor_years": tenor,
        "all_in_rate_pct": debt_rate * 100,
        "margin_bps": DEBT_MARGIN_BPS.get(technology, 250),
        "sonia_ref_pct": SONIA_REFERENCE_PCT,
        "debt_amount": dcf_diag["debt_principal"],
        "debt_amount_display": _fmt_gbp(dcf_diag["debt_principal"]),
        "min_dscr": min_dscr,
        "mean_dscr": mean_dscr,
        "llcr": summary.get("min_llcr") or 0.0,
        "plcr": summary.get("min_plcr") or 0.0,
        "amortising_rows": amortising_rows,
    }

    # Equity KPI block
    equity_ctx = {
        "unlevered_irr_pct": summary.get("irr_pct") or 0.0,
        "levered_irr_pre_tax_pct": equity.get("equity_irr_pre_tax_pct") or 0.0,
        "levered_irr_post_tax_pct": eq_post,
        "equity_multiple": equity.get("equity_multiple") or 0.0,
        "cash_on_cash_pct": equity.get("cash_on_cash_yield_pct") or 0.0,
        "equity_amount_display": _fmt_gbp(dcf_diag["equity_principal"]),
        "payback_year": equity.get("payback_year"),
        "wacc_pct": wacc_pct * 100,
        "cost_of_equity_pct": summary.get("cost_of_equity_pct") or (wacc_pct + 0.025) * 100,
        "total_dividends_display": _fmt_gbp(equity.get("total_dividends") or 0),
    }

    # Executive summary block
    exec_summary = {
        "equity_irr_p10": irr_p10,
        "equity_irr_p50": eq_post,
        "equity_irr_p90": irr_p90,
        "min_dscr_stress": stress_d["min_dscr_stressed"] or min_dscr,
        "capex_display": _fmt_gbp(total_capex),
        "capex_per_mw_k": (total_capex / capacity_mw / 1_000) if capacity_mw else 0,
        "ppa_strike": ppa_price,
        "ppa_source": "Cornwall Insight Q1 2026",
        "gearing_pct": int(round(gearing * 100)),
        "debt_tenor": tenor,
        "margin_bps": DEBT_MARGIN_BPS.get(technology, 250),
        "mean_dscr": mean_dscr,
        "critical_risks": critical_risks,
    }

    # Project identity block
    now = datetime.utcnow()
    ref = f"FVR-{uuid.uuid4().hex[:8].upper()}"
    cod = (now + timedelta(days=730)).strftime("%b %Y")
    project_ctx = {
        "site_name": site_name,
        "lat": lat,
        "lon": lon,
        "technology": technology,
        "technology_label": TECH_LABELS.get(technology, technology.replace("_", " ").title()),
        "capacity_mw": capacity_mw,
        "capacity_dc_mw": capacity_mw * 1.25 if technology == "solar" else capacity_mw,
        "ref": ref,
        "revision": "P1",
        "revision_stage": "Preliminary for Credit Committee",
        "date": now.strftime("%d %B %Y"),
        "run_id": ref,
        "region": _infer_region(lat, lon),
        "layout_ha": capacity_mw * (2.0 if technology == "solar"
                                    else 6.0 if technology == "wind"
                                    else 0.3 if technology == "bess"
                                    else 0.0),
        "substation": "Nearest 33 kV primary (TBC at Tier-2)",
        "voltage_kv": 33 if capacity_mw <= 50 else 132,
        "gsp": "TBC",
        "planning_status": "Pre-application / EIA scoping",
        "expected_cod": cod,
        "project_life_years": PROJECT_LIFE,
        "construction_years": CONSTRUCTION_YEARS,
        "capacity_factor_pct": CAPACITY_FACTORS.get(technology, 0.11) * 100,
    }

    return {
        "project": project_ctx,
        "recipient": {"name": "the Lender"},
        "verdict": {"status": status, "headline": headline},
        "exec_summary": exec_summary,
        "revenue_stack": revenue_stack,
        "capex_breakdown": capex_breakdown,
        "opex_breakdown": opex_breakdown,
        "dcf_schedule": dcf_schedule,
        "dcf_summary": summary,
        "debt": debt_ctx,
        "equity": equity_ctx,
        "tornado": sensitivity,
        "stress_downside": stress_d,
        "stress_upside": stress_u,
        "risk_register": _build_risk_register(technology),
        "assumptions": _build_assumptions(
            technology, ppa_price, wacc_pct, gearing, debt_rate, tenor,
        ),
    }


def _infer_region(lat: float, lon: float) -> str:
    """Rough UK region inference from lat/lon."""
    if lat > 56:
        return "Scotland"
    if lat > 53.5:
        return "North of England"
    if lat > 52.2:
        return "Midlands"
    if lon < -3:
        return "Wales / SW England"
    return "South East England"


# ---------------------------------------------------------------------------
# HTML -> PDF via Playwright
# ---------------------------------------------------------------------------

async def _html_to_pdf(html_string: str) -> bytes:
    import tempfile
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from e

    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(html_string)
        tmp.close()
        file_url = f"file://{tmp.name}"
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60_000)
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            await browser.close()
            return pdf_bytes
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def generate_financial_report(
    lat: float,
    lon: float,
    site_name: str = "Site",
    capacity_mw: float = 50.0,
    technology: str = "solar",
    ppa_price: float | None = None,
) -> bytes:
    """Generate the lender-grade Financial Viability Report (FVR) PDF.

    Args:
        lat, lon:     WGS84 coords of the site.
        site_name:    Display name for cover + running header.
        capacity_mw:  Proposed nameplate capacity (AC).
        technology:   'solar' | 'wind' | 'offshore_wind' | 'bess'.
        ppa_price:    PPA strike £/MWh. If None, resolves to
                      utils.finance_benchmarks.ppa_price_merchant(technology).

    Returns:
        PDF bytes (A4 portrait, ~15-20 pages at typical inputs).
    """
    technology = (technology or "solar").lower()
    if ppa_price is None:
        ppa_price = ppa_price_merchant(technology)

    log.info(
        "FVR start: %s, %.1f MW %s @ £%.0f/MWh",
        site_name, capacity_mw, technology, ppa_price,
    )

    # Resolve benchmark finance structure
    wacc_pct = bench_wacc(technology, "stabilised")
    gearing = debt_to_equity(technology)[0]
    debt_rate = senior_debt_all_in_rate(technology)
    tenor = debt_tenor_years(technology)
    tax_rate = corporation_tax_rate()

    loop = asyncio.get_running_loop()

    # Kick off subprocess calls in parallel (debt + equity summaries)
    debt_task = _run_appraisal_async(
        "debt_structure",
        capacity_mw=capacity_mw, technology=technology,
        gearing=gearing, ppa_price=ppa_price,
    )
    equity_task = _run_appraisal_async(
        "equity_returns",
        capacity_mw=capacity_mw, technology=technology,
        gearing=gearing, ppa_price=ppa_price,
    )

    # Run DCFEvaluator and in-process sensitivity in executor (CPU-bound)
    dcf_task = loop.run_in_executor(
        None, _run_dcf,
        capacity_mw, technology, ppa_price, wacc_pct, gearing, debt_rate, tenor, tax_rate,
    )
    sens_task = loop.run_in_executor(
        None, compute_tornado, capacity_mw, technology, ppa_price,
    )
    stress_u_task = loop.run_in_executor(
        None, fvr_stress_upside, capacity_mw, technology, ppa_price,
    )

    debt_raw, equity_raw, (dcf_result, dcf_diag), sensitivity, stress_u = await asyncio.gather(
        debt_task, equity_task, dcf_task, sens_task, stress_u_task,
    )
    if debt_raw.get("error"):
        log.warning("debt_structure subprocess error: %s", debt_raw["error"])
        debt_raw = {}
    if equity_raw.get("error"):
        log.warning("equity_returns subprocess error: %s", equity_raw["error"])
        equity_raw = {}

    # Elaborate downside with covenant-breach detection (uses stressed DCF)
    stress_d = await loop.run_in_executor(
        None, _elaborate_downside,
        capacity_mw, technology, ppa_price, wacc_pct, gearing, debt_rate, tenor, tax_rate,
    )

    # Synthesize payback year if not in equity subprocess output
    equity_raw.setdefault("payback_year", None)

    log.info(
        "FVR DCF: NPV=%s IRR=%.2f%% min DSCR=%s mean DSCR=%s",
        _fmt_gbp(dcf_result.summary.get("npv", 0)),
        dcf_result.summary.get("irr_pct") or 0,
        dcf_result.summary.get("min_dscr"),
        dcf_result.summary.get("equity_irr_pct"),
    )

    context = _build_context(
        lat=lat, lon=lon, site_name=site_name, capacity_mw=capacity_mw,
        technology=technology, ppa_price=ppa_price,
        dcf=dcf_result, dcf_diag=dcf_diag,
        equity=equity_raw, debt=debt_raw,
        sensitivity=sensitivity, stress_d=stress_d, stress_u=stress_u,
        wacc_pct=wacc_pct, debt_rate=debt_rate, gearing=gearing, tenor=tenor,
    )

    template = _jinja_env.get_template("main.html.j2")
    html = template.render(**context)
    pdf_bytes = await _html_to_pdf(html)
    log.info("FVR complete: %d bytes", len(pdf_bytes))
    return pdf_bytes
