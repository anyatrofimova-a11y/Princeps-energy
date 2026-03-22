"""
startup.py — Background seed / ingestion tasks for Princeps.

Extracted from main.py lifespan.  Call ``await launch_background_tasks(pool)``
once at startup after ``setup_database(pool)`` has finished.
"""

import asyncio
import logging

import asyncpg

from utils.osm_power_infra import seed_power_infra as osm_power_seed
from utils.nged_cim import seed_cim_data as nged_seed
from utils.eso_tec import seed_tec_data as eso_tec_seed
from utils.repd import seed_repd_data as repd_seed
from utils.graph_topology import (
    init_driver as neo4j_init,
    seed_from_postgres as neo4j_seed,
    driver_available as neo4j_available,
)
from utils.repd_tracker import ingest_repd
from utils.eso_tec_register import ingest_tec_register
from utils.grid_upgrade_tracker import ingest_nged_upgrades
from utils.grid_data_ingester import ingest_all_dnos
from utils.grid_seed_data import seed_real_substations
from utils.dc_infra_ingester import ingest_dc_infrastructure
from utils.alert_engine import run_daily_alert_check
from app.readiness import mark_ready, mark_loading, mark_failed, update_progress

log = logging.getLogger("princeps")


async def _safe_bg(name: str, coro_func, *args, subsystem: str | None = None) -> None:
    """Run a coroutine and log rather than crash on failure.

    If *subsystem* is provided, updates the readiness tracker on
    completion or failure.
    """
    if subsystem:
        mark_loading(subsystem)
    try:
        await coro_func(*args)
        if subsystem:
            mark_ready(subsystem)
    except Exception as e:
        log.warning("Background task %s failed: %s", name, e)
        if subsystem:
            mark_failed(subsystem, str(e))


async def launch_background_tasks(pool: asyncpg.Pool) -> None:
    """Fire-and-forget background seed / ingestion tasks.

    Each task is launched via ``asyncio.create_task`` so they run
    concurrently without blocking the server startup.
    """

    # ── Mark core subsystems ready (DB pool is already created) ─────
    mark_ready("database")
    mark_ready("core_api")

    # ── OSM power infrastructure seeding ──────────────────────────────
    asyncio.create_task(osm_power_seed(pool))

    # ── NGED CIM data seeding ─────────────────────────────────────────
    asyncio.create_task(nged_seed(pool))

    # ── ESO TEC + REPD seeding ────────────────────────────────────────
    asyncio.create_task(eso_tec_seed(pool))
    asyncio.create_task(repd_seed(pool))

    # ── Neo4j graph topology (graceful degradation) ───────────────────
    mark_loading("neo4j")
    try:
        await neo4j_init()
        if neo4j_available():
            asyncio.create_task(_safe_bg("neo4j_seed", neo4j_seed, pool, subsystem="neo4j"))
        else:
            mark_failed("neo4j", "driver not available")
    except Exception as e:
        log.warning("Neo4j init skipped — graph features disabled: %s", e)
        mark_failed("neo4j", str(e))

    # ── Regulatory intelligence background ingestion ──────────────────
    asyncio.create_task(_safe_bg("repd_ingest", ingest_repd, pool, subsystem="demand_data"))
    asyncio.create_task(_safe_bg("tec_ingest", ingest_tec_register, pool))
    asyncio.create_task(_safe_bg("grid_upgrade_ingest", ingest_nged_upgrades, pool))

    # ── Grid GSP seed — reliable baseline BEFORE DNO API ingestion ────
    await _safe_bg("grid_gsp_seed", seed_real_substations, pool)

    # ── Grid Connection module — ingest all DNO data ──────────────────
    asyncio.create_task(_safe_bg("grid_connection_ingest", ingest_all_dnos, pool, subsystem="grid_data"))

    # ── DC infrastructure — fibre POPs, IXPs, water bodies, DCs ─────
    asyncio.create_task(_safe_bg("dc_infra_ingest", ingest_dc_infrastructure, pool, subsystem="dc_infrastructure"))

    # ── GeeFlow — mark ready (no startup ingestion, on-demand) ───────
    mark_ready("geeflow")

    # ── Nightly data refresh scheduler ──────────────────────────────────
    asyncio.create_task(_nightly_refresh_loop(pool))

    # ── Seed system workflow templates ──────────────────────────────
    asyncio.create_task(_safe_bg("workflow_templates_seed", _seed_workflow_templates, pool))

    log.info("Background tasks launched")


