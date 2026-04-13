"""
NGED Embedded Capacity Register ingester.

The ECR is the authoritative list of every contracted / connected / in-queue
generator in the NGED network — ~40-column CSV updated monthly.

We store it in a dedicated `nged_ecr` table (richer than the shared `grid_ecr`
table which is used by other DNOs), so the frontend can drill into queue
position, storage sizing, target energisation, and reinforcement references.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.nged_ecr")

NGED_CKAN_BASE = "https://connecteddata.nationalgrid.co.uk/api/3/action"
NGED_ECR_PACKAGE = "55621879-bd56-48d8-8179-36daa38ede99"


NGED_ECR_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nged_ecr (
    ecr_id                  BIGSERIAL PRIMARY KEY,
    reference               TEXT,
    export_mpan_msid        TEXT,
    import_mpan_msid        TEXT,
    customer_name           TEXT,
    customer_site           TEXT,
    town                    TEXT,
    county                  TEXT,
    postcode                TEXT,
    licence_area            TEXT,
    grid_supply_point       TEXT,
    bulk_supply_point       TEXT,
    primary_substation      TEXT,
    poc_voltage_kv          NUMERIC,
    energy_source_1         TEXT,
    conversion_tech_1       TEXT,
    reg_capacity_1_mw       NUMERIC,
    storage_capacity_mwh    NUMERIC,
    storage_duration_hours  NUMERIC,
    flexible_connection     TEXT,
    connection_status       TEXT,
    connected_reg_capacity_mw NUMERIC,
    connected_max_export_mw NUMERIC,
    connected_max_import_mw NUMERIC,
    date_connected          DATE,
    accepted_reg_capacity_mw NUMERIC,
    date_accepted           DATE,
    target_energisation_date DATE,
    in_queue                TEXT,
    distribution_reinforcement_ref TEXT,
    transmission_reinforcement_ref TEXT,
    last_updated            DATE,
    lat                     DOUBLE PRECISION,
    lon                     DOUBLE PRECISION,
    local_authority         TEXT,
    geom                    GEOMETRY(Point, 4326),
    raw                     JSONB,
    ingested_at             TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nged_ecr_status      ON nged_ecr (connection_status);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_tech        ON nged_ecr (energy_source_1);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_gsp         ON nged_ecr (grid_supply_point);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_primary     ON nged_ecr (primary_substation);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_licence     ON nged_ecr (licence_area);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_geom        ON nged_ecr USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_capacity    ON nged_ecr (connected_reg_capacity_mw DESC);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Ensure the nged_ecr table exists."""
    async with pool.acquire() as conn:
        for stmt in NGED_ECR_SCHEMA_SQL.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("nged_ecr schema ready")


# ────────────────────────────────────────────────────────────────────────
# Discover latest CSV URL
# ────────────────────────────────────────────────────────────────────────

