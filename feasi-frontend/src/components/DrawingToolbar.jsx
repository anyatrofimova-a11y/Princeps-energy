import React from "react";
import { MODES, formatArea, formatDistance } from "../lib/draw-modes";

const TOOLS = [
  { mode: MODES.VIEW, label: "V", title: "View (Esc)", icon: "\u25C7" },
  { mode: MODES.POINT, label: "P", title: "Draw Point", icon: "\u25CF" },
  { mode: MODES.LINE, label: "L", title: "Draw Line", icon: "\u2571" },
  { mode: MODES.POLYGON, label: "Pg", title: "Draw Polygon", icon: "\u2B21" },
  { mode: MODES.RECTANGLE, label: "R", title: "Draw Rectangle", icon: "\u25AD" },
  { mode: MODES.CIRCLE, label: "C", title: "Draw Circle", icon: "\u25CB" },
  { mode: MODES.MODIFY, label: "M", title: "Modify Features", icon: "\u270E" },
  { mode: MODES.MEASURE, label: "\u0394", title: "Measure Area/Distance", icon: "\u25B3" },
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
  return (
    <div className="draw-toolbar">
      <div className="draw-toolbar-title">Draw</div>
      <div className="draw-toolbar-tools">
        {TOOLS.map(t => (
          <button
            key={t.mode}
            className={`draw-tool-btn ${drawMode === t.mode ? "active" : ""}`}
            onClick={() => onModeChange(t.mode)}
            title={t.title}
          >
            <span className="draw-tool-icon">{t.icon}</span>
          </button>
        ))}
      </div>

      {/* Measurement display */}
      {measurement && (
        <div className="draw-measurement">
          {measurement.distance != null && (
            <div className="draw-measure-row">
              Dist: <strong>{formatDistance(measurement.distance)}</strong>
            </div>
          )}
          {measurement.area != null && (
            <div className="draw-measure-row">
              Area: <strong>{formatArea(measurement.area)}</strong>
            </div>
          )}
          {measurement.perimeter != null && (
            <div className="draw-measure-row">
              Perim: <strong>{formatDistance(measurement.perimeter)}</strong>
            </div>
          )}
        </div>
      )}

      {/* Feature management */}
      {featureCount > 0 && (
        <div className="draw-features-info">
          <span className="draw-feat-count">{featureCount} feature{featureCount > 1 ? "s" : ""}</span>
          {selectedIndex >= 0 && (
            <button className="draw-action-btn danger" onClick={() => onDeleteFeature(selectedIndex)} title="Delete selected feature">
              Del
            </button>
          )}
          <button className="draw-action-btn" onClick={onExportGeoJSON} title="Copy GeoJSON">
            JSON
          </button>
          <button className="draw-action-btn danger" onClick={onClearAll} title="Clear all features">
            Clear
          </button>
        </div>
      )}

      {/* Mode hint */}
      <div className="draw-hint">
        {drawMode === MODES.VIEW && "Select a tool to start drawing"}
        {drawMode === MODES.POINT && "Click to place point"}
        {drawMode === MODES.LINE && "Click to add vertices, double-click to finish"}
        {drawMode === MODES.POLYGON && "Click to add vertices, click first point or double-click to close"}
        {drawMode === MODES.RECTANGLE && "Click corner, then opposite corner"}
        {drawMode === MODES.CIRCLE && "Click center, then edge"}
        {drawMode === MODES.MODIFY && "Click feature to select, drag vertices to edit"}
        {drawMode === MODES.MEASURE && "Click to measure distance/area"}
      </div>
    </div>
  );
}
