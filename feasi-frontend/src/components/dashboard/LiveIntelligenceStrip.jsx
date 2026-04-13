import React, { useState, useEffect, useRef, useCallback } from "react";
import api from "../../services/api";

function fmtGw(v) {
  if (v == null || isNaN(v)) return "---";
  const gw = v >= 1000 ? v / 1000 : v;
  return gw.toFixed(1);
}

function TrendArrow({ current, previous }) {
  if (previous == null || previous === 0 || current == null) return null;
  const pct = ((current - previous) / Math.abs(previous)) * 100;
  const up = pct >= 0;
  return (
    <span style={{
      fontFamily: "var(--mono), monospace",
      fontSize: 10,
      fontWeight: 700,
      color: up ? "#16a34a" : "#dc2626",
      display: "inline-flex",
      alignItems: "center",
      gap: 1,
    }}>
      <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
        <path d={up ? "M4 1L7 5H1L4 1Z" : "M4 7L1 3H7L4 7Z"} fill="currentColor" />
      </svg>
      {up ? "+" : ""}{pct.toFixed(0)}%
    </span>
  );
}

function Metric({ label, value, unit, color, trend, onClick }) {
  const [flash, setFlash] = useState(false);
  const prevVal = useRef(value);

  useEffect(() => {
    if (prevVal.current !== value) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      prevVal.current = value;
      return () => clearTimeout(t);
    }
  }, [value]);

  return (
    <div
      onClick={onClick}
      title={`${label}: ${value}${unit || ""}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: "pointer",
        padding: "4px 8px",
        borderRadius: 6,
        transition: "background 0.15s ease",
        flexShrink: 0,
      }}
      onMouseEnter={(e) => e.currentTarget.style.background = "rgba(245,183,49,0.06)"}
      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
    >
      <span style={{
        fontSize: 10,
        color: "var(--muted)",
        fontWeight: 600,
        letterSpacing: "0.02em",
      }}>
        {label}
      </span>
      <span style={{
        fontFamily: "var(--mono), monospace",
        fontSize: 13,
        fontWeight: 700,
        color: color || "var(--ink)",
        transition: "color 0.3s ease",
        ...(flash ? { color: "var(--gold)" } : {}),
      }}>
        {value}
      </span>
      {unit && (
        <span style={{ fontSize: 10, color: "var(--muted)", fontWeight: 500 }}>
          {unit}
        </span>
      )}
      {trend}
    </div>
  );
}

function Separator() {
  return (
    <div style={{
      width: 1,
      height: 20,
      background: "var(--border)",
      margin: "0 4px",
      flexShrink: 0,
      opacity: 0.6,
    }} />
  );
}

// Fallback when backend isn't running
const FALLBACK = {
  demand_gw: 32.1, wind_gw: 14.3, solar_gw: 9.1,
  carbon_intensity: 210, price_gbp_mwh: 48, frequency: 50.00,
};

export default function LiveIntelligenceStrip() {
  const [data, setData] = useState(FALLBACK);
  const prevRef = useRef(null);

  const poll = useCallback(async () => {
    try {
      const d = await api.liveGrid?.snapshot?.();
      if (d) {
        prevRef.current = data;
        setData(d);
      }
    } catch {}
  }, [data]);

  useEffect(() => {
    poll();
    const iv = setInterval(poll, 30000);
    return () => clearInterval(iv);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const prev = prevRef.current;
  const freq = parseFloat(data?.frequency) || 50.0;
  const freqAnomaly = Math.abs(freq - 50) > 0.05;
  const freqColor = freqAnomaly ? "#dc2626" : "#16a34a";

  const demandGw = data?.demand_gw ?? (data?.demand_mw != null ? data.demand_mw / 1000 : null);
  const windGw = data?.wind_gw ?? (data?.wind_mw != null ? data.wind_mw / 1000 : null);
  const solarGw = data?.solar_gw ?? (data?.solar_mw != null ? data.solar_mw / 1000 : null);
  const carbon = data?.carbon_intensity;
  const price = data?.price_gbp_mwh;

  const prevDemand = prev?.demand_gw ?? (prev?.demand_mw != null ? prev.demand_mw / 1000 : null);
  const prevWind = prev?.wind_gw ?? (prev?.wind_mw != null ? prev.wind_mw / 1000 : null);
  const prevSolar = prev?.solar_gw ?? (prev?.solar_mw != null ? prev.solar_mw / 1000 : null);
  const prevCarbon = prev?.carbon_intensity;
  const prevPrice = prev?.price_gbp_mwh;

  const carbonColor = carbon > 250 ? "#dc2626" : carbon > 150 ? "#d97706" : "#16a34a";

  const drillDown = (metric) => () => {
    console.log(`[LiveIntelligenceStrip] drill-down: ${metric}`, data);
  };

  return (
    <div
      className="pd3-enter-1"
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 0,
        padding: "6px 12px",
        margin: "0 24px 16px",
        background: "var(--cds-layer-01, #fff)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
        overflow: "hidden",
        whiteSpace: "nowrap",
      }}
    >
      {/* Scan line */}
      <div className="pd3-scan-line" />

      {/* LIVE indicator */}
      <div style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        marginRight: 8,
        flexShrink: 0,
        padding: "3px 8px 3px 6px",
        borderRadius: 6,
        background: "rgba(34,197,94,0.06)",
      }}>
        <span style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: "#22c55e",
          animation: "pd-live-dot 2s infinite",
          display: "inline-block",
        }} />
        <span style={{
          fontSize: 9,
          fontWeight: 800,
          color: "#16a34a",
          letterSpacing: "0.06em",
        }}>
          LIVE
        </span>
      </div>

      {/* Grid status */}
      <span style={{
        fontSize: 10,
        fontWeight: 700,
        color: "var(--ink)",
        marginRight: 4,
      }}>
        GRID
      </span>
      <span style={{
        fontFamily: "var(--mono), monospace",
        fontSize: 12,
        fontWeight: 700,
        color: freqColor,
        marginRight: 2,
      }}>
        {freqAnomaly ? "Alert" : "Stable"}
      </span>
      <span style={{
        fontFamily: "var(--mono), monospace",
        fontSize: 11,
        color: freqColor,
        fontWeight: 600,
      }}>
        {freq.toFixed(2)} Hz
      </span>
      {freqAnomaly && (
        <span style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 3,
          padding: "1px 6px",
          borderRadius: 4,
          background: "rgba(220,38,38,0.08)",
          color: "#dc2626",
          fontSize: 9,
          fontWeight: 800,
          letterSpacing: "0.04em",
          marginLeft: 4,
          animation: "pd-glow-pulse 1.5s infinite",
        }}>
          ANOMALY
        </span>
      )}

      <Separator />
      <Metric label="Demand" value={fmtGw(demandGw)} unit="GW" trend={<TrendArrow current={demandGw} previous={prevDemand} />} onClick={drillDown("demand")} />
      <Separator />
      <Metric label="Wind" value={fmtGw(windGw)} unit="GW" trend={<TrendArrow current={windGw} previous={prevWind} />} onClick={drillDown("wind")} />
      <Separator />
      <Metric label="Solar" value={fmtGw(solarGw)} unit="GW" trend={<TrendArrow current={solarGw} previous={prevSolar} />} onClick={drillDown("solar")} />
      <Separator />
      <Metric label="CO&#x2082;" value={carbon?.toFixed(0) ?? "---"} unit="g" color={carbonColor} trend={<TrendArrow current={carbon} previous={prevCarbon} />} onClick={drillDown("carbon")} />
      <Separator />
      <Metric label="" value={`\u00A3${price?.toFixed(0) ?? "---"}`} unit="/MWh" trend={<TrendArrow current={price} previous={prevPrice} />} onClick={drillDown("price")} />
    </div>
  );
}
