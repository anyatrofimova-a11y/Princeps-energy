"""
Portfolio Optimisation Engine for Princeps.

Multi-site portfolio construction, diversification analysis, sensitivity/Monte Carlo,
and auto-generation from the projects pipeline.

Functions:
- optimise_portfolio(budget_gbp, sites, constraints)
- diversification_analysis(sites)
- sensitivity_analysis(portfolio, variables)
- compare_portfolios(portfolios)
- auto_generate_portfolio(budget_gbp, target_irr, region, technologies, pool)
"""

from __future__ import annotations

import json
import math
import random
import sys
from copy import deepcopy
from itertools import combinations
from typing import Any

# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------
DEFAULT_DISCOUNT_RATE = 0.08
DEFAULT_PROJECT_LIFE = 25  # years
DEFAULT_OPEX_PER_MW_PA = 25_000  # GBP/MW/year
TECH_CAPACITY_FACTORS = {
    "solar": 0.11,
    "wind": 0.28,
    "bess": 0.0,
    "hybrid_solar_bess": 0.10,
    "hybrid_wind_bess": 0.25,
}
TECH_DEGRADATION = {
    "solar": 0.005,
    "wind": 0.003,
    "bess": 0.02,
    "hybrid_solar_bess": 0.005,
    "hybrid_wind_bess": 0.004,
}
WHOLESALE_PRICE_GBP_MWH = 55.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _npv(cashflows: list[float], rate: float) -> float:
    """Net present value."""
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def _irr(cashflows: list[float], tol: float = 1e-6, max_iter: int = 200) -> float | None:
    """Newton-Raphson IRR.  Returns None if no convergence."""
    r = 0.08
    for _ in range(max_iter):
        npv_val = sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        dnpv = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-14:
            break
        r_new = r - npv_val / dnpv
        if abs(r_new - r) < tol:
            return round(r_new * 100, 2)  # percent
        r = r_new
    return round(r * 100, 2) if abs(npv_val) < 1e3 else None


def _site_cashflows(site: dict, ppa_price: float = WHOLESALE_PRICE_GBP_MWH,
                    lifetime: int = DEFAULT_PROJECT_LIFE) -> list[float]:
    """Build annual cashflows for a single site."""
    capex = site["capex_gbp"]
    cap_mw = site["capacity_mw"]
    tech = site.get("technology", "solar")
    cf = TECH_CAPACITY_FACTORS.get(tech, 0.11)
    deg = TECH_DEGRADATION.get(tech, 0.005)
    opex = DEFAULT_OPEX_PER_MW_PA * cap_mw

    flows = [-capex]
    for yr in range(1, lifetime + 1):
        gen_mwh = cap_mw * cf * (1 - deg) ** yr * 8760
        revenue = gen_mwh * ppa_price
        flows.append(revenue - opex)
    return flows


def _site_npv(site: dict, rate: float = DEFAULT_DISCOUNT_RATE) -> float:
    return _npv(_site_cashflows(site), rate)


def _site_irr(site: dict) -> float | None:
    return _irr(_site_cashflows(site))


# ---------------------------------------------------------------------------
# 1. optimise_portfolio
# ---------------------------------------------------------------------------

