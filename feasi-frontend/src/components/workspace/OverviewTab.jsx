import React from "react";

const MOCK_BLOCKERS = [
  { severity: "warn", text: "Grid headroom marginal at summer peak — needs reinforcement", age: "2d ago" },
  { severity: "warn", text: "Local planning authority requires ecology survey", age: "5d ago" },
  { severity: "info", text: "Noise assessment pending for DC cooling plant", age: "1w ago" },
];

const MOCK_ACTIVITY = [
  { icon: "⚡", text: "Grid study completed — Tier 2 power flow passed", ts: "3h ago" },
  { icon: "◈", text: "DNO G99 application drafted", ts: "1d ago" },
  { icon: "★", text: "New candidate site added (Rainham)", ts: "2d ago" },
  { icon: "⚙", text: "Planning ML score updated: 71 → 74", ts: "4d ago" },
  { icon: "✎", text: "Financial model recomputed — IRR 11.8%", ts: "6d ago" },
];

const MOCK_NEXT = [
  "Submit G99 connection form to DNO",
  "Commission ecology + noise surveys",
  "Schedule LPA pre-application meeting",
];

function Sparkline({ points = [12, 14, 13, 15, 17, 16, 18, 20, 19, 22], color = "var(--gold)" }) {
  const w = 260, h = 60, pad = 4;
  const max = Math.max(...points), min = Math.min(...points);
  const range = max - min || 1;
  const step = (w - pad * 2) / (points.length - 1);
  const d = points
    .map((p, i) => {
      const x = pad + i * step;
      const y = h - pad - ((p - min) / range) * (h - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="ov-spark">
      <path d={d} stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export default function OverviewTab({
  project,
  mapSlot = null,
  onViewMap = () => {},
  onViewTab = () => {},
}) {
  const isBess = project?.technology === "bess";
  const isDC = project?.technology === "dc";

  const kpis = isBess
    ? [
        { label: "Projected IRR", value: "11.8%", trend: "+0.4" },
        { label: "LCOE", value: "£42/MWh", trend: "−£0.8" },
        { label: "CAPEX", value: "£52M", trend: "flat" },
      ]
    : isDC
    ? [
        { label: "PUE (modelled)", value: "1.24", trend: "−0.02" },
        { label: "$/MW/yr", value: "£3.8M", trend: "+£120k" },
        { label: "Grid risk", value: "Medium", trend: "watch" },
      ]
    : [
        { label: "IRR", value: "—", trend: "" },
        { label: "LCOE", value: "—", trend: "" },
        { label: "CAPEX", value: "—", trend: "" },
      ];

  return (
    <div className="ov-root">
      <div className="ov-row ov-row-top">
        <div className="ov-card ov-map-card">
          <div className="ov-card-header">
            <span>Site map</span>
            <button className="ov-link" onClick={onViewMap}>Full-screen ⇱</button>
          </div>
          <div className="ov-map-preview">
            {mapSlot ? (
              <div className="ov-map-live">{mapSlot}</div>
            ) : (
              <div className="ov-map-placeholder">
                Map preview
                {project?.lat != null && (
                  <div className="ov-map-coord">
                    {project.lat.toFixed(4)}°, {project.lon.toFixed(4)}°
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="ov-card ov-perf-card">
          <div className="ov-card-header">
            <span>Performance</span>
            <button className="ov-link" onClick={() => onViewTab("financial")}>Financial →</button>
          </div>
          <div className="ov-kpi-row">
            {kpis.map((k, i) => (
              <div key={i} className="ov-kpi">
                <div className="ov-kpi-label">{k.label}</div>
                <div className="ov-kpi-value">{k.value}</div>
                <div className="ov-kpi-trend">{k.trend}</div>
              </div>
            ))}
          </div>
          <Sparkline />
        </div>
      </div>

      <div className="ov-row ov-row-bot">
        <div className="ov-card">
          <div className="ov-card-header">
            <span>Blockers</span>
            <span className="ov-count">{MOCK_BLOCKERS.length}</span>
          </div>
          <ul className="ov-list">
            {MOCK_BLOCKERS.map((b, i) => (
              <li key={i} className="ov-item">
                <span
                  className="ov-dot"
                  style={{
                    background:
                      b.severity === "warn"
                        ? "var(--cds-support-warning)"
                        : "var(--cds-text-helper)",
                  }}
                />
                <span className="ov-item-text">{b.text}</span>
                <span className="ov-item-age">{b.age}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="ov-card">
          <div className="ov-card-header"><span>Recent activity</span></div>
          <ul className="ov-list">
            {MOCK_ACTIVITY.map((a, i) => (
              <li key={i} className="ov-item">
                <span className="ov-activity-icon">{a.icon}</span>
                <span className="ov-item-text">{a.text}</span>
                <span className="ov-item-age">{a.ts}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="ov-card">
          <div className="ov-card-header"><span>Next steps</span></div>
          <ul className="ov-list ov-list-tasks">
            {MOCK_NEXT.map((t, i) => (
              <li key={i} className="ov-item">
                <input type="checkbox" className="ov-check" />
                <span className="ov-item-text">{t}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <style>{`
        .ov-root {
          padding: 24px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: var(--cds-text-primary);
          display: flex; flex-direction: column; gap: 16px;
          overflow-y: auto;
        }
        .ov-row { display: flex; gap: 16px; }
        .ov-row-top > .ov-map-card { flex: 3; min-height: 420px; }
        .ov-row-top > .ov-perf-card { flex: 2; }
        .ov-row-bot > .ov-card { flex: 1; }
        .ov-card {
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 12px;
          padding: 16px;
          display: flex; flex-direction: column; min-width: 0;
        }
        .ov-card-header {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 12px;
          font-size: 13px; font-weight: 700;
          color: var(--ink);
        }
        .ov-link {
          background: none; border: none; padding: 0;
          color: var(--gold-dark);
          font-size: 12px; font-weight: 600;
          cursor: pointer;
        }
        .ov-link:hover { color: var(--gold); }
        .ov-count {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 1px 8px; border-radius: 10px;
          font-size: 10px; font-family: var(--mono);
          font-weight: 700;
        }

        .ov-map-preview {
          flex: 1;
          position: relative;
          min-height: 360px;
          border-radius: 8px;
          overflow: hidden;
        }
        .ov-map-live {
          position: absolute; inset: 0;
        }
        .ov-map-placeholder {
          height: 100%; min-height: 240px;
          background: linear-gradient(135deg, #EEF0F3, #E3E6EB);
          border-radius: 8px;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 6px;
          color: var(--cds-text-helper);
          font-size: 13px;
        }
        .ov-map-coord {
          font-family: var(--mono); font-size: 11px;
        }

        .ov-kpi-row {
          display: flex; gap: 12px;
          margin-bottom: 12px;
        }
        .ov-kpi {
          flex: 1;
          padding: 10px 12px;
          background: var(--cds-layer-02);
          border-radius: 8px;
        }
        .ov-kpi-label {
          font-size: 10px; font-weight: 600;
          color: var(--cds-text-helper);
          letter-spacing: 0.04em;
          text-transform: uppercase;
          margin-bottom: 4px;
        }
        .ov-kpi-value {
          font-family: var(--mono);
          font-size: 18px; font-weight: 700;
          color: var(--ink);
        }
        .ov-kpi-trend {
          font-family: var(--mono);
          font-size: 10px;
          color: var(--cds-text-helper);
          margin-top: 2px;
        }
        .ov-spark {
          width: 100%; height: 60px;
        }

        .ov-list {
          list-style: none; margin: 0; padding: 0;
          display: flex; flex-direction: column; gap: 6px;
        }
        .ov-item {
          display: flex; align-items: center; gap: 10px;
          padding: 6px 0;
          font-size: 12px;
          color: var(--cds-text-secondary);
          border-bottom: 1px solid transparent;
        }
        .ov-item-text { flex: 1; }
        .ov-item-age {
          font-family: var(--mono); font-size: 10px;
          color: var(--cds-text-helper);
          flex-shrink: 0;
        }
        .ov-dot {
          width: 8px; height: 8px; border-radius: 50%;
          flex-shrink: 0;
        }
        .ov-activity-icon {
          font-size: 14px; width: 18px;
          color: var(--cds-text-helper);
          text-align: center;
        }
        .ov-list-tasks .ov-item { padding: 8px 0; }
        .ov-check { accent-color: var(--gold); cursor: pointer; }
      `}</style>
    </div>
  );
}
