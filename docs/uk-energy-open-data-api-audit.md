# UK Energy Open Data API Audit

**Date**: 2026-03-23
**Platform**: Princeps (Feasibly)
**Purpose**: Comprehensive catalogue of all available UK energy open data APIs and datasets for energy infrastructure feasibility

---

## CATEGORY 1: Elexon / BMRS Insights API

**Base URL**: `https://data.elexon.co.uk/bmrs/api/v1`
**Auth**: None required -- all endpoints are public, no API key needed
**Formats**: JSON, CSV, XML
**Real-time**: IRIS (Insights Real-time Information Service) WebSocket available
**Legacy BMRS**: Switched off 31 May 2024; all data now on Insights Solution

### 1.1 Demand Datasets

| Dataset Code | Name | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| INDO | Initial National Demand Outturn | Near-real-time national demand (transmission) | Every SP (30min) | INGESTED (live_grid_status, energy_demand_predictor, grid_constraints) | -- |
| ITSDO | Initial Transmission System Demand Outturn | Transmission system demand | Every SP | INGESTED (energy_demand_predictor) | -- |
| INDOD | Day-ahead Initial National Demand Outturn | Day-ahead demand forecast outturn | Daily | NOT INGESTED | MEDIUM |
| FUELHH | Generation by Fuel Type (Half-Hourly) | HH generation broken down by fuel | Every SP | NOT INGESTED (use FUELINST instead) | LOW |
| FUELINST | Instantaneous Generation by Fuel Type | Real-time generation mix | ~2 min | INGESTED (live_grid_status, national_grid_live) | -- |
| FUELINSTHHCUR | Inst. Generation by Fuel Type (Half-Hour Current) | Current HH generation by fuel | Every SP | INGESTED (pypsa_dispatch_runner) | -- |

### 1.2 Balancing & Pricing Datasets

| Dataset Code | Name | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| DETSYSPRICES | Detailed System Prices | System buy/sell prices per settlement period | Every SP | INGESTED (live_grid_status, bmrs_wholesale) | -- |
| MID | Market Index Data | N2EX/EPEX reference price per SP | Every SP | INGESTED (national_grid_live, bmrs_wholesale) | -- |
| BOALF | Bid-Offer Acceptance Level Flagged | Balancing Mechanism acceptances (BOAs) | Real-time | NOT INGESTED | HIGH |
| BOD | Bid-Offer Data | Bid and offer prices/volumes per BM unit | Per SP | NOT INGESTED | HIGH |
| FPN | Final Physical Notification | Contracted generation/demand schedules | Per SP | NOT INGESTED | HIGH |
| QPN | Quiescent Physical Notification | Baseline physical notifications | Per SP | NOT INGESTED | MEDIUM |
| MEL/MELS | Maximum Export Limit | Max export limit per BM unit | Per SP | NOT INGESTED | MEDIUM |
| MIL/MILS | Maximum Import Limit | Max import limit per BM unit | Per SP | NOT INGESTED | MEDIUM |
| SIL | Stable Import Limit | Stable import limit | Per SP | NOT INGESTED | LOW |
| SEL | Stable Export Limit | Stable export limit | Per SP | NOT INGESTED | LOW |
| DISBSAD | Disaggregated BSAd | Disaggregated balancing services adjustment data | Per SP | NOT INGESTED | MEDIUM |
| NETBSAD | Net BSAd | Net balancing services adjustment | Per SP | NOT INGESTED | MEDIUM |
| BEB | Balancing Energy Bids | Bids into balancing mechanism | Real-time | NOT INGESTED | MEDIUM |
| RDRE | Repriced Demand-side Response Enactments | Demand-side balancing actions | Real-time | NOT INGESTED | LOW |

### 1.3 System Datasets

| Dataset Code | Name | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| FREQ | System Frequency | GB system frequency (50 Hz nominal) | ~1 sec via IRIS, 15s via API | INGESTED (grid_constraints, live_grid_status) | -- |
| LOLP | Loss of Load Probability | System risk of demand exceeding supply | Every SP | NOT INGESTED | HIGH |
| AGWS | Actual Wind & Solar Generation | Actual/estimated wind+solar output | Per SP | INGESTED (bmrs_datasets) | -- |
| AGPT | Actual Generation Per Type | Actual generation per power station type | Per SP | NOT INGESTED | HIGH |
| CCM | Cost of Congestion Management | Constraint costs | Daily | NOT INGESTED | HIGH |

### 1.4 Forecast Datasets

| Dataset Code / Endpoint | Name | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| /forecast/demand/day-ahead | Day-Ahead Demand Forecast | NESO day-ahead national demand forecast | Daily | NOT INGESTED | HIGH |
| /forecast/generation/wind-and-solar/day-ahead | Wind & Solar Day-Ahead Forecast | NESO wind/solar generation forecast | Daily | NOT INGESTED | HIGH |
| /forecast/demand/weekly | 2-14 Day Demand Forecast | Medium-term demand forecast | Weekly | NOT INGESTED | MEDIUM |
| /forecast/surplus | Surplus Forecast | Generation surplus/deficit forecast | Daily | NOT INGESTED | MEDIUM |
| /forecast/margin | Margin Forecast | Operating margin forecast | Daily | NOT INGESTED | MEDIUM |

### 1.5 Settlement & Reference

| Dataset / Endpoint | Name | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| /balancing/settlement/system-prices/{date} | Settlement System Prices | Final settlement prices (DISEBSP) | Per run | INGESTED (bmrs_wholesale) | -- |
| /balancing/pricing/market-index | Market Index Price | Day-ahead reference price | Per SP | INGESTED (national_grid_live) | -- |
| /reference/bmunits/all | BM Unit Reference | All registered BM units | Weekly | NOT INGESTED | MEDIUM |
| /reference/fueltypes | Fuel Type Reference | Fuel type code mappings | Static | NOT INGESTED | LOW |
| /demand/outturn/summary | Demand Outturn Summary | Historical national demand | 7-day pagination | INGESTED (demand_data_ingester) | -- |
| REMIT | REMIT Messages | Urgent market messages / planned outages | Real-time | NOT INGESTED | HIGH |

