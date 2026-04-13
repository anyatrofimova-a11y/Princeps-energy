import React, { useState } from "react";

const ACTIONS = [
  {
    type: "warning",
    title: "Grid capacity constraint — Slough POC",
    desc: "Substation headroom dropped below 40 MW threshold",
    action: "Review",
    priority: "high",
    intent: "grid_connection",
  },
  {
    type: "opportunity",
    title: "PPA rate improvement available",
    desc: "Renewable PPA rates down 6% — renegotiation window open",
    action: "Analyse",
    priority: "medium",
    intent: "financial",
  },
  {
    type: "info",
    title: "TCPA consultation response due",
    desc: "New data centre planning guidance — deadline 18 Apr",
    action: "Read",
    priority: "low",
    intent: "planning",
  },
];

const ICONS = {
  warning: (color) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 1.5L14.5 13H1.5L8 1.5Z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M8 6.5V9" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="8" cy="11" r="0.75" fill={color} />
    </svg>
  ),
  opportunity: (color) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M2 12L6 7L9 9.5L14 3" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.5 3H14V6.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  info: (color) => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <rect x="2.5" y="1.5" width="11" height="13" rx="1.5" stroke={color} strokeWidth="1.5" />
      <path d="M5.5 5.5H10.5M5.5 8H10.5M5.5 10.5H8.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
};

const PRIORITY_COLORS = {
  high: { icon: "#EA580C", bg: "rgba(234,88,12,0.06)", accent: "#EA580C" },
  medium: { icon: "#2563EB", bg: "rgba(37,99,235,0.06)", accent: "#2563EB" },
  low: { icon: "var(--gold-dark)", bg: "rgba(245,183,49,0.06)", accent: "var(--gold-dark)" },
};

function ActionItem({ item, index, onAction }) {
  const [hovered, setHovered] = useState(false);
  const cfg = PRIORITY_COLORS[item.priority];

  return (
    <div
      className="pd3-action-card"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        borderBottom: "1px solid var(--cds-layer-03, #EBEDF0)",
        animation: `pd-action-slide 0.3s ease both`,
        animationDelay: `${index * 60}ms`,
      }}
    >
      {/* Priority indicator */}
      <div style={{
        width: 34,
        height: 34,
        borderRadius: 8,
        background: cfg.bg,
        border: `1px solid ${hovered ? cfg.accent : "transparent"}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        transition: "border-color 0.2s ease, transform 0.2s ease",
        transform: hovered ? "scale(1.05)" : "scale(1)",
      }}>
        {ICONS[item.type](cfg.icon)}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13,
          fontWeight: 600,
          color: hovered ? "var(--ink)" : "var(--cds-text-primary)",
          transition: "color 0.15s",
        }}>
          {item.title}
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, lineHeight: 1.4 }}>
          {item.desc}
        </div>
      </div>

      {/* Action button */}
      <button
        onClick={(e) => { e.stopPropagation(); onAction?.(item.intent); }}
        style={{
        background: hovered ? "rgba(245,183,49,0.08)" : "transparent",
        border: `1px solid ${hovered ? "rgba(245,183,49,0.3)" : "transparent"}`,
        cursor: "pointer",
        fontSize: 12,
        fontWeight: 600,
        color: "var(--gold-dark)",
        padding: "6px 14px",
        borderRadius: 8,
        whiteSpace: "nowrap",
        fontFamily: "'DM Sans', sans-serif",
        transition: "all 0.2s ease",
        display: "flex",
        alignItems: "center",
        gap: 4,
      }}>
        {item.action}
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          style={{
            transition: "transform 0.2s ease",
            transform: hovered ? "translateX(2px)" : "translateX(0)",
          }}
        >
          <path d="M4.5 2.5L8 6L4.5 9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}

export default function ActionRow({ onAction }) {
  return (
    <div className="pd3-enter-3" style={{ padding: "0 24px", marginBottom: 16 }}>
      <div className="pd3-section-label">Recommended Actions</div>
      <div className="pd3-card" style={{ overflow: "hidden" }}>
        <div className="pd3-scan-line" />
        {ACTIONS.map((a, i) => (
          <ActionItem key={i} item={a} index={i} onAction={onAction} />
        ))}
      </div>
    </div>
  );
}
