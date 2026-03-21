import React, { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/**
 * ProjectPipeline — Kanban-style view of all projects across connection stages.
 *
 * Developer mental model:
 *   PROSPECT → SCREENED → APPLIED → OFFER → PLANNING → FID → CONSTRUCTION → ENERGISED
 *
 * Each card shows: site name, MW, grid verdict, key blocker, days-in-stage.
 * Cards are draggable between stages (persisted to backend).
 * Stage columns show aggregate MW and project count.
 */

const STAGES = [
  {
    id: "prospect",
    label: "Prospect",
    short: "PRSP",
    color: "#8A857D",
    description: "Land identified, not yet screened",
    actions: ["Run feasibility", "Check constraints"],
  },
  {
    id: "screened",
    label: "Screened",
    short: "SCRN",
    color: "#D4A018",
    description: "Feasibility complete, viable site",
    actions: ["Submit grid app", "Secure land option"],
  },
  {
    id: "grid_applied",
    label: "Grid Applied",
    short: "GAPP",
    color: "#0891b2",
    description: "Connection application submitted to DNO",
    actions: ["Track application", "Prepare planning"],
  },
  {
    id: "grid_offer",
    label: "Grid Offer",
    short: "GOFF",
    color: "#3b82f6",
    description: "Connection offer received, reviewing terms",
    actions: ["Accept offer", "Negotiate terms", "Reject & reapply"],
  },
  {
    id: "planning",
    label: "Planning",
    short: "PLAN",
    color: "#a855f7",
    description: "Planning application submitted to LPA",
    actions: ["Track planning", "Prepare EIA", "Community engagement"],
  },
  {
    id: "fid",
    label: "FID",
    short: "FID",
    color: "#16a34a",
    description: "Final investment decision — PPA & funding secured",
    actions: ["Execute PPA", "Appoint EPC", "Finalise BOM"],
  },
  {
    id: "construction",
    label: "Construction",
    short: "CNST",
    color: "#f59e0b",
    description: "EPC mobilised, building on site",
    actions: ["Track milestones", "Commission tests"],
  },
  {
    id: "energised",
    label: "Energised",
    short: "ENRG",
    color: "#22c55e",
    description: "Connected and generating",
    actions: ["Monitor output", "Dispatch optimise"],
  },
];

const TYPE_ICONS = {
  solar: "\u2600\uFE0F",
  bess: "\u26A1",
  wind: "\uD83C\uDF2C\uFE0F",
  dc: "\uD83C\uDFE2",
  hybrid: "\uD83D\uDD04",
};

function daysInStage(stageEnteredAt) {
  if (!stageEnteredAt) return 0;
  const entered = new Date(stageEnteredAt);
  const now = new Date();
  return Math.max(0, Math.floor((now - entered) / 86400000));
}

function StageColumn({ stage, projects, onProjectClick, onDrop, dragOverStage, onDragOver, onDragLeave }) {
  const totalMW = projects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
  const isOver = dragOverStage === stage.id;

  return (
    <div
      className={`pp-column ${isOver ? "pp-column-drag-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); onDragOver(stage.id); }}
      onDragLeave={onDragLeave}
      onDrop={(e) => onDrop(e, stage.id)}
    >
      <div className="pp-column-header" style={{ borderTopColor: stage.color }}>
        <div className="pp-column-title">
          <span className="pp-column-dot" style={{ background: stage.color }} />
          <span>{stage.label}</span>
        </div>
        <div className="pp-column-stats">
          <span className="pp-column-count">{projects.length}</span>
          {totalMW > 0 && <span className="pp-column-mw">{Math.round(totalMW)} MW</span>}
        </div>
      </div>

      <div className="pp-column-body">
        {projects.map((project) => (
          <ProjectCard
            key={project.project_id}
            project={project}
            stageColor={stage.color}
            onClick={() => onProjectClick(project)}
          />
        ))}
        {projects.length === 0 && (
          <div className="pp-empty">
            <span className="pp-empty-text">{stage.description}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectCard({ project, stageColor, onClick }) {
  const verdictColor = project.verdict === "GO" ? "#16a34a"
    : project.verdict === "CAUTION" ? "#D4A018"
    : project.verdict === "NO-GO" ? "#8B3A3A"
    : "#8A857D";
  const days = daysInStage(project.stage_entered_at);

  return (
    <div
      className="pp-card"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", project.project_id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={onClick}
    >
      <div className="pp-card-top">
        <span className="pp-card-type">{TYPE_ICONS[project.technology] || ""}</span>
        <span className="pp-card-name">{project.name}</span>
        {project.verdict && (
          <span className="pp-card-verdict" style={{ color: verdictColor, background: `${verdictColor}15` }}>
            {project.verdict}
          </span>
        )}
      </div>

      <div className="pp-card-metrics">
        <span className="pp-card-mw">{project.capacity_mw || "—"} MW</span>
        <span className="pp-card-days">{days}d</span>
      </div>

      {project.blocker && (
        <div className="pp-card-blocker">
          <span className="pp-card-blocker-icon">!</span>
          <span>{project.blocker}</span>
        </div>
      )}

      {project.repd_id && (
        <div className="pp-card-source">
          <span className="pp-card-source-badge">REPD</span>
        </div>
      )}
    </div>
  );
}

function PipelineSummaryBar({ summary }) {
  return (
    <div className="pp-summary-bar">
      <div className="pp-summary-item">
        <span className="pp-summary-value">{summary.total_projects}</span>
        <span className="pp-summary-label">Total Sites</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value">{Math.round(summary.total_mw).toLocaleString()}</span>
        <span className="pp-summary-label">Pipeline MW</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value">{summary.in_progress}</span>
        <span className="pp-summary-label">In Progress</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value" style={{ color: "#16a34a" }}>{summary.by_verdict?.GO || 0}</span>
        <span className="pp-summary-label">GO Verdict</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value" style={{ color: summary.blocked > 0 ? "#8B3A3A" : "#8A857D" }}>{summary.blocked}</span>
        <span className="pp-summary-label">Blocked</span>
      </div>
    </div>
  );
}

function CreateProjectModal({ onClose, onCreate }) {
  const [form, setForm] = useState({
    name: "", technology: "solar", capacity_mw: "", stage: "prospect",
    lat: "", lon: "", blocker: "", description: "",
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    const data = {
      name: form.name.trim(),
      technology: form.technology || null,
      capacity_mw: form.capacity_mw ? parseFloat(form.capacity_mw) : null,
      stage: form.stage,
      lat: form.lat ? parseFloat(form.lat) : null,
      lon: form.lon ? parseFloat(form.lon) : null,
      blocker: form.blocker || null,
      description: form.description || null,
    };
    const result = await api.projects.create(data);
    setSaving(false);
    if (result) {
      onCreate(result);
      onClose();
    }
  };

  return (
    <div className="pp-modal-overlay" onClick={onClose}>
      <form className="pp-modal" onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="pp-modal-header">
          <h3>New Project</h3>
          <button type="button" className="pp-detail-close" onClick={onClose}>&times;</button>
        </div>

        <div className="pp-modal-body">
          <label className="pp-form-label">
            Project Name *
            <input className="pp-form-input" value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} autoFocus />
          </label>

          <div className="pp-form-row">
            <label className="pp-form-label">
              Technology
              <select className="pp-form-input" value={form.technology} onChange={(e) => setForm(f => ({ ...f, technology: e.target.value }))}>
                <option value="solar">Solar</option>
                <option value="bess">BESS</option>
                <option value="wind">Wind</option>
                <option value="dc">Data Centre</option>
                <option value="hybrid">Hybrid</option>
              </select>
            </label>
            <label className="pp-form-label">
              Capacity (MW)
              <input className="pp-form-input" type="number" step="0.1" value={form.capacity_mw} onChange={(e) => setForm(f => ({ ...f, capacity_mw: e.target.value }))} />
            </label>
          </div>

          <div className="pp-form-row">
            <label className="pp-form-label">
              Latitude
              <input className="pp-form-input" type="number" step="0.0001" value={form.lat} onChange={(e) => setForm(f => ({ ...f, lat: e.target.value }))} />
            </label>
            <label className="pp-form-label">
              Longitude
              <input className="pp-form-input" type="number" step="0.0001" value={form.lon} onChange={(e) => setForm(f => ({ ...f, lon: e.target.value }))} />
            </label>
          </div>

          <label className="pp-form-label">
            Stage
            <select className="pp-form-input" value={form.stage} onChange={(e) => setForm(f => ({ ...f, stage: e.target.value }))}>
              {STAGES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>

          <label className="pp-form-label">
            Description
            <textarea className="pp-form-input pp-form-textarea" value={form.description} onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))} />
          </label>
        </div>

        <div className="pp-modal-footer">
          <button type="button" className="pp-btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="pp-btn-primary" disabled={!form.name.trim() || saving}>
            {saving ? "Creating..." : "Create Project"}
          </button>
        </div>
      </form>
    </div>
  );
}

// Phase 3 — Data source toggle options
const DATA_SOURCES = [
  { id: "my_projects", label: "My Projects" },
  { id: "repd", label: "REPD Market" },
  { id: "combined", label: "Combined" },
];

function DocumentsSection({ projectId }) {
  const [documents, setDocuments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    api.projects.listDocuments(projectId).then(d => { if (d) setDocuments(d); });
  }, [projectId]);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const result = await api.projects.uploadDocument(projectId, file);
    setUploading(false);
    if (result) setDocuments(prev => [result, ...prev]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDelete = async (docId) => {
    const result = await api.projects.deleteDocument(docId);
    if (result?.deleted) setDocuments(prev => prev.filter(d => d.doc_id !== docId));
  };

  const formatSize = (bytes) => {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  const DOC_TYPE_ICONS = {
    report: "\uD83D\uDCCA", grid_offer: "\u26A1", planning_app: "\uD83D\uDCC4",
    epc_contract: "\uD83D\uDCDD", ppa: "\uD83D\uDCB0", land_option: "\uD83C\uDFE0",
    environmental: "\uD83C\uDF3F", financial: "\uD83D\uDCB3", technical: "\u2699\uFE0F",
    correspondence: "\u2709\uFE0F", other: "\uD83D\uDCC1",
  };

  return (
    <div style={{ marginTop: 12 }}>
      <div className="pp-next-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>DOCUMENTS ({documents.length})</span>
        <label className="pp-btn-primary" style={{ fontSize: 10, padding: "3px 10px", cursor: "pointer" }}>
          {uploading ? "Uploading..." : "+ Upload"}
          <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={handleUpload} disabled={uploading} />
        </label>
      </div>
      {documents.length === 0 && (
        <div style={{ fontSize: 11, color: "#9CA3AF", padding: "8px 0" }}>No documents attached yet.</div>
      )}
      {documents.map(doc => (
        <div key={doc.doc_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid #f3f4f6", fontSize: 11 }}>
          <span>{DOC_TYPE_ICONS[doc.doc_type] || "\uD83D\uDCC1"}</span>
          <a
            href={api.projects.downloadDocument(doc.doc_id)}
            target="_blank"
            rel="noopener noreferrer"
            style={{ flex: 1, color: "var(--cds-interactive)", textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {doc.title || doc.filename}
          </a>
          <span style={{ color: "#9CA3AF", flexShrink: 0 }}>{formatSize(doc.size_bytes)}</span>
          <button
            onClick={(e) => { e.stopPropagation(); handleDelete(doc.doc_id); }}
            style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: 12, padding: "0 2px" }}
          >&times;</button>
        </div>
      ))}
    </div>
  );
}

export default function ProjectPipeline({ onClose, onSelectProject }) {
  const { setPickedLocation } = useSite();
  const [projects, setProjects] = useState([]);
  const [summary, setSummary] = useState({ total_projects: 0, total_mw: 0, in_progress: 0, blocked: 0, by_verdict: {} });
  const [loading, setLoading] = useState(true);
  const [selectedProject, setSelectedProject] = useState(null);
  const [viewMode, setViewMode] = useState("kanban");
  const [filterType, setFilterType] = useState(null);
  const [dragOverStage, setDragOverStage] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [timeline, setTimeline] = useState(null);
  const [dataSource, setDataSource] = useState("my_projects");
  const [repdData, setRepdData] = useState(null);
  const [repdLoading, setRepdLoading] = useState(false);
  const [importing, setImporting] = useState({});
  const loadedRef = useRef(false);

  // Load projects from backend
  const loadProjects = useCallback(async () => {
    const [listRes, sumRes] = await Promise.all([
      api.projects.list({ limit: 500 }),
      api.projects.summary(),
    ]);
    if (listRes?.projects) setProjects(listRes.projects);
    if (sumRes) setSummary(sumRes);
    setLoading(false);
  }, []);

  // Load REPD market data
  const loadRepd = useCallback(async () => {
    if (repdData) return; // already loaded
    setRepdLoading(true);
    const data = await api.tracker.repdSummary();
    setRepdData(data);
    setRepdLoading(false);
  }, [repdData]);

  useEffect(() => {
    if (!loadedRef.current) {
      loadedRef.current = true;
      loadProjects();
    }
  }, [loadProjects]);

  useEffect(() => {
    if (dataSource === "repd" || dataSource === "combined") loadRepd();
  }, [dataSource, loadRepd]);

  const handleImportRepd = useCallback(async (repdId) => {
    setImporting(prev => ({ ...prev, [repdId]: true }));
    const result = await api.projects.importRepd(repdId);
    setImporting(prev => ({ ...prev, [repdId]: false }));
    if (result) {
      setProjects(prev => [result, ...prev]);
      api.projects.summary().then(s => { if (s) setSummary(s); });
    }
  }, []);

  const filtered = filterType
    ? projects.filter(p => p.technology === filterType)
    : projects;

  const projectsByStage = useMemo(() => {
    const map = {};
    for (const s of STAGES) map[s.id] = [];
    for (const p of filtered) {
      if (map[p.stage]) map[p.stage].push(p);
    }
    return map;
  }, [filtered]);

  const handleProjectClick = useCallback(async (project) => {
    setSelectedProject(project);
    onSelectProject?.(project);
    if (project.lat && project.lon) {
      setPickedLocation({ lat: project.lat, lon: project.lon });
    }
    // Load timeline
    const tl = await api.projects.timeline(project.project_id);
    if (tl) setTimeline(tl);
  }, [onSelectProject, setPickedLocation]);

  const handleDrop = useCallback(async (e, targetStage) => {
    e.preventDefault();
    const projectId = e.dataTransfer.getData("text/plain");
    setDragOverStage(null);

    // Optimistic update
    setProjects(prev => prev.map(p =>
      p.project_id === projectId ? { ...p, stage: targetStage, stage_entered_at: new Date().toISOString() } : p
    ));

    // Persist to backend
    const result = await api.projects.update(projectId, { stage: targetStage });
    if (!result) {
      // Revert on failure
      loadProjects();
    } else {
      // Update summary
      const sumRes = await api.projects.summary();
      if (sumRes) setSummary(sumRes);
    }
  }, [loadProjects]);

  const handleCreate = useCallback((newProject) => {
    setProjects(prev => [newProject, ...prev]);
    // Refresh summary
    api.projects.summary().then(s => { if (s) setSummary(s); });
  }, []);

  const handleDelete = useCallback(async (projectId) => {
    const result = await api.projects.delete(projectId);
    if (result?.deleted) {
      setProjects(prev => prev.filter(p => p.project_id !== projectId));
      setSelectedProject(null);
      api.projects.summary().then(s => { if (s) setSummary(s); });
    }
  }, []);

  return (
    <div className="pp-overlay">
      {/* Header */}
      <div className="pp-header">
        <div className="pp-header-left">
          <h2 className="pp-title">PROJECT PIPELINE</h2>
          <span className="pp-subtitle">
            {loading ? "Loading..." : `${projects.length} sites across ${STAGES.length} stages`}
          </span>
        </div>

        <div className="pp-header-center">
          {/* View mode toggle */}
          <div className="pp-view-toggle">
            {[
              { id: "kanban", label: "Board" },
              { id: "table", label: "Table" },
              { id: "timeline", label: "Timeline" },
            ].map(v => (
              <button
                key={v.id}
                className={`pp-view-btn ${viewMode === v.id ? "active" : ""}`}
                onClick={() => setViewMode(v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>

          {/* Type filters */}
          <div className="pp-type-filters">
            <button
              className={`pp-type-filter ${filterType === null ? "active" : ""}`}
              onClick={() => setFilterType(null)}
            >All</button>
            {Object.entries(TYPE_ICONS).map(([type, icon]) => (
              <button
                key={type}
                className={`pp-type-filter ${filterType === type ? "active" : ""}`}
                onClick={() => setFilterType(filterType === type ? null : type)}
              >
                {icon} {type.charAt(0).toUpperCase() + type.slice(1)}
              </button>
            ))}
          </div>

          {/* Data source toggle */}
          <div className="pp-view-toggle">
            {DATA_SOURCES.map(ds => (
              <button
                key={ds.id}
                className={`pp-view-btn ${dataSource === ds.id ? "active" : ""}`}
                onClick={() => setDataSource(ds.id)}
              >
                {ds.label}
              </button>
            ))}
          </div>

          {/* Create button */}
          <button className="pp-btn-primary" onClick={() => setShowCreate(true)}>
            + New Project
          </button>
        </div>

        <button className="pp-close" onClick={onClose}>&times;</button>
      </div>

      {/* Summary bar */}
      <PipelineSummaryBar summary={summary} />

      {/* Main content */}
      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", flex: 1, color: "#8A857D" }}>
          Loading pipeline...
        </div>
      ) : dataSource === "repd" ? (
        /* REPD Market View */
        <div className="pp-table-wrap">
          {repdLoading ? (
            <div style={{ textAlign: "center", padding: 40, color: "#8A857D" }}>Loading REPD data...</div>
          ) : repdData ? (
            <>
              <div className="pp-summary-bar" style={{ borderBottom: "1px solid #f3f4f6", marginBottom: 0 }}>
                <div className="pp-summary-item">
                  <span className="pp-summary-value">{repdData.total_projects?.toLocaleString()}</span>
                  <span className="pp-summary-label">REPD Projects</span>
                </div>
                <div className="pp-summary-item">
                  <span className="pp-summary-value">{Math.round(repdData.total_mw || 0).toLocaleString()}</span>
                  <span className="pp-summary-label">Market MW</span>
                </div>
              </div>
              <table className="pp-table">
                <thead>
                  <tr>
                    <th>Technology</th>
                    <th>Projects</th>
                    <th>Total MW</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(repdData.by_technology || []).map(t => (
                    <tr key={t.technology || t.tech_category}>
                      <td>{TYPE_ICONS[t.technology || t.tech_category] || ""} {t.technology || t.tech_category}</td>
                      <td>{t.count?.toLocaleString()}</td>
                      <td>{Math.round(t.total_mw || 0).toLocaleString()} MW</td>
                      <td>
                        <button
                          className="pp-btn-secondary"
                          style={{ fontSize: 10, padding: "2px 8px" }}
                          onClick={() => {
                            setDataSource("my_projects");
                            setFilterType(t.technology || t.tech_category);
                          }}
                        >
                          View in pipeline
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ padding: "8px 12px", fontSize: 10, color: "#9CA3AF" }}>
                Source: BEIS REPD + ESO TEC Register. Import individual projects via search.
              </div>
            </>
          ) : null}
        </div>
      ) : (
        <>
          {viewMode === "kanban" && (
            <div className="pp-board">
              {STAGES.map(stage => (
                <StageColumn
                  key={stage.id}
                  stage={stage}
                  projects={projectsByStage[stage.id] || []}
                  onProjectClick={handleProjectClick}
                  onDrop={handleDrop}
                  dragOverStage={dragOverStage}
                  onDragOver={setDragOverStage}
                  onDragLeave={() => setDragOverStage(null)}
                />
              ))}
            </div>
          )}

          {viewMode === "table" && (
            <div className="pp-table-wrap">
              <table className="pp-table">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Type</th>
                    <th>MW</th>
                    <th>Stage</th>
                    <th>Verdict</th>
                    <th>Days</th>
                    <th>Blocker</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(p => {
                    const stage = STAGES.find(s => s.id === p.stage);
                    const days = daysInStage(p.stage_entered_at);
                    return (
                      <tr key={p.project_id} onClick={() => handleProjectClick(p)} className="pp-table-row">
                        <td className="pp-table-name">{p.name}</td>
                        <td>{TYPE_ICONS[p.technology]} {p.technology}</td>
                        <td className="pp-table-mw">{p.capacity_mw || "—"}</td>
                        <td>
                          <span className="pp-stage-badge" style={{ background: `${stage?.color}15`, color: stage?.color, borderColor: `${stage?.color}33` }}>
                            {stage?.label}
                          </span>
                        </td>
                        <td>
                          {p.verdict && (
                            <span className={`pp-verdict-badge pp-verdict-${p.verdict.toLowerCase().replace("-","")}`}>
                              {p.verdict}
                            </span>
                          )}
                        </td>
                        <td className="pp-table-days">{days}d</td>
                        <td className="pp-table-blocker">{p.blocker || "\u2014"}</td>
                        <td>
                          {p.repd_id ? <span className="pp-card-source-badge">REPD</span>
                            : p.tec_id ? <span className="pp-card-source-badge" style={{ background: "#d1fae5", color: "#059669" }}>TEC</span>
                            : "\u2014"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length === 0 && (
                <div style={{ textAlign: "center", padding: "40px", color: "#8A857D" }}>
                  No projects yet. Click <strong>+ New Project</strong> to create one.
                </div>
              )}
            </div>
          )}

          {viewMode === "timeline" && (
            <div className="pp-timeline">
              <div className="pp-timeline-header">
                {STAGES.map(stage => (
                  <div key={stage.id} className="pp-timeline-stage" style={{ borderBottomColor: stage.color }}>
                    <span style={{ color: stage.color }}>{stage.short}</span>
                  </div>
                ))}
              </div>
              <div className="pp-timeline-body">
                {filtered.map(p => {
                  const stageIdx = STAGES.findIndex(s => s.id === p.stage);
                  const stage = STAGES[stageIdx];
                  return (
                    <div
                      key={p.project_id}
                      className="pp-timeline-item"
                      style={{ left: `${(stageIdx / (STAGES.length - 1)) * 100}%` }}
                      onClick={() => handleProjectClick(p)}
                    >
                      <div className="pp-timeline-dot" style={{ background: stage?.color }}>
                        {TYPE_ICONS[p.technology]}
                      </div>
                      <div className="pp-timeline-label">
                        <span className="pp-timeline-name">{p.name}</span>
                        <span className="pp-timeline-mw">{p.capacity_mw || "—"} MW</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      {/* Selected project detail drawer */}
      {selectedProject && (
        <div className="pp-detail-drawer">
          <div className="pp-detail-header">
            <div>
              <div className="pp-detail-name">{selectedProject.name}</div>
              <div className="pp-detail-meta">
                {TYPE_ICONS[selectedProject.technology]} {selectedProject.technology} · {selectedProject.capacity_mw || "—"} MW ·
                {" "}{STAGES.find(s => s.id === selectedProject.stage)?.label}
                {selectedProject.repd_id && <span className="pp-card-source-badge" style={{ marginLeft: 8 }}>REPD</span>}
              </div>
              {selectedProject.description && (
                <div style={{ color: "#8A857D", fontSize: 12, marginTop: 4 }}>{selectedProject.description}</div>
              )}
            </div>
            <button className="pp-detail-close" onClick={() => { setSelectedProject(null); setTimeline(null); }}>&times;</button>
          </div>

          <div className="pp-detail-body">
            {/* Stage progression */}
            <div className="pp-stage-progress">
              {STAGES.map((stage, i) => {
                const currentIdx = STAGES.findIndex(s => s.id === selectedProject.stage);
                const isDone = i < currentIdx;
                const isCurrent = i === currentIdx;
                return (
                  <div key={stage.id} className={`pp-stage-step ${isDone ? "done" : ""} ${isCurrent ? "current" : ""}`}>
                    <div className="pp-stage-step-dot" style={{
                      background: isDone ? "#16a34a" : isCurrent ? stage.color : "#EBEDF0",
                      color: isDone || isCurrent ? "white" : "#8A857D",
                    }}>
                      {isDone ? "\u2713" : i + 1}
                    </div>
                    <span className="pp-stage-step-label" style={{ color: isCurrent ? stage.color : undefined }}>
                      {stage.short}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Blocker editor */}
            {selectedProject.blocker && (
              <div className="pp-card-blocker" style={{ margin: "8px 0" }}>
                <span className="pp-card-blocker-icon">!</span>
                <span>{selectedProject.blocker}</span>
              </div>
            )}

            {/* Timeline / audit trail */}
            {timeline?.transitions?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div className="pp-next-title">STAGE HISTORY</div>
                {timeline.transitions.map((t, i) => (
                  <div key={i} style={{ fontSize: 11, color: "#6B7280", padding: "3px 0", borderBottom: "1px solid #f3f4f6" }}>
                    {t.from_stage ? `${t.from_stage} → ` : ""}<strong>{t.to_stage}</strong>
                    {t.notes && <span style={{ marginLeft: 6 }}>{t.notes}</span>}
                    <span style={{ float: "right", color: "#9CA3AF" }}>
                      {new Date(t.created_at).toLocaleDateString()}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Documents */}
            <DocumentsSection projectId={selectedProject.project_id} />

            {/* Next actions */}
            <div className="pp-next-actions">
              <div className="pp-next-title">NEXT ACTIONS</div>
              {STAGES.find(s => s.id === selectedProject.stage)?.actions.map((action, i) => (
                <button key={i} className="pp-action-btn">{action}</button>
              ))}
            </div>

            {/* Quick navigate */}
            <button className="pp-goto-btn" onClick={() => {
              if (selectedProject.lat && selectedProject.lon) {
                setPickedLocation({ lat: selectedProject.lat, lon: selectedProject.lon });
              }
              onClose?.();
            }}>
              Open in Map &rarr;
            </button>

            {/* Delete */}
            <button
              className="pp-btn-secondary"
              style={{ marginTop: 8, color: "#ef4444", borderColor: "#fecaca", width: "100%" }}
              onClick={() => {
                if (confirm(`Delete "${selectedProject.name}"?`)) {
                  handleDelete(selectedProject.project_id);
                }
              }}
            >
              Delete Project
            </button>
          </div>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateProjectModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  );
}

export { STAGES };
