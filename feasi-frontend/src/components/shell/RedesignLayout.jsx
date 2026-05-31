import React, { useState, useEffect, useCallback, useRef } from "react";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import ProjectTree from "./ProjectTree";
// ChatRail moved to global mount in App.jsx (2026-04-19 chat consolidation)
import ProjectPage from "../workspace/ProjectPage";
import NewProjectModal from "../workspace/NewProjectModal";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { useSite } from "../../SiteContext";
import {
  getPortfolioTree,
  listCandidateSites,
  getProject,
} from "../../services/portfolios";

// Map AppShell-sidebar navigation signals to the verb-based tabs
// (Overview · Discover · Assess · Decide · File · Operate). Each sidebar
// click routes to the verb that actually hosts the relevant panel so the
// user lands where the content lives.
const INTENT_TO_TAB = {
  // Assess hosts GridTab + DemandForecastPanel + PlanningIntelligencePanel
  grid_connection: "assess",
  grid_study: "assess",
  advanced_grid: "assess",
  grid_efficiency: "assess",
  planning: "assess",
  demand_forecast: "assess",
  feasibility: "assess",
  satellite_analysis: "assess",
  environmental: "assess",
  terrain_analysis: "assess",
  yield_assessment: "assess",
  // Decide hosts COAMatrix + FinancialModelPanel
  financial: "decide",
  bess_optimisation: "decide",
  investment_readiness: "decide",
  portfolio_optimisation: "decide",
  // Discover hosts site prospector + candidate sites + map
  site_prospecting: "discover",
  prospector_v2: "discover",
  dc_colocation: "discover",
  // File hosts planning artefacts, reports, consents
  report_generation: "file",
  document_automation: "file",
  // Operate hosts post-commission ops
  dispatch_optimisation: "operate",
  route_to_market: "operate",
  construction_timeline: "operate",
  ppa_origination: "operate",
  legacy_compliance: "operate",
};

// When the routed tab has internal sub-tabs (currently only Assess), pass a
// hint so the sidebar lands on the right engineering section. Values must
// match the sub-tab keys inside the verb tab (AssessTab: grid / demand /
// planning / dispatch / yield / cooling / turbines).
const INTENT_TO_SUBTAB = {
  grid_connection: "grid",
  grid_study: "grid",
  advanced_grid: "grid",
  grid_efficiency: "grid",
  planning: "planning",
  demand_forecast: "demand",
  yield_assessment: "yield",
  bess_optimisation: "dispatch",
  dispatch_optimisation: "dispatch",
};

const VIEWMODE_TO_TAB = {
  map: "overview",
  dashboard: "overview",
  projects: "overview",
  chart: "assess",
  table: "discover",
  forecast: "assess",
  grid_graph: "assess",
  network: "assess",
};

/**
 * RedesignLayout — the Gallatin-inspired project-first IA.
 * Mounted by App.jsx when `?redesign=1` is present.
 *
 * Composition:
 *   [ ProjectTree 280px ] [ ProjectPage (flex) ] [ ChatRail 360/48px ]
 */
