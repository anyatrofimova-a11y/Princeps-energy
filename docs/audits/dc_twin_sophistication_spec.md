# DC Twin Sophistication Spec — COUNCIL-DC 2026-04-19

Status: **demo prop, not a pre-FID layout.** The screenshot (purple shell + green
cooling block hovering over Ditton Park) is produced by a 60-line deterministic
offset function that ignores the parcel polygon, every UK designation, and the
fully-built layout solver already in the repo.

-------------------------------------------------------------------------------
## 1. Root-cause — file:line

### 1.1 Why the shell floats in space (doesn't snap to buildable area)
- `feasi-frontend/src/components/DCDesignTwin.jsx:82-138` — `deriveSiteGeometry({lat, lon, itLoadMw, parcelHa})` is the entire geometry derivation. It takes a single **lat/lon centroid** (prop-driven, initial default `51.4974, -0.5683` at line 147 = hard-coded Langley). There is **no parcel polygon input**, no buildable-area fetch, no designation check. `parcelHa` is received (line 150) but used only as a number to display (line 114) — never to size or shape the building.
- `feasi-frontend/src/components/DataCentreTwin.jsx:1800-1806` — the parent only passes `lat`, `lon`, `itLoadMw`, `tier`, `redundancy`. Parcel geometry from `SiteContext`/`parcel_detail` is never forwarded.
- The "snap" action at `DCDesignTwin.jsx:762-766` snaps only to a **nearby substation** (`sub.lat + 120/M_PER_DEG_LAT`), not to a buildable envelope. Drag at lines 332-340 moves the centroid to wherever the cursor lands — including the middle of a river or SSSI.

### 1.2 Where the cooling-block position comes from
Hard-coded offset in `DCDesignTwin.jsx:94`:
```
const [coolLon, coolLat] = offsetMeters(lat, lon, 0, -(shellDepth/2 + 8 + coolingDepth/2));
```
Always due south of the shell, 8 m corridor, 35 % of shell footprint (line 90). No solver output, no constraint. Substation same pattern at line 98 (always east, +25 m gap). Fence at line 103 (always 12 m offset). Cable at line 110 (always shell-east-edge → sub-west-edge). Access road at line 107 (always 60 m NE spur).

### 1.3 Is `utils/dc_planner/layout_solver.py` being called?
**No.** The solver (485 lines, BS 9991 fire separation, CPNI 10 m fence, 5 m grid search, fire-appliance perimeter road, anchor-point placement around a highway bearing, default 6-component kit) is fully built but **orphaned**:

```
$ grep -r "solve_layout\|from utils.dc_planner.layout_solver" --include="*.py"
utils/dc_planner/layout_solver.py:105:def solve_layout(
```
Only the function definition matches. Zero call sites. No router exposes it — `app/routers/dc_planner.py` only wires `plan_facility` + `simulate_telemetry`, not `solve_layout`. Frontend `api.js` has no `/api/dc/layout` endpoint (lines 1082-1088 are the old `dc_layout` template engine, not the solver).

### 1.4 Real-site constraints respected in the twin
Grep of `DCDesignTwin.jsx` for `flood_zone|SSSI|AONB|ALC|setback|designation|red_line`: **0 matches.** None are respected.

The platform has the data:
- `app/connectors/designations/{flood_zones,alc_grade,sssi,aonb}.py` — connectors
- `app/analysis/buildable_area.py` — async `buildable_area(parcel, …)` subtracts AONB/SSSI/NNR/SAC/SPA/Ramsar/FZ2/FZ3/ALC 1-2
- `utils/dc_constraint_overlay.py` — hard exclusions list: sssi, sac, spa, ramsar, aonb, green_belt, alc_12; soft penalties: flood_surface_water, conservation_area, listed_building, residential_proximity, ancient_woodland
- `migrations/2026_04_19_designations.sql` — tables seeded

DCDesignTwin consumes **none of them**. The building can be dropped inside Flood Zone 3 or an SSSI and the twin renders it in purple as if it were buildable.

-------------------------------------------------------------------------------
## 2. What a real developer's pre-FID twin looks like (the bar)

Reference: Stack Infrastructure LHR pre-FID, Equinix LD11, Digital Realty Crox­ley packs; CDM/BS 9991/BS 7671/ENA G99/P28 as sizing standards.