async def _seed_workflow_templates(pool: asyncpg.Pool) -> None:
    """Seed WORKFLOW_PRESETS from workflows.py into workflow_templates table."""
    import json
    from workflows import WORKFLOW_PRESETS

    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT count(*) FROM workflow_templates WHERE is_system = TRUE")
        if existing >= len(WORKFLOW_PRESETS):
            return  # already seeded

        for key, preset in WORKFLOW_PRESETS.items():
            steps = [{"intent": s} for s in preset["steps"]]
            # Check if template already exists by name
            exists = await conn.fetchval(
                "SELECT 1 FROM workflow_templates WHERE name = $1 AND is_system = TRUE",
                preset["label"],
            )
            if not exists:
                await conn.execute(
                    """INSERT INTO workflow_templates (name, description, steps, is_system)
                       VALUES ($1, $2, $3::jsonb, TRUE)""",
                    preset["label"], preset.get("description", ""),
                    json.dumps(steps),
                )
        log.info("Seeded %d system workflow templates", len(WORKFLOW_PRESETS))


async def _nightly_refresh_loop(pool: asyncpg.Pool) -> None:
    """
    Nightly data refresh — runs at 02:00 UTC every day.

    Refreshes:
      1. REPD projects (BEIS renewable energy planning database)
      2. ESO TEC register (transmission entry capacity queue)
      3. Grid DNO substations + ECR (all 6 UK DNOs)
      4. NGED CIM equipment profiles
      5. Grid upgrade tracker (NGED investment plans)
      6. Daily alert check (threshold breaches, queue changes)

    Why: Data goes stale after startup. Beta users need to see fresh
    DNO data when they log in Monday morning, not data from last restart.
    """
    from datetime import datetime, timezone

    REFRESH_INTERVAL_HOURS = 24
    TARGET_HOUR_UTC = 2  # Run at 02:00 UTC

    # Wait until first 02:00 UTC
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=TARGET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if next_run <= now:
        from datetime import timedelta
        next_run += timedelta(days=1)
    initial_wait = (next_run - now).total_seconds()
    log.info("Nightly refresh scheduled — first run in %.1f hours at %s", initial_wait / 3600, next_run.isoformat())
    await asyncio.sleep(initial_wait)

    while True:
        run_start = _time_now()
        log.info("Nightly data refresh starting...")

        # Run all refresh tasks concurrently
        results = await asyncio.gather(
            _safe_bg("nightly_repd", ingest_repd, pool),
            _safe_bg("nightly_tec", ingest_tec_register, pool),
            _safe_bg("nightly_dno", ingest_all_dnos, pool),
            _safe_bg("nightly_nged_upgrades", ingest_nged_upgrades, pool),
            _safe_bg("nightly_alerts", _run_alerts, pool),
            return_exceptions=True,
        )

        elapsed = _time_now() - run_start
        errors = sum(1 for r in results if isinstance(r, Exception))
        log.info(
            "Nightly refresh complete in %.1fs — %d/%d tasks succeeded",
            elapsed, len(results) - errors, len(results),
        )

        # Record refresh timestamp in DB for monitoring
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO system_events (event_type, payload)
                       VALUES ('nightly_refresh', $1::jsonb)
                       ON CONFLICT DO NOTHING""",
                    '{"elapsed_s": ' + str(round(elapsed, 1)) + ', "errors": ' + str(errors) + '}',
                )
        except Exception:
            pass  # Non-critical

        await asyncio.sleep(REFRESH_INTERVAL_HOURS * 3600)


def _time_now():
    import time
    return time.time()


async def _run_alerts(pool):
    async with pool.acquire() as conn:
        await run_daily_alert_check(conn)
