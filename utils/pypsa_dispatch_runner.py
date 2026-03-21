#!/usr/bin/env python3
"""
PyPSA-based GB dispatch model — Princeps Phase 7.
Analytical merit-order dispatch with future PyPSA LOPF upgrade path.
Runs as subprocess via JSON stdin/stdout bridge.

Commands:
  {"command": "dispatch_snapshot", "demand_gw": 32.5, "wind_cf": 0.4, "solar_cf": 0.5}
  {"command": "dispatch_forecast", "hours": 48, "start_date": "2026-03-22T00:00:00Z"}
  {"command": "zonal_prices", "zones": ["Scotland", "North", "Midlands", "South"]}
  {"command": "curtailment_forecast", "hours": 48, "wind_cf_profile": [...], "solar_cf_profile": [...]}

Analytical fallback: merit-order dispatch model with GB generation stack.
When PyPSA conda env is available, switch USE_PYPSA = True for full LOPF.
"""

import json
import math
import sys
import traceback
from datetime import datetime, timedelta, timezone

# ─── Configuration ─────────────────────────────────────────────────────────

USE_PYPSA = False  # Set True when conda env with pypsa is ready

# GB generation fleet (2026 baseline)
GB_FLEET = [
    {"type": "nuclear",  "capacity_gw": 5.9,  "srmc": 10,  "carbon_tco2_mwh": 0.0,   "variable": False, "min_output_pct": 0.90},
    {"type": "wind",     "capacity_gw": 30.0,  "srmc": 0,   "carbon_tco2_mwh": 0.0,   "variable": True},
    {"type": "solar",    "capacity_gw": 16.0,  "srmc": 0,   "carbon_tco2_mwh": 0.0,   "variable": True},
    {"type": "biomass",  "capacity_gw": 3.5,   "srmc": 50,  "carbon_tco2_mwh": 0.12,  "variable": False, "min_output_pct": 0.40},
    {"type": "imports",  "capacity_gw": 8.4,   "srmc": 55,  "carbon_tco2_mwh": 0.15,  "variable": False, "min_output_pct": 0.0},
    {"type": "ccgt",     "capacity_gw": 33.0,  "srmc": 70,  "carbon_tco2_mwh": 0.34,  "variable": False, "min_output_pct": 0.0},
    {"type": "battery",  "capacity_gw": 4.0,   "srmc": 80,  "carbon_tco2_mwh": 0.0,   "variable": False, "min_output_pct": 0.0},
    {"type": "ocgt",     "capacity_gw": 2.0,   "srmc": 120, "carbon_tco2_mwh": 0.50,  "variable": False, "min_output_pct": 0.0},
]

# UK carbon price (ETS, GBP/tCO2)
CARBON_PRICE_GBP = 50.0

# Gas price sensitivity on CCGT SRMC (base £70, range £65-85)
GAS_PRICE_BASE_PENCE_THERM = 80  # p/therm

# Regional wholesale price adjustments (relative to system price)
ZONAL_ADJUSTMENTS = {
    "Scotland":  -8.0,   # Excess wind, export constrained
    "North":     -3.0,   # Wind-heavy, some constraint
    "Midlands":   0.0,   # Reference zone
    "South":     +4.0,   # Demand centre, import-dependent
    "Wales":     -2.0,   # Wind + nuclear
    "East":      +2.0,   # Solar-heavy, demand centre
}

# Typical GB annual capacity factors by technology
ANNUAL_CF = {
    "wind":  0.33,
    "solar": 0.11,
}


# ─── Demand Profile Model ─────────────────────────────────────────────────

def _gb_demand_gw(ts: datetime) -> float:
    """
    Analytical GB demand profile.
    UK peaks ~35 GW winter evening, troughs ~18 GW summer overnight.
    """
    hour = ts.hour + ts.minute / 60.0
    day_of_year = ts.timetuple().tm_yday

    # Seasonal: winter higher, summer lower
    seasonal = 1.0 + 0.20 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

    # Diurnal: morning ramp, evening peak, overnight trough
    morning = math.exp(-0.5 * ((hour - 8.5) / 2.0) ** 2) * 0.85
    evening = math.exp(-0.5 * ((hour - 17.5) / 2.5) ** 2) * 1.0
    overnight = 0.55 + 0.10 * math.cos(2 * math.pi * (hour - 3) / 24)
    diurnal = max(overnight, morning, evening)

    # Weekday/weekend factor
    weekday_factor = 1.0 if ts.weekday() < 5 else 0.90

    base_gw = 26.5  # Annual average GB demand
    return base_gw * diurnal * seasonal * weekday_factor


