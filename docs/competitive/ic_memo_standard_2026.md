# IC Memo Standard 2026 — UK Energy Infrastructure

Target: specification of what a 2026 Investment Committee memo looks like for a 50 MW solar farm, 100 MWh BESS, or 50 MW data-centre acquisition/development, such that a seasoned advisor (Augusta / Mizuho, Rothschild, Lazard, CBRE IM, Macquarie Asset Management, Quinbrook, Gresham House) would recognise it as first-page-turn-convincing.

Audience: Princeps product + engineering. Mapped against `utils/lender_pack_sections/s01_cover.py` through `s15_signature.py`.

---

## 1. Standard IC Memo Structure (2026)

An IC memo is distinct from a lender pack: the IC memo is an *equity* decision document, shorter (20–40 pages body + ~60 pages of annex), front-loaded with the recommendation, and expected to be read first by the chair in 20 minutes. Below is the consensus 2026 structure. Page counts reflect a 50 MW single-asset deal; portfolio transactions roughly 1.5x.

| # | Section | Target pages | Typical content |
|---|---|---|---|
| 1 | Cover + recommendation box | 1 | Asset, sponsor, ticket size, hold period, base-case equity IRR / MOIC / DPI, blended DSCR, verdict (GO/CONDITIONAL/NO-GO), vote requested. |
| 2 | Executive summary | 2 | Deal-in-three-bullets, thesis, price, sources & uses headline, 4 headline risks with traffic-light, committee-question pre-empt. |
| 3 | Transaction overview | 2 | Vendor / counterparty, structure (share vs asset, SPV chain), conditions precedent, exclusivity, timeline to signing / completion. |
| 4 | Market & thesis | 3–4 | UK power price curve (source: Cornwall Insight / LCP Delta / Afry — cite which), demand narrative (NESO FES 2024 pathway used), competing capacity pipeline, why-now. |
| 5 | Asset description | 3 | Site, grid connection (MIC, Gate 2 status, TMO4+ offer date), planning status (consent date, JR risk window expired y/n), technology (module/inverter OEM, augmentation plan for BESS). |
| 6 | Commercial strategy | 2–3 | CfD (AR7/AR8) vs merchant vs PPA split, offtaker credit, route-to-market (for BESS: trading desk, wholesale/BM/ancillary split), hedging policy. |
| 7 | Financial analysis — base case | 3–4 | P&L / cash-flow summary, levered & unlevered IRR, equity MOIC, DSCR (avg & min), LLCR, payback, NPV at WACC. |
| 8 | Sensitivities & downside | 3 | Tornado, scenario grid (min 9 cells), break-even analysis, Monte Carlo summary (P10/P50/P90), minimum-acceptable-return under downside. |
| 9 | Risk matrix | 2 | 15–25 rows, each with likelihood × impact × residual, owner, mitigation, linkage to CP/CS. |
| 10 | ESG, BNG, Just Transition | 1–2 | 10% BNG plan + cost line, Scope 1-3 for site, community benefit (CBS), TCFD alignment, SFDR article classification if fund is EU-registered. |
| 11 | Legal & regulatory | 2 | Planning (EN-1 / EN-3 2025 compliance), permits, grid connection legal, land (option, lease, freehold, restrictive covenants), change-of-control, subsidy control. |
| 12 | Technical & operational | 2 | ICE-member ITA sign-off, yield assessment (P50/P90 from P&P-grade resource), availability warranty, O&M counterparty, DNO/TO flexibility contracts. |
| 13 | Precedent transactions | 1–2 | 6–10 UK comparables with £/MW, £/MWh, EV/EBITDA multiples, date, advisor. |
| 14 | Exit / hold | 1 | Base and downside exit year / multiple, re-financing plan, secondaries market read. |
| 15 | Conditions, consents, committee ask | 1 | Specific vote asked, delegated authority, reporting cadence, conditions subsequent. |
| 16 | Annexes | 40–80 | Full model printout, TDDR, legal DD, commercial DD (Cornwall/LCP), insurance, data-room index. |

Body 30–40 pages; Annex 40–80 pages. A memo thicker than ~45 pages of body signals the team has not done the synthesis work.