A 40 MW IT-load campus should render ALL of the following on the parcel:

**Buildings / yards (8-12 objects, not 2):**
- **Data hall shell** subdivided into halls (e.g. 4 × 10 MW halls = 4 internal partitions visible)
- **MV switchrooms** — one flanking each hall long-side (2-4 boxes, 12×8 m each)
- **LV plant rooms** — integrated into shell or separate 15×10 m rooms
- **Genset yard** — for 40 MW N+1 that's 8-9 × 2.5-3 MW standby gensets (Cat 3516, Rolls-Royce mtu). Footprint per unit ≈ 20×4 m with 15 m frontal clearance + 50 m residential noise buffer. Yard total ~ 75×40 m acoustically enclosed.
- **Fuel bunds** — 2 × 48 h diesel bulk tanks (≈ 240 m³ each = 12×6 m bunded pits)
- **Transformer yard** — primary TXs (2-4 × 40 MVA, 132/33 kV) on concrete plinths with firewalls, 25×15 m
- **Water treatment plant** — evap cooling make-up / closed-loop polishing, 20×15 m
- **Office / NOC** — 25×15 m, usually south-west of shell
- **Security gatehouse** — 8×6 m at the access point
- **Loading bay / delivery yard** — 30×20 m hardstand for HGVs, on the service corridor

**Utilities / context overlays:**
- **POC cable run** to the nearest adoptable DNO/NGET substation — real distance & routing (not bee-line), cost/km banding
- **Fibre route** to nearest CLS (core landing station) or BT exchange, lit/dark
- **Water intake / discharge** to the nearest main (water-stress overlay already exists in `utils/dc_water_stress.py`)
- **Gas main** if genset fuel is to be converted to HVO-compatible or later to hydrogen
- **Planning red-line boundary** (from `utils/red_line_map.py`)
- **Access / egress** tied to the mapped highway (not a 60 m spur to nowhere)

**Constraint callouts (red/amber overlays on the parcel):**
- Flood Zone 2 (amber hatch) / Flood Zone 3 (red hatch)
- SSSI, SAC, SPA, Ramsar, AONB — red polygon
- ALC Grade 1/2 — amber polygon
- Green Belt — hatch
- Ancient woodland 500 m buffer, listed buildings 500 m, residential 200 m (noise)
- CPNI 10 m fence setback line
- BS 9991 6 m fire separation lines between every building pair

**Live overlays:**
- Thermal heatmap of hall PD intensity + roof cooling plume
- PUE live calc (shell + cooling + TX + aux)
- Noise contours (LAeq 45 dB line — the planning-critical boundary)
- Sun/shadow at design date/time
- Wind rose for cooling plume direction

-------------------------------------------------------------------------------
## 3. Die / Merge / Survive

| Artefact | Verdict | Reason |
|---|---|---|
| `DCDesignTwin.jsx` shell logic lines 82-138 (`deriveSiteGeometry`) | **Die** (replace) | Hard-coded compass offsets, no parcel polygon, no constraints. Unfit for pre-FID. |
| `DCDesignTwin.jsx` Mapbox mount, terrain, 3D buildings, sky (lines 188-269) | **Survive** | Solid Mapbox/deck.gl scaffolding; the camera/orbit/snapshot/preset UI stays. |
| `DCDesignTwin.jsx` Inspector pane (lines 853-956) | **Survive, extend** | Good pattern; add new asset types (genset/TX/office/gatehouse) and constraint overlap rows. |
| `DCDesignTwin.jsx` "Snap to substation" action | **Survive** | Useful — keep, and have BOT-DU wire the real cable route. |
| `DCDesignTwin.jsx` nearbySubs grid overlay (lines 281-316, 579-638) | **Survive** | Already pulls `/grid/osm/substations`; BOT-DU to augment with distance-weighted POC routing. |
| `utils/dc_planner/layout_solver.py` | **Survive, wire** | 485 lines of correct BS 9991 code; expose via new `POST /api/dc/layout/solve` and have BOT-DS call it. |
| `utils/dc_construction/{base,cooling,shell}.py` | **Merge** into BOT-DS component kit | Partially implemented 3D primitives; consolidate with solver output. |
| `utils/dc_advanced_design.py` (701 lines), `utils/dc_design_engine.py`, `utils/dc_layout_engine.py` | **Audit, probably die** | Three overlapping "design engines" predate the solver; BOT-DS owns the rationalisation. |
| `utils/dc_constraint_overlay.py` | **Survive** | Hard/soft constraint logic ready — BOT-DP consumes in drag-loop, BOT-DU in overlay layer. |
| `app/analysis/buildable_area.py` | **Survive** | Async buildable-area computation ready. BOT-DP consumes. |
| `DCPhysicalTwin.jsx` (racks floating in white void) | **Die** when DCDesignTwin reaches parity | Already superseded per top-of-file comment at line 4 of DCDesignTwin. |
| `InsiderDCDesign.jsx` (681 lines, "design" view mode) | **Audit** | Check for overlap with BOT-DS owner files — don't clobber. |
| `DataCentreTwin.jsx` `showHeatmap` prop (line 1850) | **Merge** into BOT-DX | Currently wired only to r3f `DCScene`; BOT-DX re-wires to DCDesignTwin thermal layer. |

