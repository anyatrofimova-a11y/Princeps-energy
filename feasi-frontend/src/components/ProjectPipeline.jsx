import React, { useState, useMemo, useCallback } from "react";
import { useSite } from "../SiteContext";

/**
 * ProjectPipeline — Kanban-style view of all projects across connection stages.
 *
 * Developer mental model:
 *   PROSPECT → SCREENED → APPLIED → OFFER → PLANNING → FID → CONSTRUCTION → ENERGISED
 *
 * Each card shows: site name, MW, grid verdict, key blocker, days-in-stage.
 * Cards are draggable between stages (manual override).
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

// Demo projects — in production these come from the backend
const DEMO_PROJECTS = [
  { id: "p1", name: "Ashby Solar Farm", mw: 50, type: "solar", stage: "screened", verdict: "GO", daysInStage: 12, lat: 52.76, lon: -1.47, blocker: null },
  { id: "p2", name: "Uttoxeter BESS", mw: 100, type: "bess", stage: "grid_applied", verdict: "GO", daysInStage: 45, lat: 52.90, lon: -1.86, blocker: "Awaiting DNO response" },
  { id: "p3", name: "Solihull DC + Solar", mw: 30, type: "solar", stage: "prospect", verdict: null, daysInStage: 3, lat: 52.41, lon: -1.78, blocker: null },
  { id: "p4", name: "Hinkley Extension", mw: 200, type: "solar", stage: "grid_offer", verdict: "CAUTION", daysInStage: 22, lat: 51.21, lon: -3.13, blocker: "Offer over budget — £4.2M connection" },
  { id: "p5", name: "Norfolk Wind + BESS", mw: 75, type: "wind", stage: "planning", verdict: "GO", daysInStage: 90, lat: 52.63, lon: 1.30, blocker: "Awaiting EIA determination" },
  { id: "p6", name: "Pembroke Solar", mw: 40, type: "solar", stage: "fid", verdict: "GO", daysInStage: 8, lat: 51.68, lon: -4.94, blocker: null },
  { id: "p7", name: "Didcot BESS", mw: 150, type: "bess", stage: "construction", verdict: "GO", daysInStage: 120, lat: 51.62, lon: -1.24, blocker: null },
  { id: "p8", name: "Cambourne Solar", mw: 25, type: "solar", stage: "energised", verdict: "GO", daysInStage: 365, lat: 50.21, lon: -5.30, blocker: null },
  { id: "p9", name: "Spalding Solar", mw: 60, type: "solar", stage: "grid_applied", verdict: "GO", daysInStage: 78, lat: 52.79, lon: -0.15, blocker: "Queue position: 14th" },
  { id: "p10", name: "Teesside BESS", mw: 80, type: "bess", stage: "prospect", verdict: null, daysInStage: 1, lat: 54.57, lon: -1.23, blocker: null },
];

const TYPE_ICONS = {
  solar: "\u2600\uFE0F",
  bess: "\u26A1",
  wind: "\uD83C\uDF2C\uFE0F",
  dc: "\uD83C\uDFE2",
};

function StageColumn({ stage, projects, onProjectClick, onDrop, dragOverStage, onDragOver, onDragLeave }) {
  const totalMW = projects.reduce((s, p) => s + (p.mw || 0), 0);
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
          {totalMW > 0 && <span className="pp-column-mw">{totalMW} MW</span>}
        </div>
      </div>

      <div className="pp-column-body">
        {projects.map((project) => (
          <ProjectCard
            key={project.id}
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

  return (
    <div
      className="pp-card"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", project.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={onClick}
    >
      <div className="pp-card-top">
        <span className="pp-card-type">{TYPE_ICONS[project.type] || ""}</span>
        <span className="pp-card-name">{project.name}</span>
        {project.verdict && (
          <span className="pp-card-verdict" style={{ color: verdictColor, background: `${verdictColor}15` }}>
            {project.verdict}
          </span>
        )}
      </div>

      <div className="pp-card-metrics">
        <span className="pp-card-mw">{project.mw} MW</span>
        <span className="pp-card-days">{project.daysInStage}d</span>
      </div>

      {project.blocker && (
        <div className="pp-card-blocker">
          <span className="pp-card-blocker-icon">!</span>
          <span>{project.blocker}</span>
        </div>
      )}
    </div>
  );
}

function PipelineSummaryBar({ projects }) {
  const totalMW = projects.reduce((s, p) => s + (p.mw || 0), 0);
  const activeCount = projects.filter(p => p.stage !== "energised").length;
  const blocked = projects.filter(p => p.blocker).length;
  const goCount = projects.filter(p => p.verdict === "GO").length;

  return (
    <div className="pp-summary-bar">
      <div className="pp-summary-item">
        <span className="pp-summary-value">{projects.length}</span>
        <span className="pp-summary-label">Total Sites</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value">{totalMW.toLocaleString()}</span>
        <span className="pp-summary-label">Pipeline MW</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value">{activeCount}</span>
        <span className="pp-summary-label">In Progress</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value" style={{ color: "#16a34a" }}>{goCount}</span>
        <span className="pp-summary-label">GO Verdict</span>
      </div>
      <div className="pp-summary-item">
        <span className="pp-summary-value" style={{ color: blocked > 0 ? "#8B3A3A" : "#8A857D" }}>{blocked}</span>
        <span className="pp-summary-label">Blocked</span>
      </div>
    </div>
  );
}

export default function ProjectPipeline({ onClose, onSelectProject }) {
  const { setPickedLocation, loadSite } = useSite();
  const [projects, setProjects] = useState(DEMO_PROJECTS);
  const [selectedProject, setSelectedProject] = useState(null);
  const [viewMode, setViewMode] = useState("kanban"); // kanban | table | timeline
  const [filterType, setFilterType] = useState(null);
  const [dragOverStage, setDragOverStage] = useState(null);

  const filtered = filterType
    ? projects.filter(p => p.type === filterType)
    : projects;

  const projectsByStage = useMemo(() => {
    const map = {};
    for (const s of STAGES) map[s.id] = [];
    for (const p of filtered) {
      if (map[p.stage]) map[p.stage].push(p);
    }
    return map;
  }, [filtered]);

  const handleProjectClick = useCallback((project) => {
    setSelectedProject(project);
    onSelectProject?.(project);
    if (project.lat && project.lon) {
      setPickedLocation({ lat: project.lat, lon: project.lon });
    }
  }, [onSelectProject, setPickedLocation]);

  const handleDrop = useCallback((e, targetStage) => {
    e.preventDefault();
    const projectId = e.dataTransfer.getData("text/plain");
    setProjects(prev => prev.map(p =>
      p.id === projectId ? { ...p, stage: targetStage, daysInStage: 0 } : p
    ));
    setDragOverStage(null);
  }, []);

  return (
    <div className="pp-overlay">
      {/* Header */}
      <div className="pp-header">
        <div className="pp-header-left">
          <h2 className="pp-title">PROJECT PIPELINE</h2>
          <span className="pp-subtitle">{projects.length} sites across {STAGES.length} stages</span>
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
        </div>

        <button className="pp-close" onClick={onClose}>&times;</button>
      </div>

      {/* Summary bar */}
      <PipelineSummaryBar projects={filtered} />

      {/* Main content */}
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
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => {
                const stage = STAGES.find(s => s.id === p.stage);
                return (
                  <tr key={p.id} onClick={() => handleProjectClick(p)} className="pp-table-row">
                    <td className="pp-table-name">{p.name}</td>
                    <td>{TYPE_ICONS[p.type]} {p.type}</td>
                    <td className="pp-table-mw">{p.mw}</td>
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
                    <td className="pp-table-days">{p.daysInStage}d</td>
                    <td className="pp-table-blocker">{p.blocker || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {viewMode === "timeline" && (
        <div className="pp-timeline">
          {/* Horizontal timeline showing all projects positioned by stage */}
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
                  key={p.id}
                  className="pp-timeline-item"
                  style={{ left: `${(stageIdx / (STAGES.length - 1)) * 100}%` }}
                  onClick={() => handleProjectClick(p)}
                >
                  <div className="pp-timeline-dot" style={{ background: stage?.color }}>
                    {TYPE_ICONS[p.type]}
                  </div>
                  <div className="pp-timeline-label">
                    <span className="pp-timeline-name">{p.name}</span>
                    <span className="pp-timeline-mw">{p.mw} MW</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Selected project detail drawer */}
      {selectedProject && (
        <div className="pp-detail-drawer">
          <div className="pp-detail-header">
            <div>
              <div className="pp-detail-name">{selectedProject.name}</div>
              <div className="pp-detail-meta">
                {TYPE_ICONS[selectedProject.type]} {selectedProject.type} · {selectedProject.mw} MW ·
                {" "}{STAGES.find(s => s.id === selectedProject.stage)?.label}
              </div>
            </div>
            <button className="pp-detail-close" onClick={() => setSelectedProject(null)}>&times;</button>
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
          </div>
        </div>
      )}
    </div>
  );
}

export { STAGES };
