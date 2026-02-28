"""
ESO TEC Register — ingest and query the Transmission Entry Capacity register.

Source: data.nationalgrideso.com CKAN datastore API (JSON, paginated).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.eso_tec_register")

_TIMEOUT = 30

# CKAN datastore API on data.nationalgrideso.com
# The resource ID may change when ESO republish — this is the TEC register resource.
TEC_API_BASE = "https://data.nationalgrideso.com/api/3/action/datastore_search"
TEC_RESOURCE_ID = "db2c8005-54df-4024-a7b7-62bcf2b7a4e3"
TEC_PAGE_SIZE = 5000

FUEL_CATEGORY_MAP = {
    "solar": "solar",
    "photovoltaic": "solar",
    "pv": "solar",
    "wind": "wind",
    "onshore wind": "wind",
    "offshore wind": "wind",
    "battery": "bess",
    "storage": "bess",
    "bess": "bess",
    "gas": "gas",
    "ccgt": "gas",
    "ocgt": "gas",
    "nuclear": "nuclear",
    "biomass": "biomass",
    "hydro": "hydro",
    "pumped storage": "hydro",
    "interconnector": "interconnector",
}


def _classify_fuel(fuel_type: str | None) -> str:
    if not fuel_type:
        return "other"
    lower = fuel_type.strip().lower()
    for key, cat in FUEL_CATEGORY_MAP.items():
        if key in lower:
            return cat
    return "other"


def _parse_date(val):
    if not val or not str(val).strip():
        return None
    import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(str(val).strip()[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).strip().replace(",", "")))
    except (ValueError, TypeError):
        return None


# ── Table setup ──────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS eso_tec_register (
    tec_id             TEXT PRIMARY KEY,
    customer_name      TEXT,
    connection_site    TEXT,
    fuel_type          TEXT,
    tech_category      TEXT,
    tec_mw             DOUBLE PRECISION,
    status             TEXT,
    effective_from     DATE,
    effective_to       DATE,
    connection_date    DATE,
    voltage_kv         DOUBLE PRECISION,
    zone               TEXT,
    dnc_mw             DOUBLE PRECISION,
    spv_name           TEXT,
    parent_company     TEXT,
    queue_position     INTEGER,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Point, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tec_geom            ON eso_tec_register USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_tec_tech_category    ON eso_tec_register (tech_category);
CREATE INDEX IF NOT EXISTS idx_tec_status           ON eso_tec_register (status);
CREATE INDEX IF NOT EXISTS idx_tec_connection_site  ON eso_tec_register (connection_site);
"""


async def setup_tec_table(conn: asyncpg.Connection):
    """Create eso_tec_register table if not exists."""
    for stmt in CREATE_TABLE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(stmt)
    log.info("eso_tec_register table ensured")


# ── Ingestion ────────────────────────────────────────────────────────────

