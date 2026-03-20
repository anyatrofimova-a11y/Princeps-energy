#!/usr/bin/env python3
"""
Neo4j Graph Populator for Princeps Energy Grid
================================================
Reads grid_substations and grid_lines from PostGIS and populates Neo4j
with a DTDL-inspired energy grid ontology.

Node types:
  - GridSupplyPoint     (voltage_kv >= 275)
  - BulkSupplyPoint     (100 <= voltage_kv < 275)
  - PrimarySubstation   (11 <= voltage_kv < 100)
  - SecondarySubstation (voltage_kv < 11 or NULL)
  - PowerLine           (from grid_lines)

Relationships:
  - FEEDS          — higher-voltage substation -> lower-voltage substation (via line proximity)
  - CONNECTED_BY   — PowerLine <-> Substation (both endpoints)

Usage:
  python utils/neo4j_graph_populator.py
"""

import asyncio
import os
import sys
import time
from typing import Optional

import asyncpg
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://anyatrofimova@localhost:5432/feasibly")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "princeps")

BATCH_SIZE = 500
PROXIMITY_THRESHOLD_M = 2000  # 2 km in metres (SRID 27700 is in metres)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def classify_substation(voltage_kv: Optional[float]) -> str:
    """Classify substation into DTDL ontology node label based on voltage."""
    if voltage_kv is None:
        return "SecondarySubstation"
    if voltage_kv >= 275:
        return "GridSupplyPoint"
    if voltage_kv >= 100:
        return "BulkSupplyPoint"
    if voltage_kv >= 11:
        return "PrimarySubstation"
    return "SecondarySubstation"


def fmt_float(val) -> Optional[float]:
    """Convert Decimal/None to float for Neo4j driver."""
    if val is None:
        return None
    return float(val)


# ─── PostGIS Reads ────────────────────────────────────────────────────────────

async def fetch_substations(conn: asyncpg.Connection) -> list[dict]:
    """Read all substations with lat/lon in EPSG:4326."""
    rows = await conn.fetch("""
        SELECT
            id,
            name,
            dno,
            voltage_kv,
            site_type,
            demand_mw,
            generation_mw,
            demand_headroom_mw,
            gen_headroom_mw,
            ST_X(ST_Transform(geom, 4326)) AS lon,
            ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        WHERE geom IS NOT NULL
        ORDER BY id
    """)
    substations = []
    for r in rows:
        substations.append({
            "id": r["id"],
            "name": r["name"],
            "dno": r["dno"],
            "voltage_kv": fmt_float(r["voltage_kv"]),
            "site_type": r["site_type"],
            "demand_mw": fmt_float(r["demand_mw"]),
            "generation_mw": fmt_float(r["generation_mw"]),
            "demand_headroom_mw": fmt_float(r["demand_headroom_mw"]),
            "gen_headroom_mw": fmt_float(r["gen_headroom_mw"]),
            "lon": fmt_float(r["lon"]),
            "lat": fmt_float(r["lat"]),
            "label": classify_substation(fmt_float(r["voltage_kv"])),
        })
    return substations


async def fetch_lines(conn: asyncpg.Connection) -> list[dict]:
    """Read all grid lines with start/end points in EPSG:4326 and native SRID 27700."""
    rows = await conn.fetch("""
        SELECT
            id,
            osm_id,
            voltage_kv,
            circuits,
            operator,
            length_km,
            ST_X(ST_Transform(ST_StartPoint(geom), 4326)) AS start_lon,
            ST_Y(ST_Transform(ST_StartPoint(geom), 4326)) AS start_lat,
            ST_X(ST_Transform(ST_EndPoint(geom), 4326))   AS end_lon,
            ST_Y(ST_Transform(ST_EndPoint(geom), 4326))   AS end_lat,
            ST_X(ST_StartPoint(geom)) AS start_x_27700,
            ST_Y(ST_StartPoint(geom)) AS start_y_27700,
            ST_X(ST_EndPoint(geom))   AS end_x_27700,
            ST_Y(ST_EndPoint(geom))   AS end_y_27700
        FROM grid_lines
        WHERE geom IS NOT NULL
        ORDER BY id
    """)
    lines = []
    for r in rows:
        lines.append({
            "id": r["id"],
            "osm_id": r["osm_id"],
            "voltage_kv": fmt_float(r["voltage_kv"]),
            "circuits": r["circuits"],
            "operator": r["operator"],
            "length_km": fmt_float(r["length_km"]),
            "start_lon": fmt_float(r["start_lon"]),
            "start_lat": fmt_float(r["start_lat"]),
            "end_lon": fmt_float(r["end_lon"]),
            "end_lat": fmt_float(r["end_lat"]),
            "start_x_27700": fmt_float(r["start_x_27700"]),
            "start_y_27700": fmt_float(r["start_y_27700"]),
            "end_x_27700": fmt_float(r["end_x_27700"]),
            "end_y_27700": fmt_float(r["end_y_27700"]),
        })
    return lines


