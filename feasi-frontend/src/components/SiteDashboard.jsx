import React from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

// ── 9 Data Domain Categories ──
const DATA_DOMAINS = [
  {
    id: "dno",
    name: "DNO Infrastructure",
    desc: "Substations, live export/import capacity, constraint zones, and queue data",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
    dataKey: "gridContext",
  },
  {
    id: "topography",
    name: "Topography",
    desc: "High-resolution slope, elevation, and aspect mapping for terrain modelling",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M8 21l4-10 4 10" /><path d="M2 21l6-14 4 8 4-12 6 18" />
      </svg>
    ),
    dataKey: "slopeStats",
  },
  {
    id: "solar",
    name: "Solar Resource",
    desc: "Solar irradiance data and location-specific generation estimates for yield modelling",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
      </svg>
    ),
    dataKey: "solarYield",
  },
  {
    id: "alc",
    name: "Agricultural Land",
    desc: "ALC grades 1-5 and nationally protected land exclusions",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 22c4-4 8-7.5 8-12a8 8 0 10-16 0c0 4.5 4 8 8 12z" /><circle cx="12" cy="10" r="3" />
      </svg>
    ),
    dataKey: "geeflowData",
  },
  {
    id: "admin",
    name: "Admin. Boundaries",
    desc: "LPAs, parishes, and neighbourhood plan areas",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 3v18" />
      </svg>
    ),
    dataKey: "explain",
  },
  {
    id: "projects",
    name: "Neighbouring Projects",
    desc: "Operational and pending energy developments with status and technology",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
      </svg>
    ),
    dataKey: "planningApps",
  },
  {
    id: "flood",
    name: "Flood Zones",
    desc: "Surface water, river, tidal, and reservoir flood zone data",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 2.69l5.66 5.66a8 8 0 11-11.31 0z" />
      </svg>
    ),
    dataKey: "geeflowData",
  },
  {
    id: "protected",
    name: "Protected Areas",
    desc: "SSSIs, AONBs, Green Belt, and other statutory designations",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
    dataKey: "explain",
  },
  {
    id: "vision",
    name: "Vision AI",
    desc: "AI-analysed satellite, drone, and aerial imagery for ground-truth site validation",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="3" width="20" height="14" rx="2" /><circle cx="12" cy="10" r="3" /><path d="M2 17l4-4 3 3 4-4 9 9" />
      </svg>
    ),
    dataKey: "visionData",
  },
];

// ── Radar chart dimensions ──
const RADAR_AXES = [
  { label: "Solar", key: "solar" },
  { label: "Grid", key: "grid" },
  { label: "Terrain", key: "terrain" },
  { label: "Planning", key: "planning" },
  { label: "Environ.", key: "environmental" },
  { label: "Financial", key: "financial" },
  { label: "Land Use", key: "landuse" },
  { label: "Imagery", key: "imagery" },
];

function computeScores(ctx) {
  const s = {};
  // Solar: capacity factor normalized (UK range 8-14%)
  const cf = ctx.solarYield?.capacity_factor_pct || 0;
  s.solar = Math.min(100, Math.max(0, ((cf - 5) / 10) * 100));
  // Grid: inverse distance (closer = better, max 20km)
  const gd = ctx.gridContext?.nearest_substation?.distance_km;
  s.grid = gd != null ? Math.max(0, (1 - gd / 20) * 100) : 30;
  // Terrain: slope suitability (flatter = better)
  const slope = ctx.slopeStats?.mean_slope_deg;
  s.terrain = slope != null ? Math.max(0, (1 - slope / 30) * 100) : 50;
  // Planning: from explain score
  const sc = ctx.explain?.score_total;
  s.planning = sc != null ? (sc / 120) * 100 : 40;
  // Environmental: base 60, penalize if constraints
  s.environmental = 60;
  // Financial: based on agent confidence if available
  s.financial = ctx.agentResult?.confidence ? ctx.agentResult.confidence * 100 : 50;
  // Land use: GeeFlow data presence
  s.landuse = ctx.geeflowData ? 70 : 40;
  // Imagery: Vision AI suitability score
  s.imagery = ctx.visionData?.suitability_score || 30;
  return s;
}

