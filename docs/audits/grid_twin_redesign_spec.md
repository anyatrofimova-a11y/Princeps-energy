# Grid Twin Redesign Spec — COUNCIL-2

**Brief:** kill the stacked-nav / floating-modal chaos on Grid Twin.
**Reference aesthetic:** build.inc — one surface, no visible chrome, content is hero.
**Scope:** read-only audit + spec for BOT-Z2. No code edits in this deliverable.

---

## 1. Current-state audit

| # | Layer | Component / file | Mount site | Redundant? | Keep / Kill |
|---|-------|------------------|------------|------------|-------------|
| 0 | "HEADROOM connecting…" ticker | `components/shell/HeadroomTicker.jsx` | `AppShell.jsx` L59 | No — but broken empty state + wrong route | **Kill on Grid Twin** (keep on Mission Control only) |
| 1 | "Portfolio > Dashboard" breadcrumb + "New Project" + bell | inline JSX inside `AppShell.jsx` L62-115 | `AppShell.jsx` | Yes — hard-coded breadcrumb that never updates per route | **Kill** (replace with single dynamic title `Grid Twin · United Kingdom`) |
| 2 | "Dashboard / Projects / Pulse / Grid Graph / Curtailment" tab strip | `components/workspace/ViewTabs.jsx` + `WorkspaceContext.WORKSPACE_VIEWS.home` L21 | `CenterCanvas.jsx` | Yes — these are `home` workspace views but Grid Twin is a **fullscreen overlay** mounted by `GridTwin` in `App.jsx` L764, so these tabs are leaking through from underneath | **Kill for Grid Twin route** (hide AppShell chrome when overlay is open) |
| 3 | "Browse / Map / Graph / Table / Resources" sub-tabs | verb tabs in `WorkspaceRouter`/`ProjectPage` | routed workspace | Yes — same leak, belongs to the *Project* view | **Kill for Grid Twin** |
| 4 | Voltage chips "400kV / 275kV / … / DNO / UKPN / NGED …" | left-over from `DCHyperscalerPanel.jsx` / `MapView.jsx` filter row | mounted when `layers.gridTwin3d` is on in base map | Partially — filters are useful but the full-row chip list is too loud | **Merge into single "Filter" flyout in Grid Twin left rail** |
| 5 | Main Sidebar (Mission Control / Projects / Map / Grid Twin / Chat / Settings) | `components/shell/Sidebar.jsx` | `AppShell.jsx` | No — global nav | **Keep** (but auto-collapse to 48px icon rail when Grid Twin overlay is active) |
| 6 | Portfolio tree (Default Portfolio → Slough DC / Thames BESS) | embedded `ProjectTree` inside Sidebar L289-324 | `Sidebar.jsx` | Yes, on Grid Twin route | **Kill on Grid Twin** — only expand when `active === "projects"` (already gated but renders because `projectsOpen` persists across nav) |
| 7 | "Grid Assets 25,389" asset tree column | `components/grid/GridAssetTree.jsx` (loaded via NESO098 / Grid views) | leaks from sibling workspace | Yes | **Kill on Grid Twin** |
| 8 | "Find a Site" floating modal | `components/TwinSiteFinder.jsx` — `<TwinSiteFinder viewer={…} />` at `GridTwinCesium.jsx` L1157-1162 | Grid Twin | Positioned absolutely with no anchor; state `[open, setOpen] = useState(false)` defaults open on some branches | **Keep but re-anchor** — collapse into a top-left search pill (cmd-K style) that expands inline |
| 9 | Left rail icon strip (`gt2-rail` — Layers / Vision / Satellite / AI Tour / UK / Zoom) | `GridTwinCesium.jsx` L1010-1070 | Grid Twin | No — this is actually the clean pattern we want | **Keep** |
| 10 | Right substation inspector ("Rassau Supergrid Substation" · 2-card dead space) | `GridTwinCesium.jsx` inspected-entity drawer (around the `inspected` state) | Grid Twin | Under-built: renders 2 tiny cards on a 400px-wide column | **Keep but expand** — should be full tabbed drawer (Overview / Capacity / Power Flow / Projects / Connect) |
| 11 | Live bottom strip (Demand 29.5 GW / Wind / Solar) | `components/shell/LiveDataStrip.jsx` | `AppShell.jsx` L123 | Partial — redundant with `gt2-topbar` which already shows demand/gen/util | **Kill on Grid Twin** (topbar already covers it) |
| 12 | "Ask Princeps" bottom-right pill | `ChatRail.jsx` collapsed state | global | No | **Keep** (collapsed) |

