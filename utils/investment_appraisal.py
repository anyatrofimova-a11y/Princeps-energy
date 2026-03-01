"""
Investment appraisal — 25-year project finance model.

Standalone subprocess script (stdin JSON → stdout JSON).

Commands:
  {"command": "project_finance", "capacity_mw": 50, "technology": "wind", "region": "Scotland", "ppa_price": 55}
  {"command": "debt_structure", "capacity_mw": 50, "technology": "wind", "target_dscr": 1.3, "gearing": 0.7}
  {"command": "equity_returns", "capacity_mw": 50, "technology": "wind", "gearing": 0.7, "ppa_price": 55}
"""
from __future__ import annotations

import json
import math
import sys

# ── Constants ──────────────────────────────────────────────────────────────────

CAPEX_PER_MW = {
    "wind": 1_250_000,       # £/MW onshore wind
    "solar": 550_000,        # £/MW ground-mount solar
    "bess": 600_000,         # £/MW (2h duration)
    "offshore_wind": 2_800_000,
}

OPEX_PER_MW = {
    "wind": 42_000,          # £/MW/yr
    "solar": 12_000,
    "bess": 10_000,
    "offshore_wind": 85_000,
}

CAPACITY_FACTORS = {
    "wind": 0.28,
    "solar": 0.11,
    "bess": 0.0,            # BESS uses REVENUE_PER_MW instead
    "offshore_wind": 0.40,
}

# BESS earns from arbitrage, frequency response, capacity market — not generation
REVENUE_PER_MW = {
    "bess": 75_000,          # £/MW/yr blended revenue (UK 2h BESS)
}

WACC_BENCHMARK = 0.075       # 7.5% nominal pre-tax WACC
TYPICAL_GEARING = 0.70       # 70% debt
INTEREST_RATES = {
    "senior": 0.055,         # 5.5% senior debt
    "mezzanine": 0.085,
}
DEBT_TERM_YEARS = 18
DEGRADATION_RATE = 0.005     # 0.5% p.a. for wind/solar
CORPORATION_TAX = 0.25
DEFAULT_PPA_PRICE = 55.0     # £/MWh
CONSTRUCTION_YEARS = 2
PROJECT_LIFE = 25
INFLATION = 0.025            # 2.5% CPI
DISCOUNT_RATES = [0.06, 0.08, 0.10]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _irr_newton(cashflows: list[float], guess: float = 0.10, tol: float = 1e-8, max_iter: int = 200) -> float | None:
    """Solve IRR via Newton-Raphson on NPV function."""
    r = guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        dnpv = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-14:
            return None
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol:
            return r_new
        r = r_new
    return r if abs(sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))) < 1.0 else None


def _npv(rate: float, cashflows: list[float]) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def _lcoe(total_capex: float, annual_opex: float, annual_gen_mwh: float,
           discount_rate: float = 0.08, life: int = PROJECT_LIFE) -> float:
    """Levelised cost of energy £/MWh."""
    num = total_capex + sum(annual_opex * (1 + INFLATION) ** y / (1 + discount_rate) ** y for y in range(1, life + 1))
    den = sum(annual_gen_mwh * (1 - DEGRADATION_RATE) ** y / (1 + discount_rate) ** y for y in range(1, life + 1))
    return num / den if den > 0 else 0.0


# ── Commands ───────────────────────────────────────────────────────────────────

