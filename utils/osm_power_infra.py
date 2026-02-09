"""
OSM Power Infrastructure — real power lines, substations, towers, generators, plants
sourced from OpenStreetMap via the Overpass API.

Creates 6 PostGIS tables (SRID 4326) and provides GeoJSON query functions
with bbox + voltage filtering for the frontend map.
"""
import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.osm_power")

# ---------------------------------------------------------------------------
# Overpass API configuration
# ---------------------------------------------------------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT = 120  # seconds per query
REQUEST_INTERVAL = 15   # seconds between Overpass requests (rate limit)

# UK bounding box split into 2x2 degree cells for chunked fetching
# SE England cells are seeded first (most data-dense)
UK_CELLS = [
    # SE England (priority)
    (50.0, -2.0, 52.0, 0.0),
    (50.0, 0.0, 52.0, 2.0),
    (52.0, -2.0, 54.0, 0.0),
    (52.0, 0.0, 54.0, 2.0),
    # Rest of England + Wales
    (50.0, -6.0, 52.0, -2.0),
    (52.0, -6.0, 54.0, -2.0),
    (54.0, -6.0, 56.0, -2.0),
    (54.0, -2.0, 56.0, 2.0),
    # Scotland
    (56.0, -8.0, 58.0, -2.0),
    (56.0, -2.0, 58.0, 0.0),
    (58.0, -8.0, 60.0, -2.0),
    (58.0, -2.0, 60.0, 0.0),
]


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------
async def setup_tables(conn):
    """Create OSM power infrastructure tables if they don't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS osm_power_line (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            line_type TEXT,         -- cable, line, minor_line
            operator TEXT,
            name TEXT,
            ref TEXT,
            cables INT,
            circuits INT,
            frequency TEXT,
            tags JSONB,
            geometry GEOMETRY(LineString, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_line_geom ON osm_power_line USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_osm_power_line_voltage ON osm_power_line (voltage_kv);

        CREATE TABLE IF NOT EXISTS osm_power_substation (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            substation_type TEXT,   -- transmission, distribution, etc
            operator TEXT,
            name TEXT,
            ref TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_sub_geom ON osm_power_substation USING GIST (geometry);

        CREATE TABLE IF NOT EXISTS osm_power_tower (
            osm_id BIGINT PRIMARY KEY,
            tower_type TEXT,        -- tower, pole, portal, ...
            design TEXT,
            material TEXT,
            height REAL,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_tower_geom ON osm_power_tower USING GIST (geometry);

        CREATE TABLE IF NOT EXISTS osm_power_transformer (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            rating TEXT,
            name TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_xfmr_geom ON osm_power_transformer USING GIST (geometry);

        CREATE TABLE IF NOT EXISTS osm_power_generator (
            osm_id BIGINT PRIMARY KEY,
            source TEXT,            -- solar, wind, gas, nuclear, hydro, biomass ...
            output_kw REAL,
            output_raw TEXT,
            method TEXT,            -- photovoltaic, wind_turbine, ...
            name TEXT,
            operator TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_gen_geom ON osm_power_generator USING GIST (geometry);

        CREATE TABLE IF NOT EXISTS osm_power_plant (
            osm_id BIGINT PRIMARY KEY,
            source TEXT,
            output_mw REAL,
            output_raw TEXT,
            name TEXT,
            operator TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_plant_geom ON osm_power_plant USING GIST (geometry);
    """)
    log.info("OSM power infrastructure tables ready")


# ---------------------------------------------------------------------------
# Voltage parser
# ---------------------------------------------------------------------------
def parse_voltage_kv(raw: str | None) -> float | None:
    """Parse OSM voltage string (e.g. '400000', '400000;132000') -> max kV."""
    if not raw:
        return None
    # Extract all numeric values
    nums = re.findall(r"[\d.]+", raw)
    if not nums:
        return None
    try:
        volts = [float(n) for n in nums]
        max_v = max(volts)
        # OSM stores volts; convert to kV
        return max_v / 1000.0 if max_v > 1000 else max_v
    except (ValueError, TypeError):
        return None


