"""
Princeps Grid Connection PDF Report Generator.

Generates a professional branded PDF report for grid connection assessments.
Uses the same Jinja2 + Playwright (Chromium headless) pipeline as the site
assessment report (report_renderer.py).

Sections:
  1. Cover Page -- branded with gold #D4A018 accent
  2. Executive Summary -- GO/CAUTION/NO-GO verdict, key metrics
  3. Site Location -- lat/lon, address, parcel area
  4. Grid Infrastructure -- nearest substations, voltage, headroom, RAG
  5. Connection Cost Estimate -- P10/P50/P90 breakdown by voltage option
  6. Queue Analysis -- projects ahead, wait time, pressure rating
  7. Power Flow Results -- Tier 2 voltage/thermal/N-1 (if available)
  8. Recommendations -- connection voltage, flexible connection, BESS
  9. Appendix -- data sources, methodology, disclaimers
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np
from jinja2 import Environment, FileSystemLoader

from utils.grid_connection_analyser import (
    assess_connection,
    estimate_connection_cost,
    tier2_power_flow,
    CABLE_COST_PER_KM,
    SWITCHGEAR_COST,
    TRANSFORMER_COST,
)
from utils.uk_energy_assumptions import (
    GRID_CONNECTION_COSTS_GBP_KM,
    GRID_CONNECTION_FIXED,
    BESS,
)

log = logging.getLogger("princeps.report_grid_connection")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "report"

# Brand palette -- gold accent for grid connection reports
BRAND = {
    "gold": "#D4A018",
    "gold_light": "#E8C54A",
    "gold_dark": "#B88B0E",
    "primary": "#0f62fe",
    "primary_light": "#4589ff",
    "primary_dark": "#0043ce",
    "dark": "#1a1a2e",
    "green": "#24a148",
    "green_light": "#42be65",
    "red": "#da1e28",
    "red_light": "#fa4d56",
    "amber": "#f1c21b",
    "amber_light": "#f7d84e",
    "grey": "#697077",
    "grey_light": "#a8a8a8",
    "light": "#f4f4f4",
    "white": "#ffffff",
}

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _fig_to_b64(fig: plt.Figure, dpi: int = 150) -> str:
    """Render matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=dpi, bbox_inches="tight",
        facecolor=BRAND["white"], edgecolor="none",
    )
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    """Apply Princeps chart styling."""
    fig.patch.set_facecolor(BRAND["white"])
    ax.set_facecolor(BRAND["white"])
    ax.tick_params(labelsize=8, colors=BRAND["dark"])
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(BRAND["grey_light"])
    ax.spines["left"].set_color(BRAND["grey_light"])


def _fmt_gbp(value: float | int | None) -> str:
    """Format a GBP value with comma separators."""
    if value is None:
        return "N/A"
    return f"\u00a3{value:,.0f}"


def _fmt_gbp_k(value: float | int | None) -> str:
    """Format GBP value in thousands."""
    if value is None:
        return "N/A"
    return f"\u00a3{value / 1000:,.0f}k"


def _rag_class(rag: str | None) -> str:
    """Return CSS class suffix for RAG status."""
    if not rag:
        return "grey"
    r = rag.lower()
    if r == "green":
        return "green"
    if r in ("amber", "yellow"):
        return "amber"
    if r == "red":
        return "red"
    return "grey"


def _queue_pressure(queue: dict) -> str:
    """Rate queue pressure as LOW/MEDIUM/HIGH/CRITICAL."""
    queued_mw = queue.get("ecr_queued_mw", 0)
    queued_count = queue.get("ecr_queued", 0)
    tec_mw = queue.get("tec_mw", 0)

    total_mw = queued_mw + tec_mw
    if total_mw > 200 or queued_count > 20:
        return "CRITICAL"
    if total_mw > 100 or queued_count > 10:
        return "HIGH"
    if total_mw > 30 or queued_count > 5:
        return "MEDIUM"
    return "LOW"


