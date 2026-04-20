import React, { useMemo, useState } from "react";
import { WhenWorkload } from "../../lib/workload";
import DesignCanvas from "./DesignCanvas";

/**
 * DiscoverTab — map-first canvas for finding and screening candidate sites
 * for a project. Inverse of Assess (which is engineering deep-dive on one
 * chosen site). Modeled on Glint Solar's Buildable Area pattern: a candidate
 * sites table on the left, a live map on the right.
 */

const STUB_SITES = [
  { name: "Hartwell Field", area_ha: 24, resource_score: 78, headroom: "OK", planning_risk: "Low", composite: 82 },
  { name: "Greenfield North", area_ha: 18, resource_score: 71, headroom: "⚠ Q3'27", planning_risk: "Med", composite: 64 },
  { name: "Bramley Edge", area_ha: 31, resource_score: 75, headroom: "OK", planning_risk: "Low", composite: 79 },
];

function compositeColor(score) {
  if (score == null) return "var(--cds-text-helper)";
  if (score >= 75) return "var(--cds-support-success, #198038)";
  if (score >= 60) return "var(--cds-support-warning, #f1c21b)";
  return "var(--cds-support-error, #da1e28)";
}

function deriveRows(sitesProp, project) {
  // Prefer the explicit `sites` prop (real candidate data from the API).
  // Fall back to `project.sites`, then stubs. Keep the raw record so row
  // actions (e.g. Design) have access to lat/lon/candidate_id.
  const source = Array.isArray(sitesProp) && sitesProp.length > 0
    ? sitesProp
    : (Array.isArray(project?.sites) ? project.sites : null);
  if (source && source.length > 0) {
    return source.map((s, i) => ({
      raw: s,
      name: s.name || s.label || `Site ${i + 1}`,
      area_ha: s.scores?.area_ha ?? s.area_ha ?? s.area_hectares ?? "—",
      resource_score: s.scores?.resource ?? s.resource_score ?? "—",
      headroom: s.grid_headroom || s.headroom || (s.scores?.grid != null ? `${s.scores.grid}` : "—"),
      planning_risk: s.planning_risk || (s.scores?.planning != null ? `${s.scores.planning}` : "—"),
      composite: s.composite_score ?? s.score ?? (s.scores ?
        Math.round(Object.values(s.scores).filter((v) => typeof v === "number").reduce((a, b) => a + b, 0) /
          Math.max(1, Object.values(s.scores).filter((v) => typeof v === "number").length)) : null),
    }));
  }
  return STUB_SITES.map((s) => ({ ...s, raw: null }));
}

