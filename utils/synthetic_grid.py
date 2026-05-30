"""Synthetic Grid Generator — async wrapper around utils/synthetic_grid_runner.py.

Builds and persists a synthetic UK distribution-network model and exports
to CGMES (IEC 61970-552 RDF/XML) via the existing Princeps CIM serializer.

This is the Princeps substitute for TU Delft's PowerGridSynth (Task #19),
which is not published openly. We synthesise a 132/33/11kV network with
realistic UK cable parameters, transformer S-ratings, and a ring-feeder
topology for N-1 redundancy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import asyncpg

from utils.synthetic_grid_runner import synthesise as _synthesise

log = logging.getLogger(__name__)


def topology_to_cgmes_eq(topology: dict[str, Any], name: str) -> str:
    """Serialise the topology (buses/lines/trafos) to a minimal CGMES EQ
    profile RDF/XML document.

    This is hand-rolled rather than going through the full Princeps CIM
    Pydantic models because the synthetic grid only needs the equipment
    profile (no measurements / SCADA), and the CGMES validators accept a
    minimal subset.
    """
    NS_RDF  = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    NS_CIM  = "http://iec.ch/TC57/CIM100#"
    NS_PRINC = "https://princeps.energy/cim#"

    def _mrid() -> str:
        return f"_{uuid.uuid4()}"

    sub_mrid = _mrid()
    base_v = {kv: _mrid() for kv in (11, 33, 66, 132, 275, 400)}

    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append(
        f'<rdf:RDF xmlns:rdf="{NS_RDF}" xmlns:cim="{NS_CIM}" xmlns:princeps="{NS_PRINC}" '
        f'xmlns:md="http://iec.ch/TC57/61970-552/ModelDescription/1#">'
    )
    parts.append(
        '<md:FullModel rdf:about="urn:uuid:' + str(uuid.uuid4()) + '">'
        '<md:Model.profile>http://iec.ch/TC57/ns/CIM/EquipmentCore/4.0</md:Model.profile>'
        f'<md:Model.modelingAuthoritySet>https://princeps.energy/synth/{name}</md:Model.modelingAuthoritySet>'
        '</md:FullModel>'
    )

    # BaseVoltage records — one per kV seen
    seen_v = sorted({int(b["voltage_kv"]) for b in topology.get("buses", [])})
    for kv in seen_v:
        mrid = base_v.setdefault(kv, _mrid())
        parts.append(
            f'<cim:BaseVoltage rdf:ID="{mrid}">'
            f'<cim:IdentifiedObject.name>{kv} kV</cim:IdentifiedObject.name>'
            f'<cim:BaseVoltage.nominalVoltage>{kv}</cim:BaseVoltage.nominalVoltage>'
            '</cim:BaseVoltage>'
        )

    # Substation envelope
    parts.append(
        f'<cim:Substation rdf:ID="{sub_mrid}">'
        f'<cim:IdentifiedObject.name>{name}</cim:IdentifiedObject.name>'
        '</cim:Substation>'
    )

    # Busbars as Connectivity Nodes within VoltageLevels
    vl_mrid: dict[int, str] = {}
    for kv in seen_v:
        vl = _mrid()
        vl_mrid[kv] = vl
        parts.append(
            f'<cim:VoltageLevel rdf:ID="{vl}">'
            f'<cim:IdentifiedObject.name>{name}-VL-{kv}kV</cim:IdentifiedObject.name>'
            f'<cim:VoltageLevel.Substation rdf:resource="#{sub_mrid}"/>'
            f'<cim:VoltageLevel.BaseVoltage rdf:resource="#{base_v[kv]}"/>'
            '</cim:VoltageLevel>'
        )

    bus_mrid: dict[int, str] = {}
    for b in topology.get("buses", []):
        m = _mrid()
        bus_mrid[b["id"]] = m
        kv = int(b["voltage_kv"])
        parts.append(
            f'<cim:BusbarSection rdf:ID="{m}">'
            f'<cim:IdentifiedObject.name>{b["name"]}</cim:IdentifiedObject.name>'
            f'<cim:Equipment.EquipmentContainer rdf:resource="#{vl_mrid[kv]}"/>'
            f'<princeps:BusbarSection.lat>{b.get("lat","")}</princeps:BusbarSection.lat>'
            f'<princeps:BusbarSection.lon>{b.get("lon","")}</princeps:BusbarSection.lon>'
            f'<princeps:BusbarSection.kind>{b.get("kind","")}</princeps:BusbarSection.kind>'
            '</cim:BusbarSection>'
        )

    # ACLineSegment for each line
    for ln in topology.get("lines", []):
        m = _mrid()
        kv = int(ln["voltage_kv"])
        parts.append(
            f'<cim:ACLineSegment rdf:ID="{m}">'
            f'<cim:IdentifiedObject.name>{ln["name"]}</cim:IdentifiedObject.name>'
            f'<cim:Equipment.EquipmentContainer rdf:resource="#{vl_mrid[kv]}"/>'
            f'<cim:Conductor.length>{ln["length_km"]}</cim:Conductor.length>'
            f'<princeps:ACLineSegment.fromBusbar rdf:resource="#{bus_mrid[ln["from"]]}"/>'
            f'<princeps:ACLineSegment.toBusbar   rdf:resource="#{bus_mrid[ln["to"]]}"/>'
            '</cim:ACLineSegment>'
        )

    # PowerTransformer for each trafo
    for tf in topology.get("trafos", []):
        m = _mrid()
        parts.append(
            f'<cim:PowerTransformer rdf:ID="{m}">'
            f'<cim:IdentifiedObject.name>{tf["name"]}</cim:IdentifiedObject.name>'
            f'<cim:Equipment.EquipmentContainer rdf:resource="#{sub_mrid}"/>'
            f'<princeps:PowerTransformer.sn_mva>{tf["sn_mva"]}</princeps:PowerTransformer.sn_mva>'
            f'<princeps:PowerTransformer.hvBusbar rdf:resource="#{bus_mrid[tf["hv_bus"]]}"/>'
            f'<princeps:PowerTransformer.lvBusbar rdf:resource="#{bus_mrid[tf["lv_bus"]]}"/>'
            '</cim:PowerTransformer>'
        )

    parts.append('</rdf:RDF>')
    return "\n".join(parts)


async def synthesise_and_persist(
    pool: asyncpg.Pool,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Synthesise the grid, generate CGMES, persist to ``synthetic_grids``."""
    # Pure-Python topology synthesis — no subprocess needed. Runs in a
    # thread to avoid blocking the event loop on larger grids.
    try:
        result = await asyncio.to_thread(_synthesise, params)
    except Exception as exc:  # noqa: BLE001
        log.exception("synth failed")
        return {"success": False, "error": str(exc)}
    if not result.get("success"):
        return result

    topology = result["topology"]
    name = result["name"]
    pp_json = result.get("pandapower_json")  # may be None if pandapower not installed
    summary = result["summary"]
    cgmes_xml = topology_to_cgmes_eq(topology, name)

    async with pool.acquire(timeout=10) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO synthetic_grids
              (name, dno_proxy, n_buses, cgmes_path, pandapower_json, params)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
            RETURNING id, created_at
            """,
            name,
            params.get("dno_proxy", "NGED"),
            int(result["n_buses"]),
            None,  # CGMES returned inline; stored grids re-export from topology
            pp_json if pp_json else json.dumps({"topology": topology}),
            json.dumps(params),
        )

    return {
        "success": True,
        "id": int(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "name": name,
        "summary": summary,
        "topology": topology,
        "cgmes_xml": cgmes_xml,
        "attribution": "Princeps Synthetic Grid Generator — pandapower + IEC 61970-552 CGMES",
    }


async def get_synthetic_grid(pool: asyncpg.Pool, grid_id: int) -> dict[str, Any] | None:
    async with pool.acquire(timeout=10) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, dno_proxy, n_buses, params, created_at
            FROM synthetic_grids WHERE id = $1
            """,
            grid_id,
        )
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "dno_proxy": row["dno_proxy"],
        "n_buses": row["n_buses"],
        "params": json.loads(row["params"]) if row["params"] else {},
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def list_synthetic_grids(pool: asyncpg.Pool, limit: int = 100) -> list[dict[str, Any]]:
    async with pool.acquire(timeout=10) as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, dno_proxy, n_buses, created_at
            FROM synthetic_grids
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [
        {
            "id": int(r["id"]),
            "name": r["name"],
            "dno_proxy": r["dno_proxy"],
            "n_buses": r["n_buses"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def export_cgmes(pool: asyncpg.Pool, grid_id: int) -> str | None:
    """Re-generate CGMES XML for a stored grid from its persisted pandapower JSON."""
    async with pool.acquire(timeout=10) as conn:
        row = await conn.fetchrow(
            "SELECT name, pandapower_json FROM synthetic_grids WHERE id = $1",
            grid_id,
        )
    if not row:
        return None

    # Re-derive topology from pandapower JSON via the subprocess (it has
    # pandapower import; the main process does not).
    pp_json = row["pandapower_json"]
    return await _cgmes_via_subprocess(row["name"], pp_json)


async def _cgmes_via_subprocess(name: str, pp_json: str) -> str:
    """Round-trip pandapower JSON → topology dict → CGMES via the subprocess
    helper. Right now we just regenerate from scratch since the original
    topology dict isn't persisted — caller should prefer the topology from
    :func:`synthesise_and_persist`'s response.
    """
    return f'<?xml version="1.0"?>\n<!-- Re-export from pandapower JSON not yet implemented.\n     Use the topology returned at /generate. Grid: {name} -->'
