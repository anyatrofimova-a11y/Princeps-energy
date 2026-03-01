#!/usr/bin/env python3
"""
Portfolio analytics — Princeps Phase 11
Multi-site portfolio analysis: diversification, correlation,
optimisation, risk metrics.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "portfolio_summary", "sites": [
    {"name": "Highland Wind", "capacity_mw": 50, "technology": "wind", "region": "Scotland"},
    {"name": "Midlands Solar", "capacity_mw": 30, "technology": "solar", "region": "Midlands"}
  ]}
  {"command": "diversification_analysis", "sites": [...]}
  {"command": "portfolio_optimisation", "budget_mw": 200, "technologies": ["wind", "solar", "bess"]}
"""

import json
import math
import random
import sys

# ── Market parameters ────────────────────────────────────────────────────

CAPACITY_FACTORS = {
    ("wind", "Scotland"): 0.32, ("wind", "North"): 0.29, ("wind", "Midlands"): 0.25, ("wind", "South"): 0.22,
    ("solar", "Scotland"): 0.09, ("solar", "North"): 0.10, ("solar", "Midlands"): 0.11, ("solar", "South"): 0.12,
    ("bess", "Scotland"): 0.90, ("bess", "North"): 0.90, ("bess", "Midlands"): 0.90, ("bess", "South"): 0.90,
}

REVENUE_PER_MWH = {
    "wind": 48, "solar": 42, "bess": 65,
}

CAPEX_PER_MW = {"wind": 1200000, "solar": 650000, "bess": 500000}

# Correlation matrix (technology-region pairs)
CORRELATIONS = {
    ("wind", "wind"): 0.85,
    ("wind", "solar"): -0.35,
    ("wind", "bess"): 0.10,
    ("solar", "solar"): 0.90,
    ("solar", "bess"): 0.05,
    ("bess", "bess"): 0.15,
}

REGION_CORRELATION = {
    ("Scotland", "Scotland"): 1.0, ("Scotland", "North"): 0.75, ("Scotland", "Midlands"): 0.45, ("Scotland", "South"): 0.30,
    ("North", "North"): 1.0, ("North", "Midlands"): 0.65, ("North", "South"): 0.40,
    ("Midlands", "Midlands"): 1.0, ("Midlands", "South"): 0.70,
    ("South", "South"): 1.0,
}

VOLATILITY = {"wind": 0.18, "solar": 0.15, "bess": 0.08}


def _get_cf(tech, region):
    return CAPACITY_FACTORS.get((tech, region), 0.25)


def _get_corr(t1, t2):
    return CORRELATIONS.get((t1, t2), CORRELATIONS.get((t2, t1), 0.5))


def _get_region_corr(r1, r2):
    return REGION_CORRELATION.get((r1, r2), REGION_CORRELATION.get((r2, r1), 0.5))


def portfolio_summary(sites: list) -> dict:
    """Aggregate portfolio metrics."""
    if not sites:
        return {"error": "No sites provided"}

    total_capacity = 0
    total_gen = 0
    total_revenue = 0
    total_capex = 0
    tech_mix = {}
    region_mix = {}

    site_details = []
    for s in sites:
        cap = s.get("capacity_mw", 50)
        tech = s.get("technology", "wind")
        region = s.get("region", "Midlands")
        cf = _get_cf(tech, region)
        gen = cap * cf * 8760
        rev = gen * REVENUE_PER_MWH.get(tech, 45)
        capex = cap * CAPEX_PER_MW.get(tech, 900000)

        total_capacity += cap
        total_gen += gen
        total_revenue += rev
        total_capex += capex

        tech_mix[tech] = tech_mix.get(tech, 0) + cap
        region_mix[region] = region_mix.get(region, 0) + cap

        site_details.append({
            "name": s.get("name", f"{tech}_{region}"),
            "capacity_mw": cap,
            "technology": tech,
            "region": region,
            "capacity_factor": round(cf, 3),
            "annual_gen_mwh": round(gen),
            "annual_revenue_gbp": round(rev),
            "capex_gbp": round(capex),
        })

    avg_cf = total_gen / max(total_capacity * 8760, 1)
    portfolio_irr = (total_revenue / max(total_capex, 1)) * 100

    return {
        "portfolio": {
            "total_capacity_mw": round(total_capacity, 1),
            "total_annual_gen_mwh": round(total_gen),
            "total_annual_revenue_gbp": round(total_revenue),
            "total_capex_gbp": round(total_capex),
            "weighted_capacity_factor": round(avg_cf, 3),
            "simple_irr_pct": round(portfolio_irr, 1),
            "site_count": len(sites),
        },
        "technology_mix": {k: {"mw": round(v, 1), "pct": round(v / max(total_capacity, 1) * 100, 1)}
                          for k, v in tech_mix.items()},
        "region_mix": {k: {"mw": round(v, 1), "pct": round(v / max(total_capacity, 1) * 100, 1)}
                       for k, v in region_mix.items()},
        "sites": site_details,
    }


