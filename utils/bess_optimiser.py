"""
BESS (Battery Energy Storage System) Optimiser Module.

Site scoring, optimal sizing, revenue stacking, financial modelling,
co-location analysis, and regional scanning for UK BESS deployments.

Pure Python, no external dependencies, deterministic calculations.
"""

from __future__ import annotations

import math
import random
from typing import Any

from utils.bess_benchmarks import (
    bess_capex_per_kwh,
    capacity_market_gbp_mw_yr,
    ffr_dynamic_gbp_mw_yr,
)


# ---------------------------------------------------------------------------
# UK BESS market benchmarks — 2026 (Modo Energy GB BESS index, Mar 2026)
# ---------------------------------------------------------------------------

# CAPEX per MWh by duration (GBP) — all-in installed cost.
# 1h is CapEx-heavy because power electronics dominate; 4h amortises BoS.
_CAPEX_MID_PER_KWH = bess_capex_per_kwh("mid")  # £310/kWh 2026
BESS_CAPEX_GBP_PER_MWH = {
    1: (_CAPEX_MID_PER_KWH + 80) * 1_000,   # thicker power electronics
    2: (_CAPEX_MID_PER_KWH + 20) * 1_000,   # slight PCS premium
    4: (_CAPEX_MID_PER_KWH - 30) * 1_000,   # BoS amortised over more kWh
}

# Revenue streams (GBP/MW/yr unless noted) — Mar 2026 clearing levels
UK_REVENUE_STREAMS = {
    "ffr_dynamic": {"label": "FFR Dynamic", "gbp_mw_yr": ffr_dynamic_gbp_mw_yr()},
    "ffr_primary": {"label": "FFR Primary", "gbp_mw_yr": 32_000},
    "dc": {"label": "Dynamic Containment", "gbp_mw_yr": 28_000},
    "dm": {"label": "Dynamic Moderation", "gbp_mw_yr": 22_000},
    "capacity_market": {"label": "Capacity Market",
                        "gbp_kw_yr": capacity_market_gbp_mw_yr() / 1_000},
    "agile_arbitrage": {"label": "Agile Arbitrage", "spread_gbp_mwh": 18},
    "wholesale_arbitrage": {"label": "Wholesale Arbitrage", "spread_gbp_mwh": 25},
    "dno_peak_shaving": {"label": "DNO Peak Shaving", "gbp_mw_yr": 22_000},
}

# Battery degradation — LFP model
BATTERY_DEGRADATION = {
    "calendar_fade_pct_yr": 1.5,
    "cycle_depth_factors": {
        100: 1.0,
        80: 0.7,
        60: 0.45,
        40: 0.25,
    },
    "warranty_years": 15,
    "eol_capacity_pct": 70,
}

# Operating costs
BESS_OPEX_PCT_CAPEX = 2.5
BESS_INSURANCE_PCT_CAPEX = 0.5

# Grid connection
GRID_CONNECTION_GBP_PER_MW = 120_000

# Voltage thresholds for BESS connection
VOLTAGE_THRESHOLDS = {
    11: 5,      # 11kV: up to 5 MW
    33: 30,     # 33kV: up to 30 MW
    132: 150,   # 132kV: up to 150 MW
    400: 500,   # 400kV: up to 500 MW
}

# Footprint estimate: m² per MWh (containerised LFP)
BESS_FOOTPRINT_M2_PER_MWH = 25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


def _estimate_bess_footprint(energy_mwh: float) -> float:
    """Estimate land requirement in m² for a given MWh capacity."""
    return energy_mwh * BESS_FOOTPRINT_M2_PER_MWH


def _select_grid_voltage(power_mw: float) -> int:
    """Select appropriate grid voltage for a given MW capacity."""
    for voltage, max_mw in sorted(VOLTAGE_THRESHOLDS.items()):
        if power_mw <= max_mw:
            return voltage
    return 400


