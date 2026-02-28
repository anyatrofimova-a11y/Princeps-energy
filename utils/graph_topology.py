"""
CIM Bus-Branch graph topology — Neo4j integration for Princeps.

Models IEC 61970 connectivity: Asset → Terminal → ConnectivityNode (busbar).
Reads source data from PostgreSQL nged_* tables and builds a graph in Neo4j.

Graceful degradation: all public functions return sensible defaults if Neo4j
is unavailable.  The rest of the app continues normally.
"""

import asyncio
import logging
import os
from typing import Any

from neo4j import AsyncGraphDatabase

log = logging.getLogger("princeps.graph_topology")

# ---------------------------------------------------------------------------
# Module-level driver (mirrors asyncpg pool pattern)
# ---------------------------------------------------------------------------

_driver = None


async def init_driver() -> bool:
    """Initialise the async Neo4j driver.  Returns True on success."""
    global _driver
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "princeps")
    try:
        _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        await _driver.verify_connectivity()
        log.info("Neo4j driver initialized (%s)", uri)
        await ensure_constraints()
        return True
    except Exception as e:
        log.warning("Neo4j unavailable — graph features disabled: %s", e)
        _driver = None
        return False


async def close_driver():
    """Shut down the Neo4j driver."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        log.info("Neo4j driver closed")


def driver_available() -> bool:
    return _driver is not None


# ---------------------------------------------------------------------------
# Schema — constraints & indexes (idempotent)
# ---------------------------------------------------------------------------

async def ensure_constraints():
    """Create uniqueness constraints and indexes if they don't exist."""
    if not _driver:
        return
    async with _driver.session() as session:
        for stmt in [
            "CREATE CONSTRAINT asset_id IF NOT EXISTS FOR (a:Asset) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT terminal_id IF NOT EXISTS FOR (t:Terminal) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT cnode_id IF NOT EXISTS FOR (c:ConnectivityNode) REQUIRE c.id IS UNIQUE",
            "CREATE INDEX asset_container IF NOT EXISTS FOR (a:Asset) ON (a.containerId)",
            "CREATE INDEX asset_voltage IF NOT EXISTS FOR (a:Asset) ON (a.voltageKv)",
            "CREATE INDEX asset_region IF NOT EXISTS FOR (a:Asset) ON (a.region)",
        ]:
            await session.run(stmt)
        log.info("Neo4j constraints & indexes ensured")


# ---------------------------------------------------------------------------
# Seed from PostgreSQL nged_* tables
# ---------------------------------------------------------------------------

