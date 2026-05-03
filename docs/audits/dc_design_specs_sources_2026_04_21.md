# DC Design Specs — Source Audit (2026-04-21, BOT-REAL)

Every layout number the Princeps Site Designer legend renders now resolves
through `utils/dc_design_specs.py::compute_layout_specs()`. This audit lists
each real-anchor demo project → the planning / benchmark source that backs it
→ the confidence grade, so reviewers can click straight through to the public
record.

**Grades**

| Grade              | Meaning |
| ------------------ | ------- |
| `submission`       | Number transcribed from the applicant's own submitted drawings / application forms on the council portal. |
| `press`            | Number taken from trade press (DCD, Energy Storage News, Solar Power Portal, Insider Media) quoting the developer's official announcement — applicant drawings not publicly accessible or not yet transcribed. |
| `analogue`         | No project-specific submission; number scaled from a neighbouring submission that is in the same grid cluster. |
| `benchmark_only`   | No project-specific source at all. Full fallback to ASHRAE / Uptime / Cushman ratios. |

---

## 1. Slough Hyperscale DC

**Anchor:** REPD 4699 Slough Heat & Power Station (adjacent) + SEGRO pre-let on
Slough Trading Estate.

**Grade:** `press` (SEGRO pre-let publicly announced; applicant drawings under
SBC Simplified Planning Zone fast-track, not individually published).

| Field               | Source                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| Capacity 50 MW      | SEGRO pre-let March 2024 — DCD, Data Centre Magazine                    |
| Grid connection 50 MVA | SEGRO statement — 50 MVA contracted                                 |
| GFA 30,000 m² / 3 floors | SEGRO statement — press release                                     |
| Shell footprint ~10,000 m² | Derived from GFA ÷ 3 (press confirms 3 floors of halls + plant deck) |
| BREEAM Excellent    | SEGRO sustainability target                                             |
| Genset count        | Benchmark (not publicly disclosed)                                      |
| Transformer count   | Benchmark (not publicly disclosed — grid connection 50 MVA is)          |

**Primary URL:** <https://www.datacenterdynamics.com/en/news/segro-signs-pre-lease-to-develop-50mw-data-center-slough-uk/>
**Supporting URL:** <https://datacentremagazine.com/news/pure-data-centres-segro-west-london-data-centre-plans>

---

## 2. Thames BESS Phase 1

**Anchor:** Coryton GRID 132/33 kV (UKPN EPN S0000000D7027), Shell Haven /
London Gateway Thames-estuary cluster.

**Grade:** `analogue` — InterGen Gateway Energy Centre (Thurrock) DCO is in the
same grid cluster and provides public sizing numbers; our 50 MW project is
scaled proportionally.

| Field              | Source                                                             |
| ------------------ | ------------------------------------------------------------------ |
| Site area 1.8 ha   | Scaled from Gateway 320 MW / ~11 ha → 50 MW / 1.8 ha               |
| Duration 2 h       | Gateway initial 640 MWh / 320 MW convention                        |
| PCS count ~25      | Benchmark (Pembroke ratio of 1 PCS per 2 MW)                       |
| All other fields   | Benchmark                                                           |

**Primary URL:** <https://dwd-ltd.co.uk/experiences/gateway-energy-battery-storage-thurrock/>
**Supporting URL:** <https://www.energy-storage.news/uks-largest-battery-storage-project-at-640mwh-gets-go-ahead-from-government/>
**Statera DCO URL:** <https://thurrockflexgen.co.uk/>

---

## 3. Pembroke Solar (REPD 14913)

**Anchor:** REPD 14913 Pembroke Power Station BESS 350 MW (RWE Generation UK
plc — delegated approval January 2024, Pembrokeshire County Council).

**Grade:** `submission` — container / PCS counts transcribed directly from the
publicly-reported application. Site area is from the submission.

| Field                     | Source                                           |
| ------------------------- | ------------------------------------------------ |
| Site area 5.1 ha          | RWE submission                                   |
| Battery container count 212 | RWE submission                                 |
| PCS count 106             | RWE submission                                   |
| Duration 2 h              | Derived from 350 MW / 700 MWh class deployment   |
| All other fields          | Benchmark                                        |

**Primary URL:** <https://www.solarpowerportal.co.uk/battery-storage/rwe-reaches-final-investment-decision-on-350mw-welsh-battery-energy-storage>
**Supporting URL:** <https://www.energy-storage.news/rwe-opens-community-consultation-on-350mw-battery-storage-project-in-wales-uk/>
**Insider Media:** <https://www.insidermedia.com/news/wales/pembroke-battery-energy-storage-facility-progressing>

---

## 4. Spalding Solar (REPD 10173)

**Anchor:** REPD 10173 InterGen Spalding Energy Park 550 MW BESS (Approved
2023).

**Grade:** `press` — headline capacity and energy (550 MW / 1,100 MWh) publicly
confirmed; detailed transformer / genset count on InterGen's planning portal
not transcribed in this sweep.

