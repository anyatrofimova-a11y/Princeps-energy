"""
Scenario engine — multi-variable stress testing.

Standalone subprocess script (stdin JSON → stdout JSON).

Commands:
  {"command": "stress_test", "capacity_mw": 50, "technology": "wind"}
  {"command": "correlated_montecarlo", "capacity_mw": 50, "technology": "wind", "n_sims": 2000}
  {"command": "break_even", "capacity_mw": 50, "technology": "wind"}
"""
from __future__ import annotations

import json
import math
import random
import sys

from investment_appraisal import (
    CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, INTEREST_RATES,
    REVENUE_PER_MW, TYPICAL_GEARING, DEFAULT_PPA_PRICE, CORPORATION_TAX,
    DEGRADATION_RATE, INFLATION, PROJECT_LIFE, CONSTRUCTION_YEARS,
    DEBT_TERM_YEARS, _irr_newton, _npv,
)


# ── Pure-Python Cholesky decomposition for NxN ────────────────────────────────

def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    """Cholesky decomposition: A = L * L^T. Returns lower-triangular L."""
    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                val = matrix[i][i] - s
                L[i][j] = math.sqrt(max(0.0, val))
            else:
                L[i][j] = (matrix[i][j] - s) / L[j][j] if L[j][j] > 0 else 0.0
    return L


def _correlated_normals(L: list[list[float]], n_vars: int) -> list[float]:
    """Generate correlated normal variates using Cholesky factor L."""
    z = [random.gauss(0, 1) for _ in range(n_vars)]
    return [sum(L[i][j] * z[j] for j in range(i + 1)) for i in range(n_vars)]


# ── Quick equity IRR calculator (for scenario sweeps) ─────────────────────────

def _quick_equity_irr(capacity_mw: float, technology: str, cf_override: float | None = None,
                      price_override: float | None = None, capex_override: float | None = None,
                      opex_override: float | None = None, interest_override: float | None = None,
                      curtailment: float = 0.0, gearing: float = TYPICAL_GEARING) -> dict:
    """Stripped-down equity IRR + NPV + DSCR calculation."""
    capex_mw = capex_override if capex_override is not None else CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    opex_mw = opex_override if opex_override is not None else OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    cf = cf_override if cf_override is not None else CAPACITY_FACTORS.get(technology, 0.28)
    ppa = price_override if price_override is not None else DEFAULT_PPA_PRICE
    rate = interest_override if interest_override is not None else INTEREST_RATES["senior"]

    total_capex = capex_mw * capacity_mw
    annual_opex = opex_mw * capacity_mw
    is_bess = technology == "bess" and cf_override is None
    annual_gen = capacity_mw * cf * 8760 * (1 - curtailment) if not is_bess else 0
    bess_rev = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    debt_amount = total_capex * gearing
    equity_amount = total_capex * (1 - gearing)

    equity_cfs = [-equity_amount / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
    project_cfs = [-total_capex / CONSTRUCTION_YEARS] * CONSTRUCTION_YEARS
    min_dscr = 99.0
    outstanding = debt_amount

    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            revenue = bess_rev * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            gen = annual_gen * (1 - DEGRADATION_RATE) ** y
            revenue = gen * ppa * (1 + INFLATION) ** y
        opex_y = annual_opex * (1 + INFLATION) ** y
        ebitda = revenue - opex_y

        if outstanding > 0 and y <= DEBT_TERM_YEARS:
            interest = outstanding * rate
            cfads = ebitda
            max_ds = cfads / 1.3
            principal = min(max(0, max_ds - interest), outstanding)
            ds = interest + principal
            outstanding -= principal
            dscr = cfads / ds if ds > 0 else 99.0
            min_dscr = min(min_dscr, dscr)
        else:
            ds = 0

        pre_tax = ebitda - ds
        tax = max(0, pre_tax * CORPORATION_TAX)
        dividend = max(0, pre_tax - tax)
        equity_cfs.append(dividend)
        project_cfs.append(ebitda - max(0, ebitda * CORPORATION_TAX))

    irr = _irr_newton(equity_cfs)
    npv = _npv(0.08, project_cfs)

    return {
        "equity_irr": irr * 100 if irr else None,
        "npv": npv,
        "min_dscr": min_dscr if min_dscr < 99 else None,
    }


# ── Commands ───────────────────────────────────────────────────────────────────

def stress_test(capacity_mw: float = 50, technology: str = "wind",
                gearing: float = TYPICAL_GEARING) -> dict:
    """6-variable stress test at -20%/base/+20%, sorted by IRR swing (tornado)."""
    base_cf = CAPACITY_FACTORS.get(technology, 0.28)
    base_price = DEFAULT_PPA_PRICE
    base_capex = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    base_opex = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    base_rate = INTEREST_RATES["senior"]

    base = _quick_equity_irr(capacity_mw, technology, gearing=gearing)
    base_irr = base["equity_irr"] or 0

    variables = [
        ("capacity_factor", "cf_override", base_cf),
        ("ppa_price", "price_override", base_price),
        ("capex", "capex_override", base_capex),
        ("opex", "opex_override", base_opex),
        ("interest_rate", "interest_override", base_rate),
        ("curtailment", "curtailment", 0.0),
    ]

    results = []
    for name, kwarg, base_val in variables:
        if name == "curtailment":
            low_val, high_val = 0.0, 0.20
        else:
            low_val = base_val * 0.80
            high_val = base_val * 1.20

        low_res = _quick_equity_irr(capacity_mw, technology, gearing=gearing, **{kwarg: low_val})
        high_res = _quick_equity_irr(capacity_mw, technology, gearing=gearing, **{kwarg: high_val})

        low_irr = low_res["equity_irr"] or 0
        high_irr = high_res["equity_irr"] or 0
        swing = abs(high_irr - low_irr)

        results.append({
            "variable": name,
            "base_value": round(base_val, 4),
            "low_value": round(low_val, 4),
            "high_value": round(high_val, 4),
            "low_irr": round(low_irr, 2),
            "base_irr": round(base_irr, 2),
            "high_irr": round(high_irr, 2),
            "swing": round(swing, 2),
        })

    results.sort(key=lambda x: x["swing"], reverse=True)

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "base_equity_irr": round(base_irr, 2),
        "tornado": results,
        "most_sensitive": results[0]["variable"] if results else None,
    }


