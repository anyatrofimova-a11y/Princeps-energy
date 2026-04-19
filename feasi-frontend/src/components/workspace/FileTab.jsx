import React, { useState } from "react";
import { WhenWorkload } from "../../lib/workload";

/**
 * FileTab — output queue. Surfaces every artefact the project can emit
 * (IC Memo, DD Pack, Grid Connection Report, Financial Viability Report,
 * G99 Application Pack, Site Assessment, plus placeholders for future packs)
 * as a single grid of one-click generators. Replaces the older standalone
 * IC Memo / ESG-output / Reports & Logs tabs.
 */

const ARTEFACTS = [
  {
    key: "ic-memo",
    label: "IC Memo",
    description: "Investment committee submission — verdict, finance, grid, planning, risks.",
    endpoint: "/api/reports/ic-memo",
    method: "POST",
    needsProjectId: true,
    filename: (p) => `${p?.name || "project"}-ic-memo.pdf`,
    status: "ready",
  },
  {
    key: "dd-pack",
    label: "DD Pack",
    description: "Full due-diligence bundle — technical, commercial, legal data sheets.",
    endpoint: "/api/reports/dd-pack",
    method: "POST",
    needsProjectId: true,
    filename: (p) => `${p?.name || "project"}-dd-pack.pdf`,
    status: "ready",
  },
  {
    key: "grid-connection",
    label: "Grid Connection Report",
    description: "POC, headroom, cost P10/P50/P90 and Tier 2 power-flow result.",
    endpoint: "/api/reports/grid-connection",
    method: "POST",
    needsProjectId: true,
    filename: (p) => `${p?.name || "project"}-grid-connection.pdf`,
    status: "ready",
  },
  {
    key: "financial",
    label: "Financial Viability Report",
    description: "IRR, NPV, LCOE, debt cover, sensitivity tornado — lender-ready.",
    endpoint: "/api/reports/financial",
    method: "POST",
    needsProjectId: true,
    filename: (p) => `${p?.name || "project"}-financial.pdf`,
    status: "ready",
  },
  {
    key: "g99",
    label: "G99 Application Pack",
    description: "DNO connection application form pre-filled from project data.",
    endpoint: "/api/reports/g99-pack",
    method: "POST",
    needsProjectId: true,
    filename: (p) => `${p?.name || "project"}-g99-pack.pdf`,
    status: "ready",
  },
  {
    key: "site-assessment",
    label: "Site Assessment",
    description: "Resource, terrain, land use, planning risk for the primary parcel.",
    endpoint: "/api/reports/site-assessment",
    method: "POST",
    needsLatLon: true,
    filename: (p) => `${p?.name || "site"}-assessment.pdf`,
    status: "ready",
  },
  {
    key: "planning-bundle",
    label: "Planning Application Bundle",
    description: "1APP key sections pre-filled — Planning Summary submission pack.",
    endpoint: "/api/documents/generate",
    method: "POST",
    bodyJson: { document_type: "planning_summary" },
    filename: (p) => `${p?.name || "project"}-planning-summary.html`,
    status: "ready",
  },
  {
    key: "bng-baseline",
    label: "BNG Baseline Report",
    description: "Biodiversity Net Gain baseline using DEFRA metric 4.0 (simplified).",
    endpoint: "/api/documents/generate",
    method: "POST",
    bodyJson: { document_type: "bng_baseline" },
    filename: (p) => `${p?.name || "project"}-bng-baseline.html`,
    status: "ready",
  },
  {
    key: "cdm-f10",
    label: "CDM F10 Pre-fill",
    description: "Construction phase notification with project parties pre-populated.",
    endpoint: "/api/documents/generate",
    method: "POST",
    bodyJson: { document_type: "cdm_f10" },
    filename: (p) => `${p?.name || "project"}-cdm-f10.html`,
    status: "ready",
  },
];

function buildBody(art, project) {
  if (art.bodyJson) {
    // /api/documents/generate expects nested site/capacity/technology dicts
    const firstSite = project?.sites?.[0];
    const tech = project?.workload_type === "bess" ? "bess"
               : project?.workload_type === "wind" ? "wind"
               : project?.workload_type === "dc" ? "solar"
               : "solar";
    const mw = project?.capacity_mw || 50;
    return {
      ...art.bodyJson,
      site: {
        project_id: project?.project_id,
        name: project?.name || "Project",
        lat: firstSite?.lat ?? project?.lat,
        lon: firstSite?.lon ?? project?.lon,
      },
      capacity: { capacity_mw: mw, capacity_kw: mw * 1000 },
      technology: { type: tech },
      capacity_mw: mw,
      capacity_kw: mw * 1000,
    };
  }
  if (art.needsLatLon) {
    const firstSite = project?.sites?.[0];
    return {
      project_id: project?.project_id,
      lat: firstSite?.lat ?? project?.lat,
      lon: firstSite?.lon ?? project?.lon,
    };
  }
  return null;
}

