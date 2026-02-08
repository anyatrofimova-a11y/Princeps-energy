import React, { useState, useEffect, useCallback, useRef } from "react";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";
import { useSite } from "../../SiteContext";

// ── Colour helpers ──
function heatColor(v, min, max) {
  const t = Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
  // Cool (blue) → Warm (yellow) → Hot (red)
  const r = t < 0.5 ? Math.round(t * 2 * 255) : 255;
  const g = t < 0.5 ? Math.round(100 + t * 310) : Math.round(255 - (t - 0.5) * 2 * 200);
  const b = t < 0.5 ? Math.round(255 - t * 2 * 200) : Math.round(55 - t * 50);
  return `rgb(${r},${g},${b})`;
}

function stabilityColor(score) {
  if (score > 0.7) return "#4caf50";
  if (score > 0.4) return "#ff9800";
  return "#f44336";
}

// ── Thermograph / Consumption Heatmap ──
function Thermograph({ data }) {
  if (!data) return null;
  const { heatmap, hours, days, monthly_factors, decomposition } = data;
  const flat = heatmap.flat();
  const min = Math.min(...flat), max = Math.max(...flat);

  return (
    <div>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 6 }}>Hour × Day-of-Week Consumption (LSTM R²=0.979)</div>
      {/* Heatmap grid */}
      <div style={{ display: "flex", gap: 1 }}>
        {/* Day labels */}
        <div style={{ display: "flex", flexDirection: "column", gap: 1, marginRight: 4, justifyContent: "center" }}>
          {days.map(d => (
            <div key={d} style={{ height: 14, fontSize: 9, color: "#888", display: "flex", alignItems: "center" }}>{d}</div>
          ))}
        </div>
        {/* Grid cells */}
        <div style={{ flex: 1 }}>
          {heatmap.map((row, di) => (
            <div key={di} style={{ display: "flex", gap: 1, marginBottom: 1 }}>
              {row.map((v, hi) => (
                <div
                  key={hi}
                  title={`${days[di]} ${hours[hi]}:00 — ${(v * 100).toFixed(0)}%`}
                  style={{
                    flex: 1, height: 14, borderRadius: 2,
                    background: heatColor(v, min, max),
                    opacity: 0.85,
                  }}
                />
              ))}
            </div>
          ))}
          {/* Hour labels */}
          <div style={{ display: "flex", marginTop: 2 }}>
            {hours.filter(h => h % 3 === 0).map(h => (
              <div key={h} style={{ flex: 3, fontSize: 8, color: "#666", textAlign: "center" }}>{h}</div>
            ))}
          </div>
        </div>
      </div>

      {/* Colour scale legend */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
        <span style={{ fontSize: 9, color: "#666" }}>Low</span>
        <div style={{
          flex: 1, height: 8, borderRadius: 4,
          background: "linear-gradient(90deg, #4466ff, #44ff88, #ffcc00, #ff4444)",
        }} />
        <span style={{ fontSize: 9, color: "#666" }}>High</span>
      </div>

      {/* Monthly seasonal factors */}
      {monthly_factors && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: "#888", marginBottom: 3 }}>Seasonal Decomposition</div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 36 }}>
            {monthly_factors.map((m, i) => {
              const h = Math.max(4, ((m.factor - 0.8) / 0.4) * 36);
              return (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <div
                    title={`${m.name}: ${m.factor}x`}
                    style={{
                      width: "100%", height: h, borderRadius: 2,
                      background: m.factor > 1.0 ? "#ff9800" : "#2196f3",
                      opacity: 0.7,
                    }}
                  />
                  <span style={{ fontSize: 7, color: "#666", marginTop: 1 }}>{m.name.slice(0, 1)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Solar Forecast Chart ──
function SolarForecastChart({ data }) {
  if (!data) return null;
  const { intervals, daily_yield_kwh, day_length_h, feature_importance } = data;
  const maxPower = Math.max(...intervals.map(i => i.ac_power_kw)) || 1;
  const maxIrr = Math.max(...intervals.map(i => i.irradiation_wm2)) || 1;

  return (
    <div>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
        96-interval forecast — {daily_yield_kwh} kWh/day, {day_length_h}h daylight
      </div>

      {/* Dual-axis chart: Power bars + Irradiation line overlay */}
      <div style={{ position: "relative", height: 80, display: "flex", alignItems: "flex-end", gap: 0 }}>
        {intervals.map((iv, i) => (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
            {/* Irradiation dot */}
            {iv.irradiation_wm2 > 0 && (
              <div style={{
                position: "absolute",
                bottom: `${(iv.irradiation_wm2 / maxIrr) * 100}%`,
                width: 3, height: 3, borderRadius: "50%",
                background: "#ffeb3b", opacity: 0.6,
              }} />
            )}
            {/* Power bar */}
            <div
              title={`${iv.hour}h — AC: ${iv.ac_power_kw}kW, Irr: ${iv.irradiation_wm2}W/m², Mod: ${iv.module_temp_c}°C`}
              style={{
                width: "100%",
                height: `${(iv.ac_power_kw / maxPower) * 100}%`,
                background: iv.ac_power_kw > 0
                  ? `hsl(${30 + (iv.module_temp_c - 5) * 2}, 80%, 50%)`
                  : "transparent",
                borderRadius: "1px 1px 0 0",
                minHeight: iv.ac_power_kw > 0 ? 1 : 0,
              }}
            />
          </div>
        ))}
      </div>
      {/* Hour labels */}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
        {[0, 6, 12, 18, 24].map(h => (
          <span key={h} style={{ fontSize: 8, color: "#666" }}>{h}h</span>
        ))}
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 12, marginTop: 4, fontSize: 9, color: "#888" }}>
        <span><span style={{ color: "#ff9800" }}>|</span> AC Power</span>
        <span><span style={{ color: "#ffeb3b" }}>·</span> Irradiation</span>
        <span>Colour = module temp</span>
      </div>

      {/* Feature importance */}
      {feature_importance && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10, color: "#888", marginBottom: 3 }}>XGBoost Feature Importance</div>
          {feature_importance.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
              <span style={{ fontSize: 9, color: "#aaa", width: 80, flexShrink: 0, textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>{f.feature}</span>
              <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.05)", borderRadius: 3 }}>
                <div style={{
                  height: "100%", borderRadius: 3,
                  width: `${f.importance * 100 / 0.34}%`,
                  background: `hsl(${200 - i * 30}, 70%, 55%)`,
                }} />
              </div>
              <span style={{ fontSize: 9, color: "#ccc", width: 30, textAlign: "right" }}>{(f.importance * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Prosumer Balance Chart ──
function ProsumerChart({ data }) {
  if (!data) return null;
  const { hours, summary } = data;
  const maxVal = Math.max(...hours.map(h => Math.max(h.production_kwh, h.consumption_kwh))) || 1;

  return (
    <div>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
        Self-sufficiency: {summary.self_sufficiency_pct}% — Export: {summary.grid_export_kwh} kWh
      </div>

      {/* Dual bar chart */}
      <div style={{ display: "flex", alignItems: "center", height: 70, gap: 1 }}>
        {hours.map((h, i) => {
          const prodH = (h.production_kwh / maxVal) * 35;
          const consH = (h.consumption_kwh / maxVal) * 35;
          return (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", height: 70, justifyContent: "center" }}
              title={`${h.hour}:00 — Prod: ${h.production_kwh}kWh, Cons: ${h.consumption_kwh}kWh, Net: ${h.net_kwh}kWh`}
            >
              {/* Production (up) */}
              <div style={{
                width: "100%", height: prodH, borderRadius: "2px 2px 0 0",
                background: "#4caf50", opacity: 0.8,
              }} />
              {/* Consumption (down) */}
              <div style={{
                width: "100%", height: consH, borderRadius: "0 0 2px 2px",
                background: "#f44336", opacity: 0.6,
              }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 1 }}>
        {[0, 6, 12, 18, 23].map(h => <span key={h} style={{ fontSize: 8, color: "#666" }}>{h}h</span>)}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 4, fontSize: 9, color: "#888" }}>
        <span><span style={{ color: "#4caf50" }}>|</span> Production</span>
        <span><span style={{ color: "#f44336" }}>|</span> Consumption</span>
      </div>

      {/* Summary stats */}
      <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
        {[
          { label: "Produced", value: `${summary.daily_production_kwh} kWh`, color: "#4caf50" },
          { label: "Consumed", value: `${summary.daily_consumption_kwh} kWh`, color: "#f44336" },
          { label: "Self-use", value: `${summary.self_consumption_kwh} kWh`, color: "#2196f3" },
        ].map(s => (
          <div key={s.label} style={{ fontSize: 10 }}>
            <span style={{ color: "#888" }}>{s.label}: </span>
            <strong style={{ color: s.color }}>{s.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Turbine Health Thermograph ──
function TurbineThermograph({ data }) {
  if (!data) return null;
  const { components, fault_types, temperature_matrix, base_temperatures, current_status, fault_timeline } = data;
  const faultKeys = Object.keys(temperature_matrix);
  const allTemps = Object.values(temperature_matrix).flatMap(t => Object.values(t));
  const minT = Math.min(...allTemps), maxT = Math.max(...allTemps);

  return (
    <div>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
        Status: <span style={{ color: fault_types[current_status.fault]?.color || "#fff", fontWeight: 600 }}>
          {current_status.label}
        </span> ({(current_status.confidence * 100).toFixed(1)}% confidence)
      </div>

      {/* Component × Fault condition temperature matrix */}
      <div style={{ overflow: "auto" }}>
        {/* Header row */}
        <div style={{ display: "flex", gap: 1, marginBottom: 1 }}>
          <div style={{ width: 70, flexShrink: 0 }} />
          {faultKeys.map(fk => (
            <div key={fk} style={{
              flex: 1, fontSize: 8, color: fault_types[fk]?.color || "#888",
              textAlign: "center", fontWeight: 600,
            }}>
              {fk}
            </div>
          ))}
        </div>

        {/* Component rows */}
        {components.map(comp => (
          <div key={comp} style={{ display: "flex", gap: 1, marginBottom: 1 }}>
            <div style={{ width: 70, flexShrink: 0, fontSize: 8, color: "#999", display: "flex", alignItems: "center", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
              {comp}
            </div>
            {faultKeys.map(fk => {
              const temp = temperature_matrix[fk][comp];
              const base = base_temperatures[comp];
              const deviation = ((temp - base) / base) * 100;
              return (
                <div
                  key={fk}
                  title={`${comp} under ${fault_types[fk]?.label}: ${temp}°C (base: ${base}°C, ${deviation > 0 ? "+" : ""}${deviation.toFixed(0)}%)`}
                  style={{
                    flex: 1, height: 16, borderRadius: 2,
                    background: heatColor(temp, minT, maxT),
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 7, color: temp > (minT + maxT) / 2 ? "#000" : "#fff",
                    fontWeight: 500,
                  }}
                >
                  {temp.toFixed(0)}°
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Fault timeline (24h) */}
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10, color: "#888", marginBottom: 3 }}>24h Fault Timeline</div>
        <div style={{ display: "flex", gap: 1, height: 14 }}>
          {fault_timeline.map((ft, i) => (
            <div
              key={i}
              title={`${ft.hour}:00 — ${ft.label} (${(ft.confidence * 100).toFixed(0)}%)`}
              style={{
                flex: 1, borderRadius: 2,
                background: fault_types[ft.fault]?.color || "#333",
                opacity: ft.fault === "NF" ? 0.3 : 0.9,
              }}
            />
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 1 }}>
          {[0, 6, 12, 18, 23].map(h => <span key={h} style={{ fontSize: 7, color: "#666" }}>{h}h</span>)}
        </div>
      </div>
    </div>
  );
}

// ── Transmission Line Status ──
function TransmissionStatus({ data }) {
  if (!data) return null;
  const { lines, summary } = data;

  return (
    <div>
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
        {summary.healthy}/{summary.total_lines} lines healthy — Multi-output DT (86.8%)
      </div>

      {lines.map(line => (
        <div key={line.line_id} style={{
          display: "flex", alignItems: "center", gap: 8, padding: "4px 6px",
          marginBottom: 2, borderRadius: 4,
          background: line.healthy ? "rgba(76,175,80,0.08)" : "rgba(244,67,54,0.12)",
          borderLeft: `3px solid ${line.fault_color}`,
        }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: line.healthy ? "#aaa" : line.fault_color }}>
              {line.name}
            </div>
            <div style={{ fontSize: 8, color: "#666" }}>{line.fault_label}</div>
          </div>

          {/* Phase indicators */}
          <div style={{ display: "flex", gap: 3 }}>
            {["Va", "Vb", "Vc"].map(phase => {
              const v = line.voltages[phase];
              const abnormal = Math.abs(v - 1.0) > 0.08;
              return (
                <div key={phase} title={`${phase}: ${v}pu`} style={{
                  width: 18, height: 18, borderRadius: "50%", display: "flex",
                  alignItems: "center", justifyContent: "center",
                  fontSize: 7, fontWeight: 600,
                  background: abnormal ? "rgba(244,67,54,0.3)" : "rgba(76,175,80,0.2)",
                  color: abnormal ? "#f44336" : "#4caf50",
                  border: `1px solid ${abnormal ? "#f44336" : "#4caf5044"}`,
                }}>
                  {phase[1]}
                </div>
              );
            })}
          </div>

          {/* Confidence */}
          <span style={{ fontSize: 9, color: "#888", width: 35, textAlign: "right" }}>
            {(line.confidence * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Grid Stability Gauge ──
function StabilityGauge({ data }) {
  if (!data) return null;
  const { nodes, summary } = data;
  const score = summary.avg_stability_score;
  const angle = score * 180; // 0° = unstable (left), 180° = stable (right)
  const riskColors = { low: "#4caf50", moderate: "#ff9800", high: "#f44336", critical: "#b71c1c" };

  return (
    <div>
      {/* Radial gauge */}
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 6 }}>
        <svg width="140" height="80" viewBox="0 0 140 80">
          {/* Background arc */}
          <path d="M 10 70 A 60 60 0 0 1 130 70" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="10" strokeLinecap="round" />
          {/* Red zone */}
          <path d="M 10 70 A 60 60 0 0 1 40 18" fill="none" stroke="#f4433666" strokeWidth="10" strokeLinecap="round" />
          {/* Yellow zone */}
          <path d="M 40 18 A 60 60 0 0 1 100 18" fill="none" stroke="#ff980066" strokeWidth="10" strokeLinecap="round" />
          {/* Green zone */}
          <path d="M 100 18 A 60 60 0 0 1 130 70" fill="none" stroke="#4caf5066" strokeWidth="10" strokeLinecap="round" />
          {/* Needle */}
          <line
            x1="70" y1="70"
            x2={70 + 50 * Math.cos(Math.PI - angle * Math.PI / 180)}
            y2={70 - 50 * Math.sin(Math.PI - angle * Math.PI / 180)}
            stroke={stabilityColor(score)} strokeWidth="2.5" strokeLinecap="round"
          />
          <circle cx="70" cy="70" r="4" fill={stabilityColor(score)} />
          {/* Score text */}
          <text x="70" y="65" textAnchor="middle" fill="#fff" fontSize="14" fontWeight="700">
            {(score * 100).toFixed(0)}%
          </text>
        </svg>
      </div>

      <div style={{
        textAlign: "center", fontSize: 11, fontWeight: 600,
        color: riskColors[summary.cascade_risk],
        textTransform: "uppercase", marginBottom: 6,
      }}>
        Cascade Risk: {summary.cascade_risk}
      </div>

      {/* Node status bars */}
      {nodes.map((n, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
          <span style={{ fontSize: 9, color: "#888", width: 90, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{n.name}</span>
          <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.05)", borderRadius: 3 }}>
            <div style={{
              height: "100%", borderRadius: 3,
              width: `${n.stability_score * 100}%`,
              background: stabilityColor(n.stability_score),
            }} />
          </div>
          <span style={{ fontSize: 9, color: stabilityColor(n.stability_score), width: 30, textAlign: "right", fontWeight: 600 }}>
            {(n.stability_score * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}


// ══════════════════════════════════════════════════════════════
// Main Energy Analytics Card — container for all sub-panels
// ══════════════════════════════════════════════════════════════

export default function EnergyAnalyticsCard() {
  const { samCapacity, samDay } = useSite();
  const [solarData, setSolarData] = useState(null);
  const [heatmapData, setHeatmapData] = useState(null);
  const [stabilityData, setStabilityData] = useState(null);
  const [prosumerData, setProsumerData] = useState(null);
  const [turbineData, setTurbineData] = useState(null);
  const [transmissionData, setTransmissionData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [prosumerMonth, setProsumerMonth] = useState(new Date().getMonth() + 1);
  const [prosumerBiz, setProsumerBiz] = useState(false);
  const fetchedRef = useRef(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.allSettled([
        api.analytics.solarForecast(samCapacity || 100, samDay || 172),
        api.analytics.consumptionHeatmap(),
        api.analytics.gridStability(),
        api.analytics.prosumerProfile(samCapacity ? samCapacity / 10 : 10, prosumerBiz, prosumerMonth),
        api.analytics.turbineHealth(),
        api.analytics.transmissionFaults(),
      ]);
      const val = r => r.status === "fulfilled" ? r.value : null;
      setSolarData(val(results[0]));
      setHeatmapData(val(results[1]));
      setStabilityData(val(results[2]));
      setProsumerData(val(results[3]));
      setTurbineData(val(results[4]));
      setTransmissionData(val(results[5]));
    } finally {
      setLoading(false);
    }
  }, [samCapacity, samDay, prosumerBiz, prosumerMonth]);

  useEffect(() => {
    if (!fetchedRef.current) {
      fetchedRef.current = true;
      fetchAll();
    }
  }, [fetchAll]);

  // Refetch prosumer on param change
  const prosumerDebounce = useRef(null);
  useEffect(() => {
    if (prosumerDebounce.current) clearTimeout(prosumerDebounce.current);
    prosumerDebounce.current = setTimeout(() => {
      api.analytics.prosumerProfile(samCapacity ? samCapacity / 10 : 10, prosumerBiz, prosumerMonth)
        .then(d => { if (d) setProsumerData(d); });
    }, 400);
    return () => clearTimeout(prosumerDebounce.current);
  }, [prosumerBiz, prosumerMonth, samCapacity]);

  return (
    <>
      {/* Solar Generation Forecast */}
      <MetricCard
        title="Solar Generation Forecast"
        accentColor="#ff9800"
        headerValue={solarData ? `${solarData.daily_yield_kwh} kWh/day` : "Loading..."}
        aiInsight={solarData?.model}
        defaultOpen
      >
        {loading && !solarData && <div style={{ fontSize: 11, color: "#666" }}>Fetching forecast...</div>}
        <SolarForecastChart data={solarData} />
      </MetricCard>

      {/* Consumption Thermograph */}
      <MetricCard
        title="Consumption Thermograph"
        accentColor="#2196f3"
        headerValue="Hour × Day Heatmap"
        aiInsight={heatmapData?.model}
        defaultOpen
      >
        <Thermograph data={heatmapData} />
      </MetricCard>

      {/* Grid Stability (DSGC Model) */}
      <MetricCard
        title="Grid Stability Model"
        accentColor={stabilityData?.summary?.cascade_risk === "low" ? "#4caf50" : "#ff9800"}
        headerValue={stabilityData ? `${stabilityData.summary.percent_stable}% stable` : "Loading..."}
        aiInsight={stabilityData?.model}
        defaultOpen
      >
        <StabilityGauge data={stabilityData} />
      </MetricCard>

      {/* Prosumer Profile */}
      <MetricCard
        title="Prosumer Profile"
        accentColor="#9c27b0"
        headerValue={prosumerData ? `${prosumerData.summary.self_sufficiency_pct}% self-sufficient` : "Loading..."}
        aiInsight={prosumerData?.model}
        defaultOpen
      >
        <div style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
          <select value={prosumerMonth} onChange={e => setProsumerMonth(Number(e.target.value))}
            style={{ background: "#1a1e26", color: "#ccc", border: "1px solid #333", borderRadius: 4, padding: "2px 4px", fontSize: 10 }}>
            {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => (
              <option key={i} value={i + 1}>{m}</option>
            ))}
          </select>
          <label style={{ fontSize: 10, color: "#888", display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={prosumerBiz} onChange={e => setProsumerBiz(e.target.checked)} />
            Business
          </label>
        </div>
        <ProsumerChart data={prosumerData} />
      </MetricCard>

      {/* Turbine Health Thermograph */}
      <MetricCard
        title="Turbine Health Monitor"
        accentColor={turbineData?.current_status?.fault === "NF" ? "#4caf50" : "#f44336"}
        headerValue={turbineData ? turbineData.current_status.label : "Loading..."}
        aiInsight={turbineData?.model}
      >
        <TurbineThermograph data={turbineData} />
      </MetricCard>

      {/* Transmission Line Faults */}
      <MetricCard
        title="Transmission Line Status"
        accentColor={transmissionData?.summary?.faulted > 0 ? "#ff9800" : "#4caf50"}
        headerValue={transmissionData ? `${transmissionData.summary.overall_health_pct}% healthy` : "Loading..."}
        aiInsight={transmissionData?.model}
      >
        <TransmissionStatus data={transmissionData} />
      </MetricCard>
    </>
  );
}
