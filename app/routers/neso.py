"""NESO data routes — Carbon Intensity, BMRS demand/generation, TEC register."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query, Request

from utils.neso_data_ingester import (
    fetch_carbon_intensity,
    fetch_demand_outturn,
    fetch_generation_mix,
    fetch_tec_register,
    fetch_system_prices,
    fetch_connection_queue,
    ingest_all,
)

log = logging.getLogger("princeps.neso")
router = APIRouter(prefix="/api/neso", tags=["neso"])


@router.get("/carbon-intensity")
async def carbon_intensity(
    from_dt: str | None = Query(None),
    to_dt: str | None = Query(None),
    regional: bool = Query(False),
):
    return await fetch_carbon_intensity(from_dt, to_dt, regional)


@router.get("/demand")
async def demand(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    return await fetch_demand_outturn(start_date, end_date)


@router.get("/generation-mix")
async def generation_mix(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    return await fetch_generation_mix(start_date, end_date)


@router.get("/tec-register")
async def tec_register(
    connection_site: str | None = Query(None),
    technology: str | None = Query(None),
    min_capacity_mw: float | None = Query(None),
    status: str | None = Query(None),
):
    return await fetch_tec_register(connection_site, technology, min_capacity_mw, status)


@router.get("/system-prices")
async def system_prices(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    return await fetch_system_prices(start_date, end_date)


@router.get("/connection-queue")
async def connection_queue(location: str | None = Query(None)):
    return await fetch_connection_queue(location)


@router.post("/ingest")
async def trigger_ingest(request: Request):
    pool = request.app.state.pool
    result = await ingest_all(pool)
    return {"status": "ok", "results": result}
