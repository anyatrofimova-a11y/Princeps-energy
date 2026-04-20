import React from "react";
import { STAGES, STAGE_INDEX } from "../lib/stage_workflow";

/**
 * StageRibbon — persistent, sticky stage indicator mounted under the hero
 * metric strip on every project page. Shows an 8-stage lifecycle pipeline
 * (Prospect → Screened → Grid applied → Grid offer → Planning → FID →
 * Construction → Energised) with the current stage highlighted and a
 * context-aware CTA tile on the right.
 *
 * Each stage carries a CTA that dispatches to the correct verb-tab inside
 * ProjectPage. CTA keys map to actions the backend already exposes (e.g.
 * Grid Offer → Generate G99 brief → POST /api/reports/g99-pack).
 *
 * Used on: ProjectPage root (sticky), Mission Control project row expander.
 *
 * Light-gold palette. No icon libraries — glyphs only.
 */

// Canonical 8-stage CTA map. Matches backend VALID_STAGES.
const CTA_BY_STAGE = {
  prospect: {
    eyebrow: "Next step",
    title: "Commission grid capacity study",
    detail: "Confirm nearest-substation headroom before design spend.",
    target: { tab: "assess", subTab: "grid" },
  },
  screened: {
    eyebrow: "Next step",
    title: "Submit DNO application (G99 / G100)",
    detail: "Lock queue position — lead times are 6–18 months.",
    target: { tab: "file", artefact: "g99" },
  },
  grid_applied: {
    eyebrow: "Chasing",
    title: "Chase DNO for grid offer",
    detail: "Follow up weekly and prep connection-agreement review in parallel.",
    target: { tab: "assess", subTab: "grid", chat: "Chase DNO for grid offer — summarise the latest correspondence and propose the next-step letter." },
  },
  grid_offer: {
    eyebrow: "Generate",
    title: "Generate G99 brief",
    detail: "Sign acceptance + generate the G99 pack. 30-day window — missing it forfeits the queue slot.",
    target: { tab: "file", artefact: "g99" },
  },
  planning: {
    eyebrow: "Submit",
    title: "Submit planning application",
    detail: "Validate screening opinion, ecology, noise, FRA before lodging.",
    target: { tab: "file", artefact: "planning-bundle" },
  },
  fid: {
    eyebrow: "Close",
    title: "Reach financial close",
    detail: "Finalise debt + equity, execute PPA, run sensitivity tornado.",
    target: { tab: "decide" },
  },
  construction: {
    eyebrow: "Track",
    title: "Track delivery milestones",
    detail: "Weekly progress cadence. Update commissioning date.",
    target: { tab: "operate" },
  },
  energised: {
    eyebrow: "Operate",
    title: "Monitor dispatch & revenue",
    detail: "Asset in service — optimise dispatch and ancillary stacking.",
    target: { tab: "operate" },
  },
};

function resolveCta(stage) {
  return CTA_BY_STAGE[stage] || CTA_BY_STAGE.prospect;
}

