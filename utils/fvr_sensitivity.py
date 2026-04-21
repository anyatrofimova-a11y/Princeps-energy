"""FVR sensitivity — 8-factor tornado computations for the lender-grade
Financial Viability Report.

Each factor perturbs the deterministic equity-IRR model from
:mod:`utils.investment_appraisal` and records the resulting equity IRR.
Returns a ranked list of dicts with low/high equity-IRR impact and the
implied delta in percentage points vs. the base case.

Design notes
------------
* All defaults (gearing, tenor, rate, tax, CPI, PPA) sourced from
  :mod:`utils.finance_benchmarks`. No magic numbers.
* Standalone Python — no subprocess, runs in-process in ~50 ms.
* Preserves `utils.investment_appraisal._irr_newton` so equity-IRR maths
  match the subprocess appraisal.

Factors
-------
  1. PPA price         ±20%
  2. CapEx             ±15%
  3. OpEx              ±20%
  4. Capacity factor   ±10%
  5. Senior debt rate  ±150 bps
  6. Grid connection   ±30% (modifies 14% slice of CapEx)
  7. CPI               ±1 percentage point
  8. Curtailment       +15% (one-sided — downside only)
"""
from __future__ import annotations

from typing import Any

from utils.investment_appraisal import (
    CAPACITY_FACTORS,
    CAPEX_PER_MW,
    CONSTRUCTION_YEARS,
    CORPORATION_TAX,
    DEGRADATION_RATE,
    OPEX_PER_MW,
    PROJECT_LIFE,
    REVENUE_PER_MW,
    _irr_newton,
)
from utils.finance_benchmarks import (
    cpi_long_run,
    debt_to_equity,
    debt_tenor_years,
    senior_debt_all_in_rate,
)

# Fraction of CapEx allocated to grid connection — matches the CapEx
# breakdown in report_financial.CAPEX_BREAKDOWN (solar 14%, wind 10%,
# offshore 10% via export cable + onshore substation partial, bess 10%).
_GRID_SHARE = {
    "solar": 0.14,
    "wind": 0.10,
    "offshore_wind": 0.10,
    "bess": 0.10,
}


