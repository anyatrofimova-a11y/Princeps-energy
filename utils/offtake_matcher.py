#!/usr/bin/env python3
"""
Offtake matcher — Princeps Phase 10
Corporate offtake matching: buyer profiles, demand-generation correlation,
volume matching, credit scoring, additionality assessment.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "match_buyers", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "annual_gen_mwh": 126000}
  {"command": "buyer_profile", "buyer_type": "data_centre"}
  {"command": "demand_correlation", "technology": "wind",
   "buyer_type": "industrial"}
"""

import json
import math
import random
import sys

# ── UK corporate buyer profiles ──────────────────────────────────────────

BUYER_PROFILES = {
    "data_centre": {
        "label": "Data Centre / Hyperscaler",
        "typical_demand_mwh": 250000,
        "load_factor": 0.95,
        "demand_shape": "flat",
        "credit_rating": "investment_grade",
        "ppa_appetite": "HIGH",
        "additionality_weight": 0.9,
        "price_sensitivity": 0.3,
        "term_preference_years": [10, 15, 20],
        "preferred_tech": ["wind", "solar"],
        "volume_flexibility_pct": 20,
        "examples": ["Microsoft", "Google", "Amazon", "Meta"],
        "hourly_demand": [1.0] * 24,
    },
    "industrial": {
        "label": "Industrial / Manufacturing",
        "typical_demand_mwh": 80000,
        "load_factor": 0.75,
        "demand_shape": "weekday_peak",
        "credit_rating": "sub_investment",
        "ppa_appetite": "MEDIUM",
        "additionality_weight": 0.5,
        "price_sensitivity": 0.8,
        "term_preference_years": [5, 7, 10],
        "preferred_tech": ["wind", "solar"],
        "volume_flexibility_pct": 10,
        "examples": ["Steel works", "Chemicals", "Cement", "Paper mills"],
        "hourly_demand": [0.3, 0.3, 0.3, 0.3, 0.3, 0.5, 0.8, 1.0, 1.0, 1.0,
                          1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 0.8, 0.6, 0.4, 0.3,
                          0.3, 0.3, 0.3, 0.3],
    },
    "commercial": {
        "label": "Commercial / Office",
        "typical_demand_mwh": 15000,
        "load_factor": 0.40,
        "demand_shape": "office_hours",
        "credit_rating": "investment_grade",
        "ppa_appetite": "MEDIUM",
        "additionality_weight": 0.7,
        "price_sensitivity": 0.6,
        "term_preference_years": [5, 10],
        "preferred_tech": ["solar"],
        "volume_flexibility_pct": 30,
        "examples": ["Banks", "Retail chains", "Telecom", "Insurance"],
        "hourly_demand": [0.15, 0.10, 0.10, 0.10, 0.10, 0.15, 0.30, 0.65,
                          0.90, 1.00, 1.00, 1.00, 1.00, 1.00, 0.95, 0.85,
                          0.70, 0.50, 0.30, 0.20, 0.15, 0.15, 0.15, 0.15],
    },
    "public_sector": {
        "label": "Public Sector / NHS / MOD",
        "typical_demand_mwh": 40000,
        "load_factor": 0.60,
        "demand_shape": "mixed",
        "credit_rating": "investment_grade",
        "ppa_appetite": "HIGH",
        "additionality_weight": 0.8,
        "price_sensitivity": 0.5,
        "term_preference_years": [10, 15],
        "preferred_tech": ["wind", "solar"],
        "volume_flexibility_pct": 15,
        "examples": ["NHS Trusts", "MoD", "Local authorities", "Universities"],
        "hourly_demand": [0.40, 0.35, 0.35, 0.35, 0.35, 0.40, 0.55, 0.75,
                          0.90, 0.95, 1.00, 1.00, 1.00, 0.95, 0.90, 0.85,
                          0.75, 0.60, 0.50, 0.45, 0.42, 0.40, 0.40, 0.40],
    },
    "retail_energy": {
        "label": "Retail Energy Supplier",
        "typical_demand_mwh": 500000,
        "load_factor": 0.55,
        "demand_shape": "domestic",
        "credit_rating": "sub_investment",
        "ppa_appetite": "HIGH",
        "additionality_weight": 0.3,
        "price_sensitivity": 0.9,
        "term_preference_years": [3, 5, 7],
        "preferred_tech": ["wind", "solar"],
        "volume_flexibility_pct": 40,
        "examples": ["Octopus", "Good Energy", "Ecotricity", "EDF"],
        "hourly_demand": [0.50, 0.45, 0.40, 0.38, 0.40, 0.50, 0.70, 0.85,
                          0.80, 0.70, 0.65, 0.60, 0.60, 0.60, 0.65, 0.75,
                          0.90, 1.00, 0.95, 0.85, 0.75, 0.65, 0.55, 0.50],
    },
    "ev_charging": {
        "label": "EV Charging Network",
        "typical_demand_mwh": 30000,
        "load_factor": 0.35,
        "demand_shape": "daytime_peak",
        "credit_rating": "unrated",
        "ppa_appetite": "MEDIUM",
        "additionality_weight": 0.85,
        "price_sensitivity": 0.7,
        "term_preference_years": [7, 10],
        "preferred_tech": ["solar", "wind"],
        "volume_flexibility_pct": 25,
        "examples": ["Tesla Supercharger", "BP Pulse", "Gridserve", "Pod Point"],
        "hourly_demand": [0.10, 0.05, 0.05, 0.05, 0.05, 0.10, 0.25, 0.55,
                          0.80, 0.90, 1.00, 1.00, 0.95, 0.85, 0.80, 0.85,
                          0.95, 1.00, 0.90, 0.70, 0.50, 0.30, 0.20, 0.15],
    },
}

