"""Multi-Asset System Optimizer — MILP-based sizing using scipy."""

from __future__ import annotations
import logging
import math
from typing import Any

import numpy as np
from scipy.optimize import minimize

log = logging.getLogger(__name__)

CAPEX = {"solar": 500_000, "wind": 1_200_000, "bess_mwh": 250_000, "gas": 400_000}  # £/MW or £/MWh
OPEX_PCT = {"solar": 0.015, "wind": 0.025, "bess": 0.01, "gas": 0.03}
LAND_HA_PER_MW = {"solar": 2.0, "wind": 8.0, "bess_per_mwh": 0.1, "gas": 0.05}


def optimize_system(config: dict) -> dict[str, Any]:
    """Optimize energy system sizing via constrained optimization."""
    land_ha = config.get("land_area_ha", 100)
    grid_limit = config.get("grid_export_limit_mw", 50)
    load_24h = config.get("load_profile_24h", [50] * 24)
    solar_cf = config.get("solar_cf_24h", [0, 0, 0, 0, 0, 0.02, 0.05, 0.08, 0.12, 0.15, 0.17, 0.18, 0.18, 0.17, 0.15, 0.12, 0.08, 0.05, 0.02, 0, 0, 0, 0, 0])
    wind_cf = config.get("wind_cf_24h", [0.30] * 24)
    target_cfe = config.get("target_cfe_pct", 80)
    budget = config.get("budget_gbp", 100_000_000)
    price = config.get("electricity_price_gbp_mwh", 50)
    life = config.get("project_life_years", 25)
    dr = config.get("discount_rate", 0.08)

    annual_demand = sum(load_24h) * 365

    def npv_objective(x):
        solar_mw, wind_mw, bess_mwh, gas_mw = x
        bess_mw = bess_mwh / 4

        # Annual generation
        solar_gen = solar_mw * sum(solar_cf) * 365
        wind_gen = wind_mw * sum(wind_cf) * 365

        # Revenue from generation (self-consumption + export)
        total_gen = solar_gen + wind_gen
        revenue = min(total_gen, annual_demand) * price + max(0, total_gen - annual_demand) * price * 0.7

        # Gas cost
        gas_hours = max(0, 24 - sum(1 for h in range(24) if solar_mw * solar_cf[h] + wind_mw * wind_cf[h] >= load_24h[h]))
        gas_cost = gas_mw * gas_hours * 365 * 80  # £80/MWh gas

        # CAPEX
        capex = solar_mw * CAPEX["solar"] + wind_mw * CAPEX["wind"] + bess_mwh * CAPEX["bess_mwh"] + gas_mw * CAPEX["gas"]

        # OPEX
        opex = (solar_mw * CAPEX["solar"] * OPEX_PCT["solar"] + wind_mw * CAPEX["wind"] * OPEX_PCT["wind"] +
                bess_mwh * CAPEX["bess_mwh"] * OPEX_PCT["bess"] + gas_mw * CAPEX["gas"] * OPEX_PCT["gas"])

        # NPV
        npv = -capex
        for y in range(1, life + 1):
            npv += (revenue - opex - gas_cost) / (1 + dr) ** y

        return -npv  # Minimize negative NPV

    # Constraints
    def land_constraint(x):
        return land_ha - (x[0] * LAND_HA_PER_MW["solar"] + x[1] * LAND_HA_PER_MW["wind"] + x[2] * LAND_HA_PER_MW["bess_per_mwh"] + x[3] * LAND_HA_PER_MW["gas"])

    def budget_constraint(x):
        return budget - (x[0] * CAPEX["solar"] + x[1] * CAPEX["wind"] + x[2] * CAPEX["bess_mwh"] + x[3] * CAPEX["gas"])

    def cfe_constraint(x):
        solar_gen = x[0] * sum(solar_cf) * 365
        wind_gen = x[1] * sum(wind_cf) * 365
        clean = solar_gen + wind_gen
        return clean / max(annual_demand, 1) * 100 - target_cfe

    bounds = [(0, land_ha / 2), (0, land_ha / 8), (0, 1000), (0, 200)]
    constraints = [
        {"type": "ineq", "fun": land_constraint},
        {"type": "ineq", "fun": budget_constraint},
        {"type": "ineq", "fun": cfe_constraint},
    ]

    x0 = [20, 10, 50, 10]
    result = minimize(npv_objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)

    solar_mw, wind_mw, bess_mwh, gas_mw = [max(0, v) for v in result.x]
    bess_mw = bess_mwh / 4

    capex_total = solar_mw * CAPEX["solar"] + wind_mw * CAPEX["wind"] + bess_mwh * CAPEX["bess_mwh"] + gas_mw * CAPEX["gas"]
    opex_total = (solar_mw * CAPEX["solar"] * OPEX_PCT["solar"] + wind_mw * CAPEX["wind"] * OPEX_PCT["wind"] +
                  bess_mwh * CAPEX["bess_mwh"] * OPEX_PCT["bess"] + gas_mw * CAPEX["gas"] * OPEX_PCT["gas"])

    solar_gen = solar_mw * sum(solar_cf) * 365
    wind_gen = wind_mw * sum(wind_cf) * 365
    total_gen = solar_gen + wind_gen
    cfe_pct = round(min(total_gen / max(annual_demand, 1) * 100, 100), 1)

    npv_val = -result.fun
    revenue_yr1 = min(total_gen, annual_demand) * price
    irr = (revenue_yr1 - opex_total) / max(capex_total, 1) * 100
    lcoe = capex_total / max(total_gen * life, 1) + opex_total / max(total_gen, 1) if total_gen > 0 else 0
    payback = capex_total / max(revenue_yr1 - opex_total, 1) if revenue_yr1 > opex_total else 99

    # Dispatch profile
    dispatch = {"solar": [], "wind": [], "bess": [], "gas": [], "grid": []}
    soc = bess_mwh * 0.5
    for h in range(24):
        s = solar_mw * solar_cf[h]
        w = wind_mw * wind_cf[h]
        load = load_24h[h]
        deficit = load - s - w
        b = 0
        g = 0
        if deficit > 0 and soc > bess_mwh * 0.1:
            b = min(deficit, bess_mw, soc - bess_mwh * 0.1)
            soc -= b
            deficit -= b
        elif deficit < 0 and soc < bess_mwh * 0.9:
            charge = min(-deficit, bess_mw, bess_mwh * 0.9 - soc)
            soc += charge * 0.92
            b = -charge
        if deficit > 0:
            g = min(deficit, gas_mw)
            deficit -= g
        grid = deficit
        dispatch["solar"].append(round(s, 2))
        dispatch["wind"].append(round(w, 2))
        dispatch["bess"].append(round(b, 2))
        dispatch["gas"].append(round(g, 2))
        dispatch["grid"].append(round(max(0, grid), 2))

    return {
        "optimal": {"solar_mw": round(solar_mw, 1), "wind_mw": round(wind_mw, 1), "bess_mwh": round(bess_mwh, 1), "bess_mw": round(bess_mw, 1), "gas_mw": round(gas_mw, 1)},
        "financials": {
            "capex_gbp": round(capex_total), "opex_gbp_year": round(opex_total),
            "npv_gbp": round(npv_val), "irr_pct": round(irr, 1), "lcoe_gbp_mwh": round(lcoe, 2), "payback_years": round(payback, 1),
        },
        "energy": {
            "annual_generation_mwh": round(total_gen, 1), "annual_demand_mwh": round(annual_demand, 1),
            "cfe_pct": cfe_pct, "curtailment_pct": round(max(0, total_gen - annual_demand) / max(total_gen, 1) * 100, 1),
        },
        "dispatch_24h": dispatch,
        "solver_success": result.success,
    }
