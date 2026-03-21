"""
Planning risk scorer — automated screening of UK planning constraints.

Queries real data sources to identify constraints:
- REPD historical outcomes (13,995 projects with approval/refusal status)
- Proximity to residential areas (OSM buildings, Open Buildings)
- Agricultural Land Classification (BMV restrictions)
- Grid connection feasibility (queue depth, headroom)
- Environmental designations (approximated from known UK protected areas)

Returns a composite risk score (0-100) with specific risk factors.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("princeps.planning_risk_scorer")

# ---------------------------------------------------------------------------
# Technology-specific base risk adjustments
# ---------------------------------------------------------------------------

_TECH_BASE_RISK = {
    "solar": 10,
    "solar_pv": 10,
    "wind": 25,
    "wind_onshore": 25,
    "battery": 5,
    "bess": 5,
    "hydrogen": 15,
}

# Green belt multiplier — solar on green belt is near-certain refusal
_GREEN_BELT_PENALTY = {
    "solar": 40,
    "solar_pv": 40,
    "wind": 35,
    "wind_onshore": 35,
    "battery": 15,
    "bess": 15,
}

# Known UK protected area approximate bounding boxes (lat_min, lat_max, lon_min, lon_max)
# These are rough centroids+radii for major AONBs / National Parks
_PROTECTED_AREAS = [
    {"name": "Lake District NP", "lat": 54.47, "lon": -3.08, "radius_km": 30},
    {"name": "Peak District NP", "lat": 53.35, "lon": -1.80, "radius_km": 25},
    {"name": "Snowdonia NP", "lat": 52.90, "lon": -3.90, "radius_km": 25},
    {"name": "Yorkshire Dales NP", "lat": 54.25, "lon": -2.15, "radius_km": 25},
    {"name": "North York Moors NP", "lat": 54.37, "lon": -0.95, "radius_km": 20},
    {"name": "Dartmoor NP", "lat": 50.57, "lon": -3.92, "radius_km": 18},
    {"name": "Exmoor NP", "lat": 51.15, "lon": -3.60, "radius_km": 15},
    {"name": "New Forest NP", "lat": 50.87, "lon": -1.60, "radius_km": 15},
    {"name": "South Downs NP", "lat": 50.95, "lon": -0.50, "radius_km": 30},
    {"name": "Broads NP", "lat": 52.60, "lon": 1.55, "radius_km": 15},
    {"name": "Cotswolds AONB", "lat": 51.85, "lon": -1.75, "radius_km": 30},
    {"name": "Chilterns AONB", "lat": 51.70, "lon": -0.75, "radius_km": 20},
    {"name": "Surrey Hills AONB", "lat": 51.22, "lon": -0.45, "radius_km": 15},
    {"name": "Cornwall AONB", "lat": 50.35, "lon": -5.05, "radius_km": 15},
    {"name": "Northumberland NP", "lat": 55.30, "lon": -2.20, "radius_km": 25},
    {"name": "Brecon Beacons NP", "lat": 51.88, "lon": -3.43, "radius_km": 20},
    {"name": "Pembrokeshire Coast NP", "lat": 51.80, "lon": -5.05, "radius_km": 15},
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km between two WGS84 points."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _check_protected_areas(lat: float, lon: float) -> list[dict]:
    """Check if location falls within or near known protected areas."""
    hits = []
    for area in _PROTECTED_AREAS:
        dist = _haversine_km(lat, lon, area["lat"], area["lon"])
        if dist < area["radius_km"]:
            hits.append({
                "name": area["name"],
                "distance_km": round(dist, 1),
                "inside": dist < area["radius_km"] * 0.7,
            })
        elif dist < area["radius_km"] + 5:
            hits.append({
                "name": area["name"],
                "distance_km": round(dist, 1),
                "inside": False,
            })
    return hits


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

async def score_planning_risk(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict[str, Any]:
    """
    Score planning risk for a proposed energy development site.

    Args:
        pool: asyncpg connection pool
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        capacity_mw: Proposed capacity in MW
        technology: One of solar, wind, battery, bess, hydrogen

    Returns:
        Dict with risk_score (0-100), risk_level, verdict, factors,
        local_outcomes, and recommendations.
    """
    factors: list[dict] = []
    recommendations: list[str] = []
    local_outcomes: dict[str, int] = {}

    async with pool.acquire() as conn:
        # ── 1. REPD outcome analysis (10km radius) ──────────────────────
        repd_factor = await _score_repd_outcomes(conn, lat, lon, technology)
        factors.append(repd_factor["factor"])
        local_outcomes = repd_factor.get("outcomes", {})
        recommendations.extend(repd_factor.get("recommendations", []))

        # ── 2. Building / residential proximity ─────────────────────────
        prox_factor = await _score_building_proximity(conn, lat, lon, technology)
        factors.append(prox_factor["factor"])
        recommendations.extend(prox_factor.get("recommendations", []))

        # ── 3. Agricultural Land Classification ─────────────────────────
        alc_factor = await _score_alc(lat, lon)
        factors.append(alc_factor["factor"])
        recommendations.extend(alc_factor.get("recommendations", []))

        # ── 4. Grid queue congestion ────────────────────────────────────
        queue_factor = await _score_grid_queue(conn, lat, lon, capacity_mw)
        factors.append(queue_factor["factor"])
        recommendations.extend(queue_factor.get("recommendations", []))

        # ── 5. Environmental designations ───────────────────────────────
        env_factor = _score_environmental(lat, lon, technology)
        factors.append(env_factor["factor"])
        recommendations.extend(env_factor.get("recommendations", []))

        # ── 6. Technology + scale risk ──────────────────────────────────
        tech_factor = _score_technology_risk(technology, capacity_mw)
        factors.append(tech_factor["factor"])
        recommendations.extend(tech_factor.get("recommendations", []))

    # Composite: weighted average of factor scores
    weights = {
        "Local approval rate": 0.25,
        "Residential proximity": 0.20,
        "Agricultural land": 0.15,
        "Grid congestion": 0.15,
        "Environmental designations": 0.15,
        "Technology & scale": 0.10,
    }
    risk_score = 0.0
    for f in factors:
        w = weights.get(f["name"], 0.10)
        risk_score += f["score"] * w
    risk_score = min(100, max(0, round(risk_score)))

    # Determine level and verdict
    if risk_score <= 20:
        risk_level, verdict = "low", "GO"
    elif risk_score <= 45:
        risk_level, verdict = "medium", "CAUTION"
    elif risk_score <= 70:
        risk_level, verdict = "high", "CAUTION"
    else:
        risk_level, verdict = "very_high", "NO-GO"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "verdict": verdict,
        "factors": factors,
        "local_outcomes": local_outcomes,
        "recommendations": recommendations[:6],  # cap at 6
        "location": {"lat": lat, "lon": lon},
        "capacity_mw": capacity_mw,
        "technology": technology,
    }


# ---------------------------------------------------------------------------
# Individual factor scorers
# ---------------------------------------------------------------------------

async def _score_repd_outcomes(
    conn, lat: float, lon: float, technology: str,
) -> dict[str, Any]:
    """Query REPD projects within 10km, calculate local approval rate."""
    try:
        rows = await conn.fetch("""
            SELECT dev_status_short, COUNT(*) AS cnt,
                   AVG(installed_capacity_mw) AS avg_mw
            FROM repd_project
            WHERE ST_DWithin(
                geometry::geography,
                ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                10000
            )
            GROUP BY dev_status_short
        """, lon, lat)

        outcomes: dict[str, int] = {}
        total = 0
        approved = 0  # operational + construction + consented
        refused = 0
        withdrawn = 0

        for r in rows:
            status = (r["dev_status_short"] or "").lower().strip()
            count = int(r["cnt"])
            outcomes[status] = count
            total += count

            if status in ("operational", "under construction", "consented", "awaiting construction"):
                approved += count
            elif status in ("refused", "appeal refused"):
                refused += count
            elif status in ("withdrawn", "abandoned"):
                withdrawn += count

        if total == 0:
            return {
                "factor": {
                    "name": "Local approval rate",
                    "score": 30,
                    "detail": "No REPD projects within 10km — limited local precedent",
                },
                "outcomes": {},
                "recommendations": ["Consider pre-application engagement as this is an untested area"],
            }

        approval_rate = approved / total if total > 0 else 0
        refusal_rate = refused / total if total > 0 else 0

        # Score: high approval rate = low risk
        if approval_rate >= 0.80:
            score = 10
        elif approval_rate >= 0.65:
            score = 25
        elif approval_rate >= 0.50:
            score = 45
        elif approval_rate >= 0.35:
            score = 60
        else:
            score = 80

        # Adjust for high refusal rate
        if refusal_rate > 0.30:
            score = min(100, score + 15)

        detail = f"{approval_rate:.0%} of {total} nearby projects approved"
        if refused > 0:
            detail += f" ({refused} refused)"

        recs = []
        if refusal_rate > 0.20:
            recs.append("Review refusal reasons for nearby projects before proceeding")
        if total < 5:
            recs.append("Limited local precedent — consider early community engagement")

        return {
            "factor": {"name": "Local approval rate", "score": score, "detail": detail},
            "outcomes": outcomes,
            "recommendations": recs,
        }

    except Exception as e:
        log.warning("REPD query failed: %s", e)
        return {
            "factor": {
                "name": "Local approval rate",
                "score": 30,
                "detail": "Could not query REPD data",
            },
            "outcomes": {},
            "recommendations": [],
        }


async def _score_building_proximity(
    conn, lat: float, lon: float, technology: str,
) -> dict[str, Any]:
    """Check proximity to buildings / substations as residential density proxy."""
    try:
        # Use grid_substations as a proxy for built-up areas (substations near houses)
        # Also query REPD for existing energy sites (indicates industrial land use)
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (
                    WHERE ST_DWithin(
                        geom,
                        ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700),
                        500
                    )
                ) AS subs_500m,
                COUNT(*) FILTER (
                    WHERE ST_DWithin(
                        geom,
                        ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700),
                        2000
                    )
                ) AS subs_2km
            FROM grid_substations
        """, lon, lat)

        subs_500m = int(row["subs_500m"]) if row else 0
        subs_2km = int(row["subs_2km"]) if row else 0

        # Also check for nearby REPD projects (existing energy = more receptive area)
        existing_row = await conn.fetchrow("""
            SELECT COUNT(*) AS cnt
            FROM repd_project
            WHERE ST_DWithin(
                geometry::geography,
                ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                2000
            )
            AND dev_status_short IN ('Operational', 'Under Construction')
        """, lon, lat)
        existing_nearby = int(existing_row["cnt"]) if existing_row else 0

        # Score based on density (more substations = more built-up = more objections)
        if subs_500m >= 3:
            score = 70
            detail = f"Dense built-up area ({subs_500m} substations within 500m)"
        elif subs_500m >= 1:
            score = 50
            detail = f"Near built-up area ({subs_500m} substations within 500m)"
        elif subs_2km >= 5:
            score = 40
            detail = f"Suburban fringe ({subs_2km} substations within 2km)"
        elif subs_2km >= 2:
            score = 25
            detail = f"Semi-rural ({subs_2km} substations within 2km)"
        else:
            score = 10
            detail = "Rural location — minimal residential proximity risk"

        # Wind turbines get extra penalty near buildings
        if technology in ("wind", "wind_onshore") and subs_500m >= 1:
            score = min(100, score + 20)
            detail += " (wind turbines face heightened objection risk)"

        # Reduce risk if existing energy projects nearby (area already hosting renewables)
        if existing_nearby >= 2:
            score = max(0, score - 10)
            detail += f" — {existing_nearby} existing energy projects nearby"

        recs = []
        if score >= 40:
            recs.append("Consider visual screening and landscape mitigation")
        if score >= 60:
            recs.append("Pre-application consultation with local community strongly advised")

        return {
            "factor": {"name": "Residential proximity", "score": score, "detail": detail},
            "recommendations": recs,
        }

    except Exception as e:
        log.warning("Building proximity query failed: %s", e)
        return {
            "factor": {
                "name": "Residential proximity",
                "score": 30,
                "detail": "Could not assess residential proximity",
            },
            "recommendations": [],
        }


