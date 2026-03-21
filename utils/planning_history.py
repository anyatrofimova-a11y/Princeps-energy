"""
Per-parcel planning history lookup — combines real UK data sources to give
developers a complete picture of planning precedent at their site.

Data sources:
1. planning.data.gov.uk — national planning dataset (entities API)
2. REPD (in PostGIS) — all UK renewable energy projects >150 kW
3. Derived statistics — approval rates, determination times, trends, risk

Called from app/routers/land.py GET /api/planning/history
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import httpx

log = logging.getLogger("princeps.planning_history")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLANNING_DATA_BASE = "https://www.planning.data.gov.uk"
ENTITY_ENDPOINT = f"{PLANNING_DATA_BASE}/entity.json"
SEARCH_ENDPOINT = f"{PLANNING_DATA_BASE}/api/v1/entity.json"

# Datasets of interest on planning.data.gov.uk
PLANNING_DATASETS = [
    "planning-application",
    "planning-permission",
]

# REPD statuses considered "approved" for rate calc
APPROVED_STATUSES = frozenset({
    "Operational", "Under Construction", "Awaiting Construction",
    "Approved", "No Application Required",
})
REFUSED_STATUSES = frozenset({
    "Refused", "Appeal Refused",
})
DECIDED_STATUSES = APPROVED_STATUSES | REFUSED_STATUSES

# Solar-related technology strings in REPD
SOLAR_TECHS = frozenset({
    "Solar Photovoltaics", "Solar PV", "Solar",
    "Solar Photovoltaics (PV)",
})


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    la1, lo1, la2, lo2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# 1. planning.data.gov.uk API queries
# ---------------------------------------------------------------------------

async def _query_planning_data_gov(
    lat: float, lon: float, radius_km: float,
) -> list[dict]:
    """
    Query planning.data.gov.uk entity endpoint for planning applications
    near the given coordinates.

    The API supports point-based spatial queries using longitude/latitude
    parameters or geometry-based filtering.
    """
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for dataset in PLANNING_DATASETS:
            try:
                # The entity.json endpoint supports spatial filtering
                # via longitude, latitude, and dataset parameters
                params = {
                    "dataset": dataset,
                    "longitude": str(lon),
                    "latitude": str(lat),
                    "limit": "100",
                }
                resp = await client.get(ENTITY_ENDPOINT, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    entities = data.get("entities", data) if isinstance(data, dict) else data
                    if isinstance(entities, list):
                        for ent in entities:
                            results.append(_normalise_pdg_entity(ent, dataset))
                    elif isinstance(entities, dict) and "entities" in entities:
                        for ent in entities["entities"]:
                            results.append(_normalise_pdg_entity(ent, dataset))
                else:
                    log.debug(
                        "planning.data.gov.uk %s returned %d",
                        dataset, resp.status_code,
                    )
            except Exception as e:
                log.warning("planning.data.gov.uk query failed for %s: %s", dataset, e)

        # Also try the search/entity endpoint with point geometry
        try:
            params = {
                "longitude": str(lon),
                "latitude": str(lat),
                "radius": str(int(radius_km * 1000)),  # metres
                "dataset": "planning-application",
                "limit": "100",
            }
            resp = await client.get(SEARCH_ENDPOINT, params=params)
            if resp.status_code == 200:
                data = resp.json()
                entities = data if isinstance(data, list) else data.get("entities", [])
                if isinstance(entities, list):
                    for ent in entities:
                        norm = _normalise_pdg_entity(ent, "planning-application")
                        # Deduplicate by entity reference
                        if not any(r.get("reference") == norm.get("reference") for r in results):
                            results.append(norm)
        except Exception as e:
            log.debug("planning.data.gov.uk search endpoint: %s", e)

    # Post-filter by distance (API may return wider set)
    filtered = []
    for r in results:
        rlat = r.get("lat")
        rlon = r.get("lon")
        if rlat and rlon:
            dist = _haversine_km(lat, lon, rlat, rlon)
            if dist <= radius_km:
                r["distance_km"] = round(dist, 2)
                filtered.append(r)
        else:
            # Keep entries without coords — they matched by dataset query
            r["distance_km"] = None
            filtered.append(r)

    return filtered


def _normalise_pdg_entity(ent: dict, dataset: str) -> dict:
    """Normalise a planning.data.gov.uk entity into a consistent dict."""
    point = ent.get("point") or {}
    geom = ent.get("geometry") or {}

    lat = None
    lon = None
    if isinstance(point, dict):
        lat = point.get("latitude")
        lon = point.get("longitude")
    elif isinstance(point, str) and "," in point:
        parts = point.split(",")
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            pass

    return {
        "source": "planning.data.gov.uk",
        "dataset": dataset,
        "entity": ent.get("entity"),
        "reference": ent.get("reference") or ent.get("name"),
        "name": ent.get("name", ""),
        "description": ent.get("description", ""),
        "organisation": ent.get("organisation-entity") or ent.get("organisation", ""),
        "entry_date": ent.get("entry-date"),
        "start_date": ent.get("start-date"),
        "end_date": ent.get("end-date"),
        "lat": lat,
        "lon": lon,
        "typology": ent.get("typology", ""),
        "categories": ent.get("categories", []),
        "prefix": ent.get("prefix", ""),
    }


# ---------------------------------------------------------------------------
# 2. REPD database query
# ---------------------------------------------------------------------------

async def _query_repd(
    pool, lat: float, lon: float, radius_km: float,
) -> list[dict]:
    """
    Query REPD projects from PostGIS within the given radius.
    Returns detailed records including planning dates for timeline analysis.
    """
    radius_m = radius_km * 1000
    try:
        rows = await pool.fetch("""
            SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                   dev_status, dev_status_short, operator, region, county,
                   planning_authority, address, mounting_type,
                   planning_submitted, planning_granted,
                   under_construction, operational,
                   ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
                   ST_Distance(
                       geometry::geography,
                       ST_SetSRID(ST_Point($1, $2), 4326)::geography
                   ) AS distance_m
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                  geometry::geography,
                  ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                  $3
              )
            ORDER BY distance_m ASC
            LIMIT 500
        """, lon, lat, radius_m)

        results = []
        for r in rows:
            status = r["dev_status_short"] or r["dev_status"] or "Unknown"
            tech = r["technology_type"] or "Unknown"
            cap = float(r["installed_capacity_mw"] or 0)

            # Calculate determination time if both dates available
            determination_months = None
            submitted = r["planning_submitted"]
            granted = r["planning_granted"]
            if submitted and granted:
                delta = granted - submitted
                determination_months = round(delta.days / 30.44, 1)

            results.append({
                "source": "repd",
                "ref_id": r["ref_id"],
                "site_name": r["site_name"] or "",
                "technology": tech,
                "capacity_mw": round(cap, 2),
                "status": status,
                "operator": r["operator"] or "",
                "planning_authority": r["planning_authority"] or "",
                "region": r["region"] or "",
                "county": r["county"] or "",
                "mounting_type": r["mounting_type"] or "",
                "planning_submitted": r["planning_submitted"].isoformat() if r["planning_submitted"] else None,
                "planning_granted": r["planning_granted"].isoformat() if r["planning_granted"] else None,
                "under_construction": r["under_construction"].isoformat() if r["under_construction"] else None,
                "operational": r["operational"].isoformat() if r["operational"] else None,
                "determination_months": determination_months,
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "distance_km": round(float(r["distance_m"]) / 1000, 2),
            })

        return results
    except Exception as e:
        log.warning("REPD planning history query failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# 3. Planning statistics
# ---------------------------------------------------------------------------

def _compute_planning_stats(
    repd_projects: list[dict], lat: float, lon: float,
) -> dict:
    """
    Calculate planning statistics from REPD data:
    - Solar approval rate within 10 km
    - Average determination time
    - Cumulative capacity within 5 km
    - Recent trends (3-year rolling)
    - Planning authority info
    """
    # --- Solar approval rate (all decided solar within 10 km) ---
    solar_approved = 0
    solar_refused = 0
    solar_total_decided = 0

    all_approved = 0
    all_refused = 0
    all_total_decided = 0

    determination_times: list[float] = []
    capacity_5km = 0.0
    capacity_10km = 0.0

    # For trend analysis, bucket by year
    yearly_approved: dict[int, int] = {}
    yearly_refused: dict[int, int] = {}

    # Collect planning authorities
    authorities: dict[str, int] = {}

    for p in repd_projects:
        dist = p.get("distance_km", 999)
        status = p.get("status", "")
        tech = p.get("technology", "")
        cap = p.get("capacity_mw", 0)
        is_solar = tech in SOLAR_TECHS or "solar" in tech.lower()

        # Planning authority tally
        auth = p.get("planning_authority", "")
        if auth:
            authorities[auth] = authorities.get(auth, 0) + 1

        # Capacity within 5 km
        if dist <= 5:
            if status in APPROVED_STATUSES:
                capacity_5km += cap

        # Capacity within 10 km
        if dist <= 10:
            if status in APPROVED_STATUSES:
                capacity_10km += cap

        # Approval rate (decided projects within 10 km)
        if dist <= 10 and status in DECIDED_STATUSES:
            all_total_decided += 1
            if status in APPROVED_STATUSES:
                all_approved += 1
            else:
                all_refused += 1

            if is_solar:
                solar_total_decided += 1
                if status in APPROVED_STATUSES:
                    solar_approved += 1
                else:
                    solar_refused += 1

        # Determination time
        det = p.get("determination_months")
        if det and 0 < det < 120:  # sanity: exclude > 10 years
            determination_times.append(det)

        # Yearly trend (use planning_granted or planning_submitted year)
        grant_date = p.get("planning_granted")
        if grant_date and status in DECIDED_STATUSES:
            try:
                year = int(grant_date[:4]) if isinstance(grant_date, str) else grant_date.year
                if status in APPROVED_STATUSES:
                    yearly_approved[year] = yearly_approved.get(year, 0) + 1
                else:
                    yearly_refused[year] = yearly_refused.get(year, 0) + 1
            except (ValueError, AttributeError):
                pass

    # Overall approval rates
    overall_approval_rate = (
        round(all_approved / all_total_decided, 3) if all_total_decided > 0 else None
    )
    solar_approval_rate = (
        round(solar_approved / solar_total_decided, 3) if solar_total_decided > 0 else None
    )

    # Average determination time
    avg_determination_months = (
        round(sum(determination_times) / len(determination_times), 1)
        if determination_times else None
    )
    median_determination_months = None
    if determination_times:
        sorted_det = sorted(determination_times)
        mid = len(sorted_det) // 2
        median_determination_months = round(
            sorted_det[mid] if len(sorted_det) % 2 else
            (sorted_det[mid - 1] + sorted_det[mid]) / 2, 1
        )

    # Recent trend — compare last 3 years' approval rates
    current_year = date.today().year
    trend_years = [current_year - 3, current_year - 2, current_year - 1]
    trend_data = []
    for y in trend_years:
        ya = yearly_approved.get(y, 0)
        yr = yearly_refused.get(y, 0)
        yt = ya + yr
        rate = round(ya / yt, 3) if yt > 0 else None
        trend_data.append({"year": y, "approved": ya, "refused": yr, "total": yt, "rate": rate})

    # Determine trend direction
    rates_with_data = [t["rate"] for t in trend_data if t["rate"] is not None]
    trend_direction = "stable"
    if len(rates_with_data) >= 2:
        if rates_with_data[-1] > rates_with_data[0] + 0.05:
            trend_direction = "improving"
        elif rates_with_data[-1] < rates_with_data[0] - 0.05:
            trend_direction = "declining"

    # Primary planning authority
    primary_authority = max(authorities, key=authorities.get) if authorities else None

    return {
        "overall_approval_rate": overall_approval_rate,
        "solar_approval_rate": solar_approval_rate,
        "total_decided": all_total_decided,
        "solar_decided": solar_total_decided,
        "approved": all_approved,
        "refused": all_refused,
        "solar_approved": solar_approved,
        "solar_refused": solar_refused,
        "avg_determination_months": avg_determination_months,
        "median_determination_months": median_determination_months,
        "determination_sample_size": len(determination_times),
        "cumulative_capacity_5km_mw": round(capacity_5km, 1),
        "cumulative_capacity_10km_mw": round(capacity_10km, 1),
        "trend": {
            "direction": trend_direction,
            "years": trend_data,
        },
        "planning_authority": primary_authority,
        "authorities_in_area": dict(sorted(authorities.items(), key=lambda x: -x[1])),
    }


# ---------------------------------------------------------------------------
# 4. Planning risk assessment
# ---------------------------------------------------------------------------

def _assess_planning_risk(
    stats: dict,
    repd_projects: list[dict],
    pdg_results: list[dict],
) -> dict:
    """
    Assess planning risk based on approval rates, nearby refusals,
    and environmental constraints.

    Returns:
      risk_level: HIGH / MEDIUM / LOW
      risk_score: 0-100 (higher = riskier)
      factors: list of contributing factors
    """
    score = 0
    factors: list[dict] = []

    # --- Factor 1: Approval rate ---
    approval_rate = stats.get("solar_approval_rate") or stats.get("overall_approval_rate")
    if approval_rate is not None:
        if approval_rate < 0.60:
            score += 30
            factors.append({
                "factor": "low_approval_rate",
                "description": f"Solar/RE approval rate is {approval_rate:.0%} (below 60%)",
                "impact": "high",
                "score_contribution": 30,
            })
        elif approval_rate < 0.80:
            score += 15
            factors.append({
                "factor": "moderate_approval_rate",
                "description": f"Solar/RE approval rate is {approval_rate:.0%} (60-80%)",
                "impact": "medium",
                "score_contribution": 15,
            })
        else:
            factors.append({
                "factor": "good_approval_rate",
                "description": f"Solar/RE approval rate is {approval_rate:.0%} (above 80%)",
                "impact": "positive",
                "score_contribution": 0,
            })
    else:
        score += 10
        factors.append({
            "factor": "no_precedent",
            "description": "No decided solar/RE applications found nearby — no local precedent",
            "impact": "medium",
            "score_contribution": 10,
        })

    # --- Factor 2: Nearby refusals ---
    nearby_refusals = [
        p for p in repd_projects
        if p.get("status") in REFUSED_STATUSES and p.get("distance_km", 999) <= 5
    ]
    if len(nearby_refusals) >= 3:
        score += 25
        factors.append({
            "factor": "multiple_refusals",
            "description": f"{len(nearby_refusals)} refused projects within 5 km",
            "impact": "high",
            "score_contribution": 25,
        })
    elif len(nearby_refusals) >= 1:
        score += 10
        factors.append({
            "factor": "some_refusals",
            "description": f"{len(nearby_refusals)} refused project(s) within 5 km",
            "impact": "medium",
            "score_contribution": 10,
        })

    # --- Factor 3: Existing precedent (positive) ---
    nearby_operational = [
        p for p in repd_projects
        if p.get("status") in ("Operational", "Under Construction")
        and p.get("distance_km", 999) <= 5
        and "solar" in p.get("technology", "").lower()
    ]
    if nearby_operational:
        score -= 10
        factors.append({
            "factor": "solar_precedent",
            "description": f"{len(nearby_operational)} operational/under-construction solar project(s) within 5 km",
            "impact": "positive",
            "score_contribution": -10,
        })

    # --- Factor 4: Determination time ---
    avg_det = stats.get("avg_determination_months")
    if avg_det and avg_det > 18:
        score += 10
        factors.append({
            "factor": "slow_determination",
            "description": f"Average determination time is {avg_det:.0f} months (above 18)",
            "impact": "medium",
            "score_contribution": 10,
        })

    # --- Factor 5: Trend direction ---
    trend = stats.get("trend", {}).get("direction", "stable")
    if trend == "declining":
        score += 10
        factors.append({
            "factor": "declining_approvals",
            "description": "Approval rate trending downward over last 3 years",
            "impact": "medium",
            "score_contribution": 10,
        })
    elif trend == "improving":
        score -= 5
        factors.append({
            "factor": "improving_approvals",
            "description": "Approval rate trending upward over last 3 years",
            "impact": "positive",
            "score_contribution": -5,
        })

    # --- Factor 6: Cumulative capacity saturation ---
    cum_5km = stats.get("cumulative_capacity_5km_mw", 0)
    if cum_5km > 200:
        score += 15
        factors.append({
            "factor": "capacity_saturation",
            "description": f"{cum_5km:.0f} MW already approved within 5 km — cumulative impact concerns",
            "impact": "high",
            "score_contribution": 15,
        })
    elif cum_5km > 50:
        score += 5
        factors.append({
            "factor": "moderate_capacity",
            "description": f"{cum_5km:.0f} MW approved within 5 km",
            "impact": "low",
            "score_contribution": 5,
        })

    # --- Factor 7: planning.data.gov.uk constraints ---
    constraint_count = 0
    for pdg in pdg_results:
        desc = (pdg.get("description") or pdg.get("name") or "").lower()
        if any(kw in desc for kw in ("aonb", "area of outstanding", "national landscape")):
            score += 25
            constraint_count += 1
            factors.append({
                "factor": "aonb",
                "description": "Site is within or near an AONB / National Landscape",
                "impact": "high",
                "score_contribution": 25,
            })
        elif any(kw in desc for kw in ("green belt", "greenbelt")):
            score += 30
            constraint_count += 1
            factors.append({
                "factor": "green_belt",
                "description": "Site is within or near Green Belt land",
                "impact": "high",
                "score_contribution": 30,
            })
        elif any(kw in desc for kw in ("conservation area", "listed building", "scheduled monument")):
            score += 15
            constraint_count += 1
            factors.append({
                "factor": "heritage_constraint",
                "description": f"Heritage designation nearby: {pdg.get('name', '')}",
                "impact": "medium",
                "score_contribution": 15,
            })
        if constraint_count >= 3:
            break  # cap constraint penalties

    # Clamp score
    score = max(0, min(100, score))

    # Determine risk level
    if score >= 50:
        risk_level = "HIGH"
    elif score >= 25:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Build recommendation
    if risk_level == "HIGH":
        recommendation = (
            "High planning risk. Multiple adverse factors identified. "
            "Consider pre-application consultation with the LPA, "
            "commission a Landscape & Visual Impact Assessment, "
            "and review refusal reasons for nearby rejected applications."
        )
    elif risk_level == "MEDIUM":
        recommendation = (
            "Moderate planning risk. Some constraints present but manageable. "
            "Pre-application advice recommended. Review local plan policies "
            "for renewable energy and check for any neighbourhood plan restrictions."
        )
    else:
        recommendation = (
            "Low planning risk. Good local precedent with high approval rates. "
            "Ensure standard EIA screening, BNG assessment, and glint/glare "
            "study are prepared to support a robust application."
        )

    return {
        "risk_level": risk_level,
        "risk_score": score,
        "factors": sorted(factors, key=lambda f: -abs(f["score_contribution"])),
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# 5. Main entry point
# ---------------------------------------------------------------------------

async def get_planning_history(
    pool,
    lat: float,
    lon: float,
    radius_km: float = 10,
) -> dict:
    """
    Comprehensive per-parcel planning history lookup.

    Combines:
    - planning.data.gov.uk entity queries
    - REPD database (PostGIS) for renewable energy projects
    - Derived statistics (approval rates, determination times, trends)
    - Planning risk assessment

    Args:
        pool: asyncpg connection pool
        lat: site latitude (WGS84)
        lon: site longitude (WGS84)
        radius_km: search radius in km (default 10)

    Returns:
        dict with keys: planning_data_gov, repd_projects, statistics,
                        risk_assessment, summary
    """
    # Run API query and DB query concurrently
    pdg_results, repd_projects = await asyncio.gather(
        _query_planning_data_gov(lat, lon, radius_km),
        _query_repd(pool, lat, lon, radius_km),
    )

    # Compute statistics from REPD data
    statistics = _compute_planning_stats(repd_projects, lat, lon)

    # Assess risk
    risk_assessment = _assess_planning_risk(statistics, repd_projects, pdg_results)

    # Nearest projects for quick reference
    nearest_solar = [
        p for p in repd_projects
        if "solar" in p.get("technology", "").lower()
    ][:5]
    nearest_any = repd_projects[:5]

    # Technology breakdown within radius
    tech_breakdown: dict[str, dict] = {}
    for p in repd_projects:
        tech = p.get("technology", "Unknown")
        if tech not in tech_breakdown:
            tech_breakdown[tech] = {"count": 0, "total_mw": 0.0, "approved": 0, "refused": 0}
        tech_breakdown[tech]["count"] += 1
        tech_breakdown[tech]["total_mw"] += p.get("capacity_mw", 0)
        if p.get("status") in APPROVED_STATUSES:
            tech_breakdown[tech]["approved"] += 1
        elif p.get("status") in REFUSED_STATUSES:
            tech_breakdown[tech]["refused"] += 1

    for tech in tech_breakdown:
        tech_breakdown[tech]["total_mw"] = round(tech_breakdown[tech]["total_mw"], 1)

    return {
        "centre": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "planning_data_gov": {
            "count": len(pdg_results),
            "results": pdg_results[:50],  # cap to avoid huge payloads
            "note": "Sourced from planning.data.gov.uk national planning dataset",
        },
        "repd_projects": {
            "count": len(repd_projects),
            "projects": repd_projects[:100],
            "nearest_solar": nearest_solar,
            "nearest_any": nearest_any,
            "technology_breakdown": dict(
                sorted(tech_breakdown.items(), key=lambda x: -x[1]["count"])
            ),
        },
        "statistics": statistics,
        "risk_assessment": risk_assessment,
        "summary": {
            "total_repd_projects": len(repd_projects),
            "total_pdg_entities": len(pdg_results),
            "solar_approval_rate": statistics.get("solar_approval_rate"),
            "overall_approval_rate": statistics.get("overall_approval_rate"),
            "avg_determination_months": statistics.get("avg_determination_months"),
            "cumulative_capacity_5km_mw": statistics.get("cumulative_capacity_5km_mw"),
            "cumulative_capacity_10km_mw": statistics.get("cumulative_capacity_10km_mw"),
            "risk_level": risk_assessment["risk_level"],
            "risk_score": risk_assessment["risk_score"],
            "planning_authority": statistics.get("planning_authority"),
            "trend": statistics.get("trend", {}).get("direction"),
        },
    }
