# Princeps Digital Twin — 100x Upgrade Spec

**Author:** COUNCIL-3 (read-only)
**Date:** 2026-04-19
**Consumers:** BOT-CC, BOT-DD, BOT-EE, BOT-FF, BOT-GG, BOT-LL (execution swarm), BOT-HH (perf pass)
**Related:** `docs/audits/grid_twin_redesign_spec.md` (COUNCIL-2, chrome/layout), `docs/audits/twin_layer_registry_contract.md` (tight interface)

This spec is executable-by-bots. Every proposed endpoint is marked **[EXISTS]** or **[PROPOSED]**. No swarm bot may edit `GridTwin.jsx` / `GridTwinCesium.jsx` directly — ship a layer module into `feasi-frontend/src/components/twin/layers/` and it is auto-mounted.

---

## 1. Current-state audit — `GridTwin.jsx` (Mapbox + deck.gl)

Source: `feasi-frontend/src/components/GridTwin.jsx` (695 lines). Cesium twin: `GridTwinCesium.jsx` (parallel full-screen variant; this spec governs both via a shared layer registry).

### Layers (current inventory — 8)

| # | Layer id | Type | Props of note | Data source |
|---|----------|------|---------------|-------------|
| 1 | `gt-substation-columns` | `ColumnLayer` | `radius 2500m`, elevation=demand*10, fill=utilisationColor | `gridState.substations` |
| 2 | `gt-capacity-rings` | `ScatterplotLayer` | stroked, radius=3000+capacity*3, colour by voltage | `gridState.substations` |
| 3 | `gt-power-arcs` | `ArcLayer` | width=flow/40, height=loading/200, red if congested | `gridState.lines` |
| 4 | `gt-flow-particles` (GPU) | `createParticleLayer` | 8ms frame tick, animPhase ∈ [0,1) | `gridState.lines` |
| 5 | `gt-flow-particles` (fallback) | `ArcLayer` dashed | dash [4,12], only when particles disabled | `gridState.lines` |
| 6 | `gt-substation-labels` | `TextLayer` | IBM Plex Mono, billboard, pixelOffset [0,-20] | `gridState.substations` |
| 7 | `gt-google-3d-tiles` | `Tile3DLayer` | Optional, opacity 0.9, `VITE_GOOGLE_MAPS_KEY` gate | Google Photorealistic 3D |
| 8 | `gt-constraint-heat` / `gt-constraint-pulse` | Mapbox native fill + line | heat ramp 0→0.3→0.6→1.0 | `/api/grid/constraints?hours_ahead=48` |

### Mapbox base chrome
- Style: `mapbox://styles/mapbox/dark-v11`
- Terrain source `mapbox-dem` (raster-dem, exaggeration 2.5)
- Sky atmosphere layer
- `3d-buildings` fill-extrusion from `composite` source, `building` source-layer, opacity 0.6 — **generic Mapbox buildings, NOT OS MasterMap**

### Backend endpoints (consumed today)

| Method | Path | Status |
|--------|------|--------|
| GET | `/api/grid-twin/state?limit=80` | **[EXISTS]** `app/routers/grid.py:1185` |
| WS  | `/ws/grid-twin` (5s push) | **[EXISTS]** `app/routers/grid.py:1502` |
| GET | `/api/grid-twin/scenario/{name}?year=` | **[EXISTS]** `app/routers/grid.py:1523` |
| GET | `/api/grid/constraints?hours_ahead=48` | **[EXISTS]** `app/routers/grid.py:994` |

### Supporting state / UI controls
- `liveMode`, `scenario` (5 FES pathways), `scenarioYear` (2024-2050 slider)
- `twinLayers` = {substations, lines, labels, generators}
- `particlesEnabled`, `constraintHeatmap`, `google3d`, `choreographyActive`
- Inspector drawer: substation (demand / gen / capacity / headroom / util bar) or line (flow / loading / congested flag)
- Legend: voltage colours (400/275/132/66/33/11 kV), utilisation bands
- GridCameraChoreography component for AI flythrough

