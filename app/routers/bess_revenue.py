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
