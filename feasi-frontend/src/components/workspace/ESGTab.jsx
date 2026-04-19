import React, { useEffect, useState } from "react";
import Provenance from "../Provenance";

/**
 * ESGTab — sustainability scoring across embodied carbon, water, biodiversity (BNG),
 * and grid-carbon-intensity. Backend: GET /api/esg/score?project_id=…
 */
export default function ESGTab({ project }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!project?.project_id) return;
    let cancelled = false;
    setLoading(true); setError(null);
    fetch(`/api/esg/score?project_id=${project.project_id}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [project?.project_id]);

  const dims = data?.dimensions || [];
  const score = data?.composite_score;

  return (
    <div className="esg-tab">
      <header className="esg-head">
        <div className="esg-eyebrow">Sustainability</div>
        <h2 className="esg-title">ESG Score</h2>
        <p className="esg-lede">
          Composite sustainability profile across embodied carbon, water use,
          biodiversity (BNG), and grid carbon intensity — the dimensions hyperscaler
          and lender RFPs request.
        </p>
      </header>

      {loading && <div className="esg-msg">Computing score…</div>}
      {error && <div className="esg-msg esg-err">Score failed: {error}</div>}

      {data && (
        <>
          <section className="esg-score">
            <div className="esg-score-num">{score != null ? Math.round(score) : "—"}</div>
            <div className="esg-score-label">composite ESG score · 0–100</div>
            <Provenance source="REPD 2024 Q1 + Carbon Intensity API" fetchedAt={new Date().toISOString()} />
          </section>

          <section className="esg-grid">
            {dims.map((d) => (
              <div key={d.key} className="esg-cell">
                <div className="esg-cell-label">{d.label}</div>
                <div className="esg-cell-value">{d.score != null ? Math.round(d.score) : "—"}</div>
                <div className="esg-cell-detail">{d.detail || ""}</div>
              </div>
            ))}
          </section>
        </>
      )}

      <style>{`
        .esg-tab { padding: 32px 40px; max-width: 960px; }
        .esg-head { margin-bottom: 32px; }
        .esg-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .esg-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .esg-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .esg-msg { padding: 18px; color: var(--cds-text-helper); font-size: 13px;
          font-family: var(--mono); }
        .esg-err { color: #c0392b; }
        .esg-score { padding: 28px 0; border-bottom: 1px solid var(--cds-border-subtle);
          margin-bottom: 24px; }
        .esg-score-num { font-size: 64px; font-weight: 600; color: var(--gold);
          line-height: 1; letter-spacing: -2px; }
        .esg-score-label { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--cds-text-helper); margin-top: 8px; }
        .esg-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
        .esg-cell { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .esg-cell-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 10px; }
        .esg-cell-value { font-size: 28px; font-weight: 600; color: var(--ink); line-height: 1; }
        .esg-cell-detail { font-size: 12px; color: var(--cds-text-secondary); margin-top: 8px;
          line-height: 1.45; }
      `}</style>
    </div>
  );
}
