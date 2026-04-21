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


# ---------------------------------------------------------------------------
# IC-grade combined Lender Case — applies all shocks concurrently.
# Added per 2026 IC memo standard §4b (docs/competitive/ic_memo_standard_2026.md).
#
# Shocks (canonical):
#   revenue_pct        −20%   (applied to revenue schedule)
#   capex_pct          +10%   (applied to capex)
#   availability_pp    −0.03  (−3 pp applied as multiplicative on revenue)
#   delay_months       +6     (delay revenue & opex 6 months into year 1)
#   wacc_bps           +100   (absolute bps addition to WACC)
# ---------------------------------------------------------------------------

def _apply_delay_months(series: list[float], months: int) -> list[float]:
    """Shift revenue/opex schedule forward by `months`.

    Year-1 revenue is reduced pro-rata by (12 − months) / 12. All subsequent
    years unchanged in shape but the first-year opportunity cost sticks
    (equivalent to postponing COD by `months`).
    """
    if not series or months <= 0:
        return list(series)
    factor = max(0.0, (12 - months) / 12.0)
    out = list(series)
    out[0] = out[0] * factor
    return out


def _run_dcf_with_shocks(
    *,
    base_capex: float,
    base_revenue: list[float],
    base_opex: list[float],
    wacc: float,
    gearing_pct: float,
    interest_rate: float,
    debt_term_years: int,
    revenue_multiplier: float,
    capex_multiplier: float,
    delay_months: int,
    wacc_delta: float,
) -> dict[str, Any]:
    """Helper — runs the DCFEvaluator with a single composed shock set."""
    shocked_revenue = _shock_series(base_revenue, revenue_multiplier)
    shocked_revenue = _apply_delay_months(shocked_revenue, delay_months)
    shocked_opex = list(base_opex)
    shocked_capex = base_capex * capex_multiplier

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
        wacc=wacc + wacc_delta,
        terminal_growth=0.0,
        debt_schedule=debt_schedule,
    )
    result = evaluator.evaluate()
    return {
        "summary": result.summary,
        "shocked_capex_gbp": shocked_capex,
        "covenants": result.covenants,
    }


