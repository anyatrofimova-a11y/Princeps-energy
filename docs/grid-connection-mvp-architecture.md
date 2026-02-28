# Princeps Grid Connection & Load Capacity Module
## MVP Architecture + Competitor Intelligence + 3D Digital Twin

---

## 1. HALCYON.IO DECONSTRUCTION

**What it actually is:** AI-powered US energy *regulatory intelligence* platform (not a UK grid connection tool).

| Aspect | Detail |
|--------|--------|
| **Core** | Search, alerts, and structured data across 5.5M+ US regulatory filings from 41+ state PUCs, FERC, ISOs |
| **AI** | LLM-powered natural language search with inline citations; knowledge graph linking entities/dockets/filings |
| **Products** | Halcyon Search (free beta), Alerts (free), Query (paid), 5 Data Trackers (paid) |
| **Trackers** | Gas Power Plant (201 plants, 104 GW), BESS (440+ projects, ~210 GWh), Rate Case (259 cases), Large Load Tariff (108 tariffs), New Substation (200+ projects) |
| **Funding** | $10.8M seed (Apr 2024) — Obvious Ventures + Congruent Ventures + Overture Climate VC |
| **Team** | Bruce Falck (ex-Twitter revenue), Nat Bullard (ex-BloombergNEF), Jonathan Lewis (ex-Stripe VP Product), Alex Huras (CTO) |
| **Tech hints** | Knowledge graph, ~2K docs/day ingestion, REST API (publisher/filing_type/date params), entity pages |
| **No** | Public API, open source, UK coverage, geospatial analysis, engineering calculations |

**Takeaway for Princeps:** Halcyon's *data product architecture* (AI-extracted structured trackers from unstructured filings) and knowledge graph approach are applicable patterns. Their regulatory intelligence model could be adapted for UK planning/connection data.

---

## 2. COMPETITOR LANDSCAPE

### Direct Competitors (UK Grid Connection)

| Company | What | Pricing | Funding | Developer-Facing? |
|---------|------|---------|---------|-------------------|
| **Searchland** | UK site sourcing + DNO capacity data, 400K substations, all 6 DNOs, API available | GBP 195/user/mo | Bootstrapped? | Yes |
| **LandTech** | UK proptech + power infrastructure layer, daily DNO refresh | Subscription | Established proptech | Partial |
| **Roadnight Taylor** | UK grid connection consultancy ("Connectology"), HV/EHV specialist | Consultancy fees | Bootstrapped | Services only |
| **VisNet (EA Tech)** | DNO-side connection quoting automation (15-min MV quotes) | Enterprise to DNOs | EA Technology Group | No |

### Key International Players

| Company | What | Funding | Moat |
|---------|------|---------|------|
| **Nira Energy** | US grid capacity mapping at every >=69kV substation, cost prediction | YC-backed + Energize Capital | 500 GW studied, profitable |
| **Pearl Street / Enverus** | Interconnection study automation (SUGAR engine, 200x faster) | Acquired by Enverus (Mar 2025) | CMU power flow engine |
| **GridUnity** | Interconnection lifecycle mgmt, 37 US states, 50% pop coverage | $49.5M DOE GRIP award | PG&E, Southern Company |
| **envelio** | Digital twin of grid, Connection Navigator with hosting capacity | E.ON majority stake | 60+ utilities, academic spin-out |
| **GridCare** | AI to find hidden grid capacity for data centers | $13.5M (Breakthrough Energy) | Claims 100+ GW hidden capacity |
| **Gridcog** | Energy project simulation, 30+ markets incl GB | GBP 3.3M Series A | Multi-market revenue modelling |
| **Plexigrid** | LV/MV grid analytics + connection automation | EUR 6.5M EIC | European DSO focus |
| **Heimdall Power** | Physical sensors for dynamic line rating (40% more capacity) | $25M Series B | Hardware + software moat |

### Market Gaps (MVP Opportunities)

1. **No UK platform combines capacity mapping + connection cost estimation + feasibility in one developer-facing tool**
2. **envelio's Connection Navigator concept doesn't exist developer-facing in UK**
3. **NESO Connections Reform (2025-2026) creates new data streams nobody serves yet**
4. **No competitor integrates satellite/geospatial + grid capacity** (Princeps differentiator)
5. **No AI-assisted grid connection advisory exists in UK** (Roadnight charges premium consultancy for automatable work)

