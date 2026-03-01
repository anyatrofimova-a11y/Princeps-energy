import React, { useState, useCallback } from "react";
import api from "../services/api";

const TABS = [
  { id: "constraints", label: "Constraints" },
  { id: "dispatch", label: "Dispatch" },
  { id: "bm", label: "Balancing" },
  { id: "revenue", label: "Revenue" },
];

const REGIONS = ["Scotland", "North", "Midlands", "South"];
const TECHNOLOGIES = ["wind", "solar", "bess"];
const CONN_TYPES = ["firm", "anm", "non_firm", "timed"];
const BOUNDARIES = ["B1", "B2", "B4", "B6", "B7", "B8", "B9"];

function fmt(v) { return v == null ? "—" : typeof v === "number" ? v.toLocaleString() : String(v); }
function pct(v) { return v == null ? "—" : `${v}%`; }

/* ── SVG Mini-Charts ─────────────────────────────────────────────────── */

function ConstraintHeatmap({ boundaries }) {
  if (!boundaries) return null;
  const bIds = Object.keys(boundaries);
  const cellW = 18, cellH = 14, labelW = 100;
  const maxHours = Math.max(...bIds.map(b => boundaries[b].hourly?.length || 0), 24);
  const w = labelW + maxHours * cellW + 10;
  const h = bIds.length * (cellH + 2) + 20;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-heatmap" style={{ width: "100%", height: Math.min(h, 160) }}>
      {bIds.map((bId, row) => {
        const bf = boundaries[bId];
        const hourly = bf.hourly || [];
        return (
          <g key={bId}>
            <text x={labelW - 4} y={row * (cellH + 2) + cellH - 1} textAnchor="end" fontSize="8" fill="#94a3b8">{bf.name}</text>
            {hourly.slice(0, 24).map((hr, col) => {
              const p = hr.constraint_probability || 0;
              const fill = p > 0.6 ? "#ef4444" : p > 0.3 ? "#f59e0b" : "#22c55e";
              return (
                <rect key={col} x={labelW + col * cellW} y={row * (cellH + 2)} width={cellW - 1} height={cellH}
                  fill={fill} opacity={0.3 + p * 0.7} rx={1}>
                  <title>{bf.name} h{hr.hour}: {(p * 100).toFixed(0)}%</title>
                </rect>
              );
            })}
          </g>
        );
      })}
      {/* Hour labels */}
      {Array.from({ length: Math.min(maxHours, 24) }, (_, i) => (
        <text key={i} x={labelW + i * cellW + cellW / 2} y={h - 2} textAnchor="middle" fontSize="7" fill="#64748b">{i}</text>
      ))}
    </svg>
  );
}

function DispatchChart({ schedule }) {
  if (!schedule?.length) return null;
  const w = 460, h = 120, pad = 30;
  const maxMw = Math.max(...schedule.map(s => Math.max(s.generated_mw || 0, s.exported_mw || 0)), 1);
  const barW = (w - pad * 2) / schedule.length;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-chart" style={{ width: "100%", height: 120 }}>
      {schedule.map((s, i) => {
        const genH = (s.generated_mw / maxMw) * (h - pad - 10);
        const expH = (s.exported_mw / maxMw) * (h - pad - 10);
        const x = pad + i * barW;
        return (
          <g key={i}>
            <rect x={x} y={h - pad - genH} width={barW - 1} height={genH} fill="#3b82f6" opacity={0.3}>
              <title>h{s.hour} gen: {s.generated_mw?.toFixed(1)} MW</title>
            </rect>
            <rect x={x} y={h - pad - expH} width={barW - 1} height={expH} fill="#22c55e" opacity={0.7}>
              <title>h{s.hour} export: {s.exported_mw?.toFixed(1)} MW</title>
            </rect>
            {s.is_constrained && (
              <circle cx={x + barW / 2} cy={5} r={2} fill="#ef4444">
                <title>Constrained</title>
              </circle>
            )}
          </g>
        );
      })}
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
      {[0, 6, 12, 18].map(hr => (
        <text key={hr} x={pad + hr * barW + barW / 2} y={h - pad + 10} textAnchor="middle" fontSize="8" fill="#64748b">{hr}:00</text>
      ))}
      <circle cx={pad + 10} cy={h - 5} r={3} fill="#3b82f6" opacity={0.3} />
      <text x={pad + 18} y={h - 2} fontSize="7" fill="#94a3b8">Generated</text>
      <circle cx={pad + 75} cy={h - 5} r={3} fill="#22c55e" opacity={0.7} />
      <text x={pad + 83} y={h - 2} fontSize="7" fill="#94a3b8">Exported</text>
    </svg>
  );
}