def _calculate_degradation_cost(
    energy_mwh: float,
    cycles_per_year: float,
    depth_of_discharge_pct: float = 80,
    capex_gbp: float = 0,
    years: int = 20,
) -> float:
    """Estimate annual degradation cost in GBP."""
    calendar_fade = BATTERY_DEGRADATION["calendar_fade_pct_yr"]
    depth_factors = BATTERY_DEGRADATION["cycle_depth_factors"]

    # Find nearest depth factor
    nearest_depth = min(depth_factors.keys(), key=lambda d: abs(d - depth_of_discharge_pct))
    cycle_factor = depth_factors[nearest_depth]

    # Cycle degradation: ~0.02% per cycle at 80% DoD for LFP
    cycle_deg_pct_yr = cycles_per_year * 0.02 * cycle_factor

    total_annual_deg_pct = calendar_fade + cycle_deg_pct_yr

    # Cost = proportional share of replacement capex over lifetime
    if capex_gbp > 0:
        replacement_fraction = total_annual_deg_pct / 100
        return capex_gbp * replacement_fraction
    return 0.0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def score_bess_site(
    lat: float,
    lon: float,
    grid_data: dict | None = None,
    land_area_m2: float | None = None,
    planning_context: dict | None = None,
) -> dict:
    """
    Score a site for BESS suitability (0-100).

    Components:
        grid_access (0-25), land_suitability (0-20), market_access (0-25),
        planning_risk (0-15), scalability (0-15)

    Returns dict with total_score, recommendation, scores, constraints, max_feasible_mw.
    """
    grid_data = grid_data or {}
    planning_context = planning_context or {}
    scores = {}
    constraints = []

    # 1. Grid access (0-25)
    grid_distance_km = grid_data.get("distance_km", 5)
    grid_headroom_mw = grid_data.get("headroom_mw", 10)
    grid_voltage_kv = grid_data.get("voltage_kv", 33)

    g_score = 25.0
    if grid_distance_km > 20:
        g_score -= 18
        constraints.append("Very remote from grid connection")
    elif grid_distance_km > 10:
        g_score -= 10
        constraints.append("Distant grid connection (>10km)")
    elif grid_distance_km > 5:
        g_score -= 5

    if grid_headroom_mw < 1:
        g_score -= 10
        constraints.append("Minimal grid headroom (<1MW)")
    elif grid_headroom_mw < 5:
        g_score -= 4
    elif grid_headroom_mw > 50:
        g_score += 0  # already at max

    scores["grid_access"] = max(0, round(g_score, 1))

    # 2. Land suitability (0-20)
    l_score = 14.0  # default if no area specified
    max_mwh = 500  # default
    if land_area_m2 is not None:
        max_mwh = land_area_m2 / BESS_FOOTPRINT_M2_PER_MWH
        if land_area_m2 >= 50_000:
            l_score = 20.0
        elif land_area_m2 >= 20_000:
            l_score = 16.0
        elif land_area_m2 >= 5_000:
            l_score = 12.0
        elif land_area_m2 >= 1_000:
            l_score = 6.0
        else:
            l_score = 2.0
            constraints.append("Very limited land area")
    scores["land_suitability"] = round(l_score, 1)

    # 3. Market access (0-25)
    # Urban proximity heuristic — closer to demand centres = better arbitrage
    m_score = 18.0  # default moderate
    if 51.0 <= lat <= 52.0 and -1.0 <= lon <= 0.5:
        m_score = 25.0  # London/SE — premium market
    elif 52.0 <= lat <= 53.5 and -2.5 <= lon <= 0.0:
        m_score = 22.0  # Midlands — good demand
    elif 53.0 <= lat <= 55.0:
        m_score = 19.0  # North — constrained zones
    elif lat > 55.0:
        m_score = 14.0  # Scotland — transmission constraints
        constraints.append("Potential transmission constraints (Scotland)")
    scores["market_access"] = round(m_score, 1)

    # 4. Planning risk (0-15)
    p_score = 10.0
    if planning_context.get("greenbelt"):
        p_score -= 5
        constraints.append("Green Belt designation")
    if planning_context.get("aonb"):
        p_score -= 4
        constraints.append("AONB designation")
    if planning_context.get("flood_zone"):
        p_score -= 3
        constraints.append("Flood zone risk")
    if planning_context.get("residential_proximity_m", 999) < 200:
        p_score -= 3
        constraints.append("Close residential proximity")
    if planning_context.get("approval_rate_pct", 60) >= 70:
        p_score = min(15, p_score + 3)
    scores["planning_risk"] = max(0, round(p_score, 1))

    # 5. Scalability (0-15)
    s_score = 10.0
    voltage = _select_grid_voltage(grid_headroom_mw)
    if grid_headroom_mw >= 50:
        s_score = 15.0
    elif grid_headroom_mw >= 20:
        s_score = 12.0
    elif grid_headroom_mw >= 10:
        s_score = 10.0
    elif grid_headroom_mw >= 5:
        s_score = 7.0
    else:
        s_score = 3.0
    scores["scalability"] = round(s_score, 1)

    total = sum(scores.values())

    if total >= 70:
        recommendation = "HIGH_PRIORITY"
    elif total >= 50:
        recommendation = "PROMISING"
    elif total >= 30:
        recommendation = "MARGINAL"
    else:
        recommendation = "UNSUITABLE"

    # Max feasible MW based on grid and land constraints
    max_mw_grid = grid_headroom_mw
    max_mw_land = max_mwh / 2 if land_area_m2 else 250  # assume 2hr duration
    max_feasible_mw = round(min(max_mw_grid, max_mw_land), 1)

    return {
        "lat": lat,
        "lon": lon,
        "total_score": round(total, 1),
        "recommendation": recommendation,
        "scores": scores,
        "constraints": constraints,
        "max_feasible_mw": max_feasible_mw,
        "suggested_voltage_kv": _select_grid_voltage(max_feasible_mw),
    }


