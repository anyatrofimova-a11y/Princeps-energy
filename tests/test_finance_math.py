"""Finance engineering-math smoke tests.

Three scenarios stress the central `utils.finance_benchmarks` wiring:

  1. 50 MW solar with CfD AR7 Pot 1 offtake — stabilised merchant-floor case.
  2. 100 MW / 200 MWh BESS merchant — Modo-Energy revenue stack with tighter
     gearing + shorter tenor.
  3. 50 MW DC hyperscaler lease — capacity-charge contract, longer tenor.

All three must produce an IRR inside [8%, 18%] to prove the benchmark
defaults are realistic for 2026 UK deals. Any slip outside the band is
a regression in finance_benchmarks, DEFAULT_PARAMS, or the per-tech
override block in `utils.project_finance.calculate_project_finance`.

Run:
    pytest tests/test_finance_math.py -v
"""

from __future__ import annotations

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from utils import finance_benchmarks as fb
from utils.investment_appraisal import project_finance
from utils.project_finance import calculate_project_finance
from utils.monte_carlo_finance import default_evaluator


# ---------------------------------------------------------------------------
# Hard bounds — any deal with IRR outside this band means the benchmarks
# or the overrides drifted. Tight enough to catch lazy stubs (e.g. hardcoded
# £55 PPA on BESS) but wide enough to absorb normal sensitivity.
# ---------------------------------------------------------------------------

IRR_LOWER_BOUND_PCT = 8.0
IRR_UPPER_BOUND_PCT = 18.0


# ═══════════════════════════════════════════════════════════════════════════
# 1. Benchmark module sanity
# ═══════════════════════════════════════════════════════════════════════════

def test_benchmark_module_shape():
    """All required public functions exist and return plausible UK-2026 values."""
    assert 0.07 <= fb.wacc("solar", "stabilised") <= 0.11
    assert 0.08 <= fb.wacc("wind", "stabilised") <= 0.12
    assert 0.10 <= fb.wacc("bess", "stabilised") <= 0.18
    assert 0.08 <= fb.wacc("dc", "stabilised") <= 0.12

    debt, equity = fb.debt_to_equity("solar")
    assert math.isclose(debt + equity, 1.0, abs_tol=1e-6)
    assert 0.55 <= debt <= 0.75   # UK renewables 2026 norm

    assert 40 <= fb.ppa_price_merchant("solar") <= 55
    assert 42 <= fb.ppa_price_merchant("wind") <= 65
    assert 55 <= fb.ppa_price_merchant("bess") <= 80
    assert 60 <= fb.ppa_price_merchant("dc") <= 95

    assert 60 <= fb.cfd_strike_2026(pot=1) <= 72
    assert fb.egl_threshold_gbp_mwh() > 0
    assert fb.egl_applies_to("solar") is True
    assert fb.egl_applies_to("bess") is False
    assert fb.egl_applies_to("dc") is False
    assert fb.cpi_long_run() < 0.035
    assert fb.corporation_tax_rate() == 0.25