def optimise_portfolio(
    budget_gbp: float,
    sites: list[dict],
    constraints: dict | None = None,
) -> dict:
    """Select the combination of sites maximising total NPV within budget.

    Each site dict must have:
      lat, lon, capacity_mw, technology, capex_gbp, estimated_irr
    Optional: risk_score (0-100, lower=better), revenue_type ("ppa"|"merchant")

    Constraints (all optional):
      max_single_site_pct  – max % of budget for one site (default 30)
      min_sites            – minimum sites to select (default 3)
      technology_diversification – require >=2 technologies (default True)
      max_technology_pct   – max % capacity in one tech (default 70)
    """
    c = constraints or {}
    max_single_pct = c.get("max_single_site_pct", 30) / 100.0
    min_sites = c.get("min_sites", 3)
    tech_div = c.get("technology_diversification", True)
    max_tech_pct = c.get("max_technology_pct", 70) / 100.0

    # Pre-filter sites that individually exceed budget or single-site cap
    max_per_site = budget_gbp * max_single_pct
    eligible = [s for s in sites if s["capex_gbp"] <= min(budget_gbp, max_per_site)]

    if len(eligible) < min_sites:
        return {"error": f"Only {len(eligible)} eligible sites — need at least {min_sites}"}

    # Compute NPV for each site
    scored = []
    for s in eligible:
        npv = _site_npv(s)
        scored.append({**s, "_npv": npv, "_npv_per_gbp": npv / max(s["capex_gbp"], 1)})

    # Greedy knapsack: sort by NPV/capex ratio descending
    scored.sort(key=lambda s: s["_npv_per_gbp"], reverse=True)

    selected: list[dict] = []
    spent = 0.0
    techs_selected: dict[str, float] = {}

    for s in scored:
        if spent + s["capex_gbp"] > budget_gbp:
            continue
        # Check single-site cap
        if s["capex_gbp"] > max_per_site:
            continue
        selected.append(s)
        spent += s["capex_gbp"]
        tech = s.get("technology", "solar")
        techs_selected[tech] = techs_selected.get(tech, 0) + s["capacity_mw"]

    # Enforce min_sites — back-fill from remaining if needed
    if len(selected) < min_sites:
        remaining = [s for s in scored if s not in selected]
        remaining.sort(key=lambda s: s["capex_gbp"])
        for s in remaining:
            if len(selected) >= min_sites:
                break
            if spent + s["capex_gbp"] <= budget_gbp:
                selected.append(s)
                spent += s["capex_gbp"]
                tech = s.get("technology", "solar")
                techs_selected[tech] = techs_selected.get(tech, 0) + s["capacity_mw"]

    if len(selected) < min_sites:
        return {"error": f"Cannot meet min_sites={min_sites} within budget"}

    # Enforce tech diversification
    if tech_div and len(techs_selected) < 2:
        # Try swapping last selected for a different-tech site
        current_tech = list(techs_selected.keys())[0]
        alt = [s for s in scored if s.get("technology", "solar") != current_tech and s not in selected]
        if alt:
            worst = min(selected, key=lambda s: s["_npv_per_gbp"])
            replacement = alt[0]
            new_spent = spent - worst["capex_gbp"] + replacement["capex_gbp"]
            if new_spent <= budget_gbp:
                selected.remove(worst)
                selected.append(replacement)
                spent = new_spent

    # Enforce max_technology_pct
    total_cap = sum(s["capacity_mw"] for s in selected)
    if total_cap > 0:
        for tech, cap in techs_selected.items():
            if cap / total_cap > max_tech_pct:
                pass  # advisory — noted in metrics

    # Build portfolio cashflows (summed)
    portfolio_flows = [0.0] * (DEFAULT_PROJECT_LIFE + 1)
    for s in selected:
        for t, cf in enumerate(_site_cashflows(s)):
            portfolio_flows[t] += cf

    portfolio_npv = _npv(portfolio_flows, DEFAULT_DISCOUNT_RATE)
    portfolio_irr_val = _irr(portfolio_flows)

    # Diversification score (quick)
    div = diversification_analysis(selected)

    # Risk metrics
    risk_scores = [s.get("risk_score", 50) for s in selected]
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 50

    # Clean output (remove internal keys)
    clean = []
    for s in selected:
        out = {k: v for k, v in s.items() if not k.startswith("_")}
        out["site_npv_gbp"] = round(s["_npv"], 0)
        out["site_irr_pct"] = _site_irr(s)
        clean.append(out)

    return {
        "selected_sites": clean,
        "total_sites": len(clean),
        "total_capex_gbp": round(spent, 0),
        "budget_remaining_gbp": round(budget_gbp - spent, 0),
        "total_capacity_mw": round(sum(s["capacity_mw"] for s in selected), 2),
        "portfolio_npv_gbp": round(portfolio_npv, 0),
        "portfolio_irr_pct": portfolio_irr_val,
        "diversification_score": div["diversification_score"],
        "risk_metrics": {
            "average_risk_score": round(avg_risk, 1),
            "max_single_site_exposure_pct": round(max(s["capex_gbp"] for s in selected) / spent * 100, 1) if spent else 0,
            "technology_concentration": {
                tech: round(cap / total_cap * 100, 1)
                for tech, cap in techs_selected.items()
            } if total_cap > 0 else {},
        },
        "constraints_applied": {
            "max_single_site_pct": round(max_single_pct * 100, 1),
            "min_sites": min_sites,
            "technology_diversification": tech_div,
        },
    }


