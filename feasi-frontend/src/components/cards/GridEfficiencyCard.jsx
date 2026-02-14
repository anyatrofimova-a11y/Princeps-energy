import React, { useState, useCallback } from "react";

/**
 * GridEfficiencyCard — Line loss estimation, substation health assessment.
 */
export default function GridEfficiencyCard() {
  const [view, setView] = useState("losses"); // losses | health
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Line loss form state
  const [distKm, setDistKm] = useState(10);
  const [voltageKv, setVoltageKv] = useState(132);
  const [loadMw, setLoadMw] = useState(10);

  const estimateLosses = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/grid-efficiency/line-losses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ distance_km: distKm, voltage_kv: voltageKv, load_mw: loadMw }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [distKm, voltageKv, loadMw]);

  const lossColor = (pct) => pct > 3 ? "#f44336" : pct > 1.5 ? "#ff9800" : "#4caf50";

  return (
    <div className="card" style={{ borderLeft: "3px solid #795548" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: "#795548", flex: 1 }}>Grid Efficiency</h3>
        <button
          className={`tab-btn-sm ${view === "losses" ? "active" : ""}`}
          style={view === "losses" ? { background: "#795548", color: "#fff" } : { color: "#795548" }}
          onClick={() => setView("losses")}
        >Line Losses</button>
        <button
          className={`tab-btn-sm ${view === "health" ? "active" : ""}`}
          style={view === "health" ? { background: "#795548", color: "#fff" } : { color: "#795548" }}
          onClick={() => setView("health")}
        >Sub Health</button>
      </div>

      {view === "losses" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 8 }}>
            <div>
              <label style={{ fontSize: 10, color: "#aaa" }}>Distance (km)</label>
              <input
                type="number" value={distKm} onChange={e => setDistKm(+e.target.value)}
                className="settings-input" style={{ padding: "4px 6px", fontSize: 12 }}
              />
            </div>
            <div>
              <label style={{ fontSize: 10, color: "#aaa" }}>Voltage (kV)</label>
              <select
                value={voltageKv} onChange={e => setVoltageKv(+e.target.value)}
                className="settings-select" style={{ padding: "4px 6px", fontSize: 12 }}
              >
                <option value={11}>11kV</option>
                <option value={33}>33kV</option>
                <option value={132}>132kV</option>
                <option value={275}>275kV</option>
                <option value={400}>400kV</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 10, color: "#aaa" }}>Load (MW)</label>
              <input
                type="number" value={loadMw} onChange={e => setLoadMw(+e.target.value)}
                className="settings-input" style={{ padding: "4px 6px", fontSize: 12 }}
              />
            </div>
          </div>

          <button
            onClick={estimateLosses}
            disabled={loading}
            style={{
              background: "#795548", color: "#fff", border: "none", borderRadius: 4,
              padding: "6px 14px", fontSize: 12, cursor: "pointer", width: "100%", marginBottom: 8,
            }}
          >{loading ? "Calculating..." : "Estimate Losses"}</button>

          {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

          {result && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div className="stat-box">
                <div className="stat-value" style={{ color: lossColor(result.loss_pct) }}>
                  {result.loss_pct}%
                </div>
                <div className="stat-label">Line Loss</div>
              </div>
              <div className="stat-box">
                <div className="stat-value">{result.loss_mw} MW</div>
                <div className="stat-label">Power Lost</div>
              </div>
              <div className="stat-box">
                <div className="stat-value">{result.loading_ratio}</div>
                <div className="stat-label">Loading Ratio</div>
              </div>
              <div className="stat-box">
                <div className="stat-value" style={{ color: "#ff9800" }}>
                  £{(result.annual_loss_cost_gbp / 1000).toFixed(0)}k
                </div>
                <div className="stat-label">Annual Loss Cost</div>
              </div>
            </div>
          )}
        </div>
      )}

      {view === "health" && (
        <div style={{ fontSize: 12, color: "#aaa" }}>
          <p>Use the Chat or Agent panel to assess substation health with real network data.</p>
          <p style={{ fontSize: 11 }}>
            The health assessment combines asset age, utilisation level, and satellite-derived condition scoring.
          </p>
        </div>
      )}
    </div>
  );
}