async def seed_from_postgres(pg_pool):
    """Read NGED CIM tables from Postgres and create the Neo4j graph.

    Skips seeding if the graph already has Asset nodes.
    """
    if not _driver:
        log.warning("Neo4j driver not available — skipping graph seed")
        return

    # Check if already seeded
    async with _driver.session() as session:
        result = await session.run("MATCH (a:Asset) RETURN count(a) AS cnt")
        record = await result.single()
        if record and record["cnt"] > 0:
            log.info("Neo4j graph already seeded (%d assets) — skipping", record["cnt"])
            return

    log.info("Seeding Neo4j graph from PostgreSQL nged_* tables …")

    async with pg_pool.acquire() as conn:
        substations = await conn.fetch("SELECT id, name, region, voltage_kv FROM nged_substation")
        transformers = await conn.fetch(
            "SELECT id, name, substation_id, rated_mva, voltage_kv FROM nged_transformer"
        )
        lines = await conn.fetch(
            "SELECT id, name, length_km, r_ohm, x_ohm, voltage_kv, region FROM nged_line_segment"
        )
        consumers = await conn.fetch(
            "SELECT id, name, substation_id, p_mw, region FROM nged_energy_consumer"
        )

    async with _driver.session() as session:
        # --- Substations ---
        for s in substations:
            await session.run(
                """
                MERGE (a:Asset:Substation {id: $id})
                SET a.name = $name, a.region = $region, a.voltageKv = $voltage_kv,
                    a.assetType = 'Substation'
                WITH a
                MERGE (t:Terminal {id: $id + '_T1'})
                SET t.seq = 1
                MERGE (cn:ConnectivityNode {id: $id + '_BUS'})
                SET cn.name = $name + ' Bus'
                MERGE (a)-[:HAS_TERMINAL]->(t)
                MERGE (t)-[:CONNECTED_TO]->(cn)
                """,
                id=s["id"], name=s["name"],
                region=s["region"], voltage_kv=s["voltage_kv"],
            )

        # --- Transformers ---
        for t in transformers:
            sub_id = t["substation_id"]
            await session.run(
                """
                MERGE (a:Asset:PowerTransformer {id: $id})
                SET a.name = $name, a.ratedMva = $rated_mva,
                    a.voltageKv = $voltage_kv, a.containerId = $sub_id,
                    a.assetType = 'PowerTransformer'
                WITH a
                MERGE (t1:Terminal {id: $id + '_T1'})
                SET t1.seq = 1
                MERGE (t2:Terminal {id: $id + '_T2'})
                SET t2.seq = 2
                MERGE (a)-[:HAS_TERMINAL]->(t1)
                MERGE (a)-[:HAS_TERMINAL]->(t2)
                WITH a, t1
                MATCH (sub:Asset:Substation {id: $sub_id})
                MERGE (a)-[:CONTAINED_IN]->(sub)
                WITH t1, sub
                MATCH (sub)-[:HAS_TERMINAL]->(:Terminal)-[:CONNECTED_TO]->(cn:ConnectivityNode)
                MERGE (t1)-[:CONNECTED_TO]->(cn)
                """,
                id=t["id"], name=t["name"],
                rated_mva=t["rated_mva"], voltage_kv=t["voltage_kv"],
                sub_id=sub_id,
            )
            # Secondary terminal gets its own connectivity node
            await session.run(
                """
                MATCH (a:Asset:PowerTransformer {id: $id})-[:HAS_TERMINAL]->(t2:Terminal {id: $id + '_T2'})
                MERGE (cn2:ConnectivityNode {id: $id + '_SEC_BUS'})
                SET cn2.name = $name + ' Sec Bus'
                MERGE (t2)-[:CONNECTED_TO]->(cn2)
                """,
                id=t["id"], name=t["name"] or t["id"],
            )

        # --- Line segments ---
        for ln in lines:
            await session.run(
                """
                MERGE (a:Asset:ACLineSegment {id: $id})
                SET a.name = $name, a.lengthKm = $length_km,
                    a.rOhm = $r_ohm, a.xOhm = $x_ohm,
                    a.voltageKv = $voltage_kv, a.region = $region,
                    a.assetType = 'ACLineSegment'
                WITH a
                MERGE (t1:Terminal {id: $id + '_T1'})
                SET t1.seq = 1
                MERGE (t2:Terminal {id: $id + '_T2'})
                SET t2.seq = 2
                MERGE (cn1:ConnectivityNode {id: $id + '_BUS1'})
                SET cn1.name = $name + ' Bus 1'
                MERGE (cn2:ConnectivityNode {id: $id + '_BUS2'})
                SET cn2.name = $name + ' Bus 2'
                MERGE (a)-[:HAS_TERMINAL]->(t1)
                MERGE (a)-[:HAS_TERMINAL]->(t2)
                MERGE (t1)-[:CONNECTED_TO]->(cn1)
                MERGE (t2)-[:CONNECTED_TO]->(cn2)
                """,
                id=ln["id"], name=ln["name"] or ln["id"],
                length_km=ln["length_km"], r_ohm=ln["r_ohm"],
                x_ohm=ln["x_ohm"], voltage_kv=ln["voltage_kv"],
                region=ln["region"],
            )

        # --- Energy consumers ---
        for c in consumers:
            sub_id = c["substation_id"]
            await session.run(
                """
                MERGE (a:Asset:EnergyConsumer {id: $id})
                SET a.name = $name, a.pMw = $p_mw,
                    a.region = $region, a.containerId = $sub_id,
                    a.assetType = 'EnergyConsumer'
                WITH a
                MERGE (t:Terminal {id: $id + '_T1'})
                SET t.seq = 1
                MERGE (a)-[:HAS_TERMINAL]->(t)
                WITH a, t
                MATCH (sub:Asset:Substation {id: $sub_id})
                MERGE (a)-[:CONTAINED_IN]->(sub)
                WITH t, sub
                MATCH (sub)-[:HAS_TERMINAL]->(:Terminal)-[:CONNECTED_TO]->(cn:ConnectivityNode)
                MERGE (t)-[:CONNECTED_TO]->(cn)
                """,
                id=c["id"], name=c["name"] or c["id"],
                p_mw=c["p_mw"], region=c["region"],
                sub_id=sub_id,
            )

    # Final count
    async with _driver.session() as session:
        result = await session.run(
            "MATCH (a:Asset) RETURN count(a) AS assets"
        )
        rec = await result.single()
        result2 = await session.run(
            "MATCH ()-[r]->() RETURN count(r) AS rels"
        )
        rec2 = await result2.single()
        log.info(
            "Neo4j graph seeded: %d assets, %d relationships",
            rec["assets"] if rec else 0,
            rec2["rels"] if rec2 else 0,
        )


