"""
Central regulatory-version registry.

Single source of truth for the issue numbers, publication dates and URLs of
every UK energy-development standard that Princeps cites in generated
documents. COUNCIL-1 audit flagged that individual packs were hard-coding
deprecated issue numbers (e.g. G99 Issue 1 instead of Issue 2); every new
pack generator MUST import from this module rather than inline a version
string.

Schema
------
Each entry is a dict with:

    key               short identifier (same as registry key, for symmetry)
    name              full document title
    version           current issue / edition / version string
    published         ISO date of publication (YYYY-MM-DD)
    effective         ISO date the version takes effect (may differ from published)
    url               canonical URL
    notes             optional free text (deprecation warnings, upcoming changes)
    supersedes        list of older version strings this edition replaces

When a standard is updated, bump a single entry here and every generator that
calls :func:`cite` picks up the new version on next run.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional


REGULATIONS: Dict[str, Dict] = {
    # ---------------------------------------------------------------
    # Grid connection
    # ---------------------------------------------------------------
    "g99": {
        "key": "g99",
        "name": "Engineering Recommendation G99",
        "subtitle": "Requirements for the connection of generation equipment in parallel with public distribution networks on or after 27 April 2019",
        "version": "Issue 2",
        "published": "2025-03-10",
        "effective": "2025-03-10",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G99",
        "notes": (
            "Issue 2 published 10 March 2025. Storage-specific Annex C provisions "
            "IN FORCE from 1 March 2026 (now live). Post-energisation verification tests "
            "under Annex C.9.2 must be returned within 28 days of synchronisation. "
            "No Issue 3 or further amendment as of 2026-04-19 (audited BOT-Y 2026 sweep)."
        ),
        "supersedes": [
            "Issue 1 Amendment 1",
            "Issue 1 Amendment 2",
            "Issue 1 Amendment 3",
            "Issue 1 Amendment 4",
            "Issue 1 Amendment 5",
            "Issue 1 Amendment 6",
            "Issue 1 Amendment 7",
            "Issue 1 Amendment 8",
            "Issue 1 Amendment 9",
        ],
    },
    "g100": {
        "key": "g100",
        "name": "Engineering Recommendation G100",
        "subtitle": "Technical requirements for customer export limiting schemes",
        "version": "Issue 2 Amendment 1",
        "published": "2022-07-01",
        "effective": "2022-07-01",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G100",
        "notes": "Applies where an export-limiting scheme is used to constrain connection capacity.",
        "supersedes": ["Issue 1", "Issue 2"],
    },
    "g98": {
        "key": "g98",
        "name": "Engineering Recommendation G98",
        "subtitle": "Requirements for the connection of Fully Type Tested Micro-generators (≤16 A per phase)",
        "version": "Issue 1 Amendment 9",
        "published": "2024-10-01",
        "effective": "2024-10-01",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G98",
        "notes": "Use for micro-generators only; larger installations must follow G99.",
        "supersedes": ["Issue 1", "Issue 1 Amendment 1-8"],
    },
    "g83": {
        "key": "g83",
        "name": "Engineering Recommendation G83",
        "subtitle": "Small-scale embedded generators (≤16 A per phase) — WITHDRAWN",
        "version": "Withdrawn",
        "published": "2008-01-01",
        "effective": "2018-04-27",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G83",
        "notes": (
            "DEPRECATED. Superseded by G98 Issue 1 on 27 April 2018. Never cite in new "
            "applications — use G98 instead."
        ),
        "supersedes": [],
    },
    "g59": {
        "key": "g59",
        "name": "Engineering Recommendation G59",
        "subtitle": "Embedded generators >16 A per phase — WITHDRAWN",
        "version": "Withdrawn",
        "published": "2014-01-01",
        "effective": "2019-04-27",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G59",
        "notes": (
            "DEPRECATED. Superseded by G99 Issue 1 on 27 April 2019. Never cite in new "
            "applications — use G99 instead. Legacy G59 relays remain valid until next "
            "protection review."
        ),
        "supersedes": [],
    },
    "cccm": {
        "key": "cccm",
        "name": "Common Connection Charging Methodology",
        "subtitle": "CCCM — shared DNO methodology for connection charges",
        "version": "v19",
        "published": "2024-04-01",
        "effective": "2024-04-01",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/common-connection-charging-methodology",
        "notes": (
            "Governs apportionment of reinforcement costs between connectee and DNO. "
            "Methodology level unchanged at audit 2026-04-19 — no Ofgem v20 published. "
            "Per-DNO statement refreshes continue (e.g. ENWL Statement v5.8 effective "
            "1 Jan 2026; SGN modification decision July 2025)."
        ),
        "supersedes": ["v17", "v18"],
    },
    "tmo4_gate2": {
        "key": "tmo4_gate2",
        "name": "NESO Connections Reform TMO4+ / Gate 2",
        "subtitle": "Target Model Option 4+ and Gate 2 queue reform",
        "version": "TMO4+ live (approved 15 Apr 2025)",
        "published": "2025-04-15",
        "effective": "2025-06-10",
        "url": "https://www.neso.energy/industry-information/connections-reform/connections-reform-timeline",
        "notes": (
            "Ofgem approved 15 April 2025; TMO4+ went live 10 June 2025. "
            "Gate 2 Phase 1 transmission / large embedded offers issue mid-May → mid-Sep 2026; "
            "distribution offers issue early Jul → mid-Nov 2026. Queue reduced from ~700 GW "
            "to 283 GW generation/storage. Certain existing-queue projects protected "
            "(planning consent + FID + commissioning in 2026)."
        ),
        "supersedes": ["Legacy first-come-first-served queue"],
    },

    # ---------------------------------------------------------------
    # Planning
    # ---------------------------------------------------------------
    "nppf": {
        "key": "nppf",
        "name": "National Planning Policy Framework",
        "subtitle": "England planning policy",
        "version": "December 2024",
        "published": "2024-12-12",
        "effective": "2024-12-12",
        "url": "https://www.gov.uk/government/publications/national-planning-policy-framework--2",
        "notes": (
            "Published 12 December 2024 — CURRENT at audit 2026-04-19. Paragraph "
            "numbering renumbered from the 2023 edition — use NPPF_PARA_MAP for "
            "old->new mapping (e.g. para 152 (2023) is now para 162 (2024)). "
            "PENDING: Dec 2025 revision consultation ran 16 Dec 2025 → 10 Mar 2026; "
            "revised NPPF expected June/July 2026 — DO NOT pre-emptively cite."
        ),
        "supersedes": ["2021", "July 2021", "September 2023", "December 2023"],
    },
    "pinfra_act_2025": {
        "key": "pinfra_act_2025",
        "name": "Planning and Infrastructure Act 2025",
        "subtitle": "Primary legislation — NSIP regime reform, Nature Restoration Fund, Environmental Delivery Plans",
        "version": "2025 c.[TBC]",
        "published": "2025-12-18",
        "effective": "2025-12-18",
        "url": "https://bills.parliament.uk/bills/3946",
        "notes": (
            "Royal Assent 18 December 2025. Phased commencement: some provisions in "
            "force on RA, further tranche Feb 2026, most await commencement orders "
            "(including changes to the NSIP regime and Environmental Delivery Plans). "
            "Ministers have undertaken to publish timetables. Material for every "
            "planning pack from 2026 onward."
        ),
        "supersedes": [],
    },
    "planning_act_2008": {
        "key": "planning_act_2008",
        "name": "Planning Act 2008",
        "subtitle": "Primary legislation for Nationally Significant Infrastructure Projects (NSIPs)",
        "version": "2008 c.29, as amended",
        "published": "2008-11-26",
        "effective": "2008-11-26",
        "url": "https://www.legislation.gov.uk/ukpga/2008/29/contents",
        "notes": (
            "As amended by Localism Act 2011, Growth & Infrastructure Act 2013, Wales Act 2017, "
            "Levelling-up & Regeneration Act 2023, Energy Act 2023 (solar threshold raised to "
            "100 MW, onshore wind brought back into TCPA regime)."
        ),
        "supersedes": [],
    },
    "bcp_regs_2009": {
        "key": "bcp_regs_2009",
        "name": "Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009",
        "subtitle": "APFP Regulations — DCO procedure",
        "version": "SI 2009/2264 as amended through SI 2024/332",
        "published": "2009-08-16",
        "effective": "2010-03-01",
        "url": "https://www.legislation.gov.uk/uksi/2009/2264/contents/made",
        "notes": (
            "Governs pre-application, acceptance, examination and decision stages "
            "for DCOs. Most recent amendment: Infrastructure Planning (Miscellaneous "
            "Provisions) Regulations 2024 (SI 2024/332) in force 30 April 2024, "
            "amending the Schedule 1 table of prescribed consultees and removing "
            "the s.51-advice exclusion from Panel appointments. Applies to DCO "
            "applications submitted after 30 April 2024."
        ),
        "supersedes": [],
    },
    "1app": {
        "key": "1app",
        "name": "Planning Portal 1APP",
        "subtitle": "Standard Application Form for planning consent (England & Wales)",
        "version": "v6",
        "published": "2023-04-01",
        "effective": "2023-04-01",
        "url": "https://www.planningportal.co.uk/applications/how-to-apply/how-to-apply",
        "notes": (
            "Use current 1APP v6 templates; submitting on older forms triggers "
            "invalidation. From Mar 2026 Planning Portal embeds CIL Form 1 "
            "(Additional Information) directly into the 1APP journey for "
            "CIL-enabled LPAs — separate CIL Form 1 upload no longer required "
            "for those authorities. For non-CIL-enabled LPAs continue to attach "
            "CIL Form 1 (2010 Regs as amended)."
        ),
        "supersedes": ["v4", "v5"],
    },
    "en1": {
        "key": "en1",
        "name": "Overarching National Policy Statement for Energy (EN-1)",
        "subtitle": "NPS for DCOs — overarching energy",
        "version": "2025 revision (published Nov 2025)",
        "published": "2025-11-12",
        "effective": "2025-11-12",
        "url": "https://www.gov.uk/government/publications/overarching-national-policy-statement-for-energy-en-1-2025/overarching-national-policy-statement-for-energy-en-1-2025-accessible-webpage",
        "notes": (
            "2025 REVISION published Nov 2025. Designated subject to 21-sitting-day "
            "parliamentary period; applies to DCO applications accepted for examination "
            "from in-force date. Principal changes: Clean Power Action Plan 2030 "
            "embedded in the Net Zero section; onshore wind brought into NPS scope "
            "(≥100 MW) following Infrastructure Planning (Onshore Wind and Solar "
            "Generation) Order 2025. For DCO applications ACCEPTED for examination "
            "before the 2025 NPS in-force date, the Nov 2023 (designated 17 Jan 2024) "
            "version continues to apply — always check application acceptance date."
        ),
        "supersedes": ["July 2011", "November 2023 refresh (designated 17 Jan 2024)"],
    },
    "en3": {
        "key": "en3",
        "name": "National Policy Statement for Renewable Energy Infrastructure (EN-3)",
        "subtitle": "NPS for DCOs — renewable energy (solar, onshore wind post-2024, biomass)",
        "version": "2025 revision (in force 6 Jan 2026)",
        "published": "2025-11-12",
        "effective": "2026-01-06",
        "url": "https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025",
        "notes": (
            "2025 revision IN FORCE 6 January 2026. Applies to DCO applications "
            "accepted for examination on or after that date. Earlier Nov 2023 "
            "designation (17 Jan 2024) continues to apply to applications accepted "
            "before 6 Jan 2026 — use acceptance-date logic."
        ),
        "supersedes": ["July 2011", "November 2023 refresh (designated 17 Jan 2024)"],
    },
    "en5": {
        "key": "en5",
        "name": "National Policy Statement for Electricity Networks Infrastructure (EN-5)",
        "subtitle": "NPS for DCOs — overhead lines and substations",
        "version": "2025 revision (published Nov 2025)",
        "published": "2025-11-12",
        "effective": "2025-11-12",
        "url": "https://www.gov.uk/government/publications/national-policy-statements-for-energy-infrastructure",
        "notes": (
            "2025 REVISION published Nov 2025 alongside EN-1. Designated subject to "
            "21-sitting-day parliamentary period. Once in force applies to DCO "
            "applications accepted for examination from that date. For applications "
            "accepted before the 2025 NPS in-force date, the Nov 2023 (designated "
            "17 Jan 2024) version continues to apply."
        ),
        "supersedes": ["July 2011", "November 2023 refresh (designated 17 Jan 2024)"],
    },

    # ---------------------------------------------------------------
    # Environment
    # ---------------------------------------------------------------
    "statutory_biodiversity_metric": {
        "key": "statutory_biodiversity_metric",
        "name": "Statutory Biodiversity Metric",
        "subtitle": "Environment Act 2021 s98 mandatory metric for BNG",
        "version": "v1.0 (minor tooling update July 2025)",
        "published": "2023-11-29",
        "effective": "2024-02-12",
        "url": "https://www.gov.uk/government/publications/statutory-biodiversity-metric-tools-and-guides",
        "notes": (
            "Mandatory from 12 February 2024 for most TCPA applications (small sites "
            "2 April 2024). NSIP BNG introduction DELAYED from Nov 2025 to May 2026 "
            "(Environmental Improvement Plan Dec 2025; govt response Apr 2026). "
            "Minor routine updates to statutory metric tools published July 2025 "
            "(clarifications and watercourse module refinements; biodiversity unit "
            "outputs unchanged). Small Sites Metric user guide also updated July 2025. "
            "Sites <0.2 ha exemption approved Dec 2025; statutory instrument pending. "
            "Replaces Biodiversity Metric 4.0 for statutory use."
        ),
        "supersedes": ["Biodiversity Metric 3.0", "Biodiversity Metric 3.1", "Biodiversity Metric 4.0"],
    },
    "ukhab": {
        "key": "ukhab",
        "name": "UK Habitat Classification",
        "subtitle": "UKHab — habitat classification used by the Statutory Biodiversity Metric",
        "version": "v2.0",
        "published": "2023-03-01",
        "effective": "2023-03-01",
        "url": "https://www.ukhab.org/",
        "notes": "Aligned with Statutory Biodiversity Metric v1.0; required for all BNG baseline surveys.",
        "supersedes": ["v1.0", "v1.1"],
    },
    "environment_act_2021": {
        "key": "environment_act_2021",
        "name": "Environment Act 2021",
        "subtitle": "Primary legislation mandating 10% Biodiversity Net Gain",
        "version": "2021 c.30 (further commencements to May 2025)",
        "published": "2021-11-09",
        "effective": "2024-02-12",
        "url": "https://www.legislation.gov.uk/ukpga/2021/30/contents",
        "notes": (
            "s98 and Schedule 14 bring in mandatory BNG condition on planning permissions. "
            "Environment Act 2021 (Commencement No. 10) Regulations 2025 (SI 2025/447) "
            "brought specified sections into force 1 May 2025 (including TCP-related "
            "provisions). Public bodies' biodiversity duty — first reports covering up "
            "to 1 January 2026 are due by end March 2026."
        ),
        "supersedes": [],
    },

    # ---------------------------------------------------------------
    # Health & Safety
    # ---------------------------------------------------------------
    "cdm_2015": {
        "key": "cdm_2015",
        "name": "Construction (Design and Management) Regulations 2015",
        "subtitle": "CDM 2015",
        "version": "SI 2015/51",
        "published": "2015-02-06",
        "effective": "2015-04-06",
        "url": "https://www.legislation.gov.uk/uksi/2015/51/contents/made",
        "notes": (
            "Accompanied by HSE Approved Code of Practice L153 (Managing health and safety "
            "in construction). F10 notification required for projects >500 person-days or "
            ">30 working days with >20 workers simultaneously."
        ),
        "supersedes": ["CDM 2007"],
    },
    "hse_l153": {
        "key": "hse_l153",
        "name": "HSE L153 Approved Code of Practice",
        "subtitle": "Managing health and safety in construction (CDM 2015 ACoP)",
        "version": "L153 (2015)",
        "published": "2015-04-01",
        "effective": "2015-04-06",
        "url": "https://www.hse.gov.uk/pubns/books/l153.htm",
        "notes": (
            "The authoritative guidance accompanying CDM 2015; cite alongside SI 2015/51. "
            "MONITOR: HSE has indicated (2025 bulletins) that CDM 2015 will not be "
            "supported by an ACoP going forward. L153 remains current at audit "
            "2026-04-19 but may be retired / replaced with alternative guidance."
        ),
        "supersedes": [],
    },

    # ---------------------------------------------------------------
    # Valuation / finance
    # ---------------------------------------------------------------
    "rics_fvp": {
        "key": "rics_fvp",
        "name": "RICS Professional Standard: Financial Viability in Planning — Conduct and Reporting",
        "subtitle": "FVP PS",
        "version": "2nd edition",
        "published": "2021-05-01",
        "effective": "2021-09-01",
        "url": "https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/financial-viability-in-planning-conduct-and-reporting",
        "notes": "Applies to all FVAs supporting planning applications in England.",
        "supersedes": ["1st edition (2019)"],
    },
    "rics_red_book": {
        "key": "rics_red_book",
        "name": "RICS Valuation — Global Standards (Red Book)",
        "subtitle": "IVS-compliant valuation standards",
        "version": "Effective 31 January 2025",
        "published": "2024-12-02",
        "effective": "2025-01-31",
        "url": "https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/red-book",
        "notes": (
            "Published 2 December 2024; effective 31 January 2025 — aligned with "
            "IVS also effective 31 January 2025. Includes AVM/AI guidance and ESG "
            "integration. Used for Red Book-compliant valuations of development "
            "land and operating assets."
        ),
        "supersedes": ["Red Book Global 2020", "Effective 31 January 2022"],
    },
    "cfd_ar7": {
        "key": "cfd_ar7",
        "name": "Contracts for Difference — Allocation Round 7",
        "subtitle": "AR7 — DESNZ CfD 2026 results",
        "version": "AR7 results (awarded 14 January 2026)",
        "published": "2025-08-07",
        "effective": "2026-01-14",
        "url": "https://www.gov.uk/cma-cases/referral-of-the-proposed-contracts-for-difference-allocation-round-7-scheme-by-the-department-for-energy-security-and-net-zero",
        "notes": (
            "AR7 opened 7 Aug 2025; results announced 14 Jan 2026 — 8.4 GW awarded. "
            "Offshore wind strike prices: £91.20/MWh (E&W), £89.49/MWh (Scotland); "
            "floating OSW £216.49/MWh. Administrative Strike Prices: solar PV "
            "£75/MWh (-12% vs AR6); offshore wind £113/MWh (+11%). Contract length "
            "extended to 20 years for wind and solar (was 15). Eligible techs: "
            "offshore wind, onshore wind (>5 MW), solar PV (>5 MW), floating OSW, "
            "hydro, ACT, AD, biomass CHP, EfW CHP, geothermal, landfill / sewage "
            "gas, remote island wind, tidal stream, wave."
        ),
        "supersedes": ["AR5", "AR6"],
    },
    "rema_2025": {
        "key": "rema_2025",
        "name": "Review of Electricity Market Arrangements — Summer Update 2025",
        "subtitle": "REMA decisions: Reformed National Pricing",
        "version": "Summer Update July 2025",
        "published": "2025-07-10",
        "effective": "2025-07-10",
        "url": "https://www.gov.uk/government/publications/review-of-electricity-market-arrangements-rema-summer-update-2025/review-of-electricity-market-arrangements-rema-summer-update-2025-accessible-webpage",
        "notes": (
            "REMA Summer Update (July 2025) confirmed NO zonal pricing; retained "
            "single GB-wide wholesale market with a package of 'Reformed National "
            "Pricing' enhancements — Strategic Spatial Energy Plan (SSEP), "
            "Centralised Strategic Network Plan (CSNP), reforms to TNuoS and "
            "connection costs. First SSEP expected late 2026; CSNP expected 2027. "
            "Supersedes REMA consultation scenarios that assumed zonal pricing."
        ),
        "supersedes": ["REMA 2022-2024 consultation phase"],
    },
    "clean_power_2030": {
        "key": "clean_power_2030",
        "name": "Clean Power 2030 Action Plan",
        "subtitle": "DESNZ pathway to clean electricity by 2030",
        "version": "Main report Dec 2024 + Connections Reform Annex Update April 2025",
        "published": "2024-12-13",
        "effective": "2024-12-13",
        "url": "https://www.gov.uk/government/publications/clean-power-2030-action-plan/",
        "notes": (
            "Published Dec 2024; Connections Reform Annex updated April 2025. "
            "Key 2026 milestones: most new transmission / offshore wind projects "
            "must have all relevant planning permissions in place by 2026; SSEP "
            "first edition expected late 2026; DESNZ response to community "
            "benefits working paper forthcoming (flagged 17 March 2026). Now "
            "embedded as the primary policy in NPS EN-1 (2025 revision)."
        ),
        "supersedes": [],
    },
    "pinfra_act_2025_commencements": {
        "key": "pinfra_act_2025_commencements",
        "name": "Planning and Infrastructure Act 2025 — Commencement",
        "subtitle": "Phased commencement tracker (sibling of pinfra_act_2025)",
        "version": "Phase 1 (RA + Feb 2026)",
        "published": "2025-12-18",
        "effective": "2025-12-18",
        "url": "https://www.gov.uk/government/news/landmark-planning-and-infrastructure-bill-becomes-law",
        "notes": (
            "Phase 1: immediate on Royal Assent (18 Dec 2025). Phase 2: two months "
            "after RA (February 2026). Phase 3+: by commencement order — NSIP "
            "regime changes, Environmental Delivery Plans, Nature Restoration "
            "Fund all await regulations. Check legislation.gov.uk commencement "
            "orders before citing a specific provision as in force."
        ),
        "supersedes": [],
    },
    "procurement_act_2023": {
        "key": "procurement_act_2023",
        "name": "Procurement Act 2023",
        "subtitle": "Public procurement regime (in force 24 February 2025)",
        "version": "2023 c.54 (in force 24 Feb 2025)",
        "published": "2023-10-26",
        "effective": "2025-02-24",
        "url": "https://www.legislation.gov.uk/ukpga/2023/54/contents",
        "notes": (
            "Commenced 24 February 2025 (delayed from Oct 2024). First transitional "
            "reporting period 24 Feb → 30 Sep 2025; subsequent six-month periods. "
            "Introduces open frameworks (re-openable appointment windows). DNOs are "
            "not contracting authorities for CCCM-driven connection work, so no "
            "direct interplay with connection charges. Princeps outputs for "
            "public-sector utility counterparties should reference PA 2023."
        ),
        "supersedes": ["Public Contracts Regulations 2015 (for procurements from 24 Feb 2025)"],
    },
    "reul_act_2023": {
        "key": "reul_act_2023",
        "name": "Retained EU Law (Revocation and Reform) Act 2023",
        "subtitle": "REUL sunsets + restatement powers",
        "version": "2023 c.28",
        "published": "2023-06-29",
        "effective": "2024-01-01",
        "url": "https://www.legislation.gov.uk/ukpga/2023/28/contents",
        "notes": (
            "Restatement / revocation / replacement powers EXPIRE 23 June 2026. "
            "Beyond that date broader REUL reforms require standard primary "
            "legislation. Princeps does not currently anchor on any ref that "
            "lapses by default — EIA Regs 2017 (SI 2017/571) remain in force as "
            "assimilated law. MONITOR for any DESNZ use of restatement powers "
            "before expiry."
        ),
        "supersedes": [],
    },
    "lma_lfa": {
        "key": "lma_lfa",
        "name": "Loan Market Association Leveraged Facility Agreement",
        "subtitle": "LMA template — used in debt financing of UK renewables",
        "version": "2024 update",
        "published": "2024-03-01",
        "effective": "2024-03-01",
        "url": "https://www.lma.eu.com/documents-guidelines",
        "notes": (
            "LMA templates are iteratively updated; Princeps should state 'LMA LFA, "
            "current as at <date>' because the LMA releases incremental amendments."
        ),
        "supersedes": [],
    },
}


# ---------------------------------------------------------------------------
# NPPF paragraph renumbering (2023 -> December 2024)
# ---------------------------------------------------------------------------
#
# Based on the MHCLG December 2024 NPPF and DLUHC 2023 edition. Not exhaustive
# — extend as further citations come up. Old para numbers are from the
# December 2023 edition; new numbers are from December 2024.

NPPF_PARA_MAP: Dict[int, int] = {
    11: 11,
    47: 47,
    83: 85,
    84: 86,
    85: 87,
    119: 123,
    129: 136,
    130: 139,
    135: 144,
    152: 162,
    154: 165,
    155: 166,
    157: 167,
    158: 168,
    161: 171,
    162: 172,
    164: 175,
    174: 187,
    177: 182,
    180: 193,
    186: 187,
    197: 212,
}


# Semantic key -> current (Dec 2024) NPPF paragraph reference. Use via
# :func:`nppf_para` so callers don't inline paragraph numbers. When the
# NPPF Dec 2025 revision lands, update this table in one place.
#
# Keys follow SCREAMING_SNAKE_CASE conventions mapping to the planning
# policy topic, e.g. "BMV" (Best and Most Versatile agricultural land),
# "GREEN_BELT", "AONB" (National Landscape), "SSSI", "ANCIENT_WOODLAND",
# "PRE_APP_CONSULTATION". Values are the raw paragraph citation fragment
# (e.g. "187", "162-167", "40-46", "187(b)") without the "NPPF ... para"
# prefix — that is added by :func:`nppf_para`.

NPPF_SEMANTIC_PARA_MAP: Dict[str, str] = {
    # --- Best and Most Versatile agricultural land (was 2023 para 174(b)
    # / 2021 para 186; Dec 2024 edition renumbered to para 187 footnote).
    "BMV": "187",
    "BMV_b": "187(b)",
    "BMV_FOOTNOTE": "footnote 63",  # 2021 footnote 62 -> Dec 2024 footnote 63
    # --- Green Belt (Section 13). 2021 paras 152-157 -> Dec 2024 162-167.
    "GREEN_BELT": "162-167",
    "GREEN_BELT_VSC": "162-167",
    "GREEN_BELT_SECTION": "Section 13",
    "GREEN_BELT_INAPPROPRIATE": "154",  # renumbered from 2021 para 147/148
    # --- Protected landscapes (AONB / National Landscape). 2021 para 177
    # -> Dec 2024 para 182.
    "AONB": "182",
    "NATIONAL_LANDSCAPE": "182",
    "PROTECTED_LANDSCAPE": "182-183",
    # --- Sites of Special Scientific Interest. 2021 para 180 -> 187.
    "SSSI": "187",
    "SSSI_A": "187(a)",
    # --- Ancient woodland / irreplaceable habitat. Dec 2024 para 187(c).
    "ANCIENT_WOODLAND": "187(c)",
    "IRREPLACEABLE_HABITAT": "187(c)",
    # --- Pre-application engagement. 2021 paras 39-46 -> Dec 2024 40-46.
    "PRE_APP_CONSULTATION": "40-46",
    "PRE_APP": "40-46",
    # --- Renewables / low-carbon policy block. 2021 para 158 -> 167/168;
    # 2021 para 154 -> 165; 2021 para 152 -> 162.
    "RENEWABLES": "165",
    "CLIMATE_CHANGE": "162",
    "SUITABLE_AREAS": "167",
    # --- Flood risk Sequential and Exception tests. Dec 2024 para 180.
    "FLOOD_SEQUENTIAL_EXCEPTION": "180",
    # --- Planning range for BMV / environment chapter (was 152-168).
    "range_planning": "162-175",
    "RANGE_PLANNING": "162-175",
    "range_green_belt": "162-167",
    "range_environment": "180-193",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def all_keys() -> List[str]:
    """Return the sorted list of registry keys."""
    return sorted(REGULATIONS.keys())


def get(key: str) -> Dict:
    """Return the registry record for ``key``.

    Raises KeyError if the key is unknown — callers should never silently
    fall back to an inlined version string.
    """
    try:
        return REGULATIONS[key]
    except KeyError as exc:
        raise KeyError(
            f"Unknown regulatory key {key!r}. Known keys: {', '.join(all_keys())}"
        ) from exc


def cite(key: str, include_url: bool = False) -> str:
    """Return a one-line human-readable citation for ``key``.

    Example:
        >>> cite("g99")
        'Engineering Recommendation G99, Issue 2 (10 March 2025)'
    """
    rec = get(key)
    parts = [rec["name"], rec["version"]]
    if rec.get("effective"):
        parts.append(f"(effective {rec['effective']})")
    base = ", ".join(parts[:2]) + " " + parts[2] if len(parts) == 3 else ", ".join(parts)
    if include_url and rec.get("url"):
        base = f"{base} — {rec['url']}"
    return base


def nppf_para(key: str, ref_date: Optional[date] = None) -> str:
    """Return a full citation string for a semantic NPPF paragraph key.

    Example:
        >>> nppf_para("BMV")
        'NPPF Dec 2024 para 187'
        >>> nppf_para("GREEN_BELT")
        'NPPF Dec 2024 paras 162-167'
        >>> nppf_para("GREEN_BELT_SECTION")
        'NPPF Dec 2024 Section 13'

    Parameters
    ----------
    key : str
        Semantic key from :data:`NPPF_SEMANTIC_PARA_MAP` (case-insensitive on
        the canonical form). Raises KeyError for unknown keys — callers
        should never silently fall back to an inline paragraph number.
    ref_date : date | None
        Optional application-acceptance or report-generation date. Reserved
        for future NPPF revision cut-overs (Dec 2025 revision expected
        publication ~ mid-2026). Currently always returns Dec 2024 values;
        callers that need acceptance-date branching should pass ``ref_date``
        so the behaviour can be extended centrally later.
    """
    # Look up by exact key first, then uppercase form for convenience.
    fragment = (
        NPPF_SEMANTIC_PARA_MAP.get(key)
        or NPPF_SEMANTIC_PARA_MAP.get(key.upper() if isinstance(key, str) else key)
    )
    if fragment is None:
        raise KeyError(
            f"Unknown NPPF semantic key {key!r}. "
            f"Known keys: {', '.join(sorted(NPPF_SEMANTIC_PARA_MAP.keys()))}"
        )

    nppf_rec = REGULATIONS["nppf"]
    # ref_date reserved for future Dec 2025 revision cut-over. For now the
    # Dec 2024 edition is authoritative regardless of ref_date.
    _ = ref_date

    # "Section 13" / "footnote 63" are not paragraph references — use a
    # different connector.
    low = fragment.lower()
    if low.startswith("section"):
        return f"NPPF {nppf_rec['version']} {fragment}"
    if low.startswith("footnote"):
        return f"NPPF {nppf_rec['version']} {fragment}"
    plural = "paras" if ("-" in fragment or "," in fragment) else "para"
    return f"NPPF {nppf_rec['version']} {plural} {fragment}"


# NPS EN-1 / EN-3 / EN-5 acceptance-date cut-over.
#
# EN-3 2025 revision is in force from 6 January 2026 (designated) and applies
# to DCO applications ACCEPTED for examination on or after that date. For
# applications accepted before, the Nov 2023 (designated 17 Jan 2024)
# version remains in force. EN-1 / EN-5 2025 revisions were published Nov
# 2025 and similarly apply from their designation in-force date, subject
# to the 21-sitting-day parliamentary period.

_NPS_2025_INFORCE: Dict[str, date] = {
    "en1": date(2025, 11, 12),
    "en3": date(2026, 1, 6),
    "en5": date(2025, 11, 12),
}


def cite_nps(key: str, accepted_on: Optional[date] = None) -> str:
    """Return the NPS citation appropriate for a DCO ``accepted_on`` date.

    If the application was (or will be) accepted for examination on or after
    the 2025 revision in-force date, the 2025 revision is cited. Otherwise
    the superseded Nov 2023 refresh (designated 17 Jan 2024) is cited.

    Example:
        >>> cite_nps("en3", date(2026, 2, 1))  # after 6 Jan 2026
        'National Policy Statement for Renewable Energy Infrastructure (EN-3), 2025 revision (in force 6 Jan 2026)'
        >>> cite_nps("en3", date(2025, 6, 1))  # before 6 Jan 2026
        'National Policy Statement for Renewable Energy Infrastructure (EN-3), November 2023 refresh (designated 17 January 2024)'
    """
    if key not in {"en1", "en3", "en5"}:
        raise KeyError(f"cite_nps only supports en1/en3/en5; got {key!r}")
    rec = get(key)
    cutover = _NPS_2025_INFORCE[key]
    if accepted_on is None or accepted_on >= cutover:
        return cite(key)
    # Pre-cutover — use the Nov 2023 refresh string (still accurate for
    # applications already in-flight).
    return f"{rec['name']}, November 2023 refresh (designated 17 January 2024)"


def validate_citation(key: str, cited_version: str) -> Optional[str]:
    """Return None if ``cited_version`` matches the current registry version.

    Otherwise returns a short warning string — useful in tests or pre-commit
    hooks that scan generated packs for stale version strings.
    """
    rec = get(key)
    if cited_version.strip() == rec["version"]:
        return None
    if cited_version in rec.get("supersedes", []):
        return (
            f"{rec['name']} cited as {cited_version!r} but current is {rec['version']!r} "
            f"(published {rec['published']})."
        )
    return (
        f"{rec['name']} cited as {cited_version!r}; registry current is {rec['version']!r}."
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    for k in all_keys():
        print(f"{k:36s} -> {cite(k)}")
    print()
    print("NPPF para renumbering (old -> new):")
    for old, new in sorted(NPPF_PARA_MAP.items()):
        print(f"  para {old} (2023) -> para {new} (Dec 2024)")
    print()
    print("NPPF semantic paragraph keys:")
    for sk in sorted(NPPF_SEMANTIC_PARA_MAP.keys()):
        print(f"  {sk:32s} -> {nppf_para(sk)}")
    print()
    print("NPS EN-3 cut-over:")
    print(f"  accepted 2025-06-01 -> {cite_nps('en3', date(2025, 6, 1))}")
    print(f"  accepted 2026-02-01 -> {cite_nps('en3', date(2026, 2, 1))}")
    print()
    warn = validate_citation("g99", "Issue 1 Amendment 9")
    print(f"stale-citation check: {warn}")
