"""
Enhanced DNO capacity ingester — ECR, headroom, and LTDS data for all 6 UK DNOs.

Uses same ODS v2.1 / CKAN v3 adapter patterns as grid_data_ingester.py.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx

log = logging.getLogger("princeps.dno_capacity")

_TIMEOUT = 20
_UA = "Princeps/1.0"

# ─── DNO Configurations ──────────────────────────────────────────────────────

DNO_CONFIGS = {
    "ukpn": {
        "name": "UK Power Networks",
        "type": "ods",
        "base": "https://ukpowernetworks.opendatasoft.com",
        "api_key_env": "UKPN_ODS_APIKEY",
        "datasets": {
            "ecr": "ukpn-embedded-capacity-register",
            "headroom": "dfes-network-headroom-report",
            "ltds": "ukpn-ltds-infrastructure-projects",
            "queue": "ukpn-overall-queue-insights",
        },
    },
    "npg": {
        "name": "Northern Powergrid",
        "type": "ods",
        "base": "https://northernpowergrid.opendatasoft.com",
        "api_key_env": None,  # public
        "datasets": {
            "ecr": "embedded-capacity-register",
            "headroom": "npg_ndp_demand_headroom",
            "generation_headroom": "npg_ndp_generation_headroom",
        },
    },
    "spen": {
        "name": "SP Energy Networks",
        "type": "ods",
        "base": "https://spenergynetworks.opendatasoft.com",
        "api_key_env": "SPEN_ODS_APIKEY",
        "datasets": {
            "ecr": "embedded-capacity-register",
            "headroom": "spd-dg-connections-network-info",
        },
    },
    "enwl": {
        "name": "Electricity North West",
        "type": "ods",
        "base": "https://electricitynorthwest.opendatasoft.com",
        "api_key_env": "ENWL_ODS_APIKEY",
        "datasets": {
            "ecr": "enwl-embedded-capacity-register-2-1mw-and-above",
            "headroom": "enwl-pry-heatmap",
        },
    },
    "ssen": {
        "name": "SSEN Distribution",
        "type": "ckan",
        "base": "https://data-api.ssen.co.uk",
        "api_key_env": None,  # public
        "datasets": {
            "ecr": "bbae6797-364a-4b2d-a01a-8395e21bee76",
            "headroom": "52e9a305-ad90-4c81-9175-20a40ef57894",
        },
    },
    "nged": {
        "name": "NGED (National Grid Electricity Distribution)",
        "type": "ckan",
        "base": "https://connecteddata.nationalgrid.co.uk",
        "api_key_env": "NGED_CKAN_APIKEY",
        "datasets": {
            "ecr": "82a4ae83-77a3-4e7b-9060-8072ed96de9d",
            "headroom": "d1963858-d451-4794-a6bf-123fad0f0b3a",
            "queue": "d1895bd3-d9d2-4886-a0a3-b7eadd9ab6c2",
        },
    },
}

# ─── Technology normalisation ─────────────────────────────────────────────────

TECH_MAP = {
    "solar": "solar", "pv": "solar", "photovoltaic": "solar",
    "wind": "wind", "onshore": "wind", "offshore": "wind",
    "battery": "bess", "bess": "bess", "storage": "bess",
    "gas": "gas", "ccgt": "gas", "ocgt": "gas",
    "biomass": "biomass", "chp": "chp",
    "hydro": "hydro",
}


def _normalise_tech(raw: str | None) -> str:
    if not raw:
        return "other"
    lower = raw.lower().strip()
    for key, val in TECH_MAP.items():
        if key in lower:
            return val
    return "other"


# ─── ODS v2.1 Adapter ────────────────────────────────────────────────────────

async def _fetch_ods(dno_key: str, dataset_key: str, limit: int = 100) -> list[dict]:
    """Fetch records from OpenDataSoft v2.1 API."""
    cfg = DNO_CONFIGS[dno_key]
    dataset_id = cfg["datasets"].get(dataset_key)
    if not dataset_id:
        return []

    api_key = os.environ.get(cfg["api_key_env"]) if cfg["api_key_env"] else None
    headers = {"User-Agent": _UA}
    if api_key:
        headers["Authorization"] = f"Apikey {api_key}"

    url = f"{cfg['base']}/api/explore/v2.1/catalog/datasets/{dataset_id}/records"
    all_records = []
    offset = 0

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        while True:
            params = {"limit": limit, "offset": offset}
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    log.warning("ODS %s/%s returned %d", dno_key, dataset_key, resp.status_code)
                    break
                data = resp.json()
                results = data.get("results", [])
                all_records.extend(results)
                if len(results) < limit:
                    break
                offset += limit
            except Exception as e:
                log.warning("ODS %s/%s failed: %s", dno_key, dataset_key, e)
                break

    return all_records


# ─── CKAN v3 Adapter ─────────────────────────────────────────────────────────

async def _fetch_ckan(dno_key: str, dataset_key: str, limit: int = 5000) -> list[dict]:
    """Fetch records from CKAN datastore API."""
    cfg = DNO_CONFIGS[dno_key]
    resource_id = cfg["datasets"].get(dataset_key)
    if not resource_id:
        return []

    api_key = os.environ.get(cfg["api_key_env"]) if cfg["api_key_env"] else None
    headers = {"User-Agent": _UA}
    if api_key:
        headers["Authorization"] = api_key

    url = f"{cfg['base']}/api/3/action/datastore_search"
    all_records = []
    offset = 0

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
        while True:
            params = {"resource_id": resource_id, "limit": limit, "offset": offset}
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    log.warning("CKAN %s/%s returned %d", dno_key, dataset_key, resp.status_code)
                    break
                data = resp.json()
                records = data.get("result", {}).get("records", [])
                all_records.extend(records)
                if len(records) < limit:
                    break
                offset += limit
            except Exception as e:
                log.warning("CKAN %s/%s failed: %s", dno_key, dataset_key, e)
                break

    return all_records


async def _fetch(dno_key: str, dataset_key: str) -> list[dict]:
    """Route to ODS or CKAN adapter."""
    cfg = DNO_CONFIGS[dno_key]
    if cfg["type"] == "ods":
        return await _fetch_ods(dno_key, dataset_key)
    return await _fetch_ckan(dno_key, dataset_key)


# ─── ECR (Embedded Capacity Register) ────────────────────────────────────────

async def fetch_ecr(dno: str | None = None) -> list[dict]:
    """Fetch ECR data — what generation/storage is already connected or accepted."""
    dnos = [dno] if dno else list(DNO_CONFIGS.keys())
    all_ecr = []

    for d in dnos:
        raw = await _fetch(d, "ecr")
        for r in raw:
            fields = r.get("fields", r)  # ODS wraps in "fields"
            capacity = 0
            for key in ["capacity_mw", "registered_capacity", "installed_capacity", "capacity", "export_capacity"]:
                val = fields.get(key) or fields.get(key.replace("_", " ").title())
                if val:
                    try:
                        capacity = float(val)
                        break
                    except (ValueError, TypeError):
                        pass

            tech = _normalise_tech(
                fields.get("technology") or fields.get("fuel_type") or fields.get("generation_type")
            )
            substation = (
                fields.get("substation") or fields.get("connection_point")
                or fields.get("primary_substation") or fields.get("gsp")
            )
            status = fields.get("status") or fields.get("connection_status") or "unknown"

            # Extract coordinates
            lat = fields.get("lat") or fields.get("latitude")
            lon = fields.get("lon") or fields.get("longitude")
            if not lat and "geo_point_2d" in fields:
                geo = fields["geo_point_2d"]
                if isinstance(geo, dict):
                    lat, lon = geo.get("lat"), geo.get("lon")
                elif isinstance(geo, list) and len(geo) == 2:
                    lat, lon = geo[0], geo[1]

            all_ecr.append({
                "dno": d,
                "substation": substation,
                "technology": tech,
                "capacity_mw": capacity,
                "status": str(status).lower(),
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
            })

    return all_ecr


# ─── Headroom ─────────────────────────────────────────────────────────────────

async def fetch_headroom(dno: str | None = None) -> list[dict]:
    """Fetch network headroom — available capacity at substations."""
    dnos = [dno] if dno else list(DNO_CONFIGS.keys())
    all_headroom = []

    for d in dnos:
        raw = await _fetch(d, "headroom")
        for r in raw:
            fields = r.get("fields", r)

            demand_hr = None
            gen_hr = None
            for key in ["demand_headroom", "demand_headroom_mw", "thermal_headroom", "headroom_mw", "spare_capacity"]:
                val = fields.get(key) or fields.get(key.replace("_", " ").title())
                if val:
                    try:
                        demand_hr = float(val)
                        break
                    except (ValueError, TypeError):
                        pass

            for key in ["generation_headroom", "generation_headroom_mw", "export_headroom", "dg_headroom"]:
                val = fields.get(key) or fields.get(key.replace("_", " ").title())
                if val:
                    try:
                        gen_hr = float(val)
                        break
                    except (ValueError, TypeError):
                        pass

            substation = (
                fields.get("substation") or fields.get("primary") or fields.get("name")
                or fields.get("bsp") or fields.get("gsp")
            )
            voltage = fields.get("voltage") or fields.get("voltage_kv")

            lat = fields.get("lat") or fields.get("latitude")
            lon = fields.get("lon") or fields.get("longitude")
            if not lat and "geo_point_2d" in fields:
                geo = fields["geo_point_2d"]
                if isinstance(geo, dict):
                    lat, lon = geo.get("lat"), geo.get("lon")
                elif isinstance(geo, list) and len(geo) == 2:
                    lat, lon = geo[0], geo[1]

            all_headroom.append({
                "dno": d,
                "substation": substation,
                "demand_headroom_mw": demand_hr,
                "generation_headroom_mw": gen_hr,
                "voltage_kv": voltage,
                "lat": float(lat) if lat else None,
                "lon": float(lon) if lon else None,
            })

    return all_headroom


# ─── DB Tables ────────────────────────────────────────────────────────────────

async def ensure_tables(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dno_ecr (
                id SERIAL PRIMARY KEY,
                dno TEXT NOT NULL,
                substation TEXT,
                technology TEXT,
                capacity_mw REAL,
                status TEXT,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                ingested_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_dno_ecr_dno ON dno_ecr(dno);
            CREATE INDEX IF NOT EXISTS idx_dno_ecr_sub ON dno_ecr(substation);

            CREATE TABLE IF NOT EXISTS dno_headroom (
                id SERIAL PRIMARY KEY,
                dno TEXT NOT NULL,
                substation TEXT,
                demand_headroom_mw REAL,
                generation_headroom_mw REAL,
                voltage_kv TEXT,
                lat DOUBLE PRECISION,
                lon DOUBLE PRECISION,
                ingested_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_dno_hr_dno ON dno_headroom(dno);
        """)
    log.info("DNO capacity tables ensured")


