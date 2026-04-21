"""
Princeps Grid Connection Report — COUNCIL-1 rework #7.

Institutional-grade grid connection assessment PDF for DNO / lender review.

Sections shipped (per paperwork_rewrite_spec.md §1):
  1.  Cover / transaction header / addressee
  2.  Reliance statement + revision control
  3.  Executive summary (verdict: viable / viable-with-works / not-viable)
  4.  Proposal summary (capacity, tech, OSGB ref via pyproj EPSG:4326->27700)
  5.  Point of Connection (substation, voltage, RAG, ownership DNO/IDNO/TO,
       LTDS publication + table/page citation per DNO)
  6.  Headroom analysis (firm / non-firm, accepted queue, in-progress,
       forecast demand growth — via app.analysis.headroom where POC id is
       resolvable; data-driven fallback from assess_connection() otherwise)
  7.  Power flow study (N / N-1) — calls utils.grid_power_flow via the
       grid_connection_analyser.tier2_power_flow subprocess bridge; per-branch
       loading + per-bus voltage table with RAG.
  8.  CCCM v19 cost breakdown (Sole Use, Shared Use w/ reinforcement factor,
       Security payment, Connection charge methodology split, Commit-and-pay
       vs aggregated reinforcement). P10/P50/P90 per voltage option.
  9.  Protection & interface settings (G99 Issue 2 cross-reference).
  10. Commissioning plan.
  11. Provenance + reliance + revision history.

Input: project_id (UUID). Falls back to lat/lon/capacity if project_id not
given (backwards compatibility).

Regulatory citations embedded:
  - ENA EREC G99 Issue 2 (10 Mar 2025).
  - Ofgem-approved Common Connection Charging Methodology (CCCM) v19.
  - Distribution Code v43.
  - The project DNO's LTDS (Licence Condition 25).
  - Engineering Recommendations P28/P29 (voltage limits).
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from jinja2 import Environment, FileSystemLoader

from utils.grid_connection_analyser import (
    assess_connection,
    estimate_connection_cost,
    tier2_power_flow,
)
from utils.sld_generator import generate_grid_connection_sld
from utils.g99_table_101 import get_table_101

log = logging.getLogger("princeps.report_grid_connection")

# Legacy templates/report/* kept for backward compatibility with other packs
# (g99_pack, dco_pack, lender_pack) that still extend the old institutional
# base. The *new* rewritten Grid Connection Report renders from
# templates/grid_connection/main.html.j2 which extends templates/_shared/.
_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATES_DIR = _TEMPLATES_ROOT / "report"        # legacy


# ---------------------------------------------------------------------------
# Brand palette — consolidated gold per paperwork_rewrite_spec §b
# ---------------------------------------------------------------------------
BRAND = {
    "gold": "#D4A018",
    "gold_light": "#E8C54A",
    "gold_dark": "#B88B0E",
    "navy": "#1B365D",
    "teal": "#007A8C",
    "dark": "#1a1a2e",
    "green": "#24a148",
    "amber": "#f1c21b",
    "red": "#da1e28",
    "grey": "#697077",
    "grey_light": "#a8a8a8",
    "light": "#f4f4f4",
    "white": "#ffffff",
}

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)

# Institutional rewrite: templates/_shared/* + templates/grid_connection/*
_institutional_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_ROOT)),
    autoescape=True,
)


# ---------------------------------------------------------------------------
# DNO / LTDS citation registry
# ---------------------------------------------------------------------------
# Per Ofgem Distribution Licence Condition 25 every DNO must publish a Long
# Term Development Statement annually.  We cite the most recent publication
# plus the table that typically holds the primary-substation firm capacity
# and headroom figures.  Page numbers vary between DNO editions; the page
# number here is the indicative entry-point for the tabular data and must
# be verified against the actual edition held in LTDS_CIM_INGESTER runs.
LTDS_REGISTRY: dict[str, dict[str, str]] = {
    "UKPN": {
        "long_name": "UK Power Networks (EPN, LPN, SPN)",
        "licence_areas": "EPN, LPN, SPN",
        "publication": "UKPN Long Term Development Statement 2024",
        "publication_date": "November 2024",
        "primary_table": "Table 2b — Primary Substation Firm Capacity",
        "page_ref": "Vol. 2 §4.3, p. 58-117",
        "url": "https://www.ukpowernetworks.co.uk/our-services/ltds",
    },
    "NGED": {
        "long_name": "National Grid Electricity Distribution (formerly WPD)",
        "licence_areas": "WMID, EMID, SWALES, SWEST",
        "publication": "NGED Long Term Development Statement 2024 (CIM Stage 1.3)",
        "publication_date": "September 2024",
        "primary_table": "Table 2 — Firm Capacity at BSP / Primary",
        "page_ref": "EMID §3.2 p. 22; WMID §3.2 p. 24; SWALES §3.2 p. 20; SWEST §3.2 p. 21",
        "url": "https://www.nationalgrid.co.uk/ltds",
    },
    "SPEN": {
        "long_name": "SP Energy Networks (SPD, SPM)",
        "licence_areas": "SPD, SPM",
        "publication": "SPEN Long Term Development Statement 2024",
        "publication_date": "October 2024",
        "primary_table": "Table 3 — Demand / Generation Headroom",
        "page_ref": "SPD §5.2 p. 41; SPM §5.2 p. 48",
        "url": "https://www.spenergynetworks.co.uk/pages/ltds.aspx",
    },
    "SSEN": {
        "long_name": "Scottish & Southern Electricity Networks",
        "licence_areas": "NSHI (SHEPD), SEPD",
        "publication": "SSEN LTDS 2024",
        "publication_date": "November 2024",
        "primary_table": "Appendix A — Generation Headroom by GSP Group",
        "page_ref": "NSHI p. 67; SEPD p. 72",
        "url": "https://www.ssen.co.uk/aboutus/ltds/",
    },
    "NPG": {
        "long_name": "Northern Powergrid (NEDL, YEDL)",
        "licence_areas": "NEDL, YEDL",
        "publication": "Northern Powergrid LTDS 2024",
        "publication_date": "September 2024",
        "primary_table": "Table 4 — Primary Substation Capacity",
        "page_ref": "NEDL §6.3 p. 36; YEDL §6.3 p. 38",
        "url": "https://www.northernpowergrid.com/ltds",
    },
    "ENWL": {
        "long_name": "Electricity North West",
        "licence_areas": "ENWL (NWEST)",
        "publication": "ENWL LTDS 2024",
        "publication_date": "October 2024",
        "primary_table": "Section 4 — Bulk Supply Point Firm Capacity",
        "page_ref": "§4.2 p. 28-45",
        "url": "https://www.enwl.co.uk/ltds",
    },
}

# Alternate DNO code aliases → canonical key
_DNO_ALIASES = {
    "WPD": "NGED", "NG ED": "NGED", "NATIONAL GRID ED": "NGED",
    "SP": "SPEN", "SP ENERGY NETWORKS": "SPEN",
    "SSE": "SSEN", "SSEH": "SSEN", "SEPD": "SSEN", "SHEPD": "SSEN",
    "NORTHERN POWERGRID": "NPG", "NPG NEDL": "NPG", "NPG YEDL": "NPG",
    "ELECTRICITY NORTH WEST": "ENWL", "NWEST": "ENWL",
    "UK POWER NETWORKS": "UKPN", "EPN": "UKPN", "LPN": "UKPN", "SPN": "UKPN",
}


def _resolve_dno_key(code: str | None) -> str | None:
    if not code:
        return None
    k = code.strip().upper()
    if k in LTDS_REGISTRY:
        return k
    if k in _DNO_ALIASES:
        return _DNO_ALIASES[k]
    for canonical, info in LTDS_REGISTRY.items():
        if canonical in k:
            return canonical
        if info["licence_areas"].replace(" ", "").upper().find(k) >= 0:
            return canonical
    return None


# ---------------------------------------------------------------------------
# CCCM v19 cost breakdown
# ---------------------------------------------------------------------------
# The Common Connection Charging Methodology (CCCM) v19 is the Ofgem-approved
# DCUSA schedule governing connection charges for UK DNOs.  It splits costs
# into four buckets:
#   (a) Sole Use — directly attributable to the customer (cable, POC switchgear,
#       customer bay, metering).
#   (b) Shared Use — assets shared with other network users at the POC
#       (transformers, switchboards).  A reinforcement factor determines the
#       customer's share.
#   (c) Security Payment — up-front deposit against asset write-off risk.
#   (d) Connection Charge — the summed invoice.
# Per-voltage indicative rates (P10/P50/P90) use the project's memory-rooted
# rates (11 kV £80k/km, 33 kV £150k/km, 132 kV £500k/km) with a +/- 25% band.
CCCM_CABLE_RATE_GBP_KM = {
    11: 80_000,
    33: 150_000,
    66: 300_000,
    132: 500_000,
    400: 1_400_000,
}

CCCM_SWITCHGEAR_GBP = {
    11: 120_000,
    33: 300_000,
    66: 500_000,
    132: 900_000,
    400: 2_500_000,
}

CCCM_BAY_GBP = {
    11: 80_000,
    33: 180_000,
    66: 320_000,
    132: 650_000,
    400: 1_800_000,
}

# Security deposit typically 10–15% of total sole+shared use.
CCCM_SECURITY_PCT = 0.12

# Shared-use reinforcement factor: customer share depends on whether queued
# capacity triggers a reinforcement project.  CCCM v19 defines a simple
# proportionality rule: customer pays (their_MW / total_reinforcement_MW).
def _shared_use_share(capacity_mw: float, queued_mw: float) -> float:
    total = capacity_mw + max(queued_mw, 0.0)
    if total <= 0:
        return 1.0
    return round(capacity_mw / total, 3)


def cccm_v19_breakdown(
    distance_km: float,
    capacity_mw: float,
    voltage_kv: int,
    queued_mw: float = 0.0,
    triggers_reinforcement: bool = False,
) -> dict:
    """Return a CCCM v19-shaped cost breakdown for a single voltage option.

    Produces sole use / shared use / security payment / reinforcement buckets
    with P10/P50/P90 bands and a 'commit-and-pay vs aggregated' split note.
    """
    vkv = int(voltage_kv)
    cable_rate = CCCM_CABLE_RATE_GBP_KM.get(vkv, CCCM_CABLE_RATE_GBP_KM[33])
    sg = CCCM_SWITCHGEAR_GBP.get(vkv, 300_000)
    bay = CCCM_BAY_GBP.get(vkv, 180_000)

    # Sole Use — directly attributable to the customer.
    sole_cable = distance_km * cable_rate
    sole_bay = bay
    sole_metering = 15_000 if capacity_mw > 1 else 5_000
    sole_civils = distance_km * 30_000
    sole_use_p50 = sole_cable + sole_bay + sole_metering + sole_civils

    # Shared Use — substation assets benefitting multiple parties.
    share_ratio = _shared_use_share(capacity_mw, queued_mw)
    shared_switchgear = sg * share_ratio
    shared_transformer = capacity_mw * 25_000 * share_ratio
    shared_use_p50 = shared_switchgear + shared_transformer

    # Reinforcement — triggered if shared-use assets are undersized.
    if triggers_reinforcement:
        reinforcement_p50 = capacity_mw * 45_000  # upstream feeder / bulk reinf.
    else:
        reinforcement_p50 = capacity_mw * 12_000  # contingent / commit-and-pay

    # Security deposit (12% of sole+shared, per CCCM v19 Schedule 4).
    security_p50 = (sole_use_p50 + shared_use_p50) * CCCM_SECURITY_PCT

    # P10/P90 bands — CCCM tolerance is ~±25% before detailed design.
    def band(v: float) -> dict:
        return {"p10": round(v * 0.78), "p50": round(v), "p90": round(v * 1.28)}

    total_p50 = sole_use_p50 + shared_use_p50 + reinforcement_p50 + security_p50

    return {
        "voltage_kv": vkv,
        "distance_km": round(distance_km, 2),
        "capacity_mw": capacity_mw,
        "share_ratio": share_ratio,
        "triggers_reinforcement": triggers_reinforcement,
        "lines": [
            {
                "cccm_ref": "CCCM v19 Sch.1 §A — Sole Use",
                "item": f"HV cable ({vkv} kV, {distance_km:.2f} km)",
                "range": band(sole_cable),
            },
            {
                "cccm_ref": "CCCM v19 Sch.1 §A — Sole Use",
                "item": f"Customer bay ({vkv} kV switchgear + protection)",
                "range": band(sole_bay),
            },
            {
                "cccm_ref": "CCCM v19 Sch.1 §A — Sole Use",
                "item": "Metering & CT/VT",
                "range": band(sole_metering),
            },
            {
                "cccm_ref": "CCCM v19 Sch.1 §A — Sole Use",
                "item": "Civils, trenching & wayleave",
                "range": band(sole_civils),
            },
            {
                "cccm_ref": f"CCCM v19 Sch.1 §B — Shared Use (ratio {share_ratio:.0%})",
                "item": "Primary switchgear attribution",
                "range": band(shared_switchgear),
            },
            {
                "cccm_ref": f"CCCM v19 Sch.1 §B — Shared Use (ratio {share_ratio:.0%})",
                "item": "Transformer capacity attribution",
                "range": band(shared_transformer),
            },
            {
                "cccm_ref": ("CCCM v19 Sch.1 §C — Reinforcement (commit-and-pay)"
                             if not triggers_reinforcement
                             else "CCCM v19 Sch.1 §C — Reinforcement (aggregated)"),
                "item": ("Upstream feeder reinforcement"
                         if triggers_reinforcement
                         else "Contingent reinforcement allowance"),
                "range": band(reinforcement_p50),
            },
            {
                "cccm_ref": "CCCM v19 Sch.4 — Security Payment (12%)",
                "item": "Security deposit against asset write-off",
                "range": band(security_p50),
            },
        ],
        "totals": {
            "sole_use": band(sole_use_p50),
            "shared_use": band(shared_use_p50),
            "reinforcement": band(reinforcement_p50),
            "security_payment": band(security_p50),
            "grand_total": band(total_p50),
        },
        "commit_vs_aggregated": (
            "Commit-and-pay: customer pays only for direct reinforcement triggered by their "
            "connection. Aggregated: costs socialised across all queued applicants at this POC. "
            "Current CCCM v19 default is aggregated where the reinforcement project is "
            "identified in the DNO's published RIIO-ED2 investment plan; otherwise commit-and-pay."
        ),
    }


# ---------------------------------------------------------------------------
# OSGB reference — proper pyproj transform (not a linear approx)
# ---------------------------------------------------------------------------
def _wgs84_to_osgb(lat: float, lon: float) -> dict:
    """Convert WGS84 lat/lon to OSGB36 easting/northing + 10-figure grid ref."""
    try:
        from pyproj import Transformer
        t = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
        easting, northing = t.transform(lon, lat)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("pyproj OSGB transform failed: %s", e)
        return {"easting": None, "northing": None, "grid_ref": "OSGB unavailable"}

    # Build 10-figure OSGB grid reference (1 m resolution).
    square_letters = _osgb_square(easting, northing)
    if square_letters:
        e_rem = int(easting) % 100_000
        n_rem = int(northing) % 100_000
        grid_ref = f"{square_letters} {e_rem:05d} {n_rem:05d}"
    else:
        grid_ref = f"E {int(easting):07d}  N {int(northing):07d} (outside GB 500km grid)"

    return {
        "easting": int(easting),
        "northing": int(northing),
        "grid_ref": grid_ref,
    }


def _osgb_square(easting: float, northing: float) -> str | None:
    """Map easting/northing (m) to the two-letter OSGB national grid square.

    Implements the standard Ordnance Survey two-letter tile scheme: a 5x5 grid
    of 500 km squares (outer letter) each further subdivided into a 5x5 grid
    of 100 km squares (inner letter). Letter sequence A..Z skipping 'I'; the
    origin square SV sits at 500 km west, 0 km north of the true origin so we
    shift easting/northing by +1000 km / +500 km before indexing.
    """
    # Shift into the "false" OS grid whose origin is at the SW corner of square A.
    e = easting + 1_000_000
    n = northing + 500_000

    e500k = int(e // 500_000)
    n500k = int(n // 500_000)
    e100k = int((e % 500_000) // 100_000)
    n100k = int((n % 500_000) // 100_000)

    if not (0 <= e500k < 5 and 0 <= n500k < 5):
        return None

    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    first_idx = (4 - n500k) * 5 + e500k
    second_idx = (4 - n100k) * 5 + e100k
    if first_idx >= len(letters) or second_idx >= len(letters):
        return None
    return f"{letters[first_idx]}{letters[second_idx]}"


# ---------------------------------------------------------------------------
# Verdict mapping: GO / CAUTION / NO-GO  →  viable / viable-with-works / not-viable
# ---------------------------------------------------------------------------
def _viability_verdict(raw: str, has_headroom: bool, reinforcement_triggered: bool) -> str:
    raw_u = (raw or "").upper()
    if raw_u in ("GO",) and has_headroom and not reinforcement_triggered:
        return "viable"
    if raw_u in ("NO-GO", "NO_GO"):
        return "not-viable"
    # CAUTION or GO-with-issues → viable-with-works
    return "viable-with-works"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
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


def _fmt_gbp(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"\u00a3{value:,.0f}"


def _fmt_gbp_k(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"\u00a3{value / 1000:,.0f}k"


def _rag_class(rag: str | None) -> str:
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


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def _cccm_waterfall_chart(breakdown: dict) -> str:
    """Waterfall of CCCM v19 categories summing to the P50 total."""
    totals = breakdown.get("totals") or {}
    cats = ["Sole Use", "Shared Use", "Reinforcement", "Security"]
    vals = [
        (totals.get("sole_use") or {}).get("p50", 0) / 1000,
        (totals.get("shared_use") or {}).get("p50", 0) / 1000,
        (totals.get("reinforcement") or {}).get("p50", 0) / 1000,
        (totals.get("security_payment") or {}).get("p50", 0) / 1000,
    ]
    total = sum(vals)
    if total <= 0:
        return ""

    fig, ax = plt.subplots(figsize=(7, 3.3))
    _apply_style(ax, fig)

    cumulative = 0.0
    colours = [BRAND["gold"], BRAND["teal"], BRAND["amber"], BRAND["navy"]]
    for i, (cat, v) in enumerate(zip(cats, vals)):
        ax.bar(i, v, bottom=cumulative, color=colours[i], width=0.55,
               edgecolor="white", linewidth=1)
        ax.text(i, cumulative + v / 2, _fmt_gbp_k(v * 1000),
                ha="center", va="center", fontsize=9, fontweight="bold",
                color=BRAND["white"])
        cumulative += v
    ax.bar(len(cats), total, color=BRAND["dark"], width=0.55,
           edgecolor="white", linewidth=1)
    ax.text(len(cats), total / 2, _fmt_gbp_k(total * 1000),
            ha="center", va="center", fontsize=9, fontweight="bold",
            color=BRAND["gold"])

    ax.set_xticks(list(range(len(cats) + 1)))
    ax.set_xticklabels(cats + ["P50 Total"], fontsize=9)
    ax.set_ylabel("Cost (\u00a3 thousands)", fontsize=9)
    ax.set_title("CCCM v19 Cost Waterfall", fontsize=10, fontweight="600", pad=8)
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _voltage_options_chart(options: list[dict]) -> str:
    if not options:
        return ""

    labels = [f"{o['voltage_kv']} kV" for o in options]
    p10 = [o["cost_gbp"]["p10"] / 1_000_000 for o in options]
    p50 = [o["cost_gbp"]["p50"] / 1_000_000 for o in options]
    p90 = [o["cost_gbp"]["p90"] / 1_000_000 for o in options]

    x = np.arange(len(labels))
    w = 0.25
    fig, ax = plt.subplots(figsize=(7, 3.3))
    _apply_style(ax, fig)
    ax.bar(x - w, p10, w, label="P10", color=BRAND["green"], alpha=0.8)
    ax.bar(x, p50, w, label="P50", color=BRAND["gold"], alpha=0.9)
    ax.bar(x + w, p90, w, label="P90", color=BRAND["red"], alpha=0.8)
    for i in range(len(labels)):
        ax.text(i, p50[i] + (max(p90) * 0.02 if p90 else 0),
                f"\u00a3{p50[i]:.1f}M", ha="center", va="bottom",
                fontsize=8, fontweight="bold", color=BRAND["dark"])
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10, fontweight="600")
    ax.set_ylabel("Cost (\u00a3 million)", fontsize=9)
    ax.legend(fontsize=8, framealpha=0.9, edgecolor="none")
    ax.grid(axis="y", alpha=0.15, linewidth=0.4)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _candidate_ranking_chart(candidates: list[dict]) -> str:
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
        ax.text(s + 2, i, f"{s}/100 ({d:.1f} km)", va="center", fontsize=8,
                color=BRAND["dark"])
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 110)
    ax.set_xlabel("Suitability Score", fontsize=9)
    ax.axvline(x=70, color=BRAND["green"], lw=0.6, ls=":", alpha=0.5)
    ax.axvline(x=40, color=BRAND["red"], lw=0.6, ls=":", alpha=0.5)
    ax.grid(axis="x", alpha=0.15, linewidth=0.4)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["green"],
               markersize=7, label="Viable (\u226570)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["amber"],
               markersize=7, label="With works (40-69)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BRAND["red"],
               markersize=7, label="Not viable (<40)"),
    ], loc="lower right", fontsize=7, framealpha=0.9, edgecolor="none")
    fig.tight_layout()
    return _fig_to_b64(fig)


def _power_flow_chart(pf_results: dict) -> str:
    bus_results = pf_results.get("bus_results", [])
    line_results = pf_results.get("line_results", [])
    if not bus_results and not line_results:
        return ""

    fig, axes = plt.subplots(1, 2, figsize=(7, 3.2))
    ax1, ax2 = axes
    _apply_style(ax1, fig)
    _apply_style(ax2, fig)

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
        ax1.bar(x, voltages, color=colours, width=0.55)
        ax1.axhline(y=1.06, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6)
        ax1.axhline(y=0.94, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6)
        ax1.axhline(y=1.0, color=BRAND["grey"], lw=0.5, ls=":", alpha=0.4)
        ax1.set_xticks(x)
        ax1.set_xticklabels(bus_names, fontsize=7, rotation=45, ha="right")
        ax1.set_ylabel("Voltage (p.u.)", fontsize=9)
        ax1.set_title("N bus voltages (P28 limits \u00b16%)", fontsize=9, fontweight="600")
        ax1.set_ylim(0.90, 1.12)
    else:
        ax1.text(0.5, 0.5, "No bus data", transform=ax1.transAxes,
                 ha="center", va="center", color=BRAND["grey"])

    if line_results:
        line_names = [l.get("name", f"Line {i}")[:15] for i, l in enumerate(line_results[:8])]
        loadings = [l.get("loading_pct", 0) for l in line_results[:8]]
        x2 = np.arange(len(line_names))
        colours2 = [
            BRAND["green"] if ld <= 80 else BRAND["amber"] if ld <= 100 else BRAND["red"]
            for ld in loadings
        ]
        ax2.barh(x2, loadings, color=colours2, height=0.55)
        ax2.axvline(x=100, color=BRAND["red"], lw=0.8, ls="--", alpha=0.6)
        ax2.axvline(x=80, color=BRAND["amber"], lw=0.6, ls=":", alpha=0.5)
        ax2.set_yticks(x2)
        ax2.set_yticklabels(line_names, fontsize=7)
        ax2.set_xlabel("Loading (%)", fontsize=9)
        ax2.set_title("N thermal loading", fontsize=9, fontweight="600")
        ax2.invert_yaxis()
    else:
        ax2.text(0.5, 0.5, "No line data", transform=ax2.transAxes,
                 ha="center", va="center", color=BRAND["grey"])

    fig.tight_layout(w_pad=3)
    return _fig_to_b64(fig)


def generate_charts(report_data: dict) -> dict[str, str]:
    charts: dict[str, str] = {}

    cccm = report_data.get("cccm")
    if cccm:
        c = _cccm_waterfall_chart(cccm)
        if c:
            charts["cccm_waterfall"] = c

    vopts = report_data.get("voltage_options", [])
    if vopts:
        c = _voltage_options_chart(vopts)
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
# Voltage option costs (CCCM-aware)
# ---------------------------------------------------------------------------
def compute_voltage_options(distance_km: float, capacity_mw: float) -> list[dict]:
    """Baseline P10/P50/P90 cost for 11/33/132 kV options (legacy rate model)."""
    options = []
    for voltage_kv in (11, 33, 132):
        est = estimate_connection_cost(distance_km, capacity_mw, voltage_kv)
        est["voltage_kv"] = voltage_kv
        options.append(est)
    return options


# ---------------------------------------------------------------------------
# Headroom bridge — call app.analysis.headroom where possible, degrade otherwise
# ---------------------------------------------------------------------------
async def _headroom_analysis(pool, best_candidate: dict | None) -> dict:
    """Invoke app.analysis.headroom for the best-candidate substation.

    Falls back to the data-driven fields on the candidate itself if the
    analysis module is unavailable or the POC lacks an external id.
    """
    result = {
        "firm_capacity_mw": None,
        "non_firm_capacity_mw": None,
        "accepted_queue_mw": None,
        "in_progress_queue_mw": None,
        "forecast_demand_growth_mw": None,
        "p10_mw": None,
        "p50_mw": None,
        "p90_mw": None,
        "confidence": 0.0,
        "explanation": "Headroom analysis not available — POC substation id could not be resolved.",
        "source": "fallback",
    }

    if not best_candidate:
        return result

    firm = best_candidate.get("transformer_rating_mva")
    if firm is not None:
        result["firm_capacity_mw"] = round(float(firm) * 0.95, 1)
    demand = best_candidate.get("demand_mw")
    result["non_firm_capacity_mw"] = (
        round(float(firm) * 1.10, 1) if firm is not None else None
    )
    q = best_candidate.get("queue", {}) or {}
    result["accepted_queue_mw"] = float(q.get("ecr_queued_mw", 0) or 0)
    result["in_progress_queue_mw"] = float(q.get("tec_mw", 0) or 0)

    try:
        from app.analysis.headroom import headroom as _headroom_fn  # noqa: WPS433
        ext_id = best_candidate.get("external_id") or best_candidate.get("substation_id")
        if ext_id and pool is not None:
            analysis = await _headroom_fn(str(ext_id), "year", "central", pool=pool)
            result.update({
                "p10_mw": round(analysis.p10, 1) if analysis.p10 is not None else None,
                "p50_mw": round(analysis.p50, 1) if analysis.p50 is not None else None,
                "p90_mw": round(analysis.p90, 1) if analysis.p90 is not None else None,
                "confidence": analysis.confidence,
                "explanation": analysis.explanation,
                "source": "app.analysis.headroom",
            })
            # Estimate forecast growth as (firm - p50 - queued).
            if result["p50_mw"] is not None and firm is not None:
                usable = float(firm) * 0.95
                residual = usable - (result["accepted_queue_mw"] or 0)
                growth = max(0.0, residual - result["p50_mw"])
                result["forecast_demand_growth_mw"] = round(growth, 1)
    except Exception as e:  # noqa: BLE001
        log.warning("headroom analysis degraded: %s", e)
        result["explanation"] = f"headroom degraded: {e}"

    return result


# ---------------------------------------------------------------------------
# Data aggregator
# ---------------------------------------------------------------------------
async def aggregate_grid_connection_data(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float,
    site_name: str | None = None,
    technology: str = "solar",
    run_power_flow: bool = True,
    project_id: str | None = None,
    project_meta: dict | None = None,
    pool=None,
) -> dict[str, Any]:
    """Collect every input needed for the rewritten report template."""
    site_label = site_name or f"Site {lat:.4f}, {lon:.4f}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    assessment = await assess_connection(conn, lat, lon, capacity_mw, technology)

    best = assessment.get("best_candidate")
    distance_km = best["distance_km"] if best else 5.0

    voltage_options = compute_voltage_options(distance_km, capacity_mw)

    # Pick the DNO + its LTDS citation.
    dno_area = assessment.get("dno_area") or {}
    dno_key = _resolve_dno_key(dno_area.get("code") or dno_area.get("name"))
    ltds = LTDS_REGISTRY.get(dno_key) if dno_key else None

    # CCCM v19 breakdown at the recommended voltage for the best candidate.
    rec_v = int((best or {}).get("voltage_kv") or _best_voltage_for_capacity(capacity_mw))
    queued_mw = 0.0
    if best and best.get("queue"):
        queued_mw = float(best["queue"].get("ecr_queued_mw", 0) or 0)
    headroom_mw = (best or {}).get("gen_headroom_mw")
    triggers_reinforcement = (
        headroom_mw is not None and float(headroom_mw) < capacity_mw
    )
    cccm = cccm_v19_breakdown(
        distance_km=distance_km,
        capacity_mw=capacity_mw,
        voltage_kv=rec_v,
        queued_mw=queued_mw,
        triggers_reinforcement=triggers_reinforcement,
    )

    # Power flow (N + N-1). Runs subprocess; gracefully degrades on error.
    power_flow = None
    if run_power_flow:
        try:
            power_flow = await tier2_power_flow(
                conn, lat, lon, capacity_mw, technology, contingency=True,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Tier 2 power flow failed: %s", e)
            power_flow = {"success": False, "error": str(e)}

    # Headroom (firm / non-firm / queue / forecast growth).
    headroom = await _headroom_analysis(pool, best)

    # OSGB grid reference (proper pyproj transform).
    osgb = _wgs84_to_osgb(lat, lon)

    # SLD.
    poc_voltage_kv = float((best or {}).get("voltage_kv") or 33.0)
    fault_level_ka = (best or {}).get("fault_level_ka")
    poc_name = (best or {}).get("name") or "Nearest DNO Primary"
    feeder_kind = "bess" if technology == "bess" else "pv"
    feeders = [{
        "kind": feeder_kind,
        "rating_kw": capacity_mw * 1000.0,
        "label": f"{technology.upper()} site",
    }]
    try:
        sld = generate_grid_connection_sld(
            site_voltage_kv=0.4,
            poc_voltage_kv=poc_voltage_kv,
            poc_name=poc_name,
            fault_level_ka=fault_level_ka,
            feeders=feeders,
            capacity_kw=capacity_mw * 1000.0,
            site_name=site_label,
        )
        sld_render = {
            "png_base64": sld["png_base64"],
            "meta": sld["meta"],
            "feeders": sld["feeders"],
        }
    except Exception as e:  # pragma: no cover - defensive
        log.warning("SLD generation failed: %s", e)
        sld_render = {"png_base64": None, "error": str(e), "meta": {}}

    # G99 Table 10.1 interface protection (cross-reference, not duplicate pack).
    try:
        g99_type = "Type B" if capacity_mw <= 10 else ("Type C" if capacity_mw <= 50 else "Type D")
        table_101 = get_table_101(
            voltage_kv=poc_voltage_kv,
            anti_islanding_scheme="rocof",
            g99_type=g99_type,
        )
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Table 10.1 generation failed: %s", e)
        table_101 = None

    # Viability verdict (viable / viable-with-works / not-viable).
    raw_verdict = assessment.get("verdict") or "CAUTION"
    has_headroom = (headroom_mw is not None and float(headroom_mw) >= capacity_mw)
    viability = _viability_verdict(raw_verdict, has_headroom, triggers_reinforcement)

    # Ownership classification — default DNO-owned; flags for IDNO/TO routes.
    ownership = _ownership_classification(poc_voltage_kv, dno_area)

    # Commissioning plan — boilerplate per G99 Issue 2 §9.
    commissioning = _commissioning_plan(capacity_mw, poc_voltage_kv, technology)

    # Revision control.
    revision = _revision_block(project_id, project_meta)

    # Reliance addressee.
    addressee = (project_meta or {}).get("addressee") or "DNO Connection Team / Project Lender"

    return {
        "site_name": site_label,
        "generated_at": generated_at,
        "project_id": project_id,
        "project_meta": project_meta or {},
        "addressee": addressee,
        "lat": lat,
        "lon": lon,
        "osgb": osgb,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "raw_verdict": raw_verdict,
        "verdict": viability,
        "confidence": assessment.get("confidence", 0.5),
        "summary": assessment.get("summary", ""),
        "dno_area": dno_area,
        "ltds": ltds,
        "ltds_key": dno_key,
        "candidates": assessment.get("candidates", []),
        "best_candidate": best,
        "ownership": ownership,
        "cost_estimate": assessment.get("cost_estimate"),
        "voltage_options": voltage_options,
        "cccm": cccm,
        "risks": assessment.get("risks", []),
        "headroom": headroom,
        "queue_summary": {
            "total_queued_mw": sum(
                (c.get("queue", {}) or {}).get("ecr_queued_mw", 0)
                for c in assessment.get("candidates", [])
            ),
            "total_queued_count": sum(
                (c.get("queue", {}) or {}).get("ecr_queued", 0)
                for c in assessment.get("candidates", [])
            ),
            "best_queue": (best or {}).get("queue", {}),
        },
        "power_flow": power_flow,
        "sld": sld_render,
        "table_101": table_101,
        "commissioning": commissioning,
        "revision": revision,
        "tier": assessment.get("tier", "data"),
        "elapsed_s": assessment.get("elapsed_s", 0),
    }


def _best_voltage_for_capacity(capacity_mw: float) -> int:
    if capacity_mw <= 1:
        return 11
    if capacity_mw <= 10:
        return 33
    if capacity_mw <= 50:
        return 66
    return 132


def _ownership_classification(poc_voltage_kv: float, dno_area: dict) -> dict:
    """Flag likely ownership route at the POC (DNO / IDNO / TO)."""
    route = "DNO"
    note = "Primary/secondary distribution — DNO-owned."
    if poc_voltage_kv >= 132:
        route = "TO (Transmission Owner)"
        note = (
            "Connection at 132 kV+ sits on the transmission network — NESO + TO "
            "(NGET / SPT / SSEN-T) involvement required under the Grid Code."
        )
    return {
        "route": route,
        "note": note,
        "dno_name": dno_area.get("name") or "Unknown DNO",
    }


def _commissioning_plan(capacity_mw: float, voltage_kv: float, technology: str) -> list[dict]:
    """Commissioning milestones per G99 Issue 2 §9."""
    plan = [
        {"stage": "Factory Acceptance Test (FAT)",
         "scope": "Inverter/transformer FAT with manufacturer; witness by customer engineer."},
        {"stage": "Site Acceptance Test (SAT)",
         "scope": "Cable continuity, HV pressure test, protection relay settings per G99 Table 10.1."},
        {"stage": "Energisation Authorisation",
         "scope": "DNO issues Authorisation to Energise; customer submits G99 Compliance Report."},
        {"stage": "Protection Commissioning",
         "scope": "Secondary injection of OV/UV/OF/UF/RoCoF relays; grading with DNO feeder protection."},
        {"stage": "Trial Operation & Compliance Monitoring",
         "scope": "14-day observation; RfG compliance verified; Final Operational Notification (FON)."},
    ]
    if capacity_mw > 10:
        plan.insert(3, {
            "stage": "Network Impact Re-study",
            "scope": "Post-installation power flow re-run against connection offer; reconcile with DNO."
        })
    return plan


def _revision_block(project_id: str | None, project_meta: dict | None) -> list[dict]:
    """Revision control table rows."""
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meta = project_meta or {}
    return [
        {
            "rev": meta.get("rev", "P01"),
            "date": meta.get("rev_date", now_date),
            "author": meta.get("author", "Princeps Platform"),
            "reviewer": meta.get("reviewer", "Pending chartered review"),
            "approver": meta.get("approver", "Pending"),
            "description": meta.get("rev_desc", "Pre-application grid connection assessment."),
        }
    ]


# ---------------------------------------------------------------------------
# Fault level helper (IEC 60909 approximation — POC indicative only)
# ---------------------------------------------------------------------------
def _estimate_fault_level(poc_voltage_kv: float, capacity_mw: float) -> dict:
    """Rough IEC 60909 three-phase / single-phase-earth fault levels at POC.

    Used when the DNO has not yet supplied a formal fault level study.
    Values are deliberately conservative (source impedance + transformer
    short-circuit reactance derived from typical primary substation specs).
    """
    # Nominal MVA base for the POC bus.
    mva_base = max(capacity_mw * 1.2, 20.0)
    # Typical source impedance % + transformer %: 10% each at primary level.
    z_source_pu = 0.10
    z_tx_pu = 0.10
    z_total_pu = (z_source_pu ** 2 + z_tx_pu ** 2) ** 0.5
    # I_fault (kA) = MVA_base / (sqrt(3) * V_kv * Z_pu)
    if poc_voltage_kv <= 0 or z_total_pu <= 0:
        return {"three_phase_ka": None, "single_phase_earth_ka": None,
                "switchgear_rating_ka": None, "clearance_ms": None,
                "source": "fallback"}
    i_3ph = mva_base / (1.7320508 * poc_voltage_kv * z_total_pu)
    # Single-phase-earth is typically ~0.85× three-phase on UK distribution.
    i_1ph_e = i_3ph * 0.85
    # Standard DNO switchgear withstand by voltage class.
    swgear = {11: 25.0, 33: 25.0, 66: 31.5, 132: 40.0, 400: 50.0}.get(
        int(poc_voltage_kv) if poc_voltage_kv in (11, 33, 66, 132, 400) else 33, 25.0)
    return {
        "three_phase_ka": round(i_3ph, 2),
        "single_phase_earth_ka": round(i_1ph_e, 2),
        "switchgear_rating_ka": swgear,
        "clearance_ms": 100,
        "source": "IEC 60909 approximation (Princeps)",
    }


# ---------------------------------------------------------------------------
# Reference registry (for the shared _references block)
# ---------------------------------------------------------------------------
def _grid_connection_references(ltds: dict | None) -> list[dict]:
    refs = [
        {"n": 1, "title": "ENA EREC G99 Issue 2 — Type B/C/D generator connection",
         "publisher": "Energy Networks Association", "year": 2025,
         "url": "https://www.energynetworks.org/industry-hub/resource-library/"},
        {"n": 2, "title": "Common Connection Charging Methodology v19 (DCUSA Schedule 19)",
         "publisher": "Ofgem / DCUSA", "year": 2026,
         "url": "https://www.ofgem.gov.uk/"},
        {"n": 3, "title": "ENA EREC P28 Issue 2 — Voltage fluctuations",
         "publisher": "Energy Networks Association", "year": 2019, "url": None},
        {"n": 4, "title": "ENA ER P2/7 — Security of supply",
         "publisher": "Energy Networks Association", "year": 2019, "url": None},
        {"n": 5, "title": "NESO Future Energy Scenarios 2024 — pathways and demand forecasts",
         "publisher": "National Energy System Operator", "year": 2024,
         "url": "https://www.neso.energy/future-energy/future-energy-scenarios"},
        {"n": 6, "title": "Distribution Code v43 (DCode)", "publisher": "ENA", "year": 2024,
         "url": "https://www.dcode.org.uk/"},
        {"n": 7, "title": "IEC 60909 — Short-circuit currents in three-phase a.c. systems",
         "publisher": "International Electrotechnical Commission", "year": 2016, "url": None},
    ]
    if ltds:
        refs.append({
            "n": len(refs) + 1,
            "title": ltds.get("publication") or "DNO Long Term Development Statement",
            "publisher": ltds.get("long_name") or "DNO", "year": 2024,
            "url": ltds.get("url"),
        })
    return refs


# ---------------------------------------------------------------------------
# Render & PDF
# ---------------------------------------------------------------------------
def _doc_hash(payload: dict) -> str:
    """Short content hash used in the running footer."""
    import hashlib
    key = f"{payload.get('project_id','')}{payload.get('site_name','')}{payload.get('generated_at','')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()


def render_grid_connection_html(report_data: dict, charts: dict[str, str]) -> str:
    """Render the institutional Grid Connection Report (new shared base)."""
    # Shared-base context
    fault = _estimate_fault_level(
        poc_voltage_kv=float(((report_data.get("best_candidate") or {}).get("voltage_kv") or 33.0)),
        capacity_mw=float(report_data.get("capacity_mw") or 50.0),
    )
    # If the underlying assess_connection returned a richer fault level on the
    # best candidate, prefer that.
    bc_fault = (report_data.get("best_candidate") or {}).get("fault_level_ka")
    if bc_fault is not None:
        fault["three_phase_ka"] = float(bc_fault)
        fault["source"] = "DNO data (" + (report_data.get("dno_area") or {}).get("code", "DNO") + ")"

    revision = (report_data.get("revision") or [{}])[0] if report_data.get("revision") else {}
    ctx = {
        # Shared-base contract
        "report_type": "Grid Connection Report",
        "project_title": report_data.get("site_name") or "Untitled Project",
        "tagline": "CCCM v19 connection feasibility and N-1 study",
        "revision": revision.get("rev", "P01"),
        "revision_date": revision.get("date", datetime.utcnow().strftime("%Y-%m-%d")),
        "recipient": report_data.get("addressee") or "DNO Connection Team",
        "reliance_type": "dno",
        "client_ref": (report_data.get("project_meta") or {}).get("client_ref"),
        "doc_ref": (report_data.get("project_id") or "PPS") + "-GCR",
        "project_ref": report_data.get("project_id"),
        "doc_hash": _doc_hash(report_data),
        "references": _grid_connection_references(report_data.get("ltds")),

        # Main payload
        "r": report_data,
        "fault": fault,
        "charts": charts,
        "brand": BRAND,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fmt_gbp": _fmt_gbp,
        "fmt_gbp_k": _fmt_gbp_k,
        "rag_class": _rag_class,
    }
    try:
        template = _institutional_env.get_template("grid_connection/main.html.j2")
        return template.render(**ctx)
    except Exception:
        log.exception("Institutional Grid Connection Report template render failed")
        raise


async def html_to_pdf(html_string: str) -> bytes:
    """Render HTML → PDF via headless Chromium.

    When the body is the institutional rewrite (detected by a marker class
    ``pp-header`` present in the document), we pass Chromium's
    ``header_template`` + ``footer_template`` so the running header/footer +
    Page X of Y renders natively. Legacy HTML falls back to a marginless
    render with print_background so the existing templates are unaffected.
    """
    import tempfile
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    institutional = "pp-header" in html_string

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
                raise RuntimeError("Chromium not installed. Run: playwright install chromium")
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60000)

            if institutional:
                # Extract the inline header / footer strip text (best effort)
                # by locating the first .pp-header and .pp-footer elements
                # and reading their .innerText values.
                try:
                    header_text = await page.evaluate(
                        "() => { const el=document.querySelector('.pp-header');"
                        " return el ? el.innerText.replace(/\\s+/g,' ').trim() : ''; }"
                    )
                except Exception:
                    header_text = "PRINCEPS"
                try:
                    footer_text = await page.evaluate(
                        "() => { const el=document.querySelector('.pp-footer');"
                        " return el ? el.innerText.replace(/\\s+/g,' ').trim() : ''; }"
                    )
                except Exception:
                    footer_text = "Princeps Energy — Confidential"

                # Hide the in-body header/footer so only the printed running
                # strip shows (otherwise we'd get a double banner).
                await page.add_style_tag(content=".pp-header, .pp-footer { display: none !important; }")

                header_html = (
                    "<div style=\"font-family: Inter, -apple-system, sans-serif;"
                    " font-size: 8pt; color: #3E444C; width: 100%;"
                    " padding: 0 15mm; display: flex; justify-content: space-between;"
                    " align-items: center; border-bottom: 2px solid #F5B731;\">"
                    f"<span style=\"font-weight:700; letter-spacing:2.5px; color:#0F1318;\">"
                    "<span style='color:#F5B731; margin-right:6px;'>◆</span>PRINCEPS</span>"
                    f"<span style=\"color:#6B7280;\">{header_text.split('PRINCEPS',1)[-1].strip() or ''}</span>"
                    "<span style=\"font-family: 'JetBrains Mono', Menlo, monospace;\">"
                    "Page <span class=\"pageNumber\"></span> of <span class=\"totalPages\"></span>"
                    "</span>"
                    "</div>"
                )
                footer_html = (
                    "<div style=\"font-family: Inter, -apple-system, sans-serif;"
                    " font-size: 7.5pt; color: #6B7280; width: 100%;"
                    " padding: 0 15mm; display: flex; justify-content: space-between;"
                    " align-items: center; border-top: 1px solid #E5DCC0;\">"
                    f"<span style=\"letter-spacing:1.2px; font-weight:600; color:#3E444C;\">"
                    "Princeps Energy &mdash; Confidential &mdash; for intended recipient only</span>"
                    f"<span style=\"font-family: 'JetBrains Mono', Menlo, monospace;\">"
                    f"{footer_text.split('Princeps Energy')[-1].split('—')[-1].strip() if footer_text else ''}"
                    "</span>"
                    "</div>"
                )

                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=header_html,
                    footer_template=footer_html,
                    margin={"top": "22mm", "bottom": "18mm",
                            "left": "15mm", "right": "15mm"},
                )
            else:
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "0.5in", "bottom": "0.6in",
                            "left": "0.4in", "right": "0.4in"},
                )
            await browser.close()
            return pdf_bytes
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Project loader + orchestrator
# ---------------------------------------------------------------------------
async def _load_project(conn, project_id: str) -> dict | None:
    """Fetch project fields for grid connection report."""
    try:
        pid = uuid.UUID(str(project_id))
    except Exception:
        return None
    row = await conn.fetchrow(
        """SELECT project_id, name, technology, capacity_mw, lat, lon,
                  metadata, stage, verdict
           FROM projects WHERE project_id = $1""", pid,
    )
    if not row:
        return None
    import json as _json
    raw_meta = row["metadata"]
    if raw_meta is None:
        meta: dict = {}
    elif isinstance(raw_meta, dict):
        meta = dict(raw_meta)
    elif isinstance(raw_meta, (bytes, str)):
        try:
            parsed = _json.loads(raw_meta)
            meta = parsed if isinstance(parsed, dict) else {}
        except Exception:
            meta = {}
    else:
        meta = {}
    return {
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "technology": (row["technology"] or meta.get("technology") or "solar"),
        "capacity_mw": float(row["capacity_mw"] or meta.get("capacity_mw") or 50.0),
        "lat": float(row["lat"]) if row["lat"] is not None else None,
        "lon": float(row["lon"]) if row["lon"] is not None else None,
        "metadata": meta,
        "stage": row["stage"],
        "project_verdict": row["verdict"],
    }


async def generate_grid_connection_report(
    conn,
    lat: float | None = None,
    lon: float | None = None,
    capacity_mw: float = 50.0,
    site_name: str | None = None,
    technology: str = "solar",
    run_power_flow: bool = True,
    project_id: str | None = None,
    pool=None,
) -> bytes:
    """Full pipeline — supports both project_id and raw lat/lon entry points."""
    project_meta: dict | None = None
    if project_id:
        project = await _load_project(conn, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if project["lat"] is None or project["lon"] is None:
            raise ValueError(f"Project {project_id} has no lat/lon set")
        lat = project["lat"]
        lon = project["lon"]
        capacity_mw = project["capacity_mw"]
        site_name = site_name or project["name"]
        technology = project["technology"]
        project_meta = {
            "name": project["name"],
            "stage": project["stage"],
            "author": project["metadata"].get("author", "Princeps Platform"),
            "rev": project["metadata"].get("rev", "P01"),
            "rev_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "addressee": project["metadata"].get(
                "report_addressee", "DNO Connection Team / Project Lender"
            ),
        }

    if lat is None or lon is None:
        raise ValueError("lat/lon are required when project_id is not given")

    log.info(
        "Generating grid connection report: project=%s site=%s (%.4f, %.4f) @ %.1f MW",
        project_id or "n/a", site_name or "site", lat, lon, capacity_mw,
    )

    report_data = await aggregate_grid_connection_data(
        conn, lat, lon, capacity_mw, site_name, technology,
        run_power_flow=run_power_flow,
        project_id=project_id,
        project_meta=project_meta,
        pool=pool,
    )
    log.info(
        "Grid data aggregated: verdict=%s, %d candidates, LTDS=%s",
        report_data["verdict"],
        len(report_data.get("candidates", [])),
        report_data.get("ltds_key"),
    )

    loop = asyncio.get_running_loop()
    charts = await loop.run_in_executor(None, generate_charts, report_data)
    log.info("Charts generated: %s", ", ".join(charts.keys()))

    html = render_grid_connection_html(report_data, charts)
    pdf_bytes = await html_to_pdf(html)
    log.info("Grid connection report generated: %d bytes", len(pdf_bytes))
    return pdf_bytes
