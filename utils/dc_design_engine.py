"""
DC Design Engine — Comprehensive Data Centre Design, CFE Profiling & Financial Modelling

Provides:
  - Hourly 24/7 Carbon-Free Energy (CFE%) profiling with Carbon Intensity API
  - ASHRAE TC 9.9 compliance checking (Recommended, A1-A4)
  - Uptime Institute Tier classification from design parameters
  - Power density design (rack layout, cooling, UPS, generators, transformers)
  - Power chain topology generation (HV → rack level)
  - Construction timeline / Gantt generation
  - DC-specific financial model (CAPEX/OPEX/IRR/NPV/payback)
  - Water stress assessment with WUE calculation

Engineering formulas from industry research:
  - Total Power = IT Load x PUE
  - Heat (BTU/hr) = IT Load (W) x 3.412
  - Tons of Cooling = BTU/hr / 12,000
  - Rule of thumb: 1 ton per 3.5 kW
  - UPS Heat = 0.04 x Power System Rating + 0.05 x IT Load
  - PDU Heat = 0.01 x Power System Rating + 0.02 x IT Load
  - Lighting = 21.53 W/m²
"""

from __future__ import annotations

import math
import logging
from typing import Any

import httpx

log = logging.getLogger("princeps.dc_design")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CI_API_BASE = "https://api.carbonintensity.org.uk"
HTTP_TIMEOUT = 15.0

# Carbon Intensity API region centroids (IDs 1-14 are DNO regions)
CI_REGIONS: dict[int, dict[str, Any]] = {
    1: {"name": "North Scotland", "lat": 57.5, "lon": -4.5},
    2: {"name": "South Scotland", "lat": 55.9, "lon": -3.2},
    3: {"name": "North West England", "lat": 53.8, "lon": -2.7},
    4: {"name": "North East England", "lat": 55.0, "lon": -1.5},
    5: {"name": "Yorkshire", "lat": 53.8, "lon": -1.5},
    6: {"name": "North Wales & Merseyside", "lat": 53.2, "lon": -3.0},
    7: {"name": "South Wales", "lat": 51.7, "lon": -3.4},
    8: {"name": "West Midlands", "lat": 52.5, "lon": -2.0},
    9: {"name": "East Midlands", "lat": 52.8, "lon": -1.0},
    10: {"name": "East England", "lat": 52.2, "lon": 0.5},
    11: {"name": "South West England", "lat": 50.8, "lon": -3.5},
    12: {"name": "South England", "lat": 51.0, "lon": -1.0},
    13: {"name": "London", "lat": 51.5, "lon": -0.1},
    14: {"name": "South East England", "lat": 51.2, "lon": 0.5},
}

# Fallback average carbon intensity by region (gCO2/kWh), historic 2022-2024
REGIONAL_AVG_INTENSITY: dict[int, float] = {
    1: 45, 2: 55, 3: 170, 4: 130, 5: 155, 6: 175, 7: 160,
    8: 180, 9: 165, 10: 150, 11: 140, 12: 155, 13: 190, 14: 160,
}

# ASHRAE TC 9.9 thermal envelopes
ASHRAE_ENVELOPES: dict[str, dict[str, Any]] = {
    "Recommended": {
        "temp_min_c": 18.0, "temp_max_c": 27.0,
        "dp_min_c": -9.0, "dp_max_c": 15.0,
        "max_rh_pct": 60.0,
        "description": "Recommended operating envelope for all IT equipment",
    },
    "A1": {
        "temp_min_c": 15.0, "temp_max_c": 32.0,
        "dp_min_c": -12.0, "dp_max_c": 17.0,
        "max_rh_pct": 80.0,
        "description": "Enterprise servers, storage, and networking",
    },
    "A2": {
        "temp_min_c": 10.0, "temp_max_c": 35.0,
        "dp_min_c": -12.0, "dp_max_c": 21.0,
        "max_rh_pct": 80.0,
        "description": "Volume servers, storage, personal computers",
    },
    "A3": {
        "temp_min_c": 5.0, "temp_max_c": 40.0,
        "dp_min_c": -12.0, "dp_max_c": 24.0,
        "max_rh_pct": 85.0,
        "description": "Extended environmental envelope",
    },
    "A4": {
        "temp_min_c": 5.0, "temp_max_c": 45.0,
        "dp_min_c": -12.0, "dp_max_c": 24.0,
        "max_rh_pct": 90.0,
        "description": "Maximum environmental envelope",
    },
}

# Uptime Institute Tier requirements
TIER_REQUIREMENTS: dict[int, dict[str, Any]] = {
    1: {
        "label": "Tier I", "availability_pct": 99.671,
        "annual_downtime_hours": 28.8,
        "redundancy": "N",
        "power_paths": 1, "cooling_paths": 1,
        "concurrently_maintainable": False, "fault_tolerant": False,
        "description": "Basic site infrastructure — single non-redundant path",
    },
    2: {
        "label": "Tier II", "availability_pct": 99.741,
        "annual_downtime_hours": 22.0,
        "redundancy": "N+1",
        "power_paths": 1, "cooling_paths": 1,
        "concurrently_maintainable": False, "fault_tolerant": False,
        "description": "Redundant capacity components — single distribution path",
    },
    3: {
        "label": "Tier III", "availability_pct": 99.982,
        "annual_downtime_hours": 1.6,
        "redundancy": "N+1",
        "power_paths": 2, "cooling_paths": 2,
        "concurrently_maintainable": True, "fault_tolerant": False,
        "description": "Concurrently maintainable — multiple distribution paths, one active",
    },
    4: {
        "label": "Tier IV", "availability_pct": 99.995,
        "annual_downtime_hours": 0.44,
        "redundancy": "2N+1",
        "power_paths": 2, "cooling_paths": 2,
        "concurrently_maintainable": True, "fault_tolerant": True,
        "description": "Fault tolerant — simultaneous active distribution paths",
    },
}

# Power density benchmarks (kW/rack)
POWER_DENSITY_BENCHMARKS: list[dict[str, Any]] = [
    {"workload": "Traditional enterprise", "kw_range": [5, 10], "cooling": "Air cooling"},
    {"workload": "Standard cloud", "kw_range": [10, 15], "cooling": "Air cooling"},
    {"workload": "Enhanced cloud", "kw_range": [15, 30], "cooling": "Air / hybrid"},
    {"workload": "High-density cloud", "kw_range": [30, 40], "cooling": "Hybrid (air + liquid)"},
    {"workload": "AI inference", "kw_range": [30, 60], "cooling": "Direct liquid cooling"},
    {"workload": "AI training", "kw_range": [60, 120], "cooling": "Direct liquid cooling"},
    {"workload": "AI training (GB200)", "kw_range": [120, 132], "cooling": "Immersion / DLC"},
    {"workload": "Next-gen AI (Blackwell Ultra)", "kw_range": [200, 250], "cooling": "Immersion cooling"},
    {"workload": "Extreme (Rubin 576 GPU)", "kw_range": [500, 900], "cooling": "Immersion cooling"},
]

# CAPEX benchmarks (GBP per MW of IT load, converting from USD at ~0.8)
CAPEX_PER_MW_GBP = {
    "standard": {"low": 7_200_000, "high": 9_600_000},       # $9-12M → £7.2-9.6M
    "ai_optimised": {"low": 12_000_000, "high": 16_000_000},  # $15-20M → £12-16M
}

