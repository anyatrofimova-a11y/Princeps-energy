"""Section 5 — Risk matrix.

5×5 likelihood × impact grid. 15–25 rows per 2026 IC standard §4a; each
row mapped to a CP, CS, insurance clause, or covenant (the `linked_to`
field). Residual rating shown after mitigation.

The 5×5 grid buckets rows into cells for the heatmap; the list is also
exposed as ordered rows for the table.
"""
from __future__ import annotations

from typing import Any


# Canonical risk template. IC memo builders can override / extend.
_DEFAULT_RISK_TEMPLATE: list[dict[str, Any]] = [
    {"category": "Grid / regulatory",
     "description": "Grid connection offer delayed past Gate 2 window",
     "likelihood": 3, "impact": 5,
     "mitigation": "Engage DNO under CCCM v19; secure accepted-queue slot pre-FID.",
     "residual_label": "Amber — 6–9 month residual timing risk",
     "linked_to": "CP-01 (Gate 2 offer); Insurance clause DL-3"},
    {"category": "Planning",
     "description": "Planning refusal at LPA or PINS call-in",
     "likelihood": 3, "impact": 5,
     "mitigation": "Pre-app with LPA; Tier-2 ecology + heritage + LVIA; CNP argument per EN-1/EN-3 2025.",
     "residual_label": "Amber — until decision notice issued",
     "linked_to": "CP-02 (planning consent); CS-01 (no JR)"},
    {"category": "Grid / construction",
     "description": "Connection cost overrun vs P50 estimate",
     "likelihood": 3, "impact": 4,
     "mitigation": "Fixed-price EPC wrap; P90 contingency ring-fenced in S&U.",
     "residual_label": "Green post EPC execution",
     "linked_to": "CP-05 (EPC fixed price); Covenant: capex cap"},
    {"category": "Market / offtake",
     "description": "Merchant price curve softens post-COD (REMA RNP not fully priced)",
     "likelihood": 3, "impact": 4,
     "mitigation": "50% CPPA hedge at FID; floor price covenant in senior debt.",
     "residual_label": "Amber — basis + shape risk remain",
     "linked_to": "PPA-01; Covenant: min. contracted revenue"},
    {"category": "Operational",
     "description": "Curtailment exceeds modelled 4% base case",
     "likelihood": 3, "impact": 3,
     "mitigation": "ANM / flex connection option; MOPS data on comparable sites.",
     "residual_label": "Amber — depends on DNO congestion plan",
     "linked_to": "Insurance: BI cover; O&M contract §12"},
    {"category": "Timeline",
     "description": "Delay to COD past 2028 sun-set (AR8 window)",
     "likelihood": 2, "impact": 4,
     "mitigation": "Long-stop dates in all contracts; EPC LD regime at £1k/MW/day.",
     "residual_label": "Green with LD protection",
     "linked_to": "EPC LD schedule; CS-03"},
    {"category": "Land / legal",
     "description": "Land option not converted to lease",
     "likelihood": 2, "impact": 5,
     "mitigation": "Option + extension executed; parallel alt-site scoping declined.",
     "residual_label": "Green — option + extension in place",
     "linked_to": "CP-03 (lease execution)"},
    {"category": "Environmental",
     "description": "BNG units cannot be secured on-site at 10%",
     "likelihood": 3, "impact": 3,
     "mitigation": "Off-site BNG providers pre-selected within 1-hr LPA area.",
     "residual_label": "Amber — pending habitat survey",
     "linked_to": "CP-04 (BNG plan); Environment Act 2021"},
    {"category": "Financial",
     "description": "Debt market widens beyond underwritten margin",
     "likelihood": 2, "impact": 3,
     "mitigation": "Rate hedge at term sheet; flex-down structure agreed with MLA.",
     "residual_label": "Green with SONIA swap at 7 yrs",
     "linked_to": "Hedge policy; Covenant: interest cover"},
    {"category": "Counterparty",
     "description": "PPA offtaker credit downgrade",
     "likelihood": 2, "impact": 4,
     "mitigation": "Parent-company guarantee; ISDA CSA with daily margining.",
     "residual_label": "Green at current IG rating",
     "linked_to": "PPA schedule 4; CSA in place"},
    {"category": "Technology",
     "description": "BESS augmentation capex higher than modelled at SoH 80%",
     "likelihood": 3, "impact": 3,
     "mitigation": "Augmentation sinking fund; 15-yr battery supply contract w/ OEM.",
     "residual_label": "Amber — BESS cell price trajectory",
     "linked_to": "BESS supply agreement §8"},
    {"category": "Technology",
     "description": "Inverter / module OEM warranty default",
     "likelihood": 2, "impact": 3,
     "mitigation": "Tier-1 OEM shortlist; bank guarantees from parent for 10-yr warranty.",
     "residual_label": "Green — Tier-1 only",
     "linked_to": "Supply contracts §11 (warranty)"},
    {"category": "ESG / social",
     "description": "Community opposition / local campaign",
     "likelihood": 2, "impact": 3,
     "mitigation": "CBS £800/MW/yr; pre-app public consultation; town-council briefings.",
     "residual_label": "Green — CBS in place",
     "linked_to": "S106 agreement; community benefit scheme"},
    {"category": "Regulatory (2026)",
     "description": "PIA 2025 reclassification (50 MW → NSIP → 100 MW pivot)",
     "likelihood": 1, "impact": 4,
     "mitigation": "Project classified; dual NSIP/TCPA path not needed at 50 MW.",
     "residual_label": "Green — below new NSIP threshold",
     "linked_to": "PIA 2025 schedule 2"},
    {"category": "Regulatory (2026)",
     "description": "BNG-for-NSIPs applies (post-2 Nov 2026)",
     "likelihood": 1, "impact": 2,
     "mitigation": "If project pre-dates Nov 2026 application, grandfathered; otherwise plan produced.",
     "residual_label": "Green — timing anchored pre-Nov 2026",
     "linked_to": "CP-04 (BNG plan)"},
    {"category": "Macro",
     "description": "UK sovereign / sterling risk (political / fiscal shock)",
     "likelihood": 2, "impact": 3,
     "mitigation": "N/A — unhedged. Noted as residual.",
     "residual_label": "Amber — irreducible",
     "linked_to": "None"},
    {"category": "Regulatory (2026)",
     "description": "CfD AR7 20-yr term not awarded (reverts to 15 yr)",
     "likelihood": 2, "impact": 3,
     "mitigation": "Debt tenor flexed to 15 yrs; sensitivity modelled.",
     "residual_label": "Amber — pending AR8 results",
     "linked_to": "Base case sensitivity §4"},
    {"category": "Insurance",
     "description": "Parametric / natural-catastrophe cover not available",
     "likelihood": 1, "impact": 3,
     "mitigation": "All-risks construction + operational insurance placed with A-rated carrier.",
     "residual_label": "Green — Marsh policy in place",
     "linked_to": "Insurance schedule; Covenant: insurance maintained"},
]


