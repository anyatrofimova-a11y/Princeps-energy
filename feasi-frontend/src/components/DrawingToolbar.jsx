import React from "react";
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
}) {
  const isDrawing = drawMode && drawMode !== MODES.VIEW;

  return (
    <div className="draw-toolbar">
      <div className="draw-toolbar-title">Site Tools</div>
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

      {/* Measurement display */}
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

      {/* Feature management */}
      {featureCount > 0 && (
        <div className="draw-features-info">
          <span className="draw-feat-count">{featureCount} feature{featureCount > 1 ? "s" : ""}</span>
          {selectedIndex >= 0 && (
            <button className="draw-action-btn danger" onClick={() => onDeleteFeature(selectedIndex)} title="Delete selected">
              Del
            </button>
          )}
          <button className="draw-action-btn" onClick={onExportGeoJSON} title="Copy GeoJSON">
            JSON
          </button>
          <button className="draw-action-btn danger" onClick={onClearAll} title="Clear all">
            Clear
          </button>
        </div>
      )}

      {/* Contextual hint */}
      <div className="draw-hint">
        {drawMode === MODES.VIEW && "Select a tool to draw on the map"}
        {drawMode === MODES.POINT && "Click to mark a point of interest"}
        {drawMode === MODES.LINE && "Click to add points — double-click to finish route"}
        {drawMode === MODES.POLYGON && "Click to draw site boundary — click first point to close"}
        {drawMode === MODES.RECTANGLE && "Click one corner, then the opposite corner"}
        {drawMode === MODES.CIRCLE && "Click centre, then drag to set radius"}
        {drawMode === MODES.MODIFY && "Click a feature to select — drag vertices to reshape"}
        {drawMode === MODES.MEASURE && "Click points to measure distance and area"}
      </div>
    </div>
  );
}
