"""Water Stress & Cooling Strategy Analyzer for data centres."""

from __future__ import annotations
import math
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(15.0)

# ── Cooling strategy models ───────────────────────────────────────────────
COOLING_MODELS = {
    "mechanical": {"pue_range": (1.4, 1.6), "wue": 0.0, "capex_per_mw": 800_000, "opex_pct": 0.04, "desc": "Chiller-based, no water, high energy"},
    "evaporative": {"pue_range": (1.2, 1.3), "wue": 1.5, "capex_per_mw": 600_000, "opex_pct": 0.03, "desc": "Evaporative cooling, moderate water use"},
    "air_cooled": {"pue_range": (1.25, 1.35), "wue": 0.0, "capex_per_mw": 700_000, "opex_pct": 0.035, "desc": "Dry coolers, no water, UK climate allows 5000+ free-cooling hrs"},
    "liquid_immersion": {"pue_range": (1.02, 1.10), "wue": 0.0, "capex_per_mw": 1_200_000, "opex_pct": 0.02, "desc": "Closed loop, zero water, lowest PUE"},
    "hybrid": {"pue_range": (1.15, 1.25), "wue": 0.45, "capex_per_mw": 750_000, "opex_pct": 0.035, "desc": "Evaporative + dry cooler, best balance"},
}


async def assess_water_stress(lat: float, lon: float) -> dict[str, Any]:
    """Assess water stress at a location using simplified UK model."""
    # UK regional water stress (based on EA classification)
    # South East and East Anglia are seriously stressed
    stress_map = [
        ({"minLat": 50.5, "maxLat": 52.0, "minLon": -1.5, "maxLon": 1.8}, "High", 3.5, "Thames / South East"),
        ({"minLat": 51.5, "maxLat": 53.0, "minLon": 0.0, "maxLon": 2.0}, "High", 3.2, "Anglian / East"),
        ({"minLat": 50.5, "maxLat": 51.5, "minLon": -5.0, "maxLon": -1.5}, "Medium", 2.5, "South West / Wessex"),
        ({"minLat": 52.0, "maxLat": 54.0, "minLon": -3.0, "maxLon": 0.0}, "Medium", 2.0, "Midlands"),
        ({"minLat": 53.0, "maxLat": 56.0, "minLon": -3.5, "maxLon": 0.0}, "Low", 1.5, "North / Yorkshire"),
        ({"minLat": 54.0, "maxLat": 56.0, "minLon": -6.0, "maxLon": -2.0}, "Low", 1.2, "North West"),
        ({"minLat": 55.0, "maxLat": 59.0, "minLon": -8.0, "maxLon": -1.0}, "Low", 1.0, "Scotland"),
        ({"minLat": 51.0, "maxLat": 54.0, "minLon": -6.0, "maxLon": -3.0}, "Low", 1.3, "Wales"),
    ]

    region = "Unknown"
    stress_level = "Medium"
    score = 2.0

    for bounds, level, s, name in stress_map:
        if bounds["minLat"] <= lat <= bounds["maxLat"] and bounds["minLon"] <= lon <= bounds["maxLon"]:
            region, stress_level, score = name, level, s
            break

    drought_risk = "High" if score > 3 else "Medium" if score > 2 else "Low"

    return {
        "stress_level": stress_level,
        "baseline_stress_score": score,
        "region": region,
        "seasonal_variability": "High" if stress_level == "High" else "Moderate",
        "groundwater_depletion": "Declining" if score > 3 else "Stable",
        "drought_risk": drought_risk,
        "recommendation": "Air-cooled or liquid immersion recommended" if score > 2.5 else "All cooling strategies viable",
    }


def model_cooling_strategy(it_load_mw: float, climate_zone: str = "4A", cooling_type: str = "hybrid") -> dict[str, Any]:
    """Model cooling performance for a given strategy."""
    model = COOLING_MODELS.get(cooling_type, COOLING_MODELS["hybrid"])
    pue = sum(model["pue_range"]) / 2

    # UK climate: ~5000-6000 free cooling hours/year (marine 4A)
    free_cooling_hours = 5500 if climate_zone == "4A" else 4000
    total_power_mw = it_load_mw * pue
    cooling_power_mw = total_power_mw - it_load_mw

    annual_energy_mwh = total_power_mw * 8760
    annual_water_m3 = model["wue"] * it_load_mw * 8760 * 1000  # L to m3 conversion: wue is L/kWh
    capex = model["capex_per_mw"] * it_load_mw
    opex = capex * model["opex_pct"]

    return {
        "cooling_type": cooling_type,
        "pue": round(pue, 2),
        "wue_l_per_kwh": model["wue"],
        "total_power_mw": round(total_power_mw, 2),
        "cooling_power_mw": round(cooling_power_mw, 2),
        "annual_energy_mwh": round(annual_energy_mwh, 1),
        "annual_water_m3": round(annual_water_m3, 0),
        "free_cooling_hours": free_cooling_hours,
        "capex_gbp": round(capex),
        "opex_gbp_year": round(opex),
        "description": model["desc"],
    }


def compare_cooling_strategies(it_load_mw: float, lat: float = 52.0, lon: float = -1.5) -> dict[str, Any]:
    """Compare all cooling strategies for a given site."""
    results = []
    for ct in COOLING_MODELS:
        r = model_cooling_strategy(it_load_mw, "4A", ct)
        results.append(r)

    results.sort(key=lambda x: x["pue"])

    return {
        "it_load_mw": it_load_mw,
        "location": {"lat": lat, "lon": lon},
        "strategies": results,
        "recommended": results[0]["cooling_type"],
        "recommendation_reason": f"Lowest PUE ({results[0]['pue']}) — {results[0]['description']}",
    }


def water_budget(it_load_mw: float, cooling_type: str, stress_data: dict) -> dict[str, Any]:
    """Assess whether local water supply can sustain the DC."""
    strategy = model_cooling_strategy(it_load_mw, "4A", cooling_type)
    annual_m3 = strategy["annual_water_m3"]

    # UK average water company supply: ~150 L/person/day, ~55m3/person/year
    # Typical local abstraction for 50k population: ~2.75M m3/year
    local_supply_m3 = 2_750_000
    consumption_pct = (annual_m3 / local_supply_m3 * 100) if local_supply_m3 > 0 else 0

    sustainable = consumption_pct < 5 or annual_m3 == 0
    mitigations = []
    if not sustainable:
        mitigations.extend(["Switch to air-cooled or hybrid cooling", "Install rainwater harvesting", "Use greywater recycling", "Negotiate dedicated water supply agreement"])
    if stress_data.get("stress_level") == "High":
        mitigations.append("Consider relocating to lower water-stress region")

    return {
        "sustainable": sustainable,
        "annual_consumption_m3": round(annual_m3),
        "consumption_vs_local_pct": round(consumption_pct, 2),
        "stress_level": stress_data.get("stress_level", "Unknown"),
        "mitigations": mitigations,
        "verdict": "GO" if sustainable else "CAUTION",
    }
