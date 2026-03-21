import React, { useState } from "react";
import { useSite } from "../SiteContext";

const SECTIONS = [
  {
    id: "terrain",
    label: "Terrain",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M8 21l4-10 4 10" /><path d="M2 21l6-14 4 8 4-12 6 18" />
      </svg>
    ),
    layers: [
      { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
      { id: "slope", label: "Slope", color: "#D4A018", hasOpacity: true },
      { id: "contours", label: "Contours", color: "#24a148" },
      { id: "lidarDtm", label: "LIDAR DTM", color: "#ef6c00" },
      { id: "lidarDsm", label: "LIDAR DSM", color: "#d84315" },
    ],
  },
  {
    id: "grid",
    label: "Grid Network",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
    layers: [
      { id: "gridFlow", label: "Grid Flow", color: "#24a148" },
      { id: "agilePricing", label: "Agile Pricing", color: "#f1c21b" },
      { id: "demandOverlay", label: "Smart Meter", color: "#a56eff" },
      { id: "flowFocus", label: "Flow Focus", color: "#08bdba" },
      { id: "osmPower", label: "OSM Power", color: "#B54EB2" },
      { id: "ngedSubs", label: "NGED Subs", color: "#1b5e20" },
      { id: "gridCapacity", label: "Grid Capacity", color: "#D4A018" },
      { id: "demandGsps", label: "Demand GSPs", color: "#fa8c16" },
      { id: "tecPipeline", label: "TEC Pipeline", color: "#0277bd" },
      { id: "repdProjects", label: "REPD Projects", color: "#ff6f00" },
      { id: "gridConstraints", label: "Constraints", color: "#f44336" },
      { id: "queueDepth", label: "Queue Depth", color: "#e040fb" },
      { id: "electricityZones", label: "Elec. Zones", color: "#24a148" },
    ],
  },
  {
    id: "datacentre",
    label: "Data Centre",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" />
        <circle cx="6" cy="6" r="1" fill="currentColor" /><circle cx="6" cy="18" r="1" fill="currentColor" />
      </svg>
    ),
    layers: [
      { id: "dcCapacity", label: "DC Capacity", color: "#D4A018" },
      { id: "dcFibre", label: "Fibre POPs", color: "#a855f7" },
      { id: "dcIxp", label: "IXP Nodes", color: "#3b82f6" },
    ],
  },
  {
    id: "land",
    label: "Land & Carbon",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 22c4-4 8-7.5 8-12a8 8 0 10-16 0c0 4.5 4 8 8 12z" />
        <circle cx="12" cy="10" r="3" />
      </svg>
    ),
    layers: [
      { id: "carbon", label: "Carbon (PBCC)", color: "#da1e28" },
      { id: "la", label: "Local Authority", color: "#f1c21b" },
      { id: "transport", label: "Transport", color: "#08bdba" },
      { id: "environment", label: "Energy Assets", color: "#f1c21b" },
      { id: "geeflowLandUse", label: "Land Use (GEE)", color: "#D4A018" },
      { id: "geeflowOpportunities", label: "Grid Opps (EO)", color: "#ff6f00" },
    ],
  },
  {
    id: "remote",
    label: "Remote Sensing",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z" />
      </svg>
    ),
    layers: [
      { id: "ndvi", label: "NDVI (MODIS)", color: "#24a148" },
      { id: "satellite", label: "Sentinel-2", color: "#D4A018" },
      { id: "aerial", label: "Aerial (ESRI)", color: "#a56eff" },
      { id: "landsat", label: "Landsat 30m", color: "#1b5e20" },
      { id: "viirs", label: "VIIRS Daily", color: "#0043ce" },
    ],
  },
  {
    id: "epc",
    label: "EPC / Retrofit",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
      </svg>
    ),
    layers: [
      { id: "epcZones", label: "Neighbourhoods", color: "#24a148", hasSelect: "epcZonesField" },
      { id: "epcDom", label: "Domestic EPC", color: "#0e7e58", hasSelect: "epcDomField" },
      { id: "epcNondom", label: "Non-Dom EPC", color: "#f1c21b", hasSelect: "epcNondomField" },
      { id: "postcodes", label: "Postcodes Energy", color: "#D4A018", hasSelect: "postcodesField" },
    ],
  },
];

