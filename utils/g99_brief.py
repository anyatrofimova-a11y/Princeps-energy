"""
G99 auto-brief generator.

Given a project_id, assemble the context a developer needs to fill an
ENA EREC G99 application form. Returns:

  {
    "project_id": ...,
    "form_context": {...},          # structured JSON ready for a form mapper
    "markdown": "...",              # human-readable draft
    "provenance": {...},            # where each datum came from
  }

The brief pulls from:

 - projects table (site name, lat/lon, capacity_mw, technology)
 - grid_substations (POC substation details)
 - existing utils.g99_compliance  (category, protection settings)
 - utils.queue_depth                (queue headroom sanity check)

If upstream data is missing we populate best-effort defaults and flag the
brief's data_provenance as synthetic_fallback with a reason. The endpoint
always returns 200; it never raises.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from utils.g99_compliance import check_g99_compliance, g99_protection_settings
from utils.grid_provenance import (
    SRC_DB_SNAPSHOT, SRC_SYNTHETIC, combine_provenance, make_provenance,
)
from utils.queue_depth import queue_depth_for_substation

log = logging.getLogger("princeps.g99_brief")


# Inverter selection heuristics by technology. These are defaults — a developer
# will over-ride. They are not marketing claims.
DEFAULT_INVERTER = {
    "solar": {
        "type": "grid-following string inverter",
        "topology": "central",
        "anti_islanding": "Vector-shift + RoCoF (EREC G99 LoM)",
    },
    "bess": {
        "type": "grid-forming battery inverter",
        "topology": "containerised PCS",
        "anti_islanding": "RoCoF + vector-shift with virtual inertia",
    },
    "wind": {
        "type": "doubly-fed induction generator",
        "topology": "turbine-mounted converter",
        "anti_islanding": "Vector-shift + RoCoF",
    },
}


def _first_energisation_estimate(capacity_mw: float) -> str:
    """Return a coarse energisation horizon (ISO month) as text."""
    now = datetime.now(timezone.utc)
    if capacity_mw <= 1:
        months = 12
    elif capacity_mw <= 10:
        months = 24
    elif capacity_mw <= 50:
        months = 36
    else:
        months = 48
    target = now.replace(day=1)
    month = target.month - 1 + months
    year = target.year + month // 12
    month = month % 12 + 1
    return f"{year:04d}-{month:02d}"


def _fault_level_contribution(capacity_mw: float, technology: str) -> dict[str, Any]:
    """
    Approximate inverter fault-level contribution per G99 Type B/C guidance.
    Inverter-interfaced plant typically contributes 1.1–1.5× rated current.
    """
    tech = (technology or "").lower()
    if tech in ("solar", "bess"):
        multiplier = 1.2
    elif tech == "wind":
        multiplier = 1.3
    else:
        multiplier = 1.5
    rated_current_a = capacity_mw * 1_000_000 / (33_000 * 1.732)  # default 33 kV
    return {
        "multiplier_of_rated": multiplier,
        "estimated_peak_ka": round(rated_current_a * multiplier / 1000, 3),
        "basis": "inverter-interfaced, sub-cycle, G99 Type B/C guidance",
    }


def _export_limit_mw(capacity_mw: float) -> dict[str, Any]:
    """Simple export-limit suggestion — developer-configurable."""
    return {
        "requested_export_mw": capacity_mw,
        "export_limit_scheme": "ANM (Active Network Management) or hard-wired relay",
        "notes": (
            "Export limit typically mirrors requested capacity unless the DNO "
            "offers a flexible/ANM connection at lower cost."
        ),
    }


async def _fetch_project(conn, project_id: str) -> tuple[dict | None, datetime | None]:
    row = await conn.fetchrow("""
        SELECT project_id, name, technology, capacity_mw, lat, lon,
               verdict, stage, metadata, updated_at, created_at
        FROM projects
        WHERE project_id::text = $1
    """, str(project_id))
    if not row:
        return None, None
    d = dict(row)
    refreshed = d.get("updated_at") or d.get("created_at")
    return d, refreshed


async def _nearest_substation(conn, lat: float, lon: float) -> tuple[dict | None, datetime | None]:
    row = await conn.fetchrow("""
        SELECT id, name, dno, voltage_kv, site_type,
               gen_headroom_mw, fault_level_ka, transformer_rating_mva,
               updated_at,
               ST_X(ST_Transform(geom, 4326)) AS lon,
               ST_Y(ST_Transform(geom, 4326)) AS lat,
               ST_Distance(
                   geom,
                   ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
               ) / 1000.0 AS distance_km
        FROM grid_substations
        WHERE site_type NOT IN ('lv_transformer', 'traction', 'unknown')
          AND (voltage_kv IS NULL OR voltage_kv >= 11)
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)
    if not row:
        return None, None
    d = dict(row)
    return d, d.get("updated_at")


