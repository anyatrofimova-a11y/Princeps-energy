"""
Queue depth analyser — estimates connection wait times per substation
based on ECR queue progression and TEC gate history.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("princeps.queue_analyser")


async def get_queue_depth(pool, substation_id: int) -> dict | None:
    """Queue depth analysis for a single substation."""
    try:
        # Get substation info
        sub = await pool.fetchrow(
            """SELECT id, name, dno, voltage_kv,
                      demand_headroom_mw, gen_headroom_mw,
                      rag_demand, rag_generation
               FROM grid_substations WHERE id = $1""",
            substation_id,
        )
        if not sub:
            return None

        # Get ECR entries for this substation
        rows = await pool.fetch(
            """SELECT id, site_name, technology, capacity_mw, status
               FROM grid_ecr WHERE substation_id = $1
               ORDER BY capacity_mw DESC""",
            substation_id,
        )

        # Count by status
        by_status: dict[str, int] = {}
        total_queued_mw = 0.0
        total_accepted_mw = 0.0
        projects = []

        for r in rows:
            status = (r["status"] or "unknown").lower()
            by_status[status] = by_status.get(status, 0) + 1
            cap = float(r["capacity_mw"] or 0)
            if status in ("queued", "pending", "submitted"):
                total_queued_mw += cap
            elif status in ("accepted", "offer_accepted"):
                total_accepted_mw += cap
            projects.append({
                "id": r["id"],
                "name": r["site_name"],
                "technology": r["technology"],
                "capacity_mw": cap,
                "status": r["status"],
            })

        queued_count = by_status.get("queued", 0) + by_status.get("pending", 0) + by_status.get("submitted", 0)
        accepted_count = by_status.get("accepted", 0) + by_status.get("offer_accepted", 0)
        connected_count = by_status.get("connected", 0)

        # Estimate wait time
        wait_months = _estimate_wait(
            queued_count, total_queued_mw, sub["rag_demand"], sub["gen_headroom_mw"]
        )

        risk_level = "low" if wait_months < 12 else "medium" if wait_months < 24 else "high"

        return {
            "substation_id": sub["id"],
            "name": sub["name"],
            "dno": sub["dno"],
            "voltage_kv": float(sub["voltage_kv"] or 0),
            "queued_count": queued_count,
            "accepted_count": accepted_count,
            "connected_count": connected_count,
            "total_queued_mw": round(total_queued_mw, 1),
            "total_accepted_mw": round(total_accepted_mw, 1),
            "estimated_wait_months": wait_months,
            "risk_level": risk_level,
            "projects": projects[:20],  # cap at 20
            "status_breakdown": by_status,
        }
    except Exception as e:
        log.warning("Queue depth failed for substation %s: %s", substation_id, e)
        return None


async def get_queue_summary(pool, *, bbox: tuple | None = None, limit: int = 50) -> list[dict]:
    """Queue depth summaries for substations in a bounding box."""
    try:
        bbox_clause = ""
        params: list[Any] = []
        if bbox:
            west, south, east, north = bbox
            bbox_clause = """AND ST_Intersects(
                s.geom,
                ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
            )"""
            params = [west, south, east, north]

        query = f"""
            SELECT
                s.id, s.name, s.dno, s.voltage_kv,
                s.gen_headroom_mw, s.rag_demand,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                COUNT(e.id) FILTER (WHERE e.status IN ('queued', 'pending', 'submitted')) AS queued_count,
                COUNT(e.id) FILTER (WHERE e.status IN ('accepted', 'offer_accepted')) AS accepted_count,
                COALESCE(SUM(e.capacity_mw) FILTER (WHERE e.status IN ('queued', 'pending', 'submitted')), 0) AS total_queued_mw
            FROM grid_substations s
            LEFT JOIN grid_ecr e ON e.substation_id = s.id
            WHERE 1=1 {bbox_clause}
            GROUP BY s.id
            HAVING COUNT(e.id) > 0
            ORDER BY queued_count DESC
            LIMIT ${len(params) + 1}
        """
        params.append(limit)

        rows = await pool.fetch(query, *params)
        results = []
        for r in rows:
            queued = r["queued_count"]
            queued_mw = float(r["total_queued_mw"] or 0)
            wait = _estimate_wait(queued, queued_mw, r["rag_demand"], r["gen_headroom_mw"])
            results.append({
                "substation_id": r["id"],
                "name": r["name"],
                "dno": r["dno"],
                "lat": float(r["lat"]) if r["lat"] else None,
                "lon": float(r["lon"]) if r["lon"] else None,
                "queued_count": queued,
                "accepted_count": r["accepted_count"],
                "total_queued_mw": round(queued_mw, 1),
                "estimated_wait_months": wait,
                "risk_level": "low" if wait < 12 else "medium" if wait < 24 else "high",
            })

        return results
    except Exception as e:
        log.warning("Queue summary failed: %s", e)
        return []


def _estimate_wait(
    queued_count: int,
    total_queued_mw: float,
    rag_demand: str | None,
    gen_headroom_mw: float | None,
) -> int:
    """Estimate connection wait time in months.

    Simple heuristic:
      base 6 months
      + 2 months per queued project
      + 3 months per 10 MW queued
      + 6 months if demand RAG is red
      + 3 months if gen headroom < 5 MW
    """
    wait = 6
    wait += queued_count * 2
    wait += int(total_queued_mw / 10) * 3
    if rag_demand == "red":
        wait += 6
    if gen_headroom_mw is not None and gen_headroom_mw < 5:
        wait += 3
    return min(wait, 72)  # cap at 6 years
