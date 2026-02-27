import React, { useEffect } from "react";
import { useSite } from "../SiteContext";

function verdictClass(v) {
  if (v === "GO") return "verdict-go";
  if (v === "CAUTION") return "verdict-caution";
  return "verdict-nogo";
}

function verdictDotColor(v) {
  if (v === "GO") return "#4caf50";
  if (v === "CAUTION") return "#ff9800";
  if (v === "NO-GO") return "#f44336";
  if (v === "ERROR") return "#795548";
  return "var(--cds-text-helper)";
}

const INTENT_LABELS = {
  feasibility: "Feasibility",
  grid_study: "Grid Study",
  environmental: "Environmental",
  financial: "Financial",
  planning: "Planning",
  satellite_analysis: "Satellite",
  bess_optimisation: "BESS",
  grid_efficiency: "Grid Efficiency",
  legacy_compliance: "Legacy",
  procurement: "Procurement",
  site_prospecting: "Prospecting",
};

export default function AgentVerdict() {
  const {
    parcelId, agentResult, agentLoading, runAgent,
    samCapacity, samDay, activeIntent, setActiveIntent,
    workflowStage,
    // Chained workflows
    workflowResults, workflowSummary, workflowRunning, workflowProgress,
    setAgentResult, setStudySubStep,
  } = useSite();

  // Auto-run agent when parcelId is set and no result yet (only in study stage)
  useEffect(() => {
    if (parcelId && !agentResult && !agentLoading && workflowStage === "study" && !workflowRunning) {
      setActiveIntent("feasibility");
      runAgent(parcelId, "feasibility", samCapacity, samDay);
    }
  }, [parcelId, workflowStage]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasWorkflowResults = Object.keys(workflowResults).length > 0;

  const handleStepClick = (intent) => {
    const result = workflowResults[intent];
    if (result) {
      setActiveIntent(intent);
      setStudySubStep(intent);
      setAgentResult(result);
    }
  };

  if (!parcelId) return null;

  return (
    <div className="verdict-hero">
      {/* Workflow progress stepper */}
      {(workflowRunning || hasWorkflowResults) && (
        <div className="workflow-stepper">
          {Object.entries(workflowResults).map(([intent, result], idx) => {
            const isActive = workflowProgress?.intent === intent;
            return (
              <button
                key={intent}
                className={`workflow-step${activeIntent === intent ? " active" : ""}${isActive ? " running" : ""}`}
                onClick={() => handleStepClick(intent)}
                title={`${INTENT_LABELS[intent] || intent}: ${result.verdict}`}
              >
                <span
                  className="workflow-step-dot"
                  style={{ background: verdictDotColor(result.verdict) }}
                />
                <span className="workflow-step-label">
                  {INTENT_LABELS[intent] || intent}
                </span>
              </button>
            );
          })}
          {workflowRunning && workflowProgress && !workflowResults[workflowProgress.intent] && (
            <span className="workflow-step running">
              <span className="workflow-step-spinner" />
              <span className="workflow-step-label">
                {INTENT_LABELS[workflowProgress.intent] || workflowProgress.intent}
              </span>
            </span>
          )}
        </div>
      )}

      {/* Workflow summary */}
      {workflowSummary && !workflowRunning && (
        <div className="workflow-summary-bar">
          <span className={`verdict-badge ${verdictClass(workflowSummary.overall_verdict)}`}>
            {workflowSummary.overall_verdict}
          </span>
          <span style={{ fontSize: 12, color: "var(--cds-text-helper)" }}>
            {Math.round(workflowSummary.average_confidence * 100)}% avg confidence
          </span>
          <span style={{ fontSize: 11, color: "var(--cds-text-helper)" }}>
            {workflowSummary.steps_completed} steps completed
          </span>
        </div>
      )}

      {/* Current step verdict */}
      {agentLoading && !agentResult && !workflowRunning ? (
        <div className="verdict-loading">
          <div className="verdict-spinner" />
          Analysing site...
        </div>
      ) : agentResult ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className={`verdict-badge ${verdictClass(agentResult.verdict)}`}>
              {agentResult.verdict}
            </span>
            <span style={{ fontSize: 12, color: "var(--cds-text-helper)" }}>
              {Math.round((agentResult.confidence || 0) * 100)}% confidence
            </span>
            {agentResult.intent && (
              <span style={{ fontSize: 10, color: "var(--cds-text-helper)", textTransform: "uppercase", letterSpacing: 1 }}>
                {agentResult.intent}
              </span>
            )}
            {(agentLoading || workflowRunning) && <div className="verdict-spinner" />}
          </div>
          <div className="verdict-summary">{agentResult.summary}</div>
        </>
      ) : null}
    </div>
  );
}
