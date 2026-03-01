import React from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";

export default function TopStatusBar({ onGridTwin, onPitch, onNomExplorer, onSettings }) {
  const {
    solarYield, gridContext, explain,
    agentResult, workflowSummary,
    samCapacity, setSamCapacity,
  } = useSite();
  const { activeWorkspace } = useWorkspace();

  const wsLabel = WORKSPACES.find(w => w.id === activeWorkspace)?.label || "Princeps";
  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const verdict = workflowSummary?.overall_verdict || agentResult?.verdict;
  const confidence = workflowSummary?.average_confidence || agentResult?.confidence;

  return (
    <header className="top-status-bar">
      <div className="tsb-left">
        <span className="tsb-workspace-name">{wsLabel}</span>
      </div>

      <div className="tsb-center">
        <div className="kpi-strip">
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
          <div className="kpi-item">
            <span className="kpi-label">GRID</span>
            <span className="kpi-value" style={{ color: "var(--cds-interactive)" }}>
              {gridDist ? `${gridDist.toFixed(1)}km` : "--"}
            </span>
          </div>
          {verdict && (
            <div className="kpi-item kpi-verdict">
              <span className="kpi-label">VERDICT</span>
              <span className={`kpi-verdict-pill kpi-verdict-${verdict.toLowerCase().replace("-", "")}`}>
                {verdict}
              </span>
            </div>
          )}
          {confidence != null && confidence > 0 && (
            <div className="kpi-item">
              <span className="kpi-label">CONF</span>
              <span className="kpi-value" style={{ color: "#a56eff" }}>
                {Math.round(confidence * 100)}%
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="tsb-right">
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
        <button className="btn-topbar-action" onClick={onGridTwin}>TWIN</button>
        <button className="btn-topbar-action" onClick={onPitch}>PITCH</button>
        <button className="btn-topbar-action" onClick={onNomExplorer}>NOM</button>
        <button className="btn-topbar-icon" onClick={onSettings} title="Settings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
