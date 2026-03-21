import React, { useState, lazy, Suspense } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, WORKSPACE_INTENTS } from "../../contexts/WorkspaceContext";

const GridAssetTree = lazy(() => import("../grid/GridAssetTree"));

const INTENT_META = {
  grid_study:           { label: "Grid Study",           emoji: "zap",     desc: "Analyse network capacity" },
  grid_connection:      { label: "Grid Connection",      emoji: "plug",    desc: "Connection feasibility & cost" },
  demand_forecast:      { label: "Demand Forecast",      emoji: "chart",   desc: "Demand projections" },
  advanced_grid:        { label: "Advanced Grid",        emoji: "flask",   desc: "N-1 contingency analysis" },
  grid_efficiency:      { label: "Grid Efficiency",      emoji: "shield",  desc: "Losses & congestion" },
  feasibility:          { label: "Feasibility",          emoji: "sun",     desc: "Site scoring & yield" },
  financial:            { label: "Financial",            emoji: "dollar",  desc: "Revenue & ROI" },
  bess_optimisation:    { label: "BESS Optimisation",    emoji: "battery", desc: "Storage sizing" },
  satellite_analysis:   { label: "Satellite Analysis",   emoji: "globe",   desc: "Remote sensing" },
  environmental:        { label: "Environmental",        emoji: "leaf",    desc: "Impact assessment" },
  planning:             { label: "Planning",             emoji: "clip",    desc: "Applications & constraints" },
  legacy_compliance:    { label: "Legacy Compliance",    emoji: "check",   desc: "UK regulatory" },
  connection_strategy:  { label: "Connection Strategy",  emoji: "map",     desc: "Route planning" },
  dispatch_optimisation:{ label: "Dispatch Optimisation", emoji: "clock",  desc: "Optimal scheduling" },
  route_to_market:      { label: "Route to Market",      emoji: "trend",   desc: "Revenue streams" },
  sustainability:       { label: "Sustainability",       emoji: "earth",   desc: "ESG & carbon" },
  investment_readiness: { label: "Investment Readiness",  emoji: "coins",  desc: "Due diligence" },
  site_prospecting:     { label: "Site Prospecting",     emoji: "pin",     desc: "Candidate scoring" },
  procurement:          { label: "Procurement",          emoji: "cart",    desc: "Tender analysis" },
};

// Suggested quick prompts by workspace
const SUGGESTED_PROMPTS = {
  home: [
    "Find a good solar site near Birmingham",
    "Compare grid capacity across regions",
    "What's the best location for a 50MW solar farm?",
  ],
  grid: [
    "Show grid capacity on the map",
    "What substations have spare capacity?",
    "Run N-1 contingency for this area",
  ],
  feasibility: [
    "Analyse this site for solar feasibility",
    "What's the estimated yield?",
    "Show slope and terrain overlays",
  ],
  environment: [
    "Check environmental constraints here",
    "Show land use classification",
    "Any protected habitats nearby?",
  ],
  operations: [
    "Show live grid demand",
    "What's the current energy price?",
    "Display demand forecast overlay",
  ],
  investment: [
    "Calculate ROI for this site",
    "Run financial analysis at 50MW",
    "What's the investment readiness score?",
  ],
};

export default function AssetBrowser() {
  const { activeWorkspace, activeViewMode, browserOpen, toggleBrowser, navigateToIntent } = useWorkspace();
  const {
    activeIntent,
    parcelId, samCapacity, samDay, runAgent,
    workflowResults,
  } = useSite();
  const [searchQ, setSearchQ] = useState("");

  if (!browserOpen) {
    return (
      <button className="browser-toggle-btn collapsed" onClick={toggleBrowser} title="Open browser">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    );
  }

  const intents = WORKSPACE_INTENTS[activeWorkspace] || [];
  const filtered = searchQ.trim()
    ? intents.filter(i => {
        const meta = INTENT_META[i];
        if (!meta) return false;
        const q = searchQ.toLowerCase();
        return meta.label.toLowerCase().includes(q) || meta.desc.toLowerCase().includes(q);
      })
    : intents;

  const handleIntentClick = (intent) => {
    navigateToIntent(intent);
    if (!workflowResults[intent] && parcelId) {
      runAgent(parcelId, intent, samCapacity, samDay);
    } else if (!parcelId) {
      // No site selected — dispatch to chat instead
      handlePrompt(`Run ${(INTENT_META[intent]?.label || intent).toLowerCase()} analysis`);
    }
  };

  // Dispatch a suggested prompt to the CopilotWidget chat
  const handlePrompt = (prompt) => {
    // Use custom event to communicate with CopilotWidget
    window.dispatchEvent(new CustomEvent("princeps-chat", { detail: { text: prompt } }));
  };

  // Grid workspace: smart asset tree
  if (activeWorkspace === "analyse" && activeViewMode === "explore") {
    return (
      <div className="asset-browser">
        <div className="ab-header">
          <span className="ab-title">Grid Explorer</span>
          <button className="ab-close" onClick={toggleBrowser} title="Collapse">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
        </div>
        <Suspense fallback={<div style={{ padding: 12, fontSize: 11, color: "var(--cds-text-helper)" }}>Loading...</div>}>
          <GridAssetTree />
        </Suspense>
      </div>
    );
  }

  const prompts = SUGGESTED_PROMPTS[activeWorkspace] || SUGGESTED_PROMPTS.home;

  return (
    <div className="asset-browser">
      <div className="ab-header">
        <span className="ab-title">Navigator</span>
        <button className="ab-close" onClick={toggleBrowser} title="Collapse">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>

      <div className="ab-body">
        {/* Search */}
        <div className="ab-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            placeholder="Filter analysis..."
            value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            className="ab-search-input"
          />
        </div>

        {/* Suggested prompts */}
        <div className="ab-section">
          <div className="ab-section-title">Try asking</div>
          <div className="ab-prompts">
            {prompts.map((p, i) => (
              <button key={i} className="ab-prompt-btn" onClick={() => handlePrompt(p)}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10 10 10 0 0 1-7.07-2.93" />
                  <path d="M2 12h4l2-3 3 6 2-3h3" />
                </svg>
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Intent navigation */}
        {filtered.length > 0 && (
          <div className="ab-section">
            <div className="ab-section-title">Analysis</div>
            {filtered.map((intent) => {
              const meta = INTENT_META[intent] || { label: intent, desc: "" };
              const isActive = activeIntent === intent;
              const result = workflowResults[intent];
              let verdictClass = null;
              if (result?.verdict === "GO") verdictClass = "go";
              else if (result?.verdict === "CAUTION") verdictClass = "caution";
              else if (result?.verdict === "NO-GO") verdictClass = "nogo";
              return (
                <button
                  key={intent}
                  className={`ab-intent-card${isActive ? " active" : ""}`}
                  onClick={() => handleIntentClick(intent)}
                >
                  <div className="ab-intent-card-main">
                    <span className="ab-intent-card-label">{meta.label}</span>
                    <span className="ab-intent-card-desc">{meta.desc}</span>
                  </div>
                  {verdictClass && (
                    <span className={`ab-intent-verdict ab-verdict-${verdictClass}`}>
                      {result.verdict}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
