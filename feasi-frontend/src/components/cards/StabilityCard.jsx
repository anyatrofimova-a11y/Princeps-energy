import React, { useState, useEffect, useCallback, useRef } from "react";
import MetricCard from "../ui/MetricCard";
import StatGrid, { Stat } from "../ui/StatGrid";
import api from "../../services/api";

const SLIDER_PARAMS = [
  { key: "tau_base", label: "Reaction Time", min: 0.5, max: 10, step: 0.5, unit: "s", default: 4.0 },
  { key: "gamma_base", label: "Price Elasticity", min: 0.05, max: 1.0, step: 0.05, unit: "", default: 0.5 },
  { key: "demand_scale", label: "Demand Scale", min: 0.5, max: 2.0, step: 0.1, unit: "x", default: 1.0 },
  { key: "renewable_pen", label: "Renewable %", min: 0.0, max: 1.0, step: 0.05, unit: "", default: 0.3 },
  { key: "ev_load", label: "EV Load", min: 0, max: 50, step: 5, unit: "MW", default: 0 },
  { key: "storage_factor", label: "Battery Storage", min: 0, max: 1.0, step: 0.1, unit: "", default: 0 },
];

export default function StabilityCard({ onStabilityData }) {
  const [params, setParams] = useState(
    Object.fromEntries(SLIDER_PARAMS.map(s => [s.key, s.default]))
  );
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);

  const fetchStability = useCallback(async (p) => {
    setLoading(true);
    try {
      const result = await api.grid.stability(p);
      if (result) {
        setData(result);
        if (onStabilityData) onStabilityData(result);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [onStabilityData]);

  // Debounced fetch on param change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchStability(params), 600);
    return () => clearTimeout(debounceRef.current);
  }, [params, fetchStability]);

  const handleSlider = (key, val) => {
    setParams(p => ({ ...p, [key]: parseFloat(val) }));
  };

  const s = data?.summary;
  const riskColor = { low: "#4caf50", moderate: "#ff9800", high: "#f44336", critical: "#b71c1c" };

  return (
    <MetricCard
      title="Grid Stability (DSGC)"
      accentColor={s ? riskColor[s.cascade_risk] || "#666" : "#666"}
      headerValue={s ? `${s.percent_stable}% stable` : "Loading..."}
      aiInsight={s ? `Cascade risk: ${s.cascade_risk} — ${s.unstable_count} unstable nodes` : null}
      defaultOpen
    >
      {/* Scenario sliders */}
      <div style={{ marginBottom: 10 }}>
        {SLIDER_PARAMS.map(sp => (
          <div key={sp.key} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: "#aaa", width: 100, flexShrink: 0 }}>{sp.label}</span>
            <input
              type="range" min={sp.min} max={sp.max} step={sp.step}
              value={params[sp.key]}
              onChange={e => handleSlider(sp.key, e.target.value)}
              style={{ flex: 1, height: 4 }}
            />
            <span style={{ fontSize: 11, color: "#fff", width: 50, textAlign: "right" }}>
              {params[sp.key]}{sp.unit}
            </span>
          </div>
        ))}
      </div>

      {loading && <div className="dim" style={{ fontSize: 11 }}>Simulating...</div>}

      {s && (
        <>
          <StatGrid columns={3}>
            <Stat label="Stable" value={s.stable_count} color="#4caf50" />
            <Stat label="Unstable" value={s.unstable_count} color="#f44336" />
            <Stat label="Avg Score" value={s.avg_stability_score.toFixed(2)} />
          </StatGrid>

          {/* Cascade risk bar */}
          <div style={{
            marginTop: 8, padding: "6px 10px", borderRadius: 8,
            background: `${riskColor[s.cascade_risk]}22`,
            borderLeft: `3px solid ${riskColor[s.cascade_risk]}`,
            fontSize: 12, fontWeight: 600,
          }}>
            Cascade Risk: <span style={{ color: riskColor[s.cascade_risk], textTransform: "uppercase" }}>
              {s.cascade_risk}
            </span>
          </div>

          {/* Top 10 vulnerable nodes */}
          {data.vulnerable_top10 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>Most Vulnerable Nodes</div>
              {data.vulnerable_top10.slice(0, 6).map((n, i) => (
                <div key={i} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "3px 6px", fontSize: 11, borderRadius: 4,
                  background: n.is_stable ? "rgba(76,175,80,0.1)" : "rgba(244,67,54,0.15)",
                }}>
                  <span style={{ color: n.is_stable ? "#aaa" : "#f44336" }}>
                    {n.name} ({n.voltage_kv}kV)
                  </span>
                  <span style={{
                    fontWeight: 600,
                    color: n.stability_score > 0.6 ? "#4caf50" : n.stability_score > 0.4 ? "#ff9800" : "#f44336"
                  }}>
                    {(n.stability_score * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </MetricCard>
  );
}
