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
    )
    log.info("Database pool created (min=3, max=15)")

    _app.state.pool = pool
    _app.state.claude = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)
    _app.state._start_time = _time.time()
    reset_start_time()

    # Initialize persistent modules with pool reference
    import jobs
    jobs.init_pool(pool)
    import chat as chat_module
    chat_module.init_pool(pool)

    await setup_database(pool)
    await launch_background_tasks(pool)

    yield

    # Teardown
    from utils.graph_topology import close_driver as neo4j_close
    await neo4j_close()
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
from app.graph import router as graph_router  # noqa: E402

from app.routers import (  # noqa: E402
    site, geeflow, grid, demand, strategy, market,
    legacy, procurement, grid_efficiency, prospector, scoring,
    sustainability, vision, analytics, retrofit,
    regulatory, nom, notifications, investment, home_retrofit,
    chat, jobs as jobs_router,
    assessments, workflows as workflows_v1, auth,
    cim as cim_router,
    datacentre, reports,
    hardware,
    teaser as teaser_router,
    dc_planner as dc_planner_router,
    eurosat as eurosat_router,
    land as land_router,
    projects as projects_router,
    finance as finance_router,
    site_design as site_design_router,
    environment as environment_router,
    land_management as land_mgmt_router,
    terrain as terrain_router,
)

_routers = [
    site.router, geeflow.router, grid.router, demand.router,
    strategy.router, market.router, legacy.router, procurement.router,
    grid_efficiency.router, prospector.router, scoring.router,
    sustainability.router, vision.router, analytics.router,
    retrofit.router, regulatory.router, nom.router,
    notifications.router, investment.router, home_retrofit.router,
    chat.router, jobs_router.router,
    assessments.router, workflows_v1.router, auth.router,
    cim_router.router,
    datacentre.router,
    reports.router,
    hardware.router,
    teaser_router.router,
    dc_planner_router.router,
    eurosat_router.router,
    land_router.router,
    projects_router.router,
    finance_router.router,
    site_design_router.router,
    environment_router.router,
    land_mgmt_router.router,
    terrain_router.router,
]

app.include_router(graph_router)

for r in _routers:
    app.include_router(r)


# ---------------------------------------------------------------------------
# Static frontend serving (production / ngrok demo)
# ---------------------------------------------------------------------------
_DIST_DIR = pathlib.Path(__file__).resolve().parent.parent / "feasi-frontend" / "dist"

if _DIST_DIR.is_dir():
    from starlette.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file_path = _DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_DIST_DIR / "index.html")
