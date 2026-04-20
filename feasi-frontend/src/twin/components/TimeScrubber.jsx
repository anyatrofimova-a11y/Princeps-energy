/**
 * TimeScrubber — shared 2020-2050 timeline control.
 *
 * Drives the TimeContext. All time-aware layers listen via useTime().
 * Debouncing lives in the context (250 ms) so this component can emit
 * scrub events at native input rate without saturating re-renders.
 *
 * Renders as a 44px-tall strip. Keep styling minimal / inline — Princeps
 * Gold palette (#D4A018). Caller positions it (e.g. absolute bottom).
 */

import React, { useMemo } from "react";
import { useTime, PATHWAYS, MIN_YEAR, MAX_YEAR, HISTORICAL_CUTOFF } from "../state/time_context.jsx";

function formatTs(ms, granularity) {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  if (granularity === "year") return String(y);
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  if (granularity === "day") return `${y}-${m}-${dd}`;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${y}-${m}-${dd} ${hh}:${mm}Z`;
}

const STRIP_STYLE = {
  position: "relative",
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "6px 12px",
  height: 44,
  background: "rgba(14,14,14,0.88)",
  color: "#e7dcb8",
  fontFamily: "ui-monospace, Menlo, monospace",
  fontSize: 11,
  borderTop: "1px solid #2a2a2a",
  borderRadius: 4,
  boxShadow: "0 -2px 12px rgba(0,0,0,0.35)",
  userSelect: "none",
};

const BTN = {
  background: "transparent",
  border: "1px solid #3a3a3a",
  color: "#e7dcb8",
  padding: "3px 8px",
  fontSize: 10.5,
  borderRadius: 3,
  cursor: "pointer",
  fontFamily: "inherit",
};

const PILL_LIVE = { ...BTN, background: "#D4A018", color: "#0a0a0a", borderColor: "#D4A018" };

export default function TimeScrubber({
  style = {},
  showPathwaySelector = true,
  granularity = "auto", // "auto" | "year" | "day" | "datetime"
}) {
  const t = useTime();

  // Choose a natural rendering granularity
  const effGranularity = granularity === "auto"
    ? (t.isLive ? "datetime" : "year")
    : granularity;

  // Slider operates in year + fractional-year space to keep UX simple.
  const yearFloat = useMemo(() => {
    const d = new Date(t.timestamp);
    const start = Date.UTC(d.getUTCFullYear(), 0, 1);
    const next = Date.UTC(d.getUTCFullYear() + 1, 0, 1);
    return d.getUTCFullYear() + (t.timestamp - start) / (next - start);
  }, [t.timestamp]);

  const onSlider = (e) => {
    const yf = Number(e.target.value);
    const y = Math.floor(yf);
    const frac = yf - y;
    const start = Date.UTC(y, 0, 1);
    const next = Date.UTC(y + 1, 0, 1);
    const ms = Math.round(start + frac * (next - start));
    t.setTimestamp(ms);
  };

  const isProjection = t.year > HISTORICAL_CUTOFF;

  return (
    <div className="princeps-time-scrubber" style={{ ...STRIP_STYLE, ...style }}>
      <button
        type="button"
        style={t.isLive ? PILL_LIVE : BTN}
        onClick={() => t.setLive(!t.isLive)}
        title={t.isLive ? "Currently tracking wall clock — click to pin" : "Resume live"}
      >
        {t.isLive ? "● LIVE" : "⏸ PINNED"}
      </button>

      <span style={{ color: "#8a8472", minWidth: 128 }}>
        {formatTs(t.timestamp, effGranularity)}
      </span>

      <input
        type="range"
        min={MIN_YEAR}
        max={MAX_YEAR}
        step={0.02}
        value={yearFloat}
        onChange={onSlider}
        style={{ flex: 1, accentColor: "#D4A018", minWidth: 120 }}
        aria-label="Timeline year scrubber"
      />

      <span style={{ color: isProjection ? "#D4A018" : "#7a7363", minWidth: 78, textAlign: "right" }}>
        {isProjection ? `PROJ ${t.year}` : `HIST ${t.year}`}
      </span>

      {showPathwaySelector && isProjection && (
        <select
          value={t.pathway}
          onChange={(e) => t.setPathway(e.target.value)}
          style={{
            ...BTN,
            padding: "3px 6px",
            cursor: "pointer",
            background: "#161410",
          }}
          aria-label="FES pathway"
        >
          {PATHWAYS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      )}

      <button
        type="button"
        style={BTN}
        onClick={() => t.setYear(HISTORICAL_CUTOFF)}
        title="Jump to 2024 (historical/projection boundary)"
      >
        ⧖ 2024
      </button>
      <button
        type="button"
        style={BTN}
        onClick={() => t.setYear(2030)}
        title="Jump to 2030"
      >
        2030
      </button>
      <button
        type="button"
        style={BTN}
        onClick={() => t.setYear(2050)}
        title="Jump to 2050"
      >
        2050
      </button>
    </div>
  );
}
