#!/usr/bin/env python3
"""
Grid Power Flow — pandapower-based Tier 2 connection assessment.

Called as a subprocess from the FastAPI backend because pandapower requires
Python ≤3.12 (the main backend runs Python 3.14).

Usage (stdin/stdout JSON bridge):
    echo '{"substations": [...], "lines": [...], "proposed": {...}}' | \
        .venv-grid/bin/python utils/grid_power_flow.py

Input JSON:
    {
        "substations": [
            {"id": 1, "name": "...", "voltage_kv": 33, "demand_mw": 10,
             "generation_mw": 5, "transformer_rating_mva": 40, ...},
        ],
        "lines": [
            {"from_id": 1, "to_id": 2, "voltage_kv": 33, "length_km": 5, "circuits": 1},
        ],
        "proposed": {
            "capacity_mw": 5, "technology": "solar",
            "connection_substation_id": 1, "power_factor": 0.95,
        },
        "options": {
            "contingency": false,   // N-1 analysis
            "max_loading_pct": 100,
            "voltage_limits": [0.94, 1.06],
        }
    }

Output JSON:
    {
        "success": true,
        "converged": true,
        "bus_results": [...],
        "line_results": [...],
        "trafo_results": [...],
        "violations": [...],
        "summary": {
            "max_voltage_pu": 1.04, "min_voltage_pu": 0.97,
            "max_loading_pct": 65.2, "voltage_rise_pu": 0.03,
            "reverse_power_flow": false,
            "thermal_headroom_mw": 12.5,
        },
        "verdict": "PASS" | "MARGINAL" | "FAIL",
        "notes": [...],
    }
"""

import copy
import json
import sys
import traceback

import numpy as np

try:
    import pandapower as pp
    from pandapower.run import runpp
except ImportError:
    print(json.dumps({"success": False, "error": "pandapower not installed"}))
    sys.exit(1)

try:
    from lightsim2grid import LightSimBackend
    HAS_LIGHTSIM = True
except ImportError:
    HAS_LIGHTSIM = False


# ─── UK Standard Parameters ────────────────────────────────────────────

# Typical UK cable impedances (R, X in ohm/km) by voltage
CABLE_PARAMS = {
    11:  {"r_ohm_per_km": 0.411, "x_ohm_per_km": 0.101, "c_nf_per_km": 240, "max_i_ka": 0.300},
    33:  {"r_ohm_per_km": 0.130, "x_ohm_per_km": 0.115, "c_nf_per_km": 180, "max_i_ka": 0.490},
    66:  {"r_ohm_per_km": 0.060, "x_ohm_per_km": 0.110, "c_nf_per_km": 160, "max_i_ka": 0.650},
    132: {"r_ohm_per_km": 0.035, "x_ohm_per_km": 0.105, "c_nf_per_km": 140, "max_i_ka": 0.850},
}

# Typical UK transformer parameters (Z%, loss%)
TRAFO_PARAMS = {
    "33/11":  {"vk_percent": 10.0, "vkr_percent": 0.5, "pfe_kw": 3.0, "i0_percent": 0.1},
    "66/33":  {"vk_percent": 12.0, "vkr_percent": 0.4, "pfe_kw": 5.0, "i0_percent": 0.08},
    "132/33": {"vk_percent": 15.0, "vkr_percent": 0.3, "pfe_kw": 15.0, "i0_percent": 0.06},
    "132/66": {"vk_percent": 14.0, "vkr_percent": 0.3, "pfe_kw": 12.0, "i0_percent": 0.06},
}

# UK statutory voltage limits (Engineering Recommendation P28/P29)
UK_VOLTAGE_LIMITS = {
    11:  (0.94, 1.06),  # +6% / -6%
    33:  (0.94, 1.06),
    66:  (0.95, 1.05),
    132: (0.95, 1.05),
    275: (0.95, 1.05),
    400: (0.95, 1.05),
}


