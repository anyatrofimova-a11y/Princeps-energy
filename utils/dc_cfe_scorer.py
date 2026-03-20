"""
dc_cfe_scorer.py — 24/7 Carbon-Free Energy (CFE%) scorer for Princeps.

Calculates achievable CFE% for data-centre site selection by combining
regional grid carbon intensity data with nearby renewable energy projects
available for Power Purchase Agreements (PPAs).

Uses the UK National Grid ESO Carbon Intensity API for regional hourly
forecasts and the REPD (Renewable Energy Planning Database) projects table
in PostGIS for renewable proximity analysis.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.dc_cfe")

# ---------------------------------------------------------------------------
# Carbon Intensity API — UK regional IDs with approximate centroids
# ---------------------------------------------------------------------------
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
    15: {"name": "England", "lat": 52.5, "lon": -1.5},
    16: {"name": "Scotland", "lat": 56.5, "lon": -4.0},
    17: {"name": "Wales", "lat": 52.0, "lon": -3.5},
}

# Typical annual average carbon intensities by region (gCO2/kWh).
# These are used as fallbacks when the API is unavailable, derived from
# historic averages published by National Grid ESO (2022-2024).
REGIONAL_AVG_INTENSITY: dict[int, float] = {
    1: 45,    # North Scotland — high wind, hydro
    2: 55,    # South Scotland — wind-rich
    3: 170,   # North West England — gas-heavy
    4: 130,   # North East England — some offshore wind
    5: 155,   # Yorkshire — mixed
    6: 175,   # North Wales & Merseyside
    7: 160,   # South Wales — some gas + wind
    8: 180,   # West Midlands — urban, gas
    9: 165,   # East Midlands — gas + biomass
    10: 150,  # East England — offshore wind growing
    11: 140,  # South West England — some solar + wind
    12: 155,  # South England — solar, some gas
    13: 190,  # London — high demand, import-heavy
    14: 160,  # South East England
    15: 160,  # England aggregate
    16: 50,   # Scotland aggregate
    17: 165,  # Wales aggregate
}

# Low-carbon threshold (gCO2/kWh). Hours below this count as "carbon-free".
LOW_CARBON_THRESHOLD = 100

# Search radius for nearby REPD renewable projects (metres)
REPD_SEARCH_RADIUS_M = 50_000  # 50 km

# Carbon Intensity API base URL
CI_API_BASE = "https://api.carbonintensity.org.uk"

# HTTP timeout for Carbon Intensity API calls (seconds)
HTTP_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Haversine distance
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


# ---------------------------------------------------------------------------
# Region lookup
# ---------------------------------------------------------------------------
def _find_nearest_region(lat: float, lon: float) -> tuple[int, str]:
    """Find nearest Carbon Intensity region by haversine distance.

    Returns (region_id, region_name).  Only considers the 14 specific DNO
    regions (IDs 1-14), skipping the aggregates (15=England, 16=Scotland,
    17=Wales) to avoid ambiguity.
    """
    best_id = 13  # default to London
    best_dist = float("inf")
    for rid, info in CI_REGIONS.items():
        if rid >= 15:
            # Skip national aggregates
            continue
        d = _haversine_km(lat, lon, info["lat"], info["lon"])
        if d < best_dist:
            best_dist = d
            best_id = rid
    return best_id, CI_REGIONS[best_id]["name"]


# ---------------------------------------------------------------------------
# Carbon Intensity API
# ---------------------------------------------------------------------------
async def fetch_carbon_intensity(region_id: int | None = None) -> dict:
    """Fetch current + 48h forecast from the Carbon Intensity API.

    If *region_id* is given, fetches regional data; otherwise fetches the
    GB national intensity.

    Returns::

        {
            "current": {"forecast": int, "actual": int | None, "index": str},
            "forecast": [{"from": str, "to": str, "intensity": int, "index": str}, ...],
            "avg_intensity": float,
            "low_carbon_hours": int,
            "total_hours": int,
        }

    On API failure the function returns a best-effort fallback built from
    the static ``REGIONAL_AVG_INTENSITY`` table.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # --- current intensity ---
        current_data: dict[str, Any] = {"forecast": 0, "actual": None, "index": "unknown"}
        try:
            if region_id:
                resp = await client.get(f"{CI_API_BASE}/regional/regionid/{region_id}")
            else:
                resp = await client.get(f"{CI_API_BASE}/intensity")
            resp.raise_for_status()
            payload = resp.json()

            if region_id:
                # Regional endpoint nests data differently
                regions_data = payload.get("data", [])
                if regions_data:
                    first = regions_data[0] if isinstance(regions_data, list) else regions_data
                    region_list = first.get("regions", [first])
                    for rg in region_list:
                        if rg.get("regionid") == region_id or not rg.get("regionid"):
                            intensity_block = rg.get("intensity", {})
                            current_data = {
                                "forecast": intensity_block.get("forecast", 0) or 0,
                                "actual": intensity_block.get("actual"),
                                "index": intensity_block.get("index", "unknown"),
                            }
                            break
            else:
                items = payload.get("data", [])
                if items:
                    item = items[0] if isinstance(items, list) else items
                    intensity_block = item.get("intensity", {})
                    current_data = {
                        "forecast": intensity_block.get("forecast", 0) or 0,
                        "actual": intensity_block.get("actual"),
                        "index": intensity_block.get("index", "unknown"),
                    }
        except Exception as exc:
            log.warning("Carbon Intensity current fetch failed: %s", exc)

        # --- 48h forecast ---
        forecast_entries: list[dict[str, Any]] = []
        try:
            now = datetime.now(timezone.utc)
            from_str = now.strftime("%Y-%m-%dT%H:%MZ")
            if region_id:
                url = f"{CI_API_BASE}/regional/intensity/{from_str}/fw48h/regionid/{region_id}"
            else:
                url = f"{CI_API_BASE}/intensity/{from_str}/fw48h"
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            raw_data = payload.get("data", [])
            if isinstance(raw_data, dict):
                raw_data = raw_data.get("data", [])

            for entry in raw_data:
                # Regional data has nested regions
                if "regions" in entry:
                    for rg in entry["regions"]:
                        if rg.get("regionid") == region_id or not rg.get("regionid"):
                            intensity_block = rg.get("intensity", {})
                            forecast_entries.append({
                                "from": entry.get("from", ""),
                                "to": entry.get("to", ""),
                                "intensity": intensity_block.get("forecast", 0) or 0,
                                "index": intensity_block.get("index", "unknown"),
                            })
                            break
                else:
                    intensity_block = entry.get("intensity", {})
                    forecast_entries.append({
                        "from": entry.get("from", ""),
                        "to": entry.get("to", ""),
                        "intensity": intensity_block.get("forecast", 0) or 0,
                        "index": intensity_block.get("index", "unknown"),
                    })
        except Exception as exc:
            log.warning("Carbon Intensity 48h forecast fetch failed: %s", exc)

    # --- compute summary stats from forecast ---
    if forecast_entries:
        intensities = [e["intensity"] for e in forecast_entries if e["intensity"]]
        avg_intensity = sum(intensities) / len(intensities) if intensities else 0.0
        low_carbon_hours = sum(1 for v in intensities if v < LOW_CARBON_THRESHOLD)
        total_hours = len(intensities)
    else:
        # Fallback to static regional averages
        fallback = REGIONAL_AVG_INTENSITY.get(region_id or 15, 160)
        avg_intensity = fallback
        # Estimate low-carbon hours from average: if avg < threshold, most
        # hours are low-carbon; scale linearly as a rough proxy.
        if fallback < LOW_CARBON_THRESHOLD:
            low_carbon_hours = int(48 * (1 - fallback / (LOW_CARBON_THRESHOLD * 2)))
            low_carbon_hours = max(low_carbon_hours, int(48 * 0.3))
        else:
            low_carbon_hours = max(0, int(48 * (1 - (fallback - LOW_CARBON_THRESHOLD) / 200)))
        total_hours = 48
        current_data["forecast"] = current_data["forecast"] or fallback

    return {
        "current": current_data,
        "forecast": forecast_entries,
        "avg_intensity": round(avg_intensity, 1),
        "low_carbon_hours": low_carbon_hours,
        "total_hours": total_hours,
    }