def compute_combined_downside(
    *,
    base_capex: float,
    base_revenue: list[float],
    base_opex: list[float],
    wacc: float,
    gearing_pct: float = 0.70,
    interest_rate: float = 0.06,
    debt_term_years: int = 18,
    revenue_pct: float = -0.20,
    capex_pct: float = +0.10,
    availability_pp: float = -0.03,
    delay_months: int = 6,
    wacc_bps: int = +100,
) -> dict[str, Any]:
    """Run each shock individually AND all shocks concurrently.

    Returns a dict with:
      rows: list of {label, ... summary metrics} — one per shock + base + combined.
      combined: the combined Lender Case row (shortcut).
      summary: same shape as build_downside_case's `summary`.
      shocks: the applied shock set.
    """
    if DCFEvaluator is None or not base_revenue:
        return {
            "available": False,
            "note": "DCFEvaluator not importable; combined downside unavailable.",
            "shocks": {
                "revenue_pct": revenue_pct,
                "capex_pct": capex_pct,
                "availability_pp": availability_pp,
                "delay_months": delay_months,
                "wacc_bps": wacc_bps,
            },
        }

    wacc_delta = wacc_bps / 10_000.0  # 100 bps = 0.01

    # Base case (no shocks) — for delta calculation
    base_out = _run_dcf_with_shocks(
        base_capex=base_capex,
        base_revenue=base_revenue,
        base_opex=base_opex,
        wacc=wacc,
        gearing_pct=gearing_pct,
        interest_rate=interest_rate,
        debt_term_years=debt_term_years,
        revenue_multiplier=1.0,
        capex_multiplier=1.0,
        delay_months=0,
        wacc_delta=0.0,
    )

    # Individual shocks (one-at-a-time)
    individual_specs: list[dict[str, Any]] = [
        {
            "label": f"Revenue {revenue_pct * 100:+.0f}%",
            "revenue_multiplier": 1 + revenue_pct,
            "capex_multiplier": 1.0,
            "delay_months": 0,
            "wacc_delta": 0.0,
        },
        {
            "label": f"Capex {capex_pct * 100:+.0f}%",
            "revenue_multiplier": 1.0,
            "capex_multiplier": 1 + capex_pct,
            "delay_months": 0,
            "wacc_delta": 0.0,
        },
        {
            "label": f"Availability {availability_pp * 100:+.1f} pp",
            "revenue_multiplier": 1 + availability_pp,
            "capex_multiplier": 1.0,
            "delay_months": 0,
            "wacc_delta": 0.0,
        },
        {
            "label": f"Delay +{delay_months} mo",
            "revenue_multiplier": 1.0,
            "capex_multiplier": 1.0,
            "delay_months": delay_months,
            "wacc_delta": 0.0,
        },
        {
            "label": f"WACC +{wacc_bps} bps",
            "revenue_multiplier": 1.0,
            "capex_multiplier": 1.0,
            "delay_months": 0,
            "wacc_delta": wacc_delta,
        },
    ]

    individual_rows: list[dict[str, Any]] = []
    for spec in individual_specs:
        out = _run_dcf_with_shocks(
            base_capex=base_capex,
            base_revenue=base_revenue,
            base_opex=base_opex,
            wacc=wacc,
            gearing_pct=gearing_pct,
            interest_rate=interest_rate,
            debt_term_years=debt_term_years,
            revenue_multiplier=spec["revenue_multiplier"],
            capex_multiplier=spec["capex_multiplier"],
            delay_months=spec["delay_months"],
            wacc_delta=spec["wacc_delta"],
        )
        s = out["summary"]
        individual_rows.append({
            "label": spec["label"],
            "irr_pct": s.get("irr_pct"),
            "equity_irr_pct": s.get("equity_irr_pct"),
            "npv_gbp": s.get("npv"),
            "min_dscr": s.get("min_dscr"),
            "min_llcr": s.get("min_llcr"),
            "any_breach": bool(s.get("any_breach")),
            "shocked_capex_gbp": out["shocked_capex_gbp"],
            "kind": "individual",
        })

    # Combined Lender Case — all shocks applied concurrently
    # Note: availability_pp is *additive* on revenue multiplier, not multiplicative
    # with revenue_pct — they compose as (1 + revenue_pct) * (1 + availability_pp)
    combined_revenue_multiplier = (1 + revenue_pct) * (1 + availability_pp)
    combined_out = _run_dcf_with_shocks(
        base_capex=base_capex,
        base_revenue=base_revenue,
        base_opex=base_opex,
        wacc=wacc,
        gearing_pct=gearing_pct,
        interest_rate=interest_rate,
        debt_term_years=debt_term_years,
        revenue_multiplier=combined_revenue_multiplier,
        capex_multiplier=1 + capex_pct,
        delay_months=delay_months,
        wacc_delta=wacc_delta,
    )
    cs = combined_out["summary"]
    combined_row = {
        "label": "Lender Case (combined)",
        "irr_pct": cs.get("irr_pct"),
        "equity_irr_pct": cs.get("equity_irr_pct"),
        "npv_gbp": cs.get("npv"),
        "min_dscr": cs.get("min_dscr"),
        "min_llcr": cs.get("min_llcr"),
        "any_breach": bool(cs.get("any_breach")),
        "shocked_capex_gbp": combined_out["shocked_capex_gbp"],
        "kind": "combined",
    }

    # Base row (for table top)
    bs = base_out["summary"]
    base_row = {
        "label": "Base case",
        "irr_pct": bs.get("irr_pct"),
        "equity_irr_pct": bs.get("equity_irr_pct"),
        "npv_gbp": bs.get("npv"),
        "min_dscr": bs.get("min_dscr"),
        "min_llcr": bs.get("min_llcr"),
        "any_breach": bool(bs.get("any_breach")),
        "shocked_capex_gbp": base_capex,
        "kind": "base",
    }

    return {
        "available": True,
        "shocks": {
            "revenue_pct": revenue_pct,
            "capex_pct": capex_pct,
            "availability_pp": availability_pp,
            "delay_months": delay_months,
            "wacc_bps": wacc_bps,
        },
        "rows": [base_row] + individual_rows + [combined_row],
        "combined": combined_row,
        "base": base_row,
        "summary": cs,
        "covenants": combined_out["covenants"],
        "citation": (
            "Combined-stress Lender Case — 2026 IC memo standard §4b. "
            "PRA SS31/15 (Internal capital adequacy) combined-stress scenario; "
            "each shock also shown individually for attribution."
        ),
    }
