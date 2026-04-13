"""
NGED Connected Data CKAN bulk ingester — Live GSP Data + ancillary datasets.

Discovers and ingests:
  * "Live GSP Data - East Midlands"   (~17 GSPs)
  * "Live GSP Data - West Midlands"   (~19 GSPs)
  * "Live GSP Data - South West"      (~12 GSPs)
  * "Live GSP Data - South Wales"     (~11 GSPs)

Each GSP CSV is 5-minute resolution with columns:
  Timestamp, Net Demand, Generation, Import, Solar, Wind, STOR, Other  (MW)

All rows land in `nged_gsp_timeseries`; the most recent row per GSP is mirrored
to `nged_gsp_latest` for fast GeoJSON reads from the frontend map layer.

Locations are joined from the existing `grid_substations` table (fuzzy name
match) so we don't need a separate coordinates dataset.

The ingester also pulls:
  * "Live Power Cuts"                — nged_powercuts
  * "GSP Technical Limits"           — nged_gsp_limits (used for headroom calc)
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.nged_gsp_data")

NGED_CKAN_BASE = "https://connecteddata.nationalgrid.co.uk/api/3/action"

GSP_PACKAGES = {
    "em": ("101d968c-3031-4900-a0a2-6d9f6485f92c", "East Midlands"),
    "wm": ("d5a803a8-7bc0-4d15-8ce0-de1724f4ba74", "West Midlands"),
    "sw": ("8be19ae9-d070-41d3-a01b-44dc5a89d891", "South West"),
    "wa": ("a4613210-c299-441f-85e5-c3788f62bbfa", "South Wales"),
}

POWERCUTS_PACKAGE = "d6672e1e-c684-4cea-bb78-c7e5248b62a2"
GSP_LIMITS_PACKAGE = "130e2e15-f3fb-4175-96f7-26c5e60de936"


# ────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────

NGED_GSP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nged_gsp_timeseries (
    ts_id          BIGSERIAL PRIMARY KEY,
    region         TEXT NOT NULL,          -- 'em'|'wm'|'sw'|'wa'
    gsp_name       TEXT NOT NULL,
    observed_at    TIMESTAMPTZ NOT NULL,
    net_demand_mw  NUMERIC,
    generation_mw  NUMERIC,
    import_mw      NUMERIC,
    solar_mw       NUMERIC,
    wind_mw        NUMERIC,
    storage_mw     NUMERIC,
    other_mw       NUMERIC,
    ingested_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (region, gsp_name, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_nged_gsp_ts_gsp_time
    ON nged_gsp_timeseries (region, gsp_name, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_nged_gsp_ts_time
    ON nged_gsp_timeseries (observed_at DESC);


-- Mirror of the latest row per GSP — used for fast GeoJSON rendering
CREATE TABLE IF NOT EXISTS nged_gsp_latest (
    region         TEXT NOT NULL,
    gsp_name       TEXT NOT NULL,
    observed_at    TIMESTAMPTZ,
    net_demand_mw  NUMERIC,
    generation_mw  NUMERIC,
    import_mw      NUMERIC,
    solar_mw       NUMERIC,
    wind_mw        NUMERIC,
    storage_mw     NUMERIC,
    other_mw       NUMERIC,
    gsp_capacity_mw NUMERIC,              -- from GSP Technical Limits
    lat            DOUBLE PRECISION,
    lon            DOUBLE PRECISION,
    substation_id  INTEGER,                -- FK-ish to grid_substations.id
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (region, gsp_name)
);


CREATE TABLE IF NOT EXISTS nged_gsp_limits (
    region         TEXT,
    gsp_name       TEXT,
    capacity_mw    NUMERIC,
    export_limit_mw NUMERIC,
    import_limit_mw NUMERIC,
    raw            JSONB,
    updated_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (region, gsp_name)
);


CREATE TABLE IF NOT EXISTS nged_powercuts (
    incident_id    TEXT PRIMARY KEY,
    title          TEXT,
    area           TEXT,
    latitude       DOUBLE PRECISION,
    longitude      DOUBLE PRECISION,
    customers_affected INTEGER,
    status         TEXT,
    reported_at    TIMESTAMPTZ,
    restored_at    TIMESTAMPTZ,
    raw            JSONB,
    ingested_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nged_powercuts_status ON nged_powercuts (status);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Ensure the NGED GSP ingester tables exist."""
    async with pool.acquire() as conn:
        for stmt in NGED_GSP_SCHEMA_SQL.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("nged_gsp_data schema ready")


# ────────────────────────────────────────────────────────────────────────
# CKAN discovery
# ────────────────────────────────────────────────────────────────────────

