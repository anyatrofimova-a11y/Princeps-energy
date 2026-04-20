/**
 * FesPathwaySwitcher — segmented pill for the 4 FES 2024 pathways.
 *
 *   Leading the Way · Consumer Transformation · System Transformation · Falling Short
 *
 * Selected pathway is written into the useMapTime store and read by dynamic
 * layers (FES demand choropleth, NESO carbon intensity modelled tail, etc.).
 */

import React from "react";
import { useMapTime, FES_PATHWAYS } from "../../hooks/useMapTime";

const SHORT_LABEL = {
  "Leading the Way":          "LW",
  "Consumer Transformation":  "CT",
  "System Transformation":    "ST",
  "Falling Short":            "FS",
};

const PILL_STYLE = {
  position: "absolute",
  left: 16,
  bottom: 76,
  zIndex: 41,
  display: "inline-flex",
  background: "rgba(248, 245, 237, 0.92)",
  backdropFilter: "blur(10px)",
  WebkitBackdropFilter: "blur(10px)",
  border: "1px solid rgba(15, 19, 24, 0.12)",
  borderRadius: 999,
  padding: 4,
  gap: 2,
  boxShadow: "0 2px 10px rgba(15, 19, 24, 0.08)",
  fontFamily: '"DM Sans", -apple-system, sans-serif',
};

const ITEM_BASE = {
  padding: "6px 12px",
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.02em",
  textTransform: "uppercase",
  border: "none",
  background: "transparent",
  color: "rgba(15, 19, 24, 0.65)",
  borderRadius: 999,
  cursor: "pointer",
  transition: "background 120ms ease, color 120ms ease",
  whiteSpace: "nowrap",
};

const ITEM_ACTIVE = {
  background: "#F5B731",
  color: "#0F1318",
  boxShadow: "0 2px 6px rgba(245, 183, 49, 0.35)",
};

export default function FesPathwaySwitcher({ compact = false }) {
  const { fesPathway, setFesPathway } = useMapTime();

  return (
    <div
      role="tablist"
      aria-label="FES 2024 pathway"
      style={PILL_STYLE}
    >
      {FES_PATHWAYS.map((p) => {
        const active = p === fesPathway;
        const label = compact ? SHORT_LABEL[p] : p;
        return (
          <button
            key={p}
            role="tab"
            type="button"
            aria-selected={active}
            title={p}
            onClick={() => setFesPathway(p)}
            style={{ ...ITEM_BASE, ...(active ? ITEM_ACTIVE : {}) }}
            onMouseEnter={(e) => {
              if (!active) e.currentTarget.style.background = "rgba(245, 183, 49, 0.12)";
            }}
            onMouseLeave={(e) => {
              if (!active) e.currentTarget.style.background = "transparent";
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
