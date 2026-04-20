# Regulatory Call Sites — 2026-04-19 BOT-Y Sweep

**Companion to:** `regulatory_2026_sweep.md`
**Purpose:** Every file:line in the repo that hardcodes a regulatory string, whether the cited version is current as of 2026-04-19, and what it should change to. Pack rewrite bots use this as their cleanup checklist.

---

## Legend

- **STALE** — cited version is no longer current; rewrite required.
- **CURRENT** — cited version still the authoritative one; no change needed.
- **AMBIGUOUS** — depends on application acceptance date or similar contextual logic.
- **IN-FLIGHT** — file was modified by another bot in the 5-minute window preceding this audit; BOT-Y did not touch. Owning bot must integrate fix.

---

## 1. ENA EREC G99 — Issue version

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/g99_compliance.py:9 | `ENA EREC G99 Issue 1 Amendment 9 (2023)` | **STALE** | `ENA EREC G99 Issue 2 (10 March 2025); Annex C storage provisions in force 1 March 2026` |
| utils/g99_compliance.py:630 | `EREC G99 Issue 1 Amendment 9` | **STALE** | as above |
| utils/g99_compliance.py:694 | `"applicable_standard": "EREC G99 Issue 1 Amendment 9 (2023)"` | **STALE** | `"EREC G99 Issue 2 (10 March 2025)"` |
| utils/g99_compliance.py:987 | `"standard": "EREC G99 Issue 1 Amendment 9"` | **STALE** | `"EREC G99 Issue 2"` |
| templates/report/_partials/_reliance.html:50 | `G99 Issue 2 (10 March 2025)` | **CURRENT** | no change |
| utils/construction_timeline.py:64,65,92,93,123 | `"G99 application"`, `"G99 witness test passed"` | **CURRENT** (process refs, not version refs) | no change |
| app/agent.py:138,197,237 | `G98/G99`, `G99/G100`, `G99/CUSC` (prose, no issue) | **CURRENT** | no change |
| app/regulatory/versions.py:60,78,638 | `Issue 1 Amendment 9` (in `supersedes` list + g98 version + self-test) | **CURRENT** (these are supersedes/self-test; intentional) | no change |

**Pack-rewrite action:** `g99-bot` must refactor `utils/g99_compliance.py` to import `cite("g99")` from `app.regulatory.versions` instead of string-literal Issue references.

## 2. NPPF paragraph references

COUNCIL-1 audit already spelled out that para 152 → 162, 154 → 165, 158 → 167/168, 186 varies — mappings are in `NPPF_PARA_MAP`. Remaining call sites that still quote old numbers:

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/policy_matrix.py:70 | `NPS for Energy (EN-1, EN-3, EN-5) — Nov 2023 refresh, designated 17 Jan 2024` | **STALE** (EN-3 superseded 6 Jan 2026) | See EN-1/3/5 section below. **IN-FLIGHT — mtime 18:45:15** — owning bot to apply fix. |
| utils/policy_matrix.py:125,156,179,209 | `(Old 2021 para 152.)`, `(Old 2021 para 154.)`, `(Old 2021 para 158.)`, `(Old 2021 para 186.)` in docstrings | **CURRENT** (intentional legacy notes) | no change |
| utils/policy_matrix.py:386,397,409,420 | `"legacy_ref": "NPPF 2021 para 152"` etc. | **CURRENT** (explicit legacy markers) | no change |
| utils/planning_intelligence.py:1720,1732,1743,1787 | `NPPF para 186`, `NPPF paras 152-168` | **STALE** — 186 → 187/188 variations; 152-168 → 162-180 approximate range | `1720/1732/1743`: `NPPF para 187 (Dec 2024)` (BMV / SSSI protection); `1787`: `NPPF paras 162-175 (Dec 2024)` |
| utils/planning_intelligence.py:1521,1524 | `Defra Biodiversity Metric 4.0`, `BNG Assessment (Metric 4.0)` | **STALE** | `Statutory Biodiversity Metric (v1.0.3, July 2025)`; `BNG Assessment (Statutory Biodiversity Metric)` |
| utils/document_automation.py:406 | `NPPF para 186` (BMV context) | **STALE** | `NPPF 2024 para 187` |
| utils/document_automation.py:524 | `NPPF paras 152–157` (Green Belt VSC) | **STALE** | `NPPF Dec 2024 paras 162-167 / Section 13 (Green Belt)` |
| utils/document_automation.py:942 | `NPPF Dec 2024 — para 186 (BMV)` | **STALE** | `NPPF Dec 2024 — para 187 (BMV)` |
| utils/document_automation.py:1114 | `NPPF 2024 para 186` | **STALE** | `NPPF 2024 para 187` |
| utils/document_automation.py:558,938-943,1153 | various NPPF Dec 2024 paras in correct numbering | **CURRENT** | no change |
| utils/constraint_report_generator.py:525,529,530,531,562,644 | `NPPF para 180`, `NPPF para 177`, `NPPF Section 13`, `para 180c`, `footnote 62` | **STALE/AMBIGUOUS** — Dec 2024 renumbered these: AONB para 182/183; SSSI 187; ancient woodland 187(c); BMV footnote 62 → 63 | Check against NPPF_PARA_MAP + live Dec 2024 PDF. Apply in a single pass. |
| utils/environmental_constraints.py:266 | `NPPF para 177` (AONB) | **STALE** | `NPPF Dec 2024 para 182 (National Landscape)` |
| utils/land_classification_ml.py:458 | `NPPF para 174b protection` (BMV) | **STALE** | `NPPF Dec 2024 para 187(b)` — cross-check |
| utils/dc_advanced_design.py:539 | `Pre-application consultation (NPPF para 39-46)` | **STALE** | `NPPF Dec 2024 paras 40-46` |

