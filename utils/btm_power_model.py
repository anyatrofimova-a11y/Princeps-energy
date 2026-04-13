"""Behind-the-Meter Power Architecture Modeler for data centres."""

from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger(__name__)


def simulate_btm_dispatch(config: dict) -> dict[str, Any]:
    """Simulate 24h behind-the-meter power dispatch."""
    load_mw = config.get("load_mw", 50)
    grid_limit = config.get("grid_import_limit_mw", 100)
    solar_mw = config.get("solar_mw", 0)
    solar_cf = config.get("solar_cf_24h", [0]*24)
    wind_mw = config.get("wind_mw", 0)
    wind_cf = config.get("wind_cf_24h", [0.30]*24)
    gas_mw = config.get("gas_mw", 0)
    gas_eff = config.get("gas_efficiency", 0.40)
    bess_mwh = config.get("bess_mwh", 0)
    bess_mw = config.get("bess_mw", bess_mwh / 4 if bess_mwh else 0)
    fuel_cell_mw = config.get("fuel_cell_mw", 0)
    fuel_cell_eff = config.get("fuel_cell_efficiency", 0.50)
    grid_price = config.get("grid_price_24h", [50]*24)
    gas_price_therm = config.get("gas_price_gbp_therm", 0.80)

    gas_price_mwh = gas_price_therm / 0.02931 / gas_eff  # Convert therms to £/MWh fuel
    fc_price_mwh = gas_price_therm / 0.02931 / fuel_cell_eff

    dispatch = {k: [] for k in ("solar", "wind", "bess", "grid", "gas", "fuel_cell", "curtailed")}
    cost_24h = []
    soc = bess_mwh * 0.5
    soc_min, soc_max = bess_mwh * 0.1, bess_mwh * 0.9
    eta = 0.92

    totals = {k: 0.0 for k in ("solar", "wind", "bess_discharge", "bess_charge", "grid_import", "grid_export", "gas", "fuel_cell", "curtailed", "cost")}

    for h in range(24):
        s = solar_mw * solar_cf[h]
        w = wind_mw * wind_cf[h]
        remaining = load_mw

        # Priority 1: Solar
        used_s = min(s, remaining)
        remaining -= used_s
        # Priority 2: Wind
        used_w = min(w, remaining)
        remaining -= used_w
        # Priority 3: BESS discharge
        used_b = 0
        if remaining > 0 and soc > soc_min:
            used_b = min(remaining, bess_mw, (soc - soc_min) * eta)
            soc -= used_b / eta
            remaining -= used_b
        # Priority 4: Grid
        used_grid = min(remaining, grid_limit)
        remaining -= used_grid
        # Priority 5: Fuel cell
        used_fc = min(remaining, fuel_cell_mw)
        remaining -= used_fc
        # Priority 6: Gas
        used_gas = min(remaining, gas_mw)
        remaining -= used_gas

        # Charge BESS from surplus
        surplus = (s - used_s) + (w - used_w)
        charge = 0
        if surplus > 0 and soc < soc_max:
            charge = min(surplus, bess_mw, soc_max - soc)
            soc += charge * eta
            surplus -= charge

        curtailed = surplus
        hour_cost = used_grid * grid_price[h] + used_gas * gas_price_mwh + used_fc * fc_price_mwh

        dispatch["solar"].append(round(used_s, 2))
        dispatch["wind"].append(round(used_w, 2))
        dispatch["bess"].append(round(used_b - charge, 2))  # Positive = discharge
        dispatch["grid"].append(round(used_grid, 2))
        dispatch["gas"].append(round(used_gas, 2))
        dispatch["fuel_cell"].append(round(used_fc, 2))
        dispatch["curtailed"].append(round(curtailed, 2))
        cost_24h.append(round(hour_cost, 2))

        totals["solar"] += used_s
        totals["wind"] += used_w
        totals["bess_discharge"] += used_b
        totals["bess_charge"] += charge
        totals["grid_import"] += used_grid
        totals["gas"] += used_gas
        totals["fuel_cell"] += used_fc
        totals["curtailed"] += curtailed
        totals["cost"] += hour_cost

    total_demand = load_mw * 24
    clean = totals["solar"] + totals["wind"] + totals["bess_discharge"]
    cfe_pct = round(min(clean / total_demand * 100, 100), 1) if total_demand > 0 else 0
    bess_cycles = round(totals["bess_discharge"] / max(bess_mwh, 1), 2) if bess_mwh else 0

    return {
        "dispatch_24h": dispatch,
        "summary": {
            "total_demand_mwh": round(total_demand, 1),
            "solar_mwh": round(totals["solar"], 1),
            "wind_mwh": round(totals["wind"], 1),
            "bess_cycles": bess_cycles,
            "grid_import_mwh": round(totals["grid_import"], 1),
            "gas_mwh": round(totals["gas"], 1),
            "fuel_cell_mwh": round(totals["fuel_cell"], 1),
            "curtailed_mwh": round(totals["curtailed"], 1),
        },
        "cost_24h": cost_24h,
        "total_cost_gbp": round(totals["cost"], 2),
        "cfe_pct": cfe_pct,
        "reliability": {
            "met_load": totals["grid_import"] + totals["gas"] + totals["fuel_cell"] + clean >= total_demand * 0.99,
            "shortfall_mwh": round(max(0, total_demand - clean - totals["grid_import"] - totals["gas"] - totals["fuel_cell"]), 1),
        },
    }


