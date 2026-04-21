"""
Historic England NHLE — Listed Buildings ingester (narrow focus).

This module is a **thin re-export** of the NHLE fetcher already shipped in
``utils.substrate.nature_heritage_ingester`` plus a dedicated upserter that
populates the narrower ``listed_buildings_he`` table (Point geometry, 500 m
proximity queries). The wider NHLE universe (scheduled monuments, parks &
gardens, battlefields, WHSs) still lands in ``nhle_heritage_entries`` via
``nature_heritage_ingester``.

Why two tables?
  * ``nhle_heritage_entries`` (0014) — Geometry type, covers all 6 entry
    classes, used by the general heritage panel.
  * ``listed_buildings_he``   (0015) — Point type, listed-building subset,
    used by ``consultee_resolver`` for the 500 m DMPO consultation buffer
    and by the map UI for fast tile rendering.

Usage::

    python -m utils.substrate.listed_buildings_ingester -0.3,51.3,0.3,51.7

Library::

    from utils.substrate.listed_buildings_ingester import ingest_listed_buildings
    await ingest_listed_buildings(pool, bbox=(-0.3, 51.3, 0.3, 51.7))
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import httpx

# Re-export the fetcher from nature_heritage_ingester so callers can keep
# one import. Do NOT duplicate the fetch logic.
from utils.substrate.nature_heritage_ingester import (
    fetch_nhle_features as _fetch_nhle_features,
)

log = logging.getLogger("princeps.substrate.listed_buildings")

SOURCE = "listed_buildings_he"


# Public re-export (keeps public API of this module obvious).
fetch_nhle_features = _fetch_nhle_features


# ───────────────────────── Upsert into listed_buildings_he ─────────────

_UPSERT_SQL = """
    INSERT INTO listed_buildings_he
        (list_entry_id, name, grade, entry_class, designated_date,
         local_planning_authority, source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5::date, $6, now(),
            ST_SetSRID(ST_GeomFromGeoJSON($7), 4326)::geography,
            $8::jsonb)
    ON CONFLICT (list_entry_id) DO UPDATE SET
        name        = EXCLUDED.name,
        grade       = EXCLUDED.grade,
        entry_class = EXCLUDED.entry_class,
        designated_date = EXCLUDED.designated_date,
        local_planning_authority = EXCLUDED.local_planning_authority,
        source_updated_at = EXCLUDED.source_updated_at,
        geom        = EXCLUDED.geom,
        raw         = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""


def _ensure_point(geom: dict[str, Any] | None) -> dict[str, Any] | None:
    """Coerce the NHLE geometry to a Point — HE occasionally returns
    MultiPoint or Polygon for complex listings. We take the centroid
    (approximated as the first coord) so the Point column always fits."""
    if not geom:
        return None
    gtype = (geom.get("type") or "").lower()
    coords = geom.get("coordinates")
    if gtype == "point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return {"type": "Point", "coordinates": [coords[0], coords[1]]}
    if gtype == "multipoint" and coords:
        first = coords[0]
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            return {"type": "Point", "coordinates": [first[0], first[1]]}
    if gtype == "polygon" and coords:
        # Rough centroid via first ring's first vertex — good enough for
        # 500 m DMPO buffer tests and faster than PostGIS ST_Centroid.
        try:
            ring = coords[0]
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            return {"type": "Point", "coordinates": [sum(xs) / len(xs), sum(ys) / len(ys)]}
        except Exception:
            return None
    return None


async def upsert_listed_buildings(
    pool, features: list[dict[str, Any]],
) -> dict[str, int]:
    if not features:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    inserted = updated = skipped = 0
    async with pool.acquire() as conn:
        for feat in features:
            props = feat.get("properties") or {}
            list_id = str(
                props.get("ListEntry") or props.get("LISTENTRY")
                or props.get("list_entry_id") or props.get("OBJECTID") or ""
            )
            if not list_id:
                skipped += 1
                continue
            point = _ensure_point(feat.get("geometry"))
            if not point:
                skipped += 1
                continue
            entry_class = (
                props.get("entry_class") or props.get("HeritageCategory")
                or "listed_building"
            )
            # Normalise HE's category names to our enum values.
            ec_norm = entry_class.lower().replace(" ", "_").replace("-", "_")
            if ec_norm not in {
                "listed_building", "scheduled_monument", "park_garden",
                "protected_wreck", "battlefield", "world_heritage_site",
                "conservation_area",
            }:
                ec_norm = "listed_building"

            try:
                row = await conn.fetchrow(
                    _UPSERT_SQL,
                    list_id,
                    props.get("Name") or props.get("name"),
                    props.get("Grade") or props.get("grade"),
                    ec_norm,
                    props.get("date_designated") or None,
                    props.get("lpa") or props.get("LocalPlanningAuthority"),
                    json.dumps(point),
                    json.dumps(props),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("listed_buildings upsert list_id=%s failed: %s", list_id, e)
                skipped += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ───────────────────────── Entry point ─────────────────────────────────

async def ingest_listed_buildings(
    pool, bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Fetch NHLE listed buildings in bbox + upsert into ``listed_buildings_he``."""
    run_id = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO constraint_layers_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            "listed_buildings_he", json.dumps(list(bbox)),
        )

    try:
        async with httpx.AsyncClient(timeout=90.0, headers={
            "User-Agent": "Princeps listed-buildings ingester (contact@princeps.energy)",
        }) as client:
            feats = await fetch_nhle_features(bbox, client=client)
        counts = await upsert_listed_buildings(pool, feats)
    except Exception as e:
        log.exception("listed_buildings ingest failed")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE constraint_layers_ingest_log "
                "SET finished_at=now(), status='failed', error_message=$1 WHERE id=$2",
                str(e), run_id,
            )
        return {"layer": "listed_buildings_he", "error": str(e)}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE constraint_layers_ingest_log "
            "SET finished_at=now(), status='ok', rows_inserted=$1, rows_updated=$2 "
            "WHERE id=$3",
            counts["inserted"], counts["updated"], run_id,
        )
    return {"layer": "listed_buildings_he", "bbox": bbox, **counts}


# ───────────────────────── CLI ─────────────────────────────────────────

def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be minLon,minLat,maxLon,maxLat — got {s!r}")
    return tuple(parts)  # type: ignore[return-value]


async def _cli():
    if len(sys.argv) < 2:
        print("usage: python -m utils.substrate.listed_buildings_ingester <bbox>")
        sys.exit(2)
    bbox = _parse_bbox(sys.argv[1])
    from app.deps import get_pool
    pool = await get_pool()
    try:
        result = await ingest_listed_buildings(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())


__all__ = [
    "fetch_nhle_features",
    "upsert_listed_buildings",
    "ingest_listed_buildings",
]
