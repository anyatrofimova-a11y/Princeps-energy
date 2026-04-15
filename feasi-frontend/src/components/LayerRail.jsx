import React, { useState } from "react";
import { useSite } from "../SiteContext";

/* ── 3 clean layer groups — no duplicates ── */
const SECTIONS = [
  {
    id: "grid",
    label: "Grid",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
    layers: [
      { id: "gridCapacity", label: "Capacity (RAG)", color: "#D4A018" },
      { id: "gridConstraints", label: "Constraints", color: "#f44336" },
      { id: "queueDepth", label: "Queue Depth", color: "#e040fb" },
      { id: "gridFlow", label: "Substations", color: "#24a148" },
      { id: "osmPower", label: "Lines", color: "#B54EB2" },
      { id: "tecPipeline", label: "TEC Queue", color: "#0277bd" },
      { id: "repdProjects", label: "REPD", color: "#ff6f00" },
    ],
  },
  {
    id: "environment",
    label: "Land",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 22c-4.97 0-9-2.69-9-6v-2c0-3.31 4.03-6 9-6s9 2.69 9 6v2c0 3.31-4.03 6-9 6z" />
        <path d="M12 6V2" /><path d="M8 8l-2-4" /><path d="M16 8l2-4" />
      </svg>
    ),
    layers: [
      { id: "envConstraints", label: "SSSI / AONB / Flood", color: "#ef4444" },
      { id: "landParcels", label: "Ownership (HMLR)", color: "#2563eb" },
      { id: "planningDensity", label: "Planning Apps", color: "#f59e0b" },
      { id: "planningConstraints", label: "LPA Constraints", color: "#DC2626" },
      { id: "geeflowLandUse", label: "Land Use", color: "#D4A018" },
      { id: "ndvi", label: "Vegetation", color: "#24a148" },
    ],
  },
  {
    id: "terrain",
    label: "Map",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M8 21l4-10 4 10" /><path d="M2 21l6-14 4 8 4-12 6 18" />
      </svg>
    ),
    layers: [
      { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
      { id: "slope", label: "Slope", color: "#D4A018", hasOpacity: true },
      { id: "contours", label: "Contours", color: "#24a148" },
      { id: "aerial", label: "Aerial", color: "#a56eff" },
      { id: "gridTwin3d", label: "3D Grid Twin", color: "#D4A018" },
      { id: "google3d", label: "Google 3D", color: "#4285f4" },
      { id: "cesiumGlobe", label: "Cesium Globe", color: "#00b4d8" },
      { id: "satellite", label: "Sentinel-2", color: "#D4A018" },
    ],
  },
  {
    id: "live",
    label: "Live",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.636 5.636l2.122 2.122m8.485 8.485l2.121 2.121M5.636 18.364l2.122-2.122m8.485-8.485l2.121-2.121" />
      </svg>
    ),
    layers: [
      { id: "nged_headroom", label: "NOM Headroom", color: "#2e7d32" },
      { id: "nged_ecr", label: "Capacity Register", color: "#7c3aed" },
      { id: "nged_gsp", label: "Live GSPs", color: "#2563eb" },
      { id: "nged_licence", label: "Licence Areas", color: "#c0392b" },
      { id: "dc_estate", label: "DC Estate (NESO098)", color: "#f5b731" },
    ],
  },
  {
    id: "gibs",
    label: "GIBS",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
      </svg>
    ),
    layers: [
      { id: "gibsModis", label: "MODIS True Color", color: "#4285f4" },
      { id: "gibsViirs", label: "VIIRS True Color", color: "#00b4d8" },
      { id: "gibsNightlights", label: "Night Lights", color: "#ffd60a" },
      { id: "gibsNdvi", label: "Vegetation (NDVI)", color: "#52c41a" },
      { id: "gibsLandTemp", label: "Land Surface Temp", color: "#f5222d" },
      { id: "gibsCloudFraction", label: "Cloud Fraction", color: "#adb5bd" },
      { id: "gibsFire", label: "Fire / Thermal", color: "#ff6b35" },
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