# CAPEX breakdown percentages (of total)
CAPEX_BREAKDOWN_PCT = {
    "civil": 0.25,      # Shell & core, foundations, building envelope
    "mep": 0.15,        # Mechanical, electrical, plumbing fit-out
    "power": 0.22,      # UPS, generators, switchgear, transformers
    "cooling": 0.18,    # Chillers, CRACs, cooling towers, piping
    "it_infra": 0.08,   # Racks, cabling, containment
    "fire_safety": 0.04,  # Fire suppression, detection
    "bms_dcim": 0.03,   # Building management, monitoring
    "commissioning": 0.03,  # Testing, validation, handover
    "contingency": 0.02,  # Contingency reserve
}

# WUE by cooling type (litres per kWh of IT load)
WUE_BY_COOLING: dict[str, float] = {
    "air": 0.0,
    "evaporative": 2.0,
    "hybrid": 0.8,
    "free_cooling": 0.0,
    "dlc": 0.1,
    "immersion": 0.0,
}


# ---------------------------------------------------------------------------
# Helper: find nearest Carbon Intensity region
# ---------------------------------------------------------------------------
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS-84 points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_nearest_region(lat: float, lon: float) -> tuple[int, str]:
    """Find nearest Carbon Intensity API region by haversine distance."""
    best_id = 13
    best_dist = float("inf")
    for rid, info in CI_REGIONS.items():
        d = _haversine_km(lat, lon, info["lat"], info["lon"])
        if d < best_dist:
            best_dist = d
            best_id = rid
    return best_id, CI_REGIONS[best_id]["name"]


# ---------------------------------------------------------------------------
# Helper: simple solar/wind capacity factor curves
# ---------------------------------------------------------------------------
def _solar_capacity_factor(hour: int, lat: float) -> float:
    """Approximate solar capacity factor for a given hour.

    Uses a sinusoidal model peaking at solar noon, adjusted by latitude.
    UK solar CF ~10-11% annual average; peak hours ~0.5-0.7 in summer midday.
    """
    # Sunrise/sunset approximation (UK-ish)
    sunrise = max(4, 7 - (lat - 50) * 0.1)
    sunset = min(21, 17 + (lat - 50) * 0.1)
    if hour < sunrise or hour > sunset:
        return 0.0
    # Sinusoidal curve
    day_length = sunset - sunrise
    t = (hour - sunrise) / day_length  # 0..1 through the day
    # Peak CF ~0.5 at midday, annual average ~0.11
    # We model a typical day (not peak summer): scale by 0.35
    return max(0.0, 0.35 * math.sin(math.pi * t))


def _wind_capacity_factor(hour: int) -> float:
    """Approximate wind capacity factor for a given hour.

    UK onshore wind CF ~27% annual average. Wind is less diurnal than solar
    but tends to be slightly higher overnight and in early morning.
    """
    # Mild diurnal pattern: slightly higher 22:00-08:00
    base = 0.27
    if 22 <= hour or hour <= 8:
        return base * 1.15  # ~31% overnight
    elif 10 <= hour <= 16:
        return base * 0.85  # ~23% midday (thermal convection reduces surface wind)
    return base


# ---------------------------------------------------------------------------
# 1. Hourly CFE Profile
# ---------------------------------------------------------------------------
async def hourly_cfe_profile(
    lat: float,
    lon: float,
    capacity_mw: float,
    solar_mw: float = 0,
    wind_mw: float = 0,
    bess_mwh: float = 0,
) -> dict[str, Any]:
    """Calculate 24-hour Carbon-Free Energy profile.

    For each hour: grid carbon intensity, renewable generation, DC load, CFE%.
    Uses Carbon Intensity API regional data + simplified solar/wind capacity
    factor curves.

    Parameters
    ----------
    lat, lon : float
        WGS-84 coordinates of the site.
    capacity_mw : float
        Data centre IT load in MW.
    solar_mw : float
        Co-located or PPA solar capacity in MW.
    wind_mw : float
        Co-located or PPA wind capacity in MW.
    bess_mwh : float
        Battery energy storage capacity in MWh.

    Returns
    -------
    dict
        hours: list of 24 hourly dicts with dc_load_mw, renewable_mw,
        grid_mw, carbon_gco2, cfe_pct.
        summary: avg_cfe, peak_carbon_hour, total_renewable_mwh, etc.
    """
    region_id, region_name = _find_nearest_region(lat, lon)

    # Fetch 48h forecast from Carbon Intensity API
    hourly_intensities: list[float] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            from_str = now.strftime("%Y-%m-%dT%H:%MZ")
            url = f"{CI_API_BASE}/regional/intensity/{from_str}/fw48h/regionid/{region_id}"
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            raw_data = payload.get("data", [])
            if isinstance(raw_data, dict):
                raw_data = raw_data.get("data", [])

            for entry in raw_data:
                intensity = 0
                if "regions" in entry:
                    for rg in entry["regions"]:
                        if rg.get("regionid") == region_id or not rg.get("regionid"):
                            intensity = rg.get("intensity", {}).get("forecast", 0) or 0
                            break
                else:
                    intensity = entry.get("intensity", {}).get("forecast", 0) or 0
                hourly_intensities.append(intensity)
    except Exception as exc:
        log.warning("Carbon Intensity API fetch failed: %s — using fallback", exc)

    # Pad or use fallback if API returned insufficient data
    fallback_intensity = REGIONAL_AVG_INTENSITY.get(region_id, 160)
    while len(hourly_intensities) < 24:
        hourly_intensities.append(fallback_intensity)

    # DC load: constant (data centres run near-constant, slight diurnal variation)
    dc_load_mw = capacity_mw * 0.85  # typical utilisation factor

    # Build hourly profile
    hours: list[dict[str, Any]] = []
    bess_state_mwh = bess_mwh * 0.5  # Start at 50% SoC
    total_renewable_mwh = 0.0
    total_grid_mwh = 0.0
    total_carbon_kg = 0.0
    peak_carbon_hour = 0
    peak_carbon_val = 0.0

    for h in range(24):
        # Carbon intensity for this hour
        ci = hourly_intensities[h] if h < len(hourly_intensities) else fallback_intensity

        # Renewable generation
        solar_gen = solar_mw * _solar_capacity_factor(h, lat) if solar_mw > 0 else 0.0
        wind_gen = wind_mw * _wind_capacity_factor(h) if wind_mw > 0 else 0.0
        renewable_mw = solar_gen + wind_gen

        # BESS logic: charge when renewable surplus, discharge when deficit
        surplus = renewable_mw - dc_load_mw
        bess_discharge = 0.0
        bess_charge = 0.0
        if surplus > 0 and bess_mwh > 0:
            # Charge battery with surplus (max C-rate 0.5)
            max_charge = min(surplus, bess_mwh * 0.5, bess_mwh - bess_state_mwh)
            bess_charge = max(0, max_charge)
            bess_state_mwh += bess_charge * 0.95  # 95% charge efficiency
        elif surplus < 0 and bess_state_mwh > 0 and bess_mwh > 0:
            # Discharge to cover deficit
            deficit = -surplus
            max_discharge = min(deficit, bess_mwh * 1.0, bess_state_mwh)
            bess_discharge = max(0, max_discharge)
            bess_state_mwh -= bess_discharge / 0.95  # 95% discharge efficiency
            bess_state_mwh = max(0, bess_state_mwh)

        # Effective renewable serving the DC
        effective_renewable = min(renewable_mw - bess_charge + bess_discharge, dc_load_mw)
        effective_renewable = max(0, effective_renewable)

        # Grid draw
        grid_mw = max(0, dc_load_mw - effective_renewable)

        # Carbon emissions (gCO2 for this hour, only from grid)
        carbon_gco2 = grid_mw * 1000 * ci  # MW → kW, then * gCO2/kWh

        # CFE% for this hour
        cfe_pct = (effective_renewable / dc_load_mw * 100) if dc_load_mw > 0 else 0.0
        cfe_pct = min(100.0, cfe_pct)

        hours.append({
            "hour": h,
            "dc_load_mw": round(dc_load_mw, 3),
            "solar_mw": round(solar_gen, 3),
            "wind_mw": round(wind_gen, 3),
            "renewable_mw": round(effective_renewable, 3),
            "bess_charge_mw": round(bess_charge, 3),
            "bess_discharge_mw": round(bess_discharge, 3),
            "bess_soc_mwh": round(bess_state_mwh, 3),
            "grid_mw": round(grid_mw, 3),
            "carbon_intensity_gco2": round(ci, 1),
            "carbon_gco2": round(carbon_gco2, 0),
            "cfe_pct": round(cfe_pct, 1),
        })

        total_renewable_mwh += effective_renewable
        total_grid_mwh += grid_mw
        total_carbon_kg += carbon_gco2 / 1000
        if carbon_gco2 > peak_carbon_val:
            peak_carbon_val = carbon_gco2
            peak_carbon_hour = h

    # Summary
    avg_cfe = sum(h_["cfe_pct"] for h_ in hours) / 24 if hours else 0.0
    total_demand_mwh = dc_load_mw * 24

    return {
        "hours": hours,
        "summary": {
            "avg_cfe_pct": round(avg_cfe, 1),
            "peak_carbon_hour": peak_carbon_hour,
            "peak_carbon_gco2": round(peak_carbon_val, 0),
            "total_renewable_mwh": round(total_renewable_mwh, 1),
            "total_grid_mwh": round(total_grid_mwh, 1),
            "total_demand_mwh": round(total_demand_mwh, 1),
            "total_carbon_kg": round(total_carbon_kg, 1),
            "region": region_name,
            "region_id": region_id,
            "dc_load_mw": round(dc_load_mw, 2),
            "solar_mw": solar_mw,
            "wind_mw": wind_mw,
            "bess_mwh": bess_mwh,
        },
    }


