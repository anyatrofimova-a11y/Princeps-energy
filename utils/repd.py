"""
REPD (Renewable Energy Planning Database) — download the UK government's
quarterly CSV of all renewable energy projects >150 kW, store in PostGIS
with BNG→WGS84 coordinate transform, and provide GeoJSON + summary endpoints.

Creates 1 PostGIS table (SRID 4326) and provides pipeline analysis
functions for the frontend dashboard and map layers.
"""
import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("princeps.repd")

# ---------------------------------------------------------------------------
# Data source configuration
# ---------------------------------------------------------------------------
REPD_CSV_URL = "https://assets.publishing.service.gov.uk/media/6985c316d3f57710b50a9b1f/REPD_Publication_Q4_2025.csv"

DATA_DIR = Path(os.path.dirname(__file__), "..", "data", "repd").resolve()


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------
async def setup_tables(conn):
    """Create REPD table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS repd_project (
            ref_id TEXT PRIMARY KEY,
            operator TEXT,
            site_name TEXT,
            technology_type TEXT,
            installed_capacity_mw REAL,
            dev_status TEXT,
            dev_status_short TEXT,
            region TEXT,
            county TEXT,
            country TEXT,
            planning_authority TEXT,
            mounting_type TEXT,
            num_turbines INTEGER,
            turbine_capacity_mw REAL,
            height_m REAL,
            planning_submitted DATE,
            planning_granted DATE,
            under_construction DATE,
            operational DATE,
            x_bng REAL,
            y_bng REAL,
            geometry GEOMETRY(Point, 4326),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_repd_geom ON repd_project USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_repd_tech ON repd_project (technology_type);
        CREATE INDEX IF NOT EXISTS idx_repd_status ON repd_project (dev_status_short);
        CREATE INDEX IF NOT EXISTS idx_repd_region ON repd_project (region);
    """)
    log.info("REPD tables ready")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
