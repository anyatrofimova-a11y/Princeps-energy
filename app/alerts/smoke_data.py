"""
app/alerts/smoke_data.py — Dev-mode smoke-data loader for Princeps Alerts.

Seeds ~30 realistic UK energy documents into the ``documents`` table so the
POST /api/alerts/query/stream endpoint has something substantive to reason
over in local / demo deploys. Without this, a fresh DB has zero documents,
the ingestion workers may not have run, and Claude Sonnet 4.6 will return
generic prose rather than grounded answers — which looks like mock mode
from the user's perspective.

Gated behind env flag ``PRINCEPS_LOAD_SMOKE_DOCS`` (default off in prod,
expected on in dev). Idempotent via ``ON CONFLICT (source_url) DO NOTHING``
so repeated startups are cheap no-ops.

Topics covered (≥3 each, matching the frontend mock corpus topic space):
  - Data centre approvals (Slough, Hampshire, Manchester, West London,
    Cambridge)
  - AR7 CfD parameters / results / Pot 1/2/3
  - Gate 2 / TM04+ milestones + PAW1 results
  - DNO ECR headroom deltas (UKPN, SSEN, SPEN, NGED, NPG, ENWL)
  - NSIP DCO applications + decisions
  - BESS planning applications
  - Corporate PPA announcements
  - HSE COMAH BESS incidents
  - REMA / Ofgem code modifications
  - NESO TEC register deltas

Call site: ``app/startup.py`` — invoked from ``launch_background_tasks``
if the env flag is true.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

log = logging.getLogger("princeps.alerts.smoke")


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

# Spread published_at across the last 90 days so date filters behave.
_NOW = datetime.now(timezone.utc)


def _days_ago(n: int) -> datetime:
    return _NOW - timedelta(days=n)


# Each entry: dict matching the ``documents`` row shape we persist.
# ``topic_tags`` are jsonb arrays and line up with alert source_filter tags.
# geometry uses rough UK lon/lat points where a site is identifiable, else None.
_CORPUS: list[dict[str, Any]] = [
    # ── Data-centre approvals (5) ──────────────────────────────────────────
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/dc-slough-2026-q1-approval",
        "title": "Slough Borough Council approves 180MW hyperscaler data-centre campus",
        "filing_type": "lpa_decision",
        "commission_authority": "Slough Borough Council",
        "published_at": _days_ago(7),
        "body_text": (
            "Slough Borough Council has resolved to grant planning permission for a "
            "180MW data-centre campus at the former Horlicks factory site, subject "
            "to a Section 106 agreement covering biodiversity net gain (10% on-site "
            "uplift), heat-recovery to the adjacent district-heating network, and a "
            "1.2 PUE design cap. The operator is understood to be a top-3 US "
            "hyperscaler, though the applicant SPV remains unnamed on the public "
            "register. Grid connection has been secured against SSEN's Iver 400kV "
            "substation, with a 2028 energisation date confirmed in the TEC register.\n\n"
            "Members raised concerns about cumulative load on the West London grid "
            "corridor, which remains subject to the 2023 SSEN moratorium. Officers "
            "responded that the 2026 NGET reinforcement schedule releases 450MW of "
            "incremental capacity by Q3 2027, sufficient to absorb this and two "
            "adjacent committed schemes."
        ),
        "topic_tags": ["data_centre", "hyperscaler", "lpa_decision", "slough", "west_london"],
        "geom_lon": -0.5991, "geom_lat": 51.5105,
    },
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/dc-hampshire-basingstoke-50mw",
        "title": "Basingstoke & Deane approves 50MW data-centre at Chineham Business Park",
        "filing_type": "lpa_decision",
        "commission_authority": "Basingstoke and Deane Borough Council",
        "published_at": _days_ago(19),
        "body_text": (
            "Basingstoke and Deane has approved a 50MW data-centre at Chineham "
            "Business Park on appeal from the applicant, reversing the committee's "
            "May refusal on landscape and heritage grounds. The Inspector gave "
            "decisive weight to the designated status of the NPS EN-1 (2024) "
            "security-of-supply objective and the applicant's BNG plan delivering "
            "12% off-site uplift at Fobdown Farm (Hampshire Wildlife Trust "
            "registered). Connection is via SSEN Basingstoke 132kV, secured at "
            "Gate 1 in 2023 and upgraded to Gate 2 in March 2026."
        ),
        "topic_tags": ["data_centre", "hampshire", "planning_appeal", "en1", "bng"],
        "geom_lon": -1.0876, "geom_lat": 51.2867,
    },
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/dc-manchester-trafford-240mw-pre-app",
        "title": "Trafford pre-application advice: 240MW data-centre at Carrington",
        "filing_type": "pre_application",
        "commission_authority": "Trafford Council",
        "published_at": _days_ago(34),
        "body_text": (
            "Trafford Council officers have issued pre-application advice on a "
            "240MW data-centre at the Carrington Regeneration Area, former Shell "
            "petrochemical site. The officers note the scheme would likely cross "
            "the NSIP threshold under the 50MW generation test once the proposed "
            "on-site gas peaker is included, and recommend the applicant engage "
            "PINS on a voluntary direction under s35 of the Planning Act 2008. "
            "ENWL have indicated a connection offer is achievable by 2029 subject "
            "to the Carrington Moor 400/132kV substation reinforcement."
        ),
        "topic_tags": ["data_centre", "manchester", "hyperscaler", "pre_application", "nsip"],
        "geom_lon": -2.4128, "geom_lat": 53.4239,
    },
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/dc-westlondon-hillingdon-refusal",
        "title": "Hillingdon refuses 90MW DC extension citing West London moratorium",
        "filing_type": "lpa_decision",
        "commission_authority": "London Borough of Hillingdon",
        "published_at": _days_ago(11),
        "body_text": (
            "London Borough of Hillingdon refused a 90MW extension to an existing "
            "data-centre campus at Stockley Park. Members cited the West London "
            "grid moratorium and the absence of a signed connection offer. The "
            "decision notice refers to SSEN's confirmation letter that no firm "
            "offer can be issued before 2031 under the current queue position. "
            "The applicant has 6 months to lodge a s78 appeal."
        ),
        "topic_tags": ["data_centre", "west_london_moratorium", "west_london", "refusal", "hyperscaler"],
        "geom_lon": -0.4527, "geom_lat": 51.5058,
    },
    {
        "source": "pins_nsip",
        "source_url": "https://smoke.princeps.test/docs/dc-cambridge-nsip-acceptance",
        "title": "PINS accepts DCO application for 310MW Cambridge compute cluster",
        "filing_type": "nsip_acceptance",
        "commission_authority": "Planning Inspectorate",
        "published_at": _days_ago(3),
        "body_text": (
            "The Planning Inspectorate has accepted a DCO application (EN070012) "
            "for a 310MW AI / HPC compute cluster at Waterbeach, Cambridgeshire. "
            "The scheme includes a dedicated 400kV grid connection to NGET's "
            "Burwell substation and an on-site 180MW gas-reciprocating "
            "peaking plant. Examination is scheduled to open in July 2026 with a "
            "six-month window. This is the fourth DC-led NSIP accepted under "
            "the post-2024 s14(3A) direction by SoS."
        ),
        "topic_tags": ["data_centre", "nsip_dco", "cambridge", "ai_growth_zone", "aigz"],
        "geom_lon": 0.2137, "geom_lat": 52.2693,
    },

    # ── AR7 CfD (3) ─────────────────────────────────────────────────────────
    {
        "source": "desnz_cfd",
        "source_url": "https://smoke.princeps.test/docs/ar7-allocation-framework-jan-2026",
        "title": "AR7 allocation framework published — revised strike prices, Pot 1/2/3 splits",
        "filing_type": "ar7_allocation_framework",
        "commission_authority": "DESNZ",
        "published_at": _days_ago(85),
        "body_text": (
            "DESNZ has published the AR7 allocation framework (6 January 2026). "
            "Administrative strike prices set at £58/MWh (solar, fixed-bottom "
            "offshore wind in Pot 3), £98/MWh (floating offshore wind), £140/MWh "
            "(geothermal / tidal stream). Pot 1 (established: solar, onshore "
            "wind, hydro) budget is £180m/yr. Pot 2 (emerging: floating offshore, "
            "geothermal, tidal, remote island wind) budget £220m/yr. Pot 3 "
            "(fixed-bottom offshore wind) ringfenced at £1.1bn/yr. Storage and "
            "hybrid eligibility updated: co-located BESS up to 2h duration may "
            "bid on the metered generation node. Applications open 3 March 2026, "
            "close 14 April 2026."
        ),
        "topic_tags": ["ar7", "cfd_round", "solar", "offshore_wind", "storage_eligibility"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "desnz_cfd",
        "source_url": "https://smoke.princeps.test/docs/ar7-results-day-1",
        "title": "AR7 Pot 1 results — 5.6GW solar cleared at £52/MWh",
        "filing_type": "ar7_result",
        "commission_authority": "DESNZ",
        "published_at": _days_ago(40),
        "body_text": (
            "AR7 Pot 1 cleared 5.6GW of solar PV at an average strike price of "
            "£52/MWh (2012 real). The clearing price represents a 7% decrease "
            "against the AR6 Pot 1 clearing price, driven by competitive "
            "pressure and improved module economics. Ten projects were awarded, "
            "ranging from 50MW (Swaffham Prior, Anglian Water) to 720MW "
            "(Cleve Hill Solar Park phase 2). Three co-located BESS components "
            "were eligible and awarded, representing 240MW / 480MWh of storage "
            "on the metered gen-node. Delivery year 2028/29."
        ),
        "topic_tags": ["ar7", "cfd_round", "solar", "pot_1", "colocation"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "desnz_cfd",
        "source_url": "https://smoke.princeps.test/docs/ar7-pot2-results",
        "title": "AR7 Pot 2 results — 1.2GW floating offshore at £94/MWh",
        "filing_type": "ar7_result",
        "commission_authority": "DESNZ",
        "published_at": _days_ago(40),
        "body_text": (
            "AR7 Pot 2 awarded 1.2GW of floating offshore wind to the Green "
            "Volt, Cenos and Salamander schemes at clearing prices between "
            "£92/MWh and £96/MWh (2012 real). Total budget committed: £189m/yr. "
            "A separate £12m ringfence for geothermal was fully subscribed. "
            "Tidal stream awarded 58MW across 4 projects at £135/MWh, below "
            "the £140/MWh ASP. Delivery years range 2030-2033."
        ),
        "topic_tags": ["ar7", "cfd_round", "floating_offshore", "pot_2", "geothermal"],
        "geom_lon": None, "geom_lat": None,
    },

    # ── Gate 2 / TM04+ / PAW1 (3) ──────────────────────────────────────────
    {
        "source": "neso",
        "source_url": "https://smoke.princeps.test/docs/paw1-results-batch-a",
        "title": "PAW1 Batch A results — 12GW solar / BESS Gate 2 offers issued",
        "filing_type": "gate2_decision",
        "commission_authority": "NESO",
        "published_at": _days_ago(48),
        "body_text": (
            "NESO has published PAW1 (Prioritisation Assessment Window 1) Batch A "
            "outcomes under the reformed Gate 2 process. 12.4GW of solar and "
            "BESS projects received Gate 2 connection offers, against 8.7GW "
            "that failed the Strategic Spatial Energy Plan (SSEP) alignment "
            "test. Notable outcomes: 4 projects at the ≥300MW class secured "
            "Gate 2 at SPT Torness, SPEN Denny North, UKPN Bramford East; "
            "the remaining 2.1GW failed the 'in the right place, at the right "
            "time' test under TM04+. Projects that failed have been offered "
            "a Gate 1 queue position with 24-month re-application windows."
        ),
        "topic_tags": ["gate2_decision", "tec_register", "queue", "ssep", "tm04"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "neso",
        "source_url": "https://smoke.princeps.test/docs/paw1-rejection-analysis",
        "title": "PAW1 rejection analysis — why 8.7GW failed the SSEP test",
        "filing_type": "gate2_decision",
        "commission_authority": "NESO",
        "published_at": _days_ago(45),
        "body_text": (
            "NESO has published an analysis of the 8.7GW of PAW1 applications "
            "that failed the Gate 2 SSEP alignment test. Dominant failure "
            "modes: (a) solar in zone N4 / N5 (east coast) where SSEP calls "
            "for onshore wind, (b) BESS co-located with solar in locations "
            "with existing curtailment headroom, and (c) DC demand offers "
            "beyond the Pathway 3 load envelope. NESO reiterates that re-siting "
            "within ±50km of the existing POC, coupled with a technology "
            "hybrid pivot, is the most effective route to Gate 2 at PAW2."
        ),
        "topic_tags": ["gate2_decision", "ssep", "queue", "curtailment"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "neso_tec",
        "source_url": "https://smoke.princeps.test/docs/tec-register-delta-apr-2026",
        "title": "TEC register — April 2026 weekly delta (42 projects, 6.8GW)",
        "filing_type": "tec_delta",
        "commission_authority": "NESO",
        "published_at": _days_ago(5),
        "body_text": (
            "This week's TEC register update: 42 material changes totalling "
            "6.8GW. 18 new Gate 2 offers issued post-PAW1 Batch A (total 4.1GW, "
            "weighted toward SPT and SSEN). 11 offer-withdrawals (2.3GW "
            "released, predominantly at Norwich Main 400kV and Walpole 400kV). "
            "13 milestone-date slippages averaging +14 months. The largest "
            "withdrawal is a 580MW BESS scheme at Drax's Cruachan site, "
            "freeing capacity at SPT Cruachan 275kV for the Dornoch-Loch Buie "
            "reinforcement."
        ),
        "topic_tags": ["tec_register", "queue", "withdrawal", "capacity_release"],
        "geom_lon": None, "geom_lat": None,
    },

    # ── DNO ECR deltas (6, one per DNO) ────────────────────────────────────
    {
        "source": "ukpn",
        "source_url": "https://smoke.princeps.test/docs/ukpn-ecr-apr-2026",
        "title": "UKPN ECR — weekly update: Ipswich East heads to amber",
        "filing_type": "ecr",
        "commission_authority": "UK Power Networks",
        "published_at": _days_ago(4),
        "body_text": (
            "UKPN's Embedded Capacity Register week ending 12 April 2026 shows "
            "Ipswich East primary flipping from green (320MW headroom) to amber "
            "(42MW) following the acceptance of two adjacent BESS applications. "
            "Bramford 132kV added 180MW of solar firm offers. Sudbury and "
            "Braintree remain green with >300MW headroom. 34 connections "
            "progressed from application to offer across the ENA East region."
        ),
        "topic_tags": ["ecr", "ukpn", "bess", "solar", "ipswich"],
        "geom_lon": 1.1556, "geom_lat": 52.0580,
    },
    {
        "source": "ssen",
        "source_url": "https://smoke.princeps.test/docs/ssen-ecr-apr-2026",
        "title": "SSEN ECR — Maidenhead and Bracknell red, Reading amber",
        "filing_type": "ecr",
        "commission_authority": "SSEN",
        "published_at": _days_ago(4),
        "body_text": (
            "SSEN's Embedded Capacity Register published 11 April 2026. "
            "Maidenhead and Bracknell GSPs are at red status (0MW firm "
            "headroom) under the persistent West London moratorium. Reading "
            "flipped from green to amber after accepting a 120MW DC offer at "
            "Reading Green Park. Theale, Slough and Iver remain red. SSEN "
            "notes the 2027 NGET reinforcement at Iver / Laleham will release "
            "c.450MW of incremental capacity, but no firm offers are being "
            "issued for energisation before 2028."
        ),
        "topic_tags": ["ecr", "ssen", "west_london_moratorium", "west_london"],
        "geom_lon": -0.7229, "geom_lat": 51.5217,
    },
    {
        "source": "spen",
        "source_url": "https://smoke.princeps.test/docs/spen-ecr-apr-2026",
        "title": "SPEN ECR — Scottish southern uplands absorb 450MW offers",
        "filing_type": "ecr",
        "commission_authority": "SP Energy Networks",
        "published_at": _days_ago(4),
        "body_text": (
            "SPEN's Embedded Capacity Register for week 15 shows 450MW of new "
            "firm offers in the Scottish southern uplands cluster — Chapelcross, "
            "Ecclefechan and Gretna 132kV. The offers are predominantly solar "
            "(310MW) and BESS (140MW), correlating with PAW1 Batch A outcomes. "
            "SPEN's Hunterston 400/275kV primary continues to act as the "
            "wind-dominated sink, with 1.2GW of firm wind offers year-to-date."
        ),
        "topic_tags": ["ecr", "spen", "scotland", "solar", "bess"],
        "geom_lon": -3.1883, "geom_lat": 55.9533,
    },
    {
        "source": "ngedno",
        "source_url": "https://smoke.princeps.test/docs/nged-ecr-apr-2026",
        "title": "NGED ECR — East Mids primary constraints intensify",
        "filing_type": "ecr",
        "commission_authority": "National Grid Electricity Distribution (NGED)",
        "published_at": _days_ago(4),
        "body_text": (
            "NGED's Embedded Capacity Register for the East Midlands region "
            "shows 12 primaries crossing into amber from green this period. "
            "Kettering, Corby, and Market Harborough primaries all breached "
            "the 90% firm-offer threshold on the back of solar and BESS "
            "planning consents in Q1 2026. NGED has now formally requested "
            "NGET reinforcement at Grendon 400kV to unlock the Northampton "
            "corridor, per LTDS 2026 submission."
        ),
        "topic_tags": ["ecr", "ngedno", "east_midlands", "solar", "bess"],
        "geom_lon": -0.7280, "geom_lat": 52.4381,
    },
    {
        "source": "np",
        "source_url": "https://smoke.princeps.test/docs/npg-ecr-apr-2026",
        "title": "Northern Powergrid ECR — Teesside H2 hub dominates connections",
        "filing_type": "ecr",
        "commission_authority": "Northern Powergrid",
        "published_at": _days_ago(4),
        "body_text": (
            "Northern Powergrid's ECR shows 3 GW of demand connection offers "
            "at Teesside (Lackenby, Greystones, Wilton), associated with the "
            "Teesside Hydrogen Production and Transport & Storage hub. Yorkshire "
            "and the east coast see 210MW of solar firm offers. NPG confirms "
            "its Harker 400kV reinforcement (with NGET) remains on schedule "
            "for energisation by March 2028."
        ),
        "topic_tags": ["ecr", "np", "teesside", "hydrogen", "large_load"],
        "geom_lon": -1.2577, "geom_lat": 54.5751,
    },
    {
        "source": "enwl",
        "source_url": "https://smoke.princeps.test/docs/enwl-ecr-apr-2026",
        "title": "ENWL ECR — Carrington Moor 400/132kV fully subscribed",
        "filing_type": "ecr",
        "commission_authority": "Electricity North West",
        "published_at": _days_ago(4),
        "body_text": (
            "ENWL's weekly ECR reports Carrington Moor 400/132kV primary at "
            "100% firm subscription following the acceptance of two data-centre "
            "connection offers (180MW + 240MW). ENWL has formally triggered a "
            "reinforcement case with NGET, with an in-service date estimated "
            "for 2030. Rochdale and Oldham primaries remain green, with "
            "c.150MW of headroom each."
        ),
        "topic_tags": ["ecr", "enwl", "manchester", "data_centre", "hyperscaler"],
        "geom_lon": -2.4128, "geom_lat": 53.4239,
    },

    # ── NSIP DCO (3) ───────────────────────────────────────────────────────
    {
        "source": "pins_nsip",
        "source_url": "https://smoke.princeps.test/docs/nsip-mallard-pass-decision",
        "title": "Mallard Pass Solar — SoS grants DCO with 12 conditions",
        "filing_type": "dco_decision",
        "commission_authority": "Secretary of State, DESNZ",
        "published_at": _days_ago(22),
        "body_text": (
            "The Secretary of State has granted a Development Consent Order for "
            "the Mallard Pass Solar NSIP (350MW, Rutland / South Kesteven). The "
            "consent attaches 12 conditions, including a 10% BNG uplift delivered "
            "predominantly via hedgerow and species-rich grassland restoration, "
            "a shadow pattern mitigation scheme for the A1, and a requirement to "
            "remove all panels within 6 months of end-of-life. The decision "
            "signals continued SoS support for large-scale solar NSIPs in "
            "agricultural landscapes under the designated EN-3 (2024)."
        ),
        "topic_tags": ["nsip_dco", "solar", "rutland", "bng", "en3"],
        "geom_lon": -0.5167, "geom_lat": 52.6500,
    },
    {
        "source": "pins_nsip",
        "source_url": "https://smoke.princeps.test/docs/nsip-gate-burton-decision",
        "title": "Gate Burton Solar — DCO granted, 500MW consent",
        "filing_type": "dco_decision",
        "commission_authority": "Secretary of State, DESNZ",
        "published_at": _days_ago(42),
        "body_text": (
            "The Secretary of State has granted a DCO for the 500MW Gate Burton "
            "Energy Park (West Lindsey, Lincolnshire). The scheme includes a "
            "co-located 500MW / 1000MWh BESS component, which the decision "
            "letter treats as an associated development under s115(4). The "
            "grant triggers a 24-month window to discharge pre-commencement "
            "conditions, including archaeological surveys and BNG delivery "
            "plan. Challenge window closes 6 weeks from the decision date."
        ),
        "topic_tags": ["nsip_dco", "solar", "bess", "lincolnshire", "colocation"],
        "geom_lon": -0.7500, "geom_lat": 53.3500,
    },
    {
        "source": "pins_nsip",
        "source_url": "https://smoke.princeps.test/docs/nsip-east-anglia-3-examination",
        "title": "East Anglia THREE interconnector — PINS opens examination",
        "filing_type": "nsip_examination",
        "commission_authority": "Planning Inspectorate",
        "published_at": _days_ago(14),
        "body_text": (
            "PINS has formally opened examination on the East Anglia Three "
            "interconnector project (EN070088). The six-month examination will "
            "review the 2.4GW HVDC cable landing at Bawdsey and transmission "
            "route to Bramford. Rule 6 letters have been issued to Natural "
            "England, MMO, Suffolk County Council, East Suffolk Council, and "
            "35 interested parties. The Examining Authority will hold its "
            "Preliminary Meeting on 29 April 2026."
        ),
        "topic_tags": ["nsip_dco", "interconnector", "examination", "suffolk"],
        "geom_lon": 1.4250, "geom_lat": 51.9833,
    },

    # ── BESS planning (3) ──────────────────────────────────────────────────
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/bess-cottam-800mw",
        "title": "Bassetlaw grants 800MW / 1.6GWh BESS at former Cottam power station",
        "filing_type": "lpa_decision",
        "commission_authority": "Bassetlaw District Council",
        "published_at": _days_ago(28),
        "body_text": (
            "Bassetlaw has granted planning permission for an 800MW / 1.6GWh "
            "BESS facility on the decommissioned Cottam coal power station site. "
            "The scheme uses LFP chemistry across 24 Tesla Megapack enclosures "
            "with dedicated fire-suppression and 40m separation from off-site "
            "residential receptors under the 2024 HSE BESS Siting Guidance. "
            "Connection is via the existing Cottam 400kV GSP, repurposing "
            "generation TEC freed by the 2019 plant closure."
        ),
        "topic_tags": ["bess", "battery_storage", "nottinghamshire", "colocation"],
        "geom_lon": -0.7833, "geom_lat": 53.3000,
    },
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/bess-rugby-400mw",
        "title": "Rugby Borough Council refuses 400MW BESS on thermal-runaway grounds",
        "filing_type": "lpa_decision",
        "commission_authority": "Rugby Borough Council",
        "published_at": _days_ago(51),
        "body_text": (
            "Rugby Borough Council has refused planning permission for a 400MW "
            "/ 800MWh BESS near Willoughby, citing inadequate thermal-runaway "
            "mitigation and proximity (180m) to a residential care home. The "
            "decision cites the HSE COMAH BESS Lessons Learned Report 03/2025 "
            "(the Liverpool fire), and notes the applicant's submission did not "
            "meet the updated NFCC BESS siting guidance. The applicant has "
            "indicated intention to appeal."
        ),
        "topic_tags": ["bess", "battery_storage", "battery_fire", "refusal", "warwickshire"],
        "geom_lon": -1.2569, "geom_lat": 52.3727,
    },
    {
        "source": "planit_lpa",
        "source_url": "https://smoke.princeps.test/docs/bess-solar-hybrid-wick",
        "title": "Highland Council approves 120MW solar + 60MW BESS co-located scheme",
        "filing_type": "lpa_decision",
        "commission_authority": "Highland Council",
        "published_at": _days_ago(17),
        "body_text": (
            "Highland Council has approved a co-located 120MW solar + 60MW / "
            "120MWh BESS scheme near Wick, Caithness. The development qualifies "
            "for AR7 Pot 1 under the revised co-location rules (February 2026) "
            "that allow a metered-gen bid if the BESS is AC-coupled and ≤2h "
            "duration. Connection offer held with SSEN at Mybster 132kV "
            "substation, with energisation in Q4 2028 consistent with AR7 "
            "delivery year 2028/29."
        ),
        "topic_tags": ["bess", "solar_plus_bess", "colocation", "scotland", "ar7"],
        "geom_lon": -3.0833, "geom_lat": 58.4500,
    },

    # ── Corporate PPA (3) ──────────────────────────────────────────────────
    {
        "source": "companies_house",
        "source_url": "https://smoke.princeps.test/docs/ppa-microsoft-scottishpower",
        "title": "Microsoft signs 10-year, 2.3TWh/yr PPA with ScottishPower UK portfolio",
        "filing_type": "ppa_announcement",
        "commission_authority": "Companies House / press release",
        "published_at": _days_ago(26),
        "body_text": (
            "Microsoft and ScottishPower have signed a 10-year physical PPA "
            "covering 2.3TWh/yr from a portfolio of UK onshore wind and solar "
            "sites, with first delivery in Q2 2027. The deal is the largest "
            "single corporate PPA signed in the UK to date and is structured "
            "as a pay-as-produced contract with a shape premium of c.£3/MWh "
            "above the baseload curve. Microsoft has disclosed that volumes "
            "will be retired against data-centre load in Ireland and the UK "
            "Midlands."
        ),
        "topic_tags": ["corporate_ppa", "hyperscaler", "hyperscaler_ppa", "microsoft", "onshore_wind"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "companies_house",
        "source_url": "https://smoke.princeps.test/docs/ppa-google-neoen-850gwh",
        "title": "Google signs 850GWh/yr PPA with Neoen for Scottish solar + BESS",
        "filing_type": "ppa_announcement",
        "commission_authority": "Companies House / press release",
        "published_at": _days_ago(63),
        "body_text": (
            "Google has signed an 850GWh/yr physical PPA with Neoen, covering "
            "output from a portfolio of Scottish solar + BESS projects totalling "
            "420MW. The deal is pay-as-produced with a fixed price clause for "
            "the first 5 years (undisclosed, but believed to be c.£54/MWh). "
            "The PPA backs three projects: Cawdor (Highland), Errol (Perth) "
            "and Tealing (Angus), all approved in Scottish DNS 2024-25. "
            "Google has committed to co-locate equivalent BESS capacity with "
            "each generation site."
        ),
        "topic_tags": ["corporate_ppa", "hyperscaler", "hyperscaler_ppa", "google", "solar_plus_bess"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "companies_house",
        "source_url": "https://smoke.princeps.test/docs/ppa-amazon-ocean-winds",
        "title": "Amazon signs 1.8TWh/yr offshore-wind PPA with Ocean Winds",
        "filing_type": "ppa_announcement",
        "commission_authority": "Companies House / press release",
        "published_at": _days_ago(55),
        "body_text": (
            "Amazon (AWS) and Ocean Winds have signed a 15-year physical PPA "
            "covering 1.8TWh/yr from the Moray West offshore wind farm (Moray "
            "Firth, 882MW operational since 2025). Delivery is baseload-shaped "
            "with Ocean Winds taking basis risk. The deal lifts Amazon's "
            "UK-sourced renewable PPA book above 5TWh/yr, making AWS the "
            "largest single corporate PPA offtaker in the UK ahead of "
            "Google and Microsoft on a disclosed-basis."
        ),
        "topic_tags": ["corporate_ppa", "hyperscaler", "hyperscaler_ppa", "amazon", "offshore_wind"],
        "geom_lon": None, "geom_lat": None,
    },

    # ── HSE COMAH BESS incidents (3) ───────────────────────────────────────
    {
        "source": "hse_comah",
        "source_url": "https://smoke.princeps.test/docs/hse-comah-liverpool-bess-report",
        "title": "HSE COMAH Lessons Learned 01/2026 — Liverpool BESS fire root cause",
        "filing_type": "comah_notification",
        "commission_authority": "HSE",
        "published_at": _days_ago(70),
        "body_text": (
            "HSE has published the final Lessons Learned report on the October "
            "2025 Liverpool BESS fire at the Carnegie Road site. Root cause is "
            "identified as a single-cell thermal event propagating across an "
            "NMC battery rack after a BMS software update disabled the cell-level "
            "disconnect function. Key findings: (1) operators using NMC chemistry "
            "should require cell-level disconnect on all racks; (2) remote "
            "firmware pushes must undergo a 48-hour canary rollout; (3) the "
            "NFCC's 40m separation distance is sufficient for a single-rack "
            "event but not for a cascade. Industry response is expected in Q3 "
            "2026."
        ),
        "topic_tags": ["hse_comah", "bess", "battery_fire", "lessons_learned"],
        "geom_lon": -2.9916, "geom_lat": 53.4084,
    },
    {
        "source": "hse_comah",
        "source_url": "https://smoke.princeps.test/docs/hse-comah-improvement-notice-tilbury",
        "title": "HSE serves COMAH improvement notice on Tilbury BESS operator",
        "filing_type": "comah_notification",
        "commission_authority": "HSE",
        "published_at": _days_ago(38),
        "body_text": (
            "HSE has served an improvement notice on the operator of the 100MW "
            "BESS at Tilbury (Essex) under COMAH Regulation 17. The notice "
            "follows an unannounced inspection that identified deficiencies in "
            "the written safety case, specifically (a) inadequate cascade "
            "scenario modelling, (b) no consideration of adjacent LPG storage "
            "tank within 200m, and (c) gaps in the emergency response plan "
            "tabletop exercise record. Operator has 90 days to comply; failure "
            "could trigger a prohibition notice."
        ),
        "topic_tags": ["hse_comah", "bess", "essex", "compliance"],
        "geom_lon": 0.3597, "geom_lat": 51.4653,
    },
    {
        "source": "hse_comah",
        "source_url": "https://smoke.princeps.test/docs/hse-comah-bess-siting-guidance-2026",
        "title": "HSE publishes updated BESS Siting Guidance (v3.0, March 2026)",
        "filing_type": "hse_guidance",
        "commission_authority": "HSE",
        "published_at": _days_ago(49),
        "body_text": (
            "HSE has published v3.0 of the BESS Siting Guidance. Key updates "
            "from v2.1 (2024): (1) minimum separation from occupied residential "
            "receptors increased to 60m for >100MW sites (previously 40m), "
            "(2) mandatory fire-water capacity of 2.5 × rated capacity (MWh) "
            "within 500m for all COMAH BESS, (3) LFP chemistry preferred for "
            "new build; NMC requires explicit justification in the safety case. "
            "The guidance is non-statutory but will be treated as a material "
            "consideration by LPAs per the DCLG 2024 direction."
        ),
        "topic_tags": ["hse_comah", "bess", "battery_storage", "safety_guidance"],
        "geom_lon": None, "geom_lat": None,
    },

    # ── REMA / Ofgem code mods (3) ─────────────────────────────────────────
    {
        "source": "desnz",
        "source_url": "https://smoke.princeps.test/docs/rema-locational-decision-mar-2026",
        "title": "REMA reform — national pricing retained, locational TNUoS expanded",
        "filing_type": "rema_decision",
        "commission_authority": "DESNZ",
        "published_at": _days_ago(47),
        "body_text": (
            "DESNZ has published its REMA reform decision (March 2026). The "
            "headline: UK retains national single-price wholesale markets, "
            "abandoning the zonal pricing option after 18 months of consultation. "
            "Instead, locational signals will be strengthened via expanded "
            "TNUoS bands (increasing from 27 to 60 demand zones, 33 to 75 "
            "generation zones), locational capacity market premiums, and a "
            "new 'shape premium' under Supplier Obligation. Industry reaction "
            "has been divided: generators in Scotland lose the locational "
            "upside, while consumers in the south avoid the retail premium. "
            "Transition implementation from 2027, fully effective 2030."
        ),
        "topic_tags": ["rema", "price_control", "tnuos", "supplier_obligation"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "ofgem",
        "source_url": "https://smoke.princeps.test/docs/ofgem-cmp-431-decision",
        "title": "Ofgem approves CMP431 — negative embedded-benefit restructure",
        "filing_type": "ofgem_decision",
        "commission_authority": "Ofgem",
        "published_at": _days_ago(32),
        "body_text": (
            "Ofgem has approved CUSC modification CMP431, restructuring embedded "
            "benefit payments to distributed generation. The key change: triad "
            "demand credits are abolished in their current form and replaced "
            "with a capacity-weighted locational payment based on the new "
            "REMA TNUoS zones. Implementation is from 1 April 2027. The decision "
            "reduces the embedded benefit value for existing distributed "
            "generators by c.£3-5/MWh, though sites in the south-east may "
            "receive a partial offset via the locational capacity premium."
        ),
        "topic_tags": ["cmp", "ofgem_decision", "tnuos", "rema"],
        "geom_lon": None, "geom_lat": None,
    },
    {
        "source": "ofgem",
        "source_url": "https://smoke.princeps.test/docs/ofgem-gc0166-bess-inertia",
        "title": "Grid Code GC0166 approved — BESS inertia contribution",
        "filing_type": "ofgem_decision",
        "commission_authority": "Ofgem",
        "published_at": _days_ago(81),
        "body_text": (
            "Ofgem has approved Grid Code modification GC0166, formalising "
            "synthetic inertia contribution from BESS above 50MW. The mod "
            "introduces a new Grid Forming (GFM) category with minimum rate of "
            "change of frequency (RoCoF) withstand of 2 Hz/s and a minimum "
            "5-second inertial response window. Existing BESS assets have "
            "until April 2028 to retrofit or opt into a non-firm GFM category. "
            "NESO estimates GC0166 could reduce its £1.6bn/yr inertia procurement "
            "by 40% by 2030."
        ),
        "topic_tags": ["gc", "grid_code", "bess", "inertia", "ofgem_decision"],
        "geom_lon": None, "geom_lat": None,
    },
]


_EXPECTED_MIN = 30


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _stmt_insert() -> str:
    """Return the INSERT statement with positional params."""
    return """
        INSERT INTO documents
            (source, source_url, title, body_text,
             commission_authority, filing_type,
             published_at, topic_tags, geometry)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7, $8::jsonb,
             CASE WHEN $9::double precision IS NOT NULL
                       AND $10::double precision IS NOT NULL
                  THEN ST_SetSRID(ST_MakePoint($9, $10), 4326)::geography
                  ELSE NULL
             END)
        ON CONFLICT (source_url) DO NOTHING
        RETURNING doc_id
    """


async def seed_smoke_docs(pool: asyncpg.Pool) -> int:
    """Insert the smoke-data corpus into ``documents``.

    Idempotent — returns the number of rows actually inserted this call
    (prior rows are left untouched via ``ON CONFLICT (source_url)``).
    """
    assert len(_CORPUS) >= _EXPECTED_MIN, (
        f"_CORPUS has {len(_CORPUS)} rows, expected ≥ {_EXPECTED_MIN}"
    )

    inserted = 0
    try:
        async with pool.acquire() as conn:
            present = await conn.fetchval(
                "SELECT to_regclass('public.documents') IS NOT NULL"
            )
            if not present:
                log.warning("documents table missing — skipping smoke seed")
                return 0

            for row in _CORPUS:
                try:
                    result = await conn.fetchval(
                        _stmt_insert(),
                        row["source"],
                        row["source_url"],
                        row["title"],
                        row["body_text"],
                        row.get("commission_authority"),
                        row.get("filing_type"),
                        row.get("published_at"),
                        json.dumps(row.get("topic_tags") or []),
                        row.get("geom_lon"),
                        row.get("geom_lat"),
                    )
                    if result is not None:
                        inserted += 1
                except Exception:
                    log.exception("smoke seed failed for url=%s", row["source_url"])
    except Exception:
        log.exception("seed_smoke_docs failed")
        return 0

    if inserted:
        log.info("Smoke seed: inserted %d/%d documents", inserted, len(_CORPUS))
    else:
        log.info("Smoke seed: all %d documents already present", len(_CORPUS))
    return inserted


def corpus() -> list[dict[str, Any]]:
    """Return a shallow copy of the corpus (for tests)."""
    return list(_CORPUS)


def should_load() -> bool:
    """Is the env flag set to load smoke data?"""
    return os.getenv("PRINCEPS_LOAD_SMOKE_DOCS", "false").lower() == "true"


__all__ = ["seed_smoke_docs", "corpus", "should_load"]
