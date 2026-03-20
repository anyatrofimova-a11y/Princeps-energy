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
  { value: "bess_optimisation", label: "BESS", color: "#4caf50" },
  { value: "home_retrofit", label: "Home Retrofit", color: "#8e24aa" },
  { value: "infrastructure_retrofit", label: "Infra Retrofit", color: "#607d8b" },
  { value: "dc_colocation", label: "DC Co-location", color: "#6c5ce7" },
];

function verdictColor(v) {
  if (v === "GO") return "#24a148";
  if (v === "CAUTION") return "#f1c21b";
  if (v === "NO-GO") return "#da1e28";
  return "#525252";
}

function verdictClass(v) {
  if (v === "GO") return "verdict-go";
  if (v === "CAUTION") return "verdict-caution";
  return "verdict-nogo";
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

  const hasWorkflow = Object.keys(workflowResults).length > 0;

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
        body: JSON.stringify({ intent, capacity_kw: samCapacity, day_of_year: samDay }),
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

  const executeAction = useCallback(async (action) => {
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
          setJobStatuses((prev) => ({ ...prev, [key]: `Job ${data.job_id}` }));
          pollJob(data.job_id, key);
        } else {
          setJobStatuses((prev) => ({ ...prev, [key]: "done" }));
        }
      } else {
        setJobStatuses((prev) => ({ ...prev, [key]: `${res.status} error` }));
      }
    } catch (err) {
      setJobStatuses((prev) => ({ ...prev, [key]: `error` }));
    }
  }, []);

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
              [key]: job.status === "done" ? `Done (${job.elapsed_s}s)` : `Failed`,
            }));
          }
        }
      } catch { clearInterval(interval); }
    }, 2000);
  }, []);

  return (
    <div className="agent-panel-inner">
      <div className="agent-body">

        {/* ── Workflow results view ── */}
        {hasWorkflow && (
          <div className="ap-workflow-section">
            <div className="ap-wf-tabs">
              {Object.entries(workflowResults).map(([wfIntent, result]) => {
                const meta = INTENTS.find(i => i.value === wfIntent);
                return (
                  <button
                    key={wfIntent}
                    className={`ap-wf-tab${activeResultTab === wfIntent ? " active" : ""}`}
                    onClick={() => showWorkflowResult(wfIntent)}
                  >
                    <span className="ap-wf-tab-dot" style={{ background: verdictColor(result.verdict) }} />
                    <span className="ap-wf-tab-label">{meta?.label || wfIntent}</span>
                    <span className={`ap-wf-tab-verdict ${verdictClass(result.verdict)}`}>{result.verdict}</span>
                  </button>
                );
              })}
              {workflowRunning && (
                <span className="ap-wf-tab running">
                  <span className="verdict-spinner" style={{ width: 10, height: 10 }} />
                </span>
              )}
            </div>

            {/* Workflow summary */}
            {workflowSummary && !workflowRunning && (
              <div className="ap-wf-summary">
                <div className="ap-wf-summary-header">
                  <span className={`verdict-badge sm ${verdictClass(workflowSummary.overall_verdict)}`}>
                    {workflowSummary.overall_verdict}
                  </span>
                  <span className="ap-wf-summary-meta">
                    {Math.round(workflowSummary.average_confidence * 100)}% avg | {workflowSummary.steps_completed} steps
                  </span>
                </div>
                <div className="ap-wf-summary-grid">
                  {workflowSummary.top_risks?.length > 0 && (
                    <div className="ap-wf-summary-col">
                      <span className="ap-wf-col-title risk">Top Risks</span>
                      <ul>
                        {workflowSummary.top_risks.slice(0, 4).map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    </div>
                  )}
                  {workflowSummary.top_opportunities?.length > 0 && (
                    <div className="ap-wf-summary-col">
                      <span className="ap-wf-col-title opp">Top Opportunities</span>
                      <ul>
                        {workflowSummary.top_opportunities.slice(0, 4).map((o, i) => <li key={i}>{o}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Single intent controls ── */}
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
            <button className="btn-agent" onClick={runAgent} disabled={agentLoading || !parcelId}>
              {agentLoading ? "Analysing..." : "Run Analysis"}
            </button>
            <button className="agent-dev-toggle" onClick={() => setShowDevConsole(p => !p)}>
              {showDevConsole ? "Hide JSON" : "Dev"}
            </button>
          </div>
        </div>

        {showDevConsole && agentResult && (
          <div className="agent-dev-console"><pre>{JSON.stringify(agentResult, null, 2)}</pre></div>
        )}

        {/* ── Result display ── */}
        {agentResult && (
          <>
            <div className="agent-result-header">
              <span className="agent-verdict" style={{ background: verdictColor(agentResult.verdict) }}>
                {agentResult.verdict}
              </span>
              <span className="agent-conf">{Math.round((agentResult.confidence || 0) * 100)}%</span>
              {agentResult.intent && <span className="agent-intent-tag">{agentResult.intent}</span>}
              {agentResult.elapsed_s && <span className="agent-elapsed">{agentResult.elapsed_s}s</span>}
            </div>

            <p className="agent-summary">{agentResult.summary}</p>

            <div className="agent-columns">
              {agentResult.risks?.length > 0 && (
                <div className="agent-col">
                  <div className="agent-col-title risk">Risks</div>
                  <ul>{agentResult.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                </div>
              )}
              {agentResult.opportunities?.length > 0 && (
                <div className="agent-col">
                  <div className="agent-col-title opp">Opportunities</div>
                  <ul>{agentResult.opportunities.map((o, i) => <li key={i}>{o}</li>)}</ul>
                </div>
              )}
              {agentResult.next_steps?.length > 0 && (
                <div className="agent-col">
                  <div className="agent-col-title steps">Next Steps</div>
                  <ol>{agentResult.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                </div>
              )}
            </div>

            {agentResult.recommended_capacity_kw != null && (
              <div className="agent-meta">
                Recommended: <strong>{agentResult.recommended_capacity_kw} kW</strong>
                {agentResult.estimated_roi_years != null && (
                  <> | ROI: <strong>{agentResult.estimated_roi_years}y</strong></>
                )}
              </div>
            )}

            {agentResult.actions?.length > 0 && (
              <div className="agent-actions">
                <div className="section-label">Actions</div>
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
                        <span className="agent-action-status">{jobStatuses[action.endpoint]}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {error && (
          <div className="agent-error">{error}</div>
        )}

        {!agentResult && !agentLoading && !error && !hasWorkflow && (
          <span className="muted">Select an intent and run analysis, or launch a workflow from the header</span>
        )}
      </div>
    </div>
  );
}
