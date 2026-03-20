"""Graph API — Neo4j grid topology endpoints for Princeps.

Provides spatial topology queries, hierarchy traversal, shortest path,
search, and summary statistics from the Neo4j graph database.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from neo4j import GraphDatabase

log = logging.getLogger("princeps.graph_api")

router = APIRouter(prefix="/api/graph", tags=["graph"])

# ---------------------------------------------------------------------------
# Neo4j driver (synchronous — neo4j v6.x)
# ---------------------------------------------------------------------------

_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "princeps")

_driver = None


def _get_driver():
    """Lazy-initialise and return the Neo4j driver."""
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(
                _NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD),
            )
            _driver.verify_connectivity()
            log.info("Neo4j graph-API driver connected (%s)", _NEO4J_URI)
        except Exception as exc:
            log.warning("Neo4j graph-API driver unavailable: %s", exc)
            _driver = None
            raise HTTPException(status_code=503, detail=f"Neo4j unavailable: {exc}")
    return _driver


def _require_driver():
    """Return the driver or raise 503."""
    drv = _get_driver()
    if drv is None:
        raise HTTPException(status_code=503, detail="Neo4j unavailable")
    return drv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node_to_dict(node) -> dict[str, Any]:
    """Convert a Neo4j node to a flat dict with id, labels, and properties."""
    props = dict(node)
    labels = list(node.labels) if hasattr(node, "labels") else []
    # Determine a human-friendly type from labels
    type_label = "Unknown"
    for candidate in [
        "Substation", "PowerTransformer", "ACLineSegment",
        "EnergyConsumer", "ConnectivityNode", "Generator",
        "GridConnection", "SPV", "Developer", "PlanningApplication",
    ]:
        if candidate in labels:
            type_label = candidate
            break

    return {
        "id": props.get("id", node.element_id),
        "name": props.get("name"),
        "type": type_label,
        "voltage_kv": props.get("voltageKv") or props.get("voltage_kv"),
        "demand_mw": props.get("pMw") or props.get("demand_mw"),
        "lat": props.get("lat"),
        "lon": props.get("lon"),
        **{k: v for k, v in props.items()
           if k not in ("id", "name", "voltageKv", "voltage_kv", "pMw", "demand_mw", "lat", "lon")},
    }


def _rel_to_dict(rel) -> dict[str, Any]:
    """Convert a Neo4j relationship to a dict."""
    props = dict(rel)
    return {
        "source": rel.start_node.get("id", rel.start_node.element_id),
        "target": rel.end_node.get("id", rel.end_node.element_id),
        "type": rel.type,
        "voltage_kv": props.get("voltageKv") or props.get("voltage_kv"),
        "length_km": props.get("lengthKm") or props.get("length_km"),
        "name": props.get("name"),
    }


# ---------------------------------------------------------------------------
# 1. GET /api/graph/topology
# ---------------------------------------------------------------------------

@router.get("/topology")
def get_topology(
    lat: Optional[float] = Query(None, description="Centre latitude for spatial filter"),
    lon: Optional[float] = Query(None, description="Centre longitude for spatial filter"),
    radius_km: float = Query(50, ge=1, le=500, description="Radius in km"),
    max_nodes: int = Query(500, ge=1, le=5000, description="Max nodes to return"),
):
    """Return the grid topology graph, optionally filtered around a lat/lon point."""
    driver = _require_driver()

    with driver.session() as session:
        if lat is not None and lon is not None:
            # Spatial filter: find nodes within radius_km of the given point.
            # Uses Haversine approximation in Cypher (nodes must have lat/lon).
            result = session.run(
                """
                MATCH (n:Asset)
                WHERE n.lat IS NOT NULL AND n.lon IS NOT NULL
                  AND (
                    2 * 6371 * asin(sqrt(
                      sin(radians(n.lat - $lat) / 2) ^ 2
                      + cos(radians($lat)) * cos(radians(n.lat))
                        * sin(radians(n.lon - $lon) / 2) ^ 2
                    ))
                  ) <= $radius_km
                WITH n LIMIT $max_nodes
                OPTIONAL MATCH (n)-[r]-(m:Asset)
                WHERE m.lat IS NOT NULL AND m.lon IS NOT NULL
                  AND (
                    2 * 6371 * asin(sqrt(
                      sin(radians(m.lat - $lat) / 2) ^ 2
                      + cos(radians($lat)) * cos(radians(m.lat))
                        * sin(radians(m.lon - $lon) / 2) ^ 2
                    ))
                  ) <= $radius_km
                RETURN collect(DISTINCT n) AS nodes,
                       collect(DISTINCT m) AS neighbours,
                       collect(DISTINCT r) AS edges
                """,
                lat=lat, lon=lon, radius_km=radius_km, max_nodes=max_nodes,
            )
        else:
            # No spatial filter — return up to max_nodes assets and their edges
            result = session.run(
                """
                MATCH (n:Asset)
                WITH n LIMIT $max_nodes
                OPTIONAL MATCH (n)-[r]-(m:Asset)
                RETURN collect(DISTINCT n) AS nodes,
                       collect(DISTINCT m) AS neighbours,
                       collect(DISTINCT r) AS edges
                """,
                max_nodes=max_nodes,
            )

        record = result.single()
        if not record:
            return {"nodes": [], "edges": []}

        # Deduplicate nodes
        seen = set()
        nodes = []
        for n in (record["nodes"] or []) + (record["neighbours"] or []):
            nid = n.get("id", n.element_id)
            if nid not in seen:
                seen.add(nid)
                nodes.append(_node_to_dict(n))

        # Deduplicate edges
        seen_edges = set()
        edges = []
        for r in record["edges"] or []:
            src = r.start_node.get("id", r.start_node.element_id)
            tgt = r.end_node.get("id", r.end_node.element_id)
            eid = f"{src}->{tgt}"
            if eid not in seen_edges:
                seen_edges.add(eid)
                edges.append(_rel_to_dict(r))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# 2. GET /api/graph/hierarchy/{node_id}
# ---------------------------------------------------------------------------

@router.get("/hierarchy/{node_id}")
def get_hierarchy(node_id: str):
    """Return upstream and downstream hierarchy for a specific substation."""
    driver = _require_driver()

    with driver.session() as session:
        # Fetch the node itself
        result = session.run(
            "MATCH (n:Asset {id: $id}) RETURN n",
            id=node_id,
        )
        record = result.single()
        if not record:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        node = _node_to_dict(record["n"])

        # Upstream: assets that feed into this node (higher voltage / parent)
        upstream_result = session.run(
            """
            MATCH (target:Asset {id: $id})
            OPTIONAL MATCH path = (upstream:Asset)-[:HAS_TERMINAL|CONNECTED_TO|CONTAINED_IN*1..8]->(target)
            WHERE upstream <> target AND upstream:Asset
            WITH DISTINCT upstream
            WHERE upstream IS NOT NULL
            RETURN collect(upstream) AS upstream
            """,
            id=node_id,
        )
        upstream_rec = upstream_result.single()
        upstream = [_node_to_dict(n) for n in (upstream_rec["upstream"] or [])] if upstream_rec else []

        # Downstream: assets fed by this node (lower voltage / children)
        downstream_result = session.run(
            """
            MATCH (source:Asset {id: $id})
            OPTIONAL MATCH path = (source)-[:HAS_TERMINAL|CONNECTED_TO|CONTAINED_IN*1..8]->(downstream:Asset)
            WHERE downstream <> source AND downstream:Asset
            WITH DISTINCT downstream
            WHERE downstream IS NOT NULL
            RETURN collect(downstream) AS downstream
            """,
            id=node_id,
        )
        downstream_rec = downstream_result.single()
        downstream = [_node_to_dict(n) for n in (downstream_rec["downstream"] or [])] if downstream_rec else []

        # Direct connections (all relationships on this node)
        conn_result = session.run(
            """
            MATCH (n:Asset {id: $id})-[r]-(m)
            WHERE m:Asset OR m:ConnectivityNode
            RETURN collect(DISTINCT {
                id: COALESCE(m.id, elementId(m)),
                name: m.name,
                relationship: type(r),
                direction: CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END
            }) AS connections
            """,
            id=node_id,
        )
        conn_rec = conn_result.single()
        connections = [dict(c) for c in (conn_rec["connections"] or [])] if conn_rec else []

    return {
        "node": node,
        "upstream": upstream,
        "downstream": downstream,
        "connections": connections,
    }


# ---------------------------------------------------------------------------
# 3. GET /api/graph/stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    """Return summary statistics: node counts by type, edge counts, voltage distribution."""
    driver = _require_driver()

    with driver.session() as session:
        # Node counts by label
        node_result = session.run(
            """
            MATCH (n)
            WITH labels(n) AS lbls, count(*) AS cnt
            UNWIND lbls AS lbl
            RETURN lbl, sum(cnt) AS count
            ORDER BY count DESC
            """
        )
        node_counts = {r["lbl"]: r["count"] for r in node_result}

        # Edge counts by type
        edge_result = session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS type, count(r) AS count
            ORDER BY count DESC
            """
        )
        edge_counts = {r["type"]: r["count"] for r in edge_result}

        # Voltage distribution
        voltage_result = session.run(
            """
            MATCH (n:Asset)
            WHERE n.voltageKv IS NOT NULL
            RETURN n.voltageKv AS voltage_kv, count(n) AS count
            ORDER BY voltage_kv
            """
        )
        voltage_distribution = {r["voltage_kv"]: r["count"] for r in voltage_result}

    return {
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "voltage_distribution": voltage_distribution,
        "total_nodes": sum(node_counts.values()),
        "total_edges": sum(edge_counts.values()),
    }


