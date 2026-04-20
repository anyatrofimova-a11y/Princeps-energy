"""Capacity-mix optimiser — scipy SLSQP over (solar_mw, bess_mw, bess_hours,
ppa_share) maximising NPV or minimising LCOE for a hybrid site, subject to
land area and grid headroom constraints.

Distinct from utils/design_optimiser.py (UK spelling), which does generic
black-box optimisation via Powell over a single workload's design
parameters. This module specifically handles the capacity-mix problem:
how much solar, how much BESS (MW + hours), and what fraction of output
to sell on a fixed PPA vs merchant.

Analytic fallback kicks in if scipy isn't importable so /optimize-design
never crashes the chat loop.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.design.capacity_mix")

# UK 2026 benchmarks
SOLAR_CAPEX_GBP_PER_MW = 700_000
BESS_CAPEX_GBP_PER_MWH = 330_000
SOLAR_OPEX_PCT_CAPEX = 0.015
BESS_OPEX_PCT_CAPEX = 0.020
SOLAR_CF_PCT = 11.0           # UK central-England capacity factor
MERCHANT_PRICE_GBP_MWH = 72   # expected wholesale average
BESS_ARBITRAGE_GBP_MW_YR = 75_000
DISCOUNT_RATE = 0.085
LIFE_YEARS = 25
LAND_HA_PER_SOLAR_MW = 1.8    # ground-mount UK typical
LAND_HA_PER_BESS_MW = 0.15    # pad + fire breaks


def _clamp(lo: float, v: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _kpis(solar_mw: float, bess_mw: float, bess_hours: float,
          ppa_share: float, ppa_price: float,
          site_area_ha: float, grid_headroom_mw: float) -> dict[str, Any]:
    """Evaluate the lifetime KPIs for a capacity-mix vector."""
    solar_mw = max(0.0, solar_mw)
    bess_mw = max(0.0, bess_mw)
    bess_hours = max(0.5, bess_hours)
    ppa_share = _clamp(0.0, ppa_share, 1.0)

    bess_energy_mwh = bess_mw * bess_hours
    solar_capex = solar_mw * SOLAR_CAPEX_GBP_PER_MW
    bess_capex = bess_energy_mwh * BESS_CAPEX_GBP_PER_MWH
    total_capex = solar_capex + bess_capex

    solar_generation_mwh = solar_mw * 8760 * (SOLAR_CF_PCT / 100.0)
    blended_price = ppa_share * ppa_price + (1 - ppa_share) * MERCHANT_PRICE_GBP_MWH
    solar_revenue = solar_generation_mwh * blended_price
    bess_revenue = bess_mw * BESS_ARBITRAGE_GBP_MW_YR

    solar_opex = solar_capex * SOLAR_OPEX_PCT_CAPEX
    bess_opex = bess_capex * BESS_OPEX_PCT_CAPEX
    annual_ebitda = solar_revenue + bess_revenue - solar_opex - bess_opex

    r = DISCOUNT_RATE
    if r <= 0:
        pv_factor = LIFE_YEARS
    else:
        pv_factor = (1 - (1 + r) ** -LIFE_YEARS) / r
    npv = annual_ebitda * pv_factor - total_capex

    # IRR approximation (bisection)
    def _npv_at(rate):
        pv = LIFE_YEARS if rate <= 0 else (1 - (1 + rate) ** -LIFE_YEARS) / rate
        return annual_ebitda * pv - total_capex
    lo, hi = -0.1, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if _npv_at(mid) > 0:
            lo = mid
        else:
            hi = mid
    irr = (lo + hi) / 2

    lifetime_gen_mwh = solar_generation_mwh * LIFE_YEARS
    lcoe = (total_capex + (solar_opex + bess_opex) * LIFE_YEARS) / max(1.0, lifetime_gen_mwh)
    utilisation = 0.0
    if grid_headroom_mw and grid_headroom_mw > 0:
        utilisation = min(100.0, (solar_mw + bess_mw) / grid_headroom_mw * 100.0)
    land_used_ha = solar_mw * LAND_HA_PER_SOLAR_MW + bess_mw * LAND_HA_PER_BESS_MW

    return {
        "solar_mw": round(solar_mw, 2),
        "bess_mw": round(bess_mw, 2),
        "bess_hours": round(bess_hours, 2),
        "bess_mwh": round(bess_energy_mwh, 2),
        "ppa_share_pct": round(ppa_share * 100, 1),
        "ppa_price_gbp_mwh": round(ppa_price, 2),
        "capex_gbp_m": round(total_capex / 1_000_000, 2),
        "annual_ebitda_gbp_m": round(annual_ebitda / 1_000_000, 2),
        "npv_gbp_m": round(npv / 1_000_000, 2),
        "irr_pct": round(irr * 100, 2),
        "lcoe_gbp_per_mwh": round(lcoe, 2),
        "utilisation_pct": round(utilisation, 1),
        "land_used_ha": round(land_used_ha, 2),
        "land_available_ha": round(site_area_ha, 2),
        "grid_headroom_mw": round(grid_headroom_mw, 1) if grid_headroom_mw else None,
    }


def _analytic_best(bounds: dict[str, tuple[float, float]], ppa_price: float,
                   site_area_ha: float, grid_headroom_mw: float,
                   objective: str) -> dict[str, Any]:
    """Closed-form scan when scipy isn't available. Greedy solar-first with
    a small BESS kicker, capped by land + headroom."""
    solar_lo, solar_hi = bounds.get("solar_mw", (5.0, 80.0))
    bess_lo, bess_hi = bounds.get("bess_mw", (0.0, 40.0))
    bh_lo, bh_hi = bounds.get("bess_hours", (1.0, 4.0))
    ppa_lo, ppa_hi = bounds.get("ppa_share_pct", (0.0, 100.0))

    land_cap_solar = site_area_ha / LAND_HA_PER_SOLAR_MW if site_area_ha else solar_hi
    grid_cap = grid_headroom_mw if grid_headroom_mw else (solar_hi + bess_hi)
    solar_mw = _clamp(solar_lo, min(solar_hi, land_cap_solar, grid_cap * 0.8), solar_hi)
    bess_mw = _clamp(bess_lo, min(bess_hi, max(0.0, grid_cap - solar_mw)), bess_hi)
    bess_hours = _clamp(bh_lo, 2.0, bh_hi)
    ppa_share = _clamp(ppa_lo / 100.0, 0.5, ppa_hi / 100.0)
    kpis = _kpis(solar_mw, bess_mw, bess_hours, ppa_share,
                 ppa_price, site_area_ha, grid_headroom_mw)
    return {
        "ok": True,
        "provenance": "analytic_fallback",
        "objective": objective,
        "best_params": {
            "solar_mw": solar_mw, "bess_mw": bess_mw,
            "bess_hours": bess_hours, "ppa_share_pct": ppa_share * 100,
        },
        "kpis": kpis,
        "iterations": 1,
    }


def optimise_capacity_mix(
    objective: str = "max_npv",
    bounds: dict[str, tuple[float, float]] | None = None,
    ppa_price_gbp_mwh: float = 68.0,
    site_area_ha: float = 120.0,
    grid_headroom_mw: float = 50.0,
    initial: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Optimise (solar_mw, bess_mw, bess_hours, ppa_share) for `objective`.

    objective ∈ {max_npv, min_lcoe, max_utilisation}.
    Constraints: land area (ha), grid headroom (MW).
    Returns best_params + kpis + provenance ∈ {scipy_slsqp, analytic_fallback}.
    """
    bounds = bounds or {
        "solar_mw": (5.0, 80.0),
        "bess_mw": (0.0, 40.0),
        "bess_hours": (1.0, 4.0),
        "ppa_share_pct": (0.0, 100.0),
    }
    bounds = {k: tuple(v) for k, v in bounds.items()}

    try:
        from scipy.optimize import minimize  # type: ignore
    except ImportError:
        return _analytic_best(bounds, ppa_price_gbp_mwh, site_area_ha,
                              grid_headroom_mw, objective)

    solar_b = bounds.get("solar_mw", (5.0, 80.0))
    bess_b = bounds.get("bess_mw", (0.0, 40.0))
    bh_b = bounds.get("bess_hours", (1.0, 4.0))
    ppa_b = (bounds.get("ppa_share_pct", (0.0, 100.0))[0] / 100.0,
             bounds.get("ppa_share_pct", (0.0, 100.0))[1] / 100.0)
    scipy_bounds = [solar_b, bess_b, bh_b, ppa_b]

    init = initial or {}
    x0 = [
        init.get("solar_mw", (solar_b[0] + solar_b[1]) / 2),
        init.get("bess_mw", (bess_b[0] + bess_b[1]) / 4),
        init.get("bess_hours", 2.0),
        init.get("ppa_share_pct", 50.0) / 100.0,
    ]

    trace: list[float] = []

    def _objective(x):
        s, b, h, p = x
        k = _kpis(s, b, h, p, ppa_price_gbp_mwh, site_area_ha, grid_headroom_mw)
        if objective == "min_lcoe":
            val = k["lcoe_gbp_per_mwh"]
        elif objective == "max_utilisation":
            val = -k["utilisation_pct"]
        else:  # max_npv
            val = -k["npv_gbp_m"]
        trace.append(val)
        return val

    # Constraints: land + grid headroom (slack form g(x) >= 0)
    constraints = []
    if site_area_ha and site_area_ha > 0:
        constraints.append({
            "type": "ineq",
            "fun": lambda x: site_area_ha - (x[0] * LAND_HA_PER_SOLAR_MW + x[1] * LAND_HA_PER_BESS_MW),
        })
    if grid_headroom_mw and grid_headroom_mw > 0:
        constraints.append({
            "type": "ineq",
            "fun": lambda x: grid_headroom_mw - (x[0] + x[1]),
        })

    try:
        res = minimize(
            _objective, x0=x0, method="SLSQP",
            bounds=scipy_bounds, constraints=constraints,
            options={"maxiter": 60, "ftol": 1e-3, "disp": False},
        )
        s, b, h, p = res.x
        kpis = _kpis(s, b, h, p, ppa_price_gbp_mwh, site_area_ha, grid_headroom_mw)
        return {
            "ok": bool(res.success),
            "provenance": "scipy_slsqp",
            "objective": objective,
            "best_params": {
                "solar_mw": round(float(s), 2),
                "bess_mw": round(float(b), 2),
                "bess_hours": round(float(h), 2),
                "ppa_share_pct": round(float(p) * 100, 1),
            },
            "kpis": kpis,
            "iterations": len(trace),
            "message": str(res.message),
        }
    except Exception as e:
        log.warning("SLSQP failed, falling back: %s", e)
        return _analytic_best(bounds, ppa_price_gbp_mwh, site_area_ha,
                              grid_headroom_mw, objective)


def compute_design_kpis(
    solar_mw: float,
    bess_mw: float,
    bess_hours: float = 2.0,
    ppa_price_gbp_mwh: float = 68.0,
    ppa_share_pct: float = 50.0,
    workload_mw: float = 0.0,
    site_area_ha: float = 120.0,
    grid_headroom_mw: float = 50.0,
) -> dict[str, Any]:
    """Derived KPIs for a capacity-mix state. Used by mutate_design to show
    the user what their edit did. workload_mw is DC IT-load when present."""
    k = _kpis(solar_mw, bess_mw, bess_hours, ppa_share_pct / 100.0,
              ppa_price_gbp_mwh, site_area_ha, grid_headroom_mw)
    k["workload_mw"] = round(workload_mw, 2) if workload_mw else 0.0
    if workload_mw:
        # DC offset analysis — fraction of IT load covered by onsite renewables
        onsite_annual = solar_mw * 8760 * (SOLAR_CF_PCT / 100.0)
        load_annual = workload_mw * 8760 * 0.85
        k["renewable_cover_pct"] = round(min(100.0, onsite_annual / max(1.0, load_annual) * 100), 1)
    return k