def _wind_capacity_factor(ts: datetime, base_cf: float = None) -> float:
    """
    Wind capacity factor with diurnal and seasonal variation.
    Wind is higher at night, higher in winter.
    """
    hour = ts.hour + ts.minute / 60.0
    day_of_year = ts.timetuple().tm_yday

    if base_cf is not None:
        return max(0.0, min(1.0, base_cf))

    # Seasonal: winter windier
    seasonal = 1.0 + 0.35 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

    # Diurnal: slightly windier at night
    diurnal = 1.0 + 0.08 * math.cos(2 * math.pi * (hour - 3) / 24)

    # Random-ish variability via day hash
    variability = 0.85 + 0.30 * math.sin(day_of_year * 2.3 + hour * 0.7)

    cf = ANNUAL_CF["wind"] * seasonal * diurnal * variability
    return max(0.02, min(0.95, cf))


def _solar_capacity_factor(ts: datetime, base_cf: float = None) -> float:
    """
    Solar capacity factor — zero at night, bell curve during day.
    Higher in summer, lower in winter. UK latitude ~52N.
    """
    hour = ts.hour + ts.minute / 60.0
    day_of_year = ts.timetuple().tm_yday

    if base_cf is not None:
        return max(0.0, min(1.0, base_cf))

    # Sunrise/sunset approximation for UK (52N)
    day_length = 12 + 4.5 * math.sin(2 * math.pi * (day_of_year - 80) / 365)
    sunrise = 12 - day_length / 2
    sunset = 12 + day_length / 2

    if hour < sunrise or hour > sunset:
        return 0.0

    # Solar elevation proxy (bell curve centred at noon)
    solar_angle = math.sin(math.pi * (hour - sunrise) / (sunset - sunrise))
    solar_angle = max(0, solar_angle)

    # Seasonal peak irradiance
    seasonal_peak = 0.55 + 0.45 * math.sin(2 * math.pi * (day_of_year - 80) / 365)
    seasonal_peak = max(0.1, seasonal_peak)

    # Cloud cover proxy (varies by day)
    clearness = 0.45 + 0.25 * math.sin(day_of_year * 1.7 + 0.3)
    clearness = max(0.2, min(0.8, clearness))

    cf = solar_angle * seasonal_peak * clearness
    return max(0.0, min(0.85, cf))


# ─── Merit Order Dispatch ──────────────────────────────────────────────────