### Elexon Summary
- **Currently ingested**: INDO, ITSDO, FUELINST, FUELINSTHHCUR, FREQ, AGWS, DETSYSPRICES, MID, demand/outturn, system-prices, market-index
- **High-priority gaps**: BOALF (balancing acceptances), BOD (bid-offer data), FPN (physical notifications), LOLP (loss-of-load), AGPT (generation per type), CCM (congestion costs), REMIT, day-ahead forecasts
- **Total available dataset codes**: 70+ via `/datasets/{code}` plus 30+ opinionated endpoints

---

## CATEGORY 2: NESO (National Energy System Operator) Data Portal

**Base URL**: `https://api.neso.energy/api/3/action/datastore_search`
**Platform**: CKAN
**Auth**: None required -- free access
**Rate limit**: 1 req/sec (CKAN), 2 req/min (Datastore API recommended)
**Formats**: JSON, CSV via CKAN API
**Total datasets found**: ~165 packages

### 2.1 Demand Forecasts

| Dataset | Resource ID / Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| 1-Day-Ahead Demand Forecast | 1-day-ahead-demand-forecast | Day-ahead national demand | Daily | NOT INGESTED | HIGH |
| 2-Day-Ahead Demand Forecast | 2-day-ahead-demand-forecast | 2-day ahead demand | Daily | NOT INGESTED | MEDIUM |
| 2-14 Days Ahead National Demand Forecast | 2-14-days-ahead-national-demand-forecast | Medium-term demand | Daily | NOT INGESTED | MEDIUM |
| 7-Day-Ahead National Forecast | 7-day-ahead-national-forecast | Weekly demand forecast | Weekly | NOT INGESTED | MEDIUM |
| Long-Term (2-52 weeks) National Demand Forecast | long-term-2-52-weeks-ahead-national-demand-forecast | Seasonal demand | Weekly | NOT INGESTED | MEDIUM |
| Historic Demand Data | historic-demand-data | Historical demand archives | Monthly | NOT INGESTED | HIGH |
| Daily Demand Update | daily-demand-update | Daily demand summary | Daily | NOT INGESTED | MEDIUM |
| Demand Profile Dates | demand-profile-dates | Profile class demand shapes | Periodic | NOT INGESTED | LOW |

### 2.2 Wind & Solar Forecasts

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| Day-Ahead Wind Forecast | day-ahead-wind-forecast | Wind generation forecast | Daily | NOT INGESTED | HIGH |
| 14-Days-Ahead Wind Forecasts | 14-days-ahead-wind-forecasts | Extended wind forecast | Daily | NOT INGESTED | MEDIUM |
| 14-Days-Ahead Operational Metered Wind | 14-days-ahead-operational-metered-wind-forecasts | Metered wind output forecast | Daily | NOT INGESTED | MEDIUM |
| Embedded Wind and Solar Forecasts | embedded-wind-and-solar-forecasts | Embedded (distribution-connected) renewables | Daily | NOT INGESTED | HIGH |
| Daily Wind Availability | daily-wind-availability | Wind fleet availability | Daily | NOT INGESTED | MEDIUM |
| Weekly Wind Availability | weekly-wind-availability | Weekly wind fleet | Weekly | NOT INGESTED | LOW |
| Monthly Operational Metered Wind | monthly-operational-metered-wind-output | Monthly metered wind | Monthly | NOT INGESTED | LOW |

### 2.3 Registers & Connection Data

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| TEC Register | transmission-entry-capacity-tec-register | Transmission Entry Capacity -- all projects holding TEC contracts | Twice weekly (Tue/Fri) | INGESTED (eso_tec.py, eso_tec_register.py) | -- |
| Embedded Register | embedded-register | Embedded generation in Scotland | Monthly | NOT INGESTED | HIGH |
| Interconnector Register | interconnector-register | Cross-border interconnector data | Monthly | NOT INGESTED | MEDIUM |
| Capacity Market Register | capacity-market-register | CM agreements and auctions | Monthly | NOT INGESTED | HIGH |
| NGED Connections Reform Register | (via NGED portal) | Post-reform connection queue | Jan 2026 onwards | NOT INGESTED | HIGH |

### 2.4 Future Energy Scenarios (FES)

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| FES Electricity Supply (ES1) | future-energy-scenario-electricity-supply-data-table-es1 | Generation capacity projections | Annual | NOT INGESTED | HIGH |
| FES Electricity Demand (ED1) | fes-electricity-demand-summary-data-table-ed1 | Demand pathway projections | Annual | NOT INGESTED | HIGH |
| FES Building Block Data | future-energy-scenario-fes-building-block-data | Granular FES components | Annual | NOT INGESTED | MEDIUM |
| FES European Supply (ES2) | fes-european-electricity-supply-data-table-es2 | European interconnection scenarios | Annual | NOT INGESTED | LOW |
| FES Flexibility (FLX1) | fes-flexibility-data-table-data-table-flx1 | Flexibility capacity projections | Annual | NOT INGESTED | MEDIUM |
| FES Gas Demand (ED3/ED4) | fes-natural-gas-* | Gas demand pathways | Annual | NOT INGESTED | LOW |
| FES Road Transport (ED5/ED6) | fes-road-transport-* | EV uptake scenarios | Annual | NOT INGESTED | MEDIUM |
| FES Gas Supply (WS1/WS2) | fes-whole-system-gas-supply-* | Whole-system gas scenarios | Annual | NOT INGESTED | LOW |
| Regional FES Data (Electricity) | regional-breakdown-of-fes-data-electricity | Regional FES breakdowns | Annual | NOT INGESTED | HIGH |
| Local Authority Heat Model | local-authority-level-spatial-heat-model-outputs-fes | Heat decarbonisation by LA | Annual | NOT INGESTED | MEDIUM |
| TRESP Demand Pathways | tresp-demand-pathways | Transitional regime demand | Annual | NOT INGESTED | MEDIUM |
| TRESP Generation Pathways | tresp-generation-pathways | Transitional regime generation | Annual | NOT INGESTED | MEDIUM |
| Levelised Cost Green Hydrogen | levelised-cost-of-green-hydrogen | H2 production costs | Annual | NOT INGESTED | LOW |

