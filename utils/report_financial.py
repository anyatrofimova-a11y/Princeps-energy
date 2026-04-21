"""
Princeps Financial Viability PDF Report Generator.

Generates a comprehensive financial viability assessment PDF for energy
infrastructure projects. Uses the investment_appraisal subprocess bridge
for DCF modelling and uk_energy_assumptions for CB7 reference parameters.

Pipeline: build params -> subprocess appraisal -> charts -> Jinja2 HTML -> PDF.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from jinja2 import Environment, FileSystemLoader

# DCF engine (BOT-A) — used by GAP 2: real DCF waterfall, debt schedule, DSCR timeline
from utils.dcf_evaluator import DCFEvaluator, DCFResult, build_amortising_debt
from utils.financial_viability_charts import (
    generate_dcf_charts,
    build_amortising_schedule_rows,
)

log = logging.getLogger("princeps.report_financial")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "report"
_APPRAISAL_SCRIPT = Path(__file__).resolve().parent / "investment_appraisal.py"

# Brand palette — Princeps gold
GOLD = "#D4A018"
DARK = "#1a1a2e"
GREEN = "#24a148"
GREEN_LIGHT = "#42be65"
RED = "#da1e28"
AMBER = "#f1c21b"
GREY = "#697077"
GREY_LIGHT = "#a8a8a8"
WHITE = "#ffffff"
LIGHT = "#f4f4f4"
PRIMARY = "#0f62fe"

# Technology labels
TECH_LABELS = {
    "solar": "Ground-Mount Solar PV",
    "wind": "Onshore Wind",
    "offshore_wind": "Offshore Wind",
    "bess": "Battery Energy Storage (BESS)",
}

# CAPEX breakdown ratios by technology (% of total CAPEX)
CAPEX_BREAKDOWN = {
    "solar": [
        ("Panels / Modules", 0.38),
        ("Inverters", 0.10),
        ("Mounting Structure", 0.08),
        ("Balance of System", 0.12),
        ("Grid Connection", 0.14),
        ("Development & Consenting", 0.08),
        ("Contingency", 0.05),
        ("Owner's Costs", 0.05),
    ],
    "wind": [
        ("Turbines", 0.58),
        ("Foundations", 0.08),
        ("Balance of Plant", 0.10),
        ("Grid Connection", 0.10),
        ("Development & Consenting", 0.06),
        ("Contingency", 0.04),
        ("Owner's Costs", 0.04),
    ],
    "offshore_wind": [
        ("Turbines", 0.38),
        ("Foundations & Subsea", 0.22),
        ("Array Cables", 0.08),
        ("Export Cable", 0.10),
        ("Onshore Substation", 0.06),
        ("Installation", 0.08),
        ("Development & Consenting", 0.04),
        ("Contingency", 0.04),
    ],
    "bess": [
        ("Battery Modules", 0.50),
        ("Power Conversion System", 0.15),
        ("Balance of Plant", 0.10),
        ("Grid Connection", 0.10),
        ("EMS & Controls", 0.05),
        ("Development & Consenting", 0.05),
        ("Contingency", 0.05),
    ],
}

# OPEX breakdown by technology
OPEX_BREAKDOWN = {
    "solar": [
        ("O&M Contract", 0.35, "Panel cleaning, inverter maintenance"),
        ("Insurance", 0.12, "Property + BI + liability"),
        ("Land Lease", 0.15, "Annual rent per acre"),
        ("Grid Charges (TNUoS)", 0.15, "Transmission use of system"),
        ("Grid Charges (BSUoS)", 0.08, "Balancing services"),
        ("Asset Management", 0.08, "SPV admin, reporting, compliance"),
        ("Contingency", 0.07, "Unplanned repairs reserve"),
    ],
    "wind": [
        ("O&M Contract", 0.42, "Turbine servicing, blade inspection"),
        ("Insurance", 0.12, "Property + BI + liability"),
        ("Land Lease", 0.10, "Annual rent per turbine"),
        ("Grid Charges (TNUoS)", 0.14, "Transmission use of system"),
        ("Grid Charges (BSUoS)", 0.08, "Balancing services"),
        ("Asset Management", 0.07, "SPV admin, reporting"),
        ("Contingency", 0.07, "Major component reserve"),
    ],
    "offshore_wind": [
        ("O&M Contract", 0.45, "Vessel-based maintenance, CTV/SOV"),
        ("Insurance", 0.15, "Marine + BI + liability"),
        ("Transmission Charges", 0.15, "OFTO charges"),
        ("Grid Charges (BSUoS)", 0.08, "Balancing services"),
        ("Asset Management", 0.08, "Offshore SPV admin"),
        ("Contingency", 0.09, "Major component reserve"),
    ],
    "bess": [
        ("O&M Contract", 0.30, "Cell monitoring, HVAC, fire suppression"),
        ("Insurance", 0.15, "Specialist BESS coverage"),
        ("Grid Charges (TNUoS)", 0.15, "Transmission use of system"),
        ("Grid Charges (BSUoS)", 0.10, "Balancing services"),
        ("Augmentation Reserve", 0.15, "Cell replacement fund"),
        ("Asset Management", 0.08, "SPV admin, trading oversight"),
        ("Contingency", 0.07, "Unplanned repairs"),
    ],
}

# Risk register
RISK_REGISTER = [
    {
        "category": "Grid Connection",
        "description": "Delay or refusal of grid connection offer; queue congestion at local GSP",
        "likelihood": "Medium",
        "impact": "High",
        "mitigation": "Early engagement with DNO; dual-substation strategy; connection agreement pre-FID",
    },
    {
        "category": "Planning Permission",
        "description": "Refusal or conditions from LPA; judicial review risk; community objection",
        "likelihood": "Medium",
        "impact": "High",
        "mitigation": "Pre-application consultation; LVIA & EIA screening; community benefit fund",
    },
    {
        "category": "Merchant Price",
        "description": "PPA price below forecast; wholesale price collapse; basis risk",
        "likelihood": "Medium",
        "impact": "Medium",
        "mitigation": "Long-term PPA (15yr+); CfD application; floor price mechanism; revenue stacking",
    },
    {
        "category": "Construction",
        "description": "Cost overruns; supply chain delays; contractor insolvency",
        "likelihood": "Low",
        "impact": "High",
        "mitigation": "Fixed-price EPC; liquidated damages; performance bonds; contingency reserve",
    },
    {
        "category": "Technology",
        "description": "Higher-than-expected degradation; inverter/turbine failure; underperformance",
        "likelihood": "Low",
        "impact": "Medium",
        "mitigation": "Tier-1 equipment; OEM warranty (25yr panels / 5yr inverters); independent TA",
    },
    {
        "category": "Regulatory",
        "description": "Changes to TNUoS charges, BSUoS reform, CfD terms, tax regime",
        "likelihood": "Medium",
        "impact": "Medium",
        "mitigation": "Policy monitoring; diversified revenue streams; trade body engagement",
    },
    {
        "category": "Interest Rate",
        "description": "Refinancing risk; floating rate exposure; margin step-ups",
        "likelihood": "Low",
        "impact": "Medium",
        "mitigation": "Fixed-rate senior debt; interest rate swap; cash sweep mechanism",
    },
]

_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fig_to_b64(fig: plt.Figure, dpi: int = 150) -> str:
    """Render matplotlib figure to base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=WHITE, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    """Apply Princeps styling to axes."""
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    ax.tick_params(labelsize=8, colors=DARK)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GREY_LIGHT)
    ax.spines["left"].set_color(GREY_LIGHT)