def _equity_irr(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
    *,
    capex_mult: float = 1.0,
    opex_mult: float = 1.0,
    cf_mult: float = 1.0,
    price_mult: float = 1.0,
    debt_rate_delta: float = 0.0,
    grid_mult: float = 1.0,
    cpi_delta: float = 0.0,
    curtail_delta: float = 0.0,
) -> float:
    """Re-solve the equity IRR under a set of factor perturbations.

    Returns equity IRR in percent (0-100). Uses the same construction +
    operating cashflow pattern as investment_appraisal.equity_returns.
    """
    technology = (technology or "solar").lower()
    is_bess = technology == "bess"

    # Baseline stack
    base_capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["solar"])
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW["solar"])
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    inflation = cpi_long_run() + cpi_delta

    # Apply grid-share perturbation inside CapEx
    grid_share = _GRID_SHARE.get(technology, 0.10)
    non_grid_share = 1.0 - grid_share
    perturbed_capex_mw = base_capex_mw * (
        non_grid_share * capex_mult + grid_share * capex_mult * grid_mult
    )
    total_capex = perturbed_capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw * opex_mult

    annual_gen_mwh = capacity_mw * cf * cf_mult * 8760 if not is_bess else 0.0
    bess_base_rev = (
        REVENUE_PER_MW.get(technology, 0) * capacity_mw * cf_mult if is_bess else 0.0
    )

    # Gearing + senior debt rate (perturbed)
    gearing = debt_to_equity(technology)[0]
    debt_amount = total_capex * gearing
    equity_amount = total_capex - debt_amount
    debt_rate = senior_debt_all_in_rate(technology) + debt_rate_delta
    term = debt_tenor_years(technology)
    target_dscr = 1.30

    # Equity cashflows (pre-tax) — mirrors investment_appraisal.equity_returns
    cashflows: list[float] = [-equity_amount / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
    outstanding = debt_amount

    # Curtailment haircut on revenue (pp, additive to degradation)
    curtail = max(0.0, curtail_delta)

    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            revenue = (
                bess_base_rev
                * (1 + inflation) ** y
                * (1 - DEGRADATION_RATE * 2) ** y
                * price_mult
                * (1 - curtail)
            )
        else:
            deg_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            revenue = (
                deg_gen * ppa_price * price_mult * (1 + inflation) ** y * (1 - curtail)
            )
        opex = annual_opex * (1 + inflation) ** y
        ebitda = revenue - opex

        if outstanding > 0 and y <= term:
            interest = outstanding * debt_rate
            cfads = ebitda
            max_ds = cfads / target_dscr
            principal = min(max(0.0, max_ds - interest), outstanding)
            ds = interest + principal
            outstanding -= principal
        else:
            ds = 0.0

        pre_tax = ebitda - ds
        tax = max(0.0, pre_tax * CORPORATION_TAX)
        cashflows.append(pre_tax - tax)

    irr = _irr_newton(cashflows)
    return round((irr or 0.0) * 100.0, 2)


def _pct_label(delta: float, unit: str = "%") -> str:
    sign = "+" if delta >= 0 else "−"
    return f"{sign}{abs(delta):.0f}{unit}"


def compute_tornado(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
) -> dict[str, Any]:
    """Compute the 8-factor tornado around the base equity-IRR.

    Returns
    -------
    {
      "base_irr_pct": float,
      "rows": [
        {
          "factor":      str,      # human label
          "low_case":    str,      # pessimistic label
          "high_case":   str,      # optimistic label
          "irr_low":     float,    # equity IRR at pessimistic
          "irr_high":    float,    # equity IRR at optimistic
          "delta_low":   float,    # pp vs base (negative)
          "delta_high":  float,    # pp vs base (positive)
          "range":       float,    # high - low
        }, ...
      ]
    }
    Rows are sorted descending by |range|.
    """
    base = _equity_irr(capacity_mw, technology, ppa_price)

    # Each factor: (label, low_case_label, high_case_label, low_kwargs, high_kwargs)
    factors = [
        ("PPA Price ±20%", "−20%", "+20%",
         {"price_mult": 0.80}, {"price_mult": 1.20}),
        ("CapEx ±15%", "+15%", "−15%",
         {"capex_mult": 1.15}, {"capex_mult": 0.85}),
        ("OpEx ±20%", "+20%", "−20%",
         {"opex_mult": 1.20}, {"opex_mult": 0.80}),
        ("Capacity Factor ±10%", "−10%", "+10%",
         {"cf_mult": 0.90}, {"cf_mult": 1.10}),
        ("Senior Debt Rate ±150 bps", "+150 bps", "−150 bps",
         {"debt_rate_delta": 0.015}, {"debt_rate_delta": -0.015}),
        ("Grid Connection Cost ±30%", "+30%", "−30%",
         {"grid_mult": 1.30}, {"grid_mult": 0.70}),
        ("CPI ±1 pp", "−1 pp", "+1 pp",
         {"cpi_delta": -0.01}, {"cpi_delta": 0.01}),
        ("Curtailment +15%", "+15 pp", "0 pp (base)",
         {"curtail_delta": 0.15}, {"curtail_delta": 0.0}),
    ]

    rows: list[dict[str, Any]] = []
    for label, lo_lbl, hi_lbl, lo_kw, hi_kw in factors:
        irr_lo = _equity_irr(capacity_mw, technology, ppa_price, **lo_kw)
        irr_hi = _equity_irr(capacity_mw, technology, ppa_price, **hi_kw)
        rows.append({
            "factor": label,
            "low_case": lo_lbl,
            "high_case": hi_lbl,
            "irr_low": irr_lo,
            "irr_high": irr_hi,
            "delta_low": round(irr_lo - base, 2),
            "delta_high": round(irr_hi - base, 2),
            "range": round(abs(irr_hi - irr_lo), 2),
        })

    rows.sort(key=lambda r: r["range"], reverse=True)
    return {"base_irr_pct": base, "rows": rows}


def stress_downside(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
) -> dict[str, Any]:
    """Lender stress: 20% CapEx overrun + 12-month grid slip + £45/MWh merchant tail.

    The grid slip is modelled as one additional construction year worth
    of interest carry on senior debt, rolled into CapEx (+6% rough proxy
    at a 6% rate).
    """
    overrun = 1.20
    slip_proxy = 1.06   # ~1 yr × senior debt rate ~6% on full debt
    stressed_capex_mult = overrun * slip_proxy
    # Merchant tail: post-PPA revenue blended down — approximate by a
    # flat 35% haircut on PPA price for the whole horizon (conservative).
    merchant_tail = 45.0
    effective_mult = merchant_tail / ppa_price if ppa_price > 0 else 0.80

    irr_stressed = _equity_irr(
        capacity_mw, technology, ppa_price,
        capex_mult=stressed_capex_mult,
        price_mult=effective_mult,
    )
    base = _equity_irr(capacity_mw, technology, ppa_price)
    return {
        "case": "Downside — 20% CapEx overrun + 12-mo grid slip + £45/MWh merchant tail",
        "base_irr_pct": base,
        "stressed_irr_pct": irr_stressed,
        "delta_pp": round(irr_stressed - base, 2),
        "capex_mult": round(stressed_capex_mult, 3),
        "revenue_mult": round(effective_mult, 3),
    }


def stress_upside(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
) -> dict[str, Any]:
    """Lender upside: AR7 Pot 1 CfD (£67/MWh, indexed) + 5-yr capacity contract.

    AR7 Pot 1 floors price at £67/MWh — applies only to
    solar/onshore-wind. Capacity contract adds a £20k/MW/yr revenue kick
    modelled as a +8% revenue uplift (conservative 5-yr proxy).
    """
    from utils.finance_benchmarks import cfd_strike_2026
    if technology in ("solar", "wind"):
        strike = cfd_strike_2026(pot=1)
        price_mult = strike / ppa_price if ppa_price > 0 else 1.0
    else:
        price_mult = 1.0
    upside_mult = price_mult * 1.08

    irr_upside = _equity_irr(
        capacity_mw, technology, ppa_price,
        price_mult=upside_mult,
    )
    base = _equity_irr(capacity_mw, technology, ppa_price)
    return {
        "case": "Upside — AR7 Pot 1 CfD (£67/MWh) + 5-yr capacity market contract",
        "base_irr_pct": base,
        "upside_irr_pct": irr_upside,
        "delta_pp": round(irr_upside - base, 2),
        "revenue_mult": round(upside_mult, 3),
    }
