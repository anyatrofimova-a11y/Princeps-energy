"""
Alert Engine — monitor regulatory data for changes and generate notifications.

Checks: new REPD planning applications, TEC queue changes, DNO constraint updates,
new Ofgem/DESNZ consultations.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID, uuid4

import asyncpg

log = logging.getLogger("princeps.alert_engine")


# ── Table setup ──────────────────────────────────────────────────────────

CREATE_NOTIFICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    notification_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            TEXT DEFAULT 'default',
    alert_type         TEXT,
    title              TEXT NOT NULL,
    body               TEXT,
    severity           TEXT DEFAULT 'info',
    source_ref         TEXT,
    source_url         TEXT,
    site_id            UUID,
    read               BOOLEAN DEFAULT FALSE,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user   ON notifications (user_id, read);
CREATE INDEX IF NOT EXISTS idx_notifications_type   ON notifications (alert_type);
"""

CREATE_ALERT_RULES_SQL = """
CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            TEXT DEFAULT 'default',
    rule_type          TEXT NOT NULL,
    enabled            BOOLEAN DEFAULT TRUE,
    config             JSONB DEFAULT '{}',
    site_id            UUID,
    lat                DOUBLE PRECISION,
    lon                DOUBLE PRECISION,
    radius_km          DOUBLE PRECISION DEFAULT 10,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules (user_id, enabled);
"""


async def setup_notifications_table(conn: asyncpg.Connection):
    """Create notifications and alert_rules tables."""
    for sql in [CREATE_NOTIFICATIONS_SQL, CREATE_ALERT_RULES_SQL]:
        for stmt in sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
    log.info("notifications + alert_rules tables ensured")


# ── Notification helpers ─────────────────────────────────────────────────