### 2.5 Balancing Services & System

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| Current BSUoS Data | current-balancing-services-use-of-system-bsuos-data | Half-hourly BSUoS prices | Daily | NOT INGESTED | HIGH |
| BSUoS Daily Forecast | balancing-services-use-of-system-bsuos-daily-forecast | BSUoS price forecast | Daily | NOT INGESTED | HIGH |
| BSUoS Fixed Tariffs | bsuos-fixed-tariffs | Seasonal BSUoS tariffs | Quarterly | NOT INGESTED | MEDIUM |
| BSUoS Monthly Forecast | bsuos-monthly-forecast | Monthly BSUoS forecast | Monthly | NOT INGESTED | MEDIUM |
| Daily Balancing Costs | daily-balancing-costs-balancing-services-use-of-system | Daily balancing cost breakdown | Daily | NOT INGESTED | HIGH |
| Aggregated BSAd | aggregated-bsad | Aggregated balancing adjustment | Per SP | NOT INGESTED | MEDIUM |
| System Frequency Data | system-frequency-data | Historical frequency datasets | Monthly | NOT INGESTED | LOW |
| System Inertia | system-inertia | GB system inertia levels | Per SP | NOT INGESTED | HIGH |
| System Inertia Cost | system-inertia-cost | Cost of inertia services | Monthly | NOT INGESTED | MEDIUM |
| Transmission Losses | transmission-losses | Transmission loss factors | Monthly | NOT INGESTED | MEDIUM |
| Historic Generation Mix | historic-generation-mix | Historical generation by fuel | Monthly | NOT INGESTED | MEDIUM |
| Carbon Intensity of Balancing | carbon-intensity-of-balancing-actions | CO2 from balancing actions | Daily | NOT INGESTED | MEDIUM |
| Skip Rates | skip-rates | BM unit skip rates | Monthly | NOT INGESTED | LOW |

### 2.6 Constraint Data

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| Thermal Constraint Costs | thermal-constraint-costs | Boundary constraint costs | Monthly | NOT INGESTED | HIGH |
| 24-Month Constraint Cost Forecast | 24-months-ahead-constraint-cost-forecast | Forward constraint costs | Monthly | NOT INGESTED | HIGH |
| 24-Month Constraint Limits | 24-months-ahead-constraint-limits | Forward boundary limits | Monthly | NOT INGESTED | HIGH |
| Day-Ahead Constraint Flows/Limits | day-ahead-constraint-flows-and-limits | Next-day constraint data | Daily | NOT INGESTED | HIGH |
| Constraint Breakdown | constraint-breakdown | Detailed constraint analysis | Monthly | NOT INGESTED | MEDIUM |
| Year-Ahead Constraint Limits | year-ahead-constraint-limits | Annual limit forecasts | Quarterly | NOT INGESTED | MEDIUM |
| CMIS | constraint-management-intertrip-service-information-cmis | Intertrip service info | Monthly | NOT INGESTED | LOW |

### 2.7 Network & Transmission

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| ETYS Boundaries | etys-gb-transmission-system-boundaries | Transmission system boundary GIS | Annual | NOT INGESTED | HIGH |
| GIS DNO Licence Areas | gis-boundaries-for-gb-dno-license-areas | DNO boundary polygons | Periodic | NOT INGESTED | HIGH |
| GIS GSP Boundaries | gis-boundaries-for-gb-grid-supply-points | Grid Supply Point zones | Periodic | NOT INGESTED | HIGH |
| GIS Generation Charging Zones | gis-boundaries-for-gb-generation-charging-zones | TNUoS charging zones | Periodic | NOT INGESTED | MEDIUM |
| TNUoS Tariffs | transmission-network-use-of-system-tnuos-tariffs | Transmission charges by zone | Annual | NOT INGESTED | HIGH |
| AAHEDC Tariffs | aahedc-tariffs | Assistance for Areas with High Electricity Distribution Costs | Annual | NOT INGESTED | LOW |

### 2.8 Ancillary Services & Reserve

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| Dynamic Containment Data | dynamic-containment-data | DC market results | Daily | NOT INGESTED | HIGH |
| DC 4-Day Forecast | dynamic-containment-4-day-forecast | DC requirements forecast | Daily | NOT INGESTED | HIGH |
| Dynamic Moderation Requirements | dynamic-moderation-requirements | DM market requirements | Daily | NOT INGESTED | MEDIUM |
| Dynamic Regulation Requirements | dynamic-regulation-requirements | DR market requirements | Daily | NOT INGESTED | MEDIUM |
| Long-term DC/DM/DR Forecasts | long-term-forecasts-for-dc-dm-dr-requirements | Extended frequency response forecasts | Weekly | NOT INGESTED | MEDIUM |
| Balancing Reserve Auction | balancing-reserve-auction-requirement-forecast | Reserve requirement | Daily | NOT INGESTED | MEDIUM |
| Quick Reserve Auction | quick-reserve-auction-requirement-forecast | Quick reserve needs | Daily | NOT INGESTED | MEDIUM |
| Slow Reserve Requirement | slow-reserve-requirement-forecast | Slow reserve needs | Daily | NOT INGESTED | LOW |
| STOR Day-Ahead Results | short-term-operating-reserve-stor-day-ahead-auction-results | STOR auction results | Daily | NOT INGESTED | MEDIUM |
| FFR Auction Results | firm-frequency-response-post-tender-reports | FFR procurement results | Monthly | NOT INGESTED | MEDIUM |
| Static FFR Auction | static-firm-frequency-response-auction-results | Static FFR results | Monthly | NOT INGESTED | MEDIUM |
| NRAPM Forecast | negative-reserve-active-power-margin-nrapm-forecast | Negative reserve margin | Daily | NOT INGESTED | MEDIUM |

### 2.9 Interconnectors

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| IFA (France) | ifa | IFA interconnector flows | Real-time | NOT INGESTED | MEDIUM |
| IFA2 (France) | ifa2 | IFA2 flows | Real-time | NOT INGESTED | MEDIUM |
| BritNed (Netherlands) | brit-ned | BritNed flows | Real-time | NOT INGESTED | MEDIUM |
| NemoLink (Belgium) | nemolink | Nemo Link flows | Real-time | NOT INGESTED | MEDIUM |
| NSL (Norway) | nsl | North Sea Link flows | Real-time | NOT INGESTED | MEDIUM |
| ElecLink (France) | eleclink | ElecLink flows | Real-time | NOT INGESTED | MEDIUM |
| Viking (Denmark) | viking | Viking Link flows | Real-time | NOT INGESTED | MEDIUM |

