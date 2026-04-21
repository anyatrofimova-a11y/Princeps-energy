"""Agentic operational intelligence — KPI rail + Claude-authored site memo.

Two endpoints powering the twin's Assess-tab KPI rail (BOT-LL), the parcel
drawer (BOT-FF), and the chat / reports surfaces:

 - GET  /api/agent/kpis?project_id=<uuid>       — 8 structured KPIs with verdicts
 - POST /api/agent/site-memo                    — Claude-authored 1-paragraph memo

The memo endpoint reuses the project full-doc (BOT-D's GET /api/design/{pid}/full-doc)
and leans on Anthropic prompt caching to keep the static system prompt hot.

Endpoints are non-blocking (≤10s wall clock); if Claude runs over, the memo
endpoint returns a deferred task handle the frontend can poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_claude, get_pool
from app.helpers import CLAUDE_MODEL
from utils.finance_benchmarks import ppa_price_merchant as _bench_ppa

log = logging.getLogger("princeps.agent_ops")

router = APIRouter(prefix="/api/agent", tags=["agent-ops"])


# ═══════════════════════════════════════════════════════════════════════════
# 1. KPIs — GET /api/agent/kpis?project_id=<uuid>
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/kpis")
async def get_project_kpis(
    project_id: str = Query(..., description="Project UUID"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Structured scoring for a project — grid viability, planning likelihood,
    buildable area, connection cost P50, queue position, verdict, revenue P50,
    LCOE. Each KPI carries value + unit + verdict (green/amber/red/unknown)
    + source provenance + human-readable explanation."""
    from utils.agentic_scoring import compose_project_kpis

    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            compose_project_kpis(pool, project_id),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        log.warning("KPI compose for %s timed out after 10s", project_id)
        return {
            "project_id": project_id,
            "computed_utc": datetime.now(timezone.utc).isoformat(),
            "kpis": [],
            "status": "timeout",
            "error": "KPI compose exceeded 10s budget",
        }

    if result.get("error") and not result.get("kpis"):
        raise HTTPException(status_code=404, detail=result["error"])

    result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 2. Site memo — POST /api/agent/site-memo
# ═══════════════════════════════════════════════════════════════════════════

class SiteMemoRequest(BaseModel):
    project_id: str = Field(..., description="Project UUID")
    max_sentences: int = Field(6, ge=2, le=10, description="Memo length cap")
    # Optional override — skip the full-doc fetch if caller already has it.
    full_doc: dict | None = Field(None, description="Pre-loaded full-doc (skip fetch)")


# In-memory task dict for deferred memo generation.
# Keyed by task_id → {status, memo, error, created_utc}
_MEMO_TASKS: dict[str, dict[str, Any]] = {}
_MEMO_TASK_TTL_S = 600.0


def _prune_memo_tasks() -> None:
    """Drop task records older than TTL (prevents unbounded growth)."""
    now = time.monotonic()
    drop = [k for k, v in _MEMO_TASKS.items()
            if now - v.get("_mono", now) > _MEMO_TASK_TTL_S]
    for k in drop:
        _MEMO_TASKS.pop(k, None)


SITE_MEMO_SYSTEM_PROMPT = """You are a senior UK energy-infrastructure analyst at Princeps.
Your job is to write a single tight paragraph — an operator-grade site memo — that
a development manager or lender could copy into an investment committee pack.

Style rules (STRICT):
 - One paragraph only. No headers, no bullets, no markdown formatting.
 - Between 3 and the caller's max_sentences (default 6) sentences.
 - Use engineering units: MW, MWh, km, kV, ha, £m, £/MWh, % headroom.
 - Cite real values from the provided data blob; never invent substations,
   capacities, planning flags, or financial figures.
 - Name the nearest substation (with voltage and headroom), the parcel size
   with buildable area, connection cost or cable route, planning likelihood
   or designations, and finance (DSCR / IRR / LCOE / revenue) where data
   supports them. Skip what isn't supported — do not hedge generically.
 - Flag the single binding constraint (queue depth, flood zone, ALC grade,
   DSCR covenant breach, etc.) if present.
 - Neutral professional tone. No emojis, no marketing language, no "robust"
   or "exciting". Sound like a project finance analyst, not a sales deck.

Return JSON only:
{
  "memo": "<single paragraph>",
  "key_points": ["<up to 5 short structured bullets distilling the memo>"],
  "binding_constraint": "<1 line, or null if none identified>"
}"""


