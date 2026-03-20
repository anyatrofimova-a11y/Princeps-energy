"""
dc_water_stress.py — Water stress assessment for DC site selection.

Uses EA CAMS catchment data to classify water availability and
inform cooling strategy choice (air-cooled mandatory in stressed catchments).
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.dc_water")

# ---------------------------------------------------------------------------
# UK catchment water availability status (EA CAMS simplified)
# Maps approximate regions to water stress levels
# ---------------------------------------------------------------------------
UK_WATER_STRESS: dict[str, dict[str, Any]] = {
    "Thames": {"status": "serious_stress", "score": 15, "lat": 51.5, "lon": -0.5},
    "Anglian": {"status": "serious_stress", "score": 20, "lat": 52.3, "lon": 0.5},
    "South East": {"status": "serious_stress", "score": 15, "lat": 51.1, "lon": 0.3},
    "Southern": {"status": "stress", "score": 30, "lat": 50.9, "lon": -1.0},
    "Severn Trent": {"status": "moderate_stress", "score": 50, "lat": 52.5, "lon": -1.8},
    "Wessex": {"status": "moderate_stress", "score": 50, "lat": 51.0, "lon": -2.5},
    "Yorkshire": {"status": "available", "score": 70, "lat": 53.8, "lon": -1.5},
    "North West": {"status": "available", "score": 80, "lat": 54.0, "lon": -2.7},
    "Northumbrian": {"status": "available", "score": 85, "lat": 55.0, "lon": -1.5},
    "Scottish": {"status": "available", "score": 90, "lat": 56.5, "lon": -4.0},
    "Welsh": {"status": "available", "score": 75, "lat": 52.0, "lon": -3.5},
    "South West": {"status": "moderate_stress", "score": 55, "lat": 50.7, "lon": -3.5},
}

# Cooling technology water consumption (m3 per MWh of IT load)
COOLING_WATER_RATES: dict[str, float] = {
    "evaporative": 1.8,
    "hybrid": 0.6,
    "air_cooled": 0.0,
    "liquid_immersion": 0.05,
}

# EA abstraction licence base cost per m3/yr
EA_ABSTRACTION_RATE_GBP = 0.027

# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Catchment matching
# ---------------------------------------------------------------------------

def _find_nearest_catchment(lat: float, lon: float) -> tuple[str, dict[str, Any]]:
    """
    Match a coordinate to the nearest EA CAMS catchment using haversine.

    Returns (catchment_name, catchment_dict).
    """
    best_name: str = "Thames"
    best_data: dict[str, Any] = UK_WATER_STRESS["Thames"]
    best_dist: float = float("inf")

    for name, data in UK_WATER_STRESS.items():
        d = _haversine(lat, lon, data["lat"], data["lon"])
        if d < best_dist:
            best_dist = d
            best_name = name
            best_data = data

    log.debug("Nearest catchment to (%.4f, %.4f): %s (%.1f km)",
              lat, lon, best_name, best_dist)
    return best_name, best_data


# ---------------------------------------------------------------------------
# Cooling recommendation
# ---------------------------------------------------------------------------

def _cooling_recommendation(status: str) -> str:
    """Determine recommended cooling strategy from water stress status."""
    if status == "serious_stress":
        return "air_cooled_mandatory"
    if status == "stress":
        return "hybrid_preferred"
    if status == "moderate_stress":
        return "hybrid_preferred"
    return "evaporative_available"


def _abstraction_risk(status: str) -> str:
    """Map water stress status to abstraction licence risk."""
    if status == "serious_stress":
        return "high"
    if status in ("stress", "moderate_stress"):
        return "medium"
    return "low"


def _annual_water_limit(status: str, capacity_mw: float) -> float | None:
    """
    Estimate annual water abstraction limit in m3.

    Returns None for serious-stress catchments (abstraction not permitted
    for new large consumptive uses).
    """
    if status == "serious_stress":
        return None
    if status == "stress":
        return 20_000 * capacity_mw
    if status == "moderate_stress":
        return 35_000 * capacity_mw
    # Available
    return 50_000 * capacity_mw


def _google_water_positive(status: str, cooling: str) -> bool:
    """
    Assess Google 2030 water-positive compatibility.

    A site is compatible if:
    - Water is available in the catchment, OR
    - The cooling strategy is air-cooled (zero consumptive use).
    """
    if status == "available":
        return True
    if "air_cooled" in cooling:
        return True
    return False


# ---------------------------------------------------------------------------
# Water demand estimation
# ---------------------------------------------------------------------------

def _estimate_annual_water_m3(
    capacity_mw: float,
    cooling: str,
    pue: float = 1.3,
) -> float:
    """
    Estimate annual water consumption in m3 for the DC.

    capacity_mw: IT load in MW
    pue: Power Usage Effectiveness
    cooling: one of COOLING_WATER_RATES keys or recommendation string
    """
    # Normalise cooling string
    if "air_cooled" in cooling:
        tech = "air_cooled"
    elif "hybrid" in cooling:
        tech = "hybrid"
    elif "immersion" in cooling:
        tech = "liquid_immersion"
    else:
        tech = "evaporative"

    rate = COOLING_WATER_RATES.get(tech, 1.8)
    annual_mwh = capacity_mw * 8760 * pue
    return round(rate * annual_mwh, 0)


# ---------------------------------------------------------------------------
# EA CAMS API fetch (best-effort)
# ---------------------------------------------------------------------------

async def _fetch_ea_cams_live(lat: float, lon: float) -> dict[str, Any] | None:
    """
    Attempt to fetch live EA water-resource status from the Environment Agency
    Catchment Data Explorer API.  Returns None on failure (we fall back to
    the static lookup table).
    """
    url = "https://environment.data.gov.uk/catchment-planning/so/WaterBody"
    params = {"lat": lat, "long": lon, "dist": 5}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    wb = items[0]
                    return {
                        "water_body": wb.get("label", "Unknown"),
                        "status": wb.get("currentStatus", {}).get("label", "Unknown"),
                        "catchment": wb.get("catchment", {}).get("label", "Unknown"),
                    }
    except Exception as exc:
        log.debug("EA CAMS API call failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Main assessment
# ---------------------------------------------------------------------------

async def assess_water_stress(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 10,
) -> dict[str, Any]:
    """
    Assess water stress at a proposed data-centre site.

    Parameters
    ----------
    conn : asyncpg.Connection
        Database connection (used for future DB-backed catchment data).
    lat, lon : float
        Site coordinates in WGS84.
    capacity_mw : float
        Proposed IT load in MW.

    Returns
    -------
    dict with keys:
        water_score           : 0-100  (higher = more water available)
        catchment             : str    (nearest EA CAMS catchment name)
        status                : str    (available / moderate_stress / stress / serious_stress)
        cooling_recommendation: str    (air_cooled_mandatory / hybrid_preferred / evaporative_available)
        annual_water_limit_m3 : float | None
        google_water_positive : bool   (compatible with Google water-positive 2030 pledge)
        abstraction_risk      : str    (high / medium / low)
        annual_water_demand_m3: float  (estimated demand under recommended cooling)
        abstraction_cost_gbp  : float  (EA licence cost estimate)
        ea_live               : dict | None  (live EA data if available)
        cooling_options       : list[dict]   (all cooling techs with water demand)
    """
    log.info("Assessing water stress at (%.4f, %.4f) for %s MW DC",
             lat, lon, capacity_mw)

    # Match to nearest catchment
    catchment_name, catchment_data = _find_nearest_catchment(lat, lon)
    status = catchment_data["status"]
    score = catchment_data["score"]

    # Cooling recommendation
    cooling = _cooling_recommendation(status)

    # Water limits & risks
    limit = _annual_water_limit(status, capacity_mw)
    risk = _abstraction_risk(status)
    water_positive = _google_water_positive(status, cooling)

    # Water demand under recommended cooling
    demand = _estimate_annual_water_m3(capacity_mw, cooling)
    abstraction_cost = round(demand * EA_ABSTRACTION_RATE_GBP, 2) if demand > 0 else 0.0

    # Check if demand exceeds limit
    demand_exceeds_limit = limit is not None and demand > limit

    # Try live EA data (non-blocking)
    ea_live = await _fetch_ea_cams_live(lat, lon)

    # Build cooling options comparison
    cooling_options = []
    for tech, rate in COOLING_WATER_RATES.items():
        tech_demand = _estimate_annual_water_m3(capacity_mw, tech)
        feasible = True
        if limit is not None and tech_demand > limit:
            feasible = False
        if limit is None and tech_demand > 0:
            feasible = False
        cooling_options.append({
            "technology": tech,
            "annual_water_m3": tech_demand,
            "water_rate_m3_per_mwh": rate,
            "feasible_in_catchment": feasible,
            "abstraction_cost_gbp": round(tech_demand * EA_ABSTRACTION_RATE_GBP, 2),
        })

    # Adjust score if demand exceeds limit
    if demand_exceeds_limit:
        score = max(5, score - 15)

    result: dict[str, Any] = {
        "water_score": score,
        "catchment": catchment_name,
        "status": status,
        "cooling_recommendation": cooling,
        "annual_water_limit_m3": limit,
        "google_water_positive": water_positive,
        "abstraction_risk": risk,
        "annual_water_demand_m3": demand,
        "abstraction_cost_gbp": abstraction_cost,
        "demand_exceeds_limit": demand_exceeds_limit,
        "ea_live": ea_live,
        "cooling_options": cooling_options,
    }

    log.info("Water stress result: catchment=%s status=%s score=%d cooling=%s",
             catchment_name, status, score, cooling)
    return result
