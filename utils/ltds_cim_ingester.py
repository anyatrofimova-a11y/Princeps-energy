"""
NGED LTDS CIM ingester — parses IEC 61970 Stage 1.3 EQ profile XML.

Handles the full entity set:
  - Substations, voltage levels, base voltages, sub-regions
  - Power transformers + ends + tap changers
  - AC line segments (+ parent Line containers)
  - Busbar sections
  - Breakers, disconnectors, load break switches
  - Connectivity nodes, terminals
  - EnergyConsumer loads
  - EquivalentInjection network interfaces
  - GeneratingUnit, PhotoVoltaicUnit, BatteryUnit, HydroGeneratingUnit
  - OperationalLimit (seasonal ratings)

Handles cross-boundary dedup (Lea Marston EMIDS assets appear in WMIDS file,
etc.) per the NGED Stage 1.3 supplementary publication notes.

Fuzzy-matches substations to the existing grid_substations table for
coordinates until the GL profile publication lands.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import iterparse

import asyncpg

log = logging.getLogger("princeps.ltds_cim")

_SCHEMA_PATH = Path(__file__).parent / "ltds_cim_schema.sql"

# Namespaces used in NGED LTDS CIM RDF/XML
NS = {
    "rdf":  "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}",
    "cim":  "{http://iec.ch/TC57/CIM100#}",
    "eu":   "{http://iec.ch/TC57/CIM100-European#}",
    "nc":   "{https://cim4.eu/ns/nc#}",
    "md":   "{http://iec.ch/TC57/61970-552/ModelDescription/1#}",
    "gb":   "{http://ofgem.gov.uk/ns/CIM/LTDS/Extensions#}",
}

# Element tags we care about — listed by local name and CIM prefix
_WANTED_TAGS = {
    f"{NS['cim']}BaseVoltage",
    f"{NS['cim']}PSRType",
    f"{NS['cim']}GeographicalRegion",
    f"{NS['cim']}SubGeographicalRegion",
    f"{NS['cim']}Substation",
    f"{NS['cim']}VoltageLevel",
    f"{NS['cim']}ConnectivityNode",
    f"{NS['cim']}Terminal",
    f"{NS['cim']}BusbarSection",
    f"{NS['cim']}ACLineSegment",
    f"{NS['cim']}Line",
    f"{NS['cim']}PowerTransformer",
    f"{NS['cim']}PowerTransformerEnd",
    f"{NS['cim']}RatioTapChanger",
    f"{NS['cim']}Breaker",
    f"{NS['cim']}Disconnector",
    f"{NS['cim']}LoadBreakSwitch",
    f"{NS['cim']}EnergyConsumer",
    f"{NS['cim']}EquivalentInjection",
    f"{NS['cim']}GeneratingUnit",
    f"{NS['cim']}PhotoVoltaicUnit",
    f"{NS['cim']}BatteryUnit",
    f"{NS['cim']}HydroGeneratingUnit",
    f"{NS['cim']}AsynchronousMachine",
    f"{NS['cim']}SynchronousMachine",
    f"{NS['cim']}OperationalLimit",
    f"{NS['cim']}CurrentLimit",
    f"{NS['cim']}ApparentPowerLimit",
    f"{NS['md']}FullModel",
}


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Create the LTDS CIM tables idempotently."""
    async with pool.acquire() as conn:
        sql = _SCHEMA_PATH.read_text()
        clean = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
        for stmt in clean.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("ltds_cim schema ready")


# ────────────────────────────────────────────────────────────────────────
# Substation number CSV
# ────────────────────────────────────────────────────────────────────────

async def ingest_substation_numbers(pool: asyncpg.Pool, csv_path: Path) -> int:
    """Load the NGED ltds-cim-substation-numbers CSV reference table."""
    if not csv_path.exists():
        log.warning("substation numbers CSV missing: %s", csv_path)
        return 0
    text = csv_path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = [
        (r["Substation Number"], r["LTDS Substation Name"], r["Substation Type"])
        for r in reader if r.get("Substation Number")
    ]
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE ltds_substation_numbers")
        await conn.executemany(
            "INSERT INTO ltds_substation_numbers (substation_number, ltds_substation_name, substation_type) "
            "VALUES ($1, $2, $3) ON CONFLICT (substation_number) DO NOTHING",
            rows,
        )
    log.info("loaded %d substation numbers", len(rows))
    return len(rows)


# ────────────────────────────────────────────────────────────────────────
# CIM RDF/XML streaming parser
# ────────────────────────────────────────────────────────────────────────

def _mrid_from_ref(attr: dict) -> str | None:
    """Extract an mRID from an rdf:resource or rdf:ID attribute."""
    res = attr.get(f"{NS['rdf']}resource") or attr.get(f"{NS['rdf']}ID")
    if not res:
        return None
    if res.startswith("#"):
        res = res[1:]
    if res.startswith("_"):
        res = res[1:]
    return res


def _first_text(elem, local: str, ns: str = "cim") -> str | None:
    """Return the text of the first child matching {ns}local."""
    child = elem.find(f"{NS[ns]}{local}")
    return child.text if child is not None and child.text else None


def _first_ref(elem, local: str, ns: str = "cim") -> str | None:
    """Return the mRID from the first child's rdf:resource."""
    child = elem.find(f"{NS[ns]}{local}")
    if child is None:
        return None
    return _mrid_from_ref(child.attrib)