def project_finance(capacity_mw: float = 50, technology: str = "wind",
                    region: str = "Scotland", ppa_price: float = DEFAULT_PPA_PRICE,
                    discount_rate: float = 0.08) -> dict:
    """Full DCF cashflow model — construction + operating periods."""
    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    cf = CAPACITY_FACTORS.get(technology, 0.28)

    total_capex = capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0

    # Build cashflow array: year 0-1 construction, years 2-26 operating
    cashflows = []
    # Construction spend (split equally)
    for y in range(CONSTRUCTION_YEARS):
        cashflows.append(-total_capex / CONSTRUCTION_YEARS)

    yearly_detail = []
    for y in range(1, PROJECT_LIFE + 1):
        degraded_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y if not is_bess else 0
        if is_bess:
            revenue = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            revenue = degraded_gen * ppa_price * (1 + INFLATION) ** y
        opex = annual_opex * (1 + INFLATION) ** y
        ebitda = revenue - opex
        tax = max(0, ebitda * CORPORATION_TAX)
        net_cf = ebitda - tax
        cashflows.append(net_cf)
        yearly_detail.append({
            "year": y,
            "revenue": round(revenue),
            "opex": round(opex),
            "ebitda": round(ebitda),
            "tax": round(tax),
            "net_cashflow": round(net_cf),
        })

    project_irr = _irr_newton(cashflows)
    npv_results = {f"npv_{int(r*100)}pct": round(_npv(r, cashflows)) for r in DISCOUNT_RATES}
    lcoe = _lcoe(total_capex, annual_opex, annual_gen_mwh, discount_rate)

    # Simple payback
    cumulative = 0
    payback_year = None
    for i, cf_val in enumerate(cashflows):
        cumulative += cf_val
        if cumulative >= 0 and i >= CONSTRUCTION_YEARS:
            payback_year = i
            break

    # Truncated cashflow: years 1-5 + last
    truncated = yearly_detail[:5] + [yearly_detail[-1]] if len(yearly_detail) > 5 else yearly_detail

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "total_capex": round(total_capex),
        "annual_opex_yr1": round(annual_opex),
        "annual_generation_mwh": round(annual_gen_mwh),
        "ppa_price": ppa_price,
        "wacc": WACC_BENCHMARK,
        "project_irr": round(project_irr * 100, 2) if project_irr else None,
        **npv_results,
        "lcoe": round(lcoe, 2),
        "simple_payback_years": payback_year,
        "project_life_years": PROJECT_LIFE,
        "construction_years": CONSTRUCTION_YEARS,
        "cashflow_truncated": truncated,
    }


def debt_structure(capacity_mw: float = 50, technology: str = "wind",
                   target_dscr: float = 1.3, gearing: float = TYPICAL_GEARING,
                   ppa_price: float = DEFAULT_PPA_PRICE) -> dict:
    """Senior debt sizing with sculpted repayment profile."""
    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    cf = CAPACITY_FACTORS.get(technology, 0.28)

    total_capex = capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0

    debt_amount = total_capex * gearing
    equity_amount = total_capex * (1 - gearing)
    interest_rate = INTEREST_RATES["senior"]

    # Sculpted repayment: debt service = CFADS / target_dscr
    sculpted = []
    outstanding = debt_amount
    for y in range(1, DEBT_TERM_YEARS + 1):
        if is_bess:
            revenue = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            degraded_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            revenue = degraded_gen * ppa_price * (1 + INFLATION) ** y
        opex = annual_opex * (1 + INFLATION) ** y
        cfads = revenue - opex  # cash flow available for debt service
        max_ds = cfads / target_dscr
        interest = outstanding * interest_rate
        principal = min(max(0, max_ds - interest), outstanding)
        actual_ds = interest + principal
        actual_dscr = cfads / actual_ds if actual_ds > 0 else 99.0
        outstanding -= principal
        sculpted.append({
            "year": y,
            "cfads": round(cfads),
            "debt_service": round(actual_ds),
            "principal": round(principal),
            "interest": round(interest),
            "outstanding": round(outstanding),
            "dscr": round(actual_dscr, 2),
        })
        if outstanding <= 0:
            break

    avg_dscr = sum(s["dscr"] for s in sculpted) / len(sculpted) if sculpted else 0
    min_dscr = min(s["dscr"] for s in sculpted) if sculpted else 0

    # Truncate: first 5 + last
    truncated = sculpted[:5] + [sculpted[-1]] if len(sculpted) > 5 else sculpted

    # Covenants
    lock_up_dscr = 1.15
    default_dscr = 1.05

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "total_capex": round(total_capex),
        "debt_amount": round(debt_amount),
        "equity_amount": round(equity_amount),
        "gearing_pct": round(gearing * 100, 1),
        "interest_rate_pct": round(interest_rate * 100, 1),
        "debt_term_years": DEBT_TERM_YEARS,
        "target_dscr": target_dscr,
        "avg_dscr": round(avg_dscr, 2),
        "min_dscr": round(min_dscr, 2),
        "lock_up_dscr": lock_up_dscr,
        "default_dscr": default_dscr,
        "covenant_status": "PASS" if min_dscr >= default_dscr else "BREACH",
        "sculpted_profile_truncated": truncated,
    }