# ---------------------------------------------------------------------------
# 2. ASHRAE Compliance
# ---------------------------------------------------------------------------
def _simulate_hourly_temperatures(lat: float, lon: float) -> list[dict[str, float]]:
    """Simulate 8760 hourly temperature and humidity profiles.

    Uses a simplified climate model based on latitude. UK climate: mild
    maritime, with daily and seasonal temperature variation.

    Returns list of 8760 dicts with temp_c, humidity_pct, dew_point_c.
    """
    hours = []
    for day in range(365):
        # Seasonal sinusoid: coldest day ~Jan 20 (day 20), warmest ~Jul 20 (day 200)
        seasonal_offset = -math.cos(2 * math.pi * (day - 20) / 365)
        # Base temp varies with latitude: higher lat = cooler
        base_temp = 10.0 - (lat - 51.5) * 0.5  # UK baseline ~10°C annual mean
        seasonal_amp = 7.0  # +/- 7°C seasonal swing
        daily_mean = base_temp + seasonal_amp * seasonal_offset

        for hour_of_day in range(24):
            # Diurnal variation: ~+/- 4°C, minimum at 05:00, max at 15:00
            diurnal = -math.cos(2 * math.pi * (hour_of_day - 5) / 24) * 4.0
            temp = daily_mean + diurnal

            # Humidity: higher at low temps, lower at high temps
            rh = 75.0 - (temp - 10) * 0.8 + math.sin(2 * math.pi * hour_of_day / 24) * 5
            rh = max(30, min(95, rh))

            # Dew point approximation (Magnus formula)
            a, b = 17.27, 237.7
            alpha = a * temp / (b + temp) + math.log(rh / 100.0)
            dp = b * alpha / (a - alpha)

            hours.append({
                "temp_c": round(temp, 1),
                "humidity_pct": round(rh, 1),
                "dew_point_c": round(dp, 1),
            })
    return hours


def ashrae_compliance(lat: float, lon: float) -> dict[str, Any]:
    """Check site climate against ASHRAE TC 9.9 envelopes (A1-A4 + Recommended).

    Uses simulated hourly temperature/humidity data based on latitude
    to determine which ASHRAE class the ambient conditions satisfy
    and how many free-cooling hours are available.

    Parameters
    ----------
    lat, lon : float
        WGS-84 coordinates of the site.

    Returns
    -------
    dict
        class, compliant, hours_outside_recommended, max_temp_c,
        free_cooling_hours, dry_bulb_profile, envelope_compliance.
    """
    hourly_data = _simulate_hourly_temperatures(lat, lon)

    temps = [h["temp_c"] for h in hourly_data]
    rhs = [h["humidity_pct"] for h in hourly_data]
    dps = [h["dew_point_c"] for h in hourly_data]

    max_temp = max(temps)
    min_temp = min(temps)
    mean_temp = sum(temps) / len(temps)

    # Check compliance against each envelope
    envelope_compliance: dict[str, dict[str, Any]] = {}
    for env_name, env in ASHRAE_ENVELOPES.items():
        hours_outside = 0
        for i in range(len(hourly_data)):
            t, rh, dp = temps[i], rhs[i], dps[i]
            outside = (
                t < env["temp_min_c"] or t > env["temp_max_c"]
                or dp < env["dp_min_c"] or dp > env["dp_max_c"]
                or rh > env["max_rh_pct"]
            )
            if outside:
                hours_outside += 1
        envelope_compliance[env_name] = {
            "compliant": hours_outside == 0,
            "hours_outside": hours_outside,
            "pct_compliant": round((8760 - hours_outside) / 8760 * 100, 1),
            "temp_range_c": [env["temp_min_c"], env["temp_max_c"]],
            "max_rh_pct": env["max_rh_pct"],
            "description": env["description"],
        }

    # Determine highest compliant class
    best_class = None
    for env_name in ["Recommended", "A1", "A2", "A3", "A4"]:
        if envelope_compliance[env_name]["compliant"]:
            best_class = env_name
            break
    if best_class is None:
        # Find best fit (fewest hours outside)
        best_class = min(
            envelope_compliance,
            key=lambda k: envelope_compliance[k]["hours_outside"],
        )

    # Free cooling hours: hours where ambient < 18°C (can use economiser)
    free_cooling_hours = sum(1 for t in temps if t < 18.0)

    # Extended free cooling: hours where ambient < 27°C (can assist cooling)
    assisted_cooling_hours = sum(1 for t in temps if t < 27.0)

    # Monthly average temperature profile
    monthly_temps: list[float] = []
    for month in range(12):
        start_day = int(month * 30.44)
        end_day = int((month + 1) * 30.44)
        month_temps = temps[start_day * 24:end_day * 24]
        if month_temps:
            monthly_temps.append(round(sum(month_temps) / len(month_temps), 1))

    return {
        "class": best_class,
        "compliant": envelope_compliance.get(best_class, {}).get("compliant", False),
        "hours_outside_recommended": envelope_compliance["Recommended"]["hours_outside"],
        "max_temp_c": round(max_temp, 1),
        "min_temp_c": round(min_temp, 1),
        "mean_temp_c": round(mean_temp, 1),
        "free_cooling_hours": free_cooling_hours,
        "free_cooling_pct": round(free_cooling_hours / 8760 * 100, 1),
        "assisted_cooling_hours": assisted_cooling_hours,
        "dry_bulb_profile": monthly_temps,
        "envelope_compliance": envelope_compliance,
        "location": {"lat": lat, "lon": lon},
        "recommendations": _ashrae_recommendations(best_class, free_cooling_hours, max_temp),
    }


