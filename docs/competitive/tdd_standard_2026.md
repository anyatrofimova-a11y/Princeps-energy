# 2026 Lender Technical Due Diligence (TDD) Standard — UK Energy Infrastructure

**Target:** Reference spec for a lender-technical-adviser-grade TDD that a debt-side IC could rely on, covering 50 MW solar, 100 MWh BESS, and 50 MW data-centre transactions. Benchmarked against Ramboll / AFRY / Buro Happold / RSK / Arup / DNV / Fichtner / TÜV Rheinland public scopes.

Date: 2026-04-19. Prepared for Princeps gap analysis against `utils/`.

---

## 1. Canonical TDD Structure (Lender TA Grade)

A Tier-1 lender TDD for a UK renewable / flexible-generation asset runs **70–140 pages + appendices**. The adviser signs it as an "Independent Engineer" (IE) report; the lender's facility agreement references it directly. Typical structure and target pages:

| Section | Solar 50MW | BESS 100MWh | DC 50MW |
|---|---|---|---|
| 0. Executive summary + red/amber/green traffic lights | 4 | 4 | 5 |
| 1. Transaction & scope statement, reliance wording | 2 | 2 | 2 |
| 2. Project description, SPV structure, contract map | 5 | 5 | 6 |
| 3. Site & planning review (EIA, BNG, JR window, s.106) | 8 | 6 | 10 |
| 4. Resource assessment / load profile (P50/P75/P90) | 12 | n/a | n/a |
| 5. Market & revenue review (PPA, CfD, BM, wholesale, DC-CfE) | 6 | 10 | 6 |
| 6. Technology review (modules, inverters, BESS chemistry, chiller plant) | 8 | 12 | 12 |
| 7. Electrical design: SLD, protection coordination, fault level, reactive | 10 | 10 | 10 |
| 8. Grid connection: G99 Issue 2, CCCM charge, connection CP list | 8 | 8 | 8 |
| 9. Civils, CDM-2015 register, SUDS, ground conditions | 6 | 6 | 10 |
| 10. Construction plan & schedule, EPC review, LDs, PCG | 6 | 6 | 8 |
| 11. O&M & asset management, warranty matrix, spares | 6 | 8 | 8 |
| 12. HSE, fire safety (PAS 63100 / FM 5-33), UL 9540A | 4 | 10 | 8 |
| 13. Environmental: noise (BS 4142), glint/glare, water, air | 5 | 4 | 8 |
| 14. Financial model audit (LCOE, DSCR, degradation sculpt) | 6 | 6 | 6 |
| 15. Risk register + sensitivities + lender CPs | 4 | 4 | 4 |
| Appendices: SLD, layout, calc sheets, warranties, permits | 30+ | 30+ | 40+ |

**Reliance:** TDD is typically addressed to a named bank syndicate with liability cap = fee × 3, assignable once. This is a legal gate — Princeps output must be marked "advisory only, no reliance" until a chartered engineer (CEng) signs.

---

## 2. 2026 Regulatory Sweep — What a 2023 Template Misses

A 2023 TDD template is **materially stale** on 10+ points as of April 2026:

