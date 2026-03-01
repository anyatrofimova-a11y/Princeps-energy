#!/usr/bin/env python3
"""
Route-to-market analyser — Princeps Phase 10
Compare market routes: merchant, CfD, corporate PPA, sleeved PPA,
synthetic PPA, private wire. Multi-criteria scoring.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "compare_routes", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "project_life_years": 25}
  {"command": "route_detail", "route": "cfd", "capacity_mw": 50,
   "technology": "wind"}
  {"command": "bankability_score", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "route": "corporate_ppa"}
"""

import json
import math
import random
import sys

# ── UK route-to-market options ───────────────────────────────────────────

ROUTES = {
    "merchant": {
        "label": "Merchant (Spot)",
        "description": "Sell on wholesale market at spot/day-ahead prices",
        "revenue_certainty": 0.20,
        "price_uplift_pct": 0,
        "bankability": 0.30,
        "complexity": "LOW",
        "min_capacity_mw": 0,
        "typical_term_years": 0,
        "counterparty_risk": "MARKET",
        "key_risks": ["Price volatility", "Capture price erosion", "Negative pricing exposure"],
        "key_benefits": ["Maximum upside exposure", "No commitment", "Full flexibility"],
    },
    "cfd": {
        "label": "CfD (Contract for Difference)",
        "description": "Government-backed strike price via LCCC allocation round",
        "revenue_certainty": 0.95,
        "price_uplift_pct": -5,
        "bankability": 0.98,
        "complexity": "HIGH",
        "min_capacity_mw": 5,
        "typical_term_years": 15,
        "counterparty_risk": "SOVEREIGN",
        "key_risks": ["AR allocation failure", "Strike price compression", "Curtailment not covered"],
        "key_benefits": ["Sovereign counterparty", "15-year price lock", "Index-linked"],
    },
    "corporate_ppa": {
        "label": "Corporate PPA (Physical)",
        "description": "Direct bilateral agreement with corporate buyer",
        "revenue_certainty": 0.80,
        "price_uplift_pct": 5,
        "bankability": 0.85,
        "complexity": "MEDIUM",
        "min_capacity_mw": 10,
        "typical_term_years": 10,
        "counterparty_risk": "CORPORATE",
        "key_risks": ["Counterparty credit", "Volume risk", "Shape risk"],
        "key_benefits": ["Additionality value", "ESG premium", "Long-term visibility"],
    },
    "sleeved_ppa": {
        "label": "Sleeved PPA",
        "description": "PPA via utility intermediary (balances supply/demand)",
        "revenue_certainty": 0.75,
        "price_uplift_pct": -2,
        "bankability": 0.80,
        "complexity": "MEDIUM",
        "min_capacity_mw": 5,
        "typical_term_years": 7,
        "counterparty_risk": "UTILITY",
        "key_risks": ["Sleeve fee (2-5 £/MWh)", "Utility credit exposure", "Shorter terms"],
        "key_benefits": ["Simplified for buyer", "Balancing handled", "REGOs included"],
    },
    "synthetic_ppa": {
        "label": "Synthetic / Virtual PPA",
        "description": "Financial swap — CfD-style without physical delivery",
        "revenue_certainty": 0.70,
        "price_uplift_pct": 3,
        "bankability": 0.70,
        "complexity": "HIGH",
        "min_capacity_mw": 25,
        "typical_term_years": 10,
        "counterparty_risk": "CORPORATE",
        "key_risks": ["Accounting complexity (IFRS)", "Basis risk", "Settlement risk"],
        "key_benefits": ["Location flexibility", "No physical delivery", "Clean accounting for buyer"],
    },
    "private_wire": {
        "label": "Private Wire",
        "description": "Direct connection to adjacent consumer — no grid charges",
        "revenue_certainty": 0.85,
        "price_uplift_pct": 15,
        "bankability": 0.75,
        "complexity": "HIGH",
        "min_capacity_mw": 1,
        "typical_term_years": 20,
        "counterparty_risk": "SINGLE_BUYER",
        "key_risks": ["Single buyer dependency", "Planning constraints", "Proximity requirement"],
        "key_benefits": ["No TNUoS/DUoS/BSUoS", "Premium pricing", "Embedded benefits captured"],
    },
}

# Reference pricing
WHOLESALE_BASE = 48  # £/MWh baseload average
CDF_STRIKE = {"wind": 52.29, "solar": 47.00}
CAPACITY_FACTORS = {"wind": 0.287, "solar": 0.11, "bess": 0.90}
CAPTURE_RATIOS = {"wind": 0.82, "solar": 0.78, "bess": 1.05}

# Embedded benefit savings for private wire (£/MWh)
GRID_CHARGE_SAVINGS = 18.5  # TNUoS + DUoS + BSUoS avoided