def _dispatch_merit_order(
    demand_gw: float,
    wind_cf: float,
    solar_cf: float,
    gas_price_pence_therm: float = None,
    carbon_price_gbp: float = None,
) -> dict:
    """
    Dispatch GB fleet in merit order (cheapest first) to meet demand.
    Returns generation by type, system marginal price, carbon intensity, curtailment.
    """
    gas_price = gas_price_pence_therm or GAS_PRICE_BASE_PENCE_THERM
    carbon = carbon_price_gbp or CARBON_PRICE_GBP

    # Adjust CCGT/OCGT SRMC based on gas price
    # Base: 80p/therm => £70/MWh SRMC. Scale linearly.
    gas_factor = gas_price / GAS_PRICE_BASE_PENCE_THERM

    generation = {}
    remaining = demand_gw
    total_carbon = 0.0
    marginal_price = 0.0
    marginal_gen = None
    total_generation = 0.0

    # Build dispatch stack: variable renewables first, then merit order
    dispatch_order = []
    for gen in GB_FLEET:
        g = dict(gen)
        if g["type"] == "wind":
            g["available_gw"] = g["capacity_gw"] * wind_cf
        elif g["type"] == "solar":
            g["available_gw"] = g["capacity_gw"] * solar_cf
        else:
            g["available_gw"] = g["capacity_gw"]

        # Adjust gas-fired SRMC
        if g["type"] in ("ccgt", "ocgt"):
            g["effective_srmc"] = g["srmc"] * gas_factor + g["carbon_tco2_mwh"] * carbon
        else:
            g["effective_srmc"] = g["srmc"] + g["carbon_tco2_mwh"] * carbon

        dispatch_order.append(g)

    # Sort by effective SRMC (cheapest first)
    dispatch_order.sort(key=lambda x: x["effective_srmc"])

    # Nuclear must-run: always outputs at least min_output_pct
    for g in dispatch_order:
        gen_type = g["type"]
        if remaining <= 0:
            # Still need to account for must-run nuclear
            min_out = g.get("min_output_pct", 0.0) * g["capacity_gw"]
            if gen_type == "nuclear" and min_out > 0:
                output = min_out
                generation[gen_type] = round(output, 2)
                total_generation += output
                total_carbon += output * g["carbon_tco2_mwh"] * 1000  # GW * tCO2/MWh * 1000 MW/GW
            else:
                generation[gen_type] = 0.0
            continue

        available = g["available_gw"]
        min_out = g.get("min_output_pct", 0.0) * g["capacity_gw"]

        if gen_type in ("wind", "solar"):
            # Variable: dispatch what's available
            output = min(available, remaining)
        else:
            output = min(available, remaining)
            output = max(output, min(min_out, remaining))  # Respect minimum output

        generation[gen_type] = round(output, 2)
        total_generation += output
        total_carbon += output * g["carbon_tco2_mwh"] * 1000  # Convert to tCO2 (GW->MW factor)
        remaining -= output

        if output > 0:
            marginal_price = g["effective_srmc"]
            marginal_gen = gen_type

    # Curtailment: if total variable generation exceeds demand (surplus)
    total_variable = 0.0
    for g in dispatch_order:
        if g.get("variable"):
            total_variable += g["available_gw"]

    curtailment_gw = max(0, total_generation - demand_gw)
    if curtailment_gw > 0:
        # Price drops to zero or negative during curtailment
        marginal_price = max(0, marginal_price - curtailment_gw * 15)  # Price depression

    # Unserved energy (demand not met)
    unserved_gw = max(0, remaining)
    if unserved_gw > 0:
        marginal_price = 6000  # VoLL (Value of Lost Load, GBP/MWh)
        marginal_gen = "unserved"

    # Carbon intensity in gCO2/kWh
    if total_generation > 0:
        carbon_intensity = (total_carbon / total_generation)  # tCO2/GW = gCO2/kWh (numerically equivalent)
    else:
        carbon_intensity = 0

    # Renewable percentage
    renewable_gw = generation.get("wind", 0) + generation.get("solar", 0)
    low_carbon_gw = renewable_gw + generation.get("nuclear", 0)
    renewable_pct = (renewable_gw / demand_gw * 100) if demand_gw > 0 else 0
    low_carbon_pct = (low_carbon_gw / demand_gw * 100) if demand_gw > 0 else 0

    # Constraint costs (simplified: curtailment * average constraint payment)
    constraint_cost_gbp_h = curtailment_gw * 1000 * 50  # GW -> MW * £50/MWh typical constraint payment

    return {
        "demand_gw": round(demand_gw, 2),
        "generation": generation,
        "total_generation_gw": round(total_generation, 2),
        "system_marginal_price_gbp_mwh": round(marginal_price, 1),
        "carbon_intensity_gco2_kwh": round(carbon_intensity, 1),
        "curtailment_gw": round(curtailment_gw, 2),
        "unserved_gw": round(unserved_gw, 2),
        "renewable_pct": round(renewable_pct, 1),
        "low_carbon_pct": round(low_carbon_pct, 1),
        "marginal_generator": marginal_gen,
        "constraint_cost_gbp_h": round(constraint_cost_gbp_h, 0),
    }


# ─── Command: dispatch_snapshot ────────────────────────────────────────────

