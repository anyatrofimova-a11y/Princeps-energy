/**
 * SiteDesignToolbar — floating drawing toolbar for the 3D site designer.
 *
 * Provides polygon draw, exclusion zones, access roads, point placement,
 * measurement tools, and undo. Bottom-center of screen.
 */
import React, { useState } from "react";

const TOOLS = [
  { id: "polygon",   label: "Draw Boundary",   icon: "\u2B1F", tip: "Click vertices, double-click to close" },
  { id: "exclusion", label: "Exclusion Zone",   icon: "\u26D4", tip: "Draw exclusion polygon" },
  { id: "road",      label: "Access Road",      icon: "\u2550", tip: "Click waypoints for road path" },
  { id: "point",     label: "Place Point",      icon: "\u2316", tip: "Place substation, inverter, or gate" },
  { id: "measure_d", label: "Measure Distance", icon: "\u21D4", tip: "Click two points to measure" },
  { id: "measure_a", label: "Measure Area",     icon: "\u25A2", tip: "Click polygon to measure area" },
  { id: "undo",      label: "Undo",             icon: "\u21A9", tip: "Undo last action" },
];

const POINT_TYPES = [
  { id: "substation", label: "Substation" },
  { id: "inverter",   label: "Inverter" },
  { id: "gate",       label: "Gate" },
  { id: "transformer",label: "Transformer" },
];

export default function SiteDesignToolbar({
  activeTool,
  onToolSelect,
  onUndo,
  onClear,
  pointType,
  onPointTypeChange,
  measurement,
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="sd-toolbar">
      <div className="sd-toolbar-inner">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            className={`sd-tool-btn ${activeTool === t.id ? "sd-tool-active" : ""}`}
            onClick={() => {
              if (t.id === "undo") { onUndo?.(); return; }
              onToolSelect?.(activeTool === t.id ? null : t.id);
            }}
            title={t.tip}
          >
            <span className="sd-tool-icon">{t.icon}</span>
            <span className="sd-tool-label">{t.label}</span>
          </button>
        ))}

        <div className="sd-toolbar-sep" />

        <button
          className="sd-tool-btn sd-tool-danger"
          onClick={onClear}
          title="Clear all drawn elements"
        >
          <span className="sd-tool-icon">&#x2715;</span>
          <span className="sd-tool-label">Clear</span>
        </button>
      </div>

      {/* Point type selector */}
      {activeTool === "point" && (
        <div className="sd-point-picker">
          {POINT_TYPES.map((pt) => (
            <button
              key={pt.id}
              className={`sd-point-btn ${pointType === pt.id ? "sd-point-active" : ""}`}
              onClick={() => onPointTypeChange?.(pt.id)}
            >
              {pt.label}
            </button>
          ))}
        </div>
      )}

      {/* Measurement display */}
      {measurement && (
        <div className="sd-measurement">
          {measurement.type === "distance" && `${measurement.value.toFixed(1)} m`}
          {measurement.type === "area" && `${(measurement.value / 10000).toFixed(3)} ha`}
        </div>
      )}
    </div>
  );
}