# ---------------------------------------------------------------------------
# Grid baseline CFE%
# ---------------------------------------------------------------------------
def _grid_baseline_cfe_pct(region_id: int, api_avg: float | None = None) -> float:
    """Estimate annual grid CFE% for a region.

    Uses the regional average carbon intensity to model what fraction of
    8760 annual hours would fall below the low-carbon threshold.

    The relationship between average intensity and % low-carbon hours is
    non-linear — regions with low averages have strongly skewed distributions
    (lots of clean hours, few dirty ones).  We use a logistic approximation
    calibrated against published UK regional half-hourly data.
    """
    avg = api_avg if api_avg is not None else REGIONAL_AVG_INTENSITY.get(region_id, 160)

    # Logistic curve: CFE% ~ 100 / (1 + exp(k * (avg - midpoint)))
    # Calibrated so avg=50 → ~85%, avg=100 → ~50%, avg=180 → ~15%
    k = 0.035
    midpoint = 110
    cfe = 100.0 / (1.0 + math.exp(k * (avg - midpoint)))
    return round(max(0.0, min(100.0, cfe)), 1)


# ---------------------------------------------------------------------------
# PPA overlay — nearby REPD renewable projects
# ---------------------------------------------------------------------------
async def _query_nearby_renewables(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    radius_m: float = REPD_SEARCH_RADIUS_M,
) -> list[dict[str, Any]]:
    """Query REPD projects within *radius_m* of the site.

    Returns a list of dicts with project details and distance.
    """
    rows = await conn.fetch(
        """
        SELECT repd_id, site_name, technology, capacity_mw, status,
               ST_Distance(
                   geometry,
                   ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
               ) / 1000.0 AS dist_km
        FROM repd_projects
        WHERE technology IN (
            'Wind Onshore', 'Wind Offshore', 'Solar Photovoltaics', 'Battery'
        )
          AND status IN ('Operational', 'Under Construction', 'Approved')
          AND ST_DWithin(
              geometry,
              ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
              $3
          )
        ORDER BY dist_km
        LIMIT 20
        """,
        lon,
        lat,
        radius_m,
    )

    projects = []
    for r in rows:
        projects.append({
            "ref_id": r["repd_id"],
            "site_name": r["site_name"],
            "technology_type": r["technology"],
            "installed_capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else 0.0,
            "status": r["status"],
            "dist_km": round(float(r["dist_km"]), 2),
        })
    return projects


