"""
GeeFlow Planning Analysis — satellite-informed planning viability prediction.

Combines Earth observation data with planning records to predict where
renewable energy projects are likely to succeed.
"""

from __future__ import annotations
from typing import Any


def predict_planning_viability(
    lat: float,
    lon: float,
    geeflow_data: dict | None = None,
    planning_summary: dict | None = None,
) -> dict:
    """
    Predict planning viability based on satellite data + historical patterns.

    Factors:
    - Land use classification (agricultural = good, protected = bad)
    - Distance from built-up areas (buffer zones)
    - Terrain suitability
    - Historical approval patterns in the area
    """
    viability = {"score": 50, "factors": [], "risk_level": "medium"}

    if geeflow_data:
        land_use = geeflow_data.get("land_use", {})
        terrain = geeflow_data.get("terrain", {})
        vegetation = geeflow_data.get("vegetation", {})

        # Land use assessment
        class_pcts = land_use.get("class_percentages", {})
        dev_pct = land_use.get("developable_area_pct", 0)

        if dev_pct > 70:
            viability["score"] += 20
            viability["factors"].append("High developable land coverage supports planning case")
        elif dev_pct > 40:
            viability["score"] += 10
            viability["factors"].append("Moderate developable land — may need landscape assessment")

        built_pct = class_pcts.get("built", 0)
        if built_pct > 40:
            viability["score"] -= 15
            viability["factors"].append("Proximity to built-up areas may trigger residential amenity concerns")
        elif built_pct > 10:
            viability["score"] += 5
            viability["factors"].append("Some built context — grid connection likely nearby")

        trees_pct = class_pcts.get("trees", 0)
        if trees_pct > 30:
            viability["score"] -= 10
            viability["factors"].append("Significant tree coverage — potential ecological sensitivity")

        # Terrain assessment
        slope_mean = terrain.get("slope", {}).get("mean_deg", 0)
        if slope_mean > 10:
            viability["score"] -= 10
            viability["factors"].append("Steep terrain increases visual impact concerns")
        elif slope_mean < 3:
            viability["score"] += 5
            viability["factors"].append("Flat terrain reduces visual impact")

        # Vegetation / ecology
        green_cover = vegetation.get("green_cover_pct", 0)
        if green_cover > 80:
            viability["score"] -= 5
            viability["factors"].append("High green cover — biodiversity net gain assessment needed")

    # Historical planning success
    if planning_summary:
        approval_rate = planning_summary.get("approval_rate")
        if approval_rate is not None:
            if approval_rate > 0.6:
                viability["score"] += 10
                viability["factors"].append(f"Area has good planning approval rate ({approval_rate:.0%})")
            elif approval_rate < 0.3:
                viability["score"] -= 10
                viability["factors"].append(f"Area has low planning approval rate ({approval_rate:.0%})")

    # Clamp and classify
    viability["score"] = max(0, min(100, viability["score"]))
    if viability["score"] >= 65:
        viability["risk_level"] = "low"
        viability["recommendation"] = "Proceed with pre-application — strong indicators"
    elif viability["score"] >= 40:
        viability["risk_level"] = "medium"
        viability["recommendation"] = "Consider pre-application consultation — some risks"
    else:
        viability["risk_level"] = "high"
        viability["recommendation"] = "Significant constraints — detailed assessment required"

    viability["lat"] = lat
    viability["lon"] = lon

    return viability


def detect_land_use_changes(
    change_data: dict | None = None,
) -> dict:
    """
    Analyse land use change data to identify development activity patterns.

    Uses DynamicWorld change detection output from geeflow_runner.
    """
    if not change_data or change_data.get("error"):
        return {"activity": "unknown", "notes": "No change detection data available"}

    changes = change_data.get("changes_pct", {})
    development = change_data.get("development_activity", "low")
    period = change_data.get("period", "unknown")

    analysis = {
        "period": period,
        "development_activity": development,
        "indicators": [],
    }

    built_change = changes.get("built", 0)
    if built_change > 5:
        analysis["indicators"].append(f"Significant urbanisation (+{built_change}% built)")
    elif built_change > 1:
        analysis["indicators"].append(f"Moderate development (+{built_change}% built)")

    crop_change = changes.get("crops", 0)
    grass_change = changes.get("grass", 0)
    if crop_change < -5 or grass_change < -5:
        analysis["indicators"].append("Agricultural land conversion detected")

    trees_change = changes.get("trees", 0)
    if trees_change < -3:
        analysis["indicators"].append(f"Tree loss detected ({trees_change}%)")
    elif trees_change > 3:
        analysis["indicators"].append(f"Reforestation detected (+{trees_change}%)")

    bare_change = changes.get("bare", 0)
    if bare_change > 3:
        analysis["indicators"].append("Increased bare land — possible site preparation")

    # Planning opportunity assessment
    if development == "high":
        analysis["opportunity"] = "Active development area — planning precedent likely exists"
    elif development == "moderate":
        analysis["opportunity"] = "Some development activity — research local plan policies"
    else:
        analysis["opportunity"] = "Stable area — check if local plan supports renewable energy"

    return analysis
