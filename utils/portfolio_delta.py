"""
Portfolio delta — capability 5 of the Pulse suite.

Nightly snapshots of every project's key metrics, with a delta API that
compares two snapshots and tags each change with the event that caused it.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import asyncpg

log = logging.getLogger("princeps.portfolio_delta")

# Reuse the schema file — it already contains portfolio_snapshots
from .grid_events import ensure_schema as ensure_events_schema  # re-export


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Ensure the portfolio_snapshots table exists (lives in grid_events_schema.sql)."""
    await ensure_events_schema(pool)


# ────────────────────────────────────────────────────────────────────────
# Snapshot
# ────────────────────────────────────────────────────────────────────────

async def take_snapshot(pool: asyncpg.Pool, taken_at: date | None = None) -> int:
    """Snapshot every project's key metrics for a given date (default today).

    Metrics captured per project:
      verdict, score, capacity_mw, stage, blocker, irr, cluster_exposure_gbp
    Idempotent on (taken_at, project_id) — re-running replaces values.
    """
    taken_at = taken_at or date.today()
    inserted = 0
    async with pool.acquire() as conn:
        projects_exists = await conn.fetchval(
            "SELECT to_regclass('public.projects') IS NOT NULL"
        )
        if not projects_exists:
            return 0

        # Read projects — be permissive about missing columns
        try:
            rows = await conn.fetch(
                """
                SELECT project_id, name, technology, capacity_mw, stage, verdict,
                       lat, lon, metadata
                FROM projects
                """
            )
        except Exception:
            return 0

        # Optional cluster exposure table
        cluster_exists = await conn.fetchval(
            "SELECT to_regclass('public.project_upgrade_allocations') IS NOT NULL"
        )

        for r in rows:
            proj_id = str(r["project_id"])
            raw_meta = r["metadata"]
            # asyncpg returns JSONB as str unless a codec is registered —
            # normalise to dict defensively so downstream `.get(...)` never
            # explodes regardless of pool configuration.
            if isinstance(raw_meta, str):
                try:
                    meta = json.loads(raw_meta) or {}
                except Exception:
                    meta = {}
            elif isinstance(raw_meta, dict):
                meta = raw_meta
            else:
                meta = {}
            score = _safe_num(meta.get("score") or meta.get("site_score") or meta.get("feasibility_score"))
            irr = _safe_num(meta.get("irr") or meta.get("simple_irr_pct"))
            blocker = meta.get("blocker")

            cluster_exposure = 0.0
            if cluster_exists:
                try:
                    cluster_exposure = float(
                        await conn.fetchval(
                            """
                            SELECT COALESCE(SUM(allocated_cost_gbp), 0)
                            FROM project_upgrade_allocations
                            WHERE project_id = $1 AND is_current
                            """,
                            proj_id,
                        ) or 0
                    )
                except Exception:
                    cluster_exposure = 0.0

            metrics = {
                "verdict": r["verdict"],
                "score": score,
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else None,
                "stage": r["stage"],
                "technology": r["technology"],
                "blocker": blocker,
                "irr": irr,
                "cluster_exposure_gbp": cluster_exposure,
            }

            await conn.execute(
                """
                INSERT INTO portfolio_snapshots (taken_at, project_id, metrics)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (taken_at, project_id) DO UPDATE SET
                    metrics = EXCLUDED.metrics, created_at = now()
                """,
                taken_at, proj_id, json.dumps(metrics),
            )
            inserted += 1
    return inserted