def _ashrae_recommendations(ashrae_class: str, free_cooling_hours: int, max_temp: float) -> list[str]:
    """Generate cooling strategy recommendations from ASHRAE analysis."""
    recs = []
    if free_cooling_hours > 6000:
        recs.append(
            f"Excellent free-cooling potential: {free_cooling_hours} hours/year "
            f"({free_cooling_hours / 8760 * 100:.0f}%). Direct/indirect economiser strongly recommended."
        )
    elif free_cooling_hours > 4000:
        recs.append(
            f"Good free-cooling potential: {free_cooling_hours} hours/year. "
            "Hybrid cooling (economiser + mechanical) recommended."
        )
    else:
        recs.append(
            f"Limited free-cooling: {free_cooling_hours} hours/year. "
            "Mechanical cooling required as primary."
        )

    if max_temp > 35:
        recs.append(
            f"Peak ambient {max_temp:.1f}°C exceeds A1 limit (32°C). "
            "Ensure cooling plant sized for extreme conditions. A2 or A3 envelope equipment recommended."
        )
    elif max_temp > 27:
        recs.append(
            f"Peak ambient {max_temp:.1f}°C is within A1 but above Recommended (27°C). "
            "Standard enterprise equipment suitable with adequate cooling."
        )

    if ashrae_class in ("A3", "A4"):
        recs.append(
            f"Site falls into ASHRAE {ashrae_class} — consider equipment rated for extended "
            "thermal envelope or invest in enhanced cooling to maintain Recommended envelope."
        )

    return recs


# ---------------------------------------------------------------------------
# 3. Tier Compliance
# ---------------------------------------------------------------------------
def tier_compliance(
    redundancy: str = "N+1",
    power_paths: int = 1,
    cooling_paths: int = 1,
    concurrently_maintainable: bool = False,
    fault_tolerant: bool = False,
) -> dict[str, Any]:
    """Determine Uptime Institute Tier level from design parameters.

    Evaluates the provided design against Tier I-IV requirements and
    identifies the highest tier achieved, plus any gaps to the next tier.

    Parameters
    ----------
    redundancy : str
        Component redundancy scheme: "N", "N+1", "2N", "2N+1".
    power_paths : int
        Number of independent power distribution paths.
    cooling_paths : int
        Number of independent cooling distribution paths.
    concurrently_maintainable : bool
        Whether any component can be maintained without IT shutdown.
    fault_tolerant : bool
        Whether any single fault is tolerated without IT impact.

    Returns
    -------
    dict
        tier, label, availability_pct, annual_downtime_hours, gaps.
    """
    redundancy_level = {"N": 0, "N+1": 1, "2N": 2, "2N+1": 3}.get(redundancy, 1)

    achieved_tier = 1  # Everyone gets at least Tier I

    # Tier II: requires at least N+1 redundancy
    if redundancy_level >= 1:
        achieved_tier = 2

    # Tier III: requires N+1 redundancy, 2 power paths, 2 cooling paths,
    # and concurrently maintainable
    if (redundancy_level >= 1 and power_paths >= 2
            and cooling_paths >= 2 and concurrently_maintainable):
        achieved_tier = 3

    # Tier IV: requires 2N or 2N+1 redundancy, 2+ power/cooling paths,
    # concurrently maintainable, AND fault tolerant
    if (redundancy_level >= 2 and power_paths >= 2
            and cooling_paths >= 2 and concurrently_maintainable
            and fault_tolerant):
        achieved_tier = 4

    tier_info = TIER_REQUIREMENTS[achieved_tier]

    # Identify gaps to next tier
    gaps: list[str] = []
    next_tier = min(achieved_tier + 1, 4)
    if achieved_tier < 4:
        next_req = TIER_REQUIREMENTS[next_tier]
        if next_tier == 2 and redundancy_level < 1:
            gaps.append("Need at least N+1 component redundancy for Tier II")
        if next_tier == 3:
            if power_paths < 2:
                gaps.append("Need 2 independent power distribution paths for Tier III")
            if cooling_paths < 2:
                gaps.append("Need 2 independent cooling distribution paths for Tier III")
            if not concurrently_maintainable:
                gaps.append("Need concurrent maintainability for Tier III")
        if next_tier == 4:
            if redundancy_level < 2:
                gaps.append("Need 2N or 2N+1 power redundancy for Tier IV")
            if not fault_tolerant:
                gaps.append("Need full fault tolerance for Tier IV (independent, physically isolated systems)")

    return {
        "tier": achieved_tier,
        "label": tier_info["label"],
        "availability_pct": tier_info["availability_pct"],
        "annual_downtime_hours": tier_info["annual_downtime_hours"],
        "description": tier_info["description"],
        "design_params": {
            "redundancy": redundancy,
            "power_paths": power_paths,
            "cooling_paths": cooling_paths,
            "concurrently_maintainable": concurrently_maintainable,
            "fault_tolerant": fault_tolerant,
        },
        "next_tier": next_tier if achieved_tier < 4 else None,
        "gaps": gaps,
        "tier_requirements": TIER_REQUIREMENTS,
    }


# ---------------------------------------------------------------------------
# 4. Power Density Design
# ---------------------------------------------------------------------------
def _redundancy_factor(scheme: str) -> float:
    """Multiplier for redundancy scheme."""
    return {"N": 1.0, "N+1": 1.15, "2N": 2.0, "2N+1": 2.15}.get(scheme, 1.15)


def _recommend_cooling_type(kw_per_rack: float) -> str:
    """Recommend cooling technology based on rack density."""
    if kw_per_rack <= 25:
        return "air"
    elif kw_per_rack <= 60:
        return "hybrid"
    elif kw_per_rack <= 120:
        return "dlc"
    else:
        return "immersion"


