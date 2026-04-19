import React, { useState } from "react";

/**
 * ICMemoTab — Investment Committee Memo generator.
 * Pulls together financial + grid + planning data into a one-click PDF
 * formatted for IC submission. Backend: POST /api/reports/ic-memo.
 */
export default function ICMemoTab({ project }) {
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const onGenerate = async () => {
    if (!project?.project_id) return;
    setGenerating(true); setError(null); setResult(null);
    try {
      const res = await fetch(`/api/reports/ic-memo?project_id=${project.project_id}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setResult({ url, filename: `${project.name || "project"}-ic-memo.pdf` });
    } catch (e) {
      setError(e.message || "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="ic-tab">
      <header className="ic-head">
        <div className="ic-eyebrow">Investment committee</div>
        <h2 className="ic-title">IC Memo</h2>
        <p className="ic-lede">
          A structured submission pack for your investment committee — verdict, financial summary,
          grid position, planning probability, key risks. Generated from the live project data.
        </p>
      </header>

      <section className="ic-card">
        <div className="ic-card-row">
          <div>
            <div className="ic-card-label">Source data</div>
            <div className="ic-card-value">Financial · Grid · Planning · Demand</div>
          </div>
          <div>
            <div className="ic-card-label">Output</div>
            <div className="ic-card-value">PDF, ~6 pages, lender-ready</div>
          </div>
          <div>
            <div className="ic-card-label">Refresh cadence</div>
            <div className="ic-card-value">Live — regenerate any time</div>
          </div>
        </div>

        <div className="ic-actions">
          <button className="ic-cta" onClick={onGenerate} disabled={generating || !project}>
            {generating ? "Generating…" : "Generate IC Memo"}
          </button>
          {result && (
            <a className="ic-link" href={result.url} download={result.filename}>Download {result.filename}</a>
          )}
          {error && <span className="ic-error">{error}</span>}
        </div>
      </section>

      <style>{`
        .ic-tab { padding: 32px 40px; max-width: 880px; }
        .ic-head { margin-bottom: 28px; }
        .ic-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .ic-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .ic-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .ic-card { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 28px; }
        .ic-card-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px;
          padding-bottom: 24px; border-bottom: 1px solid var(--cds-border-subtle); margin-bottom: 24px; }
        .ic-card-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 6px; }
        .ic-card-value { font-size: 13px; color: var(--ink); font-weight: 500; }
        .ic-actions { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
        .ic-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 12px 22px; font-family: inherit; font-size: 13px; font-weight: 600;
          cursor: pointer; letter-spacing: 0.2px; transition: background 120ms; }
        .ic-cta:hover:not(:disabled) { background: var(--gold-dark); }
        .ic-cta:disabled { opacity: 0.4; cursor: not-allowed; }
        .ic-link { font-size: 13px; color: var(--ink); text-decoration: underline; font-weight: 500; }
        .ic-error { font-size: 13px; color: #c0392b; font-family: var(--mono); }
      `}</style>
    </div>
  );
}
