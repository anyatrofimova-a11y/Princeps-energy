# UK Planning & Regulatory Intelligence Research
## Comprehensive Data Sources, ML Approaches, and Competitor Analysis

*Research date: 2026-03-21*

---

## 1. UK PLANNING DATA SOURCES

### 1.1 REPD — Renewable Energy Planning Database

**The single most important dataset for training an ML model on UK renewable energy planning outcomes.**

- **URL**: https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract
- **Data.gov.uk**: https://www.data.gov.uk/dataset/a5b0ed13-c960-49ce-b1f6-3a6bbe0db1b7/repd
- **Download (latest Q4 2025)**: CSV (4.64 MB) and XLSX (4.76 MB) from assets.publishing.service.gov.uk
- **Format**: CSV / XLSX (quarterly release)
- **Update frequency**: Quarterly (month following quarter end)
- **Coverage**: All UK renewable electricity projects >= 150kW (lowered from 1MW in 2021)
- **Managed by**: Barbour ABI on behalf of DESNZ
- **Free/Open**: Yes — Open Government Licence

**Complete REPD Field List (43 fields):**

| Field | Type | Notes |
|-------|------|-------|
| Old Ref ID | string | Previous version reference |
| Ref ID | integer | Project reference number |
| Record Last Updated | date | dd/mm/yyyy |
| Operator (or Applicant) | string | Developer name |
| Site Name | string | |
| Technology Type | string | Solar PV, onshore wind, offshore wind, biomass, etc. |
| Storage Type | string | Co-located / Stand-alone |
| Storage Co-location REPD Ref ID | string | |
| Installed Capacity (MWelec) | number | |
| CHP Enabled | string | Yes/No |
| RO Banding (ROC/MWh) | number | |
| FiT Tariff (p/kWh) | number | |
| CfD Capacity (MW) | number | |
| Turbine Capacity (MW) | number | Per-turbine |
| No. of Turbines | number | |
| Height of Turbines (m) | number | |
| Mounting Type for Solar | string | Ground / Roof |
| Development Status | string | Full status |
| Development Status (short) | string | Abbreviated |
| Address | string | |
| County | string | |
| Region | string | |
| Country | string | |
| Post Code | string | |
| X-coordinate | integer | EPSG:27700 |
| Y-coordinate | integer | EPSG:27700 |
| Planning Authority | string | Local planning body |
| Planning Application Reference | string | |
| Appeal Reference | string | |
| Secretary of State Reference | string | |
| Type of Secretary of State Intervention | string | Recovery / Call-in / Holding direction |
| Judicial Review | integer | |
| Offshore Wind Round | string | |
| Planning Application Submitted | date | |
| Planning Application Withdrawn | date | |
| Planning Permission Refused | date | |
| Appeal Lodged | date | |
| Appeal Withdrawn | date | |
| Appeal Refused | date | |
| Appeal Granted | date | |
| Planning Permission Granted | date | |
| Secretary of State - Intervened/Refusal/Granted | dates | |
| Planning Permission Expired | date | |
| Under Construction | date | |
| Operational | date | |
| Heat Network Ref | integer | |

**Key stats**: ~6,000+ projects across all technologies. Date fields allow computing approval timelines, appeal rates, SoS intervention frequency.

---

### 1.2 Planning Inspectorate Appeals Database

- **URL**: https://www.gov.uk/government/publications/planning-inspectorate-appeals-database
- **Download**:
  - Casework Database (21.8 MB XLSX): https://assets.publishing.service.gov.uk/media/697ca4a384f2153b1124525e/Casework_Database_Q3.xlsx
  - Older Casework Data (12.5 MB XLSX): https://assets.publishing.service.gov.uk/media/697ca4bbedc921ef1a24525a/Older_Casework_Data_Q3.xlsx
- **Format**: XLSX (Excel)
- **Records**: ~91,000 appeal cases (5-year rolling) + older data (5-10 years)
- **Coverage**: England only
- **Update**: Quarterly
- **Free/Open**: Yes
- **Includes**: Planning appeals, enforcement appeals, Community Infrastructure Levy, hedgerow, high hedges, TPO, rights of way
- **~50 variables** per record — field documentation available in accompanying guidance doc
- **Contact**: statistics@planninginspectorate.gov.uk
- **SPARQL endpoint**: http://opendatacommunities.org/sparql

**WARNING**: The Open Data Communities platform (where API access lived) is being sunset from March 2025. Download XLSX directly from GOV.UK.

---

### 1.3 Planning Data Platform (MHCLG)

