# Data Centre Planning Module Research
## Competitive Intelligence & Technical Deep Dive for Princeps DC Module

---

## 1. CADENCE REALITY DC (formerly 6SigmaDCX / Future Facilities)

**Status:** Industry leader in DC thermal/airflow CFD simulation. Acquired by Cadence Design Systems.

### Analyses Performed
- **CFD (Computational Fluid Dynamics):** Full 3D airflow and temperature distribution simulation
- **Thermal Analysis:** Steady-state and transient-state thermal simulations; hotspot identification
- **Failure Analysis:** Simulate cooling unit failures, power chain failures; predict thermal impact
- **What-If Scenarios:** Test cabinet power changes, floor cutout modifications, supply configurations
- **Solar Radiation Calculations:** Backtracing method (30x faster in latest release)
- **1D Flow Network:** Fast thermal flow analysis of liquid and air flow routes (DLC + immersion + air)
- **ASHRAE Compliance:** Automated checking against TC 9.9 temperature/humidity envelopes
- **PUE Calculation:** Integrated efficiency metrics

### Inputs Required
- 3D room geometry (CAD import, BIM model import)
- Rack layouts with per-server power loads and temperature rise
- CRAC/CRAH unit specifications and control parameters (VFDs, master/slave, staged controls)
- Floor tile configurations (perforated tiles, grilles, blanking panels)
- Containment systems (hot aisle, cold aisle)
- Cooling system types: indirect/direct free cooling, sprays, wet media
- Power network topology

### Outputs/Reports
- 3D thermal visualisation (temperature maps, airflow vectors, isosurfaces)
- Customisable dashboards and charts
- Risk analysis at any design stage
- Net sensible cooling capacity calculations
- VR visualisation (Oculus Rift compatible)
- Automated reporting in multiple formats
- Shareable result files

### UI & Workflow
- 3D drag-and-drop environment
- Library of 4,000+ data-centre-specific objects
- CAD import (2D and 3D)
- BIM model direct import
- Parallel solver with cloud compute scaling
- DCIM tool integrations (15+ tools)

### Pricing
- Enterprise licensing (not publicly disclosed). Likely $50K-200K+/year based on similar CFD tools.
- Free trial available

### What Makes It Unique
- Purpose-built CFD solver optimised specifically for data centres (not generic CFD)
- Digital twin concept: connects to real-time DCIM data
- Non-expert friendly: designed so you don't need a PhD in thermal engineering
- Hybrid cooling support: DLC + immersion + air in a single model

