import React from "react";

/**
 * Reusable bar chart with tooltips.
 *
 * Props:
 *   data       — array of numbers
 *   labels     — optional array of label strings (shown below bars)
 *   colors     — string | (value, index) => string
 *   height     — "small" (36px) or default (50px)
 *   tooltip    — (value, index) => string
 *   minHeight  — min pixel height for non-zero bars (default 2)
 *   opacity    — (value, index) => number (optional per-bar opacity)
 */
export default function BarChart({ data = [], labels, colors = "#4caf50", height, tooltip, minHeight = 2, opacity }) {
  if (!data.length) return null;
  const max = Math.max(...data.map(v => Math.max(v, 0))) || 1;
  const colorFn = typeof colors === "function" ? colors : () => colors;

  return (
    <>
      <div className={`bar-chart${height === "small" ? " small" : ""}`}>
        {data.map((v, i) => {
          const val = Math.max(v, 0);
          const style = {
            height: `${(val / max) * 100}%`,
            background: colorFn(v, i),
            minHeight: v > 0 ? minHeight : 0,
          };
          if (opacity) style.opacity = opacity(v, i);
          return (
            <div key={i} className="bar" title={tooltip ? tooltip(v, i) : String(v)} style={style} />
          );
        })}
      </div>
      {labels && (
        <div className="bar-labels">
          {labels.map((l, i) => <span key={i}>{l}</span>)}
        </div>
      )}
    </>
  );
}
