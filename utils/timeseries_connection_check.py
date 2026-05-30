#!/usr/bin/env python3
# Adapted from TU Delft AI Energy Lab LLM-Electricity-Contracts (BSD-3-Clause).
# Original: SME connection/smeOberrhein.py by Jochen L. Cremer.
# Reference: Cremer, J.L. "Customising Electricity Contracts at Scale with LLMs"
#            arXiv:2505.19551 (2025).
"""
Time-series AC power-flow feasibility check (Princeps generic version).

Runs `pandapower.timeseries.run_timeseries` over a 24-hour or 8760-hour
load profile and reports voltage / line-loading violations per timestep.

Subprocess JSON bridge (matches utils/grid_power_flow.py).

Usage:
    echo '{...}' | .venv-grid/bin/python utils/timeseries_connection_check.py

Input JSON:
    {
        "substations": [...],          # same shape as grid_power_flow.py
        "lines":       [...],
        "proposed":    {...},          # optional new connection
        "load_profile": {              # MW per hour, per (existing) load index
            "0": [1.2, 1.1, ...],      # 24 or 8760 values
            "1": [...],
            ...
            "scale_only": [...]        # alternative: single scalar series scaling base loads
        },
        "options": {
            "voltage_limits": [0.94, 1.06],
            "loading_limits": [0, 100],
            "snapshot_hours":  24       # or 8760
        }
    }

Output JSON:
    {
        "feasible": bool,
        "hours_with_voltage_violation": [int, ...],
        "hours_with_thermal_violation": [int, ...],
        "worst_voltage_pu": float,
        "worst_loading_pct": float,
        "voltage_per_hour": [float, ...],   # min vm_pu per hour (chart series)
        "loading_per_hour": [float, ...],   # max loading_pct per hour
        "per_bus_violation_count": {bus_name: int},
        "per_line_violation_count": {line_name: int},
        "summary": str
    }
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

import numpy as np
import pandas as pd

try:
    import pandapower as pp
    from pandapower.control import ConstControl
    from pandapower.timeseries import DFData, OutputWriter, run_timeseries
except ImportError:
    print(json.dumps({"success": False, "error": "pandapower not installed"}))
    sys.exit(1)

# Re-use the network-builder shipped in grid_power_flow.py so the two
# subprocess scripts produce identical pandapower topologies.
try:
    from grid_power_flow import build_network  # type: ignore
except ImportError:
    # When invoked from FastAPI we run with cwd=utils/, but defensive fallback:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from grid_power_flow import build_network  # type: ignore


# ─── Defaults ──────────────────────────────────────────────────────────
# Mirrors TU Delft `smeOberrhein.py` lines 38-40 but exposed as input options.
DEFAULT_VOLT_LIMITS = (0.94, 1.06)
DEFAULT_LOADING_LIMITS = (0.0, 100.0)
DEFAULT_N_TS = 24


# UK domestic-style demand shape (24h, peak 18-20h). Used when load_profile
# only provides `scale_only` and we need to broadcast to bus-level profiles.
# Numbers from BEIS Elexon GSP profile class 1 (normalised).
UK_24H_PROFILE = np.array([
    0.42, 0.38, 0.36, 0.36, 0.38, 0.44, 0.58, 0.74, 0.80, 0.78,
    0.74, 0.72, 0.74, 0.74, 0.74, 0.76, 0.84, 1.00, 1.00, 0.94,
    0.86, 0.74, 0.62, 0.48,
])


def _build_load_dataframe(net, load_profile: dict | None, n_ts: int) -> pd.DataFrame:
    """Build a (n_ts, n_loads) MW dataframe.

    Three modes:
      1) per-load arrays  — keys are load element indices (as strings)
      2) {"scale_only": [...]} — single series multiplies base p_mw
      3) None — synthesise UK domestic profile from base loads
    """
    n_loads = len(net.load)
    if n_loads == 0:
        return pd.DataFrame(index=np.arange(n_ts))

    base = net.load.p_mw.values.astype(float)  # shape (n_loads,)

    if load_profile and any(k.isdigit() for k in load_profile.keys()):
        # Mode 1 — explicit per-load arrays
        data = np.tile(base, (n_ts, 1))  # (n_ts, n_loads) — defaults to base
        for key, series in load_profile.items():
            if not key.isdigit():
                continue
            idx = int(key)
            arr = np.asarray(series, dtype=float)
            if len(arr) != n_ts:
                continue
            if idx < n_loads:
                # the supplied series replaces (not adds) base
                data[:, idx] = arr
        df = pd.DataFrame(data, index=np.arange(n_ts), columns=net.load.index.values)
        return df

    # Modes 2 + 3 — derive shape, then multiply each base load
    if load_profile and isinstance(load_profile.get("scale_only"), list):
        shape = np.asarray(load_profile["scale_only"], dtype=float)
        if len(shape) != n_ts:
            shape = np.resize(shape, n_ts)
    else:
        # Tile UK profile to fill n_ts hours
        reps = int(np.ceil(n_ts / len(UK_24H_PROFILE)))
        shape = np.tile(UK_24H_PROFILE, reps)[:n_ts]

    # shape (n_ts, n_loads) = outer product of shape × base
    data = np.outer(shape, base)
    df = pd.DataFrame(data, index=np.arange(n_ts), columns=net.load.index.values)
    return df


def _build_sgen_dataframe(net, n_ts: int) -> pd.DataFrame:
    """Solar-like diurnal profile applied to all sgens (placeholder; project
    can override with explicit per-sgen series later).
    """
    n_sgen = len(net.sgen)
    if n_sgen == 0:
        return pd.DataFrame(index=np.arange(n_ts))

    base = net.sgen.p_mw.values.astype(float)
    # Half-sine over 24h, zero outside ~06-18h. Tile across n_ts.
    hour = np.arange(n_ts) % 24
    shape = np.maximum(0, np.sin(np.pi * (hour - 6) / 12))
    data = np.outer(shape, base)
    return pd.DataFrame(data, index=np.arange(n_ts), columns=net.sgen.index.values)


def run_timeseries_check(
    substations: list[dict],
    lines: list[dict],
    proposed: dict | None,
    load_profile: dict | None,
    options: dict | None,
) -> dict[str, Any]:
    """Build the net, run timeseries, aggregate violations.

    Direct translation of `planner()` in smeOberrhein.py minus the plotting,
    Excel I/O, and zipcode-injection bits — kept the `ConstControl + DFData
    + run_timeseries + OutputWriter` skeleton intact.
    """
    options = options or {}
    voltage_limits = tuple(options.get("voltage_limits", DEFAULT_VOLT_LIMITS))
    loading_limits = tuple(options.get("loading_limits", DEFAULT_LOADING_LIMITS))
    n_ts = int(options.get("snapshot_hours", DEFAULT_N_TS))
    v_low, v_high = float(voltage_limits[0]), float(voltage_limits[1])
    _, l_high = float(loading_limits[0]), float(loading_limits[1])

    # Build the same network the snapshot bridge would build, so
    # voltage/loading results are directly comparable to /api/grid/power-flow.
    net, bus_map_or_error = build_network(substations, lines, proposed or {}, options)
    if net is None:
        return {"success": False, "error": bus_map_or_error}

    pd.set_option("future.no_silent_downcasting", True)

    # Load timeseries → ConstControl
    load_df = _build_load_dataframe(net, load_profile, n_ts)
    if len(net.load) > 0 and not load_df.empty:
        dsl = DFData(load_df)
        ConstControl(
            net,
            element="load",
            variable="p_mw",
            element_index=net.load.index.values,
            profile_name=net.load.index.values,
            data_source=dsl,
        )

    # Sgen timeseries (solar half-sine) → ConstControl
    sgen_df = _build_sgen_dataframe(net, n_ts)
    if len(net.sgen) > 0 and not sgen_df.empty:
        dsg = DFData(sgen_df)
        ConstControl(
            net,
            element="sgen",
            variable="p_mw",
            element_index=net.sgen.index.values,
            profile_name=net.sgen.index.values,
            data_source=dsg,
        )

    # In-memory OutputWriter (no file I/O — frontend renders charts).
    ow = OutputWriter(net, output_path=None, output_file_type=None)
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_line", "loading_percent")
    # Transformer loading too where the network has any.
    if len(net.trafo) > 0:
        ow.log_variable("res_trafo", "loading_percent")

    # Run the time-series simulation. Some pandapower releases reject the
    # `verbose` kwarg, so we pass only `time_steps` for maximum compatibility.
    run_timeseries(net, time_steps=range(n_ts))

    # Pull results out of the OutputWriter cache.
    vm_pu = ow.output.get("res_bus.vm_pu")
    loading = ow.output.get("res_line.loading_percent")
    if vm_pu is None or len(vm_pu) == 0:
        return {"success": False, "error": "Timeseries produced no voltage results"}

    voltages = vm_pu.to_numpy()      # (n_ts, n_bus)
    powerlines = loading.to_numpy() if loading is not None and len(loading) > 0 else np.zeros((n_ts, 0))

    # Direct port of smeOberrhein.py lines 173-177 (feasibility masks)
    feasible_volt_per_t = np.all(voltages >= v_low, axis=1) & np.all(voltages <= v_high, axis=1)
    if powerlines.size > 0:
        feasible_power_per_t = np.all(powerlines <= l_high, axis=1)
    else:
        feasible_power_per_t = np.ones(n_ts, dtype=bool)

    voltage_violations_hours = np.where(~feasible_volt_per_t)[0].tolist()
    thermal_violations_hours = np.where(~feasible_power_per_t)[0].tolist()
    feasible = (len(voltage_violations_hours) == 0) and (len(thermal_violations_hours) == 0)

    # Per-bus and per-line counts
    bus_names = [str(net.bus.at[idx, "name"]) for idx in vm_pu.columns]
    per_bus_count: dict[str, int] = {}
    bus_v_low_mask = voltages < v_low
    bus_v_high_mask = voltages > v_high
    bus_total = bus_v_low_mask.sum(axis=0) + bus_v_high_mask.sum(axis=0)
    for i, name in enumerate(bus_names):
        if bus_total[i] > 0:
            per_bus_count[name] = int(bus_total[i])

    per_line_count: dict[str, int] = {}
    if powerlines.size > 0:
        line_names = [str(net.line.at[idx, "name"]) for idx in loading.columns]
        line_mask = powerlines > l_high
        line_total = line_mask.sum(axis=0)
        for i, name in enumerate(line_names):
            if line_total[i] > 0:
                per_line_count[name] = int(line_total[i])

    # Chart series — per-hour worst values
    voltage_per_hour = voltages.min(axis=1).round(4).tolist()
    voltage_max_per_hour = voltages.max(axis=1).round(4).tolist()
    loading_per_hour = (
        powerlines.max(axis=1).round(2).tolist() if powerlines.size > 0 else [0.0] * n_ts
    )

    worst_voltage = float(voltages.min())
    worst_voltage_high = float(voltages.max())
    # Pick the more extreme deviation as "worst"
    worst_v_signed = (
        worst_voltage if abs(1.0 - worst_voltage) >= abs(1.0 - worst_voltage_high)
        else worst_voltage_high
    )
    worst_loading = float(powerlines.max()) if powerlines.size > 0 else 0.0

    if feasible:
        summary = (
            f"All {n_ts} timesteps within limits "
            f"({v_low:.3f}-{v_high:.3f} pu, <={l_high:.0f}% loading). "
            f"Worst voltage {worst_v_signed:.4f} pu, worst loading {worst_loading:.1f}%."
        )
    else:
        summary = (
            f"{len(voltage_violations_hours)} hour(s) breach voltage limits "
            f"({v_low:.3f}-{v_high:.3f} pu); "
            f"{len(thermal_violations_hours)} hour(s) breach thermal limit ({l_high:.0f}%). "
            f"Worst voltage {worst_v_signed:.4f} pu, worst loading {worst_loading:.1f}%."
        )

    return {
        "success": True,
        "feasible": bool(feasible),
        "snapshot_hours": n_ts,
        "voltage_limits": [v_low, v_high],
        "loading_limit_pct": l_high,
        "hours_with_voltage_violation": voltage_violations_hours,
        "hours_with_thermal_violation": thermal_violations_hours,
        "worst_voltage_pu": round(worst_v_signed, 4),
        "worst_voltage_low_pu": round(worst_voltage, 4),
        "worst_voltage_high_pu": round(worst_voltage_high, 4),
        "worst_loading_pct": round(worst_loading, 2),
        "voltage_per_hour": voltage_per_hour,          # min vm_pu series
        "voltage_max_per_hour": voltage_max_per_hour,  # max vm_pu series
        "loading_per_hour": loading_per_hour,
        "per_bus_violation_count": per_bus_count,
        "per_line_violation_count": per_line_count,
        "bus_count": int(voltages.shape[1]),
        "line_count": int(powerlines.shape[1]) if powerlines.size > 0 else 0,
        "summary": summary,
    }


def _json_serialise(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


def main() -> None:
    """Read JSON from stdin, run check, write JSON to stdout."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"success": False, "error": "Empty input"}))
            sys.exit(1)
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"success": False, "error": f"Invalid JSON: {exc}"}))
        sys.exit(1)

    substations = data.get("substations", [])
    lines = data.get("lines", [])
    proposed = data.get("proposed") or {}
    load_profile = data.get("load_profile")
    options = data.get("options") or {}

    if not substations:
        print(json.dumps({"success": False, "error": "No substations provided"}))
        sys.exit(1)

    try:
        result = run_timeseries_check(substations, lines, proposed, load_profile, options)
    except Exception as exc:
        result = {
            "success": False,
            "error": f"Timeseries simulation failed: {exc}",
            "traceback": traceback.format_exc()[-1500:],
        }

    print(json.dumps(result, default=_json_serialise))


if __name__ == "__main__":
    main()
