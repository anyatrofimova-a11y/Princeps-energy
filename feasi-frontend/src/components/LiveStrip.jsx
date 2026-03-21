import React, { useState, useEffect, useRef, useCallback } from "react";

/**
 * LiveStrip — real-time BMRS / carbon / frequency / price ticker bar.
 *
 * Sits at the bottom of the map viewport. Polls /api/grid/live-status every 30s.
 * Shows sparkline history (last 30 readings ≈ 15 min), color-coded metrics,
 * and smooth animated transitions between values.
 */

const POLL_MS = 30_000;
const HISTORY_LEN = 30;

// Tiny inline sparkline (SVG)
function Spark({ data, color = "#4caf50", width = 48, height = 16 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const points = data
    .map((v, i) => `${i * step},${height - ((v - min) / range) * (height - 2) - 1}`)
    .join(" ");
  return (
    <svg width={width} height={height} style={{ verticalAlign: "middle", marginLeft: 4 }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function carbonColor(index) {
  if (!index) return "#888";
  const i = index.toLowerCase();
  if (i === "very low") return "#4caf50";
  if (i === "low") return "#8bc34a";
  if (i === "moderate") return "#ff9800";
  if (i === "high") return "#f44336";
  if (i === "very high") return "#b71c1c";
  return "#888";
}

function freqColor(hz) {
  if (hz == null) return "#888";
  const dev = Math.abs(hz - 50);
  if (dev < 0.05) return "#4caf50";
  if (dev < 0.1) return "#ff9800";
  return "#f44336";
}

function priceColor(p) {
  if (p == null) return "#888";
  if (p < 30) return "#4caf50";
  if (p < 60) return "#ff9800";
  if (p < 100) return "#f44336";
  return "#b71c1c";
}

export default function LiveStrip() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(false);
  const histRef = useRef({
    freq: [],
    carbon: [],
    price: [],
    wind: [],
    solar: [],
    renewable: [],
  });
  const [, tick] = useState(0); // force re-render on history update

  const poll = useCallback(() => {
    fetch("/api/grid/live-status")
      .then((r) => {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then((d) => {
        setStatus(d);
        setError(false);
        const h = histRef.current;
        const push = (arr, v) => {
          if (v != null) arr.push(v);
          if (arr.length > HISTORY_LEN) arr.shift();
        };
        push(h.freq, d.frequency_hz);
        push(h.carbon, d.carbon_intensity);
        push(h.price, d.price_gbp_mwh);
        push(h.wind, d.wind_mw);
        push(h.solar, d.solar_mw);
        push(h.renewable, d.renewable_pct);
        tick((t) => t + 1);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  if (!status) {
    return (
      <div className="live-strip live-strip--loading">
        <span className="live-strip-dot" /> Connecting to grid…
      </div>
    );
  }

  const h = histRef.current;

  return (
    <div className={`live-strip${error ? " live-strip--error" : ""}`}>
      {/* Pulse dot */}
      <span className="live-strip-dot live-strip-dot--live" />

      {/* Generation mix */}
      <div className="live-strip-group">
        <span className="live-strip-label">GEN</span>
        <span className="live-strip-val">
          {(status.total_generation_mw / 1000).toFixed(1)} GW
        </span>
      </div>

      <div className="live-strip-sep" />

      {/* Wind */}
      <div className="live-strip-group">
        <span className="live-strip-label" style={{ color: "#00b0ff" }}>WIND</span>
        <span className="live-strip-val">
          {(status.wind_mw / 1000).toFixed(1)} GW
        </span>
        <Spark data={h.wind} color="#00b0ff" />
      </div>

      {/* Solar */}
      <div className="live-strip-group">
        <span className="live-strip-label" style={{ color: "#fdd835" }}>SOLAR</span>
        <span className="live-strip-val">
          {(status.solar_mw / 1000).toFixed(1)} GW
        </span>
        <Spark data={h.solar} color="#fdd835" />
      </div>

      {/* Renewable % */}
      <div className="live-strip-group">
        <span className="live-strip-label" style={{ color: "#4caf50" }}>REN</span>
        <span className="live-strip-val" style={{ color: "#4caf50" }}>
          {status.renewable_pct}%
        </span>
        <Spark data={h.renewable} color="#4caf50" />
      </div>

      <div className="live-strip-sep" />

      {/* Carbon intensity */}
      <div className="live-strip-group">
        <span className="live-strip-label">CO₂</span>
        <span
          className="live-strip-val"
          style={{ color: carbonColor(status.carbon_index) }}
        >
          {status.carbon_intensity ?? "—"} g
        </span>
        <Spark data={h.carbon} color={carbonColor(status.carbon_index)} />
      </div>

      {/* Frequency */}
      <div className="live-strip-group">
        <span className="live-strip-label">FREQ</span>
        <span
          className="live-strip-val"
          style={{ color: freqColor(status.frequency_hz) }}
        >
          {status.frequency_hz?.toFixed(3) ?? "—"} Hz
        </span>
        <Spark data={h.freq} color={freqColor(status.frequency_hz)} width={40} />
      </div>

      {/* Wholesale price */}
      <div className="live-strip-group">
        <span className="live-strip-label">PRICE</span>
        <span
          className="live-strip-val"
          style={{ color: priceColor(status.price_gbp_mwh) }}
        >
          £{status.price_gbp_mwh?.toFixed(0) ?? "—"}
        </span>
        <Spark data={h.price} color={priceColor(status.price_gbp_mwh)} />
      </div>

      {/* Net imports */}
      <div className="live-strip-sep" />
      <div className="live-strip-group">
        <span className="live-strip-label">
          {status.net_imports_mw >= 0 ? "IMPORT" : "EXPORT"}
        </span>
        <span className="live-strip-val">
          {(Math.abs(status.net_imports_mw) / 1000).toFixed(1)} GW
        </span>
      </div>
    </div>
  );
}