### Assess-tab embed — the "black-box"
`feasi-frontend/src/components/workspace/GridTab.jsx` L46-54 renders:
```
<div className="gt-placeholder">
  <div className="gt-placeholder-text">Grid twin embed
    <div className="gt-placeholder-sub">Click "Pop out" for full-screen Cesium view</div>
```
This is the placeholder the user flagged. When `embedTwin=true` it mounts `GridTwinCesium` with no project context filter. **BOT-FF owns replacing this with a project-centred embed** (see §4b).

---

## 2. UK Precision Data Source Map

Every source below is **free** unless marked otherwise. Licence defaults to **OGL v3** (Open Government Licence). All URLs confirmed as of April 2026.

| # | Upgrade | Source | URL | Format | Licence | Owner bot |
|---|---------|--------|-----|--------|---------|-----------|
| 1 | Building footprints + heights (urban) | **OS Open Zoomstack** | https://www.ordnancesurvey.co.uk/products/os-open-zoomstack | Vector tiles / GeoPackage | OGL v3 | BOT-DD |
| 2 | Premium building footprints (PSGA) | **OS MasterMap Topography** | https://www.ordnancesurvey.co.uk/products/os-mastermap-topography-layer-building-height-attribute | GML / GeoPackage | PSGA free (public sector) / commercial | BOT-DD |
| 3 | 1m bare-earth terrain | **Environment Agency LIDAR Composite DTM 1m** | https://environment.data.gov.uk/dataset/f0db0249-f17b-4036-9e65-309148c97ce4 | GeoTIFF per 1km OS square | OGL v3 | BOT-EE (wraps existing `utils/lidar_uk.py`) |
| 4 | 1m surface model (tree+building canopy) | **EA LIDAR Composite DSM 1m** | https://environment.data.gov.uk/dataset/fba12e80-519f-4be2-806f-41be9e26ab96 | GeoTIFF per 1km OS square | OGL v3 | BOT-EE |
| 5 | Roads / greenspace / rail / names | **OS Open Roads / Open Greenspace / Open Names** | https://osdatahub.os.uk/downloads/open | GeoPackage / Vector tiles | OGL v3 | BOT-DD |
| 6 | Woodland + tree canopy | **National Forest Inventory (Forest Research)** | https://www.forestresearch.gov.uk/tools-and-resources/national-forest-inventory/ | Shapefile / GeoPackage | OGL v3 | BOT-EE |
| 7 | Power towers / lines / plants (global) | **OSM Overpass** `power=tower/line/substation/plant` | https://overpass-api.de/api/interpreter | JSON | ODbL | Existing (`grid_data_ingester.py`) |
| 8 | Renewables planning register | **REPD** (DESNZ) | https://www.data.gov.uk/dataset/a5b0ed13-c960-49ce-b1f6-3a6bbe0db1b7 | CSV quarterly | OGL v3 | Existing ingester |
| 9 | NSIPs | **planning.data.gov.uk** | https://www.planning.data.gov.uk/ | GeoJSON / API | OGL v3 | Existing (via BOT-G) |
| 10 | Connection queue | **NESO ECR / TEC register** | https://www.neso.energy/data-portal/tec-register | CSV | OGL v3 | Existing (`grid_ecr` table) |
| 11 | LPAs / parishes / designations | **planning.data.gov.uk datasets** | https://www.planning.data.gov.uk/dataset/ | GeoJSON | OGL v3 | Existing |
| 12 | HMLR ownership (INSPIRE + CCOD) | **HM Land Registry** | https://use-land-property-data.service.gov.uk/datasets/inspire | Shapefile / CSV monthly | OGL v3 (free for non-personal CCOD) | Existing (`hmlr_inspire_parcels`) |
| 13 | Irradiance / wind / reanalysis | **ERA5 / ERA5-Land (CDS)** | https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-land | NetCDF / GRIB | Copernicus licence (free, attribution) | Existing (`.venv-geeflow`) |
| 14 | Near-real-time carbon | **NESO Carbon Intensity API** | https://api.carbonintensity.org.uk/ | JSON | CC-BY 4.0 | Existing (`live_grid_status.py`) |
| 15 | Live demand / gen mix | **Elexon BMRS Insights v1** | https://data.elexon.co.uk/bmrs/api/v1 | JSON / CSV | No auth, free | Existing |
| 16 | Weather forecast | **Met Office DataHub (Global Spot)** | https://datahub.metoffice.gov.uk/ | JSON | Free tier with API key | BOT-GG **[PROPOSED]** |
| 17 | Gas network | **Xoserve Gas Data Portal (NGT)** | https://data.nationalgas.com/ | CSV / JSON | Free with registration | BOT-GG **[PROPOSED — low priority]** |
| 18 | AddressBase (addressable nodes) | **OS AddressBase Premium** | https://osdatahub.os.uk/ | Commercial — ~£GBP/annum | Commercial | Note: **skip unless customer-funded** |
| 19 | Flood risk | **EA Risk of Flooding from Rivers & Sea** | https://environment.data.gov.uk/dataset/ef8f4648-b8ce-4ada-81ca-35ae9247c5ed | Shapefile / WMS | OGL v3 | Existing (`esa/flood-risk`) |
| 20 | Agricultural Land Classification | **Natural England ALC** | https://naturalengland-defra.opendata.arcgis.com/ | GeoJSON / WMS | OGL v3 | Existing (`alc_grades` table) |

