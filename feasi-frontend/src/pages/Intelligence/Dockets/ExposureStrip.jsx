import React from "react";
import { COLOURS, SANS, MONO } from "./tokens";

// Shown only when a project is pinned. Surfaces docket-to-project exposure.
export default function ExposureStrip({ docket }) {
  const ex = docket?.exposure;
  if (!docket?.pinned || !ex) return null;

  const tiles = [
    { label: "Distance from site", value: ex.distance_km != null ? `${ex.distance_km} km` : "n/a" },
    { label: "DNO overlap", value: ex.dno_area_overlap || "—" },
    { label: "Grid queue impact", value: ex.grid_queue_impact || "—" },
    {
      label: "Timeline impact",
      value:
        ex.timeline_impact_days != null ? (
          <span style={{ color: ex.timeline_impact_days > 0 ? "#B84A4A" : "#1F6A3F", fontWeight: 700 }}>
            {ex.timeline_impact_days > 0 ? "+" : ""}{ex.timeline_impact_days}d
          </span>
        ) : "—",
    },
    {
      label: "ΔIRR",
      value:
        ex.delta_irr_bps != null ? (
          <span style={{ color: ex.delta_irr_bps >= 0 ? "#1F6A3F" : "#B84A4A", fontFamily: MONO, fontWeight: 700 }}>
            {ex.delta_irr_bps >= 0 ? "+" : ""}{ex.delta_irr_bps} bps
          </span>
        ) : "—",
    },
    {
      label: "ΔNPV",
      value:
        ex.delta_npv_kgbp != null ? (
          <span style={{ color: ex.delta_npv_kgbp >= 0 ? "#1F6A3F" : "#B84A4A", fontFamily: MONO, fontWeight: 700 }}>
            {ex.delta_npv_kgbp >= 0 ? "+" : ""}£{formatK(ex.delta_npv_kgbp)}k
          </span>
        ) : "—",
    },
  ];

  return (
    <section
      style={{
        background: "linear-gradient(90deg, rgba(245,183,49,.08) 0%, rgba(245,183,49,.02) 100%)",
        border: `1px solid ${COLOURS.gold}`,
        borderRadius: 8,
        padding: 14,
        fontFamily: SANS,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={COLOURS.gold} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 2h6l-1 4 3 3h-5v4l-1 1-1-1v-4H3l3-3z" />
        </svg>
        <div style={{ fontSize: 12, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Pinned project exposure
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12 }}>
        {tiles.map((t) => (
          <div key={t.label} style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>
              {t.label}
            </div>
            <div style={{ fontSize: 13, color: COLOURS.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t.value}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatK(n) {
  if (n == null) return "";
  const abs = Math.abs(n);
  if (abs >= 1000) return `${(n / 1000).toFixed(1)}M`;
  return Math.round(n).toLocaleString();
}
