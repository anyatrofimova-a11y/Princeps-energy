import React, { useState, useCallback } from "react";

const METRICS = [
  { key: "solar_cf", label: "Solar CF", unit: "%", fmt: v => `${(v * 100).toFixed(1)}%`, higher: true },
  { key: "grid_headroom_mw", label: "Grid Headroom", unit: "MW", fmt: v => `${v.toFixed(1)} MW`, higher: true },
  { key: "connection_cost_k", label: "Connection Cost", unit: "\u00A3k", fmt: v => `\u00A3${Math.round(v)}k`, higher: false },
  { key: "timeline_months", label: "Timeline", unit: "months", fmt: v => `${Math.round(v)} mo`, higher: false },
  { key: "revenue_yr", label: "Revenue", unit: "\u00A3/yr", fmt: v => `\u00A3${(v / 1000).toFixed(0)}k/yr`, higher: true },
  { key: "irr", label: "IRR", unit: "%", fmt: v => `${(v * 100).toFixed(1)}%`, higher: true },
  { key: "planning_risk", label: "Planning Risk", unit: "score", fmt: v => v.toFixed(2), higher: false },
  { key: "verdict", label: "Verdict", unit: "", fmt: v => v, higher: null },
];

const VERDICT_COLORS = { GO: "#24a148", CAUTION: "#f1c21b", "NO-GO": "#da1e28" };

function emptyScenario() {
  return {
    id: Date.now() + Math.random(),
    name: "",
    lat: null,
    lon: null,
    capacity_mw: 50,
    technology: "solar",
    results: null,
  };
}

function bestIndex(scenarios, key, higher) {
  let bestIdx = -1;
  let bestVal = higher ? -Infinity : Infinity;
  scenarios.forEach((s, i) => {
    if (!s.results || s.results[key] == null) return;
    const v = s.results[key];
    if (higher && v > bestVal) { bestVal = v; bestIdx = i; }
    if (!higher && v < bestVal) { bestVal = v; bestIdx = i; }
  });
  return bestIdx;
}

