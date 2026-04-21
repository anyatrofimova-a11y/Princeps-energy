import React from "react";
import ActionsMenu from "./ActionsMenu";
import { WorkloadBadge } from "../../lib/workload.jsx";

/**
 * ProjectHeader — slim project hero block.
 *
 * Restructure 2026-04-19 (BOT-TT): killed the right vertical KPI column.
 * Numeric KPIs now live solely in HeroMetricStrip (IT LOAD · PUE · GRID
 * HEADROOM · IRR · PLANNING · LCOE · NPV). Stage already lives in the
 * StageRibbon + breadcrumb so we don't restate it as a metric here. The
 * verdict drives the colour/state of the warning banner that already sits
 * in this hero, so we don't show the word twice.
 *
 * What stays: title · workload badge · coordinates · stage pill (textual
 * context, not a metric tile) · verdict-tinted blocker banner.
 */

const STAGE_LABEL = {
  prospect: "Prospect", screened: "Screened", grid_applied: "Grid applied",
  grid_offer: "Grid offer", planning: "Planning", fid: "FID",
  construction: "Construction", energised: "Energised",
};

// Verdict drives the blocker banner colour so the warning IS the verdict.
const VERDICT_BANNER_STYLE = {
  "GO":      { bg: "rgba(22,163,74,0.10)",  fg: "var(--cds-support-success)", border: "rgba(22,163,74,0.40)",  glyph: "\u2713" },
  "CAUTION": { bg: "rgba(232,160,18,0.12)", fg: "var(--cds-support-warning)", border: "rgba(232,160,18,0.45)", glyph: "\u26A0" },
  "NO-GO":   { bg: "rgba(220,38,38,0.10)",  fg: "var(--cds-support-error)",   border: "rgba(220,38,38,0.45)",  glyph: "\u2716" },
};

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
  const coord = project.lat != null && project.lon != null
    ? `${project.lat.toFixed(4)}°, ${project.lon.toFixed(4)}°`
    : null;

  const verdict = project.verdict || null;
  const verdictStyle = VERDICT_BANNER_STYLE[verdict] || null;
  const stageLabel = project.stage ? (STAGE_LABEL[project.stage] || project.stage) : null;
  const blocker = project.blocker || null;

  // Banner appears whenever there's a blocker OR an explicit verdict.
  // Banner text = blocker if present, else a short verdict statement.
  const bannerText = blocker
    || (verdict === "GO"      ? "All gating checks passing — proceed"
      : verdict === "CAUTION" ? "Open risks — review before progressing"
      : verdict === "NO-GO"   ? "Hard blocker — do not progress"
      : null);

  return (
    <header className="ph-root">
      <div className="ph-hero">
        <div className="ph-title-row">
          <h1 className="ph-title">{project.name}</h1>
          {project.workload_type && <WorkloadBadge workloadType={project.workload_type} />}
        </div>
        <div className="ph-sub">
          {coord && <span className="ph-coord">{coord}</span>}
          {stageLabel && (
            <span className="ph-stage-badge" title="Lifecycle stage">
              {stageLabel}
            </span>
          )}
          {verdict && (
            <span
              className="ph-verdict-pill"
              style={verdictStyle ? { background: verdictStyle.bg, color: verdictStyle.fg, borderColor: verdictStyle.border } : undefined}
              title="Agent verdict"
            >
              {verdict}
            </span>
          )}
        </div>

        {bannerText && verdictStyle && (
          <div
            className="ph-banner"
            style={{
              background: verdictStyle.bg,
              borderColor: verdictStyle.border,
              color: verdictStyle.fg,
            }}
            title={bannerText}
          >
            <span className="ph-banner-glyph" aria-hidden="true">{verdictStyle.glyph}</span>
            <span className="ph-banner-text">{bannerText}</span>
          </div>
        )}
      </div>

      {actions && (
        <div className="ph-actions">
          <ActionsMenu actions={actions} />
        </div>
      )}

      <style>{`
        .ph-root {
          display: flex; align-items: center; justify-content: space-between;
          gap: 14px;
          min-height: 56px;
          padding: 8px 20px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .ph-hero {
          flex: 1; min-width: 0;
          display: flex; flex-direction: row; align-items: center; gap: 10px;
          flex-wrap: wrap;
        }
        .ph-title-row { display: flex; align-items: center; gap: 8px; }
        .ph-title {
          margin: 0; padding: 0;
          font-size: 16px; font-weight: 700;
          color: var(--ink);
          line-height: 1.25;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          max-width: 100%;
        }
        .ph-sub {
          display: flex; align-items: center; gap: 8px;
          flex-wrap: wrap;
          font-size: 11px;
          color: var(--cds-text-helper);
        }
        .ph-coord { font-family: var(--mono); font-size: 10px; }
        .ph-stage-badge {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 2px 8px; border-radius: 4px;
          font-size: 10px; font-family: var(--mono);
          font-weight: 700; letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .ph-verdict-pill {
          padding: 2px 10px;
          border-radius: 999px;
          border: 1px solid transparent;
          font-size: 10px; font-family: var(--mono);
          font-weight: 700; letter-spacing: 0.06em;
          text-transform: uppercase;
        }
        .ph-banner {
          display: inline-flex; align-items: center; gap: 8px;
          padding: 6px 12px;
          border: 1px solid;
          border-radius: 6px;
          font-size: 12px; line-height: 1.35;
          max-width: 100%;
          align-self: flex-start;
        }
        .ph-banner-glyph {
          font-size: 12px; line-height: 1;
          flex-shrink: 0;
        }
        .ph-banner-text {
          overflow: hidden; text-overflow: ellipsis;
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        }
        .ph-actions {
          padding-left: 16px;
          border-left: 1px solid var(--cds-border-subtle);
          flex-shrink: 0;
          align-self: stretch;
          display: flex; align-items: center;
        }
      `}</style>
    </header>
  );
}
