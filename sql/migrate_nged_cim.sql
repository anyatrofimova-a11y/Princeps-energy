-- NGED Connected Data Portal — GSP detail (customer-class demand, N-1 exposure)
-- Existing grid_substations is used for the core substation records; this
-- table holds NGED-specific granular fields that don't fit the shared schema.
-- Source: https://connecteddata.nationalgrid.co.uk/

CREATE TABLE IF NOT EXISTS nged_gsp_detail (
    id                      SERIAL PRIMARY KEY,
    gsp_name                TEXT NOT NULL,
    substation_id           INTEGER REFERENCES grid_substations(id) ON DELETE SET NULL,
    licence_area            TEXT,                      -- WMID / EMID / SWALES / SWEST
    firm_capacity_mva       NUMERIC,
    n_minus_1_capacity_mva  NUMERIC,
    demand_domestic_mw      NUMERIC,
    demand_commercial_mw    NUMERIC,
    demand_industrial_mw    NUMERIC,
    demand_ev_mw            NUMERIC,
    demand_heat_mw          NUMERIC,
    connected_gen_mw        NUMERIC,
    peak_load_factor        NUMERIC,
    as_of_date              DATE,
    raw_data                JSONB DEFAULT '{}'::jsonb,
    ingested_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nged_gsp_name_date
    ON nged_gsp_detail (gsp_name, as_of_date);
CREATE INDEX IF NOT EXISTS idx_nged_gsp_substation
    ON nged_gsp_detail (substation_id);
CREATE INDEX IF NOT EXISTS idx_nged_gsp_licence
    ON nged_gsp_detail (licence_area);
