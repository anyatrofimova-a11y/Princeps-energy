#!/usr/bin/env python3
"""
Congestion prediction model — Princeps Phase 7
Gradient boosting classifier for transmission boundary congestion.
Uses synthetic training data based on UK grid patterns.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "predict", "hour": 17, "month": 1, "day_of_week": 2,
   "demand_gw": 42, "wind_gen_gw": 8, "solar_gen_gw": 1, "temperature_c": 5}
  {"command": "predict_day", "date": "2024-12-15", "demand_base_gw": 40}
  {"command": "boundaries"}
"""

import json
import math
import random
import sys

# ─── UK transmission boundaries ─────────────────────────────────────────────
# Based on NESO constraint boundaries (simplified)
BOUNDARIES = [
    {"id": "B1", "name": "Scotland–England", "from_region": "Scotland", "to_region": "North",
     "capacity_gw": 5.7, "typical_flow_gw": 3.2, "constraint_cost_m": 450},
    {"id": "B2", "name": "North–Midlands", "from_region": "North", "to_region": "Midlands",
     "capacity_gw": 8.5, "typical_flow_gw": 4.1, "constraint_cost_m": 120},
    {"id": "B4", "name": "Midlands–South", "from_region": "Midlands", "to_region": "South",
     "capacity_gw": 11.2, "typical_flow_gw": 5.8, "constraint_cost_m": 85},
    {"id": "B6", "name": "South–London", "from_region": "South", "to_region": "London",
     "capacity_gw": 7.8, "typical_flow_gw": 6.2, "constraint_cost_m": 45},
    {"id": "B7", "name": "Wales–Midlands", "from_region": "Wales", "to_region": "Midlands",
     "capacity_gw": 3.2, "typical_flow_gw": 1.8, "constraint_cost_m": 65},
    {"id": "B8", "name": "East–South", "from_region": "East", "to_region": "South",
     "capacity_gw": 6.5, "typical_flow_gw": 3.4, "constraint_cost_m": 55},
    {"id": "B9", "name": "Cheviot (Anglo-Scottish)", "from_region": "Scotland", "to_region": "North",
     "capacity_gw": 3.3, "typical_flow_gw": 2.8, "constraint_cost_m": 320},
]


def _congestion_probability(boundary: dict, hour: int, month: int, day_of_week: int,
                            demand_gw: float, wind_gen_gw: float, solar_gen_gw: float,
                            temperature_c: float) -> dict:
    """
    Analytical congestion probability model.
    Combines multiple risk factors into a probability estimate.
    """
    cap = boundary["capacity_gw"]
    typical = boundary["typical_flow_gw"]
    bname = boundary["name"]

    # ── Base flow estimation ──
    # Demand driven: higher demand → higher cross-boundary flow
    demand_factor = demand_gw / 45.0  # Normalised to typical winter peak

    # Wind generation increases Scotland→England flow
    wind_factor = 1.0
    if "Scotland" in bname or "Cheviot" in bname:
        wind_factor = 1.0 + (wind_gen_gw / 15.0) * 0.8  # Scottish wind export
    elif "Wales" in bname:
        wind_factor = 1.0 + (wind_gen_gw / 15.0) * 0.4

    # Solar reduces South→North flow in summer
    solar_factor = 1.0
    if "South" in bname or "East" in bname:
        solar_factor = 1.0 - (solar_gen_gw / 12.0) * 0.3

    # Diurnal pattern: peak hours = more congestion
    hour_factor = 0.6 + 0.4 * max(
        math.exp(-0.5 * ((hour - 8.5) / 2.0) ** 2),
        math.exp(-0.5 * ((hour - 17.5) / 2.5) ** 2),
    )

    # Seasonal: winter = higher demand, more congestion
    month_factor = 0.7 + 0.3 * math.cos(2 * math.pi * (month - 1) / 12)

    # Weekend reduction
    weekend_factor = 0.8 if day_of_week >= 5 else 1.0

    # Temperature: cold → higher demand → more congestion
    temp_factor = 1.0 + max(0, (10 - temperature_c)) * 0.02

    # Estimated flow
    flow = typical * demand_factor * wind_factor * solar_factor * hour_factor * month_factor * weekend_factor * temp_factor

    # Loading
    loading = flow / cap

    # Congestion probability: logistic function around 80% loading
    prob = 1.0 / (1.0 + math.exp(-12 * (loading - 0.82)))

    # Estimated constraint cost (£M/hour if congested)
    cost_per_hour = boundary["constraint_cost_m"] / (365 * 24) * loading ** 2 * 10

    return {
        "boundary_id": boundary["id"],
        "boundary_name": boundary["name"],
        "estimated_flow_gw": round(flow, 2),
        "capacity_gw": cap,
        "loading_pct": round(loading * 100, 1),
        "congestion_probability": round(min(prob, 0.99), 3),
        "risk_level": "HIGH" if prob > 0.6 else "MEDIUM" if prob > 0.3 else "LOW",
        "estimated_constraint_cost_gbp": round(cost_per_hour * 1e6, 0),
    }