def _elem_id(elem) -> str | None:
    """Pull the element's own rdf:ID (or mRID child if present)."""
    rid = elem.attrib.get(f"{NS['rdf']}ID")
    if rid:
        return rid.lstrip("_#")
    return _first_text(elem, "IdentifiedObject.mRID")


def _elem_name(elem) -> str | None:
    return _first_text(elem, "IdentifiedObject.name")


def _parse_xml_stream(path: Path):
    """Yield (tag, elem) tuples for wanted CIM elements, clearing memory as we go."""
    for event, elem in iterparse(str(path), events=("end",)):
        if elem.tag in _WANTED_TAGS:
            yield elem.tag, elem
            elem.clear()


# ────────────────────────────────────────────────────────────────────────
# Main region ingest
# ────────────────────────────────────────────────────────────────────────

LICENCE_AREA_BY_TAG = {
    "EMIDS":   "East Midlands",
    "WMIDS":   "West Midlands",
    "SWEST":   "South West",
    "SWALES":  "South Wales",
}


async def ingest_region_file(pool: asyncpg.Pool, path: Path) -> dict:
    """Parse one NGED LTDS EQ XML file and persist every entity."""
    if not path.exists():
        return {"ok": False, "reason": f"missing file {path}"}

    # Infer licence area from filename (LTDS_EMIDS_...)
    m = re.search(r"LTDS_([A-Z]+)_", path.name)
    licence_area_code = m.group(1) if m else "UNKNOWN"
    licence_area = LICENCE_AREA_BY_TAG.get(licence_area_code, licence_area_code)

    # Accumulators
    model_row: dict | None = None
    sub_regions: dict[str, dict] = {}
    regions: dict[str, dict] = {}
    psr_types: dict[str, dict] = {}
    base_voltages: dict[str, dict] = {}
    substations: dict[str, dict] = {}
    voltage_levels: dict[str, dict] = {}
    connectivity_nodes: dict[str, dict] = {}
    terminals: dict[str, dict] = {}
    busbars: dict[str, dict] = {}
    ac_lines: dict[str, dict] = {}
    lines: dict[str, dict] = {}
    transformers: dict[str, dict] = {}
    transformer_ends: dict[str, dict] = {}
    tap_changers: dict[str, dict] = {}
    switches: dict[str, dict] = {}
    loads: dict[str, dict] = {}
    equivalent_injections: dict[str, dict] = {}
    generators: dict[str, dict] = {}
    op_limits: dict[str, dict] = {}

    # Regex to get numeric attrs from CIM strings
    def _num(elem, local, ns="cim") -> float | None:
        t = _first_text(elem, local, ns)
        try:
            return float(t) if t else None
        except (TypeError, ValueError):
            return None

    for tag, elem in _parse_xml_stream(path):
        local = tag.split("}", 1)[-1]
        eid = _elem_id(elem)
        if not eid and local != "FullModel":
            continue

        if local == "FullModel":
            model_mrid = elem.attrib.get(f"{NS['rdf']}about", "").replace("urn:uuid:", "")
            def _dt(s):
                if not s:
                    return None
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except Exception:
                    return None
            model_row = {
                "mrid": model_mrid,
                "dno": "NGED",
                "licence_area": licence_area,
                "profile": _first_text(elem, "Model.profile", ns="md"),
                "created": _dt(_first_text(elem, "Model.created", ns="md")),
                "scenario_time": _dt(_first_text(elem, "Model.scenarioTime", ns="md")),
                "version": _first_text(elem, "Model.version", ns="md"),
                "description": _first_text(elem, "Model.description", ns="md"),
                "source_file": path.name,
            }
            continue

        if local == "BaseVoltage":
            base_voltages[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "nominal_voltage_kv": _num(elem, "BaseVoltage.nominalVoltage"),
            }
        elif local == "PSRType":
            psr_types[eid] = {"mrid": eid, "name": _elem_name(elem)}
        elif local == "GeographicalRegion":
            regions[eid] = {"mrid": eid, "name": _elem_name(elem)}
        elif local == "SubGeographicalRegion":
            sub_regions[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "region_mrid": _first_ref(elem, "SubGeographicalRegion.Region"),
            }
        elif local == "Substation":
            substations[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "dno": "NGED",
                "licence_area": licence_area,
                "psr_type": _first_ref(elem, "PowerSystemResource.PSRType"),
                "sub_region_mrid": _first_ref(elem, "Substation.Region"),
            }
        elif local == "VoltageLevel":
            voltage_levels[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "base_voltage_mrid": _first_ref(elem, "VoltageLevel.BaseVoltage"),
                "substation_mrid": _first_ref(elem, "VoltageLevel.Substation"),
            }
        elif local == "ConnectivityNode":
            connectivity_nodes[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "container_mrid": _first_ref(elem, "ConnectivityNode.ConnectivityNodeContainer"),
            }
        elif local == "Terminal":
            terminals[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "sequence_number": int(_first_text(elem, "ACDCTerminal.sequenceNumber") or 0) if _first_text(elem, "ACDCTerminal.sequenceNumber") else None,
                "conducting_eq_mrid": _first_ref(elem, "Terminal.ConductingEquipment"),
                "connectivity_mrid": _first_ref(elem, "Terminal.ConnectivityNode"),
            }
        elif local == "BusbarSection":
            busbars[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "voltage_level_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
            }
        elif local == "ACLineSegment":
            ac_lines[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "length_km": _num(elem, "Conductor.length"),
                "r_ohm": _num(elem, "ACLineSegment.r"),
                "x_ohm": _num(elem, "ACLineSegment.x"),
                "b_siemens": _num(elem, "ACLineSegment.bch"),
                "g_siemens": _num(elem, "ACLineSegment.gch"),
                "base_voltage_mrid": _first_ref(elem, "ConductingEquipment.BaseVoltage"),
                "line_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
            }
        elif local == "Line":
            lines[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "sub_region_mrid": _first_ref(elem, "Line.Region"),
            }
        elif local == "PowerTransformer":
            transformers[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "substation_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
            }
        elif local == "PowerTransformerEnd":
            transformer_ends[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "end_number": int(_first_text(elem, "TransformerEnd.endNumber") or 0) if _first_text(elem, "TransformerEnd.endNumber") else None,
                "transformer_mrid": _first_ref(elem, "PowerTransformerEnd.PowerTransformer"),
                "base_voltage_mrid": _first_ref(elem, "TransformerEnd.BaseVoltage"),
                "rated_u_kv": _num(elem, "PowerTransformerEnd.ratedU"),
                "rated_s_mva": _num(elem, "PowerTransformerEnd.ratedS"),
                "r_ohm": _num(elem, "PowerTransformerEnd.r"),
                "x_ohm": _num(elem, "PowerTransformerEnd.x"),
                "terminal_mrid": _first_ref(elem, "TransformerEnd.Terminal"),
            }
        elif local == "RatioTapChanger":
            tap_changers[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "transformer_end_mrid": _first_ref(elem, "RatioTapChanger.TransformerEnd"),
                "low_step": int(_first_text(elem, "TapChanger.lowStep") or 0) if _first_text(elem, "TapChanger.lowStep") else None,
                "high_step": int(_first_text(elem, "TapChanger.highStep") or 0) if _first_text(elem, "TapChanger.highStep") else None,
                "neutral_step": int(_first_text(elem, "TapChanger.neutralStep") or 0) if _first_text(elem, "TapChanger.neutralStep") else None,
                "step_voltage_increment_pct": _num(elem, "RatioTapChanger.stepVoltageIncrement"),
            }
        elif local in ("Breaker", "Disconnector", "LoadBreakSwitch"):
            switches[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "switch_type": local,
                "normal_open": (_first_text(elem, "Switch.normalOpen") or "false").lower() == "true",
                "voltage_level_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
            }
        elif local == "EnergyConsumer":
            loads[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "voltage_level_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
                "p_fixed_mw": _num(elem, "EnergyConsumer.pfixed"),
                "q_fixed_mvar": _num(elem, "EnergyConsumer.qfixed"),
            }
        elif local == "EquivalentInjection":
            equivalent_injections[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "voltage_level_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
                "p_mw": _num(elem, "EquivalentInjection.p"),
                "q_mvar": _num(elem, "EquivalentInjection.q"),
            }
        elif local in ("GeneratingUnit", "PhotoVoltaicUnit", "BatteryUnit",
                       "HydroGeneratingUnit", "AsynchronousMachine", "SynchronousMachine"):
            generators[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "gen_type": local,
                "substation_mrid": None,
                "voltage_level_mrid": _first_ref(elem, "Equipment.EquipmentContainer"),
                "rated_mva": _num(elem, "RotatingMachine.ratedS"),
                "min_mw": _num(elem, "GeneratingUnit.minOperatingP"),
                "max_mw": _num(elem, "GeneratingUnit.maxOperatingP"),
            }
        elif local in ("OperationalLimit", "CurrentLimit", "ApparentPowerLimit"):
            op_limits[eid] = {
                "mrid": eid,
                "name": _elem_name(elem),
                "limit_set_mrid": _first_ref(elem, "OperationalLimit.OperationalLimitSet"),
                "limit_type": local,
                "value_numeric": _num(elem, "CurrentLimit.value") or _num(elem, "ApparentPowerLimit.value"),
                "season": None,
            }

    summary: dict[str, Any] = {
        "ok": True,
        "licence_area": licence_area,
        "source_file": path.name,
        "counts": {
            "substations": len(substations),
            "voltage_levels": len(voltage_levels),
            "base_voltages": len(base_voltages),
            "transformers": len(transformers),
            "transformer_ends": len(transformer_ends),
            "tap_changers": len(tap_changers),
            "ac_lines": len(ac_lines),
            "lines": len(lines),
            "busbars": len(busbars),
            "connectivity_nodes": len(connectivity_nodes),
            "terminals": len(terminals),
            "switches": len(switches),
            "loads": len(loads),
            "equivalent_injections": len(equivalent_injections),
            "generators": len(generators),
            "op_limits": len(op_limits),
        },
    }

    # Persist — one big transaction per file
    async with pool.acquire() as conn:
        async with conn.transaction():
            if model_row:
                await conn.execute(
                    """
                    INSERT INTO ltds_models (model_mrid, dno, licence_area, profile,
                        created, scenario_time, version, description, source_file)
                    VALUES ($1, $2, $3, $4, $5::timestamptz, $6::timestamptz, $7, $8, $9)
                    ON CONFLICT (model_mrid) DO UPDATE SET
                        profile = EXCLUDED.profile,
                        created = EXCLUDED.created,
                        scenario_time = EXCLUDED.scenario_time,
                        version = EXCLUDED.version,
                        description = EXCLUDED.description,
                        source_file = EXCLUDED.source_file,
                        ingested_at = now()
                    """,
                    model_row["mrid"], model_row["dno"], model_row["licence_area"],
                    model_row["profile"], model_row["created"], model_row["scenario_time"],
                    model_row["version"], model_row["description"], model_row["source_file"],
                )

            model_mrid = model_row["mrid"] if model_row else None

            async def many(sql, rows):
                if rows:
                    await conn.executemany(sql, rows)

            await many(
                "INSERT INTO ltds_base_voltages (mrid, name, nominal_voltage_kv, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["nominal_voltage_kv"], model_mrid) for r in base_voltages.values()],
            )
            await many(
                "INSERT INTO ltds_psr_types (mrid, name, model_mrid) VALUES ($1, $2, $3) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], model_mrid) for r in psr_types.values()],
            )
            await many(
                "INSERT INTO ltds_geographical_regions (mrid, name, model_mrid) "
                "VALUES ($1, $2, $3) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], model_mrid) for r in regions.values()],
            )
            await many(
                "INSERT INTO ltds_sub_regions (mrid, name, region_mrid, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["region_mrid"], model_mrid) for r in sub_regions.values()],
            )

            # Substations — resolve the psr_type to its human name via psr_types dict
            sub_rows = []
            for s in substations.values():
                psr_name = psr_types.get(s["psr_type"], {}).get("name") if s.get("psr_type") else None
                sub_rows.append((
                    s["mrid"], s["name"], s["dno"], s["licence_area"],
                    psr_name, s["sub_region_mrid"], model_mrid,
                ))
            await many(
                "INSERT INTO ltds_substations (mrid, name, dno, licence_area, psr_type, "
                "sub_region_mrid, model_mrid) VALUES ($1, $2, $3, $4, $5, $6, $7) "
                "ON CONFLICT (mrid) DO UPDATE SET name = EXCLUDED.name, psr_type = EXCLUDED.psr_type",
                sub_rows,
            )

            # Voltage levels — resolve nominal voltage via base_voltages dict
            vl_rows = []
            for v in voltage_levels.values():
                nominal = base_voltages.get(v["base_voltage_mrid"], {}).get("nominal_voltage_kv") if v.get("base_voltage_mrid") else None
                vl_rows.append((
                    v["mrid"], v["name"], v["base_voltage_mrid"], v["substation_mrid"],
                    nominal, model_mrid,
                ))
            await many(
                "INSERT INTO ltds_voltage_levels (mrid, name, base_voltage_mrid, substation_mrid, "
                "nominal_voltage_kv, model_mrid) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (mrid) DO NOTHING",
                vl_rows,
            )

            await many(
                "INSERT INTO ltds_connectivity_nodes (mrid, name, container_mrid, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["container_mrid"], model_mrid) for r in connectivity_nodes.values()],
            )
            await many(
                "INSERT INTO ltds_terminals (mrid, name, sequence_number, conducting_eq_mrid, "
                "connectivity_mrid, model_mrid) VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["sequence_number"], r["conducting_eq_mrid"], r["connectivity_mrid"], model_mrid) for r in terminals.values()],
            )
            await many(
                "INSERT INTO ltds_busbars (mrid, name, voltage_level_mrid, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["voltage_level_mrid"], model_mrid) for r in busbars.values()],
            )
            await many(
                "INSERT INTO ltds_lines (mrid, name, sub_region_mrid, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["sub_region_mrid"], model_mrid) for r in lines.values()],
            )
            await many(
                "INSERT INTO ltds_ac_lines (mrid, name, length_km, r_ohm, x_ohm, b_siemens, g_siemens, "
                "base_voltage_mrid, line_mrid, model_mrid) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
                "ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["length_km"], r["r_ohm"], r["x_ohm"], r["b_siemens"], r["g_siemens"], r["base_voltage_mrid"], r["line_mrid"], model_mrid) for r in ac_lines.values()],
            )
            await many(
                "INSERT INTO ltds_power_transformers (mrid, name, substation_mrid, model_mrid) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["substation_mrid"], model_mrid) for r in transformers.values()],
            )
            await many(
                "INSERT INTO ltds_transformer_ends (mrid, name, end_number, transformer_mrid, "
                "base_voltage_mrid, rated_u_kv, rated_s_mva, r_ohm, x_ohm, terminal_mrid, model_mrid) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["end_number"], r["transformer_mrid"], r["base_voltage_mrid"], r["rated_u_kv"], r["rated_s_mva"], r["r_ohm"], r["x_ohm"], r["terminal_mrid"], model_mrid) for r in transformer_ends.values()],
            )
            await many(
                "INSERT INTO ltds_tap_changers (mrid, name, transformer_end_mrid, low_step, high_step, "
                "neutral_step, step_voltage_increment_pct, model_mrid) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                "ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["transformer_end_mrid"], r["low_step"], r["high_step"], r["neutral_step"], r["step_voltage_increment_pct"], model_mrid) for r in tap_changers.values()],
            )
            await many(
                "INSERT INTO ltds_switches (mrid, name, switch_type, normal_open, voltage_level_mrid, model_mrid) "
                "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["switch_type"], r["normal_open"], r["voltage_level_mrid"], model_mrid) for r in switches.values()],
            )
            await many(
                "INSERT INTO ltds_loads (mrid, name, voltage_level_mrid, p_fixed_mw, q_fixed_mvar, model_mrid) "
                "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["voltage_level_mrid"], r["p_fixed_mw"], r["q_fixed_mvar"], model_mrid) for r in loads.values()],
            )
            await many(
                "INSERT INTO ltds_equivalent_injections (mrid, name, voltage_level_mrid, p_mw, q_mvar, model_mrid) "
                "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["voltage_level_mrid"], r["p_mw"], r["q_mvar"], model_mrid) for r in equivalent_injections.values()],
            )
            await many(
                "INSERT INTO ltds_generators (mrid, name, gen_type, substation_mrid, voltage_level_mrid, "
                "rated_mva, min_mw, max_mw, model_mrid) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
                "ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["gen_type"], r["substation_mrid"], r["voltage_level_mrid"], r["rated_mva"], r["min_mw"], r["max_mw"], model_mrid) for r in generators.values()],
            )
            await many(
                "INSERT INTO ltds_operational_limits (mrid, name, limit_set_mrid, limit_type, value_numeric, model_mrid) "
                "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (mrid) DO NOTHING",
                [(r["mrid"], r["name"], r["limit_set_mrid"], r["limit_type"], r["value_numeric"], model_mrid) for r in op_limits.values()],
            )
    return summary