Public/indicative references: Real Estate Financial Modeling [IC memo components](https://getrefm.com/investment-committee-memorandum-components/); AtlasX [Real Estate IC memo guide](https://atlasx.co/guides-and-resources/investment-committee-memo-for-real-estate-guide); Stanford GSB ["Investment Memos and Decision-Making" (Addepar)](https://longterminvesting.stanford.edu/sites/g/files/sbiybj23856/files/media/file/addepar-investment-memos-and-decision-making.pdf); SERS public [Rubicon Point Partners IC memo (as filed)](https://sers.pa.gov/pdf/Investments/Investment%20Materials/Rubicon-Point-Partners_Fund_Internal_Memo.pdf).

---

## 2. What's Different in 2026 vs Pre-2024

A 2026 memo that looks like a 2023 template fails the first page-turn. The following MUST be explicit, not implicit:

1. **NESO Gate 2 / TMO4+**. Ofgem approved TMO4+ on 15 April 2025; Gate 2 methodology decision OFG1164 published April 2025. Every grid-connected memo must state Gate 2 status, "Ready / Needed / Connected" classification, and CP2030 alignment. ([Ofgem TMO4+ decision](https://www.ofgem.gov.uk/sites/default/files/2025-04/Summary-Decision-Document-TMO4-package.pdf); [Ofgem Gate 2 methodology](https://www.ofgem.gov.uk/sites/default/files/2025-04/Gate-2-Criteria-Methodology-Final-Decision.pdf)).
2. **CfD AR7 (extended 20-year term) and AR8**. AR7 secured 8.4 GW; for the first time CfD terms extended from 15 to 20 years, which improves debt sizing (longer tail) and equity NPV. AR8 consultation live Jan 2026. ([CMS AR8 changes](https://cms-lawnow.com/en/ealerts/2026/01/cfd-allocation-round-8-and-beyond-proposed-changes-to-the-scheme)).
3. **EN-1 / EN-3 (2025)**. In force 6 January 2026. Low-carbon projects relevant for Clean Power 2030 attract Critical National Priority status — presumption in favour of consent. Memos must cite CNP. ([gov.uk EN-3 2025](https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025)).
4. **Planning & Infrastructure Act 2025**. Royal Assent December 2025. Solar NSIP threshold raised 50 → 100 MW. Judicial review paper-permission stage removed. Memos must classify whether project is NSIP-TCPA pivot candidate. ([UK Parliament PIA 2025](https://bills.parliament.uk/bills/3946)).
5. **BNG for NSIPs**. Delayed twice, now applies to applications made on or after 2 November 2026. Memos executing H2 2026 must call out whether BNG applies or is grandfathered; either way a 10% plan + £/ha cost line is expected. ([TLT — BNG for NSIPs defined but delayed](https://www.tlt.com/insights-and-events/insight/infrastructure-planning-blog-46-bng-for-nsips-defined-but-delayed-and-other-news)).
6. **REMA — Reformed National Pricing confirmed July 2025**. Zonal pricing ruled out; SSEP iteration 1 due 2026; Elexon becomes BSC code manager 2026. Merchant assumptions must explicitly reference RNP, not a vestigial zonal sensitivity. ([gov.uk REMA summer update 2025](https://www.gov.uk/government/publications/review-of-electricity-market-arrangements-rema-summer-update-2025/review-of-electricity-market-arrangements-rema-summer-update-2025-accessible-webpage); [Slaughter & May — what RNP means](https://www.slaughterandmay.com/insights/new-insights/rema-update-what-does-reformed-national-pricing-mean/)).
7. **BESS revenue stack collapse and repricing**. Frequency share fell 80% → 20% (2022–2024); wholesale trading now ~50% and forecast to be 60% over asset life; GB BESS revenues £52k/MW/yr in Jan 2026 (25% below 2025 average). Memos must show a 10-year cycling strategy and merchant-to-contracted ratio. ([Modo — Jan 2026](https://modoenergy.com/research/en/me-bess-gb-revenues-january-2026-balancing-mechanism-wholesale-prices-gas-carbon); [Rabobank — evolving revenue stacks](https://www.rabobank.com/knowledge/d011469493-backup-power-for-europe-part-2-the-uk-s-bess-leadership-and-evolving-revenue-stacks)).
8. **RICS Red Book Global Standards 2025** (effective 31 Jan 2025) adds ESG and modelling content; IC memos defer explicitly to RICS "Valuation of Assets in the Commercial Renewable Energy Sector" guidance. ([RICS Red Book Global 2024 PDF](https://www.rics.org/content/dam/ricsglobal/documents/standards/Red-Book-Global-Standards-incorporating-IVS.pdf); [RICS renewable-sector valuation](https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/the-valuation-of-assets-in-the-commercial-renewable-energy-sector)).
9. **National Wealth Fund** (ex-UKIB). If co-investment sought, memo must show additionality test per NWF investment principles. ([UKIB framework](https://assets.publishing.service.gov.uk/media/656dfdb00f12ef07a53e01d4/UK_Infrastructure_Bank_Framework_Document.pdf)).

---

## 3. Quant Treatment Expected (IC Will Redo These)

The IC team typically rebuilds 3–6 numbers before sign-off. If your model doesn't produce these cleanly, the analyst flags back — bad signal.

| Quant | Form expected | Sophistication marker |
|---|---|---|
| Base-case levered equity IRR | Annual + quarterly cash flows, min 25-year horizon (solar), 15-year (BESS with augmentation), 25-year (DC). | Post-tax, post-curtailment, with explicit tax-equity / capital-allowance timing. |
| DSCR stress | Min DSCR, avg DSCR, 1-in-X year test. Shown under base + 5 downside cases. | Banks expect avg DSCR ≥ 1.35x for CfD solar, ≥ 1.50x for merchant, ≥ 1.60x for BESS. |
| LLCR & PLCR | Separate line, across full debt tenor. | Stressed at lender downside, not sponsor base. |
| Sensitivity tornado | 8–12 variables; ±10% / ±20% on IRR. | Variables ordered by sensitivity, with P50 input value shown on bar. |
| 9-cell scenario grid | Power price × capex × availability, or for BESS: spread × cycling × augmentation cost. | Each cell shows IRR + min DSCR + payback. |
| Monte Carlo | 5 000–10 000 runs, P10/P50/P90 on IRR and DSCR. | Correlated drivers (price & demand not independent); solar yield uses P&P-grade exceedance. |
| Break-even | Price, capex, availability values at which equity IRR = WACC and DSCR = 1.00x. | Shown as % shock and as absolute value. |
| BESS revenue stack | Wholesale / BM / ancillary / capacity-market bars by year. | Cites source (Modo, LCP Delta, Cornwall); shows augmentation capex triggered at SoH 80%. |
| PPA vs merchant split | % contracted vs merchant, hedge ratio by year. | Counterparty credit rating + collateral package called out. |
| Curtailment | Expected % by year (grid + economic). | Split into 'constraint' and 'negative-price' curtailment; linked to REMA RNP. |
| Reinforcement contribution | £/MW, timing, cost-sharing per TMO4+ rules. | Shown in CapEx and separately as sensitivity. |

---

## 4. The Five Red-Flag Sections — Sophistication Ladder

These are the five an experienced IC chair flicks to first. "Basic" is what a junior analyst produces; "IC-grade" is what a seasoned MD signs.

**(a) Risk matrix.**
- Basic: 10–12 rows, colour-coded, no owner.
- Intermediate: 20 rows, likelihood × impact × residual, owner per row.
- IC-grade: 20–25 rows, each risk mapped to a CP, CS, insurance clause, or covenant; residual risk shown after mitigation; top-5 extracted into the exec summary with a traffic light.

**(b) Downside case.**
- Basic: Single 10% revenue haircut.
- Intermediate: 3 downsides (revenue, capex, delay) shown separately.
- IC-grade: Lender case (revenue -20%, capex +10%, availability -3pp, 6-month delay, WACC +100 bps) applied in combination; min DSCR and equity IRR shown under combined stress; break-even shock named.

**(c) Key assumptions.**
- Basic: Table of 30 inputs.
- Intermediate: Inputs with source citation.
- IC-grade: Inputs with source, date-stamp, last-review date, and confidence band; distinguishes hard-contracted (offtake price) from modelled (inflation, merchant curve) from technical (P50 yield).

**(d) Sensitivity tornado.**
- Basic: Excel one-at-a-time ±10% on 6 variables.
- Intermediate: 12 variables, ±20%, sorted by sensitivity.
- IC-grade: Tornado + 2D heat-map (price × availability), 9-cell scenario table, Monte Carlo P10/P50/P90, with which drivers correlate highlighted.

**(e) Covenant package.**
- Basic: Lists DSCR covenant.
- Intermediate: DSCR, LLCR, distribution lock-up, restricted payments.
- IC-grade: Full LMA-grade ratios table, headroom in % and £, hardening / cure mechanics, forecast quarterly DSCR across tenor, historic-vs-forecast test, equity cure mechanic, reserve accounts (DSRA, MRA), cash sweep trigger, cross-default, change-of-control.

---

## 5. Tone & Visual Conventions

- **Data density**: 1 chart or table per page on average. More than 2 charts signals a pitch; none signals a junior analyst.
- **Font / layout**: 10–11pt serif (Times/Garamond) for body, sans-serif for tables; Macquarie house uses bold coloured headlines and grey running text; Rothschild notably understated, few colours, numbers-driven; CBRE IM is chart-heavy, photographs of site.
- **Footnotes**: dense. Every number cites a model cell reference (e.g. `[FM §4.3, L147]`) or external source (e.g. `Cornwall Insight Central, Jan 2026`). Absence of footnotes is a tell.
- **Provenance**: every external data point date-stamped. 2025 data is too stale in an April 2026 memo for power prices, grid queue, or BESS spreads.
- **Recommendation box on page 1**: vote asked, ticket, preconditions. Mandatory.
- **No emojis, no superlatives, no marketing adjectives**. "Strong" and "attractive" are red pen words — replaced by a number.
- **"What could make us wrong"**: an explicit 3-bullet section some houses add before the recommendation. Macquarie and Actis use it.

---

## 6. Princeps Gap Analysis vs `utils/lender_pack_sections/`

Princeps today produces a *lender* pack (debt framing). It is strong on s04/s05/s07/s08/s14 for debt purposes but under-indexed for *equity* IC. The mapping below is honest.

| Princeps file | Lender-pack adequacy | IC memo gap |
|---|---|---|
| `s01_cover.py` — cover + reliance | Strong — LMA / RICS aware. | Missing: recommendation box, vote ask, ticket size, delegated authority. Add an `ic_cover` variant. |
| `s02_transaction.py` — transaction summary | OK for debt. | Missing: M&A structure detail (share-vs-asset, locked-box vs completion accounts, W&I insurance structure). |
| `s03_sources_uses.py` — sources & uses | Adequate. | Missing: tax-equity and capital allowances, hold-co vs op-co flows, management roll-over equity. |
| `s04_base_case.py` — base case | Solid DSCR/IRR/LLCR. | Missing: equity MOIC / DPI / payback explicitly; CfD 20-year tail under AR7 not wired; REMA RNP curtailment not in revenue build. |
| `s05_downside.py` — downside case | Shocks applied individually. | **Combined lender-case** (rev -20%, capex +10%, avail -3pp, delay, WACC +100 bps) not produced as a single cell. |
| `s06_breakeven.py` — break-even | Strong (bisection solver). | Missing: break-even availability and break-even augmentation capex for BESS. |
| `s07_covenants.py` — covenant package | Good — ratios, lock-ups. | Missing: cash sweep trigger, equity-cure mechanic, hardening clause, reserve account sizing logic. |
| `s08_mel.py` — material event list / risks | 246 lines, best-in-class for the pack. | Missing: explicit mapping risk → CP → insurance → covenant → residual. Add a `linked_to` field. |
| `s09_tddr.py` — technical due diligence | Default ITA template. | Missing: ICE-grade / MCS / RenewableUK accreditation statement on the ITA signatory; P99 yield and SoH trajectory for BESS. |
| `s10_cp.py` — conditions precedent | Thin (29 lines). | Major gap: needs 2026 regulatory CPs: Gate 2 offer, TMO4+ milestone, AR7 strike, BNG plan (post-Nov 2026), DCO if NSIP. |
| `s11_cs.py` — conditions subsequent | Thin (25 lines). | Same as s10. |
| `s12_precedents.py` — precedents | 35 lines — placeholder. | **Major gap**: needs a maintained UK comps database (Cleve Hill, Eni Plenitude, Statkraft, NTR, Octopus, Cubico, Island Green Power) with £/MW, £/MWh, EV/EBITDA, date, advisor. |
| `s13_security.py` — security structure | Adequate — share pledge, debenture. | Missing: direct agreements with grid (DNO/TO), offtaker, EPC step-in; environmental liability bond. |
| `s14_model_audit.py` — model audit | Strong — rebuild, stress. | Missing: ICAEW / BAI modelling accreditation tag; sensitivity-coverage test. |
| `s15_signature.py` — signature | Fine. | Fine. |

### Additional IC-memo-only sections Princeps has no file for yet:
- `s00_recommendation` — page-1 box with verdict, IRR, DSCR, ticket, vote ask.
- `s_exec_summary` — 2-page narrative before s02.
- `s_market_thesis` — market curve, FES pathway, comps pipeline.
- `s_esg_bng` — 10% BNG plan, Scope 1-3, Just Transition, TCFD/SFDR.
- `s_monte_carlo` — 10 000-run simulation P10/P50/P90 feed from s05.
- `s_exit` — base and downside exit, refinance, secondaries.
- `s_committee_ask` — explicit vote, delegated authority, reporting cadence.

### Five biggest gaps (what to build first, in priority order):

1. **Recommendation + exec-summary layer** (new `s00_recommendation`, `s_exec_summary`). Without these, a Princeps pack does not look like an IC memo at all — it looks like a lender pack. Low effort, high visibility.
2. **Combined lender / IC downside case in `s05_downside.py`**. Currently shocks are orthogonal; an IC memo needs them applied together and labelled "Lender Case" and "Sponsor Sensitivity Case".
3. **2026-regulatory CP/CS upgrade in `s10_cp.py` / `s11_cs.py`**. Must emit Gate 2, TMO4+, CfD AR7/AR8, BNG-for-NSIPs, DCO (EN-1/EN-3 2025), REMA RNP triggers. Templates at the top of each file are 2023 vintage.
4. **Monte Carlo + 9-cell scenario grid** (new `s_monte_carlo`, extends `s05`). 10 000 runs with correlated drivers; P10/P50/P90 into a waterfall. This is the single most visible intermediate-to-IC-grade upgrade.
5. **Precedent comps database in `s12_precedents.py`**. Current 35 lines are placeholder. Build a maintained (monthly-refreshed) UK comp set with £/MW, £/MWh, EV/EBITDA, date, advisor — the IC chair will check this first.

Honourable mentions: ESG/BNG section (new file), equity-specific covenant/waterfall content, ITA accreditation tagging in s09, reserves/equity-cure mechanics in s07.

---

## Confidence

- Section-by-section spec (§1): **High** — triangulated from REFM, AtlasX, Stanford/Addepar, and a publicly-filed SERS IC memo.
- 2026 regulatory requirements (§2): **High** — all citations are primary (gov.uk, Ofgem, Parliament, RICS, Modo).
- Quant-treatment table (§3): **High** for the list, **medium** on exact DSCR thresholds (vary by lender and technology — thresholds cited are market-typical not universal).
- Red-flag sophistication ladder (§4): **Medium** — based on synthesis of bankability literature + REFM + project-finance textbooks; no single authoritative source.
- Tone & visual conventions (§5): **Medium** — house-style observations drawn from public IM decks and industry commentary; not every firm publishes style guides.
- Princeps-gap analysis (§6): **High** on the file mapping (read the code), **medium** on the priority ordering (judgement call).

---

## Sources

- [Real Estate Financial Modeling — IC memo components](https://getrefm.com/investment-committee-memorandum-components/)
- [AtlasX — Real Estate IC memo guide](https://atlasx.co/guides-and-resources/investment-committee-memo-for-real-estate-guide)
- [Stanford GSB / Addepar — Investment memos & decision-making](https://longterminvesting.stanford.edu/sites/g/files/sbiybj23856/files/media/file/addepar-investment-memos-and-decision-making.pdf)
- [SERS — Rubicon Point Partners IC memo (public)](https://sers.pa.gov/pdf/Investments/Investment%20Materials/Rubicon-Point-Partners_Fund_Internal_Memo.pdf)
- [Ofgem — TMO4+ decision (Apr 2025)](https://www.ofgem.gov.uk/sites/default/files/2025-04/Summary-Decision-Document-TMO4-package.pdf)
- [Ofgem — Gate 2 criteria methodology OFG1164](https://www.ofgem.gov.uk/sites/default/files/2025-04/Gate-2-Criteria-Methodology-Final-Decision.pdf)
- [CMS — AR8 and beyond (Jan 2026)](https://cms-lawnow.com/en/ealerts/2026/01/cfd-allocation-round-8-and-beyond-proposed-changes-to-the-scheme)
- [NESO — AR7 Allocation Process Guidance](https://www.neso.energy/document/365771/download)
- [gov.uk — EN-3 2025 National Policy Statement](https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025)
- [UK Parliament — Planning & Infrastructure Act 2025](https://bills.parliament.uk/bills/3946)
- [TLT — BNG for NSIPs defined but delayed](https://www.tlt.com/insights-and-events/insight/infrastructure-planning-blog-46-bng-for-nsips-defined-but-delayed-and-other-news)
- [gov.uk — REMA summer update 2025 (RNP confirmed)](https://www.gov.uk/government/publications/review-of-electricity-market-arrangements-rema-summer-update-2025/review-of-electricity-market-arrangements-rema-summer-update-2025-accessible-webpage)
- [Slaughter & May — What RNP means](https://www.slaughterandmay.com/insights/new-insights/rema-update-what-does-reformed-national-pricing-mean/)
- [Modo Energy — GB BESS revenues Jan 2026](https://modoenergy.com/research/en/me-bess-gb-revenues-january-2026-balancing-mechanism-wholesale-prices-gas-carbon)
- [Rabobank — UK BESS leadership & evolving revenue stacks](https://www.rabobank.com/knowledge/d011469493-backup-power-for-europe-part-2-the-uk-s-bess-leadership-and-evolving-revenue-stacks)
- [RICS — Red Book Global Standards 2025 PDF](https://www.rics.org/content/dam/ricsglobal/documents/standards/Red-Book-Global-Standards-incorporating-IVS.pdf)
- [RICS — Valuation of assets in the commercial renewable energy sector](https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/the-valuation-of-assets-in-the-commercial-renewable-energy-sector)
- [UKIB (now NWF) — Framework Document](https://assets.publishing.service.gov.uk/media/656dfdb00f12ef07a53e01d4/UK_Infrastructure_Bank_Framework_Document.pdf)
- [Augusta & Co — firm overview](https://augustaco.com/)
- [Mizuho — acquisition of Augusta & Co (2025)](https://www.mizuhogroup.com/emea/news/2025/mizuho-to-acquire-leading-independent-european-financial-advisory-firm-in-the-renewable-energy-and-energy-transition-sector-augusta--co.html)
- [Bryan Cave Leighton Paisner — UK data centre M&A](https://www.bclplaw.com/en-US/events-insights-news/unlocking-value-in-uk-data-centre-manda-transactions.html)
- [Lexology — data centre grid connection regime](https://www.lexology.com/library/detail.aspx?g=d5282ffa-b29f-4a58-ba90-9d6395f819aa)
- [Quinbrook — Cleve Hill financial close (2025)](https://www.businesswire.com/news/home/20250314679302/en/Quinbrook-Closes-UKs-Largest-Solar-PV-Battery-Storage-Project-Financing-for-Cleve-Hill-Solar-Park)
- [Elgar Middleton — UK BESS market 2026](https://www.elgarmiddleton.com/the-uk-bess-market-in-2026/)
- [IIGCC — UK climate & nature policy 2026](https://www.iigcc.org/insights/uk-climate-and-nature-policy-2026)
- [PwC — Bankability issues for renewables](https://www.pwc.com.au/energy-transition/papers/11-bankability-issues-renewable-energy-projects.pdf)
- [IRENA — Five pillars of renewables bankability](https://www.irena.org/News/expertinsights/2024/Apr/Five-Pillars-That-Determine-Commercial-Renewables-Projects-Bankability)