async def _ckan_package(client: httpx.AsyncClient, package_id: str) -> dict | None:
    """Fetch CKAN package metadata."""
    try:
        r = await client.get(f"{NGED_CKAN_BASE}/package_show", params={"id": package_id})
        r.raise_for_status()
        data = r.json()
        return data.get("result") if data.get("success") else None
    except Exception as e:
        log.warning("ckan package_show %s failed: %s", package_id, e)
        return None


def _parse_gsp_filename(url: str, resource_name: str) -> str:
    """Extract the GSP substation name from a CSV resource filename."""
    # URLs look like .../download/berkswell_emids.csv
    fname = url.rsplit("/", 1)[-1] if url else resource_name or ""
    fname = re.sub(r"\.csv$", "", fname, flags=re.IGNORECASE)
    fname = re.sub(r"_(emids|wmids|swest|swales|nged)$", "", fname, flags=re.IGNORECASE)
    fname = fname.replace("-", " ").replace("_", " ").strip().title()
    # Some names get double-titled — fix known patterns
    return re.sub(r"\s+", " ", fname)


# ────────────────────────────────────────────────────────────────────────
# CSV fetch + parse
# ────────────────────────────────────────────────────────────────────────

async def _download_csv(client: httpx.AsyncClient, url: str) -> str | None:
    """Download a CSV resource body as text."""
    try:
        r = await client.get(url, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning("csv fetch %s failed: %s", url, e)
        return None


def _parse_gsp_csv(body: str) -> list[dict]:
    """Parse a Live GSP CSV into a list of row dicts."""
    reader = csv.DictReader(io.StringIO(body))
    rows = []
    for r in reader:
        ts_raw = r.get("Timestamp") or r.get("timestamp") or r.get("Time")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        rows.append({
            "observed_at": ts,
            "net_demand_mw": _num(r.get("Net Demand") or r.get("net_demand")),
            "generation_mw": _num(r.get("Generation") or r.get("generation")),
            "import_mw":     _num(r.get("Import") or r.get("import")),
            "solar_mw":      _num(r.get("Solar") or r.get("solar")),
            "wind_mw":       _num(r.get("Wind") or r.get("wind")),
            "storage_mw":    _num(r.get("STOR") or r.get("stor") or r.get("Storage")),
            "other_mw":      _num(r.get("Other") or r.get("other")),
        })
    return rows


def _num(x: Any) -> float | None:
    """Coerce to float or None."""
    try:
        return float(x) if x not in (None, "", "NA", "N/A") else None
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────────
# Ingesters — GSP live data
# ────────────────────────────────────────────────────────────────────────

async def ingest_region(
    pool: asyncpg.Pool,
    region: str,
    max_rows_per_gsp: int = 2000,
    since_hours: int | None = None,
) -> dict:
    """Ingest every GSP CSV in a given region's Live GSP Data package."""
    if region not in GSP_PACKAGES:
        return {"ok": False, "reason": f"unknown region {region}"}
    package_id, region_name = GSP_PACKAGES[region]

    summary: dict[str, Any] = {
        "region": region,
        "region_name": region_name,
        "package_id": package_id,
        "gsps": 0,
        "rows_inserted": 0,
        "failed_gsps": [],
    }

    since_dt = None
    if since_hours:
        from datetime import timedelta
        since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    async with httpx.AsyncClient(timeout=60.0) as client:
        pkg = await _ckan_package(client, package_id)
        if not pkg:
            summary["ok"] = False
            summary["reason"] = "package_not_found"
            return summary

        for res in pkg.get("resources", []):
            if (res.get("format") or "").upper() != "CSV":
                continue
            url = res.get("url")
            if not url or "redacted" in url:
                continue
            gsp_name = _parse_gsp_filename(url, res.get("name", ""))
            body = await _download_csv(client, url)
            if body is None:
                summary["failed_gsps"].append(gsp_name)
                continue
            rows = _parse_gsp_csv(body)
            if since_dt:
                rows = [r for r in rows if r["observed_at"] >= since_dt]
            rows = rows[-max_rows_per_gsp:]  # keep most recent
            if not rows:
                continue

            # Bulk upsert
            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO nged_gsp_timeseries
                        (region, gsp_name, observed_at, net_demand_mw, generation_mw,
                         import_mw, solar_mw, wind_mw, storage_mw, other_mw)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (region, gsp_name, observed_at) DO UPDATE SET
                        net_demand_mw = EXCLUDED.net_demand_mw,
                        generation_mw = EXCLUDED.generation_mw,
                        import_mw = EXCLUDED.import_mw,
                        solar_mw = EXCLUDED.solar_mw,
                        wind_mw = EXCLUDED.wind_mw,
                        storage_mw = EXCLUDED.storage_mw,
                        other_mw = EXCLUDED.other_mw
                    """,
                    [(region, gsp_name, r["observed_at"], r["net_demand_mw"], r["generation_mw"],
                      r["import_mw"], r["solar_mw"], r["wind_mw"], r["storage_mw"], r["other_mw"]) for r in rows],
                )

                latest = rows[-1]
                await conn.execute(
                    """
                    INSERT INTO nged_gsp_latest
                        (region, gsp_name, observed_at, net_demand_mw, generation_mw,
                         import_mw, solar_mw, wind_mw, storage_mw, other_mw, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
                    ON CONFLICT (region, gsp_name) DO UPDATE SET
                        observed_at = EXCLUDED.observed_at,
                        net_demand_mw = EXCLUDED.net_demand_mw,
                        generation_mw = EXCLUDED.generation_mw,
                        import_mw = EXCLUDED.import_mw,
                        solar_mw = EXCLUDED.solar_mw,
                        wind_mw = EXCLUDED.wind_mw,
                        storage_mw = EXCLUDED.storage_mw,
                        other_mw = EXCLUDED.other_mw,
                        updated_at = now()
                    """,
                    region, gsp_name, latest["observed_at"],
                    latest["net_demand_mw"], latest["generation_mw"], latest["import_mw"],
                    latest["solar_mw"], latest["wind_mw"], latest["storage_mw"], latest["other_mw"],
                )

            summary["gsps"] += 1
            summary["rows_inserted"] += len(rows)

    summary["ok"] = True
    return summary


async def ingest_all_regions(pool: asyncpg.Pool, max_rows_per_gsp: int = 500) -> dict:
    """Run ingest_region for all four NGED licence areas."""
    out = {"ok": True, "regions": {}}
    for region in GSP_PACKAGES:
        try:
            out["regions"][region] = await ingest_region(pool, region, max_rows_per_gsp=max_rows_per_gsp)
        except Exception as e:
            log.exception("ingest_region %s failed", region)
            out["regions"][region] = {"ok": False, "reason": str(e)}
    return out


# ────────────────────────────────────────────────────────────────────────
# Location resolution — join to existing grid_substations
# ────────────────────────────────────────────────────────────────────────

async def resolve_locations(pool: asyncpg.Pool) -> int:
    """Match nged_gsp_latest rows to grid_substations by fuzzy name + voltage.

    Populates lat / lon / substation_id on matches so the GeoJSON endpoint has
    coordinates without an extra location dataset.
    """
    updated = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT region, gsp_name FROM nged_gsp_latest WHERE lat IS NULL"
        )
        for r in rows:
            # Fuzzy match: lowercase, strip GSP/BSP suffixes, normalise separators
            target = _normalise(r["gsp_name"])
            match = await conn.fetchrow(
                """
                SELECT id,
                       ST_X(ST_Transform(geom, 4326)) AS lon,
                       ST_Y(ST_Transform(geom, 4326)) AS lat
                FROM grid_substations
                WHERE geom IS NOT NULL
                  AND LOWER(REGEXP_REPLACE(name, '[^a-zA-Z0-9]', '', 'g'))
                      LIKE '%' || $1 || '%'
                ORDER BY voltage_kv DESC NULLS LAST
                LIMIT 1
                """,
                target,
            )
            if match:
                await conn.execute(
                    """
                    UPDATE nged_gsp_latest
                    SET lat = $1, lon = $2, substation_id = $3, updated_at = now()
                    WHERE region = $4 AND gsp_name = $5
                    """,
                    float(match["lat"]), float(match["lon"]), match["id"],
                    r["region"], r["gsp_name"],
                )
                updated += 1
    return updated


def _normalise(name: str) -> str:
    """Lowercase alphanumeric-only key for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ────────────────────────────────────────────────────────────────────────
# Read side — frontend feeds
# ────────────────────────────────────────────────────────────────────────

async def get_gsp_geojson(pool: asyncpg.Pool, region: str | None = None) -> dict:
    """Return a GeoJSON FeatureCollection of NGED GSPs with live values."""
    conditions = ["lat IS NOT NULL", "lon IS NOT NULL"]
    params: list[Any] = []
    if region:
        conditions.append("region = $1")
        params.append(region)
    sql = f"""
        SELECT region, gsp_name, observed_at, net_demand_mw, generation_mw,
               import_mw, solar_mw, wind_mw, storage_mw, other_mw,
               gsp_capacity_mw, lat, lon, substation_id
        FROM nged_gsp_latest
        WHERE {" AND ".join(conditions)}
        ORDER BY observed_at DESC NULLS LAST
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        demand = float(r["net_demand_mw"] or 0)
        generation = float(r["generation_mw"] or 0)
        imp = float(r["import_mw"] or 0)
        cap = float(r["gsp_capacity_mw"] or 0)
        util = None
        if cap > 0:
            util = max(demand, imp, generation) / cap
        net_flow = generation - demand
        colour = _gsp_colour(util if util is not None else (demand / max(demand + generation, 1)))

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "region": r["region"],
                "gsp_name": r["gsp_name"],
                "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
                "net_demand_mw": demand,
                "generation_mw": generation,
                "import_mw": imp,
                "solar_mw": float(r["solar_mw"] or 0),
                "wind_mw": float(r["wind_mw"] or 0),
                "storage_mw": float(r["storage_mw"] or 0),
                "other_mw": float(r["other_mw"] or 0),
                "gsp_capacity_mw": cap,
                "utilisation": round(util, 3) if util is not None else None,
                "net_flow_mw": net_flow,
                "colour": colour,
                "radius": _gsp_radius(max(demand, generation)),
                "substation_id": r["substation_id"],
            },
        })

    return {
        "type": "FeatureCollection",
        "count": len(features),
        "colour_ramp": [
            {"max_util": 0.3, "colour": "#2e7d32", "label": "Ample headroom"},
            {"max_util": 0.6, "colour": "#7cb342", "label": "Comfortable"},
            {"max_util": 0.8, "colour": "#fdd835", "label": "Moderate"},
            {"max_util": 0.95, "colour": "#f57c00", "label": "Tight"},
            {"max_util": 1.10, "colour": "#c62828", "label": "At/over limit"},
        ],
        "features": features,
    }


def _gsp_colour(util: float | None) -> str:
    """Return a colour for GSP utilisation (0..1+)."""
    if util is None:
        return "#9e9e9e"
    if util < 0.3:   return "#2e7d32"
    if util < 0.6:   return "#7cb342"
    if util < 0.8:   return "#fdd835"
    if util < 0.95:  return "#f57c00"
    return "#c62828"


def _gsp_radius(mw: float) -> float:
    """Scale marker radius by MW (bounded)."""
    return 6 + min(22, mw / 25.0)


async def get_gsp_timeseries(
    pool: asyncpg.Pool, region: str, gsp_name: str, hours: int = 48,
) -> list[dict]:
    """Return historical time series for a single GSP."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT observed_at, net_demand_mw, generation_mw, import_mw,
                   solar_mw, wind_mw, storage_mw, other_mw
            FROM nged_gsp_timeseries
            WHERE region = $1 AND gsp_name = $2
              AND observed_at >= now() - make_interval(hours => $3)
            ORDER BY observed_at ASC
            """,
            region, gsp_name, hours,
        )
    return [
        {
            "observed_at": r["observed_at"].isoformat(),
            "net_demand_mw": float(r["net_demand_mw"] or 0),
            "generation_mw": float(r["generation_mw"] or 0),
            "import_mw": float(r["import_mw"] or 0),
            "solar_mw": float(r["solar_mw"] or 0),
            "wind_mw": float(r["wind_mw"] or 0),
            "storage_mw": float(r["storage_mw"] or 0),
            "other_mw": float(r["other_mw"] or 0),
        } for r in rows
    ]


async def get_stats(pool: asyncpg.Pool) -> dict:
    """Aggregate stats across all ingested GSPs."""
    async with pool.acquire() as conn:
        total_rows = await conn.fetchval("SELECT COUNT(*) FROM nged_gsp_timeseries") or 0
        total_gsps = await conn.fetchval("SELECT COUNT(*) FROM nged_gsp_latest") or 0
        resolved = await conn.fetchval("SELECT COUNT(*) FROM nged_gsp_latest WHERE lat IS NOT NULL") or 0
        by_region = await conn.fetch(
            "SELECT region, COUNT(*) AS n FROM nged_gsp_latest GROUP BY region"
        )
        latest_obs = await conn.fetchval("SELECT MAX(observed_at) FROM nged_gsp_timeseries")
    return {
        "total_rows": int(total_rows),
        "total_gsps": int(total_gsps),
        "resolved_locations": int(resolved),
        "by_region": {r["region"]: int(r["n"]) for r in by_region},
        "latest_observed_at": latest_obs.isoformat() if latest_obs else None,
    }