function RadarChart({ scores, size = 200 }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.38;
  const n = RADAR_AXES.length;

  const getPoint = (i, val) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const dist = (val / 100) * r;
    return [cx + dist * Math.cos(angle), cy + dist * Math.sin(angle)];
  };

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1.0];
  // Axis lines
  const axes = RADAR_AXES.map((_, i) => {
    const [x, y] = getPoint(i, 100);
    return `M${cx},${cy} L${x},${y}`;
  });

  // Data polygon
  const dataPoints = RADAR_AXES.map((a, i) => getPoint(i, scores[a.key] || 0));
  const dataPath = dataPoints.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(" ") + "Z";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="radar-chart">
      {/* Grid rings */}
      {rings.map((pct) => (
        <polygon
          key={pct}
          points={RADAR_AXES.map((_, i) => getPoint(i, pct * 100).join(",")).join(" ")}
          fill="none"
          stroke="var(--cds-border-subtle)"
          strokeWidth="0.5"
          opacity="0.4"
        />
      ))}
      {/* Axis lines */}
      {axes.map((d, i) => (
        <path key={i} d={d} stroke="var(--cds-border-subtle)" strokeWidth="0.5" opacity="0.3" />
      ))}
      {/* Data polygon */}
      <polygon
        points={dataPoints.map(p => p.join(",")).join(" ")}
        fill="rgba(15, 98, 254, 0.15)"
        stroke="var(--cds-interactive)"
        strokeWidth="1.5"
      />
      {/* Data points */}
      {dataPoints.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="3" fill="var(--cds-interactive)" />
      ))}
      {/* Labels */}
      {RADAR_AXES.map((a, i) => {
        const [x, y] = getPoint(i, 120);
        return (
          <text
            key={a.key}
            x={x}
            y={y}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="var(--cds-text-secondary)"
            fontSize="9"
            fontFamily="var(--mono)"
            fontWeight="600"
          >
            {a.label}
          </text>
        );
      })}
    </svg>
  );
}

// ── AI Report types ──
const AI_REPORTS = [
  { id: "feasibility", label: "Feasibility", icon: "chart" },
  { id: "grid_study", label: "Grid Study", icon: "bolt" },
  { id: "financial", label: "Financial", icon: "currency" },
  { id: "environmental", label: "Environmental", icon: "leaf" },
  { id: "satellite_analysis", label: "Satellite", icon: "globe" },
  { id: "planning", label: "Planning", icon: "doc" },
];

function ReportIcon({ type }) {
  const icons = {
    chart: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M18 20V10M12 20V4M6 20v-6" /></svg>,
    bolt: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>,
    currency: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" /></svg>,
    leaf: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M17 8C8 10 5.9 16.17 3.82 21.34l1.89.66L12 14l-2 2c1-2 3-4.5 7-6" /><path d="M2 12s5-2 10-2 10 2 10 2" /></svg>,
    globe: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10" /><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z" /></svg>,
    doc: <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" /></svg>,
  };
  return icons[type] || icons.chart;
}

