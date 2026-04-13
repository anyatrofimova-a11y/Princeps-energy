"""
Grid events, alerts, and notifications — capability 2 of the Pulse suite.

Provides:
  * grid_events persistence
  * diff cycle against TEC register + substation headroom snapshots
  * alert rule evaluation → notifications
  * in-process EventBus for WebSocket fan-out
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg

log = logging.getLogger("princeps.grid_events")

_SCHEMA_PATH = Path(__file__).parent / "grid_events_schema.sql"


# ────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────

async def setup_schema(conn: asyncpg.Connection) -> None:
    """Run the grid_events schema idempotently."""
    sql = _SCHEMA_PATH.read_text()
    clean = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    for stmt in clean.split(";"):
        if stmt.strip():
            await conn.execute(stmt)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Startup hook — ensure tables exist."""
    async with pool.acquire() as conn:
        await setup_schema(conn)
    log.info("grid_events schema ready")


# ────────────────────────────────────────────────────────────────────────
# EventBus — in-process pub/sub for WebSocket fan-out
# ────────────────────────────────────────────────────────────────────────

class EventBus:
    """Fan-out bus — subscribers get an async iterator of events."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: dict) -> None:
        """Publish an event to all active subscribers."""
        async with self._lock:
            dead: list[asyncio.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    async def subscribe(self, maxsize: int = 200) -> AsyncIterator[dict]:
        """Subscribe and receive events as an async iterator."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


event_bus = EventBus()


# ────────────────────────────────────────────────────────────────────────
# Emit events + evaluate alert rules
# ────────────────────────────────────────────────────────────────────────

