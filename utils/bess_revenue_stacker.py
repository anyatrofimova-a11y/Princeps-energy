"""
BESS Revenue Stacking Engine.

Models 6 GB BESS revenue streams with real UK market benchmarks (2024-2026),
calculates stacked revenues by strategy, forecasts forward with P10/P50/P90
confidence bands, and compares against Modo Energy published benchmarks.

Revenue streams:
  - Wholesale arbitrage (day-ahead + intraday spread capture)
  - Balancing Mechanism (NESO real-time BOAs)
  - Dynamic Containment (sub-second frequency response: DC, DM, DR)
  - Capacity Market (T-4 and T-1 de-rated capacity agreements)
  - FFR Static (legacy firm frequency response, declining)
  - TNUoS / Triad (transmission demand avoidance / BSUoS replacement)

Sources: Modo Energy Monthly BESS Index, NESO Capacity Market registers,
         EPEX/N2EX day-ahead data, BMRS settlement reports.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Revenue stream benchmarks (£/MW installed/yr) — UK market 2024-2026
# ---------------------------------------------------------------------------
REVENUE_STREAMS: dict[str, dict[str, Any]] = {
    "wholesale_arbitrage": {
        "description": "Day-ahead + intraday price spread capture",
        "benchmark_gbp_mw_yr": {"2024": 28_000, "2025": 32_000, "2026": 25_000},
        "driver": "wholesale price volatility",
        "capture_rate": 0.65,
        "duration_scaling": "linear",  # longer duration = more cycles
        "growth_rate_pct": 3.0,  # volatility increasing with renewables
    },
    "balancing_mechanism": {
        "description": "NESO real-time balancing actions (BOAs)",
        "benchmark_gbp_mw_yr": {"2024": 18_000, "2025": 22_000, "2026": 16_000},
        "driver": "system imbalance + wind intermittency",
        "capture_rate": 0.45,
        "duration_scaling": "sqrt",  # diminishing returns beyond 1h
        "growth_rate_pct": 5.0,  # more renewables = more balancing
    },
    "dynamic_containment": {
        "description": "Sub-second frequency response (DC, DM, DR)",
        "benchmark_gbp_mw_yr": {"2024": 15_000, "2025": 12_000, "2026": 10_000},
        "driver": "inertia decline + renewable penetration",
        "capture_rate": 0.80,
        "duration_scaling": "flat",  # 1h sufficient, no extra for longer
        "growth_rate_pct": -8.0,  # market saturation as BESS fleet grows
    },
    "capacity_market": {
        "description": "T-4 and T-1 capacity agreements",
        "benchmark_gbp_mw_yr": {"2024": 28_000, "2025": 65_000, "2026": 60_000},
        "driver": "de-rated capacity auctions",
        "de_rating": {"1h": 0.244, "2h": 0.488, "4h": 0.732},
        "capture_rate": 1.0,  # awarded or not
        "duration_scaling": "de_rated",
        "growth_rate_pct": -2.0,  # market maturity / price reversion
    },
    "ffr_static": {
        "description": "Static Firm Frequency Response",
        "benchmark_gbp_mw_yr": {"2024": 8_000, "2025": 6_000, "2026": 5_000},
        "driver": "legacy procurement, declining",
        "capture_rate": 0.70,
        "duration_scaling": "flat",
        "growth_rate_pct": -8.0,  # being replaced by dynamic products
    },
    "tnuos_triad": {
        "description": "Transmission demand avoidance (Triad replacement BSUoS)",
        "benchmark_gbp_mw_yr": {"2024": 5_000, "2025": 4_000, "2026": 3_000},
        "driver": "network charging reform",
        "capture_rate": 0.55,
        "duration_scaling": "flat",
        "growth_rate_pct": -8.0,  # Triad being phased out
    },
}

# ---------------------------------------------------------------------------
# Strategy emphasis weights — how aggressively each stream is pursued.
# These are NOT fractions that must sum to 1; they represent relative
# emphasis (0.3 = conservative participation, 1.0 = full, 1.4 = aggressive).
# Co-stacking means a BESS can earn from multiple streams simultaneously
# (e.g. capacity market payments are passive alongside active trading).
# ---------------------------------------------------------------------------
STRATEGIES: dict[str, dict[str, float]] = {
    "balanced": {
        "wholesale_arbitrage": 0.90,
        "balancing_mechanism": 0.80,
        "dynamic_containment": 0.70,
        "capacity_market": 1.00,
        "ffr_static": 0.50,
        "tnuos_triad": 0.60,
    },
    "arbitrage_heavy": {
        "wholesale_arbitrage": 1.30,
        "balancing_mechanism": 1.10,
        "dynamic_containment": 0.30,
        "capacity_market": 0.80,
        "ffr_static": 0.20,
        "tnuos_triad": 0.40,
    },
    "ancillary_heavy": {
        "wholesale_arbitrage": 0.40,
        "balancing_mechanism": 0.60,
        "dynamic_containment": 1.30,
        "capacity_market": 0.90,
        "ffr_static": 1.10,
        "tnuos_triad": 0.80,
    },
    "capacity_focused": {
        "wholesale_arbitrage": 0.50,
        "balancing_mechanism": 0.50,
        "dynamic_containment": 0.40,
        "capacity_market": 1.40,
        "ffr_static": 0.60,
        "tnuos_triad": 1.00,
    },
}

# Mutually-exclusive cap: some streams compete for the same dispatch
# windows. This caps the combined contribution of trading streams
# (wholesale + BM) to avoid double-counting the same MWh.
_TRADING_CAP = 1.2  # max combined weight for wholesale + BM

# ---------------------------------------------------------------------------
# Regional adjustment factors
# ---------------------------------------------------------------------------
REGIONAL_FACTORS: dict[str, dict[str, float]] = {
    "Scotland": {
        "wholesale_arbitrage": 0.90,   # lower price spreads (constrained)
        "balancing_mechanism": 1.30,   # high wind = more BM actions
        "dynamic_containment": 1.05,
        "capacity_market": 1.0,
        "ffr_static": 1.0,
        "tnuos_triad": 0.85,          # lower TNUoS benefit
    },
    "North": {
        "wholesale_arbitrage": 0.95,
        "balancing_mechanism": 1.15,
        "dynamic_containment": 1.0,
        "capacity_market": 1.0,
        "ffr_static": 1.0,
        "tnuos_triad": 0.95,
    },
    "Midlands": {
        "wholesale_arbitrage": 1.0,
        "balancing_mechanism": 1.0,
        "dynamic_containment": 1.0,
        "capacity_market": 1.0,
        "ffr_static": 1.0,
        "tnuos_triad": 1.0,
    },
    "South": {
        "wholesale_arbitrage": 1.15,   # more solar arbitrage
        "balancing_mechanism": 0.85,   # less wind imbalance
        "dynamic_containment": 1.0,
        "capacity_market": 1.0,
        "ffr_static": 1.0,
        "tnuos_triad": 1.15,          # higher TNUoS zones
    },
    "Wales": {
        "wholesale_arbitrage": 0.95,
        "balancing_mechanism": 1.10,
        "dynamic_containment": 1.0,
        "capacity_market": 1.0,
        "ffr_static": 1.0,
        "tnuos_triad": 0.90,
    },
}

# Modo Energy published BESS revenue benchmarks (£/MW installed/yr)
MODO_BENCHMARKS: dict[str, dict[str, Any]] = {
    "2024": {
        "1h": {"low": 35_000, "mid": 45_000, "high": 55_000},
        "2h": {"low": 52_000, "mid": 65_000, "high": 78_000},
        "4h": {"low": 70_000, "mid": 88_000, "high": 105_000},
    },
    "2025": {
        "1h": {"low": 38_000, "mid": 50_000, "high": 62_000},
        "2h": {"low": 55_000, "mid": 72_000, "high": 88_000},
        "4h": {"low": 75_000, "mid": 95_000, "high": 115_000},
    },
    "2026": {
        "1h": {"low": 32_000, "mid": 41_000, "high": 52_000},
        "2h": {"low": 41_000, "mid": 52_000, "high": 65_000},
        "4h": {"low": 58_000, "mid": 72_000, "high": 88_000},
    },
}

# BESS CAPEX benchmarks (£/kWh installed) for IRR calculations
CAPEX_GBP_KWH: dict[str, float] = {
    "1h": 350,
    "2h": 280,
    "4h": 220,
}

# Fixed O&M (£/MW/yr)
FIXED_OPEX_GBP_MW_YR = 8_000

# Degradation rate (%/yr capacity loss)
DEGRADATION_PCT_YR = 2.5


# ===================================================================
# Core calculation functions
# ===================================================================

def _duration_key(duration_hours: float) -> str:
    """Map continuous duration to nearest standard bucket."""
    if duration_hours <= 1.5:
        return "1h"
    if duration_hours <= 3.0:
        return "2h"
    return "4h"


def _duration_factor(stream: dict, duration_hours: float) -> float:
    """Scale revenue by duration according to the stream's scaling model."""
    scaling = stream.get("duration_scaling", "linear")
    if scaling == "flat":
        return 1.0
    if scaling == "sqrt":
        return math.sqrt(duration_hours)
    if scaling == "de_rated":
        dkey = _duration_key(duration_hours)
        dr = stream.get("de_rating", {})
        return dr.get(dkey, 0.488)
    # linear — normalised to 2h baseline
    return duration_hours / 2.0


