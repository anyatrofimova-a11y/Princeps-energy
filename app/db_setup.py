"""
db_setup.py — Database DDL and table setup for Princeps.

Extracted from main.py lifespan.  Call ``await setup_database(pool)`` once
at startup after the asyncpg pool is created.
"""

import logging

import asyncpg

from utils.planning_energy import (
    setup_table as planning_setup,
    seed_sample_data as planning_seed,
)
from utils.solar_inventory import setup_inventory_table
from utils.weave_demand import setup_demand_table, seed_demand
from utils.osm_power_infra import setup_tables as osm_power_setup
from utils.nged_cim import setup_tables as nged_setup
from utils.eso_tec import setup_tables as eso_tec_setup
from utils.repd import setup_tables as repd_setup
from utils.legacy_asset_compliance import (
    setup_legacy_table,
    seed_sample_legacy_assets,
)
from utils.infrastructure_retrofit import (
    setup_retrofit_table,
    seed_sample_retrofit_sites,
)
from utils.home_retrofit_engine import (
    setup_home_retrofit_tables,
    seed_exemplar_cases as seed_home_retrofit_cases,
)
from utils.repd_tracker import setup_repd_table
from utils.eso_tec_register import setup_tec_table
from utils.grid_upgrade_tracker import setup_grid_upgrade_tables
from utils.ofgem_rag import setup_rag_tables
from utils.alert_engine import setup_notifications_table
from utils.grid_data_platform import UK_SUBSTATIONS
from utils.cim_asset_store import setup_tables as cim_asset_setup
from utils.dc_infra_ingester import setup_dc_tables

log = logging.getLogger("princeps")


