import React, { useState, useCallback, useMemo, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

/* ── Document definitions by stage ───────────────────────────────────────── */
const STAGES = [
  {
    id: "pre_planning",
    label: "Pre-Planning",
    documents: [
      { id: "env_screening",    name: "Environmental Screening Report",   required: true  },
      { id: "pea",              name: "Preliminary Ecological Appraisal", required: true  },
      { id: "flood_screening",  name: "Flood Risk Screening",            required: true  },
      { id: "heritage",         name: "Heritage Impact Assessment",       required: false },
    ],
  },
  {
    id: "planning_app",
    label: "Planning Application",
    documents: [
      { id: "planning_stmt",    name: "Planning Statement",                      required: true  },
      { id: "design_access",    name: "Design and Access Statement",             required: true  },
      { id: "env_statement",    name: "Environmental Statement (if EIA required)", required: false },
      { id: "transport",        name: "Transport Assessment",                    required: false },
      { id: "noise",            name: "Noise Assessment",                        required: true  },
      { id: "glint_glare",      name: "Glint and Glare Assessment",              required: true  },
      { id: "lvia",             name: "Landscape and Visual Impact Assessment",  required: true  },
      { id: "bng",              name: "Biodiversity Net Gain Plan",              required: true  },
    ],
  },
  {
    id: "grid_connection",
    label: "Grid Connection",
    documents: [
      { id: "g99_form",         name: "G99 Application Form",        required: true  },
      { id: "sld",              name: "Single Line Diagram",         required: true  },
      { id: "protection",       name: "Protection Settings Schedule", required: true  },
      { id: "grid_agreement",   name: "Grid Connection Agreement",   required: false },
    ],
  },
  {
    id: "construction",
    label: "Construction",
    documents: [
      { id: "cdm_pci",          name: "CDM Pre-Construction Information",             required: true  },
      { id: "cemp",             name: "Construction Environmental Management Plan",   required: true  },
      { id: "hs_plan",          name: "Health and Safety Plan",                       required: true  },
      { id: "commissioning",    name: "Commissioning Plan",                           required: false },
    ],
  },
];

const TEMPLATES = [
  { id: "standard", label: "Standard" },
  { id: "detailed", label: "Detailed" },
  { id: "summary",  label: "Summary" },
];

/* ── Status badge ────────────────────────────────────────────────────────── */
function DocStatusBadge({ status }) {
  const cls = status === "complete" ? "dc-st-complete" :
    status === "draft" ? "dc-st-draft" :
    status === "generating" ? "dc-st-generating" : "dc-st-none";
  const label = status === "complete" ? "Complete" :
    status === "draft" ? "Draft" :
    status === "generating" ? "Generating..." : "Not started";
  return <span className={`dc-status ${cls}`}>{label}</span>;
}

/* ════════════════════════════════════════════════════════════════════════════ */
/*  DocumentsPanel                                                            */
/* ════════════════════════════════════════════════════════════════════════════ */
export default function DocumentsPanel({ onClose, embedded }) {
  const { lat, lon, samCapacity } = useSite();
  const [docStates, setDocStates] = useState({});
  const [template, setTemplate] = useState("standard");
  const [generatingAll, setGeneratingAll] = useState(false);

  /* ── All docs flat ─────────────────────────────────────────────────────── */
  const allDocs = useMemo(() => STAGES.flatMap(s => s.documents), []);
  const requiredDocs = useMemo(() => allDocs.filter(d => d.required), [allDocs]);

  /* ── Progress ──────────────────────────────────────────────────────────── */
  const progress = useMemo(() => {
    const total = requiredDocs.length;
    const done = requiredDocs.filter(d => docStates[d.id]?.status === "complete").length;
    return { total, done, pct: total > 0 ? (done / total) * 100 : 0 };
  }, [requiredDocs, docStates]);

  /* ── Generate single document ──────────────────────────────────────────── */
  const generateDoc = useCallback(async (docId) => {
    if (!lat || !lon) return;
    setDocStates(prev => ({ ...prev, [docId]: { ...prev[docId], status: "generating" } }));
    try {
      const data = await api.documents.generate({
        type: docId,
        template,
        lat, lon,
        capacity_mw: (samCapacity || 5000) / 1000,
        technology: "solar",
      });
      setDocStates(prev => ({
        ...prev,
        [docId]: {
          status: data?.download_url ? "complete" : "draft",
          url: data?.download_url,
          generated_at: new Date().toISOString(),
          data,
        },
      }));
    } catch (e) {
      console.warn("[Documents] generate error:", e);
      setDocStates(prev => ({ ...prev, [docId]: { ...prev[docId], status: "draft" } }));
    }
  }, [lat, lon, samCapacity, template]);

  /* ── Generate all required ─────────────────────────────────────────────── */
  const generateAllRequired = useCallback(async () => {
    setGeneratingAll(true);
    for (const doc of requiredDocs) {
      if (docStates[doc.id]?.status !== "complete") {
        await generateDoc(doc.id);
      }
    }
    setGeneratingAll(false);
  }, [requiredDocs, docStates, generateDoc]);

  /* ── Toggle required ───────────────────────────────────────────────────── */
  const toggleRequired = useCallback((docId) => {
    // This is local UI state only — the STAGES data is constant
    setDocStates(prev => ({
      ...prev,
      [docId]: { ...prev[docId], userRequired: !(prev[docId]?.userRequired ?? true) },
    }));
  }, []);

  return (
    <div className={`dc-panel${embedded ? " dc-embedded" : ""}`}>
      {!embedded && (
        <div className="dc-header">
          <span className="dc-title">Document Automation</span>
          <button className="dc-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      )}

      <div className="dc-body">
        {/* ── Progress bar ── */}
        <div className="dc-progress">
          <div className="dc-progress-info">
            <span className="dc-progress-label">Completeness</span>
            <span className="dc-progress-val">{progress.done}/{progress.total} required</span>
          </div>
          <div className="dc-progress-bar">
            <div className="dc-progress-fill" style={{ width: `${progress.pct}%` }} />
          </div>
        </div>

        {/* ── Template selector + batch ── */}
        <div className="dc-controls">
          <div className="dc-template-selector">
            <label className="dc-label">Template</label>
            <div className="dc-template-btns">
              {TEMPLATES.map(t => (
                <button key={t.id} className={`dc-chip${template === t.id ? " active" : ""}`}
                  onClick={() => setTemplate(t.id)}>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <button className="dc-btn dc-btn-batch" onClick={generateAllRequired}
            disabled={generatingAll || !lat}>
            {generatingAll ? "Generating..." : "Generate All Required"}
          </button>
        </div>

        {/* ── Document checklist by stage ── */}
        {STAGES.map(stage => (
          <div key={stage.id} className="dc-stage">
            <h3 className="dc-stage-title">{stage.label}</h3>
            <div className="dc-doc-list">
              {stage.documents.map(doc => {
                const state = docStates[doc.id] || {};
                const isRequired = state.userRequired !== false && doc.required;
                return (
                  <div key={doc.id} className={`dc-doc-row${isRequired ? "" : " dc-optional"}`}>
                    <div className="dc-doc-check">
                      <input type="checkbox" checked={isRequired}
                        onChange={() => toggleRequired(doc.id)}
                        className="dc-checkbox" />
                    </div>
                    <div className="dc-doc-info">
                      <span className="dc-doc-name">{doc.name}</span>
                      <DocStatusBadge status={state.status} />
                    </div>
                    <div className="dc-doc-actions">
                      <button className="dc-btn dc-btn-gen"
                        onClick={() => generateDoc(doc.id)}
                        disabled={state.status === "generating" || !lat}>
                        {state.status === "generating" ? (
                          <span className="dc-spinner" />
                        ) : "Generate"}
                      </button>
                      {state.status === "complete" && state.url && (
                        <button className="dc-btn dc-btn-dl"
                          onClick={() => window.open(state.url, "_blank")}>
                          Download
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
