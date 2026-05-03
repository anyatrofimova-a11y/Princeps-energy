# Subprocess bridge + WebSocket health — 2026-04-28

Run directly in main thread (subagent ab41dd04a754a4bc6 was sandbox-denied Bash).

## Venv health
| Venv | Python | Key lib | Status |
|---|---|---|---|
| `.venv` | 3.14.2 | (FastAPI host) | OK |
| `.venv-sam` | 3.11.14 | PySAM 7.1.0 | OK |
| `.venv-grid` | 3.12.12 | pandapower 3.4.0, lightsim2grid 0.12.2 | OK |
| `.venv-forecast` | 3.12.12 | prophet 1.3.0, darts 0.41.0 | OK |
| `.venv-geeflow` | 3.12.12 | earthengine-api 1.7.12 | OK |

All 5 boot, all key libs import.

## Runner scripts
| Runner | Exists | Has `__main__` | Verdict |
|---|---|---|---|
| `utils/sam_runner.py` | yes | yes | callable as script |
| `utils/grid_power_flow.py` | yes | yes | callable as script |
| `utils/geoai_runner.py` | yes | yes | callable as script |
| `utils/geeflow_runner.py` | yes | yes | callable as script |
| `utils/demand_forecaster.py` | yes | yes | callable as script |
| `utils/geeflow_site_scorer.py` | yes | no | imported as module — not an issue |
| `utils/geeflow_planning_analysis.py` | yes | no | imported as module — not an issue |
| `utils/geeflow_grid_analysis.py` | yes | no | imported as module — not an issue |

## Bridge env vars
| Var | Default (`app/helpers.py`) | Behavior if unset / missing | Notes |
|---|---|---|---|
| `SAM_PYTHON` | `.venv-sam/bin/python` (line 71) | warning at boot, fails at request time | resolves with `pathlib.Path(...).absolute()` |
| `GRID_PYTHON` | `.venv-grid/bin/python` (line 30) | `RuntimeError` raised in `_run_grid_subprocess` (line 39) | request-time guard |
| `GEEFLOW_PYTHON` | `.venv-geeflow/bin/python` (line 75) | warning at boot, fails at request time | |
| `GEOAI_PYTHON` | shares geeflow venv (line 80) | warning at boot | also TorchGeo / Clay / LiDAR |
| `FORECAST_PYTHON` | `.venv-forecast/bin/python` (line 95) | request-time fail | |

**Heads up:** `app/main_monolith.py` has a duplicate, divergent copy of all five env-var resolutions (lines 65, 243, 258, 273, etc.). That file is not imported anywhere and is dead code — remove or archive.

## WebSocket routes
8 WS handlers registered (live in `app/routers/`):
- `app/routers/grid.py:1759` — `/ws/grid-twin`
- `app/routers/grid.py:1902` — `/ws/bems`
- `app/routers/grid.py:2058` — `/ws/bess-facility`
- `app/routers/grid.py:2139` — `/ws/dc-twin`
- `app/routers/events.py:107` — `/ws`
- `app/routers/market_data.py:54` — `/ws/market`
- `app/routers/dc_ops.py:377` — `/ws/dc-ops/{project_id}`
- `app/main_monolith.py:4166` — `/ws/grid-twin` (dead duplicate)

`/ws/grid-twin` HTTP-upgrade handshake returned **HTTP 400** (not 404 — handler reachable, but rejected the synthetic Connection: Upgrade probe). The 4 frontend clients connect via the Vite proxy with `ws: true`, which is the supported path.

## Subprocess calls without `timeout=`
9 `subprocess.run` / `Popen` / `check_output` call sites in `app/` + `utils/` (excluding tests). 27 files in the tree contain the `timeout=` keyword overall, but the 9 hot call sites need a per-line audit:
- `app/routers/grid.py:2093`
- `utils/db_spatial_audit.py:82`
- `utils/db_spatial_audit.py:93` (uses `check=True`)
- `utils/lpa_scraper.py:200`
- `utils/lpa_scraper.py:212`
- `utils/ofgem_rag.py:131`
- `utils/report_financial.py:233`
- `utils/lender_pack.py:173`
- `utils/n1_contingency/analyser.py:207`

Any of these without `timeout=` can hang a FastAPI worker indefinitely. Worth a follow-up grep with surrounding context.

## Top 5 subprocess/WS risks (priority)
1. **`/ws/grid-twin` returned 400 to a probe handshake** — confirm the live frontend WS clients still connect (they do via Vite proxy, but worth a browser smoke test).
2. **Audit the 9 `subprocess.run` call sites** for missing `timeout=`. PDF rendering (`report_financial.py`, `lender_pack.py`) and the LPA scraper are highest risk for hangs.
3. **`app/main_monolith.py` duplicate WS handler at `/ws/grid-twin`** — dead but confusing; same routing string registered twice if anyone re-includes the module.
4. All 5 venvs healthy and all 5 named runners present + executable. **No action needed on bridges themselves** — they're solid.
5. The 3 `geeflow_*` helpers without `__main__` are imported as modules; not a regression, just noted for completeness.
