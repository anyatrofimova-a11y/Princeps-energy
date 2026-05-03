"""Grid overlay — spatial GeoJSON layer endpoints for the v2 cockpit
and DC Design Twin. MeanderX-grade visibility for UK queue + lines.

  GET /api/grid-overlay/queue?bbox=&voltage_min=&status=&source=
       Unified TEC + ECR + REPD GeoJSON FeatureCollection. Each feature
       carries a `source` (`tec` | `ecr` | `repd`), `status`, `voltage_kv`,
       `capacity_mw`, and a stable `feature_id` the frontend uses to
       open a project-info card.

  GET /api/grid-overlay/lines?bbox=&voltage_min=
       Power lines (LineString) styled by voltage band. Source: grid_lines
       (OSM-derived, 27700). Bbox-restricted with a hard row cap.

  GET /api/grid-overlay/project/{source}/{id}
       Project-info card payload (name, submitter, technology, voltage,
       in-service, status, dno, links to TEC/REPD/ECR). Used by the
       slide-in card on the cockpit map and DC twin.

All geometries come back in EPSG:4326 (lng/lat), regardless of native SRID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.grid_overlay")

router = APIRouter(prefix="/api/grid-overlay", tags=["grid-overlay"])

_QUEUE_HARD_CAP = 1500
_LINES_HARD_CAP = 4000


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("expected 4 comma-separated floats")
        minlng, minlat, maxlng, maxlat = parts
        if not (-180 <= minlng <= 180 and -180 <= maxlng <= 180):
            raise ValueError("longitude out of range")
        if not (-90 <= minlat <= 90 and -90 <= maxlat <= 90):
            raise ValueError("latitude out of range")
        if minlng >= maxlng or minlat >= maxlat:
            raise ValueError("min must be < max")
        return minlng, minlat, maxlng, maxlat
    except Exception as exc:
        raise HTTPException(400, f"invalid bbox: {exc}")


@router.get("/queue")
async def queue(
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat (EPSG:4326)"),
    voltage_min: float | None = Query(None, ge=0, le=800),
    status: str | None = Query(None, description="filter substring on status"),
    source: str = Query("all", pattern="^(all|tec|ecr|repd)$"),
    limit: int = Query(_QUEUE_HARD_CAP, ge=1, le=_QUEUE_HARD_CAP),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Unified queue layer — TEC + ECR + REPD as a single FeatureCollection.

    Each feature has consistent properties:
      feature_id       — `<source>:<id>`
      source           — 'tec' | 'ecr' | 'repd'
      name             — display name
      submitter        — developer / customer / operator
      technology       — fuel/tech category
      capacity_mw      — MW (TEC mw, ECR capacity_mw, REPD capacity_mw)
      voltage_kv       — kV (where known)
      status           — pipeline status string
      in_service_date  — ISO date string or null
      dno              — DNO area (ECR only — others null)
      raw              — small slice of original row for the card panel
    """
    minlng, minlat, maxlng, maxlat = _parse_bbox(bbox)

    features: list[dict] = []
    per_source_cap = max(50, limit // 3)

    async with pool.acquire() as conn:
        if source in ("all", "ecr"):
            features.extend(await _ecr_features(
                conn, minlng, minlat, maxlng, maxlat,
                voltage_min, status, per_source_cap,
            ))

        if source in ("all", "repd"):
            features.extend(await _repd_features(
                conn, minlng, minlat, maxlng, maxlat,
                status, per_source_cap,
            ))

        if source in ("all", "tec"):
            features.extend(await _tec_features(
                conn, minlng, minlat, maxlng, maxlat,
                voltage_min, status, per_source_cap,
            ))

    return {
        "type": "FeatureCollection",
        "features": features[:limit],
        "metadata": {
            "bbox": [minlng, minlat, maxlng, maxlat],
            "filters": {
                "voltage_min": voltage_min,
                "status": status,
                "source": source,
            },
            "feature_count": len(features),
            "truncated": len(features) > limit,
        },
    }


async def _ecr_features(conn, minlng, minlat, maxlng, maxlat,
                        voltage_min, status, cap):
    rows = await conn.fetch(
        """
        SELECT
          id, external_id, site_name, dno, technology, capacity_mw,
          voltage_kv, substation_name, status, connection_date,
          ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geojson
        FROM grid_ecr
        WHERE geom IS NOT NULL
          AND ST_Intersects(
              geom,
              ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
          )
          AND ($5::numeric IS NULL OR voltage_kv >= $5)
          AND ($6::text    IS NULL OR status ILIKE '%' || $6 || '%')
        ORDER BY capacity_mw DESC NULLS LAST
        LIMIT $7
        """,
        minlng, minlat, maxlng, maxlat, voltage_min, status, cap,
    )
    out = []
    for r in rows:
        out.append({
            "type": "Feature",
            "geometry": r["geojson"],
            "properties": {
                "feature_id": f"ecr:{r['id']}",
                "source": "ecr",
                "name": r["site_name"] or r["substation_name"] or f"ECR {r['id']}",
                "submitter": None,
                "technology": r["technology"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "status": r["status"],
                "in_service_date": r["connection_date"].isoformat() if r["connection_date"] else None,
                "dno": r["dno"],
                "external_id": r["external_id"],
                "substation_name": r["substation_name"],
            },
        })
    return out


async def _repd_features(conn, minlng, minlat, maxlng, maxlat, status, cap):
    rows = await conn.fetch(
        """
        SELECT
          repd_id, site_name, technology, tech_category, capacity_mw,
          status, developer, operator, planning_authority, planning_ref,
          date_submitted, date_decided, date_operational,
          ST_AsGeoJSON(ST_Transform(geometry, 4326))::jsonb AS geojson
        FROM repd_projects
        WHERE geometry IS NOT NULL
          AND ST_Intersects(
              geometry,
              ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
          )
          AND ($5::text IS NULL OR status ILIKE '%' || $5 || '%')
        ORDER BY capacity_mw DESC NULLS LAST
        LIMIT $6
        """,
        minlng, minlat, maxlng, maxlat, status, cap,
    )
    out = []
    for r in rows:
        in_svc = r["date_operational"] or r["date_decided"] or r["date_submitted"]
        out.append({
            "type": "Feature",
            "geometry": r["geojson"],
            "properties": {
                "feature_id": f"repd:{r['repd_id']}",
                "source": "repd",
                "name": r["site_name"] or f"REPD {r['repd_id']}",
                "submitter": r["developer"] or r["operator"],
                "technology": r["tech_category"] or r["technology"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                "voltage_kv": None,
                "status": r["status"],
                "in_service_date": in_svc.isoformat() if in_svc else None,
                "dno": None,
                "planning_authority": r["planning_authority"],
                "planning_ref": r["planning_ref"],
            },
        })
    return out


async def _tec_features(conn, minlng, minlat, maxlng, maxlat,
                        voltage_min, status, cap):
    """TEC has no geom — join on grid_substations.name via ILIKE on
    `connection_site`. We pre-filter substations by bbox to keep this
    cheap; the LIKE join is the slow bit, so we cap aggressively."""
    rows = await conn.fetch(
        """
        WITH sub AS (
          SELECT id, name, voltage_kv,
                 ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geojson
          FROM grid_substations
          WHERE geom IS NOT NULL
            AND ST_Intersects(
                geom,
                ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
            )
        )
        SELECT
          t.tec_id, t.customer_name, t.connection_site, t.fuel_type,
          t.tech_category, t.tec_mw, t.status, t.voltage_kv,
          t.connection_date, t.queue_position,
          sub.geojson,
          sub.name AS sub_name
        FROM eso_tec_register t
        JOIN sub
          ON sub.name IS NOT NULL
         AND t.connection_site IS NOT NULL
         AND t.connection_site ILIKE '%' || sub.name || '%'
        WHERE ($5::numeric IS NULL OR COALESCE(t.voltage_kv, sub.voltage_kv) >= $5)
          AND ($6::text    IS NULL OR t.status ILIKE '%' || $6 || '%')
        ORDER BY t.tec_mw DESC NULLS LAST
        LIMIT $7
        """,
        minlng, minlat, maxlng, maxlat, voltage_min, status, cap,
    )
    out = []
    for r in rows:
        out.append({
            "type": "Feature",
            "geometry": r["geojson"],
            "properties": {
                "feature_id": f"tec:{r['tec_id']}",
                "source": "tec",
                "name": r["connection_site"] or f"TEC {r['tec_id']}",
                "submitter": r["customer_name"],
                "technology": r["tech_category"] or r["fuel_type"],
                "capacity_mw": float(r["tec_mw"]) if r["tec_mw"] is not None else None,
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "status": r["status"],
                "in_service_date": r["connection_date"].isoformat() if r["connection_date"] else None,
                "dno": None,
                "queue_position": r["queue_position"],
                "matched_substation": r["sub_name"],
            },
        })
    return out


@router.get("/lines")
async def lines(
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat (EPSG:4326)"),
    voltage_min: float | None = Query(None, ge=0, le=800),
    limit: int = Query(_LINES_HARD_CAP, ge=1, le=_LINES_HARD_CAP),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Power lines as GeoJSON LineStrings, with `voltage_band` set so the
    frontend can color: 400+, 275, 132, 66, 33, ≤22 kV."""
    minlng, minlat, maxlng, maxlat = _parse_bbox(bbox)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, osm_id, voltage_kv, circuits, operator, length_km,
                   ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb AS geojson
            FROM grid_lines
            WHERE geom IS NOT NULL
              AND ST_Intersects(
                  geom,
                  ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
              )
              AND ($5::numeric IS NULL OR voltage_kv >= $5)
            ORDER BY voltage_kv DESC NULLS LAST
            LIMIT $6
            """,
            minlng, minlat, maxlng, maxlat, voltage_min, limit,
        )

    features = []
    for r in rows:
        v = float(r["voltage_kv"]) if r["voltage_kv"] is not None else None
        features.append({
            "type": "Feature",
            "geometry": r["geojson"],
            "properties": {
                "feature_id": f"line:{r['id']}",
                "osm_id": r["osm_id"],
                "voltage_kv": v,
                "voltage_band": _voltage_band(v),
                "circuits": r["circuits"],
                "operator": r["operator"],
                "length_km": float(r["length_km"]) if r["length_km"] is not None else None,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "bbox": [minlng, minlat, maxlng, maxlat],
            "feature_count": len(features),
            "truncated": len(features) >= limit,
        },
    }


def _voltage_band(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v >= 400:
        return "400kV+"
    if v >= 275:
        return "275kV"
    if v >= 132:
        return "132kV"
    if v >= 66:
        return "66kV"
    if v >= 33:
        return "33kV"
    return "≤22kV"


@router.get("/project/{source}/{project_id}")
async def project_info(
    source: str,
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Full project-info card payload for a single feature.

    Path params:
      source — 'tec' | 'ecr' | 'repd'
      project_id — native id (TEC tec_id, ECR id, REPD repd_id)
    """
    if source not in ("tec", "ecr", "repd"):
        raise HTTPException(404, f"unknown source: {source}")

    async with pool.acquire() as conn:
        if source == "tec":
            row = await conn.fetchrow(
                """
                SELECT tec_id, customer_name, connection_site, fuel_type,
                       tech_category, tec_mw, dnc_mw, status, effective_from,
                       effective_to, connection_date, voltage_kv, zone,
                       spv_name, parent_company, queue_position, metadata
                FROM eso_tec_register WHERE tec_id = $1
                """,
                project_id,
            )
        elif source == "ecr":
            try:
                pk = int(project_id)
            except ValueError:
                raise HTTPException(400, "ecr id must be integer")
            row = await conn.fetchrow(
                """
                SELECT id, external_id, site_name, dno, technology, capacity_mw,
                       voltage_kv, substation_name, substation_id, status,
                       connection_date, raw_data
                FROM grid_ecr WHERE id = $1
                """,
                pk,
            )
        else:  # repd
            row = await conn.fetchrow(
                """
                SELECT repd_id, site_name, technology, tech_category,
                       capacity_mw, status, developer, operator,
                       planning_authority, planning_ref, address, county,
                       region, country, postcode, mounting_type, height_m,
                       turbines, battery_mwh, co_located, appeal_ref,
                       date_submitted, date_decided, date_operational,
                       planning_url, metadata
                FROM repd_projects WHERE repd_id = $1
                """,
                project_id,
            )

    if not row:
        raise HTTPException(404, f"{source}:{project_id} not found")

    record = {k: _to_jsonable(v) for k, v in dict(row).items()}
    return {"source": source, "id": project_id, "record": record}


def _to_jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return v
    if isinstance(v, (list, tuple)):
        return [_to_jsonable(x) for x in v]
    try:
        return json.loads(json.dumps(v, default=str))
    except Exception:
        return str(v)
