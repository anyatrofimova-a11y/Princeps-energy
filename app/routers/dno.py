"""DNO capacity routes — ECR, headroom, capacity map — plus licence-area
overlays for the map filter (Task #19)."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query, Request

from utils.dno_capacity_ingester import (
    fetch_ecr,
    fetch_headroom,
    query_ecr,
    query_headroom,
    capacity_map_geojson,
    ecr_summary_by_substation,
    ingest_dno_capacity,
)
from utils.dno_boundaries import (
    dno_for_point,
    dno_metadata,
    licence_areas_geojson,
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


# ─── Licence-area overlays (map filter, Task #19) ────────────────────────────

@router.get("/licence-areas")
async def licence_areas(
    request: Request,
    as_of: str | None = Query(
        None,
        description="ISO date (YYYY-MM-DD). Defaults to today. Filters to "
                    "features in force on that date.",
    ),
    simplify: float = Query(
        0.0005,
        ge=0.0,
        le=0.05,
        description="ST_SimplifyPreserveTopology tolerance in degrees. "
                    "0 disables simplification.",
    ),
    operator_class: str | None = Query(
        None,
        description="Optional filter: DNO | IDNO | TO.",
    ),
):
    """
    Return a GeoJSON FeatureCollection of licence-area polygons for the map
    overlay. WGS84 coordinates, ready for Mapbox / deck.gl.
    """
    pool = request.app.state.pool
    if operator_class and operator_class.upper() not in {"DNO", "IDNO", "TO"}:
        raise HTTPException(status_code=400, detail="operator_class must be DNO, IDNO or TO")
    return await licence_areas_geojson(
        pool,
        as_of=as_of,
        simplify=(simplify or None),
        operator_class=(operator_class.upper() if operator_class else None),
    )


@router.get("/by-point")
async def by_point(
    request: Request,
    lng: float = Query(..., description="WGS84 longitude"),
    lat: float = Query(..., description="WGS84 latitude"),
):
    """
    Return the DNO slug whose licence area contains the given WGS84 point.
    200 with ``{"dno_slug": null}`` when no DNO matches (offshore, outside
    GB & NI, or table unpopulated).
    """
    pool = request.app.state.pool
    slug = await dno_for_point(pool, lng, lat)
    return {"dno_slug": slug, "lng": lng, "lat": lat}


# NOTE: keep this route AFTER all more-specific ``/api/dno/<word>`` routes
# (ecr, headroom, capacity-map, licence-areas, by-point, ingest) — otherwise
# ``/api/dno/{slug}`` would swallow them.
@router.get("/{slug}")
async def dno_detail(request: Request, slug: str):
    """DNO metadata + list of sub-regions (children with parent_slug=slug)."""
    pool = request.app.state.pool
    meta = await dno_metadata(pool, slug)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"DNO slug not found: {slug}")
    return meta
