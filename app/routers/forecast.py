"""Forecast router — per-site probabilistic demand forecasts by SIC typology."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query, HTTPException

from app.forecast import (
    forecast_site_load,
    list_typologies,
    get_typology,
    BehindMeterAssets,
    dirty_sites,
    clear_dirty,
    note_ecr_change,
    Horizon,
    Scenario,
)

log = logging.getLogger("princeps.forecast")
router = APIRouter(tags=["forecast"])


@router.get("/api/forecast/typologies")
async def api_list_typologies():
    """Library of SIC-keyed site typologies (ranked by UK dev-pipeline relevance)."""
    typs = list_typologies()
    return {"count": len(typs), "typologies": typs}


@router.get("/api/forecast/typology/{key_or_sic}")
async def api_get_typology(key_or_sic: str):
    t = get_typology(key_or_sic)
    return {
        "key": t.key,
        "name": t.name,
        "sic_codes": t.sic_codes,
        "load_factor": t.load_factor,
        "weekday_weekend_ratio": t.weekday_weekend_ratio,
        "weather_sensitivity": t.weather_sensitivity,
        "ev_uplift_frac": t.ev_uplift_frac,
        "hp_uplift_frac": t.hp_uplift_frac,
        "base_growth_pa": t.base_growth_pa,
        "pathway_growth": t.pathway_growth,
        "hh_profile": t.hh_profile,
        "description": t.description,
    }


@router.get("/api/forecast/site-load")
async def api_site_load_forecast(
    site_id: str = Query(..., description="Site identifier (GSP, substation, project)"),
    horizon: str = Query("day_ahead"),
    scenario: str = Query("central"),
    typology: str | None = Query(None, description="SIC code or typology slug"),
    peak_mw: float = Query(1.0, ge=0.0),
    pv_mw: float = Query(0.0, ge=0.0),
    bess_mw: float = Query(0.0, ge=0.0),
    bess_duration_h: float = Query(2.0, ge=0.0),
    ev_penetration: float = Query(0.0, ge=0.0, le=1.0),
    hp_penetration: float = Query(0.0, ge=0.0, le=1.0),
    ambient_c: float = Query(10.0),
    month: int = Query(6, ge=1, le=12),
    use_subprocess: bool = Query(True),
):
    """Per-site probabilistic demand forecast.

    Returns a ForecastResult (P10/P50/P90 series + timestamps + provenance).
    Always returns 200 with a well-shaped response — confidence reflects
    data quality.
    """
    bm = BehindMeterAssets(
        pv_mw=pv_mw,
        bess_mw=bess_mw,
        bess_duration_h=bess_duration_h,
        ev_penetration=ev_penetration,
        hp_penetration=hp_penetration,
        ambient_c=ambient_c,
        month=month,
    )
    try:
        result = await forecast_site_load(
            site_id=site_id,
            horizon=horizon,
            scenario=scenario,
            typology=typology,
            peak_mw=peak_mw,
            behind_meter=bm,
            use_subprocess=use_subprocess,
        )
    except Exception as e:
        log.exception("forecast_site_load failed: %s", e)
        raise HTTPException(status_code=500, detail=f"forecast failed: {e}")
    return result.to_dict()


@router.get("/api/forecast/horizons")
async def api_horizons():
    return {
        "horizons": [h.value for h in Horizon],
        "scenarios": [s.value for s in Scenario],
    }


@router.get("/api/forecast/dirty")
async def api_dirty():
    """Sites flagged dirty by upstream events (ECR, demand, substation updates)."""
    rows = dirty_sites()
    return {"count": len(rows), "dirty": rows}


@router.post("/api/forecast/dirty/clear")
async def api_clear_dirty(site_id: str | None = Query(None)):
    n = clear_dirty([site_id] if site_id else None)
    return {"cleared": n}


@router.post("/api/forecast/ecr-change")
async def api_ecr_change(
    gsp_ids: str = Query("", description="Comma-separated GSP IDs"),
    substation_ids: str = Query("", description="Comma-separated substation IDs"),
):
    gsp_list = [s.strip() for s in gsp_ids.split(",") if s.strip()]
    sub_list = [s.strip() for s in substation_ids.split(",") if s.strip()]
    n = note_ecr_change(gsp_list, sub_list)
    return {"marked_dirty": n}