def parse_output_kw(raw: str | None) -> float | None:
    """Parse OSM generator:output (e.g. '50 MW', '100 kW', '2000') -> kW."""
    if not raw:
        return None
    raw = raw.strip().lower()
    m = re.search(r"([\d.]+)\s*(mw|kw|w|gw)?", raw)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or "w"
    if unit == "gw":
        return val * 1_000_000
    if unit == "mw":
        return val * 1000
    if unit == "kw":
        return val
    return val / 1000  # watts to kW


def parse_output_mw(raw: str | None) -> float | None:
    """Parse plant:output -> MW."""
    kw = parse_output_kw(raw)
    return kw / 1000 if kw else None


# ---------------------------------------------------------------------------
# Overpass query builder & fetcher
# ---------------------------------------------------------------------------
def _overpass_query(south: float, west: float, north: float, east: float) -> str:
    """Build Overpass QL query for all power features in a bbox."""
    bbox = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  way["power"="line"]({bbox});
  way["power"="cable"]({bbox});
  way["power"="minor_line"]({bbox});
  node["power"="substation"]({bbox});
  way["power"="substation"]({bbox});
  relation["power"="substation"]({bbox});
  node["power"="tower"]({bbox});
  node["power"="pole"]({bbox});
  node["power"="portal"]({bbox});
  node["power"="transformer"]({bbox});
  node["power"="generator"]({bbox});
  way["power"="generator"]({bbox});
  node["power"="plant"]({bbox});
  way["power"="plant"]({bbox});
  relation["power"="plant"]({bbox});
);
out body;
>;
out skel qt;
"""


async def _fetch_overpass(query: str) -> dict | None:
    """Execute an Overpass API query. Returns JSON response or None on error."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(OVERPASS_TIMEOUT + 30)) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            if resp.status_code == 429:
                log.warning("Overpass rate limited, waiting 30s...")
                await asyncio.sleep(30)
                resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.error("Overpass fetch failed: %s", e)
        return None


def _build_node_lookup(elements: list[dict]) -> dict[int, tuple[float, float]]:
    """Build id -> (lon, lat) lookup from Overpass elements."""
    return {
        e["id"]: (e["lon"], e["lat"])
        for e in elements
        if e["type"] == "node" and "lon" in e and "lat" in e
    }


def _way_to_linestring(way: dict, nodes: dict) -> list[list[float]] | None:
    """Convert an Overpass way to [[lon,lat], ...] coordinate array."""
    coords = []
    for nid in way.get("nodes", []):
        pt = nodes.get(nid)
        if pt:
            coords.append(list(pt))
    return coords if len(coords) >= 2 else None


def _way_to_centroid(way: dict, nodes: dict) -> tuple[float, float] | None:
    """Get centroid of a way as (lon, lat)."""
    coords = _way_to_linestring(way, nodes)
    if not coords:
        return None
    avg_lon = sum(c[0] for c in coords) / len(coords)
    avg_lat = sum(c[1] for c in coords) / len(coords)
    return (avg_lon, avg_lat)


