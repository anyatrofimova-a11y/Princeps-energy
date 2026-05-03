import {useState, useEffect, useRef} from 'react';
import api from '../services/api';

/**
 * V2 light-theme live data tape — replaces the legacy dark LiveDataStrip.
 * Same data source (`api.liveGrid.snapshot()`); rerendered with v2 tokens
 * so it sits cleanly in the cream / gold shell.
 *
 * Format mirrors the original Mission Control hero strip:
 *   ● LIVE    DEMAND 24.1 GW    WIND 13.7 GW    SOLAR 0.0 GW
 *             CARBON 56 gCO₂   FREQ 50.08 Hz    PRICE £0/MWh    01:05:18
 */
export default function V2LiveTape() {
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const intervalRef = useRef(null);
  const clockRef = useRef(null);

  useEffect(() => {
    const fetchOnce = async () => {
      try {
        const s = await api.liveGrid?.snapshot?.();
        if (s) { setSnap(s); setError(false); }
      } catch { setError(true); }
    };
    fetchOnce();
    intervalRef.current = setInterval(fetchOnce, 30_000);
    clockRef.current = setInterval(() => setNow(new Date()), 1000);
    return () => {
      clearInterval(intervalRef.current);
      clearInterval(clockRef.current);
    };
  }, []);

  return (
    <div className="px2-tape">
      <span className="px2-tape-tag">● Live</span>
      <Stat label="Demand" value={fmt(snap?.demand_gw, 'GW')} />
      <Stat label="Wind"   value={fmt(snap?.wind_gw,   'GW')} />
      <Stat label="Solar"  value={fmt(snap?.solar_gw,  'GW')} />
      <Stat label="Carbon" value={fmt(snap?.carbon_intensity_gco2_per_kwh, 'gCO₂')} suffix={snap?.carbon_index} />
      <Stat label="Freq"   value={fmt(snap?.frequency_hz, 'Hz')} />
      <Stat label="Price"  value={fmt(snap?.price_gbp_per_mwh, '£/MWh', '£')} />
      {error && <span className="px2-tape-error">offline</span>}
      <span className="px2-tape-clock">{now.toLocaleTimeString('en-GB', {hour12:false})}</span>
    </div>
  );
}

function Stat({label, value, suffix}) {
  return (
    <span className="px2-tape-stat">
      <span className="px2-tape-stat-label">{label}</span>
      <span className="px2-tape-stat-value">{value}</span>
      {suffix ? <span className="px2-tape-stat-suffix">{String(suffix).toUpperCase()}</span> : null}
    </span>
  );
}

function fmt(v, unit, prefix = '') {
  if (v == null || Number.isNaN(v)) return '—';
  if (typeof v === 'number') {
    const n = Math.abs(v) >= 100 ? v.toFixed(0)
            : Math.abs(v) >= 10  ? v.toFixed(1)
            : v.toFixed(2);
    return `${prefix}${n} ${unit}`;
  }
  return `${prefix}${v} ${unit}`;
}
