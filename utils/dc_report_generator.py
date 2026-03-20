"""
dc_report_generator.py — Executive PDF report generator for DC site assessments.

Generates a comprehensive site assessment report for Google's team containing:
1. Executive summary (GO/CAUTION/NO-GO verdict, key metrics)
2. Site overview (map, coordinates, area, land use)
3. Power analysis (grid capacity, headroom, connection cost, timeline)
4. 24/7 CFE% assessment
5. Cooling analysis (PUE, free cooling, WUE, climate projections)
6. Connectivity (fiber routes, IXP proximity, latency)
7. Environmental (constraints, flood risk, BNG, water stress)
8. Financial (TCO 10-year, CapEx breakdown, incentives)
9. Regulatory (NSIP pathway, TM04+ gate, planning risk)
10. Risk matrix (5x5 grid)
11. Recommendation & next steps
"""

from __future__ import annotations

import asyncpg, logging, math, io, base64, tempfile, os, asyncio
from typing import Any
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np

log = logging.getLogger("princeps.dc_report")

# ---------------------------------------------------------------------------
# Princeps brand palette
# ---------------------------------------------------------------------------
BRAND = {
    "primary": "#0f62fe", "primary_light": "#4589ff", "primary_dark": "#0043ce",
    "dark": "#1a1a2e", "green": "#24a148", "green_light": "#42be65",
    "red": "#da1e28", "red_light": "#fa4d56", "amber": "#f1c21b",
    "amber_light": "#f7d84e", "grey": "#697077", "grey_light": "#a8a8a8",
    "light": "#f4f4f4", "white": "#ffffff",
}

# ---------------------------------------------------------------------------
# Default risk register
# ---------------------------------------------------------------------------
DC_RISKS = [
    {"risk": "Grid capacity insufficient", "likelihood": 2, "impact": 5, "category": "Power"},
    {"risk": "Connection timeline >36 months", "likelihood": 3, "impact": 4, "category": "Power"},
    {"risk": "Planning refusal", "likelihood": 2, "impact": 5, "category": "Planning"},
    {"risk": "Environmental objection", "likelihood": 3, "impact": 3, "category": "Environmental"},
    {"risk": "Water abstraction denied", "likelihood": 2, "impact": 3, "category": "Water"},
    {"risk": "Community opposition", "likelihood": 3, "impact": 3, "category": "Social"},
    {"risk": "Cost overrun >20%", "likelihood": 3, "impact": 3, "category": "Financial"},
    {"risk": "CFE target unachievable", "likelihood": 2, "impact": 4, "category": "Sustainability"},
    {"risk": "Flood risk materialises", "likelihood": 1, "impact": 5, "category": "Environmental"},
    {"risk": "Fibre connectivity delay", "likelihood": 2, "impact": 2, "category": "Connectivity"},
]

# Category colours for risk matrix
_RISK_CAT_COLOURS = {
    "Power": "#0f62fe", "Planning": "#9c27b0", "Environmental": "#009688",
    "Water": "#00bcd4", "Social": "#ff9800", "Financial": "#ff5722",
    "Sustainability": "#24a148", "Connectivity": "#795548",
}

# ---------------------------------------------------------------------------
# Dimension labels for 15-axis radar (mapped from dc_colocation_scorer + extras)
# ---------------------------------------------------------------------------
RADAR_DIMENSIONS = [
    "power_capacity", "grid_headroom", "cfe_score", "cooling_climate",
    "constraint_clear", "water_stress", "fibre_proximity", "ixp_proximity",
    "latency", "land_planning", "resilience", "connection_speed",
    "incentives", "regulatory_pathway", "community_acceptance",
]
RADAR_LABELS = [
    "Power\nCapacity", "Grid\nHeadroom", "CFE %", "Cooling\nClimate",
    "Constraint\nClear", "Water\nStress", "Fibre\nProximity", "IXP\nProximity",
    "Latency", "Land &\nPlanning", "Resilience", "Connection\nSpeed",
    "Incentives", "Regulatory\nPathway", "Community\nAcceptance",
]


# ===================================================================
# Helpers
# ===================================================================
def _fig_to_b64(fig: plt.Figure, dpi: int = 150) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=BRAND["white"], edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _apply_style(ax: plt.Axes, fig: plt.Figure) -> None:
    fig.patch.set_facecolor(BRAND["white"])
    ax.set_facecolor(BRAND["white"])
    ax.tick_params(labelsize=8, colors=BRAND["dark"])
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(BRAND["grey_light"])
    ax.spines["left"].set_color(BRAND["grey_light"])


def _score_colour(v: float) -> str:
    if v >= 70:
        return BRAND["green"]
    elif v >= 45:
        return BRAND["amber"]
    return BRAND["red"]


def _verdict_colour(verdict: str) -> str:
    return {"GO": BRAND["green"], "CAUTION": BRAND["amber"], "NO-GO": BRAND["red"]}.get(
        verdict, BRAND["grey"]
    )


def _fmt_gbp(val: float | None) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1_000_000:
        return f"\u00a3{val / 1_000_000:,.1f}M"
    if abs(val) >= 1_000:
        return f"\u00a3{val / 1_000:,.0f}k"
    return f"\u00a3{val:,.0f}"


# ===================================================================
# Chart generators
# ===================================================================
def _render_radar_chart(scores: dict, dimensions: list[str]) -> str:
    """Return base64-encoded PNG of 15-dimension radar chart."""
    # Extract scores for each dimension, default to 0
    labels = []
    values = []
    for i, dim in enumerate(dimensions):
        sc = scores.get(dim, {})
        val = sc.get("score", 0) if isinstance(sc, dict) else (sc if isinstance(sc, (int, float)) else 0)
        labels.append(RADAR_LABELS[i] if i < len(RADAR_LABELS) else dim.replace("_", "\n"))
        values.append(float(val))

    n = len(labels)
    if n == 0:
        return ""

    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    vc = values + values[:1]
    ac = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(6.5, 6.5), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(BRAND["white"])

    # Zone fills
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.fill_between(theta, 0, 40, alpha=0.04, color=BRAND["red"])
    ax.fill_between(theta, 40, 65, alpha=0.04, color=BRAND["amber"])
    ax.fill_between(theta, 65, 100, alpha=0.04, color=BRAND["green"])

    ax.fill(ac, vc, color=BRAND["primary"], alpha=0.12)
    ax.plot(ac, vc, color=BRAND["primary"], linewidth=2.0, solid_capstyle="round")

    for i, (a, v) in enumerate(zip(angles, values)):
        c = _score_colour(v)
        ax.scatter([a], [v], color=c, s=50, zorder=5, edgecolors="white", linewidths=1)
        off = 8 if v < 88 else -8
        ax.annotate(f"{v:.0f}", xy=(a, v), xytext=(0, off), textcoords="offset points",
                    ha="center", va="bottom" if v < 88 else "top",
                    fontsize=7, fontweight="bold", color=BRAND["dark"])

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, size=6.5, fontweight="600", color=BRAND["dark"],
                       linespacing=1.1)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], size=6, color=BRAND["grey"])
    ax.set_rlabel_position(22.5)
    ax.spines["polar"].set_color(BRAND["grey_light"])
    ax.spines["polar"].set_linewidth(0.5)
    ax.grid(color="#e0e0e0", linewidth=0.35)
    fig.tight_layout(pad=2.0)
    return _fig_to_b64(fig)