def _route_revenue(route_id: str, route: dict, capacity_mw: float,
                    technology: str, project_life_years: int) -> dict:
    """Calculate revenue for a specific route."""
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    capture = CAPTURE_RATIOS.get(technology, 0.80)
    annual_gen_mwh = capacity_mw * cf * 8760

    if route_id == "cfd":
        strike = CDF_STRIKE.get(technology, 50)
        annual_rev = annual_gen_mwh * strike
        price_mwh = strike
    elif route_id == "private_wire":
        base = WHOLESALE_BASE * capture
        price_mwh = base * (1 + route["price_uplift_pct"] / 100) + GRID_CHARGE_SAVINGS
        annual_rev = annual_gen_mwh * price_mwh
    else:
        base = WHOLESALE_BASE * capture
        price_mwh = base * (1 + route["price_uplift_pct"] / 100)
        annual_rev = annual_gen_mwh * price_mwh

    # NPV at 8%
    discount_rate = 0.08
    escalation = 0.02
    term = route["typical_term_years"] or project_life_years
    effective_term = min(term, project_life_years)

    npv = sum(
        annual_rev * (1 + escalation) ** y / (1 + discount_rate) ** y
        for y in range(effective_term)
    )

    # Merchant tail (if PPA term < project life)
    merchant_tail_npv = 0
    if effective_term < project_life_years:
        merchant_price = WHOLESALE_BASE * capture
        merchant_rev = annual_gen_mwh * merchant_price
        for y in range(effective_term, project_life_years):
            merchant_tail_npv += merchant_rev * (1 + escalation) ** y / (1 + discount_rate) ** y
        npv += merchant_tail_npv

    return {
        "effective_price_gbp_mwh": round(price_mwh, 2),
        "annual_revenue_gbp": round(annual_rev),
        "contract_term_years": effective_term,
        "contract_npv_gbp": round(npv - merchant_tail_npv),
        "merchant_tail_npv_gbp": round(merchant_tail_npv),
        "total_npv_gbp": round(npv),
        "annual_gen_mwh": round(annual_gen_mwh),
    }


def compare_routes(capacity_mw: float = 50, technology: str = "wind",
                    region: str = "Scotland",
                    project_life_years: int = 25) -> dict:
    """
    Compare all route-to-market options side-by-side.
    """
    results = []
    for route_id, route in ROUTES.items():
        if capacity_mw < route["min_capacity_mw"]:
            continue

        rev = _route_revenue(route_id, route, capacity_mw, technology, project_life_years)

        # Multi-criteria score
        max_npv = max(1, rev["total_npv_gbp"])  # Will normalise later
        results.append({
            "route": route_id,
            "label": route["label"],
            "description": route["description"],
            **rev,
            "revenue_certainty": route["revenue_certainty"],
            "bankability": route["bankability"],
            "complexity": route["complexity"],
            "counterparty_risk": route["counterparty_risk"],
            "key_risks": route["key_risks"],
            "key_benefits": route["key_benefits"],
        })

    # Normalise NPV scores
    max_npv = max(r["total_npv_gbp"] for r in results) if results else 1

    for r in results:
        npv_score = (r["total_npv_gbp"] / max_npv) * 100
        certainty_score = r["revenue_certainty"] * 100
        bankability_score = r["bankability"] * 100
        # Composite: balanced between NPV, certainty, bankability
        r["composite_score"] = round(
            npv_score * 0.35 +
            certainty_score * 0.30 +
            bankability_score * 0.35, 1
        )

    results.sort(key=lambda r: -r["composite_score"])

    # Verdict
    best = results[0]
    verdict = "GO" if best["composite_score"] >= 70 else "CAUTION" if best["composite_score"] >= 50 else "NO-GO"

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "project_life_years": project_life_years,
        },
        "routes": results,
        "recommendation": {
            "best_route": best["route"],
            "best_label": best["label"],
            "composite_score": best["composite_score"],
            "verdict": verdict,
            "rationale": (
                f"{best['label']} offers the strongest combination of revenue "
                f"(£{best['effective_price_gbp_mwh']}/MWh), "
                f"certainty ({best['revenue_certainty']:.0%}), and "
                f"bankability ({best['bankability']:.0%})"
            ),
        },
    }


