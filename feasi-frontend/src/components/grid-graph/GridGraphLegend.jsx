/**
 * GridGraphLegend — persistent, collapsible colour legend for the
 * Grid Graph view.
 *
 * OWNED by BOT-GL. Positioned bottom-left of the map canvas (absolute).
 *
 * Three columns:
 *   1. Capacity RAG      — green >30% / amber 10-30% / red <10%
 *   2. Voltage class     — 400 / 275 / 132 / 66 / 33 / 11 kV
 *   3. Asset status      — Substation (circle) / TEC queue (triangle) /
 *                          REPD operational (square green) /
 *                          REPD consented (square amber) /
 *                          REPD application (square grey)
 *
 * When collapsed, renders a single "Legend" pill — clicking expands. State
 * is local; parent just mounts. A very short localStorage hand-shake
 * (`princeps-gridgraph-legend-collapsed`) remembers user preference
 * across navigations but never across accounts.
 *
 * NOTE: BOT-GC owns the actual palette. The colour hex values below are
 * DISPLAY-ONLY (what the user sees in the key) and MUST mirror whatever
 * BOT-GC defines. If/when BOT-GC exports a `paletteSpec`, swap to it here
 * — the public API of this component does not change.
 */
import React, { useCallback, useEffect, useState } from "react";

/* Light-gold palette surface to match the container. */
const C = {
  surface:      "rgba(255, 255, 255, 0.96)",
  surfaceSolid: "#ffffff",
  border:       "#e8e5df",
  borderSoft:   "#f0ece4",
  ink:          "#1a1a1a",
  inkDim:       "#4a4a4a",
  inkMuted:     "#9c9590",
  gold:         "#C9A64B",
  goldDark:     "#A88732",
  goldSoft:     "rgba(201,166,75,0.10)",
};

/* ─────────── Palette — mirrors BOT-GC semantics ─────────── */

/** Capacity RAG (headroom as % of firm capacity). */
const RAG = [
  { key: "green",  label: "> 30 % headroom",      colour: "#16a34a", sub: "Plenty of spare firm" },
  { key: "amber",  label: "10 – 30 % headroom",   colour: "#d97706", sub: "Marginal / watch" },
  { key: "red",    label: "< 10 % headroom",      colour: "#dc2626", sub: "Constrained" },
];

/** Voltage class — colour ramp used by BOT-GC on the map. */
const VOLTAGE = [
  { key: 400, label: "400 kV",  colour: "#ea580c" },  // orange-red
  { key: 275, label: "275 kV",  colour: "#f97316" },  // orange
  { key: 132, label: "132 kV",  colour: "#eab308" },  // yellow
  { key: 66,  label: "66 kV",   colour: "#fde047" },  // pale-yellow
  { key: 33,  label: "33 kV",   colour: "#06b6d4" },  // cyan
  { key: 11,  label: "11 kV",   colour: "#67e8f9" },  // pale-cyan
];

/** Asset status — marker shape + colour. */
const STATUS = [
  { key: "substation",  label: "Substation",        shape: "circle",   colour: C.inkDim },
  { key: "tec",         label: "TEC queue",         shape: "triangle", colour: "#7c3aed" },
  { key: "repd_op",     label: "REPD operational",  shape: "square",   colour: "#16a34a" },
  { key: "repd_cons",   label: "REPD consented",    shape: "square",   colour: "#d97706" },
  { key: "repd_app",    label: "REPD application",  shape: "square",   colour: "#94a3b8" },
];

/* ─────────── Shape primitives ─────────── */

function Swatch({ shape, colour, size = 12 }) {
  const s = size;
  if (shape === "triangle") {
    return (
      <svg width={s} height={s} viewBox="0 0 12 12" aria-hidden="true">
        <polygon points="6,1 11,11 1,11" fill={colour} stroke="rgba(0,0,0,0.08)" strokeWidth="0.75" />
      </svg>
    );
  }
  if (shape === "square") {
    return (
      <span style={{
        width: s, height: s,
        background: colour,
        border: "1px solid rgba(0,0,0,0.08)",
        borderRadius: 2,
        display: "inline-block",
        flexShrink: 0,
      }} />
    );
  }
  // default: circle
  return (
    <span style={{
      width: s, height: s, borderRadius: "50%",
      background: colour,
      border: "1px solid rgba(0,0,0,0.08)",
      display: "inline-block",
      flexShrink: 0,
    }} />
  );
}

