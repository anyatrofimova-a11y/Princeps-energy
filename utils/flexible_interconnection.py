"""Flexible Interconnection & Dynamic Operating Envelopes."""

from __future__ import annotations
import time
import logging
from typing import Any

log = logging.getLogger(__name__)

# UK statutory voltage limits
VOLTAGE_LIMITS = {
    11: (0.94, 1.06), 33: (0.94, 1.06), 66: (0.95, 1.05),
    132: (0.95, 1.05), 275: (0.95, 1.05), 400: (0.95, 1.05),
}


async def compute_operating_envelope(
    conn, lat: float, lon: float, capacity_mw: float,
    load_profile_24h: list[float] = None,
) -> dict[str, Any]:
    """Compute hourly operating envelope at nearest substation."""
    t0 = time.time()
    load_profile_24h = load_profile_24h or [0.6 + 0.3 * abs(h - 12) / 12 for h in range(24)]  # Typical UK demand shape

    # Find nearest substations
    rows = await conn.fetch("""
        SELECT id, name, voltage_kv, demand_mw, generation_mw,
               demand_headroom_mw, gen_headroom_mw, transformer_rating_mva,
               ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS distance_km
        FROM grid_substations
        WHERE ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), 50000)
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 3
    """, lon, lat)

    if not rows:
        return {"error": "No substations found within 50km", "envelope_mw": [0] * 24}

    sub = dict(rows[0])
    rating = float(sub["transformer_rating_mva"] or 100)
    demand_mw = float(sub["demand_mw"] or rating * 0.6)
    gen_mw = float(sub["generation_mw"] or 0)
    voltage_kv = float(sub["voltage_kv"] or 33)
    v_min, v_max = VOLTAGE_LIMITS.get(int(voltage_kv), (0.94, 1.06))

    # Compute hourly envelope
    envelope_mw = []
    for h in range(24):
        demand_factor = load_profile_24h[h]
        hourly_demand = demand_mw * demand_factor
        thermal_headroom = max(0, rating - hourly_demand - gen_mw)

        # Voltage constraint: simplified — large generation can push voltage up
        voltage_headroom = rating * (v_max - 1.0) / 0.1  # MW that raises voltage by 0.1 pu

        available = min(thermal_headroom, voltage_headroom)
        envelope_mw.append(round(max(0, available), 2))

    firm_capacity = min(envelope_mw)
    flexible_capacity = max(envelope_mw)
    curtailment_pct = 0
    if capacity_mw > 0:
        curtailed_hours = sum(1 for e in envelope_mw if e < capacity_mw)
        curtailment_energy = sum(max(0, capacity_mw - e) for e in envelope_mw)
        total_energy = capacity_mw * 24
        curtailment_pct = round(curtailment_energy / total_energy * 100, 1) if total_energy > 0 else 0

    return {
        "substation": sub["name"],
        "distance_km": round(sub["distance_km"], 1),
        "voltage_kv": voltage_kv,
        "transformer_rating_mva": rating,
        "envelope_mw": envelope_mw,
        "firm_capacity_mw": round(firm_capacity, 1),
        "flexible_capacity_mw": round(flexible_capacity, 1),
        "curtailment_pct": curtailment_pct,
        "elapsed_s": round(time.time() - t0, 3),
    }


def estimate_curtailment(
    envelope_mw: list[float],
    generation_profile_24h: list[float],
    capacity_mw: float,
    electricity_price: float = 50,
) -> dict[str, Any]:
    """Estimate annual curtailment from operating envelope."""
    curtailed_mwh = 0
    curtailed_hours = 0

    for h in range(24):
        gen = generation_profile_24h[h] * capacity_mw
        available = envelope_mw[h]
        if gen > available:
            curtailed_mwh += gen - available
            curtailed_hours += 1

    # Scale to annual (multiply by 365)
    annual_curtailed_mwh = curtailed_mwh * 365
    annual_gen_mwh = sum(g * capacity_mw for g in generation_profile_24h) * 365
    curtailment_pct = round(annual_curtailed_mwh / annual_gen_mwh * 100, 1) if annual_gen_mwh > 0 else 0
    revenue_loss = round(annual_curtailed_mwh * electricity_price)

    return {
        "annual_curtailed_mwh": round(annual_curtailed_mwh, 1),
        "curtailment_pct": curtailment_pct,
        "curtailed_hours_per_day": curtailed_hours,
        "annual_curtailed_hours": curtailed_hours * 365,
        "revenue_loss_gbp": revenue_loss,
        "annual_generation_mwh": round(annual_gen_mwh, 1),
    }


async def compare_connection_strategies(
    conn, lat: float, lon: float, capacity_mw: float,
    queue_wait_years: float = 5,
    electricity_price: float = 50,
    discount_rate: float = 0.08,
) -> dict[str, Any]:
    """Compare firm vs flexible connection strategies."""
    envelope = await compute_operating_envelope(conn, lat, lon, capacity_mw)
    solar_cf = [0, 0, 0, 0, 0, 0.02, 0.05, 0.08, 0.12, 0.15, 0.17, 0.18, 0.18, 0.17, 0.15, 0.12, 0.08, 0.05, 0.02, 0, 0, 0, 0, 0]

    curtailment = estimate_curtailment(envelope["envelope_mw"], solar_cf, capacity_mw, electricity_price)

    # Strategy A: Wait for firm connection
    annual_revenue_firm = sum(cf * capacity_mw for cf in solar_cf) * 365 * electricity_price
    npv_firm = 0
    for y in range(1, 26):
        if y <= queue_wait_years:
            npv_firm += 0  # No revenue while waiting
        else:
            npv_firm += annual_revenue_firm / (1 + discount_rate) ** y

    # Strategy B: Connect now with curtailment
    annual_revenue_flex = annual_revenue_firm - curtailment["revenue_loss_gbp"]
    npv_flex = 0
    for y in range(1, 26):
        npv_flex += annual_revenue_flex / (1 + discount_rate) ** y

    advantage = npv_flex - npv_firm

    return {
        "strategy_a_firm": {
            "description": f"Wait {queue_wait_years} years for firm {capacity_mw}MW connection",
            "queue_years": queue_wait_years,
            "annual_revenue_gbp": round(annual_revenue_firm),
            "npv_25yr_gbp": round(npv_firm),
            "first_revenue_year": int(queue_wait_years) + 1,
        },
        "strategy_b_flexible": {
            "description": f"Connect now at flexible {envelope['flexible_capacity_mw']}MW",
            "curtailment_pct": curtailment["curtailment_pct"],
            "annual_revenue_gbp": round(annual_revenue_flex),
            "annual_curtailment_loss_gbp": curtailment["revenue_loss_gbp"],
            "npv_25yr_gbp": round(npv_flex),
            "first_revenue_year": 1,
        },
        "recommendation": "flexible" if advantage > 0 else "firm",
        "npv_advantage_gbp": round(advantage),
        "breakeven_curtailment_pct": round((1 - npv_firm / max(npv_flex, 1)) * 100, 1) if npv_flex > 0 else 0,
    }
