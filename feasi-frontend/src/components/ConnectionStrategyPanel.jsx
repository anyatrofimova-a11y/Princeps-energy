import React, { useState, useEffect, useCallback } from "react";
import api from "../services/api";

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (Math.abs(v) >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
}
function pct(v) { return v != null ? `${v.toFixed(1)}%` : "--"; }

const TABS = [
  { id: "strategy", label: "Strategy" },
  { id: "curtailment", label: "Curtailment" },
  { id: "flexible", label: "Flexible" },
  { id: "timeline", label: "Timeline" },
];

const REGIONS = ["Scotland", "North", "Wales", "Midlands", "East", "South", "London"];
const TECHNOLOGIES = ["solar", "wind"];
const CONN_TYPES = ["firm", "anm", "non_firm", "timed", "intertrip"];

/* ── Strategy comparison bars ────────────────────────────────────────────── */
function StrategyBars({ strategies, width = 560, height = 200 }) {
  if (!strategies?.length) return null;
  const pad = { l: 100, r: 60, t: 10, b: 6 };
  const w = width - pad.l - pad.r;
  const barH = Math.min(30, (height - pad.t - pad.b) / strategies.length);
  const maxScore = Math.max(1, ...strategies.map(s => s.composite_score));

  return (
    <svg width={width} height={pad.t + strategies.length * barH + pad.b} className="cs-chart">
      {strategies.map((s, i) => {
        const y = pad.t + i * barH;
        const bw = (s.composite_score / maxScore) * w;
        const col = s.composite_score > 60 ? "#52c41a" : s.composite_score > 40 ? "#fa8c16" : "#da1e28";
        return (
          <g key={s.connection_type}>
            <text x={pad.l - 6} y={y + barH / 2} textAnchor="end" fill="#ccc" fontSize="10" dy="3.5">
              {s.label}
            </text>
            <rect x={pad.l} y={y + 3} width={w} height={barH - 6} rx="3" fill="#1a1a1a" />
            <rect x={pad.l} y={y + 3} width={Math.max(0, bw)} height={barH - 6} rx="3" fill={col} opacity="0.75" />
            <text x={pad.l + Math.max(0, bw) + 4} y={y + barH / 2} fill="#ccc" fontSize="10" dy="3">
              {s.composite_score}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Monthly curtailment chart ───────────────────────────────────────────── */
function MonthlyCurtailChart({ monthly, width = 560, height = 140 }) {
  if (!monthly?.length) return null;
  const pad = { l: 42, r: 12, t: 8, b: 22 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(1, ...monthly);
  const barW = w / 12 - 4;
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

  return (
    <svg width={width} height={height} className="cs-chart">
      {monthly.map((v, i) => {
        const x = pad.l + (w / 12) * i + 2;
        const bh = (v / maxVal) * h;
        return (
          <g key={i}>
            <rect x={x} y={pad.t + h - bh} width={barW} height={bh} rx="2" fill="#fa8c16" opacity="0.7" />
            <text x={x + barW / 2} y={pad.t + h - bh - 3} textAnchor="middle" fill="#ccc" fontSize="8">{v.toFixed(1)}</text>
            <text x={x + barW / 2} y={height - 6} textAnchor="middle" fill="#999" fontSize="9">{months[i]}</text>
          </g>
        );
      })}
      <text x={4} y={pad.t + h / 2} fill="#777" fontSize="8" transform={`rotate(-90,4,${pad.t + h / 2})`} textAnchor="middle">Curtail %</text>
    </svg>
  );
}

/* ── ANM export profile ──────────────────────────────────────────────────── */
function AnmChart({ hourly, width = 560, height = 160 }) {
  if (!hourly?.length) return null;
  const pad = { l: 42, r: 12, t: 8, b: 22 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxGen = Math.max(1, ...hourly.map(h => h.generated_mw));
  const xScale = (i) => pad.l + (i / 23) * w;
  const yScale = (v) => pad.t + h - (v / maxGen) * h;

  // Generated area
  const genPath = hourly.map((h, i) => `${xScale(i)},${yScale(h.generated_mw)}`).join(" ");
  const expPath = hourly.map((h, i) => `${xScale(i)},${yScale(h.exported_mw)}`).join(" ");
  const baseLine = `${xScale(23)},${yScale(0)} ${xScale(0)},${yScale(0)}`;

  return (
    <svg width={width} height={height} className="cs-chart">
      {/* Generated area */}
      <polygon points={`${genPath} ${baseLine}`} fill="#fa8c16" opacity="0.15" />
      <polyline points={genPath} fill="none" stroke="#fa8c16" strokeWidth="1.5" />
      {/* Exported area */}
      <polygon points={`${expPath} ${baseLine}`} fill="#52c41a" opacity="0.2" />
      <polyline points={expPath} fill="none" stroke="#52c41a" strokeWidth="1.5" />
      {/* Export limit line */}
      {hourly[0] && (
        <line x1={pad.l} x2={pad.l + w} y1={yScale(hourly[0].export_limit_mw)} y2={yScale(hourly[0].export_limit_mw)}
          stroke="#da1e28" strokeDasharray="4,3" strokeWidth="1" />
      )}
      {/* X axis */}
      {[0, 6, 12, 18, 23].map(h => (
        <text key={h} x={xScale(h)} y={height - 4} textAnchor="middle" fill="#999" fontSize="9">{h}:00</text>
      ))}
    </svg>
  );
}

/* ── Timeline Gantt ──────────────────────────────────────────────────────── */
function TimelineGantt({ milestones, totalMonths, width = 560, height = 280 }) {
  if (!milestones?.length) return null;
  const pad = { l: 140, r: 16, t: 10, b: 22 };
  const w = width - pad.l - pad.r;
  const barH = Math.min(22, (height - pad.t - pad.b) / milestones.length);
  const xScale = (m) => pad.l + (m / totalMonths) * w;

  return (
    <svg width={width} height={pad.t + milestones.length * barH + pad.b + 20} className="cs-chart">
      {/* Month gridlines */}
      {Array.from({ length: Math.ceil(totalMonths) + 1 }, (_, i) => i * 6).filter(m => m <= totalMonths).map(m => (
        <g key={m}>
          <line x1={xScale(m)} x2={xScale(m)} y1={pad.t} y2={pad.t + milestones.length * barH} stroke="#333" strokeDasharray="2,3" />
          <text x={xScale(m)} y={pad.t + milestones.length * barH + 14} textAnchor="middle" fill="#777" fontSize="8">M{m}</text>
        </g>
      ))}
      {/* Bars */}
      {milestones.map((m, i) => {
        const y = pad.t + i * barH;
        const x1 = xScale(m.start_month);
        const bw = Math.max(4, xScale(m.end_month) - x1);
        return (
          <g key={m.id}>
            <text x={pad.l - 4} y={y + barH / 2} textAnchor="end" fill={m.on_critical_path ? "#fff" : "#999"} fontSize="9" dy="3" fontWeight={m.on_critical_path ? 600 : 400}>
              {m.label}
            </text>
            <rect x={x1} y={y + 3} width={bw} height={barH - 6} rx="3"
              fill={m.color || "#1890ff"}
              opacity={m.on_critical_path ? 0.85 : 0.45}
              stroke={m.on_critical_path ? "#fff" : "none"} strokeWidth="0.5"
            />
          </g>
        );
      })}
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function ConnectionStrategyPanel({ onClose }) {
  const [tab, setTab] = useState("strategy");

  // ── Common params ──
  const [capacityMw, setCapacityMw] = useState(50);
  const [region, setRegion] = useState("Midlands");
  const [technology, setTechnology] = useState("solar");
  const [headroomMw, setHeadroomMw] = useState(30);
  const [voltageKv, setVoltageKv] = useState(132);

  // ── Strategy state ──
  const [strategyData, setStrategyData] = useState(null);
  const [stratLoading, setStratLoading] = useState(false);

  // ── Curtailment state ──
  const [curtailData, setCurtailData] = useState(null);
  const [connType, setConnType] = useState("firm");
  const [curtailLoading, setCurtailLoading] = useState(false);

  // ── Flexible state ──
  const [flexData, setFlexData] = useState(null);
  const [anmData, setAnmData] = useState(null);
  const [flexLoading, setFlexLoading] = useState(false);

  // ── Timeline state ──
  const [timelineData, setTimelineData] = useState(null);
  const [tlConnType, setTlConnType] = useState("firm");
  const [tlLoading, setTlLoading] = useState(false);

  // ── Strategy fetch ──
  const fetchStrategy = useCallback(async () => {
    setStratLoading(true);
    try {
      const data = await api.connectionStrategy.compare(capacityMw, region, headroomMw, technology);
      if (data) setStrategyData(data);
    } catch (e) { console.error(e); }
    setStratLoading(false);
  }, [capacityMw, region, headroomMw, technology]);

  useEffect(() => { if (tab === "strategy") fetchStrategy(); }, [tab]); // eslint-disable-line

  // ── Curtailment fetch ──
  const fetchCurtailment = useCallback(async () => {
    setCurtailLoading(true);
    try {
      const data = await api.connectionStrategy.curtailmentEstimate(capacityMw, region, technology, connType);
      if (data) setCurtailData(data);
    } catch (e) { console.error(e); }
    setCurtailLoading(false);
  }, [capacityMw, region, technology, connType]);

  useEffect(() => { if (tab === "curtailment") fetchCurtailment(); }, [tab]); // eslint-disable-line

  // ── Flexible fetch ──
  const fetchFlexible = useCallback(async () => {
    setFlexLoading(true);
    try {
      const [flex, anm] = await Promise.all([
        api.connectionStrategy.flexibleCompare(capacityMw, headroomMw, region, technology, voltageKv),
        api.connectionStrategy.anmProfile(capacityMw, headroomMw, technology),
      ]);
      if (flex) setFlexData(flex);
      if (anm) setAnmData(anm);
    } catch (e) { console.error(e); }
    setFlexLoading(false);
  }, [capacityMw, headroomMw, region, technology, voltageKv]);

  useEffect(() => { if (tab === "flexible") fetchFlexible(); }, [tab]); // eslint-disable-line

  // ── Timeline fetch ──
  const fetchTimeline = useCallback(async () => {
    setTlLoading(true);
    try {
      const data = await api.connectionStrategy.timelineGenerate(capacityMw, voltageKv, tlConnType, "2025-06-01");
      if (data) setTimelineData(data);
    } catch (e) { console.error(e); }
    setTlLoading(false);
  }, [capacityMw, voltageKv, tlConnType]);

  useEffect(() => { if (tab === "timeline") fetchTimeline(); }, [tab]); // eslint-disable-line

  return (
    <div className="gc-panel cs-panel">
      <div className="gc-panel-header">
        <span className="gc-panel-title">Connection Strategy</span>
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

      {/* Shared controls */}
      <div className="cs-shared-controls">
        <label>
          Capacity
          <input type="number" value={capacityMw} onChange={e => setCapacityMw(+e.target.value)} style={{ width: 52 }} /> MW
        </label>
        <label>
          Region
          <select value={region} onChange={e => setRegion(e.target.value)}>
            {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>
          Tech
          <select value={technology} onChange={e => setTechnology(e.target.value)}>
            {TECHNOLOGIES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>
          Headroom
          <input type="number" value={headroomMw} onChange={e => setHeadroomMw(+e.target.value)} style={{ width: 52 }} /> MW
        </label>
      </div>

      <div className="ag-body">
        {/* ═══ Strategy Tab ═══ */}
        {tab === "strategy" && (
          <div className="ag-section">
            <button className="ag-btn" onClick={fetchStrategy} disabled={stratLoading} style={{ alignSelf: "flex-start" }}>
              {stratLoading ? "Analysing…" : "Generate Strategy"}
            </button>

            {strategyData?.recommended && (
              <div className="cs-verdict-card">
                <div className="cs-verdict-row">
                  <span className={`cs-verdict-pill cs-verdict-${strategyData.recommended.verdict.toLowerCase().replace("-", "")}`}>
                    {strategyData.recommended.verdict}
                  </span>
                  <span className="cs-verdict-label">{strategyData.recommended.label}</span>
                  <span className="cs-verdict-score">Score: {strategyData.recommended.composite_score}</span>
                  <span className="cs-verdict-conf">Confidence: {Math.round(strategyData.recommended.confidence * 100)}%</span>
                </div>
              </div>
            )}

            {strategyData?.strategies && (
              <>
                <span className="ag-subsection-title">Strategy Ranking</span>
                <StrategyBars strategies={strategyData.strategies} />

                <div className="cs-strategy-table">
                  <div className="cs-table-header">
                    <span>Option</span><span>NPV</span><span>Curtail</span><span>Timeline</span><span>LCOE</span><span>Score</span>
                  </div>
                  {strategyData.strategies.map(s => (
                    <div key={s.connection_type} className="cs-table-row">
                      <span>{s.label}</span>
                      <span style={{ color: s.npv_25yr_gbp > 0 ? "#52c41a" : "#da1e28" }}>{fmtGbp(s.npv_25yr_gbp)}</span>
                      <span>{pct(s.curtailment_pct)}</span>
                      <span>{s.timeline_months} mo</span>
                      <span>£{s.lcoe_gbp_mwh?.toFixed(0)}/MWh</span>
                      <span style={{ color: "#40a9ff" }}>{s.composite_score}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {strategyData?.grid_context && (
              <div className="ag-stat-grid" style={{ marginTop: 8 }}>
                <div className="ag-stat">
                  <span className="ag-stat-label">Region</span>
                  <span className="ag-stat-value">{strategyData.grid_context.region}</span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">Congestion Risk</span>
                  <span className="ag-stat-value" style={{ color: strategyData.grid_context.congestion_risk > 60 ? "#da1e28" : "#fa8c16" }}>
                    {strategyData.grid_context.congestion_risk}/100
                  </span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">DLR Uplift</span>
                  <span className="ag-stat-value" style={{ color: "#52c41a" }}>{strategyData.grid_context.dlr_potential?.annual_mean}%</span>
                </div>
                <div className="ag-stat">
                  <span className="ag-stat-label">Shortfall</span>
                  <span className="ag-stat-value">{strategyData.parameters?.shortfall_mw} MW</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ═══ Curtailment Tab ═══ */}
        {tab === "curtailment" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Connection
                <select value={connType} onChange={e => setConnType(e.target.value)}>
                  {CONN_TYPES.map(c => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
                </select>
              </label>
              <button className="ag-btn" onClick={fetchCurtailment} disabled={curtailLoading}>
                {curtailLoading ? "…" : "Estimate"}
              </button>
            </div>

            {curtailData && (
              <>
                <div className="ag-stat-grid">
                  <div className="ag-stat">
                    <span className="ag-stat-label">Curtailment P50</span>
                    <span className="ag-stat-value" style={{ color: "#fa8c16" }}>{pct(curtailData.curtailment_rate_pct?.p50)}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">MWh Lost P50</span>
                    <span className="ag-stat-value">{curtailData.curtailment_mwh?.p50?.toLocaleString()}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Hours Curtailed</span>
                    <span className="ag-stat-value">{curtailData.curtailment_hours?.p50?.toFixed(0)}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">Availability P50</span>
                    <span className="ag-stat-value" style={{ color: "#52c41a" }}>{pct((curtailData.availability?.p50 || 0) * 100)}</span>
                  </div>
                </div>

                <div className="cs-p-range">
                  <div className="cs-p-item"><span className="cs-p-label">P10</span><span>{pct(curtailData.curtailment_rate_pct?.p10)}</span></div>
                  <div className="cs-p-item cs-p-mid"><span className="cs-p-label">P50</span><span>{pct(curtailData.curtailment_rate_pct?.p50)}</span></div>
                  <div className="cs-p-item"><span className="cs-p-label">P90</span><span>{pct(curtailData.curtailment_rate_pct?.p90)}</span></div>
                </div>

                <span className="ag-subsection-title">Monthly Curtailment Profile</span>
                <MonthlyCurtailChart monthly={curtailData.monthly_curtailment_pct} />

                <div className="cs-meta-row">
                  <span>Potential: {curtailData.potential_generation_mwh?.toLocaleString()} MWh/yr</span>
                  <span>CF: {pct((curtailData.parameters?.capacity_factor || 0) * 100)}</span>
                  <span>Boundary: {curtailData.boundary}</span>
                </div>
              </>
            )}
          </div>
        )}

        {/* ═══ Flexible Tab ═══ */}
        {tab === "flexible" && (
          <div className="ag-section">
            <button className="ag-btn" onClick={fetchFlexible} disabled={flexLoading} style={{ alignSelf: "flex-start" }}>
              {flexLoading ? "Comparing…" : "Compare Options"}
            </button>

            {flexData?.options && (
              <>
                <span className="ag-subsection-title">Connection Options Comparison</span>
                <div className="cs-flex-table">
                  <div className="cs-flex-header">
                    <span>Option</span><span>Curtail</span><span>Conn Cost</span><span>NPV (25yr)</span><span>Payback</span>
                  </div>
                  {flexData.options.map(o => (
                    <div key={o.id} className={`cs-flex-row${o.id === flexData.recommended ? " cs-recommended" : ""}`}>
                      <span>{o.label}{o.id === flexData.recommended && <span className="cs-rec-badge">REC</span>}</span>
                      <span>{pct(o.curtailment_pct)}</span>
                      <span>{fmtGbp(o.connection_cost_gbp)}</span>
                      <span style={{ color: o.npv_25yr_gbp > 0 ? "#52c41a" : "#da1e28" }}>{fmtGbp(o.npv_25yr_gbp)}</span>
                      <span>{o.payback_years} yr</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {anmData?.hourly && (
              <>
                <span className="ag-subsection-title">ANM Export Profile (Typical Day)</span>
                <div className="cs-anm-legend">
                  <span><span className="cs-legend-line" style={{ background: "#fa8c16" }} /> Generated</span>
                  <span><span className="cs-legend-line" style={{ background: "#52c41a" }} /> Exported</span>
                  <span><span className="cs-legend-line cs-legend-dash" style={{ background: "#da1e28" }} /> Limit</span>
                </div>
                <AnmChart hourly={anmData.hourly} />
                {anmData.daily_summary && (
                  <div className="ag-stat-grid" style={{ marginTop: 6 }}>
                    <div className="ag-stat"><span className="ag-stat-label">Generated</span><span className="ag-stat-value">{anmData.daily_summary.total_generated_mwh} MWh</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Exported</span><span className="ag-stat-value" style={{ color: "#52c41a" }}>{anmData.daily_summary.total_exported_mwh} MWh</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Curtailed</span><span className="ag-stat-value" style={{ color: "#fa8c16" }}>{anmData.daily_summary.total_curtailed_mwh} MWh</span></div>
                    <div className="ag-stat"><span className="ag-stat-label">Lost Revenue</span><span className="ag-stat-value" style={{ color: "#da1e28" }}>{fmtGbp(anmData.daily_summary.total_lost_revenue_gbp)}</span></div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ═══ Timeline Tab ═══ */}
        {tab === "timeline" && (
          <div className="ag-section">
            <div className="ag-controls">
              <label>
                Connection Type
                <select value={tlConnType} onChange={e => setTlConnType(e.target.value)}>
                  {["firm", "anm", "non_firm"].map(c => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
                </select>
              </label>
              <button className="ag-btn" onClick={fetchTimeline} disabled={tlLoading}>
                {tlLoading ? "…" : "Generate"}
              </button>
            </div>

            {timelineData && (
              <>
                <div className="ag-stat-grid">
                  <div className="ag-stat">
                    <span className="ag-stat-label">P50 Duration</span>
                    <span className="ag-stat-value" style={{ color: "#1890ff" }}>{timelineData.total_months_p50} mo</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">P90 Duration</span>
                    <span className="ag-stat-value" style={{ color: "#fa8c16" }}>{timelineData.total_months_p90} mo</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">P50 Completion</span>
                    <span className="ag-stat-value">{timelineData.completion_date_p50}</span>
                  </div>
                  <div className="ag-stat">
                    <span className="ag-stat-label">P90 Completion</span>
                    <span className="ag-stat-value">{timelineData.completion_date_p90}</span>
                  </div>
                </div>

                <span className="ag-subsection-title">Gantt Timeline</span>
                <TimelineGantt milestones={timelineData.milestones} totalMonths={timelineData.total_months_p50} />

                <div className="cs-critical-path">
                  <span className="ag-subsection-title">Critical Path</span>
                  <div className="cs-path-chain">
                    {timelineData.critical_path?.map((m, i) => (
                      <React.Fragment key={m}>
                        {i > 0 && <span className="cs-path-arrow">→</span>}
                        <span className="cs-path-node">{m.replace(/_/g, " ")}</span>
                      </React.Fragment>
                    ))}
                  </div>
                </div>

                {timelineData.risks?.length > 0 && (
                  <>
                    <span className="ag-subsection-title">Key Risks</span>
                    <div className="cs-risk-list">
                      {timelineData.risks.slice(0, 5).map((r, i) => (
                        <div key={i} className="cs-risk-item">
                          <span className={`cs-risk-prob${r.probability >= 0.4 ? " high" : ""}`}>{Math.round(r.probability * 100)}%</span>
                          <span className="cs-risk-text">{r.risk}</span>
                          <span className="cs-risk-delay">+{r.delay_months} mo</span>
                          {r.on_critical_path && <span className="cs-risk-crit">CP</span>}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="ag-footer">
        <span className="ag-footer-text">NESO Connections Reform · G99/CUSC · UK wholesale 2024</span>
      </div>
    </div>
  );
}