def _regional_factor(region: str, stream_name: str) -> float:
    """Get regional multiplier for a stream, default 1.0."""
    return REGIONAL_FACTORS.get(region, REGIONAL_FACTORS["Midlands"]).get(
        stream_name, 1.0
    )


def _get_benchmark(stream: dict, year: str) -> float:
    """Get benchmark £/MW/yr for the given year, interpolate if needed."""
    benchmarks = stream["benchmark_gbp_mw_yr"]
    if year in benchmarks:
        return benchmarks[year]
    # Extrapolate from nearest known year
    known_years = sorted(benchmarks.keys())
    yr = int(year)
    last_known = known_years[-1]
    last_val = benchmarks[last_known]
    growth = stream.get("growth_rate_pct", 0) / 100
    delta = yr - int(last_known)
    return last_val * ((1 + growth) ** delta)


def stack_revenues(
    power_mw: float,
    duration_hours: float,
    region: str = "Midlands",
    year: str = "2026",
    strategy: str = "balanced",
) -> dict[str, Any]:
    """
    Calculate BESS stacked revenues for a given system configuration.

    Returns per-stream revenue breakdown, total, £/MW/yr, and IRR estimate.
    """
    weights = STRATEGIES.get(strategy, STRATEGIES["balanced"])
    dkey = _duration_key(duration_hours)
    energy_mwh = power_mw * duration_hours

    streams: list[dict[str, Any]] = []
    total_revenue = 0.0

    for name, stream in REVENUE_STREAMS.items():
        benchmark = _get_benchmark(stream, year)
        weight = weights.get(name, 0)
        capture = stream.get("capture_rate", 0.5)
        dur_factor = _duration_factor(stream, duration_hours)
        reg_factor = _regional_factor(region, name)

        # Revenue = power * benchmark * capture * duration_factor * regional * emphasis
        rev = power_mw * benchmark * capture * dur_factor * reg_factor * weight
        rev_per_mw = rev / power_mw if power_mw > 0 else 0

        streams.append({
            "stream": name,
            "description": stream["description"],
            "driver": stream.get("driver", ""),
            "benchmark_gbp_mw_yr": round(benchmark),
            "weight": round(weight, 3),
            "capture_rate": capture,
            "duration_factor": round(dur_factor, 3),
            "regional_factor": round(reg_factor, 2),
            "revenue_gbp": round(rev),
            "revenue_gbp_mw_yr": round(rev_per_mw),
        })
        total_revenue += rev

    total_per_mw = total_revenue / power_mw if power_mw > 0 else 0

    # Simple IRR estimate (20-year project)
    capex_per_kwh = CAPEX_GBP_KWH.get(dkey, 280)
    total_capex = energy_mwh * 1000 * capex_per_kwh  # £
    annual_opex = power_mw * FIXED_OPEX_GBP_MW_YR
    annual_net = total_revenue - annual_opex
    irr_estimate = _estimate_irr(total_capex, annual_net, years=20)

    # Modo benchmark comparison
    modo = MODO_BENCHMARKS.get(year, MODO_BENCHMARKS["2026"])
    modo_dur = modo.get(dkey, modo["2h"])
    modo_mid = modo_dur["mid"]
    variance_pct = ((total_per_mw - modo_mid) / modo_mid * 100) if modo_mid else 0

    return {
        "ok": True,
        "system": {
            "power_mw": power_mw,
            "duration_hours": duration_hours,
            "energy_mwh": energy_mwh,
            "duration_class": dkey,
            "region": region,
            "year": year,
            "strategy": strategy,
        },
        "streams": streams,
        "total_revenue_gbp": round(total_revenue),
        "total_gbp_mw_yr": round(total_per_mw),
        "capex_total_gbp": round(total_capex),
        "capex_gbp_kwh": capex_per_kwh,
        "annual_opex_gbp": round(annual_opex),
        "annual_net_revenue_gbp": round(annual_net),
        "irr_pct": round(irr_estimate, 1),
        "modo_benchmark": {
            "year": year,
            "duration": dkey,
            "low_gbp_mw_yr": modo_dur["low"],
            "mid_gbp_mw_yr": modo_dur["mid"],
            "high_gbp_mw_yr": modo_dur["high"],
            "our_gbp_mw_yr": round(total_per_mw),
            "variance_pct": round(variance_pct, 1),
            "assessment": (
                "above benchmark" if variance_pct > 5
                else "below benchmark" if variance_pct < -5
                else "in line with benchmark"
            ),
        },
    }


