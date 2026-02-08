"""
Grid Stability Predictor — DSGC (Decentral Smart Grid Control) model.

Based on Schäfer et al. "Decentral Smart Grid Control" (2015).
Adapted from kaymen99/AI-for-energy-sector grid stability prediction.

For a star-topology subgraph (1 supplier + N consumers), stability depends on:
  - tau_i: reaction time of each node's controller (seconds)
  - p_i: nominal power (positive = generation, negative = consumption)
  - gamma_i: price elasticity coefficient (willingness to adjust consumption)

Stability criterion: the system is linearly stable iff the maximum real part
of the eigenvalues of the Jacobian is <= 0.

For a 2-node simplified case: stable when tau * |p| / gamma < 1
For N-node star: eigenvalue analysis of the coupling matrix.

This module assigns DSGC parameters to our real 292-node UK grid and computes
per-node stability under user-adjustable scenarios.
"""

import math
import random
from typing import Optional

_RNG = random.Random(99)  # Dedicated RNG instance

# Default scenario parameters (can be overridden by user)
DEFAULT_SCENARIO = {
    "tau_base": 4.0,       # Base reaction time (seconds)
    "gamma_base": 0.5,     # Base price elasticity
    "demand_scale": 1.0,   # Demand multiplier (1.0 = normal)
    "renewable_pen": 0.3,  # Renewable penetration (0-1)
    "ev_load": 0.0,        # Additional EV charging load (MW per node)
    "storage_factor": 0.0, # Battery storage dampening (0-1)
}


def _node_dsgc_params(node: dict, scenario: dict) -> dict:
    """Assign DSGC parameters to a grid node based on its properties."""
    voltage = node["voltage_kv"]
    demand = node["demand_mw"]
    ntype = node["node_type"]

    # Reaction time: higher voltage = faster response, BSPs slower
    tau_mult = 1.0 if voltage >= 400 else (1.3 if voltage >= 275 else 1.8)
    tau = scenario["tau_base"] * tau_mult

    # Power: normalized to DSGC scale (-2 to +5 range)
    # Map real MW demand to normalized units (divide by reference power ~200MW)
    REF_POWER = 200.0
    net_power = (demand * scenario["demand_scale"]) / REF_POWER

    # Renewable intermittency adds volatility to power balance
    renewable_noise = scenario["renewable_pen"] * _RNG.uniform(-0.3, 0.3)
    p = -net_power * (1.0 + renewable_noise)

    # EV load (normalized)
    p -= (scenario["ev_load"] / REF_POWER) * (demand / 300.0)

    # Price elasticity: higher voltage nodes are less elastic (inertia)
    gamma = scenario["gamma_base"]
    if voltage >= 400:
        gamma *= 0.7
    elif voltage >= 275:
        gamma *= 0.85

    # Battery storage reduces instability (faster virtual inertia response)
    storage_dampening = 1.0 - (scenario["storage_factor"] * 0.6)
    tau *= storage_dampening
    # Storage also absorbs power fluctuations
    p *= (1.0 - scenario["storage_factor"] * 0.3)

    return {"tau": tau, "p": p, "gamma": gamma}


def _star_stability(center_params: dict, neighbor_params: list[dict]) -> dict:
    """
    Compute DSGC stability for a star subgraph.

    Uses the simplified criterion from Auer et al. (2016):
    For each consumer node i connected to a central node:
      coupling_i = |p_i| / (tau_i * gamma_i)

    The system is unstable if max(coupling) exceeds a critical threshold
    that depends on the number of connected nodes.

    Returns dict with stability_score (0=very unstable, 1=very stable),
    is_stable (bool), and dominant eigenvalue estimate.
    """
    if not neighbor_params:
        return {"stability_score": 0.5, "is_stable": True, "max_eigenvalue": 0.0}

    n = len(neighbor_params)
    all_params = [center_params] + neighbor_params

    # Compute coupling strength for each node in the subgraph
    couplings = []
    for params in all_params:
        tau = max(params["tau"], 0.1)
        gamma = max(params["gamma"], 0.01)
        p = abs(params["p"])
        coupling = p / (tau * gamma)
        couplings.append(coupling)

    max_coupling = max(couplings)
    avg_coupling = sum(couplings) / len(couplings)

    # Critical threshold: increases with connectivity (more neighbors = more stable)
    # Based on algebraic connectivity of star graph
    # Higher connectivity provides more inertia → higher critical threshold
    critical = 1.2 + 0.5 * math.log(n + 1)

    # Dominant eigenvalue estimate (simplified)
    # Real part of max eigenvalue ≈ max_coupling - critical
    max_eigenvalue = max_coupling - critical

    # Stability score: 1 = very stable, 0 = very unstable
    # Map eigenvalue to [0, 1] range using sigmoid-like function
    clamped = max(-20.0, min(20.0, 2.0 * max_eigenvalue))
    stability_score = 1.0 / (1.0 + math.exp(clamped))

    return {
        "stability_score": round(stability_score, 3),
        "is_stable": max_eigenvalue <= 0,
        "max_eigenvalue": round(max_eigenvalue, 3),
        "max_coupling": round(max_coupling, 3),
        "avg_coupling": round(avg_coupling, 3),
        "critical_threshold": round(critical, 3),
    }


