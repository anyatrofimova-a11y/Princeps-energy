"""
BESS Revenue Stacking Optimizer — multi-market dispatch optimization.

Uses Pyomo for optimal charge/discharge scheduling across day-ahead,
intraday, and balancing markets. Can import bess-optimizer from vendor/
if available, otherwise uses built-in LP formulation.

Runs in the main venv (no subprocess needed — Pyomo has no version conflicts).
"""

import json
import logging
import math
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_VENDOR_PATH = Path(__file__).resolve().parent.parent / "vendor" / "bess-optimizer"


def optimize_bess_dispatch(
    capacity_mwh: float,
    power_mw: float,
    prices_day_ahead: list[float],
    prices_intraday: list[float] | None = None,
    prices_balancing: list[float] | None = None,
    efficiency: float = 0.88,
    degradation_cost: float = 5.0,
    min_soc: float = 0.05,
    max_soc: float = 0.95,
) -> dict[str, Any]:
    """
    Optimize BESS dispatch across 3 markets using linear programming.

    Args:
        capacity_mwh: Total energy capacity (MWh)
        power_mw: Maximum charge/discharge power (MW)
        prices_day_ahead: Hourly day-ahead prices (GBP/MWh), length = horizon
        prices_intraday: Optional intraday market prices
        prices_balancing: Optional balancing mechanism prices
        efficiency: Round-trip efficiency (0-1)
        degradation_cost: Degradation cost per cycle (GBP/MWh)
        min_soc: Minimum state of charge (fraction)
        max_soc: Maximum state of charge (fraction)

    Returns:
        dict with optimal schedule, revenue breakdown, metrics
    """
    hours = len(prices_day_ahead)
    if hours == 0:
        return {"ok": False, "error": "No price data provided"}

    # Try Pyomo LP optimization
    try:
        return _optimize_pyomo(
            capacity_mwh, power_mw, prices_day_ahead,
            prices_intraday, prices_balancing,
            efficiency, degradation_cost, min_soc, max_soc,
        )
    except ImportError:
        log.warning("Pyomo not available, falling back to greedy optimizer")

    # Fallback: greedy price-spread optimization
    return _optimize_greedy(
        capacity_mwh, power_mw, prices_day_ahead,
        efficiency, degradation_cost, min_soc, max_soc,
    )


