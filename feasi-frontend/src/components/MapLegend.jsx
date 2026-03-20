import React, { useState } from "react";

/**
 * Auto-generated map legend for active chat/analysis layers.
 * Renders appropriate swatches for each layer type: circle, fill, fill-pattern, symbol, line, heatmap.
 */
export default function MapLegend({ chatLayers = [], title = "Site Analysis" }) {
  const [collapsed, setCollapsed] = useState(false);

  if (!chatLayers.length) return null;

  return (
    <div className={`map-legend${collapsed ? " collapsed" : ""}`}>
      <button className="map-legend-header" onClick={() => setCollapsed(c => !c)}>
        <span className="map-legend-title">{title}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"
          style={{ transform: collapsed ? "rotate(-90deg)" : "rotate(0)", transition: "transform 0.15s" }}>
          <path d="M3 4.5l3 3 3-3" />
        </svg>
      </button>
      {!collapsed && (
        <div className="map-legend-items">
          {chatLayers.map(layer => (
            <LegendItem key={layer.id} layer={layer} />
          ))}
        </div>
      )}
    </div>
  );
}

function LegendItem({ layer }) {
  const { name, layer_type, color, style = {} } = layer;
  const type = layer_type || "circle";

  // If layer has color_map, show sub-items
  if (style.color_field && style.color_map && Object.keys(style.color_map).length > 0) {
    return (
      <div className="map-legend-group">
        <div className="map-legend-group-label">{name}</div>
        {Object.entries(style.color_map).map(([value, clr]) => (
          <div key={value} className="map-legend-item">
            <LegendSwatch type={type} color={clr} style={style} />
            <span className="map-legend-label">{value}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="map-legend-item">
      <LegendSwatch type={type} color={color} style={style} />
      <span className="map-legend-label">{name}</span>
    </div>
  );
}

function LegendSwatch({ type, color = "#7c5cfc", style = {} }) {
  if (type === "symbol") {
    const iconName = style.icon || "substation";
    return <img src={`/icons/${iconName}.svg`} className="legend-swatch-icon" alt="" />;
  }

  if (type === "fill-pattern") {
    const patternColor = color || "#4a6fa5";
    return (
      <svg className="legend-swatch-svg" width="20" height="16" viewBox="0 0 20 16">
        <rect width="20" height="16" fill={patternColor} fillOpacity="0.15" stroke={patternColor} strokeWidth="1" rx="2" />
        <line x1="0" y1="16" x2="8" y2="0" stroke={patternColor} strokeWidth="1" opacity="0.6" />
        <line x1="6" y1="16" x2="14" y2="0" stroke={patternColor} strokeWidth="1" opacity="0.6" />
        <line x1="12" y1="16" x2="20" y2="0" stroke={patternColor} strokeWidth="1" opacity="0.6" />
      </svg>
    );
  }

  if (type === "fill") {
    return (
      <svg className="legend-swatch-svg" width="20" height="16" viewBox="0 0 20 16">
        <rect width="20" height="16" fill={color} fillOpacity="0.35" stroke={color} strokeWidth="1" rx="2" />
      </svg>
    );
  }

  if (type === "line") {
    const dashArray = style.dash_array;
    return (
      <svg className="legend-swatch-svg" width="20" height="16" viewBox="0 0 20 16">
        <line x1="0" y1="8" x2="20" y2="8" stroke={color}
          strokeWidth={style.line_width || 2}
          strokeDasharray={dashArray ? dashArray.join(",") : "none"} />
      </svg>
    );
  }

  if (type === "heatmap") {
    return (
      <svg className="legend-swatch-svg" width="20" height="16" viewBox="0 0 20 16">
        <defs>
          <radialGradient id="hg"><stop offset="0%" stopColor="#ff0" /><stop offset="100%" stopColor="#f00" stopOpacity="0.3" /></radialGradient>
        </defs>
        <rect width="20" height="16" fill="url(#hg)" rx="2" />
      </svg>
    );
  }

  // Default: circle
  return (
    <span className="legend-swatch-dot" style={{ background: color }} />
  );
}
