"""
Multi-DNO OpenDataSoft / CKAN ingester.

One adapter per UK DNO. Each adapter reads its API key from an env var
(UKPN_ODS_APIKEY, SPEN_ODS_APIKEY, ENWL_ODS_APIKEY, NGED_CKAN_APIKEY,
SSEN_API_KEY) and silently skips ingest if the key is missing. No key,
no data, no crash.

Data targets (all Tier-1 datasets from the research brief):

  * grid-and-primary-sites           → primary substation inventory
  * primary-transformers             → transformer utilisation
  * secondary-site-utilisation       → LV loading
  * ukpn-large-demand-list           → DC demand queue (≥5 MVA)
  * ukpn-overall-queue-insights      → connection queue
  * ltds-table-*                     → LTDS tabular data (all ~20 tables)
  * ukpn-ehv-network-outages         → live outages → grid_events
  * ukpn-low-carbon-technologies     → LCT connected list
  * ukpn-dnoa / ukpn-low-voltage-dnoa → Distribution Network Options Assessment

Target tables live alongside the LTDS CIM ones under the `dno_*` prefix.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.dno_opendata")


# ════════════════════════════════════════════════════════════════════════
# DNO adapter registry
# ════════════════════════════════════════════════════════════════════════

DNO_ADAPTERS = {
    "UKPN": {
        "name": "UK Power Networks",
        "base_url": "https://ukpowernetworks.opendatasoft.com",
        "api": "opendatasoft_v2",
        "api_key_env": "UKPN_ODS_APIKEY",
        "datasets": {
            "grid_primary_sites":      "grid-and-primary-sites",
            "primary_transformers":    "ukpn-primary-transformers",
            "secondary_utilisation":   "ukpn-secondary-site-utilisation",
            "secondary_transformers":  "ukpn-secondary-site-transformers",
            "large_demand_list":       "ukpn-large-demand-list",
            "queue_insights":          "ukpn-overall-queue-insights",
            "ltds_infra_projects":     "ukpn-ltds-infrastructure-projects",
            "ltds_t2b_transformers":   "ltds-table-2b-transformer-data-3w",
            "ltds_t7_restrictions":    "ltds-table-7-operational-restrictions",
            "low_carbon_tech":         "low-carbon-technologies",
            "ehv_outages":             "ukpn-ehv-network-outages",
            "network_losses":          "ukpn-network-losses",
            "dnoa":                    "ukpn-dnoa",
            "lv_dnoa":                 "ukpn-low-voltage-dnoa",
            "idno_areas":              "ukpn-idno-areas",
            "licence_boundaries":      "ukpn-licence-boundaries",
            "data_centre_profiles":    "ukpn-data-centre-demand-profiles",
            "data_centres_by_la":      "ukpn-data-centres-by-local-authority",
            "constraints_rtm":         "ukpn-constraints-real-time-meter-readings",
            "sgt_header":              "ukpn-super-grid-transformer-header",
            "domain_dataset0":         "domain-dataset0",
            "ol_132kv":                "ukpn-132kv-overhead-lines",
            "ol_33kv":                 "ukpn-33kv-overhead-lines",
            "ltds_cim":                "ukpn-ltds-cim",
        },
    },
    "SPEN": {
        "name": "SP Energy Networks",
        "base_url": "https://spenergynetworks.opendatasoft.com",
        "api": "opendatasoft_v2",
        "api_key_env": "SPEN_ODS_APIKEY",
        "datasets": {
            "ltds_cim_spd":            "spd-ltds-cim-eq-profile",
            "ltds_cim_spm":            "spm-ltds-cim-eq-profile",
        },
    },
    "ENWL": {
        "name": "Electricity North West",
        "base_url": "https://electricitynorthwest.opendatasoft.com",
        "api": "opendatasoft_v2",
        "api_key_env": "ENWL_ODS_APIKEY",
        "datasets": {},   # populated when portal is explored with key
    },
    "NGED": {
        "name": "National Grid Electricity Distribution (ex-WPD)",
        "base_url": "https://connecteddata.nationalgrid.co.uk",
        "api": "ckan_v3",
        "api_key_env": "NGED_CKAN_APIKEY",
        "datasets": {
            "ltds_cim":                "ltds-common-information-model",
            "nom_headroom":            "network-opportunity-map-headroom",
            "live_gsp_em":             "101d968c-3031-4900-a0a2-6d9f6485f92c",
            "live_gsp_wm":             "d5a803a8-7bc0-4d15-8ce0-de1724f4ba74",
            "live_gsp_sw":             "8be19ae9-d070-41d3-a01b-44dc5a89d891",
            "live_gsp_sw_wales":       "a4613210-c299-441f-85e5-c3788f62bbfa",
            "ecr":                     "55621879-bd56-48d8-8179-36daa38ede99",
        },
    },
    "NPG": {
        "name": "Northern Powergrid",
        "base_url": "https://northernpowergrid.opendatasoft.com",
        "api": "opendatasoft_v2",
        "api_key_env": "NPG_ODS_APIKEY",   # optional — some datasets public
        "datasets": {
            "ltds_cim_files":          "ltds-cim-files",
        },
    },
    "SSEN": {
        "name": "Scottish & Southern Electricity Networks",
        "base_url": "https://data.ssen.co.uk",
        "api": "ckan_v3",
        "api_key_env": "SSEN_API_KEY",
        "datasets": {},   # populated when portal is explored with key
    },
    "NESO": {
        "name": "National Energy System Operator",
        "base_url": "https://api.neso.energy",
        "api": "ckan_v3",
        "api_key_env": "NESO_API_KEY",   # optional — most NESO datasets are public
        "datasets": {
            # Constraint costs + limits — critical for curtailment intel
            "constraint_cost_24m":         "24-months-ahead-constraint-cost-forecast",
            "constraint_limits_24m":       "24-months-ahead-constraint-limits",
            "historical_constraint_flows": "historic-gb-actual-generation-output-and-dispatch-instructions",
            # Reactive power + ancillary services
            "orps_utilisation":            "obligatory-reactive-power-service-orps-utilisation",
            "orps_tender":                 "obligatory-reactive-power-service-orps-tender",
            "fr_market":                   "firm-frequency-response-ffr",
            "dc_dm_dr_long_term":          "long-term-forecasts-for-dc-dm-dr-requirements",
            "dynamic_containment":         "dynamic-containment-auction-results",
            "dynamic_moderation":          "dynamic-moderation-auction-results",
            "dynamic_regulation":          "dynamic-regulation-auction-results",
            # Demand side
            "demand_flexibility":          "demand-flexibility",
            "dfs_results":                 "demand-flexibility-service-utilisation",
            # FES + TEC register + GSP data
            "fes_2024":                    "future-energy-scenarios-fes-2024-workbook",
            "tec_register":                "tec-register",
            "eso_connection_queue":        "connection-application-offer-queue",
            "gsp_capacity_map":            "gsp-capacity-map",
            "embedded_capacity_register":  "embedded-capacity-register",
            # Carbon + costs + outturn
            "carbon_intensity_forecast":   "carbon-intensity-of-electricity-generation",
            "bsuos":                       "daily-balancing-services-use-of-system-bsuos-cost",
            "system_prices":               "system-prices",
            # DC tools
            "dc_connections_reform_2026":  "connections-reform",
            "network_options_assessment":  "network-options-assessment-noa",
        },
    },
}


def _api_key(adapter: dict) -> str | None:
    """Return the API key from the env var for this adapter, or None."""
    return os.environ.get(adapter["api_key_env"])


# ════════════════════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════════════════════

DNO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dno_datasets (
    dno                 TEXT NOT NULL,
    dataset_key         TEXT NOT NULL,
    dataset_id          TEXT NOT NULL,
    title               TEXT,
    records_count       INTEGER,
    last_modified       TIMESTAMPTZ,
    requires_auth       BOOLEAN,
    last_ingested_at    TIMESTAMPTZ,
    last_ingest_status  TEXT,          -- 'ok' | 'forbidden' | 'error' | 'skipped_no_key'
    last_ingest_rows    INTEGER,
    PRIMARY KEY (dno, dataset_key)
);


-- Unified "grid_primary_sites" landing table — primary + grid substations
-- from ANY DNO's OpenDataSoft "grid-and-primary-sites" dataset.
CREATE TABLE IF NOT EXISTS dno_grid_primary_sites (
    dno                 TEXT NOT NULL,
    site_name           TEXT NOT NULL,
    site_type           TEXT,           -- 'Grid','Primary','BSP','GSP'
    voltage_kv          NUMERIC,
    licence_area        TEXT,
    firm_capacity_mw    NUMERIC,
    headroom_mw         NUMERIC,
    lat                 DOUBLE PRECISION,
    lon                 DOUBLE PRECISION,
    raw                 JSONB,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, site_name)
);
CREATE INDEX IF NOT EXISTS idx_dno_gps_dno  ON dno_grid_primary_sites (dno);
CREATE INDEX IF NOT EXISTS idx_dno_gps_type ON dno_grid_primary_sites (site_type);


-- Unified primary transformer loading
CREATE TABLE IF NOT EXISTS dno_primary_transformers (
    dno                 TEXT NOT NULL,
    asset_id            TEXT NOT NULL,
    site_name           TEXT,
    voltage_primary_kv  NUMERIC,
    voltage_secondary_kv NUMERIC,
    rated_mva           NUMERIC,
    peak_demand_mva     NUMERIC,
    utilisation_pct     NUMERIC,
    rag_status          TEXT,
    raw                 JSONB,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_dno_prim_tf_dno ON dno_primary_transformers (dno);


-- UKPN large demand list (also usable for other DNOs with similar data)
CREATE TABLE IF NOT EXISTS dno_large_demand_list (
    dno                 TEXT NOT NULL,
    anonymised_name     TEXT NOT NULL,
    licence_area        TEXT,
    grid_supply_point   TEXT,
    demand_technology_type TEXT,
    required_import_capacity_kva NUMERIC,
    application_date    DATE,
    raw                 JSONB,
    ingested_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, anonymised_name)
);
CREATE INDEX IF NOT EXISTS idx_dno_ldl_gsp ON dno_large_demand_list (grid_supply_point);
CREATE INDEX IF NOT EXISTS idx_dno_ldl_tech ON dno_large_demand_list (demand_technology_type);


-- DC demand profiles (real measured load shapes, parquet-derived)
CREATE TABLE IF NOT EXISTS dno_dc_demand_profiles (
    dno                 TEXT NOT NULL,
    profile_id          TEXT NOT NULL,
    voltage_class       TEXT,            -- 'HV Import','EHV Import','LV Import' etc
    timestamp_utc       TIMESTAMPTZ,
    load_mw             NUMERIC,
    raw                 JSONB,
    PRIMARY KEY (dno, profile_id, timestamp_utc)
);
CREATE INDEX IF NOT EXISTS idx_dno_dc_prof_time ON dno_dc_demand_profiles (timestamp_utc);


-- LTDS tabular landing table — rows from ltds-table-* datasets
CREATE TABLE IF NOT EXISTS dno_ltds_tabular (
    dno                 TEXT NOT NULL,
    dataset_key         TEXT NOT NULL,   -- 'ltds_t2b_transformers' etc
    row_num             INTEGER NOT NULL,
    row                 JSONB,
    ingested_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, dataset_key, row_num)
);


-- Connection queue insights (merged with eso_tec_register + cluster graph)
CREATE TABLE IF NOT EXISTS dno_queue_insights (
    dno                 TEXT NOT NULL,
    project_ref         TEXT NOT NULL,
    licence_area        TEXT,
    connection_point    TEXT,
    technology          TEXT,
    capacity_mw         NUMERIC,
    stage               TEXT,
    accepted_date       DATE,
    target_energisation DATE,
    queue_position      INTEGER,
    raw                 JSONB,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, project_ref)
);


-- Distribution Network Options Assessment (DNOA) — future network upgrades
CREATE TABLE IF NOT EXISTS dno_dnoa (
    dno                 TEXT NOT NULL,
    option_ref          TEXT NOT NULL,
    title               TEXT,
    licence_area        TEXT,
    voltage_level_kv    NUMERIC,
    option_type         TEXT,
    estimated_cost_gbp  NUMERIC,
    target_year         INTEGER,
    description         TEXT,
    raw                 JSONB,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, option_ref)
);


-- Low Carbon Technologies connected list (EVs / heat pumps / DG)
CREATE TABLE IF NOT EXISTS dno_low_carbon_tech (
    dno                 TEXT NOT NULL,
    lct_ref             TEXT NOT NULL,
    lct_type            TEXT,
    postcode            TEXT,
    capacity_kw         NUMERIC,
    connection_date     DATE,
    lat                 DOUBLE PRECISION,
    lon                 DOUBLE PRECISION,
    raw                 JSONB,
    PRIMARY KEY (dno, lct_ref)
);


-- Live network outages — emitted to grid_events for the Pulse stream
CREATE TABLE IF NOT EXISTS dno_outages (
    dno                 TEXT NOT NULL,
    outage_ref          TEXT NOT NULL,
    status              TEXT,
    start_time          TIMESTAMPTZ,
    end_time            TIMESTAMPTZ,
    affected_site       TEXT,
    voltage_kv          NUMERIC,
    customers_affected  INTEGER,
    raw                 JSONB,
    ingested_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (dno, outage_ref)
);
CREATE INDEX IF NOT EXISTS idx_dno_outage_status ON dno_outages (status);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Create dno_* tables."""
    async with pool.acquire() as conn:
        clean = "\n".join(l for l in DNO_SCHEMA_SQL.splitlines() if not l.lstrip().startswith("--"))
        for stmt in clean.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("dno_opendata schema ready")