async def discover_latest_csv_url() -> str | None:
    """Ask CKAN for the most recent NGED ECR CSV URL."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{NGED_CKAN_BASE}/package_show", params={"id": NGED_ECR_PACKAGE})
            r.raise_for_status()
            pkg = r.json().get("result", {})
        csvs = [res for res in pkg.get("resources", []) if (res.get("format") or "").upper() == "CSV"]
        if not csvs:
            return None
        # Pick the most recently modified
        csvs.sort(key=lambda r: r.get("last_modified") or "", reverse=True)
        for r in csvs:
            url = r.get("url")
            if url and "redacted" not in url:
                return url
    except Exception as e:
        log.warning("discover_latest_csv_url failed: %s", e)
    return None


# ────────────────────────────────────────────────────────────────────────
# Ingest
# ────────────────────────────────────────────────────────────────────────

_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")


def _parse_date(v: Any) -> datetime | None:
    """Parse a variety of UK date formats; return None on failure."""
    if v is None or v == "" or v in ("data not available", "data not applicable"):
        return None
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _num(v: Any) -> float | None:
    """Coerce to float or return None."""
    if v is None or v == "" or v in ("data not available", "data not applicable"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


async def ingest_ecr(pool: asyncpg.Pool, url: str | None = None, limit: int | None = None) -> dict:
    """Download, parse and persist the NGED ECR CSV. Returns ingest summary."""
    if url is None:
        url = await discover_latest_csv_url()
    if not url:
        return {"ok": False, "reason": "no_url_found"}

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            body = r.text
    except Exception as e:
        return {"ok": False, "reason": f"fetch_failed: {e}"}

    reader = csv.DictReader(io.StringIO(body))
    rows = list(reader)
    if limit:
        rows = rows[:limit]

    async with pool.acquire() as conn:
        # Clear previous month's snapshot on re-ingest (ECR is a full snapshot each month)
        await conn.execute("TRUNCATE nged_ecr RESTART IDENTITY")

        batch = []
        inserted = 0
        for r in rows:
            lat = _num(r.get("lat"))
            lon = _num(r.get("lon"))
            batch.append((
                (r.get("reference") or "").strip() or None,
                (r.get("export_mpan/msid") or "").strip() or None,
                (r.get("import_mpan/msid") or "").strip() or None,
                (r.get("customer_name") or "").strip() or None,
                (r.get("customer_site") or "").strip() or None,
                (r.get("Town/City") or "").strip() or None,
                (r.get("county") or "").strip() or None,
                (r.get("postcode") or "").strip() or None,
                (r.get("licence_area") or "").strip() or None,
                (r.get("grid_supply_point") or "").strip() or None,
                (r.get("bulk_supply_point") or "").strip() or None,
                (r.get("primary") or "").strip() or None,
                _num(r.get("point_of_connection(poc)_voltage(kv)")),
                (r.get("energy_source_1") or "").strip() or None,
                (r.get("Energy Conversion Technology 1") or "").strip() or None,
                _num(r.get("energy_source_&_conversion_tech_1_reg_capacity_mw")),
                _num(r.get("storage_capacity_1(mwh)")),
                _num(r.get("storage_duration_1(hours)")),
                (r.get("flexible_connection (Yes/No)") or "").strip() or None,
                (r.get("connection_status") or "").strip() or None,
                _num(r.get("already_connected_registered_capacity(mw)")),
                _num(r.get("connected_maximum_export_capacity(mw)")),
                _num(r.get("connected_maximum_import_capacity(mw)")),
                _parse_date(r.get("date_connected")),
                _num(r.get("accepted_to_connect_registered_capacity(mw)")),
                _parse_date(r.get("date_accepted")),
                _parse_date(r.get("target_energisation_date")),
                (r.get("in_a_connection_queue(y/n)") or "").strip() or None,
                (r.get("distribution_reinforcement_reference") or "").strip() or None,
                (r.get("transmission_reinforcement_reference") or "").strip() or None,
                _parse_date(r.get("last_updated")),
                lat, lon,
                (r.get("local_authority") or "").strip() or None,
            ))
            if len(batch) >= 500:
                inserted += await _insert_batch(conn, batch)
                batch = []
        if batch:
            inserted += await _insert_batch(conn, batch)

        # Populate PostGIS geometry from lat/lon
        await conn.execute(
            "UPDATE nged_ecr SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL AND geom IS NULL"
        )

        # Aggregate quick stats
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE connection_status = 'Connected') AS connected,
                COUNT(*) FILTER (WHERE in_queue ILIKE 'y%') AS in_queue,
                COALESCE(SUM(connected_reg_capacity_mw), 0) AS total_connected_mw,
                COALESCE(SUM(accepted_reg_capacity_mw), 0) AS total_accepted_mw
            FROM nged_ecr
            """
        )

    return {
        "ok": True,
        "url": url,
        "rows_inserted": inserted,
        "stats": dict(stats) if stats else {},
    }


async def _insert_batch(conn: asyncpg.Connection, batch: list[tuple]) -> int:
    """Insert one batch of ECR rows."""
    await conn.executemany(
        """
        INSERT INTO nged_ecr (
            reference, export_mpan_msid, import_mpan_msid,
            customer_name, customer_site, town, county, postcode, licence_area,
            grid_supply_point, bulk_supply_point, primary_substation, poc_voltage_kv,
            energy_source_1, conversion_tech_1, reg_capacity_1_mw,
            storage_capacity_mwh, storage_duration_hours, flexible_connection,
            connection_status, connected_reg_capacity_mw, connected_max_export_mw,
            connected_max_import_mw, date_connected, accepted_reg_capacity_mw,
            date_accepted, target_energisation_date, in_queue,
            distribution_reinforcement_ref, transmission_reinforcement_ref,
            last_updated, lat, lon, local_authority
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9,
            $10, $11, $12, $13, $14, $15, $16, $17, $18, $19,
            $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31, $32, $33, $34
        )
        """,
        batch,
    )
    return len(batch)


# ────────────────────────────────────────────────────────────────────────
# Read side
# ────────────────────────────────────────────────────────────────────────

