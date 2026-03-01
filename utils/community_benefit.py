#!/usr/bin/env python3
"""
Community benefit modeller — Princeps Phase 11
Community fund sizing, shared ownership, local employment,
social value scoring, stakeholder mapping.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "benefit_package", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "community_fund": true, "shared_ownership_pct": 20}
  {"command": "shared_ownership", "capacity_mw": 50, "technology": "wind",
   "community_stake_pct": 25}
  {"command": "social_value", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
"""

import json
import math
import sys

# ── UK community benefit benchmarks ──────────────────────────────────────

# Community fund rates (£/MW/year) — BEIS/DESNZ guidance
FUND_RATES = {
    "wind": {"standard": 5000, "enhanced": 8000, "exemplary": 12000},
    "solar": {"standard": 2500, "enhanced": 4000, "exemplary": 6000},
    "bess": {"standard": 1500, "enhanced": 3000, "exemplary": 5000},
}

# Employment estimates (FTE per MW)
EMPLOYMENT = {
    "wind": {"construction_fte_per_mw": 1.2, "construction_months": 18,
             "operation_fte_per_mw": 0.15, "local_content_pct": 45},
    "solar": {"construction_fte_per_mw": 0.8, "construction_months": 9,
              "operation_fte_per_mw": 0.05, "local_content_pct": 35},
    "bess": {"construction_fte_per_mw": 0.6, "construction_months": 12,
             "operation_fte_per_mw": 0.08, "local_content_pct": 30},
}

# Regional wage multiplier
REGIONAL_WAGES = {
    "Scotland": 28500, "North": 27000, "Midlands": 29000,
    "South": 32000, "London": 38000,
}

# Social value multipliers (TOMS-based)
SOCIAL_VALUE_RATES = {
    "local_employment_per_fte": 32000,   # Annual social value per FTE
    "training_per_apprentice": 18000,
    "community_fund_multiplier": 2.5,     # £1 fund = £2.50 social value
    "supply_chain_local_pct_value": 1.3,  # Multiplier on local spend
    "educational_visits_per_year": 15000,
}

CAPEX_PER_MW = {"wind": 1200000, "solar": 650000, "bess": 500000}
CAPACITY_FACTORS = {"wind": 0.287, "solar": 0.11, "bess": 0.90}

# Stakeholder categories
STAKEHOLDERS = [
    {"group": "Local residents", "influence": "HIGH", "interest": "HIGH", "strategy": "Manage closely"},
    {"group": "Parish/community council", "influence": "HIGH", "interest": "HIGH", "strategy": "Manage closely"},
    {"group": "Local planning authority", "influence": "HIGH", "interest": "MEDIUM", "strategy": "Keep satisfied"},
    {"group": "MP / elected representatives", "influence": "HIGH", "interest": "LOW", "strategy": "Keep satisfied"},
    {"group": "Local businesses", "influence": "MEDIUM", "interest": "HIGH", "strategy": "Keep informed"},
    {"group": "Environmental groups", "influence": "MEDIUM", "interest": "HIGH", "strategy": "Keep informed"},
    {"group": "Schools / colleges", "influence": "LOW", "interest": "MEDIUM", "strategy": "Monitor"},
    {"group": "Recreational users", "influence": "LOW", "interest": "MEDIUM", "strategy": "Monitor"},
]