# ---------------------------------------------------------------------------
# Upsert parsed features into PostGIS
# ---------------------------------------------------------------------------
async def _upsert_lines(conn, elements: list, nodes: dict):
    """Upsert power lines/cables into osm_power_line."""
    count = 0
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags", {})
        power = tags.get("power", "")
        if power not in ("line", "cable", "minor_line"):
            continue
        coords = _way_to_linestring(e, nodes)
        if not coords:
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        geom_wkt = "LINESTRING(" + ",".join(f"{c[0]} {c[1]}" for c in coords) + ")"
        await conn.execute("""
            INSERT INTO osm_power_line (osm_id, voltage_kv, voltage_raw, line_type, operator, name, ref,
                cables, circuits, frequency, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    ST_GeomFromText($12, 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv, voltage_raw = EXCLUDED.voltage_raw,
                line_type = EXCLUDED.line_type, operator = EXCLUDED.operator,
                name = EXCLUDED.name, tags = EXCLUDED.tags, geometry = EXCLUDED.geometry,
                fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"), power,
            tags.get("operator"), tags.get("name"), tags.get("ref"),
            int(tags["cables"]) if tags.get("cables", "").isdigit() else None,
            int(tags["circuits"]) if tags.get("circuits", "").isdigit() else None,
            tags.get("frequency"),
            json.dumps({k: v for k, v in tags.items() if k not in ("power", "voltage", "operator", "name", "ref", "cables", "circuits", "frequency")}),
            geom_wkt,
        )
        count += 1
    return count


async def _upsert_substations(conn, elements: list, nodes: dict):
    """Upsert substations (node or way centroid)."""
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        if tags.get("power") != "substation":
            continue
        if e["type"] == "node" and "lon" in e:
            lon, lat = e["lon"], e["lat"]
        elif e["type"] in ("way", "relation"):
            pt = _way_to_centroid(e, nodes)
            if not pt:
                continue
            lon, lat = pt
        else:
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        await conn.execute("""
            INSERT INTO osm_power_substation (osm_id, voltage_kv, voltage_raw, substation_type,
                operator, name, ref, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, ST_SetSRID(ST_MakePoint($9, $10), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv, name = EXCLUDED.name,
                operator = EXCLUDED.operator, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"), tags.get("substation"),
            tags.get("operator"), tags.get("name"), tags.get("ref"),
            json.dumps({k: v for k, v in tags.items() if k not in ("power", "voltage", "substation", "operator", "name", "ref")}),
            lon, lat,
        )
        count += 1
    return count


async def _upsert_towers(conn, elements: list, nodes: dict):
    """Upsert towers/poles."""
    count = 0
    for e in elements:
        if e["type"] != "node" or "lon" not in e:
            continue
        tags = e.get("tags", {})
        power = tags.get("power", "")
        if power not in ("tower", "pole", "portal"):
            continue
        height_raw = tags.get("height", "")
        height = None
        if height_raw:
            m = re.search(r"[\d.]+", height_raw)
            if m:
                height = float(m.group())
        await conn.execute("""
            INSERT INTO osm_power_tower (osm_id, tower_type, design, material, height, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($7, $8), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                tower_type = EXCLUDED.tower_type, design = EXCLUDED.design,
                tags = EXCLUDED.tags, geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], power, tags.get("design"), tags.get("material"),
            height,
            json.dumps({k: v for k, v in tags.items() if k not in ("power", "design", "material", "height")}),
            e["lon"], e["lat"],
        )
        count += 1
    return count


async def _upsert_transformers(conn, elements: list, nodes: dict):
    """Upsert transformers."""
    count = 0
    for e in elements:
        if e["type"] != "node" or "lon" not in e:
            continue
        tags = e.get("tags", {})
        if tags.get("power") != "transformer":
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        await conn.execute("""
            INSERT INTO osm_power_transformer (osm_id, voltage_kv, voltage_raw, rating, name, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, ST_SetSRID(ST_MakePoint($7, $8), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv, name = EXCLUDED.name,
                tags = EXCLUDED.tags, geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"), tags.get("rating"),
            tags.get("name"),
            json.dumps({k: v for k, v in tags.items() if k not in ("power", "voltage", "rating", "name")}),
            e["lon"], e["lat"],
        )
        count += 1
    return count


async def _upsert_generators(conn, elements: list, nodes: dict):
    """Upsert generators (node or way centroid)."""
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        if tags.get("power") != "generator":
            continue
        if e["type"] == "node" and "lon" in e:
            lon, lat = e["lon"], e["lat"]
        elif e["type"] == "way":
            pt = _way_to_centroid(e, nodes)
            if not pt:
                continue
            lon, lat = pt
        else:
            continue
        output_kw = parse_output_kw(tags.get("generator:output:electricity") or tags.get("generator:output"))
        await conn.execute("""
            INSERT INTO osm_power_generator (osm_id, source, output_kw, output_raw, method, name, operator, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, ST_SetSRID(ST_MakePoint($9, $10), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                source = EXCLUDED.source, output_kw = EXCLUDED.output_kw,
                name = EXCLUDED.name, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"],
            tags.get("generator:source") or tags.get("plant:source"),
            output_kw,
            tags.get("generator:output:electricity") or tags.get("generator:output"),
            tags.get("generator:method"),
            tags.get("name"),
            tags.get("operator"),
            json.dumps({k: v for k, v in tags.items() if not k.startswith("generator:") and k not in ("power", "name", "operator")}),
            lon, lat,
        )
        count += 1
    return count


async def _upsert_plants(conn, elements: list, nodes: dict):
    """Upsert power plants (node, way centroid, or relation centroid)."""
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        if tags.get("power") != "plant":
            continue
        if e["type"] == "node" and "lon" in e:
            lon, lat = e["lon"], e["lat"]
        elif e["type"] in ("way", "relation"):
            pt = _way_to_centroid(e, nodes)
            if not pt:
                continue
            lon, lat = pt
        else:
            continue
        output_mw = parse_output_mw(tags.get("plant:output:electricity") or tags.get("plant:output"))
        await conn.execute("""
            INSERT INTO osm_power_plant (osm_id, source, output_mw, output_raw, name, operator, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, ST_SetSRID(ST_MakePoint($8, $9), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                source = EXCLUDED.source, output_mw = EXCLUDED.output_mw,
                name = EXCLUDED.name, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"],
            tags.get("plant:source") or tags.get("generator:source"),
            output_mw,
            tags.get("plant:output:electricity") or tags.get("plant:output"),
            tags.get("name"),
            tags.get("operator"),
            json.dumps({k: v for k, v in tags.items() if not k.startswith("plant:") and k not in ("power", "name", "operator")}),
            lon, lat,
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Seed — fetch from Overpass and populate tables
# ---------------------------------------------------------------------------
async def seed_power_infra(pool):
    """Fetch UK power infrastructure from Overpass API and upsert into PostGIS.
    Skips cells that already have data. Designed to run as a background task.
    """
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT count(*) FROM osm_power_line")
        if existing > 100:
            log.info("OSM power lines already seeded (%d rows), skipping", existing)
            return

    log.info("Seeding OSM power infrastructure from Overpass API (%d cells)...", len(UK_CELLS))

    for i, (south, west, north, east) in enumerate(UK_CELLS):
        query = _overpass_query(south, west, north, east)
        log.info("Fetching cell %d/%d: (%.1f,%.1f)-(%.1f,%.1f)",
                 i + 1, len(UK_CELLS), south, west, north, east)

        data = await _fetch_overpass(query)
        if not data or "elements" not in data:
            log.warning("No data for cell %d, skipping", i + 1)
            if i < len(UK_CELLS) - 1:
                await asyncio.sleep(REQUEST_INTERVAL)
            continue

        elements = data["elements"]
        nodes = _build_node_lookup(elements)
        log.info("Cell %d: %d elements, %d nodes", i + 1, len(elements), len(nodes))

        async with pool.acquire() as conn:
            lines = await _upsert_lines(conn, elements, nodes)
            subs = await _upsert_substations(conn, elements, nodes)
            towers = await _upsert_towers(conn, elements, nodes)
            xfmrs = await _upsert_transformers(conn, elements, nodes)
            gens = await _upsert_generators(conn, elements, nodes)
            plants = await _upsert_plants(conn, elements, nodes)
            log.info("Cell %d upserted: %d lines, %d subs, %d towers, %d xfmrs, %d gens, %d plants",
                     i + 1, lines, subs, towers, xfmrs, gens, plants)

        # Rate limit
        if i < len(UK_CELLS) - 1:
            await asyncio.sleep(REQUEST_INTERVAL)

    log.info("OSM power infrastructure seeding complete")


# ---------------------------------------------------------------------------
# GeoJSON query functions
# ---------------------------------------------------------------------------
async def power_lines_geojson(conn, bbox: tuple[float, float, float, float], min_voltage_kv: float = 0) -> dict:
    """Return power lines as GeoJSON FeatureCollection. bbox = (west, south, east, north)."""
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw, line_type, operator, name, ref,
               cables, circuits, ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_line
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
          AND (voltage_kv >= $5 OR ($5 = 0 AND voltage_kv IS NULL))
        ORDER BY voltage_kv DESC NULLS LAST
        LIMIT 5000
    """, west, south, east, north, min_voltage_kv)
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "line_type": r["line_type"],
                "operator": r["operator"],
                "name": r["name"],
                "ref": r["ref"],
                "cables": r["cables"],
                "circuits": r["circuits"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_substations_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return substations as GeoJSON FeatureCollection."""
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw, substation_type, operator, name, ref,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_substation
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        ORDER BY voltage_kv DESC NULLS LAST
        LIMIT 2000
    """, west, south, east, north)
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "substation_type": r["substation_type"],
                "operator": r["operator"],
                "name": r["name"],
                "ref": r["ref"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_towers_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return towers/poles as GeoJSON FeatureCollection."""
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, tower_type, design, material, height,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_tower
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        LIMIT 10000
    """, west, south, east, north)
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "tower_type": r["tower_type"],
                "design": r["design"],
                "material": r["material"],
                "height": r["height"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_generators_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return generators as GeoJSON FeatureCollection."""
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, source, output_kw, output_raw, method, name, operator,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_generator
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        LIMIT 5000
    """, west, south, east, north)
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "source": r["source"],
                "output_kw": r["output_kw"],
                "output_raw": r["output_raw"],
                "method": r["method"],
                "name": r["name"],
                "operator": r["operator"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_plants_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return power plants as GeoJSON FeatureCollection."""
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, source, output_mw, output_raw, name, operator,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_plant
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        LIMIT 2000
    """, west, south, east, north)
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "source": r["source"],
                "output_mw": r["output_mw"],
                "output_raw": r["output_raw"],
                "name": r["name"],
                "operator": r["operator"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_infra_summary(conn) -> dict:
    """Return counts and voltage distribution for all OSM power tables."""
    lines = await conn.fetchval("SELECT count(*) FROM osm_power_line")
    subs = await conn.fetchval("SELECT count(*) FROM osm_power_substation")
    towers = await conn.fetchval("SELECT count(*) FROM osm_power_tower")
    xfmrs = await conn.fetchval("SELECT count(*) FROM osm_power_transformer")
    gens = await conn.fetchval("SELECT count(*) FROM osm_power_generator")
    plants = await conn.fetchval("SELECT count(*) FROM osm_power_plant")

    # Voltage distribution for lines
    voltage_rows = await conn.fetch("""
        SELECT
            CASE
                WHEN voltage_kv >= 400 THEN '400kV'
                WHEN voltage_kv >= 275 THEN '275kV'
                WHEN voltage_kv >= 132 THEN '132kV'
                WHEN voltage_kv >= 66 THEN '66kV'
                WHEN voltage_kv >= 33 THEN '33kV'
                WHEN voltage_kv >= 11 THEN '11kV'
                WHEN voltage_kv > 0 THEN 'other'
                ELSE 'unknown'
            END AS band,
            count(*) AS cnt
        FROM osm_power_line
        GROUP BY band
        ORDER BY cnt DESC
    """)
    voltage_dist = {r["band"]: r["cnt"] for r in voltage_rows}

    # Generator source distribution
    gen_rows = await conn.fetch("""
        SELECT COALESCE(source, 'unknown') AS src, count(*) AS cnt
        FROM osm_power_generator
        GROUP BY src ORDER BY cnt DESC LIMIT 20
    """)
    gen_sources = {r["src"]: r["cnt"] for r in gen_rows}

    return {
        "counts": {
            "lines": lines, "substations": subs, "towers": towers,
            "transformers": xfmrs, "generators": gens, "plants": plants,
            "total": lines + subs + towers + xfmrs + gens + plants,
        },
        "voltage_distribution": voltage_dist,
        "generator_sources": gen_sources,
    }
