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
    """Create OSM power infrastructure tables if they don't exist.

    Task #16 extensions vs the pre-OIM schema:
      - osm_power_line gains voltage_2/3/4, construction, disused, location
      - osm_power_substation gains construction/disused
      - new osm_power_substation_poly (substation polygons, not just centroids)
      - new osm_power_switchgear (switch / compensator / converter / insulator
        / terminal — fields the OIM style consumes)
      - osm_power_transformer gains voltage_primary/secondary/tertiary,
        windings, phases, type, transformer_type, switch
      - osm_power_plant gains repd_id (joins our REPD register), construction,
        disused, plant_method, plant_storage
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS osm_power_line (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            voltage_2 REAL,                   -- second voltage from semicolon list (kV)
            voltage_3 REAL,                   -- third  voltage (kV)
            voltage_4 REAL,                   -- fourth voltage (kV) — rare, kept for symmetry with OIM
            line_type TEXT,                   -- cable, line, minor_line
            location TEXT,                    -- underground, overhead, underwater, ...
            construction BOOLEAN DEFAULT FALSE, -- construction:power=line
            disused BOOLEAN DEFAULT FALSE,    -- disused:power=line
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

        -- Forward-migrate older deployments that don't yet have the OIM columns.
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS voltage_2 REAL;
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS voltage_3 REAL;
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS voltage_4 REAL;
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS location TEXT;
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS construction BOOLEAN DEFAULT FALSE;
        ALTER TABLE osm_power_line ADD COLUMN IF NOT EXISTS disused BOOLEAN DEFAULT FALSE;

        CREATE TABLE IF NOT EXISTS osm_power_substation (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            substation_type TEXT,   -- transmission, distribution, transition, converter, ...
            construction BOOLEAN DEFAULT FALSE,
            disused BOOLEAN DEFAULT FALSE,
            operator TEXT,
            name TEXT,
            ref TEXT,
            frequency TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_sub_geom ON osm_power_substation USING GIST (geometry);
        ALTER TABLE osm_power_substation ADD COLUMN IF NOT EXISTS construction BOOLEAN DEFAULT FALSE;
        ALTER TABLE osm_power_substation ADD COLUMN IF NOT EXISTS disused      BOOLEAN DEFAULT FALSE;
        ALTER TABLE osm_power_substation ADD COLUMN IF NOT EXISTS frequency    TEXT;

        -- NEW (task #16): substation polygons. OIM uses these for the filled
        -- "power_substation" + outline layers at zoom >= 13. Kept separate
        -- from osm_power_substation (point centroids) so the existing app
        -- code that joins on substation_id keeps working.
        CREATE TABLE IF NOT EXISTS osm_power_substation_poly (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            substation_type TEXT,
            construction BOOLEAN DEFAULT FALSE,
            disused BOOLEAN DEFAULT FALSE,
            operator TEXT,
            name TEXT,
            ref TEXT,
            frequency TEXT,
            area_sqm DOUBLE PRECISION,
            tags JSONB,
            geometry GEOMETRY(Polygon, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_sub_poly_geom
            ON osm_power_substation_poly USING GIST (geometry);

        CREATE TABLE IF NOT EXISTS osm_power_tower (
            osm_id BIGINT PRIMARY KEY,
            tower_type TEXT,        -- tower, pole, portal, ...
            design TEXT,
            material TEXT,
            height REAL,
            transition BOOLEAN DEFAULT FALSE,  -- location:transition=yes
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_tower_geom ON osm_power_tower USING GIST (geometry);
        ALTER TABLE osm_power_tower ADD COLUMN IF NOT EXISTS transition BOOLEAN DEFAULT FALSE;

        -- Existing transformer table — extend with the OIM-style detail fields.
        CREATE TABLE IF NOT EXISTS osm_power_transformer (
            osm_id BIGINT PRIMARY KEY,
            voltage_kv REAL,
            voltage_raw TEXT,
            voltage_primary REAL,    -- kV
            voltage_secondary REAL,
            voltage_tertiary REAL,
            rating TEXT,             -- raw MVA / VA string
            windings INT,            -- 2 or 3 typically
            phases INT,
            transformer_type TEXT,   -- distribution, current, potential, ...
            switch TEXT,             -- if collocated with a switch
            name TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_xfmr_geom ON osm_power_transformer USING GIST (geometry);
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS voltage_primary   REAL;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS voltage_secondary REAL;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS voltage_tertiary  REAL;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS windings          INT;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS phases            INT;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS transformer_type  TEXT;
        ALTER TABLE osm_power_transformer ADD COLUMN IF NOT EXISTS switch            TEXT;

        -- NEW (task #16): switchgear — switch / compensator / converter /
        -- insulator / terminal. Mirrors OIM's power_switchgear imposm table.
        CREATE TABLE IF NOT EXISTS osm_power_switchgear (
            osm_id BIGINT PRIMARY KEY,
            kind TEXT NOT NULL,      -- switch, compensator, converter, insulator, terminal
            type TEXT,               -- disconnector / circuit_breaker / shunt_reactor / ...
            voltage_kv REAL,
            voltage_raw TEXT,
            rating TEXT,
            name TEXT,
            tags JSONB,
            geom_type TEXT NOT NULL, -- 'point' or 'polygon'
            geometry GEOMETRY(Geometry, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_switchgear_geom
            ON osm_power_switchgear USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_osm_power_switchgear_kind
            ON osm_power_switchgear (kind);

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
            plant_method TEXT,                       -- e.g. combustion, photovoltaic
            plant_storage TEXT,                      -- battery / pumped_storage / ...
            construction BOOLEAN DEFAULT FALSE,
            disused BOOLEAN DEFAULT FALSE,
            repd_id TEXT,                            -- direct join key to REPD (UK regulatory)
            name TEXT,
            operator TEXT,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_plant_geom ON osm_power_plant USING GIST (geometry);
        ALTER TABLE osm_power_plant ADD COLUMN IF NOT EXISTS plant_method   TEXT;
        ALTER TABLE osm_power_plant ADD COLUMN IF NOT EXISTS plant_storage  TEXT;
        ALTER TABLE osm_power_plant ADD COLUMN IF NOT EXISTS construction   BOOLEAN DEFAULT FALSE;
        ALTER TABLE osm_power_plant ADD COLUMN IF NOT EXISTS disused        BOOLEAN DEFAULT FALSE;
        ALTER TABLE osm_power_plant ADD COLUMN IF NOT EXISTS repd_id        TEXT;
        CREATE INDEX IF NOT EXISTS idx_osm_power_plant_repd ON osm_power_plant (repd_id);

        -- NEW (task #16): plant 'site' relations — OSM models distributed
        -- power plants (rooftop arrays etc.) as type=site relations rather
        -- than ways. Store the centroid + the member ids in JSONB.
        CREATE TABLE IF NOT EXISTS osm_power_plant_relation (
            osm_id BIGINT PRIMARY KEY,
            source TEXT,
            output_mw REAL,
            output_raw TEXT,
            construction BOOLEAN DEFAULT FALSE,
            disused BOOLEAN DEFAULT FALSE,
            repd_id TEXT,
            name TEXT,
            operator TEXT,
            member_ids JSONB,
            tags JSONB,
            geometry GEOMETRY(Point, 4326),
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_osm_power_plant_rel_geom
            ON osm_power_plant_relation USING GIST (geometry);

        -- NEW (task #16): route=power relations (whole power circuits).
        CREATE TABLE IF NOT EXISTS osm_power_circuit_relation (
            osm_id BIGINT PRIMARY KEY,
            name TEXT,
            voltage_kv REAL,
            voltage_raw TEXT,
            frequency TEXT,
            construction BOOLEAN DEFAULT FALSE,
            member_ids JSONB,
            tags JSONB,
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    log.info("OSM power infrastructure tables ready (incl. OIM extensions)")


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


def parse_voltage_list_kv(raw: str | None) -> list[float]:
    """Parse OSM voltage tag (semicolon-delimited) into ordered list of kV.

    Mirrors upstream OIM convert_integer_list + line_voltages: keeps insertion
    order so caller can map them to voltage / voltage_2 / voltage_3 / voltage_4.

    >>> parse_voltage_list_kv('400000;132000;33000')
    [400.0, 132.0, 33.0]
    >>> parse_voltage_list_kv('11000')
    [11.0]
    >>> parse_voltage_list_kv(None)
    []
    """
    if not raw:
        return []
    out: list[float] = []
    for part in raw.split(";"):
        nums = re.findall(r"[\d.]+", part)
        if not nums:
            continue
        try:
            v = float(nums[0])
        except (ValueError, TypeError):
            continue
        # OSM stores volts; convert to kV.
        out.append(v / 1000.0 if v > 1000 else v)
    return out


def parse_int(raw: str | None) -> int | None:
    """Safely parse an integer tag (e.g. windings=3)."""
    if not raw:
        return None
    m = re.match(r"\s*(-?\d+)", str(raw))
    return int(m.group(1)) if m else None


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
    """Build Overpass QL query for all power features in a bbox.

    Task #16 additions vs the pre-OIM query:
      - construction:power=* and disused:power=* for lines, plants, substations
      - power=switch / compensator / converter / insulator / terminal
      - way+relation forms of substation (we already had these but now we
        materialise polygons too)
      - route=power relations (circuits)
      - type=site relations for distributed plants
    """
    bbox = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  // Lines / cables (live + planned + retired)
  way["power"="line"]({bbox});
  way["power"="cable"]({bbox});
  way["power"="minor_line"]({bbox});
  way["construction:power"~"line|cable|minor_line"]({bbox});
  way["disused:power"~"line|cable|minor_line"]({bbox});

  // Substations — point, polygon, and `type=site` relations
  node["power"="substation"]({bbox});
  way["power"="substation"]({bbox});
  relation["power"="substation"]({bbox});
  way["construction:power"="substation"]({bbox});

  // Towers / poles / portals
  node["power"="tower"]({bbox});
  node["power"="pole"]({bbox});
  node["power"="portal"]({bbox});

  // Transformers + switchgear (OIM imposm power_switchgear table)
  node["power"="transformer"]({bbox});
  way["power"="transformer"]({bbox});
  node["power"="switch"]({bbox});
  node["power"="compensator"]({bbox});
  way["power"="compensator"]({bbox});
  node["power"="converter"]({bbox});
  way["power"="converter"]({bbox});
  node["power"="insulator"]({bbox});
  node["power"="terminal"]({bbox});

  // Generators
  node["power"="generator"]({bbox});
  way["power"="generator"]({bbox});

  // Plants — incl. type=site distributed plants + construction
  node["power"="plant"]({bbox});
  way["power"="plant"]({bbox});
  relation["power"="plant"]({bbox});
  way["construction:power"="plant"]({bbox});
  relation["construction:power"="plant"]({bbox});

  // Whole power circuits (route=power relations)
  relation["route"="power"]({bbox});
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
    """Upsert power lines/cables into osm_power_line.

    Task #16 extensions:
      - Multi-voltage parsing (voltage_2 / voltage_3 / voltage_4) via
        parse_voltage_list_kv — matches the OIM style's per-circuit colouring.
      - Lifecycle: construction:power=line / disused:power=line flagged as
        booleans so the OIM style's construction_p / disused_p filters fire.
      - location tag (underground, underwater, overhead) so OIM underground_p
        rule works without needing to look at `tunnel` alone.
    """
    count = 0
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags", {})
        power = tags.get("power", "")
        construction_val = tags.get("construction:power", "")
        disused_val = tags.get("disused:power", "")
        is_construction = construction_val in ("line", "cable", "minor_line")
        is_disused = disused_val in ("line", "cable", "minor_line")
        if power not in ("line", "cable", "minor_line") and not is_construction and not is_disused:
            continue
        if not power:
            power = construction_val or disused_val
        coords = _way_to_linestring(e, nodes)
        if not coords:
            continue
        # Multi-voltage: take all voltages from the semicolon list, sorted
        # by their order of appearance (OIM convention).
        voltages = parse_voltage_list_kv(tags.get("voltage"))
        voltage_kv = max(voltages) if voltages else None
        v2 = voltages[1] if len(voltages) >= 2 else None
        v3 = voltages[2] if len(voltages) >= 3 else None
        v4 = voltages[3] if len(voltages) >= 4 else None
        geom_wkt = "LINESTRING(" + ",".join(f"{c[0]} {c[1]}" for c in coords) + ")"
        await conn.execute("""
            INSERT INTO osm_power_line (osm_id, voltage_kv, voltage_raw,
                voltage_2, voltage_3, voltage_4,
                line_type, location, construction, disused, operator, name, ref,
                cables, circuits, frequency, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                    $14, $15, $16, $17, ST_GeomFromText($18, 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv, voltage_raw = EXCLUDED.voltage_raw,
                voltage_2 = EXCLUDED.voltage_2, voltage_3 = EXCLUDED.voltage_3,
                voltage_4 = EXCLUDED.voltage_4,
                line_type = EXCLUDED.line_type, location = EXCLUDED.location,
                construction = EXCLUDED.construction, disused = EXCLUDED.disused,
                operator = EXCLUDED.operator,
                name = EXCLUDED.name, tags = EXCLUDED.tags, geometry = EXCLUDED.geometry,
                fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"),
            v2, v3, v4,
            power, tags.get("location"),
            is_construction, is_disused,
            tags.get("operator"), tags.get("name"), tags.get("ref"),
            int(tags["cables"]) if tags.get("cables", "").isdigit() else None,
            int(tags["circuits"]) if tags.get("circuits", "").isdigit() else None,
            tags.get("frequency"),
            json.dumps({k: v for k, v in tags.items() if k not in (
                "power", "voltage", "operator", "name", "ref",
                "cables", "circuits", "frequency", "location",
                "construction:power", "disused:power",
            )}),
            geom_wkt,
        )
        count += 1
    return count


async def _upsert_substations(conn, elements: list, nodes: dict):
    """Upsert substation point centroids (also writes the polygon to
    osm_power_substation_poly when the source feature is a way/relation).

    Task #16: now populates construction / disused / frequency.
    """
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        power = tags.get("power", "")
        construction_val = tags.get("construction:power", "")
        is_construction = power == "" and construction_val == "substation"
        is_disused = power == "" and tags.get("disused:power") == "substation"
        if power != "substation" and not is_construction and not is_disused:
            continue

        poly_coords = None
        if e["type"] == "node" and "lon" in e:
            lon, lat = e["lon"], e["lat"]
        elif e["type"] in ("way", "relation"):
            coords = _way_to_linestring(e, nodes) if e["type"] == "way" else None
            pt = _way_to_centroid(e, nodes)
            if not pt:
                continue
            lon, lat = pt
            # If we have a closed way, also keep the polygon for the poly table.
            if coords and len(coords) >= 4 and coords[0] == coords[-1]:
                poly_coords = coords
        else:
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        sub_type = tags.get("substation") or ("construction" if is_construction else None)
        await conn.execute("""
            INSERT INTO osm_power_substation (osm_id, voltage_kv, voltage_raw, substation_type,
                construction, disused, operator, name, ref, frequency, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    ST_SetSRID(ST_MakePoint($12, $13), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv, name = EXCLUDED.name,
                construction = EXCLUDED.construction, disused = EXCLUDED.disused,
                operator = EXCLUDED.operator, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"), sub_type,
            is_construction, is_disused,
            tags.get("operator"), tags.get("name"), tags.get("ref"),
            tags.get("frequency"),
            json.dumps({k: v for k, v in tags.items() if k not in (
                "power", "voltage", "substation", "operator", "name", "ref",
                "frequency", "construction:power", "disused:power",
            )}),
            lon, lat,
        )
        count += 1

        if poly_coords:
            # Build a polygon WKT and upsert into osm_power_substation_poly.
            poly_wkt = "POLYGON((" + ",".join(f"{c[0]} {c[1]}" for c in poly_coords) + "))"
            try:
                await conn.execute("""
                    INSERT INTO osm_power_substation_poly (osm_id, voltage_kv, voltage_raw,
                        substation_type, construction, disused, operator, name, ref, frequency,
                        area_sqm, tags, geometry)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            ST_Area(ST_GeogFromText('SRID=4326;' || $11)),
                            $12, ST_GeomFromText($11, 4326))
                    ON CONFLICT (osm_id) DO UPDATE SET
                        voltage_kv = EXCLUDED.voltage_kv,
                        construction = EXCLUDED.construction, disused = EXCLUDED.disused,
                        name = EXCLUDED.name, tags = EXCLUDED.tags,
                        geometry = EXCLUDED.geometry, area_sqm = EXCLUDED.area_sqm,
                        fetched_at = NOW()
                """,
                    e["id"], voltage_kv, tags.get("voltage"), sub_type,
                    is_construction, is_disused,
                    tags.get("operator"), tags.get("name"), tags.get("ref"),
                    tags.get("frequency"),
                    poly_wkt,
                    json.dumps({k: v for k, v in tags.items() if k not in (
                        "power", "voltage", "substation", "operator", "name", "ref",
                        "frequency", "construction:power", "disused:power",
                    )}),
                )
            except Exception as poly_err:
                # Self-intersecting polygon from Overpass — log and move on.
                log.debug("substation polygon upsert failed for osm_id=%s: %s", e["id"], poly_err)
    return count


async def _upsert_towers(conn, elements: list, nodes: dict):
    """Upsert towers/poles. Now flags `location:transition=yes` so the OIM
    style can swap to the dedicated transition icon."""
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
        transition = tags.get("location:transition") in ("yes", "true", "1")
        await conn.execute("""
            INSERT INTO osm_power_tower (osm_id, tower_type, design, material, height, transition, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, ST_SetSRID(ST_MakePoint($8, $9), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                tower_type = EXCLUDED.tower_type, design = EXCLUDED.design,
                transition = EXCLUDED.transition,
                tags = EXCLUDED.tags, geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], power, tags.get("design"), tags.get("material"),
            height, transition,
            json.dumps({k: v for k, v in tags.items() if k not in (
                "power", "design", "material", "height", "location:transition",
            )}),
            e["lon"], e["lat"],
        )
        count += 1
    return count


async def _upsert_transformers(conn, elements: list, nodes: dict):
    """Upsert transformers with OIM-style detail (primary/secondary/tertiary
    voltages, windings, phases, transformer_type, switch). Accepts both
    nodes and way centroids.
    """
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        if tags.get("power") != "transformer":
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
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        vp = parse_voltage_kv(tags.get("voltage:primary"))
        vs = parse_voltage_kv(tags.get("voltage:secondary"))
        vt = parse_voltage_kv(tags.get("voltage:tertiary"))
        windings = parse_int(tags.get("windings"))
        # If voltage_tertiary is set we know windings is at least 3 even if
        # not tagged — OIM uses this exact rule for the 3-winding icon.
        if windings is None and vt is not None:
            windings = 3
        phases = parse_int(tags.get("phases"))
        await conn.execute("""
            INSERT INTO osm_power_transformer (osm_id, voltage_kv, voltage_raw,
                voltage_primary, voltage_secondary, voltage_tertiary,
                rating, windings, phases, transformer_type, switch,
                name, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    $12, $13, ST_SetSRID(ST_MakePoint($14, $15), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                voltage_kv = EXCLUDED.voltage_kv,
                voltage_primary   = EXCLUDED.voltage_primary,
                voltage_secondary = EXCLUDED.voltage_secondary,
                voltage_tertiary  = EXCLUDED.voltage_tertiary,
                rating  = EXCLUDED.rating, windings = EXCLUDED.windings,
                phases  = EXCLUDED.phases, transformer_type = EXCLUDED.transformer_type,
                switch  = EXCLUDED.switch,
                name = EXCLUDED.name, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"], voltage_kv, tags.get("voltage"),
            vp, vs, vt,
            tags.get("rating"), windings, phases,
            tags.get("transformer") or tags.get("transformer:type"),
            tags.get("switch"),
            tags.get("name"),
            json.dumps({k: v for k, v in tags.items() if k not in (
                "power", "voltage", "voltage:primary", "voltage:secondary",
                "voltage:tertiary", "rating", "windings", "phases",
                "transformer", "transformer:type", "switch", "name",
            )}),
            lon, lat,
        )
        count += 1
    return count


async def _upsert_switchgear(conn, elements: list, nodes: dict):
    """Upsert switch / compensator / converter / insulator / terminal as a
    single polymorphic switchgear table — the OIM style consumes them all
    from one source-layer."""
    SWITCHGEAR_KINDS = ("switch", "compensator", "converter", "insulator", "terminal")
    count = 0
    for e in elements:
        tags = e.get("tags", {})
        kind = tags.get("power")
        if kind not in SWITCHGEAR_KINDS:
            continue
        if e["type"] == "node" and "lon" in e:
            geom_wkt = f"POINT({e['lon']} {e['lat']})"
            geom_type = "point"
        elif e["type"] == "way":
            coords = _way_to_linestring(e, nodes)
            if not coords:
                continue
            # Treat as polygon if closed, else use centroid.
            if len(coords) >= 4 and coords[0] == coords[-1]:
                geom_wkt = "POLYGON((" + ",".join(f"{c[0]} {c[1]}" for c in coords) + "))"
                geom_type = "polygon"
            else:
                pt = _way_to_centroid(e, nodes)
                if not pt:
                    continue
                geom_wkt = f"POINT({pt[0]} {pt[1]})"
                geom_type = "point"
        else:
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        # `type` for a switch is e.g. disconnector / circuit_breaker; for a
        # compensator it's e.g. shunt_reactor / series_capacitor.
        sub_type = tags.get(kind) or tags.get("type")
        try:
            await conn.execute("""
                INSERT INTO osm_power_switchgear (osm_id, kind, type, voltage_kv, voltage_raw,
                    rating, name, tags, geom_type, geometry)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, ST_GeomFromText($10, 4326))
                ON CONFLICT (osm_id) DO UPDATE SET
                    kind = EXCLUDED.kind, type = EXCLUDED.type,
                    voltage_kv = EXCLUDED.voltage_kv, voltage_raw = EXCLUDED.voltage_raw,
                    rating = EXCLUDED.rating, name = EXCLUDED.name,
                    tags = EXCLUDED.tags, geom_type = EXCLUDED.geom_type,
                    geometry = EXCLUDED.geometry, fetched_at = NOW()
            """,
                e["id"], kind, sub_type, voltage_kv, tags.get("voltage"),
                tags.get("rating"), tags.get("name"),
                json.dumps({k: v for k, v in tags.items() if k not in (
                    "power", "voltage", "rating", "name", kind, "type",
                )}),
                geom_type, geom_wkt,
            )
            count += 1
        except Exception as sw_err:
            log.debug("switchgear upsert failed for osm_id=%s: %s", e["id"], sw_err)
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
    """Upsert power plants (node or way; relations go to osm_power_plant_relation).

    Task #16 extensions:
      - construction / disused lifecycle booleans
      - plant_method / plant_storage
      - repd_id — directly joins our REPD register (UK regulatory tracker).
        Two common ways to find this: a tag named ref:repd or repd:id, or a
        ref:UK:repd. We read both.
    """
    count = 0
    for e in elements:
        if e["type"] == "relation":
            # Handled by _upsert_plant_relations to keep the schema split clean.
            continue
        tags = e.get("tags", {})
        is_plant = tags.get("power") == "plant"
        is_construction_plant = tags.get("construction:power") == "plant"
        is_disused_plant = tags.get("disused:power") == "plant"
        if not (is_plant or is_construction_plant or is_disused_plant):
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
        output_mw = parse_output_mw(tags.get("plant:output:electricity") or tags.get("plant:output"))
        repd_id = (
            tags.get("ref:repd")
            or tags.get("repd:id")
            or tags.get("ref:UK:repd")
        )
        await conn.execute("""
            INSERT INTO osm_power_plant (osm_id, source, output_mw, output_raw,
                plant_method, plant_storage, construction, disused, repd_id,
                name, operator, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    ST_SetSRID(ST_MakePoint($13, $14), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                source = EXCLUDED.source, output_mw = EXCLUDED.output_mw,
                plant_method  = EXCLUDED.plant_method,
                plant_storage = EXCLUDED.plant_storage,
                construction  = EXCLUDED.construction,
                disused       = EXCLUDED.disused,
                repd_id       = COALESCE(EXCLUDED.repd_id, osm_power_plant.repd_id),
                name = EXCLUDED.name, tags = EXCLUDED.tags,
                geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"],
            tags.get("plant:source") or tags.get("generator:source"),
            output_mw,
            tags.get("plant:output:electricity") or tags.get("plant:output"),
            tags.get("plant:method"),
            tags.get("plant:storage"),
            is_construction_plant, is_disused_plant,
            repd_id,
            tags.get("name"),
            tags.get("operator"),
            json.dumps({k: v for k, v in tags.items() if not k.startswith("plant:") and k not in (
                "power", "name", "operator", "construction:power", "disused:power",
                "ref:repd", "repd:id", "ref:UK:repd",
            )}),
            lon, lat,
        )
        count += 1
    return count


async def _upsert_plant_relations(conn, elements: list, nodes: dict):
    """Distributed plants are modelled as `type=site` relations in OSM
    (rooftop solar fleets, multi-turbine wind farms). Store the centroid +
    the member ids so the renderer can show one icon per relation rather
    than per member."""
    count = 0
    for e in elements:
        if e["type"] != "relation":
            continue
        tags = e.get("tags", {})
        is_plant = tags.get("power") == "plant"
        is_construction_plant = tags.get("construction:power") == "plant"
        is_disused_plant = tags.get("disused:power") == "plant"
        if not (is_plant or is_construction_plant or is_disused_plant):
            continue
        # Cheap centroid: average of any positioned members' coords. Overpass
        # returns member ways as their own elements (we already have them in
        # `nodes` after `_build_node_lookup` runs).
        member_ids = []
        coords = []
        for m in e.get("members", []) or []:
            ref = m.get("ref")
            if ref is None:
                continue
            member_ids.append(ref)
            pt = nodes.get(ref)
            if pt:
                coords.append(pt)
        if not coords:
            # No positioned members — skip rather than guess.
            continue
        lon = sum(c[0] for c in coords) / len(coords)
        lat = sum(c[1] for c in coords) / len(coords)
        output_mw = parse_output_mw(tags.get("plant:output:electricity") or tags.get("plant:output"))
        repd_id = (
            tags.get("ref:repd")
            or tags.get("repd:id")
            or tags.get("ref:UK:repd")
        )
        await conn.execute("""
            INSERT INTO osm_power_plant_relation (osm_id, source, output_mw, output_raw,
                construction, disused, repd_id, name, operator, member_ids, tags, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    ST_SetSRID(ST_MakePoint($12, $13), 4326))
            ON CONFLICT (osm_id) DO UPDATE SET
                source = EXCLUDED.source, output_mw = EXCLUDED.output_mw,
                construction = EXCLUDED.construction, disused = EXCLUDED.disused,
                repd_id = COALESCE(EXCLUDED.repd_id, osm_power_plant_relation.repd_id),
                name = EXCLUDED.name, member_ids = EXCLUDED.member_ids,
                tags = EXCLUDED.tags, geometry = EXCLUDED.geometry, fetched_at = NOW()
        """,
            e["id"],
            tags.get("plant:source") or tags.get("generator:source"),
            output_mw,
            tags.get("plant:output:electricity") or tags.get("plant:output"),
            is_construction_plant, is_disused_plant,
            repd_id,
            tags.get("name"),
            tags.get("operator"),
            json.dumps(member_ids),
            json.dumps({k: v for k, v in tags.items() if not k.startswith("plant:") and k not in (
                "power", "name", "operator", "construction:power", "disused:power",
                "ref:repd", "repd:id", "ref:UK:repd",
            )}),
            lon, lat,
        )
        count += 1
    return count


async def _upsert_power_circuits(conn, elements: list, nodes: dict):
    """Upsert route=power relations. We don't materialise geometry — the
    member lines already exist in osm_power_line — just store metadata for
    cross-reference."""
    count = 0
    for e in elements:
        if e["type"] != "relation":
            continue
        tags = e.get("tags", {})
        if tags.get("route") != "power":
            continue
        voltage_kv = parse_voltage_kv(tags.get("voltage"))
        member_ids = [m.get("ref") for m in (e.get("members") or []) if m.get("ref") is not None]
        await conn.execute("""
            INSERT INTO osm_power_circuit_relation (osm_id, name, voltage_kv, voltage_raw,
                frequency, construction, member_ids, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (osm_id) DO UPDATE SET
                name = EXCLUDED.name, voltage_kv = EXCLUDED.voltage_kv,
                frequency = EXCLUDED.frequency, construction = EXCLUDED.construction,
                member_ids = EXCLUDED.member_ids, tags = EXCLUDED.tags,
                fetched_at = NOW()
        """,
            e["id"], tags.get("name"), voltage_kv, tags.get("voltage"),
            tags.get("frequency"),
            tags.get("construction:power") == "circuit",
            json.dumps(member_ids),
            json.dumps({k: v for k, v in tags.items() if k not in (
                "route", "name", "voltage", "frequency", "construction:power",
            )}),
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
            switchgear = await _upsert_switchgear(conn, elements, nodes)
            gens = await _upsert_generators(conn, elements, nodes)
            plants = await _upsert_plants(conn, elements, nodes)
            plant_rels = await _upsert_plant_relations(conn, elements, nodes)
            circuits = await _upsert_power_circuits(conn, elements, nodes)
            log.info(
                "Cell %d upserted: %d lines, %d subs, %d towers, %d xfmrs, "
                "%d switchgear, %d gens, %d plants, %d plant-rels, %d circuits",
                i + 1, lines, subs, towers, xfmrs, switchgear, gens, plants,
                plant_rels, circuits,
            )

        # Rate limit
        if i < len(UK_CELLS) - 1:
            await asyncio.sleep(REQUEST_INTERVAL)

    log.info("OSM power infrastructure seeding complete")


# ---------------------------------------------------------------------------
# GeoJSON query functions
# ---------------------------------------------------------------------------
async def power_lines_geojson(conn, bbox: tuple[float, float, float, float], min_voltage_kv: float = 0) -> dict:
    """Return power lines as GeoJSON FeatureCollection. bbox = (west, south, east, north).

    Task #16: emits the additional OIM-style fields so the upstream layer
    expressions (voltage_2, voltage_3, voltage_4, location, construction,
    disused) work without modification.
    """
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw,
               voltage_2, voltage_3, voltage_4,
               line_type, location, construction, disused,
               operator, name, ref, cables, circuits, frequency,
               ST_AsGeoJSON(geometry) AS geom
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
                # OIM expressions read 'voltage' (kV) — alias from voltage_kv.
                "voltage": r["voltage_kv"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "voltage_2": r["voltage_2"],
                "voltage_3": r["voltage_3"],
                "voltage_4": r["voltage_4"],
                "line": r["line_type"],     # OIM expressions read 'line'
                "line_type": r["line_type"],
                "location": r["location"],
                "construction": bool(r["construction"]),
                "disused": bool(r["disused"]),
                "operator": r["operator"],
                "name": r["name"],
                "ref": r["ref"],
                "cables": r["cables"],
                "circuits": r["circuits"],
                "frequency": r["frequency"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_substations_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return substation points as GeoJSON FeatureCollection.

    Task #16: aliases voltage_kv → voltage and substation_type → substation
    so upstream OIM expressions (which read those exact field names) work
    without modification. Includes lifecycle + frequency.
    """
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw, substation_type,
               construction, disused, operator, name, ref, frequency,
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
                "voltage": r["voltage_kv"],                # OIM-style alias
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "substation": r["substation_type"],         # OIM-style alias
                "substation_type": r["substation_type"],
                "construction": bool(r["construction"]),
                "disused": bool(r["disused"]),
                "frequency": r["frequency"],
                "operator": r["operator"],
                "name": r["name"],
                "ref": r["ref"],
                "area": 0,                                  # point = node convention
                "is_node": True,
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_substation_polys_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return substation polygons as GeoJSON FeatureCollection (task #16 new).

    Used by the OIM `power_substation` (fill) and `power_substation_outline`
    layers at zoom >= 13.
    """
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw, substation_type,
               construction, disused, operator, name, ref, frequency,
               COALESCE(area_sqm, 0) AS area_sqm,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_substation_poly
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
                "voltage": r["voltage_kv"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "substation": r["substation_type"],
                "substation_type": r["substation_type"],
                "construction": bool(r["construction"]),
                "disused": bool(r["disused"]),
                "frequency": r["frequency"],
                "operator": r["operator"],
                "name": r["name"],
                "ref": r["ref"],
                "area": r["area_sqm"],
                "is_node": False,
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_switchgear_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return switches / compensators / converters / transformers as a single
    FeatureCollection. Mirrors OIM's power_switchgear source-layer (task #16).

    Transformers come from the dedicated osm_power_transformer table (which
    has primary/secondary/tertiary voltages, windings) — UNION'd with the
    polymorphic switchgear table so the OIM transformer layer renders
    correctly.
    """
    west, south, east, north = bbox
    # Switchgear (switch/compensator/converter/insulator/terminal).
    sw_rows = await conn.fetch("""
        SELECT osm_id, kind, type, voltage_kv, voltage_raw, rating, name,
               geom_type, ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_switchgear
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        LIMIT 3000
    """, west, south, east, north)
    # Transformers.
    xf_rows = await conn.fetch("""
        SELECT osm_id, voltage_kv, voltage_raw, voltage_primary, voltage_secondary,
               voltage_tertiary, rating, windings, phases, transformer_type, switch,
               name, ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_transformer
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        LIMIT 3000
    """, west, south, east, north)
    features = []
    for r in sw_rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "kind": r["kind"],
                "type": r["type"],                    # OIM reads this
                "voltage": r["voltage_kv"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "rating": r["rating"],
                "name": r["name"],
                "switch": r["type"] if r["kind"] == "switch" else None,
                "is_node": r["geom_type"] == "point",
            },
        })
    for r in xf_rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "kind": "transformer",
                "voltage": r["voltage_kv"],
                "voltage_kv": r["voltage_kv"],
                "voltage_raw": r["voltage_raw"],
                "voltage_primary": r["voltage_primary"],
                "voltage_secondary": r["voltage_secondary"],
                "voltage_tertiary": r["voltage_tertiary"],
                "rating": r["rating"],
                "windings": r["windings"],
                "phases": r["phases"],
                "transformer_type": r["transformer_type"],
                "switch": r["switch"],
                "name": r["name"],
                "is_node": True,
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
    """Return generators as GeoJSON FeatureCollection.

    Task #16: emits 'output' (MW) alias so OIM's generator label expressions
    pick it up directly. is_node is true for point generators (the OIM
    `power_generator_solar` filter requires it).
    """
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
        # OIM expressions read 'output' in MW.
        output_mw = (r["output_kw"] / 1000.0) if r["output_kw"] else None
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geom"]),
            "properties": {
                "osm_id": r["osm_id"],
                "source": r["source"],
                "output": output_mw,
                "output_kw": r["output_kw"],
                "output_raw": r["output_raw"],
                "method": r["method"],
                "name": r["name"],
                "operator": r["operator"],
                "is_node": True,
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def power_plants_geojson(conn, bbox: tuple[float, float, float, float]) -> dict:
    """Return power plants as GeoJSON FeatureCollection.

    Task #16: includes plant relations (distributed plants), construction /
    disused lifecycle, and the repd_id join column so the popup can deep-link
    to the regulatory record.
    """
    west, south, east, north = bbox
    rows = await conn.fetch("""
        SELECT osm_id, source, output_mw, output_raw, plant_method, plant_storage,
               construction, disused, repd_id, name, operator,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_plant
        WHERE geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
        UNION ALL
        SELECT osm_id, source, output_mw, output_raw, NULL, NULL,
               construction, disused, repd_id, name, operator,
               ST_AsGeoJSON(geometry) AS geom
        FROM osm_power_plant_relation
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
                "output": r["output_mw"],          # OIM-style alias (MW)
                "output_mw": r["output_mw"],
                "output_raw": r["output_raw"],
                "plant_method": r["plant_method"],
                "plant_storage": r["plant_storage"],
                "construction": bool(r["construction"]),
                "disused": bool(r["disused"]),
                "repd_id": r["repd_id"],
                "name": r["name"],
                "operator": r["operator"],
                "is_node": True,
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
