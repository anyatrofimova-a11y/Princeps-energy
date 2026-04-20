# Princeps Paperwork Rewrite Spec
**COUNCIL-1 audit, 2026-04-19.** Status: mandatory. Applies to every document/pack/PDF Princeps generates. Execution bots must follow this spec and the companion `industry_standards_index.md` verbatim.

---

## Executive summary

Current state of Princeps paperwork vs DNO / lender / LPA standard:

- **Regulatory currency is wrong.** G99 pack cites "Issue 2 (March 2025)" in some generators and "Issue 1 Amendment 9" in others; real current version is **ENA EREC G99 Issue 2, 10 March 2025** (storage-inclusive requirements mandatory from 1 March 2026). The `g99_compliance.py` module still references Am.9. `planning_summary` cites NPPF paras 152/154/158/186 — all deprecated numbering from the July 2021 / Dec 2023 editions; current NPPF Dec 2024 uses 162 / 165 / 168 for renewables.
- **No ENA G99 application-form field mapping.** `g99_pack_generator.py` invents a bespoke 7-section layout. Actual ENA G99 application is divided into Form A1 / A2 (Type A), Form B, Form C, Form D, plus Annex A (technical), Annex B (RfG compliance), Annex C (storage) and a protection commissioning schedule. No Princeps pack matches these.
- **OS Grid Reference is fabricated.** Two modules (`g99_pack_generator.py` line 169, `document_automation.py` line 29) return a manually-constructed OSGB string from a linear approximation — not a Helmert transformation. A DNO or LPA will reject this. Must use `pyproj` or existing `utils/grid_provenance.py` / an OSGB36 transform.
- **No provenance block on outputs.** Only `g99_brief.py` has a proper provenance block (`utils/grid_provenance.py`). The PDF packs do not print a Figure/Table numbering index, revision control block, author block, RICS-style reliance statement, or data-source table. Institutional reviewers reject this on first pass.
- **Placeholders leak to final doc.** `[Developer Name]`, `[Company number]`, `[Phone]` are printed into the HTML without strike-through styling or a "mandatory to complete" banner. Lenders/LPAs reject documents with visible square-bracket placeholders.
- **No map/plan figures meet planning submission standard.** Planning Portal 1APP validation checklists (sample: Cornwall, Westminster, Fenland) require an OS 1:1250 or 1:2500 site location plan with red-line boundary plus block plan at 1:200/1:500. Princeps emits matplotlib charts only; no georeferenced PDF plan with scale bar / north arrow / legend.
- **Lender pack (`lender_pack.py`, 167 lines) is a toy.** Does not meet LMA facility-agreement CP schedule, no MEL (Material Experts' List), no TDDR (Technical DD Report) structure per Mott MacDonald / DNV-GL standard. Only 8 sections, one cashflow table, no base-case/downside/breakeven model pack, no covenant certificate.
- **Financial Viability template conflates Red Book valuation with NPPF FVA.** `financial_viability_base.html` does not follow RICS Professional Statement "Financial Viability in Planning" 2nd ed. (2021) — missing the required viability-period assumptions, EUV+ uplift tests, developer profit benchmarks (15–20% on GDV / 20–25% on cost), Section 106 treatment, confidential vs open-book split.
- **BNG baseline uses the wrong tool.** `bng_calculator.py` and `document_automation.generate_bng_baseline` both target Biodiversity Metric 4.0. Natural England replaced it with the **Statutory Biodiversity Metric (v1.0, 29 Nov 2023)** which is the only tool accepted for Environment Act 2021 s.98 mandatory BNG since 12 Feb 2024.
- **No ES/EIA Scoping report.** `esa_auto_scoping.py` produces a JSON payload of survey cost benchmarks only; no EIA Regs 2017 Sched.4 compliant output, no "topics scoped in/out" matrix, no consultation record.
- **Playwright rendering is shared but styling is inconsistent.** Three different brand palettes (purple `#7c5cfc` in `document_automation`, gold `#D4A018` in `report_grid_connection`, gold `#F5B731` in `lender_pack`, teal `#007A8C` in `institutional_base.html`). Execution bots must consolidate onto the gold palette defined in `templates/report/institutional_base.html` + Gallatin-inspired spec from `project_ui_redesign_2026_04.md`.

**Top line:** packs are visually presentable but **none** would pass a first-round DNO, lender-tech-DD, or LPA validation check without remedial work. The G99 and Planning packs are the highest-leverage rewrites — those two cover 80% of developer-facing submissions.

---

## Per-pack rework briefs

### 1. Grid Connection Report / Assessment PDF

- **Files:** `utils/report_grid_connection.py` (731 lines), `templates/report/grid_connection_report.html` (1109 lines), endpoint in `app/routers/reports.py` (955 lines).
- **Current sections:** (1) Cover, (2) Executive Summary + KPIs, (3) Site Location, (4) Grid Infrastructure (candidate substations, best candidate), (5) Connection Cost Estimate (P10/P50/P90 + voltage options), (6) Queue Analysis (pressure LOW/MEDIUM/HIGH/CRITICAL, wait months heuristic), (7) Power Flow (Tier 2 — voltage & thermal, optional), (8) Recommendations, (9) Appendix (Table 101 reference, data sources, disclaimers).
- **Current quality rating: 2/5.** Good layout, but fails DNO/lender review because: (a) no DNO-specific field structure matching UKPN/NGED/SPEN/SSEN/NPg/ENWL Connection Offer templates; (b) "queue wait months" is heuristic (`queued×3` in `_estimated_wait_months`) — no citation of NESO CMP376/TMO4+ gate reality; (c) cost components hard-coded (`11kV £80k/km` etc.) — no CCCM v19 cross-ref; (d) no LTDS cross-ref; (e) no N-1 contingency table (just text line); (f) no single-line diagram (SLD) embedded (`utils/sld_generator.py` exists but is only used on G99 route); (g) no site plan; (h) no provenance block.
- **Industry references:** ENA EREC G99 Issue 2 (10 Mar 2025); Distribution Code v43 (2024); ENA Common Connection Charging Methodology v19 (2024); NESO Connections Reform TMO4+ Gate 2 (Apr 2025); each DNO's LTDS (Licence Condition 25); NESO SOF (2025).
- **Required sections, ordered:**
  1. Cover (with revision/rev-date block, author, reviewer, commercial-in-confidence mark).
  2. Reliance Statement (who may rely — analogous to Red Book reliance note).
  3. Executive Summary — verdict / POC / capacity / voltage / P50 cost / programme / residual risks.
  4. Project Description — applicant, site, technology, installed capacity, export profile (RfG classification).
  5. Regulatory Framework box — G99 Issue 2, CCCM v19, Distribution Code v43, DNO licence, ESQCR 2002.
  6. Network Context — DNO licence area, relevant LTDS edition and page ref, GSP group, transmission boundary.
  7. Point of Connection Analysis — candidate substations ranked with full UKPN/NGED/SPEN style fields: asset ID, primary voltage, secondary voltage, firm capacity, generation headroom, demand headroom, available fault level, existing queue, statutory voltage limits per P28/P29.
  8. Load / Generation Scenario Table — export profile, import profile, reactive capability, fault-level contribution, earthing.
  9. Cost Breakdown — CCCM v19 Schedule 1 categories: Sole Use, Shared Use, Reinforcement (Extended Asset), connection-boundary fees. Show P10/P50/P90 for each.
  10. Queue & Programme — ECR entries listed (not summarised), TMO4+ Gate 2 status, earliest viable energisation year (drawn from `utils/queue_depth.py`), expected offer validity window.
  11. Power Flow (Tier 2) — baseline + N-1 table per bus / per line, voltage deviations against P28 limits.
  12. Single Line Diagram — must embed `utils/sld_generator.py` output at A4 landscape.
  13. Protection & Compliance — G99 Issue 2 Annex A / Annex C (storage) settings, commissioning schedule template.
  14. Commercial Options — Firm, Non-firm/ANM, Flexible (CMZ), BESS co-location, curtailment % bands.
  15. Risks & Residual Issues — RAG matrix with mitigation.
  16. Next Steps — pre-application with DNO (£ reference, 45 working days), Stage 1 application, supply agreement.
  17. Appendix A — Data provenance (per `utils/grid_provenance.py`).
  18. Appendix B — Assumptions & Methodology.
  19. Appendix C — Glossary.
  20. Revision History.
- **Required data inputs and source:** `projects` (DB), `grid_substations` (DB), `grid_ecr` (DB), `grid_dno_boundaries` (DB), `grid_lines` (DB), `demand_scenarios` (DB), `utils/grid_connection_analyser.py` (Tier 1), `utils/grid_power_flow.py` (Tier 2), `utils/queue_depth.py`, `utils/connection_optimiser.py`, `utils/sld_generator.py`. Missing: LTDS page-ref extractor (need `utils/ltds_cim_ingester.py` to expose page citations), CCCM cost-category breakdown (currently collapsed into single `cable`/`switchgear`/`dno_fees`).
- **Required tables:** (a) Candidate substation table — columns: Rank, Name, Asset ID, Licence area, Voltage HV/LV, Firm capacity MVA, Gen headroom MW, Demand headroom MW, Fault level kA, Queued MW, ECR count, Distance km, Suitability (0–100), RAG. (b) Cost breakdown table — CCCM Schedule 1 line × P10 × P50 × P90 × Assumption source. (c) N-1 contingency table — Contingency name × min V p.u. × max V p.u. × max line loading % × Status. (d) Revision history table — Rev × Date × Author × Reviewer × Description.
- **Required charts/maps:** (1) A4 OS-based site location map with red-line boundary and candidate substation markers (1:25000 scale + 1:5000 inset); (2) lollipop candidate ranking (exists); (3) P10/P50/P90 voltage option bar chart (exists, extend with CCCM components); (4) Power-flow voltage & thermal panels (exist); (5) SLD from `sld_generator.py` at A4 landscape; (6) Cost waterfall (new) showing how Sole Use + Shared + Reinforcement sum to P50.
- **Regulatory citations to embed:** G99 Issue 2 §8 (protection), §5 (RfG compliance); Distribution Code DPC4 and DPC5; ESQCR 2002 regs 24–27; CCCM v19 Sched.1; each DNO's LTDS cite (Licence Condition 25); NESO Grid Code v6.24 CC.6.1; TMO4+ Gate 2 procedure (Ofgem decision Apr 2025).
- **Rework size:** **L** (3–5 bot-days). Bot assignment: **grid-pack-bot**.

### 2. G99 Application Pack

- **Files:** `utils/g99_pack_generator.py` (255 lines), `utils/g99_compliance.py` (1299 lines), `utils/g99_brief.py` (338 lines), `utils/g99_table_101.py` (366 lines), `utils/document_automation.py` (lines 129–328), plus legacy `utils/market_intelligence.py` `generate_g99_application` (dup).
- **Current sections (from `generate_g99_pack`):** (1) Applicant, (2) Site, (3) Generation, (4) Connection, (5) Cost estimate, (6) Compliance, (7) AI verdict. The `document_automation.generate_g99_application` version uses Part 1/2/3/4b labels — closer to the real form, still wrong.
- **Current quality rating: 2/5.** Fails because: (a) not mapped to the actual ENA G99 Issue 2 forms (there is no "Section 5 AI verdict" in ENA); (b) OS grid reference is a linear approximation, will be rejected; (c) three separate generator functions with drifted output; (d) purple `#7c5cfc` branding clashes with grid pack; (e) provenance missing; (f) no protection commissioning schedule (ENA requires it); (g) no Annex C storage block even though storage support is mandatory from 1 March 2026.
- **Industry references:** **ENA EREC G99 Issue 2 (10 March 2025)** primary; ENA G100 Issue 2 for Type A under type-test; ENA EREC P28 (voltage fluctuations); ESQCR 2002. The actual G99 form suite has: (i) Form A1 (Type A ≤16A/phase, ≤3.68 kW single-phase) — simplified notification; (ii) Form A2 (Type A >16A/phase, ≤1 MW); (iii) Form B (Type B, 1–10 MW, 11–20 kV); (iv) Form C (Type C, 10–50 MW, 20–110 kV); (v) Form D (Type D, >50 MW or >110 kV). Plus Annex A1 (RfG technical requirements), Annex A2 (protection settings), Annex C (storage-specific, mandatory from 1 Mar 2026), and a Compliance Report template.
- **Required sections (must match ENA form one-for-one):**
  1. Cover — project, version, revision, applicant, DNO recipient.
  2. Routing check — G99 vs G100; Type A/B/C/D per capacity and voltage; flowchart.
  3. **Form [A1|A2|B|C|D]** — exact field-for-field replica of ENA form, including DNO reference box, MPAN, applicant registered company, authorised signatory, AD (authorising director), CCCM opt-in/out, export limit scheme (ANM/hard relay), phase, power factor envelope, reactive capability Q+/Q-/P+/P-, fault ride-through, frequency response capability (mandatory/optional), LoM protection (RoCoF + vector shift), synthetic inertia (for storage per Issue 2).
  4. **Annex A1** — RfG technical requirements (EU 2016/631 aligned): frequency ranges, voltage ranges, reactive capability envelope (U/Q chart), fault-ride-through curve, active power control, SYNC/ROCOF, LFSM-O, LFSM-U, FSM.
  5. **Annex A2** — Protection settings per Table A.1 / A.2 (already in `g99_compliance.py` — just needs to render into the pack).
  6. **Annex C** (storage only, mandatory 1 Mar 2026) — charge/discharge profile, grid-forming vs grid-following declaration, black-start capability declaration.
  7. Inverter/BESS type-test certificate references — manufacturer, model, certificate number, issuing body.
  8. Single line diagram — from `utils/sld_generator.py`.
  9. Protection commissioning schedule — stage × setting × relay model × test date placeholder.
  10. Site plan — OS 1:2500 red-line boundary, POC and routing.
  11. Fault level contribution calculation.
  12. Earthing declaration (solid / impedance / combined).
  13. Data provenance + disclaimer + authorised-signatory block.
- **Required data inputs:** `utils/g99_compliance.py:check_g99_compliance` for category; `utils/g99_compliance.py:g99_protection_settings` for Annex A.2 values; `utils/g99_brief.py:_fault_level_contribution`; `grid_substations` for POC details; company/applicant from `projects.metadata` (currently placeholders). **Missing:** (a) real WGS84→OSGB36 via `pyproj` (must replace linear approx); (b) applicant company lookup from Companies House (`utils/companies_house.py` exists — wire it in); (c) inverter model library (new).
- **Required tables:** Protection schedule (per stage, setting, delay, relay); RfG compliance declaration matrix (requirement × compliance method × evidence); fault level contribution (by bus); commissioning test schedule.
- **Required charts/maps:** U/Q reactive capability chart; FRT curve; site plan 1:2500; SLD.
- **Regulatory citations:** G99 Issue 2 §2 (scope), §5 (RfG), §8 (protection), §9 (commissioning), Annex A, Annex C; Distribution Code DPC; ESQCR 2002; EU RfG 2016/631 (retained).
- **Rework size:** **L** (4–6 bot-days). Bot: **g99-bot**. Recommend consolidating the three duplicate `generate_g99_application` functions into one.

### 3. Planning Application Pack (TCPA / 1APP)

- **Files:** `utils/document_automation.py` lines 334–1180 (`generate_planning_summary`) — the longest generator; no dedicated template.
- **Current sections:** meta, site details, development proposal, planning route (LPA/NSIP), EIA screening, flood, ALC, heritage, ecology/BNG, access, community, fee. ~15 subsections in nested dict but **no field-for-field match to 1APP**.
- **Current quality rating: 2/5.** Fails because: (a) not structured to Planning Portal 1APP v6 field codes (the actual 1APP has numbered fields 1–40+ plus national/local mandatory supplements); (b) NPPF citations are wrong numbering (para 86(c)/87/161/173/186 — some of these are valid in Dec 2024, but 152/154/158 are **July 2021 numbering**); (c) no 1APP ownership certificates A/B/C/D, no Article 13 notice, no CIL Form 1; (d) no site location plan or block plan; (e) no design & access statement; (f) no planning statement structured per PPG; (g) the HTML is inline f-string, not a Jinja template.
- **Industry references:** NPPF Dec 2024 (paras 162/165/168 renewables; 174 climate); PPG Renewable and Low Carbon Energy (rolling); TCPA 1990; EIA Regs 2017 SI 2017/571; EN-1 (Jan 2024) and EN-3 (Jan 2024) — relevant for NSIP but also material for TCPA; 1APP v6 Planning Portal field codes; sample LPA checklists (Cornwall, Westminster, Fenland, Cornwall North Yorkshire, South Oxfordshire).
- **Required sections:**
  1. Form 1APP — 40 numbered fields from Planning Portal v6 exactly: (1) applicant, (2) agent, (3) site address, (4) pre-application advice, (5) description of proposal, (6) existing use, (7) materials, (8) pedestrian access, (9) vehicle access, (10) parking, (11) trees/hedges, (12) biodiversity, (13) foul sewage, (14) surface water, (15) existing use — contamination, (16) trade effluent, (17) residential units, (18) non-residential, (19) employment, (20) hours of opening, (21) industrial processes, (22) hazardous substances, (23)–(40) remaining.
  2. Certificates A/B/C/D (ownership), Article 13 notice, agricultural holdings certificate.
  3. Planning Statement — policy assessment section-by-section against: Local Plan policies (from LPA), NPPF Dec 2024, NPS EN-1 + EN-3, PPG Renewable.
  4. Design & Access Statement — character, layout, scale, landscaping, appearance, access.
  5. EIA Screening or Scoping Opinion request.
  6. Flood Risk Assessment (site ≥1 ha or Zone 2/3 required).
  7. Ecology: Preliminary Ecological Appraisal + Phase 1 Habitat Survey + Protected Species.
  8. Statutory Biodiversity Metric output (see BNG pack).
  9. Agricultural Land Classification statement (Grade + BMV material).
  10. Landscape & Visual Impact Assessment (LVIA per GLVIA 3rd ed.).
  11. Glint & Glare assessment (CAP 738 methodology).
  12. Heritage Impact Assessment.
  13. Noise Assessment (BS 4142:2014+A1:2019).
  14. Transport Statement / Assessment.
  15. Construction Environmental Management Plan (outline).
  16. Site Location Plan 1:2500 + Block Plan 1:500 + Elevations 1:200.
  17. CIL Additional Information form.
  18. Community consultation statement.
  19. Fee calculation statement.
- **Required data inputs:** `projects`, `geeflow_extractions` (land use, NDVI), `legacy_assets`, flood/ALC/AONB/SSSI from PostGIS spatial layers, LPA lookup from `utils/lpa_scraper.py`, heritage from Historic England API, `utils/buildable_area.py`, `utils/glint_glare.py`, `utils/environmental_constraints.py`. **Missing:** (a) 1APP field-code mapping (new dict); (b) LPA-specific local validation list ingester (currently only 3 LPAs in repo — need a scraper that fetches each LPA's checklist at runtime); (c) CIL liability calc; (d) Design & Access generator.
- **Required tables:** 1APP 40-field table; policy compliance matrix (policy × compliance × evidence); ownership certificate matrix; EIA scoping topic matrix (topic × in/out/uncertain × reason); fee calculation.
- **Required charts/maps:** Site location plan 1:2500 with red line (OS Mastermap basemap from `utils/hmlr_inspire_ingester.py`); block plan 1:500; elevations 1:200; indicative layout from `DesignCanvas.jsx` render export.
- **Regulatory citations:** NPPF Dec 2024 paras 162 (climate as material consideration), 165 (suitable areas identification), 168 (determination test — "significant weight" to benefits); EN-1 (Jan 2024) paras relevant; EN-3 (Jan 2024) Part 2 (solar) or Part 3 (wind); EIA Regs 2017 regs 5–6 (screening), reg 10 (scoping); TCPA 1990 s.62 (application requirements); Localism Act 2011 (CIL/neighbourhood planning).
- **Rework size:** **L** (5–7 bot-days). Bot: **planning-bot**.

### 4. NSIP / DCO Application Bundle

- **Files:** `utils/pins_nsip.py` (not yet read — but referenced), no dedicated generator.
- **Current sections:** None for DCO. Planning generator has a "nsip_pathway" branch that emits 2 lines of text.
- **Current quality rating: 1/5.** No DCO pack exists. This is a major gap for any project >50 MW or any DC opting in under s.35 PA 2008.
- **Industry references:** Planning Act 2008 c.29 (as amended by LURA 2023); Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009 (SI 2009/2264, amended 2024); PINS Advice Notes 1–18; Infrastructure Planning (EIA) Regulations 2017 (SI 2017/572 — NSIP version of EIA regs); EN-1 (Jan 2024); EN-3 (Jan 2024); EN-5 (Jan 2024).
- **Required sections:** Scoping Report → PEIR → ES → DCO draft + Explanatory Memorandum → Book of Reference → Funding Statement → Consultation Report → Statement of Reasons for Compulsory Acquisition → Design and Access Statement → Habitats Regulations Assessment → Flood Risk Assessment → Transport Assessment → Planning Statement → Land Plans, Works Plans, Access & Rights of Way Plans. Format must meet PINS submission checklist.
- **Required data inputs:** Same as planning pack PLUS CPO schedule data from `utils/land_registry.py` + `utils/landowner_lookup.py`, works plan from `DesignCanvas.jsx` GeoJSON export.
- **Tables:** Book of Reference (Part 1 category 1 land, Part 2 category 2, Part 3 category 3); Land Plans schedule; Works Plans schedule.
- **Regulatory citations:** Planning Act 2008 s.37, s.55, s.58, s.123 (CPO); Infrastructure Planning (Applications) Regs 2009 SI 2009/2264 regs 5–6; PINS AN7 (EIA), AN9 (env docs), AN17 (cumulative).
- **Rework size:** **L** (6–8 bot-days). Bot: **dco-bot**. Recommend deferring until a real NSIP project is in the pipeline; build scaffold only.

### 5. BNG Baseline & Statutory Metric Pack

- **Files:** `utils/bng_calculator.py` (464 lines), `utils/document_automation.py:generate_bng_baseline` (lines 1750–1985).
- **Current sections:** Site summary, habitat baseline (from DynamicWorld → UKHab mapping), baseline BU total, 10% net gain target, creation strategy, NDVI condition note.
- **Current quality rating: 2/5.** Fails because: (a) cites **Biodiversity Metric 4.0** — superseded by **Statutory Biodiversity Metric v1.0 (29 Nov 2023)** which is the only tool accepted under Environment Act 2021 s.98 from 12 Feb 2024; (b) no condition survey by competent ecologist declared; (c) no strategic significance multiplier derivation from local nature recovery strategy; (d) no off-site gain option, no statutory biodiversity credit fallback; (e) temporal/difficulty/spatial-risk multipliers hard-coded without ranges; (f) no 30-year habitat management plan template; (g) uses DynamicWorld satellite classification as baseline — defensible for pre-app only, LPA will require UKHab v2.0 field survey.
- **Industry references:** Environment Act 2021 s.98 + Schedule 14; **Statutory Biodiversity Metric v1.0** (29 Nov 2023); UKHab v2.0 (2023); Natural England "Understanding Biodiversity Net Gain" guidance (Feb 2024, May 2024 update); Small Sites Metric v1.0; for NSIP: separate Schedule 15 BNG regime expected May 2026.
- **Required sections:**
  1. Project & site — applicant, ref, area, map.
  2. Ecologist declaration — competent-person name, CIEEM membership, date of survey.
  3. Baseline habitat survey — UKHab v2.0 parcels with area, distinctiveness, condition (from field survey not NDVI), strategic significance.
  4. Baseline biodiversity unit calc — per parcel and totals (area × distinctiveness × condition × strategic).
  5. Proposed post-development layout with habitats.
  6. Habitat losses table.
  7. Habitat creation/enhancement table with temporal, difficulty, spatial-risk multipliers.
  8. Net change summary — absolute and percentage; check ≥10%.
  9. Trading rules compliance (like-for-like, like-for-better).
  10. Off-site units required (if on-site insufficient).
  11. Statutory biodiversity credit fallback cost.
  12. 30-year habitat management & monitoring plan outline.
  13. Legal mechanism — s.106 agreement or conservation covenant with responsible body.
  14. Metric spreadsheet (v1.0) cross-reference.
  15. Provenance + disclaimer — statutory metric must be run by a competent person for submission.
- **Required inputs:** `geeflow_extractions` (for pre-app baseline); `design_bom.py` + DesignCanvas export for post-dev layout. **Missing:** field-survey ingester (accept ecologist's UKHab export as CSV/XML), integration with Natural England Biodiversity Net Gain Register API.
- **Tables:** Parcel baseline (Habitat code × area × distinctiveness × condition × strategic × BU); post-dev habitats; net change; off-site units; credit fallback.
- **Charts/maps:** Habitat map pre- vs post-development; BU stacked bar pre vs post; 30-year unit accrual chart.
- **Citations:** Environment Act 2021 s.98, Sched.14; Statutory Biodiversity Metric v1.0 Technical Annex tables; UKHab v2.0; NE guidance Feb 2024; Biodiversity Gain Requirements (Exemptions) Regs 2024 SI 2024/141; Biodiversity Gain Site Register Regs 2024 SI 2024/45.
- **Rework size:** **M** (2–3 bot-days). Bot: **bng-bot**.

### 6. CDM F10 / Pre-Construction Information (PCI)

- **Files:** `utils/document_automation.py:generate_f10_notification` (lines 1442–1636).
- **Current sections:** Notification trigger, project, client, principal designer, principal contractor, dates, existing risks.
- **Current quality rating: 3/5.** Trigger logic correct. Fails because: (a) no separate PCI document (HSE L153 requires distinct PCI from F10); (b) risk register is 8 hard-coded items — real F10 has 30+ hazard categories expected; (c) no construction phase plan template; (d) no health and safety file template; (e) placeholder values inline.
- **Industry references:** CDM Regs 2015 (SI 2015/51); HSE L153 ACoP (2015); HSE F10 online form fields; HSE GS6 (overhead lines); HSE HSG47 (underground services); HSE HSG150 (H&S in construction).
- **Required sections — F10:** exactly the HSE online form fields: 1 Client, 2 Principal Designer, 3 Principal Contractor, 4 Project description, 5 Site address, 6 Local authority, 7 Start date, 8 Duration, 9 Max workers, 10 Planned contractors, 11 Person-days. + Supporting PCI document with 20+ sections per HSE L153 Appendix 3.
- **Required sections — PCI:** Project description; client brief; existing environment (topography, ecology, contamination, UXO, radon); adjacent land uses; existing services (overhead & underground); traffic; asbestos register; health hazards; welfare arrangements; permit-to-work regime; principal contractor's management arrangements; emergency procedures; boundary hoarding; fire plan.
- **Required inputs:** `projects`, `construction_schedule.py`, `construction_planner.py`, `construction_risk.py`. Missing: asbestos/UXO/radon survey ingester.
- **Tables:** Hazard register (hazard × likelihood × severity × control × residual); permit-to-work matrix; emergency contacts.
- **Citations:** CDM 2015 reg 6 (F10 trigger), reg 12 (PCI), reg 13 (construction phase plan); L153 Appendix 3; HSE F10 form; GS6; HSG47.
- **Rework size:** **M** (2 bot-days). Bot: **cdm-bot**.

### 7. Lender Pack / Due Diligence Pack

- **Files:** `utils/lender_pack.py` (167 lines), `app/routers/finance_extras.py` (lender pack endpoint), `app/routers/project_actions.py` (lender pack action), `utils/due_diligence.py` (412 lines).
- **Current sections:** Executive summary; site & technical; revenue stack; cashflow (15 years); covenants (4 lines); Monte Carlo tornado; technical DD (1 paragraph); commercial DD (1 paragraph); footer.
- **Current quality rating: 1/5.** Not lender-grade. Fails because: (a) not structured to LMA facility-agreement conditions-precedent (CP) or conditions-subsequent (CS) schedules; (b) no Material Experts' List (MEL); (c) no TDDR (Technical DD Report) structure per DNV-GL / Mott MacDonald / Wood / AFRY template; (d) no model audit trail; (e) 4 covenants listed without actual calculations (just text "PASS/REVIEW"); (f) no base-case / downside / breakeven / reverse stress test schedules; (g) no insurance schedule; (h) no tax and accounting note; (i) no P50/P90 yield attestation; (j) colour scheme deviates (gold `#F5B731` vs. canonical gold).
- **Industry references:** LMA Investment Grade Facility Agreement (English law, 2024 update); APLMA templates (2024); BVCA Investor Reporting Guidelines 2022; Invest Europe Professional Standards Handbook 2024; PRA SS3/19 (climate risk); typical lender-TDDR templates (DNV GL "Project Certification" scope).
- **Required sections (Lender Pack):**
  1. Cover + Reliance statement + Material Experts' List.
  2. Executive Summary — transaction overview, deal metrics, verdict.
  3. Project description — SPV, sponsor, technology, capacity, location, programme.
  4. Route to market — offtaker(s), PPA or merchant profile, CfD exposure, curtailment.
  5. Technical Due Diligence — resource assessment (P50/P75/P90 attestation), technology track record, BoP, civil works, grid connection, construction programme, OEM warranty, O&M strategy.
  6. Commercial Due Diligence — market power/energy price forecast, PPA terms, counterparty rating, BSUoS/TNUoS exposure, balancing mechanism revenue, ancillary services.
  7. Environmental & Social DD — EIA status, BNG status, planning conditions, community benefit, environmental liabilities.
  8. Legal DD — land tenure, easements/wayleaves, planning permission, grid connection agreement, PPA, EPC contract, O&M contract, SPV constitution, shareholder agreement.
  9. Tax & accounting — IFRS 16 lease, R&D claims, capital allowances, VAT.
  10. Insurance — construction all risks, operational, terrorism, cyber, BI schedule.
  11. Financial model — base case, downside, breakeven, reverse stress; sensitivity tornado; DSCR/LLCR/PLCR heatmap; Monte Carlo.
  12. Debt structure — tenor, drawdown, repayment profile, hedging, margin grid.
  13. Covenants schedule — financial covenants (DSCR ≥ 1.30× P50, DSCR ≥ 1.10× P10), operating covenants, information covenants.
  14. Conditions Precedent / Conditions Subsequent schedule (LMA structure).
  15. Risk matrix + mitigants.
  16. Recommendation + follow-up actions.
  17. Appendices: model audit, reliance letters, CVs of advisors, data-room index.
- **Required data inputs:** `utils/investment_appraisal.py` (DCF subprocess), `utils/scenario_engine.py`, `utils/due_diligence.py`, `utils/bankable_yield.py`, `utils/curtailment_estimator.py`, `utils/carbon_intensity.py`, `utils/balancing_mechanism.py`, `utils/energy_price_forecast.py`. Missing: insurance premium calibration, legal tenure ingester (Land Registry), SPV/corporate structure.
- **Tables:** Model sheet tables (base/downside/breakeven × 25 years × revenue/opex/debt service/equity); DSCR heatmap; sensitivity tornado; CP/CS schedule.
- **Charts/maps:** P50/P75/P90 yield fans; LLCR/DSCR curves; CAPEX waterfall; sensitivity tornado; Monte Carlo IRR histogram.
- **Citations:** LMA IGFA; PRA SS3/19; NESO SOF; DESNZ Contracts for Difference AR5/AR6 decisions; FCA Handbook CASS 7 (if relevant); IFRS 16.
- **Rework size:** **L** (6–8 bot-days). Bot: **lender-bot**. Recommend building on existing `utils/report_financial.py` (1060 lines — substantive) rather than the 167-line `lender_pack.py`.

### 8. Financial Viability (NPPF viability, RICS FVA)

- **Files:** `utils/report_financial.py` (1060 lines), `templates/report/financial_viability_base.html` (746 lines), `templates/report/financial.html` (201 lines).
- **Current sections (from template):** Brand header, KPI cards, CAPEX breakdown, OPEX breakdown, revenue, DCF, IRR/NPV/LCOE/payback, sensitivity.
- **Current quality rating: 2/5.** Confuses two different documents: (i) an investor financial-viability appraisal (DCF/IRR); and (ii) an NPPF Financial Viability Appraisal (FVA) for planning (EUV+, benchmark land value, developer profit). Neither is done to RICS standard. Fails because: (a) doesn't follow RICS Financial Viability in Planning Professional Statement 2nd ed. (2021); (b) no EUV+, no BLV benchmark, no residual land value; (c) no developer profit benchmark (15–20% GDV / 20–25% cost); (d) confidential-vs-open-book split not declared; (e) no PPG FVA methodology cross-ref.
- **Industry references:** RICS Financial Viability in Planning — Conduct and Reporting (2nd ed., 2021, effective 1 May 2021); RICS Valuation — Global Standards (Red Book, effective 31 Jan 2025); NPPF Dec 2024 Annex 2 (viability); PPG Viability (rolling); PPG Planning Obligations.
- **Required sections (NPPF FVA):**
  1. Appraiser declaration — RICS member, conflicts, conduct standards.
  2. Instructions & scope — what is being tested, planning stage (plan-making vs decision-taking).
  3. Methodology — residual appraisal with PPG assumptions.
  4. Existing Use Value (EUV) derivation.
  5. EUV+ / premium calibration.
  6. Benchmark Land Value (BLV) adoption.
  7. Gross Development Value (GDV) — revenue build-up, exit yields.
  8. Costs — build cost (BCIS indexed), professional fees, finance, contingency.
  9. Developer profit benchmark (15–20% GDV or 20–25% cost; justify).
  10. Residual Land Value result.
  11. Test — is the scheme viable? Is it viable with full policy compliance?
  12. Section 106 / CIL treatment.
  13. Sensitivity analysis — cost, GDV, yields, timing.
  14. Confidential vs open-book appendix split.
- **Required sections (investor DCF viability — keep as separate pack):** same as current plus P50/P75/P90 revenue bands, DSCR, LLCR, IRR, NPV, payback, LCOE, Monte Carlo.
- **Citations:** RICS FVP 2021 sections 2–5; RICS Red Book 2025 VPS 1, VPS 3, VPS 4; NPPF Dec 2024 Annex 2; PPG Viability (ID 10); PPG Planning Obligations (ID 23b).
- **Required inputs:** `utils/investment_appraisal.py`, BCIS rates, RICS comparable evidence (manual input). Missing: EUV database, comparable land value ingester.
- **Tables:** EUV × BLV × RLV × GDV; cost breakdown; sensitivity; phasing.
- **Rework size:** **M** (3 bot-days). Bot: **fva-bot**. Recommend splitting `report_financial.py` into two outputs: investor-pack (current) and NPPF-FVA (new).

### 9. Investment Committee (IC) Memo

- **Files:** `app/routers/project_actions.py:api_ic_memo` (line 425), `app/routers/investment.py:api_investment_memo` (line 159), `app/main_monolith.py` line 7768.
- **Current sections:** Unclear — routes to `utils/investment_appraisal.py` subprocess with command `investment_memo`; no HTML template dedicated.
- **Current quality rating: 2/5.** No dedicated template. Returns JSON.
- **Industry references:** BVCA Investor Reporting Guidelines 2022; Invest Europe Professional Standards Handbook 2024; typical energy-infra fund IC templates (Greencoat UK Wind, Foresight Solar Fund, JLEN — all publish IC-lite in annual reports).
- **Required sections:**
  1. Transaction summary — name, SPV, vendor, target date, deal size, sponsor thesis.
  2. Sources & uses.
  3. Investment thesis — why now, why us, value creation plan.
  4. Market context — IRR vs hurdle, comparables.
  5. Technical verdict — P50/P90, grid firmness, CAPEX certainty.
  6. Commercial verdict — PPA bankability, merchant exposure.
  7. Returns — IRR, multiple, yield, DSCR.
  8. Scenario grid — base, downside, upside, breakeven.
  9. Sensitivities — tornado + stress tests (energy price, availability, curtailment, CAPEX overrun).
  10. Exit strategy + exit multiple assumption.
  11. ESG + impact — carbon saved, BNG delivered, community benefit.
  12. Key risks + mitigants (top-10).
  13. Precedent deals — recent comparable transactions.
  14. Conditions precedent + timeline.
  15. Decision ask + voting result capture.
  16. Appendix — model pack, data-room index.
- **Required inputs:** Same as lender pack PLUS comparable deals from `utils/market_intelligence.py` and `utils/procurement_intelligence.py`. Missing: deal precedent database.
- **Tables:** Sources & uses; returns scenarios (IRR/multiple × base/down/up); sensitivity tornado; risk register; comparables.
- **Citations:** BVCA IRG 2022; Invest Europe 2024; NESO SOF 2025 (for market context).
- **Rework size:** **M** (3 bot-days). Bot: **ic-bot**. Template first, then orchestration.

### 10. Site Assessment Report (one-click / institutional)

- **Files:** `utils/one_click_report.py` (1228 lines), `utils/report_renderer.py` (1080 lines), `templates/report/institutional_base.html` (291 lines), `utils/report_generator.py` (344 lines), `utils/ml_report_section.py` (778 lines).
- **Current sections:** Cover, exec summary, location, solar yield (SAM), grid, environmental, financial, planning, satellite, ML viability, recommendations.
- **Current quality rating: 3/5.** Best of the current packs. Template is the closest to institutional standard. Fails because: (a) no RICS Red Book valuation conformance if being used for land-value purposes; (b) surveyor declaration missing; (c) data-source citations inline but not systematic; (d) no revision control block; (e) no ES Sched.4 topic coverage.
- **Industry references:** RICS Red Book Global 2025; RICS land valuation for energy projects (commentary); RICS Property Observer due-diligence checklists; IEMA ES guidelines 8th ed. 2024.
- **Required sections:** Cover + reliance statement; site description; planning context; ground conditions; services (water, gas, electricity); access & rights of way; environmental constraints; flood risk; BNG baseline summary; heritage; ecology; ALC; grid connection summary; technology options appraisal; indicative layout; yield assessment; financial summary; risk register; recommendations; declaration & surveyor details; appendices (data provenance, photographs, plans).
- **Required inputs:** everything currently aggregated plus Land Registry title info, Companies House beneficial ownership (if relevant), EA flood map PDFs.
- **Tables:** Site register; constraint register; risk matrix; data provenance; signature block.
- **Charts/maps:** OS 1:25000 location; constraint overlay map; solar resource; land use pie; radar; cashflow.
- **Citations:** RICS Red Book 2025; IEMA ES 2024; NPPF Dec 2024.
- **Rework size:** **M** (3 bot-days). Bot: **site-bot**.

### 11. EIA Screening / Scoping Opinion Request

- **Files:** `utils/document_automation.py:generate_eia_screening` (lines 1181–1441), `utils/esa_auto_scoping.py` (341 lines — survey cost benchmarks only).
- **Current sections (screening):** Project details, Schedule 2 assessment, sensitivity factors, likely significant effects checklist, screening opinion, site location, environmental context, next steps.
- **Current quality rating: 3/5.** Better than most. Fails because: (a) no separate Scoping Opinion request document; (b) no formal Schedule 4 topic matrix; (c) sensitivity scoring is additive without weighting (could be defensible but needs justification); (d) no IEMA-format effects register.
- **Industry references:** EIA Regs 2017 SI 2017/571; IEMA Guidelines for EIA 8th ed. 2024; IEMA Significance of Environmental Effects 2017; NPS EN-1 / EN-3.
- **Required sections (Screening):** Already mostly present — add (a) screening opinion request letter template addressed to LPA; (b) formal Schedule 3 selection criteria matrix (characteristics × location × type/characteristics of potential impact); (c) decision trail.
- **Required sections (Scoping):** New — project description, alternatives considered, topics proposed to scope in, topics proposed to scope out with justification, consultation record, proposed methodology per topic, structure of ES.
- **Citations:** EIA Regs 2017 reg 6 (screening), reg 15 (scoping), Sched.3, Sched.4; IEMA 8th ed. chapters 3 & 6.
- **Rework size:** **S** (1–2 bot-days). Bot: **eia-bot**.

### 12. Site Constraint / Planning Constraint Report

- **Files:** `utils/constraint_report_generator.py` (991 lines).
- **Current sections:** Site, environmental, flood, heritage, ALC, grid, planning risk (ML), shadow flicker, viewshed, recommendations.
- **Current quality rating: 3/5.** Good coverage. Fails because: (a) no citation of source dataset version/date; (b) no explicit "constraint triggers" table mapping each constraint to a consent requirement; (c) ML-predicted planning risk (from REPD XGBoost) passed through without uncertainty interval.
- **Industry references:** Natural England datasets; EA flood map; Historic England NHLE; DEFRA Magic; NPPF Dec 2024.
- **Required improvements:** Add data-source version table; add constraint→consent mapping table; add predicted outcome with confidence interval; add LPA-specific supplementary constraint list.
- **Rework size:** **S** (1 bot-day). Bot: **constraint-bot**.

### 13. DC Site Assessment Report

- **Files:** `utils/dc_report_generator.py` (1338 lines).
- **Current sections:** Executive summary, site overview, power analysis, CFE, cooling, connectivity, environmental, financial, regulatory, risk matrix, recommendation (11 sections per docstring).
- **Current quality rating: 3/5.** Specialised and well-structured. Fails because: (a) no reliance on s.35 PA 2008 DC NSIP opt-in (Infrastructure Planning (Business or Commercial Projects) (Amendment) Regs 2026); (b) no ISO 30134-2 / ISO 30134-9 (PUE/WUE) cross-ref; (c) no EU CSRD Art.12 DC reporting schema; (d) no explicit Uptime Institute tier classification.
- **Required improvements:** Add NSIP opt-in check; add ISO 30134 citation; add Uptime tier; add CSRD disclosure block; add fibre route plan.
- **Rework size:** **M** (2 bot-days). Bot: **dc-bot**.

### 14. Environmental Statement (ES) / PEIR

- **Files:** None. Not currently built.
- **Current quality rating: 0/5.** Does not exist.
- **Industry references:** EIA Regs 2017 Sched.4; IEMA 8th ed. 2024; NPS EN-1 / EN-3.
- **Required sections:** Non-Technical Summary; Introduction; Site and Project Description; Alternatives; Methodology; Per-topic chapters (Landscape & Visual; Cultural Heritage; Ecology & Nature Conservation; Water Environment; Ground Conditions; Air Quality; Noise & Vibration; Traffic & Transport; Socio-economic; Climate Change; Cumulative Effects; Interaction between effects); Residual Effects Summary; Commitments Register; Figures; Appendices (technical studies).
- **Rework size:** **L** (8–10 bot-days, scaffold only; full topic chapters need specialist input). Bot: **es-bot**. Defer full build until required by an active NSIP project.

---

## Cross-cutting items (every pack must adopt)

### a. Provenance block
Every pack must terminate with a provenance table (one row per data source). Columns: Data item · Source · Dataset version/date · Extraction date · Provenance class (SRC_DB_SNAPSHOT / SRC_API_LIVE / SRC_SYNTHETIC / SRC_USER_INPUT) · Stale days · Reason (if synthetic). Use `utils/grid_provenance.py` helpers (already implemented). Execution bots MUST wire every data point through `make_provenance()` and render via `combine_provenance()`.

### b. Branding
Consolidate to single palette. Use `templates/report/institutional_base.html` root variables:
- `--inst-navy: #1B365D` (body ink)
- `--inst-teal: #007A8C` (accent)
- `--inst-green / --inst-amber / --inst-red` (RAG)
- Gold `#D4A018` (Princeps accent — masthead, section headers)
Delete all other palettes. Remove purple `#7c5cfc` from `document_automation.py`, remove gold `#F5B731` from `lender_pack.py`.

### c. Figure & table numbering
Every figure: `Figure N. Title.` Every table: `Table N. Title.` Appendix items: `Figure A1.1`, `Table A1.1`. Add a List of Figures and List of Tables page after the Contents page for packs ≥20 pages. Jinja macros to auto-number.

### d. Appendix structure
Standard appendices in all packs (A–F minimum):
- Appendix A: Data Provenance.
- Appendix B: Methodology & Assumptions.
- Appendix C: Glossary & Abbreviations.
- Appendix D: Regulatory & Standards Register.
- Appendix E: Revision History.
- Appendix F: Reliance Statement.

### e. Revision control block
Table on page 2 of every pack:
| Rev | Date | Author | Reviewer | Approver | Description |
Revision identifier format: `P01` (pre-issue), `P02`... then `01`, `02` after formal issue.

### f. Reliance statement
Per RICS template: "This report is prepared for [Client] for [Purpose]. No third party may rely on this report without prior written consent from Princeps. Princeps accepts no liability to any third party for any matter arising from this report."

### g. Page geometry
All packs: A4 portrait (`@page { size: A4; margin: 18mm 15mm }`) unless a specific figure requires A4 landscape (SLD, Land Plans). Add running header (project/rev) and running footer (page N of M, confidentiality mark).

### h. File naming
`{ProjectName}-{PackType}-{Rev}-{ISO-date}.pdf`. PackType codes: GCR (grid-connection-report), G99 (g99-pack), PLA (planning-pack), DCO (dco-pack), BNG (bng-pack), CDM (cdm-pack), LND (lender-pack), FVA (fva-pack), ICM (ic-memo), SAR (site-assessment-report), EIA (eia-screening), ESR (environmental-statement), DCR (dc-report), CON (constraint-report).

### i. OS Grid Reference — mandatory fix
Replace the linear approximation in `utils/g99_pack_generator.py:169` and `utils/document_automation.py:29` with a proper OSGB36 conversion using `pyproj` (EPSG:4326 → EPSG:27700, then bng_from_en helper for the 6/8/10-figure reference). All packs must render true OSGB36 grid ref. (pyproj is already pinned in `.venv`.)

### j. Placeholder policy
Any remaining `[Developer Name]` style placeholder must be rendered in a red-underlined "⚠ required" style with a banner at the top of the page listing all unfilled fields. No packs with placeholders may be flagged "submission-ready".

### k. Regulatory register
Every pack must include a standards register table (Appendix D) listing each cited standard with its version/issue/date and URL — per `industry_standards_index.md`. Rewrite bots must pull from that index and never cite from memory.

---

## Rewrite dispatch plan

| Priority | Pack | Bot | Size | Dependencies |
|---------:|------|-----|-----:|--------------|
| 1 | Grid Connection Report | grid-pack-bot | L | `sld_generator`, `queue_depth`, `grid_provenance` |
| 2 | G99 Application Pack | g99-bot | L | Consolidate 3 dup functions; pyproj OSGB; Companies House ingester |
| 3 | Planning Application Pack | planning-bot | L | 1APP v6 field-code mapping; LPA checklist scraper |
| 4 | Lender Pack | lender-bot | L | Build on `report_financial.py` rather than `lender_pack.py` |
| 5 | Site Assessment Report (SAR) | site-bot | M | `institutional_base.html` already close |
| 6 | BNG Baseline | bng-bot | M | Update to Statutory Metric v1.0; accept UKHab v2 CSV |
| 7 | IC Memo | ic-bot | M | New template; deal precedent DB |
| 8 | Financial Viability (NPPF FVA) | fva-bot | M | Split from `report_financial.py` |
| 9 | DC Report | dc-bot | M | NSIP opt-in check; ISO 30134 cites |
| 10 | CDM F10 + PCI | cdm-bot | M | PCI new; hazard register expansion |
| 11 | EIA Screening + Scoping | eia-bot | S | Add Scoping opinion template |
| 12 | Constraint Report | constraint-bot | S | Data-source version table |
| 13 | NSIP/DCO scaffold | dco-bot | L (defer) | Only when NSIP project exists |
| 14 | Environmental Statement | es-bot | L (defer) | Only when NSIP project exists |

**Order:** tackle in the numbered order. Grid + G99 + Planning first because they cover 80% of developer submissions and are the entry point to the DNO/LPA relationship. Lender + IC next for institutional investor pipeline. DCO and ES defer until in-flight NSIP project justifies the cost.

**Total rework estimate:** roughly 45–55 bot-days (not counting deferred DCO/ES scaffolds which are ~15 bot-days on top).

**Cross-cutting work (provenance + branding + numbering + file naming + OSGB fix):** 3–4 bot-days, done before any individual pack rewrites so all packs inherit the same scaffold.

---

*End of spec. Rewrite bots: do not deviate without filing an amendment to this document.*