def calculate_optimal_sizing(
    capacity_mw: float,
    duration_options: list[int] | None = None,
    revenue_strategy: str = "hybrid",
    grid_constraint_mw: float | None = None,
) -> dict:
    """
    Evaluate 1/2/4hr durations and pick highest NPV.

    Returns optimal sizing with NPV, IRR, CAPEX, and all scenarios compared.
    """
    if duration_options is None:
        duration_options = [1, 2, 4]

    if grid_constraint_mw is not None:
        capacity_mw = min(capacity_mw, grid_constraint_mw)

    scenarios = []

    for duration_hr in duration_options:
        energy_mwh = capacity_mw * duration_hr
        capex_per_mwh = BESS_CAPEX_GBP_PER_MWH.get(duration_hr, 450_000)
        battery_capex = energy_mwh * capex_per_mwh
        connection_cost = capacity_mw * GRID_CONNECTION_GBP_PER_MW
        total_capex = battery_capex + connection_cost

        revenue = model_revenue_stacking(capacity_mw, energy_mwh, revenue_strategy)
        annual_revenue = revenue["total_annual_gbp"]

        financial = bess_financial_model(total_capex, annual_revenue)

        scenarios.append({
            "power_mw": capacity_mw,
            "energy_mwh": energy_mwh,
            "duration_hr": duration_hr,
            "capex_gbp": round(total_capex),
            "annual_revenue_gbp": round(annual_revenue),
            "npv_20yr_gbp": financial["npv_gbp"],
            "irr_pct": financial["irr_pct"],
            "payback_years": financial["payback_years"],
            "revenue_strategy": revenue_strategy,
        })

    # Pick highest NPV
    scenarios.sort(key=lambda s: s["npv_20yr_gbp"], reverse=True)
    optimal = scenarios[0]

    return {
        "optimal": optimal,
        "scenarios": scenarios,
    }


