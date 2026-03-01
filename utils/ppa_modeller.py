#!/usr/bin/env python3
"""
PPA modeller — Princeps Phase 10
Power Purchase Agreement pricing engine: fixed, indexed, floor-cap,
baseload, shaped structures. Term analysis, cannibalisation, seasonal shaping.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "ppa_price", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "structure": "fixed", "term_years": 15}
  {"command": "term_analysis", "capacity_mw": 50, "technology": "solar",
   "region": "Midlands"}
  {"command": "structure_comparison", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
"""

import json
import math
import random
import sys

# ── UK PPA market parameters ─────────────────────────────────────────────

# Wholesale forward curve (£/MWh) — baseload by year ahead
FORWARD_CURVE = {
    0: 52,   # Spot
    1: 48,   # Y+1
    2: 45,   # Y+2
    3: 43,
    5: 42,
    10: 44,
    15: 48,
    20: 52,
    25: 55,
}

# Technology-specific capture price discounts (vs baseload)
CAPTURE_DISCOUNT = {
    "wind": {"base": 0.82, "cannibalisation_per_gw": 0.004},
    "solar": {"base": 0.78, "cannibalisation_per_gw": 0.006},
    "bess": {"base": 1.05, "cannibalisation_per_gw": 0.001},
}

# UK installed capacity (GW) — for cannibalisation
INSTALLED_CAPACITY_GW = {
    "wind_onshore": 15.2,
    "wind_offshore": 14.8,
    "solar": 18.5,
}

# PPA structure definitions
PPA_STRUCTURES = {
    "fixed": {
        "label": "Fixed Price",
        "description": "Flat £/MWh for full term — maximum revenue certainty",
        "discount_to_market": 0.08,  # 8% discount for certainty
        "bankability": 0.95,
        "counterparty_risk": "LOW",
    },
    "indexed": {
        "label": "CPI-Indexed",
        "description": "Base price escalated annually by CPI (typically 2-3%)",
        "discount_to_market": 0.05,
        "bankability": 0.90,
        "counterparty_risk": "LOW",
    },
    "floor_cap": {
        "label": "Floor & Cap",
        "description": "Minimum floor price with upside cap — shared risk/reward",
        "discount_to_market": 0.03,
        "bankability": 0.80,
        "counterparty_risk": "MEDIUM",
    },
    "baseload": {
        "label": "Baseload Shape",
        "description": "Flat MW profile — generator manages shape risk",
        "discount_to_market": 0.12,
        "bankability": 0.85,
        "counterparty_risk": "MEDIUM",
    },
    "shaped": {
        "label": "As-Generated",
        "description": "Pay for actual output — buyer takes volume risk",
        "discount_to_market": 0.02,
        "bankability": 0.70,
        "counterparty_risk": "LOW",
    },
    "synthetic": {
        "label": "Synthetic / Virtual",
        "description": "CfD-style financial swap — no physical delivery",
        "discount_to_market": 0.04,
        "bankability": 0.75,
        "counterparty_risk": "MEDIUM",
    },
}

# Seasonal shaping factors
SEASONAL_SHAPE = {
    "wind": {"winter": 1.25, "spring": 1.05, "summer": 0.70, "autumn": 1.00},
    "solar": {"winter": 0.45, "spring": 1.10, "summer": 1.50, "autumn": 0.95},
    "bess": {"winter": 1.10, "spring": 0.95, "summer": 0.90, "autumn": 1.05},
}

# Capacity factors by technology and season
CF_SEASONAL = {
    "wind": {"winter": 0.35, "spring": 0.28, "summer": 0.22, "autumn": 0.30},
    "solar": {"winter": 0.08, "spring": 0.12, "summer": 0.14, "autumn": 0.10},
    "bess": {"winter": 0.90, "spring": 0.90, "summer": 0.90, "autumn": 0.90},
}

# Buyer credit tiers
CREDIT_TIERS = {
    "investment_grade": {"spread_bps": 0, "default_prob": 0.003},
    "sub_investment": {"spread_bps": 50, "default_prob": 0.02},
    "unrated": {"spread_bps": 120, "default_prob": 0.05},
}