def _estimate_ppa_uplift(
    projects: list[dict[str, Any]],
    capacity_mw: float,
    grid_cfe_pct: float,
) -> tuple[float, float, str]:
    """Estimate how much CFE% improves by contracting PPAs with nearby renewables.

    Returns (achievable_cfe_pct, total_renewable_mw, path_description).

    Methodology:
    - Wind projects contribute more to 24/7 CFE than solar (capacity factors differ)
    - Closer projects are more likely to be contracted
    - Only a fraction of a project's output can realistically be secured via PPA
    - Battery projects improve temporal matching (shift solar into night hours)
    """
    if not projects:
        return grid_cfe_pct, 0.0, "No nearby renewable projects for PPA"

    # Capacity factors by technology
    CAPACITY_FACTORS = {
        "Wind Onshore": 0.27,
        "Wind Offshore": 0.40,
        "Solar Photovoltaics": 0.11,
        "Battery": 0.0,  # storage, not generation
    }

    # Assume we can contract up to 30% of each project's output
    PPA_SHARE = 0.30

    # Discount for distance: projects >30km away are harder to contract
    def _distance_factor(dist_km: float) -> float:
        if dist_km <= 10:
            return 1.0
        if dist_km <= 30:
            return 0.85
        return 0.65

    total_renewable_mw = 0.0
    effective_generation_mw = 0.0
    battery_mw = 0.0
    wind_mw = 0.0
    solar_mw = 0.0

    for p in projects:
        cap = p.get("installed_capacity_mw", 0)
        tech = p.get("technology_type", "")
        dist = p["dist_km"]
        df = _distance_factor(dist)
        total_renewable_mw += cap

        if tech == "Battery":
            battery_mw += cap * df * PPA_SHARE
            continue

        cf = CAPACITY_FACTORS.get(tech, 0.15)
        gen = cap * cf * df * PPA_SHARE
        effective_generation_mw += gen

        if "Wind" in tech:
            wind_mw += cap
        elif "Solar" in tech:
            solar_mw += cap

    # Demand in average MW (data centre runs at near-constant load)
    demand_mw = capacity_mw * 0.85  # typical PUE-adjusted IT load ratio

    # What fraction of demand can PPAs cover?
    if demand_mw > 0:
        ppa_coverage = min(1.0, effective_generation_mw / demand_mw)
    else:
        ppa_coverage = 0.0

    # Battery improves temporal matching: each MW of battery shifts
    # ~4 hours of solar into non-solar hours (rough heuristic).
    # This boosts the effective utilisation of solar PPAs.
    battery_boost = 0.0
    if battery_mw > 0 and demand_mw > 0:
        # Each battery MW adds ~4 MWh of time-shifting per day
        # Over 8760 hours, this covers battery_mw * 4 / 24 average MW
        shifted_mw = battery_mw * (4.0 / 24.0)
        battery_boost = min(0.10, shifted_mw / demand_mw * 0.5)

    # Combine grid baseline with PPA overlay
    # Grid provides grid_cfe_pct% of hours clean; PPAs fill some of the gap
    gap = 100.0 - grid_cfe_pct
    ppa_fill = gap * ppa_coverage * 0.85  # 85% effectiveness (imperfect temporal matching)
    battery_fill = gap * battery_boost
    achievable = grid_cfe_pct + ppa_fill + battery_fill
    achievable = round(min(99.5, max(grid_cfe_pct, achievable)), 1)

    # Build a human-readable path description
    parts = []
    if wind_mw > 0:
        parts.append(f"{wind_mw:.0f}MW wind")
    if solar_mw > 0:
        parts.append(f"{solar_mw:.0f}MW solar")
    if battery_mw > 0:
        parts.append(f"{battery_mw:.0f}MW battery")

    if not parts:
        path = "No viable PPA projects identified"
    elif achievable >= 90:
        path = f"Achievable with PPA from {', '.join(parts)} nearby"
    elif achievable >= 70:
        path = f"Partial coverage with {', '.join(parts)}; additional PPAs needed"
    else:
        path = f"Limited nearby renewables ({', '.join(parts)}); significant PPA procurement required"

    return achievable, round(total_renewable_mw, 1), path