- **URL**: https://www.planning.data.gov.uk/
- **API Docs**: https://www.planning.data.gov.uk/docs
- **OpenAPI Spec**: https://www.planning.data.gov.uk/openapi.json
- **Status**: Beta (experimental — not recommended for production yet)
- **Free/Open**: Yes — open source on GitHub
- **Format**: JSON, GeoJSON, CSV

**API Endpoints:**

| Endpoint | Method | Parameters |
|----------|--------|------------|
| `/entity.{json\|geojson}` | GET | q (postcode/UPRN), longitude, latitude, geometry, dataset, typology, organisation_entity, entity, start_date, end_date, limit, offset |
| `/entity/{entity}.{json\|geojson}` | GET | entity ID |
| `/dataset.json` | GET | dataset array, field selection |
| `/dataset/{dataset}.json` | GET | specific dataset |
| `/entity/dataset-name-search.json` | GET | search, dataset, limit |

**Key datasets available**: planning applications, conservation areas, listed buildings, tree preservation orders, article 4 directions, brownfield land, flood zones, green belt, and ~200+ others.

---

### 1.4 Planning London Datahub

- **URL**: https://planninglondondatahub.london.gov.uk/
- **API Base URL**: `https://planningdata.london.gov.uk/api-guest/`
- **API Docs**: https://www.london.gov.uk/sites/default/files/planninglondondatahub_api_connection_technical_documentation_v1.pdf
- **Format**: JSON (Elasticsearch 7.9 REST API)
- **Coverage**: All 33 London boroughs
- **Update**: Daily (real-time as boroughs validate applications)
- **Free/Open**: Yes (guest access, no API key required for basic queries)
- **Contact**: The GLA Planning team

**Endpoints:**
- `applications/_source/{application-id}` — single application
- `applications/_search` — query multiple applications

---

### 1.5 MHCLG Planning Decisions Statistics

- **URL**: https://opendatacommunities.org/data/planning/decisions/
- **Format**: CSV, linked data (SPARQL)
- **Coverage**: England, district-level aggregated
- **Datasets**:
  - Major & Minor Developments by Outcome
  - Other Developments by Outcome
  - All Developments by Speed of Decision
- **Free/Open**: Yes
- **GOV.UK statistics**: https://www.gov.uk/government/statistics/planning-applications-in-england-october-to-december-2024

---

### 1.6 LG Inform Plus — Planning Applications Schema

- **Schema**: https://schemas.opendata.esd.org.uk/PlanningApplications
- **Example CSV**: https://schemas.opendata.esd.org.uk/PlanningApplications/example-planning-applications.csv
- **Validator**: https://validator.opendata.esd.org.uk/PlanningApplications

**36 standardized fields** across local authorities:
ExtractDate, PublisherURI/Label, OrganisationURI/Label, CaseReference, CaseURL, CaseDate, ServiceTypeURI/Label, ClassificationURI/Label, CaseText, LocationText, DecisionTargetDate, Status, CoordinateReferenceSystem, GeoX, GeoY, GeoPointLicensingURL, DecisionDate, Decision, DecisionType, DecisionNoticeDate, AppealRef, AppealDecisionDate, AppealDecision, GeoAreaURI/Label, GroundArea, UPRN, Agent, PublicConsultationStartDate/EndDate, ResponsesFor, ResponsesAgainst

**Critically important**: `ResponsesFor` and `ResponsesAgainst` fields enable sentiment/opposition modelling.

---

### 1.7 MHCLG Digital Land — Planning Application Data Specification

- **GitHub**: https://github.com/digital-land/planning-application-data-specification
- **Spec page**: https://digital-land.github.io/specification/dataset/planning-application/
- **Status**: Active development (MHCLG calling for validation feedback as of April 2025)
- **Scope**: 21 compiled specifications across all main application types, 83 reusable components, 29 codelists

**Core Planning Application Dataset Fields:**

| Field | Type |
|-------|------|
| address-text | string |
| decision-date | datetime |
| description | string |
| development-classification | string |
| documentation-url | url |
| entity | integer |
| geometry | multipolygon |
| ground-area | decimal |
| name | string |
| notes | text |
| organisation | curie |
| planning-application-status | string |
| planning-application-type | string |
| planning-decision | string |
| planning-decision-type | string |
| point | point |
| reference | string |
| uprn | string |

---

### 1.8 NSIP Register — National Infrastructure Projects

- **URL**: https://national-infrastructure-consenting.planninginspectorate.gov.uk/
- **Old URL**: https://infrastructure.planninginspectorate.gov.uk/
- **Format**: Web search + individual project pages (no bulk download or API yet)
- **Coverage**: All NSIPs in England and Wales (energy, transport, water, waste)
- **Planned**: Boundary outlines and downloadable geospatial data (future)
- **Free/Open**: Yes, but no programmatic access currently

