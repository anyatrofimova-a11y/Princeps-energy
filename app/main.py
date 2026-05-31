"""Princeps API — Energy infrastructure site feasibility platform.

Modular FastAPI application. All endpoint logic lives in app/routers/*.py;
this file handles application creation, lifespan, middleware, and static serving.
"""

from __future__ import annotations

import os
import pathlib
import logging
import time as _time
from contextlib import asynccontextmanager
from uuid import uuid4

from dotenv import load_dotenv
load_dotenv()

import sys
# Allow importing from project root (for utils/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic
import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.db_setup import setup_database
from app.startup import launch_background_tasks
from app.errors import APIError, api_error_handler
from app.helpers import SAM_PYTHON, CLAUDE_MODEL
from app.readiness import get_status as readiness_status, core_ready as _core_ready, reset_start_time

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_format = os.environ.get("LOG_FORMAT", "text")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s" if _log_format != "json" else "%(message)s",
)
log = logging.getLogger("princeps")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")

if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL env var")
if not CLAUDE_API_KEY:
    raise RuntimeError("Set CLAUDE_API_KEY env var")


# ---------------------------------------------------------------------------
# Lifespan — pool creation, DB setup, background tasks, teardown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=3, max_size=15, command_timeout=30,
        statement_cache_size=0,
    )
    log.info("Database pool created (min=3, max=15, stmt_cache=0 — pgbouncer-safe)")

    _app.state.pool = pool
    _app.state.claude = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
    _app.state._start_time = _time.time()
    reset_start_time()

    # Initialize persistent modules with pool reference
    import jobs
    jobs.init_pool(pool)
    import chat as chat_module
    chat_module.init_pool(pool)

    try:
        await setup_database(pool)
    except Exception as _db_exc:
        log.exception("setup_database failed — app will continue with partial schema: %s", _db_exc)

    # Pulse suite — ensure new schemas exist (idempotent, fast)
    try:
        from utils.cluster_graph import ensure_schema as ensure_cluster_schema
        from utils.grid_events import ensure_schema as ensure_events_schema
        from utils.nged_live_feed import ensure_schema as ensure_nged_live_schema
        from utils.nged_gsp_data import ensure_schema as ensure_nged_gsp_schema
        from utils.nged_ecr import ensure_schema as ensure_nged_ecr_schema
        from utils.curtailment_intelligence import ensure_schema as ensure_curtailment_schema
        from utils.gu_capabilities import ensure_schema as ensure_gu_schema
        from utils.dno_opendata_ingester import ensure_schema as ensure_dno_schema
        from utils.neso098_dc_optimiser import ensure_schema as ensure_neso098_schema
        from utils.planning_data_uk import ensure_schema as ensure_planning_data_schema
        await ensure_cluster_schema(pool)
        await ensure_events_schema(pool)
        await ensure_nged_live_schema(pool)
        await ensure_nged_gsp_schema(pool)
        await ensure_nged_ecr_schema(pool)
        await ensure_curtailment_schema(pool)
        await ensure_gu_schema(pool)
        await ensure_dno_schema(pool)
        await ensure_neso098_schema(pool)
        await ensure_planning_data_schema(pool)
        log.info("Pulse + Gu + NESO098 + planning.data.gov.uk schemas ensured")
    except Exception as e:
        log.warning("Pulse suite schema setup failed: %s", e)

    await launch_background_tasks(pool)

    yield

    # Teardown
    from utils.graph_topology import close_driver as neo4j_close
    await neo4j_close()
    # Stop the Magritte cadence scheduler before tearing down the pool
    # so any in-flight jobs get a chance to release their connections.
    try:
        from app.startup import get_connector_scheduler
        cs = get_connector_scheduler()
        if cs is not None:
            cs.stop()
    except Exception as _e:
        log.warning("connector_scheduler stop on lifespan exit failed: %s", _e)
    await pool.close()


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------
app = FastAPI(title="Princeps API", lifespan=lifespan)

ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = _time.monotonic()
        response = await call_next(request)
        elapsed = _time.monotonic() - t0
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Request-Duration-Ms"] = f"{elapsed * 1000:.1f}"
        response.headers["X-Request-ID"] = str(uuid4())
        if elapsed > 5.0:
            log.warning("Slow request: %s %s took %.1fs", request.method, request.url.path, elapsed)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# License Guard — hard-blocks NC-licensed model artifacts on commercial endpoints.
from app.license_guard import LicenseGuardMiddleware  # noqa: E402
app.add_middleware(LicenseGuardMiddleware)

# Register audit-log middleware (Task #13) — opt-in via PRINCEPS_AUDIT_ENABLED.
try:
    from app.startup import register_audit_middleware  # noqa: E402
    register_audit_middleware(app)
except Exception as _exc:
    log.warning("audit middleware registration failed: %s", _exc)

