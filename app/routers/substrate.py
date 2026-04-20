"""Substrate routes — MVT tiles, LiDAR rasters, admin ingestion.

Routes:
  * ``GET  /api/substrate/tiles/{layer}/{z}/{x}/{y}.mvt``
  * ``GET  /api/substrate/lidar/{tile_id}/dtm.tif``
  * ``GET  /api/substrate/lidar/{tile_id}/dsm.tif``
  * ``POST /api/substrate/fetch``  (admin — triggers ingestion for a bbox)
  * ``POST /api/substrate/refresh`` (admin — rebuilds materialised views)

Graceful degradation:
  * Missing OS_DATA_HUB_KEY → MVT still serves for any ingested data;
    empty tiles return 204 No Content.
  * Missing raster file → 204.
  * Unknown layer → 404.

All MVT tiles set ``Cache-Control: public, max-age=86400`` so CDNs cache
them for a day.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

log = logging.getLogger("princeps.substrate")
router = APIRouter(prefix="/api/substrate", tags=["substrate"])


# ---------------------------------------------------------------------------
# MVT tiles
# ---------------------------------------------------------------------------

@router.get("/tiles/{layer}/{z}/{x}/{y}.mvt")
async def get_mvt_tile(layer: str, z: int, x: int, y: int, request: Request):
    """Serve a Mapbox Vector Tile for a substrate layer.

    ``layer`` ∈ {buildings, roads, water, woodland, pylons, overhead_lines}.
    Empty tiles return 204; unknown layers return 404.
    """
    from utils.substrate.tiler import LAYERS, generate_tile

    if layer not in LAYERS:
        raise HTTPException(status_code=404, detail=f"unknown substrate layer: {layer}")

    # Basic sanity checks on z/x/y to avoid runaway queries.
    if z < 0 or z > 22:
        raise HTTPException(status_code=400, detail="zoom out of range")
    max_index = (1 << z) - 1
    if x < 0 or x > max_index or y < 0 or y > max_index:
        raise HTTPException(status_code=400, detail="tile index out of range")

    pool = request.app.state.pool
    tile = await generate_tile(pool, layer, z, x, y)
    if tile is None:
        # MV missing or SQL error — hide from frontend but don't 500.
        return Response(status_code=204)
    if not tile:
        # Empty tile — 204 so the frontend can skip it without logging an error.
        return Response(status_code=204)

    return Response(
        content=tile,
        media_type="application/vnd.mapbox-vector-tile",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ---------------------------------------------------------------------------
# LiDAR rasters
# ---------------------------------------------------------------------------

async def _resolve_lidar_path(pool, tile_id: str, product: str) -> Optional[str]:
    """Return an absolute path to a DTM/DSM for ``tile_id`` or None."""
    from utils.substrate.ea_lidar_ingester import get_tile_by_id

    meta = await get_tile_by_id(pool, tile_id)
    if not meta:
        return None
    path = meta.get(f"{product.lower()}_path")
    if not path:
        return None
    p = pathlib.Path(path)
    if not p.exists() or not p.is_file():
        return None
    return str(p)


@router.get("/lidar/{tile_id}/dtm.tif")
async def get_lidar_dtm(tile_id: str, request: Request):
    """Return the raw DTM GeoTIFF for a 1 km OSGB tile."""
    pool = request.app.state.pool
    path = await _resolve_lidar_path(pool, tile_id, "dtm")
    if not path:
        return Response(status_code=204)
    return FileResponse(
        path=path,
        media_type="image/tiff",
        filename=f"{tile_id}_DTM.tif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/lidar/{tile_id}/dsm.tif")
async def get_lidar_dsm(tile_id: str, request: Request):
    """Return the raw DSM GeoTIFF for a 1 km OSGB tile."""
    pool = request.app.state.pool
    path = await _resolve_lidar_path(pool, tile_id, "dsm")
    if not path:
        return Response(status_code=204)
    return FileResponse(
        path=path,
        media_type="image/tiff",
        filename=f"{tile_id}_DSM.tif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/lidar/index")
async def lidar_index(
    request: Request,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
):
    """List LiDAR tiles currently cached whose bbox intersects the supplied bbox."""
    pool = request.app.state.pool
    wkt = (
        f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT tile_id, dtm_path, dsm_path, resolution_m,
                   ST_AsGeoJSON(ST_Transform(bbox, 4326)) AS bbox_geojson
            FROM substrate_lidar_tiles
            WHERE ST_Intersects(
                bbox,
                ST_Transform(ST_GeomFromText($1, 4326), 27700)
            )
            ORDER BY tile_id
            LIMIT 500
        """, wkt)
    return {
        "count": len(rows),
        "tiles": [
            {
                "tile_id": r["tile_id"],
                "has_dtm": bool(r["dtm_path"]),
                "has_dsm": bool(r["dsm_path"]),
                "resolution_m": r["resolution_m"],
                "bbox": r["bbox_geojson"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Admin ingestion
# ---------------------------------------------------------------------------

class SubstrateFetchRequest(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    sources: list[str] = ["osmm", "lidar", "osm_pylons"]
    force_refresh: bool = False


def _check_admin(request: Request) -> None:
    """Minimal admin guard — matches other routers' pattern.

    Accepts either an ``X-Admin-Token`` header matching ``ADMIN_TOKEN`` env,
    or a local/dev environment where ``ADMIN_TOKEN`` is unset.
    """
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        return  # dev mode — permissive
    supplied = request.headers.get("x-admin-token") or request.headers.get("X-Admin-Token")
    if supplied != expected:
        raise HTTPException(status_code=403, detail="admin token required")


@router.post("/fetch")
async def substrate_fetch(req: SubstrateFetchRequest, request: Request):
    """Trigger substrate ingestion for a bounding box.

    Runs each requested source. Returns per-source counts.
    """
    _check_admin(request)
    pool = request.app.state.pool
    bbox = (req.min_lon, req.min_lat, req.max_lon, req.max_lat)
    out: dict = {"bbox": bbox, "sources": {}}

    if "osmm" in req.sources:
        try:
            from utils.substrate.os_mastermap_ingester import fetch_topo
            tile_results = await fetch_topo(bbox, pool=pool, force_refresh=req.force_refresh)
            out["sources"]["osmm"] = {
                "tiles": len(tile_results),
                "buildings": sum(t.buildings for t in tile_results),
                "roads":     sum(t.roads for t in tile_results),
                "water":     sum(t.water for t in tile_results),
                "woodland":  sum(t.woodland for t in tile_results),
                "source":    tile_results[0].source if tile_results else None,
            }
        except Exception as exc:
            log.exception("OSMM ingest failed")
            out["sources"]["osmm"] = {"error": str(exc)}

    if "lidar" in req.sources:
        try:
            from utils.substrate.ea_lidar_ingester import fetch_lidar
            tile_results = await fetch_lidar(bbox, pool=pool, force_refresh=req.force_refresh)
            out["sources"]["lidar"] = {
                "tiles": len(tile_results),
                "dtm_downloaded": sum(1 for t in tile_results if t.dtm_path and not t.cached),
                "dsm_downloaded": sum(1 for t in tile_results if t.dsm_path and not t.cached),
                "cached": sum(1 for t in tile_results if t.cached),
                "errors": sum(1 for t in tile_results if t.error),
            }
        except Exception as exc:
            log.exception("LiDAR ingest failed")
            out["sources"]["lidar"] = {"error": str(exc)}

    if "osm_pylons" in req.sources:
        try:
            from utils.substrate.osm_pylon_ingester import fetch_pylons_and_lines
            res = await fetch_pylons_and_lines(bbox, pool)
            out["sources"]["osm_pylons"] = {
                "pylons": res.pylons,
                "overhead_lines": res.overhead_lines,
                "error": res.error,
            }
        except Exception as exc:
            log.exception("OSM pylon ingest failed")
            out["sources"]["osm_pylons"] = {"error": str(exc)}

    return out


@router.post("/refresh")
async def substrate_refresh(request: Request):
    """Rebuild the materialised views that back the MVT tiler.

    Run nightly from a scheduler; admin-gated so it isn't a DOS vector.
    """
    _check_admin(request)
    from utils.substrate.tiler import refresh_materialized_views

    pool = request.app.state.pool
    status = await refresh_materialized_views(pool)
    return {"status": status}


# ---------------------------------------------------------------------------
# Status endpoint — frontend checks whether to show substrate layers
# ---------------------------------------------------------------------------

@router.get("/status")
async def substrate_status(request: Request):
    """Summary of substrate data coverage — counts per table."""
    pool = request.app.state.pool
    counts: dict[str, int] = {}
    tables = [
        "substrate_buildings", "substrate_roads", "substrate_water",
        "substrate_woodland", "substrate_pylons", "substrate_overhead_lines",
        "substrate_lidar_tiles",
    ]
    async with pool.acquire() as conn:
        for t in tables:
            try:
                counts[t] = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
            except Exception:
                counts[t] = 0
    return {
        "counts": counts,
        "os_data_hub_key_set": bool(os.environ.get("OS_DATA_HUB_KEY") or os.environ.get("VITE_OS_API_KEY")),
    }
