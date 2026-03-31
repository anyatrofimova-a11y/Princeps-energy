import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────── */
const TECH_PHASES = {
  solar: [
    { id: "site_prep", label: "Site Preparation", weeks: 4, depends: [] },
    { id: "piling", label: "Piling", weeks: 6, depends: ["site_prep"] },
    { id: "racking", label: "Racking & Mounting", weeks: 5, depends: ["piling"] },
    { id: "module_install", label: "Module Installation", weeks: 8, depends: ["racking"] },
    { id: "electrical", label: "Electrical Works", weeks: 6, depends: ["module_install"] },
    { id: "commissioning", label: "Commissioning", weeks: 3, depends: ["electrical"] },
  ],
  bess: [
    { id: "site_prep", label: "Site Preparation", weeks: 3, depends: [] },
    { id: "foundations", label: "Foundations", weeks: 5, depends: ["site_prep"] },
    { id: "container_delivery", label: "Container Delivery", weeks: 4, depends: ["foundations"] },
    { id: "electrical", label: "Electrical Works", weeks: 6, depends: ["container_delivery"] },
    { id: "grid_connection", label: "Grid Connection", weeks: 8, depends: ["electrical"] },
    { id: "commissioning", label: "Commissioning", weeks: 4, depends: ["grid_connection"] },
  ],
  wind: [
    { id: "site_prep", label: "Site Preparation", weeks: 5, depends: [] },
    { id: "foundations", label: "Foundations", weeks: 10, depends: ["site_prep"] },
    { id: "tower_erection", label: "Tower Erection", weeks: 6, depends: ["foundations"] },
    { id: "turbine_install", label: "Turbine Installation", weeks: 8, depends: ["tower_erection"] },
    { id: "electrical", label: "Electrical Works", weeks: 6, depends: ["turbine_install"] },
    { id: "commissioning", label: "Commissioning", weeks: 4, depends: ["electrical"] },
  ],
};

const MILESTONES = [
  { id: "planning_approval", label: "Planning Approval", week_offset: -8, color: "#3b82f6" },
  { id: "fid", label: "FID", week_offset: 0, color: "var(--gold)" },
  { id: "grid_energisation", label: "Grid Energisation", phase: "electrical", position: "end", color: "#16A34A" },
  { id: "cod", label: "COD", phase: "commissioning", position: "end", color: "#16A34A" },
];

