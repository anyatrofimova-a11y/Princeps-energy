# Regulatory 2026 Sweep — Princeps Currency Audit

**Owner:** BOT-Y (paperwork pack)
**Date:** 2026-04-19
**Baseline audited against:** COUNCIL-1 `paperwork_rewrite_spec.md` + `industry_standards_index.md` (March 2025 baseline).
**Purpose:** Per-standard 2026-04-19 currency check. Nothing ships citing a superseded instrument.

---

## Supersessions since March 2025 (headline)

Ranked by impact on Princeps output packs.

| Rank | Standard | COUNCIL-1 baseline | 2026-04-19 reality | Impact |
|------|----------|-------------------|--------------------|--------|
| 1 | **NPS EN-1 / EN-3 / EN-5** | Nov 2023 redesignated Jan 2024 | **2025 revisions**; EN-3 in force **6 Jan 2026**; EN-1 & EN-5 revisions published Nov 2025, before Parliament for 21-sitting-day consideration. Clean Power 2030 imported into EN-1. | HIGH — every DCO + NSIP pack. |
| 2 | **Planning and Infrastructure Act 2025** | Did not exist | **Royal Assent 18 Dec 2025**. Some provisions in force on RA, more Feb 2026, rest await commencement. Introduces Nature Restoration Fund + Environmental Delivery Plans. | HIGH — all planning packs. |
| 3 | **NESO Connections Reform TMO4+ / Gate 2** | Proposed; Ofgem decision pending April 2025 | **Approved 15 April 2025; live from 10 June 2025**. Gate 2 Phase 1 offers issuing mid-May to mid-Nov 2026. | HIGH — all grid connection packs. |
| 4 | **BNG for NSIPs** | "November 2025" go-live anticipated | **Delayed to May 2026** (per Environmental Improvement Plan 2025). Government response Apr 2026 confirms. | HIGH — NSIP packs. |
| 5 | **Small Sites BNG exemption (0.2 ha)** | Not in force | **Given green light Dec 2025**; stat instrument pending 2026. | MED — FVA + small-site packs. |
| 6 | **RICS Red Book Global Standards** | "Effective 31 Jan 2025 edition" (in v.py already) | **Confirmed** published 2 Dec 2024, effective 31 Jan 2025. No newer edition. | LOW — already current. |
| 7 | **REMA decision (zonal pricing)** | Open consultation | **Decision July 2025: Reformed National Pricing (NO zonal)**. SSEP first edition expected late 2026. | MED — finance/dispatch packs. |
| 8 | **Statutory Biodiversity Metric** | v1.0 (Nov 2023) | **v1.0.3 (July 2025)** — minor tooling updates, biodiversity unit outputs unchanged. | LOW — text refresh only. |
| 9 | **CfD AR7 parameters / results** | AR7 scheme pre-publication | **Opened 7 Aug 2025; results 14 Jan 2026**; 8.4 GW awarded; solar ASP £75/MWh, offshore wind ASP £113/MWh; contract length extended to 20 years. | MED — finance/PPA packs. |
| 10 | **Environment Act 2021 Commencement No. 10 Regs 2025** | Up to Feb 2024 | **SI 2025/447 brought specified sections into force 1 May 2025** (inc. TCP-related provisions). First biodiversity duty reports due end-March 2026. | MED — environmental reports. |

### Also notable but lower impact

