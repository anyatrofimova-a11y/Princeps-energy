"""
REPD Tracker — ingest and query the Renewable Energy Planning Database.

Source: gov.uk REPD monthly CSV extract.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.repd_tracker")

_TIMEOUT = 30
_CACHE: dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 4 * 3600  # 4 hours

# REPD CSV hosted on gov.uk. The media-path-slug URL above used to redirect
# to the current quarter's CSV but the redirect has been unstable since 2025-Q3
# (observed silent 403/404). Use an explicit quarterly fallback ladder,
# most-recent-first — the scrape at REPD_PUBLICATIONS_URL runs as a last resort.
REPD_CSV_URL_FALLBACK_LADDER = [
    # 2025 Q4 — known-good from utils/repd.py
    "https://assets.publishing.service.gov.uk/media/6985c316d3f57710b50a9b1f/REPD_Publication_Q4_2025.csv",
    # 2025 Q3 / Q2 / Q1 — if DESNZ rotates the asset ID we fall to discovery.
    "https://assets.publishing.service.gov.uk/media/renewable-energy-planning-database-repd.csv",
]
REPD_CSV_URL = REPD_CSV_URL_FALLBACK_LADDER[0]
REPD_PUBLICATIONS_URL = (
    "https://www.gov.uk/government/publications/"
    "renewable-energy-planning-database-monthly-extract"
)

TECH_CATEGORY_MAP = {
    "solar photovoltaics": "solar",
    "battery": "bess",
    "battery storage": "bess",
    "wind onshore": "wind",
    "wind offshore": "wind",
    "biomass": "biomass",
    "landfill gas": "biomass",
    "sewage sludge digestion": "biomass",
    "anaerobic digestion": "biomass",
    "energy from waste": "biomass",
    "large hydro": "hydro",
    "small hydro": "hydro",
}

STATUS_MAP = {
    "operational": "Operational",
    "under construction": "Under Construction",
    "awaiting construction": "Awaiting Construction",
    "planning permission granted": "Approved",
    "application submitted": "Submitted",
    "appeal lodged": "Appeal",
    "appeal granted": "Approved",
    "refused": "Refused",
    "withdrawn": "Withdrawn",
    "decommissioned": "Decommissioned",
}


def _classify_tech(technology: str | None) -> str:
    if not technology:
        return "other"
    return TECH_CATEGORY_MAP.get(technology.strip().lower(), "other")


def _normalise_status(status: str | None) -> str:
    if not status:
        return "Unknown"
    return STATUS_MAP.get(status.strip().lower(), status.strip())


def _parse_date(val: str | None):
    if not val or not val.strip():
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            import datetime
            return datetime.datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip().replace(",", ""))
    except ValueError:
        return None


def _parse_int(val: str | None) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(float(val.strip().replace(",", "")))
    except ValueError:
        return None


# ── Table setup ──────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS repd_projects (
    repd_id            TEXT PRIMARY KEY,
    site_name          TEXT,
    technology         TEXT,
    tech_category      TEXT,
    capacity_mw        DOUBLE PRECISION,
    status             TEXT,
    developer          TEXT,
    operator           TEXT,
    planning_authority TEXT,
    planning_ref       TEXT,
    address            TEXT,
    county             TEXT,
    region             TEXT,
    country            TEXT,
    postcode           TEXT,
    mounting_type      TEXT,
    height_m           DOUBLE PRECISION,
    turbines           INTEGER,
    battery_mwh        DOUBLE PRECISION,
    co_located         BOOLEAN DEFAULT FALSE,
    appeal_ref         TEXT,
    date_submitted     DATE,
    date_decided       DATE,
    date_operational   DATE,
    planning_url       TEXT,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Point, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_repd_geom          ON repd_projects USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_repd_tech_category  ON repd_projects (tech_category);
CREATE INDEX IF NOT EXISTS idx_repd_status         ON repd_projects (status);
CREATE INDEX IF NOT EXISTS idx_repd_developer      ON repd_projects (developer);
CREATE INDEX IF NOT EXISTS idx_repd_region         ON repd_projects (region);
"""


async def setup_repd_table(conn: asyncpg.Connection):
    """Create repd_projects table if not exists."""
    for stmt in CREATE_TABLE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(stmt)
    log.info("repd_projects table ensured")


# ── Ingestion ────────────────────────────────────────────────────────────

