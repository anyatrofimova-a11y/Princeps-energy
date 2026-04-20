"""Monte Carlo finance engine — correlated input sampler over deterministic
project-finance model. Produces P10/P50/P90 bands for IRR, NPV, DSCR,
LCOE, plus a correlation-aware tornado chart.

Design: treat the deterministic project-finance call as a black-box; wrap
with numpy.random correlated draws over capex, opex, curtailment, price,
timeline slip. 1000 runs typically finishes in <500 ms.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("princeps.mc_finance")


# Correlation matrix (ρ) over the 6 drivers — conservative UK-2026 assumptions.
# Indices: 0=capex, 1=timeline_slip_mo, 2=opex_pct, 3=revenue_pct, 4=curtail_pct, 5=rate
_CORR = [
    # capex, slip, opex, rev,  curt, rate
    [1.00,  0.35, 0.20, -0.05, 0.10, 0.05],   # capex
    [0.35,  1.00, 0.25, -0.15, 0.20, 0.05],   # timeline slip
    [0.20,  0.25, 1.00, -0.05, 0.15, 0.00],   # opex
    [-0.05,-0.15,-0.05,  1.00,-0.40, -0.10],  # revenue (inverse curtailment)
    [0.10,  0.20, 0.15, -0.40, 1.00, 0.00],   # curtailment
    [0.05,  0.05, 0.00, -0.10, 0.00, 1.00],   # interest rate
]


def _cholesky(cov: list[list[float]]) -> list[list[float]]:
    """Manual Cholesky — avoids numpy so this runs in any venv."""
    n = len(cov)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                v = cov[i][i] - s
                L[i][j] = math.sqrt(max(1e-9, v))
            else:
                L[i][j] = (cov[i][j] - s) / L[j][j]
    return L


_L = _cholesky(_CORR)


def _correlated_draws(rng: random.Random, n: int = 6) -> list[float]:
    """Return n standard-normal draws with correlation given by _CORR."""
    z = [rng.gauss(0, 1) for _ in range(n)]
    y = [sum(_L[i][j] * z[j] for j in range(i + 1)) for i in range(n)]
    return y


@dataclass
class MCResult:
    samples: int
    irr_pct: dict[str, float]
    npv_gbp_m: dict[str, float]
    dscr: dict[str, float]
    lcoe_gbp_mwh: dict[str, float]
    tornado: list[dict[str, Any]]
    distributions: dict[str, list[float]]


def _percentile(arr: list[float], p: float) -> float:
    if not arr:
        return 0.0
    s = sorted(arr)
    i = max(0, min(len(s) - 1, int(len(s) * p)))
    return s[i]


def run_mc(
    base_case: dict,
    evaluator: Callable[[dict], dict],
    n_samples: int = 1000,
    sd: dict | None = None,
    seed: int = 42,
) -> MCResult:
    """Run Monte Carlo over the evaluator.

    Arguments:
      base_case  — dict with keys capex_gbp_m, opex_gbp_m_yr, revenue_gbp_m_yr,
                   curtail_pct, timeline_months, discount_rate_pct
      evaluator  — function taking a scenario dict → returns
                   { irr_pct, npv_gbp_m, dscr, lcoe_gbp_mwh }
      sd         — custom stdev per driver (as fraction); defaults to sensible.
    """
    rng = random.Random(seed)
    sd = sd or {
        "capex_gbp_m":    0.12,
        "timeline_slip":  3.0,    # months (absolute)
        "opex_pct":       0.15,
        "revenue_pct":    0.20,
        "curtail_pct":    0.06,   # absolute pp
        "rate_pp":        0.5,    # pp
    }

    irrs, npvs, dscrs, lcoes = [], [], [], []
    driver_log = {k: [] for k in ("capex_gbp_m", "timeline_months", "opex_gbp_m_yr",
                                  "revenue_gbp_m_yr", "curtail_pct", "discount_rate_pct")}

    for _ in range(n_samples):
        y = _correlated_draws(rng, 6)
        sc = dict(base_case)
        sc["capex_gbp_m"] = max(0.01, base_case["capex_gbp_m"] * (1 + sd["capex_gbp_m"] * y[0]))
        sc["timeline_months"] = max(0, base_case["timeline_months"] + sd["timeline_slip"] * y[1])
        sc["opex_gbp_m_yr"] = max(0, base_case["opex_gbp_m_yr"] * (1 + sd["opex_pct"] * y[2]))
        sc["revenue_gbp_m_yr"] = max(0, base_case["revenue_gbp_m_yr"] * (1 + sd["revenue_pct"] * y[3]))
        sc["curtail_pct"] = max(0, base_case.get("curtail_pct", 0) + sd["curtail_pct"] * y[4])
        sc["discount_rate_pct"] = max(0.01, base_case["discount_rate_pct"] + sd["rate_pp"] * y[5])

        try:
            out = evaluator(sc)
        except Exception as e:
            log.debug("evaluator threw: %s", e)
            continue
        irrs.append(out.get("irr_pct", 0))
        npvs.append(out.get("npv_gbp_m", 0))
        dscrs.append(out.get("dscr", 0))
        lcoes.append(out.get("lcoe_gbp_mwh", 0))
        for k in driver_log:
            driver_log[k].append(sc.get(k, 0))

    def bands(arr):
        return {
            "p10": round(_percentile(arr, 0.10), 2),
            "p50": round(_percentile(arr, 0.50), 2),
            "p90": round(_percentile(arr, 0.90), 2),
            "mean": round(sum(arr) / max(1, len(arr)), 2),
        }

    # Tornado: rank drivers by |correlation with IRR|
    def _corr(a, b):
        if len(a) != len(b) or not a:
            return 0.0
        ma, mb = sum(a)/len(a), sum(b)/len(b)
        num = sum((ai-ma)*(bi-mb) for ai, bi in zip(a, b))
        da = math.sqrt(sum((ai-ma)**2 for ai in a))
        db = math.sqrt(sum((bi-mb)**2 for bi in b))
        return num / (da * db) if da and db else 0.0

    tornado = []
    for k, vals in driver_log.items():
        c = _corr(vals, irrs)
        tornado.append({"driver": k, "corr_with_irr": round(c, 3),
                        "impact_pp": round(abs(c) * (bands(irrs)["p90"] - bands(irrs)["p10"]), 2)})
    tornado.sort(key=lambda x: abs(x["corr_with_irr"]), reverse=True)

    return MCResult(
        samples=len(irrs),
        irr_pct=bands(irrs),
        npv_gbp_m=bands(npvs),
        dscr=bands(dscrs),
        lcoe_gbp_mwh=bands(lcoes),
        tornado=tornado,
        distributions={
            "irr_pct":       [round(v, 2) for v in irrs],
            "npv_gbp_m":     [round(v, 2) for v in npvs],
            "dscr":          [round(v, 3) for v in dscrs],
            "lcoe_gbp_mwh":  [round(v, 2) for v in lcoes],
        },
    )


# ── Deterministic DSCR-aware evaluator — used when caller doesn't pass one ──

def default_evaluator(sc: dict) -> dict:
    """Quick deterministic IRR/NPV/DSCR from a scenario dict. Not as rich
    as /api/finance/project-finance but works standalone."""
    capex = sc["capex_gbp_m"] * 1_000_000
    rev_yr = sc["revenue_gbp_m_yr"] * 1_000_000 * (1 - sc.get("curtail_pct", 0) / 100)
    opex_yr = sc["opex_gbp_m_yr"] * 1_000_000
    r = sc["discount_rate_pct"] / 100
    n = int(sc.get("life_years", 15))
    net = rev_yr - opex_yr
    # NPV
    npv = -capex + sum(net / ((1 + r) ** t) for t in range(1, n + 1))
    # IRR (bisect)
    def _npv_at(rate):
        return -capex + sum(net / ((1 + rate) ** t) for t in range(1, n + 1))
    lo, hi = -0.2, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if _npv_at(mid) > 0:
            lo = mid
        else:
            hi = mid
    irr = (lo + hi) / 2
    # DSCR — 60% senior debt, 15y, interest at rate+2pp
    debt = capex * 0.60
    debt_rate = r + 0.02
    annuity = debt * debt_rate / (1 - (1 + debt_rate) ** -n) if debt_rate else 0
    dscr = net / annuity if annuity else 0
    # LCOE
    total_energy = rev_yr * n / 55  # rough £55/MWh implied price
    lcoe = (capex + opex_yr * n) / max(1, total_energy)
    return {
        "irr_pct": round(irr * 100, 2),
        "npv_gbp_m": round(npv / 1_000_000, 2),
        "dscr": round(dscr, 3),
        "lcoe_gbp_mwh": round(lcoe, 2),
    }
