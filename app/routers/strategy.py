"""Connection strategy + advanced grid endpoints (Phase 7 & 8)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query

from app.helpers import _run_generic_subprocess

router = APIRouter(tags=["strategy"])

# ── Script paths ──────────────────────────────────────────────────────────────
_UTILS_DIR = str(Path(__file__).resolve().parent.parent.parent / "utils")
_CURTAILMENT_SCRIPT = str(Path(_UTILS_DIR) / "curtailment_estimator.py")
_FLEXIBLE_SCRIPT = str(Path(_UTILS_DIR) / "flexible_connection.py")
_TIMELINE_SCRIPT = str(Path(_UTILS_DIR) / "connection_timeline.py")
_STRATEGY_SCRIPT = str(Path(_UTILS_DIR) / "connection_strategy.py")
_DLR_SCRIPT = str(Path(_UTILS_DIR) / "dynamic_line_rating.py")
_CONGESTION_SCRIPT = str(Path(_UTILS_DIR) / "congestion_predictor.py")
_OPTIMISER_SCRIPT = str(Path(_UTILS_DIR) / "connection_optimiser.py")
_REINFORCEMENT_SCRIPT = str(Path(_UTILS_DIR) / "reinforcement_cost.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONNECTION STRATEGY — Curtailment, Flexible, Timeline, Strategy (Phase 8)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Curtailment ──

@router.get("/api/connection-strategy/curtailment/estimate")
async def api_curtailment_estimate(
    capacity_mw: float = Query(50),
    voltage_kv: int = Query(132),
    region: str = Query("Midlands"),
    technology: str = Query("solar"),
    connection_type: str = Query("firm"),
    queue_depth: int = Query(0),
):
    """Estimate annual curtailment with P10/P50/P90."""
    return await _run_generic_subprocess(_CURTAILMENT_SCRIPT, {
        "command": "estimate_annual",
        "capacity_mw": capacity_mw, "voltage_kv": voltage_kv,
        "region": region, "technology": technology,
        "connection_type": connection_type, "queue_depth": queue_depth,
    })


@router.get("/api/connection-strategy/curtailment/revenue-impact")
async def api_curtailment_revenue(
    capacity_mw: float = Query(50),
    region: str = Query("Midlands"),
    technology: str = Query("solar"),
    connection_type: str = Query("firm"),
    wholesale_price_mwh: float = Query(55),
):
    """Calculate revenue impact of curtailment."""
    return await _run_generic_subprocess(_CURTAILMENT_SCRIPT, {
        "command": "revenue_impact",
        "capacity_mw": capacity_mw, "region": region,
        "technology": technology, "connection_type": connection_type,
        "wholesale_price_mwh": wholesale_price_mwh,
    })


@router.get("/api/connection-strategy/curtailment/regions")
async def api_curtailment_regions():
    """List available regions and connection types."""
    return await _run_generic_subprocess(_CURTAILMENT_SCRIPT, {"command": "regions"})


# ── Flexible Connection ──

@router.post("/api/connection-strategy/flexible/compare")
async def api_flexible_compare(body: dict):
    """Compare firm vs ANM vs non-firm connection options."""
    return await _run_generic_subprocess(_FLEXIBLE_SCRIPT, {
        "command": "compare",
        "capacity_mw": body.get("capacity_mw", 50),
        "headroom_mw": body.get("headroom_mw", 30),
        "region": body.get("region", "Midlands"),
        "technology": body.get("technology", "solar"),
        "voltage_kv": body.get("voltage_kv", 132),
    })


@router.get("/api/connection-strategy/flexible/anm-profile")
async def api_flexible_anm_profile(
    capacity_mw: float = Query(50),
    headroom_mw: float = Query(30),
    technology: str = Query("solar"),
):
    """Generate 24-hour ANM export profile."""
    return await _run_generic_subprocess(_FLEXIBLE_SCRIPT, {
        "command": "anm_profile",
        "capacity_mw": capacity_mw, "headroom_mw": headroom_mw,
        "technology": technology,
    })


@router.get("/api/connection-strategy/flexible/optimal-sizing")
async def api_flexible_sizing(
    headroom_mw: float = Query(30),
    region: str = Query("Midlands"),
    technology: str = Query("solar"),
    target_curtailment_pct: float = Query(5),
):
    """Find optimal plant capacity for given headroom."""
    return await _run_generic_subprocess(_FLEXIBLE_SCRIPT, {
        "command": "optimal_sizing",
        "headroom_mw": headroom_mw, "region": region,
        "technology": technology, "target_curtailment_pct": target_curtailment_pct,
    })


# ── Connection Timeline ──

@router.post("/api/connection-strategy/timeline/generate")
async def api_timeline_generate(body: dict):
    """Generate connection timeline with milestones and critical path."""
    return await _run_generic_subprocess(_TIMELINE_SCRIPT, {
        "command": "generate",
        "capacity_mw": body.get("capacity_mw", 50),
        "voltage_kv": body.get("voltage_kv", 132),
        "connection_type": body.get("connection_type", "firm"),
        "start_date": body.get("start_date", "2025-06-01"),
    })


@router.get("/api/connection-strategy/timeline/milestones")
async def api_timeline_milestones(capacity_mw: float = Query(50)):
    """Return milestone templates."""
    return await _run_generic_subprocess(_TIMELINE_SCRIPT, {
        "command": "milestones", "capacity_mw": capacity_mw,
    })


# ── Connection Strategy ──

@router.post("/api/connection-strategy/strategy")
async def api_connection_strategy(body: dict):
    """Generate comprehensive connection strategy report."""
    return await _run_generic_subprocess(_STRATEGY_SCRIPT, {
        "command": "strategy",
        "lat": body.get("lat", 51.5), "lon": body.get("lon", -1.0),
        "capacity_mw": body.get("capacity_mw", 50),
        "technology": body.get("technology", "solar"),
        "voltage_kv": body.get("voltage_kv", 132),
        "headroom_mw": body.get("headroom_mw", 30),
        "distance_km": body.get("distance_km", 5),
    })


@router.post("/api/connection-strategy/compare")
async def api_strategy_compare(body: dict):
    """Compare strategies with sensitivity analysis."""
    return await _run_generic_subprocess(_STRATEGY_SCRIPT, {
        "command": "compare_strategies",
        "capacity_mw": body.get("capacity_mw", 50),
        "region": body.get("region", "Midlands"),
        "headroom_mw": body.get("headroom_mw", 30),
        "technology": body.get("technology", "solar"),
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  ADVANCED GRID ANALYSIS — DLR, Congestion, Optimiser, Reinforcement (Phase 7)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Dynamic Line Rating ──

@router.get("/api/advanced-grid/dlr/rate")
async def api_dlr_rate(
    conductor: str = Query("Zebra"),
    ambient_temp_c: float = Query(20),
    wind_speed_ms: float = Query(0.5),
    wind_angle_deg: float = Query(45),
    solar_irradiance_wm2: float = Query(0),
):
    """Calculate dynamic line rating for a conductor under given weather."""
    return await _run_generic_subprocess(_DLR_SCRIPT, {
        "command": "rate",
        "conductor": conductor,
        "ambient_temp_c": ambient_temp_c,
        "wind_speed_ms": wind_speed_ms,
        "wind_angle_deg": wind_angle_deg,
        "solar_irradiance_wm2": solar_irradiance_wm2,
    })


@router.get("/api/advanced-grid/dlr/rate-line")
async def api_dlr_rate_line(
    voltage_kv: int = Query(132),
    ambient_temp_c: float = Query(20),
    wind_speed_ms: float = Query(0.5),
    wind_angle_deg: float = Query(45),
    solar_irradiance_wm2: float = Query(0),
):
    """Calculate DLR for a line by voltage level."""
    return await _run_generic_subprocess(_DLR_SCRIPT, {
        "command": "rate_line",
        "voltage_kv": voltage_kv,
        "ambient_temp_c": ambient_temp_c,
        "wind_speed_ms": wind_speed_ms,
        "wind_angle_deg": wind_angle_deg,
        "solar_irradiance_wm2": solar_irradiance_wm2,
    })


@router.get("/api/advanced-grid/dlr/seasonal")
async def api_dlr_seasonal(conductor: str = Query("Zebra"), lat: float = Query(52.0)):
    """Seasonal DLR profile showing uplift across typical UK conditions."""
    return await _run_generic_subprocess(_DLR_SCRIPT, {
        "command": "seasonal_profile",
        "conductor": conductor,
        "lat": lat,
    })


@router.get("/api/advanced-grid/dlr/conductors")
async def api_dlr_conductors():
    """List available conductor types."""
    return await _run_generic_subprocess(_DLR_SCRIPT, {"command": "list_conductors"})


# ── Congestion Prediction ──

@router.get("/api/advanced-grid/congestion/predict")
async def api_congestion_predict(
    hour: int = Query(17),
    month: int = Query(1),
    day_of_week: int = Query(2),
    demand_gw: float = Query(42),
    wind_gen_gw: float = Query(8),
    solar_gen_gw: float = Query(1),
    temperature_c: float = Query(5),
):
    """Predict congestion probability for all UK transmission boundaries."""
    return await _run_generic_subprocess(_CONGESTION_SCRIPT, {
        "command": "predict",
        "hour": hour, "month": month, "day_of_week": day_of_week,
        "demand_gw": demand_gw, "wind_gen_gw": wind_gen_gw,
        "solar_gen_gw": solar_gen_gw, "temperature_c": temperature_c,
    })


@router.get("/api/advanced-grid/congestion/predict-day")
async def api_congestion_predict_day(
    date: str = Query("2024-12-15"),
    demand_base_gw: float = Query(40),
):
    """Predict congestion for every hour of a given day."""
    return await _run_generic_subprocess(_CONGESTION_SCRIPT, {
        "command": "predict_day",
        "date": date, "demand_base_gw": demand_base_gw,
    })


@router.get("/api/advanced-grid/congestion/boundaries")
async def api_congestion_boundaries():
    """List UK transmission boundaries."""
    return await _run_generic_subprocess(_CONGESTION_SCRIPT, {"command": "boundaries"})


# ── Connection Optimiser ──

@router.post("/api/advanced-grid/optimise")
async def api_connection_optimise(body: dict):
    """Multi-objective connection optimisation with Pareto frontier."""
    return await _run_generic_subprocess(_OPTIMISER_SCRIPT, {
        "command": "optimise",
        "lat": body.get("lat", 51.5),
        "lon": body.get("lon", -1.0),
        "capacity_mw": body.get("capacity_mw", 50),
        "technology": body.get("technology", "solar"),
        "candidates": body.get("candidates"),
    })


# ── Reinforcement Cost ──

@router.get("/api/advanced-grid/reinforcement/estimate")
async def api_reinforcement_estimate(
    distance_km: float = Query(5),
    voltage_kv: int = Query(132),
    capacity_mw: float = Query(50),
    headroom_mw: float = Query(0),
    terrain: str = Query("rural"),
    connection_type: str = Query("cable"),
):
    """Monte Carlo reinforcement cost estimate with P10/P50/P90."""
    return await _run_generic_subprocess(_REINFORCEMENT_SCRIPT, {
        "command": "estimate",
        "distance_km": distance_km, "voltage_kv": voltage_kv,
        "capacity_mw": capacity_mw, "headroom_mw": headroom_mw,
        "terrain": terrain, "connection_type": connection_type,
    })


@router.get("/api/advanced-grid/reinforcement/benchmarks")
async def api_reinforcement_benchmarks():
    """Return UK DNO reinforcement cost benchmark tables."""
    return await _run_generic_subprocess(_REINFORCEMENT_SCRIPT, {"command": "benchmarks"})
