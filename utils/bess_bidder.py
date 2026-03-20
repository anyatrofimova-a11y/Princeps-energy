"""BESS Bidder — multi-market battery bidding engine.

Adapted from BessBidder (Kim K. Miskiw et al., ACM e-Energy 2025).
Implements:
  1. Day-ahead MILP arbitrage optimizer (PuLP, no Pyomo needed)
  2. Rolling intrinsic intraday strategy
  3. Coordinated multi-market dispatch schedule

All strategies work with UK wholesale price data (Agile/N2EX/EPEX).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

# PuLP for MILP — lightweight, pure-Python, ships with CBC solver
try:
    from pulp import (
        LpMaximize, LpProblem, LpVariable, lpSum,
        PULP_CBC_CMD, LpStatus,
    )
    HAS_PULP = True
except ImportError:
    HAS_PULP = False


# ── Battery Parameters ─────────────────────────────────────────────────────

@dataclass
class BatterySpec:
    """Battery energy storage system specification."""
    power_mw: float = 50.0          # MW nameplate
    energy_mwh: float = 100.0       # MWh capacity
    c_rate: float = 1.0             # C-rate (power/energy)
    round_trip_efficiency: float = 0.86
    max_cycles_per_day: float = 1.5
    min_soc: float = 0.05           # 5% minimum SoC
    max_soc: float = 0.95           # 95% maximum SoC
    degradation_per_cycle: float = 0.0001  # 0.01% per cycle


# ── UK Price Simulation (for when no real data available) ───────────────────

def simulate_uk_prices(hours: int = 24, base_date: Optional[datetime] = None) -> dict:
    """Generate realistic UK wholesale electricity prices (£/MWh).

    Based on typical N2EX/EPEX day-ahead patterns for GB.
    Returns both day-ahead forecast and 'realised' prices with noise.
    """
    if base_date is None:
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    timestamps = [base_date + timedelta(hours=h) for h in range(hours)]
    da_prices = []
    realised_prices = []

    for h in range(hours):
        hour_of_day = (base_date.hour + h) % 24
        month = base_date.month

        # Base price — seasonal
        if month in (12, 1, 2):      # winter
            base = 85
        elif month in (6, 7, 8):     # summer
            base = 55
        else:                         # shoulder
            base = 70

        # Time-of-day shape (UK demand curve)
        if 0 <= hour_of_day < 5:
            tod_mult = 0.65   # overnight low
        elif 5 <= hour_of_day < 7:
            tod_mult = 0.85   # morning ramp
        elif 7 <= hour_of_day < 9:
            tod_mult = 1.20   # morning peak
        elif 9 <= hour_of_day < 12:
            tod_mult = 1.05   # mid-morning
        elif 12 <= hour_of_day < 16:
            tod_mult = 0.90   # solar depression / lunch
        elif 16 <= hour_of_day < 19:
            tod_mult = 1.35   # evening peak (4-7 PM)
        elif 19 <= hour_of_day < 21:
            tod_mult = 1.15   # post-peak
        else:
            tod_mult = 0.80   # late evening

        # Weekend discount
        weekday = (base_date + timedelta(hours=h)).weekday()
        if weekday >= 5:
            tod_mult *= 0.88

        da_price = base * tod_mult + random.gauss(0, 5)
        # Realised = DA + noise (mean-reverting spread)
        realised = da_price + random.gauss(0, 8)

        da_prices.append(round(max(0, da_price), 2))
        realised_prices.append(round(max(0, realised), 2))

    return {
        "timestamps": [t.isoformat() for t in timestamps],
        "da_prices_gbp_mwh": da_prices,
        "realised_prices_gbp_mwh": realised_prices,
        "hours": hours,
    }


# ── Day-Ahead MILP Optimizer ───────────────────────────────────────────────

def optimize_day_ahead(
    prices_forecast: list[float],
    battery: BatterySpec | None = None,
    prices_realised: list[float] | None = None,
) -> dict:
    """Optimal day-ahead arbitrage schedule using MILP (PuLP/CBC).

    Maximises revenue from buy-low/sell-high given price forecasts.
    Based on BessBidder DayAheadMarketOptimizationModel.

    Args:
        prices_forecast: Hourly DA price forecast (£/MWh), length = hours
        battery: Battery specification (defaults to 50MW/100MWh)
        prices_realised: Actual prices for ex-post P&L (optional)

    Returns:
        Dict with schedule, revenue, SoC profile, trades
    """
    if not HAS_PULP:
        return {"error": "PuLP not installed. Run: pip install pulp"}

    if battery is None:
        battery = BatterySpec()

    hours = len(prices_forecast)
    prices = np.array(prices_forecast, dtype=float)
    efficiency = math.sqrt(battery.round_trip_efficiency)
    cap = battery.energy_mwh
    power = battery.power_mw
    max_cycles = battery.max_cycles_per_day

    # Build MILP
    prob = LpProblem("BESS_DayAhead", LpMaximize)

    # Decision variables
    charge = [LpVariable(f"charge_{t}", 0, power) for t in range(hours)]
    discharge = [LpVariable(f"discharge_{t}", 0, power) for t in range(hours)]
    soc = [LpVariable(f"soc_{t}", cap * battery.min_soc, cap * battery.max_soc) for t in range(hours)]
    # Binary: 1 = charging, 0 = discharging/idle
    mode = [LpVariable(f"mode_{t}", cat="Binary") for t in range(hours)]

    # Objective: maximise revenue
    # Revenue = sell revenue - buy cost
    # Sell: discharge * price * efficiency (losses before meter)
    # Buy: charge * price / efficiency (need more from grid)
    prob += lpSum(
        prices[t] * discharge[t] * efficiency
        - prices[t] * charge[t] / efficiency
        for t in range(hours)
    )

    # Constraints
    start_soc = cap * 0.5  # Start at 50% SoC

    for t in range(hours):
        # SoC balance
        if t == 0:
            prob += soc[t] == start_soc + charge[t] - discharge[t]
        else:
            prob += soc[t] == soc[t - 1] + charge[t] - discharge[t]

        # No simultaneous charge/discharge (big-M)
        prob += charge[t] <= mode[t] * power
        prob += discharge[t] <= (1 - mode[t]) * power

    # End SoC = start SoC (energy neutral per day)
    prob += soc[hours - 1] + charge[hours - 1] - discharge[hours - 1] == start_soc

    # Max cycles constraint
    prob += lpSum(charge[t] + discharge[t] for t in range(hours)) <= max_cycles * 2 * cap

    # Solve
    prob.solve(PULP_CBC_CMD(msg=0))

    status = LpStatus[prob.status]
    if status != "Optimal":
        return {"error": f"Solver status: {status}", "status": status}

    # Extract results
    schedule = []
    soc_profile = []
    trades = []
    total_revenue = 0.0

    for t in range(hours):
        ch = charge[t].value() or 0
        dis = discharge[t].value() or 0
        s = soc[t].value() or 0
        soc_pct = round(s / cap * 100, 1)

        # Revenue from this hour
        sell_rev = prices[t] * dis * efficiency
        buy_cost = prices[t] * ch / efficiency
        net = sell_rev - buy_cost
        total_revenue += net

        action = "idle"
        power_mw = 0
        if ch > 0.01:
            action = "charge"
            power_mw = round(-ch, 2)
        elif dis > 0.01:
            action = "discharge"
            power_mw = round(dis, 2)

        entry = {
            "hour": t,
            "action": action,
            "power_mw": power_mw,
            "soc_pct": soc_pct,
            "price_gbp_mwh": round(prices[t], 2),
            "revenue_gbp": round(net, 2),
        }

        # If realised prices available, compute actual P&L
        if prices_realised:
            actual_sell = prices_realised[t] * dis * efficiency
            actual_buy = prices_realised[t] * ch / efficiency
            entry["realised_revenue_gbp"] = round(actual_sell - actual_buy, 2)
            entry["realised_price_gbp_mwh"] = round(prices_realised[t], 2)

        schedule.append(entry)
        soc_profile.append(soc_pct)

        if action != "idle":
            trades.append({
                "hour": t,
                "side": "buy" if action == "charge" else "sell",
                "volume_mw": round(abs(power_mw), 2),
                "price_gbp_mwh": round(prices[t], 2),
            })

    realised_total = None
    if prices_realised:
        realised_total = round(sum(e.get("realised_revenue_gbp", 0) for e in schedule), 2)

    return {
        "status": "optimal",
        "strategy": "day_ahead_milp",
        "battery": {
            "power_mw": battery.power_mw,
            "energy_mwh": battery.energy_mwh,
            "efficiency": battery.round_trip_efficiency,
        },
        "forecast_revenue_gbp": round(total_revenue, 2),
        "realised_revenue_gbp": realised_total,
        "schedule": schedule,
        "soc_profile": soc_profile,
        "trades": trades,
        "num_trades": len(trades),
        "cycles": round(sum(abs(e["power_mw"]) for e in schedule) / (2 * cap), 2),
    }


# ── Rolling Intrinsic (Intraday) ──────────────────────────────────────────

def rolling_intrinsic(
    prices: list[float],
    battery: BatterySpec | None = None,
    bucket_size_hours: float = 0.25,
    discount_rate: float = 0.02,
    existing_positions: list[float] | None = None,
) -> dict:
    """Rolling intrinsic intraday trading strategy.

    Simplified version of BessBidder's rolling_intrinsic.py.
    Optimises charge/discharge decisions bucket-by-bucket using
    discounted price signals.

    Args:
        prices: Price signal (£/MWh) at bucket resolution
        battery: Battery spec
        bucket_size_hours: Duration of each bucket (0.25 = 15min)
        discount_rate: Price discount factor for time value
        existing_positions: Net position from prior market (DA)

    Returns:
        Dict with trades, schedule, revenue
    """
    if battery is None:
        battery = BatterySpec()

    n = len(prices)
    efficiency = math.sqrt(battery.round_trip_efficiency)
    cap = battery.energy_mwh
    power = battery.power_mw
    max_energy_per_bucket = power * bucket_size_hours

    # Current SoC tracking
    soc = cap * 0.5  # Start at 50%
    total_revenue = 0.0
    schedule = []
    trades = []
    cycles_used = 0.0

    # Existing positions from day-ahead
    positions = existing_positions or [0.0] * n

    for t in range(n):
        price = prices[t]
        position = positions[t] if t < len(positions) else 0.0

        # Discount future prices for spread calculation
        future_prices = []
        for f in range(t + 1, min(t + 8, n)):
            dt_hours = (f - t) * bucket_size_hours
            if price > 0:
                disc = math.exp(-discount_rate * dt_hours)
            else:
                disc = math.exp(discount_rate * dt_hours)
            future_prices.append(prices[f] * disc)

        if not future_prices:
            schedule.append({
                "bucket": t, "action": "idle", "power_mw": 0,
                "soc_pct": round(soc / cap * 100, 1),
                "price_gbp_mwh": round(price, 2), "revenue_gbp": 0,
            })
            continue

        avg_future = np.mean(future_prices)
        spread = avg_future - price

        # Decision logic
        action = "idle"
        energy = 0.0

        # Check cycle budget
        remaining_cycles = battery.max_cycles_per_day - cycles_used

        if spread > 3 and soc < cap * battery.max_soc and remaining_cycles > 0:
            # Price low relative to future → charge
            headroom = cap * battery.max_soc - soc
            energy = min(max_energy_per_bucket, headroom)
            soc += energy
            cost = price * energy / efficiency
            total_revenue -= cost
            action = "charge"
            cycles_used += energy / (2 * cap)

        elif spread < -3 and soc > cap * battery.min_soc and remaining_cycles > 0:
            # Price high relative to future → discharge
            available = soc - cap * battery.min_soc
            energy = min(max_energy_per_bucket, available)
            soc -= energy
            rev = price * energy * efficiency
            total_revenue += rev
            action = "discharge"
            cycles_used += energy / (2 * cap)

        # Account for DA position
        if position != 0:
            # Net off against position
            pos_rev = position * price * bucket_size_hours
            total_revenue += pos_rev

        net_rev = 0
        if action == "charge":
            net_rev = round(-price * energy / efficiency, 2)
        elif action == "discharge":
            net_rev = round(price * energy * efficiency, 2)

        schedule.append({
            "bucket": t,
            "action": action,
            "power_mw": round(energy / bucket_size_hours if action == "discharge" else
                              -energy / bucket_size_hours if action == "charge" else 0, 2),
            "soc_pct": round(soc / cap * 100, 1),
            "price_gbp_mwh": round(price, 2),
            "spread_gbp": round(spread, 2),
            "revenue_gbp": net_rev,
        })

        if action != "idle":
            trades.append({
                "bucket": t,
                "side": "buy" if action == "charge" else "sell",
                "volume_mwh": round(energy, 2),
                "price_gbp_mwh": round(price, 2),
            })

    return {
        "status": "ok",
        "strategy": "rolling_intrinsic",
        "battery": {
            "power_mw": battery.power_mw,
            "energy_mwh": battery.energy_mwh,
            "efficiency": battery.round_trip_efficiency,
        },
        "total_revenue_gbp": round(total_revenue, 2),
        "schedule": schedule,
        "trades": trades,
        "num_trades": len(trades),
        "cycles_used": round(cycles_used, 2),
        "final_soc_pct": round(soc / cap * 100, 1),
        "bucket_size_hours": bucket_size_hours,
    }


# ── Coordinated Multi-Market Dispatch ──────────────────────────────────────

def coordinated_dispatch(
    da_prices: list[float],
    id_prices: list[float] | None = None,
    battery: BatterySpec | None = None,
    lambda_da: float = 0.5,
) -> dict:
    """Coordinated multi-market dispatch combining DA + intraday.

    Runs DA MILP first, then overlays rolling intrinsic intraday
    trading on top, weighted by lambda.

    Based on BessBidder's coordinated multi-market approach.

    Args:
        da_prices: Day-ahead prices (hourly, £/MWh)
        id_prices: Intraday prices (quarter-hourly, £/MWh). If None, simulated.
        battery: Battery spec
        lambda_da: Weight for DA vs ID revenue (0.5 = equal)

    Returns:
        Combined dispatch schedule with DA + ID revenue breakdown
    """
    if battery is None:
        battery = BatterySpec()

    # Phase 1: Day-ahead MILP optimization
    da_result = optimize_day_ahead(da_prices, battery)

    if da_result.get("error"):
        return da_result

    # Extract DA positions (MW per hour → expand to quarter-hourly)
    da_positions = []
    for entry in da_result["schedule"]:
        # Each hourly position → 4 quarter-hourly positions
        power = entry["power_mw"]
        da_positions.extend([power] * 4)

    # Phase 2: Intraday rolling intrinsic
    if id_prices is None:
        # Generate intraday prices as DA + noise (spread)
        id_prices = []
        for p in da_prices:
            for q in range(4):  # 4 quarter-hours per hour
                id_prices.append(p + random.gauss(0, 6))

    id_result = rolling_intrinsic(
        id_prices,
        battery,
        bucket_size_hours=0.25,
        existing_positions=da_positions,
    )

    # Phase 3: Combine results
    da_rev = da_result["forecast_revenue_gbp"]
    id_rev = id_result["total_revenue_gbp"]
    combined_rev = lambda_da * da_rev + (1 - lambda_da) * id_rev

    # Build hourly combined schedule
    combined_schedule = []
    for h, da_entry in enumerate(da_result["schedule"]):
        # Aggregate quarter-hourly ID results for this hour
        id_entries = id_result["schedule"][h * 4:(h + 1) * 4]
        id_power = sum(e["power_mw"] for e in id_entries) / 4 if id_entries else 0
        id_rev_hour = sum(e["revenue_gbp"] for e in id_entries)

        combined_schedule.append({
            "hour": h,
            "da_action": da_entry["action"],
            "da_power_mw": da_entry["power_mw"],
            "da_price_gbp": da_entry["price_gbp_mwh"],
            "da_revenue_gbp": da_entry["revenue_gbp"],
            "id_power_mw": round(id_power, 2),
            "id_revenue_gbp": round(id_rev_hour, 2),
            "combined_power_mw": round(
                lambda_da * da_entry["power_mw"] + (1 - lambda_da) * id_power, 2
            ),
            "soc_pct": da_entry["soc_pct"],
        })

    return {
        "status": "optimal",
        "strategy": "coordinated_multi_market",
        "lambda_da": lambda_da,
        "battery": {
            "power_mw": battery.power_mw,
            "energy_mwh": battery.energy_mwh,
            "efficiency": battery.round_trip_efficiency,
        },
        "da_revenue_gbp": da_rev,
        "id_revenue_gbp": id_rev,
        "combined_revenue_gbp": round(combined_rev, 2),
        "improvement_pct": round(
            (combined_rev - da_rev) / max(abs(da_rev), 1) * 100, 1
        ) if da_rev else 0,
        "da_trades": da_result["num_trades"],
        "id_trades": id_result["num_trades"],
        "schedule": combined_schedule,
        "da_cycles": da_result["cycles"],
        "id_cycles": id_result["cycles_used"],
    }


# ── Quick simulation for API ──────────────────────────────────────────────

def run_bidding_simulation(
    power_mw: float = 50.0,
    energy_mwh: float = 100.0,
    strategy: str = "coordinated",
    hours: int = 24,
    efficiency: float = 0.86,
) -> dict:
    """Run a complete bidding simulation with simulated UK prices.

    High-level entry point for the API.
    """
    battery = BatterySpec(
        power_mw=power_mw,
        energy_mwh=energy_mwh,
        round_trip_efficiency=efficiency,
    )

    price_data = simulate_uk_prices(hours)

    if strategy == "day_ahead":
        result = optimize_day_ahead(
            price_data["da_prices_gbp_mwh"],
            battery,
            price_data["realised_prices_gbp_mwh"],
        )
    elif strategy == "rolling_intrinsic":
        # Convert hourly to quarter-hourly
        qh_prices = []
        for p in price_data["realised_prices_gbp_mwh"]:
            for q in range(4):
                qh_prices.append(p + random.gauss(0, 3))
        result = rolling_intrinsic(qh_prices, battery)
    elif strategy == "coordinated":
        result = coordinated_dispatch(
            price_data["da_prices_gbp_mwh"],
            battery=battery,
        )
    else:
        return {"error": f"Unknown strategy: {strategy}. Use: day_ahead, rolling_intrinsic, coordinated"}

    result["prices"] = price_data
    return result