---

## 3. OPEN SOURCE & DATA SOURCES

### Power System Analysis Libraries

| Library | GitHub Stars | Language | Best For |
|---------|-------------|----------|----------|
| **PyPSA** | ~1,900 | Python (MIT) | Full AC/DC power flow, capacity expansion, sector coupling |
| **pandapower** | ~1,100 | Python (BSD-3) | Distribution-level connection assessment, Newton-Raphson, OPF |
| **power-grid-model** | ~194 | C++/Python (MPL-2) | Fast power flow for distribution, Linux Foundation Energy |
| **lightsim2grid** | — | C++/Python (MPL-2) | 10-20x faster than pandapower, drop-in backend |
| **PyPSA-GB** | — | Python (MIT) | Full GB transmission model (2,000+ bus ETYS) |
| **NREL DISCO** | — | Python (BSD-3) | Hosting capacity analysis at distribution level |
| **GridKit** | — | Python + PostGIS | OSM power grid topology extraction (PostGIS-native!) |

### UK Data APIs

**National Level (Transmission):**
| Source | API Type | Auth | Key Data |
|--------|----------|------|----------|
| NESO Data Portal | CKAN v3 | No | Demand forecasts, gen mix, TEC Register (2x/week), constraint data |
| Elexon BMRS | REST | API key | Generation by fuel, prices, demand, frequency, imbalance |
| Carbon Intensity | REST | No | 14-region carbon intensity, gen mix, 30-min resolution |
| National Grid Connected Data | CKAN v3 | Token | Connection queue, capacity register, EV capacity, substation locations |

**DNO Level (Distribution) — 5 of 6 use OpenDataSoft:**
| DNO | Platform | Key Data |
|-----|----------|----------|
| UKPN | OpenDataSoft | GSP capacity/headroom, DG capacity map, substation data |
| NGED (ex-WPD) | CKAN | Network capacity map, gen capacity register, constraint zones |
| SSEN | Custom/ODS | Generation availability, GSP details, transformer ratings, fault levels |
| Northern Powergrid | OpenDataSoft (87 datasets) | Thermal demand/generation headroom per substation |
| SP Energy Networks | OpenDataSoft | Embedded capacity register |
| Electricity North West | OpenDataSoft (90 datasets) | HV network capacity, heat map, DFES scenarios |

**Geospatial/Topology:**
- OpenStreetMap via Overpass API — all UK power infrastructure
- Open Infrastructure Map — GeoJSON + vector tiles
- Geofabrik — country-level power network extracts
- NESO GIS Boundaries — 14 DNO licence areas
- GridKit pre-computed — European HV network (Zenodo)

### Python Data Wrappers
- `NGDataPortal` — NESO CKAN wrapper, returns DataFrames
- `ElexonDataPortal` — 50+ BMRS data streams
- `gridstatus` — US ISOs (architectural template for UK equivalent)

---

## 4. MVP ARCHITECTURE

### Integration with Princeps Stack

