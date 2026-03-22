"""
Automated Planning Constraint Report -- PDF generation.

Generates a professional constraint report covering:
1. Site location and description
2. Environmental designations (SSSI, AONB, SAC, SPA)
3. Flood risk assessment
4. Heritage constraints (listed buildings, conservation areas)
5. Agricultural land classification
6. Grid connection feasibility
7. Planning risk score (ML-predicted)
8. Shadow flicker / noise assessment summary
9. Viewshed analysis summary
10. Recommendations

This report replaces the manual constraint screening that planning
consultants typically charge GBP 5-20K for.  It pulls live data from
Natural England, Environment Agency, Historic England, BMRS, and the
Princeps PostGIS database.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from jinja2 import Environment, FileSystemLoader

log = logging.getLogger("princeps.constraint_report")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "report"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)

# Princeps brand palette (matches report_renderer.py)
BRAND = {
    "primary": "#0f62fe", "primary_light": "#4589ff", "primary_dark": "#0043ce",
    "dark": "#1a1a2e", "green": "#24a148", "green_light": "#42be65",
    "red": "#da1e28", "red_light": "#fa4d56", "amber": "#f1c21b",
    "amber_light": "#f7d84e", "grey": "#697077", "grey_light": "#a8a8a8",
    "light": "#f4f4f4", "white": "#ffffff",
}


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _fig_to_b64(fig: plt.Figure, dpi: int = 150) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=BRAND["white"], edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _constraint_summary_chart(constraints: dict) -> str:
    """Horizontal bar chart of constraint risk levels."""
    categories = []
    scores = []
    colours = []

    risk_map = {"high": 20, "medium": 55, "low": 85, "none": 95, "unknown": 50}
    colour_map = {"high": BRAND["red"], "medium": BRAND["amber"],
                  "low": BRAND["green"], "none": BRAND["green_light"],
                  "unknown": BRAND["grey"]}

    env_risk = constraints.get("environmental", {}).get("risk_level", "unknown")
    flood_risk = constraints.get("flood", {}).get("risk_level", "unknown")
    heritage_risk = constraints.get("heritage", {}).get("risk_level", "none")
    alc_suitable = constraints.get("alc", {}).get("suitable_for_development", True)
    planning_risk_val = constraints.get("planning_risk", {}).get("risk_level", "medium")
    grid_risk = "low" if constraints.get("grid", {}).get("verdict") in ("GO", "CAUTION") else "medium"

    items = [
        ("Environmental", env_risk),
        ("Flood Risk", flood_risk),
        ("Heritage", heritage_risk),
        ("Agricultural Land", "low" if alc_suitable else "high"),
        ("Planning Risk", planning_risk_val),
        ("Grid Connection", grid_risk),
    ]

    for label, risk in items:
        categories.append(label)
        scores.append(risk_map.get(risk, 50))
        colours.append(colour_map.get(risk, BRAND["grey"]))

    fig, ax = plt.subplots(figsize=(7, 3.5))
    fig.patch.set_facecolor(BRAND["white"])
    ax.set_facecolor(BRAND["white"])
    y = np.arange(len(categories))

    ax.barh(y, [100] * len(categories), color="#f0f0f0", height=0.55, zorder=1)
    ax.barh(y, scores, color=colours, height=0.55, zorder=2, edgecolor="none")
    ax.axvline(x=40, color=BRAND["red"], lw=0.8, ls="--", alpha=0.5, zorder=3)
    ax.axvline(x=65, color=BRAND["amber"], lw=0.8, ls="--", alpha=0.5, zorder=3)

    for i, (s, risk) in enumerate(zip(scores, [r for _, r in items])):
        ax.text(s + 1.5, i, risk.upper(), va="center", fontsize=9,
                fontweight="bold", color=colours[i], zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels(categories, fontsize=9, color=BRAND["dark"])
    ax.set_xlim(0, 108)
    ax.invert_yaxis()
    ax.tick_params(axis="x", bottom=False, labelbottom=False)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.spines["left"].set_color(BRAND["grey_light"])

    ax.legend(handles=[
        mpatches.Patch(facecolor=BRAND["red"], alpha=0.7, label="High Risk"),
        mpatches.Patch(facecolor=BRAND["amber"], alpha=0.7, label="Medium Risk"),
        mpatches.Patch(facecolor=BRAND["green"], alpha=0.7, label="Low Risk"),
    ], loc="lower right", fontsize=7, framealpha=0.8, edgecolor="none")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _planning_risk_radar(factors: list[dict]) -> str:
    """Radar chart of planning risk factors."""
    if not factors:
        return ""
    labels = [f.get("name", "?")[:18] for f in factors]
    values = [f.get("score", 50) for f in factors]
    n = len(labels)
    if n < 3:
        return ""

    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    values_c = values + values[:1]
    angles_c = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(5, 5), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(BRAND["white"])

    theta = np.linspace(0, 2 * np.pi, 100)
    ax.fill_between(theta, 0, 40, alpha=0.04, color=BRAND["red"])
    ax.fill_between(theta, 40, 65, alpha=0.04, color=BRAND["amber"])
    ax.fill_between(theta, 65, 100, alpha=0.04, color=BRAND["green"])

    ax.fill(angles_c, values_c, color=BRAND["primary"], alpha=0.15)
    ax.plot(angles_c, values_c, color=BRAND["primary"], linewidth=2.2)

    for i, (a, v) in enumerate(zip(angles, values)):
        c = BRAND["green"] if v >= 65 else BRAND["amber"] if v >= 40 else BRAND["red"]
        ax.scatter([a], [v], color=c, s=50, zorder=5, edgecolors="white", linewidths=1)
        ax.annotate(str(v), xy=(a, v), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=7, fontweight="bold", color=BRAND["dark"])

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, size=7.5, fontweight="600", color=BRAND["dark"])
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80])
    ax.set_yticklabels(["20", "40", "60", "80"], size=6, color=BRAND["grey"])
    ax.spines["polar"].set_color(BRAND["grey_light"])
    ax.grid(color="#e0e0e0", linewidth=0.4)
    fig.tight_layout(pad=1.5)
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

async def _gather_constraint_data(
    pool, lat: float, lon: float, capacity_mw: float, technology: str,
) -> dict[str, Any]:
    """Gather all constraint data in parallel."""

    from utils.environmental_constraints import check_all_constraints
    from utils.planning_risk_scorer import score_planning_risk
    from utils.land_registry import get_agricultural_land_class
    from utils.connection_offer_forecaster import forecast_connection_offer

    # Run all four checks in parallel
    env_result, planning_result, alc_result, grid_result = await asyncio.gather(
        check_all_constraints(lat, lon, radius_m=2000),
        score_planning_risk(pool, lat, lon, capacity_mw, technology),
        get_agricultural_land_class(lat, lon),
        forecast_connection_offer(pool, lat, lon, capacity_mw, technology),
        return_exceptions=True,
    )

    # Handle any exceptions gracefully
    if isinstance(env_result, Exception):
        log.warning("Environmental constraints failed: %s", env_result)
        env_result = {
            "environmental": {"risk_level": "unknown", "designations": []},
            "flood": {"risk_level": "unknown", "flood_zone": None},
            "heritage": {"risk_level": "none", "listed_buildings": []},
            "overall_risk": "unknown",
            "planning_impacts": ["Constraint check failed -- manual review needed."],
        }
    if isinstance(planning_result, Exception):
        log.warning("Planning risk scoring failed: %s", planning_result)
        planning_result = {
            "risk_score": 50, "risk_level": "medium", "verdict": "CAUTION",
            "factors": [], "recommendations": ["Manual planning risk assessment recommended."],
        }
    if isinstance(alc_result, Exception):
        log.warning("ALC lookup failed: %s", alc_result)
        alc_result = {
            "grade": "unknown", "description": "ALC data unavailable",
            "suitable_for_development": True,
            "note": "Unable to determine agricultural land classification.",
        }
    if isinstance(grid_result, Exception):
        log.warning("Grid connection forecast failed: %s", grid_result)
        grid_result = {
            "verdict": "CAUTION",
            "nearest_substation": None,
            "cost_estimate": {},
            "recommendations": ["Manual grid connection assessment recommended."],
        }

    return {
        "environmental": env_result.get("environmental", env_result),
        "flood": env_result.get("flood", {}),
        "heritage": env_result.get("heritage", {}),
        "overall_env_risk": env_result.get("overall_risk", "unknown"),
        "planning_impacts": env_result.get("planning_impacts", []),
        "constraints_geojson": env_result.get("constraints_geojson"),
        "planning_risk": planning_result,
        "alc": alc_result,
        "grid": grid_result,
    }


# ---------------------------------------------------------------------------
# Noise / shadow flicker / viewshed summaries
# ---------------------------------------------------------------------------

def _shadow_flicker_summary(lat: float, lon: float, capacity_mw: float, technology: str) -> dict:
    """Simplified shadow flicker assessment for solar/wind."""
    if "wind" in technology.lower():
        # Wind turbines: shadow flicker relevant within ~10x rotor diameter
        rotor_d = 120 if capacity_mw > 5 else 80  # metres
        zone_m = rotor_d * 10
        return {
            "relevant": True,
            "technology": "wind",
            "assessment_zone_m": zone_m,
            "hours_limit": 30,  # UK planning guidance: <30 hrs/yr
            "note": ("Shadow flicker assessment required within {:.0f}m of turbines. "
                     "UK BRE guidance limits exposure to <30 hours/year, <30 minutes/day.").format(zone_m),
            "recommendation": "Commission shadow flicker modelling study before planning submission.",
        }
    else:
        return {
            "relevant": False,
            "technology": "solar",
            "note": "Shadow flicker is not a material concern for ground-mount solar PV installations.",
            "recommendation": "No shadow flicker study required.",
        }


def _noise_assessment_summary(capacity_mw: float, technology: str) -> dict:
    """Simplified noise impact summary."""
    if "wind" in technology.lower():
        return {
            "relevant": True,
            "standard": "ETSU-R-97",
            "day_limit_dba": 35 + 10 * math.log10(max(capacity_mw, 0.1)),
            "night_limit_dba": 43,
            "note": "Wind farm noise must comply with ETSU-R-97. Background noise surveys required.",
            "recommendation": "Commission BS 4142 / ETSU-R-97 noise assessment.",
        }
    elif "bess" in technology.lower() or "battery" in technology.lower():
        return {
            "relevant": True,
            "standard": "BS 4142:2014+A1:2019",
            "note": "BESS cooling systems may generate tonal noise. BS 4142 assessment recommended for sites within 500m of receptors.",
            "recommendation": "Consider acoustic enclosures and review nearest sensitive receptors.",
        }
    else:
        return {
            "relevant": False,
            "note": "Solar PV has negligible operational noise (inverters ~45 dBA at 1m). Generally not a material planning concern.",
            "recommendation": "No formal noise assessment typically required for solar PV.",
        }


def _viewshed_summary(lat: float, lon: float, capacity_mw: float, technology: str) -> dict:
    """Simplified landscape and visual impact summary."""
    # Estimate Zone of Theoretical Visibility
    if "wind" in technology.lower():
        hub_height = 90 if capacity_mw > 5 else 65
        ztv_km = min(40, hub_height * 0.3)
        return {
            "relevant": True,
            "ztv_radius_km": round(ztv_km, 1),
            "hub_height_m": hub_height,
            "note": f"Zone of Theoretical Visibility extends to ~{ztv_km:.0f} km. LVIA required.",
            "recommendation": "Commission full Landscape and Visual Impact Assessment (LVIA) to EIA standard.",
        }
    else:
        panel_height = 3.0
        ztv_km = 2.0  # Solar is low-profile
        return {
            "relevant": capacity_mw > 5,
            "ztv_radius_km": ztv_km,
            "panel_height_m": panel_height,
            "note": ("Solar PV is low-profile (~{:.0f}m). Visual impact mainly within {:.0f} km. "
                     "Screening hedgerows typically mitigate impact.").format(panel_height, ztv_km),
            "recommendation": "Include landscape mitigation plan with native hedgerow screening." if capacity_mw > 5
                              else "Landscape assessment may be requested by LPA for sites >5 MW.",
        }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CONSTRAINT_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Princeps Constraint Report &mdash; {{ site_name }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { font-size: 13px; }
  body {
    font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #262626; background: #fff; line-height: 1.55;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  .page-break { page-break-after: always; break-after: page; }
  .page-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 28px; background: {{ brand.dark }}; color: #fff;
    margin-bottom: 20px; border-bottom: 3px solid {{ brand.primary }};
  }
  .page-header .logo { font-size: 18px; font-weight: 800; letter-spacing: 3px; color: {{ brand.primary }}; }
  .page-header .meta { font-size: 10px; color: #a0a0a0; letter-spacing: 0.5px; }
  .section-title {
    font-size: 17px; font-weight: 700; color: {{ brand.dark }};
    border-bottom: 3px solid {{ brand.primary }}; padding-bottom: 5px; margin-bottom: 14px;
  }
  .section-subtitle { font-size: 13px; font-weight: 600; color: {{ brand.dark }};
    margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #e0e0e0; }
  .card {
    background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }
  .card-header { font-size: 13px; font-weight: 700; color: {{ brand.dark }};
    margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
  .card-accent { border-left: 4px solid {{ brand.primary }}; }
  .card-accent-green { border-left: 4px solid {{ brand.green }}; }
  .card-accent-amber { border-left: 4px solid {{ brand.amber }}; }
  .card-accent-red { border-left: 4px solid {{ brand.red }}; }
  .kpi-strip { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
  .kpi-box { flex: 1; min-width: 100px; background: {{ brand.light }}; border-radius: 8px;
    padding: 10px 8px; text-align: center; border: 1px solid #e8e8e8; }
  .kpi-box-highlight { background: linear-gradient(135deg, {{ brand.dark }} 0%, #16213e 100%); border: none; }
  .kpi-box-highlight .kpi-value { color: {{ brand.primary }}; }
  .kpi-box-highlight .kpi-label { color: #a0a0a0; }
  .kpi-value { font-size: 20px; font-weight: 800; color: {{ brand.dark }}; }
  .kpi-label { font-size: 9px; color: {{ brand.grey }}; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }
  .verdict-badge { display: inline-block; padding: 8px 24px; border-radius: 6px;
    font-size: 18px; font-weight: 800; letter-spacing: 1px; color: #fff; }
  .verdict-GO { background: {{ brand.green }}; }
  .verdict-CAUTION { background: {{ brand.amber }}; color: {{ brand.dark }}; }
  .verdict-NO-GO { background: {{ brand.red }}; }
  table { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 8px; }
  th { background: {{ brand.dark }}; color: #fff; padding: 7px 10px; text-align: left;
    font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
  td { padding: 6px 10px; border-bottom: 1px solid #e8e8e8; vertical-align: top; }
  tr:nth-child(even) td { background: #fafafa; }
  .stat-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #f0f0f0; }
  .stat-label { color: {{ brand.grey }}; font-size: 11px; }
  .stat-value { font-weight: 700; font-size: 11px; color: {{ brand.dark }}; }
  .chart-img { max-width: 100%; height: auto; display: block; margin: 6px auto; }
  .two-col { display: flex; gap: 16px; margin-bottom: 12px; }
  .two-col > div { flex: 1; }
  .text-muted { color: {{ brand.grey }}; }
  .text-sm { font-size: 11px; }
  .text-xs { font-size: 9px; }
  .mt-4 { margin-top: 4px; }
  .mt-8 { margin-top: 8px; }
  .mb-8 { margin-bottom: 8px; }
  .mb-12 { margin-bottom: 12px; }
  .bold { font-weight: 700; }
  .center { text-align: center; }
  .page-footer { text-align: center; font-size: 9px; color: #a0a0a0;
    padding: 10px 0; border-top: 1px solid #e8e8e8; margin-top: 20px; }
  .risk-high { color: {{ brand.red }}; font-weight: 700; }
  .risk-medium { color: {{ brand.amber }}; font-weight: 700; }
  .risk-low { color: {{ brand.green }}; font-weight: 700; }
  .risk-none { color: {{ brand.green_light }}; font-weight: 600; }
  @page { size: A4; margin: 10mm 10mm 15mm 10mm; }
  @media print { .page-break { page-break-after: always; break-after: page; height: 0; } }
</style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- COVER PAGE -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div style="padding: 20px 28px;">
  <div class="page-header">
    <div class="logo">PRINCEPS</div>
    <div class="meta">Planning Constraint Report &mdash; {{ generated_at }}</div>
  </div>

  <div style="text-align: center; padding: 40px 0 20px;">
    <div style="font-size: 28px; font-weight: 800; color: {{ brand.dark }}; letter-spacing: 1px;">
      PLANNING CONSTRAINT REPORT
    </div>
    <div style="font-size: 16px; color: {{ brand.grey }}; margin-top: 8px;">
      Automated Site Screening &amp; Risk Assessment
    </div>
  </div>

  <div class="kpi-strip" style="margin-top: 24px;">
    <div class="kpi-box kpi-box-highlight">
      <div class="kpi-value">{{ site_name }}</div>
      <div class="kpi-label">Site Name</div>
    </div>
    <div class="kpi-box kpi-box-highlight">
      <div class="kpi-value">{{ "%.4f"|format(lat) }}, {{ "%.4f"|format(lon) }}</div>
      <div class="kpi-label">Coordinates (WGS84)</div>
    </div>
    <div class="kpi-box kpi-box-highlight">
      <div class="kpi-value">{{ capacity_mw }} MW</div>
      <div class="kpi-label">Proposed Capacity</div>
    </div>
    <div class="kpi-box kpi-box-highlight">
      <div class="kpi-value">{{ technology|title }}</div>
      <div class="kpi-label">Technology</div>
    </div>
  </div>

  <div class="center" style="margin: 24px 0;">
    <span class="verdict-badge verdict-{{ planning_verdict }}">{{ planning_verdict }}</span>
  </div>

  <div class="kpi-strip">
    <div class="kpi-box">
      <div class="kpi-value" style="color: {% if overall_risk == 'high' %}{{ brand.red }}{% elif overall_risk == 'medium' %}{{ brand.amber }}{% else %}{{ brand.green }}{% endif %};">
        {{ overall_risk|upper }}
      </div>
      <div class="kpi-label">Overall Constraint Risk</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value">{{ planning_risk_score }}</div>
      <div class="kpi-label">Planning Risk Score</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value">{{ alc.grade|upper }}</div>
      <div class="kpi-label">Agricultural Grade</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value">{{ grid_verdict }}</div>
      <div class="kpi-label">Grid Connection</div>
    </div>
  </div>

  {% if charts.constraint_summary %}
  <div class="card center">
    <div class="text-xs text-muted mb-8">CONSTRAINT RISK SUMMARY</div>
    <img src="data:image/png;base64,{{ charts.constraint_summary }}" alt="Constraint summary" class="chart-img">
  </div>
  {% endif %}

  <div class="page-footer">
    Princeps Constraint Report &mdash; Cover &mdash; {{ generated_at }}
  </div>
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- ENVIRONMENTAL DESIGNATIONS -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div style="padding: 20px 28px;">
  <div class="page-header">
    <div class="logo">PRINCEPS</div>
    <div class="meta">{{ site_name }} &mdash; Environmental Designations</div>
  </div>

  <h2 class="section-title">2. Environmental Designations</h2>

  <div class="two-col">
    <div>
      <div class="card {% if env_risk == 'high' %}card-accent-red{% elif env_risk == 'medium' %}card-accent-amber{% else %}card-accent-green{% endif %}">
        <div class="card-header">Statutory Designations Within 2km</div>
        <table>
          <tr><th>Designation Type</th><th>Status</th><th>Impact</th></tr>
          {% for dtype, label in [('sssi', 'SSSI'), ('sac', 'SAC'), ('spa', 'SPA'), ('ramsar', 'Ramsar Wetland'), ('aonb', 'AONB / National Landscape'), ('green_belt', 'Green Belt'), ('ancient_woodland', 'Ancient Woodland')] %}
          <tr>
            <td>{{ label }}</td>
            <td>
              {% set found = namespace(match=false) %}
              {% for d in designations %}
                {% if d.type == dtype %}
                  {% set found.match = true %}
                  {% if d.severity == 'hard' %}
                  <span class="risk-high">OVERLAP</span>
                  {% else %}
                  <span class="risk-medium">NEARBY ({{ "%.0f"|format(d.get('distance_m', 0)) }}m)</span>
                  {% endif %}
                {% endif %}
              {% endfor %}
              {% if not found.match %}
              <span class="risk-low">Clear</span>
              {% endif %}
            </td>
            <td class="text-xs text-muted">
              {% if dtype == 'sssi' %}Hard constraint if overlap. NPPF para 180 protection.
              {% elif dtype == 'sac' %}Habitats Regulations Assessment required if likely significant effect.
              {% elif dtype == 'spa' %}HRA screening required. Wild bird protection under Birds Directive.
              {% elif dtype == 'ramsar' %}International wetland protection. Treated same as SAC/SPA.
              {% elif dtype == 'aonb' %}Major development must demonstrate exceptional circumstances. NPPF para 177.
              {% elif dtype == 'green_belt' %}Very special circumstances required. NPPF Section 13.
              {% elif dtype == 'ancient_woodland' %}Irreplaceable habitat. NPPF para 180c &mdash; refusal unless wholly exceptional.
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </table>
        <div class="text-xs text-muted mt-4">
          Source: Natural England ArcGIS REST API + planning.data.gov.uk. Checked {{ generated_at }}.
        </div>
      </div>
    </div>

    <div>
      <div class="card {% if flood_risk == 'high' %}card-accent-red{% elif flood_risk == 'medium' %}card-accent-amber{% else %}card-accent-green{% endif %}">
        <div class="card-header">Flood Risk Assessment</div>
        <div class="stat-row">
          <span class="stat-label">Flood Zone</span>
          <span class="stat-value">{{ flood_data.get('flood_zone', 'N/A') }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Risk Level</span>
          <span class="stat-value risk-{{ flood_risk }}">{{ flood_risk|upper }}</span>
        </div>
        {% if flood_data.get('flood_areas') %}
        <div class="stat-row">
          <span class="stat-label">Flood Areas Nearby</span>
          <span class="stat-value">{{ flood_data.flood_areas|length }}</span>
        </div>
        {% endif %}
        <div class="text-xs text-muted mt-8">
          {% if flood_risk == 'high' %}
          Sequential and Exception Tests required under NPPF. Flood Risk Assessment mandatory.
          {% elif flood_risk == 'medium' %}
          Site-specific Flood Risk Assessment recommended for planning application.
          {% else %}
          No significant flood risk identified. Standard SUDS drainage plan sufficient.
          {% endif %}
        </div>
        <div class="text-xs text-muted mt-4">Source: Environment Agency Flood Map for Planning.</div>
      </div>

      <div class="card {% if heritage_risk == 'high' %}card-accent-red{% elif heritage_risk == 'medium' %}card-accent-amber{% else %}card-accent-green{% endif %}">
        <div class="card-header">Heritage Constraints</div>
        <div class="stat-row">
          <span class="stat-label">Risk Level</span>
          <span class="stat-value risk-{{ heritage_risk }}">{{ heritage_risk|upper }}</span>
        </div>
        {% if heritage_data.get('listed_buildings') %}
        <div class="stat-row">
          <span class="stat-label">Listed Buildings Nearby</span>
          <span class="stat-value">{{ heritage_data.listed_buildings|length }}</span>
        </div>
        {% for lb in heritage_data.listed_buildings[:5] %}
        <div class="text-xs" style="padding: 2px 0; color: {{ brand.dark }};">
          &bull; {{ lb.get('name', 'Listed building') }} (Grade {{ lb.get('grade', '?') }}, {{ "%.0f"|format(lb.get('distance_m', 0)) }}m)
        </div>
        {% endfor %}
        {% endif %}
        {% if heritage_data.get('conservation_areas') %}
        <div class="stat-row">
          <span class="stat-label">Conservation Areas</span>
          <span class="stat-value">{{ heritage_data.conservation_areas|length }}</span>
        </div>
        {% endif %}
        {% if heritage_data.get('scheduled_monuments') %}
        <div class="stat-row">
          <span class="stat-label">Scheduled Monuments</span>
          <span class="stat-value">{{ heritage_data.scheduled_monuments|length }}</span>
        </div>
        {% endif %}
        <div class="text-xs text-muted mt-4">Source: Historic England API. Setting impacts require Heritage Impact Assessment.</div>
      </div>
    </div>
  </div>

  <div class="page-footer">
    Princeps Constraint Report &mdash; Environmental &mdash; {{ generated_at }}
  </div>
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- AGRICULTURAL LAND, PLANNING RISK, GRID -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div style="padding: 20px 28px;">
  <div class="page-header">
    <div class="logo">PRINCEPS</div>
    <div class="meta">{{ site_name }} &mdash; Land, Planning &amp; Grid</div>
  </div>

  <h2 class="section-title">3. Agricultural Land Classification</h2>

  <div class="two-col">
    <div>
      <div class="card {% if alc.suitable_for_development %}card-accent-green{% else %}card-accent-red{% endif %}">
        <div class="card-header">ALC Assessment</div>
        <div class="stat-row">
          <span class="stat-label">Grade</span>
          <span class="stat-value" style="font-size: 16px;">{{ alc.grade|upper }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Description</span>
          <span class="stat-value">{{ alc.description }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Suitable for Development</span>
          <span class="stat-value {% if alc.suitable_for_development %}risk-low{% else %}risk-high{% endif %}">
            {{ "Yes" if alc.suitable_for_development else "No" }}
          </span>
        </div>
        <div class="text-xs text-muted mt-8">{{ alc.note }}</div>
        <div class="text-xs text-muted mt-4">
          NPPF footnote 62: Development of BMV land (grades 1, 2, 3a) should be avoided
          unless shown to be necessary. Grade 3b and below have fewer restrictions.
        </div>
      </div>
    </div>
    <div>
      {% if charts.planning_radar %}
      <div class="card center">
        <div class="text-xs text-muted mb-8">PLANNING RISK FACTORS</div>
        <img src="data:image/png;base64,{{ charts.planning_radar }}" alt="Planning risk radar" class="chart-img" style="max-height: 260px;">
      </div>
      {% endif %}
    </div>
  </div>

  <h2 class="section-title">4. Planning Risk Assessment</h2>

  <div class="kpi-strip">
    <div class="kpi-box kpi-box-highlight">
      <div class="kpi-value">{{ planning_risk_score }}</div>
      <div class="kpi-label">Risk Score (0-100)</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value risk-{{ planning_risk_level }}">{{ planning_risk_level|upper }}</div>
      <div class="kpi-label">Risk Level</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-value">{{ planning_verdict }}</div>
      <div class="kpi-label">Verdict</div>
    </div>
  </div>

  {% if planning_factors %}
  <div class="card card-accent">
    <div class="card-header">Risk Factor Breakdown</div>
    <table>
      <tr><th>Factor</th><th>Score</th><th>Weight</th><th>Detail</th></tr>
      {% for f in planning_factors %}
      <tr>
        <td class="bold">{{ f.get('name', 'N/A') }}</td>
        <td class="risk-{% if f.get('score', 50) >= 65 %}low{% elif f.get('score', 50) >= 40 %}medium{% else %}high{% endif %}">{{ f.get('score', 'N/A') }}</td>
        <td>{{ f.get('weight', 'N/A') }}</td>
        <td class="text-xs">{{ f.get('detail', '') }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  <h2 class="section-title" style="margin-top: 16px;">5. Grid Connection Feasibility</h2>

  <div class="card card-accent">
    <div class="card-header">Connection Forecast</div>
    <div class="stat-row">
      <span class="stat-label">Verdict</span>
      <span class="stat-value">
        <span class="verdict-badge verdict-{{ grid_verdict }}" style="font-size: 12px; padding: 4px 12px;">{{ grid_verdict }}</span>
      </span>
    </div>
    {% if grid_data.get('nearest_substation') %}
    <div class="stat-row">
      <span class="stat-label">Nearest Substation</span>
      <span class="stat-value">{{ grid_data.nearest_substation.get('name', 'N/A') }} ({{ "%.1f"|format(grid_data.nearest_substation.get('distance_km', 0)) }} km)</span>
    </div>
    {% endif %}
    {% if grid_data.get('cost_estimate') %}
    <div class="stat-row">
      <span class="stat-label">Estimated Connection Cost</span>
      <span class="stat-value">
        {% if grid_data.cost_estimate.get('p50_gbp') %}
        &pound;{{ "{:,.0f}".format(grid_data.cost_estimate.p50_gbp) }} (P50)
        {% else %}
        Contact DNO for budget estimate
        {% endif %}
      </span>
    </div>
    {% endif %}
    {% if grid_data.get('timeline_months') %}
    <div class="stat-row">
      <span class="stat-label">Estimated Timeline</span>
      <span class="stat-value">{{ grid_data.timeline_months }} months</span>
    </div>
    {% endif %}
  </div>

  <div class="page-footer">
    Princeps Constraint Report &mdash; Land, Planning &amp; Grid &mdash; {{ generated_at }}
  </div>
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- IMPACT ASSESSMENTS & RECOMMENDATIONS -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div style="padding: 20px 28px;">
  <div class="page-header">
    <div class="logo">PRINCEPS</div>
    <div class="meta">{{ site_name }} &mdash; Impact Assessments &amp; Recommendations</div>
  </div>

  <h2 class="section-title">6. Shadow Flicker Assessment</h2>
  <div class="card {% if shadow.relevant %}card-accent-amber{% else %}card-accent-green{% endif %}">
    <div class="stat-row">
      <span class="stat-label">Relevant to Technology</span>
      <span class="stat-value">{{ "Yes" if shadow.relevant else "No" }}</span>
    </div>
    {% if shadow.get('assessment_zone_m') %}
    <div class="stat-row">
      <span class="stat-label">Assessment Zone</span>
      <span class="stat-value">{{ shadow.assessment_zone_m }}m</span>
    </div>
    {% endif %}
    <div class="text-sm mt-8">{{ shadow.note }}</div>
    <div class="text-xs text-muted mt-4 bold">Recommendation: {{ shadow.recommendation }}</div>
  </div>

  <h2 class="section-title">7. Noise Assessment</h2>
  <div class="card {% if noise.relevant %}card-accent-amber{% else %}card-accent-green{% endif %}">
    <div class="stat-row">
      <span class="stat-label">Relevant to Technology</span>
      <span class="stat-value">{{ "Yes" if noise.relevant else "No" }}</span>
    </div>
    {% if noise.get('standard') %}
    <div class="stat-row">
      <span class="stat-label">Assessment Standard</span>
      <span class="stat-value">{{ noise.standard }}</span>
    </div>
    {% endif %}
    <div class="text-sm mt-8">{{ noise.note }}</div>
    <div class="text-xs text-muted mt-4 bold">Recommendation: {{ noise.recommendation }}</div>
  </div>

  <h2 class="section-title">8. Landscape &amp; Visual Impact</h2>
  <div class="card {% if viewshed.relevant %}card-accent-amber{% else %}card-accent-green{% endif %}">
    <div class="stat-row">
      <span class="stat-label">LVIA Required</span>
      <span class="stat-value">{{ "Yes" if viewshed.relevant else "Unlikely" }}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">ZTV Radius</span>
      <span class="stat-value">{{ viewshed.ztv_radius_km }} km</span>
    </div>
    <div class="text-sm mt-8">{{ viewshed.note }}</div>
    <div class="text-xs text-muted mt-4 bold">Recommendation: {{ viewshed.recommendation }}</div>
  </div>

  <h2 class="section-title">9. Recommendations</h2>
  <div class="card card-accent">
    <div class="card-header">Key Actions Before Planning Submission</div>
    <ol style="font-size: 11px; margin: 8px 0 0 16px; line-height: 2;">
    {% for rec in recommendations %}
      <li>{{ rec }}</li>
    {% endfor %}
    </ol>
  </div>

  {% if planning_impacts %}
  <div class="card card-accent-amber">
    <div class="card-header">Planning Impacts Identified</div>
    <ul style="font-size: 11px; margin: 8px 0 0 16px; line-height: 1.8;">
    {% for impact in planning_impacts %}
      <li>{{ impact }}</li>
    {% endfor %}
    </ul>
  </div>
  {% endif %}

  <div class="card" style="background: {{ brand.light }}; margin-top: 16px;">
    <div class="text-xs text-muted">
      <strong>Disclaimer:</strong> This automated constraint screening report is generated from
      publicly available data sources (Natural England, Environment Agency, Historic England,
      BMRS, Ordnance Survey) and should be treated as a preliminary desktop assessment.
      It does not replace formal Environmental Impact Assessment, site surveys, or
      professional planning advice. All findings should be verified with the relevant
      Local Planning Authority and statutory consultees before submission.
      <br><br>
      Generated by Princeps &mdash; {{ generated_at }}
    </div>
  </div>

  <div class="page-footer">
    Princeps Constraint Report &mdash; Recommendations &mdash; {{ generated_at }}
  </div>
</div>

</body>
</html>
"""


