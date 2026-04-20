"""
startup.py — Background seed / ingestion tasks for Princeps.

Extracted from main.py lifespan.  Call ``await launch_background_tasks(pool)``
once at startup after ``setup_database(pool)`` has finished.
"""

import asyncio
import logging
import os

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
from utils.magic_ingester import ingest as magic_ingest
from utils.alc_ingester import ingest as alc_ingest
from app.readiness import mark_ready, mark_loading, mark_failed, update_progress
from app.dockets.authorities_seed import seed_authorities
from app.dockets.consultee_rules_seed import seed_consultee_rules

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

    # ── Bulk-import REPD into `projects` table once the REPD scrape lands.
    # Counsel found the dashboard "~12 projects" is because no one ever
    # called the bulk-import. Wait for REPD to populate, then run it once.
    asyncio.create_task(_safe_bg("bulk_import_repd_startup", _bulk_import_repd_if_thin, pool))

    # ── MAGIC + ALC environmental constraint layers (CLI-only ingesters,
    # wire them into startup + nightly refresh so buildable-area mask
    # actually has something to probe against).
    asyncio.create_task(_safe_bg("magic_seed", _run_magic_seed, pool))
    asyncio.create_task(_safe_bg("alc_seed", _run_alc_seed, pool))

    # ── GSP catalog seeding (unhardcode the 20-GSP list → full ~340)
    asyncio.create_task(_safe_bg("gsp_catalog_seed", _seed_gsp_catalog, pool))

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

    # ── Monthly DNO full re-ingestion (APScheduler cron) ───────────────
    # Task #21: give the DNO ingestion pipeline a guaranteed monthly
    # refresh beyond the nightly opportunistic loop. Cron runs on the
    # 1st of every month at 03:15 UTC, in-process (not via ARQ), so it
    # survives a service that doesn't have the separate scheduler
    # worker deployed.
    try:
        await _start_dno_monthly_scheduler(pool)
    except Exception as e:
        log.warning("DNO monthly scheduler init failed: %s", e)

    # ── Seed system workflow templates ──────────────────────────────
    asyncio.create_task(_safe_bg("workflow_templates_seed", _seed_workflow_templates, pool))

    # ── Princeps Alerts — seed alert_definitions + user_subscriptions ──
    # Gated on env so prod-once deploys can flip it off after first boot.
    if os.getenv("PRINCEPS_SEED_ALERTS", "true").lower() == "true":
        asyncio.create_task(_safe_bg("alerts_seed", _seed_alerts_and_tiers, pool))

    # ── Princeps Alerts — smoke document corpus for demo / dev ──
    # Gated on PRINCEPS_LOAD_SMOKE_DOCS. Inserts ~30 realistic UK energy
    # documents so /api/alerts/query/stream has grounded context on a
    # fresh DB. Keeps live mode consistent with frontend mock mode when
    # real ingestion workers haven't run yet.
    if os.getenv("PRINCEPS_LOAD_SMOKE_DOCS", "false").lower() == "true":
        asyncio.create_task(_safe_bg("alerts_smoke_docs", _seed_smoke_docs, pool))

    # ── Princeps Enterprise (Task #13) — tenants + audit log schema ──
    # Always applied (idempotent, cheap). Middleware is a separate opt-in.
    asyncio.create_task(_safe_bg("enterprise_tenancy_schema", _ensure_enterprise_tenancy, pool))
    asyncio.create_task(_safe_bg("enterprise_audit_log_schema", _ensure_enterprise_audit_log, pool))

    # ── Princeps Intelligence ingestion workers (Phase 7a, task #5) ──
    # Gated on env so local dev / CI doesn't kick off external scrapes
    # unless explicitly opted in. Runs in-process via APScheduler.
    if os.getenv("PRINCEPS_INGESTION_ENABLED", "false").lower() == "true":
        try:
            from app.ingestion.scheduler import start_ingestion_scheduler
            start_ingestion_scheduler(pool)
        except Exception as e:
            log.warning("Intelligence ingestion scheduler failed to start: %s", e)
    else:
        log.info("PRINCEPS_INGESTION_ENABLED not set — intelligence ingestion disabled")

    # ── Princeps Dockets — authorities registry + consultee rules ────
    # Gated by PRINCEPS_SEED_AUTHORITIES. Consultee rules FK into
    # authorities, so run authorities first and only proceed to the
    # rules once the upsert completes.
    if os.environ.get("PRINCEPS_SEED_AUTHORITIES", "false").lower() == "true":
        async def _seed_dockets_registry(p):
            await seed_authorities(p)
            await seed_consultee_rules(p)
        asyncio.create_task(_safe_bg(
            "dockets_registry_seed", _seed_dockets_registry, pool,
        ))

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