def _estimated_wait_months(queue: dict, capacity_mw: float) -> int:
    """Rough estimate of queue wait time in months."""
    queued = queue.get("ecr_queued", 0)
    queued_mw = queue.get("ecr_queued_mw", 0)
    # Heuristic: ~3 months per queued project + scale factor
    base = queued * 3
    if queued_mw > 50:
        base += int((queued_mw - 50) * 0.2)
    if capacity_mw > 50:
        base += 6  # Transmission review adds time
    return max(6, min(base, 48))


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def _cost_breakdown_chart(breakdown: dict) -> str:
    """Horizontal bar chart of cost components."""
    items = [
        ("Cable", breakdown.get("cable", 0)),
        ("Switchgear", breakdown.get("switchgear", 0)),
        ("Transformer", breakdown.get("transformer", 0)),
        ("DNO Fees", breakdown.get("dno_fees", 0)),
        ("Protection & Metering", breakdown.get("protection_metering", 0)),
        ("Civils & Wayleaves", breakdown.get("civils_wayleaves", 0)),
        ("Reinforcement", breakdown.get("reinforcement_estimate", 0)),
    ]
    # Filter out zero items
    items = [(l, v) for l, v in items if v > 0]
    if not items:
        return ""

    labels, values = zip(*items)
    fig, ax = plt.subplots(figsize=(7, max(2.5, len(items) * 0.5)))
    _apply_style(ax, fig)

    y = np.arange(len(labels))
    colours = [BRAND["gold"] if v == max(values) else BRAND["primary"] for v in values]
    ax.barh(y, [v / 1000 for v in values], color=colours, height=0.55,
            edgecolor="none", zorder=2)

    for i, v in enumerate(values):
        ax.text(v / 1000 + max(values) / 1000 * 0.02, i,
                f"\u00a3{v / 1000:,.0f}k", va="center", fontsize=8,
                fontweight="bold", color=BRAND["dark"])

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9, color=BRAND["dark"])
    ax.invert_yaxis()
    ax.set_xlabel("Cost (\u00a3 thousands)", fontsize=9, color=BRAND["dark"])
    ax.grid(axis="x", alpha=0.15, linewidth=0.4)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _voltage_options_chart(options: list[dict]) -> str:
    """Grouped bar chart comparing voltage connection options."""
    if not options:
        return ""

    labels = [f"{o['voltage_kv']} kV" for o in options]
    p10 = [o["cost_gbp"]["p10"] / 1_000_000 for o in options]
    p50 = [o["cost_gbp"]["p50"] / 1_000_000 for o in options]
    p90 = [o["cost_gbp"]["p90"] / 1_000_000 for o in options]

    x = np.arange(len(labels))
    w = 0.25

    fig, ax = plt.subplots(figsize=(7, 3.5))
    _apply_style(ax, fig)

    ax.bar(x - w, p10, w, label="P10", color=BRAND["green"], alpha=0.8)
    ax.bar(x, p50, w, label="P50", color=BRAND["gold"], alpha=0.9)
    ax.bar(x + w, p90, w, label="P90", color=BRAND["red"], alpha=0.8)

    for i in range(len(labels)):
        ax.text(i, p50[i] + max(p90) * 0.02, f"\u00a3{p50[i]:.1f}M",
                ha="center", va="bottom", fontsize=8, fontweight="bold",
                color=BRAND["dark"])

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10, fontweight="600")
    ax.set_ylabel("Cost (\u00a3 million)", fontsize=9, color=BRAND["dark"])
    ax.legend(fontsize=8, framealpha=0.9, edgecolor="none")
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _candidate_ranking_chart(candidates: list[dict]) -> str:
    """Lollipop chart ranking candidate substations by suitability score."""
    if not candidates:
        return ""

    subs = candidates[:6]
    names = [c.get("name", "Unknown")[:28] for c in subs]
    scores = [c.get("suitability_score", 0) for c in subs]
    dists = [c.get("distance_km", 0) for c in subs]

    fig, ax = plt.subplots(figsize=(7, max(2.5, len(subs) * 0.55)))
    _apply_style(ax, fig)

    y = np.arange(len(names))
    colours = [
        BRAND["green"] if s >= 70 else BRAND["amber"] if s >= 40 else BRAND["red"]
        for s in scores
    ]

    for i, (s, c) in enumerate(zip(scores, colours)):
        ax.hlines(y=i, xmin=0, xmax=s, color=c, linewidth=2, zorder=2)
    ax.scatter(scores, y, color=colours, s=80, zorder=3,
               edgecolors="white", linewidths=1.2)

    for i, (s, d) in enumerate(zip(scores, dists)):
        label = f"{s}/100  ({d:.1f} km)"
        ax.text(s + 2, i, label, va="center", fontsize=8, color=BRAND["dark"])

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9, color=BRAND["dark"])
    ax.invert_yaxis()
    ax.set_xlim(0, 110)
    ax.set_xlabel("Suitability Score", fontsize=9, color=BRAND["dark"])
    ax.axvline(x=70, color=BRAND["green"], lw=0.6, ls=":", alpha=0.5)
    ax.axvline(x=40, color=BRAND["red"], lw=0.6, ls=":", alpha=0.5)
    ax.grid(axis="x", alpha=0.15, linewidth=0.4)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["green"],
               markersize=7, label="GO (\u226570)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["amber"],
               markersize=7, label="CAUTION (40-69)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["red"],
               markersize=7, label="NO-GO (<40)"),
    ], loc="lower right", fontsize=7, framealpha=0.9, edgecolor="none")

    fig.tight_layout()
    return _fig_to_b64(fig)


