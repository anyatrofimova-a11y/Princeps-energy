/**
 * Princeps 3D Twin — LayerRailRight
 * ----------------------------------------------------------------------
 * 320-px right rail (collapsible to 48 px). Ten groups matching the
 * layerVisibility keys on twinStore. Each group is collapsible and
 * contains layer rows with a toggle + opacity mini-slider.
 *
 * Opacity is stored locally (twinStore only tracks visibility). We emit
 * `princeps:twin:layerOpacity` window events for the renderer to
 * consume; opacity persists to `princeps.twin.layerOpacity`.
 *
 * Save-as-preset button at bottom writes the current visibility mask
 * (and opacity map) to `localStorage.princeps.twin.layerPresets`.
 */

import React, { useState, useCallback, useEffect } from 'react';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';
const SURFACE = '#FFFFFF';

const PRESETS_KEY = 'princeps.twin.layerPresets';
const OPACITY_KEY = 'princeps.twin.layerOpacity';
const COLLAPSED_KEY = 'princeps.twin.rightRailCollapsed';

// Group definition — layer keys must match twinStore.layerVisibility keys.
// Each group can contain multiple logical sub-layers for the renderer,
// but the store toggles on group-key granularity.
const GROUPS = [
  { key: 'site', label: 'Site', hint: 'Boundary, parcels, access' },
  { key: 'assets', label: 'Assets', hint: 'Megapacks, inverters, trackers' },
  { key: 'electrical', label: 'Electrical', hint: 'HV/LV cables, switchgear' },
  { key: 'civil', label: 'Civil', hint: 'Roads, foundations, drainage' },
  { key: 'grid', label: 'Grid', hint: 'DNO lines, substations, POC' },
  { key: 'context', label: 'Context', hint: 'Surroundings, buildings, terrain' },
  { key: 'constraints', label: 'Constraints', hint: 'Flood, SSSI, heritage, PROW' },
  { key: 'environment', label: 'Environment', hint: 'Canopy, hedges, water' },
  { key: 'overlays', label: 'Overlays', hint: 'Yield heatmap, shadow, NDVI' },
  { key: 'weather', label: 'Weather / Sun', hint: 'Irradiance, wind, shadow study' },
];

const readOpacity = () => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(OPACITY_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
};

const writeOpacity = (next) => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(OPACITY_KEY, JSON.stringify(next));
  } catch {}
};

const readCollapsed = () => {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
};

