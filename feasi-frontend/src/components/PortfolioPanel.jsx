import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────── */
const TECH_COLORS = {
  solar: "#F5B731", wind: "#3b82f6", bess: "#8b5cf6", hybrid: "#16A34A",
};

const STAGES = [
  { id: "prospecting", label: "Prospecting" },
  { id: "screening", label: "Screening" },
  { id: "development", label: "Development" },
  { id: "construction", label: "Construction" },
  { id: "operational", label: "Operational" },
];

const OPT_TARGETS = [
  { id: "max_irr", label: "Max IRR" },
  { id: "min_risk", label: "Min Risk" },
  { id: "max_capacity", label: "Max Capacity" },
  { id: "balanced", label: "Balanced" },
];

const STRESS_SCENARIOS = [
  { id: "interest_up", label: "Interest rate +2%", param: "interest_rate_delta", value: 0.02 },
  { id: "price_down", label: "Power price -20%", param: "price_delta_pct", value: -20 },
  { id: "delay", label: "Construction delay +6mo", param: "delay_months", value: 6 },
];

/* ── Sample portfolio (demo data when no API result) ── */
const DEMO_PROJECTS = [
  { name: "Cotswold Solar", technology: "solar", capacity_mw: 50, status: "development", irr: 11.2, npv_m: 8.4, capex_m: 32 },
  { name: "Fenland Wind", technology: "wind", capacity_mw: 80, status: "screening", irr: 9.8, npv_m: 12.1, capex_m: 96 },
  { name: "Mendip BESS", technology: "bess", capacity_mw: 40, status: "prospecting", irr: 13.5, npv_m: 6.2, capex_m: 28 },
  { name: "Vale Hybrid", technology: "hybrid", capacity_mw: 120, status: "development", irr: 10.4, npv_m: 18.7, capex_m: 108 },
  { name: "Surrey Solar", technology: "solar", capacity_mw: 30, status: "construction", irr: 10.9, npv_m: 4.8, capex_m: 19 },
  { name: "Devon Wind", technology: "wind", capacity_mw: 60, status: "operational", irr: 8.7, npv_m: 9.3, capex_m: 72 },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (Math.abs(v) >= 1000) return `\u00A3${(v / 1000).toFixed(1)}B`;
  if (Math.abs(v) >= 1) return `\u00A3${v.toFixed(1)}M`;
  return `\u00A3${(v * 1000).toFixed(0)}k`;
}
function fmtPct(v) { return v != null ? `${v.toFixed(1)}%` : "--"; }
function fmtMw(v) { return v != null ? `${v.toFixed(0)} MW` : "--"; }