def _power_flow_chart(pf_results: dict) -> str:
    """Chart voltage deviations and thermal loading from power flow."""
    bus_results = pf_results.get("bus_results", [])
    line_results = pf_results.get("line_results", [])
    if not bus_results and not line_results:
        return ""

    fig, axes = plt.subplots(1, 2, figsize=(7, 3.2))
    ax1, ax2 = axes
    _apply_style(ax1, fig)
    _apply_style(ax2, fig)

    # Voltage deviations
    if bus_results:
        bus_names = [b.get("name", f"Bus {i}")[:15] for i, b in enumerate(bus_results[:8])]
        voltages = [b.get("vm_pu", 1.0) for b in bus_results[:8]]
        x = np.arange(len(bus_names))
        colours = [
            BRAND["green"] if 0.94 <= v <= 1.06
            else BRAND["amber"] if 0.92 <= v <= 1.08
            else BRAND["red"]
            for v in voltages
        ]
        ax1.bar(x, voltages, color=colours, width=0.55, zorder=2)
        ax1.axhline(y=1.06, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6, label="+6%")
        ax1.axhline(y=0.94, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6, label="-6%")
        ax1.axhline(y=1.0, color=BRAND["grey"], lw=0.5, ls=":", alpha=0.4)
        ax1.set_xticks(x)
        ax1.set_xticklabels(bus_names, fontsize=7, rotation=45, ha="right")
        ax1.set_ylabel("Voltage (p.u.)", fontsize=9, color=BRAND["dark"])
        ax1.set_title("Bus Voltages", fontsize=10, fontweight="600", pad=8)
        ax1.set_ylim(0.90, 1.12)
    else:
        ax1.text(0.5, 0.5, "No bus data", transform=ax1.transAxes,
                 ha="center", va="center", color=BRAND["grey"])

    # Thermal loading
    if line_results:
        line_names = [l.get("name", f"Line {i}")[:15] for i, l in enumerate(line_results[:8])]
        loadings = [l.get("loading_pct", 0) for l in line_results[:8]]
        x2 = np.arange(len(line_names))
        colours2 = [
            BRAND["green"] if ld <= 80 else BRAND["amber"] if ld <= 100 else BRAND["red"]
            for ld in loadings
        ]
        ax2.barh(x2, loadings, color=colours2, height=0.55, zorder=2)
        ax2.axvline(x=100, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6, label="100%")
        ax2.axvline(x=80, color=BRAND["amber"], lw=0.6, ls=":", alpha=0.5, label="80%")
        ax2.set_yticks(x2)
        ax2.set_yticklabels(line_names, fontsize=7)
        ax2.set_xlabel("Loading (%)", fontsize=9, color=BRAND["dark"])
        ax2.set_title("Thermal Loading", fontsize=10, fontweight="600", pad=8)
        ax2.invert_yaxis()
    else:
        ax2.text(0.5, 0.5, "No line data", transform=ax2.transAxes,
                 ha="center", va="center", color=BRAND["grey"])

    fig.tight_layout(w_pad=3)
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Generate all charts
# ---------------------------------------------------------------------------