### 2.10 Demand Flexibility & Other

| Dataset | Slug | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| Demand Flexibility Service | demand-flexibility-service | DFS event data | Per event | NOT INGESTED | MEDIUM |
| DFS Live Events | demand-flexibility-service-live-events | Active DFS events | Real-time | NOT INGESTED | MEDIUM |
| System Operating Plan | system-operating-plan-sop | Forward operating plans | Weekly | NOT INGESTED | MEDIUM |
| Daily OPMR | daily-opmr | Daily Operational Planning Margin Report | Daily | NOT INGESTED | MEDIUM |
| Weekly OPMR | weekly-opmr | Weekly OPMR | Weekly | NOT INGESTED | LOW |
| Resource Adequacy 2030s | resource-adequacy-in-2030s | Long-term adequacy study | Annual | NOT INGESTED | MEDIUM |
| ORPS Utilisation | obligatory-reactive-power-service-orps-utilisation | Reactive power services | Monthly | NOT INGESTED | LOW |
| Stability Pathfinder | stability-pathfinder-service-information | Stability service contracts | Quarterly | NOT INGESTED | LOW |
| Wind BMU BOA Volumes | wind-bmu-boa-volumes | Wind curtailment volumes | Daily | NOT INGESTED | HIGH |

### NESO Summary
- **Currently ingested**: TEC Register only (resource 17becbab)
- **High-priority gaps**: Embedded Register, Capacity Market Register, FES ES1/ED1, Regional FES, BSUoS data, thermal constraint data, ETYS boundaries, GIS boundaries, Dynamic Containment, wind curtailment
- **Total datasets on portal**: ~165

---

## CATEGORY 3: DNO Open Data Portals

### 3.1 UKPN (UK Power Networks)

**Portal**: `https://ukpowernetworks.opendatasoft.com`
**API**: OpenDataSoft Explore v2.1 (`/api/explore/v2.1/catalog/datasets`)
**Auth**: Free registration recommended; browsing without registration possible
**Formats**: JSON, CSV, GeoJSON, Shapefile

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| Grid & Primary Sites | grid-and-primary-sites | Substation locations, capacity, commissioning year | INGESTED (grid_data_ingester: ukpn-grid-supply-points) | -- |
| GSP Capacity | ukpn-grid-supply-point-capacity | Headroom/capacity at GSPs | INGESTED (grid_data_ingester: ukpn-grid-supply-point-capacity) | -- |
| Power Quality | ukpn-power-quality | Power quality monitoring (450+ sites) | NOT INGESTED | LOW |
| Network Statistics | ukpn-network-statistics | Annual regulatory stats (Ofgem) | NOT INGESTED | LOW |
| Data Centre Utilisation | ukpn-data-centre-utilisation | DC demand & utilisation | NOT INGESTED | HIGH |
| Embedded Capacity Register | (ECR dataset) | Embedded generation register | NOT INGESTED | HIGH |
| LTDS Tables | (various) | Long-Term Development Statement | NOT INGESTED | MEDIUM |
| Fault Level Data | (dataset varies) | Network fault levels | NOT INGESTED | MEDIUM |

### 3.2 NGED (National Grid Electricity Distribution)

**Portal**: `https://connecteddata.nationalgrid.co.uk`
**API**: CKAN (`/api/3/action/...`)
**Auth**: Free registration; API open
**Formats**: JSON, CSV, GeoJSON

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| Network Capacity Map | network-capacity-map | Substation headroom & capacity | INGESTED (grid_data_ingester: network-capacity-map) | -- |
| Embedded Capacity Register | embedded-capacity-register | ECR for 4 regions | INGESTED (grid_data_ingester: embedded-capacity-register) | -- |
| Distribution Substations | distribution-substations | Full substation register | NOT INGESTED | MEDIUM |
| Connection Queue | connection-queue | Post-reform connection queue (from Jan 2026) | NOT INGESTED | HIGH |
| Connections Reform Register | nged-connections-reform-register | Reform outcomes | NOT INGESTED | HIGH |
| Live Network Data | (live-data-feed) | Real-time demand by area | NOT INGESTED | HIGH |
| LTDS Tables | (various) | Network planning data | NOT INGESTED | MEDIUM |
| Flexibility Data | (flexibility datasets) | Flexibility zones and tenders | NOT INGESTED | MEDIUM |
| LV Monitoring | (lv-substation-monitoring) | Low-voltage substation monitoring | NOT INGESTED | MEDIUM |

### 3.3 NPg (Northern Powergrid)

**Portal**: `https://northernpowergrid.opendatasoft.com`
**API**: OpenDataSoft Explore v2.1
**Auth**: Free registration for full API access
**Formats**: JSON, CSV, GeoJSON

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| Thermal Demand Headroom | thermal-demand-headroom | Substation demand headroom | INGESTED (grid_data_ingester) | -- |
| Thermal Generation Headroom | thermal-generation-headroom | Generation connection headroom | INGESTED (grid_data_ingester) | -- |
| NPg Site Utilisation | npg-site-utilisation | Substation utilisation, customers, max demand | NOT INGESTED | HIGH |
| Embedded Capacity Register (>1MW) | embedded-capacity-register | ECR for NE/Yorkshire | NOT INGESTED | HIGH |
| National ECR | ecr_manual_combine_test | Combined national ECR | NOT INGESTED | MEDIUM |
| Heat Map - Substation Areas | heatmapsubstationareas | EHV/HV heat map with fault level, headroom | NOT INGESTED | HIGH |
| Appendix G Information | gsp-appendix-g-information | NESO Appendix G data per GSP | NOT INGESTED | MEDIUM |
| All DNO Licence Boundaries | all_dno_boundaries | All UK DNO boundary shapefiles | NOT INGESTED | HIGH |
| Flexibility Zones | (flexibility datasets) | Flexibility requirements | NOT INGESTED | MEDIUM |

