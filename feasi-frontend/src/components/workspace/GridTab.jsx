import React, { useState, lazy, Suspense } from "react";

const GridTwinCesium = lazy(() => import("../GridTwinCesium"));
const ProjectTwinEmbed = lazy(() => import("../assess/ProjectTwinEmbed"));

const PATHWAYS = [
  { key: "CT", label: "Consumer Transformation" },
  { key: "ST", label: "System Transformation" },
  { key: "LTW", label: "Leading the Way" },
  { key: "FS", label: "Falling Short" },
];

const VERDICT_STYLE = {
  "GO": { bg: "rgba(22,163,74,0.12)", fg: "var(--cds-support-success)" },
  "CAUTION": { bg: "rgba(232,160,18,0.14)", fg: "var(--cds-support-warning)" },
  "NO-GO": { bg: "rgba(220,38,38,0.12)", fg: "var(--cds-support-error)" },
};

export default function GridTab({
  project,
  substation = { name: "Slough 132kV", voltage_kv: 132, distance_km: 2.3, headroom_mw: 18 },
  costP10 = 2.1, costP50 = 3.4, costP90 = 5.8,
  verdict = "CAUTION",
  verdictReason = "Thermal constraint at summer peak; requires reinforcement by 2029.",
  onPopOut = () => {},
  embedTwin = false,
}) {
  const [pathway, setPathway] = useState("CT");
  const [year, setYear] = useState(2030);
  const vStyle = VERDICT_STYLE[verdict] || VERDICT_STYLE.CAUTION;

  return (
    <div className="gt-root">
      <div className="gt-main">
        <div className="gt-twin-zone">
          <div className="gt-twin-label">
            Newton–Raphson · 60 Hz · N-1 ready
          </div>
          {embedTwin ? (
            <Suspense fallback={<div className="gt-placeholder-text">Loading grid twin…</div>}>
              <GridTwinCesium embedded project={project} />
            </Suspense>
          ) : (
            <Suspense fallback={<div className="gt-placeholder"><div className="gt-placeholder-text">Loading project twin…</div></div>}>
              <ProjectTwinEmbed project={project} />
            </Suspense>
          )}
        </div>

        <aside className="gt-aside">
          <div className="gt-card">
            <div className="gt-card-title">Nearest substation</div>
            <div className="gt-sub-name">{substation.name}</div>
            <div className="gt-sub-row">
              <span className="gt-sub-label">Voltage</span>
              <span className="gt-sub-val">{substation.voltage_kv} kV</span>
            </div>
            <div className="gt-sub-row">
              <span className="gt-sub-label">Distance</span>
              <span className="gt-sub-val">{substation.distance_km} km</span>
            </div>
            <div className="gt-sub-row gt-sub-row-hl">
              <span className="gt-sub-label">Headroom</span>
              <span className="gt-sub-val">{substation.headroom_mw} MW</span>
            </div>
          </div>

          <div className="gt-card">
            <div className="gt-card-title">Connection cost estimate</div>
            <div className="gt-cost-row">
              <span className="gt-cost-band">P10</span>
              <span className="gt-cost-val">£{costP10.toFixed(1)}M</span>
            </div>
            <div className="gt-cost-row gt-cost-row-hl">
              <span className="gt-cost-band">P50</span>
              <span className="gt-cost-val">£{costP50.toFixed(1)}M</span>
            </div>
            <div className="gt-cost-row">
              <span className="gt-cost-band">P90</span>
              <span className="gt-cost-val">£{costP90.toFixed(1)}M</span>
            </div>
            <div className="gt-cost-note">UK rates · 132 kV · cable-based estimate</div>
          </div>

          <div className="gt-card">
            <div className="gt-card-title">Verdict</div>
            <div className="gt-verdict-pill" style={{ background: vStyle.bg, color: vStyle.fg }}>
              {verdict}
            </div>
            <div className="gt-verdict-reason">{verdictReason}</div>
          </div>
        </aside>
      </div>

      <div className="gt-scenarios">
        <div className="gt-scen-label">NESO FES pathway</div>
        <div className="gt-scen-buttons">
          {PATHWAYS.map((p) => (
            <button
              key={p.key}
              className={"gt-scen-btn" + (p.key === pathway ? " gt-scen-active" : "")}
              onClick={() => setPathway(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="gt-year">
          <input
            type="range"
            min="2024" max="2050" step="1"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
          />
          <span className="gt-year-val">{year}</span>
        </div>
      </div>

      <style>{`
        .gt-root {
          padding: 20px 24px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: var(--cds-text-primary);
          display: flex; flex-direction: column; gap: 16px;
        }
        .gt-main {
          display: flex; gap: 16px;
          min-height: 520px;
        }
        .gt-twin-zone {
          flex: 7;
          position: relative;
          background: linear-gradient(135deg, #1A1D23 0%, #0F1318 100%);
          border-radius: 12px;
          overflow: hidden;
          min-height: 520px;
        }
        .gt-twin-label {
          position: absolute; top: 12px; left: 16px;
          font-family: var(--mono);
          font-size: 10px;
          color: rgba(255,255,255,0.5);
          letter-spacing: 0.05em;
          z-index: 2;
        }
        .gt-popout {
          position: absolute; top: 10px; right: 12px;
          background: rgba(255,255,255,0.08);
          color: rgba(255,255,255,0.85);
          border: 1px solid rgba(255,255,255,0.15);
          border-radius: 6px;
          padding: 6px 12px;
          font-size: 11px; font-weight: 600;
          font-family: inherit;
          cursor: pointer;
          z-index: 2;
          transition: all 120ms;
        }
        .gt-popout:hover {
          background: var(--gold);
          border-color: var(--gold);
          color: var(--ink);
        }
        .gt-placeholder {
          position: absolute; inset: 0;
          display: flex; align-items: center; justify-content: center;
        }
        .gt-placeholder-text {
          text-align: center;
          color: rgba(255,255,255,0.7);
          font-size: 14px; font-weight: 600;
        }
        .gt-placeholder-sub {
          font-size: 11px;
          color: rgba(255,255,255,0.4);
          margin-top: 6px; font-weight: 400;
        }

        .gt-aside {
          flex: 3;
          display: flex; flex-direction: column;
          gap: 12px;
          min-width: 260px;
        }
        .gt-card {
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 12px;
          padding: 14px 16px;
        }
        .gt-card-title {
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--cds-text-helper);
          margin-bottom: 10px;
        }
        .gt-sub-name {
          font-size: 15px; font-weight: 700;
          color: var(--ink);
          margin-bottom: 8px;
        }
        .gt-sub-row, .gt-cost-row {
          display: flex; justify-content: space-between;
          padding: 4px 0;
          font-size: 12px;
          color: var(--cds-text-secondary);
        }
        .gt-sub-row-hl, .gt-cost-row-hl {
          background: rgba(var(--accent-rgb), 0.08);
          margin: 2px -8px;
          padding: 6px 8px;
          border-radius: 6px;
          font-weight: 600;
        }
        .gt-sub-label, .gt-cost-band {
          font-size: 11px;
          color: var(--cds-text-helper);
        }
        .gt-cost-band {
          font-family: var(--mono); font-weight: 700;
        }
        .gt-sub-val, .gt-cost-val {
          font-family: var(--mono); font-weight: 600;
          color: var(--ink);
        }
        .gt-cost-note {
          font-size: 10px; color: var(--cds-text-helper);
          margin-top: 8px;
          font-style: italic;
        }
        .gt-verdict-pill {
          display: inline-flex;
          padding: 6px 14px;
          border-radius: 6px;
          font-family: var(--mono);
          font-size: 13px; font-weight: 700;
          letter-spacing: 0.04em;
          margin-bottom: 8px;
        }
        .gt-verdict-reason {
          font-size: 12px;
          color: var(--cds-text-secondary);
          line-height: 1.5;
        }

        .gt-scenarios {
          display: flex; align-items: center; gap: 16px;
          padding: 12px 16px;
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 12px;
        }
        .gt-scen-label {
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--cds-text-helper);
        }
        .gt-scen-buttons {
          display: flex; gap: 6px;
          flex: 1;
        }
        .gt-scen-btn {
          background: transparent;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 6px;
          padding: 6px 10px;
          font-family: inherit; font-size: 11px; font-weight: 600;
          color: var(--cds-text-secondary);
          cursor: pointer;
          transition: all 120ms;
        }
        .gt-scen-btn:hover {
          border-color: var(--gold);
          color: var(--gold-dark);
        }
        .gt-scen-active {
          background: var(--gold);
          color: #fff;
          border-color: var(--gold);
        }
        .gt-year {
          display: flex; align-items: center; gap: 10px;
          min-width: 200px;
        }
        .gt-year input[type=range] {
          flex: 1; accent-color: var(--gold);
        }
        .gt-year-val {
          font-family: var(--mono);
          font-size: 13px; font-weight: 700;
          color: var(--ink);
          min-width: 42px; text-align: right;
        }
      `}</style>
    </div>
  );
}