-------------------------------------------------------------------------------
## 4. Four-bot execution plan — owner files (non-overlapping)

All bots work from the same `DCDesignTwin.jsx` but on **disjoint code regions**. Contract: each bot edits only its named regions plus its backend files. Cross-bot integration points are listed as "read-only dependencies".

### BOT-DP — Positioning & snap-to-buildable
**Mission:** drag the shell → it snaps to the nearest valid buildable cell; red halo while over a hard constraint; amber while over soft; green when clear. The centroid cannot rest outside the parcel red-line.

**Owner files (write):**
- `feasi-frontend/src/components/DCDesignTwin.jsx` — `handleShellDragStart/Drag/DragEnd` at lines 321-345, `dragStateRef`, the drag-hint overlay at lines 722-733. Replaces the free-lat/lon drag with polygon-constrained drag.
- `app/analysis/buildable_area.py` — extend to return a **raster mask** (not just a total hectare figure) on a ~5 m grid so the frontend can snap cursor → nearest buildable cell in < 16 ms.
- `app/routers/analysis.py` (or new `app/routers/dc_design.py`) — expose `GET /api/dc/buildable-mask?parcel_id=…` returning a compact GeoJSON multipolygon of buildable cells + per-cell constraint flags.

**Read-only dependencies:** `utils/dc_constraint_overlay.py`, `app/connectors/designations/*`.

**Will not touch:** layout solver (BOT-DS), utility overlays (BOT-DU), thermal/PUE layers (BOT-DX).

### BOT-DS — Structural sophistication (internal layout)
**Mission:** replace `deriveSiteGeometry` with a call to the real layout solver. Render halls / MV rooms / genset yard / TX yard / water plant / office / security / loading bay as separate extruded polygons with distinct colours, heights, and inspector cards.

**Owner files (write):**
- `feasi-frontend/src/components/DCDesignTwin.jsx` — **replace** `deriveSiteGeometry` lines 82-138, the `C` colour map line 43-53, the three `PolygonLayer` blocks at lines 440-513, the `TextLayer` labels at lines 641-660, the `Swatch` legend at lines 770-785, and the `InspectorPane` branches at lines 858-914. All consume solver output instead of hard-coded offsets.
- `utils/dc_planner/layout_solver.py` — extend `default_components_for_load` to include genset_yard count scaling (1 × 2.5 MW per 2.5 MW IT load with N+1), TX yard, water_plant, loading_bay as first-class `ComponentSpec`s. Add `highway_bearing_deg` auto-detection from the parcel's nearest mapped road.
- `utils/dc_planner/__init__.py` — export `solve_layout` + `default_components_for_load`.
- `app/routers/dc_planner.py` — add `POST /api/dc/layout/solve` accepting `{parcel_geojson, it_load_mw, tier, redundancy, highway_bearing_deg?}` → returns the solver's `placements` / `access_road` / `cable_corridor` payload.
- `feasi-frontend/src/services/api.js` — add `dcPlanner.solveLayout(body)` binding around line 1088.

**Read-only dependencies:** buildable mask from BOT-DP (needed as solver input bounds).

**Will not touch:** drag logic (BOT-DP), POC/fibre/water overlays (BOT-DU), thermal rendering (BOT-DX).

### BOT-DU — Utilities + context overlays
**Mission:** add real POC cable run (routed, not bee-line), fibre route, water intake, access road tied to mapped highway, planning red-line polygon, flood zone overlay, designation overlays (SSSI / AONB / ALC / Green Belt / ancient woodland).