# ════════════════════════════════════════════════════════════════════════
# OpenDataSoft v2.1 client
# ════════════════════════════════════════════════════════════════════════

async def _ods_fetch_records(
    base_url: str,
    dataset_id: str,
    api_key: str | None,
    limit: int = 100,
    offset: int = 0,
    timeout: float = 30.0,
) -> dict:
    """Fetch records from an OpenDataSoft v2.1 records endpoint."""
    url = f"{base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Apikey {api_key}"
    params = {"limit": limit, "offset": offset}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers, params=params)
        if r.status_code == 403:
            return {"error": "forbidden", "status": 403}
        r.raise_for_status()
        return r.json()


async def _ods_fetch_all_records(
    base_url: str,
    dataset_id: str,
    api_key: str | None,
    page_size: int = 100,
    max_rows: int = 10000,
) -> tuple[list[dict], str]:
    """Page through an OpenDataSoft dataset until exhausted or max_rows reached.

    Returns (records, status) where status is 'ok' | 'forbidden' | 'error'.
    """
    out: list[dict] = []
    offset = 0
    while offset < max_rows:
        try:
            resp = await _ods_fetch_records(base_url, dataset_id, api_key, limit=page_size, offset=offset)
        except Exception as e:
            log.warning("%s records fetch failed: %s", dataset_id, e)
            return out, "error"
        if resp.get("error") == "forbidden":
            return out, "forbidden"
        results = resp.get("results", [])
        if not results:
            break
        out.extend(results)
        if len(results) < page_size:
            break
        offset += page_size
    return out, "ok"