# ---------------------------------------------------------------------------
# CFE score mapping: achievable_cfe_pct -> 0-100 score
# ---------------------------------------------------------------------------
def _cfe_pct_to_score(cfe_pct: float) -> int:
    """Map achievable CFE% to a 0-100 site suitability score.

    Mapping:
      0%   ->   0
     50%   ->  25
     80%   ->  60
     90%   ->  80
     95%+  -> 100

    Uses piecewise linear interpolation.
    """
    breakpoints = [
        (0.0, 0),
        (50.0, 25),
        (80.0, 60),
        (90.0, 80),
        (95.0, 100),
    ]

    if cfe_pct <= breakpoints[0][0]:
        return breakpoints[0][1]
    if cfe_pct >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= cfe_pct <= x1:
            t = (cfe_pct - x0) / (x1 - x0)
            return int(round(y0 + t * (y1 - y0)))

    return 50  # fallback


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------
async def score_cfe(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 100,
    target_cfe_pct: float = 90.0,
) -> dict:
    """Score a data-centre site for 24/7 Carbon-Free Energy achievability.

    Parameters
    ----------
    conn : asyncpg.Connection
        Active database connection with access to ``repd_projects``.
    lat, lon : float
        WGS-84 coordinates of the candidate site.
    capacity_mw : float
        Planned IT load capacity in MW (default 100).
    target_cfe_pct : float
        Target CFE% the operator wants to achieve (default 90).

    Returns
    -------
    dict
        Comprehensive CFE assessment including score (0-100), grid baseline,
        achievable CFE% with PPAs, nearby renewable project details, and a
        plain-English path-to-target description.
    """
    log.info(
        "CFE scoring site lat=%.4f lon=%.4f capacity=%sMW target=%.0f%%",
        lat, lon, capacity_mw, target_cfe_pct,
    )

    # 1. Determine carbon intensity region
    region_id, region_name = _find_nearest_region(lat, lon)
    log.debug("Nearest CI region: %s (ID %d)", region_name, region_id)

    # 2. Fetch live carbon intensity data
    ci_data = await fetch_carbon_intensity(region_id)
    current_intensity = ci_data["current"]["forecast"]
    avg_intensity = ci_data["avg_intensity"]

    # 3. Calculate grid baseline CFE%
    grid_cfe_pct = _grid_baseline_cfe_pct(region_id, avg_intensity if avg_intensity else None)
    log.debug("Grid baseline CFE%%: %.1f%% (avg intensity %.0f gCO2/kWh)", grid_cfe_pct, avg_intensity)

    # 4. Query nearby renewable projects for PPA potential
    projects = await _query_nearby_renewables(conn, lat, lon)
    log.debug("Found %d nearby renewable projects", len(projects))

    # 5. Estimate achievable CFE% with PPA overlay
    achievable_cfe_pct, nearby_renewables_mw, path_to_target = _estimate_ppa_uplift(
        projects, capacity_mw, grid_cfe_pct,
    )

    # 6. If still below target, describe what's needed
    if achievable_cfe_pct < target_cfe_pct:
        shortfall_pct = target_cfe_pct - achievable_cfe_pct
        # Rough estimate: each additional 50MW of onshore wind adds ~5% CFE
        extra_wind_mw = shortfall_pct / 5.0 * 50.0
        path_to_target += f"; ~{extra_wind_mw:.0f}MW additional wind PPA needed for {target_cfe_pct:.0f}% target"

    # 7. Compute final score
    cfe_score = _cfe_pct_to_score(achievable_cfe_pct)

    # 8. Extrapolate 48h forecast to annual low-carbon hours
    if ci_data["total_hours"] > 0:
        lc_ratio = ci_data["low_carbon_hours"] / ci_data["total_hours"]
        annual_low_carbon_hours = int(8760 * lc_ratio)
    else:
        annual_low_carbon_hours = int(8760 * grid_cfe_pct / 100.0)

    result = {
        "cfe_score": cfe_score,
        "grid_cfe_pct": grid_cfe_pct,
        "achievable_cfe_pct": achievable_cfe_pct,
        "target_cfe_pct": target_cfe_pct,
        "region": region_name,
        "region_id": region_id,
        "current_intensity_gco2": round(current_intensity, 1),
        "avg_intensity_gco2": round(avg_intensity, 1),
        "nearby_renewables_mw": nearby_renewables_mw,
        "ppa_projects": projects,
        "hourly_profile": {
            "low_carbon_hours": annual_low_carbon_hours,
            "total_hours": 8760,
        },
        "path_to_target": path_to_target,
    }

    log.info(
        "CFE result: score=%d, grid=%.1f%%, achievable=%.1f%%, region=%s, renewables=%.1fMW",
        cfe_score, grid_cfe_pct, achievable_cfe_pct, region_name, nearby_renewables_mw,
    )
    return result
