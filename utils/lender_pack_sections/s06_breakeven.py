"""Section 6 — Breakeven case.

Question answered: for each single driver (revenue, opex, capex) in
isolation, what level of adverse shock brings minimum DSCR down to 1.20x
(the LMA covenant floor)?

Implementation: bisect each driver between 0 and +100% (capex) or −100%
and 0% (revenue/opex) — converges on the shock level that drops min DSCR
to the floor. Uses the same DCFEvaluator engine.
"""
from __future__ import annotations

from typing import Any, Callable

try:
    from utils.dcf_evaluator import DCFEvaluator, build_amortising_debt  # type: ignore
except Exception:
    DCFEvaluator = None  # fallback
    build_amortising_debt = None  # type: ignore


def _min_dscr_for(
    evaluator_builder: Callable[[], Any],
) -> float | None:
    evaluator = evaluator_builder()
    if evaluator is None:
        return None
    result = evaluator.evaluate()
    return result.summary.get("min_dscr")


def _bisect_shock(
    shock_fn: Callable[[float], Any],
    target_dscr: float,
    lo: float,
    hi: float,
    iters: int = 30,
) -> tuple[float, float | None]:
    """Find shock x in [lo, hi] where min_dscr(x) == target_dscr.

    shock_fn(x) returns a DCFEvaluator configured with the shock applied.
    Assumes min_dscr is monotonic in x.
    """
    f_lo = _min_dscr_for(lambda: shock_fn(lo))
    f_hi = _min_dscr_for(lambda: shock_fn(hi))
    if f_lo is None or f_hi is None:
        return (0.0, None)
    # Ensure monotone — decreasing as shock gets more adverse
    mid_dscr = None
    for _ in range(iters):
        mid = (lo + hi) / 2
        mid_dscr = _min_dscr_for(lambda: shock_fn(mid))
        if mid_dscr is None:
            return (mid, None)
        if abs(mid_dscr - target_dscr) < 0.005:
            return (mid, mid_dscr)
        # lower dscr = more adverse shock
        if mid_dscr > target_dscr:
            lo = mid
        else:
            hi = mid
    return ((lo + hi) / 2, mid_dscr)


def build_breakeven_case(
    base_capex: float,
    base_revenue: list[float],
    base_opex: list[float],
    wacc: float,
    gearing_pct: float,
    interest_rate: float,
    debt_term_years: int,
    target_dscr_floor: float = 1.20,
) -> dict[str, Any]:
    if DCFEvaluator is None or not base_revenue:
        return {
            "available": False,
            "target_dscr_floor": target_dscr_floor,
            "note": "DCFEvaluator not importable; breakeven case unavailable.",
        }

    life = len(base_revenue)

    def _build_evaluator(capex, revenue, opex):
        debt_principal = capex * gearing_pct
        debt_schedule = build_amortising_debt(
            principal=debt_principal,
            rate=interest_rate,
            term_years=debt_term_years,
            life_years=life,
        )
        return DCFEvaluator(
            capex=capex,
            revenue_schedule=revenue,
            opex_schedule=opex,
            tax_rate=0.25,
            wacc=wacc,
            terminal_growth=0.0,
            debt_schedule=debt_schedule,
        )

    # Revenue shock — start from 0 (no shock, high DSCR) to −0.80 (very adverse)
    def _rev_shock(x):
        return _build_evaluator(
            base_capex,
            [r * (1 + x) for r in base_revenue],
            base_opex,
        )
    rev_shock, rev_dscr = _bisect_shock(_rev_shock, target_dscr_floor, 0.0, -0.80)

    # Opex shock — 0 (no shock) to +2.0 (200% opex increase)
    def _opex_shock(x):
        return _build_evaluator(
            base_capex,
            base_revenue,
            [o * (1 + x) for o in base_opex],
        )
    opex_shock, opex_dscr = _bisect_shock(_opex_shock, target_dscr_floor, 0.0, 2.0)

    # Capex shock — 0 (no shock) to +2.0 (200% capex overrun)
    def _capex_shock(x):
        return _build_evaluator(
            base_capex * (1 + x),
            base_revenue,
            base_opex,
        )
    capex_shock, capex_dscr = _bisect_shock(_capex_shock, target_dscr_floor, 0.0, 2.0)

    return {
        "available": True,
        "target_dscr_floor": target_dscr_floor,
        "rows": [
            {
                "driver": "Revenue (price × utilisation)",
                "breakeven_shock_pct": round(rev_shock * 100, 1),
                "direction": "decrease",
                "resulting_min_dscr": round(rev_dscr, 3) if rev_dscr else None,
                "commentary": (
                    f"Revenue can fall by {abs(rev_shock)*100:.1f}% before DSCR hits "
                    f"{target_dscr_floor:.2f}x floor. Hold this as the revenue cushion."
                ),
            },
            {
                "driver": "Operating cost",
                "breakeven_shock_pct": round(opex_shock * 100, 1),
                "direction": "increase",
                "resulting_min_dscr": round(opex_dscr, 3) if opex_dscr else None,
                "commentary": (
                    f"Opex can escalate by {opex_shock*100:.1f}% before breaching floor — "
                    "covers insurance, TNUoS, O&M inflation risk."
                ),
            },
            {
                "driver": "CAPEX overrun",
                "breakeven_shock_pct": round(capex_shock * 100, 1),
                "direction": "increase",
                "resulting_min_dscr": round(capex_dscr, 3) if capex_dscr else None,
                "commentary": (
                    f"EPC can overrun by {capex_shock*100:.1f}% before breaching. "
                    "Mitigated by fixed-price EPC + performance bond + 5% contingency."
                ),
            },
        ],
        "binding_driver": "Revenue (price × utilisation)",
        "citation": "LMA IGFA 2024 DSCR 1.20x floor; PRA SS31/15 reverse stress test methodology.",
    }
