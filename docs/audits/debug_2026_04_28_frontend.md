# Frontend wiring audit — 2026-04-28

Council agent: Explore (a47bb3708d74a9f0d). Source: `feasi-frontend/`.

## Dead imports
None. `SiteDesigner3D` and `UnifiedSiteDesigner` references fully removed; the only mention is a documentation comment in `feasi-frontend/src/components/workspace/DesignCanvas.jsx` noting it replaces the deleted designer.

## API mismatches
Six card components on the workspace canvas call endpoints that don't exist on the backend (`feasi-frontend/src/canvas/cards/`):

| Frontend call | Expected backend | Status | File:line |
|---|---|---|---|
| `GET /api/finance/project?site_id=` | `POST /api/finance/project-finance` | wrong path + method | `FinanceCard.jsx:40` |
| `GET /api/environment/assessment?site_id=` | `/api/environment/assess` or `/api/environment/constraints` | path variant | `EnvironmentCard.jsx:37` |
| `GET /api/planning/ml/predict?site_id=` | `POST /api/planning/predict` | wrong path + method | `PlanningCard.jsx:34` |
| `GET /api/yield/sam?site_id=` | no matching endpoint | missing | `YieldCard.jsx:32` |
| `GET /api/land/parcel?id=` | no `/api/land/parcel` (there is `/api/land/parcels` for bbox) | missing | `LandCard.jsx:28` |
| `GET /api/grid/connection/assessment?site_id=` | no matching grid connection assessment | missing | `GridCard.jsx:45` |

All six fail silently or fall back to mock data.

## Vite proxy
Healthy. `feasi-frontend/vite.config.js:30-79` proxies `/api/*` and `/ws/*` to `http://localhost:8000`, `ws: true` set on line 70.

## Undefined env vars
Used in code but absent from `feasi-frontend/.env.example`:
- `VITE_ORDNANCE_API_KEY` — `feasi-frontend/src/twin/layers/os_buildings.js:25` (with fallback to `VITE_OS_API_KEY`)
- `VITE_OS_API_KEY` — same file
- `VITE_MAPLIBRE_STYLE` — `feasi-frontend/src/canvas/UnifiedCanvas.jsx:146`
- `VITE_SUBSTRATE_LIDAR_TILES` — `feasi-frontend/src/components/map/SubstrateLayers.js:269`

## Unreachable routes
None. Routes for deleted designers cleanly removed; all 20+ twin/dashboard overlays reachable via CommandPalette / AppShell handlers / workspace tabs.

## WebSocket health
All 4 frontend WS clients have a backend handler:
- `/ws/grid-twin` — `GridTwin.jsx`, `GridTwinOverlay.jsx`, `GridTwinCesium.jsx` → `app/routers/grid.py:1759`
- `/ws/bems` — `BEMSDigitalTwin.jsx` → `app/routers/grid.py:1902`
- `/ws/bess-facility` — `BESSFacilityTwin.jsx` → `app/routers/grid.py:2058`
- `/ws/dc-twin` — `DataCentreTwin.jsx` → `app/routers/grid.py:2139`

## Top 5 fixes (priority)
1. `FinanceCard.jsx:40` — change to `POST /api/finance/project-finance` with proper body. Currently shows mock data only.
2. `PlanningCard.jsx:34` — change to `POST /api/planning/predict` with `{lat, lon, mw}`. Planning risk always fails today.
3. Add 4 missing `VITE_*` vars to `feasi-frontend/.env.example` with documented fallbacks.
4. `YieldCard.jsx:32` — likely should call `/api/design/yield-curtailment`. Solar yield card doesn't render.
5. `LandCard.jsx:28` — confirm whether `/api/land/parcels` (bbox) is the intended call. Land value card fails.
