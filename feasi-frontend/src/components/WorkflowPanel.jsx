import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const TEMPLATES = [
  { id: "pre_feasibility", label: "Pre-feasibility", phases: ["Site ID", "Desktop Review", "Constraints", "Scoring", "Report"] },
  { id: "full_feasibility", label: "Full Feasibility", phases: ["Site ID", "Grid Study", "Environmental", "Planning", "Financial", "Report"] },
  { id: "grid_application", label: "Grid Application", phases: ["Pre-app", "Design", "G99 Form", "DNO Submit", "Offer Review", "Accept"] },
  { id: "planning_application", label: "Planning Application", phases: ["EIA Screen", "Pre-app", "Submit", "Consultation", "Decision"] },
  { id: "construction", label: "Construction", phases: ["Procurement", "Mobilise", "Civil", "Electrical", "Commission", "Energise"] },
];

function StatusDot({ status }) {
  const colors = { complete: "#24a148", active: "#F5B731", pending: "#3a3d44", error: "#da1e28" };
  return <span className="wf-dot" style={{ background: colors[status] || colors.pending }} />;
}

export default function WorkflowPanel({ onClose, embedded }) {
  const { parcelId } = useSite();
  const [selectedTemplate, setSelectedTemplate] = useState("pre_feasibility");
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(false);

  const startWorkflow = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.workflows.run({
        template: selectedTemplate,
        site_id: parcelId,
      });
      const tpl = TEMPLATES.find(t => t.id === selectedTemplate);
      const newWf = {
        id: res?.workflow_id || `wf-${Date.now()}`,
        template: selectedTemplate,
        label: tpl?.label || selectedTemplate,
        phases: (tpl?.phases || []).map((p, i) => ({
          name: p,
          status: i === 0 ? "active" : "pending",
        })),
        status: "running",
        progress: 0,
        started: new Date().toISOString(),
      };
      setWorkflows(prev => [newWf, ...prev]);
    } catch (e) {
      console.warn("[Workflow] Start failed:", e);
    } finally {
      setLoading(false);
    }
  }, [selectedTemplate, parcelId]);

  const togglePause = useCallback((wfId) => {
    setWorkflows(prev => prev.map(w =>
      w.id === wfId ? { ...w, status: w.status === "running" ? "paused" : "running" } : w
    ));
  }, []);

  const cancelWorkflow = useCallback((wfId) => {
    setWorkflows(prev => prev.map(w =>
      w.id === wfId ? { ...w, status: "cancelled" } : w
    ));
  }, []);

  const tpl = TEMPLATES.find(t => t.id === selectedTemplate);

  return (
    <div className="wf-panel">
      {!embedded && (
        <div className="wf-header">
          <span className="wf-title">Workflow Engine</span>
          <button className="wf-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="wf-body">
        {/* Template selector */}
        <div className="wf-section">
          <label className="wf-label">Template</label>
          <select className="wf-select" value={selectedTemplate}
            onChange={e => setSelectedTemplate(e.target.value)}>
            {TEMPLATES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>

          {/* Phase preview */}
          {tpl && (
            <div className="wf-pipeline-preview">
              {tpl.phases.map((p, i) => (
                <React.Fragment key={i}>
                  <div className="wf-phase-node">
                    <StatusDot status="pending" />
                    <span className="wf-phase-name">{p}</span>
                  </div>
                  {i < tpl.phases.length - 1 && <div className="wf-phase-line" />}
                </React.Fragment>
              ))}
            </div>
          )}

          <button className="wf-btn-primary" onClick={startWorkflow} disabled={loading}>
            {loading ? "Starting..." : "Start Workflow"}
          </button>
        </div>

        {/* Active workflows */}
        {workflows.length > 0 && (
          <div className="wf-section">
            <div className="wf-section-title">Active Workflows</div>
            {workflows.map(wf => {
              const completedCount = wf.phases.filter(p => p.status === "complete").length;
              const pct = Math.round((completedCount / wf.phases.length) * 100);
              return (
                <div key={wf.id} className="wf-workflow-card">
                  <div className="wf-wf-top">
                    <span className="wf-wf-name">{wf.label}</span>
                    <span className={`wf-status-badge wf-status-${wf.status}`}>{wf.status}</span>
                  </div>

                  {/* Pipeline */}
                  <div className="wf-pipeline">
                    {wf.phases.map((p, i) => (
                      <React.Fragment key={i}>
                        <div className="wf-pip-node" title={p.name}>
                          <StatusDot status={p.status} />
                        </div>
                        {i < wf.phases.length - 1 && <div className="wf-pip-line" />}
                      </React.Fragment>
                    ))}
                  </div>

                  {/* Progress bar */}
                  <div className="wf-progress-bar">
                    <div className="wf-progress-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="wf-progress-text">{pct}% complete</div>

                  {/* Controls */}
                  <div className="wf-controls">
                    {wf.status !== "cancelled" && (
                      <button className="wf-btn-sm" onClick={() => togglePause(wf.id)}>
                        {wf.status === "paused" ? "Resume" : "Pause"}
                      </button>
                    )}
                    {wf.status !== "cancelled" && (
                      <button className="wf-btn-sm wf-btn-danger" onClick={() => cancelWorkflow(wf.id)}>
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {workflows.length === 0 && (
          <div className="wf-empty">No active workflows. Select a template and start.</div>
        )}
      </div>
    </div>
  );
}