async def ingest_tec_register(conn_or_pool) -> dict:
    """Fetch ESO TEC register via CKAN API and upsert."""
    t0 = time.time()

    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        inserted = 0
        offset = 0

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            while True:
                r = await client.get(TEC_API_BASE, params={
                    "resource_id": TEC_RESOURCE_ID,
                    "limit": TEC_PAGE_SIZE,
                    "offset": offset,
                })
                r.raise_for_status()
                data = r.json()

                records = data.get("result", {}).get("records", [])
                if not records:
                    break

                for row in records:
                    tec_id = str(row.get("_id", "")).strip()
                    if not tec_id:
                        continue

                    fuel_type = str(row.get("Fuel Type", "")).strip()
                    tech_category = _classify_fuel(fuel_type)
                    tec_mw = _parse_float(row.get("TEC (MW)") or row.get("TEC"))
                    connection_site = str(row.get("Connection Site", "")).strip()
                    status = str(row.get("Status", "")).strip()

                    # Try to geocode via dno_substations if connection_site matches
                    geom_sql = "NULL"
                    if connection_site:
                        geom_sql = f"""
                            (SELECT geometry FROM dno_substations
                             WHERE name ILIKE '%' || ${8} || '%'
                             LIMIT 1)
                        """

                    customer = str(row.get("Customer Name", "")).strip() or None
                    spv = str(row.get("SPV", row.get("Project Name", ""))).strip() or None
                    parent = str(row.get("Parent Company", "")).strip() or None
                    voltage = _parse_float(row.get("Voltage (kV)"))
                    zone = str(row.get("Zone", "")).strip() or None
                    dnc = _parse_float(row.get("DNC (MW)"))
                    eff_from = _parse_date(row.get("Effective From"))
                    eff_to = _parse_date(row.get("Effective To"))
                    conn_date = _parse_date(row.get("Connection Date") or row.get("Expected Connection Date"))

                    await conn.execute(f"""
                        INSERT INTO eso_tec_register (
                            tec_id, customer_name, connection_site, fuel_type, tech_category,
                            tec_mw, status, effective_from, effective_to, connection_date,
                            voltage_kv, zone, dnc_mw, spv_name, parent_company,
                            geometry, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5,
                            $6, $7, $9, $10, $11,
                            $12, $13, $14, $15, $16,
                            {geom_sql if connection_site else 'NULL'}, NOW()
                        )
                        ON CONFLICT (tec_id) DO UPDATE SET
                            tec_mw = EXCLUDED.tec_mw,
                            status = EXCLUDED.status,
                            effective_to = EXCLUDED.effective_to,
                            connection_date = EXCLUDED.connection_date,
                            updated_at = NOW()
                    """,
                        tec_id, customer, connection_site, fuel_type, tech_category,
                        tec_mw, status, connection_site,
                        eff_from, eff_to, conn_date,
                        voltage, zone, dnc, spv, parent,
                    )
                    inserted += 1

                offset += len(records)
                if len(records) < TEC_PAGE_SIZE:
                    break

        elapsed = round(time.time() - t0, 1)
        log.info("TEC register ingestion complete: %d rows in %.1fs", inserted, elapsed)
        return {"inserted": inserted, "elapsed_s": elapsed}

    except Exception as e:
        log.error("TEC register ingestion failed: %s", e)
        return {"error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Query ────────────────────────────────────────────────────────────────

async def query_tec(
    conn: asyncpg.Connection,
    *,
    tech_category: str | None = None,
    status: str | None = None,
    connection_site: str | None = None,
    customer_name: str | None = None,
    min_tec_mw: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    limit: int = 50,
) -> list[dict]:
    """Query TEC register with filters and optional spatial search."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if tech_category:
        conditions.append(f"tech_category = ${idx}")
        params.append(tech_category)
        idx += 1
    if status:
        conditions.append(f"status ILIKE ${idx}")
        params.append(f"%{status}%")
        idx += 1
    if connection_site:
        conditions.append(f"connection_site ILIKE ${idx}")
        params.append(f"%{connection_site}%")
        idx += 1
    if customer_name:
        conditions.append(f"customer_name ILIKE ${idx}")
        params.append(f"%{customer_name}%")
        idx += 1
    if min_tec_mw is not None:
        conditions.append(f"tec_mw >= ${idx}")
        params.append(min_tec_mw)
        idx += 1
    if lat is not None and lon is not None:
        conditions.append(
            f"geometry IS NOT NULL AND ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint(${idx}, ${idx+1}), 4326), 27700), ${idx+2})"
        )
        params.extend([lon, lat, radius_km * 1000])
        idx += 3

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = await conn.fetch(f"""
        SELECT tec_id, customer_name, connection_site, fuel_type, tech_category,
               tec_mw, status, effective_from, effective_to, connection_date,
               voltage_kv, zone, dnc_mw, spv_name, parent_company
        FROM eso_tec_register
        {where}
        ORDER BY tec_mw DESC NULLS LAST
        LIMIT {limit}
    """, *params)

    return [dict(r) for r in rows]


async def tec_summary(conn: asyncpg.Connection) -> dict:
    """Aggregate TEC register by fuel type, status, connection site."""
    by_fuel = await conn.fetch("""
        SELECT tech_category, count(*) AS cnt, coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register GROUP BY tech_category ORDER BY total_mw DESC
    """)
    by_status = await conn.fetch("""
        SELECT status, count(*) AS cnt, coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register GROUP BY status ORDER BY cnt DESC
    """)
    top_sites = await conn.fetch("""
        SELECT connection_site, count(*) AS cnt, coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        WHERE connection_site IS NOT NULL AND connection_site != ''
        GROUP BY connection_site ORDER BY total_mw DESC LIMIT 20
    """)
    total = await conn.fetchval("SELECT count(*) FROM eso_tec_register")
    total_mw = await conn.fetchval("SELECT coalesce(sum(tec_mw), 0) FROM eso_tec_register")

    return {
        "total_entries": total,
        "total_mw": round(float(total_mw), 1),
        "by_fuel_type": [dict(r) for r in by_fuel],
        "by_status": [dict(r) for r in by_status],
        "top_connection_sites": [dict(r) for r in top_sites],
    }


async def connection_queue_analysis(conn: asyncpg.Connection, connection_site: str) -> dict:
    """Detailed analysis of the connection queue at a specific substation."""
    rows = await conn.fetch("""
        SELECT tec_id, customer_name, fuel_type, tech_category, tec_mw, status,
               connection_date, queue_position
        FROM eso_tec_register
        WHERE connection_site ILIKE $1
        ORDER BY queue_position NULLS LAST, tec_mw DESC
    """, f"%{connection_site}%")

    if not rows:
        return {"connection_site": connection_site, "queue_depth": 0, "entries": []}

    by_tech = {}
    by_status = {}
    total_mw = 0.0
    for r in rows:
        cat = r["tech_category"] or "other"
        by_tech[cat] = by_tech.get(cat, 0) + float(r["tec_mw"] or 0)
        st = r["status"] or "Unknown"
        by_status[st] = by_status.get(st, 0) + 1
        total_mw += float(r["tec_mw"] or 0)

    return {
        "connection_site": connection_site,
        "queue_depth": len(rows),
        "total_mw": round(total_mw, 1),
        "by_technology_mw": by_tech,
        "by_status": by_status,
        "entries": [dict(r) for r in rows],
    }
