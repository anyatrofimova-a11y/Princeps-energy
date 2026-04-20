import React from "react";

/**
 * TwinOverlayToggles — left mini-rail of layer checkboxes for the
 * project-context twin. Controlled by parent; parent owns state and
 * persistence (localStorage).
 */

const LAYER_META = {
  boundary:     { icon: "▰", label: "Red-line" },
  substation:   { icon: "⚡", label: "Substation + arc" },
  designations: { icon: "▲", label: "Designations 500m" },
  flood:        { icon: "≋", label: "Flood zones 2/3" },
  slope:        { icon: "⋰", label: "Slope >10%" },
  landuse:      { icon: "◐", label: "Land use" },
  queue:        { icon: "◉", label: "Grid queue 10km" },
};

export default function TwinOverlayToggles({
  layers,
  order = ["boundary", "substation", "designations", "flood", "slope", "landuse", "queue"],
  onToggle,
  onSetAll,
  statuses = {}, // { layer: 'live' | 'pending' | 'empty' }
}) {
  return (
    <div className="tot-rail" role="region" aria-label="Layer toggles">
      <div className="tot-header">
        <span className="tot-eyebrow">LAYERS</span>
        <div className="tot-quick">
          <button className="tot-mini" onClick={() => onSetAll(true)}>all</button>
          <span className="tot-mini-sep">/</span>
          <button className="tot-mini" onClick={() => onSetAll(false)}>none</button>
        </div>
      </div>
      <ul className="tot-list">
        {order.map((key) => {
          const meta = LAYER_META[key];
          if (!meta) return null;
          const checked = !!layers[key];
          const status = statuses[key] || "live";
          return (
            <li key={key} className="tot-item">
              <label className="tot-label">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(key)}
                />
                <span className="tot-icon">{meta.icon}</span>
                <span className="tot-text">{meta.label}</span>
                {status === "pending" && <span className="tot-badge tot-pending">pending</span>}
                {status === "empty" && <span className="tot-badge tot-empty">none</span>}
              </label>
            </li>
          );
        })}
      </ul>

      <style>{`
        .tot-rail {
          position: absolute;
          top: 12px;
          left: 12px;
          z-index: 5;
          background: rgba(18, 20, 24, 0.82);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          border: 1px solid rgba(201, 166, 75, 0.22);
          border-radius: 10px;
          padding: 10px 10px 8px 10px;
          min-width: 176px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: rgba(255,255,255,0.9);
          box-shadow: 0 8px 28px rgba(0,0,0,0.35);
        }
        .tot-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .tot-eyebrow {
          font-size: 9.5px;
          font-weight: 700;
          letter-spacing: 0.12em;
          color: #C9A64B;
        }
        .tot-quick { display: flex; align-items: center; gap: 3px; }
        .tot-mini {
          background: none; border: none; padding: 0;
          font-family: inherit; font-size: 10px;
          color: rgba(255,255,255,0.7);
          cursor: pointer;
          letter-spacing: 0.04em;
        }
        .tot-mini:hover { color: #F5E9C8; text-decoration: underline; }
        .tot-mini-sep { color: rgba(255,255,255,0.3); font-size: 10px; }
        .tot-list { list-style: none; margin: 0; padding: 0; }
        .tot-item { margin: 0; }
        .tot-label {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 2px;
          font-size: 11.5px;
          cursor: pointer;
          user-select: none;
        }
        .tot-label input[type="checkbox"] {
          accent-color: #C9A64B;
          cursor: pointer;
          width: 12px; height: 12px; margin: 0;
        }
        .tot-icon {
          width: 14px;
          display: inline-block;
          text-align: center;
          font-size: 11px;
          color: #C9A64B;
        }
        .tot-text {
          flex: 1;
          white-space: nowrap;
        }
        .tot-badge {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 8.5px;
          padding: 1px 4px;
          border-radius: 3px;
          letter-spacing: 0.05em;
          text-transform: uppercase;
        }
        .tot-pending { background: rgba(201,166,75,0.18); color: #F5E9C8; }
        .tot-empty { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.5); }
      `}</style>
    </div>
  );
}
