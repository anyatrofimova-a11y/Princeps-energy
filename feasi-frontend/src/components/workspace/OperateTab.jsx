import React from "react";

/**
 * OperateTab — live telemetry for an energised project.
 * Embeds the Grid Twin, live demand strip, and alerts feed.
 * Sprint-1 placeholder; full embed lands when project moves to "operate" stage.
 */
export default function OperateTab({ project, onPopOutTwin = () => {} }) {
  const energised = project?.stage === "energised" || project?.stage === "operating";

  return (
    <div className="op-tab">
      <header className="op-head">
        <div className="op-eyebrow">Operations</div>
        <h2 className="op-title">Operate</h2>
        <p className="op-lede">
          Live telemetry, performance alerts, and the grid twin for {project?.name || "this project"}.
        </p>
      </header>

      {!energised ? (
        <section className="op-empty">
          <div className="op-empty-icon">○</div>
          <div className="op-empty-title">Project not yet energised</div>
          <div className="op-empty-sub">
            Operate surfaces (live SCADA · twin · alerts · revenue dispatch) activate
            once the project reaches the "energised" stage. Until then, use the Grid
            Twin pop-out for the system-wide view.
          </div>
          <button className="op-cta" onClick={onPopOutTwin}>Pop out grid twin</button>
        </section>
      ) : (
        <section className="op-stub">
          <div className="op-card">
            <div className="op-card-label">Output now</div>
            <div className="op-card-value">— MW</div>
            <div className="op-card-note">Wire SCADA in Sprint 6</div>
          </div>
          <div className="op-card">
            <div className="op-card-label">Revenue today</div>
            <div className="op-card-value">£ —</div>
            <div className="op-card-note">Wire BMRS settlement in Sprint 6</div>
          </div>
          <div className="op-card">
            <div className="op-card-label">Alerts</div>
            <div className="op-card-value">0</div>
            <div className="op-card-note">No active alerts</div>
          </div>
        </section>
      )}

      <style>{`
        .op-tab { padding: 32px 40px; max-width: 960px; }
        .op-head { margin-bottom: 28px; }
        .op-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .op-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .op-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .op-empty { display: flex; flex-direction: column; align-items: center; justify-content: center;
          padding: 80px 24px; background: var(--cds-layer-01); border: 1px dashed var(--cds-border-subtle);
          border-radius: 12px; text-align: center; }
        .op-empty-icon { font-size: 48px; color: var(--cds-border-strong); }
        .op-empty-title { font-size: 18px; font-weight: 600; color: var(--cds-text-secondary); margin-top: 8px; }
        .op-empty-sub { font-size: 13px; color: var(--cds-text-helper); margin-top: 8px;
          max-width: 480px; line-height: 1.55; }
        .op-cta { margin-top: 20px; background: var(--gold); color: #fff; border: none;
          border-radius: 8px; padding: 10px 18px; font-family: inherit; font-size: 13px;
          font-weight: 600; cursor: pointer; }
        .op-cta:hover { background: var(--gold-dark); }
        .op-stub { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        .op-card { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .op-card-label { font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 10px; }
        .op-card-value { font-size: 28px; font-weight: 600; color: var(--ink); line-height: 1; }
        .op-card-note { font-size: 12px; color: var(--cds-text-helper); margin-top: 8px; }
      `}</style>
    </div>
  );
}