**Pack-rewrite action:** `planning-bot` / `nppf-bot` should wire every NPPF paragraph ref through a helper (e.g. `nppf_para("BMV")` returning `"NPPF Dec 2024 para 187"`) rather than inline numbers. Add missing mappings to `app/regulatory/versions.py::NPPF_PARA_MAP`.

## 3. NPS EN-1 / EN-3 / EN-5 references

Major — COUNCIL-1 baseline was Nov 2023. 2026 reality: EN-3 in force 6 Jan 2026; EN-1 & EN-5 2025 revisions designated Nov 2025, 21-sitting-day period.

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/dco/statement_of_reasons.py:92-93 | `EN-1 (Overarching Energy, Jan 2024 rev.), EN-3 (Renewable Energy Infrastructure, Jan 2024 rev.) and EN-5` | **STALE** — **IN-FLIGHT (mtime 18:44:36)** | Owning bot (DCO pack rewrite) to cite EN-3 (2025 rev., in force 6 Jan 2026); EN-1/EN-5 (2025 rev., designated Nov 2025 — AMBIGUOUS in-force until 21-day period expires). Use acceptance-date logic. |
| utils/dco/statement_of_reasons.py:210 | `NPS EN-1 paragraph 3.3.1 (Jan 2024 rev.)` | **STALE** — **IN-FLIGHT** | As above — cite 2025 revision paragraph (number may have changed) if DCO accepted after 2025 NPS in-force date. |
| utils/dco/statement_of_reasons.py:216 | `NPS EN-3 (Jan 2024) Part 2` | **STALE** — **IN-FLIGHT** | EN-3 (2025, in force 6 Jan 2026) — note Part numbering may have shifted. |
| utils/policy_matrix.py:70 | `NPS for Energy (EN-1, EN-3, EN-5) — Nov 2023 refresh, designated 17 Jan 2024` | **STALE** — **IN-FLIGHT (mtime 18:45:15)** | EN-3 (2025, in force 6 Jan 2026); EN-1/EN-5 (2025 rev., designated Nov 2025). |
| utils/policy_matrix.py:244 | `EN-1 (Nov 2023 refresh, designated 17 Jan 2024)` | **STALE** — **IN-FLIGHT** | EN-1 (2025 revision) once in force. |
| utils/document_automation.py:667 | `NPS EN-1 (revised 2025) + EN-3 apply` | **CURRENT** (acknowledges 2025 revision) | Consider strengthening to reference EN-3 2025 specifically. |
| utils/document_automation.py:675 | `NPS EN-1 + EN-3 apply` | **STALE** (generic; no version) | add `(2025 revision; EN-3 in force 6 Jan 2026)` |
| utils/document_automation.py:665 | `Planning Act 2008. NPS EN-1 (revised 2025) + EN-3 apply.` | **CURRENT** | no change |
| templates/report/_partials/helpers.py:126-145 (`EN1_2024`, `EN3_2024`, `EN5_2024`) | `Designated 17 January 2024` | **STALE** but **IN-FLIGHT (mtime 18:40:xx)** — helpers.py touched in last 5 min | Owning bot (BOT-R1 / paperwork helpers) to update fallback table entries to cite 2025 revisions with acceptance-date logic. |
| app/regulatory/versions.py:en1/en3/en5 | updated by BOT-Y | **CURRENT** (post this sweep) | — |

