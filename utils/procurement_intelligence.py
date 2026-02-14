"""
Procurement Intelligence Module.

Enhances UK energy tender tracking with:
- GeoAI satellite-based site condition scoring for tender locations
- Grid capacity matching (pairs tenders with available headroom)
- Bid viability assessment (financial + technical feasibility)
- Competitive landscape analysis (nearby projects, planning history)
- Tender-to-site pairing recommendations
"""

from __future__ import annotations

import math
from datetime import datetime, date
from typing import Any


# UK energy procurement cost benchmarks (GBP per kW, 2024)
COST_BENCHMARKS = {
    "solar_pv": {"min": 450, "median": 650, "max": 950},
    "battery_storage": {"min": 300, "median": 450, "max": 700},
    "wind_onshore": {"min": 900, "median": 1200, "max": 1800},
    "ev_charging": {"min": 800, "median": 1200, "max": 2000},
    "heat_pump": {"min": 300, "median": 500, "max": 800},
    "substation": {"min": 150, "median": 250, "max": 400},
    "grid_reinforcement": {"min": 100, "median": 200, "max": 350},
}

# Technology keywords for classification
TECH_KEYWORDS = {
    "solar_pv": ["solar", "photovoltaic", "pv", "solar farm", "solar panel"],
    "battery_storage": ["battery", "bess", "energy storage", "storage system"],
    "wind_onshore": ["wind", "turbine", "wind farm", "onshore wind"],
    "ev_charging": ["ev", "electric vehicle", "charging", "charge point"],
    "heat_pump": ["heat pump", "ground source", "air source", "gshp", "ashp"],
    "substation": ["substation", "switchgear", "transformer"],
    "grid_reinforcement": ["grid", "reinforcement", "cable", "overhead line", "network"],
    "hydrogen": ["hydrogen", "electrolyser", "h2", "fuel cell"],
}


def classify_tender_technology(title: str, description: str = "") -> str:
    """Classify tender by energy technology using keyword matching."""
    text = f"{title} {description}".lower()
    scores = {}
    for tech, keywords in TECH_KEYWORDS.items():
        scores[tech] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def assess_bid_viability(
    tender: dict,
    site_score: float | None = None,
    grid_headroom_mw: float | None = None,
    distance_to_grid_km: float | None = None,
    planning_success_rate: float | None = None,
) -> dict:
    """
    Assess viability of bidding on a tender.

    Returns a viability score (0-100) with breakdown.
    """
    score = 50.0  # neutral baseline
    factors = []

    # Technology classification
    tech = classify_tender_technology(
        tender.get("title", ""),
        tender.get("description", ""),
    )

    # Value assessment
    value = tender.get("value_gbp", 0)
    if value and value > 100_000:
        score += 5
        factors.append(f"Significant contract value (£{value:,.0f})")
    elif value and value > 1_000_000:
        score += 10
        factors.append(f"Large contract value (£{value:,.0f})")

    # Deadline assessment
    deadline = tender.get("deadline", "")
    if deadline:
        try:
            dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            days_left = (dl - datetime.now(dl.tzinfo)).days
            if days_left > 30:
                score += 5
                factors.append(f"Sufficient preparation time ({days_left} days)")
            elif days_left > 14:
                factors.append(f"Moderate timeline ({days_left} days)")
            elif days_left > 0:
                score -= 10
                factors.append(f"Tight deadline ({days_left} days)")
            else:
                score -= 30
                factors.append("Deadline passed")
        except (ValueError, TypeError):
            pass

    # Site suitability (from GeoAI / GeeFlow scoring)
    if site_score is not None:
        if site_score >= 70:
            score += 15
            factors.append(f"Excellent site suitability ({site_score}/100)")
        elif site_score >= 40:
            score += 5
            factors.append(f"Moderate site suitability ({site_score}/100)")
        else:
            score -= 10
            factors.append(f"Poor site suitability ({site_score}/100)")

    # Grid capacity
    if grid_headroom_mw is not None:
        if grid_headroom_mw >= 5:
            score += 10
            factors.append(f"Strong grid headroom ({grid_headroom_mw:.1f} MW)")
        elif grid_headroom_mw >= 1:
            score += 5
            factors.append(f"Adequate grid headroom ({grid_headroom_mw:.1f} MW)")
        else:
            score -= 10
            factors.append(f"Limited grid headroom ({grid_headroom_mw:.1f} MW)")

    # Grid distance
    if distance_to_grid_km is not None:
        if distance_to_grid_km <= 2:
            score += 5
            factors.append(f"Close to grid ({distance_to_grid_km:.1f} km)")
        elif distance_to_grid_km > 10:
            score -= 10
            factors.append(f"Remote from grid ({distance_to_grid_km:.1f} km)")

    # Planning history
    if planning_success_rate is not None:
        if planning_success_rate >= 70:
            score += 10
            factors.append(f"Strong planning history ({planning_success_rate:.0f}% approval)")
        elif planning_success_rate >= 40:
            score += 3
            factors.append(f"Mixed planning history ({planning_success_rate:.0f}% approval)")
        else:
            score -= 5
            factors.append(f"Weak planning history ({planning_success_rate:.0f}% approval)")

    score = max(0, min(100, score))

    if score >= 70:
        recommendation = "STRONG_BID"
    elif score >= 45:
        recommendation = "CONDITIONAL_BID"
    else:
        recommendation = "NO_BID"

    return {
        "viability_score": round(score, 1),
        "recommendation": recommendation,
        "technology": tech,
        "factors": factors,
        "cost_benchmark": COST_BENCHMARKS.get(tech),
        "tender_title": tender.get("title", ""),
    }


