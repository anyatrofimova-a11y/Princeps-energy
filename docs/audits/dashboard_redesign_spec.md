# Dashboard Redesign Spec — COUNCIL-5

**Brief:** kill the duplicate-tree / clipping / 9-tab / two-breadcrumb chaos on Projects > Dashboard. Re-use BOT-Z2's `GRID_NATIVE_VIEWS` route-conditional pattern (`feasi-frontend/src/components/shell/AppShell.jsx` L12-20) wholesale.

The screenshot is the `home` workspace, `projects` view — i.e. user clicked "Projects" in the left rail, which mounts `RedesignLayout` underneath `AppShell`'s primary chrome. Every defect cascades from that one mount choice.

## 1. Root-cause map

**Defect 1 — Duplicate project tree**
- Outer (Sidebar embed, 240px): `feasi-frontend/src/components/shell/Sidebar.jsx` L453-489, mounts when `projectsOpen`.
- Inner (RedesignLayout 280px): `feasi-frontend/src/components/shell/RedesignLayout.jsx` L278-288, always mounts.
- `RedesignLayout` is mounted by `feasi-frontend/src/components/workspace/CenterCanvas.jsx` L118-120 when `activeViewMode === "projects"`. The Sidebar embed was added so users could pick projects from anywhere; never gated for the case where the destination view also ships a tree.

**Defect 2 — Left-rail text clipping ("efault Portfolio")**
The clipping is in the embedded Sidebar tree. Three contributing rules:
1. `Sidebar.jsx` L470 — wrapper `<div style={{ flex: 1, display: "flex", minHeight: 0 }}>` is missing `minWidth: 0`. Without it, the inner flex child can't shrink below intrinsic content width.
2. `Sidebar.jsx` L460 — host has `overflow: "hidden"`. Combined with (1), leftmost ~6-10px of every row is clipped.
3. `ProjectTree.jsx` L417-424 — `.pt-row` has `padding: 6px 10px` + `border-left: 3px solid transparent`. The 3px border on broken flex sizing is what visually shaves the first character. `.pt-pf-name` (L448) has `flex: 1` but no `min-width: 0` and no `text-overflow: ellipsis`.

**Defect 3 — 9 tabs in top bar**
`feasi-frontend/src/contexts/WorkspaceContext.jsx` L21:
```
home: ["dashboard", "projects", "pulse", "grid_graph", "curtailment",
       "dc_connection", "neso098", "dc_twin", "map"],
```
Rendered by `feasi-frontend/src/components/workspace/ViewTabs.jsx` mounted at `CenterCanvas.jsx` L93.

**Defect 4 — Two breadcrumb rows**
- "Portfolio > Dashboard" (top): `AppShell.jsx` L76-131, hard-coded JSX, never updates per route.
- "Default Portfolio > Slough Hyperscale DC > Overview": `Breadcrumb.jsx` mounted at `ProjectPage.jsx` L63, dynamic. Same family as the row COUNCIL-2 already flagged "Kill" on Grid Twin.

**Defect 5 — Two semantically overlapping KPI strips**
- Project header metrics: `ProjectHeader.jsx` L64-89 metrics array, rendered L112-114, mounted at `ProjectPage.jsx` L64. DC fields: IT Load · PUE Target · Grid Headroom · Verdict · Stage.
- Hero metric strip: `HeroMetricStrip.jsx`, mounted at `ProjectPage.jsx` L65. Fields: Capacity · IRR · Grid · Planning · LCOE · NPV.
- Overlap: Capacity ↔ IT Load, Grid Headroom MW ↔ Grid status pill. Both occupy the area immediately below project name.

**Defect 6 — Lifecycle sub-tabs** at `ProjectPage.jsx` L17-24. **Keep** — only piece of project-scoped IA in the screenshot that works.

## 2. Die / Merge / Survive

**Die:** AppShell hard-coded breadcrumb + "+ New Project" + bell (`AppShell.jsx` L76-131); Sidebar embedded ProjectTree only when `activeViewMode === "projects"`; top-bar tabs `map` (dup of Sidebar > Map), `dc_twin` (project Operate concern), `grid_graph` (Grid Twin sibling), `curtailment` (Assess-tab concern).

**Merge:** `HeroMetricStrip` into `ProjectHeader` as a single 6-cell strip; verdict moves to title-row chip, stage stays in `.ph-stage-badge`. Top-bar tabs `dc_connection` + `neso098` + `pulse` collapse into Sidebar > Intelligence children (alongside existing Alerts/Dockets/Datasets).

**Survive:** Sidebar (240px), `MarketRibbon` (34px live UK strip), ProjectPage breadcrumb (single source), 6 lifecycle verbs, `ProjectHeader` (merged), `StageRibbon`. Top bar reduced to 3 tabs: Dashboard · Projects · Pulse.

## 3. Priority + dependency order