## 4. CCCM

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| templates/report/_partials/_reliance.html:51 | `Common Connection Charging Methodology v19 (2024)` | **CURRENT** | no change; CCCM v19 still authoritative. |
| templates/report/_partials/helpers.py:CCCM_v19 | `v19, 2024` | **CURRENT** but **IN-FLIGHT** (helpers.py touched) | no substantive change; monitoring only. |
| app/regulatory/versions.py:cccm | BOT-Y updated notes | **CURRENT** | — |

## 5. Biodiversity Metric / BNG

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/bng_calculator.py:3,11,28,40,42,119,130,137,145,160,216,387 | `Biodiversity Metric 4.0`, `Defra Biodiversity Metric 4.0 (Jan 2023)` | **STALE** | `Statutory Biodiversity Metric (v1.0, 29 Nov 2023; minor tooling update July 2025)` throughout. Metric 4.0 lookup tables should be relabelled as the statutory-metric tables (they are structurally the same — Natural England kept the Metric 4.0 lookups in the statutory version — but the name must change). |
| utils/document_automation.py:866 | `Defra Statutory Biodiversity Metric v4.0 baseline` | **STALE** | `Defra Statutory Biodiversity Metric (v1.0, Nov 2023) baseline` |
| utils/document_automation.py:1119 | `Defra Statutory Biodiversity Metric v4.0 baseline` | **STALE** | as above |
| utils/document_automation.py:1767,1851,1857,2231 | `Biodiversity Metric 4.0`, `Defra Biodiversity Metric 4.0 (simplified)` | **STALE** | `Statutory Biodiversity Metric (v1.0)` variants |
| utils/one_click_report.py:455,905,939,941,965 | `Biodiversity Metric 4.0 / UKHab v2.0`, `Defra Biodiversity Metric 4.0` | **STALE** | Replace 4.0 with `Statutory Biodiversity Metric (v1.0)` |
| utils/report_renderer.py:1087 | `Defra Metric 4.0 / UKHab v2.0` (comment) | **STALE** | as above |
| utils/dc_advanced_design.py:295 | `DEFRA Biodiversity Metric 4.0 — simplified habitat unit values` | **STALE** | as above |
| utils/planning_intelligence.py:1521,1524 | see NPPF section | as above | as above |
| templates/report/environment.html:196,198,271,280 | `Biodiversity Metric 4.0 / UKHab v2.0` in HTML | **STALE** | Replace `Metric 4.0` strings with `Statutory Biodiversity Metric (v1.0)`. |
| app/routers/documents.py:148 | `Simplified Biodiversity Metric 4.0 using DynamicWorld` | **STALE** | `Simplified Statutory Biodiversity Metric (v1.0)` |
| app/routers/environment.py:438 | `"bng_metric": "DEFRA Biodiversity Metric 4.2"` | **STALE** (there was never a 4.2 for statutory) | `"bng_metric": "Statutory Biodiversity Metric v1.0"` |
| feasi-frontend/src/components/dashboard/RegulatoryFeed.jsx:63,65 | `Metric 4.0` (article body) | **STALE** | Update news card text to refer to statutory metric. |
| feasi-frontend/docs/planning-regulatory-intelligence-research.md:595 | `Defra Biodiversity Metric 4.0` | **STALE** (research doc) | flag for doc-refresh. |

**Additional BNG item:** NSIP BNG **delayed to May 2026** (was Nov 2025). Affects `utils/document_automation.py:548` which already says `"NSIPs from May 2026"` — **CURRENT**; consistent with audit.

## 6. RICS Red Book

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| app/regulatory/versions.py:rics_red_book | BOT-Y updated to `Effective 31 January 2025` | **CURRENT** | — |
| templates/report/_partials/helpers.py:RICS_RedBook_2025 | `Effective 31 January 2025` | **CURRENT** | no change |
| templates/report/financial_viability_base.html:533 | `RICS Financial Viability in Planning 1st ed.` | **STALE** | `RICS Financial Viability in Planning — Conduct and Reporting (2nd ed., 2021)` |

## 7. TMO4+ / Gate 2 (NESO Connections Reform)

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| templates/report/_partials/helpers.py:TMO4_Gate2 | `Ofgem decision April 2025, in force May 2025` | **STALE** — **IN-FLIGHT** (helpers.py touched) | `Ofgem approved 15 April 2025; TMO4+ live 10 June 2025. Gate 2 Phase 1 offers issuing mid-May → mid-Nov 2026.` |
| app/regulatory/versions.py:tmo4_gate2 | BOT-Y created | **CURRENT** | — |

