"""Grid OSM proxy endpoints — proxy NGED LTDS substations to the legacy
``/api/grid/osm/*`` URLs that the Map page calls. Returns empty
FeatureCollections for sublayers we don't yet have (towers, plants,
switchgear, generators, lines, substation polygons).

Wiring: the legacy Map component fetches seven layers in parallel
when the viewport changes. Without these endpoints all seven return
404 and the map shows no substations. With them, ``substations``
serves real LTDS data and the rest return empty so the layers register
cleanly.
"""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

router = APIRouter(prefix="/api/grid/osm", tags=["grid-osm"])


def _empty() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


@router.get("/substations")
async def osm_substations(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Substation pins within the (west, south, east, north) WGS84 bbox.

    Backed by ltds_substations (lat/lon are WGS84 — only ~6.5k of 2,059
    NGED have coords today; coord-matching to grid_substations is a
    follow-up). Returns up to 5,000 points.
    """
    try:
        async with pool.acquire(timeout=8) as conn:
            rows = await conn.fetch(
                """
                SELECT mrid, name, licence_area, psr_type, substation_number,
                       lat, lon
                FROM ltds_substations
                WHERE lat IS NOT NULL
                  AND lon BETWEEN $1 AND $3
                  AND lat BETWEEN $2 AND $4
                LIMIT 5000
                """,
                west, south, east, north,
            )
    except asyncpg.UndefinedTableError:
        return _empty()
    features = [
        {
            "type": "Feature",
            "id": r["mrid"],
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "mrid": r["mrid"],
                "name": r["name"],
                "licence_area": r["licence_area"],
                "psr_type": r["psr_type"],
                "substation_number": r["substation_number"],
                "voltage_kv": None,
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


@router.get("/substation-polys")
async def osm_substation_polys(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
) -> dict[str, Any]:
    return _empty()


@router.get("/lines")
async def osm_lines(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """AC line segments — empty for now; future ingest will populate."""
    return _empty()


@router.get("/towers")
async def osm_towers(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
) -> dict[str, Any]:
    return _empty()


@router.get("/plants")
async def osm_plants(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
) -> dict[str, Any]:
    return _empty()


@router.get("/generators")
async def osm_generators(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
) -> dict[str, Any]:
    return _empty()


@router.get("/switchgear")
async def osm_switchgear(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
) -> dict[str, Any]:
    return _empty()