def power_density_design(
    it_load_mw: float,
    kw_per_rack: float = 10,
    tier: int = 3,
    redundancy: str = "N+1",
    cooling_type: str = "hybrid",
) -> dict[str, Any]:
    """Full DC design from power density specification.

    Calculates rack count, floor area, cooling tonnage, UPS sizing,
    generator sizing, transformer sizing, PDU count, and power chain topology.

    Engineering formulas:
    - Total Power = IT Load x PUE
    - Heat (BTU/hr) = IT Load (W) x 3.412
    - Tons of Cooling = BTU/hr / 12,000
    - Rule of thumb: 1 ton per 3.5 kW
    - UPS Heat = 0.04 x Power System Rating + 0.05 x IT Load
    - PDU Heat = 0.01 x Power System Rating + 0.02 x IT Load
    - Lighting = 21.53 W/m²

    Parameters
    ----------
    it_load_mw : float
        IT load in MW.
    kw_per_rack : float
        Average power per rack in kW.
    tier : int
        Target Uptime Institute Tier (1-4).
    redundancy : str
        Component redundancy: "N", "N+1", "2N", "2N+1".
    cooling_type : str
        Cooling strategy: "air", "hybrid", "evaporative", "free_cooling", "dlc", "immersion".

    Returns
    -------
    dict
        Comprehensive design including layout, power, cooling, heat loads, benchmarks.
    """
    it_load_kw = it_load_mw * 1000
    rf = _redundancy_factor(redundancy)

    # -- Rack layout --
    rack_count = math.ceil(it_load_kw / kw_per_rack)
    racks_per_row = 20
    rows = math.ceil(rack_count / (racks_per_row * 2))
    halls = max(1, math.ceil(rack_count / 200))

    # Floor area: 2.5 m² per rack (including aisles)
    whitespace_m2 = rack_count * 2.5
    support_m2 = whitespace_m2 * 0.4  # UPS rooms, cooling plant, switchgear
    total_m2 = whitespace_m2 + support_m2

    # -- PUE estimation --
    pue_map = {
        "air": 1.5, "hybrid": 1.3, "evaporative": 1.25,
        "free_cooling": 1.15, "dlc": 1.15, "immersion": 1.08,
    }
    pue = pue_map.get(cooling_type, 1.3)
    total_facility_kw = it_load_kw * pue

    # -- Heat load calculations (engineering formulas) --
    it_heat_btu = it_load_kw * 1000 * 3.412  # IT Load (W) x 3.412
    cooling_tons = it_heat_btu / 12_000  # BTU/hr / 12000
    cooling_tons_rule_of_thumb = it_load_kw / 3.5  # 1 ton per 3.5 kW

    # Power system rating (for UPS/PDU heat calcs)
    power_system_rating_kw = it_load_kw * rf
    ups_heat_kw = 0.04 * power_system_rating_kw + 0.05 * it_load_kw
    pdu_heat_kw = 0.01 * power_system_rating_kw + 0.02 * it_load_kw
    lighting_kw = total_m2 * 21.53 / 1000  # 21.53 W/m²
    personnel_kw = max(5, rack_count * 0.01) * 0.1  # ~0.1 kW per person, ~1 person per 100 racks minimum

    total_heat_kw = it_load_kw + ups_heat_kw + pdu_heat_kw + lighting_kw + personnel_kw
    total_heat_btu = total_heat_kw * 1000 * 3.412
    total_cooling_tons = total_heat_btu / 12_000
    # Safety margin: 30%
    design_cooling_tons = total_cooling_tons * 1.3

    # -- UPS sizing --
    ups_kw = it_load_kw * rf
    ups_modules = math.ceil(ups_kw / 250)  # 250 kW modular UPS units

    # -- Generator sizing --
    gen_kw = total_facility_kw * rf * 1.1  # 10% headroom
    gen_sets = math.ceil(gen_kw / 2000)  # 2MW diesel gensets

    # -- Transformer sizing --
    transformer_mva = total_facility_kw * rf / 1000 / 0.95  # 95% power factor
    transformer_count = math.ceil(transformer_mva / 2.5)  # 2.5 MVA units

    # -- PDU sizing --
    pdu_per_rack = 2 if redundancy in ("2N", "2N+1") else 1
    pdu_count = rack_count * pdu_per_rack

    # -- Switchgear --
    voltage_kv = 11 if it_load_mw < 20 else 33 if it_load_mw < 100 else 132
    switchgear_panels = math.ceil(transformer_count * 1.5)

    # -- Cooling equipment --
    crac_units = math.ceil(design_cooling_tons * 3.517 / 100)  # 100kW CRAC units
    chiller_count = math.ceil(design_cooling_tons * 3.517 / 500)  # 500kW chillers
    cooling_towers = math.ceil(design_cooling_tons / 300) if cooling_type in ("hybrid", "evaporative") else 0

    # -- Water consumption --
    wue = WUE_BY_COOLING.get(cooling_type, 0.8)
    annual_water_m3 = it_load_kw * 8760 * wue / 1000  # kWh * L/kWh / 1000

    # Cooling recommendation check
    recommended_cooling = _recommend_cooling_type(kw_per_rack)

    return {
        "layout": {
            "rack_count": rack_count,
            "kw_per_rack": kw_per_rack,
            "racks_per_row": racks_per_row,
            "rows": rows,
            "halls": halls,
            "whitespace_m2": round(whitespace_m2),
            "support_m2": round(support_m2),
            "total_m2": round(total_m2),
            "total_sqft": round(total_m2 * 10.764),
        },
        "power": {
            "it_load_mw": it_load_mw,
            "it_load_kw": round(it_load_kw),
            "pue": pue,
            "total_facility_kw": round(total_facility_kw),
            "total_facility_mw": round(total_facility_kw / 1000, 2),
            "redundancy": redundancy,
            "redundancy_factor": rf,
            "ups_capacity_kw": round(ups_kw),
            "ups_modules": ups_modules,
            "generator_capacity_kw": round(gen_kw),
            "generator_sets": gen_sets,
            "transformer_mva": round(transformer_mva, 1),
            "transformer_count": transformer_count,
            "voltage_kv": voltage_kv,
            "switchgear_panels": switchgear_panels,
            "pdu_count": pdu_count,
            "pdu_per_rack": pdu_per_rack,
        },
        "cooling": {
            "type": cooling_type,
            "recommended_type": recommended_cooling,
            "cooling_load_kw": round(total_heat_kw),
            "cooling_tons": round(total_cooling_tons, 1),
            "design_cooling_tons": round(design_cooling_tons, 1),
            "crac_units": crac_units,
            "chiller_count": chiller_count,
            "cooling_towers": cooling_towers,
            "wue_l_kwh": wue,
            "annual_water_m3": round(annual_water_m3),
        },
        "heat_loads": {
            "it_heat_kw": round(it_load_kw),
            "it_heat_btu_hr": round(it_heat_btu),
            "ups_heat_kw": round(ups_heat_kw, 1),
            "pdu_heat_kw": round(pdu_heat_kw, 1),
            "lighting_kw": round(lighting_kw, 1),
            "personnel_kw": round(personnel_kw, 1),
            "total_heat_kw": round(total_heat_kw, 1),
            "total_heat_btu_hr": round(total_heat_btu),
        },
        "tier": {
            "level": tier,
            "label": f"Tier {tier}",
            "availability_pct": TIER_REQUIREMENTS[tier]["availability_pct"],
            "annual_downtime_hours": TIER_REQUIREMENTS[tier]["annual_downtime_hours"],
        },
        "benchmarks": {
            "power_density_benchmarks": POWER_DENSITY_BENCHMARKS,
            "cooling_type_warning": (
                f"At {kw_per_rack} kW/rack, recommended cooling is '{recommended_cooling}' "
                f"but '{cooling_type}' was specified."
            ) if cooling_type != recommended_cooling else None,
        },
    }