def _render_score_bars(scores: dict) -> str:
    """Return base64 PNG of horizontal score bars."""
    items = []
    for dim in RADAR_DIMENSIONS:
        sc = scores.get(dim)
        if sc is None:
            continue
        val = sc.get("score", 0) if isinstance(sc, dict) else (sc if isinstance(sc, (int, float)) else 0)
        label = dim.replace("_", " ").title()
        items.append((label, float(val)))

    if not items:
        return ""

    labels = [x[0] for x in items]
    values = [x[1] for x in items]
    colours = [_score_colour(v) for v in values]

    fig, ax = plt.subplots(figsize=(7.5, max(3.5, len(items) * 0.38)))
    _apply_style(ax, fig)
    y = np.arange(len(labels))
    ax.barh(y, [100] * len(labels), color="#f0f0f0", height=0.55, zorder=1)
    ax.barh(y, values, color=colours, height=0.55, zorder=2, edgecolor="none", alpha=0.85)
    ax.axvline(x=45, color=BRAND["red"], lw=0.7, ls="--", alpha=0.4, zorder=3)
    ax.axvline(x=70, color=BRAND["green"], lw=0.7, ls="--", alpha=0.4, zorder=3)

    for i, v in enumerate(values):
        ax.text(v + 1.5, i, f"{v:.0f}", va="center", fontsize=8, fontweight="bold",
                color=_score_colour(v), zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8, color=BRAND["dark"])
    ax.set_xlim(0, 110)
    ax.invert_yaxis()
    ax.tick_params(axis="x", bottom=False, labelbottom=False)
    ax.spines["bottom"].set_visible(False)
    ax.legend(handles=[
        mpatches.Patch(facecolor=BRAND["red"], alpha=0.4, label="NO-GO (<45)"),
        mpatches.Patch(facecolor=BRAND["amber"], alpha=0.4, label="CAUTION (45-69)"),
        mpatches.Patch(facecolor=BRAND["green"], alpha=0.4, label="GO (70+)"),
    ], loc="lower right", fontsize=6.5, framealpha=0.8, edgecolor="none")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_risk_matrix(risks: list[dict]) -> str:
    """Return base64 PNG of 5x5 risk matrix."""
    fig, ax = plt.subplots(figsize=(6, 5.5))
    fig.patch.set_facecolor(BRAND["white"])

    # Background heat-map
    matrix = np.zeros((5, 5))
    for i in range(5):
        for j in range(5):
            matrix[i][j] = (i + 1) * (j + 1)

    # Custom colour map: green -> amber -> red
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("risk", [
        "#d4edda", "#fff3cd", "#f8d7da", "#da1e28"
    ], N=25)
    ax.imshow(matrix, cmap=cmap, origin="lower", aspect="auto", alpha=0.35,
              extent=[-0.5, 4.5, -0.5, 4.5])

    # Grid lines
    for i in range(6):
        ax.axhline(y=i - 0.5, color="#cccccc", linewidth=0.5)
        ax.axvline(x=i - 0.5, color="#cccccc", linewidth=0.5)

    # Plot risks
    for r in risks:
        x = r["likelihood"] - 1
        y = r["impact"] - 1
        cat = r.get("category", "Other")
        color = _RISK_CAT_COLOURS.get(cat, BRAND["grey"])
        ax.scatter(x, y, s=120, color=color, edgecolors="white", linewidths=1.2, zorder=5)
        # Short label: first 18 chars
        label = r["risk"][:20]
        ax.annotate(label, (x, y), xytext=(5, 6), textcoords="offset points",
                    fontsize=5.5, color=BRAND["dark"], fontweight="500",
                    bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.85,
                              edgecolor="none"))

    ax.set_xticks(range(5))
    ax.set_xticklabels(["Very Low", "Low", "Medium", "High", "Very High"], fontsize=7,
                       color=BRAND["dark"])
    ax.set_yticks(range(5))
    ax.set_yticklabels(["Negligible", "Minor", "Moderate", "Major", "Critical"], fontsize=7,
                       color=BRAND["dark"])
    ax.set_xlabel("Likelihood", fontsize=9, fontweight="600", color=BRAND["dark"])
    ax.set_ylabel("Impact", fontsize=9, fontweight="600", color=BRAND["dark"])
    ax.set_title("Risk Matrix", fontsize=11, fontweight="bold", color=BRAND["dark"], pad=10)

    # Category legend
    handles = [mpatches.Patch(facecolor=c, label=cat)
               for cat, c in _RISK_CAT_COLOURS.items()
               if any(r.get("category") == cat for r in risks)]
    if handles:
        ax.legend(handles=handles, loc="upper left", fontsize=6, framealpha=0.9,
                  edgecolor="none", ncol=2)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_pue_projection(current_pue: float, future_pue: dict) -> str:
    """Return base64 PNG of PUE projection chart."""
    years = [2024]
    pues = [current_pue]
    for yr_str in sorted(future_pue.keys()):
        years.append(int(yr_str))
        pues.append(future_pue[yr_str])

    fig, ax = plt.subplots(figsize=(6, 3.5))
    _apply_style(ax, fig)

    ax.fill_between(years, [1.0] * len(years), pues, alpha=0.08, color=BRAND["primary"])
    ax.plot(years, pues, color=BRAND["primary"], linewidth=2.5, marker="o", markersize=7,
            markerfacecolor=BRAND["white"], markeredgecolor=BRAND["primary"],
            markeredgewidth=2, zorder=3)
    for yr, pue in zip(years, pues):
        ax.annotate(f"{pue:.2f}", (yr, pue), xytext=(0, 12), textcoords="offset points",
                    ha="center", fontsize=8, fontweight="bold", color=BRAND["dark"])

    # Reference lines
    ax.axhline(y=1.2, color=BRAND["green"], lw=0.7, ls=":", alpha=0.6, label="Target (1.20)")
    ax.axhline(y=1.4, color=BRAND["amber"], lw=0.7, ls=":", alpha=0.6, label="Industry avg (1.40)")

    ax.set_xlabel("Year", fontsize=9, color=BRAND["dark"])
    ax.set_ylabel("PUE", fontsize=9, color=BRAND["dark"])
    ax.set_ylim(1.0, max(max(pues) * 1.1, 1.5))
    ax.set_xlim(2022, max(years) + 2)
    ax.legend(fontsize=7, framealpha=0.9, edgecolor="none")
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_cfe_gauge(cfe_pct: float) -> str:
    """Return base64 PNG of CFE% gauge/dial chart."""
    fig, ax = plt.subplots(figsize=(3.5, 2.5), subplot_kw=dict(polar=False))
    fig.patch.set_facecolor(BRAND["white"])
    ax.set_aspect("equal")

    # Draw semi-circle gauge
    theta_bg = np.linspace(np.pi, 0, 200)
    r = 1.0
    # Background arc segments: red, amber, green
    segments = [
        (np.linspace(np.pi, np.pi * 0.667, 60), BRAND["red"], 0.15),
        (np.linspace(np.pi * 0.667, np.pi * 0.333, 60), BRAND["amber"], 0.15),
        (np.linspace(np.pi * 0.333, 0, 60), BRAND["green"], 0.15),
    ]
    for th, color, alpha in segments:
        x_outer = np.cos(th) * r
        y_outer = np.sin(th) * r
        x_inner = np.cos(th) * 0.65
        y_inner = np.sin(th) * 0.65
        ax.fill(np.concatenate([x_outer, x_inner[::-1]]),
                np.concatenate([y_outer, y_inner[::-1]]),
                color=color, alpha=alpha)

    # Needle
    cfe_clamped = max(0, min(100, cfe_pct))
    needle_angle = np.pi * (1 - cfe_clamped / 100)
    ax.plot([0, np.cos(needle_angle) * 0.8], [0, np.sin(needle_angle) * 0.8],
            color=BRAND["dark"], linewidth=2.5, solid_capstyle="round", zorder=5)
    ax.scatter([0], [0], s=60, color=BRAND["dark"], zorder=6)

    # Value text
    colour = BRAND["green"] if cfe_pct >= 80 else BRAND["amber"] if cfe_pct >= 60 else BRAND["red"]
    ax.text(0, -0.15, f"{cfe_pct:.0f}%", ha="center", va="center",
            fontsize=22, fontweight="bold", color=colour)
    ax.text(0, -0.4, "24/7 CFE", ha="center", va="center",
            fontsize=9, color=BRAND["grey"])

    # Scale labels
    for pct, lbl in [(0, "0"), (25, "25"), (50, "50"), (75, "75"), (100, "100")]:
        a = np.pi * (1 - pct / 100)
        ax.text(np.cos(a) * 1.15, np.sin(a) * 1.15, lbl,
                ha="center", va="center", fontsize=6, color=BRAND["grey"])

    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-0.6, 1.3)
    ax.axis("off")
    fig.tight_layout(pad=0.5)
    return _fig_to_b64(fig)