### 3.4 SSEN (Scottish & Southern Electricity Networks)

**Portal (Distribution)**: `https://data.ssen.co.uk` (CKAN-based)
**Portal (Transmission)**: `https://ssentransmission.opendatasoft.com` (OpenDataSoft)
**Auth**: Free
**Formats**: JSON, CSV, GeoJSON

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| Generation Availability & Network Capacity | generation-availability-and-network-capacity | Headroom dashboard data | INGESTED (grid_data_ingester) | -- |
| Substation Data | ssen-substation-data | Location, type, identification | NOT INGESTED | HIGH |
| Smart Meter LV Feeder Data | (smart meter datasets) | HH consumption by LV feeder (1.8M meters, 84K feeders) | NOT INGESTED | HIGH |
| NeRDA Portal Data | nerda_opengrid_dashboard | Near-real-time EHV/HV SCADA + LV monitoring | NOT INGESTED | HIGH |
| DFES (Distribution FES) | (DFES datasets) | SHEPD + SEPD LCT uptake projections to 2050 | NOT INGESTED | HIGH |
| Network Development Reports | (NDR datasets) | 10-year network plans (11kV+) | NOT INGESTED | MEDIUM |
| Real-time Outage Data | realtime_outage_dataset | Live network outages | NOT INGESTED | MEDIUM |
| Flexibility Market Data | (flexibility datasets) | Flex requirements, procurement | NOT INGESTED | MEDIUM |

### 3.5 SPEN (SP Energy Networks)

**Portal**: `https://spenergynetworks.opendatasoft.com`
**API**: OpenDataSoft Explore v2.1
**Auth**: Free
**Formats**: JSON, CSV, GeoJSON

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| Embedded Capacity Register | embedded-capacity-register | ECR for SPD + SPM (monthly) | INGESTED (grid_data_ingester) | -- |
| Embedded Generation by Type | network-dataset-embedded-generation-by-type | Generation breakdown | NOT INGESTED | MEDIUM |
| LTDS Data | (various) | Long-term development data | NOT INGESTED | MEDIUM |
| Network Capacity Heat Map | (heat map datasets) | Thermal/fault level heat maps | NOT INGESTED | HIGH |
| Mapping Data | (GIS datasets) | Substation & line GIS data | NOT INGESTED | MEDIUM |

### 3.6 ENWL (Electricity North West)

**Portal**: `https://electricitynorthwest.opendatasoft.com`
**API**: OpenDataSoft Explore v2.1
**Auth**: Free
**Total datasets**: ~90

| Dataset | ID | Description | Princeps Status | Priority |
|---|---|---|---|---|
| HV Network Capacity | hv-network-capacity | HV network headroom | INGESTED (grid_data_ingester) | -- |
| Embedded Capacity Register | embedded-capacity-register | ECR for NW England | INGESTED (grid_data_ingester) | -- |
| ECR Supplementary Data | ecr-supplementary-data | Extended ECR with 50kW+ | NOT INGESTED | MEDIUM |
| ENWL ECR 2 (1MW+) | enwl-embedded-capacity-register-2-1mw-and-above | Large-scale ECR | NOT INGESTED | MEDIUM |
| DFES Data | (DFES datasets) | Distribution FES for NW | NOT INGESTED | MEDIUM |
| GPS Boundary Flow | (boundary datasets) | GSP boundary metering | NOT INGESTED | MEDIUM |
| Outage Data | (outage datasets) | Network outage info | NOT INGESTED | LOW |
| Flexibility Data | (flexibility datasets) | Flex procurement info | NOT INGESTED | MEDIUM |

### DNO Summary
- **All 6 DNOs integrated** for basic substation capacity/ECR data
- **High-priority gaps**: Site utilisation (NPg), heat maps (NPg, SPEN), smart meter data (SSEN), NeRDA real-time (SSEN), connection queue (NGED), DFES projections (SSEN), data centre utilisation (UKPN), DNO boundary shapefiles (NPg)
- **API pattern**: 5 DNOs on OpenDataSoft (v2.1 REST), NGED on CKAN, SSEN Distribution on CKAN

---

## CATEGORY 4: Ofgem Data

**Portal**: `https://www.ofgem.gov.uk/data-portal`
**Register**: `https://rer.ofgem.gov.uk` (Renewable Electricity Register)
**Auth**: Public reports freely downloadable; no REST API
**Formats**: CSV, Excel (manual download)

| Dataset | Source | Description | Update Freq | Princeps Status | Priority |
|---|---|---|---|---|---|
| REGO Register | rer.ofgem.gov.uk | Accredited REGO stations, certificates issued/transferred | Tue/Fri | NOT INGESTED | HIGH |
| Feed-in Tariff Register | ofgem.gov.uk/public-reports-and-data-fit | FIT installations, capacity, technology | Quarterly | NOT INGESTED | HIGH |
| Renewables Obligation Register | ofgem.gov.uk RO data | RO-accredited stations, ROCs issued | Monthly | NOT INGESTED | MEDIUM |
| Capacity Market Register | NESO portal (see 2.3) | CM capacity agreements | Monthly | NOT INGESTED | HIGH |
| Ofgem Data Portal Charts | ofgem.gov.uk/data-portal | Interactive gas/electricity sector data | Quarterly | NOT INGESTED | LOW |

### Ofgem Notes
- No formal REST API; data available as downloadable reports from the Renewable Electricity Register (RER)
- RER replaced old Renewables & CHP Register; services RO, REGO, and ROOFIT schemes
- FIT deployment data available as quarterly CSV extracts
- Consider scraping/downloading approach rather than API integration

---

## CATEGORY 5: Government & Public APIs

### 5.1 Environment Agency

**Base URL**: `https://environment.data.gov.uk/flood-monitoring`
**Auth**: None -- Open Government Licence
**Formats**: JSON, CSV
**Update**: Every 15 minutes (real-time)