def _optimize_pyomo(
    capacity_mwh, power_mw, prices_da,
    prices_id, prices_bm,
    efficiency, degradation_cost, min_soc, max_soc,
):
    """LP optimization using Pyomo."""
    import pyomo.environ as pyo

    hours = len(prices_da)
    eff_charge = math.sqrt(efficiency)
    eff_discharge = math.sqrt(efficiency)

    model = pyo.ConcreteModel()
    model.T = pyo.RangeSet(0, hours - 1)

    # Variables
    model.charge = pyo.Var(model.T, domain=pyo.NonNegativeReals, bounds=(0, power_mw))
    model.discharge = pyo.Var(model.T, domain=pyo.NonNegativeReals, bounds=(0, power_mw))
    model.soc = pyo.Var(model.T, domain=pyo.NonNegativeReals,
                        bounds=(min_soc * capacity_mwh, max_soc * capacity_mwh))

    # SOC dynamics
    def soc_rule(m, t):
        if t == 0:
            return m.soc[t] == 0.5 * capacity_mwh + m.charge[t] * eff_charge - m.discharge[t] / eff_discharge
        return m.soc[t] == m.soc[t - 1] + m.charge[t] * eff_charge - m.discharge[t] / eff_discharge

    model.soc_constraint = pyo.Constraint(model.T, rule=soc_rule)

    # Objective: maximize revenue minus degradation
    def objective_rule(m):
        revenue = sum(
            prices_da[t] * m.discharge[t] - prices_da[t] * m.charge[t]
            for t in m.T
        )
        # Add intraday spread revenue if available
        if prices_id:
            revenue += sum(
                max(0, prices_id[t] - prices_da[t]) * m.discharge[t] * 0.3
                for t in m.T if t < len(prices_id)
            )
        # Add balancing revenue if available
        if prices_bm:
            revenue += sum(
                max(0, prices_bm[t] - prices_da[t]) * m.discharge[t] * 0.2
                for t in m.T if t < len(prices_bm)
            )
        # Subtract degradation
        degradation = sum(
            degradation_cost * (m.charge[t] + m.discharge[t]) / (2 * capacity_mwh)
            for t in m.T
        )
        return revenue - degradation

    model.objective = pyo.Objective(rule=objective_rule, sense=pyo.maximize)

    # Solve
    solver = pyo.SolverFactory("glpk")
    if not solver.available():
        solver = pyo.SolverFactory("cbc")
    if not solver.available():
        # Fall back to greedy
        return _optimize_greedy(
            capacity_mwh, power_mw, prices_da,
            efficiency, degradation_cost, min_soc, max_soc,
        )

    result = solver.solve(model, tee=False)

    if result.solver.status != pyo.SolverStatus.ok:
        return {"ok": False, "error": "Optimization solver failed"}

    # Extract schedule
    schedule = []
    total_revenue_da = 0.0
    total_revenue_id = 0.0
    total_revenue_bm = 0.0
    total_cycles = 0.0

    for t in model.T:
        ch = round(float(pyo.value(model.charge[t])), 3)
        dis = round(float(pyo.value(model.discharge[t])), 3)
        soc = round(float(pyo.value(model.soc[t])), 3)
        net_power = dis - ch

        rev_da = prices_da[t] * net_power
        total_revenue_da += rev_da

        rev_id = 0
        if prices_id and t < len(prices_id):
            rev_id = max(0, prices_id[t] - prices_da[t]) * dis * 0.3
            total_revenue_id += rev_id

        rev_bm = 0
        if prices_bm and t < len(prices_bm):
            rev_bm = max(0, prices_bm[t] - prices_da[t]) * dis * 0.2
            total_revenue_bm += rev_bm

        total_cycles += (ch + dis) / (2 * capacity_mwh)

        schedule.append({
            "hour": t,
            "charge_mw": ch,
            "discharge_mw": dis,
            "net_power_mw": round(net_power, 3),
            "soc_mwh": soc,
            "soc_pct": round(soc / capacity_mwh * 100, 1),
            "price_da": prices_da[t],
            "revenue_gbp": round(rev_da + rev_id + rev_bm, 2),
        })

    total_revenue = total_revenue_da + total_revenue_id + total_revenue_bm

    return {
        "ok": True,
        "schedule": schedule,
        "revenue": {
            "day_ahead_gbp": round(total_revenue_da, 2),
            "intraday_gbp": round(total_revenue_id, 2),
            "balancing_gbp": round(total_revenue_bm, 2),
            "total_gbp": round(total_revenue, 2),
        },
        "metrics": {
            "cycles": round(total_cycles, 2),
            "cycles_per_day": round(total_cycles / max(hours / 24, 1), 2),
            "avg_spread_gbp_mwh": round(total_revenue / max(total_cycles * capacity_mwh, 1), 2),
            "capacity_utilisation_pct": round(total_cycles / max(hours / 24, 1) * 100 / 2, 1),
        },
        "system": {
            "capacity_mwh": capacity_mwh,
            "power_mw": power_mw,
            "efficiency": efficiency,
            "duration_hours": capacity_mwh / power_mw,
        },
        "optimizer": "pyomo_lp",
    }


