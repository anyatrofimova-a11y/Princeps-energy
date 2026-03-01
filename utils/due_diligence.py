"""
Due diligence — automated DD scoring.

Standalone subprocess script (stdin JSON → stdout JSON).

Commands:
  {"command": "dd_checklist", "capacity_mw": 50, "technology": "wind", "region": "Scotland"}
  {"command": "technical_dd", "capacity_mw": 50, "technology": "wind"}
  {"command": "commercial_dd", "capacity_mw": 50, "technology": "wind", "ppa_price": 55}
"""
from __future__ import annotations

import json
import sys

# ── Scoring tables ─────────────────────────────────────────────────────────────

TECHNOLOGY_MATURITY = {
    "wind": 90, "solar": 95, "bess": 80, "offshore_wind": 85,
}

REGION_PLANNING_SUCCESS = {
    "Scotland": 75, "Wales": 70, "South West": 80, "South East": 72,
    "East": 78, "Midlands": 74, "North West": 68, "North East": 65,
    "Yorkshire": 72, "East Midlands": 76,
}

OEM_TIERS = {
    "tier_1": 95, "tier_2": 75, "tier_3": 55,
}

RESOURCE_QUALITY = {
    "bankable": 95, "indicative": 70, "desktop": 45,
}


def _rag(score: int) -> str:
    if score >= 75:
        return "GREEN"
    elif score >= 50:
        return "AMBER"
    return "RED"


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    elif score >= 75:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 40:
        return "C"
    return "D"


def _verdict(grade: str) -> str:
    if grade in ("A", "B+"):
        return "INVEST_READY"
    elif grade == "B":
        return "CONDITIONAL"
    return "NOT_READY"


# ── Commands ───────────────────────────────────────────────────────────────────