# ─────────────────────────────────────────────────────────────────────────
# Bulk-import REPD into `projects` on first boot — root-cause of the
# "~12 projects" dashboard. Waits up to 3 minutes for the REPD scrape
# to populate `repd_projects` before running the upsert.
# ─────────────────────────────────────────────────────────────────────────

_REPD_BULK_STATUS_MAP = {
    "Operational": "energised",
    "Under Construction": "construction",
    "Awaiting Construction": "fid",
    "Approved": "planning",
    "Submitted": "grid_applied",
    "Appeal": "planning",
    "Refused": "prospect",
    "Withdrawn": "prospect",
    "Decommissioned": "energised",
}
_REPD_TECH_MAP = {"solar": "solar", "wind": "wind", "bess": "bess", "biomass": "solar", "hydro": "solar"}


async def _bulk_import_repd_if_thin(pool: asyncpg.Pool) -> None:
    """If `projects` has <100 real rows AND `repd_projects` has rows, copy
    the UK pipeline over once. Skips silently on repeated starts."""
    import json as _json

    # Wait up to 3 minutes for the REPD scrape to land rows.
    for _ in range(36):
        async with pool.acquire() as conn:
            n_repd = await conn.fetchval("SELECT count(*) FROM repd_projects") or 0
            n_proj = await conn.fetchval(
                "SELECT count(*) FROM projects WHERE repd_id IS NOT NULL"
            ) or 0
        if n_repd > 1000 and n_proj < 100:
            break
        if n_proj >= 100:
            log.info("REPD bulk-import: skipped (projects already has %d REPD rows)", n_proj)
            return
        await asyncio.sleep(5)
    else:
        log.info("REPD bulk-import: scrape never populated (repd_projects empty) — skipping")
        return

    # Copy REPD rows in — same shape as POST /import-repd-bulk but with
    # min_capacity_mw=1 and limit=5000 per counsel recommendation.
    # Note: repd_projects has `geometry` (SRID 27700), not lat/lon columns —
    # extract via ST_Transform + ST_Y / ST_X.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.repd_id, r.site_name, r.status, r.tech_category, r.capacity_mw,
                   r.developer, r.planning_authority, r.county, r.region,
                   ST_Y(ST_Transform(r.geometry, 4326)) AS lat,
                   ST_X(ST_Transform(r.geometry, 4326)) AS lon
            FROM repd_projects r
            LEFT JOIN projects p ON p.repd_id = r.repd_id
            WHERE r.capacity_mw >= 1 AND r.geometry IS NOT NULL AND p.project_id IS NULL
            ORDER BY r.capacity_mw DESC
            LIMIT 5000
            """
        )
        imported = 0
        for r in rows:
            stage = _REPD_BULK_STATUS_MAP.get(r["status"], "prospect")
            tech = _REPD_TECH_MAP.get(r.get("tech_category"), None)
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO projects
                        (user_id, name, description, technology, capacity_mw,
                         stage, lat, lon, stage_entered_at, repd_id, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10)
                    ON CONFLICT (repd_id) DO NOTHING
                    RETURNING project_id
                    """,
                    None,
                    r["site_name"],
                    f"Bulk imported from REPD — {r['status']}",
                    tech,
                    float(r["capacity_mw"]) if r["capacity_mw"] else None,
                    stage,
                    float(r["lat"]) if r.get("lat") else None,
                    float(r["lon"]) if r.get("lon") else None,
                    r["repd_id"],
                    _json.dumps({
                        "repd_status": r["status"],
                        "developer": r.get("developer"),
                        "planning_authority": r.get("planning_authority"),
                        "county": r.get("county"),
                        "region": r.get("region"),
                        "source": "bulk_import_startup",
                    }),
                )
                if row:
                    imported += 1
            except Exception:
                continue
    log.info("REPD bulk-import: imported %d projects at startup", imported)


