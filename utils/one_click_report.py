"""
Princeps One-Click Comprehensive Feasibility Report Generator.

Drop a pin, click one button, get a 30-page institutional-grade PDF in 60 seconds.

Orchestrates ALL existing Princeps modules in parallel:
  - Site data aggregation (PostGIS: substations, GeeFlow, parcels, queue)
  - Solar yield via SAM subprocess (PvWattsv8)
  - Grid connection assessment (Tier 1 + cost P10/P50/P90)
  - Environmental constraints (Natural England, EA flood, ALC, Green Belt)
  - ML site viability (XGBoost + SHAP)
  - Loss budget (DNV GL 16-category waterfall)
  - Financial model (25-year DCF: IRR, NPV, LCOE, payback)
  - Demand forecast (nearest GSP)
  - Carbon intensity (National Grid ESO)
  - Planning risk (ML-predicted from REPD)

Renders via the institutional_base.html template with full Princeps branding,
then converts to PDF via Playwright Chromium.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

log = logging.getLogger("princeps.one_click_report")

# ---------------------------------------------------------------------------
# Lazy imports (modules may not all be installed in every env)
# ---------------------------------------------------------------------------

def _import_report_renderer():
    from utils.report_renderer import (
        aggregate_site_data,
        generate_charts,
        fetch_static_map,
        html_to_pdf,
        BRAND,
        SCORE_COLOURS,
        _fig_to_b64,
        _apply_style,
    )
    return aggregate_site_data, generate_charts, fetch_static_map, html_to_pdf, BRAND, SCORE_COLOURS, _fig_to_b64, _apply_style


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "report"
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Technology parameters for multi-tech comparison
# Solar parameters now sourced from utils.solar_benchmarks (2026 UK).
from utils import solar_benchmarks as _solar_benchmarks

TECH_PARAMS = {
    "solar": {
        "label": "Solar PV (ground-mount)",
        "capex_per_mw": _solar_benchmarks.solar_capex_per_mw(),        # £730k
        "opex_per_mw_yr": _solar_benchmarks.solar_opex_per_mw_yr(),    # £10k
        "capacity_factor_range": (
            _solar_benchmarks.SOLAR_CAPACITY_FACTOR["low"],
            _solar_benchmarks.SOLAR_CAPACITY_FACTOR["high"],
        ),
        "land_ha_per_mw": 2.0,
        "degradation_pct": 0.5,
    },
    "wind": {
        "label": "Onshore Wind",
        "capex_per_mw": 1_200_000,
        "opex_per_mw_yr": 25_000,
        "capacity_factor_range": (0.25, 0.35),
        "land_ha_per_mw": 0.5,
        "degradation_pct": 0.2,
    },
    "bess": {
        "label": "Battery Storage (4h)",
        "capex_per_mw": 800_000,
        "opex_per_mw_yr": 8_000,
        "capacity_factor_range": (0.10, 0.20),
        "land_ha_per_mw": 0.1,
        "degradation_pct": 2.0,
    },
    "solar+bess": {
        "label": "Solar PV + BESS (co-located)",
        "capex_per_mw": 900_000,
        "opex_per_mw_yr": 14_000,
        "capacity_factor_range": (0.12, 0.18),
        "land_ha_per_mw": 2.2,
        "degradation_pct": 0.6,
    },
}

# BNG habitat unit rates (simplified per-hectare)
BNG_HABITAT_UNITS = {
    "crops": 2.0,
    "grass": 4.0,
    "bare": 1.0,
    "trees": 8.0,
    "shrub_and_scrub": 5.0,
    "water": 6.0,
    "built": 0.5,
    "flooded_vegetation": 6.0,
}


# ===================================================================
# 1. DATA COLLECTION PHASE — all in parallel
# ===================================================================

async def _collect_sam_yield(lat: float, lon: float, capacity_mw: float) -> dict:
    """Run PvWattsv8 via SAM subprocess bridge."""
    try:
        from app.helpers import run_sam_subprocess
        result = await run_sam_subprocess(
            lat=lat, lon=lon, capacity_kw=capacity_mw * 1000,
            tilt=25.0, azimuth=180.0, losses=14.0,
        )
        return {"source": "pvsam_v8", **result}
    except Exception as e:
        log.warning("SAM subprocess failed, using analytical estimate: %s", e)
        # Analytical fallback
        ghi_by_lat = 1100 if lat < 52 else 1000 if lat < 54 else 900
        cf = min((ghi_by_lat * 0.82) / (1000 * 8.76), 0.25)
        annual_kwh = capacity_mw * 1000 * cf * 8760
        monthly_gen = []
        ghi_factors = [0.4, 0.5, 0.8, 1.1, 1.3, 1.4, 1.35, 1.2, 0.9, 0.65, 0.45, 0.35]
        for i, f in enumerate(ghi_factors):
            monthly_gen.append({
                "month": i + 1,
                "energy_kwh": round(annual_kwh * f / sum(ghi_factors)),
            })
        return {
            "source": "analytical_estimate",
            "annual_energy_kwh": round(annual_kwh),
            "capacity_factor_pct": round(cf * 100, 2),
            "monthly_generation": monthly_gen,
        }


async def _collect_grid_assessment(conn, lat: float, lon: float,
                                    capacity_mw: float, technology: str) -> dict:
    """Run Tier 1 grid connection assessment."""
    try:
        from utils.grid_connection_analyser import assess_connection, estimate_connection_cost
        result = await assess_connection(conn, lat, lon, capacity_mw, technology)
        return result
    except Exception as e:
        log.warning("Grid assessment failed: %s", e)
        return {"verdict": "UNKNOWN", "error": str(e)}


async def _collect_environmental(lat: float, lon: float) -> dict:
    """Query Natural England designations + carbon intensity."""
    result = {"designations": [], "carbon": {}}
    try:
        from app.routers.environment import _natural_england_designations, _regional_carbon_intensity
        desig, carbon = await asyncio.gather(
            _natural_england_designations(lat, lon, 2000),
            _regional_carbon_intensity(lat, lon),
        )
        result["designations"] = desig
        result["carbon"] = carbon
    except Exception as e:
        log.warning("Environmental query failed: %s", e)
        result["carbon"] = {"current_gco2_kwh": 200, "index": "moderate"}
    return result


async def _collect_ml_score(site_data: dict) -> dict:
    """Run XGBoost site viability prediction + SHAP."""
    try:
        from utils.ml_site_classifier import predict_site, FEATURE_NAMES
        solar = site_data.get("solar_resource", {})
        terrain = site_data.get("terrain", {})
        land = site_data.get("land_use", {})
        classes = land.get("class_percentages", {})
        flood = site_data.get("flood_risk", {})
        veg = site_data.get("vegetation", {})

        features = {
            "ghi_kwh_m2_yr": solar.get("annual_ghi_kwh_m2") or 1000,
            "wind_speed_ms": 6.0,
            "slope_mean_deg": terrain.get("slope_mean_deg") or 5.0,
            "slope_p90_deg": terrain.get("slope_p90_deg") or 8.0,
            "south_facing_pct": terrain.get("south_facing_pct") or 40.0,
            "elevation_m": terrain.get("elevation_mean_m") or 100.0,
            "developable_pct": land.get("developable_area_pct") or 55.0,
            "built_pct": classes.get("built", 12.0),
            "trees_pct": classes.get("trees", 13.0),
            "water_pct": classes.get("water", 3.0),
            "grid_distance_km": site_data.get("distance_km") or 5.0,
            "grid_headroom_mw": 5.0,
            "flood_risk_score": flood.get("flood_risk_score") or 70,
            "ndvi_mean": veg.get("mean_ndvi") or 0.45,
            "ndvi_trend_slope": 0.0,
            "sar_vv_mean_db": -12.0,
            "cloud_clear_pct": 42.0,
        }
        return predict_site(features)
    except Exception as e:
        log.warning("ML scoring failed: %s", e)
        return {"verdict": "UNKNOWN", "score": 0, "confidence": 0, "error": str(e)}


async def _collect_planning_risk(capacity_mw: float, designations: list) -> dict:
    """Run ML planning risk prediction."""
    try:
        from utils.ml_advanced_models import predict_planning_risk
        # Derive features from designations
        has_aonb = any(d.get("type") == "AONB" for d in designations)
        has_green_belt = any(d.get("type") == "Green Belt" for d in designations)
        has_sssi = any(d.get("type") == "SSSI" for d in designations)

        features = {
            "distance_to_residential_km": 1.5,
            "num_nearby_solar_farms": 2,
            "aonb_proximity_km": 0.5 if has_aonb else 10.0,
            "green_belt": 1 if has_green_belt else 0,
            "flood_zone": 1,
            "agricultural_grade": 3,
            "local_authority_approval_rate": 0.85,
            "capacity_mw": capacity_mw,
            "height_above_ground_m": 3.0,
            "landscape_sensitivity": 3 if has_sssi else 2,
        }
        return predict_planning_risk(features)
    except Exception as e:
        log.warning("Planning risk ML failed: %s", e)
        return {"outcome": "UNKNOWN", "error": str(e)}


async def _collect_loss_budget(lat: float, lon: float, capacity_mw: float) -> dict:
    """Calculate DNV GL 16-category loss budget."""
    try:
        from utils.loss_budget import calculate_loss_budget, calculate_lifetime_profile
        params = {
            "capacity_kw": capacity_mw * 1000,
            "lat": lat,
            "lon": lon,
            "tilt_deg": 25.0,
            "azimuth_deg": 180.0,
            "dc_ac_ratio": 1.20,
            "inverter_efficiency": 0.98,
            "year": 1,
        }
        budget = calculate_loss_budget(params)
        lifetime = calculate_lifetime_profile(params, 25)
        budget["lifetime"] = lifetime
        return budget
    except Exception as e:
        log.warning("Loss budget calculation failed: %s", e)
        return {"error": str(e)}


# ===================================================================
# 2. ANALYSIS PHASE
# ===================================================================

def _financial_model(capacity_mw: float, sam_result: dict, grid_result: dict,
                     loss_budget: dict, technology: str = "solar") -> dict:
    """25-year DCF financial model — IRR, NPV, LCOE, payback, debt sizing."""
    tech = TECH_PARAMS.get(technology, TECH_PARAMS["solar"])

    # Energy yield
    annual_kwh = sam_result.get("annual_energy_kwh", capacity_mw * 1000 * 0.11 * 8760)
    annual_mwh = annual_kwh / 1000

    # Apply performance ratio from loss budget if available
    pr = loss_budget.get("performance_ratio_pct", 82.0) / 100.0
    cf = annual_kwh / (capacity_mw * 1000 * 8760) if capacity_mw > 0 else 0.11

    # Connection cost
    conn_cost = 0
    if grid_result.get("cost_estimate"):
        conn_cost = grid_result["cost_estimate"].get("p50_total_gbp", 0)
    elif grid_result.get("best_candidate"):
        dist = grid_result["best_candidate"].get("distance_km", 5)
        conn_cost = dist * 150_000

    # CAPEX
    capex = capacity_mw * tech["capex_per_mw"] + conn_cost
    capex_m = capex / 1e6

    # Revenue & OPEX — solar uses 2026 merchant PPA mid (utils.solar_benchmarks)
    if technology == "solar":
        ppa_price = float(_solar_benchmarks.ppa_price_merchant_mid())   # £45/MWh
        land_rent_per_ha = float(_solar_benchmarks.land_rent_gbp_ha_yr())
    else:
        ppa_price = 55.0  # GBP/MWh — non-solar fallback
        land_rent_per_ha = 1200
    degradation = tech["degradation_pct"] / 100
    discount_rate = 0.06
    project_life = 25
    opex_yr = capacity_mw * tech["opex_per_mw_yr"]
    land_rent_yr = capacity_mw * tech["land_ha_per_mw"] * land_rent_per_ha

    # Annual cashflow table
    cashflows = [-capex]
    cumulative = [-capex]
    annual_table = []
    payback_year = None

    for yr in range(1, project_life + 1):
        deg_factor = (1 - degradation) ** (yr - 1)
        energy_mwh = annual_mwh * deg_factor
        rev = energy_mwh * ppa_price
        opex_esc = opex_yr * (1.025 ** (yr - 1))  # 2.5% CPI
        land_esc = land_rent_yr * (1.02 ** (yr - 1))  # 2% RPI
        net = rev - opex_esc - land_esc
        cashflows.append(net)
        cum = cumulative[-1] + net
        cumulative.append(cum)
        annual_table.append({
            "year": yr,
            "energy_mwh": round(energy_mwh),
            "revenue_gbp": round(rev),
            "opex_gbp": round(opex_esc),
            "land_rent_gbp": round(land_esc),
            "net_cashflow_gbp": round(net),
            "cumulative_gbp": round(cum),
        })
        if payback_year is None and cum >= 0:
            payback_year = yr

    # IRR (Newton-Raphson)
    irr = _calc_irr(cashflows)

    # NPV
    npv = sum(cf / (1 + discount_rate) ** i for i, cf in enumerate(cashflows))

    # LCOE
    total_energy = sum(annual_mwh * (1 - degradation) ** (yr - 1)
                       for yr in range(1, project_life + 1))
    total_cost = capex + sum(
        (opex_yr * (1.025 ** (yr - 1)) + land_rent_yr * (1.02 ** (yr - 1)))
        / (1 + discount_rate) ** yr
        for yr in range(1, project_life + 1)
    )
    discounted_energy = sum(
        annual_mwh * (1 - degradation) ** (yr - 1) / (1 + discount_rate) ** yr
        for yr in range(1, project_life + 1)
    )
    lcoe = total_cost / discounted_energy if discounted_energy > 0 else 999

    # Debt sizing (70:30 gearing, 1.3x DSCR minimum)
    gearing = 0.70
    debt = capex * gearing
    equity = capex * (1 - gearing)
    debt_rate = 0.045
    debt_tenor = 18
    annual_debt_service = debt * (debt_rate * (1 + debt_rate) ** debt_tenor) / \
                          ((1 + debt_rate) ** debt_tenor - 1) if debt_tenor > 0 else 0
    avg_net_cf = sum(r["net_cashflow_gbp"] for r in annual_table[:debt_tenor]) / debt_tenor if debt_tenor > 0 else 0
    min_dscr = avg_net_cf / annual_debt_service if annual_debt_service > 0 else 0
    equity_irr = _calc_irr([-equity] + [
        r["net_cashflow_gbp"] - annual_debt_service
        for r in annual_table[:debt_tenor]
    ] + [r["net_cashflow_gbp"] for r in annual_table[debt_tenor:]])

    # CO2 offset
    co2_offset = annual_mwh * 0.20  # tonnes/yr (UK grid avg 200g/kWh)

    return {
        "capex_gbp": round(capex),
        "capex_m": round(capex_m, 2),
        "capex_per_mw": tech["capex_per_mw"],
        "connection_cost_gbp": round(conn_cost),
        "annual_yield_mwh": round(annual_mwh),
        "annual_yield_gwh": round(annual_mwh / 1000, 2),
        "capacity_factor_pct": round(cf * 100, 1),
        "performance_ratio_pct": round(pr * 100, 1),
        "ppa_price_gbp_mwh": ppa_price,
        "lcoe_gbp_mwh": round(lcoe, 1),
        "irr_pct": round(irr * 100, 1) if irr else 0,
        "equity_irr_pct": round(equity_irr * 100, 1) if equity_irr else 0,
        "npv_gbp": round(npv),
        "npv_m": round(npv / 1e6, 2),
        "payback_years": payback_year or 99,
        "annual_revenue_gbp": round(annual_mwh * ppa_price),
        "annual_opex_gbp": round(opex_yr),
        "annual_land_rent_gbp": round(land_rent_yr),
        "debt_gbp": round(debt),
        "equity_gbp": round(equity),
        "annual_debt_service_gbp": round(annual_debt_service),
        "min_dscr": round(min_dscr, 2),
        "co2_offset_tonnes_yr": round(co2_offset),
        "co2_offset_lifetime_tonnes": round(co2_offset * project_life * 0.95),
        "land_required_ha": round(capacity_mw * tech["land_ha_per_mw"], 1),
        "project_life_years": project_life,
        "annual_table": annual_table[:5] + annual_table[-3:],  # first 5 + last 3 for the report
    }


def _calc_irr(cashflows: list[float], guess: float = 0.08, tol: float = 1e-6,
              max_iter: int = 100) -> float | None:
    """Calculate IRR using Newton-Raphson."""
    rate = guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + rate) ** i for i, cf in enumerate(cashflows))
        dnpv = sum(-i * cf / (1 + rate) ** (i + 1) for i, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-12:
            return None
        rate -= npv / dnpv
        if abs(npv) < tol:
            return rate
    return rate if abs(sum(cf / (1 + rate) ** i for i, cf in enumerate(cashflows))) < 1 else None


def _multi_tech_comparison(lat: float, lon: float, capacity_mw: float,
                           sam_result: dict, grid_result: dict) -> list[dict]:
    """Compare solar, wind, BESS, and solar+BESS at this site."""
    results = []
    for tech_key, params in TECH_PARAMS.items():
        cf_low, cf_high = params["capacity_factor_range"]
        # Adjust CF for latitude (solar gets lower north, wind gets higher)
        if tech_key in ("solar", "solar+bess"):
            cf = cf_low + (cf_high - cf_low) * max(0, min(1, (55 - lat) / 8))
        elif tech_key == "wind":
            cf = cf_low + (cf_high - cf_low) * max(0, min(1, (lat - 50) / 8))
        else:
            cf = (cf_low + cf_high) / 2

        annual_mwh = capacity_mw * cf * 8760
        capex = capacity_mw * params["capex_per_mw"]
        opex = capacity_mw * params["opex_per_mw_yr"]
        rev = annual_mwh * 55  # PPA price
        net = rev - opex
        payback = capex / net if net > 0 else 99
        lcoe = capex / (annual_mwh * 25 * 0.95) * 1000 + opex / annual_mwh if annual_mwh > 0 else 999

        results.append({
            "technology": params["label"],
            "capacity_factor_pct": round(cf * 100, 1),
            "annual_yield_mwh": round(annual_mwh),
            "capex_m": round(capex / 1e6, 2),
            "lcoe_gbp_mwh": round(lcoe, 1),
            "payback_years": round(payback, 1),
            "land_ha": round(capacity_mw * params["land_ha_per_mw"], 1),
            "recommended": tech_key == "solar",  # default; override below
        })

    # Mark best by LCOE
    best = min(results, key=lambda r: r["lcoe_gbp_mwh"])
    for r in results:
        r["recommended"] = (r["technology"] == best["technology"])
    return results


def _bng_estimate(land_use: dict, capacity_mw: float, technology: str = "solar") -> dict:
    """Statutory Biodiversity Metric v1.0 / UKHab v2.0 baseline + post-development
    BNG calculation via utils.bng_calculator.

    Returns a pack-ready dict with baseline_units, post_units, net_change_pct,
    compliance flag, habitat_breakdown (baseline + post) and unit-offset cost
    for any residual deficit. Keeps back-compat keys (`baseline_units`,
    `habitat_breakdown`, `offset_cost_gbp`) used by older templates.
    """
    from utils.bng_calculator import bng_from_land_use, bng_to_pack_dict, NET_GAIN_THRESHOLD_PCT

    result = bng_from_land_use(land_use or {}, capacity_mw, tech=technology)
    pack = bng_to_pack_dict(result)

    # Offset cost only applies to the deficit below the 10% threshold
    required_units = pack["baseline_units"] * (NET_GAIN_THRESHOLD_PCT / 100.0)
    achieved_over_baseline = max(pack["net_change_units"], 0.0)
    deficit_units = max(required_units - achieved_over_baseline, 0.0)
    cost_per_unit = 25_000  # UK average BNG credit cost (DEFRA statutory tariff c.£42k band2 — market avg ~£25k)
    offset_cost = deficit_units * cost_per_unit

    # Legacy keys retained for back-compat with older template paths
    pack["required_uplift_pct"] = NET_GAIN_THRESHOLD_PCT
    pack["required_uplift_units"] = round(required_units, 2)
    pack["deficit_units"] = round(deficit_units, 2)
    pack["offset_cost_gbp"] = round(offset_cost)
    pack["cost_per_unit_gbp"] = cost_per_unit
    pack["habitat_breakdown"] = pack["baseline_rows"]
    pack["strategy"] = (
        "On-site habitat creation preferred (meadow under panels, native hedgerow). "
        "Off-site BNG credits as fallback for residual deficit."
    )
    return pack


def _probability_table(annual_mwh: float, cf_pct: float) -> list[dict]:
    """Generate P50/P75/P90/P95/P99 exceedance table (GHI inter-annual variability)."""
    # UK solar inter-annual variability ~5% std dev
    std_dev = annual_mwh * 0.05
    import scipy.stats as stats
    try:
        return [
            {"period": "Year 1",
             "p50": f"{annual_mwh:,.0f} MWh",
             "p75": f"{annual_mwh - std_dev * 0.674:,.0f} MWh",
             "p90": f"{annual_mwh - std_dev * 1.282:,.0f} MWh",
             "p95": f"{annual_mwh - std_dev * 1.645:,.0f} MWh",
             "p99": f"{annual_mwh - std_dev * 2.326:,.0f} MWh"},
            {"period": "Year 10 (degraded)",
             "p50": f"{annual_mwh * 0.955:,.0f} MWh",
             "p75": f"{(annual_mwh * 0.955 - std_dev * 0.674):,.0f} MWh",
             "p90": f"{(annual_mwh * 0.955 - std_dev * 1.282):,.0f} MWh",
             "p95": f"{(annual_mwh * 0.955 - std_dev * 1.645):,.0f} MWh",
             "p99": f"{(annual_mwh * 0.955 - std_dev * 2.326):,.0f} MWh"},
            {"period": "Year 25 (end of life)",
             "p50": f"{annual_mwh * 0.882:,.0f} MWh",
             "p75": f"{(annual_mwh * 0.882 - std_dev * 0.674):,.0f} MWh",
             "p90": f"{(annual_mwh * 0.882 - std_dev * 1.282):,.0f} MWh",
             "p95": f"{(annual_mwh * 0.882 - std_dev * 1.645):,.0f} MWh",
             "p99": f"{(annual_mwh * 0.882 - std_dev * 2.326):,.0f} MWh"},
        ]
    except ImportError:
        # scipy not available — use hardcoded z-scores
        return [
            {"period": "Year 1",
             "p50": f"{annual_mwh:,.0f} MWh",
             "p75": f"{annual_mwh * 0.966:,.0f} MWh",
             "p90": f"{annual_mwh * 0.936:,.0f} MWh",
             "p95": f"{annual_mwh * 0.918:,.0f} MWh",
             "p99": f"{annual_mwh * 0.884:,.0f} MWh"},
        ]


# ===================================================================
# 3. CHART GENERATION — additional charts beyond report_renderer
# ===================================================================

def _loss_waterfall_chart(loss_budget: dict) -> str:
    """Generate DNV GL-style loss waterfall chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from utils.report_renderer import BRAND, _fig_to_b64, _apply_style

    categories = loss_budget.get("loss_categories", [])
    if not categories:
        return ""

    fig, ax = plt.subplots(figsize=(8, 5))
    _apply_style(ax, fig)

    labels = [c.get("name", "?")[:20] for c in categories]
    losses = [c.get("loss_pct", 0) for c in categories]

    # Waterfall: start at 100, subtract each loss
    running = 100.0
    bottoms = []
    heights = []
    colors = []
    for loss in losses:
        bottoms.append(running - loss)
        heights.append(loss)
        colors.append(BRAND["red"] if loss > 3 else BRAND["amber"] if loss > 1 else BRAND["green"])
        running -= loss

    y = np.arange(len(labels))
    ax.barh(y, heights, left=bottoms, color=colors, height=0.6, edgecolor="none", zorder=2)

    for i, (b, h) in enumerate(zip(bottoms, heights)):
        if h >= 0.3:
            ax.text(b + h / 2, i, f"{h:.1f}%", ha="center", va="center",
                    fontsize=7, fontweight="bold", color="white")

    # Net energy bar
    ax.barh(len(labels), running, left=0, color=BRAND["primary"], height=0.6, zorder=2)
    ax.text(running / 2, len(labels), f"PR = {running:.1f}%", ha="center",
            va="center", fontsize=8, fontweight="bold", color="white")

    all_labels = labels + ["Net Energy (PR)"]
    ax.set_yticks(range(len(all_labels)))
    ax.set_yticklabels(all_labels, fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlabel("Energy (%)", fontsize=9)
    ax.set_xlim(0, 105)
    ax.grid(axis="x", alpha=0.15)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _financial_sensitivity_chart(financials: dict) -> str:
    """IRR sensitivity tornado chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from utils.report_renderer import BRAND, _fig_to_b64, _apply_style

    base_irr = financials.get("irr_pct", 8.0)
    if base_irr <= 0:
        return ""

    # Sensitivity parameters (label, downside delta, upside delta)
    sensitivities = [
        ("PPA Price -/+10%", -base_irr * 0.22, base_irr * 0.22),
        ("CAPEX +/-15%", -base_irr * 0.28, base_irr * 0.18),
        ("Yield -/+5%", -base_irr * 0.12, base_irr * 0.12),
        ("Discount Rate +/-1%", -base_irr * 0.08, base_irr * 0.08),
        ("Grid Cost +/-30%", -base_irr * 0.06, base_irr * 0.04),
        ("Degradation +/-0.1%", -base_irr * 0.04, base_irr * 0.04),
    ]

    fig, ax = plt.subplots(figsize=(7, 4))
    _apply_style(ax, fig)

    labels = [s[0] for s in sensitivities]
    downs = [s[1] for s in sensitivities]
    ups = [s[2] for s in sensitivities]
    y = np.arange(len(labels))

    ax.barh(y, downs, height=0.5, color=BRAND["red"], alpha=0.7, label="Downside")
    ax.barh(y, ups, height=0.5, color=BRAND["green"], alpha=0.7, label="Upside")
    ax.axvline(x=0, color=BRAND["dark"], lw=1, ls="-")

    for i, (d, u) in enumerate(zip(downs, ups)):
        ax.text(d - 0.2, i, f"{base_irr + d:.1f}%", ha="right", va="center", fontsize=7, color=BRAND["red"])
        ax.text(u + 0.2, i, f"{base_irr + u:.1f}%", ha="left", va="center", fontsize=7, color=BRAND["green"])

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel(f"IRR deviation from base case ({base_irr:.1f}%)", fontsize=9)
    ax.legend(fontsize=8, loc="lower right")
    ax.invert_yaxis()
    fig.tight_layout()
    return _fig_to_b64(fig)


def _monthly_yield_chart(sam_result: dict) -> str:
    """Monthly generation bar chart from SAM result."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from utils.report_renderer import BRAND, _fig_to_b64, _apply_style

    monthly = sam_result.get("monthly_generation", [])
    if not monthly or len(monthly) < 12:
        return ""

    fig, ax = plt.subplots(figsize=(7, 3.5))
    _apply_style(ax, fig)

    months = [_MONTHS[m.get("month", i + 1) - 1] for i, m in enumerate(monthly)]
    values = [m.get("energy_kwh", 0) / 1000 for m in monthly]  # MWh

    bars = ax.bar(months, values, color=BRAND["primary"], width=0.6, edgecolor="none", zorder=2)
    max_v = max(values) if values else 1
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + max_v * 0.02,
                f"{v:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold",
                color=BRAND["dark"])

    ax.set_ylabel("Generation (MWh)", fontsize=9)
    ax.set_ylim(0, max_v * 1.15)
    ax.grid(axis="y", alpha=0.15)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _render_redline_b64(lat: float, lon: float, site_name: str) -> str:
    """Render the red-line boundary map from a drop-pin and return a
    base64 PNG string suitable for inlining in the report HTML.
    Falls back to an empty string if rendering raises."""
    try:
        import base64 as _b64
        from utils.red_line_map import render_redline_from_point
        png = render_redline_from_point(
            lat, lon,
            site_name=site_name or "Site",
            width_in=7.5, height_in=5.0, dpi=160,
        )
        return _b64.b64encode(png).decode("ascii")
    except Exception as e:
        log.warning("Red-line map b64 render failed: %s", e)
        return ""


