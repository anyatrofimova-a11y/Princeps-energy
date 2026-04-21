-- Migration: 2026-04-21 (d)  Seed demo dockets + project_docket_pins
-- ----------------------------------------------------------------------
-- BOT-DQ: `list_dockets(project_id=...)` returned 0 for every demo
-- project because `project_docket_pins` was empty. The `dockets` table
-- itself was also empty (0 rows at apply time) — no intelligence seed
-- has run yet on this DB. To make the Intelligence-panel tool-calls
-- light up for the 9 demo projects, this migration:
--
--   1. Inserts a curated set of UK-2026 dockets covering the four
--      buckets called out by the BOT-DQ brief (grid-connection, BESS,
--      solar/BESS planning, DC). Each docket has a deterministic
--      (source, source_docket_id) pair so ON CONFLICT makes it
--      re-runnable.
--
--   2. Pins 2-5 relevant dockets to each demo project via
--      project_docket_pins. Uses (project_id, docket_id) as the PK
--      conflict target — seeds skip rows that already exist.
--
-- Demo project UUIDs (from the 2026-04-21b tech-matched anchor pass):
--   Thames BESS Phase 1                     0367bdbc-4a81-4f15-aa8d-5d2190221104
--   Slough Hyperscale DC                    d0003220-e879-4b19-bc6b-235771f1a517
--   Culham BESS 500MW                       7d728132-211a-487b-a5f2-ba4d05bbe8fc
--   Pembroke Power Station BESS 350MW       f43a8152-fac0-458f-8e86-bc1267a69833
--   Spalding Energy Park BESS 550MW         ada819cb-1bf8-432e-a245-603d29019a51
--   Necton BESS & Norfolk Vanguard Landfall 06cfc2ab-cffc-4504-9a51-79a064140090
--   Lower Farm Drointon BESS 30MW           e641b73f-9b80-4750-8e40-2dccfa9839af
--   Copper Bottom Solar Farm 30MW           17485769-9d3d-4354-9d4e-974fbdfda611
--   Hinkley Point C Extension               85b6fe7a-1de2-4b1d-97fe-11793588b420
--
-- Idempotent via ON CONFLICT DO NOTHING on both the dockets insert
-- (uniq on (source, source_docket_id)) and the pins insert
-- (PK on (project_id, docket_id)). Safe to re-run without duplicates.
-- ----------------------------------------------------------------------

BEGIN;