# Register structured error handler
app.add_exception_handler(APIError, api_error_handler)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check(request: Request):
    """Multi-component health check."""
    pool = request.app.state.pool
    checks = {}
    overall = "healthy"

    # Database
    try:
        async with pool.acquire(timeout=5) as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = {"status": "healthy"}
    except Exception as exc:
        checks["database"] = {"status": "unhealthy", "error": str(exc)}
        overall = "degraded"

    # SAM availability
    sam_ok = pathlib.Path(SAM_PYTHON).is_file()
    checks["sam"] = {"status": "healthy" if sam_ok else "unavailable", "path": SAM_PYTHON}
    if not sam_ok:
        overall = "degraded"

    # Claude API
    checks["claude"] = {
        "status": "healthy" if CLAUDE_API_KEY else "missing",
        "model": CLAUDE_MODEL,
    }

    # Pool stats
    checks["pool"] = {
        "size": pool.get_size(),
        "free": pool.get_idle_size(),
        "min": pool.get_min_size(),
        "max": pool.get_max_size(),
    }

    # Agentmemory sidecar (Task #28 — cross-session episodic recall)
    try:
        from app.memory import memory_health
        am_ok = await memory_health()
        checks["agentmemory"] = {"status": "healthy" if am_ok else "unreachable"}
        if not am_ok:
            overall = "degraded"
    except Exception as exc:
        checks["agentmemory"] = {"status": "error", "error": str(exc)}

    # Uptime
    uptime = _time.time() - getattr(request.app.state, "_start_time", _time.time())

    return {
        "status": overall,
        "checks": checks,
        "uptime_s": round(uptime, 1),
        "core_ready": _core_ready(),
    }


# ---------------------------------------------------------------------------
# Readiness — progressive subsystem startup tracking
# ---------------------------------------------------------------------------
@app.get("/api/readiness")
async def readiness_endpoint():
    """Progressive readiness status for all subsystems.

    Returns overall state (starting/ready/degraded), per-subsystem status,
    and a core_ready flag the frontend can use to start making API calls
    before all background ingestion finishes.
    """
    return readiness_status()


# ---------------------------------------------------------------------------
# Register all routers
# ---------------------------------------------------------------------------
from app.graph_neo4j import router as graph_router  # noqa: E402

_ROUTER_MODULES = [
    "alerts",
    "site", "geeflow", "grid", "demand", "strategy", "market",
    "legacy", "procurement", "grid_efficiency", "prospector", "scoring",
    "sustainability", "vision", "analytics", "retrofit",
    "regulatory", "nom", "notifications", "investment", "home_retrofit",
    "chat", "jobs",
    "assessments", "workflows", "auth",
    "cim",
    "consultees",
    "datacentre", "reports", "reports_fva", "dc_reports",
    "hardware",
    "teaser",
    "dc_planner", "dc_ops", "eurosat", "land", "projects", "finance",
    "site_design", "environment", "land_management",
    "terrain", "planning_ml", "live_grid", "construction",
    "prospector_v2", "ppa_origination", "dispatch_model", "bess_revenue",
    "cable_routing", "yield_assessment", "portfolio", "grid_queue",
    "dockets",
    "documents", "dc_layout", "electrical", "yield_intel",
    "solar_layout", "export_usd", "design", "design_extras",
    "enrichment",  # must precede "analysis" — its catch-all /api/analysis/{name} shadows /api/analysis/enrich
    "analysis",
    "finance_extras",
    "neso", "dno", "market_data",
    "cluster", "events", "portfolio_delta", "nged", "curtailment",
    "dc_hyperscaler", "ltds_cim", "gu", "neso098",
    "portfolios_crud",
    "project_actions",
    "settings",
    "ontology",
    "forecast",
    "engineering_primitives",
    "connectors",
    "connector_scheduler",  # APScheduler cadence orchestration for Magritte
    "datasets",     # Magritte dataset registry — princeps_datasets + lineage
    "exports",
    "twin_assets",
    "twin_dynamic",
    "twin",
    "parcel",
    "agent_ops",
    "site_analysis",  # YC-pitch demo endpoint — POST /api/agent/analyze-site
    "substation_tracker",
    "n1_contingency",
    "billing",
    "enterprise_admin",
    "substrate",
    "ea_layers",
    "land_rights",
    "heritage_nature",
    "scan",
    "parcel_enrich",
    "lccc",
    "constraints",
    "project_memo",
    "utilities",
    "dno_engagement_workflow",
    "dno_engagement",
    "portfolio_asset_exposure",
    "asset_intel",
    "industrial",  # Swarm 6 — UK Industrial Base Graph
    "actions",     # Swarm 8 — typed Action Registry REST surface
    "workshop",    # Workshop shell — /api/workshop/object + /api/workshop/tree
    "dc_design",   # D1 — DC placement constraints (OSM forbidden zones)
    "grid_overlay", # D3 — TEC/ECR/REPD GeoJSON + lines + project-info cards
    "graph",        # Graph shadow ontology MVP — recursive-CTE Cypher shim
    "workshop_modules",  # Workshop Module Builder MVP — AI-composed manifests
    "bess_live",    # Live BESS revenue dashboard — WS + REST + Modo overlay
    "council",      # Agentic Council — GRID + BESS + DC pods + Adjudicator (SSE)
    "mission_control_v2",  # Composed Workshop module — ontology-first home screen
    "objects",      # Typed Object Page generator — /api/objects/:type[/:id]
    "lineage",      # Foundry-style provenance: connector → table → class → object
    "branches",     # Foundry-style fork-and-merge — what-if scenarios on objects
    "notes",        # Foundry Notepad — markdown notes pinned to objects
    "pending_actions",  # Action approval workflow — preview → approve / reject
    "solutions",    # Foundry Marketplace — installable Slate dashboards
    "object_sets",  # ObjectSet primitives — saved typed queries with set algebra
    "object_events",  # SSE bridge over Postgres LISTEN/NOTIFY — live widgets
    "pipelines",    # Pipeline Builder — declarative DAG executor
    "planning_constraints",  # planning.data.gov.uk Top-21 OGL v3.0 datasets (Task #17)
    "flexibility",  # Northern Powergrid Flexibility ontology — 7 OpenDataSoft datasets (Task #27)
    "asset_health", # Per-RID weighted 0-100 health score with driver provenance
    "sso",          # OIDC federated identity (Auth0/Keycloak/Google/Entra/Okta)
    "timeseries",   # Time-series store — sensor history + binned aggregations
    "timeseries_feasibility",  # 24h AC time-series + outage-window feasibility (TU Delft port)
    "synthetic_grids",         # Princeps PowerGridSynth substitute — CGMES export (Task #19)
    "demo_seed",               # One-shot endpoint to load the BESS+DC demo seed
    "grid_osm",                # /api/grid/osm/* — Map layer endpoints (substations from LTDS)
    "finance_agentic",         # /api/finance/auto-defaults · explain-verdict · optimise · sensitivity-scenarios
    "portfolio_performance",   # /api/portfolio/bess-revenue · /updates — Portfolio Performance tile + Updates tab
    "parcel_enrichment",       # /api/parcels/{inspire_id}/enriched — ALC + BNG + Companies House + Tenders
    "contract_intelligence",   # /api/contracts/* — document workspace, cite, diff, obligations
    "applications",            # /api/applications/* — UK grid+planning templates + pre-fill
]

