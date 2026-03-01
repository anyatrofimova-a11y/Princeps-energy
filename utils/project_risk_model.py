#!/usr/bin/env python3
"""
Project risk model — Princeps Phase 10
Bankability and risk: Monte Carlo revenue-at-risk, risk register,
sensitivity tornado, DSCR analysis, investment-grade scoring.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "risk_assessment", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "route": "cfd"}
  {"command": "sensitivity_analysis", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
  {"command": "bankability_report", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "route": "corporate_ppa"}
"""

import json
import math
import random
import sys

# ── Risk register ────────────────────────────────────────────────────────

RISK_REGISTER = [
    # Construction risks
    {"id": "C1", "category": "construction", "name": "EPC cost overrun",
     "probability": 0.30, "impact_pct": 12, "mitigation": "Fixed-price EPC, contingency 10%"},
    {"id": "C2", "category": "construction", "name": "Grid connection delay",
     "probability": 0.40, "impact_pct": 8, "mitigation": "Early engagement with DNO/NESO"},
    {"id": "C3", "category": "construction", "name": "Planning condition failure",
     "probability": 0.15, "impact_pct": 25, "mitigation": "Pre-app consultation, environmental surveys"},
    {"id": "C4", "category": "construction", "name": "Supply chain disruption",
     "probability": 0.25, "impact_pct": 10, "mitigation": "Multi-source procurement, buffer stock"},
    # Market risks
    {"id": "M1", "category": "market", "name": "Wholesale price decline",
     "probability": 0.35, "impact_pct": 20, "mitigation": "CfD or long-term PPA hedge"},
    {"id": "M2", "category": "market", "name": "Capture price erosion",
     "probability": 0.45, "impact_pct": 15, "mitigation": "Storage co-location, flexible PPA"},
    {"id": "M3", "category": "market", "name": "CfD allocation failure",
     "probability": 0.30, "impact_pct": 30, "mitigation": "Corporate PPA fallback, multiple AR entries"},
    {"id": "M4", "category": "market", "name": "Negative pricing hours increase",
     "probability": 0.40, "impact_pct": 8, "mitigation": "Curtailment management, BESS co-location"},
    # Operational risks
    {"id": "O1", "category": "operational", "name": "Below-P50 resource yield",
     "probability": 0.50, "impact_pct": 12, "mitigation": "Bankable resource assessment, independent review"},
    {"id": "O2", "category": "operational", "name": "Equipment failure / availability loss",
     "probability": 0.20, "impact_pct": 10, "mitigation": "Tier 1 OEM, warranty, O&M contract"},
    {"id": "O3", "category": "operational", "name": "Curtailment higher than modelled",
     "probability": 0.35, "impact_pct": 15, "mitigation": "ANM/flexible connection analysis"},
    {"id": "O4", "category": "operational", "name": "Grid outage / force majeure",
     "probability": 0.10, "impact_pct": 20, "mitigation": "Business interruption insurance"},
    # Regulatory risks
    {"id": "R1", "category": "regulatory", "name": "Subsidy reform / CfD changes",
     "probability": 0.25, "impact_pct": 15, "mitigation": "Diversify revenue, monitor policy"},
    {"id": "R2", "category": "regulatory", "name": "Grid charging reform (TNUoS)",
     "probability": 0.35, "impact_pct": 8, "mitigation": "Sensitivity modelling, embedded benefit review"},
    {"id": "R3", "category": "regulatory", "name": "Planning policy change",
     "probability": 0.15, "impact_pct": 12, "mitigation": "Maintain planning compliance buffer"},
    {"id": "R4", "category": "regulatory", "name": "Environmental constraint (BNG)",
     "probability": 0.20, "impact_pct": 10, "mitigation": "Early BNG assessment, offset credits"},
    # Financial risks
    {"id": "F1", "category": "financial", "name": "Interest rate increase",
     "probability": 0.30, "impact_pct": 8, "mitigation": "Fixed-rate debt, interest rate swap"},
    {"id": "F2", "category": "financial", "name": "Counterparty default",
     "probability": 0.10, "impact_pct": 25, "mitigation": "Investment-grade PPA, credit support"},
]