```
┌─────────────────────────────────────────────────────────┐
│                    PRINCEPS FRONTEND                     │
│  React + Vite + MapLibre GL                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ Site Map  │ │ Chat     │ │ Agent    │ │ Grid Panel │ │
│  │ Layers    │ │ Panel    │ │ Panel    │ │ (NEW)      │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP / SSE
┌─────────────────────┴───────────────────────────────────┐
│                    FASTAPI BACKEND                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Grid Connection Module (NEW)                      │   │
│  │  POST /api/grid/assess     — site feasibility     │   │
│  │  GET  /api/grid/substation — headroom + queue     │   │
│  │  GET  /api/grid/capacity   — GeoJSON heat map     │   │
│  │  GET  /api/grid/tec        — TEC register search  │   │
│  │  GET  /api/grid/ecr        — embedded capacity    │   │
│  │  GET  /api/grid/queue      — connection queue     │   │
│  └──────────────────────┬───────────────────────────┘   │
│                         │                                │
│  ┌──────────────────────┴───────────────────────────┐   │
│  │ Agent Module (EXTEND)                             │   │
│  │  New intent: grid_connection                      │   │
│  │  GO/CAUTION/NO-GO verdicts                        │   │
│  └──────────────────────────────────────────────────┘   │
└──────────┬──────────────────────────────┬───────────────┘
           │                              │
┌──────────┴──────────┐    ┌──────────────┴──────────────┐
│  PostGIS Database    │    │  Subprocess Workers         │
│  ┌────────────────┐  │    │  ┌────────────────────────┐ │
│  │ substations    │  │    │  │ grid_analyser.py       │ │
│  │ tec_register   │  │    │  │ (pandapower + lightsim)│ │
│  │ ecr_register   │  │    │  ├────────────────────────┤ │
│  │ dno_boundaries │  │    │  │ grid_data_ingester.py  │ │
│  │ grid_topology  │  │    │  │ (CKAN + ODS adapters)  │ │
│  │ capacity_hm    │  │    │  ├────────────────────────┤ │
│  │ connection_q   │  │    │  │ sam_runner.py (exists) │ │
│  └────────────────┘  │    │  │ geeflow_runner.py      │ │
│  SRID 27700 (BNG)    │    │  └────────────────────────┘ │
└──────────────────────┘    └─────────────────────────────┘
```

### Database Schema (New Tables)

```sql
-- All UK substations with capacity data
CREATE TABLE grid_substations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    dno TEXT NOT NULL,        -- UKPN, NGED, SSEN, NPG, SPEN, ENWL
    voltage_kv NUMERIC,
    demand_headroom_mw NUMERIC,
    generation_headroom_mw NUMERIC,
    fault_level_ka NUMERIC,
    rag_status TEXT,          -- green/amber/red
    geom GEOMETRY(Point, 27700),
    raw_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_substations_geom ON grid_substations USING GIST(geom);
CREATE INDEX idx_substations_dno ON grid_substations(dno);

-- TEC Register (transmission-connected projects)
CREATE TABLE tec_register (
    id SERIAL PRIMARY KEY,
    project_name TEXT,
    developer TEXT,
    technology TEXT,
    capacity_mw NUMERIC,
    connection_site TEXT,
    status TEXT,
    gate_stage TEXT,          -- Gate 1, Gate 2, etc.
    target_date DATE,
    geom GEOMETRY(Point, 27700),
    raw_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Embedded Capacity Register (distribution DER)
CREATE TABLE ecr_register (
    id SERIAL PRIMARY KEY,
    site_name TEXT,
    dno TEXT,
    technology TEXT,
    capacity_mw NUMERIC,
    connection_voltage_kv NUMERIC,
    substation_id INTEGER REFERENCES grid_substations(id),
    status TEXT,              -- connected, accepted, queued
    geom GEOMETRY(Point, 27700),
    raw_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- DNO licence area boundaries
CREATE TABLE dno_boundaries (
    id SERIAL PRIMARY KEY,
    dno_code TEXT NOT NULL,
    dno_name TEXT NOT NULL,
    geom GEOMETRY(MultiPolygon, 27700)
);

-- Grid topology (lines from OSM/GridKit)
CREATE TABLE grid_lines (
    id SERIAL PRIMARY KEY,
    voltage_kv NUMERIC,
    circuits INTEGER,
    operator TEXT,
    from_substation_id INTEGER REFERENCES grid_substations(id),
    to_substation_id INTEGER REFERENCES grid_substations(id),
    length_km NUMERIC,
    geom GEOMETRY(LineString, 27700),
    raw_data JSONB
);
CREATE INDEX idx_grid_lines_geom ON grid_lines USING GIST(geom);

-- Connection queue (post-NESO reform)
CREATE TABLE connection_queue (
    id SERIAL PRIMARY KEY,
    applicant TEXT,
    capacity_mw NUMERIC,
    technology TEXT,
    connection_point TEXT,
    substation_id INTEGER REFERENCES grid_substations(id),
    application_date DATE,
    milestone_stage TEXT,
    estimated_connection DATE,
    dno TEXT,
    geom GEOMETRY(Point, 27700),
    raw_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Data Ingestion Architecture

```python
# utils/grid_data_ingester.py — unified adapter pattern

class DataAdapter:
    """Base class for DNO/NESO data sources."""

