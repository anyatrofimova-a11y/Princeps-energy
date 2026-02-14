"""
Grid Efficiency Analyser Module.

Identifies grid inefficiencies, estimates losses, maps congestion,
and scores infrastructure degradation using grid data + satellite intelligence.

Techniques referenced from Geo_AI_compendium:
- Satellite-based infrastructure corridor mapping
- Change detection for degradation monitoring
- Spectral analysis for vegetation encroachment on power lines
"""

from __future__ import annotations

import math
from typing import Any


# UK grid loss benchmarks by voltage level
LOSS_BENCHMARKS = {
    400: {"pct_per_100km": 0.5, "label": "400kV Supergrid"},
    275: {"pct_per_100km": 0.8, "label": "275kV Grid Supply"},
    132: {"pct_per_100km": 1.5, "label": "132kV Bulk Supply"},
    33: {"pct_per_100km": 3.0, "label": "33kV Primary"},
    11: {"pct_per_100km": 5.0, "label": "11kV Secondary"},
}

# Transformer efficiency by age
TRANSFORMER_EFFICIENCY = {
    "new": {"age_range": "0-10yr", "efficiency_pct": 99.2},
    "mid_life": {"age_range": "10-25yr", "efficiency_pct": 98.5},
    "ageing": {"age_range": "25-35yr", "efficiency_pct": 97.5},
    "end_of_life": {"age_range": "35+yr", "efficiency_pct": 96.0},
}


def estimate_line_losses(
    distance_km: float,
    voltage_kv: float,
    load_mw: float,
    capacity_mva: float | None = None,
) -> dict:
    """
    Estimate transmission/distribution line losses.

    Uses voltage-dependent loss rates scaled by loading factor.
    """
    benchmark = LOSS_BENCHMARKS.get(voltage_kv)
    if not benchmark:
        # Find nearest voltage level
        nearest = min(LOSS_BENCHMARKS.keys(), key=lambda v: abs(v - voltage_kv))
        benchmark = LOSS_BENCHMARKS[nearest]
        voltage_kv = nearest

    base_loss_pct = benchmark["pct_per_100km"] * distance_km / 100

    # Loading factor: losses increase as square of loading ratio
    if capacity_mva and capacity_mva > 0:
        loading_ratio = load_mw / capacity_mva
        loss_multiplier = loading_ratio ** 2
    else:
        loss_multiplier = 0.5  # assume 50% loaded

    actual_loss_pct = base_loss_pct * max(0.1, loss_multiplier)
    loss_mw = load_mw * actual_loss_pct / 100

    # Annual cost at ~£50/MWh average
    annual_loss_cost = loss_mw * 8760 * 0.7 * 50  # 70% capacity factor

    return {
        "distance_km": round(distance_km, 1),
        "voltage_kv": voltage_kv,
        "load_mw": round(load_mw, 2),
        "loss_pct": round(actual_loss_pct, 3),
        "loss_mw": round(loss_mw, 4),
        "annual_loss_cost_gbp": round(annual_loss_cost),
        "loading_ratio": round(loss_multiplier ** 0.5, 2),
        "benchmark_pct_per_100km": benchmark["pct_per_100km"],
    }


def analyse_network_efficiency(topology: dict) -> dict:
    """
    Analyse efficiency across a grid topology.

    Args:
        topology: dict with 'nodes' and 'flows' GeoJSON FeatureCollections
    """
    flows = topology.get("flows", {}).get("features", [])
    nodes = topology.get("nodes", {}).get("features", [])

    total_loss_mw = 0
    total_flow_mw = 0
    congested_lines = []
    high_loss_lines = []

    for flow in flows:
        props = flow.get("properties", {})
        flow_mw = props.get("flow_mw", 0)
        capacity_mva = props.get("capacity_mva", 100)
        voltage_kv = props.get("voltage_kv", 132)
        utilization = props.get("utilization", 0.5)

        # Estimate distance from geometry
        coords = flow.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            c0, c1 = coords[0], coords[-1]
            dist = _haversine(c0[1], c0[0], c1[1], c1[0])
        else:
            dist = 10  # default 10km

        loss = estimate_line_losses(dist, voltage_kv, abs(flow_mw), capacity_mva)
        total_loss_mw += loss["loss_mw"]
        total_flow_mw += abs(flow_mw)

        # Flag congested lines (>80% utilization)
        if utilization > 0.8:
            congested_lines.append({
                "from": props.get("from_node", ""),
                "to": props.get("to_node", ""),
                "utilization_pct": round(utilization * 100, 1),
                "flow_mw": round(flow_mw, 1),
                "voltage_kv": voltage_kv,
            })

        # Flag high-loss lines
        if loss["loss_pct"] > 2.0:
            high_loss_lines.append({
                "from": props.get("from_node", ""),
                "to": props.get("to_node", ""),
                "loss_pct": loss["loss_pct"],
                "loss_mw": loss["loss_mw"],
                "distance_km": loss["distance_km"],
            })

    # Sort by severity
    congested_lines.sort(key=lambda x: x["utilization_pct"], reverse=True)
    high_loss_lines.sort(key=lambda x: x["loss_pct"], reverse=True)

    efficiency_pct = ((total_flow_mw - total_loss_mw) / total_flow_mw * 100) if total_flow_mw else 100

    return {
        "total_flow_mw": round(total_flow_mw, 1),
        "total_loss_mw": round(total_loss_mw, 2),
        "network_efficiency_pct": round(efficiency_pct, 2),
        "annual_loss_cost_gbp": round(total_loss_mw * 8760 * 0.7 * 50),
        "congested_lines": congested_lines[:15],
        "congested_count": len(congested_lines),
        "high_loss_lines": high_loss_lines[:15],
        "high_loss_count": len(high_loss_lines),
        "total_lines_analysed": len(flows),
        "total_nodes": len(nodes),
    }