**For energy NSIPs, key thresholds (post Planning & Infrastructure Act 2025):**
- Onshore wind: >100MW
- Solar: >100MW (raised from 50MW)
- Data centres: opt-in NSIP route for nationally significant projects

---

### 1.9 Section 36 Consents (Electricity Act 1989)

- **No centralized register**. Applications appear on local planning authority registers.
- **Applies to**: Generating stations in England & Wales requiring Secretary of State consent
- **Now largely superseded by**: Development Consent Orders (DCO) under the Planning Act 2008 for projects >50MW
- **Historical data**: Available through individual local authority planning registers

---

## 2. ENVIRONMENTAL & CONSTRAINT DATA SOURCES

### 2.1 Natural England Open Data Geoportal

- **URL**: https://naturalengland-defra.opendata.arcgis.com/
- **Format**: Shapefile, GeoJSON, API (ArcGIS REST), WMS/WFS
- **Free/Open**: Yes (Open Government Licence)

**Key datasets for planning ML:**
| Dataset | URL |
|---------|-----|
| SSSIs | https://www.data.gov.uk/dataset/5b632bd7-9838-4ef2-9101-ea9384421b0d |
| SACs | https://www.data.gov.uk/dataset/a85e64d9-d0f1-4500-9080-b0e29b81fbc8 |
| SPAs | naturalengland-defra.opendata.arcgis.com |
| SSSI Impact Risk Zones | https://www.data.gov.uk/dataset/5ae2af0c-1363-4d40-9d1a-e5a1381449f8 |
| National Landscapes (AONBs) | naturalengland-defra.opendata.arcgis.com |
| National Parks | naturalengland-defra.opendata.arcgis.com |
| Agricultural Land Classification | naturalengland-defra.opendata.arcgis.com |
| Priority Habitat Inventory | naturalengland-defra.opendata.arcgis.com |
| Ancient Woodland | naturalengland-defra.opendata.arcgis.com |

### 2.2 Historic England

- **NHLE API**: https://www.api.gov.uk/he/national-heritage-list-for-england-nhle/
- **GIS Downloads**: https://historicengland.org.uk/listing/the-list/data-downloads/
- **Open Data Hub**: https://opendata-historicengland.hub.arcgis.com/
- **Format**: Shapefile, CSV, ArcGIS REST
- **Datasets**: Listed buildings, scheduled monuments, registered parks & gardens, registered battlefields, protected wrecks, conservation areas
- **Free/Open**: Yes

### 2.3 Environment Agency Flood Data

- **Flood Monitoring API**: https://environment.data.gov.uk/flood-monitoring/doc/reference
- **API Catalogue**: https://www.api.gov.uk/ea/flood-monitoring/
- **Flood Map for Planning**: https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47
- **Format**: JSON API, GeoJSON, Shapefile
- **Free/Open**: Yes (Open Government Licence, no registration required)
- **Data includes**: Flood zones 2 & 3, flood storage areas, flood defences, water level monitoring

### 2.4 MAGIC (Multi-Agency Geographic Information for the Countryside)

- **URL**: https://magic.defra.gov.uk/
- **Dataset Download**: https://magic.defra.gov.uk/Dataset_Download_Summary.htm
- **Coverage**: 400+ environmental datasets
- **Format**: WMS, WFS, Shapefile downloads
- **Free/Open**: Yes

### 2.5 ONS Open Geography Portal

- **URL**: https://geoportal.statistics.gov.uk/
- **Format**: Shapefile, GeoJSON, API
- **Key data**: Local authority boundaries, constituency boundaries, census geographies, urban/rural classification
- **Free/Open**: Yes

### 2.6 JNCC Protected Area Datasets

- **URL**: https://jncc.gov.uk/our-work/uk-protected-area-datasets-for-download/
- **Coverage**: UK-wide SACs, SPAs, Ramsar sites
- **Format**: Shapefile, spreadsheets
- **Free/Open**: Yes

---

## 3. REGULATORY FRAMEWORK SUMMARY

### 3.1 Key Policy Documents

