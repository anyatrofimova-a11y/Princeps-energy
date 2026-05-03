"""
NGED LTDS CIM Dataset — parse CIM RDF/XML equipment profiles from
National Grid Electricity Distribution, geo-locate substations via
fuzzy-matching against OSM data, and compute connection headroom.

Creates 4 PostGIS tables (SRID 4326) and provides opportunity analysis
functions for the frontend dashboard and map layers.
"""
import asyncio
import difflib
import io
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger("princeps.nged_cim")

# ---------------------------------------------------------------------------
# CIM namespace and data source configuration
# ---------------------------------------------------------------------------
CIM_NS_100 = "http://iec.ch/TC57/CIM100#"
CIM_NS_16 = "http://iec.ch/TC57/2013/CIM-schema-cim16#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
GB_NS = "http://ofgem.gov.uk/ns/CIM/LTDS/Extensions#"
# Default to CIM100 (current LTDS format); detect() swaps if needed
CIM_NS = CIM_NS_100
NS = {"cim": CIM_NS, "rdf": RDF_NS, "gb": GB_NS}

DATA_DIR = Path(os.path.dirname(__file__), "..", "data", "nged_cim").resolve()

# NGED LTDS CIM dataset URLs (Equipment profiles)
# Source: https://connecteddata.nationalgrid.co.uk/dataset/ltds-common-information-model
NGED_REGIONS = {
    "east_midlands": "https://connecteddata.nationalgrid.co.uk/dataset/7367f8a5-7714-4647-84db-dc35119bea78/resource/2ef4b5ac-3e57-4f84-a376-9014c146c1de/download/ltds-cim-east-midlands.zip",
    "south_wales": "https://connecteddata.nationalgrid.co.uk/dataset/7367f8a5-7714-4647-84db-dc35119bea78/resource/46575bac-99cf-4edd-933e-9df58c2b95e0/download/ltds-cim-south-wales.zip",
    "south_west": "https://connecteddata.nationalgrid.co.uk/dataset/7367f8a5-7714-4647-84db-dc35119bea78/resource/38dbec57-e1ff-48c3-b4dc-c9759ebed3c0/download/ltds-cim-south-west.zip",
    "west_midlands": "https://connecteddata.nationalgrid.co.uk/dataset/7367f8a5-7714-4647-84db-dc35119bea78/resource/ab83d544-7a2a-4801-9d2a-4dbec5c8efbf/download/ltds-cim-west-midlands.zip",
}

