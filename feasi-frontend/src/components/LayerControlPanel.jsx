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
 *   onApplyFilters — callback(filters) — called when user clicks Apply Filters
 */
import React, { useState, useRef, useEffect, useMemo } from "react";

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

const DEFAULT_FILTERS = {
  minArea: null,
  maxArea: null,
  tenure: "All",
  alcGrades: [],
  maxSlope: 30,
  excludeFloodZone2: false,
  excludeFloodZone3: false,
  maxGridDistance: 20,
};

/** Count how many filters are actively constraining results. */
function countActiveFilters(f) {
  let n = 0;
  if (f.minArea != null && f.minArea > 0) n++;
  if (f.maxArea != null) n++;
  if (f.tenure && f.tenure !== "All") n++;
  if (f.alcGrades && f.alcGrades.length > 0) n++;
  if (f.maxSlope != null && f.maxSlope < 30) n++;
  if (f.excludeFloodZone2) n++;
  if (f.excludeFloodZone3) n++;
  if (f.maxGridDistance != null && f.maxGridDistance < 20) n++;
  return n;
}

/** Build human-readable chip labels for active filters. */
function buildFilterChips(f) {
  const chips = [];
  if (f.tenure && f.tenure !== "All")
    chips.push({ key: "tenure", label: `${f.tenure} only` });
  if (f.minArea != null && f.minArea > 0)
    chips.push({ key: "minArea", label: `> ${f.minArea} ha` });
  if (f.maxArea != null)
    chips.push({ key: "maxArea", label: `< ${f.maxArea} ha` });
  if (f.alcGrades && f.alcGrades.length > 0)
    chips.push({ key: "alcGrades", label: `ALC: ${f.alcGrades.join(", ")}` });
  if (f.maxSlope != null && f.maxSlope < 30)
    chips.push({ key: "maxSlope", label: `Slope < ${f.maxSlope}\u00b0` });
  if (f.excludeFloodZone2)
    chips.push({ key: "excludeFloodZone2", label: "No Flood Zone 2" });
  if (f.excludeFloodZone3)
    chips.push({ key: "excludeFloodZone3", label: "No Flood Zone 3" });
  if (f.maxGridDistance != null && f.maxGridDistance < 20)
    chips.push({ key: "maxGridDistance", label: `Grid < ${f.maxGridDistance} km` });
  return chips;
}