## 8. Environment Act 2021

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/one_click_report.py:941 | `Environment Act 2021 s.98` + `mandatory from 12 February 2024 via Schedule 7A` | **CURRENT** | no change |
| utils/document_automation.py:548 | `Environment Act 2021 — mandatory BNG ... NSIPs from May 2026` | **CURRENT** | no change |
| utils/document_automation.py:866 | `MANDATORY (Environment Act 2021)` | **CURRENT** | no change (but Metric 4.0 reference inside this string is STALE — see BNG section) |
| utils/dco/application_form.py:71 | `Planning Act 2008 c.29 (as amended by the Localism Act 2011 and Levelling-up and Regeneration Act 2023)` | **STALE** — should also cite Planning and Infrastructure Act 2025 | Append `and the Planning and Infrastructure Act 2025 (Royal Assent 18 Dec 2025; phased commencement)` |
| utils/document_automation.py:357 | `(Amendment) Regs 2026 (DC NSIP opt-in via s.35 Planning Act 2008)` | **AMBIGUOUS** — this appears to be a forward reference to a 2026 regulation. Verify if a specific SI is intended or if this is narrative. | Flag for `dc-bot` to confirm. |
| utils/document_automation.py:657,665,994 | `NSIP via s.35 Planning Act 2008 direction (opt-in, Jan 2026 regs)`, `Planning Act 2008 s.15, as amended 2025`, `Planning and Infrastructure Act 2025 (Royal Assent 18 Dec 2025)` | **CURRENT** | no change |
| utils/document_automation.py:1153 | `(NPPF 2024 / EIA Regs 2017 / Environment Act 2021 / P&I Act 2025)` | **CURRENT** | no change |
| app/regulatory/versions.py:environment_act_2021 | BOT-Y updated to cite SI 2025/447 | **CURRENT** | — |

## 9. Planning and Infrastructure Act 2025

Already correctly cited in `utils/document_automation.py:994,1153` and `utils/planning_intelligence.py:1453` — all **CURRENT**. No STALE call sites.

## 10. Infrastructure Planning (APFP) Regs 2009

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| app/regulatory/versions.py:bcp_regs_2009 | BOT-Y updated to reference SI 2024/332 | **CURRENT** | — |
| templates/report/_partials/helpers.py:IPA_Regs_2009 | `SI 2009/2264, amended through 2024` | **CURRENT** but **IN-FLIGHT** | confirmation only |

## 11. CDM 2015 / HSE L153

All call sites are prose references without version hardcoding (`app/agent.py:197`; `templates/report/environment.html` etc.). **CURRENT**.

- `templates/report/_partials/helpers.py:HSE_L153` says `2015, reprinted 2019` — **CURRENT** at audit date but monitor for HSE's indicated ACoP retirement.

## 12. Planning Portal 1APP / CIL Form 1

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/one_app_filler.py | `v6` throughout, incl. `form_version: "Planning Portal 1APP v6 (2024)"` at line 632 | **CURRENT** | Add note on Mar 2026 CIL Form 1 embedding for CIL-enabled LPAs (affects field Q-range in `_fill_cil_form1`). |
| utils/one_app_filler.py:24 | `CIL Form 1 (Assumption of Liability)` | **CURRENT** | confirm; note that for CIL-enabled LPAs the form is being journey-embedded per Planning Portal (Mar 2026). |

## 13. CfD, REMA, RIIO-ED2 — new or no-change

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| app/routers/finance_extras.py:407 | `"label": "Planning policy (NPPF 2026)"` | **STALE** — NPPF 2026 edition not yet published | `"label": "Planning policy (NPPF Dec 2024, forthcoming 2026 revision)"` |
| utils/financial_viability_charts.py:23 | `NPPF Annex 2` | **CURRENT** | no change |
| app/regulatory/versions.py:cfd_ar7, rema_2025, clean_power_2030 | BOT-Y created | **CURRENT** | Pack rewrite bots should import these for any AR7/PPA/market-structure packs. |
| session-export.md:1723,1743 | `Clean Power 2030 investment needed` etc. | **CURRENT** (historical export, not live citation) | no change |

## 14. Other strings worth noting