| Endpoint | Description | Princeps Status | Priority |
|---|---|---|---|
| /id/floods | Current flood warnings/alerts | INGESTED (esa_auto_scoping, environmental_constraints) | -- |
| /data/readings?latest | Latest water level readings | NOT INGESTED | LOW |
| /id/stations | Monitoring station register | NOT INGESTED | LOW |
| /id/floodAreas | Flood warning areas | NOT INGESTED | MEDIUM |
| Flood Map for Planning (Zones) | Flood Zone 1/2/3 GIS data (via Defra Data Services) | NOT INGESTED | HIGH |
| NaFRA2 | National Flood Risk Assessment (updated Mar 2025) | NOT INGESTED | HIGH |

**Flood Map for Planning download**: `https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47`
- GeoJSON/Shapefile download of Flood Zones 2 & 3
- Essential for planning feasibility constraint checking

### 5.2 Natural England / Defra

**Base URL**: `https://naturalengland-defra.opendata.arcgis.com`
**Auth**: None
**Formats**: GeoJSON, Shapefile, WMS/WFS

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| SSSI | Sites of Special Scientific Interest | INGESTED (environmental_constraints) | -- |
| SAC | Special Areas of Conservation | INGESTED | -- |
| SPA | Special Protection Areas | INGESTED | -- |
| AONB/NL | Areas of Outstanding Natural Beauty (now National Landscapes) | INGESTED | -- |
| ALC | Agricultural Land Classification | INGESTED (alc_lookup) | -- |
| National Nature Reserves | NNR boundaries | NOT INGESTED | MEDIUM |
| Priority Habitats | Priority habitat inventory | NOT INGESTED | MEDIUM |
| Ancient Woodland | Ancient woodland boundaries | NOT INGESTED | HIGH |
| Green Belt | Green Belt boundaries | NOT INGESTED | HIGH |
| Heritage Coasts | Heritage coast boundaries | NOT INGESTED | LOW |

### 5.3 Planning Data

**Base URL**: `https://www.planning.data.gov.uk`
**Auth**: None
**Formats**: JSON, CSV, GeoJSON

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| Planning Applications | National planning application register | NOT INGESTED | HIGH |
| Planning Application Status | Application outcomes | NOT INGESTED | HIGH |
| Planning Application Conditions | Attached conditions | NOT INGESTED | MEDIUM |
| Conservation Areas | Conservation area boundaries | NOT INGESTED | MEDIUM |
| Listed Buildings | Listed building locations | NOT INGESTED | MEDIUM |
| Article 4 Directions | Restricted PD areas | NOT INGESTED | LOW |

### 5.4 DESNZ / REPD

**URL**: `https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract`
**Auth**: None -- public download
**Formats**: CSV, Excel
**Update**: Quarterly (latest: Q4 January 2026)

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| REPD (Renewable Energy Planning Database) | All UK renewable projects >150kW through planning system | INGESTED (planning_predictor uses repd_projects table) | -- |
| Heat Networks Planning Database | Heat network projects | NOT INGESTED | LOW |

### 5.5 Carbon Intensity API

**Base URL**: `https://api.carbonintensity.org.uk`
**Auth**: None -- CC BY 4.0 licence
**Formats**: JSON
**Update**: Hourly; 96hr forecast

| Endpoint | Description | Princeps Status | Priority |
|---|---|---|---|
| /intensity | Current national carbon intensity | INGESTED (carbon_intensity_forecaster, live_grid_status, grid_constraints) | -- |
| /intensity/{from}/pt24h | 24hr carbon intensity series | INGESTED (national_grid_live) | -- |
| /intensity/date/{date} | Historical carbon intensity | INGESTED | -- |
| /generation | Current generation mix | INGESTED (live_grid_status) | -- |
| /regional | Regional carbon intensity (14 GB regions) | NOT INGESTED | HIGH |
| /regional/postcode/{postcode} | Postcode-level carbon intensity | NOT INGESTED | HIGH |
| /intensity/factors | Emission factors by fuel | NOT INGESTED | LOW |
| /intensity/stats | Statistical summaries | NOT INGESTED | LOW |

### 5.6 Sheffield Solar PV_Live

**Base URL**: `https://api.pvlive.uk` (production, hosted on GCP)
**Docs**: `https://www.solar.sheffield.ac.uk/api/`
**Auth**: None -- funded by NESO, free and open
**Formats**: JSON
**Update**: Every 30 minutes
**Python**: `pip install pvlive-api`

| Endpoint | Description | Princeps Status | Priority |
|---|---|---|---|
| PV_Live National | National estimated PV generation (half-hourly) | NOT INGESTED | HIGH |
| PV_Live Regional | Regional PV estimates by GSP/DNO area | NOT INGESTED | HIGH |
| PV_Forecast | Solar generation forecasts | NOT INGESTED | HIGH |

### 5.7 Met Office Weather DataHub

**Base URL**: `https://datahub.metoffice.gov.uk`
**Auth**: API key required (free tier available with generous limits)
**Formats**: GeoJSON (spot data), GRIB (atmospheric)
**Note**: DataPoint was decommissioned in March 2025; replaced by Weather DataHub

| Product | Description | Princeps Status | Priority |
|---|---|---|---|
| Global Spot Data (GeoJSON) | Site-specific forecasts for ~5000 UK sites | NOT INGESTED | MEDIUM |
| Atmospheric Model Data | UK hi-res model (1.5km), global model | NOT INGESTED | MEDIUM |
| Observations | Observed weather from ~140 UK stations | NOT INGESTED | MEDIUM |
| Radar/Satellite Imagery | Precipitation radar, satellite overlays | NOT INGESTED | LOW |

### 5.8 Ordnance Survey Data Hub

**Base URL**: `https://osdatahub.os.uk`
**Auth**: API key required (free tier available)
**Formats**: GeoJSON, Vector Tiles, WMS/WMTS

| Product | Description | Princeps Status | Priority |
|---|---|---|---|
| OS Terrain 50 | 50m DTM (free via OS OpenData) | NOT INGESTED (use NASADEM via GeeFlow instead) | LOW |
| OS Terrain 5 | 5m DTM (premium) | NOT INGESTED | LOW |
| OS Open Zoomstack | Free basemap tiles | NOT INGESTED | LOW |
| OS Places API | Address lookup / geocoding | NOT INGESTED | MEDIUM |
| OS Features API | Detailed building/land features | NOT INGESTED | LOW |

