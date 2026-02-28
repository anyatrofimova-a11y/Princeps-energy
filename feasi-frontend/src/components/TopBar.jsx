import React from "react";
import { useSite } from "../SiteContext";

const INTENTS = [
  { value: "overview", label: "Overview", color: "#00ff88" },
  { value: "feasibility", label: "Feasibility", color: "#4caf50" },
  { value: "grid_study", label: "Grid", color: "#2196f3" },
  { value: "financial", label: "Financial", color: "#ff9800" },
  { value: "environmental", label: "Environ.", color: "#66bb6a" },
  { value: "planning", label: "Planning", color: "#e91e63" },
  { value: "satellite_analysis", label: "Satellite", color: "#1565c0" },
  { value: "legacy_compliance", label: "Legacy", color: "#ef6c00" },
  { value: "procurement", label: "Procure.", color: "#ff5722" },
  { value: "grid_efficiency", label: "Grid Eff.", color: "#795548" },
  { value: "site_prospecting", label: "Prospect.", color: "#009688" },
  { value: "bess", label: "BESS", color: "#4caf50" },
];

export default function TopBar({
  onPickSite,
  onAnalyse,
  onNomExplorer,
  onLayoutToggle,
  onSettings,
}) {
  const {
    parcelId, pickedLocation,
    pickMode, setPickMode,
    samCapacity, setSamCapacity,
    samDay, setSamDay,
    loading, layoutMode,
    activeIntent, setActiveIntent,
    runAgent,
  } = useSite();

  const handleIntentClick = (intentValue) => {
    setActiveIntent(intentValue);
    if (parcelId && intentValue !== "overview") {
      runAgent(parcelId, intentValue, samCapacity, samDay);
    }
  };

  return (
    <header className="topbar-area">
      <div className="topbar-left">
        <div className="topbar-brand">Feasibly</div>
        <div className="topbar-intent-pills">
          {INTENTS.map((i) => (
            <button
              key={i.value}
              className={`topbar-intent-pill${activeIntent === i.value ? " active" : ""}`}
              style={{ "--pill-color": i.color }}
              onClick={() => handleIntentClick(i.value)}
            >
              {i.label}
            </button>
          ))}
        </div>
      </div>

      <div className="topbar-center">
        <button
          className={`btn-pick${pickMode ? " active" : ""}`}
          onClick={() => setPickMode((p) => !p)}
        >
          {pickMode ? "Cancel" : "Pick Site"}
        </button>
        {pickedLocation && (
          <span className="topbar-coords">
            {pickedLocation.lat.toFixed(4)}, {pickedLocation.lon.toFixed(4)}
          </span>
        )}
        {parcelId && (
          <span className="topbar-parcel" title={parcelId}>
            {parcelId.slice(0, 8)}
          </span>
        )}
      </div>

      <div className="topbar-right">
        <span className="topbar-param">
          <input
            type="number"
            value={samCapacity}
            onChange={(e) => setSamCapacity(Number(e.target.value))}
            style={{ width: 55 }}
            min={1}
          />{" "}
          kW
        </span>
        <span className="topbar-param">
          Day{" "}
          <input
            type="number"
            value={samDay}
            onChange={(e) => setSamDay(Number(e.target.value))}
            style={{ width: 40 }}
            min={1}
            max={365}
          />
        </span>
        <button className="btn-primary" onClick={onAnalyse} disabled={loading || !parcelId}>
          {loading ? "..." : "Analyse"}
        </button>
        <button className="btn-topbar-action" onClick={onNomExplorer}>NOM</button>
        <button
          className={`btn-topbar-action${layoutMode ? " active" : ""}`}
          onClick={onLayoutToggle}
          disabled={!parcelId}
        >
          {layoutMode ? "Exit" : "Layout"}
        </button>
        <button className="btn-topbar-action" onClick={onSettings} title="Settings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
