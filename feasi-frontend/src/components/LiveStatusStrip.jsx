import React, { useState, useEffect, useCallback } from "react";
import api from "../services/api";

/**
 * LiveStatusStrip — real-time UK grid status in the top bar.
 * Polls /api/grid/live-status every 30s for:
 * demand, renewable %, carbon intensity, frequency, wholesale price.
 */

const POLL_INTERVAL = 30_000;

function Metric({ label, value, unit, color, pulse }) {
  return (
    <div className="live-metric">
      <span className="live-metric-label">{label}</span>
      <span className="live-metric-value" style={{ color }}>
        {pulse && <span className="live-pulse" style={{ background: color }} />}
        {value ?? "—"}
      </span>
      {unit && <span className="live-metric-unit">{unit}</span>}
    </div>
  );
}

export default function LiveStatusStrip() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const d = await api.grid.liveStatus();
      if (d) { setData(d); setError(false); }
      else { setError(true); }
    } catch { setError(true); }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (!data && !error) return null;

  const carbonColor = !data?.carbon_intensity ? "#8A857D"
    : data.carbon_intensity < 100 ? "#16a34a"
    : data.carbon_intensity < 200 ? "#D4A018"
    : "#8B3A3A";

  const freqColor = !data?.frequency_hz ? "#8A857D"
    : Math.abs(data.frequency_hz - 50) < 0.05 ? "#16a34a"
    : Math.abs(data.frequency_hz - 50) < 0.15 ? "#D4A018"
    : "#8B3A3A";

  return (
    <div className="live-status-strip">
      <span className="live-status-dot" style={{ background: error ? "#8B3A3A" : "#16a34a" }} />
      <span className="live-status-label">UK GRID</span>

      {data && (
        <>
          <Metric
            label="Demand"
            value={data.total_generation_mw ? `${(data.total_generation_mw / 1000).toFixed(1)}` : null}
            unit="GW"
            color="#0F0E0A"
          />
          <Metric
            label="Renew"
            value={data.renewable_pct != null ? `${data.renewable_pct}` : null}
            unit="%"
            color="#16a34a"
          />
          <Metric
            label="Wind"
            value={data.wind_mw ? `${(data.wind_mw / 1000).toFixed(1)}` : null}
            unit="GW"
            color="#00b0ff"
          />
          <Metric
            label="Solar"
            value={data.solar_mw ? `${(data.solar_mw / 1000).toFixed(1)}` : null}
            unit="GW"
            color="#D4A018"
          />
          <Metric
            label="CO₂"
            value={data.carbon_intensity ?? null}
            unit="g"
            color={carbonColor}
          />
          <Metric
            label="Freq"
            value={data.frequency_hz?.toFixed(2) ?? null}
            unit="Hz"
            color={freqColor}
            pulse
          />
          {data.price_gbp_mwh != null && (
            <Metric
              label="Price"
              value={`£${data.price_gbp_mwh.toFixed(0)}`}
              unit="/MWh"
              color="#0F0E0A"
            />
          )}
        </>
      )}

      {error && !data && (
        <span className="live-status-error">Offline</span>
      )}
    </div>
  );
}
