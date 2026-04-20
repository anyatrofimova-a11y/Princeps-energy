import React, { useEffect, useMemo, useState, useCallback } from "react";
import { STAGES, STAGE_INDEX } from "../lib/stage_workflow";

/**
 * Dashboard — Mission Control 3-card hero + active project table.
 *
 * Replaces the 2026-02 portfolio-metrics strip with a denser executive hero:
 *   Card 1 — Portfolio KPI (total MW in pipeline, IRR-weighted average)
 *   Card 2 — Stage funnel (count per lifecycle stage)
 *   Card 3 — Recent activity (last 5 signals from the activity feed)
 *
 * The existing active-projects table is preserved below so Mission Control's
 * operational surface is unchanged. Data source: GET
 * /api/portfolios/mission-control (returns `metrics`, `active_projects`,
 * `activity_feed`, `live_signals`).
 *
 * Palette: gold #F5B731 accent, ink #0F1318 text, cream #FFFBF0 hero card
 * background. DM Sans + JetBrains Mono.
 */

const VERDICT = {
  GO:       { bg: "rgba(22,163,74,0.14)",  fg: "var(--cds-support-success)", label: "GO" },
  CAUTION:  { bg: "rgba(232,160,18,0.16)", fg: "var(--cds-support-warning)", label: "CAUTION" },
  "NO-GO":  { bg: "rgba(220,38,38,0.14)",  fg: "var(--cds-support-error)",   label: "NO-GO" },
  NOGO:     { bg: "rgba(220,38,38,0.14)",  fg: "var(--cds-support-error)",   label: "NO-GO" },
};

const GRID_DOT = {
  headroom_ok: { glyph: "\u25CF", color: "var(--cds-support-success)" },
  queue_long:  { glyph: "\u25CF", color: "var(--cds-support-warning)" },
  constrained: { glyph: "\u25CF", color: "var(--cds-support-error)"   },
};

const WORKLOAD_LABEL = {
  solar: "Solar", bess: "BESS", dc: "Data Centre", wind: "Wind",
  hybrid: "Hybrid", battery: "BESS", pv: "Solar", gas: "Gas", nuclear: "Nuclear",
};

function fmtMw(mw) {
  if (mw == null) return "—";
  if (mw >= 1000) return `${(mw / 1000).toFixed(1)} GW`;
  return `${Math.round(mw)} MW`;
}

function fmtDeadline(d) {
  if (d == null) return "—";
  if (d <= 0) return "due now";
  if (d === 1) return "1d";
  if (d < 14) return `${d}d`;
  return `${Math.round(d / 7)}w`;
}

