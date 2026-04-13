"""24/7 Carbon-Free Energy (CFE) Matching Engine."""

from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger(__name__)


def compute_cfe_score(
    load_24h: list[float],
    solar_24h: list[float],
    wind_24h: list[float] = None,
    bess_mwh: float = 0,
    bess_mw: float = 0,
    grid_carbon_24h: list[float] = None,
    ppa_24h: list[float] = None,
) -> dict[str, Any]:
    """Compute hourly CFE score with optimal BESS dispatch."""
    wind_24h = wind_24h or [0] * 24
    grid_carbon_24h = grid_carbon_24h or [200] * 24  # gCO2/kWh default UK average
    ppa_24h = ppa_24h or [0] * 24

    soc = bess_mwh * 0.5  # Start at 50% SOC
    soc_min = bess_mwh * 0.1
    soc_max = bess_mwh * 0.9
    eta = 0.92  # Round-trip efficiency sqrt

    hourly_cfe = []
    bess_dispatch = []
    total_clean = 0
    total_demand = 0
    gap_mwh = 0
    surplus_mwh = 0
    bess_cycles = 0

    for h in range(24):
        load = load_24h[h]
        clean = solar_24h[h] + wind_24h[h] + ppa_24h[h]
        total_demand += load

        deficit = load - clean
        bess_action = 0

        if deficit > 0 and soc > soc_min:
            # Discharge BESS to cover deficit
            discharge = min(deficit, bess_mw, (soc - soc_min) * eta)
            bess_action = -discharge
            soc -= discharge / eta
            clean += discharge
        elif deficit < 0 and soc < soc_max:
            # Charge BESS from surplus
            charge = min(-deficit, bess_mw, (soc_max - soc))
            bess_action = charge
            soc += charge * eta
            surplus_mwh += max(0, -deficit - charge)
        elif deficit < 0:
            surplus_mwh += -deficit

        bess_dispatch.append(round(bess_action, 2))
        if bess_action < 0:
            bess_cycles += abs(bess_action) / max(bess_mwh, 1)

        matched = min(clean, load)
        total_clean += matched
        gap_mwh += max(0, load - clean)

        cfe_pct = min(matched / load * 100, 100) if load > 0 else 100
        hourly_cfe.append(round(cfe_pct, 1))

    annual_cfe = round(total_clean / total_demand * 100, 1) if total_demand > 0 else 0

    worst_hours = sorted(range(24), key=lambda h: hourly_cfe[h])[:6]

    return {
        "hourly_cfe": hourly_cfe,
        "daily_cfe": annual_cfe,
        "annual_cfe": annual_cfe,
        "total_clean_mwh": round(total_clean, 2),
        "total_demand_mwh": round(total_demand, 2),
        "gap_mwh": round(gap_mwh, 2),
        "surplus_mwh": round(surplus_mwh, 2),
        "bess_dispatch": bess_dispatch,
        "bess_cycles": round(bess_cycles, 2),
        "worst_hours": worst_hours,
    }


def gap_analysis(load_mw: float, cfe_result: dict, target_pct: float = 90) -> dict[str, Any]:
    """Identify what's needed to close the CFE gap to target."""
    current = cfe_result["annual_cfe"]
    gap_mwh = cfe_result["gap_mwh"]
    total_demand = cfe_result["total_demand_mwh"]

    if current >= target_pct:
        return {"gap_hours": 0, "additional_solar_mw": 0, "additional_wind_mw": 0, "additional_bess_mwh": 0, "estimated_cost_gbp": 0, "message": f"Already at {current}% CFE, exceeds {target_pct}% target"}

    # Required additional clean energy
    target_clean = total_demand * target_pct / 100
    current_clean = cfe_result["total_clean_mwh"]
    needed_mwh = target_clean - current_clean

    # Count gap hours
    gap_hours = sum(1 for h in cfe_result["hourly_cfe"] if h < target_pct)

    # Estimate additional capacity needed
    # Solar CF ~11% UK, Wind CF ~30% UK
    solar_cf = 0.11
    wind_cf = 0.30
    additional_solar_mw = round(needed_mwh * 0.5 / (solar_cf * 24), 1)  # 50% from solar
    additional_wind_mw = round(needed_mwh * 0.3 / (wind_cf * 24), 1)   # 30% from wind
    additional_bess_mwh = round(needed_mwh * 0.2, 1)                    # 20% from storage

    # Cost estimates
    solar_cost = additional_solar_mw * 500_000
    wind_cost = additional_wind_mw * 1_200_000
    bess_cost = additional_bess_mwh * 250_000
    total_cost = solar_cost + wind_cost + bess_cost

    return {
        "current_cfe_pct": current,
        "target_cfe_pct": target_pct,
        "gap_hours": gap_hours,
        "gap_mwh": round(needed_mwh, 1),
        "additional_solar_mw": additional_solar_mw,
        "additional_wind_mw": additional_wind_mw,
        "additional_bess_mwh": additional_bess_mwh,
        "estimated_cost_gbp": round(total_cost),
        "cost_breakdown": {"solar": round(solar_cost), "wind": round(wind_cost), "bess": round(bess_cost)},
    }


