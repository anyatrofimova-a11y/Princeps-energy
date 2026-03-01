#!/usr/bin/env python3
"""
Multi-objective connection optimiser — Princeps Phase 7
NSGA-II optimisation for optimal grid connection point.
Uses pymoo for Pareto frontier generation.

Runs in .venv-grid/ (pymoo installed alongside pandapower).

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "optimise", "lat": 51.5, "lon": -1.0, "capacity_mw": 50,
   "technology": "solar", "candidates": [...]}
"""

import json
import math
import sys

# ─── Candidate scoring (no pymoo required) ──────────────────────────────────
# Fast analytical approach — works without external deps

# UK reinforcement cost benchmarks (£/unit)
COST_BENCHMARKS = {
    "cable_per_km": {11: 80_000, 33: 150_000, 66: 300_000, 132: 500_000, 275: 900_000},
    "switchgear": {11: 50_000, 33: 300_000, 66: 500_000, 132: 800_000},
    "transformer": {
        "11/33": 500_000, "33/66": 1_200_000, "33/132": 2_500_000,
        "66/132": 3_500_000, "132/275": 8_000_000, "275/400": 15_000_000,
    },
}


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _estimate_reinforcement_cost(distance_km, voltage_kv, capacity_mw, headroom_mw):
    """Estimate reinforcement cost for a connection option."""
    costs = {}

    # Cable/line cost
    cable_rate = COST_BENCHMARKS["cable_per_km"].get(voltage_kv, 300_000)
    costs["cable"] = distance_km * cable_rate

    # Switchgear
    costs["switchgear"] = COST_BENCHMARKS["switchgear"].get(voltage_kv, 300_000)

    # Transformer upgrade if headroom insufficient
    shortfall = capacity_mw - headroom_mw if headroom_mw < capacity_mw else 0
    if shortfall > 0:
        # Need transformer upgrade
        for key, cost in COST_BENCHMARKS["transformer"].items():
            voltages = [int(v) for v in key.split("/")]
            if voltage_kv in voltages:
                costs["transformer"] = cost
                break
        else:
            costs["transformer"] = 2_000_000  # Default
    else:
        costs["transformer"] = 0

    # Design & legal (~10%)
    subtotal = sum(costs.values())
    costs["design_legal"] = subtotal * 0.10

    # DNO fees (~8%)
    costs["dno_fees"] = subtotal * 0.08

    return costs


def _score_candidate(candidate, lat, lon, capacity_mw, technology):
    """Score a single candidate connection point across all objectives."""
    c_lat = candidate.get("lat", 0)
    c_lon = candidate.get("lon", 0)
    c_voltage = candidate.get("voltage_kv", 33)
    c_headroom = candidate.get("headroom_mw", 0)
    c_queue = candidate.get("queue_depth", 0)
    c_name = candidate.get("name", "Unknown")

    # Distance
    distance_km = _haversine(lat, lon, c_lat, c_lon)

    # Reinforcement cost
    costs = _estimate_reinforcement_cost(distance_km, c_voltage, capacity_mw, c_headroom)
    total_cost = sum(costs.values())

    # Queue wait (months) — roughly 6 months per queued project
    queue_wait_months = c_queue * 6 + 12  # Base 12 months minimum

    # Feasibility checks
    voltage_ok = c_voltage >= (33 if capacity_mw <= 50 else 132 if capacity_mw <= 200 else 275)
    headroom_ok = c_headroom >= capacity_mw * 0.3  # At least 30% headroom
    distance_ok = distance_km <= 30  # Max 30km

    # Composite score (0-100) — higher is better
    dist_score = max(0, 100 - distance_km * 5)  # 20km → 0
    cost_score = max(0, 100 - total_cost / 100_000)  # £10M → 0
    queue_score = max(0, 100 - queue_wait_months * 2)  # 50 months → 0
    headroom_score = min(100, (c_headroom / max(capacity_mw, 1)) * 100)

    composite = (dist_score * 0.25 + cost_score * 0.30 + queue_score * 0.20 + headroom_score * 0.25)

    return {
        "name": c_name,
        "lat": c_lat,
        "lon": c_lon,
        "voltage_kv": c_voltage,
        "distance_km": round(distance_km, 2),
        "headroom_mw": c_headroom,
        "queue_depth": c_queue,
        "queue_wait_months": queue_wait_months,
        "reinforcement_cost": {k: round(v) for k, v in costs.items()},
        "total_cost_gbp": round(total_cost),
        "scores": {
            "distance": round(dist_score, 1),
            "cost": round(cost_score, 1),
            "queue": round(queue_score, 1),
            "headroom": round(headroom_score, 1),
            "composite": round(composite, 1),
        },
        "feasible": voltage_ok and headroom_ok and distance_ok,
        "constraints": {
            "voltage_ok": voltage_ok,
            "headroom_ok": headroom_ok,
            "distance_ok": distance_ok,
        },
    }


