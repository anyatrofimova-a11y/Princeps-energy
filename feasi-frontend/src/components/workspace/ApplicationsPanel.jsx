import React, { useEffect, useState, useMemo, useCallback } from "react";

/**
 * ApplicationsPanel — UK grid + planning + environmental template
 * library. Click a template → pre-fill agent fills it from project
 * context → optional render → save as draft filing.
 */

const CATEGORY_META = {
  grid_connection: { label: "Grid connection", hint: "DNO + NESO + ECR + DCUSA" },
  planning:        { label: "Planning",        hint: "LPA + PINS DCO" },
  environmental:   { label: "Environmental",   hint: "EIA + BNG + HRA + FRA + LVIA" },
  safety:          { label: "Health & safety", hint: "CDM 2015" },
  commercial:      { label: "Commercial",      hint: "Licences + CfD + PPA + CM + DUoS" },
};

export default function ApplicationsPanel({ projectRid, siteRid, projectName }) {
  const [templates, setTemplates] = useState([]);
  const [filings, setFilings] = useState([]);
  const [active, setActive] = useState(null);      // template_id
  const [prefill, setPrefill] = useState(null);    // last prefill response
  const [pending, setPending] = useState(false);
  const [filter, setFilter] = useState("all");
  const [saveStatus, setSaveStatus] = useState(null);

  useEffect(() => {
    fetch("/api/applications/templates")
      .then((r) => r.json()).then((d) => setTemplates(d.items || []))
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    if (!projectRid) return;
    fetch(`/api/applications/filings?project_rid=${encodeURIComponent(projectRid)}`)
      .then((r) => r.json()).then((d) => setFilings(d.items || []));
  }, [projectRid]);

  const grouped = useMemo(() => {
    const out = {};
    for (const t of templates) {
      if (filter !== "all" && t.category !== filter) continue;
      (out[t.category] = out[t.category] || []).push(t);
    }
    return out;
  }, [templates, filter]);

  const runPrefill = useCallback(async (templateId) => {
    setPending(true);
    setActive(templateId);
    setPrefill(null);
    setSaveStatus(null);
    try {
      const r = await fetch("/api/applications/prefill", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_id: templateId,
          project_rid: projectRid,
          site_rid: siteRid,
          render: true,
        }),
      });
      const data = await r.json();
      setPrefill(data);
    } catch (exc) {
      setPrefill({ error: String(exc.message || exc) });
    } finally {
      setPending(false);
    }
  }, [projectRid, siteRid]);

  const saveAsDraft = useCallback(async () => {
    if (!prefill || !active) return;
    setSaveStatus("saving");
    const r = await fetch("/api/applications/filings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_id: active,
        project_rid: projectRid,
        site_rid: siteRid,
        payload: prefill.filled_payload || {},
        rendered_html: prefill.rendered || null,
        status: "draft",
      }),
    });
    const out = await r.json();
    setSaveStatus(out.filing_rid ? "saved" : "error");
    fetch(`/api/applications/filings?project_rid=${encodeURIComponent(projectRid)}`)
      .then((r) => r.json()).then((d) => setFilings(d.items || []));
  }, [prefill, active, projectRid, siteRid]);

  const counts = useMemo(() => {
    const out = { all: templates.length };
    for (const t of templates) out[t.category] = (out[t.category] || 0) + 1;
    return out;
  }, [templates]);

  return (
    <div className="ap-root">
      {/* Left rail — category filter + draft filings */}
      <div className="ap-rail">
        <div className="ap-rail-head">UK APPLICATIONS</div>
        <button
          className={`ap-cat ${filter === "all" ? "active" : ""}`}
          onClick={() => setFilter("all")}
        >
          <span>All templates</span>
          <span className="ap-cat-count">{counts.all || 0}</span>
        </button>
        {Object.entries(CATEGORY_META).map(([key, meta]) => (
          <button
            key={key}
            className={`ap-cat ${filter === key ? "active" : ""}`}
            onClick={() => setFilter(key)}
          >
            <span>
              {meta.label}
              <span className="ap-cat-hint">{meta.hint}</span>
            </span>
            <span className="ap-cat-count">{counts[key] || 0}</span>
          </button>
        ))}
        {filings.length > 0 && (
          <>
            <div className="ap-rail-head" style={{ marginTop: 18 }}>DRAFTS · {filings.length}</div>
            {filings.slice(0, 8).map((f) => (
              <div key={f.filing_rid} className="ap-draft">
                <div className="ap-draft-title">{f.template_title}</div>
                <div className="ap-draft-meta">{f.status} · {new Date(f.updated_at).toLocaleDateString()}</div>
              </div>
            ))}
          </>
        )}
      </div>

      {/* Centre — template gallery */}
      <div className="ap-gallery">
        <div className="ap-gallery-head">
          <div>
            <div className="ap-gallery-title">{projectName ? `${projectName} · Applications` : "Applications"}</div>
            <div className="ap-gallery-sub">
              {filter === "all" ? "All categories" : (CATEGORY_META[filter]?.label || filter)} ·
              &nbsp;Click a template to auto-fill from project data
            </div>
          </div>
        </div>
        <div className="ap-grid">
          {Object.entries(grouped).map(([cat, items]) => (
            <div key={cat} className="ap-grid-section">
              <div className="ap-section-head">{CATEGORY_META[cat]?.label || cat}</div>
              <div className="ap-cards">
                {items.map((t) => (
                  <TemplateCard
                    key={t.template_id}
                    t={t}
                    onClick={() => runPrefill(t.template_id)}
                    active={active === t.template_id}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right — prefill detail */}
      {active && (
        <div className="ap-detail">
          <div className="ap-detail-head">
            <div>
              <div className="ap-detail-title">
                {templates.find((x) => x.template_id === active)?.title || active}
              </div>
              <div className="ap-detail-sub">
                {prefill?.authority || ""} · {prefill?.auto_prefill_available
                  ? "Auto-fill available"
                  : "Spec only (manual fill required)"}
              </div>
            </div>
            <button className="ap-x" onClick={() => { setActive(null); setPrefill(null); }}>×</button>
          </div>
          {pending && <div className="ap-pending">Pulling site context…</div>}
          {prefill && !pending && (
            <>
              {prefill.error && <div className="ap-error">{prefill.error}</div>}
              {prefill.missing_required?.length > 0 && (
                <div className="ap-missing">
                  Missing required: {prefill.missing_required.join(", ")}
                </div>
              )}
              <div className="ap-section">
                <div className="ap-section-h">Filled payload</div>
                <pre className="ap-payload">{JSON.stringify(prefill.filled_payload, null, 2)}</pre>
              </div>
              {prefill.rendered && (
                <div className="ap-section">
                  <div className="ap-section-h">Rendered preview</div>
                  <iframe
                    title="rendered"
                    className="ap-iframe"
                    srcDoc={prefill.rendered}
                  />
                </div>
              )}
              <div className="ap-foot">
                <button
                  className="ap-btn ap-btn-primary"
                  onClick={saveAsDraft}
                  disabled={saveStatus === "saving"}
                >
                  {saveStatus === "saving" ? "Saving…" : saveStatus === "saved" ? "Saved ✓" : "Save as draft"}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      <style>{`
        .ap-root {
          display: grid;
          grid-template-columns: 240px 1fr ${active ? "440px" : "0"};
          height: 100%; min-height: 520px;
          background: #fafafa;
          color: #1f1f1f;
          font-family: "DM Sans", -apple-system, sans-serif;
          transition: grid-template-columns 200ms;
        }
        .ap-rail {
          background: #fff;
          border-right: 1px solid #ececec;
          padding: 14px;
          overflow: auto;
        }
        .ap-rail-head { font-size: 10px; letter-spacing: 0.07em; color: #C9A64B; margin-bottom: 8px; }
        .ap-cat {
          width: 100%;
          background: transparent;
          border: 1px solid transparent;
          padding: 8px 10px;
          margin-bottom: 4px;
          display: flex; align-items: center; justify-content: space-between;
          font-size: 13px; color: #1f1f1f;
          cursor: pointer;
          border-radius: 6px;
        }
        .ap-cat:hover { background: #f4f4f4; }
        .ap-cat.active { background: #fef9ec; border-color: #C9A64B; color: #5d4a1c; }
        .ap-cat-hint { display: block; font-size: 10px; color: #8d8d8d; margin-top: 2px; }
        .ap-cat-count { font-size: 11px; color: #8d8d8d; font-family: "JetBrains Mono", monospace; }

        .ap-draft { padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }
        .ap-draft-title { font-size: 12px; font-weight: 600; }
        .ap-draft-meta  { font-size: 10px; color: #8d8d8d; }

        .ap-gallery { overflow: auto; padding: 18px 24px; }
        .ap-gallery-head { margin-bottom: 18px; }
        .ap-gallery-title { font-size: 18px; font-weight: 600; }
        .ap-gallery-sub   { font-size: 12px; color: #8d8d8d; margin-top: 2px; }

        .ap-grid-section { margin-bottom: 24px; }
        .ap-section-head {
          font-size: 11px; letter-spacing: 0.07em; color: #C9A64B;
          margin-bottom: 10px; padding-bottom: 4px; border-bottom: 1px solid #ececec;
        }
        .ap-cards {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 10px;
        }

        .ap-detail {
          background: #fff;
          border-left: 1px solid #ececec;
          padding: 16px;
          overflow: auto;
        }
        .ap-detail-head { display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 12px; border-bottom: 1px solid #ececec; margin-bottom: 12px; }
        .ap-detail-title { font-size: 14px; font-weight: 600; color: #1f1f1f; }
        .ap-detail-sub { font-size: 11px; color: #8d8d8d; margin-top: 2px; }
        .ap-x { background: transparent; border: none; font-size: 22px; cursor: pointer; color: #8d8d8d; }
        .ap-pending { font-size: 12px; color: #8d8d8d; }
        .ap-error { background: #fdecea; color: #b00020; padding: 8px 10px; border-radius: 6px; font-size: 12px; margin-bottom: 10px; }
        .ap-missing { background: #fff3cd; color: #886c1a; padding: 8px 10px; border-radius: 6px; font-size: 12px; margin-bottom: 10px; }

        .ap-section { margin-bottom: 14px; }
        .ap-section-h { font-size: 10px; letter-spacing: 0.07em; color: #C9A64B; padding-bottom: 4px; border-bottom: 1px solid #ececec; }
        .ap-payload {
          background: #1a1a1a; color: #d4d4d4;
          padding: 10px;
          font-family: "JetBrains Mono", monospace;
          font-size: 11px;
          max-height: 240px; overflow: auto;
          border-radius: 6px;
          margin-top: 6px;
          white-space: pre-wrap; word-break: break-word;
        }
        .ap-iframe {
          width: 100%; height: 360px;
          background: #fff;
          border: 1px solid #ececec;
          border-radius: 6px;
          margin-top: 6px;
        }
        .ap-foot { padding-top: 12px; border-top: 1px solid #ececec; }
        .ap-btn { padding: 8px 14px; border-radius: 6px; border: 1px solid #d4d4d4; background: #fff; cursor: pointer; font-size: 13px; }
        .ap-btn-primary { background: #1f1f1f; color: #fff; border-color: #1f1f1f; }
        .ap-btn-primary:hover { background: #2d2d2d; }
        .ap-btn-primary:disabled { opacity: 0.5; }
      `}</style>
    </div>
  );
}

function TemplateCard({ t, onClick, active }) {
  return (
    <button className={`ap-card ${active ? "active" : ""}`} onClick={onClick}>
      <div className="ap-card-head">
        <span className="ap-card-doc">{t.doc_type}</span>
        {t.auto_prefill_available && <span className="ap-card-auto">⚡ auto-fill</span>}
      </div>
      <div className="ap-card-title">{t.title}</div>
      {t.applicable_when && (
        <div className="ap-card-when">{t.applicable_when}</div>
      )}
      <div className="ap-card-meta">
        {t.authority || ""} · ~{t.estimated_pages || "?"}pp · ~{t.estimated_minutes || "?"}min
      </div>
      <style>{`
        .ap-card {
          text-align: left;
          background: #fff;
          border: 1px solid #ececec;
          border-radius: 8px;
          padding: 12px;
          cursor: pointer;
          transition: border-color 120ms, box-shadow 120ms;
        }
        .ap-card:hover { border-color: #C9A64B; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
        .ap-card.active { border-color: #C9A64B; box-shadow: 0 0 0 3px rgba(201,166,75,0.16); }
        .ap-card-head { display: flex; justify-content: space-between; margin-bottom: 6px; }
        .ap-card-doc { font-size: 10px; letter-spacing: 0.05em; color: #C9A64B; font-family: "JetBrains Mono", monospace; }
        .ap-card-auto { font-size: 10px; color: #2d7a47; }
        .ap-card-title { font-size: 13px; font-weight: 600; color: #1f1f1f; }
        .ap-card-when { font-size: 11px; color: #5a5a5a; margin-top: 4px; line-height: 1.4; }
        .ap-card-meta { font-size: 10px; color: #8d8d8d; margin-top: 6px; font-family: "JetBrains Mono", monospace; }
      `}</style>
    </button>
  );
}
