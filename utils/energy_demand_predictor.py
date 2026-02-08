"""
UK Energy Demand Predictor & Storage Optimizer.

Integrates approaches from:
  - caolangan/Predicting-UK-Energy-Demand (SARIMA seasonal patterns, load status)
  - Live BMRS/NESO data (updated real-time source)
  - 2050 net-zero storage optimization (energy balance simulation)

Provides:
  1. Demand forecast (24h/7d) using seasonal patterns + recent BMRS data
  2. Generation mix forecast based on current patterns
  3. Storage optimization: optimal battery/hydrogen sizing
  4. Load status warnings (Manageable/Amber/Red)
"""

import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 15

# ── UK Grid Constants (from GridWatch/BMRS historical analysis) ──

# Seasonal demand multipliers (monthly, index 0=Jan)
# Derived from 10yr GridWatch data: winter peak ~42GW, summer trough ~25GW
MONTHLY_DEMAND_FACTOR = [
    1.18, 1.15, 1.05, 0.95, 0.88, 0.82,
    0.80, 0.82, 0.90, 1.00, 1.10, 1.16,
]

# Hourly demand shape (fraction of daily mean, 0-23h)
# Derived from BMRS half-hourly data
HOURLY_DEMAND_SHAPE = [
    0.78, 0.73, 0.70, 0.68, 0.70, 0.75,
    0.85, 0.98, 1.05, 1.08, 1.10, 1.10,
    1.08, 1.05, 1.03, 1.02, 1.05, 1.15,
    1.18, 1.12, 1.05, 0.95, 0.88, 0.82,
]

# Day-of-week demand factors (Mon=0 to Sun=6)
DOW_DEMAND_FACTOR = [1.02, 1.04, 1.04, 1.04, 1.02, 0.91, 0.89]

# Load status thresholds (MW)
LOAD_MANAGEABLE = 42000  # Below this: green
LOAD_AMBER = 47000       # Above this: amber warning
LOAD_RED = 52000         # Above this: red alert

# ── 2050 Scenario Assumptions ──
# From CCC Seventh Carbon Budget + energy system modelling

SCENARIO_2050 = {
    "annual_demand_twh": 692,
    "renewable_capacity_gw": 250,
    "solar_fraction": 0.40,
    "offshore_wind_fraction": 0.45,
    "onshore_wind_fraction": 0.15,
    "nuclear_gw": 12,
    "nuclear_cf": 0.90,
    "hydrogen_storage_twh": 50,
    "hydrogen_round_trip_eff": 0.407,
    "medium_storage_twh": 0.433,
    "medium_storage_eff": 0.70,
    "electrolyser_gw": 40,
    "electrolyser_eff": 0.74,
    "gas_ccs_gw": 18,
    "interconnect_gw": 28,
    "transmission_loss": 0.113,
    "dac_capacity_gw": 1.1,
    "dac_energy_twh_per_mt_co2": 8.8,
}

# Average UK capacity factors (from ERA5/Renewables.ninja historical)
# Monthly CF for solar, offshore wind, onshore wind (Jan-Dec)
SOLAR_CF_MONTHLY = [0.03, 0.05, 0.09, 0.13, 0.15, 0.16, 0.15, 0.13, 0.10, 0.06, 0.04, 0.02]
OFFSHORE_WIND_CF_MONTHLY = [0.45, 0.42, 0.38, 0.32, 0.28, 0.25, 0.24, 0.27, 0.33, 0.40, 0.43, 0.46]
ONSHORE_WIND_CF_MONTHLY = [0.32, 0.30, 0.27, 0.23, 0.20, 0.18, 0.17, 0.19, 0.24, 0.28, 0.30, 0.33]


# ── Data Fetching (Updated BMRS/NESO sources) ──