# Fuzzy match threshold
MATCH_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------
async def setup_tables(conn):
    """Create NGED CIM tables if they don't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS nged_substation (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            region TEXT,
            voltage_kv REAL,
            geometry GEOMETRY(Point, 4326),
            osm_match_score REAL,
            osm_match_name TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_nged_sub_geom ON nged_substation USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_nged_sub_name ON nged_substation (name);

        CREATE TABLE IF NOT EXISTS nged_transformer (
            id TEXT PRIMARY KEY,
            substation_id TEXT REFERENCES nged_substation(id),
            name TEXT,
            rated_mva REAL,
            voltage_kv REAL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_nged_xfmr_sub ON nged_transformer (substation_id);

        CREATE TABLE IF NOT EXISTS nged_line_segment (
            id TEXT PRIMARY KEY,
            name TEXT,
            length_km REAL,
            r_ohm REAL,
            x_ohm REAL,
            voltage_kv REAL,
            region TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS nged_energy_consumer (
            id TEXT PRIMARY KEY,
            name TEXT,
            substation_id TEXT,
            p_mw REAL,
            region TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_nged_consumer_sub ON nged_energy_consumer (substation_id);

        CREATE TABLE IF NOT EXISTS nged_geo_override (
            substation_id TEXT PRIMARY KEY REFERENCES nged_substation(id),
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL,
            note TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    log.info("NGED CIM tables ready")


# ---------------------------------------------------------------------------
# CIM XML parsing
# ---------------------------------------------------------------------------
def _rdf_id(elem):
    """Extract rdf:ID or rdf:about from an element.

    CIM100 uses rdf:ID='_uuid' format; strip the leading underscore.
    """
    raw = (elem.get(f"{{{RDF_NS}}}ID")
           or elem.get(f"{{{RDF_NS}}}about", "").lstrip("#")
           or "")
    return raw.lstrip("_") if raw else ""


def _rdf_ref(elem, tag, ns=None):
    """Get the rdf:resource reference from a child element."""
    child = elem.find(tag, ns or NS)
    if child is not None:
        ref = child.get(f"{{{RDF_NS}}}resource", "")
        return ref.lstrip("#").lstrip("_")
    return None


def _text(elem, tag, ns=None):
    """Get text content of a child element."""
    child = elem.find(tag, ns or NS)
    return child.text.strip() if child is not None and child.text else None


def _float(elem, tag, ns=None):
    """Get float value of a child element."""
    val = _text(elem, tag, ns)
    if val:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return None


def parse_cim_xml(xml_content: bytes, region: str) -> dict[str, list[dict]]:
    """Parse CIM RDF/XML equipment profile into structured dicts.

    Auto-detects CIM16 vs CIM100 namespace.
    """
    root = ET.fromstring(xml_content)

    # Auto-detect namespace: CIM100 (current LTDS) or CIM16 (legacy)
    cim_ns = CIM_NS_100
    if root.findall(f"{{{CIM_NS_16}}}Substation"):
        cim_ns = CIM_NS_16
    ns = {"cim": cim_ns, "rdf": RDF_NS, "gb": GB_NS}

    substations = []
    voltage_levels = {}  # id -> {substation_id, base_kv}
    transformers = []
    line_segments = []
    consumers = []
    connectivity_nodes = {}  # id -> {substation_id}

    # First pass: BaseVoltage lookup (needed to resolve VoltageLevel kV)
    base_voltages = {}
    for elem in root.findall(f"{{{cim_ns}}}BaseVoltage"):
        bv_id = _rdf_id(elem)
        nom_kv = _float(elem, "cim:BaseVoltage.nominalVoltage", ns)
        base_voltages[bv_id] = nom_kv

    # Second pass: collect VoltageLevel -> Substation mappings
    for elem in root.findall(f"{{{cim_ns}}}VoltageLevel"):
        vl_id = _rdf_id(elem)
        sub_ref = _rdf_ref(elem, "cim:VoltageLevel.Substation", ns)
        base_kv = _float(elem, "cim:VoltageLevel.BaseVoltage", ns)
        if not base_kv:
            # Resolve via BaseVoltage reference
            bv_ref = _rdf_ref(elem, "cim:VoltageLevel.BaseVoltage", ns)
            if bv_ref and bv_ref in base_voltages:
                base_kv = base_voltages[bv_ref]
        voltage_levels[vl_id] = {"substation_id": sub_ref, "base_kv": base_kv}

    # Collect ConnectivityNode -> VoltageLevel mappings
    for elem in root.findall(f"{{{cim_ns}}}ConnectivityNode"):
        cn_id = _rdf_id(elem)
        vl_ref = _rdf_ref(elem, "cim:ConnectivityNode.ConnectivityNodeContainer", ns)
        sub_id = None
        if vl_ref and vl_ref in voltage_levels:
            sub_id = voltage_levels[vl_ref].get("substation_id")
        connectivity_nodes[cn_id] = {"substation_id": sub_id, "vl_id": vl_ref}

    # Substations
    for elem in root.findall(f"{{{cim_ns}}}Substation"):
        sub_id = _rdf_id(elem)
        name = _text(elem, "cim:IdentifiedObject.name", ns) or sub_id
        # Find max voltage level for this substation
        max_kv = None
        for vl_id, vl in voltage_levels.items():
            if vl.get("substation_id") == sub_id and vl.get("base_kv"):
                if max_kv is None or vl["base_kv"] > max_kv:
                    max_kv = vl["base_kv"]
        substations.append({
            "id": sub_id,
            "name": name,
            "region": region,
            "voltage_kv": max_kv,
        })

    # PowerTransformers
    for elem in root.findall(f"{{{cim_ns}}}PowerTransformer"):
        xfmr_id = _rdf_id(elem)
        name = _text(elem, "cim:IdentifiedObject.name", ns) or xfmr_id
        # ratedS is in VA in CIM — convert to MVA
        rated_s = _float(elem, "cim:PowerTransformer.ratedS", ns)
        rated_mva = rated_s / 1e6 if rated_s and rated_s > 1000 else rated_s
        # Find parent substation via EquipmentContainer
        container_ref = _rdf_ref(elem, "cim:Equipment.EquipmentContainer", ns)
        sub_id = None
        if container_ref:
            # Could be substation directly or voltage level
            if container_ref in voltage_levels:
                sub_id = voltage_levels[container_ref].get("substation_id")
            else:
                sub_id = container_ref  # assume direct substation ref
        transformers.append({
            "id": xfmr_id,
            "name": name,
            "rated_mva": rated_mva,
            "substation_id": sub_id,
            "voltage_kv": None,  # resolved from voltage level
        })

    # Also check PowerTransformerEnd for ratedS
    xfmr_ends = {}
    for elem in root.findall(f"{{{cim_ns}}}PowerTransformerEnd"):
        end_id = _rdf_id(elem)
        xfmr_ref = _rdf_ref(elem, "cim:PowerTransformerEnd.PowerTransformer", ns)
        rated_s = _float(elem, "cim:PowerTransformerEnd.ratedS", ns)
        rated_kv = _float(elem, "cim:PowerTransformerEnd.ratedU", ns)
        if xfmr_ref:
            if xfmr_ref not in xfmr_ends:
                xfmr_ends[xfmr_ref] = []
            xfmr_ends[xfmr_ref].append({
                "rated_mva": rated_s / 1e6 if rated_s and rated_s > 1000 else rated_s,
                "rated_kv": rated_kv,
            })

    # Enrich transformers with end data
    for xfmr in transformers:
        ends = xfmr_ends.get(xfmr["id"], [])
        if ends:
            # Use max ratedS from ends if transformer itself has none
            if xfmr["rated_mva"] is None:
                mva_vals = [e["rated_mva"] for e in ends if e["rated_mva"]]
                if mva_vals:
                    xfmr["rated_mva"] = max(mva_vals)
            # Use max voltage from ends
            kv_vals = [e["rated_kv"] for e in ends if e["rated_kv"]]
            if kv_vals:
                xfmr["voltage_kv"] = max(kv_vals)

    # ACLineSegments
    for elem in root.findall(f"{{{cim_ns}}}ACLineSegment"):
        seg_id = _rdf_id(elem)
        name = _text(elem, "cim:IdentifiedObject.name", ns) or seg_id
        length = _float(elem, "cim:Conductor.length", ns)
        r = _float(elem, "cim:ACLineSegment.r", ns)
        x = _float(elem, "cim:ACLineSegment.x", ns)
        # Length in CIM is typically meters
        length_km = length / 1000.0 if length and length > 100 else length
        line_segments.append({
            "id": seg_id,
            "name": name,
            "length_km": length_km,
            "r_ohm": r,
            "x_ohm": x,
            "voltage_kv": None,
            "region": region,
        })

    # EnergyConsumers
    for elem in root.findall(f"{{{cim_ns}}}EnergyConsumer"):
        ec_id = _rdf_id(elem)
        name = _text(elem, "cim:IdentifiedObject.name", ns) or ec_id
        p = _float(elem, "cim:EnergyConsumer.pfixed", ns)
        p_mw = p / 1e6 if p and p > 10000 else p  # W -> MW if large
        container_ref = _rdf_ref(elem, "cim:Equipment.EquipmentContainer", ns)
        sub_id = None
        if container_ref and container_ref in voltage_levels:
            sub_id = voltage_levels[container_ref].get("substation_id")
        consumers.append({
            "id": ec_id,
            "name": name,
            "p_mw": p_mw,
            "substation_id": sub_id,
            "region": region,
        })

    return {
        "substations": substations,
        "transformers": transformers,
        "line_segments": line_segments,
        "consumers": consumers,
    }


def parse_cim_xml_models(xml_content: bytes, region: str) -> dict[str, list]:
    """Parse CIM XML into typed Pydantic models (wraps parse_cim_xml).

    Returns dict keyed by collection name → list of CIM Pydantic model instances.
    """
    from models.cim.core import Substation
    from models.cim.wires import ACLineSegment, EnergyConsumer, PowerTransformer

    raw = parse_cim_xml(xml_content, region)

    return {
        "substations": [
            Substation(mrid=s["id"], name=s["name"], region=s.get("region"))
            for s in raw["substations"]
        ],
        "power_transformers": [
            PowerTransformer(
                mrid=t["id"],
                name=t["name"],
                rated_mva=t.get("rated_mva"),
                substation_id=t.get("substation_id"),
            )
            for t in raw["transformers"]
        ],
        "ac_line_segments": [
            ACLineSegment(
                mrid=l["id"],
                name=l["name"],
                length_km=l.get("length_km"),
                r_ohm=l.get("r_ohm"),
                x_ohm=l.get("x_ohm"),
                region=l.get("region"),
            )
            for l in raw["line_segments"]
        ],
        "energy_consumers": [
            EnergyConsumer(
                mrid=c["id"],
                name=c["name"],
                p_mw=c.get("p_mw"),
                substation_id=c.get("substation_id"),
            )
            for c in raw["consumers"]
        ],
    }


# ---------------------------------------------------------------------------
# Download & extract
# ---------------------------------------------------------------------------
async def download_cim_data() -> dict[str, bytes]:
    """Download and extract CIM XML files from NGED ZIP archives."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result = {}

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        for region, url in NGED_REGIONS.items():
            cache_file = DATA_DIR / f"{region}.xml"
            if cache_file.exists():
                log.info("Using cached CIM data for %s", region)
                result[region] = cache_file.read_bytes()
                continue

            log.info("Downloading NGED CIM data for %s ...", region)
            try:
                resp = await client.get(url)
                resp.raise_for_status()

                # Try to extract XML from ZIP
                try:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                        xml_names = [n for n in zf.namelist()
                                     if n.lower().endswith(('.xml', '.rdf'))]
                        if xml_names:
                            xml_content = zf.read(xml_names[0])
                            cache_file.write_bytes(xml_content)
                            result[region] = xml_content
                            log.info("Extracted %s (%d bytes)", xml_names[0], len(xml_content))
                        else:
                            log.warning("No XML/RDF files found in ZIP for %s", region)
                except zipfile.BadZipFile:
                    # Might be raw XML
                    if resp.content[:5] in (b"<?xml", b"<rdf:"):
                        cache_file.write_bytes(resp.content)
                        result[region] = resp.content
                    else:
                        log.warning("Downloaded file for %s is not ZIP or XML", region)

            except httpx.HTTPError as e:
                log.warning("Failed to download CIM data for %s: %s", region, e)

    return result


