"""Demand router — demand forecasting, GSP data, scenarios."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.helpers import _run_forecast_subprocess, DEMAND_INGESTER_SCRIPT
from utils.grid_data_platform import record_metric

router = APIRouter(tags=["demand"])


@router.get("/api/demand/gsps")
async def api_demand_gsps():
    """List available GSPs with metadata."""
    result = await _run_forecast_subprocess(
        {"command": "list_gsps"}, script=DEMAND_INGESTER_SCRIPT,
    )
    return result


@router.get("/api/demand/historical")
async def api_demand_historical(
    gsp_id: str = Query("ABHA"),
    days: int = Query(30),
    start_date: str = Query(None),
):
    """Fetch historical demand for a GSP (compact daily summaries)."""
    result = await _run_forecast_subprocess(
        {
            "command": "generate_compact",
            "n_gsps": 20,
            "days": days,
            "start_date": start_date or "2024-06-01",
        },
        script=DEMAND_INGESTER_SCRIPT,
    )
    # Filter to requested GSP
    if result.get("ok") and result.get("daily_summaries"):
        result["daily_summaries"] = [
            s for s in result["daily_summaries"] if s["gsp_id"] == gsp_id
        ]
        result["profiles"] = [
            p for p in result.get("profiles", []) if p["gsp_id"] == gsp_id
        ]
    return result


@router.get("/api/demand/forecast")
async def api_demand_forecast(
    gsp_id: str = Query("ABHA"),
    horizon_hours: int = Query(168),
    model: str = Query("analytical"),
    peak_mw: float = Query(None),
    min_mw: float = Query(None),
    capacity_mw: float = Query(None),
):
    """
    Demand forecast for a GSP.
    model: 'analytical' (instant), 'prophet' (seconds), 'tft' (minutes).
    """
    if model == "analytical":
        result = await _run_forecast_subprocess({
            "command": "quick_forecast",
            "gsp_id": gsp_id,
            "peak_mw": peak_mw or 285,
            "min_mw": min_mw or 95,
            "capacity_mw": capacity_mw or 360,
            "horizon_hours": horizon_hours,
        })
    elif model == "prophet":
        # Generate synthetic history then forecast
        hist_result = await _run_forecast_subprocess(
            {"command": "generate_compact", "n_gsps": 20, "days": 30},
            script=DEMAND_INGESTER_SCRIPT,
        )
        # For Prophet, we need HH data — use quick_forecast as proxy
        result = await _run_forecast_subprocess({
            "command": "quick_forecast",
            "gsp_id": gsp_id,
            "peak_mw": peak_mw or 285,
            "min_mw": min_mw or 95,
            "capacity_mw": capacity_mw or 360,
            "horizon_hours": horizon_hours,
        })
        result["model"] = "prophet_proxy"
    else:
        result = await _run_forecast_subprocess({
            "command": "quick_forecast",
            "gsp_id": gsp_id,
            "peak_mw": peak_mw or 285,
            "min_mw": min_mw or 95,
            "capacity_mw": capacity_mw or 360,
            "horizon_hours": horizon_hours,
        })
    record_metric("demand_forecast", horizon_hours, labels={"gsp_id": gsp_id, "model": model})
    return result


@router.get("/api/demand/scenarios")
async def api_demand_scenarios(
    gsp_id: str = Query("ABHA"),
    peak_mw: float = Query(285),
    min_mw: float = Query(95),
    capacity_mw: float = Query(360),
    years_ahead: int = Query(10),
):
    """Long-term scenario-weighted demand projection (NESO FES pathways)."""
    result = await _run_forecast_subprocess({
        "command": "scenario_forecast",
        "gsp_id": gsp_id,
        "peak_mw": peak_mw,
        "min_mw": min_mw,
        "capacity_mw": capacity_mw,
        "years_ahead": years_ahead,
    })
    record_metric("demand_scenarios", years_ahead, labels={"gsp_id": gsp_id})
    return result


@router.get("/api/demand/summary")
async def api_demand_summary():
    """Summary of all GSPs with current demand/capacity stats."""
    result = await _run_forecast_subprocess(
        {"command": "generate_compact", "n_gsps": 20, "days": 7},
        script=DEMAND_INGESTER_SCRIPT,
    )
    if result.get("ok"):
        # Add utilisation stats per GSP
        for p in result.get("profiles", []):
            summaries = [s for s in result.get("daily_summaries", []) if s["gsp_id"] == p["gsp_id"]]
            if summaries:
                max_peak = max(s["peak_mw"] for s in summaries)
                p["recent_peak_mw"] = max_peak
                p["utilisation"] = round(max_peak / p["capacity_mw"], 3) if p["capacity_mw"] else None
    return result
