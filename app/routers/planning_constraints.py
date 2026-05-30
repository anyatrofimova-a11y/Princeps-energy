"""
/api/planning-data/* — planning.data.gov.uk Top-21 designations (Task #17).

Endpoints
~~~~~~~~~
* ``GET /api/planning-data/constraints`` — point + radius proximity check
* ``GET /api/planning-data/overlap``     — site polygon overlap check
* ``GET /api/planning-data/datasets``    — registered slugs + severity tiering
* ``GET /api/planning-data/designations.mvt`` — vector tiles for the map layer

Note: the older /api/planning/* namespace is owned by app/routers/planning_ml.py
(ML-driven approval predictor). This module sits at /api/planning-data/ so the
two surfaces never collide.

All geometry sits in EPSG:27700 (OSGB36) in the database; the spatial
queries always reproject inbound lat/lon or WKT to 27700 in a CTE. The
MVT tiler reprojects on-the-fly to 3857.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.deps import get_pool
from utils.planning_data_uk import SEVERITY, TOP21

log = logging.getLogger("princeps.routers.planning_constraints")

router = APIRouter(prefix="/api/planning-data", tags=["planning_constraints"])

OGL_FOOTER = "© Crown copyright · Open Government Licence v3.0"


# ---------------------------------------------------------------------------
# /api/planning/datasets
# ---------------------------------------------------------------------------

_refresh_state: dict[str, Any] = {"running": False, "last_result": None, "started_at": None}


async def _do_refresh(pool: asyncpg.Pool, slug: Optional[str]) -> None:
    """Background runner — clears etags + re-fetches without blocking the request."""
    import httpx
    from scripts.refresh_planning_data_uk import refresh_all, refresh_slug, USER_AGENT
    import datetime as _dt

    _refresh_state["running"] = True
    _refresh_state["started_at"] = _dt.datetime.utcnow().isoformat()
    try:
        async with pool.acquire() as conn:
            if slug:
                await conn.execute(
                    "DELETE FROM planning_designations_etag WHERE dataset = $1", slug,
                )
                await conn.execute(
                    "DELETE FROM planning_designations WHERE dataset = $1", slug,
                )
            else:
                await conn.execute("DELETE FROM planning_designations_etag")
                await conn.execute("DELETE FROM planning_designations")

        if slug:
            headers = {"User-Agent": USER_AGENT}
            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                result = await refresh_slug(pool, client, slug, force=True)
            _refresh_state["last_result"] = {"slug": slug, "result": result}
        else:
            result = await refresh_all(pool, slugs=None, force=True)
            _refresh_state["last_result"] = {"result": result}
    except Exception as exc:
        log.exception("force-refresh failed")
        _refresh_state["last_result"] = {"status": "error", "error": str(exc)}
    finally:
        _refresh_state["running"] = False


@router.post("/force-refresh")
async def force_refresh(
    request: Request,
    slug: Optional[str] = Query(None, description="Single dataset slug; omit to refresh all 21"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Kick off a background refresh — returns immediately. Poll
    /force-refresh-status to see progress + final counts.
    """
    if _refresh_state["running"]:
        return {"status": "already_running", "started_at": _refresh_state["started_at"]}
    import asyncio
    asyncio.create_task(_do_refresh(pool, slug))
    return {"status": "scheduled", "slug": slug or "all_21"}


@router.get("/force-refresh-status")
async def force_refresh_status() -> dict[str, Any]:
    return {
        "running": _refresh_state["running"],
        "started_at": _refresh_state["started_at"],
        "last_result": _refresh_state["last_result"],
    }


