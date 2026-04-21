# Grid Graph 100x Spec — Asset Browser + Overlay Toggles + Legend

**Author:** COUNCIL-GG (read-only swarm agent)
**Scope:** the "Grid Graph" page rendered by `GridGraphContainer` when its child is `MapView`, plus the floating `LayerRail` overlay panel and the left-rail Grid Assets browser.
**Not in scope:** GridTwin / Cesium / DC twin / Canvas — separate specs already exist at `docs/audits/grid_twin_redesign_spec.md` and `docs/audits/dc_twin_sophistication_spec.md`.

---

## 1. Component map

### 1a. Asset browser (left panel) — filter logic + "No matches" copy

| Concern | File | Lines |
|---|---|---|
| Top-level container, filter state | `feasi-frontend/src/components/grid-graph/GridGraphContainer.jsx` | 257–463 |
| Voltage bucket definition | same | 55 (`VOLTAGE_BUCKETS = [400, 275, 132, 66, 33, 22, 11]`) |
| DNO list definition | same | 56 (`DNOS = ["UKPN","NGED","SSEN","SPEN","ENWL","NPG"]`) |
| Filter pipeline (AND-of-filters, no feedback) | same | 286–299 |
| Voltage pill render | same | 407–419 |
| DNO pill render | same | 420–433 |
| `VirtualList` empty state — the dumb "No matches" | same | 490–492 |
| Row render (displayName fallback) | same | 503–524 |

### 1b. Floating GRID overlay panel — checkbox state → layer builder wiring

| Concern | File | Lines |
|---|---|---|
| Section definition with toggle ids/colors | `feasi-frontend/src/components/LayerRail.jsx` | 14–23 (Grid section) |
| Checkbox render (sole entry point for toggling) | same | 271–302 |
| `toggleLayer` source of truth | `feasi-frontend/src/SiteContext.jsx` | 343–390 |
| Defaults (all grid overlays default **off** except `gridFlow`) | same | 343–387 |
| `Grid Connection` preset | `feasi-frontend/src/components/LayerRail.jsx` | 121 |

### 1c. deck.gl / Mapbox layer builders — what props modulate each visual

The Grid Graph's "Map" sub-view mounts `MapView.jsx` (plain Mapbox GL, not deck.gl — deck.gl is only used in the separate `GridTwin.jsx` overlay). All Grid-overlay painting is inside `MapView.jsx`:

| Overlay toggle | Source id | Layer ids | Paint file/lines |
|---|---|---|---|
| `gridCapacity` (Capacity RAG) | `gc-capacity-subs` + `gc-grid-lines` | `gc-capacity-circles`, `gc-capacity-labels`, `gc-verdict-badges`, `gc-lines-glow`, `gc-lines-core` | `MapView.jsx:1376–1447` (circles + labels + verdict) |
| `gridConstraints` (Constraints) | `grid-constraints` | `constraint-zone-fill`, `constraint-zone-outline`, `constraint-zone-labels` | `MapView.jsx:1506–1560` |
| `queueDepth` (Queue Depth) | `queue-depth` | `queue-depth-circles`, `queue-depth-labels` | `MapView.jsx:1999–2045` |
| `gridFlow` (Substations) | `grid-flow-nodes` + `grid-flow-edges` | `grid-node-circles`, `grid-node-labels`, `grid-flow-*` | `MapView.jsx:1014–1050` |
| `osmPower` (Lines) | `osm-power-lines` + `osm-power-substations` | `osm-power-line-*`, `osm-substation-circles`, `osm-substation-labels` | `MapView.jsx:1051–1140` |
| `tecPipeline` (TEC Queue) | `eso-tec-projects` | `eso-tec-circles`, `eso-tec-labels` | `MapView.jsx:2190–2239` |
| `repdProjects` (REPD) | `repd-projects` | `repd-circles`, `repd-labels` | `MapView.jsx:2258–2308` |
| Visibility switch (v→`none`/`visible`) | — | — | `MapView.jsx:2942–3005` (the `layerMap` + `setLayoutProperty` loop) |

Data fetch `useEffect`s per toggle (fire only when toggle is on):
- `gridCapacity` → `MapView.jsx:3380–3423`
- `gridConstraints` → `MapView.jsx:3425–3445`
- `queueDepth` → `MapView.jsx:3491–3511`
- `tecPipeline` → `MapView.jsx:3298–3333`
- `repdProjects` → `MapView.jsx:3335–3377`

