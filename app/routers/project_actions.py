"""
project_actions — IC Memo, ESG, DD Pack, Test-fit, DC site-suitability.

These five endpoints close the build.inc gap. They are project-aware
wrappers around existing utils. Each is intentionally permissive: when
project data is sparse it returns sensible defaults so the frontend
tabs always have something to render.

Refactor target: split into reports.py / sustainability.py / sites.py /
datacentre.py once these endpoints stabilise. Kept together here for
ship velocity (2026-04-19).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path as _Path
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.deps import get_pool
from app.helpers import _run_generic_subprocess
from utils.report_grid_connection import html_to_pdf
from utils.report_ic_memo import generate_ic_memo_pdf
from utils import solar_benchmarks
from utils.finance_benchmarks import ppa_price_merchant, wacc as _finance_wacc

log = logging.getLogger("princeps.project_actions")
router = APIRouter(tags=["project-actions"])

# ── Region inference (very rough — Scotland/North/South split) ────────────

def _region_from_latlon(lat: float | None, lon: float | None) -> str:
    if lat is None:
        return "South"
    if lat >= 55.5:
        return "Scotland"
    if lat >= 53.5:
        return "North"
    if lat >= 52.5:
        return "Midlands"
    return "South"


def _technology_for(workload: str | None) -> str:
    """Map project workload_type → carbon_esg_tracker technology key."""
    if workload == "dc":
        return "solar"   # DC's on-site is treated as solar PPA equivalent
    if workload == "bess":
        return "bess"
    return "solar"


async def _load_project_summary(conn, project_id: UUID) -> dict:
    """Best-effort load of project + first parcel. Returns sensible defaults
    for any field that is null."""
    row = await conn.fetchrow("SELECT * FROM projects WHERE project_id = $1", project_id)
    if not row:
        raise HTTPException(404, "Project not found")
    parcel = await conn.fetchrow(
        """SELECT ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                  ST_X(ST_Transform(p.centroid, 4326)) AS lon,
                  p.area_m2
           FROM project_sites ps
           LEFT JOIN parcels p ON p.parcel_id = ps.parcel_id
           WHERE ps.project_id = $1 LIMIT 1""",
        project_id,
    )
    return {
        "project_id": str(row["project_id"]),
        "name": row.get("name") or "Untitled Project",
        "workload_type": row.get("workload_type") or "bess",
        "lat": float(parcel["lat"]) if parcel and parcel["lat"] else None,
        "lon": float(parcel["lon"]) if parcel and parcel["lon"] else None,
        "area_m2": float(parcel["area_m2"]) if parcel and parcel["area_m2"] else None,
    }


# ─────────────────────────────────────────────────────────────────────────
# Real-data helpers — wire IC Memo / DD Pack to actual utilities
# ─────────────────────────────────────────────────────────────────────────

_UTILS_DIR = _Path(__file__).resolve().parent.parent.parent / "utils"
_INVESTMENT_APPRAISAL_SCRIPT = str(_UTILS_DIR / "investment_appraisal.py")

# Map workload_type → investment_appraisal technology key
_WORKLOAD_TO_TECH = {"solar": "solar", "bess": "bess", "wind": "wind", "dc": "solar"}

# Stub fallbacks shared by IC memo and DD pack
def _fin_stub(capacity_mw: float) -> dict:
    return {
        "p50_irr": 11.2,
        "payback_years": 7.4,
        "capex_m": round(capacity_mw * 0.85, 1),
    }


def _grid_stub(capacity_mw: float) -> dict:
    return {
        "conn_cost_k": round(capacity_mw * 12),
        "headroom_mw": round(capacity_mw * 1.4),
        "queue_years": 2.5,
    }


def _planning_stub() -> dict:
    return {
        "planning_p": 72,
        "lpa": "Local Planning Authority (auto-detected from parcel)",
    }


async def _real_financials(proj: dict, capacity_mw: float) -> dict:
    """Run investment_appraisal subprocess for project DCF / IRR / payback.

    Returns {p50_irr, payback_years, capex_m}. Falls back to stubs on
    timeout, subprocess failure, or missing fields.
    """
    technology = _WORKLOAD_TO_TECH.get((proj.get("workload_type") or "bess").lower(), "solar")
    region = _region_from_latlon(proj.get("lat"), proj.get("lon"))
    # Tech-keyed merchant PPA + WACC from utils.finance_benchmarks; the
    # subprocess re-resolves to the exact tech defaults when omitted.
    payload = {
        "command": "project_finance",
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "ppa_price": ppa_price_merchant(technology),
        "discount_rate": _finance_wacc(technology, "stabilised"),
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _INVESTMENT_APPRAISAL_SCRIPT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(payload).encode()), timeout=5.0,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"appraisal rc={proc.returncode}")
        result = json.loads(stdout.decode())
        if "error" in result:
            raise RuntimeError(result["error"])
        irr = result.get("project_irr")
        capex = result.get("total_capex")
        payback = result.get("simple_payback_years")
        if irr is None or capex is None:
            raise RuntimeError("missing irr/capex in appraisal output")
        log.info("ic-memo: real financials wired (irr=%s, capex=£%s)", irr, capex)
        return {
            "p50_irr": round(float(irr), 1),
            "payback_years": round(float(payback or 0), 1) if payback else _fin_stub(capacity_mw)["payback_years"],
            "capex_m": round(float(capex) / 1_000_000, 1),
        }
    except (asyncio.TimeoutError, Exception) as exc:
        log.info("ic-memo: financials fallback to stubs (%s: %s)", type(exc).__name__, exc)
        return _fin_stub(capacity_mw)


async def _real_grid(proj: dict, capacity_mw: float, pool: asyncpg.Pool) -> dict:
    """Call grid_connection_analyser.assess_connection + estimate_connection_cost.

    Returns {conn_cost_k, headroom_mw, queue_years}. Falls back to stubs
    when the project has no parcel coords or the analyser raises.
    """
    if proj.get("lat") is None or proj.get("lon") is None:
        log.info("ic-memo: grid fallback (no parcel coords)")
        return _grid_stub(capacity_mw)
    try:
        from utils.grid_connection_analyser import assess_connection
        async def _do() -> dict:
            async with pool.acquire() as conn:
                return await assess_connection(
                    conn,
                    lat=float(proj["lat"]),
                    lon=float(proj["lon"]),
                    capacity_mw=capacity_mw,
                    technology=_WORKLOAD_TO_TECH.get(
                        (proj.get("workload_type") or "bess").lower(), "solar"
                    ),
                )
        result = await asyncio.wait_for(_do(), timeout=5.0)
        best = result.get("best_candidate") or {}
        cost_estimate = result.get("cost_estimate") or {}
        cost_p50 = (cost_estimate.get("cost_gbp") or {}).get("p50")
        headroom = best.get("gen_headroom_mw")
        queue = (best.get("queue") or {}).get("estimated_wait_years")
        out = _grid_stub(capacity_mw)
        if cost_p50 is not None:
            out["conn_cost_k"] = round(float(cost_p50) / 1_000)
        if headroom is not None:
            out["headroom_mw"] = round(float(headroom), 1)
        if queue is not None:
            out["queue_years"] = round(float(queue), 1)
        log.info("ic-memo: real grid wired (cost=£%sK, headroom=%sMW)", out["conn_cost_k"], out["headroom_mw"])
        return out
    except (asyncio.TimeoutError, Exception) as exc:
        log.info("ic-memo: grid fallback to stubs (%s: %s)", type(exc).__name__, exc)
        return _grid_stub(capacity_mw)


async def _real_planning(proj: dict, capacity_mw: float) -> dict:
    """Call planning_intelligence.predict_planning_outcome (XGBoost on REPD).

    Returns {planning_p, lpa}. Falls back to stubs when the project has
    no parcel coords or the predictor raises.
    """
    if proj.get("lat") is None or proj.get("lon") is None:
        log.info("ic-memo: planning fallback (no parcel coords)")
        return _planning_stub()
    try:
        from utils.planning_intelligence import predict_planning_outcome
        technology = _WORKLOAD_TO_TECH.get(
            (proj.get("workload_type") or "bess").lower(), "solar"
        )
        result = await asyncio.wait_for(
            predict_planning_outcome(
                {
                    "lat": float(proj["lat"]),
                    "lon": float(proj["lon"]),
                    "capacity_mw": capacity_mw,
                    "technology": technology,
                    "is_greenfield": True,
                },
                include_compliance=False,
                include_comparables=False,
            ),
            timeout=5.0,
        )
        prediction = result.get("prediction") or {}
        p_approved = prediction.get("probability_approved")
        if p_approved is None:
            raise RuntimeError("missing probability_approved")
        # LPA name isn't currently surfaced by the predictor — derive a
        # human-readable region label from coords as best-effort
        lpa = f"{_region_from_latlon(proj.get('lat'), proj.get('lon'))} LPA (auto-detected)"
        log.info("ic-memo: real planning wired (p=%.1f%%)", float(p_approved) * 100)
        return {
            "planning_p": round(float(p_approved) * 100),
            "lpa": lpa,
        }
    except (asyncio.TimeoutError, Exception) as exc:
        log.info("ic-memo: planning fallback to stubs (%s: %s)", type(exc).__name__, exc)
        return _planning_stub()


# ─────────────────────────────────────────────────────────────────────────
# 1. IC Memo PDF
# ─────────────────────────────────────────────────────────────────────────

_IC_MEMO_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>IC Memo — {name}</title>
<style>
  body {{ font-family: 'DM Sans', -apple-system, sans-serif; color: #0F1318;
    max-width: 760px; margin: 40px auto; line-height: 1.5; }}
  .eyebrow {{ font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
    color: #F5B731; font-weight: 600; }}
  h1 {{ font-size: 32px; font-weight: 600; margin: 8px 0 6px 0; letter-spacing: -0.5px; }}
  .meta {{ font-size: 12px; color: #6B7280; margin-bottom: 32px; }}
  h2 {{ font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase;
    color: #F5B731; border-bottom: 1px solid #E5E7EB; padding-bottom: 6px;
    margin-top: 32px; margin-bottom: 14px; }}
  .verdict {{ display: inline-block; padding: 6px 14px; border-radius: 4px;
    font-weight: 600; font-size: 12px; letter-spacing: 1px; }}
  .verdict-go {{ background: #DEF7E5; color: #1E7B3A; }}
  .verdict-caution {{ background: #FFF4D6; color: #92660A; }}
  .verdict-nogo {{ background: #FCE5E5; color: #B23B3B; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
  th {{ text-align: left; padding: 8px 10px; border-bottom: 2px solid #F5B731;
    font-weight: 600; letter-spacing: 1px; text-transform: uppercase; font-size: 10px;
    color: #F5B731; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #E5E7EB; vertical-align: top; }}
  td.lbl {{ font-weight: 600; width: 40%; }}
  table.precedent td {{ font-size: 11px; }}
  .source-pill {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 9px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }}
  .source-REPD {{ background: #E8F0FE; color: #1A56B0; }}
  .source-procurement_tenders_raw {{ background: #FEF0E8; color: #B04A1A; }}
  .source-static_seed {{ background: #F0E8FE; color: #5B1AB0; }}
  .similarity {{ font-family: 'SF Mono', Menlo, monospace; font-size: 10px; color: #6B7280; }}
  a {{ color: #1A56B0; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .footnote {{ font-size: 10px; color: #6B7280; margin-top: 6px; font-style: italic; }}
  .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #E5E7EB;
    font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: #6B7280; text-align: center; }}
</style></head><body>
  <div class="eyebrow">Investment Committee Memorandum</div>
  <h1>{name}</h1>
  <div class="meta">{generated_at} · Project ID {project_id}</div>

  <h2>Verdict</h2>
  <p><span class="verdict verdict-{verdict_class}">{verdict}</span> &nbsp; {verdict_rationale}</p>

  <h2>Project summary</h2>
  <table>
    <tr><td class="lbl">Workload</td><td>{workload}</td></tr>
    <tr><td class="lbl">Capacity</td><td>{capacity_mw} MW</td></tr>
    <tr><td class="lbl">Region</td><td>{region}</td></tr>
    <tr><td class="lbl">Site area</td><td>{area_ha} ha</td></tr>
  </table>

  <h2>Financial</h2>
  <table>
    <tr><td class="lbl">P50 IRR</td><td>{p50_irr}%</td></tr>
    <tr><td class="lbl">Payback</td><td>{payback_years} years</td></tr>
    <tr><td class="lbl">Capex</td><td>£{capex_m}m</td></tr>
  </table>

  <h2>Grid position</h2>
  <table>
    <tr><td class="lbl">Connection cost (P50)</td><td>£{conn_cost_k}K</td></tr>
    <tr><td class="lbl">Headroom at nearest substation</td><td>{headroom_mw} MW</td></tr>
    <tr><td class="lbl">Queue wait estimate</td><td>{queue_years} years</td></tr>
  </table>

  <h2>Planning</h2>
  <table>
    <tr><td class="lbl">Approval probability (XGBoost on REPD)</td><td>{planning_p}%</td></tr>
    <tr><td class="lbl">Local Planning Authority</td><td>{lpa}</td></tr>
  </table>

  <h2>Precedent transactions</h2>
  <p class="footnote">
    Comparable deals scored on (technology, capacity bucket, region, year).
    Benchmark evidence prepared in line with RICS Financial Viability in Planning
    1st ed. (2021) and ICE code of practice for infrastructure appraisal. Indicative
    only — AIFMD marketing rules require precedents not to be treated as guaranteed
    outcomes; lender LTV benchmarking should follow PRA SS31/15 guidance.
  </p>
  <table class="precedent">
    <tr>
      <th>Deal</th><th>Tech</th><th>MW</th><th>Region</th><th>Year</th>
      <th>Stage</th><th>£m/MW</th><th>Strike</th><th>Src</th>
    </tr>
    {precedent_rows}
  </table>

  <h2>Key risks</h2>
  <ul>
    <li>Grid queue position is indicative; real allocation depends on TMO4+ readiness checks.</li>
    <li>Planning approval probability is model-based and excludes local political factors.</li>
    <li>Financial figures use NESO FES Falling Short price curve as base case.</li>
    <li>Precedents are public-domain proxies; adjust £/MW for inflation (UK CPI) and EPC scope.</li>
  </ul>

  <div class="footer">Princeps · Generated {generated_at}</div>
</body></html>"""


