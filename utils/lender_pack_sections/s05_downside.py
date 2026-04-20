"""Section 5 — Downside case.

Concurrent shocks (COUNCIL-1 spec):
  - utilisation / capacity factor       −20%
  - PPA / merchant revenue price        −15%
  - construction capex                  +10%

Covenants re-run against the shocked cashflows. This is the "combined
stress" case — a lender's typical P90-of-P90 look. PRA SS31/15 expects
at least one combined stress scenario per project.
"""
from __future__ import annotations

from typing import Any

try:
    from utils.dcf_evaluator import DCFEvaluator, build_amortising_debt  # type: ignore
except Exception:
    DCFEvaluator = None  # fallback
    build_amortising_debt = None  # type: ignore


def _shock_series(series: list[float], factor: float) -> list[float]:
    return [v * factor for v in series]


def build_downside_case(
    base_capex: float,
    base_revenue: list[float],
    base_opex: list[float],
    wacc: float,
    gearing_pct: float,
    interest_rate: float,
    debt_term_years: int,
    utilisation_shock: float = -0.20,
    price_shock: float = -0.15,
    capex_shock: float = 0.10,
) -> dict[str, Any]:
    if DCFEvaluator is None or not base_revenue:
        return {
            "available": False,
            "note": "DCFEvaluator not importable; downside case unavailable.",
            "assumptions": {
                "utilisation_shock_pct": utilisation_shock * 100,
                "price_shock_pct": price_shock * 100,
                "capex_shock_pct": capex_shock * 100,
            },
        }

    # Revenue shock is multiplicative of (1 + utilisation_shock) *
    # (1 + price_shock) since they're both cashflow drivers.
    rev_factor = (1 + utilisation_shock) * (1 + price_shock)
    shocked_revenue = _shock_series(base_revenue, rev_factor)
    shocked_opex = list(base_opex)  # opex not shocked in this case
    shocked_capex = base_capex * (1 + capex_shock)

    life = len(shocked_revenue)
    debt_principal = shocked_capex * gearing_pct
    debt_schedule = build_amortising_debt(
        principal=debt_principal,
        rate=interest_rate,
        term_years=debt_term_years,
        life_years=life,
    )

    evaluator = DCFEvaluator(
        capex=shocked_capex,
        revenue_schedule=shocked_revenue,
        opex_schedule=shocked_opex,
        tax_rate=0.25,
        wacc=wacc,
        terminal_growth=0.0,
        debt_schedule=debt_schedule,
    )
    result = evaluator.evaluate()

    return {
        "available": True,
        "assumptions": {
            "utilisation_shock_pct": utilisation_shock * 100,
            "price_shock_pct": price_shock * 100,
            "capex_shock_pct": capex_shock * 100,
            "combined_revenue_factor_pct": (rev_factor - 1) * 100,
        },
        "summary": result.summary,
        "min_dscr": result.summary.get("min_dscr"),
        "min_llcr": result.summary.get("min_llcr"),
        "min_icr": result.summary.get("min_icr"),
        "any_breach": bool(result.summary.get("any_breach")),
        "breach_years": result.summary.get("breach_years", []),
        "npv_gbp": result.summary.get("npv"),
        "irr_pct": result.summary.get("irr_pct"),
        "shocked_capex_gbp": shocked_capex,
        "covenants": result.covenants,
        "citation": "PRA SS31/15 (Internal capital adequacy), combined-stress scenario.",
    }
