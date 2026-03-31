import React, { useState, useCallback, useEffect, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Chemistry data ─────────────────────────────────────────────────────── */
const CHEMISTRIES = [
  { id: "lfp",  label: "LFP",  efficiency: 0.92, cycles: 6000, degradation: 1.8, capex: 185 },
  { id: "nmc",  label: "NMC",  efficiency: 0.89, cycles: 4000, degradation: 2.5, capex: 165 },
  { id: "nca",  label: "NCA",  efficiency: 0.88, cycles: 3500, degradation: 2.8, capex: 155 },
];

const DURATION_PRESETS = [1, 2, 4];

const REVENUE_STREAMS = [
  { id: "day_ahead",   label: "Day-ahead Arbitrage",   color: "#F5B731" },
  { id: "intraday",    label: "Intraday Trading",      color: "#E8A012" },
  { id: "balancing",   label: "Balancing Mechanism",    color: "#3b82f6" },
  { id: "ffr",         label: "FFR",                    color: "#6366f1" },
  { id: "dc",          label: "Dynamic Containment",    color: "#8b5cf6" },
  { id: "capacity",    label: "Capacity Market",        color: "#16A34A" },
  { id: "triad",       label: "Triad Avoidance",        color: "#14b8a6" },
];

const CAPEX_ITEMS = [
  { id: "batteries",    label: "Battery Modules",    share: 0.50 },
  { id: "bos",          label: "Balance of System",  share: 0.15 },
  { id: "epc",          label: "EPC & Installation", share: 0.18 },
  { id: "grid",         label: "Grid Connection",    share: 0.12 },
  { id: "development",  label: "Development",        share: 0.05 },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1_000_000) return `\u00A3${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `\u00A3${(v / 1000).toFixed(0)}k`;
  return `\u00A3${v.toFixed(0)}`;
}
function fmtNum(v, dp = 0) { return v != null ? v.toFixed(dp) : "--"; }

/* ── Revenue Bar Chart (SVG) ────────────────────────────────────────────── */
function RevenueBarChart({ streams, width = 380, height = 200 }) {
  if (!streams || streams.length === 0) return null;

  const pad = { l: 90, r: 16, t: 10, b: 8 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...streams.map(s => s.value || 0), 1);
  const barH = Math.min(20, (h - streams.length * 4) / streams.length);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {streams.map((s, i) => {
        const y = pad.t + i * (barH + 6);
        const barW = ((s.value || 0) / maxVal) * w;
        return (
          <g key={s.id || i}>
            <text x={pad.l - 6} y={y + barH / 2 + 4} textAnchor="end" fill="var(--cds-text-secondary)" fontSize="9" fontFamily="DM Sans, sans-serif">
              {s.label}
            </text>
            <rect x={pad.l} y={y} width={Math.max(2, barW)} height={barH} rx={3}
              fill={s.color || "#F5B731"} opacity={0.85} />
            <text x={pad.l + barW + 6} y={y + barH / 2 + 4} fill="var(--cds-text-primary)" fontSize="10"
              fontFamily="JetBrains Mono, monospace" fontWeight="600">
              {fmtGbp(s.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Dispatch Profile Chart (SVG) ───────────────────────────────────────── */
function DispatchChart({ schedule, width = 380, height = 180 }) {
  if (!schedule?.length) return null;

  const pad = { l: 40, r: 16, t: 10, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const midY = pad.t + h / 2;
  const maxAbs = Math.max(...schedule.map(s => Math.abs(s.power_mw || s.mw || 0)), 1);
  const barW = w / schedule.length * 0.8;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {/* Zero line */}
      <line x1={pad.l} y1={midY} x2={width - pad.r} y2={midY} stroke="rgba(0,0,0,0.1)" strokeWidth={1} />
      {/* Bars */}
      {schedule.map((s, i) => {
        const val = s.power_mw || s.mw || 0;
        const barH = (Math.abs(val) / maxAbs) * (h / 2);
        const x = pad.l + (i / schedule.length) * w;
        const isCharge = val < 0;
        return (
          <g key={i}>
            <rect
              x={x} y={isCharge ? midY : midY - barH}
              width={barW} height={barH}
              rx={2}
              fill={isCharge ? "#DC2626" : "#16A34A"}
              opacity={0.75}
            />
            {i % 4 === 0 && (
              <text x={x + barW / 2} y={height - 4} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">
                {s.hour != null ? `${s.hour}:00` : i}
              </text>
            )}
          </g>
        );
      })}
      {/* Y labels */}
      <text x={pad.l - 4} y={pad.t + 8} textAnchor="end" fill="var(--cds-text-helper)" fontSize="8">{maxAbs.toFixed(0)}</text>
      <text x={pad.l - 4} y={midY + 4} textAnchor="end" fill="var(--cds-text-helper)" fontSize="8">0</text>
      <text x={pad.l - 4} y={height - pad.b - 2} textAnchor="end" fill="var(--cds-text-helper)" fontSize="8">-{maxAbs.toFixed(0)}</text>
      {/* Legend */}
      <rect x={width - pad.r - 80} y={pad.t} width={8} height={8} rx={2} fill="#16A34A" />
      <text x={width - pad.r - 68} y={pad.t + 8} fill="var(--cds-text-helper)" fontSize="8">Discharge</text>
      <rect x={width - pad.r - 80} y={pad.t + 14} width={8} height={8} rx={2} fill="#DC2626" />
      <text x={width - pad.r - 68} y={pad.t + 22} fill="var(--cds-text-helper)" fontSize="8">Charge</text>
    </svg>
  );
}

/* ── Monthly Revenue Heatmap (SVG) ──────────────────────────────────────── */
function RevenueHeatmap({ data, width = 380, height = 200 }) {
  // data: array of { month, hour, revenue }
  if (!data?.length) return null;

  const pad = { l: 30, r: 10, t: 20, b: 20 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const cellW = w / 12;
  const cellH = h / 24;
  const maxRev = Math.max(...data.map(d => d.revenue || 0), 1);
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {data.map((d, i) => {
        const intensity = (d.revenue || 0) / maxRev;
        const r = Math.round(245 * (1 - intensity) + 212 * intensity);
        const g = Math.round(245 * (1 - intensity) + 160 * intensity);
        const b = Math.round(245 * (1 - intensity) + 24 * intensity);
        return (
          <rect
            key={i}
            x={pad.l + (d.month - 1) * cellW}
            y={pad.t + d.hour * cellH}
            width={cellW - 1}
            height={cellH - 1}
            rx={1}
            fill={`rgb(${r},${g},${b})`}
            opacity={0.9}
          />
        );
      })}
      {/* Month labels */}
      {months.map((m, i) => (
        <text key={i} x={pad.l + i * cellW + cellW / 2} y={height - 4} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">{m}</text>
      ))}
      {/* Hour labels */}
      {[0, 6, 12, 18].map(h => (
        <text key={h} x={pad.l - 4} y={pad.t + h * cellH + cellH / 2 + 3} textAnchor="end" fill="var(--cds-text-helper)" fontSize="7">{h}:00</text>
      ))}
    </svg>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   BESSPanel — Battery Energy Storage System
   ═══════════════════════════════════════════════════════════════════════════ */
export default function BESSPanel({ onClose }) {
  const { explain, selectedParcel } = useSite();

  /* ── State ── */
  const [activeTab, setActiveTab] = useState("design");
  const [energyMwh, setEnergyMwh] = useState(200);
  const [powerMw, setPowerMw] = useState(50);
  const [chemistry, setChemistry] = useState("lfp");
  const [scenario, setScenario] = useState("central"); // optimistic | central | pessimistic

  // Design
  const [designResult, setDesignResult] = useState(null);
  const [designLoading, setDesignLoading] = useState(false);

  // Revenue
  const [revenueResult, setRevenueResult] = useState(null);
  const [dispatchResult, setDispatchResult] = useState(null);
  const [revLoading, setRevLoading] = useState(false);
  const [dispatchLoading, setDispatchLoading] = useState(false);

  // Financial
  const [financialResult, setFinancialResult] = useState(null);
  const [finLoading, setFinLoading] = useState(false);

  // Bidding
  const [bidResult, setBidResult] = useState(null);
  const [bidLoading, setBidLoading] = useState(false);

  /* ── Derived ── */
  const duration = powerMw > 0 ? (energyMwh / powerMw).toFixed(1) : "--";
  const chemData = CHEMISTRIES.find(c => c.id === chemistry) || CHEMISTRIES[0];
  const containerCount = Math.ceil(energyMwh / 3.7); // ~3.7 MWh per 20ft container
  const footprintM2 = containerCount * 37; // ~37 m2 per container with spacing

  /* ── Duration presets ── */
  const applyDurationPreset = (hours) => {
    setEnergyMwh(powerMw * hours);
  };

  /* ── API calls ── */
  const runDesign = useCallback(async () => {
    setDesignLoading(true);
    try {
      const result = await api.bess.sizing(powerMw, energyMwh / powerMw, "hybrid", null);
      setDesignResult(result);
    } catch (e) { /* silent */ }
    setDesignLoading(false);
  }, [powerMw, energyMwh]);

  const loadRevenue = useCallback(async () => {
    setRevLoading(true);
    try {
      const [rev, estimate] = await Promise.all([
        api.bess.revenue(powerMw, energyMwh, "hybrid"),
        api.bess.revenueEstimate(energyMwh, powerMw),
      ]);
      setRevenueResult(rev || estimate);
    } catch (e) { /* silent */ }
    setRevLoading(false);
  }, [powerMw, energyMwh]);

  const runDispatch = useCallback(async () => {
    setDispatchLoading(true);
    try {
      const result = await api.bess.optimize(energyMwh, powerMw);
      setDispatchResult(result);
    } catch (e) { /* silent */ }
    setDispatchLoading(false);
  }, [powerMw, energyMwh]);

  const loadFinancial = useCallback(async () => {
    setFinLoading(true);
    try {
      const totalCapex = energyMwh * chemData.capex * 1000; // GBP
      const annualRev = revenueResult?.total_annual_gbp || revenueResult?.annual_revenue_gbp || (energyMwh * 85000 / 100);
      const result = await api.bess.financial
        ? await (async () => {
            const r = await fetch("/bess/financial", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                capex_gbp: totalCapex,
                annual_revenue_gbp: annualRev,
                opex_pct: 0.02,
                years: 20,
                discount_rate: 0.08,
              }),
            });
            return r.ok ? r.json() : null;
          })()
        : null;
      setFinancialResult(result || computeLocalFinancials(totalCapex, annualRev));
    } catch (e) {
      const totalCapex = energyMwh * chemData.capex * 1000;
      const annualRev = revenueResult?.total_annual_gbp || revenueResult?.annual_revenue_gbp || (energyMwh * 85000 / 100);
      setFinancialResult(computeLocalFinancials(totalCapex, annualRev));
    }
    setFinLoading(false);
  }, [energyMwh, chemData, revenueResult]);

  const runBidding = useCallback(async () => {
    setBidLoading(true);
    try {
      const result = await api.bess.bidder(powerMw, energyMwh, "coordinated", 24, chemData.efficiency);
      setBidResult(result);
    } catch (e) { /* silent */ }
    setBidLoading(false);
  }, [powerMw, energyMwh, chemData]);

  // Auto-load revenue when switching to tab
  useEffect(() => {
    if (activeTab === "revenue" && !revenueResult && !revLoading) loadRevenue();
    if (activeTab === "financial" && !financialResult && !finLoading) loadFinancial();
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Revenue streams for chart ── */
  const revenueStreams = useMemo(() => {
    if (!revenueResult) return [];
    const data = revenueResult.streams || revenueResult.revenue_streams || revenueResult.breakdown || {};
    return REVENUE_STREAMS.map(s => ({
      ...s,
      value: data[s.id]?.annual_gbp || data[s.id]?.value || data[s.id] || 0,
    })).filter(s => s.value > 0);
  }, [revenueResult]);

  const totalRevenue = revenueResult?.total_annual_gbp || revenueResult?.annual_revenue_gbp
    || revenueStreams.reduce((sum, s) => sum + s.value, 0);

  return (
    <div className="gc-panel bp-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="1" y="6" width="22" height="12" rx="2" />
            <line x1="6" y1="10" x2="6" y2="14" />
            <line x1="10" y1="10" x2="10" y2="14" />
            <line x1="14" y1="10" x2="14" y2="14" />
            <line x1="18" y1="10" x2="18" y2="14" />
          </svg>
          BESS Optimiser
        </div>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Tab bar */}
      <div className="df-tabs">
        {[
          { id: "design", label: "Design" },
          { id: "revenue", label: "Revenue" },
          { id: "financial", label: "Financial" },
          { id: "bidding", label: "Bidding" },
        ].map(tab => (
          <button key={tab.id}
            className={`df-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >{tab.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">

        {/* ═══════════════════ TAB: Design ═══════════════════ */}
        {activeTab === "design" && (
          <>
            {/* Energy slider */}
            <div className="bp-slider-section">
              <div className="bp-slider-header">
                <span className="bp-slider-label">Energy Capacity</span>
                <span className="bp-slider-value">{energyMwh} MWh</span>
              </div>
              <input type="range" min={10} max={1000} step={10} value={energyMwh}
                onChange={e => setEnergyMwh(+e.target.value)} className="bp-slider" />
              <div className="bp-slider-range"><span>10 MWh</span><span>1,000 MWh</span></div>
            </div>

            {/* Power slider */}
            <div className="bp-slider-section">
              <div className="bp-slider-header">
                <span className="bp-slider-label">Power Rating</span>
                <span className="bp-slider-value">{powerMw} MW</span>
              </div>
              <input type="range" min={5} max={500} step={5} value={powerMw}
                onChange={e => setPowerMw(+e.target.value)} className="bp-slider" />
              <div className="bp-slider-range"><span>5 MW</span><span>500 MW</span></div>
            </div>

            {/* Duration auto + presets */}
            <div className="bp-duration-row">
              <div className="bp-duration-calc">
                <span className="bp-duration-label">Duration</span>
                <span className="bp-duration-value">{duration}h</span>
              </div>
              <div className="bp-duration-presets">
                {DURATION_PRESETS.map(h => (
                  <button key={h}
                    className={`bp-preset-btn${parseFloat(duration) === h ? " active" : ""}`}
                    onClick={() => applyDurationPreset(h)}
                  >{h}h</button>
                ))}
              </div>
            </div>

            {/* Chemistry selector */}
            <div className="bp-chemistry-section">
              <div className="bp-section-label">Cell Chemistry</div>
              <div className="bp-chemistry-grid">
                {CHEMISTRIES.map(c => (
                  <button key={c.id}
                    className={`bp-chem-btn${chemistry === c.id ? " active" : ""}`}
                    onClick={() => setChemistry(c.id)}
                  >
                    <div className="bp-chem-name">{c.label}</div>
                    <div className="bp-chem-detail">{c.efficiency * 100}% RTE</div>
                    <div className="bp-chem-detail">{(c.cycles / 1000).toFixed(0)}k cycles</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Auto-calculated metrics */}
            <div className="bp-metrics-grid">
              <div className="bp-metric">
                <span className="bp-metric-label">Containers</span>
                <span className="bp-metric-value">{containerCount}</span>
              </div>
              <div className="bp-metric">
                <span className="bp-metric-label">Footprint</span>
                <span className="bp-metric-value">{(footprintM2 / 10000).toFixed(2)} ha</span>
              </div>
              <div className="bp-metric">
                <span className="bp-metric-label">Round-trip Eff.</span>
                <span className="bp-metric-value">{(chemData.efficiency * 100).toFixed(0)}%</span>
              </div>
              <div className="bp-metric">
                <span className="bp-metric-label">Cycle Life</span>
                <span className="bp-metric-value">{chemData.cycles.toLocaleString()}</span>
              </div>
              <div className="bp-metric">
                <span className="bp-metric-label">Annual Degradation</span>
                <span className="bp-metric-value">{chemData.degradation}%</span>
              </div>
              <div className="bp-metric">
                <span className="bp-metric-label">Est. CAPEX</span>
                <span className="bp-metric-value">{fmtGbp(energyMwh * chemData.capex * 1000)}</span>
              </div>
            </div>

            {/* Generate button */}
            <div className="bp-action-row">
              <button
                onClick={runDesign}
                disabled={designLoading}
                className={`gc-assess-btn${designLoading ? " gc-assess-btn--loading" : ""}`}
                style={{ width: "100%" }}
              >
                {designLoading ? "Calculating..." : "Generate Layout"}
              </button>
            </div>

            {/* Design result */}
            {designResult && (
              <div className="bp-design-result">
                {designResult.recommended && (
                  <div className="bp-rec-badge">Recommended: {designResult.recommended.duration_hours}h / {designResult.recommended.power_mw} MW</div>
                )}
                {designResult.options?.map((opt, i) => (
                  <div key={i} className="bp-design-option">
                    <span>{opt.duration_hours}h</span>
                    <span>{opt.power_mw} MW / {opt.energy_mwh} MWh</span>
                    <span>{fmtGbp(opt.annual_revenue_gbp)}/yr</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ═══════════════════ TAB: Revenue ═══════════════════ */}
        {activeTab === "revenue" && (
          <>
            {revLoading ? (
              <div className="gc-loading" style={{ padding: 24, textAlign: "center", fontSize: 11, color: "var(--cds-text-helper)" }}>Loading revenue model...</div>
            ) : (
              <>
                {/* Total revenue header */}
                <div className="bp-revenue-header">
                  <div className="bp-rev-total">
                    <span className="bp-rev-total-label">Annual Revenue Estimate</span>
                    <span className="bp-rev-total-value">{fmtGbp(totalRevenue)}</span>
                  </div>
                  <div className="bp-rev-unit-metrics">
                    <div className="bp-rev-unit">
                      <span>{fmtGbp(powerMw > 0 ? totalRevenue / powerMw : 0)}</span>
                      <span className="bp-rev-unit-label">per MW</span>
                    </div>
                    <div className="bp-rev-unit">
                      <span>{fmtGbp(energyMwh > 0 ? totalRevenue / energyMwh : 0)}</span>
                      <span className="bp-rev-unit-label">per MWh</span>
                    </div>
                  </div>
                </div>

                {/* Revenue streams chart */}
                {revenueStreams.length > 0 && (
                  <div className="bp-chart-section">
                    <div className="bp-section-label">Revenue Streams Breakdown</div>
                    <RevenueBarChart streams={revenueStreams} />
                  </div>
                )}

                {/* Optimize dispatch */}
                <div className="bp-action-row">
                  <button
                    onClick={runDispatch}
                    disabled={dispatchLoading}
                    className={`gc-assess-btn${dispatchLoading ? " gc-assess-btn--loading" : ""}`}
                    style={{ width: "100%" }}
                  >
                    {dispatchLoading ? "Optimizing..." : "Optimize Dispatch"}
                  </button>
                </div>

                {/* Dispatch profile */}
                {dispatchResult?.schedule && (
                  <div className="bp-chart-section">
                    <div className="bp-section-label">24h Dispatch Profile</div>
                    <DispatchChart schedule={dispatchResult.schedule} />
                    {dispatchResult.total_revenue_gbp != null && (
                      <div className="bp-dispatch-summary">
                        Day revenue: {fmtGbp(dispatchResult.total_revenue_gbp)} |
                        Cycles: {dispatchResult.cycles?.toFixed(1) || "--"} |
                        Avg spread: {fmtGbp(dispatchResult.avg_spread_gbp_mwh || 0)}/MWh
                      </div>
                    )}
                  </div>
                )}

                {!revenueResult && !revLoading && (
                  <div className="gc-empty">
                    <div className="gc-empty-text">Configure BESS parameters in the Design tab first</div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ═══════════════════ TAB: Financial ═══════════════════ */}
        {activeTab === "financial" && (
          <>
            {finLoading ? (
              <div className="gc-loading" style={{ padding: 24, textAlign: "center", fontSize: 11, color: "var(--cds-text-helper)" }}>Building financial model...</div>
            ) : financialResult ? (
              <>
                {/* Key financial metrics */}
                <div className="bp-fin-metrics">
                  <div className="bp-fin-metric bp-fin-metric--primary">
                    <span className="bp-fin-metric-label">IRR</span>
                    <span className="bp-fin-metric-value" style={{ color: (financialResult.irr || 0) > 0.08 ? "#16A34A" : "#DC2626" }}>
                      {financialResult.irr != null ? `${(financialResult.irr * 100).toFixed(1)}%` : "--"}
                    </span>
                  </div>
                  <div className="bp-fin-metric bp-fin-metric--primary">
                    <span className="bp-fin-metric-label">NPV</span>
                    <span className="bp-fin-metric-value" style={{ color: (financialResult.npv_gbp || 0) > 0 ? "#16A34A" : "#DC2626" }}>
                      {fmtGbp(financialResult.npv_gbp)}
                    </span>
                  </div>
                  <div className="bp-fin-metric">
                    <span className="bp-fin-metric-label">Payback</span>
                    <span className="bp-fin-metric-value">{financialResult.payback_years?.toFixed(1) || "--"} yr</span>
                  </div>
                  <div className="bp-fin-metric">
                    <span className="bp-fin-metric-label">LCOS</span>
                    <span className="bp-fin-metric-value">{financialResult.lcoes_gbp_mwh ? `\u00A3${financialResult.lcoes_gbp_mwh.toFixed(0)}/MWh` : "--"}</span>
                  </div>
                </div>

                {/* Scenario toggle */}
                <div className="bp-scenario-toggle">
                  {["optimistic", "central", "pessimistic"].map(s => (
                    <button key={s}
                      className={`bp-scenario-btn${scenario === s ? " active" : ""}`}
                      onClick={() => setScenario(s)}
                    >{s.charAt(0).toUpperCase() + s.slice(1)}</button>
                  ))}
                </div>

                {/* CAPEX breakdown */}
                <div className="bp-section">
                  <div className="bp-section-label">CAPEX Breakdown</div>
                  <div className="bp-capex-list">
                    {CAPEX_ITEMS.map(item => {
                      const multiplier = scenario === "optimistic" ? 0.9 : scenario === "pessimistic" ? 1.15 : 1;
                      const val = energyMwh * chemData.capex * 1000 * item.share * multiplier;
                      return (
                        <div key={item.id} className="gc-cost-row">
                          <span className="gc-cost-label">{item.label}</span>
                          <div className="gc-cost-bar-track">
                            <div className="gc-cost-bar-fill" style={{ width: `${item.share * 100}%` }} />
                          </div>
                          <span className="gc-cost-value">{fmtGbp(val)}</span>
                        </div>
                      );
                    })}
                    <div className="bp-total-row">
                      <span>Total CAPEX</span>
                      <span className="bp-total-value">
                        {fmtGbp(energyMwh * chemData.capex * 1000 * (scenario === "optimistic" ? 0.9 : scenario === "pessimistic" ? 1.15 : 1))}
                      </span>
                    </div>
                  </div>
                </div>

                {/* OPEX summary */}
                <div className="bp-section">
                  <div className="bp-section-label">Annual OPEX</div>
                  <div className="bp-opex-list">
                    {[
                      { label: "O&M", pct: 0.012 },
                      { label: "Degradation Reserve", pct: 0.005 },
                      { label: "Insurance", pct: 0.003 },
                      { label: "Land Lease", pct: 0.002 },
                    ].map((item, i) => {
                      const totalCapex = energyMwh * chemData.capex * 1000;
                      return (
                        <div key={i} className="bp-opex-row">
                          <span>{item.label}</span>
                          <span className="bp-opex-value">{fmtGbp(totalCapex * item.pct)}/yr</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Revenue projection */}
                {financialResult.cashflows && (
                  <div className="bp-section">
                    <div className="bp-section-label">Revenue Projection</div>
                    <div className="bp-projection-table">
                      <div className="bp-proj-header">
                        <span>Year</span><span>Revenue</span><span>OPEX</span><span>Net CF</span><span>Cumulative</span>
                      </div>
                      {financialResult.cashflows.slice(0, 10).map((cf, i) => (
                        <div key={i} className="bp-proj-row">
                          <span>{cf.year || i + 1}</span>
                          <span>{fmtGbp(cf.revenue_gbp || cf.revenue)}</span>
                          <span>{fmtGbp(cf.opex_gbp || cf.opex)}</span>
                          <span style={{ color: (cf.net_cashflow_gbp || cf.net || 0) > 0 ? "#16A34A" : "#DC2626" }}>
                            {fmtGbp(cf.net_cashflow_gbp || cf.net)}
                          </span>
                          <span>{fmtGbp(cf.cumulative_gbp || cf.cumulative)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Debt/equity */}
                <div className="bp-section">
                  <div className="bp-section-label">Capital Structure</div>
                  <div className="bp-capital-bar">
                    <div className="bp-capital-debt" style={{ width: "70%" }}>
                      <span>Debt 70%</span>
                    </div>
                    <div className="bp-capital-equity" style={{ width: "30%" }}>
                      <span>Equity 30%</span>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="bp-action-row" style={{ paddingTop: 16 }}>
                <button onClick={loadFinancial} disabled={finLoading}
                  className="gc-assess-btn" style={{ width: "100%" }}>
                  Build Financial Model
                </button>
              </div>
            )}
          </>
        )}

        {/* ═══════════════════ TAB: Bidding ═══════════════════ */}
        {activeTab === "bidding" && (
          <>
            <div className="bp-action-row">
              <button
                onClick={runBidding}
                disabled={bidLoading}
                className={`gc-assess-btn${bidLoading ? " gc-assess-btn--loading" : ""}`}
                style={{ width: "100%" }}
              >
                {bidLoading ? "Simulating..." : "Run Market Simulation"}
              </button>
            </div>

            {bidResult ? (
              <>
                {/* Summary stats */}
                <div className="bp-metrics-grid" style={{ marginTop: 0 }}>
                  <div className="bp-metric">
                    <span className="bp-metric-label">Day Revenue</span>
                    <span className="bp-metric-value">{fmtGbp(bidResult.total_revenue_gbp || bidResult.total_profit_gbp)}</span>
                  </div>
                  <div className="bp-metric">
                    <span className="bp-metric-label">Cycles</span>
                    <span className="bp-metric-value">{fmtNum(bidResult.cycles || bidResult.total_cycles, 1)}</span>
                  </div>
                  <div className="bp-metric">
                    <span className="bp-metric-label">Avg Spread</span>
                    <span className="bp-metric-value">{fmtGbp(bidResult.avg_spread_gbp_mwh)}/MWh</span>
                  </div>
                  <div className="bp-metric">
                    <span className="bp-metric-label">Final SoC</span>
                    <span className="bp-metric-value">{fmtNum((bidResult.final_soc_pct || bidResult.final_soc || 0) * 100, 0)}%</span>
                  </div>
                </div>

                {/* Dispatch chart from bidding */}
                {bidResult.schedule && (
                  <div className="bp-chart-section">
                    <div className="bp-section-label">Bidding Dispatch</div>
                    <DispatchChart schedule={bidResult.schedule} />
                  </div>
                )}

                {/* Balancing actions */}
                {bidResult.balancing_actions?.length > 0 && (
                  <div className="bp-section">
                    <div className="bp-section-label">Balancing Actions</div>
                    {bidResult.balancing_actions.map((a, i) => (
                      <div key={i} className="bp-bal-action">
                        <span>{a.hour}:00</span>
                        <span className={a.direction === "offer" ? "bp-text-green" : "bp-text-red"}>
                          {a.direction}
                        </span>
                        <span>{a.volume_mw} MW</span>
                        <span>{fmtGbp(a.price_gbp_mwh)}/MWh</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Revenue heatmap */}
                {bidResult.hourly_revenue_heatmap && (
                  <div className="bp-chart-section">
                    <div className="bp-section-label">Monthly Revenue Heatmap</div>
                    <RevenueHeatmap data={bidResult.hourly_revenue_heatmap} />
                  </div>
                )}
              </>
            ) : !bidLoading ? (
              <div className="gc-empty">
                <div className="gc-empty-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cds-interactive)" strokeWidth="1.5">
                    <rect x="1" y="6" width="22" height="12" rx="2" />
                    <line x1="6" y1="10" x2="6" y2="14" />
                    <line x1="10" y1="10" x2="10" y2="14" />
                    <line x1="14" y1="10" x2="14" y2="14" />
                    <line x1="18" y1="10" x2="18" y2="14" />
                  </svg>
                </div>
                <div className="gc-empty-text">
                  Click <strong>Run Market Simulation</strong> to<br />
                  simulate day-ahead and intraday bidding
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="bp-footer">
        <span>{energyMwh} MWh / {powerMw} MW / {duration}h / {chemData.label}</span>
        <span>{fmtGbp(energyMwh * chemData.capex * 1000)} CAPEX</span>
      </div>
    </div>
  );
}

/* ── Local financial model fallback ─────────────────────────────────────── */
function computeLocalFinancials(capex, annualRevenue) {
  const opexRate = 0.022;
  const discountRate = 0.08;
  const years = 20;
  const opex = capex * opexRate;
  const netCf = annualRevenue - opex;
  let npv = -capex;
  let cumulative = -capex;
  let payback = null;
  const cashflows = [];

  for (let y = 1; y <= years; y++) {
    const degradation = Math.pow(0.98, y - 1);
    const rev = annualRevenue * degradation;
    const net = rev - opex;
    cumulative += net;
    npv += net / Math.pow(1 + discountRate, y);
    if (payback == null && cumulative >= 0) payback = y;
    cashflows.push({ year: y, revenue_gbp: rev, opex_gbp: opex, net_cashflow_gbp: net, cumulative_gbp: cumulative });
  }

  // Approximate IRR using bisection
  let irrLow = -0.5, irrHigh = 1.0;
  for (let iter = 0; iter < 50; iter++) {
    const mid = (irrLow + irrHigh) / 2;
    let testNpv = -capex;
    for (let y = 1; y <= years; y++) {
      testNpv += (annualRevenue * Math.pow(0.98, y - 1) - opex) / Math.pow(1 + mid, y);
    }
    if (testNpv > 0) irrLow = mid; else irrHigh = mid;
  }

  return {
    irr: (irrLow + irrHigh) / 2,
    npv_gbp: npv,
    payback_years: payback || years,
    lcoes_gbp_mwh: capex > 0 ? (capex + opex * years) / (annualRevenue / 85 * years) : 0,
    cashflows,
  };
}
