"""
dc_infra_ingester.py — Data centre infrastructure ingestion for Princeps.

Fetches and upserts fibre POPs, IXP nodes, water bodies, and existing DC
facilities from OSM Overpass and PeeringDB into PostGIS tables.  Follows
the adapter pattern from grid_data_ingester.py.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.dc_infra")

# ---------------------------------------------------------------------------
# Reference data — UK Internet Exchange Points (PeeringDB fallback/seed)
# ---------------------------------------------------------------------------
UK_IXP_REFERENCE: list[dict] = [
    {"name": "LINX LON1", "city": "London", "lat": 51.5185, "lon": -0.0580, "peeringdb_id": 18, "participants": 950},
    {"name": "LINX LON2", "city": "London", "lat": 51.5076, "lon": -0.0175, "peeringdb_id": 621, "participants": 200},
    {"name": "LONAP", "city": "London", "lat": 51.5230, "lon": -0.0716, "peeringdb_id": 57, "participants": 160},
    {"name": "IXManchester", "city": "Manchester", "lat": 53.4723, "lon": -2.2935, "peeringdb_id": 250, "participants": 60},
    {"name": "IXLeeds", "city": "Leeds", "lat": 53.7960, "lon": -1.5430, "peeringdb_id": 560, "participants": 30},
    {"name": "IXScotland", "city": "Edinburgh", "lat": 55.9485, "lon": -3.1999, "peeringdb_id": 607, "participants": 30},
    {"name": "IXCardiff", "city": "Cardiff", "lat": 51.4816, "lon": -3.1791, "peeringdb_id": 850, "participants": 15},
    {"name": "MidNAP", "city": "Nottingham", "lat": 52.9535, "lon": -1.1500, "peeringdb_id": 830, "participants": 20},
    {"name": "BIX (Brighton)", "city": "Brighton", "lat": 50.8225, "lon": -0.1372, "peeringdb_id": 851, "participants": 10},
    {"name": "LINX Scotland", "city": "Edinburgh", "lat": 55.9533, "lon": -3.1883, "peeringdb_id": 874, "participants": 25},
    {"name": "LINX NoVA", "city": "Manchester", "lat": 53.4808, "lon": -2.2426, "peeringdb_id": 759, "participants": 40},
    {"name": "LINX Juniper", "city": "London", "lat": 51.5120, "lon": -0.0020, "peeringdb_id": 935, "participants": 80},
]

# ---------------------------------------------------------------------------
# Overpass QL query templates
# ---------------------------------------------------------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

FIBRE_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="GB"]->.gb;
(
  node["telecom"="exchange"](area.gb);
  node["man_made"="communications_tower"](area.gb);
  way["telecom"="exchange"](area.gb);
);
out center 5000;
"""

WATER_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="GB"]->.gb;
(
  way["natural"="water"]["water"!="pond"](area.gb);
  way["waterway"~"river|canal"](area.gb);
  way["landuse"="reservoir"](area.gb);
  relation["natural"="water"]["water"!="pond"](area.gb);
  relation["waterway"~"river|canal"](area.gb);
);
out center 5000;
"""

DC_FACILITY_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="GB"]->.gb;
(
  node["building"~"data_cent(re|er)"](area.gb);
  way["building"~"data_cent(re|er)"](area.gb);
  node["man_made"="data_center"](area.gb);
  way["man_made"="data_center"](area.gb);
);
out center 2000;
"""

PEERINGDB_URL = "https://www.peeringdb.com/api/ix?country=GB"


# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------
async def setup_dc_tables(conn: asyncpg.Connection) -> None:
    """Create DC infrastructure tables (idempotent)."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_fibre_pops (
            pop_id        SERIAL PRIMARY KEY,
            osm_id        BIGINT UNIQUE,
            name          TEXT,
            operator      TEXT,
            pop_type      TEXT DEFAULT 'exchange',
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            geometry      GEOMETRY(Point, 27700),
            tags          JSONB DEFAULT '{}',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dc_fibre_pops_geom
        ON dc_fibre_pops USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_ixp_nodes (
            ixp_id        SERIAL PRIMARY KEY,
            peeringdb_id  INTEGER UNIQUE,
            name          TEXT NOT NULL,
            city          TEXT,
            participants  INTEGER DEFAULT 0,
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            geometry      GEOMETRY(Point, 27700),
            source        TEXT DEFAULT 'peeringdb',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dc_ixp_nodes_geom
        ON dc_ixp_nodes USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_water_bodies (
            water_id      SERIAL PRIMARY KEY,
            osm_id        BIGINT UNIQUE,
            name          TEXT,
            water_type    TEXT DEFAULT 'water',
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            geometry      GEOMETRY(Point, 27700),
            tags          JSONB DEFAULT '{}',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dc_water_bodies_geom
        ON dc_water_bodies USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_facilities (
            facility_id   SERIAL PRIMARY KEY,
            osm_id        BIGINT UNIQUE,
            name          TEXT,
            operator      TEXT,
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            geometry      GEOMETRY(Point, 27700),
            tags          JSONB DEFAULT '{}',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dc_facilities_geom
        ON dc_facilities USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_assessments (
            assessment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lat           DOUBLE PRECISION NOT NULL,
            lon           DOUBLE PRECISION NOT NULL,
            capacity_mw   DOUBLE PRECISION,
            profile       TEXT DEFAULT 'colocation',
            dc_score      DOUBLE PRECISION,
            verdict       TEXT,
            result_data   JSONB NOT NULL,
            geometry      GEOMETRY(Point, 27700),
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dc_assessments_geom
        ON dc_assessments USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_ingestion_log (
            log_id        SERIAL PRIMARY KEY,
            source        TEXT NOT NULL,
            records       INTEGER DEFAULT 0,
            status        TEXT DEFAULT 'ok',
            error         TEXT,
            elapsed_s     DOUBLE PRECISION,
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    log.info("DC infrastructure tables ready")


# ---------------------------------------------------------------------------
# Overpass adapter
# ---------------------------------------------------------------------------
class OverpassDCAdapter:
    """Fetch fibre POPs, water bodies, and DC facilities from OSM."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    async def _fetch(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()
            return data.get("elements", [])

    def _extract_point(self, el: dict) -> tuple[float, float] | None:
        if el.get("type") == "node":
            return el.get("lat"), el.get("lon")
        center = el.get("center")
        if center:
            return center.get("lat"), center.get("lon")
        return None

    async def fetch_fibre_pops(self) -> list[dict]:
        elements = await self._fetch(FIBRE_QUERY)
        pops = []
        for el in elements:
            pt = self._extract_point(el)
            if not pt:
                continue
            tags = el.get("tags", {})
            pops.append({
                "osm_id": el["id"],
                "name": tags.get("name", tags.get("operator", f"POP-{el['id']}")),
                "operator": tags.get("operator", ""),
                "pop_type": tags.get("telecom", tags.get("man_made", "exchange")),
                "lat": pt[0],
                "lon": pt[1],
                "tags": tags,
            })
        log.info("Overpass: fetched %d fibre POPs", len(pops))
        return pops

    async def fetch_water_bodies(self) -> list[dict]:
        elements = await self._fetch(WATER_QUERY)
        bodies = []
        for el in elements:
            pt = self._extract_point(el)
            if not pt:
                continue
            tags = el.get("tags", {})
            water_type = (
                tags.get("waterway")
                or tags.get("water")
                or tags.get("landuse")
                or tags.get("natural", "water")
            )
            bodies.append({
                "osm_id": el["id"],
                "name": tags.get("name", f"Water-{el['id']}"),
                "water_type": water_type,
                "lat": pt[0],
                "lon": pt[1],
                "tags": tags,
            })
        log.info("Overpass: fetched %d water bodies", len(bodies))
        return bodies

    async def fetch_dc_facilities(self) -> list[dict]:
        elements = await self._fetch(DC_FACILITY_QUERY)
        facilities = []
        for el in elements:
            pt = self._extract_point(el)
            if not pt:
                continue
            tags = el.get("tags", {})
            facilities.append({
                "osm_id": el["id"],
                "name": tags.get("name", f"DC-{el['id']}"),
                "operator": tags.get("operator", ""),
                "lat": pt[0],
                "lon": pt[1],
                "tags": tags,
            })
        log.info("Overpass: fetched %d DC facilities", len(facilities))
        return facilities


