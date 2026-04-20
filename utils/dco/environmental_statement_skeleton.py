"""
Environmental Statement (ES) Skeleton — Reg 5(2)(g).

SKELETON ONLY. A full ES is 15 bot-days of specialist chapter work. This
module produces the structural headings, scoping-matrix, chapter stubs and
appendix list required for a PINS-compliant ES submission so that a
lender / tracker can confirm the structure is valid and the prescribed
chapters are present.

Full submission would require:
  - specialist baseline surveys (ecology, landscape, heritage, etc.);
  - receptor identification and significance evaluation per IEMA
    "Guidelines for Environmental Impact Assessment 8th edition (2024)";
  - cumulative-effects assessment per PINS Advice Note 17 (rev. 2024);
  - mitigation register and commitments schedule.

Reference legislation:
  - Infrastructure Planning (Environmental Impact Assessment) Regulations
    2017 (SI 2017/572) — the NSIP-specific EIA regime.
  - Schedule 4 of SI 2017/572 prescribes the information for inclusion
    in an ES.
  - PINS Advice Note 7 (EIA).
  - IEMA Guidelines for EIA 8th ed. (2024).

Citation: "In fulfilment of Regulation 5(2)(g) of the Infrastructure
Planning (Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264), Regulation 14 of the Infrastructure Planning (EIA)
Regulations 2017 (SI 2017/572), and Schedule 4 of those Regulations."
"""

from __future__ import annotations

from datetime import datetime

