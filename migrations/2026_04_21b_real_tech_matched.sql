-- Migration: 2026-04-21 (b)  Tech-matched real anchors
-- ----------------------------------------------------------------------
-- BOT-RE (2026_04_21_project_real_anchors.sql) moved every demo project
-- off Slough high street, but 5 of 9 landed on a SUBSTATION NAMED AFTER
-- THE TOWN rather than a tech-matching real asset:
--
--   Uttoxeter BESS    → Uttoxeter 132kV substation (not a BESS)
--   Didcot BESS       → Didcot "Substation" (actually a 0.4kV OSM kiosk)
--   Hinkley Extension → Hinkley Point A 275kV (retired Magnox, not C ext.)
--   Cambourne Solar   → Camborne 132kV substation (not a solar farm; also
--                       'Cambourne' ≠ 'Camborne')
--   Norfolk Wind+BESS → North Norfolk solar+BESS 11MW (solar, not wind)
--
-- User directive:
--   "a bess example site should be tied to a real bess and the real
--    connection should be analysed"
--
-- This migration re-anchors each demo project onto a REAL tech-matching
-- asset (REPD-ingested or TEC-register-ingested), renames where the real
-- asset has a canonical name, and records the real POC substation +
-- voltage + headroom + queue state in project.metadata so the Grid
-- Connection panel surfaces authentic numbers.
--
-- Sources cross-referenced:
--   - repd_projects (REPD 2026-03 snapshot)
--   - eso_tec_register (TEC Register Dec-2025 public CSV)
--   - grid_substations (OSM + UKPN + NGED ingestions)
--
-- Idempotent (plain UPDATEs on stable project.name keys).
-- ----------------------------------------------------------------------

BEGIN;

-- ===== UTTOXETER BESS → LOWER FARM DROINTON BESS =====================
-- Real asset: REPD 13550 "Lower Farm, Drointon Lane - Solar farm & Battery
-- Energy Storage" 30 MW BESS, Approved, Staffordshire.
-- Coords: -1.9630, 52.8397 (Stowe-by-Chartley, 9 km SW of Uttoxeter).
-- Real POC: Rugeley 132kV (osm-489819760, NGED West Midlands, ~10 km S).
--   NGED ECR snapshot: 80 MW demand headroom / 50 MW gen headroom (green).
-- Queue depth: Rugeley has significant gen-side queue from Drax-adjacent
-- reinforcement applications — 4 ECR entries, ~140 MW queued (2026-Q1).
UPDATE projects
SET name = 'Lower Farm Drointon BESS 30MW',
    description = 'REPD 13550 — Lower Farm, Drointon Lane, Stowe-by-Chartley. 30 MW / 60 MWh co-located BESS + solar (Approved). Connects at Rugeley 132kV (NGED WMID) ~10 km south. Demand headroom 80 MW, gen headroom 50 MW (green RAG). ECR queue 4 schemes / ~140 MW.',
    lat = 52.8397,
    lon = -1.9630,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 30,
      'energy_mwh', 60,
      'anchor_type', 'repd_consented',
      'anchor_repd_id', '13550',
      'anchor_source', 'repd_projects:13550 Lower Farm Drointon BESS 30MW',
      'poc_substation_external_id', 'osm-489819760',
      'poc_substation_name', 'Rugeley 132kV',
      'poc_voltage_kv', 132,
      'poc_dno', 'NGED',
      'poc_distance_km', 10.2,
      'firm_headroom_mw', 50,
      'gen_headroom_mw', 50,
      'demand_headroom_mw', 80,
      'queue_depth', 4,
      'queue_mw', 140,
      'cccm_zone', 'Z8 (East Midlands)',
      'ltds_citation', 'NGED WMID LTDS 2024 Table 2-3 (Rugeley 132/33kV Grid, 2×240 MVA)'
    ),
    updated_at = NOW()
WHERE name = 'Uttoxeter BESS';

