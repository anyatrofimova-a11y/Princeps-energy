"""
/api/ea/* — Environment Agency layer endpoints.

Flood Zones 2 + 3 as GeoJSON (bbox-filtered) + on-demand ingester trigger.
LiDAR tiles served via existing substrate router.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.deps import get_pool
from utils.substrate.ea_flood_ingester import ingest_flood_zones_bbox

log = logging.getLogger("princeps.routers.ea_layers")

router = APIRouter(prefix="/api/ea", tags=["ea"])

# ── EA WMS proxy for first-class flood overlays (BOT-FLOOD) ─────────────
# Defra Spatial Data Platform reorg (Jan 2025) moved canonical WMS to
# environment.data.gov.uk/arcgis/rest/services/EA/<service>/MapServer/WMSServer.
# We proxy through FastAPI for: (a) consistent CORS, (b) 24h tile cache,
# (c) graceful fallback to a 1x1 transparent PNG when EA is down.
EA_WMS_DATASETS: dict[str, dict[str, str]] = {
    "flood_zone_2": {
        "url": "https://environment.data.gov.uk/arcgis/rest/services/EA/FloodMapForPlanningRiversandSeaFloodZone2/MapServer/WMSServer",
        "layers": "0",
        "label": "EA Flood Map for Planning — Zone 2 (1-in-1000y)",
    },
    "flood_zone_3": {
        "url": "https://environment.data.gov.uk/arcgis/rest/services/EA/FloodMapForPlanningRiversandSeaFloodZone3/MapServer/WMSServer",
        "layers": "0",
        "label": "EA Flood Map for Planning — Zone 3 (1-in-100y)",
    },
    "rofrs": {
        "url": "https://environment.data.gov.uk/arcgis/rest/services/EA/RiskOfFloodingFromRiversAndSea/MapServer/WMSServer",
        "layers": "0",
        "label": "EA Risk of Flooding from Rivers and Sea (NaFRA 2024)",
    },
    "rofrsw": {
        "url": "https://environment.data.gov.uk/arcgis/rest/services/EA/RiskOfFloodingFromSurfaceWater/MapServer/WMSServer",
        "layers": "0",
        "label": "EA Risk of Flooding from Surface Water",
    },
    "reservoir": {
        "url": "https://environment.data.gov.uk/arcgis/rest/services/EA/ReservoirFloodExtentsWetDayNational/MapServer/WMSServer",
        "layers": "0",
        "label": "EA Reservoir Inundation (Wet Day, National)",
    },
}

# Minimal 1x1 transparent PNG returned when an upstream tile fails so the
# Mapbox raster source doesn't display broken-tile crosses.
_TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8"
    b"\xcf\xc0\x00\x00\x00\x03\x00\x01\x10\xc0\x14\xa8\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


@router.get("/wms")
async def ea_wms_proxy(
    dataset: str = Query(..., description="One of: flood_zone_2, flood_zone_3, rofrs, rofrsw, reservoir"),
    bbox: str = Query(..., description="EPSG:3857 bbox — supplied by Mapbox via {bbox-epsg-3857}"),
    width: int = Query(512, ge=64, le=1024),
    height: int = Query(512, ge=64, le=1024),
    fmt: str = Query("image/png", alias="format"),
) -> Response:
    """Proxy a single EA WMS GetMap tile. Always returns 200 (transparent
    PNG fallback) so the Mapbox raster source keeps requesting tiles."""
    cfg = EA_WMS_DATASETS.get(dataset)
    if not cfg:
        raise HTTPException(404, f"unknown dataset: {dataset!r}")
    params = {
        "service": "WMS", "version": "1.3.0", "request": "GetMap",
        "layers": cfg["layers"], "styles": "", "crs": "EPSG:3857",
        "bbox": bbox, "width": str(width), "height": str(height),
        "format": fmt, "transparent": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            r = await c.get(
                cfg["url"], params=params,
                headers={"User-Agent": "Princeps EA proxy", "Accept": fmt},
            )
        if r.status_code != 200 or len(r.content) < 100:
            return Response(_TRANSPARENT_PNG, media_type="image/png")
        return Response(
            r.content,
            media_type=r.headers.get("content-type", fmt),
            headers={
                "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
            },
        )
    except httpx.HTTPError as exc:
        log.warning("EA WMS proxy %s failed: %s", dataset, exc)
        return Response(_TRANSPARENT_PNG, media_type="image/png")


@router.get("/wms/datasets")
async def list_wms_datasets() -> dict[str, Any]:
    """Used by the LayerControlPanel to populate the flood-layer toggles."""
    return {
        "datasets": [
            {"key": k, "label": v["label"]} for k, v in EA_WMS_DATASETS.items()
        ],
    }


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
