"""BESS revenue-stack co-optimiser — 2026-Q1 UK benchmarks, real-time
price-aware, Monte Carlo bands. Distinct from utils/revenue_stacker.py
(which is the older whole-portfolio model) — this one is BESS-specific
and powers the Design Canvas + lender pack.

Stacks modelled (priority by £/MW/h where mutually exclusive):
  - Dynamic Containment (DC)  — ~£15/MW/h, fast frequency
  - Dynamic Moderation (DM)   — ~£6/MW/h
  - Dynamic Regulation (DR)   — ~£4/MW/h
  - BM peak bids              — £/MWh on accepted BOAs
  - Wholesale arbitrage       — one charge+discharge cycle/day, spread × rte
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("princeps.bess_stacker")


BENCHMARK = {
    "dc_price_gbp_mw_h":  15.0,
    "dm_price_gbp_mw_h":   6.0,
    "dr_price_gbp_mw_h":   4.0,
    "bm_price_gbp_mwh":   92.0,
    "wholesale_peak":     78.0,
    "wholesale_offpeak":  42.0,
    "dc_hours_per_yr":  4200,
    "dm_hours_per_yr":  2800,
    "dr_hours_per_yr":  1800,
    "bm_peak_hours_per_yr": 180,
    "wholesale_cycles":   280,
    "rte": 0.87,
    "degradation_pct_yr": 2.0,
}


@dataclass
class StackResult:
    annual_revenue_gbp: float
    revenue_by_stack: dict[str, float]
    mwh_by_stack: dict[str, float]
    hours_by_stack: dict[str, float]
    utilisation_pct: float
    notes: list[str]


def _availability(duration_h: float, benchmark: dict) -> dict:
    factor = min(1.0, 2.0 / max(0.5, duration_h))
    return {
        "dc_hours": benchmark["dc_hours_per_yr"] * factor,
        "dm_hours": benchmark["dm_hours_per_yr"] * factor,
        "dr_hours": benchmark["dr_hours_per_yr"] * (0.5 + 0.5 * factor),
        "bm_hours": benchmark["bm_peak_hours_per_yr"],
        "wholesale_cycles": benchmark["wholesale_cycles"] * (0.6 + 0.4 * min(1, duration_h / 2)),
    }


def co_optimise_bess(
    capacity_mw: float,
    duration_h: float = 2.0,
    live_prices: dict | None = None,
    chemistry: str = "lfp",
) -> StackResult:
    b = dict(BENCHMARK)
    if live_prices:
        b.update({k: v for k, v in live_prices.items() if v is not None})

    h = _availability(duration_h, b)
    rte = b["rte"]
    total_hours = 8760

    # Allocate AS services by £/MW/h priority (mutually exclusive).
    priority = [
        ("dc", b["dc_price_gbp_mw_h"], h["dc_hours"]),
        ("dm", b["dm_price_gbp_mw_h"], h["dm_hours"]),
        ("dr", b["dr_price_gbp_mw_h"], h["dr_hours"]),
    ]
    priority.sort(key=lambda x: x[1], reverse=True)

    revenue = {k: 0.0 for k in ("dc", "dm", "dr", "bm", "wholesale")}
    mwh = {k: 0.0 for k in revenue}
    hours_used = {k: 0.0 for k in revenue}
    hours_left = total_hours

    for code, price, yearly in priority:
        u = min(yearly, hours_left)
        revenue[code] = u * capacity_mw * price
        hours_used[code] = u
        hours_left -= u

    bm_h = min(h["bm_hours"], hours_left)
    bm_mwh = bm_h * capacity_mw * 0.8
    revenue["bm"] = bm_mwh * b["bm_price_gbp_mwh"]
    mwh["bm"] = bm_mwh
    hours_used["bm"] = bm_h
    hours_left -= bm_h

    spread = b["wholesale_peak"] - b["wholesale_offpeak"]
    mwh_per_cycle = capacity_mw * duration_h
    cycles = min(h["wholesale_cycles"], hours_left / 5.0)
    revenue["wholesale"] = cycles * mwh_per_cycle * spread * rte
    mwh["wholesale"] = cycles * mwh_per_cycle
    hours_used["wholesale"] = cycles * 5.0
    hours_left -= hours_used["wholesale"]

    total = sum(revenue.values())
    util = ((total_hours - hours_left) / total_hours) * 100

    notes = [
        f"Priority stack: {' > '.join(c for c, _, _ in priority)} by £/MW/h",
        f"Duration {duration_h} h → AS factor {min(1.0, 2.0/max(0.5, duration_h)):.2f}",
        f"Round-trip efficiency {rte:.2f} ({chemistry.upper()})",
    ]
    return StackResult(
        annual_revenue_gbp=total,
        revenue_by_stack={k: round(v, 0) for k, v in revenue.items()},
        mwh_by_stack={k: round(v, 1) for k, v in mwh.items()},
        hours_by_stack={k: round(v, 0) for k, v in hours_used.items()},
        utilisation_pct=round(util, 1),
        notes=notes,
    )


def probabilistic_co_optimise(
    capacity_mw: float, duration_h: float = 2.0,
    live_prices: dict | None = None, n_samples: int = 800,
) -> dict[str, Any]:
    rng = random.Random(42)
    results: list[float] = []
    per_stack = {k: [] for k in ("dc", "dm", "dr", "bm", "wholesale")}
    base_lp = dict(live_prices or {})
    base_dc = base_lp.get("dc_price_gbp_mw_h", BENCHMARK["dc_price_gbp_mw_h"])
    base_dm = base_lp.get("dm_price_gbp_mw_h", BENCHMARK["dm_price_gbp_mw_h"])
    base_dr = base_lp.get("dr_price_gbp_mw_h", BENCHMARK["dr_price_gbp_mw_h"])
    base_peak = base_lp.get("wholesale_peak", BENCHMARK["wholesale_peak"])
    base_off = base_lp.get("wholesale_offpeak", BENCHMARK["wholesale_offpeak"])
    base_spread = base_peak - base_off

    for _ in range(n_samples):
        scarcity = rng.gauss(0, 1)
        pert = dict(base_lp)
        pert["dc_price_gbp_mw_h"] = max(0, base_dc * (1 + 0.18 * scarcity + 0.05 * rng.gauss(0, 1)))
        pert["dm_price_gbp_mw_h"] = max(0, base_dm * (1 + 0.12 * scarcity + 0.07 * rng.gauss(0, 1)))
        pert["dr_price_gbp_mw_h"] = max(0, base_dr * (1 + 0.10 * scarcity + 0.10 * rng.gauss(0, 1)))
        spread_mult = max(0.3, 1 + 0.25 * rng.gauss(0, 1) - 0.15 * scarcity)
        pert["wholesale_peak"] = base_peak * (1 + 0.15 * rng.gauss(0, 1))
        pert["wholesale_offpeak"] = pert["wholesale_peak"] - base_spread * spread_mult
        r = co_optimise_bess(capacity_mw, duration_h, pert)
        results.append(r.annual_revenue_gbp)
        for k in per_stack:
            per_stack[k].append(r.revenue_by_stack[k])

    def pct(arr, p):
        s = sorted(arr)
        i = max(0, min(len(s) - 1, int(len(s) * p)))
        return s[i]

    return {
        "samples": n_samples,
        "annual_revenue": {
            "p10": round(pct(results, 0.10), 0),
            "p50": round(pct(results, 0.50), 0),
            "p90": round(pct(results, 0.90), 0),
            "mean": round(sum(results) / len(results), 0),
        },
        "per_stack_p50": {k: round(pct(v, 0.50), 0) for k, v in per_stack.items()},
        "per_stack_p90": {k: round(pct(v, 0.90), 0) for k, v in per_stack.items()},
    }