async def setup_database(pool: asyncpg.Pool) -> None:
    """Run all CREATE TABLE / index DDL and seed fixed reference data."""

    async with pool.acquire() as conn:
        # ── Planning applications + sample energy data ────────────────────
        await planning_setup(conn)
        await planning_seed(conn)

        # ── Solar inventory ───────────────────────────────────────────────
        await setup_inventory_table(conn)

        # ── Weave demand ──────────────────────────────────────────────────
        await setup_demand_table(conn)
        await seed_demand(conn)

        # ── OSM power infrastructure ──────────────────────────────────────
        await osm_power_setup(conn)

        # ── NGED CIM ─────────────────────────────────────────────────────
        await nged_setup(conn)

        # ── ESO TEC + REPD ────────────────────────────────────────────────
        await eso_tec_setup(conn)
        await repd_setup(conn)

        # ── Site layouts ──────────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS site_layouts (
                parcel_id UUID PRIMARY KEY,
                layout_data JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── GeeFlow extractions ───────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS geeflow_extractions (
                extraction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parcel_id     UUID REFERENCES parcels(parcel_id) ON DELETE SET NULL,
                lat           DOUBLE PRECISION NOT NULL,
                lon           DOUBLE PRECISION NOT NULL,
                radius_km     DOUBLE PRECISION DEFAULT 5.0,
                mode          TEXT NOT NULL,
                result_data   JSONB NOT NULL,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                geometry      GEOMETRY(Polygon, 4326)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_geeflow_geom
            ON geeflow_extractions USING GIST (geometry)
        """)

        # ── pgvector extension (optional — gracefully degrade) ────────────
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            log.info("pgvector extension enabled")
            # Add embedding columns (safe to run repeatedly — IF NOT EXISTS via DO block)
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                   WHERE table_name='geeflow_extractions' AND column_name='embedding') THEN
                        ALTER TABLE geeflow_extractions ADD COLUMN embedding vector(768);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                                   WHERE table_name='geeflow_extractions' AND column_name='fingerprint') THEN
                        ALTER TABLE geeflow_extractions ADD COLUMN fingerprint vector(1809);
                    END IF;
                END $$;
            """)
            # IVFFlat indexes for cosine similarity KNN
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_geeflow_embedding
                    ON geeflow_extractions USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_geeflow_fingerprint
                    ON geeflow_extractions USING ivfflat (fingerprint vector_cosine_ops) WITH (lists = 10)
                """)
            except Exception:
                log.info("IVFFlat indexes deferred — need more rows")
        except Exception as e:
            log.warning("pgvector not available (install with: brew install pgvector): %s", e)

        # ── Vision AI analyses ────────────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vision_analyses (
                analysis_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                parcel_id        UUID REFERENCES parcels(parcel_id) ON DELETE SET NULL,
                upload_id        TEXT,
                lat              DOUBLE PRECISION,
                lon              DOUBLE PRECISION,
                image_type       TEXT,
                source           TEXT,
                analysis_tier    TEXT,
                suitability_score INTEGER,
                verdict          TEXT,
                findings         JSONB,
                domain_contributions JSONB,
                deep_results     JSONB,
                image_metadata   JSONB,
                created_at       TIMESTAMPTZ DEFAULT NOW(),
                geometry         GEOMETRY(Point, 4326)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vision_geom
            ON vision_analyses USING GIST (geometry)
        """)

        # ── Grid topology models registry ─────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS grid_models (
                model_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                source TEXT DEFAULT 'nged_cim',
                neo4j_label_prefix TEXT,
                asset_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ── Legacy asset planning & compliance ────────────────────────────
        await setup_legacy_table(conn)
        await seed_sample_legacy_assets(conn)

        # ── Infrastructure retrofit & energy storage ──────────────────────
        await setup_retrofit_table(conn)
        await seed_sample_retrofit_sites(conn)

        # ── Home retrofit CBR ─────────────────────────────────────────────
        await setup_home_retrofit_tables(conn)
        await seed_home_retrofit_cases(conn)

        # ── Regulatory intelligence ───────────────────────────────────────
        await setup_repd_table(conn)
        await setup_tec_table(conn)
        await setup_grid_upgrade_tables(conn)

        try:
            await setup_rag_tables(conn)
        except Exception as e:
            log.warning("RAG tables setup skipped — pgvector may not be installed: %s", e)

        # ── CIM Asset Library ────────────────────────────────────────────
        await cim_asset_setup(conn)

        # ── Data centre infrastructure ──────────────────────────────────
        await setup_dc_tables(conn)

        # ── Notifications / alerts ────────────────────────────────────────
        await setup_notifications_table(conn)

        # ── Seed dno_substations from UK_SUBSTATIONS if empty ─────────────
        sub_count = await conn.fetchval("SELECT count(*) FROM dno_substations")
        if sub_count == 0:
            log.info("Seeding dno_substations with %d entries from UK_SUBSTATIONS", len(UK_SUBSTATIONS))
            for s in UK_SUBSTATIONS:
                await conn.execute(
                    """
                    INSERT INTO dno_substations (sub_id, name, capacity_kw, source, geometry)
                    VALUES ($1, $2, $3, $4,
                            ST_Transform(ST_SetSRID(ST_MakePoint($5, $6), 4326), 27700))
                    ON CONFLICT (sub_id) DO NOTHING
                    """,
                    s["id"], s["site_name"],
                    float(s.get("demand_mw_winter", 0)) * 1000,  # MW -> kW
                    s.get("licence_area", "DNO"),
                    s["lon"], s["lat"],
                )
            log.info("dno_substations seeded — running nearest-substation update on existing parcels")
            await conn.execute("""
                WITH nearest AS (
                    SELECT p.parcel_id, s.sub_id, s.capacity_kw,
                           ST_Distance(p.centroid, s.geometry) AS dist_m
                    FROM parcels p
                    JOIN LATERAL (
                        SELECT sub_id, capacity_kw, geometry
                        FROM dno_substations
                        ORDER BY p.centroid <-> geometry
                        LIMIT 1
                    ) s ON true
                    WHERE p.centroid IS NOT NULL
                )
                UPDATE parcels
                SET nearest_substation_id   = n.sub_id,
                    distance_to_sub_km      = n.dist_m / 1000.0,
                    nearest_sub_capacity_kw = n.capacity_kw
                FROM nearest n
                WHERE parcels.parcel_id = n.parcel_id
            """)

    log.info("Database setup complete")
