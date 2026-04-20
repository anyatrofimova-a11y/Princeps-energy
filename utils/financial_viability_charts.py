"""
utils/financial_viability_charts — chart rendering for the Financial
Viability Pack.

Given a DCFResult (from utils.dcf_evaluator.DCFEvaluator.evaluate()),
produces three matplotlib charts as base64 PNGs suitable for inlining
into the Jinja2/Playwright template:

  1. DCF waterfall:   FCFF bars (Y1..YN) → terminal-value PV bar → NPV
     bar. Classic infra-style waterfall with positive / negative steps
     coloured distinctly and the cumulative NPV label on the final bar.
  2. DSCR timeline:   year-by-year DSCR line with PRA-style covenant
     threshold bands (default 1.20x lower, 1.30x comfort). Years where
     a covenant breaches (DSCRmin, LLCRmin, PLCRmin, ICRmin, gearing)
     are highlighted amber/red.
  3. Cashflow stack:  revenue (green) minus opex + tax (red) minus
     debt service (navy) per year, FCFE line overlay.

Regulatory framing:
  - RICS Financial Viability in Planning 1st ed. (2021) requires visible
    sensitivity + residual-value disclosure. The waterfall + terminal bar
    provides residual-value visibility.
  - NPPF Annex 2 refers to "comparable developments" and "residual land
    value" — the DCF waterfall terminal bar is the residual equivalent.
  - Bank of England PRA SS31/15 expects DSCR evidence across the life
    of the loan — the DSCR timeline chart covers this.

All figures rendered in £m for IC / bank consumption.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from utils.dcf_evaluator import DCFResult

log = logging.getLogger("princeps.financial_viability_charts")

# Brand palette — matches financial_viability_base.html
GOLD = "#D4A018"
DARK = "#1a1a2e"
NAVY = "#16213e"
GREEN = "#24a148"
GREEN_LIGHT = "#42be65"
RED = "#da1e28"
AMBER = "#f1c21b"
GREY = "#697077"
GREY_LIGHT = "#a8a8a8"
WHITE = "#ffffff"
PRIMARY = "#0f62fe"


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _fig_to_b64(fig: plt.Figure, dpi: int = 150) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=WHITE, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    ax.tick_params(labelsize=8, colors=DARK)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(GREY_LIGHT)
    ax.spines["left"].set_color(GREY_LIGHT)


def _fmt_gbp_m(v: float) -> str:
    """Format for axis labels — £m."""
    if abs(v) >= 1e6:
        return f"£{v/1e6:.1f}m"
    if abs(v) >= 1e3:
        return f"£{v/1e3:.0f}k"
    return f"£{v:.0f}"


# ──────────────────────────────────────────────────────────────────────────
# Chart 1: DCF waterfall — FCFF → terminal → NPV
# ──────────────────────────────────────────────────────────────────────────

def dcf_waterfall_chart(result: DCFResult, wacc: float) -> str:
    """Waterfall bars: −CAPEX, FCFF PVs per year, terminal PV, NPV total.

    The NPV bar is the cumulative check line; every intermediate bar
    sits on its running total. Colour: green for positive, red for
    negative, gold for terminal and NPV.
    """
    life = len(result.fcff)
    if life == 0:
        return ""

    # Discount each FCFF back to t=0
    pv_fcff = [result.fcff[i] / ((1 + wacc) ** (i + 1)) for i in range(life)]
    pv_terminal = result.terminal_value / ((1 + wacc) ** life) if result.terminal_value else 0.0
    capex = result.summary.get("capex", 0.0)

    # For readability on a 25-year project, group by 5-year blocks.
    block_size = max(1, life // 5)
    block_labels: list[str] = []
    block_values: list[float] = []
    for i in range(0, life, block_size):
        chunk = pv_fcff[i:i + block_size]
        if not chunk:
            continue
        y_start = i + 1
        y_end = min(i + block_size, life)
        block_labels.append(f"Y{y_start}-{y_end}" if y_end > y_start else f"Y{y_start}")
        block_values.append(sum(chunk))

    labels = ["−CAPEX", *block_labels, "Terminal PV", "NPV"]
    values = [-abs(capex), *block_values, pv_terminal, 0.0]  # NPV bar is a total marker

    # Compute cumulative running total (used for waterfall stacking)
    running = 0.0
    bottoms: list[float] = []
    heights: list[float] = []
    colours: list[str] = []
    for i, v in enumerate(values):
        if i == 0:  # CAPEX (negative)
            bottoms.append(v)
            heights.append(-v)  # height drawn downward → flip for positive render
            colours.append(RED)
            running += v
        elif i == len(values) - 1:  # NPV total
            bottoms.append(0.0)
            heights.append(running)
            colours.append(GOLD)
        else:
            if v >= 0:
                bottoms.append(running)
                heights.append(v)
                colours.append(GREEN if i < len(values) - 2 else GOLD)
            else:
                bottoms.append(running + v)
                heights.append(-v)
                colours.append(RED)
            running += v

    fig, ax = plt.subplots(figsize=(9, 4.2))
    _apply_style(ax, fig)
    x = np.arange(len(labels))
    # Draw each bar using (bottom, height)
    for i, (b, h, c) in enumerate(zip(bottoms, heights, colours)):
        if i == 0:  # CAPEX — draw from 0 downward
            ax.bar(x[i], values[i], 0.55, color=c, edgecolor=DARK, linewidth=0.5, zorder=3)
        elif i == len(labels) - 1:  # NPV total
            ax.bar(x[i], h, 0.6, bottom=0, color=c, edgecolor=DARK, linewidth=0.8, zorder=3, hatch="//")
        else:
            ax.bar(x[i], h, 0.55, bottom=b, color=c, edgecolor=DARK, linewidth=0.5, zorder=3,
                   alpha=0.85 if c != GOLD else 1.0)

    # Connectors between bars
    for i in range(len(labels) - 1):
        top_i = bottoms[i] + heights[i] if i > 0 else values[0]
        if i == 0:
            top_i = values[0]  # ending at -capex
        start_x = x[i] + 0.275
        end_x = x[i + 1] - 0.275
        ax.plot([start_x, end_x], [top_i, top_i],
                color=GREY, linestyle="--", linewidth=0.7, zorder=2)

    ax.axhline(y=0, color=GREY_LIGHT, linewidth=0.6, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5, rotation=20, ha="right", color=DARK)
    ax.set_ylabel("£ (nominal)", fontsize=9, color=DARK)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _fmt_gbp_m(v)))
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)

    # Annotate NPV bar
    npv = result.summary.get("npv", 0.0)
    ax.annotate(
        _fmt_gbp_m(npv),
        xy=(x[-1], npv), xytext=(x[-1], npv + (abs(npv) * 0.05 if npv != 0 else 1e5)),
        ha="center", fontsize=9.5, fontweight="bold", color=GOLD if npv > 0 else RED,
    )
    ax.set_title(
        f"DCF Waterfall  —  WACC {wacc*100:.1f}%  —  Terminal (Gordon, g={0.0:.1f}%)",
        fontsize=10, color=DARK, pad=8,
    )
    fig.tight_layout()
    return _fig_to_b64(fig)


# ──────────────────────────────────────────────────────────────────────────
# Chart 2: DSCR year-by-year timeline
# ──────────────────────────────────────────────────────────────────────────

def dscr_timeline_chart(result: DCFResult, dscr_floor: float = 1.20, dscr_comfort: float = 1.30) -> str:
    """Year-by-year DSCR line with lender covenant bands.

    Shaded bands: red below `dscr_floor`, amber between floor and
    comfort, green above comfort. Points coloured by breach status.
    """
    if not result.covenants:
        return ""
    years = [c["year"] for c in result.covenants]
    dscrs = [c["dscr"] if c["dscr"] is not None else np.nan for c in result.covenants]
    breach_statuses = [c["status"] for c in result.covenants]

    fig, ax = plt.subplots(figsize=(9, 3.6))
    _apply_style(ax, fig)
    x = np.arange(len(years))

    # Threshold bands (draw behind line)
    ymax = max((d for d in dscrs if d and d == d), default=2.0) * 1.15
    ymax = max(ymax, dscr_comfort * 1.2)
    ymin = min(min((d for d in dscrs if d and d == d), default=1.0), dscr_floor) * 0.85
    ymin = max(0.0, ymin)
    ax.axhspan(0, dscr_floor, color=RED, alpha=0.10, zorder=1)
    ax.axhspan(dscr_floor, dscr_comfort, color=AMBER, alpha=0.10, zorder=1)
    ax.axhspan(dscr_comfort, ymax, color=GREEN, alpha=0.08, zorder=1)

    ax.plot(x, dscrs, color=DARK, linewidth=1.8, zorder=3, label="DSCR")

    # Point colours by status
    for i, (xi, d, s) in enumerate(zip(x, dscrs, breach_statuses)):
        if d != d:  # NaN
            continue
        col = RED if s == "breach" else (AMBER if d < dscr_comfort else GREEN)
        ax.scatter([xi], [d], color=col, s=40, zorder=4,
                   edgecolors=WHITE, linewidths=0.8)

    # Threshold reference lines
    ax.axhline(y=dscr_floor, color=RED, linewidth=1.0, linestyle="--", alpha=0.7,
               label=f"PRA floor ({dscr_floor:.2f}x)")
    ax.axhline(y=dscr_comfort, color=GREEN, linewidth=1.0, linestyle="--", alpha=0.7,
               label=f"Comfort ({dscr_comfort:.2f}x)")

    ax.set_xticks(x[::max(1, len(years)//10)])
    ax.set_xticklabels([str(y) for y in years[::max(1, len(years)//10)]], fontsize=8)
    ax.set_xlabel("Project Year", fontsize=9, color=DARK)
    ax.set_ylabel("DSCR (x)", fontsize=9, color=DARK)
    ax.set_ylim(ymin, ymax)
    ax.legend(fontsize=8, loc="upper right", framealpha=0.9, edgecolor="none")
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    ax.set_title("DSCR Timeline  —  PRA SS31/15 Covenant View", fontsize=10, color=DARK, pad=8)
    fig.tight_layout()
    return _fig_to_b64(fig)


# ──────────────────────────────────────────────────────────────────────────
# Chart 3: Cashflow stack — revenue / opex / tax / debt service / FCFE
# ──────────────────────────────────────────────────────────────────────────

def cashflow_stack_chart(result: DCFResult) -> str:
    """Stacked bar (rev / opex / tax / debt service) with FCFE line overlay."""
    if not result.cashflows:
        return ""

    years = [c["year"] for c in result.cashflows]
    rev = [c["revenue"] for c in result.cashflows]
    opex = [c["opex"] for c in result.cashflows]
    tax = [c["tax"] for c in result.cashflows]
    ds = [c["debt_service"] for c in result.cashflows]
    fcfe = [c["fcfe"] for c in result.cashflows]

    fig, ax = plt.subplots(figsize=(9, 3.8))
    _apply_style(ax, fig)
    x = np.arange(len(years))
    w = 0.6

    ax.bar(x, rev, w, color=GREEN, alpha=0.85, label="Revenue", zorder=2)
    ax.bar(x, [-o for o in opex], w, color=RED, alpha=0.55, label="OPEX", zorder=2)
    ax.bar(x, [-t for t in tax], w, bottom=[-o for o in opex], color=AMBER, alpha=0.65,
           label="Tax", zorder=2)
    ax.bar(x, [-d for d in ds], w, bottom=[-(o + t) for o, t in zip(opex, tax)],
           color=NAVY, alpha=0.9, label="Debt service", zorder=2)

    # FCFE line overlay (on twin axis to show in £m explicitly)
    ax.plot(x, fcfe, color=GOLD, linewidth=2, marker="o", markersize=3,
            label="FCFE", zorder=4)

    ax.axhline(y=0, color=GREY_LIGHT, linewidth=0.6, zorder=1)
    ax.set_xticks(x[::max(1, len(years)//10)])
    ax.set_xticklabels([str(y) for y in years[::max(1, len(years)//10)]], fontsize=8)
    ax.set_xlabel("Project Year", fontsize=9, color=DARK)
    ax.set_ylabel("£ (nominal)", fontsize=9, color=DARK)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _fmt_gbp_m(v)))
    ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9, edgecolor="none", ncol=5)
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    ax.set_title("Cashflow Stack  —  Revenue ↓ OPEX ↓ Tax ↓ Debt Service  →  FCFE",
                 fontsize=10, color=DARK, pad=8)
    fig.tight_layout()
    return _fig_to_b64(fig)


# ──────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────

def generate_dcf_charts(result: DCFResult, wacc: float) -> dict[str, str]:
    """Return a dict of {chart_key: base64_png} for the Jinja2 template."""
    charts: dict[str, str] = {}
    try:
        charts["dcf_waterfall"] = dcf_waterfall_chart(result, wacc)
    except Exception as exc:  # pragma: no cover — never want a chart to fail the PDF
        log.warning("dcf_waterfall_chart failed: %s", exc)
        charts["dcf_waterfall"] = ""
    try:
        charts["dscr_timeline"] = dscr_timeline_chart(result)
    except Exception as exc:  # pragma: no cover
        log.warning("dscr_timeline_chart failed: %s", exc)
        charts["dscr_timeline"] = ""
    try:
        charts["cashflow_stack"] = cashflow_stack_chart(result)
    except Exception as exc:  # pragma: no cover
        log.warning("cashflow_stack_chart failed: %s", exc)
        charts["cashflow_stack"] = ""
    return charts


def build_amortising_schedule_rows(result: DCFResult) -> list[dict[str, Any]]:
    """Flatten DCFResult.covenants + cashflows into a single year-by-year
    amortising debt-schedule table row set (for the Jinja2 template).
    Each row has: year, opening balance, interest, principal, debt_service,
    closing balance, cfads, dscr, breaches.
    """
    rows: list[dict[str, Any]] = []
    for c in result.covenants:
        year = c["year"]
        principal = c.get("principal", 0) or 0
        interest = c.get("interest", 0) or 0
        opening = c.get("debt_outstanding", 0) or 0
        rows.append({
            "year": year,
            "opening_balance": opening,
            "interest": interest,
            "principal": principal,
            "debt_service": c.get("debt_service", 0),
            "closing_balance": max(0.0, opening - principal),
            "cfads": c.get("cfads", 0),
            "dscr": c.get("dscr"),
            "llcr": c.get("llcr"),
            "plcr": c.get("plcr"),
            "icr": c.get("icr"),
            "gearing": c.get("gearing"),
            "breaches": c.get("breaches") or [],
            "status": c.get("status", "ok"),
        })
    return rows