# Reference financials
CAPEX_PER_MW = {"wind": 1200000, "solar": 650000, "bess": 500000}
OPEX_PER_MW = {"wind": 35000, "solar": 12000, "bess": 18000}
CAPACITY_FACTORS = {"wind": 0.287, "solar": 0.11, "bess": 0.90}
WHOLESALE_BASE = 48
CAPTURE_RATIOS = {"wind": 0.82, "solar": 0.78, "bess": 1.05}
CDF_STRIKE = {"wind": 52.29, "solar": 47.00}


def risk_assessment(capacity_mw: float = 50, technology: str = "wind",
                     region: str = "Scotland", route: str = "cfd",
                     simulations: int = 2000) -> dict:
    """
    Monte Carlo risk assessment — P10/P50/P90 revenue-at-risk.
    """
    random.seed(42)

    cf = CAPACITY_FACTORS.get(technology, 0.25)
    capture = CAPTURE_RATIOS.get(technology, 0.80)
    capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)
    opex = capacity_mw * OPEX_PER_MW.get(technology, 25000)

    # Base revenue
    if route == "cfd":
        base_price = CDF_STRIKE.get(technology, 50)
    else:
        base_price = WHOLESALE_BASE * capture

    base_gen_mwh = capacity_mw * cf * 8760
    base_revenue = base_gen_mwh * base_price

    # Monte Carlo simulation
    revenues = []
    npvs = []
    dscrs = []

    debt = capex * 0.70
    debt_service = debt * (0.05 * 1.05 ** 20) / (1.05 ** 20 - 1)

    for _ in range(simulations):
        # Vary key parameters
        cf_var = cf * (1 + random.gauss(0, 0.08))  # ±8% resource uncertainty
        price_var = base_price * (1 + random.gauss(0, 0.15 if route == "merchant" else 0.03))
        curtailment = random.uniform(0.02, 0.20)
        opex_var = opex * (1 + random.gauss(0, 0.05))

        gen = capacity_mw * max(0.05, cf_var) * 8760 * (1 - curtailment)
        rev = gen * max(5, price_var)
        ebitda = rev - opex_var

        # 25-year NPV
        npv = sum(ebitda * 1.02 ** y / 1.08 ** y for y in range(25))
        dscr = ebitda / max(debt_service, 1)

        revenues.append(rev)
        npvs.append(npv)
        dscrs.append(dscr)

    revenues.sort()
    npvs.sort()
    dscrs.sort()

    def percentile(arr, p):
        idx = int(len(arr) * p / 100)
        return arr[min(idx, len(arr) - 1)]

    # Risk-weighted expected value
    risk_weighted = sum(
        r["probability"] * r["impact_pct"] / 100 for r in RISK_REGISTER
    )
    expected_loss_pct = round(risk_weighted * 100, 1)

    # Categorise risks
    categories = {}
    for r in RISK_REGISTER:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"risks": [], "weighted_impact": 0}
        categories[cat]["risks"].append(r)
        categories[cat]["weighted_impact"] += r["probability"] * r["impact_pct"]

    cat_summary = [
        {"category": cat, "risk_count": len(d["risks"]),
         "weighted_impact_pct": round(d["weighted_impact"], 1),
         "severity": "HIGH" if d["weighted_impact"] > 8 else "MEDIUM" if d["weighted_impact"] > 4 else "LOW"}
        for cat, d in categories.items()
    ]
    cat_summary.sort(key=lambda c: -c["weighted_impact_pct"])

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "route": route,
            "simulations": simulations,
        },
        "revenue_at_risk": {
            "p10_annual_gbp": round(percentile(revenues, 10)),
            "p50_annual_gbp": round(percentile(revenues, 50)),
            "p90_annual_gbp": round(percentile(revenues, 90)),
            "mean_annual_gbp": round(sum(revenues) / len(revenues)),
            "std_dev_gbp": round((sum((r - sum(revenues) / len(revenues)) ** 2 for r in revenues) / len(revenues)) ** 0.5),
        },
        "npv_distribution": {
            "p10_gbp": round(percentile(npvs, 10)),
            "p50_gbp": round(percentile(npvs, 50)),
            "p90_gbp": round(percentile(npvs, 90)),
        },
        "dscr_distribution": {
            "p10": round(percentile(dscrs, 10), 2),
            "p50": round(percentile(dscrs, 50), 2),
            "p90": round(percentile(dscrs, 90), 2),
            "prob_below_1_1": round(sum(1 for d in dscrs if d < 1.1) / len(dscrs) * 100, 1),
        },
        "risk_summary": {
            "total_risks": len(RISK_REGISTER),
            "expected_annual_loss_pct": expected_loss_pct,
            "category_summary": cat_summary,
        },
        "top_risks": [
            {"id": r["id"], "name": r["name"], "category": r["category"],
             "probability": r["probability"], "impact_pct": r["impact_pct"],
             "weighted": round(r["probability"] * r["impact_pct"], 1),
             "mitigation": r["mitigation"]}
            for r in sorted(RISK_REGISTER, key=lambda r: -r["probability"] * r["impact_pct"])[:8]
        ],
    }


