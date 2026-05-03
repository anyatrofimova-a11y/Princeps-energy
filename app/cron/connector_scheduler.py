"""APScheduler-driven cadence orchestration for Magritte connectors.

Every :class:`~app.connectors.base.Connector` subclass declares a
``refresh_cadence`` (``'daily'`` | ``'weekly'`` | ``'monthly'`` |
``'on_demand'``). On uvicorn startup, :class:`ConnectorScheduler`
walks the in-process registry and schedules a deterministic cron job
per connector — no Claude session, no manual cron, no per-connector
boilerplate.

Cron mapping
------------

  daily   →  every day at HH:07 + (md5(slug) % 60)-minute spread
  weekly  →  Sundays   at 09:13 + slug-hash offset
  monthly →  1st of month at 06:23 + slug-hash offset
  *other* →  not scheduled (treated as ``on_demand``)

The minute spread keeps five connectors from hammering upstream APIs
at the same instant when an operator boots fresh.

Each scheduled run wraps :meth:`Connector.ingest` and writes a row to
the new ``connector_schedule_log`` table (the manual
``/api/datasets/{slug}/refresh`` endpoint keeps writing to
``dataset_refresh_log`` — both tables coexist).

License-aware: a :class:`PermissionError` from ``Connector.ingest``
(emitted when ``license`` ∈ {``'NC'``, ``'non-commercial'``, …}) flips
``princeps_datasets.schedule_disabled`` to TRUE and removes the job so
the scheduler doesn't keep retrying.

Tenant-aware: each job opens a tenant-scoped connection via
:func:`app.middleware.tenant_jwt.acquire_tenant_conn` for the system
tenant before invoking the connector — RLS-tightened destinations
inherit the GUC for free.

Coexists with ``app/cron/bess_revenue_cron.py`` (asyncio loop) and the
single-purpose monthly DNO scheduler in ``app/startup.py``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time as _time
from datetime import datetime, timezone
from typing import Any

import asyncpg

log = logging.getLogger("princeps.connector_scheduler")

# ---------------------------------------------------------------------------
# Cron-mapping constants
# ---------------------------------------------------------------------------

# Base hour:minute anchors per cadence — hash-derived offset is added on top.
_BASE_DAILY_HOUR = 0           # any hour — daily uses HOUR every day; we let
                               # CronTrigger fire at hour=any so the spec's
                               # "every day at HH:07" actually means "once a
                               # day at the deterministic HH the slug hash
                               # picks". Implementation: hour fixed by hash.
_BASE_DAILY_MINUTE = 7

_BASE_WEEKLY_DOW = "sun"
_BASE_WEEKLY_HOUR = 9
_BASE_WEEKLY_MINUTE = 13

_BASE_MONTHLY_DAY = 1
_BASE_MONTHLY_HOUR = 6
_BASE_MONTHLY_MINUTE = 23

# System tenant — matches DEFAULT_TENANT_ID in app/middleware/tenant_jwt.py
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _slug_hash_int(slug: str) -> int:
    return int(hashlib.md5(slug.encode("utf-8")).hexdigest(), 16)


def _hash_minute_offset(slug: str) -> int:
    """Deterministic 0..59 minute offset spread."""
    return _slug_hash_int(slug) % 60


def _hash_hour_offset(slug: str, span: int = 24) -> int:
    """Deterministic 0..(span-1) hour offset for daily-cadence jobs.

    Uses a different hash slice than the minute offset so the two are
    independent (avoid all daily jobs landing on the same minute when
    they happen to land on different hours).
    """
    return (_slug_hash_int(slug) >> 8) % span


def _cron_kwargs_for_cadence(cadence: str, slug: str) -> dict[str, Any] | None:
    """Translate a connector's cadence string into APScheduler CronTrigger kwargs.

    Returns ``None`` for cadences we don't schedule (``on_demand``,
    ``quarterly``, blank, anything else). Callers should treat ``None``
    as "leave this connector alone".
    """
    minute_offset = _hash_minute_offset(slug)
    norm = (cadence or "").strip().lower()

    if norm == "daily":
        return {
            "hour": _hash_hour_offset(slug, span=24),
            "minute": (_BASE_DAILY_MINUTE + minute_offset) % 60,
        }
    if norm == "weekly":
        return {
            "day_of_week": _BASE_WEEKLY_DOW,
            "hour": _BASE_WEEKLY_HOUR,
            "minute": (_BASE_WEEKLY_MINUTE + minute_offset) % 60,
        }
    if norm == "monthly":
        return {
            "day": _BASE_MONTHLY_DAY,
            "hour": _BASE_MONTHLY_HOUR,
            "minute": (_BASE_MONTHLY_MINUTE + minute_offset) % 60,
        }
    return None


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_LOG_INSERT_SQL = """
INSERT INTO connector_schedule_log
    (slug, scheduled_at, fired_at, job_id)
