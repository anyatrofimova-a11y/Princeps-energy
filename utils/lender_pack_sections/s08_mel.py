"""Section 8 — Material Event List (MEL).

Also known in US market as the "Material Adverse Events" schedule or the
"Risk Register for the Credit". Framed against PRA SS31/15 risk taxonomy
(Internal Capital Adequacy Assessment Process), this section assigns each
material risk a likelihood × impact rating, a mitigation, and a residual
rating that sets the lender's required reserving / covenant headroom.

Technology, regulatory, counterparty, construction and revenue risks each
get their own row. Each row references the section of the pack where the
underlying evidence lives (TDDR, CP/CS, Covenants).
"""
from __future__ import annotations

from typing import Any


_RATING_SCORE = {"low": 1, "medium": 2, "high": 3}


def _residual(likelihood: str, impact: str, mitigation_strength: str) -> str:
    base = _RATING_SCORE.get(likelihood, 2) * _RATING_SCORE.get(impact, 2)
    reduction = _RATING_SCORE.get(mitigation_strength, 2)
    net = max(1, base - reduction)
    if net <= 2:
        return "low"
    if net <= 4:
        return "medium"
    return "high"


def build_material_event_list(
    technology: str,
    capacity_mw: float,
    has_grid_offer: bool,
    has_planning_consent: bool,
    has_ppa: bool,
) -> dict[str, Any]:
    """Assemble the MEL rows for the credit.

    Rows are project-agnostic in structure; the likelihood / mitigation
    wording adapts to the technology and consent status fed in.
    """

    is_bess = technology == "bess"
    is_dc = technology == "dc"

    rows: list[dict[str, Any]] = [
        {
            "event": "Technology performance shortfall",
            "category": "Technology",
            "likelihood": "low" if not is_bess else "medium",
            "impact": "medium",
            "description": (
                "Generation / cycling performance below bankable P90 case. "
                "Degradation above OEM warranty or higher-than-expected "
                "outages could erode CFADS."
            ),
            "mitigation": (
                "Bankable resource assessment (IEC 61400-12 for wind / IEC 61724 "
                "for solar / IEC 62933 for BESS); Tier-1 OEM with 10-year "
                "warranty; independent LTA performance sign-off at COD; "
                "P90-case covenant threshold; DSRA funded at close."
            ),
            "mitigation_strength": "high",
            "evidence_ref": "§9 TDDR — Performance & warranty",
        },
        {
            "event": "Regulatory / CfD framework change",
            "category": "Regulatory",
            "likelihood": "medium",
            "impact": "medium",
            "description": (
                "Change to TNUoS / BSUoS / CfD terms, capacity market reform, "
                "or Carbon Price Floor affecting capture price. "
                "Ofgem Targeted Charging Review and Balancing Services "
                "Charges Reform still evolving."
            ),
            "mitigation": (
                "Long-term PPA (10y+) hedges exposure; CfD (AR6) pot provides floor; "
                "change-in-law clauses in PPA pass-through; covenant headroom "
                "sized to withstand 20% revenue downshift (see §5 Downside)."
            ),
            "mitigation_strength": "medium",
            "evidence_ref": "§7 Covenants / PRA SS31/15 risk mapping",
        },
        {
            "event": "Counterparty credit deterioration (offtaker)",
            "category": "Counterparty",
            "likelihood": "low" if has_ppa else "high",
            "impact": "high",
            "description": (
                "Offtaker downgrade below investment grade or bankruptcy. "
                "Loss of PPA triggers merchant exposure and DSCR compression."
            ),
            "mitigation": (
                "Offtaker must be IG-rated (min BBB-/Baa3) at close; "
                "PPA replacement-value provisions; step-in rights in Direct "
                "Agreement with offtaker; Agent monitoring of counterparty "
                "credit on a quarterly basis."
            ),
            "mitigation_strength": "high" if has_ppa else "low",
            "evidence_ref": "§9 TDDR — Commercial DD; §13 Security",
        },
        {
            "event": "Construction cost overrun / delay",
            "category": "Construction",
            "likelihood": "medium",
            "impact": "high",
            "description": (
                "EPC programme delay, cost overrun, or contractor insolvency. "
                "Delay to COD impacts CfD strike date; overrun erodes equity."
            ),
            "mitigation": (
                "Fixed-price EPC wrap (LMA Bankability Note); 10% liquidated damages; "
                "10% performance bond; parent company guarantee from EPC; "
                "5% contingency in sources & uses; Lenders' Technical Adviser "
                "monthly progress review; drawstop if 60-day slip."
            ),
            "mitigation_strength": "high",
            "evidence_ref": "§10 CP — EPC wrap executed; §9 TDDR",
        },
        {
            "event": "Grid connection delay",
            "category": "Construction",
            "likelihood": "medium" if has_grid_offer else "high",
            "impact": "high",
            "description": (
                "DNO-side delay, queue re-sequencing under NESO TMO4+ Gate 2, "
                "or unforeseen reinforcement. Without energisation there is "
                "no CFADS."
            ),
            "mitigation": (
                "Accepted connection offer with defined programme; ANM / CMZ "
                "option as fallback; connection delay LAD in EPC; "
                "NESO SOF tracking monthly."
            ),
            "mitigation_strength": "high" if has_grid_offer else "low",
            "evidence_ref": "§10 CP — Grid offer accepted; §9 TDDR",
        },
        {
            "event": "Planning consent challenge / conditions breach",
            "category": "Regulatory",
            "likelihood": "low" if has_planning_consent else "medium",
            "impact": "high",
            "description": (
                "Judicial review of the planning decision, or inability to "
                "discharge a pre-commencement condition on programme."
            ),
            "mitigation": (
                "6-week JR window already expired (or near-expiry); "
                "pre-commencement conditions tracked as CPs; community "
                "benefit payment schedule in place."
            ),
            "mitigation_strength": "medium" if has_planning_consent else "low",
            "evidence_ref": "§10 CP — Planning discharged",
        },
        {
            "event": "Merchant / capture-price compression",
            "category": "Revenue",
            "likelihood": "medium",
            "impact": "medium",
            "description": (
                "Wholesale basis risk, cannibalisation of solar peak prices, "
                "or BSUoS/TNUoS reform compresses capture price."
            ),
            "mitigation": (
                "PPA floor price (minimum tenor 10y); BSUoS pass-through "
                "where available; merchant tail limited to ≤30% of tenor CFADS; "
                "annual re-forecasting in base case covenant model."
            ),
            "mitigation_strength": "medium",
            "evidence_ref": "§5 Downside; §6 Breakeven",
        },
        {
            "event": "BESS augmentation cost (year 10+)",
            "category": "Technology",
            "likelihood": "medium" if is_bess else "low",
            "impact": "medium",
            "description": (
                "Cell degradation requires augmentation or cell replacement "
                "at year 10 to maintain guaranteed energy throughput."
            ),
            "mitigation": (
                "Augmentation reserve in opex (15% of opex p.a.); OEM "
                "augmentation contract with capped £/MWh top-up price; "
                "Maintenance Reserve Account (MRA) funded from operations."
            ),
            "mitigation_strength": "medium",
            "evidence_ref": "§4 Base case (augmentation in opex)",
        },
        {
            "event": "Insurance event — CAR/EAR, natural catastrophe, cyber",
            "category": "Operational",
            "likelihood": "low",
            "impact": "medium",
            "description": (
                "Construction All Risks, Delay in Start-Up, or property damage "
                "event. Cyber event affecting control systems."
            ),
            "mitigation": (
                "CAR/EAR bound prior to drawdown; DSU insurance with 12-month "
                "indemnity; broker letter of undertaking; annual insurance "
                "certificate to Agent; cyber insurance for operational phase."
            ),
            "mitigation_strength": "high",
            "evidence_ref": "§10 CP — Insurances bound",
        },
    ]

    # Bolt on DC-specific risk line when relevant
    if is_dc:
        rows.append({
            "event": "Hyperscale tenant concentration / take-or-pay default",
            "category": "Revenue",
            "likelihood": "low",
            "impact": "high",
            "description": (
                "1–2 tenant concentration for hyperscale tier creates single-"
                "point-of-failure on capacity revenue."
            ),
            "mitigation": (
                "Take-or-pay ≥85% of contracted MW; tenant IG-rated; "
                "parent company guarantee; assignment rights to lenders; "
                "replacement tenant list pre-agreed."
            ),
            "mitigation_strength": "high",
            "evidence_ref": "§4 Base case — take-or-pay floor",
        })

    # Add residual rating per row
    for r in rows:
        r["residual_rating"] = _residual(
            r["likelihood"], r["impact"], r["mitigation_strength"],
        ).upper()

    return {
        "rows": rows,
        "framework": "PRA SS31/15 ICAAP risk taxonomy / LMA Bankability Note 2024",
        "legend": {
            "likelihood": "Low / Medium / High (annualised)",
            "impact": "Low / Medium / High (CFADS impact)",
            "residual": "Net rating after mitigation; drives covenant headroom and reserving",
        },
        "citation": "PRA Supervisory Statement SS31/15 — ICAAP; LMA Bankability Checklist.",
    }
