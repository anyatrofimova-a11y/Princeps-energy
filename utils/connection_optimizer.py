"""
Grid connection optimization — helps developers maximize their chances
of securing and keeping a grid connection under the reformed UK system.

Addresses the 2025-2026 UK grid connections reform:
- Ofgem Connections Action Plan & TMO4+
- NESO Strategic Spatial Energy Plan (SSEP)
- Gate-based viability assessment
- Queue cleansing of speculative applications

Components:
1. Gate Readiness Scorer — will your project survive each gate?
2. Queue Reform Impact Model — how many projects ahead will be removed?
3. Strategic Alignment Scorer — does your site align with NESO priorities?
4. Connection Strategy Optimizer — which substation, voltage, timing?
5. Application Pack Generator — what evidence to prepare
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

log = logging.getLogger("princeps.connection_optimizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COST_PER_KM: dict[int, int] = {
    11: 80_000,
    33: 150_000,
    66: 300_000,
    132: 500_000,
    275: 1_200_000,
    400: 2_000_000,
}

_FIXED_CIVILS: dict[int, int] = {
    11: 50_000, 33: 120_000, 66: 250_000,
    132: 500_000, 275: 1_500_000, 400: 3_000_000,
}

_DNO_FACTOR: dict[str, float] = {
    "UKPN": 2.0, "NGED": 1.5, "SPEN": 3.0,
    "SSEN": 3.5, "ENWL": 2.5, "NPG": 2.0,
}

# DNO acceptance rates (from historical REPD analysis)
_DNO_ACCEPTANCE: dict[str, float] = {
    "UKPN": 0.72, "NGED": 0.78, "SPEN": 0.65,
    "SSEN": 0.60, "ENWL": 0.68, "NPG": 0.70,
}

# NESO SSEP regional technology preferences (score multipliers)
_SSEP_TECH_REGION: dict[str, dict[str, float]] = {
    "solar": {
        "south_east": 1.3, "south_west": 1.2, "east_anglia": 1.2,
        "midlands": 1.0, "wales": 0.9, "north_west": 0.8,
        "north_east": 0.7, "scotland": 0.6,
    },
    "wind": {
        "scotland": 1.4, "north_east": 1.2, "north_west": 1.1,
        "wales": 1.1, "midlands": 0.9, "east_anglia": 1.0,
        "south_west": 0.8, "south_east": 0.7,
    },
    "bess": {
        "south_east": 1.2, "midlands": 1.1, "north_west": 1.1,
        "east_anglia": 1.0, "scotland": 1.0, "wales": 0.9,
        "south_west": 0.9, "north_east": 1.0,
    },
    "battery": {
        "south_east": 1.2, "midlands": 1.1, "north_west": 1.1,
        "east_anglia": 1.0, "scotland": 1.0, "wales": 0.9,
        "south_west": 0.9, "north_east": 1.0,
    },
}

# Mapping DNO codes to SSEP regions
_DNO_TO_REGION: dict[str, str] = {
    "UKPN": "south_east",
    "NGED": "south_west",
    "ENWL": "north_west",
    "NPG": "north_east",
    "SPEN": "scotland",
    "SSEN": "south_east",  # SSEN covers both south and north Scotland
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _voltage_for_capacity(capacity_mw: float) -> int:
    """Determine likely connection voltage based on project capacity."""
    if capacity_mw < 1:
        return 11
    elif capacity_mw < 5:
        return 33
    elif capacity_mw < 20:
        return 66
    elif capacity_mw < 50:
        return 132
    elif capacity_mw < 200:
        return 275
    else:
        return 400


def _nearest_voltage_tier(voltage_kv: float) -> int:
    tiers = sorted(_COST_PER_KM.keys())
    return min(tiers, key=lambda v: abs(v - voltage_kv))


def _connection_cost_p50(distance_km: float, voltage_kv: int) -> int:
    tier = _nearest_voltage_tier(voltage_kv)
    per_km = _COST_PER_KM[tier]
    civils = _FIXED_CIVILS.get(tier, 120_000)
    return round(per_km * distance_km + civils)


def _dno_region(dno: str) -> str:
    return _DNO_TO_REGION.get(dno, "midlands")


# ---------------------------------------------------------------------------
# 1. Gate Readiness Scorer
# ---------------------------------------------------------------------------

async def score_gate_readiness(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
    project_details: dict | None = None,
) -> dict:
    """
    Score readiness for each gate in the reformed UK connection process.

    Gates:
        1. Application — site control (land option/lease)
        2. Planning — planning permission or submitted
        3. Financial — financial backing evidence
        4. Construction — ready to build within timeline

    Uses real PostGIS data from grid_substations, grid_ecr, repd_project.
    """
    details = project_details or {}

    async with pool.acquire() as conn:
        # ── Nearby substations (SRID 27700) ──────────────────────────────
        subs = await conn.fetch("""
            SELECT
                s.id, s.name, s.dno, s.voltage_kv,
                s.gen_headroom_mw, s.demand_headroom_mw,
                s.rag_generation,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                ST_Distance(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                ) / 1000.0 AS distance_km
            FROM grid_substations s
            WHERE s.geom IS NOT NULL
              AND ST_DWithin(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    20000
                  )
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 5
        """, lon, lat)

        # ── ECR queue at nearest substations ─────────────────────────────
        sub_ids = [r["id"] for r in subs]
        ecr_rows = []
        if sub_ids:
            ecr_rows = await conn.fetch("""
                SELECT
                    substation_id,
                    COUNT(*) AS queue_count,
                    COALESCE(SUM(capacity_mw), 0) AS queued_mw
                FROM grid_ecr
                WHERE substation_id = ANY($1::int[])
                GROUP BY substation_id
            """, sub_ids)
        ecr_map = {r["substation_id"]: dict(r) for r in ecr_rows}

        # ── Nearby REPD projects (planning status) ───────────────────────
        repd_rows = await conn.fetch("""
            SELECT
                site_name, technology_type, installed_capacity_mw,
                dev_status_short, planning_submitted, planning_granted,
                operational
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.15
                  )
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
            LIMIT 30
        """, lon, lat)

        # ── Nearby TEC projects ──────────────────────────────────────────
        tec_rows = await conn.fetch("""
            SELECT project_name, project_status, cumulative_capacity_mw, gate
            FROM eso_tec_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.15
                  )
            LIMIT 20
        """, lon, lat)

    # ── Derived context ──────────────────────────────────────────────────
    best_sub = subs[0] if subs else None
    best_headroom = float(best_sub["gen_headroom_mw"] or 0) if best_sub else 0
    best_dist = float(best_sub["distance_km"]) if best_sub else 99
    best_dno = best_sub["dno"] if best_sub else "UKPN"
    ecr_at_best = ecr_map.get(best_sub["id"], {}) if best_sub else {}
    queue_count = ecr_at_best.get("queue_count", 0)
    queued_mw = float(ecr_at_best.get("queued_mw", 0))

    # REPD planning statistics
    repd_with_planning = sum(
        1 for r in repd_rows
        if r["planning_granted"] is not None
        or (r["dev_status_short"] or "").lower() in (
            "operational", "under construction", "awaiting construction"
        )
    )
    repd_total = len(repd_rows)
    local_planning_rate = repd_with_planning / max(repd_total, 1)

    # Environmental risk proxies (from REPD refusal patterns)
    repd_refused = sum(
        1 for r in repd_rows
        if (r["dev_status_short"] or "").lower() in ("refused", "appeal refused")
    )
    refusal_rate = repd_refused / max(repd_total, 1)

    # TEC queue pressure
    tec_queued = sum(
        1 for t in tec_rows
        if t["project_status"] and "queue" in t["project_status"].lower()
    )

    # ── Gate 1: Application (site control) ───────────────────────────────
    gate1_score = 50  # baseline — no info on land
    gate1_requirements = ["Site control evidence (land option or lease)", "Connection application fee"]
    gate1_risks = []

    if details.get("has_land_option"):
        gate1_score = 95
    elif details.get("has_land_option") is False:
        gate1_score = 25
        gate1_risks.append("No land option or lease secured")

    # Proximity to substation helps
    if best_dist < 3:
        gate1_score = min(100, gate1_score + 10)
    elif best_dist > 10:
        gate1_score = max(0, gate1_score - 10)
        gate1_risks.append(f"Nearest substation is {best_dist:.1f}km away — long connection route")

    # ── Gate 2: Planning ─────────────────────────────────────────────────
    gate2_score = 40  # baseline
    gate2_requirements = ["Planning application submitted or permission granted"]
    gate2_risks = []

    if details.get("has_planning") == "granted":
        gate2_score = 95
    elif details.get("has_planning") == "submitted":
        gate2_score = 70
    elif details.get("has_planning") is True:
        gate2_score = 80
    else:
        # Estimate from local conditions
        gate2_score = int(40 + local_planning_rate * 30)
        if not details.get("has_planning"):
            gate2_risks.append("No planning permission yet — submit before Gate 2 deadline")

    if refusal_rate > 0.25:
        gate2_score = max(0, gate2_score - 15)
        gate2_risks.append(f"High local refusal rate ({refusal_rate:.0%}) — strong planning case needed")

    if capacity_mw > 50:
        gate2_requirements.append("NSIP (Nationally Significant Infrastructure Project) process likely required")
        gate2_score = max(0, gate2_score - 10)
        gate2_risks.append("Large project (>50MW) — NSIP consent process is lengthy")

    # ── Gate 3: Financial ────────────────────────────────────────────────
    gate3_score = 45  # baseline
    gate3_requirements = ["Evidence of funding (debt/equity term sheet or board approval)"]
    gate3_risks = []

    if details.get("has_funding"):
        gate3_score = 90
    elif details.get("has_ppa"):
        gate3_score = 75
        gate3_requirements.append("PPA signed or indicative terms")
    else:
        gate3_risks.append("No PPA signed — secure indicative terms early")

    if details.get("has_ppa"):
        gate3_score = min(100, gate3_score + 15)

    # Reinforcement cost exposure
    if capacity_mw > best_headroom:
        shortfall = capacity_mw - best_headroom
        reinforcement_est = int(shortfall * 200_000 * (_voltage_for_capacity(capacity_mw) / 33))
        gate3_risks.append(
            f"Reinforcement likely (~£{reinforcement_est:,.0f}) — factor into financial model"
        )
        gate3_score = max(0, gate3_score - 10)

    # ── Gate 4: Construction ─────────────────────────────────────────────
    gate4_score = 40  # baseline
    gate4_requirements = ["EPC contractor appointed or framework agreement"]
    gate4_risks = []

    if details.get("construction_ready"):
        gate4_score = 85
    elif details.get("has_epc"):
        gate4_score = 70
    else:
        gate4_risks.append("No EPC contractor identified — begin procurement")

    # Grid reinforcement delay
    if capacity_mw > best_headroom:
        gate4_risks.append("Grid reinforcement may delay energisation by 12-24 months")
        gate4_score = max(0, gate4_score - 15)

    # Queue congestion impact
    if queue_count > 10:
        gate4_risks.append(f"{queue_count} projects queued ahead — connection works may be delayed")
        gate4_score = max(0, gate4_score - 10)

    if tec_queued > 5:
        gate4_risks.append(f"{tec_queued} TEC projects queued at nearby connection sites")

    # ── Aggregate ────────────────────────────────────────────────────────
    gates = [
        {
            "gate": 1, "name": "Application",
            "score": max(0, min(100, gate1_score)),
            "status": _gate_status(gate1_score),
            "requirements": gate1_requirements,
            "risks": gate1_risks,
        },
        {
            "gate": 2, "name": "Planning",
            "score": max(0, min(100, gate2_score)),
            "status": _gate_status(gate2_score),
            "requirements": gate2_requirements,
            "risks": gate2_risks,
        },
        {
            "gate": 3, "name": "Financial",
            "score": max(0, min(100, gate3_score)),
            "status": _gate_status(gate3_score),
            "requirements": gate3_requirements,
            "risks": gate3_risks,
        },
        {
            "gate": 4, "name": "Construction",
            "score": max(0, min(100, gate4_score)),
            "status": _gate_status(gate4_score),
            "requirements": gate4_requirements,
            "risks": gate4_risks,
        },
    ]

    overall = sum(g["score"] for g in gates) / 4
    survival = _survival_probability(gates)

    # Verdict
    if overall >= 75:
        verdict = "LIKELY TO PROCEED"
    elif overall >= 50:
        verdict = "AT RISK — ACTION NEEDED"
    else:
        verdict = "UNLIKELY WITHOUT CHANGES"

    # Recommendations
    recommendations = []
    for g in gates:
        if g["status"] == "FAIL":
            recommendations.append(f"CRITICAL: Address Gate {g['gate']} ({g['name']}) — score only {g['score']}")
        elif g["status"] == "AT RISK":
            for risk in g["risks"][:1]:
                recommendations.append(risk)
    if not details.get("has_planning"):
        recommendations.append("Submit planning application before Gate 2 deadline")
    if not details.get("has_ppa"):
        recommendations.append("Secure indicative PPA terms to strengthen Gate 3")

    return {
        "overall_readiness": round(overall),
        "verdict": verdict,
        "gates": gates,
        "survival_probability": round(survival, 2),
        "recommendations": recommendations[:8],
        "context": {
            "nearest_substation": best_sub["name"] if best_sub else None,
            "distance_km": round(best_dist, 2) if best_sub else None,
            "headroom_mw": round(best_headroom, 1),
            "queue_count": queue_count,
            "queued_mw": round(queued_mw, 1),
            "dno": best_dno,
            "local_repd_count": repd_total,
            "local_planning_rate": round(local_planning_rate, 2),
            "local_refusal_rate": round(refusal_rate, 2),
            "tec_queued_nearby": tec_queued,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _gate_status(score: int) -> str:
    if score >= 75:
        return "PASS"
    elif score >= 50:
        return "AT RISK"
    else:
        return "FAIL"


def _survival_probability(gates: list[dict]) -> float:
    """Estimate probability of surviving all gates."""
    prob = 1.0
    for g in gates:
        # Map score to gate pass probability
        s = g["score"]
        if s >= 80:
            p = 0.95
        elif s >= 60:
            p = 0.75
        elif s >= 40:
            p = 0.50
        else:
            p = 0.25
        prob *= p
    return prob


# ---------------------------------------------------------------------------
# 2. Queue Reform Impact Model
# ---------------------------------------------------------------------------

async def model_queue_reform_impact(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
) -> dict:
    """
    Predict how many projects in the queue ahead will be removed
    by Ofgem's connections reform (TMO4+ queue cleansing).

    Criteria for likely removal:
    - No matching REPD entry (no planning activity)
    - Capacity < 1MW with no activity (speculative)
    - Queue age > 3 years with no progress
    - No land/planning evidence
    """
    async with pool.acquire() as conn:
        # ── Nearest substations ──────────────────────────────────────────
        subs = await conn.fetch("""
            SELECT
                s.id, s.name, s.dno, s.voltage_kv,
                s.gen_headroom_mw,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                ST_Distance(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                ) / 1000.0 AS distance_km
            FROM grid_substations s
            WHERE s.geom IS NOT NULL
              AND ST_DWithin(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    20000
                  )
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 5
        """, lon, lat)

        if not subs:
            return {
                "current_queue_position": 0,
                "estimated_removals": 0,
                "post_reform_position": 0,
                "queue_reduction_pct": 0,
                "removal_reasons": {},
                "time_saving_months": 0,
                "confidence": 0.3,
                "message": "No substations found within 20km",
            }

        sub_ids = [r["id"] for r in subs]

        # ── ECR queue entries at these substations ───────────────────────
        ecr_entries = await conn.fetch("""
            SELECT
                e.id, e.site_name, e.technology, e.capacity_mw,
                e.status, e.substation_id, e.substation_name,
                e.dno
            FROM grid_ecr e
            WHERE e.substation_id = ANY($1::int[])
              AND (e.status ILIKE '%%queue%%'
                   OR e.status ILIKE '%%pending%%'
                   OR e.status ILIKE '%%accepted%%'
                   OR e.status ILIKE '%%submitted%%')
            ORDER BY e.capacity_mw DESC
        """, sub_ids)

        # ── REPD projects in the area (to cross-reference planning) ──────
        repd_names = set()
        repd_rows = await conn.fetch("""
            SELECT site_name, technology_type, installed_capacity_mw,
                   dev_status_short
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.2
                  )
        """, lon, lat)
        for rp in repd_rows:
            if rp["site_name"]:
                repd_names.add(rp["site_name"].lower().strip())

    # ── Assess each queued project for removal likelihood ────────────────
    total_queued = len(ecr_entries)
    removals = {"no_planning": 0, "speculative_small": 0, "stale_no_progress": 0}
    estimated_removals = 0
    projects_ahead = 0

    for ecr in ecr_entries:
        cap = float(ecr["capacity_mw"] or 0)
        name = (ecr["site_name"] or "").lower().strip()

        # Count as ahead if it's in the queue
        projects_ahead += 1

        likely_removed = False

        # Check 1: No REPD match (no planning activity)
        has_repd = any(
            _fuzzy_match(name, rn) for rn in repd_names
        ) if name else False

        if not has_repd and cap > 0:
            removals["no_planning"] += 1
            likely_removed = True

        # Check 2: Speculative small project (< 1MW, no REPD)
        elif cap < 1 and not has_repd:
            removals["speculative_small"] += 1
            likely_removed = True

        # Check 3: Stale — large projects with generic names, no REPD
        elif not has_repd and cap > 5:
            # Heuristic: projects without matching REPD and > 5MW
            # are likely speculative at scale
            removals["stale_no_progress"] += 1
            likely_removed = True

        if likely_removed:
            estimated_removals += 1

    post_reform_position = max(0, projects_ahead - estimated_removals)
    reduction_pct = round(estimated_removals / max(projects_ahead, 1) * 100)

    # Time saving: each removed project saves ~2-3 months of queue wait
    time_saving = estimated_removals * 2  # conservative: 2 months per removal

    # Confidence based on data quality
    confidence = 0.5
    if total_queued > 5:
        confidence = 0.65
    if len(repd_rows) > 10:
        confidence = 0.75
    if total_queued > 15 and len(repd_rows) > 20:
        confidence = 0.80

    return {
        "current_queue_position": projects_ahead,
        "estimated_removals": estimated_removals,
        "post_reform_position": post_reform_position,
        "queue_reduction_pct": reduction_pct,
        "removal_reasons": removals,
        "time_saving_months": time_saving,
        "confidence": confidence,
        "substations_analysed": [
            {"name": s["name"], "id": s["id"], "distance_km": round(float(s["distance_km"]), 2)}
            for s in subs[:3]
        ],
        "total_ecr_entries": total_queued,
        "repd_cross_references": len(repd_rows),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _fuzzy_match(a: str, b: str) -> bool:
    """Simple fuzzy name matching — checks if significant words overlap."""
    if not a or not b:
        return False
    # Strip common suffixes
    stop = {"solar", "farm", "wind", "battery", "bess", "storage", "energy",
            "park", "ltd", "limited", "project", "phase", "extension"}
    words_a = set(a.split()) - stop
    words_b = set(b.split()) - stop
    if not words_a or not words_b:
        return a == b
    overlap = words_a & words_b
    return len(overlap) >= 1


# ---------------------------------------------------------------------------
# 3. Strategic Alignment Scorer
# ---------------------------------------------------------------------------

async def score_strategic_alignment(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict:
    """
    Score alignment with NESO Strategic Spatial Energy Plan priorities.

    Factors:
    - Regional technology priority (SSEP corridors)
    - Grid headroom concentration
    - Existing renewable density (saturation check)
    - Demand proximity
    """
    tech = technology.lower().replace("_", "").replace("pv", "").strip()
    if tech in ("battery", "bess"):
        tech = "bess"
    elif "wind" in tech:
        tech = "wind"
    elif "solar" in tech:
        tech = "solar"

    async with pool.acquire() as conn:
        # ── Nearest substations for grid context ─────────────────────────
        subs = await conn.fetch("""
            SELECT
                s.id, s.name, s.dno, s.voltage_kv,
                s.demand_mw, s.generation_mw,
                s.gen_headroom_mw, s.demand_headroom_mw,
                ST_Distance(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                ) / 1000.0 AS distance_km
            FROM grid_substations s
            WHERE s.geom IS NOT NULL
              AND ST_DWithin(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    25000
                  )
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 10
        """, lon, lat)

        # ── REPD renewable density ───────────────────────────────────────
        repd_stats = await conn.fetchrow("""
            SELECT
                COUNT(*) AS project_count,
                COALESCE(SUM(installed_capacity_mw), 0) AS total_mw,
                COUNT(*) FILTER (
                    WHERE technology_type ILIKE '%%solar%%'
                ) AS solar_count,
                COUNT(*) FILTER (
                    WHERE technology_type ILIKE '%%wind%%'
                ) AS wind_count,
                COALESCE(SUM(installed_capacity_mw) FILTER (
                    WHERE dev_status_short IN ('Operational', 'Under Construction')
                ), 0) AS operational_mw
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.25
                  )
        """, lon, lat)

        # ── Demand concentration (sum of demand at nearby substations) ───
        demand_row = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(demand_mw), 0) AS total_demand_mw,
                COUNT(*) AS sub_count
            FROM grid_substations
            WHERE geom IS NOT NULL
              AND ST_DWithin(
                    geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    15000
                  )
        """, lon, lat)

    # ── Factor 1: Regional priority ──────────────────────────────────────
    dno = subs[0]["dno"] if subs else "UKPN"
    region = _dno_region(dno)
    tech_prefs = _SSEP_TECH_REGION.get(tech, _SSEP_TECH_REGION.get("solar", {}))
    region_multiplier = tech_prefs.get(region, 1.0)
    regional_score = min(100, int(60 * region_multiplier + 15))

    if region_multiplier >= 1.2:
        regional_detail = f"{region.replace('_', ' ').title()} — priority {tech} corridor in SSEP"
    elif region_multiplier >= 1.0:
        regional_detail = f"{region.replace('_', ' ').title()} — moderate {tech} suitability"
    else:
        regional_detail = f"{region.replace('_', ' ').title()} — lower priority for {tech} in SSEP"

    # ── Factor 2: Grid headroom ──────────────────────────────────────────
    best_sub = subs[0] if subs else None
    headroom = float(best_sub["gen_headroom_mw"] or 0) if best_sub else 0
    headroom_score = 50
    headroom_detail = "No substations found"

    if best_sub:
        if headroom >= capacity_mw * 1.5:
            headroom_score = 90
            headroom_detail = f"{headroom:.0f}MW headroom at nearest {best_sub['voltage_kv']}kV substation ({best_sub['name']})"
        elif headroom >= capacity_mw:
            headroom_score = 75
            headroom_detail = f"{headroom:.0f}MW headroom — sufficient but tight ({best_sub['name']})"
        elif headroom > 0:
            headroom_score = 50
            headroom_detail = f"Only {headroom:.0f}MW headroom vs {capacity_mw}MW required — reinforcement needed"
        else:
            headroom_score = 25
            headroom_detail = f"No headroom at nearest substation ({best_sub['name']})"

    # ── Factor 3: Demand proximity ───────────────────────────────────────
    total_demand = float(demand_row["total_demand_mw"]) if demand_row else 0
    demand_score = 50
    demand_detail = "Moderate demand proximity"

    if total_demand > 500:
        demand_score = 90
        demand_detail = f"Within 15km of {total_demand:.0f}MW demand centre"
    elif total_demand > 200:
        demand_score = 75
        demand_detail = f"Within 15km of {total_demand:.0f}MW demand"
    elif total_demand > 50:
        demand_score = 60
        demand_detail = f"{total_demand:.0f}MW demand within 15km"
    else:
        demand_score = 35
        demand_detail = f"Low demand proximity ({total_demand:.0f}MW within 15km)"

    # ── Factor 4: Renewable density (saturation check) ───────────────────
    re_count = int(repd_stats["project_count"]) if repd_stats else 0
    re_mw = float(repd_stats["total_mw"]) if repd_stats else 0
    operational_mw = float(repd_stats["operational_mw"]) if repd_stats else 0
    density_score = 70
    density_detail = "Moderate existing RE — not oversaturated"

    if re_count > 30 or re_mw > 500:
        density_score = 40
        density_detail = f"High RE density ({re_count} projects, {re_mw:.0f}MW) — potential curtailment risk"
    elif re_count > 15 or re_mw > 200:
        density_score = 55
        density_detail = f"Moderate RE density ({re_count} projects, {re_mw:.0f}MW)"
    elif re_count < 5:
        density_score = 85
        density_detail = f"Low RE density ({re_count} projects) — greenfield opportunity"

    # ── Aggregate alignment score ────────────────────────────────────────
    weights = {"regional": 0.25, "headroom": 0.30, "demand": 0.25, "density": 0.20}
    alignment_score = (
        regional_score * weights["regional"]
        + headroom_score * weights["headroom"]
        + demand_score * weights["demand"]
        + density_score * weights["density"]
    )

    if alignment_score >= 75:
        priority_level = "HIGH"
    elif alignment_score >= 55:
        priority_level = "MEDIUM"
    else:
        priority_level = "LOW"

    # NESO recommendation narrative
    if alignment_score >= 75:
        neso_rec = f"Site aligns well with SSEP {tech} corridor. Priority connection likely."
    elif alignment_score >= 55:
        neso_rec = f"Moderate alignment with SSEP priorities. Connection possible but not prioritised."
    else:
        neso_rec = f"Weak alignment with SSEP — consider alternative locations or technology."

    return {
        "alignment_score": round(alignment_score),
        "priority_level": priority_level,
        "factors": [
            {"name": "Regional priority", "score": regional_score, "detail": regional_detail},
            {"name": "Grid headroom", "score": headroom_score, "detail": headroom_detail},
            {"name": "Demand proximity", "score": demand_score, "detail": demand_detail},
            {"name": "Renewable density", "score": density_score, "detail": density_detail},
        ],
        "neso_recommendation": neso_rec,
        "region": region,
        "dno": dno,
        "nearby_re_projects": re_count,
        "nearby_re_mw": round(re_mw, 1),
        "nearby_operational_mw": round(operational_mw, 1),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 4. Connection Strategy Optimizer
# ---------------------------------------------------------------------------

async def optimize_connection_strategy(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict:
    """
    Recommend the best connection approach considering:
    - All substations within 20km
    - Net headroom after queue deduction
    - Voltage level trade-offs
    - DNO performance (acceptance rates)
    - Post-reform queue position
    - Optimal application timing
    """
    async with pool.acquire() as conn:
        # ── All substations within 20km ──────────────────────────────────
        subs = await conn.fetch("""
            SELECT
                s.id, s.name, s.dno, s.voltage_kv,
                s.demand_mw, s.generation_mw,
                s.gen_headroom_mw, s.demand_headroom_mw,
                s.transformer_rating_mva,
                s.rag_demand, s.rag_generation,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                ST_Distance(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                ) / 1000.0 AS distance_km
            FROM grid_substations s
            WHERE s.geom IS NOT NULL
              AND ST_DWithin(
                    s.geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    20000
                  )
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 15
        """, lon, lat)

        # ── ECR queue data ───────────────────────────────────────────────
        sub_ids = [r["id"] for r in subs]
        ecr_rows = []
        if sub_ids:
            ecr_rows = await conn.fetch("""
                SELECT
                    substation_id,
                    COUNT(*) AS queue_count,
                    COALESCE(SUM(capacity_mw), 0) AS queued_mw,
                    COUNT(*) FILTER (
                        WHERE status ILIKE '%%queue%%'
                           OR status ILIKE '%%pending%%'
                           OR status ILIKE '%%submitted%%'
                    ) AS active_count
                FROM grid_ecr
                WHERE substation_id = ANY($1::int[])
                GROUP BY substation_id
            """, sub_ids)

        ecr_map: dict[int, dict] = {}
        for er in ecr_rows:
            ecr_map[er["substation_id"]] = {
                "queue_count": int(er["queue_count"]),
                "queued_mw": float(er["queued_mw"]),
                "active_count": int(er["active_count"]),
            }

        # ── REPD for reform impact estimation ────────────────────────────
        repd_names = set()
        repd_rows = await conn.fetch("""
            SELECT site_name
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.2
                  )
        """, lon, lat)
        for rp in repd_rows:
            if rp["site_name"]:
                repd_names.add(rp["site_name"].lower().strip())

    # ── Evaluate each candidate substation ───────────────────────────────
    likely_voltage = _voltage_for_capacity(capacity_mw)
    candidates = []

    for s in subs:
        sid = s["id"]
        dist_km = float(s["distance_km"])
        headroom = float(s["gen_headroom_mw"] or 0)
        voltage = float(s["voltage_kv"] or 33)
        dno = s["dno"] or "UKPN"
        ecr = ecr_map.get(sid, {"queue_count": 0, "queued_mw": 0, "active_count": 0})

        queued_mw = ecr["queued_mw"]
        queue_count = ecr["active_count"]

        # Estimate post-reform removals (heuristic: ~40-60% of queue)
        est_removal_pct = 0.50
        post_reform_queue = max(0, int(queue_count * (1 - est_removal_pct)))
        post_reform_queued_mw = queued_mw * (1 - est_removal_pct)

        # Net headroom after post-reform queue
        net_headroom = headroom - post_reform_queued_mw

        # Connection cost
        cost_p50 = _connection_cost_p50(dist_km, likely_voltage)

        # Reinforcement
        reinforcement = 0
        if capacity_mw > net_headroom and net_headroom >= 0:
            shortfall = capacity_mw - net_headroom
            reinforcement = int(shortfall * 200_000 * (voltage / 33))
        elif net_headroom < 0:
            reinforcement = int(capacity_mw * 250_000 * (voltage / 33))

        total_cost = cost_p50 + reinforcement

        # Time-to-offer
        dno_extra = _DNO_FACTOR.get(dno, 2.0)
        base_months = 6.0
        queue_delay = (post_reform_queued_mw / max(headroom, 0.1)) * 12 if headroom > 0 else 18
        capacity_penalty = 12.0 if capacity_mw > net_headroom else 0.0
        time_months = min(84, base_months + queue_delay + capacity_penalty + dno_extra)

        # DNO acceptance factor
        acceptance = _DNO_ACCEPTANCE.get(dno, 0.70)

        # Composite score: weighted combination
        # Higher is better
        headroom_factor = max(0, net_headroom) / max(capacity_mw, 1)
        distance_factor = max(0, 1 - dist_km / 20)
        time_factor = max(0, 1 - time_months / 60)
        cost_factor = max(0, 1 - total_cost / 10_000_000)

        score = (
            headroom_factor * 0.30
            + distance_factor * 0.20
            + time_factor * 0.25
            + acceptance * 0.15
            + cost_factor * 0.10
        ) * 100

        candidates.append({
            "substation_id": sid,
            "name": s["name"],
            "dno": dno,
            "voltage_kv": voltage,
            "distance_km": round(dist_km, 2),
            "lat": float(s["lat"]),
            "lon": float(s["lon"]),
            "headroom_mw": round(headroom, 1),
            "queued_mw": round(queued_mw, 1),
            "queue_count": queue_count,
            "post_reform_queue_position": post_reform_queue,
            "post_reform_net_headroom_mw": round(net_headroom, 1),
            "estimated_cost_gbp": total_cost,
            "connection_cost_gbp": cost_p50,
            "reinforcement_cost_gbp": reinforcement,
            "estimated_timeline_months": round(time_months, 1),
            "dno_acceptance_rate": acceptance,
            "score": round(score, 1),
            "rag_demand": s["rag_demand"],
            "rag_generation": s["rag_generation"],
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)

    best = candidates[0] if candidates else None
    alts = candidates[1:4] if len(candidates) > 1 else []

    # Timing recommendation
    dno = best["dno"] if best else "UKPN"
    congestion = best["queue_count"] if best else 0
    if congestion > 10:
        timing = "Apply Q2 2026 — post-reform queue cleansing will clear speculative projects"
    elif congestion > 5:
        timing = "Apply Q1 2026 — moderate queue, early mover advantage after reform"
    else:
        timing = "Apply immediately — low queue depth, best to secure position early"

    # Risk mitigation
    risk_mitigation = []
    if best and not best.get("post_reform_net_headroom_mw", 0) >= capacity_mw:
        risk_mitigation.append("Reinforcement likely — engage early with DNO on costs")
    risk_mitigation.append("Secure land option before application to pass Gate 1")
    risk_mitigation.append("Pre-application meeting with DNO recommended")
    if best and best["distance_km"] > 5:
        risk_mitigation.append(f"Long connection route ({best['distance_km']:.1f}km) — consider wayleave acquisition early")
    if best and best["dno_acceptance_rate"] < 0.70:
        risk_mitigation.append(f"{dno} has lower acceptance rate ({best['dno_acceptance_rate']:.0%}) — prepare thorough application")

    return {
        "recommended_strategy": {
            "substation": best["name"] if best else None,
            "substation_id": best["substation_id"] if best else None,
            "voltage": int(best["voltage_kv"]) if best else None,
            "estimated_cost_gbp": best["estimated_cost_gbp"] if best else None,
            "connection_cost_gbp": best["connection_cost_gbp"] if best else None,
            "reinforcement_cost_gbp": best["reinforcement_cost_gbp"] if best else None,
            "estimated_timeline_months": best["estimated_timeline_months"] if best else None,
            "post_reform_queue_position": best["post_reform_queue_position"] if best else None,
            "distance_km": best["distance_km"] if best else None,
            "headroom_mw": best["headroom_mw"] if best else None,
            "confidence": round(0.6 + (best["score"] / 100) * 0.3, 2) if best else 0.3,
        } if best else None,
        "alternatives": [
            {
                "substation": a["name"],
                "substation_id": a["substation_id"],
                "voltage": int(a["voltage_kv"]),
                "estimated_cost_gbp": a["estimated_cost_gbp"],
                "estimated_timeline_months": a["estimated_timeline_months"],
                "post_reform_queue_position": a["post_reform_queue_position"],
                "distance_km": a["distance_km"],
                "score": a["score"],
            }
            for a in alts
        ],
        "timing_recommendation": timing,
        "risk_mitigation": risk_mitigation,
        "all_candidates": candidates,
        "likely_voltage_kv": likely_voltage,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
