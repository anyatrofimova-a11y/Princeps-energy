# Competitive Brief: Squid (squid.energy)

**Research date:** 2026-04-19
**Researcher:** RESEARCH-1 (time-boxed, 15 min)
**Confidence:** Medium-High on product/positioning (public site + press), Low on funding (undisclosed beyond YC).

> Disambiguation: multiple companies share the name "Squid Energy". The target here is the **YC W26 AI grid-planning startup** at `squid.energy`, operating as **Squid Labs Ltd** (UK #16925647) and **Squid Group, Inc.** (Delaware #10438212). It is NOT:
> - Squid Energy Limited (UK #15341220) — dissolved solar equipment firm, May 2025.
> - Squid (squidrouter / crypto cross-chain swaps, $7.5M raised).
> - Squid AI / squid-cloud (realtime data platform, $26M from Norwest).

---

## 1. Who they are

- **Founders:** Conor Jones (CEO, ex-National Grid, Octopus Energy, BCG) and George Kolokotronis (CTO, ex-Octopus Energy Head of Tech, AWS, Cambridge). [YC profile](https://www.ycombinator.com/companies/squid), [Squid about page](https://www.squid.energy/about)
- **Founded:** Late 2025 / early 2026 — participated in **Y Combinator W26** batch (Demo Day March 2026). [YC launch](https://www.ycombinator.com/launches/PHP-squid-ai-powered-grid-planning-in-your-browser)
- **HQ:** Dual presence — **London + San Francisco**. Legal: Squid Labs Ltd (UK) + Squid Group, Inc. (Delaware). [About page](https://www.squid.energy/about)
- **Team size:** 2 founders listed on YC; hiring via Work-at-a-Startup. No other employees named publicly.
- **Funding:** Only **YC W26 standard package** ($500k SAFE) publicly disclosed. No seed round announced as of 2026-04-19. Crunchbase/PitchBook entries for this specific entity are sparse. [YC companies](https://www.ycombinator.com/companies/squid)
- **Certifications:** SOC 2 Type II + ISO 27001 claimed on homepage — unusually mature for a 2-person YC-batch company, suggests they inherited or fast-tracked via a compliance-as-a-service vendor. [squid.energy](https://www.squid.energy/)

## 2. Product — what they actually sell

Browser-based AI grid-planning workspace. Core framing: "Model the network. Test the stress. Unlock progress." [squid.energy](https://www.squid.energy/)

**Core capabilities pitched:**
- Unified, **live versioned network model** — substations, lines, evidence attached.
- **Model version control** — changes are trackable, comparable, with an audit trail.
- **Evidence + assumptions** attached to every node/decision (fights the "lives in decks and spreadsheets" problem).
- **Repeatable workflows** for planning and connections teams.
- **Stress testing** / scenario runs inside the browser.
- **Flexibility-market data visualization** (productised as FlexPortal for NGED DSO).
- **CIM Explorer** — converts NGED's CIM (Common Information Model) network model into a visual/interactive UI that non-modellers can navigate. [The Energyst](https://theenergyst.com/national-grid-dso-partners-with-squid-to-improve-accessibility-of-electricity-network-data/)

**What the software looks like (from the landing page):** interactive data visualisation of grid assets, flex-market dashboards, a map-forward UX. No public demo link; design partners are invited via `hello@squid.energy`. No GitHub org public.

## 3. Positioning

- **Customer side:** **grid operators / DSOs / TSOs** — specifically "planning, connections, modelling, GIS, asset strategy" teams. This is **sell-to-utility**, not sell-to-developer. [YC launch](https://www.ycombinator.com/launches/PHP-squid-ai-powered-grid-planning-in-your-browser)
- **Asset type:** **technology-agnostic** — they don't mention solar, BESS, or DC specifically. It's grid-infrastructure-first, which includes all demand and generation connecting to it.
- **Geo:** UK anchor (National Grid DSO live), US ambition (SF office). Global TAM pitch.
- **Model:** **Product-led SaaS with consulting-flavoured onboarding** (design-partner motion). Not pure consulting.

## 4. Customer segments / named customers

- **National Grid DSO (NGED)** — confirmed partner. Squid built **FlexPortal** (public-facing flex-market transparency portal) and **CIM Explorer** (internal/stakeholder network-model browser) for them. Launched Feb 2026. [Energy Live News](https://www.energylivenews.com/2026/02/12/national-grid-dso-launches-interactive-flexportal-to-boost-transparency/), [NGED news](https://dso.nationalgrid.co.uk/news-and-events/latest-news/national-grid-dso-launch-new-interactive-flexportal)
- **Testimonial:** Doerte Schneemann, Head of Flexibility Markets, National Grid DSO: "For too long flex data lived in spreadsheets. Not anymore!" [squid.energy](https://www.squid.energy/)
- No other named customers. Actively recruiting design partners at other DNOs/ISOs.

## 5. Output format / deliverables

Based on FlexPortal + CIM Explorer and landing-page copy, deliverables are **live interactive web apps**, not PDFs or static memos:
- **FlexPortal:** dynamic, data-rich exploration of dispatch, participation, tender outcomes — replaces a PDF quarterly report. Public URL under `dso.nationalgrid.co.uk`.
- **CIM Explorer:** visual interactive interface over a CIM-formatted network model — map + data panels, navigable without modelling expertise.
- **Workspace:** versioned network model with attached evidence — feels like a GIS/Notion hybrid for grid teams.

No PDFs, no Word memos, no one-off reports surfaced. Entire delivery is SaaS dashboard.

## 6. Overlap with Princeps

| Dimension | Princeps | Squid | Overlap? |
|---|---|---|---|
| **Buyer** | DC / solar / BESS **developers** (pre-FID) | **DNOs / TSOs / grid operators** | **Low — opposite side of the table** |
| **Asset focus** | DC + solar + BESS siting + feasibility | Grid network itself (substations, lines, flex) | Low — adjacent |
| **Deliverable** | Pre-FID grid-connection + financial + planning **reports + 3D twin** | Live web workspace for grid planners | Medium (both map + twin UX) |
| **Geography** | UK-first | UK + US | Medium |
| **Tech stack** | PostGIS + FastAPI + deck.gl + SAM + pandapower + Claude | Not disclosed; browser-based, likely React + modern data layer | Overlap: both do versioned grid models, PF analysis |
| **Competitive** | Developer-facing siting + grid-connection narrative | Utility-facing network-operations narrative | **Indirect — could become direct if Squid ships a developer-portal module** |

**Direct competition today:** roughly none. **Latent competition:** if Squid adds a "developer connection-application module" (logical extension — their CIM Explorer could serve queue applicants), they move into Princeps' grid-connection-study territory. Conversely, if Princeps opens up its grid-data layer to DNOs as a product, it competes with CIM Explorer.

**Complementary angle:** Princeps already ingests DNO OpenDataSoft + CKAN feeds; if a DSO adopts Squid as its system-of-record for network data, Squid becomes a potential **upstream data source / integration partner** for Princeps.

## 7. What Princeps should copy — and differentiate against

### Copy (3)
1. **Versioned-model-as-first-class-citizen framing.** Squid's pitch ("one trusted model, versioned, with evidence attached") is a very tight narrative that resonates with enterprise buyers. Princeps has the pieces (PostGIS + JSONB + grid_assessments table) but doesn't marketing-lead with "versioned, auditable, evidenced." Steal the framing for the grid-connection PDF + DC designer.
2. **Public reference customer early.** Squid parlayed one NGED design partnership into a landing-page testimonial + two press pieces (Energyst, Energy Live News) within ~3 months. Princeps should turn the first beta user into a cited testimonial + co-branded case study immediately — worth more than a second feature.
3. **Evidence-attachment pattern in the UI.** Every node in Squid's model has assumptions + source docs attached. Princeps should mirror this in the DesignCanvas / agent verdict rail — every GO/CAUTION/NO-GO should cite the REPD row, the NSIP decision, the DNO capacity-map record it rests on. Already partially there via reasoning popover; push harder.

### Differentiate against (3)
1. **Stay developer-side, hard.** Squid is utility-side and will keep drifting there (CIM, flex markets, asset strategy). Princeps' wedge is the **developer / IPP / hyperscaler pre-FID** buyer who needs outputs DNOs will accept. Don't chase DSO RFPs — that's a 12-month procurement cycle Princeps can't fund.
2. **Own the PDF deliverable.** Squid is all-SaaS dashboard. Planning officers, credit committees, and landowners still need **signable PDFs**. Princeps' Grid Connection PDF + Financial Viability PDF are a moat; double down on paperwork-grade output (already in `docs/paperwork_style_guide.md`).
3. **Physics + finance + planning in one stack.** Squid's depth is grid topology. Princeps' depth is the **cross-domain join**: SAM yield × pandapower power flow × REPD planning ML × Prophet/TFT demand × financial P10/P50/P90. Squid would need 4 more hires and 18 months to touch that breadth. Lead with "end-to-end feasibility, not a grid viewer."

---

## What Princeps should do (3 bullets)

- **Frame Princeps as the developer-side mirror of Squid.** Both tell the "one versioned model, evidence attached" story; Princeps tells it to the people *applying* for connections, Squid to the people *granting* them. That's a cleaner pitch for both investors and buyers than "grid-connection tool".
- **Ship a public case study on the first beta user within 30 days of onboarding.** Squid did this with NGED before they had a seed round. It is the single highest-ROI marketing action at pre-seed stage.
- **Watch for a Squid "developer portal" product launch.** If they ship one, overlap goes from ~10% to ~60% within a quarter. Set a quarterly check on their blog + LinkedIn.

---

## Sources

- [Squid — YC profile](https://www.ycombinator.com/companies/squid)
- [Squid — YC launch announcement](https://www.ycombinator.com/launches/PHP-squid-ai-powered-grid-planning-in-your-browser)
- [squid.energy homepage](https://www.squid.energy/)
- [squid.energy — About](https://www.squid.energy/about)
- [The Energyst — NGED + Squid CIM Explorer partnership](https://theenergyst.com/national-grid-dso-partners-with-squid-to-improve-accessibility-of-electricity-network-data/)
- [Energy Live News — NGED FlexPortal launch (Feb 2026)](https://www.energylivenews.com/2026/02/12/national-grid-dso-launches-interactive-flexportal-to-boost-transparency/)
- [NGED DSO — FlexPortal news](https://dso.nationalgrid.co.uk/news-and-events/latest-news/national-grid-dso-launch-new-interactive-flexportal)
- [Extruct AI — YC W26 batch breakdown](https://www.extruct.ai/research/ycw26/)
- [UK Companies House — Squid Energy Limited #15341220 (dissolved, unrelated)](https://find-and-update.company-information.service.gov.uk/company/15341220)
