"""
Parametric construction schedule and traffic model for energy projects.

UK solar farm construction phases (standard sequence):
1. Site clearance & access road (2-4 weeks)
2. Cable trenching & foundations (3-6 weeks)
3. Pile driving for mounting structures (4-8 weeks)
4. Racking & panel installation (6-12 weeks)
5. Stringing & electrical (4-6 weeks)
6. Substation & grid connection (4-8 weeks)
7. Commissioning & energisation (2-4 weeks)

Traffic: ~10 HGV deliveries per MW capacity
Peak workforce: ~4 workers per MW during peak phase
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.construction")

# ─── Technology parameters ───────────────────────────────────────────────────

# Phase templates: (name, weeks_per_mw_min, weeks_per_mw_max, base_weeks_min, base_weeks_max,
#                   workers_per_mw, hgvs_per_mw, overlap_pct)
# overlap_pct: how much this phase overlaps with the previous (0=sequential, 0.5=50% overlap)

SOLAR_PHASES = [
    {
        "name": "Site Clearance & Access Roads",
        "base_weeks": (2, 4),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.3,
        "hgvs_per_mw": 0.4,
        "overlap": 0.0,
    },
    {
        "name": "Cable Trenching & Foundations",
        "base_weeks": (3, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.6,
        "hgvs_per_mw": 1.6,
        "overlap": 0.0,
    },
    {
        "name": "Pile Driving & Mounting Structures",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (1.5, 3.0),
        "workers_per_mw": 0.8,
        "hgvs_per_mw": 2.0,
        "overlap": 0.2,
    },
    {
        "name": "Racking & Panel Installation",
        "base_weeks": (6, 12),
        "scale_weeks_per_100mw": (2.0, 4.0),
        "workers_per_mw": 1.5,
        "hgvs_per_mw": 3.0,
        "overlap": 0.3,
    },
    {
        "name": "Stringing & Electrical",
        "base_weeks": (4, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.8,
        "hgvs_per_mw": 1.0,
        "overlap": 0.4,
    },
    {
        "name": "Substation & Grid Connection",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.4,
        "hgvs_per_mw": 1.5,
        "overlap": 0.0,
    },
    {
        "name": "Commissioning & Energisation",
        "base_weeks": (2, 4),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.2,
        "hgvs_per_mw": 0.5,
        "overlap": 0.0,
    },
]

WIND_PHASES = [
    {
        "name": "Site Clearance & Access Tracks",
        "base_weeks": (3, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.4,
        "hgvs_per_mw": 0.8,
        "overlap": 0.0,
    },
    {
        "name": "Foundation Excavation & Concrete",
        "base_weeks": (6, 12),
        "scale_weeks_per_100mw": (2.0, 4.0),
        "workers_per_mw": 0.8,
        "hgvs_per_mw": 3.0,
        "overlap": 0.0,
    },
    {
        "name": "Cable Trenching & Substation",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.5,
        "hgvs_per_mw": 2.0,
        "overlap": 0.3,
    },
    {
        "name": "Turbine Delivery & Erection",
        "base_weeks": (8, 16),
        "scale_weeks_per_100mw": (3.0, 6.0),
        "workers_per_mw": 1.2,
        "hgvs_per_mw": 4.0,
        "overlap": 0.0,
    },
    {
        "name": "Electrical Connection & Testing",
        "base_weeks": (4, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.6,
        "hgvs_per_mw": 1.0,
        "overlap": 0.2,
    },
    {
        "name": "Commissioning & Energisation",
        "base_weeks": (3, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.3,
        "hgvs_per_mw": 0.2,
        "overlap": 0.0,
    },
]

BESS_PHASES = [
    {
        "name": "Site Preparation & Hardstanding",
        "base_weeks": (2, 4),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.3,
        "hgvs_per_mw": 0.5,
        "overlap": 0.0,
    },
    {
        "name": "Foundations & Civil Works",
        "base_weeks": (3, 6),
        "scale_weeks_per_100mw": (1.0, 2.0),
        "workers_per_mw": 0.5,
        "hgvs_per_mw": 1.5,
        "overlap": 0.0,
    },
    {
        "name": "Battery Container Delivery & Placement",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (1.5, 3.0),
        "workers_per_mw": 0.8,
        "hgvs_per_mw": 3.0,
        "overlap": 0.2,
    },
    {
        "name": "Electrical & HVAC Installation",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (1.5, 3.0),
        "workers_per_mw": 1.0,
        "hgvs_per_mw": 1.5,
        "overlap": 0.3,
    },
    {
        "name": "Grid Connection & Substation",
        "base_weeks": (4, 8),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.4,
        "hgvs_per_mw": 1.0,
        "overlap": 0.0,
    },
    {
        "name": "Commissioning & Testing",
        "base_weeks": (2, 4),
        "scale_weeks_per_100mw": (0.5, 1.0),
        "workers_per_mw": 0.2,
        "hgvs_per_mw": 0.3,
        "overlap": 0.0,
    },
]

TECH_PHASES = {
    "solar": SOLAR_PHASES,
    "wind": WIND_PHASES,
    "bess": BESS_PHASES,
}

# Cost benchmarks (GBP per MW installed, 2024 UK market)
COST_BENCHMARKS = {
    "solar": {
        "total_gbp_per_mw": 600_000,
        "breakdown": {
            "panels": 0.35,
            "balance_of_system": 0.25,
            "epc_labour": 0.20,
            "grid_connection": 0.15,
            "other": 0.05,
        },
    },
    "wind": {
        "total_gbp_per_mw": 1_400_000,
        "breakdown": {
            "turbines": 0.55,
            "foundations_civil": 0.15,
            "electrical": 0.10,
            "grid_connection": 0.12,
            "other": 0.08,
        },
    },
    "bess": {
        "total_gbp_per_mw": 500_000,  # per MW (not MWh)
        "breakdown": {
            "battery_modules": 0.50,
            "power_conversion": 0.15,
            "balance_of_plant": 0.15,
            "grid_connection": 0.12,
            "other": 0.08,
        },
    },
}

# Access road specifications by site scale
ACCESS_ROAD_SPECS = {
    "small": {
        "max_mw": 10,
        "road_width_m": 3.5,
        "surface": "Compacted aggregate / Type 1 sub-base",
        "bridge_capacity_t": 30,
    },
    "medium": {
        "max_mw": 50,
        "road_width_m": 4.5,
        "surface": "Reinforced aggregate with geotextile",
        "bridge_capacity_t": 44,
    },
    "large": {
        "max_mw": float("inf"),
        "road_width_m": 6.0,
        "surface": "Asphalt or concrete on aggregate base",
        "bridge_capacity_t": 60,
    },
}


# ─── Schedule generator ─────────────────────────────────────────────────────

def generate_construction_schedule(
    capacity_mw: float,
    technology: str = "solar",
    site_area_ha: float | None = None,
    grid_distance_km: float | None = None,
) -> dict[str, Any]:
    """
    Generate a parametric construction schedule for an energy project.

    Parameters
    ----------
    capacity_mw : float
        Project capacity in MW.
    technology : str
        Technology type: solar, wind, bess.
    site_area_ha : float, optional
        Site area in hectares (adjusts civil works duration).
    grid_distance_km : float, optional
        Grid connection distance (adjusts connection phase).

    Returns
    -------
    dict with phases, total_weeks, workforce, HGV counts, costs.
    """
    tech = technology.lower()
    if tech not in TECH_PHASES:
        tech = "solar"

    phase_templates = TECH_PHASES[tech]
    cost_info = COST_BENCHMARKS.get(tech, COST_BENCHMARKS["solar"])

    phases = []
    current_week = 0

    for template in phase_templates:
        base_min, base_max = template["base_weeks"]
        scale_min, scale_max = template["scale_weeks_per_100mw"]

        # P50 estimate (midpoint)
        base = (base_min + base_max) / 2.0
        scale = (scale_min + scale_max) / 2.0
        duration = base + scale * (capacity_mw / 100.0)

        # Adjust for site area (larger sites need more civil works)
        if site_area_ha and "Clearance" in template["name"]:
            area_factor = max(1.0, site_area_ha / (capacity_mw * 2.0))  # 2 ha/MW baseline
            duration *= area_factor

        # Adjust grid connection phase for distance
        if grid_distance_km and "Grid" in template["name"]:
            dist_factor = max(1.0, grid_distance_km / 5.0)  # 5 km baseline
            duration *= dist_factor

        duration = max(1.0, round(duration, 0))

        # Workers and HGVs
        workers = max(2, round(template["workers_per_mw"] * capacity_mw))
        hgvs = max(1, round(template["hgvs_per_mw"] * capacity_mw))

        # Apply overlap
        overlap_weeks = round(duration * template["overlap"])
        start_week = max(0, current_week - overlap_weeks)

        phases.append({
            "name": template["name"],
            "start_week": int(start_week),
            "duration_weeks": int(duration),
            "end_week": int(start_week + duration),
            "workers": workers,
            "hgvs": hgvs,
            "hgvs_per_week": max(1, round(hgvs / duration)),
        })

        current_week = int(start_week + duration)

    total_weeks = max(p["end_week"] for p in phases) if phases else 0

    # Workforce profile
    peak_workforce = 0
    for week in range(total_weeks + 1):
        week_workers = sum(
            p["workers"] for p in phases
            if p["start_week"] <= week < p["end_week"]
        )
        peak_workforce = max(peak_workforce, week_workers)

    total_hgvs = sum(p["hgvs"] for p in phases)
    peak_daily_hgv = max(
        max(1, round(p["hgvs"] / max(1, p["duration_weeks"]) / 5))  # 5 working days
        for p in phases
    )

    # Cost estimate
    total_cost = round(cost_info["total_gbp_per_mw"] * capacity_mw)
    cost_breakdown = {
        k: round(v * total_cost)
        for k, v in cost_info["breakdown"].items()
    }

    # Adjust grid connection cost for distance
    if grid_distance_km and grid_distance_km > 5:
        extra_grid_cost = (grid_distance_km - 5) * 150_000  # approx 150k/km
        cost_breakdown["grid_connection"] = round(
            cost_breakdown.get("grid_connection", 0) + extra_grid_cost
        )
        total_cost = round(total_cost + extra_grid_cost)

    return {
        "technology": tech,
        "capacity_mw": capacity_mw,
        "site_area_ha": site_area_ha,
        "grid_distance_km": grid_distance_km,
        "total_weeks": total_weeks,
        "total_months": round(total_weeks / 4.33, 1),
        "phases": phases,
        "total_hgv_deliveries": total_hgvs,
        "peak_daily_hgv": peak_daily_hgv,
        "peak_workforce": peak_workforce,
        "average_workforce": round(
            sum(p["workers"] * p["duration_weeks"] for p in phases)
            / max(1, total_weeks),
            1,
        ),
        "estimated_cost_gbp": total_cost,
        "cost_per_mw_gbp": round(total_cost / max(0.001, capacity_mw)),
        "cost_breakdown": cost_breakdown,
        "cost_breakdown_pct": cost_info["breakdown"],
    }


# ─── Traffic estimation ──────────────────────────────────────────────────────

def estimate_construction_traffic(
    capacity_mw: float,
    technology: str = "solar",
    site_area_ha: float | None = None,
    grid_distance_km: float | None = None,
) -> dict[str, Any]:
    """
    Estimate construction traffic impacts for a CTMP (Construction Traffic
    Management Plan).

    Parameters
    ----------
    capacity_mw : float
        Project capacity in MW.
    technology : str
        Technology type: solar, wind, bess.

    Returns
    -------
    dict with HGV totals, daily peaks, abnormal loads, access specs.
    """
    tech = technology.lower()
    schedule = generate_construction_schedule(
        capacity_mw, tech, site_area_ha, grid_distance_km
    )

    # Abnormal loads (over 4.3m wide or >44t)
    if tech == "wind":
        # Turbine blades (60-80m), tower sections, nacelles
        turbine_count = max(1, round(capacity_mw / 5.0))  # ~5 MW per turbine
        abnormal_loads = turbine_count * 6  # 3 blades + 3 tower sections + nacelle
        abnormal_description = (
            f"{turbine_count} turbines: {turbine_count * 3} blade deliveries, "
            f"{turbine_count * 2} tower section loads, {turbine_count} nacelle loads"
        )
    elif tech == "solar":
        # Transformers, large inverters
        abnormal_loads = max(1, round(capacity_mw / 20))
        abnormal_description = f"{abnormal_loads} transformer/inverter abnormal loads"
    else:  # BESS
        # Battery containers, transformers
        container_count = max(1, round(capacity_mw / 2.5))
        abnormal_loads = container_count + max(1, round(capacity_mw / 25))
        abnormal_description = (
            f"{container_count} battery container deliveries + "
            f"{max(1, round(capacity_mw / 25))} transformer loads"
        )

    # Access road specification
    if capacity_mw <= 10:
        access_spec = ACCESS_ROAD_SPECS["small"]
    elif capacity_mw <= 50:
        access_spec = ACCESS_ROAD_SPECS["medium"]
    else:
        access_spec = ACCESS_ROAD_SPECS["large"]

    # Weekly traffic profile
    weekly_profile = []
    total_weeks = schedule["total_weeks"]
    for week in range(total_weeks):
        week_hgvs = sum(
            p["hgvs_per_week"]
            for p in schedule["phases"]
            if p["start_week"] <= week < p["end_week"]
        )
        weekly_profile.append({
            "week": week + 1,
            "daily_hgv": max(1, round(week_hgvs / 5)),
            "active_phases": [
                p["name"] for p in schedule["phases"]
                if p["start_week"] <= week < p["end_week"]
            ],
        })

    peak_week = max(weekly_profile, key=lambda w: w["daily_hgv"]) if weekly_profile else None

    return {
        "technology": tech,
        "capacity_mw": capacity_mw,
        "construction_duration_weeks": total_weeks,
        "total_hgv_movements": schedule["total_hgv_deliveries"] * 2,  # round trips
        "total_hgv_deliveries": schedule["total_hgv_deliveries"],
        "peak_daily_hgv_movements": schedule["peak_daily_hgv"] * 2,
        "average_daily_hgv_movements": round(
            schedule["total_hgv_deliveries"] * 2 / max(1, total_weeks * 5),
            1,
        ),
        "abnormal_loads": {
            "count": abnormal_loads,
            "description": abnormal_description,
            "escort_required": tech == "wind",
            "night_movement_required": tech == "wind" and capacity_mw > 20,
            "police_notification_required": abnormal_loads > 0,
        },
        "access_road": {
            "minimum_width_m": access_spec["road_width_m"],
            "surface_specification": access_spec["surface"],
            "bridge_capacity_tonnes": access_spec["bridge_capacity_t"],
            "turning_radius_m": 12.0 if tech == "wind" else 8.0,
            "passing_places_required": capacity_mw > 10,
        },
        "peak_week": peak_week,
        "weekly_profile": weekly_profile[:52],  # cap at 1 year
        "workforce": {
            "peak": schedule["peak_workforce"],
            "average": schedule["average_workforce"],
            "parking_spaces_required": max(20, round(schedule["peak_workforce"] * 0.8)),
            "welfare_facilities": max(1, round(schedule["peak_workforce"] / 25)),
        },
        "mitigation_measures": [
            "Construction Traffic Management Plan (CTMP) required",
            "Wheel wash facility at site exit",
            "Designated HGV routing to avoid residential areas",
            "Speed limits on access roads (20mph within site, 30mph approach)",
            "Banksman for all HGV movements within site",
            "No deliveries during school pick-up/drop-off times (08:00-09:00, 15:00-16:00)",
            "Monthly traffic monitoring and reporting to LPA",
        ],
    }
