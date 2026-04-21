# Intelligence > Datasets — UI Truth Audit (2026-04-21)

Auditor: COUNCIL-DS (read-only). Scope: Sidebar "Site Twin" orphan claim + Datasets page CTA wiring + page-wide dead-UI sweep.

---

## 1. Site Twin verdict — WIRED (not orphaned), but discoverability is broken

**Keep it. Do not remove. Small UX fix only.**

- Declared in NAV_ITEMS at `feasi-frontend/src/components/shell/Sidebar.jsx:106`.
- Click handler navigates to a **real** full-screen 3D route `/design/:projectId`, implemented in `feasi-frontend/src/components/shell/Sidebar.jsx:355-360` and mounted in `feasi-frontend/src/main.jsx:137-148` (`DesignPage` → `TwinLazy`).
- Target page exists at `feasi-frontend/src/pages/Design/DesignPage.jsx` and is non-trivial (full 3D Site Twin).
- Active-project gate is at `feasi-frontend/src/components/shell/Sidebar.jsx:413`: `const disabled = item.id === "sitetwin" && !activeProjectId;`. Without `?project=<id>` in the URL the row is rendered at `opacity: 0.5` with `cursor: not-allowed`.

**So why did the user think it was new and unreachable?**
1. The row is permanently present at full height but is greyed out *silently* until an active project is pinned in the URL — the disabled-state styling (`opacity: 0.5`, `disabledTooltip`) at `feasi-frontend/src/components/shell/Sidebar.jsx:129-131` is too subtle and the `disabledTooltip` prop is never passed, so hovering says nothing.
2. The only way to "activate" it is to select a project via the Projects tree (→ `onSelectProject` at `feasi-frontend/src/components/shell/Sidebar.jsx:308-322`) which writes `?project=<id>` to the URL. A user who hasn't expanded Projects will never unlock it.
3. `ActionsMenu.jsx:26` lists it as "Unified Site Twin" — name drift vs the sidebar.

**Recommendation**: keep the row; make the disabled state legible with a tooltip ("Select a project to open its 3D Site Twin") and wire a fallback click to route to `/design` (no project) so the user at least lands on the Twin empty state. Rename `ActionsMenu.jsx` entry to "Site Twin" for consistency.

---

## 2. Datasets CTA wiring — truth table

Each dataset card (`DatasetCard` in `feasi-frontend/src/pages/Intelligence/Datasets/DatasetsIndex.jsx:223-412`) renders up to 3 actions. Visibility depends on flags on the record in `feasi-frontend/src/data/mock-datasets.json`.

- **Open primary source** — always rendered (anchor `<a target="_blank">` to `dataset.primary_source_url`). Line 348-366.
- **Show on Map** — rendered only when `dataset.show_on_map === true`. Click handler calls `useDatasetLayer()` hook (line 228-231, 367-387). Hook at `feasi-frontend/src/hooks/useDatasetLayer.js`.
- **Recent updates** — rendered only when `dataset.change_log_available === true`. Opens `DatasetChangeLogModal`. Line 388-408.

### Truth table (all 21 cards)

