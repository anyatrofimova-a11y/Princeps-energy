# Site Designer 100x Spec — Glint Solar parity + DC/BESS one-up

**Status**: spec draft, 2026-04-19. Prepared by COUNCIL-SD (read-only audit).
**Scope**: `/design/:projectId` route — the full-screen 3D Site Twin rendered by
`DesignPage` → `TwinLazy` → `TwinRoot`. The workspace-embedded canvas at
`DesignCanvas` (used inside `ProjectPage`) is only indirectly in-scope — see
§1.6 for why the two surfaces must converge.

**Reference artefact**: user-supplied screenshot of
`Slough Hyperscale DC, 40 MW` at `(51.5260, -0.6155)` showing Trafalgar Square
basemap, empty canvas, all four layer toggles at 100% visibility, layer rail
right, icon toolbar left, Plan/Oblique/Construction/Drone tabs top-right,
month-13 time scrubber bottom, and scale chips (Human/HGV/Megapack).

**User verbatim**: *"this is not fucntional at all, deploy swarm to assess,
100x, look at how glint solar etc. did this"*.

---

## 1. Current-state audit

### 1.1 Route → component chain

- `feasi-frontend/src/main.jsx:138-161` routes `/design/:projectId` and
  `/design` to `DesignPage`, both wrapped in `SiteProvider` +
  `WorkspaceProvider` + `Suspense`.
- `feasi-frontend/src/pages/Design/DesignPage.jsx:31-62` fetches the project
  via `GET /api/projects/{id}` (falling back to `api.projects.get`; then a
  "dev stub" with tech=bess capacity=50).
- `DesignPage.jsx:64-67` extracts:
  - `tech = project.technology ?? project.workload_type ?? 'bess'`
  - `capacity = project.capacity_mw ?? project.it_load_mw ?? 50`
  - `polygon = project.polygon_wkt ?? project.site_polygon_wkt ?? null`
- `DesignPage.jsx:96-109` renders `<TwinLazy polygon_wkt={polygon} tech={tech}
  capacity_mw={capacity} mode="oblique" />`.
- `TwinLazy.jsx:254-263` lazy-loads `TwinRoot` inside an error boundary.

### 1.2 Why the basemap shows London, not Slough

Two independent bugs compound:

**Bug A — backend never returns `polygon_wkt`.**
`app/routers/projects.py:265-296` defines `GET /api/projects/{id}` as a raw
`SELECT * FROM projects WHERE project_id = $1`, passed through `_row_to_dict`.
No `polygon_wkt` / `site_polygon_wkt` / `geometry_wkt` / `centroid_lat` columns
are synthesised. A `grep` over that file for `polygon_wkt|site_polygon` returns
**zero matches**. The row does carry scalar `lat`/`lon` (writable via PATCH at
`projects.py:330-333`), but `DesignPage` never reads them (see bug B).

**Bug B — front-end only consumes `polygon_wkt`, ignores `lat`/`lon`.**
`DesignPage.jsx:66` reads `project.polygon_wkt || project.site_polygon_wkt ||
null`. Never tries `project.lat` / `project.lon` / `project.centroid`. Passes
`polygon_wkt=null` to `TwinLazy`.

**Consequence in TwinRoot** — `TwinRoot.jsx:114` and `:372` define a London
fallback `[-0.1276, 51.5074]` used by `parsePolygonWkt()` + `centroid` memo
when no ring is given. That fallback is ~40 km ENE of Slough. The map inits at
that centroid (`TwinRoot.jsx:394: center: centroid`). `useCameraMode` at
`:425` subsequently flies to the same (London) centroid on every view-mode
change, so switching Plan/Oblique/Construction/Drone also keeps the London
origin. The basemap style is `mapbox://styles/mapbox/dark-v11`
(`TwinRoot.jsx:324`), which is the monochrome dark-grey streetmap seen in the
screenshot.

### 1.3 Why the canvas is empty despite all layers "Visible"