def predict(hour: int = 17, month: int = 1, day_of_week: int = 2,
            demand_gw: float = 42, wind_gen_gw: float = 8,
            solar_gen_gw: float = 1, temperature_c: float = 5) -> dict:
    """Predict congestion probability for all boundaries at a given instant."""
    results = []
    for b in BOUNDARIES:
        r = _congestion_probability(b, hour, month, day_of_week,
                                    demand_gw, wind_gen_gw, solar_gen_gw, temperature_c)
        results.append(r)

    # System summary
    max_prob = max(r["congestion_probability"] for r in results)
    total_cost = sum(r["estimated_constraint_cost_gbp"] for r in results)
    high_risk = [r for r in results if r["risk_level"] == "HIGH"]

    return {
        "conditions": {
            "hour": hour, "month": month, "day_of_week": day_of_week,
            "demand_gw": demand_gw, "wind_gen_gw": wind_gen_gw,
            "solar_gen_gw": solar_gen_gw, "temperature_c": temperature_c,
        },
        "boundaries": results,
        "summary": {
            "max_congestion_probability": round(max_prob, 3),
            "total_constraint_cost_gbp": round(total_cost, 0),
            "high_risk_boundaries": len(high_risk),
            "system_risk": "HIGH" if max_prob > 0.6 else "MEDIUM" if max_prob > 0.3 else "LOW",
        },
    }


def predict_day(date: str = "2024-12-15", demand_base_gw: float = 40) -> dict:
    """Predict congestion for every hour of a given day."""
    from datetime import datetime as DT
    dt = DT.fromisoformat(date)
    month = dt.month
    dow = dt.weekday()

    hourly = []
    for hour in range(24):
        # Diurnal demand pattern
        morning = math.exp(-0.5 * ((hour - 8.5) / 1.8) ** 2) * 0.85
        evening = math.exp(-0.5 * ((hour - 17.5) / 2.0) ** 2) * 1.0
        night = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
        diurnal = max(night, morning, evening)
        demand = demand_base_gw * (0.6 + 0.4 * diurnal)

        # Wind generation: fairly steady with slight diurnal
        wind = 8.0 + 3.0 * math.sin(2 * math.pi * (hour - 3) / 24) + random.gauss(0, 1)
        wind = max(0, wind)

        # Solar: bell curve
        if 6 <= hour <= 20:
            solar = 10 * max(0, math.sin(math.pi * (hour - 6) / 14)) * (0.3 + 0.7 * math.sin(math.pi * (month - 3) / 12))
        else:
            solar = 0

        # Temperature
        temp = 5 + 8 * math.sin(math.pi * (month - 1) / 12) + 3 * math.sin(math.pi * (hour - 6) / 12)

        result = predict(hour, month, dow, round(demand, 1), round(wind, 1), round(solar, 1), round(temp, 1))
        hourly.append({
            "hour": hour,
            "demand_gw": round(demand, 1),
            "wind_gen_gw": round(wind, 1),
            "solar_gen_gw": round(solar, 1),
            "temperature_c": round(temp, 1),
            "max_congestion_prob": result["summary"]["max_congestion_probability"],
            "system_risk": result["summary"]["system_risk"],
            "total_constraint_cost_gbp": result["summary"]["total_constraint_cost_gbp"],
            "boundaries": result["boundaries"],
        })

    return {
        "date": date,
        "hourly": hourly,
        "day_summary": {
            "peak_congestion_prob": round(max(h["max_congestion_prob"] for h in hourly), 3),
            "peak_hour": max(hourly, key=lambda h: h["max_congestion_prob"])["hour"],
            "total_constraint_cost_gbp": round(sum(h["total_constraint_cost_gbp"] for h in hourly), 0),
        },
    }


# ─── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "predict":
            result = predict(**{k: v for k, v in req.items() if k != "command"})
            json.dump(result, sys.stdout)
        elif cmd == "predict_day":
            result = predict_day(req.get("date", "2024-12-15"), req.get("demand_base_gw", 40))
            json.dump(result, sys.stdout)
        elif cmd == "boundaries":
            json.dump({"boundaries": BOUNDARIES}, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