export default function StageRibbon({
  project = null,
  onTabChange = null,        // (tabKey) => void  — preferred API
  onNavigate = null,         // (route) => void   — compat with legacy ProjectPage
  onDispatchChat = null,     // (prompt) => void  — chat-driven CTAs
  onOpenArtefact = null,     // (artefactKey) => void  — File-tab deep link
  sticky = true,
}) {
  if (!project) return null;
  const stage = (project.stage || "prospect").toLowerCase();
  const stageIdx = STAGE_INDEX[stage] ?? 0;
  const cta = resolveCta(stage);

  const fireCta = () => {
    const t = cta.target || {};
    if (t.chat && onDispatchChat) onDispatchChat(t.chat);
    if (t.artefact && onOpenArtefact) {
      onOpenArtefact(t.artefact);
      if (onTabChange) onTabChange("file");
      return;
    }
    if (onTabChange && t.tab) onTabChange(t.tab);
    if (onNavigate) onNavigate({ tab: t.tab, subTab: t.subTab, chat: t.chat });
  };

  return (
    <div className={"srx-root" + (sticky ? " srx-sticky" : "")}>
      <ol className="srx-stages">
        {STAGES.map((s, i) => {
          const state = i < stageIdx ? "done" : i === stageIdx ? "active" : "future";
          return (
            <React.Fragment key={s.key}>
              <li className={"srx-stage srx-stage-" + state} title={s.label}>
                <span className="srx-dot" aria-hidden="true">
                  {i < stageIdx ? "\u2713" : i + 1}
                </span>
                <span className="srx-stage-lbl">{s.label}</span>
              </li>
              {i < STAGES.length - 1 && (
                <li aria-hidden="true" className={"srx-line" + (i < stageIdx ? " srx-line-done" : "")} />
              )}
            </React.Fragment>
          );
        })}
      </ol>

      <button type="button" className="srx-cta" onClick={fireCta}>
        <div className="srx-cta-body">
          <div className="srx-cta-eyebrow">{cta.eyebrow}</div>
          <div className="srx-cta-title">{cta.title}</div>
          <div className="srx-cta-detail">{cta.detail}</div>
        </div>
        <span className="srx-cta-arrow" aria-hidden="true">{"\u2192"}</span>
      </button>

      <style>{`
        .srx-root {
          display: grid;
          grid-template-columns: 1fr minmax(260px, 420px);
          gap: 20px; align-items: center;
          padding: 12px 24px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .srx-sticky {
          position: sticky; top: 0; z-index: 5;
        }
        .srx-stages {
          list-style: none; margin: 0; padding: 0;
          display: flex; align-items: center; gap: 2px;
          overflow-x: auto;
        }
        .srx-stage {
          display: flex; flex-direction: column; align-items: center; gap: 4px;
          min-width: 60px;
          padding: 0 2px;
        }
        .srx-dot {
          width: 22px; height: 22px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--mono); font-size: 10px; font-weight: 700;
          background: var(--cds-layer-03); color: var(--cds-text-helper);
          border: 2px solid var(--cds-border-subtle);
          transition: all 180ms ease;
        }
        .srx-stage-done .srx-dot {
          background: var(--cds-support-success);
          color: #fff;
          border-color: var(--cds-support-success);
        }
        .srx-stage-active .srx-dot {
          background: var(--gold);
          color: #fff;
          border-color: var(--gold);
          box-shadow: 0 0 0 4px rgba(var(--accent-rgb), 0.18);
        }
        .srx-stage-lbl {
          font-size: 9px; font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--cds-text-helper);
          white-space: nowrap;
        }
        .srx-stage-active .srx-stage-lbl { color: var(--ink); }
        .srx-stage-done .srx-stage-lbl { color: var(--cds-text-secondary); }
        .srx-line {
          flex: 1; min-width: 10px; max-width: 38px;
          height: 2px; margin-bottom: 18px;
          background: var(--cds-layer-03);
        }
        .srx-line-done { background: var(--cds-support-success); }

        .srx-cta {
          display: flex; align-items: center; gap: 14px;
          padding: 10px 14px;
          background: #FFFBF0;
          border: 1px solid var(--gold);
          border-radius: 8px;
          cursor: pointer;
          font: inherit;
          text-align: left;
          transition: background 120ms ease, transform 120ms ease, box-shadow 120ms ease;
        }
        .srx-cta:hover {
          background: rgba(var(--accent-rgb), 0.14);
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(var(--accent-rgb), 0.18);
        }
        .srx-cta:focus-visible {
          outline: 2px solid var(--gold-dark);
          outline-offset: 2px;
        }
        .srx-cta-body { flex: 1; min-width: 0; }
        .srx-cta-eyebrow {
          font-size: 9px; font-weight: 700;
          letter-spacing: 0.1em; text-transform: uppercase;
          color: var(--gold-dark);
        }
        .srx-cta-title {
          font-size: 13px; font-weight: 700;
          color: var(--ink); margin-top: 2px;
          line-height: 1.3;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .srx-cta-detail {
          font-size: 11px; color: var(--cds-text-secondary);
          margin-top: 3px; line-height: 1.4;
          overflow: hidden; text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 1; -webkit-box-orient: vertical;
        }
        .srx-cta-arrow {
          color: var(--gold-dark); font-size: 16px; font-weight: 700;
          flex-shrink: 0;
        }

        @media (max-width: 900px) {
          .srx-root {
            grid-template-columns: 1fr;
            padding: 12px 16px;
          }
          .srx-stages { padding-bottom: 4px; }
        }
      `}</style>
    </div>
  );
}
