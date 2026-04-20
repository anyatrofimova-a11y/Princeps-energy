import React, { useEffect, useMemo, useState } from "react";

/**
 * HeroMetricStrip — top-of-project hero metrics row.
 *
 * Restructure 2026-04-19 (BOT-TT): rebalanced to 7 numeric tiles with no
 * duplication against the project hero or stage ribbon. The qualitative
 * "Grid: Constrained" tile was replaced with a numeric GRID HEADROOM (MW)
 * tile, since the qualitative state is already conveyed by the verdict-
 * coloured banner in the project hero. For DC workloads the strip shows:
 *   IT LOAD (MW) · PUE · GRID HEADROOM (MW) · IRR (%) · PLANNING (%) ·
 *   LCOE (£/MWh) · NPV (£m)
 * Non-DC workloads keep CAPACITY in place of IT LOAD and drop the PUE tile.
 *
 * Data sources (preferred order):
 *   1. GET /api/projects/{id}/kpis  (future contract — tolerated 404)
 *   2. project row itself (passed as prop `project`)
 *   3. workload defaults (matches backend `_stub_for` heuristic)
 *
 * Any metric whose `*_src` is not "metadata" or "stored" renders a derived
 * badge. When the whole response is flagged `stubbed:true` the entire strip
 * is marked in a subdued way.
 *
 * Styling rule (2026-04 redesign): DM Sans labels, JetBrains Mono numerals,
 * light-gold accent, white surface, soft border.
 */

const PLAN_TINT = (pct) => {
  if (pct == null) return "var(--cds-text-helper)";
  if (pct >= 70) return "var(--cds-support-success)";
  if (pct >= 50) return "var(--cds-support-warning)";
  return "var(--cds-support-error)";
};

const WORKLOAD_DEFAULTS = {
  bess:   { lcoe: 82, irr: 11.8, capex_mw: 0.66 },
  solar:  { lcoe: 55, irr: 9.2,  capex_mw: 0.90 },
  dc:     { lcoe: 72, irr: 14.2, capex_mw: 9.5  },
  wind:   { lcoe: 48, irr: 8.6,  capex_mw: 1.40 },
  hybrid: { lcoe: 60, irr: 11.2, capex_mw: 1.10 },
};

function _defaultsFor(workload) {
  return WORKLOAD_DEFAULTS[(workload || "").toLowerCase()] || WORKLOAD_DEFAULTS.solar;
}

/** Derive a full KPI block from the project row when no /kpis endpoint exists.
 *  Mirrors the server heuristic so the UI looks the same whether the backend
 *  ever ships /api/projects/{id}/kpis or not. */
