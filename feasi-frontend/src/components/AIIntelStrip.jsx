import React, { useState, useEffect, useRef } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/**
 * AI Intelligence Strip — top banner + bottom status bar.
 * Always visible over the map, C2-style operational intelligence.
 */

// ── Top Banner: AI Threat/Opportunity Assessment ──
export function AITopBanner() {
  const { agentResult, parcelId, solarYield, gridContext, stabilityData, explain, geeflowData } = useSite();
  const [solarForecast, setSolarForecast] = useState(null);
  const [gridStab, setGridStab] = useState(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    api.analytics.solarForecast().then(d => { if (d) setSolarForecast(d); });
    api.analytics.gridStability().then(d => { if (d) setGridStab(d); });
  }, []);

  // Derive overall status
  const verdict = agentResult?.verdict?.toLowerCase?.() || "";
  const statusLevel = verdict.includes("go") && !verdict.includes("no")
    ? "GREEN" : verdict.includes("caution") ? "AMBER" : verdict.includes("no") ? "RED" : "STANDBY";
  const statusColors = {
    GREEN: { bg: "rgba(76,175,80,0.12)", border: "#4caf50", text: "#4caf50", label: "GO" },
    AMBER: { bg: "rgba(255,152,0,0.12)", border: "#ff9800", text: "#ff9800", label: "CAUTION" },
    RED: { bg: "rgba(244,67,54,0.12)", border: "#f44336", text: "#f44336", label: "NO-GO" },
    STANDBY: { bg: "rgba(212,160,24,0.06)", border: "#D4A01844", text: "#D4A018", label: "STANDBY" },
  };
  const st = statusColors[statusLevel];

  return (
    <div className="ai-top-banner" style={{ borderColor: st.border, background: st.bg }}>
      {/* Status indicator */}
      <div className="ai-status-block">
        <div className="ai-status-indicator" style={{ background: st.text, boxShadow: `0 0 12px ${st.text}` }} />
        <div>
          <div className="ai-status-label" style={{ color: st.text }}>{st.label}</div>
          <div className="ai-status-sub">AI ASSESSMENT</div>
        </div>
      </div>

      {/* Key metrics strip */}
      <div className="ai-metrics-strip">
        <div className="ai-metric">
          <span className="ai-metric-label">SOLAR YIELD</span>
          <span className="ai-metric-value" style={{ color: "#ff9800" }}>
            {solarYield?.annual_energy_kwh ? `${(solarYield.annual_energy_kwh / 1000).toFixed(1)} MWh/yr` : "--"}
          </span>
        </div>
        <div className="ai-metric-sep" />
        <div className="ai-metric">
          <span className="ai-metric-label">CAPACITY FACTOR</span>
          <span className="ai-metric-value" style={{ color: "#4caf50" }}>
            {solarYield?.capacity_factor_pct ? `${solarYield.capacity_factor_pct}%` : "--"}
          </span>
        </div>
        <div className="ai-metric-sep" />
        <div className="ai-metric">
          <span className="ai-metric-label">GRID STABILITY</span>
          <span className="ai-metric-value" style={{ color: gridStab?.summary?.cascade_risk === "low" ? "#4caf50" : "#ff9800" }}>
            {gridStab?.summary ? `${gridStab.summary.percent_stable}%` : "--"}
          </span>
        </div>
        <div className="ai-metric-sep" />
        <div className="ai-metric">
          <span className="ai-metric-label">FORECAST</span>
          <span className="ai-metric-value" style={{ color: "#D4A018" }}>
            {solarForecast ? `${solarForecast.daily_yield_kwh} kWh/d` : "--"}
          </span>
        </div>
        <div className="ai-metric-sep" />
        <div className="ai-metric">
          <span className="ai-metric-label">SITE SCORE</span>
          <span className="ai-metric-value" style={{ color: "#7c4dff" }}>
            {explain?.score?.total != null ? `${explain.score.total}/120` : "--"}
          </span>
        </div>
        <div className="ai-metric-sep" />
        <div className="ai-metric">
          <span className="ai-metric-label">LAND SCORE</span>
          <span className="ai-metric-value" style={{ color: "#1565c0" }}>
            {geeflowData?.site_score?.total_score != null
              ? `${geeflowData.site_score.total_score}/100`
              : "--"}
          </span>
        </div>
      </div>

      {/* AI summary text */}
      <div className="ai-summary-text">
        {agentResult?.summary
          ? agentResult.summary.slice(0, 120) + (agentResult.summary.length > 120 ? "..." : "")
          : parcelId ? "AI analysis available — click Analyse" : "Select site for AI intelligence briefing"}
      </div>
    </div>
  );
}