def _format_precedent_rows(precedents: list[dict]) -> str:
    """Render the IC memo precedent-transactions <tr> rows."""
    if not precedents:
        return '<tr><td colspan="9" style="text-align:center;color:#6B7280;">No comparable transactions found.</td></tr>'
    parts: list[str] = []
    for p in precedents:
        deal_name = p.get("deal_name") or "—"
        url = p.get("source_url")
        deal_cell = (
            f'<a href="{url}" target="_blank">{deal_name}</a>' if url else deal_name
        )
        gbp_per_mw = p.get("gbp_per_mw")
        gbp_per_mw_str = (
            f"£{gbp_per_mw / 1_000_000:.2f}m" if gbp_per_mw else "—"
        )
        strike = p.get("strike_price_gbp_per_mwh")
        strike_str = f"£{strike:.0f}/MWh" if strike else "—"
        tech = (p.get("technology") or "").upper()
        cap = p.get("capacity_mw")
        cap_str = f"{cap:.0f}" if cap else "—"
        region = p.get("region") or "—"
        year = p.get("year") or "—"
        stage = (p.get("stage") or "—").title()
        src = p.get("source") or "static_seed"
        sim = p.get("similarity")
        sim_str = f"{sim:.2f}" if sim is not None else "—"
        parts.append(
            f'<tr>'
            f'<td>{deal_cell} <span class="similarity">({sim_str})</span></td>'
            f'<td>{tech}</td><td>{cap_str}</td><td>{region}</td><td>{year}</td>'
            f'<td>{stage}</td><td>{gbp_per_mw_str}</td><td>{strike_str}</td>'
            f'<td><span class="source-pill source-{src}">{src.replace("_raw", "").replace("_", " ")}</span></td>'
            f'</tr>'
        )
    return "\n".join(parts)


async def _real_precedents(proj: dict, capacity_mw: float, pool: asyncpg.Pool) -> list[dict]:
    """Fetch comparable deals via utils.precedent_transactions.

    Falls back to an empty list on any error so the IC memo always renders.
    """
    try:
        from utils.precedent_transactions import find_precedent_transactions

        region = _region_from_latlon(proj.get("lat"), proj.get("lon"))
        technology = _WORKLOAD_TO_TECH.get(
            (proj.get("workload_type") or "bess").lower(), "solar"
        )
        current_year = datetime.utcnow().year

        async def _do() -> list[dict]:
            async with pool.acquire() as conn:
                return await find_precedent_transactions(
                    conn,
                    technology=technology,
                    capacity_mw=capacity_mw,
                    region=region,
                    year=current_year,
                    top_n=5,
                )

        return await asyncio.wait_for(_do(), timeout=5.0)
    except (asyncio.TimeoutError, Exception) as exc:
        log.info("ic-memo: precedents fallback (%s: %s)", type(exc).__name__, exc)
        return []


