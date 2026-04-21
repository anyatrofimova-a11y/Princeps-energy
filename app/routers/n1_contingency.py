"""API router for the UK N-1 Contingency Map manufactured dataset.

Endpoints
---------
    GET  /api/n1/substation/{substation_id}   — full contingency record
    GET  /api/n1/map?bbox=&score_lt=          — GeoJSON feature collection
    GET  /api/n1/worst-cases?limit=50         — ranked list (worst first)
    POST /api/n1/rerun/{substation_id}        — on-demand recompute (admin)

`{substation_id}` accepts either the Princeps canonical UUID or the
underlying integer `grid_substations.id`. The former is the stable key
returned by the dataset; the latter is convenient for internal tooling.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
import asyncpg

from app.deps import get_pool

from utils.n1_contingency.analyser import (
    run_substation_n1,
    substation_uuid,
)
from utils.n1_contingency.batch_runner import upsert_record

log = logging.getLogger("princeps.routers.n1")

router = APIRouter(tags=["n1_contingency"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_admin(x_admin_token: Optional[str]) -> None:
    """Gate the expensive `rerun` endpoint behind an admin token.

    If `ADMIN_INGEST_TOKEN` is unset (dev / local) the gate is open. In
    production set it to any non-empty string and pass it via the
    `X-Admin-Token` header. Matches the pattern used in `routers/grid.py`.
    """
    expected = os.environ.get("ADMIN_INGEST_TOKEN")
    if not expected:
        return
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="admin token required")


def _resolve_substation_uuid(key: str) -> Optional[uuid.UUID]:
    """Resolve the path param (UUID string or integer grid_substations.id)
    to the canonical N-1 map UUID. Returns None if unparseable."""
    try:
        return uuid.UUID(key)
    except ValueError:
        pass
    try:
        return substation_uuid(int(key))
    except ValueError:
        return None


def _row_to_payload(row: asyncpg.Record) -> dict[str, Any]:
    """Serialize a `n1_contingency_map` row to the API response shape."""
    events = row["events"]
    if isinstance(events, str):
        import json
        events = json.loads(events)
    notes = row["notes"]
    if isinstance(notes, str):
        import json
        notes = json.loads(notes)
    return {
        "substation_id": str(row["substation_id"]),
        "substation_name": row["substation_name"],
        "voltage_kv": float(row["voltage_kv"]) if row["voltage_kv"] is not None else None,
        "dno": row["dno"],
        "worst_case_overload_pct": float(row["worst_case_overload_pct"]) if row["worst_case_overload_pct"] is not None else 0.0,
        "worst_case_affected_mw": float(row["worst_case_affected_mw"]) if row["worst_case_affected_mw"] is not None else 0.0,
        "reliability_score_0_100": float(row["reliability_score"]) if row["reliability_score"] is not None else None,
        "n1_outage_events": events or [],
        "last_computed_at": row["last_computed_at"].isoformat() if row["last_computed_at"] else None,
        "model_version": row["model_version"],
        "upstream_assets_scanned": int(row["upstream_assets_scanned"] or 0),
        "failed_outages": int(row["failed_outages"] or 0),
        "notes": notes or [],
        "lat": float(row["lat"]) if ("lat" in row and row["lat"] is not None) else None,
        "lon": float(row["lon"]) if ("lon" in row and row["lon"] is not None) else None,
    }


# ---------------------------------------------------------------------------
# GET /api/n1/substation/{id}
# ---------------------------------------------------------------------------
@router.get("/n1/substation/{substation_id}")
async def get_n1_record(
    substation_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the full N-1 contingency record for one substation."""
    canonical = _resolve_substation_uuid(substation_id)
    if canonical is None:
        raise HTTPException(status_code=400, detail="invalid substation id (expected uuid or int)")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT substation_id, substation_name, voltage_kv, dno,
                   worst_case_overload_pct, worst_case_affected_mw,
                   reliability_score, events, last_computed_at, model_version,
                   upstream_assets_scanned, failed_outages, notes,
                   ST_Y(geometry::geometry) AS lat,
                   ST_X(geometry::geometry) AS lon
              FROM n1_contingency_map
             WHERE substation_id = $1
            """,
            canonical,
        )
    if not row:
        raise HTTPException(status_code=404, detail="no N-1 record for this substation — run batch first")
    return _row_to_payload(row)


# ---------------------------------------------------------------------------
# GET /api/n1/map?bbox=&score_lt=
# ---------------------------------------------------------------------------
@router.get("/n1/map")
async def get_n1_map(
    bbox: Optional[str] = Query(
        None,
        description=(
            "WGS84 bounding box as 'minLon,minLat,maxLon,maxLat'. "
            "Omit to return all points — the GET may be slow for full-country."
        ),
    ),
    score_lt: Optional[float] = Query(
        None, ge=0, le=100,
        description="Only return stations with reliability_score strictly below this value.",
    ),
    voltage_kv: Optional[float] = Query(
        None, gt=0,
        description="Filter to one voltage level (11 / 33 / 66 / 132 kV).",
    ),
    dno: Optional[str] = Query(None, description="Licensee slug filter."),
    limit: int = Query(5000, ge=1, le=20000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return a GeoJSON FeatureCollection of N-1 records for map rendering.

    Feature properties:
        substation_name, voltage_kv, dno,
        reliability_score, worst_case_overload_pct, worst_case_affected_mw
    """
    clauses = ["geometry IS NOT NULL"]
    args: list[Any] = []

    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(x) for x in bbox.split(",")]
        except Exception:
            raise HTTPException(status_code=400, detail="bbox must be 'minLon,minLat,maxLon,maxLat'")
        clauses.append(
            "geometry && ST_MakeEnvelope("
            f"${len(args) + 1}, ${len(args) + 2}, ${len(args) + 3}, ${len(args) + 4}, 4326)::geography"
        )
        args.extend([min_lon, min_lat, max_lon, max_lat])

    if score_lt is not None:
        clauses.append(f"reliability_score < ${len(args) + 1}")
        args.append(score_lt)
    if voltage_kv is not None:
        clauses.append(f"voltage_kv = ${len(args) + 1}")
        args.append(voltage_kv)
    if dno:
        clauses.append(f"dno = ${len(args) + 1}")
        args.append(dno)

    args.append(limit)
    sql = f"""
        SELECT substation_id, substation_name, voltage_kv, dno,
               worst_case_overload_pct, worst_case_affected_mw,
               reliability_score,
               ST_Y(geometry::geometry) AS lat,
               ST_X(geometry::geometry) AS lon
          FROM n1_contingency_map
         WHERE {' AND '.join(clauses)}
      ORDER BY reliability_score ASC NULLS LAST
         LIMIT ${len(args)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)

    features = []
    for r in rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "substation_id": str(r["substation_id"]),
                "substation_name": r["substation_name"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "dno": r["dno"],
                "reliability_score": float(r["reliability_score"]) if r["reliability_score"] is not None else None,
                "worst_case_overload_pct": float(r["worst_case_overload_pct"]) if r["worst_case_overload_pct"] is not None else 0.0,
                "worst_case_affected_mw": float(r["worst_case_affected_mw"]) if r["worst_case_affected_mw"] is not None else 0.0,
            },
        })

    return {"type": "FeatureCollection", "features": features, "count": len(features)}


# ---------------------------------------------------------------------------
# GET /api/n1/worst-cases
# ---------------------------------------------------------------------------
@router.get("/n1/worst-cases")
async def get_worst_cases(
    limit: int = Query(50, ge=1, le=500),
    voltage_kv: Optional[float] = Query(None, gt=0),
    dno: Optional[str] = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Rank substations nationally by reliability_score ascending."""
    clauses = ["reliability_score IS NOT NULL"]
    args: list[Any] = []
    if voltage_kv is not None:
        clauses.append(f"voltage_kv = ${len(args) + 1}")
        args.append(voltage_kv)
    if dno:
        clauses.append(f"dno = ${len(args) + 1}")
        args.append(dno)
    args.append(limit)

    sql = f"""
        SELECT substation_id, substation_name, voltage_kv, dno,
               worst_case_overload_pct, worst_case_affected_mw,
               reliability_score, upstream_assets_scanned, failed_outages,
               last_computed_at,
               ST_Y(geometry::geometry) AS lat,
               ST_X(geometry::geometry) AS lon
          FROM n1_contingency_map
         WHERE {' AND '.join(clauses)}
      ORDER BY reliability_score ASC, worst_case_overload_pct DESC
         LIMIT ${len(args)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)

    return {
        "count": len(rows),
        "results": [
            {
                "substation_id": str(r["substation_id"]),
                "substation_name": r["substation_name"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "dno": r["dno"],
                "reliability_score": float(r["reliability_score"]),
                "worst_case_overload_pct": float(r["worst_case_overload_pct"]) if r["worst_case_overload_pct"] is not None else 0.0,
                "worst_case_affected_mw": float(r["worst_case_affected_mw"]) if r["worst_case_affected_mw"] is not None else 0.0,
                "upstream_assets_scanned": int(r["upstream_assets_scanned"] or 0),
                "failed_outages": int(r["failed_outages"] or 0),
                "last_computed_at": r["last_computed_at"].isoformat() if r["last_computed_at"] else None,
                "lat": float(r["lat"]) if r["lat"] is not None else None,
                "lon": float(r["lon"]) if r["lon"] is not None else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/n1/rerun/{id} — on-demand recompute (admin-only)
# ---------------------------------------------------------------------------
@router.post("/n1/rerun/{substation_id}")
async def rerun_n1(
    substation_id: str,
    x_admin_token: Optional[str] = Header(default=None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recompute one substation's N-1 record synchronously.

    This is expensive (2-60 s depending on local subnetwork size) because it
    spawns a pandapower subprocess. Gated behind ADMIN_INGEST_TOKEN.
    """
    _require_admin(x_admin_token)

    # We need the integer grid_substations.id to call the analyser. If the
    # caller passed a UUID we have to reverse-lookup via the existing row.
    try:
        sid = int(substation_id)
    except ValueError:
        try:
            u = uuid.UUID(substation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid substation id")

        # The uuid namespace isn't reversible — we scan grid_substations
        # forward and pick the match. 7k rows is fine.
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM grid_substations")
        sid = None
        for r in rows:
            if substation_uuid(int(r["id"])) == u:
                sid = int(r["id"])
                break
        if sid is None:
            raise HTTPException(status_code=404, detail="substation not found")

    started = datetime.now(timezone.utc)
    record = await run_substation_n1(substation_id=sid, pool=pool)
    if record is None:
        raise HTTPException(status_code=404, detail="substation not found in grid_substations")

    async with pool.acquire() as conn:
        await upsert_record(conn, record)
        await conn.execute(
            """
            INSERT INTO n1_contingency_runs (
                dno_filter, limit_applied, workers, model_version,
                target_count, upserted, failed, not_found,
                started_at, finished_at, trigger
            ) VALUES (
                $1, 1, 1, $2,
                1, 1, $3, 0,
                $4, $5, 'on_demand'
            )
            """,
            record.dno,
            record.model_version,
            1 if record.failed_outages > 0 and record.upstream_assets_scanned == 0 else 0,
            started,
            datetime.now(timezone.utc),
        )

    return {
        "status": "ok",
        "substation_id": str(record.substation_id),
        "reliability_score": record.reliability_score_0_100,
        "worst_case_overload_pct": record.worst_case_overload_pct,
        "upstream_assets_scanned": record.upstream_assets_scanned,
        "failed_outages": record.failed_outages,
        "last_computed_at": record.last_computed_at.isoformat(),
    }
