"""
Grid Queue Intelligence — TEC register and REPD analysis for connection
timeline prediction, cost benchmarking, and opportunity identification.

Analyses the ESO TEC register (eso_tec_register) and REPD (repd_projects) to:
- Predict connection offer timelines with P10/P50/P90 confidence
- Benchmark connection costs by voltage, capacity, and region
- Identify queue opportunities (withdrawn projects, low-queue sites, headroom)
- Provide deep queue analysis per connection site

All functions take an asyncpg connection or pool.
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import date, timedelta
from typing import Any

log = logging.getLogger("princeps.grid_queue_intelligence")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Base offer timeline months by connection voltage (UK typical, ESO data-derived)
BASE_OFFER_MONTHS: dict[int, float] = {
    11: 6.0,
    33: 12.0,
    66: 18.0,
    132: 24.0,
    275: 36.0,
    400: 48.0,
}

# Regression coefficients for timeline prediction
QUEUE_FACTOR = 1.8        # months per project in queue
CAPACITY_FACTOR = 3.5     # months per ln(MW)

# Connection cost benchmarks GBP/km by voltage
CABLE_COST_PER_KM: dict[int, float] = {
    11: 80_000,
    33: 150_000,
    66: 300_000,
    132: 500_000,
    275: 800_000,
    400: 1_200_000,
}

SWITCHGEAR_COST: dict[int, float] = {
    11: 25_000,
    33: 200_000,
    66: 350_000,
    132: 500_000,
    275: 800_000,
    400: 1_500_000,
}

TRANSFORMER_COST_BY_RATIO: dict[str, float] = {
    "11/0.4": 15_000,
    "33/11": 250_000,
    "66/33": 400_000,
    "132/33": 2_500_000,
    "132/66": 3_500_000,
    "275/132": 8_000_000,
    "400/132": 12_000_000,
}

# Regional cost multipliers (vs national average = 1.0)
REGIONAL_COST_MULTIPLIER: dict[str, float] = {
    "scotland": 1.15,
    "north_east": 1.05,
    "north_west": 1.05,
    "yorkshire": 1.00,
    "east_midlands": 0.98,
    "west_midlands": 1.00,
    "wales": 1.10,
    "east_anglia": 0.95,
    "south_east": 1.08,
    "south_west": 1.05,
    "london": 1.25,
    "southern": 1.02,
}

# Status classifications
ACTIVE_STATUSES = {"Accepted", "Offer Made", "Contracted"}
WITHDRAWN_STATUSES = {"Terminated", "Withdrawn", "Lapsed", "Refused"}
STALLED_THRESHOLD_DAYS = 730  # 2 years without progress = stalled


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _months_between(d1: date | None, d2: date | None) -> float | None:
    """Months between two dates."""
    if not d1 or not d2:
        return None
    delta = (d2 - d1).days
    return round(delta / 30.44, 1)


def _pick_voltage(capacity_mw: float, voltage_kv: float | None = None) -> int:
    """Select appropriate connection voltage from capacity."""
    if voltage_kv and voltage_kv > 0:
        # Snap to nearest standard voltage
        standard = [11, 33, 66, 132, 275, 400]
        return min(standard, key=lambda v: abs(v - voltage_kv))
    if capacity_mw <= 5:
        return 11
    if capacity_mw <= 50:
        return 33
    if capacity_mw <= 100:
        return 66
    if capacity_mw <= 500:
        return 132
    if capacity_mw <= 1500:
        return 275
    return 400


def _risk_level(queue_depth: int, total_mw: float, avg_wait: float | None) -> str:
    """Derive risk level from queue metrics."""
    score = 0
    if queue_depth > 15:
        score += 3
    elif queue_depth > 8:
        score += 2
    elif queue_depth > 3:
        score += 1

    if total_mw > 2000:
        score += 3
    elif total_mw > 500:
        score += 2
    elif total_mw > 100:
        score += 1

    if avg_wait and avg_wait > 48:
        score += 3
    elif avg_wait and avg_wait > 24:
        score += 2
    elif avg_wait and avg_wait > 12:
        score += 1

    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _serialise_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to JSON-safe dict."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, date):
            d[k] = v.isoformat()
    return d


# ---------------------------------------------------------------------------
# 1. analyse_queue — deep analysis of a single connection site
# ---------------------------------------------------------------------------

async def analyse_queue(conn, connection_site: str) -> dict[str, Any]:
    """
    Deep queue analysis for a connection site.

    Returns queue depth, total MW, avg wait, technology breakdown,
    competing projects, recently withdrawn (opportunities), stalled projects.
    """
    rows = await conn.fetch("""
        SELECT tec_id, customer_name, connection_site, fuel_type, tech_category,
               tec_mw, status, effective_from, effective_to, connection_date,
               voltage_kv, zone, dnc_mw, spv_name, parent_company, queue_position
        FROM eso_tec_register
        WHERE connection_site ILIKE $1
        ORDER BY queue_position NULLS LAST, tec_mw DESC
    """, f"%{connection_site}%")

    if not rows:
        return {
            "connection_site": connection_site,
            "queue_depth": 0,
            "total_queued_mw": 0.0,
            "avg_wait_months": None,
            "technology_breakdown": {},
            "competing_projects": [],
            "recently_withdrawn": [],
            "stalled_projects": [],
            "risk_level": "low",
            "status_breakdown": {},
            "voltage_levels": [],
        }

    today = date.today()
    active_entries = []
    withdrawn_entries = []
    stalled_entries = []
    tech_mw: dict[str, float] = {}
    status_counts: dict[str, int] = {}
    wait_months_list: list[float] = []
    voltages: set[float] = set()
    total_mw = 0.0

    for r in rows:
        entry = _row_to_dict(r)
        mw = float(r["tec_mw"] or 0)
        status = r["status"] or "Unknown"
        tech = r["tech_category"] or "other"

        # Technology breakdown
        tech_mw[tech] = tech_mw.get(tech, 0) + mw

        # Status counts
        status_counts[status] = status_counts.get(status, 0) + 1

        # Voltage levels
        if r["voltage_kv"]:
            voltages.add(float(r["voltage_kv"]))

        # Wait time calculation
        wt = _months_between(r["effective_from"], r["connection_date"])
        if wt and wt > 0:
            wait_months_list.append(wt)

        # Classify entries
        if status in WITHDRAWN_STATUSES:
            # Recently withdrawn = within last 12 months
            eff_to = r["effective_to"]
            if eff_to and (today - eff_to).days < 365:
                entry["freed_mw"] = mw
                entry["withdrawn_date"] = _serialise_date(eff_to)
                withdrawn_entries.append(entry)
        elif status in ACTIVE_STATUSES:
            total_mw += mw
            active_entries.append(entry)

            # Stalled check: active but no connection date, or connection date >2yr past
            conn_date = r["connection_date"]
            is_stalled = False
            if conn_date and (today - conn_date).days > STALLED_THRESHOLD_DAYS:
                is_stalled = True
            elif not conn_date and r["effective_from"]:
                if (today - r["effective_from"]).days > STALLED_THRESHOLD_DAYS:
                    is_stalled = True
            if is_stalled:
                entry["stalled_reason"] = "overdue" if conn_date else "no_connection_date"
                stalled_entries.append(entry)
        else:
            total_mw += mw
            active_entries.append(entry)

    avg_wait = round(statistics.mean(wait_months_list), 1) if wait_months_list else None
    queue_depth = len(active_entries)

    return {
        "connection_site": connection_site,
        "queue_depth": queue_depth,
        "total_queued_mw": round(total_mw, 1),
        "avg_wait_months": avg_wait,
        "median_wait_months": round(statistics.median(wait_months_list), 1) if wait_months_list else None,
        "technology_breakdown": {k: round(v, 1) for k, v in tech_mw.items()},
        "status_breakdown": status_counts,
        "voltage_levels": sorted(voltages),
        "competing_projects": active_entries[:20],
        "recently_withdrawn": withdrawn_entries,
        "stalled_projects": stalled_entries,
        "risk_level": _risk_level(queue_depth, total_mw, avg_wait),
        "total_entries_all_statuses": len(rows),
    }


# ---------------------------------------------------------------------------
# 2. predict_offer_timeline — regression-based timeline prediction
# ---------------------------------------------------------------------------

async def predict_offer_timeline(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
    voltage_kv: float | None = None,
    search_radius_km: float = 30.0,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """
    Predict connection offer timeline using TEC register analysis.

    Finds nearest connection sites, analyses queues, and applies
    historical regression to predict P10/P50/P90 offer months.
    """
    voltage = _pick_voltage(capacity_mw, voltage_kv)

    # Find nearest connection sites with geocoded geometry
    nearby = await conn.fetch("""
        SELECT DISTINCT ON (connection_site)
            connection_site,
            voltage_kv,
            ST_X(ST_Transform(geometry, 4326)) AS lon,
            ST_Y(ST_Transform(geometry, 4326)) AS lat,
            ST_Distance(
                geometry,
                ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            ) / 1000.0 AS distance_km
        FROM eso_tec_register
        WHERE geometry IS NOT NULL
          AND connection_site IS NOT NULL
          AND connection_site != ''
        ORDER BY connection_site, ST_Distance(
            geometry,
            ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        )
        LIMIT $3
    """, lon, lat, max_candidates * 3)

    # Filter by radius and deduplicate
    candidates = []
    seen_sites: set[str] = set()
    for r in nearby:
        dist = float(r["distance_km"])
        site = r["connection_site"]
        if dist <= search_radius_km and site not in seen_sites:
            seen_sites.add(site)
            candidates.append({
                "connection_site": site,
                "distance_km": round(dist, 1),
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            })
        if len(candidates) >= max_candidates:
            break

    # If no geocoded results, fall back to text-based search
    if not candidates:
        fallback = await conn.fetch("""
            SELECT connection_site,
                   count(*) AS entries,
                   coalesce(sum(tec_mw), 0) AS total_mw,
                   max(voltage_kv) AS voltage_kv
            FROM eso_tec_register
            WHERE connection_site IS NOT NULL AND connection_site != ''
            GROUP BY connection_site
            ORDER BY total_mw DESC
            LIMIT $1
        """, max_candidates)
        for r in fallback:
            candidates.append({
                "connection_site": r["connection_site"],
                "distance_km": None,
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            })

    # Analyse queue at each candidate
    site_analyses = []
    for cand in candidates:
        q = await analyse_queue(conn, cand["connection_site"])
        cand["queue_analysis"] = {
            "queue_depth": q["queue_depth"],
            "total_queued_mw": q["total_queued_mw"],
            "avg_wait_months": q["avg_wait_months"],
            "risk_level": q["risk_level"],
            "recently_withdrawn_count": len(q["recently_withdrawn"]),
            "stalled_count": len(q["stalled_projects"]),
        }
        site_analyses.append((cand, q))

    # Find similar recent offers for calibration
    similar_offers = await conn.fetch("""
        SELECT tec_id, customer_name, connection_site, tech_category,
               tec_mw, status, effective_from, connection_date, voltage_kv
        FROM eso_tec_register
        WHERE tech_category = $1
          AND tec_mw BETWEEN $2 * 0.5 AND $2 * 2.0
          AND connection_date IS NOT NULL
          AND effective_from IS NOT NULL
        ORDER BY connection_date DESC
        LIMIT 10
    """, technology, capacity_mw)

    calibration_months = []
    similar_list = []
    for r in similar_offers:
        wt = _months_between(r["effective_from"], r["connection_date"])
        if wt and wt > 0:
            calibration_months.append(wt)
            similar_list.append({
                "tec_id": r["tec_id"],
                "customer_name": r["customer_name"],
                "connection_site": r["connection_site"],
                "tec_mw": float(r["tec_mw"] or 0),
                "wait_months": wt,
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            })

    # Calculate predicted offer months per candidate
    base_months = BASE_OFFER_MONTHS.get(voltage, 18.0)
    best_candidate = None
    best_p50 = float("inf")

    for cand, q in site_analyses:
        depth = q["queue_depth"]
        predicted = (
            base_months
            + QUEUE_FACTOR * depth
            + CAPACITY_FACTOR * math.log(max(capacity_mw, 1))
        )

        # Adjust for stalled projects (reduce effective queue)
        stalled_count = len(q["stalled_projects"])
        if stalled_count > 0:
            predicted -= stalled_count * QUEUE_FACTOR * 0.5

        # Adjust for withdrawn projects (opportunity)
        withdrawn_count = len(q["recently_withdrawn"])
        if withdrawn_count > 0:
            predicted -= withdrawn_count * QUEUE_FACTOR * 0.3

        # Calibrate with similar offers if available
        if calibration_months:
            cal_median = statistics.median(calibration_months)
            predicted = 0.6 * predicted + 0.4 * cal_median

        predicted = max(predicted, 3.0)  # Floor of 3 months

        # P10/P50/P90 with ±30% spread
        p10 = round(predicted * 0.7, 1)
        p50 = round(predicted, 1)
        p90 = round(predicted * 1.4, 1)

        cand["estimated_offer_months"] = {"P10": p10, "P50": p50, "P90": p90}

        if p50 < best_p50:
            best_p50 = p50
            best_candidate = cand

    # Queue risk classification
    if best_candidate:
        qa = best_candidate.get("queue_analysis", {})
        queue_risk = qa.get("risk_level", "medium")
    else:
        queue_risk = "unknown"

    return {
        "input": {
            "lat": lat,
            "lon": lon,
            "capacity_mw": capacity_mw,
            "technology": technology,
            "voltage_kv": voltage,
        },
        "recommended_connection_site": best_candidate,
        "all_candidates": candidates,
        "estimated_offer_months": best_candidate["estimated_offer_months"] if best_candidate else None,
        "queue_risk": queue_risk,
        "similar_recent_offers": similar_list,
        "calibration_sample_size": len(calibration_months),
        "model_note": (
            "Timeline = base_months(voltage) + 1.8*queue_depth + 3.5*ln(MW), "
            "calibrated against similar TEC offers where available."
        ),
    }


# ---------------------------------------------------------------------------
# 3. connection_cost_benchmark — UK benchmark costs with regional adjustment
# ---------------------------------------------------------------------------

def connection_cost_benchmark(
    capacity_mw: float,
    voltage_kv: float,
    distance_km: float,
    region: str | None = None,
) -> dict[str, Any]:
    """
    UK connection cost benchmarking with P10/P50/P90.

    Returns cable, switchgear, transformer, application, and total costs
    with regional adjustments.
    """
    v = _pick_voltage(capacity_mw, voltage_kv)

    # Cable cost
    cable_rate = CABLE_COST_PER_KM.get(v, 150_000)
    cable_cost = cable_rate * distance_km

    # Switchgear
    switchgear = SWITCHGEAR_COST.get(v, 200_000)

    # Transformer — pick based on voltage
    tx_key = None
    if v <= 11:
        tx_key = "33/11"
    elif v <= 33:
        tx_key = "132/33" if capacity_mw > 20 else "33/11"
    elif v <= 66:
        tx_key = "132/66"
    elif v <= 132:
        tx_key = "275/132" if capacity_mw > 200 else "132/33"
    elif v <= 275:
        tx_key = "400/132" if capacity_mw > 500 else "275/132"
    else:
        tx_key = "400/132"
    transformer = TRANSFORMER_COST_BY_RATIO.get(tx_key, 2_500_000)

    # Application / design fees (UK typical)
    application_fee = 10_000 if v <= 33 else 50_000 if v <= 132 else 150_000

    # Civils and commissioning (~15% of cable + equipment)
    civils = (cable_cost + switchgear + transformer) * 0.15

    # Base total
    base_total = cable_cost + switchgear + transformer + application_fee + civils

    # Regional multiplier
    region_key = (region or "").lower().replace(" ", "_")
    multiplier = REGIONAL_COST_MULTIPLIER.get(region_key, 1.0)
    adjusted_total = base_total * multiplier

    # P10/P50/P90 (±25% spread for cost uncertainty)
    p10 = round(adjusted_total * 0.80)
    p50 = round(adjusted_total)
    p90 = round(adjusted_total * 1.30)

    return {
        "input": {
            "capacity_mw": capacity_mw,
            "voltage_kv": v,
            "distance_km": distance_km,
            "region": region,
        },
        "breakdown": {
            "cable_gbp": round(cable_cost),
            "cable_rate_per_km": cable_rate,
            "switchgear_gbp": switchgear,
            "transformer_gbp": transformer,
            "transformer_ratio": tx_key,
            "application_fee_gbp": application_fee,
            "civils_commissioning_gbp": round(civils),
        },
        "regional_multiplier": multiplier,
        "total_gbp": {"P10": p10, "P50": p50, "P90": p90},
        "cost_per_mw": {
            "P10": round(p10 / max(capacity_mw, 0.1)),
            "P50": round(p50 / max(capacity_mw, 0.1)),
            "P90": round(p90 / max(capacity_mw, 0.1)),
        },
        "notes": [
            f"Based on UK benchmark rates for {v}kV connection",
            f"Cable: {cable_rate:,.0f} GBP/km x {distance_km:.1f}km",
            f"Regional adjustment: {multiplier:.2f}x ({region or 'national average'})",
            "Excludes reinforcement works, land easements, and DNO charges",
        ],
    }


# ---------------------------------------------------------------------------
# 4. find_opportunities — scan for grid queue opportunities
# ---------------------------------------------------------------------------

async def find_opportunities(
    conn,
    region: str | None = None,
    technology: str | None = None,
    min_headroom_mw: float = 10.0,
    limit: int = 30,
) -> dict[str, Any]:
    """
    Scan TEC register for grid queue opportunities:
    - Recently withdrawn projects (freed capacity)
    - Low-queue connection sites
    - Sites where planning exists (REPD) but TEC is withdrawn
    """

    # 1. Recently withdrawn projects (freed capacity)
    withdrawn_conditions = ["status IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')"]
    withdrawn_params: list[Any] = []
    idx = 1

    if technology:
        withdrawn_conditions.append(f"tech_category = ${idx}")
        withdrawn_params.append(technology)
        idx += 1

    withdrawn_where = " AND ".join(withdrawn_conditions)

    recently_withdrawn = await conn.fetch(f"""
        SELECT tec_id, customer_name, connection_site, tech_category,
               tec_mw, status, effective_to, voltage_kv, zone
        FROM eso_tec_register
        WHERE {withdrawn_where}
          AND effective_to IS NOT NULL
          AND effective_to >= CURRENT_DATE - INTERVAL '18 months'
          AND tec_mw >= ${ idx}
        ORDER BY tec_mw DESC
        LIMIT {limit}
    """, *withdrawn_params, min_headroom_mw)

    freed_opportunities = []
    for r in recently_withdrawn:
        freed_opportunities.append({
            **_row_to_dict(r),
            "opportunity_type": "withdrawn_capacity",
            "freed_mw": float(r["tec_mw"] or 0),
            "months_since_withdrawal": _months_between(
                r["effective_to"], date.today()
            ) if r["effective_to"] else None,
        })

    # 2. Low-queue connection sites (few active projects, known headroom)
    low_queue_conditions = [
        "status NOT IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')",
        "connection_site IS NOT NULL",
        "connection_site != ''",
    ]
    lq_params: list[Any] = []
    lq_idx = 1

    if technology:
        # We don't filter low-queue by technology — we want all low-queue sites
        pass

    low_queue = await conn.fetch("""
        SELECT connection_site,
               count(*) AS queue_depth,
               coalesce(sum(tec_mw), 0) AS total_queued_mw,
               max(voltage_kv) AS max_voltage_kv,
               array_agg(DISTINCT tech_category) AS technologies,
               max(zone) AS zone
        FROM eso_tec_register
        WHERE status NOT IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')
          AND connection_site IS NOT NULL
          AND connection_site != ''
        GROUP BY connection_site
        HAVING count(*) <= 5
        ORDER BY count(*) ASC, sum(tec_mw) ASC
        LIMIT $1
    """, limit)

    low_queue_sites = []
    for r in low_queue:
        low_queue_sites.append({
            "connection_site": r["connection_site"],
            "queue_depth": int(r["queue_depth"]),
            "total_queued_mw": round(float(r["total_queued_mw"]), 1),
            "max_voltage_kv": float(r["max_voltage_kv"]) if r["max_voltage_kv"] else None,
            "technologies": list(r["technologies"]) if r["technologies"] else [],
            "zone": r["zone"],
            "opportunity_type": "low_queue",
        })

    # 3. Cross-reference: REPD projects near withdrawn TEC entries
    # Sites where planning exists but grid connection was withdrawn
    planning_but_no_grid = await conn.fetch("""
        SELECT DISTINCT
            r.repd_id, r.site_name, r.technology AS repd_technology,
            r.capacity_mw AS repd_mw, r.status AS repd_status,
            r.region,
            t.connection_site, t.tec_mw, t.status AS tec_status,
            t.tech_category
        FROM repd_projects r
        JOIN eso_tec_register t
            ON r.geometry IS NOT NULL
            AND t.geometry IS NOT NULL
            AND ST_DWithin(r.geometry, t.geometry, 5000)
        WHERE t.status IN ('Terminated', 'Withdrawn', 'Lapsed')
          AND r.status NOT IN ('Abandoned', 'Refused', 'Withdrawn')
          AND r.capacity_mw >= $1
        ORDER BY r.capacity_mw DESC
        LIMIT $2
    """, min_headroom_mw, limit)

    cross_ref = []
    for r in planning_but_no_grid:
        cross_ref.append({
            "repd_id": r["repd_id"],
            "site_name": r["site_name"],
            "repd_technology": r["repd_technology"],
            "repd_mw": float(r["repd_mw"] or 0),
            "repd_status": r["repd_status"],
            "region": r["region"],
            "connection_site": r["connection_site"],
            "tec_mw": float(r["tec_mw"] or 0),
            "tec_status": r["tec_status"],
            "opportunity_type": "planning_exists_grid_withdrawn",
        })

    # 4. High-headroom sites (large voltage, few projects)
    high_headroom = await conn.fetch("""
        SELECT connection_site,
               max(voltage_kv) AS voltage_kv,
               count(*) AS active_projects,
               coalesce(sum(tec_mw), 0) AS total_queued_mw,
               max(zone) AS zone
        FROM eso_tec_register
        WHERE status NOT IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')
          AND voltage_kv >= 132
          AND connection_site IS NOT NULL
        GROUP BY connection_site
        HAVING count(*) <= 3 AND coalesce(sum(tec_mw), 0) < 500
        ORDER BY max(voltage_kv) DESC, count(*) ASC
        LIMIT $1
    """, limit)

    headroom_sites = []
    for r in high_headroom:
        headroom_sites.append({
            "connection_site": r["connection_site"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            "active_projects": int(r["active_projects"]),
            "total_queued_mw": round(float(r["total_queued_mw"]), 1),
            "zone": r["zone"],
            "opportunity_type": "high_headroom",
        })

    # Score and rank all opportunities
    all_opps = freed_opportunities + low_queue_sites + cross_ref + headroom_sites

    return {
        "total_opportunities": len(all_opps),
        "filters": {
            "region": region,
            "technology": technology,
            "min_headroom_mw": min_headroom_mw,
        },
        "freed_capacity": {
            "count": len(freed_opportunities),
            "total_freed_mw": round(sum(o.get("freed_mw", 0) for o in freed_opportunities), 1),
            "entries": freed_opportunities,
        },
        "low_queue_sites": {
            "count": len(low_queue_sites),
            "entries": low_queue_sites,
        },
        "planning_but_no_grid": {
            "count": len(cross_ref),
            "entries": cross_ref,
        },
        "high_headroom_sites": {
            "count": len(headroom_sites),
            "entries": headroom_sites,
        },
    }


# ---------------------------------------------------------------------------
# 5. queue_summary — UK-wide queue statistics
# ---------------------------------------------------------------------------

async def queue_summary(conn) -> dict[str, Any]:
    """UK-wide TEC queue statistics."""

    total = await conn.fetchrow("""
        SELECT count(*) AS total_entries,
               coalesce(sum(tec_mw), 0) AS total_mw,
               count(DISTINCT connection_site) AS unique_sites
        FROM eso_tec_register
    """)

    active = await conn.fetchrow("""
        SELECT count(*) AS entries,
               coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        WHERE status NOT IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')
    """)

    by_tech = await conn.fetch("""
        SELECT tech_category,
               count(*) AS entries,
               coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        GROUP BY tech_category
        ORDER BY total_mw DESC
    """)

    by_status = await conn.fetch("""
        SELECT status,
               count(*) AS entries,
               coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        GROUP BY status
        ORDER BY entries DESC
    """)

    by_voltage = await conn.fetch("""
        SELECT voltage_kv,
               count(*) AS entries,
               coalesce(sum(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        WHERE voltage_kv IS NOT NULL
        GROUP BY voltage_kv
        ORDER BY voltage_kv DESC
    """)

    busiest_sites = await conn.fetch("""
        SELECT connection_site,
               count(*) AS queue_depth,
               coalesce(sum(tec_mw), 0) AS total_mw,
               max(voltage_kv) AS max_voltage_kv,
               array_agg(DISTINCT tech_category) AS technologies
        FROM eso_tec_register
        WHERE connection_site IS NOT NULL AND connection_site != ''
          AND status NOT IN ('Terminated', 'Withdrawn', 'Lapsed', 'Refused')
        GROUP BY connection_site
        ORDER BY count(*) DESC
        LIMIT 20
    """)

    # Average wait time from offers with both dates
    avg_wait = await conn.fetchrow("""
        SELECT avg(connection_date - effective_from) AS avg_days,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY connection_date - effective_from) AS median_days,
               count(*) AS sample_size
        FROM eso_tec_register
        WHERE connection_date IS NOT NULL
          AND effective_from IS NOT NULL
          AND connection_date > effective_from
    """)

    avg_wait_months = round(float(avg_wait["avg_days"]) / 30.44, 1) if avg_wait["avg_days"] else None
    median_wait_months = round(float(avg_wait["median_days"]) / 30.44, 1) if avg_wait["median_days"] else None

    # Recent activity (last 6 months)
    recent = await conn.fetchrow("""
        SELECT count(*) FILTER (WHERE effective_from >= CURRENT_DATE - INTERVAL '6 months') AS new_entries,
               count(*) FILTER (WHERE status IN ('Terminated', 'Withdrawn') AND effective_to >= CURRENT_DATE - INTERVAL '6 months') AS withdrawn,
               coalesce(sum(tec_mw) FILTER (WHERE effective_from >= CURRENT_DATE - INTERVAL '6 months'), 0) AS new_mw,
               coalesce(sum(tec_mw) FILTER (WHERE status IN ('Terminated', 'Withdrawn') AND effective_to >= CURRENT_DATE - INTERVAL '6 months'), 0) AS withdrawn_mw
        FROM eso_tec_register
    """)

    return {
        "total_entries": int(total["total_entries"]),
        "total_mw": round(float(total["total_mw"]), 1),
        "unique_connection_sites": int(total["unique_sites"]),
        "active": {
            "entries": int(active["entries"]),
            "total_mw": round(float(active["total_mw"]), 1),
        },
        "avg_wait_months": avg_wait_months,
        "median_wait_months": median_wait_months,
        "wait_sample_size": int(avg_wait["sample_size"]) if avg_wait["sample_size"] else 0,
        "by_technology": [
            {"technology": r["tech_category"], "entries": int(r["entries"]), "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_tech
        ],
        "by_status": [
            {"status": r["status"], "entries": int(r["entries"]), "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_status
        ],
        "by_voltage_kv": [
            {"voltage_kv": float(r["voltage_kv"]), "entries": int(r["entries"]), "total_mw": round(float(r["total_mw"]), 1)}
            for r in by_voltage
        ],
        "busiest_sites": [
            {
                "connection_site": r["connection_site"],
                "queue_depth": int(r["queue_depth"]),
                "total_mw": round(float(r["total_mw"]), 1),
                "max_voltage_kv": float(r["max_voltage_kv"]) if r["max_voltage_kv"] else None,
                "technologies": list(r["technologies"]) if r["technologies"] else [],
            }
            for r in busiest_sites
        ],
        "recent_6_months": {
            "new_entries": int(recent["new_entries"]),
            "new_mw": round(float(recent["new_mw"]), 1),
            "withdrawn": int(recent["withdrawn"]),
            "withdrawn_mw": round(float(recent["withdrawn_mw"]), 1),
        },
    }
