"""
BESS Live Revenue router — REST + WebSocket surface for the live dashboard
widget on /v2 (feasi-frontend/src/components/bess/LiveBessRevenue.jsx).

Reads from bess_live_revenue_snapshots (written hourly by app/cron/
bess_revenue_cron.py). The WS endpoint subscribes to Postgres NOTIFY on
channel 'bess_live_revenue' (trigger defined in
migrations/2026_05_01_bess_live_revenue.sql) so new snapshots stream out
within the same tick they're written.

This router is mounted by app/main.py:_ROUTER_MODULES (entry: "bess_live").

Companion week-1 owner of the customer-facing live BESS surface; does NOT
touch app/chat.py, app/ontology/dispatch.py, app/reports/lender_im.py, or
app/agents/* (other weeks own those).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)

from app.deps import get_pool

log = logging.getLogger("princeps.bess_live")

router = APIRouter(tags=["bess-live"])

# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def _row_to_dict(row: asyncpg.Record) -> dict:
    """Serialise an asyncpg row from bess_live_revenue_snapshots."""
    sb = row["stack_breakdown"]
    if isinstance(sb, str):
        try:
            sb = json.loads(sb)
        except (json.JSONDecodeError, TypeError):
            sb = {}
    return {
        "snapshot_id": row["snapshot_id"],
        "rid": row["rid"],
        "ts": row["ts"].isoformat() if row["ts"] else None,
        "p10_rev_gbp": float(row["p10_rev_gbp"]),
        "p50_rev_gbp": float(row["p50_rev_gbp"]),
        "p90_rev_gbp": float(row["p90_rev_gbp"]),
        "stack_breakdown": sb,
        "modo_p50_forecast": (
            float(row["modo_p50_forecast"])
            if row["modo_p50_forecast"] is not None
            else None
        ),
        "source": row["source"],
    }


async def _resolve_default_rid(pool: asyncpg.Pool) -> str | None:
    """When the caller omits ``rid``, surface the most-recently-snapshotted
    site so the dashboard widget always has something to render. Returns
    ``None`` when the snapshots table isn't provisioned on this DB."""
    try:
        async with pool.acquire(timeout=5) as conn:
            return await conn.fetchval(
                """
                SELECT rid FROM bess_live_revenue_snapshots
                ORDER BY ts DESC
                LIMIT 1
                """
            )
    except asyncpg.UndefinedTableError:
        return None


