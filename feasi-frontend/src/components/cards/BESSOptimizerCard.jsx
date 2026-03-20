import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../../SiteContext";

/**
 * BESSOptimizerCard — 4-view tabbed card for BESS site scoring,
 * optimal sizing, revenue stacking, and co-location analysis.
 */
export default function BESSOptimizerCard() {
  const { pickedLocation, samCapacity } = useSite();
  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon;
  const [view, setView] = useState("score"); // score | sizing | revenue | colocation
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Sizing inputs
  const [capacityMw, setCapacityMw] = useState(50);
  const [strategy, setStrategy] = useState("hybrid");
  const [gridConstraintMw, setGridConstraintMw] = useState(100);

  // Reset result when view changes
  useEffect(() => setResult(null), [view]);

  const scoreSite = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/bess/score?lat=${lat}&lon=${lon}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  const calculateSizing = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/bess/sizing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capacity_mw: capacityMw,
          revenue_strategy: strategy,
          grid_constraint_mw: gridConstraintMw,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [capacityMw, strategy, gridConstraintMw]);

  const modelRevenue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const energyMwh = capacityMw * 2; // default 2hr duration
      const res = await fetch("/bess/revenue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          power_mw: capacityMw,
          energy_mwh: energyMwh,
          strategy,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [capacityMw, strategy]);

  const assessColocation = useCallback(async () => {
    const solarKw = samCapacity || 5000;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/bess/colocation?solar_kw=${solarKw}&lat=${lat || 52.5}&lon=${lon || -1.5}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, samCapacity]);

  const recColor = (rec) => {
    if (rec === "HIGH_PRIORITY") return "#4caf50";
    if (rec === "PROMISING") return "#ff9800";
    if (rec === "MARGINAL") return "#ff5722";
    return "#f44336";
  };

  const themeColor = "#4caf50";

  const viewLabels = { score: "Score", sizing: "Sizing", revenue: "Revenue", colocation: "Co-loc" };

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: themeColor, flex: 1 }}>BESS Optimiser</h3>
        {Object.entries(viewLabels).map(([v, label]) => (
          <button
            key={v}
            className={`tab-btn-sm ${view === v ? "active" : ""}`}
            style={view === v ? { background: themeColor, color: "#fff" } : { color: themeColor }}
            onClick={() => setView(v)}
          >{label}</button>
        ))}
      </div>

      {/* Controls for sizing/revenue views */}
      {(view === "sizing" || view === "revenue") && (
        <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 10, color: "#aaa" }}>MW:</label>
          <input
            type="number" min={1} max={500} value={capacityMw}
            onChange={e => setCapacityMw(Number(e.target.value))}
            style={{
              width: 60, padding: "3px 6px", fontSize: 11,
              background: "#F7F8FA", color: "#4B5563", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 4,
            }}
          />
          <label style={{ fontSize: 10, color: "#aaa" }}>Strategy:</label>
          <select
            value={strategy} onChange={e => setStrategy(e.target.value)}
            className="settings-select" style={{ padding: "3px 6px", fontSize: 11, flex: 1 }}
          >
            <option value="hybrid">Hybrid</option>
            <option value="frequency_response">Frequency Response</option>
            <option value="arbitrage">Arbitrage</option>
            <option value="capacity_market">Capacity Market</option>
          </select>
          {view === "sizing" && (
            <>
              <label style={{ fontSize: 10, color: "#aaa" }}>Grid cap:</label>
              <input
                type="number" min={1} max={500} value={gridConstraintMw}
                onChange={e => setGridConstraintMw(Number(e.target.value))}
                style={{
                  width: 60, padding: "3px 6px", fontSize: 11,
                  background: "#F7F8FA", color: "#4B5563", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 4,
                }}
              />
            </>
          )}
        </div>
      )}

      <button
        onClick={
          view === "score" ? scoreSite :
          view === "sizing" ? calculateSizing :
          view === "revenue" ? modelRevenue :
          assessColocation
        }
        disabled={loading || (view === "score" && (!lat || !lon))}
        style={{
          background: themeColor, color: "#fff", border: "none", borderRadius: 4,
          padding: "6px 14px", fontSize: 12, cursor: "pointer", width: "100%", marginBottom: 8,
        }}
      >
        {loading ? "Analysing..." :
          view === "score" ? "Score Site" :
          view === "sizing" ? "Calculate Sizing" :
          view === "revenue" ? "Model Revenue" :
          "Assess Co-location"}
      </button>

      {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

      {/* Score view */}
      {view === "score" && result && result.total_score !== undefined && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: recColor(result.recommendation) }}>
              {result.total_score}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: recColor(result.recommendation) }}>
                {result.recommendation}
              </div>
              <div style={{ fontSize: 11, color: "#aaa" }}>
                Max feasible: {result.max_feasible_mw} MW @ {result.suggested_voltage_kv}kV
              </div>
            </div>
          </div>
          {result.scores && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {Object.entries(result.scores).map(([k, v]) => (
                <div key={k} className="stat-box">
                  <div className="stat-value" style={{ fontSize: 14 }}>{v}</div>
                  <div className="stat-label">{k.replace(/_/g, " ")}</div>
                </div>
              ))}
            </div>
          )}
          {result.constraints?.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#f44336" }}>
              Constraints: {result.constraints.join(", ")}
            </div>
          )}
        </div>
      )}

      {/* Sizing view */}
      {view === "sizing" && result && result.optimal && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, color: themeColor }}>
                {result.optimal.power_mw} MW / {result.optimal.energy_mwh} MWh
              </div>
              <div style={{ fontSize: 11, color: "#aaa" }}>
                {result.optimal.duration_hr}hr duration — {result.optimal.revenue_strategy}
              </div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 8 }}>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14, color: result.optimal.npv_20yr_gbp > 0 ? "#4caf50" : "#f44336" }}>
                {(result.optimal.npv_20yr_gbp / 1e6).toFixed(1)}M
              </div>
              <div className="stat-label">NPV (20yr)</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14 }}>{result.optimal.irr_pct}%</div>
              <div className="stat-label">IRR</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14 }}>
                {(result.optimal.capex_gbp / 1e6).toFixed(1)}M
              </div>
              <div className="stat-label">CAPEX</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14 }}>{result.optimal.payback_years}yr</div>
              <div className="stat-label">Payback</div>
            </div>
          </div>
          {result.scenarios && (
            <>
              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>All scenarios:</div>
              {result.scenarios.map((s, i) => (
                <div key={i} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "3px 0", fontSize: 12, borderBottom: "1px solid #222",
                }}>
                  <span style={{ color: "#4B5563" }}>{s.duration_hr}hr — {s.energy_mwh} MWh</span>
                  <span style={{ color: s.npv_20yr_gbp > 0 ? "#4caf50" : "#f44336", fontWeight: 600 }}>
                    NPV {(s.npv_20yr_gbp / 1e6).toFixed(1)}M | IRR {s.irr_pct}%
                  </span>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Revenue view */}
      {view === "revenue" && result && result.revenue_breakdown && (
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: themeColor, marginBottom: 8 }}>
            {(result.total_annual_gbp / 1000).toFixed(0)}k/yr
          </div>
          {Object.entries(result.revenue_breakdown).map(([k, v]) => {
            const pct = result.total_annual_gbp > 0 ? (v / result.total_annual_gbp * 100) : 0;
            return (
              <div key={k} style={{ marginBottom: 6 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span style={{ color: "#4B5563" }}>{k.replace(/_/g, " ")}</span>
                  <span style={{ color: "#fff", fontWeight: 600 }}>
                    {(v / 1000).toFixed(0)}k ({pct.toFixed(0)}%)
                  </span>
                </div>
                <div style={{ height: 4, background: "#222", borderRadius: 2, marginTop: 2 }}>
                  <div style={{
                    height: "100%", width: `${pct}%`,
                    background: themeColor, borderRadius: 2,
                  }} />
                </div>
              </div>
            );
          })}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginTop: 8 }}>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 13 }}>{result.cycles_per_year}</div>
              <div className="stat-label">Cycles/yr</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 13 }}>{(result.capacity_factor * 100).toFixed(1)}%</div>
              <div className="stat-label">Cap factor</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 13 }}>{(result.degradation_cost_gbp_yr / 1000).toFixed(0)}k</div>
              <div className="stat-label">Deg. cost/yr</div>
            </div>
          </div>
        </div>
      )}

      {/* Co-location view */}
      {view === "colocation" && result && result.benefits && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, color: themeColor }}>
                +{(result.value_add_gbp_yr / 1000).toFixed(0)}k/yr
              </div>
              <div style={{ fontSize: 11, color: "#aaa" }}>
                Co-location value add ({result.solar_capacity_kw} kW solar + {result.bess_mwh} MWh BESS)
              </div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 8 }}>
            {result.benefits.clipping_capture && (
              <div className="stat-box">
                <div className="stat-value" style={{ fontSize: 13 }}>
                  {(result.benefits.clipping_capture.value_gbp_yr / 1000).toFixed(0)}k
                </div>
                <div className="stat-label">Clipping capture</div>
              </div>
            )}
            {result.benefits.shared_connection && (
              <div className="stat-box">
                <div className="stat-value" style={{ fontSize: 13 }}>
                  {(result.benefits.shared_connection.annualised_gbp_yr / 1000).toFixed(0)}k
                </div>
                <div className="stat-label">Shared connection</div>
              </div>
            )}
            {result.benefits.enhanced_dispatch && (
              <div className="stat-box">
                <div className="stat-value" style={{ fontSize: 13 }}>
                  {(result.benefits.enhanced_dispatch.value_gbp_yr / 1000).toFixed(0)}k
                </div>
                <div className="stat-label">Peak dispatch</div>
              </div>
            )}
            {result.benefits.reduced_curtailment && (
              <div className="stat-box">
                <div className="stat-value" style={{ fontSize: 13 }}>
                  {(result.benefits.reduced_curtailment.value_gbp_yr / 1000).toFixed(0)}k
                </div>
                <div className="stat-label">Less curtailment</div>
              </div>
            )}
          </div>
          <div style={{ fontSize: 11, color: "#aaa" }}>
            Optimal ratio: {result.optimal_solar_bess_ratio} | Recommended: {result.recommended_bess_mwh} MWh
          </div>
        </div>
      )}
    </div>
  );
}