# ────────────────────────────────────────────────────────────────────────
# Orchestrator — ingest all 4 regions + substation numbers CSV, then match
# coordinates by fuzzy-name against existing grid_substations.
# ────────────────────────────────────────────────────────────────────────

async def ingest_all(
    pool: asyncpg.Pool,
    download_dir: Path = Path("/Users/anyatrofimova/Downloads"),
) -> dict:
    """Ingest every LTDS CIM XML file found in the download dir, then match coordinates."""
    await ensure_schema(pool)

    # 1. Substation number reference CSV
    csv_path = download_dir / "ltds-cim-substation-numbers.csv"
    csv_count = await ingest_substation_numbers(pool, csv_path)

    # 2. All LTDS_*_EQ_*.xml files
    xml_files = sorted(download_dir.glob("LTDS_*_EQ_*.xml"))
    per_region: list[dict] = []
    for path in xml_files:
        try:
            result = await ingest_region_file(pool, path)
            per_region.append(result)
        except Exception as e:
            log.exception("ingest %s failed", path.name)
            per_region.append({"ok": False, "source_file": path.name, "reason": str(e)})

    # 3. Substation number join → update ltds_substations.substation_number
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE ltds_substations cs
            SET substation_number = csn.substation_number
            FROM ltds_substation_numbers csn
            WHERE cs.substation_number IS NULL
              AND LOWER(cs.name) = LOWER(csn.ltds_substation_name)
            """
        )
        matched_numbers = await conn.fetchval(
            "SELECT COUNT(*) FROM ltds_substations WHERE substation_number IS NOT NULL"
        )

    # 4. Fuzzy match to grid_substations for coordinates
    coord_matched = await match_coordinates_fuzzy(pool)

    # 4b. Promote matched LTDS substations into grid_substations so the
    # grid_line_linker has transmission-level endpoints to snap against.
    promote_result = await promote_ltds_to_grid_substations(pool)

    # 5. Aggregate stats
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM ltds_models) AS models,
                (SELECT COUNT(*) FROM ltds_substations) AS substations,
                (SELECT COUNT(*) FROM ltds_voltage_levels) AS voltage_levels,
                (SELECT COUNT(*) FROM ltds_power_transformers) AS transformers,
                (SELECT COUNT(*) FROM ltds_ac_lines) AS ac_lines,
                (SELECT COUNT(*) FROM ltds_busbars) AS busbars,
                (SELECT COUNT(*) FROM ltds_switches) AS switches,
                (SELECT COUNT(*) FROM ltds_loads) AS loads,
                (SELECT COUNT(*) FROM ltds_generators) AS generators,
                (SELECT COUNT(*) FROM ltds_connectivity_nodes) AS nodes,
                (SELECT COUNT(*) FROM ltds_terminals) AS terminals
            """
        )
    return {
        "ok": True,
        "csv_substation_numbers": csv_count,
        "per_region": per_region,
        "substation_number_matches": int(matched_numbers or 0),
        "coordinate_matches": coord_matched,
        "promoted_to_grid_substations": promote_result,
        "totals": dict(totals) if totals else {},
    }


