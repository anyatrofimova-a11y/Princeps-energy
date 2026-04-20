import React, { useState, useRef, useEffect } from "react";

/**
 * ActionsMenu — grouped dropdown exposing all power-user launchers from the
 * original Princeps UI inside the redesigned project-centric shell.
 *
 * Props:
 *   actions: { [key]: () => void }
 *   Expected keys (missing keys hide the item):
 *     gridTwin, dcTwin, bessFacility, bems, digitalTwin, terrainTwin,
 *     dataCentreTwin, asset3d, assetInspector, gridGraph, nomExplorer,
 *     scenarioCompare, dcLanding, dcCompare, intelligence,
 *     siteDesigner, hwConfig, thermalModel, dashboardBuilder,
 *     assessmentWizard, commandPalette, pitch, capabilities, settings,
 *     pipeline, exportHub
 */

const GROUPS = [
  {
    label: "Twins",
    items: [
      { key: "gridTwin",        label: "Grid Twin",         hint: "3D grid network (Cesium)" },
      { key: "dcTwin",          label: "Data Centre Twin",  hint: "DC facility viz" },
      { key: "bessFacility",    label: "BESS Facility Twin", hint: "Battery site 3D" },
      { key: "bems",            label: "BEMS Twin",         hint: "Building energy mgmt" },
      { key: "digitalTwin",     label: "Unified Site Twin", hint: "Site + terrain unified" },
      { key: "terrainTwin",     label: "Terrain Twin",      hint: "NASADEM + shading" },
      { key: "asset3d",         label: "Asset 3D Modeller", hint: "Gemini-generated 3D" },
      // assetInspector archived 2026-04-19 — utility-pole demo not relevant to DC/BESS.
      // BESS+DC asset inspection lives in BESSFacilityTwin / DataCentreTwin.
    ],
  },
  {
    label: "Analysis",
    items: [
      { key: "gridGraph",       label: "Grid Graph View",   hint: "Substation topology graph" },
      { key: "nomExplorer",     label: "NOM Explorer",      hint: "Nexus of markets" },
      { key: "scenarioCompare", label: "Scenario Compare",  hint: "Side-by-side what-ifs" },
      { key: "dcLanding",       label: "DC Site Scoring",   hint: "DC landing page" },
      { key: "dcCompare",       label: "DC Comparison",     hint: "Compare DC candidates" },
      { key: "intelligence",    label: "Intelligence Feed", hint: "Regulatory + market alerts" },
    ],
  },
  {
    label: "Design",
    items: [
      { key: "hwConfig",        label: "Hardware Configurator", hint: "Spec modules + inverters" },
      { key: "thermalModel",    label: "Thermal Model",     hint: "Heat loss + gain" },
      { key: "dashboardBuilder", label: "Dashboard Builder", hint: "Custom live dashboards" },
    ],
  },
  {
    label: "Assess & export",
    items: [
      { key: "assessmentWizard", label: "Assessment Wizard", hint: "Guided site evaluation" },
      { key: "pipeline",        label: "Open pipeline",     hint: "Legacy projects list" },
      { key: "exportHub",       label: "Export Hub",        hint: "PDFs, CSVs, CIM" },
      { key: "pitch",           label: "Pitch mode",        hint: "Stakeholder presentation" },
      { key: "capabilities",    label: "Capabilities",      hint: "What Princeps can do" },
    ],
  },
  {
    label: "System",
    items: [
      { key: "commandPalette",  label: "Command palette",   hint: "⌘K", shortcut: "⌘K" },
      { key: "settings",        label: "Settings",          hint: "Preferences" },
    ],
  },
];

export default function ActionsMenu({ actions = {} }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const fire = (key) => {
    const fn = actions[key];
    if (typeof fn === "function") {
      fn();
      setOpen(false);
    }
  };

  return (
    <div className="am-wrap" ref={wrapRef}>
      <button
        className={"am-trigger" + (open ? " am-trigger-open" : "")}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Actions
        <span className="am-caret">▾</span>
      </button>
      {open && (
        <div className="am-panel" role="menu">
          {GROUPS.map((g) => {
            const items = g.items.filter((it) => typeof actions[it.key] === "function");
            if (items.length === 0) return null;
            return (
              <div key={g.label} className="am-group">
                <div className="am-group-label">{g.label}</div>
                {items.map((it) => (
                  <button
                    key={it.key}
                    className="am-item"
                    onClick={() => fire(it.key)}
                    role="menuitem"
                  >
                    <div className="am-item-main">
                      <div className="am-item-label">{it.label}</div>
                      {it.hint && <div className="am-item-hint">{it.hint}</div>}
                    </div>
                    {it.shortcut && <div className="am-item-kbd">{it.shortcut}</div>}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}
      <style>{`
        .am-wrap { position: relative; }
        .am-trigger {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 8px 14px;
          background: var(--gold);
          color: #fff;
          border: 1px solid var(--gold);
          border-radius: 8px;
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 13px; font-weight: 600;
          cursor: pointer;
          transition: all 120ms;
        }
        .am-trigger:hover { background: var(--gold-dark); border-color: var(--gold-dark); }
        .am-trigger-open { background: var(--gold-dark); border-color: var(--gold-dark); }
        .am-caret { font-size: 10px; }
        .am-panel {
          position: absolute; top: calc(100% + 8px); right: 0;
          min-width: 320px; max-height: 520px; overflow-y: auto;
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 12px;
          box-shadow: 0 16px 48px rgba(0,0,0,0.12);
          padding: 6px;
          z-index: 900;
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .am-group { padding: 4px 0; }
        .am-group + .am-group {
          border-top: 1px solid var(--cds-border-subtle);
          margin-top: 4px;
          padding-top: 8px;
        }
        .am-group-label {
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--cds-text-helper);
          padding: 4px 10px 6px;
        }
        .am-item {
          display: flex; align-items: center; width: 100%;
          padding: 8px 10px; gap: 10px;
          background: none; border: none;
          cursor: pointer; text-align: left;
          border-radius: 8px;
          transition: background 80ms;
          font-family: inherit;
        }
        .am-item:hover { background: rgba(var(--accent-rgb), 0.08); }
        .am-item-main { flex: 1; min-width: 0; }
        .am-item-label {
          font-size: 13px; font-weight: 600;
          color: var(--ink);
        }
        .am-item-hint {
          font-size: 11px; color: var(--cds-text-helper);
          margin-top: 2px;
        }
        .am-item-kbd {
          font-family: var(--mono);
          font-size: 10px;
          color: var(--cds-text-helper);
          padding: 2px 6px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 4px;
          flex-shrink: 0;
        }
      `}</style>
    </div>
  );
}