A: kill AppShell breadcrumb + bell. B: gate Sidebar embed on `activeViewMode === "projects"`. C: ProjectTree clipping CSS (still bites on other routes after B). D: top-bar consolidation. E: KPI merge.

A+B+C are blocking for visual sign-off (everything in the screenshot). D+E are density passes. A+B+C ship as BOT-RR; D+E ship as BOT-SS after RR.

## 4. BOT-RR brief — layout / nav surgery

Files: `Sidebar.jsx`, `AppShell.jsx`, `ProjectTree.jsx`. No new files.

1. `AppShell.jsx` — delete the entire `{!isGridNative && (<div …>Portfolio › Dashboard … bell …</div>)}` at L76-131. Remove now-unused `GRID_NATIVE_VIEWS` set + `isGridNative` boolean (L12-20).
2. `Sidebar.jsx` — derive `const treeIsRedundant = activeViewMode === "projects";` and change L453 condition from `{item.id === "projects" && projectsOpen && (` to `{item.id === "projects" && projectsOpen && !treeIsRedundant && (`.
3. `Sidebar.jsx` L470 — add `minWidth: 0` to the inner div style. Append to L467-469 override block:
   ```css
   .sidebar-project-tree-host .pt-root,
   .sidebar-project-tree-host .pt-scroll,
   .sidebar-project-tree-host .pt-row { min-width: 0; }
   .sidebar-project-tree-host .pt-pf-name,
   .sidebar-project-tree-host .pt-name {
     min-width: 0; white-space: nowrap;
     overflow: hidden; text-overflow: ellipsis;
   }
   ```
4. `ProjectTree.jsx` L448 — set `.pt-pf-name { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }` so bug doesn't bite anywhere else.

**Acceptance:** one breadcrumb, one project tree on `/?view=projects`; embed still works on Map/Grid Twin/Pulse/Mission Control; first character intact at viewport widths down to 1280px.

## 5. BOT-SS brief — top-bar tab consolidation + KPI dedup

Files: `WorkspaceContext.jsx`, `ProjectPage.jsx`, `ProjectHeader.jsx`, `Sidebar.jsx`. No new files. Ships after BOT-RR.

1. `WorkspaceContext.jsx` L21 — `home: ["dashboard", "projects", "pulse"]`. Delete `grid_graph`, `curtailment`, `dc_connection`, `neso098`, `dc_twin`, `map` from this array. Handlers in `CenterCanvas.jsx` L121-138 stay (still reachable via Sidebar / palette / chat).
2. `Sidebar.jsx` `INTEL_CHILDREN` (L104-108) — append three entries (`pulse`, `dc_connection`, `dc_optimiser`) wired to `setActiveViewMode("pulse" | "dc_connection" | "neso098")` in the click handler at L408-411. Use existing `I.dataset` glyph.
3. `ProjectPage.jsx` L65 — delete `<HeroMetricStrip … />` mount.
4. `ProjectHeader.jsx` — `import { deriveKpisFromProject } from "../HeroMetricStrip"` (export it from there; currently module-private). Replace the workload-branched `metrics` array (L64-89) with one workload-agnostic 6-cell schema: Capacity · IRR · Grid · Planning · LCOE · NPV. Move verdict to a `<Pill>` next to `<WorkloadBadge />` on the title row (L94-97). Bump `.ph-metric { min-width: 110px }` to fit 6 cells.

**Acceptance:** `WORKSPACE_VIEWS.home.length === 3`; `ProjectPage` no longer imports `HeroMetricStrip`; Header shows 6 KPI cells + verdict chip on title row; Intelligence dropdown navigates to Pulse / DC Connection / DC Optimiser.

## 6. Out of scope

Backend, MissionControl density, mobile, URL renames, new icon design, Grid Twin / DC Twin overlays.

## 7. File path index

- `feasi-frontend/src/components/shell/AppShell.jsx` (L12-20, L76-131)
- `feasi-frontend/src/components/shell/Sidebar.jsx` (L104-108, L453-489, L460, L467-470)
- `feasi-frontend/src/components/shell/RedesignLayout.jsx` (L278-288)
- `feasi-frontend/src/components/shell/ProjectTree.jsx` (L417-424, L448)
- `feasi-frontend/src/components/shell/ProjectHeader.jsx` (L64-89, L94-97, L112-114)
- `feasi-frontend/src/components/shell/Breadcrumb.jsx`
- `feasi-frontend/src/components/HeroMetricStrip.jsx`
- `feasi-frontend/src/components/workspace/ProjectPage.jsx` (L63-65)
- `feasi-frontend/src/components/workspace/CenterCanvas.jsx` (L93, L118-120)
- `feasi-frontend/src/components/workspace/ViewTabs.jsx`
- `feasi-frontend/src/contexts/WorkspaceContext.jsx` (L21)
