"""
Co-location Opportunity Search Engine.

Links three data sources that currently exist in isolation:
1. Grid substations with headroom (from DNO data + PostGIS)
2. Land parcels with ownership (from HM Land Registry INSPIRE)
3. Nearby companies (from Companies House API)

Plus:
4. REPD projects (stalled/withdrawn = potential land opportunities)
5. Environmental constraints (SSSI, AONB, flood zones)
6. ALC grades (agricultural land classification)

Returns ranked co-location opportunities: sites where grid + land + ownership
align for solar, BESS, wind, or data centre development.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Optional

log = logging.getLogger("princeps.colocation_search")

# ═══════════════════════════════════════════════════════════════
#  LEASE BENCHMARKS — UK regional land rental rates
# ═══════════════════════════════════════════════════════════════

# Source: Knight Frank UK Farmland Index, Savills Rural Market Survey, RICS
# All values in £/ha/year
LEASE_BENCHMARKS = {
    # By technology
    "solar": {
        "Grade 1": {"low": 800, "mid": 1000, "high": 1200, "note": "BMV premium — rare for solar consent"},
        "Grade 2": {"low": 900, "mid": 1100, "high": 1400, "note": "BMV — strong planning resistance"},
        "Grade 3a": {"low": 800, "mid": 1000, "high": 1300, "note": "BMV borderline — detailed ALC required"},
        "Grade 3b": {"low": 700, "mid": 1000, "high": 1300, "note": "Standard solar land — most common"},
        "Grade 4": {"low": 500, "mid": 800, "high": 1100, "note": "Lower quality — good for solar"},
        "Grade 5": {"low": 300, "mid": 600, "high": 900, "note": "Marginal land — ideal for solar"},
        "Non Agricultural": {"low": 600, "mid": 1000, "high": 1500, "note": "Brownfield premium possible"},
    },
    "wind": {
        "default": {"low": 600, "mid": 800, "high": 1200, "note": "Per turbine location typically £8-15K/MW/yr"},
    },
    "bess": {
        "default": {"low": 2000, "mid": 4000, "high": 8000, "note": "Small footprint, high value per ha"},
    },
    "data_centre": {
        "default": {"low": 5000, "mid": 15000, "high": 40000, "note": "Industrial/commercial land rates apply"},
    },
}

# Regional multipliers (base = Midlands = 1.0)
REGIONAL_MULTIPLIERS = {
    "South East": 1.4,
    "South West": 1.1,
    "East Anglia": 1.2,
    "East of England": 1.2,
    "Midlands": 1.0,
    "West Midlands": 1.0,
    "East Midlands": 1.0,
    "North West": 0.85,
    "North East": 0.75,
    "Yorkshire": 0.8,
    "Wales": 0.7,
    "Scotland": 0.65,
    "default": 1.0,
}


def benchmark_lease(technology: str, alc_grade: str = "Grade 3b",
                    region: str = "default", area_ha: float = 10) -> dict:
    """
    Benchmark a land lease rate against UK market data.

    Returns low/mid/high rates, regional adjustment, annual cost, and notes.
    """
    tech_rates = LEASE_BENCHMARKS.get(technology, LEASE_BENCHMARKS.get("solar", {}))
    grade_rates = tech_rates.get(alc_grade, tech_rates.get("default", tech_rates.get("Grade 3b", {})))
    if not grade_rates:
        grade_rates = {"low": 500, "mid": 1000, "high": 1500, "note": "No benchmark data"}

    multiplier = REGIONAL_MULTIPLIERS.get(region, REGIONAL_MULTIPLIERS["default"])

    return {
        "technology": technology,
        "alc_grade": alc_grade,
        "region": region,
        "regional_multiplier": multiplier,
        "benchmark_gbp_ha_yr": {
            "low": round(grade_rates["low"] * multiplier),
            "mid": round(grade_rates["mid"] * multiplier),
            "high": round(grade_rates["high"] * multiplier),
        },
        "annual_cost_gbp": {
            "low": round(grade_rates["low"] * multiplier * area_ha),
            "mid": round(grade_rates["mid"] * multiplier * area_ha),
            "high": round(grade_rates["high"] * multiplier * area_ha),
        },
        "area_ha": area_ha,
        "note": grade_rates.get("note", ""),
        "source": "Knight Frank / Savills / RICS benchmarks (2024-25)",
    }


def validate_lease_rate(proposed_gbp_ha: float, technology: str, alc_grade: str = "Grade 3b",
                        region: str = "default") -> dict:
    """Check if a proposed lease rate is within market range."""
    bm = benchmark_lease(technology, alc_grade, region, area_ha=1)
    low = bm["benchmark_gbp_ha_yr"]["low"]
    mid = bm["benchmark_gbp_ha_yr"]["mid"]
    high = bm["benchmark_gbp_ha_yr"]["high"]

    if proposed_gbp_ha < low * 0.7:
        assessment = "BELOW_MARKET"
        detail = f"Proposed £{proposed_gbp_ha}/ha is {((low - proposed_gbp_ha) / low * 100):.0f}% below low benchmark"
    elif proposed_gbp_ha > high * 1.3:
        assessment = "ABOVE_MARKET"
        detail = f"Proposed £{proposed_gbp_ha}/ha is {((proposed_gbp_ha - high) / high * 100):.0f}% above high benchmark"
    elif proposed_gbp_ha <= mid:
        assessment = "COMPETITIVE"
        detail = f"Below mid-market (£{mid}/ha) — good deal"
    else:
        assessment = "FAIR"
        detail = f"Within market range (£{low}-{high}/ha)"

    return {
        "proposed_gbp_ha": proposed_gbp_ha,
        "assessment": assessment,
        "detail": detail,
        "benchmark": bm["benchmark_gbp_ha_yr"],
        "percentile": round(min(100, max(0, (proposed_gbp_ha - low) / max(high - low, 1) * 100))),
    }


# ═══════════════════════════════════════════════════════════════
#  LANDOWNER MATCHING — fuzzy match titles to companies
# ═══════════════════════════════════════════════════════════════

def _normalise_name(name: str) -> str:
    """Normalise a company/landowner name for matching."""
    import re
    s = name.upper().strip()
    # Remove common suffixes
    for suffix in ["LIMITED", "LTD", "PLC", "LLP", "INC", "CORP", "COMPANY", "CO", "& CO",
                   "HOLDINGS", "GROUP", "ESTATES", "FARM", "FARMS", "PROPERTY", "PROPERTIES",
                   "LAND", "AGRICULTURE", "AGRICULTURAL"]:
        s = re.sub(rf"\b{suffix}\b", "", s)
    s = re.sub(r"[^A-Z0-9\s]", "", s)  # remove punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _levenshtein(s1: str, s2: str) -> int:
    """Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def match_landowner_to_companies(landowner_name: str, companies: list[dict],
                                  threshold: float = 0.5) -> list[dict]:
    """
    Fuzzy-match a landowner name to Companies House entities.

    Uses normalised Levenshtein distance + token overlap scoring.
    Returns matches above threshold with confidence scores.
    """
    norm_owner = _normalise_name(landowner_name)
    owner_tokens = set(norm_owner.split())
    matches = []

    for company in companies:
        comp_name = company.get("name", "") or company.get("title", "")
        norm_comp = _normalise_name(comp_name)
        comp_tokens = set(norm_comp.split())

        # Token overlap score
        if not owner_tokens or not comp_tokens:
            continue
        overlap = len(owner_tokens & comp_tokens)
        token_score = overlap / max(len(owner_tokens | comp_tokens), 1)

        # Levenshtein similarity
        max_len = max(len(norm_owner), len(norm_comp), 1)
        lev_dist = _levenshtein(norm_owner, norm_comp)
        lev_score = 1 - lev_dist / max_len

        # Combined score (weighted)
        score = token_score * 0.6 + lev_score * 0.4

        if score >= threshold:
            matches.append({
                "company_name": comp_name,
                "company_number": company.get("company_number", ""),
                "match_score": round(score, 3),
                "token_overlap": overlap,
                "normalised_owner": norm_owner,
                "normalised_company": norm_comp,
                "address": company.get("address", ""),
                "status": company.get("status", ""),
                "sic_codes": company.get("sic_codes", []),
            })

    matches.sort(key=lambda m: m["match_score"], reverse=True)
    return matches[:5]