class OpenDataSoftAdapter(DataAdapter):
    """Handles UKPN, NPG, SPEN, ENWL, SSEN (5 of 6 DNOs)."""
    # All use same ODS API v2.1: /api/explore/v2.1/catalog/datasets/{id}/records

class CKANAdapter(DataAdapter):
    """Handles NESO Data Portal + NGED Connected Data Portal."""
    # Both use CKAN v3: /api/3/action/datastore_search

class OverpassAdapter(DataAdapter):
    """Extracts power infrastructure from OpenStreetMap."""
    # Overpass QL: [power=substation][voltage~"400000|275000|132000|66000|33000"]
```

### Assessment Engine

```python
# utils/grid_analyser.py — connection feasibility assessment

def assess_connection(lat, lon, capacity_mw, technology):
    """
    Three-tier assessment:

    Tier 1 — Data-driven (instant, no simulation):
      - Find nearest substations within 5/10/20km
      - Look up published headroom
      - Count queued projects consuming headroom
      - Check fault level constraints
      - Return: available_mw, queue_depth, estimated_cost_range

    Tier 2 — Power flow validation (seconds):
      - Build pandapower network model from substation data
      - Add proposed generator at nearest bus
      - Run Newton-Raphson power flow
      - Check thermal limits, voltage rise, reverse power flow
      - Return: voltage_deviation, thermal_loading, constraint_violations

    Tier 3 — Full transmission study (minutes):
      - Load PyPSA-GB model (32-bus reduced or 17-zone)
      - Add proposed connection at nearest transmission node
      - Run LOPF with N-1 contingency
      - Return: transmission_constraints, curtailment_risk, reinforcement_needs
    """
```

---

## 5. 3D DIGITAL TWIN + PROBABILISTIC DEMAND FORECASTING

### 5A. 3D Digital Twin Components

**Core 3D Libraries:**

| Library | Purpose | Integration |
|---------|---------|-------------|
| **Three.js** | WebGL 3D rendering engine | Base layer for substation/line 3D models |
| **Deck.gl** | Large-scale geospatial 3D vis | Power line corridors, capacity heat maps, flow animations |
| **CesiumJS** | 3D globe + terrain | Terrain-aware infrastructure placement |
| **Mapbox GL JS** (or MapLibre) | 3D buildings + terrain | Base map with extrusion for grid assets |
| **react-three-fiber** | React bindings for Three.js | Component-based 3D in existing React app |

**Digital Twin Architecture:**

```
┌─────────────────────────────────────────────────────────┐
│                3D DIGITAL TWIN LAYER                     │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Terrain      │  │ Grid Assets  │  │ Data Overlays  │ │
│  │ - NASADEM    │  │ - Substations│  │ - Power flow   │ │
│  │ - Lidar DTM  │  │ - Lines      │  │ - Headroom     │ │
│  │ - Landcover  │  │ - Generators │  │ - Demand       │ │
│  │ - Buildings  │  │ - Cables     │  │ - Congestion   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬─────────┘ │
│         │                 │                  │            │
│  ┌──────┴─────────────────┴──────────────────┴─────────┐ │
│  │           Deck.gl / CesiumJS Render Engine           │ │
│  │   - Animated power flow arrows on lines              │ │
│  │   - Substation 3D models (size = capacity)           │ │
│  │   - Heat map extrusion (height = demand/headroom)    │ │
│  │   - Time-slider for temporal demand patterns         │ │
│  │   - Click-to-inspect any asset                       │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket (real-time updates)
┌──────────────────────┴──────────────────────────────────┐
│              TWIN STATE ENGINE (Backend)                  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Asset State   │  │ Flow State   │  │ Scenario      │ │
│  │ Manager       │  │ Calculator   │  │ Engine        │ │
│  │ - Health      │  │ - pandapower │  │ - What-if     │ │
│  │ - Maintenance │  │ - Real-time  │  │ - N-1         │ │
│  │ - Age/rating  │  │   dispatch   │  │ - Growth      │ │
│  └──────────────┘  └──────────────┘  └───────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**3D Asset Models:**