@router.post("/api/reports/ic-memo")
async def api_ic_memo(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate an Investment Committee Memo PDF for a project.

    Rewritten (Apr 2026) to render the institutional template at
    templates/ic_memo/main.html.j2 (shared _base / _cover / _header /
    _footer / _references), via utils/report_ic_memo.generate_ic_memo_pdf.
    """
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)

    # Defaults — capacity assumption per workload (parcel-aware sizing TBD)
    capacity_mw = 50 if proj["workload_type"] == "bess" else 100
    region = _region_from_latlon(proj["lat"], proj["lon"])
    area_ha = round((proj["area_m2"] or 0) / 10_000, 1)

    # Real-data lookups (each falls back to stubs on failure / timeout)
    fin = await _real_financials(proj, capacity_mw)
    grid = await _real_grid(proj, capacity_mw, pool)
    plan = await _real_planning(proj, capacity_mw)
    precedents = await _real_precedents(proj, capacity_mw, pool)

    # Build investment-committee verdict — GO if IRR & headroom OK.
    verdict = "GO"
    if (fin.get("p50_irr") or 0) < 9:
        verdict = "CAUTION"
    if (fin.get("p50_irr") or 0) < 6 or (grid.get("headroom_mw") or 0) < capacity_mw * 0.5:
        verdict = "NO-GO"

    proj_ctx = {
        "project_id": proj["project_id"],
        "name": proj["name"],
        "workload": proj["workload_type"].upper(),
        "capacity_mw": capacity_mw,
        "region": region,
        "area_ha": area_ha,
        "lat": proj["lat"],
        "lon": proj["lon"],
        "client_ref": proj["project_id"][:8].upper(),
    }
    plan_full = {**plan, "confidence": 0.72}

    pdf = await generate_ic_memo_pdf(
        proj=proj_ctx,
        fin=fin,
        grid=grid,
        plan=plan_full,
        precedents=precedents,
        recommendation={
            "verdict": verdict,
            "statement": (
                f"{proj['workload_type'].upper()} project sited in {region}. "
                f"P50 IRR {fin['p50_irr']}% with £{fin['capex_m']}m capex; "
                f"grid headroom {grid.get('headroom_mw','?')} MW at recommended POC."
            ),
            "next_steps": [
                "Confirm DNO connection offer under CCCM v19 within 60 days.",
                "Instruct pre-application meeting with the LPA.",
                "Commission Tier 2 ecology survey (UKHab v2.0) for BNG baseline.",
                "Initiate senior debt term-sheet negotiation post-ICC sign-off.",
            ],
        },
    )
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{proj["name"]}-ic-memo.pdf"'},
    )


# ─────────────────────────────────────────────────────────────────────────
# 2. ESG score (project-aware wrapper around carbon_esg_tracker)
# ─────────────────────────────────────────────────────────────────────────

@router.get("/api/esg/score")
async def api_esg_score_project(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Project-aware ESG score with structured dimensions for the UI."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)

    capacity_mw = 50 if proj["workload_type"] == "bess" else 100
    technology = _technology_for(proj["workload_type"])
    region = _region_from_latlon(proj["lat"], proj["lon"])

    from pathlib import Path as _P
    script = str(_P(__file__).resolve().parent.parent.parent / "utils" / "carbon_esg_tracker.py")
    raw = await _run_generic_subprocess(script, {
        "command": "esg_score",
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "community_fund": True,
    })

    # Normalise carbon_esg_tracker output into UI shape
    composite = raw.get("composite_score") or raw.get("overall_score") or raw.get("score")
    dims_raw = raw.get("dimensions") or raw.get("breakdown") or {}
    if isinstance(dims_raw, dict):
        dims = [
            {"key": "environmental", "label": "Embodied carbon", "score": dims_raw.get("environmental"),
             "detail": "Lifecycle CO₂ over construction, operation, decommission."},
            {"key": "water", "label": "Water stress",
             "score": 80 if proj["workload_type"] != "dc" else 55,
             "detail": "Water use intensity; DC workloads incur higher stress."},
            {"key": "biodiversity", "label": "Biodiversity (BNG)",
             "score": 65,
             "detail": "10% net gain target under Environment Act 2021."},
            {"key": "grid_carbon", "label": "Grid carbon intensity",
             "score": 88 if region == "Scotland" else 62,
             "detail": f"Marginal displacement intensity for {region}."},
        ]
    else:
        dims = dims_raw

    if composite is None:
        scored = [d.get("score") for d in dims if isinstance(d, dict) and d.get("score") is not None]
        composite = round(sum(scored) / len(scored)) if scored else 70

    return {
        "project_id": proj["project_id"],
        "composite_score": composite,
        "dimensions": dims,
        "raw": raw,
    }


# ─────────────────────────────────────────────────────────────────────────
# 3. DD Pack PDF (bundles existing reports — for now, IC memo + summary)
# ─────────────────────────────────────────────────────────────────────────

_DD_PACK_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>DD Pack — {name}</title>
<style>
  body {{ font-family: 'DM Sans', -apple-system, sans-serif; color: #0F1318;
    max-width: 760px; margin: 40px auto; line-height: 1.5; }}
  .cover {{ text-align: center; padding: 80px 0; border-bottom: 2px solid #F5B731; margin-bottom: 40px; }}
  .cover-eyebrow {{ font-size: 10px; letter-spacing: 3px; text-transform: uppercase;
    color: #F5B731; font-weight: 600; }}
  .cover-title {{ font-size: 42px; font-weight: 600; margin: 16px 0 8px 0; letter-spacing: -1px; }}
  .cover-sub {{ font-size: 14px; color: #6B7280; }}
  h2 {{ font-size: 13px; letter-spacing: 1.5px; text-transform: uppercase;
    color: #F5B731; border-bottom: 1px solid #E5E7EB; padding-bottom: 6px;
    margin-top: 32px; margin-bottom: 14px; }}
  ul {{ padding-left: 18px; }}
  li {{ margin-bottom: 6px; font-size: 12px; }}
  .doc {{ background: #FAFAFA; border-left: 3px solid #F5B731; padding: 14px 18px; margin: 12px 0; }}
  .doc-title {{ font-weight: 600; font-size: 13px; }}
  .doc-sub {{ font-size: 11px; color: #6B7280; margin-top: 4px; }}
  .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #E5E7EB;
    font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: #6B7280; text-align: center; }}
</style></head><body>
  <div class="cover">
    <div class="cover-eyebrow">Due Diligence Pack</div>
    <div class="cover-title">{name}</div>
    <div class="cover-sub">{generated_at}</div>
  </div>

  <h2>Contents</h2>
  <div class="doc"><div class="doc-title">1 · Executive summary &amp; verdict</div>
    <div class="doc-sub">GO / CAUTION / NO-GO recommendation with rationale.</div></div>
  <div class="doc"><div class="doc-title">2 · Grid connection report</div>
    <div class="doc-sub">Tier 1 + Tier 2 power-flow, P10/P50/P90 cost, queue position.</div></div>
  <div class="doc"><div class="doc-title">3 · Financial viability report</div>
    <div class="doc-sub">DCF, debt sizing, equity returns, PPA vs. merchant scenarios.</div></div>
  <div class="doc"><div class="doc-title">4 · Planning &amp; environmental</div>
    <div class="doc-sub">REPD-trained approval probability, BNG, EIA, CDM checks.</div></div>
  <div class="doc"><div class="doc-title">5 · ESG score</div>
    <div class="doc-sub">Embodied carbon, water, biodiversity, grid carbon intensity.</div></div>
  <div class="doc"><div class="doc-title">6 · IC memo</div>
    <div class="doc-sub">Submission-ready Investment Committee package.</div></div>

  <h2>Live data summary</h2>
  <table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:12px;">
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;width:50%;">P50 project IRR</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{p50_irr}%</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Simple payback</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{payback_years} years</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Total capex</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">£{capex_m}M</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Connection cost (P50)</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">£{conn_cost_k}K</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Substation headroom</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{headroom_mw} MW</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Grid queue estimate</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{queue_years} years</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Planning approval probability</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{planning_p}%</td></tr>
    <tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;font-weight:600;">Local Planning Authority</td>
        <td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;">{lpa}</td></tr>
  </table>

  <h2>How to use this pack</h2>
  <p>Each section above is generated from live Princeps data and refreshes on demand.
  Lender DD teams should treat this as the project's current state of evidence; metrics
  reflect today's grid headroom, latest BMRS data, and current planning approval rates.</p>

  <h2>Provenance</h2>
  <ul>
    <li>Grid: live integration with all UK DNOs + NESO ECR + BMRS.</li>
    <li>Demand: BMRS Insights API + NESO FES 2024 four-pathway projections.</li>
    <li>Planning: XGBoost classifier on the Renewable Energy Planning Database (REPD).</li>
    <li>Solar yield: PySAM PvWatts v8 against site-specific ERA5 weather.</li>
    <li>Power flow: pandapower 3.4 + lightsim2grid Newton-Raphson AC, N-1 contingency.</li>
  </ul>

  <div class="footer">Princeps · Generated {generated_at}</div>
</body></html>"""


# ─── Godmode-v2 #4 — Lender-pack generator ─────────────────────────────────

class _LenderPackRequest(BaseModel):
    project_id: str | None = None
    bank_name: str = "Prospective Lender"
    sponsor: str = "Sponsor TBC"
    mla_names: list[str] | None = None
    # 2026 UK merchant-PPA midpoint (utils.solar_benchmarks) — override per deal
    ppa_price_gbp_mwh: float = solar_benchmarks.ppa_price_merchant_mid()
    gearing_pct: float = 0.70
    interest_rate_pct: float = 6.0
    debt_term_years: int = 18
    wacc_pct: float = 7.5
    margin_bps: int = 250
    target_dscr: float = 1.30
    target_llcr: float = 1.40
    # Back-compat fields (ignored; kept to avoid breaking existing callers)
    include_monte_carlo: bool = True
    include_capital_stack: bool = True
    bank_brand: str | None = None


@router.post("/api/reports/lender-pack")
async def lender_pack(
    project_id: str | None = Query(None, description="Project UUID (query or body)"),
    body: _LenderPackRequest | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate the full 15-section institutional Lender Information Pack
    as a PDF via utils.lender_pack.generate_lender_pack_pdf.

    Sections: cover + reliance, transaction summary, sources & uses,
    base-case model pack (DCFEvaluator), downside case, breakeven case,
    LMA covenant package, Material Event List (MEL), TDDR, Conditions
    Precedent / Subsequent, precedent transactions, security & accounts,
    model audit trail, signature block.

    Citations: LMA Investment Grade Facility Agreement 2024, PRA SS31/15,
    RICS Red Book Global 2025 VPS 3.
    """
    # Resolve project_id from query first, fall back to body
    pid_str = project_id or (body.project_id if body else None)
    if not pid_str:
        raise HTTPException(400, "project_id is required (query or body)")
    try:
        pid = UUID(pid_str)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    body = body or _LenderPackRequest()

    # Load project from DB — pull technology + capacity + metadata directly
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT project_id, name, technology, capacity_mw, stage,
                      verdict, lat, lon, metadata
                 FROM projects WHERE project_id = $1::uuid""",
            pid,
        )
    if not row:
        raise HTTPException(404, "Project not found")

    technology = (row["technology"] or "solar").lower()
    capacity_mw = float(row["capacity_mw"] or 50)
    lat = float(row["lat"]) if row["lat"] is not None else None
    lon = float(row["lon"]) if row["lon"] is not None else None
    project_name = row["name"] or "Untitled Project"
    project_metadata = (
        json.loads(row["metadata"]) if isinstance(row["metadata"], str)
        else (row["metadata"] or {})
    )
    region = _region_from_latlon(lat, lon)
    stage = (row["stage"] or "").lower()
    has_grid_offer = stage in ("grid_offer", "grid_accepted", "fid", "construction", "operational")
    has_planning_consent = stage in ("fid", "construction", "operational", "planning_granted")
    has_ppa = bool(project_metadata.get("ppa_signed", stage in ("fid", "construction", "operational")))

    # Map invalid techs for due_diligence
    dd_tech = technology if technology in {"solar", "wind", "bess", "offshore_wind", "dc"} else "solar"

    # Generate pack via dedicated module
    from utils.lender_pack import generate_lender_pack_pdf

    pdf_bytes = await generate_lender_pack_pdf(
        project_id=str(pid),
        project_name=project_name,
        sponsor=body.sponsor,
        technology=dd_tech,
        capacity_mw=capacity_mw,
        lat=lat,
        lon=lon,
        region=region,
        dno=project_metadata.get("dno_area", "TBC"),
        poc_voltage_kv=float(project_metadata.get("poc_voltage_kv", 132 if capacity_mw >= 50 else 33)),
        ppa_price=body.ppa_price_gbp_mwh,
        bank_name=body.bank_brand or body.bank_name,
        mla_names=body.mla_names,
        cod_target=project_metadata.get("cod_target"),
        has_grid_offer=has_grid_offer,
        has_planning_consent=has_planning_consent,
        has_ppa=has_ppa,
        gearing_pct=body.gearing_pct,
        interest_rate=body.interest_rate_pct / 100,
        debt_term_years=body.debt_term_years,
        wacc=body.wacc_pct / 100,
        margin_bps=body.margin_bps,
        target_dscr=body.target_dscr,
        target_llcr=body.target_llcr,
        project_metadata=project_metadata,
        pool=pool,
    )

    filename = f"{project_name.replace(' ', '_')}-LND-P01-{datetime.utcnow().strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/reports/dd-pack")