def route_detail(route: str = "cfd", capacity_mw: float = 50,
                  technology: str = "wind", project_life_years: int = 25) -> dict:
    """
    Detailed analysis for a specific route.
    """
    route_data = ROUTES.get(route)
    if not route_data:
        return {"error": f"Unknown route: {route}"}

    rev = _route_revenue(route, route_data, capacity_mw, technology, project_life_years)

    # Generate yearly cashflow
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    annual_gen_mwh = capacity_mw * cf * 8760
    term = route_data["typical_term_years"] or project_life_years
    effective_term = min(term, project_life_years)
    escalation = 0.02
    discount_rate = 0.08

    yearly = []
    for y in range(project_life_years):
        if y < effective_term:
            yr_price = rev["effective_price_gbp_mwh"] * (1 + escalation) ** y
            phase = "CONTRACT"
        else:
            yr_price = WHOLESALE_BASE * CAPTURE_RATIOS.get(technology, 0.80) * (1 + escalation) ** y
            phase = "MERCHANT"

        yr_rev = annual_gen_mwh * yr_price
        yr_npv = yr_rev / (1 + discount_rate) ** y

        yearly.append({
            "year": y + 1,
            "phase": phase,
            "price_gbp_mwh": round(yr_price, 2),
            "revenue_gbp": round(yr_rev),
            "npv_gbp": round(yr_npv),
        })

    return {
        "route": route,
        "label": route_data["label"],
        "description": route_data["description"],
        **rev,
        "revenue_certainty": route_data["revenue_certainty"],
        "bankability": route_data["bankability"],
        "complexity": route_data["complexity"],
        "counterparty_risk": route_data["counterparty_risk"],
        "key_risks": route_data["key_risks"],
        "key_benefits": route_data["key_benefits"],
        "yearly_cashflow": yearly[:5] + (
            [{"year": "...", "phase": "...", "price_gbp_mwh": "...", "revenue_gbp": "...", "npv_gbp": "..."}] if project_life_years > 6 else []
        ) + yearly[-1:] if project_life_years > 6 else yearly,
    }


def bankability_score(capacity_mw: float = 50, technology: str = "wind",
                       region: str = "Scotland", route: str = "corporate_ppa") -> dict:
    """
    Assess bankability / debt serviceability for a route.
    """
    route_data = ROUTES.get(route)
    if not route_data:
        return {"error": f"Unknown route: {route}"}

    rev = _route_revenue(route, route_data, capacity_mw, technology, 25)

    # Capex estimate (£/MW)
    capex_per_mw = {"wind": 1200000, "solar": 650000, "bess": 500000}.get(technology, 900000)
    total_capex = capacity_mw * capex_per_mw

    # Opex (£/MW/yr)
    opex_per_mw = {"wind": 35000, "solar": 12000, "bess": 18000}.get(technology, 25000)
    annual_opex = capacity_mw * opex_per_mw

    # DSCR (Debt Service Coverage Ratio)
    # Assume 70% gearing, 20yr debt term, 5% interest
    debt = total_capex * 0.70
    debt_service = debt * (0.05 * (1.05) ** 20) / ((1.05) ** 20 - 1)
    ebitda = rev["annual_revenue_gbp"] - annual_opex
    dscr = ebitda / max(debt_service, 1)

    # Scoring
    scores = {
        "revenue_certainty": round(route_data["revenue_certainty"] * 100),
        "counterparty_strength": {
            "SOVEREIGN": 98, "UTILITY": 80, "CORPORATE": 70,
            "SINGLE_BUYER": 55, "MARKET": 25,
        }.get(route_data["counterparty_risk"], 50),
        "contract_term": min(100, round(
            (route_data["typical_term_years"] or 0) / 20 * 100
        )),
        "dscr_score": min(100, round(dscr / 1.5 * 100)),
        "technology_maturity": {"wind": 95, "solar": 95, "bess": 80}.get(technology, 70),
    }
    composite = round(sum(scores.values()) / len(scores))

    # Investment grade threshold
    grade = (
        "INVESTMENT_GRADE" if composite >= 75
        else "SUB_INVESTMENT" if composite >= 55
        else "SPECULATIVE"
    )

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "route": route,
        },
        "financial_metrics": {
            "total_capex_gbp": round(total_capex),
            "annual_opex_gbp": round(annual_opex),
            "annual_revenue_gbp": rev["annual_revenue_gbp"],
            "ebitda_gbp": round(ebitda),
            "debt_gbp": round(debt),
            "annual_debt_service_gbp": round(debt_service),
            "dscr": round(dscr, 2),
            "equity_irr_pct": round(max(0, (ebitda - debt_service) / (total_capex * 0.30) * 100), 1),
        },
        "scores": scores,
        "composite_score": composite,
        "investment_grade": grade,
        "dscr_assessment": (
            "STRONG" if dscr >= 1.4
            else "ADEQUATE" if dscr >= 1.2
            else "MARGINAL" if dscr >= 1.0
            else "BELOW_THRESHOLD"
        ),
        "lender_view": {
            "min_dscr_lock_up": 1.10,
            "min_dscr_default": 1.05,
            "current_dscr": round(dscr, 2),
            "headroom_pct": round((dscr - 1.10) / 1.10 * 100, 1) if dscr > 1.10 else 0,
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
        if cmd == "compare_routes":
            result = compare_routes(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                project_life_years=req.get("project_life_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "route_detail":
            result = route_detail(
                route=req.get("route", "cfd"),
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                project_life_years=req.get("project_life_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "bankability_score":
            result = bankability_score(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                route=req.get("route", "corporate_ppa"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
