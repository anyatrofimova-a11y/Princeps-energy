"""NOM data, NGED CIM distribution, CIM graph topology, and Electricity Maps router."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from typing import Any

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

# ── Utils ──
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.nom_data import (
    get_all_substations as nom_get_all,
    get_substation_by_id as nom_get_by_id,
    get_nom_geojson, get_nom_summary, get_licence_areas as nom_licence_areas,
    get_local_authorities as nom_local_authorities,
)
from utils.nged_cim import (
    find_opportunities as nged_opportunities,
    find_opportunities_near as nged_opportunities_near,
    opportunity_summary as nged_summary,
    substations_geojson as nged_substations_geojson,
    calc_headroom as nged_headroom,
    substation_detail as nged_substation_detail,
    get_transformers as nged_get_transformers,
    get_line_segments as nged_get_line_segments,
)
from utils.graph_topology import (
    get_circuit_topology,
    get_shortest_path as neo4j_shortest_path,
    get_downstream_assets as neo4j_downstream,
    graph_health_check as neo4j_health,
    driver_available as neo4j_available,
)


log = logging.getLogger("princeps")

router = APIRouter(tags=["nom"])


# ---------------------------------------------------------------------------
# Electricity Maps proxy
# ---------------------------------------------------------------------------
ELECTRICITYMAPS_API_KEY = os.environ.get("ELECTRICITYMAPS_API_KEY", "")
_EMAPS_BASE = "https://api.electricitymap.org/v3"
_emaps_cache: dict[str, tuple[float, Any]] = {}
_EMAPS_CACHE_TTL = 300  # 5 minutes

EUROPEAN_ZONES = [
    "AT", "BE", "BG", "CH", "CZ", "DE", "DK-DK1", "DK-DK2", "EE", "ES",
    "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IT-NO", "IT-CNO", "IT-CSO",
    "IT-SO", "IT-SAR", "IT-SIC", "LT", "LU", "LV", "NL", "NO-NO1", "NO-NO2",
    "NO-NO3", "NO-NO4", "NO-NO5", "PL", "PT", "RO", "RS", "SE-SE1", "SE-SE2",
    "SE-SE3", "SE-SE4", "SI", "SK", "UA",
]


async def _emaps_get(path: str) -> dict | None:
    """Fetch from Electricity Maps API with caching."""
    now = _time.time()
    if path in _emaps_cache:
        cached_time, cached_data = _emaps_cache[path]
        if now - cached_time < _EMAPS_CACHE_TTL:
            return cached_data
    if not ELECTRICITYMAPS_API_KEY:
        return {"error": "ELECTRICITYMAPS_API_KEY not configured"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_EMAPS_BASE}{path}",
                headers={"auth-token": ELECTRICITYMAPS_API_KEY},
            )
            if resp.status_code == 200:
                data = resp.json()
                _emaps_cache[path] = (now, data)
                return data
            return {"error": f"Electricity Maps API returned {resp.status_code}"}
    except Exception as exc:
        log.warning("Electricity Maps API error: %s", exc)
        return {"error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# NOM (Network Output Measures) — substation data
# ---------------------------------------------------------------------------

@router.get("/nom/substations")
async def nom_substations(
    type: str | None = None,
    rag: str | None = None,
    licence_area: str | None = None,
    local_authority: str | None = None,
    supply_type: str | None = None,
    constraint: str | None = None,
    search: str | None = None,
    view: str = "connected",
    map_type: str | None = None,
):
    return nom_get_all(
        type_filter=type, rag_filter=rag, licence_area=licence_area,
        local_authority=local_authority, supply_type=supply_type,
        constraint=constraint, search=search, view=view, map_type=map_type,
    )


@router.get("/nom/substations/geojson")
async def nom_substations_geojson(
    type: str | None = None,
    rag: str | None = None,
    licence_area: str | None = None,
    local_authority: str | None = None,
    supply_type: str | None = None,
    constraint: str | None = None,
    search: str | None = None,
    view: str = "connected",
    map_type: str | None = None,
):
    return get_nom_geojson(
        type_filter=type, rag_filter=rag, licence_area=licence_area,
        local_authority=local_authority, supply_type=supply_type,
        constraint=constraint, search=search, view=view, map_type=map_type,
    )


@router.get("/nom/substations/{sub_number}")
async def nom_substation_detail(sub_number: str):
    sub = nom_get_by_id(sub_number)
    if not sub:
        raise HTTPException(404, f"Substation {sub_number} not found")
    return sub


@router.get("/nom/summary")
async def nom_summary():
    return get_nom_summary()


@router.get("/nom/licence-areas")
async def nom_licence_areas_list():
    return nom_licence_areas()


@router.get("/nom/local-authorities")
async def nom_local_authorities_list():
    return nom_local_authorities()


# ---------------------------------------------------------------------------
# NGED CIM Distribution Network (from LTDS Common Information Model)
# ---------------------------------------------------------------------------

@router.get("/nged/substations")
async def nged_substations(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON of NGED substations with headroom properties in bbox."""
    async with pool.acquire() as conn:
        return await nged_substations_geojson(conn, west, south, east, north)