def benefit_package(capacity_mw: float = 50, technology: str = "wind",
                     region: str = "Scotland", community_fund: bool = True,
                     shared_ownership_pct: float = 0,
                     project_life_years: int = 25) -> dict:
    """Generate comprehensive community benefit package."""
    fund_rates = FUND_RATES.get(technology, FUND_RATES["wind"])
    employ = EMPLOYMENT.get(technology, EMPLOYMENT["wind"])
    capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)
    avg_wage = REGIONAL_WAGES.get(region, 29000)

    # Community fund
    annual_fund = capacity_mw * fund_rates["standard"] if community_fund else 0
    enhanced_fund = capacity_mw * fund_rates["enhanced"]
    lifetime_fund = annual_fund * project_life_years

    # Employment
    construction_jobs = round(capacity_mw * employ["construction_fte_per_mw"])
    construction_duration = employ["construction_months"]
    operation_jobs = round(capacity_mw * employ["operation_fte_per_mw"], 1)
    local_jobs = round(construction_jobs * employ["local_content_pct"] / 100)

    # Local spend
    local_spend = capex * employ["local_content_pct"] / 100
    annual_ops_spend = capacity_mw * 15000  # Typical local O&M spend
    lifetime_local_spend = local_spend + annual_ops_spend * project_life_years

    # Business rates
    annual_rates = capacity_mw * {"wind": 8500, "solar": 4200, "bess": 3800}.get(technology, 5000)
    lifetime_rates = annual_rates * project_life_years

    # Shared ownership
    if shared_ownership_pct > 0:
        cf = CAPACITY_FACTORS.get(technology, 0.25)
        revenue_per_mw = cf * 8760 * 48  # Approx wholesale
        community_revenue = capacity_mw * shared_ownership_pct / 100 * revenue_per_mw
        community_investment = capex * shared_ownership_pct / 100
    else:
        community_revenue = 0
        community_investment = 0

    # Total community value
    total_annual = annual_fund + annual_rates + community_revenue + annual_ops_spend
    total_lifetime = lifetime_fund + lifetime_rates + community_revenue * project_life_years + lifetime_local_spend

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "project_life_years": project_life_years,
        },
        "community_fund": {
            "enabled": community_fund,
            "annual_gbp": round(annual_fund),
            "enhanced_rate_gbp": round(enhanced_fund),
            "lifetime_gbp": round(lifetime_fund),
            "rate_per_mw": fund_rates["standard"],
        },
        "employment": {
            "construction_fte": construction_jobs,
            "construction_months": construction_duration,
            "local_construction_fte": local_jobs,
            "permanent_operation_fte": operation_jobs,
            "construction_gva_gbp": round(construction_jobs * avg_wage * construction_duration / 12),
            "annual_operation_gva_gbp": round(operation_jobs * avg_wage),
        },
        "local_economy": {
            "construction_local_spend_gbp": round(local_spend),
            "annual_ops_spend_gbp": round(annual_ops_spend),
            "lifetime_local_spend_gbp": round(lifetime_local_spend),
            "annual_business_rates_gbp": round(annual_rates),
            "lifetime_rates_gbp": round(lifetime_rates),
            "local_content_pct": employ["local_content_pct"],
        },
        "shared_ownership": {
            "stake_pct": shared_ownership_pct,
            "community_investment_gbp": round(community_investment),
            "annual_community_revenue_gbp": round(community_revenue),
            "community_irr_pct": round(community_revenue / max(community_investment, 1) * 100, 1) if shared_ownership_pct > 0 else 0,
        },
        "total_value": {
            "annual_community_value_gbp": round(total_annual),
            "lifetime_community_value_gbp": round(total_lifetime),
            "value_per_mw_gbp": round(total_annual / max(capacity_mw, 1)),
        },
        "stakeholders": STAKEHOLDERS,
    }


def shared_ownership(capacity_mw: float = 50, technology: str = "wind",
                      community_stake_pct: float = 25,
                      project_life_years: int = 25) -> dict:
    """Model shared ownership financial structure."""
    capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    annual_gen_mwh = capacity_mw * cf * 8760
    annual_revenue = annual_gen_mwh * 48  # Wholesale approx
    annual_opex = capacity_mw * {"wind": 35000, "solar": 12000, "bess": 18000}.get(technology, 25000)
    annual_profit = annual_revenue - annual_opex

    community_capex = capex * community_stake_pct / 100
    community_profit = annual_profit * community_stake_pct / 100

    # Financing options for community
    options = [
        {
            "model": "direct_equity",
            "label": "Direct Community Equity",
            "community_investment_gbp": round(community_capex),
            "annual_return_gbp": round(community_profit),
            "simple_payback_years": round(community_capex / max(community_profit, 1), 1),
            "irr_pct": round(community_profit / max(community_capex, 1) * 100, 1),
        },
        {
            "model": "community_bond",
            "label": "Community Bond (5% coupon)",
            "community_investment_gbp": round(community_capex),
            "annual_coupon_gbp": round(community_capex * 0.05),
            "annual_surplus_gbp": round(community_profit - community_capex * 0.05),
            "bond_term_years": 15,
        },
        {
            "model": "cooperative",
            "label": "Community Energy Cooperative",
            "community_investment_gbp": round(community_capex),
            "share_price_gbp": 500,
            "shares_required": round(community_capex / 500),
            "members_target": round(community_capex / 5000),  # £5k avg investment
            "annual_dividend_gbp": round(community_profit),
            "dividend_per_share_pct": round(community_profit / max(community_capex, 1) * 100, 1),
        },
    ]

    # 25-year cashflow
    cashflow = []
    cumulative = -community_capex
    for y in range(project_life_years):
        yr_profit = community_profit * (1.02 ** y)  # 2% escalation
        cumulative += yr_profit
        cashflow.append({
            "year": y + 1,
            "annual_return_gbp": round(yr_profit),
            "cumulative_gbp": round(cumulative),
        })

    npv = sum(community_profit * 1.02 ** y / 1.08 ** y for y in range(project_life_years))

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "community_stake_pct": community_stake_pct,
        },
        "financials": {
            "total_capex_gbp": round(capex),
            "community_capex_gbp": round(community_capex),
            "annual_revenue_gbp": round(annual_revenue),
            "annual_profit_gbp": round(annual_profit),
            "community_profit_gbp": round(community_profit),
            "community_npv_gbp": round(npv),
        },
        "ownership_models": options,
        "cashflow_summary": cashflow[:5] + cashflow[-1:] if len(cashflow) > 6 else cashflow,
        "payback_year": next((c["year"] for c in cashflow if c["cumulative_gbp"] > 0), None),
    }


