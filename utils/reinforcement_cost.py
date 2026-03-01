#!/usr/bin/env python3
"""
Reinforcement cost estimator — Princeps Phase 7
Rule-based model from published UK DNO cost data.
Monte Carlo for P10/P50/P90 probabilistic estimates.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "estimate", "distance_km": 5, "voltage_kv": 132, "capacity_mw": 50,
   "headroom_mw": 30, "terrain": "rural"}
  {"command": "breakdown", "components": [{"type": "cable", "voltage_kv": 132, "length_km": 5}, ...]}
  {"command": "benchmarks"}
"""

import json
import math
import random
import sys

# ─── UK DNO published cost benchmarks (2024 prices, £) ──────────────────────
# Source: Ofgem cost assessment data, DNO connection charge statements

UNIT_COSTS = {
    "cable_underground_per_km": {
        11: {"mean": 95_000, "std": 25_000, "min": 60_000, "max": 150_000},
        33: {"mean": 200_000, "std": 50_000, "min": 120_000, "max": 300_000},
        66: {"mean": 400_000, "std": 80_000, "min": 280_000, "max": 550_000},
        132: {"mean": 700_000, "std": 120_000, "min": 500_000, "max": 950_000},
    },
    "overhead_line_per_km": {
        11: {"mean": 55_000, "std": 15_000, "min": 35_000, "max": 80_000},
        33: {"mean": 120_000, "std": 30_000, "min": 80_000, "max": 180_000},
        66: {"mean": 250_000, "std": 60_000, "min": 160_000, "max": 380_000},
        132: {"mean": 650_000, "std": 100_000, "min": 450_000, "max": 850_000},
        275: {"mean": 1_200_000, "std": 200_000, "min": 850_000, "max": 1_600_000},
        400: {"mean": 1_800_000, "std": 300_000, "min": 1_300_000, "max": 2_500_000},
    },
    "switchgear_per_bay": {
        11: {"mean": 65_000, "std": 15_000, "min": 40_000, "max": 100_000},
        33: {"mean": 300_000, "std": 60_000, "min": 200_000, "max": 400_000},
        66: {"mean": 550_000, "std": 80_000, "min": 400_000, "max": 700_000},
        132: {"mean": 900_000, "std": 150_000, "min": 650_000, "max": 1_200_000},
    },
    "transformer": {
        "11/33": {"mean": 450_000, "std": 80_000, "min": 300_000, "max": 600_000},
        "33/66": {"mean": 1_100_000, "std": 200_000, "min": 800_000, "max": 1_500_000},
        "33/132": {"mean": 2_800_000, "std": 500_000, "min": 2_000_000, "max": 4_000_000},
        "66/132": {"mean": 3_800_000, "std": 600_000, "min": 2_800_000, "max": 5_000_000},
        "132/275": {"mean": 8_500_000, "std": 1_500_000, "min": 6_000_000, "max": 12_000_000},
        "275/400": {"mean": 16_000_000, "std": 3_000_000, "min": 11_000_000, "max": 22_000_000},
    },
    "protection_relay": {"mean": 35_000, "std": 8_000, "min": 20_000, "max": 55_000},
    "scada_integration": {"mean": 45_000, "std": 12_000, "min": 25_000, "max": 70_000},
    "civils_substation": {"mean": 250_000, "std": 60_000, "min": 150_000, "max": 400_000},
}

# Terrain difficulty multipliers
TERRAIN_FACTORS = {
    "urban": 1.4,
    "suburban": 1.2,
    "rural": 1.0,
    "upland": 1.3,
    "coastal": 1.15,
    "crossing_river": 1.8,
    "crossing_rail": 2.0,
    "crossing_motorway": 1.6,
}

N_SAMPLES = 2000  # Monte Carlo samples


def _sample_cost(spec: dict, n: int = N_SAMPLES) -> list:
    """Generate Monte Carlo samples from a cost spec."""
    samples = []
    for _ in range(n):
        v = random.gauss(spec["mean"], spec["std"])
        v = max(spec["min"], min(spec["max"], v))
        samples.append(v)
    return samples