async def find_nearest_substations_for_lines(conn: asyncpg.Connection) -> list[dict]:
    """
    For each line, find the nearest substation within 2km of each endpoint.
    Uses PostGIS spatial query for accuracy and performance.
    Returns list of dicts with line_id, start_sub_id, end_sub_id.
    """
    rows = await conn.fetch("""
        WITH line_endpoints AS (
            SELECT
                l.id AS line_id,
                l.voltage_kv AS line_voltage_kv,
                l.length_km,
                ST_StartPoint(l.geom) AS start_pt,
                ST_EndPoint(l.geom)   AS end_pt
            FROM grid_lines l
            WHERE l.geom IS NOT NULL
        )
        SELECT
            le.line_id,
            le.line_voltage_kv,
            le.length_km,
            (
                SELECT s.id FROM grid_substations s
                WHERE s.geom IS NOT NULL
                  AND ST_DWithin(s.geom, le.start_pt, $1)
                ORDER BY ST_Distance(s.geom, le.start_pt)
                LIMIT 1
            ) AS start_sub_id,
            (
                SELECT s.id FROM grid_substations s
                WHERE s.geom IS NOT NULL
                  AND ST_DWithin(s.geom, le.end_pt, $1)
                ORDER BY ST_Distance(s.geom, le.end_pt)
                LIMIT 1
            ) AS end_sub_id
        FROM line_endpoints le
    """, PROXIMITY_THRESHOLD_M)

    results = []
    for r in rows:
        results.append({
            "line_id": r["line_id"],
            "line_voltage_kv": fmt_float(r["line_voltage_kv"]),
            "length_km": fmt_float(r["length_km"]),
            "start_sub_id": r["start_sub_id"],
            "end_sub_id": r["end_sub_id"],
        })
    return results


# ─── Neo4j Write Operations ──────────────────────────────────────────────────

def clear_graph(driver):
    """Delete all nodes and relationships in the graph."""
    print("[1/7] Clearing existing graph...")
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS cnt")
        count = result.single()["cnt"]
        print(f"       Found {count:,} existing nodes — deleting...")
        # Delete in batches to avoid memory issues with large graphs
        while True:
            result = session.run("""
                MATCH (n)
                WITH n LIMIT 10000
                DETACH DELETE n
                RETURN count(*) AS deleted
            """)
            deleted = result.single()["deleted"]
            if deleted == 0:
                break
            print(f"       Deleted {deleted:,} nodes...")
    print("       Graph cleared.")


def create_indexes(driver):
    """Create indexes on node id and name for fast lookups."""
    print("[2/7] Creating indexes...")
    labels = ["GridSupplyPoint", "BulkSupplyPoint", "PrimarySubstation", "SecondarySubstation", "PowerLine"]
    with driver.session() as session:
        for label in labels:
            # Index on id
            try:
                session.run(f"CREATE INDEX idx_{label.lower()}_id IF NOT EXISTS FOR (n:{label}) ON (n.id)")
                print(f"       Index on {label}.id created.")
            except Exception as e:
                print(f"       Index on {label}.id: {e}")
            # Index on name
            try:
                session.run(f"CREATE INDEX idx_{label.lower()}_name IF NOT EXISTS FOR (n:{label}) ON (n.name)")
                print(f"       Index on {label}.name created.")
            except Exception as e:
                print(f"       Index on {label}.name: {e}")
    print("       Indexes created.")