def correlated_montecarlo(capacity_mw: float = 50, technology: str = "wind",
                          n_sims: int = 2000, gearing: float = TYPICAL_GEARING,
                          seed: int = 42) -> dict:
    """2000 simulations with Cholesky-decomposed correlated inputs."""
    random.seed(seed)

    base_cf = CAPACITY_FACTORS.get(technology, 0.28)
    base_price = DEFAULT_PPA_PRICE
    base_capex = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    base_opex = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])

    # Correlation matrix (CF, price, capex, opex)
    # CF-price: negative for wind (high wind → lower prices)
    corr = [
        [1.00, -0.30, 0.00, 0.10],
        [-0.30, 1.00, 0.15, 0.20],
        [0.00, 0.15, 1.00, 0.50],
        [0.10, 0.20, 0.50, 1.00],
    ]
    L = _cholesky(corr)

    # Standard deviations (as fraction of base)
    sds = [0.08, 0.15, 0.10, 0.08]  # CF 8%, price 15%, capex 10%, opex 8%

    irrs = []
    npvs = []
    dscrs = []

    for _ in range(n_sims):
        z = _correlated_normals(L, 4)
        cf_sim = base_cf * (1 + sds[0] * z[0])
        price_sim = base_price * (1 + sds[1] * z[1])
        capex_sim = base_capex * (1 + sds[2] * z[2])
        opex_sim = base_opex * (1 + sds[3] * z[3])

        # Clamp to reasonable bounds
        cf_sim = max(0.05, min(0.60, cf_sim))
        price_sim = max(20, min(120, price_sim))
        capex_sim = max(capex_sim * 0.5, capex_sim)
        opex_sim = max(opex_sim * 0.5, opex_sim)

        res = _quick_equity_irr(
            capacity_mw, technology, gearing=gearing,
            cf_override=cf_sim, price_override=price_sim,
            capex_override=capex_sim, opex_override=opex_sim,
        )
        if res["equity_irr"] is not None:
            irrs.append(res["equity_irr"])
        npvs.append(res["npv"])
        if res["min_dscr"] is not None:
            dscrs.append(res["min_dscr"])

    irrs.sort()
    npvs.sort()
    dscrs.sort()

    def _percentile(arr, p):
        if not arr:
            return None
        k = (len(arr) - 1) * p / 100
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return arr[int(k)]
        return arr[f] * (c - k) + arr[c] * (k - f)

    # 20-bin histogram
    if irrs:
        mn, mx = irrs[0], irrs[-1]
        bin_width = (mx - mn) / 20 if mx > mn else 1
        histogram = []
        for b in range(20):
            lo = mn + b * bin_width
            hi = lo + bin_width
            count = sum(1 for v in irrs if lo <= v < hi) if b < 19 else sum(1 for v in irrs if lo <= v <= hi)
            histogram.append({"bin_low": round(lo, 1), "bin_high": round(hi, 1), "count": count})
    else:
        histogram = []

    prob_neg_npv = sum(1 for v in npvs if v < 0) / len(npvs) * 100 if npvs else 0

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "n_simulations": n_sims,
        "equity_irr_p10": round(_percentile(irrs, 10), 2) if irrs else None,
        "equity_irr_p50": round(_percentile(irrs, 50), 2) if irrs else None,
        "equity_irr_p90": round(_percentile(irrs, 90), 2) if irrs else None,
        "npv_p10": round(_percentile(npvs, 10)) if npvs else None,
        "npv_p50": round(_percentile(npvs, 50)) if npvs else None,
        "npv_p90": round(_percentile(npvs, 90)) if npvs else None,
        "dscr_p10": round(_percentile(dscrs, 10), 2) if dscrs else None,
        "dscr_p50": round(_percentile(dscrs, 50), 2) if dscrs else None,
        "prob_negative_npv_pct": round(prob_neg_npv, 1),
        "histogram": histogram,
    }