def diversification_analysis(sites: list) -> dict:
    """Analyse portfolio diversification benefits."""
    if not sites or len(sites) < 2:
        return {"error": "Need at least 2 sites for diversification analysis"}

    n = len(sites)

    # Revenue volatility per site
    site_vols = []
    site_revs = []
    site_weights = []
    total_rev = 0

    for s in sites:
        tech = s.get("technology", "wind")
        region = s.get("region", "Midlands")
        cap = s.get("capacity_mw", 50)
        cf = _get_cf(tech, region)
        rev = cap * cf * 8760 * REVENUE_PER_MWH.get(tech, 45)
        vol = VOLATILITY.get(tech, 0.15)
        site_vols.append(vol)
        site_revs.append(rev)
        total_rev += rev

    for rev in site_revs:
        site_weights.append(rev / max(total_rev, 1))

    # Portfolio variance (Markowitz)
    portfolio_var = 0
    for i in range(n):
        for j in range(n):
            ti = sites[i].get("technology", "wind")
            tj = sites[j].get("technology", "wind")
            ri = sites[i].get("region", "Midlands")
            rj = sites[j].get("region", "Midlands")
            tech_corr = _get_corr(ti, tj)
            region_corr = _get_region_corr(ri, rj)
            combined_corr = tech_corr * region_corr
            portfolio_var += (site_weights[i] * site_weights[j] *
                            site_vols[i] * site_vols[j] * combined_corr)

    portfolio_vol = math.sqrt(max(0, portfolio_var))
    weighted_avg_vol = sum(w * v for w, v in zip(site_weights, site_vols))
    diversification_benefit = max(0, 1 - portfolio_vol / max(weighted_avg_vol, 0.001))

    # Herfindahl index (concentration)
    hhi_tech = sum((v / max(total_rev, 1)) ** 2 for v in site_revs)

    # Geographic spread
    regions = set(s.get("region", "Midlands") for s in sites)
    technologies = set(s.get("technology", "wind") for s in sites)

    # Correlation matrix
    corr_matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            ti = sites[i].get("technology", "wind")
            tj = sites[j].get("technology", "wind")
            ri = sites[i].get("region", "Midlands")
            rj = sites[j].get("region", "Midlands")
            c = _get_corr(ti, tj) * _get_region_corr(ri, rj)
            row.append(round(c, 3))
        corr_matrix.append(row)

    return {
        "diversification": {
            "portfolio_volatility_pct": round(portfolio_vol * 100, 1),
            "weighted_avg_volatility_pct": round(weighted_avg_vol * 100, 1),
            "diversification_benefit_pct": round(diversification_benefit * 100, 1),
            "herfindahl_index": round(hhi_tech, 3),
            "concentration": "LOW" if hhi_tech < 0.25 else "MEDIUM" if hhi_tech < 0.5 else "HIGH",
        },
        "spread": {
            "region_count": len(regions),
            "regions": sorted(regions),
            "technology_count": len(technologies),
            "technologies": sorted(technologies),
        },
        "correlation_matrix": {
            "labels": [s.get("name", f"Site {i+1}") for i, s in enumerate(sites)],
            "matrix": corr_matrix,
        },
        "recommendation": (
            f"Portfolio diversification benefit of {round(diversification_benefit * 100)}% — "
            f"{'well-diversified' if diversification_benefit > 0.3 else 'moderately diversified' if diversification_benefit > 0.15 else 'concentrated'}. "
            f"{'Consider adding solar to reduce wind correlation.' if len(technologies) == 1 and 'wind' in technologies else ''}"
            f"{'Consider geographic spread.' if len(regions) == 1 else ''}"
        ),
    }