def granular_certificate_cost(gap_mwh: float, market: str = "uk") -> dict[str, Any]:
    """Estimate cost of closing CFE gap via Granular Energy Certificates."""
    # UK GC price estimates (2026)
    prices = {"off_peak": 8, "shoulder": 15, "peak": 35, "super_peak": 50}  # £/MWh

    # Assume gap distribution: 40% peak, 30% shoulder, 20% off-peak, 10% super-peak
    avg_price = 0.1 * prices["super_peak"] + 0.4 * prices["peak"] + 0.3 * prices["shoulder"] + 0.2 * prices["off_peak"]
    total_cost = gap_mwh * avg_price

    return {
        "gc_volume_mwh": round(gap_mwh, 1),
        "avg_price_per_mwh": round(avg_price, 2),
        "gc_cost_gbp": round(total_cost),
        "market": market,
        "price_breakdown": prices,
    }


def optimal_cfe_portfolio(load_mw: float, lat: float, lon: float, target_cfe_pct: float = 90, budget_gbp: float = 50_000_000) -> dict[str, Any]:
    """Optimize portfolio to achieve target CFE within budget."""
    # Simple heuristic optimizer
    # UK solar CF by hour (summer-weighted average)
    solar_cf_24h = [0, 0, 0, 0, 0, 0.02, 0.05, 0.08, 0.12, 0.15, 0.17, 0.18, 0.18, 0.17, 0.15, 0.12, 0.08, 0.05, 0.02, 0, 0, 0, 0, 0]
    wind_cf_24h = [0.32, 0.31, 0.30, 0.29, 0.28, 0.27, 0.26, 0.27, 0.28, 0.29, 0.30, 0.31, 0.32, 0.33, 0.34, 0.33, 0.32, 0.31, 0.30, 0.31, 0.32, 0.33, 0.33, 0.32]

    load_24h = [load_mw] * 24
    best = None

    for solar_mw in range(0, int(budget_gbp / 500_000) + 1, 5):
        remaining = budget_gbp - solar_mw * 500_000
        for wind_mw in range(0, int(remaining / 1_200_000) + 1, 5):
            remaining2 = remaining - wind_mw * 1_200_000
            bess_mwh = min(remaining2 / 250_000, solar_mw * 4)
            bess_mw = bess_mwh / 4

            solar_24h = [solar_mw * cf for cf in solar_cf_24h]
            wind_24h_gen = [wind_mw * cf for cf in wind_cf_24h]

            result = compute_cfe_score(load_24h, solar_24h, wind_24h_gen, bess_mwh, bess_mw)
            cost = solar_mw * 500_000 + wind_mw * 1_200_000 + bess_mwh * 250_000

            if result["annual_cfe"] >= target_cfe_pct:
                if best is None or cost < best["total_cost_gbp"]:
                    best = {
                        "solar_mw": solar_mw, "wind_mw": wind_mw, "bess_mwh": round(bess_mwh, 1), "bess_mw": round(bess_mw, 1),
                        "achieved_cfe_pct": result["annual_cfe"], "total_cost_gbp": round(cost),
                    }
            elif best is None or result["annual_cfe"] > best.get("achieved_cfe_pct", 0):
                best = {
                    "solar_mw": solar_mw, "wind_mw": wind_mw, "bess_mwh": round(bess_mwh, 1), "bess_mw": round(bess_mw, 1),
                    "achieved_cfe_pct": result["annual_cfe"], "total_cost_gbp": round(cost),
                }

    gc_gap = gap_analysis(load_mw, compute_cfe_score(load_24h, [0]*24), target_cfe_pct)
    if best:
        best["gc_mwh_to_close_gap"] = max(0, gc_gap["gap_mwh"] - (best.get("achieved_cfe_pct", 0) / 100 * sum(load_24h)))

    return best or {"error": "Could not find feasible portfolio within budget"}