def dd_checklist(capacity_mw: float = 50, technology: str = "wind",
                 region: str = "Scotland", resource_quality: str = "indicative",
                 oem_tier: str = "tier_1", has_ppa: bool = True,
                 has_planning: bool = False, grid_offer: bool = False) -> dict:
    """4-pillar DD checklist with RAG scoring."""
    tech_maturity = TECHNOLOGY_MATURITY.get(technology, 70)
    planning_rate = REGION_PLANNING_SUCCESS.get(region, 70)

    # ── Technical (6 items) ──
    technical_items = [
        {
            "item": "Resource assessment quality",
            "score": RESOURCE_QUALITY.get(resource_quality, 70),
            "rag": _rag(RESOURCE_QUALITY.get(resource_quality, 70)),
            "note": f"{resource_quality.title()} — {'meets lender requirements' if resource_quality == 'bankable' else 'upgrade recommended'}",
        },
        {
            "item": "Technology track record",
            "score": tech_maturity,
            "rag": _rag(tech_maturity),
            "note": f"{technology.title()} — well-established" if tech_maturity >= 80 else f"{technology.title()} — emerging",
        },
        {
            "item": "Grid connection status",
            "score": 90 if grid_offer else 40,
            "rag": "GREEN" if grid_offer else "RED",
            "note": "Accepted grid offer" if grid_offer else "Grid offer pending",
        },
        {
            "item": "OEM warranty & tier",
            "score": OEM_TIERS.get(oem_tier, 55),
            "rag": _rag(OEM_TIERS.get(oem_tier, 55)),
            "note": f"{oem_tier.replace('_', ' ').title()} manufacturer",
        },
        {
            "item": "Construction risk",
            "score": min(90, 60 + capacity_mw * 0.3) if capacity_mw <= 100 else 65,
            "rag": _rag(min(90, 60 + capacity_mw * 0.3) if capacity_mw <= 100 else 65),
            "note": "Standard build" if capacity_mw <= 100 else "Large-scale — specialist EPC required",
        },
        {
            "item": "Site access & civil works",
            "score": 75,
            "rag": "GREEN",
            "note": "Standard UK site — no exceptional civil challenges assumed",
        },
    ]

    # ── Commercial (5 items) ──
    ppa_score = 85 if has_ppa else 35
    commercial_items = [
        {
            "item": "Revenue certainty",
            "score": ppa_score,
            "rag": _rag(ppa_score),
            "note": "PPA in place" if has_ppa else "Merchant exposure — PPA required",
        },
        {
            "item": "Market price outlook",
            "score": 70,
            "rag": "AMBER",
            "note": "UK wholesale prices volatile — CfD / PPA hedging recommended",
        },
        {
            "item": "Insurance coverage",
            "score": 80 if tech_maturity >= 80 else 60,
            "rag": _rag(80 if tech_maturity >= 80 else 60),
            "note": "Standard renewable energy package available",
        },
        {
            "item": "O&M contract quality",
            "score": OEM_TIERS.get(oem_tier, 55),
            "rag": _rag(OEM_TIERS.get(oem_tier, 55)),
            "note": f"{'Full-wrap OEM service' if oem_tier == 'tier_1' else 'ISP or partial wrap'}",
        },
        {
            "item": "Offtake counterparty credit",
            "score": 75,
            "rag": "GREEN",
            "note": "Investment-grade offtaker assumed",
        },
    ]

    # ── Legal (5 items) ──
    planning_score = 90 if has_planning else planning_rate
    legal_items = [
        {
            "item": "Planning consent",
            "score": planning_score,
            "rag": _rag(planning_score),
            "note": "Consent granted" if has_planning else f"Regional success rate: {planning_rate}%",
        },
        {
            "item": "Land rights & lease",
            "score": 75,
            "rag": "GREEN",
            "note": "25-year option/lease standard structure",
        },
        {
            "item": "Environmental permits",
            "score": 70 if technology != "offshore_wind" else 55,
            "rag": _rag(70 if technology != "offshore_wind" else 55),
            "note": "EIA screening/scoping complete" if technology != "offshore_wind" else "Marine licence pending",
        },
        {
            "item": "Grid connection agreement",
            "score": 85 if grid_offer else 40,
            "rag": "GREEN" if grid_offer else "RED",
            "note": "Bilateral connection agreement" if grid_offer else "Connection offer pending",
        },
        {
            "item": "Regulatory compliance",
            "score": 80,
            "rag": "GREEN",
            "note": "G99/G100 compliance pathway identified",
        },
    ]

    # ── Financial (5 items) ──
    scale_score = min(85, 50 + capacity_mw * 0.5) if capacity_mw >= 10 else 40
    financial_items = [
        {
            "item": "Project scale & bankability",
            "score": round(scale_score),
            "rag": _rag(scale_score),
            "note": f"{capacity_mw}MW — {'bankable scale' if capacity_mw >= 10 else 'sub-scale for project finance'}",
        },
        {
            "item": "DSCR headroom",
            "score": 75,
            "rag": "GREEN",
            "note": "Target DSCR 1.3x — standard for UK renewables",
        },
        {
            "item": "Tax structure",
            "score": 80,
            "rag": "GREEN",
            "note": "UK SPV — 25% corporation tax, capital allowances available",
        },
        {
            "item": "Sponsor track record",
            "score": 70,
            "rag": "AMBER",
            "note": "Developer experience to be confirmed",
        },
        {
            "item": "Model audit status",
            "score": 60,
            "rag": "AMBER",
            "note": "Independent model audit recommended before financial close",
        },
    ]

    pillars = {
        "technical": {"items": technical_items, "score": round(sum(i["score"] for i in technical_items) / len(technical_items))},
        "commercial": {"items": commercial_items, "score": round(sum(i["score"] for i in commercial_items) / len(commercial_items))},
        "legal": {"items": legal_items, "score": round(sum(i["score"] for i in legal_items) / len(legal_items))},
        "financial": {"items": financial_items, "score": round(sum(i["score"] for i in financial_items) / len(financial_items))},
    }
    for p in pillars.values():
        p["rag"] = _rag(p["score"])

    overall = round(sum(p["score"] for p in pillars.values()) / 4)
    grade = _grade(overall)

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "pillars": pillars,
        "overall_score": overall,
        "overall_rag": _rag(overall),
        "grade": grade,
        "verdict": _verdict(grade),
    }


