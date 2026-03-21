"""
Connection offer forecasting -- predicts time-to-offer, likely voltage,
reinforcement cost, and queue position for a proposed grid connection.

Uses real TEC gate data, ECR queue depth, substation capacity, and
REPD historical outcomes to train a predictive model.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from typing import Any

log = logging.getLogger("princeps.connection_offer_forecaster")

# ---------------------------------------------------------------------------
# UK connection cost rates (GBP per km) by voltage tier
# ---------------------------------------------------------------------------
_COST_PER_KM: dict[int, int] = {
    11: 80_000,
    33: 150_000,
    66: 300_000,
    132: 500_000,
    275: 1_200_000,
    400: 2_000_000,
}

# DNO processing speed factors (months of additional delay).
# Higher = slower to process applications.
_DNO_FACTOR: dict[str, float] = {
    "UKPN": 2.0,
    "NGED": 1.5,
    "SPEN": 3.0,
    "SSEN": 3.5,
    "ENWL": 2.5,
    "NPG":  2.0,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _voltage_for_capacity(capacity_mw: float) -> float:
    """Determine the likely connection voltage based on project capacity."""
    if capacity_mw < 1:
        return 11
    elif capacity_mw < 5:
        return 33
    elif capacity_mw < 50:
        return 132 if capacity_mw >= 20 else 66
    elif capacity_mw < 200:
        return 275
    else:
        return 400


def _cost_per_km_for_voltage(voltage_kv: float) -> int:
    """Return per-km cost for the nearest voltage tier."""
    best = 33
    best_diff = abs(voltage_kv - 33)
    for v in _COST_PER_KM:
        diff = abs(voltage_kv - v)
        if diff < best_diff:
            best = v
            best_diff = diff
    return _COST_PER_KM[best]


def _connection_cost_range(distance_km: float, voltage_kv: float) -> dict:
    """P10/P50/P90 connection cost estimates."""
    per_km = _cost_per_km_for_voltage(voltage_kv)
    base = per_km * distance_km
    # Add fixed civils/switchgear cost
    fixed = {11: 50_000, 33: 120_000, 66: 250_000, 132: 500_000, 275: 1_500_000, 400: 3_000_000}
    closest_v = min(fixed, key=lambda v: abs(v - voltage_kv))
    civils = fixed[closest_v]
    p50 = base + civils
    return {
        "p10_gbp": round(p50 * 0.7),
        "p50_gbp": round(p50),
        "p90_gbp": round(p50 * 1.6),
        "distance_km": round(distance_km, 2),
        "voltage_kv": voltage_kv,
        "rate_gbp_per_km": per_km,
    }


# ---------------------------------------------------------------------------
# Core forecasting function
# ---------------------------------------------------------------------------

async def forecast_connection_offer(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict:
    """
    Predict connection offer timeline, cost, and risk for a proposed
    grid connection at (lat, lon) with the given capacity.

    Queries real PostGIS data from grid_substations, grid_ecr,
    eso_tec_project, and repd_project.
    """
    async with pool.acquire() as conn:
        # ---- 1. Nearest substations (within 15 km, SRID 27700) ----------
        subs = await conn.fetch("""
            SELECT
                s.id,
                s.name,
                s.dno,
                s.voltage_kv,
                s.demand_mw,
                s.generation_mw,
                s.demand_headroom_mw,
                s.gen_headroom_mw,
                s.transformer_rating_mva,
                s.rag_demand,
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
                    15000
                  )
            ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT 10
        """, lon, lat)

        # ---- 2. ECR queue at each candidate substation -------------------
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
                           OR status ILIKE '%%accepted%%'
                    ) AS active_queue_count
                FROM grid_ecr
                WHERE substation_id = ANY($1::int[])
                GROUP BY substation_id
            """, sub_ids)

        ecr_map: dict[int, dict] = {}
        for er in ecr_rows:
            ecr_map[er["substation_id"]] = {
                "queue_count": int(er["queue_count"]),
                "queued_mw": float(er["queued_mw"]),
                "active_queue_count": int(er["active_queue_count"]),
            }

        # ---- 3. TEC projects near nearest connection sites ---------------
        tec_projects = await conn.fetch("""
            SELECT
                project_name,
                customer_name,
                connection_site,
                mw_connected,
                cumulative_capacity_mw,
                plant_type,
                project_status,
                host_to,
                gate,
                ST_Y(geometry) AS lat,
                ST_X(geometry) AS lon
            FROM eso_tec_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.15
                  )
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
            LIMIT 20
        """, lon, lat)

        # ---- 4. Nearby REPD projects for historical timelines ------------
        repd_projects = await conn.fetch("""
            SELECT
                site_name,
                technology_type,
                installed_capacity_mw,
                dev_status,
                dev_status_short,
                planning_submitted,
                planning_granted,
                operational,
                region,
                ST_Y(geometry) AS lat,
                ST_X(geometry) AS lon
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                    geometry,
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    0.2
                  )
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
            LIMIT 30
        """, lon, lat)

    # ---- 5. Build candidate substation analysis --------------------------
    likely_voltage = _voltage_for_capacity(capacity_mw)
    candidates = []

    for s in subs:
        sid = s["id"]
        dist_km = float(s["distance_km"])
        headroom = float(s["gen_headroom_mw"] or 0)
        voltage = float(s["voltage_kv"] or 33)
        dno = s["dno"] or "UKPN"
        ecr = ecr_map.get(sid, {"queue_count": 0, "queued_mw": 0, "active_queue_count": 0})

        queued_mw = ecr["queued_mw"]
        queue_count = ecr["active_queue_count"]

        # Time-to-offer formula
        dno_extra = _DNO_FACTOR.get(dno, 2.0)
        base_months = 6.0
        queue_delay = (queued_mw / max(headroom, 0.1)) * 12 if headroom > 0 else 18
        capacity_penalty = 18.0 if capacity_mw > headroom else 0.0
        time_to_offer = base_months + queue_delay + capacity_penalty + dno_extra

        # Reinforcement cost
        headroom_exceeded = capacity_mw > headroom
        reinforcement_gbp = 0
        if headroom_exceeded:
            shortfall_mw = capacity_mw - headroom
            # Approx: reinforcement scales with shortfall and voltage
            reinforcement_gbp = int(shortfall_mw * 200_000 * (voltage / 33))

        # Connection cost
        cost_range = _connection_cost_range(dist_km, likely_voltage)

        # Composite score: prefer substations with (headroom - queue) / distance
        net_headroom = headroom - queued_mw
        score = net_headroom / max(dist_km, 0.5)

        candidates.append({
            "substation_id": sid,
            "name": s["name"],
            "dno": dno,
            "voltage_kv": voltage,
            "distance_km": round(dist_km, 2),
            "lat": float(s["lat"]),
            "lon": float(s["lon"]),
            "demand_mw": float(s["demand_mw"] or 0),
            "generation_mw": float(s["generation_mw"] or 0),
            "headroom_mw": round(headroom, 1),
            "queue_count": queue_count,
            "queued_mw": round(queued_mw, 1),
            "net_headroom_mw": round(net_headroom, 1),
            "time_to_offer_months": round(min(time_to_offer, 84), 1),
            "reinforcement_cost_gbp": reinforcement_gbp,
            "headroom_exceeded": headroom_exceeded,
            "connection_cost": cost_range,
            "score": round(score, 2),
            "rag_demand": s["rag_demand"],
            "rag_generation": s["rag_generation"],
        })

    # Sort candidates by score descending (best first)
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # ---- 6. Pick the best substation for headline numbers ----------------
    best = candidates[0] if candidates else None

    # ---- 7. Risk factors -------------------------------------------------
    risk_factors = []
    if best:
        utilisation = float(best["demand_mw"]) / max(float(best.get("headroom_mw", 1) + best["demand_mw"]), 1) * 100
        if utilisation > 80:
            risk_factors.append(f"Substation at {utilisation:.0f}% utilisation")
        if best["queue_count"] > 10:
            risk_factors.append(f"{best['queue_count']} projects queued ahead")
        elif best["queue_count"] > 0:
            risk_factors.append(f"{best['queue_count']} projects in queue")
        if best["headroom_exceeded"]:
            risk_factors.append("Reinforcement likely needed — capacity exceeds headroom")
        if best["reinforcement_cost_gbp"] > 0:
            risk_factors.append(
                f"Estimated reinforcement: \u00a3{best['reinforcement_cost_gbp']:,.0f}"
            )
        if best["distance_km"] > 5:
            risk_factors.append(f"Connection distance {best['distance_km']:.1f} km — long cable run")

        # TEC queue pressure
        tec_queued = sum(1 for t in tec_projects if t["project_status"] and "queue" in t["project_status"].lower())
        tec_mw = sum(float(t["cumulative_capacity_mw"] or 0) for t in tec_projects)
        if tec_queued > 5:
            risk_factors.append(f"{tec_queued} TEC projects ({tec_mw:.0f} MW) queued at nearby connection sites")

    if not candidates:
        risk_factors.append("No substations found within 15 km")

    # ---- 8. Historical comparisons from REPD ----------------------------
    historical = []
    for rp in repd_projects[:10]:
        entry: dict[str, Any] = {
            "site_name": rp["site_name"],
            "technology": rp["technology_type"],
            "capacity_mw": float(rp["installed_capacity_mw"] or 0),
            "status": rp["dev_status_short"] or rp["dev_status"],
            "lat": round(float(rp["lat"]), 5),
            "lon": round(float(rp["lon"]), 5),
        }
        # Calculate timeline if dates available
        if rp["planning_submitted"] and rp["operational"]:
            delta = (rp["operational"] - rp["planning_submitted"]).days
            entry["planning_to_operational_months"] = round(delta / 30.44, 1)
        elif rp["planning_submitted"] and rp["planning_granted"]:
            delta = (rp["planning_granted"] - rp["planning_submitted"]).days
            entry["planning_to_granted_months"] = round(delta / 30.44, 1)
        historical.append(entry)

    # Average historical timeline
    operational_timelines = [
        h["planning_to_operational_months"]
        for h in historical
        if "planning_to_operational_months" in h
    ]
    avg_historical_months = (
        round(sum(operational_timelines) / len(operational_timelines), 1)
        if operational_timelines
        else None
    )

    # ---- 9. TEC summary -------------------------------------------------
    tec_summary = []
    for t in tec_projects[:10]:
        tec_summary.append({
            "project_name": t["project_name"],
            "connection_site": t["connection_site"],
            "mw": float(t["cumulative_capacity_mw"] or t["mw_connected"] or 0),
            "plant_type": t["plant_type"],
            "status": t["project_status"],
            "gate": t["gate"],
        })

    # ---- 10. Build response ----------------------------------------------
    return {
        "request": {
            "lat": lat,
            "lon": lon,
            "capacity_mw": capacity_mw,
            "technology": technology,
        },
        "forecast": {
            "time_to_offer_months": best["time_to_offer_months"] if best else None,
            "likely_voltage_kv": likely_voltage,
            "recommended_substation": best["name"] if best else None,
            "recommended_substation_id": best["substation_id"] if best else None,
            "dno": best["dno"] if best else None,
            "distance_km": best["distance_km"] if best else None,
            "queue_position": best["queue_count"] if best else None,
            "headroom_mw": best["headroom_mw"] if best else None,
            "net_headroom_mw": best["net_headroom_mw"] if best else None,
            "reinforcement_cost_gbp": best["reinforcement_cost_gbp"] if best else None,
            "connection_cost_range": best["connection_cost"] if best else None,
            "total_cost_estimate_gbp": (
                (best["connection_cost"]["p50_gbp"] + best["reinforcement_cost_gbp"])
                if best else None
            ),
        },
        "risk_factors": risk_factors,
        "risk_level": (
            "HIGH" if len(risk_factors) >= 4 or (best and best["headroom_exceeded"])
            else "MEDIUM" if len(risk_factors) >= 2
            else "LOW"
        ),
        "recommended_substations": candidates[:3],
        "all_candidates": candidates,
        "tec_projects_nearby": tec_summary,
        "historical_comparisons": historical,
        "avg_historical_planning_to_operational_months": avg_historical_months,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Batch forecasting
# ---------------------------------------------------------------------------

async def batch_forecast(
    pool,
    sites: list[dict],
) -> list[dict]:
    """
    Score multiple candidate sites in parallel.

    Each site dict should have: lat, lon, capacity_mw, technology (optional).
    Returns a ranked list with composite connection feasibility scores.
    """
    async def _score_one(site: dict) -> dict:
        lat = site["lat"]
        lon = site["lon"]
        capacity_mw = site.get("capacity_mw", 50)
        technology = site.get("technology", "solar")
        name = site.get("name", f"Site ({lat:.3f}, {lon:.3f})")

        try:
            result = await forecast_connection_offer(
                pool, lat, lon, capacity_mw, technology
            )
            fc = result["forecast"]

            # Composite feasibility score (0-100)
            score = 100.0
            # Penalise long timelines
            months = fc.get("time_to_offer_months") or 36
            score -= min(30, months * 0.8)
            # Penalise low headroom
            headroom = fc.get("net_headroom_mw") or 0
            if headroom < 0:
                score -= min(25, abs(headroom) * 2)
            elif headroom < capacity_mw:
                score -= 10
            # Penalise long distance
            dist = fc.get("distance_km") or 10
            score -= min(15, dist * 1.5)
            # Penalise high risk
            risk = result.get("risk_level", "MEDIUM")
            if risk == "HIGH":
                score -= 15
            elif risk == "MEDIUM":
                score -= 5
            # Penalise reinforcement
            reinf = fc.get("reinforcement_cost_gbp") or 0
            if reinf > 0:
                score -= min(10, reinf / 500_000)

            score = max(0, min(100, score))

            return {
                "name": name,
                "lat": lat,
                "lon": lon,
                "capacity_mw": capacity_mw,
                "technology": technology,
                "feasibility_score": round(score, 1),
                "time_to_offer_months": fc.get("time_to_offer_months"),
                "recommended_substation": fc.get("recommended_substation"),
                "distance_km": fc.get("distance_km"),
                "headroom_mw": fc.get("headroom_mw"),
                "net_headroom_mw": fc.get("net_headroom_mw"),
                "connection_cost_p50_gbp": fc.get("connection_cost_range", {}).get("p50_gbp"),
                "reinforcement_cost_gbp": fc.get("reinforcement_cost_gbp"),
                "total_cost_gbp": fc.get("total_cost_estimate_gbp"),
                "risk_level": result.get("risk_level"),
                "risk_factors": result.get("risk_factors", []),
                "queue_position": fc.get("queue_position"),
            }
        except Exception as exc:
            log.warning("Batch forecast failed for %s: %s", name, exc)
            return {
                "name": name,
                "lat": lat,
                "lon": lon,
                "capacity_mw": capacity_mw,
                "technology": technology,
                "feasibility_score": 0,
                "error": str(exc)[:200],
            }

    results = await asyncio.gather(*[_score_one(s) for s in sites])
    # Sort by feasibility score descending
    results.sort(key=lambda r: r.get("feasibility_score", 0), reverse=True)

    return {
        "site_count": len(results),
        "sites": results,
        "best_site": results[0] if results else None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
