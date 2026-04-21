# Squid Energy - Integration Decision

**Author:** BOT-SE
**Date:** 2026-04-19
**Input:** `/Users/anyatrofimova/feasibly/docs/competitive/squid_energy.md` (RESEARCH-1 brief)
**Status:** Decision draft for founder review

---

## 1. Decision: **MONITOR-ONLY, with a lightweight co-marketing reach-out (Shape C lite)**

Not "integrate" and not "ignore". Princeps should not invest engineering cycles in a technical integration with Squid in Q2 2026, but it should open a human channel now because the founder overlap (National Grid / Octopus / YC) is a high-signal network and because a future Squid developer-portal product would flip the relationship from complementary to competitive within a quarter.

### Three reasons

1. **No public API yet.** Squid ships browser SaaS (FlexPortal + CIM Explorer). There is no documented partner API, no SDK, no GitHub org. Any "integration" today would require a bilateral design-partner contract, which is a 2-3 month sales cycle on their side for a 2-person YC-batch company that is still building out its first customer (NGED). The effort-to-value is wrong for Princeps at pre-seed.
2. **Opposite sides of the table.** Squid sells into DSOs (the people granting connections). Princeps sells to developers (the people applying). A deep technical integration would require either Squid to expose NGED's CIM model to third-party developers (a governance decision that sits with NGED, not Squid) or Princeps to push G99 applications into a pipe Squid has not built. Neither is a decision Princeps can force.
3. **Latent competitive risk is real.** The RESEARCH-1 brief flagged the developer-portal scenario: if Squid extends CIM Explorer into a connection-applicant workflow, overlap jumps from ~10% to ~60%. Princeps should talk to them precisely so we have the relationship and early warning, not so we ship code against a moving target.

---

## 2. Three integration shapes - ranked

### Shape C (RECOMMENDED) - Co-marketing / referral partnership. **Effort: Low. Value: Medium.**

Both companies gain from a smoother end-to-end story: a Princeps developer user who lodges a G99 into an NGED licence area where the DSO planner is already using Squid's CIM Explorer gets a faster, better-evidenced response. The ask is a joint blog post, a co-authored Current-News piece, and a mutual referral ("if you're a developer, try Princeps; if you're a DNO, try Squid"). No code. No legal beyond a one-page MoU.

### Shape B (DEFER to Q4 2026) - Squid as a data source into Princeps. **Effort: Medium. Value: Medium-High.**

If Squid ever publishes read-only access to the CIM-derived substation + headroom dataset they built for NGED, it would beat Princeps' current OSM + OpenDataSoft ingestion on accuracy for the NGED licence area. Target code surface: `utils/grid_data_ingester.py` (add a `SquidCIMAdapter` alongside the OpenDataSoft + CKAN adapters) and `utils/grid_connection_analyser.py` (use Squid headroom data as Tier 1.5 between current Tier 1 and pandapower Tier 2). Blocked today because no public read API exists.

### Shape A (DEFER indefinitely) - Princeps as a data producer into Squid. **Effort: High. Value: Low for Princeps.**

Pushing G99 site metadata into a Squid-compatible feed is interesting for a DSO, but the value accrues to Squid (they get a richer dataset) and to the DSO, not to the Princeps user. Only worth doing if a specific DSO customer pays for it. File it under "RFP response material" not "roadmap".

---

## 3. Recommended shape (C) - concrete plan

### Target Princeps code surface
- **None in Q2 2026.** This is a GTM action, not an engineering action.
- Optional Q3: add a `partner_dsos` hint in `utils/grid_connection_analyser.py` that, when the POC falls in NGED's licence area, appends a line to the Grid Connection PDF: "NGED publishes live flex + network data via FlexPortal (partner: Squid Energy)." This is a one-line insertion in the PDF template, not a code integration.

### Expected API shape on Squid's side (speculative)
- **Current:** none public. CIM Explorer is an authenticated NGED-internal tool. FlexPortal is public HTML at `dso.nationalgrid.co.uk/flexportal` but has no documented JSON endpoint.
- **Plausible future:** a read-only REST endpoint returning CIM-formatted substation + line records, likely at `api.squid.energy/v1/network/{dso}/substations/{mrid}`. Auth probably OAuth2 client-credentials. Speculation - confirm in discovery.

