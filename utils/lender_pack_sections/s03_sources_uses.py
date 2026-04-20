"""Section 3 — Sources & Uses table + capital stack waterfall.

Layout follows BVCA IRG 2022 §4 (Sources & Uses) and the LMA utilisation
request template. The capital stack waterfall is the lender-grade version
of the sources side: senior debt, mezzanine (if any), equity, with
ordering reflecting repayment seniority.
"""
from __future__ import annotations

from typing import Any


def build_sources_uses(
    capex_gbp: float,
    gearing_pct: float,
    debt_principal_gbp: float | None = None,
    dsra_months: int = 6,
    opex_gbp_yr1: float = 0.0,
    transaction_costs_pct: float = 0.025,
    contingency_pct: float = 0.05,
) -> dict[str, Any]:
    """Construct Sources & Uses + capital stack.

    Uses = construction capex + transaction costs (2.5% of debt) +
    contingency (5% of construction) + DSRA (6 months of debt service at
    y1, approx).

    Sources = senior debt + equity, gearing applied to total uses so both
    sides balance.
    """
    construction_capex = capex_gbp
    transaction_costs = construction_capex * transaction_costs_pct
    contingency = construction_capex * contingency_pct

    # DSRA approx = 6 months * annuity-like debt service at 6% rate, ~(debt/10)
    # Refined when the DCFEvaluator result is available, but this keeps the
    # table sources-and-uses-balanced for the pre-DCF draft.
    dsra = (debt_principal_gbp or (construction_capex * gearing_pct)) * (dsra_months / 24)

    total_uses = construction_capex + transaction_costs + contingency + dsra
    senior_debt = debt_principal_gbp if debt_principal_gbp is not None else total_uses * gearing_pct
    equity = total_uses - senior_debt

    uses_rows = [
        {"label": "Construction capex (EPC wrap)", "amount_gbp": construction_capex,
         "pct": construction_capex / total_uses * 100},
        {"label": "Contingency (5% of construction)", "amount_gbp": contingency,
         "pct": contingency / total_uses * 100},
        {"label": "Transaction costs (legal, advisory, LTA)", "amount_gbp": transaction_costs,
         "pct": transaction_costs / total_uses * 100},
        {"label": f"DSRA ({dsra_months}-month reserve)", "amount_gbp": dsra,
         "pct": dsra / total_uses * 100},
    ]
    sources_rows = [
        {"label": "Senior secured debt (LMA IGFA)", "amount_gbp": senior_debt,
         "pct": senior_debt / total_uses * 100, "tier": "senior"},
        {"label": "Sponsor equity commitment", "amount_gbp": equity,
         "pct": equity / total_uses * 100, "tier": "equity"},
    ]

    # Capital stack waterfall — list top-down (senior first)
    capital_stack = [
        {"layer": "Senior secured debt", "amount_gbp": senior_debt,
         "ranking": 1, "return_target_pct": 6.0,
         "notes": "LMA IGFA 2024 form; full English debenture, share charge."},
        {"layer": "Sponsor equity", "amount_gbp": equity,
         "ranking": 2, "return_target_pct": 12.0,
         "notes": "Equity contributed as commitment letter at financial close, drawn pro-rata with debt."},
    ]

    return {
        "uses_rows": uses_rows,
        "sources_rows": sources_rows,
        "capital_stack": capital_stack,
        "total_uses_gbp": total_uses,
        "total_sources_gbp": total_uses,
        "balanced": True,
        "citation": "BVCA IRG 2022 §4 / LMA IGFA Utilisation",
    }
