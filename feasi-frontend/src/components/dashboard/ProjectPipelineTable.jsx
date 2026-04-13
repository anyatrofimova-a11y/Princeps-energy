import React, { useState, useMemo } from "react";

const PHASES = {
  feasibility: { label: "Feasibility", pct: 0.15, color: "#9CA3AF" },
  grid_study: { label: "Grid Study", pct: 0.3, color: "#D4A018" },
  planning: { label: "Planning", pct: 0.5, color: "#3b82f6" },
  installation: { label: "Installation", pct: 0.75, color: "#8b5cf6" },
  commissioning: { label: "Commissioning", pct: 0.9, color: "#22c55e" },
  operational: { label: "Operational", pct: 1.0, color: "#16a34a" },
};

const STATUS_COLORS = {
  operational: "#16a34a",
  in_progress: "#3b82f6",
  at_risk: "#f59e0b",
  paused: "#9CA3AF",
};

const TECH_CHIPS = [
  { key: "all", label: "All" },
  { key: "solar", label: "Solar" },
  { key: "wind", label: "Wind" },
  { key: "bess", label: "BESS" },
  { key: "datacentre", label: "DC" },
];

const VERDICT_CHIPS = [
  { key: "GO", label: "GO" },
  { key: "CAUTION", label: "CAUTION" },
  { key: "NO-GO", label: "NO-GO" },
];

function getRiskLevel(p) {
  if (p.risk_level) return p.risk_level;
  if ((p.score || 0) >= 70) return "low";
  if ((p.score || 0) >= 50) return "medium";
  return "high";
}

function scoreColor(score) {
  if (score >= 70) return "#16a34a";
  if (score >= 50) return "#d97706";
  return "#dc2626";
}

function SortIcon({ active, dir }) {
  if (!active) return null;
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ marginLeft: 3, verticalAlign: "middle" }}>
      <path d={dir > 0 ? "M5 2L8 6H2L5 2Z" : "M5 8L2 4H8L5 8Z"} fill="var(--muted)" />
    </svg>
  );
}

/* Map project phase to the most relevant analysis intent */
const PHASE_INTENT = {
  feasibility: "feasibility",
  grid_study: "grid_connection",
  planning: "planning",
  installation: "feasibility",
  commissioning: "feasibility",
  operational: "financial",
};

