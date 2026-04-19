import React, { useState } from "react";
import Provenance from "../Provenance";

/**
 * TestFitTab — auto-layout solver for a candidate site.
 * Given a parcel polygon + workload (BESS or DC), returns auto-placed rows,
 * substations, cable runs, and setback compliance. Backend: POST /api/sites/test-fit
 */
export default function TestFitTab({ project }) {
  const [workload, setWorkload] = useState(project?.workload_type || "bess");
  const [capacity, setCapacity] = useState(project?.workload_type === "dc" ? 50 : 100);
  const [loading, setLoading] = useState(false);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState(null);

  const onRun = async () => {
    if (!project?.project_id) return;
    setLoading(true); setError(null); setFit(null);
    try {
      const res = await fetch("/api/sites/test-fit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.project_id,
          workload_type: workload,
          target_capacity_mw: Number(capacity),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFit(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tf-tab">
      <header className="tf-head">
        <div className="tf-eyebrow">Site engineering</div>
        <h2 className="tf-title">Test-fit</h2>
        <p className="tf-lede">
          Auto-place rows, substation, cable runs, and setbacks on the parcel. Returns
          a feasible layout, fit ratio, and the binding constraint — in seconds, not weeks.
        </p>
      </header>

      <section className="tf-controls">
        <label className="tf-field">
          <span className="tf-field-label">Workload</span>
          <select className="tf-input" value={workload} onChange={(e) => setWorkload(e.target.value)}>
            <option value="bess">BESS</option>
            <option value="solar">Solar PV</option>
            <option value="dc">Data Centre</option>
          </select>
        </label>
        <label className="tf-field">
          <span className="tf-field-label">Target capacity (MW)</span>
          <input className="tf-input" type="number" min="1" max="500"
            value={capacity} onChange={(e) => setCapacity(e.target.value)} />
        </label>
        <button className="tf-cta" onClick={onRun} disabled={loading || !project}>
          {loading ? "Solving…" : "Run test-fit"}
        </button>
      </section>

      {error && <div className="tf-msg tf-err">Test-fit failed: {error}</div>}

      {fit && (
        <section className="tf-result">
          <div className="tf-result-row">
            <div className="tf-stat">
              <div className="tf-stat-label">Achievable capacity</div>
              <div className="tf-stat-value">{fit.achievable_mw ?? "—"} <span className="tf-unit">MW</span></div>
              <Provenance source="Parcel area · UK rate cards" pathway="11kV £80k/km baseline" />
            </div>
            <div className="tf-stat">
              <div className="tf-stat-label">Fit ratio</div>
              <div className="tf-stat-value">{fit.fit_ratio != null ? Math.round(fit.fit_ratio * 100) : "—"}<span className="tf-unit">%</span></div>
            </div>
            <div className="tf-stat">
              <div className="tf-stat-label">Binding constraint</div>
              <div className="tf-stat-value tf-stat-value-text">{fit.binding_constraint || "—"}</div>
            </div>
          </div>
          {Array.isArray(fit.notes) && fit.notes.length > 0 && (
            <ul className="tf-notes">
              {fit.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </section>
      )}

      <style>{`
        .tf-tab { padding: 32px 40px; max-width: 960px; }
        .tf-head { margin-bottom: 28px; }
        .tf-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .tf-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .tf-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .tf-controls { display: flex; gap: 16px; align-items: end; flex-wrap: wrap;
          padding: 20px 0; border-bottom: 1px solid var(--cds-border-subtle); margin-bottom: 24px; }
        .tf-field { display: flex; flex-direction: column; gap: 6px; }
        .tf-field-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); }
        .tf-input { padding: 8px 12px; border: 1px solid var(--cds-border-subtle); border-radius: 6px;
          background: var(--cds-layer-01); font-family: inherit; font-size: 13px;
          color: var(--ink); min-width: 160px; }
        .tf-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 10px 18px; font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
        .tf-cta:hover:not(:disabled) { background: var(--gold-dark); }
        .tf-cta:disabled { opacity: 0.4; cursor: not-allowed; }
        .tf-msg { padding: 14px 18px; color: var(--cds-text-helper); font-size: 13px;
          font-family: var(--mono); }
        .tf-err { color: #c0392b; }
        .tf-result-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        .tf-stat { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .tf-stat-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 10px; }
        .tf-stat-value { font-size: 28px; font-weight: 600; color: var(--ink); line-height: 1; }
        .tf-stat-value-text { font-size: 16px; font-weight: 500; }
        .tf-unit { font-size: 14px; color: var(--cds-text-helper); margin-left: 4px; font-weight: 400; }
        .tf-notes { margin-top: 18px; padding-left: 20px; font-size: 13px; line-height: 1.55;
          color: var(--cds-text-secondary); }
        .tf-notes li { margin-bottom: 6px; }
      `}</style>
    </div>
  );
}