| Asset | 3D Representation | Data Source |
|-------|-------------------|-------------|
| Substations | Extruded footprint, height ~ voltage level | OSM + DNO data |
| Transmission lines | Catenary curves with tower models | OSM power=line |
| Pylons/towers | Parametric models by type (lattice, T-pylon) | OSM power=tower |
| Solar farms | Panel arrays on terrain | GeeFlow Sentinel-2 + planning |
| Wind farms | Turbine models with rotor animation | TEC/ECR register |
| Battery storage | Container models | ECR register |
| Cable routes | Underground path visualisation | OSM power=cable |
| Constraint zones | Semi-transparent volumes | DNO constraint data |

**Open Source 3D Grid Assets:**
- `power-grid-model` has network topology that maps to 3D
- OSM 3D building data (height tags) for substation buildings
- Lidar DTM from DEFRA (1m resolution UK terrain)
- OS Open ZoomStack for building footprints

### 5B. Probabilistic Demand Forecasting

**Architecture:**

```
┌──────────────────────────────────────────────────────────┐
│            PROBABILISTIC DEMAND FORECASTING               │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ Historical   │  │ Covariates   │  │ Scenario        │ │
│  │ Demand Data  │  │              │  │ Drivers         │ │
│  │ - BMRS half- │  │ - Weather    │  │ - EV uptake     │ │
│  │   hourly     │  │ - Calendar   │  │ - Heat pumps    │ │
│  │ - DNO GSP    │  │ - Economic   │  │ - Solar PV      │ │
│  │   profiles   │  │ - Population │  │ - Data centres  │ │
│  │ - Smart meter│  │ - Industrial │  │ - DFES curves   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬──────────┘ │
│         │                 │                  │             │
│  ┌──────┴─────────────────┴──────────────────┴──────────┐ │
│  │              FORECASTING ENGINE                       │ │
│  │                                                       │ │
│  │  Layer 1: Temporal Fusion Transformer (TFT)           │ │
│  │  - Google's state-of-art for multi-horizon forecasts  │ │
│  │  - Built-in attention over variable-length history    │ │
│  │  - Quantile outputs (P10, P50, P90)                   │ │
│  │  - PyTorch Forecasting or Darts library               │ │
│  │                                                       │ │
│  │  Layer 2: Gaussian Process Regression                 │ │
│  │  - Full posterior distribution over demand             │ │
│  │  - Captures epistemic uncertainty (sparse data areas) │ │
│  │  - GPyTorch or scikit-learn                           │ │
│  │                                                       │ │
│  │  Layer 3: Scenario-Weighted Ensemble                  │ │
│  │  - NESO FES scenarios (Leading the Way, Consumer      │ │
│  │    Transformation, System Transformation, Falling     │ │
│  │    Short) as prior weights                            │ │
│  │  - Monte Carlo simulation across scenario paths       │ │
│  │  - Copula-based correlation between regions           │ │
│  └──────────────────────┬────────────────────────────────┘ │
│                         │                                  │
│  ┌──────────────────────┴────────────────────────────────┐ │
│  │              OUTPUT: PROBABILISTIC FORECASTS           │ │
│  │                                                       │ │
│  │  Per substation/GSP:                                  │ │
│  │  - P10/P50/P90 demand curves (hourly, 1-20 years)    │ │
│  │  - Probability of capacity exceedance by year         │ │
│  │  - Expected time-to-constraint                        │ │
│  │  - Peak demand distribution (GEV/Weibull)             │ │
│  │  - Coincidence factor across connected sites          │ │
│  │                                                       │ │
│  │  Per grid zone:                                       │ │
│  │  - Net demand (demand - embedded gen) distribution    │ │
│  │  - Reverse power flow probability                     │ │
│  │  - Curtailment risk curves                            │ │
│  └───────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**Key Libraries:**

| Library | Purpose | Why |
|---------|---------|-----|
| **Darts** (unit8co) | Probabilistic time series | TFT, N-BEATS, DeepAR, GP models; quantile + distributional forecasts |
| **PyTorch Forecasting** | TFT implementation | Google's Temporal Fusion Transformer for multi-horizon |
| **GPyTorch** | Gaussian processes | Scalable GP regression for uncertainty quantification |
| **Pyro / NumPyro** | Probabilistic programming | Full Bayesian inference for scenario modelling |
| **CopulaLib** | Dependency modelling | Spatial demand correlation between substations |
| **scipy.stats** | Distribution fitting | GEV/Weibull for peak demand extremes |
| **Prophet** (Meta) | Baseline seasonal decomposition | Quick baseline with changepoint detection |

**Data Sources for Forecasting:**

| Data | Source | Resolution |
|------|--------|------------|
| Historical national demand | Elexon BMRS | 30-min, 5+ years |
| GSP-level demand profiles | DNO open data (NPG, UKPN) | 30-min per substation |
| Weather (temperature, wind, solar) | ERA5 / Met Office MIDAS | Hourly gridded |
| DFES scenario curves | Each DNO publishes annually | Annual by technology |
| FES national scenarios | NESO | Annual to 2050, 4 pathways |
| EV registrations | DfT / DVLA | Quarterly by region |
| Heat pump installations | MCS database / BRE | Monthly by postcode |
| New connections | DNO embedded capacity registers | Quarterly |
| Population / housing growth | ONS projections | Annual by LSOA |

### 5C. Advanced Components

**Dynamic Line Rating (DLR):**
- Use ERA5 wind speed + temperature at line location
- Calculate real-time thermal capacity using IEEE 738 / CIGRE TB601
- Show capacity uplift (typically 10-40% above static rating) in 3D twin
- Open source: `openoa` (NREL) has thermal rating calculations

**Network Congestion Prediction:**
- Train classifier on historical constraint data (NESO publishes constraint costs by location)
- Features: demand forecast, wind/solar forecast, outage schedule, historical congestion
- Output: probability of congestion at each transmission boundary per hour
- Visualise as animated heatmap on 3D twin

**Optimal Connection Point Selection:**
- Multi-objective optimisation: minimise (distance + reinforcement_cost + queue_wait)
- Constraints: headroom >= capacity, voltage within limits, fault level within rating
- Use NSGA-II (pymoo library) for Pareto frontier of connection options
- Display trade-off curves in agent panel

**Reinforcement Cost Estimation:**
- Rule-based model from published DNO cost data:
  - HV cable: ~GBP 80-150/m
  - 33kV switchgear: ~GBP 200-400K per bay
  - 132/33kV transformer: ~GBP 2-5M
  - 132kV overhead line: ~GBP 500-800K/km
- Calibrated against published connection offers (Ofgem data)
- Probabilistic range (P10/P50/P90) based on historical variance

---

## 6. BUILD SEQUENCE

### Phase 1: Data Foundation (Weeks 1-3)
- [ ] Set up `grid_data_ingester.py` with OpenDataSoft + CKAN adapters
- [ ] Ingest TEC Register, ECR from all 6 DNOs, substation locations
- [ ] Load DNO boundaries + OSM grid topology via GridKit into PostGIS
- [ ] Create scheduled refresh jobs (daily for headroom, weekly for registers)

### Phase 2: Assessment API (Weeks 3-5)
- [ ] Build `grid_analyser.py` with Tier 1 data-driven assessment
- [ ] Implement `/api/grid/assess` endpoint
- [ ] Add `grid_connection` intent to `app/agent.py`
- [ ] Connection to existing chat panel for grid queries

### Phase 3: Map Visualisation (Weeks 5-7)
- [ ] Substation layer with RAG headroom colours
- [ ] Grid line overlay from PostGIS
- [ ] Connection queue markers
- [ ] Click-to-assess interaction

### Phase 4: Power Flow (Weeks 7-9)
- [ ] Install pandapower + lightsim2grid in `.venv/` (or subprocess bridge)
- [ ] Build representative feeder models from DNO data
- [ ] Implement Tier 2 power flow validation
- [ ] Validate against published headroom figures

### Phase 5: Demand Forecasting (Weeks 9-12)
- [ ] Ingest historical demand data (BMRS + DNO GSP profiles)
- [ ] Train baseline Prophet models per GSP
- [ ] Implement TFT model with Darts for probabilistic forecasts
- [ ] Add forecast endpoints + time-slider in frontend

### Phase 6: 3D Digital Twin (Weeks 12-16)
- [ ] Add Deck.gl layer for 3D infrastructure visualisation
- [ ] Substation extrusions, line catenary rendering
- [ ] Animated power flow arrows
- [ ] Real-time demand overlay via WebSocket
- [ ] Scenario toggle (FES pathways)

### Phase 7: Advanced (Weeks 16+)
- [ ] Dynamic line rating calculator
- [ ] Congestion prediction ML model
- [ ] Multi-objective connection optimisation
- [ ] Reinforcement cost estimator
- [ ] PyPSA-GB transmission studies (Tier 3)

---

## 7. KEY OPEN SOURCE REPOS

```
# Core analysis
pip install pypsa pandapower lightsim2grid power-grid-model

