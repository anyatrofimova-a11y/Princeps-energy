"""
/api/nature/* + /api/heritage/* + /api/bng/* — Natural England + Historic
England + BNG Register endpoints.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool
from utils.substrate.nature_heritage_ingester import (
    ingest_layer_bbox,
    ingest_all_layers_bbox,
)

log = logging.getLogger("princeps.routers.heritage_nature")

router = APIRouter(tags=["nature_heritage"])


# ── MAGIC designations ───────────────────────────────────────────────────
@router.get("/api/nature/{layer}")
async def magic_layer_geojson(
    layer: Literal["aonb", "sssi", "sac", "spa", "ramsar", "ancient_woodland"],
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(5000, ge=1, le=20000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    try:
        parts = [float(p) for p in bbox.split(",")]
        min_lon, min_lat, max_lon, max_lat = parts
    except (ValueError, TypeError):
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")

    sql = """
        SELECT feature_id, name, area_ha, designated_date, condition,
               statutory_basis,
               ST_AsGeoJSON(geom::geometry)::jsonb AS geom
        FROM magic_designations
        WHERE layer = $1
          AND ST_Intersects(
              geom,
              ST_MakeEnvelope($2, $3, $4, $5, 4326)::geography
          )
        LIMIT $6
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, layer, min_lon, min_lat, max_lon, max_lat, limit)
    except Exception as e:
        log.warning("nature %s query failed: %s", layer, e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    features = [
        {
            "type": "Feature",
            "id": r["feature_id"],
            "properties": {
                "layer": layer,
                "name": r["name"],
                "area_ha": float(r["area_ha"]) if r["area_ha"] is not None else None,
                "designated_date": r["designated_date"].isoformat() if r["designated_date"] else None,
                "condition": r["condition"],
                "statutory_basis": r["statutory_basis"],
            },
            "geometry": r["geom"],
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


# ── Historic England — NHLE ───────────────────────────────────────────────
@router.get("/api/heritage/nhle")
async def nhle_geojson(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    entry_class: str | None = Query(None),
    grade: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    try:
        parts = [float(p) for p in bbox.split(",")]
        min_lon, min_lat, max_lon, max_lat = parts
    except (ValueError, TypeError):
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")

    conds = ["ST_Intersects(geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)"]
    args: list[Any] = [min_lon, min_lat, max_lon, max_lat]
    if entry_class:
        conds.append(f"entry_class = ${len(args) + 1}")
        args.append(entry_class)
    if grade:
        conds.append(f"grade = ${len(args) + 1}")
        args.append(grade)
    args.append(limit)

    sql = f"""
        SELECT list_entry_id, entry_class, name, grade, designated_date,
               local_planning_authority,
               ST_AsGeoJSON(geom::geometry)::jsonb AS geom
        FROM nhle_heritage_entries
        WHERE {' AND '.join(conds)}
        LIMIT ${len(args)}
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
    except Exception as e:
        log.warning("nhle query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "error": str(e)}

    features = [
        {
            "type": "Feature",
            "id": r["list_entry_id"],
            "properties": {
                "entry_class": r["entry_class"],
                "name": r["name"],
                "grade": r["grade"],
                "designated_date": r["designated_date"].isoformat() if r["designated_date"] else None,
                "local_planning_authority": r["local_planning_authority"],
            },
            "geometry": r["geom"],
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


# ── BNG Register ─────────────────────────────────────────────────────────
@router.get("/api/bng/register")
async def bng_register(
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat"),
    status: str | None = Query(None),
    lpa: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    conds: list[str] = []
    args: list[Any] = []
    if bbox:
        try:
            parts = [float(p) for p in bbox.split(",")]
            args.extend(parts)
            conds.append("ST_Intersects(geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)")
        except (ValueError, TypeError):
            raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
    if status:
        conds.append(f"status = ${len(args) + 1}")
        args.append(status)
    if lpa:
        conds.append(f"lpa_code = ${len(args) + 1}")
        args.append(lpa)
    args.append(limit)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""

    sql = f"""
        SELECT register_reference, site_name, responsible_body, lpa_code, status,
               habitat_baseline_units, habitat_enhanced_units,
               hedgerow_units, watercourse_units, units_available_for_sale,
               management_start, management_end,
               ST_AsGeoJSON(geom::geometry)::jsonb AS geom
        FROM bng_register_sites
        {where}
        ORDER BY management_start DESC NULLS LAST
        LIMIT ${len(args)}
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
    except Exception as e:
        log.warning("bng register query failed: %s", e)
        return {"sites": [], "error": str(e)}

    return {
        "sites": [
            {
                **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items() if k != "geom"},
                "geometry": r["geom"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ── On-demand ingest trigger ─────────────────────────────────────────────
@router.post("/api/nature/ingest")
async def trigger_ingest(
    layer: Literal["aonb", "sssi", "sac", "spa", "ramsar", "ancient_woodland",
                    "nhle", "bng", "all"] = Query(...),
    bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat (required for all MAGIC + NHLE; ignored for BNG)"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    bbox_tuple: tuple[float, float, float, float] | None = None
    if bbox:
        try:
            parts = [float(p) for p in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox_tuple = tuple(parts)  # type: ignore[assignment]
        except ValueError:
            raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")

    try:
        if layer == "all":
            if not bbox_tuple:
                raise HTTPException(400, "'all' requires bbox")
            result = await ingest_all_layers_bbox(pool, bbox_tuple)
        else:
            result = await ingest_layer_bbox(pool, layer, bbox_tuple)
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        log.error("nature ingest %s failed: %s", layer, e)
        raise HTTPException(500, f"ingest failed: {e}")


@router.get("/api/nature/status")
async def ingest_status(pool=Depends(get_pool)) -> dict[str, Any]:
    sql = """
        SELECT layer, bbox, rows_inserted, rows_updated, status,
               started_at, finished_at, error_message
        FROM nature_heritage_ingest_log
        ORDER BY started_at DESC
        LIMIT 20
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return {"runs": [dict(r) for r in rows]}
    except Exception as e:
        return {"runs": [], "error": str(e)}