| Change | Date live | Impact |
|---|---|---|
| **EN-1, EN-3, EN-5 2025** — designated 13 Nov 2025, in force 6 Jan 2026 | Q1 2026 | NPS now explicitly covers BESS + solar resilience; flood design standard tightened; DCO cases must cite 2025 EN-3 |
| **G99 Issue 2** (ENA, 10 March 2025) | Live | New Type A-D thresholds, stricter FRT and reactive capability; offshore modules carved out; re-witnessing rules; mobile-gen exclusion |
| **BS 7671:2018 Amd 4 (2026)** publication 15 Apr 2026, prior withdrawn 15 Oct 2026 | Transition window | New **Chapter 57** on stationary secondary batteries; lithium thermal-runaway mitigation; loft/escape-route prohibition; PAS 63100 tie-in |
| **PAS 63100:2024** | Live | Domestic + light-commercial BESS fire protection — cited by Amd 4 |
| **IEC 62933-2-1 + TS 62933-2-2** (latest) | Live | Safety and performance testing for grid BESS — now standard TDD cite |
| **UL 9540A** cell/module/unit levels | Live | Lenders reject single-level cell tests; must be **all three levels** with CFD extrapolation |
| **FM Global DS 5-33** (DC fire/electrical) | Live | Now explicitly referenced in insurer-led DC TDDs alongside NFPA 855 |
| **BNG mandatory** for NSIPs from **May 2026** | Imminent | NSIP solar/BESS applications lodged after May 2026 must show 10% uplift + 30-yr maintenance; critical CP for lenders |
| **CCCM / Access SCR / Queue reform (Gate 2)** | Live since mid-2025 | Connection charging and queue position changed; legacy offers may be void or re-scoped. REMA reformed national market structure |
| **AR7 CfD** open Jan 2026 | Live | Revenue-stack assumption changed for solar |
| **NSIP threshold** for solar raised to 100 MW (Infrastructure Act 2024 amendments) | Live | 50 MW sites now go to LPA — shorter JR window (6 weeks s.288 vs NSIP process) |

Any 2023 TDD boilerplate that cites "EN-1 2011", "G99 Issue 1", "BS 7671 Amd 2 (2022)" is now flagged as stale and must be updated before lender signoff.

---

## 3. Engineering Calculation Matrix (What Must Be Quantified)

For each asset class, the lender TA is expected to either perform or independently verify the following calculations. "Lender-grade" means method, inputs, sensitivity and uncertainty documented.

### Solar 50 MW

| Calc | Tool standard | Sophistication expected |
|---|---|---|
| P50 / P75 / P90 / P99 yield | PVsyst v8 or equiv, 10 yr+ satellite + ≥1 yr ground | Uncertainty decomposition by source (resource, model, soiling, availability), output in MWh/yr with 1-sigma band |
| Capacity factor | From yield / nameplate | UK central England ~10.5–11.5% realistic |
| Degradation curve | Module datasheet + IEC 61215 + adjusted for field data | 0.5%/yr typical; first-year 2% stepped |
| LCOE build-up | £/MWh, real, pre- and post-tax | Decomposed: CAPEX, OPEX, DSRA, debt cost, degradation, resid |
| DSCR timeline | Sculpted against P90 | Min ≥1.30, avg ≥1.40 |
| Fault level @ POC | IEC 60909 | 3-phase, line-to-ground, sub-transient; compare to switchgear rating |
| Protection coordination | IEEE C37.112 TCC curves | Inverter trip, SEL relay, DNO back-up grading |
| Voltage regulation | Load-flow (pandapower / DIgSILENT) | ±6% at 11/33kV, ±5% at 66kV+ per Eng Rec P28/P29 |
| Glint / glare | FAA SGHAT or equivalent | All receptors; runway-approach exclusion |
| Noise | BS 4142:2014+A1:2019 | Rating level vs background, inverter cabinet source data |

### BESS 100 MWh

| Calc | Standard | Sophistication |
|---|---|---|
| Capacity retention curve + augmentation schedule | IEC 62933-2-1, manufacturer cyc data + field | Annual SoH% trajectory, augmentation CAPEX in yr 5 / 8 / 12 |
| Round-trip efficiency vs cycling + temperature | IEC TS 62933-2-2 | ≥85% AC-AC at BoL, SoH corrected |
| Thermal runaway propagation (CFD or UL 9540A extrapolation) | UL 9540A cell+module+unit + NFPA 855 | Deflagration vent sizing, 10 ft setback, water-spray / clean-agent spec |
| Revenue stack | BMRS + EPEX + DC/FFR + capacity market | Hourly dispatch w/ warranty cycling limits; curtailment haircut |
| Fault level + fault ride-through | G99 Issue 2 Table 10.1 | FRT curve, RoCoF 1 Hz/s withstand |
| Augmentation NPV | DCF over 15–20 yr | Compare augment-at-80% vs replace-at-end |