async def _discover_csv_url() -> str:
    """Resolve the current REPD CSV URL.

    Strategy — try each known quarterly asset URL with a HEAD; return the
    first that returns 200. If none respond, fall back to scraping the
    publications page for a CSV href, then to REPD_CSV_URL as a last resort.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for candidate in REPD_CSV_URL_FALLBACK_LADDER:
            try:
                r = await client.head(candidate)
                if r.status_code == 200:
                    log.info("REPD URL resolved via ladder: %s", candidate)
                    return candidate
            except Exception as exc:
                log.debug("REPD ladder candidate %s unreachable: %s", candidate, exc)
        try:
            r = await client.get(REPD_PUBLICATIONS_URL)
            r.raise_for_status()
            match = re.search(
                r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"',
                r.text,
            )
            if match:
                url = match.group(1)
                log.info("REPD URL resolved via publications scrape: %s", url)
                return url
        except Exception as e:
            log.warning("REPD URL discovery scrape failed: %s", e)
    log.warning("REPD URL discovery exhausted — using static default %s", REPD_CSV_URL)
    return REPD_CSV_URL


async def ingest_repd(conn_or_pool) -> dict:
    """Download REPD CSV and upsert into repd_projects table."""
    t0 = time.time()

    # Resolve connection
    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        csv_url = await _discover_csv_url()
        log.info("Ingesting REPD from %s", csv_url)

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(csv_url)
            r.raise_for_status()

        text = r.text
        reader = csv.DictReader(io.StringIO(text))

        inserted = 0
        updated = 0
        skipped = 0

        for row in reader:
            repd_id = row.get("Ref ID", "").strip()
            if not repd_id:
                skipped += 1
                continue

            technology = row.get("Technology Type", "")
            tech_category = _classify_tech(technology)
            status = _normalise_status(row.get("Development Status"))
            capacity_mw = _parse_float(row.get("Installed Capacity (MWelec)"))

            # OS grid ref (easting/northing in EPSG:27700)
            x = _parse_float(row.get("X-coordinate"))
            y = _parse_float(row.get("Y-coordinate"))
            geom_expr = (
                f"ST_SetSRID(ST_MakePoint({x}, {y}), 27700)"
                if x is not None and y is not None
                else "NULL"
            )

            await conn.execute(f"""
                INSERT INTO repd_projects (
                    repd_id, site_name, technology, tech_category, capacity_mw, status,
                    developer, operator, planning_authority, planning_ref,
                    address, county, region, country, postcode,
                    mounting_type, height_m, turbines, battery_mwh, co_located,
                    appeal_ref, date_submitted, date_decided, date_operational,
                    planning_url, geometry, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13, $14, $15,
                    $16, $17, $18, $19, $20,
                    $21, $22, $23, $24,
                    $25, {geom_expr}, NOW()
                )
                ON CONFLICT (repd_id) DO UPDATE SET
                    site_name = EXCLUDED.site_name,
                    technology = EXCLUDED.technology,
                    tech_category = EXCLUDED.tech_category,
                    capacity_mw = EXCLUDED.capacity_mw,
                    status = EXCLUDED.status,
                    developer = EXCLUDED.developer,
                    operator = EXCLUDED.operator,
                    date_operational = EXCLUDED.date_operational,
                    geometry = EXCLUDED.geometry,
                    updated_at = NOW()
            """,
                repd_id,
                row.get("Site Name", "").strip(),
                technology.strip(),
                tech_category,
                capacity_mw,
                status,
                row.get("Developer", "").strip() or None,
                row.get("Operator (or Applicant)", "").strip() or None,
                row.get("Planning Authority", "").strip() or None,
                row.get("Planning Application Reference", "").strip() or None,
                row.get("Address", "").strip() or None,
                row.get("County", "").strip() or None,
                row.get("Region", "").strip() or None,
                row.get("Country", "").strip() or None,
                row.get("Post Code", "").strip() or None,
                row.get("Mounting Type for Solar", "").strip() or None,
                _parse_float(row.get("Height of Turbines (m)")),
                _parse_int(row.get("No. of Turbines")),
                _parse_float(row.get("Battery Capacity (MWh)")),
                row.get("CHP Enabled", "").strip().lower() == "yes",
                row.get("Appeal Reference", "").strip() or None,
                _parse_date(row.get("Planning Application Submitted")),
                _parse_date(row.get("Planning Permission Granted")),
                _parse_date(row.get("Operational")),
                row.get("Planning Application Website", "").strip() or None,
            )
            inserted += 1

        elapsed = round(time.time() - t0, 1)
        log.info("REPD ingestion complete: %d rows in %.1fs", inserted, elapsed)
        return {"inserted": inserted, "updated": updated, "skipped": skipped, "elapsed_s": elapsed}

    except Exception as e:
        log.error("REPD ingestion failed: %s", e)
        return {"error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Query ────────────────────────────────────────────────────────────────

async def query_repd(
    conn: asyncpg.Connection,
    *,
    tech_category: str | None = None,
    status: str | None = None,
    developer: str | None = None,
    region: str | None = None,
    min_capacity_mw: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    page: int = 1,
    limit: int = 50,
) -> list[dict]:
    """Query REPD projects with filters and optional spatial search."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if tech_category:
        conditions.append(f"tech_category = ${idx}")
        params.append(tech_category)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if developer:
        conditions.append(f"developer ILIKE ${idx}")
        params.append(f"%{developer}%")
        idx += 1
    if region:
        conditions.append(f"region ILIKE ${idx}")
        params.append(f"%{region}%")
        idx += 1
    if min_capacity_mw is not None:
        conditions.append(f"capacity_mw >= ${idx}")
        params.append(min_capacity_mw)
        idx += 1
    if lat is not None and lon is not None:
        conditions.append(
            f"ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint(${idx}, ${idx+1}), 4326), 27700), ${idx+2})"
        )
        params.extend([lon, lat, radius_km * 1000])
        idx += 3

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * limit

    rows = await conn.fetch(f"""
        SELECT repd_id, site_name, technology, tech_category, capacity_mw, status,
               developer, region, county, date_submitted, date_decided, date_operational,
               planning_authority, planning_ref,
               ST_X(ST_Transform(geometry, 4326)) AS lon,
               ST_Y(ST_Transform(geometry, 4326)) AS lat
        FROM repd_projects
        {where}
        ORDER BY capacity_mw DESC NULLS LAST
        LIMIT {limit} OFFSET {offset}
    """, *params)

    return [dict(r) for r in rows]