function timeAgoShort(iso) {
  if (!iso) return "";
  try {
    const delta = Date.now() - new Date(iso).getTime();
    const m = Math.floor(delta / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return ""; }
}

function VerdictPill({ verdict }) {
  const v = VERDICT[(verdict || "").toUpperCase()] || { bg: "var(--cds-layer-03)", fg: "var(--cds-text-secondary)", label: "—" };
  return <span className="mc-pill" style={{ background: v.bg, color: v.fg }}>{v.label}</span>;
}

/** Shimmer block while loading */
function Sk({ w = "100%", h = 14, mt = 0 }) {
  return <div className="mc-sk" style={{ width: w, height: h, marginTop: mt }} />;
}

/* ──────────────────────────────────────────────────────────────
   CARD 1 — Portfolio KPI
   ─────────────────────────────────────────────────────────── */
function PortfolioKpiCard({ metrics, projects, loading }) {
  const totalMw = metrics?.total_mw ?? 0;
  const totalProjects = metrics?.total_projects ?? 0;
  const goCount = metrics?.go_count ?? 0;
  const cautionCount = metrics?.caution_count ?? 0;

  // IRR-weighted by capacity (projects come with irr_pct)
  const irrWeighted = useMemo(() => {
    if (!Array.isArray(projects) || projects.length === 0) return null;
    let num = 0, den = 0;
    for (const p of projects) {
      const w = Number(p.capacity_mw) || 0;
      const irr = Number(p.irr_pct);
      if (!Number.isFinite(irr) || w <= 0) continue;
      num += irr * w;
      den += w;
    }
    if (den === 0) return null;
    return Math.round((num / den) * 10) / 10;
  }, [projects]);

  return (
    <article className="mc-hero-card mc-hero-primary">
      <header className="mc-hero-head">
        <div className="mc-hero-eyebrow">Pipeline</div>
        <h3 className="mc-hero-title">Portfolio KPIs</h3>
      </header>
      <div className="mc-hero-hero-row">
        <div className="mc-big">
          <div className="mc-big-value mc-big-gold">{loading ? <Sk w="70%" h={34} /> : fmtMw(totalMw)}</div>
          <div className="mc-big-lbl">Total capacity</div>
        </div>
        <div className="mc-big">
          <div className="mc-big-value">
            {loading ? <Sk w="60%" h={34} /> : (irrWeighted != null ? `${irrWeighted.toFixed(1)}%` : "—")}
          </div>
          <div className="mc-big-lbl">IRR (MW-weighted)</div>
        </div>
      </div>
      <div className="mc-hero-row-bot">
        <div className="mc-rollup">
          <span className="mc-rollup-num">{loading ? "—" : totalProjects}</span>
          <span className="mc-rollup-lbl">projects</span>
        </div>
        <div className="mc-rollup">
          <span className="mc-rollup-num" style={{ color: "var(--cds-support-success)" }}>{loading ? "—" : goCount}</span>
          <span className="mc-rollup-lbl">GO</span>
        </div>
        <div className="mc-rollup">
          <span className="mc-rollup-num" style={{ color: "var(--cds-support-warning)" }}>{loading ? "—" : cautionCount}</span>
          <span className="mc-rollup-lbl">CAUTION</span>
        </div>
      </div>
    </article>
  );
}

/* ──────────────────────────────────────────────────────────────
   CARD 2 — Stage funnel
   ─────────────────────────────────────────────────────────── */
function StageFunnelCard({ projects, loading }) {
  const counts = useMemo(() => {
    const c = {};
    for (const s of STAGES) c[s.key] = 0;
    (projects || []).forEach((p) => {
      const s = (p.stage || "prospect").toLowerCase();
      if (c[s] == null) c[s] = 0;
      c[s] += 1;
    });
    return c;
  }, [projects]);
  const max = Math.max(1, ...STAGES.map((s) => counts[s.key] || 0));

  return (
    <article className="mc-hero-card">
      <header className="mc-hero-head">
        <div className="mc-hero-eyebrow">By stage</div>
        <h3 className="mc-hero-title">Stage funnel</h3>
      </header>
      <ul className="mc-funnel">
        {STAGES.map((s) => {
          const n = counts[s.key] || 0;
          const pct = loading ? 0 : Math.round((n / max) * 100);
          return (
            <li key={s.key} className="mc-funnel-row">
              <span className="mc-funnel-lbl">{s.label}</span>
              <span className="mc-funnel-bar-wrap">
                <span className="mc-funnel-bar" style={{ width: `${pct}%` }} />
              </span>
              <span className="mc-funnel-num">{loading ? "—" : n}</span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

/* ──────────────────────────────────────────────────────────────
   CARD 3 — Recent activity (last 5 signals)
   ─────────────────────────────────────────────────────────── */
const ACTIVITY_GLYPH = {
  doc: "\u25A4", grid: "\u25C9", stage: "\u2192", signal: "\u25CF",
};

function RecentActivityCard({ activity = [], signals = [], loading, onActivityClick }) {
  // Merge activity + live signals, cap at 5
  const merged = useMemo(() => {
    const rows = [];
    (activity || []).slice(0, 5).forEach((a) => rows.push({
      kind: "activity",
      glyph: ACTIVITY_GLYPH[a.icon] || "\u2022",
      text: a.text,
      when: a.time_ago,
      project_id: a.project_id,
      entity_type: a.entity_type,
      raw: a,
    }));
    (signals || []).slice(0, 2).forEach((s) => rows.push({
      kind: "signal",
      glyph: ACTIVITY_GLYPH.signal,
      text: `${s.label} — ${s.value}`,
      when: s.fetched_at ? timeAgoShort(s.fetched_at) : "",
      raw: s,
    }));
    return rows.slice(0, 5);
  }, [activity, signals]);

  return (
    <article className="mc-hero-card">
      <header className="mc-hero-head">
        <div className="mc-hero-eyebrow">Live</div>
        <h3 className="mc-hero-title">Recent activity</h3>
      </header>
      {loading ? (
        <div className="mc-activity-sk">
          {[1,2,3,4,5].map(i => (
            <div key={i} className="mc-activity-row">
              <Sk w={16} h={16} />
              <Sk w="70%" h={12} />
            </div>
          ))}
        </div>
      ) : merged.length === 0 ? (
        <div className="mc-activity-empty">No recent activity.</div>
      ) : (
        <ul className="mc-activity-list">
          {merged.map((a, i) => {
            const clickable = !!(a.project_id || a.entity_type);
            return (
            <li
              key={i}
              className={"mc-activity-row" + (clickable ? " mc-activity-clickable" : "")}
              onClick={() => clickable && onActivityClick?.(a.raw)}
              title={
                a.entity_type === "substation" ? "Open substation in grid view" :
                a.entity_type === "memo" ? "Open IC memo" :
                a.project_id ? "Open project" : undefined
              }
            >
              <span className="mc-activity-glyph">{a.glyph}</span>
              <span className="mc-activity-text">{a.text}</span>
              {a.when && <span className="mc-activity-when">{a.when}</span>}
            </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

/* ──────────────────────────────────────────────────────────────
   Active projects table (preserved from previous Mission Control)
   ─────────────────────────────────────────────────────────── */
function ActiveProjectsTable({ projects, loading, onSelectProject }) {
  const [hover, setHover] = useState(null);
  return (
    <div className="mc-table-wrap">
      <div className="mc-table-head">
        <span className="mc-table-eyebrow">Active projects</span>
        <span className="mc-table-count">{loading ? "—" : (projects?.length ?? 0)}</span>
      </div>
      <div className="mc-table-scroll">
        <table className="mc-table">
          <thead>
            <tr>
              {["Project","Type","Verdict","IRR","Grid","Plan","Next action",""].map((h, i) => (
                <th key={h} className={i >= 3 && i <= 5 ? "mc-th-num" : ""}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 5 }).map((_, i) => (
              <tr key={i}>
                {Array.from({ length: 8 }).map((_, j) => (
                  <td key={j}><Sk w={j === 0 ? "70%" : "50%"} h={12} /></td>
                ))}
              </tr>
            )) : (projects?.length ?? 0) === 0 ? (
              <tr><td colSpan={8} className="mc-table-empty">No active projects.</td></tr>
            ) : projects.map((p) => {
              const grid = GRID_DOT[p.grid_status] || { glyph: "\u25CB", color: "var(--cds-text-helper)" };
              const isHover = hover === p.project_id;
              return (
                <tr
                  key={p.project_id}
                  onClick={() => onSelectProject?.(p.project_id)}
                  onMouseEnter={() => setHover(p.project_id)}
                  onMouseLeave={() => setHover(null)}
                  className={isHover ? "mc-tr-hover" : ""}
                >
                  <td className="mc-td-name">{p.name}</td>
                  <td className="mc-td-type">{WORKLOAD_LABEL[p.workload_type] || p.workload_type || "—"}</td>
                  <td><VerdictPill verdict={p.verdict} /></td>
                  <td className="mc-th-num mc-td-mono">{p.irr_pct != null ? `${Number(p.irr_pct).toFixed(1)}%` : "—"}</td>
                  <td className="mc-th-num">
                    <span style={{ color: grid.color, fontSize: 14 }}>{grid.glyph}</span>
                    <span className="mc-td-muted" style={{ marginLeft: 6 }}>{p.grid_status_label}</span>
                  </td>
                  <td className="mc-th-num mc-td-mono">{p.planning_pct != null ? `${p.planning_pct}%` : "—"}</td>
                  <td className="mc-td-next">
                    {p.next_action}
                    <span className="mc-td-muted mc-td-mono" style={{ marginLeft: 8 }}>
                      ({fmtDeadline(p.next_action_due_days)})
                    </span>
                  </td>
                  <td className="mc-td-arr">{isHover ? "\u2192" : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   Main component
   ─────────────────────────────────────────────────────────── */
export default function Dashboard({
  onSelectProject = () => {},
  onNewProject = () => {},
  onSelectEntity = null,
  onOpenInbox = null,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
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

  const metrics = data?.metrics || {};
  const projects = data?.active_projects || [];
  const signals = data?.live_signals || [];
  const activity = data?.activity_feed || [];

  const handleActivityClick = (a) => {
    if (onSelectEntity) {
      onSelectEntity({
        entity_type: a.entity_type || (a.project_id ? "project" : null),
        entity_id: a.entity_id || a.project_id,
        project_id: a.project_id,
      });
    } else if (a.project_id) {
      onSelectProject(a.project_id);
    }
  };

  if (error && !loading) {
    return (
      <div className="mc-root mc-root-err">
        <div className="mc-err-card">
          <div className="mc-err-title">Couldn't load Mission Control</div>
          <div className="mc-err-sub">{error}</div>
          <button type="button" className="mc-err-retry" onClick={load}>Retry</button>
        </div>
        <style>{dashboardCss}</style>
      </div>
    );
  }

  return (
    <div className="mc-root">
      <header className="mc-top">
        <div className="mc-top-left">
          <img src="/logo-princeps.png" alt="" width="28" height="28" className="mc-logo" />
          <span className="mc-brand">PRINCEPS</span>
          <span className="mc-kicker">Mission Control</span>
        </div>
        <div className="mc-top-actions">
          {onOpenInbox && (
            <button type="button" className="mc-btn mc-btn-ghost" onClick={onOpenInbox}>
              Ingest from email
            </button>
          )}
          <button type="button" className="mc-btn mc-btn-primary" onClick={onNewProject}>
            + New project
          </button>
        </div>
      </header>

      {/* ── 3-card hero ── */}
      <section className="mc-hero" aria-label="Portfolio summary">
        <PortfolioKpiCard metrics={metrics} projects={projects} loading={loading} />
        <StageFunnelCard projects={projects} loading={loading} />
        <RecentActivityCard
          activity={activity}
          signals={signals}
          loading={loading}
          onActivityClick={handleActivityClick}
        />
      </section>

      {/* ── Active projects table ── */}
      <ActiveProjectsTable
        projects={projects}
        loading={loading}
        onSelectProject={onSelectProject}
      />

      <style>{dashboardCss}</style>
    </div>
  );
}

const dashboardCss = `
  .mc-root {
    min-height: 100%;
    padding: 24px 32px 40px;
    background: var(--bg);
    color: var(--cds-text-primary);
    font-family: "DM Sans", -apple-system, sans-serif;
  }
  .mc-root-err { display: flex; align-items: center; justify-content: center; }
  .mc-err-card {
    background: rgba(220,38,38,0.08);
    color: var(--cds-support-error);
    border: 1px solid var(--cds-support-error);
    padding: 18px 24px; border-radius: 8px;
    max-width: 520px; margin: 80px auto;
  }
  .mc-err-title { font-weight: 700; margin-bottom: 6px; font-size: 14px; }
  .mc-err-sub { font-size: 12px; margin-bottom: 12px; opacity: 0.9; }
  .mc-err-retry {
    background: var(--cds-support-error); color: #fff; border: none;
    padding: 8px 16px; border-radius: 4px; cursor: pointer;
    font: inherit; font-weight: 600; font-size: 12px;
  }

  /* ── Top bar ── */
  .mc-top {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 20px;
  }
  .mc-top-left { display: flex; align-items: center; gap: 10px; }
  .mc-logo { object-fit: contain; }
  .mc-brand {
    font-weight: 700; letter-spacing: 0.18em; font-size: 13px;
    color: var(--ink);
  }
  .mc-kicker {
    font-size: 10px; letterSpacing: 0.12em; text-transform: uppercase;
    color: var(--cds-text-helper); font-weight: 600; margin-left: 8px;
    letter-spacing: 0.12em;
  }
  .mc-top-actions { display: flex; gap: 10px; }
  .mc-btn {
    padding: 8px 16px; border-radius: 4px;
    font: inherit; font-weight: 600; font-size: 12px;
    cursor: pointer; letter-spacing: 0.03em;
    transition: background 120ms ease, transform 120ms ease;
  }
  .mc-btn-ghost {
    background: transparent; color: var(--ink);
    border: 1px solid var(--cds-border-subtle);
  }
  .mc-btn-ghost:hover { border-color: var(--gold); color: var(--gold-dark); }
  .mc-btn-primary {
    background: var(--gold); color: var(--ink); border: none;
  }
  .mc-btn-primary:hover { background: var(--gold-dark); color: #fff; }

  /* ── 3-card hero ── */
  .mc-hero {
    display: grid; grid-template-columns: 1.15fr 1fr 1fr;
    gap: 16px; margin-bottom: 24px;
  }
  .mc-hero-card {
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle);
    border-radius: 8px;
    padding: 18px 20px;
    min-height: 230px;
    display: flex; flex-direction: column;
  }
  .mc-hero-primary {
    background: linear-gradient(180deg, #FFFBF0 0%, #fff 60%);
    border-color: rgba(var(--accent-rgb), 0.4);
  }
  .mc-hero-head { margin-bottom: 14px; }
  .mc-hero-eyebrow {
    font-size: 9px; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--gold-dark);
  }
  .mc-hero-title {
    margin: 4px 0 0; font-size: 15px; font-weight: 700; color: var(--ink);
  }

  .mc-hero-hero-row {
    display: flex; gap: 24px; margin-bottom: 16px;
  }
  .mc-big { flex: 1; min-width: 0; }
  .mc-big-value {
    font-family: var(--mono);
    font-size: 32px; font-weight: 700; line-height: 1;
    color: var(--ink);
    letter-spacing: -0.02em;
  }
  .mc-big-gold { color: var(--gold-dark); }
  .mc-big-lbl {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--cds-text-helper);
    margin-top: 8px;
  }
  .mc-hero-row-bot {
    display: flex; gap: 18px; margin-top: auto;
    padding-top: 14px;
    border-top: 1px solid rgba(var(--accent-rgb), 0.18);
  }
  .mc-rollup {
    display: flex; align-items: baseline; gap: 6px;
  }
  .mc-rollup-num {
    font-family: var(--mono); font-size: 18px; font-weight: 700;
    color: var(--ink);
  }
  .mc-rollup-lbl {
    font-size: 10px; font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--cds-text-helper);
  }

  /* Funnel */
  .mc-funnel { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .mc-funnel-row {
    display: grid; grid-template-columns: 82px 1fr 24px;
    gap: 10px; align-items: center;
  }
  .mc-funnel-lbl {
    font-size: 10px; font-weight: 600; letter-spacing: 0.04em;
    color: var(--cds-text-secondary);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .mc-funnel-bar-wrap {
    height: 10px; background: var(--cds-layer-02); border-radius: 3px;
    overflow: hidden;
  }
  .mc-funnel-bar {
    display: block; height: 100%;
    background: linear-gradient(90deg, var(--gold) 0%, var(--gold-light) 100%);
    transition: width 220ms ease;
  }
  .mc-funnel-num {
    font-family: var(--mono); font-size: 12px; font-weight: 700;
    color: var(--ink); text-align: right;
  }

  /* Activity */
  .mc-activity-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .mc-activity-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid var(--cds-border-subtle);
    font-size: 12px;
  }
  .mc-activity-row:last-child { border-bottom: none; }
  .mc-activity-clickable { cursor: pointer; }
  .mc-activity-clickable:hover { color: var(--gold-dark); }
  .mc-activity-glyph {
    width: 18px; height: 18px;
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--cds-text-helper); font-size: 13px;
    flex-shrink: 0;
  }
  .mc-activity-text {
    flex: 1; color: inherit;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .mc-activity-when {
    font-family: var(--mono); font-size: 10px;
    color: var(--cds-text-helper); flex-shrink: 0;
  }
  .mc-activity-empty {
    padding: 32px 0; text-align: center;
    font-size: 12px; color: var(--cds-text-helper);
  }
  .mc-activity-sk .mc-activity-row {
    border-bottom: none; padding: 6px 0;
  }

  /* Shimmer */
  .mc-sk {
    display: inline-block;
    border-radius: 3px;
    background: linear-gradient(90deg, var(--cds-layer-02) 0%, var(--cds-layer-03) 50%, var(--cds-layer-02) 100%);
    background-size: 200% 100%;
    animation: mc-shimmer 1.4s ease-in-out infinite;
  }
  @keyframes mc-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  /* ── Table ── */
  .mc-table-wrap {
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle);
    border-radius: 8px;
    overflow: hidden;
  }
  .mc-table-head {
    padding: 12px 20px;
    border-bottom: 1px solid var(--cds-border-subtle);
    display: flex; align-items: center; justify-content: space-between;
    font-size: 10px; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--cds-text-helper);
  }
  .mc-table-count {
    font-family: var(--mono); color: var(--ink);
    letter-spacing: 0.04em;
  }
  .mc-table-scroll { overflow-x: auto; }
  .mc-table {
    width: 100%; border-collapse: collapse; font-size: 13px;
  }
  .mc-table th {
    text-align: left; padding: 12px 16px;
    border-bottom: 1px solid var(--cds-border-subtle);
    font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--cds-text-helper); font-weight: 700;
  }
  .mc-table th.mc-th-num, .mc-table td.mc-th-num { text-align: right; }
  .mc-table td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--cds-border-subtle);
    color: var(--cds-text-primary);
  }
  .mc-tr-hover { background: #FFFBF0; cursor: pointer; }
  .mc-td-name { font-weight: 500; }
  .mc-td-type { color: var(--cds-text-helper); font-size: 12px; }
  .mc-td-mono { font-family: var(--mono); }
  .mc-td-muted { color: var(--cds-text-helper); font-size: 12px; }
  .mc-td-next { font-size: 12px; }
  .mc-td-arr { text-align: right; color: var(--cds-text-helper); font-size: 14px; }
  .mc-table-empty { padding: 32px; text-align: center; color: var(--cds-text-helper); }
  .mc-pill {
    display: inline-flex; align-items: center;
    padding: 3px 8px; border-radius: 3px;
    font-family: "DM Sans", sans-serif; font-weight: 700;
    font-size: 10px; letter-spacing: 0.06em;
  }

  @media (max-width: 1100px) {
    .mc-hero { grid-template-columns: 1fr 1fr; }
    .mc-hero > :nth-child(3) { grid-column: 1 / -1; }
  }
  @media (max-width: 720px) {
    .mc-root { padding: 16px; }
    .mc-hero { grid-template-columns: 1fr; }
    .mc-hero > :nth-child(3) { grid-column: auto; }
    .mc-top { flex-wrap: wrap; gap: 12px; }
  }
`;
