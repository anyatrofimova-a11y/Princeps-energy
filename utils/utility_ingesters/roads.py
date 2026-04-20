"""
roads.py — OSM `highway=primary|secondary|tertiary|service|unclassified|residential`
ingester → utility_roads, with a derived access_class for the DC-twin site
access rendering.

CLI:
    python -m utils.utility_ingesters.roads --bbox='-0.2,51.3,0.2,51.7'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

import asyncpg

from utils.utility_ingesters import ensure_schema, parse_bbox, run_overpass

log = logging.getLogger("princeps.utility_ingesters.roads")

_HIGHWAY_TYPES = (
    "primary", "secondary", "tertiary",
    "unclassified", "residential", "service",
)

# Mapping from OSM highway tag → DC-twin access class bucket.
#   strategic — A-road grade, suitable for 44t abnormal loads after surveys
#   local     — B-class distributor, typical last-mile HGV routing
#   site      — service / residential / unclassified, site-access only
_ACCESS_CLASS = {
    "primary":      "strategic",
    "secondary":    "strategic",
    "tertiary":     "local",
    "unclassified": "local",
    "residential":  "site",
    "service":      "site",
}


def _build_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    regex = "|".join(_HIGHWAY_TYPES)
    return f"""
[out:json][timeout:60];
(
  way["highway"~"^({regex})$"]({south},{west},{north},{east});
);
out geom tags;
""".strip()


def _classify(highway: str | None) -> str | None:
    if not highway:
        return None
    return _ACCESS_CLASS.get(highway.lower())


def _parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {}) or {}
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None
    coords = [(pt["lon"], pt["lat"]) for pt in geom if "lon" in pt and "lat" in pt]
    if len(coords) < 2:
        return None

    highway = tags.get("highway")
    return {
        "osm_id": el.get("id"),
        "name": tags.get("name"),
        "ref": tags.get("ref"),
        "highway": highway,
        "access_class": _classify(highway),
        "surface": tags.get("surface"),
        "maxspeed": tags.get("maxspeed"),
        "coords": coords,
        "tags": tags,
    }


async def _upsert(conn: asyncpg.Connection, rows: list[dict]) -> int:
    count = 0
    for r in rows:
        coords = r["coords"]
        coord_str = ", ".join(f"{lon} {lat}" for lon, lat in coords)
        wkt = f"LINESTRING({coord_str})"
        try:
            await conn.execute(
                """
                INSERT INTO utility_roads
                    (osm_id, name, ref, highway, access_class,
                     surface, maxspeed, geom, tags, updated_at)
                VALUES ($1, $2, $3, $4, $5,
                        $6, $7,
                        ST_Transform(ST_GeomFromText($8, 4326), 27700),
                        $9::jsonb, NOW())
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    ref = EXCLUDED.ref,
                    highway = EXCLUDED.highway,
                    access_class = EXCLUDED.access_class,
                    surface = EXCLUDED.surface,
                    maxspeed = EXCLUDED.maxspeed,
                    geom = EXCLUDED.geom,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                """,
                r["osm_id"], r["name"], r["ref"], r["highway"], r["access_class"],
                r["surface"], r["maxspeed"], wkt, json.dumps(r["tags"], default=str),
            )
            count += 1
        except Exception as e:
            log.debug("road upsert failed for osm_id=%s: %s", r.get("osm_id"), e)
    return count


async def ingest(
    pool: asyncpg.Pool,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    if bbox is None:
        return {"status": "skipped", "reason": "bbox required"}

    query = _build_query(bbox)
    data = await run_overpass(query)
    rows = [r for r in (_parse_element(e) for e in data.get("elements", [])) if r]

    if dry_run:
        return {"status": "dry_run", "fetched": len(rows), "upserted": 0}

    async with pool.acquire() as conn:
        await ensure_schema(conn)
        upserted = await _upsert(conn, rows)

    log.info("roads: bbox=%s fetched=%d upserted=%d", bbox, len(rows), upserted)
    return {"status": "success", "fetched": len(rows), "upserted": upserted, "bbox": list(bbox)}


async def _cli_main() -> int:
    parser = argparse.ArgumentParser(description="Ingest OSM roads into utility_roads.")
    parser.add_argument("--bbox", required=True, help="Bounding box: 'w,s,e,n'")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not args.db_url:
        print("DATABASE_URL not set", flush=True)
        return 2

    bbox = parse_bbox(args.bbox)
    pool = await asyncpg.create_pool(args.db_url, min_size=1, max_size=2)
    try:
        summary = await ingest(pool, bbox=bbox, dry_run=args.dry_run)
    finally:
        await pool.close()
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("status") in ("success", "dry_run") else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(_cli_main()))