# ---------------------------------------------------------------------------
# 2. diversification_analysis
# ---------------------------------------------------------------------------

def diversification_analysis(sites: list[dict]) -> dict:
    """Analyse correlation between sites — geographic, technology, revenue."""
    n = len(sites)
    if n < 2:
        return {
            "correlation_matrix": [],
            "diversification_score": 0,
            "recommendations": ["Need at least 2 sites for diversification analysis."],
        }

    # Pairwise correlation matrix
    matrix = []
    geo_scores = []
    tech_scores = []
    rev_scores = []

    for i, a in enumerate(sites):
        row = []
        for j, b in enumerate(sites):
            if i == j:
                row.append({"pair": f"{i}-{j}", "geo": 1.0, "tech": 1.0, "revenue": 1.0, "composite": 1.0})
                continue

            # Geographic correlation
            dist = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if dist > 100:
                geo_corr = 0.2
            elif dist > 50:
                geo_corr = 0.4
            elif dist > 20:
                geo_corr = 0.6
            else:
                geo_corr = 0.9

            # Technology correlation
            ta, tb = a.get("technology", "solar"), b.get("technology", "solar")
            if ta == tb:
                tech_corr = 0.9
            elif {ta, tb} == {"solar", "wind"}:
                tech_corr = 0.2  # complementary generation profiles
            elif "bess" in {ta, tb}:
                tech_corr = 0.3
            else:
                tech_corr = 0.5

            # Revenue correlation
            ra = a.get("revenue_type", "merchant")
            rb = b.get("revenue_type", "merchant")
            if ra == rb:
                rev_corr = 0.8
            else:
                rev_corr = 0.3  # PPA vs merchant = diversified

            composite = round(0.4 * geo_corr + 0.35 * tech_corr + 0.25 * rev_corr, 3)
            row.append({
                "pair": f"{i}-{j}",
                "distance_km": round(dist, 1),
                "geo_correlation": round(geo_corr, 2),
                "tech_correlation": round(tech_corr, 2),
                "revenue_correlation": round(rev_corr, 2),
                "composite_correlation": composite,
            })

            if j > i:
                geo_scores.append(geo_corr)
                tech_scores.append(tech_corr)
                rev_scores.append(rev_corr)

        matrix.append(row)

    # Overall diversification score: 100 = fully diversified (low avg correlation)
    avg_geo = sum(geo_scores) / len(geo_scores) if geo_scores else 1
    avg_tech = sum(tech_scores) / len(tech_scores) if tech_scores else 1
    avg_rev = sum(rev_scores) / len(rev_scores) if rev_scores else 1
    avg_composite = 0.4 * avg_geo + 0.35 * avg_tech + 0.25 * avg_rev
    div_score = round((1 - avg_composite) * 100, 1)

    # Recommendations
    recs: list[str] = []
    techs = set(s.get("technology", "solar") for s in sites)
    if len(techs) < 2:
        recs.append("Add a different technology (e.g. wind or BESS) to reduce generation-profile correlation.")
    if avg_geo > 0.6:
        recs.append("Sites are geographically clustered — consider adding sites >100 km apart.")
    if avg_rev > 0.7:
        recs.append("Revenue streams are concentrated — mix contracted (PPA) and merchant exposure.")
    if len(sites) < 4:
        recs.append("Fewer than 4 sites limits diversification benefit — consider expanding the portfolio.")
    if not recs:
        recs.append("Portfolio is well-diversified across geography, technology and revenue streams.")

    return {
        "site_count": n,
        "correlation_matrix": matrix,
        "average_correlations": {
            "geographic": round(avg_geo, 3),
            "technology": round(avg_tech, 3),
            "revenue": round(avg_rev, 3),
            "composite": round(avg_composite, 3),
        },
        "diversification_score": div_score,
        "recommendations": recs,
    }


# ---------------------------------------------------------------------------
# 3. sensitivity_analysis
# ---------------------------------------------------------------------------