export default function DiscoverTab({ project, sites = null, mapSlot = null }) {
  const [region, setRegion] = useState(project?.region || "");
  const [minCapacity, setMinCapacity] = useState(project?.min_capacity_mw || "");
  const workload = project?.workload_type || project?.technology || "bess";
  const [scanning, setScanning] = useState(false);

  const rows = useMemo(() => deriveRows(sites, project), [sites, project]);
  const [designingSite, setDesigningSite] = useState(null);

  const onAddSite = () => {
    // Placeholder — real wiring will open the Add Site modal.
    console.log("[DiscoverTab] Add candidate site clicked", { project: project?.project_id });
  };

  const onScan = async () => {
    setScanning(true);
    console.log("[DiscoverTab] Run regional scan clicked", {
      project_id: project?.project_id,
      region,
      min_capacity_mw: minCapacity,
      workload,
    });
    // Stub — real call will be: await fetch('/api/prospector/scan', { ... })
    setTimeout(() => setScanning(false), 600);
  };

  return (
    <div className="dsc-tab">
      <header className="dsc-head">
        <div className="dsc-eyebrow">Site discovery</div>
        <h2 className="dsc-title">Discover</h2>
        <p className="dsc-lede">
          Find, screen, and compare candidate sites for this project.
        </p>
      </header>

      <section className="dsc-workspace">
        <div className="dsc-left">
          <div className="dsc-filters">
            <label className="dsc-field">
              <span className="dsc-field-label">Region</span>
              <input
                className="dsc-input"
                type="text"
                placeholder="e.g. East Midlands"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
              />
            </label>
            <label className="dsc-field">
              <span className="dsc-field-label">Min capacity (MW)</span>
              <input
                className="dsc-input"
                type="number"
                min="0"
                placeholder="50"
                value={minCapacity}
                onChange={(e) => setMinCapacity(e.target.value)}
              />
            </label>
            <label className="dsc-field">
              <span className="dsc-field-label">Workload</span>
              <input className="dsc-input dsc-input-readonly" type="text" value={workload} readOnly />
            </label>
          </div>

          <div className="dsc-table-head">
            <div className="dsc-table-title">Candidate sites</div>
            <button className="dsc-cta" onClick={onAddSite}>+ Add candidate site</button>
          </div>

          <div className="dsc-table-wrap">
            <table className="dsc-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="dsc-num">Area (ha)</th>
                  <th className="dsc-num">Resource</th>
                  <th>Grid headroom</th>
                  <th>Planning risk</th>
                  <th className="dsc-num">Composite</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="dsc-name">{r.name}</td>
                    <td className="dsc-num">{r.area_ha}</td>
                    <td className="dsc-num">{r.resource_score}</td>
                    <td>{r.headroom}</td>
                    <td>{r.planning_risk}</td>
                    <td className="dsc-num">
                      <span
                        className="dsc-composite"
                        style={{ background: compositeColor(r.composite) }}
                      >
                        {r.composite ?? "—"}
                      </span>
                    </td>
                    <td className="dsc-design-cell">
                      {r.raw && r.raw.lat != null && r.raw.lon != null ? (
                        <button
                          className="dsc-design-btn"
                          onClick={() => setDesigningSite(r.raw)}
                          title="Open design canvas"
                        >Design →</button>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={7} className="dsc-empty">No candidate sites yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="dsc-right">
          {mapSlot ? (
            <div className="dsc-map-live">{mapSlot}</div>
          ) : (
            <div className="dsc-map-placeholder">Map view — wired in next sprint</div>
          )}
        </div>
      </section>

      <section className="dsc-wl-section">
        <WhenWorkload project={project} only={["solar", "hybrid"]}>
          <div className="dsc-wl-card">
            <div className="dsc-wl-eyebrow">Solar overlay</div>
            <div className="dsc-wl-title">Solar resource map (irradiance overlay)</div>
            <div className="dsc-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="dc">
          <div className="dsc-wl-card">
            <div className="dsc-wl-eyebrow">Data centre overlay</div>
            <div className="dsc-wl-title">Cooling / water / fibre overlay (DC siting score)</div>
            <div className="dsc-wl-body">Uses <span className="dsc-wl-mono">/api/dc/site-suitability</span>.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="wind">
          <div className="dsc-wl-card">
            <div className="dsc-wl-eyebrow">Wind overlay</div>
            <div className="dsc-wl-title">Wind resource + wake modelling</div>
            <div className="dsc-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
      </section>

      <div className="dsc-scan-row">
        <button className="dsc-scan" onClick={onScan} disabled={scanning}>
          {scanning ? "Scanning…" : "Run regional scan"}
        </button>
        <span className="dsc-scan-hint">
          Sweeps the region for parcels matching your filters and ranks them by composite score.
        </span>
      </div>

      <DesignCanvas
        isOpen={!!designingSite}
        site={designingSite}
        project={project}
        onClose={() => setDesigningSite(null)}
      />

      <style>{`
        .dsc-design-cell { text-align: right; padding-right: 12px; }
        .dsc-design-btn {
          background: rgba(245,183,49,0.14);
          color: #E8A012;
          border: 1px solid transparent;
          padding: 4px 10px; border-radius: 6px;
          font-family: inherit; font-size: 11px; font-weight: 700;
          cursor: pointer;
          transition: all 120ms;
        }
        .dsc-design-btn:hover {
          background: #F5B731; color: #fff; border-color: #F5B731;
        }
        .dsc-tab { padding: 32px 40px; max-width: 1100px;
          font-family: "DM Sans", -apple-system, sans-serif; color: var(--cds-text-primary); }
        .dsc-head { margin-bottom: 28px; }
        .dsc-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .dsc-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .dsc-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }

        .dsc-workspace { display: grid; grid-template-columns: 40fr 60fr; gap: 20px;
          margin-bottom: 24px; }
        @media (max-width: 880px) { .dsc-workspace { grid-template-columns: 1fr; } }

        .dsc-left { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
        .dsc-filters { display: flex; gap: 12px; flex-wrap: wrap; padding-bottom: 14px;
          border-bottom: 1px solid var(--cds-border-subtle); }
        .dsc-field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 110px; }
        .dsc-field-label { font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); }
        .dsc-input { padding: 7px 10px; border: 1px solid var(--cds-border-subtle); border-radius: 6px;
          background: var(--cds-layer-01); font-family: inherit; font-size: 12px; color: var(--ink); }
        .dsc-input-readonly { background: var(--cds-layer-02); color: var(--cds-text-secondary); }

        .dsc-table-head { display: flex; align-items: center; justify-content: space-between; }
        .dsc-table-title { font-size: 13px; font-weight: 700; color: var(--ink); }
        .dsc-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 8px 14px; font-family: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
          letter-spacing: 0.2px; transition: background 120ms; }
        .dsc-cta:hover { background: var(--gold-dark); }

        .dsc-table-wrap { overflow-x: auto; }
        .dsc-table { width: 100%; border-collapse: collapse; font-size: 12px; }
        .dsc-table th { text-align: left; font-size: 10px; font-weight: 600; letter-spacing: 0.06em;
          text-transform: uppercase; color: var(--cds-text-helper); padding: 8px 8px;
          border-bottom: 1px solid var(--cds-border-subtle); }
        .dsc-table td { padding: 10px 8px; border-bottom: 1px solid var(--cds-border-subtle);
          color: var(--cds-text-secondary); }
        .dsc-table tr:last-child td { border-bottom: none; }
        .dsc-name { color: var(--ink); font-weight: 500; }
        .dsc-num { font-family: var(--mono); text-align: right; }
        .dsc-composite { display: inline-block; min-width: 32px; padding: 2px 8px; border-radius: 10px;
          color: #fff; font-family: var(--mono); font-size: 11px; font-weight: 700; text-align: center; }
        .dsc-empty { text-align: center; color: var(--cds-text-helper); padding: 18px 0;
          font-style: italic; }

        .dsc-right { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; overflow: hidden; min-height: 480px; position: relative; }
        .dsc-map-live { position: absolute; inset: 0; }
        .dsc-map-placeholder { min-height: 480px; background: #FAFAFA;
          border: 1px dashed #E5E7EB; display: flex; align-items: center; justify-content: center;
          color: var(--cds-text-helper); font-size: 13px; }

        .dsc-wl-section { display: flex; flex-direction: column; gap: 12px;
          margin-bottom: 20px; }
        .dsc-wl-card { background: var(--cds-layer-01); border: 1px dashed var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .dsc-wl-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 8px; }
        .dsc-wl-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
        .dsc-wl-body { font-size: 12px; color: var(--cds-text-secondary); line-height: 1.5; }
        .dsc-wl-mono { font-family: var(--mono); font-size: 11px; color: var(--cds-text-secondary); }

        .dsc-scan-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
          padding-top: 8px; }
        .dsc-scan { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 12px 22px; font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
          letter-spacing: 0.2px; transition: background 120ms; }
        .dsc-scan:hover:not(:disabled) { background: var(--gold-dark); }
        .dsc-scan:disabled { opacity: 0.4; cursor: not-allowed; }
        .dsc-scan-hint { font-size: 12px; color: var(--cds-text-helper); }
      `}</style>
    </div>
  );
}
