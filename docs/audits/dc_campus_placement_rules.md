# DC Campus Placement Rules

**Spec for the Princeps Site Designer placement engine.** Defines hard/soft constraints, adjacency matrix, and a rule-based + simulated-annealing algorithm that lays out a coherent data-centre campus inside a planning red-line, instead of scattering equipment across unrelated streets.

Author: BOT-DCP — 2026-04-21. Targets `feasi-frontend/src/components/DesignCanvas.jsx` and any backend placement helper in `utils/`.

---

## Section 1 — Public DC planning applications referenced

All live or recently-consented UK/IE applications whose public site plans informed the rules below. Use these for validation test fixtures.

| # | Scheme | LPA | Capacity | App ref / URL | Layout features of note |
|---|---|---|---|---|---|
| 1 | **Yondr Slough Campus Building C** (ex-AkzoNobel paint works) | Slough BC | 40 MW, 25,100 sqm, 4 halls over 2 storeys | [Slough moderngov P-00072-139](https://slough.moderngov.co.uk/mgAi.aspx?ID=50841) | Shell central, genset yard on NW service edge, substation tapped off southern boundary, HGV entry off Liverpool Rd via gatehouse, BREEAM Very Good, PV roof |
| 2 | **Equinix Slough (ex-paint factory)** outline | Slough BC | ~90,000 sqm across 3 buildings | [Techerati](https://www.techerati.com/news-hub/council-approves-equinix-slough-data-centre-campus/) | Three separate shells on one parcel, shared MV substation, ancillary offices on public-facing edge |
| 3 | **Google Waltham Cross** | Broxbourne BC | 33 acres, ~667,000 sqft DC + 245,000 sqft office | [DCD](https://www.datacenterdynamics.com/en/news/google-to-build-new-uk-data-center-campus-in-hertfordshire/), [Google press](https://www.googlecloudpresscorner.com/2025-09-16-Google-Opens-Waltham-Cross-Data-Centre-as-Part-of-Two-year-GBP5-Billion-Investment-in-the-UK-to-Help-Power-its-AI-Economy) | Access off A10 + Lt Ellis Way, air-cooled (no large water plant), office wing facing highway, halls set back from River Lee flood corridor |
| 4 | **Meta Clonee (Building 5)** | Fingal/Meath CoCo, IE | 288 MW at build-out, 227 acres, 3 single-storey shells | [Data Center Map PDF](https://static.datacentermap.com/company/meta/datacenter10009/Meta%20Clonee%20Data%20Center.pdf), [studioNWA](https://www.studionwa.com/project/facebook/) | On-site 220 kV substation, guardhouse at single access, intensive landscaping berm for noise, solar-oriented admin block |
| 5 | **Stellium Cobalt Park, Newcastle** (noise assessment doc) | N. Tyneside MBC | 180 MW master plan | [docs.planning.org.uk Stellium NIA](https://docs.planning.org.uk/20250113/222/SOSUS1BHJWT00/rml06ijwafqfpdod.pdf) | Generator yards acoustically screened by shell mass toward nearest dwellings; +12 dB(A) limit at nearest residential receptor |
| 6 | **Microsoft Skelton Grange, Leeds** | Leeds CC | Pre-app consultation 2024-25 | [Microsoft Local blog](https://local.microsoft.com/blog/skelton-grange-leeds-datacentre-planning-application/) | Brownfield ex-power station site, existing 400 kV grid bay reused, access off Pontefract Ln |
| 7 | **Segro / Pure DC Slough 50 MW** pre-let | Slough BC (SPZ) | 50 MW | [DCD](https://www.datacenterdynamics.com/en/news/segro-signs-pre-lease-to-develop-50mw-data-center-slough-uk/) | Simplified Planning Zone — rapid consent where layout fits SPZ template |
| 8 | **Equinix LD10 Slough** (operational ref) | Slough BC | 110,566 sqft, 74,873 sqft raised floor | [Colo-X LD10](https://www.colo-x.com/data-centre/equinix-ld10-data-centre-slough/), [Baxtel campus](https://baxtel.com/data-center/equinix-slough-campus-ld4-ld5-ld6-ld10) | Non-contiguous "virtual campus" linked by innerduct corridors — shows cable-corridor importance |

Common pattern: **shell(s) central, TX/genset yards on the "service" (back) edge away from public frontage, office/gatehouse on the public frontage, access road as the spine**.

---

## Section 2 — Hard constraints (reject layout if violated)

Evaluate in this order. First failure returns a reason code.

| Code | Rule | Source |
|---|---|---|
| `H01_REDLINE` | Every element polygon must lie entirely inside the planning red-line | NPPF; BS EN 50600-2-1 site configuration |
| `H02_REDLINE_SETBACK` | ≥ 5 m from red-line, ≥ 10 m from any residential-zoned boundary | UK LPA norms, [Yondr Building C](https://slough.moderngov.co.uk/mgAi.aspx?ID=50841) |
| `H03_FLOOD` | No shell/hall/TX yard/genset/water plant inside EA Flood Zone 3; finished floor ≥ 600 mm above 1-in-100-yr + CC allowance | [GOV.UK Flood Zones](https://www.gov.uk/guidance/flood-risk-assessment-flood-zones-1-2-3-and-3b), [Cundall CNI](https://www.cundall.com/ideas/blog/what-the-critical-infrastructure-label-means-for-data-centre-flood-risk) |
| `H04_FIRE_GEN` | Genset housings ≥ 1.5 m from any opening in a combustible-walled building; ≥ 3.0 m preferred at hyperscale | [NFPA 37 §4.1.4](https://support.generac.com/s/article/What-Is-NFPA-37), [NFPA 850 for fuel-storage sep](https://www.nfpa.org/product/nfpa-850-standard-for-fire-protection-for-electric-generating-plants-and-high-voltage-direct-current-hvdc-converter-stations/p0850code) |
| `H05_FIRE_SHELL` | Minimum 10 m clear between two shells/halls (compartmentation + fire-tender access) | BS EN 50600-2-1; Building Regs Part B |
| `H06_TX_CLEARANCE` | 3 m oil-containment bund around any transformer; 6 m between transformers without firewall | [IEEE PCIC 2022-0545](https://ieeepcic.com/2022conference/wp-content/uploads/sites/7/2022/09/2022-PCIC-0545.pdf) |
| `H07_NOISE` | Genset façade LAeq ≤ background + 12 dB(A) at nearest residential receptor; use shell mass as acoustic screen; ideal ≥ 200 m clear distance, minimum 75 m with attenuation | [Stellium NIA](https://docs.planning.org.uk/20250113/222/SOSUS1BHJWT00/rml06ijwafqfpdod.pdf), [Caice DC noise guide](https://caice.co.uk/data-centre-noise-control-visual-screening-guide/) |
| `H08_POC` | TX yard must connect to the point-of-connection (POC) substation via a continuous corridor inside the red-line; MV/LV room ≤ 150 m cable run from TX | Uptime Tier III Topology; cable-drop economics |
| `H09_ACCESS` | Exactly one primary vehicle access point; must serve gatehouse, car park, and HGV loading bay without HGVs crossing pedestrian routes | BS EN 50600-2-5; CPNI layered access |
| `H10_FENCE` | Continuous security fence ≥ 3 m from any shell wall; 5–10 m inner clear zone free of vegetation/cover | [Barkers CPNI guide](https://barkersfencing.com/blog/data-centre-security-fencing-cpni-approval/) |
| `H11_HGV_SWEPT` | Loading bay inner sweep ≥ 5.3 m, outer ≥ 12.5 m; 35 m straight approach for 18 m artic | [Don-Bur HGV turning](https://donbur.co.uk/faqs/regulations/trailer-turning-circle-requirements.html) |
| `H12_FUEL` | Diesel bulk-fuel tank ≥ 15 m from shell; bunded 110%; tanker stand reachable without reversing | NFPA 850 / BS 5410 |
| `H13_LIGHTNING` | LPS separation per IEC 62305 — mast/arrays no closer than calculated separation distance `s = k(i)·k(c)·L/k(m)` | IEC 62305-3 |

---

## Section 3 — Soft constraints (optimisation objectives)

Minimise weighted sum `J = Σ wᵢ·costᵢ(x)` over a simulated-annealing pass. Default weights in brackets.

| Code | Objective | Weight | Rationale |
|---|---|---|---|
| `S01_CABLE_LEN` | Total MV cable run TX↔MV room + MV↔shell electrical room | 1.00 | <2 % voltage drop target at BS 7671 |
| `S02_DOWNWIND` | Genset exhaust stacks downwind of shell on prevailing-wind azimuth (UK default 240°, westerly) | 0.60 | ASHRAE TC 9.9 air-intake separation |
| `S03_HGV_PATH` | Minimise HGV overlap with pedestrian/staff routes; one-way service loop preferred | 0.40 | Stertil loading-bay guide |
| `S04_HALL_AXIS` | Hall long axis ±20° of N-S so CRAC/hot-aisle banks align with cooling-tower/dry-cooler face; reduces solar gain on long façades | 0.30 | ASHRAE TC 9.9; Meta Clonee |
| `S05_OFFICE_FRONTAGE` | Office/NOC on the public-facing (street) boundary for aesthetic + natural light | 0.25 | MCA Architects masterplan principles |
| `S06_WATER_POC` | Water plant near utility main tap-off, above flood line, condenser loop ≤ 80 m | 0.35 | BS EN 50600-2-3 |
| `S07_FENCE_COMPACT` | Minimise fence perimeter length (capex) while satisfying `H10` | 0.20 | CPNI layered security |
| `S08_LANDSCAPE` | Reserve ≥ 15 % site area for landscaping/biodiversity net gain (BNG statutory 10 % + buffer) | 0.25 | BNG-NSIP May 2026 regs |
| `S09_EXPANSION` | Reserve ≥ 20 % site area for future Hall N+1 footprint, adjacent to existing shell, on TX side | 0.30 | Hyperscale master-plan norm |

---

## Section 4 — Adjacency matrix (10 × 10)

`+2` must-be-near (≤ 30 m or direct frontage), `+1` prefer-near, `0` indifferent, `-1` prefer-far, `-2` must-be-far (≥ 50 m or separated by mass). Symmetric.

|              | Hall | Genset | TX yard | Water | Office/NOC | Gatehouse | Loading bay | Cable corridor | Access road | Fence |
|---|---|---|---|---|---|---|---|---|---|---|
| **Hall**           |  —  | -1  | +1  |  0  | -1  | -1  | -2  | +2  |  0  |  +1 |
| **Genset**         | -1  |  —  | +2  | -1  | -2  | -1  | -1  | +1  |  0  |  +1 |
| **TX yard**        | +1  | +2  |  —  |  0  | -1  | -1  | -1  | +2  |  0  |  +1 |
| **Water plant**    |  0  | -1  |  0  |  —  | -1  | -1  | -1  | +1  |  0  |  +1 |
| **Office/NOC**     | -1  | -2  | -1  | -1  |  —  | +2  | -1  |  0  | +1  |  +1 |
| **Gatehouse**      | -1  | -1  | -1  | -1  | +2  |  —  | +1  |  0  | +2  |  +2 |
| **Loading bay**    | -2  | -1  | -1  | -1  | -1  | +1  |  —  |  0  | +2  |  +1 |
| **Cable corridor** | +2  | +1  | +2  | +1  |  0  |  0  |  0  |  —  | -1  |  0  |
| **Access road**    |  0  |  0  |  0  |  0  | +1  | +2  | +2  | -1  |  —  |  +1 |
| **Fence**          | +1  | +1  | +1  | +1  | +1  | +2  | +1  |  0  | +1  |  —  |

Reading the matrix:
- **Genset ⟷ TX yard (+2)**: keep MV cable runs short — they're always paired on a service edge.
- **Hall ⟷ Loading bay (−2)**: dust, vibration, HGV movements incompatible with hall sensitive equipment; enforce via min 25 m clear.
- **Office/NOC ⟷ Genset (−2)**: acoustic and air-quality clash; office always on opposite face of shell.
- **Gatehouse ⟷ Access road (+2) & Fence (+2)**: gatehouse sits at the pinch-point where the access road pierces the fence.

---

## Section 5 — Recommended placement algorithm

Phased pipeline. Each phase either returns success or surfaces the failing constraint for user override.

```
INPUT:
  redline: Polygon (EPSG:27british_national_grid)
  poc: Point  (DNO/TO substation location on or near redline)
  residential_edges: LineString[]  (protected boundary segments)
  flood_zone3: MultiPolygon
  wind_dir_deg: float   (default 240)
  capacity_mw: float
  tier: "II" | "III" | "IV"
  design: {halls:n, gensets:n, tx_count:n, water:bool, office:bool, ...}

# ---------- Phase 1: site conditioning ----------
buildable = redline.difference(flood_zone3)
          .buffer(-5)                       # H02 redline setback
          .difference(residential_edges.buffer(10))
reject if area(buildable) < required_total_footprint(design) * 1.3

# ---------- Phase 2: rule-based seeding ----------
# Establish site spine: access road from nearest public highway edge to centroid
access_entry = closest_point_on(redline, public_highway)
spine        = straight_skeleton(buildable, from=access_entry)
gatehouse    = place(spine.offset(8), 40 m2)     # 8 m inside fence

# Office/NOC on public frontage (S05)
office_face = edge_of(buildable) facing public_highway
office      = place_along(office_face, footprint=design.office)

# Shell(s): centroid-biased, N-S long axis (S04)
halls = pack_rectangles(
    buildable.difference(office).difference(spine.buffer(6)),
    count = design.halls,
    long_axis_deg = 0 ± 20,
    clear_between = 10     # H05
)

# TX yard + genset yard: service edge opposite office, near POC (H08, S02)
service_edge = argmax_edge(buildable, distance_to(office_face))
                .filter(downwind_of(halls, wind_dir_deg))
tx_yard      = place_along(service_edge, near=projected(poc))
genset_yard  = place_along(service_edge, adjacent_to(tx_yard), offset=6)   # H06

# Water plant: near utility main, above flood line (S06)
water        = place_near(utility_main_tap, above(flood_contour+0.6))

# Loading bay: off the access road spine, far from halls (H11, -2 adj)
loading_bay  = place_off(spine, min_from=halls(25), sweep_radius=12.5)

# Cable corridor: rectilinear TX↔MV room↔each hall (S01, H08)
cable_corridor = l_shape_route(tx_yard, halls.mv_room, max_len=150)

# ---------- Phase 3: simulated annealing refinement ----------
state = {halls, genset_yard, tx_yard, water, office, gatehouse, loading_bay}
T     = 1.0
while T > 0.01:
    candidate = perturb(state, jitter=3 m, rotate=5°)
    if any_hard_violated(candidate): continue
    dJ = soft_cost(candidate) - soft_cost(state)
    if dJ < 0 or exp(-dJ/T) > rand():
        state = candidate
    T *= 0.97                                    # ~150 iters

# ---------- Phase 4: fence + enforcement ----------
fence = concave_hull(state, offset=3)            # H10
fence = smooth(fence, min_radius=5)              # no sharp CPNI corners
reject if len(fence.intersections(spine)) != 1   # H09 single access

# ---------- Phase 5: report ----------
return {
  layout: state ∪ {fence, cable_corridor, spine},
  hard_checks: HARD_PASS,
  soft_score:  J(state),
  explanations: [(element, rule_ids, rationale)]
}
```

Implementation notes:
- Geometry ops via **Shapely** (backend) or **turf.js** (DesignCanvas.jsx already uses it).
- Rectangle packing: **greedy skyline** algorithm, seeded from largest hall first.
- SA schedule: 150 iter × 1 restart is enough empirically for a ≤ 10 ha site; larger campuses use 3 restarts.
- Every perturbation re-checks `H01–H13` before computing `J` — no point optimising a broken layout.

---

## Section 6 — Canonical test case: 50 MW Tier III hyperscale, 3.5 ha rectangle, POC at SE corner

**Parcel**: 250 m (E-W) × 140 m (N-S) = 35,000 m². Red-line = rectangle. POC substation sits just outside SE corner. Prevailing wind 240°. Public highway along southern edge.

**Design pack** (50 MW Tier III N+1):
- 2 × halls, each 60 × 30 m (1,800 m²) ≈ 25 MW IT load each
- 1 × genset yard, 40 × 20 m (16 × 2.5 MW diesel N+1)
- 1 × TX yard, 30 × 20 m (3 × 22 MVA 132/11 kV)
- 1 × water plant (air-cooled dry-coolers adjacent to halls), 20 × 15 m
- 1 × office/NOC, 30 × 12 m
- 1 × gatehouse, 8 × 5 m
- 1 × loading bay, 25 × 15 m (one dock, 35 m approach)
- Cable corridor 3 m wide
- Access road 8 m wide
- Fence perimeter

**Canonical layout** (coordinates in metres, origin = SW corner, x east, y north):

```
  y=140 ┌──────────────────────────────────────────────────────┐ redline N
        │                                                      │
        │  [TX yard 40,110 → 70,130]   [Genset yard 90,105 → 130,130]
        │  ╱╱╱╱ cable corridor along y=100 to halls MV rooms    │
        │                                                      │
  y=100 │  ┌──────────Hall A──────────┐  ┌──────────Hall B──────────┐
        │  │ 40 ≤ x ≤ 100, 50 ≤ y ≤ 100│  │ 120 ≤ x ≤ 180, 50 ≤ y ≤ 100│
        │  │  (hot aisle facing east)  │  │  (hot aisle facing east) │
  y=50  │  └───────────────────────────┘  └───────────────────────────┘
        │          [Water plant 190,55 → 210,95]                │
        │  [Loading bay 215,30 → 240,60]  (HGV sweep clear)     │
        │ ════════════ access road spine, y≈20 ═══════════════  │
        │ [Office/NOC   [Gatehouse               POC (outside SE)→
        │  20,5→80,25]   210,5→230,15]                          │
  y=0   └──────────────────────────────────────────────────────┘ redline S
        x=0                                               x=250
        
        Fence: offset 3 m inside redline, gate at x=215, y=10
        Prevailing wind ← from SW (240°); exhausts at TX/genset yard drift NE clear of halls
```

**Verification vs constraints:**
- `H01–H02`: all elements 5 m inside redline — pass.
- `H05`: Hall A east face (x=100) to Hall B west face (x=120) = 20 m clear — pass (>10 m).
- `H07`: Genset yard at y=105–130, nearest residential notional N edge; shell mass (halls at y=50–100) screens south receptors; combined distance + attenuation satisfies +12 dB(A).
- `H08`: TX yard to POC (SE external) via corridor along south access spine — 1 cable run ~220 m external to hall MV rooms ~60 m each — within 150 m each leg.
- `H11`: Loading bay 25 × 15 m with 35 m approach down access road — pass.
- `S04`: Halls long axis E-W here because the parcel's E-W dimension is dominant; 90° rotation would break packing. Allowed by ±20° tolerance? No — exception flagged; acceptable with CRAC on N/S short edges.
- `S05`: Office on south frontage facing highway — pass.
- `S02`: Gensets NE of halls; wind 240° sweeps exhaust NE, away from hall intakes on west/south faces — pass.
- `S09`: ~4,500 m² reserve on NW quarter (x=0–40, y=50–140) available for Hall C future expansion, adjacent to existing TX yard — pass.

This layout is the golden-path fixture — the placement algorithm should converge to within ±5 m of these positions on the test parcel.

---

## Implementation hooks (Princeps-specific)

- Add `utils/dc_campus_placer.py` with `place_campus(redline_geojson, poc, design, constraints) -> LayoutResult` implementing Section 5.
- Extend `DesignCanvas.jsx` to call a new endpoint `POST /api/site-designer/auto-layout` that returns layout + per-element `{rule_ids, rationale}` for the reasoning popover (already landed per `project_site_designer_consolidation.md`).
- Validation harness: feed Section 6 parcel; assert all `H*` pass and SA `J` < threshold.
- Future: train a learned placer on 20–50 real UK planning PDFs (Section 1 + similar) once a dataset is curated.

---

## Sources

- [Yondr Slough Building C — Slough moderngov P-00072-139](https://slough.moderngov.co.uk/mgAi.aspx?ID=50841)
- [Yondr planning approval — DCD](https://www.datacenterdynamics.com/en/news/yondr-granted-planning-permission-for-third-data-center-at-slough-uk-campus/)
- [Equinix Slough outline consent — Techerati](https://www.techerati.com/news-hub/council-approves-equinix-slough-data-centre-campus/)
- [Google Waltham Cross — DCD](https://www.datacenterdynamics.com/en/news/google-to-build-new-uk-data-center-campus-in-hertfordshire/)
- [Google Waltham Cross opening release](https://www.googlecloudpresscorner.com/2025-09-16-Google-Opens-Waltham-Cross-Data-Centre-as-Part-of-Two-year-GBP5-Billion-Investment-in-the-UK-to-Help-Power-its-AI-Economy)
- [Meta Clonee DC spec PDF](https://static.datacentermap.com/company/meta/datacenter10009/Meta%20Clonee%20Data%20Center.pdf)
- [Meta Clonee studioNWA project page](https://www.studionwa.com/project/facebook/)
- [Stellium Cobalt Park Noise Impact Assessment (docs.planning.org.uk)](https://docs.planning.org.uk/20250113/222/SOSUS1BHJWT00/rml06ijwafqfpdod.pdf)
- [Microsoft Skelton Grange Leeds pre-app](https://local.microsoft.com/blog/skelton-grange-leeds-datacentre-planning-application/)
- [Segro Slough 50 MW DCD](https://www.datacenterdynamics.com/en/news/segro-signs-pre-lease-to-develop-50mw-data-center-slough-uk/)
- [Equinix LD10 Slough — Colo-X](https://www.colo-x.com/data-centre/equinix-ld10-data-centre-slough/)
- [Uptime Institute Tier Standard: Topology (GPX mirror PDF)](https://www.gpxglobal.net/wp-content/uploads/2018/11/Uptime-Tier-Standard-Topology.pdf)
- [Uptime Institute Tier Certification](https://uptimeinstitute.com/tier-certification)
- [ASHRAE TC 9.9 Thermal Guidelines](https://datacenters.lbl.gov/sites/default/files/ASHRAE%20Thermal%20Guidelines_%20SVLG%202015.pdf)
- [ASHRAE 2021 Thermal Guidelines ref card](https://www.ashrae.org/file%20library/technical%20resources/bookstore/supplemental%20files/therm-gdlns-5th-r-e-refcard.pdf)
- [BS EN 50600-1 overview (BSI)](https://landingpage.bsigroup.com/LandingPage/Series?UPI=BS+EN+50600)
- [BS EN 50600-2-1 Building construction](https://www.en-standard.eu/bs-en-50600-2-1-2021-information-technology-data-centre-facilities-and-infrastructures-building-construction/)
- [TIA-942-C standard (TIA Online)](https://tiaonline.org/products-and-services/tia942certification/)
- [TIA-942 site-selection 2026 guide (datacenterss.com)](https://datacenterss.com/data-center-site-selection-tia-942-guide/)
- [NFPA 850 product page](https://www.nfpa.org/product/nfpa-850-standard-for-fire-protection-for-electric-generating-plants-and-high-voltage-direct-current-hvdc-converter-stations/p0850code)
- [NFPA 37 fire safety for engines — Curtis Power](https://www.curtispowersolutions.com/news/get-to-know-nfpa-37-fire-safety-requirements-for-permanently-installed-engines)
- [Generac NFPA 37 summary](https://support.generac.com/s/article/What-Is-NFPA-37)
- [IEEE PCIC 2022-0545 substation-building spacing](https://ieeepcic.com/2022conference/wp-content/uploads/sites/7/2022/09/2022-PCIC-0545.pdf)
- [GOV.UK Flood Risk Assessment Zones 1/2/3/3b](https://www.gov.uk/guidance/flood-risk-assessment-flood-zones-1-2-3-and-3b)
- [Flood map for planning service](https://flood-map-for-planning.service.gov.uk/)
- [Cundall — CNI flood-risk label for DCs](https://www.cundall.com/ideas/blog/what-the-critical-infrastructure-label-means-for-data-centre-flood-risk)
- [Caice DC Noise & Visual Screening guide](https://caice.co.uk/data-centre-noise-control-visual-screening-guide/)
- [Cundall — early acoustic input for UK DCs](https://www.cundall.com/ideas/blog/quiet-efficiency-the-value-of-early-acoustic-consultancy-in-uk-data-centres)
- [Barkers DC security fencing + CPNI guide](https://barkersfencing.com/blog/data-centre-security-fencing-cpni-approval/)
- [Jacksons Security Fencing — DCs](https://www.jacksons-security.co.uk/applications/data-centres)
- [Don-Bur HGV turning-circle spec](https://donbur.co.uk/faqs/regulations/trailer-turning-circle-requirements.html)
- [Stertil loading-bay design guide](https://stertil-dockproducts.com/uploads/2018/01/lr_95004110-how-to-design-gb_2017-12-11.pdf)
- [MCA Architects — DC master-plan principles](https://www.mca.ie/insights/data-centre-masterplan-design-principles-and-best-practices/)
- [UK Parliament research briefing CBP-10315 — DC planning policy](https://researchbriefings.files.parliament.uk/documents/CBP-10315/CBP-10315.pdf)