export default function ProjectPipelineTable({ projects = [], onViewProject, onAssessProject, onNavigateIntent }) {
  const [search, setSearch] = useState("");
  const [techFilter, setTechFilter] = useState("all");
  const [verdictFilters, setVerdictFilters] = useState(new Set());
  const [sortBy, setSortBy] = useState("score");
  const [sortDir, setSortDir] = useState(-1);
  const [expandedId, setExpandedId] = useState(null);
  const [hoverIdx, setHoverIdx] = useState(null);

  const toggleVerdict = (v) => {
    setVerdictFilters((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      return next;
    });
  };

  const filtered = useMemo(() => {
    let list = projects;
    if (search) list = list.filter((p) => p.name?.toLowerCase().includes(search.toLowerCase()));
    if (techFilter !== "all") list = list.filter((p) => p.technology === techFilter);
    if (verdictFilters.size > 0) list = list.filter((p) => verdictFilters.has(p.verdict));
    list = [...list].sort((a, b) => {
      const av = a[sortBy] ?? 0;
      const bv = b[sortBy] ?? 0;
      return typeof av === "string" ? av.localeCompare(bv) * sortDir : (av - bv) * sortDir;
    });
    return list;
  }, [projects, search, techFilter, verdictFilters, sortBy, sortDir]);

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir((d) => -d);
    else { setSortBy(col); setSortDir(-1); }
  };

  const toggleExpand = (id) => setExpandedId((prev) => (prev === id ? null : id));

  const verdictClass = (v) =>
    v === "GO" ? "pd3-verdict pd3-verdict-go"
      : v === "NO-GO" ? "pd3-verdict pd3-verdict-nogo"
        : "pd3-verdict pd3-verdict-caution";

  const thStyle = {
    fontSize: 10,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: "var(--muted)",
    padding: "10px 16px",
    borderBottom: "1px solid var(--border)",
    textAlign: "left",
    position: "sticky",
    top: 0,
    background: "var(--cds-layer-01)",
    cursor: "pointer",
    userSelect: "none",
    whiteSpace: "nowrap",
    zIndex: 1,
  };

  const tdStyle = {
    padding: "12px 16px",
    borderBottom: "1px solid var(--cds-layer-03, #EBEDF0)",
    verticalAlign: "middle",
    fontSize: 13,
  };

  return (
    <div>
      {/* Filter bar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "14px 20px 12px",
        flexWrap: "wrap",
      }}>
        {TECH_CHIPS.map((c) => (
          <button
            key={c.key}
            className={`pd3-chip ${techFilter === c.key ? "pd3-chip-active" : ""}`}
            onClick={() => setTechFilter(c.key)}
          >
            {c.label}
          </button>
        ))}
        <div style={{ width: 1, height: 20, background: "var(--border)", margin: "0 6px" }} />
        {VERDICT_CHIPS.map((c) => (
          <button
            key={c.key}
            className={`pd3-chip ${verdictFilters.has(c.key) ? "pd3-chip-active" : ""}`}
            onClick={() => toggleVerdict(c.key)}
          >
            {c.label}
          </button>
        ))}
        <div style={{ width: 1, height: 20, background: "var(--border)", margin: "0 6px" }} />
        <input
          type="text"
          placeholder="Search projects..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            padding: "6px 12px",
            fontSize: 12,
            fontFamily: "'DM Sans', sans-serif",
            border: "1px solid var(--border)",
            borderRadius: 8,
            outline: "none",
            background: "var(--cds-layer-02)",
            color: "var(--ink)",
            width: 180,
            transition: "border-color 0.15s, box-shadow 0.15s",
          }}
          onFocus={(e) => {
            e.target.style.borderColor = "var(--gold)";
            e.target.style.boxShadow = "0 0 0 2px rgba(245,183,49,0.1)";
          }}
          onBlur={(e) => {
            e.target.style.borderColor = "var(--border)";
            e.target.style.boxShadow = "none";
          }}
        />
        <span style={{ fontSize: 11, color: "var(--muted-light)", marginLeft: 4 }}>
          {filtered.length} projects
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: 480 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "'DM Sans', sans-serif" }}>
          <thead>
            <tr>
              <th style={thStyle} onClick={() => toggleSort("name")}>
                Project <SortIcon active={sortBy === "name"} dir={sortDir} />
              </th>
              <th style={thStyle}>Status</th>
              <th style={thStyle} onClick={() => toggleSort("capacity_mw")}>
                MW <SortIcon active={sortBy === "capacity_mw"} dir={sortDir} />
              </th>
              <th style={thStyle}>Phase</th>
              <th style={thStyle}>Risk</th>
              <th style={thStyle} onClick={() => toggleSort("score")}>
                Score <SortIcon active={sortBy === "score"} dir={sortDir} />
              </th>
              <th style={thStyle}>Verdict</th>
              <th style={{ ...thStyle, cursor: "default" }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p, i) => {
              const phase = PHASES[p.phase] || PHASES.feasibility;
              const risk = getRiskLevel(p);
              const pid = p.id || i;
              const isExpanded = expandedId === pid;
              const isHover = hoverIdx === i;

              return (
                <React.Fragment key={pid}>
                  <tr
                    className="pd3-table-row"
                    style={{
                      background: isHover ? "rgba(245,183,49,0.03)" : "transparent",
                    }}
                    onMouseEnter={() => setHoverIdx(i)}
                    onMouseLeave={() => setHoverIdx(null)}
                    onClick={() => toggleExpand(pid)}
                  >
                    <td style={{
                      ...tdStyle,
                      fontWeight: 600,
                      color: isHover ? "var(--gold-dark)" : "var(--ink)",
                      transition: "color 0.15s",
                    }}>
                      {p.name}
                    </td>
                    <td style={tdStyle}>
                      <span
                        className={`pd3-risk-dot pd3-risk-dot-${risk}`}
                        style={{
                          background: STATUS_COLORS[p.status || "in_progress"],
                          marginRight: 8,
                        }}
                      />
                      <span style={{ fontSize: 12, color: "var(--muted)" }}>
                        {(p.status || "in_progress").replace("_", " ")}
                      </span>
                    </td>
                    <td style={{
                      ...tdStyle,
                      fontFamily: "var(--mono), monospace",
                      fontWeight: 700,
                    }}>
                      {p.capacity_mw}
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div className="pd3-progress-track">
                          <div
                            className="pd3-progress-fill"
                            style={{
                              width: `${phase.pct * 100}%`,
                              background: phase.color,
                            }}
                          />
                        </div>
                        <span style={{ fontSize: 10, color: "var(--muted-light)", whiteSpace: "nowrap" }}>
                          {phase.label}
                        </span>
                      </div>
                    </td>
                    <td style={tdStyle}>
                      <span className={`pd3-risk-dot pd3-risk-dot-${risk}`} />
                    </td>
                    <td style={{
                      ...tdStyle,
                      fontFamily: "var(--mono), monospace",
                      fontWeight: 800,
                      color: scoreColor(p.score || 0),
                    }}>
                      {p.score}
                    </td>
                    <td style={tdStyle}>
                      <span className={verdictClass(p.verdict)}>{p.verdict}</span>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: "flex", gap: 4 }}>
                        <button
                          title="View project"
                          onClick={(e) => { e.stopPropagation(); onViewProject?.(p); }}
                          style={{
                            background: "none",
                            border: "1px solid transparent",
                            cursor: "pointer",
                            padding: "4px 6px",
                            borderRadius: 6,
                            color: "var(--muted)",
                            transition: "all 0.15s",
                            display: "flex",
                            alignItems: "center",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = "var(--gold-dark)";
                            e.currentTarget.style.borderColor = "rgba(245,183,49,0.3)";
                            e.currentTarget.style.background = "rgba(245,183,49,0.06)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = "var(--muted)";
                            e.currentTarget.style.borderColor = "transparent";
                            e.currentTarget.style.background = "none";
                          }}
                        >
                          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <circle cx="8" cy="8" r="3" />
                            <path d="M1.5 8c1.5-4 4.5-5.5 6.5-5.5s5 1.5 6.5 5.5c-1.5 4-4.5 5.5-6.5 5.5S3 12 1.5 8z" />
                          </svg>
                        </button>
                        <button
                          title="Run assessment"
                          onClick={(e) => {
                            e.stopPropagation();
                            onViewProject?.(p);
                            const intent = PHASE_INTENT[p.phase] || "feasibility";
                            onNavigateIntent?.(intent);
                          }}
                          style={{
                            background: "none",
                            border: "1px solid transparent",
                            cursor: "pointer",
                            padding: "4px 6px",
                            borderRadius: 6,
                            color: "var(--muted)",
                            transition: "all 0.15s",
                            display: "flex",
                            alignItems: "center",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color = "var(--gold-dark)";
                            e.currentTarget.style.borderColor = "rgba(245,183,49,0.3)";
                            e.currentTarget.style.background = "rgba(245,183,49,0.06)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = "var(--muted)";
                            e.currentTarget.style.borderColor = "transparent";
                            e.currentTarget.style.background = "none";
                          }}
                        >
                          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <path d="M8.5 1.5L3 9h5l-.5 6L13 7H8l.5-5.5z" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>

                  {/* Expanded detail row */}
                  {isExpanded && (
                    <tr className="pd3-table-row-expanded">
                      <td colSpan={8} style={{ padding: 0 }}>
                        <div style={{
                          display: "flex",
                          gap: 32,
                          padding: "16px 20px",
                          fontSize: 12,
                          color: "var(--ink)",
                          animation: "pd-expand-in 0.3s ease",
                        }}>
                          {/* Financial */}
                          <div style={{ display: "flex", gap: 24 }}>
                            {[
                              { label: "IRR", value: `${p.irr ?? "8.2"}%` },
                              { label: "NPV", value: p.npv ? `${(p.npv / 1e6).toFixed(1)}M` : "2.4M" },
                              { label: "LCOE", value: `${p.lcoe ?? "42"} /MWh` },
                            ].map((m) => (
                              <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                <span style={{
                                  fontSize: 9,
                                  textTransform: "uppercase",
                                  color: "var(--muted)",
                                  fontWeight: 700,
                                  letterSpacing: "0.05em",
                                }}>
                                  {m.label}
                                </span>
                                <span style={{
                                  fontSize: 15,
                                  fontWeight: 700,
                                  fontFamily: "var(--mono), monospace",
                                }}>
                                  {m.value}
                                </span>
                              </div>
                            ))}
                          </div>

                          {/* Timeline */}
                          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                            <span style={{
                              fontSize: 9,
                              textTransform: "uppercase",
                              color: "var(--muted)",
                              fontWeight: 700,
                              letterSpacing: "0.05em",
                            }}>
                              Timeline
                            </span>
                            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                              {["Scoping", "Grid App", "Planning", "Build", "COD"].map((ms, mi) => {
                                const phaseIdx = Object.keys(PHASES).indexOf(p.phase) ?? 0;
                                const completed = mi <= phaseIdx;
                                return (
                                  <React.Fragment key={ms}>
                                    <div style={{
                                      width: 8,
                                      height: 8,
                                      borderRadius: "50%",
                                      background: completed ? "var(--gold)" : "var(--cds-layer-03)",
                                      border: "2px solid var(--cds-layer-01)",
                                      boxShadow: completed
                                        ? "0 0 0 1px var(--gold), 0 0 4px rgba(245,183,49,0.3)"
                                        : "0 0 0 1px var(--border)",
                                      transition: "all 0.3s ease",
                                    }} />
                                    {mi < 4 && (
                                      <div style={{
                                        flex: 1,
                                        height: 2,
                                        background: mi < phaseIdx ? "var(--gold)" : "var(--cds-layer-03)",
                                        borderRadius: 1,
                                        transition: "background 0.3s ease",
                                      }} />
                                    )}
                                  </React.Fragment>
                                );
                              })}
                            </div>
                            <div style={{
                              display: "flex",
                              justifyContent: "space-between",
                              fontSize: 9,
                              color: "var(--muted-light)",
                            }}>
                              {["Scoping", "Grid App", "Planning", "Build", "COD"].map((ms) => (
                                <span key={ms}>{ms}</span>
                              ))}
                            </div>
                          </div>

                          {/* Risk + link */}
                          <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 160 }}>
                            <span style={{
                              fontSize: 9,
                              textTransform: "uppercase",
                              color: "var(--muted)",
                              fontWeight: 700,
                              letterSpacing: "0.05em",
                            }}>
                              Top Risk
                            </span>
                            <span
                              style={{
                                fontSize: 12,
                                color: "#dc2626",
                                fontWeight: 500,
                                cursor: "pointer",
                                transition: "opacity 0.15s",
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                onViewProject?.(p);
                                onNavigateIntent?.("grid_connection");
                              }}
                              onMouseEnter={e => e.currentTarget.style.opacity = "0.7"}
                              onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                            >
                              {p.top_risk || "Grid capacity constrained"}
                            </span>
                            <button
                              style={{
                                fontSize: 12,
                                color: "var(--gold-dark)",
                                fontWeight: 600,
                                cursor: "pointer",
                                border: "none",
                                background: "none",
                                padding: 0,
                                textAlign: "left",
                                fontFamily: "'DM Sans', sans-serif",
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                onViewProject?.(p);
                                const intent = PHASE_INTENT[p.phase] || "feasibility";
                                onNavigateIntent?.(intent);
                              }}
                            >
                              View full analysis
                              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                                <path d="M3.5 1.5L7 5L3.5 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                              </svg>
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  style={{ ...tdStyle, textAlign: "center", color: "var(--muted)", padding: 48 }}
                >
                  No projects match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