| # | Card (title) | Open primary source | Show on Map (rendered?) | Show on Map (actually toggles a real layer?) | Recent updates |
|---|---|---|---|---|---|
| 1 | UK N-1 Contingency Map | yes (link) | yes | **NO** — `map_layer_slug` = `n1_reliability_heat`, no entry in `SLUG_TO_LAYER` nor in SiteContext `layers{}` | yes (modal) |
| 2 | NESO TEC Register | yes | yes | yes (`tec_register` → `tecPipeline`) | yes |
| 3 | DNO Capacity Maps — UKPN/NPG/NGED/SPEN/ENWL/SSEN | yes | yes | **yes in principle** (`dno_capacity` → `gridCapacity`) — see "why user's click appeared dead" below | yes |
| 4 | HMLR INSPIRE Polygons | yes | yes | yes (`land_parcels` → `landParcels`) | yes |
| 5 | HSE COMAH + BESS Safety | yes | — (hidden) | — | yes |
| 6 | EU EED Article 12 | yes | — | — | yes |
| 7 | REPD | yes | yes | yes (`repd` → `repdProjects`) | yes |
| 8 | PINS NSIP Register | yes | yes | **partial** (`nsip` is mapped but falls back to `repdProjects`, wrong surface) | yes |
| 9 | Ofgem Publications + Decisions | yes | — | — | yes |
| 10 | BMRS Balancing Mechanism | yes | — | — | yes |
| 11 | LCCC CfD AR7 | yes | — | — | yes |
| 12 | Capacity Market Auction Results | yes | — | — | yes |
| 13 | NESO FES 4-Pathway Scenarios | yes | — | — | yes |
| 14 | Companies House SPV Filings | yes | — | — | yes |
| 15 | Find-a-Tender Energy Notices | yes | — | — | yes |
| 16 | NESO Balancing Services Monthly | yes | — | — | yes |
| 17 | Ofgem RIIO-ED2/ED3 Register | yes | — | — | yes |
| 18 | EA Flood Map for Planning | yes | yes | **NO** — `map_layer_slug` = `ea_flood_planning`, only `flood_zones` / `floodzones` / `flood` are mapped | yes |
| 19 | LCCC CfD Daily Reference Price | yes | — | — | yes |
| 20 | MoD DIO Safeguarding Zones | yes | yes | **NO** — `map_layer_slug` = `mod_safeguarding`, unmapped | yes |
| 21 | CAA Aerodrome Safeguarding | yes | yes | **NO** — `map_layer_slug` = `caa_aerodrome_safeguarding`, unmapped | yes |

### Why the user's DNO Capacity Maps click "did nothing"

The click path:

1. `handleMap()` in `DatasetCard` (line 228-231) calls `goToMap(slug, layer)`.
2. `useDatasetLayer` (`feasi-frontend/src/hooks/useDatasetLayer.js:40-66`) `navigate("/?dataset=dno-capacity-maps&layer=dno_capacity")` then fires a `princeps-activate-dataset-layer` CustomEvent on `setTimeout(_, 0)`.
3. `/intelligence/*` route in `feasi-frontend/src/main.jsx:209-274` does **NOT** mount a `SiteProvider`. That provider is only mounted under `<LegacyApp />` on the `*` catch-all (line 275). The SiteContext listener at `feasi-frontend/src/SiteContext.jsx:467` is therefore NOT attached while the user is on `/intelligence/datasets`.
4. Navigation swaps the route to `/`, unmounts IntelligenceShell, mounts LegacyApp. Two mount-time mechanisms can catch the layer:
   - URL fallback: `SiteContext.jsx:444-460` reads `?layer=dno_capacity`, `SLUG_TO_LAYER` maps it to `gridCapacity`, and calls `setLayers(prev => ({...prev, gridCapacity: true}))`. This *should* light the layer up.
   - Event: the `setTimeout(_, 0)` dispatch almost certainly fires **before** the listener attaches (React must render the Suspense fallback → Suspense boundary resolves → SiteProvider mounts → `useEffect` runs → `addEventListener` attaches). No listener, event lost.
5. **The likely failure the user experienced**: on `/` the Mission Control overlay (`App.jsx:955-1003`, rendered full-screen when `?redesign=1` is absent) sits *on top of* the map. The map does activate `gridCapacity` underneath, but the user never sees it because Mission Control is covering everything. To them, "nothing happens" — sidebar state didn't change, visible view didn't change, no toast, no indication.
6. Additionally, 4 of the 7 "show_on_map" cards have slugs that are **not in `SLUG_TO_LAYER`** (N-1, EA Flood Planning, MoD Safeguarding, CAA Aerodrome) — for those cards the layer silently fails to activate even under the best conditions.