-- ===== DOCKET SEED ====================================================
-- Grid-connection and regulatory reform
INSERT INTO dockets (
    source, source_docket_id, title, description, case_type, industry,
    status, stage, applicant_name, statutory_deadline, opened_at
) VALUES
  -- GRID / CONNECTION REFORM
  ('ofgem', 'GC0167',
   'G99 Issue 2 review — embedded generation commissioning',
   'Grid Code mod GC0167: periodic review of Engineering Recommendation G99 Issue 2 requirements for commissioning embedded generation ≥1 MW. Affects BESS/solar DNO-connected schemes in queue.',
   'gc', 'electricity', 'open', 'examination',
   'National Energy System Operator', DATE '2026-09-30', TIMESTAMPTZ '2026-01-15 09:00+00'),
  ('neso', 'TMO4PLUS-GATE2',
   'NESO TMO4+ Gate 2 assessment window',
   'Transmission-connected Mod 4+ (TMO4+) Gate 2 methodology now live. Projects in gen-queue scored on commercial maturity + consenting + land; failing projects exit the queue. Directly affects Hinkley, Necton, Culham 400kV schemes.',
   'cmp', 'electricity', 'open', 'examination',
   'National Energy System Operator', DATE '2026-07-31', TIMESTAMPTZ '2026-03-03 09:00+00'),
  ('neso', 'CCCM-V19',
   'CCCM v19 review — Connections Charging & Coordination Methodology',
   'NESO CCCM v19 consultation: revisions to zonal charge boundaries and reinforcement-cost allocation (RCA) rules. Z5 London, Z10 Thames Valley and Z6 East Anglia boundaries under review.',
   'cmp', 'electricity', 'open', 'pre_examination',
   'National Energy System Operator', DATE '2026-06-30', TIMESTAMPTZ '2026-02-10 09:00+00'),
  ('ofgem', 'RIIO-ED3',
   'RIIO-ED3 — Electricity distribution price control 2028-2033',
   'Ofgem RIIO-ED3 Framework Decision: DNO totex allowances, connections incentives, and LDES/flex arrangements for the 2028-33 control period. Affects UKPN, NGED, SSEN, SPEN, NPG, SHEPD.',
   'riio_control', 'electricity', 'open', 'pre_examination',
   'Ofgem', DATE '2027-12-31', TIMESTAMPTZ '2025-11-20 09:00+00'),
  ('ofgem', 'REMA-PHASE2',
   'REMA Phase 2 — Reformed national pricing decision',
   'DESNZ/Ofgem REMA Phase 2 decision (post-2026 reform): retained national wholesale pricing, strengthened locational signals via Transmission Network Use of System (TNUoS) reforms. Affects revenue stack for all generators + BESS arbitrage.',
   'ofgem_decision', 'electricity', 'open', 'decision',
   'DESNZ / Ofgem', DATE '2026-12-31', TIMESTAMPTZ '2026-01-30 09:00+00'),
  ('neso', 'LARGE-LOAD-CONNECT-2026',
   'NESO Large Load Connection framework (demand ≥100 MW)',
   'NESO framework for data-centre and industrial demand ≥100 MW: queue prioritisation, anticipatory investment, and demand-flex obligations. Live consultation window.',
   'cmp', 'electricity', 'open', 'examination',
   'National Energy System Operator', DATE '2026-08-31', TIMESTAMPTZ '2026-04-01 09:00+00'),

  -- BESS / MARKET
  ('neso', 'EMR-CM-T4-2029-30',
   'EMR Capacity Market T-4 2029/30 auction — Prequalification',
   'Capacity Market T-4 auction for delivery year 2029/30. Prequalification window open; BESS de-rating factors updated (1h: 7.8%, 2h: 18.8%, 4h: 45%).',
   'cm_auction', 'electricity', 'open', 'pre_examination',
   'NESO / ESC', DATE '2026-11-15', TIMESTAMPTZ '2026-02-01 09:00+00'),
  ('neso', 'BSWA-2026',
   'Balancing Services Wider Access (BSWA) — BESS aggregation',
   'BSWA consultation: rules for BESS-at-distribution to participate in NESO balancing products (DC, DM, DR, FFR, Enhanced Frequency Response) via aggregators with firm-curtailable interface.',
   'cmp', 'electricity', 'open', 'examination',
   'National Energy System Operator', DATE '2026-07-15', TIMESTAMPTZ '2026-01-20 09:00+00'),
  ('neso', 'ANCILLARY-ROADMAP-2026',
   'NESO Ancillary Services Roadmap 2026-2030',
   'Roadmap for procurement of response/reserve/inertia/reactive products 2026-30. Stability Pathfinder Phase 3, Inertia Dynamic Containment tender refresh, Reactive Services enduring procurement.',
   'cmp', 'electricity', 'open', 'recommendation',
   'National Energy System Operator', DATE '2026-10-31', TIMESTAMPTZ '2025-12-10 09:00+00'),

  -- PLANNING: BESS/SOLAR
  ('desnz', 'EN-3-2025',
   'EN-3 2025 — Revised NPS for Renewable Energy Infrastructure',
   'DESNZ EN-3 National Policy Statement update (designated Jan 2026). Solar PV >50 MW and BESS with co-located generation treated as NSIP where thresholds met. Presumption in favour for BNG-compliant schemes.',
   'ofgem_consultation', 'electricity', 'made', 'made',
   'DESNZ', DATE '2026-01-17', TIMESTAMPTZ '2025-07-15 09:00+00'),
  ('mhclg', 'BNG-NSIP-DELAY-2026',
   'BNG-for-NSIPs commencement — 27 May 2026',
   'Biodiversity Net Gain mandatory-for-NSIPs regime commences 27 May 2026 (delayed from Nov 2025). 10% minimum BNG applies to DCO applications submitted post-commencement. Pre-submission projects grandfathered.',
   'ofgem_consultation', 'electricity', 'open', 'pre_examination',
   'DEFRA / MHCLG', DATE '2026-05-27', TIMESTAMPTZ '2025-10-20 09:00+00'),
  ('mhclg', 'NPPF-DEC-2024',
   'NPPF Dec 2024 — paras 162/165/168/196 energy reforms',
   'National Planning Policy Framework (Dec 2024 revision): strengthened presumption for clean energy (para 162), removal of ''wind farm de facto ban'' (para 165), BESS in open countryside guidance (para 168), Grey-Belt releases (para 196).',
   'ofgem_consultation', 'electricity', 'made', 'made',
   'MHCLG', DATE '2024-12-12', TIMESTAMPTZ '2024-07-30 09:00+00'),
  ('desnz', 'AR7-2026',
   'Contracts for Difference Allocation Round 7 (AR7) — Jan 2026 opening',
   'AR7 auction opened January 2026. Solar Pot 1 reference price £63/MWh (2024 prices); onshore wind £68/MWh; offshore wind Pot 3 with ringfenced fixed-bottom budget.',
   'cfd_round', 'electricity', 'open', 'examination',
   'DESNZ / LCCC', DATE '2026-05-31', TIMESTAMPTZ '2026-01-08 09:00+00'),

  -- DC / DATA CENTRE
  ('ofgem', 'DC-POLICY-REVIEW-2026',
   'Ofgem Data Centre Policy Review — connections queue reform',
   'Ofgem policy consultation on data-centre connection prioritisation, demand-flex obligations, and anticipatory network investment for the "National Critical Infrastructure" classification applied to DCs from 2024.',
   'ofgem_consultation', 'electricity', 'open', 'examination',
   'Ofgem', DATE '2026-07-31', TIMESTAMPTZ '2026-02-15 09:00+00'),
  ('desnz', 'DC-HEAT-REUSE-2026',
   'Data-centre waste-heat reuse consultation',
   'DESNZ consultation on mandatory waste-heat reuse for DC developments ≥40 MW IT load. Aligns with EU Energy Efficiency Directive Art. 26. Impact assessment includes feasibility corridor for Slough and Thames Valley cluster.',
   'ofgem_consultation', 'electricity', 'open', 'pre_examination',
   'DESNZ', DATE '2026-09-30', TIMESTAMPTZ '2026-03-12 09:00+00'),

  -- WALES / COASTAL (Pembroke)
  ('welsh-gov', 'WALES-ENERGY-FRAMEWORK-2026',
   'Welsh Government Energy Framework 2026 update',
   'Welsh Government policy framework: 100% renewable electricity by 2035, designated energy-priority zones including Pembrokeshire coastal. Updated DNS thresholds (50 MW generation, 350 MW BESS).',
   'scottish_dns', 'electricity', 'open', 'examination',
   'Welsh Government', DATE '2026-06-30', TIMESTAMPTZ '2026-01-12 09:00+00'),
  ('tce', 'OFFSHORE-LANDFALL-2026',
   'Offshore Wind Landfall Guidance update (Crown Estate + MMO)',
   'Crown Estate / MMO joint guidance on offshore-wind landfall cable corridors: revised HDD preference, Nature Restoration Fund obligations, consultation on derogation for shared-use corridors.',
   'misc', 'electricity', 'open', 'examination',
   'The Crown Estate / MMO', DATE '2026-08-15', TIMESTAMPTZ '2026-02-28 09:00+00')
