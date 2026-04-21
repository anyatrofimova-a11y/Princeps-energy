"""
/api/constraints/* — GeoJSON bbox endpoints for the constraint layers
consumed by the consultee resolver (migration 0015).

Each endpoint returns a FeatureCollection or HTTP 204 (No Content) when
the bbox is empty / the underlying table has no intersecting rows. Hard
cap is 5 000 features per request to protect the frontend.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.deps import get_pool

log = logging.getLogger("princeps.routers.constraints")

router = APIRouter(prefix="/api/constraints", tags=["constraints"])


MAX_FEATURES = 5_000


# ───────────────────────── Helpers ─────────────────────────────────────

def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        return tuple(parts)  # type: ignore[return-value]
    except ValueError:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")


async def _table_exists(conn: asyncpg.Connection, name: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT to_regclass($1) IS NOT NULL", f"public.{name}",
    ))


def _empty_response() -> Response:
    return Response(status_code=204)


async def _bbox_query_geojson(
    pool: asyncpg.Pool,
    *,
    table: str,
    select_cols: str,
    properties_builder,
    bbox: tuple[float, float, float, float],
    limit: int,
    geom_col: str = "geom",
) -> dict[str, Any] | Response:
    """Run a generic bbox GeoJSON query and return a FeatureCollection.

    ``properties_builder`` is a callable that takes an asyncpg.Record and
    returns the properties dict for its feature.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    sql = f"""
        SELECT {select_cols},
               ST_AsGeoJSON({geom_col}::geometry)::jsonb AS _geom
        FROM {table}
        WHERE ST_Intersects(
            {geom_col},
            ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography
        )
        LIMIT $5
    """
    try:
        async with pool.acquire() as conn:
            if not await _table_exists(conn, table):
                log.info("constraints: table %s missing — 204", table)
                return _empty_response()
            rows = await conn.fetch(sql, min_lon, min_lat, max_lon, max_lat, limit)
    except Exception as e:
        log.warning("constraints query on %s failed: %s", table, e)
        raise HTTPException(500, f"query failed: {e}")

    if not rows:
        return _empty_response()

    features = [
        {
            "type": "Feature",
            "properties": properties_builder(r),
            "geometry": r["_geom"],
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


# ───────────────────────── MoD safeguarding ───────────────────────────

@router.get("/mod")
async def mod_safeguarding(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """MoD DIO safeguarding zones (low-flying, radar, training, explosive)."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="mod_safeguarding_zones",
        select_cols="id, feature_id, zone_type, name, buffer_m, "
                    "consultation_required, statutory_basis",
        properties_builder=lambda r: {
            "feature_id": r["feature_id"],
            "zone_type": r["zone_type"],
            "name": r["name"],
            "buffer_m": r["buffer_m"],
            "consultation_required": r["consultation_required"],
            "statutory_basis": r["statutory_basis"],
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── CAA airspace ───────────────────────────────

@router.get("/caa")
async def caa_airspace(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """CAA aerodrome safeguarding buffers (6 km + 15 km rings)."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="caa_airspace_buffers",
        select_cols="id, feature_id, aerodrome_icao, aerodrome_name, "
                    "zone_class, height_limit_m, buffer_m",
        properties_builder=lambda r: {
            "feature_id": r["feature_id"],
            "icao": r["aerodrome_icao"],
            "aerodrome": r["aerodrome_name"],
            "zone_class": r["zone_class"],
            "height_limit_m": float(r["height_limit_m"]) if r["height_limit_m"] is not None else None,
            "buffer_m": r["buffer_m"],
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── Listed Buildings ───────────────────────────

@router.get("/listed-buildings")
async def listed_buildings(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Historic England listed buildings (NHLE narrow subset, Points)."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="listed_buildings_he",
        select_cols="list_entry_id, name, grade, entry_class, "
                    "designated_date, local_planning_authority",
        properties_builder=lambda r: {
            "list_entry_id": r["list_entry_id"],
            "name": r["name"],
            "grade": r["grade"],
            "entry_class": r["entry_class"],
            "designated_date": r["designated_date"].isoformat()
                if r["designated_date"] else None,
            "lpa": r["local_planning_authority"],
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── Crown Estate ───────────────────────────────

@router.get("/crown-estate")
async def crown_estate(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Crown Estate onshore + foreshore holdings."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="crown_estate_land",
        select_cols="id, feature_id, name, land_class, holding_type, area_ha",
        properties_builder=lambda r: {
            "feature_id": r["feature_id"],
            "name": r["name"],
            "land_class": r["land_class"],
            "holding_type": r["holding_type"],
            "area_ha": float(r["area_ha"]) if r["area_ha"] is not None else None,
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── Ofcom telecom links ────────────────────────

@router.get("/ofcom-links")
async def ofcom_links(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ofcom fixed telecom links (> 1 GHz) as LineStrings."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="ofcom_telecom_links",
        select_cols="id, feature_id, operator, service_class, "
                    "frequency_mhz_tx, frequency_mhz_rx, bandwidth_mhz, "
                    "licence_expiry",
        properties_builder=lambda r: {
            "feature_id": r["feature_id"],
            "operator": r["operator"],
            "service_class": r["service_class"],
            "frequency_mhz_tx": float(r["frequency_mhz_tx"]) if r["frequency_mhz_tx"] is not None else None,
            "frequency_mhz_rx": float(r["frequency_mhz_rx"]) if r["frequency_mhz_rx"] is not None else None,
            "bandwidth_mhz": float(r["bandwidth_mhz"]) if r["bandwidth_mhz"] is not None else None,
            "licence_expiry": r["licence_expiry"].isoformat()
                if r["licence_expiry"] else None,
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── Marine Plan Areas ──────────────────────────

@router.get("/marine-plan")
async def marine_plan(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """MMO adopted marine plan areas."""
    b = _parse_bbox(bbox)
    return await _bbox_query_geojson(
        pool,
        table="marine_plan_areas",
        select_cols="id, feature_id, plan_name, plan_code, tier, adopted_date",
        properties_builder=lambda r: {
            "feature_id": r["feature_id"],
            "plan_name": r["plan_name"],
            "plan_code": r["plan_code"],
            "tier": r["tier"],
            "adopted_date": r["adopted_date"].isoformat()
                if r["adopted_date"] else None,
        },
        bbox=b,
        limit=limit,
    )


# ───────────────────────── Ingestion status ───────────────────────────

@router.get("/status")
async def ingest_status(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """Last 20 ingestion runs across all constraint layers."""
    try:
        async with pool.acquire() as conn:
            if not await _table_exists(conn, "constraint_layers_ingest_log"):
                return {"runs": []}
            rows = await conn.fetch(
                "SELECT id, layer, bbox, rows_inserted, rows_updated, "
                "       rows_failed, status, started_at, finished_at, "
                "       error_message "
                "FROM constraint_layers_ingest_log "
                "ORDER BY started_at DESC LIMIT 20"
            )
        return {"runs": [dict(r) for r in rows]}
    except Exception as e:
        return {"runs": [], "error": str(e)}
