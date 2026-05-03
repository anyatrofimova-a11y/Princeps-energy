"""Postgres advisory-lock leader election for cron jobs.

Princeps schedulers (connector + pipeline) run in-process via APScheduler.
On a multi-replica deploy (Railway runs N web services), every replica
fires the same cron — duplicate ingestions, double-billed external API
calls, race conditions on connector inserts saved by ON CONFLICT only
by luck.

This module provides a session-level Postgres advisory lock so only ONE
replica actually runs each job. Other replicas skip and log.

Usage
-----

    from app.cron.leader_lock import try_leader_lock

    async with try_leader_lock(pool, "connector", slug) as acquired:
        if not acquired:
            log.info("skipping %s — another replica holds the lock", slug)
            return
        # ... do the work ...

Why session-level, not transactional? A connector ingest spans many
asyncpg pool acquisitions; a transactional advisory lock would release
between them. Session-level holds across the job lifetime as long as
we keep ONE dedicated connection alive — which is exactly what this
context manager does.

Why ``blake2b`` for the lock key? Postgres advisory locks are 64-bit
signed integers. We need a deterministic, collision-resistant mapping
from ``(namespace, slug)`` strings → int64. Blake2b digest_size=8 gives
exactly 8 bytes; sign-bit interpretation puts us inside the Postgres
``bigint`` range. Different namespaces (``connector`` vs ``pipeline``)
with identical slug names hash to different ints, so they don't collide.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager

import asyncpg

log = logging.getLogger("princeps.cron.leader_lock")


def _lock_key(namespace: str, slug: str) -> int:
    """Hash ``(namespace, slug)`` to a Postgres-bigint-safe int64."""
    h = hashlib.blake2b(f"{namespace}:{slug}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, byteorder="big", signed=True)


@asynccontextmanager
async def try_leader_lock(pool: asyncpg.Pool, namespace: str, slug: str):
    """Try to acquire a session-level advisory lock. Yields True/False.

    True  → this replica holds the lock; run the job.
    False → another replica holds it; skip silently.

    The lock is auto-released on exit (or when the holding connection
    closes — defense in depth against a crash mid-job).
    """
    key = _lock_key(namespace, slug)
    conn = await pool.acquire()
    acquired = False
    try:
        try:
            acquired = bool(await conn.fetchval("SELECT pg_try_advisory_lock($1)", key))
        except Exception as exc:
            # If the advisory call itself failed, fail OPEN (run the job)
            # rather than silently dropping every cron fire across the cluster.
            # A duplicate run is recoverable; a missed run can stop the
            # platform altogether.
            log.warning(
                "leader_lock: pg_try_advisory_lock failed for %s:%s — running anyway: %s",
                namespace, slug, exc,
            )
            acquired = True
        yield acquired
    finally:
        if acquired:
            try:
                await conn.fetchval("SELECT pg_advisory_unlock($1)", key)
            except Exception as exc:
                log.warning(
                    "leader_lock: pg_advisory_unlock failed for %s:%s: %s",
                    namespace, slug, exc,
                )
        try:
            await pool.release(conn)
        except Exception:
            log.exception("leader_lock: pool.release failed for %s:%s", namespace, slug)


__all__ = ["try_leader_lock"]
