"""
Time-to-energisation estimator -- predicts total timeline from
application to first power export.

Phases modelled (with real UK benchmarks):
1. Pre-application (1-3 months) -- surveys, community consultation
2. Planning application (3-12 months) -- LPA determination
3. Connection offer (3-18 months) -- DNO processing queue
4. Connection works (6-24 months) -- construction of grid connection
5. Commissioning (1-3 months) -- testing and energisation

Uses real data:
- REPD project timelines (planning dates where available)
- ECR queue depth at target substation
- DNO processing time benchmarks
- Technology and capacity-specific adjustments
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Any

log = logging.getLogger("princeps.energisation_estimator")


# ── DNO processing time benchmarks (months of delay) ───────────────────────

_DNO_PROCESSING_MONTHS: dict[str, float] = {
    "UKPN": 6.0,
    "NGED": 5.0,
    "SPEN": 8.0,
    "SSEN": 9.0,
    "ENWL": 7.0,
    "NPG":  6.5,
    "default": 7.0,
}

# ── Connection works duration by voltage (months) ──────────────────────────

_WORKS_MONTHS_BY_VOLTAGE: dict[int, int] = {
    11: 6,
    33: 9,
    66: 14,
    132: 18,
    275: 24,
    400: 30,
}

# ── Technology adjustment factors ──────────────────────────────────────────

_TECH_PLANNING_ADDER: dict[str, int] = {
    "wind": 3,          # Wind adds ~3 months (visual impact assessment)
    "onshore_wind": 3,
    "solar": 0,
    "bess": -1,         # BESS often permitted development
    "solar+bess": 0,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _voltage_for_capacity(capacity_mw: float) -> int:
    """Determine likely connection voltage based on capacity."""
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


# ── Phase estimators ───────────────────────────────────────────────────────

def _estimate_pre_application(capacity_mw: float, technology: str) -> int:
    """Phase 1: Pre-application surveys and community consultation."""
    base = 2
    # NSIP threshold (> 50 MW onshore, > 100 MW offshore) adds complexity
    if capacity_mw > 50:
        base += 1
    return base


async def _estimate_planning(
    pool, lat: float, lon: float,
    capacity_mw: float, technology: str,
) -> tuple[int, list[str]]:
    """
    Phase 2: Planning application -- query REPD for nearby approval times.
    Returns (months, risk_factors).
    """
    base = 6
    risks = []

    # Technology adjustment
    tech_key = technology.lower().replace(" ", "")
    base += _TECH_PLANNING_ADDER.get(tech_key, 0)

    # Capacity adjustment: NSIP regime (> 50 MW) is much slower
    if capacity_mw > 50:
        base += 2
        risks.append("NSIP regime (>50 MW) -- DCO required, slower determination")

    # Query REPD for nearby project planning durations
    repd_avg_months = None
    try:
        async with pool.acquire() as conn:
            # Find REPD projects within 20 km that have both submitted and granted dates
            rows = await conn.fetch("""
                SELECT
                    planning_submitted,
                    planning_granted,
                    installed_capacity_mw,
                    technology_type
                FROM repd_project
                WHERE geometry IS NOT NULL
                  AND planning_submitted IS NOT NULL
                  AND planning_granted IS NOT NULL
                  AND ST_DWithin(
                      geometry,
                      ST_SetSRID(ST_MakePoint($1, $2), 4326),
                      0.2  -- ~20 km in degrees at UK latitudes
                  )
                ORDER BY ST_Distance(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)
                )
                LIMIT 50
            """, lon, lat)

            if rows:
                durations = []
                for r in rows:
                    submitted = r["planning_submitted"]
                    granted = r["planning_granted"]
                    if submitted and granted and granted > submitted:
                        months = (granted.year - submitted.year) * 12 + (granted.month - submitted.month)
                        if 1 <= months <= 60:  # Sanity check
                            durations.append(months)

                if durations:
                    repd_avg_months = round(sum(durations) / len(durations), 1)
                    log.info(
                        "REPD planning benchmark: %.1f months avg from %d nearby projects",
                        repd_avg_months, len(durations),
                    )
                    # Weight the REPD average with our base estimate
                    base = round(0.6 * repd_avg_months + 0.4 * base)
                    risks.append(
                        f"REPD benchmark: {repd_avg_months:.0f}mo avg from {len(durations)} nearby projects"
                    )

    except Exception as exc:
        log.debug("REPD planning query failed: %s", exc)

    return max(base, 3), risks


async def _estimate_connection_offer(
    pool, lat: float, lon: float,
    capacity_mw: float, technology: str,
) -> tuple[int, list[str], dict]:
    """
    Phase 3: Connection offer -- uses connection_offer_forecaster if available,
    else estimates from ECR queue depth and DNO benchmarks.
    Returns (months, risk_factors, benchmarks).
    """
    risks = []
    benchmarks = {}

    # Try the full forecaster first
    try:
        from utils.connection_offer_forecaster import forecast_connection_offer
        forecast = await forecast_connection_offer(
            pool, lat, lon, capacity_mw, technology,
        )
        if forecast and "timeline_months" in forecast:
            offer_months = forecast["timeline_months"]
            if forecast.get("queue_depth"):
                risks.append(
                    f"Queue depth at nearest sub: {forecast['queue_depth']} projects"
                )
            if forecast.get("dno"):
                dno_avg = _DNO_PROCESSING_MONTHS.get(forecast["dno"], 7)
                benchmarks["dno_avg_processing_months"] = dno_avg
            benchmarks["forecaster_confidence"] = forecast.get("confidence", 0.5)
            return max(offer_months, 3), risks, benchmarks
    except Exception as exc:
        log.debug("Connection offer forecaster unavailable: %s", exc)

    # Fallback: estimate from ECR queue depth + DNO benchmarks
    queue_depth = 0
    dno = "default"
    try:
        async with pool.acquire() as conn:
            # Find nearest substation and its queue
            sub = await conn.fetchrow("""
                SELECT
                    s.id, s.name, s.dno, s.voltage_kv,
                    (SELECT COUNT(*) FROM grid_ecr e
                     WHERE e.substation_id = s.id) AS queue_count,
                    (SELECT COALESCE(SUM(e.capacity_mw), 0) FROM grid_ecr e
                     WHERE e.substation_id = s.id) AS queue_mw
                FROM grid_substations s
                WHERE s.geom IS NOT NULL
                ORDER BY s.geom <-> ST_Transform(
                    ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                )
                LIMIT 1
            """, lon, lat)

            if sub:
                dno = sub["dno"] or "default"
                queue_depth = sub["queue_count"] or 0
                queue_mw = sub["queue_mw"] or 0

                if queue_depth > 0:
                    risks.append(
                        f"Queue depth at nearest sub: {queue_depth} projects ({queue_mw:.0f} MW)"
                    )

    except Exception as exc:
        log.debug("ECR queue query failed: %s", exc)

    # Base DNO processing time
    dno_base = _DNO_PROCESSING_MONTHS.get(dno, 7)
    benchmarks["dno_avg_processing_months"] = dno_base

    # Queue depth adds delay: each project adds ~0.5 months
    queue_delay = min(queue_depth * 0.5, 12)

    # Capacity factor: larger projects take longer
    capacity_adder = 0
    if capacity_mw > 100:
        capacity_adder = 3
    elif capacity_mw > 50:
        capacity_adder = 2
    elif capacity_mw > 10:
        capacity_adder = 1

    offer_months = round(dno_base + queue_delay + capacity_adder)
    return max(offer_months, 3), risks, benchmarks


def _estimate_connection_works(
    capacity_mw: float, voltage_kv: int, reinforcement_needed: bool,
) -> tuple[int, list[str]]:
    """
    Phase 4: Connection works -- construction duration by voltage tier.
    """
    risks = []

    # Find closest voltage tier
    closest = min(_WORKS_MONTHS_BY_VOLTAGE.keys(), key=lambda v: abs(v - voltage_kv))
    base = _WORKS_MONTHS_BY_VOLTAGE[closest]

    if reinforcement_needed:
        base += 12
        risks.append("Reinforcement likely needed -- adds ~12 months")

    return base, risks


def _estimate_commissioning(capacity_mw: float, technology: str) -> int:
    """Phase 5: Testing and commissioning."""
    base = 2
    if capacity_mw > 50:
        base = 3
    return base


async def _check_reinforcement_needed(
    pool, lat: float, lon: float, capacity_mw: float,
) -> bool:
    """Check if grid reinforcement is likely needed based on headroom data."""
    try:
        async with pool.acquire() as conn:
            sub = await conn.fetchrow("""
                SELECT gen_headroom_mw, demand_headroom_mw
                FROM grid_substations
                WHERE geom IS NOT NULL
                ORDER BY geom <-> ST_Transform(
                    ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                )
                LIMIT 1
            """, lon, lat)
            if sub and sub["gen_headroom_mw"] is not None:
                return capacity_mw > sub["gen_headroom_mw"]
    except Exception:
        pass
    # Default: reinforcement likely if > 20 MW
    return capacity_mw > 20


async def _repd_similar_projects_avg(
    pool, lat: float, lon: float,
    capacity_mw: float, technology: str,
) -> float | None:
    """Query REPD for average total timeline of similar nearby projects."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    planning_submitted,
                    operational
                FROM repd_project
                WHERE geometry IS NOT NULL
                  AND planning_submitted IS NOT NULL
                  AND operational IS NOT NULL
                  AND ST_DWithin(
                      geometry,
                      ST_SetSRID(ST_MakePoint($1, $2), 4326),
                      0.3  -- ~30 km
                  )
                ORDER BY ST_Distance(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)
                )
                LIMIT 30
            """, lon, lat)

            durations = []
            for r in rows:
                sub = r["planning_submitted"]
                op = r["operational"]
                if sub and op and op > sub:
                    months = (op.year - sub.year) * 12 + (op.month - sub.month)
                    if 6 <= months <= 120:
                        durations.append(months)

            if durations:
                return round(sum(durations) / len(durations), 1)
    except Exception as exc:
        log.debug("REPD similar projects query failed: %s", exc)
    return None


# ── Main estimator ─────────────────────────────────────────────────────────

async def estimate_energisation_timeline(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict[str, Any]:
    """
    Predict total months from application to first power export.

    Args:
        pool: asyncpg connection pool
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        capacity_mw: Proposed capacity in MW
        technology: solar, wind, bess, solar+bess

    Returns:
        Dict with total_months, phases, target_date, risk_factors, benchmarks.
    """
    tech = technology.lower().replace(" ", "")
    voltage_kv = _voltage_for_capacity(capacity_mw)
    all_risks = []
    benchmarks = {}

    # Phase 1: Pre-application
    pre_app_months = _estimate_pre_application(capacity_mw, tech)

    # Phase 2: Planning
    planning_months, planning_risks = await _estimate_planning(
        pool, lat, lon, capacity_mw, tech,
    )
    all_risks.extend(planning_risks)

    # Phase 3: Connection offer
    conn_offer_months, conn_risks, conn_benchmarks = await _estimate_connection_offer(
        pool, lat, lon, capacity_mw, tech,
    )
    all_risks.extend(conn_risks)
    benchmarks.update(conn_benchmarks)

    # Phase 4: Connection works
    reinforcement_needed = await _check_reinforcement_needed(pool, lat, lon, capacity_mw)
    works_months, works_risks = _estimate_connection_works(
        capacity_mw, voltage_kv, reinforcement_needed,
    )
    all_risks.extend(works_risks)

    # Phase 5: Commissioning
    commissioning_months = _estimate_commissioning(capacity_mw, tech)

    # Build phase timeline
    phases = []
    cursor = 0

    phase_data = [
        ("Pre-application", pre_app_months),
        ("Planning", planning_months),
        ("Connection offer", conn_offer_months),
        ("Connection works", works_months),
        ("Commissioning", commissioning_months),
    ]

    for name, months in phase_data:
        phases.append({
            "name": name,
            "months": months,
            "start_month": cursor,
        })
        cursor += months

    total_months = cursor

    # P10/P50/P90 range
    # P10 (optimistic): 75% of total
    # P50 (expected): total as calculated
    # P90 (pessimistic): 150% of total
    p10 = max(round(total_months * 0.75), total_months - 8)
    p50 = total_months
    p90 = round(total_months * 1.5)

    # Target date
    now = datetime.utcnow()
    try:
        target = now + relativedelta(months=total_months)
        target_date = target.strftime("%Y-%m")
    except Exception:
        target_date = None

    # REPD similar projects benchmark
    similar_avg = await _repd_similar_projects_avg(pool, lat, lon, capacity_mw, tech)
    if similar_avg is not None:
        benchmarks["similar_projects_avg_months"] = similar_avg

    # Voltage info
    if voltage_kv >= 132:
        all_risks.append(f"Connection at {voltage_kv}kV -- requires NESO involvement")

    return {
        "total_months": total_months,
        "total_months_range": {
            "p10": p10,
            "p50": p50,
            "p90": p90,
        },
        "phases": phases,
        "target_date": target_date,
        "risk_factors": all_risks,
        "benchmarks": benchmarks,
        "inputs": {
            "lat": lat,
            "lon": lon,
            "capacity_mw": capacity_mw,
            "technology": technology,
            "estimated_voltage_kv": voltage_kv,
            "reinforcement_needed": reinforcement_needed,
        },
    }
