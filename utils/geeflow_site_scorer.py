"""
GeeFlow Site Scorer — composite suitability scoring (0-100) for solar sites.

Combines satellite Earth observation data with existing grid + planning data
to produce a GO / CAUTION / NO-GO recommendation for tender evaluation.

Scoring breakdown:
  Terrain      (0-25): slope, aspect, elevation
  Land use     (0-25): developable area, class suitability
  Solar resource (0-25): annual GHI relative to UK range
  Grid access  (0-15): headroom + substation proximity
  Planning     (0-10): historical planning success density
"""

from __future__ import annotations
from typing import Any


def score_terrain(terrain_data: dict | None) -> dict:
    """Score terrain suitability (0-25)."""
    if not terrain_data or terrain_data.get("error"):
        return {"score": 0, "max": 25, "notes": "No terrain data available"}

    score = 25.0
    notes = []

    # Slope penalty: >15 deg = severe, >10 deg = moderate
    slope_mean = terrain_data.get("slope", {}).get("mean_deg", 0)
    slope_p90 = terrain_data.get("slope", {}).get("p90_deg", 0)
    if slope_mean > 15:
        score -= 15
        notes.append(f"Steep terrain (mean {slope_mean}°)")
    elif slope_mean > 10:
        score -= 8
        notes.append(f"Moderate slope ({slope_mean}°)")
    elif slope_mean > 5:
        score -= 3
        notes.append(f"Gentle slope ({slope_mean}°)")

    if slope_p90 > 20:
        score -= 5
        notes.append(f"Extreme slope patches (p90={slope_p90}°)")

    # Aspect: reward south-facing
    south_pct = terrain_data.get("aspect", {}).get("south_facing_pct", 0)
    if south_pct > 50:
        notes.append(f"Excellent aspect ({south_pct}% south-facing)")
    elif south_pct > 30:
        score -= 3
        notes.append(f"Good aspect ({south_pct}% south-facing)")
    else:
        score -= 8
        notes.append(f"Poor aspect ({south_pct}% south-facing)")

    # Elevation: penalize >500m (UK context — lower solar resource, harder access)
    elev = terrain_data.get("elevation", {}).get("mean_m", 0)
    if elev > 500:
        score -= 5
        notes.append(f"High elevation ({elev}m)")
    elif elev > 300:
        score -= 2
        notes.append(f"Elevated ({elev}m)")

    return {"score": max(0, round(score)), "max": 25, "notes": notes}


def score_land_use(land_use_data: dict | None) -> dict:
    """Score land use suitability (0-25)."""
    if not land_use_data or land_use_data.get("error"):
        return {"score": 0, "max": 25, "notes": "No land use data available"}

    score = 25.0
    notes = []

    dev_pct = land_use_data.get("developable_area_pct", 0)
    class_pcts = land_use_data.get("class_percentages", {})

    # Developable area score
    if dev_pct > 80:
        notes.append(f"Highly developable ({dev_pct}%)")
    elif dev_pct > 50:
        score -= 5
        notes.append(f"Mostly developable ({dev_pct}%)")
    elif dev_pct > 20:
        score -= 12
        notes.append(f"Partially developable ({dev_pct}%)")
    else:
        score -= 20
        notes.append(f"Limited developable area ({dev_pct}%)")

    # Penalty for water/built
    water_pct = class_pcts.get("water", 0)
    built_pct = class_pcts.get("built", 0)
    forest_pct = class_pcts.get("trees", 0)

    if water_pct > 20:
        score -= 5
        notes.append(f"Significant water ({water_pct}%)")
    if built_pct > 30:
        score -= 5
        notes.append(f"Built-up area ({built_pct}%)")
    if forest_pct > 40:
        score -= 3
        notes.append(f"Forested ({forest_pct}%)")

    return {"score": max(0, round(score)), "max": 25, "notes": notes}


def score_solar_resource(solar_data: dict | None) -> dict:
    """Score solar resource quality (0-25). UK GHI range: 900-1150 kWh/m2/yr."""
    if not solar_data or solar_data.get("error"):
        return {"score": 0, "max": 25, "notes": "No solar resource data available"}

    score = 0.0
    notes = []

    annual_ghi = solar_data.get("annual_ghi_kwh_m2", 0)

    # UK range: 900 (north Scotland) to 1150 (south coast)
    uk_min, uk_max = 900, 1150
    if annual_ghi > 0:
        normalised = (annual_ghi - uk_min) / (uk_max - uk_min)
        normalised = max(0, min(1, normalised))
        score = normalised * 25
        notes.append(f"Annual GHI: {annual_ghi} kWh/m²")

        if annual_ghi > 1050:
            notes.append("Above-average solar resource")
        elif annual_ghi > 950:
            notes.append("Average UK solar resource")
        else:
            notes.append("Below-average solar resource")
    else:
        notes.append("GHI data unavailable")

    return {"score": round(score), "max": 25, "notes": notes}


