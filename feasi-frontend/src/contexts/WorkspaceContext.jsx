import React, { createContext, useContext, useState, useCallback } from "react";
import { useSite } from "../SiteContext";

const WorkspaceContext = createContext(null);

export const WORKSPACES = [
  { id: "home",        label: "Home",          icon: "home" },
  { id: "grid",        label: "Grid",          icon: "bolt" },
  { id: "feasibility", label: "Feasibility",   icon: "sun" },
  { id: "environment", label: "Environment",   icon: "leaf" },
  { id: "operations",  label: "Operations",    icon: "gear" },
  { id: "investment",  label: "Investment",     icon: "briefcase" },
];

export const WORKSPACE_DEFAULTS = {
  home:          { intent: null,                    viewMode: "dashboard" },
  grid:          { intent: "grid_study",            viewMode: "map" },
  feasibility:   { intent: "feasibility",           viewMode: "map" },
  environment:   { intent: "environmental",         viewMode: "map" },
  operations:    { intent: "dispatch_optimisation",  viewMode: "map" },
  investment:    { intent: "investment_readiness",   viewMode: "dashboard" },
};

// Maps each workspace to the intents it contains
export const WORKSPACE_INTENTS = {
  home:          [],
  grid:          ["grid_study", "grid_connection", "demand_forecast", "advanced_grid", "grid_efficiency"],
  feasibility:   ["feasibility", "financial", "bess_optimisation", "satellite_analysis"],
  environment:   ["environmental", "planning", "legacy_compliance"],
  operations:    ["connection_strategy", "dispatch_optimisation", "route_to_market", "sustainability"],
  investment:    ["investment_readiness"],
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
};

export function WorkspaceProvider({ children }) {
  const [activeWorkspace, setActiveWorkspaceRaw] = useState("home");
  const [activeViewMode, setActiveViewMode] = useState("map");
  const [browserOpen, setBrowserOpen] = useState(true);
  const [detailOpen, setDetailOpen] = useState(true);
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