// ── Bottom Status Bar: Real-time operational intelligence ──
export function AIBottomBar() {
  const { parcelId, pickedLocation, gridContext, energyPrice, deferral, demandForecast } = useSite();
  const [prosumer, setProsumer] = useState(null);
  const [turbine, setTurbine] = useState(null);
  const [transmission, setTransmission] = useState(null);
  const [time, setTime] = useState(new Date());
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    api.analytics.prosumerProfile().then(d => { if (d) setProsumer(d); });
    api.analytics.turbineHealth().then(d => { if (d) setTurbine(d); });
    api.analytics.transmissionFaults().then(d => { if (d) setTransmission(d); });
  }, []);

  useEffect(() => {
    const iv = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(iv);
  }, []);

  const faultColor = turbine?.current_status?.fault === "NF" ? "#4caf50" : "#f44336";
  const txHealth = transmission?.summary?.overall_health_pct;

  return (
    <div className="ai-bottom-bar">
      {/* Timestamp */}
      <div className="ai-bottom-cell ai-bottom-time">
        <span className="ai-bottom-label">ZULU</span>
        <span className="ai-bottom-val mono">{time.toISOString().slice(11, 19)}Z</span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Location */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">GRID REF</span>
        <span className="ai-bottom-val mono">
          {pickedLocation ? `${pickedLocation.lat.toFixed(4)}N ${Math.abs(pickedLocation.lon).toFixed(4)}${pickedLocation.lon >= 0 ? "E" : "W"}` : "NO FIX"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Prosumer self-sufficiency */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">SELF-SUFF</span>
        <span className="ai-bottom-val" style={{ color: prosumer?.summary?.self_sufficiency_pct > 50 ? "#4caf50" : "#ff9800" }}>
          {prosumer?.summary ? `${prosumer.summary.self_sufficiency_pct}%` : "--"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Turbine health */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">TURBINE</span>
        <span className="ai-bottom-val" style={{ color: faultColor }}>
          {turbine?.current_status?.label || "--"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Transmission */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">TX LINES</span>
        <span className="ai-bottom-val" style={{ color: txHealth >= 80 ? "#4caf50" : txHealth >= 50 ? "#ff9800" : "#f44336" }}>
          {txHealth != null ? `${txHealth}% OK` : "--"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Energy price */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">ENERGY £</span>
        <span className="ai-bottom-val" style={{ color: "#ffeb3b" }}>
          {energyPrice?.export_rate_p ? `${energyPrice.export_rate_p}p/kWh` : "--"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Grid connection */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">GRID CONN</span>
        <span className="ai-bottom-val" style={{ color: "#D4A018" }}>
          {gridContext?.nearest_substation_km ? `${gridContext.nearest_substation_km.toFixed(1)}km` : "--"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Deferral status */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">DEFERRAL</span>
        <span className="ai-bottom-val" style={{ color: deferral?.allocations ? "#4caf50" : "#666" }}>
          {deferral?.allocations ? `${deferral.allocations.length} ALLOC` : "NONE"}
        </span>
      </div>

      <div className="ai-bottom-sep" />

      {/* Parcel ID */}
      <div className="ai-bottom-cell">
        <span className="ai-bottom-label">PARCEL</span>
        <span className="ai-bottom-val mono" style={{ color: "#888" }}>
          {parcelId ? parcelId.slice(0, 8) : "NONE"}
        </span>
      </div>
    </div>
  );
}