async def download_repd() -> str | None:
    """Download REPD CSV, cache locally. Returns CSV text or None."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "repd_latest.csv"

    # Use cache if fresh (< 30 days — REPD is quarterly)
    if cache_path.exists():
        import time
        age_d = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_d < 30:
            log.info("Using cached REPD (%d days old)", int(age_d))
            return cache_path.read_text(encoding="utf-8-sig")

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(REPD_CSV_URL)
            resp.raise_for_status()
            text = resp.text
            cache_path.write_text(text, encoding="utf-8")
            log.info("REPD downloaded: %d bytes", len(text))
            return text
    except Exception as e:
        log.error("REPD download failed: %s", e)
        # Try cache even if stale
        if cache_path.exists():
            log.info("Using stale REPD cache")
            return cache_path.read_text(encoding="utf-8-sig")
        return None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------
def _safe_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _safe_date(v):
    """Parse date string, return datetime.date or None."""
    if not v or v.strip() == "":
        return None
    v = v.strip()
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _status_short(status: str | None) -> str | None:
    """Map verbose REPD status to short category."""
    if not status:
        return None
    s = status.lower()
    if "operational" in s:
        return "Operational"
    if "under construction" in s:
        return "Under Construction"
    if "approved" in s or "granted" in s or "awaiting" in s:
        return "Approved"
    if "submitted" in s or "application" in s:
        return "Submitted"
    if "refused" in s or "rejected" in s:
        return "Refused"
    if "withdrawn" in s or "abandoned" in s:
        return "Withdrawn"
    if "appeal" in s:
        return "Appeal"
    if "decommissioned" in s:
        return "Decommissioned"
    return status


def parse_repd_csv(text: str) -> list[dict]:
    """Parse REPD CSV text into normalised records."""
    reader = csv.DictReader(io.StringIO(text))
    records = []

    for row in reader:
        r = {k.strip(): v.strip() if v else "" for k, v in row.items()}

        def g(*keys):
            for k in keys:
                if k in r and r[k]:
                    return r[k]
            return None

        ref = g("Ref ID", "Old Ref ID", "ref_id")
        if not ref:
            continue

        x = _safe_float(g("X-coordinate", "x_bng"))
        y = _safe_float(g("Y-coordinate", "y_bng"))
        status = g("Development Status", "dev_status")

        records.append({
            "ref_id": ref,
            "operator": g("Operator (or Applicant)", "operator"),
            "site_name": g("Site Name", "site_name"),
            "technology_type": g("Technology Type", "technology_type"),
            "installed_capacity_mw": _safe_float(g("Installed Capacity (MWelec)", "installed_capacity_mw")),
            "dev_status": status,
            "dev_status_short": _status_short(status),
            "region": g("Region", "region"),
            "county": g("County", "county"),
            "country": g("Country", "country"),
            "planning_authority": g("Planning Authority", "planning_authority"),
            "mounting_type": g("Mounting Type for Solar", "mounting_type"),
            "num_turbines": _safe_int(g("No. of Turbines", "num_turbines")),
            "turbine_capacity_mw": _safe_float(g("Turbine Capacity (MW)", "turbine_capacity_mw")),
            "height_m": _safe_float(g("Height of Turbines (m)", "height_m")),
            "planning_submitted": _safe_date(g("Planning Application Submitted", "planning_submitted")),
            "planning_granted": _safe_date(g("Planning Permission Granted", "Planning Permission  Granted", "planning_granted")),
            "under_construction": _safe_date(g("Under Construction", "under_construction")),
            "operational": _safe_date(g("Operational", "operational")),
            "x_bng": x,
            "y_bng": y,
        })

    log.info("Parsed %d REPD records", len(records))
    return records


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
async def seed_repd_data(pool):
    """Background task: download REPD CSV and upsert into PostGIS."""
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM repd_project")
        if count > 0:
            log.info("REPD already seeded (%d projects) — skipping", count)
            return

    log.info("Seeding REPD...")
    text = await download_repd()
    if not text:
        log.warning("No REPD data downloaded — skipping seed")
        return

    records = parse_repd_csv(text)
    if not records:
        log.warning("No REPD records parsed — skipping seed")
        return

    async with pool.acquire() as conn:
        inserted = 0
        for rec in records:
            try:
                x, y = rec["x_bng"], rec["y_bng"]
                if x and y:
                    await conn.execute("""
                        INSERT INTO repd_project
                            (ref_id, operator, site_name, technology_type,
                             installed_capacity_mw, dev_status, dev_status_short,
                             region, county, country, planning_authority,
                             mounting_type, num_turbines, turbine_capacity_mw, height_m,
                             planning_submitted, planning_granted, under_construction, operational,
                             x_bng, y_bng, geometry)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                                $16,$17,$18,$19,$20,$21,
                                ST_Transform(ST_SetSRID(ST_MakePoint($22::double precision,$23::double precision), 27700), 4326))
                        ON CONFLICT (ref_id) DO UPDATE SET
                            dev_status = EXCLUDED.dev_status,
                            dev_status_short = EXCLUDED.dev_status_short,
                            installed_capacity_mw = EXCLUDED.installed_capacity_mw,
                            geometry = EXCLUDED.geometry
                    """,
                        rec["ref_id"], rec["operator"], rec["site_name"], rec["technology_type"],
                        rec["installed_capacity_mw"], rec["dev_status"], rec["dev_status_short"],
                        rec["region"], rec["county"], rec["country"], rec["planning_authority"],
                        rec["mounting_type"], rec["num_turbines"], rec["turbine_capacity_mw"], rec["height_m"],
                        rec["planning_submitted"], rec["planning_granted"],
                        rec["under_construction"], rec["operational"],
                        x, y, float(x), float(y),
                    )
                else:
                    await conn.execute("""
                        INSERT INTO repd_project
                            (ref_id, operator, site_name, technology_type,
                             installed_capacity_mw, dev_status, dev_status_short,
                             region, county, country, planning_authority,
                             mounting_type, num_turbines, turbine_capacity_mw, height_m,
                             planning_submitted, planning_granted, under_construction, operational)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                                $16,$17,$18,$19)
                        ON CONFLICT (ref_id) DO UPDATE SET
                            dev_status = EXCLUDED.dev_status,
                            dev_status_short = EXCLUDED.dev_status_short,
                            installed_capacity_mw = EXCLUDED.installed_capacity_mw
                    """,
                        rec["ref_id"], rec["operator"], rec["site_name"], rec["technology_type"],
                        rec["installed_capacity_mw"], rec["dev_status"], rec["dev_status_short"],
                        rec["region"], rec["county"], rec["country"], rec["planning_authority"],
                        rec["mounting_type"], rec["num_turbines"], rec["turbine_capacity_mw"], rec["height_m"],
                        rec["planning_submitted"], rec["planning_granted"],
                        rec["under_construction"], rec["operational"],
                    )
                inserted += 1
            except Exception as e:
                log.debug("REPD insert skip: %s — %s", rec.get("ref_id"), e)

        log.info("REPD seeded: %d records inserted/updated", inserted)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
async def repd_geojson(conn, west: float, south: float, east: float, north: float,
                       technology: str | None = None, status: str | None = None,
                       min_mw: float = 0) -> dict:
    """Return GeoJSON FeatureCollection of REPD projects within bbox."""
    conditions = ["geometry IS NOT NULL"]
    params: list[Any] = []
    idx = 1

    conditions.append(f"ST_Intersects(geometry, ST_MakeEnvelope(${idx},${idx+1},${idx+2},${idx+3}, 4326))")
    params.extend([west, south, east, north])
    idx += 4

    if technology:
        conditions.append(f"technology_type = ${idx}")
        params.append(technology)
        idx += 1
    if status:
        conditions.append(f"dev_status_short = ${idx}")
        params.append(status)
        idx += 1
    if min_mw > 0:
        conditions.append(f"COALESCE(installed_capacity_mw, 0) >= ${idx}")
        params.append(min_mw)
        idx += 1

    where = " AND ".join(conditions)
    rows = await conn.fetch(f"""
        SELECT ref_id, site_name, operator, technology_type,
               installed_capacity_mw, dev_status_short, region, county,
               mounting_type,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM repd_project
        WHERE {where}
        ORDER BY installed_capacity_mw DESC NULLS LAST
        LIMIT 3000
    """, *params)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "ref_id": r["ref_id"],
                "name": r["site_name"],
                "operator": r["operator"],
                "technology": r["technology_type"],
                "capacity_mw": r["installed_capacity_mw"],
                "status": r["dev_status_short"],
                "region": r["region"],
                "county": r["county"],
                "mounting": r["mounting_type"],
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def repd_summary(conn) -> dict:
    """Summary breakdown by technology, status, and region."""
    by_tech = await conn.fetch("""
        SELECT technology_type, count(*) AS n,
               COALESCE(SUM(COALESCE(installed_capacity_mw, 0)), 0) AS total_mw
        FROM repd_project GROUP BY technology_type ORDER BY total_mw DESC
    """)
    by_status = await conn.fetch("""
        SELECT dev_status_short, count(*) AS n,
               COALESCE(SUM(COALESCE(installed_capacity_mw, 0)), 0) AS total_mw
        FROM repd_project GROUP BY dev_status_short ORDER BY n DESC
    """)
    by_region = await conn.fetch("""
        SELECT region, count(*) AS n,
               COALESCE(SUM(COALESCE(installed_capacity_mw, 0)), 0) AS total_mw
        FROM repd_project WHERE region IS NOT NULL GROUP BY region ORDER BY total_mw DESC
    """)
    totals = await conn.fetchrow("""
        SELECT count(*) AS total_projects,
               COALESCE(SUM(COALESCE(installed_capacity_mw, 0)), 0) AS total_mw,
               count(*) FILTER (WHERE geometry IS NOT NULL) AS geo_located
        FROM repd_project
    """)

    return {
        "total_projects": totals["total_projects"],
        "total_mw": round(float(totals["total_mw"]), 1),
        "total_gw": round(float(totals["total_mw"]) / 1000, 2),
        "geo_located": totals["geo_located"],
        "by_technology": [
            {"technology": r["technology_type"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_tech
        ],
        "by_status": [
            {"status": r["dev_status_short"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_status
        ],
        "by_region": [
            {"region": r["region"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_region
        ],
    }


async def repd_project_detail(conn, ref_id: str) -> dict | None:
    """Single REPD project detail by ref_id."""
    row = await conn.fetchrow("""
        SELECT *, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM repd_project WHERE ref_id = $1
    """, ref_id)
    if not row:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------
async def pipeline_combined(conn) -> dict:
    """Merged TEC + REPD summary for the pipeline card."""
    # Import tec_summary here to avoid circular imports
    from utils.eso_tec import tec_summary

    tec = await tec_summary(conn)
    repd = await repd_summary(conn)

    # Merge technology breakdown
    tech_map: dict[str, dict] = {}
    for t in tec.get("by_plant_type", []):
        key = (t["plant_type"] or "Unknown").lower()
        tech_map[key] = {"label": t["plant_type"] or "Unknown", "tec_mw": t["total_mw"], "tec_n": t["count"], "repd_mw": 0, "repd_n": 0}
    for t in repd.get("by_technology", []):
        key = (t["technology"] or "Unknown").lower()
        if key in tech_map:
            tech_map[key]["repd_mw"] = t["total_mw"]
            tech_map[key]["repd_n"] = t["count"]
        else:
            tech_map[key] = {"label": t["technology"] or "Unknown", "tec_mw": 0, "tec_n": 0, "repd_mw": t["total_mw"], "repd_n": t["count"]}

    combined_tech = sorted(tech_map.values(), key=lambda x: x["tec_mw"] + x["repd_mw"], reverse=True)

    return {
        "tec": {
            "total_projects": tec["total_projects"],
            "total_gw": tec["total_gw"],
            "geo_matched_pct": tec["match_pct"],
        },
        "repd": {
            "total_projects": repd["total_projects"],
            "total_gw": repd["total_gw"],
            "geo_located": repd["geo_located"],
        },
        "combined": {
            "total_projects": tec["total_projects"] + repd["total_projects"],
            "total_gw": round(tec["total_gw"] + repd["total_gw"], 2),
        },
        "by_technology": combined_tech,
        "tec_by_status": tec.get("by_status", []),
        "repd_by_status": repd.get("by_status", []),
    }