# ---------------------------------------------------------------------------
# 5. Power Chain Topology
# ---------------------------------------------------------------------------
def power_chain_topology(
    it_load_mw: float,
    tier: int = 3,
    voltage_kv: float = 33,
) -> dict[str, Any]:
    """Generate the full power distribution chain topology.

    Models the path from grid HV supply through to rack-level IT equipment
    with redundancy based on tier level.

    Chain:
    Grid(HV) -> Substation(MV) -> Transformer(LV) -> Main Switchgear
    -> UPS -> STS -> PDU -> Rack PDU -> IT Equipment

    Parameters
    ----------
    it_load_mw : float
        IT load in MW.
    tier : int
        Target Uptime Institute Tier (1-4).
    voltage_kv : float
        Incoming grid voltage (11, 33, or 132 kV).

    Returns
    -------
    dict
        stages: list of power chain stages with voltage, redundancy, units.
        single_line_diagram: structured data for rendering.
    """
    it_load_kw = it_load_mw * 1000
    tier_info = TIER_REQUIREMENTS.get(tier, TIER_REQUIREMENTS[3])

    # Determine redundancy scheme from tier
    redundancy = tier_info["redundancy"]
    rf = _redundancy_factor(redundancy)
    power_paths = tier_info["power_paths"]
    is_dual_bus = tier >= 3

    # Facility total (assume PUE 1.3)
    pue = 1.3
    total_kw = it_load_kw * pue
    total_mw = total_kw / 1000

    # Grid supply voltage
    hv_voltage = max(voltage_kv, 33 if it_load_mw > 20 else 11)

    # Transformer LV output
    lv_voltage = 0.415  # 415V (UK standard)

    stages: list[dict[str, Any]] = []

    # Stage 1: Grid supply
    grid_capacity = total_mw * rf
    stages.append({
        "name": "Grid Supply (HV)",
        "voltage_kv": hv_voltage,
        "redundancy": f"{power_paths}x independent feeds" if power_paths > 1 else "Single feed",
        "units": power_paths,
        "capacity_each_mw": round(grid_capacity / power_paths, 1),
        "total_capacity_mw": round(grid_capacity, 1),
        "description": f"{hv_voltage}kV supply from DNO",
    })

    # Stage 2: HV/MV Substation
    stages.append({
        "name": "Substation (HV/MV)",
        "voltage_kv": hv_voltage,
        "redundancy": redundancy,
        "units": power_paths,
        "capacity_each_mw": round(grid_capacity / power_paths, 1),
        "total_capacity_mw": round(grid_capacity, 1),
        "description": f"Ring main unit / GIS switchgear at {hv_voltage}kV",
    })

    # Stage 3: Step-down Transformers
    tx_mva = total_kw * rf / 1000 / 0.95
    tx_count = math.ceil(tx_mva / 2.5)
    # For Tier III/IV: distribute across paths
    tx_per_path = math.ceil(tx_count / power_paths)
    stages.append({
        "name": "Transformers (MV → LV)",
        "voltage_kv": lv_voltage,
        "redundancy": redundancy,
        "units": tx_count,
        "capacity_each_mva": 2.5,
        "total_capacity_mva": round(tx_mva, 1),
        "description": f"{hv_voltage}kV to {lv_voltage * 1000:.0f}V step-down, {tx_per_path} per path",
    })

    # Stage 4: Main Switchgear / MSB
    msb_count = power_paths * 2  # A + B bus per path
    stages.append({
        "name": "Main Switchgear (MSB)",
        "voltage_kv": lv_voltage,
        "redundancy": "A+B bus" if is_dual_bus else "Single bus",
        "units": msb_count if is_dual_bus else power_paths,
        "capacity_each_kw": round(it_load_kw * rf / (msb_count if is_dual_bus else power_paths)),
        "total_capacity_kw": round(it_load_kw * rf),
        "description": "Main switchboard with automatic transfer",
    })

    # Stage 5: UPS
    ups_kw = it_load_kw * rf
    ups_modules = math.ceil(ups_kw / 250)
    stages.append({
        "name": "UPS (Uninterruptible Power Supply)",
        "voltage_kv": lv_voltage,
        "redundancy": redundancy,
        "units": ups_modules,
        "capacity_each_kw": 250,
        "total_capacity_kw": round(ups_kw),
        "description": f"Modular UPS, {redundancy} configuration, 94-97% efficiency",
    })

    # Stage 6: STS (Static Transfer Switch) — Tier III/IV only
    if tier >= 3:
        sts_count = math.ceil(it_load_kw / 500)  # 500kW STS units
        stages.append({
            "name": "STS (Static Transfer Switch)",
            "voltage_kv": lv_voltage,
            "redundancy": "Dual source",
            "units": sts_count,
            "capacity_each_kw": 500,
            "total_capacity_kw": round(sts_count * 500),
            "description": "Automatic transfer between A+B paths in <10ms",
        })

    # Stage 7: Floor PDU
    rack_count = math.ceil(it_load_kw / 10)  # assume 10kW average for PDU sizing
    pdu_count = math.ceil(rack_count / 20)  # each floor PDU serves ~20 racks
    pdu_per_path = 2 if is_dual_bus else 1
    stages.append({
        "name": "Floor PDU",
        "voltage_kv": lv_voltage,
        "redundancy": "A+B feed" if is_dual_bus else "Single feed",
        "units": pdu_count * pdu_per_path,
        "capacity_each_kw": round(it_load_kw / pdu_count),
        "total_capacity_kw": round(it_load_kw * rf),
        "description": f"Floor-level power distribution, each serving ~20 racks",
    })

    # Stage 8: Rack PDU
    rack_pdus = rack_count * pdu_per_path
    stages.append({
        "name": "Rack PDU",
        "voltage_kv": lv_voltage,
        "redundancy": "A+B" if is_dual_bus else "Single",
        "units": rack_pdus,
        "capacity_each_kw": round(it_load_kw / rack_count, 1),
        "total_capacity_kw": round(it_load_kw * rf),
        "description": "Intelligent metered PDU, per-outlet monitoring",
    })

    # Stage 9: IT Equipment
    stages.append({
        "name": "IT Equipment",
        "voltage_kv": lv_voltage,
        "redundancy": "Dual PSU" if tier >= 3 else "Single PSU",
        "units": rack_count,
        "capacity_each_kw": round(it_load_kw / rack_count, 1),
        "total_capacity_kw": round(it_load_kw),
        "description": f"{rack_count} racks, {it_load_kw / rack_count:.1f} kW average",
    })

    # Generator backup
    gen_kw = total_kw * rf * 1.1
    gen_count = math.ceil(gen_kw / 2000)
    generator = {
        "name": "Diesel Generators (Backup)",
        "redundancy": redundancy,
        "units": gen_count,
        "capacity_each_kw": 2000,
        "total_capacity_kw": round(gen_kw),
        "auto_start_seconds": 10,
        "fuel_hours": 48 if tier >= 3 else 24,
        "description": f"{gen_count}x 2MW gensets, auto-start within 10s of grid failure",
    }

    # Single line diagram structure
    sld = {
        "paths": power_paths,
        "bus_config": "A+B" if is_dual_bus else "Single",
        "tier": tier,
        "voltage_levels": [
            {"level": "HV", "voltage_kv": hv_voltage},
            {"level": "LV", "voltage_kv": lv_voltage},
        ],
        "chain": " → ".join(s["name"] for s in stages),
    }

    return {
        "stages": stages,
        "generator_backup": generator,
        "single_line_diagram": sld,
        "summary": {
            "it_load_mw": it_load_mw,
            "total_facility_mw": round(total_mw, 2),
            "tier": tier,
            "redundancy": redundancy,
            "power_paths": power_paths,
            "incoming_voltage_kv": hv_voltage,
            "rack_count": rack_count,
        },
    }


