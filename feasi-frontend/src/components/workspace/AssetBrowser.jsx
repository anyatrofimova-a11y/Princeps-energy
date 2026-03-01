import React, { useState } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, WORKSPACE_INTENTS } from "../../contexts/WorkspaceContext";

// Layer sections distributed by workspace
const WORKSPACE_LAYERS = {
  home: [],
  grid: [
    { id: "gridFlow", label: "Grid Flow", color: "#24a148" },
    { id: "agilePricing", label: "Agile Pricing", color: "#f1c21b" },
    { id: "demandOverlay", label: "Smart Meter", color: "#a56eff" },
    { id: "flowFocus", label: "Flow Focus", color: "#08bdba" },
    { id: "osmPower", label: "OSM Power", color: "#B54EB2" },
    { id: "ngedSubs", label: "NGED Subs", color: "#1b5e20" },
    { id: "gridCapacity", label: "Grid Capacity", color: "#0f62fe" },
    { id: "demandGsps", label: "Demand GSPs", color: "#fa8c16" },
    { id: "tecPipeline", label: "TEC Pipeline", color: "#0277bd" },
    { id: "repdProjects", label: "REPD Projects", color: "#ff6f00" },
    { id: "electricityZones", label: "Elec. Zones", color: "#24a148" },
    { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
    { id: "contours", label: "Contours", color: "#24a148" },
  ],
  feasibility: [
    { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
    { id: "slope", label: "Slope", color: "#0f62fe", hasOpacity: true },
    { id: "contours", label: "Contours", color: "#24a148" },
    { id: "lidarDtm", label: "LIDAR DTM", color: "#ef6c00" },
    { id: "lidarDsm", label: "LIDAR DSM", color: "#d84315" },
    { id: "ndvi", label: "NDVI (MODIS)", color: "#24a148" },
    { id: "satellite", label: "Sentinel-2", color: "#0f62fe" },
    { id: "aerial", label: "Aerial (ESRI)", color: "#a56eff" },
    { id: "landsat", label: "Landsat 30m", color: "#1b5e20" },
    { id: "viirs", label: "VIIRS Daily", color: "#0043ce" },
  ],
  environment: [
    { id: "carbon", label: "Carbon (PBCC)", color: "#da1e28" },
    { id: "la", label: "Local Authority", color: "#f1c21b" },
    { id: "transport", label: "Transport", color: "#08bdba" },
    { id: "environment", label: "Energy Assets", color: "#f1c21b" },
    { id: "geeflowLandUse", label: "Land Use (GEE)", color: "#0f62fe" },
    { id: "geeflowOpportunities", label: "Grid Opps (EO)", color: "#ff6f00" },
    { id: "epcZones", label: "Neighbourhoods", color: "#24a148" },
    { id: "epcDom", label: "Domestic EPC", color: "#0e7e58" },
    { id: "epcNondom", label: "Non-Dom EPC", color: "#f1c21b" },
    { id: "postcodes", label: "Postcodes Energy", color: "#0f62fe" },
  ],
  operations: [
    { id: "gridFlow", label: "Grid Flow", color: "#24a148" },
    { id: "gridCapacity", label: "Grid Capacity", color: "#0f62fe" },
    { id: "demandGsps", label: "Demand GSPs", color: "#fa8c16" },
    { id: "agilePricing", label: "Agile Pricing", color: "#f1c21b" },
  ],
  investment: [
    { id: "gridCapacity", label: "Grid Capacity", color: "#0f62fe" },
    { id: "repdProjects", label: "REPD Projects", color: "#ff6f00" },
    { id: "tecPipeline", label: "TEC Pipeline", color: "#0277bd" },
  ],
};

const INTENT_LABELS = {
  grid_study: "Grid Study",
  grid_connection: "Grid Connection",
  demand_forecast: "Demand Forecast",
  advanced_grid: "Advanced Grid",
  grid_efficiency: "Grid Efficiency",
  feasibility: "Feasibility",
  financial: "Financial",
  bess_optimisation: "BESS Optimisation",
  satellite_analysis: "Satellite Analysis",
  environmental: "Environmental",
  planning: "Planning",
  legacy_compliance: "Legacy Compliance",
  connection_strategy: "Connection Strategy",
  dispatch_optimisation: "Dispatch Optimisation",
  route_to_market: "Route to Market",
  sustainability: "Sustainability",
  investment_readiness: "Investment Readiness",
};

export default function AssetBrowser() {
  const { activeWorkspace, browserOpen, toggleBrowser, navigateToIntent } = useWorkspace();
  const {
    layers, toggleLayer,
    slopeOpacity, setSlopeOpacity,
    activeIntent,
    parcelId, samCapacity, samDay, runAgent,
    workflowResults,
  } = useSite();
  const [layersExpanded, setLayersExpanded] = useState(true);

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
  const wsLayers = WORKSPACE_LAYERS[activeWorkspace] || [];

  const handleIntentClick = (intent) => {
    navigateToIntent(intent);
    if (!workflowResults[intent] && parcelId) {
      runAgent(parcelId, intent, samCapacity, samDay);
    }
  };

  return (
    <div className="asset-browser">
      <div className="ab-header">
        <span className="ab-title">Browser</span>
        <button className="ab-close" onClick={toggleBrowser} title="Collapse">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>

      <div className="ab-body">
        {/* Intent navigation for this workspace */}
        {intents.length > 0 && (
          <div className="ab-section">
            <div className="ab-section-title">Analysis</div>
            {intents.map((intent) => {
              const isActive = activeIntent === intent;
              const result = workflowResults[intent];
              let dotColor = null;
              if (result?.verdict === "GO") dotColor = "#24a148";
              else if (result?.verdict === "CAUTION") dotColor = "#f1c21b";
              else if (result?.verdict === "NO-GO") dotColor = "#da1e28";
              else if (result?.verdict === "ERROR") dotColor = "#795548";
              return (
                <button
                  key={intent}
                  className={`ab-intent-btn${isActive ? " active" : ""}`}
                  onClick={() => handleIntentClick(intent)}
                >
                  {dotColor && <span className="ab-verdict-dot" style={{ background: dotColor }} />}
                  {INTENT_LABELS[intent] || intent}
                </button>
              );
            })}
          </div>
        )}

        {/* Layer toggles */}
        {wsLayers.length > 0 && (
          <div className="ab-section">
            <button
              className="ab-section-title ab-section-toggle"
              onClick={() => setLayersExpanded(p => !p)}
            >
              Layers
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                style={{ transform: layersExpanded ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.15s" }}
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {layersExpanded && wsLayers.map((l) => (
              <div key={l.id}>
                <label className="ab-layer-item">
                  <input
                    type="checkbox"
                    checked={!!layers[l.id]}
                    onChange={() => toggleLayer(l.id)}
                  />
                  <span className="layer-dot" style={{ background: l.color }} />
                  {l.label}
                </label>
                {l.hasOpacity && layers[l.id] && (
                  <input
                    type="range" min="0" max="1" step="0.05"
                    value={slopeOpacity}
                    onChange={(e) => setSlopeOpacity(parseFloat(e.target.value))}
                    className="sidebar-slider"
                    style={{ marginLeft: 24, width: "calc(100% - 32px)" }}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