def equity_returns(capacity_mw: float = 50, technology: str = "wind",
                   gearing: float = TYPICAL_GEARING, ppa_price: float = DEFAULT_PPA_PRICE,
                   tax_rate: float = CORPORATION_TAX) -> dict:
    """Pre/post-tax equity IRR, cash-on-cash yield, dividend waterfall."""
    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    cf = CAPACITY_FACTORS.get(technology, 0.28)
    interest_rate = INTEREST_RATES["senior"]

    total_capex = capex_mw * capacity_mw
    debt_amount = total_capex * gearing
    equity_amount = total_capex * (1 - gearing)
    annual_opex = opex_mw * capacity_mw
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0

    # Equity cashflows: construction equity injection, then dividends
    equity_cashflows_pre_tax = [-equity_amount / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
    equity_cashflows_post_tax = [-equity_amount / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS

    waterfall = []
    total_dividends = 0
    outstanding_debt = debt_amount
    target_dscr = 1.3

    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            revenue = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            degraded_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            revenue = degraded_gen * ppa_price * (1 + INFLATION) ** y
        opex = annual_opex * (1 + INFLATION) ** y
        ebitda = revenue - opex

        # Debt service (sculpted)
        if outstanding_debt > 0 and y <= DEBT_TERM_YEARS:
            interest = outstanding_debt * interest_rate
            cfads = ebitda
            max_ds = cfads / target_dscr
            principal = min(max(0, max_ds - interest), outstanding_debt)
            ds = interest + principal
            outstanding_debt -= principal
        else:
            ds = 0
            interest = 0
            principal = 0

        pre_tax_cf = ebitda - ds
        tax = max(0, pre_tax_cf * tax_rate)
        dividend = max(0, pre_tax_cf - tax)
        retention = max(0, pre_tax_cf * 0.05)  # 5% cash reserve
        actual_dividend = max(0, dividend - retention)

        equity_cashflows_pre_tax.append(pre_tax_cf)
        equity_cashflows_post_tax.append(actual_dividend)
        total_dividends += actual_dividend

        waterfall.append({
            "year": y,
            "ebitda": round(ebitda),
            "debt_service": round(ds),
            "pre_tax_cf": round(pre_tax_cf),
            "tax": round(tax),
            "dividend": round(actual_dividend),
            "retention": round(retention),
        })

    equity_irr_pre = _irr_newton(equity_cashflows_pre_tax)
    equity_irr_post = _irr_newton(equity_cashflows_post_tax)
    equity_multiple = (equity_amount + total_dividends) / equity_amount if equity_amount > 0 else 0
    avg_coc = (total_dividends / PROJECT_LIFE) / equity_amount * 100 if equity_amount > 0 else 0

    # Truncated: first 5 + last
    truncated = waterfall[:5] + [waterfall[-1]] if len(waterfall) > 5 else waterfall

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "equity_amount": round(equity_amount),
        "gearing_pct": round(gearing * 100, 1),
        "equity_irr_pre_tax_pct": round(equity_irr_pre * 100, 2) if equity_irr_pre else None,
        "equity_irr_post_tax_pct": round(equity_irr_post * 100, 2) if equity_irr_post else None,
        "equity_multiple": round(equity_multiple, 2),
        "cash_on_cash_yield_pct": round(avg_coc, 2),
        "total_dividends": round(total_dividends),
        "distribution_schedule_truncated": truncated,
    }


# ── Subprocess bridge ─────────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "project_finance":
            result = project_finance(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                ppa_price=req.get("ppa_price", DEFAULT_PPA_PRICE),
                discount_rate=req.get("discount_rate", 0.08),
            )
            json.dump(result, sys.stdout)
        elif cmd == "debt_structure":
            result = debt_structure(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                target_dscr=req.get("target_dscr", 1.3),
                gearing=req.get("gearing", TYPICAL_GEARING),
                ppa_price=req.get("ppa_price", DEFAULT_PPA_PRICE),
            )
            json.dump(result, sys.stdout)
        elif cmd == "equity_returns":
            result = equity_returns(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                gearing=req.get("gearing", TYPICAL_GEARING),
                ppa_price=req.get("ppa_price", DEFAULT_PPA_PRICE),
                tax_rate=req.get("tax_rate", CORPORATION_TAX),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