def _interpolate_forward(year: int) -> float:
    """Interpolate forward curve price."""
    years = sorted(FORWARD_CURVE.keys())
    if year <= years[0]:
        return FORWARD_CURVE[years[0]]
    if year >= years[-1]:
        return FORWARD_CURVE[years[-1]]
    for i in range(len(years) - 1):
        if years[i] <= year <= years[i + 1]:
            frac = (year - years[i]) / (years[i + 1] - years[i])
            return FORWARD_CURVE[years[i]] + frac * (FORWARD_CURVE[years[i + 1]] - FORWARD_CURVE[years[i]])
    return FORWARD_CURVE[years[-1]]


def ppa_price(capacity_mw: float = 50, technology: str = "wind",
              region: str = "Scotland", structure: str = "fixed",
              term_years: int = 15, credit_tier: str = "investment_grade") -> dict:
    """
    Calculate PPA price for a given structure and term.
    """
    struct = PPA_STRUCTURES.get(structure, PPA_STRUCTURES["fixed"])
    capture = CAPTURE_DISCOUNT.get(technology, CAPTURE_DISCOUNT["wind"])
    credit = CREDIT_TIERS.get(credit_tier, CREDIT_TIERS["investment_grade"])

    # Base forward price (weighted average over term)
    avg_forward = sum(_interpolate_forward(y) for y in range(term_years)) / term_years

    # Capture price adjustment
    total_capacity = sum(INSTALLED_CAPACITY_GW.values())
    cannibalisation = capture["cannibalisation_per_gw"] * total_capacity
    capture_ratio = max(0.55, capture["base"] - cannibalisation)
    capture_price = avg_forward * capture_ratio

    # Structure discount
    ppa_base = capture_price * (1 - struct["discount_to_market"])

    # Credit spread
    credit_spread = credit["spread_bps"] / 100  # bps → £/MWh
    ppa_final = ppa_base + credit_spread

    # Floor & cap specifics
    floor_price = ppa_final * 0.75 if structure == "floor_cap" else None
    cap_price = ppa_final * 1.40 if structure == "floor_cap" else None

    # CPI-indexed starting price (lower start, escalates)
    if structure == "indexed":
        cpi_rate = 0.025
        # NPV-equivalent: start lower, escalate
        annuity_factor = sum(1 / (1.08 ** y) for y in range(term_years))
        indexed_annuity = sum((1 + cpi_rate) ** y / (1.08 ** y) for y in range(term_years))
        start_price = ppa_final * annuity_factor / indexed_annuity
        end_price = start_price * (1 + cpi_rate) ** (term_years - 1)
    else:
        start_price = ppa_final
        end_price = ppa_final
        cpi_rate = 0

    # Annual generation & revenue
    cf = sum(CF_SEASONAL.get(technology, CF_SEASONAL["wind"]).values()) / 4
    annual_gen_mwh = capacity_mw * cf * 8760
    annual_revenue = annual_gen_mwh * ppa_final

    # Lifetime revenue (NPV at 8%)
    discount_rate = 0.08
    npv = 0
    yearly_revenues = []
    for y in range(term_years):
        if structure == "indexed":
            yr_price = start_price * (1 + cpi_rate) ** y
        else:
            yr_price = ppa_final
        yr_rev = annual_gen_mwh * yr_price
        yr_npv = yr_rev / (1 + discount_rate) ** y
        npv += yr_npv
        yearly_revenues.append({
            "year": y + 1,
            "price_gbp_mwh": round(yr_price, 2),
            "revenue_gbp": round(yr_rev),
            "npv_gbp": round(yr_npv),
        })

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "structure": structure,
            "structure_label": struct["label"],
            "term_years": term_years,
            "credit_tier": credit_tier,
        },
        "pricing": {
            "avg_forward_gbp_mwh": round(avg_forward, 2),
            "capture_ratio": round(capture_ratio, 3),
            "capture_price_gbp_mwh": round(capture_price, 2),
            "structure_discount_pct": round(struct["discount_to_market"] * 100, 1),
            "ppa_price_gbp_mwh": round(ppa_final, 2),
            "start_price_gbp_mwh": round(start_price, 2),
            "end_price_gbp_mwh": round(end_price, 2),
            "floor_price_gbp_mwh": round(floor_price, 2) if floor_price else None,
            "cap_price_gbp_mwh": round(cap_price, 2) if cap_price else None,
            "cpi_escalation_pct": round(cpi_rate * 100, 1) if structure == "indexed" else None,
        },
        "financials": {
            "annual_capacity_factor": round(cf, 3),
            "annual_generation_mwh": round(annual_gen_mwh),
            "annual_revenue_gbp": round(annual_revenue),
            "lifetime_npv_gbp": round(npv),
            "revenue_certainty": struct["bankability"],
            "counterparty_risk": struct["counterparty_risk"],
        },
        "yearly_cashflow": yearly_revenues[:5] + (
            [{"year": "...", "price_gbp_mwh": "...", "revenue_gbp": "...", "npv_gbp": "..."}] if term_years > 6 else []
        ) + yearly_revenues[-1:] if term_years > 6 else yearly_revenues,
    }