def build_network(substations, lines, proposed, options=None):
    """
    Build a pandapower network from substation and line data.

    Creates a realistic UK distribution/sub-transmission model with:
    - External grid (slack bus) at highest voltage substation
    - Buses for each substation
    - Lines between connected substations
    - Transformers where voltage changes
    - Existing loads and generators
    - Proposed new generator/load
    """
    options = options or {}
    net = pp.create_empty_network(name="princeps_grid_connection", f_hz=50.0)

    # Index mapping: substation_id -> pandapower bus index
    bus_map = {}

    # Sort substations by voltage (highest first = slack bus candidate)
    subs_sorted = sorted(substations, key=lambda s: s.get("voltage_kv") or 0, reverse=True)

    if not subs_sorted:
        return None, "No substations provided"

    # Create buses
    for sub in subs_sorted:
        vn_kv = sub.get("voltage_kv") or 33.0
        bus_idx = pp.create_bus(
            net,
            vn_kv=vn_kv,
            name=sub.get("name", f"bus_{sub['id']}"),
            type="b",  # busbar
            max_vm_pu=UK_VOLTAGE_LIMITS.get(int(vn_kv), (0.94, 1.06))[1],
            min_vm_pu=UK_VOLTAGE_LIMITS.get(int(vn_kv), (0.94, 1.06))[0],
        )
        bus_map[sub["id"]] = bus_idx

        # Add existing load
        demand = sub.get("demand_mw")
        if demand and demand > 0:
            pp.create_load(
                net, bus_idx,
                p_mw=demand,
                q_mvar=demand * 0.33,  # PF ~0.95 lagging
                name=f"load_{sub['name']}",
            )

        # Add existing generation (as static generator)
        gen_mw = sub.get("generation_mw")
        if gen_mw and gen_mw > 0:
            pp.create_sgen(
                net, bus_idx,
                p_mw=gen_mw,
                q_mvar=0,  # Unity PF for existing DG
                name=f"gen_{sub['name']}",
            )

    # Create external grid (slack) at highest voltage bus
    slack_sub = subs_sorted[0]
    slack_bus = bus_map[slack_sub["id"]]
    pp.create_ext_grid(
        net, slack_bus,
        vm_pu=1.0,
        name="grid_supply",
        s_sc_max_mva=(slack_sub.get("fault_level_ka") or 20) * (slack_sub.get("voltage_kv") or 132) * 1.732,
        rx_max=0.1,
    )

    # Create lines between substations
    for line in lines:
        from_id = line.get("from_id")
        to_id = line.get("to_id")
        if from_id not in bus_map or to_id not in bus_map:
            continue

        from_bus = bus_map[from_id]
        to_bus = bus_map[to_id]
        vkv = line.get("voltage_kv") or 33
        length = line.get("length_km") or 1.0
        circuits = line.get("circuits") or 1

        params = CABLE_PARAMS.get(int(vkv), CABLE_PARAMS[33])

        for c in range(circuits):
            pp.create_line_from_parameters(
                net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=length,
                r_ohm_per_km=params["r_ohm_per_km"],
                x_ohm_per_km=params["x_ohm_per_km"],
                c_nf_per_km=params["c_nf_per_km"],
                max_i_ka=params["max_i_ka"],
                name=f"line_{from_id}_{to_id}_c{c}",
            )

    # Create transformers where adjacent substations have different voltages
    processed_pairs = set()
    for line in lines:
        from_id = line.get("from_id")
        to_id = line.get("to_id")
        if from_id not in bus_map or to_id not in bus_map:
            continue

        pair = tuple(sorted([from_id, to_id]))
        if pair in processed_pairs:
            continue

        from_sub = next((s for s in substations if s["id"] == from_id), None)
        to_sub = next((s for s in substations if s["id"] == to_id), None)
        if not from_sub or not to_sub:
            continue

        v1 = from_sub.get("voltage_kv") or 33
        v2 = to_sub.get("voltage_kv") or 33

        if v1 != v2:
            processed_pairs.add(pair)
            hv = max(v1, v2)
            lv = min(v1, v2)
            hv_bus = bus_map[from_id] if v1 > v2 else bus_map[to_id]
            lv_bus = bus_map[to_id] if v1 > v2 else bus_map[from_id]

            trafo_key = f"{int(hv)}/{int(lv)}"
            tparams = TRAFO_PARAMS.get(trafo_key, TRAFO_PARAMS.get("33/11"))

            # Rating from transformer data or estimate
            hv_sub = from_sub if v1 > v2 else to_sub
            rating = hv_sub.get("transformer_rating_mva") or max(hv, lv) * 0.3

            pp.create_transformer_from_parameters(
                net,
                hv_bus=hv_bus,
                lv_bus=lv_bus,
                sn_mva=rating,
                vn_hv_kv=hv,
                vn_lv_kv=lv,
                vk_percent=tparams["vk_percent"],
                vkr_percent=tparams["vkr_percent"],
                pfe_kw=tparams["pfe_kw"],
                i0_percent=tparams["i0_percent"],
                name=f"trafo_{int(hv)}_{int(lv)}",
            )

    # Add proposed connection
    conn_sub_id = proposed.get("connection_substation_id")
    if conn_sub_id and conn_sub_id in bus_map:
        conn_bus = bus_map[conn_sub_id]
        cap = proposed.get("capacity_mw", 5)
        pf = proposed.get("power_factor", 0.95)
        tech = proposed.get("technology", "solar")

        if tech in ("solar", "wind", "bess"):
            # Generator
            q_mvar = cap * ((1 - pf**2) ** 0.5) / pf if pf < 1 else 0
            pp.create_sgen(
                net, conn_bus,
                p_mw=cap,
                q_mvar=-q_mvar,  # Absorbing reactive (typical inverter)
                name="proposed_generator",
                type=tech,
            )
        else:
            # Demand connection
            q_mvar = cap * 0.33  # PF ~0.95
            pp.create_load(
                net, conn_bus,
                p_mw=cap,
                q_mvar=q_mvar,
                name="proposed_load",
            )

    return net, bus_map


