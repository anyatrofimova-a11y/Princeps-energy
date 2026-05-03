# Backend route + boot audit — 2026-04-28

Council agent: Explore (a78d3f3db7d990a85). Source: `app/`.

## Routers status
- `app/routers/` contains **107 router files**.
- `app/main.py` declares **83 in `_ROUTER_MODULES`** plus 3 manual includes (`graph_router`, `auth_login` at `/api/auth`, `trust_center`).
- **2 routers on disk but not declared** (will silently log a warning at boot, won't crash): `engineering`, `heritage_nature`. If their endpoints are referenced anywhere, those callers 404.

## Import problems
None at module-load time. New `from app.startup_pulse_seed import run_pulse_seed` (added by the uncommitted Pulse seed diff) resolves — `app/startup_pulse_seed.py:44` declares `async def run_pulse_seed(pool)` matching the call signature.

## `app/main_monolith.py` is dead code
File exists (~7000 lines, copied env-var resolution + ~17 routes including a duplicate `/ws/grid-twin` and `/health`). **No file in `app/` imports it.** Risk: confusing for new maintainers, drifts from `app/main.py`. Recommend deleting or moving to `archive/`.

## Background task risk
Most tasks are fire-and-forget via `_safe_bg(...)`. Risks:

| Task | Gate env | Behavior if unset | Risk |
|---|---|---|---|
| `grid_gsp_seed` | none | runs (`app/startup.py:110`) | **HIGH — uses blocking `await`, not `asyncio.create_task()`. If `seed_real_substations` hangs, all later tasks are delayed and 502 risk on cold start.** |
| `bulk_import_repd` | none | runs | MEDIUM — waits 3 min for REPD scrape (`startup.py:436-447`), wrapped safe |
| `nightly_refresh_loop` | none | infinite loop spawns at line 137 | MEDIUM |
| `pulse_seed` | `PULSE_SEED_ON_BOOT` | runs (default true in dev) | MEDIUM — depends on `cluster_studies` / `grid_events` schemas existing |
| `ltds_ingest` | `PRINCEPS_LTDS_INGEST_ON_STARTUP` | skipped (default off) | LOW — but reads ~100MB CIM XML when on |
| All others | `_safe_bg` wrapped, idempotent | varies | LOW |

## Migrations
18 files in `app/migrations/` (numbered 0001–0018, no gaps). No CLI runner — `app/db_setup.setup_database(pool)` integrates them via `CREATE TABLE IF NOT EXISTS`. Idempotent. Safe.

## Required env vars (boot-blocking)
Crash at import time if missing:
- `DATABASE_URL` — `app/main.py:52`
- `CLAUDE_API_KEY` — `app/main.py:54`

## Subprocess bridge env vars
All have venv defaults via `app/helpers.py`:
- `SAM_PYTHON` (default `.venv-sam/bin/python`) — line 71
- `GRID_PYTHON` (default `.venv-grid/bin/python`) — line 30; raises `RuntimeError` at request time if missing
- `GEEFLOW_PYTHON` — line 75
- `GEOAI_PYTHON` (defaults to geeflow venv) — line 80
- `FORECAST_PYTHON` — line 95

## Undocumented optional env vars
Used in code but absent from `.env.example`:
- `REDIS_URL`, `SMTP_HOST`, `SMTP_*` — required if alert delivery enabled
- `OPENAI_API_KEY` — Alerts semantic search downgrades silently to tsvector if missing
- `VITE_MAPBOX_TOKEN` (frontend), `MAPBOX_TOKEN` (backend) — split is correct but underdocumented
- `CDS_API_KEY` (`app/routers/twin_dynamic.py:192`)
- `DNO_PARSER_MODEL`, `PRINCEPS_INGESTION_JOBSTORE`
- `COMPANIES_HOUSE_API_KEY`, `SENDGRID_API_KEY`, `RESEND_API_KEY`, `SLACK_WEBHOOK_URL`, `GITHUB_TOKEN`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `PRINCEPS_SSO_ENABLED`, `PRINCEPS_ACL_STRICT`, `PRINCEPS_AGENTS_ENABLED`
- `WORKER_CONCURRENCY` (default 4), `WORKER_JOB_TIMEOUT_S` (default 1800), `AGENT_NAME`
- `BUILDER_REPO` (default `anyatrofimova-a11y/feasibly`), `DRY_RUN`
- `PRINCEPS_LTDS_DNOS`, `PRINCEPS_LINK_GRID_LINES_*`
- `JWT_SECRET` — **demo-mode safety net hides this; required for any non-demo deploy**

## Health route
Exists at `/health` (`app/main.py:165-209`), NOT `/api/health`. Returns `{status: healthy|degraded, checks, core_ready}`. Readiness at `/api/readiness` (`main.py:215-223`).

## Top 5 boot risks (priority)
1. **Blocking `await` at `startup.py:110`** for `grid_gsp_seed` — change to `asyncio.create_task()` or wrap with `asyncio.wait_for(timeout=…)`.
2. **`JWT_SECRET` undefined** — auth survives only because `PRINCEPS_DEMO_MODE=true`. Production deploy with demo off = 100% auth failure.
3. **Dead code: `app/main_monolith.py`** (~7000 lines, unimported, drifting from `main.py`). Delete or archive.
4. **Two routers (`engineering`, `heritage_nature`) on disk but not in `_ROUTER_MODULES`** — add to the list or remove the files.
5. **`.env.example` ~15 vars short** — fix the GEE name drift (`GEE_PROJECT_ID` documented, `GEE_PROJECT` consumed) and document the rest with defaults.