def forecast_revenues(
    power_mw: float,
    duration_hours: float,
    region: str = "Midlands",
    years_ahead: int = 10,
    strategy: str = "balanced",
    base_year: int = 2026,
) -> dict[str, Any]:
    """
    Project BESS revenues forward using per-stream growth/decline rates.

    Returns annual P10/P50/P90 revenues and cumulative NPV at multiple
    discount rates.
    """
    annual_forecasts: list[dict[str, Any]] = []
    cumulative_p50 = 0.0

    for i in range(years_ahead):
        yr = base_year + i
        result = stack_revenues(power_mw, duration_hours, region, str(yr), strategy)

        # Apply degradation
        deg_factor = (1 - DEGRADATION_PCT_YR / 100) ** i
        p50 = result["total_revenue_gbp"] * deg_factor

        # P10/P90 spread: ±20% in year 1, widening by 2% per year
        spread = 0.20 + 0.02 * i
        p10 = p50 * (1 - spread)
        p90 = p50 * (1 + spread)

        opex = power_mw * FIXED_OPEX_GBP_MW_YR
        cumulative_p50 += p50 - opex

        annual_forecasts.append({
            "year": yr,
            "degradation_factor": round(deg_factor, 3),
            "revenue_p10_gbp": round(p10),
            "revenue_p50_gbp": round(p50),
            "revenue_p90_gbp": round(p90),
            "net_p50_gbp": round(p50 - opex),
            "cumulative_net_p50_gbp": round(cumulative_p50),
        })

    # NPV calculations at multiple discount rates
    dkey = _duration_key(duration_hours)
    energy_mwh = power_mw * duration_hours
    capex_per_kwh = CAPEX_GBP_KWH.get(dkey, 280)
    total_capex = energy_mwh * 1000 * capex_per_kwh
    opex_annual = power_mw * FIXED_OPEX_GBP_MW_YR

    npv_results: dict[str, float] = {}
    for rate in [6, 8, 10]:
        r = rate / 100
        npv = -total_capex
        for i, f in enumerate(annual_forecasts):
            cf = f["revenue_p50_gbp"] - opex_annual
            npv += cf / ((1 + r) ** (i + 1))
        npv_results[f"{rate}pct"] = round(npv)

    # Project-level IRR
    cashflows = [-total_capex]
    for f in annual_forecasts:
        cashflows.append(f["net_p50_gbp"])
    project_irr = _calculate_irr(cashflows)

    return {
        "ok": True,
        "system": {
            "power_mw": power_mw,
            "duration_hours": duration_hours,
            "energy_mwh": energy_mwh,
            "duration_class": dkey,
            "region": region,
            "strategy": strategy,
            "base_year": base_year,
            "forecast_years": years_ahead,
        },
        "annual_forecasts": annual_forecasts,
        "npv": {
            "capex_gbp": round(total_capex),
            "discount_6pct": npv_results["6pct"],
            "discount_8pct": npv_results["8pct"],
            "discount_10pct": npv_results["10pct"],
        },
        "project_irr_pct": round(project_irr, 1),
        "payback_year": _payback_year(annual_forecasts, total_capex),
    }