def run_power_flow(net, options=None):
    """
    Run Newton-Raphson power flow and extract results.
    Uses lightsim2grid backend if available for 10-20x speedup.
    """
    options = options or {}
    voltage_limits = options.get("voltage_limits", [0.94, 1.06])
    max_loading = options.get("max_loading_pct", 100)

    try:
        if HAS_LIGHTSIM:
            pp.runpp(net, algorithm="nr", numba=False, lightsim2grid=True)
        else:
            pp.runpp(net, algorithm="nr", numba=False)
    except pp.LoadflowNotConverged:
        return {
            "success": True,
            "converged": False,
            "verdict": "FAIL",
            "notes": ["Power flow did not converge — network may be unstable with proposed connection"],
            "summary": {},
            "violations": [{"type": "convergence", "detail": "Newton-Raphson did not converge"}],
            "bus_results": [],
            "line_results": [],
            "trafo_results": [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Power flow error: {str(e)}",
        }

    # Extract bus results
    bus_results = []
    for idx in net.bus.index:
        if idx in net.res_bus.index:
            vm = float(net.res_bus.at[idx, "vm_pu"])
            va = float(net.res_bus.at[idx, "va_degree"])
            p = float(net.res_bus.at[idx, "p_mw"])
            q = float(net.res_bus.at[idx, "q_mvar"])
            bus_results.append({
                "bus_idx": int(idx),
                "name": net.bus.at[idx, "name"],
                "vn_kv": float(net.bus.at[idx, "vn_kv"]),
                "vm_pu": round(vm, 4),
                "va_degree": round(va, 2),
                "p_mw": round(p, 3),
                "q_mvar": round(q, 3),
            })

    # Extract line results
    line_results = []
    for idx in net.line.index:
        if idx in net.res_line.index:
            loading = float(net.res_line.at[idx, "loading_percent"])
            p_from = float(net.res_line.at[idx, "p_from_mw"])
            p_to = float(net.res_line.at[idx, "p_to_mw"])
            pl = float(net.res_line.at[idx, "pl_mw"])
            line_results.append({
                "line_idx": int(idx),
                "name": net.line.at[idx, "name"],
                "loading_pct": round(loading, 1),
                "p_from_mw": round(p_from, 3),
                "p_to_mw": round(p_to, 3),
                "losses_mw": round(pl, 4),
            })

    # Extract transformer results
    trafo_results = []
    for idx in net.trafo.index:
        if idx in net.res_trafo.index:
            loading = float(net.res_trafo.at[idx, "loading_percent"])
            p_hv = float(net.res_trafo.at[idx, "p_hv_mw"])
            p_lv = float(net.res_trafo.at[idx, "p_lv_mw"])
            pl = float(net.res_trafo.at[idx, "pl_mw"])
            trafo_results.append({
                "trafo_idx": int(idx),
                "name": net.trafo.at[idx, "name"],
                "loading_pct": round(loading, 1),
                "p_hv_mw": round(p_hv, 3),
                "p_lv_mw": round(p_lv, 3),
                "losses_mw": round(pl, 4),
            })

    # Analyse violations
    violations = []
    notes = []

    voltages = [b["vm_pu"] for b in bus_results]
    max_v = max(voltages) if voltages else 1.0
    min_v = min(voltages) if voltages else 1.0
    v_low, v_high = voltage_limits

    if max_v > v_high:
        over_buses = [b for b in bus_results if b["vm_pu"] > v_high]
        for b in over_buses:
            violations.append({
                "type": "overvoltage",
                "bus": b["name"],
                "value": b["vm_pu"],
                "limit": v_high,
                "detail": f"Voltage {b['vm_pu']:.4f} pu exceeds {v_high} pu at {b['name']}",
            })

    if min_v < v_low:
        under_buses = [b for b in bus_results if b["vm_pu"] < v_low]
        for b in under_buses:
            violations.append({
                "type": "undervoltage",
                "bus": b["name"],
                "value": b["vm_pu"],
                "limit": v_low,
                "detail": f"Voltage {b['vm_pu']:.4f} pu below {v_low} pu at {b['name']}",
            })

    # Thermal overloads
    all_loadings = [l["loading_pct"] for l in line_results] + [t["loading_pct"] for t in trafo_results]
    max_load = max(all_loadings) if all_loadings else 0

    for l in line_results:
        if l["loading_pct"] > max_loading:
            violations.append({
                "type": "thermal_overload",
                "element": l["name"],
                "loading_pct": l["loading_pct"],
                "limit": max_loading,
                "detail": f"Line {l['name']} loaded to {l['loading_pct']:.1f}% (limit {max_loading}%)",
            })

    for t in trafo_results:
        if t["loading_pct"] > max_loading:
            violations.append({
                "type": "thermal_overload",
                "element": t["name"],
                "loading_pct": t["loading_pct"],
                "limit": max_loading,
                "detail": f"Transformer {t['name']} loaded to {t['loading_pct']:.1f}% (limit {max_loading}%)",
            })

    # Check for reverse power flow (generation > demand at slack)
    slack_bus = bus_results[0] if bus_results else None
    reverse_flow = False
    if slack_bus and slack_bus["p_mw"] > 0:
        reverse_flow = True
        notes.append("Reverse power flow detected at grid supply point — export to transmission")

    # Voltage rise at connection point
    conn_bus_name = "proposed_generator"
    conn_sgen = net.sgen[net.sgen["name"] == conn_bus_name]
    voltage_rise = 0.0
    if len(conn_sgen) > 0:
        conn_bus_idx = int(conn_sgen.iloc[0]["bus"])
        if conn_bus_idx in net.res_bus.index:
            voltage_rise = float(net.res_bus.at[conn_bus_idx, "vm_pu"]) - 1.0

    # Calculate thermal headroom (how much more capacity before overload)
    thermal_headroom = None
    if max_load < max_loading and max_load > 0:
        headroom_factor = (max_loading - max_load) / max_load
        proposed_mw = 0
        if len(conn_sgen) > 0:
            proposed_mw = float(conn_sgen.iloc[0]["p_mw"])
        if proposed_mw > 0:
            thermal_headroom = round(proposed_mw * headroom_factor, 1)

    # Summary
    summary = {
        "max_voltage_pu": round(max_v, 4),
        "min_voltage_pu": round(min_v, 4),
        "max_loading_pct": round(max_load, 1),
        "voltage_rise_pu": round(voltage_rise, 4),
        "reverse_power_flow": reverse_flow,
        "thermal_headroom_mw": thermal_headroom,
        "total_losses_mw": round(sum(l["losses_mw"] for l in line_results) + sum(t["losses_mw"] for t in trafo_results), 3),
        "bus_count": len(bus_results),
        "line_count": len(line_results),
        "trafo_count": len(trafo_results),
    }

    # Derive verdict
    if not violations:
        if max_load > 80 or abs(voltage_rise) > 0.03:
            verdict = "MARGINAL"
            notes.append(f"No violations but operating margins are tight (max loading {max_load:.0f}%, voltage rise {voltage_rise:.3f} pu)")
        else:
            verdict = "PASS"
            notes.append(f"All bus voltages within limits ({min_v:.3f}–{max_v:.3f} pu)")
            notes.append(f"Maximum thermal loading {max_load:.1f}% — within limits")
    else:
        voltage_viols = [v for v in violations if v["type"] in ("overvoltage", "undervoltage")]
        thermal_viols = [v for v in violations if v["type"] == "thermal_overload"]
        if thermal_viols:
            verdict = "FAIL"
            notes.append(f"Thermal overload detected on {len(thermal_viols)} element(s)")
        elif voltage_viols:
            if all(abs(v["value"] - 1.0) < 0.08 for v in voltage_viols):
                verdict = "MARGINAL"
                notes.append("Minor voltage limit exceedance — may be managed with reactive power control")
            else:
                verdict = "FAIL"
                notes.append(f"Voltage violations at {len(voltage_viols)} bus(es)")
        else:
            verdict = "MARGINAL"

    return {
        "success": True,
        "converged": True,
        "verdict": verdict,
        "summary": summary,
        "violations": violations,
        "notes": notes,
        "bus_results": bus_results,
        "line_results": line_results,
        "trafo_results": trafo_results,
    }


def run_contingency(net, options=None):
    """
    N-1 contingency analysis — check if network survives each line/trafo outage.
    """
    options = options or {}
    results = []

    # Test each line outage
    for idx in net.line.index:
        net_copy = copy.deepcopy(net)
        net_copy.line.at[idx, "in_service"] = False
        try:
            pp.runpp(net_copy, algorithm="nr", numba=False)
            max_loading = float(net_copy.res_line["loading_percent"].max()) if len(net_copy.res_line) > 0 else 0
            max_v = float(net_copy.res_bus["vm_pu"].max()) if len(net_copy.res_bus) > 0 else 1
            min_v = float(net_copy.res_bus["vm_pu"].min()) if len(net_copy.res_bus) > 0 else 1
            results.append({
                "element": f"line_{net.line.at[idx, 'name']}",
                "converged": True,
                "max_loading_pct": round(max_loading, 1),
                "max_voltage_pu": round(max_v, 4),
                "min_voltage_pu": round(min_v, 4),
                "pass": max_loading <= 100 and min_v >= 0.94 and max_v <= 1.06,
            })
        except Exception:
            results.append({
                "element": f"line_{net.line.at[idx, 'name']}",
                "converged": False,
                "pass": False,
            })

    # Test each transformer outage
    for idx in net.trafo.index:
        net_copy = copy.deepcopy(net)
        net_copy.trafo.at[idx, "in_service"] = False
        try:
            pp.runpp(net_copy, algorithm="nr", numba=False)
            max_loading = float(net_copy.res_line["loading_percent"].max()) if len(net_copy.res_line) > 0 else 0
            max_v = float(net_copy.res_bus["vm_pu"].max()) if len(net_copy.res_bus) > 0 else 1
            min_v = float(net_copy.res_bus["vm_pu"].min()) if len(net_copy.res_bus) > 0 else 1
            results.append({
                "element": f"trafo_{net.trafo.at[idx, 'name']}",
                "converged": True,
                "max_loading_pct": round(max_loading, 1),
                "max_voltage_pu": round(max_v, 4),
                "min_voltage_pu": round(min_v, 4),
                "pass": max_loading <= 100 and min_v >= 0.94 and max_v <= 1.06,
            })
        except Exception:
            results.append({
                "element": f"trafo_{net.trafo.at[idx, 'name']}",
                "converged": False,
                "pass": False,
            })

    failed = [r for r in results if not r["pass"]]
    return {
        "total_contingencies": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "n1_secure": len(failed) == 0,
        "results": results,
        "worst_case": max(results, key=lambda r: r.get("max_loading_pct", 0)) if results else None,
    }


def main():
    """Read JSON from stdin, run power flow, write JSON to stdout."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"success": False, "error": "Empty input"}))
            sys.exit(1)

        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    substations = data.get("substations", [])
    lines = data.get("lines", [])
    proposed = data.get("proposed", {})
    options = data.get("options", {})

    if not substations:
        print(json.dumps({"success": False, "error": "No substations provided"}))
        sys.exit(1)

    # Build network
    net, bus_map_or_error = build_network(substations, lines, proposed, options)
    if net is None:
        print(json.dumps({"success": False, "error": bus_map_or_error}))
        sys.exit(1)

    # Run power flow
    result = run_power_flow(net, options)

    # Optionally run N-1 contingency
    if options.get("contingency") and result.get("converged"):
        result["contingency"] = run_contingency(net, options)

    # Serialise (handle numpy types)
    print(json.dumps(result, default=_json_serialise))


def _json_serialise(obj):
    """Handle numpy types for JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


if __name__ == "__main__":
    main()
