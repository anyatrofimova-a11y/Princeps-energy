-- Migration: 2026-04-21  Real-asset project anchors
-- ----------------------------------------------------------------------
-- BOT-RL moved demo projects off Slough town centre, but the seed guard
-- (db_setup.py:478) only inserts when portfolios is empty, so existing
-- DBs kept the old mock coords (51.5074,-0.1278 / 51.5105,-0.595 = Tesco
-- Extra / Residence Inn / Nando's / Upton Hospital — Slough high street).
--
-- This migration re-anchors every demo project onto a REAL grid-connected
-- asset: either an operational/consented REPD project, or a named UKPN/
-- OSM substation, cross-referenced against grid_substations + repd_projects.
-- Idempotent (plain UPDATEs on stable business keys: project.name).
-- ----------------------------------------------------------------------

BEGIN;

-- ===== THAMES BESS PHASE 1 ============================================
-- Anchor: CORYTON GRID 132/33KV substation (UKPN EPN, ext ukpn-EPN-S0000000D7027).
-- Real 132kV grid substation at Shell Haven / Coryton industrial complex.
UPDATE projects
SET lat = 51.5179,
    lon = 0.5045,
    description = '50 MW / 100 MWh grid-scale battery — co-located with CORYTON GRID 132/33kV substation (UKPN EPN), Shell Haven / London Gateway Thames-estuary brownfield cluster.',
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"grid_substations:ukpn-EPN-S0000000D7027","anchor_type":"substation"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Thames BESS Phase 1';

-- ===== SLOUGH HYPERSCALE DC ===========================================
-- Anchor: REPD 4699 — Slough Heat & Power Station (49.9 MW Under Construction).
-- Real operational/consented energy site on Slough Trading Estate. Iver 132kV 2.2 km.
-- NOTE: repd_id on projects table has a UNIQUE constraint and the REPD row is
-- ingested independently into repd_projects. We therefore record the linkage
-- in metadata only (avoid collision with the repd_projects-seeded project row).
UPDATE projects
SET lat = 51.5239,
    lon = -0.6269,
    description = '40 MW IT-load data centre adjacent to Slough Heat & Power Station (REPD 4699, 49.9 MW under construction), Slough Trading Estate. Iver 132kV GSP 2.2 km north.',
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"repd_projects:4699 Slough Heat & Power Station","anchor_type":"repd_operational","anchor_repd_id":"4699"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Slough Hyperscale DC';

-- ===== UTTOXETER BESS =================================================
-- Anchor: Uttoxeter Substation 132kV (OSM osm-477116465). Real 132kV.
UPDATE projects
SET lat = 52.9080,
    lon = -1.8575,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"grid_substations:osm-477116465 Uttoxeter 132kV","anchor_type":"substation"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Uttoxeter BESS';

-- ===== HINKLEY EXTENSION ==============================================
-- Anchor: Hinkley Point A Substation 275kV (OSM osm-292371992). Real 275kV.
UPDATE projects
SET lat = 51.2061,
    lon = -3.1325,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"grid_substations:osm-292371992 Hinkley Point A 275kV","anchor_type":"substation"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Hinkley Extension';

-- ===== NORFOLK WIND + BESS ============================================
-- Anchor: REPD 10497 / 1590 — North Norfolk Business Centre Solar Park + BESS
-- (Operational, 11 MW + 6 MW BESS). Real operational asset.
-- (repd_id kept in metadata only — REPD row exists as its own project.)
UPDATE projects
SET lat = 52.9013,
    lon = 1.3083,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"repd_projects:10497 North Norfolk Business Centre Solar + BESS","anchor_type":"repd_operational","anchor_repd_id":"10497"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Norfolk Wind + BESS';

-- ===== PEMBROKE SOLAR =================================================
-- Anchor: REPD 14913 — Pembroke Power Station BESS 350 MW (Approved).
-- Real consented energy asset co-located with 500kV Pembroke Power Station.
-- (repd_id kept in metadata only — REPD row exists as its own project.)
UPDATE projects
SET lat = 51.6818,
    lon = -4.9950,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"repd_projects:14913 Pembroke Power Station BESS","anchor_type":"repd_consented","anchor_repd_id":"14913"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Pembroke Solar';

-- ===== DIDCOT BESS ====================================================
-- Anchor: Didcot Substation (OSM osm-263863442). Real Didcot power station substation.
UPDATE projects
SET lat = 51.6256,
    lon = -1.2592,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"grid_substations:osm-263863442 Didcot Substation","anchor_type":"substation"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Didcot BESS';

-- ===== CAMBOURNE SOLAR ================================================
-- Anchor: Camborne Substation 132kV (OSM osm-143569365). Real 132kV in Cornwall.
-- (Note: project name 'Cambourne' likely a typo for 'Camborne' — anchored to real Camborne.)
UPDATE projects
SET lat = 50.2289,
    lon = -5.2798,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"grid_substations:osm-143569365 Camborne 132kV","anchor_type":"substation"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Cambourne Solar';

-- ===== SPALDING SOLAR =================================================
-- Anchor: REPD 10173 — Spalding Energy Park 550 MW BESS (Approved), adjacent to
-- Spalding Substation 132kV (OSM osm-138102199). Real operational/consented cluster.
-- (repd_id kept in metadata only — REPD row exists as its own project.)
UPDATE projects
SET lat = 52.8039,
    lon = -0.1353,
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"anchor_source":"repd_projects:10173 Spalding Energy Park 550MW BESS","anchor_type":"repd_consented","anchor_repd_id":"10173"}'::jsonb,
    updated_at = NOW()