- **CDM 2015 / HSE L153** — no amendments. HSE has confirmed (May 2025) CDM 2015 will NOT be supported by an ACoP going forward (L153 remains but signalled as not renewed); monitor. No change to SI 2015/51.
- **ENA EREC G99** — Issue 2 (10 Mar 2025) remains latest. **Annex C storage requirements come into force 1 March 2026** (already live as of audit date). No Issue 3.
- **ENA EREC G100 / G98 / G5/5** — no updates found. G5/5 (2020) current.
- **CCCM** — v19 remains reference version; per-DNO statements updated (e.g. ENWL v5.8 effective 1 Jan 2026) but the shared methodology is unchanged. No Ofgem-published v20.
- **NPPF** — Dec 2024 edition **still in force**. Dec 2025 consultation closed 10 Mar 2026; revised NPPF expected June/July 2026. FLAG: monitor for ship-date coincidence.
- **Infrastructure Planning (APFP) Regs 2009** — amended by **Infrastructure Planning (Miscellaneous Provisions) Regulations 2024** (in force 30 April 2024). Current SI 2009/2264 as amended through SI 2024/332.
- **REUL Act 2023** — power to revoke/restate retained EU law **expires 23 June 2026** unless extended per-instrument. Princeps does not currently anchor anything that would lapse, but any REUL-derived ref (EIA Regs 2017 is REUL-derived) is in the shadow of this date.
- **Procurement Act 2023** — commenced **24 Feb 2025**. No direct CCCM collision; relevant for any Princeps-generated procurement schedules for contracting authorities (DNOs are not contracting authorities under PA 2023).
- **RIIO-ED2** — runs 2023-04-01 → 2028-03-31. Mid-period adjustments ongoing: additional NIA funding confirmed Oct 2025 for final two years. RIIO-ED3 draft determinations open; NOT yet final. No ED2-replacement in 2026.
- **1APP v6 / CIL Form 1** — Planning Portal announced (Mar 2026) that CIL Form 1 is being embedded directly into the 1APP journey for CIL-enabled LPAs, removing the separate upload. The v6 form remains canonical.
- **Environmental Outcomes Reports (EOR)** — Part 6 LURA 2023 is in force but substantive regulations **not yet made**. EIA/SEA remain the operative regimes. No change for 2026 packs.
- **RICS FVP** — 2nd ed. (2021) remains current. RICS has published a "4th edition" notionally but the authoritative professional statement is still 2nd ed per RICS standards page (ambiguity flagged — see Open Questions).

### Repealed / withdrawn with no replacement — none found

No standard in scope was silently withdrawn without replacement. G83 and G59 were withdrawn but have documented replacements (G98, G99) already captured in `versions.py`.

---

## Per-standard detail

### 1. ENA EREC G99 — Issue 2

- **Status (2026-04-19):** Issue 2, 10 March 2025 — CURRENT.
- **Annex C (storage):** Mandatory provisions live from 1 March 2026 — now LIVE as of audit. Post-energisation tests under Annex C.9.2 must be returned within 28 days of synchronisation.
- **Delta from COUNCIL-1:** Annex C now in-force rather than pending; notes text needs refresh.
- **Source:** https://dcode.org.uk/assets/250307ena-erec-g99-issue-2-(2025).pdf

### 2. ENA EREC G100 / G98

- **G100:** Issue 2 Amendment 1, 2022 — no update found. `versions.py` current.
- **G98:** Issue 1 Amendment 9 in `versions.py`. Search evidence of **Issue 1 Amendment 10 (2024)** at dcode.org.uk for G99 — need to verify G98 equivalent. Principal hub record unchanged. Low impact; flag for monitoring.

### 3. ENA EREC G5/5 — Harmonics

- Current version: G5/5, introduced 17 June 2020. Unchanged. No G5/6 in pipeline per NESO Grid Code GC0129.

### 4. CCCM

- **Status:** v19 (2024) remains the referenced methodology. DNO per-statement updates continue (ENWL Statement v5.8 effective 1 Jan 2026; SGN modification decision July 2025). No v20 published by Ofgem / ENA.
- **Delta:** None at methodology level.

### 5. NPPF

- **Status:** December 2024 edition — still in force on audit date.
- **Pending:** December 2025 consultation closed 10 March 2026; revised edition expected **June/July 2026**. The 2025 consultation document is already referenced in COUNCIL-1's `industry_standards_index.md` row 31.
- **Action:** Leave `versions.py` at Dec 2024 edition; add a forthcoming-revision note.

### 6. NPS EN-1 / EN-3 / EN-5 — MAJOR CHANGE

- **COUNCIL-1 baseline:** Nov 2023 refresh, designated 17 January 2024.
- **2026 reality:** DESNZ published 2025 revisions.
  - **EN-3 (renewables) — in force 6 January 2026.**
  - EN-1 and EN-5 — revised texts published Nov 2025, before Parliament for 21-sitting-day consideration. Once in force, apply to DCO applications accepted for examination from that point.
- **Key substantive change:** Clean Power Action Plan 2030 is embedded into EN-1. Onshore wind covered (≥100 MW) following Infrastructure Planning (Onshore Wind and Solar Generation) Order 2025.
- **Source:** https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025 ; https://www.gov.uk/government/publications/overarching-national-policy-statement-for-energy-en-1-2025/overarching-national-policy-statement-for-energy-en-1-2025-accessible-webpage
- **Action:** Update `versions.py` entries en1/en3/en5. Pack rewrite bots must cite EN-3 (2026) where applicable; EN-1 (2025) and EN-5 (2025) pending in-force confirmation — flag as "designated Nov 2025, in force pending 21-day parliamentary period".

### 7. Planning and Infrastructure Act 2025 — NEW

