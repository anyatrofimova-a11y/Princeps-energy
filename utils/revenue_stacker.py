"""
Revenue stacking model — optimises multi-market revenue for energy assets.

Markets modelled:
1. Day-ahead wholesale (N2EX/EPEX) — uses Octopus Agile as proxy
2. Balancing Mechanism — spread on wholesale price
3. FFR (Firm Frequency Response) — frequency regulation service
4. DC (Dynamic Containment) — fast frequency response
5. Capacity Market — annual availability payment
6. Embedded benefits — TNUoS/BSUoS/DUoS avoided charges

Uses real Agile pricing data and capacity market clearing prices.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any

log = logging.getLogger("princeps.revenue_stacker")

# ─── UK Market Constants (real published values) ────────────────────────────

# Capacity Market T-4 2024 clearing price (published by NESO)
CM_T4_CLEARING_GBP_KW_YEAR = 63.0

# FFR and DC rates (published by NESO, GBP/MW/h)
FFR_RATE_LOW = 8.0
FFR_RATE_HIGH = 12.0
DC_RATE_LOW = 12.0
DC_RATE_HIGH = 17.0

# Embedded benefits by DNO zone (TNUoS avoided charges, GBP/kW/year)
EMBEDDED_BENEFITS_BY_ZONE = {
    "UKPN":  12.0,
    "NGED":  10.0,
    "ENWL":  8.0,
    "NPG":   9.0,
    "SPEN":  7.0,
    "SSEN":  6.0,
    "default": 10.0,
}

# BM premium over wholesale (15-25%)
BM_PREMIUM_LOW = 0.15
BM_PREMIUM_HIGH = 0.25

# Technology capacity factors (UK averages)
CAPACITY_FACTORS = {
    "solar": 0.11,
    "wind": 0.27,
    "onshore_wind": 0.27,
    "offshore_wind": 0.40,
    "bess": 0.0,  # BESS doesn't generate — revenue from arbitrage
    "solar+bess": 0.11,  # Solar CF for generation component
}

# BESS parameters
BESS_ROUND_TRIP_EFFICIENCY = 0.85
BESS_ANNUAL_DEGRADATION_PCT = 2.5
BESS_DEFAULT_DURATION_HOURS = 2  # 2-hour duration if not specified

# CAPEX benchmarks (GBP/kW installed)
CAPEX_GBP_KW = {
    "solar": 450,
    "wind": 1100,
    "onshore_wind": 1100,
    "offshore_wind": 2800,
    "bess": 350,  # Per kW of power capacity
    "solar+bess": 650,
}

# OPEX as % of CAPEX per year
OPEX_PCT = {
    "solar": 0.012,
    "wind": 0.025,
    "onshore_wind": 0.025,
    "offshore_wind": 0.035,
    "bess": 0.015,
    "solar+bess": 0.015,
}

# Project lifetime (years)
LIFETIME_YEARS = {
    "solar": 35,
    "wind": 25,
    "onshore_wind": 25,
    "offshore_wind": 25,
    "bess": 15,
    "solar+bess": 30,
}

# Discount rate for LCOE / IRR
DISCOUNT_RATE = 0.08


# ─── DNO Region Lookup ──────────────────────────────────────────────────────

async def _identify_dno_zone(pool, lat: float | None, lon: float | None) -> str:
    """Look up DNO zone from grid_dno_boundaries or grid_substations."""
    if lat is None or lon is None:
        return "default"
    try:
        async with pool.acquire() as conn:
            # Try DNO boundaries first
            row = await conn.fetchrow("""
                SELECT dno FROM grid_dno_boundaries
                WHERE ST_Contains(
                    geom,
                    ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700)
                )
                LIMIT 1
            """, lon, lat)
            if row:
                return row["dno"]

            # Fall back to nearest substation
            row = await conn.fetchrow("""
                SELECT dno FROM grid_substations
                WHERE geom IS NOT NULL
                ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700)
                LIMIT 1
            """, lon, lat)
            if row:
                return row["dno"]
    except Exception as exc:
        log.debug("DNO lookup failed: %s", exc)
    return "default"


# ─── Agile Price Analysis ───────────────────────────────────────────────────

async def _fetch_agile_price_stats(region: str = "C") -> dict:
    """Fetch real Agile prices and compute key stats for revenue modelling."""
    from utils.agile_pricing import fetch_agile_prices, find_cheapest_windows, find_peak_windows

    prices = await fetch_agile_prices(region=region)
    if not prices:
        # Fallback: UK typical wholesale ~£55/MWh = 5.5p/kWh
        return {
            "avg_price_pence": 22.0,
            "min_price_pence": 5.0,
            "max_price_pence": 45.0,
            "spread_pence": 40.0,
            "cheapest_4h_avg_pence": 8.0,
            "peak_4h_avg_pence": 38.0,
            "source": "fallback (Agile API unavailable)",
            "periods": 0,
        }

    all_p = [p["price_pence"] for p in prices]
    cheapest = find_cheapest_windows(prices, window_hours=4)
    peak = find_peak_windows(prices, window_hours=4)

    cheapest_avg = cheapest[0]["avg_price_pence"] if cheapest else min(all_p)
    peak_avg = peak[0]["avg_price_pence"] if peak else max(all_p)

    return {
        "avg_price_pence": round(sum(all_p) / len(all_p), 2),
        "min_price_pence": round(min(all_p), 2),
        "max_price_pence": round(max(all_p), 2),
        "spread_pence": round(max(all_p) - min(all_p), 2),
        "cheapest_4h_avg_pence": round(cheapest_avg, 2),
        "peak_4h_avg_pence": round(peak_avg, 2),
        "source": "Octopus Agile (real prices)",
        "periods": len(prices),
    }


# ─── Revenue Calculations ───────────────────────────────────────────────────

def _wholesale_revenue(capacity_mw: float, cf: float, avg_price_pence: float) -> float:
    """Annual wholesale revenue (GBP) = capacity * CF * 8760h * price."""
    # price_pence is p/kWh; convert to GBP/MWh: * 10
    price_gbp_mwh = avg_price_pence * 10
    annual_mwh = capacity_mw * cf * 8760
    return annual_mwh * price_gbp_mwh


def _bm_revenue(wholesale_gbp: float) -> float:
    """BM revenue = 15-25% premium on wholesale."""
    premium = (BM_PREMIUM_LOW + BM_PREMIUM_HIGH) / 2  # 20% mid-point
    return wholesale_gbp * premium


def _ffr_revenue(capacity_mw: float, technology: str) -> float:
    """FFR revenue — only applicable to BESS and dispatchable assets."""
    if "bess" not in technology and "battery" not in technology:
        return 0.0
    # FFR availability: assume 40% of hours available for FFR
    ffr_rate = (FFR_RATE_LOW + FFR_RATE_HIGH) / 2  # £10/MW/h
    ffr_hours = 8760 * 0.40
    return capacity_mw * ffr_rate * ffr_hours


def _dc_revenue(capacity_mw: float, technology: str) -> float:
    """Dynamic Containment revenue — only for BESS."""
    if "bess" not in technology and "battery" not in technology:
        return 0.0
    # DC availability: assume 35% of hours (competes with FFR and arbitrage)
    dc_rate = (DC_RATE_LOW + DC_RATE_HIGH) / 2  # £14.5/MW/h
    dc_hours = 8760 * 0.35
    return capacity_mw * dc_rate * dc_hours


def _capacity_market_revenue(capacity_mw: float, technology: str) -> float:
    """Capacity Market revenue = clearing price * derated capacity."""
    # De-rating factors (NESO published)
    derate = {
        "solar": 0.0,  # Solar gets 0% de-rating in UK CM
        "wind": 0.08,
        "onshore_wind": 0.08,
        "offshore_wind": 0.12,
        "bess": 0.90,  # 2h BESS gets ~90% de-rating
        "solar+bess": 0.50,  # Blended
    }
    factor = derate.get(technology, 0.50)
    capacity_kw = capacity_mw * 1000
    return capacity_kw * factor * CM_T4_CLEARING_GBP_KW_YEAR


def _embedded_benefits_revenue(capacity_mw: float, dno_zone: str) -> float:
    """Embedded benefits (TNUoS/BSUoS/DUoS avoided charges)."""
    rate = EMBEDDED_BENEFITS_BY_ZONE.get(dno_zone, EMBEDDED_BENEFITS_BY_ZONE["default"])
    capacity_kw = capacity_mw * 1000
    return capacity_kw * rate


def _bess_arbitrage_revenue(
    bess_mw: float,
    bess_mwh: float,
    cheapest_4h_pence: float,
    peak_4h_pence: float,
) -> dict:
    """BESS daily charge/discharge arbitrage revenue."""
    spread_pence = peak_4h_pence - cheapest_4h_pence
    spread_gbp_mwh = spread_pence * 10  # p/kWh -> GBP/MWh

    # Daily cycles limited by energy capacity and duration
    duration_hours = bess_mwh / bess_mw if bess_mw > 0 else 2
    # Typically 1-2 cycles per day; longer duration = fewer but deeper cycles
    daily_cycles = min(2.0, 8.0 / max(duration_hours, 1))

    annual_arbitrage = (
        spread_gbp_mwh * bess_mwh * daily_cycles * 365 * BESS_ROUND_TRIP_EFFICIENCY
    )

    return {
        "annual_arbitrage_gbp": round(annual_arbitrage),
        "daily_cycles": round(daily_cycles, 1),
        "spread_avg_gbp_mwh": round(spread_gbp_mwh, 1),
        "degradation_yr_pct": BESS_ANNUAL_DEGRADATION_PCT,
    }


# ─── Monte Carlo Simulation ─────────────────────────────────────────────────

def _monte_carlo(base_revenue: float, n_sims: int = 5000) -> dict:
    """Run Monte Carlo on total revenue with realistic uncertainty bands."""
    results = []
    for _ in range(n_sims):
        # Wholesale: +/- 25% volatility
        wholesale_factor = random.gauss(1.0, 0.12)
        # BM: +/- 30%
        bm_factor = random.gauss(1.0, 0.15)
        # Ancillary: +/- 20%
        ancillary_factor = random.gauss(1.0, 0.10)
        # Capacity Market: stable, +/- 5%
        cm_factor = random.gauss(1.0, 0.03)

        blended = (
            wholesale_factor * 0.45 +
            bm_factor * 0.10 +
            ancillary_factor * 0.30 +
            cm_factor * 0.15
        )
        results.append(base_revenue * blended)

    results.sort()
    return {
        "p10": round(results[int(n_sims * 0.10)]),
        "p50": round(results[int(n_sims * 0.50)]),
        "p90": round(results[int(n_sims * 0.90)]),
        "mean": round(sum(results) / n_sims),
        "simulations": n_sims,
    }


# ─── Financial Metrics ──────────────────────────────────────────────────────

def _compute_lcoe(
    capacity_mw: float,
    technology: str,
    annual_mwh: float,
) -> float:
    """Levelised Cost of Energy (GBP/MWh)."""
    capex_total = capacity_mw * 1000 * CAPEX_GBP_KW.get(technology, 600)
    opex_annual = capex_total * OPEX_PCT.get(technology, 0.02)
    lifetime = LIFETIME_YEARS.get(technology, 25)

    # Sum of discounted generation
    disc_gen = sum(annual_mwh / (1 + DISCOUNT_RATE) ** y for y in range(1, lifetime + 1))
    # Sum of discounted costs
    disc_cost = capex_total + sum(
        opex_annual / (1 + DISCOUNT_RATE) ** y for y in range(1, lifetime + 1)
    )
    return round(disc_cost / max(disc_gen, 1), 1)


def _compute_irr(
    capacity_mw: float,
    technology: str,
    annual_revenue: float,
) -> float:
    """Approximate IRR using Newton's method."""
    capex = capacity_mw * 1000 * CAPEX_GBP_KW.get(technology, 600)
    opex = capex * OPEX_PCT.get(technology, 0.02)
    lifetime = LIFETIME_YEARS.get(technology, 25)
    net_annual = annual_revenue - opex

    # Newton-Raphson for IRR
    r = 0.10  # initial guess
    for _ in range(100):
        npv = -capex + sum(net_annual / (1 + r) ** t for t in range(1, lifetime + 1))
        dnpv = sum(-t * net_annual / (1 + r) ** (t + 1) for t in range(1, lifetime + 1))
        if abs(dnpv) < 1e-10:
            break
        r_new = r - npv / dnpv
        if abs(r_new - r) < 1e-6:
            r = r_new
            break
        r = r_new
    return round(max(0, min(r * 100, 50)), 1)