---

## CATEGORY 6: Market & Commercial Data

### 6.1 N2EX / Nord Pool Day-Ahead Prices

**URL**: `https://data.nordpoolgroup.com/auction/n2ex/prices`
**Auth**: Free to view; bulk API may require registration
**Formats**: JSON, CSV
**Update**: Daily (auction at 09:50 D-1)

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| N2EX Day-Ahead Hourly Prices | Auction clearing prices per hour | PARTIALLY (via BMRS MID as proxy) | HIGH |
| N2EX Price Indices | Daily price indices | NOT INGESTED | MEDIUM |

### 6.2 EPEX Spot

**URL**: `https://www.epexspot.com/en/market-results`
**Auth**: Registration required for API access
**Update**: Daily (DA auction at 09:20 D-1) + continuous intraday

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| Day-Ahead 60-Minute Prices | EPEX GB day-ahead auction | NOT INGESTED | MEDIUM |
| Intraday Continuous Prices | Real-time intraday trading | NOT INGESTED | MEDIUM |

### 6.3 EMR Settlement (Capacity Market)

**URL**: `https://www.emrsettlement.co.uk/settlement-data/`
**Auth**: Public download
**Formats**: CSV

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| Capacity Cleared Prices (Historical) | All T-1 and T-4 auction clearing prices | NOT INGESTED | HIGH |
| Monthly Weighting Factors | CM payment weightings | NOT INGESTED | MEDIUM |
| Supplier Capacity Charges | Capacity Market supplier charges | NOT INGESTED | LOW |

### 6.4 CfD (Contracts for Difference)

**URL**: `https://www.cfdallocationround.uk` + GOV.UK publications
**Auth**: Public
**Formats**: PDF, CSV, Excel

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| AR7 Results (Jan 2026) | Latest allocation round -- record offshore wind | NOT INGESTED | HIGH |
| AR7a Results (Feb 2026) | Supplementary AR7 results | NOT INGESTED | HIGH |
| Historical AR1-AR6 Results | All previous allocation results | NOT INGESTED | MEDIUM |
| Administrative Strike Prices | Max bid prices by technology | NOT INGESTED | HIGH |
| CfD Register | All active CfD contracts | NOT INGESTED | HIGH |

### 6.5 Modo Energy (Third-Party Analytics)

**URL**: `https://developers.modoenergy.com`
**Auth**: Subscription required
**Note**: Commercial API for wholesale prices, BESS revenues, market analytics

| Dataset | Description | Princeps Status | Priority |
|---|---|---|---|
| Wholesale Power Prices | GB day-ahead, intraday from EPEX+N2EX | NOT INGESTED | MEDIUM |
| BESS Revenue Benchmark | Battery revenue analytics (ME BESS GB) | NOT INGESTED | MEDIUM |
| Balancing Mechanism Analytics | BM price/volume analytics | NOT INGESTED | LOW |

### 6.6 Icebreaker One / Open Net Zero

**URL**: `https://opennetzero.org`
**Auth**: Free search; data from original sources
**Note**: Aggregator/catalogue, not a data source itself

Useful as a discovery tool to find additional datasets across all UK energy organisations.

---

## PRIORITY SUMMARY

### Tier 1 -- HIGH PRIORITY (Immediate Value for Energy Developers)

| # | Dataset | Source | Why It Matters |
|---|---|---|---|
| 1 | BOALF (Balancing Acceptances) | Elexon | Revenue stacking -- BM dispatch patterns |
| 2 | BOD (Bid-Offer Data) | Elexon | BM price discovery for BESS |
| 3 | FPN (Physical Notifications) | Elexon | Understanding contracted positions |
| 4 | LOLP (Loss of Load Probability) | Elexon | System stress periods = high prices |
| 5 | Day-Ahead Demand/Wind Forecasts | Elexon/NESO | Operational planning |
| 6 | Capacity Market Register | NESO | Active CM agreements, connection data |
| 7 | Embedded Register | NESO | Scottish embedded generation |
| 8 | FES ES1/ED1 + Regional FES | NESO | Investment case modelling to 2050 |
| 9 | Thermal Constraint Costs/Limits | NESO | Network bottleneck identification |
| 10 | BSUoS Data & Forecast | NESO | Balancing cost exposure |
| 11 | Dynamic Containment Data | NESO | Frequency response revenue streams |
| 12 | ETYS + GIS Boundaries (DNO/GSP) | NESO | Network topology for connection assessment |
| 13 | Wind Curtailment (BOA Volumes) | NESO | Constraint-driven curtailment risk |
| 14 | PV_Live (Sheffield Solar) | Sheffield Solar | Real solar output for yield validation |
| 15 | Regional Carbon Intensity | Carbon Intensity API | Site-specific carbon scoring |
| 16 | Flood Zones (Flood Map for Planning) | EA/Defra | Planning constraint (automatic screening) |
| 17 | Ancient Woodland / Green Belt | Natural England | Planning constraint (automatic screening) |
| 18 | CfD Register + AR7 Results | DESNZ/LCCC | Revenue benchmarking, strike prices |
| 19 | CM Clearing Prices | EMR Settlement | CM revenue modelling |
| 20 | REGO Register | Ofgem | Renewable asset verification |
| 21 | FIT Register | Ofgem | Small-scale renewables database |
| 22 | NPg Site Utilisation + Heat Map | NPg | Network capacity heat mapping |
| 23 | NGED Connection Queue | NGED | Post-reform queue position data |
| 24 | SSEN Smart Meter / NeRDA | SSEN | Granular demand data for connection |
| 25 | SSEN DFES | SSEN | LCT uptake projections by substation |
| 26 | UKPN Data Centre Utilisation | UKPN | DC demand hotspot identification |
| 27 | REMIT Messages | Elexon | Planned outages and urgent market info |
| 28 | System Inertia | NESO | Grid stability metrics |
| 29 | TNUoS Tariffs | NESO | Transmission charging by zone |
| 30 | Planning Applications | planning.data.gov.uk | Planning outcome tracking |

### Tier 2 -- MEDIUM PRIORITY

