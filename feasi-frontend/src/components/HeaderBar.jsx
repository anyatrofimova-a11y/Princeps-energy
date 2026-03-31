import React from "react";
import { useSite } from "../SiteContext";

const STAGES = [
  { id: "site", label: "SITE" },
  { id: "study", label: "STUDY" },
  { id: "plan", label: "PLAN" },
  { id: "act", label: "ACT" },
];

const STUDY_STEPS = [
  { id: "feasibility", intent: "feasibility", label: "Feasibility" },
  { id: "grid_study", intent: "grid_study", label: "Grid" },
  { id: "financial", intent: "financial", label: "Financial" },
  { id: "environmental", intent: "environmental", label: "Environ." },
  { id: "planning", intent: "planning", label: "Planning" },
  { id: "satellite_analysis", intent: "satellite_analysis", label: "Satellite" },
  { id: "legacy_compliance", intent: "legacy_compliance", label: "Legacy" },
  { id: "bess_optimisation", intent: "bess_optimisation", label: "BESS" },
  { id: "grid_connection", intent: "grid_connection", label: "Connection" },
  { id: "demand_forecast", intent: "demand_forecast", label: "Demand" },
  { id: "advanced_grid", intent: "advanced_grid", label: "Advanced" },
  { id: "connection_strategy", intent: "connection_strategy", label: "Strategy" },
  { id: "dispatch_optimisation", intent: "dispatch_optimisation", label: "Dispatch" },
  { id: "route_to_market", intent: "route_to_market", label: "RTM" },
  { id: "sustainability", intent: "sustainability", label: "Sustain." },
  { id: "investment_readiness", intent: "investment_readiness", label: "Invest" },
  { id: "financial", intent: "financial", label: "Finance" },
  { id: "site_prospecting", intent: "site_prospecting", label: "Prospect" },
];

const WORKFLOW_BUTTONS = [
  { preset: "full_feasibility", label: "Full Assessment", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" },
  { preset: "grid_deep_dive", label: "Grid Deep Dive", icon: "M13 10V3L4 14h7v7l9-11h-7z" },
  { preset: "investment_ready", label: "Investment Ready", icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
];

function verdictDot(v) {
  if (v === "GO") return "#24a148";
  if (v === "CAUTION") return "#f1c21b";
  if (v === "NO-GO") return "#da1e28";
  if (v === "ERROR") return "#795548";
  return null;
}

export default function HeaderBar({ onAnalyse, onNomExplorer, onLayoutToggle, onSettings, onPitch, onGridTwin }) {
  const {
    parcelId,
    samCapacity, setSamCapacity,
    loading,
    agentResult, solarYield, gridContext, explain,
    workflowStage, workflowHistory, navigateWorkflow,
    studySubStep, setStudySubStep,
    activeIntent, setActiveIntent,
    runAgent, samDay,
    workflowResults, workflowRunning, workflowProgress, workflowSummary,
    runWorkflow,
    setWorkflowPanelOpen, setExportPanelOpen,
  } = useSite();

  const handleStepClick = (step) => {
    setStudySubStep(step.id);
    setActiveIntent(step.intent);
    if (workflowResults[step.intent]) return;
    if (parcelId) runAgent(parcelId, step.intent, samCapacity, samDay);
  };

  const handleWorkflowClick = (preset) => {
    if (!parcelId || workflowRunning) return;
    runWorkflow(parcelId, preset, samCapacity, samDay);
  };

  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const score = explain?.score_total;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const verdict = workflowSummary?.overall_verdict || agentResult?.verdict;
  const confidence = workflowSummary?.average_confidence || agentResult?.confidence;

  return (
    <header className="header-v2">
      <div className="header-v2-left">
        <span className="header-v2-brand">PRINCEPS</span>
        <nav className="breadcrumb-nav">
          {STAGES.map((s, i) => {
            const visited = workflowHistory.includes(s.id);
            const active = workflowStage === s.id;
            return (
              <React.Fragment key={s.id}>
                {i > 0 && <span className="breadcrumb-sep" />}
                <button
                  className={`breadcrumb-step${active ? " active" : ""}${visited && !active ? " visited" : ""}${!visited ? " locked" : ""}`}
                  onClick={() => visited && navigateWorkflow(s.id)}
                  disabled={!visited}
                >
                  {s.label}
                </button>
              </React.Fragment>
            );
          })}
        </nav>
      </div>

      {/* Study sub-nav */}
      {workflowStage === "study" && (
        <div className="study-subnav">
          {/* Individual step buttons */}
          {STUDY_STEPS.map((step) => {
            const stepResult = workflowResults[step.intent];
            const dot = stepResult ? verdictDot(stepResult.verdict) : null;
            const isRunning = workflowProgress?.intent === step.intent;
            return (
              <button
                key={step.id}
                className={`study-subnav-btn${studySubStep === step.id ? " active" : ""}${isRunning ? " running" : ""}${dot ? " completed" : ""}`}
                onClick={() => handleStepClick(step)}
              >
                {isRunning && <span className="subnav-spinner" />}
                {dot && !isRunning && <span className="subnav-verdict-dot" style={{ background: dot }} />}
                {step.label}
              </button>
            );
          })}

          <span className="subnav-divider" />

          {/* Workflow triggers */}
          {WORKFLOW_BUTTONS.map((w) => {
            const isActive = workflowRunning && workflowProgress?.preset === w.preset;
            return (
              <button
                key={w.preset}
                className={`wf-trigger${isActive ? " active" : ""}${workflowRunning && !isActive ? " disabled" : ""}`}
                onClick={() => handleWorkflowClick(w.preset)}
                disabled={!parcelId || workflowRunning}
                title={w.label}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d={w.icon} />
                </svg>
                {isActive
                  ? <span className="wf-trigger-progress">{workflowProgress.step}/{workflowProgress.total}</span>
                  : <span>{w.label}</span>}
              </button>
            );
          })}
        </div>
      )}

      <div className="header-v2-right">
        {/* Compact KPIs */}
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

        <button className="btn-topbar-action" onClick={() => setWorkflowPanelOpen(true)}>FLOW</button>
        <button className="btn-topbar-action" onClick={() => setExportPanelOpen(true)}>EXPORT</button>
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
