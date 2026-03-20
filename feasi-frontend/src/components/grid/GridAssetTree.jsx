import React, { useState, useMemo, useCallback } from "react";
import { useGridModel } from "../../contexts/GridModelContext";
import { RagDot } from "./StatusBadge";

// Group substations by licence area
function groupByRegion(subs) {
  const groups = {};
  for (const s of subs) {
    const key = s.licenceArea || "Unknown";
    (groups[key] ||= []).push(s);
  }
  // Sort groups by count descending, sort subs within by name
  return Object.entries(groups)
    .sort((a, b) => b[1].length - a[1].length)
    .map(([region, items]) => ({
      region,
      items: items.sort((a, b) => (a.name || "").localeCompare(b.name || "")),
      constrained: items.filter(s => s.demandRag === "Red" || s.genRag === "Red").length,
    }));
}

const VOLTAGE_OPTIONS = [
  { value: "", label: "All voltages" },
  { value: "400", label: "400 kV" },
  { value: "275", label: "275 kV" },
  { value: "132", label: "132 kV" },
  { value: "33", label: "33 kV" },
  { value: "11", label: "11 kV" },
];

const CONSTRAINT_OPTIONS = [
  { value: "", label: "All status" },
  { value: "Thermal", label: "Thermal" },
  { value: "Voltage", label: "Voltage" },
  { value: "Fault Level", label: "Fault Level" },
];

export default function GridAssetTree() {
  const {
    filteredSubstations, filters, updateFilter,
    selectedSubstation, selectSubstation,
    insights, loading,
  } = useGridModel();

  const [expandedRegions, setExpandedRegions] = useState(new Set());
  const [sortBy, setSortBy] = useState("name"); // name | headroom | constraint

  const toggleRegion = useCallback((region) => {
    setExpandedRegions(prev => {
      const next = new Set(prev);
      if (next.has(region)) next.delete(region);
      else next.add(region);
      return next;
    });
  }, []);

  // Sorted + grouped
  const grouped = useMemo(() => {
    let sorted = [...filteredSubstations];
    if (sortBy === "headroom") {
      sorted.sort((a, b) => (a.demandHeadroomMw ?? 999) - (b.demandHeadroomMw ?? 999));
    } else if (sortBy === "constraint") {
      const prio = { Red: 0, Amber: 1, Green: 2 };
      sorted.sort((a, b) => (prio[a.demandRag] ?? 3) - (prio[b.demandRag] ?? 3));
    }
    return groupByRegion(sorted);
  }, [filteredSubstations, sortBy]);

  return (
    <div className="grid-asset-tree">
      {/* AI Insights Feed */}
      {insights.length > 0 && (
        <div className="gat-insights">
          {insights.map((ins, i) => (
            <button
              key={i}
              className={`gat-insight gat-insight--${ins.type}`}
              onClick={ins.action || undefined}
              disabled={!ins.action}
            >
              <span className="gat-insight-icon">
                {ins.type === "warning" ? "!" : ins.type === "caution" ? "~" : "i"}
              </span>
              <span className="gat-insight-text">{ins.text}</span>
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="gat-search">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
        </svg>
        <input
          type="text"
          placeholder="Search substations..."
          value={filters.search}
          onChange={(e) => updateFilter("search", e.target.value)}
        />
      </div>

      {/* Filter chips */}
      <div className="gat-filters">
        <select
          className="gat-filter-select"
          value={filters.voltage}
          onChange={(e) => updateFilter("voltage", e.target.value)}
        >
          {VOLTAGE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          className="gat-filter-select"
          value={filters.constraint}
          onChange={(e) => updateFilter("constraint", e.target.value)}
        >
          {CONSTRAINT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          className="gat-filter-select"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
        >
          <option value="name">Sort: Name</option>
          <option value="headroom">Sort: Headroom</option>
          <option value="constraint">Sort: Constraint</option>
        </select>
      </div>

      {/* Count */}
      <div className="gat-count">
        {loading ? "Loading..." : `${filteredSubstations.length} substations`}
      </div>

      {/* Tree */}
      <div className="gat-tree">
        {grouped.map(({ region, items, constrained }) => (
          <div key={region} className="gat-region">
            <button
              className="gat-region-header"
              onClick={() => toggleRegion(region)}
            >
              <svg
                width="10" height="10" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" strokeWidth="2"
                className={`gat-chevron ${expandedRegions.has(region) ? "expanded" : ""}`}
              >
                <path d="M9 18l6-6-6-6" />
              </svg>
              <span className="gat-region-name">{region}</span>
              <span className="gat-region-count">{items.length}</span>
              {constrained > 0 && (
                <span className="gat-region-warn">{constrained} constrained</span>
              )}
            </button>

            {expandedRegions.has(region) && (
              <div className="gat-region-items">
                {items.map((sub) => {
                  const isSelected = selectedSubstation?.id === sub.id;
                  return (
                    <button
                      key={sub.id}
                      className={`gat-node ${isSelected ? "selected" : ""}`}
                      onClick={() => selectSubstation(sub)}
                    >
                      <RagDot rag={sub.demandRag || sub.genRag} size={6} />
                      <span className="gat-node-name">{sub.name}</span>
                      {sub.voltageKv && (
                        <span className="gat-node-voltage">{sub.voltageKv}kV</span>
                      )}
                      {sub.demandHeadroomMw != null && (
                        <span className={`gat-node-headroom ${sub.demandHeadroomMw < 3 ? "low" : ""}`}>
                          {sub.demandHeadroomMw.toFixed(1)}MW
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}

        {!loading && grouped.length === 0 && (
          <div className="gat-empty">No substations match filters</div>
        )}
      </div>
    </div>
  );
}
