"""
app/alerts/seed.py — Princeps Alerts council catalogue (84 UK SKUs).

Shape of each row is the ``alert_definitions`` table declared in
``app/migrations/0001_intelligence_schema.sql``:

    slug                 TEXT UNIQUE
    title                TEXT
    description          TEXT
    cluster              TEXT
    source_filter        JSONB  -- matched against documents by digest_worker
    llm_prompt           TEXT   -- passed to Haiku to summarise the batch
    cadence              TEXT   -- 'daily' | 'weekly_mon' | 'weekly_fri' | …
    est_docs_per_digest  INT
    icp_tags             TEXT[]

Cluster breakdown follows the council catalogue cited in the Task #6 spec,
plus the 2 DNO-engagement SKUs added in Task #20 (scoped to the Grid
connection & queue cluster, but project-driven via the
``project_dno_engagements`` / ``dno_engagement_responses`` tables rather
than the generic ``documents`` feed):

  Grid connection & queue .................. 8  (+2 DNO engagement = 10)
  Price controls & codes ................... 6
  Planning & consents ...................... 7
  Data centres & large loads ............... 7
  BESS & storage ........................... 6
  Renewables & CfD ......................... 6
  PPA / offtake ............................ 5
  Capex / investments / M&A ................ 5
  Devolved-nation & regional ............... 5
  Market & settlement ...................... 5
  Safety & compliance ...................... 5
  Environmental ............................ 5
  Company intelligence ..................... 7
  Innovation & NIA/SIF ..................... 5
  ------------------------------------------------
  TOTAL .................................... 84

Seed runs on startup behind ``PRINCEPS_SEED_ALERTS`` (default on in dev).
Idempotent via ``INSERT … ON CONFLICT (slug) DO NOTHING``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.alerts.seed")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

# Each entry: (slug, title, description, cluster, source_filter, llm_prompt,
# cadence, est_docs_per_digest, icp_tags)
# source_filter is a flexible JSON predicate consumed by digest_worker — the
# ingestion workers tag incoming documents with `source`, `filing_type`,
# `topic_tags`, `commission_authority` so these fields line up cleanly.

_CATALOGUE: list[dict[str, Any]] = [
    # ── Grid connection & queue (8) ─────────────────────────────────────────
    {
        "slug": "tec-register-deltas",
        "title": "TEC Register — weekly deltas",
        "description": "New entries, withdrawals and milestone changes on the NESO Transmission Entry Capacity register.",
        "cluster": "Grid connection & queue",
        "source_filter": {"source": "neso_tec", "topic_tags_any": ["tec_register", "queue"]},
        "llm_prompt": "Summarise this week's TEC register changes. For each delta state project name, MW, technology, TO, previous vs new milestone date, and the likely queue-position impact.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 40,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "grid_consultant"],
    },
    {
        "slug": "dno-ecr-weekly",
        "title": "DNO ECR — weekly capacity updates",
        "description": "Embedded Capacity Register changes across all 6 UK DNOs (headroom, new connections, capacity drop-outs).",
        "cluster": "Grid connection & queue",
        "source_filter": {"source_in": ["ngedno", "ukpn", "spen", "ssen", "np", "enwl"], "filing_type": "ecr"},
        "llm_prompt": "Summarise this week's DNO ECR updates: largest headroom changes, new >10MW connections, and substations that flipped from green to amber. Output as a ranked list.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 60,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent", "grid_consultant"],
    },
    {
        "slug": "gate2-offer-decisions",
        "title": "Gate 2 offer decisions",
        "description": "NESO Gate 2 connection-agreement decisions under the reformed queue (from April 2026).",
        "cluster": "Grid connection & queue",
        "source_filter": {"source": "neso", "filing_type_in": ["gate2_offer", "gate2_decision"]},
        "llm_prompt": "List each Gate 2 offer published: project, MW, POC, energisation date, critical dependencies flagged. Highlight any rejections with the stated reason.",
        "cadence": "daily",
        "est_docs_per_digest": 8,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "grid_consultant"],
    },
    {
        "slug": "offer-withdrawals",
        "title": "Offer withdrawals & capacity releases",
        "description": "Connection-offer withdrawals that free up TO/DNO capacity (triggers for queue-jump opportunities).",
        "cluster": "Grid connection & queue",
        "source_filter": {"source_in": ["neso_tec", "ngedno", "ukpn", "spen", "ssen", "np", "enwl"], "topic_tags_any": ["withdrawal", "capacity_release"]},
        "llm_prompt": "Identify each withdrawn connection and quantify the capacity released at the POC. Flag any GSPs where total released MW > 100.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 15,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "grid_consultant", "land_agent"],
    },
    {
        "slug": "large-load-connection-offers",
        "title": "Large-load connection offers (>50MW)",
        "description": "New or revised HV connection offers to >50MW demand sites (data centres, hydrogen, industrial).",
        "cluster": "Grid connection & queue",
        "source_filter": {"topic_tags_any": ["large_load", "hv_demand"], "min_capacity_mw": 50},
        "llm_prompt": "For each >50MW demand offer list the customer (if public), POC, MW, energisation date, security deposit. Highlight any west-London or Scottish corridor sites.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 10,
        "icp_tags": ["dc_dev", "grid_consultant"],
    },
    {
        "slug": "ltds-publication-diff",
        "title": "LTDS publication diff",
        "description": "Annual Long-Term Development Statement diffs: new reinforcements, capacity headroom changes at GSP/BSP.",
        "cluster": "Grid connection & queue",
        "source_filter": {"source": "neso_etys_ltds", "filing_type": "ltds"},
        "llm_prompt": "Diff the latest LTDS against the previous year. List new reinforcements with in-service date, changes to GSP capability, and any region moving from surplus to deficit.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["grid_consultant", "solar_dev", "dc_dev"],
    },
    {
        "slug": "transmission-works-tracker",
        "title": "Transmission works tracker",
        "description": "NGET/SHET/SPT construction milestones, outages, and commissioning dates on the 400/275kV network.",
        "cluster": "Grid connection & queue",
        "source_filter": {"source_in": ["nget", "shet", "spt"], "topic_tags_any": ["construction", "commissioning"]},
        "llm_prompt": "Summarise this week's transmission works: projects energised, delayed, or entering outage. Note impact on connection availability by region.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 12,
        "icp_tags": ["grid_consultant", "solar_dev", "dc_dev"],
    },
    {
        "slug": "firm-nonfirm-split-shifts",
        "title": "Firm / non-firm split shifts",
        "description": "Changes in the firm vs non-firm connection mix at GSP/BSP level, which move curtailment risk.",
        "cluster": "Grid connection & queue",
        "source_filter": {"topic_tags_any": ["firm_offer", "non_firm_offer"]},
        "llm_prompt": "For each GSP where the firm/non-firm mix shifted >10%, state the GSP, previous vs new split, and the expected curtailment-risk impact.",
        "cadence": "monthly",
        "est_docs_per_digest": 20,
        "icp_tags": ["solar_dev", "bess_dev", "grid_consultant"],
    },

    # ── Price controls & codes (6) ──────────────────────────────────────────
    {
        "slug": "riio-ed3-consultation",
        "title": "RIIO-ED3 consultation tracker",
        "description": "Ofgem RIIO-ED3 consultation documents, draft determinations, stakeholder responses.",
        "cluster": "Price controls & codes",
        "source_filter": {"source": "ofgem", "topic_tags_any": ["riio_ed3", "price_control"]},
        "llm_prompt": "Summarise the latest RIIO-ED3 consultation documents: what changed vs the previous draft, which DNOs pushed back, and the timeline for final determinations.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 8,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "rema-implementation",
        "title": "REMA implementation tracker",
        "description": "Review of Electricity Market Arrangements — consultations, decisions, statutory-instrument progress.",
        "cluster": "Price controls & codes",
        "source_filter": {"source_in": ["desnz", "ofgem"], "topic_tags_any": ["rema"]},
        "llm_prompt": "Summarise this week's REMA developments. Flag any firm decisions on locational pricing and the associated transition timetable.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 5,
        "icp_tags": ["grid_consultant", "solar_dev", "bess_dev", "dc_dev"],
    },
    {
        "slug": "bsc-mod-decisions",
        "title": "BSC modification decisions",
        "description": "Elexon / BSC panel modification decisions and P-mod implementation dates.",
        "cluster": "Price controls & codes",
        "source_filter": {"source": "elexon_bsc", "case_type": "bsc_pmod"},
        "llm_prompt": "List each BSC panel decision: mod number, title, decision (approved / rejected / deferred), implementation date, impact on settlement.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 8,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "dcusa-change-proposals",
        "title": "DCUSA change proposals",
        "description": "DCUSA panel change proposals (DCP) affecting use-of-system charges and DNO settlement.",
        "cluster": "Price controls & codes",
        "source_filter": {"source": "dcusa", "case_type": "dcusa_dcp"},
        "llm_prompt": "Summarise this week's DCP activity: new proposals, panel votes, and any cost impact on DUoS charges for generation vs demand connections.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 6,
        "icp_tags": ["grid_consultant", "dc_dev"],
    },
    {
        "slug": "stc-sqss-changes",
        "title": "STC / SQSS changes",
        "description": "System Operator Transmission Code and Security & Quality of Supply Standards changes.",
        "cluster": "Price controls & codes",
        "source_filter": {"source_in": ["neso", "ofgem"], "case_type_in": ["stc", "misc"], "topic_tags_any": ["stc", "sqss"]},
        "llm_prompt": "Summarise STC/SQSS modifications progressing this period, highlighting impacts on transmission planning criteria and N-1 security.",
        "cadence": "monthly",
        "est_docs_per_digest": 4,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "ofgem-open-letters",
        "title": "Ofgem open letters",
        "description": "All Ofgem open letters, including minded-to positions and direction statements.",
        "cluster": "Price controls & codes",
        "source_filter": {"source": "ofgem", "filing_type": "open_letter"},
        "llm_prompt": "List Ofgem open letters this period. For each state the addressees, the regulatory position taken, and the response deadline.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 5,
        "icp_tags": ["grid_consultant", "solar_dev", "bess_dev"],
    },

    # ── Planning & consents (7) ─────────────────────────────────────────────
    {
        "slug": "nsip-dco-applications",
        "title": "NSIP / DCO applications",
        "description": "Nationally Significant Infrastructure Project DCO applications at PINS — acceptance, examination, decision.",
        "cluster": "Planning & consents",
        "source_filter": {"source": "pins_nsip", "case_type": "nsip_dco"},
        "llm_prompt": "Summarise NSIP activity: new applications accepted, Rule 6 letters, Examining Authority recommendations, and SoS decisions. State the statutory deadline for each.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 12,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "land_agent"],
    },
    {
        "slug": "lpa-major-energy-10mw",
        "title": "LPA major energy applications (>10MW)",
        "description": "Local Planning Authority decisions on energy-project applications above 10MW.",
        "cluster": "Planning & consents",
        "source_filter": {"source": "planit_lpa", "min_capacity_mw": 10, "topic_tags_any": ["energy", "solar", "bess", "wind"]},
        "llm_prompt": "List major LPA energy decisions (>10MW): site name, LPA, capacity, technology, decision, reasons. Flag any refused on landscape or heritage grounds.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 25,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent"],
    },
    {
        "slug": "planning-appeals",
        "title": "Planning appeals — energy",
        "description": "Planning Inspectorate appeal decisions on energy projects (solar, BESS, wind).",
        "cluster": "Planning & consents",
        "source_filter": {"source": "pins_appeals", "topic_tags_any": ["solar", "bess", "wind", "energy"]},
        "llm_prompt": "Summarise this period's energy-project planning appeals: decisions, grounds, Inspector reasoning, and any precedent value for comparable schemes.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 10,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent"],
    },
    {
        "slug": "repd-new-entries",
        "title": "REPD — new entries & status moves",
        "description": "Renewable Energy Planning Database new entries and status changes (Submitted → Approved → Operational).",
        "cluster": "Planning & consents",
        "source_filter": {"source": "desnz_repd"},
        "llm_prompt": "List new REPD entries and status transitions. Sort by MW. Call out projects newly at Approved status that should trigger grid-connection follow-ups.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 30,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent", "grid_consultant"],
    },
    {
        "slug": "bng-nsip-filings",
        "title": "BNG on NSIPs",
        "description": "Biodiversity Net Gain reporting now mandatory on NSIPs (May 2026) — track BNG plans in DCO applications.",
        "cluster": "Planning & consents",
        "source_filter": {"source": "pins_nsip", "topic_tags_any": ["bng", "biodiversity_net_gain"]},
        "llm_prompt": "Summarise BNG plans in recent DCO filings: % gain committed, on-site vs off-site delivery, and any Natural England objections.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 6,
        "icp_tags": ["solar_dev", "land_agent"],
    },
    {
        "slug": "dc-planning-20mw",
        "title": "Data-centre planning (>20MW)",
        "description": "LPA and NSIP planning activity on data-centre developments above 20MW site load.",
        "cluster": "Planning & consents",
        "source_filter": {"topic_tags_any": ["data_centre", "hyperscaler"], "min_capacity_mw": 20},
        "llm_prompt": "List DC planning filings >20MW: site, operator (if named), MW load, LPA, decision status. Highlight any within 5km of a 400kV substation.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 8,
        "icp_tags": ["dc_dev", "land_agent"],
    },
    {
        "slug": "bess-planning-filings",
        "title": "BESS planning filings",
        "description": "LPA and NSIP filings for battery energy storage systems — all MW ranges.",
        "cluster": "Planning & consents",
        "source_filter": {"topic_tags_any": ["bess", "battery_storage"]},
        "llm_prompt": "Summarise this week's BESS planning activity: new applications, decisions, duration (hours) where disclosed, and any fire-safety conditions imposed.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 20,
        "icp_tags": ["bess_dev", "land_agent"],
    },

    # ── Data centres & large loads (7) ──────────────────────────────────────
    {
        "slug": "hyperscaler-siting",
        "title": "Hyperscaler siting signals",
        "description": "Aggregated public signals of AWS / Google / Microsoft / Meta / Oracle UK site selection.",
        "cluster": "Data centres & large loads",
        "source_filter": {"topic_tags_any": ["hyperscaler"], "source_in": ["companies_house", "planit_lpa", "ngedno", "ukpn", "spen", "ssen"]},
        "llm_prompt": "Correlate hyperscaler-linked filings across planning, grid, and Companies House. For each cluster name the probable operator and the stage of commitment.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 12,
        "icp_tags": ["dc_dev", "land_agent"],
    },
    {
        "slug": "btm-generation",
        "title": "Behind-the-meter generation",
        "description": "BTM gas / solar / fuel-cell generation filings serving large loads (trips AESO/NESO constrained-connection flows).",
        "cluster": "Data centres & large loads",
        "source_filter": {"topic_tags_any": ["behind_the_meter", "btm", "private_wire"]},
        "llm_prompt": "List BTM generation filings: host load, technology, MW, planning status. Flag any co-located with hyperscaler campuses.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 6,
        "icp_tags": ["dc_dev", "bess_dev"],
    },
    {
        "slug": "dsr-flex-agreements",
        "title": "DSR / flexibility agreements",
        "description": "Large-consumer flexibility and demand-side response tenders / contracts.",
        "cluster": "Data centres & large loads",
        "source_filter": {"topic_tags_any": ["dsr", "flexibility"]},
        "llm_prompt": "Summarise DSR/flex activity: tenders open, contracts awarded, £/MW rates disclosed, and typical duration commitments.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 10,
        "icp_tags": ["dc_dev", "bess_dev"],
    },
    {
        "slug": "liquid-cooling-permits",
        "title": "Liquid-cooling DC permits",
        "description": "EA discharge permits and LLFA drainage consents for liquid-cooled DC builds.",
        "cluster": "Data centres & large loads",
        "source_filter": {"source_in": ["ea_permits", "llfa"], "topic_tags_any": ["liquid_cooling", "data_centre"]},
        "llm_prompt": "List liquid-cooling permit activity: site, permit type, abstraction/discharge volumes, and any consultee objections.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 4,
        "icp_tags": ["dc_dev"],
    },
    {
        "slug": "uk-sovereign-ai-compute",
        "title": "UK Sovereign AI / AIGZ compute signals",
        "description": "Gov-backed AI growth zones and sovereign-compute announcements (Blyth, Culham, Edinburgh and onwards).",
        "cluster": "Data centres & large loads",
        "source_filter": {"source_in": ["desnz", "dsit", "govuk"], "topic_tags_any": ["sovereign_ai", "aigz", "ai_growth_zone"]},
        "llm_prompt": "Summarise UK sovereign-AI / AI Growth Zone announcements: location, capacity, funding, and implied timeline. Flag anchor-tenant commitments.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 5,
        "icp_tags": ["dc_dev", "grid_consultant"],
    },
    {
        "slug": "west-london-power-ceiling",
        "title": "West-London power ceiling tracker",
        "description": "SSEN / NGET West London moratorium updates — capacity unlocks and reinforcement progress.",
        "cluster": "Data centres & large loads",
        "source_filter": {"topic_tags_any": ["west_london_moratorium"]},
        "llm_prompt": "Summarise West London power-ceiling status: any newly freed MW, reinforcement milestones, and affected boroughs.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 3,
        "icp_tags": ["dc_dev", "grid_consultant"],
    },
    {
        "slug": "scottish-dc-corridor",
        "title": "Scottish DC corridor",
        "description": "Scottish data-centre siting — SSEN/SPEN offers, Scottish Government announcements, Section 36 large-load filings.",
        "cluster": "Data centres & large loads",
        "source_filter": {"topic_tags_any": ["scottish_dc", "scotland_datacentre"]},
        "llm_prompt": "Summarise DC activity in Scotland: new siting signals, SSEN/SPEN offers, planning status. Flag anything north of the B6 boundary.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 4,
        "icp_tags": ["dc_dev"],
    },

    # ── BESS & storage (6) ──────────────────────────────────────────────────
    {
        "slug": "capacity-market-auctions",
        "title": "Capacity Market auctions",
        "description": "T-1 and T-4 Capacity Market pre-qualification, auction results, and contract notifications.",
        "cluster": "BESS & storage",
        "source_filter": {"source": "desnz_cm", "case_type": "cm_auction"},
        "llm_prompt": "Summarise CM auction activity: clearing prices by zone, BESS vs gas derating factors, storage-weighted awards.",
        "cadence": "daily",
        "est_docs_per_digest": 6,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "ldes-cap-and-floor",
        "title": "LDES cap-and-floor scheme",
        "description": "Long-duration electricity storage cap-and-floor consultations, project windows, technical discussion notes.",
        "cluster": "BESS & storage",
        "source_filter": {"source_in": ["ofgem", "desnz"], "topic_tags_any": ["ldes", "cap_and_floor"]},
        "llm_prompt": "Summarise LDES cap-and-floor activity: consultation windows, technical-decision updates, and project pipeline implications.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 4,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "ar7-storage-eligible",
        "title": "AR7 — storage-eligible parameters",
        "description": "CfD AR7 storage/hybrid eligibility updates, parameters, draft allocation framework.",
        "cluster": "BESS & storage",
        "source_filter": {"source": "desnz_cfd", "topic_tags_any": ["ar7", "storage_eligibility"]},
        "llm_prompt": "Summarise AR7 developments relevant to storage and hybrids: eligibility rules, strike-price ranges, and allocation-framework deadlines.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 3,
        "icp_tags": ["bess_dev", "solar_dev"],
    },
    {
        "slug": "colocation-filings",
        "title": "Solar + BESS co-location filings",
        "description": "Planning and connection filings for co-located solar + BESS schemes.",
        "cluster": "BESS & storage",
        "source_filter": {"topic_tags_any": ["colocation", "solar_plus_bess"]},
        "llm_prompt": "List co-location filings: site, solar MW, BESS MW/MWh, planning status, connection-offer status.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 12,
        "icp_tags": ["solar_dev", "bess_dev"],
    },
    {
        "slug": "battery-fire-comah",
        "title": "Battery fire / COMAH filings",
        "description": "HSE COMAH notifications and lessons-learned reports from BESS thermal events.",
        "cluster": "BESS & storage",
        "source_filter": {"source": "hse_comah", "topic_tags_any": ["bess", "battery_fire"]},
        "llm_prompt": "Summarise battery-fire / COMAH activity: sites affected, root-cause where disclosed, regulatory follow-up, and planning-condition implications.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 3,
        "icp_tags": ["bess_dev", "grid_consultant", "land_agent"],
    },
    {
        "slug": "dfs-tenders",
        "title": "DFS / SO flex tenders",
        "description": "NESO Demand Flexibility Service and SO flexibility tenders, awards and settlements.",
        "cluster": "BESS & storage",
        "source_filter": {"source": "neso", "topic_tags_any": ["dfs", "flexibility_tender"]},
        "llm_prompt": "List DFS / SO flex activity: tender rounds, clearing prices, MW awarded by technology, settlement summaries.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 6,
        "icp_tags": ["bess_dev"],
    },

    # ── Renewables & CfD (6) ────────────────────────────────────────────────
    {
        "slug": "ar7-cfd-notices",
        "title": "AR7 CfD notices",
        "description": "All CfD AR7 allocation-round notices — framework, strike prices, timetable, budget.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source": "desnz_cfd", "case_type": "cfd_round", "topic_tags_any": ["ar7"]},
        "llm_prompt": "Summarise AR7 notices: budget splits by pot, admin strike prices, delivery-year changes, and key deadlines.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 5,
        "icp_tags": ["solar_dev", "bess_dev"],
    },
    {
        "slug": "ar6-delivery-milestones",
        "title": "AR6 delivery milestones",
        "description": "Post-award AR6 delivery tracking — milestones, target commissioning, withdrawals.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source": "lccc", "topic_tags_any": ["ar6", "cfd_delivery"]},
        "llm_prompt": "Summarise AR6 delivery progress: hitting milestones, at-risk projects, and any terminated contracts.",
        "cadence": "monthly",
        "est_docs_per_digest": 10,
        "icp_tags": ["solar_dev"],
    },
    {
        "slug": "roc-lifetime-end",
        "title": "RO / ROC lifetime-end tracker",
        "description": "Renewables Obligation end-of-support dates — repowering / decommissioning pipeline triggers.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source_in": ["ofgem", "desnz"], "topic_tags_any": ["roc_lifetime", "repowering"]},
        "llm_prompt": "List RO-supported assets approaching end-of-support. For each state technology, MW, site, operator, and the next 24-month repowering/disposal decisions expected.",
        "cadence": "monthly",
        "est_docs_per_digest": 8,
        "icp_tags": ["solar_dev", "land_agent"],
    },
    {
        "slug": "curtailment-volumes",
        "title": "Curtailment volumes & bid-volumes",
        "description": "NESO wind / solar curtailment volumes, Balancing Mechanism bid-volumes by zone.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source": "neso", "topic_tags_any": ["curtailment", "bm_bids"]},
        "llm_prompt": "Summarise curtailment volumes by zone and technology this period. Flag hot-spots where curtailment >20% of generation.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "bess_dev", "grid_consultant"],
    },
    {
        "slug": "en3-designation",
        "title": "EN-3 designation tracker",
        "description": "National Policy Statement EN-3 (renewable energy) designation status and material considerations.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source_in": ["desnz", "pins_nsip"], "topic_tags_any": ["en3", "nps_renewable"]},
        "llm_prompt": "Summarise EN-3 designation activity: statutory milestones, material-consideration weight shifts, and NSIP cases citing the updated NPS.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "grid_consultant"],
    },
    {
        "slug": "en1-en5-policy-updates",
        "title": "EN-1 / EN-5 policy updates",
        "description": "Overarching (EN-1) and electricity-networks (EN-5) NPS updates driving NSIP decisions.",
        "cluster": "Renewables & CfD",
        "source_filter": {"source": "desnz", "topic_tags_any": ["en1", "en5"]},
        "llm_prompt": "Summarise EN-1 / EN-5 policy changes: draft vs designated text, weight given to security of supply vs landscape, and implications for in-flight DCOs.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["grid_consultant", "solar_dev", "dc_dev"],
    },

    # ── PPA / offtake (5) ───────────────────────────────────────────────────
    {
        "slug": "corporate-ppa-announcements",
        "title": "Corporate PPA announcements",
        "description": "Publicly announced corporate PPAs — offtaker, seller, MW, tenor, product type.",
        "cluster": "PPA / offtake",
        "source_filter": {"topic_tags_any": ["corporate_ppa"]},
        "llm_prompt": "For each announced PPA state offtaker, developer, MW, tenor, product (physical / virtual / proxy), and £/MWh if disclosed.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 8,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev"],
    },
    {
        "slug": "ppa-index-prices",
        "title": "PPA index prices",
        "description": "Nord Pool / EEX / Baringa / LCP PPA index prices and baseload curves.",
        "cluster": "PPA / offtake",
        "source_filter": {"source_in": ["nordpool", "eex", "baringa", "lcp"], "topic_tags_any": ["ppa_index"]},
        "llm_prompt": "Summarise PPA index movements: baseload, shape, renewable solar/wind indices, and MoM change in £/MWh.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "bess_dev"],
    },
    {
        "slug": "cfd-supplier-obligation-deltas",
        "title": "CfD Supplier Obligation deltas",
        "description": "LCCC Supplier Obligation levy rate changes — driver of retail-price and PPA pricing.",
        "cluster": "PPA / offtake",
        "source_filter": {"source": "lccc", "topic_tags_any": ["supplier_obligation"]},
        "llm_prompt": "Summarise Supplier Obligation changes: ILR / Total Reserve Amount / ALR updates, in £/MWh, and direction implied for retail pricing.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["solar_dev"],
    },
    {
        "slug": "rego-market",
        "title": "REGO market",
        "description": "Renewable Energy Guarantees of Origin price prints, auction results, retirement volumes.",
        "cluster": "PPA / offtake",
        "source_filter": {"topic_tags_any": ["rego"]},
        "llm_prompt": "Summarise REGO market activity: price prints, auction results, retirement volumes, and implications for embedded benefit value.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 3,
        "icp_tags": ["solar_dev"],
    },
    {
        "slug": "hyperscaler-ppa-rfps",
        "title": "Hyperscaler PPA RFPs",
        "description": "Hyperscaler-issued PPA RFPs / IFPs and their award decisions (where public).",
        "cluster": "PPA / offtake",
        "source_filter": {"topic_tags_any": ["hyperscaler_ppa", "ppa_rfp"]},
        "llm_prompt": "Summarise hyperscaler PPA RFP activity: buyer, technology(s), MW sought, submission deadline, award status.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "dc_dev"],
    },

    # ── Capex / investments / M&A (5) ───────────────────────────────────────
    {
        "slug": "riio-ed2-ed3-capex-allowances",
        "title": "RIIO-ED2 / ED3 capex allowance changes",
        "description": "DNO business-plan / re-opener decisions and associated capex allowances.",
        "cluster": "Capex / investments / M&A",
        "source_filter": {"source": "ofgem", "topic_tags_any": ["capex_allowance", "riio_ed2", "riio_ed3"]},
        "llm_prompt": "Summarise DNO capex allowance decisions: DNO, £m change, rationale, and reinforcement programmes unlocked.",
        "cadence": "monthly",
        "est_docs_per_digest": 5,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "dno-business-plan-updates",
        "title": "DNO business plan updates",
        "description": "RIIO-ED3 business plan submissions, consultations and updates by the 6 UK DNOs.",
        "cluster": "Capex / investments / M&A",
        "source_filter": {"source_in": ["ngedno", "ukpn", "spen", "ssen", "np", "enwl"], "topic_tags_any": ["business_plan"]},
        "llm_prompt": "List DNO business-plan updates: DNO, document type, consultation window, and any material capex or workload changes flagged.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 6,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "infrastructure-fund-m-and-a",
        "title": "Infrastructure-fund M&A",
        "description": "UK renewables / storage / networks acquisitions by infra funds (Greencoat, JLEN, BBGI, Foresight, Macquarie, etc).",
        "cluster": "Capex / investments / M&A",
        "source_filter": {"topic_tags_any": ["infra_fund", "m_and_a"]},
        "llm_prompt": "For each transaction state buyer, seller, asset, MW, EV if disclosed, and implied £/MW.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 5,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent"],
    },
    {
        "slug": "utility-credit-rating",
        "title": "Utility credit-rating actions",
        "description": "Moody's / S&P / Fitch ratings, outlook changes and bond pricing for UK networks and generators.",
        "cluster": "Capex / investments / M&A",
        "source_filter": {"topic_tags_any": ["credit_rating", "utility_rating"]},
        "llm_prompt": "Summarise credit-rating actions on UK utilities: entity, agency, new rating / outlook, and stated drivers.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 4,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "green-bond-issuance",
        "title": "Green bond / sustainability-linked issuance",
        "description": "Green-bond and SLB issuance by UK energy utilities and developers.",
        "cluster": "Capex / investments / M&A",
        "source_filter": {"topic_tags_any": ["green_bond", "sustainability_linked"]},
        "llm_prompt": "List green-bond / SLB issuances: issuer, size, tenor, coupon, and use-of-proceeds allocation.",
        "cadence": "monthly",
        "est_docs_per_digest": 4,
        "icp_tags": ["grid_consultant"],
    },

    # ── Devolved-nation & regional (5) ──────────────────────────────────────
    {
        "slug": "section36-scottish-dns",
        "title": "Section 36 / Scottish DNS",
        "description": "Scottish Government Section 36 and DNS consent decisions.",
        "cluster": "Devolved-nation & regional",
        "source_filter": {"source": "scot_gov_energy_consents", "case_type_in": ["section36", "scottish_dns"]},
        "llm_prompt": "Summarise Scottish consent activity: applications lodged, decisions, attached conditions, and cumulative landscape-and-visual considerations.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 6,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent", "grid_consultant"],
    },
    {
        "slug": "welsh-dns-tracker",
        "title": "Welsh DNS tracker",
        "description": "Planning and Environment Decisions Wales (PEDW) DNS tracker for energy schemes >10MW.",
        "cluster": "Devolved-nation & regional",
        "source_filter": {"source": "welsh_pedw", "topic_tags_any": ["dns", "energy"]},
        "llm_prompt": "Summarise PEDW DNS activity: new applications, decisions, and consenting-timeline performance.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "bess_dev"],
    },
    {
        "slug": "ni-utility-regulator",
        "title": "NI Utility Regulator",
        "description": "Northern Ireland Utility Regulator decisions, SEM reforms and related code modifications.",
        "cluster": "Devolved-nation & regional",
        "source_filter": {"source": "uregni", "topic_tags_any": ["sem", "ni_ur"]},
        "llm_prompt": "Summarise NI UR / SEM activity: decisions, consultations and implications for NI-based projects.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 3,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "crown-estate-offshore-leasing",
        "title": "Crown Estate & Crown Estate Scotland leasing",
        "description": "Offshore / seabed leasing rounds, coastal-zone decisions, Celtic Sea and ScotWind updates.",
        "cluster": "Devolved-nation & regional",
        "source_filter": {"source_in": ["crown_estate", "crown_estate_scotland"], "topic_tags_any": ["leasing", "seabed"]},
        "llm_prompt": "Summarise leasing-round activity: leasing round, MW, partners, milestones, and any consenting-pathway clarifications.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 4,
        "icp_tags": ["solar_dev", "grid_consultant"],
    },
    {
        "slug": "devolved-land-designations",
        "title": "Devolved land designations",
        "description": "AONB / National Park / National Landscape designation changes across E/W/S.",
        "cluster": "Devolved-nation & regional",
        "source_filter": {"topic_tags_any": ["aonb", "national_park", "national_landscape"]},
        "llm_prompt": "Summarise land-designation changes by region and assess likely development-pipeline impact.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["land_agent"],
    },

    # ── Market & settlement (5) ─────────────────────────────────────────────
    {
        "slug": "bmrs-imbalance-daily",
        "title": "BMRS imbalance daily",
        "description": "BMRS system imbalance prices, NIV, and cashout outturn — daily summary.",
        "cluster": "Market & settlement",
        "source_filter": {"source": "bmrs", "topic_tags_any": ["imbalance", "cashout"]},
        "llm_prompt": "Summarise imbalance prices, NIV direction, and cashout events today. Flag any spikes > £500/MWh.",
        "cadence": "daily",
        "est_docs_per_digest": 2,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "negative-pricing-events",
        "title": "Negative-pricing events",
        "description": "All periods with negative day-ahead / imbalance prices and associated MW curtailed.",
        "cluster": "Market & settlement",
        "source_filter": {"source": "bmrs", "topic_tags_any": ["negative_pricing"]},
        "llm_prompt": "List all negative-pricing periods: date/time, price floor hit, MW curtailed, dominant driver (wind oversupply, low demand).",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 5,
        "icp_tags": ["solar_dev", "bess_dev"],
    },
    {
        "slug": "balancing-services-monthly",
        "title": "Balancing services monthly",
        "description": "NESO balancing services £m spend by category and technology mix.",
        "cluster": "Market & settlement",
        "source_filter": {"source": "neso", "topic_tags_any": ["balancing_services"]},
        "llm_prompt": "Summarise monthly balancing services spend: £m by service, YoY change, and technology-mix shift.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "cmp-gc-mod-tracker",
        "title": "CUSC / CMP and Grid Code mod tracker",
        "description": "All CMP and Grid Code modification proposals — panel votes, Ofgem decisions, implementation.",
        "cluster": "Market & settlement",
        "source_filter": {"source_in": ["neso", "ofgem"], "case_type_in": ["cmp", "gc", "cusc"]},
        "llm_prompt": "List CMP / GC / CUSC mods active this period: mod number, title, panel recommendation, Ofgem decision, implementation date.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 10,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "eex-nordpool-uk-curves",
        "title": "EEX / Nord Pool UK curves",
        "description": "UK forward-curve prints — baseload, peak, solar/wind profiles across front-year and curve.",
        "cluster": "Market & settlement",
        "source_filter": {"source_in": ["eex", "nordpool"], "topic_tags_any": ["uk_forward_curve"]},
        "llm_prompt": "Summarise UK forward-curve movements: baseload, peak, profile premia, and solar/wind capture-price implications.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 3,
        "icp_tags": ["solar_dev", "bess_dev"],
    },

    # ── Safety & compliance (5) ─────────────────────────────────────────────
    {
        "slug": "bs9991-grenfell-flowdown",
        "title": "BS9991 / Grenfell flow-down",
        "description": "Building Safety Act and BS9991 updates that flow down to DC / HV-switchroom build.",
        "cluster": "Safety & compliance",
        "source_filter": {"topic_tags_any": ["bs9991", "building_safety_act"]},
        "llm_prompt": "Summarise BS9991 / BSA compliance changes affecting DC / switchroom builds: requirement changed, effective date, and typical cost impact.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["dc_dev"],
    },
    {
        "slug": "hse-comah-updates",
        "title": "HSE COMAH updates",
        "description": "HSE COMAH notifications, incident reports and regulatory notices for UK energy sites.",
        "cluster": "Safety & compliance",
        "source_filter": {"source": "hse_comah", "case_type": "hse_comah"},
        "llm_prompt": "Summarise HSE COMAH activity: notifications, incidents, improvement notices, and lessons-learned relevant to HV / BESS / hydrogen.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 5,
        "icp_tags": ["bess_dev", "grid_consultant"],
    },
    {
        "slug": "eng-rec-p28-p29",
        "title": "Eng Rec P28 / P29 updates",
        "description": "Engineering Recommendations P28 (voltage fluctuations) and P29 (voltage unbalance) amendments.",
        "cluster": "Safety & compliance",
        "source_filter": {"topic_tags_any": ["p28", "p29", "eng_rec"]},
        "llm_prompt": "Summarise any P28 / P29 amendments: technical change, effective date, and connection-design implications.",
        "cadence": "monthly",
        "est_docs_per_digest": 2,
        "icp_tags": ["grid_consultant", "dc_dev"],
    },
    {
        "slug": "g99-g98-updates",
        "title": "G99 / G98 updates",
        "description": "Engineering Recommendations G99 and G98 amendments — driver of DNO connection sign-off.",
        "cluster": "Safety & compliance",
        "source_filter": {"topic_tags_any": ["g99", "g98"]},
        "llm_prompt": "Summarise G99 / G98 revisions: technical change, effective date, retrofit vs new-build applicability.",
        "cadence": "monthly",
        "est_docs_per_digest": 2,
        "icp_tags": ["solar_dev", "bess_dev", "grid_consultant"],
    },
    {
        "slug": "cdm-2015-enforcement",
        "title": "CDM 2015 enforcement",
        "description": "HSE enforcement notices and prosecutions under CDM 2015 regs relevant to energy construction.",
        "cluster": "Safety & compliance",
        "source_filter": {"source": "hse", "topic_tags_any": ["cdm_2015", "construction_enforcement"]},
        "llm_prompt": "Summarise CDM enforcement activity: notices served, projects affected, principal designer / PC implications.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev"],
    },

    # ── Environmental (5) ───────────────────────────────────────────────────
    {
        "slug": "water-stress-dc-permits",
        "title": "Water-stress DC permits",
        "description": "EA abstraction / discharge permits in water-stress areas relevant to DC cooling.",
        "cluster": "Environmental",
        "source_filter": {"source": "ea_permits", "topic_tags_any": ["water_stress", "abstraction"]},
        "llm_prompt": "Summarise water-stress permit activity: permit type, catchment, volume, any EA objections to DC cooling applications.",
        "cadence": "monthly",
        "est_docs_per_digest": 4,
        "icp_tags": ["dc_dev"],
    },
    {
        "slug": "ea-environmental-permits",
        "title": "EA environmental permits",
        "description": "Environment Agency environmental permit decisions relevant to energy projects.",
        "cluster": "Environmental",
        "source_filter": {"source": "ea_permits", "case_type": "ea_permit"},
        "llm_prompt": "Summarise EA permit decisions: project, permit type, key conditions, and any consultee objections.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 8,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev"],
    },
    {
        "slug": "bng-on-nsip-and-lpa",
        "title": "BNG on NSIPs & LPAs",
        "description": "Biodiversity Net Gain reporting activity across NSIP and LPA schemes.",
        "cluster": "Environmental",
        "source_filter": {"topic_tags_any": ["bng", "biodiversity_net_gain"]},
        "llm_prompt": "Summarise BNG reporting across all recent schemes: % gain, on-site vs off-site split, habitat types, and Natural England responses.",
        "cadence": "monthly",
        "est_docs_per_digest": 10,
        "icp_tags": ["solar_dev", "land_agent"],
    },
    {
        "slug": "natural-england-objections",
        "title": "Natural England objections",
        "description": "All Natural England objections and consultation responses on energy NSIPs / LPAs.",
        "cluster": "Environmental",
        "source_filter": {"source_in": ["pins_nsip", "planit_lpa"], "topic_tags_any": ["natural_england"]},
        "llm_prompt": "List Natural England objections: scheme, reason, whether withdrawn after mitigation, and implications for EIA scope.",
        "cadence": "weekly_thu",
        "est_docs_per_digest": 6,
        "icp_tags": ["solar_dev", "bess_dev", "land_agent"],
    },
    {
        "slug": "dsa-peat-deep-peat",
        "title": "Designated / deep peat restrictions",
        "description": "Designated / deep-peat / irreplaceable-habitat restrictions and related policy updates.",
        "cluster": "Environmental",
        "source_filter": {"topic_tags_any": ["peat", "deep_peat", "irreplaceable_habitat"]},
        "llm_prompt": "Summarise deep-peat / irreplaceable-habitat restrictions: geographic coverage, policy status, case-law where cited.",
        "cadence": "monthly",
        "est_docs_per_digest": 3,
        "icp_tags": ["solar_dev", "land_agent"],
    },

    # ── Company intelligence (7) ────────────────────────────────────────────
    {
        "slug": "new-spv-incorporations",
        "title": "New SPV incorporations",
        "description": "Companies House — new SPV incorporations tagged to energy / DC / battery SIC codes.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["spv_incorporation"]},
        "llm_prompt": "List new energy/DC SPV incorporations: company number, name, SIC codes, directors, registered office.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 25,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "land_agent"],
    },
    {
        "slug": "director-watchlist",
        "title": "Director watchlist",
        "description": "Director appointments / resignations for a configurable watchlist of key UK energy execs.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["director_move"]},
        "llm_prompt": "List director appointments/resignations on the watchlist this week: person, company, role, date.",
        "cadence": "weekly_tue",
        "est_docs_per_digest": 10,
        "icp_tags": ["land_agent", "solar_dev"],
    },
    {
        "slug": "dissolutions-project-spvs",
        "title": "Dissolutions / strike-offs",
        "description": "Companies House dissolutions and strike-offs of energy-project SPVs (signals end-of-life).",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["dissolution", "strike_off"]},
        "llm_prompt": "List dissolved/struck-off project SPVs: company, prior project asset, dissolution reason if disclosed.",
        "cadence": "weekly_wed",
        "est_docs_per_digest": 10,
        "icp_tags": ["land_agent"],
    },
    {
        "slug": "group-consolidations",
        "title": "Group consolidations",
        "description": "Group-structure changes, holdco relocations, mergers/reorganisations in UK energy.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["consolidation", "reorganisation"]},
        "llm_prompt": "Summarise group consolidations: parties, structure change, strategic rationale implied.",
        "cadence": "monthly",
        "est_docs_per_digest": 5,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "persons-of-significant-control",
        "title": "PSC changes",
        "description": "Persons of Significant Control changes for UK energy SPVs.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["psc_change"]},
        "llm_prompt": "List PSC changes on UK energy SPVs: company, incoming / outgoing PSC, nature of control.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 10,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "sanctions-screening",
        "title": "Sanctions screening — counterparties",
        "description": "OFSI sanctions-list deltas affecting UK energy counterparties.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "ofsi", "topic_tags_any": ["sanctions"]},
        "llm_prompt": "Summarise OFSI sanctions list deltas: new designations, delistings, and counterparties screened.",
        "cadence": "weekly_fri",
        "est_docs_per_digest": 3,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "filing-confirmations",
        "title": "Accounts / confirmation-statement filings",
        "description": "Annual accounts and confirmation-statement filings for UK energy SPVs.",
        "cluster": "Company intelligence",
        "source_filter": {"source": "companies_house", "topic_tags_any": ["confirmation_statement", "annual_accounts"]},
        "llm_prompt": "List recent accounts / confirmation-statement filings: entity, filing type, period covered, and any material events disclosed.",
        "cadence": "monthly",
        "est_docs_per_digest": 20,
        "icp_tags": ["grid_consultant"],
    },

    # ── Innovation & NIA/SIF (5) ────────────────────────────────────────────
    {
        "slug": "sif-awards",
        "title": "SIF awards",
        "description": "Strategic Innovation Fund discovery/alpha/beta award decisions.",
        "cluster": "Innovation & NIA/SIF",
        "source_filter": {"source": "ofgem_sif", "topic_tags_any": ["sif"]},
        "llm_prompt": "Summarise SIF award decisions: project, lead, partners, stage, funding amount, delivery phase.",
        "cadence": "monthly",
        "est_docs_per_digest": 6,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "nia-annual-reports",
        "title": "NIA annual reports",
        "description": "Network Innovation Allowance annual reports across DNOs and NGET/NESO.",
        "cluster": "Innovation & NIA/SIF",
        "source_filter": {"topic_tags_any": ["nia", "nia_annual"]},
        "llm_prompt": "Summarise NIA annual reports: projects completed, BCR realised, rollout status by sponsor.",
        "cadence": "monthly",
        "est_docs_per_digest": 6,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "dlr-advanced-conductor-pilots",
        "title": "DLR / advanced-conductor pilots",
        "description": "Dynamic line rating and advanced-conductor (ACCC, HVCRC) pilots and deployments.",
        "cluster": "Innovation & NIA/SIF",
        "source_filter": {"topic_tags_any": ["dlr", "advanced_conductor"]},
        "llm_prompt": "Summarise DLR / advanced-conductor activity: site, sponsor, MW uplift delivered, decision-stage.",
        "cadence": "monthly",
        "est_docs_per_digest": 4,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "gbso-digital-systems",
        "title": "NESO / digital systems",
        "description": "NESO digital-first initiatives (digital twin, ADMS, whole-system planning).",
        "cluster": "Innovation & NIA/SIF",
        "source_filter": {"source": "neso", "topic_tags_any": ["digital_twin", "digital_systems"]},
        "llm_prompt": "Summarise NESO digital activity: published RFPs, pilots, architectural decisions relevant to SO-level planning.",
        "cadence": "monthly",
        "est_docs_per_digest": 4,
        "icp_tags": ["grid_consultant"],
    },
    {
        "slug": "ukri-ctf-funding",
        "title": "UKRI / CTF funding",
        "description": "UKRI, Innovate UK and Clean Technology Fund competitions relevant to UK energy innovation.",
        "cluster": "Innovation & NIA/SIF",
        "source_filter": {"topic_tags_any": ["ukri", "innovate_uk", "ctf"]},
        "llm_prompt": "Summarise funding calls, awards and delivery milestones: competition, theme, £m, awardees.",
        "cadence": "monthly",
        "est_docs_per_digest": 5,
        "icp_tags": ["grid_consultant"],
    },

    # ── DNO engagement workflow (Task #20) ─────────────────────────────────
    # These SKUs are project-scoped, not library-scoped — the digest_worker
    # joins against `project_dno_engagements` / `dno_engagement_responses`
    # rather than the generic `documents` table. `source_filter.internal`
    # flags them so the worker routes them to the right dispatcher.
    {
        "slug": "dno-engagement-response-received",
        "title": "DNO engagement response received",
        "description": "The DNO has responded to a project's engagement pack — in-app + email push within minutes of ingestion so the project team can react before the window closes.",
        "cluster": "Grid connection & queue",
        "source_filter": {
            "internal": "dno_engagement_response",
            "severity": "high",
            "channels": ["in_app", "email"],
        },
        "llm_prompt": "Summarise the DNO's response: sentiment, proposed POC vs original ask, firm/non-firm split delta (MW), timeline shift (days), and the single most material item requiring a decision in the next 14 days.",
        "cadence": "realtime",
        "est_docs_per_digest": 1,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "grid_consultant"],
    },
    {
        "slug": "dno-engagement-deadline-approaching",
        "title": "DNO engagement deadline approaching",
        "description": "Outstanding response deadlines on active DNO engagements — weekly Monday 08:00 digest so the team can plan the week's regulatory workload.",
        "cluster": "Grid connection & queue",
        "source_filter": {
            "internal": "dno_engagement_deadline",
            "severity": "med",
            "channels": ["in_app"],
            "lookahead_days": 14,
        },
        "llm_prompt": "List engagement deadlines falling inside the next 14 days. For each, state project, DNO, deadline item, days remaining, owner, and the consequence if missed.",
        "cadence": "weekly_mon",
        "est_docs_per_digest": 8,
        "icp_tags": ["solar_dev", "bess_dev", "dc_dev", "grid_consultant"],
    },
]


_EXPECTED_COUNT = 84


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def seed_alert_definitions(pool: asyncpg.Pool) -> int:
    """Idempotently seed the 84 UK alert SKUs.

    Returns the number of rows inserted this run (existing rows are skipped).
    Count includes the 2 DNO-engagement SKUs added in Task #20 —
    `dno-engagement-response-received` and
    `dno-engagement-deadline-approaching`.
    """
    assert len(_CATALOGUE) == _EXPECTED_COUNT, (
        f"_CATALOGUE has {len(_CATALOGUE)} rows, expected {_EXPECTED_COUNT}"
    )

    inserted = 0
    try:
        async with pool.acquire() as conn:
            # Ensure the table exists before we try to insert. The 0001
            # migration creates it, but in a mis-ordered startup we don't
            # want to crash the whole app.
            present = await conn.fetchval(
                "SELECT to_regclass('public.alert_definitions') IS NOT NULL"
            )
            if not present:
                log.warning("alert_definitions table missing — skipping alert seed")
                return 0

            for row in _CATALOGUE:
                try:
                    result = await conn.execute(
                        """
                        INSERT INTO alert_definitions
                            (slug, title, description, cluster, source_filter,
                             llm_prompt, cadence, est_docs_per_digest,
                             icp_tags, is_public)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, true)
                        ON CONFLICT (slug) DO NOTHING
                        """,
                        row["slug"], row["title"], row["description"],
                        row["cluster"], json.dumps(row["source_filter"]),
                        row["llm_prompt"], row["cadence"],
                        row["est_docs_per_digest"], row["icp_tags"],
                    )
                    # asyncpg returns 'INSERT 0 1' on actual insert, 'INSERT 0 0' on conflict
                    if result.endswith(" 1"):
                        inserted += 1
                except Exception:
                    log.exception("alert seed failed for slug=%s", row["slug"])
    except Exception:
        log.exception("seed_alert_definitions failed")
        return 0

    if inserted:
        log.info("Seeded %d/%d alert_definitions (existing rows left untouched)", inserted, _EXPECTED_COUNT)
    else:
        log.info("Alert seed: all %d SKUs already present", _EXPECTED_COUNT)
    return inserted


def catalogue() -> list[dict[str, Any]]:
    """Return a shallow copy of the catalogue (used by tests / starter packs)."""
    return list(_CATALOGUE)


def catalogue_slugs() -> set[str]:
    """Set of all seeded slugs — used by starter_packs to validate membership."""
    return {row["slug"] for row in _CATALOGUE}


__all__ = [
    "seed_alert_definitions",
    "catalogue",
    "catalogue_slugs",
]