# Generation profiles (normalised)
GEN_PROFILES = {
    "wind": [0.72, 0.75, 0.78, 0.80, 0.82, 0.78, 0.70, 0.62,
             0.55, 0.50, 0.48, 0.45, 0.42, 0.45, 0.50, 0.55,
             0.60, 0.65, 0.68, 0.70, 0.72, 0.74, 0.73, 0.72],
    "solar": [0, 0, 0, 0, 0.02, 0.08, 0.20, 0.40, 0.60, 0.78, 0.90, 0.96,
              1.00, 0.98, 0.92, 0.80, 0.62, 0.40, 0.18, 0.05, 0, 0, 0, 0],
    "bess": [0.9] * 24,
}


def _correlation(gen_profile: list, demand_profile: list) -> float:
    """Pearson correlation between generation and demand profiles."""
    n = min(len(gen_profile), len(demand_profile))
    if n < 2:
        return 0
    g = gen_profile[:n]
    d = demand_profile[:n]
    g_mean = sum(g) / n
    d_mean = sum(d) / n
    cov = sum((g[i] - g_mean) * (d[i] - d_mean) for i in range(n))
    g_std = math.sqrt(sum((g[i] - g_mean) ** 2 for i in range(n)))
    d_std = math.sqrt(sum((d[i] - d_mean) ** 2 for i in range(n)))
    if g_std == 0 or d_std == 0:
        return 0
    return cov / (g_std * d_std)


def _match_score(buyer: dict, technology: str, annual_gen_mwh: float,
                 gen_profile: list) -> dict:
    """Score a buyer match (0-100)."""
    # Volume match (how well supply meets demand)
    demand = buyer["typical_demand_mwh"]
    vol_ratio = min(annual_gen_mwh, demand) / max(annual_gen_mwh, demand, 1)
    vol_score = vol_ratio * 100

    # Shape correlation
    corr = _correlation(gen_profile, buyer["hourly_demand"])
    shape_score = max(0, (corr + 1) / 2 * 100)  # Scale -1..1 to 0..100

    # Technology preference
    tech_score = 90 if technology in buyer.get("preferred_tech", []) else 50

    # Credit quality
    credit_scores = {"investment_grade": 95, "sub_investment": 60, "unrated": 35}
    credit_score = credit_scores.get(buyer["credit_rating"], 50)

    # Additionality value
    add_score = buyer["additionality_weight"] * 100

    # PPA appetite
    appetite_scores = {"HIGH": 90, "MEDIUM": 60, "LOW": 30}
    appetite = appetite_scores.get(buyer["ppa_appetite"], 50)

    # Weighted composite
    composite = (
        vol_score * 0.25 +
        shape_score * 0.20 +
        tech_score * 0.15 +
        credit_score * 0.15 +
        add_score * 0.10 +
        appetite * 0.15
    )

    return {
        "volume_match": round(vol_score, 1),
        "shape_correlation": round(corr, 3),
        "shape_score": round(shape_score, 1),
        "technology_fit": round(tech_score, 1),
        "credit_score": round(credit_score, 1),
        "additionality_score": round(add_score, 1),
        "appetite_score": round(appetite, 1),
        "composite_score": round(composite, 1),
        "recommendation": "STRONG" if composite >= 70 else "SUITABLE" if composite >= 50 else "MARGINAL",
    }


