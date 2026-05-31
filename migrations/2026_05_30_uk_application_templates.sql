-- UK grid + planning application templates repository.
-- Schema-of-record for every regulatory submission a UK energy developer
-- can produce through Princeps. Each row carries the exact field
-- specification (required + optional, types, regex, source authority).

CREATE SCHEMA IF NOT EXISTS applications;

CREATE TABLE IF NOT EXISTS applications.templates (
  template_id        text PRIMARY KEY,
  category           text NOT NULL,        -- grid_connection | planning | environmental | safety | commercial | market
  doc_type           text NOT NULL,        -- G99 | G98 | StatementOfWorks | CDM_F10 | EIA_Screening | …
  title              text NOT NULL,
  authority          text,                 -- DNO | NESO | LPA | HSE | Defra | Ofgem | Companies House
  legal_basis        text,                 -- e.g. "EREC G99 Issue 1 Amd 11 (March 2026)"
  applicable_when    text,                 -- short rule
  generator_fn       text,                 -- python dotted path to a generator (or NULL for spec-only)
  required_fields    jsonb NOT NULL,       -- [{name, type, regex?, options?, description}]
  optional_fields    jsonb DEFAULT '[]'::jsonb,
  output_format      text DEFAULT 'html',  -- html | pdf | json
  sample_url         text,
  evidence_list      jsonb DEFAULT '[]'::jsonb,
  estimated_pages    integer,
  estimated_minutes  integer,              -- rough effort to prepare manually
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_templates_category  ON applications.templates (category);
CREATE INDEX IF NOT EXISTS idx_templates_doc_type  ON applications.templates (doc_type);
CREATE INDEX IF NOT EXISTS idx_templates_authority ON applications.templates (authority);

-- Filings = a concrete pre-filled instance produced for a site/project.
CREATE TABLE IF NOT EXISTS applications.filings (
  filing_rid       text PRIMARY KEY DEFAULT ('rid.princeps.filing.' || gen_random_uuid()::text),
  template_id      text NOT NULL REFERENCES applications.templates(template_id),
  project_rid      text,
  site_rid         text,
  tenant_id        uuid,
  payload          jsonb NOT NULL,
  rendered_html    text,
  rendered_pdf     bytea,
  status           text DEFAULT 'draft',   -- draft | submitted | accepted | rejected
  submitted_at     timestamptz,
  submitted_to     text,                   -- portal URL or contact email
  reference_no     text,                   -- DNO connection ref, planning ref, …
  created_by       text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_filings_project  ON applications.filings (project_rid);
CREATE INDEX IF NOT EXISTS idx_filings_site     ON applications.filings (site_rid);
CREATE INDEX IF NOT EXISTS idx_filings_template ON applications.filings (template_id, status);

-- Idempotent seed: 24 UK grid + planning + commercial templates.
INSERT INTO applications.templates
  (template_id, category, doc_type, title, authority, legal_basis,
   applicable_when, generator_fn, required_fields, optional_fields,
   output_format, evidence_list, estimated_pages, estimated_minutes)
VALUES
-- ── Grid connection ─────────────────────────────────────────────
('g99_application_parts_1_4b', 'grid_connection', 'G99',
 'G99 Application (Parts 1–4b) — Type Tested Generation > 16 A/phase',
 'DNO',
 'EREC G99 Issue 1 Amendment 11 (March 2026)',
 'Embedded generation > 3.68 kW per phase OR storage import/export > 11.04 kW',
 'utils.document_automation.generate_g99_application',
 '[
   {"name":"site","type":"object","description":"Site identity + grid ref (OSGB36)"},
   {"name":"capacity","type":"object","description":"Capacity kW, technology, primary energy source"},
   {"name":"grid","type":"object","description":"Existing supply ID, MPAN, fault level"},
   {"name":"technology","type":"object","description":"Inverter model, EREC G99 type-test certificate ID"}
 ]'::jsonb,
 '[
   {"name":"assessment","type":"object","description":"Pre-app fault level + voltage rise calculation"},
   {"name":"timeline","type":"object","description":"Target energisation date"}
 ]'::jsonb,
 'html',
 '["Type test certificate","Single line diagram","Schedule of equipment","Site location plan"]'::jsonb,
 24, 240),

