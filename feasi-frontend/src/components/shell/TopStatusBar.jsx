import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";
import api from "../../services/api";

const STEPS = [
  { id: "site",  label: "Discover", sub: "Find & select sites",  icon: "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z", num: "1" },
  { id: "study", label: "Analyse",  sub: "AI feasibility study", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", num: "2", gate: "pickedLocation" },
  { id: "plan",  label: "Design",   sub: "3D layout & sizing",   icon: "M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z", num: "3", gate: "agentResult" },
  { id: "act",   label: "Execute",  sub: "Export & procure",     icon: "M5 12h14M12 5l7 7-7 7", num: "4" },
];

function WorkflowSteps() {
  const { workflowStage, navigateWorkflow, pickedLocation, agentResult, workflowHistory } = useSite();
  const stageIdx = STEPS.findIndex(s => s.id === workflowStage);

  const canNavigate = (step) => {
    if (step.id === "site") return true;
    if (step.id === "study") return !!pickedLocation;
    if (step.id === "plan") return !!agentResult;
    if (step.id === "act") return !!agentResult;
    return false;
  };

  return (
    <div className="workflow-steps">
      {STEPS.map((step, i) => {
        const done = workflowHistory.includes(step.id) && i < stageIdx;
        const active = i === stageIdx;
        const reachable = canNavigate(step);
        const locked = !reachable && !done && !active;
        return (
          <React.Fragment key={step.id}>
            {i > 0 && (
              <div className={`workflow-step-line${done ? " done" : active ? " active" : ""}`}>
                <div className="workflow-step-line-fill" />
              </div>
            )}
            <button
              className={`workflow-step${active ? " active" : ""}${done ? " done" : ""}${locked ? " locked" : ""}`}
              onClick={() => reachable && navigateWorkflow(step.id)}
              disabled={locked}
              title={locked ? `Complete ${STEPS[i - 1]?.label || "previous step"} first` : step.sub}
            >
              <div className="workflow-step-dot">
                {done ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>
                ) : locked ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                ) : (
                  <span className="workflow-step-num">{step.num}</span>
                )}
              </div>
              <div className="workflow-step-text">
                <span className="workflow-step-label">{step.label}</span>
                <span className="workflow-step-sub">{step.sub}</span>
              </div>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function MoreMenu({ items }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button className="btn-topbar-action" onClick={() => setOpen(!open)} title="More tools">
        ···
      </button>
      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 1199 }} onClick={() => setOpen(false)} />
          <div style={{
            position: "absolute", top: "100%", right: 0, marginTop: 4,
            background: "#ffffff", border: "1px solid rgba(0,0,0,0.1)",
            borderRadius: 8, padding: "4px 0", zIndex: 1200, minWidth: 160,
            boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
          }}>
            {items.map((it, i) => (
              <button key={i} onClick={() => { setOpen(false); it.action?.(); }} style={{
                display: "block", width: "100%", padding: "7px 14px", border: "none",
                background: "transparent", color: "#374151", fontSize: 12,
                textAlign: "left", cursor: "pointer",
              }}
                onMouseEnter={e => e.target.style.background = "rgba(124,92,252,0.06)"}
                onMouseLeave={e => e.target.style.background = "transparent"}
              >{it.label}</button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function TopStatusBar({ onGridTwin, onBems, onAssetInspect, onGridGraph, onBessFacility, onHardware, onThermal, onPitch, onNomExplorer, onSettings, onCommandPalette, onDcTwin }) {
  const {
    solarYield, gridContext, explain,
    agentResult, workflowSummary,
    samCapacity, setSamCapacity,
    pickedLocation, parcelId,
  } = useSite();
  const { activeWorkspace } = useWorkspace();

  const wsLabel = WORKSPACES.find(w => w.id === activeWorkspace)?.label || "Princeps";

  // PDF download
  const [pdfLoading, setPdfLoading] = useState(false);
  const downloadPdf = useCallback(async () => {
    if (pdfLoading) return;
    setPdfLoading(true);
    try {
      const lat = explain?.lat ?? explain?.location?.lat ?? pickedLocation?.lat;
      const lon = explain?.lon ?? explain?.location?.lon ?? pickedLocation?.lon;
      if (!lat || !lon) { alert("Select a site first"); setPdfLoading(false); return; }
      const name = explain?.name || parcelId || "Site";
      const blob = await api.reports.siteAssessment(lat, lon, name, samCapacity / 1000 || 50);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `princeps-report-${name.replace(/[^\w-]/g, "-")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("PDF download failed:", e);
      alert("Report generation failed — see console.");
    } finally {
      setPdfLoading(false);
    }
  }, [explain, pickedLocation, parcelId, samCapacity, pdfLoading]);
  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const verdict = workflowSummary?.overall_verdict || agentResult?.verdict;
  const confidence = workflowSummary?.average_confidence || agentResult?.confidence;

  return (
    <header className="top-status-bar">
      <div className="tsb-left">
        <WorkflowSteps />
      </div>

      <div className="tsb-center">
        <button className="tsb-search-trigger" onClick={onCommandPalette}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          Search sites, commands...
          <kbd>&#8984;K</kbd>
        </button>
      </div>

      <div className="tsb-right">
        <div className="kpi-strip">
          {activeWorkspace !== "analyse" && (
            <>
              <div className="kpi-item">
                <span className="kpi-label">CF</span>
                <span className="kpi-value" style={{ color: "var(--cds-interactive)" }}>
                  {cf ? `${cf.toFixed(1)}%` : "--"}
                </span>
              </div>
              <div className="kpi-item">
                <span className="kpi-label">MWh</span>
                <span className="kpi-value" style={{ color: "var(--cds-support-warning)" }}>
                  {annualKwh ? `${(annualKwh / 1000).toFixed(0)}` : "--"}
                </span>
              </div>
            </>
          )}
          <div className="kpi-item">
            <span className="kpi-label">Grid</span>
            <span className="kpi-value" style={{ color: "var(--cyan)" }}>
              {gridDist ? `${gridDist.toFixed(1)}km` : "--"}
            </span>
          </div>
          {verdict && (
            <div className="kpi-item kpi-verdict">
              <span className={`kpi-verdict-pill kpi-verdict-${verdict.toLowerCase().replace("-", "")}`}>
                {verdict}
              </span>
            </div>
          )}
          {confidence != null && confidence > 0 && (
            <div className="kpi-item">
              <span className="kpi-label">Conf</span>
              <span className="kpi-value" style={{ color: "var(--purple-soft)" }}>
                {Math.round(confidence * 100)}%
              </span>
            </div>
          )}
        </div>

        <span className="header-v2-param">
          <input
            type="number"
            value={samCapacity}
            onChange={(e) => setSamCapacity(Number(e.target.value))}
            style={{ width: 48 }}
            min={1}
          />
          <span>kW</span>
        </span>
        <button
          className="btn-topbar-action"
          onClick={downloadPdf}
          disabled={pdfLoading}
          title="Download PDF site report"
        >
          {pdfLoading ? "..." : "PDF"}
        </button>
        <button className="btn-topbar-action" onClick={onGridTwin} title="Grid Digital Twin">Twin</button>
        <button className="btn-topbar-action" onClick={onDcTwin} title="Data Centre Twin">DC</button>
        <button className="btn-topbar-action" onClick={onBessFacility} title="BESS Facility Twin">BESS</button>
        <MoreMenu
          items={[
            { label: "BEMS Twin", action: onBems },
            { label: "Asset Inspector", action: onAssetInspect },
            { label: "Grid Graph", action: onGridGraph },
            { label: "Hardware Config", action: onHardware },
            { label: "Thermal Model", action: onThermal },
            { label: "Pitch Deck", action: onPitch },
            { label: "NOM Explorer", action: onNomExplorer },
          ]}
        />
        <button className="btn-topbar-icon" onClick={onSettings} title="Settings">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
