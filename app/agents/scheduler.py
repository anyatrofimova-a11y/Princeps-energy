"""
APScheduler that enqueues ARQ jobs on recurring schedules.

Deployed as its own Railway service (princeps-scheduler). Start command:
    python -m app.agents.scheduler

Each schedule entry enqueues a job to an ARQ queue, which is then consumed
by the appropriate princeps-worker-* service.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from arq import create_pool
from arq.connections import RedisSettings

log = logging.getLogger("princeps.scheduler")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


# ── Schedule declarations ────────────────────────────────────────────────────
# Each entry maps a cron schedule to a payload sent through ARQ to the
# `dispatch` function. The worker picks up the payload and dispatches to its
# bound agent (AGENT_NAME env var on the target worker).
#
# The queue name is "arq:queue" by default (ARQ convention); all workers
# consume the same queue and filter by AGENT_NAME. To route to a specific
# agent, set `_queue_name` per job (via the @agent_job decorator in future).

_SCHEDULES = [
    # Prospector: daily sweep at 04:00 UTC
    {
        "name": "prospector.daily_sweep",
        "cron": CronTrigger(hour=4, minute=0),
        "payload": {"_agent": "prospector"},
    },
    # GridMonitor: every 2 hours
    {
        "name": "grid_monitor.hourly",
        "cron": CronTrigger(minute=0, hour="*/2"),
        "payload": {"_agent": "grid_monitor"},
    },
    # Procurement: daily at 05:30 UTC
    {
        "name": "procurement.daily",
        "cron": CronTrigger(hour=5, minute=30),
        "payload": {"_agent": "procurement", "since_days": 1},
    },
    # Ingestion: BMRS every hour
    {
        "name": "ingestion.bmrs_hourly",
        "cron": CronTrigger(minute=5),
        "payload": {"_agent": "ingestion", "source": "bmrs"},
    },
    # Ingestion: canonical grid tables (substations / ECR / snapshots)
    # every 6 hours — feeds GridMonitorAgent's change detection.
    {
        "name": "ingestion.grid_6h",
        "cron": CronTrigger(minute=15, hour="*/6"),
        "payload": {"_agent": "ingestion", "source": "grid"},
    },
    # Ingestion: NGED Embedded Capacity Register. NGED publish a fresh CSV
    # monthly, so we poll weekly (Sunday 01:30 UTC, before the weekly
    # all-sources heavy ingest) to catch updates within a few days. Also
    # triggers a grid_ecr refresh inside the handler.
    {
        "name": "ingestion.nged_ecr_weekly",
        "cron": CronTrigger(day_of_week="sun", hour=1, minute=30),
        "payload": {"_agent": "ingestion", "source": "nged_ecr"},
    },
    # Ingestion: heavy sources (NESO/DNO/OSM/GeeFlow) weekly Sunday 02:00 UTC
    {
        "name": "ingestion.weekly",
        "cron": CronTrigger(day_of_week="sun", hour=2, minute=0),
        "payload": {"_agent": "ingestion", "source": "all"},
    },
    # Report: weekly Monday 07:00 UK time (06:00 UTC during BST, close enough)
    {
        "name": "report.weekly",
        "cron": CronTrigger(day_of_week="mon", hour=6, minute=0),
        "payload": {"_agent": "report"},
    },
    # Competitor R&D scout: daily 03:00 UTC
    {
        "name": "rnd.scout_daily",
        "cron": CronTrigger(hour=3, minute=0),
        "payload": {"_agent": "rnd", "mode": "scout"},
    },
    # Competitor R&D synthesis: weekly Thursday 08:00 UTC
    {
        "name": "rnd.synthesis_weekly",
        "cron": CronTrigger(day_of_week="thu", hour=8, minute=0),
        "payload": {"_agent": "rnd", "mode": "rnd"},
    },
    # Planning monitor: daily at 06:00 UTC (after the nightly ingestion runs)
    {
        "name": "planning_monitor.daily",
        "cron": CronTrigger(hour=6, minute=0),
        "payload": {"_agent": "planning_monitor", "since_days": 7},
    },
    # Market intel scout: weekdays at 07:00 UTC
    {
        "name": "market_intel.scout_daily",
        "cron": CronTrigger(day_of_week="mon-fri", hour=7, minute=0),
        "payload": {"_agent": "market_intel", "mode": "scout"},
    },
    # Market intel digest: Monday at 09:00 UTC (so it's ready for UK morning)
    {
        "name": "market_intel.digest_weekly",
        "cron": CronTrigger(day_of_week="mon", hour=9, minute=0),
        "payload": {"_agent": "market_intel", "mode": "digest", "since_days": 7},
    },
    # NOTE: `builder` is NOT scheduled — it's triggered on demand via the
    # `/api/agents/builder/dispatch` endpoint (or by webhook on an issue
    # being labelled `agent:build`). Scheduling it blindly would spend
    # money without a mission.
]


# ── Job dispatch ─────────────────────────────────────────────────────────────

async def _enqueue(redis_pool, name: str, payload: dict) -> None:
    """Push a job onto the per-agent ARQ queue (`arq:{agent}`).

    The ``_agent`` key in the payload names the worker service; we route the
    job to that worker's queue. Other workers never see it.
    """
    agent = payload.pop("_agent", "prospector")
    queue = f"arq:{agent}"
    try:
        await redis_pool.enqueue_job("dispatch", payload, _queue_name=queue)
        log.info("scheduler.enqueue name=%s queue=%s payload=%s", name, queue, payload)
    except Exception:
        log.exception("scheduler.enqueue_failed name=%s", name)


# ── Main loop ────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("scheduler.starting schedules=%d", len(_SCHEDULES))

    redis_url = os.environ["REDIS_URL"]
    redis_pool = await create_pool(RedisSettings.from_dsn(redis_url))

    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    for entry in _SCHEDULES:
        scheduler.add_job(
            _enqueue,
            trigger=entry["cron"],
            args=[redis_pool, entry["name"], entry["payload"]],
            id=entry["name"],
            name=entry["name"],
            replace_existing=True,
        )
    scheduler.start()
    log.info("scheduler.started at=%s", datetime.now(timezone.utc).isoformat())

    # Run until SIGTERM
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_event_loop().add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("scheduler.shutting_down")
    scheduler.shutdown(wait=False)
    await redis_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