def _render_markdown(ctx: dict[str, Any]) -> str:
    p = ctx["project"]
    poc = ctx.get("poc_substation") or {}
    inv = ctx["inverter"]
    fl = ctx["fault_level_contribution"]
    cat = ctx["g99_category"]
    export = ctx["export_limit"]
    prov = ctx["provenance"]

    poc_line = (
        f"{poc.get('name','UNKNOWN')} ({poc.get('dno','?')}, "
        f"{poc.get('voltage_kv','?')} kV, {poc.get('distance_km','?')} km from site)"
        if poc else "not identified — substation search returned no result"
    )

    lines = [
        f"# G99 Application Brief — {p.get('name','Untitled project')}",
        "",
        f"- Project ID: `{ctx['project_id']}`",
        f"- Site coordinates: {p.get('lat')}, {p.get('lon')}",
        f"- Technology: {p.get('technology','unknown')}",
        f"- Installed capacity: {p.get('capacity_mw','?')} MW",
        f"- G99 category: **{cat.get('category','?')}** "
        f"({cat.get('applicable_standard','')})",
        f"- Point of connection: {poc_line}",
        f"- Inverter type: {inv['type']} ({inv['topology']})",
        f"- Anti-islanding: {inv['anti_islanding']}",
        f"- Fault-level contribution: {fl['multiplier_of_rated']}× rated "
        f"(≈ {fl['estimated_peak_ka']} kA peak)",
        f"- Export limit: {export['requested_export_mw']} MW "
        f"({export['export_limit_scheme']})",
        f"- Expected first energisation: {ctx['first_energisation']}",
        "",
        "## Protection (EREC G99 Table A.1/A.2)",
    ]
    vp = ctx.get("protection", {}).get("voltage_protection", {})
    fp = ctx.get("protection", {}).get("frequency_protection", {})
    for stage, val in (vp or {}).items():
        if isinstance(val, dict):
            pct = val.get("setting_percent_un")
            delay = val.get("time_delay_s")
        else:
            pct = val[0] if val else None
            delay = val[1] if val else None
        lines.append(f"- {stage}: {pct}% Un, {delay} s")
    for stage, val in (fp or {}).items():
        if isinstance(val, dict):
            hz = val.get("setting_hz")
            delay = val.get("time_delay_s")
        else:
            hz = val[0] if val else None
            delay = val[1] if val else None
        lines.append(f"- {stage}: {hz} Hz, {delay} s")
    lines.append("")
    lines.append("## Queue-depth sanity check")
    qd = ctx.get("queue_depth_check") or {}
    if qd.get("substation_id"):
        lines.append(
            f"- Free headroom at POC: {qd.get('free_headroom_mw')} MW "
            f"(queue depth ratio {qd.get('queue_depth_ratio')})"
        )
        lines.append(f"- Earliest viable year: {qd.get('earliest_viable_year')}")
    else:
        lines.append("- Queue-depth check not available (POC not resolved).")

    lines.append("")
    lines.append("## Provenance")
    lines.append(f"- Source: `{prov.get('data_provenance')}`")
    lines.append(f"- Last refreshed (UTC): {prov.get('last_refreshed_utc')}")
    lines.append(f"- Stale days: {prov.get('stale_days')}")
    if prov.get("reason"):
        lines.append(f"- Reason: {prov['reason']}")
    return "\n".join(lines)