async def emit_event(
    pool: asyncpg.Pool,
    event_type: str,
    severity: str = "info",
    project_id: str | None = None,
    substation_id: str | None = None,
    upgrade_id: int | None = None,
    payload: dict | None = None,
    source: str = "system",
    observed_at: datetime | None = None,
) -> int:
    """Persist a grid event, fan out via EventBus, and evaluate alert rules."""
    async with pool.acquire() as conn:
        event_id = await conn.fetchval(
            """
            INSERT INTO grid_events
                (event_type, severity, project_id, substation_id, upgrade_id,
                 payload, source, observed_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            RETURNING event_id
            """,
            event_type, severity, project_id, substation_id, upgrade_id,
            json.dumps(payload or {}), source, observed_at,
        )

        event = {
            "event_id": event_id,
            "event_type": event_type,
            "severity": severity,
            "project_id": project_id,
            "substation_id": substation_id,
            "upgrade_id": upgrade_id,
            "payload": payload or {},
            "source": source,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        # Fan out live
        await event_bus.publish({"kind": "grid_event", "event": event})
        # Evaluate rules
        await _evaluate_rules(conn, event_id, event)
        return int(event_id)


async def emit_events_batch(pool: asyncpg.Pool, events: list[dict]) -> list[int]:
    """Emit a batch of events. Each dict: {event_type, severity?, project_id?, payload?, source?}."""
    ids = []
    for e in events:
        eid = await emit_event(
            pool,
            event_type=e["event_type"],
            severity=e.get("severity", "info"),
            project_id=e.get("project_id"),
            substation_id=e.get("substation_id"),
            upgrade_id=e.get("upgrade_id"),
            payload=e.get("payload"),
            source=e.get("source", "system"),
        )
        ids.append(eid)
    return ids


_SEVERITY_ORDER = {"info": 0, "warn": 1, "critical": 2}


async def _evaluate_rules(conn: asyncpg.Connection, event_id: int, event: dict) -> None:
    """Match the event against alert_rules and insert notifications for each hit."""
    rules = await conn.fetch("SELECT * FROM alert_rules WHERE enabled = TRUE")
    for r in rules:
        types = list(r["event_types"] or [])
        if types and event["event_type"] not in types:
            continue
        if _SEVERITY_ORDER.get(event["severity"], 0) < _SEVERITY_ORDER.get(r["min_severity"] or "info", 0):
            continue
        # project_scope matching is permissive for now (default scope matches everything)
        scope = r["project_scope"] or "all"
        if scope == "by_region" and r["scope_value"]:
            if (event.get("payload") or {}).get("region") != r["scope_value"]:
                continue
        if scope == "by_technology" and r["scope_value"]:
            if (event.get("payload") or {}).get("technology") != r["scope_value"]:
                continue

        title = f"{event['event_type'].replace('_', ' ').title()}"
        body = (event.get("payload") or {}).get("summary") or json.dumps(event.get("payload") or {})[:280]
        notif_id = await conn.fetchval(
            """
            INSERT INTO notifications (user_id, rule_id, event_id, title, body, read)
            VALUES ($1, $2, $3, $4, $5, FALSE)
            RETURNING notification_id
            """,
            r["user_id"], r["rule_id"], event_id, title, body,
        )
        await event_bus.publish({
            "kind": "notification",
            "notification": {
                "notification_id": notif_id,
                "user_id": r["user_id"],
                "rule_id": r["rule_id"],
                "event_id": event_id,
                "title": title,
                "body": body,
            },
        })


# ────────────────────────────────────────────────────────────────────────
# Diff cycle — TEC register + substation headroom
# ────────────────────────────────────────────────────────────────────────

def _hash_row(*fields: Any) -> str:
    """Stable hash for diff detection."""
    s = "|".join("" if f is None else str(f) for f in fields)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


async def diff_tec_register(pool: asyncpg.Pool) -> list[dict]:
    """Compare live TEC register rows against the stored snapshot. Return event dicts."""
    events: list[dict] = []
    async with pool.acquire() as conn:
        tec_exists = await conn.fetchval("SELECT to_regclass('public.eso_tec_register') IS NOT NULL")
        if not tec_exists:
            return events

        current = await conn.fetch(
            """
            SELECT tec_id, status, tec_mw, effective_from
            FROM eso_tec_register
            WHERE tec_id IS NOT NULL
            """
        )
        current_map = {r["tec_id"]: r for r in current}

        prior = {
            r["tec_id"]: r
            for r in await conn.fetch("SELECT tec_id, hash, status, tec_mw, offer_date FROM tec_register_snapshot")
        }

        # New + changed
        for tec_id, row in current_map.items():
            new_hash = _hash_row(row["status"], row["tec_mw"], row["effective_from"])
            old = prior.get(tec_id)
            if old is None:
                events.append({
                    "event_type": "new_offer",
                    "severity": "info",
                    "project_id": tec_id,
                    "payload": {
                        "status": row["status"],
                        "capacity_mw": float(row["tec_mw"] or 0),
                        "offer_date": str(row["effective_from"]) if row["effective_from"] else None,
                        "summary": f"New TEC offer: {row['status']}, {row['tec_mw']} MW",
                    },
                    "source": "tec_register_diff",
                })
            elif old["hash"] != new_hash:
                old_mw = float(old["tec_mw"] or 0)
                new_mw = float(row["tec_mw"] or 0)
                if old["status"] != row["status"]:
                    ev_type = "restudy"
                    sev = "warn"
                elif abs(old_mw - new_mw) > 0.01:
                    ev_type = "restudy"
                    sev = "warn"
                else:
                    ev_type = "new_offer"
                    sev = "info"
                events.append({
                    "event_type": ev_type,
                    "severity": sev,
                    "project_id": tec_id,
                    "payload": {
                        "old_status": old["status"],
                        "new_status": row["status"],
                        "old_capacity_mw": old_mw,
                        "new_capacity_mw": new_mw,
                        "summary": f"TEC change: {old['status']}→{row['status']}, {old_mw}→{new_mw} MW",
                    },
                    "source": "tec_register_diff",
                })

        # Withdrawals (rows in snapshot but not current)
        for tec_id in set(prior.keys()) - set(current_map.keys()):
            events.append({
                "event_type": "withdrawal",
                "severity": "critical",
                "project_id": tec_id,
                "payload": {
                    "last_status": prior[tec_id]["status"],
                    "summary": f"Project withdrawn from TEC register",
                },
                "source": "tec_register_diff",
            })

        # Update snapshot table
        async with conn.transaction():
            await conn.execute("TRUNCATE tec_register_snapshot")
            if current_map:
                await conn.executemany(
                    """
                    INSERT INTO tec_register_snapshot (tec_id, hash, status, tec_mw, offer_date, last_seen)
                    VALUES ($1, $2, $3, $4, $5, now())
                    """,
                    [
                        (
                            r["tec_id"],
                            _hash_row(r["status"], r["tec_mw"], r["effective_from"]),
                            r["status"],
                            r["tec_mw"],
                            r["effective_from"],
                        )
                        for r in current
                    ],
                )
    return events


async def diff_substation_headroom(pool: asyncpg.Pool) -> list[dict]:
    """Compare substation headroom against stored snapshot. Return event dicts."""
    events: list[dict] = []
    async with pool.acquire() as conn:
        sub_exists = await conn.fetchval("SELECT to_regclass('public.grid_substations') IS NOT NULL")
        if not sub_exists:
            return events

        # Try common column names for substation id and headroom
        try:
            current = await conn.fetch(
                """
                SELECT COALESCE(external_id, id::TEXT) AS substation_id,
                       COALESCE(demand_headroom_mw, 0) AS headroom_mw
                FROM grid_substations
                WHERE demand_headroom_mw IS NOT NULL
                """
            )
        except Exception:
            return events

        prior = {
            r["substation_id"]: r
            for r in await conn.fetch("SELECT substation_id, headroom_mw, hash FROM substation_snapshot")
        }

        for r in current:
            sid = r["substation_id"]
            new_hr = float(r["headroom_mw"] or 0)
            new_hash = _hash_row(new_hr)
            old = prior.get(sid)
            if old is None:
                continue  # first pass — just store, no event
            old_hr = float(old["headroom_mw"] or 0)
            if abs(new_hr - old_hr) > 0.5:  # threshold: 0.5 MW
                delta = new_hr - old_hr
                events.append({
                    "event_type": "substation_headroom_change",
                    "severity": "warn" if abs(delta) > 5 else "info",
                    "substation_id": sid,
                    "payload": {
                        "old_headroom_mw": old_hr,
                        "new_headroom_mw": new_hr,
                        "delta_mw": delta,
                        "summary": f"Substation {sid} headroom {old_hr:.1f}→{new_hr:.1f} MW",
                    },
                    "source": "substation_diff",
                })

        async with conn.transaction():
            await conn.execute("TRUNCATE substation_snapshot")
            if current:
                await conn.executemany(
                    """
                    INSERT INTO substation_snapshot (substation_id, headroom_mw, hash, last_seen)
                    VALUES ($1, $2, $3, now())
                    """,
                    [(r["substation_id"], float(r["headroom_mw"] or 0), _hash_row(r["headroom_mw"])) for r in current],
                )
    return events


async def run_full_diff_cycle(pool: asyncpg.Pool) -> dict:
    """Run TEC + substation diffs, persist events, return summary."""
    t0 = time.monotonic()
    events: list[dict] = []
    try:
        events += await diff_tec_register(pool)
    except Exception as e:
        log.warning("TEC diff failed: %s", e)
    try:
        events += await diff_substation_headroom(pool)
    except Exception as e:
        log.warning("substation diff failed: %s", e)

    ids = await emit_events_batch(pool, events) if events else []
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1

    return {
        "new_events": len(events),
        "event_ids": ids,
        "by_type": by_type,
        "duration_ms": round((time.monotonic() - t0) * 1000, 1),
    }


# ────────────────────────────────────────────────────────────────────────
# Read-side
# ────────────────────────────────────────────────────────────────────────

async def list_events(
    pool: asyncpg.Pool,
    project_id: str | None = None,
    event_type: str | None = None,
    min_severity: str = "info",
    since: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    """List events with filters. Newest first."""
    min_level = _SEVERITY_ORDER.get(min_severity, 0)
    conditions = []
    params: list[Any] = []
    idx = 1
    if project_id:
        conditions.append(f"project_id = ${idx}")
        params.append(project_id)
        idx += 1
    if event_type:
        conditions.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1
    if since:
        conditions.append(f"detected_at >= ${idx}")
        params.append(since)
        idx += 1
    sql = f"""
        SELECT event_id, event_type, severity, project_id, substation_id,
               upgrade_id, payload, source, detected_at, observed_at
        FROM grid_events
        {"WHERE " + " AND ".join(conditions) if conditions else ""}
        ORDER BY detected_at DESC
        LIMIT ${idx}
    """
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    out = []
    for r in rows:
        if _SEVERITY_ORDER.get(r["severity"], 0) < min_level:
            continue
        out.append({
            "event_id": int(r["event_id"]),
            "event_type": r["event_type"],
            "severity": r["severity"],
            "project_id": r["project_id"],
            "substation_id": r["substation_id"],
            "upgrade_id": r["upgrade_id"],
            "payload": r["payload"] or {},
            "source": r["source"],
            "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
        })
    return out


async def list_notifications(
    pool: asyncpg.Pool,
    user_id: str = "default",
    unread_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    """List notifications for a user."""
    where = "user_id = $1"
    params: list[Any] = [user_id]
    if unread_only:
        where += " AND read = FALSE"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT notification_id, user_id, rule_id, event_id, title, body, read, created_at
            FROM notifications
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT $2
            """,
            *params, limit,
        )
    return [
        {
            "notification_id": int(r["notification_id"]),
            "user_id": r["user_id"],
            "rule_id": r["rule_id"],
            "event_id": int(r["event_id"]) if r["event_id"] else None,
            "title": r["title"],
            "body": r["body"],
            "read": r["read"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows
    ]


async def mark_notification_read(pool: asyncpg.Pool, notification_id: int) -> bool:
    """Mark a notification as read."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE notifications SET read = TRUE WHERE notification_id = $1",
            notification_id,
        )
    return "UPDATE 1" in result


async def create_alert_rule(pool: asyncpg.Pool, **fields) -> int:
    """Insert a new alert rule. Returns rule_id."""
    async with pool.acquire() as conn:
        rid = await conn.fetchval(
            """
            INSERT INTO alert_rules
                (user_id, name, project_scope, scope_value, event_types, min_severity, channels, enabled)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING rule_id
            """,
            fields.get("user_id", "default"),
            fields.get("name", "Unnamed rule"),
            fields.get("project_scope", "all"),
            fields.get("scope_value"),
            fields.get("event_types", []),
            fields.get("min_severity", "info"),
            fields.get("channels", ["inapp"]),
            fields.get("enabled", True),
        )
    return int(rid)


async def list_alert_rules(pool: asyncpg.Pool, user_id: str = "default") -> list[dict]:
    """List alert rules for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM alert_rules WHERE user_id = $1 ORDER BY rule_id",
            user_id,
        )
    return [dict(r) for r in rows]


async def get_stats(pool: asyncpg.Pool, user_id: str = "default") -> dict:
    """Aggregate stats for the Pulse header strip."""
    async with pool.acquire() as conn:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        total_24h = await conn.fetchval("SELECT COUNT(*) FROM grid_events WHERE detected_at >= $1", since) or 0
        critical_24h = await conn.fetchval(
            "SELECT COUNT(*) FROM grid_events WHERE detected_at >= $1 AND severity = 'critical'", since
        ) or 0
        by_type_rows = await conn.fetch(
            "SELECT event_type, COUNT(*) AS n FROM grid_events WHERE detected_at >= $1 GROUP BY event_type",
            since,
        )
        unread = await conn.fetchval(
            "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND read = FALSE",
            user_id,
        ) or 0
    return {
        "events_24h": int(total_24h),
        "critical_24h": int(critical_24h),
        "by_type": {r["event_type"]: int(r["n"]) for r in by_type_rows},
        "unread_notifications": int(unread),
    }
