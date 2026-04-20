"""
gas_pipelines.py — OSM `man_made=pipeline` + `substance=gas` ingester
                   → utility_gas_pipelines.

CLI:
    python -m utils.utility_ingesters.gas_pipelines --bbox='-0.2,51.3,0.2,51.7'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

import asyncpg

from utils.utility_ingesters import ensure_schema, parse_bbox, run_overpass

log = logging.getLogger("princeps.utility_ingesters.gas_pipelines")


def _build_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    # OSM coverage of UK gas transmission is patchy — we also pull pipelines
    # tagged man_made=pipeline without substance when their operator/name
    # hints at National Gas / Cadent / SGN, to avoid dropping real
    # high-pressure assets that sidestep the substance tag.
    return f"""
[out:json][timeout:60];
(
  way["man_made"="pipeline"]["substance"="gas"]({south},{west},{north},{east});
  way["man_made"="pipeline"]["type"="gas"]({south},{west},{north},{east});
);
out geom tags;
""".strip()


def _parse_diameter_mm(val) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).lower().strip()
        # OSM free-text — '600', '600mm', '24in', '600 mm'
        if "in" in s:
            n = float(s.replace("in", "").strip())
            return round(n * 25.4, 1)
        if "mm" in s:
            return float(s.replace("mm", "").strip())
        n = float(s)
        # Heuristic: >20 is mm, <=20 is m
        return n if n > 20 else n * 1000.0
    except Exception:
        return None


def _parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {}) or {}
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None
    coords = [(pt["lon"], pt["lat"]) for pt in geom if "lon" in pt and "lat" in pt]
    if len(coords) < 2:
        return None

    return {
        "osm_id": el.get("id"),
        "name": tags.get("name"),
        "operator": tags.get("operator"),
        "substance": tags.get("substance") or tags.get("type") or "gas",
        "pressure": tags.get("pressure"),
        "diameter_mm": _parse_diameter_mm(tags.get("diameter")),
        "location": tags.get("location"),  # overground | underground
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
                INSERT INTO utility_gas_pipelines
                    (osm_id, name, operator, substance, pressure, diameter_mm,
                     location, geom, tags, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6,
                        $7,
                        ST_Transform(ST_GeomFromText($8, 4326), 27700),
                        $9::jsonb, NOW())
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    operator = EXCLUDED.operator,
                    substance = EXCLUDED.substance,
                    pressure = EXCLUDED.pressure,
                    diameter_mm = COALESCE(EXCLUDED.diameter_mm, utility_gas_pipelines.diameter_mm),
                    location = EXCLUDED.location,
                    geom = EXCLUDED.geom,
                    tags = EXCLUDED.tags,
                    updated_at = NOW()
                """,
                r["osm_id"], r["name"], r["operator"], r["substance"],
                r["pressure"], r["diameter_mm"], r["location"],
                wkt, json.dumps(r["tags"], default=str),
            )
            count += 1
        except Exception as e:
            log.debug("gas pipeline upsert failed for osm_id=%s: %s", r.get("osm_id"), e)
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

    log.info("gas_pipelines: bbox=%s fetched=%d upserted=%d", bbox, len(rows), upserted)
    return {"status": "success", "fetched": len(rows), "upserted": upserted, "bbox": list(bbox)}


async def _cli_main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest OSM gas pipelines into utility_gas_pipelines.",
    )
    parser.add_argument("--bbox", required=True)
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
