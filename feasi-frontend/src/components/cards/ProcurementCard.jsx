import React, { useState, useEffect, useCallback } from "react";

/**
 * ProcurementCard — Procurement pipeline analytics, bid viability, and cost benchmarks.
 */
export default function ProcurementCard() {
  const [pipeline, setPipeline] = useState(null);
  const [benchmarks, setBenchmarks] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState("pipeline"); // pipeline | benchmarks

  const loadPipeline = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/procurement/pipeline");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPipeline(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBenchmarks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/procurement/cost-benchmarks");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setBenchmarks(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (view === "pipeline" && !pipeline) loadPipeline();
    if (view === "benchmarks" && !benchmarks) loadBenchmarks();
  }, [view, pipeline, benchmarks, loadPipeline, loadBenchmarks]);

  return (
    <div className="card" style={{ borderLeft: "3px solid #ff5722" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: "#ff5722", flex: 1 }}>Procurement Intelligence</h3>
        <button
          className={`tab-btn-sm ${view === "pipeline" ? "active" : ""}`}
          style={view === "pipeline" ? { background: "#ff5722", color: "#fff" } : { color: "#ff5722" }}
          onClick={() => setView("pipeline")}
        >Pipeline</button>
        <button
          className={`tab-btn-sm ${view === "benchmarks" ? "active" : ""}`}
          style={view === "benchmarks" ? { background: "#ff5722", color: "#fff" } : { color: "#ff5722" }}
          onClick={() => setView("benchmarks")}
        >Benchmarks</button>
      </div>

      {loading && <p style={{ color: "#aaa" }}>Loading...</p>}
      {error && <p style={{ color: "#f44336" }}>{error}</p>}

      {view === "pipeline" && pipeline && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
            <div className="stat-box">
              <div className="stat-value">{pipeline.total_active}</div>
              <div className="stat-label">Active Tenders</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ color: "#ff9800" }}>{pipeline.urgent_count}</div>
              <div className="stat-label">Urgent (&lt;14d)</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ color: "#4caf50" }}>
                {pipeline.total_value_gbp ? `£${(pipeline.total_value_gbp / 1e6).toFixed(1)}M` : "N/A"}
              </div>
              <div className="stat-label">Total Value</div>
            </div>
          </div>

          {pipeline.by_technology && Object.keys(pipeline.by_technology).length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>By Technology</div>
              {Object.entries(pipeline.by_technology).map(([tech, count]) => (
                <div key={tech} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0", fontSize: 12 }}>
                  <span style={{ color: "#ccc" }}>{tech.replace(/_/g, " ")}</span>
                  <span style={{ color: "#ff5722" }}>{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {view === "benchmarks" && benchmarks && (
        <div>
          <div style={{ fontSize: 11, color: "#aaa", marginBottom: 6 }}>UK Energy Cost Benchmarks (GBP/kW)</div>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #333" }}>
                <th style={{ textAlign: "left", color: "#aaa", padding: "4px 0" }}>Technology</th>
                <th style={{ textAlign: "right", color: "#aaa" }}>Min</th>
                <th style={{ textAlign: "right", color: "#aaa" }}>Median</th>
                <th style={{ textAlign: "right", color: "#aaa" }}>Max</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(benchmarks).map(([tech, vals]) => (
                <tr key={tech} style={{ borderBottom: "1px solid #222" }}>
                  <td style={{ color: "#ccc", padding: "3px 0" }}>{tech.replace(/_/g, " ")}</td>
                  <td style={{ textAlign: "right", color: "#4caf50" }}>£{vals.min}</td>
                  <td style={{ textAlign: "right", color: "#ff9800" }}>£{vals.median}</td>
                  <td style={{ textAlign: "right", color: "#f44336" }}>£{vals.max}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