# Forecasting
pip install darts pytorch-forecasting gpytorch pyro-ppl prophet

# Data access
pip install NGDataPortal ElexonDataPortal

# Optimisation
pip install pymoo scipy

# 3D visualisation (npm)
npm install three @react-three/fiber @react-three/drei deck.gl @deck.gl/core
npm install @deck.gl/layers @deck.gl/geo-layers cesium
```

## 8. SOURCES

### Companies
- [Halcyon.io](https://halcyon.io) — US energy regulatory intelligence
- [Searchland](https://searchland.co.uk) — UK site sourcing + DNO data (GBP 195/mo, has API)
- [Nira Energy](https://www.niraenergy.com) — US grid capacity mapping (YC)
- [envelio](https://envelio.com) — Grid digital twin + Connection Navigator (E.ON)
- [Pearl Street / Enverus](https://pearlstreettechnologies.com) — Interconnection study automation
- [GridUnity](https://www.gridunity.com) — Interconnection lifecycle ($49.5M DOE)
- [Gridcog](https://www.gridcog.com) — Energy project simulation (GB support)
- [GridCare](https://www.gridcare.ai) — Hidden capacity for data centers
- [Roadnight Taylor](https://roadnighttaylor.co.uk) — UK grid connection consultancy
- [VisNet](https://visnet.tech) — DNO connection quoting automation
- [LandTech](https://land.tech) — UK proptech + power infrastructure
- [Plexigrid](https://plexigrid.com) — LV/MV grid analytics
- [Heimdall Power](https://www.heimdallpower.com) — Dynamic line rating sensors

### Data Portals
- [NESO Data Portal](https://www.neso.energy/data-portal)
- [National Grid Connected Data](https://connecteddata.nationalgrid.co.uk/)
- [UKPN Open Data](https://ukpowernetworks.opendatasoft.com/explore/)
- [Northern Powergrid Open Data](https://northernpowergrid.opendatasoft.com/explore/)
- [SSEN Data](https://data.ssen.co.uk/)
- [Electricity North West Open Data](https://electricitynorthwest.opendatasoft.com/explore/)
- [SP Energy Networks Open Data](https://spenergynetworks.opendatasoft.com/)
- [Elexon BMRS API](https://bmrs.elexon.co.uk/api-documentation)
- [Carbon Intensity API](https://carbonintensity.org.uk/)
- [ENA Connections Data](https://www.energynetworks.org/industry/connecting-to-the-networks/connections-data)
- [Open Infrastructure Map](https://openinframap.org/)

### GitHub Repos
- [PyPSA](https://github.com/PyPSA/PyPSA) ~1,900 stars
- [pandapower](https://github.com/e2nIEE/pandapower) ~1,100 stars
- [power-grid-model](https://github.com/PowerGridModel/power-grid-model) LF Energy
- [lightsim2grid](https://github.com/Grid2op/lightsim2grid) 10-20x faster
- [PyPSA-GB](https://github.com/andrewlyden/PyPSA-GB) Full GB transmission
- [NREL DISCO](https://github.com/NREL/disco) Hosting capacity
- [GridKit](https://github.com/bdw/GridKit) OSM -> PostGIS topology
- [NGDataPortal](https://github.com/OSUKED/NGDataPortal) NESO wrapper
- [ElexonDataPortal](https://github.com/OSUKED/ElexonDataPortal) BMRS wrapper
- [Open Infrastructure Map](https://github.com/openinframap/openinframap)
- [Awesome Electrical Grid Mapping](https://github.com/open-energy-transition/Awesome-Electrical-Grid-Mapping)
- [Darts](https://github.com/unit8co/darts) Probabilistic time series
