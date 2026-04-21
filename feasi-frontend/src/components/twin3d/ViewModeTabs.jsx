/**
 * Princeps 3D Twin — ViewModeTabs
 * ----------------------------------------------------------------------
 * Top-right pill tabs: Plan / Oblique / Construction / Drone.
 * Reads `viewMode` from twinStore. Gold active state.
 * Keyboard: Cmd/Ctrl + 1..4 switches mode.
 *
 * Sibling deck.gl renderer (TwinRoot) reacts to viewMode changes via
 * store subscription — this component is pure chrome.
 */

import React, { useEffect, useMemo } from 'react';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';

const MODES = [
  { id: 'plan', label: 'Plan', shortcut: '1' },
  { id: 'oblique', label: 'Oblique', shortcut: '2' },
  { id: 'construction', label: 'Construction', shortcut: '3' },
  { id: 'drone', label: 'Drone', shortcut: '4' },
];

export default function ViewModeTabs({ style }) {
  const viewMode = useTwinStore((s) => s.viewMode);
  const setViewMode = useTwinStore((s) => s.setViewMode);

  useEffect(() => {
    const handler = (e) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      // skip when user is typing
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;
      const idx = ['1', '2', '3', '4'].indexOf(e.key);
      if (idx < 0) return;
      e.preventDefault();
      setViewMode(MODES[idx].id);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setViewMode]);

  const containerStyle = useMemo(() => ({
    position: 'absolute',
    top: 16,
    right: 16,
    display: 'flex',
    gap: 4,
    padding: 4,
    background: IVORY,
    border: `1px solid ${BORDER}`,
    borderRadius: 999,
    boxShadow: '0 2px 8px rgba(15, 19, 24, 0.08)',
    fontFamily: "'DM Sans', system-ui, sans-serif",
    zIndex: 20,
    ...style,
  }), [style]);

  return (
    <div role="tablist" aria-label="3D twin view mode" style={containerStyle}>
      {MODES.map((m) => {
        const active = viewMode === m.id;
        return (
          <button
            key={m.id}
            role="tab"
            aria-selected={active}
            onClick={() => setViewMode(m.id)}
            title={`${m.label} (\u2318${m.shortcut})`}
            style={{
              appearance: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '6px 14px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: active ? 600 : 500,
              letterSpacing: 0.2,
              background: active ? GOLD : 'transparent',
              color: active ? INK : MUTED,
              transition: 'background 120ms ease, color 120ms ease',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>{m.label}</span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 10,
                opacity: active ? 0.7 : 0.5,
                padding: '1px 4px',
                borderRadius: 3,
                background: active ? 'rgba(15,19,24,0.12)' : 'transparent',
                border: active ? 'none' : `1px solid ${BORDER}`,
              }}
            >
              {'\u2318'}{m.shortcut}
            </span>
          </button>
        );
      })}
    </div>
  );
}