function exportCSV(scenarios) {
  const headers = ["Site", "Technology", "Capacity MW", ...METRICS.map(m => m.label)];
  const rows = scenarios.map(s => [
    s.name || `${s.lat?.toFixed(4)}, ${s.lon?.toFixed(4)}`,
    s.technology,
    s.capacity_mw,
    ...METRICS.map(m => s.results?.[m.key] != null ? s.results[m.key] : ""),
  ]);
  const csv = [headers, ...rows].map(r => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "scenario_comparison.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export default function ScenarioCompare({ scenarios: initialScenarios, onClose, onRunAnalysis }) {
  const [scenarios, setScenarios] = useState(() =>
    initialScenarios && initialScenarios.length > 0
      ? initialScenarios.map((s, i) => ({ ...emptyScenario(), ...s, id: s.id || Date.now() + i }))
      : [emptyScenario(), emptyScenario()]
  );

  const addScenario = useCallback(() => {
    if (scenarios.length >= 4) return;
    setScenarios(prev => [...prev, emptyScenario()]);
  }, [scenarios.length]);

  const removeScenario = useCallback((id) => {
    setScenarios(prev => prev.filter(s => s.id !== id));
  }, []);

  const updateScenario = useCallback((id, field, value) => {
    setScenarios(prev => prev.map(s => s.id === id ? { ...s, [field]: value } : s));
  }, []);

  const handleRun = useCallback((scenario) => {
    if (onRunAnalysis) {
      onRunAnalysis(scenario, (results) => {
        setScenarios(prev => prev.map(s => s.id === scenario.id ? { ...s, results } : s));
      });
    }
  }, [onRunAnalysis]);

  // Find overall best scenario (most "best" metrics)
  const bestCounts = scenarios.map(() => 0);
  METRICS.forEach(m => {
    if (m.higher === null) return; // skip verdict
    const idx = bestIndex(scenarios, m.key, m.higher);
    if (idx >= 0) bestCounts[idx]++;
  });
  const overallBestIdx = bestCounts.indexOf(Math.max(...bestCounts));

  return (
    <div className="scenario-compare-overlay">
      <div className="scenario-compare-panel">
        {/* Header */}
        <div className="scenario-compare-header">
          <h2 className="scenario-compare-title">Scenario Comparison</h2>
          <div className="scenario-compare-header-actions">
            <button className="scenario-compare-btn scenario-compare-btn--export" onClick={() => exportCSV(scenarios)}>
              Export CSV
            </button>
            <button className="scenario-compare-btn scenario-compare-btn--close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {/* Columns */}
        <div className="scenario-compare-grid" style={{ gridTemplateColumns: `200px repeat(${scenarios.length}, 1fr)` }}>
          {/* Metric labels column */}
          <div className="scenario-compare-labels">
            <div className="scenario-compare-label-cell scenario-compare-label-cell--header">Metric</div>
            <div className="scenario-compare-label-cell scenario-compare-label-cell--site">Site</div>
            <div className="scenario-compare-label-cell scenario-compare-label-cell--tech">Technology</div>
            <div className="scenario-compare-label-cell scenario-compare-label-cell--cap">Capacity</div>
            {METRICS.map(m => (
              <div key={m.key} className="scenario-compare-label-cell">{m.label}</div>
            ))}
            <div className="scenario-compare-label-cell scenario-compare-label-cell--action" />
          </div>

          {/* Scenario columns */}
          {scenarios.map((s, idx) => {
            const isBest = overallBestIdx === idx && scenarios.some(sc => sc.results);
            return (
              <div key={s.id} className={`scenario-compare-col ${isBest ? "scenario-compare-col--best" : ""}`}>
                {/* Column header */}
                <div className="scenario-compare-col-header">
                  <input
                    className="scenario-compare-name-input"
                    placeholder={`Scenario ${idx + 1}`}
                    value={s.name}
                    onChange={e => updateScenario(s.id, "name", e.target.value)}
                  />
                  {scenarios.length > 1 && (
                    <button className="scenario-compare-remove" onClick={() => removeScenario(s.id)} title="Remove scenario">
                      &times;
                    </button>
                  )}
                  {isBest && <span className="scenario-compare-best-badge">BEST</span>}
                </div>

                {/* Site coords */}
                <div className="scenario-compare-cell scenario-compare-cell--site">
                  <input
                    className="scenario-compare-coord-input"
                    placeholder="Lat"
                    type="number"
                    step="0.0001"
                    value={s.lat || ""}
                    onChange={e => updateScenario(s.id, "lat", parseFloat(e.target.value) || null)}
                  />
                  <input
                    className="scenario-compare-coord-input"
                    placeholder="Lon"
                    type="number"
                    step="0.0001"
                    value={s.lon || ""}
                    onChange={e => updateScenario(s.id, "lon", parseFloat(e.target.value) || null)}
                  />
                </div>

                {/* Technology */}
                <div className="scenario-compare-cell">
                  <select
                    className="scenario-compare-select"
                    value={s.technology}
                    onChange={e => updateScenario(s.id, "technology", e.target.value)}
                  >
                    <option value="solar">Solar PV</option>
                    <option value="wind">Onshore Wind</option>
                    <option value="battery">Battery Storage</option>
                    <option value="hybrid">Solar + Battery</option>
                  </select>
                </div>

                {/* Capacity */}
                <div className="scenario-compare-cell">
                  <input
                    className="scenario-compare-cap-input"
                    type="number"
                    min={1}
                    max={500}
                    value={s.capacity_mw}
                    onChange={e => updateScenario(s.id, "capacity_mw", parseInt(e.target.value) || 1)}
                  />
                  <span className="scenario-compare-unit">MW</span>
                </div>

                {/* Metric rows */}
                {METRICS.map(m => {
                  const val = s.results?.[m.key];
                  const isBestMetric = m.higher !== null && bestIndex(scenarios, m.key, m.higher) === idx;
                  if (m.key === "verdict" && val) {
                    return (
                      <div key={m.key} className="scenario-compare-cell">
                        <span
                          className="scenario-compare-verdict"
                          style={{ color: VERDICT_COLORS[val] || "#ccc", background: "rgba(0,0,0,0.5)" }}
                        >
                          {val}
                        </span>
                      </div>
                    );
                  }
                  return (
                    <div key={m.key} className={`scenario-compare-cell ${isBestMetric ? "scenario-compare-cell--best" : ""}`}>
                      {val != null ? m.fmt(val) : <span className="scenario-compare-empty">--</span>}
                    </div>
                  );
                })}

                {/* Action button */}
                <div className="scenario-compare-cell scenario-compare-cell--action">
                  <button
                    className="scenario-compare-btn scenario-compare-btn--run"
                    disabled={!s.lat || !s.lon}
                    onClick={() => handleRun(s)}
                  >
                    Run Analysis
                  </button>
                </div>
              </div>
            );
          })}

          {/* Add scenario button */}
          {scenarios.length < 4 && (
            <div className="scenario-compare-col scenario-compare-col--add" onClick={addScenario}>
              <div className="scenario-compare-add-btn">
                <span className="scenario-compare-add-icon">+</span>
                <span>Add Scenario</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