# ════════════════════════════════════════════════════════════════════════
# Dataset-specific parsers — map ODS records to our unified tables
# ════════════════════════════════════════════════════════════════════════

import json


async def _record_datasets_status(pool: asyncpg.Pool, dno: str, key: str, dataset_id: str, status: str, rows: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO dno_datasets (dno, dataset_key, dataset_id, last_ingested_at, last_ingest_status, last_ingest_rows)
            VALUES ($1, $2, $3, now(), $4, $5)
            ON CONFLICT (dno, dataset_key) DO UPDATE SET
                last_ingested_at = EXCLUDED.last_ingested_at,
                last_ingest_status = EXCLUDED.last_ingest_status,
                last_ingest_rows = EXCLUDED.last_ingest_rows
            """,
            dno, key, dataset_id, status, rows,
        )


async def ingest_grid_primary_sites(pool: asyncpg.Pool, dno: str, records: list[dict]) -> int:
    """Normalise grid-and-primary-sites records into dno_grid_primary_sites.

    UKPN schema (verified live Apr 2026): sitename / sitetype / sitevoltage /
    licencearea / maxdemandsummer|winter / transratingsummer|winter /
    spatial_coordinates{lat,lon}.
    """
    rows = []
    for r in records:
        name = (
            r.get("sitename") or r.get("site_name") or r.get("name")
            or r.get("site") or r.get("sitedesc") or ""
        )
        if not name:
            continue
        geo = r.get("spatial_coordinates") or r.get("geo_point_2d") or {}
        lat = geo.get("lat") if isinstance(geo, dict) else None
        lon = geo.get("lon") if isinstance(geo, dict) else None
        # Summer headroom = summer transformer rating − summer max demand
        max_d_sum = _num(r.get("maxdemandsummer"))
        tr_rating_sum = _num(r.get("transratingsummer"))
        headroom_mw = None
        if max_d_sum is not None and tr_rating_sum is not None:
            headroom_mw = max(0, tr_rating_sum - max_d_sum)
        rows.append((
            dno, name,
            r.get("sitetype") or r.get("site_type") or r.get("type"),
            _num(r.get("sitevoltage") or r.get("voltage_kv") or r.get("voltage")),
            r.get("licencearea") or r.get("licence_area"),
            tr_rating_sum,
            headroom_mw,
            lat, lon,
            json.dumps(r),
        ))
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO dno_grid_primary_sites (dno, site_name, site_type, voltage_kv,
                licence_area, firm_capacity_mw, headroom_mw, lat, lon, raw, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, now())
            ON CONFLICT (dno, site_name) DO UPDATE SET
                site_type = EXCLUDED.site_type,
                voltage_kv = EXCLUDED.voltage_kv,
                firm_capacity_mw = EXCLUDED.firm_capacity_mw,
                headroom_mw = EXCLUDED.headroom_mw,
                lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                raw = EXCLUDED.raw, updated_at = now()
            """,
            rows,
        )
    return len(rows)