# ---------------------------------------------------------------------------
# Query: Circuit topology for React Flow
# ---------------------------------------------------------------------------

async def get_circuit_topology(substation_id: str, depth: int = 3) -> dict[str, Any]:
    """BFS traversal from a substation returning {nodes, edges, stats} for React Flow."""
    if not _driver:
        return {"nodes": [], "edges": [], "stats": {}, "error": "Neo4j unavailable"}

    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH path = (start:Asset:Substation {id: $sub_id})
                -[:HAS_TERMINAL|CONNECTED_TO|CONTAINED_IN*1..""" + str(min(depth * 4, 20)) + """]-
                (end)
            WHERE end:Asset OR end:ConnectivityNode
            UNWIND nodes(path) AS n
            UNWIND relationships(path) AS r
            WITH collect(DISTINCT n) AS allNodes, collect(DISTINCT r) AS allRels
            RETURN allNodes, allRels
            """,
            sub_id=substation_id,
        )
        record = await result.single()
        if not record:
            return {"nodes": [], "edges": [], "stats": {}}

        # Build React Flow nodes
        rf_nodes = []
        seen_ids = set()
        for node in record["allNodes"]:
            nid = node.get("id", node.element_id)
            if nid in seen_ids:
                continue
            seen_ids.add(nid)

            labels = list(node.labels) if hasattr(node, "labels") else []
            props = dict(node)
            node_type = "default"
            if "Substation" in labels:
                node_type = "substation"
            elif "PowerTransformer" in labels:
                node_type = "transformer"
            elif "ACLineSegment" in labels:
                node_type = "line"
            elif "EnergyConsumer" in labels:
                node_type = "consumer"
            elif "ConnectivityNode" in labels:
                node_type = "busbar"
            elif "Terminal" in labels:
                continue  # skip terminals — we connect through them

            rf_nodes.append({
                "id": nid,
                "type": node_type,
                "data": {
                    "label": props.get("name", nid),
                    **{k: v for k, v in props.items() if k != "name"},
                },
                "position": {"x": 0, "y": 0},  # layout computed client-side
            })

        # Build React Flow edges
        rf_edges = []
        seen_edges = set()
        for rel in record["allRels"]:
            src = rel.start_node.get("id", rel.start_node.element_id)
            tgt = rel.end_node.get("id", rel.end_node.element_id)
            eid = f"{src}->{tgt}"
            if eid in seen_edges:
                continue
            seen_edges.add(eid)
            # Skip edges involving Terminal nodes — flatten to asset↔busbar
            src_labels = list(rel.start_node.labels) if hasattr(rel.start_node, "labels") else []
            tgt_labels = list(rel.end_node.labels) if hasattr(rel.end_node, "labels") else []
            if "Terminal" in src_labels or "Terminal" in tgt_labels:
                continue
            rf_edges.append({
                "id": eid,
                "source": src,
                "target": tgt,
                "type": rel.type,
            })

        # If we lost edges by filtering Terminals, reconstruct asset↔busbar edges
        # by traversing Asset→Terminal→ConnectivityNode chains
        if not rf_edges:
            result2 = await session.run(
                """
                MATCH (start:Asset:Substation {id: $sub_id})
                    -[:HAS_TERMINAL|CONNECTED_TO|CONTAINED_IN*1..""" + str(min(depth * 4, 20)) + """]-
                    (end)
                WITH start, collect(DISTINCT end) AS reached
                UNWIND [start] + reached AS a
                WITH a WHERE a:Asset
                MATCH (a)-[:HAS_TERMINAL]->(t:Terminal)-[:CONNECTED_TO]->(cn:ConnectivityNode)
                RETURN a.id AS asset_id, cn.id AS bus_id
                """,
                sub_id=substation_id,
            )
            records = await result2.data()
            for rec in records:
                eid = f"{rec['asset_id']}->{rec['bus_id']}"
                if eid not in seen_edges:
                    seen_edges.add(eid)
                    rf_edges.append({
                        "id": eid,
                        "source": rec["asset_id"],
                        "target": rec["bus_id"],
                        "type": "CONNECTS",
                    })
            # Also add CONTAINED_IN edges
            result3 = await session.run(
                """
                MATCH (start:Asset:Substation {id: $sub_id})
                    -[:HAS_TERMINAL|CONNECTED_TO|CONTAINED_IN*1..""" + str(min(depth * 4, 20)) + """]-
                    (end)
                WITH start, collect(DISTINCT end) AS reached
                UNWIND [start] + reached AS a
                WITH a WHERE a:Asset
                MATCH (a)-[:CONTAINED_IN]->(parent:Asset)
                RETURN a.id AS child_id, parent.id AS parent_id
                """,
                sub_id=substation_id,
            )
            records3 = await result3.data()
            for rec in records3:
                eid = f"{rec['child_id']}->contained_{rec['parent_id']}"
                if eid not in seen_edges:
                    seen_edges.add(eid)
                    rf_edges.append({
                        "id": eid,
                        "source": rec["child_id"],
                        "target": rec["parent_id"],
                        "type": "CONTAINED_IN",
                    })

        # Stats
        type_counts = {}
        total_mva = 0.0
        total_mw = 0.0
        for n in rf_nodes:
            t = n["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
            if t == "transformer":
                total_mva += n["data"].get("ratedMva") or 0
            if t == "consumer":
                total_mw += n["data"].get("pMw") or 0

        return {
            "nodes": rf_nodes,
            "edges": rf_edges,
            "stats": {
                "assetCount": len(rf_nodes),
                "busbarCount": type_counts.get("busbar", 0),
                "totalMva": round(total_mva, 2),
                "totalMw": round(total_mw, 2),
                **type_counts,
            },
        }


# ---------------------------------------------------------------------------
# Query: Shortest electrical path
# ---------------------------------------------------------------------------

async def get_shortest_path(from_id: str, to_id: str) -> dict[str, Any]:
    """Find the shortest electrical path between two assets."""
    if not _driver:
        return {"path": [], "error": "Neo4j unavailable"}

    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (a:Asset {id: $from_id}), (b:Asset {id: $to_id}),
                  path = shortestPath((a)-[*..30]-(b))
            UNWIND nodes(path) AS n
            WITH n WHERE n:Asset OR n:ConnectivityNode
            RETURN collect({
                id: n.id, name: n.name,
                type: CASE
                    WHEN n:Substation THEN 'Substation'
                    WHEN n:PowerTransformer THEN 'PowerTransformer'
                    WHEN n:ACLineSegment THEN 'ACLineSegment'
                    WHEN n:EnergyConsumer THEN 'EnergyConsumer'
                    WHEN n:ConnectivityNode THEN 'ConnectivityNode'
                    ELSE 'Unknown'
                END
            }) AS path
            """,
            from_id=from_id, to_id=to_id,
        )
        record = await result.single()
        if not record:
            return {"path": [], "message": "No path found"}
        return {"path": record["path"]}