### Data Centre 50 MW

| Calc | Standard | Sophistication |
|---|---|---|
| PUE (design + predicted annual) | ASHRAE 90.4, EN 50600, Open Compute OCP PUE R1 | Target ≤1.25 design, ≤1.35 realised |
| WUE (L/kWh), including indirect | The Green Grid WUE | Report direct + embodied |
| Cooling redundancy + N+1 hold-up | Uptime Institute Tier III/IV | CFD for hot-aisle 30°C failure scenario |
| Electrical redundancy | IEC 62040 (UPS), IEC 61439 (switchgear) | 2N UPS, N+1 DRUPS / gensets, fault-current study |
| Heat rejection (dry cooler / adiabatic / liquid) thermodynamics | ASHRAE Thermal Guidelines TC 9.9 | psychrometric balance, drift loss, water plan under drought |
| Connection capacity modelling | G99 + CCCM v-current | Load flow + contingency |
| Carbon-free energy (24/7 CFE) | Google/IEA 24/7 CFE methodology | Hourly matching score |

---

## 4. TDD-Specific Sections an IC Memo Does NOT Need

These are the sections that **separate a lender TDD from a generic feasibility memo**. They are the debt gate:

1. **DNO application pack summary** — G99 form copy, Connection Offer clauses, Modification Applications, Conditions Precedent list
2. **G99 Issue 2 Table 10.1 compliance matrix** — parameter-by-parameter evidence trail for Type A/B/C/D
3. **SLD + protection coordination study** — from 400/132/33/11 kV down to string level, with TCC curves
4. **IEC 61439 switchgear conformance certificates** (Form 1-7, temperature-rise, short-circuit withstand)
5. **Civils + CDM-2015 Principal Designer / Principal Contractor register** with F10 notification status
6. **Water use plan + abstraction licence status** (DC especially; also BESS fire-water)
7. **LCOE build-up** — fully decomposed to 2 dp/MWh
8. **Degradation audit** — independent test-data review or field-fleet proxy
9. **Asset management plan / O&M contract review** — availability guarantee, response SLAs, spares strategy, LTSA cost trajectory
10. **Warranty matrix** — module, inverter, BESS, BoP, civils — with **parent company guarantee** (PCG) status
11. **OPEX reasonableness benchmarking** — £/MW/yr vs lender comparables, indexed to RPI/CPIH
12. **Connection CP schedule** — every clause in the connection offer that needs satisfying before energisation, with owner + date
13. **Insurance programme** — construction-all-risks, DSU, operational property, liability — adequacy vs lender minima
14. **Model audit** — financial model re-build with macro trace, formula check, auditor sign-off letter

---

## 5. Red-Flag Sophistication Ladder (What a Lender TA Flags in Red)

A lender TA earns fees by finding the **five things that kill the deal** if left unfixed. Sophistication ladder (what separates a £30k junior report from a £150k Tier-1 report):

1. **Warranty scope gaps + PCG status**
   - Junior: notes warranty length
   - Senior: reads the actual warranty PDF, identifies carve-outs (power cycling, climate zone, annual cycling cap), checks if PCG from ultimate parent is in place and unconditional, checks parent credit rating, flags if module/BESS OEM has filed Chapter 11 (SunPower precedent)

2. **Connection offer CPs + queue position**
   - Junior: confirms offer is live
   - Senior: reads every clause, flags any "best endeavours" wording, checks REMA/Gate-2 queue reform implications for legacy offers, maps every CP to a dated action owner, stress-tests cost exposure if DNO reinforces asymmetrically

3. **Manufacturer technology risk**
   - Junior: checks module is Tier 1 Bloomberg
   - Senior: reviews bankability ranking (e.g. Sinovoltaics, RETC), IEC 61215/61730 test data, PID/LID susceptibility, field-fleet failure rate, cell supplier disclosure for BESS (LFP vs NMC, vintage, cycle data source)

