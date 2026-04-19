import React, { useState, useMemo } from "react";

const SCORE_KEYS = [
  { key: "resource", label: "Resource" },
  { key: "grid", label: "Grid" },
  { key: "planning", label: "Planning" },
  { key: "land_use", label: "Land use" },
  { key: "terrain", label: "Terrain" },
];

const VERDICT_STYLE = {
  "GO": { bg: "rgba(22,163,74,0.12)", fg: "var(--cds-support-success)" },
  "CAUTION": { bg: "rgba(232,160,18,0.14)", fg: "var(--cds-support-warning)" },
  "NO-GO": { bg: "rgba(220,38,38,0.12)", fg: "var(--cds-support-error)" },
};

const DEFAULT_SITES = [
  { candidate_id: "s1", name: "Rainham substation adjacent", lat: 51.518, lon: 0.19, capacity_mw: 50,
    scores: { resource: 82, grid: 88, planning: 71, land_use: 78, terrain: 65 }, lcoe: 42.5, verdict: "GO", is_preferred: true },
  { candidate_id: "s2", name: "Dagenham industrial estate", lat: 51.54, lon: 0.15, capacity_mw: 50,
    scores: { resource: 78, grid: 74, planning: 68, land_use: 62, terrain: 72 }, lcoe: 45.1, verdict: "GO", is_preferred: false },
  { candidate_id: "s3", name: "Tilbury port brownfield", lat: 51.465, lon: 0.36, capacity_mw: 50,
    scores: { resource: 74, grid: 82, planning: 45, land_use: 58, terrain: 80 }, lcoe: 48.3, verdict: "CAUTION", is_preferred: false },
];

function scoreCellStyle(value) {
  if (value == null) return { bg: "var(--cds-layer-03)", fg: "var(--cds-text-helper)" };
  if (value < 40) return { bg: "rgba(220,38,38,0.15)", fg: "var(--cds-support-error)" };
  if (value < 70) return { bg: "rgba(232,160,18,0.15)", fg: "var(--cds-support-warning)" };
  return { bg: "rgba(22,163,74,0.15)", fg: "var(--cds-support-success)" };
}

function Pill({ verdict }) {
  const s = VERDICT_STYLE[verdict] || { bg: "var(--cds-layer-03)", fg: "var(--cds-text-secondary)" };
  return (
    <span className="st-pill" style={{ background: s.bg, color: s.fg }}>
      {verdict || "—"}
    </span>
  );
}

function DeltaCell({ value, unit }) {
  if (value == null || value === 0) return <span className="st-delta-neutral">—</span>;
  const positive = value > 0;
  return (
    <span className={positive ? "st-delta-pos" : "st-delta-neg"}>
      {positive ? "+" : ""}{value}{unit || ""}
    </span>
  );
}

