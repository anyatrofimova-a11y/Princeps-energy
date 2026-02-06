import React, { useState, useEffect, useCallback } from "react";

const RISK_COLORS = { High: "#f44336", Medium: "#ff9800", Low: "#4caf50" };

export default function GridDataPanel({ parcelId, samCapacity }) {
  const [dashboard, setDashboard] = useState(null);
  const [connection, setConnection] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);

  // Fetch dashboard on mount
  useEffect(() => {
    fetch("/grid/dashboard")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setDashboard(d); })
      .catch(() => {});
  }, []);

  const runConnectionAnalysis = useCallback(async () => {
    if (!parcelId) return;
    setLoading(true);
    try {
      const [connRes, healthRes] = await Promise.allSettled([
        fetch(`/site/${encodeURIComponent(parcelId)}/grid/connection?capacity_kw=${samCapacity}`),
        fetch("/grid/health"),
      ]);
      if (connRes.status === "fulfilled" && connRes.value.ok)
        setConnection(await connRes.value.json());
      if (healthRes.status === "fulfilled" && healthRes.value.ok)
        setHealth(await healthRes.value.json());
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [parcelId, samCapacity]);

  return (
    <div>
      {/* Dashboard overview */}
      {dashboard?.grid_overview && (
        <>
          <div className="stat-grid">
            <div>Substations: <strong>{dashboard.grid_overview.total_substations}</strong></div>
            <div>Data sources: <strong>{dashboard.grid_overview.total_data_sources}</strong></div>
          </div>
          <div className="stat-grid">
            <div>Capacity: <strong>{dashboard.grid_overview.total_transformer_capacity_mva} MVA</strong></div>
            <div>Headroom: <strong>{dashboard.grid_overview.total_network_headroom_mw} MW</strong></div>
          </div>

          {/* Risk distribution */}
          <div className="section-label">Risk Distribution</div>
          <div className="grid-risk-row">
            {Object.entries(dashboard.risk_distribution).map(([risk, count]) => (
              <span key={risk} className="grid-risk-badge"
                style={{ background: RISK_COLORS[risk] || "#666" }}>
                {risk}: {count}
              </span>
            ))}
          </div>

          {/* Voltage distribution */}
          <div className="section-label">By Voltage</div>
          <div className="planning-cats">
            {Object.entries(dashboard.voltage_distribution).map(([v, count]) => (
              <div key={v} className="planning-cat-item">
                <span className="planning-cat-name">{v}</span>
                <span className="planning-cat-count" style={{ background: "#2196f3" }}>{count}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Connection analysis button */}
      <div style={{ margin: "8px 0" }}>
        <button className="grid-analyse-btn" onClick={runConnectionAnalysis}
          disabled={loading || !parcelId}>
          {loading ? "Analysing..." : "Analyse Grid Connection"}
        </button>
      </div>

      {/* Connection result */}
      {connection && (
        <>
          <div className="section-label">Nearest Substation</div>
          {connection.nearest_substation ? (
            <div className="grid-sub-card">
              <div className="grid-sub-name">{connection.nearest_substation.site_name}</div>
              <div className="stat-grid">
                <div>Distance: <strong>{connection.nearest_substation.distance_km} km</strong></div>
                <div>Voltage: <strong>{connection.nearest_substation.voltage_kv} kV</strong></div>
              </div>
              <div className="stat-grid">
                <div>Headroom: <strong>{connection.nearest_substation.headroom_mw} MW</strong></div>
                <div>Risk: <span style={{ color: RISK_COLORS[connection.nearest_substation.risk_rating] }}>
                  <strong>{connection.nearest_substation.risk_rating}</strong>
                </span></div>
              </div>
              <div className="stat-inline">
                {connection.nearest_substation.licence_area} — {connection.nearest_substation.town}, {connection.nearest_substation.county}
              </div>
            </div>
          ) : <span className="muted">No substation data</span>}

          {/* Cost estimate */}
          {connection.connection_estimate && (
            <>
              <div className="section-label">Connection Cost Estimate</div>
              <div className="stat-grid">
                <div>Total: <strong>GBP {connection.connection_estimate.total_cost_gbp?.toLocaleString()}</strong></div>
                <div>Timeline: <strong>{connection.connection_estimate.estimated_timeline_weeks} weeks</strong></div>
              </div>
              <div className="planning-cats">
                {Object.entries(connection.connection_estimate.breakdown || {}).map(([k, v]) => (
                  <div key={k} className="planning-cat-item">
                    <span className="planning-cat-name">{k.replace(/_/g, " ")}</span>
                    <span className="planning-cat-count" style={{ background: "#607d8b" }}>
                      GBP {v?.toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
              {connection.connection_estimate.notes?.map((note, i) => (
                <div key={i} className="stat-inline">{note}</div>
              ))}
            </>
          )}

          {/* Nearby substations */}
          {connection.nearby_substations?.length > 0 && (
            <>
              <div className="section-label">Nearby Substations ({connection.nearby_substations.length})</div>
              {connection.nearby_substations.map((sub) => (
                <div key={sub.id} className="stat-inline">
                  <strong>{sub.site_name}</strong> — {sub.distance_km} km, {sub.voltage_kv} kV,
                  headroom {sub.headroom_mw} MW
                </div>
              ))}
            </>
          )}
        </>
      )}

      {/* Health */}
      {health && (
        <>
          <div className="section-label">System Health</div>
          <div className="grid-health-row">
            <span className="grid-health-badge"
              style={{ background: health.status === "healthy" ? "#4caf50" : "#ff9800" }}>
              {health.status}
            </span>
            {Object.entries(health.checks).map(([k, v]) => (
              <span key={k} className="grid-health-item"
                style={{ color: v.status === "healthy" ? "#4caf50" : "#f44336" }}>
                {k}: {v.status}
              </span>
            ))}
          </div>
        </>
      )}

      {!dashboard && <span className="muted">Loading grid data...</span>}
    </div>
  );
}
