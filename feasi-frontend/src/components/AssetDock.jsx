import React, { useState, useRef } from "react";

/**
 * AssetDock — bottom-of-screen draggable asset palette
 * Inspired by energyPRO's component library but spatial-first.
 * Assets are dragged directly onto the Mapbox map canvas.
 */

const ASSET_TYPES = [
  {
    id: "solar_array",
    label: "Solar Array",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <rect x="4" y="10" width="24" height="16" rx="2" fill="#D4A018" opacity="0.15" stroke="#D4A018" strokeWidth="1.5"/>
        <line x1="4" y1="18" x2="28" y2="18" stroke="#D4A018" strokeWidth="1" opacity="0.5"/>
        <line x1="4" y1="22" x2="28" y2="22" stroke="#D4A018" strokeWidth="1" opacity="0.5"/>
        <line x1="12" y1="10" x2="12" y2="26" stroke="#D4A018" strokeWidth="1" opacity="0.5"/>
        <line x1="20" y1="10" x2="20" y2="26" stroke="#D4A018" strokeWidth="1" opacity="0.5"/>
        <circle cx="16" cy="5" r="3" fill="#D4A018" opacity="0.6"/>
        <line x1="16" y1="8" x2="16" y2="10" stroke="#D4A018" strokeWidth="1"/>
      </svg>
    ),
    color: "#D4A018",
    category: "generation",
    defaultMW: 50,
    description: "Ground-mount PV array",
  },
  {
    id: "bess",
    label: "BESS",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <rect x="6" y="8" width="20" height="18" rx="3" fill="#16a34a" opacity="0.15" stroke="#16a34a" strokeWidth="1.5"/>
        <rect x="12" y="5" width="8" height="4" rx="1" fill="#16a34a" opacity="0.3"/>
        <path d="M16 14 L13 19 L15 19 L15 24 L19 17 L17 17 L17 14Z" fill="#16a34a" opacity="0.7"/>
      </svg>
    ),
    color: "#16a34a",
    category: "storage",
    defaultMW: 50,
    description: "Battery energy storage",
  },
  {
    id: "transformer",
    label: "Transformer",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <circle cx="12" cy="16" r="6" fill="none" stroke="#0891b2" strokeWidth="1.5"/>
        <circle cx="20" cy="16" r="6" fill="none" stroke="#0891b2" strokeWidth="1.5"/>
        <line x1="6" y1="10" x2="6" y2="22" stroke="#0891b2" strokeWidth="2"/>
        <line x1="26" y1="10" x2="26" y2="22" stroke="#0891b2" strokeWidth="2"/>
      </svg>
    ),
    color: "#0891b2",
    category: "infrastructure",
    defaultMW: null,
    description: "Step-up transformer",
  },
  {
    id: "substation",
    label: "Substation",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <rect x="6" y="10" width="20" height="14" rx="2" fill="#78909c" opacity="0.15" stroke="#78909c" strokeWidth="1.5"/>
        <line x1="10" y1="6" x2="10" y2="10" stroke="#78909c" strokeWidth="1.5"/>
        <line x1="22" y1="6" x2="22" y2="10" stroke="#78909c" strokeWidth="1.5"/>
        <circle cx="10" cy="5" r="2" fill="#78909c" opacity="0.5"/>
        <circle cx="22" cy="5" r="2" fill="#78909c" opacity="0.5"/>
        <line x1="10" y1="17" x2="22" y2="17" stroke="#78909c" strokeWidth="1" strokeDasharray="2 2"/>
      </svg>
    ),
    color: "#78909c",
    category: "infrastructure",
    defaultMW: null,
    description: "Grid substation",
  },
  {
    id: "inverter",
    label: "Inverter",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <rect x="8" y="8" width="16" height="16" rx="3" fill="#ff9800" opacity="0.15" stroke="#ff9800" strokeWidth="1.5"/>
        <path d="M12 16 Q14 12 16 16 Q18 20 20 16" fill="none" stroke="#ff9800" strokeWidth="1.5"/>
        <line x1="4" y1="16" x2="8" y2="16" stroke="#ff9800" strokeWidth="1.5"/>
        <line x1="24" y1="16" x2="28" y2="16" stroke="#ff9800" strokeWidth="1.5"/>
      </svg>
    ),
    color: "#ff9800",
    category: "infrastructure",
    defaultMW: null,
    description: "DC-AC inverter",
  },
  {
    id: "cable_33kv",
    label: "Cable 33kV",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <line x1="4" y1="16" x2="28" y2="16" stroke="#607d8b" strokeWidth="3" strokeLinecap="round"/>
        <circle cx="8" cy="16" r="3" fill="#607d8b" opacity="0.3" stroke="#607d8b" strokeWidth="1"/>
        <circle cx="24" cy="16" r="3" fill="#607d8b" opacity="0.3" stroke="#607d8b" strokeWidth="1"/>
      </svg>
    ),
    color: "#607d8b",
    category: "infrastructure",
    defaultMW: null,
    description: "33kV cable route",
  },
  {
    id: "wind_turbine",
    label: "Wind Turbine",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <line x1="16" y1="12" x2="16" y2="28" stroke="#00b0ff" strokeWidth="2"/>
        <circle cx="16" cy="12" r="2.5" fill="#00b0ff" opacity="0.3" stroke="#00b0ff" strokeWidth="1"/>
        <path d="M16 12 L16 3 L19 12Z" fill="#00b0ff" opacity="0.5"/>
        <path d="M16 12 L23 18 L16 15Z" fill="#00b0ff" opacity="0.5"/>
        <path d="M16 12 L9 18 L16 15Z" fill="#00b0ff" opacity="0.5"/>
      </svg>
    ),
    color: "#00b0ff",
    category: "generation",
    defaultMW: 5,
    description: "Onshore wind turbine",
  },
  {
    id: "meter",
    label: "Meter",
    icon: (
      <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
        <rect x="8" y="8" width="16" height="16" rx="8" fill="#e91e63" opacity="0.1" stroke="#e91e63" strokeWidth="1.5"/>
        <path d="M16 12 L16 16 L20 18" fill="none" stroke="#e91e63" strokeWidth="1.5" strokeLinecap="round"/>
        <text x="16" y="24" textAnchor="middle" fill="#e91e63" fontSize="5" fontWeight="700">MWh</text>
      </svg>
    ),
    color: "#e91e63",
    category: "monitoring",
    defaultMW: null,
    description: "Revenue meter",
  },
];

