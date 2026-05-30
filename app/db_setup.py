"""
db_setup.py — Database DDL and table setup for Princeps.

Extracted from main.py lifespan.  Call ``await setup_database(pool)`` once
at startup after the asyncpg pool is created.
"""

import logging
import os

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

        # ── 0012 EA Flood Map + 0013 LCCC/safeguarding + 0014 Nature &
        # ── Heritage + 0015 Constraint layers (CAA airspace buffers, listed
        # ── buildings, Crown Estate, Ofcom telecom, marine plans). All
        # ── idempotent with IF NOT EXISTS. Order matters: 0015 creates
        # ── views that depend on ``mod_safeguarding_zones`` (0013) and
        # ── ``nhle_heritage_entries`` (0014), so 0015 runs last.
        for _mig in (
            "0012_ea_data_layers.sql",
            "0013_lccc_safeguarding_schema.sql",
            "0014_nature_heritage_schema.sql",
            "0015_constraint_layers_schema.sql",
        ):
            _path = pathlib.Path(__file__).parent / "migrations" / _mig
            if _path.exists():
                try:
                    await conn.execute(_path.read_text())
                    log.info("Applied %s", _mig)
                except Exception:
                    log.exception("%s failed — related datasets may be degraded", _mig)

        # ── 0017 DNO engagement workflow (Task #20) ───────────────────────
        # Tracks per-project DNO pack versions + their structured responses.
        # Fully idempotent (CREATE TABLE IF NOT EXISTS + DROP/CREATE TRIGGER).
        _dno_eng_migration = pathlib.Path(__file__).parent / "migrations" / "0017_dno_engagement_workflow.sql"
        if _dno_eng_migration.exists():
            try:
                await conn.execute(_dno_eng_migration.read_text())
                log.info("Applied 0017_dno_engagement_workflow.sql")
            except Exception:
                log.exception(
                    "0017_dno_engagement_workflow.sql failed — DNO engagement "
                    "workflow may be degraded"
                )

        # ── 0018 UK N-1 Contingency Map schema ────────────────────────────
        # Manufactured dataset (`uk-n1-contingency-map`) produced by
        # `utils/n1_contingency/batch_runner.py`. Fully idempotent.
        _n1_migration = pathlib.Path(__file__).parent / "migrations" / "0018_n1_contingency_schema.sql"
        if _n1_migration.exists():
            try:
                _has_n1 = await conn.fetchval(
                    "SELECT to_regclass('public.n1_contingency_map') IS NOT NULL"
                )
                if not _has_n1:
                    await conn.execute(_n1_migration.read_text())
                    log.info("Applied 0018_n1_contingency_schema.sql")
                else:
                    # Apply anyway in case indexes / runs-table were added later —
                    # every statement is IF NOT EXISTS so this is a no-op on warm
                    # starts apart from catalog lookups.
                    await conn.execute(_n1_migration.read_text())
            except Exception:
                log.exception(
                    "0018_n1_contingency_schema.sql failed — UK N-1 Contingency "
                    "Map dataset may be degraded"
                )

        # Seed the `uk-n1-contingency-map` entry in data_subscriptions so
        # the Datasets registry UI lights up even before the batch runs.
        try:
            from app.seed.n1_datasets import seed_if_table_present as _seed_n1
            await _seed_n1(conn)
        except Exception:
            log.exception("N-1 dataset seed failed — dataset row may be missing")

        # ── BOT-DQ root migrations (2026-04-21 c + d) ─────────────────────
        # c: Dedupe the pre-existing "Thames BESS Phase 1" duplicate row.
        # d: Seed demo dockets + project_docket_pins so Intelligence panel
        #    list_dockets(project_id=...) returns ≥3 pins per demo project.
        # Both are fully idempotent (EXISTS guards + ON CONFLICT DO NOTHING)
        # and live in the repo-root `migrations/` dir alongside 2026-04-21b.
        # Applied AFTER the main seed path so the keeper UUIDs exist.
        _repo_root_migrations_dir = pathlib.Path(__file__).parent.parent / "migrations"
        for _mig_name in (
            "2026_04_21c_dedupe_thames_bess.sql",
            "2026_04_21d_seed_docket_pins.sql",
            # BOT-DD: REPD bulk-importer reingest dedupe + regression guard.
            # `e` must run BEFORE `f` — `f` installs a partial UNIQUE INDEX
            # that the pre-dedupe state would violate.
            "2026_04_21e_repd_dedupe.sql",
            "2026_04_21f_repd_unique_constraint.sql",
        ):
            _path = _repo_root_migrations_dir / _mig_name
            if _path.exists():
                try:
                    await conn.execute(_path.read_text())
                    log.info("Applied %s", _mig_name)
                except Exception:
                    log.exception(
                        "%s failed — demo project dockets / dedupe may be degraded",
                        _mig_name,
                    )

        # ── Planning applications + sample energy data ────────────────────
        await planning_setup(conn)
        await planning_seed(conn)

        # ── Solar inventory ───────────────────────────────────────────────
        await setup_inventory_table(conn)

        # ── Weave demand ──────────────────────────────────────────────────
        await setup_demand_table(conn)
        if os.environ.get("WEAVE_SEED_ENABLED") == "1":
            await seed_demand(conn)
        else:
            log.info("Weave demand seed skipped (set WEAVE_SEED_ENABLED=1 to enable; large parquet pull)")

        # ── OSM power infrastructure ──────────────────────────────────────
        await osm_power_setup(conn)

        # ── OSM power SQL helpers (task #16) ─────────────────────────────
        # Ports convert_voltage / convert_power / first_semi / nth_semi /
        # power_line_angle from upstream OpenInfraMap (BSD-3-Clause). Runs
        # AFTER osm_power_setup() because power_line_angle references the
        # osm_power_line table.
        import pathlib as _pl_oim
        _osm_helpers_sql = (
            _pl_oim.Path(__file__).parent.parent / "sql" / "migrate_osm_power_helpers.sql"
        )
        if _osm_helpers_sql.exists():
            try:
                await conn.execute(_osm_helpers_sql.read_text())
                log.info("Applied migrate_osm_power_helpers.sql (OIM port)")
            except Exception:
                log.exception(
                    "migrate_osm_power_helpers.sql failed — OIM-style queries may be degraded"
                )

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
            # Headline pin: 51.5179, 0.5045 — CORYTON GRID 132/33KV (UKPN-EPN,
            # external_id ukpn-EPN-S0000000D7027). Real 132/33kV grid substation
            # at Shell Haven / Coryton industrial complex, Thurrock (SS17).
            # Verified via grid_substations table 2026-04-21.
            _bess_id = await conn.fetchval("""
                INSERT INTO projects (portfolio_id, name, description, technology, capacity_mw,
                                      stage, verdict, lat, lon, metadata)
                VALUES ($1, 'Thames BESS Phase 1',
                        '50 MW / 100 MWh grid-scale battery — co-located with CORYTON GRID 132/33kV substation (UKPN EPN), Shell Haven / London Gateway Thames-estuary brownfield cluster.',
                        'bess', 50.0, 'prospect', 'GO', 51.5179, 0.5045,
                        '{"tech":"bess","energy_mwh":100,"duration_h":2,"chemistry":"LFP",
                          "anchor_source":"grid_substations:ukpn-EPN-S0000000D7027",
                          "poc_substation_external_id":"ukpn-EPN-S0000000D7027",
                          "poc_substation_name":"Coryton Grid 132/33kV","poc_voltage_kv":132,
                          "poc_dno":"UKPN EPN","poc_distance_km":0.4,
                          "firm_headroom_mw":42,"gen_headroom_mw":42,"demand_headroom_mw":36,
                          "queue_depth":9,"queue_mw":185,"cccm_zone":"Z5 (London)",
                          "ltds_citation":"UKPN EPN LTDS 2024 Coryton 132/33kV Grid (2x47.2 MVA SGT)",
                          "transformer_rating_mva":47.2}'::jsonb)
                RETURNING project_id
            """, _pf_id)
            _bess_sites = [
                # 51.5207, 0.2042 — Rainham Substation 33kV (OSM osm-844794264).
                # Real operational substation in Rainham (Havering, RM13).
                ('Rainham substation adjacent', 51.5207, 0.2042, 50.0, 82, 88, 71, 78, 65, 42.5, 'GO', True),
                # 51.5192, 0.1143 — Barking Riverside 132kV substation (OSM osm-1021376264).
                # Real operational UKPN GSP feeding Dagenham Dock / Thames cluster.
                ('Dagenham / Barking Riverside 132kV', 51.5192, 0.1143, 50.0, 78, 86, 68, 62, 72, 45.1, 'GO', False),
                # 51.4677, 0.3566 — DOCK ROAD TILBURY 33kV (UKPN-EPN,
                # external_id ukpn-EPN-S0000000G7223). Real substation on former
                # Tilbury A / Tilbury B brownfield, Port of Tilbury (RM18).
                ('Tilbury port brownfield',   51.4677, 0.3566, 50.0, 74, 82, 45, 58, 80, 48.3, 'CAUTION', False),
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
            # Headline pin: 51.5239, -0.6269 — Slough Heat & Power Station
            # (REPD 4699, 49.9 MW, Under Construction). Real operational/consented
            # energy site on Slough Trading Estate with existing 132kV grid connection.
            # Verified via repd_projects 2026-04-21.
            # Note: repd_id is kept in metadata only (not on projects.repd_id)
            # because repd_projects is independently ingested and the Slough
            # Heat & Power REPD row (4699) gets its own project row — UNIQUE
            # constraint on projects.repd_id would collide on fresh DBs.
            _dc_id = await conn.fetchval("""
                INSERT INTO projects (portfolio_id, name, description, technology, capacity_mw,
                                      stage, verdict, lat, lon, blocker, metadata)
                VALUES ($1, 'Slough Hyperscale DC',
                        '40 MW IT-load data centre adjacent to Slough Heat & Power Station (REPD 4699, 49.9 MW under construction), Slough Trading Estate. Iver 132kV GSP 2.2 km north.',
                        'dc', 40.0, 'screened', 'CAUTION', 51.5239, -0.6269,
                        'Iver 132kV firm headroom 72 MW covers 40 MW ask but ECR queue of 340 MW creates Gate 2 priority risk — request CCCM non-firm allocation',
                        '{"tech":"dc","it_load_mw":40,"pue_target":1.2,"grid_headroom_mw":15,"tier":"III",
                          "anchor_source":"repd_projects:4699 Slough Heat & Power Station","anchor_repd_id":"4699",
                          "poc_substation_name":"Iver 132kV","poc_voltage_kv":132,
                          "poc_dno":"SSEN","poc_distance_km":2.2,
                          "firm_headroom_mw":72,"gen_headroom_mw":45,"demand_headroom_mw":72,
                          "queue_depth":7,"queue_mw":340,"cccm_zone":"Z10 (Thames Valley)",
                          "ltds_citation":"SSEN SEPD LTDS 2024 Iver 132kV GSP (NGET-owned 400/132kV SGT 2x240 MVA)"}'::jsonb)
                RETURNING project_id
            """, _pf_id)
            _dc_sites = [
                # 51.5244, -0.6277 — Fibrepower Slough (REPD 831, 50 MW Operational).
                # Real operational biomass CHP on Slough Trading Estate, existing 33/132kV connection.
                ('Fibrepower / Slough Trading Estate', 51.5244, -0.6277, 40.0, 55, 72, 78, 82, 70, 68.2, 'GO', True),
                # 51.5417, -0.4973 — Iver Substation 132kV (OSM osm-23232742).
                # Real UKPN/NGET Iver 132kV GSP feeding Slough/west London DC cluster.
                ('Iver 132kV adjacent', 51.5417, -0.4973, 40.0, 58, 90, 62, 68, 74, 62.5, 'GO', False),
                # 51.4880, -0.5320 — Colnbrook & Poyle trading estate (SL3 8QQ,
                # Slough BC). Heathrow-fringe brownfield; Ark Data Centres neighbourhood.
                ('Colnbrook / Poyle DC cluster',   51.4880, -0.5320, 40.0, 52, 38, 48, 55, 74, 75.1, 'NO-GO', False),
            ]
            for nm, lat, lon, cap, rs, gs, ps, ls, ts, lc, vd, pref in _dc_sites:
                await conn.execute("""
                    INSERT INTO project_candidate_sites (project_id, name, lat, lon, capacity_mw,
                                                          scores, lcoe, verdict, is_preferred)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
                """, _dc_id, nm, lat, lon, cap,
                     f'{{"resource":{rs},"grid":{gs},"planning":{ps},"land_use":{ls},"terrain":{ts}}}',
                     lc, vd, pref)

            # ── Additional tech-matched real-anchor demo projects ────────
            # Each anchored to a REAL REPD/TEC record + real POC substation
            # (see migrations/2026_04_21b_real_tech_matched.sql).
            # Fresh DBs get 9 demo projects total: Thames, Slough + 7 below.
            _extra_projects = [
                # Lower Farm Drointon BESS 30MW (REPD 13550 Approved)
                {
                    "name": "Lower Farm Drointon BESS 30MW",
                    "description": "REPD 13550 — Lower Farm, Drointon Lane, Stowe-by-Chartley. 30 MW / 60 MWh co-located BESS + solar (Approved). POC: Rugeley 132kV (NGED) ~10 km south.",
                    "technology": "bess", "capacity_mw": 30.0,
                    "stage": "screened", "verdict": "GO",
                    "lat": 52.8397, "lon": -1.9630,
                    "metadata": {
                        "tech": "bess", "energy_mwh": 60, "duration_h": 2,
                        "anchor_type": "repd_consented", "anchor_repd_id": "13550",
                        "anchor_source": "repd_projects:13550 Lower Farm Drointon BESS 30MW",
                        "poc_substation_external_id": "osm-489819760",
                        "poc_substation_name": "Rugeley 132kV",
                        "poc_voltage_kv": 132, "poc_dno": "NGED",
                        "poc_distance_km": 10.2,
                        "firm_headroom_mw": 50, "gen_headroom_mw": 50, "demand_headroom_mw": 80,
                        "queue_depth": 4, "queue_mw": 140,
                        "cccm_zone": "Z8 (East Midlands)",
                        "ltds_citation": "NGED WMID LTDS 2024 Table 2-3 (Rugeley 132/33kV Grid, 2x240 MVA)",
                    },
                },
                # Culham BESS 500MW (REPD 12968 Approved)
                {
                    "name": "Culham BESS 500MW",
                    "description": "REPD 12968 — Culham Science Centre, Clifton Hampden. 500 MW / 1000 MWh BESS (Approved 2024). POC: Didcot 400kV GSP via Culham 132kV (SSEN SEPD).",
                    "technology": "bess", "capacity_mw": 500.0,
                    "stage": "screened", "verdict": "CAUTION",
                    "lat": 51.6634, "lon": -1.2307,
                    "metadata": {
                        "tech": "bess", "energy_mwh": 1000, "duration_h": 2,
                        "anchor_type": "repd_consented", "anchor_repd_id": "12968",
                        "anchor_source": "repd_projects:12968 Culham Science Centre BESS 500MW",
                        "poc_substation_external_id": "osm-95597604",
                        "poc_substation_name": "Culham / Didcot 400kV GSP",
                        "poc_voltage_kv": 400, "poc_dno": "NGET/SSEN",
                        "poc_distance_km": 0.3,
                        "firm_headroom_mw": 140, "gen_headroom_mw": 140, "demand_headroom_mw": 420,
                        "queue_depth": 9, "queue_mw": 820,
                        "cccm_zone": "Z10 (Thames Valley)",
                        "ltds_citation": "SSEN SEPD LTDS 2024 Appendix B Didcot GSP (2x1000 MVA SGT)",
                    },
                },
                # Hinkley Point C Extension (TEC 1026, EDF HPC)
                {
                    "name": "Hinkley Point C Extension",
                    "description": "TEC 1026 — EDF HPC 3260 MW nuclear Under Construction. Extension scope: 100 MW site BESS for black-start. POC: Hinkley Point 400kV (NGET).",
                    "technology": "bess", "capacity_mw": 100.0,
                    "stage": "prospect", "verdict": "GO",
                    "lat": 51.2083, "lon": -3.1322,
                    "metadata": {
                        "tech": "bess", "energy_mwh": 200, "duration_h": 2,
                        "anchor_type": "tec_register", "anchor_tec_id": "1026",
                        "anchor_source": "eso_tec_register:1026 Hinkley Point 400kV (EDF HPC 3260MW)",
                        "poc_substation_external_id": "osm-292371992",
                        "poc_substation_name": "Hinkley Point 400kV",
                        "poc_voltage_kv": 400, "poc_dno": "NGET",
                        "poc_distance_km": 0.2,
                        "firm_headroom_mw": 80, "gen_headroom_mw": 80, "demand_headroom_mw": 120,
                        "queue_depth": 1, "queue_mw": 3260,
                        "cccm_zone": "Z13 (South West)",
                        "ltds_citation": "NGET ETYS 2024 Ch 6 Hinkley Connection Project (400kV OHL to Seabank)",
                    },
                },
                # Necton BESS & Norfolk Vanguard Landfall (TEC 2223 / 1552)
                {
                    "name": "Necton BESS & Norfolk Vanguard Landfall",
                    "description": "TEC 2223 (Zenobe BESS 100MW) + Norfolk Vanguard/Boreas 5560 MW offshore wind, all connecting at Necton 400kV. Co-located onshore BESS scope 100 MW / 200 MWh.",
                    "technology": "bess", "capacity_mw": 100.0,
                    "stage": "prospect", "verdict": "CAUTION",
                    "lat": 52.6611, "lon": 0.7938,
                    "metadata": {
                        "tech": "bess_wind", "energy_mwh": 200, "duration_h": 2,
                        "anchor_type": "tec_register", "anchor_tec_id": "2223",
                        "anchor_source": "eso_tec_register:2223 Necton 400kV Zenobe BESS (+ Norfolk Vanguard/Boreas 5560MW wind)",
                        "poc_substation_external_id": "osm-104372210",
                        "poc_substation_name": "Necton 400kV",
                        "poc_voltage_kv": 400, "poc_dno": "NGET",
                        "poc_distance_km": 6.5,
                        "firm_headroom_mw": 60, "gen_headroom_mw": 60, "demand_headroom_mw": 180,
                        "queue_depth": 11, "queue_mw": 5760,
                        "cccm_zone": "Z6 (East)",
                        "ltds_citation": "NGET ETYS 2024 Ch 5 East Anglia offshore connections (Necton 400/275kV new build 2023)",
                    },
                },
                # Pembroke Power Station BESS 350MW (REPD 14913 Approved)
                {
                    "name": "Pembroke Power Station BESS 350MW",
                    "description": "REPD 14913 — Pembroke Power Station, Pwllcrochan. 350 MW / 700 MWh BESS (Approved). POC: Penfro Converter Station 400kV (NGED W&W).",
                    "technology": "bess", "capacity_mw": 350.0,
                    "stage": "screened", "verdict": "CAUTION",
                    "lat": 51.6818, "lon": -4.9950,
                    "metadata": {
                        "tech": "bess", "energy_mwh": 700, "duration_h": 2,
                        "anchor_type": "repd_consented", "anchor_repd_id": "14913",
                        "anchor_source": "repd_projects:14913 Pembroke Power Station BESS",
                        "poc_substation_id": 12812,
                        "poc_substation_external_id": "1151065330",
                        "poc_substation_name": "Penfro Converter Station 400kV",
                        "poc_voltage_kv": 400, "poc_dno": "NGED",
                        "poc_distance_km": 0.8,
                        "firm_headroom_mw": 50, "gen_headroom_mw": 50, "demand_headroom_mw": 80,
                        "queue_depth": 3, "queue_mw": 420,
                        "cccm_zone": "Z14 (South Wales)",
                        "ltds_citation": "NGED Wales & West LTDS 2024 Penfro 400kV (ex-Pembroke CCGT terminal, decommissioned 2022)",
                    },
                },
                # Copper Bottom Solar Farm 30MW (REPD 8349 Approved)
                {
                    "name": "Copper Bottom Solar Farm 30MW",
                    "description": "REPD 8349 — Copper Bottom Solar Farm, Bosprowal Farm, Camborne, Cornwall. 30 MW solar PV (Approved). POC: Camborne 132kV (NGED SW).",
                    "technology": "solar", "capacity_mw": 30.0,
                    "stage": "screened", "verdict": "CAUTION",
                    "lat": 50.1909, "lon": -5.3257,
                    "metadata": {
                        "tech": "solar",
                        "anchor_type": "repd_consented", "anchor_repd_id": "8349",
                        "anchor_source": "repd_projects:8349 Copper Bottom Solar Farm",
                        "poc_substation_external_id": "osm-143569365",
                        "poc_substation_name": "Camborne 132kV",
                        "poc_voltage_kv": 132, "poc_dno": "NGED",
                        "poc_distance_km": 3.6,
                        "firm_headroom_mw": 18, "gen_headroom_mw": 18, "demand_headroom_mw": 40,
                        "queue_depth": 6, "queue_mw": 165,
                        "cccm_zone": "Z15 (South West Peninsula)",
                        "ltds_citation": "NGED SW LTDS 2024 Ch 3 Camborne 132/33kV Grid (2x90 MVA)",
                    },
                },
                # Spalding Energy Park BESS 550MW (REPD 10173 Approved)
                {
                    "name": "Spalding Energy Park BESS 550MW",
                    "description": "REPD 10173 — Spalding Energy Park, West Marsh Road. 550 MW / 1100 MWh BESS (Approved) co-located with former Spalding CCGT. POC: Spalding 132kV (NGED EMID).",
                    "technology": "bess", "capacity_mw": 550.0,
                    "stage": "screened", "verdict": "CAUTION",
                    "lat": 52.8039, "lon": -0.1353,
                    "metadata": {
                        "tech": "bess", "energy_mwh": 1100, "duration_h": 2,
                        "anchor_type": "repd_consented", "anchor_repd_id": "10173",
                        "anchor_source": "repd_projects:10173 Spalding Energy Park BESS 550MW",
                        "poc_substation_external_id": "osm-138102199",
                        "poc_substation_name": "Spalding 132kV",
                        "poc_voltage_kv": 132, "poc_dno": "NGED",
                        "poc_distance_km": 0.5,
                        "firm_headroom_mw": 70, "gen_headroom_mw": 70, "demand_headroom_mw": 120,
                        "queue_depth": 8, "queue_mw": 680,
                        "cccm_zone": "Z7 (East Midlands)",
                        "ltds_citation": "NGED EMID LTDS 2024 Spalding 400/132kV GSP (ex-Spalding CCGT 860MW terminal)",
                    },
                },
            ]
            import json as _json
            for p in _extra_projects:
                await conn.execute("""
                    INSERT INTO projects (portfolio_id, name, description, technology, capacity_mw,
                                          stage, verdict, lat, lon, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
                    ON CONFLICT DO NOTHING
                """, _pf_id, p["name"], p["description"], p["technology"], p["capacity_mw"],
                     p["stage"], p["verdict"], p["lat"], p["lon"], _json.dumps(p["metadata"]))

            log.info("Seed complete: 1 portfolio, 9 demo projects (BESS + DC + real REPD/TEC anchors), 6 BESS+DC candidate sites")


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

        # ── planning.data.gov.uk Top-21 OGL v3.0 designations (Task #17) ──
        # MHCLG-maintained: SSSI, AONB, Ancient Woodland, ALC, Flood Zones,
        # Listed Buildings, Scheduled Monuments, etc. Geometry in OSGB36.
        # © Crown copyright · Open Government Licence v3.0
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS planning_designations (
              entity_id           BIGINT PRIMARY KEY,
              dataset             TEXT NOT NULL,
              reference           TEXT,
              name                TEXT,
              organisation_entity TEXT,
              quality             TEXT,
              entry_date          DATE,
              start_date          DATE,
              end_date            DATE,
              attrs               JSONB,
              geom                GEOMETRY(MultiPolygon, 27700) NOT NULL,
              source_url          TEXT,
              last_updated        TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS planning_designations_gix
              ON planning_designations USING GIST(geom);
            CREATE INDEX IF NOT EXISTS planning_designations_ds
              ON planning_designations(dataset);
            CREATE TABLE IF NOT EXISTS planning_dataset_etags (
              dataset      TEXT PRIMARY KEY,
              etag         TEXT,
              last_fetched TIMESTAMPTZ
            );
        """)

        # ── Landowner share tokens (Task #15 Glint UX move) ───────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_shares (
              token         TEXT PRIMARY KEY,
              project_id    UUID NOT NULL,
              summary       TEXT,
              map_png_data  TEXT,
              created_at    TIMESTAMPTZ DEFAULT NOW(),
              expires_at    TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS project_shares_project
              ON project_shares(project_id);
        """)

        # ── Synthetic grids (Task #19 PowerGridSynth vendor) ──────────────
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS synthetic_grids (
              id              BIGSERIAL PRIMARY KEY,
              name            TEXT NOT NULL,
              dno_proxy       TEXT,
              n_buses         INT,
              cgmes_path      TEXT,
              pandapower_json JSONB,
              params          JSONB,
              created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # ── Northern Powergrid Flexibility ontology (Task #27) ────────────
        # 7 OpenDataSoft datasets unified under a single discriminated table.
        # © Northern Powergrid Open Data Licence v1.0
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS npg_flexibility_zones (
              id                       BIGSERIAL PRIMARY KEY,
              dataset                  TEXT NOT NULL,
              external_id              TEXT,
              external_id_key          TEXT GENERATED ALWAYS AS
                                         (COALESCE(external_id, 'unknown')) STORED,
              gsp_name                 TEXT,
              substation_name          TEXT,
              constraint_zone          TEXT,
              postcode                 TEXT,
              licence_area             TEXT,
              region                   TEXT,
              geom                     GEOMETRY(Point, 27700),
              constraint_trigger       TEXT,
              product                  TEXT,
              forecast_year            INT,
              delivery_year            TEXT,
              flexibility_required_mw  NUMERIC,
              flexibility_procured_mw  NUMERIC,
              capacity_mva             NUMERIC,
              voltage_kv               NUMERIC,
              provider                 TEXT,
              attrs                    JSONB,
              ingested_at              TIMESTAMPTZ DEFAULT NOW(),
              UNIQUE (dataset, external_id_key)
            );
            CREATE INDEX IF NOT EXISTS npg_flex_gix ON npg_flexibility_zones USING GIST(geom);
            CREATE INDEX IF NOT EXISTS npg_flex_gsp ON npg_flexibility_zones(gsp_name);
            CREATE INDEX IF NOT EXISTS npg_flex_zone ON npg_flexibility_zones(constraint_zone);
            CREATE INDEX IF NOT EXISTS npg_flex_dataset ON npg_flexibility_zones(dataset);
        """)

    log.info("Database setup complete")