('g98_application', 'grid_connection', 'G98',
 'G98 Notification — Fully Type Tested Micro-Generators ≤ 16 A/phase',
 'DNO',
 'EREC G98 Issue 1 Amendment 5 (October 2025)',
 'Single-phase ≤ 16 A or three-phase ≤ 16 A per phase, type-tested',
 NULL,
 '[
   {"name":"installer","type":"object","description":"MCS-accredited installer details"},
   {"name":"equipment","type":"object","description":"Type-tested make/model + serial"},
   {"name":"location","type":"object","description":"Connection address + MPAN"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["MCS certificate","Type test certificate","Equipment data sheet"]'::jsonb,
 4, 30),

('statement_of_works_neso', 'grid_connection', 'StatementOfWorks',
 'Statement of Works — NESO Transmission Connection',
 'NESO',
 'CUSC Section 6 + Bilateral Connection Agreement Schedule 1',
 'Generation/storage > 100 MW connecting at 132 kV+',
 NULL,
 '[
   {"name":"project","type":"object","description":"Generator legal entity + parent"},
   {"name":"capacity_mw","type":"number","description":"Capacity in MW (export)"},
   {"name":"location","type":"object","description":"Lat/lon + NESO transmission node"},
   {"name":"connection_voltage_kv","type":"number","options":[132,275,400]},
   {"name":"target_completion","type":"date"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["Single line diagram","Reactive power capability","Earthing study summary","SLD with protection settings"]'::jsonb,
 18, 480),

('modification_application_dno', 'grid_connection', 'ModificationApplication',
 'Modification Application — Existing DNO Connection Capacity Change',
 'DNO',
 'DCUSA Schedule 16',
 'Increase or decrease of agreed import/export capacity on an existing connection',
 NULL,
 '[
   {"name":"existing_connection_ref","type":"string"},
   {"name":"existing_mw","type":"number"},
   {"name":"proposed_mw","type":"number"},
   {"name":"reason","type":"string","description":"E.g. battery augmentation, electrolyser add"}
 ]'::jsonb,
 '[]'::jsonb,
 'html', '[]'::jsonb, 6, 90),

('bca_neso', 'grid_connection', 'BilateralConnectionAgreement',
 'Bilateral Connection Agreement (NESO)',
 'NESO',
 'CUSC Section 2 + Schedule 6 (BCA Template Version 23)',
 'Post Statement of Works acceptance for transmission-connected assets',
 NULL,
 '[
   {"name":"generator","type":"object"},
   {"name":"connection_site","type":"object"},
   {"name":"capacity","type":"object"},
   {"name":"completion_date_iso","type":"date"}
 ]'::jsonb,
 '[]'::jsonb,
 'html', '[]'::jsonb, 80, 1200),

('construction_agreement', 'grid_connection', 'ConstructionAgreement',
 'Construction Agreement — DNO Asset Build',
 'DNO',
 'DCUSA Section 2L',
 'Triggered when the DNO needs to build new assets to enable the connection',
 NULL,
 '[
   {"name":"works_scope","type":"object","description":"Itemised scope and budget"},
   {"name":"payments_schedule","type":"array"},
   {"name":"target_energisation","type":"date"}
 ]'::jsonb,
 '[]'::jsonb,
 'html', '[]'::jsonb, 28, 240),

('embedded_capacity_register', 'grid_connection', 'EmbeddedCapacityRegister',
 'Embedded Capacity Register Submission (NESO/ENA)',
 'NESO',
 'ENA Open Networks Workstream 3 (2024 schema)',
 'All embedded generation > 1 MW must appear on the ECR within 12 months',
 NULL,
 '[
   {"name":"asset_owner","type":"string"},
   {"name":"gsp_group_id","type":"string"},
   {"name":"connection_voltage_kv","type":"number"},
   {"name":"installed_capacity_mw","type":"number"},
   {"name":"primary_resource","type":"string","options":["solar","wind","battery","gas","biomass","other"]}
 ]'::jsonb,
 '[]'::jsonb,
 'json', '[]'::jsonb, 1, 30),