def _build_key_points_fallback(full_doc: dict) -> list[str]:
    """Derive 3-5 bullets from the full-doc when Claude fails."""
    bullets: list[str] = []
    proj = full_doc.get("project") or {}
    design = full_doc.get("design") or {}
    grid = full_doc.get("grid") or {}
    finance = full_doc.get("finance") or {}
    if proj.get("name"):
        bullets.append(f"Project: {proj['name']} "
                       f"({proj.get('capacity_mw', '?')} MW {proj.get('technology', '')})")
    if grid.get("nearest_substation"):
        bullets.append(f"Nearest: {grid['nearest_substation']} "
                       f"at {grid.get('distance_km', '?')} km, "
                       f"{grid.get('headroom_mw', '?')} MW headroom")
    if design.get("site_area_ha"):
        bullets.append(f"Site: {design['site_area_ha']} ha parcel")
    if finance and finance.get("kpis"):
        k = finance["kpis"]
        if k.get("lcoe_gbp_per_mwh"):
            bullets.append(f"LCOE: £{k['lcoe_gbp_per_mwh']:.0f}/MWh")
        elif k.get("irr_pct"):
            bullets.append(f"IRR: {k['irr_pct']:.1f}%")
    if proj.get("verdict"):
        bullets.append(f"Verdict: {proj['verdict']}")
    return bullets[:5]


def _fallback_memo(full_doc: dict) -> str:
    """Deterministic memo when Claude fails or times out."""
    proj = full_doc.get("project") or {}
    design = full_doc.get("design") or {}
    grid = full_doc.get("grid") or {}
    finance = full_doc.get("finance") or {}
    name = proj.get("name") or "This project"
    cap = proj.get("capacity_mw") or design.get("solar_mw") or "?"
    tech = proj.get("technology") or "energy"
    area = design.get("site_area_ha") or "?"
    sub = grid.get("nearest_substation") or "the nearest DNO substation"
    dist = grid.get("distance_km") or "?"
    headroom = grid.get("headroom_mw") or "?"
    verdict = proj.get("verdict") or "CAUTION"
    lcoe = ""
    if finance and finance.get("kpis"):
        k = finance["kpis"]
        if k.get("lcoe_gbp_per_mwh"):
            lcoe = f" LCOE tracks £{k['lcoe_gbp_per_mwh']:.0f}/MWh."
    return (
        f"{name} is a {cap} MW {tech} scheme on a {area} ha parcel. "
        f"Nearest grid point is {sub}, {dist} km from site, with approximately "
        f"{headroom} MW of available headroom.{lcoe} Current agent verdict "
        f"is {verdict} — see dashboard for full breakdown."
    )


async def _fetch_full_doc(pool: asyncpg.Pool, project_id: str) -> dict | None:
    """Call the existing design/full-doc helpers directly (no HTTP round-trip)."""
    from app.routers.design import (
        _demand_snapshot,
        _extract_design_state,
        _grid_snapshot,
        _latest_assessments,
        _latest_finance,
        _load_project_row,
        _planning_snapshot,
    )

    try:
        pid = _uuid.UUID(project_id)
    except ValueError:
        return None

    async with pool.acquire() as conn:
        proj = await _load_project_row(conn, pid)
        if not proj:
            return None
        design = _extract_design_state(proj)
        finance = await _latest_finance(conn, pid)
        grid = await _grid_snapshot(conn, proj["lat"], proj["lon"])
        planning = await _planning_snapshot(conn, proj["lat"], proj["lon"])
        demand = await _demand_snapshot(conn, proj["lat"], proj["lon"])
        assessments = await _latest_assessments(conn, pid)

    try:
        from utils.design_optimizer import compute_design_kpis
        derived = compute_design_kpis(
            solar_mw=float(design.get("solar_mw", 0)),
            bess_mw=float(design.get("bess_mw", 0)),
            bess_hours=float(design.get("bess_hours", 2.0)),
            ppa_price_gbp_mwh=float(design.get("ppa_price_gbp_mwh", _bench_ppa("solar"))),
            ppa_share_pct=float(design.get("ppa_share_pct", 50.0)),
            workload_mw=float(design.get("workload_mw", 0)),
            site_area_ha=float(design.get("site_area_ha", 120.0)),
            grid_headroom_mw=float((grid or {}).get("headroom_mw") or 50.0),
        )
    except Exception:
        derived = None

    return {
        "project": proj,
        "design": design,
        "derived_kpis": derived,
        "finance": finance,
        "grid": grid,
        "planning": planning,
        "demand": demand,
        "latest_assessments": assessments,
    }