def _render_constraint_html(ctx: dict) -> str:
    """Render the constraint report HTML from inline template."""
    from jinja2 import Template
    tmpl = Template(_CONSTRAINT_REPORT_HTML)
    return tmpl.render(**ctx)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_constraint_report(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float = 50.0,
    technology: str = "solar",
    site_name: str | None = None,
) -> bytes:
    """
    Generate a professional planning constraint report as PDF bytes.

    Args:
        pool: asyncpg connection pool
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        capacity_mw: Proposed capacity in MW
        technology: Technology type (solar, wind, bess, etc.)
        site_name: Optional human-readable site name

    Returns:
        PDF bytes ready for HTTP response.
    """
    site_name = site_name or f"Site {lat:.4f}, {lon:.4f}"
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    log.info("Generating constraint report for %s (%.4f, %.4f) @ %.1f MW %s",
             site_name, lat, lon, capacity_mw, technology)

    # 1. Gather all constraint data
    data = await _gather_constraint_data(pool, lat, lon, capacity_mw, technology)

    # 2. Extract key values
    env_data = data["environmental"]
    flood_data = data["flood"]
    heritage_data = data["heritage"]
    planning_risk = data["planning_risk"]
    alc_data = data["alc"]
    grid_data = data["grid"]

    env_risk = env_data.get("risk_level", "unknown")
    flood_risk = flood_data.get("risk_level", "unknown")
    heritage_risk = heritage_data.get("risk_level", "none")
    planning_risk_score = planning_risk.get("risk_score", 50)
    planning_risk_level = planning_risk.get("risk_level", "medium")
    planning_verdict = planning_risk.get("verdict", "CAUTION")
    grid_verdict = grid_data.get("verdict", "CAUTION")
    overall_risk = data.get("overall_env_risk", "unknown")

    # Designations list for the table
    designations = env_data.get("designations", [])
    if not designations and isinstance(env_data, dict):
        # Try nested structure
        designations = []
        for key in ("sssi", "sac", "spa", "ramsar", "aonb", "green_belt", "ancient_woodland"):
            items = env_data.get(key, [])
            if isinstance(items, list):
                for item in items:
                    item["type"] = key
                    designations.append(item)

    # Planning factors
    planning_factors = planning_risk.get("factors", [])

    # Recommendations — merge from all sources
    recommendations = []
    for rec in planning_risk.get("recommendations", []):
        if rec not in recommendations:
            recommendations.append(rec)
    for rec in grid_data.get("recommendations", []):
        if rec not in recommendations:
            recommendations.append(rec)
    if not alc_data.get("suitable_for_development"):
        recommendations.append(
            "Agricultural Land Classification survey required — site appears to be BMV land (Grade {}).".format(
                alc_data.get("grade", "?")
            )
        )

    # Impact assessments
    shadow = _shadow_flicker_summary(lat, lon, capacity_mw, technology)
    noise = _noise_assessment_summary(capacity_mw, technology)
    viewshed = _viewshed_summary(lat, lon, capacity_mw, technology)

    if shadow.get("relevant"):
        recommendations.append(shadow["recommendation"])
    if noise.get("relevant"):
        recommendations.append(noise["recommendation"])
    if viewshed.get("relevant"):
        recommendations.append(viewshed["recommendation"])

    planning_impacts = data.get("planning_impacts", [])

    # 3. Generate charts
    charts = {}
    try:
        charts["constraint_summary"] = _constraint_summary_chart(data)
    except Exception as e:
        log.debug("Constraint summary chart failed: %s", e)

    try:
        if planning_factors:
            charts["planning_radar"] = _planning_risk_radar(planning_factors)
    except Exception as e:
        log.debug("Planning radar chart failed: %s", e)

    # 4. Render HTML
    ctx = {
        "site_name": site_name,
        "lat": lat,
        "lon": lon,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "generated_at": generated_at,
        "brand": BRAND,
        "overall_risk": overall_risk,
        "planning_verdict": planning_verdict,
        "planning_risk_score": planning_risk_score,
        "planning_risk_level": planning_risk_level,
        "planning_factors": planning_factors,
        "env_risk": env_risk,
        "flood_risk": flood_risk,
        "flood_data": flood_data,
        "heritage_risk": heritage_risk,
        "heritage_data": heritage_data,
        "designations": designations,
        "alc": alc_data,
        "grid_verdict": grid_verdict,
        "grid_data": grid_data,
        "shadow": shadow,
        "noise": noise,
        "viewshed": viewshed,
        "recommendations": recommendations,
        "planning_impacts": planning_impacts,
        "charts": charts,
    }

    html = _render_constraint_html(ctx)

    # 5. Convert to PDF using existing html_to_pdf from report_renderer
    from utils.report_renderer import html_to_pdf
    pdf_bytes = await html_to_pdf(html)

    log.info("Constraint report generated: %d bytes, %d recommendations",
             len(pdf_bytes), len(recommendations))

    return pdf_bytes