function deriveKpisFromProject(project) {
  if (!project) return null;
  const meta = project.metadata || {};
  const workload = (project.technology || project.workload_type || "solar").toLowerCase();
  const cap = Number(project.capacity_mw) || 0;
  const stage = (project.stage || "prospect").toLowerCase();
  const blocker = (project.blocker || "").toLowerCase();
  const d = _defaultsFor(workload);
  const isDC = workload === "dc";

  // Capacity / IT load — for DC the headline number is IT load (MW)
  const itLoadStored = meta.it_load_mw;
  const it_load_mw = itLoadStored != null ? itLoadStored : (isDC ? cap : null);
  const it_load_src = itLoadStored != null ? "metadata" : (isDC && cap ? "derived" : "default");

  // PUE target (DC only)
  const pue_stored = meta.pue_target ?? meta.pue;
  const pue_target = pue_stored != null ? pue_stored : (isDC ? 1.25 : null);
  const pue_src = pue_stored != null ? "metadata" : (isDC ? "default" : "default");

  // Grid headroom (MW) — numeric replacement for the qualitative grid tile
  const headStored = meta.grid_headroom_mw ?? meta.headroom_mw;
  let grid_headroom_mw = headStored != null ? headStored : null;
  let grid_headroom_src = headStored != null ? "metadata" : "default";
  if (grid_headroom_mw == null) {
    if (/headroom|constrain|thermal|congest/.test(blocker)) {
      // Heuristic: constrained means roughly half of demand is short
      grid_headroom_mw = cap ? Math.max(0, Math.round(cap * 0.4)) : null;
      grid_headroom_src = "derived";
    } else if (cap) {
      // Best-effort default — assume comfortable headroom unless stated otherwise
      grid_headroom_mw = Math.round(cap * 1.2);
      grid_headroom_src = "default";
    }
  }

  // IRR
  const irrStored = meta.irr_pct;
  const irrDerived = irrStored == null && cap
    ? Math.round((d.irr + (cap > 75 ? 0.2 : 0) - (cap < 20 ? 0.5 : 0)) * 10) / 10
    : null;
  const irr_pct = irrStored != null ? irrStored : (irrDerived != null ? irrDerived : d.irr);
  const irr_src = irrStored != null ? "metadata" : (irrDerived != null ? "derived" : "default");

  // Planning
  const plan_stored = meta.planning_pct ?? meta.planning_probability;
  const planning_pct = plan_stored != null ? plan_stored : (stage === "prospect" ? 35 : 58);
  const planning_src = plan_stored != null ? "metadata" : "default";

  // LCOE
  const lcoe_stored = meta.lcoe_gbp_per_mwh ?? meta.lcoe;
  const lcoe_gbp_per_mwh = lcoe_stored != null ? lcoe_stored : d.lcoe;
  const lcoe_src = lcoe_stored != null ? "metadata" : "default";

  // NPV £m — stored, else heuristic from capex/IRR/cap
  const npv_stored = meta.npv_gbp_m ?? meta.npv_m;
  let npv_derived = null;
  if (npv_stored == null && cap) {
    const capex = cap * d.capex_mw;
    const multiple = workload === "dc" ? 0.45
                     : workload === "bess" ? 0.32
                     : 0.25;
    npv_derived = Math.round(capex * multiple * 10) / 10;
  }
  const npv_gbp_m = npv_stored != null ? npv_stored : (npv_derived != null ? npv_derived : null);
  const npv_src = npv_stored != null ? "metadata" : (npv_derived != null ? "derived" : "default");

  const stubbed = (
    irr_src !== "metadata"
    && lcoe_src !== "metadata"
    && planning_src !== "metadata"
    && npv_src !== "metadata"
    && grid_headroom_src !== "metadata"
  );

  return {
    workload,
    is_dc: isDC,
    capacity_mw: cap,
    capacity_src: cap ? "metadata" : "default",
    it_load_mw, it_load_src,
    pue_target, pue_src,
    grid_headroom_mw, grid_headroom_src,
    irr_pct, irr_src,
    planning_pct, planning_src,
    lcoe_gbp_per_mwh, lcoe_src,
    npv_gbp_m, npv_src,
    stubbed,
  };
}

function Metric({ label, value, sub, src, tint, valueNode, mono = true }) {
  const derived = src && src !== "metadata" && src !== "stored";
  return (
    <div className="hms-metric">
      <div className="hms-metric-row-top">
        <div className="hms-metric-label">{label}</div>
        {derived && <span className="hms-pill">derived</span>}
      </div>
      <div className={"hms-metric-value" + (mono ? " hms-metric-value-mono" : "")} style={tint ? { color: tint } : undefined}>
        {valueNode ?? (value ?? "—")}
      </div>
      {sub && <div className="hms-metric-sub">{sub}</div>}
    </div>
  );
}