async def build_g99_brief(conn, project_id: str) -> dict[str, Any]:
    """
    Build the G99 brief. Always returns a 200-style dict.
    """
    provs: list[dict[str, Any]] = []

    project, proj_refreshed = await _fetch_project(conn, project_id)
    if not project:
        prov = make_provenance(
            SRC_SYNTHETIC,
            reason=f"project {project_id} not found in projects table",
        )
        return {
            "project_id": project_id,
            "error": "project_not_found",
            "form_context": None,
            "markdown": None,
            **prov,
        }
    provs.append(make_provenance(SRC_DB_SNAPSHOT, proj_refreshed,
                                 extra={"table": "projects"}))

    lat = project.get("lat")
    lon = project.get("lon")
    capacity_mw = float(project.get("capacity_mw") or 0) or 5.0
    technology = (project.get("technology") or "solar").lower()

    poc, poc_refreshed = (None, None)
    queue_check: dict[str, Any] = {}
    if lat is not None and lon is not None:
        poc, poc_refreshed = await _nearest_substation(conn, lat, lon)
        if poc:
            provs.append(make_provenance(SRC_DB_SNAPSHOT, poc_refreshed,
                                         extra={"table": "grid_substations"}))
            try:
                queue_check = await queue_depth_for_substation(conn, poc["id"])
                # The queue_depth result already carries a provenance block.
                q_prov = {
                    "data_provenance": queue_check.get("data_provenance"),
                    "last_refreshed_utc": queue_check.get("last_refreshed_utc"),
                    "stale_days": queue_check.get("stale_days"),
                    "reason": queue_check.get("reason"),
                }
                provs.append(q_prov)
            except Exception as e:
                log.exception("queue_depth_for_substation failed")
                provs.append(make_provenance(
                    SRC_SYNTHETIC,
                    reason=f"queue-depth sub-call failed: {e.__class__.__name__}",
                ))
        else:
            provs.append(make_provenance(
                SRC_SYNTHETIC,
                reason="no substation found near project coordinates",
            ))
    else:
        provs.append(make_provenance(
            SRC_SYNTHETIC,
            reason="project has no lat/lon — POC cannot be resolved",
        ))

    voltage_kv = float(poc.get("voltage_kv") or 33) if poc else 33.0

    g99_cat = check_g99_compliance(capacity_mw, voltage_kv, technology)
    prot = g99_protection_settings(capacity_mw, voltage_kv, technology)

    inv = DEFAULT_INVERTER.get(technology, DEFAULT_INVERTER["solar"])

    ctx: dict[str, Any] = {
        "project_id": str(project.get("project_id")),
        "project": {
            "name": project.get("name"),
            "technology": technology,
            "capacity_mw": capacity_mw,
            "lat": lat, "lon": lon,
            "stage": project.get("stage"),
        },
        "poc_substation": (
            {
                "id": poc["id"],
                "name": poc["name"],
                "dno": poc.get("dno"),
                "voltage_kv": poc.get("voltage_kv"),
                "distance_km": round(float(poc["distance_km"]), 2),
                "fault_level_ka": poc.get("fault_level_ka"),
                "transformer_rating_mva": poc.get("transformer_rating_mva"),
            }
            if poc else None
        ),
        "inverter": inv,
        "fault_level_contribution": _fault_level_contribution(capacity_mw, technology),
        "export_limit": _export_limit_mw(capacity_mw),
        "first_energisation": _first_energisation_estimate(capacity_mw),
        "g99_category": g99_cat,
        "protection": prot,
        "queue_depth_check": (
            {
                "substation_id": queue_check.get("substation_id"),
                "free_headroom_mw": queue_check.get("free_headroom_mw"),
                "queue_depth_ratio": queue_check.get("queue_depth_ratio"),
                "earliest_viable_year": queue_check.get("earliest_viable_year"),
            } if queue_check else {}
        ),
    }

    provenance = combine_provenance(provs)
    ctx["provenance"] = provenance

    markdown = _render_markdown(ctx)

    return {
        "project_id": ctx["project_id"],
        "form_context": ctx,
        "markdown": markdown,
        **provenance,  # top-level provenance fields per contract
    }