async def _insert_notification(
    conn: asyncpg.Connection,
    alert_type: str,
    title: str,
    body: str,
    severity: str = "info",
    source_ref: str | None = None,
    source_url: str | None = None,
    site_id: UUID | None = None,
    user_id: str = "default",
):
    """Insert a single notification."""
    await conn.execute("""
        INSERT INTO notifications (user_id, alert_type, title, body, severity, source_ref, source_url, site_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, user_id, alert_type, title, body, severity, source_ref, source_url, site_id)


# ── Check: new REPD planning applications ────────────────────────────────

async def check_new_planning_applications(conn: asyncpg.Connection) -> int:
    """Detect REPD projects added in the last 24 hours."""
    rows = await conn.fetch("""
        SELECT repd_id, site_name, technology, capacity_mw, status, developer, region
        FROM repd_projects
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY capacity_mw DESC NULLS LAST
        LIMIT 50
    """)

    count = 0
    for r in rows:
        cap = f"{r['capacity_mw']:.1f} MW" if r["capacity_mw"] else "unknown capacity"
        await _insert_notification(
            conn,
            alert_type="new_planning",
            title=f"New REPD: {r['site_name'] or 'Unnamed'}",
            body=(
                f"{r['technology'] or 'Unknown'} project ({cap}) — {r['status']} "
                f"in {r['region'] or 'unknown region'}. Developer: {r['developer'] or 'unknown'}."
            ),
            severity="info",
            source_ref=r["repd_id"],
        )
        count += 1

    return count


# ── Check: TEC queue changes ────────────────────────────────────────────

async def check_tec_queue_changes(conn: asyncpg.Connection) -> int:
    """Detect new or changed TEC register entries in the last 24 hours."""
    rows = await conn.fetch("""
        SELECT tec_id, customer_name, connection_site, tec_mw, status, fuel_type
        FROM eso_tec_register
        WHERE updated_at > NOW() - INTERVAL '24 hours'
        ORDER BY tec_mw DESC NULLS LAST
        LIMIT 50
    """)

    count = 0
    for r in rows:
        mw = f"{r['tec_mw']:.0f} MW" if r["tec_mw"] else "unknown MW"
        await _insert_notification(
            conn,
            alert_type="tec_change",
            title=f"TEC update: {r['connection_site'] or 'Unknown site'}",
            body=(
                f"{r['customer_name'] or 'Unknown'} — {r['fuel_type'] or ''} {mw}, "
                f"status: {r['status'] or 'unknown'}."
            ),
            severity="info",
            source_ref=r["tec_id"],
        )
        count += 1

    return count


# ── Check: DNO constraint changes ───────────────────────────────────────

async def check_dno_constraint_changes(conn: asyncpg.Connection) -> int:
    """Detect grid upgrade status changes in the last 24 hours."""
    rows = await conn.fetch("""
        SELECT upgrade_id, dno, project_name, status, capex_gbp, capacity_released_mw
        FROM grid_upgrades
        WHERE updated_at > NOW() - INTERVAL '24 hours'
        ORDER BY capex_gbp DESC NULLS LAST
        LIMIT 30
    """)

    count = 0
    for r in rows:
        cap = f"{r['capacity_released_mw']:.0f} MW released" if r["capacity_released_mw"] else ""
        await _insert_notification(
            conn,
            alert_type="dno_update",
            title=f"Grid upgrade: {r['project_name'] or 'Unnamed'}",
            body=(
                f"{r['dno'] or ''} — status: {r['status'] or 'unknown'}. "
                f"{cap}"
            ),
            severity="info" if r["status"] != "Completed" else "warning",
            source_ref=str(r["upgrade_id"]),
        )
        count += 1

    return count


# ── Check: new Ofgem/DESNZ consultations ────────────────────────────────

async def check_ofgem_consultations(conn: asyncpg.Connection) -> int:
    """Detect new documents in rag_documents added in the last 24 hours."""
    rows = await conn.fetch("""
        SELECT doc_id, source, title, url, doc_type
        FROM rag_documents
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 20
    """)

    count = 0
    for r in rows:
        await _insert_notification(
            conn,
            alert_type="new_consultation",
            title=f"New {r['source'] or 'regulatory'} document",
            body=r["title"] or "Untitled document",
            severity="info",
            source_ref=str(r["doc_id"]),
            source_url=r["url"],
        )
        count += 1

    return count


# ── Orchestrator ─────────────────────────────────────────────────────────

async def run_daily_alert_check(conn: asyncpg.Connection) -> dict:
    """Run all alert checks and return summary."""
    t0 = time.time()
    results = {}

    try:
        results["new_planning"] = await check_new_planning_applications(conn)
    except Exception as e:
        log.warning("REPD alert check failed: %s", e)
        results["new_planning_error"] = str(e)

    try:
        results["tec_changes"] = await check_tec_queue_changes(conn)
    except Exception as e:
        log.warning("TEC alert check failed: %s", e)
        results["tec_changes_error"] = str(e)

    try:
        results["dno_updates"] = await check_dno_constraint_changes(conn)
    except Exception as e:
        log.warning("DNO alert check failed: %s", e)
        results["dno_updates_error"] = str(e)

    try:
        results["new_consultations"] = await check_ofgem_consultations(conn)
    except Exception as e:
        log.warning("Consultation alert check failed: %s", e)
        results["new_consultations_error"] = str(e)

    total = sum(v for v in results.values() if isinstance(v, int))
    elapsed = round(time.time() - t0, 1)
    log.info("Daily alert check: %d notifications created in %.1fs", total, elapsed)

    return {"total_notifications": total, "details": results, "elapsed_s": elapsed}


# ── CRUD: notifications ──────────────────────────────────────────────────

async def get_notifications(
    conn: asyncpg.Connection,
    user_id: str = "default",
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Retrieve notifications for a user."""
    conditions = ["user_id = $1"]
    params: list[Any] = [user_id]

    if unread_only:
        conditions.append("read = FALSE")

    where = "WHERE " + " AND ".join(conditions)

    rows = await conn.fetch(f"""
        SELECT notification_id, alert_type, title, body, severity,
               source_ref, source_url, site_id, read, created_at
        FROM notifications
        {where}
        ORDER BY created_at DESC
        LIMIT {limit}
    """, *params)

    return [
        {
            **dict(r),
            "notification_id": str(r["notification_id"]),
            "site_id": str(r["site_id"]) if r["site_id"] else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def mark_notification_read(conn: asyncpg.Connection, notification_id: str):
    """Mark a single notification as read."""
    await conn.execute(
        "UPDATE notifications SET read = TRUE WHERE notification_id = $1",
        notification_id if isinstance(notification_id, UUID) else UUID(notification_id),
    )


async def mark_all_read(conn: asyncpg.Connection, user_id: str = "default"):
    """Mark all notifications as read for a user."""
    await conn.execute(
        "UPDATE notifications SET read = TRUE WHERE user_id = $1 AND read = FALSE",
        user_id,
    )


# ── CRUD: alert rules ───────────────────────────────────────────────────

async def get_alert_rules(conn: asyncpg.Connection, user_id: str = "default") -> list[dict]:
    """List alert rules for a user."""
    rows = await conn.fetch("""
        SELECT rule_id, rule_type, enabled, config, site_id, lat, lon, radius_km, created_at
        FROM alert_rules
        WHERE user_id = $1
        ORDER BY created_at DESC
    """, user_id)

    return [
        {
            **dict(r),
            "rule_id": str(r["rule_id"]),
            "site_id": str(r["site_id"]) if r["site_id"] else None,
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def create_alert_rule(
    conn: asyncpg.Connection,
    user_id: str = "default",
    *,
    rule_type: str,
    config: dict | None = None,
    site_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 10,
) -> dict:
    """Create a new alert rule."""
    rule_id = uuid4()
    site_uuid = UUID(site_id) if site_id else None

    await conn.execute("""
        INSERT INTO alert_rules (rule_id, user_id, rule_type, config, site_id, lat, lon, radius_km)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """,
        rule_id, user_id, rule_type,
        json_module_dumps(config or {}),
        site_uuid, lat, lon, radius_km,
    )

    return {"rule_id": str(rule_id), "rule_type": rule_type, "enabled": True}


async def delete_alert_rule(conn: asyncpg.Connection, rule_id: str):
    """Delete an alert rule."""
    await conn.execute(
        "DELETE FROM alert_rules WHERE rule_id = $1",
        rule_id if isinstance(rule_id, UUID) else UUID(rule_id),
    )


# Avoid name collision with json module
import json as json_module_lib
json_module_dumps = json_module_lib.dumps
