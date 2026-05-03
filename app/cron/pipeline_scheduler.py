"""Pipeline scheduler — APScheduler-driven cadence-based pipeline runs.

Mirrors `app/cron/connector_scheduler.py` but for `data_pipelines` rows.
At startup walks every enabled pipeline and registers a cron job per its
``cadence`` field (`hourly`, `daily`, `weekly`, `monthly`). Slug-hashed
minute/hour offsets spread load across the hour/day so simultaneous
pipelines don't all hit the DB at the same instant.

`on_demand` pipelines are not auto-scheduled.

Coexists with `connector_scheduler.py` and `bess_revenue_cron.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

import asyncpg

log = logging.getLogger("princeps.cron.pipeline_scheduler")

# Anchors per cadence — hash-derived offset is added on top.
_BASE_HOURLY_MINUTE = 7        # off-the-hour
_BASE_DAILY_HOUR = 4           # 04:xx UTC for daily
_BASE_DAILY_MINUTE = 17
_BASE_WEEKLY_DOW = "sun"
_BASE_WEEKLY_HOUR = 5
_BASE_WEEKLY_MINUTE = 23
_BASE_MONTHLY_DAY = 1
_BASE_MONTHLY_HOUR = 6
_BASE_MONTHLY_MINUTE = 41


def _slug_hash_int(slug: str) -> int:
    return int(hashlib.md5((slug or "").encode()).hexdigest(), 16)


def _minute_offset(slug: str) -> int:
    return _slug_hash_int(slug) % 60


def _hour_offset(slug: str, span: int = 24) -> int:
    return (_slug_hash_int(slug) // 60) % span


def _cron_kwargs_for_cadence(cadence: str, slug: str) -> dict[str, Any] | None:
    norm = (cadence or "").strip().lower()
    m_off = _minute_offset(slug)
    if norm == "hourly":
        return {"minute": (_BASE_HOURLY_MINUTE + m_off) % 60}
    if norm == "daily":
        return {
            "hour": _hour_offset(slug, span=24),
            "minute": (_BASE_DAILY_MINUTE + m_off) % 60,
        }
    if norm == "weekly":
        return {
            "day_of_week": _BASE_WEEKLY_DOW,
            "hour": _BASE_WEEKLY_HOUR,
            "minute": (_BASE_WEEKLY_MINUTE + m_off) % 60,
        }
    if norm == "monthly":
        return {
            "day": _BASE_MONTHLY_DAY,
            "hour": _BASE_MONTHLY_HOUR,
            "minute": (_BASE_MONTHLY_MINUTE + m_off) % 60,
        }
    return None


class PipelineScheduler:
    """Walks data_pipelines + schedules cron-fires per cadence."""

    def __init__(self, pool: asyncpg.Pool, app):
        self._pool = pool
        self._app = app
        self._scheduler = None
        self._jobs: dict[str, str] = {}    # slug -> job_id
        self._cadences: dict[str, str] = {}

    async def start(self) -> dict:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as exc:
            log.warning("apscheduler unavailable — pipeline scheduler disabled: %s", exc)
            return {"status": "disabled", "reason": str(exc)}

        self._scheduler = AsyncIOScheduler()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT slug, cadence, enabled FROM data_pipelines WHERE enabled = TRUE",
            )
        scheduled = []
        skipped = []
        for r in rows:
            slug = r["slug"]
            cadence = r["cadence"] or "on_demand"
            self._cadences[slug] = cadence
            cron_kwargs = _cron_kwargs_for_cadence(cadence, slug)
            if cron_kwargs is None:
                skipped.append(f"{slug}({cadence})")
                continue
            job = self._scheduler.add_job(
                self._fire_async, "cron", id=f"pipeline:{slug}",
                args=[slug], **cron_kwargs,
                misfire_grace_time=3600, coalesce=True, max_instances=1,
            )
            self._jobs[slug] = job.id
            scheduled.append(slug)

        self._scheduler.start()
        log.info("pipeline scheduler started: %d scheduled, %d skipped", len(scheduled), len(skipped))
        return {"status": "started", "scheduled": len(scheduled), "skipped": skipped}

    async def _fire_async(self, slug: str) -> None:
        """Cron-fired wrapper that posts to /api/pipelines/{slug}/run.

        Wrapped in a Postgres advisory lock so only one replica in a
        multi-replica deploy actually fires the run — others skip silently.
        """
        from app.cron.leader_lock import try_leader_lock
        from app.routers.pipelines import run_pipeline as _run

        async with try_leader_lock(self._pool, "pipeline", slug) as acquired:
            if not acquired:
                log.info(
                    "pipeline_scheduler: skipping %s — another replica holds the leader lock",
                    slug,
                )
                return
            log.info("pipeline cron firing: %s", slug)
            try:
                # Call the router function directly with our pool — same flow as HTTP.
                res = await _run(slug=slug, body={"triggered_by": "cron:pipeline_scheduler"}, pool=self._pool)
                log.info("pipeline %s cron-run result: %s", slug, res)
            except Exception as exc:
                log.exception("pipeline %s cron-run failed: %s", slug, exc)

    async def stop(self) -> None:
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception as exc:
            log.warning("pipeline scheduler shutdown failed: %s", exc)

    def status(self) -> list[dict]:
        out = []
        if not self._scheduler:
            return out
        for slug, jid in self._jobs.items():
            try:
                j = self._scheduler.get_job(jid)
                next_fire = j.next_run_time.isoformat() if j and j.next_run_time else None
            except Exception:
                next_fire = None
            out.append({
                "slug": slug,
                "cadence": self._cadences.get(slug),
                "next_fire_at": next_fire,
                "enabled": True,
            })
        return out

    def fire_now(self, slug: str) -> bool:
        """Trigger an out-of-cadence run (best-effort schedule on the loop)."""
        if not self._scheduler:
            return False
        try:
            asyncio.create_task(self._fire_async(slug))
            return True
        except Exception:
            return False

    def pause(self, slug: str) -> bool:
        if not self._scheduler:
            return False
        jid = self._jobs.get(slug)
        if not jid:
            return False
        try:
            self._scheduler.pause_job(jid)
            return True
        except Exception:
            return False

    def resume(self, slug: str) -> bool:
        if not self._scheduler:
            return False
        jid = self._jobs.get(slug)
        if not jid:
            return False
        try:
            self._scheduler.resume_job(jid)
            return True
        except Exception:
            return False
