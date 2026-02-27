import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";

const INTENTS = [
  { value: "feasibility", label: "Feasibility", color: "#4caf50" },
  { value: "grid_study", label: "Grid Study", color: "#2196f3" },
  { value: "financial", label: "Financial", color: "#ff9800" },
  { value: "environmental", label: "Environmental", color: "#66bb6a" },
  { value: "planning", label: "Planning", color: "#e91e63" },
  { value: "satellite_analysis", label: "Satellite / DL", color: "#1565c0" },
  { value: "legacy_compliance", label: "Legacy / Compliance", color: "#ef6c00" },
  { value: "procurement", label: "Procurement", color: "#ff5722" },
  { value: "grid_efficiency", label: "Grid Efficiency", color: "#795548" },
  { value: "site_prospecting", label: "Site Prospecting", color: "#009688" },
  { value: "home_retrofit", label: "Home Retrofit", color: "#8e24aa" },
  { value: "infrastructure_retrofit", label: "Infra Retrofit", color: "#607d8b" },
];

function verdictColor(v) {
  if (v === "GO") return "#4caf50";
  if (v === "CAUTION") return "#ff9800";
  return "#f44336";
}

export default function AgentPanel({
  parcelId,
  samCapacity,
  samDay,
  agentResult,
  setAgentResult,
  agentLoading,
  setAgentLoading,
}) {
  const {
    workflowResults, workflowRunning, workflowSummary,
    setActiveIntent, setStudySubStep,
  } = useSite();

  const [intent, setIntent] = useState("feasibility");
  const [showDevConsole, setShowDevConsole] = useState(false);
  const [jobStatuses, setJobStatuses] = useState({});
  const [error, setError] = useState(null);
  const [activeResultTab, setActiveResultTab] = useState(null);

  const hasWorkflowResults = Object.keys(workflowResults).length > 0;

  // Show a specific workflow result
  const showWorkflowResult = useCallback((wfIntent) => {
    const result = workflowResults[wfIntent];
    if (result) {
      setActiveResultTab(wfIntent);
      setAgentResult(result);
      setActiveIntent(wfIntent);
      setStudySubStep(wfIntent);
    }
  }, [workflowResults, setAgentResult, setActiveIntent, setStudySubStep]);

  const runAgent = useCallback(async () => {
    if (!parcelId) return;
    setAgentLoading(true);
    setError(null);
    setActiveResultTab(null);
    try {
      const res = await fetch(`/site/${encodeURIComponent(parcelId)}/agent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intent,
          capacity_kw: samCapacity,
          day_of_year: samDay,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setAgentResult(data.agent);
      } else {
        const errData = await res.json().catch(() => null);
        setError(errData?.detail || `Server error (${res.status})`);
      }
    } catch (err) {
      console.error(err);
      setError(err.message || "Network error");
    } finally {
      setAgentLoading(false);
    }
  }, [parcelId, intent, samCapacity, samDay, setAgentResult, setAgentLoading]);

  const executeAction = useCallback(
    async (action) => {
      const key = action.endpoint;
      setJobStatuses((prev) => ({ ...prev, [key]: "running" }));
      try {
        const opts = { method: action.method };
        if (action.method === "POST" && action.payload) {
          opts.headers = { "Content-Type": "application/json" };
          opts.body = JSON.stringify(action.payload);
        }
        const res = await fetch(action.endpoint, opts);
        if (res.ok) {
          const data = await res.json();
          if (data.job_id) {
            setJobStatuses((prev) => ({
              ...prev,
              [key]: `Job ${data.job_id} submitted`,
            }));
            pollJob(data.job_id, key);
          } else {
            setJobStatuses((prev) => ({ ...prev, [key]: "done" }));
          }
        } else {
          const errText = await res.text().catch(() => "");
          const detail = errText ? `: ${errText.slice(0, 80)}` : "";
          setJobStatuses((prev) => ({ ...prev, [key]: `${res.status} error${detail}` }));
        }
      } catch (err) {
        setJobStatuses((prev) => ({ ...prev, [key]: `error: ${err.message || "network"}` }));
      }
    },
    []
  );

  const pollJob = useCallback((jobId, key) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/job/${jobId}`);
        if (res.ok) {
          const job = await res.json();
          if (job.status === "done" || job.status === "failed") {
            clearInterval(interval);
            setJobStatuses((prev) => ({
              ...prev,
              [key]: job.status === "done"
                ? `Done (${job.elapsed_s}s)`
                : `Failed: ${job.error}`,
            }));
          }
        }
      } catch {
        clearInterval(interval);
      }
    }, 2000);
  }, []);

  return (
    <div className="agent-panel-inner">
        <div className="agent-body">
          {/* Workflow results tabs */}
          {hasWorkflowResults && (
            <div className="workflow-result-tabs">
              {Object.entries(workflowResults).map(([wfIntent, result]) => (
                <button
                  key={wfIntent}
                  className={`workflow-result-tab${activeResultTab === wfIntent ? " active" : ""}`}
                  style={{ borderColor: verdictColor(result.verdict) }}
                  onClick={() => showWorkflowResult(wfIntent)}
                >
                  <span className="wf-tab-dot" style={{ background: verdictColor(result.verdict) }} />
                  {INTENTS.find(i => i.value === wfIntent)?.label || wfIntent}
                </button>
              ))}
              {workflowRunning && (
                <span className="workflow-result-tab running">
                  <span className="verdict-spinner" style={{ width: 10, height: 10 }} />
                  Running...
                </span>
              )}
            </div>
          )}

          {/* Intent selector + run button */}
          <div className="agent-controls">
            <div className="agent-intent-row">
              {INTENTS.map((i) => (
                <button
                  key={i.value}
                  className={`agent-intent-btn ${intent === i.value ? "active" : ""}`}
                  style={{
                    borderColor: i.color,
                    background: intent === i.value ? i.color : "transparent",
                    color: intent === i.value ? "#fff" : i.color,
                  }}
                  onClick={() => setIntent(i.value)}
                >
                  {i.label}
                </button>
              ))}
            </div>
            <div className="agent-action-row">
              <button
                className="btn-agent"
                onClick={runAgent}
                disabled={agentLoading || !parcelId}
              >
                {agentLoading ? "Thinking..." : "Run Agent"}
              </button>
              <button
                className="agent-dev-toggle"
                onClick={() => setShowDevConsole((p) => !p)}
                title="Toggle developer console"
              >
                {showDevConsole ? "Hide Context" : "Dev Console"}
              </button>
            </div>
          </div>

          {/* Dev console — raw context JSON */}
          {showDevConsole && agentResult && (
            <div className="agent-dev-console">
              <pre>{JSON.stringify(agentResult, null, 2)}</pre>
            </div>
          )}

          {/* Results */}
          {agentResult && (
            <>
              <div
                className="agent-verdict"
                style={{ background: verdictColor(agentResult.verdict) }}
              >
                {agentResult.verdict}
                <span className="agent-conf">
                  {Math.round((agentResult.confidence || 0) * 100)}% conf
                </span>
                {agentResult.intent && (
                  <span className="agent-intent-tag">{agentResult.intent}</span>
                )}
              </div>

              <p className="agent-summary">{agentResult.summary}</p>

              <div className="agent-columns">
                {agentResult.risks?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title risk">Risks</div>
                    <ul>
                      {agentResult.risks.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {agentResult.opportunities?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title opp">Opportunities</div>
                    <ul>
                      {agentResult.opportunities.map((o, i) => (
                        <li key={i}>{o}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {agentResult.next_steps?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title steps">Next Steps</div>
                    <ol>
                      {agentResult.next_steps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>

              {agentResult.recommended_capacity_kw != null && (
                <div className="agent-meta">
                  Recommended capacity:{" "}
                  <strong>{agentResult.recommended_capacity_kw} kW</strong>
                  {agentResult.estimated_roi_years != null && (
                    <>
                      {" "}| Est. ROI:{" "}
                      <strong>{agentResult.estimated_roi_years} years</strong>
                    </>
                  )}
                </div>
              )}

              {/* Action buttons */}
              {agentResult.actions?.length > 0 && (
                <div className="agent-actions">
                  <div className="section-label">Suggested Actions</div>
                  <div className="agent-action-btns">
                    {agentResult.actions.map((action, i) => (
                      <button
                        key={i}
                        className="agent-action-btn"
                        onClick={() => executeAction(action)}
                        disabled={jobStatuses[action.endpoint] === "running"}
                        title={`${action.method} ${action.endpoint}`}
                      >
                        {action.label}
                        {jobStatuses[action.endpoint] && (
                          <span className="agent-action-status">
                            {jobStatuses[action.endpoint]}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Workflow summary card */}
          {workflowSummary && !workflowRunning && (
            <div className="workflow-summary-card">
              <div className="section-label">Workflow Summary</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <span className="agent-verdict" style={{ background: verdictColor(workflowSummary.overall_verdict), fontSize: 13, padding: "3px 10px" }}>
                  {workflowSummary.overall_verdict}
                </span>
                <span style={{ fontSize: 11, color: "var(--cds-text-helper)" }}>
                  {Math.round(workflowSummary.average_confidence * 100)}% avg | {workflowSummary.steps_completed} steps
                </span>
              </div>
              {workflowSummary.top_risks?.length > 0 && (
                <div style={{ fontSize: 11, marginBottom: 4 }}>
                  <span style={{ color: "#f44336" }}>Top risks: </span>
                  {workflowSummary.top_risks.slice(0, 3).join(" | ")}
                </div>
              )}
              {workflowSummary.top_opportunities?.length > 0 && (
                <div style={{ fontSize: 11 }}>
                  <span style={{ color: "#4caf50" }}>Opportunities: </span>
                  {workflowSummary.top_opportunities.slice(0, 3).join(" | ")}
                </div>
              )}
            </div>
          )}

          {error && (
            <div style={{ color: "var(--danger, #ff4757)", fontSize: 12, marginTop: 8, padding: "6px 10px", background: "rgba(255,71,87,0.08)", borderRadius: 6, border: "1px solid rgba(255,71,87,0.2)" }}>
              {error}
            </div>
          )}

          {!agentResult && !agentLoading && !error && !hasWorkflowResults && (
            <span className="muted">
              Select an intent and click Run Agent to start analysis
            </span>
          )}
        </div>
    </div>
  );
}
