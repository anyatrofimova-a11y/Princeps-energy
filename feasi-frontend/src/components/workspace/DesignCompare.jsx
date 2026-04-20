import React, { useState, useEffect, useMemo } from "react";
import { listLayouts, getLayout } from "../../services/design";

/**
 * DesignCompare — two-layout side-by-side viewer. Opens as a slide-over
 * within the Decide tab (z-index above its content) so users can compare
 * COA scenarios without losing project context.
 */

const COMPARE_KPIS = [
  { key: "effective_capacity_mw", label: "Capacity", unit: "MW", fmt: (v) => v?.toFixed(1) },
  { key: "energy_mwh", label: "Energy", unit: "MWh", fmt: (v) => v?.toFixed(0) },
  { key: "capex_gbp_m", label: "CAPEX", unit: "£M", fmt: (v) => v?.toFixed(2) },
  { key: "annual_revenue_gbp_m", label: "Revenue/yr", unit: "£M", fmt: (v) => v?.toFixed(2) },
  { key: "irr_pct", label: "IRR", unit: "%", fmt: (v) => v?.toFixed(1) },
  { key: "lcoe_gbp_per_mwh", label: "LCOE", unit: "£/MWh", fmt: (v) => v?.toFixed(0) },
  { key: "npv_gbp_m", label: "NPV", unit: "£M", fmt: (v) => v?.toFixed(2) },
];

function deltaSign(a, b, lowerBetter = false) {
  if (a == null || b == null) return null;
  const diff = b - a;
  if (Math.abs(diff) < 1e-6) return "neutral";
  const positive = diff > 0;
  if (lowerBetter) return positive ? "worse" : "better";
  return positive ? "better" : "worse";
}

