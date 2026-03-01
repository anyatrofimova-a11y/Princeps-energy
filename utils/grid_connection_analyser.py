"""
Grid Connection Analyser — three-tier feasibility assessment.

Tier 1 (Data-driven): Instant lookup of published DNO headroom + queue depth.
Tier 2 (Power flow): pandapower simulation via subprocess bridge.
Tier 3 (Transmission): PyPSA-GB model (future).

Called from FastAPI endpoints and agent module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from math import atan2, cos, radians, sin, sqrt
from typing import Any

log = logging.getLogger("princeps.grid_connection_analyser")

# Connection cost parameters (UK typical rates, GBP)
CABLE_COST_PER_KM = {
    11: 80_000,
    33: 150_000,
    66: 300_000,
    132: 500_000,
    275: 800_000,
    400: 1_200_000,
}

SWITCHGEAR_COST = {
    11: 25_000,
    33: 200_000,
    66: 350_000,
    132: 500_000,
}

TRANSFORMER_COST = {
    "11/0.4": 15_000,
    "33/11": 250_000,
    "66/33": 400_000,
    "132/33": 2_500_000,
    "132/66": 3_500_000,
    "275/132": 8_000_000,
    "400/132": 12_000_000,
}


# ─── Tier 1: Data-Driven Assessment ──────────────────────────────────────

async def assess_connection(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
    search_radius_km: float = 20.0,
    max_substations: int = 5,
) -> dict[str, Any]:
    """
    Assess grid connection feasibility using published DNO data.

    Returns:
        Dict with nearest substations, headroom analysis, cost estimate,
        queue depth, and RAG verdict.
    """
    t0 = time.time()

    # 1. Find nearest substations with headroom data
    substations = await _find_nearest_substations(
        conn, lat, lon, search_radius_km, max_substations,
    )

    # 2. Identify the DNO area
    dno_area = await _identify_dno(conn, lat, lon)

    # 3. Check connection queue at each substation
    for sub in substations:
        sub["queue"] = await _check_queue(conn, sub["id"], sub["name"])

    # 4. Assess each substation as a connection candidate
    candidates = []
    for sub in substations:
        candidate = _assess_candidate(sub, capacity_mw, technology)
        candidates.append(candidate)

    # Sort by suitability score (descending)
    candidates.sort(key=lambda c: c["suitability_score"], reverse=True)

    # 5. Overall verdict
    best = candidates[0] if candidates else None
    verdict = _derive_verdict(best, capacity_mw)

    # 6. Cost estimate for best candidate
    cost_estimate = None
    if best:
        cost_estimate = estimate_connection_cost(
            distance_km=best["distance_km"],
            capacity_mw=capacity_mw,
            voltage_kv=best.get("voltage_kv", 33),
        )

    elapsed = round(time.time() - t0, 3)

    return {
        "location": {"lat": lat, "lon": lon},
        "capacity_mw": capacity_mw,
        "technology": technology,
        "dno_area": dno_area,
        "verdict": verdict["verdict"],
        "confidence": verdict["confidence"],
        "summary": verdict["summary"],
        "candidates": candidates,
        "best_candidate": best,
        "cost_estimate": cost_estimate,
        "risks": verdict["risks"],
        "tier": "data",
        "elapsed_s": elapsed,
    }


async def _find_nearest_substations(
    conn, lat: float, lon: float, radius_km: float, limit: int,
) -> list[dict]:
    """Find substations within radius, ordered by distance."""
    rows = await conn.fetch("""
        SELECT
            id, external_id, name, dno, region, voltage_kv, site_type,
            demand_mw, generation_mw, demand_headroom_mw, gen_headroom_mw,
            fault_level_ka, transformer_rating_mva,
            rag_demand, rag_generation,
            ST_Distance(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            ) / 1000.0 AS distance_km,
            ST_X(ST_Transform(geom, 4326)) AS sub_lon,
            ST_Y(ST_Transform(geom, 4326)) AS sub_lat
        FROM grid_substations
        WHERE ST_DWithin(
            geom,
            ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
            $3
        )
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT $4
    """, lon, lat, radius_km * 1000, limit)

    return [
        {
            "id": r["id"],
            "external_id": r["external_id"],
            "name": r["name"],
            "dno": r["dno"],
            "region": r["region"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            "site_type": r["site_type"],
            "demand_mw": float(r["demand_mw"]) if r["demand_mw"] else None,
            "generation_mw": float(r["generation_mw"]) if r["generation_mw"] else None,
            "demand_headroom_mw": float(r["demand_headroom_mw"]) if r["demand_headroom_mw"] else None,
            "gen_headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] else None,
            "fault_level_ka": float(r["fault_level_ka"]) if r["fault_level_ka"] else None,
            "transformer_rating_mva": float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] else None,
            "rag_demand": r["rag_demand"],
            "rag_generation": r["rag_generation"],
            "distance_km": round(float(r["distance_km"]), 2),
            "lat": float(r["sub_lat"]),
            "lon": float(r["sub_lon"]),
        }
        for r in rows
    ]


async def _identify_dno(conn, lat: float, lon: float) -> dict | None:
    """Identify which DNO licence area covers this location."""
    row = await conn.fetchrow("""
        SELECT dno_code, dno_name, long_name
        FROM grid_dno_boundaries
        WHERE ST_Contains(
            geom,
            ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        )
        LIMIT 1
    """, lon, lat)

    if row:
        return {"code": row["dno_code"], "name": row["dno_name"], "long_name": row["long_name"]}
    return None


async def _check_queue(conn, substation_id: int, substation_name: str) -> dict:
    """Check connection queue depth at a substation."""
    # Check grid_ecr for queued/accepted entries
    ecr_row = await conn.fetchrow("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status ILIKE '%queue%' OR status ILIKE '%accepted%') AS queued,
            COALESCE(SUM(capacity_mw) FILTER (WHERE status ILIKE '%queue%' OR status ILIKE '%accepted%'), 0) AS queued_mw,
            COALESCE(SUM(capacity_mw), 0) AS total_mw
        FROM grid_ecr
        WHERE substation_id = $1
    """, substation_id)

    # Also check TEC register for transmission-connected nearby
    tec_row = await conn.fetchrow("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(tec_mw), 0) AS total_mw
        FROM eso_tec_register
        WHERE connection_site ILIKE $1
    """, f"%{substation_name}%")

    return {
        "ecr_total": int(ecr_row["total"]) if ecr_row else 0,
        "ecr_queued": int(ecr_row["queued"]) if ecr_row else 0,
        "ecr_queued_mw": round(float(ecr_row["queued_mw"]), 1) if ecr_row else 0,
        "ecr_total_mw": round(float(ecr_row["total_mw"]), 1) if ecr_row else 0,
        "tec_count": int(tec_row["cnt"]) if tec_row else 0,
        "tec_mw": round(float(tec_row["total_mw"]), 1) if tec_row else 0,
    }


def _assess_candidate(sub: dict, capacity_mw: float, technology: str) -> dict:
    """Score a substation as a connection candidate."""
    score = 0.0
    notes = []
    risks = []

    # Headroom assessment (generation for solar/wind/bess, demand for loads)
    headroom_field = "gen_headroom_mw" if technology in ("solar", "wind", "bess") else "demand_headroom_mw"
    headroom = sub.get(headroom_field)

    if headroom is not None:
        if headroom >= capacity_mw:
            score += 40
            notes.append(f"Sufficient headroom: {headroom:.1f} MW available vs {capacity_mw:.1f} MW requested")
        elif headroom >= capacity_mw * 0.5:
            score += 20
            notes.append(f"Partial headroom: {headroom:.1f} MW available — may require reinforcement")
            risks.append("Headroom below requested capacity — reinforcement likely needed")
        else:
            score += 5
            notes.append(f"Insufficient headroom: {headroom:.1f} MW vs {capacity_mw:.1f} MW")
            risks.append("Significant reinforcement required — long timeline and high cost likely")
    else:
        score += 15  # Unknown headroom — neutral
        notes.append("Headroom data unavailable — DNO study required")

    # Distance scoring
    distance = sub["distance_km"]
    if distance <= 1:
        score += 30
        notes.append(f"Very close: {distance:.1f} km cable run")
    elif distance <= 3:
        score += 25
        notes.append(f"Short cable run: {distance:.1f} km")
    elif distance <= 5:
        score += 15
        notes.append(f"Moderate cable distance: {distance:.1f} km")
    elif distance <= 10:
        score += 5
        notes.append(f"Long cable run: {distance:.1f} km — consider higher voltage")
        risks.append(f"Cable distance {distance:.1f} km increases cost and losses")
    else:
        notes.append(f"Very long cable run: {distance:.1f} km")
        risks.append("Cable distance likely prohibitive — consider alternative connection point")

    # Voltage level match
    voltage = sub.get("voltage_kv")
    if voltage:
        recommended_voltage = _recommended_voltage(capacity_mw)
        if voltage >= recommended_voltage:
            score += 15
        else:
            score += 5
            risks.append(f"Substation voltage {voltage} kV may be low for {capacity_mw} MW — transformer needed")

    # Queue impact
    queue = sub.get("queue", {})
    queued_mw = queue.get("ecr_queued_mw", 0)
    if headroom and queued_mw > 0:
        effective_headroom = headroom - queued_mw
        if effective_headroom < capacity_mw:
            score -= 10
            risks.append(
                f"Queue competition: {queued_mw:.1f} MW already queued reduces effective headroom to {effective_headroom:.1f} MW"
            )

    # RAG status
    rag_field = "rag_generation" if technology in ("solar", "wind", "bess") else "rag_demand"
    rag = sub.get(rag_field, "").lower() if sub.get(rag_field) else None
    if rag == "green":
        score += 15
    elif rag == "amber":
        score += 8
        notes.append("Amber RAG — limited capacity, accept subject to DNO study")
    elif rag == "red":
        score -= 5
        risks.append("Red RAG — no available capacity without reinforcement")

    return {
        **sub,
        "suitability_score": max(0, min(100, round(score))),
        "notes": notes,
        "risks": risks,
    }


def _derive_verdict(best: dict | None, capacity_mw: float) -> dict:
    """Produce GO/CAUTION/NO-GO verdict from best candidate."""
    if not best:
        return {
            "verdict": "NO-GO",
            "confidence": 0.3,
            "summary": "No substations found within search radius. Site may be too remote for economical grid connection.",
            "risks": ["No suitable connection point identified"],
        }

    score = best["suitability_score"]
    risks = best.get("risks", [])

    if score >= 70:
        return {
            "verdict": "GO",
            "confidence": min(0.9, score / 100),
            "summary": (
                f"Strong connection opportunity at {best['name']} ({best['dno'].upper()}). "
                f"{best['distance_km']:.1f} km cable run, "
                f"{'sufficient' if (best.get('gen_headroom_mw') or 0) >= capacity_mw else 'available'} headroom."
            ),
            "risks": risks,
        }
    elif score >= 40:
        return {
            "verdict": "CAUTION",
            "confidence": score / 100,
            "summary": (
                f"Connection possible at {best['name']} ({best['dno'].upper()}) but constraints identified. "
                f"{best['distance_km']:.1f} km distance. "
                "DNO pre-application study recommended before proceeding."
            ),
            "risks": risks,
        }
    else:
        return {
            "verdict": "NO-GO",
            "confidence": max(0.3, 1 - score / 100),
            "summary": (
                f"Grid connection at {best['name']} is challenging. "
                f"Significant constraints: {'; '.join(risks[:2]) if risks else 'limited capacity'}. "
                "Consider alternative sites or connection strategy."
            ),
            "risks": risks,
        }


# ─── Cost Estimation ─────────────────────────────────────────────────────

def estimate_connection_cost(
    distance_km: float,
    capacity_mw: float,
    voltage_kv: float = 33,
) -> dict:
    """
    Probabilistic connection cost estimate (P10/P50/P90).
    Based on published UK DNO connection cost data and industry benchmarks.
    """
    vkv = int(voltage_kv)
    cable_rate = CABLE_COST_PER_KM.get(vkv, CABLE_COST_PER_KM.get(33, 150_000))
    cable_cost = distance_km * cable_rate

    # Switchgear
    sg_cost = SWITCHGEAR_COST.get(vkv, 200_000)

    # Transformer (if voltage step needed)
    xfmr_cost = 0
    rec_v = _recommended_voltage(capacity_mw)
    if rec_v != vkv:
        key = f"{vkv}/{rec_v}" if vkv > rec_v else f"{rec_v}/{vkv}"
        xfmr_cost = TRANSFORMER_COST.get(key, capacity_mw * 50_000)

    # DNO application & design fees
    if capacity_mw <= 0.05:
        dno_fee = 2_000
    elif capacity_mw <= 1:
        dno_fee = 10_000
    elif capacity_mw <= 10:
        dno_fee = 30_000
    else:
        dno_fee = 50_000 + capacity_mw * 2_000

    # Reinforcement estimate (if headroom likely insufficient)
    reinforcement = 0
    if capacity_mw > 10:
        reinforcement = capacity_mw * 15_000
    elif capacity_mw > 50:
        reinforcement = capacity_mw * 25_000

    # Protection & metering
    protection = 15_000 if capacity_mw > 1 else 5_000

    # Civils & wayleaves
    civils = distance_km * 30_000  # trenching, reinstatement

    base_total = cable_cost + sg_cost + xfmr_cost + dno_fee + protection + civils

    # P10/P50/P90 range
    p50 = round(base_total + reinforcement * 0.5)
    p10 = round(base_total * 0.75)
    p90 = round((base_total + reinforcement) * 1.3)

    # Timeline
    if capacity_mw <= 0.05:
        timeline_weeks = {"p10": 8, "p50": 12, "p90": 20}
    elif capacity_mw <= 1:
        timeline_weeks = {"p10": 12, "p50": 20, "p90": 36}
    elif capacity_mw <= 10:
        timeline_weeks = {"p10": 20, "p50": 36, "p90": 52}
    elif capacity_mw <= 50:
        timeline_weeks = {"p10": 36, "p50": 52, "p90": 78}
    else:
        timeline_weeks = {"p10": 52, "p50": 78, "p90": 130}

    return {
        "cost_gbp": {"p10": p10, "p50": p50, "p90": p90},
        "breakdown": {
            "cable": round(cable_cost),
            "switchgear": sg_cost,
            "transformer": xfmr_cost,
            "dno_fees": round(dno_fee),
            "protection_metering": protection,
            "civils_wayleaves": round(civils),
            "reinforcement_estimate": round(reinforcement * 0.5),
        },
        "timeline_weeks": timeline_weeks,
        "connection_voltage_kv": vkv,
        "cable_distance_km": round(distance_km, 2),
        "capacity_mw": capacity_mw,
        "g99_required": capacity_mw > 0.01668,  # > 16.68 kW per phase (50 kW 3-phase)
        "notes": _cost_notes(capacity_mw, distance_km, vkv),
    }


def _cost_notes(capacity_mw: float, distance_km: float, voltage_kv: int) -> list[str]:
    """Advisory notes for connection cost estimate."""
    notes = []
    if capacity_mw <= 0.003_68:
        notes.append("Below 3.68 kW: G98 notification only — no formal application")
    elif capacity_mw <= 0.05:
        notes.append("Below 50 kW: G99 Stage 1 — typically 8-12 weeks")
    elif capacity_mw <= 1:
        notes.append("G99 Stage 2 required — DNO assessment within 45 working days")
    else:
        notes.append("Formal connection application — full technical design required")

    if capacity_mw > 50:
        notes.append("NESO involvement likely for transmission impacts")
    if distance_km > 5:
        notes.append(f"Long cable run ({distance_km:.1f} km) — consider higher voltage to reduce losses")
    if voltage_kv <= 11 and capacity_mw > 1:
        notes.append("Capacity exceeds typical 11 kV limit — 33 kV connection recommended")

    return notes


def _recommended_voltage(capacity_mw: float) -> int:
    """Recommend connection voltage based on capacity."""
    if capacity_mw <= 0.1:
        return 11
    elif capacity_mw <= 10:
        return 33
    elif capacity_mw <= 50:
        return 66
    elif capacity_mw <= 100:
        return 132
    else:
        return 275


# ─── Capacity Map (GeoJSON) ──────────────────────────────────────────────

async def capacity_map_geojson(
    conn,
    dno: str | None = None,
    min_voltage_kv: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict:
    """
    Generate GeoJSON FeatureCollection of substations with capacity RAG status.
    """
    conditions = []
    params: list[Any] = []
    idx = 1

    if dno:
        conditions.append(f"dno = ${idx}")
        params.append(dno)
        idx += 1
    if min_voltage_kv:
        conditions.append(f"voltage_kv >= ${idx}")
        params.append(min_voltage_kv)
        idx += 1
    if bbox:
        west, south, east, north = bbox
        conditions.append(f"""
            ST_Intersects(
                geom,
                ST_Transform(ST_MakeEnvelope(${idx}, ${idx+1}, ${idx+2}, ${idx+3}, 4326), 27700)
            )
        """)
        params.extend([west, south, east, north])
        idx += 4

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = await conn.fetch(f"""
        SELECT
            id, name, dno, voltage_kv, site_type,
            demand_headroom_mw, gen_headroom_mw,
            demand_mw, generation_mw,
            rag_demand, rag_generation,
            transformer_rating_mva,
            ST_X(ST_Transform(geom, 4326)) AS lon,
            ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        {where}
        ORDER BY voltage_kv DESC NULLS LAST
    """, *params)

    features = []
    for r in rows:
        # Derive RAG if not provided
        gen_rag = r["rag_generation"]
        if not gen_rag and r["gen_headroom_mw"] is not None:
            h = float(r["gen_headroom_mw"])
            gen_rag = "green" if h > 5 else ("amber" if h > 0 else "red")

        dem_rag = r["rag_demand"]
        if not dem_rag and r["demand_headroom_mw"] is not None:
            h = float(r["demand_headroom_mw"])
            dem_rag = "green" if h > 5 else ("amber" if h > 0 else "red")

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "id": r["id"],
                "name": r["name"],
                "dno": r["dno"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                "site_type": r["site_type"],
                "demand_headroom_mw": float(r["demand_headroom_mw"]) if r["demand_headroom_mw"] else None,
                "gen_headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] else None,
                "demand_mw": float(r["demand_mw"]) if r["demand_mw"] else None,
                "generation_mw": float(r["generation_mw"]) if r["generation_mw"] else None,
                "rag_demand": dem_rag,
                "rag_generation": gen_rag,
                "transformer_mva": float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] else None,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total": len(features),
            "filters": {"dno": dno, "min_voltage_kv": min_voltage_kv},
        },
    }


# ─── Substation Detail ───────────────────────────────────────────────────

async def substation_detail(conn, substation_id: int) -> dict | None:
    """Full detail for a single substation including queue and ECR."""
    row = await conn.fetchrow("""
        SELECT
            id, external_id, name, dno, region, voltage_kv, site_type,
            demand_mw, generation_mw, demand_headroom_mw, gen_headroom_mw,
            fault_level_ka, transformer_rating_mva,
            rag_demand, rag_generation, raw_data,
            ST_X(ST_Transform(geom, 4326)) AS lon,
            ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        WHERE id = $1
    """, substation_id)

    if not row:
        return None

    # Connected/queued DER
    ecr = await conn.fetch("""
        SELECT site_name, technology, capacity_mw, voltage_kv, status
        FROM grid_ecr
        WHERE substation_id = $1
        ORDER BY capacity_mw DESC NULLS LAST
    """, substation_id)

    # TEC entries at this substation
    tec = await conn.fetch("""
        SELECT customer_name, fuel_type, tech_category, tec_mw, status, connection_date
        FROM eso_tec_register
        WHERE connection_site ILIKE $1
        ORDER BY tec_mw DESC NULLS LAST
        LIMIT 20
    """, f"%{row['name']}%")

    # Capacity history
    history = await conn.fetch("""
        SELECT snapshot_date, demand_headroom_mw, gen_headroom_mw, demand_mw, generation_mw
        FROM grid_capacity_snapshots
        WHERE substation_id = $1
        ORDER BY snapshot_date DESC
        LIMIT 12
    """, substation_id)

    result = {k: v for k, v in dict(row).items() if k != "raw_data"}
    result["lat"] = float(row["lat"])
    result["lon"] = float(row["lon"])
    result["connected_der"] = [dict(r) for r in ecr]
    result["tec_entries"] = [dict(r) for r in tec]
    result["capacity_history"] = [dict(r) for r in history]
    result["queue_summary"] = {
        "ecr_count": len(ecr),
        "ecr_total_mw": round(sum(float(r["capacity_mw"] or 0) for r in ecr), 1),
        "tec_count": len(tec),
        "tec_total_mw": round(sum(float(r["tec_mw"] or 0) for r in tec), 1),
    }

    return result


# ─── Grid Lines GeoJSON ──────────────────────────────────────────────────

async def grid_lines_geojson(
    conn,
    min_voltage_kv: float = 132,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict:
    """GeoJSON FeatureCollection of grid transmission/distribution lines."""
    conditions = [f"voltage_kv >= $1"]
    params: list[Any] = [min_voltage_kv]
    idx = 2

    if bbox:
        west, south, east, north = bbox
        conditions.append(f"""
            ST_Intersects(
                geom,
                ST_Transform(ST_MakeEnvelope(${idx}, ${idx+1}, ${idx+2}, ${idx+3}, 4326), 27700)
            )
        """)
        params.extend([west, south, east, north])
        idx += 4

    where = "WHERE " + " AND ".join(conditions)

    rows = await conn.fetch(f"""
        SELECT
            id, voltage_kv, circuits, operator, length_km,
            ST_AsGeoJSON(ST_Transform(geom, 4326))::json AS geojson
        FROM grid_lines
        {where}
        ORDER BY voltage_kv DESC
    """, *params)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": json.loads(r["geojson"]) if isinstance(r["geojson"], str) else r["geojson"],
            "properties": {
                "id": r["id"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                "circuits": r["circuits"],
                "operator": r["operator"],
                "length_km": float(r["length_km"]) if r["length_km"] else None,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"total": len(features), "min_voltage_kv": min_voltage_kv},
    }


# ─── Tier 2: Power Flow Validation ──────────────────────────────────────

# Path to pandapower subprocess
GRID_PYTHON = os.environ.get(
    "GRID_PYTHON",
    os.path.join(os.path.dirname(__file__), "..", ".venv-grid", "bin", "python"),
)
GRID_POWER_FLOW_SCRIPT = os.path.join(os.path.dirname(__file__), "grid_power_flow.py")


async def tier2_power_flow(
    conn,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
    connection_substation_id: int | None = None,
    search_radius_km: float = 20.0,
    contingency: bool = False,
) -> dict[str, Any]:
    """
    Run Tier 2 pandapower-based power flow validation.

    Fetches network topology from PostGIS, builds a pandapower model via
    subprocess, and returns detailed electrical analysis.
    """
    t0 = time.time()

    # 1. Get substations near the site
    substations = await _find_nearest_substations(conn, lat, lon, search_radius_km, 10)
    if not substations:
        return {
            "success": False,
            "error": "No substations found within search radius",
            "tier": "power_flow",
        }

    # 2. Determine connection point
    conn_sub_id = connection_substation_id
    if conn_sub_id is None:
        # Default to nearest suitable substation
        for sub in substations:
            rec_v = _recommended_voltage(capacity_mw)
            if sub.get("voltage_kv") and sub["voltage_kv"] >= rec_v:
                conn_sub_id = sub["id"]
                break
        if conn_sub_id is None:
            conn_sub_id = substations[0]["id"]

    # 3. Get grid lines connecting these substations
    sub_ids = [s["id"] for s in substations]
    lines = await _fetch_grid_lines(conn, sub_ids)

    # If no lines in DB, create synthetic connections between nearest substations
    if not lines:
        lines = _synthesise_lines(substations)

    # 4. Build input for subprocess
    pf_input = {
        "substations": substations,
        "lines": lines,
        "proposed": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "connection_substation_id": conn_sub_id,
            "power_factor": 0.95,
        },
        "options": {
            "contingency": contingency,
            "max_loading_pct": 100,
            "voltage_limits": [0.94, 1.06],
        },
    }

    # 5. Run pandapower subprocess
    result = await _run_power_flow_subprocess(pf_input)

    elapsed = round(time.time() - t0, 3)
    result["tier"] = "power_flow"
    result["elapsed_s"] = elapsed
    result["connection_substation_id"] = conn_sub_id
    result["network_size"] = {
        "substations": len(substations),
        "lines": len(lines),
    }

    return result


async def _fetch_grid_lines(conn, substation_ids: list[int]) -> list[dict]:
    """Fetch grid lines connecting the given substations."""
    if not substation_ids:
        return []

    rows = await conn.fetch("""
        SELECT
            id, from_substation_id, to_substation_id,
            voltage_kv, circuits, length_km
        FROM grid_lines
        WHERE from_substation_id = ANY($1::int[])
           OR to_substation_id = ANY($1::int[])
    """, substation_ids)

    return [
        {
            "id": r["id"],
            "from_id": r["from_substation_id"],
            "to_id": r["to_substation_id"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else 33,
            "circuits": r["circuits"] or 1,
            "length_km": float(r["length_km"]) if r["length_km"] else 1.0,
        }
        for r in rows
    ]


def _synthesise_lines(substations: list[dict]) -> list[dict]:
    """
    Create synthetic line connections between substations when PostGIS
    line data is unavailable. Connects each substation to the nearest
    higher-voltage one.
    """
    if len(substations) < 2:
        return []

    lines = []
    sorted_subs = sorted(substations, key=lambda s: s.get("voltage_kv") or 0, reverse=True)

    for i, sub in enumerate(sorted_subs[1:], 1):
        # Connect to nearest higher-voltage substation
        best_parent = sorted_subs[0]
        best_dist = _haversine(sub["lat"], sub["lon"], best_parent["lat"], best_parent["lon"])

        for parent in sorted_subs[:i]:
            if (parent.get("voltage_kv") or 0) >= (sub.get("voltage_kv") or 0):
                d = _haversine(sub["lat"], sub["lon"], parent["lat"], parent["lon"])
                if d < best_dist:
                    best_dist = d
                    best_parent = parent

        lines.append({
            "from_id": best_parent["id"],
            "to_id": sub["id"],
            "voltage_kv": min(
                best_parent.get("voltage_kv") or 33,
                sub.get("voltage_kv") or 33,
            ),
            "circuits": 1,
            "length_km": round(best_dist, 2),
        })

    return lines


def _haversine(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


async def _run_power_flow_subprocess(pf_input: dict) -> dict:
    """Run the pandapower subprocess and parse results."""
    grid_python = GRID_PYTHON
    script = GRID_POWER_FLOW_SCRIPT

    if not os.path.isfile(grid_python):
        return {"success": False, "error": f"Grid Python not found at {grid_python}"}
    if not os.path.isfile(script):
        return {"success": False, "error": f"Power flow script not found at {script}"}

    input_json = json.dumps(pf_input)

    try:
        proc = await asyncio.create_subprocess_exec(
            grid_python, script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=input_json.encode()),
            timeout=30.0,
        )

        if proc.returncode != 0:
            err = stderr.decode().strip()
            log.warning("Power flow subprocess failed (rc=%d): %s", proc.returncode, err[:500])
            return {"success": False, "error": f"Subprocess error: {err[:200]}"}

        result = json.loads(stdout.decode())
        return result

    except asyncio.TimeoutError:
        return {"success": False, "error": "Power flow subprocess timed out (30s)"}
    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid JSON from power flow subprocess"}
    except FileNotFoundError:
        return {"success": False, "error": f"Grid Python executable not found: {grid_python}"}
    except Exception as e:
        log.exception("Power flow subprocess error")
        return {"success": False, "error": str(e)}