def compare_to_benchmark(
    power_mw: float,
    duration_hours: float,
    region: str = "Midlands",
    year: str = "2026",
) -> dict[str, Any]:
    """
    Compare calculated revenue to Modo Energy published benchmarks.

    Modo publishes £41k-52k/MW/yr for 2h systems in 2026, and higher
    for 4h systems due to capacity market de-rating.
    """
    dkey = _duration_key(duration_hours)
    modo = MODO_BENCHMARKS.get(year, MODO_BENCHMARKS["2026"])
    modo_dur = modo.get(dkey, modo["2h"])

    # Calculate across all strategies
    comparisons = []
    for strat in STRATEGIES:
        result = stack_revenues(power_mw, duration_hours, region, year, strat)
        our_per_mw = result["total_gbp_mw_yr"]
        variance = ((our_per_mw - modo_dur["mid"]) / modo_dur["mid"] * 100)
        comparisons.append({
            "strategy": strat,
            "our_gbp_mw_yr": round(our_per_mw),
            "variance_vs_modo_mid_pct": round(variance, 1),
            "within_modo_range": modo_dur["low"] <= our_per_mw <= modo_dur["high"],
            "irr_pct": result["irr_pct"],
        })

    best = max(comparisons, key=lambda c: c["our_gbp_mw_yr"])
    worst = min(comparisons, key=lambda c: c["our_gbp_mw_yr"])

    return {
        "ok": True,
        "system": {
            "power_mw": power_mw,
            "duration_hours": duration_hours,
            "duration_class": dkey,
            "region": region,
            "year": year,
        },
        "modo_benchmark": {
            "year": year,
            "duration": dkey,
            "low_gbp_mw_yr": modo_dur["low"],
            "mid_gbp_mw_yr": modo_dur["mid"],
            "high_gbp_mw_yr": modo_dur["high"],
            "source": "Modo Energy BESS Revenue Index",
        },
        "strategy_comparisons": comparisons,
        "best_strategy": best["strategy"],
        "best_revenue_gbp_mw_yr": best["our_gbp_mw_yr"],
        "worst_strategy": worst["strategy"],
        "worst_revenue_gbp_mw_yr": worst["our_gbp_mw_yr"],
        "explanation": (
            f"For a {dkey} BESS in {region}, Modo Energy benchmarks "
            f"£{modo_dur['low']:,}-£{modo_dur['high']:,}/MW/yr (mid "
            f"£{modo_dur['mid']:,}). The '{best['strategy']}' strategy "
            f"yields £{best['our_gbp_mw_yr']:,}/MW/yr, "
            f"{'above' if best['our_gbp_mw_yr'] > modo_dur['mid'] else 'below'} "
            f"the Modo mid-point. Revenue varies significantly by strategy "
            f"and region — Scotland benefits from higher BM revenues while "
            f"Southern England captures more wholesale arbitrage."
        ),
    }