function buildUrl(art, project) {
  if (art.needsProjectId && project?.project_id) {
    return `${art.endpoint}?project_id=${project.project_id}`;
  }
  return art.endpoint;
}

export default function FileTab({ project }) {
  // state per artefact key: { generating, result, error, generatedAt }
  const [state, setState] = useState({});
  const [activity, setActivity] = useState([]);

  const update = (key, patch) =>
    setState((s) => ({ ...s, [key]: { ...(s[key] || {}), ...patch } }));

  const onGenerate = async (art) => {
    if (art.status !== "ready") return;
    if (!project?.project_id && art.needsProjectId) return;
    update(art.key, { generating: true, error: null, result: null });
    try {
      const body = buildBody(art, project);
      const res = await fetch(buildUrl(art, project), {
        method: art.method || "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const ct = res.headers.get("content-type") || "";
      let blob;
      if (ct.includes("application/json")) {
        // /api/documents/generate returns JSON {html, form_data, auto_fill_pct}
        const json = await res.json();
        const html = json.html || `<pre>${JSON.stringify(json, null, 2)}</pre>`;
        blob = new Blob([html], { type: "text/html" });
      } else {
        blob = await res.blob();
      }
      const url = URL.createObjectURL(blob);
      const filename = art.filename ? art.filename(project) : `${art.key}.pdf`;
      const ts = new Date().toISOString();
      update(art.key, { generating: false, result: { url, filename }, generatedAt: ts });
      setActivity((a) =>
        [{ ts, project: project?.name || "—", filename, label: art.label }, ...a].slice(0, 10)
      );
    } catch (e) {
      update(art.key, { generating: false, error: e.message || "Generation failed" });
    }
  };

  return (
    <div className="file-tab">
      <header className="file-head">
        <div className="file-eyebrow">Output queue</div>
        <h2 className="file-title">File</h2>
        <p className="file-lede">
          Generate, download, and submit the artefacts your project needs.
        </p>
      </header>

      <section className="file-grid">
        {ARTEFACTS.map((art) => {
          const s = state[art.key] || {};
          const isReady = art.status === "ready";
          const disabled = !isReady || s.generating || (art.needsProjectId && !project?.project_id);
          return (
            <div key={art.key} className="file-card">
              <div className="file-card-top">
                <div className="file-card-label">{art.label}</div>
                <span className={`file-status file-status-${art.status}`}>
                  {art.status === "ready" ? "Ready" : "Coming soon"}
                </span>
              </div>
              <div className="file-card-desc">{art.description}</div>
              <div className="file-card-actions">
                {s.result ? (
                  <a className="file-link" href={s.result.url} download={s.result.filename}>
                    Download {s.result.filename}
                  </a>
                ) : (
                  <button
                    className="file-cta"
                    onClick={() => onGenerate(art)}
                    disabled={disabled}
                  >
                    {s.generating ? "Generating…" : isReady ? "Generate" : "Coming soon"}
                  </button>
                )}
              </div>
              {s.error && <div className="file-card-err">{s.error}</div>}
              {s.generatedAt && (
                <div className="file-card-ts">
                  Last generated {new Date(s.generatedAt).toLocaleString()}
                </div>
              )}
            </div>
          );
        })}
      </section>

      <section className="file-wl-section">
        <WhenWorkload project={project} only="solar">
          <div className="file-wl-card">
            <div className="file-wl-eyebrow">Solar pack</div>
            <div className="file-wl-title">G99 Solar PV pack</div>
            <div className="file-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="bess">
          <div className="file-wl-card">
            <div className="file-wl-eyebrow">Storage pack</div>
            <div className="file-wl-title">G99 Storage pack</div>
            <div className="file-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="dc">
          <div className="file-wl-card">
            <div className="file-wl-eyebrow">Data centre pack</div>
            <div className="file-wl-title">G100 + DCO planning bundle</div>
            <div className="file-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="wind">
          <div className="file-wl-card">
            <div className="file-wl-eyebrow">Wind pack</div>
            <div className="file-wl-title">G99 Large-scale wind pack</div>
            <div className="file-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
      </section>

      <section className="file-activity">
        <div className="file-activity-head">
          <div className="file-eyebrow">Activity log</div>
          <span className="file-activity-count">{activity.length}</span>
        </div>
        {activity.length === 0 ? (
          <div className="file-activity-empty">
            No artefacts generated yet. Use the cards above to produce a file.
          </div>
        ) : (
          <ul className="file-activity-list">
            {activity.map((a, i) => (
              <li key={i} className="file-activity-row">
                <span className="file-activity-ts">{new Date(a.ts).toLocaleString()}</span>
                <span className="file-activity-proj">{a.project}</span>
                <span className="file-activity-label">{a.label}</span>
                <span className="file-activity-file">{a.filename}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <style>{`
        .file-tab { padding: 32px 40px; max-width: 1100px;
          font-family: "DM Sans", -apple-system, sans-serif; color: var(--cds-text-primary); }
        .file-head { margin-bottom: 28px; }
        .file-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .file-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .file-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }

        .file-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
          margin-bottom: 36px; }
        @media (max-width: 960px) { .file-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 640px) { .file-grid { grid-template-columns: 1fr; } }

        .file-card { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; display: flex; flex-direction: column; gap: 10px; }
        .file-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .file-card-label { font-size: 14px; font-weight: 700; color: var(--ink); }
        .file-status { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
          padding: 2px 8px; border-radius: 10px; font-family: var(--mono); }
        .file-status-ready { background: var(--cds-layer-02); color: var(--cds-text-secondary); }
        .file-status-soon { background: var(--cds-layer-03); color: var(--cds-text-helper); }
        .file-card-desc { font-size: 12px; line-height: 1.45; color: var(--cds-text-secondary);
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .file-card-actions { margin-top: 4px; }
        .file-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 9px 16px; font-family: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
          letter-spacing: 0.2px; transition: background 120ms; }
        .file-cta:hover:not(:disabled) { background: var(--gold-dark); }
        .file-cta:disabled { opacity: 0.4; cursor: not-allowed; }
        .file-link { font-size: 12px; color: var(--ink); text-decoration: underline; font-weight: 500;
          word-break: break-all; }
        .file-card-err { font-size: 11px; color: #c0392b; font-family: var(--mono); }
        .file-card-ts { font-size: 11px; color: var(--cds-text-helper); font-family: var(--mono); }

        .file-wl-section { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
          margin-bottom: 36px; }
        @media (max-width: 960px) { .file-wl-section { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 640px) { .file-wl-section { grid-template-columns: 1fr; } }
        .file-wl-section:empty { display: none; }
        .file-wl-card { background: var(--cds-layer-01); border: 1px dashed var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; display: flex; flex-direction: column; gap: 6px; }
        .file-wl-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--cds-text-helper); }
        .file-wl-title { font-size: 14px; font-weight: 700; color: var(--ink); }
        .file-wl-body { font-size: 12px; color: var(--cds-text-secondary); line-height: 1.5; }

        .file-activity { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .file-activity-head { display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 14px; }
        .file-activity-count { background: var(--cds-layer-03); color: var(--cds-text-secondary);
          padding: 1px 8px; border-radius: 10px; font-size: 10px; font-family: var(--mono); font-weight: 700; }
        .file-activity-empty { font-size: 12px; color: var(--cds-text-helper); padding: 8px 0; }
        .file-activity-list { list-style: none; margin: 0; padding: 0;
          display: flex; flex-direction: column; gap: 6px; }
        .file-activity-row { display: grid;
          grid-template-columns: 180px 160px 1fr auto; gap: 12px; align-items: center;
          padding: 8px 0; border-bottom: 1px solid var(--cds-border-subtle); font-size: 12px; }
        .file-activity-row:last-child { border-bottom: none; }
        .file-activity-ts { font-family: var(--mono); font-size: 11px; color: var(--cds-text-helper); }
        .file-activity-proj { color: var(--cds-text-secondary); }
        .file-activity-label { color: var(--ink); font-weight: 500; }
        .file-activity-file { font-family: var(--mono); font-size: 11px; color: var(--cds-text-helper); }
      `}</style>
    </div>
  );
}
