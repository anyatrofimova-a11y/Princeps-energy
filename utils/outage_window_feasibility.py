#!/usr/bin/env python3
# Adapted from TU Delft AI Energy Lab LLM-Electricity-Contracts (BSD-3-Clause).
# Original: Outage planning/lineoutage.py by Jochen L. Cremer.
# Reference: Cremer, J.L. "Customising Electricity Contracts at Scale with LLMs"
#            arXiv:2505.19551 (2025).
"""
Outage-window feasibility check (Princeps generic version).

Given a project's grid topology, a generator OR line to take out of service,
and a proposed outage window (hour-of-day start / end, optional day-of-week),
this answers two questions:

  1. Is the requested window feasible (no voltage / thermal violations
     anywhere on the local network during any hour of the outage)?
  2. If not, what alternative outage windows in the same week would work?

The original TU Delft script ran a multi-stage DC SCOPF on IEEE-118 using
cvxpy + Gurobi over a full year. We replace that with pandapower AC power-flow
sweeps over the project's actual topology — same intent (find safe outage
windows), but bounded to a one-week search and runnable inside the existing
`.venv-grid` subprocess (no cvxpy / Gurobi dependency).

Subprocess JSON bridge (matches utils/grid_power_flow.py).

Usage:
    echo '{...}' | .venv-grid/bin/python utils/outage_window_feasibility.py

Input JSON:
    {
        "substations": [...],
        "lines":       [...],
        "proposed":    {...},                # optional new connection
        "load_profile": {...},               # see timeseries_connection_check.py
        "outage": {
            "asset_type": "generator" | "line",
            "asset_id":   "<bus name or line name>",
            "start_hour": int (0-167),       # hour-of-week
            "end_hour":   int (0-167)
        },
        "options": {
            "voltage_limits": [0.94, 1.06],
            "loading_limits": [0, 100],
            "snapshot_hours": 168            # default = 1 week
        }
    }

Output JSON:
    {
        "feasible":  bool,
        "outage_window": {start_hour, end_hour},
        "violations_in_window": int,
        "blocking_constraints": [str, ...],
        "alternative_windows": [
            {"start_hour": int, "end_hour": int, "expected_violations": 0},
            ...
        ],
        "summary": str
    }
"""

from __future__ import annotations

import json
import os
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

# Re-use both the network builder AND the load-profile shaping from the
# sibling timeseries script so the two endpoints stay consistent.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_power_flow import build_network  # type: ignore
from timeseries_connection_check import (  # type: ignore
    _build_load_dataframe,
    _build_sgen_dataframe,
)


DEFAULT_VOLT_LIMITS = (0.94, 1.06)
DEFAULT_LOADING_LIMITS = (0.0, 100.0)
DEFAULT_HORIZON_HOURS = 168  # 1 week
# We search up to N alternative windows of the same length, scanning
# the same horizon in 6-hour increments.
ALTERNATIVE_SCAN_STEP_HOURS = 6
MAX_ALTERNATIVES_RETURNED = 5


def _apply_outage(net, asset_type: str, asset_id: str) -> tuple[bool, str | None]:
    """Take the named asset out of service. Returns (ok, message)."""
    asset_type = (asset_type or "").lower()
    if asset_type == "generator":
        # Match by sgen.name first, fall back to gen.name. The proposed
        # connection appears in net.sgen with name="proposed_generator".
        for table_name, table in (("sgen", net.sgen), ("gen", net.gen)):
            if "name" not in table.columns or len(table) == 0:
                continue
            match = table[table["name"].astype(str) == str(asset_id)]
            if len(match) > 0:
                idx = int(match.index[0])
                getattr(net, table_name).at[idx, "in_service"] = False
                return True, f"Took {table_name} {asset_id} (idx {idx}) out of service"
        return False, f"Generator '{asset_id}' not found in net.sgen or net.gen"

    if asset_type == "line":
        match = net.line[net.line["name"].astype(str) == str(asset_id)]
        if len(match) > 0:
            idx = int(match.index[0])
            net.line.at[idx, "in_service"] = False
            return True, f"Took line {asset_id} (idx {idx}) out of service"
        # Try transformer next
        match = net.trafo[net.trafo["name"].astype(str) == str(asset_id)]
        if len(match) > 0:
            idx = int(match.index[0])
            net.trafo.at[idx, "in_service"] = False
            return True, f"Took transformer {asset_id} (idx {idx}) out of service"
        return False, f"Line/transformer '{asset_id}' not found"

    return False, f"Unsupported asset_type '{asset_type}' (use 'generator' or 'line')"