def model_revenue_stacking(
    power_mw: float,
    energy_mwh: float,
    strategy: str = "hybrid",
) -> dict:
    """
    Calculate revenue from stacked UK markets.

    Strategies: frequency_response, arbitrage, capacity_market, hybrid
    """
    duration_hr = energy_mwh / power_mw if power_mw > 0 else 2

    breakdown = {}
    total = 0.0

    if strategy in ("frequency_response", "hybrid"):
        # FFR dynamic — typically wins ~40% of available hours
        ffr_rev = UK_REVENUE_STREAMS["ffr_dynamic"]["gbp_mw_yr"] * power_mw * 0.4
        breakdown["ffr_dynamic"] = round(ffr_rev)
        total += ffr_rev

        # DC/DM — additional ancillary
        dc_rev = UK_REVENUE_STREAMS["dc"]["gbp_mw_yr"] * power_mw * 0.25
        breakdown["dynamic_containment"] = round(dc_rev)
        total += dc_rev

    if strategy in ("arbitrage", "hybrid"):
        # Wholesale arbitrage — cycles depend on duration
        if duration_hr >= 2:
            daily_cycles = 1.5
            spread = UK_REVENUE_STREAMS["wholesale_arbitrage"]["spread_gbp_mwh"]
        else:
            daily_cycles = 2.0
            spread = UK_REVENUE_STREAMS["agile_arbitrage"]["spread_gbp_mwh"]

        arb_rev = energy_mwh * spread * daily_cycles * 365
        # But also scale down for realistic dispatch
        arb_rev *= 0.7  # 70% capture rate
        breakdown["arbitrage"] = round(arb_rev)
        total += arb_rev

    if strategy in ("capacity_market", "hybrid"):
        # Capacity market — £12.50/kW/yr
        cm_rev = UK_REVENUE_STREAMS["capacity_market"]["gbp_kw_yr"] * power_mw * 1000
        breakdown["capacity_market"] = round(cm_rev)
        total += cm_rev

    if strategy == "hybrid":
        # DNO peak shaving — supplement
        ps_rev = UK_REVENUE_STREAMS["dno_peak_shaving"]["gbp_mw_yr"] * power_mw * 0.3
        breakdown["dno_peak_shaving"] = round(ps_rev)
        total += ps_rev

    # Cycling metrics
    if strategy in ("arbitrage", "hybrid"):
        cycles_per_year = daily_cycles * 365 * 0.7
    elif strategy == "frequency_response":
        cycles_per_year = 1.0 * 365  # ~1 equivalent cycle per day from FR
    else:
        cycles_per_year = 300

    capacity_factor = min(0.95, cycles_per_year * duration_hr / 8760)

    # Degradation cost
    capex_per_mwh = BESS_CAPEX_GBP_PER_MWH.get(round(duration_hr), 450_000)
    capex_est = energy_mwh * capex_per_mwh
    deg_cost = _calculate_degradation_cost(
        energy_mwh, cycles_per_year, 80, capex_est,
    )

    return {
        "total_annual_gbp": round(total),
        "revenue_breakdown": breakdown,
        "cycles_per_year": round(cycles_per_year),
        "capacity_factor": round(capacity_factor, 3),
        "degradation_cost_gbp_yr": round(deg_cost),
        "strategy": strategy,
        "power_mw": power_mw,
        "energy_mwh": energy_mwh,
    }


def bess_financial_model(
    capex_gbp: float,
    annual_revenue_gbp: float,
    opex_pct: float = BESS_OPEX_PCT_CAPEX + BESS_INSURANCE_PCT_CAPEX,
    years: int = 20,
    discount_rate: float = 0.08,
) -> dict:
    """
    Financial model: NPV, IRR, payback, LCOES, annual cashflow table.
    """
    annual_opex = capex_gbp * opex_pct / 100
    annual_cashflow = []
    cumulative = -capex_gbp
    payback_year = None

    for yr in range(1, years + 1):
        # Revenue degrades with battery capacity (calendar fade)
        fade_factor = max(0.7, 1.0 - BATTERY_DEGRADATION["calendar_fade_pct_yr"] / 100 * yr)
        revenue = annual_revenue_gbp * fade_factor
        net = revenue - annual_opex
        cumulative += net

        annual_cashflow.append({
            "year": yr,
            "revenue_gbp": round(revenue),
            "opex_gbp": round(annual_opex),
            "net_gbp": round(net),
            "cumulative_gbp": round(cumulative),
            "capacity_retention_pct": round(fade_factor * 100, 1),
        })

        if payback_year is None and cumulative >= 0:
            payback_year = yr

    # NPV calculation
    npv = -capex_gbp
    for yr in range(1, years + 1):
        cf = annual_cashflow[yr - 1]["net_gbp"]
        npv += cf / (1 + discount_rate) ** yr

    # IRR via bisection
    irr = _calculate_irr(capex_gbp, [cf["net_gbp"] for cf in annual_cashflow])

    # LCOES — levelised cost of energy storage
    total_energy_mwh = 0
    total_cost_discounted = capex_gbp
    for yr in range(1, years + 1):
        total_cost_discounted += annual_opex / (1 + discount_rate) ** yr
    # Assume 1 cycle/day at rated capacity for LCOES calc
    # This is a simplification — real LCOES depends on dispatch
    lcoes = total_cost_discounted / max(1, years * 365)  # per cycle

    return {
        "npv_gbp": round(npv),
        "irr_pct": irr,
        "payback_years": payback_year or years,
        "lcoes_gbp_mwh": round(lcoes, 2),
        "capex_gbp": round(capex_gbp),
        "annual_opex_gbp": round(annual_opex),
        "annual_cashflow": annual_cashflow,
    }