### Root cause: "HEADROOMconnecting…"

File: `components/shell/HeadroomTicker.jsx` L32-39.
```
if (error || deltas.length === 0) {
  return (
    <div className="headroom-ticker headroom-ticker-empty">
      <span className="ht-label">HEADROOM</span>
      <span className="ht-muted">{error ? "offline" : "connecting…"}</span>
    </div>
  );
}
```
The two `<span>` are rendered inline-flex with no separator. On a narrow topbar (e.g. because the voltage chip row wraps), they collide visually into `HEADROOMconnecting…`. Also: the ticker fetches `/api/grid/headroom-deltas` which returns empty for first ~2s on cold boot, so the empty-state is hit on **every** page load. Fix: add `gap: 8px` to `.headroom-ticker-empty` (trivial), but better — **do not mount HeadroomTicker on the Grid Twin route at all** since its data already appears in the twin's own topbar.

### Root cause: four stacked nav layers

The AppShell chrome (breadcrumb + HeadroomTicker + LiveDataStrip) is rendered **underneath** the Grid Twin overlay but the overlay is not `position: fixed; inset: 0; z-index: 9999`. It is `position: absolute` inside `.map-area-inner`, so AppShell's top bars render **above** the overlay, and the overlay's own `gt2-topbar` renders **over** the map — producing two topbars stacked. Visual confirm: `App.jsx` L764 mounts `<GridTwin />` inside the AppShell, not as a sibling. Fix: either (a) render Grid Twin as a **full-page route outside AppShell** (like `NOMExplorer`, `SettingsPage`, `PitchPage` which short-circuit at `App.jsx` L442-454), or (b) hide `HeadroomTicker`, breadcrumb bar, and `LiveDataStrip` when `gridTwinOpen === true`.

Recommendation: **(a) — make Grid Twin a top-level route**, matching the NOMExplorer pattern already in place.

---

## 2. build.inc principles (distilled from build.inc landing + Linear / Vercel / Fly)

1. **One primary surface per route.** Build.inc's product pages are a single headline + single hero card. No nested tabs, no stacked strips. Grid Twin should be: map, period.
2. **No stacked horizontal tab sets — ever.** If you need hierarchy, use a command palette or a left rail, not a second row of tabs.
3. **Chrome is invisible until you need it.** Build.inc's header is ~48px. Linear's is ~44px. Our current Grid Twin has ~160px of top chrome stacked.
4. **Primary action is singular.** Build.inc = "Request a Demo." Linear = "Inbox." Grid Twin's primary action should be a single thing: **Find a site → assess headroom.** Everything else secondary.
5. **Content density wins over decoration.** When info does appear (live numbers, substation detail), it's dense, mono-font, and inline — not cards-within-cards.
6. **Drawers, not dialogs.** When users click a substation, content anchors to a right-edge drawer that can go full-width — it never floats as a free-standing card over the map.

---

## 3. Target layout

```
┌────┬───────────────────────────────────────────────────────────────────────────┐
│    │ Grid Twin · United Kingdom           [LIVE 50.01 Hz]  29.5 GW  67%  2024 ▾│  ← 44px single topbar
│ S  ├──────────────┬────────────────────────────────────────────────┬───────────┤
│ I  │              │                                                │           │
│ D  │  [🔍 Find a  │                                                │  ═══════  │
│ E  │    site ⌘K]  │                                                │  Rassau   │
│ B  │              │                                                │  Super-   │
│ A  │  ▣ Layers    │            MAP  (full surface)                 │  grid     │
│ R  │  ◉ Vision    │                                                │           │
│    │  ⊕ Sat       │                                                │  tabs:    │
│(48)│  ⟳ Tour      │                                                │  Overview │
│    │  ⌕ Filter    │                                                │  Capacity │
│    │   ▸ Voltage  │                                                │  Flow     │
│    │   ▸ Operator │                                                │  Projects │
│    │              │                                                │  Connect  │
│    │              │                                                │           │
│    │              │                                                │  (full    │
│    │              │                                                │   tabbed  │
│    │              │                                                │   drawer  │
│    │              │                                                │   only    │
│    │              │                                                │   when a  │
│    │              │                                                │   subst.  │
│    │              │                                                │   selected│
│    │              │                                                │   )       │
│    │              │                                                │           │
│    └──────────────┴────────────────────────────────────────────────┴───────────┘
│                                                            [ Ask Princeps ▾ ]
└────────────────────────────────────────────────────────────────────────────────┘
```