| Document | Status | Key Provisions |
|----------|--------|----------------|
| **NPPF** (Dec 2024 revision) | In force | Para 168: "significant weight" to renewable energy benefits. Green Belt "very special circumstances" for renewables. Data centres now mentioned. |
| **EN-1** (2025) | In force | Overarching energy NPS. Updated for Clean Power 2030 mission. Critical National Priority policy. |
| **EN-3** (2025) | In force | Renewable energy infrastructure NPS. Onshore wind reintroduced to NSIP. Wake effects guidance. Covers biomass, offshore wind, pumped hydro, solar PV, tidal stream, onshore wind. |
| **Planning & Infrastructure Act 2025** | Royal Assent 18 Dec 2025 | NSIP streamlining, onshore wind >100MW back in NSIP, solar threshold raised to >100MW, LDES cap-and-floor, grid connection reforms. |
| **BNG Regulations** (Feb 2024) | Mandatory | 10% biodiversity net gain required. 30-year management commitment. Metric-based assessment. |
| **EIA Regulations 2017** | In force | Schedule 2 screening thresholds (see below). |
| **CDM Regulations 2015** | In force | Construction health & safety. Principal Designer appointment required. |
| **ETSU-R-97** (updated 2025) | Updated guidance | Wind turbine noise assessment. Day 35-40dB / Night 43dB limits or background +5dB. |

### 3.2 EIA Schedule 2 Thresholds for Energy

| Development Type | Threshold |
|-----------------|-----------|
| Industrial installations for electricity (3(a)) — *includes solar* | Site area > 0.5 hectares |
| Wind farms (3(i)) | >2 turbines OR hub height >15m |
| Hydroelectric (3(h)) | >0.5 MW |
| Surface storage of natural gas (3(c)) | All development |
| Underground storage combustible gases (3(d)) | All development |

Solar PV farms are not explicitly listed but fall under 3(a) "industrial installations for the production of electricity" when >0.5 hectares.

### 3.3 NSIP Thresholds (post-2025)

| Technology | Threshold | Decision-maker |
|-----------|-----------|----------------|
| Onshore wind (England) | >100MW | Secretary of State (DCO) |
| Solar PV (England) | >100MW | Secretary of State (DCO) |
| Offshore wind | >100MW | Secretary of State (DCO) |
| BESS | No NSIP threshold | Local planning authority (any size) |
| Data centres | Opt-in NSIP | SoS direction under s.35 if "nationally significant" |
| Below threshold | <100MW | Local planning authority (TCPA) |

### 3.4 Consenting Regime Overview

| Consent/Licence | Authority | When Required |
|----------------|-----------|---------------|
| Planning permission (TCPA) | Local planning authority | <100MW onshore |
| Development Consent Order (DCO) | Secretary of State via PINS | >100MW (NSIP) |
| Generation licence | Ofgem | Required unless exempt (<10-50MW Class A) |
| Grid connection (G99) | DNO | >3.68kW single-phase |
| Grid connection (G100 export limitation) | DNO | When export limit imposed |
| EIA screening | LPA | Schedule 2 development (see above) |
| Habitats Regulations Assessment | LPA + Natural England | Near SAC/SPA/Ramsar |
| Water abstraction licence | Environment Agency | >20 m3/day |
| Marine licence | MMO | Offshore/coastal |
| Seabed lease | Crown Estate | Offshore |
| CDM notification | HSE | All construction projects |
| BEIS/DESNZ Section 36 | Secretary of State | Historical (pre-2008 Act projects) |
| CfD/ROC accreditation | LCCC/Ofgem | For subsidy support |
| BNG plan approval | LPA | All new developments (since Feb 2024) |

### 3.5 Top 10 Reasons Solar/Wind/BESS Applications Get Refused

1. **Loss of Best & Most Versatile agricultural land** (Grade 1, 2, 3a)
2. **Landscape and visual impact** — especially in AONBs/National Landscapes
3. **Harm to heritage assets** — listed buildings, conservation areas, scheduled monuments
4. **Green Belt — inappropriate development** without "very special circumstances"
5. **Ecological harm** — impact on protected species, habitats, insufficient BNG
6. **Residential amenity** — noise (wind), glint/glare (solar), visual dominance
7. **Flood risk** — sites in Flood Zones 2/3 without sequential test
8. **Cumulative impact** — too many renewable developments in one area
9. **Highway safety and access** — construction traffic, insufficient access roads
10. **Public opposition** — volume of objection letters (correlates with refusal)

### 3.6 Data Centre Specific Regulations

- **NSIP status**: Parliament approved NSIP opt-in for data centres (Nov 2025). Secretary of State may direct under s.35 if "nationally significant"
- **NPS for data centres**: DSIT drafting a new NPS (thresholds/parameters TBD)
- **AI Growth Zones**: Designated in Oxfordshire, South/North Wales, North East, Lanarkshire. Backed by £4.5M planning expert fund
- **NPPF**: Dec 2024 reforms require LPAs to consider data centre needs in local plans
- **Flood risk**: Data centres classified as "essential infrastructure" — can be in Flood Zone 3 with appropriate mitigation
- **Water abstraction**: EA tightening criteria — Water Framework Directive compliance required
- **Power**: Hyperscale >100MW load. ~140 projects seeking 50GW total grid capacity. TM04+ connection reforms (first ready, first needed, first connected)
- **Noise**: Standard BS 4142 assessment applies. Cooling systems are primary concern
- **Flexibility requirement**: Potential mandatory demand flexibility as connection condition