`TwinRoot.jsx:428-490` builds the deck.gl layers. What *should* render:

- `twin-site-boundary` PolygonLayer (needs `polygonRing`).
- `createAssetInstancedLayers` (needs `assets[]` from `computeLayout`).
- `createShadowPolygonLayer` (only when `layerVisibility.environment` is ON —
  default is `false`, see `twinStore.js:66-68`).

`computeLayout` at `TwinRoot.jsx:108-312` is deterministic and **does** emit
assets for `tech=dc` / `capacity=40` — one IT hall, ~12 gensets, hundreds of
CRACs, UPS rooms. So the parametric layout *exists*. But:

1. Because `polygonRing` is null, the site-boundary polygon **does not render
   at all** (guarded by `TwinRoot.jsx:434`).
2. The assets **do render** at lng/lat offsets from the **London fallback
   centroid** — they're placed on The Mall, not Slough. The map opens at zoom
   16 pitched 45°, and given London's density the 100 m × 60 m DC shell plus
   genset row is at the far south-east edge of the viewport (off-screen for
   the user's camera pose and masked by building layer of dark-v11).
3. The screenshot shows `month 13` on the time scrubber. The `TimeSlider`
   (`twin3d/TimeSlider.jsx`) drives the construction-phase animation; nothing
   in `AssetInstancedLayer` actually gates asset visibility on `timeMonth`, so
   that slider is cosmetic at the moment — assets are either drawn or not.
4. The right layer rail (`LayerRailRight.jsx:33-44`) lists **10 groups** —
   site / assets / electrical / civil / grid / context / constraints /
   environment / overlays / weather. The four toggles visible in the
   screenshot (Megapacks / Electrical / Civil / Grid) therefore aren't the
   full set; user has collapsed / renamed the rail or the screenshot is
   clipped. Either way `layerVisibility.assets=true` is the default.
5. Even if the renderer had geometry, the dark-v11 basemap has no aerial
   context, so a data-centre shell on an empty white polygon would still look
   like "nothing there".

### 1.4 Four top tabs Plan / Oblique / Construction / Drone

Wired to a single camera-pose hook, **not** to distinct renderers.

- `ViewModeTabs.jsx:21-26` stores one of four mode IDs in `twinStore.viewMode`.
- `useCameraMode.js:25-30` maps each to a `{pitch, bearing, zoom}` pose and
  calls `map.flyTo`. Drone adds a 0.3 deg/s bearing auto-rotate at `:79-101`.
- There is **no** Construction-mode overlay (phase painter, time-lapse shells,
  crane silhouettes, hoarding). There is **no** Drone-mode DOF / cinematic
  bloom. Construction ≠ "plan-with-tool-sheet"; Drone ≠ "oblique-with-spin".
- Keyboard Cmd/Ctrl+1..4 shortcuts work (`ViewModeTabs.jsx:32-45`).

**Verdict**: four tabs, one behaviour (camera pose). Feels like a bug.

### 1.5 Is there an equipment palette?

No. `LayerRailRight` is **visibility toggles only** — one toggle + opacity
slider per layer-group, save-as-preset button (`LayerRailRight.jsx:72+`). There
is no draggable equipment library. `ToolbarLeft.jsx:30-41` is the left icon
rail (grid / measure / annotate / section / sun / scale / snapshot / export /
reset / help) — all are *tools*, not asset palettes. `ScaleReferences.jsx`
renders the Human 1.7 m / HGV 16 m / Megapack 7 m chips.

Assets are generated deterministically by `computeLayout` (BESS/solar/DC seed
rules). User cannot place, move, rotate, delete, or swap a single megapack.
The experience is "look at the machine's answer", not "design a site".

### 1.6 Two designers, one user-expected surface

- `DesignCanvas.jsx` (1,504 LOC, `components/workspace/`) is the *real*
  designer — it has buildable-mask fetches (`/api/design/buildable-mask`),
  REPD/NSIP precedent pins, agent verdict rail, SAM yield heatmap, headroom
  governor. It mounts on `mapbox://styles/mapbox/satellite-streets-v12` with
  real site `lat`/`lon` from `useSite()`.
- `DesignPage.jsx` → `TwinRoot.jsx` is the *3D twin* — dark basemap, no
  buildable mask, no agent verdicts, no precedent, no ALC overlay, no headroom
  slider, no drag-drop.

The two were meant to converge per the Apr-2026 UI redesign
(`project_site_designer_consolidation.md`: *"DesignCanvas.jsx is now the only
designer; old SiteDesigner3D + UnifiedSiteDesigner deleted"*). That
consolidation completed the workspace-embedded surface but **left
`/design/:projectId` on the old TwinRoot path**. The screenshot shows the
surface that got orphaned.

### 1.7 Backend surface that already exists (available for wiring)

- `GET /api/design/buildable` (`routers/design.py:1066`) — positive buildable
  polygon.
- `GET /api/design/buildable-mask` (`routers/design_extras.py:94`) — negative
  constraint GeoJSON (flood / slope / ALC / protected / land-use).
- `POST /api/design/auto-layout` (`routers/design.py:85`) — auto place assets.
- `POST /api/design/optimise` (`routers/design.py:487`) — objective-driven.
- `POST /api/design/shade` (`routers/design.py:457`) — shadow + sun path.
- `POST /api/design/constraint-gate` (`routers/design.py:435`) — pass/fail.
- `POST /api/design/export` (`routers/design.py:710`) — PDF / KML / DXF.
- `GET  /api/design/yield-curtailment` (`routers/design_extras.py:272`).
- `POST /api/design/layouts` + `GET /api/design/layouts` (versioning, `:558`
  / `:590`).

**The backend is not the gap. The front-end is.**

---

## 2. Glint Solar feature-map (priority + effort)

15 features ranked by what a prospect sees in the first 60 seconds of a demo.

| # | Glint capability | Princeps today | Priority | Effort |
|---|---|---|---|---|
| 1 | Aerial / satellite basemap at 10-25 cm | `mapbox://dark-v11` (monochrome streets) | **P0 blocker** | S |
| 2 | Auto-center on project coords | Falls back to London | **P0 blocker** | S |
| 3 | Cadastral / parcel outlines auto-loaded | None on `/design/` (DesignCanvas has precedent pins only) | **P0 blocker** | M |
| 4 | Setback polygons (road, property, exclusion) | None; hinted at in `DCContextOverlays.jsx` for DC only, never called from TwinRoot | **P0 blocker** | M |
| 5 | Constraint overlays (flood, SSSI, ALC, AONB, listed) | Partial — endpoints live, not wired into TwinRoot; `DCContextOverlays` exists for DC campus surface | **P0 blocker** | M |
| 6 | Auto-layout (packing algorithm obeying buildable mask) | `computeLayout` is parametric-only — does not clip to buildable ring or respect keepouts | **P1** | L |
| 7 | Equipment palette + drag/drop | **None** | **P0 blocker** | L |
| 8 | Energy yield per layout + financial KPIs | Present in `DesignCanvas` (solarKpis / bessKpis); **absent** in `TwinRoot` | **P1** | S |
| 9 | Shading + sun-path simulation | `ShadowPolygonLayer` + `SunSlider` exist, gated behind `layerVisibility.environment=false` by default | **P1** | S |
| 10 | Pass/fail constraint panel | `/api/design/constraint-gate` exists, never rendered in TwinRoot | **P1** | M |
| 11 | Revision history / branching layouts | `/api/design/layouts` exists, never rendered in TwinRoot | **P2** | M |
| 12 | Team markup + comments | `annotations` in twinStore, only local, no multi-user | **P2** | L |
| 13 | Export PDF / KML / DXF / PVsyst | `/api/design/export` exists, tied to left-rail "Export GA" button via `princeps:twin:export` event but no listener in `DesignPage` | **P1** | S |
| 14 | Multiple view modes (plan / oblique / 3D) | Four tabs render one behaviour (camera pose), not four renderers | **P1** | M |
| 15 | PUE / WUE estimate for DC layouts (Princeps moat vs Glint) | **Missing** — Glint doesn't do DC; this is where we one-up | **P1** | M |

---

## 3. DIE / FIX / ADD

### DIE
- **Monochrome `dark-v11` basemap** on `DesignPage`. Replace with Mapbox
  satellite-v12 + terrain + 3D buildings, which is already in use on the
  workspace `DesignCanvas`. Losing nothing — the dark look doesn't survive
  first-demo contact.
- **Empty canvas on default visibility**. Site-boundary polygon guard
  (`TwinRoot.jsx:434`) must fall back to the project `lat/lon` + a 250 m
  buffer polygon when no WKT is persisted. Same for the asset renderer.
- **Cryptic measurement ruler "M" tool** as default active tool on page open.
  If there's nothing to measure, the tool is noise. Remove from first-run
  state; fire it only when user has geometry.
- **Layer-rail "Megapacks / Electrical / Civil / Grid"** as surfaced group
  names on a DC project. For a DC workload the groups should be "Shell /
  Power / Cooling / Network / Civil / Grid / Constraints" — we're showing the
  BESS rail to a DC user. `LayerRailRight` should read `tech` and swap its
  `GROUPS` definition.

### FIX
- **Project geometry loading** — wire `project.lat/lon/polygon_wkt` from
  `GET /api/projects/{id}`. Either (a) server-side: extend the SELECT to emit
  `ST_AsText(polygon_4326) AS polygon_wkt` + `lat` + `lon`; or (b) client-side:
  in `DesignPage.jsx:66` fall through to `lat`/`lon` scalars and synthesise a
  minimal `POLYGON((...))` 250-m buffer ring via turf. Both are acceptable;
  (a) is canonical, (b) unblocks the demo tonight.
- **Real layer rendering when toggles ON** — bind `layerVisibility.site` to a
  lat/lon buffer polygon (not just WKT), bind `layerVisibility.assets` to the
  `computeLayout` result, bind `layerVisibility.constraints` to a fetched
  `buildable-mask` GeoJSON, bind `layerVisibility.grid` to the
  `/api/grid/nearest-substation` result rendered as a LineLayer from shell to
  POC.
- **Plan / Oblique / Construction / Drone as distinct renderers**:
  - **Plan** — orthographic flat-shade, no pitch, labels on every asset,
    dimension stamps, north arrow, scale bar. This is the PDF GA drawing.
  - **Oblique** — current pose; marketing hero.
  - **Construction** — time-phased shell shown as hoarding → foundations →
    shell → fitout tied to `timeMonth`; crane silhouettes; construction zones.
  - **Drone** — current cinematic + DOF blur via Mapbox fog + particulate
    haze; snapshot-frame overlay so the user knows they're "recording".

### ADD
- **Aerial imagery basemap** — Mapbox `satellite-streets-v12` + terrain DEM +
  3D buildings. Same three lines as `DesignCanvas.jsx:436-443`.
- **Constraint overlays** — fetch `/api/design/buildable` + `/buildable-mask`
  on mount, render as two deck.gl `PolygonLayer` passes (green buildable,
  red/amber/blue/magenta mask). Reuse the colour constants in
  `DCContextOverlays.jsx:20-28`.
- **Setback dimensions** — render `ScatterplotLayer` + `TextLayer` with
  distance-to-boundary labels once assets exist. Standard UK setbacks:
  - 12 m highway setback (DMRB),
  - 6 m residential boundary (CDM / planning policy),
  - 15 m PROW,
  - 50 m noise setback for gensets (BS 4142).
- **Equipment palette** — left-docked 260 px panel, above or below
  `ToolbarLeft`. Categories: Batteries / PV / Inverters / Transformers /
  Gensets / Chillers / Switchgear / Shells. Drag-drop onto the canvas emits a
  new entry in `twinStore.assets` (new slice) which the renderer honours.
- **Auto-layout button** — calls `POST /api/design/auto-layout` with
  `{lat, lon, tech, capacity_mw, buildable_ring}`, replaces the parametric
  `computeLayout` output.
- **PUE / WUE estimate per layout** — for `tech=dc`: render an inline card
  showing PUE (from chiller count × cooling preset + genset standby loss),
  WUE (from cooling type + redundancy), DCIE. Our moat vs Glint.
- **Pass/fail constraint panel** — top-right below the view-mode tabs, docked
  120 px card: "6 rules pass, 2 warnings, 0 blockers". Click opens the
  detailed list.
- **Export controls** — wire the `princeps:twin:export` event listener in
  `DesignPage` to call `POST /api/design/export` with format=pdf|kml|dxf.
- **Revision branching** — bottom-right hover dropdown listing
  `/api/design/layouts?project_id=…` versions with "branch from here"
  affordance. Store current version id in twinStore.
- **Team markup** — lift the existing `annotations` slice to server via
  `/api/design/layouts/:id/annotations` (endpoint doesn't exist yet; out of
  scope for the 3 bots below, queue as a separate BOT-SDM for v2).

---

## 4. Three disjoint execution-bot briefs

Each bot owns strictly disjoint files. Disputed edges go to **BOT-SDL** (it
owns the integration point). Every bot must land CI-green and not regress the
workspace-embedded `DesignCanvas` surface.

### BOT-SDL — Loading + layer wiring
**Goal**: page centres on real project coords, all four default toggles render
real data.

**Owned files** (edit):
- `feasi-frontend/src/pages/Design/DesignPage.jsx` (lines 31-62 data fetch,
  lines 64-67 geometry derivation, lines 96-109 TwinLazy mount).
- `feasi-frontend/src/components/twin3d/TwinRoot.jsx`
  (lines 108-312 `computeLayout` wiring to `buildable_ring`, lines 360-373
  centroid memo, lines 428-490 layers effect).
- `feasi-frontend/src/components/twin3d/stores/twinStore.js` (add a
  `projectGeometry` slice storing `{lat, lon, polygon_wkt, buildable_ring,
  buildable_mask, nearest_poc}`).
- `app/routers/projects.py` (lines 265-296 `get_project` — extend SELECT to
  synthesise `ST_AsText(ST_Transform(polygon_4326, 4326)) AS polygon_wkt` and
  expose `lat`/`lon` floats).

**Forbidden**:
- Touching `computeLayout`'s parametric rules (BESS / solar / DC seeds stay).
- Touching `LayerRailRight`, `ViewModeTabs`, `ToolbarLeft`, `ScaleReferences`
  (BOT-SDE owns chrome changes).
- Touching `mapStyle`, terrain, 3D buildings, constraint overlays (BOT-SDB).

**Deliverables**:
1. When a user opens `/design/:projectId` for the Slough project, the Mapbox
   map centres on `(51.5260, -0.6155)` at zoom 16 pitch 45°.
2. When `polygon_wkt` is missing but `lat/lon` are present, synthesise a
   250-m square buffer ring on the client, pass to `TwinRoot`.
3. `layerVisibility.assets=true` renders the DC seed (hall + gensets + CRACs +
   UPS) on the ground plane, not on The Mall.
4. `layerVisibility.site=true` renders the buffer ring (or the real polygon).
5. `layerVisibility.grid=true` fetches `/api/grid/nearest-substation` and
   draws a LineLayer from campus centroid to POC.

**Confidence**: **High (0.9)** — all needed endpoints exist, change is purely
wiring. Only risk is the `projects.py` schema; keep it client-side if DB
migration adds cost.

---

### BOT-SDB — Basemap + constraint overlays
**Goal**: replace the dark streetmap with aerial + terrain + 3D buildings, and
light up flood / SSSI / ALC / AONB / listed-building overlays.

**Owned files** (edit):
- `feasi-frontend/src/components/twin3d/TwinRoot.jsx` **only** the
  `mapStyle` prop default (line 324) and the `map.on('load', ...)` block at
  lines 402-407 — add terrain DEM source + 3D building fill-extrusion layer
  here.

**Owned files** (create):
- `feasi-frontend/src/components/twin3d/overlays/ConstraintOverlayLayer.js` —
  factory that fetches `/api/design/buildable` + `/api/design/buildable-mask`
  and returns an array of deck.gl `PolygonLayer`s (one per class). Reuse the
  RGBA palette from `components/dc/DCContextOverlays.jsx:20-28`.
- `feasi-frontend/src/components/twin3d/overlays/SetbackDimensionsLayer.js` —
  factory for dimension-stamp `TextLayer` on buildable ring + highway buffer.

**Forbidden**:
- Touching `DesignPage.jsx`, the `TwinLazy` error boundary, the `ToolbarLeft`,
  `LayerRailRight`, `ViewModeTabs`, or any equipment palette code.
- Touching `computeLayout`, `AssetInstancedLayer`, `ShadowPolygonLayer`.
- Touching the `twinStore` — BOT-SDL owns store slice additions, this bot
  reads only.
- Touching `projects.py` or any backend file.

**Deliverables**:
1. `mapStyle` defaults to `mapbox://styles/mapbox/satellite-streets-v12` on
   `/design/` (DesignCanvas already uses this; bring TwinRoot in line).
2. Terrain: `map.addSource('mapbox-dem', {type:'raster-dem', url:'mapbox://
   mapbox.terrain-rgb'})` + `map.setTerrain({source:'mapbox-dem', exaggeration:
   1.2})` inside the existing `load` handler.
3. 3D buildings: fill-extrusion layer filtered on `extrude==true` as in
   `GridTwin.jsx`.
4. New `ConstraintOverlayLayer` returns 5-6 PolygonLayers gated on
   `layerVisibility.constraints=true`. Default-on for DC technology.
5. Dimension stamps on the buildable ring when `layerVisibility.site=true`.

**Confidence**: **High (0.85)** — all deck.gl + Mapbox patterns exist in
`GridTwin.jsx` and `DCContextOverlays.jsx`, lift-and-shift. Risk: Mapbox
terrain at zoom 16 can be slow on M1 — cap `exaggeration` at 1.0 on plan mode.

---

### BOT-SDE — Equipment palette + real-tab renderers
**Goal**: ship a left-docked equipment palette with drag-drop, and make the
four top tabs render four distinct experiences.

**Owned files** (edit):
- `feasi-frontend/src/components/twin3d/ToolbarLeft.jsx` — move the existing
  48-px tool rail to `top: 12 + 340px` to make room for the palette above it.
- `feasi-frontend/src/components/twin3d/ViewModeTabs.jsx` — keep IDs, but emit
  a distinct `princeps:twin:viewMode:plan|oblique|construction|drone` event on
  change so per-mode renderers can listen.
- `feasi-frontend/src/components/twin3d/camera/useCameraMode.js` — extend
  `POSES` to include per-mode side-effects (construction = hoarding paint,
  drone = DOF fog). Keep the existing flyTo contract.

**Owned files** (create):
- `feasi-frontend/src/components/twin3d/EquipmentPalette.jsx` — left-docked
  260 × 340 px panel, tech-aware (reads `tech` from twinStore projectGeometry
  slice added by BOT-SDL). Categories: Batteries / PV / Inverters /
  Transformers / Gensets / Chillers / Switchgear / Shells. Source the asset
  definitions from `twin3d/assets/registry.js` (already 12 primitives
  shipped). Drag-drop emits `twinStore.addAsset({assetType, position})`.
- `feasi-frontend/src/components/twin3d/renderers/PlanRenderer.js` — flat-
  shaded orthographic overlay: labels, dim stamps, north arrow, scale bar.
- `feasi-frontend/src/components/twin3d/renderers/ConstructionRenderer.js` —
  hoarding paint + crane silhouettes tied to `timeMonth`.
- `feasi-frontend/src/components/twin3d/renderers/DroneRenderer.js` — Mapbox
  `setFog()` + auto-rotate already exists; add snapshot-frame UI chrome and
  DOF blur.

**Forbidden**:
- Touching `DesignPage.jsx`, `TwinRoot.jsx` (other than reading twinStore),
  `mapStyle`, terrain, overlays, constraint layers, `buildable` endpoints.
- Touching `projects.py` or any backend.
- Changing `computeLayout` seed rules.

**Deliverables**:
1. Equipment palette renders on the left, 260 px wide, 340 px tall, with the
   existing 12 primitives grouped by tech. Drag-drop onto canvas adds an
   asset instance at the drop lng/lat, persisted via `twinStore.addAsset`.
2. Plan tab renders orthographic view + labels + dim stamps.
3. Construction tab paints hoarding + crane silhouettes driven by `timeMonth`.
4. Drone tab adds fog + frame chrome + DOF hint.
5. Oblique tab unchanged (baseline).

**Confidence**: **Medium (0.7)** — palette + drag-drop is mechanical; the four
distinct renderers add ~3 days of iteration risk for visual polish (DOF blur
and hoarding paint specifically are non-trivial on a pure deck.gl stack
without three.js post-processing). Ship Plan + Oblique + Construction first,
Drone can stay cinematic-lite for v1.

---

## 5. Out-of-scope but tracked

- **BOT-SDM** (markup + comments) — multi-user annotations via
  `/api/design/layouts/:id/annotations` (endpoint does not exist).
- **BOT-SDR** (revision branching) — wiring `/api/design/layouts` to a
  bottom-right version dropdown. Endpoints exist; UI doesn't.
- **BOT-SDX** (export) — wire `princeps:twin:export` to
  `/api/design/export` with format selector (PDF / KML / DXF / PVsyst).
- Converging `DesignPage` ↔ `DesignCanvas` onto one surface (tracked in
  `project_site_designer_consolidation.md`).

---

## 6. Acceptance — demo script

After all three bots land, the operator should be able to:

1. Open `/design/<slough-project-id>`.
2. Land on Slough Trading Estate with satellite imagery visible, project
   polygon highlighted, flood / ALC / protected overlays drawn in their
   respective colours, 3D buildings rendered on the POC substation area.
3. See the DC shell + genset yard + chiller plant rendered **on the actual
   parcel**, not on Trafalgar Square.
4. Drag a Tesla Megapack 2XL from the equipment palette, drop it on the
   buildable area; see it snap onto terrain, see a new row appear in
   `twinStore.assets`.
5. Hit Cmd-1 (Plan) — get a GA-style orthographic drawing with dims and
   labels; hit Cmd-3 (Construction) — see the shell morph between hoarding /
   foundations / fitout as the bottom time-scrubber moves; hit Cmd-4 (Drone)
   — see cinematic DOF with auto-rotate.
6. Click the pass/fail chip top-right — see "6 rules pass, 2 warnings: 15 m
   setback clash on east boundary, flood-zone 2 within 60 m".
7. Click Export — get a PDF GA drawing + DXF.

If any of those fail, the demo fails.

---

## 7. Confidence summary

| Bot | Confidence | Blocking risks |
|---|---|---|
| BOT-SDL — Loading + layers | **0.90** | `projects.py` schema change (can be client-side fallback) |
| BOT-SDB — Basemap + constraints | **0.85** | Mapbox terrain perf at zoom 16 on M1 |
| BOT-SDE — Equipment + tabs | **0.70** | DOF blur in deck.gl; hoarding paint asset choice |

Overall: **0.82**. Ship the three bots in parallel; BOT-SDL first-past-the-
post unblocks the others (polygon/ring + twinStore `projectGeometry` slice).