def identify_upgrade_opportunities(
    topology: dict,
    substations: list[dict] | None = None,
    min_congestion_pct: float = 70,
) -> list[dict]:
    """
    Identify grid upgrade opportunities based on congestion and losses.

    Returns ranked list of intervention recommendations.
    """
    opportunities = []
    flows = topology.get("flows", {}).get("features", [])

    for flow in flows:
        props = flow.get("properties", {})
        utilization = props.get("utilization", 0)
        voltage_kv = props.get("voltage_kv", 132)
        flow_mw = abs(props.get("flow_mw", 0))
        capacity_mva = props.get("capacity_mva", 100)

        if utilization * 100 < min_congestion_pct:
            continue

        # Estimate savings from upgrade
        coords = flow.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            dist = _haversine(coords[0][1], coords[0][0], coords[-1][1], coords[-1][0])
        else:
            dist = 10

        current_loss = estimate_line_losses(dist, voltage_kv, flow_mw, capacity_mva)

        # Modelled upgrade: double capacity
        upgraded_loss = estimate_line_losses(dist, voltage_kv, flow_mw, capacity_mva * 2)
        saving_mw = current_loss["loss_mw"] - upgraded_loss["loss_mw"]
        annual_saving = saving_mw * 8760 * 0.7 * 50

        # Upgrade cost estimate (£/km varies by voltage)
        cost_per_km = {400: 2_000_000, 275: 1_500_000, 132: 800_000, 33: 300_000, 11: 150_000}
        nearest_v = min(cost_per_km.keys(), key=lambda v: abs(v - voltage_kv))
        upgrade_cost = cost_per_km[nearest_v] * dist

        payback_years = upgrade_cost / annual_saving if annual_saving > 0 else 999

        # Battery storage alternative
        battery_capacity_mwh = flow_mw * 0.3 * 2  # 30% peak shaving, 2hr duration
        battery_cost = battery_capacity_mwh * 450_000  # £450k/MWh

        opportunities.append({
            "from_node": props.get("from_node", ""),
            "to_node": props.get("to_node", ""),
            "congestion_pct": round(utilization * 100, 1),
            "current_flow_mw": round(flow_mw, 1),
            "voltage_kv": voltage_kv,
            "distance_km": round(dist, 1),
            "interventions": [
                {
                    "type": "line_upgrade",
                    "description": f"Upgrade {voltage_kv}kV line to double capacity",
                    "cost_gbp": round(upgrade_cost),
                    "annual_saving_gbp": round(annual_saving),
                    "payback_years": round(payback_years, 1),
                    "loss_reduction_mw": round(saving_mw, 3),
                },
                {
                    "type": "battery_storage",
                    "description": f"Deploy {battery_capacity_mwh:.1f} MWh BESS for peak shaving",
                    "cost_gbp": round(battery_cost),
                    "capacity_mwh": round(battery_capacity_mwh, 1),
                },
            ],
        })

    opportunities.sort(key=lambda x: x["congestion_pct"], reverse=True)
    return opportunities[:20]


def substation_health_assessment(
    substations: list[dict],
    geoai_condition: dict | None = None,
) -> list[dict]:
    """
    Assess substation health using available data + GeoAI satellite condition.
    """
    assessments = []
    for sub in substations:
        age_years = sub.get("age_years")
        capacity_mva = sub.get("capacity_mva", sub.get("capacity_kw", 0) / 1000)
        headroom_mw = sub.get("headroom_mw", sub.get("headroom_mva", 0))
        utilization = 1 - (headroom_mw / capacity_mva) if capacity_mva > 0 else 0.5

        # Health score based on age, utilization, and condition
        health = 100.0
        issues = []

        if age_years is not None:
            if age_years > 40:
                health -= 30
                issues.append(f"Beyond design life ({age_years}yr)")
            elif age_years > 25:
                health -= 15
                issues.append(f"Ageing infrastructure ({age_years}yr)")

        if utilization > 0.9:
            health -= 20
            issues.append(f"Near capacity ({utilization*100:.0f}%)")
        elif utilization > 0.75:
            health -= 10
            issues.append(f"High utilization ({utilization*100:.0f}%)")

        # GeoAI satellite condition (vegetation, structural changes)
        if geoai_condition:
            sat_score = geoai_condition.get("condition_score", 75)
            if sat_score < 50:
                health -= 15
                issues.append(f"Satellite condition concern ({sat_score}/100)")
            flags = geoai_condition.get("flags", [])
            for flag in flags[:2]:
                issues.append(f"GeoAI: {flag}")

        health = max(0, min(100, health))
        if health >= 70:
            rating = "GOOD"
        elif health >= 40:
            rating = "FAIR"
        else:
            rating = "POOR"

        assessments.append({
            "name": sub.get("name", sub.get("site_name", "")),
            "health_score": round(health, 1),
            "rating": rating,
            "utilization_pct": round(utilization * 100, 1),
            "capacity_mva": round(capacity_mva, 1),
            "headroom_mw": round(headroom_mw, 1),
            "issues": issues,
        })

    assessments.sort(key=lambda x: x["health_score"])
    return assessments


def _haversine(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))
