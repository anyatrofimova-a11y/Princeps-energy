/**
 * LayerControlPanel — GIS Filters + Layers panel (top-right, Glint Solar style).
 *
 * Two floating buttons: "Filters" and "Layers" that expand into white dropdown panels.
 * Professional GIS tool aesthetic with toggle switches, opacity sliders, and
 * gold accent for active states.
 *
 * Props:
 *   layers         — { landParcels, landClassification, gridInfra, energyAssets,
 *                      floodZones, protectedAreas, alcGrades, slopeAnalysis,
 *                      constraintPins, satellite, buildings }
 *   onLayerChange  — callback(layerKey, { visible, opacity })
 *   filters        — { minArea, maxArea, tenure, alcGrades[], maxSlope,
 *                      excludeFloodZone2, excludeFloodZone3, maxGridDistance }
 *   onFilterChange — callback(newFilters)
 */
import React, { useState, useRef, useEffect } from "react";

const LAYER_DEFS = [
  { key: "landParcels", label: "Land Parcels", color: "#c040ff", group: "Land" },
  { key: "landClassification", label: "Land Classification", color: "#34a853", group: "Land" },
  { key: "gridInfra", label: "Grid Infrastructure", color: "#1e88e5", group: "Infrastructure" },
  { key: "energyAssets", label: "Energy Assets", color: "#fdd835", group: "Infrastructure" },
  { key: "floodZones", label: "Flood Zones", color: "#0288d1", group: "Constraints" },
  { key: "protectedAreas", label: "Protected Areas", color: "#2e7d32", group: "Constraints" },
  { key: "alcGrades", label: "Agricultural Land Class.", color: "#8d6e63", group: "Constraints" },
  { key: "slopeAnalysis", label: "Slope Analysis", color: "#ff6f00", group: "Analysis" },
  { key: "constraintPins", label: "Constraint Pins", color: "#e53935", group: "Constraints" },
  { key: "satellite", label: "Satellite Imagery", color: "#78909c", group: "Base" },
  { key: "buildings", label: "3D Buildings", color: "#9e9e9e", group: "Base" },
];

const ALC_GRADES = ["Grade 1", "Grade 2", "Grade 3a", "Grade 3b", "Grade 4", "Grade 5"];
const TENURE_OPTIONS = ["All", "Freehold", "Leasehold"];