def _compute_payback(
    capacity_mw: float,
    technology: str,
    annual_revenue: float,
) -> float:
    """Simple payback period in years."""
    capex = capacity_mw * 1000 * CAPEX_GBP_KW.get(technology, 600)
    opex = capex * OPEX_PCT.get(technology, 0.02)
    net_annual = annual_revenue - opex
    if net_annual <= 0:
        return 99.0
    return round(capex / net_annual, 1)


# ─── Main Entry Point ───────────────────────────────────────────────────────

async def stack_revenue(
    capacity_mw: float,
    technology: str = "solar+bess",
    bess_mwh: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    pool=None,
) -> dict[str, Any]:
    """
    Multi-market revenue optimisation for energy assets.

    Args:
        capacity_mw: Total installed capacity in MW.
        technology: One of solar, wind, onshore_wind, offshore_wind, bess, solar+bess.
        bess_mwh: BESS energy capacity in MWh (auto-calculated if None).
        lat/lon: Site location for DNO zone lookup.
        pool: asyncpg connection pool.

    Returns:
        Dict with revenue streams, Monte Carlo P10/P50/P90, LCOE, IRR, payback.
    """
    tech = technology.lower().replace(" ", "")
    cf = CAPACITY_FACTORS.get(tech, 0.11)

    # Determine BESS component
    has_bess = "bess" in tech or "battery" in tech
    if has_bess and bess_mwh is None:
        bess_mwh = capacity_mw * BESS_DEFAULT_DURATION_HOURS
    bess_mw = capacity_mw if has_bess else 0
    bess_mwh = bess_mwh or 0

    # DNO zone for embedded benefits
    dno_zone = "default"
    if pool and lat is not None and lon is not None:
        dno_zone = await _identify_dno_zone(pool, lat, lon)

    # Map Agile region from lat/lon (simplified UK mapping)
    agile_region = "C"  # Default London
    if lat is not None:
        if lat > 55.5:
            agile_region = "P"   # North Scotland
        elif lat > 54.5:
            agile_region = "N"   # South Scotland
        elif lat > 53.5:
            agile_region = "M"   # Yorkshire
        elif lat > 52.5:
            agile_region = "B"   # East Midlands
        elif lat > 51.5:
            agile_region = "A"   # East England
        else:
            agile_region = "H"   # Southern England

    # Fetch real Agile prices
    price_stats = await _fetch_agile_price_stats(region=agile_region)

    # ── Revenue Streams ─────────────────────────────────────────────────

    # 1. Wholesale (solar/wind generation revenue)
    wholesale_gbp = _wholesale_revenue(capacity_mw, cf, price_stats["avg_price_pence"])

    # 2. Balancing Mechanism
    bm_gbp = _bm_revenue(wholesale_gbp)

    # 3. FFR
    ffr_gbp = _ffr_revenue(bess_mw, tech)

    # 4. Dynamic Containment
    dc_gbp = _dc_revenue(bess_mw, tech)

    # 5. Capacity Market
    cm_gbp = _capacity_market_revenue(capacity_mw, tech)

    # 6. Embedded Benefits
    eb_gbp = _embedded_benefits_revenue(capacity_mw, dno_zone)

    # 7. BESS Arbitrage (replaces some wholesale for hybrid)
    bess_metrics = None
    bess_arb_gbp = 0
    if has_bess and bess_mwh > 0:
        bess_result = _bess_arbitrage_revenue(
            bess_mw, bess_mwh,
            price_stats["cheapest_4h_avg_pence"],
            price_stats["peak_4h_avg_pence"],
        )
        bess_arb_gbp = bess_result["annual_arbitrage_gbp"]
        bess_metrics = {
            "daily_cycles": bess_result["daily_cycles"],
            "degradation_yr_pct": bess_result["degradation_yr_pct"],
            "spread_avg_gbp_mwh": bess_result["spread_avg_gbp_mwh"],
            "bess_mw": bess_mw,
            "bess_mwh": bess_mwh,
            "round_trip_efficiency": BESS_ROUND_TRIP_EFFICIENCY,
        }
        # For hybrid, BESS arbitrage is additional to solar wholesale
        wholesale_gbp += bess_arb_gbp

    # ── Totals ──────────────────────────────────────────────────────────

    total = wholesale_gbp + bm_gbp + ffr_gbp + dc_gbp + cm_gbp + eb_gbp

    def _pct(v):
        return round(v / max(total, 1) * 100) if total > 0 else 0

    streams = {
        "wholesale": {
            "gbp": round(wholesale_gbp),
            "pct": _pct(wholesale_gbp),
            "source": price_stats["source"],
            "avg_price_gbp_mwh": round(price_stats["avg_price_pence"] * 10, 1),
        },
        "balancing_mechanism": {
            "gbp": round(bm_gbp),
            "pct": _pct(bm_gbp),
            "source": "BM premium (20% on wholesale)",
        },
        "ffr": {
            "gbp": round(ffr_gbp),
            "pct": _pct(ffr_gbp),
            "source": f"NESO FFR {FFR_RATE_LOW}-{FFR_RATE_HIGH} GBP/MW/h",
        },
        "dc": {
            "gbp": round(dc_gbp),
            "pct": _pct(dc_gbp),
            "source": f"NESO DC {DC_RATE_LOW}-{DC_RATE_HIGH} GBP/MW/h",
        },
        "capacity_market": {
            "gbp": round(cm_gbp),
            "pct": _pct(cm_gbp),
            "source": f"NESO T-4 2024 clearing {CM_T4_CLEARING_GBP_KW_YEAR} GBP/kW/yr",
        },
        "embedded_benefits": {
            "gbp": round(eb_gbp),
            "pct": _pct(eb_gbp),
            "source": f"TNUoS/BSUoS/DUoS — {dno_zone} zone",
        },
    }

    # ── Monte Carlo ─────────────────────────────────────────────────────

    mc = _monte_carlo(total)

    # ── Financial Metrics ───────────────────────────────────────────────

    annual_mwh = capacity_mw * cf * 8760 if cf > 0 else bess_mwh * 365
    lcoe = _compute_lcoe(capacity_mw, tech, max(annual_mwh, 1))
    irr = _compute_irr(capacity_mw, tech, total)
    payback = _compute_payback(capacity_mw, tech, total)

    # Optimal strategy
    if has_bess and cf > 0:
        strategy = "hybrid"
        strategy_detail = "Solar generation + BESS arbitrage + ancillary stacking"
    elif has_bess:
        strategy = "ancillary_first"
        strategy_detail = "DC/FFR primary, arbitrage secondary, CM availability"
    elif cf >= 0.25:
        strategy = "wholesale_dominant"
        strategy_detail = "Wholesale + BM primary, CM availability for wind"
    else:
        strategy = "wholesale_plus_cm"
        strategy_detail = "Wholesale generation + embedded benefits"

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "dno_zone": dno_zone,
        "total_annual_revenue_gbp": round(total),
        "revenue_streams": streams,
        "monte_carlo": mc,
        "lcoe_gbp_mwh": lcoe,
        "irr_pct": irr,
        "payback_years": payback,
        "optimal_strategy": strategy,
        "optimal_strategy_detail": strategy_detail,
        "bess_metrics": bess_metrics,
        "price_data": {
            "agile_region": agile_region,
            "avg_wholesale_gbp_mwh": round(price_stats["avg_price_pence"] * 10, 1),
            "spread_gbp_mwh": round(price_stats["spread_pence"] * 10, 1),
            "cheapest_4h_gbp_mwh": round(price_stats["cheapest_4h_avg_pence"] * 10, 1),
            "peak_4h_gbp_mwh": round(price_stats["peak_4h_avg_pence"] * 10, 1),
            "source": price_stats["source"],
        },
        "assumptions": {
            "capacity_factor": cf,
            "discount_rate": DISCOUNT_RATE,
            "capex_gbp_kw": CAPEX_GBP_KW.get(tech, 600),
            "opex_pct_capex": OPEX_PCT.get(tech, 0.02),
            "lifetime_years": LIFETIME_YEARS.get(tech, 25),
            "cm_clearing_gbp_kw_yr": CM_T4_CLEARING_GBP_KW_YEAR,
        },
    }