def social_value(capacity_mw: float = 50, technology: str = "wind",
                  region: str = "Scotland", community_fund: bool = True,
                  apprenticeships: int = 3) -> dict:
    """Calculate social value using TOMS methodology."""
    employ = EMPLOYMENT.get(technology, EMPLOYMENT["wind"])
    fund_rates = FUND_RATES.get(technology, FUND_RATES["wind"])
    capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)

    construction_jobs = round(capacity_mw * employ["construction_fte_per_mw"])
    operation_jobs = max(1, round(capacity_mw * employ["operation_fte_per_mw"]))
    local_jobs = round(construction_jobs * employ["local_content_pct"] / 100)

    # Social value components
    sv_employment = (construction_jobs * SOCIAL_VALUE_RATES["local_employment_per_fte"]
                     * employ["construction_months"] / 12)
    sv_operations = operation_jobs * SOCIAL_VALUE_RATES["local_employment_per_fte"] * 25
    sv_training = apprenticeships * SOCIAL_VALUE_RATES["training_per_apprentice"] * 3  # 3yr programme
    sv_fund = 0
    if community_fund:
        annual_fund = capacity_mw * fund_rates["standard"]
        sv_fund = annual_fund * 25 * SOCIAL_VALUE_RATES["community_fund_multiplier"]
    sv_supply = capex * employ["local_content_pct"] / 100 * (SOCIAL_VALUE_RATES["supply_chain_local_pct_value"] - 1)
    sv_education = SOCIAL_VALUE_RATES["educational_visits_per_year"] * 25

    total_sv = sv_employment + sv_operations + sv_training + sv_fund + sv_supply + sv_education

    # Per-MW benchmark
    sv_per_mw = total_sv / max(capacity_mw, 1)
    benchmark = {"wind": 120000, "solar": 65000, "bess": 50000}.get(technology, 80000)

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
        },
        "social_value_breakdown": {
            "construction_employment_gbp": round(sv_employment),
            "operation_employment_gbp": round(sv_operations),
            "training_apprenticeships_gbp": round(sv_training),
            "community_fund_gbp": round(sv_fund),
            "local_supply_chain_gbp": round(sv_supply),
            "educational_engagement_gbp": round(sv_education),
            "total_lifetime_gbp": round(total_sv),
        },
        "per_mw": {
            "social_value_per_mw_gbp": round(sv_per_mw),
            "benchmark_per_mw_gbp": benchmark,
            "vs_benchmark_pct": round(sv_per_mw / max(benchmark, 1) * 100, 1),
        },
        "employment_impact": {
            "construction_fte": construction_jobs,
            "local_construction_fte": local_jobs,
            "permanent_fte": operation_jobs,
            "apprenticeships": apprenticeships,
            "total_job_years": round(construction_jobs * employ["construction_months"] / 12 + operation_jobs * 25, 1),
        },
        "rating": (
            "EXEMPLARY" if sv_per_mw > benchmark * 1.5
            else "STRONG" if sv_per_mw > benchmark
            else "STANDARD" if sv_per_mw > benchmark * 0.6
            else "BELOW_BENCHMARK"
        ),
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
        if cmd == "benefit_package":
            result = benefit_package(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                community_fund=req.get("community_fund", True),
                shared_ownership_pct=req.get("shared_ownership_pct", 0),
            )
            json.dump(result, sys.stdout)
        elif cmd == "shared_ownership":
            result = shared_ownership(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                community_stake_pct=req.get("community_stake_pct", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "social_value":
            result = social_value(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                community_fund=req.get("community_fund", True),
                apprenticeships=req.get("apprenticeships", 3),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
