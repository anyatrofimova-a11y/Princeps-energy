"""Project KPI composite — viability, grid/planning risk, delta-IRR, critical path.

Architecture
------------
`compute_kpis(project_id)` fans out five sub-queries *concurrently* against
PostgreSQL (agent verdicts, grid connection analyses, planning predictions,
project snapshots, regulatory calendar) and folds the answers into a single
`ProjectKpis` dataclass. Target latency budget is p95 < 400 ms so every
sub-query is bounded by a 250 ms timeout and falls back to a safe default
on error — a single slow surface must never sink the whole strip.

Caching
-------
Results are cached for 1 hour. Redis is used when `REDIS_URL` is set in the
environment; otherwise an in-process TTL map is used. Both expose the same
`.get()` / `.set()` surface so call sites never branch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

log = logging.getLogger("princeps.project_kpis")

# ---------------------------------------------------------------------------
# Cache — Redis when available, in-process TTL map otherwise
# ---------------------------------------------------------------------------
_TTL_SECONDS = 3600  # 1 hour
_local_cache: dict[str, tuple[float, dict]] = {}

try:  # Soft dependency — Redis is optional in dev.
    import redis.asyncio as _redis_asyncio  # type: ignore
    _REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("REDIS_HOST_URL")
    _redis_client: Any = _redis_asyncio.from_url(_REDIS_URL) if _REDIS_URL else None
except Exception:
    _redis_client = None


async def _cache_get(key: str) -> dict | None:
    if _redis_client is not None:
        try:
            raw = await _redis_client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as e:  # noqa: BLE001
            log.debug("redis get failed: %s", e)
    entry = _local_cache.get(key)
    if entry:
        expiry, value = entry
        if expiry > time.time():
            return value
        _local_cache.pop(key, None)
    return None


async def _cache_set(key: str, value: dict, ttl: int = _TTL_SECONDS) -> None:
    if _redis_client is not None:
        try:
            await _redis_client.set(key, json.dumps(value), ex=ttl)
            return
        except Exception as e:  # noqa: BLE001
            log.debug("redis set failed: %s", e)
    _local_cache[key] = (time.time() + ttl, value)


async def invalidate_cache(project_id: str) -> None:
    """Drop cached KPIs for a project — called after snapshot writes."""
    key = f"project_kpis:{project_id}"
    if _redis_client is not None:
        try:
            await _redis_client.delete(key)
        except Exception as e:  # noqa: BLE001
            log.debug("redis del failed: %s", e)
    _local_cache.pop(key, None)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------
@dataclass
class ProjectKpis:
    project_id: str
    viability_pct: float          # 0-100 composite
    grid_risk_pct: float          # 0-100 higher = worse
    planning_risk_pct: float      # 0-100 higher = worse
    delta_irr_7d_bps: float       # signed basis-point change
    critical_path_days: int       # days until the next blocking deadline
    confidence: float             # 0-1 min across sub-scores
    last_updated_iso: str

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Sub-query helpers — each returns (score_0_100, confidence_0_1, detail_dict)
# ---------------------------------------------------------------------------
_SUB_TIMEOUT = 0.25  # 250 ms ceiling per sub-query


async def _q_viability(conn: asyncpg.Connection, project_id: str) -> tuple[float, float, dict]:
    """Average of AgentVerdict results across all intents for this project.

    We read from `agent_analyses` (written by agent.py) filtered to the
    project parcel. GO=90, CAUTION=55, NO-GO=20 is the standard Princeps
    weighting used in the feasibility dashboard.
    """
    try:
        rows = await asyncio.wait_for(
            conn.fetch(
                """
                SELECT intent, verdict, confidence, created_at
                FROM agent_analyses
                WHERE parcel_id = (
                    SELECT parcel_id FROM projects WHERE project_id::text = $1
                )
                  AND created_at > NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC
                LIMIT 48
                """,
                str(project_id),
            ),
            timeout=_SUB_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("viability query fallback: %s", e)
        return 62.0, 0.4, {"source": "fallback"}

    if not rows:
        return 62.0, 0.4, {"source": "no_data", "intent_count": 0}

    latest_by_intent: dict[str, dict] = {}
    for r in rows:
        if r["intent"] not in latest_by_intent:
            latest_by_intent[r["intent"]] = dict(r)

    weights = {"GO": 90.0, "CAUTION": 55.0, "NO-GO": 20.0}
    scores = [weights.get((v["verdict"] or "CAUTION").upper(), 55.0) for v in latest_by_intent.values()]
    confs = [float(v.get("confidence") or 0.5) for v in latest_by_intent.values()]
    return (
        round(sum(scores) / len(scores), 1),
        round(sum(confs) / len(confs), 2),
        {"intent_count": len(latest_by_intent), "intents": list(latest_by_intent.keys())},
    )


async def _q_grid_risk(conn: asyncpg.Connection, project_id: str) -> tuple[float, float, dict]:
    """Grid risk — combine verdict on `grid_connection` intent with DNO headroom."""
    try:
        row = await asyncio.wait_for(
            conn.fetchrow(
                """
                SELECT ga.verdict, ga.confidence, ga.result_json
                FROM grid_assessments ga
                JOIN projects p ON p.parcel_id = ga.parcel_id
                WHERE p.project_id::text = $1
                ORDER BY ga.created_at DESC
                LIMIT 1
                """,
                str(project_id),
            ),
            timeout=_SUB_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("grid_risk query fallback: %s", e)
        row = None

    if not row:
        return 45.0, 0.4, {"source": "fallback"}

    verdict = (row["verdict"] or "CAUTION").upper()
    risk = {"GO": 25.0, "CAUTION": 55.0, "NO-GO": 85.0}.get(verdict, 55.0)

    # Headroom refinement — parse JSON blob cheaply.
    detail: dict = {}
    try:
        blob = row["result_json"]
        if isinstance(blob, str):
            blob = json.loads(blob)
        headroom = float((blob or {}).get("headroom_mw") or 0)
        if headroom < 5:
            risk = min(100.0, risk + 15.0)
        elif headroom > 50:
            risk = max(5.0, risk - 10.0)
        detail = {"headroom_mw": headroom, "verdict": verdict}
    except Exception:
        detail = {"verdict": verdict}

    conf = float(row.get("confidence") or 0.55)
    return round(risk, 1), round(conf, 2), detail


async def _q_planning_risk(conn: asyncpg.Connection, project_id: str) -> tuple[float, float, dict]:
    """Planning risk — blend predicted approval prob with REPD precedent density."""
    try:
        row = await asyncio.wait_for(
            conn.fetchrow(
                """
                SELECT result_json, created_at
                FROM agent_analyses
                WHERE parcel_id = (SELECT parcel_id FROM projects WHERE project_id::text = $1)
                  AND intent = 'planning'
                ORDER BY created_at DESC LIMIT 1
                """,
                str(project_id),
            ),
            timeout=_SUB_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("planning_risk query fallback: %s", e)
        row = None

    approval_pct = 65.0
    precedent_count = 0
    detail: dict = {}

    if row:
        try:
            blob = row["result_json"]
            if isinstance(blob, str):
                blob = json.loads(blob)
            approval_pct = float((blob or {}).get("approval_pct", approval_pct))
            precedent_count = int((blob or {}).get("precedent_count", 0))
            detail = {"approval_pct": approval_pct, "precedent_count": precedent_count}
        except Exception:
            pass

    # Higher approval -> lower risk; more precedents -> lower risk.
    risk = 100.0 - approval_pct
    if precedent_count >= 5:
        risk = max(5.0, risk - 10.0)
    elif precedent_count == 0:
        risk = min(100.0, risk + 10.0)

    conf = 0.6 if row else 0.35
    return round(risk, 1), conf, detail


async def _q_delta_irr(conn: asyncpg.Connection, project_id: str) -> tuple[float, float, dict]:
    """Return IRR change (bps) between today and 7 days ago from project_snapshots."""
    try:
        rows = await asyncio.wait_for(
            conn.fetch(
                """
                SELECT irr_pct, created_at FROM project_snapshots
                WHERE project_id::text = $1
                  AND created_at > NOW() - INTERVAL '10 days'
                ORDER BY created_at DESC
                LIMIT 30
                """,
                str(project_id),
            ),
            timeout=_SUB_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("delta_irr query fallback: %s", e)
        return 0.0, 0.3, {"source": "fallback"}

    if not rows or len(rows) < 2:
        return 0.0, 0.3, {"source": "insufficient_history"}

    latest = float(rows[0]["irr_pct"] or 0)
    # Find first snapshot older than 7 days, else oldest available.
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    reference = rows[-1]
    for r in rows:
        if r["created_at"] and r["created_at"].timestamp() <= cutoff:
            reference = r
            break
    baseline = float(reference["irr_pct"] or 0)
    delta_bps = round((latest - baseline) * 100.0, 1)  # % -> bps
    return delta_bps, 0.8, {"latest_irr_pct": latest, "baseline_irr_pct": baseline}


async def _q_critical_path(conn: asyncpg.Connection, project_id: str) -> tuple[int, float, dict]:
    """Days until the next regulatory / stage deadline blocks progress."""
    try:
        row = await asyncio.wait_for(
            conn.fetchrow(
                """
                SELECT MIN(deadline_date) AS next_deadline
                FROM project_deadlines
                WHERE project_id::text = $1
                  AND deadline_date > NOW()
                  AND blocking = TRUE
                """,
                str(project_id),
            ),
            timeout=_SUB_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("critical_path query fallback: %s", e)
        row = None

    if not row or not row["next_deadline"]:
        return 90, 0.4, {"source": "default"}
    next_d = row["next_deadline"]
    days = max(0, (next_d - datetime.now(timezone.utc).date()).days
               if hasattr(next_d, "year") else 90)
    return int(days), 0.75, {"next_deadline": next_d.isoformat() if hasattr(next_d, "isoformat") else None}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def compute_kpis(
    project_id: str,
    pool: asyncpg.Pool | None = None,
    *,
    skip_cache: bool = False,
) -> ProjectKpis:
    """Return the five-number project KPI strip, cached for 1 hour."""
    key = f"project_kpis:{project_id}"

    if not skip_cache:
        cached = await _cache_get(key)
        if cached:
            return ProjectKpis(**cached)

    if pool is None:
        # Stand-alone fallback used by unit tests — no DB available.
        return _synthetic_kpis(project_id)

    async with pool.acquire() as conn:
        results = await asyncio.gather(
            _q_viability(conn, project_id),
            _q_grid_risk(conn, project_id),
            _q_planning_risk(conn, project_id),
            _q_delta_irr(conn, project_id),
            _q_critical_path(conn, project_id),
            return_exceptions=True,
        )

    (via, grid, plan, dirr, crit) = [
        r if not isinstance(r, Exception) else (0.0, 0.3, {"error": str(r)})
        for r in results
    ]

    viability_pct, via_conf, _ = via
    grid_risk_pct, grid_conf, _ = grid
    planning_risk_pct, plan_conf, _ = plan
    delta_irr_bps, dirr_conf, _ = dirr
    critical_path_days, crit_conf, _ = crit

    confidence = round(min(via_conf, grid_conf, plan_conf, dirr_conf, crit_conf), 2)

    kpi = ProjectKpis(
        project_id=str(project_id),
        viability_pct=float(viability_pct),
        grid_risk_pct=float(grid_risk_pct),
        planning_risk_pct=float(planning_risk_pct),
        delta_irr_7d_bps=float(delta_irr_bps),
        critical_path_days=int(critical_path_days),
        confidence=float(confidence),
        last_updated_iso=datetime.now(timezone.utc).isoformat(),
    )
    await _cache_set(key, kpi.as_dict())
    return kpi


def _synthetic_kpis(project_id: str) -> ProjectKpis:
    """Deterministic fixture used when no DB pool is passed (tests / demos)."""
    return ProjectKpis(
        project_id=str(project_id),
        viability_pct=72.0,
        grid_risk_pct=38.0,
        planning_risk_pct=42.0,
        delta_irr_7d_bps=18.5,
        critical_path_days=47,
        confidence=0.62,
        last_updated_iso=datetime.now(timezone.utc).isoformat(),
    )