---

## 4. COMPETITOR ANALYSIS — PLANNING INTELLIGENCE

### 4.1 Searchland

- **URL**: https://searchland.co.uk/
- **API Docs**: https://docs.searchland.co.uk/
- **Coverage**: 23.9 million planning applications, 500K+ appeals, updated every 24 hours
- **Data since**: 1990
- **Auth**: Bearer token
- **Pricing**: Credit-based (annual contract)

**API Endpoints:**
- `GET/POST /planning_applications/search` — area-based search (1 credit/20 results)
- `GET /planning_applications/get` — individual application (1 credit)
- `GET /constraints/check_title` — constraints on a title (1 credit)
- `GET /allocation/list` — site allocations
- `GET /titles/search` — ownership data
- `GET /local_plan_policy/get` — local plan policies
- Plus: SHLAA, price paid, TPO, Article 4, HMO, MVT tiles, OGC endpoints

**Constraints data**: Heritage, natural/protected areas, flood zones, agricultural land, Article 4, nutrient neutrality, Coal Authority, London-specific datasets.

### 4.2 LandInsight (Land Technologies)

- **URL**: https://land.tech/products/landinsight
- **API Docs**: https://landinsight.docs.apiary.io/
- **API URL**: https://land.tech/api
- **Key features beyond Princeps**:
  - Ownership data (title numbers, lease info, persons of significant control)
  - Constraint layering (Green Belt, flood zones, Article 4, heritage)
  - Building height, floor area, EPC ratings per parcel
  - Housing delivery targets, CIL charges, 5-year housing land supply
  - Substation details (type, voltage, capacity RAG)
  - Homes England developable sites
  - Sites coming to market within 6 months

### 4.3 Glenigan

- **URL**: https://www.glenigan.com/
- **API Docs**: https://www.gleniganapi.com/docs_glenigan/
- **Coverage**: 500,000+ planning applications/year, 30,000+ daily updates
- **Team**: 100+ researchers for larger projects
- **Pricing**: Enterprise (contact for quote)
- **Key differentiator**: Combined planning + construction leads + main contract awards
- **Used by**: ONS for construction statistics

### 4.4 LandHawk

- **URL**: https://www.landhawk.uk/
- **API Docs**: https://docs.landhawk.uk/
- **Coverage**: 99% of UK local authority planning data
- **Update**: Hourly
- **Pricing**: From £299/month
- **Differentiator**: WMS + JSON APIs, additional search params (development size, formal consent, status)

### 4.5 Barbour ABI

- **URL**: https://barbour-abi.com/
- **APIs**: Locations API + Projects API
- **Key role**: Manages REPD on behalf of DESNZ
- **Differentiator**: Telephone-researched project intelligence, "Just Ask" AI search
- **Interactive REPD map**: https://data.barbour-abi.com/smart-map/repd/desnz/

### 4.6 Pager Power

- **URL**: https://www.pagerpower.com/
- **Speciality**: Glint & glare (1,700+ assessments), wind turbine noise, shadow flicker, radar/aviation (1,000+ assessments)
- **Not a data platform** — consultancy with proprietary assessment software
- **No API**

### 4.7 Cornwall Insight / Eden Seven

- **Cornwall Insight**: https://www.cornwall-insight.com/ — energy market analysis, planning approval statistics
- **Eden Seven**: https://www.edenseven.co.uk/ — quarterly REPD analysis, renewable energy approval tracking
- **Not data APIs** — analytical reports

### 4.8 Urban Intelligence

- **URL**: https://www.urbanintelligence.co.uk/
- **Product**: PlaceMaker — for local authorities
- **Focus**: Local plan development, Call for Sites, suitability/capacity analysis
- **Not a developer-facing API**

### 4.9 What Competitors Offer That Princeps Does NOT (Yet)

1. **Ownership data** (title numbers, lease info, beneficial ownership) — Searchland, LandInsight
2. **23.9M historical planning applications** with decisions — Searchland
3. **500K+ appeals with inspectorate links** — Searchland
4. **Constraint checking per title/parcel** — Searchland, LandInsight
5. **Local plan policy data** (housing targets, CIL, 5YHLS) — Searchland, LandInsight
6. **Site allocation data** (SHLAA, local plan allocations) — Searchland, LandInsight
7. **Glint & glare proprietary modelling** — Pager Power
8. **Construction leads** (contractor, timelines, values) — Glenigan, Barbour ABI
9. **Planning outcome prediction ML model** — NOBODY has this publicly

