"""LTDS CIM router — ingest + read endpoints for the NGED CIM model."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool
from utils.ltds_cim_ingester import (
    ingest_all,
    ingest_region_file,
    match_coordinates_fuzzy,
    get_cim_stats,
    list_substations,
    get_substation_detail,
    get_substations_geojson,
)

router = APIRouter(tags=["ltds-cim"], prefix="/api/ltds")


@router.post("/ingest")
async def ingest(
    download_dir: str = Query("/Users/anyatrofimova/Downloads"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ingest every LTDS_*_EQ_*.xml found in the download dir + the CSV."""
    return await ingest_all(pool, download_dir=Path(download_dir))


@router.post("/match-coordinates")
async def match_coordinates(pool: asyncpg.Pool = Depends(get_pool)):
    """Fuzzy-join cim_substations to grid_substations by name to populate lat/lon."""
    n = await match_coordinates_fuzzy(pool)
    return {"updated": n}


@router.get("/stats")
async def stats(pool: asyncpg.Pool = Depends(get_pool)):
    """CIM stats — totals + breakdown by licence area + PSR type."""
    return await get_cim_stats(pool)


@router.get("/substations")
async def substations(
    licence_area: str | None = Query(None),
    psr_type: str | None = Query(None),
    limit: int = Query(20000, ge=1, le=50000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Substation index for the CIM Graph left sidebar."""
    return await list_substations(pool, licence_area=licence_area, psr_type=psr_type, limit=limit)


@router.get("/substations.geojson")
async def substations_geojson(pool: asyncpg.Pool = Depends(get_pool)):
    """Located substations as GeoJSON."""
    return await get_substations_geojson(pool)


@router.get("/substations/{mrid}")
async def substation_detail(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Full detail for a single substation — voltage levels, transformers, counts."""
    detail = await get_substation_detail(pool, mrid)
    if not detail:
        raise HTTPException(404, f"Substation {mrid} not found")
    return detail


@router.get("/substations/{mrid}/circuit")
async def substation_circuit(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Busbar-level circuit graph for the substation — nodes + edges shape
    designed for React Flow / Cytoscape. Pure Postgres, no Neo4j needed.

    Returns:
      {
        "substation": {mrid, name, region, voltage_levels: [{kv, mrid, name}]},
        "nodes": [{id, type, name, voltage_kv, parent_id}, ...],
        "edges": [{from, to, terminal_mrid, voltage_kv}, ...],
        "assets": {busbars, transformers, switches, generators, loads, lines, equiv}
      }
    """
    async with pool.acquire(timeout=10) as conn:
        sub = await conn.fetchrow(
            """
            SELECT mrid, name, dno, licence_area, psr_type, substation_number,
                   lat, lon
            FROM ltds_substations WHERE mrid = $1
            """,
            mrid,
        )
        if not sub:
            raise HTTPException(404, f"Substation {mrid} not found")

        vls = await conn.fetch(
            """
            SELECT mrid, name, COALESCE(nominal_voltage_kv, 0) AS voltage_kv
            FROM ltds_voltage_levels
            WHERE substation_mrid = $1
            ORDER BY voltage_kv DESC NULLS LAST, name
            """,
            mrid,
        )
        vl_mrids = [v["mrid"] for v in vls]

        # Equipment hosted by these voltage levels.
        async def _by_vl(table: str, extra_cols: str = "") -> list[dict]:
            if not vl_mrids:
                return []
            sql = f"""
                SELECT mrid, name {extra_cols}
                FROM {table}
                WHERE voltage_level_mrid = ANY($1::text[])
                ORDER BY name
                LIMIT 5000
            """
            rows = await conn.fetch(sql, vl_mrids)
            return [dict(r) for r in rows]

        busbars = await _by_vl("ltds_busbars")
        switches = await _by_vl("ltds_switches", ", switch_type, normal_open")
        generators = await _by_vl(
            "ltds_generators", ", gen_type, rated_mva, min_mw, max_mw"
        )
        loads = await _by_vl("ltds_loads", ", p_fixed_mw, q_fixed_mvar")
        equiv = await _by_vl(
            "ltds_equivalent_injections", ", p_mw, q_mvar"
        )

        transformers = await conn.fetch(
            """
            SELECT mrid, name FROM ltds_power_transformers
            WHERE substation_mrid = $1
            ORDER BY name
            """,
            mrid,
        )
        tf_mrids = [t["mrid"] for t in transformers]
        tf_ends = await conn.fetch(
            """
            SELECT mrid, transformer_mrid, end_number, rated_s_mva, rated_u_kv,
                   r_ohm, x_ohm, terminal_mrid, connectivity_mrid
            FROM ltds_transformer_ends
            WHERE transformer_mrid = ANY($1::text[])
            ORDER BY transformer_mrid, end_number
            """,
            tf_mrids,
        ) if tf_mrids else []

        # Terminals + connectivity nodes for everything we just gathered.
        equip_mrids = (
            [b["mrid"] for b in busbars]
            + [s["mrid"] for s in switches]
            + [g["mrid"] for g in generators]
            + [l["mrid"] for l in loads]
            + [e["mrid"] for e in equiv]
            + tf_mrids
        )
        terminals = await conn.fetch(
            """
            SELECT mrid, conducting_eq_mrid, connectivity_mrid, sequence_number
            FROM ltds_terminals
            WHERE conducting_eq_mrid = ANY($1::text[])
            """,
            equip_mrids,
        ) if equip_mrids else []
        cn_mrids = list({t["connectivity_mrid"] for t in terminals if t["connectivity_mrid"]})
        connectivity_nodes = await conn.fetch(
            """
            SELECT mrid, name, container_mrid
            FROM ltds_connectivity_nodes
            WHERE mrid = ANY($1::text[])
            """,
            cn_mrids,
        ) if cn_mrids else []

        # AC line segments touching any of our connectivity nodes (incoming
        # circuits from neighbouring substations).
        ac_lines_in = await conn.fetch(
            """
            SELECT DISTINCT al.mrid, al.name, al.length_km, al.r_ohm, al.x_ohm,
                   al.b_siemens, l.name AS line_name, al.line_mrid
            FROM ltds_ac_lines al
            LEFT JOIN ltds_lines l ON al.line_mrid = l.mrid
            JOIN ltds_terminals t ON t.conducting_eq_mrid = al.mrid
            WHERE t.connectivity_mrid = ANY($1::text[])
            LIMIT 500
            """,
            cn_mrids,
        ) if cn_mrids else []

    # Build the nodes + edges shape for React Flow.
    nodes: list[dict] = []
    for b in busbars:
        nodes.append({"id": b["mrid"], "type": "Busbar", "name": b["name"]})
    for s in switches:
        nodes.append({
            "id": s["mrid"], "type": s.get("switch_type") or "Switch",
            "name": s["name"], "normal_open": s.get("normal_open"),
        })
    for g in generators:
        nodes.append({
            "id": g["mrid"], "type": "Generator",
            "gen_type": g.get("gen_type"), "name": g["name"],
            "rated_mva": g.get("rated_mva"),
            "min_mw": g.get("min_mw"), "max_mw": g.get("max_mw"),
        })
    for ld in loads:
        nodes.append({
            "id": ld["mrid"], "type": "EnergyConsumer", "name": ld["name"],
            "p_mw": ld.get("p_fixed_mw"), "q_mvar": ld.get("q_fixed_mvar"),
        })
    for e in equiv:
        nodes.append({
            "id": e["mrid"], "type": "EquivalentInjection", "name": e["name"],
            "p_mw": e.get("p_mw"), "q_mvar": e.get("q_mvar"),
        })
    for t in transformers:
        nodes.append({"id": t["mrid"], "type": "PowerTransformer", "name": t["name"]})
    for cn in connectivity_nodes:
        nodes.append({"id": cn["mrid"], "type": "ConnectivityNode", "name": cn["name"]})

    edges: list[dict] = []
    for term in terminals:
        if term["connectivity_mrid"]:
            edges.append({
                "from": term["conducting_eq_mrid"],
                "to": term["connectivity_mrid"],
                "terminal_mrid": term["mrid"],
                "sequence_number": term["sequence_number"],
            })

    return {
        "substation": {
            "mrid": sub["mrid"], "name": sub["name"],
            "dno": sub["dno"], "licence_area": sub["licence_area"],
            "psr_type": sub["psr_type"],
            "substation_number": sub["substation_number"],
            "lat": sub["lat"], "lon": sub["lon"],
            "voltage_levels": [dict(v) for v in vls],
        },
        "nodes": nodes,
        "edges": edges,
        "ac_lines_incoming": [dict(r) for r in ac_lines_in],
        "transformer_ends": [dict(r) for r in tf_ends],
        "assets": {
            "busbars": len(busbars),
            "transformers": len(transformers),
            "switches": len(switches),
            "generators": len(generators),
            "loads": len(loads),
            "equivalent_injections": len(equiv),
            "ac_lines_incoming": len(ac_lines_in),
            "connectivity_nodes": len(connectivity_nodes),
            "terminals": len(terminals),
        },
        "attribution": "NGED LTDS CIM (Open Data Licence v1.0)",
    }


@router.get("/substations/{mrid}/connections")
async def substation_connections(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Adjacent substations connected via AC line segments — the
    "substation connections" graph Squid shows in the Table++ view.
    """
    async with pool.acquire(timeout=10) as conn:
        sub = await conn.fetchrow(
            "SELECT mrid, name FROM ltds_substations WHERE mrid = $1", mrid,
        )
        if not sub:
            raise HTTPException(404, f"Substation {mrid} not found")

        rows = await conn.fetch(
            """
            WITH our_cns AS (
              SELECT cn.mrid
              FROM ltds_connectivity_nodes cn
              JOIN ltds_voltage_levels vl ON cn.container_mrid = vl.mrid
              WHERE vl.substation_mrid = $1
            ),
            our_lines AS (
              SELECT DISTINCT al.line_mrid, al.mrid AS ac_mrid, al.name AS ac_name,
                     al.length_km, l.name AS line_name
              FROM ltds_ac_lines al
              LEFT JOIN ltds_lines l ON al.line_mrid = l.mrid
              JOIN ltds_terminals t ON t.conducting_eq_mrid = al.mrid
              WHERE t.connectivity_mrid IN (SELECT mrid FROM our_cns)
            )
            SELECT ol.ac_mrid, ol.ac_name,
                   COALESCE(ol.length_km * 1000.0, NULL) AS length_m,
                   ol.length_km, ol.line_name,
                   far_sub.mrid AS neighbour_mrid, far_sub.name AS neighbour_name
            FROM our_lines ol
            JOIN ltds_terminals t2 ON t2.conducting_eq_mrid = ol.ac_mrid
            JOIN ltds_connectivity_nodes cn2 ON cn2.mrid = t2.connectivity_mrid
            LEFT JOIN ltds_voltage_levels vl2 ON cn2.container_mrid = vl2.mrid
            LEFT JOIN ltds_substations far_sub ON vl2.substation_mrid = far_sub.mrid
            WHERE far_sub.mrid IS NOT NULL AND far_sub.mrid != $1
            ORDER BY ol.ac_name
            LIMIT 200
            """,
            mrid,
        )
    return {
        "substation": dict(sub),
        "neighbours": [dict(r) for r in rows],
        "count": len(rows),
    }