ON CONFLICT (source, source_docket_id) DO NOTHING;


-- ===== PROJECT_DOCKET_PINS SEED =======================================
-- Pin 3-5 relevant dockets per demo project. Each INSERT uses a
-- SELECT from dockets so the docket_id is resolved at apply-time.
-- ON CONFLICT (project_id, docket_id) DO NOTHING → idempotent.

-- Thames BESS Phase 1 (50 MW, UKPN EPN, Z5 London) ─────────────────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'GC0167'       THEN 'G99 Issue 2 drives commissioning timeline for 50 MW DNO-connected BESS at Coryton 132/33kV.'
         WHEN 'CCCM-V19'     THEN 'Z5 (London) zonal boundary under review — affects connection charge bracket for Thames Phase 1.'
         WHEN 'EMR-CM-T4-2029-30' THEN '2h BESS de-rating 18.8% sets CM revenue stack for Thames 100 MWh energy.'
         WHEN 'BSWA-2026'    THEN 'Wider Access rules determine balancing-service revenue path for UKPN-connected BESS.'
         WHEN 'NPPF-DEC-2024' THEN 'Para 168 BESS-in-countryside guidance applies — Thames Haven brownfield meets preferred-location test.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('GC0167','CCCM-V19','EMR-CM-T4-2029-30','BSWA-2026','NPPF-DEC-2024')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Slough Hyperscale DC (40 MW, SSEN SEPD, Z10 Thames Valley) ───────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT 'd0003220-e879-4b19-bc6b-235771f1a517'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'LARGE-LOAD-CONNECT-2026' THEN 'Core framework for DC ≥40 MW demand connection at Iver 132kV — prioritisation score directly affects queue position.'
         WHEN 'DC-POLICY-REVIEW-2026'   THEN 'Ofgem DC policy review determines demand-flex obligations applied to Slough hyperscale.'
         WHEN 'DC-HEAT-REUSE-2026'      THEN 'Mandatory waste-heat reuse consultation — 40 MW IT load exceeds the proposed threshold; needs heat-reuse feasibility study.'
         WHEN 'CCCM-V19'                THEN 'Z10 Thames Valley zonal boundary review affects connection charge for Slough + Iver 132kV GSP.'
         WHEN 'RIIO-ED3'                THEN 'SSEN SEPD ED3 allowances shape connection-charge socialisation for DC loads 2028-33.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('LARGE-LOAD-CONNECT-2026','DC-POLICY-REVIEW-2026','DC-HEAT-REUSE-2026','CCCM-V19','RIIO-ED3')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Culham BESS 500MW (SSEN SEPD, Z10, 400kV transmission-connected) ─────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT '7d728132-211a-487b-a5f2-ba4d05bbe8fc'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'TMO4PLUS-GATE2' THEN 'Gate 2 assessment directly gates Culham 500 MW TEC status — commercial/consenting/land tests apply.'
         WHEN 'EN-3-2025'       THEN 'Revised NPS EN-3 treats 500 MW co-located BESS as NSIP — Culham straddles DCO/TCPA threshold.'
         WHEN 'CCCM-V19'        THEN 'Z10 zonal charge bracket review affects £/MW connection cost at Didcot 400kV GSP.'
         WHEN 'BNG-NSIP-DELAY-2026' THEN 'If Culham lodges DCO post-May 2026, 10% BNG mandatory for NSIP applies.'
         WHEN 'EMR-CM-T4-2029-30' THEN '2h BESS CM de-rating applies to 1000 MWh Culham energy stack.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('TMO4PLUS-GATE2','EN-3-2025','CCCM-V19','BNG-NSIP-DELAY-2026','EMR-CM-T4-2029-30')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Pembroke Power Station BESS 350MW (NGED Wales & West, Z14) ───────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT 'f43a8152-fac0-458f-8e86-bc1267a69833'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'WALES-ENERGY-FRAMEWORK-2026' THEN 'Welsh Gov 350 MW BESS DNS threshold applies — Pembroke Power Station falls under Welsh DNS regime.'
         WHEN 'OFFSHORE-LANDFALL-2026' THEN 'Pembroke coastal site intersects proposed offshore-wind landfall corridor (Celtic Sea Floating Wind Round 5).'
         WHEN 'TMO4PLUS-GATE2' THEN 'Penfro 400kV is transmission-connected — Gate 2 assessment applies.'
         WHEN 'BSWA-2026'      THEN 'Balancing Services Wider Access relevant to 700 MWh Pembroke BESS ancillary revenue.'
         WHEN 'ANCILLARY-ROADMAP-2026' THEN 'Stability Pathfinder Phase 3 tender window aligns with Pembroke commissioning 2027-28.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('WALES-ENERGY-FRAMEWORK-2026','OFFSHORE-LANDFALL-2026','TMO4PLUS-GATE2','BSWA-2026','ANCILLARY-ROADMAP-2026')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Spalding Energy Park BESS 550MW (NGED EMID, Z7) ──────────────────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT 'ada819cb-1bf8-432e-a245-603d29019a51'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'EN-3-2025' THEN '550 MW BESS with ex-CCGT colocation — NPS EN-3 NSIP treatment.'
         WHEN 'BNG-NSIP-DELAY-2026' THEN 'Post-May 2026 DCO lodgement triggers 10% BNG — brownfield CCGT site may qualify for reduced baseline.'
         WHEN 'GC0167'    THEN 'G99 Issue 2 commissioning requirements apply at Spalding 132kV POC.'
         WHEN 'EMR-CM-T4-2029-30' THEN 'Spalding 1100 MWh 2h energy stack CM de-rating = 18.8%.'
         WHEN 'NPPF-DEC-2024' THEN 'Para 162 + 168 support BESS on ex-CCGT brownfield.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('EN-3-2025','BNG-NSIP-DELAY-2026','GC0167','EMR-CM-T4-2029-30','NPPF-DEC-2024')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Necton BESS & Norfolk Vanguard Landfall (NGET, Z6 East) ──────────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT '06cfc2ab-cffc-4504-9a51-79a064140090'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'TMO4PLUS-GATE2' THEN 'Necton 400kV TEC 2223 directly scored under Gate 2 — 100 MW BESS + 5560 MW offshore wind cluster.'
         WHEN 'OFFSHORE-LANDFALL-2026' THEN 'Norfolk Vanguard/Boreas landfall corridor directly affected by new Crown Estate/MMO guidance.'
         WHEN 'AR7-2026'       THEN 'Offshore wind Pot 3 AR7 round open — Vanguard/Boreas revenue stack dependency.'
         WHEN 'ANCILLARY-ROADMAP-2026' THEN 'Inertia/reactive products roadmap relevant to Necton co-located BESS revenue.'
         WHEN 'BNG-NSIP-DELAY-2026' THEN 'Norfolk Vanguard East/West already consented pre-May 2026 — grandfathered; new Boreas variation triggers BNG.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('TMO4PLUS-GATE2','OFFSHORE-LANDFALL-2026','AR7-2026','ANCILLARY-ROADMAP-2026','BNG-NSIP-DELAY-2026')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Lower Farm Drointon BESS 30MW (NGED WMID, Z8) ────────────────────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT 'e641b73f-9b80-4750-8e40-2dccfa9839af'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'GC0167'    THEN 'G99 Issue 2 governs commissioning at Rugeley 132kV for 30 MW DNO-connected BESS.'
         WHEN 'NPPF-DEC-2024' THEN 'Para 168 BESS guidance + para 162 presumption for clean energy support consented site.'
         WHEN 'EMR-CM-T4-2029-30' THEN 'CM revenue stream for 60 MWh 2h BESS — de-rating 18.8%.'
         WHEN 'BSWA-2026' THEN 'BESS-at-distribution BSWA rules enable NGED WMID aggregator participation.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('GC0167','NPPF-DEC-2024','EMR-CM-T4-2029-30','BSWA-2026')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Copper Bottom Solar Farm 30MW (NGED SW, Z15) ─────────────────────────
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT '17485769-9d3d-4354-9d4e-974fbdfda611'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'AR7-2026'  THEN 'Solar Pot 1 AR7 reference price £63/MWh sets revenue floor for 30 MW Copper Bottom.'
         WHEN 'EN-3-2025' THEN '30 MW solar below 50 MW NSIP threshold — TCPA route via Cornwall Council.'
         WHEN 'NPPF-DEC-2024' THEN 'Paras 162/196 (Grey-Belt release) support Cornish agricultural-land solar.'
         WHEN 'GC0167'    THEN 'G99 Issue 2 commissioning at Camborne 132kV POC.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('AR7-2026','EN-3-2025','NPPF-DEC-2024','GC0167')
