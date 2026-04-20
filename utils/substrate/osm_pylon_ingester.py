"""OSM pylon / overhead-line ingester (Overpass API).

Queries OpenStreetMap for the four tags that describe the overhead
electricity network visible in the basemap:

  * ``power=tower`` — transmission pylons (usually > 132 kV)
  * ``power=pole``  — distribution poles (usually 11–33 kV, wooden)
  * ``power=line``  — high-voltage circuits
  * ``power=minor_line`` — distribution circuits

Results upsert into ``substrate_pylons`` (points) and
``substrate_overhead_lines`` (polylines). Voltage is parsed from
``voltage`` tag values like ``"400000"`` or ``"275000;132000"`` and
stored in kV. The upsert keys on (osm_type, osm_id) so re-runs are safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("princeps.substrate.osm_pylons")

OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# Overpass query template — one call returns both points (pylons/poles) and
# ways (lines/minor_lines) for the bbox.
_QUERY_TEMPLATE = """[out:json][timeout:90][bbox:{south},{west},{north},{east}];
(
  node["power"="tower"];
  node["power"="pole"];
  way["power"="line"];
  way["power"="minor_line"];
);
out body geom tags;
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_voltage_kv(raw: Optional[str]) -> Optional[float]:
    """Return max voltage in kV from an OSM voltage tag value."""
    if not raw:
        return None
    # Sanitise common variants: "400000", "275 kV", "275000;132000".
    parts = raw.replace(",", ";").split(";")
    values: list[float] = []
    for p in parts:
        p = p.strip().lower().replace("kv", "")
        try:
            v = float(p)
            if v > 1000:  # tag in volts
                v /= 1000.0
            values.append(v)
        except ValueError:
            continue
    return max(values) if values else None


def _parse_numeric(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(str(raw).split()[0])
    except (ValueError, IndexError):
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    v = _parse_numeric(raw)
    return int(v) if v is not None else None


# ---------------------------------------------------------------------------
# Fetch + upsert
# ---------------------------------------------------------------------------

@dataclass
class OsmPylonIngestResult:
    pylons: int = 0
    overhead_lines: int = 0
    error: Optional[str] = None


async def _overpass_fetch(
    client: httpx.AsyncClient,
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    min_lon, min_lat, max_lon, max_lat = bbox
    query = _QUERY_TEMPLATE.format(
        south=min_lat, west=min_lon, north=max_lat, east=max_lon
    )
    for attempt in range(3):
        try:
            r = await client.post(OVERPASS_URL, data={"data": query}, timeout=120)
        except httpx.HTTPError as exc:
            log.warning("Overpass transport error (attempt %d): %s", attempt + 1, exc)
            await asyncio.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            log.warning("Overpass %d — backing off (attempt %d)", r.status_code, attempt + 1)
            await asyncio.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json().get("elements", [])
    return []


async def _upsert_pylon(conn, el: dict) -> None:
    tags = el.get("tags", {}) or {}
    lat, lon = el.get("lat"), el.get("lon")
    if lat is None or lon is None:
        return
    osm_type = "tower" if tags.get("power") == "tower" else "pole"
    wkt = f"POINT({lon} {lat})"
    await conn.execute("""
        INSERT INTO substrate_pylons
            (osm_id, osm_type, voltage_kv, operator, height_m, material, attrs, geom)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb,
                ST_Transform(ST_SetSRID(ST_GeomFromText($8),4326),27700))
        ON CONFLICT (osm_type, osm_id) DO UPDATE
            SET voltage_kv = EXCLUDED.voltage_kv,
                operator = EXCLUDED.operator,
                height_m = EXCLUDED.height_m,
                material = EXCLUDED.material,
                attrs = EXCLUDED.attrs,
                geom = EXCLUDED.geom,
                fetched_at = now()
    """,
        el.get("id"),
        osm_type,
        _parse_voltage_kv(tags.get("voltage")),
        tags.get("operator"),
        _parse_numeric(tags.get("height")),
        tags.get("material"),
        json.dumps(tags),
        wkt,
    )


async def _upsert_line(conn, el: dict) -> None:
    tags = el.get("tags", {}) or {}
    geometry = el.get("geometry") or []
    if len(geometry) < 2:
        return
    coords = ",".join(f"{p['lon']} {p['lat']}" for p in geometry if p.get("lon") and p.get("lat"))
    if not coords:
        return
    osm_type = "line" if tags.get("power") == "line" else "minor_line"
    wkt = f"MULTILINESTRING(({coords}))"
    await conn.execute("""
        INSERT INTO substrate_overhead_lines
            (osm_id, osm_type, voltage_kv, operator, circuits, cables, frequency_hz, attrs, geom)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromText($9),4326),27700)))
        ON CONFLICT (osm_type, osm_id) DO UPDATE
            SET voltage_kv = EXCLUDED.voltage_kv,
                operator = EXCLUDED.operator,
                circuits = EXCLUDED.circuits,
                cables = EXCLUDED.cables,
                frequency_hz = EXCLUDED.frequency_hz,
                attrs = EXCLUDED.attrs,
                geom = EXCLUDED.geom,
                fetched_at = now()
    """,
        el.get("id"),
        osm_type,
        _parse_voltage_kv(tags.get("voltage")),
        tags.get("operator"),
        _parse_int(tags.get("circuits")),
        _parse_int(tags.get("cables")),
        _parse_numeric(tags.get("frequency")),
        json.dumps(tags),
        wkt,
    )


async def fetch_pylons_and_lines(
    bbox: tuple[float, float, float, float],
    pool,
) -> OsmPylonIngestResult:
    """Query Overpass for pylons + overhead lines in bbox and upsert."""
    async with httpx.AsyncClient() as client:
        try:
            elements = await _overpass_fetch(client, bbox)
        except Exception as exc:
            return OsmPylonIngestResult(error=str(exc))

    result = OsmPylonIngestResult()
    if not elements:
        return result

    async with pool.acquire() as conn:
        for el in elements:
            try:
                if el.get("type") == "node":
                    await _upsert_pylon(conn, el)
                    result.pylons += 1
                elif el.get("type") == "way":
                    await _upsert_line(conn, el)
                    result.overhead_lines += 1
            except Exception as exc:
                log.debug("Upsert skipped for osm %s/%s: %s",
                          el.get("type"), el.get("id"), exc)

    log.info("OSM pylons/lines ingested: pylons=%d lines=%d",
             result.pylons, result.overhead_lines)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m utils.substrate.osm_pylon_ingester min_lon,min_lat,max_lon,max_lat")
        sys.exit(1)

    bbox = tuple(float(x) for x in sys.argv[1].split(","))
    if len(bbox) != 4:
        print("bbox must be 4 comma-separated numbers")
        sys.exit(1)

    async def _main():
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/feasibly")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
        res = await fetch_pylons_and_lines(bbox, pool)
        log.info("done: pylons=%d lines=%d error=%s", res.pylons, res.overhead_lines, res.error)
        await pool.close()

    asyncio.run(_main())