def sensitivity_analysis(capacity_mw: float = 50, technology: str = "wind",
                          region: str = "Scotland", route: str = "cfd") -> dict:
    """
    Tornado chart sensitivity — NPV impact of ±20% on each variable.
    """
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    capture = CAPTURE_RATIOS.get(technology, 0.80)
    capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)
    opex = capacity_mw * OPEX_PER_MW.get(technology, 25000)

    if route == "cfd":
        base_price = CDF_STRIKE.get(technology, 50)
    else:
        base_price = WHOLESALE_BASE * capture

    gen = capacity_mw * cf * 8760
    base_rev = gen * base_price
    base_ebitda = base_rev - opex
    base_npv = sum(base_ebitda * 1.02 ** y / 1.08 ** y for y in range(25))

    variables = [
        {"name": "Energy Price", "var": "price", "unit": "£/MWh"},
        {"name": "Capacity Factor", "var": "cf", "unit": "%"},
        {"name": "Capex", "var": "capex", "unit": "£M"},
        {"name": "Opex", "var": "opex", "unit": "£k/yr"},
        {"name": "Discount Rate", "var": "discount", "unit": "%"},
        {"name": "Curtailment", "var": "curtailment", "unit": "%"},
        {"name": "Inflation", "var": "inflation", "unit": "%"},
    ]

    results = []
    swing = 0.20  # ±20%

    for v in variables:
        for direction in [-1, 1]:
            mult = 1 + direction * swing

            if v["var"] == "price":
                adj_rev = gen * base_price * mult
                adj_npv = sum((adj_rev - opex) * 1.02 ** y / 1.08 ** y for y in range(25))
            elif v["var"] == "cf":
                adj_gen = capacity_mw * cf * mult * 8760
                adj_npv = sum((adj_gen * base_price - opex) * 1.02 ** y / 1.08 ** y for y in range(25))
            elif v["var"] == "capex":
                adj_capex = capex * mult
                adj_npv = base_npv - (adj_capex - capex)
            elif v["var"] == "opex":
                adj_opex = opex * mult
                adj_npv = sum((base_rev - adj_opex) * 1.02 ** y / 1.08 ** y for y in range(25))
            elif v["var"] == "discount":
                dr = 0.08 * mult
                adj_npv = sum(base_ebitda * 1.02 ** y / (1 + dr) ** y for y in range(25))
            elif v["var"] == "curtailment":
                curt = 0.10 * mult
                adj_gen = gen * (1 - curt)
                adj_npv = sum((adj_gen * base_price - opex) * 1.02 ** y / 1.08 ** y for y in range(25))
            elif v["var"] == "inflation":
                infl = 0.02 * mult
                adj_npv = sum(base_ebitda * (1 + infl) ** y / 1.08 ** y for y in range(25))
            else:
                adj_npv = base_npv

            if direction == -1:
                v["npv_low_gbp"] = round(adj_npv)
            else:
                v["npv_high_gbp"] = round(adj_npv)

        v["npv_range_gbp"] = abs(v.get("npv_high_gbp", 0) - v.get("npv_low_gbp", 0))
        v["npv_swing_pct"] = round(v["npv_range_gbp"] / max(abs(base_npv), 1) * 100, 1)

    # Sort by impact
    variables.sort(key=lambda v: -v.get("npv_range_gbp", 0))

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "route": route,
            "swing_pct": swing * 100,
        },
        "base_case": {
            "npv_gbp": round(base_npv),
            "annual_revenue_gbp": round(base_rev),
            "ebitda_gbp": round(base_ebitda),
        },
        "tornado": [
            {"variable": v["name"], "unit": v["unit"],
             "npv_low_gbp": v.get("npv_low_gbp", 0),
             "npv_high_gbp": v.get("npv_high_gbp", 0),
             "npv_range_gbp": v.get("npv_range_gbp", 0),
             "npv_swing_pct": v.get("npv_swing_pct", 0)}
            for v in variables
        ],
        "key_driver": variables[0]["name"] if variables else "N/A",
    }


