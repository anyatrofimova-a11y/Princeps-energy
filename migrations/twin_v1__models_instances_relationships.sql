-- DTDL Twin storage tables (Swarm 11).
-- Holds the actual instances + relationships that DTDL models in
-- ontology/dtdl/*.json describe.
-- Idempotent.

-- Apache AGE extension — graph queries on top of Postgres.
CREATE EXTENSION IF NOT EXISTS age;

-- ---------- twin_models ----------
-- Catalog of DTDL Interface models loaded from ontology/dtdl/.
CREATE TABLE IF NOT EXISTS twin_models (
    dtmi          TEXT PRIMARY KEY,
    display_name  TEXT,
    version       INTEGER NOT NULL,
    parent_dtmi   TEXT,
    raw           JSONB NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS twin_models_parent_idx ON twin_models (parent_dtmi);


-- ---------- twin_instances ----------
-- Actual instances of a DTDL model, keyed by Princeps RID.
CREATE TABLE IF NOT EXISTS twin_instances (
    rid           TEXT PRIMARY KEY,
    dtmi          TEXT NOT NULL REFERENCES twin_models(dtmi) ON DELETE RESTRICT,
    properties    JSONB NOT NULL DEFAULT '{}'::jsonb,
    geom          geometry(Point, 27700),
    last_telemetry_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS twin_instances_dtmi_idx ON twin_instances (dtmi);
CREATE INDEX IF NOT EXISTS twin_instances_geom_gix ON twin_instances USING GIST (geom);
CREATE INDEX IF NOT EXISTS twin_instances_props_gin ON twin_instances USING GIN (properties);


-- ---------- twin_relationships ----------
CREATE TABLE IF NOT EXISTS twin_relationships (
    rid          TEXT PRIMARY KEY,
    from_rid     TEXT NOT NULL REFERENCES twin_instances(rid) ON DELETE CASCADE,
    to_rid       TEXT NOT NULL REFERENCES twin_instances(rid) ON DELETE CASCADE,
    rel_name     TEXT NOT NULL,                 -- DTDL Relationship.name
    properties   JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS twin_rel_from_idx  ON twin_relationships (from_rid);
CREATE INDEX IF NOT EXISTS twin_rel_to_idx    ON twin_relationships (to_rid);
CREATE INDEX IF NOT EXISTS twin_rel_name_idx  ON twin_relationships (rel_name);


-- ---------- twin_telemetry ----------
-- Time-series telemetry per (instance, channel). Could move to TimescaleDB
-- hypertable once installed; this base table is fine for v1.
CREATE TABLE IF NOT EXISTS twin_telemetry (
    instance_rid TEXT NOT NULL REFERENCES twin_instances(rid) ON DELETE CASCADE,
    channel      TEXT NOT NULL,
    ts           TIMESTAMPTZ NOT NULL,
    value_num    DOUBLE PRECISION,
    value_str    TEXT,
    PRIMARY KEY (instance_rid, channel, ts)
);
CREATE INDEX IF NOT EXISTS twin_telemetry_channel_idx ON twin_telemetry (channel, ts DESC);


-- Updated_at trigger for twin_instances.
CREATE OR REPLACE FUNCTION twin_touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END $$;

DROP TRIGGER IF EXISTS twin_instances_touch ON twin_instances;
CREATE TRIGGER twin_instances_touch BEFORE UPDATE ON twin_instances
    FOR EACH ROW EXECUTE FUNCTION twin_touch_updated_at();
