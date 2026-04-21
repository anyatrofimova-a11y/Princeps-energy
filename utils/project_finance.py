#!/usr/bin/env python3
"""
Project finance engine — comprehensive 25-year DCF model.

Replaces Excel-based financial models with a lender-grade (DNV GL standard)
project finance engine. Full CAPEX breakdown, itemised OPEX, multi-stream
revenue, sculpted debt, tax shield, sensitivity/tornado analysis.

Standalone subprocess script (stdin JSON -> stdout JSON).

Commands:
  {"command": "project_model", "capacity_kwp": 50000, "technology": "solar", ...}
  {"command": "sensitivity", "capacity_kwp": 50000, ...}
  {"command": "summary", "capacity_kwp": 50000, ...}
"""
from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from typing import Any

from utils.bess_benchmarks import bess_revenue_mid
from utils.finance_benchmarks import (
    corporation_tax_rate,
    cpi_long_run,
    debt_tenor_years,
    debt_to_equity,
    egl_applies_to,
    egl_threshold_gbp_mwh,
    ppa_price_merchant,
    senior_debt_all_in_rate,
    wacc,
)

# ═══════════════════════════════════════════════════════════════════════════
# 1.  CAPEX BENCHMARKS  (£/kWp or £/kW unless noted)
# ═══════════════════════════════════════════════════════════════════════════

CAPEX_BENCHMARKS: dict[str, dict[str, float]] = {
    "solar": {
        "modules":          220,    # £/kWp — mono-PERC / TOPCon
        "inverters":         40,    # £/kW  — string or central
        "mounting_racking":  45,    # £/kWp — ground-mount tracker/fixed
        "electrical_bos":    35,    # £/kWp — cables, switchgear, transformer
        "civil_works":       30,    # £/kWp — access roads, fencing, drainage
        "grid_connection":    0,    # £ absolute — override from Princeps or user
        "development":       25,    # £/kWp — planning, surveys, legal, EIA
        "contingency_pct":  7.5,   # % of sub-total
    },
    "wind": {
        "modules":          850,    # £/kW  — turbine supply (WTG)
        "inverters":          0,    # included in WTG
        "mounting_racking":   0,    # N/A
        "electrical_bos":    80,    # £/kW
        "civil_works":      120,    # £/kW  — foundations, crane pads, roads
        "grid_connection":    0,
        "development":       45,    # £/kW
        "contingency_pct": 10.0,
    },
    "bess": {
        "modules":          320,    # £/kW  — battery packs (2h duration)
        "inverters":         60,    # £/kW  — PCS
        "mounting_racking":  15,    # £/kW  — containerised enclosures
        "electrical_bos":    50,    # £/kW  — HV, switchgear, SCADA
        "civil_works":       35,    # £/kW  — hardstanding, fencing, fire
        "grid_connection":    0,
        "development":       20,    # £/kW
        "contingency_pct":  7.5,
    },
    "offshore_wind": {
        "modules":         1600,    # £/kW  — WTG supply
        "inverters":          0,
        "mounting_racking": 400,    # £/kW  — foundations (monopile/jacket)
        "electrical_bos":   300,    # £/kW  — export cable, offshore substation
        "civil_works":      200,    # £/kW  — installation vessels
        "grid_connection":    0,
        "development":      100,    # £/kW
        "contingency_pct": 10.0,
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# 2.  OPEX BENCHMARKS  (annual, before escalation)
# ═══════════════════════════════════════════════════════════════════════════

OPEX_BENCHMARKS: dict[str, dict[str, float]] = {
    "solar": {
        "om_per_kw":         8.50,   # £/kW/yr — O&M contract
        "land_rent_per_ha": 1200,    # £/ha/yr
        "insurance_pct":    0.35,    # % of CAPEX
        "business_rates":   6000,    # £/MW/yr (VOA rateable value basis)
        "grid_charges":     3500,    # £/MW/yr — DUoS + TNUoS (embedded benefit)
        "management_admin": 2500,    # £/MW/yr — SPV admin, accounting, legal
    },
    "wind": {
        "om_per_kw":        22.0,
        "land_rent_per_ha": 1500,
        "insurance_pct":    0.40,
        "business_rates":   8000,
        "grid_charges":     4500,
        "management_admin": 3000,
    },
    "bess": {
        "om_per_kw":         6.0,
        "land_rent_per_ha":  800,
        "insurance_pct":    0.50,
        "business_rates":   3000,
        "grid_charges":     5000,
        "management_admin": 2000,
    },
    "offshore_wind": {
        "om_per_kw":        55.0,
        "land_rent_per_ha":    0,    # seabed lease handled differently
        "insurance_pct":    0.50,
        "business_rates":  10000,
        "grid_charges":     6000,
        "management_admin": 5000,
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# 3.  CAPACITY FACTORS & YIELD
# ═══════════════════════════════════════════════════════════════════════════

CAPACITY_FACTORS = {
    "solar":          0.110,   # UK average ground-mount
    "wind":           0.280,   # UK onshore
    "bess":           0.000,   # revenue-based, not generation
    "offshore_wind":  0.400,
}

# Land density (kWp per hectare)
LAND_DENSITY = {
    "solar":   800,    # ~0.8 MW/ha ground-mount
    "wind":    40,     # ~40 kW/ha (sparse spacing)
    "bess":  5000,     # compact footprint
    "offshore_wind": 0,
}

# BESS blended revenue (£/MW/yr) — arbitrage + FFR + CM + triad
# Sourced from Modo Energy GB BESS index, Mar 2026 (2h P50 benchmark).
BESS_REVENUE_PER_MW = bess_revenue_mid(2)

# ═══════════════════════════════════════════════════════════════════════════
# 4.  FINANCIAL PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════

# Defaults resolve through utils.finance_benchmarks so the whole stack
# tracks one set of UK-2026 capital-structure + tax + PPA assumptions.
# Callers (routers, subprocess bridges) override per deal; tech-specific
# values override module defaults when `technology` is provided.
DEFAULT_PARAMS = {
    "project_life_years":   25,
    "construction_months":  18,                 # solar; wind ~24; offshore ~36
    "degradation_rate":     0.005,              # 0.5% p.a.
    "cpi_escalation":       cpi_long_run(),     # 2.4% BoE long-run
    "corporation_tax":      corporation_tax_rate(),
    "discount_rate":        wacc("solar", "stabilised"),  # 8.5% solar stabilised
    "gearing":              debt_to_equity("solar")[0],   # 65% UK 2026 norm
    "senior_interest":      senior_debt_all_in_rate("solar"),  # SONIA+250bp
    "debt_term_years":      debt_tenor_years("solar"),    # 18y
    "target_dscr":          1.30,
    "lock_up_dscr":         1.15,
    "default_dscr":         1.05,
    "cash_reserve_months":  6,
    "ppa_price_mwh":        ppa_price_merchant("solar"),  # £48/MWh merchant
    "ppa_term_years":       15,
    "merchant_price_mwh":   ppa_price_merchant("solar", "low"),  # post-PPA tail
    "merchant_escalation":  0.02,
    "subsidy_type":         "none",              # none / roc / cfd
    "subsidy_value":        0.0,                 # £/MWh (ROC buyout) or CfD strike
    "capacity_market_rev":  0.0,                 # £/MW/yr (BESS)
    "ancillary_rev":        0.0,                 # £/MW/yr (BESS FFR etc.)
    "tax_depreciation_rate": 0.18,               # 18% reducing balance (main pool)
    "tax_depreciation_type": "reducing_balance", # or straight_line
}

CONSTRUCTION_MONTHS = {
    "solar": 12,
    "wind": 24,
    "bess": 9,
    "offshore_wind": 36,
}


# ═══════════════════════════════════════════════════════════════════════════
# 5.  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _irr_newton(cashflows: list[float], guess: float = 0.10,
                tol: float = 1e-9, max_iter: int = 300) -> float | None:
    """Solve IRR via Newton-Raphson on NPV = 0.

    Clamps r into (-0.95, 5.0) each iteration so a bad starting point
    cannot overflow `(1+r)**t` when t → 25+.
    """
    r = guess
    for _ in range(max_iter):
        # Clamp r to safe range before evaluating NPV to avoid OverflowError.
        r = max(-0.95, min(5.0, r))
        try:
            npv = sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
            dnpv = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cashflows))
        except (OverflowError, ZeroDivisionError):
            return None
        if abs(dnpv) < 1e-14:
            return None
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol:
            return round(r_new, 6)
        r = r_new
    r = max(-0.95, min(5.0, r))
    try:
        resid = abs(sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows)))
    except (OverflowError, ZeroDivisionError):
        return None
    return round(r, 6) if resid < 1.0 else None


