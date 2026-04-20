"""Agentic KPI composition — structured scoring for the twin's operational intelligence.

Pulls honest numbers from existing utilities (headroom, buildable_area, queue_depth,
grid_connection_analyser, dcf_evaluator, lcoe, agent verdict logic) and wraps them
into a stable KPI contract for the Assess-tab rail and parcel drawer.

Each KPI carries: id, label, value, unit, verdict (green/amber/red/unknown),
source (provenance string), and explanation. On compute failure a KPI is still
returned with value=null and an explanation naming the upstream gap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

log = logging.getLogger("princeps.agentic_scoring")


# ─── Verdict thresholds ────────────────────────────────────────────────────
# Tuned for UK utility-scale solar + BESS on mid-voltage DNO networks.

THRESHOLDS: dict[str, dict[str, float]] = {
    # Grid viability score (0-100): higher = more viable
    "grid_viability": {"green": 70.0, "amber": 40.0},
    # Planning likelihood (%): P(approval)
    "planning_likelihood": {"green": 65.0, "amber": 40.0},
    # Buildable hectares as % of parcel area
    "buildable_pct": {"green": 80.0, "amber": 50.0},
    # Connection cost £m at P50 — lower is better
    "connection_cost_p50_m": {"green": 2.0, "amber": 5.0},
    # Queue position (projects ahead) — lower is better
    "queue_position": {"green": 5.0, "amber": 20.0},
    # LCOE £/MWh — lower is better
    "lcoe_gbp_mwh": {"green": 65.0, "amber": 85.0},
    # Revenue P50 £m/yr — informational; verdict from DSCR if available
    "revenue_p50_m": {"green": 5.0, "amber": 2.0},
}


def _verdict_higher_better(value: float | None, green: float, amber: float) -> str:
    if value is None:
        return "unknown"
    if value >= green:
        return "green"
    if value >= amber:
        return "amber"
    return "red"


def _verdict_lower_better(value: float | None, green: float, amber: float) -> str:
    if value is None:
        return "unknown"
    if value <= green:
        return "green"
    if value <= amber:
        return "amber"
    return "red"


def _verdict_from_agent(verdict_str: str | None) -> str:
    if not verdict_str:
        return "unknown"
    v = str(verdict_str).upper().strip()
    return {"GO": "green", "CAUTION": "amber", "NO-GO": "red", "NO_GO": "red"}.get(v, "unknown")


def _kpi(
    id_: str,
    label: str,
    value: float | str | None,
    unit: str | None,
    verdict: str,
    source: str,
    explanation: str,
) -> dict[str, Any]:
    return {
        "id": id_,
        "label": label,
        "value": value,
        "unit": unit,
        "verdict": verdict,
        "source": source,
        "explanation": explanation,
    }


def _unknown_kpi(id_: str, label: str, unit: str | None, source: str, reason: str) -> dict[str, Any]:
    return _kpi(id_, label, None, unit, "unknown", source, f"unavailable — {reason}")


# ─── Project data gather ───────────────────────────────────────────────────

async def _load_project(conn, project_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """SELECT project_id, name, description, status, technology,
                  capacity_mw, stage, verdict, lat, lon, metadata
           FROM projects WHERE project_id = $1""",
        project_id,
    )
    if not row:
        return None
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = meta or {}
    return {
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "technology": row["technology"],
        "capacity_mw": float(row["capacity_mw"] or 0.0),
        "verdict": row["verdict"],
        "lat": row["lat"],
        "lon": row["lon"],
        "metadata": meta,
    }


async def _latest_design_kpis(conn, project_id: UUID) -> dict | None:
    try:
        row = await conn.fetchrow(
            """SELECT kpis FROM design_layouts
               WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1""",
            project_id,
        )
        if row and row["kpis"]:
            k = row["kpis"]
            return json.loads(k) if isinstance(k, str) else k
    except Exception as e:
        log.debug("latest_design_kpis: %s", e)
    return None


async def _nearest_substation(conn, lat, lon) -> dict | None:
    """Return nearest substation with id, name, headroom. Works against
    grid_substations if available, falls back to dno_substations."""
    if lat is None or lon is None:
        return None
    # Prefer grid_substations (has numeric id used by queue_depth)
    try:
        row = await conn.fetchrow(
            """SELECT id, name, dno, voltage_kv,
                      demand_headroom_mw, gen_headroom_mw,
                      ST_Distance(geom,
                          ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
                      )/1000.0 AS dist_km
               FROM grid_substations
               ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
               LIMIT 1""",
            lon, lat,
        )
        if row:
            return {
                "id": int(row["id"]),
                "name": row["name"],
                "dno": row["dno"],
                "voltage_kv": float(row["voltage_kv"] or 33),
                "gen_headroom_mw": float(row["gen_headroom_mw"] or 0.0) if row["gen_headroom_mw"] is not None else None,
                "demand_headroom_mw": float(row["demand_headroom_mw"] or 0.0) if row["demand_headroom_mw"] is not None else None,
                "dist_km": float(row["dist_km"] or 0.0),
                "source_table": "grid_substations",
            }
    except Exception as e:
        log.debug("nearest grid_substations: %s", e)
    # Fallback — dno_substations (no numeric id for queue_depth)
    try:
        row = await conn.fetchrow(
            """SELECT name, capacity_kw,
                      ST_Distance(geometry,
                          ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
                      )/1000.0 AS dist_km
               FROM dno_substations
               ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
               LIMIT 1""",
            lon, lat,
        )
        if row:
            cap_mw = float(row["capacity_kw"] or 0.0) / 1000.0
            return {
                "id": None,
                "name": row["name"],
                "dno": None,
                "voltage_kv": 33.0,
                "gen_headroom_mw": round(cap_mw * 0.3, 1),
                "demand_headroom_mw": None,
                "dist_km": float(row["dist_km"] or 0.0),
                "source_table": "dno_substations",
            }
    except Exception as e:
        log.debug("nearest dno_substations: %s", e)
    return None


# ─── Individual KPI computations ───────────────────────────────────────────

async def _kpi_grid_viability(pool, proj: dict, sub: dict | None) -> dict[str, Any]:
    """Composite 0-100 score: headroom ratio + queue depth + cost proxy."""
    label = "Grid Viability"
    if sub is None:
        return _unknown_kpi("grid_viability", label, "/100",
                            "analysis.headroom + queue_depth + cost",
                            "no substation within search radius")

    capacity = max(float(proj.get("capacity_mw") or 0.0), 1.0)
    headroom = sub.get("gen_headroom_mw")
    # Headroom component (50 pts): ratio of headroom to required capacity
    if headroom is None:
        head_score = 25.0  # neutral
        head_reason = f"headroom unknown at {sub['name']}"
    else:
        ratio = headroom / capacity
        head_score = max(0.0, min(50.0, 50.0 * min(ratio, 1.0)))
        head_reason = f"{headroom:.1f} MW headroom vs {capacity:.1f} MW need ({ratio*100:.0f}%)"

    # Queue depth component (30 pts): via queue_depth util when substation id known
    queue_score = 15.0
    queue_reason = "queue depth unknown"
    ahead = None
    if sub.get("id") is not None:
        try:
            from utils.queue_depth import queue_depth_for_substation
            async with pool.acquire() as conn:
                qd = await queue_depth_for_substation(conn, sub["id"])
            ahead_raw = qd.get("ahead_in_queue_count")
            if ahead_raw is not None:
                ahead = int(ahead_raw)
                # 0 ahead → 30 pts, 30+ ahead → 0 pts
                queue_score = max(0.0, 30.0 - ahead * 1.0)
                queue_reason = f"{ahead} projects ahead in queue"
        except Exception as e:
            log.debug("queue_depth inside viability: %s", e)

    # Distance component (20 pts): closer is better
    dist = float(sub.get("dist_km") or 0.0)
    if dist < 1:
        dist_score = 20.0
    elif dist < 5:
        dist_score = 15.0
    elif dist < 15:
        dist_score = 8.0
    else:
        dist_score = max(0.0, 8.0 - (dist - 15) * 0.3)
    dist_reason = f"{dist:.1f} km to {sub['name']}"

    total = round(head_score + queue_score + dist_score)
    thr = THRESHOLDS["grid_viability"]
    verdict = _verdict_higher_better(total, thr["green"], thr["amber"])
    explanation = f"{head_reason}; {queue_reason}; {dist_reason}"
    return _kpi("grid_viability", label, total, "/100", verdict,
                "analysis.headroom + queue_depth + cable_distance", explanation)


async def _kpi_planning_likelihood(pool, proj: dict) -> dict[str, Any]:
    label = "Planning Likelihood"
    lat = proj.get("lat")
    lon = proj.get("lon")
    tech = (proj.get("technology") or "solar").lower()
    cap = float(proj.get("capacity_mw") or 50.0)
    if lat is None or lon is None:
        return _unknown_kpi("planning_likelihood", label, "%",
                            "planning_ml + policy_matrix + designations",
                            "no project coordinates")
    # Map non-REPD tech slugs onto the predictor's vocabulary
    tech_map = {"dc": "solar", "datacentre": "solar", "datacenter": "solar"}
    predictor_tech = tech_map.get(tech, tech)

    try:
        from utils.planning_predictor import get_predictor
        predictor = await get_predictor(pool)
        result = await predictor.predict(pool, lat, lon, predictor_tech, cap)
    except Exception as e:
        return _unknown_kpi("planning_likelihood", label, "%",
                            "planning_predictor (REPD GradientBoost)",
                            f"model error: {type(e).__name__}")

    prob = result.get("approval_probability")
    if prob is None:
        return _unknown_kpi("planning_likelihood", label, "%",
                            "planning_predictor",
                            result.get("error") or "no prediction returned")
    pct = round(float(prob) * 100.0, 1) if prob <= 1.0 else round(float(prob), 1)
    thr = THRESHOLDS["planning_likelihood"]
    verdict = _verdict_higher_better(pct, thr["green"], thr["amber"])
    risks = result.get("risk_factors") or []
    explanation_bits = [f"REPD model P(approval) {pct}%"]
    if risks:
        explanation_bits.append(f"risks: {'; '.join(risks[:2])}")
    months = result.get("predicted_months_to_decision")
    if months:
        explanation_bits.append(f"~{months:.0f}mo to decision")
    return _kpi("planning_likelihood", label, pct, "%", verdict,
                "planning_predictor (REPD GradientBoost)",
                " — ".join(explanation_bits))


async def _kpi_buildable_ha(pool, proj: dict) -> dict[str, Any]:
    label = "Buildable"
    meta = proj.get("metadata") or {}
    design = dict(meta.get("design") or {})
    site_area = float(design.get("site_area_ha") or 0.0)
    parcel_id = meta.get("parcel_id") or meta.get("inspire_id")

    # Try inspire-parcel buildable-area analysis first
    buildable = None
    explanation = ""
    source = "analysis.buildable_area"
    if parcel_id:
        try:
            from app.analysis.buildable_area import buildable_area as buildable_fn
            analysis = await buildable_fn(str(parcel_id), pool=pool)
            buildable = analysis.value
            explanation = analysis.explanation or ""
        except Exception as e:
            log.debug("buildable_area analyser failed: %s", e)

    if buildable is None:
        # Fallback to metadata.buildable_ha or a conservative 70% rule
        buildable = design.get("buildable_ha")
        if buildable is None and site_area > 0:
            buildable = round(site_area * 0.70, 2)
            explanation = f"Parcel area {site_area:.1f} ha × 70% heuristic (no designation data)"
            source = "heuristic (70% of site_area_ha)"
        elif buildable is not None:
            explanation = f"From project metadata.design.buildable_ha = {buildable:.2f}"

    if buildable is None:
        return _unknown_kpi("buildable_ha", label, "ha",
                            source, "no parcel or site_area_ha on project")

    area_ref = site_area if site_area > 0 else float(buildable)
    pct = (float(buildable) / area_ref * 100.0) if area_ref > 0 else 0.0
    thr = THRESHOLDS["buildable_pct"]
    verdict = _verdict_higher_better(pct, thr["green"], thr["amber"])
    unit = f"of {area_ref:.1f} ha" if area_ref > 0 else "ha"
    return _kpi("buildable_ha", label, round(float(buildable), 2), unit,
                verdict, source, explanation or f"{pct:.0f}% of site buildable")


async def _kpi_connection_cost_p50(proj: dict, sub: dict | None) -> dict[str, Any]:
    label = "Connection Cost P50"
    if sub is None:
        return _unknown_kpi("connection_cost_p50", label, "£m",
                            "grid_connection_analyser",
                            "no substation identified")
    try:
        from utils.grid_connection_analyser import estimate_connection_cost
        est = estimate_connection_cost(
            distance_km=float(sub.get("dist_km") or 0.0),
            capacity_mw=float(proj.get("capacity_mw") or 0.0),
            voltage_kv=float(sub.get("voltage_kv") or 33.0),
        )
    except Exception as e:
        return _unknown_kpi("connection_cost_p50", label, "£m",
                            "grid_connection_analyser",
                            f"{type(e).__name__}: {e}")

    p50 = float(est["cost_gbp"]["p50"]) / 1_000_000.0
    thr = THRESHOLDS["connection_cost_p50_m"]
    verdict = _verdict_lower_better(p50, thr["green"], thr["amber"])
    p10 = float(est["cost_gbp"]["p10"]) / 1_000_000.0
    p90 = float(est["cost_gbp"]["p90"]) / 1_000_000.0
    explanation = (f"P10 £{p10:.2f}m / P50 £{p50:.2f}m / P90 £{p90:.2f}m — "
                   f"{sub.get('dist_km', 0):.1f} km at {int(sub.get('voltage_kv') or 33)} kV")
    return _kpi("connection_cost_p50", label, round(p50, 2), "£m",
                verdict, "grid_connection_analyser (UK DNO rates)", explanation)


async def _kpi_queue_position(pool, sub: dict | None) -> dict[str, Any]:
    label = "Queue Position"
    if sub is None or sub.get("id") is None:
        return _unknown_kpi("queue_position", label, "ahead",
                            "queue_depth",
                            "substation has no id in grid_substations table")
    try:
        from utils.queue_depth import queue_depth_for_substation
        async with pool.acquire() as conn:
            qd = await queue_depth_for_substation(conn, sub["id"])
    except Exception as e:
        return _unknown_kpi("queue_position", label, "ahead",
                            "queue_depth",
                            f"{type(e).__name__}: {e}")

    if qd.get("error"):
        return _unknown_kpi("queue_position", label, "ahead",
                            "queue_depth", qd["error"])
    ahead = qd.get("ahead_in_queue_count")
    if ahead is None:
        ahead = qd.get("queue_total_count")
    if ahead is None:
        return _unknown_kpi("queue_position", label, "ahead",
                            "queue_depth", "no queue data returned")
    ahead_int = int(ahead)
    thr = THRESHOLDS["queue_position"]
    verdict = _verdict_lower_better(ahead_int, thr["green"], thr["amber"])
    viable = qd.get("earliest_viable_year")
    queued_mw = qd.get("queue_total_mw")
    explanation_bits = [f"{ahead_int} projects ahead at {sub['name']}"]
    if queued_mw is not None:
        explanation_bits.append(f"{queued_mw:.1f} MW queued")
    if viable:
        explanation_bits.append(f"earliest viable {viable}")
    return _kpi("queue_position", label, ahead_int, "ahead",
                verdict, "queue_depth (grid_ecr + TEC + NESO live)",
                "; ".join(explanation_bits))


async def _kpi_verdict(proj: dict) -> dict[str, Any]:
    label = "Verdict"
    v = proj.get("verdict")
    if not v:
        return _unknown_kpi("verdict", label, None, "agent.py", "no verdict persisted on project")
    v_norm = str(v).upper().strip().replace("_", "-")
    if v_norm not in ("GO", "CAUTION", "NO-GO"):
        v_norm = "CAUTION"
    return _kpi("verdict", label, v_norm, None, _verdict_from_agent(v_norm),
                "agent.py (structured verdict)",
                f"Persisted project verdict: {v_norm}")


async def _kpi_revenue_p50(pool, proj: dict, design_kpis: dict | None) -> dict[str, Any]:
    label = "Revenue P50"
    # First: prefer the latest design_layouts.kpis if it has a revenue figure
    if design_kpis:
        rev = (design_kpis.get("revenue_p50_gbp_m")
               or design_kpis.get("annual_revenue_gbp_m")
               or design_kpis.get("revenue_year1_gbp_m"))
        if rev is not None:
            val = round(float(rev), 2)
            thr = THRESHOLDS["revenue_p50_m"]
            verdict = _verdict_higher_better(val, thr["green"], thr["amber"])
            return _kpi("revenue_p50", label, val, "£m/yr", verdict,
                        "design_layouts.kpis", f"From latest design run: £{val:.2f}m/yr")

    # Fallback: capacity × capacity_factor × price from metadata.design
    meta = proj.get("metadata") or {}
    design = dict(meta.get("design") or {})
    cap_mw = float(design.get("solar_mw") or proj.get("capacity_mw") or 0.0)
    ppa_price = float(design.get("ppa_price_gbp_mwh") or 68.0)
    if cap_mw <= 0:
        return _unknown_kpi("revenue_p50", label, "£m/yr",
                            "dcf_evaluator",
                            "no capacity on project")
    # UK central-England typical capacity factor ~11%
    cf = 0.11 if (proj.get("technology") or "solar").lower() == "solar" else 0.35
    annual_mwh = cap_mw * 8760.0 * cf
    rev_m = round(annual_mwh * ppa_price / 1_000_000.0, 2)
    thr = THRESHOLDS["revenue_p50_m"]
    verdict = _verdict_higher_better(rev_m, thr["green"], thr["amber"])
    explanation = (f"{cap_mw:.1f} MW × {cf*100:.0f}% CF × £{ppa_price:.0f}/MWh "
                   f"= £{rev_m:.2f}m/yr (P50 estimate)")
    return _kpi("revenue_p50", label, rev_m, "£m/yr", verdict,
                "dcf_evaluator (analytical CF × PPA)", explanation)


async def _kpi_lcoe(pool, proj: dict, design_kpis: dict | None) -> dict[str, Any]:
    label = "LCOE"
    # Prefer design_layouts kpi if present
    if design_kpis:
        lc = (design_kpis.get("lcoe_gbp_per_mwh")
              or design_kpis.get("lcoe_gbp_mwh")
              or design_kpis.get("lcoe"))
        if lc is not None:
            val = round(float(lc), 1)
            thr = THRESHOLDS["lcoe_gbp_mwh"]
            verdict = _verdict_lower_better(val, thr["green"], thr["amber"])
            return _kpi("lcoe", label, val, "£/MWh", verdict,
                        "design_layouts.kpis",
                        f"From latest design run: £{val:.1f}/MWh")

    # Fallback: run the analytical LCOE util with project defaults
    meta = proj.get("metadata") or {}
    design = dict(meta.get("design") or {})
    cap_mw = float(design.get("solar_mw") or proj.get("capacity_mw") or 0.0)
    if cap_mw <= 0:
        return _unknown_kpi("lcoe", label, "£/MWh",
                            "utils/lcoe",
                            "no capacity on project")
    try:
        from utils.lcoe import compute_lcoe
        # UK solar — ~£700/kW installed, ~£15/kW/yr opex, 25yr life, ~11% CF
        tech = (proj.get("technology") or "solar").lower()
        if tech == "solar":
            capex_per_kw = 700.0
            opex_per_kw_yr = 15.0
            cf = 0.11
            life = 25
        elif tech in ("bess", "battery"):
            capex_per_kw = 500.0
            opex_per_kw_yr = 10.0
            cf = 0.20  # effective; crude
            life = 15
        else:
            capex_per_kw = 800.0
            opex_per_kw_yr = 18.0
            cf = 0.12
            life = 25
        capex_gbp = cap_mw * 1000.0 * capex_per_kw
        opex_annual = cap_mw * 1000.0 * opex_per_kw_yr
        annual_mwh = cap_mw * 8760.0 * cf
        result = compute_lcoe(
            capex_gbp=capex_gbp,
            opex_schedule_gbp=[opex_annual] * life,
            annual_generation_mwh=annual_mwh,
            discount_rate=0.07,
            lifetime_years=life,
        )
        val = float(result.outputs["lcoe_gbp_per_mwh"])
    except Exception as e:
        return _unknown_kpi("lcoe", label, "£/MWh",
                            "utils/lcoe",
                            f"{type(e).__name__}: {e}")
    val_r = round(val, 1)
    thr = THRESHOLDS["lcoe_gbp_mwh"]
    verdict = _verdict_lower_better(val_r, thr["green"], thr["amber"])
    explanation = (f"LCOE {val_r} £/MWh from £{capex_per_kw:.0f}/kW capex, "
                   f"£{opex_per_kw_yr:.0f}/kW/yr opex, {cf*100:.0f}% CF, "
                   f"{life}y life, 7% discount")
    return _kpi("lcoe", label, val_r, "£/MWh", verdict,
                "utils/lcoe (analytical)", explanation)


# ─── Public entry ──────────────────────────────────────────────────────────

async def compose_project_kpis(pool, project_id: str) -> dict[str, Any]:
    """Compose the 8-KPI structured score for a project.

    Never raises for a single KPI failure — every KPI returns a dict with a
    verdict, and failures are surfaced as verdict='unknown' with the reason
    in `explanation`.
    """
    try:
        pid = UUID(project_id)
    except ValueError:
        return {
            "project_id": project_id,
            "computed_utc": datetime.now(timezone.utc).isoformat(),
            "kpis": [],
            "error": "invalid project_id uuid",
        }

    async with pool.acquire() as conn:
        proj = await _load_project(conn, pid)
        if not proj:
            return {
                "project_id": project_id,
                "computed_utc": datetime.now(timezone.utc).isoformat(),
                "kpis": [],
                "error": f"project {project_id} not found",
            }
        design_kpis = await _latest_design_kpis(conn, pid)
        sub = await _nearest_substation(conn, proj["lat"], proj["lon"])

    # Run KPIs concurrently where independent
    grid_kpi_task = _kpi_grid_viability(pool, proj, sub)
    planning_kpi_task = _kpi_planning_likelihood(pool, proj)
    buildable_kpi_task = _kpi_buildable_ha(pool, proj)
    cost_kpi_task = _kpi_connection_cost_p50(proj, sub)
    queue_kpi_task = _kpi_queue_position(pool, sub)
    verdict_kpi_task = _kpi_verdict(proj)
    revenue_kpi_task = _kpi_revenue_p50(pool, proj, design_kpis)
    lcoe_kpi_task = _kpi_lcoe(pool, proj, design_kpis)

    results = await asyncio.gather(
        grid_kpi_task, planning_kpi_task, buildable_kpi_task, cost_kpi_task,
        queue_kpi_task, verdict_kpi_task, revenue_kpi_task, lcoe_kpi_task,
        return_exceptions=True,
    )
    kpis: list[dict[str, Any]] = []
    labels = [
        ("grid_viability", "Grid Viability", "/100"),
        ("planning_likelihood", "Planning Likelihood", "%"),
        ("buildable_ha", "Buildable", "ha"),
        ("connection_cost_p50", "Connection Cost P50", "£m"),
        ("queue_position", "Queue Position", "ahead"),
        ("verdict", "Verdict", None),
        ("revenue_p50", "Revenue P50", "£m/yr"),
        ("lcoe", "LCOE", "£/MWh"),
    ]
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            kpi_id, kpi_label, kpi_unit = labels[idx]
            log.warning("KPI %s raised: %s", kpi_id, res)
            kpis.append(_unknown_kpi(
                kpi_id, kpi_label, kpi_unit, f"compose:{kpi_id}",
                f"exception {type(res).__name__}: {res}",
            ))
        else:
            kpis.append(res)

    return {
        "project_id": project_id,
        "computed_utc": datetime.now(timezone.utc).isoformat(),
        "kpis": kpis,
    }
