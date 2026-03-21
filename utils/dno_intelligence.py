"""
DNO pre-application intelligence — per-DNO analytics from real data.

Analyses REPD and ECR data to provide DNO-specific insights:
- Acceptance rates by DNO and technology
- Average queue depth and headroom
- Congestion hotspots per DNO region
- Recommended application timing
- Technology bias per DNO
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("princeps.dno_intelligence")

# Map REPD regions to DNO codes
_REGION_TO_DNO = {
    "scotland": "SPEN", "north east england": "NPG", "yorkshire": "NPG",
    "north west england": "ENWL", "east midlands": "UKPN",
    "east england": "UKPN", "south east england": "UKPN", "london": "UKPN",
    "south west england": "NGED", "west midlands": "NGED", "wales": "NGED",
    "south england": "SSEN", "southern england": "SSEN",
    "north scotland": "SSEN",
}

DNO_NAMES = {
    "UKPN": "UK Power Networks", "NPG": "Northern Powergrid",
    "ENWL": "Electricity North West", "SPEN": "SP Energy Networks",
    "SSEN": "Scottish & Southern Electricity Networks", "NGED": "National Grid Electricity Distribution",
}


def _region_to_dno(region: str) -> str:
    if not region:
        return "Unknown"
    r = region.lower().strip()
    for key, dno in _REGION_TO_DNO.items():
        if key in r:
            return dno
    return "Unknown"


async def analyse_dno(pool, *, dno: str = None, lat: float = None, lon: float = None) -> dict:
    """Analyse DNO performance from real REPD + ECR data."""

    # If lat/lon given, determine DNO from nearest substation
    if dno is None and lat is not None:
        try:
            row = await pool.fetchrow("""
                SELECT dno FROM grid_substations
                WHERE geom IS NOT NULL
                  AND ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700), 30000)
                ORDER BY ST_Distance(geom, ST_Transform(ST_SetSRID(ST_Point($1,$2),4326),27700))
                LIMIT 1
            """, lon, lat)
            if row:
                dno = row["dno"]
        except Exception:
            pass

    result = {
        "dno": dno or "All",
        "dno_name": DNO_NAMES.get(dno, "All DNOs"),
    }

    async with pool.acquire() as conn:
        # ── Per-DNO REPD outcomes ──
        try:
            dno_filter = ""
            if dno and dno != "All":
                # Filter REPD by region mapping
                regions = [k for k, v in _REGION_TO_DNO.items() if v == dno]
                if regions:
                    like_clauses = " OR ".join(f"region ILIKE '%{r}%'" for r in regions)
                    dno_filter = f"AND ({like_clauses})"

            rows = await conn.fetch(f"""
                SELECT dev_status_short, technology_type, COUNT(*) AS cnt,
                       SUM(installed_capacity_mw) AS total_mw,
                       AVG(installed_capacity_mw) AS avg_mw
                FROM repd_project
                WHERE dev_status_short IS NOT NULL {dno_filter}
                GROUP BY dev_status_short, technology_type
                ORDER BY cnt DESC
            """)

            # Aggregate by status
            status_totals: dict[str, int] = {}
            tech_status: dict[str, dict[str, int]] = {}
            for r in rows:
                status = r["dev_status_short"]
                tech = r["technology_type"] or "Unknown"
                status_totals[status] = status_totals.get(status, 0) + r["cnt"]
                tech_status.setdefault(tech, {})
                tech_status[tech][status] = tech_status[tech].get(status, 0) + r["cnt"]

            total_projects = sum(status_totals.values())
            approved = sum(v for k, v in status_totals.items() if k in
                           ("Operational", "Under Construction", "Awaiting Construction"))
            refused = sum(v for k, v in status_totals.items() if k in ("Refused", "Appeal Refused"))

            result["acceptance_rate"] = round(approved / max(total_projects, 1), 3)
            result["refusal_rate"] = round(refused / max(total_projects, 1), 3)
            result["total_projects"] = total_projects
            result["status_breakdown"] = status_totals

            # Technology bias
            tech_rates = {}
            for tech, statuses in tech_status.items():
                t_total = sum(statuses.values())
                t_approved = sum(v for k, v in statuses.items() if k in
                                 ("Operational", "Under Construction", "Awaiting Construction"))
                if t_total >= 5:
                    tech_rates[tech] = round(t_approved / t_total, 2)
            result["technology_acceptance"] = tech_rates

        except Exception as e:
            log.warning("REPD DNO analysis failed: %s", e)
            result["acceptance_rate"] = None

        # ── Grid queue analysis per DNO ──
        try:
            dno_clause = f"AND s.dno = '{dno}'" if dno and dno != "All" else ""
            queue_row = await conn.fetchrow(f"""
                SELECT COUNT(DISTINCT s.id) AS sub_count,
                       AVG(s.gen_headroom_mw) AS avg_headroom,
                       COUNT(e.id) AS total_queue,
                       COALESCE(SUM(e.capacity_mw), 0) AS total_queue_mw
                FROM grid_substations s
                LEFT JOIN grid_ecr e ON e.substation_id = s.id
                WHERE s.geom IS NOT NULL {dno_clause}
            """)
            if queue_row:
                result["substations"] = queue_row["sub_count"]
                result["avg_headroom_mw"] = round(float(queue_row["avg_headroom"] or 0), 1)
                result["total_queue_count"] = queue_row["total_queue"]
                result["total_queue_mw"] = round(float(queue_row["total_queue_mw"] or 0), 1)
                result["avg_queue_per_sub"] = round(
                    queue_row["total_queue"] / max(queue_row["sub_count"], 1), 1)
        except Exception as e:
            log.warning("Grid queue DNO analysis failed: %s", e)

        # ── Congestion hotspots ──
        try:
            hotspots = await conn.fetch(f"""
                SELECT s.name, s.voltage_kv, s.gen_headroom_mw,
                       COUNT(e.id) AS queue_count,
                       ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                       ST_X(ST_Transform(s.geom, 4326)) AS lon
                FROM grid_substations s
                LEFT JOIN grid_ecr e ON e.substation_id = s.id
                WHERE s.geom IS NOT NULL {dno_clause}
                GROUP BY s.id
                HAVING COUNT(e.id) >= 5
                ORDER BY COUNT(e.id) DESC
                LIMIT 10
            """)
            result["congestion_hotspots"] = [{
                "name": h["name"], "voltage_kv": float(h["voltage_kv"] or 0),
                "headroom_mw": round(float(h["gen_headroom_mw"] or 0), 1),
                "queue_count": h["queue_count"],
                "lat": float(h["lat"]), "lon": float(h["lon"]),
            } for h in hotspots]
        except Exception:
            result["congestion_hotspots"] = []

    # ── Recommendations ──
    congestion = result.get("avg_queue_per_sub", 0)
    result["congestion_level"] = "low" if congestion < 3 else "medium" if congestion < 8 else "high"
    result["recommended_timing"] = (
        "Q1 (Jan-Mar) — post-Christmas lull, DNO capacity refreshed"
        if congestion < 5 else
        "Q2 (Apr-Jun) — after annual planning round, new headroom released"
    )

    risk_factors = []
    if result.get("avg_headroom_mw", 100) < 20:
        risk_factors.append(f"Low average headroom ({result['avg_headroom_mw']:.0f}MW) across {dno} substations")
    if result.get("total_queue_mw", 0) > 1000:
        risk_factors.append(f"High queue pressure: {result['total_queue_mw']:.0f}MW queued")
    if result.get("refusal_rate", 0) > 0.15:
        risk_factors.append(f"Above-average refusal rate ({result['refusal_rate']:.0%})")
    result["risk_factors"] = risk_factors

    return result


async def compare_dnos(pool) -> list[dict]:
    """Compare all DNOs side-by-side."""
    results = []
    for dno_code in ["UKPN", "NPG", "ENWL", "SPEN", "SSEN", "NGED"]:
        try:
            r = await analyse_dno(pool, dno=dno_code)
            results.append(r)
        except Exception as e:
            log.warning("DNO comparison failed for %s: %s", dno_code, e)
    results.sort(key=lambda x: x.get("acceptance_rate", 0) or 0, reverse=True)
    return results