# ===================================================================
# Adjust risks based on assessment data
# ===================================================================
def _adjust_risks(base_risks: list[dict], assessment: dict) -> list[dict]:
    """Adjust default risk likelihood/impact based on actual assessment data."""
    risks = [dict(r) for r in base_risks]  # deep copy

    grid = assessment.get("grid_connection", {})
    headroom = grid.get("headroom_mw")
    capacity = assessment.get("capacity_mw", 100)

    for r in risks:
        name = r["risk"]
        if name == "Grid capacity insufficient":
            if headroom is not None:
                if headroom >= capacity * 2:
                    r["likelihood"] = 1
                elif headroom >= capacity:
                    r["likelihood"] = 2
                else:
                    r["likelihood"] = 4
                    r["impact"] = 5

        elif name == "Connection timeline >36 months":
            queue = grid.get("queue_depth", 0)
            if queue <= 1:
                r["likelihood"] = 1
            elif queue >= 5:
                r["likelihood"] = 4

        elif name == "Planning refusal":
            scores = assessment.get("scores", {})
            land = scores.get("land_planning", {})
            land_score = land.get("score", 50) if isinstance(land, dict) else 50
            if land_score >= 75:
                r["likelihood"] = 1
            elif land_score < 40:
                r["likelihood"] = 4

        elif name == "CFE target unachievable":
            cfe = assessment.get("cfe", {})
            cfe_pct = cfe.get("cfe_pct", 50) if isinstance(cfe, dict) else 50
            if cfe_pct >= 80:
                r["likelihood"] = 1
            elif cfe_pct < 50:
                r["likelihood"] = 4

        elif name == "Flood risk materialises":
            scores = assessment.get("scores", {})
            constraint = scores.get("constraint_clear", {})
            cs = constraint.get("score", 70) if isinstance(constraint, dict) else 70
            if cs >= 80:
                r["likelihood"] = 1

        elif name == "Fibre connectivity delay":
            prox = assessment.get("proximity", {})
            fibre = prox.get("fibre", {})
            dist = fibre.get("distance_km", 5) if isinstance(fibre, dict) else 5
            if dist < 1:
                r["likelihood"] = 1
            elif dist > 10:
                r["likelihood"] = 4

    return risks


# ===================================================================
# Fetch static map
# ===================================================================
async def _fetch_static_map(lat: float, lon: float) -> str:
    """Fetch Mapbox static satellite map as base64 PNG."""
    token = os.environ.get("VITE_MAPBOX_TOKEN", os.environ.get("MAPBOX_TOKEN", ""))
    if not token:
        return _placeholder_map(lat, lon)
    try:
        import httpx
        url = (f"https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/"
               f"pin-l+0f62fe({lon},{lat})/{lon},{lat},12/800x500@2x"
               f"?access_token={token}")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("ascii")
    except Exception as e:
        log.warning("Mapbox static map failed: %s", e)
        return _placeholder_map(lat, lon)


def _placeholder_map(lat: float, lon: float) -> str:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.set_facecolor("#e8ecf0")
    for i in range(10):
        ax.axhline(y=i / 10, color="#d0d4d8", linewidth=0.3)
        ax.axvline(x=i / 10, color="#d0d4d8", linewidth=0.3)
    ax.plot(0.5, 0.5, "o", color=BRAND["primary"], markersize=14, zorder=5)
    ax.plot(0.5, 0.5, "o", color=BRAND["white"], markersize=6, zorder=6)
    ax.text(0.5, 0.35,
            f"Satellite imagery unavailable\n{lat:.4f}\u00b0N, {abs(lon):.4f}\u00b0{'W' if lon < 0 else 'E'}",
            ha="center", va="center", fontsize=11, color=BRAND["grey"], fontweight="500")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("#e8ecf0")
    return _fig_to_b64(fig, dpi=100)


# ===================================================================
# Extended scoring — aggregate DC-specific modules
# ===================================================================
async def score_dc_site_extended(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 100,
    profile: str = "google_hyperscale",
) -> dict[str, Any]:
    """
    Extended DC site scoring that combines colocation scorer, CFE scorer,
    cooling analyser, and water stress into a single assessment dict.
    """
    from utils.dc_colocation_scorer import score_dc_site
    from utils.dc_cfe_scorer import score_cfe
    from utils.dc_cooling_analyser import analyse_cooling
    from utils.dc_water_stress import assess_water_stress

    # Run all scorers concurrently
    base_result, cfe_result, cooling_result, water_result = await asyncio.gather(
        score_dc_site(conn, lat, lon, capacity_mw, profile),
        score_cfe(conn, lat, lon),
        analyse_cooling(conn, lat, lon, capacity_mw, "hybrid"),
        assess_water_stress(conn, lat, lon),
        return_exceptions=True,
    )

    # Use base result as foundation
    if isinstance(base_result, Exception):
        log.error("DC colocation scorer failed: %s", base_result)
        base_result = {
            "dc_score": 0, "verdict": "NO-GO", "confidence": 0.3,
            "scores": {}, "proximity": {}, "gates": {},
            "gates_all_passed": False, "grid_connection": {},
            "risks": [], "opportunities": [],
        }

    # Merge CFE data
    if isinstance(cfe_result, Exception):
        log.warning("CFE scorer failed: %s", cfe_result)
        cfe_result = {"cfe_pct": 0, "score": 0, "region": "Unknown"}
    base_result["cfe"] = cfe_result

    # Merge cooling data
    if isinstance(cooling_result, Exception):
        log.warning("Cooling analyser failed: %s", cooling_result)
        cooling_result = {
            "pue_estimate": {"pue": 1.35},
            "wue": {"wue": 1.0},
            "free_cooling": {"free_cooling_hours": 4500},
            "climate_projection": {"future_pue": {"2030": 1.38, "2040": 1.42, "2050": 1.48}},
            "cooling_score": 50,
        }
    base_result["cooling"] = cooling_result

    # Merge water stress data
    if isinstance(water_result, Exception):
        log.warning("Water stress assessment failed: %s", water_result)
        water_result = {"stress_level": "UNKNOWN", "score": 50}
    base_result["water_stress"] = water_result

    # Add extra computed dimensions for the google_hyperscale profile
    scores = base_result.get("scores", {})
    if "cfe_score" not in scores:
        cfe_pct = cfe_result.get("cfe_pct", 0) if isinstance(cfe_result, dict) else 0
        scores["cfe_score"] = {"score": min(100, cfe_pct * 1.1), "detail": cfe_result}
    if "cooling_climate" not in scores:
        cs = cooling_result.get("cooling_score", 50) if isinstance(cooling_result, dict) else 50
        scores["cooling_climate"] = {"score": cs, "detail": cooling_result}
    if "water_stress" not in scores:
        ws = water_result.get("score", 50) if isinstance(water_result, dict) else 50
        scores["water_stress"] = {"score": ws, "detail": water_result}
    # Fill dimensions that might be missing
    for dim in ["constraint_clear", "incentives", "regulatory_pathway", "community_acceptance"]:
        if dim not in scores:
            scores[dim] = {"score": 60, "detail": {"note": "Estimated — detailed assessment pending"}}
    base_result["scores"] = scores

    base_result["profile"] = profile
    base_result["capacity_mw"] = capacity_mw
    base_result["lat"] = lat
    base_result["lon"] = lon

    return base_result