| File:line | Current string | Status | Target string |
|-----------|----------------|--------|---------------|
| utils/xlsx_export.py:247 | `["G99/G100", "CDM 2015", "BNG (10% uplift)", "EIA Screening", "NPPF", "ALC", "Flood Test", "NSIP (>50MW)"]` | **CURRENT** (generic labels) | NSIP threshold — since Energy Act 2023 solar threshold raised to 100 MW, "NSIP (>50MW)" is misleading — should read `"NSIP (solar >100MW; wind >100MW onshore)"` |
| utils/one_click_report.py:941 | inline `Biodiversity Metric 4.0` default in `get('metric_version', 'Biodiversity Metric 4.0')` — **STALE** default | Default should be `'Statutory Biodiversity Metric v1.0'` |
| utils/bng_calculator.py:160 `METRIC_VERSION` constant | `"Defra Biodiversity Metric 4.0 (Jan 2023)"` | **STALE** | `"Statutory Biodiversity Metric v1.0 (29 Nov 2023; minor tooling update Jul 2025)"` |

---

## In-flight files (skipped by BOT-Y)

BOT-Y did not modify these; owning bot must apply the fixes listed above. Mtimes are as observed 2026-04-19 18:47:38 BST.

| File | Mtime | Likely owner |
|------|-------|--------------|
| utils/policy_matrix.py | 18:45:15 | nppf-bot / policy-bot |
| utils/dco/statement_of_reasons.py | 18:44:36 | dco-bot |
| utils/document_automation.py | 18:39:52 (just outside 5-min window but last touched adjacent to BOT-R2 edit) | doc-automation-bot |
| templates/report/_partials/helpers.py | ~18:39-18:40 | BOT-R1 (paperwork scaffolding) |
| app/regulatory/versions.py | 18:39:41 → edited by BOT-Y after stability confirmed | BOT-R2 + BOT-Y |
| utils/one_app_filler.py | 18:xx | one-app-bot |
| utils/rics_fvp.py | 18:xx | fva-bot |
| utils/lender_pack_sections/* | 18:xx | lender-bot |
| utils/dco/application_form.py | 18:xx | dco-bot |

**Note:** mtimes of helpers.py and versions.py were both inside the sensitive window at start of BOT-Y's run. BOT-Y waited for stability and edited versions.py only (helpers.py left untouched — owning bot to update per the call sites flagged above).

---

## Summary of call-sites touched / flagged

| Category | STALE | CURRENT | IN-FLIGHT | Total cited |
|----------|-------|---------|-----------|-------------|
| G99 Issue | 4 | 7 | 0 | 11 |
| NPPF paragraphs | 12 | 8 | 0 | 20 |
| NPS EN-1/3/5 | 2 | 4 | 6 | 12 |
| Biodiversity Metric 4.0 | 17 | 0 | 0 | 17 |
| RICS Red Book | 1 | 2 | 0 | 3 |
| TMO4+ / Gate 2 | 0 | 1 | 1 | 2 |
| Environment Act 2021 | 1 | 5 | 0 | 6 |
| Planning Act / P&I Act | 0 | 3 | 0 | 3 |
| NSIP thresholds / CCCM / other | 2 | 5 | 2 | 9 |
| **Totals** | **39** | **35** | **9** | **83** |

---

## Upstream changes BOT-Y applied

- `/Users/anyatrofimova/feasibly/app/regulatory/versions.py` — updated IN PLACE (stability confirmed: mtime 3+ min stale when BOT-Y edited).
  - G99 notes refresh (Annex C live)
  - CCCM notes refresh
  - NPPF notes (flag pending Dec 2025 revision)
  - EN-1 / EN-3 / EN-5 — updated to 2025 revisions with acceptance-date logic
  - Statutory Biodiversity Metric — Jul 2025 tooling update + NSIP delay to May 2026
  - Environment Act 2021 — SI 2025/447 (Commencement No. 10) note
  - HSE L153 — ACoP retirement monitoring note
  - RICS Red Book — corrected from Jan 2022 → Jan 2025 edition
  - Infrastructure Planning APFP Regs — SI 2024/332 amendment
  - 1APP — CIL Form 1 embedding note
  - NEW entries: `tmo4_gate2`, `pinfra_act_2025`, `pinfra_act_2025_commencements`, `procurement_act_2023`, `reul_act_2023`, `cfd_ar7`, `rema_2025`, `clean_power_2030`
- `/Users/anyatrofimova/feasibly/docs/audits/regulatory_2026_sweep.md` — new file.

BOT-Y did NOT write a companion `versions_2026_delta.py` — in-place update to `versions.py` was safer (stability confirmed) and avoids fragmenting the source of truth.