export default function SiteDashboard({ onClose }) {
  const {
    parcelId, pickedLocation,
    solarYield, gridContext, explain, slopeStats,
    agentResult, agentLoading, geeflowData, planningApps,
    visionData, digitalTwinOpen, setDigitalTwinOpen, setTwinData,
    samCapacity, samDay,
    runAgent, setActiveIntent, setStudySubStep,
    navigateWorkflow,
    workflowResults, workflowSummary, workflowRunning, workflowProgress,
    runWorkflow,
  } = useSite();

  const scores = computeScores({
    solarYield, gridContext, slopeStats, explain, agentResult, geeflowData, visionData,
  });

  const overallScore = Math.round(
    Object.values(scores).reduce((a, b) => a + b, 0) / Object.keys(scores).length
  );

  const verdict = agentResult?.verdict;
  const verdictColor = verdict === "GO" ? "var(--cds-support-success)" :
    verdict === "CAUTION" ? "var(--cds-support-warning)" :
    verdict === "NO-GO" ? "var(--cds-support-error)" : "var(--cds-text-helper)";

  const handleRunReport = (intentId) => {
    setActiveIntent(intentId);
    setStudySubStep(intentId);
    if (parcelId) {
      runAgent(parcelId, intentId, samCapacity, samDay);
    }
    onClose();
  };

  const handleExploreMap = () => {
    onClose();
  };

  // Data availability check
  const hasData = (key) => {
    const ctx = { gridContext, slopeStats, solarYield, geeflowData, explain, planningApps, visionData };
    return !!ctx[key];
  };

  return (
    <div className="site-dashboard-overlay">
      <div className="site-dashboard">
        {/* Header */}
        <div className="sd-header">
          <div className="sd-header-left">
            <h1 className="sd-title">Site Assessment</h1>
            {pickedLocation && (
              <span className="sd-coords">
                {pickedLocation.lat.toFixed(4)}N, {Math.abs(pickedLocation.lon).toFixed(4)}{pickedLocation.lon < 0 ? "W" : "E"}
              </span>
            )}
            {parcelId && <span className="sd-parcel">{parcelId.slice(0, 12)}</span>}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="sd-map-btn" onClick={handleExploreMap}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
                <line x1="8" y1="2" x2="8" y2="18" /><line x1="16" y1="6" x2="16" y2="22" />
              </svg>
              Explore on Map
            </button>
            {parcelId && (
              <button className="sd-map-btn" style={{ background: "rgba(124,77,255,0.15)", borderColor: "#7c4dff50" }}
                onClick={async () => {
                  const data = await api.vision.getTwinData(parcelId, 500);
                  if (data) { setTwinData(data); setDigitalTwinOpen(true); }
                  onClose();
                }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
                </svg>
                3D Twin
              </button>
            )}
          </div>
        </div>

        <div className="sd-body">
          {/* Left column: Radar + score breakdown */}
          <div className="sd-col-left">
            <div className="sd-card sd-overview-card">
              <div className="sd-card-header">
                <span>Overview</span>
                <span className="sd-overall-score" style={{ color: overallScore > 60 ? "var(--cds-support-success)" : overallScore > 40 ? "var(--cds-support-warning)" : "var(--cds-support-error)" }}>
                  {overallScore}%
                </span>
              </div>
              <div className="sd-radar-wrap">
                <RadarChart scores={scores} size={200} />
              </div>
              <div className="sd-score-list">
                {RADAR_AXES.map((a) => {
                  const val = Math.round(scores[a.key] || 0);
                  const color = val > 65 ? "var(--cds-support-success)" : val > 40 ? "var(--cds-support-warning)" : "var(--cds-support-error)";
                  return (
                    <div key={a.key} className="sd-score-row">
                      <span className="sd-score-label">{a.label}</span>
                      <div className="sd-score-bar-bg">
                        <div className="sd-score-bar" style={{ width: `${val}%`, background: color }} />
                      </div>
                      <span className="sd-score-val" style={{ color }}>{val}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Center: KPI cards + Data domains */}
          <div className="sd-col-center">
            {/* KPI Row */}
            <div className="sd-kpi-row">
              <div className="sd-kpi-card">
                <span className="sd-kpi-title">Grid Capacity</span>
                <span className="sd-kpi-big" style={{ color: "var(--cds-interactive)" }}>
                  {gridContext?.nearest_substation?.distance_km ? `${gridContext.nearest_substation.distance_km.toFixed(1)}km` : "--"}
                </span>
                <span className="sd-kpi-badge" style={{ background: scores.grid > 60 ? "var(--cds-support-success)" : "var(--cds-support-warning)" }}>
                  {scores.grid > 60 ? "GOOD" : "MODERATE"}
                </span>
              </div>
              <div className="sd-kpi-card">
                <span className="sd-kpi-title">Solar Yield</span>
                <span className="sd-kpi-big" style={{ color: "var(--cds-support-warning)" }}>
                  {solarYield?.capacity_factor_pct ? `${solarYield.capacity_factor_pct.toFixed(1)}%` : "--"}
                </span>
                <span className="sd-kpi-badge" style={{ background: scores.solar > 60 ? "var(--cds-support-success)" : "var(--cds-support-warning)" }}>
                  {scores.solar > 60 ? "GOOD" : "MODERATE"}
                </span>
              </div>
              <div className="sd-kpi-card">
                <span className="sd-kpi-title">Verdict</span>
                <span className="sd-kpi-big" style={{ color: verdictColor }}>
                  {verdict || (agentLoading ? "..." : "--")}
                </span>
                {agentResult?.confidence && (
                  <span className="sd-kpi-sub">{Math.round(agentResult.confidence * 100)}% confidence</span>
                )}
              </div>
            </div>

            {/* Data Domains Grid */}
            <div className="sd-section-label">Data Layers</div>
            <div className="sd-domains-grid">
              {DATA_DOMAINS.map((d) => {
                const available = hasData(d.dataKey);
                return (
                  <div key={d.id} className={`sd-domain-card${available ? " available" : ""}`}>
                    <div className="sd-domain-icon">{d.icon}</div>
                    <div className="sd-domain-name">{d.name}</div>
                    <div className="sd-domain-desc">{d.desc}</div>
                    <div className={`sd-domain-status${available ? " on" : ""}`}>
                      {available ? "Available" : "Pending"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right column: AI Reports + Agent summary */}
          <div className="sd-col-right">
            {/* Agent verdict card */}
            {agentResult && (
              <div className="sd-card sd-verdict-card">
                <div className="sd-verdict-badge" style={{ background: verdictColor }}>
                  {agentResult.verdict}
                </div>
                <p className="sd-verdict-summary">{agentResult.summary}</p>
                {agentResult.risks?.length > 0 && (
                  <div className="sd-verdict-section">
                    <span className="sd-verdict-section-title risk">Risks</span>
                    <ul>{agentResult.risks.slice(0, 3).map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}
                {agentResult.opportunities?.length > 0 && (
                  <div className="sd-verdict-section">
                    <span className="sd-verdict-section-title opp">Opportunities</span>
                    <ul>{agentResult.opportunities.slice(0, 3).map((o, i) => <li key={i}>{o}</li>)}</ul>
                  </div>
                )}
              </div>
            )}

            {/* Workflow launchers */}
            <div className="sd-card">
              <div className="sd-card-header">Automated Workflows</div>
              <div className="sd-workflow-btns">
                {[
                  { preset: "full_feasibility", label: "Full Feasibility", desc: "7-step comprehensive assessment", color: "#24a148" },
                  { preset: "grid_deep_dive", label: "Grid Deep Dive", desc: "Grid + BESS + financial", color: "#0f62fe" },
                  { preset: "investment_ready", label: "Investment Ready", desc: "Due-diligence package", color: "#a56eff" },
                ].map((wf) => {
                  const isRunning = workflowRunning && workflowProgress?.preset === wf.preset;
                  return (
                    <button
                      key={wf.preset}
                      className={`sd-workflow-btn${isRunning ? " running" : ""}`}
                      style={{ borderColor: wf.color }}
                      disabled={!parcelId || workflowRunning}
                      onClick={() => { runWorkflow(parcelId, wf.preset, samCapacity, samDay); onClose(); }}
                    >
                      <span className="sd-wf-dot" style={{ background: wf.color }} />
                      <div>
                        <div className="sd-wf-label">{wf.label}</div>
                        <div className="sd-wf-desc">
                          {isRunning ? `Step ${workflowProgress.step}/${workflowProgress.total}...` : wf.desc}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Workflow summary if available */}
              {workflowSummary && !workflowRunning && (
                <div className="sd-wf-summary">
                  <span className="sd-wf-summary-verdict" style={{
                    color: workflowSummary.overall_verdict === "GO" ? "#24a148" :
                      workflowSummary.overall_verdict === "CAUTION" ? "#f1c21b" : "#da1e28"
                  }}>
                    {workflowSummary.overall_verdict}
                  </span>
                  <span className="sd-wf-summary-meta">
                    {Math.round(workflowSummary.average_confidence * 100)}% avg | {workflowSummary.steps_completed} steps
                  </span>
                </div>
              )}
            </div>

            {/* AI Reports (single intent) */}
            <div className="sd-card">
              <div className="sd-card-header">Single Analysis</div>
              <div className="sd-reports-grid">
                {AI_REPORTS.map((rpt) => (
                  <button
                    key={rpt.id}
                    className="sd-report-btn"
                    onClick={() => handleRunReport(rpt.id)}
                  >
                    <div className="sd-report-icon">
                      <ReportIcon type={rpt.icon} />
                    </div>
                    <span className="sd-report-label">{rpt.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Quick stats */}
            <div className="sd-card sd-stats-card">
              <div className="sd-card-header">Quick Stats</div>
              <div className="sd-stat-row">
                <span>Annual Energy</span>
                <strong>{solarYield?.annual_energy_kwh ? `${(solarYield.annual_energy_kwh / 1000).toFixed(1)} MWh` : "--"}</strong>
              </div>
              <div className="sd-stat-row">
                <span>Site Score</span>
                <strong>{explain?.score_total ? `${explain.score_total}/120` : "--"}</strong>
              </div>
              <div className="sd-stat-row">
                <span>Mean Slope</span>
                <strong>{slopeStats?.mean_slope_deg ? `${slopeStats.mean_slope_deg.toFixed(1)}\u00B0` : "--"}</strong>
              </div>
              <div className="sd-stat-row">
                <span>Planning Apps</span>
                <strong>{planningApps?.total ?? "--"}</strong>
              </div>
              <div className="sd-stat-row">
                <span>Capacity</span>
                <strong>{samCapacity} kW</strong>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