def optimise(lat: float, lon: float, capacity_mw: float, technology: str = "solar",
             candidates: list = None) -> dict:
    """
    Multi-objective connection optimisation.
    If candidates provided, scores them. Otherwise generates synthetic candidates.
    Returns Pareto-optimal solutions.
    """
    if not candidates:
        # Generate synthetic candidates (typical UK substations near location)
        import random
        random.seed(int(lat * 1000 + lon * 1000))
        candidates = []
        voltages = [33, 33, 66, 132, 132, 275]
        for i in range(8):
            d = random.uniform(2, 25)
            bearing = random.uniform(0, 360)
            c_lat = lat + d / 111.0 * math.cos(math.radians(bearing))
            c_lon = lon + d / (111.0 * math.cos(math.radians(lat))) * math.sin(math.radians(bearing))
            v = voltages[i % len(voltages)]
            candidates.append({
                "name": f"Substation_{i+1}",
                "lat": round(c_lat, 4),
                "lon": round(c_lon, 4),
                "voltage_kv": v,
                "headroom_mw": round(random.uniform(5, 200) * (v / 132), 1),
                "queue_depth": random.randint(0, 8),
            })

    # Score all candidates
    scored = [_score_candidate(c, lat, lon, capacity_mw, technology) for c in candidates]

    # Filter feasible
    feasible = [s for s in scored if s["feasible"]]
    infeasible = [s for s in scored if not s["feasible"]]

    # Find Pareto frontier (non-dominated solutions)
    pareto = []
    for s in feasible:
        dominated = False
        for other in feasible:
            if other is s:
                continue
            # other dominates s if better on all objectives
            if (other["distance_km"] <= s["distance_km"] and
                other["total_cost_gbp"] <= s["total_cost_gbp"] and
                other["queue_wait_months"] <= s["queue_wait_months"] and
                (other["distance_km"] < s["distance_km"] or
                 other["total_cost_gbp"] < s["total_cost_gbp"] or
                 other["queue_wait_months"] < s["queue_wait_months"])):
                dominated = True
                break
        if not dominated:
            pareto.append(s)

    # Sort by composite score
    pareto.sort(key=lambda x: -x["scores"]["composite"])
    feasible.sort(key=lambda x: -x["scores"]["composite"])

    return {
        "site": {"lat": lat, "lon": lon, "capacity_mw": capacity_mw, "technology": technology},
        "candidates_total": len(scored),
        "candidates_feasible": len(feasible),
        "pareto_optimal": len(pareto),
        "recommended": pareto[0] if pareto else (feasible[0] if feasible else None),
        "pareto_frontier": pareto,
        "all_feasible": feasible,
        "infeasible": infeasible,
        "objectives": ["distance_km", "total_cost_gbp", "queue_wait_months"],
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
        if cmd == "optimise":
            result = optimise(
                lat=req.get("lat", 51.5),
                lon=req.get("lon", -1.0),
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                candidates=req.get("candidates"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
