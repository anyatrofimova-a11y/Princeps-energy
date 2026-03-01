import React, { useState } from "react";
import { useWorkspace, WORKSPACE_INTENTS } from "../../contexts/WorkspaceContext";
import { useSite } from "../../SiteContext";

const CAPABILITY_CARDS = {
  grid_study:           { label: "Grid Study",           desc: "Network analysis and capacity assessment", icon: "M13 2L3 14h9l-1 8 10-12h-9l1-8z", color: "#0f62fe" },
  grid_connection:      { label: "Grid Connection",      desc: "Connection feasibility and cost estimation", icon: "M13 2L3 14h9l-1 8 10-12h-9l1-8z", color: "#3b82f6" },
  demand_forecast:      { label: "Demand Forecast",      desc: "Prophet + TFT demand projections", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z", color: "#fa8c16" },
  advanced_grid:        { label: "Advanced Grid",        desc: "N-1 contingency and power flow analysis", icon: "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z", color: "#6366f1" },
  grid_efficiency:      { label: "Grid Efficiency",      desc: "Line losses, congestion, upgrade opportunities", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z", color: "#24a148" },
  feasibility:          { label: "Feasibility",          desc: "Site scoring and solar yield analysis", icon: "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z", color: "#f59e0b" },
  financial:            { label: "Financial",            desc: "Revenue, pricing, and ROI analysis", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#24a148" },
  bess_optimisation:    { label: "BESS Optimisation",    desc: "Battery storage sizing and dispatch", icon: "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15", color: "#a56eff" },
  satellite_analysis:   { label: "Satellite Analysis",   desc: "Remote sensing and land classification", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#0f62fe" },
  environmental:        { label: "Environmental",        desc: "Impact assessment and habitat analysis", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#24a148" },
  planning:             { label: "Planning",             desc: "Planning applications and constraints", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", color: "#f1c21b" },
  legacy_compliance:    { label: "Legacy Compliance",    desc: "UK regulatory compliance (G99, CDM, BNG)", icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z", color: "#8d6e63" },
  connection_strategy:  { label: "Connection Strategy",  desc: "Optimal connection route planning", icon: "M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7", color: "#0277bd" },
  dispatch_optimisation:{ label: "Dispatch Optimisation", desc: "Optimal energy dispatch scheduling", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", color: "#0f62fe" },
  route_to_market:      { label: "Route to Market",      desc: "Revenue streams and PPA analysis", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6", color: "#24a148" },
  sustainability:       { label: "Sustainability",       desc: "ESG metrics and carbon accounting", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#0e7e58" },
  investment_readiness: { label: "Investment Readiness",  desc: "Due diligence and investment scoring", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#a56eff" },
};

export default function WorkspaceHome() {
  const { activeWorkspace, navigateToIntent, setActiveViewMode } = useWorkspace();
  const { parcelId, samCapacity, samDay, runAgent, workflowResults } = useSite();
  const [search, setSearch] = useState("");

  const intents = WORKSPACE_INTENTS[activeWorkspace] || [];
  const filtered = intents.filter(intent => {
    const card = CAPABILITY_CARDS[intent];
    if (!card) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return card.label.toLowerCase().includes(q) || card.desc.toLowerCase().includes(q);
  });

  const handleCardClick = (intent) => {
    navigateToIntent(intent);
    setActiveViewMode("map");
    if (!workflowResults[intent] && parcelId) {
      runAgent(parcelId, intent, samCapacity, samDay);
    }
  };

  if (activeWorkspace === "home") {
    return (
      <div className="workspace-home">
        <div className="wh-hero">
          <h2 className="wh-title">PRINCEPS</h2>
          <p className="wh-subtitle">Energy infrastructure site feasibility platform</p>
        </div>
        <div className="wh-grid">
          {Object.entries(CAPABILITY_CARDS).slice(0, 8).map(([intent, card]) => (
            <button key={intent} className="wh-card" onClick={() => handleCardClick(intent)}>
              <div className="wh-card-icon" style={{ color: card.color }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d={card.icon} />
                </svg>
              </div>
              <div className="wh-card-label">{card.label}</div>
              <div className="wh-card-desc">{card.desc}</div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="workspace-home">
      <div className="wh-search">
        <input
          type="text"
          placeholder="Search capabilities..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="wh-search-input"
        />
      </div>
      <div className="wh-grid">
        {filtered.map(intent => {
          const card = CAPABILITY_CARDS[intent];
          if (!card) return null;
          const result = workflowResults[intent];
          return (
            <button key={intent} className="wh-card" onClick={() => handleCardClick(intent)}>
              <div className="wh-card-icon" style={{ color: card.color }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d={card.icon} />
                </svg>
              </div>
              <div className="wh-card-label">{card.label}</div>
              <div className="wh-card-desc">{card.desc}</div>
              {result?.verdict && (
                <span className={`wh-card-verdict wh-verdict-${result.verdict.toLowerCase().replace("-","")}`}>
                  {result.verdict}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