| Field               | Source                                                              |
| ------------------- | ------------------------------------------------------------------- |
| Capacity 550 MW     | InterGen + South Holland DC planning                                |
| Energy 1,100 MWh    | Tesla Megapack tracker project 604 + InterGen disclosures           |
| Duration ~2 h       | Derived (1,100 ÷ 550)                                               |
| Grid substation     | Spalding North 132/33 kV                                            |
| All other fields    | Benchmark                                                           |

**Primary URL:** <https://www.intergen.com/our-assets/spalding-expansion-planning-documents/>
**Megapack tracker:** <https://lorenz-g.github.io/tesla-megapack-tracker/projects/604.html>

---

## 5. Hinkley Extension, Didcot BESS, Uttoxeter BESS, Norfolk Wind+BESS, Cambourne Solar

**Grade:** `benchmark_only`.

No project-specific planning submission transcribed in this sweep. Each
project is anchored to a real grid substation (Hinkley Point A 275 kV,
Didcot 132 kV, Uttoxeter 132 kV, North Norfolk Business Centre REPD 10497,
Camborne 132 kV) and layout numbers fall through to the benchmark ratios in
`BENCHMARK_RATIOS`. Legend renders the amber "benchmark" pill.

**Follow-up for future sweeps:**
- Parkway BESS Didcot / Sutton Courtenay 300 MW — submission likely available through South Oxfordshire DC planning portal.
- Uttoxeter has a known East Staffordshire BESS cluster (multiple REPD entries worth crosschecking).

---

## Benchmark citations (fallback ratios)

`utils/dc_design_specs.py::BENCHMARK_RATIOS` is the single source of truth for
the fallback math. Key citations:

- **Shell 615 m² / MW IT** — Cushman & Wakefield UK & Ireland DC Market H1 2025;
  Uptime Institute Global DC Survey 2024.
- **IT white space 440 m² / MW** — ASHRAE TC 9.9 (rack density 8 kW, aisle
  ratios per 2021 5th-ed Equipment Thermal Guidelines).
- **MV/LV 60 m² / MVA** — BS EN 61439 switchroom layout + UPS gallery
  benchmark.
- **5 MW genset container** — Caterpillar C175-20 / Rolls-Royce MTU 20V4000
  class (the two standard hyperscale SKUs).
- **50 m genset hazard buffer** — BS 5839 / NFPA 37 diesel storage separation.
- **20 MVA transformer + 8 m firewall** — BS EN 61936-1 oil-filled
  transformer fire separation.
- **Cooling plant 35-65 m² / MW by topology** — ASHRAE TC 9.9 Liquid Cooling
  Guidelines 2024; Uptime 2024 cooling mode categories.
- **Office 2-storey 448 m²** — BCO (British Council for Offices) + BS 8300
  compliant NOC floor plate.
- **Gatehouse 72 m²** — CPNI / Secured by Design guidance, guard + ANPR +
  search booth standard footprint.
- **Loading bay 20 × 14 m** — DfT Manual for Streets 2007 HGV turning
  standard.

---

## Consumption surface

| Consumer                                     | Endpoint / call                                           |
| -------------------------------------------- | --------------------------------------------------------- |
| Site Designer legend (DCDesignTwin.jsx ~l1075) | `GET /api/design/layout-specs?project_id=…` (fetch hook) |
| Chat tool `full_project_doc`                 | Upstream `full_project_doc` can call `compute_layout_specs()` directly |
| PDF reports (grid_connection, financial)    | Jinja templates can call helper directly via utils import |
| Agent intent = grid_study / dc_design        | `app.routers.agent_ops` — next sweep                      |

## File-level citations

- `utils/dc_design_specs.py:1-466` — new module (spec dict + benchmark ratios + compute_layout_specs + layout_legend_rows).
- `app/routers/design.py:1383-1424` — new `GET /api/design/layout-specs` endpoint.
- `feasi-frontend/src/components/DCDesignTwin.jsx:216-222` — new `projectId`/`projectName` props.
- `feasi-frontend/src/components/DCDesignTwin.jsx:255-273` — `layoutSpecs` fetch hook.
- `feasi-frontend/src/components/DCDesignTwin.jsx:1248-1297` — Swatch with source pill + tooltip.
- `feasi-frontend/src/components/DCDesignTwin.jsx:1020-1150` — legend rewired to consume `layoutSpecs.legend_rows` with local synthetic fallback.
- `migrations/2026_04_21_project_real_anchors.sql` — real anchor projects (reference for REAL_DC_SPECS keys).

## Open follow-ups

1. Wire `projectId` / `projectName` from `DataCentreTwin.jsx:1804` (currently `null`) and `DesignPage.jsx` to `<DCDesignTwin>` so the Slough demo actually receives its real-anchor name.
2. Transcribe InterGen Spalding submission drawings once accessible.
3. Backfill Parkway BESS (Didcot) from South Oxfordshire DC portal.
4. Add `GET /api/design/layout-specs/sources` that returns the full `REAL_DC_SPECS` dict for admin / QA inspection.
