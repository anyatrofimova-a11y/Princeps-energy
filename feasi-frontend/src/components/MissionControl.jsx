import React, { useEffect, useState, useCallback } from "react";

/* ──────────────────────────────────────────────────────────────────────
   Mission Control — lender-grade portfolio dashboard.
   Replaces the abstract "What would you like to do?" landing screen
   with a dense, at-a-glance view of the user's actual portfolio.
   ────────────────────────────────────────────────────────────────────── */

const VERDICT_STYLES = {
  GO:      { bg: "#DEF7E5", fg: "#1E7B3A", label: "GO" },
  CAUTION: { bg: "#FFF4D6", fg: "#92660A", label: "CAUTION" },
  NOGO:    { bg: "#FCE5E5", fg: "#B23B3B", label: "NO-GO" },
  "NO-GO": { bg: "#FCE5E5", fg: "#B23B3B", label: "NO-GO" },
};

const WORKLOAD_ICON = {
  solar:  "\u2600",        // ☀
  bess:   "\uD83D\uDD0B",  // 🔋
  dc:     "\uD83C\uDFE2",  // 🏢
  wind:   "\uD83C\uDF2C",  // 🌬
  hybrid: "\u26A1",        // ⚡
};

const WORKLOAD_LABEL = {
  solar: "Solar", bess: "BESS", dc: "Data Centre", wind: "Wind", hybrid: "Hybrid",
};

const GRID_GLYPH = {
  headroom_ok:  { glyph: "\u2713", color: "#1E7B3A" },
  queue_long:   { glyph: "\u23F3", color: "#92660A" },
  constrained:  { glyph: "\u26A0", color: "#B23B3B" },
};

const ACTIVITY_ICONS = {
  doc:   "\u25A4",
  grid:  "\u25C9",
  stage: "\u2192",
};

const COLORS = {
  gold: "var(--gold, #F5B731)",
  helper: "var(--cds-text-helper, #6B7280)",
  body: "#0F1318",
  border: "#E5E7EB",
  surface: "#FFFFFF",
  shimmer: "#F2F3F5",
  errBg: "#FCE5E5",
  errFg: "#B23B3B",
};

const FONT_BODY = "'DM Sans', -apple-system, sans-serif";
const FONT_MONO = "var(--mono, ui-monospace, 'SF Mono', Menlo, monospace)";

/* ── small helpers ───────────────────────────────────────────────────── */
function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function fmtDeadline(d) {
  if (d == null) return "—";
  if (d <= 0) return "due now";
  if (d === 1) return "1d";
  return `${d}d`;
}

/* ── Skeleton row for loading state ──────────────────────────────────── */
function Shimmer({ w = "100%", h = 14, style = {} }) {
  return (
    <div
      style={{
        width: w, height: h, borderRadius: 3,
        background: `linear-gradient(90deg, ${COLORS.shimmer} 0%, #E8EAEE 50%, ${COLORS.shimmer} 100%)`,
        backgroundSize: "200% 100%",
        animation: "mc-shimmer 1.4s ease-in-out infinite",
        ...style,
      }}
    />
  );
}

/* ── Verdict pill ────────────────────────────────────────────────────── */
function VerdictPill({ verdict }) {
  const s = VERDICT_STYLES[verdict] || VERDICT_STYLES.CAUTION;
  return (
    <span style={{
      background: s.bg, color: s.fg,
      fontWeight: 600, fontSize: 10, letterSpacing: 1,
      padding: "3px 8px", borderRadius: 3, fontFamily: FONT_BODY,
    }}>{s.label}</span>
  );
}

