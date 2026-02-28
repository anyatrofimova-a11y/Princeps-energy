"""
ESO TEC Register — download Transmission Entry Capacity data from the
NESO CKAN API, geo-locate connection sites via fuzzy matching against
OSM/NGED substations, and provide GeoJSON + summary endpoints.

Creates 1 PostGIS table (SRID 4326) and provides pipeline analysis
functions for the frontend dashboard and map layers.
"""
import csv
import difflib
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("princeps.eso_tec")

# ---------------------------------------------------------------------------
# Data source configuration
# ---------------------------------------------------------------------------
CKAN_BASE = "https://api.neso.energy/api/3/action/datastore_search"
RESOURCE_ID = "17becbab-e3e8-473f-b303-3806f43a6a10"
CSV_FALLBACK = "https://api.neso.energy/dataset/6e4ab15b-9ccf-49f7-84dd-2a84450e4a76/resource/17becbab-e3e8-473f-b303-3806f43a6a10/download/tec-register.csv"

DATA_DIR = Path(os.path.dirname(__file__), "..", "data", "eso_tec").resolve()

MATCH_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------
async def setup_tables(conn):
    """Create ESO TEC table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS eso_tec_project (
            id SERIAL PRIMARY KEY,
            project_name TEXT NOT NULL,
            customer_name TEXT,
            connection_site TEXT,
            mw_connected REAL,
            cumulative_capacity_mw REAL,
            plant_type TEXT,
            project_status TEXT,
            host_to TEXT,
            gate TEXT,
            agreement_type TEXT,
            project_id TEXT,
            mw_effective_from DATE,
            matched_substation_name TEXT,
            match_source TEXT,
            match_score REAL,
            geometry GEOMETRY(Point, 4326),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (project_name, connection_site, mw_effective_from)
        );
        CREATE INDEX IF NOT EXISTS idx_eso_tec_geom ON eso_tec_project USING GIST (geometry);
        CREATE INDEX IF NOT EXISTS idx_eso_tec_plant ON eso_tec_project (plant_type);
        CREATE INDEX IF NOT EXISTS idx_eso_tec_status ON eso_tec_project (project_status);
        CREATE INDEX IF NOT EXISTS idx_eso_tec_host ON eso_tec_project (host_to);
    """)
    log.info("ESO TEC tables ready")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
