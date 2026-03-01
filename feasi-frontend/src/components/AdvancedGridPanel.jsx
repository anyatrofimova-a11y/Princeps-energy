import React, { useState, useEffect, useCallback } from "react";
import api from "../services/api";

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
}
function pct(v) { return v != null ? `${v.toFixed(1)}%` : "--"; }

const TABS = [
  { id: "dlr", label: "DLR" },
  { id: "congestion", label: "Congestion" },
  { id: "optimiser", label: "Optimiser" },
  { id: "cost", label: "Cost" },
];

const CONDUCTORS = ["Lynx", "Zebra", "Rubus", "Matthew", "Araucaria"];

/* ── Seasonal DLR chart ──────────────────────────────────────────────────── */
function SeasonalChart({ profiles, width = 560, height = 180 }) {
  if (!profiles) return null;
  const seasons = Object.entries(profiles);
  const pad = { l: 48, r: 12, t: 10, b: 22 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const allVals = seasons.flatMap(([, hrs]) => hrs.map(h => h.uplift_pct));
  const yMin = Math.min(0, ...allVals);
  const yMax = Math.max(10, ...allVals);
  const xScale = (i) => pad.l + (i / 23) * w;
  const yScale = (v) => pad.t + h - ((v - yMin) / (yMax - yMin)) * h;

  const colors = { winter: "#1890ff", spring: "#52c41a", summer: "#fa8c16" };

  return (
    <svg width={width} height={height} className="ag-chart">
      {/* zero line */}
      <line x1={pad.l} x2={pad.l + w} y1={yScale(0)} y2={yScale(0)} stroke="#555" strokeDasharray="3,3" />
      {/* Y axis labels */}
      {[yMin, (yMin + yMax) / 2, yMax].map(v => (
        <text key={v} x={pad.l - 4} y={yScale(v)} textAnchor="end" fill="#999" fontSize="9" dy="3">{v.toFixed(0)}%</text>
      ))}
      {/* X axis */}
      {[0, 6, 12, 18, 23].map(h => (
        <text key={h} x={xScale(h)} y={height - 4} textAnchor="middle" fill="#999" fontSize="9">{h}:00</text>
      ))}
      {/* Lines */}
      {seasons.map(([name, hrs]) => (
        <polyline
          key={name}
          fill="none"
          stroke={colors[name] || "#999"}
          strokeWidth="1.5"
          points={hrs.map((h, i) => `${xScale(i)},${yScale(h.uplift_pct)}`).join(" ")}
        />
      ))}
    </svg>
  );
}

/* ── Congestion heatmap ──────────────────────────────────────────────────── */
function CongestionHeatmap({ boundaries, width = 560, height = 200 }) {
  if (!boundaries?.length) return null;
  const pad = { l: 130, r: 12, t: 10, b: 6 };
  const w = width - pad.l - pad.r;
  const barH = Math.min(22, (height - pad.t - pad.b) / boundaries.length);

  function riskColor(prob) {
    if (prob > 0.6) return "#da1e28";
    if (prob > 0.3) return "#fa8c16";
    return "#24a148";
  }

  return (
    <svg width={width} height={pad.t + boundaries.length * barH + pad.b} className="ag-chart">
      {boundaries.map((b, i) => {
        const y = pad.t + i * barH;
        const bw = (b.loading_pct / 120) * w;
        return (
          <g key={b.boundary_id}>
            <text x={pad.l - 6} y={y + barH / 2} textAnchor="end" fill="#ccc" fontSize="10" dy="3.5">
              {b.boundary_name}
            </text>
            <rect x={pad.l} y={y + 2} width={w} height={barH - 4} rx="2" fill="#262626" />
            <rect x={pad.l} y={y + 2} width={Math.max(0, bw)} height={barH - 4} rx="2" fill={riskColor(b.congestion_probability)} opacity="0.8" />
            <text x={pad.l + Math.max(0, bw) + 4} y={y + barH / 2} fill="#ccc" fontSize="9" dy="3">
              {b.loading_pct}% · {b.risk_level}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Pareto chart ────────────────────────────────────────────────────────── */
function ParetoChart({ pareto, allFeasible, width = 560, height = 220 }) {
  const all = allFeasible || [];
  if (!all.length) return null;
  const pad = { l: 55, r: 16, t: 14, b: 30 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const distMax = Math.max(1, ...all.map(c => c.distance_km));
  const costMax = Math.max(1, ...all.map(c => c.total_cost_gbp));
  const xScale = (v) => pad.l + (v / distMax) * w;
  const yScale = (v) => pad.t + h - (v / costMax) * h;

  const paretoSet = new Set((pareto || []).map(p => p.name));

  return (
    <svg width={width} height={height} className="ag-chart">
      {/* axes */}
      <line x1={pad.l} x2={pad.l + w} y1={pad.t + h} y2={pad.t + h} stroke="#555" />
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={pad.t + h} stroke="#555" />
      <text x={width / 2} y={height - 4} textAnchor="middle" fill="#999" fontSize="9">Distance (km)</text>
      <text x={10} y={height / 2} textAnchor="middle" fill="#999" fontSize="9" transform={`rotate(-90,10,${height / 2})`}>Cost (£)</text>
      {/* points */}
      {all.map(c => (
        <g key={c.name}>
          <circle
            cx={xScale(c.distance_km)} cy={yScale(c.total_cost_gbp)} r={paretoSet.has(c.name) ? 6 : 4}
            fill={paretoSet.has(c.name) ? "#1890ff" : "#555"}
            stroke={paretoSet.has(c.name) ? "#40a9ff" : "none"} strokeWidth="1.5"
            opacity={paretoSet.has(c.name) ? 1 : 0.5}
          />
          {paretoSet.has(c.name) && (
            <text x={xScale(c.distance_km)} y={yScale(c.total_cost_gbp) - 8} textAnchor="middle" fill="#40a9ff" fontSize="8">{c.name}</text>
          )}
        </g>
      ))}
      {/* Pareto frontier line */}
      {pareto?.length > 1 && (
        <polyline
          fill="none" stroke="#1890ff" strokeWidth="1" strokeDasharray="4,2" opacity="0.6"
          points={[...pareto].sort((a, b) => a.distance_km - b.distance_km).map(c => `${xScale(c.distance_km)},${yScale(c.total_cost_gbp)}`).join(" ")}
        />
      )}
    </svg>
  );
}

/* ── Cost breakdown bars ─────────────────────────────────────────────────── */
function CostBreakdown({ components, width = 560 }) {
  if (!components?.length) return null;
  const maxVal = Math.max(1, ...components.map(c => c.p90_gbp));

  return (
    <div className="ag-cost-breakdown">
      {components.map(c => (
        <div key={c.name} className="ag-cost-row">
          <span className="ag-cost-label">{c.name}</span>
          <div className="ag-cost-bar-track">
            <div className="ag-cost-bar ag-cost-p10" style={{ width: `${(c.p10_gbp / maxVal) * 100}%` }} />
            <div className="ag-cost-bar ag-cost-p50" style={{ width: `${(c.p50_gbp / maxVal) * 100}%` }} />
            <div className="ag-cost-bar ag-cost-p90" style={{ width: `${(c.p90_gbp / maxVal) * 100}%` }} />
          </div>
          <span className="ag-cost-val">{fmtGbp(c.p50_gbp)}</span>
        </div>
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function AdvancedGridPanel({ onClose }) {
  const [tab, setTab] = useState("dlr");

  // ── DLR state ──
  const [conductor, setConductor] = useState("Zebra");
  const [dlrTemp, setDlrTemp] = useState(15);
  const [dlrWind, setDlrWind] = useState(3);
  const [dlrSolar, setDlrSolar] = useState(200);
  const [dlrResult, setDlrResult] = useState(null);
  const [seasonalData, setSeasonalData] = useState(null);
  const [dlrLoading, setDlrLoading] = useState(false);

  // ── Congestion state ──
  const [congestionData, setCongestionData] = useState(null);
  const [congHour, setCongHour] = useState(17);
  const [congMonth, setCongMonth] = useState(1);
  const [congDemand, setCongDemand] = useState(42);
  const [congWind, setCongWind] = useState(8);
  const [congLoading, setCongLoading] = useState(false);

  // ── Optimiser state ──
  const [optResult, setOptResult] = useState(null);
  const [optLat, setOptLat] = useState(51.5);
  const [optLon, setOptLon] = useState(-1.0);
  const [optCapacity, setOptCapacity] = useState(50);
  const [optLoading, setOptLoading] = useState(false);

  // ── Cost state ──
  const [costResult, setCostResult] = useState(null);
  const [costDist, setCostDist] = useState(5);
  const [costVoltage, setCostVoltage] = useState(132);
  const [costCapacity, setCostCapacity] = useState(50);
  const [costTerrain, setCostTerrain] = useState("rural");
  const [costLoading, setCostLoading] = useState(false);

  // ── DLR fetch ──
  const fetchDlr = useCallback(async () => {
    setDlrLoading(true);
    try {
      const [rate, seasonal] = await Promise.all([
        api.advancedGrid.dlrRate(conductor, dlrTemp, dlrWind, 45, dlrSolar),
        api.advancedGrid.dlrSeasonal(conductor),
      ]);
      if (rate) setDlrResult(rate);
      if (seasonal) setSeasonalData(seasonal);
    } catch (e) { console.error(e); }
    setDlrLoading(false);
  }, [conductor, dlrTemp, dlrWind, dlrSolar]);

  useEffect(() => { if (tab === "dlr") fetchDlr(); }, [tab]); // eslint-disable-line

  // ── Congestion fetch ──
  const fetchCongestion = useCallback(async () => {
    setCongLoading(true);
    try {
      const data = await api.advancedGrid.congestionPredict({
        hour: congHour, month: congMonth, demand_gw: congDemand, wind_gen_gw: congWind,
      });
      if (data) setCongestionData(data);
    } catch (e) { console.error(e); }
    setCongLoading(false);
  }, [congHour, congMonth, congDemand, congWind]);

  useEffect(() => { if (tab === "congestion") fetchCongestion(); }, [tab]); // eslint-disable-line

  // ── Optimiser fetch ──
  const fetchOptimiser = useCallback(async () => {
    setOptLoading(true);
    try {
      const data = await api.advancedGrid.optimise(optLat, optLon, optCapacity);
      if (data) setOptResult(data);
    } catch (e) { console.error(e); }
    setOptLoading(false);
  }, [optLat, optLon, optCapacity]);

  useEffect(() => { if (tab === "optimiser") fetchOptimiser(); }, [tab]); // eslint-disable-line

  // ── Cost fetch ──
  const fetchCost = useCallback(async () => {
    setCostLoading(true);
    try {
      const data = await api.advancedGrid.reinforcementEstimate(costDist, costVoltage, costCapacity, 0, costTerrain);
      if (data) setCostResult(data);
    } catch (e) { console.error(e); }
    setCostLoading(false);
  }, [costDist, costVoltage, costCapacity, costTerrain]);

  useEffect(() => { if (tab === "cost") fetchCost(); }, [tab]); // eslint-disable-line

  return (
    <div className="gc-panel ag-panel">
      <div className="gc-panel-header">
        <span className="gc-panel-title">Advanced Grid Analysis</span>
        <button className="gc-panel-close" onClick={onClose}>×</button>
      </div>

      {/* Tabs */}
      <div className="ag-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`ag-tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="ag-body">
        {/* ═══ DLR Tab ═══ */}
        {tab === "dlr" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Conductor
                <select value={conductor} onChange={e => setConductor(e.target.value)}>
                  {CONDUCTORS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label>
                Temp (°C)
                <input type="number" value={dlrTemp} onChange={e => setDlrTemp(+e.target.value)} style={{ width: 52 }} />
              </label>
              <label>
                Wind (m/s)
                <input type="number" value={dlrWind} onChange={e => setDlrWind(+e.target.value)} min={0} step={0.5} style={{ width: 52 }} />
              </label>
              <label>
                Solar (W/m²)
                <input type="number" value={dlrSolar} onChange={e => setDlrSolar(+e.target.value)} min={0} step={50} style={{ width: 60 }} />
              </label>
              <button className="ag-btn" onClick={fetchDlr} disabled={dlrLoading}>{dlrLoading ? "…" : "Calculate"}</button>
            </div>

            {dlrResult && !dlrResult.error && (
              <>
                <div className="ag-stat-grid">
                  <div className="ag-stat">
                    <span className="ag-stat-label">Dynamic Rating</span>
                    <span className="ag-stat-value" style={{ color: "#40a9ff" }}>{dlrResult.ampacity_a} A</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Static Rating</span>
                    <span className="ag-stat-value">{dlrResult.static_rating_a} A</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Uplift</span>
                    <span className="ag-stat-value" style={{ color: dlrResult.uplift_pct > 0 ? "#52c41a" : "#fa8c16" }}>
                      {dlrResult.uplift_pct > 0 ? "+" : ""}{pct(dlrResult.uplift_pct)}
                    </span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Max Temp</span>
                    <span className="ag-stat-value">{dlrResult.max_temp_c}°C</span>
                  </div>
                </div>

                {dlrResult.capacity_mw && (
                  <div className="ag-capacity-list">
                    <span className="ag-subsection-title">Capacity</span>
                    {Object.entries(dlrResult.capacity_mw).map(([k, v]) => (
                      <span key={k} className="ag-capacity-item">{k}: {v} MW</span>
                    ))}
                  </div>
                )}

                <div className="ag-heat-balance">
                  <span className="ag-subsection-title">Heat Balance (W/m)</span>
                  <div className="ag-stat-grid">
                    <div className="ag-stat"><span className="ag-stat-label">Convective</span><span className="ag-stat-value">{dlrResult.heat_balance_wm?.convective}</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Radiative</span><span className="ag-stat-value">{dlrResult.heat_balance_wm?.radiative}</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Solar Gain</span><span className="ag-stat-value">{dlrResult.heat_balance_wm?.solar_gain}</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Net Cooling</span><span className="ag-stat-value" style={{ color: "#52c41a" }}>{dlrResult.heat_balance_wm?.net_cooling}</span></div>
                  </div>
                </div>

                {seasonalData?.profiles && (
                  <div className="ag-seasonal">
                    <span className="ag-subsection-title">Seasonal Uplift Profile</span>
                    <div className="ag-legend-row">
                      <span className="ag-legend-dot" style={{ background: "#1890ff" }} /> Winter
                      <span className="ag-legend-dot" style={{ background: "#52c41a" }} /> Spring
                      <span className="ag-legend-dot" style={{ background: "#fa8c16" }} /> Summer
                    </div>
                    <SeasonalChart profiles={seasonalData.profiles} />
                    {seasonalData.summary && (
                      <div className="ag-stat-grid" style={{ marginTop: 8 }}>
                        {Object.entries(seasonalData.summary).map(([s, v]) => (
                          <div className="ag-stat" key={s}>
                            <span className="ag-stat-label">{s} uplift</span>
                            <span className="ag-stat-value">{v.min_uplift_pct}–{v.max_uplift_pct}%</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ═══ Congestion Tab ═══ */}
        {tab === "congestion" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Hour
                <input type="range" min={0} max={23} value={congHour} onChange={e => setCongHour(+e.target.value)} />
                <span className="ag-range-val">{congHour}:00</span>
              </label>
              <label>
                Month
                <input type="range" min={1} max={12} value={congMonth} onChange={e => setCongMonth(+e.target.value)} />
                <span className="ag-range-val">{["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][congMonth - 1]}</span>
              </label>
              <label>
                Demand (GW)
                <input type="number" value={congDemand} onChange={e => setCongDemand(+e.target.value)} style={{ width: 52 }} />
              </label>
              <label>
                Wind (GW)
                <input type="number" value={congWind} onChange={e => setCongWind(+e.target.value)} style={{ width: 52 }} />
              </label>
              <button className="ag-btn" onClick={fetchCongestion} disabled={congLoading}>{congLoading ? "…" : "Predict"}</button>
            </div>

            {congestionData?.summary && (
              <div className="ag-stat-grid">
                <div className="ag-stat">
                  <span className="ag-stat-label">System Risk</span>
                  <span className={`ag-risk-pill ag-risk-${congestionData.summary.system_risk.toLowerCase()}`}>
                    {congestionData.summary.system_risk}
                  </span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">Max Congestion</span>
                  <span className="ag-stat-value">{pct(congestionData.summary.max_congestion_probability * 100)}</span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">High-Risk Boundaries</span>
                  <span className="ag-stat-value" style={{ color: "#da1e28" }}>{congestionData.summary.high_risk_boundaries}</span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">Total Constraint Cost</span>
                  <span className="ag-stat-value">{fmtGbp(congestionData.summary.total_constraint_cost_gbp)}</span>
                </div>
              </div>
            )}

            {congestionData?.boundaries && (
              <>
                <span className="ag-subsection-title">Boundary Loading</span>
                <CongestionHeatmap boundaries={congestionData.boundaries} />
                <div className="ag-boundary-table">
                  <div className="ag-table-header">
                    <span>Boundary</span><span>Flow</span><span>Cap</span><span>Load%</span><span>Prob</span><span>Risk</span>
                  </div>
                  {congestionData.boundaries.map(b => (
                    <div key={b.boundary_id} className="ag-table-row">
                      <span>{b.boundary_name}</span>
                      <span>{b.estimated_flow_gw} GW</span>
                      <span>{b.capacity_gw} GW</span>
                      <span>{b.loading_pct}%</span>
                      <span>{(b.congestion_probability * 100).toFixed(0)}%</span>
                      <span className={`ag-risk-pill ag-risk-${b.risk_level.toLowerCase()}`}>{b.risk_level}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* ═══ Optimiser Tab ═══ */}
        {tab === "optimiser" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Lat
                <input type="number" value={optLat} onChange={e => setOptLat(+e.target.value)} step={0.1} style={{ width: 64 }} />
              </label>
              <label>
                Lon
                <input type="number" value={optLon} onChange={e => setOptLon(+e.target.value)} step={0.1} style={{ width: 64 }} />
              </label>
              <label>
                Capacity (MW)
                <input type="number" value={optCapacity} onChange={e => setOptCapacity(+e.target.value)} style={{ width: 56 }} />
              </label>
              <button className="ag-btn" onClick={fetchOptimiser} disabled={optLoading}>{optLoading ? "…" : "Optimise"}</button>
            </div>

            {optResult && (
              <>
                <div className="ag-stat-grid">
                  <div className="ag-stat">
                    <span className="ag-stat-label">Candidates</span>
                    <span className="ag-stat-value">{optResult.candidates_total}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Feasible</span>
                    <span className="ag-stat-value" style={{ color: "#52c41a" }}>{optResult.candidates_feasible}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Pareto Optimal</span>
                    <span className="ag-stat-value" style={{ color: "#1890ff" }}>{optResult.pareto_optimal}</span>
                  </div>
                </div>

                {optResult.recommended && (
                  <div className="ag-recommended">
                    <span className="ag-subsection-title">Recommended</span>
                    <div className="ag-rec-card">
                      <span className="ag-rec-name">{optResult.recommended.name}</span>
                      <div className="ag-stat-grid">
                        <div className="ag-stat"><span className="ag-stat-label">Distance</span><span className="ag-stat-value">{optResult.recommended.distance_km} km</span></div>
                        <div className="ag-stat"><span className="ag-stat-label">Cost</span><span className="ag-stat-value">{fmtGbp(optResult.recommended.total_cost_gbp)}</span></div>
                        <div className="ag-stat"><span className="ag-stat-label">Voltage</span><span className="ag-stat-value">{optResult.recommended.voltage_kv} kV</span></div>
                        <div className="ag-stat"><span className="ag-stat-label">Queue</span><span className="ag-stat-value">{optResult.recommended.queue_wait_months} mo</span></div>
                        <div className="ag-stat"><span className="ag-stat-label">Headroom</span><span className="ag-stat-value">{optResult.recommended.headroom_mw} MW</span></div>
                        <div className="ag-stat"><span className="ag-stat-label">Score</span><span className="ag-stat-value" style={{ color: "#1890ff" }}>{optResult.recommended.scores?.composite}</span></div>
                      </div>
                    </div>
                  </div>
                )}

                <span className="ag-subsection-title">Pareto Frontier (Distance vs Cost)</span>
                <ParetoChart pareto={optResult.pareto_frontier} allFeasible={optResult.all_feasible} />

                {optResult.all_feasible?.length > 0 && (
                  <div className="ag-candidates-table">
                    <div className="ag-table-header">
                      <span>Name</span><span>Dist</span><span>Cost</span><span>kV</span><span>Queue</span><span>Score</span>
                    </div>
                    {optResult.all_feasible.map(c => (
                      <div key={c.name} className="ag-table-row">
                        <span>{c.name}</span>
                        <span>{c.distance_km} km</span>
                        <span>{fmtGbp(c.total_cost_gbp)}</span>
                        <span>{c.voltage_kv}</span>
                        <span>{c.queue_wait_months} mo</span>
                        <span style={{ color: "#1890ff" }}>{c.scores?.composite}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ═══ Cost Tab ═══ */}
        {tab === "cost" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Distance (km)
                <input type="number" value={costDist} onChange={e => setCostDist(+e.target.value)} min={0.1} step={0.5} style={{ width: 52 }} />
              </label>
              <label>
                Voltage (kV)
                <select value={costVoltage} onChange={e => setCostVoltage(+e.target.value)}>
                  {[11, 33, 66, 132, 275, 400].map(v => <option key={v} value={v}>{v} kV</option>)}
                </select>
              </label>
              <label>
                Capacity (MW)
                <input type="number" value={costCapacity} onChange={e => setCostCapacity(+e.target.value)} style={{ width: 56 }} />
              </label>
              <label>
                Terrain
                <select value={costTerrain} onChange={e => setCostTerrain(e.target.value)}>
                  {["rural", "suburban", "urban", "upland", "coastal"].map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <button className="ag-btn" onClick={fetchCost} disabled={costLoading}>{costLoading ? "…" : "Estimate"}</button>
            </div>

            {costResult?.total && (
              <>
                <div className="ag-stat-grid">
                  <div className="ag-stat">
                    <span className="ag-stat-label">P10 (Low)</span>
                    <span className="ag-stat-value" style={{ color: "#52c41a" }}>{fmtGbp(costResult.total.p10_gbp)}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">P50 (Central)</span>
                    <span className="ag-stat-value" style={{ color: "#1890ff" }}>{fmtGbp(costResult.total.p50_gbp)}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">P90 (High)</span>
                    <span className="ag-stat-value" style={{ color: "#fa8c16" }}>{fmtGbp(costResult.total.p90_gbp)}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Mean</span>
                    <span className="ag-stat-value">{fmtGbp(costResult.total.mean_gbp)}</span>
                  </div>
                </div>

                <div className="ag-cost-meta">
                  <span>Terrain factor: {costResult.terrain_factor}x</span>
                  <span>Monte Carlo: {costResult.monte_carlo_samples} samples</span>
                  <span>Transformer: {costResult.parameters?.needs_transformer ? "Yes" : "No"}</span>
                </div>

                <span className="ag-subsection-title">Component Breakdown (P10 / P50 / P90)</span>
                <CostBreakdown components={costResult.components} />

                <div className="ag-cost-legend">
                  <span className="ag-cost-legend-item"><span className="ag-cost-swatch" style={{ background: "#52c41a" }} />P10</span>
                  <span className="ag-cost-legend-item"><span className="ag-cost-swatch" style={{ background: "#1890ff" }} />P50</span>
                  <span className="ag-cost-legend-item"><span className="ag-cost-swatch" style={{ background: "#fa8c16" }} />P90</span>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="ag-footer">
        <span className="ag-footer-text">IEEE 738 · CIGRE TB601 · UK DNO benchmarks 2024</span>
      </div>
    </div>
  );
}
