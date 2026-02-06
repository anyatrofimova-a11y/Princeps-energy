import React, { useState } from "react";

const CAT_LABELS = {
  panel: "Solar Panels",
  inverter: "Inverters",
  battery: "Battery Storage",
  mounting: "Mounting",
  cable: "Cables",
  transformer: "Transformers",
  monitoring: "Monitoring",
  bos: "Balance of System",
  fencing: "Fencing",
};

const CAT_COLORS = {
  panel: "#1e88e5",
  inverter: "#ff9800",
  battery: "#4caf50",
  mounting: "#795548",
  cable: "#607d8b",
  transformer: "#9e9e9e",
  monitoring: "#e91e63",
  bos: "#00bcd4",
  fencing: "#8d6e63",
};

export default function ComponentPalette({ catalogue, onDragStart }) {
  const [expandedCat, setExpandedCat] = useState("panel");

  if (!catalogue || !catalogue.categories) return null;

  const handleDrag = (e, comp) => {
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("application/json", JSON.stringify(comp));
    e.target.style.opacity = "0.5";
  };

  const handleDragEnd = (e) => {
    e.target.style.opacity = "1";
  };

  const spec = (comp) => {
    if (comp.watts) {
      return comp.watts >= 1000 ? `${(comp.watts / 1000).toFixed(1)}kW` : `${comp.watts}W`;
    }
    if (comp.kwh) return `${comp.kwh}kWh`;
    if (comp.kva) return `${comp.kva}kVA`;
    return comp.unit;
  };

  return (
    <div className="component-palette">
      <div className="palette-header">Component Library</div>
      <div className="palette-body">
        {Object.entries(catalogue.categories).map(([cat, items]) => (
          <div key={cat} className="palette-category">
            <div
              className="palette-cat-title"
              onClick={() => setExpandedCat(expandedCat === cat ? null : cat)}
              style={{ borderLeftColor: CAT_COLORS[cat] || "#888" }}
            >
              <span>{CAT_LABELS[cat] || cat}</span>
              <span className="palette-cat-count">{items.length}</span>
              <span className="palette-cat-toggle">{expandedCat === cat ? "\u25B2" : "\u25BC"}</span>
            </div>
            {expandedCat === cat &&
              items.map((comp) => (
                <div
                  key={comp.id}
                  className="palette-card"
                  draggable
                  onDragStart={(e) => handleDrag(e, comp)}
                  onDragEnd={handleDragEnd}
                >
                  <div className="palette-card-row">
                    <span
                      className="palette-card-dot"
                      style={{ background: CAT_COLORS[cat] || "#888" }}
                    />
                    <span className="palette-card-name">{comp.name}</span>
                  </div>
                  <div className="palette-card-meta">
                    <span>{spec(comp)}</span>
                    {comp.efficiency && (
                      <span>{(comp.efficiency * 100).toFixed(1)}% eff</span>
                    )}
                    <span className="palette-card-cost">
                      £{comp.unit_cost_gbp.toLocaleString()}/{comp.unit}
                    </span>
                  </div>
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