Attribution requirement (put in twin footer, BOT-LL): *"Contains OS data © Crown copyright and database right 2026 · Contains data from Ordnance Survey, Environment Agency, HM Land Registry, Elexon, NESO, Forest Research — licensed under OGL v3 · © OpenStreetMap contributors, ODbL · ERA5 data from Copernicus Climate Change Service."*

---

## 3. Plugin Layer Registry — the one rule

**Swarm bots do NOT edit `GridTwin.jsx` or `GridTwinCesium.jsx`.** They add a single file:

```
feasi-frontend/src/components/twin/layers/<bot>_<feature>.jsx
```

Each file is a **layer module** matching the contract in `twin_layer_registry_contract.md`. A central `feasi-frontend/src/components/twin/layers/index.js` uses Vite `import.meta.glob` to auto-register every module — GridTwin picks them up on next render. No merge conflicts, no coordination.

Minimum module shape:
```js
export default {
  id: "ff_parcel_ownership",          // unique, kebab/snake — bot prefix recommended
  menuLabel: "Ownership (HMLR)",      // shown in left-rail layer toggle
  defaultVisible: false,
  renderer: "deckgl" | "mapbox",      // which engine
  requiresSite: false,                // true = only mounts in Assess embed
  dataHook: ({ bbox, siteId, scenario, year }) => ({ data, loading, error }),
  layerFactory: (data, ctx) => new GeoJsonLayer({...}) | [mapboxLayerSpec],
  inspector: (feature) => <JSX/>,     // optional right-drawer section
  kpis: (data) => [ kpi, ... ],       // optional — pushed into agentic KPI rail
  attribution: "HMLR INSPIRE · OGL v3",
};
```