async def ingest_primary_transformers(pool: asyncpg.Pool, dno: str, records: list[dict]) -> int:
    """Normalise primary transformer records into dno_primary_transformers.

    UKPN schema (verified Apr 2026): functionallocation / sitedesc /
    operationalvoltage / onanrating_kva / primary_winding_voltage /
    secondary_winding_voltage / make / model / dno / reverse_power_capability.
    """
    rows = []
    for r in records:
        aid = (
            r.get("functionallocation") or r.get("asset_id")
            or r.get("transformer_id") or r.get("id")
            or r.get("equipment")
        )
        if not aid:
            continue
        rated_kva = _num(r.get("onanrating_kva"))
        rated_mva = rated_kva / 1000 if rated_kva else _num(r.get("rated_mva") or r.get("capacity_mva"))
        rows.append((
            dno, str(aid),
            r.get("sitedesc") or r.get("site_name") or r.get("substation_name"),
            _num(r.get("primary_winding_voltage") or r.get("primary_voltage_kv") or r.get("hv_voltage_kv")),
            _num(r.get("secondary_winding_voltage") or r.get("secondary_voltage_kv") or r.get("lv_voltage_kv")),
            rated_mva,
            _num(r.get("peak_demand_mva")),
            _num(r.get("utilisation_pct") or r.get("loading_pct")),
            r.get("rag_status") or r.get("rag"),
            json.dumps(r),
        ))
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO dno_primary_transformers (dno, asset_id, site_name,
                voltage_primary_kv, voltage_secondary_kv, rated_mva, peak_demand_mva,
                utilisation_pct, rag_status, raw, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb, now())
            ON CONFLICT (dno, asset_id) DO UPDATE SET
                site_name = EXCLUDED.site_name,
                peak_demand_mva = EXCLUDED.peak_demand_mva,
                utilisation_pct = EXCLUDED.utilisation_pct,
                rag_status = EXCLUDED.rag_status,
                raw = EXCLUDED.raw, updated_at = now()
            """,
            rows,
        )
    return len(rows)


async def ingest_large_demand_list(pool: asyncpg.Pool, dno: str, records: list[dict]) -> int:
    """Normalise UKPN large demand list records."""
    rows = []
    for r in records:
        name = r.get("anonymised_name")
        if not name:
            continue
        app_date = r.get("application_date")
        if app_date and isinstance(app_date, str):
            try:
                app_date = datetime.fromisoformat(app_date.split("T")[0]).date()
            except Exception:
                app_date = None
        rows.append((
            dno, str(name),
            r.get("licence_area"),
            r.get("grid_supply_point"),
            r.get("demand_technology_type"),
            _num(r.get("required_import_capacity_kva")),
            app_date,
            json.dumps(r),
        ))
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO dno_large_demand_list (dno, anonymised_name, licence_area,
                grid_supply_point, demand_technology_type, required_import_capacity_kva,
                application_date, raw)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
            ON CONFLICT (dno, anonymised_name) DO UPDATE SET
                required_import_capacity_kva = EXCLUDED.required_import_capacity_kva,
                application_date = EXCLUDED.application_date,
                raw = EXCLUDED.raw
            """,
            rows,
        )
    return len(rows)


