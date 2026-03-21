import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";

/**
 * TimelineCard — horizontal Gantt-style SVG showing the 5 phases of
 * time-to-energisation: Pre-application, Planning, Connection Offer,
 * Connection Works, Commissioning.
 *
 * Calls POST /api/grid/energisation-timeline with site location and capacity.
 */

const PHASE_COLORS = [
  "#6366f1", // Pre-application — indigo
  "#f59e0b", // Planning — amber
  "#3b82f6", // Connection offer — blue
  "#10b981", // Connection works — emerald
  "#8b5cf6", // Commissioning — violet
];

function GanttSVG({ data }) {
  if (!data || !data.phases || data.phases.length === 0) return null;

  const phases = data.phases;
  const totalMonths = data.total_months || phases[phases.length - 1].start_month + phases[phases.length - 1].months;
  const range = data.total_months_range;

  // SVG layout
  const W = 800;
  const H = 180;
  const padL = 120;
  const padR = 50;
  const padT = 25;
  const padB = 30;
  const chartW = W - padL - padR;
  const rowH = 24;
  const rowGap = 4;

  const scale = totalMonths > 0 ? chartW / (totalMonths * 1.1) : 1;
  const xForMonth = (m) => padL + m * scale;

  // Year markers
  const yearMarkers = [];
  for (let m = 12; m <= totalMonths * 1.1; m += 12) {
    yearMarkers.push(m);
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      style={{ display: "block" }}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Year grid lines */}
      {yearMarkers.map((m) => (
        <g key={`yr-${m}`}>
          <line
            x1={xForMonth(m)} y1={padT - 5}
            x2={xForMonth(m)} y2={padT + phases.length * (rowH + rowGap)}
            stroke="rgba(100,120,160,0.15)" strokeWidth={1} strokeDasharray="4,3"
          />
          <text
            x={xForMonth(m)} y={padT - 8}
            fill="#666" fontSize={8} textAnchor="middle"
          >
            Yr {m / 12}
          </text>
        </g>
      ))}

      {/* Phase bars */}
      {phases.map((phase, i) => {
        const y = padT + i * (rowH + rowGap);
        const x = xForMonth(phase.start_month);
        const w = Math.max(8, phase.months * scale);
        const color = PHASE_COLORS[i % PHASE_COLORS.length];

        return (
          <g key={i}>
            {/* Phase label */}
            <text
              x={padL - 8} y={y + rowH / 2 + 3}
              fill="#aaa" fontSize={9} textAnchor="end"
              fontWeight={500}
            >
              {phase.name}
            </text>

            {/* Bar */}
            <rect
              x={x} y={y}
              width={w} height={rowH}
              fill={color} rx={3} opacity={0.85}
            />

            {/* Duration label inside bar */}
            <text
              x={x + w / 2} y={y + rowH / 2 + 3}
              fill="#fff" fontSize={9} textAnchor="middle"
              fontWeight={600}
            >
              {phase.months}mo
            </text>
          </g>
        );
      })}

      {/* Total line with P10/P90 range */}
      {range && (
        <g>
          {/* P10/P90 range bar */}
          <rect
            x={xForMonth(range.p10)}
            y={padT + phases.length * (rowH + rowGap) + 4}
            width={Math.max(4, (range.p90 - range.p10) * scale)}
            height={6}
            fill="rgba(99,102,241,0.25)" rx={3}
          />
          {/* P50 marker */}
          <line
            x1={xForMonth(range.p50)}
            y1={padT + phases.length * (rowH + rowGap) + 2}
            x2={xForMonth(range.p50)}
            y2={padT + phases.length * (rowH + rowGap) + 12}
            stroke="#6366f1" strokeWidth={2}
          />
          <text
            x={xForMonth(range.p50)}
            y={padT + phases.length * (rowH + rowGap) + 22}
            fill="#6366f1" fontSize={9} textAnchor="middle" fontWeight={600}
          >
            {range.p50}mo (P50)
          </text>
          {/* P10 label */}
          <text
            x={xForMonth(range.p10) - 2}
            y={padT + phases.length * (rowH + rowGap) + 10}
            fill="#888" fontSize={7} textAnchor="end"
          >
            {range.p10}
          </text>
          {/* P90 label */}
          <text
            x={xForMonth(range.p90) + 2}
            y={padT + phases.length * (rowH + rowGap) + 10}
            fill="#888" fontSize={7} textAnchor="start"
          >
            {range.p90}
          </text>
        </g>
      )}

      {/* Month axis */}
      <text
        x={padL} y={H - 4}
        fill="#666" fontSize={8}
      >
        Months from application
      </text>
    </svg>
  );
}

export default function TimelineCard() {
  const { pickedLocation } = useSite();
  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon;

  const [capacityMw, setCapacityMw] = useState(50);
  const [technology, setTechnology] = useState("solar");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/grid/energisation-timeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: lat || 52.5,
          lon: lon || -1.5,
          capacity_mw: capacityMw,
          technology,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, capacityMw, technology]);

  const themeColor = "#6366f1";

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <h3 style={{ margin: "0 0 8px", color: themeColor }}>
        Time to Energisation
      </h3>

      {/* Controls */}
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 10, color: "#aaa" }}>MW:</label>
        <input
          type="number" min={0.1} max={500} value={capacityMw}
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
          <option value="solar">Solar PV</option>
          <option value="wind">Wind</option>
          <option value="bess">BESS</option>
          <option value="solar+bess">Solar + BESS</option>
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
        {loading ? "Estimating..." : "Estimate Timeline"}
      </button>

      {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

      {result && (
        <>
          {/* Headline */}
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
            <span style={{ fontSize: 28, fontWeight: 700, color: themeColor }}>
              {result.total_months}
            </span>
            <span style={{ fontSize: 13, color: "#aaa" }}>months to energisation</span>
            {result.target_date && (
              <span style={{
                fontSize: 11, color: "#4caf50", fontWeight: 600,
                marginLeft: "auto",
              }}>
                Target: {result.target_date}
              </span>
            )}
          </div>

          {/* Gantt chart */}
          <div className="timeline-chart-container">
            <GanttSVG data={result} />
          </div>

          {/* Risk factors */}
          {result.risk_factors && result.risk_factors.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#f59e0b", marginBottom: 4 }}>
                Risk Factors
              </div>
              {result.risk_factors.map((r, i) => (
                <div key={i} style={{ fontSize: 10, color: "#f59e0b", marginBottom: 2 }}>
                  {r}
                </div>
              ))}
            </div>
          )}

          {/* Benchmarks */}
          {result.benchmarks && (
            <div style={{
              display: "flex", gap: 12, marginTop: 8, fontSize: 10, color: "#888",
            }}>
              {result.benchmarks.similar_projects_avg_months != null && (
                <span>Similar projects avg: <strong>{result.benchmarks.similar_projects_avg_months}mo</strong></span>
              )}
              {result.benchmarks.dno_avg_processing_months != null && (
                <span>DNO avg processing: <strong>{result.benchmarks.dno_avg_processing_months}mo</strong></span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