def generate_charts(report_data: dict) -> dict[str, str]:
    """Generate all charts as base64 PNG strings."""
    charts: dict[str, str] = {}

    cost_est = report_data.get("cost_estimate")
    if cost_est and cost_est.get("breakdown"):
        c = _cost_breakdown_chart(cost_est["breakdown"])
        if c:
            charts["cost_breakdown"] = c

    voltage_options = report_data.get("voltage_options", [])
    if voltage_options:
        c = _voltage_options_chart(voltage_options)
        if c:
            charts["voltage_options"] = c

    candidates = report_data.get("candidates", [])
    if candidates:
        c = _candidate_ranking_chart(candidates)
        if c:
            charts["candidate_ranking"] = c

    pf = report_data.get("power_flow")
    if pf and pf.get("success"):
        c = _power_flow_chart(pf)
        if c:
            charts["power_flow"] = c

    return charts


# ---------------------------------------------------------------------------
# Compute voltage option costs
# ---------------------------------------------------------------------------

def compute_voltage_options(
    distance_km: float,
    capacity_mw: float,
) -> list[dict]:
    """Compute P10/P50/P90 cost estimates for 11kV, 33kV, and 132kV options."""
    options = []
    for voltage_kv in (11, 33, 132):
        est = estimate_connection_cost(distance_km, capacity_mw, voltage_kv)
        est["voltage_kv"] = voltage_kv
        options.append(est)
    return options


# ---------------------------------------------------------------------------
# Build recommendations
# ---------------------------------------------------------------------------