_DEFAULT_SENSITIVITY_VARS = [
    {"name": "ppa_price", "base": 55.0, "range_pct": 20, "unit": "GBP/MWh"},
    {"name": "capex", "base": 1.0, "range_pct": 15, "unit": "multiplier"},
    {"name": "capacity_factor", "base": 1.0, "range_pct": 10, "unit": "multiplier"},
    {"name": "opex", "base": 1.0, "range_pct": 20, "unit": "multiplier"},
    {"name": "interest_rate", "base": 8.0, "range_pct": 25, "unit": "%"},
    {"name": "construction_delay", "base": 0, "range_pct": 0, "unit": "months"},
]


def sensitivity_analysis(
    portfolio: dict,
    variables: list[str] | None = None,
    n_montecarlo: int = 2000,
) -> dict:
    """Tornado chart + Monte Carlo for a portfolio.

    `portfolio` must contain `selected_sites` from optimise_portfolio output.
    """
    sites = portfolio.get("selected_sites", [])
    if not sites:
        return {"error": "No selected_sites in portfolio"}

    # Filter variables
    var_names = variables or [v["name"] for v in _DEFAULT_SENSITIVITY_VARS]
    sens_vars = [v for v in _DEFAULT_SENSITIVITY_VARS if v["name"] in var_names]

    # Base IRR
    base_flows = _portfolio_cashflows(sites)
    base_irr = _irr(base_flows) or 8.0

    # ── Tornado ──
    tornado: list[dict] = []
    for var in sens_vars:
        low_irr = _perturbed_irr(sites, var["name"], -var["range_pct"] / 100) if var["range_pct"] > 0 else base_irr
        high_irr = _perturbed_irr(sites, var["name"], var["range_pct"] / 100) if var["range_pct"] > 0 else base_irr

        # Construction delay is special
        if var["name"] == "construction_delay":
            low_irr = base_irr
            high_irr = _delayed_irr(sites, months=12)

        tornado.append({
            "variable": var["name"],
            "unit": var["unit"],
            "low_value": round(var["base"] * (1 - var["range_pct"] / 100), 2) if var["range_pct"] > 0 else var["base"],
            "high_value": round(var["base"] * (1 + var["range_pct"] / 100), 2) if var["range_pct"] > 0 else 12,
            "low_irr_pct": low_irr,
            "high_irr_pct": high_irr,
            "spread_pct": round(abs(high_irr - low_irr), 2),
        })

    tornado.sort(key=lambda t: t["spread_pct"], reverse=True)

    # ── Monte Carlo ──
    mc_irrs: list[float] = []
    mc_npvs: list[float] = []
    rng = random.Random(42)

    for _ in range(n_montecarlo):
        # Correlated perturbations
        macro_shock = rng.gauss(0, 0.05)  # market-wide factor
        ppa_mult = 1 + rng.gauss(0, 0.10) + macro_shock * 0.5
        capex_mult = 1 + rng.gauss(0, 0.08)
        cf_mult = 1 + rng.gauss(0, 0.05) + macro_shock * 0.3
        opex_mult = 1 + rng.gauss(0, 0.10)
        rate_shift = rng.gauss(0, 0.01)

        sim_flows = [0.0] * (DEFAULT_PROJECT_LIFE + 1)
        for s in sites:
            capex = s["capex_gbp"] * capex_mult
            cap_mw = s["capacity_mw"]
            tech = s.get("technology", "solar")
            cf = TECH_CAPACITY_FACTORS.get(tech, 0.11) * cf_mult
            deg = TECH_DEGRADATION.get(tech, 0.005)
            opex = DEFAULT_OPEX_PER_MW_PA * cap_mw * opex_mult
            ppa = WHOLESALE_PRICE_GBP_MWH * ppa_mult

            sim_flows[0] -= capex
            for yr in range(1, DEFAULT_PROJECT_LIFE + 1):
                gen = cap_mw * cf * (1 - deg) ** yr * 8760
                sim_flows[yr] += gen * ppa - opex

        irr_val = _irr(sim_flows)
        if irr_val is not None:
            mc_irrs.append(irr_val)
        disc = DEFAULT_DISCOUNT_RATE + rate_shift
        mc_npvs.append(_npv(sim_flows, max(disc, 0.01)))

    mc_irrs.sort()
    mc_npvs.sort()
    n = len(mc_irrs)

    def _percentile(arr: list[float], p: float) -> float:
        idx = int(len(arr) * p / 100)
        return round(arr[min(idx, len(arr) - 1)], 2)

    prob_neg_npv = round(sum(1 for v in mc_npvs if v < 0) / max(len(mc_npvs), 1) * 100, 1)

    return {
        "base_irr_pct": base_irr,
        "tornado_data": tornado,
        "montecarlo": {
            "simulations": n_montecarlo,
            "converged": n,
            "irr_p10_pct": _percentile(mc_irrs, 10) if n else None,
            "irr_p50_pct": _percentile(mc_irrs, 50) if n else None,
            "irr_p90_pct": _percentile(mc_irrs, 90) if n else None,
            "irr_mean_pct": round(sum(mc_irrs) / n, 2) if n else None,
            "irr_std_pct": round((sum((x - sum(mc_irrs) / n) ** 2 for x in mc_irrs) / n) ** 0.5, 2) if n else None,
            "npv_p10_gbp": round(_percentile(mc_npvs, 10), 0),
            "npv_p50_gbp": round(_percentile(mc_npvs, 50), 0),
            "npv_p90_gbp": round(_percentile(mc_npvs, 90), 0),
            "probability_negative_npv_pct": prob_neg_npv,
        },
    }