def score_grid_access(grid_data: dict | None) -> dict:
    """Score grid connection access (0-15)."""
    if not grid_data:
        return {"score": 0, "max": 15, "notes": "No grid data available"}

    score = 15.0
    notes = []

    # Substation distance
    dist_km = grid_data.get("distance_km")
    if dist_km is not None:
        if dist_km > 10:
            score -= 10
            notes.append(f"Remote from grid ({dist_km:.1f}km)")
        elif dist_km > 5:
            score -= 5
            notes.append(f"Moderate grid distance ({dist_km:.1f}km)")
        elif dist_km > 2:
            score -= 2
            notes.append(f"Near grid ({dist_km:.1f}km)")
        else:
            notes.append(f"Excellent grid access ({dist_km:.1f}km)")
    else:
        score -= 8

    # Headroom
    headroom_mw = grid_data.get("headroom_mw")
    if headroom_mw is not None:
        if headroom_mw < 1:
            score -= 5
            notes.append(f"Limited headroom ({headroom_mw:.1f}MW)")
        elif headroom_mw < 5:
            score -= 2
            notes.append(f"Moderate headroom ({headroom_mw:.1f}MW)")
        else:
            notes.append(f"Good headroom ({headroom_mw:.1f}MW)")

    return {"score": max(0, round(score)), "max": 15, "notes": notes}


def score_planning(planning_data: dict | None) -> dict:
    """Score planning viability (0-10) based on historical success."""
    if not planning_data:
        return {"score": 5, "max": 10, "notes": "No planning data — neutral score"}

    score = 5.0  # neutral baseline
    notes = []

    success_rate = planning_data.get("approval_rate")
    nearby_count = planning_data.get("nearby_energy_apps", 0)

    if success_rate is not None:
        if success_rate > 0.7:
            score = 10
            notes.append(f"High planning success rate ({success_rate:.0%})")
        elif success_rate > 0.4:
            score = 7
            notes.append(f"Moderate planning success ({success_rate:.0%})")
        else:
            score = 3
            notes.append(f"Low planning success rate ({success_rate:.0%})")

    if nearby_count > 5:
        score = min(10, score + 2)
        notes.append(f"Active energy development area ({nearby_count} nearby apps)")

    return {"score": round(score), "max": 10, "notes": notes}


def score_flood_risk(flood_data: dict | None) -> dict:
    """Score flood risk penalty (0 to -10 deduction)."""
    if not flood_data or flood_data.get("error"):
        return {"penalty": 0, "notes": "No flood data available"}

    risk_level = flood_data.get("risk_level", "LOW")
    occ_pct = flood_data.get("water_occurrence_pct", 0)
    notes = []

    if risk_level == "HIGH":
        penalty = -10
        notes.append(f"HIGH flood risk ({occ_pct}% water occurrence) — severe constraint")
    elif risk_level == "MEDIUM":
        penalty = -5
        notes.append(f"MEDIUM flood risk ({occ_pct}% water occurrence) — mitigation needed")
    else:
        penalty = 0
        notes.append(f"LOW flood risk ({occ_pct}% water occurrence)")

    if flood_data.get("environmental_constraint"):
        notes.append("Environmental constraint flagged — may require EA consent")

    return {"penalty": penalty, "notes": notes}


def compute_site_score(
    terrain_data: dict | None = None,
    land_use_data: dict | None = None,
    solar_data: dict | None = None,
    grid_data: dict | None = None,
    planning_data: dict | None = None,
    flood_data: dict | None = None,
) -> dict:
    """
    Compute composite site suitability score (0-100).

    Returns:
        {
            total_score: int,
            breakdown: { terrain, land_use, solar_resource, grid_access, planning },
            recommendation: "GO" | "CAUTION" | "NO-GO",
            summary: str,
        }
    """
    breakdown = {
        "terrain": score_terrain(terrain_data),
        "land_use": score_land_use(land_use_data),
        "solar_resource": score_solar_resource(solar_data),
        "grid_access": score_grid_access(grid_data),
        "planning": score_planning(planning_data),
    }

    # Flood risk penalty
    flood = score_flood_risk(flood_data)
    breakdown["flood_risk"] = flood

    total = sum(v["score"] for v in breakdown.values() if "score" in v)
    total += flood["penalty"]
    total = max(0, total)

    if total >= 70:
        recommendation = "GO"
        summary = f"Strong candidate site (score {total}/100). Good terrain, land use, and solar resource."
    elif total >= 40:
        recommendation = "CAUTION"
        summary = f"Moderate candidate (score {total}/100). Some constraints identified — review details."
    else:
        recommendation = "NO-GO"
        summary = f"Poor candidate (score {total}/100). Significant constraints across multiple dimensions."

    # Add detail from top concerns
    concerns = []
    for category, data in breakdown.items():
        if data["score"] < data["max"] * 0.4:
            concerns.extend(data.get("notes", [])[:1])
    if concerns:
        summary += " Key concerns: " + "; ".join(concerns[:3]) + "."

    return {
        "total_score": total,
        "max_score": 100,
        "breakdown": breakdown,
        "recommendation": recommendation,
        "summary": summary,
    }


def score_multiple_sites(
    sites: list[dict],
    technology: str = "solar",
) -> list[dict]:
    """
    Score multiple candidate sites for tender comparison.

    Each site dict should have: name, lat, lon, and optionally
    geeflow_data, grid_data, planning_data.

    Returns list sorted by score (highest first).
    """
    scored = []
    for site in sites:
        geeflow = site.get("geeflow_data", {})

        result = compute_site_score(
            terrain_data=geeflow.get("terrain"),
            land_use_data=geeflow.get("land_use"),
            solar_data=geeflow.get("solar_resource"),
            grid_data=site.get("grid_data"),
            planning_data=site.get("planning_data"),
        )

        scored.append({
            "name": site.get("name", "Unknown"),
            "lat": site.get("lat"),
            "lon": site.get("lon"),
            "technology": technology,
            **result,
        })

    scored.sort(key=lambda s: s["total_score"], reverse=True)

    # Add rank
    for i, s in enumerate(scored):
        s["rank"] = i + 1

    return scored
