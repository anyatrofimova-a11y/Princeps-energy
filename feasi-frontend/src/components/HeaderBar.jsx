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
  { id: "satellite_analysis", intent: "satellite_analysis", label: "Satellite" },
  { id: "legacy_compliance", intent: "legacy_compliance", label: "Legacy" },
  { id: "bess", intent: "bess", label: "BESS" },
];

const WORKFLOW_BUTTONS = [
  { preset: "full_feasibility", label: "Full Feasibility", color: "#4caf50" },
  { preset: "grid_deep_dive", label: "Grid Deep Dive", color: "#2196f3" },
  { preset: "investment_ready", label: "Investment Ready", color: "#a56eff" },
];

function verdictDotColor(v) {
  if (v === "GO") return "#4caf50";
  if (v === "CAUTION") return "#ff9800";
  if (v === "NO-GO") return "#f44336";
  if (v === "ERROR") return "#795548";
  return null;
}

export default function HeaderBar({ onAnalyse, onNomExplorer, onLayoutToggle, onSettings, onPitch }) {
  const {
    parcelId,
    samCapacity, setSamCapacity,
    samDay, setSamDay,
    loading,
    agentResult, solarYield, gridContext, explain,
    workflowStage, workflowHistory, navigateWorkflow,
    studySubStep, setStudySubStep,
    activeIntent, setActiveIntent,
    runAgent,
    // Chained workflows
    workflowResults, workflowRunning, workflowProgress,
    runWorkflow,
  } = useSite();

  const handleStepClick = (step) => {
    setStudySubStep(step.id);
    setActiveIntent(step.intent);
    // If we have a cached workflow result for this step, show it
    if (workflowResults[step.intent]) return;
    if (parcelId) {
      runAgent(parcelId, step.intent, samCapacity, samDay);
    }
  };

  const handleWorkflowClick = (preset) => {
    if (!parcelId || workflowRunning) return;
    runWorkflow(parcelId, preset, samCapacity, samDay);
  };

  // KPI data
  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const score = explain?.score_total;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const verdict = agentResult?.verdict;
  const confidence = agentResult?.confidence;

  const verdictColor = verdict === "GO" ? "var(--cds-support-success)" :
    verdict === "CAUTION" ? "var(--cds-support-warning)" :
    verdict === "NO-GO" ? "var(--cds-support-error)" : "var(--cds-text-helper)";

  return (
    <header className="header-v2">
      <div className="header-v2-left">
        <span className="header-v2-brand">FEASIBLY</span>
        <nav className="breadcrumb-nav">
          {STAGES.map((s, i) => {
            const visited = workflowHistory.includes(s.id);
            const active = workflowStage === s.id;
            return (
              <React.Fragment key={s.id}>
                {i > 0 && <span className="breadcrumb-sep">&gt;</span>}
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

      {/* Study sub-nav — only in STUDY stage */}
      {workflowStage === "study" && (
        <div className="study-subnav">
          {STUDY_STEPS.map((step) => {
            const stepResult = workflowResults[step.intent];
            const dotColor = stepResult ? verdictDotColor(stepResult.verdict) : null;
            const isRunning = workflowProgress?.intent === step.intent;
            return (
              <button
                key={step.id}
                className={`study-subnav-btn${studySubStep === step.id ? " active" : ""}${isRunning ? " running" : ""}`}
                onClick={() => handleStepClick(step)}
              >
                {dotColor && <span className="subnav-verdict-dot" style={{ background: dotColor }} />}
                {isRunning && <span className="subnav-spinner" />}
                {step.label}
              </button>
            );
          })}

          <span className="subnav-divider" />

          {/* Workflow trigger buttons */}
          {WORKFLOW_BUTTONS.map((w) => (
            <button
              key={w.preset}
              className={`workflow-trigger-btn${workflowRunning ? " disabled" : ""}`}
              style={{ borderColor: w.color, color: w.color }}
              onClick={() => handleWorkflowClick(w.preset)}
              disabled={!parcelId || workflowRunning}
              title={w.label}
            >
              {workflowRunning && workflowProgress?.preset === w.preset
                ? `${workflowProgress.step}/${workflowProgress.total}`
                : w.label}
            </button>
          ))}
        </div>
      )}

      <div className="header-v2-right">
        {/* KPI strip */}
        <div className="kpi-strip">
          <div className="kpi-item">
            <span className="kpi-label">YIELD</span>
            <span className="kpi-value" style={{ color: "var(--cds-support-warning)" }}>
              {annualKwh ? `${(annualKwh / 1000).toFixed(1)}` : "--"}
            </span>
          </div>
          <div className="kpi-item">
            <span className="kpi-label">CF</span>
            <span className="kpi-value" style={{ color: "var(--cds-interactive)" }}>
              {cf ? `${cf.toFixed(1)}%` : "--"}
            </span>
          </div>
          <div className="kpi-item">
            <span className="kpi-label">SCORE</span>
            <span className="kpi-value" style={{ color: "var(--cds-support-success)" }}>
              {score != null ? `${score}` : "--"}
            </span>
          </div>
          <div className="kpi-item">
            <span className="kpi-label">GRID</span>
            <span className="kpi-value" style={{ color: "var(--cds-interactive)" }}>
              {gridDist ? `${gridDist.toFixed(1)}km` : "--"}
            </span>
          </div>
          <div className="kpi-item">
            <span className="kpi-label">VERDICT</span>
            <span className="kpi-value" style={{ color: verdictColor }}>
              {verdict || "--"}
            </span>
          </div>
          <div className="kpi-item">
            <span className="kpi-label">CONF</span>
            <span className="kpi-value" style={{ color: "#a56eff" }}>
              {confidence ? `${Math.round(confidence * 100)}%` : "--"}
            </span>
          </div>
        </div>

        {/* SAM params */}
        <span className="header-v2-param">
          <input
            type="number"
            value={samCapacity}
            onChange={(e) => setSamCapacity(Number(e.target.value))}
            style={{ width: 50 }}
            min={1}
          />
          kW
        </span>

        {/* Action buttons */}
        <button className="btn-topbar-action" onClick={onPitch}>PITCH</button>
        <button className="btn-topbar-action" onClick={onNomExplorer}>NOM</button>
        <button className="btn-topbar-action" onClick={onSettings} title="Settings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