def insert_substations(driver, substations: list[dict]):
    """Insert substation nodes in batches, using the correct label per voltage tier."""
    print(f"[3/7] Inserting {len(substations):,} substation nodes...")
    t0 = time.time()

    # Group by label for efficient Cypher
    by_label: dict[str, list[dict]] = {}
    for s in substations:
        label = s["label"]
        by_label.setdefault(label, []).append(s)

    total_inserted = 0
    for label, subs in by_label.items():
        print(f"       {label}: {len(subs):,} nodes")
        for i in range(0, len(subs), BATCH_SIZE):
            batch = subs[i : i + BATCH_SIZE]
            with driver.session() as session:
                session.run(
                    f"""
                    UNWIND $batch AS sub
                    CREATE (n:{label} {{
                        id: sub.id,
                        name: sub.name,
                        dno: sub.dno,
                        voltage_kv: sub.voltage_kv,
                        site_type: sub.site_type,
                        demand_mw: sub.demand_mw,
                        generation_mw: sub.generation_mw,
                        demand_headroom_mw: sub.demand_headroom_mw,
                        gen_headroom_mw: sub.gen_headroom_mw,
                        lat: sub.lat,
                        lon: sub.lon
                    }})
                    """,
                    batch=batch,
                )
            total_inserted += len(batch)
            if total_inserted % 2000 == 0 or total_inserted == len(substations):
                print(f"       {total_inserted:,}/{len(substations):,} inserted...")

    elapsed = time.time() - t0
    print(f"       Done in {elapsed:.1f}s — {total_inserted:,} substation nodes inserted.")


def insert_powerlines(driver, lines: list[dict]):
    """Insert PowerLine nodes in batches."""
    print(f"[4/7] Inserting {len(lines):,} PowerLine nodes...")
    t0 = time.time()

    total_inserted = 0
    for i in range(0, len(lines), BATCH_SIZE):
        batch = lines[i : i + BATCH_SIZE]
        with driver.session() as session:
            session.run(
                """
                UNWIND $batch AS line
                CREATE (n:PowerLine {
                    id: line.id,
                    name: COALESCE('Line-' + toString(line.osm_id), 'Line-' + toString(line.id)),
                    osm_id: line.osm_id,
                    voltage_kv: line.voltage_kv,
                    circuits: line.circuits,
                    operator: line.operator,
                    length_km: line.length_km,
                    start_lat: line.start_lat,
                    start_lon: line.start_lon,
                    end_lat: line.end_lat,
                    end_lon: line.end_lon
                })
                """,
                batch=batch,
            )
        total_inserted += len(batch)
        if total_inserted % 2000 == 0 or total_inserted == len(lines):
            print(f"       {total_inserted:,}/{len(lines):,} inserted...")

    elapsed = time.time() - t0
    print(f"       Done in {elapsed:.1f}s — {total_inserted:,} PowerLine nodes inserted.")


def create_connected_by_relationships(driver, line_sub_links: list[dict]):
    """
    Create CONNECTED_BY relationships between PowerLine nodes and their
    nearest substations (start and end endpoints).
    """
    print(f"[5/7] Creating CONNECTED_BY relationships...")
    t0 = time.time()

    # Build batches: each entry has line_id and sub_id
    start_links = []
    end_links = []
    for link in line_sub_links:
        if link["start_sub_id"] is not None:
            start_links.append({"line_id": link["line_id"], "sub_id": link["start_sub_id"]})
        if link["end_sub_id"] is not None:
            end_links.append({"line_id": link["line_id"], "sub_id": link["end_sub_id"]})

    all_labels = ["GridSupplyPoint", "BulkSupplyPoint", "PrimarySubstation", "SecondarySubstation"]

    # Helper to create CONNECTED_BY in batches, matching any substation label
    def create_links(links: list[dict], endpoint_name: str):
        total = 0
        for i in range(0, len(links), BATCH_SIZE):
            batch = links[i : i + BATCH_SIZE]
            with driver.session() as session:
                # Use a union-style match across all substation labels
                session.run(
                    """
                    UNWIND $batch AS link
                    MATCH (pl:PowerLine {id: link.line_id})
                    WITH pl, link
                    CALL {
                        WITH link
                        OPTIONAL MATCH (s:GridSupplyPoint {id: link.sub_id}) RETURN s AS sub
                        UNION
                        WITH link
                        OPTIONAL MATCH (s:BulkSupplyPoint {id: link.sub_id}) RETURN s AS sub
                        UNION
                        WITH link
                        OPTIONAL MATCH (s:PrimarySubstation {id: link.sub_id}) RETURN s AS sub
                        UNION
                        WITH link
                        OPTIONAL MATCH (s:SecondarySubstation {id: link.sub_id}) RETURN s AS sub
                    }
                    WITH pl, sub
                    WHERE sub IS NOT NULL
                    WITH pl, head(collect(sub)) AS s
                    CREATE (pl)-[:CONNECTED_BY]->(s)
                    """,
                    batch=batch,
                )
            total += len(batch)
            if total % 2000 == 0 or total == len(links):
                print(f"       {endpoint_name}: {total:,}/{len(links):,} processed...")
        return total

    start_count = create_links(start_links, "start-endpoint")
    end_count = create_links(end_links, "end-endpoint")

    elapsed = time.time() - t0
    print(f"       Done in {elapsed:.1f}s — {start_count + end_count:,} CONNECTED_BY relationships.")


