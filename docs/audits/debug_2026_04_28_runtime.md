# Live runtime smoke test — 2026-04-28

Council agent: general-purpose (a0ea6a973d90498b7). Backend uvicorn :8000, Vite :3000.

OpenAPI advertises **984 paths**. All curls used `--max-time 10`.

## Endpoints tested (selected)

| Method | Path | Status | Time | Size | Notes |
|---|---|---|---|---|---|
| GET | `/health` | 200 | 0.14s | — | overall=healthy; pool size=1 vs config min=3 |
| GET | `/api/readiness` | 200 | 0.05s | — | overall=`degraded`; neo4j subsystem failed |
| GET | `/api/health` | **404** | 1.08s | 22b | does not exist (correct path: `/health`) |
| GET | `/openapi.json` | 200 | 1.56s | 893 KB | |
| GET | `/api/graph/topology` | **503** | 3.70s | 344b | Neo4j unavailable |
| GET | `/api/graph/stats` | **503** | 1.13s | 344b | Neo4j unavailable |
| GET | `/api/auth/me` | 401 | 0.25s | 54b | expected (no session) |
| GET | `/api/alerts/library` | 200 | 1.23s | 42 KB | |
| GET | `/grid/topology` | 200 | 0.38s | 200 KB | |
| GET | `/grid/storage-sim` | 200 | **7.86s** → 0.04s | 7.7 KB | cold-cache slow |
| GET | `/grid/agile-map` | 200 | **9.02s** → 1.68s | 2.5 KB | cold-cache slow |
| GET | `/grid/demand-map` | 200 | **>10s timeout**, 2.96s retry | 6.9 MB | huge payload |
| GET | `/api/grid/dno-intelligence` | **500** | 0.01s | 21b | unhandled exception (plain-text response) |
| GET | `/api/grid/unmapped` | **500** | 0.01s | 21b | unhandled exception |
| GET | `/api/grid/queue-summary` | 200 | **4.21s** | 2b `[]` | suspect missing index |
| GET | `/api/grid/queue-depth` | 200 | 2.67s | 42b | slow for tiny payload |
| GET | `/api/demand/forecast` | 200 | 4.70s | 31 KB | slow |
| GET | `/api/carbon/history` | 200 | 4.54s | 26 KB | slow |
| GET | `/api/grid-twin/state` | 200 | 1.25s | 62 KB | |
| GET | `/api/compliance/g99-check` | 200 | 0.01s | 1.8 KB | |
| GET | `localhost:3000/` | 200 | <0.1s | — | React shell + `<div id="root">` + `/src/main.jsx` script |

## Failures
- **All `/api/graph/*` → 503**. Body: `Neo4j unavailable: Couldn't connect to localhost:7687 ... [Errno 61] Connection refused`. Confirmed in `/api/readiness.subsystems.neo4j = {status:"failed"}`.
- **`/api/grid/dno-intelligence` → 500** plain-text. Handler `app/routers/grid.py:2261` calls `utils.dno_intelligence.all_dno_summary(pool)`. Bypasses `app/errors.api_error_handler` so the exception isn't structured. Suspected missing table or dep.
- **`/api/grid/unmapped` → 500** plain-text. Handler `app/routers/grid.py:2173` calls `utils.gridfinder_runner.detect_unmapped_grid`. Suspected import or runtime error.
- **422 on `/grid/osm/{lines,substations,towers,generators,plants}`, `/api/site/{real-context,nearest-residence}`, `/api/landowner/lookup`**. Handlers require `lat`/`lon`/`bbox`, but OpenAPI didn't mark them required — schema/handler out of sync.

## Slow endpoints (>2s)
- `/grid/agile-map` 9.02s cold / 1.68s warm
- `/grid/storage-sim` 7.86s cold / 0.04s warm
- `/api/demand/forecast` 4.70s consistent
- `/api/carbon/history` 4.54s consistent
- `/api/grid/queue-summary` 4.21s for `[]` (DB-scan smell)
- `/grid/live` 3.75s
- `/api/graph/topology` 3.70s (Neo4j retry timeout)
- `/grid/demand-map` >10s on first hit (6.9 MB GeoJSON)
- `/api/grid/queue-depth` 2.67s for 42b
- `/grid/context` 2.37s
- `/grid/stability` 2.15s

## Health endpoint
- `/health` works. `/api/readiness` works.
- `/api/health`, `/api/healthz`, `/api/status`, `/api/ready` all 404. If any frontend code expects `/api/health`, it silently fails.
- Pool oddity: `/health.checks.pool.size = 1` vs configured `min=3` (`app/main.py:64`). Suspected idle-shrink.

## Frontend serve
Healthy. `localhost:3000/` returns HTML with `<div id="root"></div>` + `<script type="module" src="/src/main.jsx">` + Vite HMR client. Title: `Princeps — AI Grid Intelligence`.

## Top 5 user-facing breakages (priority)
1. **Neo4j down → every `/api/graph/*` returns 503**. Topology view, hierarchy walks, search, paths all break. Either start Neo4j on `:7687` or hide graph features until it's up.
2. **`/api/grid/dno-intelligence` plain-text 500**. DNO pre-app intelligence panel broken. Need server log to diagnose.
3. **`/api/grid/unmapped` plain-text 500**. Gridfinder/unmapped-asset feature broken.
4. **`/grid/demand-map` busts 10s budget on cold hit (6.9 MB GeoJSON)**. Map UI spinner-stalls. Needs paging/tile-cutting.
5. **`/api/grid/queue-summary` 4.2s for empty `[]`**. Missing index on queue table; same DB-scan smell on `/api/grid/queue-depth`. Inflates dashboard load.

Secondary: pool size shrunk to 1 vs `min=3`; `/grid/osm/*` spec/handler mismatch.