# ===================================================================
# Financial model
# ===================================================================
def _compute_financials(capacity_mw: float, assessment: dict) -> dict[str, Any]:
    """Compute 10-year TCO, CapEx breakdown, and incentive estimates."""
    grid = assessment.get("grid_connection", {})
    cost_est = grid.get("cost_estimate", {})
    conn_cost = cost_est.get("p50_gbp", capacity_mw * 300_000) if isinstance(cost_est, dict) else capacity_mw * 300_000

    # CapEx breakdown (GBP)
    it_load_kw = capacity_mw * 1000
    capex = {
        "land_acquisition": round(capacity_mw * 120_000),  # ~120k/MW for UK industrial
        "civil_shell_core": round(it_load_kw * 2.5 * 1_800),  # 2.5m2/rack * 1800/m2
        "power_distribution": round(it_load_kw * 600),  # UPS, PDU, switchgear
        "cooling_plant": round(it_load_kw * 500),
        "generators": round(it_load_kw * 180 * 1.2),  # N+1
        "grid_connection": round(conn_cost),
        "fibre_connectivity": round(capacity_mw * 50_000),
        "fire_suppression": round(it_load_kw * 2.5 * 85),
        "bms_dcim": round(it_load_kw / 8 * 450),  # per rack
        "professional_fees": 0,  # computed below
    }
    subtotal = sum(capex.values())
    capex["professional_fees"] = round(subtotal * 0.08)
    capex["contingency"] = round(subtotal * 0.10)
    total_capex = sum(capex.values())

    # OpEx annual (GBP)
    opex = {
        "electricity": round(it_load_kw * 1.35 * 8760 * 0.18),  # PUE * hours * price/kWh
        "maintenance": round(total_capex * 0.025),
        "staffing": round(max(15, capacity_mw * 0.8) * 55_000),  # headcount * avg salary
        "insurance": round(total_capex * 0.005),
        "rates_taxes": round(total_capex * 0.012),
        "connectivity": round(capacity_mw * 30_000),
    }
    annual_opex = sum(opex.values())

    # 10-year TCO
    tco_10y = total_capex + annual_opex * 10
    cost_per_kw = round(total_capex / it_load_kw) if it_load_kw else 0

    # Incentives
    incentives = []
    incentives.append({"name": "Enterprise Zone relief", "value_gbp": round(total_capex * 0.05),
                       "probability": 0.6, "note": "Business rates relief for 5 years"})
    incentives.append({"name": "UK Investment Zone", "value_gbp": round(total_capex * 0.03),
                       "probability": 0.4, "note": "Tax credits in designated zones"})
    incentives.append({"name": "CfD renewable PPA", "value_gbp": round(annual_opex * 0.08 * 10),
                       "probability": 0.7, "note": "Stabilised green electricity cost"})

    return {
        "total_capex_gbp": total_capex,
        "capex_breakdown": capex,
        "annual_opex_gbp": annual_opex,
        "opex_breakdown": opex,
        "tco_10y_gbp": tco_10y,
        "cost_per_kw": cost_per_kw,
        "incentives": incentives,
    }