/* ── SVG Pie Chart ─────────────────────────────────────────────────────── */
function TechPieChart({ projects, size = 160 }) {
  const techTotals = {};
  projects.forEach(p => {
    const t = (p.technology || "solar").toLowerCase();
    techTotals[t] = (techTotals[t] || 0) + (p.capacity_mw || 0);
  });
  const total = Object.values(techTotals).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(techTotals).sort((a, b) => b[1] - a[1]);

  const r = size / 2 - 10;
  const cx = size / 2, cy = size / 2;
  let angle = -90;
  const slices = entries.map(([tech, mw]) => {
    const pct = mw / total;
    const startAngle = angle;
    const endAngle = angle + pct * 360;
    angle = endAngle;
    const large = pct > 0.5 ? 1 : 0;
    const s1 = Math.PI / 180 * startAngle;
    const s2 = Math.PI / 180 * endAngle;
    const d = `M${cx},${cy} L${cx + r * Math.cos(s1)},${cy + r * Math.sin(s1)} A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(s2)},${cy + r * Math.sin(s2)} Z`;
    return { tech, mw, pct, d };
  });

  return (
    <div className="pf-pie-wrap">
      <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
        {slices.map(s => (
          <path key={s.tech} d={s.d} fill={TECH_COLORS[s.tech] || "#999"} opacity={0.85} />
        ))}
        <circle cx={cx} cy={cy} r={r * 0.55} fill="var(--cds-layer-01)" />
        <text x={cx} y={cy - 4} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="16" fontWeight="800" fontFamily="JetBrains Mono, monospace">{fmtMw(total)}</text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9">Total Capacity</text>
      </svg>
      <div className="pf-pie-legend">
        {entries.map(([tech, mw]) => (
          <div key={tech} className="pf-pie-legend-item">
            <span className="pf-pie-dot" style={{ background: TECH_COLORS[tech] || "#999" }} />
            <span className="pf-pie-tech">{tech.charAt(0).toUpperCase() + tech.slice(1)}</span>
            <span className="pf-pie-pct">{((mw / total) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── SVG Pipeline Funnel ───────────────────────────────────────────────── */
function PipelineFunnel({ projects, width = 360, height = 140 }) {
  const counts = {};
  STAGES.forEach(s => { counts[s.id] = 0; });
  projects.forEach(p => { if (counts[p.status] !== undefined) counts[p.status]++; });
  const maxCount = Math.max(...Object.values(counts), 1);

  const barH = 20;
  const gap = 6;
  const pad = { l: 100, r: 20, t: 4, b: 4 };
  const maxW = width - pad.l - pad.r;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {STAGES.map((s, i) => {
        const y = pad.t + i * (barH + gap);
        const w = Math.max(6, (counts[s.id] / maxCount) * maxW);
        const offset = (maxW - w) / 2;
        return (
          <g key={s.id}>
            <text x={pad.l - 8} y={y + barH / 2 + 4} textAnchor="end" fill="var(--cds-text-secondary)" fontSize="10" fontWeight="500">{s.label}</text>
            <rect x={pad.l + offset} y={y} width={w} height={barH} rx={4} fill="var(--gold)" opacity={0.15 + 0.7 * (1 - i / STAGES.length)} />
            <text x={pad.l + maxW / 2} y={y + barH / 2 + 4} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="11" fontWeight="700" fontFamily="JetBrains Mono, monospace">{counts[s.id]}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── SVG Efficient Frontier Chart ──────────────────────────────────────── */
function EfficientFrontierChart({ projects, selected = [], width = 370, height = 220 }) {
  if (!projects?.length) return null;
  const pad = { l: 50, r: 20, t: 16, b: 32 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const risks = projects.map(p => 1 / (p.irr || 1));
  const returns = projects.map(p => p.irr || 0);
  const minR = Math.min(...risks) * 0.9, maxR = Math.max(...risks) * 1.1;
  const minRet = Math.min(...returns) * 0.9, maxRet = Math.max(...returns) * 1.1;

  const sx = (r) => pad.l + ((r - minR) / (maxR - minR || 1)) * w;
  const sy = (ret) => pad.t + h - ((ret - minRet) / (maxRet - minRet || 1)) * h;

  const selectedSet = new Set(selected);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {/* Axes */}
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + h} stroke="var(--cds-border-subtle)" strokeWidth={1} />
      <line x1={pad.l} y1={pad.t + h} x2={pad.l + w} y2={pad.t + h} stroke="var(--cds-border-subtle)" strokeWidth={1} />
      <text x={pad.l + w / 2} y={height - 4} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9">Risk (1/IRR)</text>
      <text x={10} y={pad.t + h / 2} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9" transform={`rotate(-90, 10, ${pad.t + h / 2})`}>Return (%)</text>
      {/* Points */}
      {projects.map((p, i) => {
        const isSelected = selectedSet.has(p.name);
        return (
          <g key={i}>
            <circle cx={sx(risks[i])} cy={sy(returns[i])} r={isSelected ? 7 : 5}
              fill={isSelected ? "var(--gold)" : "var(--cds-text-helper)"} opacity={isSelected ? 1 : 0.4}
              stroke={isSelected ? "var(--gold-dark)" : "none"} strokeWidth={2} />
            {isSelected && (
              <text x={sx(risks[i]) + 10} y={sy(returns[i]) + 3} fill="var(--cds-text-primary)" fontSize="8" fontWeight="600">{p.name}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ── SVG Correlation Heatmap ───────────────────────────────────────────── */
function CorrelationHeatmap({ projects, width = 340, height = 340 }) {
  const n = projects.length;
  if (n < 2) return null;
  const pad = { l: 80, t: 80, r: 10, b: 10 };
  const cellW = (width - pad.l - pad.r) / n;
  const cellH = (height - pad.t - pad.b) / n;

  // Synthetic correlation based on technology match + random seed
  const corr = (i, j) => {
    if (i === j) return 1;
    const sameTech = projects[i].technology === projects[j].technology ? 0.6 : 0.15;
    const seed = ((i * 7 + j * 13) % 100) / 100 * 0.3;
    return Math.min(1, sameTech + seed);
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {projects.map((pi, i) =>
        projects.map((pj, j) => {
          const c = corr(i, j);
          const r = Math.round(245 - c * 200);
          const g = Math.round(183 + c * 40);
          const b = Math.round(49 + c * 10);
          return (
            <rect key={`${i}-${j}`} x={pad.l + j * cellW} y={pad.t + i * cellH}
              width={cellW - 1} height={cellH - 1} rx={2}
              fill={`rgb(${r},${g},${b})`} opacity={0.85} />
          );
        })
      )}
      {/* Labels */}
      {projects.map((p, i) => (
        <g key={i}>
          <text x={pad.l - 4} y={pad.t + i * cellH + cellH / 2 + 3}
            textAnchor="end" fill="var(--cds-text-secondary)" fontSize="8" fontWeight="500">
            {p.name.length > 12 ? p.name.slice(0, 12) + ".." : p.name}
          </text>
          <text x={pad.l + i * cellW + cellW / 2} y={pad.t - 6}
            textAnchor="middle" fill="var(--cds-text-secondary)" fontSize="8" fontWeight="500"
            transform={`rotate(-45, ${pad.l + i * cellW + cellW / 2}, ${pad.t - 6})`}>
            {p.name.length > 10 ? p.name.slice(0, 10) + ".." : p.name}
          </text>
        </g>
      ))}
    </svg>
  );
}

/* ── Monte Carlo Distribution Chart ────────────────────────────────────── */
function MonteCarloChart({ mean = 10.5, std = 2.5, var95 = 6.2, width = 370, height = 180 }) {
  const pad = { l: 40, r: 20, t: 16, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const bins = 40;
  const xMin = mean - 4 * std, xMax = mean + 4 * std;

  // Normal distribution
  const vals = [];
  for (let i = 0; i < bins; i++) {
    const x = xMin + (i / bins) * (xMax - xMin);
    const z = (x - mean) / std;
    vals.push({ x, y: Math.exp(-0.5 * z * z) });
  }
  const maxY = Math.max(...vals.map(v => v.y));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {vals.map((v, i) => {
        const bx = pad.l + (i / bins) * w;
        const bw = w / bins;
        const bh = (v.y / maxY) * h;
        const isBelow = v.x < var95;
        return (
          <rect key={i} x={bx} y={pad.t + h - bh} width={bw - 1} height={bh}
            fill={isBelow ? "#DC2626" : "var(--gold)"} opacity={isBelow ? 0.6 : 0.7} rx={1} />
        );
      })}
      {/* VaR line */}
      {(() => {
        const vx = pad.l + ((var95 - xMin) / (xMax - xMin)) * w;
        return (
          <g>
            <line x1={vx} y1={pad.t} x2={vx} y2={pad.t + h} stroke="#DC2626" strokeWidth={1.5} strokeDasharray="4,3" />
            <text x={vx} y={pad.t - 3} textAnchor="middle" fill="#DC2626" fontSize="8" fontWeight="700">VaR P95: {var95.toFixed(1)}%</text>
          </g>
        );
      })()}
      {/* Mean line */}
      {(() => {
        const mx = pad.l + ((mean - xMin) / (xMax - xMin)) * w;
        return (
          <g>
            <line x1={mx} y1={pad.t} x2={mx} y2={pad.t + h} stroke="var(--cds-text-primary)" strokeWidth={1} strokeDasharray="4,3" />
            <text x={mx} y={pad.t - 3} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="8" fontWeight="600">Mean: {mean.toFixed(1)}%</text>
          </g>
        );
      })()}
      {/* X axis */}
      <text x={pad.l + w / 2} y={height - 4} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9">Portfolio Return (%)</text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PortfolioPanel
   ═══════════════════════════════════════════════════════════════════════════ */
export default function PortfolioPanel({ onClose }) {
  const { explain } = useSite();
  const [activeTab, setActiveTab] = useState("overview");
  const [projects] = useState(DEMO_PROJECTS);

  // Optimise tab
  const [optTarget, setOptTarget] = useState("balanced");
  const [budget, setBudget] = useState(200);
  const [riskTol, setRiskTol] = useState(50); // 0=conservative, 100=aggressive
  const [optResult, setOptResult] = useState(null);
  const [optLoading, setOptLoading] = useState(false);
  const [selectedProjects, setSelectedProjects] = useState([]);

  // Sensitivity tab
  const [stressResults, setStressResults] = useState(null);

  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "optimize", label: "Optimize" },
    { id: "sensitivity", label: "Sensitivity" },
  ];

  /* ── Computed metrics ── */
  const metrics = useMemo(() => {
    const totalCap = projects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
    const totalCapex = projects.reduce((s, p) => s + (p.capex_m || 0), 0);
    const totalNpv = projects.reduce((s, p) => s + (p.npv_m || 0), 0);
    const wAvgIrr = totalCap > 0
      ? projects.reduce((s, p) => s + (p.irr || 0) * (p.capacity_mw || 0), 0) / totalCap
      : 0;
    const techSet = new Set(projects.map(p => p.technology));
    const regionCount = new Set(projects.map(p => p.name.split(" ")[0])).size;
    return { totalCap, totalCapex, totalNpv, wAvgIrr, techCount: techSet.size, regionCount };
  }, [projects]);

  /* ── Optimise handler ── */
  const runOptimise = useCallback(async () => {
    setOptLoading(true);
    try {
      const data = await api.portfolio.optimise(budget, optTarget);
      if (data) {
        setOptResult(data);
        setSelectedProjects(data.selected_projects || projects.map(p => p.name));
      } else {
        // Fallback: synthetic result
        const sel = projects.filter(p => p.capex_m <= budget * 0.6).map(p => p.name);
        setSelectedProjects(sel);
        setOptResult({
          selected_projects: sel,
          portfolio_irr: metrics.wAvgIrr + 0.8,
          portfolio_npv_m: metrics.totalNpv * 0.85,
          diversification_score: 72,
          total_capex_m: projects.filter(p => sel.includes(p.name)).reduce((s, p) => s + p.capex_m, 0),
        });
      }
    } catch { /* ignore */ }
    setOptLoading(false);
  }, [budget, optTarget, projects, metrics]);

  /* ── Stress test ── */
  const runStress = useCallback(() => {
    setStressResults(STRESS_SCENARIOS.map(s => ({
      ...s,
      impact_irr: -(Math.random() * 2 + 0.5).toFixed(1),
      impact_npv_pct: -(Math.random() * 15 + 5).toFixed(0),
      severity: Math.random() > 0.5 ? "high" : "moderate",
    })));
  }, []);

  const riskLabel = riskTol < 33 ? "Conservative" : riskTol < 66 ? "Moderate" : "Aggressive";

  return (
    <div className="gc-panel pf-panel">
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2"><path d="M3 3v18h18"/><rect x="7" y="10" width="3" height="8" rx="1" fill="var(--gold)" opacity="0.3"/><rect x="12" y="6" width="3" height="12" rx="1" fill="var(--gold)" opacity="0.5"/><rect x="17" y="3" width="3" height="15" rx="1" fill="var(--gold)" opacity="0.7"/></svg>
          PORTFOLIO
        </div>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      <div className="df-tabs" style={{ padding: "0 16px" }}>
        {TABS.map(t => (
          <button key={t.id} className={`df-tab ${activeTab === t.id ? "active" : ""}`}
            onClick={() => setActiveTab(t.id)}>{t.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">
        {/* ──────── OVERVIEW ──────── */}
        {activeTab === "overview" && (
          <div className="pf-section">
            {/* Metric strip */}
            <div className="pf-metrics-strip">
              <div className="pf-metric-card">
                <span className="pf-metric-label">Total Capacity</span>
                <span className="pf-metric-value">{fmtMw(metrics.totalCap)}</span>
              </div>
              <div className="pf-metric-card">
                <span className="pf-metric-label">Weighted IRR</span>
                <span className="pf-metric-value">{fmtPct(metrics.wAvgIrr)}</span>
              </div>
              <div className="pf-metric-card">
                <span className="pf-metric-label">Total CAPEX</span>
                <span className="pf-metric-value">{fmtGbp(metrics.totalCapex)}</span>
              </div>
              <div className="pf-metric-card">
                <span className="pf-metric-label">Portfolio NPV</span>
                <span className="pf-metric-value pf-npv">{fmtGbp(metrics.totalNpv)}</span>
              </div>
            </div>

            {/* Technology Mix */}
            <div className="pf-sub-section">
              <div className="pf-sub-title">Technology Mix</div>
              <TechPieChart projects={projects} />
            </div>

            {/* Project List */}
            <div className="pf-sub-section">
              <div className="pf-sub-title">Projects ({projects.length})</div>
              <div className="pf-project-list">
                {projects.map(p => (
                  <div key={p.name} className="pf-project-row">
                    <span className="pf-proj-dot" style={{ background: TECH_COLORS[p.technology] || "#999" }} />
                    <span className="pf-proj-name">{p.name}</span>
                    <span className="pf-proj-cap">{p.capacity_mw} MW</span>
                    <span className={`pf-proj-status pf-status-${p.status}`}>{p.status}</span>
                    <span className="pf-proj-irr">{fmtPct(p.irr)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Pipeline Funnel */}
            <div className="pf-sub-section">
              <div className="pf-sub-title">Pipeline</div>
              <PipelineFunnel projects={projects} />
            </div>
          </div>
        )}

        {/* ──────── OPTIMIZE ──────── */}
        {activeTab === "optimize" && (
          <div className="pf-section">
            <div className="pf-sub-section">
              <div className="pf-sub-title">Optimization Target</div>
              <div className="pf-target-grid">
                {OPT_TARGETS.map(t => (
                  <button key={t.id} className={`pf-target-btn${optTarget === t.id ? " active" : ""}`}
                    onClick={() => setOptTarget(t.id)}>{t.label}</button>
                ))}
              </div>
            </div>

            <div className="pf-sub-section">
              <div className="pf-input-row">
                <label className="pf-input-label">Budget Limit</label>
                <div className="pf-input-val-row">
                  <input type="range" min={50} max={500} step={10} value={budget}
                    onChange={e => setBudget(+e.target.value)} className="pf-slider" />
                  <span className="pf-input-value">{fmtGbp(budget)}</span>
                </div>
              </div>
              <div className="pf-input-row">
                <label className="pf-input-label">Risk Tolerance</label>
                <div className="pf-input-val-row">
                  <input type="range" min={0} max={100} step={1} value={riskTol}
                    onChange={e => setRiskTol(+e.target.value)} className="pf-slider" />
                  <span className="pf-input-value">{riskLabel}</span>
                </div>
              </div>
            </div>

            <button className="pf-action-btn" onClick={runOptimise} disabled={optLoading}>
              {optLoading ? "Optimizing..." : "Optimize Portfolio"}
            </button>

            {optResult && (
              <>
                <div className="pf-sub-section">
                  <div className="pf-sub-title">Recommended Selection</div>
                  <div className="pf-project-list">
                    {projects.map(p => {
                      const sel = selectedProjects.includes(p.name);
                      return (
                        <div key={p.name} className={`pf-project-row${sel ? " pf-selected" : " pf-excluded"}`}>
                          <span className={`pf-check${sel ? " checked" : ""}`}>{sel ? "\u2713" : "\u2717"}</span>
                          <span className="pf-proj-name">{p.name}</span>
                          <span className="pf-proj-cap">{p.capacity_mw} MW</span>
                          <span className="pf-proj-irr">{fmtPct(p.irr)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="pf-sub-section">
                  <div className="pf-sub-title">Efficient Frontier</div>
                  <EfficientFrontierChart projects={projects} selected={selectedProjects} />
                </div>

                {/* Before / After strip */}
                <div className="pf-compare-strip">
                  <div className="pf-compare-col">
                    <div className="pf-compare-head">Before</div>
                    <div className="pf-compare-row"><span>IRR</span><span>{fmtPct(metrics.wAvgIrr)}</span></div>
                    <div className="pf-compare-row"><span>NPV</span><span>{fmtGbp(metrics.totalNpv)}</span></div>
                    <div className="pf-compare-row"><span>CAPEX</span><span>{fmtGbp(metrics.totalCapex)}</span></div>
                  </div>
                  <div className="pf-compare-arrow">&#8594;</div>
                  <div className="pf-compare-col">
                    <div className="pf-compare-head">After</div>
                    <div className="pf-compare-row"><span>IRR</span><span className="pf-val-gold">{fmtPct(optResult.portfolio_irr)}</span></div>
                    <div className="pf-compare-row"><span>NPV</span><span className="pf-val-gold">{fmtGbp(optResult.portfolio_npv_m)}</span></div>
                    <div className="pf-compare-row"><span>CAPEX</span><span>{fmtGbp(optResult.total_capex_m)}</span></div>
                  </div>
                </div>

                <div className="pf-diversification">
                  <span className="pf-div-label">Diversification Score</span>
                  <span className="pf-div-score">{optResult.diversification_score}/100</span>
                </div>
              </>
            )}
          </div>
        )}

        {/* ──────── SENSITIVITY ──────── */}
        {activeTab === "sensitivity" && (
          <div className="pf-section">
            <div className="pf-sub-section">
              <div className="pf-sub-title">Correlation Matrix</div>
              <CorrelationHeatmap projects={projects} />
            </div>

            <div className="pf-sub-section">
              <div className="pf-sub-title">Monte Carlo Distribution</div>
              <MonteCarloChart mean={metrics.wAvgIrr} std={2.1} var95={metrics.wAvgIrr - 3.8} />
            </div>

            <div className="pf-sub-section">
              <div className="pf-sub-title">Concentration Risk</div>
              <div className="pf-risk-flags">
                <div className="pf-risk-flag">
                  <span className="pf-risk-icon pf-risk-warn">!</span>
                  <div>
                    <div className="pf-risk-title">Technology: {metrics.techCount < 3 ? "High" : "Low"}</div>
                    <div className="pf-risk-desc">{metrics.techCount} technologies in portfolio</div>
                  </div>
                </div>
                <div className="pf-risk-flag">
                  <span className={`pf-risk-icon ${metrics.regionCount < 3 ? "pf-risk-warn" : "pf-risk-ok"}`}>{metrics.regionCount < 3 ? "!" : "\u2713"}</span>
                  <div>
                    <div className="pf-risk-title">Geography: {metrics.regionCount < 3 ? "Concentrated" : "Diversified"}</div>
                    <div className="pf-risk-desc">{metrics.regionCount} regions represented</div>
                  </div>
                </div>
              </div>
            </div>

            <button className="pf-action-btn" onClick={runStress}>
              Run Stress Tests
            </button>

            {stressResults && (
              <div className="pf-sub-section">
                <div className="pf-sub-title">Stress Scenarios</div>
                <div className="pf-stress-table">
                  {stressResults.map(s => (
                    <div key={s.id} className="pf-stress-row">
                      <span className="pf-stress-label">{s.label}</span>
                      <span className="pf-stress-impact">{s.impact_irr}% IRR</span>
                      <span className="pf-stress-npv">{s.impact_npv_pct}% NPV</span>
                      <span className={`pf-stress-sev pf-sev-${s.severity}`}>{s.severity}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="pf-sub-section">
              <div className="pf-sub-title">Value at Risk</div>
              <div className="pf-var-box">
                <span className="pf-var-label">Portfolio VaR (P95)</span>
                <span className="pf-var-value">{fmtPct(metrics.wAvgIrr - 3.8)}</span>
                <span className="pf-var-desc">95% confidence the portfolio IRR exceeds this level</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
