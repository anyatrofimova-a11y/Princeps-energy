"""Portfolio Performance — aggregate BESS revenue + an Updates feed.

Two endpoints used by the Mission Control "Portfolio Performance" tile
and the new "Updates" tab.

  GET /api/portfolio/bess-revenue
       Aggregate P10/P50/P90 across all BESS sites with snapshots.
       Today's hour + 24h sum + 7d sum + 30d sum + per-site breakdown.

  GET /api/portfolio/updates?limit=50
       Unified activity feed: project stage changes, council verdicts,
       new dockets, alert firings, dataset refreshes — newest first.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

log = logging.getLogger("princeps.portfolio_performance")
router = APIRouter(prefix="/api/portfolio", tags=["portfolio-performance"])


@router.get("/bess-revenue")
async def bess_revenue(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """Aggregate BESS revenue across all sites with live snapshots."""
    now = datetime.now(timezone.utc)
    cutoffs = {
        "today_h":  now - timedelta(hours=1),
        "today_24h": now - timedelta(hours=24),
        "rolling_7d": now - timedelta(days=7),
        "rolling_30d": now - timedelta(days=30),
    }
    out: dict[str, Any] = {"now": now.isoformat(), "windows": {}, "per_site": []}

    try:
        async with pool.acquire(timeout=10) as conn:
            for window, since in cutoffs.items():
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(DISTINCT rid) AS n_sites,
                           COUNT(*)::int       AS n_obs,
                           COALESCE(SUM(p10_rev_gbp), 0)::numeric AS p10,
                           COALESCE(SUM(p50_rev_gbp), 0)::numeric AS p50,
                           COALESCE(SUM(p90_rev_gbp), 0)::numeric AS p90
                    FROM bess_live_revenue_snapshots
                    WHERE ts >= $1
                    """,
                    since,
                )
                out["windows"][window] = {
                    "n_sites": row["n_sites"] or 0,
                    "n_obs":   row["n_obs"] or 0,
                    "p10_gbp": float(row["p10"] or 0),
                    "p50_gbp": float(row["p50"] or 0),
                    "p90_gbp": float(row["p90"] or 0),
                }

            # Per-site 24h aggregate, sorted by p50 desc
            sites = await conn.fetch(
                """
                SELECT rid,
                       COUNT(*)::int AS obs_24h,
                       SUM(p50_rev_gbp)::numeric AS p50_24h,
                       MAX(ts) AS latest_ts
                FROM bess_live_revenue_snapshots
                WHERE ts >= $1
                GROUP BY rid
                ORDER BY p50_24h DESC
                """,
                cutoffs["today_24h"],
            )
            out["per_site"] = [
                {
                    "rid": s["rid"],
                    "obs_24h": s["obs_24h"],
                    "p50_24h_gbp": float(s["p50_24h"] or 0),
                    "latest_ts": s["latest_ts"].isoformat() if s["latest_ts"] else None,
                }
                for s in sites
            ]
    except asyncpg.UndefinedTableError:
        return {
            "now": now.isoformat(),
            "windows": {k: {"n_sites": 0, "n_obs": 0, "p10_gbp": 0, "p50_gbp": 0, "p90_gbp": 0} for k in cutoffs},
            "per_site": [],
            "warning": "bess_live_revenue_snapshots not provisioned",
        }
    return out


@router.get("/updates")
async def portfolio_updates(
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Unified activity feed across project stage history, council
    sessions, alert firings, dataset refreshes, council activity."""
    out: list[dict[str, Any]] = []

    async def _safe_fetch(sql: str, *args) -> list[asyncpg.Record]:
        try:
            async with pool.acquire(timeout=5) as conn:
                return list(await conn.fetch(sql, *args))
        except Exception as exc:  # noqa: BLE001
            log.debug("updates fetch failed: %s", exc)
            return []

    # 1. Project stage changes (latest)
    for r in await _safe_fetch(
        """
        SELECT p.project_id, p.name, h.from_stage, h.to_stage, h.changed_at
        FROM project_stage_history h
        JOIN projects p ON p.project_id = h.project_id
        ORDER BY h.changed_at DESC
        LIMIT $1
        """,
        limit,
    ):
        out.append({
            "kind": "stage_change",
            "ts":   r["changed_at"].isoformat() if r["changed_at"] else None,
            "title": f"{r['name']} → {r['to_stage']}",
            "subtitle": f"From {r['from_stage'] or 'new'} to {r['to_stage']}",
            "ref":   {"type": "project", "id": str(r["project_id"])},
        })

    # 2. Council session verdicts
    for r in await _safe_fetch(
        """
        SELECT session_rid, query, final_verdict, created_at
        FROM council_sessions
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    ):
        verdict = r["final_verdict"]
        verdict_label = (verdict.get("verdict") if isinstance(verdict, dict) else None) or "REVIEWED"
        out.append({
            "kind": "council",
            "ts":   r["created_at"].isoformat() if r["created_at"] else None,
            "title": f"Council {verdict_label.lower()} — {(r['query'] or '')[:80]}",
            "subtitle": r["session_rid"],
            "ref":  {"type": "council_session", "id": r["session_rid"]},
        })

    # 3. Recent dockets
    for r in await _safe_fetch(
        """
        SELECT docket_id, title, source, opened_at, statutory_deadline
        FROM dockets
        ORDER BY opened_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    ):
        out.append({
            "kind": "docket",
            "ts":   r["opened_at"].isoformat() if r["opened_at"] else None,
            "title": (r["title"] or "")[:120],
            "subtitle": f"{r['source']} · deadline {r['statutory_deadline'] or 'tbd'}",
            "ref":  {"type": "docket", "id": str(r["docket_id"])},
        })

    # 4. Dataset refreshes (Connector health)
    for r in await _safe_fetch(
        """
        SELECT slug, last_refreshed_at, last_row_count, health_status
        FROM princeps_datasets
        WHERE last_refreshed_at IS NOT NULL
        ORDER BY last_refreshed_at DESC
        LIMIT $1
        """,
        limit,
    ):
        out.append({
            "kind": "dataset_refresh",
            "ts":   r["last_refreshed_at"].isoformat() if r["last_refreshed_at"] else None,
            "title": f"{r['slug']} refreshed",
            "subtitle": f"{r['last_row_count'] or 0:,} rows · {r['health_status'] or 'unknown'}",
            "ref":  {"type": "dataset", "id": r["slug"]},
        })

    # Sort all by ts desc, drop nulls, trim
    out = [u for u in out if u.get("ts")]
    out.sort(key=lambda u: u["ts"], reverse=True)
    return {"updates": out[:limit], "count": len(out[:limit])}