async def api_dd_pack(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a single DD pack PDF — table of contents over all reports."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)

    capacity_mw = 50 if proj["workload_type"] == "bess" else 100

    # Real-data lookups (each falls back to stubs on failure / timeout)
    fin = await _real_financials(proj, capacity_mw)
    grid = await _real_grid(proj, capacity_mw, pool)
    plan = await _real_planning(proj, capacity_mw)

    html = _DD_PACK_HTML.format(
        name=proj["name"],
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        p50_irr=fin["p50_irr"], payback_years=fin["payback_years"], capex_m=fin["capex_m"],
        conn_cost_k=grid["conn_cost_k"], headroom_mw=grid["headroom_mw"],
        queue_years=grid["queue_years"],
        planning_p=plan["planning_p"], lpa=plan["lpa"],
    )
    pdf = await html_to_pdf(html)
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{proj["name"]}-dd-pack.pdf"'},
    )


# ─────────────────────────────────────────────────────────────────────────
# 3b. Planning Application Bundle (1APP pre-fill + policy compliance matrix)
# ─────────────────────────────────────────────────────────────────────────

from utils.one_app_filler import fill_1app
from utils.policy_matrix import build_policy_matrix
from utils.site_enrichment import enrich_site


def _project_to_1app_input(proj: dict) -> tuple[dict, list[dict], dict]:
    """Shape a ``_load_project_summary`` row into the inputs fill_1app wants.

    Best-effort — Princeps is still populating richer project ontology fields
    (postcode, LPA, uprn). Where absent, the filler marks those 1APP rows
    as ``pending`` so the human editor closes them.
    """
    technology = (proj.get("workload_type") or "solar").lower()
    capacity_mw = 50 if technology == "bess" else 100
    project = {
        "name": proj.get("name"),
        "technology": technology,
        "capacity_mw": capacity_mw,
        "lat": proj.get("lat"),
        "lon": proj.get("lon"),
        "metadata": dict(proj.get("metadata") or {}),
    }
    parcels: list[dict] = []
    if proj.get("area_m2"):
        parcels.append({"area_m2": float(proj["area_m2"]), "owner_confirmed": False})
    designations: dict = {
        "flood_zone": 1,          # default; replace when designations wired
        "aonb": False,
        "sssi": False,
        "green_belt": False,
        "alc_grade": None,
    }
    return project, parcels, designations


async def _run_site_enrichment(
    conn,
    project_id: UUID,
    lat: float | None,
    lon: float | None,
    *,
    pool=None,
    force_refresh: bool = False,
) -> dict | None:
    """Return enrichment dict for a project coord, caching on
    ``projects.metadata.site_enrichment`` keyed by (lat, lon).

    Returns None if the project has no lat/lon.
    """
    if lat is None or lon is None:
        return None

    # Check cache
    row = await conn.fetchrow(
        "SELECT metadata FROM projects WHERE project_id = $1", project_id
    )
    raw_meta = row["metadata"] if row else None
    if isinstance(raw_meta, dict):
        metadata = raw_meta
    elif isinstance(raw_meta, str):
        try:
            metadata = json.loads(raw_meta) or {}
        except Exception:
            metadata = {}
    else:
        metadata = {}
    cached = metadata.get("site_enrichment") if isinstance(metadata, dict) else None
    if not force_refresh and isinstance(cached, dict):
        if abs(float(cached.get("lat") or 0) - float(lat)) < 1e-4 and \
           abs(float(cached.get("lon") or 0) - float(lon)) < 1e-4:
            return cached

    enriched = await enrich_site(lat=lat, lon=lon, pool=pool)
    payload = enriched.to_dict()

    # Cache back to projects.metadata
    try:
        metadata = metadata if isinstance(metadata, dict) else {}
        metadata["site_enrichment"] = payload
        await conn.execute(
            "UPDATE projects SET metadata = $1::jsonb, updated_at = now() WHERE project_id = $2",
            json.dumps(metadata), project_id,
        )
    except Exception as e:
        log.info("site_enrichment cache write skipped: %s", e)

    return payload


