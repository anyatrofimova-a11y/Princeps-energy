"""
Explanatory Memorandum — Reg 5(2)(d).

The Explanatory Memorandum explains each article and schedule of the draft
Development Consent Order in plain English, highlighting departures from
published DCO precedent and the reasoning for each power sought.

PINS Advice Note 15 "Drafting Development Consent Orders" (July 2024 rev)
sets out the expected structure. This skeleton follows that layout.

Citation: "In fulfilment of Reg 5(2)(d) of the Infrastructure Planning
(Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

from datetime import datetime


def build_explanatory_memorandum(project: dict, draft_order: dict) -> dict:
    """Return an EM structured to track each article in draft_order."""
    proj_name = project.get("name") or "[Project name — TO POPULATE]"
    order_title = draft_order.get("order_title") or f"The {proj_name} Development Consent Order 20xx"

    article_explanations: list[dict] = []
    for part in draft_order.get("parts", []):
        for art in part.get("articles", []):
            article_explanations.append({
                "part_n": part["n"],
                "part_heading": part["heading"],
                "article_n": art["n"],
                "article_heading": art["heading"],
                "explanation": _explain_article(art["n"], art["heading"]),
                "precedent_cite": _precedent_for(art["n"]),
            })

    schedule_explanations: list[dict] = []
    for sch in draft_order.get("schedules", []):
        schedule_explanations.append({
            "schedule_n": sch["n"],
            "heading": sch["heading"],
            "explanation": _explain_schedule(sch["n"], sch["heading"]),
        })

    return {
        "document_title": "Explanatory Memorandum",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(d) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264, as amended)."
        ),
        "advice_note_citation": "Structured per PINS Advice Note 15 — Drafting Development Consent Orders (rev. 2024).",
        "order_title": order_title,
        "introduction": _introduction(proj_name, order_title),
        "sections": [
            {
                "n": "1",
                "heading": "Introduction and purpose",
                "body": _introduction(proj_name, order_title),
            },
            {
                "n": "2",
                "heading": "The application and scheme overview",
                "body": (
                    f"This Explanatory Memorandum accompanies the application for the {order_title} "
                    f"made to the Secretary of State under section 37 of the Planning Act 2008. "
                    "The scheme is described in the Application Form, Statement of Reasons and "
                    "Environmental Statement. This memorandum sets out the purpose and effect of "
                    "each article of the draft Order and each schedule, and identifies — where "
                    "relevant — the departures from the model DCO provisions at published "
                    "precedents (Sunnica, Gate Burton, Mallard Pass, Longfield Solar, Rampion 2)."
                ),
            },
            {
                "n": "3",
                "heading": "Article-by-article commentary",
                "body": "See the table below. Each article of the draft DCO is explained, with a "
                       "cross-reference to a published precedent DCO where the wording follows "
                       "the standard model, or — where the wording departs — a justification.",
                "articles": article_explanations,
            },
            {
                "n": "4",
                "heading": "Schedule-by-schedule commentary",
                "body": "See the table below.",
                "schedules": schedule_explanations,
            },
            {
                "n": "5",
                "heading": "Departures from the model DCO",
                "body": (
                    "The Order generally follows the model provisions annexed to PINS Advice "
                    "Note 15. The following departures are made: [TO POPULATE — list each "
                    "bespoke provision, justification, and precedent where a similar "
                    "departure has been accepted by the Secretary of State]."
                ),
            },
            {
                "n": "6",
                "heading": "Human Rights considerations",
                "body": (
                    "Where the Order confers powers of compulsory acquisition, the undertaker "
                    "has considered the provisions of the European Convention on Human Rights "
                    "(as given effect by the Human Rights Act 1998), in particular Article 1 "
                    "of the First Protocol (protection of property), Article 8 (respect for "
                    "private and family life) and Article 6 (right to a fair hearing). The "
                    "undertaker's conclusion on proportionality and public interest is set out "
                    "in the Statement of Reasons."
                ),
            },
            {
                "n": "7",
                "heading": "Equalities considerations",
                "body": (
                    "The undertaker has had due regard to the public sector equality duty under "
                    "section 149 of the Equality Act 2010. A full Equality Impact Assessment "
                    "is provided as an appendix to the Environmental Statement."
                ),
            },
        ],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _introduction(proj_name: str, order_title: str) -> str:
    return (
        f"This Explanatory Memorandum has been prepared in accordance with Regulation "
        f"5(2)(d) of the Infrastructure Planning (Applications: Prescribed Forms and "
        f"Procedure) Regulations 2009 (SI 2009/2264). It accompanies the application for "
        f"the {order_title} made under section 37 of the Planning Act 2008. It explains "
        f"the purpose and effect of each article and each schedule of the draft Order and "
        f"is intended to assist the Examining Authority, interested parties and the "
        f"Secretary of State in understanding the Order. It is not itself a legal "
        f"document and in the event of any inconsistency between this memorandum and the "
        f"draft Order, the draft Order takes precedence."
    )


def _explain_article(n: int, heading: str) -> str:
    """Canned plain-English explanation for each standard article number."""
    explanations = {
        1: "Sets the short title and commencement date of the Order, tracking model DCO art. 1.",
        2: "Defines terms used throughout the Order. The defined terms tie back to the deposited plans and the Book of Reference.",
        3: "The principal consent-granting article. Grants development consent for the authorised development described in Schedule 1 within the Order limits, subject to the requirements in Schedule 2.",
        4: "Permits maintenance within the Order limits but prevents maintenance that would cause materially new or materially different environmental effects — consistent with the limits of the Environmental Statement.",
        5: "Authorises use and operation of the generating station (for energy NSIPs). Without this article, consent would only cover construction.",
        6: "The Order operates for the benefit of the undertaker only. This prevents an unintended third party from relying on the consent.",
        7: "Permits transfer of the benefit of the Order (in whole or in part), subject to Secretary of State consent — essential for project finance / SPV structures.",
        8: "Applies the Highways Act 1980 with modifications for any street works. The modifications are in Schedule 3.",
        9: "Grants the undertaker power to carry out street works (breaking up, tunnelling, placing apparatus). Tracks model DCO.",
        10: "Permits temporary street closures during construction. Typical wording with 7-day notice to highway authority.",
        11: "Permits formation or improvement of means of access per Schedule 4.",
        12: "Permits discharge of water to watercourses or sewers with owner / undertaker consent. Essential for SuDS discharge during operation.",
        13: "Permits protective works (e.g. underpinning, monitoring) to buildings within the Order limits.",
        14: "Permits pre-construction survey access including trial holes. Limited to land shown on the land plans.",
        15: "Permits felling or lopping of trees and removal of hedgerows necessary for construction or operation. Hedgerows subject to Schedule 8.",
        16: "Core CA power — acquisition of land required for the authorised development. Engaged only if CA is sought.",
        17: "Power to acquire new rights (e.g. cable easements) as well as existing rights.",
        18: "Extinguishes private rights over land subject to CA (e.g. easements, restrictive covenants) as of the acquisition / entry date.",
        19: "Applies the Compulsory Purchase (Vesting Declarations) Act 1981 as if the Order were a CPO.",
        20: "Permits subsoil- or airspace-only acquisition — reduces CA burden where only cable subsoil or overhead line airspace is required.",
        21: "Street rights — permits acquisition of rights over/under/along a street.",
        22: "Temporary possession of land for construction (laydown, haul routes). Land returned on completion subject to Schedule 6.",
        23: "5-year time limit on CA powers, consistent with PA 2008 s.154.",
        90: "Preserves landlord and tenant enactments where relevant.",
        91: "Treats the Order as specific planning permission under TCPA 1990 s.264(3)(a) — required to bring the authorised development within operational land.",
        92: "Statutory nuisance defence for construction noise under EPA 1990 s.82 where noise complies with a s.60 Control of Pollution Act 1974 notice.",
        93: "Brings Schedule 9 (protective provisions) into effect.",
        94: "Post-making certification of the deposited documents — required per PINS Advice Note 15.",
        95: "Service of notices by post, delivery or electronic means with consent.",
        96: "Arbitration mechanism for disputes — Arbitration Act 1996 single arbitrator.",
        97: "Brings Schedule 2 (requirements) into effect — the requirements attach to the consent per PA 2008 s.120.",
    }
    return explanations.get(n, f"[TO POPULATE — explanation for Article {n} '{heading}'.]")


def _precedent_for(n: int) -> str:
    """Typical published precedent DCO reference for each article number."""
    if n <= 2:
        return "Model DCO art. 1-2 (PINS AN-15)"
    if 3 <= n <= 7:
        return "Sunnica Energy Farm DCO 2024, arts 3-7"
    if 8 <= n <= 11:
        return "Mallard Pass Solar Farm DCO 2024, arts 8-11"
    if 12 <= n <= 15:
        return "Gate Burton Energy Park DCO 2024, arts 12-15"
    if 16 <= n <= 23:
        return "Longfield Solar Farm DCO 2024, arts 16-23 (where CA sought)"
    if n >= 90:
        return "Sunnica Energy Farm DCO 2024, final articles"
    return "Model DCO (PINS AN-15)"


def _explain_schedule(n: int, heading: str) -> str:
    explanations = {
        1: "Describes the authorised development (Work No. 1, 2, …) and ties each work number to a location on the Works Plans.",
        2: "The conditions (requirements) attaching to the consent. Requirements are equivalent to planning conditions under TCPA 1990.",
        3: "Street works schedule — each street subject to street works is listed with OS grid reference.",
        4: "Access and rights of way schedule — new and modified means of access.",
        5: "Land in which only new rights may be acquired (Book of Reference Category 2 — e.g. cable easements).",
        6: "Land subject to temporary possession (Book of Reference Category 3 — e.g. construction compounds).",
        7: "Compensation modifications for acquisition of new rights.",
        8: "Hedgerows schedule — each hedgerow subject to removal, cross-referenced to the Hedgerows Regulations 1997 assessment.",
        9: "Protective provisions — negotiated with each statutory undertaker (NGET, DNO, WASC, etc).",
        10: "List of deposited documents to be certified after the Order is made.",
        11: "Deemed Marine Licence — only where works below MHWS or in coastal waters.",
    }
    return explanations.get(n, f"[TO POPULATE — explanation for Schedule {n} '{heading}'.]")