4. **BNG compliance certificate + planning condition discharge**
   - Junior: notes BNG was applied for
   - Senior: checks the BGP (Biodiversity Gain Plan) has been formally approved, monitors for **Judicial Review window** (6 weeks from s.288 grant for LPA, 6 weeks pre-action for NSIP), NSIP-BNG mandate from May 2026 for applications, 30-year habitat maintenance bond

5. **Fire / thermal-runaway package for BESS, power-density package for DC**
   - Junior: confirms UL 9540A exists
   - Senior: insists on cell+module+unit, CFD propagation, PAS 63100 alignment with Amd 4, FM Global DS 5-33 for DC, insurer sign-off, fire-water volume + spill containment, 10 ft / 3 m aisle, toxicity assessment, HSE review under DSEAR + COMAH if relevant

A Tier-1 TA will also flag: **grid code derogations** outstanding; **STC / BSC accession** progress; **Metering CoP** agreed; **ICP / IDNO** scope split; **Land registry / Title** encumbrances not resolved.

---

## 6. Princeps Gap Analysis vs Lender-TDD Grade

Princeps has the **Lender Pack + Grid Connection Report** already. Mapping against existing `utils/` files:

| TDD section | Princeps coverage | File(s) | Sophistication now | Gap to lender-TDD |
|---|---|---|---|---|
| Yield P50/P90 | Strong | `bankable_yield.py`, `yield_intelligence.py`, SAM bridge | Good (PVsyst-comparable via SAM PvWattsv8) | Needs explicit P75/P99, uncertainty decomposition, 1-sigma band |
| LCOE / DSCR | Partial | `lcoe.py`, `project_finance.py`, `monte_carlo_finance.py`, `dc_finance.py` | Strong on MC; OK on LCOE | Missing: sculpted-debt DSCR output, model audit trail, auditor sign-off format |
| G99 pack | Strong | `g99_pack_generator.py`, `g99_compliance.py`, `g99_brief.py`, `g99_table_101.py` | Good Issue 2 alignment | Needs: **Issue 2 Table 10.1 evidence trail** with test certificate citations; FRT curve plotter |
| Grid connection | Strong | `grid_connection_analyser.py`, `report_grid_connection.py`, `connection_offer_forecaster.py` | Strong Tier 1+2 | Missing: CP schedule generator with owner/date mapping; CCCM cost decomposition to current version |
| SLD | Partial | `sld_generator.py`, `design_sld.py`, `electrical_design.py` | Schematic generator exists | **Missing: protection coordination TCC curves, IEC 60909 fault-level calc, IEC 61439 switchgear conformance check** |
| Noise | Strong | `noise_propagation.py` | BS 4142 likely modelled | Needs explicit rating-level output + receptor table format |
| Glint/glare | Strong | `glint_glare.py` | Good | Needs aviation-authority (CAA CAP 764) output formatting |
| BESS thermal / fire | Partial | `bess_thermal.py` | Thermal modelling exists | **Missing: UL 9540A / NFPA 855 / PAS 63100 compliance audit generator; augmentation plan + capacity retention curve** |
| DC cooling + PUE | Partial | `dc_advanced_design.py`, `dc_cooling_analyser.py`, `dc_heat_rejection.py`, `dc_water_stress.py` | Strong parametric | Missing: formal ASHRAE 90.4 / EN 50600 compliance output; N+1 failure CFD; FM Global DS 5-33 gap check |
| Civils / CDM | Partial | `civil_earthworks.py`, `cdm_pci.py`, `cdm_workforce_timeline.py` | Volume calcs good | Missing: F10 notification tracker; Principal Designer register |
| Planning / BNG / JR | Partial | `bng_calculator.py`, `dco_pack.py`, planning ML | Good | Missing: **JR-window countdown**, BGP approval tracker, condition-discharge register, May-2026 NSIP-BNG flag |
| Warranty / O&M / asset mgmt | **MISSING** | — | None | **Big gap: no warranty matrix, no PCG register, no O&M contract reviewer, no LTSA cost model, no spares plan** |
| Protection coordination | **MISSING** | — | None | **Big gap: no TCC plotter, no relay settings generator, no IEC 60909 fault engine** |
| Insurance programme | **MISSING** | — | None | **Big gap: no CAR/DSU adequacy check** |
| Fire safety (site-wide) | **MISSING** | — | None | Relates to BESS and DC; no PAS 63100 / FM 5-33 / NFPA 855 cross-walk |
| Reliance + sign-off | **MISSING** | `lender_pack.py`, `one_click_report.py` | Output exists | **Missing: CEng sign-off block, liability-cap boilerplate, addressee letter template** |

