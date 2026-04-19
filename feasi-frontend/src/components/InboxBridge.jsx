import React, { useState } from "react";

/**
 * InboxBridge — Email-as-UI scaffolding (build.inc pattern).
 * Forward an email → classify → extract entities → pre-load a project.
 * For now: manual paste form. Real SMTP/Mailgun forwarding is deferred.
 */
export default function InboxBridge() {
  const [subject, setSubject] = useState("");
  const [from, setFrom] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [recent, setRecent] = useState([]);

  const onIngest = async () => {
    if (!subject.trim() && !body.trim()) {
      setError("Paste at least a subject or body.");
      return;
    }
    setSubmitting(true); setError(null); setResult(null);
    try {
      const res = await fetch("/api/inbox/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject,
          body,
          from_address: from || null,
          received_at: new Date().toISOString(),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      setRecent((prev) => [data, ...prev].slice(0, 20));
    } catch (e) {
      setError(e.message || "Ingest failed");
    } finally {
      setSubmitting(false);
    }
  };

  const onClear = () => { setSubject(""); setFrom(""); setBody(""); setResult(null); setError(null); };

  const labelFor = (c) => ({
    rfp: "RFP / Tender",
    land_tip: "Land tip",
    planning_notice: "Planning notice",
    grid_alert: "Grid alert",
    general: "General",
  }[c] || c);

  return (
    <div className="ib-tab">
      <header className="ib-head">
        <div className="ib-eyebrow">Inbox bridge</div>
        <h2 className="ib-title">Forward emails. Get projects.</h2>
        <p className="ib-lede">
          Forward any email to <code className="ib-mono">ingest@princeps.dev</code> — RFPs, land tips, planning
          notices. Princeps classifies, extracts, and opens a pre-loaded project for you.
        </p>
      </header>

      <section className="ib-card">
        <div className="ib-row">
          <label className="ib-field">
            <span className="ib-field-label">From</span>
            <input
              className="ib-input"
              placeholder="henry@landagent.example"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="ib-field ib-field-wide">
            <span className="ib-field-label">Subject</span>
            <input
              className="ib-input"
              placeholder="FW: Land available — South Cambs, 24 ha former dairy"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </label>
        </div>
        <label className="ib-field">
          <span className="ib-field-label">Body</span>
          <textarea
            className="ib-textarea"
            rows={10}
            placeholder="Paste the email body here…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </label>
        <div className="ib-actions">
          <button className="ib-cta" onClick={onIngest} disabled={submitting}>
            {submitting ? "Ingesting…" : "Ingest"}
          </button>
          <button className="ib-ghost" onClick={onClear} disabled={submitting}>Clear</button>
          {error && <span className="ib-error">{error}</span>}
        </div>
      </section>

      {result && (
        <section className="ib-result">
          <div className="ib-result-head">
            <span className={`ib-chip ib-chip-${result.classification}`}>{labelFor(result.classification)}</span>
            <span className="ib-conf">confidence {Math.round((result.confidence || 0) * 100)}%</span>
          </div>
          <div className="ib-narr">{result.narrative}</div>
          <div className="ib-extracted">
            {Object.entries(result.extracted || {}).map(([k, v]) => (
              <div className="ib-kv" key={k}>
                <div className="ib-k">{k.replace(/_/g, " ")}</div>
                <div className="ib-v">{v == null || v === "" ? "—" : String(v)}</div>
              </div>
            ))}
          </div>
          <div className="ib-next">
            <span className="ib-next-label">Next</span>
            <span className="ib-next-text">{result.next_action}</span>
            {result.project_id && (
              <a className="ib-link" href={`/projects/${result.project_id}`}>Open project →</a>
            )}
          </div>
        </section>
      )}

      <section className="ib-recent">
        <div className="ib-recent-head">Recent ingests this session</div>
        {recent.length === 0 && <div className="ib-empty">Nothing yet. Paste an email above to begin.</div>}
        {recent.map((r) => (
          <div className="ib-recent-card" key={r.ingest_id}>
            <div className="ib-recent-row">
              <span className={`ib-chip ib-chip-${r.classification}`}>{labelFor(r.classification)}</span>
              <span className="ib-recent-subj">{r.subject || "(no subject)"}</span>
              {r.project_id ? (
                <a className="ib-link" href={`/projects/${r.project_id}`}>Open project →</a>
              ) : (
                <span className="ib-recent-pending">Pending confirmation</span>
              )}
            </div>
            <div className="ib-recent-meta">
              {r.from_address || "unknown sender"} · {r.extracted?.location_hint || "no location"} ·
              {" "}{r.extracted?.area_ha ? `${r.extracted.area_ha} ha` : "area unknown"}
            </div>
          </div>
        ))}
      </section>

      <div className="ib-footnote">Coming next: real SMTP forwarding via Mailgun.</div>

      <style>{`
        .ib-tab { padding: 32px 40px; max-width: 880px; }
        .ib-head { margin-bottom: 28px; }
        .ib-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .ib-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .ib-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .ib-mono { font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
          background: var(--cds-layer-02, #F2F2F2); padding: 1px 6px; border-radius: 4px; font-size: 13px; }

        .ib-card { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 24px; margin-bottom: 20px; }
        .ib-row { display: grid; grid-template-columns: 1fr 2fr; gap: 16px; margin-bottom: 16px; }
        .ib-field { display: flex; flex-direction: column; gap: 6px; }
        .ib-field-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); }
        .ib-input, .ib-textarea { font-family: inherit; font-size: 13px; color: var(--ink);
          background: #fff; border: 1px solid #E5E7EB; border-radius: 6px; padding: 10px 12px;
          outline: none; transition: border-color 120ms; width: 100%; box-sizing: border-box; }
        .ib-input:focus, .ib-textarea:focus { border-color: var(--gold); }
        .ib-textarea { font-family: var(--mono, ui-monospace, Menlo, monospace); font-size: 12.5px;
          line-height: 1.5; resize: vertical; }
        .ib-actions { display: flex; gap: 12px; align-items: center; margin-top: 18px; flex-wrap: wrap; }
        .ib-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 11px 22px; font-family: inherit; font-size: 13px; font-weight: 600;
          cursor: pointer; letter-spacing: 0.2px; transition: background 120ms; }
        .ib-cta:hover:not(:disabled) { background: var(--gold-dark, var(--gold)); }
        .ib-cta:disabled { opacity: 0.4; cursor: not-allowed; }
        .ib-ghost { background: transparent; color: var(--cds-text-secondary); border: 1px solid #E5E7EB;
          border-radius: 8px; padding: 11px 18px; font-family: inherit; font-size: 13px; cursor: pointer; }
        .ib-ghost:disabled { opacity: 0.4; cursor: not-allowed; }
        .ib-error { font-size: 13px; color: #c0392b; }

        .ib-result { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 24px; margin-bottom: 20px; }
        .ib-result-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
        .ib-chip { font-size: 11px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase;
          padding: 4px 10px; border-radius: 999px; background: #F2F2F2; color: var(--ink);
          border: 1px solid #E5E7EB; }
        .ib-chip-rfp { background: #FFF7E6; border-color: #F4D27A; }
        .ib-chip-land_tip { background: #EAF6EE; border-color: #A8D5B7; }
        .ib-chip-planning_notice { background: #EAF1FB; border-color: #A8C2E5; }
        .ib-chip-grid_alert { background: #FBEAEA; border-color: #E5A8A8; }
        .ib-conf { font-size: 12px; color: var(--cds-text-helper); font-family: var(--mono, monospace); }
        .ib-narr { font-size: 14px; line-height: 1.55; color: var(--ink); margin-bottom: 18px; }
        .ib-extracted { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
          padding-top: 16px; border-top: 1px solid #E5E7EB; }
        .ib-kv { display: flex; flex-direction: column; gap: 4px; }
        .ib-k { font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); }
        .ib-v { font-size: 13px; color: var(--ink); font-weight: 500; }
        .ib-next { display: flex; align-items: center; gap: 12px; margin-top: 18px;
          padding-top: 16px; border-top: 1px solid #E5E7EB; flex-wrap: wrap; }
        .ib-next-label { font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); }
        .ib-next-text { font-size: 13px; color: var(--ink); }
        .ib-link { font-size: 13px; color: var(--gold); text-decoration: none; font-weight: 600; }
        .ib-link:hover { text-decoration: underline; }

        .ib-recent { margin-top: 8px; }
        .ib-recent-head { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 12px; }
        .ib-empty { font-size: 13px; color: var(--cds-text-helper); padding: 16px;
          background: var(--cds-layer-01); border: 1px dashed #E5E7EB; border-radius: 8px; }
        .ib-recent-card { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 8px; padding: 14px 18px; margin-bottom: 8px; }
        .ib-recent-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        .ib-recent-subj { font-size: 13px; color: var(--ink); font-weight: 500; flex: 1; min-width: 0;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ib-recent-pending { font-size: 12px; color: var(--cds-text-helper); font-style: italic; }
        .ib-recent-meta { font-size: 12px; color: var(--cds-text-helper); margin-top: 6px;
          font-family: var(--mono, monospace); }

        .ib-footnote { font-size: 11px; color: var(--cds-text-helper); margin-top: 28px;
          padding-top: 16px; border-top: 1px solid #E5E7EB; }
      `}</style>
    </div>
  );
}