async def get_ecr_geojson(
    pool: asyncpg.Pool,
    status: str | None = None,
    technology: str | None = None,
    min_mw: float | None = None,
    licence_area: str | None = None,
    limit: int = 10000,
) -> dict:
    """Return ECR records as a GeoJSON FeatureCollection."""
    conditions = ["lat IS NOT NULL", "lon IS NOT NULL"]
    params: list[Any] = []
    idx = 1
    if status:
        conditions.append(f"connection_status = ${idx}"); params.append(status); idx += 1
    if technology:
        conditions.append(f"energy_source_1 ILIKE ${idx}"); params.append(f"%{technology}%"); idx += 1
    if min_mw is not None:
        conditions.append(f"COALESCE(connected_reg_capacity_mw, accepted_reg_capacity_mw, 0) >= ${idx}")
        params.append(min_mw); idx += 1
    if licence_area:
        conditions.append(f"licence_area ILIKE ${idx}"); params.append(f"%{licence_area}%"); idx += 1

    sql = f"""
        SELECT customer_name, customer_site, town, county, licence_area,
               grid_supply_point, primary_substation, poc_voltage_kv,
               energy_source_1, conversion_tech_1, reg_capacity_1_mw,
               connection_status, connected_reg_capacity_mw, accepted_reg_capacity_mw,
               date_connected, target_energisation_date, in_queue, lat, lon
        FROM nged_ecr
        WHERE {" AND ".join(conditions)}
        ORDER BY COALESCE(connected_reg_capacity_mw, accepted_reg_capacity_mw, 0) DESC NULLS LAST
        LIMIT ${idx}
    """
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        capacity = float(r["connected_reg_capacity_mw"] or r["accepted_reg_capacity_mw"] or 0)
        status_val = r["connection_status"] or ""
        colour = _status_colour(status_val)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "customer": r["customer_name"],
                "site": r["customer_site"],
                "town": r["town"],
                "licence_area": r["licence_area"],
                "gsp": r["grid_supply_point"],
                "primary": r["primary_substation"],
                "voltage_kv": float(r["poc_voltage_kv"]) if r["poc_voltage_kv"] else None,
                "technology": r["energy_source_1"],
                "conversion": r["conversion_tech_1"],
                "capacity_mw": capacity,
                "status": status_val,
                "in_queue": r["in_queue"],
                "date_connected": str(r["date_connected"]) if r["date_connected"] else None,
                "target_energisation": str(r["target_energisation_date"]) if r["target_energisation_date"] else None,
                "colour": colour,
                "radius": 3 + min(20, capacity / 2),
            },
        })

    return {
        "type": "FeatureCollection",
        "count": len(features),
        "status_legend": {
            "Connected":  "#2e7d32",
            "Accepted":   "#1976d2",
            "Applied":    "#f57c00",
            "Offered":    "#fbc02d",
            "Queued":     "#9c27b0",
            "Withdrawn":  "#9e9e9e",
        },
        "features": features,
    }


def _status_colour(status: str) -> str:
    """Colour map for ECR connection status."""
    s = (status or "").lower()
    if "connected" in s:   return "#2e7d32"
    if "accept" in s:      return "#1976d2"
    if "applied" in s:     return "#f57c00"
    if "offered" in s:     return "#fbc02d"
    if "queue" in s:       return "#9c27b0"
    if "withdraw" in s:    return "#9e9e9e"
    return "#607d8b"


async def get_ecr_stats(pool: asyncpg.Pool) -> dict:
    """Aggregate ECR stats."""
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM nged_ecr") or 0
        connected = await conn.fetchval("SELECT COUNT(*) FROM nged_ecr WHERE connection_status = 'Connected'") or 0
        in_queue = await conn.fetchval("SELECT COUNT(*) FROM nged_ecr WHERE in_queue ILIKE 'y%'") or 0
        total_mw = await conn.fetchval("SELECT COALESCE(SUM(connected_reg_capacity_mw), 0) FROM nged_ecr") or 0
        by_tech = await conn.fetch(
            """
            SELECT energy_source_1 AS tech, COUNT(*)::int AS n,
                   COALESCE(SUM(connected_reg_capacity_mw), 0)::float AS total_mw
            FROM nged_ecr
            WHERE energy_source_1 IS NOT NULL
            GROUP BY energy_source_1
            ORDER BY total_mw DESC NULLS LAST
            LIMIT 20
            """
        )
    return {
        "total_records": int(total),
        "connected": int(connected),
        "in_queue": int(in_queue),
        "total_connected_mw": float(total_mw),
        "by_technology": [dict(r) for r in by_tech],
    }