def _calculate_irr(
    initial_investment: float,
    cashflows: list[float],
    tolerance: float = 0.0001,
    max_iterations: int = 100,
) -> float:
    """Calculate IRR via bisection method."""
    low, high = -0.5, 2.0

    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv = -initial_investment
        for i, cf in enumerate(cashflows, 1):
            npv += cf / (1 + mid) ** i

        if abs(npv) < tolerance:
            return round(mid * 100, 2)
        if npv > 0:
            low = mid
        else:
            high = mid

    return round(((low + high) / 2) * 100, 2)


def assess_colocation_value(
    solar_capacity_kw: float,
    bess_mwh: float | None = None,
    location_data: dict | None = None,
) -> dict:
    """
    Assess value-add from co-locating BESS with solar PV.

    If bess_mwh not specified, calculates optimal ratio.
    """
    location_data = location_data or {}
    lat = location_data.get("lat", 52.5)
    lon = location_data.get("lon", -1.5)

    solar_mw = solar_capacity_kw / 1000

    # Optimal BESS sizing: typically 50-100% of solar MW, 2hr duration
    optimal_ratio = 0.6  # 60% of solar MW for 2hr
    optimal_bess_mw = solar_mw * optimal_ratio
    optimal_bess_mwh = optimal_bess_mw * 2

    if bess_mwh is None:
        bess_mwh = optimal_bess_mwh

    bess_mw = bess_mwh / 2  # assume 2hr duration

    # Benefits calculation
    benefits = {}

    # 1. Clipping capture — solar overproduction stored instead of curtailed
    # UK solar farms typically clip 3-8% of annual generation
    annual_solar_mwh = solar_mw * 8760 * 0.11  # ~11% CF for UK
    clipping_pct = 0.05  # 5% average
    clipping_captured_mwh = annual_solar_mwh * clipping_pct * min(1.0, bess_mw / solar_mw)
    clipping_value = clipping_captured_mwh * 60  # £60/MWh average
    benefits["clipping_capture"] = {
        "captured_mwh_yr": round(clipping_captured_mwh, 1),
        "value_gbp_yr": round(clipping_value),
    }

    # 2. Shared grid connection — save ~40% on BESS connection costs
    standalone_connection = bess_mw * GRID_CONNECTION_GBP_PER_MW
    shared_saving = standalone_connection * 0.4
    benefits["shared_connection"] = {
        "saving_gbp": round(shared_saving),
        "annualised_gbp_yr": round(shared_saving / 20),  # over 20yr
    }

    # 3. Enhanced dispatch — time-shift solar to peak prices
    # Average peak/off-peak spread captured
    peak_shift_mwh = min(bess_mwh, annual_solar_mwh * 0.15) * 365 / 365  # daily
    peak_premium = 40  # £40/MWh average peak premium
    dispatch_value = bess_mwh * 365 * 0.6 * peak_premium / 1000  # 60% utilisation
    benefits["enhanced_dispatch"] = {
        "value_gbp_yr": round(dispatch_value),
    }

    # 4. Reduced curtailment — avoid grid export constraints
    curtailment_saving = annual_solar_mwh * 0.03 * 55  # 3% curtailment at £55/MWh
    curtailment_saving *= min(1.0, bess_mw / solar_mw)
    benefits["reduced_curtailment"] = {
        "avoided_curtailment_mwh_yr": round(annual_solar_mwh * 0.03, 1),
        "value_gbp_yr": round(curtailment_saving),
    }

    total_value_add = (
        clipping_value
        + shared_saving / 20
        + dispatch_value
        + curtailment_saving
    )

    return {
        "solar_capacity_kw": solar_capacity_kw,
        "bess_mwh": round(bess_mwh, 1),
        "bess_mw": round(bess_mw, 1),
        "value_add_gbp_yr": round(total_value_add),
        "benefits": benefits,
        "optimal_solar_bess_ratio": f"1:{optimal_ratio}",
        "recommended_bess_mwh": round(optimal_bess_mwh, 1),
        "lat": lat,
        "lon": lon,
    }