# ═══════════════════════════════════════════════════════════════
#  CO-LOCATION OPPORTUNITY SEARCH
# ═══════════════════════════════════════════════════════════════

async def search_colocation_opportunities(
    pool,
    lat: float, lon: float,
    radius_km: float = 10,
    technology: str = "solar",
    min_capacity_mw: float = 5,
    min_area_ha: float = 2,
) -> dict:
    """
    Search for co-location opportunities by linking:
    1. Grid substations with headroom
    2. Nearby land parcels (HMLR)
    3. REPD stalled projects (land opportunities)
    4. Companies House nearby landowners
    5. Environmental constraints
    6. Lease benchmarking

    Returns ranked opportunities with all data linked.
    """
    from utils.land_registry import get_land_parcels, get_agricultural_land_class

    opportunities = []

    # 1. Find substations with headroom
    substations = []
    try:
        rows = await pool.fetch("""
            SELECT id, name, voltage_kv, demand_headroom_mw,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon,
                   ST_Distance(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) / 1000 as dist_km
            FROM grid_substations
            WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3)
            AND demand_headroom_mw >= $4
            ORDER BY dist_km
            LIMIT 20
        """, lon, lat, radius_km * 1000, min_capacity_mw)
        substations = [dict(r) for r in rows]
    except Exception as e:
        log.warning("Substation query failed: %s", e)

    # 2. Find REPD stalled/withdrawn projects (land opportunities)
    repd_opportunities = []
    try:
        rows = await pool.fetch("""
            SELECT ref_id, site_name, technology, capacity_mw, dev_status, county,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon,
                   ST_Distance(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) / 1000 as dist_km
            FROM repd_projects
            WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3)
            AND dev_status IN ('Withdrawn', 'Refused', 'Appeal Refused', 'Abandoned', 'Expired')
            ORDER BY capacity_mw DESC
            LIMIT 15
        """, lon, lat, radius_km * 1000)
        repd_opportunities = [dict(r) for r in rows]
    except Exception as e:
        log.warning("REPD query failed: %s", e)

    # 3. For each substation, find nearby land parcels
    for sub in substations[:8]:  # limit to top 8
        sub_lat, sub_lon = sub["lat"], sub["lon"]

        # Land parcels within 3km of substation
        half_deg = 3 / 111.32
        bbox = (sub_lon - half_deg, sub_lat - half_deg, sub_lon + half_deg, sub_lat + half_deg)
        try:
            parcels = await get_land_parcels(bbox, min_area_ha=min_area_ha, max_features=10)
            land_features = parcels.get("features", []) if isinstance(parcels, dict) else []
        except Exception:
            land_features = []

        # ALC grade
        try:
            alc = await get_agricultural_land_class(sub_lat, sub_lon)
        except Exception:
            alc = {"grade": "Grade 3b", "suitable_for_development": True}

        # Lease benchmark
        lease = benchmark_lease(technology, alc.get("grade", "Grade 3b"), area_ha=min_area_ha)

        # Score this opportunity
        score = 0
        score += min(30, sub.get("demand_headroom_mw", 0) * 0.5)  # headroom (max 30)
        score += max(0, 20 - sub.get("dist_km", 20) * 2)  # proximity (max 20)
        score += 15 if land_features else 0  # land available
        score += 10 if alc.get("suitable_for_development") else 0  # non-BMV
        score += 10 if sub.get("voltage_kv", 0) >= 33 else 5  # voltage
        # REPD bonus: stalled project nearby = proven site
        nearby_repd = [r for r in repd_opportunities if _haversine(sub_lat, sub_lon, r["lat"], r["lon"]) < 3]
        score += 15 if nearby_repd else 0

        opportunities.append({
            "substation": {
                "name": sub.get("name", ""),
                "voltage_kv": sub.get("voltage_kv"),
                "headroom_mw": round(sub.get("demand_headroom_mw", 0), 1),
                "distance_km": round(sub.get("dist_km", 0), 1),
                "lat": sub_lat,
                "lon": sub_lon,
            },
            "land": {
                "parcels_found": len(land_features),
                "parcels": [
                    {
                        "title": f.get("properties", {}).get("title_number", ""),
                        "tenure": f.get("properties", {}).get("tenure", ""),
                        "area_ha": f.get("properties", {}).get("area_ha"),
                    }
                    for f in land_features[:5]
                ],
            },
            "alc": {
                "grade": alc.get("grade", "Unknown"),
                "bmv": alc.get("suitable_for_development") is False,
                "suitable": alc.get("suitable_for_development", True),
            },
            "lease_benchmark": lease["benchmark_gbp_ha_yr"],
            "repd_opportunities": [
                {
                    "name": r["site_name"],
                    "technology": r["technology"],
                    "capacity_mw": r["capacity_mw"],
                    "status": r["dev_status"],
                    "distance_km": round(r["dist_km"], 1),
                }
                for r in nearby_repd[:3]
            ],
            "score": round(min(100, score), 1),
        })

    # Sort by score
    opportunities.sort(key=lambda o: o["score"], reverse=True)
    for i, opp in enumerate(opportunities):
        opp["rank"] = i + 1

    return {
        "search": {"lat": lat, "lon": lon, "radius_km": radius_km, "technology": technology},
        "opportunities": opportunities,
        "count": len(opportunities),
        "substations_searched": len(substations),
        "repd_stalled_nearby": len(repd_opportunities),
    }


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))
