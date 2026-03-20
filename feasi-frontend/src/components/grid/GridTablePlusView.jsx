import React, { useState, useMemo, useCallback } from "react";
import { useGridModel } from "../../contexts/GridModelContext";
import StatusBadge from "./StatusBadge";

const ASSET_TABS = [
  { id: "substations", label: "Substations" },
  { id: "constrained", label: "Constrained" },
  { id: "opportunity", label: "Opportunities" },
];

const COLUMNS = {
  substations: [
    { key: "name", label: "Name", sortable: true },
    { key: "voltageKv", label: "Voltage", sortable: true, unit: "kV" },
    { key: "licenceArea", label: "Region", sortable: true },
    { key: "demandHeadroomMw", label: "Demand Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "genHeadroomMw", label: "Gen Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "demandRag", label: "Demand", sortable: true, isRag: true },
    { key: "genRag", label: "Gen", sortable: true, isRag: true },
    { key: "constraint", label: "Constraint", sortable: true },
  ],
  constrained: [
    { key: "name", label: "Name", sortable: true },
    { key: "voltageKv", label: "Voltage", sortable: true, unit: "kV" },
    { key: "licenceArea", label: "Region", sortable: true },
    { key: "constraint", label: "Constraint Type", sortable: true },
    { key: "demandHeadroomMw", label: "Demand Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "genHeadroomMw", label: "Gen Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "gsp", label: "GSP", sortable: true },
  ],
  opportunity: [
    { key: "name", label: "Name", sortable: true },
    { key: "voltageKv", label: "Voltage", sortable: true, unit: "kV" },
    { key: "licenceArea", label: "Region", sortable: true },
    { key: "genHeadroomMw", label: "Gen Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "demandHeadroomMw", label: "Demand Headroom", sortable: true, unit: "MW", decimal: 1 },
    { key: "genRag", label: "Status", sortable: true, isRag: true },
    { key: "gsp", label: "GSP", sortable: true },
  ],
};

function formatValue(value, col) {
  if (value == null || value === "") return "--";
  if (col.decimal != null) return Number(value).toFixed(col.decimal);
  return String(value);
}

export default function GridTablePlusView() {
  const { filteredSubstations, selectedSubstation, selectSubstation } = useGridModel();
  const [activeTab, setActiveTab] = useState("substations");
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [searchFilter, setSearchFilter] = useState("");

  // Filter data by tab type
  const tabData = useMemo(() => {
    let data = filteredSubstations;
    if (activeTab === "constrained") {
      data = data.filter(s => s.demandRag === "Red" || s.genRag === "Red" || s.constraint);
    } else if (activeTab === "opportunity") {
      data = data.filter(s => (s.genHeadroomMw || 0) > 5 && s.genRag !== "Red");
    }
    // Local search
    if (searchFilter) {
      const q = searchFilter.toLowerCase();
      data = data.filter(s =>
        (s.name || "").toLowerCase().includes(q) ||
        (s.licenceArea || "").toLowerCase().includes(q) ||
        (s.gsp || "").toLowerCase().includes(q)
      );
    }
    return data;
  }, [filteredSubstations, activeTab, searchFilter]);

  // Sort
  const sorted = useMemo(() => {
    return [...tabData].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      const cmp = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [tabData, sortKey, sortDir]);

  const handleSort = useCallback((key) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }, [sortKey]);

  const handleExport = useCallback(() => {
    const cols = COLUMNS[activeTab];
    const header = cols.map(c => c.label).join(",");
    const rows = sorted.map(s => cols.map(c => formatValue(s[c.key], c)).join(","));
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `grid-${activeTab}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [sorted, activeTab]);

  const columns = COLUMNS[activeTab];

  return (
    <div className="grid-table-plus">
      {/* Tab bar */}
      <div className="gtp-header">
        <div className="gtp-tabs">
          {ASSET_TABS.map(tab => (
            <button
              key={tab.id}
              className={`gtp-tab ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
              <span className="gtp-tab-count">
                {tab.id === "substations" ? filteredSubstations.length
                  : tab.id === "constrained" ? filteredSubstations.filter(s => s.demandRag === "Red" || s.genRag === "Red" || s.constraint).length
                  : filteredSubstations.filter(s => (s.genHeadroomMw || 0) > 5 && s.genRag !== "Red").length}
              </span>
            </button>
          ))}
        </div>
        <div className="gtp-controls">
          <input
            type="text"
            placeholder="Filter..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            className="gtp-search"
          />
          <button className="gtp-export" onClick={handleExport} title="Export CSV">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
            </svg>
            CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="gtp-table-wrap">
        <table className="gtp-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  className={col.sortable ? "sortable" : ""}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  {col.label}
                  {col.unit && <span className="gtp-unit">{col.unit}</span>}
                  {sortKey === col.key && (
                    <span className="gtp-sort-arrow">{sortDir === "asc" ? " ^" : " v"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(sub => (
              <tr
                key={sub.id}
                className={selectedSubstation?.id === sub.id ? "selected" : ""}
                onClick={() => selectSubstation(sub)}
              >
                {columns.map(col => (
                  <td key={col.key}>
                    {col.isRag ? (
                      <StatusBadge status={sub[col.key]} size="xs" />
                    ) : (
                      formatValue(sub[col.key], col)
                    )}
                  </td>
                ))}
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr><td colSpan={columns.length} className="gtp-empty">No data matches filters</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="gtp-footer">
        <span>{sorted.length} of {filteredSubstations.length} substations</span>
      </div>
    </div>
  );
}