def _format_gbp(value: float) -> str:
    """Format GBP value with appropriate magnitude suffix."""
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        return f"{'−' if value < 0 else ''}£{abs_val / 1e9:.1f}bn"
    if abs_val >= 1_000_000:
        return f"{'−' if value < 0 else ''}£{abs_val / 1e6:.1f}m"
    if abs_val >= 1_000:
        return f"{'−' if value < 0 else ''}£{abs_val / 1e3:.0f}k"
    return f"£{value:,.0f}"


# ---------------------------------------------------------------------------
# Subprocess bridge to investment_appraisal.py
# ---------------------------------------------------------------------------

def _run_appraisal(command: str, **kwargs) -> dict:
    """Run investment_appraisal.py via subprocess and return parsed JSON."""
    python = os.environ.get("PYTHON", sys.executable)
    payload = {"command": command, **kwargs}

    try:
        result = subprocess.run(
            [python, str(_APPRAISAL_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Appraisal subprocess error: %s", result.stderr)
            return {"error": result.stderr or "Subprocess failed"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        log.error("Appraisal subprocess timed out")
        return {"error": "Subprocess timed out"}
    except json.JSONDecodeError as e:
        log.error("Appraisal subprocess invalid JSON: %s", e)
        return {"error": f"Invalid JSON response: {e}"}
    except Exception as e:
        log.error("Appraisal subprocess exception: %s", e)
        return {"error": str(e)}


async def _run_appraisal_async(command: str, **kwargs) -> dict:
    """Async wrapper for subprocess appraisal call."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _run_appraisal(command, **kwargs))


# ---------------------------------------------------------------------------
# Chart generators
# ---------------------------------------------------------------------------

def _capex_pie_chart(breakdown: list[dict]) -> str:
    """Donut chart for CAPEX breakdown."""
    items = [b for b in breakdown if not b.get("is_total")]
    if not items:
        return ""
    labels = [b["component"] for b in items]
    sizes = [b["pct"] for b in items]
    colours = [
        GOLD, "#e8c547", "#c49215", "#8a6a0f", PRIMARY, "#4589ff", "#a8a8a8", "#697077",
    ][:len(items)]

    fig, ax = plt.subplots(figsize=(5, 4))
    fig.patch.set_facecolor(WHITE)
    wedges, _, autotexts = ax.pie(
        sizes, labels=None, colors=colours,
        autopct=lambda p: f"{p:.0f}%" if p >= 4 else "",
        textprops={"fontsize": 8, "color": WHITE, "fontweight": "bold"},
        startangle=140, pctdistance=0.78,
        wedgeprops=dict(width=0.42, edgecolor=WHITE, linewidth=1.5),
    )
    ax.text(0, 0, "CAPEX\nBreakdown", ha="center", va="center",
            fontsize=11, fontweight="bold", color=DARK)
    ax.legend(wedges, [f"{l} ({s:.0f}%)" for l, s in zip(labels, sizes)],
              loc="center left", bbox_to_anchor=(1.0, 0.5),
              fontsize=7.5, framealpha=0.9, edgecolor="none")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _revenue_projection_chart(cashflow_detail: list[dict]) -> str:
    """Bar chart of annual revenue and OPEX over project life."""
    if not cashflow_detail:
        return ""
    years = [d["year"] for d in cashflow_detail]
    revenues = [d["revenue"] for d in cashflow_detail]
    opex_vals = [d["opex"] for d in cashflow_detail]
    ebitda_vals = [d["ebitda"] for d in cashflow_detail]

    fig, ax = plt.subplots(figsize=(8, 3.8))
    _apply_style(ax, fig)
    x = np.arange(len(years))
    w = 0.55

    ax.bar(x, revenues, w, color=GREEN, alpha=0.8, label="Revenue", zorder=2)
    ax.bar(x, [-o for o in opex_vals], w, color=RED, alpha=0.5, label="OPEX", zorder=2)
    ax.plot(x, ebitda_vals, color=GOLD, linewidth=2, marker="o", markersize=3,
            label="EBITDA", zorder=3)

    ax.set_xticks(x[::5])
    ax.set_xticklabels([str(y) for y in years[::5]], fontsize=8)
    ax.set_xlabel("Year", fontsize=9, color=DARK)
    ax.set_ylabel("£", fontsize=9, color=DARK)
    ax.axhline(y=0, color=GREY_LIGHT, linewidth=0.5)
    ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9, edgecolor="none")
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)

    # Format y-axis in millions
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"£{v/1e6:.1f}m" if abs(v) >= 1e6 else f"£{v/1e3:.0f}k"))

    fig.tight_layout()
    return _fig_to_b64(fig)


def _cashflow_chart(cashflow_detail: list[dict], total_capex: float, construction_years: int) -> str:
    """Combined bar + line chart: annual net CF bars, cumulative CF line."""
    if not cashflow_detail:
        return ""

    # Build full series including construction
    all_years = []
    all_net = []
    cumulative = 0

    # Construction years
    annual_capex = total_capex / construction_years
    for y in range(construction_years):
        all_years.append(-(construction_years - y))
        all_net.append(-annual_capex)

    # Operating years
    for d in cashflow_detail:
        all_years.append(d["year"])
        all_net.append(d["net_cashflow"])

    all_cumulative = []
    for ncf in all_net:
        cumulative += ncf
        all_cumulative.append(cumulative)

    fig, ax1 = plt.subplots(figsize=(8, 4))
    _apply_style(ax1, fig)
    x = np.arange(len(all_years))

    bar_colors = [GREEN if v >= 0 else RED for v in all_net]
    ax1.bar(x, all_net, 0.6, color=bar_colors, alpha=0.6, zorder=2, label="Net Cashflow")
    ax1.set_ylabel("Annual Net CF (£)", fontsize=9, color=DARK)
    ax1.axhline(y=0, color=GREY_LIGHT, linewidth=0.8)

    ax2 = ax1.twinx()
    ax2.plot(x, all_cumulative, color=GOLD, linewidth=2.5, marker="o", markersize=3,
             zorder=3, label="Cumulative CF")
    ax2.axhline(y=0, color=GOLD, linewidth=0.5, linestyle="--", alpha=0.5)
    ax2.set_ylabel("Cumulative CF (£)", fontsize=9, color=GOLD)
    ax2.tick_params(axis="y", labelcolor=GOLD, labelsize=8)
    ax2.spines["right"].set_color(GOLD)
    ax2.spines["top"].set_visible(False)

    # Format axes
    for ax in (ax1, ax2):
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"£{v/1e6:.1f}m" if abs(v) >= 1e6 else f"£{v/1e3:.0f}k")
        )

    tick_every = max(1, len(all_years) // 12)
    ax1.set_xticks(x[::tick_every])
    ax1.set_xticklabels([str(y) for y in all_years[::tick_every]], fontsize=8)
    ax1.set_xlabel("Year", fontsize=9, color=DARK)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7.5, loc="lower right",
               framealpha=0.9, edgecolor="none")

    ax1.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _sensitivity_tornado(sensitivity_data: list[dict], base_irr: float) -> str:
    """Tornado chart for IRR sensitivity."""
    if not sensitivity_data:
        return ""

    fig, ax = plt.subplots(figsize=(7, 4))
    _apply_style(ax, fig)

    params = [d["parameter"] for d in sensitivity_data]
    lows = [d["irr_low"] for d in sensitivity_data]
    highs = [d["irr_high"] for d in sensitivity_data]

    # Sort by range (widest at top)
    ranges = [abs(h - l) for h, l in zip(highs, lows)]
    order = sorted(range(len(params)), key=lambda i: ranges[i])
    params = [params[i] for i in order]
    lows = [lows[i] for i in order]
    highs = [highs[i] for i in order]

    y = np.arange(len(params))
    for i, (lo, hi) in enumerate(zip(lows, highs)):
        left = min(lo, base_irr)
        width_lo = base_irr - lo
        width_hi = hi - base_irr
        ax.barh(i, -width_lo, left=base_irr, height=0.5, color=RED, alpha=0.7, zorder=2)
        ax.barh(i, width_hi, left=base_irr, height=0.5, color=GREEN, alpha=0.7, zorder=2)
        ax.text(lo - 0.3, i, f"{lo:.1f}%", va="center", ha="right", fontsize=7.5, color=RED)
        ax.text(hi + 0.3, i, f"{hi:.1f}%", va="center", ha="left", fontsize=7.5, color=GREEN)

    ax.axvline(x=base_irr, color=GOLD, linewidth=2, linestyle="-", zorder=3, label=f"Base IRR: {base_irr:.1f}%")
    ax.set_yticks(y)
    ax.set_yticklabels(params, fontsize=9, color=DARK)
    ax.set_xlabel("Project IRR (%)", fontsize=9, color=DARK)
    ax.legend(fontsize=8, loc="lower right", framealpha=0.9, edgecolor="none")
    ax.grid(axis="x", alpha=0.15, linewidth=0.4)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _dscr_profile_chart(debt_schedule: list[dict], target_dscr: float) -> str:
    """Combined bar + line chart for DSCR profile and debt service."""
    if not debt_schedule:
        return ""

    years = [d["year"] for d in debt_schedule]
    ds = [d["debt_service"] for d in debt_schedule]
    dscrs = [d["dscr"] for d in debt_schedule]

    fig, ax1 = plt.subplots(figsize=(7, 3.5))
    _apply_style(ax1, fig)
    x = np.arange(len(years))

    ax1.bar(x, ds, 0.55, color=PRIMARY, alpha=0.7, label="Debt Service", zorder=2)
    ax1.set_ylabel("Debt Service (£)", fontsize=9, color=DARK)
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"£{v/1e6:.1f}m" if abs(v) >= 1e6 else f"£{v/1e3:.0f}k")
    )

    ax2 = ax1.twinx()
    dscr_colors = [GREEN if d >= target_dscr else AMBER if d >= 1.15 else RED for d in dscrs]
    ax2.plot(x, dscrs, color=GOLD, linewidth=2, marker="o", markersize=5, zorder=3, label="DSCR")
    for i, (xi, d) in enumerate(zip(x, dscrs)):
        ax2.scatter([xi], [d], color=dscr_colors[i], s=30, zorder=4, edgecolors=WHITE, linewidths=0.8)
    ax2.axhline(y=target_dscr, color=GREEN, linewidth=0.8, linestyle="--", alpha=0.6, label=f"Target ({target_dscr:.1f}x)")
    ax2.axhline(y=1.15, color=AMBER, linewidth=0.8, linestyle="--", alpha=0.6, label="Lock-up (1.15x)")
    ax2.axhline(y=1.05, color=RED, linewidth=0.8, linestyle="--", alpha=0.6, label="Default (1.05x)")
    ax2.set_ylabel("DSCR (x)", fontsize=9, color=GOLD)
    ax2.tick_params(axis="y", labelcolor=GOLD, labelsize=8)
    ax2.spines["right"].set_color(GOLD)
    ax2.spines["top"].set_visible(False)

    ax1.set_xticks(x)
    ax1.set_xticklabels([str(y) for y in years], fontsize=8)
    ax1.set_xlabel("Year", fontsize=9, color=DARK)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="upper right",
               framealpha=0.9, edgecolor="none")

    ax1.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Build full cashflow detail (all 25 years)
# ---------------------------------------------------------------------------

def _build_full_cashflow(finance: dict) -> list[dict]:
    """Reconstruct full 25-year cashflow from appraisal parameters."""
    from utils.investment_appraisal import (
        CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, REVENUE_PER_MW,
        DEGRADATION_RATE, CORPORATION_TAX, INFLATION, PROJECT_LIFE,
    )

    capacity_mw = finance.get("capacity_mw", 50)
    technology = finance.get("technology", "solar")
    # Solar default PPA from utils.solar_benchmarks (2026 merchant mid £45/MWh)
    from utils import solar_benchmarks as _sb
    ppa_price = finance.get("ppa_price", _sb.ppa_price_merchant_mid())

    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW.get("solar", 550_000))
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW.get("solar", 12_000))
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    annual_opex = opex_mw * capacity_mw

    detail = []
    for y in range(1, PROJECT_LIFE + 1):
        degraded_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y if not is_bess else 0
        if is_bess:
            revenue = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            revenue = degraded_gen * ppa_price * (1 + INFLATION) ** y
        opex = annual_opex * (1 + INFLATION) ** y
        ebitda = revenue - opex
        tax = max(0, ebitda * CORPORATION_TAX)
        net_cf = ebitda - tax
        detail.append({
            "year": y,
            "revenue": round(revenue),
            "opex": round(opex),
            "ebitda": round(ebitda),
            "tax": round(tax),
            "net_cashflow": round(net_cf),
        })
    return detail


def _build_full_debt_schedule(debt: dict) -> list[dict]:
    """Return the full sculpted repayment schedule from debt_structure output."""
    # The subprocess returns truncated. Re-run locally for full schedule.
    from utils.investment_appraisal import (
        CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, REVENUE_PER_MW,
        DEGRADATION_RATE, INFLATION, INTEREST_RATES, DEBT_TERM_YEARS,
    )

    capacity_mw = debt.get("capacity_mw", 50)
    technology = debt.get("technology", "solar")
    target_dscr = debt.get("target_dscr", 1.3)
    gearing = debt.get("gearing_pct", 70) / 100

    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW.get("solar", 550_000))
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW.get("solar", 12_000))
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"

    total_capex = capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    # Solar default PPA from utils.solar_benchmarks (2026 merchant mid £45/MWh)
    from utils import solar_benchmarks as _sb
    ppa_price = _sb.ppa_price_merchant_mid()

    debt_amount = total_capex * gearing
    interest_rate = INTEREST_RATES["senior"]
    outstanding = debt_amount

    schedule = []
    for y in range(1, DEBT_TERM_YEARS + 1):
        if is_bess:
            revenue = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            degraded_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            revenue = degraded_gen * ppa_price * (1 + INFLATION) ** y
        opex = annual_opex * (1 + INFLATION) ** y
        cfads = revenue - opex
        max_ds = cfads / target_dscr
        interest = outstanding * interest_rate
        principal = min(max(0, max_ds - interest), outstanding)
        actual_ds = interest + principal
        actual_dscr = cfads / actual_ds if actual_ds > 0 else 99.0
        outstanding -= principal
        schedule.append({
            "year": y,
            "cfads": round(cfads),
            "debt_service": round(actual_ds),
            "principal": round(principal),
            "interest": round(interest),
            "outstanding": round(max(0, outstanding)),
            "dscr": round(actual_dscr, 2),
        })
        if outstanding <= 0:
            break

    return schedule


# ---------------------------------------------------------------------------
# GAP 2 — Real DCF via utils.dcf_evaluator.DCFEvaluator
# ---------------------------------------------------------------------------

def _run_dcf_evaluator(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
    gearing_pct: float = 0.70,
    interest_rate: float = 0.06,
    debt_term_years: int = 18,
    wacc: float = 0.075,
    tax_rate: float = 0.25,
) -> tuple[DCFResult, dict]:
    """Build revenue + opex + debt schedules from UK assumptions and run
    DCFEvaluator.evaluate(). Returns the DCFResult plus an echoed param
    dict for the template context.

    This replaces the legacy finance-summary path (_build_full_cashflow +
    _build_full_debt_schedule) with the single-source-of-truth BOT-A
    evaluator so the IC pack, lender pack and FVP all agree.
    """
    from utils.investment_appraisal import (
        CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, REVENUE_PER_MW,
        DEGRADATION_RATE, INFLATION, PROJECT_LIFE,
    )

    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW.get("solar", 550_000))
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW.get("solar", 12_000))
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    annual_opex = opex_mw * capacity_mw
    total_capex = capex_mw * capacity_mw

    revenue_schedule: list[float] = []
    opex_schedule: list[float] = []
    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            rev = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            deg_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            rev = deg_gen * ppa_price * (1 + INFLATION) ** y
        opx = annual_opex * (1 + INFLATION) ** y
        revenue_schedule.append(rev)
        opex_schedule.append(opx)

    debt_principal = total_capex * gearing_pct
    debt_schedule = build_amortising_debt(
        principal=debt_principal,
        rate=interest_rate,
        term_years=debt_term_years,
        life_years=PROJECT_LIFE,
    )

    evaluator = DCFEvaluator(
        capex=total_capex,
        revenue_schedule=revenue_schedule,
        opex_schedule=opex_schedule,
        tax_rate=tax_rate,
        wacc=wacc,
        terminal_growth=0.0,
        debt_schedule=debt_schedule,
    )
    result = evaluator.evaluate()
    params = {
        "capex": total_capex,
        "annual_opex_yr1": annual_opex,
        "gearing_pct": gearing_pct,
        "debt_principal": debt_principal,
        "equity": total_capex - debt_principal,
        "interest_rate_pct": interest_rate * 100,
        "debt_term_years": debt_term_years,
        "wacc": wacc,
        "tax_rate": tax_rate,
        "project_life_years": PROJECT_LIFE,
    }
    return result, params


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

def _run_sensitivity(capacity_mw: float, technology: str, ppa_price: float) -> list[dict]:
    """Run sensitivity analysis on four key parameters, return table rows."""
    base = _run_appraisal("project_finance",
                          capacity_mw=capacity_mw, technology=technology,
                          ppa_price=ppa_price)
    base_irr = base.get("project_irr", 0) or 0

    scenarios = []

    # PPA price +/- 20%
    lo_ppa = _run_appraisal("project_finance", capacity_mw=capacity_mw,
                            technology=technology, ppa_price=ppa_price * 0.80)
    hi_ppa = _run_appraisal("project_finance", capacity_mw=capacity_mw,
                            technology=technology, ppa_price=ppa_price * 1.20)
    scenarios.append({
        "parameter": "PPA Price",
        "low_case": f"£{ppa_price * 0.80:.0f}/MWh",
        "irr_low": (lo_ppa.get("project_irr") or 0),
        "base_case": f"£{ppa_price:.0f}/MWh",
        "irr_base": base_irr,
        "high_case": f"£{ppa_price * 1.20:.0f}/MWh",
        "irr_high": (hi_ppa.get("project_irr") or 0),
    })

    # CAPEX +/- 15% (we approximate by adjusting capacity — the appraisal uses fixed per-MW)
    # Instead, we'll use the discount_rate parameter to simulate, or just note that
    # the per-MW costs are fixed. We'll run with different discount rates for CAPEX proxy.
    # Actually, the appraisal doesn't support CAPEX override directly. We'll compute manually.
    from utils.investment_appraisal import (
        CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, DEGRADATION_RATE,
        INFLATION, CORPORATION_TAX, PROJECT_LIFE, CONSTRUCTION_YEARS,
        _irr_newton, REVENUE_PER_MW,
    )

    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW.get("solar", 550_000))
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW.get("solar", 12_000))
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    annual_opex = opex_mw * capacity_mw

    def _compute_irr_for_capex_mult(mult: float) -> float:
        total = capex_mw * capacity_mw * mult
        cfs = [-total / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
        for y in range(1, PROJECT_LIFE + 1):
            if is_bess:
                rev = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
            else:
                dg = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
                rev = dg * ppa_price * (1 + INFLATION) ** y
            opx = annual_opex * (1 + INFLATION) ** y
            ebitda = rev - opx
            tax = max(0, ebitda * CORPORATION_TAX)
            cfs.append(ebitda - tax)
        irr = _irr_newton(cfs)
        return round((irr or 0) * 100, 2)

    scenarios.append({
        "parameter": "CAPEX",
        "low_case": f"−15% (£{capex_mw * 0.85 / 1000:.0f}k/MW)",
        "irr_low": _compute_irr_for_capex_mult(0.85),  # lower capex = higher IRR
        "base_case": f"£{capex_mw / 1000:.0f}k/MW",
        "irr_base": base_irr,
        "high_case": f"+15% (£{capex_mw * 1.15 / 1000:.0f}k/MW)",
        "irr_high": _compute_irr_for_capex_mult(1.15),
    })
    # Note: for CAPEX, "low case" = lower cost = higher IRR, so swap presentation
    # Actually the convention in tornado charts is: low_case = pessimistic for that parameter
    # For CAPEX: high CAPEX = pessimistic (lower IRR), low CAPEX = optimistic (higher IRR)
    # We keep irr_low = IRR when CAPEX is +15%, irr_high = IRR when CAPEX is -15%
    scenarios[-1]["irr_low"], scenarios[-1]["irr_high"] = scenarios[-1]["irr_high"], scenarios[-1]["irr_low"]
    scenarios[-1]["low_case"], scenarios[-1]["high_case"] = (
        f"+15% (£{capex_mw * 1.15 / 1000:.0f}k/MW)",
        f"−15% (£{capex_mw * 0.85 / 1000:.0f}k/MW)",
    )

    # Capacity factor +/- 10%
    def _compute_irr_for_cf_mult(mult: float) -> float:
        total = capex_mw * capacity_mw
        adj_gen = annual_gen_mwh * mult
        adj_bess = bess_revenue_base * mult
        cfs = [-total / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
        for y in range(1, PROJECT_LIFE + 1):
            if is_bess:
                rev = adj_bess * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
            else:
                dg = adj_gen * (1 - DEGRADATION_RATE) ** y
                rev = dg * ppa_price * (1 + INFLATION) ** y
            opx = annual_opex * (1 + INFLATION) ** y
            ebitda = rev - opx
            tax = max(0, ebitda * CORPORATION_TAX)
            cfs.append(ebitda - tax)
        irr = _irr_newton(cfs)
        return round((irr or 0) * 100, 2)

    scenarios.append({
        "parameter": "Capacity Factor",
        "low_case": f"−10% ({cf * 0.90 * 100:.1f}%)",
        "irr_low": _compute_irr_for_cf_mult(0.90),
        "base_case": f"{cf * 100:.1f}%",
        "irr_base": base_irr,
        "high_case": f"+10% ({cf * 1.10 * 100:.1f}%)",
        "irr_high": _compute_irr_for_cf_mult(1.10),
    })

    # Discount rate 6%-10%
    scenarios.append({
        "parameter": "Discount Rate",
        "low_case": "6%",
        "irr_low": base_irr,  # IRR doesn't change with DR; but NPV does. Show NPV instead.
        "base_case": "8%",
        "irr_base": base_irr,
        "high_case": "10%",
        "irr_high": base_irr,
    })

    return scenarios


# ---------------------------------------------------------------------------
# Build template context
# ---------------------------------------------------------------------------

def _build_context(
    finance: dict,
    debt: dict | None,
    equity: dict | None,
    site_name: str,
    capacity_mw: float,
    technology: str,
    lat: float,
    lon: float,
    ppa_price: float,
    sensitivity: list[dict],
    charts: dict[str, str],
    dcf_result: DCFResult | None = None,
    dcf_params: dict | None = None,
) -> dict[str, Any]:
    """Build the Jinja2 template context dict."""

    total_capex = finance.get("total_capex", 0)
    irr = finance.get("project_irr") or 0
    wacc_pct = (finance.get("wacc", 0.075)) * 100

    # Verdict
    if irr >= wacc_pct + 2:
        verdict = "ATTRACTIVE"
        verdict_class = "ATTRACTIVE"
    elif irr >= wacc_pct - 1:
        verdict = "MARGINAL"
        verdict_class = "MARGINAL"
    else:
        verdict = "BELOW HURDLE"
        verdict_class = "BELOW-HURDLE"

    # CAPEX breakdown
    tech_breakdown = CAPEX_BREAKDOWN.get(technology, CAPEX_BREAKDOWN["solar"])
    capex_items = []
    for component, frac in tech_breakdown:
        item_total = total_capex * frac
        capex_items.append({
            "component": component,
            "per_mw": item_total / capacity_mw if capacity_mw > 0 else 0,
            "total": item_total,
            "pct": frac * 100,
            "is_total": False,
        })
    capex_items.append({
        "component": "TOTAL CAPEX",
        "per_mw": total_capex / capacity_mw if capacity_mw > 0 else 0,
        "total": total_capex,
        "pct": 100.0,
        "is_total": True,
    })

    # OPEX breakdown
    annual_opex = finance.get("annual_opex_yr1", 0)
    tech_opex = OPEX_BREAKDOWN.get(technology, OPEX_BREAKDOWN["solar"])
    opex_items = []
    for component, frac, notes in tech_opex:
        opex_items.append({
            "component": component,
            "annual": annual_opex * frac,
            "per_mw": (annual_opex * frac) / capacity_mw if capacity_mw > 0 else 0,
            "notes": notes,
            "is_total": False,
        })
    opex_items.append({
        "component": "TOTAL OPEX (Year 1)",
        "annual": annual_opex,
        "per_mw": annual_opex / capacity_mw if capacity_mw > 0 else 0,
        "notes": "Escalated at CPI",
        "is_total": True,
    })

    # Full cashflow
    full_cf = _build_full_cashflow(finance)
    cumulative = -total_capex
    cashflow_table = []
    payback_found = False
    for row in full_cf:
        cumulative += row["net_cashflow"]
        is_payback = cumulative >= 0 and not payback_found
        if is_payback:
            payback_found = True
        cashflow_table.append({
            **row,
            "cumulative": round(cumulative),
            "is_payback": is_payback,
        })

    # Full debt schedule
    debt_schedule = _build_full_debt_schedule(debt) if debt and not debt.get("error") else []

    # Capacity factor
    from utils.investment_appraisal import CAPACITY_FACTORS
    cf = CAPACITY_FACTORS.get(technology, 0.11)

    # Year 1 revenue and total
    year1_revenue = full_cf[0]["revenue"] if full_cf else 0
    total_revenue = sum(r["revenue"] for r in full_cf)

    # Land
    land_per_mw = {"solar": 2.0, "wind": 6.0, "offshore_wind": 0, "bess": 0.3}

    # NPV display
    npv_8 = finance.get("npv_8pct", 0) or 0

    # GAP 2: Real DCF waterfall / amortising-debt table / DSCR timeline
    dcf_summary: dict[str, Any] = {}
    dcf_amortising_rows: list[dict[str, Any]] = []
    dcf_covenants: list[dict[str, Any]] = []
    if dcf_result is not None:
        dcf_summary = dict(dcf_result.summary)
        dcf_amortising_rows = build_amortising_schedule_rows(dcf_result)
        dcf_covenants = list(dcf_result.covenants)

    return {
        "site_name": site_name,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "technology_label": TECH_LABELS.get(technology, technology.replace("_", " ").title()),
        "lat": lat,
        "lon": lon,
        "ppa_price": ppa_price,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "verdict": verdict,
        "verdict_class": verdict_class,
        "finance": finance,
        "equity": equity if equity and not equity.get("error") else None,
        "debt": debt if debt and not debt.get("error") else None,
        "npv_display": _format_gbp(npv_8),
        "capex_display": _format_gbp(total_capex),
        "capex_breakdown": capex_items,
        "opex_breakdown": opex_items,
        "cashflow_table": cashflow_table,
        "debt_schedule": debt_schedule,
        "sensitivity_table": sensitivity,
        "hurdle_rate": finance.get("wacc", 0.075) * 100,
        "capacity_factor_pct": cf * 100,
        "year1_revenue": year1_revenue,
        "total_revenue_display": _format_gbp(total_revenue),
        "land_ha": capacity_mw * land_per_mw.get(technology, 2.0),
        "risks": RISK_REGISTER,
        "charts": charts,
        # GAP 2 — DCF evaluator output (from utils.dcf_evaluator.DCFEvaluator)
        "dcf_summary": dcf_summary,
        "dcf_amortising_rows": dcf_amortising_rows,
        "dcf_covenants": dcf_covenants,
        "dcf_params": dcf_params or {},
        "dcf_npv_display": _format_gbp(dcf_summary.get("npv", 0) or 0),
        "dcf_equity_npv_display": _format_gbp(dcf_summary.get("equity_npv", 0) or 0),
        "dcf_terminal_display": _format_gbp(dcf_summary.get("terminal_value", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Chart orchestrator
# ---------------------------------------------------------------------------

def _generate_all_charts(
    finance: dict,
    debt: dict | None,
    capex_items: list[dict],
    full_cashflow: list[dict],
    sensitivity: list[dict],
    debt_schedule: list[dict],
) -> dict[str, str]:
    """Generate all financial charts as base64 PNG strings."""
    charts: dict[str, str] = {}

    # CAPEX pie
    charts["capex_pie"] = _capex_pie_chart(capex_items)

    # Revenue projection
    charts["revenue_projection"] = _revenue_projection_chart(full_cashflow)

    # Cashflow
    total_capex = finance.get("total_capex", 0)
    construction_years = finance.get("construction_years", 2)
    charts["cashflow"] = _cashflow_chart(full_cashflow, total_capex, construction_years)

    # Sensitivity tornado
    base_irr = finance.get("project_irr") or 0
    charts["sensitivity"] = _sensitivity_tornado(sensitivity, base_irr)

    # DSCR profile
    if debt_schedule:
        target_dscr = (debt or {}).get("target_dscr", 1.3)
        charts["dscr_profile"] = _dscr_profile_chart(debt_schedule, target_dscr)

    return charts


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_html(context: dict) -> str:
    """Render the financial viability report HTML from Jinja2 template."""
    template = _jinja_env.get_template("financial_viability_base.html")
    return template.render(**context)


# ---------------------------------------------------------------------------
# HTML -> PDF (same engine as report_renderer.py)
# ---------------------------------------------------------------------------

async def _html_to_pdf(html_string: str) -> bytes:
    """Convert HTML string to PDF bytes via Playwright Chromium."""
    import tempfile
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(html_string)
        tmp.close()
        file_url = f"file://{tmp.name}"

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                raise RuntimeError("Chromium not installed. Run: playwright install chromium")
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60000)
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0.4in", "bottom": "0.6in",
                        "left": "0.4in", "right": "0.4in"},
            )
            await browser.close()
            return pdf_bytes
    finally:
        os.unlink(tmp.name)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def generate_financial_report(
    lat: float,
    lon: float,
    site_name: str = "Site",
    capacity_mw: float = 50.0,
    technology: str = "solar",
    # Solar default = merchant PPA mid (utils.solar_benchmarks, 2026)
    ppa_price: float = 45.0,
) -> bytes:
    """Full pipeline: appraisal -> sensitivity -> charts -> HTML -> PDF.

    Returns PDF bytes ready for streaming response.

    Args:
        lat: Site latitude (WGS84).
        lon: Site longitude (WGS84).
        site_name: Display name for the site.
        capacity_mw: Proposed installed capacity in MW.
        technology: One of 'solar', 'wind', 'offshore_wind', 'bess'.
        ppa_price: PPA price in £/MWh.

    Returns:
        PDF file as bytes.
    """
    log.info(
        "Generating financial report: %s, %.1f MW %s @ £%.0f/MWh",
        site_name, capacity_mw, technology, ppa_price,
    )

    # 1. Run investment appraisal models (async, in parallel)
    finance_task = _run_appraisal_async(
        "project_finance",
        capacity_mw=capacity_mw,
        technology=technology,
        ppa_price=ppa_price,
    )
    debt_task = _run_appraisal_async(
        "debt_structure",
        capacity_mw=capacity_mw,
        technology=technology,
        gearing=0.70,
        ppa_price=ppa_price,
    )
    equity_task = _run_appraisal_async(
        "equity_returns",
        capacity_mw=capacity_mw,
        technology=technology,
        gearing=0.70,
        ppa_price=ppa_price,
    )

    finance, debt, equity = await asyncio.gather(finance_task, debt_task, equity_task)

    if finance.get("error"):
        raise RuntimeError(f"Investment appraisal failed: {finance['error']}")

    log.info(
        "Appraisal complete: IRR=%.1f%%, NPV@8%%=£%s, LCOE=%.1f",
        float(finance.get("project_irr") or 0),
        _format_gbp(float(finance.get("npv_8pct") or 0)),
        float(finance.get("lcoe") or 0),
    )

    # 2. Run sensitivity analysis (CPU-bound, run in executor)
    loop = asyncio.get_running_loop()
    sensitivity = await loop.run_in_executor(
        None, _run_sensitivity, capacity_mw, technology, ppa_price,
    )

    # 3. Build full cashflow and debt schedule for charts
    full_cashflow = await loop.run_in_executor(None, _build_full_cashflow, finance)
    debt_schedule = (
        await loop.run_in_executor(None, _build_full_debt_schedule, debt)
        if debt and not debt.get("error") else []
    )

    # 4. Build CAPEX breakdown for chart
    total_capex = finance.get("total_capex", 0)
    tech_breakdown = CAPEX_BREAKDOWN.get(technology, CAPEX_BREAKDOWN["solar"])
    capex_items = []
    for component, frac in tech_breakdown:
        item_total = total_capex * frac
        capex_items.append({
            "component": component,
            "per_mw": item_total / capacity_mw if capacity_mw > 0 else 0,
            "total": item_total,
            "pct": frac * 100,
            "is_total": False,
        })

    # 5. Generate charts (CPU-bound, run in executor)
    charts = await loop.run_in_executor(
        None, _generate_all_charts,
        finance, debt, capex_items, full_cashflow, sensitivity, debt_schedule,
    )

    # GAP 2: Run DCFEvaluator (BOT-A) to produce DCF waterfall + DSCR timeline +
    # amortising debt schedule. This becomes the single source of truth for
    # NPV / terminal / FCFF / DSCR across IC pack, FVP and lender pack.
    wacc = float(finance.get("wacc") or 0.075)
    dcf_result, dcf_params = await loop.run_in_executor(
        None, _run_dcf_evaluator,
        capacity_mw, technology, ppa_price, 0.70, 0.06, 18, wacc, 0.25,
    )
    dcf_charts = await loop.run_in_executor(None, generate_dcf_charts, dcf_result, wacc)
    charts.update(dcf_charts)
    log.info(
        "DCF (BOT-A) NPV=%s  IRR=%s%%  min DSCR=%s  terminal=%s  charts=%s",
        _format_gbp(dcf_result.summary.get("npv", 0)),
        dcf_result.summary.get("irr_pct"),
        dcf_result.summary.get("min_dscr"),
        _format_gbp(dcf_result.summary.get("terminal_value", 0)),
        ", ".join(charts.keys()),
    )

    # 6. Build context and render HTML
    context = _build_context(
        finance=finance,
        debt=debt,
        equity=equity,
        site_name=site_name,
        capacity_mw=capacity_mw,
        technology=technology,
        lat=lat,
        lon=lon,
        ppa_price=ppa_price,
        sensitivity=sensitivity,
        charts=charts,
        dcf_result=dcf_result,
        dcf_params=dcf_params,
    )
    html = _render_html(context)

    # 7. Convert to PDF
    pdf_bytes = await _html_to_pdf(html)
    log.info("Financial report generated: %d bytes", len(pdf_bytes))

    return pdf_bytes