---

## 5. ML MODEL ARCHITECTURE FOR PLANNING OUTCOME PREDICTION

### 5.1 Academic Foundation

**Key paper**: "Here comes the sun: Determinants of solar farm planning at local authority level in England" (Hussain, Concetti, Toke et al., 2025, Energy Research & Social Science)
- **Method**: Logistic regression + Coarsened Exact Matching
- **Data**: REPD + planning officer reports
- **Key finding**: Success relies on recommendations from institutional actors and public support, not advocacy groups. Landscape context and planning guidelines are critical.
- **Variables**: BMV land classification, Conservative party affiliation of LPA, environmental impacts, network support configurations

**Alan Turing Institute** (2019 Data Study Group with Agile Datum):
- Trained deep learning (Mask-RCNN) on planning documents for classification
- Found 80% of rejections come from 12 common mistakes
- Focus was document validation, not outcome prediction

**Economic NIMBY research** (UC Berkeley / Chicago):
- ~4,000 large wind and solar projects in UK over 30 years
- Wind: <50% approval rate; Solar: ~80% approval rate
- NIMBYism raises cost of wind power by 10-29%
- Planning officials sensitive to local costs, especially in wealthy areas

### 5.2 Proposed Feature Engineering

**From REPD (direct features):**
- Technology type (solar/wind/BESS/biomass)
- Installed capacity (MW)
- Mounting type (ground/roof for solar)
- Number/height of turbines (wind)
- Planning authority (categorical, ~350 LPAs)
- Region/country
- Time features (month/year of submission)

**Geospatial constraint features (overlay analysis):**
- Distance to nearest SSSI (m)
- Inside/distance to AONB/National Landscape
- Inside/distance to Green Belt
- Inside/distance to Conservation Area
- Distance to nearest listed building
- Flood zone classification (1/2/3a/3b)
- Agricultural Land Classification grade (1/2/3a/3b/4/5)
- Distance to nearest residential property
- Distance to nearest road (A-road, motorway)
- Distance to nearest substation/grid connection point
- Inside/distance to National Park
- Proximity to ancient woodland
- SSSI Impact Risk Zone intersection
- Terrain slope and aspect (from NASADEM)
- Land use (from DynamicWorld/GeeFlow)

**Socio-economic features:**
- Index of Multiple Deprivation (IMD) of ward
- Population density
- Rural/urban classification
- Political control of local authority
- Housing delivery test performance
- Previous renewable energy applications in same LPA (approval rate)
- Count of existing renewable installations within 5km

**Application-specific features:**
- EIA screening required (boolean)
- Is the site brownfield/greenfield
- Does application include community benefit
- Is there a grid connection offer

**NLP-derived features (from decision notices / officer reports):**
- Objection count (ResponsesAgainst from LG Inform schema)
- Support count (ResponsesFor)
- Sentiment score of officer recommendation
- Key risk topics mentioned (landscape, heritage, ecology, flood, noise, glint)
- Planning conditions count and type
- Previous refusal on same site

### 5.3 Recommended Model Stack

```
Layer 1: XGBoost / LightGBM ensemble
  - Tabular features (REPD + geospatial + socioeconomic)
  - SHAP for feature importance and explainability
  - Handles missing data well (common in planning records)

Layer 2: NLP Model (BERT/RoBERTa fine-tuned)
  - Planning officer reports → extract risk signals
  - Decision notices → condition extraction
  - Public objection letters → sentiment and topic classification

Layer 3: Graph Neural Network (optional)
  - Model relationships: LPA ↔ inspector ↔ appeal outcome
  - Spatial adjacency of applications

Ensemble: Stacking meta-learner combining all layers
```

### 5.4 Training Data Pipeline

```
1. REPD CSV → label: granted/refused/withdrawn/appeal_granted/appeal_refused
2. Geocode X,Y → PostGIS point
3. Spatial overlay against all constraint layers (ST_Intersects, ST_DWithin)
4. Join PINS appeals database on appeal reference
5. Join LPA statistics (IMD, political control, HDT)
6. Scrape decision notices and officer reports via LPA portals
7. NLP pipeline: extract features from text
8. Feature matrix → train/test split (time-based, not random)
9. Train XGBoost + SHAP
10. Validate on held-out recent applications
```

### 5.5 Prediction Outputs

For each proposed development site, the model would output:
- **P(Granted)** — probability of planning permission
- **P(Refused)** — probability of refusal
- **P(Appeal Success)** — if refused, probability of winning appeal
- **Top 5 risk factors** — SHAP-explained (e.g., "BMV Grade 3a land", "within 2km of AONB")
- **Estimated timeline** — months to decision
- **Comparable precedents** — similar approved/refused projects in area
- **Recommended mitigations** — based on patterns in successful similar applications

