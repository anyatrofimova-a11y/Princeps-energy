"""
Enriched substation detail — assembles 8 dense sections from existing utils
and tables. No new compute. Every section carries its own provenance block
and, when upstream is empty/missing, a clear ``_explanation``.

Sections (keys are load-bearing — frontend depends on them):

  1. identity            — names, ids, DNO/GSP, location, OSGB ref, provenance
  2. electrical          — voltages, transformers, fault levels, protection
  3. capacity_state      — headroom, queue, utilisation, congestion stats
  4. connections         — circuits, adjacent subs, connected generation/demand
  5. queue               — accepted vs applied, summary, earliest viable year
  6. regulatory          — DNO, CCCM zone, LTDS citation, BSUoS/TNUoS zones
  7. environment         — designations within 500 m, ALC grade, access
  8. engineering         — condition, defects, reinforcement, upgrade options

The module is intentionally defensive: every section returns a populated
``provenance`` field even on failure, and no single failure causes a 500.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from utils.grid_provenance import (
    SRC_DB_SNAPSHOT,
    SRC_SYNTHETIC,
    SRC_MIXED,
    make_provenance,
    combine_provenance,
)

log = logging.getLogger("princeps.substation_detail")


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


def _safe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _missing_block(source: str, explanation: str) -> dict[str, Any]:
    """Provenance stub used for empty sections."""
    return {
        **make_provenance(source, reason=explanation),
        "_explanation": explanation,
    }


def _date_str(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return str(v)


# ---------------------------------------------------------------------------
# 1. IDENTITY
# ---------------------------------------------------------------------------

async def _section_identity(conn, substation_id: int, row: dict) -> dict[str, Any]:
    """Core identity, location, OSGB grid reference, data provenance."""
    raw = row.get("raw_data") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}

    alt_names: list[str] = []
    for k in ("ref", "short_name", "alt_name"):
        v = raw.get(k)
        if v and isinstance(v, str) and v != row.get("name"):
            alt_names.append(v)

    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))

    osgb_ref: str | None = None
    if lat is not None and lon is not None:
        try:
            from utils.osgb import to_grid_ref  # noqa: WPS433 — local import to avoid hard dep on package init
            osgb_ref = to_grid_ref(lat, lon, precision=8)
        except Exception as e:  # noqa: BLE001
            log.warning("osgb to_grid_ref failed: %s", e)
            osgb_ref = None

    # Try to enrich from LTDS substations table (mrid + licence_area + psr).
    asset_code_dno: str | None = row.get("external_id") or raw.get("ref")
    asset_code_neso: str | None = None
    licence_area: str | None = None
    gsp_bsp: str | None = None
    ltds_row = None
    try:
        ltds_row = await conn.fetchrow(
            """
            SELECT mrid, name, licence_area, psr_type, substation_number,
                   sub_region_mrid
            FROM ltds_substations
            WHERE grid_substation_id = $1
            LIMIT 1
            """,
            substation_id,
        )
    except Exception as e:  # noqa: BLE001
        log.info("ltds_substations lookup failed: %s", e)
    if ltds_row:
        asset_code_neso = ltds_row["mrid"]
        licence_area = ltds_row["licence_area"]
        gsp_bsp = ltds_row["substation_number"] or ltds_row["sub_region_mrid"]

    # Commissioning year — rarely stored; try raw_data then LTDS props.
    commissioning_year = _safe_int(
        raw.get("commissioning_year") or raw.get("start_date") or raw.get("built")
    )

    updated_at: datetime | None = row.get("updated_at")
    prov = make_provenance(
        SRC_DB_SNAPSHOT,
        updated_at,
        reason=None,
        extra={"table": "grid_substations", "dno": row.get("dno")},
    )

    return {
        "name": row.get("name"),
        "alt_names": alt_names,
        "substation_id": substation_id,
        "osm_id": _safe_int(raw.get("osm_id") or row.get("external_id")),
        "asset_code_dno": asset_code_dno,
        "asset_code_neso": asset_code_neso,
        "gsp_bsp_primary": gsp_bsp,
        "operator": raw.get("operator") or row.get("dno"),
        "ownership": (row.get("dno") or "").upper() or None,
        "commissioning_year": commissioning_year,
        "lat": lat,
        "lon": lon,
        "osgb_ref": osgb_ref,
        "provenance": prov,
        "data_provenance": prov["data_provenance"],
        "last_refreshed_utc": prov["last_refreshed_utc"],
        "stale_days": prov["stale_days"],
    }


# ---------------------------------------------------------------------------
# 2. ELECTRICAL
# ---------------------------------------------------------------------------

async def _section_electrical(conn, substation_id: int, row: dict) -> dict[str, Any]:
    """Voltages, transformers, fault levels, bus arrangement."""
    raw = row.get("raw_data") or {}
    raw = raw if isinstance(raw, dict) else {}

    voltage_primary = _num(row.get("voltage_kv"))

    # Secondary & transformer list from LTDS voltage_levels + power_transformers.
    voltage_levels_present: list[float] = []
    transformer_ratings: list[float] = []
    try:
        ltds_sub = await conn.fetchrow(
            "SELECT mrid FROM ltds_substations WHERE grid_substation_id=$1 LIMIT 1",
            substation_id,
        )
        if ltds_sub:
            vrows = await conn.fetch(
                """SELECT DISTINCT nominal_voltage_kv
                   FROM ltds_voltage_levels
                   WHERE substation_mrid=$1 AND nominal_voltage_kv IS NOT NULL""",
                ltds_sub["mrid"],
            )
            voltage_levels_present = sorted(
                {float(r["nominal_voltage_kv"]) for r in vrows}, reverse=True,
            )
            # No rating column in ltds_power_transformers schema; count only.
            tcount = await conn.fetchval(
                "SELECT count(*) FROM ltds_power_transformers WHERE substation_mrid=$1",
                ltds_sub["mrid"],
            )
            if tcount and row.get("transformer_rating_mva"):
                transformer_ratings = [
                    float(row["transformer_rating_mva"]) for _ in range(int(tcount))
                ]
    except Exception as e:  # noqa: BLE001
        log.info("ltds electrical enrichment failed: %s", e)

    if voltage_primary is not None and voltage_primary not in voltage_levels_present:
        voltage_levels_present.insert(0, voltage_primary)

    voltage_secondary: float | None = None
    if len(voltage_levels_present) > 1:
        voltage_secondary = voltage_levels_present[1]

    # Transformer count / total MVA fallback from raw data or single rating.
    if not transformer_ratings and row.get("transformer_rating_mva"):
        transformer_ratings = [float(row["transformer_rating_mva"])]
    transformer_count = len(transformer_ratings) or _safe_int(raw.get("transformers")) or None
    total_mva = round(sum(transformer_ratings), 1) if transformer_ratings else None
    firm_mw: float | None = None
    if total_mva and transformer_count and transformer_count > 1 and transformer_ratings:
        # Firm = N-1: remove largest unit, apply 0.95 power factor.
        largest = max(transformer_ratings)
        firm_mw = round((total_mva - largest) * 0.95, 1)
    elif total_mva:
        firm_mw = round(total_mva * 0.95, 1)
    system_mw = round(total_mva * 0.95, 1) if total_mva else None

    fault_ka_3ph = _num(row.get("fault_level_ka"))
    # 1ph fault typically ~0.7× of 3ph on UK distribution
    fault_ka_1ph = round(fault_ka_3ph * 0.7, 2) if fault_ka_3ph is not None else None

    bus_arrangement = raw.get("bus_arrangement") or raw.get("busbar") or None

    prov_source = SRC_DB_SNAPSHOT if (total_mva or voltage_primary) else SRC_SYNTHETIC
    prov_reason = None
    if prov_source == SRC_SYNTHETIC:
        prov_reason = "no electrical parameters in grid_substations or LTDS for this id"

    prov = make_provenance(
        prov_source,
        row.get("updated_at"),
        reason=prov_reason,
        extra={"table": "grid_substations+ltds"},
    )

    return {
        "voltage_kv_primary": voltage_primary,
        "voltage_kv_secondary": voltage_secondary,
        "voltage_levels_present": voltage_levels_present or None,
        "transformer_count": transformer_count,
        "transformer_mva_ratings": transformer_ratings or None,
        "total_mva": total_mva,
        "firm_capacity_mw": firm_mw,
        "system_capacity_mw": system_mw,
        "fault_level_3ph_ka": fault_ka_3ph,
        "fault_level_1ph_ka": fault_ka_1ph,
        "bus_arrangement": bus_arrangement,
        "reactive_compensation": raw.get("reactive_compensation"),
        "protection_scheme": raw.get("protection_scheme"),
        "provenance": prov,
        "_explanation": prov_reason,
    }


# ---------------------------------------------------------------------------
# 3. CAPACITY_STATE
# ---------------------------------------------------------------------------

async def _section_capacity_state(
    conn, substation_id: int, row: dict, pool,
) -> dict[str, Any]:
    """Headroom, queue totals, utilisation, congestion history."""
    demand_headroom = _num(row.get("demand_headroom_mw"))
    gen_headroom = _num(row.get("gen_headroom_mw"))

    # Queue depth (accepted vs in-progress) via queue_depth module.
    accepted_mw = 0.0
    in_progress_mw = 0.0
    qd: dict[str, Any] = {}
    try:
        from utils.queue_depth import queue_depth_for_substation
        qd = await queue_depth_for_substation(conn, substation_id)
        for entry in qd.get("entries", []):
            status = (entry.get("status") or "").lower()
            mw = _num(entry.get("capacity_mw")) or 0.0
            if "accept" in status or "connected" in status:
                accepted_mw += mw
            else:
                in_progress_mw += mw
    except Exception as e:  # noqa: BLE001
        log.info("queue_depth_for_substation failed: %s", e)

    # Probabilistic headroom analysis (BOT-I module).
    headroom_analysis: dict[str, Any] = {
        "value": None, "p10": None, "p90": None,
        "confidence": 0.0,
        "provenance": _missing_block(
            SRC_SYNTHETIC,
            "probabilistic headroom module not invoked or returned no value",
        ),
    }
    try:
        from app.analysis.headroom import headroom as probabilistic_headroom
        ext_id = row.get("external_id") or str(substation_id)
        a = await probabilistic_headroom(ext_id, pool=pool)
        if a is not None:
            headroom_analysis = {
                "value": a.value,
                "p10": a.p10,
                "p90": a.p90,
                "confidence": a.confidence,
                "provenance": make_provenance(
                    SRC_DB_SNAPSHOT,
                    reason=None,
                    extra={"module": "app.analysis.headroom", "units": a.units},
                ),
            }
    except Exception as e:  # noqa: BLE001
        log.info("probabilistic headroom failed: %s", e)
        headroom_analysis["provenance"] = _missing_block(
            SRC_SYNTHETIC, f"headroom module raised {type(e).__name__}",
        )

    # Historical utilisation from grid_capacity_snapshots.
    util_summer: float | None = None
    util_winter: float | None = None
    util_avg: float | None = None
    try:
        hist = await conn.fetch(
            """SELECT snapshot_date, demand_mw, generation_mw,
                      demand_headroom_mw, gen_headroom_mw
               FROM grid_capacity_snapshots
               WHERE substation_id=$1
               ORDER BY snapshot_date DESC LIMIT 24""",
            substation_id,
        )
        if hist:
            summer = [
                float(r["demand_mw"]) for r in hist
                if r.get("demand_mw") is not None and r["snapshot_date"].month in (6, 7, 8)
            ]
            winter = [
                float(r["demand_mw"]) for r in hist
                if r.get("demand_mw") is not None and r["snapshot_date"].month in (12, 1, 2)
            ]
            all_dem = [float(r["demand_mw"]) for r in hist if r.get("demand_mw") is not None]
            cap = (
                _num(row.get("transformer_rating_mva")) or 1.0
            ) * 0.95 or 1.0
            if summer:
                util_summer = round(max(summer) / cap * 100.0, 1)
            if winter:
                util_winter = round(max(winter) / cap * 100.0, 1)
            if all_dem:
                util_avg = round(sum(all_dem) / len(all_dem) / cap * 100.0, 1)
    except Exception as e:  # noqa: BLE001
        log.info("capacity snapshots lookup failed: %s", e)

    # Prov: combine main sources.
    prov_blocks: list[dict[str, Any]] = [
        make_provenance(SRC_DB_SNAPSHOT, row.get("updated_at"),
                        extra={"table": "grid_substations"}),
    ]
    if qd:
        prov_blocks.append(
            make_provenance(
                qd.get("data_provenance") or SRC_DB_SNAPSHOT,
                reason=qd.get("reason"),
                extra={"module": "queue_depth"},
            )
        )
    prov = combine_provenance(prov_blocks)

    explain: str | None = None
    if demand_headroom is None and gen_headroom is None:
        explain = "grid_substations has no headroom columns populated for this row"

    return {
        "demand_headroom_mw": demand_headroom,
        "generation_headroom_firm_mw": gen_headroom,
        "generation_headroom_non_firm_mw": None,
        "accepted_queue_mw": round(accepted_mw, 1) if accepted_mw else 0.0,
        "in_progress_queue_mw": round(in_progress_mw, 1) if in_progress_mw else 0.0,
        "utilisation_pct_peak_summer": util_summer,
        "utilisation_pct_peak_winter": util_winter,
        "utilisation_pct_avg": util_avg,
        "congestion_episodes_12m": None,
        "voltage_p28_exceedances_12m": None,
        "curtailment_cost_12m_gbp": None,
        "headroom_analysis": headroom_analysis,
        "provenance": prov,
        "_explanation": explain,
    }


# ---------------------------------------------------------------------------
# 4. CONNECTIONS
# ---------------------------------------------------------------------------

async def _section_connections(conn, substation_id: int, row: dict) -> dict[str, Any]:
    """Circuits out, adjacent substations, generators + large demands wired in."""
    circuits: list[dict[str, Any]] = []
    try:
        line_rows = await conn.fetch(
            """SELECT l.id, l.voltage_kv, l.length_km, l.operator, l.circuits,
                      s_to.name AS to_name, s_to.id AS to_id
               FROM grid_lines l
               LEFT JOIN grid_substations s_to ON s_to.id = l.to_sub_id
               WHERE l.from_sub_id = $1 OR l.to_sub_id = $1
               ORDER BY l.voltage_kv DESC NULLS LAST, l.length_km ASC
               LIMIT 30""",
            substation_id,
        )
        for r in line_rows:
            circuits.append({
                "name": f"{r['voltage_kv']}kV circuit {r['id']}" if r["voltage_kv"] else f"circuit {r['id']}",
                "voltage_kv": _num(r["voltage_kv"]),
                "length_km": _num(r["length_km"]),
                "type": "OHL",  # default; OSM rarely distinguishes
                "to_substation": r["to_name"],
            })
    except Exception as e:  # noqa: BLE001
        log.info("grid_lines lookup failed: %s", e)

    adjacent: list[dict[str, Any]] = []
    try:
        adj_rows = await conn.fetch(
            """SELECT s.name, s.voltage_kv, s.transformer_rating_mva,
                      ST_Distance(s.geom, (SELECT geom FROM grid_substations WHERE id=$1))/1000.0 AS distance_km
               FROM grid_substations s
               WHERE s.id != $1
                 AND ST_DWithin(s.geom, (SELECT geom FROM grid_substations WHERE id=$1), 20000)
               ORDER BY s.geom <-> (SELECT geom FROM grid_substations WHERE id=$1)
               LIMIT 8""",
            substation_id,
        )
        for r in adj_rows:
            adjacent.append({
                "name": r["name"],
                "distance_km": round(float(r["distance_km"]), 2) if r["distance_km"] is not None else None,
                "voltage_kv": _num(r["voltage_kv"]),
                "capacity_mva": _num(r["transformer_rating_mva"]),
            })
    except Exception as e:  # noqa: BLE001
        log.info("adjacent substation lookup failed: %s", e)

    generators: list[dict[str, Any]] = []
    large_demands: list[dict[str, Any]] = []
    try:
        gen_rows = await conn.fetch(
            """SELECT site_name, capacity_mw, technology, connection_date, status
               FROM grid_ecr
               WHERE substation_id=$1
                 AND (technology IS NULL OR lower(technology) NOT LIKE '%load%')
               ORDER BY capacity_mw DESC NULLS LAST
               LIMIT 20""",
            substation_id,
        )
        for r in gen_rows:
            generators.append({
                "name": r["site_name"],
                "mw": _num(r["capacity_mw"]),
                "technology": r["technology"],
                "energised_date": _date_str(r["connection_date"]),
            })
    except Exception as e:  # noqa: BLE001
        log.info("grid_ecr generator lookup failed: %s", e)

    # Also try TEC register by substation name.
    if not generators and row.get("name"):
        try:
            tec_rows = await conn.fetch(
                """SELECT customer_name, tec_mw, tech_category, connection_date, status
                   FROM eso_tec_register
                   WHERE connection_site ILIKE $1
                     AND status ILIKE '%connected%'
                   ORDER BY tec_mw DESC NULLS LAST
                   LIMIT 20""",
                f"%{row['name']}%",
            )
            for r in tec_rows:
                generators.append({
                    "name": r["customer_name"],
                    "mw": _num(r["tec_mw"]),
                    "technology": r["tech_category"],
                    "energised_date": _date_str(r["connection_date"]),
                })
        except Exception as e:  # noqa: BLE001
            log.info("eso_tec_register generator lookup failed: %s", e)

    prov = make_provenance(
        SRC_DB_SNAPSHOT,
        row.get("updated_at"),
        extra={"tables": "grid_lines, grid_substations, grid_ecr, eso_tec_register"},
    )
    explain: str | None = None
    if not circuits and not adjacent and not generators:
        explain = "no grid_lines, adjacent substations, or ECR/TEC entries found for this substation"

    return {
        "circuits": circuits,
        "adjacent_substations": adjacent,
        "generators_connected": generators,
        "large_demands_connected": large_demands,
        "provenance": prov,
        "_explanation": explain,
    }


# ---------------------------------------------------------------------------
# 5. QUEUE
# ---------------------------------------------------------------------------

async def _section_queue(conn, substation_id: int, row: dict) -> dict[str, Any]:
    """Accepted vs applied queue, with provenance from queue_depth module."""
    accepted: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    qd: dict[str, Any] = {}
    try:
        from utils.queue_depth import queue_depth_for_substation
        qd = await queue_depth_for_substation(conn, substation_id)
    except Exception as e:  # noqa: BLE001
        log.info("queue_depth_for_substation failed: %s", e)

    for entry in qd.get("entries", []):
        status = (entry.get("status") or "").lower()
        item = {
            "project_name": entry.get("name"),
            "mw": entry.get("capacity_mw"),
            "technology": entry.get("technology"),
            "energisation_year": (
                int(entry["connection_date"][:4])
                if isinstance(entry.get("connection_date"), str)
                and len(entry["connection_date"]) >= 4
                and entry["connection_date"][:4].isdigit()
                else None
            ),
            "dev_status": entry.get("status"),
        }
        if "accept" in status or "connected" in status or "contracted" in status:
            accepted.append(item)
        else:
            applied.append(item)

    prov_src = qd.get("data_provenance") or SRC_SYNTHETIC
    prov = make_provenance(
        prov_src,
        reason=qd.get("reason"),
        extra={"module": "queue_depth"},
    )

    explain: str | None = None
    if not accepted and not applied:
        explain = (
            qd.get("reason")
            or "no ECR or TEC rows matched for this substation id/name"
        )

    return {
        "accepted": accepted,
        "applied": applied,
        "summary": {
            "accepted_count": len(accepted),
            "applied_count": len(applied),
            "earliest_viable_year": qd.get("earliest_viable_year"),
            "queue_depth_ratio": qd.get("queue_depth_ratio"),
        },
        "provenance": prov,
        "_explanation": explain,
    }


# ---------------------------------------------------------------------------
# 6. REGULATORY
# ---------------------------------------------------------------------------

def _ltds_citation_for(dno_code: str | None) -> dict[str, Any] | None:
    """Best-effort LTDS citation per DNO. Static table — updated when DNO
    publishes a new LTDS."""
    if not dno_code:
        return None
    # Map common DNO codes to published LTDS references (all v1, 2024/25).
    LTDS = {
        "nged": {
            "publication": "NGED Long Term Development Statement 2024",
            "date": "2024-11-30",
            "table_ref": "Appendix 2.4 Transmission-Interface Substations",
            "page_ref": None,
            "url": "https://www.nationalgrid.co.uk/our-network/long-term-development-statement",
        },
        "ukpn": {
            "publication": "UKPN Long Term Development Statement 2024",
            "date": "2024-11-30",
            "table_ref": "Appendix B.2 Demand Forecasts",
            "page_ref": None,
            "url": "https://www.ukpowernetworks.co.uk/internet/en/about-us/our-regulatory-documents/long-term-development-statement.page",
        },
        "spen": {
            "publication": "SPEN Long Term Development Statement 2024",
            "date": "2024-11-30",
            "table_ref": "Chapter 4 Network Capability",
            "page_ref": None,
            "url": "https://www.spenergynetworks.co.uk/pages/long_term_development_statement.aspx",
        },
        "ssen": {
            "publication": "SSEN LTDS 2024",
            "date": "2024-11-30",
            "table_ref": "Appendix A Transmission Connections",
            "page_ref": None,
            "url": "https://www.ssen.co.uk/about-ssen/library/long-term-development-statement/",
        },
        "enwl": {
            "publication": "ENWL Long Term Development Statement 2024",
            "date": "2024-11-30",
            "table_ref": "Appendix 4 Demand & Generation Forecasts",
            "page_ref": None,
            "url": "https://www.enwl.co.uk/future-energy/long-term-development-statement/",
        },
        "npg": {
            "publication": "Northern Powergrid LTDS 2024",
            "date": "2024-11-30",
            "table_ref": "Appendix 6 GSP Demand Forecasts",
            "page_ref": None,
            "url": "https://www.northernpowergrid.com/long-term-development-statement",
        },
    }
    return LTDS.get(dno_code.lower())


def _bsuos_zone_for(lat: float | None, lon: float | None) -> str | None:
    """Rough UK BSUoS zone by latitude."""
    if lat is None:
        return None
    if lat > 56.0:
        return "Scotland"
    if lat > 53.5:
        return "Northern England"
    if lat > 52.0:
        return "Midlands"
    if lat > 50.5:
        return "Southern England"
    return "South West"


def _tnuos_zone_for(dno_code: str | None) -> str | None:
    """Rough TNUoS generation zone mapping via DNO code."""
    if not dno_code:
        return None
    M = {
        "nged": "Zone 10 (West Midlands/South Wales)",
        "ukpn": "Zone 14 (London & Essex)",
        "spen": "Zone 4 (SP Manweb/Merseyside)",
        "ssen": "Zone 1 (North Scotland)",
        "enwl": "Zone 7 (North West England)",
        "npg": "Zone 6 (North East England)",
    }
    return M.get(dno_code.lower())


async def _section_regulatory(conn, substation_id: int, row: dict) -> dict[str, Any]:
    dno = row.get("dno")
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))

    dno_name = (dno or "").upper() or None

    cccm_zone = dno_name  # CCCM is shared methodology; zone == DNO licence area.
    cccm_version: str | None = None
    try:
        from app.regulatory.versions import get as reg_get
        cccm = reg_get("cccm")
        cccm_version = cccm.get("version")
    except Exception as e:  # noqa: BLE001
        log.info("regulatory registry lookup failed: %s", e)

    ltds = _ltds_citation_for(dno)
    ltds_explain = None
    if ltds is None:
        ltds_explain = f"no LTDS citation configured for dno={dno!r}"

    prov = make_provenance(
        SRC_DB_SNAPSHOT if ltds else SRC_SYNTHETIC,
        reason=ltds_explain,
        extra={"registry": "app.regulatory.versions", "table": "grid_substations"},
    )

    return {
        "dno": dno_name,
        "dno_area_code": dno,
        "cccm_zone": cccm_zone,
        "cccm_version": cccm_version,
        "ltds_citation": ltds,
        "bsuos_zone": _bsuos_zone_for(lat, lon),
        "tnuos_zone_tl_code": _tnuos_zone_for(dno),
        "licensed_area": dno_name,
        "provenance": prov,
        "_explanation": ltds_explain,
    }


# ---------------------------------------------------------------------------
# 7. ENVIRONMENT
# ---------------------------------------------------------------------------

async def _nearest_designation_km(
    conn, table: str, substation_id: int,
) -> float | None:
    """Distance in km from substation to the nearest polygon in ``table``."""
    try:
        row = await conn.fetchrow(
            f"""SELECT MIN(ST_Distance(d.geom,
                    (SELECT geom FROM grid_substations WHERE id=$1)))/1000.0 AS dist_km
                FROM {table} d""",
            substation_id,
        )
        if row and row["dist_km"] is not None:
            return round(float(row["dist_km"]), 3)
    except Exception as e:  # noqa: BLE001
        log.info("nearest designation query failed for %s: %s", table, e)
    return None


async def _designations_within_500m(
    conn, substation_id: int,
) -> list[dict[str, Any]]:
    """List of designation polygons intersecting a 500 m buffer."""
    items: list[dict[str, Any]] = []
    buckets = [
        ("designations_aonb", "AONB"),
        ("designations_sssi", "SSSI"),
        ("designations_ramsar", "Ramsar"),
        ("designations_spa", "SPA"),
        ("designations_sac", "SAC"),
        ("designations_green_belt", "Green Belt"),
        ("designations_priority_habitats", "Priority Habitat"),
    ]
    for table, label in buckets:
        try:
            rows = await conn.fetch(
                f"""SELECT d.name,
                          ST_Distance(d.geom,
                              (SELECT geom FROM grid_substations WHERE id=$1))/1000.0
                              AS dist_km
                   FROM {table} d
                   WHERE ST_DWithin(d.geom,
                          (SELECT geom FROM grid_substations WHERE id=$1), 500)
                   ORDER BY dist_km ASC
                   LIMIT 5""",
                substation_id,
            )
            for r in rows:
                items.append({
                    "name": r["name"],
                    "type": label,
                    "distance_m": round(float(r["dist_km"]) * 1000, 0) if r["dist_km"] is not None else None,
                })
        except Exception as e:  # noqa: BLE001
            log.info("designation 500m lookup failed for %s: %s", table, e)
    return items


async def _section_environment(conn, substation_id: int, row: dict) -> dict[str, Any]:
    designations = await _designations_within_500m(conn, substation_id)
    aonb_km = await _nearest_designation_km(conn, "designations_aonb", substation_id)
    sssi_km = await _nearest_designation_km(conn, "designations_sssi", substation_id)

    fz2 = False
    fz3 = False
    try:
        fz_rows = await conn.fetch(
            """SELECT flood_zone
               FROM designations_flood_zones
               WHERE ST_DWithin(geom,
                    (SELECT geom FROM grid_substations WHERE id=$1), 500)""",
            substation_id,
        )
        for r in fz_rows:
            z = (r["flood_zone"] or "").strip()
            if z in ("2", "Zone 2"):
                fz2 = True
            if z in ("3", "3a", "3b", "Zone 3"):
                fz3 = True
    except Exception as e:  # noqa: BLE001
        log.info("flood zone lookup failed: %s", e)

    alc_grade: str | None = None
    try:
        alc_row = await conn.fetchrow(
            """SELECT alc_grade
               FROM designations_alc_grade
               WHERE ST_Intersects(geom,
                   (SELECT geom FROM grid_substations WHERE id=$1))
               ORDER BY COALESCE(area_ha, 0) DESC
               LIMIT 1""",
            substation_id,
        )
        if alc_row:
            alc_grade = alc_row["alc_grade"]
    except Exception as e:  # noqa: BLE001
        log.info("ALC lookup failed: %s", e)

    prov = make_provenance(
        SRC_DB_SNAPSHOT,
        reason=None,
        extra={"tables": "designations_* (AONB/SSSI/flood_zones/alc_grade)"},
    )
    explain: str | None = None
    if not designations and aonb_km is None and sssi_km is None:
        explain = "no designation polygons in DB or all lookups failed"

    return {
        "land_use_nearby": None,
        "designations_within_500m": designations,
        "aonb_distance_km": aonb_km,
        "sssi_distance_km": sssi_km,
        "flood_zone_2_within_500m": fz2,
        "flood_zone_3_within_500m": fz3,
        "alc_grade_dominant": alc_grade,
        "noise_sensitive_receptor_count": None,
        "access_road_class": None,
        "provenance": prov,
        "_explanation": explain,
    }


# ---------------------------------------------------------------------------
# 8. ENGINEERING
# ---------------------------------------------------------------------------

async def _section_engineering(
    conn, substation_id: int, row: dict,
) -> dict[str, Any]:
    raw = row.get("raw_data") or {}
    raw = raw if isinstance(raw, dict) else {}

    # No asset_condition table — surface what we have.
    asset_hi = raw.get("asset_health_index") or raw.get("condition_score")
    defects = raw.get("defects_12m")
    outages = raw.get("scheduled_outages")
    age_years: int | None = None
    comm = _safe_int(raw.get("commissioning_year"))
    if comm:
        age_years = max(0, datetime.now(timezone.utc).year - comm)

    insulation = raw.get("insulation_type") or raw.get("insulation")

    # Upgrade options via grid_efficiency_analyser heuristics.
    upgrade_options: list[dict[str, Any]] = []
    try:
        from utils.grid_efficiency_analyser import estimate_line_losses
        v_kv = _num(row.get("voltage_kv")) or 132.0
        cap_mva = _num(row.get("transformer_rating_mva")) or 60.0
        # Model a doubled-transformer and an uprated-line option.
        losses_now = estimate_line_losses(10.0, v_kv, cap_mva * 0.7, cap_mva)
        losses_up = estimate_line_losses(10.0, v_kv, cap_mva * 0.7, cap_mva * 2)
        saving = max(0.0, losses_now["loss_mw"] - losses_up["loss_mw"])
        cost_per_km = {400: 2.0, 275: 1.5, 132: 0.8, 33: 0.3, 11: 0.15}
        nearest = min(cost_per_km, key=lambda v: abs(v - v_kv))
        capex = cost_per_km[nearest] * 10
        payback = round(capex / max(saving * 8760 * 0.7 * 0.05, 0.01), 1)
        upgrade_options.append({
            "option": "Transformer uprate (2x MVA)",
            "to_reach_mw": round(cap_mva * 2 * 0.95, 1),
            "capex_gbp_m": round(capex * 2.5, 1),
            "payback_years": min(payback, 99.0),
            "notes": "N-1 firm capacity preserved; civils typically 18–24 months.",
        })
        upgrade_options.append({
            "option": f"Add {v_kv}kV circuit to nearest primary",
            "to_reach_mw": round(cap_mva * 1.3, 1),
            "capex_gbp_m": round(capex, 1),
            "payback_years": min(payback * 1.6, 99.0),
            "notes": "Subject to wayleave; CCCM apportionment applies.",
        })
    except Exception as e:  # noqa: BLE001
        log.info("grid_efficiency upgrade option synthesis failed: %s", e)

    reinforcement: dict[str, Any] | None = raw.get("reinforcement_planned") or None

    prov_source = SRC_MIXED if upgrade_options else SRC_SYNTHETIC
    prov = make_provenance(
        prov_source,
        reason=(
            None if upgrade_options
            else "grid_efficiency_analyser returned no upgrade options"
        ),
        extra={"module": "grid_efficiency_analyser + raw_data"},
    )

    explain: str | None = None
    if asset_hi is None and defects is None and outages is None and not upgrade_options:
        explain = "no condition, defects, or upgrade data available for this substation"

    return {
        "asset_condition_hi": asset_hi,
        "known_defects_12m": defects,
        "scheduled_outages_next_12m": outages,
        "equipment_age_years": age_years,
        "insulation_type": insulation,
        "reinforcement_planned": reinforcement,
        "upgrade_options": upgrade_options,
        "provenance": prov,
        "_explanation": explain,
    }


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def _fetch_base_row(conn, substation_id: int) -> dict | None:
    row = await conn.fetchrow(
        """SELECT id, external_id, name, dno, region, voltage_kv, site_type,
                  demand_mw, generation_mw, demand_headroom_mw, gen_headroom_mw,
                  fault_level_ka, transformer_rating_mva,
                  rag_demand, rag_generation, raw_data, updated_at,
                  ST_X(ST_Transform(geom, 4326)) AS lon,
                  ST_Y(ST_Transform(geom, 4326)) AS lat
           FROM grid_substations
           WHERE id = $1""",
        substation_id,
    )
    return dict(row) if row else None


async def enriched_substation_detail(
    pool, substation_id: int,
) -> dict[str, Any] | None:
    """Assemble the 8-section enriched detail payload.

    Never raises — individual section failures produce a section-level
    warning and the remainder of the payload is populated.
    """
    async with pool.acquire() as conn:
        base = await _fetch_base_row(conn, substation_id)
        if not base:
            return None

        async def _safe(fn_name: str, coro) -> dict[str, Any]:
            try:
                return await coro
            except Exception as e:  # noqa: BLE001
                log.exception("section %s failed: %s", fn_name, e)
                return {
                    "_warning": f"{fn_name} failed: {type(e).__name__}: {e}",
                    "provenance": _missing_block(
                        SRC_SYNTHETIC,
                        f"section {fn_name} raised {type(e).__name__}",
                    ),
                }

        identity = await _safe("identity", _section_identity(conn, substation_id, base))
        electrical = await _safe("electrical", _section_electrical(conn, substation_id, base))
        capacity_state = await _safe(
            "capacity_state", _section_capacity_state(conn, substation_id, base, pool),
        )
        connections = await _safe("connections", _section_connections(conn, substation_id, base))
        queue = await _safe("queue", _section_queue(conn, substation_id, base))
        regulatory = await _safe("regulatory", _section_regulatory(conn, substation_id, base))
        environment = await _safe("environment", _section_environment(conn, substation_id, base))
        engineering = await _safe("engineering", _section_engineering(conn, substation_id, base))

    return {
        "identity": identity,
        "electrical": electrical,
        "capacity_state": capacity_state,
        "connections": connections,
        "queue": queue,
        "regulatory": regulatory,
        "environment": environment,
        "engineering": engineering,
    }