def build_recommendations(
    report_data: dict,
    capacity_mw: float,
) -> list[dict]:
    """Generate actionable recommendations based on grid assessment data."""
    recs: list[dict] = []
    best = report_data.get("best_candidate")
    verdict = report_data.get("verdict", "CAUTION")

    # Recommended connection voltage
    if best:
        voltage = best.get("voltage_kv")
        headroom = best.get("gen_headroom_mw")
        distance = best.get("distance_km", 0)

        if capacity_mw <= 1 and voltage and voltage <= 11:
            rec_v = "11 kV"
        elif capacity_mw <= 10:
            rec_v = "33 kV"
        elif capacity_mw <= 50:
            rec_v = "66 kV" if distance < 5 else "132 kV"
        else:
            rec_v = "132 kV"

        recs.append({
            "title": "Recommended Connection Voltage",
            "detail": (
                f"For {capacity_mw:.1f} MW at {distance:.1f} km distance, a {rec_v} connection "
                f"is recommended. This balances cable cost, electrical losses, and DNO "
                f"acceptance probability."
            ),
            "priority": "HIGH",
        })

        # Flexible connection
        if headroom is not None and headroom < capacity_mw:
            shortfall = capacity_mw - headroom
            recs.append({
                "title": "Flexible Connection (ANM)",
                "detail": (
                    f"Headroom shortfall of {shortfall:.1f} MW identified. A flexible "
                    f"(Active Network Management) connection could secure access sooner "
                    f"at reduced cost, accepting curtailment during peak periods. "
                    f"Typical curtailment: 2-8% of annual generation."
                ),
                "priority": "HIGH",
            })

        # BESS co-location
        if capacity_mw >= 5:
            bess_mw = round(capacity_mw * 0.25, 1)
            bess_mwh = bess_mw * BESS["typical_duration_hrs"]
            recs.append({
                "title": "BESS Co-location",
                "detail": (
                    f"Co-locating {bess_mw} MW / {bess_mwh:.0f} MWh battery storage can "
                    f"reduce peak export, improve connection offer terms, and unlock "
                    f"additional revenue streams (frequency response, wholesale arbitrage). "
                    f"Estimated BESS CAPEX: {_fmt_gbp(bess_mw * 1000 * (BESS['capex_gbp_kw'] + BESS['capex_gbp_kwh'] * BESS['typical_duration_hrs']))}."
                ),
                "priority": "MEDIUM",
            })

    # Queue strategy
    queue_data = _get_queue_summary(report_data)
    if queue_data.get("total_queued_mw", 0) > 50:
        recs.append({
            "title": "Queue Management Strategy",
            "detail": (
                f"Significant queue pressure ({queue_data['total_queued_mw']:.0f} MW queued). "
                f"Consider early DNO pre-application engagement, alternative connection "
                f"points, or queue acceleration mechanisms (Ofgem queue reforms 2025)."
            ),
            "priority": "HIGH",
        })

    # DNO pre-application
    if verdict in ("CAUTION", "NO-GO"):
        recs.append({
            "title": "DNO Pre-application Study",
            "detail": (
                "Submit a formal pre-application enquiry to the DNO to confirm "
                "connection feasibility, identify reinforcement requirements, and "
                "receive an indicative cost and timeline before committing to full "
                "application (typically 45 working days, cost approx. "
                f"{_fmt_gbp(10_000 if capacity_mw <= 10 else 30_000)})."
            ),
            "priority": "HIGH" if verdict == "NO-GO" else "MEDIUM",
        })

    return recs


def _get_queue_summary(report_data: dict) -> dict:
    """Summarise queue data across all candidates."""
    total_queued_mw = 0.0
    total_queued_count = 0
    for c in report_data.get("candidates", []):
        q = c.get("queue", {})
        total_queued_mw += q.get("ecr_queued_mw", 0)
        total_queued_count += q.get("ecr_queued", 0)
    return {
        "total_queued_mw": total_queued_mw,
        "total_queued_count": total_queued_count,
    }


# ---------------------------------------------------------------------------
# Aggregate report data
# ---------------------------------------------------------------------------

async def aggregate_grid_connection_data(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float,
    site_name: str | None = None,
    technology: str = "solar",
    run_power_flow: bool = False,
) -> dict[str, Any]:
    """
    Collect all grid connection data for report generation.

    Calls assess_connection(), estimate_connection_cost() for multiple voltage
    options, and optionally tier2_power_flow().
    """
    site_label = site_name or f"Site {lat:.4f}, {lon:.4f}"
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Tier 1: data-driven assessment
    assessment = await assess_connection(
        conn, lat, lon, capacity_mw, technology,
    )

    # Compute voltage option costs
    best = assessment.get("best_candidate")
    distance_km = best["distance_km"] if best else 5.0
    voltage_options = compute_voltage_options(distance_km, capacity_mw)

    # Queue analysis
    queue_summary = _get_queue_summary(assessment)
    best_queue = best.get("queue", {}) if best else {}
    queue_pressure = _queue_pressure(best_queue)
    wait_months = _estimated_wait_months(best_queue, capacity_mw)

    # Optional Tier 2 power flow
    power_flow = None
    if run_power_flow:
        try:
            power_flow = await tier2_power_flow(
                conn, lat, lon, capacity_mw, technology,
            )
        except Exception as e:
            log.warning("Tier 2 power flow failed: %s", e)
            power_flow = {"success": False, "error": str(e)}

    # Build recommendations
    report_data = {
        **assessment,
        "voltage_options": voltage_options,
        "power_flow": power_flow,
    }
    recommendations = build_recommendations(report_data, capacity_mw)

    return {
        "site_name": site_label,
        "generated_at": generated_at,
        "lat": lat,
        "lon": lon,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "verdict": assessment["verdict"],
        "confidence": assessment["confidence"],
        "summary": assessment["summary"],
        "dno_area": assessment.get("dno_area"),
        "candidates": assessment.get("candidates", []),
        "best_candidate": best,
        "cost_estimate": assessment.get("cost_estimate"),
        "voltage_options": voltage_options,
        "risks": assessment.get("risks", []),
        "queue_summary": {
            **queue_summary,
            "pressure": queue_pressure,
            "estimated_wait_months": wait_months,
            "best_queue": best_queue,
        },
        "power_flow": power_flow,
        "recommendations": recommendations,
        "tier": assessment.get("tier", "data"),
        "elapsed_s": assessment.get("elapsed_s", 0),
    }


