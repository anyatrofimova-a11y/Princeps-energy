import React, { useState } from "react";

/**
 * Expandable dashboard card with hero metric + AI insight slot.
 *
 * Props:
 *   title       — card title
 *   accentColor — left border / header accent
 *   headerValue — hero metric shown in header (e.g. "87/120")
 *   aiInsight   — short AI-generated insight string
 *   defaultOpen — start expanded (default true)
 *   children    — expandable content
 */
export default function MetricCard({ title, accentColor = "var(--accent)", headerValue, aiInsight, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="metric-card floating-card-inner" style={{ borderLeft: `3px solid ${accentColor}` }}>
      <div className="metric-card-header" onClick={() => setOpen(o => !o)}>
        <div>
          <span className="metric-card-title">{title}</span>
          {headerValue && <span className="metric-card-hero">{headerValue}</span>}
        </div>
        <span className="metric-card-chevron">{open ? "\u25B4" : "\u25BE"}</span>
      </div>
      {aiInsight && (
        <div className="metric-card-insight">{aiInsight}</div>
      )}
      {open && (
        <div className="metric-card-content">
          {children}
        </div>
      )}
    </div>
  );
}