---

## 6. LEGAL COMPLIANCE AUTOMATION

### 6.1 Pre-Construction Regulatory Checklist

| Check | Authority | Data Source | Automatable? |
|-------|-----------|-------------|-------------|
| Planning permission status | LPA | Searchland/LandHawk API | Yes |
| EIA screening determination | LPA | EIA Regulations Schedule 2 + site data | Yes (rule-based) |
| Habitats Regulations Assessment | Natural England | SAC/SPA/Ramsar spatial data | Partially |
| BNG metric calculation | Ecologist | Defra Biodiversity Metric 4.0 | Partially |
| Flood risk sequential test | EA | Flood map API | Yes |
| Heritage impact assessment | Historic England | NHLE API + spatial overlay | Yes (screening) |
| Agricultural land classification | Natural England | ALC spatial data | Yes |
| Glint & glare assessment | Pager Power / LPA | Solar geometry + receptor mapping | Yes (model) |
| Noise assessment (ETSU-R-97) | LPA | Turbine specs + receptor distances | Yes (model) |
| G99 grid connection application | DNO | Grid data | Partially |
| CDM Principal Designer appointment | HSE | Project management | No (process) |
| Ofgem generation licence | Ofgem | Capacity check | Yes (threshold) |
| CfD eligibility check | LCCC/DESNZ | Previous accreditation check | Yes |
| Water abstraction licence | EA | Abstraction data + WFD status | Partially |
| Fire safety (BESS) | FRS | NFCC position statement | Partially (checklist) |

### 6.2 NLP for Condition Extraction

Research at the built environment level (SPaR.txt — validated on 420 UK regulatory documents) demonstrates NLP can:
- Identify multi-word expressions in regulatory documents
- Extract requirements labeled as "permission", "obligation", "condition", "exception"
- Map conditions to compliance checks

**Application to planning**: Extract and classify planning conditions from decision notices into:
- Pre-commencement conditions
- Construction-phase conditions
- Operational conditions
- Decommissioning conditions
- Time limits

---

## 7. TRAINING DATA STRATEGY — COMPLETE INVENTORY

| # | Data Source | URL | Format | Records | Update | Free? | Key Fields |
|---|-----------|-----|--------|---------|--------|-------|------------|
| 1 | REPD | gov.uk/...renewable-energy-planning-database | CSV/XLSX | ~6,000+ | Quarterly | Yes | 43 fields incl. technology, capacity, status, dates, coordinates |
| 2 | PINS Appeals DB | gov.uk/...planning-inspectorate-appeals-database | XLSX | ~91,000 | Quarterly | Yes | ~50 variables, appeal decisions |
| 3 | Planning Data Platform | planning.data.gov.uk | JSON/GeoJSON/CSV | 200+ datasets | Ongoing | Yes | Entity-based, all constraint types |
| 4 | Planning London Datahub | planningdata.london.gov.uk | JSON (ES) | All London apps | Daily | Yes | Full planning application details |
| 5 | MHCLG Decisions Stats | opendatacommunities.org | CSV/SPARQL | National aggregate | Quarterly | Yes | District-level decisions by outcome |
| 6 | LG Inform Schema | schemas.opendata.esd.org.uk | CSV | Per LPA | Varies | Yes | 36 fields incl. ResponsesFor/Against |
| 7 | Digital Land Spec | digital-land.github.io | JSON/CSV | Growing | Active dev | Yes | 22 core fields, 29 codelists |
| 8 | NSIP Register | national-infrastructure-consenting... | Web only | ~600+ projects | Ongoing | Yes | Project status, documents |
| 9 | SSSIs | data.gov.uk | Shapefile | ~4,100+ sites | Annual | Yes | Boundary, condition |
| 10 | SACs | data.gov.uk | Shapefile | ~250+ sites | Annual | Yes | Boundary, qualifying features |
| 11 | SPAs | naturalengland-defra.opendata... | Shapefile | ~80+ sites | Annual | Yes | Boundary, bird species |
| 12 | Listed Buildings | historicengland.org.uk | Shapefile/CSV/API | ~400,000 | Ongoing | Yes | Grade, location, description |
| 13 | Conservation Areas | historicengland.org.uk | Shapefile | ~10,000+ | Annual | Yes | Boundary |
| 14 | Flood Zones | environment.data.gov.uk | GeoJSON/Shapefile | National | Annual | Yes | Zone 2, 3a, 3b |
| 15 | Flood Monitoring API | environment.data.gov.uk | JSON API | Real-time | Real-time | Yes | Warnings, levels, stations |
| 16 | ALC (Agricultural Land) | naturalengland-defra.opendata... | Shapefile | National | Static | Yes | Grade 1-5 |
| 17 | Green Belt | planning.data.gov.uk | GeoJSON | National | Annual | Yes | Boundary |
| 18 | AONBs/National Landscapes | naturalengland-defra.opendata... | Shapefile | 34 areas | Annual | Yes | Boundary, name |
| 19 | Ancient Woodland | naturalengland-defra.opendata... | Shapefile | ~52,000 sites | Annual | Yes | Boundary, type |
| 20 | SSSI Impact Risk Zones | data.gov.uk | Shapefile | National | Annual | Yes | Risk zone boundaries |
| 21 | ONS Geography | geoportal.statistics.gov.uk | Shapefile/GeoJSON | National | Annual | Yes | LA boundaries, ward, LSOA |
| 22 | IMD (Deprivation) | opendatacommunities.org | CSV | 32,844 LSOAs | Periodic | Yes | Deprivation scores |
| 23 | JNCC Protected Areas | jncc.gov.uk | Shapefile | UK-wide | Annual | Yes | SAC, SPA, Ramsar |
| 24 | MAGIC datasets | magic.defra.gov.uk | WMS/WFS/Shapefile | 400+ layers | Varies | Yes | Environmental constraints |
| 25 | Searchland API | docs.searchland.co.uk | JSON API | 23.9M apps | 24-hourly | Paid | Full planning history |
| 26 | LandHawk API | docs.landhawk.uk | JSON/WMS | 99% coverage | Hourly | Paid | Planning + DNO data |
| 27 | Glenigan API | gleniganapi.com | JSON | 500K/year | Real-time | Paid | Planning + construction leads |
| 28 | Barbour ABI APIs | barbour-abi.com | JSON | Extensive | Daily | Paid | Projects + locations |