# ---------------------------------------------------------------------------
# 6. Construction Timeline
# ---------------------------------------------------------------------------
def construction_timeline(
    it_load_mw: float,
    tier: int = 3,
    modular: bool = False,
    has_planning: bool = False,
    has_grid: bool = False,
) -> dict[str, Any]:
    """Generate construction Gantt timeline for a DC facility.

    Phases: Land acquisition -> Planning -> Grid connection -> Enabling works
    -> Shell & core -> M&E install -> Commissioning -> Handover.

    Parameters
    ----------
    it_load_mw : float
        IT load capacity in MW.
    tier : int
        Target Uptime Institute Tier (1-4).
    modular : bool
        Whether using modular/prefab construction (faster).
    has_planning : bool
        Whether planning permission is already secured.
    has_grid : bool
        Whether grid connection is already secured.

    Returns
    -------
    dict
        phases: list of phase dicts with start_month, duration, dependencies.
        total_months, critical_path.
    """
    # Duration estimates by size and tier
    size_factor = 1.0
    if it_load_mw > 100:
        size_factor = 1.5
    elif it_load_mw > 50:
        size_factor = 1.3
    elif it_load_mw > 20:
        size_factor = 1.1

    tier_factor = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.3}.get(tier, 1.0)
    modular_factor = 0.6 if modular else 1.0

    phases: list[dict[str, Any]] = []
    month = 0

    # Phase 1: Land Acquisition
    if not has_planning:
        duration = round(3 * size_factor)
        phases.append({
            "name": "Land Acquisition & Due Diligence",
            "start_month": month,
            "duration_months": duration,
            "dependencies": [],
            "status": "pending",
            "description": "Site survey, legal due diligence, land purchase/lease, environmental baseline",
        })
        month += duration

    # Phase 2: Planning Permission
    if not has_planning:
        # NSIP pathway for >50MW, otherwise local planning
        nsip = it_load_mw * 1.3 > 50  # PUE-adjusted total > 50MW
        duration = round((12 if nsip else 8) * tier_factor)
        phases.append({
            "name": "Planning Permission" + (" (NSIP)" if nsip else ""),
            "start_month": month,
            "duration_months": duration,
            "dependencies": ["Land Acquisition & Due Diligence"] if not has_planning else [],
            "status": "pending",
            "description": "EIA screening/scoping, application, determination" +
                           (". NSIP DCO process for >50MW total facility power" if nsip else ""),
        })
        month += duration
    else:
        phases.append({
            "name": "Planning Permission",
            "start_month": 0,
            "duration_months": 0,
            "dependencies": [],
            "status": "complete",
            "description": "Already secured",
        })

    # Phase 3: Grid Connection
    if not has_grid:
        # UK grid connection: 6-24 months depending on capacity and DNO queue
        if it_load_mw * 1.3 < 10:
            grid_months = 6
        elif it_load_mw * 1.3 < 50:
            grid_months = 12
        elif it_load_mw * 1.3 < 200:
            grid_months = 18
        else:
            grid_months = 24
        grid_months = round(grid_months * tier_factor)
        # Grid connection can start in parallel with planning (month overlap)
        grid_start = max(0, month - 6) if not has_planning else 0
        phases.append({
            "name": "Grid Connection",
            "start_month": grid_start,
            "duration_months": grid_months,
            "dependencies": ["Land Acquisition & Due Diligence"] if not has_planning else [],
            "status": "pending",
            "description": f"DNO application, design, build. ~{it_load_mw * 1.3:.0f}MW total facility load",
        })
        grid_end = grid_start + grid_months
    else:
        phases.append({
            "name": "Grid Connection",
            "start_month": 0,
            "duration_months": 0,
            "dependencies": [],
            "status": "complete",
            "description": "Already secured",
        })
        grid_end = 0

    # Earliest construction start: after planning + grid
    construction_start = max(month, grid_end)

    # Phase 4: Enabling Works
    duration = round(3 * size_factor * modular_factor)
    phases.append({
        "name": "Enabling Works",
        "start_month": construction_start,
        "duration_months": duration,
        "dependencies": ["Planning Permission", "Grid Connection"],
        "status": "pending",
        "description": "Site clearance, earthworks, access roads, temporary services, foundations",
    })
    enabling_end = construction_start + duration

    # Phase 5: Shell & Core
    duration = round(8 * size_factor * tier_factor * modular_factor)
    phases.append({
        "name": "Shell & Core",
        "start_month": enabling_end,
        "duration_months": duration,
        "dependencies": ["Enabling Works"],
        "status": "pending",
        "description": "Structural steel, cladding, roofing, internal walls" +
                       (". Modular/prefab units: accelerated programme" if modular else ""),
    })
    shell_end = enabling_end + duration

    # Phase 6: M&E Installation
    duration = round(10 * size_factor * tier_factor * modular_factor)
    # M&E can overlap with shell by ~2 months
    me_start = max(enabling_end, shell_end - 2)
    phases.append({
        "name": "M&E Installation",
        "start_month": me_start,
        "duration_months": duration,
        "dependencies": ["Shell & Core"],
        "status": "pending",
        "description": "Power distribution, UPS, generators, cooling plant, fire suppression, BMS/DCIM",
    })
    me_end = me_start + duration

    # Phase 7: Commissioning
    duration = round(3 * tier_factor)
    if tier >= 4:
        duration = max(duration, 6)
    phases.append({
        "name": "Commissioning & Testing",
        "start_month": me_end,
        "duration_months": duration,
        "dependencies": ["M&E Installation"],
        "status": "pending",
        "description": "IST (Integrated Systems Testing), load bank testing, "
                       "Tier certification, soak testing",
    })
    comm_end = me_end + duration

    # Phase 8: Handover
    phases.append({
        "name": "Handover & Go-Live",
        "start_month": comm_end,
        "duration_months": 1,
        "dependencies": ["Commissioning & Testing"],
        "status": "pending",
        "description": "Operational handover, IT fit-out begins, first racks energised",
    })

    total_months = comm_end + 1

    # Critical path
    critical = [p["name"] for p in phases if p["duration_months"] > 0]

    return {
        "phases": phases,
        "total_months": total_months,
        "critical_path": critical,
        "modular": modular,
        "summary": {
            "it_load_mw": it_load_mw,
            "tier": tier,
            "total_months": total_months,
            "total_years": round(total_months / 12, 1),
            "modular_savings_months": round(total_months * 0.35) if not modular else 0,
            "note": (
                "Modular construction can save ~35% on timeline"
                if not modular else "Modular/prefab construction programme applied"
            ),
        },
    }


