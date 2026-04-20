"""Section 1 — Cover page, reliance addressee, document control block.

RICS Red Book Global Standards 2025 (VPS 3) and the LMA Investment Grade
Facility Agreement both require a named addressee and reliance statement
on any pack that a lender will rely on for credit approval.

The reliance list is built from the request (bank_name + MLA list) plus
the standard Princeps belt-and-braces addressees (the SPV and the sponsor).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


_RELIANCE_BOILERPLATE = (
    "This Lender Information Pack has been prepared by Princeps for the "
    "Addressees named below in connection with the financing of the "
    "{project_name} project. Princeps owes a duty of care to the "
    "Addressees only and accepts no liability to any third party. "
    "Reliance is subject to the terms of the Reliance Letter to be "
    "entered into separately. Nothing in this pack constitutes a "
    "commitment to lend or invest; any such commitment is given solely "
    "in the Facility Agreement and ancillary documents. "
    "Reference: LMA Investment Grade Facility Agreement (English law, "
    "2024 update); RICS Red Book Global Standards 2025, VPS 3 (Reliance)."
)


def build_cover(
    project_name: str,
    sponsor: str,
    bank_name: str,
    mla_names: list[str] | None,
    revision: str,
    generated_at: datetime,
) -> dict[str, Any]:
    reliance: list[str] = [bank_name]
    for m in mla_names or []:
        if m and m not in reliance:
            reliance.append(m)
    reliance.append(sponsor)
    reliance.append(f"{project_name} ProjectCo Limited (SPV)")

    return {
        "title": "Lender Information Pack",
        "project_name": project_name,
        "sponsor": sponsor,
        "issued_to": bank_name,
        "reliance_addressees": reliance,
        "reliance_statement": _RELIANCE_BOILERPLATE.format(project_name=project_name),
        "revision": revision,
        "revision_date": generated_at.strftime("%d %b %Y"),
        "revision_history": [
            {
                "rev": revision,
                "date": generated_at.strftime("%Y-%m-%d"),
                "author": "Princeps Analytics",
                "reviewer": "Princeps QA",
                "approver": "Princeps Director",
                "description": "Initial issue — model-driven draft for lender review.",
            },
        ],
        "confidentiality": "COMMERCIAL IN CONFIDENCE",
        "citation": "LMA IGFA 2024 / RICS Red Book VPS 3",
    }