### 1d. Legend / tooltip / hover state components

| Concern | File | Lines |
|---|---|---|
| **No persistent on-map Grid legend exists.** The only grid-adjacent legend is FES-only | `feasi-frontend/src/components/map/FESLegend.jsx` | whole file |
| Per-layer click popups (inline HTML string) — `gridCapacity` | `MapView.jsx` | 1464–1500 |
| Per-layer click popups — `queueDepth` | `MapView.jsx` | 2047–2062 |
| Per-layer click popups — `tecPipeline` | `MapView.jsx` | 2242–2254 |
| Per-layer click popups — `repdProjects` | `MapView.jsx` | 2311–2323 |
| Hover cursor toggles only (no hover tooltip — you only see data on **click**) | `MapView.jsx` | 1502–1503, 2063–2064, 2099–2100, 2255–2256, 2325–2326 |
| Node labels (`grid-node-labels`) are zoom ≥9, name + demand_mw | `MapView.jsx` | 1033–1049 |
| OSM line labels — zoom ≥10 **and only voltage≥132kV** | `MapView.jsx` | 1099–1123 |
| Graph sub-view legend (DNO only) | `GridGraphContainer.jsx` | 881–901 |

---

## 2. Current layer inventory — what actually mounts

| LayerRail label | SiteContext key | Mapbox layers exist? | Source fetch wired? | Real visual? |
|---|---|---|---|---|
| Capacity (RAG) | `gridCapacity` | YES (5) | YES | YES — graduated circles + labels + verdict badges |
| Constraints | `gridConstraints` | YES (3) | YES | YES — boundary polygons colored by risk_level |
| Queue Depth | `queueDepth` | YES (2) | YES | YES — purple circles sized by queue_count |
| Substations | `gridFlow` | YES (many) | YES (on mount — `MapView.jsx:3142–3172`) | YES — but **labels default to visible at z≥9 regardless of toggle** (line 1046 uses `visibility: "visible"`) |
| Lines | `osmPower` | YES (many) | YES (`MapView.jsx:3177–3259`) | YES — OpenInfraMap voltage palette |
| TEC Queue | `tecPipeline` | YES (2) | YES | YES — technology-coloured circles |
| REPD | `repdProjects` | YES (2) | YES | YES — technology-coloured circles |

**Net:** every Grid toggle *does* wire to a real layer. **Not a no-op** — but the user's perception "nothing happens" is defensible because:
1. There are no hover tooltips — you must click a pinpoint to see anything.
2. Multiple overlays stack the same circle geometry (substations) with near-identical radii → they visually merge.
3. **No legend** — a user sees circles in purple/amber/red/blue and has no anchor for what those mean.
4. Labels are sparse: `queueDepth` labels only at z≥8, `repd` only at z≥10, `osmPower` lines only at z≥10 AND voltage ≥132kV, so the mid-zoom UK-wide view users open with is label-free.

---

## 3. DIE / FIX / ADD

### DIE
1. `VirtualList` empty state "No matches" at `GridGraphContainer.jsx:491` — gives zero diagnostic signal.
2. The "combination is valid but empty" anti-pattern — there is no UI affordance that 400kV ∩ UKPN is structurally empty because 400kV is transmission (NGET) and UKPN is distribution.
3. Grid toggles without hover tooltips — users cannot interrogate the dots they see. Click-only is a regression vs every mapping tool users know.
4. Substation labels permanently visible at z≥9 on `gridFlow` regardless of the checkbox — the toggle lies. (`MapView.jsx:1046`)
5. No persistent on-map legend explaining circle/line colours.

### FIX
1. **Hover tooltips on every grid overlay layer.** Every `map.on("mouseenter", ...)` at lines 1502/2063/2099/2255/2325 currently only changes the cursor. Add a `mouseenter`+`mousemove`+`mouseleave` pattern that creates a lightweight hover popup (smaller than the click popup). Substation hover must show: name · DNO · voltage_kv · headroom_mw · queue_count (if loaded). Line hover must show: voltage_kv · operator (or DNO) · length_km.
2. **Text labels at zoom > 8 for substations** — remove the `visibility: "visible"` default at `MapView.jsx:1046`; bind it to the `gridFlow` toggle (fix the lie). Tighten the gridFlow label expression to prefer `name` (collapse the `"\nMW"` suffix until z≥11).
3. **Line labels: always show voltage at z≥10, drop the `>=132kV` filter** (`MapView.jsx:1104`). At 11/33kV the user still needs to know what they're looking at.
4. **Toggle-state honesty** — when the user flips `gridCapacity` off, force-clear the source at `MapView.jsx:3419` (already done) AND call `map.setLayoutProperty` for all 5 layer ids synchronously so the user sees instant feedback without a next-frame `moveend`.