- **Royal Assent:** 18 December 2025.
- **Commencement:** Phased — some provisions on RA, some Feb 2026, majority await commencement orders.
- **Key provisions:** Nature Restoration Fund; Environmental Delivery Plans; NSIP regime reform; modernisation of planning committees.
- **Source:** https://bills.parliament.uk/bills/3946 ; https://www.gov.uk/government/news/landmark-planning-and-infrastructure-bill-becomes-law
- **Action:** Add `pinfra_act_2025` entry to `versions.py`.

### 8. Clean Power 2030 Action Plan

- **Status:** Published Dec 2024; **connections reform annex update April 2025**; ongoing implementation.
- **2026 milestones:** SSEP expected publication late 2026; most new transmission grid / offshore wind projects need all relevant planning permissions in place **by 2026**; DESNZ response to community benefits working paper forthcoming.
- **Source:** https://www.gov.uk/government/publications/clean-power-2030-action-plan/

### 9. NESO Connections Reform TMO4+ / Gate 2

- **Ofgem approval:** 15 April 2025.
- **Live date:** 10 June 2025.
- **Gate 2 Phase 1 offers:** Transmission/large embedded mid-May → mid-Sep 2026. Distribution early Jul → mid-Nov 2026.
- **Queue outcome:** Reduced from ~700 GW to 283 GW (generation/storage).
- **Source:** https://www.neso.energy/industry-information/connections-reform/connections-reform-timeline
- **Action:** Update `versions.py` tmo4 entry. `helpers.py` fallback key `TMO4_Gate2` currently says "Ofgem decision April 2025, in force May 2025" — CORRECTION: live from 10 June 2025.

### 10. Statutory Biodiversity Metric

- **Status:** v1.0 (29 Nov 2023) with **minor routine updates July 2025** — current publication indicates v1.0.3 family; biodiversity unit outputs unchanged.
- **Small Sites Metric:** Updated user guide July 2025. Exemption for sites <0.2 ha approved Dec 2025; SI pending.
- **NSIP BNG:** Introduction delayed from Nov 2025 → **May 2026**.
- **Source:** https://www.gov.uk/government/publications/statutory-biodiversity-metric-tools-and-guides ; https://assets.publishing.service.gov.uk/media/689c5ee17b2e384441636196/The_Statutory_Biodiversity_Metric_-_User_Guide_-_July_2025.pdf

### 11. UKHab v2.0

- **Status:** v2.0 (2023) — no update found. Unchanged.

### 12. CDM Regulations 2015 / HSE L153

- **Status:** SI 2015/51 unchanged. L153 remains the ACoP. However: HSE has indicated (May 2025 bulletins) that CDM 2015 **will not be supported by an ACoP** going forward — L153 may be retired in future. Not yet retired on audit date.
- **Action:** Add monitoring note to `versions.py` `hse_l153` entry.

### 13. Planning Portal 1APP v6 / CIL Form 1

- **Status:** v6 remains canonical. Planning Portal (Mar 2026 blog) confirms CIL information now embedded into the 1APP journey for CIL-enabled LPAs.
- **Action:** Update `versions.py` `1app` notes to reflect CIL embedding for CIL-enabled authorities.

### 14. RICS FVP

- **Status:** 2nd edition, 2021, effective 1 May 2021. One secondary source mentions "4th edition" but the RICS professional standards page does not surface a 3rd/4th ed at audit date. **AMBIGUITY** — retain 2nd ed. pending primary confirmation.

### 15. RICS Red Book Global Standards

- **Status:** Effective 31 January 2025 edition — published 2 Dec 2024. CURRENT. Aligned with IVS effective 31 Jan 2025.
- **Action:** `versions.py` `rics_red_book` entry currently shows "Effective 31 January 2022" — STALE. UPDATE to 31 January 2025.

### 16. LMA loan documentation

- **Status:** 2024 update referenced in `versions.py`. LMA releases iterative amendments year-round; no authoritative single "v.." string. Princeps convention is "LMA LFA current as at [date]" — keep.

### 17. Environmental Outcomes Reports (EOR)

- **Status:** Part 6 LURA 2023 in force 26 Dec 2023 but **no substantive EOR regulations made** as of audit. Labour Government (Dec 2024 statement) confirmed intent to implement; no timeline on audit date. EIA and SEA remain operative.
- **Action:** Do not cite EOR as operative regime. Princeps packs already use EIA Regs 2017 — correct.

### 18. REUL Act 2023