This is the combined bug: (a) slug→layer mapping is incomplete, (b) no user-visible confirmation, (c) the target view is occluded by Mission Control, (d) event-based fallback is racy.

### What the button SHOULD do (per card / per type)

For every `show_on_map: true` card:

1. Navigate to `/?dataset=<slug>&layer=<map_layer_slug>` — already correct.
2. On LegacyApp mount, `SLUG_TO_LAYER` must cover every slug in the fixture. Missing keys: `n1_reliability_heat`, `nsip` (needs proper layer, not repd fallback), `ea_flood_planning`, `mod_safeguarding`, `caa_aerodrome_safeguarding`.
3. Close the Mission Control overlay as soon as a `?dataset=` param is present (force `?redesign=1` or dismiss the overlay on mount), so the user actually *sees* the map.
4. Fire a toast / pill confirming "Activated: DNO Capacity Maps layer" with a direct "Open Map" link so the user gets feedback even if the map isn't in view.
5. For cards whose slug doesn't correspond to any rendered layer (e.g. COMAH guidance, Ofgem publications), `show_on_map` is correctly `false` — keep it that way.

---

## 3. Other dead / half-dead UI on the page

Found during the sweep of `DatasetsIndex.jsx`, `IntelligenceShell.jsx`, and the Datasets subtree:

- **IntelligenceShell top bar** — `← Princeps` button navigates to `/` and works. `SegmentedControl` (Alerts/Dockets/Engagements/Datasets) works via `NavLink`. No dead items.
- **Filter bar on Datasets page** — `Category`, `Badge`, `Cadence` pill groups (`PillGroup` at lines 171-207, used 540-542) all work — filters drive `useMemo` at 480-487. Good.
- **"Clear filters" button in empty-state** — line 566-583, works.
- **`DatasetChangeLogModal`** — open/close state wired via `changeLogFor` + `setChangeLogFor`. Modal lives at `feasi-frontend/src/pages/Intelligence/Datasets/DatasetChangeLogModal.jsx`. Need to verify internally but the shell wire-up is correct.
- **No search input** — there is no keyword/free-text search on Datasets. With 21 cards and more coming this is a missing affordance but not "broken".
- **No pagination** — currently renders all filtered cards in a single grid. OK at current scale.
- **Sort controls** — none. Cards render in file order; no "sort by refreshed / rows / delta" control.
- **Deep-link back** — if the user lands on `/intelligence/datasets?dataset=<slug>` there is no support; deep-linking only works into the map, not back into the card.
- **Refreshed timestamps are static** — `fmtRefreshed()` (line 101-117) is based on the fixture's `refreshed` field. Cards age as the day goes on (tooltip shows ISO). Fine for a fixture; real feed needs live data.

No runtime errors, no obviously orphaned imports, no broken modal flags.

---

## 4. Execution bot briefs

### BOT-DM — Datasets CTA wiring (owns `feasi-frontend/src/pages/Intelligence/Datasets/*.jsx`, `feasi-frontend/src/hooks/useDatasetLayer.js`, and the `SLUG_TO_LAYER` block at `feasi-frontend/src/SiteContext.jsx:406-426`)

Fix the "Show on Map" chain end-to-end.

1. Extend `SLUG_TO_LAYER` in `SiteContext.jsx` to cover every `map_layer_slug` in `mock-datasets.json`:
   - `n1_reliability_heat` → add real layer (or `gridCapacity` as an honest fallback + a planned `n1Heat` entry)
   - `ea_flood_planning` → `envConstraints`
   - `mod_safeguarding` → new layer id (register in SiteContext `layers{}` + MapView) or map to `planningConstraints`
   - `caa_aerodrome_safeguarding` → same as MoD
   - Promote `nsip` from the `repdProjects` fallback to its own real layer — add a TODO if the layer doesn't exist yet