export default function HeroMetricStrip({ project, projectId = null }) {
  const [remoteKpis, setRemoteKpis] = useState(null);
  const [fetchFailed, setFetchFailed] = useState(false);

  const pid = projectId || project?.project_id || null;

  // Attempt the real endpoint; quietly fall back to client-side derivation
  useEffect(() => {
    if (!pid) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/kpis`);
        if (!res.ok) { if (!cancelled) setFetchFailed(true); return; }
        const json = await res.json();
        if (!cancelled) setRemoteKpis(json);
      } catch {
        if (!cancelled) setFetchFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [pid]);

  const k = useMemo(() => remoteKpis || deriveKpisFromProject(project), [remoteKpis, project]);

  if (!project || !k) {
    return (
      <div className="hms-root hms-empty">
        <div className="hms-skeleton-row">
          {[1,2,3,4,5,6].map(i => <div key={i} className="hms-skeleton" />)}
        </div>
        <style>{hmsCss}</style>
      </div>
    );
  }

  // Lead tile: IT LOAD for DC (since the project IS a data centre), Capacity otherwise.
  const leadValue = k.is_dc
    ? (k.it_load_mw != null ? Number(k.it_load_mw).toFixed(0) : "—")
    : (k.capacity_mw ? Number(k.capacity_mw).toFixed(0) : "—");
  const leadSrc = k.is_dc ? k.it_load_src : k.capacity_src;
  const leadHasValue = k.is_dc ? k.it_load_mw != null : !!k.capacity_mw;

  return (
    <section className={"hms-root" + (k.stubbed ? " hms-stubbed" : "")} aria-label="Project hero metrics">
      <Metric
        label={k.is_dc ? "IT Load" : "Capacity"}
        src={leadSrc}
        value={leadValue}
        sub={leadHasValue ? "MW" : null}
      />
      {k.is_dc && (
        <Metric
          label="PUE"
          src={k.pue_src}
          value={k.pue_target != null ? Number(k.pue_target).toFixed(2) : "—"}
          sub={k.pue_target != null ? "target" : null}
        />
      )}
      <Metric
        label="Grid Headroom"
        src={k.grid_headroom_src}
        tint={k.grid_headroom_mw != null && k.is_dc && k.it_load_mw != null && k.grid_headroom_mw < k.it_load_mw
          ? "var(--cds-support-warning)" : undefined}
        value={k.grid_headroom_mw != null ? `${Number(k.grid_headroom_mw).toFixed(0)}` : "—"}
        sub={k.grid_headroom_mw != null ? "MW" : null}
      />
      <Metric
        label="IRR"
        src={k.irr_src}
        value={k.irr_pct != null ? `${Number(k.irr_pct).toFixed(1)}` : "—"}
        sub={k.irr_pct != null ? "%" : null}
      />
      <Metric
        label="Planning"
        src={k.planning_src}
        tint={PLAN_TINT(k.planning_pct)}
        value={k.planning_pct != null ? `${Math.round(k.planning_pct)}` : "—"}
        sub={k.planning_pct != null ? "% approval" : null}
      />
      <Metric
        label="LCOE"
        src={k.lcoe_src}
        value={k.lcoe_gbp_per_mwh != null ? `£${Math.round(k.lcoe_gbp_per_mwh)}` : "—"}
        sub={k.lcoe_gbp_per_mwh != null ? "/MWh" : null}
      />
      <Metric
        label="NPV"
        src={k.npv_src}
        value={k.npv_gbp_m != null ? `£${Number(k.npv_gbp_m).toFixed(1)}` : "—"}
        sub={k.npv_gbp_m != null ? "m" : null}
      />
      <style>{hmsCss}</style>
    </section>
  );
}

const hmsCss = `
  .hms-root {
    display: flex; flex-wrap: wrap; gap: 0;
    background: var(--cds-layer-01);
    border-bottom: 1px solid var(--cds-border-subtle);
    font-family: "DM Sans", -apple-system, sans-serif;
    position: relative;
  }
  .hms-empty { min-height: 86px; padding: 16px 24px; }
  .hms-skeleton-row { display: flex; gap: 16px; flex: 1; }
  .hms-skeleton {
    flex: 1; height: 50px; border-radius: 6px;
    background: linear-gradient(90deg, var(--cds-layer-02) 0%, var(--cds-layer-03) 50%, var(--cds-layer-02) 100%);
    background-size: 200% 100%;
    animation: hms-shimmer 1.4s ease-in-out infinite;
  }
  @keyframes hms-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .hms-metric {
    flex: 1; min-width: 124px;
    padding: 14px 18px;
    border-right: 1px solid var(--cds-border-subtle);
    display: flex; flex-direction: column; gap: 6px;
  }
  .hms-metric:last-child { border-right: none; }
  .hms-metric-row-top {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .hms-metric-label {
    font-size: 10px; font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--cds-text-helper);
    text-transform: uppercase;
  }
  .hms-pill {
    font-family: var(--mono); font-size: 8px; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase;
    padding: 1px 6px; border-radius: 3px;
    background: rgba(var(--accent-rgb), 0.14);
    color: var(--gold-dark);
  }
  .hms-metric-value {
    font-size: 26px; font-weight: 700; line-height: 1;
    color: var(--ink);
    letter-spacing: -0.02em;
  }
  .hms-metric-value-mono {
    font-family: var(--mono);
  }
  .hms-metric-sub {
    font-family: var(--mono);
    font-size: 11px; font-weight: 500;
    color: var(--cds-text-helper);
    letter-spacing: 0.02em;
  }
  /* Mobile: wrap every 2 to keep numerals legible */
  @media (max-width: 900px) {
    .hms-metric { flex-basis: 50%; min-width: 0; }
    .hms-metric:nth-child(2n) { border-right: none; }
    .hms-metric { border-bottom: 1px solid var(--cds-border-subtle); }
    .hms-metric:nth-last-child(-n+2) { border-bottom: none; }
  }
  @media (max-width: 520px) {
    .hms-metric { flex-basis: 100%; border-right: none; }
    .hms-metric-value { font-size: 22px; }
  }
`;