def _trim_full_doc(doc: dict) -> dict:
    """Strip heavy / irrelevant fields before sending to Claude.
    Keeps the static portion stable so prompt caching works."""
    if not doc:
        return {}
    out = {
        "project": {
            k: v for k, v in (doc.get("project") or {}).items()
            if k in ("project_id", "name", "description", "technology",
                    "capacity_mw", "stage", "verdict", "lat", "lon", "status")
        },
        "design": doc.get("design"),
        "derived_kpis": doc.get("derived_kpis"),
        "grid": doc.get("grid"),
        "planning": doc.get("planning"),
        "demand": doc.get("demand"),
    }
    finance = doc.get("finance") or {}
    if finance.get("kpis"):
        # Keep only the handful of fields that matter for a memo
        fin_kpis = finance["kpis"]
        if isinstance(fin_kpis, dict):
            keep = {k: v for k, v in fin_kpis.items()
                    if k in ("lcoe_gbp_per_mwh", "npv_gbp_m", "irr_pct",
                            "equity_irr_pct", "dscr_min", "dscr_p50",
                            "capex_gbp_m", "revenue_year1_gbp_m",
                            "revenue_p50_gbp_m", "payback_years")}
            if keep:
                out["finance"] = {"kpis": keep}
    # Compact assessment history: intent_count + overall verdict only
    if doc.get("latest_assessments"):
        out["latest_assessments"] = doc["latest_assessments"][:3]
    return out


async def _claude_site_memo(
    claude: anthropic.AsyncAnthropic,
    full_doc: dict,
    max_sentences: int,
) -> tuple[dict, dict]:
    """Ask Claude for the memo. Returns (parsed_dict, usage_dict).

    System prompt + trimmed full-doc are cached — the only varying content
    is the `max_sentences` instruction and the project_id header.
    """
    trimmed = _trim_full_doc(full_doc)
    static_blob = json.dumps(trimmed, default=str, sort_keys=True, indent=2)
    project_id = (trimmed.get("project") or {}).get("project_id") or "unknown"

    # System: cacheable via cache_control on the last block (prefix match).
    system_blocks = [
        {
            "type": "text",
            "text": SITE_MEMO_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    # User message carries the project data (stable within a session) +
    # a tiny volatile suffix with the caller's length preference.
    user_content = [
        {
            "type": "text",
            "text": f"PROJECT DATA (project_id={project_id}):\n```json\n{static_blob}\n```",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                f"Write the memo in no more than {max_sentences} sentences. "
                "Return JSON only matching the schema in the system prompt."
            ),
        },
    ]

    t0 = time.monotonic()
    message = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=900,
        temperature=0.1,
        system=system_blocks,
        messages=[{"role": "user", "content": user_content}],
    )
    elapsed = round(time.monotonic() - t0, 2)

    raw = ""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            raw = block.text
            break
    parsed = _parse_memo_json(raw)
    usage = {
        "input_tokens": getattr(message.usage, "input_tokens", None),
        "output_tokens": getattr(message.usage, "output_tokens", None),
        "cache_creation_input_tokens": getattr(
            message.usage, "cache_creation_input_tokens", None),
        "cache_read_input_tokens": getattr(
            message.usage, "cache_read_input_tokens", None),
        "elapsed_s": elapsed,
    }
    return parsed, usage


def _parse_memo_json(raw: str) -> dict:
    """Extract {memo, key_points, binding_constraint} from Claude's response."""
    if not raw:
        return {}
    txt = raw.strip()
    # Strip code fences if present
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1] if "```" in txt[3:] else txt[3:]
        if txt.startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
        if txt.endswith("```"):
            txt = txt[:-3].strip()
    # Find first { ... last }
    start = txt.find("{")
    end = txt.rfind("}")
    if start >= 0 and end > start:
        txt = txt[start:end + 1]
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return {"memo": raw.strip(), "key_points": [], "binding_constraint": None}


