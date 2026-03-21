import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";

/**
 * RevenueWaterfallCard — SVG waterfall chart showing BESS revenue breakdown
 * by market service. Required for every BESS investment committee paper.
 *
 * Displays stacked waterfall bars: Wholesale, BM Spread, FFR, Dynamic
 * Containment, Capacity Market, Embedded Benefits = Total, minus OPEX = Net.
 * P10/P50/P90 whiskers on Total bar. LCOE, IRR, payback below chart.
 */

const SERVICES = [
  { key: "wholesale",           label: "Wholesale",  color: "#D4A018" },
  { key: "balancing_mechanism",  label: "BM Spread",  color: "#e67e22" },
  { key: "ffr",                 label: "FFR",         color: "#2196f3" },
  { key: "dc",                  label: "Dyn. Cont.",  color: "#00bcd4" },
  { key: "capacity_market",     label: "Cap. Mkt",    color: "#4caf50" },
  { key: "embedded_benefits",   label: "Embedded",    color: "#9c27b0" },
];

const fmtK = (v) => {
  if (v == null) return "\u2014";
  if (Math.abs(v) >= 1e6) return `\u00A3${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `\u00A3${(v / 1e3).toFixed(0)}k`;
  return `\u00A3${Math.round(v)}`;
};

function WaterfallSVG({ data }) {
  if (!data) return null;

  const streams = data.revenue_streams || {};
  const mc = data.monte_carlo || {};
  const totalRevenue = data.total_annual_revenue_gbp || 0;

  // Build bars: revenue services + total + opex + net
  const capex = (data.assumptions?.capex_gbp_kw || 600) * (data.capacity_mw || 50) * 1000;
  const opexPct = data.assumptions?.opex_pct_capex || 0.015;
  const opexGbp = capex * opexPct;
  const netRevenue = totalRevenue - opexGbp;

  const bars = [];
  let runningTotal = 0;

  // Revenue service bars
  for (const svc of SERVICES) {
    const gbp = streams[svc.key]?.gbp || 0;
    if (gbp <= 0) continue;
    bars.push({
      label: svc.label,
      value: gbp,
      start: runningTotal,
      color: svc.color,
      type: "add",
    });
    runningTotal += gbp;
  }

  // Total bar
  bars.push({
    label: "Total",
    value: totalRevenue,
    start: 0,
    color: "#1a237e",
    type: "total",
    p10: mc.p10,
    p50: mc.p50,
    p90: mc.p90,
  });

  // OPEX (subtraction)
  bars.push({
    label: "OPEX",
    value: opexGbp,
    start: totalRevenue - opexGbp,
    color: "#e53935",
    type: "subtract",
  });

  // Net bar
  bars.push({
    label: "Net",
    value: netRevenue,
    start: 0,
    color: netRevenue >= 0 ? "#2e7d32" : "#c62828",
    type: "total",
  });

  // SVG dimensions
  const W = 800;
  const H = 240;
  const padL = 10;
  const padR = 10;
  const padT = 30;
  const padB = 40;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const barCount = bars.length;
  const gap = 6;
  const barW = Math.max(20, (chartW - gap * (barCount - 1)) / barCount);

  // Scale: max value = totalRevenue * 1.15 (room for whiskers)
  const maxVal = Math.max(totalRevenue * 1.15, netRevenue, ...(mc.p90 ? [mc.p90] : []));
  const scale = maxVal > 0 ? chartH / maxVal : 1;

  const yForVal = (v) => padT + chartH - v * scale;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      style={{ display: "block" }}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Baseline */}
      <line
        x1={padL} y1={padT + chartH}
        x2={padL + chartW} y2={padT + chartH}
        stroke="rgba(100,120,160,0.2)" strokeWidth={1}
      />

      {bars.map((bar, i) => {
        const x = padL + i * (barW + gap);
        const barTop = bar.type === "subtract"
          ? yForVal(bar.start + bar.value)
          : yForVal(bar.start + bar.value);
        const barBottom = bar.type === "total"
          ? yForVal(0)
          : yForVal(bar.start);
        const barHeight = Math.max(1, barBottom - barTop);

        // Connector line from previous bar
        const connector = bar.type === "add" && i > 0;
        const prevBar = bars[i - 1];
        const prevX = padL + (i - 1) * (barW + gap);

        return (
          <g key={i}>
            {/* Connector dashed line */}
            {connector && (
              <line
                x1={prevX + barW} y1={yForVal(bar.start)}
                x2={x} y2={yForVal(bar.start)}
                stroke="rgba(100,120,160,0.25)" strokeWidth={1} strokeDasharray="3,2"
              />
            )}

            {/* Bar */}
            <rect
              x={x} y={barTop}
              width={barW} height={barHeight}
              fill={bar.color}
              rx={2}
              opacity={bar.type === "total" ? 1 : 0.85}
            />

            {/* Total bar bold border */}
            {bar.type === "total" && (
              <rect
                x={x} y={barTop}
                width={barW} height={barHeight}
                fill="none" stroke={bar.color} strokeWidth={2} rx={2}
              />
            )}

            {/* P10/P50/P90 whiskers on Total bar */}
            {bar.p10 != null && bar.p90 != null && (
              <>
                {/* Whisker line */}
                <line
                  x1={x + barW / 2} y1={yForVal(bar.p90)}
                  x2={x + barW / 2} y2={yForVal(bar.p10)}
                  stroke="#fff" strokeWidth={2} opacity={0.7}
                />
                {/* P10 cap */}
                <line
                  x1={x + barW / 2 - 6} y1={yForVal(bar.p10)}
                  x2={x + barW / 2 + 6} y2={yForVal(bar.p10)}
                  stroke="#fff" strokeWidth={2} opacity={0.7}
                />
                {/* P90 cap */}
                <line
                  x1={x + barW / 2 - 6} y1={yForVal(bar.p90)}
                  x2={x + barW / 2 + 6} y2={yForVal(bar.p90)}
                  stroke="#fff" strokeWidth={2} opacity={0.7}
                />
                {/* P10 label */}
                <text
                  x={x + barW / 2 + 10} y={yForVal(bar.p10) + 3}
                  fill="#aaa" fontSize={8} textAnchor="start"
                >P10</text>
                {/* P90 label */}
                <text
                  x={x + barW / 2 + 10} y={yForVal(bar.p90) + 3}
                  fill="#aaa" fontSize={8} textAnchor="start"
                >P90</text>
              </>
            )}

            {/* Value label above bar */}
            <text
              x={x + barW / 2}
              y={barTop - 4}
              fill={bar.type === "total" ? "#fff" : "#ccc"}
              fontSize={9}
              fontWeight={bar.type === "total" ? 700 : 500}
              textAnchor="middle"
              fontFamily="var(--mono, monospace)"
            >
              {fmtK(bar.value)}
            </text>

            {/* Category label below */}
            <text
              x={x + barW / 2}
              y={padT + chartH + 14}
              fill="#888"
              fontSize={8}
              textAnchor="middle"
              fontWeight={bar.type === "total" ? 700 : 400}
            >
              {bar.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function RevenueWaterfallCard() {
  const { pickedLocation, samCapacity } = useSite();
  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon;

  const [capacityMw, setCapacityMw] = useState(50);
  const [technology, setTechnology] = useState("bess");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({
        capacity_mw: capacityMw,
        technology,
      });
      if (lat != null) q.set("lat", lat);
      if (lon != null) q.set("lon", lon);
      const res = await fetch(`/api/grid/revenue-stack?${q}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, capacityMw, technology]);

  const themeColor = "#1a237e";

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <h3 style={{ margin: "0 0 8px", color: themeColor }}>
        Revenue Waterfall
      </h3>

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 10, color: "#aaa" }}>MW:</label>
        <input
          type="number" min={1} max={500} value={capacityMw}
          onChange={(e) => setCapacityMw(Number(e.target.value))}
          style={{
            width: 60, padding: "3px 6px", fontSize: 11,
            background: "#F7F8FA", color: "#4B5563",
            border: "1px solid rgba(0,0,0,0.1)", borderRadius: 4,
          }}
        />
        <label style={{ fontSize: 10, color: "#aaa" }}>Tech:</label>
        <select
          value={technology}
          onChange={(e) => setTechnology(e.target.value)}
          className="settings-select"
          style={{ padding: "3px 6px", fontSize: 11, flex: 1 }}
        >
          <option value="bess">BESS</option>
          <option value="solar+bess">Solar + BESS</option>
          <option value="solar">Solar</option>
          <option value="wind">Wind</option>
        </select>
      </div>

      <button
        onClick={run}
        disabled={loading}
        style={{
          background: themeColor, color: "#fff", border: "none", borderRadius: 4,
          padding: "6px 14px", fontSize: 12, cursor: "pointer", width: "100%", marginBottom: 8,
        }}
      >
        {loading ? "Calculating..." : "Revenue Waterfall"}
      </button>

      {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

      {result && (
        <>
          {/* Waterfall chart */}
          <div className="waterfall-chart-container">
            <WaterfallSVG data={result} />
          </div>

          {/* KPI strip below chart */}
          <div className="waterfall-kpi-strip">
            <div className="waterfall-kpi">
              <span className="waterfall-kpi-value">
                {result.lcoe_gbp_mwh != null ? `\u00A3${result.lcoe_gbp_mwh.toFixed(1)}` : "\u2014"}
              </span>
              <span className="waterfall-kpi-label">LCOE/MWh</span>
            </div>
            <div className="waterfall-kpi">
              <span className="waterfall-kpi-value" style={{
                color: (result.irr_pct || 0) >= 10 ? "#4caf50" : (result.irr_pct || 0) >= 6 ? "#ff9800" : "#f44336",
              }}>
                {result.irr_pct != null ? `${result.irr_pct.toFixed(1)}%` : "\u2014"}
              </span>
              <span className="waterfall-kpi-label">IRR</span>
            </div>
            <div className="waterfall-kpi">
              <span className="waterfall-kpi-value">
                {result.payback_years != null ? `${result.payback_years.toFixed(1)}yr` : "\u2014"}
              </span>
              <span className="waterfall-kpi-label">Payback</span>
            </div>
            <div className="waterfall-kpi">
              <span className="waterfall-kpi-value" style={{ color: "#D4A018" }}>
                {fmtK(result.total_annual_revenue_gbp)}
              </span>
              <span className="waterfall-kpi-label">Total/yr</span>
            </div>
          </div>

          {/* Monte Carlo range */}
          {result.monte_carlo && (
            <div style={{
              display: "flex", justifyContent: "space-between",
              fontSize: 10, color: "#888", marginTop: 6, padding: "0 4px",
            }}>
              <span>P10: {fmtK(result.monte_carlo.p10)}</span>
              <span style={{ fontWeight: 600, color: "#ccc" }}>P50: {fmtK(result.monte_carlo.p50)}</span>
              <span>P90: {fmtK(result.monte_carlo.p90)}</span>
            </div>
          )}

          {/* Strategy */}
          {result.optimal_strategy_detail && (
            <div style={{ fontSize: 10, color: "#888", marginTop: 6, fontStyle: "italic" }}>
              Strategy: {result.optimal_strategy_detail}
            </div>
          )}
        </>
      )}
    </div>
  );
}