# ---------------------------------------------------------------------------
# Query: Downstream assets (impact analysis)
# ---------------------------------------------------------------------------

async def get_downstream_assets(substation_id: str) -> dict[str, Any]:
    """All assets downstream of a substation (for impact/outage analysis)."""
    if not _driver:
        return {"assets": [], "error": "Neo4j unavailable"}

    try:
        async with _driver.session() as session:
            result = await session.run(
                """
                OPTIONAL MATCH (sub:Asset:Substation {id: $sub_id})
                WITH sub WHERE sub IS NOT NULL
                OPTIONAL MATCH (child)-[:CONTAINED_IN]->(sub)
                WITH sub, collect(child) AS direct
                OPTIONAL MATCH (sub)-[:HAS_TERMINAL]->(:Terminal)-[:CONNECTED_TO]->(cn:ConnectivityNode)
                    <-[:CONNECTED_TO]-(:Terminal)<-[:HAS_TERMINAL]-(connected:Asset)
                WHERE connected.id <> sub.id
                WITH direct + collect(DISTINCT connected) AS all_assets
                UNWIND all_assets AS a
                WITH DISTINCT a WHERE a IS NOT NULL
                RETURN collect({
                    id: a.id, name: a.name, type: a.assetType,
                    voltageKv: a.voltageKv, ratedMva: a.ratedMva, pMw: a.pMw
                }) AS assets
                """,
                sub_id=substation_id,
            )
            record = await result.single()
            assets = record["assets"] if record else []
    except Exception as e:
        log.warning("Downstream query failed: %s", e)
        assets = []

    type_counts = {}
    for a in assets:
        t = a.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "substationId": substation_id,
        "assets": assets,
        "count": len(assets),
        "byType": type_counts,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def graph_health_check() -> dict[str, Any]:
    """Node and relationship counts for monitoring."""
    if not _driver:
        return {"available": False, "error": "Neo4j driver not initialized"}

    try:
        async with _driver.session() as session:
            result = await session.run("""
                MATCH (n) WITH labels(n) AS lbls, count(*) AS cnt
                UNWIND lbls AS lbl
                RETURN lbl, sum(cnt) AS count
                ORDER BY count DESC
            """)
            node_counts = {r["lbl"]: r["count"] async for r in result}

            result2 = await session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
            """)
            rel_counts = {r["type"]: r["count"] async for r in result2}

        return {
            "available": True,
            "nodes": node_counts,
            "relationships": rel_counts,
            "totalNodes": sum(node_counts.values()),
            "totalRelationships": sum(rel_counts.values()),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Regulatory Intelligence Graph Extension
# ---------------------------------------------------------------------------

async def ensure_regulatory_constraints():
    """Create constraints and indexes for regulatory node types."""
    if not _driver:
        return
    async with _driver.session() as session:
        for stmt in [
            "CREATE CONSTRAINT developer_name IF NOT EXISTS FOR (d:Developer) REQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT spv_id IF NOT EXISTS FOR (s:SPV) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT planning_ref IF NOT EXISTS FOR (p:PlanningApplication) REQUIRE p.ref IS UNIQUE",
            "CREATE CONSTRAINT grid_conn_id IF NOT EXISTS FOR (g:GridConnection) REQUIRE g.id IS UNIQUE",
            "CREATE CONSTRAINT dno_zone_code IF NOT EXISTS FOR (z:DNOZone) REQUIRE z.code IS UNIQUE",
            "CREATE INDEX developer_search IF NOT EXISTS FOR (d:Developer) ON (d.name)",
            "CREATE INDEX spv_developer IF NOT EXISTS FOR (s:SPV) ON (s.developer)",
        ]:
            try:
                await session.run(stmt)
            except Exception as e:
                log.debug("Regulatory constraint skipped: %s", e)
        log.info("Regulatory graph constraints ensured")


async def seed_regulatory_graph(pg_pool):
    """Populate regulatory graph from REPD, TEC register, and grid_upgrades tables."""
    if not _driver:
        log.warning("Neo4j unavailable — skipping regulatory graph seed")
        return

    log.info("Seeding regulatory graph from REPD + TEC + grid_upgrades …")

    async with pg_pool.acquire() as conn:
        # REPD projects → Developer, SPV, PlanningApplication
        repd_rows = await conn.fetch("""
            SELECT repd_id, site_name, technology, tech_category, capacity_mw,
                   status, developer, planning_ref
            FROM repd_projects
            WHERE developer IS NOT NULL
            LIMIT 2000
        """)

        # TEC register → GridConnection
        tec_rows = await conn.fetch("""
            SELECT tec_id, customer_name, connection_site, fuel_type, tech_category,
                   tec_mw, status, spv_name, parent_company
            FROM eso_tec_register
            LIMIT 2000
        """)

    async with _driver.session() as session:
        # --- Developers and PlanningApplications from REPD ---
        developers_seen = set()
        for r in repd_rows:
            dev_name = r["developer"]
            canonical = _canonical_developer_name(dev_name)

            if canonical not in developers_seen:
                await session.run(
                    "MERGE (d:Developer {name: $name})",
                    name=canonical,
                )
                developers_seen.add(canonical)

            # SPV = the project itself (site_name as SPV ID)
            spv_id = r["repd_id"]
            await session.run(
                """
                MERGE (s:SPV {id: $id})
                SET s.name = $name, s.techCategory = $tech, s.capacityMw = $cap, s.status = $status
                WITH s
                MATCH (d:Developer {name: $dev})
                MERGE (d)-[:DEVELOPS]->(s)
                """,
                id=spv_id, name=r["site_name"] or spv_id,
                tech=r["tech_category"], cap=r["capacity_mw"],
                status=r["status"], dev=canonical,
            )

            # PlanningApplication
            if r["planning_ref"]:
                await session.run(
                    """
                    MERGE (p:PlanningApplication {ref: $ref})
                    SET p.rePDId = $repd_id, p.techCategory = $tech, p.capacityMw = $cap
                    WITH p
                    MATCH (s:SPV {id: $spv_id})
                    MERGE (s)-[:HAS_PLANNING]->(p)
                    """,
                    ref=r["planning_ref"], repd_id=r["repd_id"],
                    tech=r["tech_category"], cap=r["capacity_mw"],
                    spv_id=spv_id,
                )

        # --- GridConnections from TEC register ---
        for r in tec_rows:
            await session.run(
                """
                MERGE (g:GridConnection {id: $id})
                SET g.customerName = $customer, g.connectionSite = $site,
                    g.fuelType = $fuel, g.tecMw = $mw, g.status = $status
                """,
                id=r["tec_id"], customer=r["customer_name"],
                site=r["connection_site"], fuel=r["fuel_type"],
                mw=r["tec_mw"], status=r["status"],
            )

            # Link to substation if name matches
            if r["connection_site"]:
                await session.run(
                    """
                    MATCH (g:GridConnection {id: $id})
                    MATCH (sub:Asset:Substation)
                    WHERE sub.name CONTAINS $site_fragment
                    WITH g, sub LIMIT 1
                    MERGE (g)-[:CONNECTS_TO]->(sub)
                    """,
                    id=r["tec_id"],
                    site_fragment=r["connection_site"][:20],
                )

            # Link PlanningApplication → GridConnection if same developer/SPV
            if r["spv_name"]:
                await session.run(
                    """
                    MATCH (g:GridConnection {id: $id})
                    MATCH (s:SPV) WHERE s.name CONTAINS $spv_fragment
                    WITH g, s LIMIT 1
                    MATCH (s)-[:HAS_PLANNING]->(p:PlanningApplication)
                    MERGE (p)-[:CONNECTS_VIA]->(g)
                    """,
                    id=r["tec_id"],
                    spv_fragment=r["spv_name"][:20],
                )

    log.info("Regulatory graph seeded (%d REPD, %d TEC)", len(repd_rows), len(tec_rows))


def _canonical_developer_name(name: str) -> str:
    """Normalise developer names for fuzzy matching and dedup."""
    import re
    canonical = name.strip()
    # Remove common suffixes
    for suffix in [" Ltd", " Limited", " PLC", " plc", " LLP", " Inc", " LLC"]:
        if canonical.endswith(suffix):
            canonical = canonical[: -len(suffix)]
    # Collapse whitespace
    canonical = re.sub(r"\s+", " ", canonical).strip()
    return canonical


def disambiguate_developer(name: str) -> str:
    """Return canonical developer name (synchronous helper)."""
    return _canonical_developer_name(name)


async def get_developer_portfolio(name: str) -> dict:
    """All SPVs, planning apps, and connections for a developer."""
    if not _driver:
        return {"developer": name, "error": "Neo4j unavailable"}

    canonical = _canonical_developer_name(name)

    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Developer {name: $name})-[:DEVELOPS]->(s:SPV)
            OPTIONAL MATCH (s)-[:HAS_PLANNING]->(p:PlanningApplication)
            OPTIONAL MATCH (p)-[:CONNECTS_VIA]->(g:GridConnection)
            RETURN d.name AS developer,
                   collect(DISTINCT {id: s.id, name: s.name, tech: s.techCategory,
                                     capacity: s.capacityMw, status: s.status}) AS spvs,
                   collect(DISTINCT {ref: p.ref, tech: p.techCategory}) AS planning,
                   collect(DISTINCT {id: g.id, site: g.connectionSite, mw: g.tecMw}) AS connections
            """,
            name=canonical,
        )
        record = await result.single()
        if not record:
            return {"developer": canonical, "spvs": [], "planning": [], "connections": []}

        return {
            "developer": record["developer"],
            "spvs": [dict(s) for s in record["spvs"] if s.get("id")],
            "planning": [dict(p) for p in record["planning"] if p.get("ref")],
            "connections": [dict(c) for c in record["connections"] if c.get("id")],
        }


