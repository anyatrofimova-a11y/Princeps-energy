-- Princeps Intelligence seed — populates the Intelligence > Datasets and
-- Intelligence > Alerts surfaces with the curated set of UK energy &
-- planning connectors shown in the original product. Idempotent — every
-- INSERT uses ON CONFLICT (slug/alert_id) DO UPDATE so re-running just
-- refreshes the metadata.

-- ─── Datasets (Intelligence > Datasets tab) ────────────────────────────
INSERT INTO princeps_datasets
  (slug, title, source_url, license, refresh_cadence, table_name,
   last_refreshed_at, last_refresh_ok, last_row_count, health_status,
   health_checked_at, metadata)
VALUES
  ('bmrs_balancing_mechanism',
   'BMRS Balancing Mechanism',
   'https://data.elexon.co.uk/bmrs/api/v1/balancing/dynamic',
   'NETSO Public', '15-min', 'bmrs_balancing',
   NOW() - INTERVAL '2 days', TRUE, 94700000, 'green', NOW(),
   '{"publisher":"Elexon","category":"market","badge":"wired","desc":"Elexon BMRS balancing mechanism — MEL, PN, BOA accepts, system prices, imbalance volumes, settlement runs at 15-minute resolution.","delta_7d":240000,"returns":"Settlement period, BM unit, volume, price"}'::jsonb),

  ('ofgem_publications',
   'Ofgem Publications + Decisions',
   'https://www.ofgem.gov.uk/publications', 'OGL-3.0',
   'daily', 'ofgem_publications',
   NOW() - INTERVAL '2 days', TRUE, 8231, 'green', NOW(),
   '{"publisher":"Ofgem","category":"regulatory","badge":"wired","desc":"Every Ofgem publication — RIIO-T3, RIIO-ED2/ED3, REMA, MSIP, connection charging, licence modifications, compliance notices.","delta_7d":14,"returns":"Decision, consultation, open letter, framework doc"}'::jsonb),

  ('lccc_cfd_reference_price',
   'LCCC CfD Daily Reference Price',
   'https://www.lowcarboncontracts.uk/data-portal/dataset/IMRP',
   'OGL-3.0', 'daily', 'lccc_cfd_prices',
   NOW() - INTERVAL '2 days', TRUE, 9840, 'green', NOW(),
   '{"publisher":"LCCC","category":"market","badge":"wired","desc":"Low Carbon Contracts Company daily IMRP + BMRP + CfD top-up payments. Defines CfD cashflow for every AR-awarded solar, wind, and storage project.","delta_7d":21,"returns":"Trading date, series, price £/MWh"}'::jsonb),

  ('find_a_tender_energy',
   'Find-a-Tender Energy Notices',
   'https://www.find-tender.service.gov.uk',
   'OGL-3.0', 'daily', 'find_a_tender_notices',
   NOW() - INTERVAL '1 day', TRUE, 4218, 'green', NOW(),
   '{"publisher":"Cabinet Office","category":"market","badge":"wired","desc":"UK Find-a-Tender notices filtered to energy + grid CPV codes. Contract opportunity, award and modification notices across public procurement.","delta_7d":63}'::jsonb),

  ('ea_flood_map_planning',
   'EA Flood Map for Planning',
   'https://environment.data.gov.uk/asset-management/index.jsp',
   'OGL-3.0', 'continuous', 'ea_flood_zones',
   NOW() - INTERVAL '6 hours', TRUE, 1248000, 'green', NOW(),
   '{"publisher":"Environment Agency","category":"regulatory","badge":"wired","desc":"Statutory flood zones 2 + 3 with climate-change overlay — a hard planning exclusion for NSIP DCOs and Town & Country Planning applications. OGL v3 via the Defra Spatial Data WFS."}'::jsonb),

  ('princeps_n1_contingency',
   'UK N-1 Contingency Map',
   'https://princeps.energy/grid/n-minus-1',
   'Princeps Proprietary', 'quarterly', 'princeps_n1_contingency',
   NOW() - INTERVAL '14 days', TRUE, 53412, 'green', NOW(),
   '{"publisher":"Princeps","category":"grid","badge":"source_link","desc":"Pre-computed N-1 outage impacts across the GB transmission system. For each primary we enumerate transformer outage, flag downstream feeders that would exceed 100% loading."}'::jsonb),

  ('repd_desnz',
   'REPD — Renewable Energy Planning Database',
   'https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract',
   'OGL-3.0', 'monthly', 'repd_projects',
   NOW() - INTERVAL '11 days', TRUE, 18654, 'green', NOW(),
   '{"publisher":"DESNZ","category":"regulatory","badge":"wired","desc":"DESNZ Renewable Energy Planning Database — every grid-connecting solar, wind, BESS, hydrogen application in the UK with status, capacity, developer, planning consent timelines.","delta_7d":42,"returns":"REPD ID, technology, capacity_mw, status, applicant, planning_authority"}'::jsonb),

  ('nsip_dco_register',
   'PINS NSIP / DCO Register',
   'https://infrastructure.planninginspectorate.gov.uk',
   'OGL-3.0', 'daily', 'pins_nsip_dco',
   NOW() - INTERVAL '12 hours', TRUE, 487, 'green', NOW(),
   '{"publisher":"PINS","category":"regulatory","badge":"wired","desc":"Nationally Significant Infrastructure Projects + Development Consent Orders. Every NSIP from pre-application through to decision — covers solar, BESS, transmission, hydrogen, offshore wind.","delta_7d":3}'::jsonb),

  ('neso_tec_register',
   'NESO TEC Register',
   'https://www.neso.energy/data-portal/dataset/tec-register',
   'OGL-3.0', 'weekly', 'neso_tec',
   NOW() - INTERVAL '4 days', TRUE, 4862, 'green', NOW(),
   '{"publisher":"NESO","category":"grid","badge":"wired","desc":"Transmission Entry Capacity register — every contracted and queued generator on the GB transmission system. The authoritative source for connection queue position and Gate 2 status.","delta_7d":18,"returns":"TEC ID, station, plant_type, capacity_mw, connection_date, status"}'::jsonb),

  ('npg_ecr',
   'Northern Powergrid ECR',
   'https://northernpowergrid.opendatasoft.com',
   'NPg Open Data v1.0', 'daily', 'npg_ecr',
   NOW() - INTERVAL '1 day', TRUE, 12480, 'green', NOW(),
   '{"publisher":"Northern Powergrid","category":"grid","badge":"wired","desc":"Embedded Capacity Register for the Northern Powergrid licence area — every accepted, contracted and energised generator under 132kV."}'::jsonb),

  ('ukpn_ecr',
   'UKPN Embedded Capacity Register',
   'https://ukpowernetworks.opendatasoft.com',
   'UKPN Open Data', 'daily', 'ukpn_ecr',
   NOW() - INTERVAL '1 day', TRUE, 38420, 'green', NOW(),
   '{"publisher":"UKPN","category":"grid","badge":"wired","desc":"UK Power Networks embedded capacity register — every accepted, contracted and energised generator across EPN, LPN, SPN.","delta_7d":42}'::jsonb),

  ('nged_ecr',
   'NGED Embedded Capacity Register',
   'https://connecteddata.nationalgrid.co.uk/dataset/embedded-capacity-register',
   'NGED Open Data v1.0', 'daily', 'nged_ecr',
   NOW() - INTERVAL '1 day', TRUE, 28104, 'green', NOW(),
   '{"publisher":"National Grid Electricity Distribution","category":"grid","badge":"wired","desc":"NGED ECR — embedded generators across South West, South Wales, East and West Midlands."}'::jsonb),

  ('ssen_ecr',
   'SSEN Embedded Capacity Register',
   'https://ckan-prod.sse.energy/dataset/embedded-capacity-register',
   'SSEN Open Data', 'daily', 'ssen_ecr',
   NOW() - INTERVAL '1 day', TRUE, 14802, 'green', NOW(),
   '{"publisher":"SSEN","category":"grid","badge":"wired","desc":"Scottish & Southern Electricity Networks ECR — Scotland (north of Edinburgh) + Southern England embedded generators."}'::jsonb),

  ('hmlr_ccod',
   'HM Land Registry Corporate Ownership',
   'https://use-land-property-data.service.gov.uk/datasets/ccod',
   'OGL-3.0', 'monthly', 'hm_land_registry_ccod',
   NOW() - INTERVAL '4 days', TRUE, 4280000, 'green', NOW(),
   '{"publisher":"HM Land Registry","category":"regulatory","badge":"wired","desc":"Every company-held freehold or leasehold title in England & Wales. The authoritative source for landowner identification on candidate sites.","delta_7d":12000}'::jsonb),

  ('hse_riddor',
   'HSE RIDDOR Incidents',
   'https://www.hse.gov.uk/statistics/index.htm',
   'OGL-3.0', 'monthly', 'hse_riddor_incidents',
   NOW() - INTERVAL '8 days', TRUE, 89240, 'green', NOW(),
   '{"publisher":"HSE","category":"regulatory","badge":"wired","desc":"Health & Safety Executive — Reporting of Injuries, Diseases and Dangerous Occurrences Regulations dataset. Used for BESS / DC site-safety benchmarking."}'::jsonb),

  ('entsoe_da_gb',
   'ENTSO-E Day-Ahead Prices (GB)',
   'https://transparency.entsoe.eu',
   'ENTSO-E open data', 'hourly', 'entsoe_da_prices_gb',
   NOW() - INTERVAL '1 hour', TRUE, 87600, 'green', NOW(),
   '{"publisher":"ENTSO-E","category":"market","badge":"wired","desc":"Day-ahead wholesale electricity prices for the GB market area. Used by BESS revenue stack + dispatch optimisation."}'::jsonb),

  ('capacity_market_register',
   'Capacity Market Register',
   'https://www.emrdeliverybody.com',
   'EMR Open Data', 'monthly', 'capacity_market_register',
   NOW() - INTERVAL '6 days', TRUE, 6240, 'green', NOW(),
   '{"publisher":"EMR Delivery Body","category":"market","badge":"wired","desc":"Capacity Market T-1/T-4 auction results and unit-level Capacity Agreements. Required for BESS revenue stack and ICO modelling."}'::jsonb),

  ('carbon_intensity_api',
   'National Grid ESO Carbon Intensity API',
   'https://api.carbonintensity.org.uk',
   'CC-BY-4.0', 'realtime', 'carbon_intensity',
   NOW() - INTERVAL '5 minutes', TRUE, 105120, 'green', NOW(),
   '{"publisher":"NESO","category":"grid","badge":"wired","desc":"Live GB carbon intensity by region — 30-minute resolution. Drives PPA carbon accounting + green CfD strike-price modelling."}'::jsonb),

  ('bmrs_settlement_prices',
   'BMRS Imbalance Settlement Prices',
   'https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement',
   'NETSO Public', '30-min', 'bmrs_settlement_prices',
   NOW() - INTERVAL '30 minutes', TRUE, 17520, 'green', NOW(),
   '{"publisher":"Elexon","category":"market","badge":"wired","desc":"30-minute imbalance settlement prices — system buy / sell prices used by BESS for cash-out forecasting."}'::jsonb),

  ('modo_benchmark',
   'Modo Energy BESS Benchmark',
   'https://modo.energy/data',
   'Modo Energy', 'daily', 'modo_benchmark',
   NOW() - INTERVAL '1 day', TRUE, 4860, 'green', NOW(),
   '{"publisher":"Modo Energy","category":"market","badge":"partial","desc":"Modo Energy public Index — daily BESS revenue benchmark across 1h, 2h and 4h durations. Used as the dashed overlay on the Live BESS Revenue tile."}'::jsonb),

  ('planning_data_gov_uk',
   'planning.data.gov.uk Designations',
   'https://www.planning.data.gov.uk',
   'OGL-3.0', 'daily', 'planning_designations',
   NOW() - INTERVAL '1 day', TRUE, 91381, 'green', NOW(),
   '{"publisher":"DLUHC","category":"regulatory","badge":"wired","desc":"21 Top-priority designations — green belt, AONB, SSSI, ancient woodland, listed buildings, flood zones, conservation areas, scheduled monuments, SPA/SAC/Ramsar, brownfield, TPZ, A4 directions. The full UK planning constraint stack.","delta_7d":380}'::jsonb)

ON CONFLICT (slug) DO UPDATE SET
  title = EXCLUDED.title,
  source_url = EXCLUDED.source_url,
  license = EXCLUDED.license,
  refresh_cadence = EXCLUDED.refresh_cadence,
  last_refreshed_at = EXCLUDED.last_refreshed_at,
  last_refresh_ok = EXCLUDED.last_refresh_ok,
  last_row_count = EXCLUDED.last_row_count,
  health_status = EXCLUDED.health_status,
  metadata = EXCLUDED.metadata,
  updated_at = NOW();
