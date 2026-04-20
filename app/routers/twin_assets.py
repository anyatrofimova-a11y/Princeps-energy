"""Twin asset-domain GeoJSON endpoints.

Serves per-asset-type GeoJSON FeatureCollections scoped to a map viewport
bbox so the deck.gl twin never has to ship the full REPD (~14k rows) to
the browser.

Covered asset types:
  - solar (REPD tech_category = 'solar')
  - bess  (REPD tech_category = 'bess' + projects where technology in ('bess','battery'))
  - dc    (projects table, technology in ('dc','datacentre') or metadata['workload_type'])
  - wind  (REPD tech_category = 'wind', with onshore/offshore filter via mounting)
  - ev    (currently not ingested — returns empty with note flag)
  - hydrogen (gu_hydrogen_opportunities + REPD 'other' tech matching)

All endpoints accept bbox=west,south,east,north (WGS84). Status colouring
is normalised server-side into a `status_bucket` field so the frontend
palette stays consistent across REPD / projects / TEC origins.
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query, HTTPException

from app.deps import get_pool

log = logging.getLogger("princeps.twin_assets")

router = APIRouter(tags=["twin-assets"])

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_STATUS_BUCKETS = {
    "operational":            "operational",
    "under construction":     "under_construction",
    "approved":               "consented",
    "planning permission granted": "consented",
    "revised":                "consented",
    "planning application submitted": "application_submitted",
    "submitted":              "application_submitted",
    "appeal lodged":          "application_submitted",
    "planning permission refused": "refused",
    "appeal refused":         "refused",
    "refused":                "refused",
    "planning application withdrawn": "withdrawn",
    "withdrawn":              "withdrawn",
    "abandoned":              "withdrawn",
    "decommissioned":         "decommissioned",
    "planning permission expired": "pre_planning",
}


def _bucket(status: str | None) -> str:
    if not status:
        return "pre_planning"
    s = status.lower().strip()
    if s in _STATUS_BUCKETS:
        return _STATUS_BUCKETS[s]
    for key, bucket in _STATUS_BUCKETS.items():
        if key in s:
            return bucket
    return "pre_planning"


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("need 4 comma-separated floats")
        west, south, east, north = parts
        if not (-180 <= west <= 180 and -180 <= east <= 180 and
                -90 <= south <= 90 and -90 <= north <= 90):
            raise ValueError("out of WGS84 range")
        if west >= east or south >= north:
            raise ValueError("bbox must be west<east, south<north")
        return west, south, east, north
    except Exception as exc:
        raise HTTPException(400, f"bad bbox '{bbox}': {exc}")


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


async def _repd_features(conn, tech_category: str, bbox: tuple, limit: int,
                         extra_where: str = "") -> list[dict]:
    west, south, east, north = bbox
    sql = f"""
        SELECT repd_id, site_name, developer, operator, tech_category,
               technology, capacity_mw, status, mounting_type, height_m,
               turbines, battery_mwh, region, county, country,
               ST_X(ST_Transform(geometry, 4326)) AS lon,
               ST_Y(ST_Transform(geometry, 4326)) AS lat
          FROM repd_projects
         WHERE tech_category = $1
           AND geometry IS NOT NULL
           AND ST_Intersects(
                 ST_Transform(geometry, 4326),
                 ST_MakeEnvelope($2, $3, $4, $5, 4326))
           {extra_where}
         ORDER BY capacity_mw DESC NULLS LAST
         LIMIT {int(limit)}
    """
    rows = await conn.fetch(sql, tech_category, west, south, east, north)
    feats = []
    for r in rows:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "id": r["repd_id"],
                "source": "repd",
                "name": r["site_name"],
                "developer": r["developer"] or r["operator"],
                "technology": r["technology"] or r["tech_category"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                "status": r["status"],
                "status_bucket": _bucket(r["status"]),
                "mounting": r["mounting_type"],
                "height_m": float(r["height_m"]) if r["height_m"] is not None else None,
                "turbines": r["turbines"],
                "battery_mwh": float(r["battery_mwh"]) if r["battery_mwh"] is not None else None,
                "region": r["region"],
                "county": r["county"],
                "country": r["country"],
            },
        })
    return feats


# ---------------------------------------------------------------------------
# Solar
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/solar")
async def assets_solar(
    bbox: str = Query(..., description="west,south,east,north (WGS84)"),
    min_mw: float = Query(0.0, ge=0.0),
    limit: int = Query(2000, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    b = _parse_bbox(bbox)
    extra = f"AND COALESCE(capacity_mw, 0) >= {float(min_mw)}"
    async with pool.acquire() as conn:
        feats = await _repd_features(conn, "solar", b, limit, extra)
    return _fc(feats)


# ---------------------------------------------------------------------------
# BESS
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/bess")
async def assets_bess(
    bbox: str = Query(...),
    min_mw: float = Query(0.0, ge=0.0),
    limit: int = Query(2000, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    b = _parse_bbox(bbox)
    west, south, east, north = b
    async with pool.acquire() as conn:
        extra = f"AND COALESCE(capacity_mw, 0) >= {float(min_mw)}"
        feats = await _repd_features(conn, "bess", b, limit, extra)
        # Also merge in user-created projects tagged as bess/battery
        rows = await conn.fetch("""
            SELECT project_id::text AS id, name, technology, capacity_mw, stage, verdict,
                   lat, lon, metadata
              FROM projects
             WHERE lat IS NOT NULL AND lon IS NOT NULL
               AND lat BETWEEN $2 AND $4 AND lon BETWEEN $1 AND $3
               AND (technology ILIKE 'bess' OR technology ILIKE 'battery')
             LIMIT 500
        """, west, south, east, north)
        for r in rows:
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                "properties": {
                    "id": r["id"],
                    "source": "project",
                    "name": r["name"],
                    "technology": r["technology"],
                    "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                    "status": r["stage"],
                    "status_bucket": _bucket(r["stage"]),
                    "verdict": r["verdict"],
                },
            })
    return _fc(feats)


# ---------------------------------------------------------------------------
# Data centres
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/dc")
async def assets_dc(
    bbox: str = Query(...),
    limit: int = Query(1000, ge=1, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    west, south, east, north = _parse_bbox(bbox)
    feats: list[dict] = []
    async with pool.acquire() as conn:
        # 1) User projects tagged DC
        rows = await conn.fetch("""
            SELECT project_id::text AS id, name, technology, capacity_mw, stage,
                   verdict, lat, lon, metadata
              FROM projects
             WHERE lat IS NOT NULL AND lon IS NOT NULL
               AND lat BETWEEN $2 AND $4 AND lon BETWEEN $1 AND $3
               AND (technology ILIKE 'dc' OR technology ILIKE '%datacentre%'
                    OR technology ILIKE '%data centre%' OR technology ILIKE '%data_center%')
             LIMIT $5
        """, west, south, east, north, limit)
        for r in rows:
            md = r["metadata"] or {}
            it_load = md.get("it_load_mw") or md.get("it_mw") or r["capacity_mw"]
            pue = md.get("pue") or md.get("pue_target")
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                "properties": {
                    "id": r["id"],
                    "source": "project",
                    "name": r["name"],
                    "it_load_mw": float(it_load) if it_load is not None else None,
                    "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                    "pue": float(pue) if pue is not None else None,
                    "status": r["stage"],
                    "status_bucket": _bucket(r["stage"]),
                    "verdict": r["verdict"],
                    "workload_type": md.get("workload_type"),
                },
            })

        # 2) OSM-derived dc_facilities (points) as fallback reference
        try:
            osm_rows = await conn.fetch("""
                SELECT facility_id, osm_id, name, operator, lat, lon, tags
                  FROM dc_facilities
                 WHERE lat BETWEEN $2 AND $4 AND lon BETWEEN $1 AND $3
                 LIMIT $5
            """, west, south, east, north, limit)
            for r in osm_rows:
                tags = r["tags"] or {}
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                    "properties": {
                        "id": f"osm-{r['osm_id']}",
                        "source": "osm",
                        "name": r["name"] or tags.get("name") or "Data centre",
                        "operator": r["operator"] or tags.get("operator"),
                        "status_bucket": "operational",
                        "it_load_mw": None,
                    },
                })
        except Exception as exc:  # pragma: no cover — table optional
            log.debug("dc_facilities merge skipped: %s", exc)

    return _fc(feats)


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/wind")
async def assets_wind(
    bbox: str = Query(...),
    offshore: str = Query("all", pattern="^(all|onshore|offshore)$"),
    min_mw: float = Query(0.0, ge=0.0),
    limit: int = Query(2500, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    b = _parse_bbox(bbox)
    extras = [f"AND COALESCE(capacity_mw, 0) >= {float(min_mw)}"]
    if offshore == "onshore":
        extras.append("AND (mounting_type IS NULL OR mounting_type NOT ILIKE '%offshore%')"
                      " AND (technology IS NULL OR technology NOT ILIKE '%offshore%')")
    elif offshore == "offshore":
        extras.append("AND (mounting_type ILIKE '%offshore%' OR technology ILIKE '%offshore%')")
    async with pool.acquire() as conn:
        feats = await _repd_features(conn, "wind", b, limit, " ".join(extras))
        for f in feats:
            tech = (f["properties"].get("technology") or "").lower()
            mounting = (f["properties"].get("mounting") or "").lower()
            f["properties"]["is_offshore"] = "offshore" in tech or "offshore" in mounting
    return _fc(feats)


# ---------------------------------------------------------------------------
# EV charging (currently no ingest — empty with note)
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/ev")
async def assets_ev(
    bbox: str = Query(...),
    limit: int = Query(2000, ge=1, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    _parse_bbox(bbox)  # validate
    # No table wired yet — return empty FC plus a note flag the frontend
    # renders as a "data not ingested" chip.
    resp = _fc([])
    resp["note"] = "EV charging not ingested — wire OSM amenity=charging_station to populate"
    resp["available"] = False
    return resp


# ---------------------------------------------------------------------------
# Hydrogen / electrolyser
# ---------------------------------------------------------------------------
@router.get("/api/twin/assets/hydrogen")
async def assets_hydrogen(
    bbox: str = Query(...),
    limit: int = Query(1000, ge=1, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    b = _parse_bbox(bbox)
    west, south, east, north = b
    feats: list[dict] = []
    async with pool.acquire() as conn:
        # gu_hydrogen_opportunities (colocation + electrolyser sizing)
        try:
            rows = await conn.fetch("""
                SELECT project_id, lat, lon, electrolyser_mw, annual_h2_tonnes,
                       annual_revenue_gbp, wobbe_ok, gas_grid_distance_km, curtailment_pct
                  FROM gu_hydrogen_opportunities
                 WHERE lat IS NOT NULL AND lon IS NOT NULL
                   AND lat BETWEEN $2 AND $4 AND lon BETWEEN $1 AND $3
                 LIMIT $5
            """, west, south, east, north, limit)
            for r in rows:
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                    "properties": {
                        "id": r["project_id"],
                        "source": "gu_hydrogen",
                        "name": f"Electrolyser @ {r['project_id']}",
                        "electrolyser_mw": float(r["electrolyser_mw"]) if r["electrolyser_mw"] is not None else None,
                        "annual_h2_tonnes": float(r["annual_h2_tonnes"]) if r["annual_h2_tonnes"] is not None else None,
                        "curtailment_pct": float(r["curtailment_pct"]) if r["curtailment_pct"] is not None else None,
                        "wobbe_ok": r["wobbe_ok"],
                        "gas_grid_km": float(r["gas_grid_distance_km"]) if r["gas_grid_distance_km"] is not None else None,
                        "status_bucket": "pre_planning",
                    },
                })
        except Exception as exc:
            log.debug("gu_hydrogen merge skipped: %s", exc)

        # REPD "other" tech where technology mentions hydrogen / fuel cell
        try:
            rows = await conn.fetch("""
                SELECT repd_id, site_name, operator, developer, technology, capacity_mw,
                       status,
                       ST_X(ST_Transform(geometry, 4326)) AS lon,
                       ST_Y(ST_Transform(geometry, 4326)) AS lat
                  FROM repd_projects
                 WHERE geometry IS NOT NULL
                   AND tech_category = 'other'
                   AND (technology ILIKE '%hydrogen%' OR technology ILIKE '%electrolys%'
                        OR technology ILIKE '%fuel cell%')
                   AND ST_Intersects(ST_Transform(geometry, 4326),
                                     ST_MakeEnvelope($1, $2, $3, $4, 4326))
                 LIMIT $5
            """, west, south, east, north, limit)
            for r in rows:
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                    "properties": {
                        "id": r["repd_id"],
                        "source": "repd",
                        "name": r["site_name"],
                        "developer": r["developer"] or r["operator"],
                        "technology": r["technology"],
                        "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                        "status": r["status"],
                        "status_bucket": _bucket(r["status"]),
                    },
                })
        except Exception as exc:
            log.debug("repd hydrogen merge skipped: %s", exc)

    resp = _fc(feats)
    if not feats:
        resp["note"] = "No hydrogen / electrolyser sites in this bbox"
        resp["available"] = True  # table exists, just empty here
    return resp