function BessChart({ schedule }) {
  if (!schedule?.length) return null;
  const w = 460, h = 130, pad = 30;
  const maxSoc = Math.max(...schedule.map(s => s.soc_mwh || 0), 1);

  const points = schedule.map((s, i) => {
    const x = pad + (i / (schedule.length - 1)) * (w - pad * 2);
    const y = h - pad - (s.soc_mwh / maxSoc) * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  const actionColors = { CHARGE: "#3b82f6", DISCHARGE: "#f59e0b", FFR: "#a855f7", IDLE: "#475569" };

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-chart" style={{ width: "100%", height: 130 }}>
      <polyline points={points} fill="none" stroke="#22c55e" strokeWidth={1.5} />
      {schedule.map((s, i) => {
        const x = pad + (i / (schedule.length - 1)) * (w - pad * 2);
        return (
          <rect key={i} x={x - 6} y={h - pad + 2} width={12} height={6} fill={actionColors[s.action] || "#475569"} rx={1}>
            <title>h{s.hour}: {s.action} {s.power_mw?.toFixed(1)}MW</title>
          </rect>
        );
      })}
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
      <text x={5} y={15} fontSize="7" fill="#94a3b8">SoC (MWh)</text>
      {Object.entries(actionColors).map(([k, c], i) => (
        <g key={k}>
          <rect x={pad + i * 70} y={h - 8} width={8} height={6} fill={c} rx={1} />
          <text x={pad + i * 70 + 12} y={h - 3} fontSize="7" fill="#94a3b8">{k}</text>
        </g>
      ))}
    </svg>
  );
}

function SystemPriceChart({ hourly }) {
  if (!hourly?.length) return null;
  const w = 460, h = 110, pad = 30;
  const maxP = Math.max(...hourly.map(h => Math.max(h.sbp_gbp_mwh || 0, h.ssp_gbp_mwh || 0)), 1);

  const sbpPts = hourly.map((hr, i) => {
    const x = pad + (i / (hourly.length - 1)) * (w - pad * 2);
    const y = h - pad - (hr.sbp_gbp_mwh / maxP) * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  const sspPts = hourly.map((hr, i) => {
    const x = pad + (i / (hourly.length - 1)) * (w - pad * 2);
    const y = h - pad - (hr.ssp_gbp_mwh / maxP) * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-chart" style={{ width: "100%", height: 110 }}>
      <polyline points={sbpPts} fill="none" stroke="#ef4444" strokeWidth={1.5} />
      <polyline points={sspPts} fill="none" stroke="#22c55e" strokeWidth={1.5} />
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
      <circle cx={pad + 10} cy={h - 5} r={3} fill="#ef4444" />
      <text x={pad + 18} y={h - 2} fontSize="7" fill="#94a3b8">SBP</text>
      <circle cx={pad + 55} cy={h - 5} r={3} fill="#22c55e" />
      <text x={pad + 63} y={h - 2} fontSize="7" fill="#94a3b8">SSP</text>
    </svg>
  );
}

function RevenueStackChart({ shares }) {
  if (!shares) return null;
  const items = [
    { key: "energy_pct", label: "Energy", color: "#3b82f6" },
    { key: "capacity_market_pct", label: "CM", color: "#f59e0b" },
    { key: "frequency_response_pct", label: "FR", color: "#a855f7" },
    { key: "bm_pct", label: "BM", color: "#ef4444" },
    { key: "embedded_pct", label: "Embedded", color: "#22c55e" },
    { key: "triad_pct", label: "Triad", color: "#06b6d4" },
  ].filter(it => (shares[it.key] || 0) > 0.5);

  const w = 460, h = 50, pad = 10;
  let cumX = pad;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-chart" style={{ width: "100%", height: 50 }}>
      {items.map(it => {
        const pctVal = shares[it.key] || 0;
        const barW = ((w - pad * 2) * pctVal) / 100;
        const x = cumX;
        cumX += barW;
        return (
          <g key={it.key}>
            <rect x={x} y={5} width={barW} height={20} fill={it.color} rx={2}>
              <title>{it.label}: {pctVal}%</title>
            </rect>
            {barW > 30 && (
              <text x={x + barW / 2} y={19} textAnchor="middle" fontSize="7" fill="#fff">{it.label} {pctVal}%</text>
            )}
          </g>
        );
      })}
      {/* Legend */}
      {items.map((it, i) => (
        <g key={it.key}>
          <rect x={pad + i * 65} y={h - 12} width={8} height={6} fill={it.color} rx={1} />
          <text x={pad + i * 65 + 12} y={h - 7} fontSize="7" fill="#94a3b8">{it.label}</text>
        </g>
      ))}
    </svg>
  );
}

function MonthlyRevenueChart({ monthly }) {
  if (!monthly?.length) return null;
  const w = 460, h = 120, pad = 30;
  const maxRev = Math.max(...monthly.map(m => m.total_gbp || 0), 1);
  const barW = (w - pad * 2) / 12;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dp-chart" style={{ width: "100%", height: 120 }}>
      {monthly.map((m, i) => {
        const bH = (m.total_gbp / maxRev) * (h - pad - 10);
        return (
          <g key={i}>
            <rect x={pad + i * barW} y={h - pad - bH} width={barW - 2} height={bH} fill="#3b82f6" rx={1}>
              <title>{m.month_name}: {fmt(m.total_gbp)}</title>
            </rect>
            <text x={pad + i * barW + barW / 2} y={h - pad + 10} textAnchor="middle" fontSize="7" fill="#64748b">{m.month_name}</text>
          </g>
        );
      })}
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
    </svg>
  );
}


/* ── Main Panel ─────────────────────────────────────────────────────── */

export default function DispatchPanel({ onClose }) {
  const [tab, setTab] = useState("constraints");
  const [loading, setLoading] = useState(false);

  // Shared controls
  const [capacityMw, setCapacityMw] = useState(50);
  const [region, setRegion] = useState("Scotland");
  const [technology, setTechnology] = useState("wind");
  const [connType, setConnType] = useState("anm");
  const [headroomMw, setHeadroomMw] = useState(30);

  // Tab data
  const [constraintData, setConstraintData] = useState(null);
  const [dispatchData, setDispatchData] = useState(null);
  const [bessData, setBessData] = useState(null);
  const [bmData, setBmData] = useState(null);
  const [boaData, setBoaData] = useState(null);
  const [priceData, setPriceData] = useState(null);
  const [revenueData, setRevenueData] = useState(null);
  const [monthlyData, setMonthlyData] = useState(null);
  const [scenarioData, setScenarioData] = useState(null);

  const run = useCallback(async (fn) => {
    setLoading(true);
    try { await fn(); } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  /* ── Tab: Constraints ── */
  const loadConstraints = () => run(async () => {
    const d = await api.dispatch.constraintForecast(48);
    setConstraintData(d);
  });

  /* ── Tab: Dispatch ── */
  const loadDispatch = () => run(async () => {
    if (technology === "bess") {
      const d = await api.dispatch.bessSchedule(capacityMw / 2, capacityMw, 50, region, 24, 1);
      setBessData(d);
      setDispatchData(null);
    } else {
      const d = await api.dispatch.schedule(capacityMw, technology, region, connType, headroomMw, 24, 1);
      setDispatchData(d);
      setBessData(null);
    }
  });

  /* ── Tab: Balancing ── */
  const loadBm = () => run(async () => {
    const [bm, boa, prices] = await Promise.all([
      api.dispatch.bmRevenue(capacityMw, technology, region),
      api.dispatch.bmBoaProfile(capacityMw, region, technology, 24, 1),
      api.dispatch.bmSystemPrices("2025-01-15"),
    ]);
    setBmData(bm);
    setBoaData(boa);
    setPriceData(prices);
  });

  /* ── Tab: Revenue ── */
  const loadRevenue = () => run(async () => {
    const [stack, monthly, scenarios] = await Promise.all([
      api.dispatch.revenueStack(capacityMw, technology, region, connType, headroomMw),
      api.dispatch.revenueMonthly(capacityMw, technology, region, connType, headroomMw),
      api.dispatch.revenueScenarios(capacityMw, technology, region),
    ]);
    setRevenueData(stack);
    setMonthlyData(monthly);
    setScenarioData(scenarios);
  });

  const handleRun = () => {
    if (tab === "constraints") loadConstraints();
    else if (tab === "dispatch") loadDispatch();
    else if (tab === "bm") loadBm();
    else if (tab === "revenue") loadRevenue();
  };

  return (
    <div className="gc-panel dp-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <span className="gc-panel-title">Dispatch Optimisation</span>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Tabs */}
      <div className="dp-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`dp-tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Shared controls */}
      {tab !== "constraints" && (
        <div className="dp-controls">
          <label>Capacity<input type="number" value={capacityMw} onChange={e => setCapacityMw(+e.target.value)} min={1} max={500} /></label>
          <label>Region<select value={region} onChange={e => setRegion(e.target.value)}>
            {REGIONS.map(r => <option key={r}>{r}</option>)}
          </select></label>
          <label>Tech<select value={technology} onChange={e => setTechnology(e.target.value)}>
            {TECHNOLOGIES.map(t => <option key={t}>{t}</option>)}
          </select></label>
          {tab !== "bm" && (
            <>
              <label>Conn<select value={connType} onChange={e => setConnType(e.target.value)}>
                {CONN_TYPES.map(c => <option key={c}>{c}</option>)}
              </select></label>
              <label>Headroom<input type="number" value={headroomMw} onChange={e => setHeadroomMw(+e.target.value)} min={1} max={500} /></label>
            </>
          )}
        </div>
      )}

      <button className="dp-run-btn" onClick={handleRun} disabled={loading}>
        {loading ? "Loading..." : "Run Analysis"}
      </button>

      <div className="dp-body">
        {/* ═══ CONSTRAINTS TAB ═══ */}
        {tab === "constraints" && constraintData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">System Risk</span>
                <span className={`dp-risk-pill dp-risk-${constraintData.summary?.system_risk?.toLowerCase()}`}>
                  {constraintData.summary?.system_risk}
                </span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Max Prob</span>
                <span className="dp-stat-value">{pct((constraintData.summary?.max_system_constraint_prob * 100)?.toFixed(0))}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">At-Risk Boundaries</span>
                <span className="dp-stat-value">{constraintData.summary?.boundaries_at_risk}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Constrained Hrs</span>
                <span className="dp-stat-value">{constraintData.summary?.total_constrained_boundary_hours}</span>
              </div>
            </div>

            <h4 className="dp-section-title">Boundary Heatmap (24h)</h4>
            <ConstraintHeatmap boundaries={constraintData.boundaries} />

            {constraintData.constraint_windows?.length > 0 && (
              <>
                <h4 className="dp-section-title">Constraint Windows</h4>
                <div className="dp-table-wrap">
                  <table className="dp-table">
                    <thead><tr><th>Boundary</th><th>Start</th><th>End</th><th>Peak</th><th>Hrs</th></tr></thead>
                    <tbody>
                      {constraintData.constraint_windows.slice(0, 8).map((cw, i) => (
                        <tr key={i}>
                          <td>{cw.boundary_name}</td>
                          <td>{cw.start?.split(" ")[1]}</td>
                          <td>{cw.end?.split(" ")[1]}</td>
                          <td><span className={`dp-risk-pill dp-risk-${cw.peak_prob > 0.6 ? "high" : "medium"}`}>{(cw.peak_prob * 100).toFixed(0)}%</span></td>
                          <td>{cw.duration_hours}h</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}

        {/* ═══ DISPATCH TAB ═══ */}
        {tab === "dispatch" && dispatchData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Generated</span>
                <span className="dp-stat-value">{fmt(dispatchData.summary?.total_generated_mwh)} MWh</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Exported</span>
                <span className="dp-stat-value">{fmt(dispatchData.summary?.total_exported_mwh)} MWh</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Curtailed</span>
                <span className="dp-stat-value">{pct(dispatchData.summary?.curtailment_pct)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Revenue</span>
                <span className="dp-stat-value">{fmt(dispatchData.summary?.total_revenue_gbp)}</span>
              </div>
            </div>
            <h4 className="dp-section-title">Hourly Dispatch</h4>
            <DispatchChart schedule={dispatchData.schedule} />
          </>
        )}

        {tab === "dispatch" && bessData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Daily Revenue</span>
                <span className="dp-stat-value">{fmt(bessData.summary?.total_daily_revenue_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Annual Est.</span>
                <span className="dp-stat-value">{fmt(bessData.summary?.estimated_annual_revenue_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Cycles/Day</span>
                <span className="dp-stat-value">{bessData.summary?.cycles_per_day}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">FFR Revenue</span>
                <span className="dp-stat-value">{fmt(bessData.summary?.ffr_revenue_gbp)}</span>
              </div>
            </div>
            <h4 className="dp-section-title">BESS Schedule</h4>
            <BessChart schedule={bessData.schedule} />
          </>
        )}

        {/* ═══ BALANCING TAB ═══ */}
        {tab === "bm" && bmData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Total BM Revenue</span>
                <span className="dp-stat-value">{fmt(bmData.annual_estimates?.total_bm_revenue_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Rev/MW</span>
                <span className="dp-stat-value">{fmt(bmData.annual_estimates?.revenue_per_mw_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Constraint</span>
                <span className={`dp-risk-pill dp-risk-${bmData.market_context?.region_constraint_intensity?.toLowerCase()}`}>
                  {bmData.market_context?.region_constraint_intensity}
                </span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Bid Hours</span>
                <span className="dp-stat-value">{fmt(bmData.annual_estimates?.bid_acceptance_hours)}</span>
              </div>
            </div>

            <div className="dp-breakdown">
              <div className="dp-breakdown-row">
                <span>Bid Revenue</span><span>{fmt(bmData.annual_estimates?.bid_revenue_gbp)}</span>
              </div>
              <div className="dp-breakdown-row">
                <span>Offer Revenue</span><span>{fmt(bmData.annual_estimates?.offer_revenue_gbp)}</span>
              </div>
              <div className="dp-breakdown-row">
                <span>Spread Revenue</span><span>{fmt(bmData.annual_estimates?.spread_revenue_gbp)}</span>
              </div>
              <div className="dp-breakdown-row">
                <span>Constraint Price (mean)</span><span>{bmData.constraint_prices?.mean_gbp_mwh} /MWh</span>
              </div>
            </div>

            {priceData && (
              <>
                <h4 className="dp-section-title">System Prices (SBP / SSP)</h4>
                <SystemPriceChart hourly={priceData.hourly} />
                <div className="dp-stat-row" style={{ marginTop: 6 }}>
                  <div className="dp-stat"><span className="dp-stat-label">Avg SBP</span><span className="dp-stat-value">{priceData.summary?.avg_sbp}</span></div>
                  <div className="dp-stat"><span className="dp-stat-label">Avg SSP</span><span className="dp-stat-value">{priceData.summary?.avg_ssp}</span></div>
                  <div className="dp-stat"><span className="dp-stat-label">Avg Spread</span><span className="dp-stat-value">{priceData.summary?.avg_spread}</span></div>
                </div>
              </>
            )}
          </>
        )}

        {/* ═══ REVENUE TAB ═══ */}
        {tab === "revenue" && revenueData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Total Annual</span>
                <span className="dp-stat-value">{fmt(revenueData.revenue_stack?.total_annual_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Rev/MW</span>
                <span className="dp-stat-value">{fmt(revenueData.revenue_stack?.revenue_per_mw_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">25yr NPV</span>
                <span className="dp-stat-value">{fmt(revenueData.lifetime?.npv_gbp)}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Curtailment</span>
                <span className="dp-stat-value">{pct(revenueData.generation?.curtailment_pct)}</span>
              </div>
            </div>

            <h4 className="dp-section-title">Revenue Stack</h4>
            <RevenueStackChart shares={revenueData.revenue_shares} />

            <div className="dp-breakdown">
              <div className="dp-breakdown-row"><span>Wholesale + CfD</span><span>{fmt(revenueData.revenue_stack?.total_energy_gbp)}</span></div>
              <div className="dp-breakdown-row"><span>Capacity Market</span><span>{fmt(revenueData.revenue_stack?.capacity_market_gbp)}</span></div>
              <div className="dp-breakdown-row"><span>Frequency Response</span><span>{fmt(revenueData.revenue_stack?.frequency_response_gbp)}</span></div>
              <div className="dp-breakdown-row"><span>Balancing Mechanism</span><span>{fmt(revenueData.revenue_stack?.balancing_mechanism_gbp)}</span></div>
              <div className="dp-breakdown-row"><span>Embedded Benefits</span><span>{fmt(revenueData.revenue_stack?.embedded_benefits_gbp)}</span></div>
              <div className="dp-breakdown-row"><span>Triad Avoidance</span><span>{fmt(revenueData.revenue_stack?.triad_avoidance_gbp)}</span></div>
            </div>

            {monthlyData?.monthly && (
              <>
                <h4 className="dp-section-title">Monthly Revenue</h4>
                <MonthlyRevenueChart monthly={monthlyData.monthly} />
              </>
            )}

            {scenarioData?.scenarios && (
              <>
                <h4 className="dp-section-title">Scenario Comparison</h4>
                <div className="dp-table-wrap">
                  <table className="dp-table">
                    <thead><tr><th>Scenario</th><th>Annual</th><th>25yr NPV</th></tr></thead>
                    <tbody>
                      {scenarioData.scenarios.map((s, i) => (
                        <tr key={i} className={s.scenario === "base" ? "dp-row-highlight" : ""}>
                          <td>{s.label}</td>
                          <td>{fmt(s.total_annual_gbp)}</td>
                          <td>{fmt(s.npv_25yr_gbp)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}

        {/* Empty state */}
        {!loading && !constraintData && !dispatchData && !bessData && !bmData && !revenueData && (
          <div className="dp-empty">Click "Run Analysis" to load data for the selected tab.</div>
        )}
      </div>

      <div className="dp-footer">
        Phase 9 — Constraint Forecasting & Dispatch Optimisation
      </div>
    </div>
  );
}