@router.post("/site-memo")
async def site_memo(
    req: SiteMemoRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """Claude writes a 1-paragraph operator-grade memo from the project full-doc.

    Never blocks more than ~10s; if Claude exceeds, returns a deferred
    task_id the UI can poll via GET /api/agent/site-memo/task/{task_id}.
    """
    _prune_memo_tasks()
    t_overall = time.monotonic()

    # 1. Resolve full-doc (or use caller-provided one)
    doc = req.full_doc
    if doc is None:
        try:
            doc = await asyncio.wait_for(
                _fetch_full_doc(pool, req.project_id),
                timeout=3.0,
            )
        except asyncio.TimeoutError:
            raise HTTPException(504, "full-doc fetch timed out (>3s)")
    if doc is None:
        raise HTTPException(404, f"Project {req.project_id} not found")

    provenance = [
        {"source": "design.full-doc", "kind": "cached"},
    ]
    for bucket in ("grid", "planning", "demand", "finance"):
        if doc.get(bucket):
            provenance.append({"source": bucket, "kind": "cached"})

    # 2. Try Claude with a hard wall-clock budget
    budget_s = 8.0
    remaining = budget_s - (time.monotonic() - t_overall)
    if remaining <= 1.5:
        # Not enough time — fall back immediately
        memo = _fallback_memo(doc)
        return {
            "project_id": req.project_id,
            "memo": memo,
            "key_points": _build_key_points_fallback(doc),
            "binding_constraint": None,
            "provenance": provenance,
            "model": "fallback",
            "tokens_used": None,
            "status": "fallback",
            "reason": "no time budget remaining for Claude call",
        }

    try:
        parsed, usage = await asyncio.wait_for(
            _claude_site_memo(claude, doc, req.max_sentences),
            timeout=remaining,
        )
        memo_text = (parsed.get("memo") or "").strip()
        if not memo_text:
            raise ValueError("empty memo from Claude")
        return {
            "project_id": req.project_id,
            "memo": memo_text,
            "key_points": parsed.get("key_points") or _build_key_points_fallback(doc),
            "binding_constraint": parsed.get("binding_constraint"),
            "provenance": provenance,
            "model": CLAUDE_MODEL,
            "tokens_used": usage,
            "status": "ok",
        }
    except asyncio.TimeoutError:
        # Spin a deferred task so the UI can poll
        task_id = _uuid.uuid4().hex[:12]
        _MEMO_TASKS[task_id] = {
            "status": "deferred",
            "memo": _fallback_memo(doc),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "_mono": time.monotonic(),
        }
        asyncio.create_task(_generate_memo_background(
            task_id, claude, doc, req.max_sentences, provenance, req.project_id,
        ))
        return {
            "project_id": req.project_id,
            "memo": _fallback_memo(doc),
            "key_points": _build_key_points_fallback(doc),
            "binding_constraint": None,
            "provenance": provenance,
            "model": "fallback",
            "tokens_used": None,
            "status": "deferred",
            "task_id": task_id,
        }
    except (anthropic.APIError, anthropic.APIConnectionError,
            anthropic.RateLimitError, json.JSONDecodeError, ValueError) as exc:
        log.warning("site-memo Claude call failed for %s: %s", req.project_id, exc)
        return {
            "project_id": req.project_id,
            "memo": _fallback_memo(doc),
            "key_points": _build_key_points_fallback(doc),
            "binding_constraint": None,
            "provenance": provenance,
            "model": "fallback",
            "tokens_used": None,
            "status": "fallback",
            "reason": f"{type(exc).__name__}: {exc}",
        }


async def _generate_memo_background(
    task_id: str,
    claude: anthropic.AsyncAnthropic,
    doc: dict,
    max_sentences: int,
    provenance: list,
    project_id: str,
) -> None:
    """Finish a memo after the HTTP response already returned (deferred path)."""
    try:
        parsed, usage = await asyncio.wait_for(
            _claude_site_memo(claude, doc, max_sentences),
            timeout=45.0,
        )
        memo_text = (parsed.get("memo") or "").strip()
        if memo_text:
            _MEMO_TASKS[task_id].update({
                "status": "ok",
                "memo": memo_text,
                "key_points": parsed.get("key_points") or [],
                "binding_constraint": parsed.get("binding_constraint"),
                "model": CLAUDE_MODEL,
                "tokens_used": usage,
                "provenance": provenance,
                "project_id": project_id,
            })
            return
    except Exception as exc:
        log.warning("deferred memo %s failed: %s", task_id, exc)
        _MEMO_TASKS[task_id].update({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        })


@router.get("/site-memo/task/{task_id}")
async def get_memo_task(task_id: str):
    _prune_memo_tasks()
    task = _MEMO_TASKS.get(task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found or expired")
    # Strip internal fields
    out = {k: v for k, v in task.items() if not k.startswith("_")}
    out["task_id"] = task_id
    return out