export default function DesignCompare({ candidateId = null, projectId = null,
                                          isOpen = false, onClose = () => {} }) {
  const [layouts, setLayouts] = useState([]);
  const [leftId, setLeftId] = useState(null);
  const [rightId, setRightId] = useState(null);
  const [left, setLeft] = useState(null);
  const [right, setRight] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    (async () => {
      try {
        const res = await listLayouts(candidateId ? { candidate_id: candidateId }
                                                   : { project_id: projectId });
        const list = res.layouts || [];
        setLayouts(list);
        if (list.length >= 1 && !leftId) setLeftId(list[0].layout_id);
        if (list.length >= 2 && !rightId) setRightId(list[1].layout_id);
      } catch (e) { setError(e.message); }
    })();
  }, [isOpen, candidateId, projectId]);

  useEffect(() => { if (leftId) getLayout(leftId).then(setLeft).catch((e) => setError(e.message)); }, [leftId]);
  useEffect(() => { if (rightId) getLayout(rightId).then(setRight).catch((e) => setError(e.message)); }, [rightId]);

  const rows = useMemo(() => {
    if (!left || !right) return [];
    return COMPARE_KPIS.map((def) => {
      const lowerBetter = ["capex_gbp_m", "lcoe_gbp_per_mwh"].includes(def.key);
      const lv = left.kpis?.[def.key];
      const rv = right.kpis?.[def.key];
      return {
        ...def,
        lv, rv,
        sign: deltaSign(lv, rv, lowerBetter),
        delta: lv != null && rv != null ? rv - lv : null,
      };
    });
  }, [left, right]);

  if (!isOpen) return null;

  return (
    <div className="dco-root">
      <header className="dco-head">
        <h2 className="dco-title">Compare designs</h2>
        <div className="dco-spacer" />
        <button className="dco-close" onClick={onClose}>×</button>
      </header>
      {error && <div className="dco-err">⚠ {error}</div>}
      <div className="dco-body">
        <div className="dco-col">
          <select className="dco-sel" value={leftId || ""} onChange={(e) => setLeftId(e.target.value)}>
            <option value="" disabled>Pick a design…</option>
            {layouts.map((l) => (
              <option key={l.layout_id} value={l.layout_id}>
                {l.is_preferred ? "★ " : ""}{l.name || l.layout_id.slice(0, 8)}
              </option>
            ))}
          </select>
          <LayoutCard l={left} />
        </div>
        <div className="dco-kpis">
          <div className="dco-kpi-title">Δ KPIs</div>
          {rows.map((r) => (
            <div key={r.key} className="dco-kpi-row">
              <div className="dco-kpi-lbl">{r.label}</div>
              <div className="dco-kpi-vals">
                <span>{r.fmt(r.lv)}</span>
                <span className={"dco-arrow dco-arrow-" + (r.sign || "neutral")}>→</span>
                <span>{r.fmt(r.rv)}</span>
              </div>
              {r.delta != null && (
                <div className={"dco-delta dco-delta-" + (r.sign || "neutral")}>
                  {r.delta > 0 ? "+" : ""}{r.fmt(r.delta)} {r.unit}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="dco-col">
          <select className="dco-sel" value={rightId || ""} onChange={(e) => setRightId(e.target.value)}>
            <option value="" disabled>Pick a design…</option>
            {layouts.map((l) => (
              <option key={l.layout_id} value={l.layout_id}>
                {l.is_preferred ? "★ " : ""}{l.name || l.layout_id.slice(0, 8)}
              </option>
            ))}
          </select>
          <LayoutCard l={right} />
        </div>
      </div>
      <style>{CSS}</style>
    </div>
  );
}

function LayoutCard({ l }) {
  if (!l) return <div className="dco-empty">Select a design to preview</div>;
  const kpis = l.kpis || {};
  return (
    <div className="dco-card">
      <div className="dco-card-meta">
        <span className="dco-wl">{l.workload?.toUpperCase()}</span>
        {l.is_preferred && <span className="dco-star">★ Preferred</span>}
      </div>
      <div className="dco-card-name">{l.name}</div>
      <div className="dco-card-date">{new Date(l.created_at).toLocaleString()}</div>
      <ul className="dco-reasoning">
        {(l.doc?.reasoning || []).slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
      </ul>
    </div>
  );
}

const CSS = `
  .dco-root {
    position: absolute; inset: 0;
    background: var(--cds-layer-02);
    z-index: 40;
    display: flex; flex-direction: column;
    font-family: "DM Sans", -apple-system, sans-serif;
  }
  .dco-head {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 20px;
    border-bottom: 1px solid var(--cds-border-subtle);
    background: var(--cds-layer-01);
  }
  .dco-title { margin: 0; font-size: 16px; font-weight: 700; color: var(--ink); }
  .dco-spacer { flex: 1; }
  .dco-close { background: none; border: none; font-size: 22px; cursor: pointer; color: var(--cds-text-helper); }
  .dco-err { padding: 10px 20px; background: rgba(220,38,38,0.1); color: var(--cds-support-error); font-size: 12px; }

  .dco-body {
    flex: 1; display: grid; grid-template-columns: 1fr 300px 1fr;
    gap: 16px; padding: 20px; overflow: auto;
  }
  .dco-col { display: flex; flex-direction: column; gap: 10px; }
  .dco-sel {
    padding: 8px 10px; border: 1px solid var(--cds-border-subtle);
    border-radius: 8px; background: var(--cds-layer-01);
    font-family: inherit; font-size: 12px;
    color: var(--ink);
  }

  .dco-card {
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle);
    border-radius: 12px; padding: 16px;
    display: flex; flex-direction: column; gap: 10px;
  }
  .dco-card-meta { display: flex; align-items: center; gap: 8px; }
  .dco-wl {
    background: rgba(var(--accent-rgb), 0.12); color: var(--gold-dark);
    padding: 2px 8px; border-radius: 4px;
    font-family: var(--mono); font-size: 10px; font-weight: 700;
  }
  .dco-star { color: var(--gold); font-size: 11px; font-weight: 600; }
  .dco-card-name { font-size: 14px; font-weight: 700; color: var(--ink); }
  .dco-card-date { font-family: var(--mono); font-size: 10px; color: var(--cds-text-helper); }
  .dco-empty { padding: 40px; text-align: center; color: var(--cds-text-helper); font-size: 13px; }

  .dco-reasoning { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .dco-reasoning li {
    position: relative; padding: 4px 6px 4px 16px;
    font-size: 11px; color: var(--cds-text-secondary); line-height: 1.4;
  }
  .dco-reasoning li::before { content: "•"; position: absolute; left: 4px; color: var(--gold); }

  .dco-kpis {
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle); border-radius: 12px;
    padding: 14px; display: flex; flex-direction: column; gap: 8px;
  }
  .dco-kpi-title {
    font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--cds-text-helper);
  }
  .dco-kpi-row { display: flex; flex-direction: column; gap: 2px; padding: 6px 0; border-bottom: 1px solid var(--cds-border-subtle); }
  .dco-kpi-row:last-child { border-bottom: none; }
  .dco-kpi-lbl { font-size: 11px; color: var(--cds-text-secondary); font-weight: 600; }
  .dco-kpi-vals {
    display: flex; align-items: center; gap: 6px;
    font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--ink);
  }
  .dco-arrow { font-size: 11px; }
  .dco-arrow-better { color: var(--cds-support-success); }
  .dco-arrow-worse { color: var(--cds-support-error); }
  .dco-arrow-neutral { color: var(--cds-text-helper); }
  .dco-delta { font-family: var(--mono); font-size: 10px; font-weight: 700; }
  .dco-delta-better { color: var(--cds-support-success); }
  .dco-delta-worse { color: var(--cds-support-error); }
  .dco-delta-neutral { color: var(--cds-text-helper); }
`;