# ────────────────────────────────────────────────────────────────────────
# Fuzzy coordinate match to grid_substations
# ────────────────────────────────────────────────────────────────────────

async def match_coordinates_fuzzy(pool: asyncpg.Pool) -> int:
    """Join ``ltds_substations`` → ``grid_substations`` to populate coordinates.

    Three match passes, evaluated in order (most precise first):

    1. **wpd_site code** — ``grid_substations.raw_data->>'ref:GB:wpd_site'``
       matches ``ltds_substations.substation_number``. This is the NGED
       open-data identifier; it's the authoritative join.
    2. **Normalised name (voltage-stripped)** — strip the trailing
       ``' 132/33kV'`` / ``' 33kV'`` pattern from LTDS names and the
       trailing ``' Substation'`` token from grid_substations names,
       then compare lowercased alphanumeric-only strings.
    3. **First-token match** — the original heuristic as a last-resort
       fallback (kept so we don't regress existing matches).

    Each pass updates only ``WHERE lat IS NULL`` so they compose cleanly.
    Returns the total number of rows updated across all three passes.
    """
    total = 0
    async with pool.acquire() as conn:
        # Pass 1 — wpd_site code (authoritative for NGED)
        result = await conn.execute(
            """
            UPDATE ltds_substations cs
            SET lat = gs.lat, lon = gs.lon, grid_substation_id = gs.id,
                geom = ST_SetSRID(ST_MakePoint(gs.lon, gs.lat), 4326)
            FROM (
                SELECT
                    id,
                    raw_data->>'ref:GB:wpd_site' AS wpd_site,
                    ST_X(ST_Transform(geom, 4326)) AS lon,
                    ST_Y(ST_Transform(geom, 4326)) AS lat
                FROM grid_substations
                WHERE geom IS NOT NULL
                  AND raw_data->>'ref:GB:wpd_site' IS NOT NULL
            ) gs
            WHERE cs.lat IS NULL
              AND cs.substation_number IS NOT NULL
              AND gs.wpd_site = cs.substation_number
            """
        )
        try:
            total += int(result.split()[-1])
        except Exception:
            pass

        # Pass 2 — voltage-stripped fuzzy name match
        result = await conn.execute(
            """
            UPDATE ltds_substations cs
            SET lat = gs.lat, lon = gs.lon, grid_substation_id = gs.id,
                geom = ST_SetSRID(ST_MakePoint(gs.lon, gs.lat), 4326)
            FROM (
                SELECT
                    id,
                    LOWER(REGEXP_REPLACE(
                        REGEXP_REPLACE(name, '\\s*substation\\s*$', '', 'i'),
                        '[^a-zA-Z0-9]', '', 'g'
                    )) AS norm,
                    ST_X(ST_Transform(geom, 4326)) AS lon,
                    ST_Y(ST_Transform(geom, 4326)) AS lat
                FROM grid_substations
                WHERE geom IS NOT NULL
            ) gs
            WHERE cs.lat IS NULL
              AND LOWER(REGEXP_REPLACE(
                    REGEXP_REPLACE(cs.name, '\\s+\\d+(\\.\\d+)?(/\\d+(\\.\\d+)?)*\\s*kv.*$', '', 'i'),
                    '[^a-zA-Z0-9]', '', 'g'
                  )) = gs.norm
              AND gs.norm <> ''
            """
        )
        try:
            total += int(result.split()[-1])
        except Exception:
            pass

        # Pass 3 — first-token fallback (the original heuristic)
        result = await conn.execute(
            """
            UPDATE ltds_substations cs
            SET lat = gs.lat, lon = gs.lon, grid_substation_id = gs.id,
                geom = ST_SetSRID(ST_MakePoint(gs.lon, gs.lat), 4326)
            FROM (
                SELECT
                    id,
                    ST_X(ST_Transform(geom, 4326)) AS lon,
                    ST_Y(ST_Transform(geom, 4326)) AS lat,
                    LOWER(REGEXP_REPLACE(name, '[^a-zA-Z0-9]', '', 'g')) AS norm_name
                FROM grid_substations
                WHERE geom IS NOT NULL
            ) gs
            WHERE cs.lat IS NULL
              AND LOWER(REGEXP_REPLACE(SPLIT_PART(cs.name, ' ', 1), '[^a-zA-Z0-9]', '', 'g')) = gs.norm_name
            """
        )
        try:
            total += int(result.split()[-1])
        except Exception:
            pass
    log.info("ltds_cim: match_coordinates_fuzzy -> %d rows updated", total)
    return total


