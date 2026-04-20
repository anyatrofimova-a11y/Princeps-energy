import React from "react";

/**
 * AssessTwinLegend — 200px wide, pinned bottom-left of the twin embed.
 * Shows active layer swatches + a distance scale readout.
 *
 * Props:
 *   layers:    { [key]: bool }
 *   scaleKm:   approximate ground distance in km represented across map width
 *   tech:      "solar" | "wind" | "bess" | "dc" (informational)
 */

const SWATCHES = [
  { key: "polygon",    label: "Project polygon",    dot: "#F5B731",           border: true },
  { key: "buildable",  label: "Buildable mask",     dot: "rgba(245,183,49,0.45)" },
  { key: "substation", label: "POC substation",     dot: "#2B7FFF" },
  { key: "grid_lines", label: "Grid lines (5 km)",  dot: "#3B8BD9", line: true },
  { key: "landuse",    label: "Land-use overlay",   dot: "#8FB56B" },
  { key: "terrain",    label: "Terrain (NASADEM)",  dot: "#7E6A46" },
];

function formatKm(km) {
  if (!Number.isFinite(km) || km <= 0) return "—";
  if (km < 1) return `${Math.round(km * 1000)} m`;
  if (km < 10) return `${km.toFixed(1)} km`;
  return `${Math.round(km)} km`;
}

// Legend key → Inspector selection mapping. Null = not inspectable.
const LEGEND_INSPECTOR_KEY = {
  polygon: "polygon",
  substation: "poc",
  grid_lines: null,   // individual lines are picked from the map, not the legend
  buildable: null,
  terrain: null,
  landuse: null,
  satellite: null,
};

export default function AssessTwinLegend({
  layers = {}, scaleKm = null, tech = null,
  selected = null, onLegendClick = null,
}) {
  const active = SWATCHES.filter((s) => layers[s.key]);

  return (
    <div className="atl-wrap">
      <div className="atl-head">
        <span className="atl-title">Legend</span>
        {tech && <span className="atl-tech">{tech.toUpperCase()}</span>}
      </div>

      {active.length === 0 ? (
        <div className="atl-empty">No layers active.</div>
      ) : (
        <ul className="atl-list">
          {active.map((s) => {
            const inspectKey = LEGEND_INSPECTOR_KEY[s.key] ?? null;
            const clickable = !!(inspectKey && onLegendClick);
            const isSelected = inspectKey && selected === inspectKey;
            return (
              <li
                key={s.key}
                className={"atl-row" + (clickable ? " atl-row-clickable" : "") + (isSelected ? " atl-row-selected" : "")}
                onClick={clickable ? () => onLegendClick(inspectKey) : undefined}
                title={clickable ? "Click to inspect" : undefined}
              >
                <span
                  className={"atl-dot" + (s.border ? " atl-dot-border" : "") + (s.line ? " atl-dot-line" : "")}
                  style={{
                    background: s.line ? "transparent" : s.dot,
                    borderColor: s.border ? s.dot : undefined,
                    color: s.line ? s.dot : undefined,
                  }}
                />
                <span className="atl-label">{s.label}</span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="atl-scale">
        <div className="atl-scale-head">Scale</div>
        <div className="atl-scale-row">
          <div className="atl-scale-bar">
            <div className="atl-scale-tick" />
            <div className="atl-scale-tick" />
            <div className="atl-scale-tick" />
          </div>
          <span className="atl-scale-val">{formatKm(scaleKm)}</span>
        </div>
      </div>

      <style>{`
        .atl-wrap {
          position: absolute;
          left: 10px;
          bottom: 10px;
          z-index: 15;
          width: 200px;
          background: #FBF8F2;
          border: 1px solid rgba(245, 183, 49, 0.4);
          border-radius: 8px;
          box-shadow: 0 2px 8px rgba(20, 18, 10, 0.12);
          padding: 10px 12px;
          font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
          color: #2A2317;
        }
        .atl-head {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 8px;
        }
        .atl-title {
          font-size: 10px; font-weight: 700;
          letter-spacing: 1.4px; text-transform: uppercase;
          color: #6B4A0A;
        }
        .atl-tech {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 9.5px; letter-spacing: 0.8px;
          background: rgba(245, 183, 49, 0.18);
          color: #6B4A0A;
          padding: 1px 5px; border-radius: 3px;
        }
        .atl-empty {
          font-size: 11px;
          color: rgba(42, 35, 23, 0.6);
          font-style: italic;
        }
        .atl-list { list-style: none; margin: 0 0 8px 0; padding: 0; }
        .atl-row {
          display: flex; align-items: center; gap: 8px;
          padding: 2px 4px;
          font-size: 11px;
          border-radius: 3px;
          transition: background-color 120ms ease;
        }
        .atl-row-clickable { cursor: pointer; }
        .atl-row-clickable:hover { background: rgba(245, 183, 49, 0.14); }
        .atl-row-selected {
          background: rgba(245, 183, 49, 0.24);
          box-shadow: inset 2px 0 0 #F5B731;
        }
        .atl-dot {
          width: 12px; height: 12px; border-radius: 3px;
          flex-shrink: 0;
        }
        .atl-dot-border {
          background: transparent !important;
          border: 2px solid currentColor;
        }
        .atl-dot-line {
          background: transparent !important;
          border: none;
          height: 2px;
          margin: 5px 0;
          border-top: 2px solid currentColor;
          border-radius: 0;
        }
        .atl-label {
          color: rgba(42, 35, 23, 0.85);
        }
        .atl-scale {
          padding-top: 6px;
          border-top: 1px solid rgba(20, 18, 10, 0.08);
        }
        .atl-scale-head {
          font-size: 9.5px;
          font-weight: 700;
          letter-spacing: 1.2px;
          text-transform: uppercase;
          color: #6B4A0A;
          margin-bottom: 4px;
        }
        .atl-scale-row {
          display: flex; align-items: center; gap: 8px;
        }
        .atl-scale-bar {
          flex: 1;
          height: 6px;
          display: flex;
          align-items: center;
          border-bottom: 2px solid #2A2317;
          position: relative;
        }
        .atl-scale-tick {
          width: 1px;
          height: 6px;
          background: #2A2317;
          flex: 1;
          border-right: 1px solid #2A2317;
        }
        .atl-scale-tick:last-child { border-right: none; }
        .atl-scale-val {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 10px;
          color: #2A2317;
          min-width: 44px;
          text-align: right;
        }
      `}</style>
    </div>
  );
}