def bankability_report(capacity_mw: float = 50, technology: str = "wind",
                        region: str = "Scotland", route: str = "corporate_ppa") -> dict:
    """
    Comprehensive bankability assessment for project finance.
    """
    risk = risk_assessment(capacity_mw, technology, region, route, 1500)
    sensitivity = sensitivity_analysis(capacity_mw, technology, region, route)

    # Investment criteria
    dscr_p50 = risk["dscr_distribution"]["p50"]
    npv_p50 = risk["npv_distribution"]["p50_gbp"]
    prob_dscr_breach = risk["dscr_distribution"]["prob_below_1_1"]

    criteria = {
        "dscr_minimum": {"target": 1.20, "actual": dscr_p50,
                         "pass": dscr_p50 >= 1.20},
        "dscr_lock_up": {"target": 1.10, "actual": risk["dscr_distribution"]["p10"],
                         "pass": risk["dscr_distribution"]["p10"] >= 1.10},
        "npv_positive": {"target": 0, "actual": risk["npv_distribution"]["p10_gbp"],
                         "pass": risk["npv_distribution"]["p10_gbp"] > 0},
        "revenue_certainty": {"target": 70, "actual": round(
            (1 - risk["risk_summary"]["expected_annual_loss_pct"] / 100) * 100),
                              "pass": risk["risk_summary"]["expected_annual_loss_pct"] < 30},
        "technology_proven": {"target": True, "actual": technology in ("wind", "solar"),
                              "pass": technology in ("wind", "solar")},
    }

    passed = sum(1 for c in criteria.values() if c["pass"])
    total = len(criteria)
    score = round(passed / total * 100)

    grade = (
        "A" if score >= 90 else
        "B+" if score >= 80 else
        "B" if score >= 70 else
        "B-" if score >= 60 else
        "C" if score >= 50 else
        "D"
    )

    verdict = "GO" if score >= 70 else "CAUTION" if score >= 50 else "NO-GO"

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "route": route,
        },
        "investment_criteria": criteria,
        "score": score,
        "grade": grade,
        "verdict": verdict,
        "risk_metrics": {
            "p10_annual_revenue": risk["revenue_at_risk"]["p10_annual_gbp"],
            "p50_annual_revenue": risk["revenue_at_risk"]["p50_annual_gbp"],
            "p90_annual_revenue": risk["revenue_at_risk"]["p90_annual_gbp"],
            "dscr_p50": dscr_p50,
            "prob_dscr_breach_pct": prob_dscr_breach,
        },
        "key_driver": sensitivity["key_driver"],
        "top_risks": risk["top_risks"][:5],
        "recommendation": (
            f"Project scores {grade} ({score}%) for bankability. "
            f"DSCR P50 of {dscr_p50:.2f}x {'exceeds' if dscr_p50 >= 1.2 else 'falls below'} "
            f"lender minimum. Key sensitivity is {sensitivity['key_driver']}. "
            f"{'Suitable for project finance.' if verdict == 'GO' else 'Needs risk mitigation before financing.'}"
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
        if cmd == "risk_assessment":
            result = risk_assessment(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                route=req.get("route", "cfd"),
                simulations=req.get("simulations", 2000),
            )
            json.dump(result, sys.stdout)
        elif cmd == "sensitivity_analysis":
            result = sensitivity_analysis(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                route=req.get("route", "cfd"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "bankability_report":
            result = bankability_report(
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