@router.get("/datasets")
async def list_datasets(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """Return the registered slug list with severity tiering and last-refresh."""
    by_slug: dict[str, dict[str, Any]] = {
        slug: {
            "slug": slug,
            "severity": SEVERITY.get(slug, "MEDIUM"),
            "entity_count": 0,
            "last_refresh": None,
            "rows_loaded": None,
            "status": None,
            "source_url": f"https://www.planning.data.gov.uk/dataset/{slug}",
        }
        for slug in TOP21
    }
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT dataset, COUNT(*) AS n
                FROM planning_designations
                GROUP BY dataset
                """
            )
            for r in rows:
                slug = r["dataset"]
                if slug in by_slug:
                    by_slug[slug]["entity_count"] = int(r["n"])
            etag_rows = await conn.fetch(
                """
                SELECT dataset, last_refresh, rows_loaded, status
                FROM planning_designations_etag
                """
            )
            for r in etag_rows:
                slug = r["dataset"]
                if slug in by_slug:
                    by_slug[slug].update({
                        "last_refresh": r["last_refresh"].isoformat()
                            if r["last_refresh"] else None,
                        "rows_loaded": r["rows_loaded"],
                        "status": r["status"],
                    })
    except Exception as exc:
        log.warning("datasets summary failed: %s", exc)
    return {
        "datasets": list(by_slug.values()),
        "attribution": OGL_FOOTER,
    }


# ---------------------------------------------------------------------------
# /api/planning/constraints — proximity radius around a lat/lon
# ---------------------------------------------------------------------------

@router.get("/constraints")
async def constraints_at_point(
    lat: float = Query(..., ge=49.0, le=61.0),
    lon: float = Query(..., ge=-9.0, le=2.5),
    radius_m: int = Query(500, ge=10, le=10_000),
    datasets: Optional[str] = Query(
        None,
        description="Comma-separated slug list (default: all Top-21)",
    ),
    limit: int = Query(500, ge=1, le=2_000),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return designations within `radius_m` of a (lat, lon) WGS84 point.

    Always reprojects the search point to EPSG:27700 in a CTE — never
    casts the 27700 column to ::geography (per Princeps spatial rules).
    """
    slugs = _parse_slugs(datasets)
    sql = """
    WITH q AS (
        SELECT ST_Transform(
                   ST_SetSRID(ST_MakePoint($1, $2), 4326),
                   27700
               ) AS pt
    )
    SELECT
        d.entity_id,
        d.dataset,
        d.reference,
        d.name,
        d.organisation_entity,
        d.entry_date,
        d.source_url,
        ROUND(ST_Distance(d.geom, q.pt)::numeric, 1) AS distance_m,
        ST_AsGeoJSON(
            ST_Transform(d.geom, 4326)
        )::jsonb AS geometry
    FROM planning_designations d, q
    WHERE d.dataset = ANY($3::text[])
      AND ST_DWithin(d.geom, q.pt, $4)
    ORDER BY ST_Distance(d.geom, q.pt) ASC
    LIMIT $5
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, lon, lat, slugs, radius_m, limit)
    except asyncpg.UndefinedTableError:
        # Table not yet created (cold start / refresher hasn't run).
        return {"hits": [], "by_severity": {"CRITICAL": [], "HIGH": [], "MEDIUM": []}, "count": 0, "attribution": OGL_FOOTER}
    except Exception as exc:
        log.warning("constraints query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"constraints query failed: {exc}")

    hits = []
    by_sev: dict[str, list[dict]] = {"CRITICAL": [], "HIGH": [], "MEDIUM": []}
    for r in rows:
        sev = SEVERITY.get(r["dataset"], "MEDIUM")
        hit = {
            "entity_id": r["entity_id"],
            "dataset": r["dataset"],
            "reference": r["reference"],
            "name": r["name"],
            "organisation_entity": r["organisation_entity"],
            "entry_date": r["entry_date"].isoformat() if r["entry_date"] else None,
            "severity": sev,
            "distance_m": float(r["distance_m"]) if r["distance_m"] is not None else None,
            "source_url": r["source_url"],
            "geometry": r["geometry"],
        }
        hits.append(hit)
        by_sev.setdefault(sev, []).append(hit)

    return {
        "point": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "datasets": slugs,
        "count": len(hits),
        "hits": hits,
        "by_severity": by_sev,
        "attribution": OGL_FOOTER,
    }


# ---------------------------------------------------------------------------
# /api/planning/overlap — explicit polygon overlap check
# ---------------------------------------------------------------------------

@router.get("/overlap")
async def overlap_query(
    wkt: str = Query(..., description="Site polygon WKT in EPSG:4326"),
    datasets: Optional[str] = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return designations that overlap the supplied WKT polygon (EPSG:4326).

    Returns per-hit ``overlap_m2`` and ``overlap_pct`` so the agent verdict
    can cite e.g. "SSSI 'Foo Bar' overlaps site by 1,452 m² (3.1%)".
    """
    slugs = _parse_slugs(datasets)
    sql = """
    WITH q AS (
        SELECT ST_Transform(
                   ST_SetSRID(ST_GeomFromText($1), 4326),
                   27700
               ) AS poly
    ),
    qa AS (
        SELECT poly, GREATEST(ST_Area(poly), 1e-6) AS poly_area FROM q
    )
    SELECT
        d.entity_id,
        d.dataset,
        d.reference,
        d.name,
        d.organisation_entity,
        d.entry_date,
        d.source_url,
        ROUND(ST_Area(ST_Intersection(d.geom, qa.poly))::numeric, 2) AS overlap_m2,
        ROUND(
            100.0 * ST_Area(ST_Intersection(d.geom, qa.poly))
            / qa.poly_area
        ::numeric, 3) AS overlap_pct
    FROM planning_designations d, qa
    WHERE d.dataset = ANY($2::text[])
      AND ST_Intersects(d.geom, qa.poly)
    ORDER BY ST_Area(ST_Intersection(d.geom, qa.poly)) DESC
    LIMIT 2000
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, wkt, slugs)
    except asyncpg.PostgresSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"invalid WKT: {exc}")
    except asyncpg.UndefinedTableError:
        return {"hits": [], "count": 0, "attribution": OGL_FOOTER}
    except Exception as exc:
        log.warning("overlap query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"overlap query failed: {exc}")

    hits = []
    for r in rows:
        sev = SEVERITY.get(r["dataset"], "MEDIUM")
        hits.append({
            "entity_id": r["entity_id"],
            "dataset": r["dataset"],
            "severity": sev,
            "reference": r["reference"],
            "name": r["name"],
            "organisation_entity": r["organisation_entity"],
            "entry_date": r["entry_date"].isoformat() if r["entry_date"] else None,
            "overlap_m2": float(r["overlap_m2"]) if r["overlap_m2"] is not None else 0.0,
            "overlap_pct": float(r["overlap_pct"]) if r["overlap_pct"] is not None else 0.0,
            "source_url": r["source_url"],
        })
    return {"count": len(hits), "hits": hits, "attribution": OGL_FOOTER}


# ---------------------------------------------------------------------------
# /api/planning/designations.mvt — Mapbox Vector Tile
# ---------------------------------------------------------------------------

@router.get("/designations.mvt")
async def designations_mvt(
    z: int = Query(..., ge=0, le=22),
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    datasets: Optional[str] = Query(
        None, description="Comma-separated slug filter (default: all Top-21)"
    ),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Response:
    """Serve a Mapbox Vector Tile of planning designations.

    All geometry is reprojected to EPSG:3857 inside the tile envelope via
    ``ST_AsMVTGeom``. Empty tiles return 204 so the frontend skips them.
    """
    max_index = (1 << z) - 1
    if x > max_index or y > max_index:
        raise HTTPException(status_code=400, detail="tile index out of range")

    slugs = _parse_slugs(datasets)

    min_x, min_y, max_x, max_y = _tile_bounds_3857(z, x, y)
    sql = """
    WITH tile AS (
        SELECT ST_MakeEnvelope($1, $2, $3, $4, 3857) AS env
    ),
    rows AS (
        SELECT
            d.entity_id,
            d.dataset,
            d.name,
            d.reference,
            d.source_url,
            ST_AsMVTGeom(
                ST_Transform(d.geom, 3857),
                (SELECT env FROM tile),
                4096, 64, true
            ) AS mvt_geom
        FROM planning_designations d, tile
        WHERE d.dataset = ANY($5::text[])
          AND ST_Transform(d.geom, 3857) && (SELECT env FROM tile)
    )
    SELECT ST_AsMVT(rows.*, 'planning_designations', 4096, 'mvt_geom')
    FROM rows
    WHERE mvt_geom IS NOT NULL
    """
    try:
        async with pool.acquire() as conn:
            tile_bytes = await conn.fetchval(
                sql, min_x, min_y, max_x, max_y, slugs,
            )
    except asyncpg.UndefinedTableError:
        return Response(status_code=204)
    except Exception as exc:
        log.warning("MVT generation failed z=%d/%d/%d: %s", z, x, y, exc)
        return Response(status_code=204)

    if not tile_bytes:
        return Response(status_code=204)

    return Response(
        content=bytes(tile_bytes),
        media_type="application/vnd.mapbox-vector-tile",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
            "X-OGL-Attribution": OGL_FOOTER,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_slugs(raw: Optional[str]) -> list[str]:
    """Validate the optional ?datasets=a,b,c query, defaulting to TOP21."""
    if not raw:
        return list(TOP21)
    slugs = [s.strip() for s in raw.split(",") if s.strip()]
    bad = [s for s in slugs if s not in TOP21]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"unknown datasets: {','.join(bad)}",
        )
    return slugs


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Slippy tile -> EPSG:3857 envelope (web Mercator metres)."""
    n = 2 ** z
    earth = 20037508.342789244
    def lon_to_x(lon: float) -> float:
        return lon * earth / 180.0
    def lat_to_y(lat: float) -> float:
        rad = math.radians(lat)
        return math.log(math.tan(math.pi / 4 + rad / 2)) * earth / math.pi
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (lon_to_x(lon_w), lat_to_y(lat_s), lon_to_x(lon_e), lat_to_y(lat_n))