def assess_reliability(config: dict) -> dict[str, Any]:
    """Assess N+1 redundancy and islanding capability."""
    load_mw = config.get("load_mw", 50)
    sources = {
        "grid": config.get("grid_import_limit_mw", 100),
        "solar_peak": config.get("solar_mw", 0) * 0.18,
        "wind_avg": config.get("wind_mw", 0) * 0.30,
        "gas": config.get("gas_mw", 0),
        "fuel_cell": config.get("fuel_cell_mw", 0),
        "bess": config.get("bess_mw", config.get("bess_mwh", 0) / 4),
    }

    total_capacity = sum(sources.values())
    largest_source = max(sources.values())
    n_plus_1 = (total_capacity - largest_source) >= load_mw
    concurrent_maintainable = (total_capacity - sources.get("gas", 0)) >= load_mw

    bess_mwh = config.get("bess_mwh", 0)
    non_grid = sources["solar_peak"] + sources["wind_avg"] + sources["gas"] + sources["fuel_cell"]
    island_deficit = max(0, load_mw - non_grid)
    island_hours = bess_mwh * 0.8 / max(island_deficit, 0.1) if island_deficit > 0 else 999

    uptime = 99.99 if n_plus_1 else 99.9 if concurrent_maintainable else 99.0
    tier = "4" if n_plus_1 and concurrent_maintainable else "3" if n_plus_1 else "2" if concurrent_maintainable else "1"

    return {
        "n_plus_1": n_plus_1,
        "concurrent_maintainable": concurrent_maintainable,
        "island_hours": round(min(island_hours, 168), 1),
        "uptime_pct": uptime,
        "tier_equivalent": tier,
        "source_capacities": {k: round(v, 1) for k, v in sources.items()},
        "total_capacity_mw": round(total_capacity, 1),
        "load_mw": load_mw,
    }


def power_flow_sankey(dispatch_24h: dict) -> dict[str, Any]:
    """Generate Sankey diagram data from dispatch."""
    nodes = ["Solar", "Wind", "BESS", "Gas", "Fuel Cell", "Grid", "Load", "Curtailed"]
    links = []

    for source_key, node_name in [("solar", "Solar"), ("wind", "Wind"), ("bess", "BESS"), ("gas", "Gas"), ("fuel_cell", "Fuel Cell"), ("grid", "Grid")]:
        total = sum(max(0, v) for v in dispatch_24h.get(source_key, []))
        if total > 0:
            links.append({"source": node_name, "target": "Load", "value": round(total, 1)})

    curtailed = sum(max(0, v) for v in dispatch_24h.get("curtailed", []))
    if curtailed > 0:
        links.append({"source": "Solar", "target": "Curtailed", "value": round(curtailed, 1)})

    return {"nodes": nodes, "links": links}