export default function LayerControlPanel({
  layers = {},
  onLayerChange,
  filters = {},
  onFilterChange,
}) {
  const [layersOpen, setLayersOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const layerRef = useRef(null);
  const filterRef = useRef(null);

  // Close panels when clicking outside
  useEffect(() => {
    const handleClick = (e) => {
      if (layerRef.current && !layerRef.current.contains(e.target)) {
        setLayersOpen(false);
      }
      if (filterRef.current && !filterRef.current.contains(e.target)) {
        setFiltersOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const toggleLayer = (key) => {
    const current = layers[key] || { visible: false, opacity: 1 };
    onLayerChange?.(key, { ...current, visible: !current.visible });
  };

  const setOpacity = (key, val) => {
    const current = layers[key] || { visible: true, opacity: 1 };
    onLayerChange?.(key, { ...current, opacity: val / 100 });
  };

  const updateFilter = (key, val) => {
    onFilterChange?.({ ...filters, [key]: val });
  };

  const toggleAlcGrade = (grade) => {
    const current = filters.alcGrades || [];
    const next = current.includes(grade)
      ? current.filter(g => g !== grade)
      : [...current, grade];
    updateFilter("alcGrades", next);
  };

  // Group layers
  const groups = {};
  for (const def of LAYER_DEFS) {
    if (!groups[def.group]) groups[def.group] = [];
    groups[def.group].push(def);
  }

  return (
    <div className="lyc-container">
      {/* Button bar */}
      <div className="lyc-buttons">
        <div ref={filterRef} className="lyc-btn-wrapper">
          <button
            className={`lyc-btn ${filtersOpen ? "lyc-btn-active" : ""}`}
            onClick={() => { setFiltersOpen(!filtersOpen); setLayersOpen(false); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
            Filters
          </button>

          {/* Filters dropdown */}
          {filtersOpen && (
            <div className="lyc-dropdown lyc-filter-dropdown">
              <div className="lyc-dropdown-title">Filters</div>

              {/* Area range */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">Parcel area (ha)</div>
                <div className="lyc-filter-range">
                  <input
                    type="number"
                    className="lyc-filter-input"
                    placeholder="Min"
                    value={filters.minArea || ""}
                    onChange={(e) => updateFilter("minArea", e.target.value ? Number(e.target.value) : null)}
                    min={0}
                    step={0.5}
                  />
                  <span className="lyc-filter-sep">--</span>
                  <input
                    type="number"
                    className="lyc-filter-input"
                    placeholder="Max"
                    value={filters.maxArea || ""}
                    onChange={(e) => updateFilter("maxArea", e.target.value ? Number(e.target.value) : null)}
                    min={0}
                    step={0.5}
                  />
                </div>
              </div>

              {/* Tenure */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">Tenure type</div>
                <div className="lyc-filter-pills">
                  {TENURE_OPTIONS.map(t => (
                    <button
                      key={t}
                      className={`lyc-pill ${(filters.tenure || "All") === t ? "lyc-pill-active" : ""}`}
                      onClick={() => updateFilter("tenure", t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* ALC Grades */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">ALC Grade</div>
                <div className="lyc-filter-checks">
                  {ALC_GRADES.map(g => (
                    <label key={g} className="lyc-checkbox-label">
                      <input
                        type="checkbox"
                        checked={(filters.alcGrades || []).includes(g)}
                        onChange={() => toggleAlcGrade(g)}
                      />
                      <span>{g}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Max slope */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">
                  Max slope: {filters.maxSlope ?? 30}&deg;
                </div>
                <input
                  type="range"
                  className="lyc-slider"
                  min={0} max={30} step={1}
                  value={filters.maxSlope ?? 30}
                  onChange={(e) => updateFilter("maxSlope", Number(e.target.value))}
                />
              </div>

              {/* Flood zones */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">Exclude flood zones</div>
                <div className="lyc-filter-checks">
                  <label className="lyc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={!!filters.excludeFloodZone2}
                      onChange={(e) => updateFilter("excludeFloodZone2", e.target.checked)}
                    />
                    <span>Zone 2</span>
                  </label>
                  <label className="lyc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={!!filters.excludeFloodZone3}
                      onChange={(e) => updateFilter("excludeFloodZone3", e.target.checked)}
                    />
                    <span>Zone 3</span>
                  </label>
                </div>
              </div>

              {/* Distance to grid */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">
                  Max distance to grid: {filters.maxGridDistance ?? 20} km
                </div>
                <input
                  type="range"
                  className="lyc-slider"
                  min={0} max={50} step={1}
                  value={filters.maxGridDistance ?? 20}
                  onChange={(e) => updateFilter("maxGridDistance", Number(e.target.value))}
                />
              </div>
            </div>
          )}
        </div>

        <div ref={layerRef} className="lyc-btn-wrapper">
          <button
            className={`lyc-btn ${layersOpen ? "lyc-btn-active" : ""}`}
            onClick={() => { setLayersOpen(!layersOpen); setFiltersOpen(false); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="12 2 2 7 12 12 22 7 12 2" />
              <polyline points="2 17 12 22 22 17" />
              <polyline points="2 12 12 17 22 12" />
            </svg>
            Layers
          </button>

          {/* Layers dropdown */}
          {layersOpen && (
            <div className="lyc-dropdown lyc-layer-dropdown">
              <div className="lyc-dropdown-title">Layers</div>

              {Object.entries(groups).map(([group, defs]) => (
                <div key={group} className="lyc-layer-group">
                  <div className="lyc-layer-group-title">{group}</div>
                  {defs.map(def => {
                    const state = layers[def.key] || { visible: false, opacity: 1 };
                    const isVisible = state.visible;
                    const opacityVal = Math.round((state.opacity ?? 1) * 100);

                    return (
                      <div key={def.key} className="lyc-layer-row">
                        <div className="lyc-layer-toggle-row">
                          <span
                            className="lyc-layer-dot"
                            style={{ background: isVisible ? def.color : "#ccc" }}
                          />
                          <span className="lyc-layer-name">{def.label}</span>
                          <button
                            className={`lyc-toggle ${isVisible ? "lyc-toggle-on" : ""}`}
                            onClick={() => toggleLayer(def.key)}
                            aria-label={`Toggle ${def.label}`}
                          >
                            <span className="lyc-toggle-thumb" />
                          </button>
                        </div>
                        {isVisible && (
                          <div className="lyc-opacity-row">
                            <span className="lyc-opacity-label">Opacity</span>
                            <input
                              type="range"
                              className="lyc-opacity-slider"
                              min={0} max={100} step={5}
                              value={opacityVal}
                              onChange={(e) => setOpacity(def.key, Number(e.target.value))}
                            />
                            <span className="lyc-opacity-val">{opacityVal}%</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
