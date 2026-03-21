import React, { useState, lazy, Suspense } from "react";

const DigitalTwin = lazy(() => import("./DigitalTwin"));
const TerrainTwin = lazy(() => import("./TerrainTwin"));

/**
 * UnifiedTwin — single overlay with mode toggle between Site View and Terrain Analysis.
 *
 * Site View: satellite imagery, buildings, solar panels, trees, clouds, real infrastructure
 * Terrain Analysis: LiDAR DEM with slope/aspect/viewshed/hydrology overlays
 */
export default function UnifiedTwin({
  initialMode = "site",
  data,
  realContext,
  lat,
  lon,
  placedAssets = [],
  onClose,
}) {
  const [mode, setMode] = useState(initialMode);

  return (
    <div className="unified-twin-overlay">
      {/* Mode toggle bar */}
      <div className="unified-twin-mode-bar">
        <button
          className={`unified-twin-mode-btn${mode === "site" ? " active" : ""}`}
          onClick={() => setMode("site")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
          </svg>
          Site View
        </button>
        <button
          className={`unified-twin-mode-btn${mode === "terrain" ? " active" : ""}`}
          onClick={() => setMode("terrain")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 17l4-4 4 4 4-8 4 4" /><path d="M3 21h18" />
          </svg>
          Terrain Analysis
        </button>
        <div className="unified-twin-mode-spacer" />
        <button className="unified-twin-close" onClick={onClose} title="Close twin">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="unified-twin-content">
        <Suspense fallback={<div className="unified-twin-loading">Loading...</div>}>
          {mode === "site" ? (
            <DigitalTwin
              data={data}
              realContext={realContext}
              onClose={onClose}
            />
          ) : (
            <TerrainTwin
              lat={lat}
              lon={lon}
              zoom={14}
              placedAssets={placedAssets}
              onClose={onClose}
            />
          )}
        </Suspense>
      </div>
    </div>
  );
}
