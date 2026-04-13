#!/usr/bin/env python3
"""UKPN Data Ingester — ingest all priority UKPN datasets via OpenDataSoft API."""

import asyncio
import json
import logging
import os
import sys

import httpx
import asyncpg

log = logging.getLogger(__name__)

API_KEY = os.environ.get("UKPN_ODS_APIKEY", "4b75b72db09dc599549bbd261035f40d70eb70df18e9f4c92adf0b91")
BASE = "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets"
DB_URL = "postgresql://localhost:5432/feasibly"


async def fetch_all_records(client, dataset_id, limit=100):
    """Fetch all records from an ODS dataset with pagination."""
    records = []
    offset = 0
    while True:
        url = f"{BASE}/{dataset_id}/records?limit={limit}&offset={offset}&apikey={API_KEY}"
        r = await client.get(url, timeout=30)
        if r.status_code != 200:
            log.warning("[%s] HTTP %d at offset %d", dataset_id, r.status_code, offset)
            break
        data = r.json()
        batch = data.get("results", [])
        if not batch:
            break
        records.extend(batch)
        total = data.get("total_count", 0)
        offset += limit
        log.info("[%s] Fetched %d/%d", dataset_id, len(records), total)
        if offset >= total:
            break
    return records


async def ingest_grid_primary_sites(pool, client):
    """Ingest UKPN Grid and Primary Sites → grid_substations."""
    log.info("=== Ingesting UKPN Grid & Primary Sites ===")
    records = await fetch_all_records(client, "grid-and-primary-sites")
    log.info("Fetched %d UKPN substations", len(records))

    async with pool.acquire() as conn:
        inserted = 0
        for r in records:
            geo = r.get("spatial_coordinates") or r.get("geo_point_2d") or r.get("geo_shape", {}).get("geometry", {})
            if not geo:
                continue
            lat = geo.get("lat") or (geo.get("coordinates", [None, None])[1])
            lon = geo.get("lon") or (geo.get("coordinates", [None, None])[0])
            if not lat or not lon:
                continue

            name = r.get("sitename", "Unknown")
            ext_id = f"ukpn-{r.get('sitefunctionallocation', name)}"
            voltage = r.get("sitevoltage")
            site_type = r.get("sitetype", "")
            demand_summer = r.get("maxdemandsummer")
            demand_winter = r.get("maxdemandwinter")
            trans_summer = r.get("transratingsummer")
            trans_winter = r.get("transratingwinter")
            demand_mw = max(demand_summer or 0, demand_winter or 0) if (demand_summer or demand_winter) else None
            trans_mva = max(trans_summer or 0, trans_winter or 0) if (trans_summer or trans_winter) else None
            postcode = r.get("postcode")
            town = r.get("towncity")
            county = r.get("county")
            region = r.get("licencearea")

            try:
                await conn.execute("""
                    INSERT INTO grid_substations (external_id, name, dno, region, voltage_kv, site_type,
                        demand_mw, transformer_rating_mva, postcode, town, county, geom, raw_data)
                    VALUES ($1, $2, 'ukpn', $3, $4, $5, $6, $7, $8, $9, $10,
                        ST_Transform(ST_SetSRID(ST_MakePoint($11, $12), 4326), 27700), $13)
                    ON CONFLICT (external_id) DO UPDATE SET
                        name = EXCLUDED.name, voltage_kv = EXCLUDED.voltage_kv,
                        demand_mw = EXCLUDED.demand_mw, transformer_rating_mva = EXCLUDED.transformer_rating_mva,
                        raw_data = EXCLUDED.raw_data, updated_at = NOW()
                """, ext_id, name, region, voltage, site_type, demand_mw, trans_mva,
                    postcode, town, county, lon, lat, json.dumps(r))
                inserted += 1
            except asyncpg.exceptions.UniqueViolationError:
                pass
            except Exception as e:
                # Try without ON CONFLICT if no unique constraint
                try:
                    await conn.execute("""
                        INSERT INTO grid_substations (external_id, name, dno, region, voltage_kv, site_type,
                            demand_mw, transformer_rating_mva, postcode, town, county, geom, raw_data)
                        VALUES ($1, $2, 'ukpn', $3, $4, $5, $6, $7, $8, $9, $10,
                            ST_Transform(ST_SetSRID(ST_MakePoint($11, $12), 4326), 27700), $13)
                    """, ext_id, name, region, voltage, site_type, demand_mw, trans_mva,
                        postcode, town, county, lon, lat, json.dumps(r))
                    inserted += 1
                except Exception as e2:
                    log.warning("Failed %s: %s", name, e2)

    log.info("UKPN Grid & Primary: inserted %d of %d", inserted, len(records))
    return inserted


async def ingest_headroom(pool, client):
    """Ingest DFES Network Headroom Report."""
    log.info("=== Ingesting UKPN DFES Headroom ===")
    records = await fetch_all_records(client, "dfes-network-headroom-report")
    log.info("Fetched %d headroom records", len(records))

    # Update existing substations with headroom data
    async with pool.acquire() as conn:
        updated = 0
        for r in records:
            site_name = r.get("site_name") or r.get("sitename") or r.get("name")
            if not site_name:
                continue
            demand_headroom = r.get("demand_headroom_mw") or r.get("demand_headroom")
            gen_headroom = r.get("generation_headroom_mw") or r.get("generation_headroom")
            if demand_headroom is None and gen_headroom is None:
                continue
            try:
                result = await conn.execute("""
                    UPDATE grid_substations SET
                        demand_headroom_mw = COALESCE($1, demand_headroom_mw),
                        gen_headroom_mw = COALESCE($2, gen_headroom_mw),
                        updated_at = NOW()
                    WHERE dno = 'ukpn' AND name ILIKE $3
                """, demand_headroom, gen_headroom, f"%{site_name}%")
                if "UPDATE 1" in result:
                    updated += 1
            except Exception:
                pass
    log.info("UKPN Headroom: updated %d substations", updated)
    return updated


