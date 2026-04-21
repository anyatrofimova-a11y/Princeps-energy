/**
 * Princeps 3D Twin — ScaleReferences
 * ----------------------------------------------------------------------
 * Top-right 3-chip toggle: Human (1.7 m) / HGV (16 m) / Megapack (7 m).
 * When a chip is active, the next map click should drop a scale
 * reference at that world position. We publish this intent in two ways:
 *
 *   1. If `twinStore.addScaleReference` exists (sibling agent adds it),
 *      call it directly with `{ kind, position }`.
 *   2. Always fire a window CustomEvent `princeps:twin:scaleReference`
 *      with `{ kind, active }` that AssetInstancedLayer listens to.
 *
 * Sits below ViewModeTabs. Toggling the same chip deactivates it.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useTwinStore } from './stores/twinStore';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';

const CHIPS = [
  { kind: 'human', label: 'Human', size: '1.7 m' },
  { kind: 'hgv', label: 'HGV', size: '16 m' },
  { kind: 'megapack', label: 'Megapack', size: '7 m' },
];

export default function ScaleReferences({ style }) {
  const [active, setActive] = useState(null);

  // If the store grows an `addScaleReference` action in future, we can
  // pick it up opportunistically. Until then this is a no-op selector.
  const addScaleReferenceFn = useTwinStore((s) => s.addScaleReference);

  const toggle = useCallback((kind) => {
    setActive((prev) => (prev === kind ? null : kind));
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('princeps:twin:scaleReference', {
          detail: { kind: active, active: !!active },
        })
      );
    }
  }, [active]);

  // Bridge: allow external code (e.g. AssetInstancedLayer) to confirm a
  // placement at world coords; we forward to the store if available.
  useEffect(() => {
    const handler = (e) => {
      const detail = e.detail || {};
      if (!detail.kind || !detail.position) return;
      if (typeof addScaleReferenceFn === 'function') {
        try {
          addScaleReferenceFn({ kind: detail.kind, position: detail.position });
        } catch (err) {
          console.warn('[ScaleReferences] addScaleReference failed', err);
        }
      }
      // Auto-clear selection after drop
      setActive(null);
    };
    window.addEventListener('princeps:twin:scaleReferenceDrop', handler);
    return () => window.removeEventListener('princeps:twin:scaleReferenceDrop', handler);
  }, [addScaleReferenceFn]);

  return (
    <div
      role="group"
      aria-label="Scale references"
      style={{
        position: 'absolute',
        top: 56, // just under ViewModeTabs
        right: 16,
        display: 'flex',
        gap: 4,
        padding: 4,
        background: IVORY,
        border: `1px solid ${BORDER}`,
        borderRadius: 999,
        boxShadow: '0 2px 8px rgba(15, 19, 24, 0.06)',
        zIndex: 20,
        fontFamily: "'DM Sans', system-ui, sans-serif",
        ...style,
      }}
    >
      {CHIPS.map((c) => {
        const isActive = active === c.kind;
        return (
          <button
            key={c.kind}
            role="checkbox"
            aria-checked={isActive}
            onClick={() => toggle(c.kind)}
            title={`${c.label} \u00B7 ${c.size}`}
            style={{
              appearance: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '4px 10px',
              borderRadius: 999,
              fontSize: 11,
              fontWeight: isActive ? 600 : 500,
              background: isActive ? GOLD : 'transparent',
              color: isActive ? INK : MUTED,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              transition: 'background 120ms, color 120ms',
            }}
          >
            <span>{c.label}</span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 10,
                opacity: isActive ? 0.75 : 0.55,
              }}
            >
              {c.size}
            </span>
          </button>
        );
      })}
    </div>
  );
}