export default function SitesTab({
  sites = DEFAULT_SITES,
  onAddCandidate = () => {},
  onExport = () => {},
  onSelectSite = () => {},
}) {
  const [whatIfActive, setWhatIfActive] = useState(false);
  const [whatIfBy, setWhatIfBy] = useState(10); // +MW hypothetical

  const proposals = useMemo(() => {
    if (!whatIfActive) return {};
    const out = {};
    sites.forEach((s) => {
      out[s.candidate_id] = {
        capacity_delta: whatIfBy,
        lcoe_delta: -Math.round((whatIfBy / 10) * 12) / 10,
        grid_delta: -Math.min(8, Math.round(whatIfBy / 4)),
        resource_delta: 0,
        verdict_change: s.verdict === "GO" && whatIfBy > 20 ? "CAUTION" : s.verdict,
      };
    });
    return out;
  }, [whatIfActive, whatIfBy, sites]);

  return (
    <div className="st-root">
      <div className="st-toolbar">
        <div>
          <h2 className="st-title">Site comparison</h2>
          <div className="st-sub">Courses of action · {sites.length} candidates</div>
        </div>
        <div className="st-actions">
          <label className="st-whatif">
            <input
              type="checkbox"
              checked={whatIfActive}
              onChange={(e) => setWhatIfActive(e.target.checked)}
            />
            Propose what-if
          </label>
          {whatIfActive && (
            <div className="st-whatif-ctrl">
              <span>Resize by</span>
              <input
                type="number"
                value={whatIfBy}
                onChange={(e) => setWhatIfBy(Number(e.target.value))}
                step="5"
              />
              <span>MW</span>
            </div>
          )}
          <button className="st-btn st-btn-ghost" onClick={onExport}>Export</button>
          <button className="st-btn st-btn-primary" onClick={onAddCandidate}>+ Add site</button>
        </div>
      </div>

      <div className="st-table-wrap">
        <table className="st-table">
          <thead>
            <tr>
              <th className="st-th st-th-site">Site</th>
              <th className="st-th">Capacity</th>
              {SCORE_KEYS.map((k) => <th key={k.key} className="st-th">{k.label}</th>)}
              <th className="st-th">LCOE</th>
              <th className="st-th">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {sites.map((s) => {
              const proposal = proposals[s.candidate_id];
              return (
                <React.Fragment key={s.candidate_id}>
                  <tr
                    className={"st-row" + (s.is_preferred ? " st-row-preferred" : "")}
                    onClick={() => onSelectSite(s)}
                  >
                    <td className="st-td st-td-site">
                      <div className="st-site-name">
                        {s.is_preferred && <span className="st-star">★</span>}
                        {s.name}
                      </div>
                      {s.lat != null && (
                        <div className="st-coord">{s.lat.toFixed(3)}°, {s.lon.toFixed(3)}°</div>
                      )}
                    </td>
                    <td className="st-td st-td-num">
                      {s.capacity_mw ?? "—"}<span className="st-unit"> MW</span>
                    </td>
                    {SCORE_KEYS.map((k) => {
                      const v = s.scores?.[k.key];
                      const style = scoreCellStyle(v);
                      return (
                        <td key={k.key} className="st-td st-td-score">
                          <span className="st-score-chip" style={{ background: style.bg, color: style.fg }}>
                            {v ?? "—"}
                          </span>
                        </td>
                      );
                    })}
                    <td className="st-td st-td-num">
                      £{s.lcoe?.toFixed(1) ?? "—"}<span className="st-unit">/MWh</span>
                    </td>
                    <td className="st-td"><Pill verdict={s.verdict} /></td>
                  </tr>
                  {proposal && (
                    <tr className="st-proposal-row">
                      <td className="st-td st-td-site st-proposal-label">
                        <span className="st-arrow">↳</span>
                        Proposal: +{proposal.capacity_delta} MW
                      </td>
                      <td className="st-td st-td-num">
                        <DeltaCell value={proposal.capacity_delta} unit=" MW" />
                      </td>
                      <td className="st-td st-td-score">
                        <DeltaCell value={proposal.resource_delta} />
                      </td>
                      <td className="st-td st-td-score">
                        <DeltaCell value={proposal.grid_delta} />
                      </td>
                      <td className="st-td st-td-score">—</td>
                      <td className="st-td st-td-score">—</td>
                      <td className="st-td st-td-score">—</td>
                      <td className="st-td st-td-num">
                        <DeltaCell value={proposal.lcoe_delta} unit=" £/MWh" />
                      </td>
                      <td className="st-td">
                        {proposal.verdict_change !== s.verdict ? (
                          <span className="st-verdict-shift">
                            <Pill verdict={s.verdict} /> → <Pill verdict={proposal.verdict_change} />
                          </span>
                        ) : (
                          <span className="st-delta-neutral">no change</span>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="st-legend">
        <div className="st-legend-item"><span className="st-chip-sm" style={{ background: "rgba(22,163,74,0.15)" }} /> ≥ 70 good</div>
        <div className="st-legend-item"><span className="st-chip-sm" style={{ background: "rgba(232,160,18,0.15)" }} /> 40–69 marginal</div>
        <div className="st-legend-item"><span className="st-chip-sm" style={{ background: "rgba(220,38,38,0.15)" }} /> &lt; 40 poor</div>
        <div className="st-legend-item"><span className="st-star">★</span> preferred candidate</div>
      </div>

      <style>{`
        .st-root {
          padding: 20px 24px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: var(--cds-text-primary);
        }
        .st-toolbar {
          display: flex; justify-content: space-between; align-items: flex-end;
          margin-bottom: 16px;
        }
        .st-title {
          margin: 0;
          font-size: 18px; font-weight: 700;
          color: var(--ink);
        }
        .st-sub {
          font-size: 12px; color: var(--cds-text-helper);
          margin-top: 4px;
        }
        .st-actions {
          display: flex; align-items: center; gap: 12px;
        }
        .st-whatif {
          display: flex; align-items: center; gap: 6px;
          font-size: 13px; color: var(--cds-text-secondary);
          cursor: pointer; user-select: none;
        }
        .st-whatif input { cursor: pointer; accent-color: var(--gold); }
        .st-whatif-ctrl {
          display: flex; align-items: center; gap: 6px;
          font-size: 12px; color: var(--cds-text-secondary);
          padding: 4px 10px;
          background: rgba(var(--accent-rgb), 0.08);
          border-radius: 6px;
        }
        .st-whatif-ctrl input {
          width: 48px; padding: 2px 6px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 4px; font-family: var(--mono);
          font-size: 12px;
        }
        .st-btn {
          padding: 8px 14px;
          border-radius: 8px;
          font-family: inherit; font-size: 13px; font-weight: 600;
          cursor: pointer; border: 1px solid transparent;
          transition: all 120ms;
        }
        .st-btn-ghost {
          background: transparent;
          border-color: var(--cds-border-subtle);
          color: var(--cds-text-secondary);
        }
        .st-btn-ghost:hover {
          border-color: var(--gold);
          color: var(--gold-dark);
        }
        .st-btn-primary {
          background: var(--gold);
          color: #fff;
        }
        .st-btn-primary:hover { background: var(--gold-dark); }

        .st-table-wrap {
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 12px;
          overflow: hidden;
        }
        .st-table {
          width: 100%; border-collapse: collapse;
          font-size: 13px;
        }
        .st-th {
          text-align: left;
          padding: 10px 12px;
          background: var(--cds-layer-02);
          color: var(--cds-text-helper);
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.06em; text-transform: uppercase;
          border-bottom: 1px solid var(--cds-border-subtle);
        }
        .st-th-site { min-width: 240px; }
        .st-td {
          padding: 12px;
          border-bottom: 1px solid var(--cds-border-subtle);
          vertical-align: middle;
        }
        .st-row {
          cursor: pointer;
          transition: background 120ms;
          border-left: 3px solid transparent;
        }
        .st-row:hover { background: rgba(var(--accent-rgb), 0.04); }
        .st-row-preferred td:first-child {
          border-left: 3px solid var(--gold);
        }
        .st-site-name {
          display: flex; align-items: center; gap: 6px;
          font-weight: 600; color: var(--ink);
        }
        .st-coord {
          font-family: var(--mono); font-size: 10px;
          color: var(--cds-text-helper);
          margin-top: 3px;
        }
        .st-star { color: var(--gold); font-size: 13px; }
        .st-td-num {
          font-family: var(--mono);
          font-size: 13px; font-weight: 600;
          color: var(--ink);
        }
        .st-unit {
          font-size: 10px; font-weight: 500;
          color: var(--cds-text-helper);
          margin-left: 2px;
        }
        .st-td-score { text-align: center; }
        .st-score-chip {
          display: inline-block;
          padding: 4px 10px; border-radius: 6px;
          font-family: var(--mono);
          font-size: 13px; font-weight: 700;
          min-width: 40px; text-align: center;
        }
        .st-pill {
          display: inline-flex;
          padding: 3px 8px; border-radius: 5px;
          font-family: var(--mono);
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.04em;
        }

        .st-proposal-row {
          background: rgba(45,108,176,0.05);
        }
        .st-proposal-label {
          color: #2D6CB0;
          font-weight: 600;
          font-size: 12px;
        }
        .st-arrow { margin-right: 6px; }
        .st-delta-pos {
          color: #2D6CB0;
          font-family: var(--mono);
          font-size: 12px; font-weight: 700;
        }
        .st-delta-neg {
          color: var(--cds-support-error);
          font-family: var(--mono);
          font-size: 12px; font-weight: 700;
        }
        .st-delta-neutral {
          color: var(--cds-text-helper);
          font-size: 11px;
        }
        .st-verdict-shift {
          display: inline-flex; align-items: center; gap: 4px;
          font-size: 10px; color: var(--cds-text-helper);
        }

        .st-legend {
          display: flex; gap: 24px;
          margin-top: 12px;
          padding: 0 4px;
          font-size: 11px;
          color: var(--cds-text-helper);
        }
        .st-legend-item { display: flex; align-items: center; gap: 6px; }
        .st-chip-sm {
          display: inline-block;
          width: 12px; height: 12px; border-radius: 3px;
        }
      `}</style>
    </div>
  );
}
