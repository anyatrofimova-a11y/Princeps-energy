import React, { useState } from "react";
import { MODES, formatArea, formatDistance } from "../lib/draw-modes";

const TOOLS = [
  { mode: MODES.VIEW, title: "Select / Pan (Esc)", icon: "◇", label: "Select" },
  { mode: MODES.POLYGON, title: "Draw site boundary", icon: "⬡", label: "Site Boundary" },
  { mode: MODES.RECTANGLE, title: "Draw exclusion zone", icon: "▭", label: "Exclusion Zone" },
  { mode: MODES.LINE, title: "Measure route / cable", icon: "╱", label: "Route" },
  { mode: MODES.POINT, title: "Mark point of interest", icon: "●", label: "Mark Point" },
  { mode: MODES.CIRCLE, title: "Draw buffer zone", icon: "○", label: "Buffer Zone" },
  { mode: MODES.MEASURE, title: "Measure area / distance", icon: "△", label: "Measure" },
  { mode: MODES.MODIFY, title: "Edit existing features", icon: "✎", label: "Edit" },
];

export default function DrawingToolbar({
  drawMode,
  onModeChange,
  featureCount,
  selectedIndex,
  onDeleteFeature,
  onClearAll,
  onExportGeoJSON,
  measurement,
  onAnalyseArea,
}) {
  const [expanded, setExpanded] = useState(false);
  const isDrawing = drawMode && drawMode !== MODES.VIEW;

  // Collapsed: just a small pencil button
  if (!expanded && !isDrawing) {
    return (
      <button
        className="draw-toolbar-toggle"
        onClick={() => setExpanded(true)}
        title="Drawing Tools"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
        </svg>
      </button>
    );
  }

  return (
    <div className="draw-toolbar">
      <div className="draw-toolbar-header">
        <span className="draw-toolbar-title">Draw</span>
        <button className="draw-toolbar-close" onClick={() => { setExpanded(false); onModeChange(MODES.VIEW); }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="draw-toolbar-tools">
        {TOOLS.map(t => (
          <button
            key={t.mode}
            className={`draw-tool-btn ${drawMode === t.mode ? "active" : ""}`}
            onClick={() => onModeChange(t.mode)}
            title={t.title}
          >
            <span className="draw-tool-icon">{t.icon}</span>
            <span className="draw-tool-label">{t.label}</span>
          </button>
        ))}
      </div>

      {measurement && (
        <div className="draw-measurement">
          {measurement.distance != null && (
            <div className="draw-measure-row">
              <span className="draw-measure-label">Distance</span>
              <strong>{formatDistance(measurement.distance)}</strong>
            </div>
          )}
          {measurement.area != null && (
            <div className="draw-measure-row">
              <span className="draw-measure-label">Area</span>
              <strong>{formatArea(measurement.area)}</strong>
            </div>
          )}
          {measurement.perimeter != null && (
            <div className="draw-measure-row">
              <span className="draw-measure-label">Perimeter</span>
              <strong>{formatDistance(measurement.perimeter)}</strong>
            </div>
          )}
        </div>
      )}

      {measurement?.area != null && onAnalyseArea && (
        <button className="draw-analyse-btn" onClick={onAnalyseArea} title="Run feasibility on drawn area">
          Analyse
        </button>
      )}

      {featureCount > 0 && (
        <div className="draw-features-info">
          <span className="draw-feat-count">{featureCount} feature{featureCount > 1 ? "s" : ""}</span>
          {selectedIndex >= 0 && (
            <button className="draw-action-btn danger" onClick={() => onDeleteFeature(selectedIndex)} title="Delete selected">Del</button>
          )}
          <button className="draw-action-btn" onClick={onExportGeoJSON} title="Copy GeoJSON">JSON</button>
          <button className="draw-action-btn danger" onClick={onClearAll} title="Clear all">Clear</button>
        </div>
      )}
    </div>
  );
}
