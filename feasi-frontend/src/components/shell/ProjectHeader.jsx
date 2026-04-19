import React from "react";
import ActionsMenu from "./ActionsMenu";
import { WorkloadBadge } from "../../lib/workload.jsx";

const STAGE_LABEL = {
  prospect: "Prospect", screened: "Screened", grid_applied: "Grid applied",
  grid_offer: "Grid offer", planning: "Planning", fid: "FID",
  construction: "Construction", energised: "Energised",
};

const VERDICT_STYLE = {
  "GO": { bg: "rgba(22,163,74,0.12)", fg: "var(--cds-support-success)" },
  "CAUTION": { bg: "rgba(232,160,18,0.14)", fg: "var(--cds-support-warning)" },
  "NO-GO": { bg: "rgba(220,38,38,0.12)", fg: "var(--cds-support-error)" },
};

function Pill({ verdict }) {
  const s = VERDICT_STYLE[verdict] || { bg: "var(--cds-layer-03)", fg: "var(--cds-text-secondary)" };
  return (
    <span
      className="ph-pill"
      style={{ background: s.bg, color: s.fg }}
    >
      {verdict || "—"}
    </span>
  );
}

function Metric({ label, value, unit, valueColor, valueNode }) {
  return (
    <div className="ph-metric">
      <div className="ph-metric-label">{label}</div>
      <div className="ph-metric-value" style={valueColor ? { color: valueColor } : undefined}>
        {valueNode ?? (
          <>
            <span className="ph-metric-num">{value ?? "—"}</span>
            {unit && <span className="ph-metric-unit">{unit}</span>}
          </>
        )}
      </div>
    </div>
  );
}

export default function ProjectHeader({
  project = {
    name: "Project",
    technology: "bess",
    capacity_mw: null,
    stage: null,
    verdict: null,
    lat: null, lon: null,
    metadata: {},
    sites_count: 0,
  },
  actions = null,
}) {
  const tech = project.technology;
  const meta = project.metadata || {};
  const coord = project.lat != null && project.lon != null
    ? `${project.lat.toFixed(4)}°, ${project.lon.toFixed(4)}°`
    : null;

  const metrics = (() => {
    if (tech === "bess") {
      return [
        { label: "Capacity", value: project.capacity_mw, unit: "MW" },
        { label: "Energy", value: meta.energy_mwh, unit: "MWh" },
        { label: "Verdict", valueNode: <Pill verdict={project.verdict} /> },
        { label: "Stage", value: STAGE_LABEL[project.stage] || project.stage || "—" },
        { label: "Sites", value: project.sites_count ?? 0 },
      ];
    }
    if (tech === "dc") {
      return [
        { label: "IT Load", value: meta.it_load_mw ?? project.capacity_mw, unit: "MW" },
        { label: "PUE Target", value: meta.pue_target },
        { label: "Grid Headroom", value: meta.grid_headroom_mw, unit: "MW" },
        { label: "Verdict", valueNode: <Pill verdict={project.verdict} /> },
        { label: "Stage", value: STAGE_LABEL[project.stage] || project.stage || "—" },
      ];
    }
    return [
      { label: "Capacity", value: project.capacity_mw, unit: "MW" },
      { label: "Verdict", valueNode: <Pill verdict={project.verdict} /> },
      { label: "Stage", value: STAGE_LABEL[project.stage] || project.stage || "—" },
      { label: "Sites", value: project.sites_count ?? 0 },
    ];
  })();

  return (
    <header className="ph-root">
      <div className="ph-left">
        <div className="ph-title-row">
          <h1 className="ph-title">{project.name}</h1>
          {project.workload_type && <WorkloadBadge workloadType={project.workload_type} />}
        </div>
        <div className="ph-sub">
          {coord && <span className="ph-coord">{coord}</span>}
          {project.stage && (
            <span className="ph-stage-badge">
              {STAGE_LABEL[project.stage] || project.stage}
            </span>
          )}
          {project.blocker && (
            <span className="ph-blocker" title={project.blocker}>
              ⚠ {project.blocker.slice(0, 60)}{project.blocker.length > 60 ? "…" : ""}
            </span>
          )}
        </div>
      </div>
      <div className="ph-metrics">
        {metrics.map((m, i) => <Metric key={i} {...m} />)}
      </div>
      {actions && (
        <div className="ph-actions">
          <ActionsMenu actions={actions} />
        </div>
      )}
      <style>{`
        .ph-root {
          display: flex; align-items: center; justify-content: space-between;
          gap: 24px;
          min-height: 92px;
          padding: 16px 24px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .ph-left { flex-shrink: 0; min-width: 0; }
        .ph-title-row { display: flex; align-items: center; gap: 10px; }
        .ph-title {
          margin: 0; padding: 0;
          font-size: 22px; font-weight: 700;
          color: var(--ink);
          line-height: 1.2;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          max-width: 420px;
        }
        .ph-sub {
          display: flex; align-items: center; gap: 10px;
          margin-top: 6px;
          font-size: 12px;
          color: var(--cds-text-helper);
        }
        .ph-coord { font-family: var(--mono); font-size: 11px; }
        .ph-stage-badge {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 2px 8px; border-radius: 4px;
          font-size: 10px; font-family: var(--mono);
          font-weight: 700; letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .ph-blocker {
          color: var(--cds-support-warning);
          font-size: 11px;
          max-width: 340px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .ph-metrics {
          display: flex; gap: 0;
          flex-shrink: 0;
        }
        .ph-metric {
          padding: 8px 20px;
          border-left: 1px solid var(--cds-border-subtle);
          min-width: 120px;
        }
        .ph-metric:first-child { border-left: none; }
        .ph-metric-label {
          font-size: 10px;
          color: var(--cds-text-helper);
          font-weight: 600;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }
        .ph-metric-value {
          display: flex; align-items: baseline; gap: 4px;
          color: var(--ink);
        }
        .ph-metric-num {
          font-family: var(--mono);
          font-size: 22px; font-weight: 700;
          line-height: 1;
        }
        .ph-metric-unit {
          font-family: var(--mono);
          font-size: 12px; font-weight: 500;
          color: var(--cds-text-helper);
        }
        .ph-pill {
          display: inline-flex; align-items: center;
          padding: 3px 10px;
          border-radius: 6px;
          font-size: 12px; font-weight: 700;
          letter-spacing: 0.04em;
          font-family: var(--mono);
        }
        .ph-actions {
          margin-left: 12px;
          padding-left: 20px;
          border-left: 1px solid var(--cds-border-subtle);
          flex-shrink: 0;
        }
      `}</style>
    </header>
  );
}