async def fetch_recent_demand(days: int = 7) -> list[dict] | None:
    """Fetch recent half-hourly demand from BMRS INDO dataset.

    Returns list of {timestamp, demand_mw, settlement_period} dicts.
    """
    now = datetime.now(timezone.utc)
    from_dt = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    to_dt = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/datasets/INDO"
        f"?publishDateTimeFrom={from_dt}&publishDateTimeTo={to_dt}&format=json"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("data", [])
    except Exception as e:
        log.warning("BMRS demand fetch failed: %s", e)
        return None

    if not items:
        return None

    result = []
    for item in items:
        try:
            result.append({
                "timestamp": item["startTime"],
                "demand_mw": int(item["demand"]),
                "settlement_period": item.get("settlementPeriod", 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return result


async def fetch_demand_outturn(days: int = 2) -> list[dict] | None:
    """Fetch initial national demand outturn (ITSDO) — more accurate than INDO."""
    now = datetime.now(timezone.utc)
    from_dt = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    to_dt = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/datasets/ITSDO"
        f"?publishDateTimeFrom={from_dt}&publishDateTimeTo={to_dt}&format=json"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("data", [])
    except Exception as e:
        log.warning("BMRS demand outturn fetch failed: %s", e)
        return None

    result = []
    for item in items:
        try:
            result.append({
                "timestamp": item["startTime"],
                "demand_mw": int(item["demand"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return result


# ── Demand Forecasting ──

def _demand_at_hour(base_mw: float, month: int, hour: int, dow: int) -> float:
    """Predict demand for a specific hour given base demand.

    Uses seasonal × hourly × day-of-week decomposition.
    """
    monthly = MONTHLY_DEMAND_FACTOR[month - 1]
    hourly = HOURLY_DEMAND_SHAPE[hour]
    daily = DOW_DEMAND_FACTOR[dow]
    return base_mw * monthly * hourly * daily


def _load_status(demand_mw: float) -> str:
    """Classify demand load status (GridWatch thresholds)."""
    if demand_mw >= LOAD_RED:
        return "red"
    elif demand_mw >= LOAD_AMBER:
        return "amber"
    return "manageable"


def forecast_demand_24h(recent_demand: list[dict] | None = None) -> dict:
    """Generate 24-hour demand forecast using seasonal patterns.

    If recent_demand is provided, calibrates base demand from actuals.
    Otherwise uses typical UK average (~33 GW).
    """
    now = datetime.now(timezone.utc)
    month = now.month
    dow = now.weekday()

    # Calibrate base demand from recent data
    base_mw = 33000  # UK annual average ~33 GW
    if recent_demand:
        # Use mean of last 24h of actual demand as calibration
        recent_vals = [d["demand_mw"] for d in recent_demand[-48:] if d.get("demand_mw")]
        if recent_vals:
            actual_mean = sum(recent_vals) / len(recent_vals)
            # De-seasonalize to get base
            avg_monthly = MONTHLY_DEMAND_FACTOR[month - 1]
            avg_dow = DOW_DEMAND_FACTOR[dow]
            base_mw = actual_mean / (avg_monthly * avg_dow)

    hourly = []
    for h in range(24):
        forecast_time = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if h < now.hour and recent_demand:
            # Use actual data for past hours today
            actual = None
            for d in recent_demand:
                try:
                    ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
                    if ts.hour == h and ts.date() == now.date():
                        actual = d["demand_mw"]
                except (ValueError, AttributeError):
                    pass
            if actual:
                hourly.append({
                    "hour": h,
                    "demand_mw": actual,
                    "is_actual": True,
                    "status": _load_status(actual),
                })
                continue

        predicted = round(_demand_at_hour(base_mw, month, h, dow))
        hourly.append({
            "hour": h,
            "demand_mw": predicted,
            "is_actual": False,
            "status": _load_status(predicted),
        })

    peak = max(hourly, key=lambda x: x["demand_mw"])
    trough = min(hourly, key=lambda x: x["demand_mw"])

    return {
        "date": now.strftime("%Y-%m-%d"),
        "hourly": hourly,
        "peak_mw": peak["demand_mw"],
        "peak_hour": peak["hour"],
        "trough_mw": trough["demand_mw"],
        "trough_hour": trough["hour"],
        "daily_mean_mw": round(sum(h["demand_mw"] for h in hourly) / 24),
        "status_summary": {
            "manageable": sum(1 for h in hourly if h["status"] == "manageable"),
            "amber": sum(1 for h in hourly if h["status"] == "amber"),
            "red": sum(1 for h in hourly if h["status"] == "red"),
        },
    }


def forecast_demand_7d(recent_demand: list[dict] | None = None) -> dict:
    """Generate 7-day daily demand forecast."""
    now = datetime.now(timezone.utc)

    base_mw = 33000
    if recent_demand:
        recent_vals = [d["demand_mw"] for d in recent_demand if d.get("demand_mw")]
        if recent_vals:
            actual_mean = sum(recent_vals) / len(recent_vals)
            month = now.month
            dow = now.weekday()
            base_mw = actual_mean / (MONTHLY_DEMAND_FACTOR[month - 1] * DOW_DEMAND_FACTOR[dow])

    daily = []
    for day_offset in range(7):
        dt = now + timedelta(days=day_offset)
        month = dt.month
        dow = dt.weekday()

        # Calculate daily mean and peak
        hourly_demands = [_demand_at_hour(base_mw, month, h, dow) for h in range(24)]
        daily_mean = round(sum(hourly_demands) / 24)
        daily_peak = round(max(hourly_demands))
        daily_trough = round(min(hourly_demands))

        daily.append({
            "date": dt.strftime("%Y-%m-%d"),
            "day_name": dt.strftime("%A"),
            "mean_mw": daily_mean,
            "peak_mw": daily_peak,
            "trough_mw": daily_trough,
            "status": _load_status(daily_peak),
        })

    return {
        "forecast_from": now.strftime("%Y-%m-%d"),
        "daily": daily,
        "week_mean_mw": round(sum(d["mean_mw"] for d in daily) / 7),
        "week_peak_mw": max(d["peak_mw"] for d in daily),
    }


# ── Storage Optimization (Energy Balance Simulation) ──

def simulate_storage(
    renewable_gw: float = 250,
    days: int = 365,
    demand_twh_yr: float = 692,
) -> dict:
    """Run daily energy balance simulation for storage optimization.

    Simulates a year of daily energy balancing between renewables, nuclear,
    storage (hydrogen + medium-term), and backup (gas CCS).

    Based on power_system_core.py from the UK energy modelling approach,
    simplified for real-time API use.

    Returns storage requirements, curtailment, and adequacy metrics.
    """
    s = SCENARIO_2050

    # Daily demand (TWh) — with seasonal variation
    daily_demand_base = demand_twh_yr / 365
    transmission_loss = s["transmission_loss"]

    # Renewable capacity breakdown
    solar_gw = renewable_gw * s["solar_fraction"]
    offshore_gw = renewable_gw * s["offshore_wind_fraction"]
    onshore_gw = renewable_gw * s["onshore_wind_fraction"]
    nuclear_daily_twh = s["nuclear_gw"] * s["nuclear_cf"] * 24 / 1000

    # Storage state
    h2_level = s["hydrogen_storage_twh"] * 0.5  # Start half full
    h2_max = s["hydrogen_storage_twh"]
    med_level = s["medium_storage_twh"] * 0.5
    med_max = s["medium_storage_twh"]

    electrolyser_max_daily = s["electrolyser_gw"] * s["electrolyser_eff"] * 24 / 1000  # TWh/day
    med_power_daily = 0.05 * 24 / 1000  # ~50 GW for 24h → TWh (simplified)
    gas_ccs_max_daily = s["gas_ccs_gw"] * 24 / 1000

    # Daily tracking
    daily_results = []
    h2_min = h2_max
    med_min = med_max
    total_curtailed = 0
    total_gas_ccs = 0
    total_unmet = 0
    total_renewables = 0

    for day in range(days):
        month = (day * 12 // 365) % 12  # Approximate month

        # Seasonal demand
        demand_factor = MONTHLY_DEMAND_FACTOR[month]
        daily_demand = daily_demand_base * demand_factor * (1 + transmission_loss)

        # Renewable generation (using monthly capacity factors)
        solar_gen = solar_gw * SOLAR_CF_MONTHLY[month] * 24 / 1000
        offshore_gen = offshore_gw * OFFSHORE_WIND_CF_MONTHLY[month] * 24 / 1000
        onshore_gen = onshore_gw * ONSHORE_WIND_CF_MONTHLY[month] * 24 / 1000
        total_gen = solar_gen + offshore_gen + onshore_gen + nuclear_daily_twh
        total_renewables += solar_gen + offshore_gen + onshore_gen

        net_supply = total_gen - daily_demand
        curtailed = 0
        gas_ccs_used = 0
        unmet = 0

        if net_supply >= 0:
            # Surplus: charge storage
            excess = net_supply

            # Fill medium storage first (faster response)
            med_space = med_max - med_level
            to_med = min(excess, med_space, med_power_daily)
            med_level += to_med * s["medium_storage_eff"]
            excess -= to_med

            # Electrolyse hydrogen
            to_h2 = min(excess, electrolyser_max_daily, h2_max - h2_level)
            h2_level += to_h2 * s["electrolyser_eff"]
            excess -= to_h2

            # Remaining is curtailed
            curtailed = excess
            total_curtailed += curtailed
        else:
            # Deficit: discharge storage
            deficit = abs(net_supply)

            # Medium storage first
            from_med = min(deficit, med_level * s["medium_storage_eff"], med_power_daily)
            med_level -= from_med / s["medium_storage_eff"] if s["medium_storage_eff"] > 0 else 0
            deficit -= from_med

            # Gas CCS backup
            if deficit > 0:
                from_gas = min(deficit, gas_ccs_max_daily)
                deficit -= from_gas
                gas_ccs_used = from_gas
                total_gas_ccs += from_gas

            # Hydrogen storage
            if deficit > 0:
                from_h2 = min(deficit / s["hydrogen_round_trip_eff"],
                              h2_level) if s["hydrogen_round_trip_eff"] > 0 else 0
                h2_level -= from_h2
                deficit -= from_h2 * s["hydrogen_round_trip_eff"]

            # Unmet demand
            if deficit > 0:
                unmet = deficit
                total_unmet += unmet

        h2_min = min(h2_min, h2_level)
        med_min = min(med_min, med_level)

        daily_results.append({
            "day": day,
            "month": month + 1,
            "demand_twh": round(daily_demand, 4),
            "generation_twh": round(total_gen, 4),
            "net_supply_twh": round(net_supply, 4),
            "h2_storage_twh": round(h2_level, 3),
            "med_storage_twh": round(med_level, 4),
            "curtailed_twh": round(curtailed, 4),
            "gas_ccs_twh": round(gas_ccs_used, 4),
            "unmet_twh": round(unmet, 4),
        })

    # Monthly aggregation
    monthly = []
    for m in range(12):
        m_days = [d for d in daily_results if d["month"] == m + 1]
        if not m_days:
            continue
        monthly.append({
            "month": m + 1,
            "avg_demand_twh": round(sum(d["demand_twh"] for d in m_days) / len(m_days), 4),
            "avg_generation_twh": round(sum(d["generation_twh"] for d in m_days) / len(m_days), 4),
            "avg_net_supply_twh": round(sum(d["net_supply_twh"] for d in m_days) / len(m_days), 4),
            "curtailed_twh": round(sum(d["curtailed_twh"] for d in m_days), 3),
            "gas_ccs_twh": round(sum(d["gas_ccs_twh"] for d in m_days), 3),
        })

    # System adequacy
    fail_days = sum(1 for d in daily_results if d["unmet_twh"] > 0.001)
    adequacy_pct = round((1 - fail_days / days) * 100, 2)

    return {
        "scenario": {
            "renewable_gw": renewable_gw,
            "demand_twh_yr": demand_twh_yr,
            "nuclear_gw": s["nuclear_gw"],
            "h2_storage_twh": s["hydrogen_storage_twh"],
            "gas_ccs_gw": s["gas_ccs_gw"],
        },
        "results": {
            "adequacy_pct": adequacy_pct,
            "fail_days": fail_days,
            "total_curtailed_twh": round(total_curtailed, 2),
            "total_gas_ccs_twh": round(total_gas_ccs, 2),
            "total_unmet_twh": round(total_unmet, 3),
            "total_renewables_twh": round(total_renewables, 1),
            "h2_storage_min_twh": round(h2_min, 2),
            "med_storage_min_twh": round(med_min, 4),
            "renewable_fraction_pct": round(
                total_renewables / (demand_twh_yr * (1 + transmission_loss)) * 100, 1
            ),
        },
        "monthly": monthly,
        "daily_sample": daily_results[:30],  # First 30 days for charts
    }


def optimize_storage(demand_twh_yr: float = 692) -> dict:
    """Find optimal renewable capacity and storage for 99%+ adequacy.

    Tests multiple renewable capacity scenarios and returns the optimal
    configuration with cost estimates.
    """
    # Test range of renewable capacities
    scenarios = []
    for gw in range(150, 401, 25):
        result = simulate_storage(renewable_gw=gw, demand_twh_yr=demand_twh_yr)
        cost = _estimate_system_cost(gw, result)
        scenarios.append({
            "renewable_gw": gw,
            "adequacy_pct": result["results"]["adequacy_pct"],
            "curtailed_twh": result["results"]["total_curtailed_twh"],
            "gas_ccs_twh": result["results"]["total_gas_ccs_twh"],
            "unmet_twh": result["results"]["total_unmet_twh"],
            "renewable_pct": result["results"]["renewable_fraction_pct"],
            "cost_bn_gbp_yr": cost["total_bn_yr"],
            "lcoe_gbp_mwh": cost["lcoe_gbp_mwh"],
        })

    # Find cheapest scenario with ≥99% adequacy
    adequate = [s for s in scenarios if s["adequacy_pct"] >= 99.0]
    optimal = min(adequate, key=lambda s: s["cost_bn_gbp_yr"]) if adequate else scenarios[-1]

    return {
        "optimal": optimal,
        "scenarios": scenarios,
        "assumptions": {
            "h2_storage_twh": SCENARIO_2050["hydrogen_storage_twh"],
            "nuclear_gw": SCENARIO_2050["nuclear_gw"],
            "gas_ccs_gw": SCENARIO_2050["gas_ccs_gw"],
            "demand_twh_yr": demand_twh_yr,
        },
    }


def _estimate_system_cost(renewable_gw: float, sim_result: dict) -> dict:
    """Estimate annual system cost (simplified LCOE model).

    Based on CCC/BEIS cost assumptions for 2050.
    """
    s = SCENARIO_2050
    # Annualized capital costs (GBP bn/yr) at 5% discount rate
    # Solar: ~£30/kW/yr, Offshore wind: ~£55/kW/yr, Onshore wind: ~£25/kW/yr
    solar_cost = renewable_gw * s["solar_fraction"] * 30 / 1000
    offshore_cost = renewable_gw * s["offshore_wind_fraction"] * 55 / 1000
    onshore_cost = renewable_gw * s["onshore_wind_fraction"] * 25 / 1000
    nuclear_cost = s["nuclear_gw"] * 90 / 1000  # ~£90/kW/yr
    h2_storage_cost = s["hydrogen_storage_twh"] * 0.5  # ~£0.5bn per TWh/yr
    gas_ccs_cost = s["gas_ccs_gw"] * 45 / 1000  # ~£45/kW/yr

    total = solar_cost + offshore_cost + onshore_cost + nuclear_cost + h2_storage_cost + gas_ccs_cost
    total_gen_twh = sim_result["results"]["total_renewables_twh"] + s["nuclear_gw"] * s["nuclear_cf"] * 8760 / 1000
    lcoe = round(total * 1e9 / (total_gen_twh * 1e6), 1) if total_gen_twh > 0 else 0

    return {
        "total_bn_yr": round(total, 1),
        "lcoe_gbp_mwh": lcoe,
        "breakdown": {
            "solar_bn": round(solar_cost, 2),
            "offshore_wind_bn": round(offshore_cost, 2),
            "onshore_wind_bn": round(onshore_cost, 2),
            "nuclear_bn": round(nuclear_cost, 2),
            "h2_storage_bn": round(h2_storage_cost, 2),
            "gas_ccs_bn": round(gas_ccs_cost, 2),
        },
    }


# ── Main API function ──

async def get_demand_forecast() -> dict:
    """Fetch live data and generate demand forecast + storage analysis.

    Returns complete forecast package for the frontend.
    """
    import asyncio

    # Fetch recent demand from BMRS
    demand_task = asyncio.create_task(fetch_recent_demand(days=2))
    outturn_task = asyncio.create_task(fetch_demand_outturn(days=1))

    recent = await demand_task
    outturn = await outturn_task

    # Use outturn data if available (more accurate), fall back to INDO
    demand_data = outturn or recent

    # Generate forecasts
    forecast_24h = forecast_demand_24h(demand_data)
    forecast_7d = forecast_demand_7d(demand_data)

    # Run storage optimization (precomputed, fast)
    storage = optimize_storage()

    # Current demand snapshot
    current_mw = None
    if demand_data:
        current_mw = demand_data[-1].get("demand_mw")

    return {
        "current_demand_mw": current_mw,
        "current_status": _load_status(current_mw) if current_mw else "unknown",
        "forecast_24h": forecast_24h,
        "forecast_7d": forecast_7d,
        "storage_optimization": storage,
        "thresholds": {
            "manageable_mw": LOAD_MANAGEABLE,
            "amber_mw": LOAD_AMBER,
            "red_mw": LOAD_RED,
        },
    }
