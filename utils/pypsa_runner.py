#!/usr/bin/env python3
"""PyPSA runner — subprocess bridge for Tier 3 grid analysis.

Run in .venv-grid/ (Python 3.12) where pandapower lives.
PyPSA needs: pip install pypsa highspy

Usage: echo '{"action":"opf","params":{...}}' | .venv-grid/bin/python utils/pypsa_runner.py
"""

import sys
import json
import logging

log = logging.getLogger(__name__)


def run_opf(params: dict) -> dict:
    """Optimal Power Flow on a network."""
    import pypsa
    import numpy as np

    n = pypsa.Network()

    # Build network from params
    buses = params.get("buses", [])
    for b in buses:
        n.add("Bus", b["name"], v_nom=b.get("v_nom", 132))

    lines = params.get("lines", [])
    for l in lines:
        n.add("Line", l["name"], bus0=l["bus0"], bus1=l["bus1"],
               s_nom=l.get("s_nom", 100), x=l.get("x", 0.1), r=l.get("r", 0.01),
               length=l.get("length_km", 10))

    generators = params.get("generators", [])
    for g in generators:
        n.add("Generator", g["name"], bus=g["bus"],
               p_nom=g.get("p_nom", 50), marginal_cost=g.get("marginal_cost", 30),
               carrier=g.get("carrier", "solar"))

    loads = params.get("loads", [])
    for ld in loads:
        n.add("Load", ld["name"], bus=ld["bus"], p_set=ld.get("p_set", 20))

    # Solve
    status = n.optimize(solver_name="highs")

    return {
        "status": str(status[0]) if isinstance(status, tuple) else str(status),
        "objective": float(n.objective) if hasattr(n, "objective") else None,
        "generator_dispatch": {g: float(n.generators_t.p[g].sum()) for g in n.generators.index} if len(n.generators) else {},
        "line_loading": {l: float(n.lines_t.p0[l].abs().max() / n.lines.s_nom[l] * 100) for l in n.lines.index} if len(n.lines) else {},
    }


def run_lopf(params: dict) -> dict:
    """Linear OPF with investment optimization."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(range(params.get("hours", 24)))

    for b in params.get("buses", []):
        n.add("Bus", b["name"], v_nom=b.get("v_nom", 132))

    for g in params.get("generators", []):
        n.add("Generator", g["name"], bus=g["bus"],
               p_nom_extendable=g.get("extendable", True),
               p_nom_max=g.get("p_nom_max", 500),
               capital_cost=g.get("capital_cost", 500000),
               marginal_cost=g.get("marginal_cost", 0),
               carrier=g.get("carrier", "solar"))

    for s in params.get("storage", []):
        n.add("StorageUnit", s["name"], bus=s["bus"],
               p_nom_extendable=True, p_nom_max=s.get("p_nom_max", 200),
               capital_cost=s.get("capital_cost", 150000),
               max_hours=s.get("max_hours", 4),
               cyclic_state_of_charge=True)

    for ld in params.get("loads", []):
        n.add("Load", ld["name"], bus=ld["bus"], p_set=ld.get("p_set", 50))

    for l in params.get("lines", []):
        n.add("Line", l["name"], bus0=l["bus0"], bus1=l["bus1"],
               s_nom_extendable=l.get("extendable", True),
               s_nom_max=l.get("s_nom_max", 500),
               capital_cost=l.get("capital_cost", 400),
               x=l.get("x", 0.1), length=l.get("length_km", 10))

    status = n.optimize(solver_name="highs")

    return {
        "status": str(status[0]) if isinstance(status, tuple) else str(status),
        "objective": float(n.objective) if hasattr(n, "objective") else None,
        "optimal_capacity": {
            "generators": {g: float(n.generators.p_nom_opt[g]) for g in n.generators.index},
            "storage": {s: float(n.storage_units.p_nom_opt[s]) for s in n.storage_units.index} if len(n.storage_units) else {},
            "lines": {l: float(n.lines.s_nom_opt[l]) for l in n.lines.index},
        },
        "total_cost": float(n.objective) if hasattr(n, "objective") else None,
    }


def expansion_planning(params: dict) -> dict:
    """Network expansion planning with reinforcement cost."""
    result = run_lopf(params)
    # Add reinforcement cost breakdown
    if result.get("optimal_capacity"):
        costs = {}
        for cat, items in result["optimal_capacity"].items():
            for name, mw in items.items():
                if mw > 0:
                    costs[name] = {"capacity_mw": round(mw, 2), "category": cat}
        result["reinforcement_breakdown"] = costs
    return result


def hosting_capacity(params: dict) -> dict:
    """Binary search for maximum generation at a bus."""
    import pypsa

    bus_id = params["bus_id"]
    max_mw = params.get("max_mw", 500)
    network_params = params.get("network", {})

    lo, hi = 0, max_mw
    best = 0

    for _ in range(20):  # Binary search iterations
        mid = (lo + hi) / 2
        test_params = {**network_params}
        # Add test generator
        test_params.setdefault("generators", []).append({
            "name": "test_gen", "bus": bus_id, "p_nom": mid,
            "marginal_cost": 0, "carrier": "solar",
        })

        try:
            n = pypsa.Network()
            for b in test_params.get("buses", []):
                n.add("Bus", b["name"], v_nom=b.get("v_nom", 132))
            for l in test_params.get("lines", []):
                n.add("Line", l["name"], bus0=l["bus0"], bus1=l["bus1"],
                       s_nom=l.get("s_nom", 100), x=l.get("x", 0.1))
            for g in test_params.get("generators", []):
                n.add("Generator", g["name"], bus=g["bus"], p_nom=g.get("p_nom", 50),
                       marginal_cost=g.get("marginal_cost", 30))
            for ld in test_params.get("loads", []):
                n.add("Load", ld["name"], bus=ld["bus"], p_set=ld.get("p_set", 20))

            n.optimize(solver_name="highs")

            # Check constraints
            violations = False
            for l in n.lines.index:
                if hasattr(n.lines_t, "p0") and len(n.lines_t.p0) > 0:
                    loading = abs(float(n.lines_t.p0[l].max())) / float(n.lines.s_nom[l])
                    if loading > 1.0:
                        violations = True
                        break

            if violations:
                hi = mid
            else:
                best = mid
                lo = mid
        except Exception:
            hi = mid

        test_params.get("generators", []).pop()

    return {
        "bus_id": bus_id,
        "hosting_capacity_mw": round(best, 1),
        "search_range_mw": [0, max_mw],
    }


ACTIONS = {
    "opf": run_opf,
    "lopf": run_lopf,
    "expansion": expansion_planning,
    "hosting_capacity": hosting_capacity,
}


def main():
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    action = data.get("action")
    if action not in ACTIONS:
        json.dump({"error": f"Unknown action: {action}. Valid: {list(ACTIONS.keys())}"}, sys.stdout)
        return

    try:
        result = ACTIONS[action](data.get("params", {}))
        json.dump(result, sys.stdout, default=str)
    except Exception as e:
        json.dump({"error": str(e), "type": type(e).__name__}, sys.stdout)


if __name__ == "__main__":
    main()