- **Status:** Revocation/restatement powers expire **23 June 2026**. Princeps does not currently anchor on any retained EU law ref that would lapse. EIA Regs 2017 (SI 2017/571) — originally implementing EU EIA Directive — remain in force as assimilated law.
- **Monitor:** Any ministerial use of s.14 before June 2026.

### 19. Procurement Act 2023

- **Status:** Commenced 24 February 2025. Transitional period running 24 Feb 2025 → 30 Sep 2025; subsequent six-month reporting periods.
- **CCCM interplay:** DNOs are not contracting authorities under PA 2023 for CCCM work; no direct collision. Any Princeps outputs for public-sector utility counterparties should note PA 2023 applies.

### 20. CfD AR7 (2026 round)

- **Status:** AR7 opened 7 Aug 2025; results announced **14 January 2026** — 8.4 GW awarded.
- **Strike prices:** Offshore wind E&W £91.20/MWh; Scotland £89.49/MWh; floating OSW £216.49/MWh.
- **ASPs:** Solar PV £75/MWh (-12% from AR6); offshore wind £113/MWh (+11%).
- **Contract length:** Extended to 20 years (was 15) for wind & solar.
- **Action:** Add `cfd_ar7` entry to `versions.py`.

### 21. Ofgem RIIO-ED2 mid-period review

- **Status:** Price control runs 2023-04-01 → 2028-03-31. **No formal mid-period review** equivalent to GD/T. Ongoing Ofgem reopener adjustments: NIA funding top-up Oct 2025; LRE volume driver consultation (decision awaited Feb 2026).
- **RIIO-ED3:** Draft determinations in progress; framework-setting underway — not final.

### 22. REMA

- **Status:** July 2025 REMA Summer Update: **NO zonal pricing; Reformed National Pricing confirmed**. SSEP late 2026; CSNP 2027.
- **Source:** https://assets.publishing.service.gov.uk/media/686f71412557debd867cbeff/review-of-electricity-market-arrangements-rema-summer-update-2025.pdf

### 23. Infrastructure Planning (APFP) Regs 2009

- **Status:** Most recent amendment: **Infrastructure Planning (Miscellaneous Provisions) Regulations 2024** (SI 2024/332) — in force 30 April 2024. Applies to DCO applications submitted after that date.
- **Action:** `versions.py` `bcp_regs_2009` notes SI 2013/1124 — update to reference SI 2024/332 as the most recent amendment to SI 2009/2264.

### 24. Environment Act 2021 — further commencements

- **Status:** Environment Act 2021 (Commencement No. 10) Regs 2025 (SI 2025/447) brought specified sections into force **1 May 2025**, including TCP-related provisions. First biodiversity duty reports due end March 2026.
- **Action:** `versions.py` notes refresh.

---

## Open questions / ambiguities

1. **RICS FVP 3rd/4th edition** — secondary sources suggest a "4th edition" but RICS professional standards page does not obviously surface it. Flagged; treated as 2nd edition (2021) pending primary evidence.
2. **EN-1 / EN-5 (2025) precise in-force date** — 21-sitting-day parliamentary period was running at audit date. Principal site confirms EN-3 in force 6 Jan 2026; EN-1/EN-5 status ambiguous — conservatively cite "designated Nov 2025, in force once 21-sitting-day period expires".
3. **L153 retention** — HSE signalled ACoP would not be maintained; not yet retired. Monitor.
4. **NPPF June/July 2026 revision** — consultation closed; publication imminent but not on audit date.

---

## Primary sources (consolidated)

- ENA / dcode.org.uk (for EREC documents): https://dcode.org.uk/
- GOV.UK NPSs: https://www.gov.uk/government/publications/national-policy-statements-for-energy-infrastructure
- GOV.UK NPPF: https://www.gov.uk/government/publications/national-planning-policy-framework--2
- GOV.UK Planning and Infrastructure Act 2025: https://bills.parliament.uk/bills/3946
- NESO Connections Reform: https://www.neso.energy/industry-information/connections-reform
- Ofgem REMA: https://www.gov.uk/government/collections/review-of-electricity-market-arrangements-rema
- Defra biodiversity metric: https://www.gov.uk/government/publications/statutory-biodiversity-metric-tools-and-guides
- legislation.gov.uk for SI 2024/332, SI 2025/447, Environment Act 2021, LURA 2023.
- RICS Red Book: https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/red-book
- CfD AR7: https://www.gov.uk/cma-cases/referral-of-the-proposed-contracts-for-difference-allocation-round-7-scheme-by-the-department-for-energy-security-and-net-zero
