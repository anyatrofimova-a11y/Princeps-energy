#!/usr/bin/env python3
"""
Connection strategy report engine — Princeps Phase 8
Integrates DLR uplift, congestion risk, reinforcement cost, curtailment,
and flexible connection options into ranked strategy recommendations.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "strategy", "lat": 51.5, "lon": -1.0, "capacity_mw": 50,
   "technology": "solar", "voltage_kv": 132, "headroom_mw": 30}
  {"command": "compare_strategies", "capacity_mw": 50, "region": "Midlands",
   "headroom_mw": 30}
"""

import json
import math
import random
import sys

# ── Strategy scoring weights ─────────────────────────────────────────────
STRATEGY_WEIGHTS = {
    "npv": 0.30,           # Financial return
    "curtailment": 0.20,    # Lower curtailment = better
    "timeline": 0.15,       # Faster connection = better
    "risk": 0.15,           # Lower risk = better
    "flexibility": 0.10,    # ANM/flexibility value
    "dlr_benefit": 0.10,    # DLR uplift potential
}

# ── Regional data ─────────────────────────────────────────────────────────
REGIONS_BY_COORDS = [
    {"name": "Scotland", "lat_range": (55, 61), "lon_range": (-8, -1)},
    {"name": "North", "lat_range": (53.5, 55), "lon_range": (-4, 0)},
    {"name": "Wales", "lat_range": (51.3, 53.5), "lon_range": (-5.5, -2.7)},
    {"name": "Midlands", "lat_range": (52, 53.5), "lon_range": (-2.7, 0)},
    {"name": "East", "lat_range": (51.5, 53), "lon_range": (0, 2)},
    {"name": "South", "lat_range": (50, 52), "lon_range": (-3, 0)},
    {"name": "London", "lat_range": (51.2, 51.7), "lon_range": (-0.5, 0.3)},
]

# DLR potential by region (typical uplift % under favourable conditions)
DLR_POTENTIAL = {
    "Scotland": {"winter": 85, "summer": 25, "annual_mean": 52},
    "North": {"winter": 70, "summer": 20, "annual_mean": 42},
    "Wales": {"winter": 75, "summer": 22, "annual_mean": 45},
    "Midlands": {"winter": 55, "summer": 15, "annual_mean": 33},
    "East": {"winter": 65, "summer": 18, "annual_mean": 38},
    "South": {"winter": 50, "summer": 12, "annual_mean": 28},
    "London": {"winter": 35, "summer": 8, "annual_mean": 20},
}

# Congestion risk by region (0-100 score)
CONGESTION_RISK = {
    "Scotland": 82, "North": 55, "Wales": 60, "Midlands": 38,
    "East": 45, "South": 30, "London": 25,
}

# Connection cost benchmarks (£/MW for total connection)
CONNECTION_COST_PER_MW = {
    "firm": {"11": 120000, "33": 95000, "66": 85000, "132": 75000, "275": 65000},
    "anm": {"11": 55000, "33": 42000, "66": 38000, "132": 35000, "275": 30000},
    "non_firm": {"11": 40000, "33": 30000, "66": 28000, "132": 25000, "275": 22000},
    "timed": {"11": 60000, "33": 48000, "66": 42000, "132": 38000, "275": 32000},
    "intertrip": {"11": 85000, "33": 68000, "66": 60000, "132": 55000, "275": 48000},
}


def _region_from_coords(lat: float, lon: float) -> str:
    for r in REGIONS_BY_COORDS:
        if r["lat_range"][0] <= lat <= r["lat_range"][1] and r["lon_range"][0] <= lon <= r["lon_range"][1]:
            return r["name"]
    return "Midlands"


def _score_strategy(strategy: dict, max_npv: float, max_timeline: float) -> float:
    """Score a strategy option 0-100."""
    w = STRATEGY_WEIGHTS

    # NPV score (0-100, normalised)
    npv_score = max(0, min(100, (strategy["npv_25yr_gbp"] / max(abs(max_npv), 1)) * 100)) if max_npv > 0 else 50

    # Curtailment score (lower = better)
    curtail_score = max(0, 100 - strategy["curtailment_pct"] * 5)

    # Timeline score (faster = better)
    timeline_score = max(0, 100 - (strategy["timeline_months"] / max(max_timeline, 1)) * 80)

    # Risk score (lower = better)
    risk_score = max(0, 100 - strategy["risk_score"])

    # Flexibility score
    flex_score = strategy.get("flexibility_score", 50)

    # DLR benefit score
    dlr_score = min(100, strategy.get("dlr_uplift_pct", 0) * 1.5)

    composite = (
        w["npv"] * npv_score +
        w["curtailment"] * curtail_score +
        w["timeline"] * timeline_score +
        w["risk"] * risk_score +
        w["flexibility"] * flex_score +
        w["dlr_benefit"] * dlr_score
    )
    return round(composite, 1)