def _safe_num(v: Any) -> float | None:
    """Coerce to float or return None."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────────
# Delta computation
# ────────────────────────────────────────────────────────────────────────

_TRACKED_METRICS = ("verdict", "score", "capacity_mw", "stage", "irr", "cluster_exposure_gbp")


async def compute_deltas(
    pool: asyncpg.Pool,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """Compare two snapshots and return per-project per-metric deltas.

    For each changed metric, try to find the grid_events row that caused it
    (best-effort match on project_id within the date range).
    """
    async with pool.acquire() as conn:
        rows_from = await conn.fetch(
            "SELECT project_id, metrics FROM portfolio_snapshots WHERE taken_at = $1",
            from_date,
        )
        rows_to = await conn.fetch(
            "SELECT project_id, metrics FROM portfolio_snapshots WHERE taken_at = $1",
            to_date,
        )
        map_from = {r["project_id"]: _parse_metrics(r["metrics"]) for r in rows_from}
        map_to = {r["project_id"]: _parse_metrics(r["metrics"]) for r in rows_to}

        deltas: list[dict] = []
        for pid, to_m in map_to.items():
            from_m = map_from.get(pid, {})
            for metric in _TRACKED_METRICS:
                old = from_m.get(metric)
                new = to_m.get(metric)
                if old == new:
                    continue
                # Find a causing event
                try:
                    cause = await conn.fetchrow(
                        """
                        SELECT event_type, severity, detected_at, payload
                        FROM grid_events
                        WHERE project_id = $1
                          AND detected_at::date >= $2
                          AND detected_at::date <= $3
                        ORDER BY detected_at DESC
                        LIMIT 1
                        """,
                        pid, from_date, to_date,
                    )
                except Exception:
                    cause = None
                delta_val = _compute_numeric_delta(old, new)
                pct = _compute_pct(old, new)
                deltas.append({
                    "project_id": pid,
                    "metric": metric,
                    "old": old,
                    "new": new,
                    "delta": delta_val,
                    "pct_change": pct,
                    "event_cause": {
                        "event_type": cause["event_type"],
                        "severity": cause["severity"],
                        "detected_at": cause["detected_at"].isoformat(),
                    } if cause else None,
                })
    return deltas


def _parse_metrics(raw: Any) -> dict:
    """Parse the metrics JSONB column (asyncpg may give dict or str)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _compute_numeric_delta(old: Any, new: Any) -> float | None:
    """Numeric delta if both sides are numbers, else None."""
    if old is None or new is None:
        return None
    try:
        return float(new) - float(old)
    except (TypeError, ValueError):
        return None


def _compute_pct(old: Any, new: Any) -> float | None:
    """Percent change if both sides are numeric."""
    try:
        old_f = float(old)
        new_f = float(new)
        if old_f == 0:
            return None
        return (new_f - old_f) / old_f * 100.0
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────────
# Convenience
# ────────────────────────────────────────────────────────────────────────

async def get_latest_deltas(pool: asyncpg.Pool, user_id: str = "default", limit: int = 50) -> list[dict]:
    """Return deltas for the two most recent snapshots."""
    async with pool.acquire() as conn:
        dates = await conn.fetch(
            "SELECT DISTINCT taken_at FROM portfolio_snapshots ORDER BY taken_at DESC LIMIT 2"
        )
        if len(dates) < 2:
            return []
        to_date = dates[0]["taken_at"]
        from_date = dates[1]["taken_at"]
    deltas = await compute_deltas(pool, from_date, to_date)
    return sorted(
        deltas,
        key=lambda d: abs(d.get("delta") or 0),
        reverse=True,
    )[:limit]


async def weekly_summary(pool: asyncpg.Pool, user_id: str = "default") -> dict:
    """Aggregate weekly changes across the whole portfolio."""
    today = date.today()
    last_week = today - timedelta(days=7)
    deltas = await compute_deltas(pool, last_week, today)

    score_deltas = [d["delta"] for d in deltas if d["metric"] == "score" and d["delta"] is not None]
    gainers: list[dict] = []
    losers: list[dict] = []
    for d in deltas:
        if d["metric"] != "score" or d["delta"] is None:
            continue
        if d["delta"] > 0:
            gainers.append(d)
        elif d["delta"] < 0:
            losers.append(d)

    gainers.sort(key=lambda d: d["delta"] or 0, reverse=True)
    losers.sort(key=lambda d: d["delta"] or 0)

    return {
        "from_date": str(last_week),
        "to_date": str(today),
        "total_changes": len(deltas),
        "projects_improved": len(gainers),
        "projects_degraded": len(losers),
        "avg_score_delta": sum(score_deltas) / len(score_deltas) if score_deltas else 0,
        "biggest_gainers": gainers[:5],
        "biggest_losers": losers[:5],
    }
