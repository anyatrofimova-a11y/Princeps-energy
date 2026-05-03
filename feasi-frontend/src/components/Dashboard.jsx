import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { STAGES, STAGE_INDEX } from "../lib/stage_workflow";
import GridCanvas from "./GridCanvas";
import LiveBessRevenue from "./bess/LiveBessRevenue";

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
          const onOpen = () => {
            // Switch to the projects view filtered by this stage. The
            // event is handled by CenterCanvas which flips activeViewMode
            // and stashes the filter for RedesignLayout to consume.
            window.dispatchEvent(new CustomEvent("princeps:open-projects-by-stage", {
              detail: { stage: s.key, label: s.label },
            }));
          };
          return (
            <li
              key={s.key}
              className="mc-funnel-row mc-funnel-row-click"
              onClick={onOpen}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}
              title={`Open projects at ${s.label} stage`}
            >
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
  // Dedupe by project_id — backend mission-control feed occasionally returns
  // the same project twice when joined against multi-verdict runs, which
  // otherwise shows up as ghost duplicates (e.g. Thames BESS GO + CAUTION).
  const dedupedProjects = React.useMemo(() => {
    if (!Array.isArray(projects)) return [];
    const seen = new Set();
    const out = [];
    for (const p of projects) {
      const id = p?.project_id;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(p);
    }
    return out;
  }, [projects]);
  return (
    <div className="mc-table-wrap">
      <div className="mc-table-head">
        <span className="mc-table-eyebrow">Active projects</span>
        <span className="mc-table-count">{loading ? "—" : dedupedProjects.length}</span>
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
            )) : dedupedProjects.length === 0 ? (
              <tr><td colSpan={8} className="mc-table-empty">No active projects.</td></tr>
            ) : dedupedProjects.map((p) => {
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

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  const firstName = useMemo(() => {
    try {
      const stored = localStorage.getItem("princeps.user.firstName");
      if (stored && stored.trim()) return stored.trim();
      const email = localStorage.getItem("princeps.user.email") || "";
      const local = email.split("@")[0] || "";
      const first = local.split(/[._-]/)[0] || "";
      if (first) return first.charAt(0).toUpperCase() + first.slice(1);
    } catch {}
    return "Anya";
  }, []);
  const greeting = useMemo(() => {
    const h = now.getHours();
    if (h < 5) return "Working late";
    if (h < 12) return "Good morning";
    if (h < 18) return "Good afternoon";
    return "Good evening";
  }, [now]);
  const dateStr = now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const timeStr = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

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
      <GridCanvas className="mc-bg-canvas" />
      <header className="mc-top">
        <div className="mc-top-left">
          <img src="/logo-princeps.png" alt="" width="28" height="28" className="mc-logo" />
          <div className="mc-top-title">
            <div className="mc-top-title-row">
              <span className="mc-brand">PRINCEPS</span>
              <span className="mc-kicker">Mission Control</span>
            </div>
            <div className="mc-welcome">
              <span className="mc-welcome-greet">{greeting}, {firstName}</span>
              <span className="mc-welcome-sep">·</span>
              <span className="mc-welcome-date">{dateStr}</span>
              <span className="mc-welcome-sep">·</span>
              <span className="mc-welcome-time">{timeStr}</span>
            </div>
          </div>
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

      {/* ── Live BESS revenue widget (WebSocket + Modo overlay) ── */}
      <LiveBessRevenue />

      {/* ── Princeps Tools — links to the new Foundry/Warp-Speed surfaces ── */}
      <PrincepsToolsCard />

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

function PrincepsToolsCard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);

  // Live counts fetched in parallel — every tile shows real telemetry.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [datasets, modules, councils, repd, substations, projects] = await Promise.all([
          fetch("/api/datasets").then(r => r.ok ? r.json() : null).catch(() => null),
          fetch("/api/workshop/modules").then(r => r.ok ? r.json() : null).catch(() => null),
          fetch("/api/council/sessions?limit=5").then(r => r.ok ? r.json() : null).catch(() => null),
          fetch("/api/objects/REPDProject?limit=1").then(r => r.ok ? r.json() : null).catch(() => null),
          fetch("/api/objects/Substation?limit=1").then(r => r.ok ? r.json() : null).catch(() => null),
          fetch("/api/objects/Project?limit=1").then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        if (cancelled) return;
        const ds = datasets?.datasets || datasets || [];
        const dsHealth = ds.reduce((a, d) => {
          const h = d.health_status || "unknown";
          a[h] = (a[h] || 0) + 1;
          return a;
        }, {});
        setStats({
          datasets_total: ds.length,
          datasets_green: dsHealth.green || 0,
          datasets_yellow: dsHealth.yellow || 0,
          datasets_red: dsHealth.red || 0,
          datasets_rows: ds.reduce((s, d) => s + (d.last_row_count || 0), 0),
          modules_total: (modules?.modules || []).length,
          council_recent: (councils?.sessions || councils || []).length,
          repd_total: repd?.count_estimated || repd?.count || (repd?.items || []).length || 0,
          subs_total: substations?.count_estimated || substations?.count || (substations?.items || []).length || 0,
          projects_total: projects?.count_estimated || projects?.count || (projects?.items || []).length || 0,
        });
      } catch (e) { /* swallow */ }
      finally { if (!cancelled) setLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // Each tile: chip, title, sub, optional badge (live count), optional health pills.
  const fmtNum = (n) => n == null ? "—" : Number(n).toLocaleString();

  const tiles = [
    {
      to: "/v2/builder", chip: "Workshop", title: "Module Builder",
      sub: "AI composes Workshop modules from DTDL", icon: "🛠",
      badge: stats.modules_total != null ? `${stats.modules_total} saved` : null,
    },
    {
      to: "/v2/council", chip: "Agentic", title: "Council Session",
      sub: "GRID + BESS + DC pods + Adjudicator (SSE)", icon: "▤",
      badge: stats.council_recent ? `${stats.council_recent} recent` : "demo",
    },
    {
      to: "/v2/datasets", chip: "Data", title: "Datasets Catalogue",
      sub: "Magritte connectors — refresh + health",
      badge: stats.datasets_total != null ? `${stats.datasets_total} live · ${fmtNum(stats.datasets_rows)} rows` : null,
      health: { green: stats.datasets_green, yellow: stats.datasets_yellow, red: stats.datasets_red },
    },
    {
      to: "/v2/object/Project", chip: "Ontology", title: "Object Browser",
      sub: "All typed objects — Project, Site, Substation, REPD, NSIP, TEC, Entity",
      badge: stats.projects_total ? `${stats.projects_total}+ Projects` : null,
    },
    {
      to: "/v2/object/REPDProject", chip: "Spatial", title: "REPD Map View",
      sub: "Map + table split — every UK renewable project",
      badge: "13,995 projects",
    },
    {
      to: "/v2/object/Substation", chip: "Spatial", title: "Substations",
      sub: "Grid asset map — DNO + voltage filter",
      badge: "71,912 substations",
    },
    {
      to: "/v2/object/NSIPProject", chip: "Pipeline", title: "NSIP / DCO",
      sub: "Nationally Significant Infrastructure register",
      badge: "30 projects",
    },
    {
      to: "/v2/quiver/REPDProject", chip: "Charts", title: "Quiver",
      sub: "Cross-filter scatter / bar charts over any typed object set",
      badge: "X·Y axes",
    },
    {
      to: "/v2/solutions", chip: "Marketplace", title: "Solutions",
      sub: "Installable Slate dashboards — BESS, DC, Ops, Grid, Risk",
      badge: "5 packages",
    },
    {
      to: "/v2/sets", chip: "Ontology", title: "Object Sets",
      sub: "Saved typed queries with union / intersect / subtract",
      badge: "set algebra",
    },
    {
      to: "/v2/pipelines", chip: "Pipelines", title: "Pipeline Builder",
      sub: "Declarative DAGs — connectors → SQL transforms → CTAS sinks",
      badge: "DAG executor",
    },
    {
      to: "/v2/modules/bess-revenue-mvp", chip: "Module", title: "BESS Revenue Module",
      sub: "AI-composed manifest — live revenue stack",
      badge: "demo",
    },
    {
      kind: "lineage-trigger", chip: "Provenance", title: "Lineage Graph",
      sub: "Trace any connector → table → ontology class",
      badge: "click to open",
      onClick: () => window.dispatchEvent(new CustomEvent("princeps:lineage", {detail: {root: "bmrs_settlement_prices"}})),
    },
    {
      kind: "lender-im", chip: "Reports", title: "Lender IM PDF",
      sub: "30-page DC IM in 8s — pick a project below",
      badge: "ready",
      onClick: async () => {
        // Pick the first DC-tagged project; fall back to any project
        try {
          const r = await fetch("/api/objects/Project?technology=data_centre&limit=1");
          const j = await r.json();
          const id = j?.items?.[0]?.id;
          if (id) {
            window.location.href = `/api/dc/lender-im-pdf?project_id=${encodeURIComponent(id)}`;
            return;
          }
          const fb = await fetch("/api/objects/Project?limit=1").then(x => x.json());
          const fbid = fb?.items?.[0]?.id;
          if (fbid) window.location.href = `/api/dc/lender-im-pdf?project_id=${encodeURIComponent(fbid)}`;
        } catch (e) { alert("Couldn't auto-pick a project for the IM."); }
      },
    },
  ];

  return (
    <section className="px-tools-card" aria-label="Princeps tools">
      <div className="px-tools-head">
        <span className="px-tools-eyebrow">PRINCEPS · TOOLS</span>
        <span className="px-tools-sub">Foundry-grade surfaces — agentic, composable, audited</span>
        <span className="px-tools-stats">
          {loading ? "syncing…" : (
            <>
              <code>{stats.datasets_total}</code> connectors ·{" "}
              <code>{fmtNum(stats.datasets_rows)}</code> rows ·{" "}
              <code>{stats.modules_total}</code> modules
            </>
          )}
        </span>
      </div>

      <div className="px-tools-grid">
        {tiles.map((t, i) => {
          const isAction = t.kind === "lineage-trigger" || t.kind === "lender-im";
          const Tag = isAction ? "button" : Link;
          const tagProps = isAction
            ? { type: "button", onClick: t.onClick, className: "px-tool-tile" }
            : { to: t.to, className: "px-tool-tile" };
          return (
            <Tag key={i} {...tagProps}>
              <div className="px-tool-chip-row">
                <span className="px-tool-chip">{t.chip}</span>
                {t.badge && <span className="px-tool-badge">{t.badge}</span>}
              </div>
              <div className="px-tool-title">{t.title}</div>
              <div className="px-tool-sub">{t.sub}</div>
              {t.health && (t.health.green || t.health.yellow || t.health.red) ? (
                <div className="px-tool-health">
                  {t.health.green ? <span className="px-h px-h-g">{t.health.green}</span> : null}
                  {t.health.yellow ? <span className="px-h px-h-y">{t.health.yellow}</span> : null}
                  {t.health.red ? <span className="px-h px-h-r">{t.health.red}</span> : null}
                </div>
              ) : null}
              <div className="px-tool-arr">→</div>
            </Tag>
          );
        })}
      </div>

      <style>{`
        .px-tools-card {
          margin-top: 20px; padding: 18px 20px;
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(15,19,24,0.08);
          border-radius: 14px;
          box-shadow: 0 4px 24px rgba(15,19,24,0.06);
          backdrop-filter: blur(10px);
          position: relative; z-index: 1;
        }
        .px-tools-head {
          display: flex; align-items: baseline; gap: 12px;
          margin-bottom: 14px; flex-wrap: wrap;
        }
        .px-tools-eyebrow {
          font-size: 10px; letter-spacing: 0.12em; font-weight: 700;
          color: #F5B731; font-family: "DM Sans", sans-serif;
        }
        .px-tools-sub { font-size: 11.5px; color: #5A5F66; }
        .px-tools-stats {
          margin-left: auto;
          font-family: "JetBrains Mono", monospace;
          font-size: 10.5px;
          color: #5A5F66;
          font-variant-numeric: tabular-nums;
        }
        .px-tools-stats code {
          background: rgba(245,183,49,0.15);
          padding: 1px 5px;
          border-radius: 4px;
          color: #4A3208;
          font-weight: 600;
        }
        .px-tools-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 10px;
        }
        .px-tool-tile {
          display: block; padding: 14px 14px 16px; text-decoration: none;
          color: inherit; text-align: left;
          background: linear-gradient(180deg, #FBF8F2 0%, #F2F3F5 100%);
          border: 1px solid rgba(15,19,24,0.08);
          border-radius: 10px;
          transition: transform 80ms, border-color 100ms, box-shadow 100ms;
          position: relative; cursor: pointer;
          font-family: inherit;
          width: 100%;
        }
        .px-tool-tile:hover {
          transform: translateY(-1px);
          border-color: #F5B731;
          box-shadow: 0 6px 18px rgba(245,183,49,0.15);
        }
        .px-tool-chip-row {
          display: flex; align-items: center; gap: 6px;
          margin-bottom: 8px;
        }
        .px-tool-chip {
          display: inline-block; font-size: 9px; letter-spacing: 0.08em;
          text-transform: uppercase; font-weight: 600;
          padding: 2px 6px; border-radius: 999px;
          background: rgba(245,183,49,0.18); color: #4A3208;
        }
        .px-tool-badge {
          font-size: 9.5px;
          color: #5A5F66;
          background: rgba(255,255,255,0.7);
          border: 1px solid rgba(15,19,24,0.08);
          padding: 2px 6px;
          border-radius: 4px;
          font-family: "JetBrains Mono", monospace;
          font-variant-numeric: tabular-nums;
        }
        .px-tool-title {
          font-size: 13px; font-weight: 600; color: #0F1318;
          font-family: "DM Sans", sans-serif;
        }
        .px-tool-sub {
          font-size: 11px; color: #5A5F66;
          margin-top: 3px; line-height: 1.40;
        }
        .px-tool-health {
          display: flex; gap: 4px; margin-top: 8px;
        }
        .px-h {
          font-family: "JetBrains Mono", monospace;
          font-size: 10px; padding: 1px 6px; border-radius: 4px;
          font-weight: 600;
        }
        .px-h-g { background: rgba(34,197,94,0.18); color: #166534; }
        .px-h-y { background: rgba(245,183,49,0.20); color: #854D0E; }
        .px-h-r { background: rgba(239,68,68,0.18); color: #991B1B; }
        .px-tool-arr { position: absolute; top: 14px; right: 14px; color: #94A3B8; font-size: 14px; }
        .px-tool-tile:hover .px-tool-arr { color: #F5B731; }
      `}</style>
    </section>
  );
}