# ---------------------------------------------------------------------------
# Render HTML
# ---------------------------------------------------------------------------

def render_grid_connection_html(
    report_data: dict,
    charts: dict[str, str],
) -> str:
    """Render the full grid connection report HTML."""
    ctx = {
        "r": report_data,
        "charts": charts,
        "brand": BRAND,
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "fmt_gbp": _fmt_gbp,
        "fmt_gbp_k": _fmt_gbp_k,
        "rag_class": _rag_class,
    }
    try:
        template = _jinja_env.get_template("grid_connection_report.html")
        return template.render(**ctx)
    except Exception:
        log.exception("Grid connection report template render failed")
        raise


# ---------------------------------------------------------------------------
# HTML -> PDF (reuse report_renderer pipeline)
# ---------------------------------------------------------------------------

async def html_to_pdf(html_string: str) -> bytes:
    """Convert HTML string to PDF bytes via Playwright Chromium."""
    import tempfile
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8",
    )
    try:
        tmp.write(html_string)
        tmp.close()
        file_url = f"file://{tmp.name}"

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                raise RuntimeError(
                    "Chromium not installed. Run: playwright install chromium"
                )
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60000)
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={
                    "top": "0.4in",
                    "bottom": "0.6in",
                    "left": "0.4in",
                    "right": "0.4in",
                },
            )
            await browser.close()
            return pdf_bytes
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def generate_grid_connection_report(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float = 50.0,
    site_name: str | None = None,
    technology: str = "solar",
    run_power_flow: bool = False,
) -> bytes:
    """
    Full pipeline: aggregate data -> generate charts -> render HTML -> convert PDF.

    Args:
        conn: asyncpg connection (from pool.acquire())
        lat: Site latitude (WGS84)
        lon: Site longitude (WGS84)
        capacity_mw: Proposed generation capacity
        site_name: Human-readable site name
        technology: solar | wind | bess
        run_power_flow: Whether to run Tier 2 pandapower analysis

    Returns:
        PDF bytes
    """
    log.info(
        "Generating grid connection report for %s (%.4f, %.4f) @ %.1f MW",
        site_name or "site", lat, lon, capacity_mw,
    )

    report_data = await aggregate_grid_connection_data(
        conn, lat, lon, capacity_mw, site_name, technology, run_power_flow,
    )
    log.info(
        "Grid data aggregated: verdict=%s, %d candidates, confidence=%.0f%%",
        report_data["verdict"],
        len(report_data.get("candidates", [])),
        report_data["confidence"] * 100,
    )

    loop = asyncio.get_running_loop()
    charts = await loop.run_in_executor(None, generate_charts, report_data)
    log.info("Charts generated: %s", ", ".join(charts.keys()))

    html = render_grid_connection_html(report_data, charts)
    pdf_bytes = await html_to_pdf(html)
    log.info("Grid connection report generated: %d bytes", len(pdf_bytes))
    return pdf_bytes