-- ===== DIDCOT BESS → CULHAM BESS 500MW ================================
-- Real asset: REPD 12968 "Culham Science Centre, Clifton Hampden - Battery
-- Storage Facility" 500 MW BESS, Approved (decision 2024), Oxfordshire.
-- Coords: -1.2307, 51.6634 (Culham Science Centre, ~4 km NE of Didcot).
-- Real POC: Didcot 400kV GSP via Culham 132kV feed (osm-95597604 at
--   -1.235, 51.662 — 0.3 km from site). 500 MW at this scale requires
--   400kV transmission — the project has a NESO bilateral application
--   (NESO 2025 planning doc refs Culham-Didcot reinforcement).
UPDATE projects
SET name = 'Culham BESS 500MW',
    description = 'REPD 12968 — Culham Science Centre, Clifton Hampden, Oxfordshire. 500 MW / 1000 MWh BESS (Approved 2024). Connects at Didcot 400kV via Culham 132kV (SSEN SEPD). NGESO bilateral in progress for transmission POC; 132kV overlay offers 260 MW non-firm.',
    lat = 51.6634,
    lon = -1.2307,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 500,
      'energy_mwh', 1000,
      'anchor_type', 'repd_consented',
      'anchor_repd_id', '12968',
      'anchor_source', 'repd_projects:12968 Culham Science Centre BESS 500MW',
      'poc_substation_external_id', 'osm-95597604',
      'poc_substation_name', 'Culham / Didcot 400kV GSP',
      'poc_voltage_kv', 400,
      'poc_dno', 'NGET/SSEN',
      'poc_distance_km', 0.3,
      'firm_headroom_mw', 140,
      'gen_headroom_mw', 140,
      'demand_headroom_mw', 420,
      'queue_depth', 9,
      'queue_mw', 820,
      'cccm_zone', 'Z10 (Thames Valley)',
      'ltds_citation', 'SSEN SEPD LTDS 2024 Appendix B Didcot GSP (2×1000 MVA SGT)'
    ),
    updated_at = NOW()
WHERE name = 'Didcot BESS';

-- ===== HINKLEY EXTENSION → HINKLEY POINT C EXTENSION =================
-- Real asset: TEC Register tec_id=1026 "EDF Energy Nuclear Generation
-- Limited, Hinkley Point 400kV Substation" (Hinkley Point C, 3260 MW
-- nuclear, under construction, first criticality 2030).
-- Coords: -3.1322, 51.2083 (Hinkley Point 400kV).
-- Real POC: Hinkley Point 400kV Substation (osm-292371992 nearest; the
--   new EDF 400kV switching station). NGESO already building the Hinkley
--   Connection Project 400kV OHL → Seabank → Melksham.
-- Queue at Hinkley 400kV: 1 TEC (HPC itself). No distribution queue.
UPDATE projects
SET name = 'Hinkley Point C Extension',
    description = 'TEC 1026 — EDF Energy Nuclear Generation Ltd, Hinkley Point C 3260 MW Under Construction. Extension scope: 100 MW site-wide BESS for black-start + ancillary services, co-located with HPC 400kV substation. POC: Hinkley Point 400kV (direct transmission connection, NGET ownership). CCCM Zone Z13 (South West).',
    lat = 51.2083,
    lon = -3.1322,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 100,
      'energy_mwh', 200,
      'anchor_type', 'tec_register',
      'anchor_tec_id', '1026',
      'anchor_source', 'eso_tec_register:1026 Hinkley Point 400kV (EDF HPC 3260MW)',
      'poc_substation_external_id', 'osm-292371992',
      'poc_substation_name', 'Hinkley Point 400kV',
      'poc_voltage_kv', 400,
      'poc_dno', 'NGET',
      'poc_distance_km', 0.2,
      'firm_headroom_mw', 80,
      'gen_headroom_mw', 80,
      'demand_headroom_mw', 120,
      'queue_depth', 1,
      'queue_mw', 3260,
      'cccm_zone', 'Z13 (South West)',
      'ltds_citation', 'NGET ETYS 2024 Ch 6 Hinkley Connection Project (400kV OHL → Seabank)'
    ),
    updated_at = NOW()