# ───────────────────────────────────────────────────────────────────────────
# REST: 30d snapshot window for chart bootstrap.
# ───────────────────────────────────────────────────────────────────────────
@router.get("/api/bess/revenue-snapshot")
async def api_bess_revenue_snapshot(
    rid: str | None = Query(None, description="Site rid (project_id). Omit to use most-recent site."),
    days: int = Query(30, ge=1, le=180, description="Lookback window in days."),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return last <days> of hourly BESS revenue snapshots for a site.

    Frontend bootstrap: GET this once on widget mount, then upgrade to
    the /ws/bess-live-revenue WebSocket for live appends.
    """
    if rid is None:
        rid = await _resolve_default_rid(pool)
    if not rid:
        # Cron hasn't ticked yet — return empty so the frontend can render
        # the loading state instead of erroring.
        return {"rid": None, "snapshots": [], "count": 0, "warning": "no_data_yet"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        async with pool.acquire(timeout=10) as conn:
            rows = await conn.fetch(
                """
                SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                       stack_breakdown, modo_p50_forecast, source
                FROM bess_live_revenue_snapshots
                WHERE rid = $1 AND ts >= $2
                ORDER BY ts ASC
                """,
                rid, cutoff,
            )
    except asyncpg.UndefinedTableError:
        return {"rid": rid, "snapshots": [], "count": 0, "warning": "table_not_provisioned"}
    snapshots = [_row_to_dict(r) for r in rows]
    latest = snapshots[-1] if snapshots else None
    return {
        "rid": rid,
        "site_name": (latest or {}).get("stack_breakdown", {}).get("site_name") if latest else None,
        "snapshots": snapshots,
        "count": len(snapshots),
        "lookback_days": days,
        "latest_ts": latest["ts"] if latest else None,
    }


# ───────────────────────────────────────────────────────────────────────────
# REST: single-day stack breakdown — feeds the side-panel "today's split" view.
# ───────────────────────────────────────────────────────────────────────────
@router.get("/api/bess/revenue-stack-breakdown")
async def api_bess_revenue_stack_breakdown(
    rid: str | None = Query(None, description="Site rid."),
    date: str | None = Query(None, description="ISO date (YYYY-MM-DD). Omit for latest."),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the closest snapshot to the requested date for one site.

    The frontend uses this for the "today's split" right panel and the
    delta-vs-yesterday bar.
    """
    if rid is None:
        rid = await _resolve_default_rid(pool)
    if not rid:
        raise HTTPException(status_code=404, detail="No BESS snapshots yet")

    if date:
        try:
            target = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date: {date}")
    else:
        target = datetime.now(timezone.utc)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    yest_start = day_start - timedelta(days=1)

    async with pool.acquire(timeout=10) as conn:
        today = await conn.fetchrow(
            """
            SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                   stack_breakdown, modo_p50_forecast, source
            FROM bess_live_revenue_snapshots
            WHERE rid = $1 AND ts >= $2 AND ts < $3
            ORDER BY ts DESC LIMIT 1
            """,
            rid, day_start, day_end,
        )
        if today is None:
            # Fall back to the most-recent row so the widget renders
            # something useful when there's no row for the exact day.
            today = await conn.fetchrow(
                """
                SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                       stack_breakdown, modo_p50_forecast, source
                FROM bess_live_revenue_snapshots
                WHERE rid = $1
                ORDER BY ts DESC LIMIT 1
                """,
                rid,
            )
        yesterday = await conn.fetchrow(
            """
            SELECT p50_rev_gbp
            FROM bess_live_revenue_snapshots
            WHERE rid = $1 AND ts >= $2 AND ts < $3
            ORDER BY ts DESC LIMIT 1
            """,
            rid, yest_start, day_start,
        )

    if today is None:
        raise HTTPException(status_code=404, detail=f"No snapshot for rid={rid}")

    today_d = _row_to_dict(today)
    delta_gbp: float | None = None
    delta_pct: float | None = None
    if yesterday is not None and yesterday["p50_rev_gbp"]:
        y = float(yesterday["p50_rev_gbp"])
        delta_gbp = today_d["p50_rev_gbp"] - y
        delta_pct = (delta_gbp / y * 100.0) if y else None

    return {
        "rid": rid,
        "snapshot": today_d,
        "delta_vs_yesterday_gbp": delta_gbp,
        "delta_vs_yesterday_pct": delta_pct,
    }


# ───────────────────────────────────────────────────────────────────────────
# WebSocket: live append stream.
#
# Strategy: open a dedicated asyncpg connection (NOT a pool acquire — pool
# connections must NOT block on LISTEN), register a NOTIFY listener on
# channel 'bess_live_revenue', and forward every new snapshot for the
# requested rid down the wire.
#
# Fallback: if connection acquisition fails we degrade to a 60s poll loop.
# Keepalive: ping every 25s so intermediate proxies don't drop the socket.
# ───────────────────────────────────────────────────────────────────────────
@router.websocket("/ws/bess-live-revenue")
async def ws_bess_live_revenue(ws: WebSocket):
    await ws.accept()

    pool: asyncpg.Pool = ws.app.state.pool
    rid = ws.query_params.get("rid")

    # Resolve default rid if caller didn't pass one.
    try:
        if not rid:
            rid = await _resolve_default_rid(pool)
    except Exception:
        rid = None

    if not rid:
        await ws.send_json({"event": "error", "reason": "no_rid_available"})
        await ws.close()
        return

    # Send the latest existing snapshot immediately so the chart updates
    # within milliseconds of WS open (smoke test #3 requires < 60s).
    try:
        async with pool.acquire(timeout=5) as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                       stack_breakdown, modo_p50_forecast, source
                FROM bess_live_revenue_snapshots
                WHERE rid = $1
                ORDER BY ts DESC LIMIT 1
                """,
                rid,
            )
        if row:
            await ws.send_json({"event": "snapshot", "data": _row_to_dict(row)})
        else:
            await ws.send_json({
                "event": "hello",
                "rid": rid,
                "warning": "no_data_yet",
            })
    except Exception as e:
        log.debug("ws bootstrap snapshot failed: %s", e)

    queue: asyncio.Queue[int] = asyncio.Queue()

    async def _on_notify(_conn, _pid, _channel, payload: str):
        try:
            queue.put_nowait(int(payload))
        except (ValueError, asyncio.QueueFull):
            pass

    listen_conn: asyncpg.Connection | None = None
    try:
        listen_conn = await asyncpg.connect(
            dsn=__import__("os").environ.get("DATABASE_URL"),
        )
        await listen_conn.add_listener("bess_live_revenue", _on_notify)
        log.info("ws bess-live-revenue: LISTEN registered for rid=%s", rid)
    except Exception as e:
        log.warning("ws bess-live-revenue: LISTEN setup failed (%s) — falling back to poll", e)
        listen_conn = None

    try:
        last_seen_id = 0
        async with pool.acquire(timeout=5) as conn:
            last_seen_id = await conn.fetchval(
                "SELECT COALESCE(MAX(snapshot_id), 0) FROM bess_live_revenue_snapshots WHERE rid = $1",
                rid,
            ) or 0

        # Send a periodic ping in parallel.
        async def _ping_loop():
            while True:
                await asyncio.sleep(25)
                try:
                    await ws.send_json({"event": "ping", "ts": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    return

        ping_task = asyncio.create_task(_ping_loop())

        try:
            while True:
                if listen_conn is not None:
                    # Wait for NOTIFY or 60s timeout (degrade to poll).
                    try:
                        sid = await asyncio.wait_for(queue.get(), timeout=60.0)
                    except asyncio.TimeoutError:
                        sid = None
                else:
                    await asyncio.sleep(60)
                    sid = None

                if sid is not None:
                    # NOTIFY arrived — fetch that exact row, only push if
                    # rid matches (snapshots channel is shared across sites).
                    try:
                        async with pool.acquire(timeout=5) as conn:
                            row = await conn.fetchrow(
                                """
                                SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                                       stack_breakdown, modo_p50_forecast, source
                                FROM bess_live_revenue_snapshots
                                WHERE snapshot_id = $1
                                """,
                                sid,
                            )
                        if row and row["rid"] == rid:
                            last_seen_id = max(last_seen_id, row["snapshot_id"])
                            await ws.send_json({"event": "snapshot", "data": _row_to_dict(row)})
                    except Exception as e:
                        log.debug("ws fetch by snapshot_id failed: %s", e)
                else:
                    # Poll fallback — fetch any rows newer than last_seen_id.
                    try:
                        async with pool.acquire(timeout=5) as conn:
                            rows = await conn.fetch(
                                """
                                SELECT snapshot_id, rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                                       stack_breakdown, modo_p50_forecast, source
                                FROM bess_live_revenue_snapshots
                                WHERE rid = $1 AND snapshot_id > $2
                                ORDER BY snapshot_id ASC
                                """,
                                rid, last_seen_id,
                            )
                        for r in rows:
                            last_seen_id = max(last_seen_id, r["snapshot_id"])
                            await ws.send_json({"event": "snapshot", "data": _row_to_dict(r)})
                    except Exception as e:
                        log.debug("ws poll fallback failed: %s", e)
        finally:
            ping_task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.info("ws bess-live-revenue closed: %s", e)
    finally:
        if listen_conn is not None:
            try:
                await listen_conn.remove_listener("bess_live_revenue", _on_notify)
            except Exception:
                pass
            try:
                await listen_conn.close()
            except Exception:
                pass