# ===================================================================
# HTML template
# ===================================================================
def _build_html(
    assessment: dict,
    financials: dict,
    charts: dict[str, str],
    map_image: str,
    site_name: str,
    capacity_mw: float,
    risks: list[dict],
) -> str:
    """Build the complete HTML report with inline CSS and embedded chart images."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict = assessment.get("verdict", "CAUTION")
    dc_score = assessment.get("dc_score", 0)
    confidence = assessment.get("confidence", 0.5)
    lat = assessment.get("lat", 0)
    lon = assessment.get("lon", 0)
    profile_name = assessment.get("profile", "google_hyperscale").replace("_", " ").title()

    grid = assessment.get("grid_connection", {})
    proximity = assessment.get("proximity", {})
    cfe_data = assessment.get("cfe", {})
    cooling_data = assessment.get("cooling", {})
    water_data = assessment.get("water_stress", {})
    scores = assessment.get("scores", {})
    opp_list = assessment.get("opportunities", [])
    risk_list = assessment.get("risks", [])

    # Extract key metrics
    headroom_mw = grid.get("headroom_mw")
    substation = grid.get("substation", "N/A")
    dno = grid.get("dno", "N/A")
    queue_depth = grid.get("queue_depth", 0)
    cost_est = grid.get("cost_estimate", {})
    conn_cost_p50 = cost_est.get("p50_gbp") if isinstance(cost_est, dict) else None

    cfe_pct = cfe_data.get("cfe_pct", 0) if isinstance(cfe_data, dict) else 0
    cfe_region = cfe_data.get("region", "Unknown") if isinstance(cfe_data, dict) else "Unknown"

    pue_data = cooling_data.get("pue_estimate", {}) if isinstance(cooling_data, dict) else {}
    current_pue = pue_data.get("pue", 1.35) if isinstance(pue_data, dict) else 1.35
    wue_data = cooling_data.get("wue", {}) if isinstance(cooling_data, dict) else {}
    current_wue = wue_data.get("wue", 1.0) if isinstance(wue_data, dict) else 1.0
    fc_data = cooling_data.get("free_cooling", {}) if isinstance(cooling_data, dict) else {}
    fc_hours = fc_data.get("free_cooling_hours", 4500) if isinstance(fc_data, dict) else 4500

    fibre = proximity.get("fibre", {}) if isinstance(proximity, dict) else {}
    fibre_km = fibre.get("distance_km", "N/A") if isinstance(fibre, dict) else "N/A"
    ixp = proximity.get("ixp", {}) if isinstance(proximity, dict) else {}
    ixp_km = ixp.get("distance_km", "N/A") if isinstance(ixp, dict) else "N/A"

    water_stress_level = water_data.get("stress_level", "UNKNOWN") if isinstance(water_data, dict) else "UNKNOWN"

    gates = assessment.get("gates", {})
    gates_passed = assessment.get("gates_all_passed", False)

    vc = _verdict_colour(verdict)

    def _img(key: str, alt: str = "") -> str:
        b64 = charts.get(key, "")
        if not b64:
            return f'<p style="color:#999;font-style:italic;">Chart unavailable: {alt}</p>'
        return f'<img src="data:image/png;base64,{b64}" alt="{alt}" style="max-width:100%;height:auto;">'

    def _metric_card(label: str, value: str, sub: str = "", color: str = BRAND["dark"]) -> str:
        return f'''<div style="flex:1;min-width:140px;padding:14px 16px;background:#f8f9fa;
            border-radius:8px;border-left:4px solid {color};">
            <div style="font-size:11px;color:{BRAND["grey"]};text-transform:uppercase;letter-spacing:0.5px;">{label}</div>
            <div style="font-size:22px;font-weight:700;color:{color};margin-top:4px;">{value}</div>
            {f'<div style="font-size:10px;color:{BRAND["grey"]};margin-top:2px;">{sub}</div>' if sub else ''}
        </div>'''

    def _gate_row(name: str, gate_info: dict) -> str:
        passed = gate_info.get("passed", False) if isinstance(gate_info, dict) else False
        val = gate_info.get("value", "N/A") if isinstance(gate_info, dict) else "N/A"
        req = gate_info.get("required", "N/A") if isinstance(gate_info, dict) else "N/A"
        icon = "&#10003;" if passed else "&#10007;"
        col = BRAND["green"] if passed else BRAND["red"]
        return f'''<tr>
            <td style="padding:6px 10px;font-size:12px;">{name.replace("_"," ").title()}</td>
            <td style="padding:6px 10px;font-size:12px;">{val}</td>
            <td style="padding:6px 10px;font-size:12px;">{req}</td>
            <td style="padding:6px 10px;font-size:12px;color:{col};font-weight:700;">{icon}</td>
        </tr>'''

    def _capex_rows(breakdown: dict) -> str:
        rows = ""
        for k, v in breakdown.items():
            rows += f'''<tr>
                <td style="padding:5px 10px;font-size:11px;">{k.replace("_"," ").title()}</td>
                <td style="padding:5px 10px;font-size:11px;text-align:right;">{_fmt_gbp(v)}</td>
            </tr>'''
        return rows

    # Connection timeline estimate
    if queue_depth <= 2:
        timeline = "18-24 months"
    elif queue_depth <= 5:
        timeline = "24-36 months"
    else:
        timeline = "36-48+ months"

    # NSIP pathway
    nsip = capacity_mw >= 50
    nsip_text = ("NSIP (Nationally Significant Infrastructure Project) pathway applies "
                 f"for {capacity_mw:.0f} MW. Requires Development Consent Order (DCO) "
                 "via Planning Inspectorate.") if nsip else (
                 f"Below 50 MW NSIP threshold ({capacity_mw:.0f} MW). "
                 "Standard Town & Country Planning Act application via Local Planning Authority.")

    # TM04+ gate
    tm04_text = ("Ofgem TM04+ gate assessment required for connections >1 MW. "
                 f"Queue depth at nearest substation: {queue_depth} applications.")

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Princeps DC Site Assessment — {site_name}</title>
<style>
@page {{
    size: A4;
    margin: 0;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: {BRAND["dark"]};
    font-size: 13px;
    line-height: 1.5;
    background: white;
}}
.page {{
    page-break-after: always;
    padding: 32px 36px;
    min-height: 100vh;
    position: relative;
}}
.page:last-child {{ page-break-after: auto; }}
h1 {{
    font-size: 28px; font-weight: 800; color: {BRAND["dark"]};
    margin-bottom: 4px; letter-spacing: -0.5px;
}}
h2 {{
    font-size: 18px; font-weight: 700; color: {BRAND["primary"]};
    margin: 24px 0 12px 0; padding-bottom: 6px;
    border-bottom: 2px solid {BRAND["primary"]}20;
}}
h3 {{
    font-size: 14px; font-weight: 600; color: {BRAND["dark"]};
    margin: 16px 0 8px 0;
}}
.header-bar {{
    background: linear-gradient(135deg, {BRAND["dark"]} 0%, #2d2d5e 100%);
    color: white; padding: 28px 36px 24px; margin: -32px -36px 24px -36px;
}}
.header-bar h1 {{ color: white; }}
.header-bar .subtitle {{ color: rgba(255,255,255,0.7); font-size: 13px; margin-top: 4px; }}
.verdict-badge {{
    display: inline-block; padding: 6px 20px; border-radius: 20px;
    font-size: 16px; font-weight: 800; letter-spacing: 1px;
    color: white; margin-top: 10px;
}}
.metrics-row {{
    display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0;
}}
table {{
    width: 100%; border-collapse: collapse; margin: 8px 0;
}}
table th {{
    background: {BRAND["light"]}; padding: 8px 10px; text-align: left;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px;
    color: {BRAND["grey"]}; border-bottom: 2px solid #e0e0e0;
}}
table td {{
    padding: 6px 10px; border-bottom: 1px solid #f0f0f0;
}}
.section {{ margin-bottom: 20px; }}
.two-col {{ display: flex; gap: 24px; }}
.two-col > div {{ flex: 1; }}
.risk-item {{
    padding: 6px 0; border-bottom: 1px solid #f0f0f0;
    font-size: 12px;
}}
.risk-icon {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 6px; vertical-align: middle; }}
.footer {{
    position: absolute; bottom: 12px; left: 36px; right: 36px;
    font-size: 9px; color: {BRAND["grey"]}; border-top: 1px solid #e0e0e0;
    padding-top: 6px; display: flex; justify-content: space-between;
}}
.tag {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 600; margin-right: 4px;
}}
.tag-go {{ background: {BRAND["green"]}20; color: {BRAND["green"]}; }}
.tag-caution {{ background: {BRAND["amber"]}30; color: #8a6d00; }}
.tag-nogo {{ background: {BRAND["red"]}20; color: {BRAND["red"]}; }}
.chart-container {{ text-align: center; margin: 12px 0; }}
</style>
</head>
<body>

<!-- ====== PAGE 1: EXECUTIVE SUMMARY ====== -->
<div class="page">
    <div class="header-bar">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;">
            <div>
                <div style="font-size:12px;font-weight:600;letter-spacing:2px;color:rgba(255,255,255,0.5);margin-bottom:4px;">PRINCEPS</div>
                <h1>Data Centre Site Assessment</h1>
                <div class="subtitle">{site_name} &mdash; {profile_name} Profile &mdash; {capacity_mw:.0f} MW IT Load</div>
                <div class="verdict-badge" style="background:{vc};">{verdict}</div>
            </div>
            <div style="text-align:right;font-size:11px;color:rgba(255,255,255,0.6);">
                <div>{now}</div>
                <div>{lat:.4f}&deg;N, {abs(lon):.4f}&deg;{'W' if lon < 0 else 'E'}</div>
                <div>Score: {dc_score:.0f}/100</div>
                <div>Confidence: {confidence:.0%}</div>
            </div>
        </div>
    </div>

    <h2>1. Executive Summary</h2>
    <div class="metrics-row">
        {_metric_card("Overall Score", f"{dc_score:.0f}/100", f"Confidence {confidence:.0%}", vc)}
        {_metric_card("Grid Headroom", f"{headroom_mw:.0f} MW" if headroom_mw else "N/A", substation, BRAND["primary"])}
        {_metric_card("24/7 CFE", f"{cfe_pct:.0f}%", cfe_region, BRAND["green"] if cfe_pct >= 80 else BRAND["amber"])}
        {_metric_card("PUE", f"{current_pue:.2f}", f"WUE {current_wue:.2f} L/kWh", BRAND["primary"])}
    </div>
    <div class="metrics-row">
        {_metric_card("Connection Cost", _fmt_gbp(conn_cost_p50), f"Timeline: {timeline}", BRAND["primary"])}
        {_metric_card("10-Year TCO", _fmt_gbp(financials["tco_10y_gbp"]), f"CapEx {_fmt_gbp(financials['total_capex_gbp'])}", BRAND["dark"])}
        {_metric_card("Fibre", f"{fibre_km} km" if isinstance(fibre_km, (int,float)) else fibre_km, "To nearest POP", BRAND["primary"])}
        {_metric_card("Gates", "ALL PASS" if gates_passed else "FAIL", f"{sum(1 for g in gates.values() if isinstance(g,dict) and g.get('passed'))}/{len(gates)} passed" if gates else "", BRAND["green"] if gates_passed else BRAND["red"])}
    </div>

    <h3>Key Findings</h3>
    <div style="display:flex;gap:20px;margin-top:8px;">
        <div style="flex:1;">
            <div style="font-size:11px;font-weight:700;color:{BRAND['green']};margin-bottom:6px;">OPPORTUNITIES</div>
            {"".join(f'<div class="risk-item"><span class="risk-icon" style="background:{BRAND["green"]};"></span>{o}</div>' for o in opp_list[:5]) if opp_list else '<div style="font-size:12px;color:#999;">None identified</div>'}
        </div>
        <div style="flex:1;">
            <div style="font-size:11px;font-weight:700;color:{BRAND['red']};margin-bottom:6px;">KEY RISKS</div>
            {"".join(f'<div class="risk-item"><span class="risk-icon" style="background:{BRAND["red"]};"></span>{r}</div>' for r in risk_list[:5]) if risk_list else '<div style="font-size:12px;color:#999;">None identified</div>'}
        </div>
    </div>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 1</div>
    </div>
</div>

<!-- ====== PAGE 2: SITE OVERVIEW ====== -->
<div class="page">
    <h2>2. Site Overview</h2>
    <div class="chart-container">
        <img src="data:image/png;base64,{map_image}" alt="Site Map"
             style="max-width:100%;height:auto;border-radius:8px;border:1px solid #e0e0e0;">
    </div>
    <div class="metrics-row">
        {_metric_card("Coordinates", f"{lat:.4f}, {lon:.4f}", "WGS84", BRAND["primary"])}
        {_metric_card("Capacity", f"{capacity_mw:.0f} MW", "IT Load", BRAND["primary"])}
        {_metric_card("Profile", profile_name, "", BRAND["dark"])}
        {_metric_card("DNO Region", str(dno), "", BRAND["dark"])}
    </div>

    <h2>3. Power Analysis</h2>
    <div class="two-col">
        <div>
            <h3>Grid Connection</h3>
            <table>
                <tr><td style="font-weight:600;">Nearest Substation</td><td>{substation}</td></tr>
                <tr><td style="font-weight:600;">Headroom</td><td>{f"{headroom_mw:.1f} MW" if headroom_mw else "N/A"}</td></tr>
                <tr><td style="font-weight:600;">Queue Depth</td><td>{queue_depth} applications</td></tr>
                <tr><td style="font-weight:600;">DNO</td><td>{dno}</td></tr>
                <tr><td style="font-weight:600;">Connection Cost (P50)</td><td>{_fmt_gbp(conn_cost_p50)}</td></tr>
                <tr><td style="font-weight:600;">Estimated Timeline</td><td>{timeline}</td></tr>
            </table>
        </div>
        <div>
            <h3>Gate Thresholds</h3>
            <table>
                <tr><th>Gate</th><th>Actual</th><th>Required</th><th>Status</th></tr>
                {"".join(_gate_row(k, v) for k, v in gates.items()) if gates else '<tr><td colspan="4" style="color:#999;">No gate data</td></tr>'}
            </table>
        </div>
    </div>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 2</div>
    </div>
</div>

<!-- ====== PAGE 3: CFE & COOLING ====== -->
<div class="page">
    <h2>4. 24/7 CFE% Assessment</h2>
    <div class="two-col">
        <div class="chart-container">
            {_img("cfe_gauge", "CFE Gauge")}
        </div>
        <div>
            <table>
                <tr><td style="font-weight:600;">Achievable CFE%</td><td style="font-size:18px;font-weight:700;color:{BRAND['green'] if cfe_pct >= 80 else BRAND['amber']}">{cfe_pct:.0f}%</td></tr>
                <tr><td style="font-weight:600;">Grid Region</td><td>{cfe_region}</td></tr>
                <tr><td style="font-weight:600;">Google Target</td><td>90% by 2030</td></tr>
                <tr><td style="font-weight:600;">Gap to Target</td><td>{max(0, 90 - cfe_pct):.0f} pp</td></tr>
            </table>
            <p style="font-size:11px;color:{BRAND['grey']};margin-top:12px;">
                CFE% combines regional grid carbon intensity with locally available renewable PPAs
                (wind, solar, storage). Scores above 80% indicate strong alignment with Google's
                24/7 carbon-free energy commitment.
            </p>
        </div>
    </div>

    <h2>5. Cooling Analysis</h2>
    <div class="metrics-row">
        {_metric_card("Current PUE", f"{current_pue:.2f}", "Design estimate", BRAND["green"] if current_pue <= 1.25 else BRAND["amber"])}
        {_metric_card("WUE", f"{current_wue:.2f}", "L/kWh IT load", BRAND["primary"])}
        {_metric_card("Free Cooling", f"{fc_hours:,} hrs", f"{fc_hours/87.6:.0f}% of year", BRAND["green"] if fc_hours >= 5000 else BRAND["amber"])}
    </div>
    <h3>PUE Projection (UKCP18 RCP8.5)</h3>
    <div class="chart-container">
        {_img("pue_projection", "PUE Projection")}
    </div>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 3</div>
    </div>
</div>

<!-- ====== PAGE 4: CONNECTIVITY & ENVIRONMENTAL ====== -->
<div class="page">
    <h2>6. Connectivity</h2>
    <div class="two-col">
        <div>
            <table>
                <tr><th colspan="2">Network Infrastructure</th></tr>
                <tr><td style="font-weight:600;">Fibre POP Distance</td><td>{f"{fibre_km:.1f} km" if isinstance(fibre_km, (int,float)) else fibre_km}</td></tr>
                <tr><td style="font-weight:600;">Nearest IXP</td><td>{f"{ixp_km:.1f} km" if isinstance(ixp_km, (int,float)) else ixp_km}</td></tr>
                <tr><td style="font-weight:600;">Latency Score</td><td>{scores.get("latency", {}).get("score", "N/A") if isinstance(scores.get("latency"), dict) else "N/A"}/100</td></tr>
            </table>
        </div>
        <div>
            <p style="font-size:11px;color:{BRAND['grey']};margin-top:8px;">
                Fibre proximity is critical for hyperscale data centres. Sub-5km POP distance
                ensures diverse, redundant dark fibre routes at competitive IRU rates.
                IXP proximity reduces transit costs and improves peering options.
            </p>
        </div>
    </div>

    <h2>7. Environmental</h2>
    <div class="metrics-row">
        {_metric_card("Constraint Clear", f"{scores.get('constraint_clear', {}).get('score', 'N/A') if isinstance(scores.get('constraint_clear'), dict) else 'N/A'}/100", "Env. constraints", BRAND["green"])}
        {_metric_card("Water Stress", water_stress_level, "", BRAND["green"] if water_stress_level in ("LOW","UNKNOWN") else BRAND["amber"] if water_stress_level == "MEDIUM" else BRAND["red"])}
        {_metric_card("Flood Risk", "Assessed", "", BRAND["primary"])}
    </div>
    <table>
        <tr><th>Environmental Factor</th><th>Status</th><th>Risk Level</th></tr>
        <tr><td>Flood Zone</td><td>{"Zone assessed" if scores.get("constraint_clear") else "Pending"}</td>
            <td><span class="tag tag-go">LOW</span></td></tr>
        <tr><td>Biodiversity Net Gain (BNG)</td><td>10% net gain required (Environment Act 2021)</td>
            <td><span class="tag tag-caution">MEDIUM</span></td></tr>
        <tr><td>Water Stress</td><td>EA classification: {water_stress_level}</td>
            <td><span class="tag {'tag-go' if water_stress_level in ('LOW','UNKNOWN') else 'tag-caution' if water_stress_level == 'MEDIUM' else 'tag-nogo'}">{water_stress_level}</span></td></tr>
        <tr><td>Protected Habitats</td><td>SSSI/SAC/SPA proximity check</td>
            <td><span class="tag tag-go">LOW</span></td></tr>
        <tr><td>Air Quality</td><td>Diesel generator emissions assessment</td>
            <td><span class="tag tag-caution">MEDIUM</span></td></tr>
    </table>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 4</div>
    </div>
</div>

<!-- ====== PAGE 5: FINANCIAL ====== -->
<div class="page">
    <h2>8. Financial Analysis</h2>
    <div class="metrics-row">
        {_metric_card("Total CapEx", _fmt_gbp(financials["total_capex_gbp"]), f"{financials['cost_per_kw']:,}/kW" if financials.get("cost_per_kw") else "", BRAND["primary"])}
        {_metric_card("Annual OpEx", _fmt_gbp(financials["annual_opex_gbp"]), "", BRAND["dark"])}
        {_metric_card("10-Year TCO", _fmt_gbp(financials["tco_10y_gbp"]), "", BRAND["dark"])}
    </div>

    <div class="two-col">
        <div>
            <h3>CapEx Breakdown</h3>
            <table>
                <tr><th>Component</th><th style="text-align:right;">Cost</th></tr>
                {_capex_rows(financials["capex_breakdown"])}
                <tr style="font-weight:700;border-top:2px solid #333;">
                    <td style="padding:8px 10px;">TOTAL</td>
                    <td style="padding:8px 10px;text-align:right;">{_fmt_gbp(financials["total_capex_gbp"])}</td>
                </tr>
            </table>
        </div>
        <div>
            <h3>Annual OpEx Breakdown</h3>
            <table>
                <tr><th>Component</th><th style="text-align:right;">Cost p.a.</th></tr>
                {_capex_rows(financials["opex_breakdown"])}
                <tr style="font-weight:700;border-top:2px solid #333;">
                    <td style="padding:8px 10px;">TOTAL</td>
                    <td style="padding:8px 10px;text-align:right;">{_fmt_gbp(financials["annual_opex_gbp"])}</td>
                </tr>
            </table>
        </div>
    </div>

    <h3>Incentives & Reliefs</h3>
    <table>
        <tr><th>Incentive</th><th style="text-align:right;">Est. Value</th><th>Probability</th><th>Notes</th></tr>
        {"".join(f'<tr><td style="padding:5px 10px;font-size:11px;">{inc["name"]}</td><td style="padding:5px 10px;font-size:11px;text-align:right;">{_fmt_gbp(inc["value_gbp"])}</td><td style="padding:5px 10px;font-size:11px;">{inc["probability"]:.0%}</td><td style="padding:5px 10px;font-size:11px;">{inc["note"]}</td></tr>' for inc in financials.get("incentives", []))}
    </table>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 5</div>
    </div>
</div>

<!-- ====== PAGE 6: REGULATORY & RISK ====== -->
<div class="page">
    <h2>9. Regulatory Pathway</h2>
    <div class="two-col">
        <div>
            <h3>Planning Route</h3>
            <p style="font-size:12px;margin-bottom:12px;">{nsip_text}</p>
            <table>
                <tr><td style="font-weight:600;">NSIP Threshold</td>
                    <td><span class="tag {'tag-nogo' if nsip else 'tag-go'}">{'ABOVE' if nsip else 'BELOW'} 50 MW</span></td></tr>
                <tr><td style="font-weight:600;">EIA Required</td><td>Yes (Schedule 2, >1 ha)</td></tr>
                <tr><td style="font-weight:600;">Section 36 Consent</td><td>{'Required' if capacity_mw >= 50 else 'Not required'}</td></tr>
            </table>
        </div>
        <div>
            <h3>Grid Connection (TM04+)</h3>
            <p style="font-size:12px;margin-bottom:12px;">{tm04_text}</p>
            <table>
                <tr><td style="font-weight:600;">Connection Offer</td><td>{timeline}</td></tr>
                <tr><td style="font-weight:600;">Queue Position</td><td>{queue_depth}</td></tr>
                <tr><td style="font-weight:600;">Acceleration</td>
                    <td>{'Strategic growth area — potential fast-track' if queue_depth <= 2 else 'Standard queue — consider acceleration agreement'}</td></tr>
            </table>
        </div>
    </div>

    <h2>10. Risk Matrix</h2>
    <div class="chart-container">
        {_img("risk_matrix", "Risk Matrix")}
    </div>
    <h3>Risk Register</h3>
    <table>
        <tr><th>Risk</th><th>Category</th><th>Likelihood</th><th>Impact</th><th>Score</th></tr>
        {"".join(f'<tr><td style="font-size:11px;padding:5px 10px;">{r["risk"]}</td><td style="font-size:11px;padding:5px 10px;">{r["category"]}</td><td style="font-size:11px;padding:5px 10px;text-align:center;">{r["likelihood"]}</td><td style="font-size:11px;padding:5px 10px;text-align:center;">{r["impact"]}</td><td style="font-size:11px;padding:5px 10px;text-align:center;font-weight:700;color:{BRAND["red"] if r["likelihood"]*r["impact"]>=12 else BRAND["amber"] if r["likelihood"]*r["impact"]>=6 else BRAND["green"]}">{r["likelihood"]*r["impact"]}</td></tr>' for r in risks)}
    </table>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential</div>
        <div>Page 6</div>
    </div>
</div>

<!-- ====== PAGE 7: SCORING & RECOMMENDATIONS ====== -->
<div class="page">
    <h2>Multi-Dimension Scoring</h2>
    <div class="two-col">
        <div class="chart-container">
            {_img("radar", "Radar Chart")}
        </div>
        <div class="chart-container">
            {_img("score_bars", "Score Breakdown")}
        </div>
    </div>

    <h2>11. Recommendation & Next Steps</h2>
    <div style="background:{'#e8f5e9' if verdict == 'GO' else '#fff8e1' if verdict == 'CAUTION' else '#fce4ec'};
         border-radius:8px;padding:16px 20px;margin:12px 0;border-left:4px solid {vc};">
        <div style="font-size:16px;font-weight:800;color:{vc};margin-bottom:8px;">
            {verdict} &mdash; {dc_score:.0f}/100
        </div>
        <p style="font-size:12px;line-height:1.6;">
            {_recommendation_text(verdict, dc_score, assessment, financials, capacity_mw)}
        </p>
    </div>

    <h3>Recommended Next Steps</h3>
    <table>
        <tr><th>#</th><th>Action</th><th>Timeline</th><th>Owner</th></tr>
        {_next_steps_rows(verdict, assessment, capacity_mw)}
    </table>

    <div style="margin-top:24px;padding:12px 16px;background:{BRAND['light']};border-radius:6px;">
        <p style="font-size:10px;color:{BRAND['grey']};line-height:1.6;">
            <strong>Disclaimer:</strong> This report is generated by Princeps automated site assessment engine
            using publicly available data, satellite imagery, and government datasets. It is intended for
            preliminary screening purposes only. Formal grid connection applications, environmental impact
            assessments, and planning submissions require independent professional verification.
            All financial projections are indicative and subject to market conditions.
        </p>
    </div>

    <div class="footer">
        <div>PRINCEPS &mdash; Confidential &mdash; Generated {now}</div>
        <div>Page 7</div>
    </div>
</div>

</body>
</html>'''
    return html


# ===================================================================
# Recommendation text
# ===================================================================
def _recommendation_text(
    verdict: str, score: float, assessment: dict, financials: dict, capacity_mw: float
) -> str:
    grid = assessment.get("grid_connection", {})
    headroom = grid.get("headroom_mw")
    cfe = assessment.get("cfe", {})
    cfe_pct = cfe.get("cfe_pct", 0) if isinstance(cfe, dict) else 0

    if verdict == "GO":
        return (
            f"This site scores {score:.0f}/100 and passes all gate thresholds for a "
            f"{capacity_mw:.0f} MW hyperscale data centre deployment. "
            f"Grid headroom of {headroom:.0f} MW is adequate, "
            f"and the achievable CFE% of {cfe_pct:.0f}% supports Google's 24/7 carbon-free energy target. "
            f"Total 10-year cost of ownership is estimated at {_fmt_gbp(financials['tco_10y_gbp'])}. "
            f"We recommend proceeding to formal grid connection application and detailed EIA."
        )
    elif verdict == "CAUTION":
        blockers = []
        if headroom is not None and headroom < capacity_mw:
            blockers.append(f"grid headroom ({headroom:.0f} MW vs {capacity_mw:.0f} MW required)")
        if cfe_pct < 60:
            blockers.append(f"CFE% ({cfe_pct:.0f}% vs 60% minimum)")
        if not assessment.get("gates_all_passed"):
            blockers.append("one or more gate thresholds not met")
        blocker_text = ", ".join(blockers) if blockers else "marginal scoring across multiple dimensions"
        return (
            f"This site scores {score:.0f}/100 and warrants further investigation, but has "
            f"concerns: {blocker_text}. "
            f"Targeted mitigation (grid reinforcement, PPA procurement, or phased deployment) "
            f"could address these issues. Recommend a detailed feasibility study before commitment."
        )
    else:
        return (
            f"This site scores {score:.0f}/100 and is not recommended for a {capacity_mw:.0f} MW "
            f"data centre at this time. Critical issues include insufficient grid capacity, "
            f"failed gate thresholds, or prohibitive environmental constraints. "
            f"Consider alternative sites identified by the Princeps regional scan."
        )


def _next_steps_rows(verdict: str, assessment: dict, capacity_mw: float) -> str:
    steps = [
        ("1", "Commission detailed geotechnical survey", "Month 1-2", "Developer"),
        ("2", "Submit formal grid connection application (TM04+)", "Month 1", "Grid consultant"),
        ("3", "Engage DNO pre-application meeting", "Month 1", "Grid consultant"),
        ("4", "Environmental Impact Assessment scoping", "Month 2-3", "Environmental consultant"),
        ("5", "Fibre route survey & dark fibre IRU negotiation", "Month 2-4", "Network architect"),
        ("6", "Water abstraction licence pre-application", "Month 2-3", "Environmental consultant"),
        ("7", "Community engagement strategy", "Month 3-6", "Planning consultant"),
    ]
    if capacity_mw >= 50:
        steps.append(("8", "NSIP pre-application: PINS scoping opinion", "Month 3-4", "Planning lawyer"))
    else:
        steps.append(("8", "Pre-application advice from LPA", "Month 2-3", "Planning consultant"))
    steps.append(("9", "Renewable PPA procurement (wind/solar)", "Month 3-6", "Energy procurement"))
    steps.append(("10", "Board investment decision gate", "Month 6-9", "Executive sponsor"))

    return "".join(
        f'<tr><td style="font-size:11px;padding:5px 10px;text-align:center;">{s[0]}</td>'
        f'<td style="font-size:11px;padding:5px 10px;">{s[1]}</td>'
        f'<td style="font-size:11px;padding:5px 10px;">{s[2]}</td>'
        f'<td style="font-size:11px;padding:5px 10px;">{s[3]}</td></tr>'
        for s in steps
    )


# ===================================================================
# HTML -> PDF
# ===================================================================
async def _html_to_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes via Playwright Chromium."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(html)
        tmp.close()
        file_url = f"file://{tmp.name}"

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                raise RuntimeError("Chromium not installed. Run: playwright install chromium")
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60_000)
            pdf_bytes = await page.pdf(
                format="A4",
                margin={"top": "0.4in", "bottom": "0.4in", "left": "0.4in", "right": "0.4in"},
                print_background=True,
            )
            await browser.close()
            return pdf_bytes
    finally:
        os.unlink(tmp.name)


# ===================================================================
# MAIN ENTRY POINT
# ===================================================================
async def generate_dc_report(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    site_name: str = "Candidate Site",
    capacity_mw: float = 100,
    profile: str = "google_hyperscale",
) -> bytes:
    """Generate a complete DC site assessment PDF report. Returns PDF bytes."""
    log.info(
        "Generating DC report for %s (%.4f, %.4f) @ %.0f MW [%s]",
        site_name, lat, lon, capacity_mw, profile,
    )

    # 1. Score the site (extended — combines colocation + CFE + cooling + water)
    assessment = await score_dc_site_extended(conn, lat, lon, capacity_mw, profile)
    log.info(
        "Assessment complete: score=%.1f, verdict=%s, confidence=%.2f",
        assessment.get("dc_score", 0),
        assessment.get("verdict", "?"),
        assessment.get("confidence", 0),
    )

    # 2. Compute financials
    financials = _compute_financials(capacity_mw, assessment)

    # 3. Adjust risks
    risks = _adjust_risks(DC_RISKS, assessment)

    # 4. Generate charts (CPU-bound — run in executor)
    loop = asyncio.get_running_loop()
    scores = assessment.get("scores", {})
    cooling = assessment.get("cooling", {})
    pue_est = cooling.get("pue_estimate", {}) if isinstance(cooling, dict) else {}
    current_pue = pue_est.get("pue", 1.35) if isinstance(pue_est, dict) else 1.35
    climate_proj = cooling.get("climate_projection", {}) if isinstance(cooling, dict) else {}
    future_pue = climate_proj.get("future_pue", {"2030": 1.38, "2040": 1.42, "2050": 1.48}) if isinstance(climate_proj, dict) else {"2030": 1.38, "2040": 1.42, "2050": 1.48}
    cfe_data = assessment.get("cfe", {})
    cfe_pct = cfe_data.get("cfe_pct", 0) if isinstance(cfe_data, dict) else 0

    def _generate_all_charts() -> dict[str, str]:
        charts: dict[str, str] = {}
        try:
            charts["radar"] = _render_radar_chart(scores, RADAR_DIMENSIONS)
        except Exception as e:
            log.warning("Radar chart failed: %s", e)
        try:
            charts["score_bars"] = _render_score_bars(scores)
        except Exception as e:
            log.warning("Score bars chart failed: %s", e)
        try:
            charts["risk_matrix"] = _render_risk_matrix(risks)
        except Exception as e:
            log.warning("Risk matrix chart failed: %s", e)
        try:
            charts["pue_projection"] = _render_pue_projection(current_pue, future_pue)
        except Exception as e:
            log.warning("PUE projection chart failed: %s", e)
        try:
            charts["cfe_gauge"] = _render_cfe_gauge(cfe_pct)
        except Exception as e:
            log.warning("CFE gauge chart failed: %s", e)
        return charts

    charts, map_image = await asyncio.gather(
        loop.run_in_executor(None, _generate_all_charts),
        _fetch_static_map(lat, lon),
    )
    log.info("Charts generated: %s", ", ".join(charts.keys()))

    # 5. Build HTML
    html = _build_html(assessment, financials, charts, map_image, site_name, capacity_mw, risks)

    # 6. Convert to PDF
    pdf_bytes = await _html_to_pdf(html)
    log.info("DC report generated: %d bytes (%d pages est.)", len(pdf_bytes), 7)
    return pdf_bytes
