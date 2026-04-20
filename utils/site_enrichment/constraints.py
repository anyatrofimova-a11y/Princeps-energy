"""Batch environmental / planning constraint intersections.

Each constraint returns::
    {"inside": bool, "distance_m": float | null, "todo": str | null}

The check set (table names are the conventional Princeps Defra-MAGIC layer
names — see ``utils/magic_ingester.py``):

    aonb                → magic_aonb                 (inside + buffer)
    sssi                → magic_sssi                 (inside + buffer)
    ramsar              → magic_ramsar               (inside + buffer)
    sac                 → magic_sac                  (inside + buffer)
    spa                 → magic_spa                  (inside + buffer)
    flood_zone_2        → ea_flood_zone_2            (inside + buffer)
    flood_zone_3        → ea_flood_zone_3            (inside + buffer)
    ancient_woodland    → magic_ancient_woodland     (inside + buffer)
    green_belt          → magic_green_belt           (inside + buffer)
    national_park       → magic_national_parks       (inside + buffer)
    listed_buildings    → listed_buildings           (within 500 m)
    alc_grades_1_3a     → alc_grades                 (inside + buffer)

If a table is not ingested the result dict for that constraint is::
    {"inside": None, "distance_m": None,
     "todo": "Table '<name>' not ingested. Run utils/magic_ingester.py."}
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

log = logging.getLogger("princeps.site_enrichment.constraints")


# (result_key, table_name, kind) where kind ∈ {"poly", "poly_filter", "buffer"}
# ``poly``        = straight intersect + nearest-edge distance
# ``poly_filter`` = intersect with a WHERE filter (ALC grades 1..3a)
# ``buffer``      = within-500 m listed-building probe
_LAYERS: list[tuple[str, str, str]] = [
    ("aonb",             "magic_aonb",             "poly"),
    ("sssi",             "magic_sssi",             "poly"),
    ("ramsar",           "magic_ramsar",           "poly"),
    ("sac",              "magic_sac",              "poly"),
    ("spa",              "magic_spa",              "poly"),
    ("flood_zone_2",     "ea_flood_zone_2",        "poly"),
    ("flood_zone_3",     "ea_flood_zone_3",        "poly"),
    ("ancient_woodland", "magic_ancient_woodland", "poly"),
    ("green_belt",       "magic_green_belt",       "poly"),
    ("national_park",    "magic_national_parks",   "poly"),
    ("listed_buildings", "listed_buildings",       "buffer"),
    ("alc_grades_1_3a",  "alc_grades",             "poly_filter"),
]

_LISTED_RADIUS_M = 500


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}"))


async def _probe_poly(
    conn: asyncpg.Connection, table: str, lat: float, lon: float, *, where: str = "TRUE"
) -> dict[str, Any]:
    row = await conn.fetchrow(
        f"""
        SELECT
            bool_or(ST_Intersects(geom, p.g))                                   AS inside,
            MIN(ST_Distance(geom::geography, p.g::geography))::float            AS distance_m
        FROM {table}, (SELECT ST_SetSRID(ST_MakePoint($1, $2), 4326) AS g) p
        WHERE {where}
        """,
        lon, lat,
    )
    if row is None:
        return {"inside": False, "distance_m": None, "todo": None}
    return {
        "inside": bool(row["inside"]) if row["inside"] is not None else False,
        "distance_m": float(row["distance_m"]) if row["distance_m"] is not None else None,
        "todo": None,
    }


async def _probe_buffer(
    conn: asyncpg.Connection, table: str, lat: float, lon: float, radius_m: int
) -> dict[str, Any]:
    row = await conn.fetchrow(
        f"""
        SELECT
            bool_or(ST_DWithin(geom::geography, p.g::geography, $3))  AS inside,
            MIN(ST_Distance(geom::geography, p.g::geography))::float  AS distance_m
        FROM {table}, (SELECT ST_SetSRID(ST_MakePoint($1, $2), 4326) AS g) p
        """,
        lon, lat, radius_m,
    )
    if row is None:
        return {"inside": False, "distance_m": None, "todo": None}
    return {
        "inside": bool(row["inside"]) if row["inside"] is not None else False,
        "distance_m": float(row["distance_m"]) if row["distance_m"] is not None else None,
        "todo": None,
    }


async def lookup(
    lat: float,
    lon: float,
    *,
    pool: Optional[asyncpg.Pool] = None,
) -> dict[str, Any]:
    """Run all 12 constraint probes. Missing tables degrade to TODO entries."""
    if pool is None:
        raise ValueError("constraints: no DB pool provided")

    out: dict[str, Any] = {}
    async with pool.acquire() as conn:
        for key, table, kind in _LAYERS:
            try:
                if not await _table_exists(conn, table):
                    out[key] = {
                        "inside": None,
                        "distance_m": None,
                        "todo": f"Table '{table}' not ingested. Backfill via utils/magic_ingester.py.",
                    }
                    continue

                if kind == "poly":
                    out[key] = await _probe_poly(conn, table, lat, lon)
                elif kind == "poly_filter":
                    # ALC: "grade" column, values '1','2','3a','3b','4','5'.
                    out[key] = await _probe_poly(
                        conn, table, lat, lon, where="grade IN ('1','2','3a')"
                    )
                elif kind == "buffer":
                    out[key] = await _probe_buffer(conn, table, lat, lon, _LISTED_RADIUS_M)
            except Exception as exc:
                log.debug("constraint %s probe failed: %s", key, exc)
                out[key] = {"inside": None, "distance_m": None, "todo": f"probe error: {exc!s}"}

    return out