# ---------------------------------------------------------------------------
# 4. GET /api/graph/path/{from_id}/{to_id}
# ---------------------------------------------------------------------------

@router.get("/path/{from_id}/{to_id}")
def get_shortest_path(from_id: str, to_id: str):
    """Find the shortest path between two substations/assets."""
    driver = _require_driver()

    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Asset {id: $from_id}), (b:Asset {id: $to_id}),
                  path = shortestPath((a)-[*..30]-(b))
            RETURN nodes(path) AS path_nodes, relationships(path) AS path_rels
            """,
            from_id=from_id, to_id=to_id,
        )
        record = result.single()

        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"No path found between {from_id} and {to_id}",
            )

        # Build path nodes (skip Terminal nodes for cleaner output)
        path_nodes = []
        for n in record["path_nodes"]:
            labels = list(n.labels) if hasattr(n, "labels") else []
            if "Terminal" in labels:
                continue
            path_nodes.append(_node_to_dict(n))

        # Build path edges
        path_edges = []
        total_length_km = 0.0
        for r in record["path_rels"]:
            edge = _rel_to_dict(r)
            path_edges.append(edge)
            if edge.get("length_km"):
                total_length_km += float(edge["length_km"])

    return {
        "path": path_nodes,
        "edges": path_edges,
        "total_length_km": round(total_length_km, 3),
    }


# ---------------------------------------------------------------------------
# 5. GET /api/graph/search?q=name
# ---------------------------------------------------------------------------

@router.get("/search")
def search_nodes(
    q: str = Query(..., min_length=1, description="Name substring to search for"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search graph nodes by name substring. Returns top matches."""
    driver = _require_driver()

    with driver.session() as session:
        result = session.run(
            """
            MATCH (n:Asset)
            WHERE n.name IS NOT NULL AND toLower(n.name) CONTAINS toLower($query)
            RETURN n
            ORDER BY n.name
            LIMIT $limit
            """,
            query=q, limit=limit,
        )
        nodes = [_node_to_dict(r["n"]) for r in result]

    return {"query": q, "count": len(nodes), "results": nodes}