/* ── Metric tile (hero numbers in gold) ──────────────────────────────── */
function MetricTile({ label, value, sub, hero = false }) {
  return (
    <div style={{
      flex: 1, minWidth: 0,
      borderRight: `1px solid ${COLORS.border}`,
      padding: "18px 24px",
    }}>
      <div style={{
        fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase",
        color: COLORS.helper, fontWeight: 600, marginBottom: 8,
      }}>{label}</div>
      <div style={{
        fontFamily: FONT_MONO, fontSize: 26, fontWeight: 600,
        color: hero ? COLORS.gold : COLORS.body,
        lineHeight: 1, letterSpacing: "-0.5px",
      }}>{value}</div>
      {sub != null && (
        <div style={{ fontSize: 11, color: COLORS.helper, marginTop: 6 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

/* ── Empty-state workload picker (first-run experience) ──────────────── */
const WORKLOAD_PICKER = [
  { id: "solar",  icon: WORKLOAD_ICON.solar,  label: "Solar",       desc: "Utility-scale PV" },
  { id: "bess",   icon: WORKLOAD_ICON.bess,   label: "BESS",        desc: "Battery storage" },
  { id: "dc",     icon: WORKLOAD_ICON.dc,     label: "Data Centre", desc: "Hyperscale / colo" },
  { id: "wind",   icon: WORKLOAD_ICON.wind,   label: "Wind",        desc: "Onshore turbines" },
  { id: "hybrid", icon: WORKLOAD_ICON.hybrid, label: "Hybrid",      desc: "Co-located mix" },
];

function EmptyStatePicker({ onPick }) {
  const [hover, setHover] = useState(null);
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: COLORS.shimmer, fontFamily: FONT_BODY, padding: 32,
    }}>
      <div style={{
        background: COLORS.surface, borderRadius: 6, padding: 48,
        maxWidth: 880, width: "100%", boxShadow: "0 1px 3px rgba(15,19,24,0.06)",
        border: `1px solid ${COLORS.border}`,
      }}>
        <div style={{
          fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
          color: COLORS.gold, fontWeight: 600, marginBottom: 10,
        }}>Welcome to Princeps</div>
        <h1 style={{
          fontSize: 28, fontWeight: 600, color: COLORS.body, margin: 0,
          letterSpacing: "-0.5px",
        }}>What are you developing?</h1>
        <div style={{ color: COLORS.helper, fontSize: 14, marginTop: 8, marginBottom: 32 }}>
          Pick your primary workload. You can change this per-project later.
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
          {WORKLOAD_PICKER.map(w => (
            <button
              key={w.id}
              onClick={() => onPick(w.id)}
              onMouseEnter={() => setHover(w.id)}
              onMouseLeave={() => setHover(null)}
              style={{
                background: hover === w.id ? "#FFFBF0" : COLORS.surface,
                border: `1px solid ${hover === w.id ? COLORS.gold : COLORS.border}`,
                borderRadius: 4, padding: "20px 12px", cursor: "pointer",
                textAlign: "center", fontFamily: FONT_BODY,
                transition: "all 120ms ease",
              }}
            >
              <div style={{ fontSize: 26, marginBottom: 8 }}>{w.icon}</div>
              <div style={{ fontWeight: 600, fontSize: 13, color: COLORS.body }}>{w.label}</div>
              <div style={{ fontSize: 11, color: COLORS.helper, marginTop: 3 }}>{w.desc}</div>
            </button>
          ))}
        </div>

        <div style={{
          marginTop: 32, paddingTop: 20, borderTop: `1px solid ${COLORS.border}`,
          fontSize: 11, color: COLORS.helper, letterSpacing: 1, textTransform: "uppercase",
        }}>
          Or press <kbd style={{
            background: COLORS.shimmer, padding: "2px 6px", borderRadius: 3,
            fontFamily: FONT_MONO, fontSize: 10, marginLeft: 4,
          }}>&#8984;K</kbd> to search
        </div>
      </div>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────────── */
export default function MissionControl({
  onSelectProject = () => {},
  onNewProject = () => {},
  onPickWorkload = () => {},
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoverRow, setHoverRow] = useState(null);
  const [ctaHover, setCtaHover] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/portfolios/mission-control");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message || "Failed to load portfolio");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  /* ── Empty-state branch (no projects) ──────────────────────────────── */
  if (!loading && !error && data && data.metrics && data.metrics.total_projects === 0) {
    return <EmptyStatePicker onPick={onPickWorkload} />;
  }

  /* ── Error banner ──────────────────────────────────────────────────── */
  if (error && !loading) {
    return (
      <div style={{
        minHeight: "100vh", background: COLORS.shimmer, padding: 32,
        fontFamily: FONT_BODY,
      }}>
        <div style={{
          background: COLORS.errBg, color: COLORS.errFg, padding: "16px 24px",
          borderRadius: 4, border: `1px solid ${COLORS.errFg}`, maxWidth: 600,
          margin: "120px auto", fontSize: 13,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Couldn't load Mission Control</div>
          <div style={{ marginBottom: 12, opacity: 0.85 }}>{error}</div>
          <button
            onClick={load}
            style={{
              background: COLORS.errFg, color: "#fff", border: "none",
              padding: "8px 16px", borderRadius: 3, fontWeight: 600,
              fontSize: 12, cursor: "pointer", fontFamily: FONT_BODY,
            }}
          >Retry</button>
        </div>
      </div>
    );
  }

  const m = data?.metrics || {};
  const projects = data?.active_projects || [];
  const signals = data?.live_signals || [];
  const activity = data?.activity_feed || [];

  return (
    <div style={{
      minHeight: "100vh", background: COLORS.shimmer, padding: 32,
      fontFamily: FONT_BODY, color: COLORS.body,
    }}>
      <style>{`
        @keyframes mc-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

      <div style={{ maxWidth: 1400, margin: "0 auto" }}>
        {/* ── Header ── */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
          <img src="/logo-princeps.png" alt="Princeps" width="28" height="28" style={{ objectFit: "contain", marginRight: 10 }} />
          <span style={{
            fontWeight: 600, letterSpacing: 2, fontSize: 13,
            color: COLORS.body,
          }}>PRINCEPS</span>
          <span style={{
            marginLeft: 12, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase",
            color: COLORS.helper, fontWeight: 600,
          }}>Mission Control</span>
        </div>

        {/* ── Portfolio metrics strip ── */}
        <div style={{
          background: COLORS.surface, border: `1px solid ${COLORS.border}`,
          borderRadius: 4, marginBottom: 20, overflow: "hidden",
        }}>
          <div style={{
            padding: "12px 24px", borderBottom: `1px solid ${COLORS.border}`,
            fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
            color: COLORS.helper, fontWeight: 600,
          }}>Portfolio</div>
          {loading ? (
            <div style={{ display: "flex", padding: "18px 24px", gap: 24 }}>
              {[1,2,3,4,5].map(i => (
                <div key={i} style={{ flex: 1 }}>
                  <Shimmer w="60%" h={10} style={{ marginBottom: 10 }} />
                  <Shimmer w="80%" h={26} />
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex" }}>
              <MetricTile label="Projects" value={m.total_projects ?? 0} hero />
              <MetricTile label="Total MW" value={m.total_mw ?? 0} hero />
              <MetricTile
                label="Verdicts"
                value={`${m.go_count ?? 0} GO`}
                sub={`${m.caution_count ?? 0} CAUTION`}
              />
              <MetricTile label="In queue" value={m.in_queue ?? 0} sub="Discover · Assess · Design" />
              <MetricTile
                label="Next filing"
                value={m.next_filing_deadline?.days_away != null
                  ? fmtDeadline(m.next_filing_deadline.days_away)
                  : "—"}
                sub={m.next_filing_deadline?.project_name || "no upcoming"}
                hero
              />
            </div>
          )}
        </div>

        {/* ── Active projects table ── */}
        <div style={{
          background: COLORS.surface, border: `1px solid ${COLORS.border}`,
          borderRadius: 4, marginBottom: 20, overflow: "hidden",
        }}>
          <div style={{
            padding: "12px 24px", borderBottom: `1px solid ${COLORS.border}`,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <div style={{
              fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
              color: COLORS.helper, fontWeight: 600,
            }}>Active Projects</div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => window.dispatchEvent(new CustomEvent("princeps-inbox-open"))}
                style={{
                  background: "transparent", color: COLORS.body,
                  border: `1px solid ${COLORS.border}`,
                  padding: "8px 14px", borderRadius: 3,
                  fontWeight: 500, fontSize: 12, cursor: "pointer",
                  fontFamily: FONT_BODY, letterSpacing: 0.3,
                }}
              >Ingest from email</button>
              <button
                onClick={onNewProject}
                onMouseEnter={() => setCtaHover(true)}
                onMouseLeave={() => setCtaHover(false)}
                style={{
                  background: ctaHover ? "#E0A529" : COLORS.gold,
                  color: COLORS.body, border: "none",
                  padding: "8px 16px", borderRadius: 3,
                  fontWeight: 600, fontSize: 12, cursor: "pointer",
                  fontFamily: FONT_BODY, letterSpacing: 0.3,
                  transition: "background 120ms ease",
                }}
              >+ New Project</button>
            </div>
          </div>

          <div style={{ padding: "8px 32px 24px" }}>
            <table style={{
              width: "100%", borderCollapse: "collapse", fontSize: 13,
            }}>
              <thead>
                <tr>
                  {["Project","Type","Verdict","IRR","Grid","Plan","Next action",""].map((h, i) => (
                    <th key={i} style={{
                      textAlign: i >= 3 && i <= 5 ? "right" : "left",
                      padding: "12px 10px",
                      borderBottom: `1px solid ${COLORS.border}`,
                      fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase",
                      color: COLORS.helper, fontWeight: 600,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 8 }).map((_, j) => (
                        <td key={j} style={{ padding: "14px 10px", borderBottom: `1px solid ${COLORS.border}` }}>
                          <Shimmer w={j === 0 ? "70%" : "50%"} h={12} />
                        </td>
                      ))}
                    </tr>
                  ))
                ) : projects.length === 0 ? (
                  <tr><td colSpan={8} style={{ padding: 32, textAlign: "center", color: COLORS.helper, fontSize: 13 }}>
                    No active projects.
                  </td></tr>
                ) : projects.map((p, i) => {
                  const grid = GRID_GLYPH[p.grid_status] || { glyph: "\u25CB", color: COLORS.helper };
                  const isHover = hoverRow === p.project_id;
                  return (
                    <tr
                      key={p.project_id}
                      onClick={() => onSelectProject(p.project_id)}
                      onMouseEnter={() => setHoverRow(p.project_id)}
                      onMouseLeave={() => setHoverRow(null)}
                      style={{
                        cursor: "pointer",
                        background: isHover ? "#FFFBF0" : "transparent",
                        transition: "background 80ms ease",
                      }}
                    >
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        fontWeight: 500,
                      }}>{p.name}</td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        color: COLORS.helper, fontSize: 12,
                      }}>
                        <span style={{ marginRight: 6, fontSize: 14 }}>{WORKLOAD_ICON[p.workload_type] || ""}</span>
                        {WORKLOAD_LABEL[p.workload_type] || p.workload_type}
                      </td>
                      <td style={{ padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}` }}>
                        <VerdictPill verdict={p.verdict} />
                      </td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        textAlign: "right", fontFamily: FONT_MONO, fontSize: 13,
                      }}>{p.irr_pct != null ? `${p.irr_pct.toFixed(1)}%` : "—"}</td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        textAlign: "right",
                      }}>
                        <span style={{ color: grid.color, fontWeight: 600, marginRight: 4 }}>{grid.glyph}</span>
                        <span style={{ fontSize: 12, color: COLORS.helper }}>{p.grid_status_label}</span>
                      </td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        textAlign: "right", fontFamily: FONT_MONO, fontSize: 13,
                      }}>{p.planning_pct != null ? `${p.planning_pct}%` : "—"}</td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        fontSize: 12,
                      }}>
                        {p.next_action}
                        <span style={{
                          marginLeft: 8, color: COLORS.helper, fontFamily: FONT_MONO, fontSize: 11,
                        }}>({fmtDeadline(p.next_action_due_days)})</span>
                      </td>
                      <td style={{
                        padding: "12px 10px", borderBottom: `1px solid ${COLORS.border}`,
                        color: COLORS.helper, fontSize: 14, textAlign: "right",
                      }}>{isHover ? "\u2192" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Bottom row: Live signals + Activity ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          {/* Live signals */}
          <div style={{
            background: COLORS.surface, border: `1px solid ${COLORS.border}`,
            borderRadius: 4, overflow: "hidden",
          }}>
            <div style={{
              padding: "12px 24px", borderBottom: `1px solid ${COLORS.border}`,
              fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
              color: COLORS.helper, fontWeight: 600,
            }}>Live Signals</div>
            <div style={{ padding: "20px 32px" }}>
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} style={{ marginBottom: 18 }}>
                    <Shimmer w="40%" h={10} style={{ marginBottom: 8 }} />
                    <Shimmer w="60%" h={20} />
                  </div>
                ))
              ) : signals.map((s, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "baseline", justifyContent: "space-between",
                  paddingBottom: 14, marginBottom: 14,
                  borderBottom: i < signals.length - 1 ? `1px solid ${COLORS.border}` : "none",
                }}>
                  <div>
                    <div style={{
                      fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase",
                      color: COLORS.helper, fontWeight: 600, marginBottom: 4,
                    }}>{s.label}</div>
                    <div style={{
                      fontFamily: FONT_MONO, fontSize: 18, fontWeight: 600,
                      color: COLORS.body,
                    }}>
                      {s.value}
                      {s.delta && (
                        <span style={{
                          marginLeft: 8, fontSize: 11, color: COLORS.helper, fontWeight: 500,
                        }}>{s.delta}</span>
                      )}
                    </div>
                  </div>
                  <div style={{
                    fontSize: 10, color: COLORS.helper, textAlign: "right",
                    maxWidth: 180, lineHeight: 1.4,
                  }}>
                    <div>{s.source}</div>
                    <div style={{ fontFamily: FONT_MONO, marginTop: 2 }}>{fmtTime(s.fetched_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Activity feed */}
          <div style={{
            background: COLORS.surface, border: `1px solid ${COLORS.border}`,
            borderRadius: 4, overflow: "hidden",
          }}>
            <div style={{
              padding: "12px 24px", borderBottom: `1px solid ${COLORS.border}`,
              fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
              color: COLORS.helper, fontWeight: 600,
            }}>Activity</div>
            <div style={{ padding: "12px 32px 20px" }}>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", padding: "10px 0" }}>
                    <Shimmer w={16} h={16} style={{ marginRight: 12, borderRadius: "50%" }} />
                    <Shimmer w="60%" h={12} />
                  </div>
                ))
              ) : activity.length === 0 ? (
                <div style={{ padding: 24, textAlign: "center", color: COLORS.helper, fontSize: 13 }}>
                  No recent activity.
                </div>
              ) : activity.map((a, i) => {
                const clickable = !!a.project_id;
                return (
                  <div
                    key={i}
                    onClick={clickable ? () => onSelectProject(a.project_id) : undefined}
                    style={{
                      display: "flex", alignItems: "center",
                      padding: "10px 0",
                      borderBottom: i < activity.length - 1 ? `1px solid ${COLORS.border}` : "none",
                      cursor: clickable ? "pointer" : "default",
                      fontSize: 13,
                    }}
                    onMouseEnter={(e) => { if (clickable) e.currentTarget.style.color = COLORS.gold; }}
                    onMouseLeave={(e) => { if (clickable) e.currentTarget.style.color = COLORS.body; }}
                  >
                    <span style={{
                      width: 18, height: 18, marginRight: 12,
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      color: COLORS.helper, fontSize: 13,
                    }}>{ACTIVITY_ICONS[a.icon] || "\u2022"}</span>
                    <span style={{ flex: 1, color: "inherit" }}>{a.text}</span>
                    <span style={{
                      fontSize: 11, color: COLORS.helper, fontFamily: FONT_MONO,
                      marginLeft: 12, whiteSpace: "nowrap",
                    }}>{a.time_ago}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