def break_even(capacity_mw: float = 50, technology: str = "wind",
               gearing: float = TYPICAL_GEARING) -> dict:
    """Bisection method to find NPV=0 value for each variable."""
    base_cf = CAPACITY_FACTORS.get(technology, 0.28)
    base_price = DEFAULT_PPA_PRICE
    base_capex = CAPEX_PER_MW.get(technology, CAPEX_PER_MW["wind"])
    base_opex = OPEX_PER_MW.get(technology, OPEX_PER_MW["wind"])
    base_rate = INTEREST_RATES["senior"]

    # For "positive" vars (CF, price), higher → higher NPV, so break-even is below base
    # For "negative" vars (capex, opex, rate), higher → lower NPV, so break-even is above base
    variables = [
        ("capacity_factor", "cf_override", base_cf, 0.01, 0.60, True),
        ("ppa_price", "price_override", base_price, 10.0, 150.0, True),
        ("capex", "capex_override", base_capex, base_capex * 0.3, base_capex * 3.0, False),
        ("opex", "opex_override", base_opex, base_opex * 0.3, base_opex * 3.0, False),
        ("interest_rate", "interest_override", base_rate, 0.01, 0.15, False),
    ]

    results = []
    for name, kwarg, base_val, lo, hi, positive in variables:
        # Bisection: find value where NPV = 0
        a, b = lo, hi
        try:
            for _ in range(50):
                mid = (a + b) / 2
                res = _quick_equity_irr(capacity_mw, technology, gearing=gearing, **{kwarg: mid})
                npv_mid = res["npv"]
                if positive:
                    # Higher value → higher NPV; NPV=0 crossing: go lower if npv>0
                    if npv_mid > 0:
                        b = mid
                    else:
                        a = mid
                else:
                    # Higher value → lower NPV; NPV=0 crossing: go higher if npv>0
                    if npv_mid > 0:
                        a = mid
                    else:
                        b = mid

            be_val = (a + b) / 2
            headroom = abs((be_val - base_val) / base_val * 100) if base_val != 0 else 0
        except (OverflowError, ValueError):
            be_val = base_val
            headroom = 0.0

        results.append({
            "variable": name,
            "base_value": round(base_val, 4),
            "break_even_value": round(be_val, 4),
            "headroom_pct": round(headroom, 1),
            "direction": "lower" if positive else "higher",
        })

    results.sort(key=lambda x: x["headroom_pct"])

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "break_even_analysis": results,
        "most_fragile": results[0]["variable"] if results else None,
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
        if cmd == "stress_test":
            result = stress_test(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                gearing=req.get("gearing", TYPICAL_GEARING),
            )
            json.dump(result, sys.stdout)
        elif cmd == "correlated_montecarlo":
            result = correlated_montecarlo(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                n_sims=req.get("n_sims", 2000),
                gearing=req.get("gearing", TYPICAL_GEARING),
                seed=req.get("seed", 42),
            )
            json.dump(result, sys.stdout)
        elif cmd == "break_even":
            result = break_even(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                gearing=req.get("gearing", TYPICAL_GEARING),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