def generate_strategy(lat: float = 51.5, lon: float = -1.0,
                       capacity_mw: float = 50, technology: str = "solar",
                       voltage_kv: int = 132, headroom_mw: float = 30,
                       distance_km: float = 5) -> dict:
    """
    Generate comprehensive connection strategy with ranked recommendations.
    """
    region = _region_from_coords(lat, lon)
    dlr = DLR_POTENTIAL.get(region, DLR_POTENTIAL["Midlands"])
    congestion = CONGESTION_RISK.get(region, 40)

    # Capacity factor
    cf_map = {
        "solar": {"Scotland": 0.095, "North": 0.100, "Wales": 0.102, "Midlands": 0.108,
                  "East": 0.112, "South": 0.115, "London": 0.105},
        "wind": {"Scotland": 0.32, "North": 0.28, "Wales": 0.30, "Midlands": 0.22,
                 "East": 0.26, "South": 0.24, "London": 0.18},
    }
    cf = cf_map.get(technology, cf_map["solar"]).get(region, 0.10)

    # Shortfall
    shortfall_mw = max(0, capacity_mw - headroom_mw)
    shortfall_ratio = shortfall_mw / max(capacity_mw, 1)

    # Annual generation
    annual_mwh = capacity_mw * 8760 * cf
    avg_price = 55  # £/MWh wholesale

    # Build strategy options
    strategies = []
    vk_str = str(min([11, 33, 66, 132, 275], key=lambda v: abs(v - voltage_kv)))

    for conn_type, conn_label in [
        ("firm", "Firm Connection"), ("anm", "ANM Managed"),
        ("non_firm", "Non-Firm Export"), ("timed", "Timed Export"),
        ("intertrip", "Intertrip Scheme"),
    ]:
        # Connection cost
        cost_per_mw = CONNECTION_COST_PER_MW.get(conn_type, CONNECTION_COST_PER_MW["firm"]).get(vk_str, 75000)
        connection_cost = capacity_mw * cost_per_mw

        # Project CAPEX
        project_capex_per_mw = 450000 if technology == "solar" else 1200000
        total_capex = capacity_mw * project_capex_per_mw + connection_cost

        # Curtailment
        base_curtail = {"firm": 0.5, "anm": 4.5, "non_firm": 9.0, "timed": 3.5, "intertrip": 1.5}
        curtail_pct = base_curtail.get(conn_type, 5) * (1 + shortfall_ratio * 2) * (congestion / 50)
        curtail_pct = max(0.1, min(curtail_pct, 40))

        curtailed_mwh = annual_mwh * curtail_pct / 100
        delivered_mwh = annual_mwh - curtailed_mwh

        # Revenue
        annual_revenue = delivered_mwh * avg_price
        annual_om = capacity_mw * 1000 * (10 if technology == "solar" else 25)

        # NPV
        npv = -total_capex
        for yr in range(1, 26):
            net = (annual_revenue - annual_om) * (1.02 ** (yr - 1))
            npv += net / (1.08 ** yr)

        # Timeline
        timeline_map = {"firm": 24, "anm": 14, "non_firm": 12, "timed": 16, "intertrip": 18}
        timeline = timeline_map.get(conn_type, 18)
        if capacity_mw > 50:
            timeline = int(timeline * 1.3)
        if shortfall_mw > 0 and conn_type == "firm":
            timeline += 6  # Reinforcement adds time

        # Risk score (0-100)
        risk_base = {"firm": 25, "anm": 40, "non_firm": 55, "timed": 35, "intertrip": 30}
        risk = risk_base.get(conn_type, 40)
        risk += congestion * 0.3
        risk += shortfall_ratio * 20
        risk = min(100, risk)

        # Flexibility score
        flex_map = {"firm": 30, "anm": 85, "non_firm": 60, "timed": 70, "intertrip": 45}
        flex = flex_map.get(conn_type, 50)

        strategies.append({
            "connection_type": conn_type,
            "label": conn_label,
            "connection_cost_gbp": round(connection_cost),
            "total_capex_gbp": round(total_capex),
            "curtailment_pct": round(curtail_pct, 2),
            "curtailed_mwh": round(curtailed_mwh),
            "delivered_mwh": round(delivered_mwh),
            "annual_revenue_gbp": round(annual_revenue),
            "npv_25yr_gbp": round(npv),
            "timeline_months": timeline,
            "risk_score": round(risk, 1),
            "flexibility_score": flex,
            "dlr_uplift_pct": dlr["annual_mean"],
        })

    # Score and rank
    max_npv = max(s["npv_25yr_gbp"] for s in strategies)
    max_timeline = max(s["timeline_months"] for s in strategies)

    for s in strategies:
        s["composite_score"] = _score_strategy(s, max_npv, max_timeline)

    strategies.sort(key=lambda x: -x["composite_score"])

    # Generate recommendation summary
    best = strategies[0]
    if best["curtailment_pct"] < 3 and best["npv_25yr_gbp"] > 0:
        verdict = "GO"
        confidence = min(0.9, 0.5 + (100 - best["risk_score"]) / 200)
    elif best["curtailment_pct"] < 10 and best["npv_25yr_gbp"] > -total_capex * 0.1:
        verdict = "CAUTION"
        confidence = 0.5
    else:
        verdict = "NO-GO"
        confidence = 0.3

    return {
        "site": {"lat": lat, "lon": lon, "region": region},
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "voltage_kv": voltage_kv,
            "headroom_mw": headroom_mw,
            "shortfall_mw": round(shortfall_mw, 1),
            "distance_km": distance_km,
            "capacity_factor": cf,
        },
        "grid_context": {
            "congestion_risk": congestion,
            "dlr_potential": dlr,
            "region": region,
        },
        "strategies": strategies,
        "recommended": {
            "connection_type": best["connection_type"],
            "label": best["label"],
            "composite_score": best["composite_score"],
            "verdict": verdict,
            "confidence": round(confidence, 2),
        },
        "annual_potential_mwh": round(annual_mwh),
    }