def dispatch_snapshot(
    demand_gw: float = None,
    wind_cf: float = None,
    solar_cf: float = None,
    timestamp: str = None,
    gas_price_pence_therm: float = None,
    carbon_price_gbp: float = None,
) -> dict:
    """
    Current GB dispatch state — single timestamp snapshot.
    Uses BMRS live data if available, else analytical profiles.
    """
    if timestamp:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    else:
        ts = datetime.now(timezone.utc)

    # Use provided values or analytical profiles
    if demand_gw is None:
        demand_gw = _gb_demand_gw(ts)
    if wind_cf is None:
        wind_cf = _wind_capacity_factor(ts)
    if solar_cf is None:
        solar_cf = _solar_capacity_factor(ts)

    result = _dispatch_merit_order(
        demand_gw=demand_gw,
        wind_cf=wind_cf,
        solar_cf=solar_cf,
        gas_price_pence_therm=gas_price_pence_therm,
        carbon_price_gbp=carbon_price_gbp,
    )

    result["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    result["model"] = "analytical_merit_order"
    result["data_source"] = "analytical"  # Will be "bmrs_live" when connected

    return result


# ─── Command: dispatch_forecast ────────────────────────────────────────────

def dispatch_forecast(
    hours: int = 48,
    start_date: str = None,
    gas_price_pence_therm: float = None,
    carbon_price_gbp: float = None,
    wind_cf_profile: list = None,
    solar_cf_profile: list = None,
) -> dict:
    """
    Hourly dispatch forecast for N hours ahead.
    Returns hourly SMP, carbon intensity, curtailment, generation mix.
    """
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    hourly = []
    summary = {
        "total_demand_gwh": 0,
        "total_renewable_gwh": 0,
        "total_curtailment_gwh": 0,
        "avg_smp_gbp_mwh": 0,
        "avg_carbon_gco2_kwh": 0,
        "peak_demand_gw": 0,
        "min_demand_gw": 999,
        "max_smp_gbp_mwh": 0,
        "min_smp_gbp_mwh": 999,
        "total_constraint_cost_gbp": 0,
    }

    for h in range(hours):
        ts = start + timedelta(hours=h)

        # Use profile arrays if provided, else analytical
        w_cf = wind_cf_profile[h] if wind_cf_profile and h < len(wind_cf_profile) else None
        s_cf = solar_cf_profile[h] if solar_cf_profile and h < len(solar_cf_profile) else None

        demand = _gb_demand_gw(ts)
        wind_cf_val = _wind_capacity_factor(ts, w_cf)
        solar_cf_val = _solar_capacity_factor(ts, s_cf)

        snap = _dispatch_merit_order(
            demand_gw=demand,
            wind_cf=wind_cf_val,
            solar_cf=solar_cf_val,
            gas_price_pence_therm=gas_price_pence_therm,
            carbon_price_gbp=carbon_price_gbp,
        )
        snap["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        snap["hour"] = h

        hourly.append(snap)

        # Aggregate summaries
        summary["total_demand_gwh"] += demand
        ren = snap["generation"].get("wind", 0) + snap["generation"].get("solar", 0)
        summary["total_renewable_gwh"] += ren
        summary["total_curtailment_gwh"] += snap["curtailment_gw"]
        summary["avg_smp_gbp_mwh"] += snap["system_marginal_price_gbp_mwh"]
        summary["avg_carbon_gco2_kwh"] += snap["carbon_intensity_gco2_kwh"]
        summary["peak_demand_gw"] = max(summary["peak_demand_gw"], demand)
        summary["min_demand_gw"] = min(summary["min_demand_gw"], demand)
        summary["max_smp_gbp_mwh"] = max(summary["max_smp_gbp_mwh"], snap["system_marginal_price_gbp_mwh"])
        summary["min_smp_gbp_mwh"] = min(summary["min_smp_gbp_mwh"], snap["system_marginal_price_gbp_mwh"])
        summary["total_constraint_cost_gbp"] += snap["constraint_cost_gbp_h"]

    # Finalise averages
    if hours > 0:
        summary["avg_smp_gbp_mwh"] = round(summary["avg_smp_gbp_mwh"] / hours, 1)
        summary["avg_carbon_gco2_kwh"] = round(summary["avg_carbon_gco2_kwh"] / hours, 1)

    for k in ("total_demand_gwh", "total_renewable_gwh", "total_curtailment_gwh",
              "peak_demand_gw", "min_demand_gw", "max_smp_gbp_mwh", "min_smp_gbp_mwh"):
        summary[k] = round(summary[k], 2)
    summary["total_constraint_cost_gbp"] = round(summary["total_constraint_cost_gbp"], 0)
    summary["renewable_share_pct"] = round(
        summary["total_renewable_gwh"] / summary["total_demand_gwh"] * 100, 1
    ) if summary["total_demand_gwh"] > 0 else 0

    return {
        "model": "analytical_merit_order",
        "hours": hours,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": (start + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
        "hourly": hourly,
    }


# ─── Command: zonal_prices ────────────────────────────────────────────────

def zonal_prices(
    zones: list = None,
    hours: int = 48,
    start_date: str = None,
    gas_price_pence_therm: float = None,
    carbon_price_gbp: float = None,
) -> dict:
    """
    Zonal wholesale price forecast for GB regions.
    Applies locational adjustments to system marginal price.
    """
    if zones is None:
        zones = list(ZONAL_ADJUSTMENTS.keys())

    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Get system-level dispatch forecast
    forecast = dispatch_forecast(
        hours=hours,
        start_date=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        gas_price_pence_therm=gas_price_pence_therm,
        carbon_price_gbp=carbon_price_gbp,
    )

    zone_results = {}
    for zone in zones:
        adj = ZONAL_ADJUSTMENTS.get(zone, 0.0)
        zone_hourly = []
        avg_price = 0.0

        for snap in forecast["hourly"]:
            smp = snap["system_marginal_price_gbp_mwh"]

            # Zonal adjustment varies with renewable penetration
            # More wind => Scotland cheaper, South dearer
            ren_pct = snap["renewable_pct"]
            dynamic_adj = adj * (1 + (ren_pct - 30) / 100)  # Amplify when renewables high

            zonal_price = max(0, smp + dynamic_adj)

            zone_hourly.append({
                "timestamp": snap["timestamp"],
                "system_price_gbp_mwh": round(smp, 1),
                "zonal_price_gbp_mwh": round(zonal_price, 1),
                "adjustment_gbp_mwh": round(dynamic_adj, 1),
            })
            avg_price += zonal_price

        avg_price = round(avg_price / hours, 1) if hours > 0 else 0

        zone_results[zone] = {
            "zone": zone,
            "avg_price_gbp_mwh": avg_price,
            "base_adjustment_gbp_mwh": adj,
            "hourly": zone_hourly,
        }

    return {
        "model": "analytical_zonal",
        "zones": zones,
        "hours": hours,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "system_summary": forecast["summary"],
        "zonal": zone_results,
    }


# ─── Command: curtailment_forecast ─────────────────────────────────────────

def curtailment_forecast(
    hours: int = 48,
    start_date: str = None,
    technology: str = "solar",
    capacity_mw: float = 50,
    region: str = "Midlands",
    connection_type: str = "firm",
) -> dict:
    """
    Curtailment forecast for a specific site/technology.
    Estimates periods when the site would be curtailed and revenue impact.
    """
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Get system dispatch
    forecast = dispatch_forecast(
        hours=hours,
        start_date=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Regional curtailment factor (Scotland highest, South lowest)
    region_curtailment_factor = {
        "Scotland": 2.5,
        "North": 1.5,
        "Wales": 1.3,
        "Midlands": 1.0,
        "East": 0.8,
        "South": 0.5,
    }.get(region, 1.0)

    # ANM/flexible connections have higher curtailment
    conn_curtailment_factor = {
        "firm": 0.3,
        "non_firm": 1.5,
        "anm": 2.0,
        "flexible": 1.8,
    }.get(connection_type, 1.0)

    hourly = []
    total_potential_mwh = 0
    total_curtailed_mwh = 0
    total_revenue_loss_gbp = 0

    for snap in forecast["hourly"]:
        ts = datetime.fromisoformat(snap["timestamp"].replace("Z", "+00:00"))
        hour = ts.hour + ts.minute / 60.0
        day_of_year = ts.timetuple().tm_yday

        # Site generation profile
        if technology == "solar":
            site_cf = _solar_capacity_factor(ts)
        elif technology == "wind":
            site_cf = _wind_capacity_factor(ts)
        else:
            site_cf = 0.5  # Baseload

        potential_mw = capacity_mw * site_cf
        total_potential_mwh += potential_mw

        # System curtailment risk: based on system surplus + regional factor
        system_curtailment = snap["curtailment_gw"]
        ren_pct = snap["renewable_pct"]

        # Higher curtailment risk when:
        # 1. System is curtailing
        # 2. Renewable % is very high (>60%)
        # 3. Demand is low
        base_curtailment_pct = 0
        if system_curtailment > 0:
            base_curtailment_pct = min(50, system_curtailment / 5 * 100)
        elif ren_pct > 70:
            base_curtailment_pct = (ren_pct - 70) * 1.5
        elif ren_pct > 55:
            base_curtailment_pct = (ren_pct - 55) * 0.5

        site_curtailment_pct = min(100, base_curtailment_pct * region_curtailment_factor * conn_curtailment_factor)
        curtailed_mw = potential_mw * site_curtailment_pct / 100
        actual_mw = potential_mw - curtailed_mw

        total_curtailed_mwh += curtailed_mw

        # Revenue impact
        zonal_adj = ZONAL_ADJUSTMENTS.get(region, 0)
        price = max(0, snap["system_marginal_price_gbp_mwh"] + zonal_adj)
        revenue_loss = curtailed_mw * price / 1000  # MWh * GBP/MWh / 1000 for hourly

        # Actually price is per MWh and we have MW for 1 hour = MWh
        revenue_loss = curtailed_mw * price
        total_revenue_loss_gbp += revenue_loss

        hourly.append({
            "timestamp": snap["timestamp"],
            "potential_mw": round(potential_mw, 1),
            "actual_mw": round(actual_mw, 1),
            "curtailed_mw": round(curtailed_mw, 1),
            "curtailment_pct": round(site_curtailment_pct, 1),
            "wholesale_price_gbp_mwh": round(price, 1),
            "revenue_loss_gbp": round(revenue_loss, 0),
            "system_renewable_pct": snap["renewable_pct"],
        })

    # Summary
    curtailment_rate = (total_curtailed_mwh / total_potential_mwh * 100) if total_potential_mwh > 0 else 0
    avg_cf = total_potential_mwh / (capacity_mw * hours) if hours > 0 else 0
    effective_cf = (total_potential_mwh - total_curtailed_mwh) / (capacity_mw * hours) if hours > 0 else 0

    # Annualised estimates
    hours_in_year = 8760
    scale = hours_in_year / hours if hours > 0 else 1
    annual_generation_mwh = (total_potential_mwh - total_curtailed_mwh) * scale
    annual_curtailed_mwh = total_curtailed_mwh * scale
    annual_revenue_loss_gbp = total_revenue_loss_gbp * scale

    return {
        "model": "analytical_curtailment",
        "technology": technology,
        "capacity_mw": capacity_mw,
        "region": region,
        "connection_type": connection_type,
        "hours": hours,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_potential_mwh": round(total_potential_mwh, 1),
            "total_curtailed_mwh": round(total_curtailed_mwh, 1),
            "curtailment_rate_pct": round(curtailment_rate, 1),
            "total_revenue_loss_gbp": round(total_revenue_loss_gbp, 0),
            "avg_capacity_factor": round(avg_cf, 3),
            "effective_capacity_factor": round(effective_cf, 3),
            "annual_generation_mwh": round(annual_generation_mwh, 0),
            "annual_curtailed_mwh": round(annual_curtailed_mwh, 0),
            "annual_revenue_loss_gbp": round(annual_revenue_loss_gbp, 0),
        },
        "hourly": hourly,
    }


# ─── Site Impact Assessment ───────────────────────────────────────────────

def site_impact(
    lat: float,
    lon: float,
    capacity_mw: float = 50,
    technology: str = "solar",
    region: str = None,
) -> dict:
    """
    Assess how connecting a new generation site affects local wholesale price
    and curtailment exposure.
    """
    # Infer region from latitude if not provided
    if region is None:
        if lat > 55.5:
            region = "Scotland"
        elif lat > 53.5:
            region = "North"
        elif lat > 52:
            region = "Midlands"
        elif lon < -3:
            region = "Wales"
        elif lon > 0.5:
            region = "East"
        else:
            region = "South"

    # Get baseline system dispatch
    baseline = dispatch_forecast(hours=24)

    # Estimate site annual generation
    cf = ANNUAL_CF.get(technology, 0.11)
    annual_mwh = capacity_mw * cf * 8760

    # Curtailment exposure
    curt = curtailment_forecast(
        hours=24,
        technology=technology,
        capacity_mw=capacity_mw,
        region=region,
        connection_type="firm",
    )

    # Price impact (merit order effect): adding generation depresses prices
    # Rough rule: 1 GW of zero-marginal-cost gen depresses SMP by ~£3-5/MWh
    price_depression_gbp_mwh = (capacity_mw / 1000) * 4.0 * cf  # Small for typical sites

    # Zonal price
    zonal_adj = ZONAL_ADJUSTMENTS.get(region, 0)
    avg_system_price = baseline["summary"]["avg_smp_gbp_mwh"]
    avg_zonal_price = avg_system_price + zonal_adj

    # Revenue estimate (pre-curtailment)
    gross_revenue_pa = annual_mwh * avg_zonal_price
    net_revenue_pa = gross_revenue_pa * (1 - curt["summary"]["curtailment_rate_pct"] / 100)

    return {
        "model": "analytical_site_impact",
        "site": {"lat": lat, "lon": lon, "region": region},
        "technology": technology,
        "capacity_mw": capacity_mw,
        "annual_capacity_factor": round(cf, 3),
        "annual_generation_mwh": round(annual_mwh, 0),
        "wholesale_price": {
            "system_avg_gbp_mwh": round(avg_system_price, 1),
            "zonal_avg_gbp_mwh": round(avg_zonal_price, 1),
            "price_depression_gbp_mwh": round(price_depression_gbp_mwh, 2),
            "effective_capture_price_gbp_mwh": round(avg_zonal_price - price_depression_gbp_mwh, 1),
        },
        "curtailment": {
            "rate_pct": curt["summary"]["curtailment_rate_pct"],
            "annual_mwh_lost": curt["summary"]["annual_curtailed_mwh"],
            "annual_revenue_loss_gbp": curt["summary"]["annual_revenue_loss_gbp"],
        },
        "revenue_estimate": {
            "gross_annual_gbp": round(gross_revenue_pa, 0),
            "net_annual_gbp": round(net_revenue_pa, 0),
            "net_gbp_per_mw": round(net_revenue_pa / capacity_mw, 0) if capacity_mw > 0 else 0,
        },
    }


# ─── Revenue Forecast ─────────────────────────────────────────────────────

def revenue_forecast(
    capacity_mw: float = 50,
    technology: str = "solar",
    region: str = "Midlands",
    ppa_price_gbp_mwh: float = None,
    years: int = 25,
    degradation_pct_pa: float = 0.5,
) -> dict:
    """
    Projected annual revenue from wholesale + BM based on dispatch forecast.
    Includes degradation, price escalation scenarios, and BM revenue.
    """
    cf = ANNUAL_CF.get(technology, 0.11)
    zonal_adj = ZONAL_ADJUSTMENTS.get(region, 0)

    # Get current system price from 48h dispatch
    forecast_48h = dispatch_forecast(hours=48)
    base_wholesale_price = forecast_48h["summary"]["avg_smp_gbp_mwh"] + zonal_adj

    # Curtailment rate
    curt = curtailment_forecast(
        hours=48, technology=technology, capacity_mw=capacity_mw,
        region=region, connection_type="firm",
    )
    curtailment_rate = curt["summary"]["curtailment_rate_pct"] / 100

    # BM revenue estimate (technology-dependent)
    bm_revenue_gbp_per_mw = {
        "wind": 8000,   # £8k/MW/yr typical BM revenue for wind
        "solar": 3000,  # £3k/MW/yr for solar (less BM flexibility)
        "battery": 25000,  # £25k/MW/yr for BESS
    }.get(technology, 5000)

    # Price escalation scenarios
    price_scenarios = {
        "low":    {"escalation": 0.01, "label": "Low (1% p.a.)"},
        "central": {"escalation": 0.025, "label": "Central (2.5% p.a.)"},
        "high":   {"escalation": 0.04, "label": "High (4% p.a.)"},
    }

    annual_projections = {}
    for scenario_name, sc in price_scenarios.items():
        years_data = []
        cumulative_revenue = 0

        for yr in range(1, years + 1):
            # Degradation
            eff_cf = cf * (1 - degradation_pct_pa / 100) ** yr

            # Generation
            annual_mwh = capacity_mw * eff_cf * 8760 * (1 - curtailment_rate)

            # Wholesale price
            wp = base_wholesale_price * (1 + sc["escalation"]) ** yr

            # Revenue streams
            if ppa_price_gbp_mwh and ppa_price_gbp_mwh > 0:
                wholesale_rev = annual_mwh * ppa_price_gbp_mwh
            else:
                wholesale_rev = annual_mwh * wp

            bm_rev = bm_revenue_gbp_per_mw * capacity_mw * (1 - degradation_pct_pa / 100) ** yr

            # ROC/CfD revenue (simplified)
            subsidy_rev = 0  # Assume merchant for now

            total_rev = wholesale_rev + bm_rev + subsidy_rev
            cumulative_revenue += total_rev

            years_data.append({
                "year": yr,
                "capacity_factor": round(eff_cf, 3),
                "generation_mwh": round(annual_mwh, 0),
                "wholesale_price_gbp_mwh": round(wp, 1),
                "wholesale_revenue_gbp": round(wholesale_rev, 0),
                "bm_revenue_gbp": round(bm_rev, 0),
                "total_revenue_gbp": round(total_rev, 0),
                "cumulative_revenue_gbp": round(cumulative_revenue, 0),
            })

        annual_projections[scenario_name] = {
            "label": sc["label"],
            "annual": years_data,
            "total_revenue_gbp": round(cumulative_revenue, 0),
            "avg_annual_revenue_gbp": round(cumulative_revenue / years, 0),
        }

    # NPV calculation (central scenario, 8% discount rate)
    discount_rate = 0.08
    central_npv = 0
    for yr_data in annual_projections["central"]["annual"]:
        central_npv += yr_data["total_revenue_gbp"] / (1 + discount_rate) ** yr_data["year"]

    return {
        "model": "analytical_revenue",
        "technology": technology,
        "capacity_mw": capacity_mw,
        "region": region,
        "base_capacity_factor": round(cf, 3),
        "curtailment_rate_pct": round(curtailment_rate * 100, 1),
        "base_wholesale_price_gbp_mwh": round(base_wholesale_price, 1),
        "bm_revenue_gbp_per_mw_pa": bm_revenue_gbp_per_mw,
        "ppa_price_gbp_mwh": ppa_price_gbp_mwh,
        "project_life_years": years,
        "degradation_pct_pa": degradation_pct_pa,
        "npv_central_gbp": round(central_npv, 0),
        "scenarios": annual_projections,
    }


# ─── BMRS Live Data (future integration) ──────────────────────────────────

def _fetch_bmrs_demand() -> float | None:
    """
    Fetch current GB demand from BMRS API.
    Returns demand in GW or None if unavailable.
    """
    try:
        import httpx
        resp = httpx.get(
            "https://data.elexon.co.uk/bmrs/api/v1/datasets/INDO",
            params={"format": "json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data"):
                latest = data["data"][0]
                return latest.get("demand", 0) / 1000  # MW -> GW
    except Exception:
        pass
    return None


def _fetch_bmrs_generation_mix() -> dict | None:
    """
    Fetch current GB generation mix from BMRS API.
    Returns dict of fuel type -> GW or None if unavailable.
    """
    try:
        import httpx
        resp = httpx.get(
            "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINSTHHCUR",
            params={"format": "json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            mix = {}
            for rec in data.get("data", []):
                fuel = rec.get("fuelType", "").lower()
                gen = rec.get("currentUsagePerFuelType", 0) / 1000  # MW -> GW
                mix[fuel] = gen
            return mix if mix else None
    except Exception:
        pass
    return None


# ─── Subprocess bridge ─────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "dispatch_snapshot":
            result = dispatch_snapshot(
                demand_gw=req.get("demand_gw"),
                wind_cf=req.get("wind_cf"),
                solar_cf=req.get("solar_cf"),
                timestamp=req.get("timestamp"),
                gas_price_pence_therm=req.get("gas_price_pence_therm"),
                carbon_price_gbp=req.get("carbon_price_gbp"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "dispatch_forecast":
            result = dispatch_forecast(
                hours=req.get("hours", 48),
                start_date=req.get("start_date"),
                gas_price_pence_therm=req.get("gas_price_pence_therm"),
                carbon_price_gbp=req.get("carbon_price_gbp"),
                wind_cf_profile=req.get("wind_cf_profile"),
                solar_cf_profile=req.get("solar_cf_profile"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "zonal_prices":
            result = zonal_prices(
                zones=req.get("zones"),
                hours=req.get("hours", 48),
                start_date=req.get("start_date"),
                gas_price_pence_therm=req.get("gas_price_pence_therm"),
                carbon_price_gbp=req.get("carbon_price_gbp"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "curtailment_forecast":
            result = curtailment_forecast(
                hours=req.get("hours", 48),
                start_date=req.get("start_date"),
                technology=req.get("technology", "solar"),
                capacity_mw=req.get("capacity_mw", 50),
                region=req.get("region", "Midlands"),
                connection_type=req.get("connection_type", "firm"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "site_impact":
            result = site_impact(
                lat=req.get("lat", 52.5),
                lon=req.get("lon", -1.5),
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "revenue_forecast":
            result = revenue_forecast(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region", "Midlands"),
                ppa_price_gbp_mwh=req.get("ppa_price_gbp_mwh"),
                years=req.get("years", 25),
                degradation_pct_pa=req.get("degradation_pct_pa", 0.5),
            )
            json.dump(result, sys.stdout)

        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)

    except Exception as e:
        json.dump({"error": str(e), "traceback": traceback.format_exc()}, sys.stdout)


if __name__ == "__main__":
    main()