async def repd_summary(conn: asyncpg.Connection) -> dict:
    """Aggregate REPD projects by tech, status, region."""
    by_tech = await conn.fetch("""
        SELECT tech_category, count(*) AS cnt, coalesce(sum(capacity_mw), 0) AS total_mw
        FROM repd_projects GROUP BY tech_category ORDER BY total_mw DESC
    """)
    by_status = await conn.fetch("""
        SELECT status, count(*) AS cnt, coalesce(sum(capacity_mw), 0) AS total_mw
        FROM repd_projects GROUP BY status ORDER BY cnt DESC
    """)
    by_region = await conn.fetch("""
        SELECT region, count(*) AS cnt, coalesce(sum(capacity_mw), 0) AS total_mw
        FROM repd_projects GROUP BY region ORDER BY total_mw DESC
    """)
    total = await conn.fetchval("SELECT count(*) FROM repd_projects")
    total_mw = await conn.fetchval("SELECT coalesce(sum(capacity_mw), 0) FROM repd_projects")

    return {
        "total_projects": total,
        "total_mw": round(float(total_mw), 1),
        "by_technology": [dict(r) for r in by_tech],
        "by_status": [dict(r) for r in by_status],
        "by_region": [dict(r) for r in by_region],
    }


async def repd_geojson(
    conn: asyncpg.Connection,
    tech_category: str | None = None,
    status: str | None = None,
) -> dict:
    """Return REPD projects as GeoJSON FeatureCollection."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if tech_category:
        conditions.append(f"tech_category = ${idx}")
        params.append(tech_category)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    conditions.append("geometry IS NOT NULL")
    where = "WHERE " + " AND ".join(conditions)

    rows = await conn.fetch(f"""
        SELECT repd_id, site_name, technology, tech_category, capacity_mw, status, developer,
               ST_X(ST_Transform(geometry, 4326)) AS lon,
               ST_Y(ST_Transform(geometry, 4326)) AS lat
        FROM repd_projects
        {where}
        LIMIT 5000
    """, *params)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "repd_id": r["repd_id"],
                "site_name": r["site_name"],
                "technology": r["technology"],
                "tech_category": r["tech_category"],
                "capacity_mw": r["capacity_mw"],
                "status": r["status"],
                "developer": r["developer"],
            },
        })

    return {"type": "FeatureCollection", "features": features}
