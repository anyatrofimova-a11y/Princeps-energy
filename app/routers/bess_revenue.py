"""BESS Revenue Stacking router — market benchmarks, revenue forecasting, optimal duration."""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.bess_revenue_stacker import (
    stack_revenues,
    forecast_revenues,
    compare_to_benchmark,
    optimal_duration,
    list_streams,
)

router = APIRouter(tags=["bess-revenue"])


@router.get("/api/bess/revenue-stack")
async def api_bess_revenue_stack(
    power_mw: float = Query(50, description="BESS power rating (MW)"),
    duration_hours: float = Query(2, description="Storage duration (hours)"),
    region: str = Query("Midlands", description="UK region"),
    year: str = Query("2026", description="Revenue year"),
    strategy: str = Query("balanced", description="Revenue strategy"),
):
    """Calculate stacked BESS revenues from 6 UK market streams."""
    return stack_revenues(power_mw, duration_hours, region, year, strategy)


@router.get("/api/bess/revenue-forecast")
async def api_bess_revenue_forecast(
    power_mw: float = Query(50, description="BESS power rating (MW)"),
    duration_hours: float = Query(2, description="Storage duration (hours)"),
    region: str = Query("Midlands", description="UK region"),
    years: int = Query(10, description="Forecast horizon (years)"),
    strategy: str = Query("balanced", description="Revenue strategy"),
):
    """Forecast BESS revenues forward with P10/P50/P90 and NPV."""
    return forecast_revenues(power_mw, duration_hours, region, years, strategy)


@router.get("/api/bess/benchmark")
async def api_bess_benchmark(
    power_mw: float = Query(50, description="BESS power rating (MW)"),
    duration_hours: float = Query(2, description="Storage duration (hours)"),
    region: str = Query("Midlands", description="UK region"),
    year: str = Query("2026", description="Benchmark year"),
):
    """Compare calculated revenue to Modo Energy published benchmarks."""
    return compare_to_benchmark(power_mw, duration_hours, region, year)


@router.get("/api/bess/streams")
async def api_bess_streams():
    """List all BESS revenue streams with current UK market benchmarks."""
    return list_streams()


@router.get("/api/bess/optimal-duration")
async def api_bess_optimal_duration(
    power_mw: float = Query(50, description="BESS power rating (MW)"),
    region: str = Query("Midlands", description="UK region"),
    year: str = Query("2026", description="Target year"),
):
    """Determine which duration (1h/2h/4h) maximises IRR for a given site."""
    return optimal_duration(power_mw, region, year)


# ─── Godmode-v2 #1 — Live revenue stack co-optimiser ───────────────────────

from pydantic import BaseModel as _BM
import math as _math
import random as _random


class _CoOptimiseRequest(_BM):
    power_mw: float = 50
    duration_hours: float = 2
    region: str = "Midlands"
    year: str = "2026"
    lookahead_hours: int = 24
    n_samples: int = 200  # Monte Carlo samples for P10/P50/P90


@router.post("/api/bess/revenue-co-optimise")
async def api_bess_co_optimise(body: _CoOptimiseRequest):
    """Co-optimise across revenue stacks with a 24-hour lookahead allocation
    and Monte Carlo resampling for P10/P50/P90 bands.

    MVP: greedy per-hour stack allocation against synthetic hourly clearing
    prices (arbitrage spread, DC/DM/DR clearing probability, wholesale).
    Real LP (PuLP/cvxpy) is sprint-2 work — this endpoint locks the contract
    so the frontend can render live today.
    """
    base = stack_revenues(body.power_mw, body.duration_hours, body.region, body.year, "balanced")
    stacks = base.get("streams") or base.get("revenue_streams") or []

    # Build a 24h lookahead of synthetic clearing prices per stack.
    hours = list(range(body.lookahead_hours))
    price_shape = [60 + 40 * _math.sin((h - 4) * _math.pi / 12) for h in hours]  # GBP/MWh wholesale
    allocation = []
    for h in hours:
        p = price_shape[h]
        # Rank-order revenue streams by marginal £ at this hour.
        ordered = sorted(
            stacks,
            key=lambda s: (s.get("gbp_per_mw_yr", 0) / 8760) + p * 0.02,
            reverse=True,
        )
        top = ordered[0] if ordered else {}
        allocation.append({
            "hour": h,
            "assigned_stack": top.get("stream") or top.get("name") or "arbitrage",
            "expected_gbp_mwh": round(p, 2),
            "mw_allocated": body.power_mw,
        })

    # Monte Carlo: perturb each stack's annual by a log-normal multiplier.
    annual_samples = []
    base_annual = base.get("annual_gbp") or base.get("total_annual_gbp") or 0
    for _ in range(body.n_samples):
        m = max(0.4, min(1.8, _random.lognormvariate(0, 0.22)))
        annual_samples.append(base_annual * m)
    annual_samples.sort()
    n = len(annual_samples) or 1

    def pct(p):
        idx = max(0, min(n - 1, int(n * p)))
        return round(annual_samples[idx], 0)

    return {
        "power_mw": body.power_mw,
        "duration_hours": body.duration_hours,
        "region": body.region,
        "year": body.year,
        "base_annual_gbp": round(base_annual, 0),
        "annual_bands_gbp": {
            "p10": pct(0.10),
            "p50": pct(0.50),
            "p90": pct(0.90),
        },
        "lookahead": allocation,
        "streams": stacks,
        "method": "greedy_lookahead_v1",
        "notes": "MVP greedy allocator; full LP (cvxpy) is sprint-2 upgrade.",
    }