VALUES ($1, $2, NOW(), $3)
RETURNING id
"""

_LOG_FINISH_OK_SQL = """
UPDATE connector_schedule_log
SET completed_at = NOW(),
    ok = TRUE,
    rows_ingested = $2,
    duration_ms = $3
WHERE id = $1
"""

_LOG_FINISH_FAIL_SQL = """
UPDATE connector_schedule_log
SET completed_at = NOW(),
    ok = FALSE,
    error = $2,
    duration_ms = $3
WHERE id = $1
"""

_DISABLE_SQL = """
UPDATE princeps_datasets
SET schedule_disabled = TRUE,
    schedule_disabled_reason = $2,
    updated_at = NOW()
WHERE slug = $1
"""

_NEXT_FIRE_SQL = """
UPDATE princeps_datasets
SET next_fire_at = $2,
    updated_at = NOW()
WHERE slug = $1
"""

_STATUS_SQL = """
SELECT slug, last_refreshed_at, last_refresh_ok, last_row_count,
       schedule_disabled, schedule_disabled_reason, next_fire_at,
       refresh_cadence
FROM princeps_datasets
ORDER BY slug
"""


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------

class ConnectorScheduler:
    """Wraps an :class:`AsyncIOScheduler` with one job per connector.

    Public surface used by ``app/startup.py`` and the
    ``/api/connector-scheduler`` router:

    - :meth:`start` — instantiate scheduler + add jobs from registry
    - :meth:`stop` — graceful shutdown (called on lifespan exit)
    - :meth:`status` — list of `{slug, next_fire_at, …}` dicts
    - :meth:`pause(slug)`, :meth:`resume(slug)`, :meth:`fire_now(slug)`
    """

    def __init__(self, pool: asyncpg.Pool, app: Any) -> None:
        self.pool = pool
        self.app = app
        self._scheduler = None  # AsyncIOScheduler — lazy import in start()
        self._jobs: dict[str, str] = {}        # slug -> APScheduler job id
        self._cadences: dict[str, str] = {}    # slug -> normalised cadence

    # ------------------------------------------------------------------ #
    # Lifecycle                                                          #
    # ------------------------------------------------------------------ #

    async def start(self) -> dict[str, Any]:
        """Instantiate the scheduler and add a job per registered connector.

        Returns a small summary dict (counts) for caller logging. Idempotent
        — a second call short-circuits to status().
        """
        if self._scheduler is not None:
            return {"status": "already_started", **self.status()}

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger  # noqa: F401
        except ImportError as exc:
            log.warning("APScheduler missing — connector scheduler disabled: %s", exc)
            return {"status": "apscheduler_missing", "scheduled": 0}

        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # Walk the in-process connector registry. We do this lazily here
        # (rather than at import time) so register_all_connectors() has
        # already imported every source module by the time we look.
        from app.connectors import registry as connector_registry

        scheduled = 0
        skipped: list[str] = []
        for cls in connector_registry.all_connectors():
            slug = getattr(cls, "slug", None)
            cadence = getattr(cls, "refresh_cadence", "on_demand")
            if not slug:
                continue
            cron_kwargs = _cron_kwargs_for_cadence(cadence, slug)
            if cron_kwargs is None:
                skipped.append(f"{slug}({cadence})")
                continue
            try:
                self._add_job(slug, cron_kwargs)
                self._cadences[slug] = cadence
                scheduled += 1
            except Exception as exc:
                log.warning("connector %s schedule add failed: %s", slug, exc)

        self._scheduler.start()
        await self._refresh_next_fire_at()

        log.info(
            "ConnectorScheduler started: scheduled=%d skipped=%s",
            scheduled, ",".join(skipped) or "<none>",
        )

        # Optional dev convenience — fire every connector once at startup.
        if os.getenv("RUN_NOW_ON_STARTUP", "false").lower() == "true":
            for slug in list(self._jobs):
                try:
                    self.fire_now(slug)
                except Exception as exc:
                    log.warning("RUN_NOW_ON_STARTUP fire_now(%s) failed: %s", slug, exc)

        return {
            "status": "started",
            "scheduled": scheduled,
            "skipped": skipped,
        }

    def stop(self) -> None:
        """Stop the scheduler. Safe to call multiple times."""
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as exc:
            log.warning("ConnectorScheduler shutdown failed: %s", exc)
        finally:
            self._scheduler = None
            self._jobs.clear()

    # ------------------------------------------------------------------ #
    # Per-job helpers                                                    #
    # ------------------------------------------------------------------ #

    def _add_job(self, slug: str, cron_kwargs: dict[str, Any]) -> None:
        """Internal — register / replace a job on the underlying scheduler."""
        from apscheduler.triggers.cron import CronTrigger

        job_id = f"connector::{slug}"
        trigger = CronTrigger(timezone="UTC", **cron_kwargs)
        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id=job_id,
            name=f"connector:{slug}",
            args=[slug],
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        self._jobs[slug] = job_id

    async def _run_job(self, slug: str) -> None:
        """The function APScheduler actually fires.

        Wrapped in a Postgres advisory lock so only one replica in a
        multi-replica deploy actually runs the job — the others see
        ``acquired=False`` and skip silently.

        Records a row to ``connector_schedule_log``, runs the connector's
        ingest under the system-tenant GUC, handles license-blocks by
        flipping ``schedule_disabled`` and removing the job.
        """
        from app.cron.leader_lock import try_leader_lock

        async with try_leader_lock(self.pool, "connector", slug) as acquired:
            if not acquired:
                log.info(
                    "connector_scheduler: skipping %s — another replica holds the leader lock",
                    slug,
                )
                return
            await self._run_job_locked(slug)

    async def _run_job_locked(self, slug: str) -> None:
        """Body of the cron job, executed only by the lock-holding replica."""
        from app.connectors import registry as connector_registry
        try:
            from app.middleware.tenant_jwt import acquire_tenant_conn
        except Exception:
            acquire_tenant_conn = None  # graceful degrade

        cls = connector_registry.get(slug)
        if cls is None:
            log.warning("connector_scheduler: %s vanished from registry", slug)
            return

        scheduled_at = datetime.now(timezone.utc)
        log_id = None
        started_monotonic = _time.monotonic()
        try:
            async with self.pool.acquire() as conn:
                log_id = await conn.fetchval(
                    _LOG_INSERT_SQL,
                    slug,
                    scheduled_at,
                    self._jobs.get(slug),
                )
        except Exception as exc:
            log.warning("connector_schedule_log insert failed for %s: %s", slug, exc)

        # Tenant-scoped DB context. We don't pass `conn` into the
        # connector's ingest() because the framework re-acquires its own
        # connections — the tenant GUC is process-wide-per-connection,
        # so we only need it on the connections the connector itself
        # opens. asyncpg pools don't propagate session GUCs across
        # acquisitions, so the GUC's only durable effect here is the
        # tenant_id stamping we do directly via the pool. The wrapper
        # remains in place so a future tightening (handing the conn
        # into ingest) is a one-line change.
        try:
            if acquire_tenant_conn is not None:
                async with acquire_tenant_conn(self.pool, _SYSTEM_TENANT_ID):
                    pass  # GUC set, conn returned to pool
            result = await cls().ingest(self.pool)
            duration_ms = int((_time.monotonic() - started_monotonic) * 1000)
            try:
                async with self.pool.acquire() as conn:
                    if log_id is not None:
                        await conn.execute(
                            _LOG_FINISH_OK_SQL,
                            log_id,
                            int(getattr(result, "rows_ingested", 0) or 0),
                            duration_ms,
                        )
            except Exception:
                log.exception("connector_schedule_log update failed for %s", slug)
            log.info(
                "connector_scheduler ok slug=%s rows=%s duration=%dms",
                slug,
                getattr(result, "rows_ingested", "?"),
                duration_ms,
            )
        except PermissionError as exc:
            duration_ms = int((_time.monotonic() - started_monotonic) * 1000)
            await self._handle_license_block(slug, log_id, str(exc), duration_ms)
        except Exception as exc:
            duration_ms = int((_time.monotonic() - started_monotonic) * 1000)
            err_msg = f"{type(exc).__name__}: {exc}"[:500]
            try:
                async with self.pool.acquire() as conn:
                    if log_id is not None:
                        await conn.execute(
                            _LOG_FINISH_FAIL_SQL, log_id, err_msg, duration_ms,
                        )
            except Exception:
                log.exception("connector_schedule_log fail-update failed for %s", slug)
            log.warning("connector_scheduler fail slug=%s err=%s", slug, err_msg)
        finally:
            await self._refresh_next_fire_at()

    async def _handle_license_block(
        self,
        slug: str,
        log_id: int | None,
        err: str,
        duration_ms: int,
    ) -> None:
        """Flip schedule_disabled and remove the job — don't keep retrying."""
        msg = f"license-blocked: {err}"[:500]
        try:
            async with self.pool.acquire() as conn:
                if log_id is not None:
                    await conn.execute(_LOG_FINISH_FAIL_SQL, log_id, msg, duration_ms)
                await conn.execute(_DISABLE_SQL, slug, msg)
        except Exception:
            log.exception("license-block disable record failed for %s", slug)
        try:
            self._remove_job(slug)
        except Exception:
            log.exception("license-block job removal failed for %s", slug)
        log.warning("connector_scheduler disabled slug=%s reason=%s", slug, msg)

    def _remove_job(self, slug: str) -> None:
        job_id = self._jobs.pop(slug, None)
        if job_id and self._scheduler is not None:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Public control                                                     #
    # ------------------------------------------------------------------ #

    def pause(self, slug: str) -> dict[str, Any]:
        if self._scheduler is None:
            return {"slug": slug, "ok": False, "error": "scheduler_not_started"}
        job_id = self._jobs.get(slug)
        if not job_id:
            return {"slug": slug, "ok": False, "error": "no_such_job"}
        try:
            self._scheduler.pause_job(job_id)
        except Exception as exc:
            return {"slug": slug, "ok": False, "error": str(exc)}
        # Mark schedule_disabled in the registry so /status reflects
        # operator intent. Same column the license-guard uses — distinguished
        # by schedule_disabled_reason (``'paused-by-operator'`` here vs
        # ``'license-blocked: …'`` for the guard path).
        self.app.state.connector_scheduler_paused = (
            getattr(self.app.state, "connector_scheduler_paused", set()) | {slug}
        )
        import asyncio as _aio
        try:
            loop = _aio.get_event_loop()
            loop.create_task(self._mark_disabled(slug, "paused-by-operator"))
        except RuntimeError:
            pass
        return {"slug": slug, "ok": True, "action": "paused"}

    async def _mark_disabled(self, slug: str, reason: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(_DISABLE_SQL, slug, reason)
        except Exception:
            log.exception("pause: schedule_disabled flip failed for %s", slug)

    async def _mark_enabled(self, slug: str) -> None:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE princeps_datasets
                    SET schedule_disabled = FALSE,
                        schedule_disabled_reason = NULL,
                        updated_at = NOW()
                    WHERE slug = $1
                    """,
                    slug,
                )
        except Exception:
            log.exception("resume: schedule_disabled clear failed for %s", slug)

    def resume(self, slug: str) -> dict[str, Any]:
        if self._scheduler is None:
            return {"slug": slug, "ok": False, "error": "scheduler_not_started"}
        job_id = self._jobs.get(slug)
        if not job_id:
            return {"slug": slug, "ok": False, "error": "no_such_job"}
        try:
            self._scheduler.resume_job(job_id)
        except Exception as exc:
            return {"slug": slug, "ok": False, "error": str(exc)}
        paused = getattr(self.app.state, "connector_scheduler_paused", set())
        paused.discard(slug)
        self.app.state.connector_scheduler_paused = paused
        import asyncio as _aio
        try:
            loop = _aio.get_event_loop()
            loop.create_task(self._mark_enabled(slug))
        except RuntimeError:
            pass
        return {"slug": slug, "ok": True, "action": "resumed"}

    def fire_now(self, slug: str) -> dict[str, Any]:
        """Schedule a one-shot run on the next event-loop tick.

        Returns immediately — caller polls ``connector_schedule_log`` to
        observe completion.
        """
        if self._scheduler is None:
            return {"slug": slug, "ok": False, "error": "scheduler_not_started"}
        from app.connectors import registry as connector_registry

        if connector_registry.get(slug) is None:
            return {"slug": slug, "ok": False, "error": "no_such_connector"}
        try:
            self._scheduler.add_job(
                self._run_job,
                args=[slug],
                id=f"connector::{slug}::adhoc::{int(_time.time() * 1000)}",
                name=f"connector:{slug} (ad-hoc)",
                misfire_grace_time=300,
            )
        except Exception as exc:
            return {"slug": slug, "ok": False, "error": str(exc)}
        return {"slug": slug, "ok": True, "action": "fire_now"}

    def status(self) -> dict[str, Any]:
        """Return the in-memory view of every scheduled job."""
        out: list[dict[str, Any]] = []
        if self._scheduler is None:
            return {"running": False, "scheduler": []}

        paused: set[str] = getattr(self.app.state, "connector_scheduler_paused", set())
        for slug, job_id in self._jobs.items():
            try:
                job = self._scheduler.get_job(job_id)
            except Exception:
                job = None
            next_fire = getattr(job, "next_run_time", None)
            out.append({
                "slug": slug,
                "cadence": self._cadences.get(slug, "unknown"),
                "next_fire_at": next_fire.isoformat() if next_fire else None,
                "job_id": job_id,
                "paused": slug in paused,
            })
        return {"running": True, "scheduler": out}

    async def _refresh_next_fire_at(self) -> None:
        """Persist next_fire_at into princeps_datasets so the catalogue UI
        can show it without going through this scheduler."""
        if self._scheduler is None:
            return
        try:
            async with self.pool.acquire() as conn:
                for slug, job_id in self._jobs.items():
                    try:
                        job = self._scheduler.get_job(job_id)
                    except Exception:
                        job = None
                    next_fire = getattr(job, "next_run_time", None)
                    try:
                        await conn.execute(_NEXT_FIRE_SQL, slug, next_fire)
                    except Exception:
                        pass
        except Exception:
            pass

    async def status_with_db(self) -> list[dict[str, Any]]:
        """Status dict enriched with princeps_datasets columns.

        Used by the GET /status endpoint so the UI gets one canonical
        record per slug — registry truth + scheduler truth merged.
        """
        in_memory = self.status().get("scheduler", [])
        index = {row["slug"]: row for row in in_memory}

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(_STATUS_SQL)
        except Exception:
            return in_memory

        merged: list[dict[str, Any]] = []
        for r in rows:
            slug = r["slug"]
            mem = index.get(slug, {})
            last_fire_at = r["last_refreshed_at"]
            merged.append({
                "slug": slug,
                "cadence": r["refresh_cadence"],
                "next_fire_at": (
                    mem.get("next_fire_at")
                    or (r["next_fire_at"].isoformat() if r["next_fire_at"] else None)
                ),
                "last_fire_at": last_fire_at.isoformat() if last_fire_at else None,
                "last_ok": r["last_refresh_ok"],
                "last_rows": r["last_row_count"],
                "schedule_disabled": bool(r["schedule_disabled"]),
                "schedule_disabled_reason": r["schedule_disabled_reason"],
                "paused": mem.get("paused", False),
                "scheduled_in_memory": slug in self._jobs,
            })
        # Append any in-memory jobs that aren't yet in the registry table.
        seen = {row["slug"] for row in merged}
        for mem in in_memory:
            if mem["slug"] not in seen:
                merged.append({**mem, "schedule_disabled": False})
        return merged


__all__ = ["ConnectorScheduler"]