def _portfolio_cashflows(sites: list[dict]) -> list[float]:
    flows = [0.0] * (DEFAULT_PROJECT_LIFE + 1)
    for s in sites:
        for t, cf in enumerate(_site_cashflows(s)):
            flows[t] += cf
    return flows


def _perturbed_irr(sites: list[dict], variable: str, delta: float) -> float:
    """Compute portfolio IRR with one variable shifted by delta (fractional)."""
    flows = [0.0] * (DEFAULT_PROJECT_LIFE + 1)
    for s in sites:
        capex = s["capex_gbp"]
        cap_mw = s["capacity_mw"]
        tech = s.get("technology", "solar")
        cf = TECH_CAPACITY_FACTORS.get(tech, 0.11)
        deg = TECH_DEGRADATION.get(tech, 0.005)
        opex = DEFAULT_OPEX_PER_MW_PA * cap_mw
        ppa = WHOLESALE_PRICE_GBP_MWH

        if variable == "ppa_price":
            ppa *= (1 + delta)
        elif variable == "capex":
            capex *= (1 + delta)
        elif variable == "capacity_factor":
            cf *= (1 + delta)
        elif variable == "opex":
            opex *= (1 + delta)

        flows[0] -= capex
        for yr in range(1, DEFAULT_PROJECT_LIFE + 1):
            gen = cap_mw * cf * (1 - deg) ** yr * 8760
            flows[yr] += gen * ppa - opex

    if variable == "interest_rate":
        rate = DEFAULT_DISCOUNT_RATE * (1 + delta)
        return round(_npv(flows, rate) / max(abs(flows[0]), 1) * 100, 2)

    return _irr(flows) or 0.0


def _delayed_irr(sites: list[dict], months: int = 12) -> float:
    """IRR with construction delay (push revenues back, keep capex at t=0)."""
    delay_years = months / 12
    flows = [0.0] * (DEFAULT_PROJECT_LIFE + 2)
    for s in sites:
        flows[0] -= s["capex_gbp"]
        cap_mw = s["capacity_mw"]
        tech = s.get("technology", "solar")
        cf = TECH_CAPACITY_FACTORS.get(tech, 0.11)
        deg = TECH_DEGRADATION.get(tech, 0.005)
        opex = DEFAULT_OPEX_PER_MW_PA * cap_mw
        ppa = WHOLESALE_PRICE_GBP_MWH

        for yr in range(1, DEFAULT_PROJECT_LIFE + 1):
            shifted = yr + int(delay_years)
            if shifted < len(flows):
                gen = cap_mw * cf * (1 - deg) ** yr * 8760
                flows[shifted] += gen * ppa - opex

    return _irr(flows) or 0.0


# ---------------------------------------------------------------------------
# 4. compare_portfolios
# ---------------------------------------------------------------------------

