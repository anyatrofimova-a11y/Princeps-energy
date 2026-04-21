"""
Substation neighbourhood traversal — N-hop walk on PostGIS `grid_lines`
joined to `grid_substations`, with a PostGIS geo-adjacent fallback for
nodes that are NOT electrically connected but are nearby in space.

Designed for the "Connection Nodes" map-highlight feature
(see docs/audits/connection_nodes_spec.md §6 BOT-CN-D).

Contract:
    result = await neighbourhood(pool, substation_id, depth=2, radius_km=20)

    {
      "root":    {id, name, lat, lon, voltage_kv, dno, ...},
      "nodes":   [ {id, name, lat, lon, voltage_kv, hop, electrical}, ... ],
      "edges":   [ {id, from_id, to_id, voltage_kv, length_km,
                    is_path_to_root}, ... ],
      "queue_at_root": {"accepted": [...], "applied": [...]},
      "_explanation": "...",       # present when data is thin
      "_truncated":   true|false,  # true if node cap hit
      "provenance":   {...},
      "depth_resolved": int,
      "radius_km":     float,
      "source":        "postgres_grid_lines",
    }

IMPORTANT: The current DB snapshot (2026-04-19) has every `grid_lines`
row with `from_sub_id = NULL` and `to_sub_id = NULL` (1.6 M rows, zero
joined). The electrical traversal therefore returns zero edges for every
substation until the DNO ingest is re-run (see council-bots task #21).
We still return a valid payload with the root + geo-adjacent nodes, so
the frontend has *something* to render.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from utils.grid_provenance import (
    SRC_DB_SNAPSHOT,
    SRC_SYNTHETIC,
    make_provenance,
)

log = logging.getLogger("princeps.grid_neighbourhood")


# Hard upper bounds — even if the caller asks for more, we cap.
MAX_DEPTH = 5
DEFAULT_DEPTH = 3
DEFAULT_RADIUS_KM = 20.0
DEFAULT_NODE_CAP = 150


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _node_row(r: asyncpg.Record, hop: int, electrical: bool) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "voltage_kv": _num(r["voltage_kv"]),
        "dno": r["dno"],
        "lat": _num(r["lat"]),
        "lon": _num(r["lon"]),
        "transformer_rating_mva": _num(r.get("transformer_rating_mva"))
        if hasattr(r, "get") else _num(r["transformer_rating_mva"]),
        "hop": hop,
        "electrical": electrical,
    }


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------


async def neighbourhood(
    pool: asyncpg.Pool,
    substation_id: int,
    depth: int = DEFAULT_DEPTH,
    radius_km: float = DEFAULT_RADIUS_KM,
    node_cap: int = DEFAULT_NODE_CAP,
) -> dict[str, Any] | None:
    """
    Build an N-hop neighbourhood payload for one substation.

    Returns None if the root substation does not exist.
    """
    depth = max(1, min(int(depth or DEFAULT_DEPTH), MAX_DEPTH))
    radius_km = max(0.5, float(radius_km or DEFAULT_RADIUS_KM))
    node_cap = max(10, int(node_cap or DEFAULT_NODE_CAP))

    async with pool.acquire() as conn:
        root = await _fetch_root(conn, substation_id)
        if root is None:
            return None

        electrical_nodes, edges, truncated_electrical = await _walk_electrical(
            conn, substation_id, depth, node_cap
        )

        # Geo-adjacent fallback: substations within radius that are NOT
        # already in the electrical set.
        electrical_ids = {n["id"] for n in electrical_nodes} | {substation_id}
        remaining_cap = max(0, node_cap - len(electrical_nodes) - 1)
        geo_nodes, truncated_geo = await _fetch_geo_adjacent(
            conn, substation_id, radius_km, electrical_ids,
            limit=min(remaining_cap, 20),
        )

        queue = await _fetch_queue(conn, substation_id)

    root_node = {
        "id": root["id"],
        "name": root["name"],
        "voltage_kv": _num(root["voltage_kv"]),
        "dno": root["dno"],
        "lat": _num(root["lat"]),
        "lon": _num(root["lon"]),
        "transformer_rating_mva": _num(root["transformer_rating_mva"]),
        "hop": 0,
        "electrical": True,
    }

    nodes = [root_node] + electrical_nodes + geo_nodes
    truncated = truncated_electrical or truncated_geo

    # Empty-state explanation — distinguishes "no lines data at all" from
    # "isolated substation" for the frontend's empty-state UI.
    explanation: str | None = None
    if not electrical_nodes and not edges:
        has_any_linked = await _has_any_linked_lines(pool)
        if not has_any_linked:
            explanation = (
                "No grid_lines rows have from_sub_id/to_sub_id populated — "
                "DNO ingest pending (see council-bots task #21). "
                "Showing geographic neighbourhood only."
            )
        else:
            explanation = (
                "No grid_lines connect this substation to any other in the DB. "
                "Showing geographic neighbourhood only."
            )

    prov = make_provenance(
        SRC_DB_SNAPSHOT if (electrical_nodes or edges) else SRC_SYNTHETIC,
        reason=explanation or "grid_lines recursive traversal",
    )

    return {
        "root": root_node,
        "nodes": nodes,
        "edges": edges,
        "queue_at_root": queue,
        "depth_resolved": depth,
        "radius_km": radius_km,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "_truncated": truncated,
        "_explanation": explanation,
        "provenance": prov,
        "source": "postgres_grid_lines",
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _fetch_root(conn, substation_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """SELECT id, name, voltage_kv, dno, transformer_rating_mva,
                  ST_X(ST_Transform(geom, 4326)) AS lon,
                  ST_Y(ST_Transform(geom, 4326)) AS lat
           FROM grid_substations
           WHERE id = $1""",
        substation_id,
    )


async def _walk_electrical(
    conn,
    substation_id: int,
    depth: int,
    node_cap: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """
    Recursive CTE walk over grid_lines treating the graph as undirected.
    Returns (electrical_nodes_excluding_root, edges, truncated_flag).
    """
    try:
        rows = await conn.fetch(
            """
            WITH RECURSIVE walk AS (
                -- Seed: root
                SELECT $1::int      AS node_id,
                       0            AS hop,
                       NULL::int    AS via_line_id,
                       NULL::int    AS prev_id
                UNION
                -- Step: follow any grid_line touching the frontier node,
                -- switching to the "other end". Treats edges as undirected.
                SELECT CASE WHEN l.from_sub_id = w.node_id
                            THEN l.to_sub_id ELSE l.from_sub_id END AS node_id,
                       w.hop + 1                                    AS hop,
                       l.id                                         AS via_line_id,
                       w.node_id                                    AS prev_id
                FROM walk w
                JOIN grid_lines l
                  ON (l.from_sub_id = w.node_id OR l.to_sub_id = w.node_id)
                WHERE w.hop < $2
                  AND (CASE WHEN l.from_sub_id = w.node_id
                            THEN l.to_sub_id ELSE l.from_sub_id END) IS NOT NULL
            ),
            -- Dedup: keep shallowest hop per node
            nodes_agg AS (
                SELECT node_id, MIN(hop) AS hop
                FROM walk
                WHERE node_id IS NOT NULL
                GROUP BY node_id
            ),
            edges_agg AS (
                -- Each distinct via_line_id becomes one edge
                SELECT DISTINCT w.via_line_id
                FROM walk w
                WHERE w.via_line_id IS NOT NULL
            )
            SELECT
              (SELECT json_agg(row_to_json(n)) FROM (
                  SELECT s.id, s.name, s.voltage_kv, s.dno,
                         s.transformer_rating_mva,
                         ST_X(ST_Transform(s.geom, 4326)) AS lon,
                         ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                         na.hop
                  FROM nodes_agg na
                  JOIN grid_substations s ON s.id = na.node_id
                  WHERE na.node_id <> $1
                  ORDER BY na.hop, s.id
                  LIMIT $3
              ) n) AS nodes_json,
              (SELECT json_agg(row_to_json(e)) FROM (
                  SELECT l.id, l.from_sub_id, l.to_sub_id,
                         l.voltage_kv, l.length_km
                  FROM edges_agg ea
                  JOIN grid_lines l ON l.id = ea.via_line_id
                  ORDER BY l.voltage_kv DESC NULLS LAST, l.id
                  LIMIT $3
              ) e) AS edges_json,
              (SELECT COUNT(*) FROM nodes_agg WHERE node_id <> $1)
                  AS total_nodes,
              (SELECT COUNT(*) FROM edges_agg) AS total_edges
            """,
            substation_id, depth, node_cap,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("electrical walk failed for sub %s: %s", substation_id, e)
        return [], [], False

    if not rows:
        return [], [], False
    row = rows[0]
    nodes_json = row["nodes_json"] or []
    edges_json = row["edges_json"] or []
    total_nodes = int(row["total_nodes"] or 0)
    total_edges = int(row["total_edges"] or 0)

    nodes: list[dict[str, Any]] = [
        {
            "id": n["id"],
            "name": n["name"],
            "voltage_kv": _num(n["voltage_kv"]),
            "dno": n["dno"],
            "lat": _num(n["lat"]),
            "lon": _num(n["lon"]),
            "transformer_rating_mva": _num(n["transformer_rating_mva"]),
            "hop": int(n["hop"]),
            "electrical": True,
        }
        for n in nodes_json
    ]

    # Edges: any edge whose BOTH endpoints are in the kept node set is a
    # "path-to-root" edge; else it's a dangling reference (we skip it so
    # the frontend doesn't try to render a broken line).
    kept_ids = {n["id"] for n in nodes} | {substation_id}
    edges: list[dict[str, Any]] = []
    for e in edges_json:
        from_id = e["from_sub_id"]
        to_id = e["to_sub_id"]
        if from_id in kept_ids and to_id in kept_ids:
            edges.append({
                "id": e["id"],
                "from_id": from_id,
                "to_id": to_id,
                "voltage_kv": _num(e["voltage_kv"]),
                "length_km": _num(e["length_km"]),
                "is_path_to_root": True,
            })

    truncated = (total_nodes > len(nodes)) or (total_edges > len(edges))
    return nodes, edges, truncated


async def _fetch_geo_adjacent(
    conn,
    substation_id: int,
    radius_km: float,
    exclude_ids: set[int],
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Substations within `radius_km` that are NOT in exclude_ids."""
    if limit <= 0:
        return [], False
    radius_m = float(radius_km) * 1000.0
    try:
        rows = await conn.fetch(
            """SELECT s.id, s.name, s.voltage_kv, s.dno,
                      s.transformer_rating_mva,
                      ST_X(ST_Transform(s.geom, 4326)) AS lon,
                      ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                      ST_Distance(
                          s.geom,
                          (SELECT geom FROM grid_substations WHERE id=$1)
                      )/1000.0 AS distance_km
               FROM grid_substations s
               WHERE s.id <> ALL($3)
                 AND ST_DWithin(
                     s.geom,
                     (SELECT geom FROM grid_substations WHERE id=$1),
                     $2
                 )
               ORDER BY s.geom <-> (SELECT geom FROM grid_substations WHERE id=$1)
               LIMIT $4""",
            substation_id, radius_m, list(exclude_ids), limit + 1,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("geo-adjacent lookup failed for sub %s: %s", substation_id, e)
        return [], False

    truncated = len(rows) > limit
    rows = rows[:limit]
    out = [
        {
            "id": r["id"],
            "name": r["name"],
            "voltage_kv": _num(r["voltage_kv"]),
            "dno": r["dno"],
            "lat": _num(r["lat"]),
            "lon": _num(r["lon"]),
            "transformer_rating_mva": _num(r["transformer_rating_mva"]),
            "distance_km": round(float(r["distance_km"]), 2)
                if r["distance_km"] is not None else None,
            "hop": None,
            "electrical": False,
        }
        for r in rows
    ]
    return out, truncated


async def _fetch_queue(conn, substation_id: int) -> dict[str, Any]:
    """Light queue counts — full list is on the detail endpoint."""
    try:
        row = await conn.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE lower(COALESCE(status,'')) IN
                    ('accepted','offered','connected','energised','energized'))
                    AS accepted,
                 COUNT(*) FILTER (WHERE lower(COALESCE(status,'')) IN
                    ('applied','in progress','under_consideration','pending'))
                    AS applied,
                 COALESCE(SUM(capacity_mw) FILTER (
                    WHERE lower(COALESCE(status,'')) IN
                    ('accepted','offered','connected','energised','energized')
                 ), 0) AS accepted_mw,
                 COALESCE(SUM(capacity_mw) FILTER (
                    WHERE lower(COALESCE(status,'')) IN
                    ('applied','in progress','under_consideration','pending')
                 ), 0) AS applied_mw
               FROM grid_ecr
               WHERE substation_id = $1""",
            substation_id,
        )
    except Exception as e:  # noqa: BLE001
        log.info("queue count failed for sub %s: %s", substation_id, e)
        return {"accepted": 0, "applied": 0, "accepted_mw": 0, "applied_mw": 0}

    if not row:
        return {"accepted": 0, "applied": 0, "accepted_mw": 0, "applied_mw": 0}
    return {
        "accepted": int(row["accepted"] or 0),
        "applied": int(row["applied"] or 0),
        "accepted_mw": float(row["accepted_mw"] or 0),
        "applied_mw": float(row["applied_mw"] or 0),
    }


async def _has_any_linked_lines(pool: asyncpg.Pool) -> bool:
    """Cheap probe: are there ANY grid_lines with both endpoints populated?"""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM grid_lines "
                "WHERE from_sub_id IS NOT NULL AND to_sub_id IS NOT NULL "
                "LIMIT 1"
            )
        return row is not None
    except Exception:  # noqa: BLE001
        return False
