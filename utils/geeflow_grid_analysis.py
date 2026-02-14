"""
GeeFlow Grid Analysis — satellite-enhanced grid intelligence.

Cross-references remote sensing data with NGED CIM / OSM grid data
to identify underserved areas and connection bottlenecks.
"""

from __future__ import annotations
from typing import Any


def identify_underserved_areas(
    grid_opportunities: list[dict] | None = None,
    geeflow_data: dict | None = None,
) -> dict:
    """
    Cross-reference grid headroom with satellite demand indicators.

    Identifies areas where:
    - Grid has capacity (headroom > threshold)
    - Land is suitable for embedded generation (developable, solar-friendly)
    - Development activity is growing (demand pressure)
    """
    if not grid_opportunities:
        return {"areas": [], "summary": "No grid opportunity data available"}

    areas = []
    for opp in grid_opportunities:
        area = {
            "substation": opp.get("name", "Unknown"),
            "headroom_mw": opp.get("headroom_mw", 0),
            "distance_km": opp.get("distance_km"),
            "voltage_kv": opp.get("voltage_kv"),
            "suitability": "unknown",
        }

        # If we have satellite data for this area, enrich
        if geeflow_data:
            land_use = geeflow_data.get("land_use", {})
            dev_pct = land_use.get("developable_area_pct", 0)
            terrain = geeflow_data.get("terrain", {})
            slope_mean = terrain.get("slope", {}).get("mean_deg", 0)

            if dev_pct > 60 and slope_mean < 10:
                area["suitability"] = "high"
                area["notes"] = f"Good land ({dev_pct}% developable, {slope_mean}° slope)"
            elif dev_pct > 30:
                area["suitability"] = "moderate"
                area["notes"] = f"Some suitable land ({dev_pct}% developable)"
            else:
                area["suitability"] = "low"
                area["notes"] = f"Limited suitable land ({dev_pct}% developable)"

        areas.append(area)

    # Sort by combined headroom + suitability
    suitability_rank = {"high": 3, "moderate": 2, "low": 1, "unknown": 0}
    areas.sort(key=lambda a: (
        suitability_rank.get(a["suitability"], 0),
        a.get("headroom_mw", 0),
    ), reverse=True)

    high_count = sum(1 for a in areas if a["suitability"] == "high")

    return {
        "areas": areas[:20],
        "total_assessed": len(areas),
        "high_suitability_count": high_count,
        "summary": (
            f"Assessed {len(areas)} substations. "
            f"{high_count} have high suitability for embedded generation."
        ),
    }


def grid_bottleneck_analysis(
    constrained_substations: list[dict] | None = None,
    geeflow_data: dict | None = None,
    headroom_threshold_mw: float = 2.0,
) -> dict:
    """
    For constrained substations (<threshold MW headroom), assess surrounding
    land suitability for embedded generation that could relieve constraints.

    This helps identify where battery storage or demand-side response
    could be valuable.
    """
    if not constrained_substations:
        return {"bottlenecks": [], "summary": "No constrained substations provided"}

    bottlenecks = []
    for sub in constrained_substations:
        headroom = sub.get("headroom_mw", 0)
        if headroom > headroom_threshold_mw:
            continue

        bottleneck = {
            "substation": sub.get("name", "Unknown"),
            "headroom_mw": headroom,
            "voltage_kv": sub.get("voltage_kv"),
            "constraint_severity": (
                "critical" if headroom < 0.5 else
                "severe" if headroom < 1 else
                "moderate"
            ),
            "opportunity": None,
        }

        # Assess opportunity for embedded generation / storage
        if geeflow_data:
            land_use = geeflow_data.get("land_use", {})
            dev_pct = land_use.get("developable_area_pct", 0)

            if dev_pct > 50 and headroom < 1:
                bottleneck["opportunity"] = (
                    "Battery storage opportunity — constrained substation with "
                    f"developable land ({dev_pct}%). Storage could provide "
                    "peak shaving and deferral value."
                )
            elif dev_pct > 30:
                bottleneck["opportunity"] = (
                    "Demand-side response potential — moderate land availability "
                    "near constrained substation."
                )
            else:
                bottleneck["opportunity"] = (
                    "Limited land for new generation — consider network reinforcement."
                )

        bottlenecks.append(bottleneck)

    critical_count = sum(1 for b in bottlenecks if b["constraint_severity"] == "critical")

    return {
        "bottlenecks": bottlenecks[:20],
        "total_assessed": len(bottlenecks),
        "critical_count": critical_count,
        "summary": (
            f"Identified {len(bottlenecks)} constrained substations "
            f"({critical_count} critical). "
            "Battery storage or demand-side response may provide value."
        ),
    }


def enhanced_grid_context(
    base_grid_context: dict | None = None,
    geeflow_data: dict | None = None,
) -> dict:
    """
    Merge standard grid context with satellite-derived data for
    a comprehensive grid connection assessment.
    """
    if not base_grid_context:
        base_grid_context = {}

    enhanced = dict(base_grid_context)

    if geeflow_data:
        # Add satellite-derived insights
        satellite_insights = []

        land_use = geeflow_data.get("land_use", {})
        dev_pct = land_use.get("developable_area_pct", 0)
        if dev_pct > 0:
            satellite_insights.append(
                f"Satellite land analysis: {dev_pct}% developable area within radius"
            )

        terrain = geeflow_data.get("terrain", {})
        slope_mean = terrain.get("slope", {}).get("mean_deg", 0)
        if slope_mean > 0:
            satellite_insights.append(
                f"Terrain: mean slope {slope_mean}°, "
                f"{terrain.get('aspect', {}).get('south_facing_pct', 0)}% south-facing"
            )

        solar = geeflow_data.get("solar_resource", {})
        ghi = solar.get("annual_ghi_kwh_m2", 0)
        if ghi > 0:
            satellite_insights.append(f"Solar resource: {ghi} kWh/m²/yr (ERA5)")

        enhanced["satellite_insights"] = satellite_insights
        enhanced["satellite_data_available"] = True
    else:
        enhanced["satellite_data_available"] = False

    return enhanced