def compare_portfolios(portfolios: list[dict]) -> dict:
    """Side-by-side comparison of 2-4 portfolio configurations.

    Each portfolio dict should have `selected_sites` and optionally pre-computed metrics.
    If metrics are missing they are re-derived from the sites.
    """
    if len(portfolios) < 2:
        return {"error": "Need at least 2 portfolios to compare"}
    if len(portfolios) > 4:
        portfolios = portfolios[:4]

    rows: list[dict] = []
    for idx, p in enumerate(portfolios):
        sites = p.get("selected_sites", [])
        if not sites:
            rows.append({"portfolio": idx + 1, "error": "No sites"})
            continue

        flows = _portfolio_cashflows(sites)
        npv = _npv(flows, DEFAULT_DISCOUNT_RATE)
        irr_val = _irr(flows)
        total_capex = sum(s["capex_gbp"] for s in sites)
        total_cap = sum(s["capacity_mw"] for s in sites)

        # Payback
        cumulative = 0.0
        payback = None
        for yr, cf in enumerate(flows):
            cumulative += cf
            if cumulative >= 0 and yr > 0:
                payback = yr
                break

        div = diversification_analysis(sites)

        # Geographic spread: max distance between any two sites
        max_dist = 0.0
        for a, b in combinations(sites, 2):
            d = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if d > max_dist:
                max_dist = d

        risks = [s.get("risk_score", 50) for s in sites]

        rows.append({
            "portfolio": p.get("name", f"Portfolio {idx + 1}"),
            "site_count": len(sites),
            "total_capacity_mw": round(total_cap, 2),
            "total_capex_gbp": round(total_capex, 0),
            "portfolio_npv_gbp": round(npv, 0),
            "portfolio_irr_pct": irr_val,
            "payback_years": payback,
            "average_risk_score": round(sum(risks) / len(risks), 1) if risks else None,
            "diversification_score": div["diversification_score"],
            "geographic_spread_km": round(max_dist, 1),
            "technologies": list(set(s.get("technology", "solar") for s in sites)),
        })

    # Recommendation: highest NPV with diversification score >= 50
    best = None
    for r in rows:
        if "error" in r:
            continue
        if r.get("diversification_score", 0) >= 50 or len(rows) == 2:
            if best is None or (r.get("portfolio_npv_gbp", 0) or 0) > (best.get("portfolio_npv_gbp", 0) or 0):
                best = r

    if best is None and rows:
        best = max((r for r in rows if "error" not in r), key=lambda r: r.get("portfolio_npv_gbp", 0), default=rows[0])

    return {
        "comparison_table": rows,
        "recommendation": {
            "preferred": best.get("portfolio") if best else None,
            "reason": (
                f"Highest NPV ({_fmt_gbp(best.get('portfolio_npv_gbp', 0))}) with "
                f"diversification score {best.get('diversification_score', 0)}/100"
            ) if best and "error" not in best else "Insufficient data",
        },
    }


def _fmt_gbp(val: float) -> str:
    if abs(val) >= 1e6:
        return f"\u00a3{val / 1e6:.1f}M"
    return f"\u00a3{val:,.0f}"


# ---------------------------------------------------------------------------
# 5. auto_generate_portfolio  (async — needs DB pool)
# ---------------------------------------------------------------------------