def _npv(rate: float, cashflows: list[float]) -> float:
    """Net present value at given discount rate."""
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def _lcoe(total_capex: float, annual_opex_yr1: float, annual_gen_mwh: float,
          discount_rate: float, cpi: float, degradation: float,
          life: int) -> float:
    """Levelised Cost of Energy (£/MWh) — real-terms LCOE per BEIS methodology."""
    if annual_gen_mwh <= 0:
        return 0.0
    cost_pv = total_capex + sum(
        annual_opex_yr1 * (1 + cpi) ** y / (1 + discount_rate) ** y
        for y in range(1, life + 1)
    )
    gen_pv = sum(
        annual_gen_mwh * (1 - degradation) ** y / (1 + discount_rate) ** y
        for y in range(1, life + 1)
    )
    return cost_pv / gen_pv if gen_pv > 0 else 0.0


def _merge_params(user: dict) -> dict:
    """Merge user overrides into defaults.

    Keys in DEFAULT_PARAMS get overridden; extra keys (e.g. capex_*_per_kw,
    opex_* overrides, grid_connection_cost) pass through so that _build_capex
    and _build_opex_yr1 can pick them up via params.get().
    """
    p = dict(DEFAULT_PARAMS)
    for k, v in user.items():
        if v is not None:
            p[k] = v
    return p


# ═══════════════════════════════════════════════════════════════════════════
# 6.  CAPEX CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════