async def _score_alc(lat: float, lon: float) -> dict[str, Any]:
    """Agricultural Land Classification check."""
    from utils.land_registry import get_agricultural_land_class

    alc = await get_agricultural_land_class(lat, lon)
    grade = alc.get("grade", "unknown")
    suitable = alc.get("suitable_for_development", True)

    if grade in ("1", "2"):
        score = 75
        detail = f"Grade {grade} — Best and Most Versatile land, strong planning restriction"
        recs = ["BMV land strongly resisted by LPAs for energy development",
                "NPPF requires demonstration of no alternative non-BMV sites"]
    elif grade == "3a":
        score = 50
        detail = f"Grade {grade} — Good quality agricultural land (BMV), moderate restriction"
        recs = ["Grade 3a is BMV — may need agricultural land assessment"]
    elif grade == "3b":
        score = 15
        detail = f"Grade {grade} — Non-BMV, suitable for development"
        recs = []
    elif grade in ("4", "5"):
        score = 5
        detail = f"Grade {grade} — Low agricultural value, minimal planning concern"
        recs = []
    else:
        score = 25
        detail = f"Grade {grade} — classification uncertain"
        recs = ["Commission Agricultural Land Classification survey to confirm grade"]

    return {
        "factor": {"name": "Agricultural land", "score": score, "detail": detail},
        "recommendations": recs,
    }