### 5-line JSON payload sketch (for eventual Shape A / B handshake)

```json
{
  "princeps_application_id": "PRN-2026-04-00123",
  "poc": {"lat": 52.4581, "lon": -1.9290, "srid": 4326},
  "capacity_mw": 49.9,
  "tech": "solar_pv_bess",
  "expected_energisation": "2028-Q3",
  "evidence": {"repd_id": null, "design_canvas_hash": "sha256:..."}
}
```

### 4-week engagement plan

- **Week 1 (outreach):** Anya emails `hello@squid.energy` using the Appendix A draft. Cold-connect on LinkedIn to Conor Jones (CEO, ex-National Grid / Octopus / BCG) and George Kolokotronis (CTO, ex-Octopus). Goal: 30-min founder-to-founder call.
- **Week 2 (technical discovery):** If Week 1 lands a call, scope three questions: (a) is there any partner API roadmap, (b) would they co-author a Current-News piece, (c) would NGED be open to a joint pilot where a Princeps developer user's application is visible to their planner inside CIM Explorer. No NDA yet.
- **Week 3 (MoU draft):** If discovery goes well, one-page mutual referral MoU. No revenue share. Just: "we will list each other on a partners page and co-author one piece of content this quarter."
- **Week 4 (content drop):** Publish a joint LinkedIn post + Current-News pitch framed as "the two sides of the connection queue". Measure: inbound referrals, landing-page clicks, and whether Squid name-checks Princeps to any of its DSO prospects.

---

## 4. Monitor-only path - trigger signals

Revisit the integrate-vs-don't debate when any one of these fires:

1. **Squid publishes a public partner API** (any endpoint, documented, auth scheme declared). Re-evaluate Shape B immediately.
2. **Squid raises a Series A** (public round, any lead). Signals product expansion; check the roadmap language for "developer portal", "connection applicant", or "queue management" - those are the competitive-pivot tell.
3. **Squid wins a second DSO** (anyone beyond NGED). Signals they are scaling horizontally across operators, making their data layer more valuable to Princeps as a data source.
4. **A competitor (Envision Greenwich, Build.inc, Glint, Arup) announces an integration with Squid.** Forces a response - silence equals ceding the narrative.
5. **NGED publishes a developer-facing API derived from CIM Explorer.** Effectively Shape B becomes free; build the adapter.
6. **Squid posts a job for a "developer experience" or "API platform" engineer.** Soft signal, but usually precedes a public API by 3-6 months.

Set a quarterly calendar reminder to re-scan their blog, LinkedIn, YC profile, and Companies House filings.

---

## Appendix A - Outreach email draft

> **To:** hello@squid.energy
> **Cc:** conor@squid.energy (if findable)
> **Subject:** Princeps <> Squid - the other side of the connection queue
>
> Hi Conor, George,
>
> I'm Anya, founder of Princeps (princeps.energy). We're the developer-side mirror of what you're building at Squid: we sit with DC, solar and BESS developers on their pre-FID grid-connection studies, while you sit with the DSO planners on the other side of the same application.
>
> Saw the NGED FlexPortal + CIM Explorer work - impressive turnaround from YC W26 to a live NGED product. Congrats.
>
> Two reasons to talk:
> 1. Our users apply into DNOs; your users grant those applications. A co-authored "both sides of the queue" piece on Current-News would write itself and we'd both get inbound.
> 2. If NGED eventually opens a read API on the CIM-derived network data, we'd be a natural first consumer - our grid_connection_analyser currently stitches OpenDataSoft + CKAN + OSM, and your dataset would be materially better.
>
> 30 minutes next week? Happy to jump on a call at a time that works on either coast.
>
> Anya
> anya@princeps.energy

---

**Decision owner:** Anya
**Review date:** 2026-07-19 (Q3 quarterly trigger check)
