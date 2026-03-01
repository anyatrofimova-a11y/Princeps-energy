"""
Report generator — investment memo, risk matrix, action plan.

Standalone subprocess script (stdin JSON → stdout JSON).
Imports from other Phase 12 utilities directly.

Commands:
  {"command": "investment_memo", "capacity_mw": 50, "technology": "wind", "region": "Scotland"}
  {"command": "risk_matrix", "capacity_mw": 50, "technology": "wind"}
  {"command": "action_plan", "capacity_mw": 50, "technology": "wind"}
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

from investment_appraisal import (
    project_finance, debt_structure, equity_returns,
    DEFAULT_PPA_PRICE, TYPICAL_GEARING, CORPORATION_TAX,
)
from due_diligence import dd_checklist


# ── Risk definitions ──────────────────────────────────────────────────────────

RISK_REGISTER = [
    # (category, risk, likelihood 1-5, impact 1-5, mitigation)
    ("Technical", "Resource uncertainty exceeds P90 estimate", 2, 4,
     "Commission bankable resource assessment; apply uncertainty haircut"),
    ("Technical", "Grid connection delay >12 months", 3, 5,
     "Early engagement with DNO; alternative connection strategy"),
    ("Technical", "Equipment supply chain disruption", 2, 3,
     "Diversify OEM suppliers; early procurement"),
    ("Commercial", "PPA counterparty default", 1, 5,
     "Investment-grade offtaker requirement; credit insurance"),
    ("Commercial", "Wholesale price collapse below LCOE", 3, 4,
     "CfD or fixed-price PPA hedge; revenue floor"),
    ("Commercial", "Capture price cannibalisation", 3, 3,
     "Co-locate BESS for shape; diversify technology mix"),
    ("Regulatory", "Planning refusal or judicial review", 2, 5,
     "Pre-application engagement; community benefit package"),
    ("Regulatory", "Grid code change (e.g. G99 tightening)", 2, 3,
     "Design margin; monitor Ofgem consultations"),
    ("Regulatory", "Subsidy regime change (CfD reform)", 2, 4,
     "Secure current AR allocation; PPA fallback"),
    ("Financial", "Interest rate rise >200bps", 3, 3,
     "Interest rate swap at financial close; fixed-rate debt"),
    ("Financial", "Cost overrun >15% of capex budget", 2, 4,
     "Fixed-price EPC; contingency reserve 10%"),
    ("Financial", "FX exposure on imported equipment", 2, 2,
     "FX hedging programme; domestic supply preference"),
    ("ESG", "Community opposition escalation", 2, 4,
     "Early engagement; shared ownership; community fund"),
    ("ESG", "Environmental constraint (protected species)", 2, 4,
     "Pre-construction surveys; ecological mitigation plan"),
    ("ESG", "Decommissioning cost underestimate", 1, 3,
     "Conservative provision; escrow/bond at financial close"),
]


# ── Commands ───────────────────────────────────────────────────────────────────

def investment_memo(capacity_mw: float = 50, technology: str = "wind",
                    region: str = "Scotland", ppa_price: float = DEFAULT_PPA_PRICE,
                    gearing: float = TYPICAL_GEARING) -> dict:
    """Executive summary pulling together finance, DD, and verdict."""
    fin = project_finance(capacity_mw, technology, region, ppa_price)
    debt = debt_structure(capacity_mw, technology, gearing=gearing, ppa_price=ppa_price)
    eq = equity_returns(capacity_mw, technology, gearing=gearing, ppa_price=ppa_price)
    dd = dd_checklist(capacity_mw, technology, region)

    irr = eq.get("equity_irr_post_tax_pct")
    npv = fin.get("npv_8pct", 0)
    lcoe = fin.get("lcoe", 0)
    dscr = debt.get("min_dscr", 0)
    dd_score = dd.get("overall_score", 0)
    dd_grade = dd.get("grade", "C")

    # Verdict logic
    if irr and irr >= 8 and dscr >= 1.2 and dd_score >= 70:
        verdict = "INVEST"
        confidence = min(95, 60 + dd_score * 0.3 + (irr - 8) * 2)
    elif irr and irr >= 6 and dscr >= 1.1:
        verdict = "CONDITIONAL"
        confidence = min(80, 40 + dd_score * 0.3 + (irr - 6) * 2)
    else:
        verdict = "DECLINE"
        confidence = max(20, 60 - abs((irr or 0) - 8) * 5)

    confidence = round(min(95, max(15, confidence)), 1)

    # Investment highlights
    highlights = []
    if irr and irr >= 10:
        highlights.append(f"Strong equity returns at {irr:.1f}% post-tax IRR")
    if dscr >= 1.3:
        highlights.append(f"Comfortable debt service coverage at {dscr:.2f}x")
    if dd_grade in ("A", "B+"):
        highlights.append(f"Due diligence grade {dd_grade} — investment ready")
    if lcoe and lcoe < 50:
        highlights.append(f"Competitive LCOE at £{lcoe:.0f}/MWh")
    if fin.get("simple_payback_years") and fin["simple_payback_years"] <= 8:
        highlights.append(f"Quick payback in {fin['simple_payback_years']} years")
    if not highlights:
        highlights.append(f"Project returns at {irr:.1f}% equity IRR" if irr else "Returns analysis pending")

    # Key risks
    risks = []
    if dscr < 1.2:
        risks.append(f"Tight DSCR at {dscr:.2f}x — limited debt headroom")
    if irr and irr < 8:
        risks.append(f"Below-benchmark equity IRR at {irr:.1f}%")
    if dd_score < 60:
        risks.append(f"Due diligence score {dd_score}/100 — material gaps")
    if lcoe and lcoe > 60:
        risks.append(f"Elevated LCOE at £{lcoe:.0f}/MWh")
    if not risks:
        risks.append("No material red flags identified")

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "executive_summary": {
            "total_capex": fin.get("total_capex"),
            "equity_irr_post_tax_pct": irr,
            "project_irr_pct": fin.get("project_irr"),
            "npv_8pct": npv,
            "lcoe": lcoe,
            "min_dscr": dscr,
            "gearing_pct": round(gearing * 100, 1),
            "ppa_price": ppa_price,
            "simple_payback_years": fin.get("simple_payback_years"),
            "dd_score": dd_score,
            "dd_grade": dd_grade,
        },
        "investment_highlights": highlights,
        "key_risks": risks,
        "verdict": verdict,
        "confidence_pct": confidence,
    }


def risk_matrix(capacity_mw: float = 50, technology: str = "wind",
                region: str = "Scotland") -> dict:
    """5x5 likelihood-impact grid with ~15 risks."""
    # Adjust risks based on technology/scale
    risks = []
    for cat, desc, lik, imp, mit in RISK_REGISTER:
        adj_lik = lik
        adj_imp = imp

        # Technology-specific adjustments
        if technology == "solar" and "resource uncertainty" in desc.lower():
            adj_lik = max(1, lik - 1)  # Solar resource more predictable
        if technology == "offshore_wind" and "grid connection" in desc.lower():
            adj_imp = 5  # Offshore grid always critical
        if capacity_mw > 100 and "cost overrun" in desc.lower():
            adj_lik = min(5, lik + 1)

        risk_score = adj_lik * adj_imp
        if risk_score >= 15:
            priority = "CRITICAL"
        elif risk_score >= 9:
            priority = "HIGH"
        elif risk_score >= 4:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        risks.append({
            "category": cat,
            "description": desc,
            "likelihood": adj_lik,
            "impact": adj_imp,
            "risk_score": risk_score,
            "priority": priority,
            "mitigation": mit,
        })

    risks.sort(key=lambda r: r["risk_score"], reverse=True)

    # Build 5x5 grid
    grid = [[[] for _ in range(5)] for _ in range(5)]
    for r in risks:
        grid[r["likelihood"] - 1][r["impact"] - 1].append(r["description"][:40])

    categories = {}
    for r in risks:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "max_score": 0}
        categories[cat]["count"] += 1
        categories[cat]["max_score"] = max(categories[cat]["max_score"], r["risk_score"])

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "total_risks": len(risks),
        "critical_count": sum(1 for r in risks if r["priority"] == "CRITICAL"),
        "high_count": sum(1 for r in risks if r["priority"] == "HIGH"),
        "risks": risks,
        "grid_5x5": grid,
        "categories": categories,
    }


def action_plan(capacity_mw: float = 50, technology: str = "wind",
                region: str = "Scotland") -> dict:
    """Phased milestones to financial close."""
    today = datetime.now()

    phases = [
        {
            "phase": "Pre-development",
            "duration_months": 6,
            "start": today.strftime("%Y-%m-%d"),
            "end": (today + timedelta(days=180)).strftime("%Y-%m-%d"),
            "milestones": [
                {"task": "Site option agreement", "week": 2, "critical": True},
                {"task": "Desktop resource assessment", "week": 4, "critical": False},
                {"task": "Environmental screening", "week": 6, "critical": False},
                {"task": "Grid connection application", "week": 8, "critical": True},
                {"task": "Community engagement launch", "week": 10, "critical": False},
                {"task": "Bankable resource assessment commissioned", "week": 16, "critical": True},
            ],
        },
        {
            "phase": "Planning",
            "duration_months": 12,
            "start": (today + timedelta(days=180)).strftime("%Y-%m-%d"),
            "end": (today + timedelta(days=540)).strftime("%Y-%m-%d"),
            "milestones": [
                {"task": "EIA scoping opinion", "week": 2, "critical": True},
                {"task": "Planning application submission", "week": 16, "critical": True},
                {"task": "Grid connection offer received", "week": 20, "critical": True},
                {"task": "Planning determination", "week": 40, "critical": True},
                {"task": "Judicial review period expires", "week": 46, "critical": False},
            ],
        },
        {
            "phase": "Pre-construction",
            "duration_months": 9,
            "start": (today + timedelta(days=540)).strftime("%Y-%m-%d"),
            "end": (today + timedelta(days=810)).strftime("%Y-%m-%d"),
            "milestones": [
                {"task": "PPA execution", "week": 4, "critical": True},
                {"task": "EPC tender & award", "week": 12, "critical": True},
                {"task": "Debt term sheet", "week": 16, "critical": True},
                {"task": "Independent model audit", "week": 20, "critical": True},
                {"task": "Financial close", "week": 32, "critical": True},
            ],
        },
        {
            "phase": "Construction",
            "duration_months": 18 if technology in ("wind", "offshore_wind") else 12,
            "start": (today + timedelta(days=810)).strftime("%Y-%m-%d"),
            "end": (today + timedelta(days=810 + (540 if technology in ("wind", "offshore_wind") else 360))).strftime("%Y-%m-%d"),
            "milestones": [
                {"task": "Site mobilisation", "week": 2, "critical": True},
                {"task": "Civil works complete", "week": 16, "critical": False},
                {"task": "Equipment delivery", "week": 20, "critical": True},
                {"task": "Grid energisation", "week": -4, "critical": True},  # relative to end
                {"task": "Commissioning complete", "week": -2, "critical": True},
            ],
        },
        {
            "phase": "Operations",
            "duration_months": 300,  # 25 years
            "start": (today + timedelta(days=810 + (540 if technology in ("wind", "offshore_wind") else 360))).strftime("%Y-%m-%d"),
            "end": "Ongoing (25-year life)",
            "milestones": [
                {"task": "Commercial operations date (COD)", "week": 0, "critical": True},
                {"task": "Performance acceptance test", "week": 4, "critical": False},
                {"task": "First revenue distribution", "week": 26, "critical": False},
            ],
        },
    ]

    critical_path = [m["task"] for p in phases for m in p["milestones"] if m.get("critical")]

    next_actions = [
        {"action": "Secure site option agreement", "deadline": (today + timedelta(days=14)).strftime("%Y-%m-%d"), "priority": "HIGH"},
        {"action": "Submit grid connection application", "deadline": (today + timedelta(days=56)).strftime("%Y-%m-%d"), "priority": "HIGH"},
        {"action": "Commission resource assessment", "deadline": (today + timedelta(days=112)).strftime("%Y-%m-%d"), "priority": "MEDIUM"},
        {"action": "Appoint planning consultant", "deadline": (today + timedelta(days=90)).strftime("%Y-%m-%d"), "priority": "MEDIUM"},
        {"action": "Engage community stakeholders", "deadline": (today + timedelta(days=70)).strftime("%Y-%m-%d"), "priority": "MEDIUM"},
    ]

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "total_development_months": sum(p["duration_months"] for p in phases[:4]),
        "phases": phases,
        "critical_path": critical_path,
        "next_actions": next_actions,
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
        if cmd == "investment_memo":
            result = investment_memo(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                ppa_price=req.get("ppa_price", DEFAULT_PPA_PRICE),
                gearing=req.get("gearing", TYPICAL_GEARING),
            )
            json.dump(result, sys.stdout)
        elif cmd == "risk_matrix":
            result = risk_matrix(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "action_plan":
            result = action_plan(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
