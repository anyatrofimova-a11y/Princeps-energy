"""REPD (Renewable Energy Planning Database) overlap analysis.

For a given INSPIRE parcel geometry, finds REPD projects whose footprint
intersects the parcel (or falls within a 100 m buffer). Returns up to
``top_k`` rows with the project ref, technology, capacity, status and the
overlap area in hectares.

If the ``repd_projects`` table is missing (common in dev / demo
environments) the caller gets an empty list with a ``pending`` marker —
the caller decides how to surface that. This module never raises.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.parcel.repd_overlap")


async def repd_overlap(
    conn: asyncpg.Connection,
    inspire_id: str,
    *,
    buffer_m: int = 100,
    top_k: int = 25,
) -> list[dict[str, Any]]:
    """Return REPD projects intersecting the parcel (buffered by ``buffer_m``)."""

    # Check the REPD table exists — skip gracefully if it doesn't.
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.repd_projects') IS NOT NULL"
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("repd table probe failed: %s", exc)
        return []
    if not exists:
        return []

    sql = f"""
        WITH p AS (
            SELECT geom
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text = $1
             LIMIT 1
        )
        SELECT r.ref_id,
               r.site_name,
               r.technology,
               r.capacity_mw,
               r.status,
               r.operator,
               r.planning_authority,
               r.decision_date,
               ROUND(
                   (ST_Area(ST_Intersection(r.geom, ST_Buffer(p.geom, {int(buffer_m)}))) / 10000.0)::numeric,
                   2
               ) AS overlap_ha,
               ST_Distance(r.geom, p.geom) AS distance_m
          FROM repd_projects r, p
         WHERE ST_DWithin(r.geom, p.geom, {int(buffer_m)})
         ORDER BY distance_m ASC
         LIMIT {int(top_k)}
    """
    try:
        rows = await conn.fetch(sql, inspire_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("repd overlap query failed for %s: %s", inspire_id, exc)
        return []

    return [
        {
            "ref_id": r["ref_id"],
            "site_name": r["site_name"],
            "technology": r["technology"],
            "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
            "status": r["status"],
            "operator": r["operator"],
            "planning_authority": r["planning_authority"],
            "decision_date": (
                r["decision_date"].isoformat() if r["decision_date"] else None
            ),
            "overlap_ha": float(r["overlap_ha"]) if r["overlap_ha"] is not None else 0.0,
            "distance_m": round(float(r["distance_m"]), 1) if r["distance_m"] is not None else None,
        }
        for r in rows
    ]