# ─────────────────────────────────────────────────────────────────────────
# MAGIC + ALC environmental constraints — the buildable-area mask probes
# `magic_constraints` and `alc_grades`; without these, every D5 mask comes
# back half-populated. CLI ingesters run nationally with no bbox.
# ─────────────────────────────────────────────────────────────────────────

_MAGIC_LAYERS = ["sssi", "aonb", "flood2", "flood3", "habitat"]


async def _run_magic_seed(pool: asyncpg.Pool) -> None:
    """Seed MAGIC constraint layers if the `magic_constraints` table is empty."""
    try:
        async with pool.acquire() as conn:
            has_table = await conn.fetchval(
                "SELECT to_regclass('public.magic_constraints') IS NOT NULL"
            )
            if not has_table:
                log.info("MAGIC seed: table does not exist — skipping (run ingester CLI to create)")
                return
            n = await conn.fetchval("SELECT count(*) FROM magic_constraints") or 0
        if n >= 1000:
            log.info("MAGIC seed: already has %d rows — skipping", n)
            return
    except Exception as e:
        log.info("MAGIC seed: precheck failed (%s) — skipping", e)
        return
    try:
        summary = await magic_ingest(layers=_MAGIC_LAYERS, bbox=None, dry_run=False)
        log.info("MAGIC seed: ingested %d features across %d layers",
                 summary.get("total_features", 0), len(summary.get("layers", {})))
    except Exception as e:
        log.warning("MAGIC seed failed: %s", e)


