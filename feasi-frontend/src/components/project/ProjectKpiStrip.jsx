import React from "react";
import { useProjectKpis } from "../../hooks/useProjectKpis.js";

const GOLD = "#F5B731";
const INK = "#0F1318";
const GREEN = "#3B8A5A";
const AMBER = "#E89A2A";
const RED = "#B84A4A";

function riskColour(pct) {
  if (pct == null) return "#6B7280";
  if (pct < 25) return GREEN;
  if (pct < 50) return AMBER;
  return RED;
}

export default function ProjectKpiStrip({ projectId }) {
  const { kpis, loading } = useProjectKpis(projectId);

  if (loading && !kpis) {
    return (
      <div style={skeletonRow}>
        {[...Array(5)].map((_, i) =>
          <div key={i} style={{ ...tile, background: "rgba(15,19,24,0.04)" }} />
        )}
      </div>
    );
  }
  if (!kpis) return null;

  const irrUp = (kpis.delta_irr_7d_bps || 0) >= 0;

  return (
    <div style={stripWrap}>
      <Tile label="Viability">
        <Gauge pct={kpis.viability_pct} />
      </Tile>
      <Tile label="Grid risk">
        <RiskPill pct={kpis.grid_risk_pct} />
      </Tile>
      <Tile label="Planning risk">
        <RiskPill pct={kpis.planning_risk_pct} />
      </Tile>
      <Tile label="ΔIRR 7d">
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 18, fontWeight: 700,
          color: irrUp ? GREEN : RED,
          fontVariantNumeric: "tabular-nums",
        }}>
          {irrUp ? "↑" : "↓"} {Math.abs(kpis.delta_irr_7d_bps || 0)} bps
        </div>
      </Tile>
      <Tile label="Critical path">
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 18, fontWeight: 700, color: INK,
          fontVariantNumeric: "tabular-nums",
        }}>
          {kpis.critical_path_days}<span style={{ fontSize: 11, color: "#6B7280", marginLeft: 4 }}>days</span>
        </div>
      </Tile>
    </div>
  );
}

function Tile({ label, children }) {
  return (
    <div style={tile}>
      <div style={{
        fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
        textTransform: "uppercase", color: "#6B7280", marginBottom: 4,
      }}>{label}</div>
      {children}
    </div>
  );
}
function Gauge({ pct }) {
  const p = pct || 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        width: 36, height: 36, borderRadius: "50%",
        background: `conic-gradient(${GOLD} ${p * 3.6}deg, rgba(15,19,24,0.08) 0)`,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: "50%", background: "#FBF8F2",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{p}</span>
        </div>
      </div>
      <div style={{ fontSize: 11, color: "#6B7280" }}>/ 100</div>
    </div>
  );
}
function RiskPill({ pct }) {
  const c = riskColour(pct);
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 999,
      background: c + "22", color: c,
      fontFamily: "'JetBrains Mono', monospace",
      fontWeight: 700, fontSize: 14, fontVariantNumeric: "tabular-nums",
    }}>
      {pct ?? "—"}%
    </div>
  );
}

const stripWrap = {
  display: "grid",
  gridTemplateColumns: "repeat(5, 1fr)",
  gap: 1,
  padding: 0,
  background: "rgba(15,19,24,0.08)",
  border: "1px solid rgba(15,19,24,0.08)",
  borderRadius: 8,
  overflow: "hidden",
  fontFamily: "'DM Sans', sans-serif",
};
const tile = {
  padding: "10px 14px",
  background: "#FBF8F2",
  minHeight: 56,
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
};
const skeletonRow = {
  ...stripWrap,
};
