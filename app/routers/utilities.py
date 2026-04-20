"""
/api/utilities/* — utility context layers for the DC site twin.

Serves the four utility layers BOT-B3 ingested into PostGIS:

    /api/utilities/waterways  — OSM rivers / canals / streams (LineString)
    /api/utilities/roads      — OSM highway network, access-class tagged
    /api/utilities/gas        — OSM man_made=pipeline, substance=gas
    /api/utilities/fibre      — Carrier POP / exchange seed (Point)

All four accept bbox=minLon,minLat,maxLon,maxLat (WGS84) + optional limit,
and return GeoJSON FeatureCollection. Frontend fallbacks (dcContext.js)
hit these first; if the table is empty for the bbox they drop through to
the legacy Overpass-in-browser path.

If a bbox query returns zero rows and `lazy_fill=1`, we fire a background
task to ingest the bbox from OSM so the next call is warm. Cap the ingest
tile size — too-big bboxes blow up Overpass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.deps import get_pool

log = logging.getLogger("princeps.routers.utilities")

router = APIRouter(prefix="/api/utilities", tags=["utilities"])


# ─── helpers ────────────────────────────────────────────────────────────

_MAX_BBOX_DEG = 2.5  # refuse ridiculous bboxes (≈ 280 km at UK latitudes)


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(p) for p in bbox.split(",")]
    except ValueError:
        raise HTTPException(400, "bbox must be 4 comma-separated numbers")
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
    min_lon, min_lat, max_lon, max_lat = parts
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(400, "bbox is empty or inverted")
    if (max_lon - min_lon) > _MAX_BBOX_DEG or (max_lat - min_lat) > _MAX_BBOX_DEG:
        raise HTTPException(400, f"bbox too large (>{_MAX_BBOX_DEG} deg per side)")
    return min_lon, min_lat, max_lon, max_lat


async def _line_features(pool, table: str, extra_cols: list[str],
                          bbox: tuple[float, float, float, float],
                          limit: int) -> list[dict]:
    """Shared GeoJSON projector for LineString utility tables."""
    cols = ", ".join(extra_cols)
    sql = f"""
        SELECT id, {cols},
               ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geom
          FROM {table}
         WHERE ST_Intersects(
               geom,
               ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
             )
         LIMIT $5
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *bbox, limit)

    features = []
    for r in rows:
        props = {c: r[c] for c in extra_cols if c in r}
        props["id"] = r["id"]
        features.append({
            "type": "Feature",
            "id": r["id"],
            "properties": props,
            "geometry": r["geom"],
        })
    return features


async def _lazy_fill(bbox: tuple[float, float, float, float],
                    layer: str, pool) -> None:
    """Kick off a background ingest for an empty bbox. Fire-and-forget."""
    try:
        if layer == "waterways":
            from utils.utility_ingesters.waterways import ingest as _ing
        elif layer == "roads":
            from utils.utility_ingesters.roads import ingest as _ing
        elif layer == "gas":
            from utils.utility_ingesters.gas_pipelines import ingest as _ing
        else:
            return  # fibre has no OSM-driven fill
        summary = await _ing(pool, bbox=bbox)
        log.info("lazy-fill %s: %s", layer, summary)
    except Exception as e:
        log.warning("lazy-fill %s failed: %s", layer, e)


# ─── /api/utilities/waterways ───────────────────────────────────────────

@router.get("/waterways")
async def get_waterways(
    request: Request,
    background: BackgroundTasks,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat (WGS84)"),
    limit: int = Query(2000, ge=1, le=20000),
    lazy_fill: int = Query(1, ge=0, le=1, description="1=ingest bbox if empty"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    bb = _parse_bbox(bbox)
    cols = ["osm_id", "name", "waterway", "width_m", "intermittent"]
    try:
        features = await _line_features(pool, "utility_waterways", cols, bb, limit)
    except Exception as e:
        log.warning("waterways query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    if not features and lazy_fill:
        background.add_task(_lazy_fill, bb, "waterways", pool)

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "layer": "waterways",
        "bbox": list(bb),
    }


# ─── /api/utilities/roads ───────────────────────────────────────────────

@router.get("/roads")
async def get_roads(
    request: Request,
    background: BackgroundTasks,
    bbox: str = Query(...),
    limit: int = Query(5000, ge=1, le=30000),
    access_class: str | None = Query(None, description="strategic|local|site"),
    lazy_fill: int = Query(1, ge=0, le=1),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    bb = _parse_bbox(bbox)
    cols = ["osm_id", "name", "ref", "highway", "access_class", "surface", "maxspeed"]

    sql = f"""
        SELECT id, {", ".join(cols)},
               ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geom
          FROM utility_roads
         WHERE ST_Intersects(
               geom,
               ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
             )
           AND ($5::text IS NULL OR access_class = $5)
         LIMIT $6
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *bb, access_class, limit)
    except Exception as e:
        log.warning("roads query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    features = [{
        "type": "Feature",
        "id": r["id"],
        "properties": {c: r[c] for c in cols} | {"id": r["id"]},
        "geometry": r["geom"],
    } for r in rows]

    if not features and lazy_fill:
        background.add_task(_lazy_fill, bb, "roads", pool)

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "layer": "roads",
        "bbox": list(bb),
    }


# ─── /api/utilities/gas ─────────────────────────────────────────────────

@router.get("/gas")
async def get_gas_pipelines(
    request: Request,
    background: BackgroundTasks,
    bbox: str = Query(...),
    limit: int = Query(2000, ge=1, le=20000),
    lazy_fill: int = Query(1, ge=0, le=1),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    bb = _parse_bbox(bbox)
    cols = ["osm_id", "name", "operator", "substance", "pressure",
            "diameter_mm", "location"]
    try:
        features = await _line_features(pool, "utility_gas_pipelines", cols, bb, limit)
    except Exception as e:
        log.warning("gas query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    if not features and lazy_fill:
        background.add_task(_lazy_fill, bb, "gas", pool)

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "layer": "gas_pipelines",
        "bbox": list(bb),
    }


# ─── /api/utilities/fibre ───────────────────────────────────────────────

@router.get("/fibre")
async def get_fibre_pops(
    request: Request,
    bbox: str = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    carrier: str | None = Query(None, description="openreach|linx|lonap|ixscotland|..."),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    bb = _parse_bbox(bbox)
    sql = """
        SELECT id, external_id, name, carrier, pop_class, city,
               lat, lon, source, notes,
               ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geom
          FROM fibre_pops
         WHERE ST_Intersects(
               geom,
               ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
             )
           AND ($5::text IS NULL OR carrier = $5)
         LIMIT $6
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *bb, carrier, limit)
    except Exception as e:
        log.warning("fibre query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    features = [{
        "type": "Feature",
        "id": r["id"],
        "properties": {
            "external_id": r["external_id"],
            "name": r["name"],
            "carrier": r["carrier"],
            "pop_class": r["pop_class"],
            "city": r["city"],
            "lat": r["lat"],
            "lon": r["lon"],
            "source": r["source"],
            "notes": r["notes"],
        },
        "geometry": r["geom"],
    } for r in rows]

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "layer": "fibre_pops",
        "bbox": list(bb),
        "_stubbed": True,
        "_note": "Seed data (Openreach majors + UK IXs). See utils/utility_ingesters/fibre_pop.py TODO.",
    }