### ADD
1. **Persistent on-map Grid legend** — bottom-right corner (mirrors FESLegend convention; top-right is already owned by chat rail on this layout). Driven by `layers.*` so it shows only the currently-active overlays. Collapsible. Must cover:
   - Substation Capacity RAG: green ≥50 MW headroom / amber 10–50 MW / red <10 MW (matches `MapView.jsx:1438–1441` thresholds)
   - Line voltage class: 400 · 275 · 132 · 66 · 33 · 11 kV (matches `osmVoltageColor` palette at `MapView.jsx:1053–1062`)
   - TEC Queue: technology swatches (Solar #fdd835 / Wind #00b0ff / Battery #7cb342 / Gas #ff8f00 / Nuclear #e53935 / Hydro #1565c0 / Biomass #8d6e63 / Interconnector #ab47bc / Other #0277bd) — from `MapView.jsx:2201–2212`
   - REPD: status or technology — use technology palette from `MapView.jsx:2269–2282`
   - Queue Depth: HIGH/MEDIUM/LOW pressure colours from `MapView.jsx:2009–2015`

2. **Smart empty state on asset browser** (replace `GridGraphContainer.jsx:491`). Inspect `voltageFilter` ∩ `dnoFilter` before rendering "No matches" and detect structurally-empty combinations:
   - voltage ∈ {400, 275} ∧ any DNO selected → "No matches. 400/275kV is National Grid ET (transmission). Clear DNO filter to see NGET assets, or pick 132kV to stay on a DNO."
   - voltage = 132 ∧ dno = UKPN → "UKPN operates 132kV primarily in EPN/SPN. Results may be empty if this bucket isn't ingested yet — try 33kV or 66kV."
   - search term with no numeric → add "No match for '<q>' — try postcode or substation code."
   - Generic fallback: list the three most-populated (voltage × DNO) combos from the `substations` array with one-click apply.

3. **Facet counts on pills** — the filter pill components at `GridGraphContainer.jsx:407–433` currently show only the label (e.g. "400kV", "UKPN"). Replace with Finder-style dual-line: `400kV` on top, `23` (count) underneath in mono dim. Count = how many substations match the *other* filters + search, i.e. the marginal count if you flipped this pill on. A pill that would yield zero matches gets rendered disabled + tooltipped with the same copy from ADD#2. This forces the combinatorial truth onto the surface before the user clicks.

4. **Persistent hover readout strip** — bottom-center 40px strip that echoes whatever overlay + feature the cursor is over. Replaces the need to click for 80% of inspection gestures. Optional; lower priority than the legend.

---

## 4. Bot briefs — disjoint file ownership

### BOT-GO (overlays — wire every toggle to a distinct, informative layer)
**Owns:** `feasi-frontend/src/components/MapView.jsx` ranges `1376–1560`, `1999–2045`, `2190–2308`, `2942–3005`, `3142–3511`.
**Does NOT touch:** `GridGraphContainer.jsx`, `LayerRail.jsx`, `SiteContext.jsx`, new legend files.
**Tasks:**
- Fix the `gridFlow` default-visible label bug at 1046 (bind visibility to `layers.gridFlow`).
- Ensure the toggle→layerMap switch at 2942–3005 is synchronous (no next-tick `moveend` dependency).
- Add a sixth overlay wire-up for `gridConstraints` if new backend adds line-level constraint types (keep source/layer id pattern).
- Verify every overlay has distinct `circle-radius`, `circle-color` AND z-ordering so they don't visually collide when stacked (shift `queue-depth-circles` z +50 above `gc-capacity-circles`).

### BOT-GL (labels + legend + hover tooltips)
**Owns:** new file `feasi-frontend/src/components/map/GridLegend.jsx`; mounts it in `feasi-frontend/src/components/MapView.jsx` near the existing overlay children (before the closing return). Also owns the `map.on("mouseenter"...)`/`mousemove`/`mouseleave` blocks at `MapView.jsx:1502–1503, 2063–2064, 2099–2100, 2255–2256, 2325–2326` — extends each to create a lightweight hover popup. Owns the label-layout edits at `MapView.jsx:1033–1049` and `MapView.jsx:1099–1123`.
**Does NOT touch:** the overlay source/fetch effects (BOT-GO), asset browser (BOT-GA), SiteContext (BOT-GC).
**Tasks:**
- Build `GridLegend.jsx` reading `layers` from `useSite()`, rendering only active groups. Mirror `FESLegend.jsx` styling convention but use bottom-right slot.
- Drop the `>=132kV` filter on line labels (1104) and add a zoom-graduated text-size.
- Unify hover handlers into a single helper hook `useMapHoverTooltip(map, layerId, renderer)` in a new `feasi-frontend/src/hooks/useMapHoverTooltip.js`.

### BOT-GA (asset browser — smart empty state + facet counts)
**Owns:** `feasi-frontend/src/components/grid-graph/GridGraphContainer.jsx` ranges `55–56` (constants), `286–299` (filter pipeline), `407–433` (pill render), `490–492` (empty state). May add a helper file `feasi-frontend/src/components/grid-graph/emptyStateDiagnosis.js`.
**Does NOT touch:** `MapView.jsx`, `LayerRail.jsx`, `SiteContext.jsx`, legend.
**Tasks:**
- Replace `VirtualList` empty state with a diagnosis component driven by `emptyStateDiagnosis(voltageFilter, dnoFilter, search, substations)` that returns structured guidance + suggested-filter chips.
- Precompute two `useMemo` facet-count maps: `byVoltageGivenOtherFilters` and `byDnoGivenOtherFilters` (apply every filter EXCEPT the axis being counted). Render counts in the pills.
- Disable pills whose marginal count is 0, add a tooltip explaining the structural reason (via the same `emptyStateDiagnosis` lookup).

### BOT-GC (colour semantics + palette reconciliation)
**Owns:** a new `feasi-frontend/src/lib/gridPalette.js` that becomes the single source of truth for grid colour codes, consumed by BOT-GO (paint expressions), BOT-GL (legend swatches), BOT-GA (pill colours). Also owns `feasi-frontend/src/SiteContext.jsx:343–387` (normalising default overlay-on set and whether pipeline-stage mapping exposes the same palette). Owns `feasi-frontend/src/components/StageRibbon.jsx:1–50` read-only — must reconcile its stage colour codes (prospect/screened/planning/FID/construction/energised) against the grid RAG palette so overloading doesn't confuse the map.
**Does NOT touch:** MapView paint code directly — exports constants/functions that BOT-GO imports. Does NOT touch asset browser logic, only the palette it reads.
**Tasks:**
- Extract the 6 palettes currently duplicated across `MapView.jsx` (RAG at 1387–1390, voltage at 1053–1062, verdict at 1436–1441, queue at 2009–2015, TEC tech at 2201–2211, REPD tech at 2269–2281) into one module with named exports.
- Codify the RAG thresholds (currently implicit at 1438–1441: ≥50 GO, ≥10 CAUTION, else NO-GO) as named constants `GRID_RAG_THRESHOLDS = { GO: 50, CAUTION: 10 }`.
- Write a short `pipelineStageVsGridRAG.md` note (BOT-GC scratchpad) documenting that the StageRibbon pipeline pills (lifecycle) and Grid Map RAG pills (capacity state) share no palette — prevent future accidental overload.

---

## 5. Confidence per finding

| Finding | Confidence | Rationale |
|---|---|---|
| Component-map file/line citations | **High** — read every cited range directly |
| All 7 Grid toggles wire to real Mapbox layers | **High** — layerMap at `MapView.jsx:2942` confirms; data-fetch effects confirmed per id |
| `gridFlow` labels leak (visibility:"visible" at 1046) | **High** — direct read |
| No persistent Grid legend exists | **High** — only `FESLegend.jsx` found, verified scope |
| OSM line labels filter out <132kV | **High** — direct read at 1104 |
| Hover only changes cursor, no tooltip | **High** — handlers at 1502/2063/2099/2255/2325 confirmed trivial |
| "Stacking collision" of overlay circles on same substation coords | **Medium** — plausible from radius overlap at zooms 5–9 but not tested live |
| Empty-state copy suggestions will match user mental model | **Medium** — UK grid ownership rules are correct; specific ingestion gaps (e.g. UKPN@132kV) are a guess not verified against the live DB |
| Facet-count approach will be performant on 14k substations | **High** — pure JS `.reduce` on memoised array is trivial |

---

*End of spec.*