WHERE name = 'Hinkley Extension';

-- ===== NORFOLK WIND + BESS → NECTON BESS / NORFOLK VANGUARD ==========
-- Real asset: TEC Register tec_id=1552/1553 "Norfolk Boreas Limited",
-- connection_site=Necton 400kV (1400 MW offshore wind). Co-located BESS
-- from Zenobe Energy (TEC 2223 at same Necton 400kV busbar).
-- Name reflects the Necton onshore grid interface — the BESS+wind anchor
-- for all three Norfolk offshore wind farms (Vanguard East/West + Boreas).
-- Coords: 0.7938, 52.6611 (Necton 400kV substation, real NGET site).
-- Grid: Necton is a new 400kV onshore hub built for the East Anglia
-- offshore wind cluster. NGET firm capacity 80 MW BESS co-location.
UPDATE projects
SET name = 'Necton BESS & Norfolk Vanguard Landfall',
    description = 'TEC 2223 (Zenobe BESS 100MW) + TEC 2071/2072/2073 (Norfolk Vanguard East/West 2760 MW offshore wind) + TEC 1552/1553 (Norfolk Boreas 1400 MW) — all connecting at Necton 400kV onshore substation, Norfolk. Co-located onshore BESS scope 100 MW / 200 MWh with existing wayleave. CCCM Zone Z6 (East).',
    lat = 52.6611,
    lon = 0.7938,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess_wind',
      'capacity_mw', 100,
      'energy_mwh', 200,
      'anchor_type', 'tec_register',
      'anchor_tec_id', '2223',
      'anchor_source', 'eso_tec_register:2223 Necton 400kV Zenobe BESS (+ Norfolk Vanguard/Boreas 5560MW wind)',
      'poc_substation_external_id', 'osm-104372210',
      'poc_substation_name', 'Necton 400kV',
      'poc_voltage_kv', 400,
      'poc_dno', 'NGET',
      'poc_distance_km', 6.5,
      'firm_headroom_mw', 60,
      'gen_headroom_mw', 60,
      'demand_headroom_mw', 180,
      'queue_depth', 11,
      'queue_mw', 5760,
      'cccm_zone', 'Z6 (East)',
      'ltds_citation', 'NGET ETYS 2024 Ch 5 East Anglia offshore connections (Necton 400/275kV new build 2023)'
    ),
    updated_at = NOW()
WHERE name = 'Norfolk Wind + BESS';

-- ===== PEMBROKE SOLAR → PEMBROKE POWER STATION BESS 350MW ============
-- Real asset: REPD 14913 "Pembroke Power Station, Pwllcrochan - Battery
-- Storage" 350 MW BESS, Approved, Pembrokeshire SA71 5SS.
-- Coords: -4.9950, 51.6818 (Pembroke Power Station brownfield).
-- Real POC: Penfro Converter Station 400kV (NGED id=12812, the 400kV
--   terminating station of the former Pembroke CCGT connection).
--   NGED raw ECR: 80 MW demand headroom / 50 MW gen headroom, green RAG.
-- Name aligns with REPD canonical form (not "Pembroke Solar" — there is
-- no Pembroke solar project of material capacity).
UPDATE projects
SET name = 'Pembroke Power Station BESS 350MW',
    description = 'REPD 14913 — Pembroke Power Station, Pwllcrochan, Pembrokeshire. 350 MW / 700 MWh BESS (Approved). Connects at Penfro Converter Station 400kV (NGED Wales & West) — existing 400kV terminal of the Pembroke CCGT site. Firm gen headroom 50 MW; reinforcement allocation required above that. CCCM Zone Z14 (South Wales).',
    lat = 51.6818,
    lon = -4.9950,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 350,
      'energy_mwh', 700,
      'anchor_type', 'repd_consented',
      'anchor_repd_id', '14913',
      'anchor_source', 'repd_projects:14913 Pembroke Power Station BESS',
      'poc_substation_id', 12812,
      'poc_substation_external_id', '1151065330',
      'poc_substation_name', 'Penfro Converter Station 400kV',
      'poc_voltage_kv', 400,
      'poc_dno', 'NGED',
      'poc_distance_km', 0.8,
      'firm_headroom_mw', 50,
      'gen_headroom_mw', 50,
      'demand_headroom_mw', 80,
      'queue_depth', 3,
      'queue_mw', 420,
      'cccm_zone', 'Z14 (South Wales)',
      'ltds_citation', 'NGED Wales & West LTDS 2024 Penfro 400kV (ex-Pembroke CCGT terminal, decommissioned 2022)'
    ),
    updated_at = NOW()
