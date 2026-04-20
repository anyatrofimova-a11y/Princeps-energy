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
        # ── Required extensions (Railway Postgres ships without these) ────
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

        # ── Agent tables (runtime bot infrastructure) ─────────────────────
        import pathlib
        _agent_migration = pathlib.Path(__file__).parent.parent / "sql" / "migrate_agent_tables.sql"
        if _agent_migration.exists():
            try:
                await conn.execute(_agent_migration.read_text())
                log.info("Applied migrate_agent_tables.sql")
            except Exception:
                log.exception("migrate_agent_tables.sql failed — agents may be degraded")

        # ── Phase 7a Intelligence schema (alerts / dockets / data subs) ───
        # Gate on existence of `documents` marker table. The migration file
        # itself is fully idempotent, but skipping avoids catalog churn on
        # warm starts. See app/migrations/README.md for conventions.
        _intel_migration = pathlib.Path(__file__).parent / "migrations" / "0001_intelligence_schema.sql"
        if _intel_migration.exists():
            try:
                _has_documents = await conn.fetchval(
                    "SELECT to_regclass('public.documents') IS NOT NULL"
                )
                if not _has_documents:
                    await conn.execute(_intel_migration.read_text())
                    log.info("Applied 0001_intelligence_schema.sql")
                else:
                    log.info("0001_intelligence_schema.sql already applied — skipping")
            except Exception:
                log.exception(
                    "0001_intelligence_schema.sql failed — alerts/dockets/data subs may be degraded"
                )

        # ── Phase 7a ingestion log (Task #5) ──────────────────────────────
        # Separate from grid_ingestion_log so Intelligence workers can evolve
        # their schema independently. Fully idempotent.
        _intel_log_migration = pathlib.Path(__file__).parent / "migrations" / "0002_intelligence_ingestion_log.sql"
        if _intel_log_migration.exists():
            try:
                await conn.execute(_intel_log_migration.read_text())
                log.info("Applied 0002_intelligence_ingestion_log.sql")
            except Exception:
                log.exception(
                    "0002_intelligence_ingestion_log.sql failed — intelligence workers may not log runs"
                )

        # ── BOT-CC substrate (OS MasterMap / EA LiDAR / OSM pylons) ────────
        # Fully idempotent: all CREATE TABLE/INDEX/MATERIALIZED VIEW IF NOT
        # EXISTS. Safe to re-run on warm starts.
        _substrate_migration = pathlib.Path(__file__).parent / "migrations" / "0009_substrate_schema.sql"
        if _substrate_migration.exists():
            try:
                await conn.execute(_substrate_migration.read_text())
                log.info("Applied 0009_substrate_schema.sql")
            except Exception:
                log.exception(
                    "0009_substrate_schema.sql failed — substrate layers may be degraded"
                )

        # ── 0012 EA Flood Map + 0013 LCCC + safeguarding ──────────────────
        # Applied lazily on startup; idempotent with IF NOT EXISTS.
        for _mig in ("0012_ea_data_layers.sql", "0013_lccc_safeguarding_schema.sql"):
            _path = pathlib.Path(__file__).parent / "migrations" / _mig
            if _path.exists():
                try:
                    await conn.execute(_path.read_text())
                    log.info("Applied %s", _mig)
                except Exception:
                    log.exception("%s failed — related datasets may be degraded", _mig)

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
                parcel_id     UUID,
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

        # ── DC constraint zones ────────────────────────────────────────
        try:
            from utils.dc_constraint_overlay import setup_constraint_tables
            await setup_constraint_tables(conn)
        except Exception as e:
            log.warning("DC constraint tables setup skipped: %s", e)

        # ── Pipeline project management ──────────────────────────────────
        await conn.execute("ALTER TABLE projects ALTER COLUMN user_id DROP NOT NULL")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS technology TEXT")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS capacity_mw DOUBLE PRECISION")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT 'prospect'")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS verdict TEXT")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS blocker TEXT")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS stage_entered_at TIMESTAMPTZ DEFAULT NOW()")
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS repd_id TEXT")
        # UNIQUE so REPD bulk-import can ON CONFLICT safely (counsel's fix —
        # without it, every bulk-import raised InvalidColumnReferenceError).
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'projects_repd_id_unique'
                ) THEN
                    ALTER TABLE projects ADD CONSTRAINT projects_repd_id_unique UNIQUE (repd_id);
                END IF;
            END
            $$
        """)
        await conn.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS tec_id TEXT")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_stage ON projects(stage)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_technology ON projects(technology)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_stage_history (
                history_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id   UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                from_stage   TEXT,
                to_stage     TEXT NOT NULL,
                changed_by   UUID REFERENCES users(user_id),
                notes        TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stage_history_project ON project_stage_history(project_id)"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_documents (
                doc_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id    UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                doc_type      TEXT DEFAULT 'other',
                title         TEXT,
                filename      TEXT NOT NULL,
                content_type  TEXT,
                size_bytes    INTEGER,
                storage_path  TEXT NOT NULL,
                uploaded_by   UUID REFERENCES users(user_id),
                metadata      JSONB DEFAULT '{}',
                created_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_project ON project_documents(project_id)"
        )

        # ── Site boundaries + land options ────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS site_boundaries (
                boundary_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id    UUID REFERENCES projects(project_id) ON DELETE CASCADE,
                parcel_id     UUID,
                name          TEXT,
                boundary_type TEXT DEFAULT 'site',
                geojson       JSONB NOT NULL,
                area_m2       DOUBLE PRECISION,
                area_ha       DOUBLE PRECISION,
                perimeter_m   DOUBLE PRECISION,
                centroid_lat  DOUBLE PRECISION,
                centroid_lon  DOUBLE PRECISION,
                geometry      GEOMETRY(Polygon, 4326),
                metadata      JSONB DEFAULT '{}',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_site_boundaries_project ON site_boundaries(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_site_boundaries_geom ON site_boundaries USING GIST (geometry)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS land_options (
                option_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id    UUID REFERENCES projects(project_id) ON DELETE CASCADE,
                boundary_id   UUID REFERENCES site_boundaries(boundary_id) ON DELETE SET NULL,
                landowner     TEXT,
                landowner_contact TEXT,
                option_type   TEXT DEFAULT 'option',
                status        TEXT DEFAULT 'prospect',
                option_fee_gbp DOUBLE PRECISION,
                annual_rent_gbp_ha DOUBLE PRECISION,
                term_years    INTEGER,
                start_date    DATE,
                expiry_date   DATE,
                break_clause  TEXT,
                solicitor     TEXT,
                title_number  TEXT,
                tenure        TEXT,
                alc_grade     TEXT,
                notes         TEXT,
                documents     JSONB DEFAULT '[]',
                metadata      JSONB DEFAULT '{}',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_land_options_project ON land_options(project_id)")

        # ── Placed assets (site design) ────────────────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS placed_assets (
                asset_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id    UUID REFERENCES projects(project_id) ON DELETE CASCADE,
                parcel_id     UUID,
                asset_type    TEXT NOT NULL,
                label         TEXT,
                capacity_mw   DOUBLE PRECISION DEFAULT 0,
                lat           DOUBLE PRECISION NOT NULL,
                lon           DOUBLE PRECISION NOT NULL,
                rotation_deg  DOUBLE PRECISION DEFAULT 0,
                width_m       DOUBLE PRECISION,
                depth_m       DOUBLE PRECISION,
                height_m      DOUBLE PRECISION,
                color         TEXT,
                bom_item_id   TEXT,
                bom_spec      JSONB DEFAULT '{}',
                validation    JSONB DEFAULT '{}',
                sort_order    INTEGER DEFAULT 0,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_placed_assets_project ON placed_assets(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_placed_assets_parcel ON placed_assets(parcel_id)")

        # ── Notifications / alerts ────────────────────────────────────────
        await setup_notifications_table(conn)

        # ── Portfolios (container for projects) ───────────────────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolios (
                portfolio_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id      UUID,
                name         TEXT NOT NULL,
                description  TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            ALTER TABLE projects
            ADD COLUMN IF NOT EXISTS portfolio_id UUID
            REFERENCES portfolios(portfolio_id) ON DELETE SET NULL
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_portfolio ON projects(portfolio_id)")

        # ── Design layouts (versioned, one candidate → many layouts) ──────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS design_layouts (
                layout_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                candidate_id      UUID REFERENCES project_candidate_sites(candidate_id) ON DELETE CASCADE,
                project_id        UUID REFERENCES projects(project_id) ON DELETE CASCADE,
                parent_layout_id  UUID REFERENCES design_layouts(layout_id) ON DELETE SET NULL,
                workload          TEXT NOT NULL,
                name              TEXT,
                doc               JSONB NOT NULL DEFAULT '{}'::jsonb,
                kpis              JSONB NOT NULL DEFAULT '{}'::jsonb,
                status            TEXT DEFAULT 'draft',
                is_preferred      BOOLEAN DEFAULT false,
                created_by        UUID,
                created_at        TIMESTAMPTZ DEFAULT NOW(),
                updated_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_design_layouts_candidate ON design_layouts(candidate_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_design_layouts_project ON design_layouts(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_design_layouts_parent ON design_layouts(parent_layout_id)")

        # ── Candidate sites for a project (distinct from junction project_sites) ─
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_candidate_sites (
                candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                project_id   UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                name         TEXT,
                lat          DOUBLE PRECISION,
                lon          DOUBLE PRECISION,
                capacity_mw  DOUBLE PRECISION,
                scores       JSONB DEFAULT '{}'::jsonb,
                lcoe         DOUBLE PRECISION,
                verdict      TEXT,
                is_preferred BOOLEAN DEFAULT false,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_sites_project ON project_candidate_sites(project_id)")

        # ── Seed default portfolio + demo BESS + DC projects ──────────────
        _portfolio_count = await conn.fetchval("SELECT count(*) FROM portfolios")
        if _portfolio_count == 0:
            log.info("Seeding default portfolio with BESS + DC demo projects")
            _pf_id = await conn.fetchval("""
                INSERT INTO portfolios (name, description)
                VALUES ('Default Portfolio', 'Demo portfolio with BESS and DC projects')
                RETURNING portfolio_id
            """)
            # BESS project — Thames BESS Phase 1, 50MW/100MWh, London
            _bess_id = await conn.fetchval("""
                INSERT INTO projects (portfolio_id, name, description, technology, capacity_mw,
                                      stage, verdict, lat, lon, metadata)
                VALUES ($1, 'Thames BESS Phase 1',
                        '50 MW / 100 MWh grid-scale battery — Tilbury port brownfield, Thames Estuary.',
                        'bess', 50.0, 'prospect', 'GO', 51.4650, 0.3600,
                        '{"energy_mwh": 100, "duration_h": 2, "chemistry": "LFP"}'::jsonb)
                RETURNING project_id
            """, _pf_id)
            _bess_sites = [
                ('Rainham substation adjacent', 51.5180, 0.1900, 50.0, 82, 88, 71, 78, 65, 42.5, 'GO', True),
                ('Dagenham industrial estate', 51.5400, 0.1500, 50.0, 78, 74, 68, 62, 72, 45.1, 'GO', False),
                ('Tilbury port brownfield',   51.4650, 0.3600, 50.0, 74, 82, 45, 58, 80, 48.3, 'CAUTION', False),
            ]
            for nm, lat, lon, cap, rs, gs, ps, ls, ts, lc, vd, pref in _bess_sites:
                await conn.execute("""
                    INSERT INTO project_candidate_sites (project_id, name, lat, lon, capacity_mw,
                                                          scores, lcoe, verdict, is_preferred)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                """, _bess_id, nm, lat, lon, cap,
                     f'{{"resource":{rs},"grid":{gs},"planning":{ps},"land_use":{ls},"terrain":{ts}}}',
                     lc, vd, pref)
            # DC project — Slough Hyperscale DC, 40MW IT load
            _dc_id = await conn.fetchval("""
                INSERT INTO projects (portfolio_id, name, description, technology, capacity_mw,
                                      stage, verdict, lat, lon, blocker, metadata)
                VALUES ($1, 'Slough Hyperscale DC',
                        '40 MW IT-load data centre, Slough Trading Estate cluster (Equinix LD4/LD5 neighbourhood).',
                        'dc', 40.0, 'screened', 'CAUTION', 51.4974, -0.5683,
                        'Grid headroom marginal at summer peak — requires reinforcement',
                        '{"it_load_mw": 40, "pue_target": 1.2, "grid_headroom_mw": 15, "tier": "III"}'::jsonb)
                RETURNING project_id
            """, _pf_id)
            _dc_sites = [
                ('Slough West industrial', 51.5205, -0.6100, 40.0, 55, 42, 78, 82, 70, 68.2, 'CAUTION', True),
                ('Reading east logistics', 51.4540, -0.9700, 40.0, 58, 68, 72, 75, 68, 62.5, 'GO', False),
                ('Heathrow fringe plot',   51.4700, -0.4500, 40.0, 52, 38, 48, 55, 74, 75.1, 'NO-GO', False),
            ]
            for nm, lat, lon, cap, rs, gs, ps, ls, ts, lc, vd, pref in _dc_sites:
                await conn.execute("""
                    INSERT INTO project_candidate_sites (project_id, name, lat, lon, capacity_mw,
                                                          scores, lcoe, verdict, is_preferred)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                """, _dc_id, nm, lat, lon, cap,
                     f'{{"resource":{rs},"grid":{gs},"planning":{ps},"land_use":{ls},"terrain":{ts}}}',
                     lc, vd, pref)
            log.info("Seed complete: 1 portfolio, 2 projects (BESS + DC), 6 candidate sites")


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