const dashboardCss = `
  .mc-root {
    min-height: 100%;
    padding: 24px 32px 40px;
    background: var(--bg);
    color: var(--cds-text-primary);
    font-family: "DM Sans", -apple-system, sans-serif;
    position: relative;
  }
  /* Subtle animated grid-node network behind Mission Control content
     (same GridCanvas component chat rail uses). GridCanvas internally
     paints at rgba(90,100,120,0.5) node / 0.25 edge alpha, so we don't
     additionally dim here — leaving the outer opacity at 1 keeps the
     gold pulses readable against the #F7F8FA page background. */
  .mc-bg-canvas {
    position: absolute !important;
    inset: 0 !important;
    pointer-events: none !important;
    z-index: 0 !important;
  }
  /* Ensure every direct child of .mc-root (header, card grid, active-
     projects table, etc.) sits above the canvas + vignette. */
  .mc-root > header,
  .mc-root > section,
  .mc-root > div,
  .mc-root > article { position: relative; z-index: 2; }
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
  .mc-top-left { display: flex; align-items: center; gap: 12px; }
  .mc-logo { object-fit: contain; flex-shrink: 0; }
  .mc-top-title { display: flex; flex-direction: column; gap: 4px; line-height: 1.15; }
  .mc-top-title-row { display: flex; align-items: baseline; gap: 8px; }
  .mc-welcome {
    display: flex; align-items: baseline; gap: 8px;
    font-size: 12px; color: var(--cds-text-helper);
    font-weight: 500; letter-spacing: 0.01em;
  }
  .mc-welcome-greet { color: var(--ink); font-weight: 600; }
  .mc-welcome-sep { opacity: 0.4; }
  .mc-welcome-time { font-variant-numeric: tabular-nums; }
  .mc-brand {
    font-weight: 700; letter-spacing: 0.18em; font-size: 13px;
    color: var(--ink);
  }
  .mc-kicker {
    font-size: 10px; letterSpacing: 0.12em; text-transform: uppercase;
    color: var(--cds-text-helper); font-weight: 600; margin-left: 0;
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
