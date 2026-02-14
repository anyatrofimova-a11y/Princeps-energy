import React, { useState, useCallback } from "react";

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
  const [intent, setIntent] = useState("feasibility");
  const [showDevConsole, setShowDevConsole] = useState(false);
  const [jobStatuses, setJobStatuses] = useState({});
  const [error, setError] = useState(null);

  const runAgent = useCallback(async () => {
    if (!parcelId) return;
    setAgentLoading(true);
    setError(null);
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
          // If it returned a job_id, poll for it
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

          {error && (
            <div style={{ color: "var(--danger, #ff4757)", fontSize: 12, marginTop: 8, padding: "6px 10px", background: "rgba(255,71,87,0.08)", borderRadius: 6, border: "1px solid rgba(255,71,87,0.2)" }}>
              {error}
            </div>
          )}

          {!agentResult && !agentLoading && !error && (
            <span className="muted">
              Select an intent and click Run Agent to start analysis
            </span>
          )}
        </div>
    </div>
  );
}
