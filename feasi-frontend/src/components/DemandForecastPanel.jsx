import React, { useState, useCallback, useEffect, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";
import Provenance from "./Provenance";

/* ── FES scenario metadata ─────────────────────────────────────────────── */
const SCENARIOS = [
  { id: "leading_the_way", label: "Leading the Way", color: "#f5222d", desc: "Fastest decarbonisation" },
  { id: "consumer_transformation", label: "Consumer Transform.", color: "#fa8c16", desc: "Consumer-led flexibility" },
  { id: "system_transformation", label: "System Transform.", color: "#1890ff", desc: "Supply-side hydrogen" },
  { id: "falling_short", label: "Falling Short", color: "#8c8c8c", desc: "Slowest progress" },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${v.toFixed(0)} MW`;
}
function pct(v) { return v != null ? `${(v * 100).toFixed(1)}%` : "--"; }
function clampIdx(i, len) { return Math.max(0, Math.min(i, len - 1)); }

/* ── Inline SVG time-series chart with P10/P50/P90 bands ───────────────── */
function ForecastChart({ forecasts, capacityMw, width = 600, height = 200, sliderIdx }) {
  if (!forecasts?.length) return null;

  const pad = { l: 50, r: 16, t: 10, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const allVals = forecasts.flatMap(f => [f.p10_mw, f.p50_mw, f.p90_mw]);
  if (capacityMw) allVals.push(capacityMw);
  const yMin = Math.floor(Math.min(...allVals) * 0.9);
  const yMax = Math.ceil(Math.max(...allVals) * 1.05);

  const x = (i) => pad.l + (i / (forecasts.length - 1)) * w;
  const y = (v) => pad.t + h - ((v - yMin) / (yMax - yMin)) * h;

  // Band path (P10 to P90)
  const bandUp = forecasts.map((f, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(f.p90_mw)}`).join(" ");
  const bandDown = [...forecasts].reverse().map((f, i) => {
    const idx = forecasts.length - 1 - i;
    return `L${x(idx)},${y(f.p10_mw)}`;
  }).join(" ");
  const bandPath = `${bandUp} ${bandDown} Z`;

  // P50 line
  const p50Line = forecasts.map((f, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(f.p50_mw)}`).join(" ");

  // X-axis labels (show ~6 labels)
  const step = Math.max(1, Math.floor(forecasts.length / 6));
  const xLabels = [];
  for (let i = 0; i < forecasts.length; i += step) {
    const ts = forecasts[i].timestamp_utc;
    const d = new Date(ts);
    xLabels.push({ i, label: `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:00` });
  }

  // Y-axis labels
  const yTicks = 5;
  const yLabels = [];
  for (let t = 0; t <= yTicks; t++) {
    const v = yMin + (yMax - yMin) * (t / yTicks);
    yLabels.push({ v, y: y(v) });
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="df-chart" style={{ width: "100%", height: "auto" }}>
      {/* Grid lines */}
      {yLabels.map(({ v, y: yy }) => (
        <g key={v}>
          <line x1={pad.l} y1={yy} x2={width - pad.r} y2={yy} stroke="rgba(255,255,255,0.06)" />
          <text x={pad.l - 6} y={yy + 4} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize="9">{Math.round(v)}</text>
        </g>
      ))}

      {/* Capacity line */}
      {capacityMw && (
        <>
          <line x1={pad.l} y1={y(capacityMw)} x2={width - pad.r} y2={y(capacityMw)}
            stroke="#f5222d" strokeDasharray="4 3" strokeWidth={1} opacity={0.7} />
          <text x={width - pad.r + 2} y={y(capacityMw) + 3} fill="#f5222d" fontSize="8">Cap</text>
        </>
      )}

      {/* P10-P90 band */}
      <path d={bandPath} fill="rgba(15,98,254,0.15)" />

      {/* P50 line */}
      <path d={p50Line} fill="none" stroke="#D4A018" strokeWidth={1.5} />

      {/* Slider indicator */}
      {sliderIdx != null && sliderIdx < forecasts.length && (
        <>
          <line x1={x(sliderIdx)} y1={pad.t} x2={x(sliderIdx)} y2={pad.t + h}
            stroke="rgba(255,255,255,0.4)" strokeWidth={1} strokeDasharray="2 2" />
          <circle cx={x(sliderIdx)} cy={y(forecasts[sliderIdx].p50_mw)} r={4}
            fill="#D4A018" stroke="#fff" strokeWidth={1.5} />
        </>
      )}

      {/* X labels */}
      {xLabels.map(({ i, label }) => (
        <text key={i} x={x(i)} y={height - 4} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="8">{label}</text>
      ))}
    </svg>
  );
}

/* ── Scenario projection chart (annual bars) ────────────────────────────── */
function ScenarioChart({ annual, scenarios, width = 600, height = 220 }) {
  if (!annual?.length) return null;

  const pad = { l: 50, r: 16, t: 10, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const allVals = annual.flatMap(a => [a.p10_mw, a.p90_mw, a.capacity_mw]);
  const yMin = Math.floor(Math.min(...allVals) * 0.9);
  const yMax = Math.ceil(Math.max(...allVals) * 1.05);
  const barW = w / annual.length * 0.7;
  const gap = w / annual.length;

  const y = (v) => pad.t + h - ((v - yMin) / (yMax - yMin)) * h;

  // Scenario trajectories
  const scenLines = scenarios ? Object.entries(scenarios).map(([key, s]) => {
    const meta = SCENARIOS.find(sc => sc.id === key);
    const line = s.trajectory.map((pt, i) =>
      `${i === 0 ? "M" : "L"}${pad.l + i * gap + gap / 2},${y(pt.peak_demand_mw)}`
    ).join(" ");
    return { key, line, color: meta?.color || "#888", label: s.label };
  }) : [];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="df-chart" style={{ width: "100%", height: "auto" }}>
      {/* Capacity line */}
      {annual[0]?.capacity_mw && (
        <>
          <line x1={pad.l} y1={y(annual[0].capacity_mw)} x2={width - pad.r} y2={y(annual[0].capacity_mw)}
            stroke="#f5222d" strokeDasharray="4 3" strokeWidth={1} opacity={0.7} />
          <text x={width - pad.r + 2} y={y(annual[0].capacity_mw) + 3} fill="#f5222d" fontSize="8">Capacity</text>
        </>
      )}

      {/* P10-P90 range bars */}
      {annual.map((a, i) => {
        const xc = pad.l + i * gap + gap / 2;
        const exceed = a.exceedance_probability > 0.1;
        return (
          <g key={a.year}>
            <rect x={xc - barW / 2} y={y(a.p90_mw)} width={barW}
              height={Math.max(1, y(a.p10_mw) - y(a.p90_mw))}
              fill={exceed ? "rgba(245,34,45,0.25)" : "rgba(15,98,254,0.2)"} rx={2} />
            <line x1={xc - barW / 3} y1={y(a.p50_mw)} x2={xc + barW / 3} y2={y(a.p50_mw)}
              stroke={exceed ? "#f5222d" : "#D4A018"} strokeWidth={2} />
            <text x={xc} y={height - 6} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="8">
              {a.year}
            </text>
          </g>
        );
      })}

      {/* Scenario trajectory lines */}
      {scenLines.map(s => (
        <path key={s.key} d={s.line} fill="none" stroke={s.color} strokeWidth={1.2}
          strokeDasharray="3 2" opacity={0.7} />
      ))}
    </svg>
  );
}

/* ── Utilisation bar ────────────────────────────────────────────────────── */
function UtilBar({ value, label }) {
  const pctVal = Math.min(value * 100, 120);
  const color = value >= 0.9 ? "#f5222d" : value >= 0.7 ? "#fa8c16" : "#52c41a";
  return (
    <div className="df-util-bar">
      <div className="df-util-label">{label}</div>
      <div className="df-util-track">
        <div className="df-util-fill" style={{ width: `${Math.min(pctVal, 100)}%`, background: color }} />
        {value >= 0.8 && <div className="df-util-mark" style={{ left: "80%" }} />}
      </div>
      <div className="df-util-value" style={{ color }}>{(value * 100).toFixed(1)}%</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DemandForecastPanel — right slide-in panel
   ═══════════════════════════════════════════════════════════════════════════ */
/* Haversine km between two (lat, lon) — used to pick nearest GSP. */
function _haversineKm(a, b) {
  if (!a || !b || a.lat == null || b.lat == null) return Infinity;
  const R = 6371;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLon = (b.lon - a.lon) * Math.PI / 180;
  const lat1 = a.lat * Math.PI / 180;
  const lat2 = b.lat * Math.PI / 180;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

export default function DemandForecastPanel({ onClose }) {
  const { selectedParcel, explain, pickedLocation } = useSite();

  // Site coords — prefer explicit explain.lat/lon, fall back to picked marker.
  const siteCoord = (() => {
    const lat = explain?.lat ?? pickedLocation?.lat ?? selectedParcel?.lat;
    const lon = explain?.lon ?? pickedLocation?.lon ?? selectedParcel?.lon;
    return lat != null && lon != null ? { lat, lon } : null;
  })();

  /* ── State ── */
  const [gsps, setGsps] = useState([]);
  const [selectedGsp, setSelectedGsp] = useState(null);
  const [autoPickedFor, setAutoPickedFor] = useState(null); // track which coord we auto-picked for
  const [forecast, setForecast] = useState(null);
  const [scenarios, setScenarios] = useState(null);
  const [historical, setHistorical] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scenLoading, setScenLoading] = useState(false);
  const [error, setError] = useState(null);
  const [horizonHours, setHorizonHours] = useState(168);
  const [sliderIdx, setSliderIdx] = useState(0);
  const [activeTab, setActiveTab] = useState("forecast"); // forecast | scenarios | historical
  const [activeScenarios, setActiveScenarios] = useState(
    SCENARIOS.reduce((o, s) => ({ ...o, [s.id]: true }), {})
  );

  /* ── Load GSP list on mount ── */
  useEffect(() => {
    api.demand.gsps().then(data => {
      if (data?.gsps) setGsps(data.gsps);
    });
  }, []);

  /* ── Auto-pick nearest GSP to the active site ──
     If we have a site coord and the user hasn't already manually chosen a
     different GSP for this coord, pick the closest one. Recomputes when the
     site moves. */
  useEffect(() => {
    if (!gsps.length) return;
    if (!siteCoord) {
      // No site context — default to Beddington (London) as a sane national demo pick
      // rather than the alphabetical first entry.
      if (!selectedGsp) {
        const demo = gsps.find(g => g.gsp_id === "BEDD") || gsps[0];
        setSelectedGsp(demo);
      }
      return;
    }
    const key = `${siteCoord.lat.toFixed(3)},${siteCoord.lon.toFixed(3)}`;
    if (autoPickedFor === key) return;
    const ranked = [...gsps]
      .map(g => ({ ...g, _km: _haversineKm(siteCoord, g) }))
      .sort((a, b) => a._km - b._km);
    const nearest = ranked[0];
    if (nearest) {
      setSelectedGsp(nearest);
      setAutoPickedFor(key);
    }
  }, [gsps, siteCoord?.lat, siteCoord?.lon, autoPickedFor]);

  /* ── Load forecast when GSP selected ── */
  const loadForecast = useCallback(async (gsp) => {
    if (!gsp) return;
    setLoading(true);
    setError(null);
    try {
      const [fc, hist] = await Promise.all([
        api.demand.forecast(gsp.gsp_id, horizonHours, "analytical", gsp.peak_demand_mw, gsp.min_demand_mw, gsp.capacity_mw),
        api.demand.historical(gsp.gsp_id, 30),
      ]);
      setForecast(fc);
      setHistorical(hist);
      setSliderIdx(0);
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [horizonHours]);

  const loadScenarios = useCallback(async (gsp) => {
    if (!gsp) return;
    setScenLoading(true);
    try {
      const sc = await api.demand.scenarios(gsp.gsp_id, gsp.peak_demand_mw, gsp.min_demand_mw, gsp.capacity_mw, 15);
      setScenarios(sc);
    } catch (e) { /* ignore */ }
    setScenLoading(false);
  }, []);

  useEffect(() => {
    if (selectedGsp) {
      loadForecast(selectedGsp);
      loadScenarios(selectedGsp);
    }
  }, [selectedGsp, loadForecast, loadScenarios]);

  /* ── Current slider point ── */
  const sliderPoint = forecast?.forecasts?.[sliderIdx];

  /* ── Exceedance year ── */
  const constraintYear = scenarios?.time_to_constraint_year;

  return (
    <div className="gc-panel df-panel">
      {/* ── Header ── */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
          Demand Forecast
        </div>
        <button className="gc-close" onClick={onClose} title="Close">&times;</button>
      </div>

      {/* ── GSP Selector — ordered by distance when site is known ── */}
      <div className="df-gsp-selector">
        <select
          value={selectedGsp?.gsp_id || ""}
          onChange={e => {
            const gsp = gsps.find(g => g.gsp_id === e.target.value);
            setSelectedGsp(gsp);
            if (siteCoord) {
              // Manual override — freeze auto-pick for this coord.
              setAutoPickedFor(`${siteCoord.lat.toFixed(3)},${siteCoord.lon.toFixed(3)}`);
            }
          }}
          className="df-select"
        >
          {(siteCoord
            ? [...gsps].sort((a, b) => _haversineKm(siteCoord, a) - _haversineKm(siteCoord, b))
            : gsps
          ).map((g, idx) => {
            const km = siteCoord ? _haversineKm(siteCoord, g) : null;
            const prefix = siteCoord && idx < 5 ? `★ ` : "";
            const suffix = km != null && isFinite(km) ? ` · ${km.toFixed(0)} km` : "";
            return (
              <option key={g.gsp_id} value={g.gsp_id}>
                {prefix}{g.gsp_name} ({g.dno.toUpperCase()}) — {g.peak_demand_mw} MW peak{suffix}
              </option>
            );
          })}
        </select>
        {siteCoord && selectedGsp && (
          <div className="df-gsp-hint">
            Auto-selected nearest GSP
            <b> · {_haversineKm(siteCoord, selectedGsp).toFixed(1)} km</b> from site
            {selectedGsp.peak_demand_mw && selectedGsp.capacity_mw && (
              <> · utilisation <b>{((selectedGsp.peak_demand_mw / selectedGsp.capacity_mw) * 100).toFixed(0)}%</b></>
            )}
          </div>
        )}
      </div>

      {/* ── Tab bar ── */}
      <div className="df-tabs">
        {[
          { id: "forecast", label: "Short-term" },
          { id: "scenarios", label: "Scenarios" },
          { id: "historical", label: "Historical" },
        ].map(tab => (
          <button key={tab.id}
            className={`df-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >{tab.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">
        {error && <div className="gc-error">{error}</div>}

        {/* ════════════════════════════════════════════════════════════════════
            TAB: Short-term Forecast
           ════════════════════════════════════════════════════════════════════ */}
        {activeTab === "forecast" && (
          <>
            {loading ? (
              <div className="gc-loading">Loading forecast...</div>
            ) : forecast?.forecasts?.length ? (
              <>
                {/* Stat grid */}
                <div className="df-stat-grid">
                  <div className="df-stat">
                    <div className="df-stat-label">Horizon</div>
                    <div className="df-stat-value">{forecast.horizon_hours}h</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Model</div>
                    <div className="df-stat-value">{forecast.model}</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Points</div>
                    <div className="df-stat-value">{forecast.points}</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Capacity</div>
                    <div className="df-stat-value">{fmtMw(forecast.capacity_mw)}</div>
                  </div>
                </div>

                {/* Chart */}
                <div className="df-chart-wrap">
                  <ForecastChart
                    forecasts={forecast.forecasts}
                    capacityMw={forecast.capacity_mw}
                    sliderIdx={sliderIdx}
                  />
                </div>

                {/* Time slider */}
                <div className="df-slider-wrap">
                  <input
                    type="range"
                    min={0}
                    max={forecast.forecasts.length - 1}
                    value={sliderIdx}
                    onChange={e => setSliderIdx(Number(e.target.value))}
                    className="df-slider"
                  />
                  {sliderPoint && (
                    <div className="df-slider-readout">
                      <span className="df-slider-ts">
                        {new Date(sliderPoint.timestamp_utc).toLocaleString("en-GB", {
                          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                        })}
                      </span>
                      <span className="df-slider-vals">
                        P10: <b>{sliderPoint.p10_mw.toFixed(0)}</b> &nbsp;
                        P50: <b style={{ color: "#D4A018" }}>{sliderPoint.p50_mw.toFixed(0)}</b> &nbsp;
                        P90: <b>{sliderPoint.p90_mw.toFixed(0)}</b> MW
                      </span>
                      <Provenance
                        source="BMRS Insights API + NESO FES 2024"
                        pathway="Leading the Way"
                        fetchedAt={new Date().toISOString()}
                      />
                    </div>
                  )}
                </div>

                {/* Horizon selector */}
                <div className="df-horizon-row">
                  <span className="df-horizon-label">Forecast horizon:</span>
                  {[24, 48, 168, 336, 720].map(h => (
                    <button key={h}
                      className={`df-horizon-btn ${horizonHours === h ? "active" : ""}`}
                      onClick={() => { setHorizonHours(h); }}
                    >
                      {h <= 48 ? `${h}h` : `${Math.round(h / 24)}d`}
                    </button>
                  ))}
                </div>

                {/* Peak / utilisation summary */}
                {selectedGsp && (
                  <div className="df-peak-summary">
                    <div className="df-peak-row">
                      <span>Current peak demand</span>
                      <span className="df-peak-val">{fmtMw(selectedGsp.peak_demand_mw)}</span>
                    </div>
                    <div className="df-peak-row">
                      <span>Transformer capacity</span>
                      <span className="df-peak-val">{fmtMw(selectedGsp.capacity_mw)}</span>
                    </div>
                    <UtilBar
                      value={selectedGsp.peak_demand_mw / selectedGsp.capacity_mw}
                      label="Current utilisation"
                    />
                  </div>
                )}
              </>
            ) : (
              <div className="gc-empty">Select a GSP to view demand forecast</div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════════════════════
            TAB: Scenario Projections
           ════════════════════════════════════════════════════════════════════ */}
        {activeTab === "scenarios" && (
          <>
            {scenLoading ? (
              <div className="gc-loading">Loading scenarios...</div>
            ) : scenarios ? (
              <>
                {/* Constraint alert */}
                {constraintYear && (
                  <div className={`df-constraint-alert ${constraintYear <= 2028 ? "urgent" : "warning"}`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Capacity constraint expected by <b>{constraintYear}</b>
                    {constraintYear <= 2028 ? " — reinforcement needed" : ""}
                  </div>
                )}

                {/* Stat grid */}
                <div className="df-stat-grid">
                  <div className="df-stat">
                    <div className="df-stat-label">Current peak</div>
                    <div className="df-stat-value">{fmtMw(scenarios.current_peak_mw)}</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Capacity</div>
                    <div className="df-stat-value">{fmtMw(scenarios.capacity_mw)}</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Projection</div>
                    <div className="df-stat-value">{scenarios.years_ahead} years</div>
                  </div>
                  <div className="df-stat">
                    <div className="df-stat-label">Constraint</div>
                    <div className="df-stat-value" style={{ color: constraintYear ? "#f5222d" : "#52c41a" }}>
                      {constraintYear || "None"}
                    </div>
                  </div>
                </div>

                {/* Scenario chart */}
                <div className="df-chart-wrap">
                  <ScenarioChart
                    annual={scenarios.annual_forecasts}
                    scenarios={scenarios.scenarios}
                  />
                </div>

                {/* Scenario legend + toggles */}
                <div className="df-scenario-legend">
                  {SCENARIOS.map(s => (
                    <label key={s.id} className="df-scenario-item">
                      <span className="df-scenario-dot" style={{ background: s.color }} />
                      <span className="df-scenario-name">{s.label}</span>
                      <span className="df-scenario-desc">{s.desc}</span>
                    </label>
                  ))}
                </div>

                {/* Annual table */}
                <div className="df-annual-table">
                  <div className="df-table-header">
                    <span>Year</span><span>P10</span><span>P50</span><span>P90</span>
                    <span>Util.</span><span>Exceed</span>
                  </div>
                  {scenarios.annual_forecasts?.map(a => (
                    <div key={a.year} className={`df-table-row ${a.exceedance_probability > 0.1 ? "df-row-warn" : ""}`}>
                      <span>{a.year}</span>
                      <span>{a.p10_mw.toFixed(0)}</span>
                      <span style={{ fontWeight: 600 }}>{a.p50_mw.toFixed(0)}</span>
                      <span>{a.p90_mw.toFixed(0)}</span>
                      <span style={{ color: a.utilisation >= 0.9 ? "#f5222d" : a.utilisation >= 0.7 ? "#fa8c16" : "#52c41a" }}>
                        {pct(a.utilisation)}
                      </span>
                      <span style={{ color: a.exceedance_probability > 0.1 ? "#f5222d" : "inherit" }}>
                        {pct(a.exceedance_probability)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="gc-empty">No scenario data</div>
            )}
          </>
        )}

        {/* ════════════════════════════════════════════════════════════════════
            TAB: Historical Demand
           ════════════════════════════════════════════════════════════════════ */}
        {activeTab === "historical" && (
          <>
            {historical?.daily_summaries?.length ? (
              <>
                <div className="df-hist-list">
                  {historical.daily_summaries.map((d, i) => {
                    const util = d.peak_mw / d.capacity_mw;
                    return (
                      <div key={i} className="df-hist-row">
                        <span className="df-hist-date">{d.date}</span>
                        <div className="df-hist-bar-wrap">
                          <div className="df-hist-bar"
                            style={{
                              width: `${(d.peak_mw / d.capacity_mw) * 100}%`,
                              background: util >= 0.9 ? "#f5222d" : util >= 0.7 ? "#fa8c16" : "rgba(15,98,254,0.5)",
                            }}
                          />
                          <div className="df-hist-min-mark" style={{ left: `${(d.min_mw / d.capacity_mw) * 100}%` }} />
                        </div>
                        <span className="df-hist-vals">
                          {d.peak_mw.toFixed(0)} / {d.mean_mw.toFixed(0)} / {d.min_mw.toFixed(0)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="df-hist-legend">
                  Peak / Mean / Min (MW) — bar shows peak as % of capacity
                </div>
              </>
            ) : (
              <div className="gc-empty">No historical data for this GSP</div>
            )}
          </>
        )}
      </div>

      {/* ── Footer ── */}
      <div className="df-footer">
        <span>NESO FES 2024 scenarios</span>
        <span>{selectedGsp?.dno?.toUpperCase() || ""} — {selectedGsp?.region || ""}</span>
      </div>
    </div>
  );
}
