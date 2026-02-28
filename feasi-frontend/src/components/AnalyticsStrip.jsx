import React, { useState, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

function utcTime() {
  const d = new Date();
  return d.toISOString().slice(11, 19) + "Z";
}

export default function AnalyticsStrip() {
  const {
    agentResult, solarYield, gridContext, explain,
    parcelId, pickedLocation,
    analyticsCollapsed, setAnalyticsCollapsed,
  } = useSite();

  const [time, setTime] = useState(utcTime);

  useEffect(() => {
    const t = setInterval(() => setTime(utcTime()), 1000);
    return () => clearInterval(t);
  }, []);

  if (analyticsCollapsed) {
    return (
      <div className="analytics-area analytics-collapsed-bar">
        <button className="analytics-expand-btn" onClick={() => setAnalyticsCollapsed(false)}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="18 15 12 9 6 15" /></svg>
        </button>
      </div>
    );
  }

  const verdict = agentResult?.verdict;
  const verdictColor = verdict === "GO" ? "#4caf50" : verdict === "CAUTION" ? "#ff9800" : verdict === "NO-GO" ? "#f44336" : "#546e7a";

  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const score = explain?.score_total;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const confidence = agentResult?.confidence;

  const metrics = [
    { label: "YIELD", value: annualKwh ? `${(annualKwh / 1000).toFixed(1)} MWh/yr` : "--", color: "#ff9800" },
    { label: "CF", value: cf ? `${cf.toFixed(1)}%` : "--", color: "#00e5ff" },
    { label: "SCORE", value: score != null ? `${score}/120` : "--", color: "#00ff88" },
    { label: "GRID", value: gridDist ? `${gridDist.toFixed(1)} km` : "--", color: "#2196f3" },
    { label: "CONF", value: confidence ? `${Math.round(confidence * 100)}%` : "--", color: "#7c4dff" },
  ];

  return (
    <div className="analytics-area analytics-strip">
      <div className="analytics-status">
        <span className="analytics-dot" style={{ background: verdictColor, boxShadow: `0 0 8px ${verdictColor}` }} />
        <span className="analytics-verdict" style={{ color: verdictColor }}>
          {verdict || "STANDBY"}
        </span>
      </div>

      <div className="analytics-metrics">
        {metrics.map((m) => (
          <div key={m.label} className="analytics-metric">
            <span className="analytics-metric-label">{m.label}</span>
            <span className="analytics-metric-value" style={{ color: m.color }}>{m.value}</span>
          </div>
        ))}
      </div>

      <div className="analytics-meta">
        {pickedLocation && (
          <span className="analytics-coord">
            {pickedLocation.lat.toFixed(3)}N {Math.abs(pickedLocation.lon).toFixed(3)}{pickedLocation.lon < 0 ? "W" : "E"}
          </span>
        )}
        {parcelId && <span className="analytics-pid">{parcelId.slice(0, 8)}</span>}
        <span className="analytics-time">{time}</span>
        <button className="analytics-collapse-btn" onClick={() => setAnalyticsCollapsed(true)} title="Collapse">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
        </button>
      </div>
    </div>
  );
}