def term_analysis(capacity_mw: float = 50, technology: str = "solar",
                   region: str = "Midlands", structure: str = "fixed") -> dict:
    """
    Analyse PPA value across different term lengths (5-25 years).
    """
    terms = [5, 7, 10, 12, 15, 20, 25]
    results = []

    for t in terms:
        p = ppa_price(capacity_mw, technology, region, structure, t)
        results.append({
            "term_years": t,
            "ppa_price_gbp_mwh": p["pricing"]["ppa_price_gbp_mwh"],
            "annual_revenue_gbp": p["financials"]["annual_revenue_gbp"],
            "lifetime_npv_gbp": p["financials"]["lifetime_npv_gbp"],
            "revenue_certainty": p["financials"]["revenue_certainty"],
        })

    # Optimal term (highest NPV per year)
    for r in results:
        r["npv_per_year"] = round(r["lifetime_npv_gbp"] / r["term_years"])

    optimal = max(results, key=lambda r: r["npv_per_year"])

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "structure": structure,
        },
        "terms": results,
        "recommendation": {
            "optimal_term_years": optimal["term_years"],
            "optimal_npv_per_year": optimal["npv_per_year"],
            "rationale": f"{optimal['term_years']}-year term offers best NPV/year at "
                        f"£{optimal['npv_per_year']:,}/yr with price £{optimal['ppa_price_gbp_mwh']}/MWh",
        },
    }


def structure_comparison(capacity_mw: float = 50, technology: str = "wind",
                          region: str = "Scotland", term_years: int = 15) -> dict:
    """
    Compare all PPA structures side-by-side.
    """
    results = []
    for struct_id in PPA_STRUCTURES:
        p = ppa_price(capacity_mw, technology, region, struct_id, term_years)
        struct = PPA_STRUCTURES[struct_id]
        results.append({
            "structure": struct_id,
            "label": struct["label"],
            "description": struct["description"],
            "ppa_price_gbp_mwh": p["pricing"]["ppa_price_gbp_mwh"],
            "annual_revenue_gbp": p["financials"]["annual_revenue_gbp"],
            "lifetime_npv_gbp": p["financials"]["lifetime_npv_gbp"],
            "revenue_certainty": struct["bankability"],
            "counterparty_risk": struct["counterparty_risk"],
            "bankability_score": round(struct["bankability"] * 100),
        })

    results.sort(key=lambda r: -r["lifetime_npv_gbp"])

    # Seasonal shape
    shape = SEASONAL_SHAPE.get(technology, SEASONAL_SHAPE["wind"])
    seasonal = [{"season": s, "shape_factor": shape[s]} for s in ["winter", "spring", "summer", "autumn"]]

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "term_years": term_years,
        },
        "structures": results,
        "recommended": results[0]["structure"],
        "seasonal_shape": seasonal,
        "market_context": {
            "forward_curve_avg": round(
                sum(_interpolate_forward(y) for y in range(term_years)) / term_years, 2
            ),
            "capture_ratio": round(
                CAPTURE_DISCOUNT.get(technology, CAPTURE_DISCOUNT["wind"])["base"]
                - CAPTURE_DISCOUNT.get(technology, CAPTURE_DISCOUNT["wind"])["cannibalisation_per_gw"]
                * sum(INSTALLED_CAPACITY_GW.values()), 3
            ),
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
        if cmd == "ppa_price":
            result = ppa_price(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                structure=req.get("structure", "fixed"),
                term_years=req.get("term_years", 15),
                credit_tier=req.get("credit_tier", "investment_grade"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "term_analysis":
            result = term_analysis(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region", "Midlands"),
                structure=req.get("structure", "fixed"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "structure_comparison":
            result = structure_comparison(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                term_years=req.get("term_years", 15),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