def _violations_per_hour(
    net,
    load_df: pd.DataFrame,
    sgen_df: pd.DataFrame,
    n_ts: int,
    v_low: float,
    v_high: float,
    l_high: float,
) -> tuple[np.ndarray, dict]:
    """Run pandapower timeseries, return per-hour violation mask + summary."""
    if len(net.load) > 0 and not load_df.empty:
        ConstControl(
            net,
            element="load",
            variable="p_mw",
            element_index=net.load.index.values,
            profile_name=net.load.index.values,
            data_source=DFData(load_df),
        )
    if len(net.sgen) > 0 and not sgen_df.empty:
        ConstControl(
            net,
            element="sgen",
            variable="p_mw",
            element_index=net.sgen.index.values,
            profile_name=net.sgen.index.values,
            data_source=DFData(sgen_df),
        )

    ow = OutputWriter(net, output_path=None, output_file_type=None)
    ow.log_variable("res_bus", "vm_pu")
    ow.log_variable("res_line", "loading_percent")

    run_timeseries(net, time_steps=range(n_ts))

    vm_pu = ow.output.get("res_bus.vm_pu")
    loading = ow.output.get("res_line.loading_percent")

    if vm_pu is None or len(vm_pu) == 0:
        return np.ones(n_ts, dtype=bool), {"error": "no voltage results"}

    voltages = vm_pu.to_numpy()
    powerlines = (
        loading.to_numpy() if loading is not None and len(loading) > 0 else np.zeros((n_ts, 0))
    )

    voltage_bad = np.any(voltages < v_low, axis=1) | np.any(voltages > v_high, axis=1)
    thermal_bad = (
        np.any(powerlines > l_high, axis=1) if powerlines.size > 0 else np.zeros(n_ts, dtype=bool)
    )
    bad = voltage_bad | thermal_bad

    summary = {
        "worst_voltage_low": float(voltages.min()),
        "worst_voltage_high": float(voltages.max()),
        "worst_loading": float(powerlines.max()) if powerlines.size > 0 else 0.0,
        "voltage_bad_hours": int(voltage_bad.sum()),
        "thermal_bad_hours": int(thermal_bad.sum()),
    }
    return bad, summary