---

## 8. IMPLEMENTATION PRIORITIES FOR PRINCEPS

### Phase 1 — Data Foundation (Weeks 1-4)
1. Ingest REPD quarterly CSV into PostGIS (automate quarterly refresh)
2. Ingest PINS appeals XLSX into PostGIS
3. Ingest all Natural England constraint layers (SSSI, SAC, SPA, ALC, AONB, ancient woodland)
4. Ingest Historic England datasets (listed buildings, conservation areas, scheduled monuments)
5. Ingest EA flood zones
6. Ingest Green Belt boundaries
7. Compute spatial overlay features for every REPD project

### Phase 2 — Feature Engineering (Weeks 4-8)
8. Join REPD with appeals data (appeal reference matching)
9. Join with ONS geography (LPA → IMD, rural/urban, political control)
10. Compute distance-to-constraint features for all projects
11. Label engineering: granted/refused/withdrawn/appeal_granted/appeal_refused
12. Time-based train/test split

### Phase 3 — Model Training (Weeks 8-12)
13. Train XGBoost classifier on tabular features
14. SHAP analysis for feature importance
15. Validate on held-out recent period
16. Build API endpoint: POST /api/planning/predict → {probability, risks, precedents}

### Phase 4 — NLP Enhancement (Weeks 12-20)
17. Scrape decision notices from LPA portals (start with top 50 LPAs for renewable energy)
18. Fine-tune BERT for condition extraction
19. Build objection sentiment classifier
20. Add NLP features to ensemble model

### Phase 5 — Planning Intelligence Dashboard (Weeks 20-24)
21. Build PlanningIntelligencePanel.jsx (right slide-in, like GridConnectionPanel)
22. Show: GO/CAUTION/NO-GO verdict, probability scores, risk breakdown, comparable precedents
23. Map layer: constraint heat map, approved/refused projects nearby
24. Regulatory compliance checklist (automated where possible)
25. Timeline estimator based on LPA performance statistics

---

## 9. UNIQUE COMPETITIVE ADVANTAGE

No existing UK planning intelligence platform offers **ML-based planning outcome prediction**. The closest is:
- Searchland: has the data but no prediction
- LandInsight: has constraint checking but no ML
- Glenigan: focused on construction leads, not planning outcome analysis
- Barbour ABI: manages REPD but doesn't model outcomes
- Pager Power: specialist assessments, not platform-wide prediction

Princeps would be **the first platform to combine**:
1. REPD + PINS + constraint data → trained ML model
2. SHAP-explained risk factors per site
3. NLP extraction of planning conditions and objection sentiment
4. Integrated with existing GeeFlow, SAM, grid connection, and demand forecast capabilities
5. Full regulatory compliance automation checklist

This makes the planning/regulatory intelligence module a genuine market differentiator.
