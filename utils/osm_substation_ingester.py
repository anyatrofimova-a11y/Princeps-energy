#!/usr/bin/env python3
"""OSM Substation Ingester — comprehensive UK substation data from OpenStreetMap.

Queries Overpass API in regional chunks to avoid timeouts, then upserts into
grid_substations table. Covers all of GB including London/UKPN gap.
"""

import asyncio
import json
import logging
import sys
import time
import httpx
import asyncpg

log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Break UK into regional bounding boxes to avoid Overpass timeouts
# Format: (south, west, north, east, label)
UK_REGIONS = [
    # England - South
    (50.0, -6.0, 51.2, -2.0, "SW England"),
    (50.0, -2.0, 51.2, 2.0, "SE England (excl London)"),
    (51.2, -2.5, 51.7, 0.5, "London & Home Counties West"),
    (51.2, 0.5, 51.7, 2.0, "London & Home Counties East"),
    # England - Central
    (51.7, -3.5, 52.5, -0.5, "Central South"),
    (51.7, -0.5, 52.5, 2.0, "Central East"),
    (52.5, -3.5, 53.2, -0.5, "Midlands West"),
    (52.5, -0.5, 53.2, 1.0, "Midlands East"),
    # England - North
    (53.2, -3.5, 54.0, -1.0, "NW England"),
    (53.2, -1.0, 54.0, 0.5, "NE England South"),
    (54.0, -3.5, 55.5, 0.0, "NE England North"),
    # Wales
    (51.2, -5.5, 53.5, -2.5, "Wales"),
    # Scotland
    (55.0, -6.0, 56.5, -3.0, "Scotland South"),
    (56.5, -8.0, 58.0, -2.0, "Scotland Central"),
    (58.0, -8.0, 61.0, -1.0, "Scotland North"),
]


def _build_query(south, west, north, east):
    """Build Overpass query for substations in a bounding box."""
    return f"""[out:json][timeout:60][bbox:{south},{west},{north},{east}];
(
  node["power"="substation"];
  way["power"="substation"];
  relation["power"="substation"];
  node["power"="sub_station"];
  way["power"="sub_station"];
);
out center tags;"""


def _parse_voltage(tags):
    """Extract voltage in kV from OSM tags."""
    v = tags.get("voltage", "")
    if not v:
        # Infer from substation type
        st = tags.get("substation", "")
        if st == "transmission":
            return 275
        if st == "distribution":
            return 33
        return None
    try:
        # voltage tag is in volts, convert to kV
        # Handle ranges like "132000;33000"
        parts = v.replace(",", ";").split(";")
        voltages = []
        for p in parts:
            p = p.strip().replace("kV", "000").replace("kv", "000")
            try:
                val = float(p)
                if val > 1000:
                    val /= 1000  # Convert V to kV
                voltages.append(val)
            except ValueError:
                pass
        return max(voltages) if voltages else None
    except Exception:
        return None


def _parse_element(el):
    """Parse an OSM element into a substation dict."""
    tags = el.get("tags", {})

    # Get coordinates
    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")

    if not lat or not lon:
        return None

    name = tags.get("name", tags.get("ref", f"OSM-{el['id']}"))
    voltage_kv = _parse_voltage(tags)
    operator = tags.get("operator", "")

    # Determine site type
    substation_type = tags.get("substation", "")
    if substation_type == "transmission":
        site_type = "transmission"
    elif substation_type == "distribution":
        site_type = "distribution"
    elif voltage_kv and voltage_kv >= 132:
        site_type = "transmission"
    elif voltage_kv and voltage_kv >= 11:
        site_type = "distribution"
    else:
        site_type = "unknown"

    return {
        "external_id": f"osm-{el['id']}",
        "name": name,
        "lat": lat,
        "lon": lon,
        "voltage_kv": voltage_kv,
        "operator": operator,
        "site_type": site_type,
        "dno": "osm",
    }


async def fetch_region(client, south, west, north, east, label):
    """Fetch substations for one region from Overpass."""
    query = _build_query(south, west, north, east)
    for attempt in range(3):
        try:
            r = await client.post(OVERPASS_URL, data={"data": query}, timeout=90)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                log.warning("[%s] Rate limited, waiting %ds...", label, wait)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            elements = data.get("elements", [])
            subs = []
            for el in elements:
                parsed = _parse_element(el)
                if parsed:
                    subs.append(parsed)
            log.info("[%s] Found %d substations", label, len(subs))
            return subs
        except Exception as e:
            log.warning("[%s] Attempt %d failed: %s", label, attempt + 1, e)
            await asyncio.sleep(10 * (attempt + 1))
    return []


async def ingest_all(db_url="postgresql://localhost:5432/feasibly"):
    """Ingest all UK substations from OSM into PostGIS."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    log.info("Connected to database")

    # First, delete old OSM data to avoid duplicates
    async with pool.acquire() as conn:
        old_count = await conn.fetchval("SELECT COUNT(*) FROM grid_substations WHERE dno = 'osm'")
        log.info("Existing OSM substations: %d", old_count)

    all_subs = []
    async with httpx.AsyncClient() as client:
        # Process regions sequentially to respect Overpass rate limits
        for south, west, north, east, label in UK_REGIONS:
            subs = await fetch_region(client, south, west, north, east, label)
            all_subs.extend(subs)
            # Rate limit: Overpass asks for 1 request per 5 seconds
            await asyncio.sleep(6)

    log.info("Total substations fetched: %d", len(all_subs))

    # Deduplicate by external_id
    seen = set()
    unique = []
    for s in all_subs:
        if s["external_id"] not in seen:
            seen.add(s["external_id"])
            unique.append(s)
    log.info("Unique substations: %d", len(unique))

    # Upsert into database
    async with pool.acquire() as conn:
        inserted = 0
        updated = 0
        for s in unique:
            try:
                result = await conn.execute("""
                    INSERT INTO grid_substations (external_id, name, dno, voltage_kv, site_type, geom)
                    VALUES ($1, $2, $3, $4, $5, ST_Transform(ST_SetSRID(ST_MakePoint($6, $7), 4326), 27700))
                    ON CONFLICT (external_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        voltage_kv = COALESCE(EXCLUDED.voltage_kv, grid_substations.voltage_kv),
                        site_type = COALESCE(EXCLUDED.site_type, grid_substations.site_type)
                """, s["external_id"], s["name"], s["dno"],
                    s["voltage_kv"], s["site_type"], s["lon"], s["lat"])
                if "INSERT" in result:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("Failed to upsert %s: %s", s["external_id"], e)

        log.info("Inserted: %d, Updated: %d", inserted, updated)

    # Final count
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM grid_substations")
        osm_count = await conn.fetchval("SELECT COUNT(*) FROM grid_substations WHERE dno = 'osm'")
        log.info("Final totals — OSM: %d, All: %d", osm_count, total)

    await pool.close()
    return {"inserted": inserted, "updated": updated, "total_fetched": len(unique)}


if __name__ == "__main__":
    result = asyncio.run(ingest_all())
    print(json.dumps(result))