('dcusa_modification', 'grid_connection', 'DCUSAModification',
 'DCUSA Modification Proposal',
 'DCUSA Panel',
 'DCUSA Section 11',
 'Industry change proposal to the Distribution Connection & Use of System Agreement',
 NULL,
 '[
   {"name":"proposer","type":"string"},
   {"name":"defect_description","type":"string"},
   {"name":"proposed_solution","type":"string"},
   {"name":"benefits","type":"string"},
   {"name":"implementation_date","type":"date"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 12, 360),

-- ── Planning ────────────────────────────────────────────────────
('planning_application_1app', 'planning', 'PlanningApplication',
 'Planning Application Summary (1APP key sections)',
 'LPA',
 'Town and Country Planning (Development Management Procedure) (England) Order 2015',
 'Site < 50 MW solar / < 50 MW onshore wind / < 50 MW battery (post AR7 thresholds reviewed)',
 'utils.document_automation.generate_planning_summary',
 '[
   {"name":"site","type":"object"},
   {"name":"capacity","type":"object"},
   {"name":"technology","type":"object"},
   {"name":"constraints","type":"object","description":"AONB / SSSI / Green Belt presence"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["Site location plan","Block plan","DAS","Heritage statement","LVIA","Flood risk assessment"]'::jsonb,
 12, 360),

('nsip_dco_screening', 'planning', 'NSIP_DCO_Screening',
 'NSIP DCO Pre-Application Screening Memo',
 'PINS',
 'Planning Act 2008 + Infrastructure Planning (Applications) Regulations 2009',
 'Solar > 50 MW, onshore wind > 50 MW, battery > 50 MW (subject to current thresholds)',
 NULL,
 '[
   {"name":"project","type":"object"},
   {"name":"capacity_mw","type":"number"},
   {"name":"location","type":"object"},
   {"name":"npss_compliance","type":"object","description":"EN-1 / EN-3 / EN-5 compliance pass"}
 ]'::jsonb,
 '[]'::jsonb,
 'html', '[]'::jsonb, 16, 600),

('eia_screening_request', 'environmental', 'EIA_Screening',
 'EIA Screening Request (Schedule 2 / Schedule 3 criteria)',
 'LPA',
 'Town and Country Planning (EIA) Regulations 2017',
 'All Schedule 2 development above the thresholds',
 'utils.document_automation.generate_eia_screening',
 '[
   {"name":"site","type":"object"},
   {"name":"capacity","type":"object"},
   {"name":"technology","type":"object"},
   {"name":"constraints","type":"object"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["Indicative site layout","Habitat/landscape baseline","Cumulative impacts memo"]'::jsonb,
 8, 240),

('environmental_statement', 'environmental', 'EnvironmentalStatement',
 'Environmental Statement (full EIA)',
 'LPA',
 'Town and Country Planning (EIA) Regulations 2017 Schedule 4',
 'Triggered when EIA screening returns positive',
 NULL,
 '[
   {"name":"chapters","type":"array","description":"Each chapter = ES topic (Landscape, Ecology, Noise, Heritage, Water, Soils, Air, Transport, Climate, Cumulative)"},
   {"name":"nts","type":"string","description":"Non-Technical Summary"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["LVIA","Ecological Impact Assessment","Noise Assessment","Cultural Heritage Assessment","Flood Risk Assessment","Transport Statement","Climate Change Assessment"]'::jsonb,
 220, 4800),

('bng_baseline', 'environmental', 'BNG_Baseline',
 'BNG Baseline Assessment (Statutory Biodiversity Metric 4.0)',
 'Defra',
 'Environment Act 2021 Schedule 7A',
 'Mandatory for all planning applications post Nov 2023 / NSIPs post May 2026',
 'utils.document_automation.generate_bng_baseline',
 '[
   {"name":"site","type":"object"},
   {"name":"capacity","type":"object"},
   {"name":"habitats_baseline","type":"array","description":"Per-habitat area_m2 + condition"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["Statutory Biodiversity Metric workbook","Habitat survey","Condition assessment"]'::jsonb,
 14, 360),

('hra_screening', 'environmental', 'HabitatsRegulationsAssessment',
 'Habitats Regulations Assessment Screening',
 'LPA',
 'Conservation of Habitats and Species Regulations 2017 (as amended)',
 'Required when development could affect a Special Area of Conservation, SPA or Ramsar',
 NULL,
 '[
   {"name":"european_sites_within_15km","type":"array"},
   {"name":"effect_pathways","type":"array"},
   {"name":"likely_significant_effect","type":"boolean"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 10, 240),

('flood_risk_assessment', 'environmental', 'FloodRiskAssessment',
 'Flood Risk Assessment (FRA)',
 'EA',
 'NPPF (2023) Section 14 + EA Standing Advice',
 'Required for all sites in Flood Zones 2 and 3, or > 1ha in Flood Zone 1',
 NULL,
 '[
   {"name":"flood_zone","type":"string","options":["1","2","3a","3b"]},
   {"name":"sequential_test_applied","type":"boolean"},
   {"name":"exception_test_applied","type":"boolean"},
   {"name":"finished_floor_level_m_aod","type":"number"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 22, 600),

('lvia', 'environmental', 'LVIA',
 'Landscape and Visual Impact Assessment',
 'LPA',
 'GLVIA 3rd Edition (Landscape Institute)',
 'Required for large-scale solar (> 10 ha), all wind > 50m to hub, BESS > 50 MW',
 NULL,
 '[
   {"name":"zti","type":"object","description":"Zone of theoretical visibility map"},
   {"name":"viewpoints","type":"array","description":"Per-viewpoint assessment with sensitivity + magnitude"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 40, 960),

-- ── Safety / construction ───────────────────────────────────────
('cdm_f10', 'safety', 'CDM_F10',
 'CDM F10 Notification of Construction Project (HSE)',
 'HSE',
 'CDM Regulations 2015 Reg 6 (Notifiable Project)',
 'Construction phase > 30 days with > 20 workers OR > 500 person-days',
 'utils.document_automation.generate_cdm_f10',
 '[
   {"name":"site","type":"object"},
   {"name":"principal_designer","type":"object"},
   {"name":"principal_contractor","type":"object"},
   {"name":"construction_phase_plan_present","type":"boolean"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 3, 60),

('cdm_dra', 'safety', 'CDM_DesignRiskAssessment',
 'Design Risk Assessment + Designer''s Risk Register (CDM 2015 Reg 9)',
 'HSE',
 'CDM Regulations 2015 Reg 9 + 10',
 'All construction projects — Designer obligation',
 NULL,
 '[
   {"name":"hazards","type":"array","description":"Per hazard: source, harm, who, severity, mitigation"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 12, 360),

-- ── Commercial / market ─────────────────────────────────────────
('licence_exemption_memo', 'commercial', 'LicenceExemptionMemo',
 'Generation Licence Exemption Memo (Class A / B)',
 'Ofgem',
 'Electricity Act 1989 Section 5 + Class Exemptions Order',
 'Generation < 50 MW (Class B) or < 100 MW for stations not connected to a distribution network (Class A)',
 'utils.document_automation.generate_licence_memo',
 '[
   {"name":"capacity_kw","type":"number"},
   {"name":"connection_voltage_kv","type":"number"},
   {"name":"distribution_network","type":"boolean"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 2, 30),

('ar7_cfd_application', 'commercial', 'AR7_CfD',
 'AR7 CfD Sealed Bid Application',
 'LCCC / NESO',
 'CFD Regulations 2014 (as amended) + AR7 Allocation Framework',
 'Pot 1 (established) or Pot 2 (less-established) eligible generation, Jan 2026 round',
 NULL,
 '[
   {"name":"applicant","type":"object"},
   {"name":"project","type":"object"},
   {"name":"capacity_mw","type":"number"},
   {"name":"strike_price_offered","type":"number"},
   {"name":"target_commissioning_window","type":"object"}
 ]'::jsonb,
 '[]'::jsonb,
 'html',
 '["Planning consent","Grid connection offer","Land rights evidence","Supply chain plan (> 300 MW)"]'::jsonb,
 12, 720),

('ppa_heads_of_terms', 'commercial', 'PPA_HeadsOfTerms',
 'Corporate PPA — Heads of Terms',
 'Counterparty',
 'Industry standard (EFET-derived) bilateral PPA',
 'Pre-contract negotiation for direct supply / synthetic / sleeved PPA',
 NULL,
 '[
   {"name":"buyer","type":"object"},
   {"name":"seller","type":"object"},
   {"name":"volume_gwh_per_year","type":"number"},
   {"name":"price_basis","type":"string","options":["fixed","day_ahead_plus","pay_as_produced","baseload"]},
   {"name":"term_years","type":"number"},
   {"name":"shape","type":"string","options":["baseload","pay_as_generated","peak_shaped","custom"]}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 6, 240),

('cm_t1_application', 'commercial', 'CapacityMarket_T1',
 'Capacity Market T-1 Application',
 'NESO',
 'EMR Capacity Market Rules 2025',
 'New build < 25 MW + DSR + battery storage eligible for T-1 auction',
 NULL,
 '[
   {"name":"applicant","type":"object"},
   {"name":"de_rated_capacity_mw","type":"number"},
   {"name":"connection_agreement_ref","type":"string"},
   {"name":"technology_class","type":"string"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 8, 360),

('duos_contract', 'commercial', 'DUoS_Contract',
 'Distribution Use of System Contract',
 'DNO',
 'DCUSA Section 2K',
 'Auto-issued post energisation; sets DUoS charges + metering arrangements',
 NULL,
 '[
   {"name":"customer","type":"object"},
   {"name":"site","type":"object"},
   {"name":"tariff_band","type":"string"}
 ]'::jsonb,
 '[]'::jsonb, 'html', '[]'::jsonb, 28, 120)
ON CONFLICT (template_id) DO NOTHING;
