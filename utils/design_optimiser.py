"""Design optimiser — scipy-based search over a handful of design variables
to maximise IRR / minimise LCOE / maximise yield for a given site + workload.

The pipeline is treated as a black-box function: given a vector of params
(capacity, duration, DC ratio, tilt, etc.) we call the same physics +
financial model that /api/design/generate uses and return the scalar
objective. scipy.optimize.minimize with Powell method copes well with
this noisy low-dimension landscape (≤5 vars).

Keeping this import-optional — if scipy is missing at import time the
router catches ImportError and returns a 501 so the rest of the design
stack still works.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("princeps.design.optimiser")


OBJECTIVES = {
    "irr":   ("kpis.irr_pct",            "max"),
    "lcoe":  ("kpis.lcoe_gbp_per_mwh",   "min"),
    "yield": ("kpis.annual_mwh",         "max"),
    "capex": ("kpis.capex_gbp_m",        "min"),
    "npv":   ("kpis.npv_gbp_m",          "max"),
}


def _dig(obj: dict, path: str, default: float | None = None):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur if isinstance(cur, (int, float)) else default


def optimise(
    workload: str,
    objective: str,
    initial_params: dict,
    bounds: dict[str, tuple[float, float]],
    evaluator: Callable[[dict], dict],
    max_iter: int = 40,
) -> dict[str, Any]:
    """Run black-box optimisation. ``evaluator`` is a synchronous function
    that takes a params dict and returns a full pipeline result (same shape
    as /api/design/generate). scipy's Powell method is gradient-free so
    it handles the evaluator's discrete clamping steps."""
    try:
        from scipy.optimize import minimize  # type: ignore
    except ImportError:
        return {
            "ok": False,
            "reason": "scipy not installed; install scipy>=1.10 in the backend venv.",
            "params": initial_params,
        }

    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}. Must be one of {list(OBJECTIVES)}")

    key_path, direction = OBJECTIVES[objective]
    keys = list(bounds.keys())

    def pack(p_dict: dict) -> list[float]:
        return [p_dict.get(k, (bounds[k][0] + bounds[k][1]) / 2) for k in keys]

    def unpack(x: list[float]) -> dict:
        out = dict(initial_params)
        for k, v in zip(keys, x):
            lo, hi = bounds[k]
            out[k] = float(min(hi, max(lo, v)))
        return out

    trace: list[dict] = []

    def objective_fn(x: list[float]) -> float:
        params = unpack(x)
        try:
            result = evaluator(params)
            value = _dig(result, key_path, default=0.0) or 0.0
            trace.append({"params": params, "objective": value})
            return -value if direction == "max" else value
        except Exception as e:
            log.warning("evaluator raised: %s", e)
            return 1e9

    x0 = pack(initial_params)
    try:
        res = minimize(
            objective_fn,
            x0=x0,
            method="Powell",
            options={"maxiter": max_iter, "xtol": 1e-3, "disp": False},
        )
        best_params = unpack(list(res.x))
        best_result = evaluator(best_params)
        best_value = _dig(best_result, key_path, default=0.0)
        baseline_value = _dig(evaluator(initial_params), key_path, default=0.0)
        delta = best_value - baseline_value if best_value is not None and baseline_value is not None else None
        return {
            "ok": True,
            "objective": objective,
            "direction": direction,
            "iterations": len(trace),
            "initial_value": baseline_value,
            "best_value": best_value,
            "delta": delta,
            "best_params": best_params,
            "best_result": best_result,
            "trace": trace[-10:],
        }
    except Exception as e:
        log.exception("optimiser failed")
        return {"ok": False, "reason": str(e), "params": initial_params}
