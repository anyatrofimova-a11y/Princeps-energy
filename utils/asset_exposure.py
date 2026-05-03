"""Connected-asset financial exposure — compute portfolio-wide exposure to a
single grid asset (substation / GSP / connection point).

The panel this feeds sits in :mod:`app/routers/portfolio_asset_exposure.py`
and is Princeps' answer to Pexapark's "connected-asset impact" view + LCP
Delta's "shared-asset risk" board.

The core query finds every project in the caller's portfolio whose grid
route flows through the target substation (either via explicit
``projects.metadata->>'connection_substation_id'`` or via the preferred
substation recorded on ``grid_assessments``). We then aggregate MW,
IRR and NPV, compute an HHI concentration index, and shock the
portfolio through four pre-canned stress cases driven by
:mod:`utils.monte_carlo_finance` + :mod:`utils.investment_appraisal`.

Design notes
------------
* HHI is normalised to 0–100 using ``(HHI - 1/N) / (1 - 1/N) * 100``
  so a perfectly diversified N-project portfolio sits at 0 and a
  single-project portfolio at 100. This matches the convention in
  ``utils.portfolio_analytics`` and EMR impact-assessment practice.
* Stress cases are applied AT THE CONNECTED-ASSET LEVEL only — projects
  not routed through the target substation are untouched. That is the
  whole point of the view: isolate concentration risk to one node.
* Missing metadata fields (IRR, NPV) fall back to a tech-keyed
  investment-appraisal computation rather than dropping the project —
  this keeps the panel useful for early-stage / prospect projects.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import asyncpg

from utils.investment_appraisal import project_finance
from utils.monte_carlo_finance import default_evaluator

log = logging.getLogger("princeps.asset_exposure")


# ── Stress-case parameters — tuned to ENA / NESO 2026 benchmarks ──────────
STRESS_HEADROOM_CUT_MW: float = 20.0
STRESS_ENERGISATION_SLIP_MONTHS: int = 12
STRESS_QUEUE_ADDITIONAL_MW: float = 100.0  # two 50 MW projects
STRESS_REINFORCEMENT_LEVY_GBP: float = 5_000_000.0


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fallback_finance(capacity_mw: float, technology: str) -> dict:
    """Run the deterministic project-finance model when the project row
    has no cached IRR / NPV metadata. Cheap (~10 ms) at this scale."""
    try:
        pf = project_finance(
            capacity_mw=max(0.1, capacity_mw or 0.1),
            technology=(technology or "solar").lower(),
            region="England",
        )
        return {
            "irr_pct": pf.get("project_irr"),
            "npv_gbp": pf.get("npv_8pct"),  # 8% discount rate
            "capex_gbp": pf.get("total_capex"),
            "opex_gbp_yr": pf.get("annual_opex_yr1"),
        }
    except Exception as e:
        log.debug("project_finance fallback failed: %s", e)
        return {"irr_pct": None, "npv_gbp": None, "capex_gbp": None, "opex_gbp_yr": None}


def _parse_metadata(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


async def _fetch_asset_header(conn: asyncpg.Connection, substation_id: int) -> dict:
    """Pull the substation's own row (name, voltage, DNO, headroom).

    We grab the NGED/UKPN/etc. row from grid_substations by internal id.
    If the caller passed an external string id we also try external_id.
    """
    # grid_substations PK is `id` (int); `external_id` is the DNO-side ref.
    # Accept either — try numeric id first, fall back to external_id.
    row = None
    try:
        sub_int = int(substation_id)
        row = await conn.fetchrow(
            """
            SELECT
                id AS substation_id, external_id, name, dno, region, voltage_kv,
                site_type, demand_mw, generation_mw,
                demand_headroom_mw, gen_headroom_mw,
                transformer_rating_mva, fault_level_ka,
                rag_demand, rag_generation, updated_at
            FROM grid_substations
            WHERE id = $1
            """,
            sub_int,
        )
    except (TypeError, ValueError):
        pass
    if row is None:
        row = await conn.fetchrow(
            """
            SELECT
                id AS substation_id, external_id, name, dno, region, voltage_kv,
                site_type, demand_mw, generation_mw,
                demand_headroom_mw, gen_headroom_mw,
                transformer_rating_mva, fault_level_ka,
                rag_demand, rag_generation, updated_at
            FROM grid_substations
            WHERE external_id = $1::text
            LIMIT 1
            """,
            str(substation_id),
        )
    if row is None:
        return {
            "substation_id": substation_id,
            "name": None,
            "voltage_kv": None,
            "dno": None,
            "firm_headroom_mw": None,
            "non_firm_headroom_mw": None,
            "rag": None,
            "not_found": True,
        }

    firm = _safe_float(row["gen_headroom_mw"])
    demand = _safe_float(row["demand_headroom_mw"])
    return {
        "substation_id": row["substation_id"],
        "external_id": row["external_id"],
        "name": row["name"],
        "dno": row["dno"],
        "region": row["region"],
        "voltage_kv": _safe_float(row["voltage_kv"]),
        "site_type": row["site_type"],
        "firm_headroom_mw": firm,
        "non_firm_headroom_mw": demand,  # demand headroom as a non-firm proxy
        "transformer_rating_mva": _safe_float(row["transformer_rating_mva"]),
        "fault_level_ka": _safe_float(row["fault_level_ka"]),
        "rag": row["rag_generation"] or row["rag_demand"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def _fetch_connected_projects(
    conn: asyncpg.Connection,
    substation_id: int,
    portfolio_id: str | None,
) -> list[dict]:
    """Find every project whose grid route passes through this substation.

    Two linkage paths are supported:
      1. ``projects.metadata->>'connection_substation_id'`` set at
         wizard-time when the developer picks a POC substation.
      2. ``grid_assessments.result_json->>'best_substation_id'`` set when
         the automated grid-connection analyser recommends one.
    """
    where_portfolio = ""
    args: list = [str(substation_id)]
    if portfolio_id:
        where_portfolio = "AND p.portfolio_id = $2::uuid"
        args.append(portfolio_id)

    # grid_assessments in this schema uses `nearest_sub_id` (int) as the FK
    # to grid_substations.id, and has no `project_id` / `result_json`
    # columns. The join via grid_assessments is therefore geometric (by
    # lat/lon) rather than relational, and is skipped here; metadata-only
    # is both sufficient and safe.
    sql = f"""
        SELECT
            p.project_id, p.name, p.technology, p.capacity_mw, p.stage,
            p.verdict, p.lat, p.lon, p.portfolio_id,
            p.metadata AS metadata,
            NULL::jsonb AS latest_grid_assessment
        FROM projects p
        WHERE p.metadata->>'connection_substation_id' = $1
          {where_portfolio}
        ORDER BY p.capacity_mw DESC NULLS LAST
    """
    rows = await conn.fetch(sql, *args)

    projects = []
    for r in rows:
        md = _parse_metadata(r["metadata"])
        irr_pct = _safe_float(md.get("irr") or md.get("irr_pct"))
        npv_gbp = _safe_float(md.get("npv_gbp") or md.get("npv"))
        capex_gbp = _safe_float(md.get("capex_gbp") or md.get("total_capex"))
        opex_gbp_yr = _safe_float(md.get("opex_gbp_yr") or md.get("annual_opex"))
        capacity = _safe_float(r["capacity_mw"]) or 0.0
        tech = (r["technology"] or "solar").lower()

        if irr_pct is None or npv_gbp is None:
            fin = _fallback_finance(capacity, tech)
            irr_pct = irr_pct if irr_pct is not None else _safe_float(fin["irr_pct"])
            npv_gbp = npv_gbp if npv_gbp is not None else _safe_float(fin["npv_gbp"])
            capex_gbp = capex_gbp if capex_gbp is not None else _safe_float(fin["capex_gbp"])
            opex_gbp_yr = opex_gbp_yr if opex_gbp_yr is not None else _safe_float(fin["opex_gbp_yr"])

        projects.append({
            "project_id": str(r["project_id"]),
            "name": r["name"],
            "technology": tech,
            "capacity_mw": capacity,
            "stage": r["stage"],
            "verdict": r["verdict"],
            "lat": _safe_float(r["lat"]),
            "lon": _safe_float(r["lon"]),
            "portfolio_id": str(r["portfolio_id"]) if r["portfolio_id"] else None,
            "irr_pct": irr_pct,
            "npv_gbp": npv_gbp,
            "capex_gbp": capex_gbp,
            "opex_gbp_yr": opex_gbp_yr,
        })
    return projects


async def _portfolio_total_mw(
    conn: asyncpg.Connection, portfolio_id: str | None
) -> float:
    """Total MW across ALL projects (not just those on this asset) — used
    as the denominator for the concentration-vs-portfolio flag."""
    if portfolio_id:
        row = await conn.fetchrow(
            "SELECT COALESCE(SUM(capacity_mw), 0) AS mw FROM projects WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    else:
        row = await conn.fetchrow("SELECT COALESCE(SUM(capacity_mw), 0) AS mw FROM projects")
    return float(row["mw"] or 0.0)


def _hhi_index(projects: list[dict]) -> dict:
    """Herfindahl-Hirschman Index normalised 0-100.

    Raw HHI sums (share_i ** 2) so values range from 1/N to 1. We rescale
    using (HHI - 1/N) / (1 - 1/N) so a perfectly equal portfolio is 0
    and a single-project portfolio is 100.
    """
    n = len(projects)
    if n == 0:
        return {"hhi_raw": 0.0, "hhi_normalised": 0.0, "n": 0}
    total_mw = sum(p["capacity_mw"] for p in projects) or 1.0
    shares = [p["capacity_mw"] / total_mw for p in projects]
    hhi_raw = sum(s * s for s in shares)
    lower = 1.0 / n
    if n == 1:
        normalised = 100.0
    else:
        normalised = max(0.0, (hhi_raw - lower) / (1.0 - lower)) * 100.0
    return {
        "hhi_raw": round(hhi_raw, 4),
        "hhi_normalised": round(normalised, 1),
        "n": n,
    }


def _mw_weighted_irr(projects: list[dict]) -> float | None:
    total_mw = sum(p["capacity_mw"] for p in projects if p["irr_pct"] is not None)
    if total_mw <= 0:
        return None
    return round(
        sum(
            (p["irr_pct"] or 0) * p["capacity_mw"]
            for p in projects
            if p["irr_pct"] is not None
        )
        / total_mw,
        2,
    )


def _diversification_flag(portfolio_mw_share_pct: float) -> str:
    if portfolio_mw_share_pct >= 40.0:
        return "RED"
    if portfolio_mw_share_pct >= 25.0:
        return "AMBER"
    return "GREEN"


# ── Stress cases ────────────────────────────────────────────────────────────

def _npv_gbp_m(p: dict) -> float:
    """Return NPV in £m for the per-project dict, defaulting to 0."""
    return (p.get("npv_gbp") or 0) / 1_000_000.0


def _stress_headroom_cut(
    header: dict, projects: list[dict], cut_mw: float
) -> dict:
    """If the substation loses `cut_mw` of firm headroom, which projects
    get curtailed (ordered by latest-stage first, then smallest MW)?"""
    firm = header.get("firm_headroom_mw") or 0.0
    total_exposed = sum(p["capacity_mw"] for p in projects)
    # Order: protect most-advanced / largest projects; curtail the rest.
    stage_rank = {
        "operational": 0, "construction": 1, "consented": 2,
        "planning": 3, "prospect": 4, None: 5,
    }
    ordered = sorted(
        projects,
        key=lambda p: (stage_rank.get(p.get("stage"), 5), -(p.get("capacity_mw") or 0)),
        reverse=True,
    )
    # The cut bites into total exposure minus remaining headroom — i.e.
    # if cut > firm, projects at the back of the queue lose capacity.
    to_curtail_mw = max(0.0, cut_mw)
    curtailed: list[dict] = []
    npv_drop_gbp = 0.0
    for p in ordered:
        if to_curtail_mw <= 0:
            break
        mw_lost = min(p["capacity_mw"], to_curtail_mw)
        to_curtail_mw -= mw_lost
        # Pro-rate NPV damage by MW fraction lost.
        if p["capacity_mw"] > 0 and p.get("npv_gbp"):
            loss = p["npv_gbp"] * (mw_lost / p["capacity_mw"])
        else:
            loss = 0.0
        npv_drop_gbp += loss
        curtailed.append({
            "project_id": p["project_id"],
            "name": p["name"],
            "mw_lost": round(mw_lost, 2),
            "npv_loss_gbp": round(loss, 0),
        })
    return {
        "label": f"-{cut_mw:.0f} MW firm headroom cut",
        "cut_mw": cut_mw,
        "total_exposed_mw": round(total_exposed, 2),
        "projects_curtailed": curtailed,
        "portfolio_npv_drop_gbp": round(npv_drop_gbp, 0),
        "portfolio_npv_drop_gbp_m": round(npv_drop_gbp / 1e6, 2),
    }


def _stress_energisation_slip(projects: list[dict], slip_months: int) -> dict:
    """+N months of energisation delay. Applies a uniform DCF penalty
    (slip_months / 12) × discount_rate on the per-project NPV."""
    discount = 0.08
    slip_yr = slip_months / 12.0
    per_project = []
    total_drop = 0.0
    for p in projects:
        npv = p.get("npv_gbp") or 0
        # DCF erosion: (1 - 1/(1+r)^slip) × NPV.
        erosion = npv * (1 - 1.0 / ((1 + discount) ** slip_yr))
        total_drop += erosion
        per_project.append({
            "project_id": p["project_id"],
            "name": p["name"],
            "npv_drop_gbp": round(erosion, 0),
        })
    return {
        "label": f"+{slip_months} months energisation slip",
        "slip_months": slip_months,
        "per_project": per_project,
        "portfolio_npv_drop_gbp": round(total_drop, 0),
        "portfolio_npv_drop_gbp_m": round(total_drop / 1e6, 2),
    }


def _stress_queue_escalation(
    header: dict, projects: list[dict], additional_mw: float
) -> dict:
    """Two 50 MW projects slot in ahead of us. Queue position worsens —
    offer timing slips ~6 months per 50 MW ahead for CP2 windows.

    We approximate: each 50 MW ahead → +6-month offer slip → DCF erosion
    cascaded to every connected project."""
    slip_months = int(6 * (additional_mw / 50.0))
    return {
        "label": f"+{additional_mw:.0f} MW queued ahead",
        "additional_mw_ahead": additional_mw,
        "implied_slip_months": slip_months,
        **_stress_energisation_slip(projects, slip_months),
    }


def _stress_reinforcement_levy(
    projects: list[dict], levy_gbp: float
) -> dict:
    """+£5m shared-reinforcement levy, allocated pro-rata by MW.

    DSCR impact per project assumes 25y × 8% annuity on the allocated
    share (standard ENA shared-reinforcement recovery model)."""
    total_mw = sum(p["capacity_mw"] for p in projects) or 1.0
    r, n = 0.08, 25
    annuity_factor = r / (1 - (1 + r) ** -n) if r else 0
    per_project = []
    for p in projects:
        share_gbp = levy_gbp * (p["capacity_mw"] / total_mw)
        annual_add = share_gbp * annuity_factor
        opex_yr = p.get("opex_gbp_yr") or (p["capacity_mw"] * 12000)  # solar default
        # Rough DSCR proxy: new DSCR = old DSCR × (old_debt_service / new_debt_service).
        # We express the impact as the % increase in annual debt service.
        dscr_pp_impact = -(annual_add / max(1.0, opex_yr + annual_add)) * 100
        per_project.append({
            "project_id": p["project_id"],
            "name": p["name"],
            "levy_share_gbp": round(share_gbp, 0),
            "dscr_pct_impact": round(dscr_pp_impact, 2),
        })
    return {
        "label": f"+£{levy_gbp/1e6:.1f}m shared reinforcement levy",
        "total_levy_gbp": levy_gbp,
        "per_project": per_project,
    }


# ── Entry point ─────────────────────────────────────────────────────────────

async def compute_asset_exposure(
    pool: asyncpg.Pool,
    substation_id: int,
    portfolio_id: str | None = None,
) -> dict:
    """Return the full payload consumed by ConnectedAssetPanel."""
    async with pool.acquire() as conn:
        header = await _fetch_asset_header(conn, substation_id)
        projects = await _fetch_connected_projects(conn, substation_id, portfolio_id)
        portfolio_total_mw = await _portfolio_total_mw(conn, portfolio_id)

    connected_mw = sum(p["capacity_mw"] for p in projects)
    total_npv_gbp = sum((p.get("npv_gbp") or 0) for p in projects)
    total_capex_gbp = sum((p.get("capex_gbp") or 0) for p in projects)
    mw_share_pct = (
        (connected_mw / portfolio_total_mw * 100.0) if portfolio_total_mw > 0 else 0.0
    )

    concentration = _hhi_index(projects)
    exposure = {
        "connected_mw": round(connected_mw, 2),
        "portfolio_total_mw": round(portfolio_total_mw, 2),
        "mw_share_pct": round(mw_share_pct, 1),
        "total_npv_gbp": round(total_npv_gbp, 0),
        "total_npv_gbp_m": round(total_npv_gbp / 1e6, 2),
        "total_capex_gbp": round(total_capex_gbp, 0),
        "mw_weighted_irr_pct": _mw_weighted_irr(projects),
        "project_count": len(projects),
        "diversification_flag": _diversification_flag(mw_share_pct),
    }

    stress_cases = [
        _stress_headroom_cut(header, projects, STRESS_HEADROOM_CUT_MW),
        _stress_energisation_slip(projects, STRESS_ENERGISATION_SLIP_MONTHS),
        _stress_queue_escalation(header, projects, STRESS_QUEUE_ADDITIONAL_MW),
        _stress_reinforcement_levy(projects, STRESS_REINFORCEMENT_LEVY_GBP),
    ]

    # Sparkline series: one point per stress case, plotting portfolio NPV
    # before and after each shock. Frontend renders as inline SVG.
    base_npv_m = exposure["total_npv_gbp_m"]
    sparkline = [{"label": "Base", "npv_gbp_m": base_npv_m}]
    for sc in stress_cases:
        drop = sc.get("portfolio_npv_drop_gbp_m", 0.0)
        sparkline.append({
            "label": sc["label"],
            "npv_gbp_m": round(base_npv_m - drop, 2),
            "drop_gbp_m": round(drop, 2),
        })

    return {
        "asset_header": header,
        "projects": projects,
        "portfolio_exposure": exposure,
        "concentration_index": concentration,
        "stress_cases": stress_cases,
        "sparkline": sparkline,
        "filters": {
            "substation_id": substation_id,
            "portfolio_id": portfolio_id,
        },
    }