Example files to ship (one per bot, parallel):
- `cc_os_mastermap_buildings.jsx` (layer #1, #2)
- `dd_os_open_roads_greenspace.jsx` (layer #5)
- `ee_ea_lidar_terrain.jsx` (layers #3, #4 — reuses `utils/lidar_uk.py` backend)
- `ff_parcel_ownership.jsx` (layer #12)
- `gg_met_office_weather.jsx` (layer #16)
- `ll_nfi_woodland.jsx` (layer #6)

The full interface (Python KPI side + JS module side) is in `twin_layer_registry_contract.md`.

---

## 4. Twin Slots — two mount sites, one registry

### 4a. Full-screen route `/twin` (BOT-LL)
- Top-level route outside AppShell chrome (as recommended in `grid_twin_redesign_spec.md` §1).
- Mounts **all** registered layers. Layer toggles in the left rail (`gt2-rail` pattern).
- Default visible: substations, lines, labels, terrain, MasterMap buildings.
- All FES scenarios + year slider remain.

### 4b. Assess-tab embed (BOT-FF owns — replaces `gt-placeholder`)
`GridTab.jsx` currently shows a black box. Replace with:

```
<TwinEmbed
  site={project.site}                 // geom + centroid
  filter={{ requiresSite: true, withinKm: 5 }}
  showAgenticKpiRail                  // right-edge 280px rail
  scenarios={["baseline", "CT"]}
  onParcelClick={(p) => openParcelDrawer(p)}  // §6
/>
```

- **Project-centred camera:** fly to `project.site.centroid` at pitch 55°, zoom 16.
- **Layer filter:** only layers with `requiresSite !== false` OR intersecting site bbox.
- **Agentic KPI rail** (§5): right edge, always visible, live values.
- **Parcel drawer** (§6): click any HMLR polygon → 10-section drawer.
- **Overlay toggles:** same registry, shown as a compact chip row above the canvas.
- **No separate chrome** — use TwinEmbed component, reuse layer registry.

Both mount sites share the same registry. Only difference: embed passes `siteId` into `dataHook`; full-screen passes `bbox` from camera.

---

## 5. Agentic KPI contract

Each KPI is a single JSON object. Full shape:

```ts
type KPI = {
  id: string;                               // e.g. "grid_viability"
  label: string;                            // "Grid Viability"
  value: number | string;
  unit?: string;                            // "%", "£M", "ha", "MW"
  verdict: "green" | "amber" | "red";
  source_endpoint: string;                  // where the value came from
  explanation: string;                      // ≤140 chars, shown on hover / tap
  last_updated: string;                     // ISO8601
  confidence?: number;                      // 0-1, optional
}
```

### Minimum set (all must render in the Assess embed rail)

| id | label | unit | source_endpoint | Status |
|----|-------|------|-----------------|--------|
| `grid_viability` | Grid Viability | 0-100 | `/api/grid/assess` | **[EXISTS]** |
| `planning_likelihood` | Planning Likelihood | % | `/api/planning/predict-repd` | **[EXISTS]** |
| `buildable_ha` | Buildable Area | ha | `/api/analysis/buildable-area` | **[EXISTS]** (`app/analysis/buildable.py`) |
| `connection_cost_p50_gbp_m` | Connection Cost P50 | £M | `/api/grid/connection_cost` | **[EXISTS]** |
| `queue_position` | ECR Queue Position | — | `/api/grid/queue` | **[EXISTS]** |
| `verdict` | Verdict | GO/CAUTION/NO-GO | `/api/twin/project-kpis` | **[PROPOSED — BOT-GG]** |
| `revenue_p50_gbp_m` | Revenue P50 | £M/yr | `/api/finance/project-finance` | **[EXISTS]** |
| `compliance_status` | Compliance | G99/CDM/BNG | `/api/compliance/g99-check` | **[EXISTS]** |

BOT-GG ships a **new aggregator** endpoint `/api/twin/project-kpis/{project_id}` **[PROPOSED]** that calls the above in parallel and returns `{kpis: KPI[]}`. The frontend calls only this one endpoint; it SWR-refreshes every 30s.

Verdict rollup rule (must match existing `app/workflows.py:101`): any red → red, any amber → amber, else green. Mapped to GO/CAUTION/NO-GO in UI copy.

---

## 6. Parcel Drawer contract — 10 sections (BOT-FF)

When the user clicks an HMLR polygon (`ff_parcel_ownership.jsx`), open a right-edge drawer (≤480px wide). Same component is re-used by the full-screen twin and the Assess embed. Each section has its own provenance badge.

```ts
type ParcelDrawerData = {
  parcel: { inspire_id: string; area_ha: number; centroid: [lon, lat]; geom_bbox: [number,number,number,number] };
  sections: {
    identity:      { title_number?, uprn[], postcode, what3words?, provenance };
    ownership:    { freehold_name, leasehold_name?, ccod_company_no?, last_transfer_price_gbp?, last_transfer_date?, provenance };
    planning:     { lpa, recent_apps: [], repd_nearby: [], precedent_outcome, likelihood_pct, provenance };
    environment: { alc_grade, flood_risk_band, sssi_within_m?, aonb_within_m?, peat_depth?, provenance };
    grid:         { nearest_substation_id, distance_km, voltage_kv, headroom_mw, ecr_status?, provenance };
    access:       { nearest_a_road_m, nearest_motorway_km, byway_within_parcel: bool, provenance };
    utilities:   { gas_pipeline_within_m?, water_main_within_m?, telecoms_mast_within_m?, provenance };
    topography:  { mean_slope_pct, mean_elev_m, lidar_coverage: "1m"|"2m"|"none", provenance };
    designations: { conservation_area, listed_building_within_m?, tpo_within_parcel, green_belt, nfi_woodland_pct, provenance };
    market:      { comparable_sales: [], gbp_per_ha_median?, time_on_market_median_days?, provenance };
  };
};
```

`provenance` on every section: `{ source: string; source_url: string; fetched_at: ISO; licence: "OGL v3" | "ODbL" | ... }`. Badge renders inline as `HMLR · OGL v3 · 2026-04-02`.

Data flow: one endpoint `/api/parcels/{inspire_id}/drawer` **[PROPOSED — BOT-FF]** returns the full shape. Section-level lazy loading permitted (emit `{section: loading: true}` if slow).

---

## 7. Performance notes (for BOT-HH)

Current twin is fine at national zoom, degrades when LIDAR + MasterMap land. Strategy:

1. **LOD by camera zoom.** Each layer module declares `minZoom`, `maxZoom` — registry filters before passing to deck. Suggested:
   - `< 8`: substations (columns), arcs, labels, terrain. No buildings, no parcels, no LIDAR.
   - `8-12`: + REPD/NSIP pins, NFI woodland, flood-risk tiles.
   - `12-15`: + OS Open Zoomstack buildings, OSM power towers.
   - `> 15`: + MasterMap building heights, HMLR parcels, EA LIDAR 1m DSM shade.
2. **Viewport bbox culling.** `dataHook({bbox})` returns only features in viewport + 10% margin. Backend endpoints MUST accept `bbox=minx,miny,maxx,maxy` (note: BOT-GG must add this to `/api/twin/project-kpis` query, and `app/routers/land.py` must gain bbox filter — **[PROPOSED]**).
3. **Tile cache.** LIDAR DTM/DSM served as XYZ tiles via new `/api/tiles/lidar/{z}/{x}/{y}.png` **[PROPOSED — BOT-EE]**; wrap `utils/lidar_uk.py` cache. HTTP cache 24h. Precompute hillshade in backend.
4. **Offscreen rendering for heat rollups.** Constraint heatmap: render to offscreen canvas, update on scenario/year change only — not every frame.
5. **Instancing for towers.** OSM `power=tower` is ~350k points nationally — use `ScatterplotLayer` with GPU instancing (single draw call), not GeoJson.
6. **WebSocket diff, not full state.** Change `/ws/grid-twin` to emit JSON-patch (RFC 6902) after first full snapshot. **[PROPOSED — BOT-GG]**. Saves ~95% payload.
7. **Parcel clustering.** At zoom < 14, cluster HMLR parcels by H3 level 9, render as supercluster. Below 14, render actual polygons.
8. **deck.gl `updateTriggers` hygiene.** Current code uses `gridState.timestamp` — keep; it is correct. New layers must do the same (see contract).
9. **Suspense boundaries per layer.** Each layer's `dataHook` is its own Suspense boundary so one slow fetch doesn't freeze the twin.
10. **Budget:** 60fps at zoom 15 with 8 layers visible on M1 MacBook. BOT-HH to verify with Chrome perf trace; target JS main-thread < 10ms per frame.

---

## 8. Delivery checklist (for swarm)

- [ ] BOT-CC: `cc_os_mastermap_buildings.jsx` + backend proxy `/api/tiles/mastermap/{z}/{x}/{y}` **[PROPOSED]**
- [ ] BOT-DD: `dd_os_open_roads_greenspace.jsx` (Zoomstack vector tiles)
- [ ] BOT-EE: `ee_ea_lidar_terrain.jsx` + `/api/tiles/lidar/{z}/{x}/{y}` **[PROPOSED]**
- [ ] BOT-FF: `ff_parcel_ownership.jsx` + `/api/parcels/{id}/drawer` **[PROPOSED]** + `ParcelDrawer` component + replace `gt-placeholder` in `GridTab.jsx` with `TwinEmbed`
- [ ] BOT-GG: `/api/twin/project-kpis/{project_id}` **[PROPOSED]**, WS diff patches **[PROPOSED]**, Met Office DataHub adapter
- [ ] BOT-LL: `ll_nfi_woodland.jsx`, attribution footer, `/twin` full-screen route extraction
- [ ] BOT-HH (later): perf pass per §7

**Constraint — no bot may edit `GridTwin.jsx`, `GridTwinCesium.jsx`, or each other's layer files.** All additions land via the registry in `feasi-frontend/src/components/twin/layers/`.

**Word count: ~1,950**