def match_tenders_to_sites(
    tenders: list[dict],
    available_sites: list[dict],
    max_matches: int = 5,
) -> list[dict]:
    """
    Match procurement tenders to available/scored sites.

    Each site should have: lat, lon, site_score, grid_headroom_mw, asset_type
    """
    matches = []
    for tender in tenders:
        tech = classify_tender_technology(
            tender.get("title", ""),
            tender.get("description", ""),
        )

        # Filter sites by technology compatibility
        compatible = []
        for site in available_sites:
            site_type = site.get("asset_type", "solar_farm")
            if tech in ("solar_pv", "unknown") and "solar" in site_type:
                compatible.append(site)
            elif tech == "battery_storage" and "battery" in site_type:
                compatible.append(site)
            elif tech in ("wind_onshore",) and "wind" in site_type:
                compatible.append(site)
            else:
                # Generic match — any high-scoring site
                if site.get("site_score", 0) >= 60:
                    compatible.append(site)

        # Sort by site score descending
        compatible.sort(key=lambda s: s.get("site_score", 0), reverse=True)

        tender_match = {
            "tender": {
                "title": tender.get("title"),
                "value_gbp": tender.get("value_gbp"),
                "deadline": tender.get("deadline"),
                "source": tender.get("source"),
            },
            "technology": tech,
            "matched_sites": compatible[:max_matches],
            "match_count": len(compatible),
        }
        matches.append(tender_match)

    return matches


def procurement_pipeline_summary(tenders: list[dict]) -> dict:
    """
    Generate procurement pipeline analytics.

    Breaks down tenders by technology, value, timeline, and source.
    """
    by_tech = {}
    by_source = {}
    total_value = 0
    active_count = 0
    urgent_count = 0

    for t in tenders:
        tech = classify_tender_technology(t.get("title", ""), t.get("description", ""))
        by_tech[tech] = by_tech.get(tech, 0) + 1

        source = t.get("source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1

        value = t.get("value_gbp", 0) or 0
        total_value += value
        active_count += 1

        deadline = t.get("deadline", "")
        if deadline:
            try:
                dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                days = (dl - datetime.now(dl.tzinfo)).days
                if 0 < days <= 14:
                    urgent_count += 1
            except (ValueError, TypeError):
                pass

    return {
        "total_active": active_count,
        "total_value_gbp": round(total_value),
        "urgent_count": urgent_count,
        "by_technology": by_tech,
        "by_source": by_source,
        "avg_value_gbp": round(total_value / active_count) if active_count else 0,
        "cost_benchmarks": COST_BENCHMARKS,
    }