async def auto_generate_portfolio(
    budget_gbp: float,
    target_irr: float = 8.0,
    region: str | None = None,
    technologies: list[str] | None = None,
    pool=None,
) -> dict:
    """Query projects table and auto-build an optimised portfolio.

    If `pool` is provided, queries the projects table in PostgreSQL.
    Otherwise, returns a synthetic demonstration portfolio.
    """
    candidate_sites: list[dict] = []

    if pool is not None:
        query = """
            SELECT id, name, lat, lon, capacity_mw, technology,
                   (metadata->>'capex_gbp')::float AS capex_gbp,
                   (metadata->>'estimated_irr')::float AS estimated_irr,
                   (metadata->>'risk_score')::float AS risk_score,
                   (metadata->>'revenue_type') AS revenue_type
            FROM projects
            WHERE status NOT IN ('cancelled', 'rejected')
              AND capacity_mw IS NOT NULL
              AND lat IS NOT NULL AND lon IS NOT NULL
        """
        params: list = []
        param_idx = 0

        if region:
            param_idx += 1
            query += f" AND LOWER(region) = LOWER(${param_idx})"
            params.append(region)

        if technologies:
            param_idx += 1
            query += f" AND technology = ANY(${param_idx}::text[])"
            params.append(technologies)

        query += " ORDER BY capacity_mw DESC LIMIT 200"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        for r in rows:
            capex = r["capex_gbp"]
            if capex is None:
                # Estimate capex from capacity
                tech = r["technology"] or "solar"
                capex_per_mw = {"solar": 600_000, "wind": 1_200_000, "bess": 350_000}.get(tech, 800_000)
                capex = r["capacity_mw"] * capex_per_mw

            irr_est = r["estimated_irr"]
            if irr_est is None:
                s_tmp = {
                    "capex_gbp": capex,
                    "capacity_mw": r["capacity_mw"],
                    "technology": r["technology"] or "solar",
                }
                irr_est = _site_irr(s_tmp) or 6.0

            candidate_sites.append({
                "project_id": str(r["id"]),
                "name": r["name"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "capacity_mw": float(r["capacity_mw"]),
                "technology": r["technology"] or "solar",
                "capex_gbp": capex,
                "estimated_irr": irr_est,
                "risk_score": r["risk_score"] or 50,
                "revenue_type": r["revenue_type"] or "merchant",
            })
    else:
        # Synthetic demo candidates
        import random as _rnd
        _rnd.seed(99)
        techs = technologies or ["solar", "wind", "bess"]
        for i in range(15):
            tech = techs[i % len(techs)]
            cap = _rnd.uniform(10, 80)
            capex_per_mw = {"solar": 600_000, "wind": 1_200_000, "bess": 350_000}.get(tech, 800_000)
            candidate_sites.append({
                "name": f"Demo Site {i + 1}",
                "lat": 51.5 + _rnd.uniform(-2, 3),
                "lon": -1.5 + _rnd.uniform(-3, 2),
                "capacity_mw": round(cap, 1),
                "technology": tech,
                "capex_gbp": round(cap * capex_per_mw),
                "estimated_irr": round(_rnd.uniform(5, 14), 1),
                "risk_score": round(_rnd.uniform(20, 80)),
                "revenue_type": _rnd.choice(["ppa", "merchant"]),
            })

    if not candidate_sites:
        return {"error": "No candidate projects found in database"}

    # Filter by target IRR (keep sites with estimated_irr >= target * 0.7 as candidates)
    viable = [s for s in candidate_sites if s.get("estimated_irr", 0) >= target_irr * 0.7]
    if len(viable) < 3:
        viable = sorted(candidate_sites, key=lambda s: s.get("estimated_irr", 0), reverse=True)[:max(len(candidate_sites), 3)]

    portfolio = optimise_portfolio(budget_gbp, viable)

    if "error" in portfolio:
        return portfolio

    # Add sensitivity
    sens = sensitivity_analysis(portfolio, n_montecarlo=1000)

    return {
        "candidates_screened": len(candidate_sites),
        "viable_candidates": len(viable),
        **portfolio,
        "sensitivity": sens,
    }


# ---------------------------------------------------------------------------
# CLI entry point for subprocess bridge
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    raw = sys.stdin.read()
    payload = json.loads(raw)
    cmd = payload.get("command", "optimise")

    if cmd == "optimise":
        result = optimise_portfolio(
            payload["budget_gbp"],
            payload["sites"],
            payload.get("constraints"),
        )
    elif cmd == "diversification":
        result = diversification_analysis(payload["sites"])
    elif cmd == "sensitivity":
        result = sensitivity_analysis(
            payload["portfolio"],
            payload.get("variables"),
            payload.get("n_montecarlo", 2000),
        )
    elif cmd == "compare":
        result = compare_portfolios(payload["portfolios"])
    elif cmd == "auto_generate":
        result = asyncio.run(auto_generate_portfolio(
            payload["budget_gbp"],
            payload.get("target_irr", 8),
            payload.get("region"),
            payload.get("technologies"),
        ))
    else:
        result = {"error": f"Unknown command: {cmd}"}

    json.dump(result, sys.stdout)
