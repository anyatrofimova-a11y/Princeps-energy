"""DNO capacity routes — ECR, headroom, capacity map."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query, Request

from utils.dno_capacity_ingester import (
    fetch_ecr,
    fetch_headroom,
    query_ecr,
    query_headroom,
    capacity_map_geojson,
    ecr_summary_by_substation,
    ingest_dno_capacity,
)

log = logging.getLogger("princeps.dno")
router = APIRouter(prefix="/api/dno", tags=["dno"])


@router.get("/ecr")
async def ecr(
    request: Request,
    dno: str | None = Query(None),
    substation: str | None = Query(None),
    technology: str | None = Query(None),
    status: str | None = Query(None),
):
    pool = request.app.state.pool
    return await query_ecr(pool, dno, substation, technology, status)


@router.get("/headroom")
async def headroom(
    request: Request,
    lat: float | None = Query(None),
    lon: float | None = Query(None),
    radius_km: float = Query(20),
    dno: str | None = Query(None),
):
    pool = request.app.state.pool
    return await query_headroom(pool, lat, lon, radius_km, dno)


@router.get("/capacity-map")
async def capacity_map(
    request: Request,
    dno: str | None = Query(None),
):
    pool = request.app.state.pool
    return await capacity_map_geojson(pool, dno)


@router.get("/ecr/summary")
async def ecr_summary(
    request: Request,
    dno: str | None = Query(None),
):
    pool = request.app.state.pool
    return await ecr_summary_by_substation(pool, dno)


@router.post("/ingest")
async def trigger_ingest(request: Request):
    pool = request.app.state.pool
    result = await ingest_dno_capacity(pool)
    return {"status": "ok", "results": result}
