"""
waterways.py — OSM `waterway=river|canal|stream` ingester → utility_waterways.

CLI:
    python -m utils.utility_ingesters.waterways --bbox='-0.2,51.3,0.2,51.7'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

import asyncpg

from utils.utility_ingesters import ensure_schema, parse_bbox, run_overpass

log = logging.getLogger("princeps.utility_ingesters.waterways")

# Waterway classes we care about for DC site context (water intake / EA flood
# risk / culverting constraints). Drains, ditches, tidal channels are skipped
# to keep the row count sane.
_WATERWAY_TYPES = ("river", "canal", "stream")


def _build_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    regex = "|".join(_WATERWAY_TYPES)
    # Overpass bbox is (south, west, north, east)
    return f"""
[out:json][timeout:60];
(
  way["waterway"~"^({regex})$"]({south},{west},{north},{east});
);
out geom tags;
""".strip()


def _parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {}) or {}
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None
    coords = [(pt["lon"], pt["lat"]) for pt in geom if "lon" in pt and "lat" in pt]
    if len(coords) < 2:
        return None

    width = tags.get("width")
    try:
        width_m = float(width) if width else None
    except (TypeError, ValueError):
        width_m = None

    return {
        "osm_id": el.get("id"),
        "name": tags.get("name"),
        "waterway": tags.get("waterway"),
        "width_m": width_m,
        "intermittent": (tags.get("intermittent") == "yes"),
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
                INSERT INTO utility_waterways
                    (osm_id, name, waterway, width_m, intermittent, geom, tags, updated_at)
                VALUES ($1, $2, $3, $4, $5,
                        ST_Transform(ST_GeomFromText($6, 4326), 27700),
                        $7::jsonb, NOW())
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    waterway = EXCLUDED.waterway,
                    width_m = COALESCE(EXCLUDED.width_m, utility_waterways.width_m),
                    intermittent = EXCLUDED.intermittent,
                    geom = EXCLUDED.geom,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                """,
                r["osm_id"], r["name"], r["waterway"], r["width_m"],
                r["intermittent"], wkt, json.dumps(r["tags"], default=str),
            )
            count += 1
        except Exception as e:
            log.debug("waterway upsert failed for osm_id=%s: %s", r.get("osm_id"), e)
    return count


async def ingest(
    pool: asyncpg.Pool,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Fetch + upsert OSM waterways within the bbox.

    If bbox is None we refuse to run — a nationwide Overpass query for all
    rivers/streams is far too heavy. Call with per-region tiles if you want
    full UK coverage (future work; out of scope for this swarm pass).
    """
    if bbox is None:
        return {"status": "skipped", "reason": "bbox required (nationwide query too heavy)"}

    query = _build_query(bbox)
    data = await run_overpass(query)
    rows = [r for r in (_parse_element(e) for e in data.get("elements", [])) if r]

    if dry_run:
        return {"status": "dry_run", "fetched": len(rows), "upserted": 0}

    async with pool.acquire() as conn:
        await ensure_schema(conn)
        upserted = await _upsert(conn, rows)

    log.info("waterways: bbox=%s fetched=%d upserted=%d", bbox, len(rows), upserted)
    return {"status": "success", "fetched": len(rows), "upserted": upserted, "bbox": list(bbox)}


# ─── CLI ───────────────────────────────────────────────────────────────────

async def _cli_main() -> int:
    parser = argparse.ArgumentParser(description="Ingest OSM waterways into utility_waterways.")
    parser.add_argument("--bbox", required=True, help="Bounding box: 'w,s,e,n' (WGS84 lon/lat)")
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
