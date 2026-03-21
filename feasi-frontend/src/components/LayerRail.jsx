import React, { useState } from "react";
import { useSite } from "../SiteContext";

/* ── Functional layer groups (not by data source) ── */
const SECTIONS = [
  {
    id: "ai",
    label: "AI Analysis",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
      </svg>
    ),
    layers: [
      { id: "gridCapacity", label: "Site Suitability", color: "#D4A018" },
      { id: "geeflowOpportunities", label: "Grid Opportunities", color: "#ff6f00" },
      { id: "queueDepth", label: "Queue Depth", color: "#e040fb" },
      { id: "gridConstraints", label: "Grid Constraints", color: "#f44336" },
      { id: "envConstraints", label: "Env. Constraints", color: "#e53935" },
    ],
  },
  {
    id: "grid",
    label: "Grid & Power",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
    layers: [
      { id: "gridCapacity", label: "Grid Capacity (RAG)", color: "#D4A018" },
      { id: "gridConstraints", label: "Constraint Zones", color: "#f44336" },
      { id: "queueDepth", label: "Queue Depth", color: "#e040fb" },
      { id: "gridFlow", label: "Substations", color: "#24a148" },
      { id: "osmPower", label: "Transmission Lines", color: "#B54EB2" },
      { id: "ngedSubs", label: "NGED Substations", color: "#1b5e20" },
      { id: "tecPipeline", label: "TEC Pipeline", color: "#0277bd" },
      { id: "repdProjects", label: "REPD Projects", color: "#ff6f00" },
      { id: "demandGsps", label: "Demand GSPs", color: "#fa8c16" },
      { id: "agilePricing", label: "Agile Pricing", color: "#f1c21b" },
      { id: "demandOverlay", label: "Smart Meter", color: "#a56eff" },
      { id: "flowFocus", label: "Flow Focus", color: "#08bdba" },
      { id: "electricityZones", label: "Elec. Zones", color: "#24a148" },
    ],
  },
  {
    id: "environment",
    label: "Environment & Land",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 22c-4.97 0-9-2.69-9-6v-2c0-3.31 4.03-6 9-6s9 2.69 9 6v2c0 3.31-4.03 6-9 6z" />
        <path d="M12 6V2" /><path d="M8 8l-2-4" /><path d="M16 8l2-4" />
      </svg>
    ),
    layers: [
      { id: "envConstraints", label: "Constraints (SSSI/AONB/Flood)", color: "#ef4444" },
      { id: "geeflowLandUse", label: "Land Use (GEE)", color: "#D4A018" },
      { id: "environment", label: "Energy Assets", color: "#f1c21b" },
      { id: "carbon", label: "Carbon (PBCC)", color: "#da1e28" },
      { id: "ndvi", label: "NDVI Vegetation", color: "#24a148" },
      { id: "landParcels", label: "HMLR Parcels", color: "#2563eb" },
      { id: "planningDensity", label: "Planning Density", color: "#f59e0b" },
    ],
  },
  {
    id: "infra",
    label: "Infrastructure",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 4v16" /><path d="M4 9h16" />
      </svg>
    ),
    layers: [
      { id: "transport", label: "Transport", color: "#08bdba" },
      { id: "la", label: "Local Authority", color: "#f1c21b" },
      { id: "dcCapacity", label: "DC Capacity", color: "#D4A018" },
      { id: "dcFibre", label: "Fibre POPs", color: "#a855f7" },
      { id: "dcIxp", label: "IXP Nodes", color: "#3b82f6" },
    ],
  },
  {
    id: "terrain",
    label: "Terrain & Imagery",
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
      { id: "aerial", label: "Aerial (ESRI)", color: "#a56eff" },
      { id: "satellite", label: "Sentinel-2", color: "#D4A018" },
      { id: "landsat", label: "Landsat 30m", color: "#1b5e20" },
      { id: "viirs", label: "VIIRS Night", color: "#0043ce" },
      { id: "google3d", label: "Google 3D", color: "#4285f4" },
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

/* ── Layer presets tied to analysis intents ── */
const PRESETS = [
  { id: "grid_connection", label: "Grid Connection", layers: ["gridFlow", "osmPower", "ngedSubs", "gridCapacity", "tecPipeline", "gridConstraints", "queueDepth"] },
  { id: "environmental", label: "Environmental", layers: ["geeflowLandUse", "environment", "ndvi", "carbon", "envConstraints", "landParcels"] },
  { id: "solar_feasibility", label: "Solar Feasibility", layers: ["slope", "hillshade", "gridFlow", "gridCapacity", "geeflowLandUse", "environment"] },
  { id: "dc_colocation", label: "Data Centre", layers: ["gridFlow", "gridCapacity", "dcCapacity", "dcFibre", "dcIxp", "transport", "queueDepth"] },
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
  const [activePreset, setActivePreset] = useState(null);
  const {
    layers, toggleLayer, setLayers,
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

  /* Apply a preset — enable listed layers, disable everything else */
  const applyPreset = (preset) => {
    if (activePreset === preset.id) {
      setActivePreset(null);
      return;
    }
    setActivePreset(preset.id);
    setLayers((prev) => {
      const next = {};
      for (const k of Object.keys(prev)) next[k] = preset.layers.includes(k);
      return next;
    });
  };

  /* Count active layers in a section */
  const countActive = (section) =>
    section.layers.filter((l) => layers[l.id]).length;

  return (
    <div className="layer-rail">
      <div className="layer-rail-icons">
        {/* Preset buttons at top */}
        <button
          className={`layer-rail-btn preset-btn${flyout === "presets" ? " active" : ""}`}
          onClick={() => setFlyout((f) => (f === "presets" ? null : "presets"))}
          title="Layer Presets"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 6h16M4 12h16M4 18h16" />
            <circle cx="8" cy="6" r="2" fill="currentColor" />
            <circle cx="16" cy="12" r="2" fill="currentColor" />
            <circle cx="10" cy="18" r="2" fill="currentColor" />
          </svg>
        </button>

        <div className="layer-rail-divider" />

        {SECTIONS.map((section) => (
          <button
            key={section.id}
            className={`layer-rail-btn${flyout === section.id ? " active" : ""}${countActive(section) > 0 ? " has-active" : ""}`}
            onClick={() => setFlyout((f) => (f === section.id ? null : section.id))}
            title={`${section.label}${countActive(section) > 0 ? ` (${countActive(section)} active)` : ""}`}
          >
            {section.icon}
            {countActive(section) > 0 && (
              <span className="layer-rail-badge">{countActive(section)}</span>
            )}
          </button>
        ))}

        {hasChatLayers && (
          <>
            <div className="layer-rail-divider" />
            <button
              className={`layer-rail-btn ai-layers${flyout === "chat" ? " active" : ""}`}
              onClick={() => setFlyout((f) => (f === "chat" ? null : "chat"))}
              title={`AI Layers (${chatLayers.length})`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
              </svg>
              <span className="layer-rail-badge">{chatLayers.length}</span>
            </button>
          </>
        )}
      </div>

      {/* ── Preset flyout ── */}
      {flyout === "presets" && (
        <div className="layer-rail-flyout">
          <div className="layer-rail-flyout-title">Layer Presets</div>
          <div className="layer-rail-flyout-desc">Auto-configure layers for analysis type</div>
          {PRESETS.map((p) => (
            <button
              key={p.id}
              className={`layer-preset-btn${activePreset === p.id ? " active" : ""}`}
              onClick={() => applyPreset(p)}
            >
              {p.label}
              {activePreset === p.id && <span className="preset-check">✓</span>}
            </button>
          ))}
        </div>
      )}

      {/* ── Section flyouts ── */}
      {flyout && flyout !== "chat" && flyout !== "presets" && (() => {
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

      {/* ── AI/Chat layers ── */}
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