app.include_router(graph_router)

# BOT-LOG-AUTH: Mount the login router used by the React login page.
# Kept separate from app/routers/auth.py (DB-backed v1 auth at /api/v1/auth)
# so the new in-memory allow-list flow can live cleanly at /api/auth/*.
from app.routers import auth_login as auth_router  # noqa: E402
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])

import importlib  # noqa: E402

_skipped: list[tuple[str, str]] = []
for _mod_name in _ROUTER_MODULES:
    try:
        _mod = importlib.import_module(f"app.routers.{_mod_name}")
        app.include_router(_mod.router)
        # Side-routers: any module exposing additional `*_router` attrs gets
        # them included automatically. Used by `objects.py` for the spatial
        # geo router that must live under a different prefix.
        for _attr in dir(_mod):
            if _attr != "router" and _attr.endswith("_router"):
                _side = getattr(_mod, _attr, None)
                if _side is not None and hasattr(_side, "routes"):
                    app.include_router(_side)
    except Exception as _exc:
        _skipped.append((_mod_name, f"{type(_exc).__name__}: {_exc}"))
        log.warning("router %s skipped: %s", _mod_name, _exc)

# Trust Center lives under app/enterprise/ rather than app/routers/, so
# register it directly rather than through _ROUTER_MODULES.
try:
    from app.enterprise.trust_center import router as _trust_router  # noqa: E402
    app.include_router(_trust_router)
except Exception as _exc:
    log.warning("trust_center router skipped: %s", _exc)

if _skipped:
    log.warning("Router load: %d of %d skipped — %s",
                len(_skipped), len(_ROUTER_MODULES),
                ", ".join(n for n, _ in _skipped))


# ---------------------------------------------------------------------------
# Static frontend serving (production / ngrok demo)
# ---------------------------------------------------------------------------
_DIST_DIR = pathlib.Path(__file__).resolve().parent.parent / "feasi-frontend" / "dist"

if _DIST_DIR.is_dir():
    from starlette.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="static-assets")

# Design exports (PDF / DWG / CSV) — served under /static/design_exports/
_EXPORTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "design_exports"
_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
try:
    from starlette.staticfiles import StaticFiles as _SF
    app.mount("/static/design_exports",
              _SF(directory=_EXPORTS_DIR),
              name="design-exports")
except Exception as _e:
    log.warning("design_exports static mount failed: %s", _e)

# Twin geometry assets (IFC + glTF) served under /static/cad and /static/glb.
_CAD_DIR = pathlib.Path(__file__).resolve().parent.parent / "static" / "cad"
_GLB_DIR = pathlib.Path(__file__).resolve().parent.parent / "static" / "glb"
_CAD_DIR.mkdir(parents=True, exist_ok=True)
_GLB_DIR.mkdir(parents=True, exist_ok=True)
try:
    from starlette.staticfiles import StaticFiles as _SF
    app.mount("/static/cad", _SF(directory=_CAD_DIR), name="static-cad")
    app.mount("/static/glb", _SF(directory=_GLB_DIR), name="static-glb")
except Exception as _e:
    log.warning("twin geometry static mounts failed: %s", _e)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file_path = _DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_DIST_DIR / "index.html")