async def ingest_tabular_generic(pool: asyncpg.Pool, dno: str, dataset_key: str, records: list[dict]) -> int:
    """Fall-back: land raw records into dno_ltds_tabular."""
    rows = [(dno, dataset_key, i, json.dumps(r)) for i, r in enumerate(records)]
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM dno_ltds_tabular WHERE dno = $1 AND dataset_key = $2",
            dno, dataset_key,
        )
        await conn.executemany(
            "INSERT INTO dno_ltds_tabular (dno, dataset_key, row_num, row) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            rows,
        )
    return len(rows)


# ════════════════════════════════════════════════════════════════════════
# Dispatcher — pick the right parser for each dataset
# ════════════════════════════════════════════════════════════════════════

_PARSERS = {
    "grid_primary_sites":   ingest_grid_primary_sites,
    "primary_transformers": ingest_primary_transformers,
    "large_demand_list":    ingest_large_demand_list,
}


async def _ckan_fetch_dataset(
    base_url: str, dataset_id: str, max_csv_rows: int = 20000,
) -> tuple[list[dict], str]:
    """Fetch a CKAN dataset: try package_show → download first CSV resource.

    Works for NESO (api.neso.energy) and other CKAN v3 portals.
    Returns (records, status).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{base_url}/api/3/action/package_show",
                params={"id": dataset_id},
            )
            if r.status_code == 403:
                return [], "forbidden"
            r.raise_for_status()
            pkg = r.json().get("result", {})
            csv_res = next(
                (res for res in pkg.get("resources", [])
                 if (res.get("format") or "").upper() == "CSV" and res.get("url")),
                None,
            )
            if not csv_res:
                return [], "error"
            csv_r = await client.get(csv_res["url"], timeout=120.0, follow_redirects=True)
            csv_r.raise_for_status()
            import csv as _csv, io as _io
            reader = _csv.DictReader(_io.StringIO(csv_r.text))
            rows = []
            for i, row in enumerate(reader):
                if i >= max_csv_rows:
                    break
                rows.append(dict(row))
            return rows, "ok"
    except Exception as e:
        log.warning("ckan fetch %s failed: %s", dataset_id, e)
        return [], "error"


async def ingest_dataset(
    pool: asyncpg.Pool, dno: str, adapter: dict, key: str, dataset_id: str,
) -> dict:
    """Ingest a single dataset from a given DNO / CKAN portal."""
    api_key = _api_key(adapter)
    if not api_key and adapter["api"] == "opendatasoft_v2":
        await _record_datasets_status(pool, dno, key, dataset_id, "skipped_no_key", 0)
        return {"dno": dno, "dataset_key": key, "status": "skipped_no_key"}

    if adapter["api"] == "ckan_v3":
        records, status = await _ckan_fetch_dataset(
            adapter["base_url"], dataset_id, max_csv_rows=20000,
        )
    else:
        records, status = await _ods_fetch_all_records(
            adapter["base_url"], dataset_id, api_key=api_key, max_rows=20000,
        )

    if status == "forbidden":
        await _record_datasets_status(pool, dno, key, dataset_id, "forbidden", 0)
        return {"dno": dno, "dataset_key": key, "status": "forbidden", "rows": 0}
    if status == "error":
        await _record_datasets_status(pool, dno, key, dataset_id, "error", 0)
        return {"dno": dno, "dataset_key": key, "status": "error", "rows": 0}

    parser = _PARSERS.get(key, None)
    if parser is None:
        # Fall-back generic tabular landing
        rows = await ingest_tabular_generic(pool, dno, key, records)
    else:
        rows = await parser(pool, dno, records)

    await _record_datasets_status(pool, dno, key, dataset_id, "ok", rows)
    return {"dno": dno, "dataset_key": key, "status": "ok", "rows": rows}


async def ingest_dno(pool: asyncpg.Pool, dno: str) -> dict:
    """Ingest every dataset for a single DNO."""
    adapter = DNO_ADAPTERS.get(dno)
    if not adapter:
        return {"ok": False, "reason": f"unknown dno {dno}"}

    results: list[dict] = []
    for key, dataset_id in adapter["datasets"].items():
        try:
            r = await ingest_dataset(pool, dno, adapter, key, dataset_id)
            results.append(r)
        except Exception as e:
            log.exception("ingest %s/%s failed", dno, key)
            results.append({"dno": dno, "dataset_key": key, "status": "error", "error": str(e)})
    return {
        "ok": True,
        "dno": dno,
        "has_api_key": _api_key(adapter) is not None,
        "datasets": results,
    }


async def ingest_all_dnos(pool: asyncpg.Pool) -> dict:
    """Ingest every dataset for every DNO with a configured adapter."""
    out = {"ok": True, "dnos": {}}
    for dno in DNO_ADAPTERS:
        try:
            out["dnos"][dno] = await ingest_dno(pool, dno)
        except Exception as e:
            log.exception("ingest_dno %s failed", dno)
            out["dnos"][dno] = {"ok": False, "reason": str(e)}
    return out


# ════════════════════════════════════════════════════════════════════════
# Read-side helpers
# ════════════════════════════════════════════════════════════════════════

async def get_ingest_status(pool: asyncpg.Pool) -> list[dict]:
    """Return the per-DNO ingest status for the Grid Graph Resources tab."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM dno_datasets ORDER BY dno, dataset_key"
        )
    return [dict(r) for r in rows]


