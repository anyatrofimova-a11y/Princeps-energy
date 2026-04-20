import React from "react";
import { useDomainLayers } from "../../../hooks/useDomainLayers.js";

const PACKS = [
  { slug: "solar", label: "Solar", accent: "#F5B731" },
  { slug: "bess", label: "BESS", accent: "#6B3FA0" },
  { slug: "dc", label: "Data centre", accent: "#2F8F87" },
  { slug: "wind", label: "Wind", accent: "#2E8B8B" },
  { slug: "ev", label: "EV", accent: "#3B8A5A" },
];

const SUB_LAYERS = {
  solar: ["irradiance", "slope", "aspect", "suitability", "precedents", "exclusions"],
  bess: ["revenue", "thermal_buffers", "comah", "curtailment", "precedents", "exclusions"],
  dc: ["grid_proximity", "water", "fibre", "hyperscalers", "latency", "precedents"],
  wind: ["dwpt", "turbulence", "aviation", "radar", "precedents", "exclusions"],
  ev: ["chargepoints", "grid_proximity", "traffic", "amenity", "roads", "precedents"],
};

export default function DomainLayerToggle({ tech }) {
  const { activePack, subLayers, setPack, toggleSubLayer } = useDomainLayers(tech);

  return (
    <div style={{
      padding: "12px 14px",
      borderTop: "1px solid rgba(15,19,24,0.08)",
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <div style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: "#6B7280",
        marginBottom: 8,
      }}>Asset domain</div>

      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
        {PACKS.map(p => {
          const active = activePack === p.slug;
          return (
            <button
              key={p.slug}
              onClick={() => setPack(p.slug)}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: active ? 700 : 500,
                border: `1px solid ${active ? p.accent : "rgba(15,19,24,0.2)"}`,
                background: active ? `${p.accent}22` : "transparent",
                color: active ? p.accent : "#0F1318",
                borderRadius: 999,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >{p.label}</button>
          );
        })}
      </div>

      {activePack && SUB_LAYERS[activePack] && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {SUB_LAYERS[activePack].map(sub => {
            const on = subLayers[sub] !== false;
            return (
              <label
                key={sub}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12,
                  color: "#0F1318",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggleSubLayer(sub)}
                  style={{ accentColor: "#F5B731" }}
                />
                <span style={{ textTransform: "capitalize" }}>
                  {sub.replace(/_/g, " ")}
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
