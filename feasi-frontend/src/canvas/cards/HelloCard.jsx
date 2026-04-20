/**
 * HelloCard — placeholder right-rail card for the L1 canvas.
 *
 * Real cards will replace this. Contract for card components:
 *
 *   props.polygon     — GeoJSON Feature | null (currently-drawn polygon)
 *   props.projectId   — string | null
 *   props.assetClass  — 'solar' | 'wind' | 'bess' | 'dc' | 'hybrid'
 */
import React from "react";

export default function HelloCard({ polygon, projectId, assetClass }) {
  const hasPolygon = !!polygon?.geometry;
  return (
    <div className="pc-card">
      <h3 className="pc-card-title">Canvas Ready</h3>
      <div style={{ fontSize: 13, color: "var(--ink)", lineHeight: 1.5 }}>
        Asset class: <strong>{assetClass}</strong>
      </div>
      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 6 }}>
        Project: {projectId || "(none)"}
      </div>
      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 6 }}>
        {hasPolygon
          ? "Polygon drawn — cards will analyse this geometry."
          : "Draw a polygon on the map to begin."}
      </div>
    </div>
  );
}