### Five biggest Princeps gaps vs lender-TDD grade

1. **Warranty / PCG matrix + O&M contract reviewer** — no file covers this; zero-to-new module needed
2. **Protection coordination + IEC 60909 fault-level engine + IEC 61439 switchgear audit** — `electrical_design.py` + `sld_generator.py` stop short; needs pandapower short-circuit + TCC plotter
3. **BESS augmentation plan + capacity retention curve + UL 9540A / PAS 63100 compliance audit** — `bess_thermal.py` is thermodynamic only; missing the commercial/compliance layer lenders care about
4. **Insurance programme adequacy (CAR, DSU, operational) + CEng sign-off / reliance wording** — no file; blocks any "TDD" label
5. **2026 regulatory currency sweep** — G99 Issue 2 Table 10.1 evidence trail, EN-1/3/5 2025 cites, BS 7671 Amd 4 Chapter 57 cross-walk, CCCM-current cost decomposition, BNG-for-NSIP (May 2026) trigger

---

## Sources

- DNV Solar Due Diligence — <https://www.dnv.com/services/solar-due-diligence-58495/>
- Ramboll Solar TDD datasheet — <https://www.ramboll.com/planning-and-project-management/transactional-due-diligence>
- Desapex DC TDD checklist — <https://www.desapex.com/blog-posts/the-ultimate-technical-due-diligence-checklist-for-data-centres>
- BDO Data Centre DD checklist — <https://www.bdo.com/insights/industries/private-equity/data-center-investment-due-diligence-a-checklist>
- ENA G99 Issue 2 (10 March 2025) — <https://dcode.org.uk/assets/250307ena-erec-g99-issue-2-(2025).pdf>
- BS 7671 Amd 4 (2026) — <https://electrical.theiet.org/amendment-4-updates-to-18th-edition>
- NPS EN-1, EN-3, EN-5 2025 — <https://www.gov.uk/government/collections/national-policy-statements-for-energy-infrastructure>
- UL 9540A guidance — <https://www.ul.com/services/ul-9540a-test-method>
- IEC 62933 / BESS certifications — <https://sunlithenergy.com/bess-certifications-guide/>
- DNV BESS warranty paper — <https://www.dnv.com/article/energy-storage-capacity-warranties-beyond-the-fine-print-200339/>
- Solar Bankability Guidelines (TÜV) — <https://www.tuv.com/content-media-files/master-content/services/products/p06-solar/solar-downloadpage/solar-bankability_d4.3_technical-bankability-guidelines.pdf>
- BCLP on UK Data Centre M&A — <https://www.bclplaw.com/en-US/events-insights-news/unlocking-value-in-uk-data-centre-manda-transactions.html>
- BNG planning / CP implications — <https://www.kennedyslaw.com/en/thought-leadership/article/2024/biodiversity-net-gain-and-its-future-impact-on-planning/>
- CCCM (DCUSA Schedule 22) — <http://cdcm.co.uk/cccm.html>
- Arup DC site selection — <https://www.arup.com/en-us/services/data-centre-site-selection-and-due-diligence/>
- BS 4142 ANC guidance — <https://www.association-of-noise-consultants.co.uk/wp-content/uploads/2020/05/ANC-BS-4142-Guide-March-2020.pdf>
