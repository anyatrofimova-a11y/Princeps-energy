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
from utils.dc_infra_ingester import ingest_dc_infrastructure
from utils.alert_engine import run_daily_alert_check

log = logging.getLogger("princeps")


async def _safe_bg(name: str, coro_func, *args) -> None:
    """Run a coroutine and log rather than crash on failure."""
    try:
        await coro_func(*args)
    except Exception as e:
        log.warning("Background task %s failed: %s", name, e)


async def launch_background_tasks(pool: asyncpg.Pool) -> None:
    """Fire-and-forget background seed / ingestion tasks.

    Each task is launched via ``asyncio.create_task`` so they run
    concurrently without blocking the server startup.
    """

    # ── OSM power infrastructure seeding ──────────────────────────────
    asyncio.create_task(osm_power_seed(pool))

    # ── NGED CIM data seeding ─────────────────────────────────────────
    asyncio.create_task(nged_seed(pool))

    # ── ESO TEC + REPD seeding ────────────────────────────────────────
    asyncio.create_task(eso_tec_seed(pool))
    asyncio.create_task(repd_seed(pool))

    # ── Neo4j graph topology (graceful degradation) ───────────────────
    try:
        await neo4j_init()
        if neo4j_available():
            asyncio.create_task(neo4j_seed(pool))
    except Exception as e:
        log.warning("Neo4j init skipped — graph features disabled: %s", e)

    # ── Regulatory intelligence background ingestion ──────────────────
    asyncio.create_task(_safe_bg("repd_ingest", ingest_repd, pool))
    asyncio.create_task(_safe_bg("tec_ingest", ingest_tec_register, pool))
    asyncio.create_task(_safe_bg("grid_upgrade_ingest", ingest_nged_upgrades, pool))

    # ── Grid Connection module — ingest all DNO data ──────────────────
    asyncio.create_task(_safe_bg("grid_connection_ingest", ingest_all_dnos, pool))

    # ── DC infrastructure — fibre POPs, IXPs, water bodies, DCs ─────
    asyncio.create_task(_safe_bg("dc_infra_ingest", ingest_dc_infrastructure, pool))

    # ── Daily alert loop ──────────────────────────────────────────────
    async def _daily_alert_loop():
        while True:
            await asyncio.sleep(24 * 3600)
            try:
                async with pool.acquire() as conn:
                    await run_daily_alert_check(conn)
            except Exception as e:
                log.error("Daily alert check failed: %s", e)

    asyncio.create_task(_daily_alert_loop())

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
