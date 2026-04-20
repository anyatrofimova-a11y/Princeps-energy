"""
app/ingestion/scheduler.py — APScheduler entry point for the Intelligence
ingestion workers.

Runs in-process as an ``AsyncIOScheduler`` started from
``app/startup.py``. Gated on ``PRINCEPS_INGESTION_ENABLED=true`` so local
dev / CI doesn't kick off scrapes unless explicitly opted in.

Schedules registered
--------------------
- ofgem:           every 6h
- planit_lpa:      every 4h
- bmrs:            every 15 min
- neso_tec:        daily  00:30 UTC
- pins_nsip:       daily  00:30 UTC
- desnz:           daily  00:30 UTC
- companies_house: daily  01:00 UTC
- find_a_tender:   daily  02:00 UTC
- hse_comah:       weekly Fri 09:00 UTC
- embed_nightly:   daily  03:00 UTC (populate missing documents.embedding)
- dno_ltds:        monthly 1st 01:00 UTC  (blocked on DNO ingestion task #1)

Job stores are in-process (default MemoryJobStore). A SQLAlchemyJobStore
using the app's DSN is mounted when ``PRINCEPS_INGESTION_JOBSTORE=sql``
is set — left opt-in because most deployments run a single replica and
don't need persistent scheduling state.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import asyncpg

log = logging.getLogger("princeps.ingestion.scheduler")


_scheduler: Any = None   # singleton handle


# ── Worker registry — source slug → coroutine factory ───────────────────────

def _build_job(pool: asyncpg.Pool, worker_cls_path: str):
    """Return an async job callable that runs the worker's .run()."""
    mod_name, cls_name = worker_cls_path.rsplit(".", 1)

    async def _job():
        import importlib
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
        except Exception as e:
            log.exception("scheduler: failed to import %s: %s", worker_cls_path, e)
            return
        try:
            worker = cls(pool)
            result = await worker.run()
            log.info(
                "%s cron run done: status=%s inserted=%d updated=%d failed=%d",
                cls_name, result.status, result.rows_inserted,
                result.rows_updated, result.rows_failed,
            )
        except Exception as e:
            log.exception("%s cron run crashed: %s", cls_name, e)

    return _job


async def _embed_missing_job(pool: asyncpg.Pool):
    """Nightly pass — populate documents.embedding for rows that lack one."""
    from app.ingestion.embeddings import embed_missing_documents
    try:
        written = await embed_missing_documents(pool, limit=500)
        log.info("nightly embedding: wrote %d rows", written)
    except Exception as e:
        log.exception("nightly embedding failed: %s", e)


async def _dno_ltds_placeholder(pool: asyncpg.Pool):
    """Placeholder monthly DNO LTDS ingest job.

    Blocked on task #1 (DNO ingestion pipeline fix). When that lands the
    body of this job should delegate to whatever the canonical LTDS
    ingester becomes; for now we log and exit so the schedule row is
    real-ish.
    """
    log.info("dno_ltds monthly slot — pending task #1 completion; no-op")


# ── Public entry points ─────────────────────────────────────────────────────

def start_ingestion_scheduler(pool: asyncpg.Pool) -> Any:
    """
    Build, register and start the AsyncIOScheduler.

    Returns the scheduler handle so the caller (``app/startup.py``) can
    stash it on ``app.state`` for shutdown.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as e:
        log.warning("apscheduler not installed — ingestion scheduler disabled: %s", e)
        return None

    jobstores = _build_jobstores()
    scheduler = AsyncIOScheduler(timezone="UTC", jobstores=jobstores)

    # ── Interval jobs ───────────────────────────────────────────────────────
    scheduler.add_job(
        _build_job(pool, "app.ingestion.ofgem.OfgemWorker"),
        IntervalTrigger(hours=6),
        id="ingest_ofgem",
        name="Ofgem publications (6h)",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.planit_lpa.PlanitLpaWorker"),
        IntervalTrigger(hours=4),
        id="ingest_planit_lpa",
        name="PlanIt LPA planning apps (4h)",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.bmrs.BmrsWorker"),
        IntervalTrigger(minutes=15),
        id="ingest_bmrs",
        name="BMRS balancing events (15m)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── Daily cron jobs (most Intelligence sources run daily @ 00:30+) ──────
    scheduler.add_job(
        _build_job(pool, "app.ingestion.neso_tec.NesoTecWorker"),
        CronTrigger(hour=0, minute=30),
        id="ingest_neso_tec",
        name="NESO TEC register (daily 00:30 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.pins_nsip.PinsNsipWorker"),
        CronTrigger(hour=0, minute=30),
        id="ingest_pins_nsip",
        name="PINS NSIP register (daily 00:30 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.desnz.DesnzWorker"),
        CronTrigger(hour=0, minute=30),
        id="ingest_desnz",
        name="DESNZ GOV.UK ATOM (daily 00:30 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.companies_house.CompaniesHouseWorker"),
        CronTrigger(hour=1, minute=0),
        id="ingest_companies_house",
        name="Companies House (daily 01:00 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _build_job(pool, "app.ingestion.find_a_tender.FindATenderWorker"),
        CronTrigger(hour=2, minute=0),
        id="ingest_find_a_tender",
        name="Find-a-Tender OCDS (daily 02:00 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Weekly job ──────────────────────────────────────────────────────────
    scheduler.add_job(
        _build_job(pool, "app.ingestion.hse_comah.HseComahWorker"),
        CronTrigger(day_of_week="fri", hour=9, minute=0),
        id="ingest_hse_comah",
        name="HSE COMAH notices (weekly Fri 09:00 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Monthly DNO LTDS placeholder ────────────────────────────────────────
    scheduler.add_job(
        lambda: _dno_ltds_placeholder(pool),
        CronTrigger(day=1, hour=1, minute=0),
        id="ingest_dno_ltds",
        name="DNO LTDS monthly (blocked on task #1)",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── Nightly embeddings backfill ─────────────────────────────────────────
    scheduler.add_job(
        lambda: _embed_missing_job(pool),
        CronTrigger(hour=3, minute=0),
        id="ingest_embed_nightly",
        name="Embeddings backfill (daily 03:00 UTC)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    _scheduler = scheduler

    log.info(
        "Princeps ingestion scheduler started — %d jobs registered",
        len(scheduler.get_jobs()),
    )
    return scheduler


def stop_ingestion_scheduler() -> None:
    """Shutdown hook — safe to call multiple times."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None


def get_scheduler() -> Any:
    return _scheduler


# ── Internals ───────────────────────────────────────────────────────────────

def _build_jobstores() -> dict[str, Any]:
    """
    Build the APScheduler job-store dict.

    Opt into SQLAlchemyJobStore with ``PRINCEPS_INGESTION_JOBSTORE=sql``.
    Defaults to in-memory, which is fine for single-replica deploys.
    """
    mode = (os.getenv("PRINCEPS_INGESTION_JOBSTORE") or "memory").lower()
    if mode != "sql":
        return {}  # AsyncIOScheduler defaults to MemoryJobStore

    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    except ImportError:
        log.warning("SQLAlchemyJobStore not importable — falling back to memory")
        return {}

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        log.warning("DATABASE_URL not set — SQLAlchemyJobStore disabled")
        return {}

    # APScheduler expects a sync DSN (SQLAlchemy) — strip asyncpg driver
    # qualifier if present.
    sync_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    try:
        return {"default": SQLAlchemyJobStore(url=sync_dsn, tablename="apscheduler_jobs_intel")}
    except Exception as e:
        log.warning("SQLAlchemyJobStore init failed: %s — falling back to memory", e)
        return {}