- **Sidebar (48px)**: global icons only. No portfolio tree, no project tree, no breadcrumb. Only expands on hover or `⌘B`.
- **Topbar (44px)**: `Grid Twin · United Kingdom` title • LIVE pill • 3 mono KPIs (demand, util, freq) • scenario year dropdown • close. Nothing else.
- **Left rail (56px)**: icons only — Layers / Vision / Satellite / Tour / **Filter** (new, swallows the voltage + DNO chips) / UK-view / Zoom-to.
- **Map (remaining full viewport)**: map is the hero. Drawing tools surface only when user presses `D`.
- **Find a site (top-left floating pill)**: collapsed by default as a 220×36 search bar with `⌘K` hint. Expands in place to a 3-tab (Search / Coords / Pin) inline popover. Never a free-floating modal.
- **Right drawer (420px default, expandable to 720px)**: only renders when `inspected != null`. Tabbed: **Overview / Capacity / Power Flow / Projects / Connect**. Empty state = drawer is not mounted at all.
- **No bottom strip.** Already in topbar.
- **Chat**: existing collapsed `Ask Princeps` pill. Untouched.

---

## 4. Per-problem fix

| Problem | Fix |
|---|---|
| 4 stacked nav layers | Move Grid Twin to a top-level route (like `NOMExplorer`) — short-circuit `App.jsx` before AppShell renders. Unmounts `HeadroomTicker`, breadcrumb, `LiveDataStrip`, `ViewTabs`, portfolio tree in one move. |
| "HEADROOMconnecting…" | Root cause = missing `gap` + empty fetch on cold boot. But the real fix is: **do not mount HeadroomTicker on Grid Twin.** If kept elsewhere, add `gap: 8px` to `.headroom-ticker-empty` and change string to `Loading…`. |
| Find-a-Site floating modal | Re-anchor to top-left of map surface (16px from top, 72px from left — sits right of the left rail). Collapsed pill pattern. Expanded popover stays anchored, never floats free. Auto-close on blur + Escape. |
| Left panel competition | `Sidebar.jsx` already supports collapsed mode; force-collapse when `gridTwinOpen === true`. `ProjectTree` and `GridAssetTree` are in sibling workspaces and will disappear automatically once Grid Twin is a top-level route. |
| Right substation panel too empty | Kill the 2-card placeholder layout. Replace with tabbed drawer using tab pattern from `GridConnectionPanel.jsx`: Overview (headroom, voltage, operator, last updated), Capacity (demand/gen headroom sparkline), Power Flow (link to pandapower run), Projects (ECR queue for this substation), Connect (cost estimate + CTA). Default width 420px, user can drag to 720px. |
| Live bottom strip | Kill on Grid Twin. Topbar already has demand/gen/util/freq. |
| Voltage + DNO filter chips | Consolidate into left-rail **Filter** flyout. Two sections: Voltage (400/275/132/66/33/22/11 checkboxes), Operator (DNO chips). State persists per session. |

---

## 5. Typography + palette

Reuse existing tokens from `Sidebar.jsx`:
```
gold:        #C9A64B
goldStrong:  #B5912F
goldSurface: rgba(201,166,75,0.10)
ink:         #1a1a1a
secondary:   #6B6560
tertiary:    #9C9590
border:      #E8E5DF
card:        #FFFFFF
bg:          #F7F8FA
```
Grid Twin runs on a **dark map**, so mirror palette:
```
twinBg:     #0B0E13
twinPanel:  #12151C   (drawer background, matches PulseWorkspace.panel)
twinBorder: rgba(255,255,255,0.08)
twinText:   #E8E5DF
twinDim:    #9C9590
gold:       #C9A64B   (primary accent — unchanged)
live:       #10B981   (green dot / positive deltas)
warn:       #F59E0B
crit:       #EF4444
```

