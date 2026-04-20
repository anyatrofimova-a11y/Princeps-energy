"""Section 13 — Security & account structure.

Typical UK project-finance security package per LMA Real Estate Finance
form + LMA Security Agent Deed:
  • Fixed & floating debenture
  • Share charge over SPV shares
  • Assignment by way of security of Project Documents
  • Step-in via Direct Agreements
  • Project-accounts cascade (waterfall)
"""
from __future__ import annotations

from typing import Any


def build_security_structure() -> dict[str, Any]:
    security_rows = [
        {
            "instrument": "Debenture (fixed & floating charge)",
            "granted_by": "Project Company (SPV)",
            "scope": "All present and future assets of the SPV",
            "ranking": "1st ranking, shared with Security Agent",
            "lma_ref": "LMA Security Agent Deed + LMA REF debenture template",
        },
        {
            "instrument": "Share charge",
            "granted_by": "Sponsor (HoldCo)",
            "scope": "100% of ordinary shares in SPV",
            "ranking": "1st ranking",
            "lma_ref": "LMA IGFA + LMA Share Charge template",
        },
        {
            "instrument": "Assignment of Project Documents",
            "granted_by": "Project Company (SPV)",
            "scope": "EPC, O&M, PPA, Connection Agreement, Lease, Insurance proceeds",
            "ranking": "1st ranking",
            "lma_ref": "LMA Project Finance Assignment",
        },
        {
            "instrument": "Assignment of Insurance proceeds",
            "granted_by": "Project Company (SPV)",
            "scope": "All insurance receipts > £100k applied per waterfall",
            "ranking": "1st ranking",
            "lma_ref": "LMA IGFA §19",
        },
        {
            "instrument": "Direct Agreements (step-in rights)",
            "granted_by": "EPC, O&M, PPA counterparties",
            "scope": "Lender cure / step-in / novation on Borrower default",
            "ranking": "Tri-partite",
            "lma_ref": "LMA Direct Agreement template",
        },
        {
            "instrument": "Parent Company Guarantee (from EPC parent)",
            "granted_by": "EPC parent",
            "scope": "Performance + payment obligations of EPC counterparty",
            "ranking": "Several, capped at EPC contract price",
            "lma_ref": "LMA Parent Company Guarantee form",
        },
    ]

    accounts_cascade = [
        {
            "account": "Proceeds Account",
            "purpose": "All revenue receipts (PPA, merchant, ancillary, capacity market).",
            "control": "Borrower signatory; Agent co-signatory on acceleration.",
        },
        {
            "account": "Operating Account",
            "purpose": "Opex payments, O&M, insurance, admin costs.",
            "control": "Borrower signatory up to monthly budget.",
        },
        {
            "account": "Debt Service Account (DSA)",
            "purpose": "Pre-funded 30 days ahead of each interest / principal date.",
            "control": "Agent signatory.",
        },
        {
            "account": "Debt Service Reserve Account (DSRA)",
            "purpose": "6 months of next-period debt service, cash or LC.",
            "control": "Agent sole signatory.",
        },
        {
            "account": "Maintenance Reserve Account (MRA)",
            "purpose": "Capital maintenance / augmentation reserve (BESS particularly).",
            "control": "Agent sole signatory.",
        },
        {
            "account": "Distribution Account",
            "purpose": "Surplus cash after covenants tested; distributions subject to lock-up tests.",
            "control": "Borrower signatory; locked on breach.",
        },
    ]

    waterfall = [
        "Taxes and statutory payments",
        "Operating costs and O&M (within budget)",
        "Fees and expenses of Agent / Security Agent",
        "Senior interest",
        "Senior scheduled principal",
        "DSRA top-up to target",
        "MRA top-up to target",
        "Mandatory prepayments (if any)",
        "Cash sweep (if lock-up triggered)",
        "Distributions to equity (subject to Distribution Test)",
    ]

    return {
        "security_rows": security_rows,
        "accounts_cascade": accounts_cascade,
        "waterfall": waterfall,
        "citation": (
            "LMA Investment Grade Facility Agreement 2024; LMA Real Estate Finance "
            "debenture; LMA Security Agent Deed; LMA Direct Agreement template."
        ),
    }
