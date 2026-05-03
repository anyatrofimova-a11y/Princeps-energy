-- =============================================================================
-- 2026_05_02_tenant_rls_tighten.sql
-- -----------------------------------------------------------------------------
-- Princeps — close the GUC-NULL escape hatch left open by
-- 2026_05_01_tenant_rls.sql.
--
-- Day-1 (2026-05-01) shipped permissive policies that pass when the GUC is
-- unset. The 7-critic audit (2026-05-02) flagged this as the #1
-- security finding: "RLS is theatre — passes when the tenant GUC is unset,
-- and zero of the 6 spot-checked routers actually set the GUC."
--
-- This migration tightens every policy so:
--   * If the GUC is SET to a non-empty UUID  → only matching tenant_id rows.
--   * If the GUC is UNSET or empty           → only DEFAULT_TENANT_ID rows.
--
-- Why allow the unset case to read the default tenant rather than fail-closed:
--   The default tenant is the seeded demo / public-data space — every
--   currently-existing row belongs to it (per 2026_05_01 backfill). Any
--   handler that hasn't been migrated to the tenant-scoped pool dependency
--   ``get_tenant_pool`` will continue to see the same data it sees today.
--   When real second-tenant rows arrive, they are isolated. Cross-tenant
--   reads are no longer possible — the audit finding is closed.
--
-- Idempotent: every DROP POLICY IF EXISTS / CREATE POLICY pair re-runs cleanly.
-- =============================================================================


-- The tightened predicate, repeated per table because Postgres policies are
-- per-table objects. The default tenant UUID matches DEFAULT_TENANT_ID in
-- app/middleware/tenant_jwt.py and the seed in 2026_05_01.
--
-- Critical: also ``FORCE ROW LEVEL SECURITY`` on every table. Without it,
-- table OWNERS bypass RLS entirely (Postgres default). The Princeps dev DB
-- runs as the table owner (single-role setup), so without FORCE the policies
-- would be theatre — exactly the audit finding we are closing here.

-- ── projects ───────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'projects') THEN
        ALTER TABLE projects FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS projects_tenant_isolation ON projects;
        CREATE POLICY projects_tenant_isolation ON projects
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;


-- ── prospect_parcels ───────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'prospect_parcels') THEN
        ALTER TABLE prospect_parcels FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS prospect_parcels_tenant_isolation ON prospect_parcels;
        CREATE POLICY prospect_parcels_tenant_isolation ON prospect_parcels
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;


-- ── planning_applications_submitted ────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'planning_applications_submitted') THEN
        ALTER TABLE planning_applications_submitted FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS pas_tenant_isolation ON planning_applications_submitted;
        CREATE POLICY pas_tenant_isolation ON planning_applications_submitted
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;


-- ── procurement_tenders_raw ────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'procurement_tenders_raw') THEN
        ALTER TABLE procurement_tenders_raw FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS ptr_tenant_isolation ON procurement_tenders_raw;
        CREATE POLICY ptr_tenant_isolation ON procurement_tenders_raw
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;


-- ── ontology_action_log ────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'ontology_action_log') THEN
        ALTER TABLE ontology_action_log FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS oal_tenant_isolation ON ontology_action_log;
        CREATE POLICY oal_tenant_isolation ON ontology_action_log
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
                    ELSE tenant_id::text = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;


-- ── action_audit_log ───────────────────────────────────────────────────────
-- Note: this table's tenant_id is TEXT (legacy) — no UUID cast needed.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'action_audit_log') THEN
        ALTER TABLE action_audit_log FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS aal_tenant_isolation ON action_audit_log;
        CREATE POLICY aal_tenant_isolation ON action_audit_log
            USING (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'
                    ELSE tenant_id = current_setting('princeps.tenant_id', true)
                END
            )
            WITH CHECK (
                CASE
                    WHEN current_setting('princeps.tenant_id', true) IS NULL
                      OR current_setting('princeps.tenant_id', true) = ''
                    THEN tenant_id = '00000000-0000-0000-0000-000000000001'
                    ELSE tenant_id = current_setting('princeps.tenant_id', true)
                END
            );
    END IF;
END $$;
