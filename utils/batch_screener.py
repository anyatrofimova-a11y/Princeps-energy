"""
Batch site screener — scores multiple candidate locations simultaneously.

Given a list of lat/lon + capacity, runs all feasibility checks in parallel:
- Grid connection (headroom, queue, cost)
- Planning risk (local REPD outcomes, constraints)
- Solar resource (capacity factor from latitude)
- Land suitability (ALC grade)
- Constraint cost (congestion zone pricing)

Returns ranked shortlist with composite score.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

log = logging.getLogger("princeps.batch_screener")


async def screen_sites(pool, candidates: list[dict], *, top_n: int = 20) -> dict:
    if not candidates:
        return {"ranked": [], "summary": {}, "total_screened": 0}

    results = []
    batch_size = 10
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[_score_single(pool, c) for c in batch],
            return_exceptions=True,
        )
        for c, r in zip(batch, batch_results):
            if isinstance(r, Exception):
                log.warning("Screening failed for %s: %s", c, r)
                results.append({**c, "composite_score": 0, "error": str(r)})
            else:
                results.append(r)

    results.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    scores = [r["composite_score"] for r in results if "error" not in r]
    go = sum(1 for r in results if r.get("verdict") == "GO")
    caution = sum(1 for r in results if r.get("verdict") == "CAUTION")
    nogo = sum(1 for r in results if r.get("verdict") == "NO-GO")

    return {
        "ranked": results[:top_n],
        "all_results": results,
        "total_screened": len(candidates),
        "summary": {
            "go": go, "caution": caution, "no_go": nogo,
            "avg_score": round(sum(scores) / max(len(scores), 1), 1),
            "max_score": max(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
        },
    }


async def _score_single(pool, candidate: dict) -> dict:
    lat = candidate["lat"]
    lon = candidate["lon"]
    capacity_mw = candidate.get("capacity_mw", 50)
    technology = candidate.get("technology", "solar")
    scores = {}

    async with pool.acquire() as conn:
        # Grid headroom
        try:
            sub = await conn.fetchrow("""
                SELECT name, gen_headroom_mw, voltage_kv,
                       ST_Distance(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700))/1000 AS dist_km,
                       (SELECT COUNT(*) FROM grid_ecr WHERE substation_id=s.id
                        AND status IN ('queued','pending','submitted')) AS queue_count
                FROM grid_substations s
                WHERE geom IS NOT NULL
                  AND ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700), 15000)
                ORDER BY ST_Distance(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700))
                LIMIT 1
            """, lon, lat)
            if sub:
                headroom = float(sub["gen_headroom_mw"] or 0)
                dist = float(sub["dist_km"])
                queue = sub["queue_count"] or 0
                h_score = min(100, max(0, (headroom / max(capacity_mw, 1)) * 50))
                d_score = max(0, 100 - dist * 10)
                q_score = max(0, 100 - queue * 5)
                grid_score = int(h_score * 0.5 + d_score * 0.3 + q_score * 0.2)
                scores["grid"] = {"score": grid_score, "substation": sub["name"],
                                  "headroom_mw": headroom, "distance_km": round(dist, 1), "queue_count": queue}
            else:
                scores["grid"] = {"score": 10, "detail": "No substation within 15km"}
        except Exception:
            scores["grid"] = {"score": 20}

        # Planning risk
        try:
            outcomes = await conn.fetch("""
                SELECT dev_status_short, COUNT(*) AS cnt FROM repd_project
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(geometry::geography, ST_SetSRID(ST_Point($1,$2),4326)::geography, 10000)
                GROUP BY dev_status_short
            """, lon, lat)
            total = sum(r["cnt"] for r in outcomes)
            approved = sum(r["cnt"] for r in outcomes if r["dev_status_short"] in
                           ("Operational", "Under Construction", "Awaiting Construction"))
            rate = approved / max(total, 1)
            scores["planning"] = {"score": int(rate * 80 + 10), "approval_rate": round(rate, 2), "total_nearby": total}
        except Exception:
            scores["planning"] = {"score": 50}

        # Solar resource
        cf = max(8, min(13, 14 - (lat - 50) * 1.5))
        scores["solar"] = {"score": int((cf - 8) / 5 * 100), "capacity_factor_pct": round(cf, 1)}

        # Land suitability
        from utils.land_registry import get_agricultural_land_class
        alc = await get_agricultural_land_class(lat, lon)
        scores["land"] = {"score": 80 if alc["suitable_for_development"] else 30,
                          "alc_grade": alc["grade"], "bmv": not alc["suitable_for_development"]}

        # Constraint cost
        try:
            avg_hr = await conn.fetchval("""
                SELECT AVG(COALESCE(gen_headroom_mw, 50)) FROM grid_substations
                WHERE geom IS NOT NULL
                  AND ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700), 20000)
            """, lon, lat)
            scores["cost"] = {"score": int(min(100, max(10, float(avg_hr or 50) * 1.5))),
                              "avg_area_headroom_mw": round(float(avg_hr or 50), 1)}
        except Exception:
            scores["cost"] = {"score": 50}

    composite = int(
        scores.get("grid", {}).get("score", 0) * 0.30
        + scores.get("planning", {}).get("score", 0) * 0.25
        + scores.get("solar", {}).get("score", 0) * 0.20
        + scores.get("land", {}).get("score", 0) * 0.15
        + scores.get("cost", {}).get("score", 0) * 0.10
    )
    verdict = "GO" if composite >= 60 else "CAUTION" if composite >= 35 else "NO-GO"

    return {
        "lat": lat, "lon": lon, "capacity_mw": capacity_mw, "technology": technology,
        "composite_score": composite, "verdict": verdict, "scores": scores,
        "label": candidate.get("label", f"{lat:.3f},{lon:.3f}"),
    }