export default function RedesignLayout({ actions = null, mapSlot = null, onViewMap = null }) {
  const workspace = useWorkspace();
  const site = useSite();
  const [tree, setTree] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [selectedPortfolioId, setSelectedPortfolioId] = useState(null);
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [activeSubTab, setActiveSubTab] = useState(null);

  const [project, setProject] = useState(null);
  const [sites, setSites] = useState([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardPortfolioId, setWizardPortfolioId] = useState(null);
  // Stage filter pushed by Dashboard's "Stage funnel" rows. When set, the
  // overview pane should show projects at this stage sorted by recency.
  const [stageFilter, setStageFilter] = useState(null);
  const [stageFilterLabel, setStageFilterLabel] = useState(null);
  // Ref holds the latest tree so event handlers (attached once) read fresh data.
  const treeRef = useRef([]);

  const reloadTree = useCallback(async () => {
    setLoading(true); setLoadError(null);
    try {
      const data = await getPortfolioTree();
      const list = data.portfolios || [];
      setTree(list);
      treeRef.current = list;
      // Resolve any existing selection (URL ?project= or a runtime pick) against
      // the loaded tree so we land on the right portfolio. Only fall back to
      // auto-selecting the first project when no selection is in flight.
      const urlPid = new URLSearchParams(window.location.search).get("project");
      const targetPid = selectedProjectId || urlPid;
      if (targetPid) {
        for (const pf of list) {
          const hit = (pf.projects || []).find((p) => p.project_id === targetPid);
          if (hit) {
            setSelectedPortfolioId(pf.portfolio_id);
            setSelectedProjectId(targetPid);
            return;
          }
        }
      }
      // No matching selection — auto-select the first portfolio's first project.
      if (list.length > 0 && !selectedPortfolioId) {
        const pf = list[0];
        setSelectedPortfolioId(pf.portfolio_id);
        if (pf.projects && pf.projects.length > 0) {
          setSelectedProjectId(pf.projects[0].project_id);
        }
      }
    } catch (e) {
      setLoadError(e.message || "Failed to load portfolios");
    } finally {
      setLoading(false);
    }
  }, [selectedPortfolioId, selectedProjectId]);

  useEffect(() => { reloadTree(); }, []); // eslint-disable-line

  // On mount, honour ?project=<id> from the URL (set by Mission Control
  // when the user picked a row there). Also listen for runtime events
  // from App.jsx so clicks arrive even without a reload.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const pid = params.get("project");
    if (pid) {
      setSelectedProjectId(pid);
      setActiveTab("overview");
    }
    // Pick up a pending selection stashed by CenterCanvas before mount.
    try {
      const pending = sessionStorage.getItem("princeps.pendingProjectId");
      if (pending) {
        sessionStorage.removeItem("princeps.pendingProjectId");
        setSelectedProjectId(pending);
        setActiveTab("overview");
      }
      const pendingNew = sessionStorage.getItem("princeps.pendingNewProject");
      if (pendingNew) {
        sessionStorage.removeItem("princeps.pendingNewProject");
        setWizardPortfolioId(selectedPortfolioId);
        setWizardOpen(true);
      }
    } catch {}
    const onSelect = (e) => {
      const id = e.detail?.projectId;
      if (!id) return;
      setSelectedProjectId(id);
      setActiveTab("overview");
      // Resolve portfolio from the latest tree (via ref to avoid stale closure).
      for (const pf of treeRef.current) {
        if ((pf.projects || []).some((p) => p.project_id === id)) {
          setSelectedPortfolioId(pf.portfolio_id);
          break;
        }
      }
    };
    const onNew = (e) => {
      setWizardPortfolioId(selectedPortfolioId);
      setWizardOpen(true);
    };
    // DC twin "Draw polygon in Site Designer →" CTA — switch to Discover tab
    // where DesignCanvas is mounted; coords ride along on the event so the
    // canvas can seed itself with the picked location.
    const onOpenDesigner = (e) => {
      setActiveTab("discover");
      try {
        sessionStorage.setItem("princeps.designSeed", JSON.stringify(e.detail || {}));
      } catch {}
    };
    // Pending stage filter stashed by CenterCanvas (Dashboard funnel click).
    try {
      const pendingStage = sessionStorage.getItem("princeps.pendingStageFilter");
      const pendingLabel = sessionStorage.getItem("princeps.pendingStageLabel");
      if (pendingStage) {
        sessionStorage.removeItem("princeps.pendingStageFilter");
        sessionStorage.removeItem("princeps.pendingStageLabel");
        setStageFilter(pendingStage);
        setStageFilterLabel(pendingLabel || pendingStage);
        setSelectedProjectId(null);
        setActiveTab("overview");
      }
    } catch {}
    const onStageFilter = (e) => {
      const stage = e.detail?.stage;
      if (!stage) return;
      setStageFilter(stage);
      setStageFilterLabel(e.detail?.label || stage);
      setSelectedProjectId(null);
      setActiveTab("overview");
    };
    window.addEventListener("princeps-redesign-select-project", onSelect);
    window.addEventListener("princeps-redesign-new-project", onNew);
    window.addEventListener("princeps-open-site-designer", onOpenDesigner);
    window.addEventListener("princeps-redesign-filter-stage", onStageFilter);
    return () => {
      window.removeEventListener("princeps-redesign-select-project", onSelect);
      window.removeEventListener("princeps-redesign-new-project", onNew);
      window.removeEventListener("princeps-open-site-designer", onOpenDesigner);
      window.removeEventListener("princeps-redesign-filter-stage", onStageFilter);
    };
  }, [selectedPortfolioId]);

  // Bridge AppShell sidebar → redesign tabs. When the sidebar's PORTFOLIO /
  // ANALYSIS items are clicked they set the workspace / intent / viewMode on
  // WorkspaceContext; we observe those and switch tabs accordingly.
  useEffect(() => {
    if (!workspace) return;
    const { activeWorkspace, activeViewMode } = workspace;
    const activeIntent = site?.activeIntent;
    if (activeIntent && INTENT_TO_TAB[activeIntent]) {
      setActiveTab(INTENT_TO_TAB[activeIntent]);
      // Pass sub-tab hint so e.g. Grid Connection → Assess/grid, not Assess/default
      setActiveSubTab(INTENT_TO_SUBTAB[activeIntent] || null);
      return;
    }
    if (activeViewMode && VIEWMODE_TO_TAB[activeViewMode]) {
      setActiveTab(VIEWMODE_TO_TAB[activeViewMode]);
      setActiveSubTab(null);
    }
  }, [workspace?.activeWorkspace, workspace?.activeViewMode, site?.activeIntent]); // eslint-disable-line

  // Load project + candidate sites whenever selection changes.
  // allSettled (not all) — a flaky /candidate-sites shouldn't block the page
  // from rendering the project record we already fetched successfully.
  useEffect(() => {
    if (!selectedProjectId) { setProject(null); setSites([]); setLoadError(null); return; }
    let cancelled = false;
    setLoadError(null);
    (async () => {
      const [projRes, candRes] = await Promise.allSettled([
        getProject(selectedProjectId),
        listCandidateSites(selectedProjectId),
      ]);
      if (cancelled) return;
      if (projRes.status === "fulfilled" && projRes.value) {
        setProject(projRes.value);
      } else {
        console.warn("[RedesignLayout] getProject failed", selectedProjectId, projRes.reason);
        setProject(null);
        setLoadError(projRes.reason?.message || "Failed to load project");
      }
      if (candRes.status === "fulfilled" && candRes.value) {
        setSites(candRes.value.candidates || []);
      } else {
        console.warn("[RedesignLayout] listCandidateSites failed", selectedProjectId, candRes.reason);
        setSites([]);  // render project without candidates rather than the whole page breaking
      }
    })();
    return () => { cancelled = true; };
  }, [selectedProjectId]);

  // Current portfolio object for breadcrumb / header
  const currentPortfolio = tree.find((p) => p.portfolio_id === selectedPortfolioId) || null;

  const onSelectProject = useCallback((projectId, portfolioId) => {
    setSelectedProjectId(projectId);
    setSelectedCandidateId(null);
    if (portfolioId) setSelectedPortfolioId(portfolioId);
    setActiveTab("overview");
  }, []);

  const onSelectSite = useCallback((candidateId, projectId, portfolioId) => {
    setSelectedCandidateId(candidateId);
    if (projectId) setSelectedProjectId(projectId);
    if (portfolioId) setSelectedPortfolioId(portfolioId);
    setActiveTab("sites");
  }, []);

  const onNewProject = useCallback((portfolioId) => {
    setWizardPortfolioId(portfolioId);
    setWizardOpen(true);
  }, []);

  const onCreated = useCallback(async (newProjectId) => {
    await reloadTree();
    setSelectedProjectId(newProjectId);
    setActiveTab("overview");
  }, [reloadTree]);

  const onPopOutTwin = () => {
    window.open("?grid-twin=1", "_blank");
  };

  // Project tree is only relevant on the Projects view. On Map / Grid Twin /
  // Pulse / DC Twin / Dashboard routes the tree just wastes a ~60-80px column
  // (even when collapsed the chevron-stub leaks through) and crushes the
  // ProjectPage header. BOT-LX 2026-04-19: gate the PanelGroup on
  // activeViewMode === "projects" and otherwise render the center pane at
  // full width.
  // Auto-collapse tree pane at narrow viewports (below 1400px total). The
  // Sidebar itself is 240px fixed; leaving room for a ~240px tree plus the
  // project page crushes the content. Only show the secondary tree on wide
  // screens — the Sidebar's Projects row expander is sufficient on narrow.
  const [isNarrow, setIsNarrow] = useState(() =>
    typeof window !== "undefined" && window.innerWidth < 1400
  );
  useEffect(() => {
    const onResize = () => setIsNarrow(window.innerWidth < 1400);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // showTreePane disabled 2026-05-31 — the resizable side tree kept
  // squashing under ~80px regardless of minSize (autoSave race during
  // mount), wasn't reachable from a fresh viewport, and duplicated the
  // sidebar's Projects expander. Projects are now selected from the
  // sidebar OR via the project picker rendered in the empty workspace.
  const showTreePane = false;

  // ── Stage funnel filter view ──────────────────────────────────────
  // When the user clicks a row in Dashboard's "Stage funnel" we land here
  // with stageFilter set + no selectedProjectId. Render a sortable list
  // of matching projects across all portfolios; clicking a project opens
  // it (which clears the filter via setSelectedProjectId).
  const stageFilterMatches = React.useMemo(() => {
    if (!stageFilter) return null;
    const norm = String(stageFilter).toLowerCase();
    const out = [];
    for (const pf of (tree || [])) {
      for (const p of (pf.projects || [])) {
        if (String(p.stage || "").toLowerCase() === norm) {
          out.push({
            ...p,
            portfolio_id: pf.portfolio_id,
            portfolio_name: pf.portfolio_name || pf.name,
          });
        }
      }
    }
    out.sort((a, b) => {
      const ta = a.stage_entered_at || a.updated_at || a.created_at || "";
      const tb = b.stage_entered_at || b.updated_at || b.created_at || "";
      return String(tb).localeCompare(String(ta));
    });
    return out;
  }, [tree, stageFilter]);

  const centerPane = (
    <div className="rd-center">
      {loading && !project ? (
        <div className="rd-loading">Loading portfolios…</div>
      ) : loadError ? (
        <div className="rd-error">
          <div className="rd-error-title">Could not load</div>
          <div className="rd-error-sub">{loadError}</div>
          <button className="rd-retry" onClick={reloadTree}>Retry</button>
        </div>
      ) : (stageFilter && stageFilterMatches && !selectedProjectId) ? (
        <div className="rd-stage-list">
          <header className="rd-stage-list-head">
            <div>
              <div className="rd-stage-list-eyebrow">FILTERED BY STAGE</div>
              <h2 className="rd-stage-list-title">
                {stageFilterLabel || stageFilter}
                <span className="rd-stage-list-count"> · {stageFilterMatches.length}</span>
              </h2>
            </div>
            <button
              className="rd-stage-list-clear"
              onClick={() => { setStageFilter(null); setStageFilterLabel(null); }}
            >Clear filter</button>
          </header>
          {stageFilterMatches.length === 0 ? (
            <div className="rd-stage-list-empty">
              No projects at this stage yet.
            </div>
          ) : (
            <ul className="rd-stage-list-rows">
              {stageFilterMatches.map((p) => (
                <li
                  key={p.project_id}
                  className="rd-stage-list-row"
                  onClick={() => {
                    setSelectedPortfolioId(p.portfolio_id);
                    setSelectedProjectId(p.project_id);
                    setActiveTab("overview");
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <div className="rd-stage-list-row-main">
                    <span className="rd-stage-list-row-name">{p.name || p.project_id}</span>
                    <span className="rd-stage-list-row-meta">
                      {p.technology || ""}{p.capacity_mw ? ` · ${p.capacity_mw} MW` : ""}
                      {p.portfolio_name ? ` · ${p.portfolio_name}` : ""}
                    </span>
                  </div>
                  <span className="rd-stage-list-row-date">
                    {p.stage_entered_at ? new Date(p.stage_entered_at).toLocaleDateString() : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <ProjectPage
          portfolio={currentPortfolio}
          project={project}
          sites={sites}
          activeTab={activeTab}
          activeSubTab={activeSubTab}
          onTabChange={(t) => { setActiveTab(t); setActiveSubTab(null); }}
          onPopOutTwin={actions?.gridTwin || onPopOutTwin}
          onAddCandidate={() => onNewProject(selectedPortfolioId)}
          onSelectSite={(s) => setSelectedCandidateId(s.candidate_id)}
          actions={actions}
          mapSlot={activeTab === "overview" ? mapSlot : null}
          onViewMap={onViewMap || (() => {})}
          onNavigate={(href) => {
            if (!href) return;
            const match = href.match(/\/p\/([^/]+)(?:\/project\/([^/]+))?/);
            if (match) {
              setSelectedPortfolioId(match[1]);
              setSelectedProjectId(match[2] || null);
            }
          }}
        />
      )}
    </div>
  );

  return (
    <div className="rd-root">
      {showTreePane ? (
        /* Resizable + collapsible split between project tree and main canvas.
           Sizes persist to localStorage via autoSaveId. Drag the gold rule to
           resize; double-click to snap-collapse the project tree. */
        <PanelGroup
          direction="horizontal"
          /* v4 invalidates v3 — v3 still let the panel fall under its own
             minSize on resize-during-mount when the viewport was narrow,
             leaving the empty-state truncated to "No por Cre or". v4
             bumps the floor to 28% and rewrites the empty state to fit
             smaller widths cleanly. */
          autoSaveId="princeps-rd-layout-v4"
          style={{ height: "100%", width: "100%" }}
        >
          <Panel
            id="rd-tree"
            order={1}
            defaultSize={30}
            minSize={28}
            maxSize={44}
            collapsible
            collapsedSize={0}
            className="rd-pane rd-pane-tree"
          >
            <ProjectTree
              portfolios={tree}
              selectedPortfolioId={selectedPortfolioId}
              selectedProjectId={selectedProjectId}
              selectedSiteId={selectedCandidateId}
              onSelectPortfolio={setSelectedPortfolioId}
              onSelectProject={onSelectProject}
              onSelectSite={onSelectSite}
              onNewProject={onNewProject}
              onNewPortfolio={() => { /* TODO: portfolio create modal */ }}
            />
          </Panel>

          <PanelResizeHandle className="rd-resize-handle" />

          <Panel id="rd-center" order={2} defaultSize={80} minSize={50}>
            {centerPane}
          </Panel>
        </PanelGroup>
      ) : (
        /* Non-Projects routes: render the center pane full-width. Tree is
           still reachable from the Sidebar's Projects row expander. */
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex" }}>
          {centerPane}
        </div>
      )}

      {/* ChatRail mounted globally in App.jsx (2026-04-19 chat consolidation).
          Project context flows via window event 'princeps-chat-context'. */}

      <NewProjectModal
        isOpen={wizardOpen}
        onClose={() => setWizardOpen(false)}
        portfolioId={wizardPortfolioId}
        onCreated={onCreated}
      />

      <style>{`
        .rd-root {
          display: flex;
          width: 100%; height: 100%;
          background: var(--bg);
          overflow: hidden;
          flex: 1; min-height: 0;
        }
        .rd-pane {
          height: 100%;
          overflow: hidden;
          min-width: 0;
        }
        /* Override ProjectTree's hard-coded 280px root width so it fills the
           resizable Panel instead of clipping at the panel boundary. */
        .rd-pane-tree { background: var(--surface, #fff); }
        .rd-pane-tree .pt-root,
        .rd-pane-tree .pt-scroll,
        .rd-pane-tree .pt-row { min-width: 0; }
        .rd-pane-tree .pt-root { width: 100%; }
        .rd-pane-tree .pt-pf-name,
        .rd-pane-tree .pt-name {
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        /* Drag handle — thin gold rule. Hover/active widens it slightly so
           it's hit-friendly but quiet at rest. */
        .rd-resize-handle {
          width: 4px;
          flex-shrink: 0;
          background: transparent;
          border-left: 1px solid var(--cds-border-subtle, #e8e5df);
          cursor: col-resize;
          transition: background 120ms ease, border-color 120ms ease;
          position: relative;
        }
        .rd-resize-handle:hover {
          background: rgba(201, 166, 75, 0.12);
          border-left-color: #C9A64B;
        }
        .rd-resize-handle[data-resize-handle-active] {
          background: rgba(201, 166, 75, 0.22);
          border-left-color: #A88732;
        }
        /* Collapsed-tree affordance: when the tree panel is collapsed the
           resize handle is the only thing the user sees on the left edge,
           so make it a touch wider on hover so it's discoverable. */
        .rd-resize-handle:hover { width: 5px; }
        .rd-center {
          flex: 1; min-width: 0; min-height: 0;
          display: flex; flex-direction: column;
          height: 100%;
        }
        .rd-loading, .rd-error {
          flex: 1;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: var(--cds-text-helper);
          padding: 40px;
          gap: 8px;
        }
        .rd-error-title {
          font-size: 16px; font-weight: 700;
          color: var(--cds-text-primary);
        }
        .rd-error-sub {
          font-size: 13px;
          font-family: var(--mono);
          max-width: 480px;
          text-align: center;
        }
        .rd-retry {
          margin-top: 12px;
          padding: 8px 16px;
          background: var(--gold);
          color: #fff;
          border: none; border-radius: 8px;
          font-family: inherit; font-weight: 600; font-size: 13px;
          cursor: pointer;
        }
        .rd-retry:hover { background: var(--gold-dark); }
      `}</style>
    </div>
  );
}