async def get_connection_chain(planning_ref: str) -> dict:
    """PlanningApp → GridConnection → Substation → DNOZone chain."""
    if not _driver:
        return {"planning_ref": planning_ref, "error": "Neo4j unavailable"}

    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (p:PlanningApplication {ref: $ref})
            OPTIONAL MATCH (p)-[:CONNECTS_VIA]->(g:GridConnection)
            OPTIONAL MATCH (g)-[:CONNECTS_TO]->(sub:Asset:Substation)
            OPTIONAL MATCH (sub)-[:IN_ZONE]->(z:DNOZone)
            RETURN p.ref AS ref, p.techCategory AS tech, p.capacityMw AS capacity,
                   g.id AS connection_id, g.connectionSite AS connection_site, g.tecMw AS tec_mw,
                   sub.id AS substation_id, sub.name AS substation_name,
                   z.code AS zone_code
            """,
            ref=planning_ref,
        )
        record = await result.single()
        if not record:
            return {"planning_ref": planning_ref, "chain": None}

        return {
            "planning_ref": record["ref"],
            "technology": record["tech"],
            "capacity_mw": record["capacity"],
            "grid_connection": {
                "id": record["connection_id"],
                "site": record["connection_site"],
                "tec_mw": record["tec_mw"],
            } if record["connection_id"] else None,
            "substation": {
                "id": record["substation_id"],
                "name": record["substation_name"],
            } if record["substation_id"] else None,
            "dno_zone": record["zone_code"],
        }


async def get_zone_intelligence(dno_zone: str) -> dict:
    """All assets, connections, and planning applications in a DNO zone."""
    if not _driver:
        return {"zone": dno_zone, "error": "Neo4j unavailable"}

    async with _driver.session() as session:
        result = await session.run(
            """
            MATCH (z:DNOZone {code: $zone})
            OPTIONAL MATCH (sub:Asset:Substation)-[:IN_ZONE]->(z)
            OPTIONAL MATCH (g:GridConnection)-[:CONNECTS_TO]->(sub)
            OPTIONAL MATCH (p:PlanningApplication)-[:CONNECTS_VIA]->(g)
            RETURN z.code AS zone,
                   collect(DISTINCT {id: sub.id, name: sub.name, voltage: sub.voltageKv}) AS substations,
                   collect(DISTINCT {id: g.id, site: g.connectionSite, mw: g.tecMw, status: g.status}) AS connections,
                   collect(DISTINCT {ref: p.ref, tech: p.techCategory, cap: p.capacityMw}) AS planning
            """,
            zone=dno_zone,
        )
        record = await result.single()
        if not record:
            return {"zone": dno_zone, "substations": [], "connections": [], "planning": []}

        return {
            "zone": record["zone"],
            "substations": [dict(s) for s in record["substations"] if s.get("id")],
            "connections": [dict(c) for c in record["connections"] if c.get("id")],
            "planning": [dict(p) for p in record["planning"] if p.get("ref")],
        }