export default function LayerRailRight({ style }) {
  const layerVisibility = useTwinStore((s) => s.layerVisibility);
  const toggleLayer = useTwinStore((s) => s.toggleLayer);

  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [opened, setOpened] = useState(() => {
    const o = {};
    GROUPS.forEach((g) => { o[g.key] = true; });
    return o;
  });
  const [opacity, setOpacity] = useState(readOpacity);
  const [presetToast, setPresetToast] = useState(null);

  // Persist collapse
  useEffect(() => {
    try { window.localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0'); } catch {}
  }, [collapsed]);

  const onOpacityChange = useCallback((key, value) => {
    setOpacity((prev) => {
      const next = { ...prev, [key]: value };
      writeOpacity(next);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('princeps:twin:layerOpacity', {
          detail: { layerKey: key, opacity: value },
        }));
      }
      return next;
    });
  }, []);

  const savePreset = useCallback(() => {
    if (typeof window === 'undefined') return;
    let presets = [];
    try {
      const raw = window.localStorage.getItem(PRESETS_KEY);
      if (raw) presets = JSON.parse(raw);
    } catch { presets = []; }
    const now = new Date();
    const name = `Preset ${presets.length + 1} \u00B7 ${now.toLocaleDateString('en-GB')} ${now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
    presets.push({
      id: `preset_${Date.now()}`,
      name,
      createdAt: now.toISOString(),
      visibility: { ...layerVisibility },
      opacity: { ...opacity },
    });
    try {
      window.localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
      setPresetToast(`Saved \u201C${name}\u201D`);
      setTimeout(() => setPresetToast(null), 2200);
    } catch (err) {
      setPresetToast('Save failed');
      setTimeout(() => setPresetToast(null), 2200);
    }
  }, [layerVisibility, opacity]);

  if (collapsed) {
    return (
      <div
        style={{
          position: 'absolute',
          top: 72, // under ViewModeTabs
          right: 16,
          width: 48,
          background: IVORY,
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          boxShadow: '0 2px 8px rgba(15, 19, 24, 0.08)',
          padding: '8px 0',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 4,
          zIndex: 19,
          fontFamily: "'DM Sans', system-ui, sans-serif",
          ...style,
        }}
      >
        <button
          aria-label="Expand layers"
          onClick={() => setCollapsed(false)}
          style={collapseBtn(true)}
          title="Expand layers"
        >
          <IconLayers />
        </button>
      </div>
    );
  }

  return (
    <aside
      style={{
        position: 'absolute',
        top: 72,
        right: 16,
        bottom: 56, // leave room for time slider
        width: 320,
        background: IVORY,
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        boxShadow: '0 2px 12px rgba(15, 19, 24, 0.10)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 19,
        fontFamily: "'DM Sans', system-ui, sans-serif",
        color: INK,
        ...style,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 14px',
          borderBottom: `1px solid ${BORDER}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <IconLayers />
          <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 0.2 }}>Layers</span>
        </div>
        <button
          aria-label="Collapse rail"
          onClick={() => setCollapsed(true)}
          style={collapseBtn(false)}
          title="Collapse"
        >
          <IconChevronRight />
        </button>
      </div>

      {/* Groups */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {GROUPS.map((g) => {
          const visible = !!layerVisibility[g.key];
          const isOpen = opened[g.key];
          const op = opacity[g.key] != null ? opacity[g.key] : 1;
          return (
            <div key={g.key} style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '10px 14px',
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
                onClick={() => setOpened((o) => ({ ...o, [g.key]: !o[g.key] }))}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    background: visible ? GOLD : 'transparent',
                    border: `1px solid ${visible ? GOLD : BORDER}`,
                    display: 'inline-block',
                    flexShrink: 0,
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{g.label}</div>
                  <div style={{ fontSize: 10, color: MUTED, marginTop: 1 }}>{g.hint}</div>
                </div>
                <span style={{ color: MUTED, transform: isOpen ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 120ms' }}>
                  <IconChevronRight size={12} />
                </span>
              </div>

              {isOpen && (
                <div style={{ padding: '0 14px 12px 30px', background: SURFACE }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 0' }}>
                    <Toggle
                      checked={visible}
                      onChange={() => toggleLayer(g.key)}
                      ariaLabel={`Toggle ${g.label}`}
                    />
                    <span style={{ fontSize: 11, color: INK }}>Visible</span>
                  </label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                    <span style={{ fontSize: 10, color: MUTED, width: 48 }}>Opacity</span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={op}
                      disabled={!visible}
                      onChange={(e) => onOpacityChange(g.key, parseFloat(e.target.value))}
                      aria-label={`${g.label} opacity`}
                      style={{
                        flex: 1,
                        accentColor: GOLD,
                        opacity: visible ? 1 : 0.4,
                      }}
                    />
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: 10,
                        color: visible ? INK : MUTED,
                        width: 32,
                        textAlign: 'right',
                      }}
                    >
                      {Math.round(op * 100)}%
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer: save preset */}
      <div
        style={{
          padding: 10,
          borderTop: `1px solid ${BORDER}`,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <button
          onClick={savePreset}
          style={{
            flex: 1,
            height: 32,
            border: 'none',
            borderRadius: 8,
            background: GOLD,
            color: INK,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: "'DM Sans', system-ui, sans-serif",
          }}
        >
          Save as preset
        </button>
        {presetToast && (
          <span style={{ fontSize: 10, color: MUTED }}>{presetToast}</span>
        )}
      </div>
    </aside>
  );
}

function Toggle({ checked, onChange, ariaLabel }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={onChange}
      style={{
        width: 30,
        height: 16,
        borderRadius: 999,
        border: 'none',
        cursor: 'pointer',
        background: checked ? GOLD : '#D1D5DB',
        position: 'relative',
        transition: 'background 120ms',
        padding: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 2,
          left: checked ? 16 : 2,
          width: 12,
          height: 12,
          borderRadius: '50%',
          background: IVORY,
          transition: 'left 120ms',
          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
        }}
      />
    </button>
  );
}

function collapseBtn(collapsed) {
  return {
    width: 28,
    height: 28,
    border: 'none',
    borderRadius: 6,
    background: 'transparent',
    cursor: 'pointer',
    color: INK,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transform: collapsed ? 'rotate(180deg)' : 'none',
    transition: 'transform 120ms',
  };
}

function IconLayers({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3 2 8l10 5 10-5z" />
      <path d="M2 13l10 5 10-5" />
      <path d="M2 18l10 5 10-5" />
    </svg>
  );
}
function IconChevronRight({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
