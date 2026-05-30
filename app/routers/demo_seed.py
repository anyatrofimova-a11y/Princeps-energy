"""Demo seed router — populates the Princeps workspace with the canonical
BESS + DC demo so deployed instances surface real data on first boot.

POST /api/demo/seed-workspace
  Loads migrations/twin_seed_v1__bess_dc_demo.sql which seeds:
    - 2 BESS units (Essex 100 MW, Aldershot 50 MW) with block/rack/cell hierarchy
    - 2 Data Centres (Slough 50 MW, Cardington 20 MW) with hall/aisle/rack hierarchy
    - Substations + counterparty entities
  Idempotent (ON CONFLICT DO NOTHING on every row).
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_pool

log = logging.getLogger("princeps.routers.demo_seed")
router = APIRouter(prefix="/api/demo", tags=["demo"])

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"
SEED_MIGRATIONS = [
    # 1. Twin schema (twin_models / twin_instances / twin_relationships).
    "twin_v1__models_instances_relationships.sql",
    # 2. CAD geometry tables (referenced by some seed rows).
    "twin_geometry_v1__cad_assets.sql",
    # 3. BESS + DC demo data (idempotent ON CONFLICT DO NOTHING).
    "twin_seed_v1__bess_dc_demo.sql",
    # 4. Regulatory dataset registry (princeps_datasets table + 21 datasets).
    "2026_05_03_dataset_registry.sql",
    # 5. Connector refresh log (dataset_refresh_log for "Connector health" tile).
    "2026_05_03_connector_schedule_log.sql",
    # 6. NSIP/DCO seed for Intelligence > Dockets.
    "2026_05_03_pins_nsip.sql",
    # 7. Demo docket pins linked to projects.
    "2026_04_21d_seed_docket_pins.sql",
    # 8. Intelligence seed — 21 UK Energy & Planning datasets visible on
    #    the Intelligence > Datasets surface.
    "2026_05_27_intelligence_seed.sql",
    # 9a. BESS Live Revenue schema (table + indices). Must run before the
    #     seed below.
    "2026_05_01_bess_live_revenue.sql",
    # 9b. BESS Live Revenue — 30 days × hourly P10/P50/P90 for 3 BESS projects.
    "2026_05_27_bess_live_revenue_seed.sql",
    # 10. Workshop modules table (for /api/workshop/modules — currently 500s
    #     on Supabase because the table doesn't exist).
    "2026_05_02_workshop_modules.sql",
    # 11. Council sessions table (for /api/council/sessions — same story).
    "2026_05_01_council_sessions.sql",
]


@router.post("/seed-workspace")
async def seed_workspace(pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Apply the twin schema + canonical BESS + DC demo seed.

    Order matters: schema migrations run first, then data. Safe to re-run.
    """
    applied: list[dict] = []
    for fname in SEED_MIGRATIONS:
        path = MIGRATIONS_DIR / fname
        if not path.is_file():
            applied.append({"file": fname, "status": "missing"})
            continue
        sql = path.read_text()
        # Supabase doesn't ship the Apache AGE graph extension. The twin
        # schema only needs AGE for the optional graph queries, so we strip
        # the CREATE EXTENSION line before applying — the tables themselves
        # are pure PostgreSQL + PostGIS.
        sql = sql.replace("CREATE EXTENSION IF NOT EXISTS age;",
                          "-- CREATE EXTENSION age skipped (not available on Supabase)")
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(sql)
            applied.append({"file": fname, "status": "ok"})
        except Exception as exc:
            log.exception("seed migration %s failed", fname)
            applied.append({"file": fname, "status": "error", "error": str(exc)[:300]})

    async with pool.acquire() as conn:
        try:
            n_twins = await conn.fetchval("SELECT COUNT(*) FROM twin_instances")
        except Exception:
            n_twins = None
        try:
            n_ents = await conn.fetchval("SELECT COUNT(*) FROM entities")
        except Exception:
            n_ents = None

    return {
        "status": "ok",
        "migrations": applied,
        "twin_instances_count": n_twins,
        "entities_count": n_ents,
    }


@router.get("/seed-status")
async def seed_status(pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Report current row counts for the demo tables."""
    counts: dict[str, int | None] = {}
    async with pool.acquire() as conn:
        for table in ("twin_instances", "entities", "twin_models",
                       "ltds_substations", "synthetic_grids",
                       "planning_designations", "uk_flexibility_zones"):
            try:
                counts[table] = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            except Exception:
                counts[table] = None
    return {"counts": counts}