# ---------------------------------------------------------------------------
# PeeringDB adapter
# ---------------------------------------------------------------------------
class PeeringDBAdapter:
    """Fetch UK IXP nodes from PeeringDB public API."""

    async def fetch_ixps(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(PEERINGDB_URL)
                resp.raise_for_status()
                data = resp.json().get("data", [])
        except Exception as e:
            log.warning("PeeringDB fetch failed, using hardcoded reference: %s", e)
            return UK_IXP_REFERENCE

        # PeeringDB doesn't always include coordinates — merge with reference
        ref_by_id = {r["peeringdb_id"]: r for r in UK_IXP_REFERENCE}
        ixps = []
        for ix in data:
            pid = ix.get("id")
            ref = ref_by_id.get(pid, {})
            lat = ix.get("latitude") or ref.get("lat")
            lon = ix.get("longitude") or ref.get("lon")
            if not lat or not lon:
                continue
            ixps.append({
                "peeringdb_id": pid,
                "name": ix.get("name", ref.get("name", f"IXP-{pid}")),
                "city": ix.get("city", ref.get("city", "")),
                "participants": ix.get("net_count", ref.get("participants", 0)),
                "lat": float(lat),
                "lon": float(lon),
            })

        # Ensure all reference IXPs are included
        seen_ids = {i["peeringdb_id"] for i in ixps}
        for ref in UK_IXP_REFERENCE:
            if ref["peeringdb_id"] not in seen_ids:
                ixps.append(ref)

        log.info("PeeringDB: resolved %d UK IXPs", len(ixps))
        return ixps


# ---------------------------------------------------------------------------
# Upsert functions
# ---------------------------------------------------------------------------
async def upsert_fibre_pops(conn: asyncpg.Connection, pops: list[dict]) -> int:
    count = 0
    for p in pops:
        await conn.execute("""
            INSERT INTO dc_fibre_pops (osm_id, name, operator, pop_type, lat, lon, geometry, tags, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6,
                    ST_Transform(ST_SetSRID(ST_MakePoint($7, $8), 4326), 27700),
                    $9, NOW())
            ON CONFLICT (osm_id) DO UPDATE SET
                name = EXCLUDED.name,
                operator = EXCLUDED.operator,
                pop_type = EXCLUDED.pop_type,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                geometry = EXCLUDED.geometry,
                tags = EXCLUDED.tags,
                updated_at = NOW()
        """, p["osm_id"], p["name"], p["operator"], p["pop_type"],
            p["lat"], p["lon"], p["lon"], p["lat"],
            json.dumps(p.get("tags", {})))
        count += 1
    return count


async def upsert_ixp_nodes(conn: asyncpg.Connection, ixps: list[dict]) -> int:
    count = 0
    for ix in ixps:
        await conn.execute("""
            INSERT INTO dc_ixp_nodes (peeringdb_id, name, city, participants, lat, lon, geometry, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6,
                    ST_Transform(ST_SetSRID(ST_MakePoint($7, $8), 4326), 27700),
                    NOW())
            ON CONFLICT (peeringdb_id) DO UPDATE SET
                name = EXCLUDED.name,
                city = EXCLUDED.city,
                participants = EXCLUDED.participants,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                geometry = EXCLUDED.geometry,
                updated_at = NOW()
        """, ix["peeringdb_id"], ix["name"], ix["city"], ix["participants"],
            ix["lat"], ix["lon"], ix["lon"], ix["lat"])
        count += 1
    return count


async def upsert_water_bodies(conn: asyncpg.Connection, bodies: list[dict]) -> int:
    count = 0
    for b in bodies:
        await conn.execute("""
            INSERT INTO dc_water_bodies (osm_id, name, water_type, lat, lon, geometry, tags, updated_at)
            VALUES ($1, $2, $3, $4, $5,
                    ST_Transform(ST_SetSRID(ST_MakePoint($6, $7), 4326), 27700),
                    $8, NOW())
            ON CONFLICT (osm_id) DO UPDATE SET
                name = EXCLUDED.name,
                water_type = EXCLUDED.water_type,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                geometry = EXCLUDED.geometry,
                tags = EXCLUDED.tags,
                updated_at = NOW()
        """, b["osm_id"], b["name"], b["water_type"],
            b["lat"], b["lon"], b["lon"], b["lat"],
            json.dumps(b.get("tags", {})))
        count += 1
    return count


async def upsert_dc_facilities(conn: asyncpg.Connection, facilities: list[dict]) -> int:
    count = 0
    for f in facilities:
        await conn.execute("""
            INSERT INTO dc_facilities (osm_id, name, operator, lat, lon, geometry, tags, updated_at)
            VALUES ($1, $2, $3, $4, $5,
                    ST_Transform(ST_SetSRID(ST_MakePoint($6, $7), 4326), 27700),
                    $8, NOW())
            ON CONFLICT (osm_id) DO UPDATE SET
                name = EXCLUDED.name,
                operator = EXCLUDED.operator,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                geometry = EXCLUDED.geometry,
                tags = EXCLUDED.tags,
                updated_at = NOW()
        """, f["osm_id"], f["name"], f["operator"],
            f["lat"], f["lon"], f["lon"], f["lat"],
            json.dumps(f.get("tags", {})))
        count += 1
    return count


# ---------------------------------------------------------------------------
# Ingestion log
# ---------------------------------------------------------------------------
async def _log_ingestion(conn: asyncpg.Connection, source: str, records: int,
                         status: str = "ok", error: str | None = None,
                         elapsed: float = 0.0) -> None:
    await conn.execute("""
        INSERT INTO dc_ingestion_log (source, records, status, error, elapsed_s)
        VALUES ($1, $2, $3, $4, $5)
    """, source, records, status, error, elapsed)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def ingest_dc_infrastructure(pool: asyncpg.Pool) -> None:
    """Run full DC infrastructure ingestion pipeline."""
    log.info("Starting DC infrastructure ingestion")
    t0 = time.time()

    overpass = OverpassDCAdapter()
    peeringdb = PeeringDBAdapter()

    async with pool.acquire() as conn:
        # Fibre POPs
        try:
            t1 = time.time()
            pops = await overpass.fetch_fibre_pops()
            n = await upsert_fibre_pops(conn, pops)
            await _log_ingestion(conn, "overpass_fibre", n, elapsed=time.time() - t1)
        except Exception as e:
            log.warning("Fibre POP ingestion failed: %s", e)
            await _log_ingestion(conn, "overpass_fibre", 0, "error", str(e))

        # IXP nodes
        try:
            t1 = time.time()
            ixps = await peeringdb.fetch_ixps()
            n = await upsert_ixp_nodes(conn, ixps)
            await _log_ingestion(conn, "peeringdb_ixp", n, elapsed=time.time() - t1)
        except Exception as e:
            log.warning("IXP ingestion failed: %s", e)
            await _log_ingestion(conn, "peeringdb_ixp", 0, "error", str(e))

        # Water bodies
        try:
            t1 = time.time()
            bodies = await overpass.fetch_water_bodies()
            n = await upsert_water_bodies(conn, bodies)
            await _log_ingestion(conn, "overpass_water", n, elapsed=time.time() - t1)
        except Exception as e:
            log.warning("Water body ingestion failed: %s", e)
            await _log_ingestion(conn, "overpass_water", 0, "error", str(e))

        # DC facilities
        try:
            t1 = time.time()
            facilities = await overpass.fetch_dc_facilities()
            n = await upsert_dc_facilities(conn, facilities)
            await _log_ingestion(conn, "overpass_dc", n, elapsed=time.time() - t1)
        except Exception as e:
            log.warning("DC facility ingestion failed: %s", e)
            await _log_ingestion(conn, "overpass_dc", 0, "error", str(e))

    elapsed = time.time() - t0
    log.info("DC infrastructure ingestion complete in %.1fs", elapsed)
