-- migrate_cim_substrate.sql
-- CIM/CGMES 100 substrate for the Princeps Grid Model Explorer.
--
-- Source: DNO LTDS Common Information Model XML (CGMES Equipment Profile
-- + Ofgem LTDS Extensions). Currently populated from NGED (4 regions,
-- ~50% of GB by area) under NGED Open Data Licence v1.0.
--
-- Attribution required on any derived public surface:
--   "Contains data from NGED LTDS CIM (Open Data Licence v1.0)"

CREATE TABLE IF NOT EXISTS cim_substations (
  mrid           TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  region_mrid    TEXT,
  region_name    TEXT,
  dno            TEXT NOT NULL,
  source_region  TEXT,
  ingested_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS cim_substations_dno ON cim_substations(dno);
CREATE INDEX IF NOT EXISTS cim_substations_name ON cim_substations(name);

CREATE TABLE IF NOT EXISTS cim_voltage_levels (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  substation_mrid    TEXT,
  base_voltage_mrid  TEXT,
  base_voltage_kv    NUMERIC
);
CREATE INDEX IF NOT EXISTS cim_voltage_levels_sub ON cim_voltage_levels(substation_mrid);

CREATE TABLE IF NOT EXISTS cim_base_voltages (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  nominal_voltage_kv NUMERIC
);

CREATE TABLE IF NOT EXISTS cim_busbar_sections (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  voltage_level_mrid TEXT,
  base_voltage_mrid  TEXT
);
CREATE INDEX IF NOT EXISTS cim_busbar_sections_vl ON cim_busbar_sections(voltage_level_mrid);

CREATE TABLE IF NOT EXISTS cim_ac_line_segments (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  line_mrid          TEXT,
  base_voltage_mrid  TEXT,
  length_m           NUMERIC,
  r                  NUMERIC,
  x                  NUMERIC,
  bch                NUMERIC,
  gch                NUMERIC
);
CREATE INDEX IF NOT EXISTS cim_ac_line_segments_line ON cim_ac_line_segments(line_mrid);

CREATE TABLE IF NOT EXISTS cim_power_transformers (
  mrid              TEXT PRIMARY KEY,
  name              TEXT,
  substation_mrid   TEXT
);
CREATE INDEX IF NOT EXISTS cim_power_transformers_sub ON cim_power_transformers(substation_mrid);

CREATE TABLE IF NOT EXISTS cim_power_transformer_ends (
  mrid                  TEXT PRIMARY KEY,
  transformer_mrid      TEXT,
  end_number            INT,
  base_voltage_mrid     TEXT,
  rated_s_mva           NUMERIC,
  rated_u_kv            NUMERIC,
  r                     NUMERIC,
  x                     NUMERIC,
  b                     NUMERIC,
  terminal_mrid         TEXT
);
CREATE INDEX IF NOT EXISTS cim_ptend_xfm ON cim_power_transformer_ends(transformer_mrid);

CREATE TABLE IF NOT EXISTS cim_connectivity_nodes (
  mrid           TEXT PRIMARY KEY,
  name           TEXT,
  container_mrid TEXT
);
CREATE INDEX IF NOT EXISTS cim_cn_container ON cim_connectivity_nodes(container_mrid);

CREATE TABLE IF NOT EXISTS cim_terminals (
  mrid                       TEXT PRIMARY KEY,
  conducting_equipment_mrid  TEXT,
  connectivity_node_mrid     TEXT,
  sequence_number            INT
);
CREATE INDEX IF NOT EXISTS cim_terminals_ce ON cim_terminals(conducting_equipment_mrid);
CREATE INDEX IF NOT EXISTS cim_terminals_cn ON cim_terminals(connectivity_node_mrid);

CREATE TABLE IF NOT EXISTS cim_switches (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  switch_type        TEXT,
  voltage_level_mrid TEXT,
  base_voltage_mrid  TEXT,
  normal_open        BOOLEAN
);
CREATE INDEX IF NOT EXISTS cim_switches_vl ON cim_switches(voltage_level_mrid);
CREATE INDEX IF NOT EXISTS cim_switches_type ON cim_switches(switch_type);

CREATE TABLE IF NOT EXISTS cim_synchronous_machines (
  mrid                  TEXT PRIMARY KEY,
  name                  TEXT,
  voltage_level_mrid    TEXT,
  base_voltage_mrid     TEXT,
  max_export_p_mw       NUMERIC,
  nominal_voltage_kv    NUMERIC,
  machine_type          TEXT,
  generating_unit_ref   TEXT,
  aggregate             BOOLEAN
);

CREATE TABLE IF NOT EXISTS cim_energy_consumers (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  voltage_level_mrid TEXT,
  p_mw               NUMERIC,
  q_mvar             NUMERIC
);

CREATE TABLE IF NOT EXISTS cim_equivalent_injections (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  voltage_level_mrid TEXT,
  p_mw               NUMERIC,
  q_mvar             NUMERIC,
  max_p_mw           NUMERIC,
  min_p_mw           NUMERIC
);

CREATE TABLE IF NOT EXISTS cim_linear_shunt_compensators (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  voltage_level_mrid TEXT,
  nom_u_kv           NUMERIC,
  section_count      INT
);

CREATE TABLE IF NOT EXISTS cim_power_electronics_connections (
  mrid               TEXT PRIMARY KEY,
  name               TEXT,
  voltage_level_mrid TEXT,
  max_p_mw           NUMERIC,
  type               TEXT
);

CREATE TABLE IF NOT EXISTS cim_lines (
  mrid          TEXT PRIMARY KEY,
  name          TEXT,
  region_mrid   TEXT
);

CREATE TABLE IF NOT EXISTS cim_geographical_regions (
  mrid          TEXT PRIMARY KEY,
  name          TEXT,
  parent_mrid   TEXT
);

-- Ingestion run log so we can answer "when was the SWest CIM last refreshed?"
CREATE TABLE IF NOT EXISTS cim_ingest_log (
  id              BIGSERIAL PRIMARY KEY,
  dno             TEXT NOT NULL,
  source_region   TEXT,
  source_url      TEXT,
  xml_filename    TEXT,
  xml_bytes       BIGINT,
  rows_written    JSONB,
  ingested_at     TIMESTAMPTZ DEFAULT NOW(),
  status          TEXT
);