def estimate_connection_cost(distance_km: float, voltage_kv: int, capacity_mw: float,
                             headroom_mw: float = 0, terrain: str = "rural",
                             connection_type: str = "cable") -> dict:
    """
    Full connection cost estimate with Monte Carlo uncertainty.
    Returns P10/P50/P90 for total and per-component.
    """
    terrain_factor = TERRAIN_FACTORS.get(terrain, 1.0)

    components = []

    # ── 1. Cable or overhead line ──
    if connection_type == "cable":
        cost_table = UNIT_COSTS["cable_underground_per_km"]
    else:
        cost_table = UNIT_COSTS["overhead_line_per_km"]

    vk = min(cost_table.keys(), key=lambda k: abs(k - voltage_kv))
    cable_spec = cost_table[vk]
    cable_samples = [s * distance_km * terrain_factor for s in _sample_cost(cable_spec)]
    components.append({
        "name": f"{'Cable' if connection_type == 'cable' else 'OHL'} ({vk} kV, {distance_km:.1f} km)",
        "category": "cable",
        "samples": cable_samples,
    })

    # ── 2. Switchgear (2 bays — at each end) ──
    sg_table = UNIT_COSTS["switchgear_per_bay"]
    sg_vk = min(sg_table.keys(), key=lambda k: abs(k - voltage_kv))
    sg_samples = [s * 2 for s in _sample_cost(sg_table[sg_vk])]
    components.append({
        "name": f"Switchgear ({sg_vk} kV, 2 bays)",
        "category": "switchgear",
        "samples": sg_samples,
    })

    # ── 3. Transformer (if headroom < capacity) ──
    needs_transformer = headroom_mw < capacity_mw
    if needs_transformer:
        # Find appropriate transformer
        trafo_key = None
        for key in UNIT_COSTS["transformer"]:
            voltages = [int(v) for v in key.split("/")]
            if voltage_kv in voltages:
                trafo_key = key
                break
        if not trafo_key:
            trafo_key = "33/132"  # Default

        trafo_samples = _sample_cost(UNIT_COSTS["transformer"][trafo_key])
        components.append({
            "name": f"Transformer ({trafo_key} kV)",
            "category": "transformer",
            "samples": trafo_samples,
        })

    # ── 4. Protection & SCADA ──
    prot_samples = _sample_cost(UNIT_COSTS["protection_relay"])
    components.append({"name": "Protection relays", "category": "protection", "samples": prot_samples})

    scada_samples = _sample_cost(UNIT_COSTS["scada_integration"])
    components.append({"name": "SCADA integration", "category": "scada", "samples": scada_samples})

    # ── 5. Civils ──
    civils_samples = [s * terrain_factor for s in _sample_cost(UNIT_COSTS["civils_substation"])]
    components.append({"name": "Civil works", "category": "civils", "samples": civils_samples})

    # ── 6. Design & consenting (~10-15%) ──
    subtotal_samples = [sum(c["samples"][i] for c in components) for i in range(N_SAMPLES)]
    design_samples = [s * random.uniform(0.10, 0.15) for s in subtotal_samples]
    components.append({"name": "Design & consenting", "category": "design", "samples": design_samples})

    # ── 7. DNO application fees (~5-8%) ──
    dno_samples = [s * random.uniform(0.05, 0.08) for s in subtotal_samples]
    components.append({"name": "DNO fees", "category": "dno_fees", "samples": dno_samples})

    # ── Total ──
    total_samples = [sum(c["samples"][i] for c in components) for i in range(N_SAMPLES)]
    total_samples.sort()

    # Component summaries
    component_results = []
    for c in components:
        s = sorted(c["samples"])
        component_results.append({
            "name": c["name"],
            "category": c["category"],
            "p10_gbp": round(s[int(N_SAMPLES * 0.1)]),
            "p50_gbp": round(s[int(N_SAMPLES * 0.5)]),
            "p90_gbp": round(s[int(N_SAMPLES * 0.9)]),
        })

    return {
        "parameters": {
            "distance_km": distance_km,
            "voltage_kv": voltage_kv,
            "capacity_mw": capacity_mw,
            "headroom_mw": headroom_mw,
            "terrain": terrain,
            "connection_type": connection_type,
            "needs_transformer": needs_transformer,
        },
        "total": {
            "p10_gbp": round(total_samples[int(N_SAMPLES * 0.1)]),
            "p50_gbp": round(total_samples[int(N_SAMPLES * 0.5)]),
            "p90_gbp": round(total_samples[int(N_SAMPLES * 0.9)]),
            "mean_gbp": round(sum(total_samples) / N_SAMPLES),
        },
        "components": component_results,
        "terrain_factor": terrain_factor,
        "monte_carlo_samples": N_SAMPLES,
    }


def get_benchmarks() -> dict:
    """Return full cost benchmark tables."""
    return {
        "unit_costs": {
            category: {
                str(k): {mk: round(mv) for mk, mv in v.items()} if isinstance(v, dict) and "mean" in v
                else {str(vk): {mk: round(mv) for mk, mv in vv.items()} for vk, vv in v.items()} if isinstance(v, dict) else v
                for k, v in costs.items()
            }
            for category, costs in UNIT_COSTS.items()
        },
        "terrain_factors": TERRAIN_FACTORS,
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
        if cmd == "estimate":
            result = estimate_connection_cost(
                distance_km=req.get("distance_km", 5),
                voltage_kv=req.get("voltage_kv", 132),
                capacity_mw=req.get("capacity_mw", 50),
                headroom_mw=req.get("headroom_mw", 0),
                terrain=req.get("terrain", "rural"),
                connection_type=req.get("connection_type", "cable"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "breakdown":
            # Score individual components
            results = []
            for comp in req.get("components", []):
                r = estimate_connection_cost(**comp)
                results.append(r)
            json.dump({"estimates": results}, sys.stdout)
        elif cmd == "benchmarks":
            json.dump(get_benchmarks(), sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
