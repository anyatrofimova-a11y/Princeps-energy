"""Section 6 — Investment ask and decision frame.

Explicit ticket, vote asked, delegated authority, CPs, reporting cadence.
The final section in an IC memo — the decision is made here.

Per 2026 IC standard §1 and §4e: covenant package, reserves, cure
mechanics all referenced.
"""
from __future__ import annotations

from typing import Any


_DEFAULT_CPS = [
    "Gate 2 connection offer accepted in writing by the DNO (NESO OFG1164 methodology).",
    "Planning consent issued by LPA or NSIP DCO granted; JR window expired.",
    "Land option converted to 30-year lease, executed.",
    "BNG plan produced and secured for 10% net-gain (DEFRA Metric 4.0).",
    "Tier-1 EPC term sheet executed with fixed-price wrap and LD regime.",
    "Senior debt term sheet executed with MLA; credit committee approval.",
]

_DEFAULT_CSS = [
    "Execute full finance documents and drawdown within 120 days of FID.",
    "Complete Tier-2 ecology + habitat survey pre-construction.",
    "Secure CPPA or participate in CfD AR7/AR8 within 12 months of COD.",
    "Construction insurance policy placed with A-rated carrier pre-commencement.",
    "Tax-equity partner onboarded (if structure in use) pre-FID.",
]


def build_ask_vote(
    ticket_gbp_m: float,
    hold_years: int,
    target_irr_pct: float,
    target_moic: float,
    delegated_cap_gbp_m: float | None = None,
    cps: list[str] | None = None,
    css: list[str] | None = None,
    reporting_cadence: str = "Quarterly against milestone waterfall; "
                             "monthly operating MI post-COD.",
    approver: str = "Investment Committee, Princeps Infrastructure Fund I",
    preconditions_narrative: str | None = None,
) -> dict[str, Any]:
    """Build the ask / vote block."""
    delegated = delegated_cap_gbp_m or round(ticket_gbp_m * 0.15, 2)
    cp_list = cps or _DEFAULT_CPS
    cs_list = css or _DEFAULT_CSS

    ask_statement = (
        f"The Committee is asked to approve sponsor equity commitment of "
        f"£{ticket_gbp_m:.1f}m for a {hold_years}-year hold at target "
        f"equity IRR {target_irr_pct:.1f}% / MOIC {target_moic:.2f}x, "
        f"subject to the conditions precedent listed below."
    )

    decision_options = [
        {"option": "APPROVE",
         "body": ("Approve commitment of £{tk:.1f}m subject to CPs. "
                  "Delegated authority to CIO for up to £{dg:.1f}m "
                  "working-capital draw within commitment envelope.").format(
                  tk=ticket_gbp_m, dg=delegated)},
        {"option": "APPROVE WITH VARIATIONS",
         "body": ("Approve in principle; Committee to name specific "
                  "variations (ticket size, hold period, CPs). Re-table "
                  "at next IC with amended pack.")},
        {"option": "DECLINE",
         "body": ("Decline commitment. Team to return with revised "
                  "downside case or alternative site.")},
    ]

    return {
        "available": True,
        "ask_statement": ask_statement,
        "ticket_gbp_m": ticket_gbp_m,
        "hold_years": hold_years,
        "target_irr_pct": target_irr_pct,
        "target_moic": target_moic,
        "delegated_cap_gbp_m": delegated,
        "approver": approver,
        "cps": cp_list,
        "css": cs_list,
        "reporting_cadence": reporting_cadence,
        "preconditions_narrative": preconditions_narrative or (
            "CPs are phrased as hard gates to drawdown; all must be in "
            "effect before first capital call. Committee to ratify any "
            "CP waiver by email-round at CIO discretion."
        ),
        "decision_options": decision_options,
        "citation": (
            "IC memo ask/vote frame — 2026 standard §1 and §4e. "
            "LMA IG Facility Agreement 2024 covenant package."
        ),
    }