async def _score_grid_queue(
    conn, lat: float, lon: float, capacity_mw: float,
) -> dict[str, Any]:
    """Check queue congestion at nearest substation."""
    try:
        # Find nearest substation with ECR data
        row = await conn.fetchrow("""
            SELECT s.id, s.name, s.voltage_kv,
                   s.gen_headroom_mw,
                   ST_Distance(
                       s.geom,
                       ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700)
                   ) / 1000.0 AS dist_km
            FROM grid_substations s
            WHERE s.voltage_kv >= 33
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700)
            LIMIT 1
        """, lon, lat)

        if not row:
            return {
                "factor": {
                    "name": "Grid congestion",
                    "score": 40,
                    "detail": "No substation data available nearby",
                },
                "recommendations": ["Request formal grid capacity study from DNO"],
            }

        sub_id = row["id"]
        sub_name = row["name"] or "Unknown"
        dist_km = float(row["dist_km"])
        headroom = float(row["gen_headroom_mw"]) if row["gen_headroom_mw"] else None

        # Check ECR queue at this substation
        ecr_row = await conn.fetchrow("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE status ILIKE '%%queue%%'
                       OR status ILIKE '%%accepted%%'
                       OR status ILIKE '%%pending%%'
                ) AS queued,
                COALESCE(SUM(capacity_mw) FILTER (
                    WHERE status ILIKE '%%queue%%'
                       OR status ILIKE '%%accepted%%'
                       OR status ILIKE '%%pending%%'
                ), 0) AS queued_mw
            FROM grid_ecr
            WHERE substation_id = $1
        """, sub_id)

        queued = int(ecr_row["queued"]) if ecr_row else 0
        queued_mw = float(ecr_row["queued_mw"]) if ecr_row else 0

        # Score based on queue depth and headroom
        score = 10  # base
        detail_parts = []

        if queued >= 20:
            score += 40
            detail_parts.append(f"{queued} projects queued ({queued_mw:.0f} MW)")
        elif queued >= 10:
            score += 25
            detail_parts.append(f"{queued} projects queued ({queued_mw:.0f} MW)")
        elif queued >= 5:
            score += 15
            detail_parts.append(f"{queued} projects queued ({queued_mw:.0f} MW)")
        elif queued > 0:
            detail_parts.append(f"{queued} projects queued ({queued_mw:.0f} MW)")
        else:
            detail_parts.append("No queue at nearest substation")

        if headroom is not None:
            if headroom < capacity_mw:
                score += 25
                detail_parts.append(f"insufficient headroom ({headroom:.1f} MW vs {capacity_mw:.1f} MW needed)")
            elif headroom < capacity_mw * 2:
                score += 10
                detail_parts.append(f"tight headroom ({headroom:.1f} MW available)")
            else:
                detail_parts.append(f"{headroom:.1f} MW headroom available")

        detail = f"At {sub_name} ({dist_km:.1f} km): " + ", ".join(detail_parts)
        score = min(100, score)

        recs = []
        if queued >= 10:
            recs.append("High queue depth may extend connection timeline by 2-5 years")
        if headroom is not None and headroom < capacity_mw:
            recs.append("Insufficient headroom — may need grid reinforcement or flexible connection")
        if dist_km > 10:
            recs.append(f"Substation is {dist_km:.1f} km away — connection cost will be significant")

        return {
            "factor": {"name": "Grid congestion", "score": score, "detail": detail},
            "recommendations": recs,
        }

    except Exception as e:
        log.warning("Grid queue query failed: %s", e)
        return {
            "factor": {
                "name": "Grid congestion",
                "score": 30,
                "detail": "Could not assess grid congestion",
            },
            "recommendations": [],
        }


def _score_environmental(lat: float, lon: float, technology: str) -> dict[str, Any]:
    """Check environmental designations (AONB, National Park, etc.)."""
    hits = _check_protected_areas(lat, lon)

    if not hits:
        return {
            "factor": {
                "name": "Environmental designations",
                "score": 5,
                "detail": "No known protected areas nearby",
            },
            "recommendations": [],
        }

    inside = [h for h in hits if h["inside"]]
    nearby = [h for h in hits if not h["inside"]]

    if inside:
        names = ", ".join(h["name"] for h in inside)
        score = 85
        detail = f"Inside protected area: {names}"
        recs = [
            f"Site is within {inside[0]['name']} — major projects face exceptional scrutiny",
            "National policy strongly resists major development in designated landscapes",
        ]
    elif nearby:
        closest = min(nearby, key=lambda h: h["distance_km"])
        score = 40
        detail = f"Near {closest['name']} ({closest['distance_km']} km from boundary)"
        recs = ["Landscape and Visual Impact Assessment (LVIA) recommended"]
    else:
        score = 5
        detail = "No significant environmental designations"
        recs = []

    # Wind turbines in/near AONBs are particularly contentious
    if technology in ("wind", "wind_onshore") and (inside or nearby):
        score = min(100, score + 15)
        recs.append("Wind turbines in or near designated landscapes face very high refusal rates")

    return {
        "factor": {"name": "Environmental designations", "score": score, "detail": detail},
        "recommendations": recs,
    }


def _score_technology_risk(technology: str, capacity_mw: float) -> dict[str, Any]:
    """Technology and scale specific planning risk."""
    base = _TECH_BASE_RISK.get(technology, 15)
    score = base

    # Scale penalty — larger sites attract more scrutiny
    if capacity_mw > 50:
        score += 20
        scale_note = "NSIP threshold (>50MW) — requires Development Consent Order"
    elif capacity_mw > 25:
        score += 10
        scale_note = "Large scale — heightened scrutiny expected"
    elif capacity_mw > 5:
        score += 5
        scale_note = "Utility scale"
    else:
        scale_note = "Small to medium scale"

    detail = f"{technology.replace('_', ' ').title()} at {capacity_mw:.1f} MW — {scale_note}"

    recs = []
    if capacity_mw > 50:
        recs.append("NSIP process applies — 12-18 month examination expected")
    if technology in ("wind", "wind_onshore"):
        recs.append("Ministerial Written Statement requires community backing for onshore wind")

    score = min(100, score)

    return {
        "factor": {"name": "Technology & scale", "score": score, "detail": detail},
        "recommendations": recs,
    }