const EPC_OPTIONS = {
  epcZonesField: [
    { v: "epc_score_avg", l: "Avg EPC Score" }, { v: "floor_area_avg", l: "Avg Floor Area" },
    { v: "modal_age", l: "Building Age" }, { v: "modal_wall", l: "Wall Rating" },
    { v: "modal_roof", l: "Roof Rating" }, { v: "modal_heat", l: "Heating Rating" },
    { v: "modal_window", l: "Window Rating" }, { v: "modal_mainheat", l: "Heating Type" },
    { v: "modal_mainfuel", l: "Fuel Type" }, { v: "modal_floord", l: "Floor Type" },
    { v: "modal_type", l: "Building Type" }, { v: "percent_EPC", l: "% with EPC" },
  ],
  epcDomField: [
    { v: "cur_rate", l: "EPC Rating" }, { v: "b_type", l: "Building Type" },
    { v: "p_type", l: "Property Type" }, { v: "age", l: "Building Age" },
    { v: "year", l: "Last Assessed" }, { v: "area", l: "Floor Area" },
    { v: "floor_ee", l: "Floor Rating" }, { v: "water_ee", l: "Hot Water" },
    { v: "wind_ee", l: "Window Rating" }, { v: "wall_ee", l: "Wall Rating" },
    { v: "roof_ee", l: "Roof Rating" }, { v: "heat_ee", l: "Heating Rating" },
    { v: "con_ee", l: "Controls" }, { v: "light_ee", l: "Lighting" },
    { v: "sol_wat", l: "Solar Thermal" },
  ],
  epcNondomField: [
    { v: "band", l: "Rating Band" }, { v: "transaction", l: "Transaction" },
    { v: "area", l: "Floor Area" }, { v: "year", l: "Last Assessed" },
  ],
  postcodesField: [
    { v: "combined", l: "Combined Emissions" }, { v: "gas", l: "Gas Emissions" },
    { v: "elec", l: "Elec. Emissions" },
  ],
};

export default function LayerRail({ chatLayers, onRemoveChatLayer }) {
  const [flyout, setFlyout] = useState(null);
  const {
    layers, toggleLayer,
    slopeOpacity, setSlopeOpacity,
    epcZonesField, setEpcZonesField,
    epcDomField, setEpcDomField,
    epcNondomField, setEpcNondomField,
    postcodesField, setPostcodesField,
  } = useSite();

  const fieldState = { epcZonesField, epcDomField, epcNondomField, postcodesField };
  const fieldSetters = {
    epcZonesField: setEpcZonesField,
    epcDomField: setEpcDomField,
    epcNondomField: setEpcNondomField,
    postcodesField: setPostcodesField,
  };

  const hasChatLayers = chatLayers && chatLayers.length > 0;

  return (
    <div className="layer-rail">
      <div className="layer-rail-icons">
        {SECTIONS.map((section) => (
          <button
            key={section.id}
            className={`layer-rail-btn${flyout === section.id ? " active" : ""}`}
            onClick={() => setFlyout((f) => (f === section.id ? null : section.id))}
            title={section.label}
          >
            {section.icon}
          </button>
        ))}

        {hasChatLayers && (
          <button
            className={`layer-rail-btn ai-layers${flyout === "chat" ? " active" : ""}`}
            onClick={() => setFlyout((f) => (f === "chat" ? null : "chat"))}
            title="AI Layers"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
            </svg>
          </button>
        )}
      </div>

      {/* Flyout panels */}
      {flyout && flyout !== "chat" && (() => {
        const section = SECTIONS.find((s) => s.id === flyout);
        if (!section) return null;
        return (
          <div className="layer-rail-flyout">
            <div className="layer-rail-flyout-title">{section.label}</div>
            {section.layers.map((l) => (
              <div key={l.id}>
                <label className="layer-item">
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
                  />
                )}
                {l.hasSelect && layers[l.id] && EPC_OPTIONS[l.hasSelect] && (
                  <select
                    className="layer-select"
                    value={fieldState[l.hasSelect]}
                    onChange={(e) => fieldSetters[l.hasSelect](e.target.value)}
                  >
                    {EPC_OPTIONS[l.hasSelect].map((o) => (
                      <option key={o.v} value={o.v}>{o.l}</option>
                    ))}
                  </select>
                )}
              </div>
            ))}
          </div>
        );
      })()}

      {flyout === "chat" && hasChatLayers && (
        <div className="layer-rail-flyout">
          <div className="layer-rail-flyout-title">AI Layers</div>
          {chatLayers.map((l) => (
            <label key={l.id} className="layer-item">
              <span className="layer-dot" style={{ background: l.color || "#D4A018" }} />
              {l.name}
              <button
                className="chat-layer-remove"
                onClick={() => onRemoveChatLayer(l.id)}
              >
                &times;
              </button>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
