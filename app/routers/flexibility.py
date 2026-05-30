"""
/api/flexibility/* — Northern Powergrid flexibility ontology.

Surfaces the uk_flexibility_zones table (Task #27) to the agent and frontend.
Joins by spatial proximity (lat/lon → 27700) or by GSP/substation name.

License: data is © Northern Powergrid Open Data Licence v1.0 — attribute on
any derived public surface.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/flexibility", tags=["flexibility"])


def _pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


@router.get("/datasets")
async def list_datasets(request: Request) -> dict[str, Any]:
    """Per-dataset row counts + last refresh time."""
    pool = _pool(request)
    rows = await pool.fetch(
        """
        SELECT dataset, COUNT(*) AS rows, MAX(ingested_at) AS last_ingested
        FROM uk_flexibility_zones
        GROUP BY dataset
        ORDER BY rows DESC
        """
    )
    return {
        "source": "Northern Powergrid OpenDataSoft",
        "licence": "Northern Powergrid Open Data Licence v1.0",
        "datasets": [dict(r) for r in rows],
    }


@router.get("/zones")
async def zones_near(
    request: Request,
    lat: float,
    lon: float,
    radius_m: float = 5000.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return flexibility events within `radius_m` of a WGS84 point.

    Includes the constraint zone, GSP, MW required/procured, provider —
    everything an agent needs to reason about local flexibility headroom
    when a developer drops a pin in NPg territory.
    """
    if not (49 <= lat <= 61 and -9 <= lon <= 2.5):
        raise HTTPException(400, "lat/lon outside GB envelope")
    pool = _pool(request)
    rows = await pool.fetch(
        """
        SELECT id, dataset, gsp_name, substation_name, constraint_zone,
               postcode, licence_area, region, constraint_trigger, product,
               forecast_year, delivery_year, flexibility_required_mw,
               flexibility_procured_mw, capacity_mva, voltage_kv, provider,
               ROUND(ST_Distance(geom,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700))::numeric,
                  0) AS distance_m
        FROM uk_flexibility_zones
        WHERE geom IS NOT NULL
          AND ST_DWithin(geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700), $3)
        ORDER BY distance_m ASC
        LIMIT $4
        """,
        lon, lat, radius_m, limit,
    )
    items = [dict(r) for r in rows]
    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "count": len(items),
        "items": items,
        "summary": _summarise(items),
        "licence": "Northern Powergrid Open Data Licence v1.0",
    }


@router.get("/by-gsp")
async def by_gsp(request: Request, gsp_name: str, limit: int = 50) -> dict[str, Any]:
    """All flexibility records for a named GSP (e.g. 'Stella South')."""
    pool = _pool(request)
    rows = await pool.fetch(
        """
        SELECT id, dataset, gsp_name, substation_name, constraint_zone,
               product, forecast_year, delivery_year,
               flexibility_required_mw, flexibility_procured_mw,
               capacity_mva, voltage_kv, provider
        FROM uk_flexibility_zones
        WHERE LOWER(gsp_name) = LOWER($1)
           OR gsp_name ILIKE $2
        ORDER BY forecast_year NULLS LAST, dataset
        LIMIT $3
        """,
        gsp_name, f"{gsp_name}%", limit,
    )
    items = [dict(r) for r in rows]
    return {"gsp": gsp_name, "count": len(items), "items": items}


def _summarise(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stats for agent context."""
    required = sum(float(r["flexibility_required_mw"] or 0) for r in items)
    procured = sum(float(r["flexibility_procured_mw"] or 0) for r in items)
    triggers: dict[str, int] = {}
    providers: set[str] = set()
    zones: set[str] = set()
    for r in items:
        t = r.get("constraint_trigger")
        if t:
            triggers[t] = triggers.get(t, 0) + 1
        if r.get("provider"):
            providers.add(r["provider"])
        if r.get("constraint_zone"):
            zones.add(r["constraint_zone"])
    return {
        "total_flexibility_required_mw": round(required, 2),
        "total_flexibility_procured_mw": round(procured, 2),
        "gap_mw": round(required - procured, 2),
        "constraint_triggers": triggers,
        "active_providers": sorted(providers)[:10],
        "constraint_zones": sorted(zones)[:10],
    }