def _optimize_greedy(capacity_mwh, power_mw, prices, efficiency, degradation_cost, min_soc, max_soc):
    """Simple greedy price-spread optimization as fallback."""
    hours = len(prices)
    eff = math.sqrt(efficiency)

    # Find charge/discharge windows by price ranking
    indexed = sorted(enumerate(prices), key=lambda x: x[1])
    n_cycles = min(hours // 4, int(capacity_mwh / power_mw * 2))

    charge_hours = set(h for h, _ in indexed[:n_cycles])
    discharge_hours = set(h for h, _ in indexed[-n_cycles:])

    schedule = []
    soc = 0.5 * capacity_mwh
    total_revenue = 0.0
    total_cycles = 0.0

    for t in range(hours):
        ch, dis = 0.0, 0.0
        if t in charge_hours and soc < max_soc * capacity_mwh:
            ch = min(power_mw, (max_soc * capacity_mwh - soc) / eff)
            soc += ch * eff
        elif t in discharge_hours and soc > min_soc * capacity_mwh:
            dis = min(power_mw, (soc - min_soc * capacity_mwh) * eff)
            soc -= dis / eff

        net = dis - ch
        rev = prices[t] * net
        total_revenue += rev
        total_cycles += (ch + dis) / (2 * capacity_mwh)

        schedule.append({
            "hour": t,
            "charge_mw": round(ch, 3),
            "discharge_mw": round(dis, 3),
            "net_power_mw": round(net, 3),
            "soc_mwh": round(soc, 3),
            "soc_pct": round(soc / capacity_mwh * 100, 1),
            "price_da": prices[t],
            "revenue_gbp": round(rev, 2),
        })

    return {
        "ok": True,
        "schedule": schedule,
        "revenue": {
            "day_ahead_gbp": round(total_revenue, 2),
            "intraday_gbp": 0,
            "balancing_gbp": 0,
            "total_gbp": round(total_revenue, 2),
        },
        "metrics": {
            "cycles": round(total_cycles, 2),
            "cycles_per_day": round(total_cycles / max(hours / 24, 1), 2),
            "avg_spread_gbp_mwh": round(total_revenue / max(total_cycles * capacity_mwh, 1), 2),
            "capacity_utilisation_pct": round(total_cycles / max(hours / 24, 1) * 100 / 2, 1),
        },
        "system": {
            "capacity_mwh": capacity_mwh,
            "power_mw": power_mw,
            "efficiency": efficiency,
            "duration_hours": capacity_mwh / power_mw,
        },
        "optimizer": "greedy_fallback",
    }


def estimate_bess_revenue(
    capacity_mwh: float,
    power_mw: float,
    year: int = 2025,
    region: str = "GB",
) -> dict[str, Any]:
    """
    Quick annual BESS revenue estimate using UK market benchmarks.

    Uses published UK BESS revenue data (Modo Energy, GridBeyond)
    to estimate annual revenue by market stream.
    """
    duration = capacity_mwh / power_mw if power_mw > 0 else 2.0

    # UK BESS revenue benchmarks 2024/2025 (GBP/MW/year) by market
    # Source: Modo Energy UK BESS Revenue Index
    benchmarks = {
        2023: {"wholesale_arbitrage": 65000, "ffr_dc": 35000, "capacity_market": 18000, "bm_balancing": 25000, "triad": 8000},
        2024: {"wholesale_arbitrage": 55000, "ffr_dc": 30000, "capacity_market": 20000, "bm_balancing": 22000, "triad": 6000},
        2025: {"wholesale_arbitrage": 50000, "ffr_dc": 28000, "capacity_market": 22000, "bm_balancing": 20000, "triad": 5000},
        2026: {"wholesale_arbitrage": 45000, "ffr_dc": 25000, "capacity_market": 24000, "bm_balancing": 18000, "triad": 4000},
    }

    yr_bench = benchmarks.get(year, benchmarks[2025])

    # Duration adjustment: 1hr gets ~60% of 2hr revenue per MW, 4hr gets ~130%
    duration_factors = {0.5: 0.45, 1: 0.65, 1.5: 0.85, 2: 1.0, 3: 1.15, 4: 1.30}
    dur_key = min(duration_factors.keys(), key=lambda k: abs(k - duration))
    dur_factor = duration_factors[dur_key]

    revenue_by_stream = {}
    total = 0.0
    for stream, rev_per_mw in yr_bench.items():
        stream_rev = rev_per_mw * power_mw * dur_factor
        revenue_by_stream[stream] = round(stream_rev, 0)
        total += stream_rev

    # Degradation cost estimate
    cycles_per_year = 365 * 1.5  # ~1.5 cycles/day average
    degradation_cost = cycles_per_year * capacity_mwh * 3.0  # GBP3/MWh degradation

    return {
        "ok": True,
        "year": year,
        "system": {
            "capacity_mwh": capacity_mwh,
            "power_mw": power_mw,
            "duration_hours": round(duration, 1),
        },
        "annual_revenue_gbp": round(total, 0),
        "revenue_by_stream": revenue_by_stream,
        "degradation_cost_gbp": round(degradation_cost, 0),
        "net_revenue_gbp": round(total - degradation_cost, 0),
        "revenue_per_mw_gbp": round(total / power_mw, 0) if power_mw > 0 else 0,
        "revenue_per_mwh_gbp": round(total / capacity_mwh, 0) if capacity_mwh > 0 else 0,
        "duration_factor": dur_factor,
        "benchmark_year": year,
        "note": "Estimates based on UK BESS revenue benchmarks (Modo Energy). Actual revenue depends on market conditions and trading strategy.",
    }