# ---------------------------------------------------------------------------
# Geo-matching: CIM substations → OSM substations
# ---------------------------------------------------------------------------
def _normalise_name(name: str) -> str:
    """Normalise substation name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes
    for suffix in [" substation", " primary", " bsp", " gsp",
                   " grid supply point", " bulk supply point",
                   " 33kv", " 11kv", " 66kv", " 132kv",
                   " s/s", " sub"]:
        name = name.replace(suffix, "")
    # Remove parenthetical content
    name = re.sub(r"\s*\(.*?\)\s*", " ", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


async def geo_match_substations(conn, substations: list[dict]) -> list[dict]:
    """Fuzzy-match CIM substations against OSM substation names to get geometry."""
    # Fetch all OSM substations with names
    osm_rows = await conn.fetch("""
        SELECT osm_id, name,
               ST_Y(ST_Centroid(geometry)) AS lat, ST_X(ST_Centroid(geometry)) AS lon
        FROM osm_power_substation
        WHERE name IS NOT NULL AND name != ''
    """)

    osm_lookup = {}
    for row in osm_rows:
        norm = _normalise_name(row["name"])
        if norm:
            osm_lookup[norm] = {
                "osm_id": row["osm_id"],
                "name": row["name"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }

    osm_names = list(osm_lookup.keys())
    matched = 0

    for sub in substations:
        norm_cim = _normalise_name(sub["name"])
        if not norm_cim or norm_cim == "cimgrid":
            sub["lat"] = sub["lon"] = sub["osm_match_score"] = sub["osm_match_name"] = None
            continue

        # Use get_close_matches for fast fuzzy matching (cutoff pre-filters)
        close = difflib.get_close_matches(norm_cim, osm_names, n=1, cutoff=MATCH_THRESHOLD)
        if close:
            best_match = close[0]
            best_score = difflib.SequenceMatcher(None, norm_cim, best_match).ratio()
            osm = osm_lookup[best_match]
            sub["lat"] = osm["lat"]
            sub["lon"] = osm["lon"]
            sub["osm_match_score"] = round(best_score, 3)
            sub["osm_match_name"] = osm["name"]
            matched += 1
        else:
            sub["lat"] = None
            sub["lon"] = None
            sub["osm_match_score"] = None
            sub["osm_match_name"] = None

    log.info("Geo-matched %d / %d NGED substations against OSM", matched, len(substations))
    return substations


# ---------------------------------------------------------------------------
# Database seeding
# ---------------------------------------------------------------------------
async def _insert_parsed_data(conn, parsed: dict[str, list[dict]]):
    """Insert parsed CIM data into PostGIS tables."""
    # Substations
    for sub in parsed["substations"]:
        if sub.get("lat") is not None and sub.get("lon") is not None:
            await conn.execute("""
                INSERT INTO nged_substation (id, name, region, voltage_kv, geometry, osm_match_score, osm_match_name)
                VALUES ($1, $2, $3, $4, ST_SetSRID(ST_MakePoint($5, $6), 4326), $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, region = EXCLUDED.region,
                    voltage_kv = EXCLUDED.voltage_kv, geometry = EXCLUDED.geometry,
                    osm_match_score = EXCLUDED.osm_match_score, osm_match_name = EXCLUDED.osm_match_name
            """, sub["id"], sub["name"], sub["region"], sub.get("voltage_kv"),
                sub["lon"], sub["lat"],
                sub.get("osm_match_score"), sub.get("osm_match_name"))
        else:
            await conn.execute("""
                INSERT INTO nged_substation (id, name, region, voltage_kv, osm_match_score, osm_match_name)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, region = EXCLUDED.region,
                    voltage_kv = EXCLUDED.voltage_kv,
                    osm_match_score = EXCLUDED.osm_match_score, osm_match_name = EXCLUDED.osm_match_name
            """, sub["id"], sub["name"], sub["region"], sub.get("voltage_kv"),
                sub.get("osm_match_score"), sub.get("osm_match_name"))

    # Transformers
    for xfmr in parsed["transformers"]:
        # Only insert if substation_id exists in our table
        await conn.execute("""
            INSERT INTO nged_transformer (id, substation_id, name, rated_mva, voltage_kv)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                substation_id = EXCLUDED.substation_id, name = EXCLUDED.name,
                rated_mva = EXCLUDED.rated_mva, voltage_kv = EXCLUDED.voltage_kv
        """, xfmr["id"], xfmr.get("substation_id"), xfmr["name"],
            xfmr.get("rated_mva"), xfmr.get("voltage_kv"))

    # Line segments
    for seg in parsed["line_segments"]:
        await conn.execute("""
            INSERT INTO nged_line_segment (id, name, length_km, r_ohm, x_ohm, voltage_kv, region)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name, length_km = EXCLUDED.length_km,
                r_ohm = EXCLUDED.r_ohm, x_ohm = EXCLUDED.x_ohm,
                voltage_kv = EXCLUDED.voltage_kv, region = EXCLUDED.region
        """, seg["id"], seg["name"], seg.get("length_km"),
            seg.get("r_ohm"), seg.get("x_ohm"), seg.get("voltage_kv"), seg.get("region"))

    # Energy consumers
    for ec in parsed["consumers"]:
        await conn.execute("""
            INSERT INTO nged_energy_consumer (id, name, substation_id, p_mw, region)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name, substation_id = EXCLUDED.substation_id,
                p_mw = EXCLUDED.p_mw, region = EXCLUDED.region
        """, ec["id"], ec["name"], ec.get("substation_id"),
            ec.get("p_mw"), ec.get("region"))


async def seed_cim_data(pool):
    """Download, parse, geo-match and seed all NGED CIM data (background task)."""
    log.info("Starting NGED CIM data seeding...")
    try:
        # Check if already seeded
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT count(*) FROM nged_substation")
            if count > 0:
                log.info("NGED CIM data already seeded (%d substations), skipping", count)
                return

        # Download all regional data
        xml_data = await download_cim_data()
        if not xml_data:
            log.warning("No NGED CIM data downloaded — skipping seed")
            return

        # Parse all regions
        all_substations = []
        all_parsed = {"substations": [], "transformers": [],
                      "line_segments": [], "consumers": []}

        for region, xml_bytes in xml_data.items():
            try:
                parsed = parse_cim_xml(xml_bytes, region)
                for key in all_parsed:
                    all_parsed[key].extend(parsed[key])
                all_substations.extend(parsed["substations"])
                log.info("Parsed %s: %d subs, %d xfmrs, %d lines, %d consumers",
                         region, len(parsed["substations"]),
                         len(parsed["transformers"]),
                         len(parsed["line_segments"]),
                         len(parsed["consumers"]))
            except ET.ParseError as e:
                log.warning("Failed to parse CIM XML for %s: %s", region, e)

        # Geo-match substations against OSM
        async with pool.acquire() as conn:
            all_parsed["substations"] = await geo_match_substations(conn, all_substations)

        # Insert into database
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _insert_parsed_data(conn, all_parsed)

        log.info("NGED CIM seeding complete: %d substations, %d transformers, "
                 "%d line segments, %d consumers",
                 len(all_parsed["substations"]), len(all_parsed["transformers"]),
                 len(all_parsed["line_segments"]), len(all_parsed["consumers"]))

    except Exception:
        log.exception("NGED CIM seeding failed")


# ---------------------------------------------------------------------------
# Opportunity analysis
# ---------------------------------------------------------------------------
async def calc_headroom(conn, substation_id: str) -> dict:
    """Calculate available headroom at a substation (rated MVA - connected load)."""
    # Total transformer capacity at this substation
    rated = await conn.fetchval("""
        SELECT COALESCE(SUM(rated_mva), 0) FROM nged_transformer
        WHERE substation_id = $1
    """, substation_id)

    # Total connected load
    load = await conn.fetchval("""
        SELECT COALESCE(SUM(p_mw), 0) FROM nged_energy_consumer
        WHERE substation_id = $1
    """, substation_id)

    rated_mva = float(rated) if rated else 0.0
    load_mw = float(load) if load else 0.0
    headroom_mw = rated_mva - load_mw  # MVA ≈ MW at unity PF

    return {
        "substation_id": substation_id,
        "rated_mva": round(rated_mva, 2),
        "connected_load_mw": round(load_mw, 2),
        "headroom_mw": round(headroom_mw, 2),
        "utilisation_pct": round(load_mw / rated_mva * 100, 1) if rated_mva > 0 else None,
    }


async def find_opportunities(conn, west: float, south: float,
                             east: float, north: float,
                             min_headroom_mw: float = 1.0) -> dict:
    """Find substations with spare capacity in a bounding box."""
    rows = await conn.fetch("""
        WITH sub_capacity AS (
            SELECT s.id, s.name, s.region, s.voltage_kv,
                   ST_Y(s.geometry) AS lat, ST_X(s.geometry) AS lon,
                   s.osm_match_score,
                   COALESCE(SUM(t.rated_mva), 0) AS rated_mva,
                   COALESCE((SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                             WHERE ec.substation_id = s.id), 0) AS load_mw
            FROM nged_substation s
            LEFT JOIN nged_transformer t ON t.substation_id = s.id
            WHERE s.geometry IS NOT NULL
              AND s.geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
            GROUP BY s.id, s.name, s.region, s.voltage_kv, s.geometry, s.osm_match_score
        )
        SELECT *, (rated_mva - load_mw) AS headroom_mw
        FROM sub_capacity
        WHERE (rated_mva - load_mw) >= $5
        ORDER BY (rated_mva - load_mw) DESC
    """, west, south, east, north, min_headroom_mw)

    features = []
    for r in rows:
        features.append({
            "id": r["id"],
            "name": r["name"],
            "region": r["region"],
            "voltage_kv": r["voltage_kv"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "rated_mva": round(float(r["rated_mva"]), 2),
            "connected_load_mw": round(float(r["load_mw"]), 2),
            "headroom_mw": round(float(r["headroom_mw"]), 2),
            "osm_match_score": float(r["osm_match_score"]) if r["osm_match_score"] else None,
        })

    return {"opportunities": features, "count": len(features)}


async def find_opportunities_near(conn, lat: float, lon: float,
                                  radius_km: float = 15,
                                  min_headroom_mw: float = 1.0) -> dict:
    """Find substations with spare capacity near a point (for chat tool)."""
    rows = await conn.fetch("""
        WITH sub_capacity AS (
            SELECT s.id, s.name, s.region, s.voltage_kv,
                   ST_Y(s.geometry) AS lat, ST_X(s.geometry) AS lon,
                   s.osm_match_score,
                   COALESCE(SUM(t.rated_mva), 0) AS rated_mva,
                   COALESCE((SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                             WHERE ec.substation_id = s.id), 0) AS load_mw,
                   ST_Distance(s.geometry::geography,
                               ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography) / 1000 AS dist_km
            FROM nged_substation s
            LEFT JOIN nged_transformer t ON t.substation_id = s.id
            WHERE s.geometry IS NOT NULL
              AND ST_DWithin(s.geometry::geography,
                             ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography,
                             $3 * 1000)
            GROUP BY s.id, s.name, s.region, s.voltage_kv, s.geometry, s.osm_match_score
        )
        SELECT *, (rated_mva - load_mw) AS headroom_mw
        FROM sub_capacity
        WHERE (rated_mva - load_mw) >= $4
        ORDER BY (rated_mva - load_mw) DESC
        LIMIT 20
    """, lat, lon, radius_km, min_headroom_mw)

    results = []
    for r in rows:
        results.append({
            "name": r["name"],
            "region": r["region"],
            "voltage_kv": r["voltage_kv"],
            "distance_km": round(float(r["dist_km"]), 1),
            "rated_mva": round(float(r["rated_mva"]), 2),
            "connected_load_mw": round(float(r["load_mw"]), 2),
            "headroom_mw": round(float(r["headroom_mw"]), 2),
            "match_confidence": float(r["osm_match_score"]) if r["osm_match_score"] else None,
        })

    return {
        "search_centre": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "min_headroom_mw": min_headroom_mw,
        "results": results,
        "count": len(results),
    }


async def opportunity_summary(conn) -> dict:
    """Regional breakdown of available headroom and top opportunities."""
    # Regional stats
    regions = await conn.fetch("""
        SELECT s.region,
               COUNT(DISTINCT s.id) AS substation_count,
               COUNT(DISTINCT CASE WHEN s.geometry IS NOT NULL THEN s.id END) AS geo_matched,
               COALESCE(SUM(t.rated_mva), 0) AS total_rated_mva,
               COALESCE((SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                         WHERE ec.substation_id IN (
                             SELECT id FROM nged_substation WHERE region = s.region
                         )), 0) AS total_load_mw
        FROM nged_substation s
        LEFT JOIN nged_transformer t ON t.substation_id = s.id
        GROUP BY s.region
        ORDER BY s.region
    """)

    region_stats = []
    total_subs = 0
    total_matched = 0
    total_rated = 0.0
    total_load = 0.0

    for r in regions:
        count = r["substation_count"]
        matched = r["geo_matched"]
        rated = float(r["total_rated_mva"])
        load = float(r["total_load_mw"])
        region_stats.append({
            "region": r["region"],
            "substations": count,
            "geo_matched": matched,
            "match_pct": round(matched / count * 100, 1) if count > 0 else 0,
            "total_rated_mva": round(rated, 1),
            "total_load_mw": round(load, 1),
            "total_headroom_mw": round(rated - load, 1),
        })
        total_subs += count
        total_matched += matched
        total_rated += rated
        total_load += load

    # Top 10 opportunities
    top = await conn.fetch("""
        WITH sub_cap AS (
            SELECT s.id, s.name, s.region, s.voltage_kv,
                   COALESCE(SUM(t.rated_mva), 0) AS rated_mva,
                   COALESCE((SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                             WHERE ec.substation_id = s.id), 0) AS load_mw
            FROM nged_substation s
            LEFT JOIN nged_transformer t ON t.substation_id = s.id
            WHERE s.geometry IS NOT NULL
            GROUP BY s.id, s.name, s.region, s.voltage_kv
        )
        SELECT *, (rated_mva - load_mw) AS headroom_mw
        FROM sub_cap
        WHERE rated_mva > 0
        ORDER BY (rated_mva - load_mw) DESC
        LIMIT 10
    """)

    top_opportunities = []
    for r in top:
        top_opportunities.append({
            "id": r["id"],
            "name": r["name"],
            "region": r["region"],
            "voltage_kv": r["voltage_kv"],
            "rated_mva": round(float(r["rated_mva"]), 2),
            "headroom_mw": round(float(r["headroom_mw"]), 2),
        })

    # RAG breakdown
    rag = await conn.fetch("""
        WITH sub_cap AS (
            SELECT s.id,
                   COALESCE(SUM(t.rated_mva), 0) AS rated_mva,
                   COALESCE((SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                             WHERE ec.substation_id = s.id), 0) AS load_mw
            FROM nged_substation s
            LEFT JOIN nged_transformer t ON t.substation_id = s.id
            WHERE s.geometry IS NOT NULL AND
                  EXISTS (SELECT 1 FROM nged_transformer t2 WHERE t2.substation_id = s.id)
            GROUP BY s.id
        )
        SELECT
            COUNT(*) FILTER (WHERE (rated_mva - load_mw) > 5) AS green,
            COUNT(*) FILTER (WHERE (rated_mva - load_mw) BETWEEN 1 AND 5) AS amber,
            COUNT(*) FILTER (WHERE (rated_mva - load_mw) < 1) AS red
        FROM sub_cap
    """)

    rag_row = rag[0] if rag else {"green": 0, "amber": 0, "red": 0}

    return {
        "total_substations": total_subs,
        "geo_matched": total_matched,
        "match_pct": round(total_matched / total_subs * 100, 1) if total_subs > 0 else 0,
        "total_rated_mva": round(total_rated, 1),
        "total_load_mw": round(total_load, 1),
        "total_headroom_mw": round(total_rated - total_load, 1),
        "rag": {
            "green": rag_row["green"],
            "amber": rag_row["amber"],
            "red": rag_row["red"],
        },
        "regions": region_stats,
        "top_opportunities": top_opportunities,
    }


async def substations_geojson(conn, west: float, south: float,
                              east: float, north: float) -> dict:
    """GeoJSON FeatureCollection of NGED substations with headroom properties."""
    # NULL-preserving aggregates: distinguish "no transformers found" from
    # "transformers exist but rated_mva is placeholder". Without this the
    # popup shows fake zeros where the upstream LTDS CIM data is missing.
    # is_canonical filter dedupes coord-collisions (Astrazeneca east_midlands
    # vs Astra Zeneca south_west). The flag is maintained by the dedupe SQL
    # in app/migrations/0020_nged_substation_dedupe.sql; rows where it's
    # FALSE are duplicate names at coords already covered by the canonical row.
    rows = await conn.fetch("""
        SELECT s.id, s.name, s.region, s.voltage_kv,
               ST_Y(s.geometry) AS lat, ST_X(s.geometry) AS lon,
               s.osm_match_score,
               SUM(t.rated_mva) FILTER (WHERE t.rated_mva IS NOT NULL) AS rated_mva,
               COUNT(t.id) AS transformer_count,
               (SELECT SUM(ec.p_mw) FROM nged_energy_consumer ec
                 WHERE ec.substation_id = s.id
                   AND ec.p_mw IS NOT NULL) AS load_mw,
               (SELECT COUNT(*) FROM nged_energy_consumer ec
                 WHERE ec.substation_id = s.id) AS consumer_count
        FROM nged_substation s
        LEFT JOIN nged_transformer t ON t.substation_id = s.id
        WHERE s.geometry IS NOT NULL
          AND s.geometry && ST_MakeEnvelope($1, $2, $3, $4, 4326)
          AND COALESCE(s.is_canonical, TRUE)
        GROUP BY s.id, s.name, s.region, s.voltage_kv, s.geometry, s.osm_match_score
    """, west, south, east, north)

    # Treat the well-known LTDS placeholder (every transformer = exactly 100 MVA
    # and only one transformer) as missing data rather than a real rating.
    PLACEHOLDER_RATED_MVA = 100.0

    features = []
    for r in rows:
        rated_raw = r["rated_mva"]
        rated = float(rated_raw) if rated_raw is not None else None
        if rated is not None and r["transformer_count"] == 1 and abs(rated - PLACEHOLDER_RATED_MVA) < 0.01:
            rated = None  # placeholder — surface as unknown

        load = float(r["load_mw"]) if r["load_mw"] is not None else None
        # If no consumers linked at all, load is unknown — not zero.
        if r["consumer_count"] == 0:
            load = None

        headroom = (rated - load) if (rated is not None and load is not None) else None

        if headroom is not None:
            rag = "green" if headroom > 5 else "amber" if headroom >= 1 else "red"
        else:
            rag = "unknown"

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "id": r["id"],
                "name": r["name"],
                "region": r["region"],
                "voltage_kv": r["voltage_kv"],
                "rated_mva": round(rated, 2) if rated is not None else None,
                "connected_load_mw": round(load, 2) if load is not None else None,
                "headroom_mw": round(headroom, 2) if headroom is not None else None,
                "transformer_count": int(r["transformer_count"]),
                "consumer_count": int(r["consumer_count"]),
                "osm_match_score": float(r["osm_match_score"]) if r["osm_match_score"] else None,
                "data_quality": (
                    "complete" if (rated is not None and load is not None)
                    else "rating_only" if rated is not None
                    else "load_only" if load is not None
                    else "name_only"
                ),
                "rag": rag,
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def substation_detail(conn, substation_id: str) -> dict | None:
    """Full detail for a single substation including transformers and consumers."""
    sub = await conn.fetchrow("""
        SELECT id, name, region, voltage_kv,
               ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
               osm_match_score, osm_match_name
        FROM nged_substation WHERE id = $1
    """, substation_id)

    if not sub:
        return None

    transformers = await conn.fetch("""
        SELECT id, name, rated_mva, voltage_kv
        FROM nged_transformer WHERE substation_id = $1
    """, substation_id)

    consumers = await conn.fetch("""
        SELECT id, name, p_mw
        FROM nged_energy_consumer WHERE substation_id = $1
    """, substation_id)

    headroom = await calc_headroom(conn, substation_id)

    return {
        "id": sub["id"],
        "name": sub["name"],
        "region": sub["region"],
        "voltage_kv": sub["voltage_kv"],
        "lat": float(sub["lat"]) if sub["lat"] else None,
        "lon": float(sub["lon"]) if sub["lon"] else None,
        "osm_match_score": float(sub["osm_match_score"]) if sub["osm_match_score"] else None,
        "osm_match_name": sub["osm_match_name"],
        "headroom": headroom,
        "transformers": [
            {"id": t["id"], "name": t["name"],
             "rated_mva": float(t["rated_mva"]) if t["rated_mva"] else None,
             "voltage_kv": float(t["voltage_kv"]) if t["voltage_kv"] else None}
            for t in transformers
        ],
        "consumers": [
            {"id": c["id"], "name": c["name"],
             "p_mw": float(c["p_mw"]) if c["p_mw"] else None}
            for c in consumers
        ],
    }


async def get_transformers(conn, substation_id: str) -> list[dict]:
    """List transformers at a substation."""
    rows = await conn.fetch("""
        SELECT id, name, rated_mva, voltage_kv
        FROM nged_transformer WHERE substation_id = $1
        ORDER BY rated_mva DESC NULLS LAST
    """, substation_id)
    return [
        {"id": r["id"], "name": r["name"],
         "rated_mva": float(r["rated_mva"]) if r["rated_mva"] else None,
         "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None}
        for r in rows
    ]


async def get_line_segments(conn, substation_id: str | None = None,
                            region: str | None = None) -> list[dict]:
    """List line segments, optionally filtered."""
    if region:
        rows = await conn.fetch("""
            SELECT id, name, length_km, r_ohm, x_ohm, voltage_kv, region
            FROM nged_line_segment WHERE region = $1
            ORDER BY length_km DESC NULLS LAST LIMIT 100
        """, region)
    else:
        rows = await conn.fetch("""
            SELECT id, name, length_km, r_ohm, x_ohm, voltage_kv, region
            FROM nged_line_segment
            ORDER BY length_km DESC NULLS LAST LIMIT 100
        """)
    return [
        {"id": r["id"], "name": r["name"],
         "length_km": float(r["length_km"]) if r["length_km"] else None,
         "r_ohm": float(r["r_ohm"]) if r["r_ohm"] else None,
         "x_ohm": float(r["x_ohm"]) if r["x_ohm"] else None,
         "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
         "region": r["region"]}
        for r in rows
    ]


async def enrich_opportunities_with_satellite(
    conn,
    opportunities: list[dict],
    geeflow_data: dict | None = None,
) -> list[dict]:
    """
    Enrich NGED grid opportunities with satellite-derived suitability data.

    Adds land use and terrain context from GeeFlow extraction results
    to each opportunity for improved site selection.
    """
    if not geeflow_data:
        return opportunities

    from utils.geeflow_grid_analysis import identify_underserved_areas
    result = identify_underserved_areas(opportunities, geeflow_data)
    return result.get("areas", opportunities)