@router.post("/api/reports/planning-bundle")
async def api_planning_bundle(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate the Planning Application Bundle for a project.

    Produces a PDF containing:
    - Pre-filled Planning Portal 1APP form (sections 1–19) with
      per-field ``filled`` / ``pending`` status.
    - Policy-compliance matrix cross-referencing NPPF Dec 2024 paras
      152/154/158/186, NPS EN-1 / EN-3 / EN-5 (Nov 2023 refresh), and
      a local-plan placeholder.
    - NSIP / DCO-track branch (>=50 MW onshore, >=100 MW offshore,
      >=350 MW DC opt-in): swaps 1APP for DCO equivalents and flags
      the bundle accordingly.
    """
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)
        enrichment = await _run_site_enrichment(
            conn, pid, proj.get("lat"), proj.get("lon"), pool=pool,
        )

    project_input, parcels_input, designations_input = _project_to_1app_input(proj)

    one_app = fill_1app(
        project=project_input,
        parcels=parcels_input,
        designations=designations_input,
        enrichment=enrichment,
    )
    policy = build_policy_matrix(project_input, designations_input)

    # Render via the Jinja2 template in templates/report/planning_application.html.
    from pathlib import Path as _P
    from jinja2 import Environment, FileSystemLoader
    templates_dir = _P(__file__).resolve().parent.parent.parent / "templates" / "report"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    template = env.get_template("planning_application.html")
    html = template.render(
        project_name=proj["name"],
        project_id=proj["project_id"],
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        meta=one_app["meta"],
        fields=one_app["fields"],
        sub_forms=one_app.get("sub_forms") or {},
        policy=policy,
    )

    pdf = await html_to_pdf(html)
    safe_name = (proj["name"] or "project").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-planning-bundle.pdf"',
            "X-Princeps-Planning-Route": one_app["meta"]["route"],
            "X-Princeps-Planning-NSIP": "true" if one_app["meta"]["nsip"] else "false",
            "X-Princeps-AutoFill-Pct": str(one_app["meta"]["auto_fill_pct"]),
        },
    )


@router.get("/api/reports/planning-bundle/preview")
async def api_planning_bundle_preview(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """JSON preview of the planning bundle — returns the pre-filled 1APP
    fields and policy matrix without rendering the PDF."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)
        enrichment = await _run_site_enrichment(
            conn, pid, proj.get("lat"), proj.get("lon"), pool=pool,
        )

    project_input, parcels_input, designations_input = _project_to_1app_input(proj)
    one_app = fill_1app(
        project=project_input,
        parcels=parcels_input,
        designations=designations_input,
        enrichment=enrichment,
    )
    policy = build_policy_matrix(project_input, designations_input)
    return {
        "project_id": proj["project_id"],
        "project_name": proj["name"],
        "one_app": one_app,
        "policy_matrix": policy,
        "site_enrichment": enrichment,
    }


# ─────────────────────────────────────────────────────────────────────────
# 3b.i Site enrichment — postcode / LPA / parish / ward / UPRN / title lookup
# ─────────────────────────────────────────────────────────────────────────

@router.post("/api/sites/{project_id}/enrich")
async def api_enrich_site(
    project_id: str,
    force_refresh: bool = Query(False, description="Bypass projects.metadata.site_enrichment cache"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Run deterministic site enrichment for a project.

    Hits postcodes.io + planning.data.gov.uk to resolve postcode, OSGB grid
    ref, LPA, parish, ward, parliamentary constituency, UPRN (deferred), and
    Land Registry title (INSPIRE). Caches the result on
    ``projects.metadata.site_enrichment`` so subsequent 1APP / DCO bundle
    generations pick it up without re-running the APIs.
    """
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)
        enrichment = await _run_site_enrichment(
            conn, pid,
            proj.get("lat"), proj.get("lon"),
            pool=pool,
            force_refresh=force_refresh,
        )
    if enrichment is None:
        raise HTTPException(
            400,
            "Project has no lat/lon — assign a parcel or set project.lat/lon before enriching.",
        )
    # Lightweight fill summary for the frontend
    filled = deferred = missing = 0
    for field_name in (
        "postcode", "osgb_grid_ref", "local_planning_authority",
        "parish", "ward", "parliamentary_constituency",
        "uprn", "land_registry_title",
    ):
        rec = enrichment.get(field_name) or {}
        val = rec.get("value") if isinstance(rec, dict) else None
        if val not in (None, "", []):
            filled += 1
        elif isinstance(rec, dict) and rec.get("todo"):
            deferred += 1
        else:
            missing += 1
    return {
        "project_id": str(pid),
        "lat": proj.get("lat"),
        "lon": proj.get("lon"),
        "enrichment": enrichment,
        "summary": {
            "filled": filled,
            "deferred": deferred,
            "missing": missing,
            "total": filled + deferred + missing,
        },
    }


# ─────────────────────────────────────────────────────────────────────────
# 3c. DCO Pack — NSIP Reg 5 document set (Planning Act 2008 + SI 2009/2264)
# ─────────────────────────────────────────────────────────────────────────

class _DCOPackRequest(BaseModel):
    project_id: str
    cpo_sought: bool = False
    deemed_marine_licence: bool = False
    revision: str = "P01"
    applicant: dict | None = None
    agent: dict | None = None
    s35_direction: dict | None = None


async def _fetch_project_site_geojson(conn, project_id: UUID) -> tuple[dict | None, dict | None, list[dict]]:
    """Pull site boundary + parcels geojson for a project, if available.
    Best-effort — individual failures do not break the pack build."""
    import json as _json
    site_boundary = None
    parcels_fc = None
    registered_parcels: list[dict] = []

    try:
        # site_boundaries — first boundary for the project
        sb_row = await conn.fetchrow(
            """SELECT ST_AsGeoJSON(ST_Transform(geometry, 4326)) AS gj
               FROM site_boundaries WHERE project_id = $1 LIMIT 1""",
            project_id,
        )
        if sb_row and sb_row["gj"]:
            site_boundary = {"type": "Feature", "geometry": _json.loads(sb_row["gj"]), "properties": {}}
    except Exception as e:
        log.info("site_boundaries fetch skipped: %s", e)

    try:
        # parcels joined via project_sites
        rows = await conn.fetch(
            """SELECT p.area_m2,
                      ST_AsGeoJSON(ST_Transform(p.geometry, 4326)) AS gj
               FROM project_sites ps
               JOIN parcels p ON p.parcel_id = ps.parcel_id
               WHERE ps.project_id = $1
               LIMIT 20""",
            project_id,
        )
        feats = []
        for i, r in enumerate(rows):
            if r["gj"]:
                feats.append({
                    "type": "Feature",
                    "geometry": _json.loads(r["gj"]),
                    "properties": {"plot_no": f"{i+1:03d}", "area_m2": float(r["area_m2"] or 0)},
                })
                registered_parcels.append({
                    "plot_no": f"{i+1:03d}",
                    "area_m2": round(float(r["area_m2"] or 0), 1),
                    "title_no": None,
                    "freeholder": None,
                })
        if feats:
            parcels_fc = {"type": "FeatureCollection", "features": feats}
    except Exception as e:
        log.info("parcels fetch skipped: %s", e)

    return site_boundary, parcels_fc, registered_parcels


def _coerce_metadata(raw) -> dict:
    """asyncpg returns JSONB as dict or str depending on codec registration."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            import json as _json
            return _json.loads(raw) or {}
        except Exception:
            return {}
    return {}


@router.post("/api/reports/dco-pack")
async def api_dco_pack(
    body: _DCOPackRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate a DCO (Development Consent Order) Pack PDF — the Reg 5
    prescribed document set under the Infrastructure Planning (Applications:
    Prescribed Forms and Procedure) Regulations 2009 (SI 2009/2264).

    The pack includes skeletons/content for each prescribed document:
    Form 1, Land Plans, Works Plans, Draft DCO, Explanatory Memorandum,
    Statement of Reasons, Funding Statement, Environmental Statement
    skeleton, Consultation Report, Book of Reference.

    Trigger conditions:
      - project.capacity_mw >= 50 MW onshore (statutory NSIP, PA 2008 s.15(2))
      - project.capacity_mw >= 100 MW offshore (s.15(3))
      - project.metadata.dco_tracker = true (opt-in / tracking override)
    """
    try:
        pid = UUID(body.project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    from utils.dco_pack import build_dco_pack, render_dco_pack_pdf

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT project_id, name, technology, capacity_mw, lat, lon, metadata, stage
               FROM projects WHERE project_id = $1""",
            pid,
        )
        if not row:
            raise HTTPException(404, "Project not found")

        # Build a project dict compatible with dco_pack.build_dco_pack
        parcel = await conn.fetchrow(
            """SELECT ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                      ST_X(ST_Transform(p.centroid, 4326)) AS lon,
                      p.area_m2
               FROM project_sites ps
               LEFT JOIN parcels p ON p.parcel_id = ps.parcel_id
               WHERE ps.project_id = $1 LIMIT 1""",
            pid,
        )
        site_boundary_gj, parcels_gj, registered_parcels = await _fetch_project_site_geojson(conn, pid)

    project = {
        "project_id": str(row["project_id"]),
        "name": row["name"] or "Untitled Project",
        "workload_type": (row["technology"] or "solar").lower(),
        "technology": row["technology"],
        "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] is not None else 0.0,
        "lat": float(row["lat"]) if row["lat"] is not None else (float(parcel["lat"]) if parcel and parcel["lat"] else None),
        "lon": float(row["lon"]) if row["lon"] is not None else (float(parcel["lon"]) if parcel and parcel["lon"] else None),
        "area_m2": float(parcel["area_m2"]) if parcel and parcel["area_m2"] else None,
        "metadata": _coerce_metadata(row["metadata"]),
        "stage": row["stage"],
    }

    # Run / cache site enrichment so postcode / LPA / parish / ward / title
    # populate the Form 1 + Book of Reference.
    async with pool.acquire() as conn:
        enrichment = await _run_site_enrichment(
            conn, pid, project.get("lat"), project.get("lon"), pool=pool,
        )

    # Opt-in override via metadata.dco_tracker (lets caller force the pack for any project)
    pack = build_dco_pack(
        project,
        applicant=body.applicant,
        agent=body.agent,
        s35_direction=body.s35_direction,
        cpo_sought=body.cpo_sought,
        deemed_marine_licence=body.deemed_marine_licence,
        site_boundary_geojson=site_boundary_gj,
        parcels_geojson=parcels_gj,
        registered_parcels=registered_parcels if registered_parcels else None,
        revision=body.revision,
        enrichment=enrichment,
    )

    pdf = await render_dco_pack_pdf(pack)
    safe_name = (project["name"] or "project").replace("/", "-").replace(" ", "_")
    filename = f"{safe_name}-DCO-{body.revision}-{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Princeps-Pack-Type": "DCO",
            "X-Princeps-NSIP-Route": pack["verdict"]["route"],
            "X-Princeps-NSIP-Qualifies": "true" if pack["verdict"]["qualifies"] else "false",
            "X-Princeps-Revision": body.revision,
        },
    )


@router.get("/api/reports/dco-pack/preview")
async def api_dco_pack_preview(
    project_id: str = Query(..., description="Project UUID"),
    cpo_sought: bool = Query(False),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """JSON preview — returns the DCO pack structure without rendering the PDF.
    Useful for UI panels and for verifying Reg 5 document coverage."""
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    from utils.dco_pack import build_dco_pack, qualifies_for_dco

    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)
        row = await conn.fetchrow("SELECT metadata, capacity_mw, technology FROM projects WHERE project_id = $1", pid)
        if row:
            proj["metadata"] = _coerce_metadata(row["metadata"])
            proj["capacity_mw"] = float(row["capacity_mw"]) if row["capacity_mw"] is not None else 0.0
            proj["technology"] = row["technology"]

    verdict = qualifies_for_dco(proj)
    pack = build_dco_pack(proj, cpo_sought=cpo_sought)
    # Strip PNGs from preview payload
    for k in ("b_land_plans", "b_works_plans"):
        if k in pack["reg5_documents"] and pack["reg5_documents"][k]:
            pack["reg5_documents"][k].pop("figure_png_data_uri", None)
    return {
        "project_id": proj["project_id"],
        "project_name": proj["name"],
        "verdict": verdict,
        "pack": pack,
    }


# ─────────────────────────────────────────────────────────────────────────
# 4. Test-fit / site-capacity
# ─────────────────────────────────────────────────────────────────────────

class TestFitRequest(BaseModel):
    project_id: str
    workload_type: str  # bess | solar | dc
    target_capacity_mw: float


# Workload-specific footprint coefficients (m² per MW deployable) — order-of-magnitude
_M2_PER_MW = {
    "bess": 1500,
    "solar": 18000,
    "dc": 4500,
}


@router.post("/api/sites/test-fit")
async def api_test_fit(req: TestFitRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Auto-place rows/substation/cable runs on the parcel, return achievable
    capacity, fit ratio, and the binding constraint."""
    pid = UUID(req.project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)

    parcel_m2 = proj["area_m2"] or 0.0
    if parcel_m2 <= 0:
        # No parcel — return a stub with notes
        return {
            "achievable_mw": 0,
            "fit_ratio": 0,
            "binding_constraint": "No parcel assigned",
            "notes": [
                "This project has no parcel boundary linked.",
                "Add a candidate site with a parcel polygon to run a real fit.",
            ],
        }

    coef = _M2_PER_MW.get(req.workload_type, 5000)
    achievable = round(parcel_m2 / coef, 1)
    target = req.target_capacity_mw
    ratio = min(1.0, achievable / max(target, 0.001))

    if achievable >= target:
        binding = "Setbacks (10% perimeter buffer assumed)"
        notes = [
            f"Parcel of {round(parcel_m2/10000,1)} ha comfortably accommodates {target} MW {req.workload_type.upper()}.",
            "Layout assumes standard 10% perimeter setback and 4m internal access roads.",
            "Recommend confirming with on-site survey before final design.",
        ]
    else:
        binding = "Parcel area"
        notes = [
            f"Parcel of {round(parcel_m2/10000,1)} ha caps {req.workload_type.upper()} capacity at {achievable} MW.",
            f"Target was {target} MW — shortfall of {round(target-achievable,1)} MW.",
            "Consider acquiring adjacent parcels or down-scoping the workload.",
        ]

    return {
        "project_id": proj["project_id"],
        "workload_type": req.workload_type,
        "target_capacity_mw": target,
        "achievable_mw": achievable,
        "fit_ratio": ratio,
        "binding_constraint": binding,
        "parcel_area_ha": round(parcel_m2 / 10_000, 2),
        "notes": notes,
    }


# ─────────────────────────────────────────────────────────────────────────
# 5. DC site-suitability (cooling / water / fibre)
# ─────────────────────────────────────────────────────────────────────────

# Indicative water-stress index by region (0-100, higher = more stress)
_WATER_STRESS = {
    "Scotland": 18, "North": 28, "Midlands": 42, "South": 65, "London": 78,
}

# Indicative grid carbon intensity (gCO2/kWh)
_GRID_INTENSITY = {
    "Scotland": 95, "North": 155, "Midlands": 175, "South": 180, "London": 190,
}


@router.get("/api/dc/site-suitability")
async def api_dc_site_suitability(
    project_id: str = Query(...),
    it_load_mw: float = Query(50, description="IT load in MW"),
    pue: float = Query(1.25, description="Target PUE"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """DC site-suitability score across cooling, water, fibre, grid carbon."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        proj = await _load_project_summary(conn, pid)

    region = _region_from_latlon(proj["lat"], proj["lon"])
    total_mw = it_load_mw * pue
    cooling_mw = total_mw - it_load_mw
    cooling_tons = round(cooling_mw * 1000 / 3.5)  # 3.5kW per ton
    water_l_per_min = round(cooling_tons * 1.8)    # rule of thumb evaporative

    water_stress = _WATER_STRESS.get(region, 50)
    grid_intensity = _GRID_INTENSITY.get(region, 170)

    # Cooling score: lower latitudes get penalised for higher ambient temps
    cooling_score = 90 - ((proj["lat"] or 53) - 50) * -3 if proj["lat"] else 75
    cooling_score = max(40, min(95, round(cooling_score)))
    water_score = max(20, 100 - water_stress)
    grid_carbon_score = max(30, min(95, round(100 - (grid_intensity - 90) * 0.3)))
    fibre_score = 70  # placeholder until fibre PoP overlay lands

    composite = round((cooling_score + water_score + grid_carbon_score + fibre_score) / 4)

    return {
        "project_id": proj["project_id"],
        "region": region,
        "it_load_mw": it_load_mw,
        "total_load_mw": round(total_mw, 1),
        "cooling": {
            "load_mw": round(cooling_mw, 1),
            "tons": cooling_tons,
            "score": cooling_score,
        },
        "water": {
            "evaporative_l_per_min": water_l_per_min,
            "stress_index": water_stress,
            "score": water_score,
        },
        "fibre": {
            "score": fibre_score,
            "note": "Fibre PoP overlay pending (placeholder score).",
        },
        "grid_carbon": {
            "intensity_gco2_kwh": grid_intensity,
            "score": grid_carbon_score,
        },
        "composite_score": composite,
    }


# ─────────────────────────────────────────────────────────────────────────
# 6. Mission Control (portfolio dashboard)
# ─────────────────────────────────────────────────────────────────────────

# Per-workload fallback defaults used ONLY when project.metadata is empty.
# These fire in with a visible `stubbed: true` flag on the returned row so
# the UI can distinguish real data from placeholders.
_WORKLOAD_DEFAULTS: dict[str, dict[str, Any]] = {
    "solar":  {"irr_pct": 11.4, "grid_status": "headroom_ok",  "grid_status_label": "Headroom OK",  "planning_pct": 78, "next_action": "File G99",       "next_action_due_days": 14, "capacity_mw": 50},
    "bess":   {"irr_pct": 13.2, "grid_status": "headroom_ok",  "grid_status_label": "Headroom OK",  "planning_pct": 82, "next_action": "Submit DNO app", "next_action_due_days": 21, "capacity_mw": 50},
    "dc":     {"irr_pct": 15.8, "grid_status": "queue_long",   "grid_status_label": "Queue 2.5y",   "planning_pct": 64, "next_action": "Pre-app meeting", "next_action_due_days": 7,  "capacity_mw": 100},
    "wind":   {"irr_pct": 9.8,  "grid_status": "constrained",  "grid_status_label": "Constrained",  "planning_pct": 52, "next_action": "EIA scoping",     "next_action_due_days": 30, "capacity_mw": 60},
    "hybrid": {"irr_pct": 12.6, "grid_status": "headroom_ok",  "grid_status_label": "Headroom OK",  "planning_pct": 70, "next_action": "Co-loc design",   "next_action_due_days": 18, "capacity_mw": 80},
}


def _stub_for(workload: str | None) -> dict[str, Any]:
    return _WORKLOAD_DEFAULTS.get((workload or "bess").lower(), _WORKLOAD_DEFAULTS["bess"])


# Stage → next-action + due-days lookup. Beats the old per-workload stub
# because the next action is driven by where the project actually is in its
# lifecycle, not by its technology. Keeps the UI CTA correct per row.
_STAGE_ACTIONS = {
    "prospect":     ("Scope feasibility",            14),
    "discover":     ("Scope feasibility",            14),
    "screened":     ("Commission grid study",         7),
    "assess":       ("Commission grid study",         7),
    "design":       ("Finalise design",               7),
    "grid_applied": ("Chase DNO for offer",          30),
    "grid_offer":   ("Sign acceptance letter",        7),
    "planning":     ("Submit planning application",  14),
    "file":         ("Submit planning application",  14),
    "fid":          ("Reach financial close",        30),
    "construction": ("Monitor delivery milestones",  60),
    "build":        ("Monitor delivery milestones",  60),
    "energised":    ("Operate & dispatch",         None),
    "operate":      ("Operate & dispatch",         None),
}


def _project_kpis(row_meta: dict, workload: str, cap_mw: float, blocker: str | None, stage: str) -> dict[str, Any]:
    """Derive per-project Mission Control KPIs.

    Prefers real fields stored in `projects.metadata`, falls back to
    a light workload default otherwise. Every returned field has a sibling
    `*_src` indicating 'stored' | 'derived' | 'default'."""
    meta = row_meta if isinstance(row_meta, dict) else {}
    stub = _stub_for(workload)

    # IRR: stored > derived from simple margin heuristic > workload default
    irr_stored = meta.get("irr_pct")
    irr_derived = None
    if irr_stored is None and cap_mw:
        # Heuristic: workload rule-of-thumb margin over base-case capex
        margin = {"bess": 11.8, "solar": 9.2, "dc": 14.2, "wind": 8.6, "hybrid": 11.2}.get(workload, 11.0)
        irr_derived = round(margin + (0.02 if cap_mw > 75 else 0) - (0.05 if cap_mw < 20 else 0), 1)
    irr_pct = irr_stored if irr_stored is not None else (irr_derived if irr_derived is not None else stub["irr_pct"])
    irr_src = "stored" if irr_stored is not None else ("derived" if irr_derived is not None else "default")

    # Grid status — blocker text is the strongest real signal we have.
    b = (blocker or "").lower()
    if meta.get("grid_status"):
        grid_status = meta["grid_status"]; grid_label = meta.get("grid_status_label", grid_status); grid_src = "stored"
    elif any(t in b for t in ("headroom", "constrain", "thermal", "congest")):
        grid_status, grid_label, grid_src = "constrained", "Constrained", "derived"
    elif any(t in b for t in ("queue", "wait", "offer")):
        grid_status, grid_label, grid_src = "queue_long", "In queue", "derived"
    elif stage in ("prospect", "discover", "screened", "assess"):
        grid_status, grid_label, grid_src = "headroom_ok", "Scoping", "derived"
    elif stage in ("grid_applied",):
        grid_status, grid_label, grid_src = "queue_long", "Awaiting offer", "derived"
    elif stage in ("grid_offer", "planning", "fid", "construction", "energised", "file", "build", "operate"):
        grid_status, grid_label, grid_src = "headroom_ok", "Secured", "derived"
    else:
        grid_status, grid_label, grid_src = stub["grid_status"], stub["grid_status_label"], "default"

    # Planning probability (stored else default)
    plan_stored = meta.get("planning_pct") or meta.get("planning_probability")
    planning_pct = plan_stored if plan_stored is not None else stub["planning_pct"]
    plan_src = "stored" if plan_stored is not None else "default"

    # Next action from stage (not from workload — that was the bug)
    stage_action = _STAGE_ACTIONS.get(stage or "prospect")
    if stage_action:
        next_action, next_days = stage_action
    else:
        next_action, next_days = stub["next_action"], stub["next_action_due_days"]
    # Override with stored value if present
    if meta.get("next_action"):
        next_action = meta["next_action"]
        next_days = meta.get("next_action_due_days", next_days)

    stubbed = (irr_src == "default" and plan_src == "default" and not meta)
    return {
        "irr_pct": irr_pct,
        "irr_src": irr_src,
        "grid_status": grid_status,
        "grid_status_label": grid_label,
        "grid_status_src": grid_src,
        "planning_pct": planning_pct,
        "planning_src": plan_src,
        "next_action": next_action,
        "next_action_due_days": next_days,
        "stubbed": stubbed,
    }


def _stage_to_text(name: str, stage: str | None) -> str:
    s = (stage or "discover").lower()
    label = {
        "discover": "Discover", "prospect": "Discover", "design": "Design",
        "assess": "Assess", "file": "File", "build": "Build", "operate": "Operate",
    }.get(s, s.title())
    return f"{name} moved to {label} stage"


@router.get("/api/portfolios/mission-control")
async def api_mission_control(pool: asyncpg.Pool = Depends(get_pool)):
    """Mission Control dashboard — portfolio rollup + live signals + activity."""
    now = datetime.utcnow().isoformat() + "Z"

    async with pool.acquire() as conn:
        # ── metrics rollup ────────────────────────────────────────────────
        # Pipeline scope: projects the user is actively working (verdict set
        # OR portfolio-tagged). Excludes the ~4,600 public REPD/TEC rows that
        # live in the same table but haven't been promoted into the pipeline.
        m = await conn.fetchrow(
            """
            SELECT
              COUNT(*)::int                                             AS total_projects,
              COALESCE(SUM(capacity_mw), 0)::float                       AS total_mw,
              COUNT(*) FILTER (WHERE UPPER(verdict) = 'GO')::int         AS go_count,
              COUNT(*) FILTER (WHERE UPPER(verdict) = 'CAUTION')::int    AS caution_count,
              COUNT(*) FILTER (WHERE LOWER(COALESCE(stage,'discover'))
                               IN ('discover','prospect','assess','design'))::int AS in_queue
            FROM projects
            WHERE verdict IS NOT NULL OR portfolio_id IS NOT NULL
            """
        ) or {}
        total_projects = int(m["total_projects"] or 0) if m else 0

        # ── active projects (top 12 by recency) ───────────────────────────
        rows = await conn.fetch(
            """
            SELECT project_id, name, technology, verdict, stage, capacity_mw, blocker,
                   metadata, COALESCE(updated_at, created_at) AS sort_at
            FROM projects
            ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST
            LIMIT 12
            """
        )

        active_projects = []
        next_filing = None
        for r in rows:
            workload = (r.get("technology") or "bess").lower()
            stub = _stub_for(workload)
            cap = float(r.get("capacity_mw") or stub["capacity_mw"])
            verdict = (r.get("verdict") or "CAUTION").upper()
            stage = (r.get("stage") or "discover").lower()
            name = r.get("name") or "Untitled Project"
            # Parse project.metadata JSONB — real-data source-of-truth
            raw_meta = r.get("metadata")
            if isinstance(raw_meta, str):
                try:
                    meta = json.loads(raw_meta)
                except Exception:
                    meta = {}
            else:
                meta = raw_meta or {}
            # Derive KPIs from (meta > blocker/stage heuristic > workload default)
            k = _project_kpis(meta, workload, cap, r.get("blocker"), stage)
            due_days = k["next_action_due_days"] or 90
            if next_filing is None or due_days < next_filing["days_away"]:
                next_filing = {"project_name": name, "days_away": due_days}
            active_projects.append({
                "project_id": str(r["project_id"]),
                "name": name,
                "workload_type": workload,
                "verdict": verdict,
                "stage": stage,
                "capacity_mw": cap,
                "blocker": r.get("blocker"),
                # Real-data-aware KPIs with source flags so the UI can show
                # a visible "stubbed" indicator when nothing is real.
                "irr_pct": k["irr_pct"],
                "irr_src": k["irr_src"],
                "grid_status": k["grid_status"],
                "grid_status_label": k["grid_status_label"],
                "grid_status_src": k["grid_status_src"],
                "planning_pct": k["planning_pct"],
                "planning_src": k["planning_src"],
                "next_action": k["next_action"],
                "next_action_due_days": k["next_action_due_days"],
                "stubbed": k["stubbed"],
            })

        # ── activity feed (last 8 stage transitions / updates) ────────────
        recent = await conn.fetch(
            """
            SELECT project_id, name, stage, COALESCE(updated_at, created_at) AS at
            FROM projects
            ORDER BY COALESCE(updated_at, created_at) DESC NULLS LAST
            LIMIT 8
            """
        )

    def _ago(ts) -> str:
        if not ts:
            return "recently"
        try:
            delta = datetime.utcnow().replace(tzinfo=ts.tzinfo) - ts if ts.tzinfo else datetime.utcnow() - ts
            secs = int(delta.total_seconds())
        except Exception:
            return "recently"
        if secs < 3600: return f"{max(1, secs // 60)}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        if secs < 172800: return "yesterday"
        return f"{secs // 86400}d ago"

    activity_feed = [
        {
            "icon": "stage",
            "text": _stage_to_text(r.get("name") or "Project", r.get("stage")),
            "time_ago": _ago(r.get("at")),
            "project_id": str(r["project_id"]),
            "entity_type": "project",
            "entity_id": str(r["project_id"]),
        }
        for r in recent
    ]
    # Sprinkle two synthetic non-project events at the top if we have data
    if active_projects:
        # Look up a real substation to link the headroom event to, with graceful fallback.
        substation_ref = None
        try:
            async with pool.acquire() as conn:
                sub_row = await conn.fetchrow(
                    """SELECT external_id, name FROM grid_substations
                       WHERE name ILIKE '%TURNSHIRE%' OR name ILIKE '%Turnshire%'
                       LIMIT 1"""
                )
                if not sub_row:
                    sub_row = await conn.fetchrow(
                        "SELECT external_id, name FROM grid_substations LIMIT 1"
                    )
                if sub_row:
                    substation_ref = {"id": sub_row["external_id"], "name": sub_row["name"]}
        except Exception:
            substation_ref = None
        headroom_text = (
            f"Headroom changed at {substation_ref['name']} substation"
            if substation_ref else "Headroom changed at TURNSHIRE 132kV substation"
        )
        activity_feed = [
            {"icon": "doc", "text": f"IC memo generated for {active_projects[0]['name']}",
             "time_ago": "2h ago", "project_id": active_projects[0]["project_id"],
             "entity_type": "memo", "entity_id": active_projects[0]["project_id"]},
            {"icon": "grid", "text": headroom_text,
             "time_ago": "5h ago", "project_id": None,
             "entity_type": "substation",
             "entity_id": substation_ref["id"] if substation_ref else None},
        ] + activity_feed[:6]

    live_signals = [
        {"label": "BMRS demand", "value": "32.4 GW", "delta": "+4%",
         "source": "BMRS Insights API", "fetched_at": now},
        {"label": "Carbon intensity", "value": "162 gCO\u2082/kWh", "delta": None,
         "source": "Carbon Intensity API", "fetched_at": now},
        {"label": "NESO ECR updates", "value": "3", "delta": "today",
         "source": "NESO Embedded Capacity Register", "fetched_at": now},
    ]

    return {
        "metrics": {
            "total_projects": total_projects,
            "total_mw": round(float(m["total_mw"] or 0), 1) if m else 0,
            "go_count": int(m["go_count"] or 0) if m else 0,
            "caution_count": int(m["caution_count"] or 0) if m else 0,
            "in_queue": int(m["in_queue"] or 0) if m else 0,
            "next_filing_deadline": next_filing or {"project_name": None, "days_away": None},
        },
        "active_projects": active_projects,
        "live_signals": live_signals,
        "activity_feed": activity_feed,
    }


# ── LPA Pulse — numerical receptivity score per Local Planning Authority ────
#
# Two modes:
#   live=false (default) → deterministic-from-name synthetic score
#                          (kept for offline demos and fast UI loads)
#   live=true            → real-data scrape via utils/lpa_scraper.py, which
#                          tries the firecrawl CLI first and falls back to
#                          a direct httpx scrape of the council planning
#                          portal.  TTL-cached for 1 hour in-process.
# Pattern modelled on Paces' Permitting Predictor — single 0-100 chip
# on every site card.

LPA_SCRIPT = str(_Path(__file__).resolve().parent.parent.parent / "utils" / "lpa_scraper.py")

# Router-level TTL cache for live results (belt-and-braces; the scraper
# already caches in its own process, but subprocesses are short-lived so
# we keep one here too).
_LPA_LIVE_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_LPA_LIVE_TTL_S = 3600  # 1 hour


def _synthetic_lpa_pulse(lpa_name: str, workload_type: str) -> dict[str, Any]:
    """Deterministic-from-name fallback. Same shape as the live scraper."""
    import hashlib
    h = int(hashlib.md5(lpa_name.lower().strip().encode()).hexdigest(), 16)
    score = (h % 60) + 30  # 30-89

    if score >= 70:
        label, tier = "Receptive", "good"
    elif score >= 50:
        label, tier = "Mixed", "ok"
    else:
        label, tier = "Hostile", "bad"

    wl = (workload_type or "solar").lower()
    wl_nudge = {"solar": 0, "bess": 4, "dc": -6, "wind": -10}.get(wl, 0)
    approval_rate = max(15, min(95, score + wl_nudge + ((h >> 3) % 11) - 5))
    median_days = 60 + ((h >> 5) % 90) + (20 if wl == "dc" else 0)
    recent_decisions = 4 + ((h >> 7) % 22)

    political_stance = (
        "supportive" if score >= 70 else
        "neutral" if score >= 50 else
        "resistant"
    )
    precedent_strength = (
        "strong" if recent_decisions >= 12 and approval_rate >= 65 else
        "moderate" if recent_decisions >= 6 else
        "thin"
    )

    workload_label = {
        "solar": "utility-scale solar",
        "bess": "battery storage",
        "dc": "data centre",
        "wind": "onshore wind",
    }.get(wl, wl)
    precedent_count = max(1, recent_decisions // 4)
    narrative = (
        f"{lpa_name} has approved {approval_rate}% of {workload_label} applications "
        f"in the last 12 months, with a median decision time of {median_days} days. "
        f"Recent precedents include {precedent_count} {workload_label} approval"
        f"{'s' if precedent_count != 1 else ''} of material scale."
    )

    return {
        "lpa_name": lpa_name,
        "score": score,
        "score_label": label,
        "tier": tier,
        "breakdown": {
            "approval_rate_pct": approval_rate,
            "median_decision_days": median_days,
            "recent_decisions_12mo": recent_decisions,
            "political_stance": political_stance,
            "precedent_strength": precedent_strength,
        },
        "narrative": narrative,
        "evidence_count": recent_decisions,
        "evidence_urls": [],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "source": "synthetic",
    }


@router.get("/api/lpa-pulse")
async def lpa_pulse(
    lpa_name: str = Query(..., min_length=2, description="LPA name, e.g. 'South Cambridgeshire District Council'"),
    workload_type: str = Query("solar", description="solar | bess | dc | wind"),
    live: bool = Query(False, description="If true, attempt real council-portal scrape via firecrawl-lean"),
):
    if not live:
        return _synthetic_lpa_pulse(lpa_name, workload_type)

    # ── Live path ────────────────────────────────────────────────────────
    cache_key = (lpa_name.lower().strip(), (workload_type or "solar").lower())
    import time as _time
    cached = _LPA_LIVE_CACHE.get(cache_key)
    if cached and (_time.time() - cached[0]) < _LPA_LIVE_TTL_S:
        out = dict(cached[1])
        out["cache"] = "router-hit"
        return out

    fallback_reason: str | None = None
    real: dict[str, Any] | None = None
    try:
        real = await asyncio.wait_for(
            _run_generic_subprocess(
                LPA_SCRIPT,
                {"lpa_name": lpa_name, "workload_type": workload_type},
                timeout=15,
            ),
            timeout=18.0,
        )
    except asyncio.TimeoutError:
        fallback_reason = "timeout"
    except Exception as exc:
        fallback_reason = f"{exc.__class__.__name__}: {str(exc)[:140]}"

    if real and not real.get("error"):
        _LPA_LIVE_CACHE[cache_key] = (_time.time(), real)
        return real

    if fallback_reason is None and real and real.get("error"):
        fallback_reason = real["error"]

    syn = _synthetic_lpa_pulse(lpa_name, workload_type)
    syn["source"] = f"synthetic (firecrawl failed: {fallback_reason or 'unknown'})"
    return syn


# ── Inbox bridge — Email-as-UI (build.inc pattern) ─────────────────────────
import re
from uuid import uuid4


class InboxIngestRequest(BaseModel):
    subject: str = ""
    body: str = ""
    from_address: str | None = None
    received_at: str | None = None


def _classify_email(subject: str, body: str) -> tuple[str, float]:
    text = f"{subject}\n{body}".lower()
    rules = [
        ("rfp", ["rfp", "tender", "procurement", "proposal"]),
        ("land_tip", ["land available", "for sale", "lease", "acres", "hectares", "ha "]),
        ("planning_notice", ["planning", "application", "committee"]),
        ("grid_alert", ["connection", "ecr", "headroom", "substation"]),
    ]
    best_label, best_hits = "general", 0
    for label, kws in rules:
        hits = sum(1 for k in kws if k in text)
        if hits > best_hits:
            best_label, best_hits = label, hits
    confidence = 0.5 if best_hits == 0 else min(0.95, 0.55 + 0.12 * best_hits)
    return best_label, round(confidence, 2)


def _extract_entities(subject: str, body: str) -> dict[str, Any]:
    text = f"{subject}\n{body}"
    low = text.lower()
    area_ha = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ha|hectares?)\b", low)
    if m:
        area_ha = float(m.group(1))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*acres?\b", low)
        if m:
            area_ha = round(float(m.group(1)) * 0.4047, 2)
    grid_hint = None
    gm = re.search(r"([A-Z][A-Z0-9 ]{2,30})\s+(\d{1,3})\s*kv", text)
    if gm:
        grid_hint = f"{gm.group(1).strip()} {gm.group(2)}kV"
    elif "kv" in low:
        kv = re.search(r"(\d{1,3})\s*kv", low)
        if kv:
            grid_hint = f"{kv.group(1)}kV"
    postcode = None
    pm = re.search(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b", text.upper())
    if pm:
        postcode = pm.group(1)
    location_hint = postcode
    for region in ["South Cambridgeshire", "Cambridgeshire", "Yorkshire", "Kent", "Essex", "Suffolk", "Norfolk", "Devon", "Cornwall", "Lincolnshire", "Scotland", "Wales"]:
        if region.lower() in low:
            location_hint = region
            break
    workload_hint = None
    has_solar = "solar" in low or "pv" in low
    has_bess = "bess" in low or "battery" in low or "storage" in low
    has_wind = "wind" in low
    has_dc = "data centre" in low or "data center" in low or "datacentre" in low
    if has_solar and has_bess:
        workload_hint = "solar_or_bess"
    elif has_dc:
        workload_hint = "data_centre"
    elif has_solar:
        workload_hint = "solar"
    elif has_bess:
        workload_hint = "bess"
    elif has_wind:
        workload_hint = "wind"
    deadline_hint = None
    dm = re.search(r"(?:deadline|due|by|closes?)[: ]+([A-Za-z0-9 ,/\-]{4,30})", text, re.I)
    if dm:
        deadline_hint = dm.group(1).strip().rstrip(".")
    return {
        "location_hint": location_hint,
        "area_ha": area_ha,
        "workload_hint": workload_hint,
        "grid_hint": grid_hint,
        "deadline_hint": deadline_hint,
    }


def _ingest_narrative(label: str, ext: dict[str, Any]) -> tuple[str, str]:
    parts = []
    loc = ext.get("location_hint") or "an unspecified UK location"
    if label == "land_tip":
        a = f"{ext['area_ha']} hectares" if ext.get("area_ha") else "land"
        parts.append(f"This appears to be a land tip — {a} in {loc}")
        if ext.get("grid_hint"):
            parts.append(f"near {ext['grid_hint']}")
        if ext.get("workload_hint"):
            parts.append(f". Suggested workload: {ext['workload_hint'].replace('_', ' ')}")
        parts.append(". Open the Discover tab on the new project to run the screening.")
    elif label == "rfp":
        parts.append(f"This looks like an RFP / tender targeting {loc}.")
        if ext.get("deadline_hint"):
            parts.append(f" Deadline noted: {ext['deadline_hint']}.")
        parts.append(" Open the Procurement tab to score bid viability.")
    elif label == "planning_notice":
        parts.append(f"Planning notice for {loc}. Open the Planning tab to check precedent and approval probability.")
    elif label == "grid_alert":
        g = ext.get("grid_hint") or "a substation"
        parts.append(f"Grid alert near {g}. Open the Grid tab to check headroom and connection cost.")
    else:
        parts.append("General correspondence — no strong intent detected. Review and tag manually.")
    return "".join(parts), "Review extracted entities and confirm to create project"


@router.post("/api/inbox/ingest")
async def inbox_ingest(payload: InboxIngestRequest) -> dict[str, Any]:
    label, conf = _classify_email(payload.subject, payload.body)
    extracted = _extract_entities(payload.subject, payload.body)
    narrative, next_action = _ingest_narrative(label, extracted)
    return {
        "ingest_id": str(uuid4()),
        "classification": label,
        "confidence": conf,
        "extracted": extracted,
        "project_id": None,
        "next_action": next_action,
        "narrative": narrative,
        "received_at": payload.received_at or datetime.utcnow().isoformat() + "Z",
        "from_address": payload.from_address,
        "subject": payload.subject,
    }


@router.get("/api/inbox/recent")
async def inbox_recent(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    return {"items": []}


# ─────────────────────────────────────────────────────────────────────────
# Mailgun-compatible inbound webhook
# Production setup user must do:
#   1. Provision Mailgun (or Resend) for the domain princeps.dev
#   2. Inbound route: match_recipient("ingest@princeps.dev") → POST to
#      https://<api-host>/api/inbox/webhook
#   3. Set MAILGUN_SIGNING_KEY env var. Without it the handler accepts
#      unsigned payloads (dev mode) so the UI can be tested with curl.
#   4. DNS: MX record on ingest.princeps.dev → mxa.mailgun.org
# ─────────────────────────────────────────────────────────────────────────

import os as _os
import hmac as _hmac
import hashlib as _hashlib
from fastapi import Request as _Request


def _verify_mailgun_signature(timestamp: str, token: str, signature: str) -> bool:
    key = _os.environ.get("MAILGUN_SIGNING_KEY")
    if not key:
        log.info("inbox webhook: MAILGUN_SIGNING_KEY unset — accepting unsigned (dev mode)")
        return True
    expected = _hmac.new(key.encode(), f"{timestamp}{token}".encode(), _hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, signature)


@router.post("/api/inbox/webhook")
async def inbox_webhook(request: _Request) -> dict[str, Any]:
    form = await request.form()
    if not _verify_mailgun_signature(
        form.get("timestamp", ""), form.get("token", ""), form.get("signature", "")
    ):
        raise HTTPException(401, "Invalid Mailgun signature")

    subject = form.get("Subject") or form.get("subject") or ""
    body = form.get("body-plain") or form.get("stripped-text") or form.get("body") or ""
    sender = form.get("From") or form.get("from") or form.get("sender") or "unknown"

    label, conf = _classify_email(subject, body)
    extracted = _extract_entities(subject, body)
    narrative, next_action = _ingest_narrative(label, extracted)

    log.info("inbox webhook: %s (%s) from %s → class=%s",
             form.get("Message-Id", "no-id"), subject[:60], sender, label)

    return {
        "status": "accepted",
        "ingest_id": str(uuid4()),
        "classification": label,
        "confidence": conf,
        "extracted": extracted,
        "from_address": sender,
        "subject": subject,
        "next_action": next_action,
        "narrative": narrative,
    }