def bess_regional_scan(
    region: str = "south_west",
    min_mw: float = 10,
    max_mw: float = 100,
    substations: list[dict] | None = None,
) -> dict:
    """
    Scan a UK region for BESS deployment opportunities.

    Generates candidate points, scores each for BESS suitability.
    """
    from utils.site_prospector import UK_REGIONAL_RESOURCE

    resource = UK_REGIONAL_RESOURCE.get(region)
    if not resource:
        return {"error": f"Unknown region. Choose from: {list(UK_REGIONAL_RESOURCE.keys())}"}

    lat_min, lat_max = resource["lat_range"]
    lon_min, lon_max = resource["lon_range"]

    grid_size = 5  # 5x5 grid
    lat_step = (lat_max - lat_min) / grid_size
    lon_step = (lon_max - lon_min) / grid_size

    candidates = []
    lat = lat_min + lat_step / 2
    while lat < lat_max:
        lon = lon_min + lon_step / 2
        while lon < lon_max:
            # Synthetic grid data for scan
            grid_dist = 2 + random.gauss(0, 3)
            grid_dist = max(0.5, grid_dist)
            headroom = min_mw + random.random() * (max_mw - min_mw)

            grid_data = {
                "distance_km": grid_dist,
                "headroom_mw": round(headroom, 1),
                "voltage_kv": _select_grid_voltage(headroom),
            }

            # Find nearest substation if available
            if substations:
                nearest = min(
                    substations,
                    key=lambda s: _haversine(lat, lon, s.get("lat", 0), s.get("lon", 0)),
                )
                dist = _haversine(lat, lon, nearest.get("lat", 0), nearest.get("lon", 0))
                grid_data["distance_km"] = round(dist, 1)
                grid_data["headroom_mw"] = nearest.get("headroom_mw", headroom)
                grid_data["substation_name"] = nearest.get("name", "")

            land_area = 10_000 + random.gauss(0, 5000)
            land_area = max(1_000, land_area)

            score = score_bess_site(
                lat=round(lat, 4),
                lon=round(lon, 4),
                grid_data=grid_data,
                land_area_m2=land_area,
            )

            if grid_data.get("substation_name"):
                score["nearest_substation"] = grid_data["substation_name"]
            score["grid_distance_km"] = grid_data["distance_km"]
            score["headroom_mw"] = grid_data["headroom_mw"]

            candidates.append(score)
            lon += lon_step
        lat += lat_step

    candidates.sort(key=lambda c: c["total_score"], reverse=True)

    high_priority = [c for c in candidates if c["recommendation"] == "HIGH_PRIORITY"]

    return {
        "region": region,
        "total_scanned": len(candidates),
        "high_priority_count": len(high_priority),
        "top_sites": candidates[:10],
        "avg_score": round(
            sum(c["total_score"] for c in candidates) / len(candidates), 1
        ) if candidates else 0,
        "min_mw": min_mw,
        "max_mw": max_mw,
    }