async def get_large_demand_geojson(pool: asyncpg.Pool, dno: str | None = None) -> dict:
    """Return the large demand list as a GeoJSON FeatureCollection — joined to
    GSP coordinates via existing grid_substations where possible.
    """
    conditions = ["dno = $1"] if dno else []
    params: list[Any] = [dno] if dno else []
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT ldl.*, gs.lat AS gsp_lat, gs.lon AS gsp_lon
        FROM dno_large_demand_list ldl
        LEFT JOIN LATERAL (
            SELECT ST_Y(ST_Transform(geom, 4326)) AS lat,
                   ST_X(ST_Transform(geom, 4326)) AS lon
            FROM grid_substations
            WHERE geom IS NOT NULL
              AND LOWER(REGEXP_REPLACE(name, '[^a-zA-Z0-9]', '', 'g'))
                  = LOWER(REGEXP_REPLACE(ldl.grid_supply_point, '[^a-zA-Z0-9]', '', 'g'))
            ORDER BY voltage_kv DESC NULLS LAST
            LIMIT 1
        ) gs ON TRUE
        {where}
        ORDER BY ldl.required_import_capacity_kva DESC NULLS LAST
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    features = []
    for r in rows:
        if r["gsp_lat"] is None or r["gsp_lon"] is None:
            continue
        mva = float(r["required_import_capacity_kva"] or 0) / 1000
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["gsp_lon"]), float(r["gsp_lat"])]},
            "properties": {
                "dno": r["dno"],
                "anonymised_name": r["anonymised_name"],
                "licence_area": r["licence_area"],
                "grid_supply_point": r["grid_supply_point"],
                "demand_technology_type": r["demand_technology_type"],
                "required_import_mva": round(mva, 2),
                "application_date": str(r["application_date"]) if r["application_date"] else None,
                "colour": _demand_colour(mva),
                "radius": 6 + min(20, mva / 5),
            },
        })
    return {"type": "FeatureCollection", "count": len(features), "features": features}


def _demand_colour(mva: float) -> str:
    """Colour map for large demand projects by size."""
    if mva >= 200: return "#7c3aed"   # hyperscaler
    if mva >= 100: return "#b91c1c"
    if mva >= 50:  return "#f59e0b"
    if mva >= 20:  return "#eab308"
    return "#10b981"


def _num(v: Any) -> float | None:
    """Coerce to float or None."""
    try:
        return float(v) if v not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None