### Princeps Opportunity
We cannot replicate full CFD (that's a multi-year physics engine project), but we CAN:
- Build a **simplified thermal model** using rule-of-thumb calculations (kW/rack vs cooling capacity)
- Provide **ASHRAE compliance checking** against A1-A4 envelopes
- Calculate **cooling capacity requirements** from IT load
- Model **power chain topology** and failure scenarios
- Offer **3D rack visualisation** (we already have deck.gl 3D capability)

---

## 2. NLYTE DCIM

### Modules
1. **Asset Optimizer** — Lifecycle management, capacity planning, workflow automation, compliance/audit
2. **Energy Optimizer** — Power/cooling analytics, power chain risk, remote site validation
3. **Data Center Monitoring** — Utilisation, bottleneck identification, proactive maintenance

### Power Distribution Modelling
- Interactive, dynamic power chain analysis tool
- End-to-end visibility: circuits through compute systems
- Simulates power chain failures to validate redundancy
- Branch circuit monitoring (macro level energy tracking)
- Virtual PDU functionality (software replaces expensive intelligent PDUs)
- Tracks: busmain → tapoff → cabinets → strips → assets

### Metrics Tracked
- Real-time power, temperature, environmental data
- **PUE** (Power Usage Effectiveness)
- **DCiE** (Data Centre Infrastructure Efficiency = 1/PUE)
- Energy consumption and cost analysis
- Carbon emissions calculations
- Phase and load balancing metrics
- Variable cost of assets and true cost of service
- Real-time heat mapping

### Capacity Planning
- Forecast future power, space, cooling, network capacity
- "What-if" models for future state prediction
- Identifies unused and under-utilised capacity
- Helps postpone/eliminate new DC investments

### Integration Points
- Pre-built connectors: BMC, ServiceNow, HPE
- Extensive REST APIs
- ITSM system integration
- LDAP/Active Directory

### Pricing
- Enterprise licensing, not publicly disclosed. Estimated $50K-500K+ depending on scale.
- Gartner reviews indicate mid-to-high enterprise pricing.

### What Makes It Unique
- Power chain simulation is the standout feature
- Hardware-agnostic, protocol-based monitoring
- Strong compliance/audit trail

---

## 3. SCHNEIDER ELECTRIC EcoStruxure IT

### Architecture
- **Cloud-based** SaaS platform
- Vendor-neutral (any manufacturer's equipment)
- Covers: on-premises, colocation, cloud, edge

### Modules
- **EcoStruxure IT Expert** — Device-level monitoring, smart alarms
- **EcoStruxure IT Advisor** — Cloud-based asset and planning software

### Metrics Tracked
- Physical infrastructure (racks, cooling, power distribution)
- IT equipment (servers, storage, networking)
- Environmental conditions (temperature, humidity via sensor networks)
- PUE per site and room over time
- Power consumption per location vs historical trends
- Security metrics via camera integration

### Capacity Planning
- Global benchmarks and analytics in the "EcoStruxure data lake"
- Predictive insights on infrastructure risks using AI
- Automated sustainability metric reporting

### What Makes It Unique
- Cloud-native with global data lake for benchmarking
- Automated sustainability reporting (PUE, energy, carbon)
- Edge computing support alongside traditional DC
- Subscription/SaaS pricing model

---

## 4. VERTIV TRELLIS

### Modules
- **Site Manager** — Central monitoring dashboard
- **Thermal System Manager** — 3D real-time thermal visualisation
- **Energy Manager** — Power chain analysis
- **Asset Management** — Lifecycle tracking

### Power & Cooling Optimisation
- 3D real-time thermal visualisation with heat maps
- Rotate, pan, zoom into racks and rows for thermal inspection
- Advanced net sensible cooling capacity calculation
- Monitors entire mechanical chain: chillers → cooling towers → CRAC/CRAH
- Balances cooling and IT heat loads
- Power infrastructure visibility from utility entrance to rack PDU
- Automated KPI, SLA, and dashboard metrics
- AI-enhanced predictive maintenance

### Integration
- Supports wireless, wired, and rack PDU sensors
- Quick Start package: 30 floor-mounted devices, 25 sensor nodes, 1-year maintenance

### What Makes It Unique
- 3D thermal visualisation is the standout
- End-to-end power chain visibility in single view
- Modular, scalable architecture

---

## 5. OpenDCIM (Open Source)

### Technology Stack
- Apache 2.x + MySQL 5.x + PHP 8.0+ (LAMP)
- Web-based UI
- LDAP authentication support
- GPL v3 license

### Features
- Complete physical inventory/asset tracking
- Multiple rooms/data centres support
- Power connection mapping: device → power strip → panel → source feed
- Network connection mapping to switches
- Image mapping with custom maps (clickable zones per cabinet)
- Overlay layers: Power, Space, Temperature, Weight capacity
- Centre of gravity calculation for each cabinet
- Fault tolerance tracking
- Power outage simulation (impact of panel/source feed failure)
- Equipment archival
- Hosting cost reporting by department (cost per U + cost per Watt)
- Basic workflow for rack requests
- Drag-and-drop interface

### Limitations
- No REST API or GraphQL
- No CFD or thermal simulation
- No real-time monitoring (manual data entry)
- No cloud/SaaS option
- Limited reporting/dashboards
- No capacity planning forecasting

### What Makes It Unique
- Free and open source
- Solid for basic inventory and power mapping
- Power outage simulation is useful

---

## 6. SUNBIRD dcTrack

### Key Features
- **Rack-Level Capacity:** Real-time views of space, power, network ports, cooling per rack
- **Auto Power Budget:** AI calculates accurate power budget per device from actual measured load (eliminates stranded power)
- **Load Shift Detection:** Alerts when power supply redundancy is compromised
- **3D Visualisation:** Bird's-eye view of DC floor, true-to-scale blade chassis images
- **Cooling Management:** Derating factor for cooling unit age, multi-zone cooling assignment
- **Connectivity:** Visual trace routes, cable measurements, port connectivity
- **100+ Dashboard Widgets** out-of-the-box

### Metrics
- Space capacity per rack (U)
- Power capacity (budgeted vs actual)
- Heat output per rack
- Cooling capacity with age derating
- Network port availability (copper + fibre)
- Branch circuit feeds

### What Makes It Unique
- Auto Power Budget (AI-based) is the killer feature — eliminates stranded power
- True-to-scale rack elevation diagrams
- Strong at the rack level (vs facility level)

---

## 7. NETBOX (Open Source DCIM + IPAM)

### Technology Stack
- Python/Django backend
- PostgreSQL database
- REST API + GraphQL API
- Apache 2.0 license

### Features
- Hierarchical organisation: regions → sites → racks → devices
- IP address management (IPAM) for Layer 2/3
- Cable management and path visualisation
- Power connectivity documentation
- Rack elevation visualisation
- VPN, VLAN, circuit management
- Full CRUD REST API + GraphQL
- Plugin architecture for extensibility
- Templating system
- Device configuration management

### What Makes It Unique
- Best open-source option for modern DC management
- API-first design (perfect for automation)
- Active community (thousands of organisations)
- Extensible via plugins

---

## 8. CoolSim (SaaS CFD)

### Technical Details
- **Origin:** Developed at Ansys/Fluent in 2005; uses Ansys Icepak/Fluent solvers
- **Architecture:** Local model building + cloud HPC for meshing/solving/postprocessing
- **Pricing:** Pay-As-You-Go (no annual license required)

### Inputs Required
- 3D DC geometry (raised/non-raised floors, plenums, rooftop units)
- CRAC/CRAH specifications and control parameters
- IT rack configs with individual server power loads
- Ductwork and diffuser placement
- External conditions (wind, temperature)

### Outputs
- Numerical flow/temperature field reports
- 3D manipulable results in browser
- High-resolution graphics and animations
- HTML reports exportable to PowerPoint/Excel
- Shareable URLs

### What Makes It Unique
- Pay-as-you-go CFD (dramatically lower cost than 6SigmaDCX)
- Cloud-based solving eliminates need for local HPC

---

## 9. GOOGLE DC APPROACH

### Efficiency
- **Fleet-wide PUE: 1.09** (2024) vs industry average 1.56
- Best sites: PUE as low as 1.06
- 84% less overhead energy than industry average

### AI-Driven Cooling (DeepMind)
- Neural networks trained on DC operating scenarios
- **40% reduction in cooling energy** = 15% reduction in overall PUE overhead
- Now productised as "Industrial Adaptive Controls" platform

### Site Selection Priorities
1. **Carbon-free energy availability** — 24/7 CFE matching (not just annual)
2. **Renewable energy proximity** — 170+ agreements, 22+ GW of clean energy
3. **Climate-conscious cooling** — Evaporative cooling or free air when possible
4. **Water stewardship** — Replenished 4.5 billion gallons in 2024 (64% of consumption)
5. **Grid carbon intensity** — Carbon Heat Maps tracking hour-by-hour energy profile

### Energy Procurement
- $3.7B+ invested in clean energy projects
- 100% renewable energy match annually since 2017
- Acquired Intersect Power (~$5B) for "energy parks" co-locating DCs with generation + BESS
- Behind-the-meter PPAs to bypass grid congestion

### What Makes Their Approach Unique
- 24/7 carbon-free energy (hourly matching, not annual)
- AI-driven cooling optimisation
- Co-located generation + storage ("energy parks")
- Water replenishment programme

---

## 10. MICROSOFT DC APPROACH

### Project Natick (Underwater DC)
- Deployed to Orkney Islands (100% wind/solar grid)
- **1/8th the failure rate** of land-based DCs
- Nitrogen atmosphere (less corrosive than oxygen)
- Zero water consumption for cooling
- Zero freshwater impact
- **Status:** Discontinued as of 2024. Learnings applied to conventional designs.

### Site Selection
- Proximity to coast (>50% world population within 120 miles)
- Renewable energy grid access
- Low-latency fibre to population centres

### Sustainability
- Carbon negative by 2030 commitment
- Hydrogen fuel cell backup generators (replacing diesel)
- Water positive commitment

---

## 11. AWS DC APPROACH

### Site Selection Criteria
1. **Power:** Multiple independent feeds, on-site UPS, diesel backup (auto-start within seconds)
2. **Water:** Critical for cooling; proposed 630MW campus withdrawn over water constraints ($3.6B project)
3. **Fibre:** ~20 million km of terrestrial + subsea fibre; 400 GbE inter-AZ links
4. **Environmental Risk:** Careful avoidance of flooding, extreme weather, seismic zones
5. **AZ Isolation:** Each AZ has independent power, water, and cooling

### Cooling Innovation
- Free-air cooling when conditions allow (sensors monitor temp/humidity)
- Deactivates evaporative cooling in favourable conditions
- WUE: 0.19 L/kWh (industry best)

---

## 12. UPTIME INSTITUTE TIER STANDARDS

| Attribute | Tier I | Tier II | Tier III | Tier IV |
|-----------|--------|---------|----------|---------|
| **Availability** | 99.671% | 99.741% | 99.982% | 99.995% |
| **Annual Downtime** | 28.8 hours | 22 hours | 1.6 hours | 26.3 minutes |
| **Redundancy** | None (N) | N+1 components | N+1 distribution | 2N+1 (full 2N) |
| **Power Paths** | Single | Single | Multiple (one active) | Multiple (simultaneous) |
| **Cooling Paths** | Single | Single | Multiple | Multiple |
| **Concurrently Maintainable** | No | No | Yes | Yes |
| **Fault Tolerant** | No | No | No | Yes |
| **Maintenance Requires Shutdown** | Yes | Yes | No | No |
| **Construction Cost** | $5M-$25M | $5M-$25M | $50M-$250M | $500M+ |
| **Construction Timeline** | 6-12 months | 6-12 months | 12-18 months | 18-24+ months |

### Progressive Requirements
- Each tier incorporates all lower tier requirements
- Tier I: UPS + dedicated cooling + generator (basics)
- Tier II: Adds redundant capacity components
- Tier III: Adds redundant distribution paths (concurrently maintainable)
- Tier IV: Adds fault tolerance (independent, physically isolated systems)

---

## 13. KEY ENGINEERING CALCULATIONS & FORMULAS

### Power Calculations

**Total Facility Power:**
```
Total Power = IT Load / (1 - (1 - 1/PUE))
Or simply: Total Power = IT Load x PUE
```

**UPS Sizing:**
- Size for N+1 (Tier III) or 2N (Tier IV) redundancy
- 20-25% buffer above calculated load for derating and future expansion
- Typical UPS efficiency: 94-97% (double conversion)

**Generator Sizing:**
- Match to total UPS capacity + mechanical loads
- N+1 for Tier III, 2N+1 for Tier IV
- Auto-start within seconds of grid failure
- Fuel storage: typically 24-72 hours depending on tier

**Power Distribution Chain:**
```
Utility (HV) → Substation (MV: 11-33kV) → Transformer (LV: 400/415V)
→ Main Switchgear → UPS → STS → PDU → Rack PDU → IT Equipment
```

**Voltage Levels:**
- UK: 11kV/33kV/132kV → 400/415V → rack level
- US: 13.8kV → 480V → 120/208V
- PDU ratings: 50 kW to 500 kW

### Cooling Calculations

**Heat Load:**
```
Total Heat (BTU/hr) = IT Load (Watts) x 3.412
Tons of Cooling = BTU/hr / 12,000
```

**Quick Conversion:**
- 1 kW = 3,412 BTU/hr
- 1 ton of cooling = 3,517 W = 12,000 BTU/hr
- Rule of thumb: 1 ton of cooling per 3.5 kW of IT load

**UPS Heat Contribution:**
```
UPS Heat = (0.04 x Power System Rating) + (0.05 x Total IT Load)
```

**Power Distribution Heat:**
```
PDU Heat = (0.01 x Power System Rating) + (0.02 x Total IT Load)
```

**Lighting Heat:**
```
Lighting = 2.0 W/sq.ft or 21.53 W/sq.m
```

**Personnel Heat:**
```
Personnel = Max Occupants x 100W per person
```

**Total Cooling Required (with safety):**
```
Total Cooling = IT Load x 1.3 (30% safety margin)
Add 30% more if humidification is needed
Minimum N+1 redundancy on cooling units
```

### Efficiency Metrics

**PUE (Power Usage Effectiveness):**
```
PUE = Total Facility Energy / IT Equipment Energy
Ideal: 1.0 (impossible), Excellent: <1.2, Average: 1.5-1.8, Poor: >2.0
Google best: 1.06, Google fleet average: 1.09, Industry average: 1.56
```

**DCiE (Data Centre Infrastructure Efficiency):**
```
DCiE = 1 / PUE x 100%
```

**WUE (Water Usage Effectiveness):**
```
WUE = Annual Water Used (litres) / IT Equipment Energy (kWh)
Industry average: 1.8-1.9 L/kWh
Best in class (AWS): 0.19 L/kWh
Evaporative-only: up to 2.5 L/kWh
Air-cooled-only: 0 L/kWh (but higher PUE)
```

**CUE (Carbon Usage Effectiveness):**
```
CUE = Total CO2 Emissions (kgCO2) / IT Equipment Energy (kWh)
Grid-dependent: varies by country/region carbon intensity
```

### ASHRAE TC 9.9 Temperature/Humidity Envelopes

| Class | Temp Range (C) | Dew Point Range (C) | Max RH |
|-------|---------------|---------------------|--------|
| **Recommended** | 18-27 | -9 to 15 | 60% |
| **A1** (Enterprise) | 15-32 | -12 to 17 | 80% |
| **A2** (Volume servers) | 10-35 | -12 to 21 | 80% |
| **A3** (Extended) | 5-40 | -12 to 24 | 85% |
| **A4** (Maximum) | 5-45 | -12 to 24 | 90% |

---

## 14. POWER DENSITY BENCHMARKS

| Workload Type | kW/Rack | Cooling Method |
|---------------|---------|----------------|
| Traditional enterprise | 5-10 | Air cooling |
| Standard cloud | 10-15 | Air cooling |
| Enhanced cloud | 15-30 | Air / hybrid |
| High-density cloud | 30-40 | Hybrid (air + liquid) |
| AI inference | 30-60 | Direct liquid cooling |
| AI training | 60-120 | Direct liquid cooling |
| AI training (GB200) | 120-132 | Immersion / DLC |
| Next-gen AI (Blackwell Ultra) | Up to 250+ | Immersion cooling |
| Extreme (Rubin 576 GPU) | Up to 900 | Immersion cooling |

**Cooling Technology Limits:**
- Air cooling: practical limit ~25-35 kW/rack
- Direct-to-chip liquid: 50-120 kW/rack
- Immersion cooling: 120+ kW/rack, potentially unlimited
- Liquid cooling is 50-1,000x more efficient than air at heat transfer

---

## 15. FINANCIAL MODEL

### CAPEX Benchmarks (per MW of IT Load)
- Standard DC: $9-12M per MW
- AI-optimised DC: $15-20M+ per MW
- Tier III: $50M-$250M total
- Tier IV: $500M+ total

### OPEX Breakdown
- Maintenance: ~40% of OpEx
- Electricity: 15-25% of OpEx (location dependent)
- Annual electricity cost examples (100MW facility):
  - Cheap power ($0.047/kWh): ~$41M/year
  - Expensive power ($0.15/kWh): ~$131M/year

### Revenue Model
- Core metric: IT Load (kW), not square footage
- "Power is what drives revenue"
- Revenue = kW delivered x rate per kW x time

### Investment Returns
- 30MW DC at $10M/MW capex needs ~$100M/year revenue for 10% IRR
- Key metrics: IRR, NPV, equity multiple, yield-on-cost

### Construction Timeline
- Traditional build: 24-36 months
- Modular/prefab: 12-18 months
- Full lifecycle (land to operations) with permitting: 4-6 years
- Modular approaches: 60-80% standardised components

---

## 16. SITE SELECTION METHODOLOGY

### GIS/Geospatial Analysis Approach
1. **Multi-Criteria Decision Making (MCDM)** — Analytical Hierarchy Process (AHP) or Best-Worst Method
2. **Weighted Overlay Analysis** — Score sites against weighted criteria
3. **Random Forest / ML** — Identify and rank siting factor importance

### Weighted Criteria (from academic research, AHP)
| Factor | Weight | Data Source |
|--------|--------|-------------|
| Infrastructure & utilities | 0.14 | Grid capacity maps, substation data |
| Disaster avoidance | 0.13 | Flood zones, seismic data, wind risk |
| Telecom network availability | 0.13 | Fibre routes, IXP proximity |
| Power availability & cost | 0.12 | DNO data, grid connection queue |
| Climate (free cooling hours) | 0.10 | ERA5/weather data |
| Water availability | 0.10 | Water company data, aquifer maps |
| Land cost & availability | 0.08 | Land registry, planning zones |
| Renewable energy potential | 0.08 | Solar/wind resource maps |
| Labour market | 0.06 | ONS employment data |
| Tax incentives | 0.06 | Local authority data |

### Scoring Model
Three pillars: **Performance**, **Cost**, **Risk**

---

## 17. UK-SPECIFIC REQUIREMENTS

### Grid Connection
- <100MW: Apply to local DNO
- Merit-based queuing (replaced chronological)
- Must demonstrate: land rights (20+ year lease), planning status, engineering milestones
- Progression Commitment Fee: starts £2,500/MW, rises to £10,000/MW every 6 months
- Grid connection delays: 3-7 years in constrained areas

### Planning Permission
- Generally Schedule 2 under EIA Regulations
- NSIP regime available for large DCs (Secretary of State decision)
- Required assessments: noise, water consumption, drainage, biodiversity net gain
- AI Growth Zones: must prove water supply sufficiency

### Preferred UK Locations
- North of England emerging: Manchester, Leeds, Newcastle
- Lower land costs, less grid congestion than South East
- Growing fibre networks and regional IXPs
- Access to wind energy resources

---

## 18. BEHIND-THE-METER & ENERGY PROCUREMENT

### Behind-the-Meter (BTM) Co-Location
- Power generated on-site, bypassing grid
- Eliminates transmission costs and losses
- Mitigates grid congestion and interconnection delays
- FERC ordered PJM to reform tariff for co-located generation (Dec 2025)

### PPA Structures
- Developer ↔ Generator (multi-tenant colo)
- Tenant ↔ Generator (single/anchor hyperscaler)
- Google's "energy parks": DC + generation + BESS co-located

### Emerging Models
- Google acquired Intersect Power (~$5B) for co-located clean energy
- Distributed behind-the-meter power (natural gas, solar, BESS)
- Nuclear SMRs and fuel cells as future DC power sources

---

## 19. COOLING TECHNOLOGY COMPARISON

| Technology | kW/Rack Capacity | PUE Impact | WUE Impact | CAPEX | Maturity |
|------------|-----------------|------------|------------|-------|----------|
| Air (CRAC/CRAH) | Up to 25-35 | 1.4-2.0 | 0 (no water) | Low | Mature |
| Hot/cold aisle containment | Up to 35 | 1.2-1.5 | 0 | Low-Med | Mature |
| Evaporative (cooling tower) | Any | 1.1-1.3 | 1.5-2.5 L/kWh | Medium | Mature |
| Free air (economiser) | Any (climate dependent) | 1.05-1.2 | 0 | Medium | Mature |
| Direct liquid cooling (DLC) | 50-120 | 1.1-1.2 | Low | High | Growing |
| Rear-door heat exchangers | 30-60 | 1.15-1.3 | Low | Medium | Growing |
| Immersion (single phase) | 100-250+ | 1.02-1.1 | 0 | Very High | Emerging |
| Immersion (two phase) | 250+ | 1.02-1.1 | 0 | Very High | Emerging |

### Key Design Decisions
- Air cooling sufficient for <25 kW/rack (traditional enterprise)
- Hybrid (air + DLC) for 25-80 kW/rack
- Full liquid/immersion required for 80+ kW/rack
- Climate determines free cooling potential (UK: excellent — cool climate)
- Immersion reduces DC footprint by ~1/3 vs air-cooled

---

## 20. PRINCEPS DC MODULE — RECOMMENDED FEATURE SET

Based on competitive analysis, here's what would make Princeps' DC module superior:

### Phase 1: Site Feasibility (MVP)
1. **Multi-criteria site scoring** (we already have this pattern from site_prospector.py)
   - Power availability score (from grid_connection_analyser.py — already built)
   - Grid capacity & connection cost estimate (already built)
   - Fibre connectivity score (proximity to IXPs and fibre routes)
   - Climate score (free cooling hours from ERA5 — already built via GeeFlow)
   - Water availability score
   - Land suitability (terrain, flood risk, planning zones — already built via GeeFlow)
   - Renewable energy potential (solar/wind — already built via SAM)
   - Natural disaster risk (seismic, flood — can derive from GeeFlow)
   - Latency map to population centres
   - Behind-the-meter renewable potential

2. **Power demand modelling**
   - Input: number of racks, kW per rack, tier level
   - Calculate: total IT load, total facility load (using PUE), UPS sizing, generator sizing
   - Redundancy: N, N+1, 2N, 2N+1 configurations
   - Power chain topology diagram
   - Grid connection requirements & estimated cost

3. **Cooling requirements calculator**
   - From IT load → BTU → tons of cooling
   - ASHRAE compliance check (A1-A4)
   - Cooling technology recommendation based on density
   - Free cooling hours estimate from local climate data
   - Water consumption estimate (WUE)

4. **Financial model**
   - CAPEX estimate ($/MW based on tier and density)
   - OPEX estimate (electricity, maintenance, water, staff)
   - Revenue projection (kW x rate x utilisation)
   - IRR, NPV, payback period
   - Sensitivity analysis (electricity price, utilisation rate)

### Phase 2: Design & Planning
5. **Tier compliance checker**
   - Input design parameters → validate against Tier I-IV requirements
   - Redundancy validation (N, N+1, 2N, 2N+1)
   - Availability calculation
   - Gap analysis with remediation recommendations

6. **Power chain modeller**
   - Visual topology: utility → transformer → switchgear → UPS → STS → PDU → rack
   - Failure simulation (what happens if component X fails?)
   - Stranded power identification
   - Load balancing analysis

7. **Sustainability metrics dashboard**
   - PUE calculation and tracking
   - WUE calculation
   - CUE calculation (using UK grid carbon intensity + on-site renewables)
   - 24/7 CFE tracking (Google-style hourly matching)
   - Renewable energy fraction

8. **3D Rack visualisation** (extend existing deck.gl twin)
   - Rack layout on floor plan
   - Power density heat map
   - Temperature overlay (from simplified thermal model)
   - Capacity utilisation (space, power, cooling)

### Phase 3: Operations Intelligence
9. **AI-driven insights**
   - Stranded capacity identification (Sunbird-style)
   - Cooling optimisation recommendations
   - PUE improvement suggestions
   - Demand forecast integration (already built)

10. **Regulatory compliance** (UK)
    - EIA checklist generator
    - Noise assessment parameters
    - Water consumption assessment
    - Biodiversity net gain requirements
    - NSIP threshold check
    - Grid connection application preparation

### Architecture Approach
- Leverage existing Princeps infrastructure:
  - PostGIS for spatial analysis
  - GeeFlow for climate/terrain/land use
  - SAM for solar resource
  - Grid connection analyser for power availability
  - Demand forecaster for load projections
  - deck.gl for 3D visualisation
  - Claude for AI-driven analysis and recommendations
- New calculations module: `utils/dc_planning_engine.py`
- New frontend panel: `DCPlanningPanel.jsx`
- New API endpoints: `/api/dc/feasibility`, `/api/dc/design`, `/api/dc/financial`

---

## SOURCES

### Platform Research
- [Cadence Reality DC (6SigmaDCX)](https://www.futurefacilities.com/)
- [6SigmaRoom via Data Centre CFD](https://datacentercfd.com/6sigmadc/)
- [Cadence Reality DC Datasheet](https://www.cadence.com/en_US/home/resources/datasheets/datacenter-insight-platform-digital-twin-ds.html)
- [Nlyte DCIM Products](https://www.nlyte.com/products/)
- [Nlyte Energy Optimizer](https://www.nlyte.com/products/nlyte-energy-optimizer/)
- [Schneider Electric EcoStruxure IT](https://www.se.com/us/en/work/solutions/data-centers-and-networks/dcim-software/what-is-ecostruxure-it/)
- [Vertiv Trellis Thermal Manager](https://www.vertiv.com/en-us/products-catalog/monitoring-control-and-management/software/trellis-platform-thermal-manager-solution/)
- [OpenDCIM](https://opendcim.org/)
- [GitHub - OpenDCIM](https://github.com/opendcim/openDCIM)
- [Sunbird dcTrack](https://www.sunbirddcim.com/)
- [NetBox](https://github.com/netbox-community/netbox)
- [CoolSim Overview](https://www.coolsimsoftware.com/coolsim-overview/)

### Hyperscaler Approaches
- [Google Data Center Efficiency](https://datacenters.google/efficiency/)
- [Google Operating Sustainably](https://datacenters.google/operating-sustainably/)
- [Google 24x7 Carbon-Free Energy](https://sustainability.google/reports/24x7-carbon-free-energy-data-centers/)
- [DeepMind AI Cooling](https://deepmind.google/discover/blog/deepmind-ai-reduces-google-data-centre-cooling-bill-by-40/)
- [Microsoft Project Natick](https://news.microsoft.com/source/features/sustainability/project-natick-underwater-datacenter/)
- [AWS Global Infrastructure](https://aws.amazon.com/about-aws/global-infrastructure/)
- [AWS Data Centers](https://aws.amazon.com/compliance/data-center/data-centers/)

### Standards & Engineering
- [Uptime Institute Tier Classification](https://uptimeinstitute.com/tiers)
- [Data Center Tiers Explained (2026)](https://www.ingenious.build/blog-posts/data-center-tiers-explained)
- [ASHRAE TC 9.9 Guidelines](https://envigilance.com/compliance/ashrae-tc-9-9/)
- [DOE Best Practice Guide for DC Design](https://www.energy.gov/sites/default/files/2024-07/best-practice-guide-data-center-design_0.pdf)
- [DataSpan Cooling Calculations](https://dataspan.com/blog/how-to-calculate-cooling-requirements-for-a-data-center/)
- [Electrical Data Center Design 2025](https://gbc-engineers.com/news/electrical-data-center-design)

### Metrics & Efficiency
- [PUE, CUE, WUE Metrics Guide](https://ussignal.com/blog/pue-cue-and-wue-sustainable-data-center-metrics-guide/)
- [PUE White Paper (APC/Green Grid)](https://datacenters.lbl.gov/sites/default/files/WP49-PUE%20A%20Comprehensive%20Examination%20of%20the%20Metric_v6.pdf)
- [WUE Guidelines (Green Grid)](https://airatwork.com/wp-content/uploads/The-Green-Grid-White-Paper-35-WUE-Usage-Guidelines.pdf)

### Market & Financial
- [McKinsey: AI Power Demand](https://www.mckinsey.com/industries/technology-media-and-telecommunications/our-insights/ai-power-expanding-data-center-capacity-to-meet-growing-demand)
- [McKinsey: Scaling Data Centers](https://www.mckinsey.com/industries/private-capital/our-insights/scaling-bigger-faster-cheaper-data-centers-with-smarter-designs)
- [DC Construction Cost Index 2025-2026 (Turner & Townsend)](https://www.turnerandtownsend.com/insights/data-centre-construction-cost-index-2025-2026/)
- [JLL 2026 Global Data Center Outlook](https://www.jll.com/en-us/insights/market-outlook/data-center-outlook)
- [DC Economics (Thunder Said Energy)](https://thundersaidenergy.com/downloads/data-centers-the-economics/)

### Site Selection & GIS
- [ESRI Data Center Planning](https://www.esri.com/en-us/industries/technology/focus-areas/data-center-planning-site-selection-and-analysis)
- [CBRE UK DC Site Selection](https://www.cbre.co.uk/insights/articles/key-factors-to-consider-for-effective-data-centre-site-selection)
- [Geospatial DC Siting (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S221067072500561X)
- [Enverus DC Siting Guide](https://www.enverus.com/data-center-site-selection-criteria/)

### UK Regulatory
- [UK DC Planning Policy (House of Commons)](https://commonslibrary.parliament.uk/research-briefings/cbp-10315/)
- [UK Grid Connection Guide](https://www.brownejacobson.com/insights/securing-data-centre-power-steps-to-navigate-uk-grid-connection)
- [eSmart Networks DC Grid Connections](https://esmartnetworks.co.uk/data-centres/)
- [Behind-the-Meter Power (S&P Global)](https://www.spglobal.com/market-intelligence/en/news-insights/articles/2025/10/data-center-developers-turn-to-distributed-behind-the-meter-power-94174247)
- [FERC Co-Location Order](https://www.klgates.com/FERC-Orders-PJM-to-Reform-Tariff-for-Co-Located-Generation-and-Load-1-15-2026)