def _build_capex(capacity_kwp: float, technology: str, params: dict) -> dict:
    """Itemised CAPEX breakdown with contingency and benchmarking."""
    bench = CAPEX_BENCHMARKS.get(technology, CAPEX_BENCHMARKS["solar"])
    capacity_kw = capacity_kwp  # for solar kWp == kW(DC); for others treat as kW

    # User overrides for individual line items
    modules     = params.get("capex_modules_per_kw",     bench["modules"])     * capacity_kw
    inverters   = params.get("capex_inverters_per_kw",   bench["inverters"])   * capacity_kw
    mounting    = params.get("capex_mounting_per_kw",     bench["mounting_racking"]) * capacity_kw
    elec_bos    = params.get("capex_electrical_per_kw",  bench["electrical_bos"])   * capacity_kw
    civil       = params.get("capex_civil_per_kw",       bench["civil_works"])      * capacity_kw
    grid_conn   = params.get("grid_connection_cost",     bench["grid_connection"])   # absolute £
    development = params.get("capex_development_per_kw", bench["development"])      * capacity_kw
    contingency_pct = params.get("contingency_pct",      bench["contingency_pct"])

    sub_total = modules + inverters + mounting + elec_bos + civil + grid_conn + development
    contingency = sub_total * contingency_pct / 100.0
    total = sub_total + contingency

    return {
        "modules":             round(modules),
        "inverters":           round(inverters),
        "mounting_racking":    round(mounting),
        "electrical_bos":      round(elec_bos),
        "civil_works":         round(civil),
        "grid_connection":     round(grid_conn),
        "development":         round(development),
        "sub_total":           round(sub_total),
        "contingency_pct":     contingency_pct,
        "contingency":         round(contingency),
        "total_capex":         round(total),
        "capex_per_kwp":       round(total / capacity_kwp, 2) if capacity_kwp > 0 else 0,
        "capex_per_mw":        round(total / (capacity_kwp / 1000), 0) if capacity_kwp > 0 else 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 7.  OPEX CALCULATOR (year-1 baseline, before escalation)
# ═══════════════════════════════════════════════════════════════════════════

def _build_opex_yr1(capacity_kwp: float, technology: str,
                    total_capex: float, params: dict) -> dict:
    """Year-1 OPEX breakdown (pre-escalation)."""
    bench = OPEX_BENCHMARKS.get(technology, OPEX_BENCHMARKS["solar"])
    capacity_mw = capacity_kwp / 1000
    capacity_kw = capacity_kwp

    # Land area estimate
    density = LAND_DENSITY.get(technology, 800)
    site_ha = capacity_kwp / density if density > 0 else 0

    om_contract   = params.get("opex_om_per_kw", bench["om_per_kw"]) * capacity_kw
    land_rent     = params.get("opex_land_rent_per_ha", bench["land_rent_per_ha"]) * site_ha
    insurance_pct = params.get("opex_insurance_pct", bench["insurance_pct"])
    insurance     = total_capex * insurance_pct / 100.0
    biz_rates     = params.get("opex_business_rates_per_mw", bench["business_rates"]) * capacity_mw
    grid_charges  = params.get("opex_grid_charges_per_mw", bench["grid_charges"]) * capacity_mw
    mgmt_admin    = params.get("opex_management_per_mw", bench["management_admin"]) * capacity_mw

    total = om_contract + land_rent + insurance + biz_rates + grid_charges + mgmt_admin

    return {
        "om_contract":     round(om_contract),
        "land_rent":       round(land_rent),
        "insurance":       round(insurance),
        "business_rates":  round(biz_rates),
        "grid_charges":    round(grid_charges),
        "management_admin": round(mgmt_admin),
        "total_opex_yr1":  round(total),
        "opex_per_kw_yr1": round(total / capacity_kw, 2) if capacity_kw > 0 else 0,
        "site_area_ha":    round(site_ha, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 8.  TAX DEPRECIATION / CAPITAL ALLOWANCES
# ═══════════════════════════════════════════════════════════════════════════

def _tax_depreciation_schedule(total_capex: float, params: dict) -> list[float]:
    """Return annual tax depreciation (capital allowances) over project life."""
    life = params["project_life_years"]
    rate = params.get("tax_depreciation_rate", 0.18)
    dep_type = params.get("tax_depreciation_type", "reducing_balance")

    schedule = []
    if dep_type == "straight_line":
        annual = total_capex / life
        for _ in range(life):
            schedule.append(annual)
    else:  # reducing balance (UK main pool 18%)
        wdv = total_capex  # written-down value
        for y in range(life):
            dep = wdv * rate
            if y == life - 1:
                dep = wdv  # balancing allowance in final year
            schedule.append(dep)
            wdv -= dep
            if wdv < 0:
                wdv = 0
    return schedule


# ═══════════════════════════════════════════════════════════════════════════
# 9.  REVENUE MODEL
# ═══════════════════════════════════════════════════════════════════════════

def _annual_revenue(year: int, capacity_kwp: float, technology: str,
                    annual_gen_mwh_yr0: float, params: dict) -> dict:
    """Calculate revenue for a given operating year (1-indexed)."""
    degradation = params["degradation_rate"]
    cpi = params["cpi_escalation"]
    ppa_price = params["ppa_price_mwh"]
    ppa_term = params["ppa_term_years"]
    merchant_price = params["merchant_price_mwh"]
    merchant_esc = params["merchant_escalation"]
    subsidy_type = params.get("subsidy_type", "none")
    subsidy_val = params.get("subsidy_value", 0.0)
    capacity_mw = capacity_kwp / 1000
    is_bess = technology == "bess"

    if is_bess:
        # BESS revenue: arbitrage + capacity market + ancillary
        bess_base = params.get("bess_revenue_per_mw", BESS_REVENUE_PER_MW) * capacity_mw
        bess_degradation = degradation * 2  # batteries degrade faster
        arbitrage = bess_base * (1 + cpi) ** year * (1 - bess_degradation) ** year
        cm_rev = params.get("capacity_market_rev", 0) * capacity_mw * (1 + cpi) ** year
        anc_rev = params.get("ancillary_rev", 0) * capacity_mw * (1 + cpi) ** year
        return {
            "generation_mwh": 0,
            "ppa_revenue": 0,
            "merchant_revenue": 0,
            "subsidy_revenue": 0,
            "bess_arbitrage": round(arbitrage),
            "capacity_market": round(cm_rev),
            "ancillary_services": round(anc_rev),
            "total_revenue": round(arbitrage + cm_rev + anc_rev),
        }

    # Generation with degradation
    gen_mwh = annual_gen_mwh_yr0 * (1 - degradation) ** year

    # PPA revenue (within PPA term, CPI-escalated)
    if year <= ppa_term:
        eff_ppa_price = ppa_price * (1 + cpi) ** year
        ppa_rev = gen_mwh * eff_ppa_price
        merchant_rev = 0.0
    else:
        # Merchant tail — post-PPA
        years_merchant = year - ppa_term
        eff_merchant = merchant_price * (1 + merchant_esc) ** years_merchant
        ppa_rev = 0.0
        merchant_rev = gen_mwh * eff_merchant

    # Subsidy
    if subsidy_type == "roc" and subsidy_val > 0:
        subsidy_rev = gen_mwh * subsidy_val
    elif subsidy_type == "cfd" and subsidy_val > 0:
        # CfD top-up: strike - reference price (simplified)
        ref_price = ppa_price if year <= ppa_term else merchant_price
        top_up = max(0, subsidy_val - ref_price)
        subsidy_rev = gen_mwh * top_up * (1 + cpi) ** year
    else:
        subsidy_rev = 0.0

    total = ppa_rev + merchant_rev + subsidy_rev

    return {
        "generation_mwh":   round(gen_mwh, 1),
        "ppa_revenue":      round(ppa_rev),
        "merchant_revenue": round(merchant_rev),
        "subsidy_revenue":  round(subsidy_rev),
        "bess_arbitrage":   0,
        "capacity_market":  0,
        "ancillary_services": 0,
        "total_revenue":    round(total),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 10. FULL 25-YEAR DCF MODEL
# ═══════════════════════════════════════════════════════════════════════════

def calculate_project_finance(user_params: dict) -> dict:
    """
    Comprehensive 25-year DCF model — DNV GL / lender-standard output.

    Parameters
    ----------
    user_params : dict
        Required:
          capacity_kwp : float — installed capacity in kWp (e.g. 50000 = 50 MW)
          technology   : str   — solar / wind / bess / offshore_wind
        Optional (all have sensible UK defaults):
          ppa_price_mwh, discount_rate, gearing, senior_interest,
          grid_connection_cost, capex_*_per_kw overrides,
          opex_*_per_kw overrides, etc.

    Returns
    -------
    dict with keys:
      summary, capex_breakdown, opex_yr1, cashflow_annual (full 25yr),
      debt_schedule, returns, sensitivity_inputs
    """
    # ── Parse inputs ──────────────────────────────────────────────────────
    capacity_kwp = user_params.get("capacity_kwp", 50000)
    technology = user_params.get("technology", "solar")
    params = _merge_params(user_params)

    # Apply tech-specific UK-2026 finance benchmarks when the caller did not
    # explicitly override. (The DEFAULT_PARAMS dict is solar-biased; wind/
    # BESS/offshore/DC have their own capital-stack realities.)
    tech_lower = (technology or "solar").lower()
    if "gearing" not in user_params or user_params.get("gearing") is None:
        params["gearing"] = debt_to_equity(tech_lower)[0]
    if "senior_interest" not in user_params or user_params.get("senior_interest") is None:
        params["senior_interest"] = senior_debt_all_in_rate(tech_lower)
    if "debt_term_years" not in user_params or user_params.get("debt_term_years") is None:
        params["debt_term_years"] = debt_tenor_years(tech_lower)
    if "discount_rate" not in user_params or user_params.get("discount_rate") is None:
        params["discount_rate"] = wacc(tech_lower, "stabilised")
    if "ppa_price_mwh" not in user_params or user_params.get("ppa_price_mwh") is None:
        params["ppa_price_mwh"] = ppa_price_merchant(tech_lower)
    if "merchant_price_mwh" not in user_params or user_params.get("merchant_price_mwh") is None:
        params["merchant_price_mwh"] = ppa_price_merchant(tech_lower, "low")

    capacity_mw = capacity_kwp / 1000
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    life = params["project_life_years"]
    cpi = params["cpi_escalation"]
    degradation = params["degradation_rate"]
    discount_rate = params["discount_rate"]
    gearing = params["gearing"]
    interest_rate = params["senior_interest"]
    debt_term = params["debt_term_years"]
    target_dscr = params["target_dscr"]
    tax_rate = params["corporation_tax"]
    construction_months = params.get(
        "construction_months",
        CONSTRUCTION_MONTHS.get(technology, 18),
    )
    construction_years = max(1, round(construction_months / 12))

    # Annual generation (year-0 baseline, before degradation)
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0

    # ── CAPEX ─────────────────────────────────────────────────────────────
    capex = _build_capex(capacity_kwp, technology, params)
    total_capex = capex["total_capex"]

    # ── OPEX (year-1 baseline) ────────────────────────────────────────────
    opex_yr1 = _build_opex_yr1(capacity_kwp, technology, total_capex, params)
    total_opex_yr1 = opex_yr1["total_opex_yr1"]

    # ── Debt sizing ───────────────────────────────────────────────────────
    debt_amount = total_capex * gearing
    equity_amount = total_capex * (1 - gearing)

    # ── Tax depreciation schedule ─────────────────────────────────────────
    dep_schedule = _tax_depreciation_schedule(total_capex, params)

    # ── Construction cashflows ────────────────────────────────────────────
    project_cashflows = []       # for project IRR (pre-financing)
    equity_cashflows_pre = []    # equity IRR pre-tax
    equity_cashflows_post = []   # equity IRR post-tax

    for cy in range(construction_years):
        capex_spend = -total_capex / construction_years
        equity_inject = -equity_amount / construction_years
        project_cashflows.append(capex_spend)
        equity_cashflows_pre.append(equity_inject)
        equity_cashflows_post.append(equity_inject)

    # ── Year-by-year operating cashflow ───────────────────────────────────
    cashflow_annual = []
    debt_schedule = []
    outstanding_debt = debt_amount
    cumulative_cf = -total_capex
    payback_year = None
    total_generation_mwh = 0
    total_revenue_lifetime = 0
    total_opex_lifetime = 0

    for y in range(1, life + 1):
        # Revenue
        rev = _annual_revenue(y, capacity_kwp, technology, annual_gen_mwh, params)
        revenue = rev["total_revenue"]
        gen_mwh = rev["generation_mwh"]
        total_generation_mwh += gen_mwh
        total_revenue_lifetime += revenue

        # OPEX (escalated by CPI)
        opex = total_opex_yr1 * (1 + cpi) ** y
        total_opex_lifetime += opex

        # EBITDA
        ebitda = revenue - opex

        # Tax depreciation / capital allowances
        dep_y = dep_schedule[y - 1] if y - 1 < len(dep_schedule) else 0

        # Debt service (sculpted repayment)
        if outstanding_debt > 0 and y <= debt_term:
            interest = outstanding_debt * interest_rate
            cfads = ebitda  # cash flow available for debt service
            max_ds = cfads / target_dscr if target_dscr > 0 else cfads
            principal = min(max(0, max_ds - interest), outstanding_debt)
            debt_service = interest + principal
            outstanding_debt -= principal
            dscr = cfads / debt_service if debt_service > 0 else 99.0
        else:
            interest = 0
            principal = 0
            debt_service = 0
            dscr = 99.0

        # Taxable profit (EBITDA - interest - depreciation)
        taxable = max(0, ebitda - interest - dep_y)
        tax = taxable * tax_rate

        # Net cashflow (project level, pre-financing)
        net_cf_project = ebitda - tax
        project_cashflows.append(net_cf_project)

        # Equity cashflow (after debt service and tax)
        pre_tax_equity_cf = ebitda - debt_service
        post_tax_equity_cf = pre_tax_equity_cf - tax
        equity_cashflows_pre.append(pre_tax_equity_cf)
        equity_cashflows_post.append(max(0, post_tax_equity_cf))

        # Cumulative for payback
        cumulative_cf += net_cf_project
        if payback_year is None and cumulative_cf >= 0:
            payback_year = y + construction_years

        # Store annual row
        cashflow_annual.append({
            "year": y,
            "generation_mwh":   gen_mwh,
            "ppa_revenue":      rev["ppa_revenue"],
            "merchant_revenue": rev["merchant_revenue"],
            "subsidy_revenue":  rev["subsidy_revenue"],
            "bess_arbitrage":   rev["bess_arbitrage"],
            "capacity_market":  rev["capacity_market"],
            "ancillary_services": rev["ancillary_services"],
            "total_revenue":    round(revenue),
            "total_opex":       round(opex),
            "ebitda":           round(ebitda),
            "depreciation":     round(dep_y),
            "interest":         round(interest),
            "principal":        round(principal),
            "debt_service":     round(debt_service),
            "tax":              round(tax),
            "net_cashflow":     round(net_cf_project),
            "equity_cashflow":  round(max(0, post_tax_equity_cf)),
            "cumulative_cf":    round(cumulative_cf),
            "dscr":             round(dscr, 2),
        })

        if y <= debt_term and debt_service > 0:
            debt_schedule.append({
                "year": y,
                "opening_balance": round(outstanding_debt + principal),
                "interest":        round(interest),
                "principal":       round(principal),
                "debt_service":    round(debt_service),
                "closing_balance": round(outstanding_debt),
                "dscr":            round(dscr, 2),
            })

    # ── Key return metrics ────────────────────────────────────────────────
    project_irr = _irr_newton(project_cashflows)
    equity_irr_pre = _irr_newton(equity_cashflows_pre)
    equity_irr_post = _irr_newton(equity_cashflows_post)

    npv_at_discount = _npv(discount_rate, project_cashflows)
    npv_at_6 = _npv(0.06, project_cashflows)
    npv_at_8 = _npv(0.08, project_cashflows)
    npv_at_10 = _npv(0.10, project_cashflows)

    lcoe = _lcoe(total_capex, total_opex_yr1, annual_gen_mwh,
                 discount_rate, cpi, degradation, life)

    # DSCR statistics (operating years with debt)
    dscr_values = [row["dscr"] for row in cashflow_annual if row["dscr"] < 90]
    min_dscr = min(dscr_values) if dscr_values else 0
    avg_dscr = sum(dscr_values) / len(dscr_values) if dscr_values else 0

    # Cash-on-cash yield (average annual equity CF / equity invested)
    total_equity_cf = sum(row["equity_cashflow"] for row in cashflow_annual)
    avg_annual_equity = total_equity_cf / life if life > 0 else 0
    cash_on_cash = avg_annual_equity / equity_amount * 100 if equity_amount > 0 else 0

    # Equity multiple
    equity_multiple = (equity_amount + total_equity_cf) / equity_amount if equity_amount > 0 else 0

    # Covenant check
    lock_up = params.get("lock_up_dscr", 1.15)
    default_threshold = params.get("default_dscr", 1.05)
    covenant_status = "PASS"
    if min_dscr < default_threshold:
        covenant_status = "DEFAULT_BREACH"
    elif min_dscr < lock_up:
        covenant_status = "LOCK_UP"

    returns = {
        "project_irr_pct":        round(project_irr * 100, 2) if project_irr else None,
        "equity_irr_pre_tax_pct": round(equity_irr_pre * 100, 2) if equity_irr_pre else None,
        "equity_irr_post_tax_pct": round(equity_irr_post * 100, 2) if equity_irr_post else None,
        "npv_at_discount_rate":   round(npv_at_discount),
        "npv_6pct":               round(npv_at_6),
        "npv_8pct":               round(npv_at_8),
        "npv_10pct":              round(npv_at_10),
        "lcoe_per_mwh":           round(lcoe, 2),
        "simple_payback_years":   payback_year,
        "dscr_min":               round(min_dscr, 2),
        "dscr_avg":               round(avg_dscr, 2),
        "covenant_status":        covenant_status,
        "equity_multiple":        round(equity_multiple, 2),
        "cash_on_cash_yield_pct": round(cash_on_cash, 2),
        "total_generation_mwh":   round(total_generation_mwh),
        "total_revenue_lifetime": round(total_revenue_lifetime),
        "total_opex_lifetime":    round(total_opex_lifetime),
        "egl_applies":            egl_applies_to(tech_lower),
        "egl_threshold_gbp_mwh":  egl_threshold_gbp_mwh(),
    }

    # ── Summary ───────────────────────────────────────────────────────────
    summary = {
        "capacity_kwp":        capacity_kwp,
        "capacity_mw":         capacity_mw,
        "technology":          technology,
        "project_life_years":  life,
        "construction_months": construction_months,
        "capacity_factor":     cf,
        "annual_yield_mwh":    round(annual_gen_mwh),
        "specific_yield_kwh_kwp": round(cf * 8760, 1),
        "total_capex":         total_capex,
        "capex_per_kwp":       capex["capex_per_kwp"],
        "total_opex_yr1":      total_opex_yr1,
        "gearing_pct":         round(gearing * 100, 1),
        "debt_amount":         round(debt_amount),
        "equity_amount":       round(equity_amount),
        "ppa_price_mwh":       params["ppa_price_mwh"],
        "ppa_term_years":      params["ppa_term_years"],
        "discount_rate":       discount_rate,
    }

    return {
        "summary":          summary,
        "capex_breakdown":  capex,
        "opex_yr1":         opex_yr1,
        "returns":          returns,
        "cashflow_annual":  cashflow_annual,
        "debt_schedule":    debt_schedule,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 11. SENSITIVITY ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def run_sensitivity(user_params: dict) -> dict:
    """
    Tornado sensitivity analysis — vary key inputs and measure IRR/NPV impact.

    Varies:
      - PPA price:     +/-20%
      - CAPEX:         +/-15%
      - Yield:         +/-10%
      - Discount rate: +/-200 bps
      - OPEX:          +/-15%
      - Gearing:       +/-10 ppts

    Returns tornado chart data (sorted by impact magnitude) + scenario matrix.
    """
    # Run base case
    base = calculate_project_finance(user_params)
    base_irr = base["returns"]["project_irr_pct"]
    base_npv = base["returns"]["npv_at_discount_rate"]
    base_lcoe = base["returns"]["lcoe_per_mwh"]

    if base_irr is None:
        base_irr = 0.0

    capacity_kwp = user_params.get("capacity_kwp", 50000)
    technology = user_params.get("technology", "solar")
    params = _merge_params(user_params)

    # Define sensitivity axes
    axes = [
        {
            "variable": "PPA Price",
            "unit": "£/MWh",
            "base_value": params["ppa_price_mwh"],
            "param_key": "ppa_price_mwh",
            "low_factor": 0.80,
            "high_factor": 1.20,
        },
        {
            "variable": "Total CAPEX",
            "unit": "£/kWp",
            "base_value": base["capex_breakdown"]["capex_per_kwp"],
            "param_key": "_capex_multiplier",
            "low_factor": 0.85,
            "high_factor": 1.15,
        },
        {
            "variable": "Annual Yield",
            "unit": "MWh",
            "base_value": base["summary"]["annual_yield_mwh"],
            "param_key": "_yield_multiplier",
            "low_factor": 0.90,
            "high_factor": 1.10,
        },
        {
            "variable": "Discount Rate",
            "unit": "%",
            "base_value": params["discount_rate"] * 100,
            "param_key": "discount_rate",
            "low_delta": -0.02,
            "high_delta": 0.02,
        },
        {
            "variable": "OPEX",
            "unit": "£/kW/yr",
            "base_value": base["opex_yr1"]["opex_per_kw_yr1"],
            "param_key": "_opex_multiplier",
            "low_factor": 0.85,
            "high_factor": 1.15,
        },
        {
            "variable": "Gearing",
            "unit": "%",
            "base_value": params["gearing"] * 100,
            "param_key": "gearing",
            "low_delta": -0.10,
            "high_delta": 0.10,
        },
    ]

    tornado_data = []
    scenario_matrix = []

    for axis in axes:
        # Build low/high parameter sets
        low_params = dict(user_params)
        high_params = dict(user_params)

        key = axis["param_key"]

        if "low_factor" in axis:
            factor_lo = axis["low_factor"]
            factor_hi = axis["high_factor"]

            if key == "_capex_multiplier":
                # Scale all CAPEX line items
                bench = CAPEX_BENCHMARKS.get(technology, CAPEX_BENCHMARKS["solar"])
                for ckey in ["modules", "inverters", "mounting_racking",
                             "electrical_bos", "civil_works", "development"]:
                    param_name = f"capex_{ckey.replace('mounting_racking', 'mounting').replace('electrical_bos', 'electrical')}_per_kw"
                    if ckey == "mounting_racking":
                        param_name = "capex_mounting_per_kw"
                    elif ckey == "electrical_bos":
                        param_name = "capex_electrical_per_kw"
                    else:
                        param_name = f"capex_{ckey}_per_kw"
                    low_params[param_name] = bench[ckey] * factor_lo
                    high_params[param_name] = bench[ckey] * factor_hi
            elif key == "_yield_multiplier":
                # Adjust capacity factor to simulate yield change
                base_cf = CAPACITY_FACTORS.get(technology, 0.11)
                low_params["_cf_override"] = base_cf * factor_lo
                high_params["_cf_override"] = base_cf * factor_hi
            elif key == "_opex_multiplier":
                bench = OPEX_BENCHMARKS.get(technology, OPEX_BENCHMARKS["solar"])
                for okey, pkey in [
                    ("om_per_kw", "opex_om_per_kw"),
                    ("land_rent_per_ha", "opex_land_rent_per_ha"),
                    ("business_rates", "opex_business_rates_per_mw"),
                    ("grid_charges", "opex_grid_charges_per_mw"),
                    ("management_admin", "opex_management_per_mw"),
                ]:
                    low_params[pkey] = bench[okey] * factor_lo
                    high_params[pkey] = bench[okey] * factor_hi
            else:
                low_params[key] = params[key] * factor_lo
                high_params[key] = params[key] * factor_hi
        else:
            # Delta-based (discount rate, gearing)
            low_params[key] = max(0.01, params[key] + axis["low_delta"])
            high_params[key] = min(0.99, params[key] + axis["high_delta"])

        # Handle CF override for yield sensitivity
        if "_cf_override" in low_params:
            cf_lo = low_params.pop("_cf_override")
            # Monkey-patch via a wrapper — simplest approach: override annual gen
            _orig_cf = CAPACITY_FACTORS.get(technology, 0.11)
            CAPACITY_FACTORS[technology] = cf_lo
            low_result = calculate_project_finance(low_params)
            CAPACITY_FACTORS[technology] = _orig_cf
        else:
            low_result = calculate_project_finance(low_params)

        if "_cf_override" in high_params:
            cf_hi = high_params.pop("_cf_override")
            _orig_cf = CAPACITY_FACTORS.get(technology, 0.11)
            CAPACITY_FACTORS[technology] = cf_hi
            high_result = calculate_project_finance(high_params)
            CAPACITY_FACTORS[technology] = _orig_cf
        else:
            high_result = calculate_project_finance(high_params)

        low_irr = low_result["returns"]["project_irr_pct"] or 0
        high_irr = high_result["returns"]["project_irr_pct"] or 0
        low_npv = low_result["returns"]["npv_at_discount_rate"]
        high_npv = high_result["returns"]["npv_at_discount_rate"]

        irr_spread = abs(high_irr - low_irr)
        npv_spread = abs(high_npv - low_npv)

        tornado_data.append({
            "variable":    axis["variable"],
            "unit":        axis["unit"],
            "base_value":  axis["base_value"],
            "irr_low":     round(low_irr, 2),
            "irr_base":    round(base_irr, 2),
            "irr_high":    round(high_irr, 2),
            "irr_spread":  round(irr_spread, 2),
            "npv_low":     round(low_npv),
            "npv_base":    round(base_npv),
            "npv_high":    round(high_npv),
            "npv_spread":  round(npv_spread),
        })

    # Sort by IRR spread descending (most impactful first)
    tornado_data.sort(key=lambda x: x["irr_spread"], reverse=True)

    # Build scenario matrix: 3x3 PPA price vs CAPEX
    ppa_base = params["ppa_price_mwh"]
    ppa_steps = [ppa_base * 0.85, ppa_base, ppa_base * 1.15]
    capex_bench = CAPEX_BENCHMARKS.get(technology, CAPEX_BENCHMARKS["solar"])

    for ppa_val in ppa_steps:
        for capex_mult in [0.90, 1.00, 1.10]:
            sc_params = dict(user_params)
            sc_params["ppa_price_mwh"] = ppa_val
            for ckey in ["modules", "inverters", "mounting_racking",
                         "electrical_bos", "civil_works", "development"]:
                if ckey == "mounting_racking":
                    param_name = "capex_mounting_per_kw"
                elif ckey == "electrical_bos":
                    param_name = "capex_electrical_per_kw"
                else:
                    param_name = f"capex_{ckey}_per_kw"
                sc_params[param_name] = capex_bench[ckey] * capex_mult

            sc_result = calculate_project_finance(sc_params)
            scenario_matrix.append({
                "ppa_price_mwh":   round(ppa_val, 1),
                "capex_multiplier": capex_mult,
                "project_irr_pct": sc_result["returns"]["project_irr_pct"],
                "npv":             sc_result["returns"]["npv_at_discount_rate"],
                "lcoe":            sc_result["returns"]["lcoe_per_mwh"],
                "dscr_min":        sc_result["returns"]["dscr_min"],
            })

    return {
        "base_case": {
            "project_irr_pct": base_irr,
            "npv":             base_npv,
            "lcoe":            base_lcoe,
        },
        "tornado":        tornado_data,
        "scenario_matrix": scenario_matrix,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 12. SUMMARY (condensed output for chat/agent)
# ═══════════════════════════════════════════════════════════════════════════

def project_summary(user_params: dict) -> dict:
    """Return a concise summary suitable for chat display or agent verdict."""
    result = calculate_project_finance(user_params)
    s = result["summary"]
    r = result["returns"]
    c = result["capex_breakdown"]
    o = result["opex_yr1"]

    # Verdict
    irr = r["project_irr_pct"]
    if irr is None:
        verdict = "NO-GO"
        verdict_reason = "IRR could not be calculated — project economics unviable"
    elif irr >= 10:
        verdict = "GO"
        verdict_reason = f"Project IRR of {irr}% exceeds 10% hurdle rate"
    elif irr >= 7:
        verdict = "CAUTION"
        verdict_reason = f"Project IRR of {irr}% is marginal (7-10% range)"
    else:
        verdict = "NO-GO"
        verdict_reason = f"Project IRR of {irr}% below 7% minimum threshold"

    return {
        "verdict":           verdict,
        "verdict_reason":    verdict_reason,
        "capacity_mw":       s["capacity_mw"],
        "technology":        s["technology"],
        "total_capex":       s["total_capex"],
        "capex_per_kwp":     c["capex_per_kwp"],
        "annual_yield_mwh":  s["annual_yield_mwh"],
        "ppa_price_mwh":     s["ppa_price_mwh"],
        "project_irr_pct":   r["project_irr_pct"],
        "equity_irr_pct":    r["equity_irr_post_tax_pct"],
        "npv":               r["npv_at_discount_rate"],
        "lcoe_per_mwh":      r["lcoe_per_mwh"],
        "payback_years":     r["simple_payback_years"],
        "dscr_min":          r["dscr_min"],
        "dscr_avg":          r["dscr_avg"],
        "covenant_status":   r["covenant_status"],
        "equity_multiple":   r["equity_multiple"],
        "cash_on_cash_pct":  r["cash_on_cash_yield_pct"],
        "opex_yr1":          o["total_opex_yr1"],
        "gearing_pct":       s["gearing_pct"],
        "debt_amount":       s["debt_amount"],
        "equity_amount":     s["equity_amount"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 13. SUBPROCESS BRIDGE
# ═══════════════════════════════════════════════════════════════════════════

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.pop("command", "project_model")

    try:
        if cmd == "project_model":
            result = calculate_project_finance(req)
        elif cmd == "sensitivity":
            result = run_sensitivity(req)
        elif cmd == "summary":
            result = project_summary(req)
        else:
            result = {"error": f"Unknown command: {cmd}"}
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
