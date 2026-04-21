/**
 * DnoFilterPills — pill rail that drives useDnoFilter.
 *
 * Layout: horizontal row of 8 pills — [All] [UKPN] [SSEN] [SPEN] [NGED] [NPG]
 *                                      [ENWL] [NIE].
 *
 * Interaction model
 * ─────────────────
 *   • Click on DNO pill      → solo that slug (clears others).
 *   • Shift-click DNO pill   → toggle that slug in/out of the filter set
 *                              (multi-select).
 *   • Double-click DNO pill  → solo that slug, same as single click but sets
 *                              mode='solo' explicitly (used by the map to
 *                              zoom onto a DNO).
 *   • Click 'All' pill       → clear the filter (mode='all').
 *
 * Keyboard shortcuts
 * ──────────────────
 *   G           — focus the first pill (rail "gateway").
 *   0           — All
 *   1..7        — UKPN, SSEN, SPEN, NGED, NPG, ENWL, NIE (solo)
 *   shift+1..7  — toggle
 *
 * Active pills render in the Princeps gold accent (var(--accent)) with the
 * DNO's own palette colour on the left border as a 2px rail — this keeps
 * palette recognition even when the gold dominates.
 */

import React, { useEffect, useMemo, useRef } from "react";
import palette from "../../data/dno-palette.json";
import useDnoFilter, { DNO_SLUGS } from "../../hooks/useDnoFilter";

// Digit → slug map for keyboard shortcuts.
const DIGIT_TO_SLUG = Object.freeze({
  "1": "ukpn",
  "2": "ssen",
  "3": "spen",
  "4": "nged",
  "5": "npg",
  "6": "enwl",
  "7": "nie",
});

// ── Styles ─────────────────────────────────────────────────────────────────
// Inline to avoid yet another CSS module for one rail; the palette drives
// per-pill colour so a static CSS would need 7 overrides anyway.

const wrapStyle = {
  display:      "flex",
  alignItems:   "center",
  gap:          6,
  padding:      "6px 10px",
  background:   "rgba(20, 20, 22, 0.72)",
  border:       "1px solid rgba(255, 255, 255, 0.08)",
  borderRadius: 10,
  backdropFilter: "blur(6px)",
  WebkitBackdropFilter: "blur(6px)",
  font: "12px/1.1 ui-sans-serif, system-ui, sans-serif",
  color: "rgba(255, 255, 255, 0.85)",
  userSelect: "none",
  pointerEvents: "auto",
};

function pillStyle({ active, accent, isAllPill }) {
  return {
    display:       "inline-flex",
    alignItems:    "center",
    gap:           6,
    padding:       "4px 10px 4px 8px",
    borderRadius:  999,
    cursor:        "pointer",
    whiteSpace:    "nowrap",
    border:        active
      ? "1px solid var(--accent, #F5B731)"
      : "1px solid rgba(255,255,255,0.14)",
    background: active
      ? "rgba(245, 183, 49, 0.16)"
      : "rgba(255, 255, 255, 0.04)",
    color: active
      ? "var(--accent, #F5B731)"
      : "rgba(255, 255, 255, 0.82)",
    boxShadow: active
      ? "0 0 0 2px rgba(245, 183, 49, 0.18) inset"
      : "none",
    // Left dot: palette colour swatch (hidden on the 'All' pill).
    "--dot": isAllPill ? "transparent" : (accent || "#666"),
    transition: "background 140ms ease, color 140ms ease, box-shadow 140ms ease",
    fontWeight: active ? 600 : 500,
  };
}

const dotStyle = {
  width:  8,
  height: 8,
  borderRadius: "50%",
  background:   "var(--dot)",
  boxShadow:    "0 0 0 1px rgba(0,0,0,0.35)",
  flex: "none",
};

// ── Component ──────────────────────────────────────────────────────────────
export default function DnoFilterPills({ compact = false }) {
  const { activeDnos, mode, solo, toggle, clear } = useDnoFilter();
  const containerRef = useRef(null);

  // Pre-compute pill definitions so the DOM list is stable.
  const pills = useMemo(() => {
    return [
      { slug: "__all__", label: "All", shortLabel: "All", accent: null, isAllPill: true },
      ...DNO_SLUGS.map((slug) => {
        const p = palette[slug] || {};
        return {
          slug,
          label: p.label || slug.toUpperCase(),
          shortLabel: slug.toUpperCase(),
          accent: p.accent,
          isAllPill: false,
        };
      }),
    ];
  }, []);

  const isActive = (slug) => {
    if (slug === "__all__") return mode === "all" && activeDnos.size === 0;
    return activeDnos.has(slug);
  };

  const handlePillClick = (e, slug) => {
    if (slug === "__all__") {
      clear();
      return;
    }
    if (e.shiftKey) {
      toggle(slug);
    } else {
      solo(slug);
    }
  };

  const handlePillDoubleClick = (e, slug) => {
    if (slug === "__all__") return;
    e.preventDefault();
    solo(slug);
  };

  // Keyboard shortcuts — global (document-level).
  useEffect(() => {
    function onKey(e) {
      // Ignore when user is typing in an input / textarea / contentEditable.
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || e.target?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "g" || e.key === "G") {
        // Focus first button in the rail.
        const firstBtn = containerRef.current?.querySelector("button");
        if (firstBtn) { firstBtn.focus(); e.preventDefault(); }
        return;
      }

      if (e.key === "0") {
        clear();
        e.preventDefault();
        return;
      }

      const slug = DIGIT_TO_SLUG[e.key];
      if (slug) {
        if (e.shiftKey) toggle(slug); else solo(slug);
        e.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clear, solo, toggle]);

  return (
    <div
      ref={containerRef}
      role="toolbar"
      aria-label="DNO licence-area filter"
      style={wrapStyle}
      data-dno-mode={mode}
    >
      {pills.map((p) => {
        const active = isActive(p.slug);
        return (
          <button
            key={p.slug}
            type="button"
            role="switch"
            aria-checked={active}
            aria-label={
              p.isAllPill
                ? "Show all DNOs"
                : `${p.label}${active ? " (active)" : ""} — shift-click to multi-select`
            }
            title={p.label}
            style={pillStyle({ active, accent: p.accent, isAllPill: p.isAllPill })}
            onClick={(e) => handlePillClick(e, p.slug)}
            onDoubleClick={(e) => handlePillDoubleClick(e, p.slug)}
          >
            {!p.isAllPill && <span style={dotStyle} aria-hidden="true" />}
            <span>{compact ? p.shortLabel : p.label}</span>
          </button>
        );
      })}
    </div>
  );
}
