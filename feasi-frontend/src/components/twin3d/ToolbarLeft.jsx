/**
 * Princeps 3D Twin — ToolbarLeft
 * ----------------------------------------------------------------------
 * 48-px left rail with 10 icon buttons. Dispatches to `twinStore.setTool`
 * for tools the store understands (measure/annotate/section/sun/snapshot),
 * and fires window CustomEvents for chrome-only tools (grid/scale/export/
 * reset/help) that sibling renderer or app shell listens to.
 *
 * Keyboard shortcuts:
 *   G grid · M measure · A annotate · S section · U sun · R scale
 *   P snapshot · E export · Esc reset · ? help
 *
 * Active tool renders gold-on-ink. Radix Popover tooltips show labels +
 * keyboard hints on hover.
 */

import React, { useEffect, useCallback } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';

// Tools that the twinStore's setTool knows about
const STORE_TOOLS = new Set(['measure', 'annotate', 'section', 'sun', 'snapshot']);

const TOOLS = [
  { id: 'grid', label: 'Grid', key: 'g', icon: IconGrid },
  { id: 'measure', label: 'Measure', key: 'm', icon: IconMeasure },
  { id: 'annotate', label: 'Annotate', key: 'a', icon: IconAnnotate },
  { id: 'section', label: 'Section cut', key: 's', icon: IconSection },
  { id: 'sun', label: 'Sun study', key: 'u', icon: IconSun },
  { id: 'scale', label: 'Scale reference', key: 'r', icon: IconScale },
  { id: 'snapshot', label: 'Snapshot', key: 'p', icon: IconCamera },
  { id: 'export', label: 'Export GA', key: 'e', icon: IconExport },
  { id: 'reset', label: 'Reset view', key: 'Esc', icon: IconReset },
  { id: 'help', label: 'Help', key: '?', icon: IconHelp },
];

const emit = (name, detail = {}) => {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(name, { detail }));
};

export default function ToolbarLeft({ style }) {
  const activeTool = useTwinStore((s) => s.activeTool);
  const setTool = useTwinStore((s) => s.setTool);

  const dispatch = useCallback((toolId) => {
    if (toolId === 'reset') {
      setTool(null);
      emit('princeps:twin:reset');
      return;
    }
    if (toolId === 'help') {
      emit('princeps:twin:help');
      return;
    }
    if (toolId === 'export') {
      emit('princeps:twin:export');
      return;
    }
    if (toolId === 'grid') {
      emit('princeps:twin:toggleGrid');
      return;
    }
    if (toolId === 'scale') {
      // Scale chip row is a separate component; this button toggles its visibility
      emit('princeps:twin:toggleScaleChips');
      return;
    }
    if (STORE_TOOLS.has(toolId)) {
      // toggle: click active tool again to deactivate
      setTool(activeTool === toolId ? null : toolId);
    }
  }, [activeTool, setTool]);

  useEffect(() => {
    const handler = (e) => {
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        dispatch('reset');
        return;
      }
      if (e.key === '?') {
        e.preventDefault();
        dispatch('help');
        return;
      }
      const key = e.key.toLowerCase();
      const hit = TOOLS.find((t) => t.key.toLowerCase() === key);
      if (hit) {
        e.preventDefault();
        dispatch(hit.id);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [dispatch]);

  const railStyle = {
    position: 'absolute',
    top: 16,
    bottom: 16,
    left: 16,
    width: 48,
    background: IVORY,
    border: `1px solid ${BORDER}`,
    borderRadius: 12,
    boxShadow: '0 2px 8px rgba(15, 19, 24, 0.08)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '8px 0',
    gap: 2,
    zIndex: 20,
    fontFamily: "'DM Sans', system-ui, sans-serif",
    ...style,
  };

  return (
    <div role="toolbar" aria-orientation="vertical" aria-label="3D twin tools" style={railStyle}>
      {TOOLS.map((t, idx) => {
        const active = activeTool === t.id;
        return (
          <React.Fragment key={t.id}>
            {idx === 7 ? <Divider /> : null}
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  aria-label={t.label}
                  aria-pressed={active}
                  onClick={() => dispatch(t.id)}
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    border: 'none',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: active ? INK : 'transparent',
                    color: active ? GOLD : INK,
                    transition: 'background 100ms ease, color 100ms ease',
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.background = 'rgba(15,19,24,0.05)';
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <t.icon size={18} />
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  side="right"
                  sideOffset={8}
                  style={{
                    background: INK,
                    color: IVORY,
                    padding: '6px 10px',
                    borderRadius: 6,
                    fontSize: 11,
                    fontFamily: "'DM Sans', system-ui, sans-serif",
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
                    zIndex: 100,
                  }}
                >
                  <span>{t.label}</span>
                  <kbd
                    style={{
                      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                      fontSize: 10,
                      padding: '1px 5px',
                      borderRadius: 3,
                      background: 'rgba(245, 183, 49, 0.2)',
                      color: GOLD,
                      border: `1px solid ${GOLD}`,
                    }}
                  >
                    {t.key}
                  </kbd>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function Divider() {
  return (
    <div
      style={{
        width: 24,
        height: 1,
        background: BORDER,
        margin: '4px 0',
      }}
    />
  );
}

// ---------------- Minimal inline SVG icons ----------------
// Line-only, 18px default, currentColor. Kept local so this file has
// zero icon-library dependencies.

function IconGrid({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  );
}
function IconMeasure({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 17 17 3l4 4L7 21z" />
      <path d="M7 13l2 2M10 10l2 2M13 7l2 2" />
    </svg>
  );
}
function IconAnnotate({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 4h14v12H9l-4 4z" />
      <path d="M8 9h8M8 12h5" />
    </svg>
  );
}
function IconSection({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 12h16" strokeDasharray="2 2" />
      <path d="M6 6h12v12H6z" />
    </svg>
  );
}
function IconSun({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
    </svg>
  );
}
function IconScale({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v6M8 5l4-2 4 2M6 14h12l-2 6H8z" />
    </svg>
  );
}
function IconCamera({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7h4l2-2h4l2 2h4v12H4z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}
function IconExport({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 4v11M8 8l4-4 4 4" />
      <path d="M5 17v3h14v-3" />
    </svg>
  );
}
function IconReset({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 10a8 8 0 0 1 14-4" />
      <path d="M18 3v4h-4" />
      <path d="M20 14a8 8 0 0 1-14 4" />
      <path d="M6 21v-4h4" />
    </svg>
  );
}
function IconHelp({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 .9-1 1.7v.5" />
      <path d="M12 17v.01" />
    </svg>
  );
}
