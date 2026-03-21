import React, { useState, useEffect, useCallback } from "react";
import { useWorkspace, WORKSPACES, WORKSPACE_INTENTS } from "../../contexts/WorkspaceContext";
import { useSite } from "../../SiteContext";
import api from "../../services/api";

/* ── Capability cards (unchanged) ─────────────────────────────────────────── */
const CAPABILITY_CARDS = {
  grid_study:           { label: "Grid Study",           desc: "Network analysis and capacity assessment", icon: "M13 2L3 14h9l-1 8 10-12h-9l1-8z", color: "#D4A018" },
  grid_connection:      { label: "Grid Connection",      desc: "Connection feasibility and cost estimation", icon: "M13 2L3 14h9l-1 8 10-12h-9l1-8z", color: "#5b8def" },
  demand_forecast:      { label: "Demand Forecast",      desc: "Prophet + TFT demand projections", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z", color: "#f59e0b" },
  advanced_grid:        { label: "Advanced Grid",        desc: "N-1 contingency and power flow analysis", icon: "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z", color: "#818cf8" },
  grid_efficiency:      { label: "Grid Efficiency",      desc: "Line losses, congestion, upgrade opportunities", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z", color: "#22c55e" },
  feasibility:          { label: "Feasibility",          desc: "Site scoring and solar yield analysis", icon: "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z", color: "#f59e0b" },
  financial:            { label: "Financial",            desc: "Revenue, pricing, and ROI analysis", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#22c55e" },
  bess_optimisation:    { label: "BESS Optimisation",    desc: "Battery storage sizing and dispatch", icon: "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15", color: "#a78bfa" },
  satellite_analysis:   { label: "Satellite Analysis",   desc: "Remote sensing and land classification", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#38bdf8" },
  environmental:        { label: "Environmental",        desc: "Impact assessment and habitat analysis", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#22c55e" },
  planning:             { label: "Planning",             desc: "Planning applications and constraints", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", color: "#f59e0b" },
  legacy_compliance:    { label: "Legacy Compliance",    desc: "UK regulatory compliance (G99, CDM, BNG)", icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z", color: "#9ba8b9" },
  connection_strategy:  { label: "Connection Strategy",  desc: "Optimal connection route planning", icon: "M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7", color: "#5b8def" },
  dispatch_optimisation:{ label: "Dispatch Optimisation", desc: "Optimal energy dispatch scheduling", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", color: "#D4A018" },
  route_to_market:      { label: "Route to Market",      desc: "Revenue streams and PPA analysis", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6", color: "#22c55e" },
  sustainability:       { label: "Sustainability",       desc: "ESG metrics and carbon accounting", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#10b981" },
  investment_readiness: { label: "Investment Readiness", desc: "Due diligence and investment scoring", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", color: "#a78bfa" },
  site_prospecting:     { label: "Site Prospecting",     desc: "Candidate scoring and regional scan", icon: "M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z", color: "#38bdf8" },
  procurement:          { label: "Procurement",          desc: "Tender classification and bid viability", icon: "M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z", color: "#f59e0b" },
};

const WORKSPACE_META = {
  home:        { title: "Princeps", desc: "Energy infrastructure site feasibility platform" },
  grid:        { title: "Grid", desc: "Network analysis, power flow, and capacity assessment" },
  feasibility: { title: "Feasibility", desc: "Site scoring, solar yield, and connection analysis" },
  environment: { title: "Environment", desc: "Impact assessment, land use, and habitat analysis" },
  operations:  { title: "Operations", desc: "Live monitoring, dispatch, and grid efficiency" },
  investment:  { title: "Investment", desc: "Financial modelling, due diligence, and ROI" },
};

/* ── Demo portfolio data (loaded from API when available, falls back to demo) ── */
const DEMO_PORTFOLIO = [
  { name: "Highland Wind", capacity_mw: 50, technology: "wind", region: "Scotland", status: "operational", phase: "operational", score: 78, verdict: "GO" },
  { name: "Midlands Solar", capacity_mw: 30, technology: "solar", region: "Midlands", status: "construction", phase: "installation", score: 72, verdict: "GO" },
  { name: "Slough DC", capacity_mw: 15, technology: "datacentre", region: "South", status: "planning", phase: "grid_study", score: 64, verdict: "CAUTION" },
  { name: "Kent BESS", capacity_mw: 40, technology: "bess", region: "South", status: "permitting", phase: "permitting", score: 81, verdict: "GO" },
  { name: "Norfolk Solar", capacity_mw: 25, technology: "solar", region: "South", status: "feasibility", phase: "site_assessment", score: 55, verdict: "CAUTION" },
  { name: "Yorkshire Wind", capacity_mw: 60, technology: "wind", region: "North", status: "operational", phase: "operational", score: 85, verdict: "GO" },
  { name: "Manchester Edge DC", capacity_mw: 5, technology: "datacentre", region: "North", status: "feasibility", phase: "feasibility", score: 42, verdict: "NO-GO" },
  { name: "Devon Thermal", capacity_mw: 8, technology: "thermal", region: "South", status: "construction", phase: "foundation", score: 69, verdict: "GO" },
];

const TECH_COLORS = {
  wind: "#5b8def", solar: "#f59e0b", bess: "#a78bfa", datacentre: "#D4A018", thermal: "#f97316",
};

const STATUS_COLORS = {
  operational: "#24a148", construction: "#1890ff", permitting: "#f59e0b", planning: "#818cf8", feasibility: "#8b8fa3",
};

const PHASES = [
  "feasibility", "site_assessment", "grid_study", "permitting", "foundation", "installation", "commissioning", "operational",
];

const RISK_CATEGORIES = [
  { id: "grid", label: "Grid Capacity", severity: 3, count: 2, color: "#da1e28" },
  { id: "planning", label: "Planning/Permitting", severity: 2, count: 3, color: "#f59e0b" },
  { id: "environmental", label: "Environmental", severity: 1, count: 1, color: "#22c55e" },
  { id: "supply", label: "Supply Chain", severity: 2, count: 2, color: "#f59e0b" },
  { id: "financial", label: "Financial", severity: 1, count: 1, color: "#22c55e" },
  { id: "technical", label: "Technical", severity: 2, count: 1, color: "#f59e0b" },
  { id: "regulatory", label: "Regulatory", severity: 3, count: 1, color: "#da1e28" },
  { id: "cyber", label: "Cybersecurity", severity: 1, count: 0, color: "#22c55e" },
];

const COST_CATEGORIES = [
  { label: "Grid Connection", planned: 4200, actual: 3800, color: "#5b8def" },
  { label: "Equipment", planned: 12500, actual: 11200, color: "#D4A018" },
  { label: "Civil Works", planned: 6800, actual: 7100, color: "#f59e0b" },
  { label: "Permits & Legal", planned: 1200, actual: 950, color: "#22c55e" },
  { label: "O&M Reserve", planned: 2400, actual: 2400, color: "#a78bfa" },
  { label: "Contingency", planned: 1800, actual: 600, color: "#8b8fa3" },
];

/* ── Inline chart components ─────────────────────────────────────────────── */

function KPICard({ label, value, unit, delta, deltaLabel, color, icon }) {
  return (
    <div className="pd-kpi-card">
      <div className="pd-kpi-header">
        <span className="pd-kpi-label">{label}</span>
        {icon && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color || "#8b8fa3"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d={icon} />
          </svg>
        )}
      </div>
      <div className="pd-kpi-value" style={{ color: color || "#e8e8e8" }}>
        {value}<span className="pd-kpi-unit">{unit}</span>
      </div>
      {delta != null && (
        <div className="pd-kpi-delta" style={{ color: delta >= 0 ? "#24a148" : "#da1e28" }}>
          {delta >= 0 ? "+" : ""}{delta}% <span style={{ color: "#666", fontSize: 9 }}>{deltaLabel}</span>
        </div>
      )}
    </div>
  );
}

function TechMixDonut({ portfolio, apiTechMix, size = 140 }) {
  const techTotals = {};
  if (apiTechMix) {
    // Use real API data
    Object.entries(apiTechMix).forEach(([tech, data]) => {
      techTotals[tech] = data.mw || 0;
    });
  } else {
    portfolio.forEach(p => {
      techTotals[p.technology] = (techTotals[p.technology] || 0) + p.capacity_mw;
    });
  }
  const entries = Object.entries(techTotals).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const cx = size / 2, cy = size / 2, r = size / 2 - 20, inner = r * 0.6;

  let angle = -Math.PI / 2;
  const arcs = entries.map(([tech, val]) => {
    const sweep = (val / total) * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sweep), y2 = cy + r * Math.sin(angle + sweep);
    const ix1 = cx + inner * Math.cos(angle), iy1 = cy + inner * Math.sin(angle);
    const ix2 = cx + inner * Math.cos(angle + sweep), iy2 = cy + inner * Math.sin(angle + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    const d = `M${ix1},${iy1} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} L${ix2},${iy2} A${inner},${inner} 0 ${large} 0 ${ix1},${iy1}`;
    angle += sweep;
    return { tech, val, d, color: TECH_COLORS[tech] || "#888" };
  });

  return (
    <div style={{ textAlign: "center" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {arcs.map(a => <path key={a.tech} d={a.d} fill={a.color} opacity={0.85} />)}
        <text x={cx} y={cy - 6} textAnchor="middle" fill="#e8e8e8" fontSize={18} fontWeight={700}>{total}</text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill="#8b8fa3" fontSize={9}>MW Total</text>
      </svg>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "4px 12px", marginTop: 4 }}>
        {entries.map(([tech, val]) => (
          <div key={tech} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: TECH_COLORS[tech] || "#888" }} />
            <span style={{ color: "#ccc", textTransform: "capitalize" }}>{tech}</span>
            <span style={{ color: "#888" }}>{val} MW</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function VerdictPills({ portfolio }) {
  const counts = { GO: 0, CAUTION: 0, "NO-GO": 0 };
  portfolio.forEach(p => { if (counts[p.verdict] != null) counts[p.verdict]++; });
  const total = portfolio.length;
  return (
    <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
      {[
        { key: "GO", color: "#24a148" },
        { key: "CAUTION", color: "#f1c21b" },
        { key: "NO-GO", color: "#da1e28" },
      ].map(v => (
        <div key={v.key} style={{ textAlign: "center" }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: v.color }}>{counts[v.key]}</div>
          <div style={{ fontSize: 9, color: "#888" }}>{v.key}</div>
          <div style={{
            height: 3, borderRadius: 2, marginTop: 3,
            width: 40, background: "#1a1f2e",
          }}>
            <div style={{
              width: `${total ? (counts[v.key] / total) * 100 : 0}%`,
              height: "100%", borderRadius: 2, background: v.color,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ProjectPipeline({ portfolio }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
            <th style={{ textAlign: "left", padding: "6px 8px", color: "#8b8fa3", fontWeight: 500 }}>Project</th>
            <th style={{ textAlign: "center", padding: "6px 4px", color: "#8b8fa3", fontWeight: 500 }}>Type</th>
            <th style={{ textAlign: "right", padding: "6px 4px", color: "#8b8fa3", fontWeight: 500 }}>MW</th>
            <th style={{ textAlign: "left", padding: "6px 4px", color: "#8b8fa3", fontWeight: 500 }}>Phase</th>
            <th style={{ textAlign: "center", padding: "6px 4px", color: "#8b8fa3", fontWeight: 500 }}>Score</th>
            <th style={{ textAlign: "center", padding: "6px 4px", color: "#8b8fa3", fontWeight: 500 }}>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {portfolio.map((p, i) => {
            const phaseIdx = PHASES.indexOf(p.phase);
            const phasePct = phaseIdx >= 0 ? ((phaseIdx + 1) / PHASES.length) * 100 : 0;
            return (
              <tr key={i} style={{ borderBottom: "1px solid #1a1f2e" }}>
                <td style={{ padding: "6px 8px", color: "#e8e8e8", fontWeight: 500 }}>{p.name}</td>
                <td style={{ padding: "6px 4px", textAlign: "center" }}>
                  <span style={{
                    display: "inline-block", width: 8, height: 8, borderRadius: 2,
                    background: TECH_COLORS[p.technology] || "#888", marginRight: 4,
                  }} />
                  <span style={{ color: "#aaa", fontSize: 10, textTransform: "capitalize" }}>{p.technology}</span>
                </td>
                <td style={{ padding: "6px 4px", color: "#e8e8e8", textAlign: "right" }}>{p.capacity_mw}</td>
                <td style={{ padding: "6px 4px", width: 120 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ flex: 1, height: 4, background: "#1a1f2e", borderRadius: 2 }}>
                      <div style={{
                        width: `${phasePct}%`, height: "100%", borderRadius: 2,
                        background: STATUS_COLORS[p.status] || "#888",
                      }} />
                    </div>
                    <span style={{ fontSize: 9, color: "#888", whiteSpace: "nowrap" }}>{p.phase.replace("_", " ")}</span>
                  </div>
                </td>
                <td style={{ padding: "6px 4px", textAlign: "center" }}>
                  <span style={{
                    color: p.score >= 70 ? "#24a148" : p.score >= 50 ? "#f1c21b" : "#da1e28",
                    fontWeight: 700,
                  }}>{p.score}</span>
                </td>
                <td style={{ padding: "6px 4px", textAlign: "center" }}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 8, fontSize: 9, fontWeight: 700, color: "#fff",
                    background: p.verdict === "GO" ? "#24a148" : p.verdict === "CAUTION" ? "#f1c21b" : "#da1e28",
                  }}>{p.verdict}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CostVarianceChart({ costs, width = 320, height = 150 }) {
  const maxVal = Math.max(...costs.flatMap(c => [c.planned, c.actual]));
  const barW = width / costs.length;
  const gap = 4;
  const innerBarW = (barW - gap * 3) / 2;

  return (
    <svg width={width} height={height + 30} viewBox={`0 0 ${width} ${height + 30}`} style={{ display: "block" }}>
      {costs.map((c, i) => {
        const x = i * barW + gap;
        const pH = (c.planned / maxVal) * height;
        const aH = (c.actual / maxVal) * height;
        const variance = c.actual - c.planned;
        return (
          <g key={c.label}>
            {/* Planned */}
            <rect x={x} y={height - pH} width={innerBarW} height={pH} fill={c.color} opacity={0.3} rx={2} />
            {/* Actual */}
            <rect x={x + innerBarW + 2} y={height - aH} width={innerBarW} height={aH} fill={c.color} opacity={0.85} rx={2} />
            {/* Variance dot */}
            {variance !== 0 && (
              <circle cx={x + barW / 2 - gap / 2} cy={height - aH - 8} r={3}
                fill={variance > 0 ? "#da1e28" : "#24a148"} />
            )}
            {/* Label */}
            <text x={x + barW / 2 - gap / 2} y={height + 14} textAnchor="middle" fill="#888" fontSize={8}>
              {c.label.length > 8 ? c.label.slice(0, 8) + ".." : c.label}
            </text>
          </g>
        );
      })}
      {/* Legend */}
      <rect x={0} y={height + 22} width={8} height={4} fill="#888" opacity={0.3} rx={1} />
      <text x={12} y={height + 27} fill="#888" fontSize={8}>Planned</text>
      <rect x={55} y={height + 22} width={8} height={4} fill="#888" opacity={0.85} rx={1} />
      <text x={67} y={height + 27} fill="#888" fontSize={8}>Actual</text>
    </svg>
  );
}

function RiskMatrix({ risks }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
      {risks.map(r => (
        <div key={r.id} style={{
          padding: "6px 8px", borderRadius: 6,
          background: r.severity >= 3 ? "rgba(218,30,40,0.08)" : r.severity >= 2 ? "rgba(245,158,11,0.08)" : "rgba(36,161,72,0.08)",
          border: `1px solid ${r.severity >= 3 ? "rgba(218,30,40,0.2)" : r.severity >= 2 ? "rgba(245,158,11,0.2)" : "rgba(36,161,72,0.2)"}`,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 10, color: "#ccc", fontWeight: 500 }}>{r.label}</span>
            <span style={{
              fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 6,
              background: r.color, color: "#fff",
            }}>{r.count}</span>
          </div>
          <div style={{ display: "flex", gap: 2, marginTop: 3 }}>
            {[1, 2, 3].map(s => (
              <div key={s} style={{
                flex: 1, height: 3, borderRadius: 2,
                background: s <= r.severity ? r.color : "#1a1f2e",
              }} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function EnergyPerformance({ portfolio }) {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Simulated monthly generation (GWh) — seasonal curve
  const gen = months.map((m, i) => {
    const solar = Math.sin((i + 1) / 12 * Math.PI) * 15 + 3;
    const wind = 25 - Math.sin((i + 1) / 12 * Math.PI) * 8 + Math.random() * 3;
    const bess = 8 + Math.random() * 2;
    return { month: m, solar: +solar.toFixed(1), wind: +wind.toFixed(1), bess: +bess.toFixed(1) };
  });
  const maxVal = Math.max(...gen.map(g => g.solar + g.wind + g.bess));
  const w = 340, h = 110;
  const barW = w / 12;

  return (
    <svg width={w} height={h + 20} viewBox={`0 0 ${w} ${h + 20}`} style={{ display: "block" }}>
      {gen.map((g, i) => {
        const x = i * barW + 2;
        const bW = barW - 4;
        const wH = (g.wind / maxVal) * h;
        const sH = (g.solar / maxVal) * h;
        const bH = (g.bess / maxVal) * h;
        return (
          <g key={g.month}>
            <rect x={x} y={h - wH - sH - bH} width={bW} height={wH} fill="#5b8def" opacity={0.8} rx={1} />
            <rect x={x} y={h - sH - bH} width={bW} height={sH} fill="#f59e0b" opacity={0.8} rx={1} />
            <rect x={x} y={h - bH} width={bW} height={bH} fill="#a78bfa" opacity={0.8} rx={1} />
            <text x={x + bW / 2} y={h + 12} textAnchor="middle" fill="#888" fontSize={8}>{g.month}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Portfolio Dashboard (Home workspace)
   ═══════════════════════════════════════════════════════════════════════════ */

function PortfolioDashboard({ onWorkspaceClick, onCapabilityClick }) {
  const [portfolio] = useState(DEMO_PORTFOLIO);
  const [apiData, setApiData] = useState(null);
  const [diversification, setDiversification] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fetch real portfolio analytics from backend
  useEffect(() => {
    const sites = portfolio.map(p => ({
      name: p.name,
      capacity_mw: p.capacity_mw,
      technology: p.technology === "datacentre" ? "bess" : p.technology === "thermal" ? "solar" : p.technology,
      region: p.region,
    }));
    setLoading(true);
    Promise.all([
      api.sustainability.portfolioSummary(sites),
      api.sustainability.portfolioDiversification(sites),
    ]).then(([summary, divers]) => {
      if (summary) setApiData(summary);
      if (divers) setDiversification(divers);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Use real API data when available, fall back to local calc
  const totalCapacity = apiData?.portfolio?.total_capacity_mw
    ?? portfolio.reduce((s, p) => s + p.capacity_mw, 0);
  const avgScore = Math.round(portfolio.reduce((s, p) => s + p.score, 0) / portfolio.length);
  const operationalMw = portfolio.filter(p => p.status === "operational").reduce((s, p) => s + p.capacity_mw, 0);
  const annualGwh = apiData?.portfolio?.total_annual_gen_mwh
    ? Math.round(apiData.portfolio.total_annual_gen_mwh / 1000)
    : Math.round(totalCapacity * 0.25 * 8760 / 1000);
  const annualRevenue = apiData?.portfolio?.total_annual_revenue_gbp
    ? Math.round(apiData.portfolio.total_annual_revenue_gbp / 1000)
    : Math.round(annualGwh * 48);
  const weightedCF = apiData?.portfolio?.weighted_capacity_factor;
  const irr = apiData?.portfolio?.simple_irr_pct;
  const divBenefit = diversification?.diversification_benefit_pct;

  return (
    <div className="workspace-home">
      <div className="wh-hub pd-dashboard">
        {/* Compact header */}
        <div className="pd-header">
          <div>
            <h1 className="pd-title">Princeps</h1>
            <p className="pd-subtitle">Portfolio Analytics Dashboard</p>
          </div>
          <div className="pd-header-right">
            <span className="pd-date">{new Date().toLocaleDateString("en-GB", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</span>
          </div>
        </div>

        {/* KPI Strip */}
        <div className="pd-kpi-strip">
          <KPICard label="Total Capacity" value={totalCapacity} unit="MW" delta={12} deltaLabel="vs last quarter"
            color="#D4A018" icon="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          <KPICard label="Portfolio Score" value={avgScore} unit="/100" delta={3} deltaLabel="avg improvement"
            color={avgScore >= 70 ? "#24a148" : "#f1c21b"} icon="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          <KPICard label="Annual Generation" value={annualGwh} unit="GWh" delta={8} deltaLabel="forecast"
            color="#f59e0b" icon="M12 3v1m0 16v1m9-9h-1M4 12H3" />
          <KPICard label="Annual Revenue" value={`£${annualRevenue}k`} unit="" delta={5} deltaLabel="vs budget"
            color="#22c55e" icon="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2" />
          <KPICard label={weightedCF ? "Capacity Factor" : "Operational"} value={weightedCF ? `${(weightedCF * 100).toFixed(1)}` : operationalMw} unit={weightedCF ? "%" : "MW"} color="#1890ff"
            icon="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6" />
          <KPICard label={irr ? "Portfolio IRR" : "Projects"} value={irr ? `${irr.toFixed(1)}` : portfolio.length} unit={irr ? "%" : "active"} color="#a78bfa"
            delta={divBenefit ? +divBenefit.toFixed(0) : undefined} deltaLabel={divBenefit ? "diversification" : undefined}
            icon="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6z" />
        </div>

        {/* Main grid */}
        <div className="pd-grid">
          {/* Left column */}
          <div className="pd-col">
            {/* Verdicts */}
            <div className="pd-card">
              <div className="pd-card-title">Portfolio Verdicts</div>
              <VerdictPills portfolio={portfolio} />
            </div>

            {/* Technology Mix */}
            <div className="pd-card">
              <div className="pd-card-title">Technology Mix</div>
              <TechMixDonut portfolio={portfolio} apiTechMix={apiData?.technology_mix} />
            </div>

            {/* Risk Matrix */}
            <div className="pd-card">
              <div className="pd-card-title">Risk Matrix</div>
              <RiskMatrix risks={RISK_CATEGORIES} />
            </div>
          </div>

          {/* Right column */}
          <div className="pd-col pd-col-wide">
            {/* Project Pipeline */}
            <div className="pd-card">
              <div className="pd-card-title">Project Pipeline</div>
              <ProjectPipeline portfolio={portfolio} />
            </div>

            {/* Energy Performance */}
            <div className="pd-card">
              <div className="pd-card-title">Monthly Energy Performance (GWh)</div>
              <EnergyPerformance portfolio={portfolio} />
              <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: "#5b8def" }} />
                  <span style={{ color: "#888" }}>Wind</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: "#f59e0b" }} />
                  <span style={{ color: "#888" }}>Solar</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2, background: "#a78bfa" }} />
                  <span style={{ color: "#888" }}>BESS</span>
                </div>
              </div>
            </div>

            {/* Cost Variance */}
            <div className="pd-card">
              <div className="pd-card-title">Cost Variance (£k)</div>
              <CostVarianceChart costs={COST_CATEGORIES} />
            </div>
          </div>
        </div>

        {/* Workspace nav row */}
        <div className="wh-section" style={{ marginTop: 16 }}>
          <div className="wh-section-label">WORKSPACES</div>
          <div className="wh-ws-grid">
            {WORKSPACES.filter(w => w.id !== "home").map(ws => {
              const wsMeta = WORKSPACE_META[ws.id];
              return (
                <button key={ws.id} className="wh-ws-card" onClick={() => onWorkspaceClick(ws.id)}>
                  <div className="wh-ws-card-icon">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      {ws.icon === "bolt" && <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />}
                      {ws.icon === "sun" && <><circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /></>}
                      {ws.icon === "leaf" && <><path d="M17 8C8 10 5.9 16.17 3.82 21.34l1.89-.75L7 22l-.5-2" /><path d="M17 8c4-1 6 3 6 7-5 0-11 .5-14 5.5" /></>}
                      {ws.icon === "gear" && <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4" /></>}
                      {ws.icon === "briefcase" && <><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16" /></>}
                    </svg>
                  </div>
                  <div className="wh-ws-card-body">
                    <div className="wh-ws-card-title">{wsMeta?.title || ws.label}</div>
                    <div className="wh-ws-card-desc">{wsMeta?.desc || ""}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Quick capabilities */}
        <div className="wh-section">
          <div className="wh-section-label">CAPABILITIES</div>
          <div className="wh-cap-grid">
            {Object.entries(CAPABILITY_CARDS).slice(0, 8).map(([intent, card]) => (
              <button key={intent} className="wh-cap-card" onClick={() => onCapabilityClick(intent)}>
                <div className="wh-cap-icon" style={{ color: card.color }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d={card.icon} />
                  </svg>
                </div>
                <span className="wh-cap-label">{card.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Main export
   ═══════════════════════════════════════════════════════════════════════════ */

export default function WorkspaceHome() {
  const { activeWorkspace, navigateToIntent, setActiveViewMode, setActiveWorkspace } = useWorkspace();
  const { parcelId, samCapacity, samDay, runAgent, workflowResults } = useSite();
  const [search, setSearch] = useState("");

  const intents = WORKSPACE_INTENTS[activeWorkspace] || [];
  const filtered = intents.filter(intent => {
    const card = CAPABILITY_CARDS[intent];
    if (!card) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return card.label.toLowerCase().includes(q) || card.desc.toLowerCase().includes(q);
  });

  const handleCardClick = (intent) => {
    navigateToIntent(intent);
    setActiveViewMode("map");
    if (!workflowResults[intent] && parcelId) {
      runAgent(parcelId, intent, samCapacity, samDay);
    }
  };

  const meta = WORKSPACE_META[activeWorkspace] || WORKSPACE_META.home;

  // HOME workspace — portfolio analytics dashboard
  if (activeWorkspace === "home") {
    return (
      <PortfolioDashboard
        onWorkspaceClick={setActiveWorkspace}
        onCapabilityClick={handleCardClick}
      />
    );
  }

  // Non-home workspace dashboard (unchanged)
  return (
    <div className="workspace-home">
      <div className="wh-hub">
        <div className="wh-ws-header">
          <h2 className="wh-ws-title">{meta.title}</h2>
          <p className="wh-ws-desc">{meta.desc}</p>
        </div>

        <div className="wh-search-wrap">
          <div className="wh-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
            </svg>
            <input
              type="text"
              placeholder="Search capabilities..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="wh-search-input"
            />
          </div>
        </div>

        <div className="wh-cap-grid wh-cap-grid-lg">
          {filtered.map(intent => {
            const card = CAPABILITY_CARDS[intent];
            if (!card) return null;
            const result = workflowResults[intent];
            return (
              <button key={intent} className="wh-card" onClick={() => handleCardClick(intent)}>
                <div className="wh-card-top">
                  <div className="wh-card-icon" style={{ color: card.color }}>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d={card.icon} />
                    </svg>
                  </div>
                  {result?.verdict && (
                    <span className={`wh-card-verdict wh-verdict-${result.verdict.toLowerCase().replace("-","")}`}>
                      {result.verdict}
                    </span>
                  )}
                </div>
                <div className="wh-card-label">{card.label}</div>
                <div className="wh-card-desc">{card.desc}</div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
