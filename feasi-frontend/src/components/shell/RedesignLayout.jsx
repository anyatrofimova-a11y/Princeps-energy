import React, { useState, useEffect, useCallback } from "react";
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

  const reloadTree = useCallback(async () => {
    setLoading(true); setLoadError(null);
    try {
      const data = await getPortfolioTree();
      const list = data.portfolios || [];
      setTree(list);
      // Auto-select first portfolio + first project on initial load
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
  }, [selectedPortfolioId]);

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
    const onSelect = (e) => {
      const id = e.detail?.projectId;
      if (id) {
        setSelectedProjectId(id);
        setActiveTab("overview");
      }
    };
    const onNew = (e) => {
      setWizardPortfolioId(selectedPortfolioId);
      setWizardOpen(true);
    };
    window.addEventListener("princeps-redesign-select-project", onSelect);
    window.addEventListener("princeps-redesign-new-project", onNew);
    return () => {
      window.removeEventListener("princeps-redesign-select-project", onSelect);
      window.removeEventListener("princeps-redesign-new-project", onNew);
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

  // Load project + candidate sites whenever selection changes
  useEffect(() => {
    if (!selectedProjectId) { setProject(null); setSites([]); return; }
    let cancelled = false;
    (async () => {
      try {
        const [proj, cand] = await Promise.all([
          getProject(selectedProjectId),
          listCandidateSites(selectedProjectId),
        ]);
        if (cancelled) return;
        setProject(proj);
        setSites(cand.candidates || []);
      } catch (e) {
        if (!cancelled) setLoadError(e.message || "Failed to load project");
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

  return (
    <div className="rd-root">
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

      <div className="rd-center">
        {loading && !project ? (
          <div className="rd-loading">Loading portfolios…</div>
        ) : loadError ? (
          <div className="rd-error">
            <div className="rd-error-title">Could not load</div>
            <div className="rd-error-sub">{loadError}</div>
            <button className="rd-retry" onClick={reloadTree}>Retry</button>
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
            mapSlot={(activeTab === "overview" || activeTab === "discover") ? mapSlot : null}
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
        .rd-center {
          flex: 1; min-width: 0; min-height: 0;
          display: flex; flex-direction: column;
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