- All interconnector flow data (NESO)
- MEL/MIL (max export/import limits)
- DISBSAD/NETBSAD (balancing adjustments)
- Ancillary service auction results (FFR, STOR, EAC)
- Transmission losses
- DNO LTDS tables
- DNO flexibility zones/procurement data
- Met Office Weather DataHub
- EPEX Spot intraday prices
- N2EX direct prices (vs BMRS MID proxy)
- FES flexibility, transport, gas scenarios
- Historic generation mix

### Tier 3 -- LOW PRIORITY

- System frequency archives (already have real-time)
- OS Terrain (already use NASADEM)
- Skip rates
- AAHEDC tariffs
- Heritage coasts
- Radar/satellite imagery (Met Office)
- Modo Energy commercial API

---

## INGESTION ARCHITECTURE RECOMMENDATIONS

### Already Working Well
- Elexon BMRS v1 REST (no auth, JSON, 15+ datasets)
- NESO CKAN (TEC register)
- DNO OpenDataSoft (5 DNOs) + CKAN (NGED)
- Carbon Intensity API (national)
- EA Flood Monitoring (warnings)
- Natural England ArcGIS (SSSI, SAC, SPA, AONB, ALC)
- REPD (via DB table)

### New Adapters Needed
1. **NESO CKAN bulk ingester** -- extend existing CKAN adapter to ingest 20+ high-priority NESO datasets
2. **Elexon balancing adapter** -- new module for BOALF, BOD, FPN, LOLP (different endpoint patterns from dataset endpoints)
3. **Ofgem RER scraper** -- download REGO/FIT/RO register CSVs (no API)
4. **Sheffield Solar PV_Live adapter** -- simple REST, pip package available
5. **EA Flood Zone GIS ingester** -- download & import Flood Zone shapefiles into PostGIS
6. **Natural England additional layers** -- Ancient Woodland, Green Belt (same ArcGIS pattern)
7. **EMR/CfD data ingester** -- CSV downloads from GOV.UK
8. **Carbon Intensity regional adapter** -- extend existing to use /regional endpoints
9. **SSEN CKAN adapter** -- data.ssen.co.uk uses CKAN (different from OpenDataSoft)
10. **Nord Pool N2EX adapter** -- direct day-ahead prices

---

## Sources

- [Elexon BMRS API Documentation](https://bmrs.elexon.co.uk/api-documentation)
- [Elexon Developer Portal](https://developer.data.elexon.co.uk/)
- [NESO Data Portal](https://www.neso.energy/data-portal)
- [NESO API Guidance](https://www.neso.energy/data-portal/api-guidance)
- [NESO TEC Register](https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register)
- [NESO Embedded Register](https://www.neso.energy/data-portal/embedded-register)
- [NESO Capacity Market Register](https://www.neso.energy/data-portal/capacity-market-register)
- [NESO ETYS Boundaries](https://www.neso.energy/data-portal/etys-gb-transmission-system-boundaries)
- [NESO BSUoS Data](https://www.neso.energy/data-portal/current-balancing-services-use-system-bsuos-data)
- [NESO Thermal Constraint Costs](https://www.neso.energy/data-portal/thermal-constraint-costs/thermal_constraint_costs_data_25-26)
- [NESO Connections Reform Results](https://www.neso.energy/industry-information/connections-reform/connections-reform-results)
- [UK Power Networks Open Data Portal](https://ukpowernetworks.opendatasoft.com/explore/)
- [NGED Connected Data Portal](https://connecteddata.nationalgrid.co.uk/dataset/)
- [NGED Connection Queue](https://connecteddata.nationalgrid.co.uk/dataset/connection-queue)
- [Northern Powergrid Open Data](https://northernpowergrid.opendatasoft.com/explore/)
- [SSEN Distribution Data Portal](https://data.ssen.co.uk/)
- [SSEN Network Capacity](https://data.ssen.co.uk/collections/network-capacity)
- [SP Energy Networks Open Data](https://spenergynetworks.opendatasoft.com/explore/)
- [Electricity North West Open Data](https://electricitynorthwest.opendatasoft.com/explore/)
- [Ofgem Data Portal](https://www.ofgem.gov.uk/data-portal)
- [Ofgem REGO Public Reports](https://www.ofgem.gov.uk/renewables-energy-guarantees-origin-rego/contacts-publications-and-data/public-reports-and-data-rego)
- [Ofgem FIT Public Reports](https://www.ofgem.gov.uk/public-reports-and-data-fit)
- [Renewable Electricity Register](https://rer.ofgem.gov.uk/)
- [Environment Agency Flood Monitoring API](https://environment.data.gov.uk/flood-monitoring/doc/reference)
- [Flood Map for Planning - Flood Zones](https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47)
- [Planning Data](https://www.planning.data.gov.uk/dataset/)
- [REPD Quarterly Extract](https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract)
- [Carbon Intensity API](https://carbon-intensity.github.io/api-definitions/)
- [Sheffield Solar PV_Live](https://www.solar.sheffield.ac.uk/pvlive/)
- [Sheffield Solar PV_Live API](https://www.solar.sheffield.ac.uk/api/)
- [Met Office Weather DataHub](https://datahub.metoffice.gov.uk/)
- [Met Office DataPoint Retirement FAQs](https://www.metoffice.gov.uk/services/data/datapoint/datapoint-retirement-faqs)
- [OS Data Hub Open Downloads](https://osdatahub.os.uk/downloads/open)
- [Nord Pool N2EX Day-Ahead Prices](https://data.nordpoolgroup.com/auction/n2ex/prices)
- [EPEX Spot Market Results](https://www.epexspot.com/en/market-results)
- [EMR Settlement Data](https://www.emrsettlement.co.uk/settlement-data/settlement-data-capacity-providers/)
- [CfD Allocation Round 7 Results](https://www.cfdallocationround.uk/news)
- [Modo Energy Developer API](https://developers.modoenergy.com/docs/wholesale-power-prices)
- [Open Net Zero (Icebreaker One)](https://opennetzero.org/dataset-list)
- [CKAN on SSEN](https://ckan.org/events/ssen-energy-data-transparency-net-zero-first-dno-open-data-portal-smart-metering)
- [OpenDataSoft Explore API v2.1](https://help.opendatasoft.com/apis/ods-explore-v2/)