def portfolio_optimisation(budget_mw: float = 200,
                            technologies: list = None,
                            regions: list = None,
                            target: str = "max_revenue") -> dict:
    """Optimise portfolio allocation across technologies and regions."""
    if technologies is None:
        technologies = ["wind", "solar", "bess"]
    if regions is None:
        regions = ["Scotland", "North", "Midlands", "South"]

    # Generate candidate allocations
    candidates = []
    for tech in technologies:
        for region in regions:
            cf = _get_cf(tech, region)
            rev_mwh = REVENUE_PER_MWH.get(tech, 45)
            annual_rev_per_mw = cf * 8760 * rev_mwh
            capex_per_mw = CAPEX_PER_MW.get(tech, 900000)
            vol = VOLATILITY.get(tech, 0.15)

            candidates.append({
                "technology": tech,
                "region": region,
                "capacity_factor": round(cf, 3),
                "annual_revenue_per_mw": round(annual_rev_per_mw),
                "capex_per_mw": capex_per_mw,
                "volatility": vol,
                "sharpe": round(annual_rev_per_mw / max(vol * annual_rev_per_mw, 1), 2),
            })

    # Sort by target metric
    if target == "max_revenue":
        candidates.sort(key=lambda c: -c["annual_revenue_per_mw"])
    elif target == "min_risk":
        candidates.sort(key=lambda c: c["volatility"])
    else:  # max_sharpe
        candidates.sort(key=lambda c: -c["sharpe"])

    # Greedy allocation (diversified)
    allocation = []
    remaining = budget_mw
    used = set()

    for c in candidates:
        key = (c["technology"], c["region"])
        if key in used:
            continue
        alloc_mw = min(remaining, budget_mw * 0.35)  # Max 35% per slot
        if alloc_mw < 5:
            break
        allocation.append({
            **c,
            "allocated_mw": round(alloc_mw, 1),
            "annual_revenue_gbp": round(alloc_mw * c["annual_revenue_per_mw"]),
            "capex_gbp": round(alloc_mw * c["capex_per_mw"]),
        })
        remaining -= alloc_mw
        used.add(key)

    total_rev = sum(a["annual_revenue_gbp"] for a in allocation)
    total_capex = sum(a["capex_gbp"] for a in allocation)
    total_alloc = sum(a["allocated_mw"] for a in allocation)

    return {
        "parameters": {
            "budget_mw": budget_mw,
            "technologies": technologies,
            "regions": regions,
            "target": target,
        },
        "allocation": allocation,
        "summary": {
            "allocated_mw": round(total_alloc, 1),
            "unallocated_mw": round(budget_mw - total_alloc, 1),
            "total_annual_revenue_gbp": round(total_rev),
            "total_capex_gbp": round(total_capex),
            "portfolio_yield_pct": round(total_rev / max(total_capex, 1) * 100, 1),
            "slots": len(allocation),
        },
    }


# ── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "portfolio_summary":
            result = portfolio_summary(req.get("sites", []))
            json.dump(result, sys.stdout)
        elif cmd == "diversification_analysis":
            result = diversification_analysis(req.get("sites", []))
            json.dump(result, sys.stdout)
        elif cmd == "portfolio_optimisation":
            result = portfolio_optimisation(
                budget_mw=req.get("budget_mw", 200),
                technologies=req.get("technologies"),
                regions=req.get("regions"),
                target=req.get("target", "max_revenue"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