def _rag(likelihood: int, impact: int) -> str:
    score = likelihood * impact
    if score >= 20:
        return "red"
    if score >= 12:
        return "amber"
    if score >= 6:
        return "yellow"
    return "green"


def build_risk_matrix(
    risks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the risk list + the 5×5 heatmap grid."""
    rows_raw = risks if risks else _DEFAULT_RISK_TEMPLATE

    # Normalise each row — add idx, rag, score.
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(rows_raw, start=1):
        L = int(r.get("likelihood", 3) or 3)
        I = int(r.get("impact", 3) or 3)
        L = max(1, min(5, L))
        I = max(1, min(5, I))
        score = L * I
        rag = _rag(L, I)
        rows.append({
            **r,
            "idx": i,
            "likelihood": L,
            "impact": I,
            "score": score,
            "rag": rag,
        })

    # 5×5 grid counts
    grid: list[list[int]] = [[0] * 5 for _ in range(5)]
    for r in rows:
        grid[r["impact"] - 1][r["likelihood"] - 1] += 1

    # Top-5 highest score (for exec summary carry-back)
    top5 = sorted(rows, key=lambda x: (-x["score"], x["idx"]))[:5]

    # Summary counts
    counts_by_rag = {"red": 0, "amber": 0, "yellow": 0, "green": 0}
    for r in rows:
        counts_by_rag[r["rag"]] = counts_by_rag.get(r["rag"], 0) + 1

    return {
        "available": True,
        "rows": rows,
        "grid": grid,  # grid[impact-1][likelihood-1] = count
        "top5": top5,
        "counts_by_rag": counts_by_rag,
        "total_rows": len(rows),
        "citation": (
            "Risk matrix per 2026 IC memo standard §4a: 5×5 likelihood × "
            "impact grid; residual rating after mitigation; each row linked "
            "to CP/CS/insurance/covenant."
        ),
    }