ON CONFLICT (project_id, docket_id) DO NOTHING;

-- Hinkley Point C Extension (NGET, Z13 South West, 400kV nuclear site) ─
INSERT INTO project_docket_pins (project_id, docket_id, pinned_by, note)
SELECT '85b6fe7a-1de2-4b1d-97fe-11793588b420'::uuid, d.docket_id,
       'seed:2026_04_21d',
       CASE d.source_docket_id
         WHEN 'TMO4PLUS-GATE2' THEN 'HPC 400kV transmission-connected — Gate 2 assessment applies to 100 MW BESS extension.'
         WHEN 'ANCILLARY-ROADMAP-2026' THEN 'Black-start + Stability Pathfinder directly relevant to HPC BESS use-case.'
         WHEN 'RIIO-ED3'  THEN 'NGET transmission charging regime under ED3/RIIO-T3 determines TNUoS exposure.'
         WHEN 'REMA-PHASE2' THEN 'REMA national-pricing decision preserves HPC baseload economics + BESS arbitrage headroom.'
       END
  FROM dockets d
 WHERE d.source_docket_id IN ('TMO4PLUS-GATE2','ANCILLARY-ROADMAP-2026','RIIO-ED3','REMA-PHASE2')
ON CONFLICT (project_id, docket_id) DO NOTHING;

COMMIT;

-- ===== VERIFICATION ==================================================
--   SELECT p.name, count(pin.docket_id) AS pins
--     FROM projects p
--     LEFT JOIN project_docket_pins pin ON pin.project_id = p.project_id
--    WHERE p.name IN ('Thames BESS Phase 1','Slough Hyperscale DC',
--                     'Culham BESS 500MW','Pembroke Power Station BESS 350MW',
--                     'Spalding Energy Park BESS 550MW',
--                     'Necton BESS & Norfolk Vanguard Landfall',
--                     'Lower Farm Drointon BESS 30MW',
--                     'Copper Bottom Solar Farm 30MW',
--                     'Hinkley Point C Extension')
--    GROUP BY p.name ORDER BY p.name;
--     → expect ≥3 pins per project.
-- ----------------------------------------------------------------------
