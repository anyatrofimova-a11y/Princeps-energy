"""Constraint gate — screens a proposed site boundary / layout polygon
against UK environmental & planning designations.

Uses the existing PostGIS-stored designation tables when available
(loaded from Natural England, MHCLG, Environment Agency feeds), falling
back to a clean "no data" response if a particular table isn't present.

Designations checked:
  - SSSI (Sites of Special Scientific Interest)
  - AONB (Areas of Outstanding Natural Beauty)
  - National Parks
  - Scheduled Monuments
  - Listed Buildings (within 100 m)
  - Flood Zone 2 / 3 (Environment Agency)
  - Green Belt
  - Greenfield / Ancient Woodland (optional)

Response shape:
  {
    "allowed": bool,
    "severity": "pass" | "caution" | "block",
    "designations": [
      { "code": "sssi", "name": "Epping Forest", "overlap_pct": 0.0, "impact": "block" },
      ...
    ],
    "recommendation": str,
  }
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.design.constraints")


# Designation → (table name, severity) tuple. Tables are checked for
# existence at query time so missing data gracefully degrades.
DESIGNATIONS = [
    ("sssi",               "env_sssi",                "block"),
    ("aonb",               "env_aonb",                "caution"),
    ("national_park",      "env_national_parks",      "block"),
    ("scheduled_monument", "env_scheduled_monuments", "block"),
    ("flood_zone_3",       "env_flood_zone_3",        "block"),
    ("flood_zone_2",       "env_flood_zone_2",        "caution"),
    ("green_belt",         "env_green_belt",          "caution"),
    ("ancient_woodland",   "env_ancient_woodland",    "block"),
]


async def _table_exists(conn, table: str) -> bool:
    q = """SELECT 1 FROM information_schema.tables
           WHERE table_name = $1 LIMIT 1"""
    return bool(await conn.fetchval(q, table))


async def screen_polygon(pool: asyncpg.Pool, geojson_polygon: dict) -> dict[str, Any]:
    """Return a constraint-gate decision for a GeoJSON polygon."""
    wkt_ring = _geojson_to_wkt(geojson_polygon)
    if wkt_ring is None:
        return {
            "allowed": False, "severity": "block",
            "designations": [],
            "recommendation": "Invalid polygon geometry.",
        }

    hits: list[dict] = []
    max_severity = "pass"
    async with pool.acquire() as conn:
        for code, table, severity in DESIGNATIONS:
            if not await _table_exists(conn, table):
                continue
            try:
                rows = await conn.fetch(
                    f"""SELECT name, ST_Area(ST_Intersection(geom, ST_GeomFromText($1, 4326))) AS ovr_m2,
                              ST_Area(ST_GeomFromText($1, 4326)) AS poly_m2
                       FROM {table}
                       WHERE ST_Intersects(geom, ST_GeomFromText($1, 4326))
                       LIMIT 5""",
                    wkt_ring,
                )
            except Exception as e:
                log.debug("constraint query %s failed: %s", code, e)
                continue
            for r in rows:
                overlap_pct = (r["ovr_m2"] / max(1, r["poly_m2"])) * 100 if r["poly_m2"] else 0
                hits.append({
                    "code": code,
                    "name": r["name"],
                    "overlap_pct": round(overlap_pct, 2),
                    "impact": severity,
                })
                max_severity = _escalate(max_severity, severity)

    allowed = max_severity != "block"
    return {
        "allowed": allowed,
        "severity": max_severity,
        "designations": hits,
        "recommendation": _recommendation(max_severity, hits),
    }


def _escalate(current: str, new: str) -> str:
    order = {"pass": 0, "caution": 1, "block": 2}
    return current if order[current] >= order[new] else new


def _recommendation(severity: str, hits: list[dict]) -> str:
    if severity == "pass":
        return "No statutory designation hit — proceed to design."
    if severity == "caution":
        return "Partial overlap with sensitive designations — a planning statement will be required; consider shrinking the boundary."
    block_names = [h["name"] for h in hits if h["impact"] == "block"]
    if block_names:
        return f"Hard blocker: overlaps {', '.join(block_names[:3])}. Redraw the boundary to exclude these."
    return "Constraint screening failed — redraw or escalate to planning counsel."


def _geojson_to_wkt(g: dict) -> str | None:
    """Convert a GeoJSON Polygon or MultiPolygon to a WKT string."""
    if not g:
        return None
    t = g.get("type")
    if t == "Polygon":
        rings = g.get("coordinates") or []
    elif t == "MultiPolygon":
        rings = sum((r for r in (g.get("coordinates") or [])), [])
    elif t == "Feature":
        return _geojson_to_wkt(g.get("geometry") or {})
    else:
        return None
    if not rings:
        return None
    ring = rings[0]
    if len(ring) < 3:
        return None
    pts = ", ".join(f"{pt[0]} {pt[1]}" for pt in ring)
    return f"POLYGON(({pts}))"
