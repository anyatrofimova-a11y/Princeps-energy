-- =============================================================================
-- 2026_05_02_graph_shim.sql
-- Pure-PostgreSQL graph shadow ontology (Apache AGE substitute).
--
-- Two tables + recursive CTEs in app/graph/cypher_shim.py give us a queryable
-- graph mirror without the AGE Homebrew formula. Idempotent: safe to re-run.
-- Tenant scoping is included on both tables (no RLS in this MVP — defaults
-- to the demo tenant).
-- =============================================================================

CREATE TABLE IF NOT EXISTS graph_nodes (
    rid          TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    props        JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenant_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id           BIGSERIAL PRIMARY KEY,
    from_rid     TEXT NOT NULL REFERENCES graph_nodes(rid) ON DELETE CASCADE,
    to_rid       TEXT NOT NULL REFERENCES graph_nodes(rid) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    props        JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenant_id    UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    UNIQUE (from_rid, to_rid, label)
);

-- Indexes — labels, directional traversal, tenant scope, prop search.
CREATE INDEX IF NOT EXISTS graph_nodes_label_idx     ON graph_nodes (label);
CREATE INDEX IF NOT EXISTS graph_nodes_tenant_idx    ON graph_nodes (tenant_id);
CREATE INDEX IF NOT EXISTS graph_nodes_props_gin     ON graph_nodes USING GIN (props);

CREATE INDEX IF NOT EXISTS graph_edges_label_idx     ON graph_edges (label);
CREATE INDEX IF NOT EXISTS graph_edges_from_label_idx ON graph_edges (from_rid, label);
CREATE INDEX IF NOT EXISTS graph_edges_to_label_idx  ON graph_edges (to_rid, label);
CREATE INDEX IF NOT EXISTS graph_edges_tenant_idx    ON graph_edges (tenant_id);
CREATE INDEX IF NOT EXISTS graph_edges_props_gin     ON graph_edges USING GIN (props);