/* ─────────── Styles ─────────── */
const S = {
  root: (expanded) => ({
    position: "absolute",
    bottom: 14,
    left: 14,
    zIndex: 6,
    background: C.surface,
    border: `1px solid ${C.border}`,
    borderRadius: 10,
    boxShadow: "0 4px 16px rgba(15, 23, 42, 0.08)",
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    color: C.ink,
    overflow: "hidden",
    backdropFilter: "blur(6px)",
    transition: "all 180ms ease",
    maxWidth: expanded ? 560 : 110,
  }),
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "8px 12px",
    borderBottom: `1px solid ${C.borderSoft}`,
    cursor: "pointer",
    userSelect: "none",
  },
  title: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.6,
    textTransform: "uppercase",
    color: C.inkDim,
  },
  toggle: {
    background: "transparent",
    border: "none",
    color: C.inkMuted,
    fontSize: 14,
    cursor: "pointer",
    lineHeight: 1,
    padding: 0,
    marginLeft: 8,
  },
  body: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr 1fr",
    gap: 0,
  },
  col: {
    padding: "10px 14px",
    borderRight: `1px solid ${C.borderSoft}`,
    minWidth: 150,
  },
  colLast: {
    padding: "10px 14px",
    minWidth: 150,
  },
  colTitle: {
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: 0.5,
    color: C.inkMuted,
    textTransform: "uppercase",
    marginBottom: 7,
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 5,
    fontSize: 11,
    lineHeight: 1.25,
  },
  rowLabel: {
    fontWeight: 600,
    color: C.ink,
    fontSize: 10.5,
  },
  rowSub: {
    color: C.inkMuted,
    fontSize: 9,
    marginLeft: 4,
  },
  pill: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 10px",
    cursor: "pointer",
    userSelect: "none",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.5,
    textTransform: "uppercase",
    color: C.goldDark,
  },
};

/* ─────────── Component ─────────── */

const LS_KEY = "princeps-gridgraph-legend-collapsed";

/**
 * @param {object=}  props
 * @param {boolean=} props.defaultCollapsed  — starting state if no LS entry
 * @param {object=}  props.style            — escape hatch for positioning
 */
export default function GridGraphLegend({ defaultCollapsed = false, style = {} } = {}) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return defaultCollapsed;
    try {
      const v = window.localStorage.getItem(LS_KEY);
      if (v === "1") return true;
      if (v === "0") return false;
    } catch { /* ignore */ }
    return defaultCollapsed;
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    try { window.localStorage.setItem(LS_KEY, collapsed ? "1" : "0"); } catch { /* ignore */ }
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed(v => !v), []);

  // Collapsed pill
  if (collapsed) {
    return (
      <div
        style={{ ...S.root(false), ...style }}
        role="region"
        aria-label="Grid graph legend (collapsed)"
      >
        <div
          style={S.pill}
          onClick={toggle}
          tabIndex={0}
          role="button"
          aria-expanded="false"
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
        >
          <Swatch shape="circle" colour={C.gold} size={8} />
          <span>Legend</span>
        </div>
      </div>
    );
  }

  // Expanded three-column legend
  return (
    <div
      style={{ ...S.root(true), ...style }}
      role="region"
      aria-label="Grid graph legend"
    >
      <div style={S.header} onClick={toggle} tabIndex={0} role="button" aria-expanded="true"
           onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>
        <span style={S.title}>Legend</span>
        <button
          style={S.toggle}
          aria-label="Collapse legend"
          onClick={(e) => { e.stopPropagation(); toggle(); }}
        >−</button>
      </div>

      <div style={S.body}>
        {/* Column 1 — Capacity RAG */}
        <div style={S.col}>
          <div style={S.colTitle}>Capacity headroom</div>
          {RAG.map(r => (
            <div key={r.key} style={S.row}>
              <Swatch shape="circle" colour={r.colour} />
              <div>
                <div style={S.rowLabel}>{r.label}</div>
                <div style={S.rowSub}>{r.sub}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Column 2 — Voltage class */}
        <div style={S.col}>
          <div style={S.colTitle}>Voltage class</div>
          {VOLTAGE.map(v => (
            <div key={v.key} style={S.row}>
              <Swatch shape="circle" colour={v.colour} />
              <span style={S.rowLabel}>{v.label}</span>
            </div>
          ))}
        </div>

        {/* Column 3 — Asset status */}
        <div style={S.colLast}>
          <div style={S.colTitle}>Asset status</div>
          {STATUS.map(s => (
            <div key={s.key} style={S.row}>
              <Swatch shape={s.shape} colour={s.colour} />
              <span style={S.rowLabel}>{s.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