const CATEGORIES = {
  generation: "Generation",
  storage: "Storage",
  infrastructure: "Infrastructure",
  monitoring: "Monitoring",
};

export default function AssetDock({ onAssetPlaced, placedAssets = [], mapInstance }) {
  const [expanded, setExpanded] = useState(true);
  const [dragging, setDragging] = useState(null);
  const [filter, setFilter] = useState(null);
  const dragGhost = useRef(null);

  const filtered = filter
    ? ASSET_TYPES.filter((a) => a.category === filter)
    : ASSET_TYPES;

  const handleDragStart = (e, asset) => {
    setDragging(asset.id);
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData(
      "application/princeps-asset",
      JSON.stringify(asset)
    );
    // Create minimal drag image
    const ghost = document.createElement("div");
    ghost.style.cssText = `
      width: 48px; height: 48px; border-radius: 12px;
      background: ${asset.color}22; border: 2px solid ${asset.color};
      display: flex; align-items: center; justify-content: center;
      font-size: 10px; font-weight: 700; color: ${asset.color};
      position: absolute; top: -100px;
    `;
    ghost.textContent = asset.label.slice(0, 3).toUpperCase();
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 24, 24);
    dragGhost.current = ghost;
  };

  const handleDragEnd = () => {
    setDragging(null);
    if (dragGhost.current) {
      document.body.removeChild(dragGhost.current);
      dragGhost.current = null;
    }
  };

  const placedCount = (id) => placedAssets.filter((a) => a.assetType === id).length;

  return (
    <div className={`asset-dock ${expanded ? "expanded" : "collapsed"}`}>
      {/* Toggle */}
      <button
        className="asset-dock-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="asset-dock-toggle-label">
          {expanded ? "Components" : "Components"}
        </span>
        <span className="asset-dock-toggle-icon">{expanded ? "\u25BC" : "\u25B2"}</span>
      </button>

      {expanded && (
        <>
          {/* Category filters */}
          <div className="asset-dock-filters">
            <button
              className={`asset-dock-filter ${filter === null ? "active" : ""}`}
              onClick={() => setFilter(null)}
            >
              All
            </button>
            {Object.entries(CATEGORIES).map(([key, label]) => (
              <button
                key={key}
                className={`asset-dock-filter ${filter === key ? "active" : ""}`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Asset cards */}
          <div className="asset-dock-grid">
            {filtered.map((asset) => {
              const count = placedCount(asset.id);
              return (
                <div
                  key={asset.id}
                  className={`asset-dock-card ${dragging === asset.id ? "dragging" : ""}`}
                  draggable
                  onDragStart={(e) => handleDragStart(e, asset)}
                  onDragEnd={handleDragEnd}
                  title={`Drag ${asset.label} onto the map`}
                >
                  <div className="asset-dock-card-icon">{asset.icon}</div>
                  <div className="asset-dock-card-info">
                    <span className="asset-dock-card-label">{asset.label}</span>
                    <span className="asset-dock-card-desc">{asset.description}</span>
                  </div>
                  {count > 0 && (
                    <span className="asset-dock-card-badge" style={{ background: asset.color }}>
                      {count}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* Placed summary */}
          {placedAssets.length > 0 && (
            <div className="asset-dock-summary">
              <span>{placedAssets.length} component{placedAssets.length !== 1 ? "s" : ""} placed</span>
              <span className="asset-dock-summary-mw">
                {placedAssets.reduce((s, a) => s + (a.mw || 0), 0).toFixed(0)} MW total
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export { ASSET_TYPES };