def technical_dd(capacity_mw: float = 50, technology: str = "wind",
                 resource_quality: str = "indicative", oem_tier: str = "tier_1",
                 grid_offer: bool = False) -> dict:
    """Deep-dive technical due diligence."""
    resource_score = RESOURCE_QUALITY.get(resource_quality, 70)
    tech_maturity = TECHNOLOGY_MATURITY.get(technology, 70)
    oem_score = OEM_TIERS.get(oem_tier, 55)

    # Construction risk factors
    if capacity_mw <= 20:
        construction_risk = "LOW"
        construction_score = 90
    elif capacity_mw <= 100:
        construction_risk = "MEDIUM"
        construction_score = 75
    else:
        construction_risk = "HIGH"
        construction_score = 60

    # Performance ratio benchmarks
    perf_benchmarks = {
        "wind": {"availability": 97, "wake_loss_pct": 4, "electrical_loss_pct": 2},
        "solar": {"availability": 99, "soiling_loss_pct": 2, "electrical_loss_pct": 1.5},
        "bess": {"round_trip_efficiency_pct": 87, "availability": 97, "degradation_yr1_pct": 2},
        "offshore_wind": {"availability": 95, "wake_loss_pct": 6, "electrical_loss_pct": 3},
    }

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "resource_assessment": {
            "quality": resource_quality,
            "score": resource_score,
            "bankable": resource_quality == "bankable",
            "recommendation": "Meets lender requirements" if resource_quality == "bankable" else "Commission bankable resource assessment (IEC 61400-12 / IEC 61724)",
        },
        "technology_risk": {
            "maturity_score": tech_maturity,
            "oem_tier": oem_tier,
            "oem_score": oem_score,
            "warranty_years": 10 if oem_tier == "tier_1" else 5,
        },
        "grid_connection": {
            "offer_accepted": grid_offer,
            "score": 90 if grid_offer else 40,
            "recommendation": "Proceed to energisation" if grid_offer else "Priority action — secure grid connection offer",
        },
        "construction": {
            "risk_level": construction_risk,
            "score": construction_score,
            "epc_strategy": "Turnkey" if capacity_mw <= 50 else "Multi-lot with owner's engineer",
        },
        "performance": perf_benchmarks.get(technology, perf_benchmarks["wind"]),
        "overall_technical_score": round((resource_score + tech_maturity + oem_score + construction_score) / 4),
    }


def commercial_dd(capacity_mw: float = 50, technology: str = "wind",
                  ppa_price: float = 55, has_ppa: bool = True,
                  region: str = "Scotland") -> dict:
    """Revenue certainty, market exposure, insurance, O&M quality."""
    # Revenue certainty
    if has_ppa:
        revenue_certainty = 85
        revenue_note = f"PPA at £{ppa_price}/MWh — fixed price hedges merchant risk"
    else:
        revenue_certainty = 40
        revenue_note = "Full merchant exposure — high revenue volatility"

    # Market exposure
    merchant_pct = 0 if has_ppa else 100
    cfd_eligible = technology in ("wind", "solar", "offshore_wind")

    # Insurance
    insurance_score = 80 if TECHNOLOGY_MATURITY.get(technology, 70) >= 80 else 60
    insurance_covers = [
        "All-risks construction (CAR/EAR)",
        "Operational all-risks",
        "Business interruption (12 months)",
        "Third-party liability",
        "Environmental liability",
    ]
    if technology in ("wind", "offshore_wind"):
        insurance_covers.append("Machinery breakdown (turbine-specific)")

    # O&M benchmarks
    om_benchmarks = {
        "wind": {"annual_per_mw": 42000, "availability_target": 97, "response_time_hrs": 4},
        "solar": {"annual_per_mw": 18000, "availability_target": 99, "response_time_hrs": 24},
        "bess": {"annual_per_mw": 15000, "availability_target": 97, "response_time_hrs": 2},
        "offshore_wind": {"annual_per_mw": 85000, "availability_target": 95, "response_time_hrs": 48},
    }

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "revenue": {
            "certainty_score": revenue_certainty,
            "note": revenue_note,
            "merchant_exposure_pct": merchant_pct,
            "cfd_eligible": cfd_eligible,
            "ppa_price": ppa_price if has_ppa else None,
        },
        "market_outlook": {
            "score": 70,
            "uk_baseload_forecast": "£55-75/MWh (2025-2030 range)",
            "capture_price_discount": f"{15 if technology == 'solar' else 8}%",
            "cannibalisation_risk": "HIGH" if technology == "solar" else "MEDIUM",
        },
        "insurance": {
            "score": insurance_score,
            "covers": insurance_covers,
            "estimated_premium_pct_capex": 0.35 if technology != "offshore_wind" else 0.55,
        },
        "om_contract": om_benchmarks.get(technology, om_benchmarks["wind"]),
        "overall_commercial_score": round((revenue_certainty + 70 + insurance_score) / 3),
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
        if cmd == "dd_checklist":
            result = dd_checklist(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                resource_quality=req.get("resource_quality", "indicative"),
                oem_tier=req.get("oem_tier", "tier_1"),
                has_ppa=req.get("has_ppa", True),
                has_planning=req.get("has_planning", False),
                grid_offer=req.get("grid_offer", False),
            )
            json.dump(result, sys.stdout)
        elif cmd == "technical_dd":
            result = technical_dd(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                resource_quality=req.get("resource_quality", "indicative"),
                oem_tier=req.get("oem_tier", "tier_1"),
                grid_offer=req.get("grid_offer", False),
            )
            json.dump(result, sys.stdout)
        elif cmd == "commercial_dd":
            result = commercial_dd(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                ppa_price=req.get("ppa_price", 55),
                has_ppa=req.get("has_ppa", True),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
