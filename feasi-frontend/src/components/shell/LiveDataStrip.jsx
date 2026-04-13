import React, { useState, useEffect, useRef } from "react";
import api from "../../services/api";

export default function LiveDataStrip() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const intervalRef = useRef(null);

  useEffect(() => {
    const fetchLive = async () => {
      try {
        const snapshot = await api.liveGrid.snapshot();
        if (snapshot) { setData(snapshot); setError(false); }
      } catch { setError(true); }
    };
    fetchLive();
    intervalRef.current = setInterval(fetchLive, 30000);
    return () => clearInterval(intervalRef.current);
  }, []);

  if (!data) return (
    <div className="live-strip-v2">
      <span className="live-dot offline" />
      <span className="live-label">Connecting to grid data...</span>
    </div>
  );

  const demand = data.demand?.current_mw ? (data.demand.current_mw / 1000).toFixed(1) : null;
  const wind = data.wind?.current_mw ? (data.wind.current_mw / 1000).toFixed(1) : null;
  const solarEntry = data.generation_mix?.find(g => g.fuel === 'solar');
  const solarGW = solarEntry && data.demand?.current_mw
    ? (solarEntry.perc * data.demand.current_mw / 100 / 1000).toFixed(1) : null;
  const carbon = data.carbon?.forecast_gco2_kwh || data.carbon?.actual_gco2_kwh;
  const carbonIndex = data.carbon?.index;
  const freq = data.frequency?.hz;
  const price = data.price?.market_index_gbp_mwh;
  const renewPct = data.generation?.renewable_pct;

  // Carbon badge color
  const carbonColor = carbonIndex === 'very low' ? '#16a34a' : carbonIndex === 'low' ? '#4ade80' :
    carbonIndex === 'moderate' ? '#D4A018' : carbonIndex === 'high' ? '#ef4444' : '#dc2626';

  return (
    <div className="live-strip-v2">
      <span className="live-dot" />
      <span className="live-label">LIVE</span>

      {demand && <MetricPill label="Demand" value={`${demand} GW`} />}
      {wind && <MetricPill label="Wind" value={`${wind} GW`} color="#3b82f6" />}
      {solarGW ? <MetricPill label="Solar" value={`${solarGW} GW`} color="#f59e0b" /> :
        solarEntry ? <MetricPill label="Solar" value={`${solarEntry.perc}%`} color="#f59e0b" /> : null}
      {carbon && <MetricPill label="Carbon" value={`${Math.round(carbon)} gCO\u2082`} badge={carbonIndex} badgeColor={carbonColor} />}
      {freq != null && <MetricPill label="Freq" value={`${parseFloat(freq).toFixed(2)} Hz`} color={parseFloat(freq) < 49.95 || parseFloat(freq) > 50.05 ? '#ef4444' : '#16a34a'} />}
      {price != null && <MetricPill label="Price" value={`\u00a3${Number(price).toFixed(0)}/MWh`} color="#22c55e" />}
      {renewPct != null && <MetricPill label="Renewables" value={`${renewPct}%`} color="#16a34a" />}

      <span className="live-timestamp">{new Date(data.timestamp).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span>
    </div>
  );
}

function MetricPill({ label, value, color, badge, badgeColor }) {
  return (
    <div className="live-metric">
      <span className="live-metric-label">{label}</span>
      <span className="live-metric-value" style={color ? {color} : undefined}>{value}</span>
      {badge && <span className="live-badge" style={{background: badgeColor, color: '#fff'}}>{badge}</span>}
    </div>
  );
}
