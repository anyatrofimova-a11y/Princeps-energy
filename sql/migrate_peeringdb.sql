-- PeeringDB ingestion — IX and data-centre facility footprint
-- Source: https://www.peeringdb.com/api  (free JSON, no auth for reads)
-- Stored in SRID 4326 because PeeringDB is global; reproject on query.

CREATE TABLE IF NOT EXISTS peering_facilities (
    id              SERIAL PRIMARY KEY,
    pdb_id          INTEGER NOT NULL UNIQUE,     -- PeeringDB fac id
    name            TEXT NOT NULL,
    org_id          INTEGER,
    org_name        TEXT,
    city            TEXT,
    country         TEXT,
    region          TEXT,
    address1        TEXT,
    zipcode         TEXT,
    clli            TEXT,
    rencode         TEXT,
    net_count       INTEGER DEFAULT 0,           -- networks connected
    ix_count        INTEGER DEFAULT 0,           -- IXs present
    status          TEXT,                         -- ok | deleted
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    geom            GEOMETRY(Point, 4326),
    raw_data        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_peering_fac_geom ON peering_facilities USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_peering_fac_country ON peering_facilities (country);
CREATE INDEX IF NOT EXISTS idx_peering_fac_city ON peering_facilities (city);
CREATE INDEX IF NOT EXISTS idx_peering_fac_netcount ON peering_facilities (net_count DESC);

CREATE TABLE IF NOT EXISTS peering_ixs (
    id              SERIAL PRIMARY KEY,
    pdb_id          INTEGER NOT NULL UNIQUE,     -- PeeringDB ix id
    name            TEXT NOT NULL,
    name_long       TEXT,
    city            TEXT,
    country         TEXT,
    region          TEXT,
    media           TEXT,
    net_count       INTEGER DEFAULT 0,
    fac_count       INTEGER DEFAULT 0,
    status          TEXT,
    website         TEXT,
    raw_data        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_peering_ix_country ON peering_ixs (country);
CREATE INDEX IF NOT EXISTS idx_peering_ix_netcount ON peering_ixs (net_count DESC);

-- Join table: which IX lives in which facility
CREATE TABLE IF NOT EXISTS peering_ixfac (
    id              SERIAL PRIMARY KEY,
    pdb_id          INTEGER NOT NULL UNIQUE,
    ix_pdb_id       INTEGER NOT NULL,
    fac_pdb_id      INTEGER NOT NULL,
    status          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_peering_ixfac_ix ON peering_ixfac (ix_pdb_id);
CREATE INDEX IF NOT EXISTS idx_peering_ixfac_fac ON peering_ixfac (fac_pdb_id);