@router.get("/nged/opportunities")
async def nged_opportunities_endpoint(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    min_headroom_mw: float = Query(1.0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Substations with spare capacity in bbox."""
    async with pool.acquire() as conn:
        return await nged_opportunities(conn, west, south, east, north, min_headroom_mw)


@router.get("/nged/substation/{sub_id}")
async def nged_substation_detail_endpoint(sub_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Single substation detail with transformers, consumers, and headroom."""
    async with pool.acquire() as conn:
        detail = await nged_substation_detail(conn, sub_id)
        if not detail:
            raise HTTPException(404, f"NGED substation {sub_id} not found")
        return detail


@router.get("/nged/substation/{sub_id}/headroom")
async def nged_substation_headroom(sub_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Headroom calculation for a substation."""
    async with pool.acquire() as conn:
        return await nged_headroom(conn, sub_id)


@router.get("/nged/summary")
async def nged_summary_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """Regional counts, total headroom, top opportunities."""
    async with pool.acquire() as conn:
        return await nged_summary(conn)


@router.get("/nged/transformers")
async def nged_transformers(substation_id: str = Query(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Transformers at a substation."""
    async with pool.acquire() as conn:
        return await nged_get_transformers(conn, substation_id)


@router.get("/nged/lines")
async def nged_lines(
    substation_id: str = Query(None),
    region: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Line segments, optionally filtered by region."""
    async with pool.acquire() as conn:
        return await nged_get_line_segments(conn, substation_id, region)


# ---------------------------------------------------------------------------
# CIM Graph Topology (Neo4j Bus-Branch model)
# ---------------------------------------------------------------------------

@router.get("/grid/cim/circuit/{substation_id}")
async def cim_circuit(substation_id: str, depth: int = Query(3, ge=1, le=5)):
    """Circuit topology around a substation for React Flow diagram."""
    if not neo4j_available():
        raise HTTPException(503, "Neo4j graph database is not available")
    return await get_circuit_topology(substation_id, depth)


@router.get("/grid/cim/search")
async def cim_search(q: str = Query(..., min_length=1), pool: asyncpg.Pool = Depends(get_pool)):
    """Search NGED substations by name (queries PostgreSQL)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, region, voltage_kv
            FROM nged_substation
            WHERE name ILIKE $1
            ORDER BY name
            LIMIT 20
            """,
            f"%{q}%",
        )
        return [dict(r) for r in rows]


@router.get("/grid/cim/path")
async def cim_path(from_id: str = Query(...), to_id: str = Query(...)):
    """Shortest electrical path between two assets."""
    if not neo4j_available():
        raise HTTPException(503, "Neo4j graph database is not available")
    return await neo4j_shortest_path(from_id, to_id)


@router.get("/grid/cim/downstream/{substation_id}")
async def cim_downstream(substation_id: str):
    """All assets downstream of a substation (impact analysis)."""
    if not neo4j_available():
        raise HTTPException(503, "Neo4j graph database is not available")
    return await neo4j_downstream(substation_id)


@router.get("/grid/cim/health")
async def cim_health():
    """Neo4j graph health -- node/relationship counts."""
    return await neo4j_health()


# ---------------------------------------------------------------------------
# Electricity Maps — carbon intensity & power breakdown
# ---------------------------------------------------------------------------

@router.get("/electricity/carbon-intensity/{zone}")
async def electricity_carbon_intensity(zone: str):
    """Proxy to Electricity Maps carbon intensity for a zone."""
    data = await _emaps_get(f"/carbon-intensity/latest?zone={zone}")
    if not data:
        raise HTTPException(status_code=502, detail="Failed to fetch from Electricity Maps")
    return data


@router.get("/electricity/power-breakdown/{zone}")
async def electricity_power_breakdown(zone: str):
    """Proxy to Electricity Maps power generation breakdown for a zone."""
    data = await _emaps_get(f"/power-breakdown/latest?zone={zone}")
    if not data:
        raise HTTPException(status_code=502, detail="Failed to fetch from Electricity Maps")
    return data


@router.get("/electricity/carbon-intensity-all")
async def electricity_carbon_intensity_all():
    """Batch query carbon intensity for all European zones."""
    now = _time.time()
    cache_key = "__all_european__"
    if cache_key in _emaps_cache:
        cached_time, cached_data = _emaps_cache[cache_key]
        if now - cached_time < _EMAPS_CACHE_TTL:
            return cached_data

    tasks = [_emaps_get(f"/carbon-intensity/latest?zone={z}") for z in EUROPEAN_ZONES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    zones_data = {}
    for zone, result in zip(EUROPEAN_ZONES, results):
        if isinstance(result, Exception):
            zones_data[zone] = {"error": str(result)[:200]}
        elif result and "error" not in result:
            zones_data[zone] = result
        else:
            zones_data[zone] = result or {"error": "No data"}

    response = {"zones": zones_data, "timestamp": now}
    _emaps_cache[cache_key] = (now, response)
    return response