def match_buyers(capacity_mw: float = 50, technology: str = "wind",
                  region: str = "Scotland", annual_gen_mwh: float = None) -> dict:
    """
    Match a generation asset to the best corporate offtake buyers.
    """
    # Estimate annual generation if not provided
    cf = {"wind": 0.287, "solar": 0.11, "bess": 0.90}.get(technology, 0.25)
    if annual_gen_mwh is None or annual_gen_mwh <= 0:
        annual_gen_mwh = capacity_mw * cf * 8760

    gen_profile = GEN_PROFILES.get(technology, GEN_PROFILES["wind"])

    matches = []
    for buyer_id, buyer in BUYER_PROFILES.items():
        score = _match_score(buyer, technology, annual_gen_mwh, gen_profile)
        matches.append({
            "buyer_type": buyer_id,
            "label": buyer["label"],
            "credit_rating": buyer["credit_rating"],
            "typical_demand_mwh": buyer["typical_demand_mwh"],
            "ppa_appetite": buyer["ppa_appetite"],
            "preferred_terms": buyer["term_preference_years"],
            "examples": buyer["examples"][:2],
            **score,
        })

    matches.sort(key=lambda m: -m["composite_score"])

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "annual_gen_mwh": round(annual_gen_mwh),
        },
        "matches": matches,
        "top_match": {
            "buyer_type": matches[0]["buyer_type"],
            "label": matches[0]["label"],
            "score": matches[0]["composite_score"],
            "recommendation": matches[0]["recommendation"],
        },
        "market_summary": {
            "strong_matches": sum(1 for m in matches if m["recommendation"] == "STRONG"),
            "suitable_matches": sum(1 for m in matches if m["recommendation"] == "SUITABLE"),
            "marginal_matches": sum(1 for m in matches if m["recommendation"] == "MARGINAL"),
        },
    }


def buyer_profile(buyer_type: str = "data_centre") -> dict:
    """
    Detailed profile for a specific buyer type.
    """
    buyer = BUYER_PROFILES.get(buyer_type)
    if not buyer:
        return {"error": f"Unknown buyer type: {buyer_type}"}

    return {
        "buyer_type": buyer_type,
        "label": buyer["label"],
        "typical_demand_mwh": buyer["typical_demand_mwh"],
        "load_factor": buyer["load_factor"],
        "demand_shape": buyer["demand_shape"],
        "credit_rating": buyer["credit_rating"],
        "ppa_appetite": buyer["ppa_appetite"],
        "additionality_weight": buyer["additionality_weight"],
        "price_sensitivity": buyer["price_sensitivity"],
        "term_preference_years": buyer["term_preference_years"],
        "preferred_tech": buyer["preferred_tech"],
        "volume_flexibility_pct": buyer["volume_flexibility_pct"],
        "examples": buyer["examples"],
        "hourly_demand_profile": [
            {"hour": h, "demand_factor": buyer["hourly_demand"][h]}
            for h in range(24)
        ],
    }


def demand_correlation(technology: str = "wind",
                        buyer_type: str = "industrial") -> dict:
    """
    Analyse correlation between generation profile and buyer demand.
    """
    buyer = BUYER_PROFILES.get(buyer_type)
    if not buyer:
        return {"error": f"Unknown buyer type: {buyer_type}"}

    gen_profile = GEN_PROFILES.get(technology, GEN_PROFILES["wind"])
    demand = buyer["hourly_demand"]
    corr = _correlation(gen_profile, demand)

    # Hourly overlap analysis
    hourly = []
    for h in range(24):
        g = gen_profile[h]
        d = demand[h]
        overlap = min(g, d) / max(g, d, 0.01)
        hourly.append({
            "hour": h,
            "generation": round(g, 3),
            "demand": round(d, 3),
            "overlap_pct": round(overlap * 100, 1),
            "surplus": round(max(0, g - d), 3),
            "deficit": round(max(0, d - g), 3),
        })

    # Aggregate metrics
    total_gen = sum(h["generation"] for h in hourly)
    total_demand = sum(h["demand"] for h in hourly)
    total_overlap = sum(min(h["generation"], h["demand"]) for h in hourly)

    return {
        "parameters": {"technology": technology, "buyer_type": buyer_type},
        "correlation": round(corr, 4),
        "correlation_label": "STRONG" if corr > 0.7 else "MODERATE" if corr > 0.3 else "WEAK" if corr > -0.1 else "INVERSE",
        "volume_match_pct": round(total_overlap / max(total_demand, 0.01) * 100, 1),
        "surplus_pct": round((total_gen - total_overlap) / max(total_gen, 0.01) * 100, 1),
        "hourly_analysis": hourly,
        "peak_overlap_hours": [h["hour"] for h in hourly if h["overlap_pct"] > 70],
        "recommendation": (
            f"{technology.title()} generation has {'strong' if corr > 0.5 else 'moderate' if corr > 0 else 'weak'} "
            f"correlation with {buyer['label']} demand. "
            f"Volume match covers {round(total_overlap / max(total_demand, 0.01) * 100)}% of buyer demand."
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
        if cmd == "match_buyers":
            result = match_buyers(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                annual_gen_mwh=req.get("annual_gen_mwh"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "buyer_profile":
            result = buyer_profile(req.get("buyer_type", "data_centre"))
            json.dump(result, sys.stdout)
        elif cmd == "demand_correlation":
            result = demand_correlation(
                technology=req.get("technology", "wind"),
                buyer_type=req.get("buyer_type", "industrial"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
