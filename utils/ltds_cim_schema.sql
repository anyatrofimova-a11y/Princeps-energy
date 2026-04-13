-- ──────────────────────────────────────────────────────────────────────
-- NGED LTDS CIM — IEC 61970 Common Information Model tables.
-- Stage 1.3 EQ profile (equipment only). Future stages add TP / SSH / SV / GL.
-- Source: https://connecteddata.nationalgrid.co.uk
-- ──────────────────────────────────────────────────────────────────────

-- Model metadata (one row per region per publication)
CREATE TABLE IF NOT EXISTS ltds_models (
    model_mrid          TEXT PRIMARY KEY,
    dno                 TEXT NOT NULL,
    licence_area        TEXT NOT NULL,         -- EMIDS / WMIDS / SWEST / SWALES
    profile             TEXT,                  -- e.g. http://ofgem.gov.uk/ns/CIM/LTDS/Equipment/6.0
    created             TIMESTAMPTZ,
    scenario_time       TIMESTAMPTZ,
    version             TEXT,
    description         TEXT,
    source_file         TEXT,
    ingested_at         TIMESTAMPTZ DEFAULT now()
);


-- Geographical regions (DNO) + sub-regions (GSP groupings)
CREATE TABLE IF NOT EXISTS ltds_geographical_regions (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS ltds_sub_regions (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    region_mrid         TEXT REFERENCES ltds_geographical_regions(mrid) ON DELETE CASCADE,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- PSR (Power System Resource) type classification
CREATE TABLE IF NOT EXISTS ltds_psr_types (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Base voltages (132 kV, 66 kV, 33 kV, 11 kV …)
CREATE TABLE IF NOT EXISTS ltds_base_voltages (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    nominal_voltage_kv  NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Substations (with optional geography once GL profile lands, else joined to
-- the existing grid_substations table by fuzzy name match)
CREATE TABLE IF NOT EXISTS ltds_substations (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    dno                 TEXT,
    licence_area        TEXT,
    psr_type            TEXT,                  -- 'Primary','BSP','GSP','Grid','Other'
    sub_region_mrid     TEXT REFERENCES ltds_sub_regions(mrid) ON DELETE SET NULL,
    substation_number   TEXT,                  -- from ltds-cim-substation-numbers.csv
    -- Coordinates — populated from GL profile OR joined from grid_substations
    lat                 DOUBLE PRECISION,
    lon                 DOUBLE PRECISION,
    geom                GEOMETRY(Point, 4326),
    grid_substation_id  INTEGER,               -- FK-ish to grid_substations.id when matched
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE,
    ingested_at         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cim_substations_name  ON ltds_substations (LOWER(name));
CREATE INDEX IF NOT EXISTS idx_cim_substations_dno   ON ltds_substations (dno);
CREATE INDEX IF NOT EXISTS idx_cim_substations_psr   ON ltds_substations (psr_type);
CREATE INDEX IF NOT EXISTS idx_cim_substations_geom  ON ltds_substations USING GIST (geom);


-- VoltageLevel — a voltage zone within a substation
CREATE TABLE IF NOT EXISTS ltds_voltage_levels (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    base_voltage_mrid   TEXT REFERENCES ltds_base_voltages(mrid) ON DELETE SET NULL,
    substation_mrid     TEXT REFERENCES ltds_substations(mrid) ON DELETE CASCADE,
    nominal_voltage_kv  NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_vl_substation ON ltds_voltage_levels (substation_mrid);


-- ConnectivityNode — the topological bus concept
CREATE TABLE IF NOT EXISTS ltds_connectivity_nodes (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    container_mrid      TEXT,                  -- VoltageLevel or Line
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_cn_container ON ltds_connectivity_nodes (container_mrid);


-- Terminals — the join between equipment and connectivity nodes
CREATE TABLE IF NOT EXISTS ltds_terminals (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    sequence_number     INTEGER,
    conducting_eq_mrid  TEXT,                  -- the piece of equipment
    connectivity_mrid   TEXT,                  -- references ltds_connectivity_nodes.mrid (no FK — cross-model)
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_term_equip    ON ltds_terminals (conducting_eq_mrid);
CREATE INDEX IF NOT EXISTS idx_cim_term_connect  ON ltds_terminals (connectivity_mrid);


-- Busbar sections
CREATE TABLE IF NOT EXISTS ltds_busbars (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    voltage_level_mrid  TEXT REFERENCES ltds_voltage_levels(mrid) ON DELETE CASCADE,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- AC line segments
CREATE TABLE IF NOT EXISTS ltds_ac_lines (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    length_km           NUMERIC,
    r_ohm               NUMERIC,
    x_ohm               NUMERIC,
    b_siemens           NUMERIC,
    g_siemens           NUMERIC,
    base_voltage_mrid   TEXT REFERENCES ltds_base_voltages(mrid) ON DELETE SET NULL,
    voltage_level_mrid  TEXT,
    line_mrid           TEXT,                  -- parent Line container
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_line_parent   ON ltds_ac_lines (line_mrid);


-- Lines (container that owns the segments — represents a whole circuit)
CREATE TABLE IF NOT EXISTS ltds_lines (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    sub_region_mrid     TEXT,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Power Transformers + their Ends (windings)
CREATE TABLE IF NOT EXISTS ltds_power_transformers (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    substation_mrid     TEXT REFERENCES ltds_substations(mrid) ON DELETE CASCADE,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_tf_sub ON ltds_power_transformers (substation_mrid);

CREATE TABLE IF NOT EXISTS ltds_transformer_ends (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    end_number          INTEGER,
    transformer_mrid    TEXT REFERENCES ltds_power_transformers(mrid) ON DELETE CASCADE,
    base_voltage_mrid   TEXT,
    rated_u_kv          NUMERIC,
    rated_s_mva         NUMERIC,
    r_ohm               NUMERIC,
    x_ohm               NUMERIC,
    terminal_mrid       TEXT,
    connectivity_mrid   TEXT,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_tf_end_parent ON ltds_transformer_ends (transformer_mrid);


-- Tap changers
CREATE TABLE IF NOT EXISTS ltds_tap_changers (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    transformer_end_mrid TEXT REFERENCES ltds_transformer_ends(mrid) ON DELETE CASCADE,
    low_step            INTEGER,
    high_step           INTEGER,
    neutral_step        INTEGER,
    step_voltage_increment_pct NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Breakers + Disconnectors (switches)
CREATE TABLE IF NOT EXISTS ltds_switches (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    switch_type         TEXT,                  -- 'Breaker' | 'Disconnector' | 'LoadBreakSwitch'
    normal_open         BOOLEAN,
    voltage_level_mrid  TEXT REFERENCES ltds_voltage_levels(mrid) ON DELETE CASCADE,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_switch_type ON ltds_switches (switch_type);


-- Loads (EnergyConsumer)
CREATE TABLE IF NOT EXISTS ltds_loads (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    voltage_level_mrid  TEXT REFERENCES ltds_voltage_levels(mrid) ON DELETE CASCADE,
    p_fixed_mw          NUMERIC,
    q_fixed_mvar        NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Equivalent injections — interfaces to neighbour networks
CREATE TABLE IF NOT EXISTS ltds_equivalent_injections (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    voltage_level_mrid  TEXT REFERENCES ltds_voltage_levels(mrid) ON DELETE CASCADE,
    p_mw                NUMERIC,
    q_mvar              NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Generating units (real gen + PhotoVoltaic + Battery + Hydro)
CREATE TABLE IF NOT EXISTS ltds_generators (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    gen_type            TEXT,                  -- 'Synchronous','PV','Battery','Hydro','Asynchronous'
    substation_mrid     TEXT,
    voltage_level_mrid  TEXT,
    rated_mva           NUMERIC,
    min_mw              NUMERIC,
    max_mw              NUMERIC,
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);


-- Operational limits (seasonal thermal ratings)
CREATE TABLE IF NOT EXISTS ltds_operational_limits (
    mrid                TEXT PRIMARY KEY,
    name                TEXT,
    limit_set_mrid      TEXT,
    equipment_mrid      TEXT,                  -- conducting equipment the limit applies to
    limit_type          TEXT,                  -- 'patl' | 'tatl' | 'currentLimit' | 'apparentPowerLimit'
    value_numeric       NUMERIC,
    season              TEXT,                  -- 'summer' | 'winter' | 'spring' | 'autumn' | 'reverse'
    model_mrid          TEXT REFERENCES ltds_models(model_mrid) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cim_oplimit_equip ON ltds_operational_limits (equipment_mrid);
CREATE INDEX IF NOT EXISTS idx_cim_oplimit_season ON ltds_operational_limits (season);


-- Substation number reference (from NGED CSV)
CREATE TABLE IF NOT EXISTS ltds_substation_numbers (
    substation_number   TEXT PRIMARY KEY,
    ltds_substation_name TEXT,
    substation_type     TEXT
);
CREATE INDEX IF NOT EXISTS idx_cim_sub_num_name ON ltds_substation_numbers (LOWER(ltds_substation_name));