def create_feeds_relationships(driver, line_sub_links: list[dict], substations: list[dict]):
    """
    Create FEEDS relationships between substations connected by lines.
    Direction: higher voltage -> lower voltage. If same voltage, use the
    substation id ordering (lower id feeds higher id) as a convention.
    """
    print(f"[6/7] Creating FEEDS relationships...")
    t0 = time.time()

    # Build substation lookup by id
    sub_lookup = {s["id"]: s for s in substations}

    # Collect unique (from_sub, to_sub) pairs with line metadata
    feeds_pairs: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()

    for link in line_sub_links:
        start_id = link["start_sub_id"]
        end_id = link["end_sub_id"]
        if start_id is None or end_id is None or start_id == end_id:
            continue

        # Determine direction: higher voltage feeds lower voltage
        start_sub = sub_lookup.get(start_id)
        end_sub = sub_lookup.get(end_id)
        if start_sub is None or end_sub is None:
            continue

        v_start = start_sub.get("voltage_kv") or 0.0
        v_end = end_sub.get("voltage_kv") or 0.0

        if v_start >= v_end:
            from_id, to_id = start_id, end_id
        else:
            from_id, to_id = end_id, start_id

        pair_key = (from_id, to_id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        from_sub = sub_lookup[from_id]
        to_sub = sub_lookup[to_id]

        feeds_pairs.append({
            "from_id": from_id,
            "to_id": to_id,
            "from_label": from_sub["label"],
            "to_label": to_sub["label"],
            "voltage_kv": link["line_voltage_kv"],
            "length_km": link["length_km"],
            "line_name": f"Line-{link['line_id']}",
        })

    print(f"       {len(feeds_pairs):,} unique FEEDS pairs identified.")

    total_created = 0
    for i in range(0, len(feeds_pairs), BATCH_SIZE):
        batch = feeds_pairs[i : i + BATCH_SIZE]
        with driver.session() as session:
            session.run(
                """
                UNWIND $batch AS feed
                CALL {
                    WITH feed
                    OPTIONAL MATCH (s:GridSupplyPoint {id: feed.from_id}) RETURN s AS from_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:BulkSupplyPoint {id: feed.from_id}) RETURN s AS from_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:PrimarySubstation {id: feed.from_id}) RETURN s AS from_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:SecondarySubstation {id: feed.from_id}) RETURN s AS from_node
                }
                WITH feed, from_node
                WHERE from_node IS NOT NULL
                WITH feed, head(collect(from_node)) AS f
                CALL {
                    WITH feed
                    OPTIONAL MATCH (s:GridSupplyPoint {id: feed.to_id}) RETURN s AS to_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:BulkSupplyPoint {id: feed.to_id}) RETURN s AS to_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:PrimarySubstation {id: feed.to_id}) RETURN s AS to_node
                    UNION
                    WITH feed
                    OPTIONAL MATCH (s:SecondarySubstation {id: feed.to_id}) RETURN s AS to_node
                }
                WITH feed, f, to_node
                WHERE to_node IS NOT NULL
                WITH feed, f, head(collect(to_node)) AS t
                CREATE (f)-[:FEEDS {
                    voltage_kv: feed.voltage_kv,
                    length_km: feed.length_km,
                    line_name: feed.line_name
                }]->(t)
                """,
                batch=batch,
            )
        total_created += len(batch)
        if total_created % 2000 == 0 or total_created == len(feeds_pairs):
            print(f"       {total_created:,}/{len(feeds_pairs):,} created...")

    elapsed = time.time() - t0
    print(f"       Done in {elapsed:.1f}s — {total_created:,} FEEDS relationships.")


def print_summary(driver):
    """Print final graph summary."""
    print("[7/7] Graph summary:")
    with driver.session() as session:
        labels = ["GridSupplyPoint", "BulkSupplyPoint", "PrimarySubstation", "SecondarySubstation", "PowerLine"]
        for label in labels:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            cnt = result.single()["cnt"]
            print(f"       {label}: {cnt:,} nodes")

        result = session.run("MATCH ()-[r:FEEDS]->() RETURN count(r) AS cnt")
        feeds_cnt = result.single()["cnt"]
        print(f"       FEEDS relationships: {feeds_cnt:,}")

        result = session.run("MATCH ()-[r:CONNECTED_BY]->() RETURN count(r) AS cnt")
        conn_cnt = result.single()["cnt"]
        print(f"       CONNECTED_BY relationships: {conn_cnt:,}")

        result = session.run("MATCH (n) RETURN count(n) AS cnt")
        total = result.single()["cnt"]
        result = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
        total_rels = result.single()["cnt"]
        print(f"       TOTAL: {total:,} nodes, {total_rels:,} relationships")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("  Princeps — Neo4j Grid Graph Populator")
    print("=" * 70)
    print(f"  PostGIS:  {DATABASE_URL}")
    print(f"  Neo4j:    {NEO4J_URI}")
    print(f"  Batch:    {BATCH_SIZE}")
    print(f"  Proximity threshold: {PROXIMITY_THRESHOLD_M}m")
    print("=" * 70)
    print()

    t_start = time.time()

    # ── Connect to PostGIS ──
    print("Connecting to PostGIS...")
    try:
        pg_conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"ERROR: Could not connect to PostGIS: {e}")
        sys.exit(1)
    print("Connected to PostGIS.\n")

    # ── Read substations ──
    print("Reading substations from grid_substations...")
    substations = await fetch_substations(pg_conn)
    print(f"  Read {len(substations):,} substations.")

    label_counts = {}
    for s in substations:
        label_counts[s["label"]] = label_counts.get(s["label"], 0) + 1
    for label, count in sorted(label_counts.items()):
        print(f"    {label}: {count:,}")
    print()

    # ── Read lines ──
    print("Reading lines from grid_lines...")
    lines = await fetch_lines(pg_conn)
    print(f"  Read {len(lines):,} lines.\n")

    # ── Find nearest substations for line endpoints ──
    print("Finding nearest substations for line endpoints (spatial query, may take a moment)...")
    t_spatial = time.time()
    line_sub_links = await find_nearest_substations_for_lines(pg_conn)
    spatial_time = time.time() - t_spatial

    matched_start = sum(1 for l in line_sub_links if l["start_sub_id"] is not None)
    matched_end = sum(1 for l in line_sub_links if l["end_sub_id"] is not None)
    matched_both = sum(1 for l in line_sub_links if l["start_sub_id"] is not None and l["end_sub_id"] is not None)
    print(f"  Spatial query completed in {spatial_time:.1f}s.")
    print(f"  Start endpoint matched: {matched_start:,}/{len(line_sub_links):,}")
    print(f"  End endpoint matched:   {matched_end:,}/{len(line_sub_links):,}")
    print(f"  Both endpoints matched: {matched_both:,}/{len(line_sub_links):,}")
    print()

    await pg_conn.close()
    print("PostGIS connection closed.\n")

    # ── Connect to Neo4j ──
    print("Connecting to Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Could not connect to Neo4j: {e}")
        sys.exit(1)
    print("Connected to Neo4j.\n")

    # ── Populate graph ──
    clear_graph(driver)
    print()
    create_indexes(driver)
    print()
    insert_substations(driver, substations)
    print()
    insert_powerlines(driver, lines)
    print()
    create_connected_by_relationships(driver, line_sub_links)
    print()
    create_feeds_relationships(driver, line_sub_links, substations)
    print()
    print_summary(driver)

    driver.close()
    print()

    elapsed_total = time.time() - t_start
    print(f"Completed in {elapsed_total:.1f}s.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
