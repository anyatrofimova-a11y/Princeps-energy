import React from "react";
import { useWorkspace, WORKSPACE_VIEWS } from "../../contexts/WorkspaceContext";

// SVG path data for view icons
const VIEW_ICONS = {
  map:        "M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7",
  table:      "M3 10h18M3 14h18M3 6h18M3 18h18",
  chart:      "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  dashboard:  "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z",
  // Grid-specific views
  explore:    "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v6m-3-3h6",
  network:    "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z",
  circuit:    "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  data:       "M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7C5 4 4 5 4 7zm0 4h16M8 4v16m4-16v16",
  forecast:   "M3 17l4-4 4 4 4-8 4 4M3 21h18",
  compare:    "M9 3v18m6-18v18M3 9h18M3 15h18",
  satellite:  "M12 2a10 10 0 100 20 10 10 0 000-20zm0 4a6 6 0 110 12 6 6 0 010-12zm0 3a3 3 0 100 6 3 3 0 000-6z",
};

const VIEW_LABELS = {
  map: "Map", table: "Table", chart: "Chart", dashboard: "Dashboard",
  explore: "Explore", network: "Network", circuit: "Circuit",
  data: "Data", forecast: "Forecast", compare: "Compare", satellite: "Satellite",
};

export default function ViewTabs() {
  const { activeViewMode, setActiveViewMode, activeWorkspace } = useWorkspace();
  const views = WORKSPACE_VIEWS[activeWorkspace] || ["map", "table", "chart", "dashboard"];

  return (
    <div className="view-tabs">
      {views.map((id) => (
        <button
          key={id}
          className={`view-tab${activeViewMode === id ? " active" : ""}`}
          onClick={() => setActiveViewMode(id)}
          title={VIEW_LABELS[id] || id}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d={VIEW_ICONS[id] || VIEW_ICONS.map} />
          </svg>
          <span>{VIEW_LABELS[id] || id}</span>
        </button>
      ))}
    </div>
  );
}
