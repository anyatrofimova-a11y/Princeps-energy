"""Section 15 — Reliance, qualifications, signature block.

Final-page qualifications, RICS-style reliance language, and signature
slots for author, reviewer and approver. Mirrors RICS Red Book VPS 3.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


_QUALIFICATIONS = [
    "This Lender Information Pack is provided for discussion and credit-paper purposes only.",
    "No liability is accepted to any party other than the Reliance Addressees listed in §1, and only on the terms of the Reliance Letter.",
    "Financial model outputs are indicative and subject to independent model audit (CS item cs_11_model_audit).",
    "Regulatory framework references (LMA IGFA, PRA SS31/15, ENA EREC G99 Issue 2, NESO SOF) are cited as at the date of issue and are subject to change.",
    "The pack assumes the scheme proceeds on the base-case programme; material deviation requires re-issue of this pack at the next revision level.",
    "Princeps is not authorised under FSMA 2000 to give regulated advice; all credit and investment decisions rest with the lender / investor.",
]


def build_signature_block(
    project_name: str,
    generated_at: datetime,
    author: str = "Princeps Analytics",
    reviewer: str = "Princeps QA",
    approver: str = "Princeps Director",
) -> dict[str, Any]:
    return {
        "qualifications": _QUALIFICATIONS,
        "reliance": (
            f"This report is prepared for the Reliance Addressees named in "
            f"§1 of this pack in respect of the {project_name} project, "
            f"for the purpose of a senior-debt financing decision. "
            f"No third party may rely on this report without prior written "
            f"consent from Princeps. Princeps accepts no liability to any "
            f"third party for any matter arising from this report."
        ),
        "signatures": [
            {"role": "Author", "name": author, "date": generated_at.strftime("%d %b %Y")},
            {"role": "Reviewer", "name": reviewer, "date": generated_at.strftime("%d %b %Y")},
            {"role": "Approver", "name": approver, "date": generated_at.strftime("%d %b %Y")},
        ],
        "citation": "RICS Red Book Global Standards 2025 VPS 3 (Reliance and Liability).",
    }
