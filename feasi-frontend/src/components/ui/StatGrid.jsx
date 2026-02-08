import React from "react";

/**
 * Reusable stat grid layout.
 *
 * Props:
 *   columns — 2 (default) or 3
 *   children — arbitrary content
 */
export default function StatGrid({ columns = 2, children }) {
  return (
    <div className={`stat-grid${columns === 3 ? " three" : ""}`}>
      {children}
    </div>
  );
}

/**
 * Single stat display: <Stat label="Peak" value="42 GW" color="#f44336" />
 */
export function Stat({ label, value, color }) {
  return (
    <div>
      {label}: <strong style={color ? { color } : undefined}>{value}</strong>
    </div>
  );
}