# ─── Query Helpers ────────────────────────────────────────────────────────────

async def query_ecr(pool, dno=None, substation=None, technology=None, status=None) -> list:
    sql = "SELECT * FROM dno_ecr WHERE 1=1"
    params = []
    idx = 0
    if dno:
        idx += 1; sql += f" AND dno=${idx}"; params.append(dno)
    if substation:
        idx += 1; sql += f" AND substation ILIKE ${idx}"; params.append(f"%{substation}%")
    if technology:
        idx += 1; sql += f" AND technology=${idx}"; params.append(technology)
    if status:
        idx += 1; sql += f" AND status=${idx}"; params.append(status)
    sql += " ORDER BY capacity_mw DESC LIMIT 500"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def query_headroom(pool, lat=None, lon=None, radius_km=20, dno=None) -> list:
    sql = "SELECT * FROM dno_headroom WHERE lat IS NOT NULL AND lon IS NOT NULL"
    params = []
    idx = 0
    if dno:
        idx += 1; sql += f" AND dno=${idx}"; params.append(dno)
    if lat and lon:
        # Simple bounding box filter (approx)
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * 0.7)  # rough cos(lat) for UK
        idx += 1; sql += f" AND lat BETWEEN ${idx}"
        params.append(lat - dlat)
        idx += 1; sql += f" AND ${idx}"
        params.append(lat + dlat)
        idx += 1; sql += f" AND lon BETWEEN ${idx}"
        params.append(lon - dlon)
        idx += 1; sql += f" AND ${idx}"
        params.append(lon + dlon)
    sql += " ORDER BY demand_headroom_mw DESC NULLS LAST LIMIT 200"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def capacity_map_geojson(pool, dno=None) -> dict:
    """Return headroom data as GeoJSON FeatureCollection."""
    headroom = await query_headroom(pool, dno=dno)
    features = []
    for h in headroom:
        if h.get("lat") and h.get("lon"):
            hr = h.get("demand_headroom_mw")
            # Color code: green >50MW, amber 10-50MW, red <10MW
            color = "#2D7A4F" if (hr and hr > 50) else "#C67A1A" if (hr and hr > 10) else "#B5432A"
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
                "properties": {
                    "substation": h.get("substation"),
                    "dno": h.get("dno"),
                    "demand_headroom_mw": hr,
                    "generation_headroom_mw": h.get("generation_headroom_mw"),
                    "voltage_kv": h.get("voltage_kv"),
                    "color": color,
                    "availability": "high" if (hr and hr > 50) else "medium" if (hr and hr > 10) else "low",
                },
            })
    return {"type": "FeatureCollection", "features": features}