async def _run_alc_seed(pool: asyncpg.Pool) -> None:
    """Seed ALC agricultural land grades if `alc_grades` is empty."""
    try:
        async with pool.acquire() as conn:
            has_table = await conn.fetchval(
                "SELECT to_regclass('public.alc_grades') IS NOT NULL"
            )
            if not has_table:
                log.info("ALC seed: table does not exist — skipping")
                return
            n = await conn.fetchval("SELECT count(*) FROM alc_grades") or 0
        if n >= 10_000:
            log.info("ALC seed: already has %d rows — skipping", n)
            return
    except Exception as e:
        log.info("ALC seed: precheck failed (%s) — skipping", e)
        return
    try:
        summary = await alc_ingest(bbox=None, dry_run=False)
        log.info("ALC seed: ingested %d features", summary.get("written", 0))
    except Exception as e:
        log.warning("ALC seed failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────
# GSP catalog — unhardcode the 20-entry list in demand_data_ingester.py.
# NESO CKAN publishes boundary polygons + centroids for every GSP. Seed
# a `gsp_catalog` table that `/api/demand/gsps` can read instead.
# ─────────────────────────────────────────────────────────────────────────

_NESO_CKAN_BASE = "https://api.neso.energy/api/3/action"
_GSP_BOUNDARY_PACKAGE = "gis-boundaries-for-gb-grid-supply-points"
_GSP_GROUP_PACKAGE = "gsp-group-mapping-table"


async def _seed_gsp_catalog(pool: asyncpg.Pool) -> None:
    """Ensure `gsp_catalog` exists and is seeded with all ~340 UK GSPs from
    NESO CKAN. Falls back to the hardcoded 20 in demand_data_ingester if
    the CKAN fetch fails — UI stays usable either way."""
    import httpx

    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gsp_catalog (
                    gsp_id TEXT PRIMARY KEY,
                    gsp_name TEXT,
                    gsp_group_id TEXT,
                    dno TEXT,
                    region TEXT,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    peak_demand_mw DOUBLE PRECISION,
                    min_demand_mw DOUBLE PRECISION,
                    capacity_mw DOUBLE PRECISION,
                    source TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        except Exception as e:
            log.warning("gsp_catalog create failed: %s", e)
            return
        n_existing = await conn.fetchval("SELECT count(*) FROM gsp_catalog") or 0
        if n_existing >= 100:
            log.info("GSP catalog: already has %d rows — skipping", n_existing)
            return

    # Seed from the 20 hardcoded entries first so the UI always has
    # something. Then augment from NESO CKAN if reachable.
    try:
        from utils.demand_data_ingester import UK_GSPS
    except Exception:
        UK_GSPS = []

    async with pool.acquire() as conn:
        for g in UK_GSPS:
            try:
                await conn.execute(
                    """
                    INSERT INTO gsp_catalog
                        (gsp_id, gsp_name, dno, region, lat, lon,
                         peak_demand_mw, min_demand_mw, capacity_mw, source)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'demand_data_ingester_seed')
                    ON CONFLICT (gsp_id) DO NOTHING
                    """,
                    g["gsp_id"], g["gsp_name"], g.get("dno"), g.get("region"),
                    g.get("lat"), g.get("lon"),
                    g.get("peak_mw"), g.get("min_mw"), g.get("capacity_mw"),
                )
            except Exception:
                continue

    # Augment from NESO CKAN. Resolve the package → first GeoJSON/CSV
    # resource → row-by-row upsert. Defensive — any failure leaves the
    # 20-GSP seed in place rather than erroring the app.
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            pkg = await client.get(
                f"{_NESO_CKAN_BASE}/package_show",
                params={"id": _GSP_BOUNDARY_PACKAGE},
            )
            pkg.raise_for_status()
            pkg_data = pkg.json().get("result", {})
            resources = pkg_data.get("resources", [])
            geo_res = next((r for r in resources if (r.get("format") or "").lower()
                           in ("geojson", "json")), None)
            if not geo_res or not geo_res.get("url"):
                log.info("GSP catalog: NESO CKAN has no geojson resource — keeping 20-GSP seed")
                return
            gj = await client.get(geo_res["url"])
            gj.raise_for_status()
            fc = gj.json()
    except Exception as e:
        log.info("GSP catalog: NESO CKAN fetch skipped (%s) — keeping 20-GSP seed", e)
        return

    inserted = 0
    async with pool.acquire() as conn:
        for feat in (fc.get("features") or []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            # NESO gsp_regions_20181031 uses RegionID + RegionName.
            # Other potential NESO packages use GSP_ID / gsp_id / node.
            gsp_id = (
                props.get("RegionID") or props.get("GSP_ID")
                or props.get("gsp_id") or props.get("node") or props.get("code")
            )
            gsp_name = (
                props.get("RegionName") or props.get("GSP_NAME")
                or props.get("gsp_name") or props.get("name") or gsp_id
            )
            if not gsp_id:
                continue
            # Centroid from geometry — simplest viable: take first coord.
            lat, lon = None, None
            try:
                if geom.get("type") == "Point":
                    lon, lat = geom["coordinates"][:2]
                elif geom.get("type") == "Polygon":
                    # Rough centroid from first ring
                    ring = geom["coordinates"][0]
                    xs = [p[0] for p in ring]
                    ys = [p[1] for p in ring]
                    lon = sum(xs) / len(xs); lat = sum(ys) / len(ys)
                elif geom.get("type") == "MultiPolygon":
                    ring = geom["coordinates"][0][0]
                    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
                    lon = sum(xs) / len(xs); lat = sum(ys) / len(ys)
            except Exception:
                pass
            try:
                await conn.execute(
                    """
                    INSERT INTO gsp_catalog
                        (gsp_id, gsp_name, gsp_group_id, lat, lon, source)
                    VALUES ($1, $2, $3, $4, $5, 'neso_ckan_boundary')
                    ON CONFLICT (gsp_id) DO UPDATE
                    SET gsp_name = EXCLUDED.gsp_name,
                        gsp_group_id = COALESCE(EXCLUDED.gsp_group_id, gsp_catalog.gsp_group_id),
                        lat = COALESCE(EXCLUDED.lat, gsp_catalog.lat),
                        lon = COALESCE(EXCLUDED.lon, gsp_catalog.lon),
                        updated_at = NOW()
                    """,
                    str(gsp_id), str(gsp_name),
                    props.get("GSP_GROUP_ID") or props.get("group_id"),
                    lat, lon,
                )
                inserted += 1
            except Exception:
                continue
    log.info("GSP catalog: seeded / refreshed %d GSPs from NESO CKAN", inserted)


# ─────────────────────────────────────────────────────────────────────────
# Task #21 — Monthly APScheduler cron for full DNO re-ingestion.
# In-process AsyncIOScheduler; survives without the external
# `app.agents.scheduler` process. Stored on app.state so it gets shut down
# cleanly on lifespan exit.
# ─────────────────────────────────────────────────────────────────────────

_dno_scheduler = None  # module-level handle; main.py shutdown hook can use


async def _start_dno_monthly_scheduler(pool: asyncpg.Pool) -> None:
    """Spin up an APScheduler AsyncIOScheduler with a monthly DNO run.

    Cron: 1st of every month @ 03:15 UTC — after nightly refresh, so
    the monthly run can rely on fresh upstream state.
    """
    global _dno_scheduler
    if _dno_scheduler is not None:
        return  # already started

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.warning("APScheduler not installed — monthly DNO cron disabled")
        return

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _monthly_ingest_job():
        log.info("Monthly DNO ingest job starting (APScheduler)")
        try:
            summary = await ingest_all_dnos(pool)
            log.info("Monthly DNO ingest complete: %s", summary)
        except Exception as e:
            log.exception("Monthly DNO ingest failed: %s", e)

    scheduler.add_job(
        _monthly_ingest_job,
        CronTrigger(day=1, hour=3, minute=15),
        id="dno_monthly_ingest",
        name="DNO monthly full ingest",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _dno_scheduler = scheduler
    log.info("APScheduler: monthly DNO ingest cron registered (day=1 03:15 UTC)")


def get_dno_scheduler():
    """Return the singleton scheduler (for shutdown hooks)."""
    return _dno_scheduler


# ─────────────────────────────────────────────────────────────────────────
# Princeps Alerts seed (Task #6) — 82 UK SKUs + default free-tier rows.
# Idempotent; safe to re-run on every boot.
# ─────────────────────────────────────────────────────────────────────────

async def _seed_alerts_and_tiers(pool: asyncpg.Pool) -> None:
    """Seed alert_definitions and user_subscriptions default tiers."""
    try:
        from app.alerts import seed_alert_definitions, seed_user_tier_defaults
    except Exception as e:
        log.warning("alerts seed skipped — module not importable: %s", e)
        return
    await seed_alert_definitions(pool)
    await seed_user_tier_defaults(pool)


async def _seed_smoke_docs(pool: asyncpg.Pool) -> None:
    """Load the smoke-data UK energy corpus so query/stream has context."""
    try:
        from app.alerts.smoke_data import seed_smoke_docs
    except Exception as e:
        log.warning("smoke docs seed skipped — module not importable: %s", e)
        return
    await seed_smoke_docs(pool)


# ─────────────────────────────────────────────────────────────────────────
# Enterprise readiness (Task #13) — tenancy + audit-log schema bootstrap.
# ─────────────────────────────────────────────────────────────────────────

async def _ensure_enterprise_tenancy(pool: asyncpg.Pool) -> None:
    """Apply migration 0005 (tenants + memberships + sso configs)."""
    try:
        from app.enterprise.tenants import ensure_schema
    except Exception as e:
        log.warning("enterprise tenancy schema skipped — not importable: %s", e)
        return
    await ensure_schema(pool)


async def _ensure_enterprise_audit_log(pool: asyncpg.Pool) -> None:
    """Apply migration 0006 (audit_log_v2)."""
    try:
        from app.enterprise.audit_log import ensure_schema
    except Exception as e:
        log.warning("enterprise audit-log schema skipped — not importable: %s", e)
        return
    await ensure_schema(pool)


def register_audit_middleware(app) -> bool:
    """Attach the audit-log middleware to *app* if enabled by env.

    Called from ``app/main.py`` at module import time (before the first
    request) so the middleware is in place before any traffic. Returns
    True if registered, False if skipped so callers can log the outcome.
    """
    if os.getenv("PRINCEPS_AUDIT_ENABLED", "false").lower() != "true":
        return False
    try:
        from app.enterprise.audit_log import AuditLogMiddleware
    except Exception as e:
        log.warning("audit middleware import failed: %s", e)
        return False
    app.add_middleware(AuditLogMiddleware)
    log.info("PRINCEPS_AUDIT_ENABLED=true — AuditLogMiddleware registered")
    return True