def compare_strategies(capacity_mw: float = 50, region: str = "Midlands",
                        headroom_mw: float = 30,
                        technology: str = "solar") -> dict:
    """
    Simplified comparison across connection types for a region.
    """
    # Use centroid coords for region
    region_centres = {
        "Scotland": (56.5, -4.0), "North": (54.0, -2.0), "Wales": (52.0, -3.5),
        "Midlands": (52.5, -1.5), "East": (52.0, 0.5), "South": (51.0, -1.5),
        "London": (51.5, -0.1),
    }
    lat, lon = region_centres.get(region, (52.5, -1.5))

    result = generate_strategy(lat, lon, capacity_mw, technology, 132, headroom_mw)

    # Add sensitivity analysis — how does NPV change with curtailment?
    sensitivity = []
    for curtail_mult in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        annual_mwh = result["annual_potential_mwh"]
        curtailed = annual_mwh * (result["strategies"][0]["curtailment_pct"] * curtail_mult / 100)
        delivered = annual_mwh - curtailed
        rev = delivered * 55
        om = capacity_mw * 1000 * (10 if technology == "solar" else 25)
        npv = -result["strategies"][0]["total_capex_gbp"]
        for yr in range(1, 26):
            npv += (rev - om) * (1.02 ** (yr - 1)) / (1.08 ** yr)
        sensitivity.append({
            "curtailment_multiplier": curtail_mult,
            "curtailment_pct": round(result["strategies"][0]["curtailment_pct"] * curtail_mult, 2),
            "npv_gbp": round(npv),
        })

    result["sensitivity"] = sensitivity
    return result


# ── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "strategy":
            result = generate_strategy(
                lat=req.get("lat", 51.5),
                lon=req.get("lon", -1.0),
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                voltage_kv=req.get("voltage_kv", 132),
                headroom_mw=req.get("headroom_mw", 30),
                distance_km=req.get("distance_km", 5),
            )
            json.dump(result, sys.stdout)
        elif cmd == "compare_strategies":
            result = compare_strategies(
                capacity_mw=req.get("capacity_mw", 50),
                region=req.get("region", "Midlands"),
                headroom_mw=req.get("headroom_mw", 30),
                technology=req.get("technology", "solar"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
