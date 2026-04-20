"""Section 2 — Transaction summary.

One-page deal snapshot: borrower, sponsor, project company, technology,
installed capacity, grid, debt ask, tenor, DSCR ask, LLCR ask, margin ask.

Modelled on typical BVCA IC-lite cover pages (Greencoat UK Wind, Foresight
Solar Fund annual reports) and LMA Term Sheet §1 layout.
"""
from __future__ import annotations

from typing import Any


def build_transaction_summary(
    project_name: str,
    sponsor: str,
    technology: str,
    capacity_mw: float,
    capex_gbp: float,
    gearing_pct: float,
    debt_term_years: int,
    interest_rate_pct: float,
    target_dscr: float,
    target_llcr: float,
    margin_bps: int,
    region: str,
    dno: str,
    poc_voltage_kv: float,
    cod_target: str | None,
) -> dict[str, Any]:
    debt_amount = capex_gbp * gearing_pct
    equity_amount = capex_gbp - debt_amount

    rows = [
        ("Borrower", f"{project_name} ProjectCo Limited (SPV)"),
        ("Sponsor", sponsor),
        ("Project", project_name),
        ("Technology", technology.upper()),
        ("Installed capacity", f"{capacity_mw:.1f} MW"),
        ("Region / DNO", f"{region} / {dno}"),
        ("Point of connection", f"{poc_voltage_kv:.0f} kV primary"),
        ("Target COD", cod_target or "TBC — programme dependency"),
        ("Total project cost", f"£{capex_gbp/1e6:,.1f}m"),
        ("Debt ask", f"£{debt_amount/1e6:,.1f}m (gearing {gearing_pct*100:.0f}%)"),
        ("Equity ticket", f"£{equity_amount/1e6:,.1f}m"),
        ("Debt tenor", f"{debt_term_years} years door-to-door"),
        ("Indicative margin", f"{margin_bps} bps over SONIA"),
        ("Target DSCR (P50)", f"{target_dscr:.2f}x"),
        ("Target LLCR (P50)", f"{target_llcr:.2f}x"),
        ("Repayment profile", "Sculpted to target DSCR, annuity fallback (LMA §16)"),
        ("Security", "Full English debenture + share charge + PF accounts pledge"),
        ("Governing law", "English law (LMA IGFA 2024 form)"),
    ]

    return {
        "rows": [{"label": k, "value": v} for k, v in rows],
        "debt_amount_gbp": debt_amount,
        "equity_amount_gbp": equity_amount,
        "citation": "LMA IGFA 2024 / BVCA IRG 2022",
    }