async def ingest_ecr(pool, client):
    """Ingest Embedded Capacity Register (≥1MW)."""
    log.info("=== Ingesting UKPN ECR ===")
    records = await fetch_all_records(client, "ukpn-embedded-capacity-register")
    log.info("Fetched %d ECR records", len(records))

    async with pool.acquire() as conn:
        # Ensure grid_ecr table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ukpn_ecr (
                id SERIAL PRIMARY KEY,
                site_name TEXT,
                technology TEXT,
                installed_capacity_mw FLOAT,
                export_capacity_mw FLOAT,
                connection_status TEXT,
                connection_date DATE,
                geom geometry(Point, 27700),
                raw_data JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        inserted = 0
        for r in records:
            geo = r.get("spatial_coordinates") or r.get("geo_point_2d") or r.get("geo_shape", {}).get("geometry", {})
            if not geo:
                continue
            lat = geo.get("lat") or (geo.get("coordinates", [None, None])[1])
            lon = geo.get("lon") or (geo.get("coordinates", [None, None])[0])
            if not lat or not lon:
                continue
            try:
                await conn.execute("""
                    INSERT INTO ukpn_ecr (site_name, technology, installed_capacity_mw, export_capacity_mw,
                        connection_status, geom, raw_data)
                    VALUES ($1, $2, $3, $4, $5, ST_Transform(ST_SetSRID(ST_MakePoint($6, $7), 4326), 27700), $8)
                """, r.get("site_name", r.get("name", "")),
                    r.get("technology_type", r.get("technology", "")),
                    r.get("installed_capacity_mw", r.get("installed_generation_capacity_mw")),
                    r.get("export_capacity_mw"),
                    r.get("connection_status", r.get("status", "")),
                    lon, lat, json.dumps(r))
                inserted += 1
            except Exception as e:
                log.warning("ECR insert failed: %s", e)
    log.info("UKPN ECR: inserted %d", inserted)
    return inserted


async def ingest_dc_by_la(pool, client):
    """Ingest Data Centres by Local Authority."""
    log.info("=== Ingesting UKPN Data Centres by LA ===")
    records = await fetch_all_records(client, "data-centres-by-local-authority")
    log.info("Fetched %d DC records", len(records))

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ukpn_data_centres (
                id SERIAL PRIMARY KEY,
                local_authority TEXT,
                local_authority_code TEXT,
                operational_capacity_mw FLOAT,
                pipeline_capacity_mw FLOAT,
                total_capacity_mw FLOAT,
                raw_data JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        for r in records:
            try:
                await conn.execute("""
                    INSERT INTO ukpn_data_centres (local_authority, local_authority_code,
                        operational_capacity_mw, pipeline_capacity_mw, total_capacity_mw, raw_data)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, r.get("local_authority_district", r.get("local_authority", "")),
                    r.get("local_authority_code", ""),
                    r.get("operational_capacity_mw", r.get("operational_mw")),
                    r.get("pipeline_capacity_mw", r.get("pipeline_mw")),
                    r.get("total_capacity_mw", r.get("total_mw")),
                    json.dumps(r))
            except Exception as e:
                log.warning("DC insert failed: %s", e)
    log.info("UKPN DCs by LA: inserted %d", len(records))


async def ingest_gsp_overview(pool, client):
    """Ingest Grid Supply Points Overview."""
    log.info("=== Ingesting UKPN GSP Overview ===")
    records = await fetch_all_records(client, "ukpn-grid-supply-points-overview")
    log.info("Fetched %d GSP records", len(records))
    # Store as raw JSONB for now — rich capacity data
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ukpn_gsp_overview (
                id SERIAL PRIMARY KEY,
                gsp_name TEXT,
                raw_data JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        for r in records:
            try:
                await conn.execute("INSERT INTO ukpn_gsp_overview (gsp_name, raw_data) VALUES ($1, $2)",
                    r.get("gsp_name", r.get("name", str(r)[:100])), json.dumps(r))
            except Exception:
                pass
    log.info("UKPN GSP Overview: inserted %d", len(records))


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=3)

    async with httpx.AsyncClient() as client:
        results = {}
        results["grid_primary"] = await ingest_grid_primary_sites(pool, client)
        results["headroom"] = await ingest_headroom(pool, client)
        results["ecr"] = await ingest_ecr(pool, client)
        results["dc_by_la"] = await ingest_dc_by_la(pool, client)
        results["gsp_overview"] = await ingest_gsp_overview(pool, client)

    # Final count
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM grid_substations")
        ukpn = await conn.fetchval("SELECT COUNT(*) FROM grid_substations WHERE dno = 'ukpn'")
        log.info("=== DONE === UKPN: %d, Total substations: %d", ukpn, total)

    await pool.close()
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
