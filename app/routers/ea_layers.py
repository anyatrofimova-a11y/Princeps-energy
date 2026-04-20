"""
/api/ea/* — Environment Agency layer endpoints.

Flood Zones 2 + 3 as GeoJSON (bbox-filtered) + on-demand ingester trigger.
LiDAR tiles served via existing substrate router.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.deps import get_pool
from utils.substrate.ea_flood_ingester import ingest_flood_zones_bbox

log = logging.getLogger("princeps.routers.ea_layers")

router = APIRouter(prefix="/api/ea", tags=["ea"])


@router.get("/flood/{zone}")
async def flood_zone_geojson(
    zone: int,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(5000, ge=1, le=20000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Return GeoJSON FeatureCollection for Flood Zone 2 or 3 inside bbox."""
    if zone not in (2, 3):
        raise HTTPException(400, "zone must be 2 or 3")
    try:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        min_lon, min_lat, max_lon, max_lat = parts
    except ValueError:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")

    table = f"ea_flood_zone_{zone}"
    sql = f"""
        SELECT feature_id, zone_class, climate_scenario, area_ha,
               ST_AsGeoJSON(geom::geometry)::jsonb AS geom
        FROM {table}
        WHERE ST_Intersects(
            geom,
            ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography
        )
        LIMIT $5
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, min_lon, min_lat, max_lon, max_lat, limit)
    except Exception as e:
        log.warning("flood_zone query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    features = [
        {
            "type": "Feature",
            "id": r["feature_id"],
            "properties": {
                "zone_class": r["zone_class"],
                "climate_scenario": r["climate_scenario"],
                "area_ha": float(r["area_ha"]) if r["area_ha"] is not None else None,
                "zone_number": zone,
            },
            "geometry": r["geom"],
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


@router.post("/ingest")
async def trigger_ingest(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Trigger an on-demand bbox ingest of EA flood zones. Admin-only in prod."""
    try:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        bbox_tuple = tuple(parts)
    except ValueError:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")

    try:
        result = await ingest_flood_zones_bbox(pool, bbox_tuple)  # type: ignore[arg-type]
        return {"status": "ok", "result": result}
    except Exception as e:
        log.error("EA ingest failed: %s", e)
        raise HTTPException(500, f"ingest failed: {e}")


@router.get("/status")
async def ingest_status(pool=Depends(get_pool)) -> dict[str, Any]:
    """Return last ingestion run summary for EA flood datasets."""
    sql = """
        SELECT id, dataset, bbox, rows_inserted, rows_updated, status,
               started_at, finished_at
        FROM ea_ingest_log
        ORDER BY started_at DESC
        LIMIT 10
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return {"runs": [dict(r) for r in rows]}
    except Exception as e:
        return {"runs": [], "error": str(e)}
