import React, { useState, useEffect, useMemo, useCallback } from "react";
import api from "../../services/api";

function KpiCard({ label, value, unit, color }) {
  return (
    <div className="gsp-kpi-card">
      <div className="gsp-kpi-label">{label}</div>
      <div className="gsp-kpi-value" style={{ color: color || "var(--cds-text-primary)" }}>
        {value ?? "--"}{unit && <span className="gsp-kpi-unit">{unit}</span>}
      </div>
    </div>
  );
}

function UtilisationBar({ value, max = 100 }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color = pct > 85 ? "#da1e28" : pct > 60 ? "#f1c21b" : "#24a148";
  return (
    <div className="gsp-util-bar">
      <div className="gsp-util-fill" style={{ width: `${pct}%`, background: color }} />
      <span className="gsp-util-text">{pct.toFixed(0)}%</span>
    </div>
  );
}

export default function GSPExplorerView() {
  const [gsps, setGsps] = useState([]);
  const [summary, setSummary] = useState(null);
  const [selectedGsp, setSelectedGsp] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchFilter, setSearchFilter] = useState("");
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");

  // Load GSP list and summary on mount
  useEffect(() => {
    Promise.all([
      api.demand.gsps(),
      api.demand.summary(),
    ]).then(([gspData, summaryData]) => {
      if (gspData) setGsps(gspData);
      if (summaryData) setSummary(summaryData);
      setLoading(false);
    });
  }, []);

  // Load forecast when GSP selected
  useEffect(() => {
    if (!selectedGsp) { setForecast(null); return; }
    api.demand.forecast(selectedGsp.gsp_id, 168, "analytical",
      selectedGsp.peak_mw, selectedGsp.min_mw, selectedGsp.capacity_mw
    ).then(data => {
      if (data) setForecast(data);
    });
  }, [selectedGsp]);

  // Filter + sort
  const filtered = useMemo(() => {
    let data = gsps;
    if (searchFilter) {
      const q = searchFilter.toLowerCase();
      data = data.filter(g =>
        (g.name || "").toLowerCase().includes(q) ||
        (g.gsp_id || "").toLowerCase().includes(q) ||
        (g.region || "").toLowerCase().includes(q)
      );
    }
    return [...data].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      const cmp = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [gsps, searchFilter, sortKey, sortDir]);

  const handleSort = useCallback((key) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("asc"); }
  }, [sortKey]);

  // KPI calculations
  const totalGsps = gsps.length;
  const totalDemandGw = summary?.total_demand_gw ?? gsps.reduce((s, g) => s + (g.peak_mw || 0), 0) / 1000;
  const avgUtil = summary?.avg_utilisation_pct ?? 0;
  const constrainedCount = summary?.constrained_count ?? gsps.filter(g => (g.utilisation_pct || 0) > 85).length;

  return (
    <div className="gsp-explorer-view">
      {/* KPI strip */}
      <div className="gsp-kpi-strip">
        <KpiCard label="Total GSPs" value={totalGsps} color="var(--cds-interactive)" />
        <KpiCard label="Total Demand" value={totalDemandGw.toFixed(1)} unit="GW" color="var(--cds-support-warning)" />
        <KpiCard label="Avg Utilisation" value={avgUtil.toFixed(0)} unit="%" color={avgUtil > 70 ? "#f1c21b" : "#24a148"} />
        <KpiCard label="Constrained" value={constrainedCount} color={constrainedCount > 0 ? "#da1e28" : "#24a148"} />
      </div>

      <div className="gsp-main">
        {/* Table */}
        <div className="gsp-table-section">
          <div className="gsp-table-header">
            <input
              type="text"
              placeholder="Search GSPs..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="gsp-search"
            />
            <span className="gsp-count">{filtered.length} GSPs</span>
          </div>

          <div className="gsp-table-wrap">
            <table className="gsp-table">
              <thead>
                <tr>
                  <th className="sortable" onClick={() => handleSort("name")}>
                    Name {sortKey === "name" && (sortDir === "asc" ? "^" : "v")}
                  </th>
                  <th className="sortable" onClick={() => handleSort("region")}>Region</th>
                  <th className="sortable" onClick={() => handleSort("peak_mw")}>Peak MW</th>
                  <th className="sortable" onClick={() => handleSort("generation_mw")}>Gen MW</th>
                  <th className="sortable" onClick={() => handleSort("capacity_mw")}>Capacity MW</th>
                  <th>Utilisation</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={6} className="gsp-loading">Loading GSP data...</td></tr>}
                {!loading && filtered.map(gsp => (
                  <tr
                    key={gsp.gsp_id}
                    className={selectedGsp?.gsp_id === gsp.gsp_id ? "selected" : ""}
                    onClick={() => setSelectedGsp(gsp)}
                  >
                    <td className="gsp-name-cell">{gsp.name || gsp.gsp_id}</td>
                    <td>{gsp.region || "--"}</td>
                    <td>{gsp.peak_mw?.toFixed(1) || "--"}</td>
                    <td>{gsp.generation_mw?.toFixed(1) || "--"}</td>
                    <td>{gsp.capacity_mw?.toFixed(1) || "--"}</td>
                    <td>
                      <UtilisationBar
                        value={gsp.utilisation_pct || (gsp.peak_mw && gsp.capacity_mw ? (gsp.peak_mw / gsp.capacity_mw) * 100 : 0)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detail panel for selected GSP */}
        {selectedGsp && (
          <div className="gsp-detail">
            <div className="gsp-detail-header">
              <h3>{selectedGsp.name || selectedGsp.gsp_id}</h3>
              <button className="gsp-detail-close" onClick={() => setSelectedGsp(null)}>&times;</button>
            </div>
            <div className="gsp-detail-body">
              <div className="gsp-detail-row">
                <span>Region</span><span>{selectedGsp.region || "--"}</span>
              </div>
              <div className="gsp-detail-row">
                <span>Peak Demand</span><span>{selectedGsp.peak_mw?.toFixed(1)} MW</span>
              </div>
              <div className="gsp-detail-row">
                <span>Generation</span><span>{selectedGsp.generation_mw?.toFixed(1) || "--"} MW</span>
              </div>
              <div className="gsp-detail-row">
                <span>Capacity</span><span>{selectedGsp.capacity_mw?.toFixed(1) || "--"} MW</span>
              </div>

              {/* Forecast chart (simple bar representation) */}
              {forecast?.forecast && (
                <div className="gsp-forecast-section">
                  <div className="gsp-section-label">7-Day Forecast</div>
                  <div className="gsp-forecast-bars">
                    {forecast.forecast.slice(0, 48).map((f, i) => {
                      const pct = forecast.forecast.length > 0
                        ? ((f.demand_mw || f.value || 0) / Math.max(...forecast.forecast.slice(0, 48).map(x => x.demand_mw || x.value || 1))) * 100
                        : 0;
                      return (
                        <div
                          key={i}
                          className="gsp-forecast-bar"
                          style={{ height: `${pct}%` }}
                          title={`${f.demand_mw?.toFixed(1) || f.value?.toFixed(1)} MW`}
                        />
                      );
                    })}
                  </div>
                  <div className="gsp-forecast-labels">
                    <span>Now</span>
                    <span>+24h</span>
                    <span>+48h</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
