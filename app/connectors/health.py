"""Health computation for Magritte-style connectors.

A dataset's health is a function of:

  * Its registered ``freshness_threshold_hours`` (declared on the connector).
  * The ``last_refreshed_at`` + ``last_refresh_ok`` columns in
    ``princeps_datasets`` (written by :meth:`Connector.ingest`).
  * The actual row count of the destination table (a live ``count(*)``
    so a dropped/truncated table reads as red even if the registry says
    last refresh was fine).

Status logic
------------

  * ``red``    — last refresh failed, OR age > 2× threshold, OR the
                 destination table is empty / missing.
  * ``yellow`` — age > threshold but ≤ 2× threshold.
  * ``green``  — age ≤ threshold and the destination table has rows.
  * ``unknown``— never refreshed (no ``last_refreshed_at`` yet) and the
                 table has no rows.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from .base import HealthCheck

log = logging.getLogger("princeps.connectors.health")

# Identifier whitelist — only [a-zA-Z0-9_] schema/table names allowed in
# the live count(*) query, so we can't be tricked into SQL injection by
# a connector author who declares ``table_name = 'x; DROP TABLE …'``.
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$")


def _safe_table(table_name: str) -> Optional[str]:
    """Return *table_name* if it's a safe ``schema.table`` or ``table``,
    else ``None``. Asyncpg has no native identifier quoting, so we
    whitelist instead of escaping."""
    if not table_name:
        return None
    if not _IDENT_RE.match(table_name):
        log.warning("rejecting non-whitelist table identifier: %r", table_name)
        return None
    return table_name


async def compute_health(pool: asyncpg.Pool, slug: str) -> HealthCheck:
    """Compute :class:`HealthCheck` for the dataset *slug*.

    Returns a HealthCheck even if the dataset isn't registered yet — in
    that case status is ``'unknown'`` and the issue list explains why.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT slug, table_name, last_refreshed_at, last_refresh_ok,
                   last_refresh_error, last_row_count,
                   freshness_threshold_hours
            FROM princeps_datasets
            WHERE slug = $1
            """,
            slug,
        )

        if row is None:
            return HealthCheck(
                status="unknown",
                age_hours=None,
                row_count=None,
                expected_freshness_hours=168,
                issues=[f"dataset '{slug}' not registered"],
            )

        threshold = int(row["freshness_threshold_hours"] or 168)
        last_ok = row["last_refresh_ok"]
        last_error = row["last_refresh_error"]
        last_at = row["last_refreshed_at"]

        # Live row count — survives table truncations / migrations.
        row_count: Optional[int] = row["last_row_count"]
        safe = _safe_table(row["table_name"])
        if safe:
            try:
                row_count = await conn.fetchval(f"SELECT count(*) FROM {safe}")
            except Exception as exc:
                # Table doesn't exist yet (migration not applied) or read
                # blocked — keep the registry's last_row_count and flag.
                row_count = row["last_row_count"]
                log.debug("count(*) failed for %s.%s: %s", slug, safe, exc)

    # Compute age + status outside the connection block — pure logic.
    issues: list[str] = []
    age_hours: Optional[float] = None
    if last_at is not None:
        # asyncpg always returns aware datetimes for timestamptz columns,
        # but be defensive in case tests pass naive ones in.
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - last_at).total_seconds() / 3600.0

    if last_ok is False:
        status = "red"
        issues.append(f"last refresh failed: {last_error or 'unknown error'}")
    elif age_hours is None:
        # Never refreshed.
        if (row_count or 0) == 0:
            status = "unknown"
            issues.append("never refreshed; table empty")
        else:
            status = "yellow"
            issues.append("never refreshed; table has rows from another source")
    elif age_hours > 2 * threshold:
        status = "red"
        issues.append(
            f"stale: {age_hours:.1f}h > {2 * threshold}h "
            f"(2× {threshold}h threshold)",
        )
    elif age_hours > threshold:
        status = "yellow"
        issues.append(f"stale: {age_hours:.1f}h > {threshold}h threshold")
    elif (row_count or 0) == 0:
        status = "yellow"
        issues.append("table empty")
    else:
        status = "green"

    return HealthCheck(
        status=status,
        age_hours=age_hours,
        row_count=row_count,
        expected_freshness_hours=threshold,
        issues=issues,
    )


async def update_health(pool: asyncpg.Pool, slug: str) -> HealthCheck:
    """Compute *and persist* health for *slug*. Returns the new HealthCheck."""
    hc = await compute_health(pool, slug)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE princeps_datasets
            SET health_status = $2, health_checked_at = NOW()
            WHERE slug = $1
            """,
            slug, hc.status,
        )
    return hc


__all__ = ["compute_health", "update_health"]