2. In `useDatasetLayer.js`, on dispatch also call `window.dispatchEvent(new CustomEvent("princeps-dismiss-mission-control"))` (new event) so the map is actually visible after navigation.
3. Show user feedback: add a toast via whichever toast primitive exists (search for `toast`, `notification`, `useToast`) — "Activated <layer> on map". If no toast primitive is present, brief to BOT-DI.
4. Fix the race: replace `setTimeout(..., 0)` with a `sessionStorage.setItem("princeps_pending_layer", JSON.stringify({slug, layer}))`; read + consume it from the mount-time effect in SiteContext as a last-resort fallback.
5. **Do not** rename the button, do not touch card visuals.

### BOT-ST — Site Twin discoverability (owns `feasi-frontend/src/components/shell/Sidebar.jsx` only)

Keep the row; make it honest.

1. Pass `disabledTooltip="Select a project to open its 3D Site Twin"` on the Sidebar NAV row (Sidebar.jsx:413-414 — thread through to `NavRow` which already reads `disabledTooltip`).
2. When disabled and clicked, offer a gentle nudge: expand the Projects tree (`setProjectsOpen(true)`) instead of being a pure no-op at `Sidebar.jsx:355-360`.
3. Rename `ActionsMenu.jsx:26` label from "Unified Site Twin" to "Site Twin" to match Sidebar.
4. **Do not** remove the nav item. **Do not** add a new route.

### BOT-DI — Dead UI / missing affordances (owns `feasi-frontend/src/pages/Intelligence/Datasets/DatasetsIndex.jsx` only — non-CTA scope)

1. Add a free-text search input (filter by title + publisher + description) above the filter bar. Debounce 120ms; keep all pills.
2. Add a "Sort by" chip row: Refreshed (default), Rows desc, 7d delta desc. Small, at the right of the filter bar.
3. Add a lightweight toast / inline banner primitive if none exists at `feasi-frontend/src/components/`. Single-file `Toast.jsx` that BOT-DM can import. Coordinate import path with BOT-DM.
4. **Do not** touch CTAs, card layout, modal, or hooks — those are BOT-DM's and BOT-DT's scope.

### BOT-DT (optional) — Intelligence shell polish (owns `feasi-frontend/src/pages/Intelligence/IntelligenceShell.jsx`)

Only needed if BOT-DI uncovers that the "back to Princeps" flow strands Mission Control over the map. In that case:
1. On the `← Princeps` click, navigate to `/?redesign=1` so the user returns to the redesign workspace rather than the overlay-covered legacy map.
2. Keep the segmented control untouched.

---

## Top-3 sharpest findings (executive)

1. **Site Twin is NOT an orphan** — it's a real route (`/design/:projectId`, real component, real 3D Twin). It's gated on an active project and the gate is silent. Fix is tooltip + nudge, not deletion. File: `feasi-frontend/src/components/shell/Sidebar.jsx:106, 355-360, 413`.
2. **The "Show on Map" failure is a combo of 4 bugs, not 1**: (a) `SLUG_TO_LAYER` misses 4 of 7 map-capable slugs (N-1, EA Flood, MoD, CAA); (b) `nsip` is incorrectly aliased to `repdProjects`; (c) event dispatch in `useDatasetLayer` races provider mount (works-by-URL-fallback-only); (d) even when the layer activates, Mission Control overlay occludes the map so the user sees no change. Fix is cumulative. File: `feasi-frontend/src/SiteContext.jsx:406-426`, `feasi-frontend/src/hooks/useDatasetLayer.js:52-58`, `feasi-frontend/src/App.jsx:955-1003`.
3. **The Datasets page has no user feedback loop** — no toast, no "layer activated" pill, no search, no sort, no deep-link-back. The CTAs are the only interactive points on the page, so when any of them silently fails the whole page feels broken. Minimum fix: one toast primitive + one search input pays for itself twice over.