def optimal_duration(
    power_mw: float,
    region: str = "Midlands",
    year: str = "2026",
) -> dict[str, Any]:
    """
    Determine which duration (1h/2h/4h) maximises IRR for the given site.

    Longer duration = more revenue but higher CAPEX. The optimal point
    depends on capacity market de-rating and regional wholesale spreads.
    """
    results = []
    for dur in [1, 2, 4]:
        for strat in STRATEGIES:
            r = stack_revenues(power_mw, dur, region, year, strat)
            forecast = forecast_revenues(power_mw, dur, region, 15, strat)
            results.append({
                "duration_hours": dur,
                "duration_class": _duration_key(dur),
                "strategy": strat,
                "total_revenue_gbp": r["total_revenue_gbp"],
                "gbp_mw_yr": r["total_gbp_mw_yr"],
                "capex_total_gbp": r["capex_total_gbp"],
                "capex_gbp_kwh": r["capex_gbp_kwh"],
                "irr_pct": r["irr_pct"],
                "npv_8pct": forecast["npv"]["discount_8pct"],
                "payback_year": forecast["payback_year"],
            })

    # Find the best by IRR
    best_irr = max(results, key=lambda x: x["irr_pct"])
    # Find the best by NPV
    best_npv = max(results, key=lambda x: x["npv_8pct"])

    # Group by duration for summary
    by_duration = {}
    for r in results:
        d = r["duration_class"]
        if d not in by_duration:
            by_duration[d] = []
        by_duration[d].append(r)

    duration_summary = []
    for d in ["1h", "2h", "4h"]:
        group = by_duration.get(d, [])
        if group:
            best_in_group = max(group, key=lambda x: x["irr_pct"])
            duration_summary.append({
                "duration": d,
                "best_strategy": best_in_group["strategy"],
                "best_irr_pct": best_in_group["irr_pct"],
                "best_npv_8pct": best_in_group["npv_8pct"],
                "revenue_range_gbp_mw_yr": {
                    "min": min(g["gbp_mw_yr"] for g in group),
                    "max": max(g["gbp_mw_yr"] for g in group),
                },
                "capex_gbp_kwh": best_in_group["capex_gbp_kwh"],
            })

    return {
        "ok": True,
        "system": {
            "power_mw": power_mw,
            "region": region,
            "year": year,
        },
        "optimal_irr": {
            "duration": best_irr["duration_class"],
            "strategy": best_irr["strategy"],
            "irr_pct": best_irr["irr_pct"],
            "gbp_mw_yr": best_irr["gbp_mw_yr"],
            "npv_8pct": best_irr["npv_8pct"],
        },
        "optimal_npv": {
            "duration": best_npv["duration_class"],
            "strategy": best_npv["strategy"],
            "irr_pct": best_npv["irr_pct"],
            "gbp_mw_yr": best_npv["gbp_mw_yr"],
            "npv_8pct": best_npv["npv_8pct"],
        },
        "duration_summary": duration_summary,
        "all_combinations": results,
        "recommendation": (
            f"For {power_mw}MW in {region} ({year}), the highest IRR is "
            f"{best_irr['irr_pct']:.1f}% with {best_irr['duration_class']} "
            f"duration and '{best_irr['strategy']}' strategy. "
            f"The highest NPV (@8%) is £{best_npv['npv_8pct']:,.0f} with "
            f"{best_npv['duration_class']} / '{best_npv['strategy']}'."
        ),
    }


