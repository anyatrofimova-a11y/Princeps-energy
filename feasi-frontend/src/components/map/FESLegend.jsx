/**
 * FESLegend — tiny on-map explainer so the user knows what the
 * (year × pathway) controls are actually doing.
 *
 * Appears bottom-right, above the live strip. It reads the current scrubber
 * state from `useMapTime` and the FES pathway from the same store, so it
 * stays in sync automatically.
 *
 * Intentionally unopinionated about the layers themselves — it just tells
 * the user: "here is the scenario, here is the visual encoding". If we
 * change the colour ramps we should update this copy.
 */

import React from "react";
import { useMapTime } from "../../hooks/useMapTime";
import { labelYear, isProjectedMode } from "../../lib/fesProjections";

const WRAP_STYLE = {
  position: "absolute",
  right: 16,
  bottom: 96,
  zIndex: 42,
  maxWidth: 320,
  padding: "10px 12px",
  borderRadius: 10,
  background: "rgba(15, 19, 24, 0.82)",
  color: "#F5EFE3",
  backdropFilter: "blur(10px)",
  WebkitBackdropFilter: "blur(10px)",
  border: "1px solid rgba(245, 183, 49, 0.25)",
  boxShadow: "0 4px 14px rgba(15, 19, 24, 0.25)",
  fontFamily: '"DM Sans", -apple-system, sans-serif',
  fontSize: 11.5,
  lineHeight: 1.45,
  letterSpacing: "0.01em",
  pointerEvents: "none",
};

const TITLE_STYLE = {
  fontWeight: 700,
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "#F5B731",
  marginBottom: 6,
};

const KEY_ROW = { display: "flex", alignItems: "center", gap: 6, marginTop: 4 };
const DOT_STYLE = (col) => ({
  display: "inline-block",
  width: 10,
  height: 10,
  borderRadius: 999,
  background: col,
  flex: "0 0 10px",
});

export default function FESLegend({ compact = false }) {
  const { asOf, fesPathway } = useMapTime();
  const year = labelYear(asOf);
  const projected = isProjectedMode(asOf);

  return (
    <div style={WRAP_STYLE} role="note" aria-label="FES scenario legend">
      <div style={TITLE_STYLE}>
        {projected ? "Projected scenario" : "Live grid"}
      </div>

      <div style={{ marginBottom: 6 }}>
        FES 2024 — <strong style={{ color: "#F5B731" }}>{fesPathway}</strong>
        <br />
        Year: <strong>{year}</strong>
        {!projected && (
          <span style={{ opacity: 0.65 }}> (today)</span>
        )}
      </div>

      {!compact && (
        <>
          <div style={{ opacity: 0.85, marginBottom: 2 }}>
            Column height &amp; bubble size = projected peak demand (GW).
            Colour = headroom state.
          </div>
          <div style={KEY_ROW}>
            <span style={DOT_STYLE("#28BE5A")} />
            <span>Ample headroom (&lt; 70% util)</span>
          </div>
          <div style={KEY_ROW}>
            <span style={DOT_STYLE("#F5B731")} />
            <span>Constrained (70–95%)</span>
          </div>
          <div style={KEY_ROW}>
            <span style={DOT_STYLE("#DC3C3C")} />
            <span>At / over capacity (&gt; 95%)</span>
          </div>
          <div style={{ marginTop: 8, opacity: 0.6, fontSize: 10.5 }}>
            Drag the time scrubber or pick a pathway — the map, demand
            columns and live-strip all update.
          </div>
        </>
      )}
    </div>
  );
}
