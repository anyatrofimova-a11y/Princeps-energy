import React, { useState, useEffect, useCallback } from "react";
import api from "../../services/api";
import StatusBadge from "./StatusBadge";

function ScenarioCard({ title, data, color }) {
  if (!data) {
    return (
      <div className="gcmp-card gcmp-card--empty">
        <div className="gcmp-card-title">{title}</div>
        <div className="gcmp-card-empty">Select a scenario</div>
      </div>
    );
  }
  return (
    <div className="gcmp-card" style={{ borderTopColor: color }}>
      <div className="gcmp-card-title">{title}</div>
      {data.label && <div className="gcmp-card-label">{data.label}</div>}
      {data.verdict && (
        <div className="gcmp-card-verdict">
          <StatusBadge status={data.verdict} />
        </div>
      )}
      {data.confidence != null && (
        <div className="gcmp-kpi-row">
          <span>Confidence</span>
          <span>{Math.round(data.confidence * 100)}%</span>
        </div>
      )}
      {data.intents && (
        <div className="gcmp-intents">
          {Object.entries(data.intents).map(([intent, result]) => (
            <div key={intent} className="gcmp-intent-row">
              <span className="gcmp-intent-name">{intent.replace(/_/g, " ")}</span>
              <StatusBadge status={result.verdict} size="xs" />
              {result.confidence != null && (
                <span className="gcmp-intent-conf">{Math.round(result.confidence * 100)}%</span>
              )}
            </div>
          ))}
        </div>
      )}
      {data.metrics && (
        <div className="gcmp-metrics">
          {Object.entries(data.metrics).map(([key, val]) => (
            <div key={key} className="gcmp-kpi-row">
              <span>{key.replace(/_/g, " ")}</span>
              <span>{typeof val === "number" ? val.toFixed(2) : String(val)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function GridCompareView() {
  const [scenarios, setScenarios] = useState([]);
  const [scenarioA, setScenarioA] = useState(null);
  const [scenarioB, setScenarioB] = useState(null);
  const [selectedA, setSelectedA] = useState("");
  const [selectedB, setSelectedB] = useState("");
  const [loading, setLoading] = useState(false);

  // Load available scenarios (grid twin scenarios)
  useEffect(() => {
    // Try grid twin scenarios
    const presets = [
      { id: "leading_the_way", label: "Leading the Way (FES)", year: 2030 },
      { id: "consumer_transformation", label: "Consumer Transformation (FES)", year: 2030 },
      { id: "system_transformation", label: "System Transformation (FES)", year: 2030 },
      { id: "falling_short", label: "Falling Short (FES)", year: 2030 },
    ];
    setScenarios(presets);
  }, []);

  const loadScenario = useCallback(async (id, setter) => {
    if (!id) { setter(null); return; }
    setLoading(true);
    try {
      const data = await api.gridTwin.scenario(id, 2030);
      if (data) {
        setter({ ...data, label: scenarios.find(s => s.id === id)?.label || id });
      }
    } catch { setter(null); }
    setLoading(false);
  }, [scenarios]);

  const handleSelectA = (e) => {
    setSelectedA(e.target.value);
    loadScenario(e.target.value, setScenarioA);
  };

  const handleSelectB = (e) => {
    setSelectedB(e.target.value);
    loadScenario(e.target.value, setScenarioB);
  };

  // Compute deltas between A and B
  const deltas = [];
  if (scenarioA && scenarioB) {
    const metricsA = scenarioA.metrics || {};
    const metricsB = scenarioB.metrics || {};
    const allKeys = new Set([...Object.keys(metricsA), ...Object.keys(metricsB)]);
    for (const key of allKeys) {
      const va = metricsA[key];
      const vb = metricsB[key];
      if (typeof va === "number" && typeof vb === "number") {
        deltas.push({ key, a: va, b: vb, delta: vb - va, pctChange: va !== 0 ? ((vb - va) / va) * 100 : 0 });
      }
    }
  }

  return (
    <div className="grid-compare-view">
      <div className="gcmp-header">
        <h3 className="gcmp-title">Scenario Comparison</h3>
        <div className="gcmp-hint">
          Compare FES pathways to understand grid evolution under different policy scenarios
        </div>
      </div>

      {/* Selectors */}
      <div className="gcmp-selectors">
        <div className="gcmp-selector">
          <label>Scenario A</label>
          <select value={selectedA} onChange={handleSelectA} className="gcmp-select">
            <option value="">Select scenario...</option>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </div>
        <div className="gcmp-vs">vs</div>
        <div className="gcmp-selector">
          <label>Scenario B</label>
          <select value={selectedB} onChange={handleSelectB} className="gcmp-select">
            <option value="">Select scenario...</option>
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && <div className="gcmp-loading">Loading scenarios...</div>}

      {/* Side-by-side cards */}
      <div className="gcmp-columns">
        <ScenarioCard title="Scenario A" data={scenarioA} color="var(--cds-interactive)" />
        <ScenarioCard title="Scenario B" data={scenarioB} color="#a56eff" />
      </div>

      {/* Delta table */}
      {deltas.length > 0 && (
        <div className="gcmp-deltas">
          <h4 className="gcmp-deltas-title">Differences</h4>
          <table className="gcmp-delta-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Scenario A</th>
                <th>Scenario B</th>
                <th>Delta</th>
                <th>Change</th>
              </tr>
            </thead>
            <tbody>
              {deltas.map(d => (
                <tr key={d.key}>
                  <td>{d.key.replace(/_/g, " ")}</td>
                  <td>{d.a.toFixed(2)}</td>
                  <td>{d.b.toFixed(2)}</td>
                  <td className={d.delta > 0 ? "positive" : d.delta < 0 ? "negative" : ""}>
                    {d.delta > 0 ? "+" : ""}{d.delta.toFixed(2)}
                  </td>
                  <td className={d.pctChange > 0 ? "positive" : d.pctChange < 0 ? "negative" : ""}>
                    {d.pctChange > 0 ? "+" : ""}{d.pctChange.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Empty state */}
      {!selectedA && !selectedB && !loading && (
        <div className="gcmp-empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
            <path d="M9 3v18m6-18v18M3 9h18M3 15h18" />
          </svg>
          <div>Select two FES scenarios to compare grid evolution pathways</div>
          <div style={{ fontSize: 10, color: "var(--cds-text-helper)", marginTop: 4 }}>
            Leading the Way, Consumer Transformation, System Transformation, Falling Short
          </div>
        </div>
      )}
    </div>
  );
}