export default function LayerControlPanel({
  layers = {},
  onLayerChange,
  filters = {},
  onFilterChange,
  onApplyFilters,
}) {
  const [layersOpen, setLayersOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Draft filters: edited in the dropdown, only committed on "Apply"
  const [draftFilters, setDraftFilters] = useState(filters);
  const layerRef = useRef(null);
  const filterRef = useRef(null);

  // Sync draft when external filters change
  useEffect(() => {
    setDraftFilters(filters);
  }, [filters]);

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

  const updateDraft = (key, val) => {
    setDraftFilters(prev => ({ ...prev, [key]: val }));
  };

  const toggleAlcGrade = (grade) => {
    const current = draftFilters.alcGrades || [];
    const next = current.includes(grade)
      ? current.filter(g => g !== grade)
      : [...current, grade];
    updateDraft("alcGrades", next);
  };

  const handleApply = () => {
    onFilterChange?.(draftFilters);
    onApplyFilters?.(draftFilters);
    setFiltersOpen(false);
  };

  const handleClearAll = () => {
    const cleared = { ...DEFAULT_FILTERS };
    setDraftFilters(cleared);
    onFilterChange?.(cleared);
    onApplyFilters?.(cleared);
  };

  /** Remove a single filter chip */
  const removeChip = (chipKey) => {
    const updated = { ...filters };
    if (chipKey === "tenure") updated.tenure = "All";
    else if (chipKey === "minArea") updated.minArea = null;
    else if (chipKey === "maxArea") updated.maxArea = null;
    else if (chipKey === "alcGrades") updated.alcGrades = [];
    else if (chipKey === "maxSlope") updated.maxSlope = 30;
    else if (chipKey === "excludeFloodZone2") updated.excludeFloodZone2 = false;
    else if (chipKey === "excludeFloodZone3") updated.excludeFloodZone3 = false;
    else if (chipKey === "maxGridDistance") updated.maxGridDistance = 20;
    setDraftFilters(updated);
    onFilterChange?.(updated);
    onApplyFilters?.(updated);
  };

  const activeCount = useMemo(() => countActiveFilters(filters), [filters]);
  const chips = useMemo(() => buildFilterChips(filters), [filters]);

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
            className={`lyc-btn ${filtersOpen ? "lyc-btn-active" : ""} ${activeCount > 0 ? "lyc-btn-has-filters" : ""}`}
            onClick={() => { setFiltersOpen(!filtersOpen); setLayersOpen(false); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
            Filters{activeCount > 0 ? ` (${activeCount})` : ""}
            {activeCount > 0 && <span className="lyc-filter-badge">{activeCount}</span>}
          </button>

          {/* Filters dropdown */}
          {filtersOpen && (
            <div className="lyc-dropdown lyc-filter-dropdown">
              <div className="lyc-dropdown-header">
                <div className="lyc-dropdown-title">Filters</div>
                {activeCount > 0 && (
                  <button className="lyc-clear-all" onClick={handleClearAll}>
                    Clear all
                  </button>
                )}
              </div>

              {/* Area range */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">Parcel area (ha)</div>
                <div className="lyc-filter-range">
                  <input
                    type="number"
                    className="lyc-filter-input"
                    placeholder="Min"
                    value={draftFilters.minArea || ""}
                    onChange={(e) => updateDraft("minArea", e.target.value ? Number(e.target.value) : null)}
                    min={0}
                    step={0.5}
                  />
                  <span className="lyc-filter-sep">--</span>
                  <input
                    type="number"
                    className="lyc-filter-input"
                    placeholder="Max"
                    value={draftFilters.maxArea || ""}
                    onChange={(e) => updateDraft("maxArea", e.target.value ? Number(e.target.value) : null)}
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
                      className={`lyc-pill ${(draftFilters.tenure || "All") === t ? "lyc-pill-active" : ""}`}
                      onClick={() => updateDraft("tenure", t)}
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
                        checked={(draftFilters.alcGrades || []).includes(g)}
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
                  Max slope: {draftFilters.maxSlope ?? 30}&deg;
                </div>
                <input
                  type="range"
                  className="lyc-slider"
                  min={0} max={30} step={1}
                  value={draftFilters.maxSlope ?? 30}
                  onChange={(e) => updateDraft("maxSlope", Number(e.target.value))}
                />
              </div>

              {/* Flood zones */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">Exclude flood zones</div>
                <div className="lyc-filter-checks">
                  <label className="lyc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={!!draftFilters.excludeFloodZone2}
                      onChange={(e) => updateDraft("excludeFloodZone2", e.target.checked)}
                    />
                    <span>Zone 2</span>
                  </label>
                  <label className="lyc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={!!draftFilters.excludeFloodZone3}
                      onChange={(e) => updateDraft("excludeFloodZone3", e.target.checked)}
                    />
                    <span>Zone 3</span>
                  </label>
                </div>
              </div>

              {/* Distance to grid */}
              <div className="lyc-filter-group">
                <div className="lyc-filter-label">
                  Max distance to grid: {draftFilters.maxGridDistance ?? 20} km
                </div>
                <input
                  type="range"
                  className="lyc-slider"
                  min={0} max={50} step={1}
                  value={draftFilters.maxGridDistance ?? 20}
                  onChange={(e) => updateDraft("maxGridDistance", Number(e.target.value))}
                />
              </div>

              {/* Apply button */}
              <div className="lyc-filter-actions">
                <button className="lyc-apply-btn" onClick={handleApply}>
                  Apply Filters
                </button>
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

      {/* ── Active filter chips strip ── */}
      {chips.length > 0 && (
        <div className="lyc-chip-strip">
          {chips.map(chip => (
            <span key={chip.key} className="lyc-chip" onClick={() => removeChip(chip.key)}>
              {chip.label}
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