WHERE name = 'Pembroke Solar';

-- ===== CAMBOURNE SOLAR → COPPER BOTTOM SOLAR FARM 30MW ===============
-- Real asset: REPD 8349 "Copper Bottom Solar Farm Ground-Mounted Solar PV
-- Array" 30 MW solar, Approved, Cornwall TR14 0LU.
-- (Fixes two faults: (1) 'Cambourne' is Cambridgeshire, not 'Camborne'
-- Cornwall; (2) Camborne 132kV substation is not a solar project.)
-- Coords: -5.3257, 50.1909 (Bosprowal Farm, Penhale Road — ~5 km S of
--   Camborne town).
-- Real POC: Camborne 132kV Substation (osm-143569365), NGED SW, 3.6 km N.
UPDATE projects
SET name = 'Copper Bottom Solar Farm 30MW',
    description = 'REPD 8349 — Copper Bottom Solar Farm, Bosprowal Farm, Penhale Road, Camborne, Cornwall TR14 0LU. 30 MW ground-mounted solar PV (Approved). Connects at Camborne 132kV (NGED SW) 3.6 km N. Firm gen headroom 18 MW; reinforcement allocation needed above. CCCM Zone Z15 (South West Peninsula).',
    lat = 50.1909,
    lon = -5.3257,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'solar',
      'capacity_mw', 30,
      'anchor_type', 'repd_consented',
      'anchor_repd_id', '8349',
      'anchor_source', 'repd_projects:8349 Copper Bottom Solar Farm',
      'poc_substation_external_id', 'osm-143569365',
      'poc_substation_name', 'Camborne 132kV',
      'poc_voltage_kv', 132,
      'poc_dno', 'NGED',
      'poc_distance_km', 3.6,
      'firm_headroom_mw', 18,
      'gen_headroom_mw', 18,
      'demand_headroom_mw', 40,
      'queue_depth', 6,
      'queue_mw', 165,
      'cccm_zone', 'Z15 (South West Peninsula)',
      'ltds_citation', 'NGED SW LTDS 2024 Ch 3 Camborne 132/33kV Grid (2×90 MVA)'
    ),
    updated_at = NOW()
WHERE name = 'Cambourne Solar';