async def ecr_summary_by_substation(pool, dno=None) -> list:
    """Aggregate ECR by substation — total connected capacity + tech breakdown."""
    sql = """
        SELECT substation, dno,
               SUM(capacity_mw) as total_mw,
               COUNT(*) as project_count,
               json_agg(json_build_object('technology', technology, 'capacity_mw', capacity_mw, 'status', status)) as projects
        FROM dno_ecr
        WHERE substation IS NOT NULL
    """
    params = []
    if dno:
        sql += " AND dno=$1"
        params.append(dno)
    sql += " GROUP BY substation, dno ORDER BY total_mw DESC LIMIT 100"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


# ─── Ingest Orchestrator ──────────────────────────────────────────────────────

async def ingest_dno_capacity(pool=None) -> dict:
    """Fetch ECR + headroom for all DNOs and persist to DB."""
    ecr_data, headroom_data = await asyncio.gather(
        fetch_ecr(),
        fetch_headroom(),
        return_exceptions=True,
    )

    summary = {
        "ecr": {"count": len(ecr_data) if isinstance(ecr_data, list) else 0},
        "headroom": {"count": len(headroom_data) if isinstance(headroom_data, list) else 0},
    }

    if pool and isinstance(ecr_data, list) and ecr_data:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM dno_ecr")
            await conn.executemany(
                """INSERT INTO dno_ecr (dno, substation, technology, capacity_mw, status, lat, lon)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                [(r["dno"], r["substation"], r["technology"], r["capacity_mw"],
                  r["status"], r["lat"], r["lon"]) for r in ecr_data],
            )
            summary["ecr"]["persisted"] = len(ecr_data)

    if pool and isinstance(headroom_data, list) and headroom_data:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM dno_headroom")
            await conn.executemany(
                """INSERT INTO dno_headroom (dno, substation, demand_headroom_mw, generation_headroom_mw, voltage_kv, lat, lon)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                [(r["dno"], r["substation"], r["demand_headroom_mw"], r["generation_headroom_mw"],
                  r["voltage_kv"], r["lat"], r["lon"]) for r in headroom_data],
            )
            summary["headroom"]["persisted"] = len(headroom_data)

    return summary
