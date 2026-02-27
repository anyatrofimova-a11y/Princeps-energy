import React, { useEffect } from "react";
import { useSite } from "../SiteContext";

function verdictClass(v) {
  if (v === "GO") return "verdict-go";
  if (v === "CAUTION") return "verdict-caution";
  return "verdict-nogo";
}

function verdictDotColor(v) {
  if (v === "GO") return "#24a148";
  if (v === "CAUTION") return "#f1c21b";
  if (v === "NO-GO") return "#da1e28";
  if (v === "ERROR") return "#795548";
  return "rgba(255,255,255,0.2)";
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
    workflowResults, workflowSummary, workflowRunning, workflowProgress,
    setAgentResult, setStudySubStep,
  } = useSite();

  useEffect(() => {
    if (parcelId && !agentResult && !agentLoading && workflowStage === "study" && !workflowRunning) {
      setActiveIntent("feasibility");
      runAgent(parcelId, "feasibility", samCapacity, samDay);
    }
  }, [parcelId, workflowStage]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasWorkflow = Object.keys(workflowResults).length > 0;

  const handleStepClick = (intent) => {
    const result = workflowResults[intent];
    if (result) {
      setActiveIntent(intent);
      setStudySubStep(intent);
      setAgentResult(result);
    }
  };

  if (!parcelId) return null;

  // Workflow stepper mode
  if (workflowRunning || hasWorkflow) {
    const completedSteps = Object.entries(workflowResults);
    const totalSteps = workflowProgress?.total || completedSteps.length;
    const progress = totalSteps > 0 ? (completedSteps.length / totalSteps) * 100 : 0;

    return (
      <div className="verdict-hero wf-mode">
        {/* Progress bar */}
        <div className="wf-progress-track">
          <div
            className="wf-progress-fill"
            style={{ width: `${workflowRunning ? Math.max(progress, 5) : 100}%` }}
          />
        </div>

        {/* Step pills */}
        <div className="wf-stepper">
          {completedSteps.map(([intent, result], idx) => (
            <button
              key={intent}
              className={`wf-step-pill${activeIntent === intent ? " active" : ""}`}
              onClick={() => handleStepClick(intent)}
              title={`${INTENT_LABELS[intent] || intent}: ${result.verdict} (${Math.round((result.confidence || 0) * 100)}%)`}
            >
              <span className="wf-step-dot" style={{ background: verdictDotColor(result.verdict) }} />
              <span className="wf-step-name">{INTENT_LABELS[intent] || intent}</span>
              <span className={`wf-step-verdict ${verdictClass(result.verdict)}`}>{result.verdict}</span>
            </button>
          ))}

          {/* Currently running step */}
          {workflowRunning && workflowProgress && !workflowResults[workflowProgress.intent] && (
            <span className="wf-step-pill running">
              <span className="wf-step-spinner" />
              <span className="wf-step-name">{INTENT_LABELS[workflowProgress.intent] || workflowProgress.intent}</span>
              <span className="wf-step-meta">{workflowProgress.step}/{workflowProgress.total}</span>
            </span>
          )}
        </div>

        {/* Overall summary when done */}
        {workflowSummary && !workflowRunning && (
          <div className="wf-overall">
            <span className={`verdict-badge ${verdictClass(workflowSummary.overall_verdict)}`}>
              {workflowSummary.overall_verdict}
            </span>
            <span className="wf-overall-conf">
              {Math.round(workflowSummary.average_confidence * 100)}% avg confidence
            </span>
            <span className="wf-overall-steps">
              {workflowSummary.steps_completed} analyses complete
            </span>
          </div>
        )}

        {/* Current step detail */}
        {agentResult && (
          <div className="wf-current-detail">
            <div className="wf-current-header">
              <span className={`verdict-badge sm ${verdictClass(agentResult.verdict)}`}>
                {agentResult.verdict}
              </span>
              <span className="wf-current-intent">{INTENT_LABELS[agentResult.intent] || agentResult.intent}</span>
              <span className="wf-current-conf">{Math.round((agentResult.confidence || 0) * 100)}%</span>
              {(agentLoading || workflowRunning) && <span className="verdict-spinner sm" />}
            </div>
            <p className="verdict-summary">{agentResult.summary}</p>
          </div>
        )}
      </div>
    );
  }

  // Single-intent mode (original)
  if (agentLoading && !agentResult) {
    return (
      <div className="verdict-hero">
        <div className="verdict-loading">
          <div className="verdict-spinner" />
          Analysing site...
        </div>
      </div>
    );
  }

  if (!agentResult) return null;

  return (
    <div className="verdict-hero">
      <div className="verdict-row">
        <span className={`verdict-badge ${verdictClass(agentResult.verdict)}`}>
          {agentResult.verdict}
        </span>
        <span className="verdict-conf">
          {Math.round((agentResult.confidence || 0) * 100)}% confidence
        </span>
        {agentResult.intent && (
          <span className="verdict-intent-label">{agentResult.intent}</span>
        )}
        {agentLoading && <div className="verdict-spinner sm" />}
      </div>
      <p className="verdict-summary">{agentResult.summary}</p>
    </div>
  );
}