**Owner files (write):**
- `feasi-frontend/src/components/DCDesignTwin.jsx` — **new layers only** appended to `deckLayers` memo (approx after line 637). No touches to existing shell/cooling/substation layers.
- `feasi-frontend/src/components/dc/DCUtilityOverlays.jsx` — **new** component wrapping fetchers + layer builders for POC/fibre/water/red-line/designations.
- `feasi-frontend/src/components/dc/DCDesignationOverlays.jsx` — **new** PolygonLayers for SSSI/SAC/SPA/Ramsar/AONB/FZ2/FZ3/ALC, red-hatched for hard, amber for soft.
- `feasi-frontend/src/services/api.js` — add `designations.forBbox(bbox)`, `routing.cableRoute(from, to, voltage_kv)`, `utilities.fibre(bbox)`, `utilities.water(bbox)`.
- `app/routers/dc_planner.py` or new `app/routers/dc_overlays.py` — wire `GET /api/dc/overlays/designations`, `GET /api/dc/overlays/utilities`, `POST /api/dc/routing/cable`.
- `utils/dc_hyperscaler_connection.py` — extend `dual_feed_pairs` output to carry a routed `LineString` not just distance_km.

**Read-only dependencies:** `grid_substations` table, `app/connectors/designations/*`, `utils/red_line_map.py`.

**Will not touch:** building footprints (BOT-DS), drag logic (BOT-DP), heatmap (BOT-DX).

### BOT-DX — Thermal + live ops
**Mission:** the top-bar "heatmap" toggle currently does nothing visible in Design mode (`DataCentreTwin.jsx:1850` only passes `showHeatmap` to the legacy r3f `DCScene`). Wire it to a deck.gl `HeatmapLayer` over the hall roofs; add PUE live readout; noise contour; hotspot airflow overlay.

**Owner files (write):**
- `feasi-frontend/src/components/DCDesignTwin.jsx` — **new props** `showHeatmap`, `showNoise`, `showAirflow`, `pue` + a single new chip-bar row (row 3) near line 720 for toggles. New layers appended to `deckLayers` memo. No touches to shell/cooling/substation layers.
- `feasi-frontend/src/components/dc/DCThermalLayer.jsx` — **new** deck.gl HeatmapLayer builder consuming `{hall_id, inlet_temp_c, rack_kw}` from `/api/dc/telemetry`.
- `feasi-frontend/src/components/dc/DCNoiseContour.jsx` — **new** contour layer from genset / cooling-plant sound-power levels (LAeq 45 dB iso-line).
- `feasi-frontend/src/components/DataCentreTwin.jsx` — **minimum-viable edit**: forward the existing `showHeatmap` state (line 1850 region) into `<DCDesignTwin ...>` at line 1800-1806 when `viewMode === "plan"`.
- `app/routers/dc_planner.py` — extend `/api/dc/telemetry` to return per-hall thermal buckets (not just facility-wide).
- `utils/dc_heat_rejection.py` — expose `compute_noise_contour(site_polygon, gensets, cooling_units)` → iso-line GeoJSON.

**Read-only dependencies:** layout-solver output (for hall centroids + genset positions — BOT-DS produces), buildable mask (for clipping contours — BOT-DP produces).

**Will not touch:** building footprints (BOT-DS), drag logic (BOT-DP), utility overlays (BOT-DU), designation layers (BOT-DU).

-------------------------------------------------------------------------------
## 5. Sequencing

1. **BOT-DS first** on backend (`dc_planner.py` router + solver export) so the solver is callable. Can proceed in parallel with frontend mount by BOT-DS.
2. **BOT-DP** buildable mask endpoint in parallel; DCDesignTwin drag refactor lands after BOT-DS' new solver-sourced geometry replaces `deriveSiteGeometry` (avoids merge conflict on the same memo block).
3. **BOT-DU** additive-only — safe to land any time.
4. **BOT-DX** additive-only, needs BOT-DS' hall centroids for heatmap anchoring; ships last.

File-conflict guard: all four bots touch `DCDesignTwin.jsx` but each owns a disjoint region (see "Owner files" above). If two bots need to edit the same region, escalate to COUNCIL-DC for merge arbitration.