Type scale (DM Sans + JetBrains Mono for numerics):
| Token | Font | Size / weight | Use |
|---|---|---|---|
| display | DM Sans | 20 / 700 | drawer title (substation name) |
| title   | DM Sans | 14 / 600 | topbar title, drawer tab label |
| body    | DM Sans | 13 / 500 | layer labels, menu items |
| caption | DM Sans | 11 / 500, letter-spacing .04em, uppercase | section labels ("CAPACITY", "PROJECTS") |
| mono-l  | JB Mono | 16 / 700 | topbar KPI values |
| mono-s  | JB Mono | 11 / 600 | drawer numeric cells |

---

## 6. Deliverables for BOT-Z2

Concrete file-level change list — **scope all in `feasi-frontend/src/`**:

1. **`App.jsx`** — add Grid Twin to the full-screen overlay short-circuit (L442-454). When `gridTwinOpen === true`, render `<GridTwin onClose={…} />` instead of `AppShell`. This unmounts HeadroomTicker / LiveDataStrip / breadcrumb / ViewTabs in one change.
2. **`components/shell/AppShell.jsx`** — remove the hard-coded "Portfolio > Dashboard" breadcrumb div (L62-115). Replace with a dynamic `<RouteTitle />` slot that routes pass into. AppShell still runs for other routes.
3. **`components/shell/HeadroomTicker.jsx`** — add `gap: 8px` to `.headroom-ticker-empty`, change copy to `Loading…`. Not mounted on Grid Twin (handled via step 1).
4. **`components/GridTwinCesium.jsx`**
   - topbar (L969-1007): keep but swap "PRINCEPS · DIGITAL TWIN" badges for single title `Grid Twin · United Kingdom`.
   - Add `onClose` → route back to Mission Control. Wire ⌘W / Esc.
   - Left rail (L1010-1070): add `Filter` icon between Satellite and AI-Tour. Flyout hosts voltage + DNO multiselect (consolidates the chip strip).
   - Remove the standalone `<TwinSiteFinder />` mount (L1157-1162) and replace with a new `TwinSiteFinderPill` anchored top-left at `{ top: 16, left: 72 }`. Collapsed-by-default, 220×36.
5. **`components/TwinSiteFinder.jsx`** — convert from floating modal to **inline collapsible pill**. Default state `open: false`. Expand in place, never render as a dialog. Add `Escape` + outside-click to collapse.
6. **New `components/grid-twin/SubstationDrawer.jsx`** — tabbed full-height right drawer. Replaces the 2-card dead space. Tabs: Overview / Capacity / Power Flow / Projects / Connect. Mount only when `inspected != null`. 420-720px resizable.
7. **`components/grid/GridAssetTree.jsx`** — no code change; will simply not render when Grid Twin is routed outside AppShell.
8. **`components/shell/Sidebar.jsx`** — auto-collapse to 48px icon-only mode when `workspace.activeRoute === "gridtwin"`. Existing `projectsOpen` state should reset to `false` on route change (currently persists).
9. **`styles.css`** — add `.gt2-topbar` gap rule; add `.twin-drawer`, `.twin-finder-pill` classes matching palette in §5.

### Acceptance criteria

- Only **one** horizontal bar at top of Grid Twin (the 44px `gt2-topbar`).
- No breadcrumb, no HeadroomTicker, no LiveDataStrip on Grid Twin route.
- No portfolio tree, no Grid Assets tree visible on Grid Twin.
- Find-a-site is a single top-left pill, not a floating card.
- Right drawer only appears on selection, and when it appears it is full-height with at least 4 tabs.
- No text reads `HEADROOMconnecting…` anywhere.

### Out of scope

- Power-flow engine / data pipelines / backend.
- Other routes' chrome (Mission Control, Projects, Pulse) — address in separate pass.
- Mobile / small-screen layout.

---

*Spec authored by COUNCIL-2 · 2026-04-19 · read-only audit, no code edits made.*
