/**
 * Princeps 3D Twin — SunSlider
 * ----------------------------------------------------------------------
 * Renders only when `twinStore.activeTool === 'sun'`. Combines a date
 * picker and a time slider (00:00 -> 23:59) that write back to
 * `twinStore.setSunDate`. Also shows a live readout of azimuth and
 * altitude computed from lat/lon (defaults to central UK — 52.5N, -1.5W).
 *
 * Azimuth/altitude maths is a lightweight NOAA approximation; fine for
 * chrome display. The renderer owns the authoritative shadow polygon
 * layer and will use the same sun date.
 */

import React, { useMemo } from 'react';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';

// Default site location (central England). Site context can override via prop.
const DEFAULT_LAT = 52.5;
const DEFAULT_LON = -1.5;

function pad2(n) {
  return n < 10 ? `0${n}` : String(n);
}

function formatDateInput(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function minutesOfDay(d) {
  return d.getHours() * 60 + d.getMinutes();
}

function formatHM(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${pad2(h)}:${pad2(m)}`;
}

// NOAA-style sun position (simplified). Inputs: date (JS), lat/lon degrees.
// Returns azimuth (degrees clockwise from north) and altitude (degrees).
function sunPosition(date, lat, lon) {
  const rad = Math.PI / 180;
  const deg = 180 / Math.PI;
  // Julian date
  const jd = date.getTime() / 86400000 + 2440587.5;
  const n = jd - 2451545.0;
  const L = (280.460 + 0.9856474 * n) % 360;
  const g = ((357.528 + 0.9856003 * n) % 360) * rad;
  const lambda = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const epsilon = (23.439 - 0.0000004 * n) * rad;
  const ra = Math.atan2(Math.cos(epsilon) * Math.sin(lambda), Math.cos(lambda));
  const dec = Math.asin(Math.sin(epsilon) * Math.sin(lambda));
  // Greenwich mean sidereal time (hours)
  const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
  const lst = ((gmst * 15 + lon) % 360) * rad;
  let H = lst - ra;
  // Local hour angle
  const latRad = lat * rad;
  const altitude = Math.asin(
    Math.sin(latRad) * Math.sin(dec) + Math.cos(latRad) * Math.cos(dec) * Math.cos(H)
  );
  const azimuth = Math.atan2(
    -Math.sin(H),
    Math.tan(dec) * Math.cos(latRad) - Math.sin(latRad) * Math.cos(H)
  );
  let azDeg = (azimuth * deg + 360) % 360;
  return { azimuth: azDeg, altitude: altitude * deg };
}

export default function SunSlider({ lat = DEFAULT_LAT, lon = DEFAULT_LON, style }) {
  const activeTool = useTwinStore((s) => s.activeTool);
  const sunDate = useTwinStore((s) => s.sunDate);
  const setSunDate = useTwinStore((s) => s.setSunDate);

  const mins = minutesOfDay(sunDate);
  const dateStr = formatDateInput(sunDate);

  const onDateChange = (iso) => {
    if (!iso) return;
    const [y, m, d] = iso.split('-').map((s) => parseInt(s, 10));
    if (!y || !m || !d) return;
    const next = new Date(sunDate);
    next.setFullYear(y, m - 1, d);
    setSunDate(next);
  };

  const onTimeChange = (value) => {
    const v = Math.max(0, Math.min(1439, parseInt(value, 10)));
    const h = Math.floor(v / 60);
    const m = v % 60;
    const next = new Date(sunDate);
    next.setHours(h, m, 0, 0);
    setSunDate(next);
  };

  const pos = useMemo(() => sunPosition(sunDate, lat, lon), [sunDate, lat, lon]);
  const below = pos.altitude < 0;

  if (activeTool !== 'sun') return null;

  return (
    <div
      role="region"
      aria-label="Sun study"
      style={{
        position: 'absolute',
        left: 80, // clear of left rail
        bottom: 64, // sits above TimeSlider
        width: 360,
        background: IVORY,
        border: `1px solid ${BORDER}`,
        borderRadius: 10,
        boxShadow: '0 2px 12px rgba(15, 19, 24, 0.10)',
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        zIndex: 22,
        fontFamily: "'DM Sans', system-ui, sans-serif",
        color: INK,
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              background: GOLD,
              boxShadow: '0 0 8px rgba(245, 183, 49, 0.6)',
            }}
          />
          <span style={{ fontSize: 12, fontWeight: 600 }}>Sun study</span>
        </div>
        <span
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10,
            color: MUTED,
          }}
        >
          {`${lat.toFixed(2)}\u00B0N ${lon.toFixed(2)}\u00B0E`}
        </span>
      </div>

      {/* Date + time controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="date"
          value={dateStr}
          onChange={(e) => onDateChange(e.target.value)}
          aria-label="Sun study date"
          style={{
            flex: '0 0 auto',
            padding: '5px 8px',
            borderRadius: 6,
            border: `1px solid ${BORDER}`,
            fontSize: 11,
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            background: '#FFFFFF',
            color: INK,
          }}
        />
        <span
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 11,
            color: INK,
            minWidth: 46,
            textAlign: 'center',
          }}
        >
          {formatHM(mins)}
        </span>
      </div>

      <div>
        <input
          type="range"
          min={0}
          max={1439}
          step={5}
          value={mins}
          onChange={(e) => onTimeChange(e.target.value)}
          aria-label="Time of day"
          style={{ width: '100%', accentColor: GOLD }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: MUTED, fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>23:59</span>
        </div>
      </div>

      {/* Azimuth / altitude readout */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          marginTop: 2,
        }}
      >
        <Readout label="Azimuth" value={`${pos.azimuth.toFixed(1)}\u00B0`} />
        <Readout
          label="Altitude"
          value={`${pos.altitude.toFixed(1)}\u00B0`}
          warn={below}
          hint={below ? 'below horizon' : null}
        />
      </div>
    </div>
  );
}

function Readout({ label, value, warn, hint }) {
  return (
    <div
      style={{
        flex: 1,
        padding: '8px 10px',
        borderRadius: 8,
        background: '#FFFFFF',
        border: `1px solid ${BORDER}`,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <span style={{ fontSize: 10, color: MUTED, letterSpacing: 0.3, textTransform: 'uppercase' }}>
        {label}
      </span>
      <span
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: warn ? MUTED : INK,
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        }}
      >
        {value}
      </span>
      {hint && <span style={{ fontSize: 9, color: MUTED }}>{hint}</span>}
    </div>
  );
}