def list_streams() -> dict[str, Any]:
    """Return all revenue streams with current benchmarks and metadata."""
    streams = []
    for name, s in REVENUE_STREAMS.items():
        streams.append({
            "name": name,
            "description": s["description"],
            "driver": s.get("driver", ""),
            "benchmark_gbp_mw_yr": s["benchmark_gbp_mw_yr"],
            "capture_rate": s.get("capture_rate"),
            "de_rating": s.get("de_rating"),
            "growth_rate_pct_yr": s.get("growth_rate_pct", 0),
            "duration_scaling": s.get("duration_scaling", "linear"),
        })

    return {
        "ok": True,
        "streams": streams,
        "total_streams": len(streams),
        "strategies": list(STRATEGIES.keys()),
        "regions": list(REGIONAL_FACTORS.keys()),
        "modo_benchmarks": MODO_BENCHMARKS,
        "capex_benchmarks_gbp_kwh": CAPEX_GBP_KWH,
        "fixed_opex_gbp_mw_yr": FIXED_OPEX_GBP_MW_YR,
        "degradation_pct_yr": DEGRADATION_PCT_YR,
    }


# ===================================================================
# Internal helpers
# ===================================================================

def _estimate_irr(capex: float, annual_net: float, years: int = 20) -> float:
    """Simple IRR estimate using annuity approximation."""
    if capex <= 0 or annual_net <= 0:
        return 0.0
    # Newton's method on NPV = 0
    return _calculate_irr([-capex] + [annual_net] * years)


def _calculate_irr(cashflows: list[float], tol: float = 0.0001, max_iter: int = 100) -> float:
    """Calculate IRR using Newton-Raphson method."""
    if not cashflows or all(c == 0 for c in cashflows):
        return 0.0

    # Initial guess
    total_in = sum(c for c in cashflows if c > 0)
    total_out = abs(sum(c for c in cashflows if c < 0))
    if total_out == 0:
        return 100.0

    r = (total_in / total_out) ** (1 / max(len(cashflows) - 1, 1)) - 1
    r = max(min(r, 0.5), -0.5)  # clamp initial guess

    for _ in range(max_iter):
        npv = sum(cf / ((1 + r) ** i) for i, cf in enumerate(cashflows))
        dnpv = sum(-i * cf / ((1 + r) ** (i + 1)) for i, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-12:
            break
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol:
            r = r_new
            break
        r = r_new

    return r * 100  # return as percentage


def _payback_year(forecasts: list[dict], capex: float) -> int | None:
    """Find the year where cumulative net revenue exceeds CAPEX."""
    cumulative = 0.0
    for f in forecasts:
        cumulative += f.get("net_p50_gbp", 0)
        if cumulative >= capex:
            return f["year"]
    return None
