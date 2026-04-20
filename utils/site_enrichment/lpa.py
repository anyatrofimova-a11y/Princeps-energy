"""Local Planning Authority resolution.

Strategy (in order):
    1. PostGIS point-in-polygon against ``lpa_boundaries`` (SRID 4326).
    2. If the table is missing, try a one-shot bootstrap from a bundled
       simplified LAD24 GeoJSON at ``data/lad24_simplified.geojson`` —
       this fixture is only a placeholder in source control (0 features);
       production deployments should replace it with the real ONS simplified
       polygons.  When the fixture is empty or absent we return ``None`` with
       a structured TODO.
    3. Final fallback: planning.data.gov.uk point-in-polygon query — kept as
       a *last-resort* because it adds ~200 ms of network RTT to the
       sub-enricher and we want to stay inside the 800 ms p95 budget.

Returned dict (on success):
    {"lpa_code": "E07000223", "lpa_name": "Arun", "region": "South East"}
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import asyncpg
import httpx

log = logging.getLogger("princeps.site_enrichment.lpa")

_DATA_DIR = Path(__file__).parent / "data"
_LAD24_PATH = _DATA_DIR / "lad24_simplified.geojson"
_TABLE_NAME = "lpa_boundaries"

_PLANNING_BASE = "https://www.planning.data.gov.uk/entity.json"
_HTTP_TIMEOUT = 2.5


_bootstrap_attempted = False


async def _table_exists(conn: asyncpg.Connection) -> bool:
    v = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{_TABLE_NAME}")
    return bool(v)


async def _bootstrap_from_fixture(conn: asyncpg.Connection) -> bool:
    """Create ``lpa_boundaries`` from the bundled LAD24 GeoJSON fixture.

    Idempotent per-process via the module-level ``_bootstrap_attempted``
    latch — we only probe once regardless of outcome.  Returns True if the
    table now has rows.
    """
    global _bootstrap_attempted
    if _bootstrap_attempted:
        return False
    _bootstrap_attempted = True

    if not _LAD24_PATH.is_file():
        log.info("lpa bootstrap skipped — fixture not bundled at %s", _LAD24_PATH)
        return False

    try:
        raw = _LAD24_PATH.read_text(encoding="utf-8")
        fc = json.loads(raw)
    except Exception as exc:
        log.warning("lpa bootstrap — cannot parse fixture: %s", exc)
        return False

    features = (fc or {}).get("features") or []
    if not features:
        log.info("lpa bootstrap — fixture has 0 features; skipping")
        return False

    # DDL guarded with IF NOT EXISTS — safe if another worker raced us.
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
            lpa_code  TEXT PRIMARY KEY,
            lpa_name  TEXT NOT NULL,
            region    TEXT,
            geom      GEOMETRY(MultiPolygon, 4326) NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_lpa_boundaries_geom
            ON {_TABLE_NAME} USING GIST (geom);
        """
    )

    inserted = 0
    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if not geom:
            continue
        code = props.get("LAD24CD") or props.get("lad24cd") or props.get("lpa_code")
        name = props.get("LAD24NM") or props.get("lad24nm") or props.get("lpa_name")
        region = props.get("RGN24NM") or props.get("region")
        if not code or not name:
            continue
        try:
            await conn.execute(
                f"""
                INSERT INTO {_TABLE_NAME} (lpa_code, lpa_name, region, geom)
                VALUES ($1, $2, $3,
                        ST_Multi(ST_SimplifyPreserveTopology(
                            ST_SetSRID(ST_GeomFromGeoJSON($4), 4326), 0.001)))
                ON CONFLICT (lpa_code) DO NOTHING
                """,
                code, name, region, json.dumps(geom),
            )
            inserted += 1
        except Exception as exc:
            log.debug("lpa bootstrap row skip %s: %s", code, exc)

    log.info("lpa bootstrap inserted %d LAD24 polygons", inserted)
    return inserted > 0


async def _postgis_lookup(conn: asyncpg.Connection, lat: float, lon: float) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow(
        f"""
        SELECT lpa_code, lpa_name, region
        FROM {_TABLE_NAME}
        WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
        LIMIT 1
        """,
        lon, lat,
    )
    return dict(row) if row else None


async def _planning_api_fallback(lat: float, lon: float) -> Optional[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(
                _PLANNING_BASE,
                params={
                    "dataset": "local-planning-authority",
                    "geometry": f"POINT({lon} {lat})",
                    "geometry_relation": "intersects",
                    "limit": 1,
                },
            )
            r.raise_for_status()
            rows = (r.json() or {}).get("entities") or []
            if not rows:
                return None
            top = rows[0]
            return {
                "lpa_code": top.get("reference"),
                "lpa_name": top.get("name"),
                "region": None,
            }
    except Exception as exc:
        log.debug("planning.data.gov.uk lpa fallback failed: %s", exc)
        return None


async def lookup(
    lat: float,
    lon: float,
    *,
    pool: Optional[asyncpg.Pool] = None,
) -> dict[str, Any]:
    """Resolve the LPA for (lat, lon). Raises ``ValueError`` on fatal failure."""
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                if not await _table_exists(conn):
                    await _bootstrap_from_fixture(conn)
                if await _table_exists(conn):
                    hit = await _postgis_lookup(conn, lat, lon)
                    if hit:
                        return hit
        except Exception as exc:
            log.debug("lpa postgis path failed: %s", exc)

    hit = await _planning_api_fallback(lat, lon)
    if hit:
        return hit
    raise ValueError("lpa: no polygon intersected and planning.data.gov.uk fallback empty")