# ────────────────────────────────────────────────────────────────────────
# Promote matched LTDS substations into grid_substations
# ────────────────────────────────────────────────────────────────────────

# Map CIM psr_type → voltage (kV) estimate, used only when the LTDS row
# doesn't already have an explicit voltage on its grid_substation match.
_PSR_DEFAULT_KV = {
    "GSP": 132.0,     # Grid Supply Point — always 132kV or higher
    "BSP": 33.0,      # Bulk Supply Point
    "Primary": 11.0,  # Primary substation
    "Grid": 132.0,
}


async def promote_ltds_to_grid_substations(pool: asyncpg.Pool) -> dict[str, int]:
    """Upsert located LTDS substations into ``grid_substations``.

    The linker needs real transmission-level endpoints (GSPs, BSPs) to snap
    lines against. OSM dominates ``grid_substations`` with 11kV distribution
    cabinets that never appear as endpoints on 132kV+ lines. LTDS already
    catalogues the right class of substation — once we've matched their
    coords via :func:`match_coordinates_fuzzy`, we can either:

      * re-use the matched ``grid_substation_id`` (no insert needed), or
      * insert an LTDS-only row for future matching.

    Strategy:
      * For each located LTDS row, UPSERT into ``grid_substations`` keyed on
        ``(external_id, dno)``. External id format: ``ltds:<mrid>``.
      * If the LTDS row was matched to an existing grid_substations row,
        we **don't** insert a duplicate — the existing row is already
        findable by the linker. We do refresh voltage + site_type if the
        existing row has NULL.
      * For unmatched LTDS rows (no coords), we skip — we can't place them.

    Returns a dict with ``inserted`` / ``updated`` counts.
    """
    inserted = 0
    updated = 0
    async with pool.acquire() as conn:
        # Insert fresh rows for LTDS substations that DON'T already point at
        # an existing grid_substations row but still have coords (e.g. when
        # a future GL profile lands these will have lat/lon but no match).
        rows = await conn.fetch(
            """
            SELECT mrid, name, dno, licence_area, psr_type, substation_number,
                   lat, lon, grid_substation_id,
                   (SELECT MAX(nominal_voltage_kv) FROM ltds_voltage_levels
                    WHERE substation_mrid = cs.mrid) AS max_kv
            FROM ltds_substations cs
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
        )
        for r in rows:
            ext_id = f"ltds:{r['mrid']}"
            voltage_kv = float(r["max_kv"]) if r["max_kv"] is not None else _PSR_DEFAULT_KV.get(r["psr_type"])
            dno = (r["dno"] or "").lower() or "ltds"

            if r["grid_substation_id"] is not None:
                # Existing row — only fill NULL voltage + site_type, and
                # only touch raw_data if the LTDS keys aren't present yet.
                # Skip entirely (no UPDATE, no updated_at bump) when the
                # target already carries the same LTDS mrid — keeps
                # re-runs a zero-work no-op.
                res = await conn.execute(
                    """
                    UPDATE grid_substations
                    SET voltage_kv = COALESCE(voltage_kv, $1),
                        site_type  = COALESCE(site_type,  $2),
                        raw_data   = raw_data || jsonb_build_object(
                            'ltds_mrid', $3::text,
                            'ltds_substation_number', $4::text,
                            'ltds_psr_type', $5::text,
                            'ltds_licence_area', $6::text,
                            'external_source', 'ltds_nged'
                        ),
                        updated_at = now()
                    WHERE id = $7
                      AND (raw_data->>'ltds_mrid' IS DISTINCT FROM $3::text
                           OR voltage_kv IS NULL
                           OR site_type  IS NULL)
                    """,
                    voltage_kv,
                    (r["psr_type"] or "").lower() or None,
                    r["mrid"], r["substation_number"], r["psr_type"],
                    r["licence_area"], r["grid_substation_id"],
                )
                try:
                    if int(res.split()[-1]) > 0:
                        updated += 1
                except Exception:
                    pass
                continue

            # New LTDS-origin row. We got here only if the LTDS row has
            # coordinates but they didn't match an existing grid_substations
            # row (e.g. future GL-profile-derived or an unrelated feed).
            import json
            raw = json.dumps({
                "source": "ltds_cim",
                "ltds_mrid": r["mrid"],
                "ltds_substation_number": r["substation_number"],
                "ltds_psr_type": r["psr_type"],
                "ltds_licence_area": r["licence_area"],
                "external_source": f"ltds_{dno}",
            })
            res = await conn.execute(
                """
                INSERT INTO grid_substations (
                    external_id, name, dno, region, voltage_kv, site_type,
                    geom, raw_data
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    ST_Transform(ST_SetSRID(ST_MakePoint($7, $8), 4326), 27700),
                    $9::jsonb
                )
                ON CONFLICT (external_id, dno) DO UPDATE SET
                    voltage_kv = COALESCE(grid_substations.voltage_kv, EXCLUDED.voltage_kv),
                    site_type  = COALESCE(grid_substations.site_type,  EXCLUDED.site_type),
                    raw_data   = grid_substations.raw_data || EXCLUDED.raw_data,
                    updated_at = now()
                RETURNING id
                """,
                ext_id, r["name"], dno, r["licence_area"], voltage_kv,
                (r["psr_type"] or "").lower() or None,
                float(r["lon"]), float(r["lat"]), raw,
            )
            try:
                # INSERT N or UPDATE N
                if "INSERT" in res:
                    inserted += 1
                else:
                    updated += 1
            except Exception:
                pass

            # Back-link the LTDS row to the new grid_substations id we just
            # created so subsequent runs don't re-insert.
            new_id = await conn.fetchval(
                "SELECT id FROM grid_substations WHERE external_id = $1 AND dno = $2",
                ext_id, dno,
            )
            if new_id:
                await conn.execute(
                    "UPDATE ltds_substations SET grid_substation_id = $1 WHERE mrid = $2",
                    new_id, r["mrid"],
                )
    log.info("ltds_cim: promote_ltds_to_grid_substations inserted=%d updated=%d",
             inserted, updated)
    return {"inserted": inserted, "updated": updated}


# ────────────────────────────────────────────────────────────────────────
# Read-side helpers for the Grid Graph frontend
# ────────────────────────────────────────────────────────────────────────

async def get_cim_stats(pool: asyncpg.Pool) -> dict:
    """Aggregate CIM stats for the Resources tab + Pulse header."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM ltds_models) AS models,
                (SELECT COUNT(*) FROM ltds_substations) AS substations,
                (SELECT COUNT(*) FROM ltds_substations WHERE lat IS NOT NULL) AS located_substations,
                (SELECT COUNT(*) FROM ltds_voltage_levels) AS voltage_levels,
                (SELECT COUNT(*) FROM ltds_power_transformers) AS transformers,
                (SELECT COUNT(*) FROM ltds_ac_lines) AS ac_lines,
                (SELECT COUNT(*) FROM ltds_busbars) AS busbars,
                (SELECT COUNT(*) FROM ltds_switches) AS switches,
                (SELECT COUNT(*) FROM ltds_loads) AS loads,
                (SELECT COUNT(*) FROM ltds_generators) AS generators,
                (SELECT COUNT(*) FROM ltds_connectivity_nodes) AS connectivity_nodes,
                (SELECT COUNT(*) FROM ltds_terminals) AS terminals
            """
        )
        by_psr = await conn.fetch(
            "SELECT psr_type, COUNT(*) AS n FROM ltds_substations "
            "GROUP BY psr_type ORDER BY n DESC"
        )
        by_area = await conn.fetch(
            "SELECT licence_area, COUNT(*) AS n FROM ltds_substations "
            "GROUP BY licence_area ORDER BY n DESC"
        )
    return {
        "totals": dict(row) if row else {},
        "by_psr_type": [dict(r) for r in by_psr],
        "by_licence_area": [dict(r) for r in by_area],
    }


async def list_substations(
    pool: asyncpg.Pool,
    licence_area: str | None = None,
    psr_type: str | None = None,
    limit: int = 20000,
) -> list[dict]:
    """Return a lightweight substation index for the left asset browser."""
    conditions = []
    params: list[Any] = []
    if licence_area:
        conditions.append(f"licence_area = ${len(params)+1}")
        params.append(licence_area)
    if psr_type:
        conditions.append(f"psr_type = ${len(params)+1}")
        params.append(psr_type)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT s.mrid, s.name, s.dno, s.licence_area, s.psr_type,
               s.substation_number, s.lat, s.lon,
               (SELECT COUNT(*) FROM ltds_voltage_levels WHERE substation_mrid = s.mrid) AS voltage_level_count,
               (SELECT COUNT(*) FROM ltds_power_transformers WHERE substation_mrid = s.mrid) AS transformer_count,
               (SELECT MAX(nominal_voltage_kv) FROM ltds_voltage_levels WHERE substation_mrid = s.mrid) AS max_voltage_kv
        FROM ltds_substations s
        {where}
        ORDER BY s.licence_area, s.name
        LIMIT ${len(params)+1}
    """
    params.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def get_substation_detail(pool: asyncpg.Pool, mrid: str) -> dict:
    """Return everything about a single substation for the right detail panel."""
    async with pool.acquire() as conn:
        sub = await conn.fetchrow("SELECT * FROM ltds_substations WHERE mrid = $1", mrid)
        if not sub:
            return {}
        vls = await conn.fetch(
            "SELECT mrid, name, nominal_voltage_kv FROM ltds_voltage_levels "
            "WHERE substation_mrid = $1 ORDER BY nominal_voltage_kv DESC",
            mrid,
        )
        tfs = await conn.fetch(
            "SELECT mrid, name FROM ltds_power_transformers WHERE substation_mrid = $1",
            mrid,
        )
        tf_ends = await conn.fetch(
            """
            SELECT te.mrid, te.name, te.end_number, te.rated_u_kv, te.rated_s_mva, te.transformer_mrid
            FROM ltds_transformer_ends te
            WHERE te.transformer_mrid IN (
                SELECT mrid FROM ltds_power_transformers WHERE substation_mrid = $1
            )
            ORDER BY te.end_number
            """,
            mrid,
        )
        busbar_count = await conn.fetchval(
            "SELECT COUNT(*) FROM ltds_busbars WHERE voltage_level_mrid IN "
            "(SELECT mrid FROM ltds_voltage_levels WHERE substation_mrid = $1)",
            mrid,
        ) or 0
        switch_count = await conn.fetchval(
            "SELECT COUNT(*) FROM ltds_switches WHERE voltage_level_mrid IN "
            "(SELECT mrid FROM ltds_voltage_levels WHERE substation_mrid = $1)",
            mrid,
        ) or 0
        load_count = await conn.fetchval(
            "SELECT COUNT(*) FROM ltds_loads WHERE voltage_level_mrid IN "
            "(SELECT mrid FROM ltds_voltage_levels WHERE substation_mrid = $1)",
            mrid,
        ) or 0

    return {
        "substation": dict(sub),
        "voltage_levels": [dict(r) for r in vls],
        "transformers": [dict(r) for r in tfs],
        "transformer_ends": [dict(r) for r in tf_ends],
        "busbar_count": int(busbar_count),
        "switch_count": int(switch_count),
        "load_count": int(load_count),
    }


async def get_substations_geojson(pool: asyncpg.Pool) -> dict:
    """Return the located substations as GeoJSON for the Map sub-view."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT mrid, name, dno, licence_area, psr_type, substation_number,
                   lat, lon,
                   (SELECT MAX(nominal_voltage_kv) FROM ltds_voltage_levels WHERE substation_mrid = cs.mrid) AS max_voltage_kv
            FROM ltds_substations cs
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
        )
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "mrid": r["mrid"],
                "name": r["name"],
                "dno": r["dno"],
                "licence_area": r["licence_area"],
                "psr_type": r["psr_type"],
                "substation_number": r["substation_number"],
                "max_voltage_kv": float(r["max_voltage_kv"]) if r["max_voltage_kv"] else None,
                "colour": _psr_colour(r["psr_type"]),
            },
        })
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


def _psr_colour(psr: str | None) -> str:
    """Colour map for PSR types."""
    p = (psr or "").lower()
    if "gsp" in p:        return "#c0392b"   # Grid Supply Point — red
    if "bsp" in p:        return "#e67e22"   # Bulk Supply Point — orange
    if "primary" in p:    return "#2980b9"   # Primary substation — blue
    if "distribution" in p: return "#16a34a"
    return "#64748b"