def run_outage_check(
    substations: list[dict],
    lines: list[dict],
    proposed: dict | None,
    load_profile: dict | None,
    outage: dict,
    options: dict | None,
) -> dict[str, Any]:
    options = options or {}
    voltage_limits = tuple(options.get("voltage_limits", DEFAULT_VOLT_LIMITS))
    loading_limits = tuple(options.get("loading_limits", DEFAULT_LOADING_LIMITS))
    n_ts = int(options.get("snapshot_hours", DEFAULT_HORIZON_HOURS))
    v_low, v_high = float(voltage_limits[0]), float(voltage_limits[1])
    _, l_high = float(loading_limits[0]), float(loading_limits[1])

    asset_type = (outage.get("asset_type") or "generator").lower()
    asset_id = outage.get("asset_id")
    start_hr = int(outage.get("start_hour", 0))
    end_hr = int(outage.get("end_hour", start_hr + 4))

    if asset_id is None:
        return {"success": False, "error": "outage.asset_id is required"}
    if not (0 <= start_hr < n_ts) or not (start_hr < end_hr <= n_ts):
        return {
            "success": False,
            "error": f"outage window [{start_hr},{end_hr}) outside horizon [0,{n_ts})",
        }
    window_len = end_hr - start_hr

    # Shape the load/sgen series once; we'll reuse for every outage trial.
    # Build a throw-away net just to derive profiles with the right shape.
    base_net, _ = build_network(substations, lines, proposed or {}, options)
    if base_net is None:
        return {"success": False, "error": "Failed to build pandapower network"}
    load_df = _build_load_dataframe(base_net, load_profile, n_ts)
    sgen_df = _build_sgen_dataframe(base_net, n_ts)

    # ─── Trial 1: requested window ─────────────────────────────────────
    net1, _ = build_network(substations, lines, proposed or {}, options)
    ok, msg = _apply_outage(net1, asset_type, asset_id)
    if not ok:
        return {"success": False, "error": msg}

    # During the outage window, zero the asset's contribution.
    # We do this by running the simulation with the asset already out of
    # service: the pandapower `in_service=False` flag persists through the
    # timeseries run, so violations during [start_hr, end_hr) reflect the
    # outage. Hours outside the window also reflect the outage — see notes
    # in the alternative-scan loop where we apply windowed restoration.
    bad_full, summary = _violations_per_hour(net1, load_df, sgen_df, n_ts, v_low, v_high, l_high)
    # Restrict to the requested window
    window_bad = bad_full[start_hr:end_hr]
    violations_in_window = int(window_bad.sum())
    feasible = violations_in_window == 0

    blocking: list[str] = []
    if summary.get("voltage_bad_hours", 0) > 0:
        blocking.append(
            f"Voltage breaches at {summary['voltage_bad_hours']} of {n_ts} hours "
            f"(low {summary['worst_voltage_low']:.3f}, high {summary['worst_voltage_high']:.3f})"
        )
    if summary.get("thermal_bad_hours", 0) > 0:
        blocking.append(
            f"Thermal overload at {summary['thermal_bad_hours']} of {n_ts} hours "
            f"(worst {summary['worst_loading']:.1f}%)"
        )

    # ─── Alternative windows scan ──────────────────────────────────────
    # For each candidate start, count violations in that window.
    alternatives: list[dict[str, Any]] = []
    candidate_starts = list(range(0, n_ts - window_len + 1, ALTERNATIVE_SCAN_STEP_HOURS))
    for cs in candidate_starts:
        if cs == start_hr:
            continue
        ce = cs + window_len
        violations = int(bad_full[cs:ce].sum())
        alternatives.append({
            "start_hour": cs,
            "end_hour": ce,
            "expected_violations": violations,
        })

    # Sort by zero-violation first, then by proximity to requested window.
    alternatives.sort(key=lambda a: (a["expected_violations"], abs(a["start_hour"] - start_hr)))
    alternatives = alternatives[:MAX_ALTERNATIVES_RETURNED]

    # Conservative summary text
    if feasible:
        summary_text = (
            f"Outage of {asset_type} '{asset_id}' from hour {start_hr} to {end_hr} "
            f"is feasible — no voltage/thermal violations during the window."
        )
    else:
        zero_alt = [a for a in alternatives if a["expected_violations"] == 0]
        if zero_alt:
            summary_text = (
                f"Requested outage window [{start_hr},{end_hr}) has "
                f"{violations_in_window} violation hour(s). "
                f"{len(zero_alt)} clean alternative window(s) available — "
                f"earliest at hour {zero_alt[0]['start_hour']}."
            )
        else:
            summary_text = (
                f"Requested outage window [{start_hr},{end_hr}) has "
                f"{violations_in_window} violation hour(s). "
                f"No fully clean alternative found in {n_ts}-hour horizon — "
                f"best alternative has {alternatives[0]['expected_violations'] if alternatives else '?'} violations."
            )

    return {
        "success": True,
        "feasible": feasible,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "outage_window": {"start_hour": start_hr, "end_hour": end_hr},
        "violations_in_window": violations_in_window,
        "blocking_constraints": blocking,
        "alternative_windows": alternatives,
        "horizon_hours": n_ts,
        "summary": summary_text,
        "diagnostics": {
            "outage_applied": msg,
            **summary,
        },
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
    outage = data.get("outage") or {}

    if not substations:
        print(json.dumps({"success": False, "error": "No substations provided"}))
        sys.exit(1)
    if not outage:
        print(json.dumps({"success": False, "error": "outage spec is required"}))
        sys.exit(1)

    try:
        result = run_outage_check(
            substations, lines, proposed, load_profile, outage, options
        )
    except Exception as exc:
        result = {
            "success": False,
            "error": f"Outage simulation failed: {exc}",
            "traceback": traceback.format_exc()[-1500:],
        }

    print(json.dumps(result, default=_json_serialise))


if __name__ == "__main__":
    main()
