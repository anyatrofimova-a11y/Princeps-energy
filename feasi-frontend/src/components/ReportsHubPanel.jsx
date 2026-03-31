import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/* ── Report type definitions ─────────────────────────────────────────────── */
const REPORT_TYPES = [
  {
    id: "site_assessment",
    name: "Site Assessment Report",
    description: "Comprehensive feasibility summary covering terrain, solar resource, planning constraints, and grid proximity.",
    pages: "12-18",
    format: "PDF",
    icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  },
  {
    id: "grid_connection",
    name: "Grid Connection Report",
    description: "Connection options, substation headroom, estimated costs, and power flow simulation results.",
    pages: "8-14",
    format: "PDF",
    icon: "M13 10V3L4 14h7v7l9-11h-7z",
  },
  {
    id: "financial_viability",
    name: "Financial Viability Report",
    description: "Project IRR, NPV, cashflow waterfall, DSCR coverage, and sensitivity analysis.",
    pages: "10-16",
    format: "PDF",
    icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  },
  {
    id: "g99_application",
    name: "G99 Application Pack",
    description: "Pre-filled DNO grid connection application with site data, SLD reference, and protection schedule.",
    pages: "6-10",
    format: "PDF",
    icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
  },
  {
    id: "constraint_report",
    name: "Constraint Report",
    description: "Environmental, planning, and land use constraints within the site boundary and buffer zone.",
    pages: "8-12",
    format: "PDF",
    icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.999L13.732 4.003c-.77-1.333-2.694-1.333-3.464 0L3.34 16.003c-.77 1.332.192 2.999 1.732 2.999z",
  },
  {
    id: "ml_enhanced",
    name: "ML-Enhanced Report",
    description: "AI-driven analysis with planning approval prediction, comparable project benchmarking, and risk scoring.",
    pages: "14-22",
    format: "PDF",
    icon: "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z",
  },
  {
    id: "financial_excel",
    name: "Financial Excel Export",
    description: "Full financial model with assumptions, cashflows, sensitivity tables, and debt structure in XLSX.",
    pages: "5 sheets",
    format: "XLSX",
    icon: "M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4",
  },
];

/* ── Status Badge ────────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const cls = status === "ready" ? "rh-badge-ready" :
    status === "generating" ? "rh-badge-generating" :
    status === "error" ? "rh-badge-error" : "rh-badge-idle";
  const label = status === "ready" ? "Ready" :
    status === "generating" ? "Generating..." :
    status === "error" ? "Error" : "Not generated";
  return <span className={`rh-badge ${cls}`}>{label}</span>;
}

/* ════════════════════════════════════════════════════════════════════════════ */
/*  ReportsHubPanel                                                           */
/* ════════════════════════════════════════════════════════════════════════════ */
export default function ReportsHubPanel({ onClose, embedded }) {
  const { lat, lon, samCapacity } = useSite();
  const [reportStates, setReportStates] = useState({});
  const [recentReports, setRecentReports] = useState([]);
  const [batchGenerating, setBatchGenerating] = useState(false);

  /* ── Load recent reports ───────────────────────────────────────────────── */
  useEffect(() => {
    (async () => {
      try {
        const data = await api.reports.list();
        if (data?.reports) setRecentReports(data.reports);
      } catch (e) { /* no-op */ }
    })();
  }, []);

  /* ── Generate single report ────────────────────────────────────────────── */
  const generateReport = useCallback(async (reportId) => {
    if (!lat || !lon) return;
    setReportStates(prev => ({ ...prev, [reportId]: { status: "generating" } }));
    try {
      const data = await api.reports.generate({
        type: reportId,
        lat, lon,
        capacity_mw: (samCapacity || 5000) / 1000,
        technology: "solar",
      });
      if (data?.download_url) {
        setReportStates(prev => ({
          ...prev,
          [reportId]: { status: "ready", url: data.download_url, generated_at: new Date().toISOString() },
        }));
        setRecentReports(prev => [{
          type: reportId,
          name: REPORT_TYPES.find(r => r.id === reportId)?.name,
          url: data.download_url,
          generated_at: new Date().toISOString(),
        }, ...prev].slice(0, 20));
      } else {
        setReportStates(prev => ({ ...prev, [reportId]: { status: "ready", data } }));
      }
    } catch (e) {
      console.warn("[ReportsHub] generate error:", e);
      setReportStates(prev => ({ ...prev, [reportId]: { status: "error" } }));
    }
  }, [lat, lon, samCapacity]);

  /* ── Batch generate ────────────────────────────────────────────────────── */
  const generateAll = useCallback(async () => {
    setBatchGenerating(true);
    for (const rt of REPORT_TYPES) {
      await generateReport(rt.id);
    }
    setBatchGenerating(false);
  }, [generateReport]);

  /* ── Download handler ──────────────────────────────────────────────────── */
  const handleDownload = useCallback((url) => {
    if (!url) return;
    window.open(url, "_blank");
  }, []);

  return (
    <div className={`rh-panel${embedded ? " rh-embedded" : ""}`}>
      {!embedded && (
        <div className="rh-header">
          <span className="rh-title">Report Generation</span>
          <button className="rh-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      )}

      <div className="rh-body">
        {/* ── Batch action ── */}
        <div className="rh-batch-row">
          <span className="rh-batch-label">Full Due Diligence Pack</span>
          <button className="rh-btn rh-btn-batch" onClick={generateAll}
            disabled={batchGenerating || !lat}>
            {batchGenerating ? "Generating All..." : "Generate All"}
          </button>
        </div>

        {/* ── Report cards ── */}
        <div className="rh-cards">
          {REPORT_TYPES.map(rt => {
            const state = reportStates[rt.id] || {};
            return (
              <div key={rt.id} className="rh-card">
                <div className="rh-card-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d={rt.icon} />
                  </svg>
                </div>
                <div className="rh-card-body">
                  <div className="rh-card-top">
                    <span className="rh-card-name">{rt.name}</span>
                    <StatusBadge status={state.status} />
                  </div>
                  <p className="rh-card-desc">{rt.description}</p>
                  <div className="rh-card-meta">
                    <span className="rh-card-pages">{rt.pages} {rt.format === "XLSX" ? "sheets" : "pages"}</span>
                    <span className="rh-card-format">{rt.format}</span>
                  </div>
                  <div className="rh-card-actions">
                    <button className="rh-btn rh-btn-gen"
                      onClick={() => generateReport(rt.id)}
                      disabled={state.status === "generating" || !lat}>
                      {state.status === "generating" ? (
                        <span className="rh-spinner" />
                      ) : "Generate"}
                    </button>
                    {state.status === "ready" && state.url && (
                      <button className="rh-btn rh-btn-dl" onClick={() => handleDownload(state.url)}>
                        Download
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Recent reports ── */}
        {recentReports.length > 0 && (
          <div className="rh-recent">
            <h4 className="rh-recent-title">Recent Reports</h4>
            <div className="rh-recent-list">
              {recentReports.map((r, i) => (
                <div key={i} className="rh-recent-item">
                  <div className="rh-recent-info">
                    <span className="rh-recent-name">{r.name || r.type}</span>
                    <span className="rh-recent-date">{fmtDate(r.generated_at)}</span>
                  </div>
                  {r.url && (
                    <button className="rh-btn rh-btn-sm" onClick={() => handleDownload(r.url)}>
                      Download
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