const RISK_FLAGS = [
  { id: "weather", label: "Weather Delays", desc: "Seasonal restrictions on ground works (Nov-Mar)", severity: "moderate" },
  { id: "supply_chain", label: "Supply Chain", desc: "Component lead times (transformers 26-52 weeks)", severity: "high" },
  { id: "permitting", label: "Permitting", desc: "Pre-construction discharge conditions", severity: "low" },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function addWeeks(date, weeks) {
  const d = new Date(date);
  d.setDate(d.getDate() + weeks * 7);
  return d;
}
function fmtDate(d) {
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
}

/* ── SVG Gantt Chart ───────────────────────────────────────────────────── */
function GanttChart({ phases, startDate, milestones = [], width = 390, criticalPath = true }) {
  if (!phases?.length) return null;

  // Compute schedule
  const schedule = [];
  const endWeeks = {};
  phases.forEach(p => {
    let startWeek = 0;
    p.depends.forEach(dep => {
      if (endWeeks[dep] != null && endWeeks[dep] > startWeek) startWeek = endWeeks[dep];
    });
    const endWeek = startWeek + p.weeks;
    endWeeks[p.id] = endWeek;
    schedule.push({ ...p, startWeek, endWeek });
  });

  const totalWeeks = Math.max(...schedule.map(s => s.endWeek), 1);
  const rowH = 28;
  const gap = 4;
  const pad = { l: 140, r: 20, t: 30, b: 20 };
  const chartW = width - pad.l - pad.r;
  const height = pad.t + schedule.length * (rowH + gap) + pad.b + 30;

  // Critical path: phases on the longest path
  const critPhases = new Set();
  if (criticalPath) {
    let current = schedule[schedule.length - 1];
    critPhases.add(current.id);
    while (current.depends.length > 0) {
      const dep = current.depends.reduce((best, d) => {
        const s = schedule.find(x => x.id === d);
        return s && s.endWeek > (best?.endWeek || 0) ? s : best;
      }, null);
      if (dep) { critPhases.add(dep.id); current = dep; } else break;
    }
  }

  // Milestone positions
  const milestonePts = milestones.map(m => {
    let week;
    if (m.week_offset != null) week = m.week_offset;
    else if (m.phase) {
      const s = schedule.find(p => p.id === m.phase);
      week = s ? (m.position === "end" ? s.endWeek : s.startWeek) : 0;
    }
    return { ...m, week };
  }).filter(m => m.week != null);

  // Month markers
  const monthMarkers = [];
  for (let w = 0; w <= totalWeeks; w += 4) {
    monthMarkers.push(w);
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {/* Month grid */}
      {monthMarkers.map(w => {
        const x = pad.l + (w / totalWeeks) * chartW;
        return (
          <g key={w}>
            <line x1={x} y1={pad.t - 10} x2={x} y2={height - pad.b} stroke="var(--cds-border-subtle)" strokeWidth={0.5} />
            <text x={x} y={pad.t - 14} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="7">
              {fmtDate(addWeeks(startDate, w))}
            </text>
          </g>
        );
      })}

      {/* Phase bars */}
      {schedule.map((s, i) => {
        const y = pad.t + i * (rowH + gap);
        const x = pad.l + (s.startWeek / totalWeeks) * chartW;
        const w = (s.weeks / totalWeeks) * chartW;
        const isCrit = critPhases.has(s.id);
        return (
          <g key={s.id}>
            <text x={pad.l - 6} y={y + rowH / 2 + 4} textAnchor="end" fill="var(--cds-text-secondary)" fontSize="9" fontWeight="500">
              {s.label}
            </text>
            <rect x={x} y={y} width={w} height={rowH} rx={4}
              fill={isCrit ? "var(--gold)" : "var(--cds-layer-03)"}
              opacity={isCrit ? 0.85 : 0.6}
              stroke={isCrit ? "var(--gold-dark)" : "none"} strokeWidth={isCrit ? 1.5 : 0} />
            <text x={x + w / 2} y={y + rowH / 2 + 4} textAnchor="middle"
              fill={isCrit ? "#000" : "var(--cds-text-secondary)"} fontSize="9" fontWeight="600"
              fontFamily="JetBrains Mono, monospace">
              {s.weeks}w
            </text>
            {/* Dependency arrows */}
            {s.depends.map(dep => {
              const depS = schedule.find(p => p.id === dep);
              if (!depS) return null;
              const depI = schedule.indexOf(depS);
              const fromX = pad.l + (depS.endWeek / totalWeeks) * chartW;
              const fromY = pad.t + depI * (rowH + gap) + rowH / 2;
              const toY = y + rowH / 2;
              return (
                <path key={dep} d={`M${fromX},${fromY} C${fromX + 10},${fromY} ${x - 10},${toY} ${x},${toY}`}
                  fill="none" stroke="var(--cds-text-helper)" strokeWidth={0.8} opacity={0.4} />
              );
            })}
          </g>
        );
      })}

      {/* Milestones */}
      {milestonePts.map(m => {
        const x = pad.l + ((m.week < 0 ? 0 : m.week) / totalWeeks) * chartW;
        const y = height - pad.b + 8;
        return (
          <g key={m.id}>
            <line x1={x} y1={pad.t} x2={x} y2={height - pad.b} stroke={m.color} strokeWidth={1.5} strokeDasharray="3,3" />
            <polygon points={`${x},${y - 6} ${x - 5},${y + 2} ${x + 5},${y + 2}`} fill={m.color} />
            <text x={x} y={y + 14} textAnchor="middle" fill={m.color} fontSize="7" fontWeight="700">{m.label}</text>
          </g>
        );
      })}

      {/* Duration label */}
      <text x={width / 2} y={height - 2} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="10" fontWeight="700" fontFamily="JetBrains Mono, monospace">
        Total: {totalWeeks} weeks ({Math.ceil(totalWeeks / 4.33)} months)
      </text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ConstructionPanel
   ═══════════════════════════════════════════════════════════════════════════ */
export default function ConstructionPanel({ onClose }) {
  const { explain } = useSite();
  const [activeTab, setActiveTab] = useState("timeline");
  const [technology, setTechnology] = useState("solar");
  const [capacityMw, setCapacityMw] = useState(50);
  const [startDate] = useState(new Date(2026, 5, 1)); // Jun 2026

  // Monitor tab
  const [progress, setProgress] = useState({});

  const TABS = [
    { id: "timeline", label: "Timeline" },
    { id: "monitor", label: "Monitor" },
  ];

  const phases = useMemo(() => {
    const base = TECH_PHASES[technology] || TECH_PHASES.solar;
    // Scale durations by capacity
    const scale = capacityMw > 100 ? 1.3 : capacityMw > 50 ? 1.1 : 1.0;
    return base.map(p => ({ ...p, weeks: Math.ceil(p.weeks * scale) }));
  }, [technology, capacityMw]);

  const totalWeeks = useMemo(() => {
    const endWeeks = {};
    phases.forEach(p => {
      let sw = 0;
      p.depends.forEach(d => { if (endWeeks[d] > sw) sw = endWeeks[d]; });
      endWeeks[p.id] = sw + p.weeks;
    });
    return Math.max(...Object.values(endWeeks), 0);
  }, [phases]);

  // Compute schedule for monitor tab
  const schedule = useMemo(() => {
    const result = [];
    const endWeeks = {};
    phases.forEach(p => {
      let sw = 0;
      p.depends.forEach(d => { if (endWeeks[d] > sw) sw = endWeeks[d]; });
      endWeeks[p.id] = sw + p.weeks;
      result.push({ ...p, startWeek: sw, endWeek: sw + p.weeks });
    });
    return result;
  }, [phases]);

  const overallProgress = useMemo(() => {
    if (Object.keys(progress).length === 0) return 0;
    const total = phases.reduce((s, p) => s + (progress[p.id] || 0), 0);
    return total / phases.length;
  }, [progress, phases]);

  const initProgress = useCallback(() => {
    const p = {};
    // Simulate some progress
    phases.forEach((phase, i) => {
      p[phase.id] = i < 2 ? 100 : i === 2 ? 65 : 0;
    });
    setProgress(p);
  }, [phases]);

  return (
    <div className="gc-panel ct-panel">
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="4" x2="9" y2="20"/></svg>
          CONSTRUCTION
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
        {/* ──────── TIMELINE ──────── */}
        {activeTab === "timeline" && (
          <div className="ct-section">
            <div className="ct-sub-section">
              <div className="ct-sub-title">Technology</div>
              <div className="ct-tech-row">
                {["solar", "bess", "wind"].map(t => (
                  <button key={t} className={`ct-tech-btn${technology === t ? " active" : ""}`}
                    onClick={() => setTechnology(t)}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            <div className="ct-sub-section">
              <div className="ct-input-row">
                <label className="ct-input-label">Capacity</label>
                <div className="ct-input-val-row">
                  <input type="range" min={5} max={200} step={5} value={capacityMw}
                    onChange={e => setCapacityMw(+e.target.value)} className="pf-slider" />
                  <span className="ct-input-value">{capacityMw} MW</span>
                </div>
              </div>
            </div>

            <div className="ct-sub-section">
              <div className="ct-sub-title">Gantt Chart</div>
              <div className="ct-gantt-wrap">
                <GanttChart phases={phases} startDate={startDate} milestones={MILESTONES} />
              </div>
            </div>

            <div className="ct-sub-section">
              <div className="ct-sub-title">Phase Details</div>
              <div className="ct-phase-list">
                {schedule.map(p => (
                  <div key={p.id} className="ct-phase-row">
                    <span className="ct-phase-name">{p.label}</span>
                    <span className="ct-phase-dates">
                      {fmtDate(addWeeks(startDate, p.startWeek))} - {fmtDate(addWeeks(startDate, p.endWeek))}
                    </span>
                    <span className="ct-phase-dur">{p.weeks}w</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="ct-summary-strip">
              <div className="ct-summary-item">
                <span className="ct-sum-label">Start</span>
                <span className="ct-sum-value">{fmtDate(startDate)}</span>
              </div>
              <div className="ct-summary-item">
                <span className="ct-sum-label">Duration</span>
                <span className="ct-sum-value">{totalWeeks} weeks</span>
              </div>
              <div className="ct-summary-item">
                <span className="ct-sum-label">COD</span>
                <span className="ct-sum-value ct-sum-gold">{fmtDate(addWeeks(startDate, totalWeeks))}</span>
              </div>
            </div>
          </div>
        )}

        {/* ──────── MONITOR ──────── */}
        {activeTab === "monitor" && (
          <div className="ct-section">
            {Object.keys(progress).length === 0 ? (
              <div className="ct-monitor-init">
                <div className="ct-empty">No construction monitoring data. Click below to simulate progress tracking.</div>
                <button className="pf-action-btn" onClick={initProgress}>Initialize Monitoring</button>
              </div>
            ) : (
              <>
                <div className="ct-sub-section">
                  <div className="ct-sub-title">Overall Progress</div>
                  <div className="ct-overall-bar">
                    <div className="ct-overall-track">
                      <div className="ct-overall-fill" style={{ width: `${overallProgress}%` }} />
                    </div>
                    <span className="ct-overall-pct">{overallProgress.toFixed(0)}%</span>
                  </div>
                </div>

                <div className="ct-sub-section">
                  <div className="ct-sub-title">Phase Progress</div>
                  <div className="ct-progress-list">
                    {phases.map(p => {
                      const pct = progress[p.id] || 0;
                      return (
                        <div key={p.id} className="ct-progress-row">
                          <span className="ct-prog-name">{p.label}</span>
                          <div className="ct-prog-bar">
                            <div className="ct-prog-track">
                              <div className="ct-prog-fill" style={{
                                width: `${pct}%`,
                                background: pct === 100 ? "var(--cds-support-success)" : "var(--gold)"
                              }} />
                            </div>
                          </div>
                          <span className="ct-prog-pct">{pct}%</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="ct-sub-section">
                  <div className="ct-sub-title">Risk Flags</div>
                  <div className="ct-risk-list">
                    {RISK_FLAGS.map(r => (
                      <div key={r.id} className="ct-risk-item">
                        <span className={`ct-risk-dot ct-risk-${r.severity}`} />
                        <div>
                          <div className="ct-risk-label">{r.label}</div>
                          <div className="ct-risk-desc">{r.desc}</div>
                        </div>
                        <span className={`ct-risk-sev ct-sev-${r.severity}`}>{r.severity}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="ct-sub-section">
                  <div className="ct-sub-title">Photo Upload</div>
                  <div className="ct-photo-placeholder">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--cds-text-helper)" strokeWidth="1.5">
                      <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>
                    </svg>
                    <span>Site inspection photos (coming soon)</span>
                  </div>
                </div>

                <div className="ct-sub-section">
                  <div className="ct-sub-title">Next Milestones</div>
                  <div className="ct-milestone-list">
                    {(() => {
                      const now = new Date();
                      const upcoming = [
                        { label: "Module delivery", date: addWeeks(startDate, 10), critical: true },
                        { label: "Grid connection offer", date: addWeeks(startDate, 14), critical: false },
                        { label: "First power", date: addWeeks(startDate, totalWeeks - 3), critical: true },
                        { label: "COD", date: addWeeks(startDate, totalWeeks), critical: true },
                      ];
                      return upcoming.map((m, i) => {
                        const daysLeft = Math.ceil((m.date - now) / (1000 * 60 * 60 * 24));
                        return (
                          <div key={i} className="ct-milestone-row">
                            <span className={`ct-ms-dot${m.critical ? " ct-ms-critical" : ""}`} />
                            <span className="ct-ms-label">{m.label}</span>
                            <span className="ct-ms-date">{fmtDate(m.date)}</span>
                            <span className="ct-ms-countdown">{daysLeft > 0 ? `${daysLeft}d` : "Past"}</span>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
