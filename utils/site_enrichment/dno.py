"""DNO (Distribution Network Operator) resolver.

Two paths:
    1. PostGIS intersect on ``dno_licence_areas`` (or the existing
       ``grid_dno_boundaries`` — we try both for compatibility with the
       active schema).
    2. Postcode-district (outcode) → DNO lookup using a bundled static map
       at ``data/postcode_dno_map.json``.  Free fallback — accuracy is
       outcode-level (first half of postcode), which is correct for the
       vast majority of mainland GB outcodes.

Returns:
    {"dno_slug": "ukpn", "dno_name": "UK Power Networks", "licence_sub_region": "EPN"}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import asyncpg

log = logging.getLogger("princeps.site_enrichment.dno")

_DATA = Path(__file__).parent / "data" / "postcode_dno_map.json"

# Two candidate table names — first match wins.
_CANDIDATE_TABLES = ["dno_licence_areas", "grid_dno_boundaries"]


async def _first_existing_table(conn: asyncpg.Connection) -> Optional[str]:
    for t in _CANDIDATE_TABLES:
        v = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{t}")
        if v:
            return t
    return None


async def _postgis_lookup(conn: asyncpg.Connection, table: str, lat: float, lon: float) -> Optional[dict[str, Any]]:
    # We don't know the exact column names across both candidate tables, so
    # use a tolerant SELECT: coalesce common field names.
    sql = f"""
        SELECT
            COALESCE(dno_slug, licence_area_code, slug, code)          AS dno_slug,
            COALESCE(dno_name, licence_area_name, name, operator_name) AS dno_name,
            COALESCE(licence_sub_region, sub_region, region, NULL)     AS licence_sub_region
        FROM {table}
        WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
        LIMIT 1
    """
    try:
        row = await conn.fetchrow(sql, lon, lat)
    except asyncpg.UndefinedColumnError:
        # Fall back to a minimal projection — just any row that intersects.
        row = await conn.fetchrow(
            f"SELECT * FROM {table} "
            f"WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)) LIMIT 1",
            lon, lat,
        )
        if row is None:
            return None
        d = dict(row)
        return {
            "dno_slug": d.get("dno_slug") or d.get("code") or d.get("slug"),
            "dno_name": d.get("dno_name") or d.get("name") or d.get("operator_name"),
            "licence_sub_region": d.get("licence_sub_region") or d.get("sub_region") or d.get("region"),
        }
    return dict(row) if row else None


def _load_static_map() -> dict[str, dict[str, str]]:
    if not _DATA.is_file():
        return {}
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("static postcode→DNO map unreadable: %s", exc)
        return {}


def _postcode_fallback(outcode: str) -> Optional[dict[str, Any]]:
    table = _load_static_map()
    if not table:
        return None
    outcode_up = outcode.strip().upper()
    # Try exact outcode (e.g. "SW1A"), then the area (leading letter prefix).
    if outcode_up in table:
        return dict(table[outcode_up])
    # Area = the leading alphabetic characters of the outcode.
    # e.g. "SW1A" → "SW", "OX4" → "OX", "B1" → "B".
    area_chars: list[str] = []
    for ch in outcode_up:
        if ch.isalpha():
            area_chars.append(ch)
        else:
            break
    area = "".join(area_chars)
    if area and area in table:
        return dict(table[area])
    return None


async def lookup(
    lat: float,
    lon: float,
    *,
    pool: Optional[asyncpg.Pool] = None,
    postcode: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve the DNO for (lat, lon). ``postcode`` is the postcodes.io hit,
    used as the fallback key when we have no spatial layer.

    Raises ``ValueError`` if neither path produced a result.
    """
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                tbl = await _first_existing_table(conn)
                if tbl:
                    hit = await _postgis_lookup(conn, tbl, lat, lon)
                    if hit and hit.get("dno_name"):
                        return hit
        except Exception as exc:
            log.debug("dno postgis path failed: %s", exc)

    if postcode:
        outcode = postcode.split()[0]
        hit = _postcode_fallback(outcode)
        if hit:
            return hit

    raise ValueError("dno: no PostGIS layer hit and no outcode fallback match")