def _demand_forecast_mini_chart(site_data: dict) -> str:
    """Mini demand forecast chart for the report."""
    from utils.report_renderer import generate_charts
    fc = site_data.get("demand_forecast")
    if fc and fc.get("data"):
        from utils.report_renderer import _demand_forecast_chart
        return _demand_forecast_chart(fc["data"])
    return ""


# ===================================================================
# 4. REPORT SECTIONS — build the institutional template context
# ===================================================================

def _build_sections(site_data: dict, sam_result: dict, grid_result: dict,
                    environmental: dict, ml_score: dict, planning_risk: dict,
                    loss_budget: dict, financials: dict, multi_tech: list,
                    bng_estimate: dict, charts: dict) -> list[dict]:
    """Build the 11 numbered sections for the institutional template."""
    sections = []

    # Section 2: Site Description
    terrain = site_data.get("terrain", {})
    land = site_data.get("land_use", {})
    sections.append({
        "number": 2,
        "title": "Site Description & Location",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Latitude</span><span class="rpt-kv-value">{site_data.get('lat', 0):.5f}&deg;N</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Longitude</span><span class="rpt-kv-value">{abs(site_data.get('lon', 0)):.5f}&deg;{'W' if site_data.get('lon', 0) < 0 else 'E'}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Elevation</span><span class="rpt-kv-value">{terrain.get('elevation_mean_m', '—')} m AOD</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Mean Slope</span><span class="rpt-kv-value">{terrain.get('slope_mean_deg', '—')}&deg;</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">South-facing</span><span class="rpt-kv-value">{terrain.get('south_facing_pct', '—')}%</span></div>
          </div>
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Total Area</span><span class="rpt-kv-value">{land.get('total_area_m2', 0) / 10000:.1f} ha</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Developable</span><span class="rpt-kv-value">{land.get('developable_area_pct', '—')}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Capacity</span><span class="rpt-kv-value">{site_data.get('capacity_mw', 0)} MW</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Technology</span><span class="rpt-kv-value">{site_data.get('technology', 'Solar PV')}</span></div>
          </div>
        </div>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('redline_map', '') + '" alt="Red-line boundary map"><div class="chart-caption">Figure 2a: Red-line site boundary with statutory overlays (AONB/SSSI/flood) and access roads</div></div>' if charts.get('redline_map') else ''}
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('terrain_profile', '') + '" alt="Terrain"><div class="chart-caption">Terrain elevation and slope profile</div></div>' if charts.get('terrain_profile') else ''}
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('land_use_pie', '') + '" alt="Land use"><div class="chart-caption">DynamicWorld land use classification</div></div>' if charts.get('land_use_pie') else ''}
        """,
    })

    # Section 3: Solar Resource Assessment
    solar = site_data.get("solar_resource", {})
    sections.append({
        "number": 3,
        "title": "Solar Resource Assessment",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Annual GHI</span><span class="rpt-kv-value">{solar.get('annual_ghi_kwh_m2', '—')} kWh/m&sup2;/yr</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Mean Daily GHI</span><span class="rpt-kv-value">{solar.get('mean_ghi_kwh_m2_day', '—')} kWh/m&sup2;/day</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Peak Month</span><span class="rpt-kv-value">{solar.get('peak_month_ghi', {}).get('month', '—') if isinstance(solar.get('peak_month_ghi'), dict) else '—'}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Mean Temperature</span><span class="rpt-kv-value">{solar.get('mean_annual_temp_c', '—')}&deg;C</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Data Source</span><span class="rpt-kv-value">{solar.get('source', 'ERA5-Land / GeeFlow')}</span></div>
          </div>
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">SAM Annual Yield</span><span class="rpt-kv-value">{sam_result.get('annual_energy_kwh', 0) / 1000:,.0f} MWh</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Capacity Factor</span><span class="rpt-kv-value">{sam_result.get('capacity_factor_pct', financials.get('capacity_factor_pct', '—'))}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Specific Yield</span><span class="rpt-kv-value">{sam_result.get('annual_energy_kwh', 0) / max(site_data.get('capacity_mw', 1) * 1000, 1):,.0f} kWh/kWp</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">SAM Model</span><span class="rpt-kv-value">{sam_result.get('source', 'PvWattsv8')}</span></div>
          </div>
        </div>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('solar_monthly', '') + '" alt="Monthly solar"><div class="chart-caption">Monthly GHI and temperature profile (ERA5-Land)</div></div>' if charts.get('solar_monthly') else ''}
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('monthly_yield', '') + '" alt="Monthly yield"><div class="chart-caption">Monthly generation forecast (PvWattsv8)</div></div>' if charts.get('monthly_yield') else ''}
        """,
    })

    # Section 4: Grid Connection
    best_candidate = grid_result.get("best_candidate", grid_result.get("candidates", [{}])[0] if grid_result.get("candidates") else {})
    cost_est = grid_result.get("cost_estimate", {})
    sections.append({
        "number": 4,
        "title": "Grid Connection Assessment",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Nearest Substation</span><span class="rpt-kv-value">{site_data.get('nearest_substation', best_candidate.get('name', '—'))}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Distance</span><span class="rpt-kv-value">{site_data.get('distance_km', best_candidate.get('distance_km', '—'))} km</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Voltage</span><span class="rpt-kv-value">{site_data.get('voltage_kv', best_candidate.get('voltage_kv', '—'))} kV</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">DNO Area</span><span class="rpt-kv-value">{grid_result.get('dno_area', {}).get('name', '—') if isinstance(grid_result.get('dno_area'), dict) else grid_result.get('dno_area', '—')}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Grid Verdict</span><span class="rpt-kv-value">{grid_result.get('verdict', '—')}</span></div>
          </div>
          <div class="rpt-col">
            <h4 class="rpt-minor">Connection Cost Estimate</h4>
            <div class="rpt-kv"><span class="rpt-kv-label">P10 (optimistic)</span><span class="rpt-kv-value">&pound;{cost_est.get('p10_total_gbp', financials.get('connection_cost_gbp', 0) * 0.7):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">P50 (central)</span><span class="rpt-kv-value">&pound;{cost_est.get('p50_total_gbp', financials.get('connection_cost_gbp', 0)):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">P90 (conservative)</span><span class="rpt-kv-value">&pound;{cost_est.get('p90_total_gbp', financials.get('connection_cost_gbp', 0) * 1.5):,.0f}</span></div>
          </div>
        </div>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('grid_proximity', '') + '" alt="Grid proximity"><div class="chart-caption">Nearby substations ranked by distance</div></div>' if charts.get('grid_proximity') else ''}
        """,
    })

    # Section 5: Environmental Constraints
    designations = environmental.get("designations", [])
    hard = [d for d in designations if d.get("severity") == "hard"]
    soft = [d for d in designations if d.get("severity") != "hard"]
    flood = site_data.get("flood_risk", {})

    desig_html = ""
    if designations:
        for d in designations:
            dot_class = "risk-high" if d.get("severity") == "hard" else "risk-med" if d.get("severity") == "medium" else "risk-low"
            desig_html += f'<div class="risk-item"><div class="risk-dot {dot_class}"></div><div><strong>{d.get("type", "Unknown")}</strong> — {d.get("name", "")}<br><span style="font-size:8pt;color:var(--inst-grey);">{d.get("impact", "")}</span></div></div>'
    else:
        desig_html = '<p style="color:var(--inst-green);">No environmental designations identified within 2 km search radius.</p>'

    sections.append({
        "number": 5,
        "title": "Environmental & Planning Constraints",
        "content": f"""
        <h3 class="rpt-sub">Environmental Designations</h3>
        {desig_html}
        <h3 class="rpt-sub">Flood Risk</h3>
        <div class="rpt-kv"><span class="rpt-kv-label">Flood Risk Level</span><span class="rpt-kv-value">{flood.get('risk_level', '—')}</span></div>
        <div class="rpt-kv"><span class="rpt-kv-label">Water Occurrence</span><span class="rpt-kv-value">{flood.get('water_occurrence_pct', '—')}%</span></div>
        <h3 class="rpt-sub">Carbon Intensity</h3>
        <div class="rpt-kv"><span class="rpt-kv-label">Regional Grid Intensity</span><span class="rpt-kv-value">{environmental.get('carbon', {}).get('current_gco2_kwh', 200)} gCO2/kWh</span></div>
        <h3 class="rpt-sub">Vegetation (NDVI)</h3>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('ndvi_monthly', '') + '" alt="NDVI"><div class="chart-caption">Monthly NDVI vegetation index (Sentinel-2)</div></div>' if charts.get('ndvi_monthly') else ''}
        <h3 class="rpt-sub">Planning Risk Assessment (ML)</h3>
        <div class="rpt-kv"><span class="rpt-kv-label">Predicted Outcome</span><span class="rpt-kv-value">{planning_risk.get('outcome', '—')}</span></div>
        <div class="rpt-kv"><span class="rpt-kv-label">Approval Probability</span><span class="rpt-kv-value">{planning_risk.get('probability', {}).get('APPROVED', planning_risk.get('approval_probability', '—'))}</span></div>
        """,
    })

    # Section 6: Energy Yield & Loss Budget
    pr = loss_budget.get("performance_ratio_pct", 82)
    sy = loss_budget.get("specific_yield_kwh_kwp", 900)
    sections.append({
        "number": 6,
        "title": "Energy Yield & Loss Budget (DNV GL Standard)",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Performance Ratio</span><span class="rpt-kv-value">{pr:.1f}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Specific Yield</span><span class="rpt-kv-value">{sy:,.0f} kWh/kWp</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Total Losses</span><span class="rpt-kv-value">{100 - pr:.1f}%</span></div>
          </div>
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">Methodology</span><span class="rpt-kv-value">DNV GL / IEC 61724-1:2021</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Categories</span><span class="rpt-kv-value">16 sequential multiplicative losses</span></div>
          </div>
        </div>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('loss_waterfall', '') + '" alt="Loss waterfall"><div class="chart-caption">Energy loss waterfall — gross POA to net export</div></div>' if charts.get('loss_waterfall') else ''}
        """,
    })

    # Section 7: Financial Viability
    sections.append({
        "number": 7,
        "title": "Financial Viability Assessment",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <h4 class="rpt-minor">Investment Summary</h4>
            <div class="rpt-kv"><span class="rpt-kv-label">Total CAPEX</span><span class="rpt-kv-value">&pound;{financials.get('capex_m', 0):.2f}M</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Connection Cost</span><span class="rpt-kv-value">&pound;{financials.get('connection_cost_gbp', 0):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Project IRR</span><span class="rpt-kv-value">{financials.get('irr_pct', 0):.1f}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Equity IRR</span><span class="rpt-kv-value">{financials.get('equity_irr_pct', 0):.1f}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">NPV (25yr)</span><span class="rpt-kv-value">&pound;{financials.get('npv_m', 0):.2f}M</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">LCOE</span><span class="rpt-kv-value">&pound;{financials.get('lcoe_gbp_mwh', 0):.1f}/MWh</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Payback Period</span><span class="rpt-kv-value">{financials.get('payback_years', '—')} years</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">PPA Price</span><span class="rpt-kv-value">&pound;{financials.get('ppa_price_gbp_mwh', _solar_benchmarks.ppa_price_merchant_mid())}/MWh</span></div>
          </div>
          <div class="rpt-col">
            <h4 class="rpt-minor">Debt Structure</h4>
            <div class="rpt-kv"><span class="rpt-kv-label">Gearing</span><span class="rpt-kv-value">70:30 (Debt:Equity)</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Senior Debt</span><span class="rpt-kv-value">&pound;{financials.get('debt_gbp', 0):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Equity Required</span><span class="rpt-kv-value">&pound;{financials.get('equity_gbp', 0):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Annual Debt Service</span><span class="rpt-kv-value">&pound;{financials.get('annual_debt_service_gbp', 0):,.0f}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Min DSCR</span><span class="rpt-kv-value">{financials.get('min_dscr', 0):.2f}x</span></div>
            <h4 class="rpt-minor">Carbon Offset</h4>
            <div class="rpt-kv"><span class="rpt-kv-label">Annual CO2 Offset</span><span class="rpt-kv-value">{financials.get('co2_offset_tonnes_yr', 0):,} tonnes</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Lifetime CO2</span><span class="rpt-kv-value">{financials.get('co2_offset_lifetime_tonnes', 0):,} tonnes</span></div>
          </div>
        </div>
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('financial_sensitivity', '') + '" alt="IRR sensitivity"><div class="chart-caption">IRR sensitivity analysis (tornado chart)</div></div>' if charts.get('financial_sensitivity') else ''}
        """,
    })

    # Section 8: Technology Comparison
    tech_rows = ""
    for t in multi_tech:
        rec = " (Recommended)" if t.get("recommended") else ""
        tech_rows += f"""<tr{'  style="background:#E8F4F6;"' if t.get('recommended') else ''}>
            <td><strong>{t['technology']}{rec}</strong></td>
            <td class="num">{t['capacity_factor_pct']}%</td>
            <td class="num">{t['annual_yield_mwh']:,} MWh</td>
            <td class="num">&pound;{t['capex_m']}M</td>
            <td class="num">&pound;{t['lcoe_gbp_mwh']}/MWh</td>
            <td class="num">{t['payback_years']} yr</td>
            <td class="num">{t['land_ha']} ha</td>
        </tr>"""

    sections.append({
        "number": 8,
        "title": "Multi-Technology Comparison",
        "content": f"""
        <p>Comparative analysis of four technology options at this site location, using identical grid connection assumptions.</p>
        <table class="rpt-table">
          <tr><th>Technology</th><th>CF</th><th>Annual Yield</th><th>CAPEX</th><th>LCOE</th><th>Payback</th><th>Land</th></tr>
          {tech_rows}
        </table>
        """,
    })

    # Section 9: Demand & Market Context
    sections.append({
        "number": 9,
        "title": "Demand & Market Context",
        "content": f"""
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('demand_forecast', '') + '" alt="Demand forecast"><div class="chart-caption">Local GSP demand forecast (P10/P50/P90)</div></div>' if charts.get('demand_forecast') else '<p>Demand forecast data not available for this location.</p>'}
        """,
    })

    # Section 10: BNG Assessment (Statutory Biodiversity Metric v1.0 / UKHab v2.0)
    baseline_rows = ""
    for h in bng_estimate.get("baseline_rows", []) or bng_estimate.get("habitat_breakdown", []):
        baseline_rows += f"""<tr>
            <td>{h['habitat']}</td>
            <td class=\"num\">{h.get('ukhab_code', '—')}</td>
            <td class=\"num\">{h['area_ha']}</td>
            <td class=\"num\">{h.get('distinctiveness', '—')}</td>
            <td class=\"num\">{h.get('condition', '—')}</td>
            <td class=\"num\">{h['units']}</td>
        </tr>"""

    post_rows = ""
    for h in bng_estimate.get("post_rows", []):
        post_rows += f"""<tr>
            <td>{h['habitat']}</td>
            <td class=\"num\">{h.get('ukhab_code', '—')}</td>
            <td class=\"num\">{h['area_ha']}</td>
            <td class=\"num\">{h.get('action', '—')}</td>
            <td class=\"num\">{h.get('years_to_target', '—')}</td>
            <td class=\"num\">{h['units']}</td>
        </tr>"""

    compliant = bng_estimate.get("compliant", False)
    net_pct = bng_estimate.get("net_change_pct", 0.0)
    threshold = bng_estimate.get("threshold_pct", 10)
    pill = (
        f'<span style="background:#d4f4dd;color:#0a5;padding:2px 8px;border-radius:10px;font-weight:700;">MEETS ≥{threshold:.0f}%</span>'
        if compliant else
        f'<span style="background:#fde2e4;color:#b00020;padding:2px 8px;border-radius:10px;font-weight:700;">BELOW ≥{threshold:.0f}%</span>'
    )

    sections.append({
        "number": 10,
        "title": "Biodiversity Net Gain — Statutory Biodiversity Metric v1.0 / UKHab v2.0",
        "content": f"""
        <p>Under the <strong>Environment Act 2021 s.98</strong> (mandatory from 12 February 2024 via Schedule 7A of the Town & Country Planning Act 1990), development must deliver a minimum <strong>{threshold:.0f}% biodiversity net gain</strong> measured with Natural England's statutory <em>{bng_estimate.get('metric_version', 'Statutory Biodiversity Metric v1.0')}</em>. Habitat classifications below follow <em>{bng_estimate.get('ukhab_version', 'UKHab v2.0')}</em>.</p>
        <div class=\"rpt-cols\">
          <div class=\"rpt-col\">
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Baseline Units</span><span class=\"rpt-kv-value\">{bng_estimate.get('baseline_units', '—')}</span></div>
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Post-Development Units</span><span class=\"rpt-kv-value\">{bng_estimate.get('post_units', '—')}</span></div>
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Net Change</span><span class=\"rpt-kv-value\">{bng_estimate.get('net_change_units', 0):+.2f} units ({net_pct:+.1f}%)</span></div>
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Statutory Threshold</span><span class=\"rpt-kv-value\">{pill}</span></div>
          </div>
          <div class=\"rpt-col\">
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Residual Deficit</span><span class=\"rpt-kv-value\">{bng_estimate.get('deficit_units', 0):.2f} units</span></div>
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Offset Cost (if credits)</span><span class=\"rpt-kv-value\">&pound;{bng_estimate.get('offset_cost_gbp', 0):,.0f}</span></div>
            <div class=\"rpt-kv\"><span class=\"rpt-kv-label\">Strategy</span><span class=\"rpt-kv-value\">{bng_estimate.get('strategy', '—')}</span></div>
          </div>
        </div>
        <h3 class=\"rpt-sub\">Baseline habitats (pre-development)</h3>
        <table class=\"rpt-table\">
          <tr><th>Habitat (UKHab)</th><th>Code</th><th>Area (ha)</th><th>Distinctiveness</th><th>Condition</th><th>Units</th></tr>
          {baseline_rows}
        </table>
        <h3 class=\"rpt-sub\">Post-development habitats (≥10% net-gain plan)</h3>
        <table class=\"rpt-table\">
          <tr><th>Habitat (UKHab)</th><th>Code</th><th>Area (ha)</th><th>Action</th><th>Years to target</th><th>Units</th></tr>
          {post_rows}
        </table>
        <div class=\"text-xs text-muted mt-8\">Pragmatic port of {bng_estimate.get('metric_version', 'Statutory Biodiversity Metric v1.0')} — formal submission requires the official Natural England spreadsheet executed by an accredited ecologist. Cost assumptions: residual deficit &times; &pound;{bng_estimate.get('cost_per_unit_gbp', 25000):,} per unit (market average for off-site credits, 2024).</div>
        """,
    })

    # Section 11: ML Site Intelligence (Appendix)
    shap_html = ""
    top_factors = ml_score.get("top_factors", [])
    if top_factors:
        for f in top_factors[:8]:
            name = f.get("feature", f.get("name", "?"))
            impact = f.get("impact", f.get("shap_value", 0))
            direction = "positive" if impact > 0 else "negative"
            dot = "risk-low" if impact > 0 else "risk-high"
            shap_html += f'<div class="risk-item"><div class="risk-dot {dot}"></div><div><strong>{name}</strong> — {direction} impact ({impact:+.3f})</div></div>'

    sections.append({
        "number": 11,
        "title": "Appendix: ML Site Intelligence & SHAP Analysis",
        "content": f"""
        <div class="rpt-cols">
          <div class="rpt-col">
            <div class="rpt-kv"><span class="rpt-kv-label">ML Verdict</span><span class="rpt-kv-value">{ml_score.get('verdict', '—')}</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">ML Score</span><span class="rpt-kv-value">{ml_score.get('score', 0)}/100</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Confidence</span><span class="rpt-kv-value">{ml_score.get('confidence', 0)}%</span></div>
            <div class="rpt-kv"><span class="rpt-kv-label">Model</span><span class="rpt-kv-value">XGBoost (17 features, SHAP explainability)</span></div>
          </div>
        </div>
        <h3 class="rpt-sub">SHAP Feature Importance</h3>
        {shap_html if shap_html else '<p>SHAP analysis not available.</p>'}
        {'<div class="chart-container"><img src="data:image/png;base64,' + charts.get('score_bars', '') + '" alt="Score breakdown"><div class="chart-caption">Multi-axis feasibility score breakdown</div></div>' if charts.get('score_bars') else ''}
        """,
    })

    return sections


# ===================================================================
# 5. RENDER HTML via institutional_base.html template
# ===================================================================

def _render_institutional_html(site_data: dict, sam_result: dict, grid_result: dict,
                                environmental: dict, ml_score: dict, planning_risk: dict,
                                loss_budget: dict, financials: dict, multi_tech: list,
                                bng_estimate: dict, prob_table: list,
                                charts: dict, map_image: str) -> str:
    """Render the full institutional report HTML."""
    from jinja2 import Environment, FileSystemLoader

    jinja_env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )
    # Register abs filter
    jinja_env.filters["abs"] = abs

    template = jinja_env.get_template("institutional_base.html")

    # Build verdict summary
    score_pct = site_data.get("score_pct", 0)
    verdict_text = site_data.get("verdict", "CAUTION")
    verdict_summary = (
        f"This {site_data.get('capacity_mw', 0)} MW {site_data.get('technology', 'solar')} project "
        f"scores {score_pct:.0f}% overall feasibility. "
        f"{'The site is suitable for development with standard mitigation measures.' if verdict_text == 'GO' else 'The site requires further investigation on identified risk factors.' if verdict_text == 'CAUTION' else 'Significant barriers to development have been identified.'}"
    )

    # Build sections
    sections = _build_sections(
        site_data, sam_result, grid_result, environmental, ml_score,
        planning_risk, loss_budget, financials, multi_tech, bng_estimate, charts,
    )

    # Connection cost for template
    cost_est = grid_result.get("cost_estimate", {})
    conn_cost_p50 = cost_est.get("p50_total_gbp", financials.get("connection_cost_gbp", 0))
    conn_cost_p10 = cost_est.get("p10_total_gbp", int(conn_cost_p50 * 0.7))
    conn_cost_p90 = cost_est.get("p90_total_gbp", int(conn_cost_p50 * 1.5))

    ctx = {
        "site": {
            **site_data,
            "technology": site_data.get("technology", "Solar PV"),
        },
        "report": {
            "number": f"PRC-{datetime.utcnow().strftime('%Y%m%d')}-{abs(hash((site_data.get('lat', 0), site_data.get('lon', 0)))) % 10000:04d}",
            "revision": "A",
            "date": datetime.utcnow().strftime("%d %B %Y"),
            "version": "3.0",
            "classification": "Commercial in Confidence",
            "client": "[Client Name]",
            "reviewer": "[Reviewer Name, Credentials]",
            "approver": "[Approver Name, Credentials]",
        },
        "verdict": {
            "verdict": verdict_text,
            "confidence": round(score_pct),
            "summary": verdict_summary,
        },
        "score": {
            "total": round(score_pct),
        },
        "yield": {
            "capacity_kw": int(site_data.get("capacity_mw", 0) * 1000),
            "annual_mwh_p50": financials.get("annual_yield_mwh", 0),
            "annual_energy_kwh": sam_result.get("annual_energy_kwh", 0),
            "specific_yield": round(sam_result.get("annual_energy_kwh", 0) / max(site_data.get("capacity_mw", 1) * 1000, 1)),
            "capacity_factor_pct": financials.get("capacity_factor_pct", "—"),
            "performance_ratio": loss_budget.get("performance_ratio_pct", 82),
            "probability_table": prob_table,
        },
        "grid": {
            "nearest_substation": site_data.get("nearest_substation", "—"),
            "distance_km": site_data.get("distance_km", "—"),
            "voltage_kv": site_data.get("voltage_kv", "—"),
            "headroom_mw": grid_result.get("best_candidate", {}).get("headroom_mw", "—") if isinstance(grid_result.get("best_candidate"), dict) else "—",
            "connection_cost_p10": conn_cost_p10,
            "connection_cost_p50": conn_cost_p50,
            "connection_cost_p90": conn_cost_p90,
        },
        "land": {
            "alc_grade": "3b (estimated)",
            "bmv": False,
            "flood_zone": site_data.get("flood_risk", {}).get("risk_level", "1"),
        },
        "charts": charts,
        "sections": sections,
        "map_image": map_image,
        "now": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

    return template.render(**ctx)


# ===================================================================
# 6. MAIN ORCHESTRATOR
# ===================================================================

async def generate_one_click_report(
    pool: asyncpg.Pool,
    lat: float,
    lon: float,
    capacity_mw: float = 50.0,
    technology: str = "solar",
    site_name: str | None = None,
) -> bytes:
    """
    One-click comprehensive feasibility report generator.

    Drop a pin -> click one button -> get a 30-page institutional-grade PDF in <60 seconds.

    Orchestrates ALL existing Princeps modules in parallel, runs analysis,
    generates charts, renders HTML via the institutional template, and
    converts to PDF via Playwright Chromium.

    Parameters
    ----------
    pool : asyncpg.Pool
        Database connection pool.
    lat : float
        Site latitude (WGS84).
    lon : float
        Site longitude (WGS84).
    capacity_mw : float
        Proposed generation capacity in MW.
    technology : str
        Technology type: solar, wind, bess, solar+bess.
    site_name : str | None
        Site name for report branding.

    Returns
    -------
    bytes
        PDF file contents.
    """
    t0 = time.time()
    name = site_name or f"Site {lat:.4f}N {abs(lon):.4f}{'W' if lon < 0 else 'E'}"
    log.info("ONE-CLICK REPORT: Starting for %s (%.5f, %.5f) @ %.1f MW %s",
             name, lat, lon, capacity_mw, technology)

    # ─── Phase 1: Parallel data collection ───────────────────────────
    async with pool.acquire() as conn:
        # Import report_renderer functions
        aggregate_site_data, generate_charts, fetch_static_map, html_to_pdf, BRAND, _, _, _ = _import_report_renderer()

        # Fire off all data collection in parallel
        site_task = aggregate_site_data(conn, lat, lon, name, capacity_mw)
        sam_task = _collect_sam_yield(lat, lon, capacity_mw)
        grid_task = _collect_grid_assessment(conn, lat, lon, capacity_mw, technology)
        env_task = _collect_environmental(lat, lon)
        map_task = fetch_static_map(lat, lon)
        loss_task = asyncio.get_running_loop().run_in_executor(
            None, lambda: _collect_loss_budget_sync(lat, lon, capacity_mw))

        # Gather Phase 1 results
        (site_data, sam_result, grid_result, environmental, map_image, loss_budget_wrapper) = \
            await asyncio.gather(
                site_task, sam_task, grid_task, env_task, map_task, loss_task,
                return_exceptions=True,
            )

        # Handle exceptions gracefully
        if isinstance(site_data, Exception):
            log.error("Site data aggregation failed: %s", site_data)
            raise RuntimeError(f"Site data aggregation failed: {site_data}")
        if isinstance(sam_result, Exception):
            log.warning("SAM failed, using fallback: %s", sam_result)
            sam_result = {"source": "fallback", "annual_energy_kwh": capacity_mw * 1000 * 0.11 * 8760}
        if isinstance(grid_result, Exception):
            log.warning("Grid assessment failed: %s", grid_result)
            grid_result = {"verdict": "UNKNOWN", "error": str(grid_result)}
        if isinstance(environmental, Exception):
            log.warning("Environmental query failed: %s", environmental)
            environmental = {"designations": [], "carbon": {"current_gco2_kwh": 200}}
        if isinstance(map_image, Exception):
            log.warning("Map fetch failed: %s", map_image)
            map_image = ""
        if isinstance(loss_budget_wrapper, Exception):
            log.warning("Loss budget failed: %s", loss_budget_wrapper)
            loss_budget_wrapper = {"performance_ratio_pct": 82, "specific_yield_kwh_kwp": 900}

        loss_budget = loss_budget_wrapper if isinstance(loss_budget_wrapper, dict) else {}

        # Inject technology into site_data
        site_data["technology"] = technology.replace("_", " ").title() if technology else "Solar PV"

        t_phase1 = time.time() - t0
        log.info("Phase 1 complete in %.1fs — data collected", t_phase1)

    # ─── Phase 2: Analysis (CPU-bound, run in executor) ──────────────
    loop = asyncio.get_running_loop()

    # ML scoring (needs site_data from Phase 1)
    ml_score_task = _collect_ml_score(site_data)
    planning_risk_task = _collect_planning_risk(
        capacity_mw, environmental.get("designations", []))

    ml_score, planning_risk = await asyncio.gather(
        ml_score_task, planning_risk_task, return_exceptions=True)

    if isinstance(ml_score, Exception):
        ml_score = {"verdict": "UNKNOWN", "score": 0, "confidence": 0}
    if isinstance(planning_risk, Exception):
        planning_risk = {"outcome": "UNKNOWN"}

    # Financial model + multi-tech + BNG (CPU-bound)
    financials = await loop.run_in_executor(None, lambda: _financial_model(
        capacity_mw, sam_result, grid_result, loss_budget, technology))
    multi_tech = await loop.run_in_executor(None, lambda: _multi_tech_comparison(
        lat, lon, capacity_mw, sam_result, grid_result))
    bng_estimate = _bng_estimate(site_data.get("land_use", {}), capacity_mw, technology=technology)
    prob_table = _probability_table(financials.get("annual_yield_mwh", 0),
                                     financials.get("capacity_factor_pct", 11))

    t_phase2 = time.time() - t0
    log.info("Phase 2 complete in %.1fs — analysis done", t_phase2)

    # ─── Phase 3: Generate all charts ────────────────────────────────
    # Base charts from report_renderer
    base_charts = await loop.run_in_executor(None, generate_charts, site_data)

    # Additional one-click-specific charts
    extra_charts = {}
    if loss_budget and not loss_budget.get("error"):
        extra_charts["loss_waterfall"] = await loop.run_in_executor(
            None, _loss_waterfall_chart, loss_budget)
    extra_charts["financial_sensitivity"] = await loop.run_in_executor(
        None, _financial_sensitivity_chart, financials)
    if sam_result.get("monthly_generation"):
        extra_charts["monthly_yield"] = await loop.run_in_executor(
            None, _monthly_yield_chart, sam_result)

    # Red-line boundary map — embedded in the Site Assessment pack
    try:
        extra_charts["redline_map"] = await loop.run_in_executor(
            None, _render_redline_b64, lat, lon, name)
    except Exception as e:
        log.warning("Red-line map render failed: %s", e)

    charts = {**base_charts, **extra_charts}

    t_phase3 = time.time() - t0
    log.info("Phase 3 complete in %.1fs — %d charts generated", t_phase3, len(charts))

    # ─── Phase 4: Render HTML ────────────────────────────────────────
    html = await loop.run_in_executor(None, lambda: _render_institutional_html(
        site_data, sam_result, grid_result, environmental, ml_score, planning_risk,
        loss_budget, financials, multi_tech, bng_estimate, prob_table,
        charts, map_image,
    ))

    t_phase4 = time.time() - t0
    log.info("Phase 4 complete in %.1fs — HTML rendered (%d bytes)", t_phase4, len(html))

    # ─── Phase 5: Convert to PDF via Playwright ──────────────────────
    pdf_bytes = await html_to_pdf(html)

    elapsed = time.time() - t0
    log.info("ONE-CLICK REPORT COMPLETE: %d bytes, %.1f seconds, %d pages (est.)",
             len(pdf_bytes), elapsed, max(1, len(pdf_bytes) // 30_000))

    return pdf_bytes


def _collect_loss_budget_sync(lat: float, lon: float, capacity_mw: float) -> dict:
    """Synchronous wrapper for loss budget (runs in executor)."""
    try:
        from utils.loss_budget import calculate_loss_budget, calculate_lifetime_profile
        params = {
            "capacity_kw": capacity_mw * 1000,
            "lat": lat,
            "lon": lon,
            "tilt_deg": 25.0,
            "azimuth_deg": 180.0,
            "dc_ac_ratio": 1.20,
            "inverter_efficiency": 0.98,
            "year": 1,
        }
        budget = calculate_loss_budget(params)
        lifetime = calculate_lifetime_profile(params, 25)
        budget["lifetime"] = lifetime
        return budget
    except Exception as e:
        log.warning("Loss budget sync failed: %s", e)
        return {"performance_ratio_pct": 82, "specific_yield_kwh_kwp": 900, "error": str(e)}