# ═══════════════════════════════════════════════════════════════════════════
# 2. Scenario 1 — 50 MW solar with CfD AR7 Pot 1 offtake
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario_50mw_solar_cfd():
    """50 MW solar with CfD AR7 Pot 1 (£67/MWh) — levered equity IRR.

    Unlevered project IRR for UK solar normally prints 5-8%; levered
    equity IRR (65:35 gearing, SONIA+250bp senior debt) is the 10-14%
    range institutional sponsors target. We assert against equity IRR.
    """
    from utils.investment_appraisal import equity_returns

    # Project-level snapshot for EGL + CapEx sanity
    pf = project_finance(
        capacity_mw=50,
        technology="solar",
        region="Midlands",
        ppa_price=fb.cfd_strike_2026(pot=1),
        discount_rate=fb.wacc("solar", "stabilised"),
    )
    assert pf["project_irr"] is not None, "Solar project IRR failed to solve"
    assert pf["egl_applies"] is True
    assert pf["egl_threshold_gbp_mwh"] > 0

    # Levered equity IRR — primary IRR check against institutional band
    eq = equity_returns(
        capacity_mw=50,
        technology="solar",
        ppa_price=fb.cfd_strike_2026(pot=1),
    )
    irr = eq["equity_irr_post_tax_pct"]
    assert irr is not None, "Solar equity IRR failed to solve"
    assert IRR_LOWER_BOUND_PCT <= irr <= IRR_UPPER_BOUND_PCT, (
        f"Solar CfD equity IRR {irr}% outside plausible [{IRR_LOWER_BOUND_PCT}, "
        f"{IRR_UPPER_BOUND_PCT}] band — check finance_benchmarks.ppa_price_merchant"
    )
    assert eq["egl_applies"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. Scenario 2 — 100 MW / 200 MWh BESS merchant
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario_100mw_bess_merchant():
    """100 MW 2h BESS on merchant-only revenue stack — IRR within band."""
    out = calculate_project_finance({
        "capacity_kwp": 100_000,       # 100 MW nameplate
        "technology": "bess",
        # No PPA — merchant arbitrage + FFR + capacity market stacked
        # through utils.project_finance's BESS revenue path.
    })
    irr = out["returns"]["project_irr_pct"]
    assert irr is not None, "BESS merchant IRR failed to solve"
    assert IRR_LOWER_BOUND_PCT <= irr <= IRR_UPPER_BOUND_PCT, (
        f"BESS merchant IRR {irr}% outside plausible band — "
        "check bess_benchmarks.bess_revenue_mid and finance_benchmarks.debt_to_equity('bess')"
    )
    # BESS is NOT EGL-in-scope
    assert out["returns"]["egl_applies"] is False
    # Sanity on capital stack — BESS should have tighter gearing than solar
    assert out["summary"]["gearing_pct"] <= 60.0


# ═══════════════════════════════════════════════════════════════════════════
# 4. Scenario 3 — 50 MW DC hyperscaler lease (tenanted capacity charge)
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario_50mw_dc_hyperscaler():
    """50 MW DC hyperscaler on 15yr powered-shell + MEP lease.

    JLL/CBRE Q1 2026 UK data-centre index: powered-shell development yields
    of ~9-11% for hyperscale 50-100MW deals. Lease is structured on
    £/MW/month capacity rent (take-or-pay) + opex pass-through.

    Scenario model (simplified, excludes energy pass-through which is
    revenue-neutral): shell+MEP CapEx £3.5m/MW × 50MW = £175m;
    capacity rent £35k/MW/month × 50MW × 12mo = £21m/yr (fully-fit-out
    powered shell, hyperscale tier); opex £3m/yr (staff + rates +
    insurance + maintenance).
    """
    capacity_mw = 50
    capex_gbp_m = capacity_mw * 3.5          # £175m shell+MEP CapEx
    revenue_gbp_m_yr = (capacity_mw * 35_000 * 12) / 1_000_000  # £21m/yr
    opex_gbp_m_yr = capacity_mw * 0.06       # £3m/yr opex

    out = default_evaluator({
        "capex_gbp_m": capex_gbp_m,
        "opex_gbp_m_yr": opex_gbp_m_yr,
        "revenue_gbp_m_yr": revenue_gbp_m_yr,
        "curtail_pct": 0.0,                  # DC does not curtail
        "timeline_months": 24,
        "discount_rate_pct": round(fb.wacc("dc", "stabilised") * 100, 2),
        "life_years": 20,
        "technology": "dc",
    })
    irr = out["irr_pct"]
    assert irr is not None, "DC IRR failed to solve"
    assert IRR_LOWER_BOUND_PCT <= irr <= IRR_UPPER_BOUND_PCT, (
        f"DC hyperscaler IRR {irr}% outside plausible band "
        f"[{IRR_LOWER_BOUND_PCT}, {IRR_UPPER_BOUND_PCT}]"
    )
    # DC not EGL-in-scope
    assert out["egl_applies"] is False
    assert out["egl_threshold_gbp_mwh"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. DCF evaluator carries EGL fields through
# ═══════════════════════════════════════════════════════════════════════════

def test_dcf_evaluator_egl_flags():
    """DCFEvaluator summary must include egl_applies + egl_threshold_gbp_mwh."""
    from utils.dcf_evaluator import DCFEvaluator
    life = 20
    ev = DCFEvaluator(
        capex=50_000_000,
        revenue_schedule=[5_000_000] * life,
        opex_schedule=[800_000] * life,
        technology="wind",
    )
    r = ev.evaluate()
    assert r.summary["egl_applies"] is True         # wind is in-scope
    assert r.summary["egl_threshold_gbp_mwh"] > 0
    assert r.summary["technology"] == "wind"

    ev_dc = DCFEvaluator(
        capex=100_000_000,
        revenue_schedule=[10_000_000] * life,
        opex_schedule=[1_500_000] * life,
        technology="dc",
    )
    r_dc = ev_dc.evaluate()
    assert r_dc.summary["egl_applies"] is False     # DC is out-of-scope


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