WHERE name = 'Spalding Solar';

-- ===== CANDIDATE SITES FOR THAMES BESS PHASE 1 =======================
-- Candidate #1: Rainham Substation 33kV (OSM osm-844794264). Real RM13 substation.
UPDATE project_candidate_sites pcs
SET lat = 51.5207,
    lon = 0.2042,
    name = 'Rainham substation adjacent'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Thames BESS Phase 1'
  AND (pcs.name ILIKE '%rainham%' OR pcs.is_preferred = true);

-- Candidate #2: Barking Riverside 132kV substation (OSM osm-1021376264).
UPDATE project_candidate_sites pcs
SET lat = 51.5192,
    lon = 0.1143,
    name = 'Dagenham / Barking Riverside 132kV'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Thames BESS Phase 1'
  AND pcs.name ILIKE '%dagenham%';

-- Candidate #3: DOCK ROAD TILBURY 33kV (UKPN EPN ukpn-EPN-S0000000G7223).
UPDATE project_candidate_sites pcs
SET lat = 51.4677,
    lon = 0.3566,
    name = 'Tilbury port brownfield'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Thames BESS Phase 1'
  AND pcs.name ILIKE '%tilbury%';

-- ===== CANDIDATE SITES FOR SLOUGH HYPERSCALE DC ======================
-- Candidate #1: REPD 831 — Fibrepower Slough (50 MW Operational biomass CHP).
UPDATE project_candidate_sites pcs
SET lat = 51.5244,
    lon = -0.6277,
    name = 'Fibrepower / Slough Trading Estate'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Slough Hyperscale DC'
  AND (pcs.name ILIKE '%slough west%' OR pcs.name ILIKE '%fibrepower%' OR pcs.is_preferred = true);

-- Candidate #2: Iver Substation 132kV (OSM osm-23232742). Real UKPN/NGET Iver GSP.
UPDATE project_candidate_sites pcs
SET lat = 51.5417,
    lon = -0.4973,
    name = 'Iver 132kV adjacent'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Slough Hyperscale DC'
  AND (pcs.name ILIKE '%reading east%' OR pcs.name ILIKE '%iver%');

-- Candidate #3: Colnbrook / Poyle trading estate (SL3, Heathrow-fringe DC cluster).
UPDATE project_candidate_sites pcs
SET lat = 51.4880,
    lon = -0.5320,
    name = 'Colnbrook / Poyle DC cluster'
FROM projects p
WHERE pcs.project_id = p.project_id
  AND p.name = 'Slough Hyperscale DC'
  AND (pcs.name ILIKE '%heathrow%' OR pcs.name ILIKE '%colnbrook%');

COMMIT;

-- ===== VERIFICATION ==================================================
-- After applying, confirm no project still sits on Slough town centre:
--   SELECT name, lat, lon FROM projects
--   WHERE lat BETWEEN 51.509 AND 51.512 AND lon BETWEEN -0.596 AND -0.594;
-- Expected: 0 rows.
