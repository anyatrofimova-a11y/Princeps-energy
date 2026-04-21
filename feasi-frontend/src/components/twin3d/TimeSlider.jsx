/**
 * Princeps 3D Twin — TimeSlider
 * ----------------------------------------------------------------------
 * Bottom-docked 40-px horizontal slider, range 0..24 months. Reads/writes
 * `twinStore.timeMonth`. Labels the two ends: "month 0 pre-construction"
 * -> "month 24 operational". Includes auto-play at 1x / 2x / 5x.
 *
 * Phase bands (colour-coded stripe underneath the slider):
 *   0..2   enabling (brown)
 *   2..8   civils (grey)
 *   8..18  electrical (gold)
 *   18..24 commissioning (green)
 */

import React, { useEffect, useRef, useState, useMemo } from 'react';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';
const BROWN = '#8B6F47';
const GREY_CIVIL = '#9CA3AF';
const GREEN = '#16A34A';

const PHASES = [
  { key: 'enabling', from: 0, to: 2, color: BROWN, label: 'Enabling' },
  { key: 'civils', from: 2, to: 8, color: GREY_CIVIL, label: 'Civils' },
  { key: 'electrical', from: 8, to: 18, color: GOLD, label: 'Electrical' },
  { key: 'commissioning', from: 18, to: 24, color: GREEN, label: 'Commissioning' },
];

const SPEEDS = [1, 2, 5];

function phaseAt(month) {
  for (const p of PHASES) {
    if (month >= p.from && month <= p.to) return p;
  }
  return PHASES[PHASES.length - 1];
}

function endLabel(month) {
  if (month <= 0) return 'month 0 \u00B7 pre-construction';
  if (month >= 24) return 'month 24 \u00B7 operational';
  return null;
}

export default function TimeSlider({ style }) {
  const timeMonth = useTwinStore((s) => s.timeMonth);
  const setTimeMonth = useTwinStore((s) => s.setTimeMonth);

  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const rafRef = useRef(null);
  const lastTickRef = useRef(0);
  const accumRef = useRef(0);

  // Auto-play loop. Advances timeMonth by `speed` months per second.
  // Because the store rounds timeMonth to integers, we accumulate sub-month
  // deltas locally and only call setTimeMonth when a full month has elapsed.
  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      accumRef.current = 0;
      return;
    }
    lastTickRef.current = performance.now();
    accumRef.current = 0;
    const tick = (now) => {
      const dt = (now - lastTickRef.current) / 1000;
      lastTickRef.current = now;
      accumRef.current += dt * speed;
      if (accumRef.current >= 1) {
        const whole = Math.floor(accumRef.current);
        accumRef.current -= whole;
        const next = useTwinStore.getState().timeMonth + whole;
        if (next >= 24) {
          setTimeMonth(24);
          setPlaying(false);
          return;
        }
        setTimeMonth(next);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, speed, setTimeMonth]);

  const currentPhase = useMemo(() => phaseAt(timeMonth), [timeMonth]);
  const pct = (timeMonth / 24) * 100;
  const end = endLabel(timeMonth);

  return (
    <div
      style={{
        position: 'absolute',
        left: 80, // clear of left rail (16 + 48 + gap)
        right: 16,
        bottom: 16,
        height: 40,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '0 14px',
        background: IVORY,
        border: `1px solid ${BORDER}`,
        borderRadius: 10,
        boxShadow: '0 2px 8px rgba(15, 19, 24, 0.08)',
        zIndex: 18,
        fontFamily: "'DM Sans', system-ui, sans-serif",
        ...style,
      }}
    >
      {/* Play controls */}
      <button
        aria-label={playing ? 'Pause' : 'Play'}
        onClick={() => setPlaying((p) => !p)}
        style={{
          width: 26,
          height: 26,
          borderRadius: 999,
          border: 'none',
          cursor: 'pointer',
          background: playing ? GOLD : INK,
          color: playing ? INK : IVORY,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {playing ? <IconPause /> : <IconPlay />}
      </button>

      {/* Speed selector */}
      <div style={{ display: 'flex', gap: 2, flexShrink: 0 }}>
        {SPEEDS.map((s) => {
          const active = speed === s;
          return (
            <button
              key={s}
              aria-label={`${s}x speed`}
              onClick={() => setSpeed(s)}
              style={{
                minWidth: 26,
                height: 22,
                borderRadius: 4,
                border: 'none',
                cursor: 'pointer',
                background: active ? INK : 'transparent',
                color: active ? GOLD : MUTED,
                fontSize: 10,
                fontWeight: 600,
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                padding: '0 6px',
              }}
            >
              {s}x
            </button>
          );
        })}
      </div>

      {/* Track + range */}
      <div style={{ flex: 1, position: 'relative', height: 22, display: 'flex', alignItems: 'center' }}>
        {/* Phase bands */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            height: 6,
            top: '50%',
            transform: 'translateY(-50%)',
            borderRadius: 999,
            overflow: 'hidden',
            display: 'flex',
            background: '#E5E7EB',
          }}
        >
          {PHASES.map((p) => (
            <div
              key={p.key}
              title={`${p.label}: month ${p.from}\u2013${p.to}`}
              style={{
                width: `${((p.to - p.from) / 24) * 100}%`,
                background: p.color,
                opacity: 0.45,
              }}
            />
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={24}
          step={1}
          value={timeMonth}
          onChange={(e) => {
            setPlaying(false);
            setTimeMonth(parseFloat(e.target.value));
          }}
          aria-label="Construction month"
          style={{
            position: 'relative',
            width: '100%',
            accentColor: GOLD,
            background: 'transparent',
            zIndex: 2,
          }}
        />
      </div>

      {/* Readout */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          minWidth: 160,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 12,
            color: INK,
            fontWeight: 600,
          }}
        >
          month {Math.round(timeMonth)}
        </div>
        <div style={{ fontSize: 10, color: MUTED, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: currentPhase.color,
            }}
          />
          <span>{end || currentPhase.label.toLowerCase()}</span>
        </div>
      </div>

      {/* Progress-marker glow above the thumb, proportional */}
      <span aria-hidden style={{ position: 'absolute', left: `calc(${pct}% + 0px)`, top: -1, width: 0, height: 0 }} />
    </div>
  );
}

function IconPlay({ size = 10 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M7 4l14 8-14 8z" />
    </svg>
  );
}
function IconPause({ size = 10 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="4" width="4" height="16" />
      <rect x="14" y="4" width="4" height="16" />
    </svg>
  );
}