# Topics per IEMA 8th ed + Schedule 4 SI 2017/572 — standard NSIP ES chapters
STANDARD_ES_TOPICS: list[dict] = [
    {
        "n": 1, "title": "Introduction",
        "schedule_4_ref": "Sched 4 para 1(a)",
        "scoped_in": True,
        "summary": "Introduces the scheme, the applicant, the EIA team, and the structure of the ES.",
    },
    {
        "n": 2, "title": "Non-Technical Summary (NTS)",
        "schedule_4_ref": "Sched 4 para 7",
        "scoped_in": True,
        "summary": "A plain-language summary of the ES, bound as a separate document for public distribution.",
    },
    {
        "n": 3, "title": "Site and Project Description",
        "schedule_4_ref": "Sched 4 para 1(a)-(c)",
        "scoped_in": True,
        "summary": "Describes the site location, Order limits, authorised development, construction programme, operation and decommissioning.",
    },
    {
        "n": 4, "title": "Consideration of Alternatives",
        "schedule_4_ref": "Sched 4 para 2",
        "scoped_in": True,
        "summary": "Reasonable alternatives studied (do-nothing, site options, layout, technology, grid route) and reasons for the selection.",
    },
    {
        "n": 5, "title": "EIA Methodology",
        "schedule_4_ref": "Sched 4 para 4",
        "scoped_in": True,
        "summary": "Overall approach, assessment significance framework (IEMA 2017), cumulative-effects methodology (AN-17).",
    },
    {
        "n": 6, "title": "Landscape and Visual Impact Assessment (LVIA)",
        "schedule_4_ref": "Sched 4 para 4(c)(ii)",
        "scoped_in": True,
        "summary": "Per GLVIA 3rd ed. Baseline, receptors, ZTV, photomontages, significance.",
    },
    {
        "n": 7, "title": "Ecology and Nature Conservation",
        "schedule_4_ref": "Sched 4 para 4(c)(iv)",
        "scoped_in": True,
        "summary": "Phase 1 Habitat Survey, protected species, designated sites, HRA screening (separate doc if needed), BNG interaction.",
    },
    {
        "n": 8, "title": "Cultural Heritage and Archaeology",
        "schedule_4_ref": "Sched 4 para 4(c)(iii)",
        "scoped_in": True,
        "summary": "Designated assets (SMR, HER), setting assessment, buried archaeology, WSI for mitigation.",
    },
    {
        "n": 9, "title": "Water Environment",
        "schedule_4_ref": "Sched 4 para 4(c)(i)",
        "scoped_in": True,
        "summary": "Surface water, groundwater, flood risk (FRA cross-ref), Water Framework Directive assessment.",
    },
    {
        "n": 10, "title": "Ground Conditions and Contamination",
        "schedule_4_ref": "Sched 4 para 4(c)(i)",
        "scoped_in": True,
        "summary": "Geology, hydrogeology, contamination risk assessment, mineral safeguarding.",
    },
    {
        "n": 11, "title": "Air Quality",
        "schedule_4_ref": "Sched 4 para 4(c)(v)",
        "scoped_in": True,
        "summary": "Construction dust per IAQM guidance, operational emissions (generators for DC), sensitive receptors.",
    },
    {
        "n": 12, "title": "Noise and Vibration",
        "schedule_4_ref": "Sched 4 para 4(c)(vi)",
        "scoped_in": True,
        "summary": "Per BS 4142:2014+A1:2019 (operational), BS 5228:2009+A1:2014 (construction), sensitive receptors.",
    },
    {
        "n": 13, "title": "Traffic and Transport",
        "schedule_4_ref": "Sched 4 para 4(c)(vii)",
        "scoped_in": True,
        "summary": "Construction traffic, abnormal loads, CTMP, operational movements, sustainable transport.",
    },
    {
        "n": 14, "title": "Socio-economic",
        "schedule_4_ref": "Sched 4 para 4(d)",
        "scoped_in": True,
        "summary": "Construction employment, operational employment, community benefits, tourism, agricultural holdings.",
    },
    {
        "n": 15, "title": "Climate Change",
        "schedule_4_ref": "Sched 4 para 4(f)",
        "scoped_in": True,
        "summary": "In-use GHG footprint, embodied carbon, resilience to climate change per IEMA 2020 Climate Change guide.",
    },
    {
        "n": 16, "title": "Major Accidents and Disasters",
        "schedule_4_ref": "Sched 4 para 8",
        "scoped_in": True,
        "summary": "Vulnerability of the project to major accidents and disasters, including cyber-physical risks where relevant.",
    },
    {
        "n": 17, "title": "Cumulative Effects",
        "schedule_4_ref": "Sched 4 para 5(e)",
        "scoped_in": True,
        "summary": "Per PINS Advice Note 17 — long list / short list / ZoI-based identification of other developments, cumulative assessment.",
    },
    {
        "n": 18, "title": "Interaction Between Effects",
        "schedule_4_ref": "Sched 4 para 5(e)",
        "scoped_in": True,
        "summary": "Identification of effects that interact at a single receptor (e.g. noise + air quality + visual at a dwelling).",
    },
    {
        "n": 19, "title": "Residual Effects Summary",
        "schedule_4_ref": "Sched 4 para 5(f)",
        "scoped_in": True,
        "summary": "Summary table of residual significant effects, tied to the Commitments Register.",
    },
    {
        "n": 20, "title": "Commitments Register",
        "schedule_4_ref": "Sched 4 para 7",
        "scoped_in": True,
        "summary": "Each embedded / additional mitigation commitment, cross-referenced to the draft DCO requirements (Schedule 2).",
    },
]