# ---------------------------------------------------------------------------
# 7. DC Financial Model
# ---------------------------------------------------------------------------
def dc_financial_model(
    it_load_mw: float,
    tier: int = 3,
    kw_per_rack: float = 10,
    pue: float = 1.3,
    electricity_price_gbp_kwh: float = 0.12,
    land_cost_gbp: float = 0,
    grid_connection_cost_gbp: float = 0,
) -> dict[str, Any]:
    """DC-specific CAPEX/OPEX/revenue/IRR model.

    CAPEX benchmarks:
    - Standard: £7.2-9.6M/MW (£9-12M/MW USD equivalent)
    - AI-optimised: £12-16M/MW (£15-20M/MW USD equivalent)

    OPEX breakdown: maintenance ~40%, electricity 15-25%.

    Revenue: kW delivered x rate/kW/month x utilisation.

    Parameters
    ----------
    it_load_mw : float
        IT load in MW.
    tier : int
        Uptime Institute Tier (1-4).
    kw_per_rack : float
        Average kW per rack.
    pue : float
        Power Usage Effectiveness.
    electricity_price_gbp_kwh : float
        Electricity price in £/kWh.
    land_cost_gbp : float
        Land acquisition cost in £.
    grid_connection_cost_gbp : float
        Grid connection cost in £.

    Returns
    -------
    dict
        capex, opex, revenue, irr, npv, payback_years.
    """
    it_load_kw = it_load_mw * 1000
    total_facility_kw = it_load_kw * pue
    annual_kwh = total_facility_kw * 8760

    # -- Determine if AI-optimised (>30 kW/rack) --
    is_ai = kw_per_rack > 30
    capex_range = CAPEX_PER_MW_GBP["ai_optimised"] if is_ai else CAPEX_PER_MW_GBP["standard"]
    capex_per_mw = (capex_range["low"] + capex_range["high"]) / 2

    # Tier premium
    tier_premium = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.4}.get(tier, 1.0)
    capex_per_mw *= tier_premium

    base_capex = capex_per_mw * it_load_mw

    # CAPEX breakdown
    capex_breakdown: dict[str, float] = {}
    for category, pct in CAPEX_BREAKDOWN_PCT.items():
        capex_breakdown[category] = round(base_capex * pct)

    # Add land and grid connection
    total_capex = base_capex + land_cost_gbp + grid_connection_cost_gbp
    capex_breakdown["land"] = round(land_cost_gbp)
    capex_breakdown["grid_connection"] = round(grid_connection_cost_gbp)

    # -- OPEX --
    annual_electricity = annual_kwh * electricity_price_gbp_kwh
    annual_maintenance = base_capex * 0.03  # 3% of base capex
    rack_count = math.ceil(it_load_kw / kw_per_rack)
    annual_staffing = max(300_000, rack_count * 1500)  # min 3 FTE
    annual_insurance = base_capex * 0.005
    annual_water = total_facility_kw * 8760 * 0.0008 * 0.002  # WUE * water price
    annual_rates = base_capex * 0.012  # business rates ~1.2%

    total_opex = (
        annual_electricity + annual_maintenance + annual_staffing
        + annual_insurance + annual_water + annual_rates
    )

    opex_breakdown = {
        "electricity": round(annual_electricity),
        "maintenance": round(annual_maintenance),
        "staffing": round(annual_staffing),
        "insurance": round(annual_insurance),
        "water": round(annual_water),
        "business_rates": round(annual_rates),
    }

    # -- Revenue --
    # UK colocation rates: £100-200/kW/month for standard, £250-400 for high-density
    rate_per_kw_month = 180 if is_ai else 120
    utilisation_pct = 75.0  # Typical ramp to 75% over first few years

    annual_revenue = it_load_kw * rate_per_kw_month * 12 * (utilisation_pct / 100)

    # -- Financial Metrics --
    annual_noi = annual_revenue - total_opex  # Net Operating Income
    project_life = 25

    # Simple payback
    payback_years = total_capex / annual_noi if annual_noi > 0 else float("inf")

    # IRR approximation (simplified: assume constant annual cash flows)
    # NPV = -CAPEX + sum(NOI / (1+r)^t) for t=1..25
    # Find r where NPV=0 using bisection
    irr = _calculate_irr(total_capex, annual_noi, project_life)

    # NPV at 8% discount rate
    discount_rate = 0.08
    npv = -total_capex
    for year in range(1, project_life + 1):
        npv += annual_noi / (1 + discount_rate) ** year

    return {
        "capex": {
            "total_gbp": round(total_capex),
            "per_mw_gbp": round(total_capex / it_load_mw),
            "per_kw_gbp": round(total_capex / it_load_kw),
            "per_rack_gbp": round(total_capex / rack_count),
            "breakdown": capex_breakdown,
            "type": "AI-optimised" if is_ai else "Standard",
            "tier_premium_pct": round((tier_premium - 1) * 100),
        },
        "opex": {
            "total_annual_gbp": round(total_opex),
            "per_kw_annual_gbp": round(total_opex / it_load_kw),
            "breakdown": opex_breakdown,
            "electricity_pct": round(annual_electricity / total_opex * 100, 1) if total_opex > 0 else 0,
        },
        "revenue": {
            "annual_gbp": round(annual_revenue),
            "per_kw_month_gbp": rate_per_kw_month,
            "utilisation_pct": utilisation_pct,
        },
        "financials": {
            "annual_noi_gbp": round(annual_noi),
            "irr_pct": round(irr * 100, 1) if irr else None,
            "npv_gbp": round(npv),
            "payback_years": round(payback_years, 1) if payback_years != float("inf") else None,
            "discount_rate_pct": discount_rate * 100,
            "project_life_years": project_life,
        },
        "assumptions": {
            "pue": pue,
            "electricity_price_gbp_kwh": electricity_price_gbp_kwh,
            "it_load_mw": it_load_mw,
            "kw_per_rack": kw_per_rack,
            "rack_count": rack_count,
            "annual_kwh": round(annual_kwh),
        },
    }


def _calculate_irr(
    initial_investment: float,
    annual_cash_flow: float,
    years: int,
    tolerance: float = 0.0001,
) -> float | None:
    """Calculate IRR using bisection method for uniform annual cash flows."""
    if annual_cash_flow <= 0:
        return None

    low, high = -0.5, 2.0
    for _ in range(200):
        mid = (low + high) / 2
        npv = -initial_investment
        for year in range(1, years + 1):
            npv += annual_cash_flow / (1 + mid) ** year

        if abs(npv) < tolerance:
            return mid
        if npv > 0:
            low = mid
        else:
            high = mid

    return (low + high) / 2


# ---------------------------------------------------------------------------
# 8. Water Stress Assessment
# ---------------------------------------------------------------------------
async def water_stress_assessment(
    lat: float,
    lon: float,
    cooling_type: str = "hybrid",
    it_load_mw: float = 10,
) -> dict[str, Any]:
    """Assess local water availability and DC water requirements.

    Calculates WUE based on cooling type and estimates annual water
    consumption. Provides a qualitative water stress assessment based
    on UK regional data.

    Parameters
    ----------
    lat, lon : float
        WGS-84 coordinates.
    cooling_type : str
        Cooling strategy.
    it_load_mw : float
        IT load in MW.

    Returns
    -------
    dict
        wue_l_kwh, annual_water_m3, water_stress_level,
        nearest_water_source, abstraction_available.
    """
    it_load_kw = it_load_mw * 1000

    # WUE by cooling type
    wue = WUE_BY_COOLING.get(cooling_type, 0.8)

    # Annual IT energy
    annual_it_kwh = it_load_kw * 8760

    # Annual water consumption
    annual_water_m3 = annual_it_kwh * wue / 1000  # L/kWh * kWh / 1000 = m³
    daily_water_m3 = annual_water_m3 / 365

    # UK regional water stress assessment
    # EA water stress classification areas (simplified)
    # South East is severely stressed; North/Scotland less so
    if lat > 55:
        stress_level = "low"
        stress_description = "Northern England / Scotland — generally abundant water resources"
        abstraction_available = True
    elif lat > 53:
        stress_level = "moderate"
        stress_description = "Midlands / Northern England — moderate water stress"
        abstraction_available = True
    elif lon < -2:
        stress_level = "moderate"
        stress_description = "Western England / Wales — moderate water stress"
        abstraction_available = True
    elif lat > 51.5:
        stress_level = "high"
        stress_description = "East / Central England — high water stress (EA designated)"
        abstraction_available = daily_water_m3 < 500
    else:
        stress_level = "severe"
        stress_description = "South East England / London — severe water stress (EA designated)"
        abstraction_available = daily_water_m3 < 200

    # Cooling strategy comparison
    cooling_comparison = {}
    for ct, ct_wue in WUE_BY_COOLING.items():
        ct_annual_m3 = annual_it_kwh * ct_wue / 1000
        cooling_comparison[ct] = {
            "wue_l_kwh": ct_wue,
            "annual_water_m3": round(ct_annual_m3),
            "daily_water_m3": round(ct_annual_m3 / 365, 1),
        }

    # Recommendations
    recommendations: list[str] = []
    if stress_level in ("high", "severe") and wue > 0.5:
        recommendations.append(
            "Site is in a water-stressed area. Consider air-cooled or DLC/immersion "
            "cooling to minimise water consumption."
        )
    if wue > 0 and daily_water_m3 > 100:
        recommendations.append(
            f"Daily consumption of {daily_water_m3:.0f} m³ may require EA "
            "abstraction licence and water company agreement."
        )
    if cooling_type == "evaporative" and stress_level != "low":
        recommendations.append(
            "Evaporative cooling in water-stressed areas faces regulatory risk. "
            "DCMS AI Growth Zone rules require proof of water supply sufficiency."
        )
    if wue == 0:
        recommendations.append(
            f"{cooling_type.replace('_', ' ').title()} cooling has zero water consumption — "
            "excellent for water-constrained sites."
        )

    return {
        "wue_l_kwh": wue,
        "annual_water_m3": round(annual_water_m3),
        "daily_water_m3": round(daily_water_m3, 1),
        "water_stress_level": stress_level,
        "water_stress_description": stress_description,
        "abstraction_available": abstraction_available,
        "cooling_type": cooling_type,
        "it_load_mw": it_load_mw,
        "cooling_comparison": cooling_comparison,
        "recommendations": recommendations,
        "benchmarks": {
            "industry_avg_wue": 1.8,
            "best_in_class_wue": 0.19,
            "google_fleet_wue": 0.8,
        },
        "location": {"lat": lat, "lon": lon},
    }
