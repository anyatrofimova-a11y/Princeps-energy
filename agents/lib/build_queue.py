"""Helper for any agent to enqueue work for the builder agent.

Usage::

    from agents.lib.build_queue import enqueue_build_task

    await enqueue_build_task(
        pool,
        title="Add SSEN connector to dataset_registry",
        brief="The connector_health agent observed SSEN feed missing. Add ingester wrapper at utils/ssen_connector.py and register it in app/connectors/registry.py.",
        context_paths=["app/connectors/registry.py", "utils/grid_data_ingester.py"],
        requested_by="agent:connector_health",
        priority=4,
    )

Dedupe: tasks with the same title in the last 24h are silently skipped
so an agent that ticks hourly doesn't flood the queue.
"""
from __future__ import annotations

import logging
from typing import Iterable

import asyncpg

log = logging.getLogger(__name__)


async def enqueue_build_task(
    pool: asyncpg.Pool,
    *,
    title: str,
    brief: str,
    context_paths: Iterable[str] = (),
    requested_by: str = "agent:unknown",
    priority: int = 6,
    branch_policy: str = "pr",
    auto_merge: bool = False,
) -> str | None:
    """Insert a build task; returns the task_id, or None if deduped."""
    async with pool.acquire() as conn:
        # Dedupe against same title in last 24h
        existing = await conn.fetchval(
            """SELECT task_id FROM builder.queue
                WHERE title = $1
                  AND created_at > now() - interval '24 hours'
                ORDER BY created_at DESC LIMIT 1""",
            title,
        )
        if existing:
            log.info("dedup: build task '%s' already queued (%s)", title, existing)
            return None

        task_id = await conn.fetchval(
            """INSERT INTO builder.queue
                 (title, brief, context_paths, branch_policy,
                  auto_merge, priority, requested_by)
               VALUES ($1, $2, $3::text[], $4, $5, $6, $7)
               RETURNING task_id::text""",
            title, brief, list(context_paths),
            branch_policy, auto_merge, priority, requested_by,
        )
    log.info("enqueued build task %s: %s", task_id, title)
    return task_id