def build_environmental_statement_skeleton(project: dict) -> dict:
    """Produce the ES skeleton — headings and chapter stubs only."""
    proj_name = project.get("name") or "[Project]"

    chapters = []
    for t in STANDARD_ES_TOPICS:
        chapters.append({
            "n": t["n"],
            "title": f"Chapter {t['n']}: {t['title']}",
            "schedule_4_ref": t["schedule_4_ref"],
            "scoped_in": t["scoped_in"],
            "chapter_stub": [
                "Introduction and scope",
                "Legislation, policy and guidance",
                "Methodology",
                "Baseline conditions",
                "Scoping of impacts",
                "Impact assessment — construction",
                "Impact assessment — operation",
                "Impact assessment — decommissioning",
                "Mitigation",
                "Residual effects",
                "Cumulative and interaction effects",
                "Commitments",
                "Summary",
            ],
            "status": "SKELETON — specialist author TO POPULATE",
            "summary_line": t["summary"],
        })

    return {
        "document_title": "Environmental Statement — SKELETON",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(g) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264), Regulation 14 of the Infrastructure Planning "
            "(Environmental Impact Assessment) Regulations 2017 (SI 2017/572), "
            "and Schedule 4 of those Regulations."
        ),
        "status_banner": (
            "THIS IS A SKELETON. A full Environmental Statement requires "
            "specialist baseline surveys and chapter authorship (~15 bot-days). "
            "The chapter list, Schedule 4 cross-references, standard stub "
            "structure and commitments-register placeholder below are correct "
            "per SI 2017/572 and IEMA Guidelines 8th ed. (2024). Do not submit "
            "this skeleton as a substantive ES."
        ),
        "iema_reference": "IEMA Guidelines for Environmental Impact Assessment 8th edition (2024)",
        "pins_advice_notes": [
            "AN-7 — Environmental Impact Assessment (rev. 2024)",
            "AN-9 — Rochdale Envelope (rev. 2024)",
            "AN-17 — Cumulative Effects Assessment (rev. 2024)",
        ],
        "scoping": {
            "opinion_requested": "[TO POPULATE — scoping opinion request date]",
            "opinion_received": "[TO POPULATE — scoping opinion receipt date]",
            "request_reference": "[TO POPULATE — PINS scoping reference]",
        },
        "peir": {
            "published_date": "[TO POPULATE — PEIR publication date]",
            "consultation_window": "[TO POPULATE — min 28 days per s.47]",
        },
        "chapter_list": chapters,
        "appendices": _standard_appendices(),
        "figures_register": _figures_register(),
        "project_name": proj_name,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _standard_appendices() -> list[dict]:
    return [
        {"id": "A", "title": "EIA Scoping Opinion (PINS) — as received"},
        {"id": "B", "title": "Consultation responses — record of pre-application EIA engagement"},
        {"id": "C", "title": "Technical appendices — Landscape (LVIA tables, photomontages, ZTV, wirelines)"},
        {"id": "D", "title": "Technical appendices — Ecology (Phase 1 Habitat Survey, protected species, BNG metric)"},
        {"id": "E", "title": "Technical appendices — Cultural Heritage (baseline, setting, WSI)"},
        {"id": "F", "title": "Technical appendices — Water (FRA, WFD, Hydrology)"},
        {"id": "G", "title": "Technical appendices — Ground Conditions (Phase 1 desk study)"},
        {"id": "H", "title": "Technical appendices — Air Quality (construction dust, operational)"},
        {"id": "I", "title": "Technical appendices — Noise (construction BS 5228, operational BS 4142)"},
        {"id": "J", "title": "Technical appendices — Traffic and Transport (TA, CTMP)"},
        {"id": "K", "title": "Technical appendices — Socio-economic"},
        {"id": "L", "title": "Technical appendices — Climate Change (GHG, resilience)"},
        {"id": "M", "title": "Commitments Register (machine-readable)"},
        {"id": "N", "title": "Non-Technical Summary (bound separately)"},
        {"id": "O", "title": "Habitats Regulations Assessment (if triggered)"},
    ]


def _figures_register() -> list[dict]:
    return [
        {"id": "Fig 1.1", "title": "Site location"},
        {"id": "Fig 3.1", "title": "Order limits and indicative layout"},
        {"id": "Fig 6.1", "title": "Zone of Theoretical Visibility (ZTV)"},
        {"id": "Fig 6.2–6.8", "title": "Photomontages from representative viewpoints"},
        {"id": "Fig 7.1", "title": "Phase 1 Habitat Survey"},
        {"id": "Fig 7.2", "title": "Designated nature conservation sites within 10 km"},
        {"id": "Fig 8.1", "title": "Heritage assets within study area"},
        {"id": "Fig 9.1", "title": "Flood zones and surface water features"},
        {"id": "Fig 11.1", "title": "Air quality sensitive receptors"},
        {"id": "Fig 12.1", "title": "Noise sensitive receptors"},
        {"id": "Fig 13.1", "title": "Construction traffic routeing"},
        {"id": "Fig 17.1", "title": "Cumulative schemes — long list"},
    ]
