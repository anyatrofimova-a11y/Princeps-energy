import React from "react";

export default function LayoutControls({
  selectedItem,
  layout,
  onUpdate,
  onDelete,
  catalogue,
}) {
  if (!selectedItem) {
    return <div className="layout-controls-empty">Drop components onto the 3D view above, then click to edit</div>;
  }

  const item = layout.find((i) => i.id === selectedItem);
  if (!item) return null;

  // Find component in catalogue categories
  let component = null;
  if (catalogue?.categories) {
    for (const items of Object.values(catalogue.categories)) {
      const found = items.find((c) => c.id === item.componentId);
      if (found) { component = found; break; }
    }
  }
  if (!component) return null;

  const handleChange = (field, value) => {
    onUpdate(item.id, { ...item, [field]: value });
  };

  const totalCost = component.unit_cost_gbp * item.quantity;

  return (
    <div className="layout-controls">
      <div className="layout-ctrl-header">
        <strong>{component.name}</strong>
        <button className="btn-delete" onClick={() => onDelete(item.id)}>Remove</button>
      </div>
      <div className="layout-ctrl-grid">
        <label>
          Qty
          <input type="number" value={item.quantity} min={1} max={9999}
            onChange={(e) => handleChange("quantity", Math.max(1, parseInt(e.target.value) || 1))} />
        </label>
        <label>
          Rotation
          <input type="number" value={item.rotation || 0} step={15} min={0} max={360}
            onChange={(e) => handleChange("rotation", parseFloat(e.target.value) || 0)} />
        </label>
        <label>
          X
          <input type="number" value={item.x?.toFixed(1)} step={1}
            onChange={(e) => handleChange("x", parseFloat(e.target.value) || 0)} />
        </label>
        <label>
          Y
          <input type="number" value={item.y?.toFixed(1)} step={1}
            onChange={(e) => handleChange("y", parseFloat(e.target.value) || 0)} />
        </label>
      </div>
      <div className="layout-ctrl-cost">
        <span>£{component.unit_cost_gbp.toLocaleString()}/{component.unit} × {item.quantity}</span>
        <strong>= £{totalCost.toLocaleString()}</strong>
      </div>
    </div>
  );
}
