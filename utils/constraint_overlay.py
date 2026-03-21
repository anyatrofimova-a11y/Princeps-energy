"""
Grid constraint cost overlay — shows congestion zones on the map.

Derives constraint severity from substation headroom and ECR queue depth.
Groups nearby substations into zones and assigns cost estimates.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.constraint_overlay")

# Grid cell size for grouping substations into zones (degrees)
CELL_SIZE = 0.25  # ~25km at UK latitudes


def _cell_key(lat: float, lon: float) -> tuple[int, int]:
    return (int(math.floor(lat / CELL_SIZE)), int(math.floor(lon / CELL_SIZE)))


def _cell_center(key: tuple[int, int]) -> tuple[float, float]:
    return ((key[0] + 0.5) * CELL_SIZE, (key[1] + 0.5) * CELL_SIZE)


def _cell_polygon(key: tuple[int, int]) -> list[list[float]]:
    lat0 = key[0] * CELL_SIZE
    lon0 = key[1] * CELL_SIZE
    return [
        [lon0, lat0],
        [lon0 + CELL_SIZE, lat0],
        [lon0 + CELL_SIZE, lat0 + CELL_SIZE],
        [lon0, lat0 + CELL_SIZE],
        [lon0, lat0],
    ]


def _severity(cost: float) -> str:
    if cost < 5:
        return "low"
    if cost < 15:
        return "medium"
    if cost < 30:
        return "high"
    return "critical"


def _color(severity: str) -> str:
    return {
        "low": "#24a148",
        "medium": "#f1c21b",
        "high": "#ff6b35",
        "critical": "#da1e28",
    }.get(severity, "#8d8d8d")


async def get_constraint_zones(pool, bbox: tuple | None = None) -> dict:
    """Return GeoJSON FeatureCollection of constraint cost zones."""
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
                s.demand_headroom_mw, s.gen_headroom_mw,
                s.rag_demand, s.rag_generation,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                COUNT(e.id) FILTER (WHERE e.status IN ('queued', 'pending', 'submitted')) AS queued_count,
                COALESCE(SUM(e.capacity_mw) FILTER (WHERE e.status IN ('queued', 'pending', 'submitted')), 0) AS queued_mw
            FROM grid_substations s
            LEFT JOIN grid_ecr e ON e.substation_id = s.id
            WHERE s.voltage_kv >= 33 {bbox_clause}
            GROUP BY s.id
        """
        rows = await pool.fetch(query, *params)

        # Group substations into grid cells
        cells: dict[tuple[int, int], list[dict]] = {}
        for r in rows:
            if r["lat"] is None or r["lon"] is None:
                continue
            key = _cell_key(float(r["lat"]), float(r["lon"]))
            cells.setdefault(key, []).append(dict(r))

        # Calculate constraint cost per cell
        features = []
        for key, subs in cells.items():
            # Average metrics across substations in cell
            n = len(subs)
            avg_gen_headroom = sum(float(s.get("gen_headroom_mw") or 50) for s in subs) / n
            avg_dem_headroom = sum(float(s.get("demand_headroom_mw") or 50) for s in subs) / n
            total_queued = sum(int(s.get("queued_count") or 0) for s in subs)
            total_queued_mw = sum(float(s.get("queued_mw") or 0) for s in subs)
            red_count = sum(1 for s in subs if s.get("rag_generation") == "red")

            # Estimate constraint cost (£/MWh)
            # Low headroom + high queue = high cost
            cost = 2.0  # base
            if avg_gen_headroom < 10:
                cost += 15
            elif avg_gen_headroom < 30:
                cost += 8
            elif avg_gen_headroom < 60:
                cost += 3

            cost += total_queued * 0.5
            cost += total_queued_mw * 0.1
            cost += red_count * 5

            # Cap
            cost = min(round(cost, 1), 50.0)

            sev = _severity(cost)
            # Only include cells with meaningful constraint data
            if cost < 3 and total_queued == 0:
                continue

            center = _cell_center(key)
            zone_name = _zone_name(subs)

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [_cell_polygon(key)],
                },
                "properties": {
                    "zone_name": zone_name,
                    "constraint_cost_gbp_mwh": cost,
                    "severity": sev,
                    "color": _color(sev),
                    "substations": n,
                    "queued_projects": total_queued,
                    "queued_mw": round(total_queued_mw, 1),
                    "avg_gen_headroom_mw": round(avg_gen_headroom, 1),
                    "description": f"{zone_name}: £{cost}/MWh constraint cost, {total_queued} queued projects",
                },
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "total": len(features),
                "cell_size_deg": CELL_SIZE,
            },
        }
    except Exception as e:
        log.warning("Constraint overlay failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "metadata": {"error": str(e)}}


def _zone_name(subs: list[dict]) -> str:
    """Derive a zone name from the substations in it."""
    # Use the highest-voltage substation's name, or the DNO
    best = max(subs, key=lambda s: float(s.get("voltage_kv") or 0))
    name = best.get("name") or best.get("dno") or "Unknown"
    if len(subs) > 1:
        return f"{name} area"
    return name