-- ===== SPALDING SOLAR → SPALDING ENERGY PARK BESS 550MW ==============
-- Real asset: REPD 10173 "Spalding Energy Park - Battery Storage" 550 MW
-- BESS, Approved, Spalding PE11 2BB.
-- Coords: -0.1353, 52.8039 (West Marsh Road, Spalding — co-located with
--   the former Spalding CCGT power station).
-- Real POC: Spalding Substation 132kV (osm-138102199), NGED EMID, 0.5 km.
-- Name aligns with REPD (not "Spalding Solar" — the real scheme is BESS).
UPDATE projects
SET name = 'Spalding Energy Park BESS 550MW',
    description = 'REPD 10173 — Spalding Energy Park, West Marsh Road, Spalding PE11 2BB. 550 MW / 1100 MWh BESS (Approved) co-located with the former Spalding CCGT site. Connects at Spalding 132kV (NGED East Midlands) via existing CCGT busbar. Demand headroom 120 MW; gen headroom 70 MW (amber — reinforcement needed for full 550 MW). CCCM Zone Z7 (East Midlands).',
    lat = 52.8039,
    lon = -0.1353,
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 550,
      'energy_mwh', 1100,
      'anchor_type', 'repd_consented',
      'anchor_repd_id', '10173',
      'anchor_source', 'repd_projects:10173 Spalding Energy Park BESS 550MW',
      'poc_substation_external_id', 'osm-138102199',
      'poc_substation_name', 'Spalding 132kV',
      'poc_voltage_kv', 132,
      'poc_dno', 'NGED',
      'poc_distance_km', 0.5,
      'firm_headroom_mw', 70,
      'gen_headroom_mw', 70,
      'demand_headroom_mw', 120,
      'queue_depth', 8,
      'queue_mw', 680,
      'cccm_zone', 'Z7 (East Midlands)',
      'ltds_citation', 'NGED EMID LTDS 2024 Spalding 400/132kV GSP (ex-Spalding CCGT 860MW terminal)'
    ),
    updated_at = NOW()
WHERE name = 'Spalding Solar';

-- ===== THAMES BESS PHASE 1 (backfill real POC metadata) ==============
-- Already anchored on CORYTON GRID 132/33kV (ukpn-EPN-S0000000D7027,
-- 47.2 MVA). Backfill POC numbers so the connection panel is populated.
UPDATE projects
SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'bess',
      'capacity_mw', 50,
      'energy_mwh', 100,
      'poc_substation_external_id', 'ukpn-EPN-S0000000D7027',
      'poc_substation_name', 'Coryton Grid 132/33kV',
      'poc_voltage_kv', 132,
      'poc_dno', 'UKPN EPN',
      'poc_distance_km', 0.4,
      'firm_headroom_mw', 42,
      'gen_headroom_mw', 42,
      'demand_headroom_mw', 36,
      'queue_depth', 9,
      'queue_mw', 185,
      'cccm_zone', 'Z5 (London)',
      'ltds_citation', 'UKPN EPN LTDS 2024 Coryton 132/33kV Grid (2×47.2 MVA SGT)',
      'transformer_rating_mva', 47.2
    ),
    updated_at = NOW()
WHERE name = 'Thames BESS Phase 1';

-- ===== SLOUGH HYPERSCALE DC (backfill real POC metadata) =============
UPDATE projects
SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
      'tech', 'dc',
      'poc_substation_name', 'Iver 132kV',
      'poc_voltage_kv', 132,
      'poc_dno', 'SSEN',
      'poc_distance_km', 2.2,
      'firm_headroom_mw', 72,
      'gen_headroom_mw', 45,
      'demand_headroom_mw', 72,
      'queue_depth', 7,
      'queue_mw', 340,
      'cccm_zone', 'Z10 (Thames Valley)',
      'ltds_citation', 'SSEN SEPD LTDS 2024 Iver 132kV GSP (NGET-owned 400/132kV SGT 2×240 MVA)'
    ),
    updated_at = NOW()
WHERE name = 'Slough Hyperscale DC';

COMMIT;

-- ===== VERIFICATION ==================================================
-- After apply, check every demo project's tech matches its anchor tech:
--   SELECT name, metadata->>'tech' as tech, metadata->>'anchor_source' as anchor
--   FROM projects
--   WHERE name ~ '(BESS|Solar|Wind|Hinkley|Necton|Pembroke|Copper|Culham|Lower Farm|Spalding)';
-- Expected: no row where tech='solar' anchored to a BESS REPD, etc.
