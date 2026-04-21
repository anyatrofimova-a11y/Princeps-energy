import React from "react";
import { STAGES, STAGE_INDEX, STAGE_CTA, CTA_ROUTE } from "../../lib/stage_workflow";

/**
 * StageRibbon — always-on status bar mounted under ProjectHeader on every
 * tab. Shows stage pipeline, grid status, planning %, next action CTA.
 *
 * Built.inc pattern: the screen always tells you what the project needs
 * from you next, not just what it is.
 */

const GRID_STATUS_STYLES = {
  headroom_ok: { bg: "rgba(22,163,74,0.12)",   fg: "var(--cds-support-success)", label: "Headroom OK" },
  queue_long:  { bg: "rgba(232,160,18,0.14)",  fg: "var(--cds-support-warning)", label: "In queue" },
  constrained: { bg: "rgba(220,38,38,0.12)",   fg: "var(--cds-support-error)",   label: "Constrained" },
  unknown:     { bg: "var(--cds-layer-03)",    fg: "var(--cds-text-helper)",     label: "Unverified" },
};

function fmtDue(days) {
  if (days == null) return "—";
  if (days <= 0) return "due now";
  if (days === 1) return "1 day";
  if (days < 14) return `${days} days`;
  return `${Math.round(days / 7)}w`;
}

function planningTint(pct) {
  if (pct == null) return "var(--cds-text-helper)";
  if (pct >= 70) return "var(--cds-support-success)";
  if (pct >= 50) return "var(--cds-support-warning)";
  return "var(--cds-support-error)";
}

export default function StageRibbon({
  project,
  gridStatus = null,         // "headroom_ok" | "queue_long" | "constrained" | "unknown"
  gridStatusLabel = null,    // optional override of default label
  planningPct = null,
  nextAction = null,         // optional override; else derived from stage
  onNavigate = () => {},     // (route: { tab, subTab?, chat? }) => void
  onDispatchChat = null,     // optional hook for "agent-*" CTAs
}) {
  if (!project) return null;
  const stage = project.stage || "prospect";
  const stageIdx = STAGE_INDEX[stage] ?? 0;
  const cta = nextAction || STAGE_CTA[stage];
  const gridCls = GRID_STATUS_STYLES[gridStatus || "unknown"];

  const fireCta = () => {
    if (!cta) return;
    const route = CTA_ROUTE[cta.action];
    if (!route) return;
    if (route.chat && onDispatchChat) onDispatchChat(route.chat);
    onNavigate(route);
  };

  return (
    <div className="sr-root">
      {/* Stage pipeline — 8 tight dots */}
      <div className="sr-pipeline">
        {STAGES.map((s, i) => {
          const state = i < stageIdx ? "done" : i === stageIdx ? "active" : "future";
          return (
            <React.Fragment key={s.key}>
              <div className={"sr-stage sr-stage-" + state} title={s.label}>
                <div className="sr-dot">{i < stageIdx ? "✓" : i + 1}</div>
                <div className="sr-lbl">{s.short}</div>
              </div>
              {i < STAGES.length - 1 && (
                <div className={"sr-line" + (i < stageIdx ? " sr-line-done" : "")} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Metric chips */}
      <div className="sr-chips">
        <div className="sr-chip" title="Nearest-substation headroom" style={{ background: gridCls.bg, color: gridCls.fg }}>
          <span className="sr-chip-lbl">Grid</span>
          <span className="sr-chip-val">{gridStatusLabel || gridCls.label}</span>
        </div>
        <div className="sr-chip" title="Planning approval probability">
          <span className="sr-chip-lbl">Planning</span>
          <span className="sr-chip-val" style={{ color: planningTint(planningPct) }}>
            {planningPct != null ? `${Math.round(planningPct)}%` : "—"}
          </span>
        </div>
      </div>

      {/* CTA card — "Your next step" */}
      {cta && (
        <div className="sr-cta" onClick={fireCta}>
          <div className="sr-cta-body">
            <div className="sr-cta-eyebrow">Your next step</div>
            <div className="sr-cta-title">{cta.title}</div>
            <div className="sr-cta-rat">{cta.rationale}</div>
          </div>
          <div className="sr-cta-meta">
            <span className="sr-cta-due">{fmtDue(cta.due_days)}</span>
            <span className="sr-cta-arr">→</span>
          </div>
        </div>
      )}

      <style>{`
        .sr-root {
          display: grid; grid-template-columns: auto auto 1fr; gap: 14px;
          align-items: center; padding: 6px 20px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .sr-pipeline {
          display: flex; align-items: center; gap: 2px;
        }
        .sr-stage {
          display: flex; flex-direction: column; align-items: center; gap: 2px;
          min-width: 32px;
        }
        .sr-dot {
          width: 18px; height: 18px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--mono); font-size: 9px; font-weight: 700;
          background: var(--cds-layer-03); color: var(--cds-text-helper);
          border: 2px solid var(--cds-border-subtle);
        }
        .sr-stage-done .sr-dot { background: var(--cds-support-success); color: #fff; border-color: var(--cds-support-success); }
        .sr-stage-active .sr-dot { background: var(--gold); color: #fff; border-color: var(--gold); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.2); }
        .sr-lbl {
          font-size: 8px; font-family: var(--mono); font-weight: 700;
          letter-spacing: 0.04em; color: var(--cds-text-helper);
        }
        .sr-stage-active .sr-lbl { color: var(--ink); }
        .sr-stage-done .sr-lbl { color: var(--cds-text-secondary); }
        .sr-line {
          height: 2px; width: 14px; background: var(--cds-layer-03); margin-top: -10px;
        }
        .sr-line-done { background: var(--cds-support-success); }

        .sr-chips { display: flex; gap: 8px; }
        .sr-chip {
          display: flex; flex-direction: column; gap: 1px;
          padding: 6px 10px; border-radius: 6px;
          background: var(--cds-layer-02);
        }
        .sr-chip-lbl {
          font-size: 8px; font-weight: 700; letter-spacing: 0.06em;
          text-transform: uppercase; color: var(--cds-text-helper);
        }
        .sr-chip-val {
          font-family: var(--mono); font-size: 12px; font-weight: 700;
          color: var(--ink);
        }

        .sr-cta {
          display: flex; align-items: center; gap: 14px;
          padding: 8px 14px; justify-self: end;
          background: rgba(var(--accent-rgb), 0.08);
          border: 1px solid var(--gold);
          border-radius: 8px;
          cursor: pointer;
          transition: all 120ms;
          max-width: 520px;
        }
        .sr-cta:hover { background: rgba(var(--accent-rgb), 0.14); transform: translateY(-1px); }
        .sr-cta-body { min-width: 0; }
        .sr-cta-eyebrow {
          font-size: 9px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--gold-dark); margin-bottom: 2px;
        }
        .sr-cta-title { font-size: 13px; font-weight: 700; color: var(--ink); line-height: 1.3; }
        .sr-cta-rat {
          font-size: 11px; color: var(--cds-text-secondary);
          margin-top: 2px; line-height: 1.4;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          max-width: 380px;
        }
        .sr-cta-meta { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
        .sr-cta-due {
          font-family: var(--mono); font-size: 11px; font-weight: 700;
          color: var(--gold-dark);
          padding: 2px 8px; background: #fff;
          border-radius: 4px;
        }
        .sr-cta-arr { color: var(--gold-dark); font-size: 16px; font-weight: 700; }
      `}</style>
    </div>
  );
}