def predict_grid_stability(nodes: list[dict], edges: list[dict],
                           scenario: Optional[dict] = None) -> dict:
    """
    Predict stability for every node in the grid under a given scenario.

    Args:
        nodes: list of node dicts from build_topology()
        edges: list of edge dicts from build_topology()
        scenario: dict overriding DEFAULT_SCENARIO keys

    Returns:
        dict with per-node stability, summary stats, and scenario echo
    """
    sc = {**DEFAULT_SCENARIO, **(scenario or {})}

    # Build adjacency
    name_to_idx = {n["name"]: i for i, n in enumerate(nodes)}
    adj: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
    for e in edges:
        i = name_to_idx.get(e["from_name"])
        j = name_to_idx.get(e["to_name"])
        if i is not None and j is not None:
            adj[i].append(j)
            adj[j].append(i)

    # Reset RNG for reproducibility across calls
    _RNG.seed(99)
    # Compute DSGC params for each node
    dsgc_params = [_node_dsgc_params(n, sc) for n in nodes]

    # Per-node stability (using local star subgraph)
    results = []
    stable_count = 0
    total_score = 0.0

    for i, node in enumerate(nodes):
        neighbors = adj[i]
        center_p = dsgc_params[i]
        neighbor_p = [dsgc_params[j] for j in neighbors]

        stab = _star_stability(center_p, neighbor_p)

        if stab["is_stable"]:
            stable_count += 1
        total_score += stab["stability_score"]

        results.append({
            "node_id": node["id"],
            "name": node["name"],
            "lat": node["lat"],
            "lon": node["lon"],
            "voltage_kv": node["voltage_kv"],
            "node_type": node["node_type"],
            "demand_mw": node["demand_mw"],
            "stability_score": stab["stability_score"],
            "is_stable": stab["is_stable"],
            "max_eigenvalue": stab["max_eigenvalue"],
            "connections": len(neighbors),
            "tau": round(dsgc_params[i]["tau"], 2),
            "power": round(dsgc_params[i]["p"], 1),
            "gamma": round(dsgc_params[i]["gamma"], 3),
        })

    n_total = len(nodes)
    n_unstable = n_total - stable_count
    avg_score = total_score / n_total if n_total else 0

    # Identify most vulnerable nodes
    results.sort(key=lambda r: r["stability_score"])
    vulnerable = results[:10]

    # Cascade risk assessment
    cascade_risk = "low"
    pct_unstable = n_unstable / n_total if n_total else 0
    if pct_unstable > 0.5:
        cascade_risk = "critical"
    elif pct_unstable > 0.3:
        cascade_risk = "high"
    elif pct_unstable > 0.15:
        cascade_risk = "moderate"

    # Re-sort by node_id for consistent output
    results.sort(key=lambda r: r["node_id"])

    return {
        "nodes": results,
        "summary": {
            "total_nodes": n_total,
            "stable_count": stable_count,
            "unstable_count": n_unstable,
            "percent_stable": round(stable_count / n_total * 100, 1) if n_total else 0,
            "avg_stability_score": round(avg_score, 3),
            "cascade_risk": cascade_risk,
        },
        "vulnerable_top10": vulnerable,
        "scenario": sc,
    }
