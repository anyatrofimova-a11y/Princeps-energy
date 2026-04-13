import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";

const WorkspaceContext = createContext(null);

export const WORKSPACES = [
  { id: "home",     label: "Home",     icon: "home" },
  { id: "analyse",  label: "Analyse",  icon: "bolt" },
  { id: "design",   label: "Design",   icon: "sun" },
  { id: "pipeline", label: "Pipeline", icon: "briefcase" },
];

// Legacy workspace aliases — map old IDs to new ones
export const WORKSPACE_ALIASES = {
  grid: "analyse", feasibility: "analyse", environment: "analyse",
  operations: "design", investment: "comply",
};

// Per-workspace view configurations
export const WORKSPACE_VIEWS = {
  home:    ["dashboard", "projects", "pulse", "grid_graph", "curtailment", "dc_connection", "neso098", "dc_twin", "map"],
  analyse: ["map", "grid_graph", "network", "forecast", "table", "chart", "curtailment"],
  design:  ["map", "table", "chart", "dc_connection", "dc_twin"],
  comply:  ["dashboard", "table"],
};

export const WORKSPACE_DEFAULTS = {
  home:    { intent: null,          viewMode: "dashboard" },
  analyse: { intent: "feasibility", viewMode: "map" },
  design:  { intent: "dispatch_optimisation", viewMode: "map" },
  comply:  { intent: "investment_readiness",  viewMode: "dashboard" },
};

// Maps each workspace to the intents it contains
export const WORKSPACE_INTENTS = {
  home:    [],
  analyse: [
    "feasibility", "grid_study", "grid_connection", "demand_forecast", "advanced_grid", "grid_efficiency",
    "financial", "bess_optimisation", "satellite_analysis", "environmental", "planning", "legacy_compliance",
    "terrain_analysis", "electrical_design",
    "yield_assessment", "cable_routing",
  ],
  design:  ["connection_strategy", "dispatch_optimisation", "route_to_market", "sustainability",
    "report_generation", "document_automation", "construction_timeline"],
  pipeline: ["portfolio_optimisation"],
  comply:  ["investment_readiness"],
};

// Maps intent → detailSection for deep-dive panels
export const INTENT_DETAIL_MAP = {
  grid_connection:       "connection",
  demand_forecast:       "demand",
  advanced_grid:         "advanced",
  connection_strategy:   "strategy",
  dispatch_optimisation: "dispatch",
  route_to_market:       "rtm",
  sustainability:        "sustainability",
  investment_readiness:  "investment",
  financial:            "financial",
  site_prospecting:     "prospector",
  dc_colocation:        "datacentre",
  council_search:       "council",
  planning:             "planning",
  bess_optimisation:    "bess",
  portfolio_optimisation: "portfolio",
  cable_routing:        "cablerouting",
  yield_assessment:     "yield",
  construction_timeline: "construction",
  ppa_origination:      "ppa",
  workflow_engine:       "workflow",
  assessment_snapshot:   "snapshot",
  export_hub:            "export",
  alert_rules:           "alerts",
  prospector_v2:         "prospector_v2",
  terrain_analysis:      "terrain",
  report_generation:     "reports",
  electrical_design:     "electrical",
  document_automation:   "documents",
};

export function WorkspaceProvider({ children }) {
  const [activeWorkspace, setActiveWorkspaceRaw] = useState("home");
  const [activeViewMode, setActiveViewMode] = useState(WORKSPACE_DEFAULTS.home.viewMode);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailSection, setDetailSection] = useState("cards"); // "cards" | deep-dive key

  const site = useSite();

  const setActiveWorkspace = useCallback((ws) => {
    setActiveWorkspaceRaw(ws);
    const defaults = WORKSPACE_DEFAULTS[ws];
    if (defaults) {
      setActiveViewMode(defaults.viewMode);
      if (defaults.intent) {
        site.setActiveIntent(defaults.intent);
        site.setStudySubStep(defaults.intent);
      }
    }
    // Reset detail to cards when switching workspace
    setDetailSection("cards");
  }, [site]);

  // Navigate to a specific intent within a workspace
  const navigateToIntent = useCallback((intent) => {
    site.setActiveIntent(intent);
    site.setStudySubStep(intent);
    // Auto-open deep-dive section if mapped
    const section = INTENT_DETAIL_MAP[intent];
    if (section) {
      setDetailSection(section);
      setDetailOpen(true);
    } else {
      setDetailSection("cards");
    }
    // Auto-enable relevant layers
    if (intent === "grid_connection") {
      site.setLayers(prev => ({ ...prev, gridCapacity: true }));
    }
    if (intent === "demand_forecast") {
      site.setLayers(prev => ({ ...prev, demandGsps: true }));
    }
  }, [site]);

  const toggleBrowser = useCallback(() => setBrowserOpen(p => !p), []);
  const toggleDetail = useCallback(() => setDetailOpen(p => !p), []);

  // Auto-switch workspace when transitioning from site → study
  useEffect(() => {
    if (site.workflowStage === "study") {
      setBrowserOpen(true);
      if (activeWorkspace === "home") setActiveWorkspace("analyse");
      // Detail panel stays closed — user opens via Ctrl+D or clicking analysis
    }
  }, [site.workflowStage]);

  const value = {
    activeWorkspace, setActiveWorkspace,
    activeViewMode, setActiveViewMode,
    browserOpen, setBrowserOpen, toggleBrowser,
    detailOpen, setDetailOpen, toggleDetail,
    detailSection, setDetailSection,
    navigateToIntent,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}

export default WorkspaceContext;