async def download_tec_register() -> list[dict]:
    """Download TEC register via CKAN API with pagination, fallback to CSV."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = DATA_DIR / "tec_register.json"

    # Use cache if fresh (< 3 days)
    if cache_path.exists():
        import time
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < 72:
            log.info("Using cached TEC register (%d hours old)", int(age_h))
            return json.loads(cache_path.read_text())

    records = []
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            offset = 0
            page_size = 1000
            while True:
                url = f"{CKAN_BASE}?resource_id={RESOURCE_ID}&limit={page_size}&offset={offset}"
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("result", {}).get("records", [])
                if not batch:
                    break
                records.extend(batch)
                offset += page_size
                total = data.get("result", {}).get("total", 0)
                log.info("TEC CKAN: fetched %d / %d records", len(records), total)
                if len(records) >= total:
                    break
    except Exception as e:
        log.warning("CKAN API failed (%s), trying CSV fallback", e)
        records = await _download_csv_fallback()

    if records:
        cache_path.write_text(json.dumps(records, default=str))
        log.info("TEC register cached: %d records", len(records))

    return records


async def _download_csv_fallback() -> list[dict]:
    """Fallback: download TEC register as CSV."""
    records = []
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(CSV_FALLBACK)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                records.append(dict(row))
        log.info("TEC CSV fallback: %d records", len(records))
    except Exception as e:
        log.error("TEC CSV fallback also failed: %s", e)
    return records


# ---------------------------------------------------------------------------
# Field normalisation
# ---------------------------------------------------------------------------
def _normalise_record(raw: dict) -> dict:
    """Normalise CKAN field names to our schema."""
    # CKAN fields can have varied casing — normalise
    r = {k.strip(): v for k, v in raw.items()}
    def g(*keys):
        for k in keys:
            if k in r and r[k] is not None and str(r[k]).strip():
                return str(r[k]).strip()
        return None

    mw_conn = g("MW Connected", "mw_connected", "MW_Connected")
    cum_mw = g("Cumulative MW", "cumulative_capacity_mw", "Cumulative_MW", "Cumulative Capacity (MW)")
    eff_from = g("MW Effective From", "mw_effective_from", "MW_Effective_From")

    return {
        "project_name": g("Project Name", "project_name", "Project_Name") or "Unknown",
        "customer_name": g("Customer Name", "customer_name", "Customer_Name"),
        "connection_site": g("Connection Site", "connection_site", "Connection_Site"),
        "mw_connected": _safe_float(mw_conn),
        "cumulative_capacity_mw": _safe_float(cum_mw),
        "plant_type": g("Plant Type", "plant_type", "Plant_Type"),
        "project_status": g("Project Status", "project_status", "Project_Status"),
        "host_to": g("Host TO", "host_to", "Host_TO"),
        "gate": g("Gate", "gate"),
        "agreement_type": g("Agreement Type", "agreement_type", "Agreement_Type"),
        "project_id": g("TEC Project ID", "project_id", "TEC_Project_ID"),
        "mw_effective_from": _safe_date(eff_from),
    }


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_date(v):
    """Parse date string, return datetime.date or None."""
    if v is None or str(v).strip() in ("", "None"):
        return None
    from datetime import datetime
    v = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Geo-matching
# ---------------------------------------------------------------------------
def _normalise_substation_name(name: str) -> str:
    """Normalise a connection site / substation name for fuzzy matching."""
    import re
    s = name.lower().strip()
    # Remove voltage suffixes (400kV, 275kV, 132kV, etc.)
    s = re.sub(r'\d+\s*kv', '', s)
    # Remove common suffixes
    for suffix in ("substation", "gsp", "bsp", "grid", "tee", "gis",
                   "400", "275", "132", "node"):
        s = s.replace(suffix, "")
    # Remove parenthetical content
    s = re.sub(r'\([^)]*\)', '', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


async def geo_match_connection_sites(conn, records: list[dict]) -> list[dict]:
    """Fuzzy-match connection sites against OSM + NGED substations."""
    # Build lookup of known substations with coordinates
    osm_subs = await conn.fetch("""
        SELECT name, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM osm_power_substation
        WHERE geometry IS NOT NULL AND name IS NOT NULL
    """)
    nged_subs = await conn.fetch("""
        SELECT name, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM nged_substation
        WHERE geometry IS NOT NULL AND name IS NOT NULL
    """)

    # Build name -> (lon, lat, source) lookup with normalised keys
    lookup = {}
    for row in osm_subs:
        norm = _normalise_substation_name(row["name"])
        if norm:
            lookup[norm] = (float(row["lon"]), float(row["lat"]), "osm", row["name"])
    for row in nged_subs:
        norm = _normalise_substation_name(row["name"])
        if norm and norm not in lookup:
            lookup[norm] = (float(row["lon"]), float(row["lat"]), "nged", row["name"])

    names_list = list(lookup.keys())
    matched = 0

    for rec in records:
        site = rec.get("connection_site")
        if not site:
            continue
        norm = _normalise_substation_name(site)
        if not norm:
            continue
        matches = difflib.get_close_matches(norm, names_list, n=1, cutoff=MATCH_THRESHOLD)
        if matches:
            best = matches[0]
            lon, lat, source, orig_name = lookup[best]
            score = difflib.SequenceMatcher(None, norm, best).ratio()
            rec["matched_substation_name"] = orig_name
            rec["match_source"] = source
            rec["match_score"] = round(score, 3)
            rec["lon"] = lon
            rec["lat"] = lat
            matched += 1

    log.info("TEC geo-match: %d / %d connection sites matched (%.0f%%)",
             matched, len(records), 100 * matched / max(len(records), 1))
    return records


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
async def seed_tec_data(pool):
    """Background task: download TEC register and upsert into PostGIS."""
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM eso_tec_project")
        if count > 0:
            log.info("ESO TEC already seeded (%d projects) — skipping", count)
            return

    log.info("Seeding ESO TEC register...")
    raw = await download_tec_register()
    if not raw:
        log.warning("No TEC records downloaded — skipping seed")
        return

    records = [_normalise_record(r) for r in raw]
    log.info("Parsed %d TEC records", len(records))

    async with pool.acquire() as conn:
        records = await geo_match_connection_sites(conn, records)

        inserted = 0
        for rec in records:
            try:
                if rec.get("lon") and rec.get("lat"):
                    await conn.execute("""
                        INSERT INTO eso_tec_project
                            (project_name, customer_name, connection_site,
                             mw_connected, cumulative_capacity_mw, plant_type,
                             project_status, host_to, gate, agreement_type,
                             project_id, mw_effective_from,
                             matched_substation_name, match_source, match_score,
                             geometry)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                                ST_SetSRID(ST_MakePoint($16,$17), 4326))
                        ON CONFLICT (project_name, connection_site, mw_effective_from) DO UPDATE SET
                            mw_connected = EXCLUDED.mw_connected,
                            cumulative_capacity_mw = EXCLUDED.cumulative_capacity_mw,
                            project_status = EXCLUDED.project_status,
                            matched_substation_name = EXCLUDED.matched_substation_name,
                            match_source = EXCLUDED.match_source,
                            match_score = EXCLUDED.match_score,
                            geometry = EXCLUDED.geometry
                    """,
                        rec["project_name"], rec["customer_name"], rec["connection_site"],
                        rec["mw_connected"], rec["cumulative_capacity_mw"], rec["plant_type"],
                        rec["project_status"], rec["host_to"], rec["gate"], rec["agreement_type"],
                        rec["project_id"], rec.get("mw_effective_from"),
                        rec.get("matched_substation_name"), rec.get("match_source"), rec.get("match_score"),
                        rec["lon"], rec["lat"],
                    )
                else:
                    await conn.execute("""
                        INSERT INTO eso_tec_project
                            (project_name, customer_name, connection_site,
                             mw_connected, cumulative_capacity_mw, plant_type,
                             project_status, host_to, gate, agreement_type,
                             project_id, mw_effective_from)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                        ON CONFLICT (project_name, connection_site, mw_effective_from) DO UPDATE SET
                            mw_connected = EXCLUDED.mw_connected,
                            cumulative_capacity_mw = EXCLUDED.cumulative_capacity_mw,
                            project_status = EXCLUDED.project_status
                    """,
                        rec["project_name"], rec["customer_name"], rec["connection_site"],
                        rec["mw_connected"], rec["cumulative_capacity_mw"], rec["plant_type"],
                        rec["project_status"], rec["host_to"], rec["gate"], rec["agreement_type"],
                        rec["project_id"], rec.get("mw_effective_from"),
                    )
                inserted += 1
            except Exception as e:
                log.debug("TEC insert skip: %s — %s", rec.get("project_name"), e)

        log.info("ESO TEC seeded: %d records inserted/updated", inserted)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
async def tec_geojson(conn, west: float, south: float, east: float, north: float,
                      plant_type: str | None = None, status: str | None = None) -> dict:
    """Return GeoJSON FeatureCollection of TEC projects within bbox."""
    conditions = ["geometry IS NOT NULL"]
    params: list[Any] = []
    idx = 1

    conditions.append(f"ST_Intersects(geometry, ST_MakeEnvelope(${idx},${idx+1},${idx+2},${idx+3}, 4326))")
    params.extend([west, south, east, north])
    idx += 4

    if plant_type:
        conditions.append(f"plant_type = ${idx}")
        params.append(plant_type)
        idx += 1
    if status:
        conditions.append(f"project_status = ${idx}")
        params.append(status)
        idx += 1

    where = " AND ".join(conditions)
    rows = await conn.fetch(f"""
        SELECT project_name, customer_name, connection_site,
               mw_connected, cumulative_capacity_mw, plant_type,
               project_status, host_to, gate, project_id,
               matched_substation_name, match_source, match_score,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM eso_tec_project
        WHERE {where}
        LIMIT 2000
    """, *params)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "name": r["project_name"],
                "customer": r["customer_name"],
                "connection_site": r["connection_site"],
                "capacity_mw": r["mw_connected"] or r["cumulative_capacity_mw"],
                "plant_type": r["plant_type"],
                "status": r["project_status"],
                "host_to": r["host_to"],
                "gate": r["gate"],
                "match_score": r["match_score"],
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def tec_summary(conn) -> dict:
    """Summary breakdown by plant type, status, and host TO."""
    by_type = await conn.fetch("""
        SELECT plant_type, count(*) AS n,
               COALESCE(SUM(COALESCE(mw_connected, cumulative_capacity_mw, 0)), 0) AS total_mw
        FROM eso_tec_project GROUP BY plant_type ORDER BY total_mw DESC
    """)
    by_status = await conn.fetch("""
        SELECT project_status, count(*) AS n,
               COALESCE(SUM(COALESCE(mw_connected, cumulative_capacity_mw, 0)), 0) AS total_mw
        FROM eso_tec_project GROUP BY project_status ORDER BY n DESC
    """)
    by_host = await conn.fetch("""
        SELECT host_to, count(*) AS n,
               COALESCE(SUM(COALESCE(mw_connected, cumulative_capacity_mw, 0)), 0) AS total_mw
        FROM eso_tec_project GROUP BY host_to ORDER BY total_mw DESC
    """)
    totals = await conn.fetchrow("""
        SELECT count(*) AS total_projects,
               COALESCE(SUM(COALESCE(mw_connected, cumulative_capacity_mw, 0)), 0) AS total_mw,
               count(*) FILTER (WHERE geometry IS NOT NULL) AS geo_matched
        FROM eso_tec_project
    """)

    return {
        "total_projects": totals["total_projects"],
        "total_mw": round(float(totals["total_mw"]), 1),
        "total_gw": round(float(totals["total_mw"]) / 1000, 2),
        "geo_matched": totals["geo_matched"],
        "match_pct": round(100 * totals["geo_matched"] / max(totals["total_projects"], 1), 1),
        "by_plant_type": [
            {"plant_type": r["plant_type"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_type
        ],
        "by_status": [
            {"status": r["project_status"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_status
        ],
        "by_host_to": [
            {"host_to": r["host_to"], "count": r["n"], "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_host
        ],
    }


async def tec_project_detail(conn, project_id: str) -> dict | None:
    """Single TEC project detail by project_id."""
    row = await conn.fetchrow("""
        SELECT *, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM eso_tec_project WHERE project_id = $1
        LIMIT 1
    """, project_id)
    if not row:
        return None
    return dict(row)
