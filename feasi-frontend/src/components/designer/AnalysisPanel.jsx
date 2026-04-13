import React from "react";

const C = {
  gold: "#F5B731", goldDark: "#E8A012", goldSurface: "rgba(245,183,49,0.06)",
  ink: "#1A1714", secondary: "#6B6560", tertiary: "#9C9590",
  border: "#E8E5DF", card: "#FFFFFF", go: "#2D7A4F", danger: "#B5432A",
};

function fmt(v, decimals = 0) {
  if (v == null) return "---";
  if (typeof v === "string") return v;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(decimals > 0 ? decimals : 0)}k`;
  return decimals > 0 ? v.toFixed(decimals) : Math.round(v).toString();
}

function MetricGroup({ title, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
        color: C.secondary, marginBottom: 8, paddingLeft: 10,
        borderLeft: `3px solid ${C.gold}`,
      }}>
        {title}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {children}
      </div>
    </div>
  );
}

function Metric({ label, value, unit, color, wide }) {
  return (
    <div style={{
      padding: "8px 10px",
      background: C.goldSurface,
      borderRadius: 8,
      gridColumn: wide ? "1 / -1" : undefined,
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.05em", color: C.tertiary, marginBottom: 3,
      }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <span style={{
          fontSize: 20, fontWeight: 800,
          fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
          color: color || C.ink, letterSpacing: "-0.02em",
        }}>
          {typeof value === "number" ? fmt(value) : value}
        </span>
        {unit && (
          <span style={{ fontSize: 11, color: C.secondary, fontWeight: 500 }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function BESSAnalysis({ metrics }) {
  const m = metrics || {};
  return (
    <>
      <MetricGroup title="Capacity">
        <Metric label="Total Power" value={m.total_mw} unit="MW" />
        <Metric label="Total Energy" value={m.total_mwh} unit="MWh" />
        <Metric label="Duration" value={m.duration_hours} unit="hr" />
        <Metric label="Containers" value={m.container_count} />
      </MetricGroup>
      <MetricGroup title="Financial">
        <Metric label="Est. CAPEX" value={m.estimated_capex_gbp ? `£${fmt(m.estimated_capex_gbp)}` : "---"} />
        <Metric label="Revenue" value={m.estimated_revenue_gbp_per_mw_yr ? `£${fmt(m.estimated_revenue_gbp_per_mw_yr)}` : "---"} unit="/MW/yr" />
        <Metric label="IRR" value={m.irr_pct} unit="%" color={m.irr_pct >= 10 ? C.go : C.goldDark} />
        <Metric label="Payback" value={m.payback_years} unit="yr" />
      </MetricGroup>
      <MetricGroup title="Grid Connection">
        <Metric label="Voltage" value={m.grid_connection_voltage} />
        <Metric label="Est. Cost" value={m.grid_connection_cost_gbp ? `£${fmt(m.grid_connection_cost_gbp)}` : "---"} />
        <Metric label="Timeline" value={m.grid_connection_timeline_months} unit="mo" />
        <Metric label="PCS Count" value={m.pcs_count} />
      </MetricGroup>
      <MetricGroup title="Site">
        <Metric label="Total Area" value={m.site_area_ha} unit="ha" />
        <Metric label="Footprint" value={m.footprint_m2 ? fmt(m.footprint_m2) : "---"} unit="m²" />
      </MetricGroup>
    </>
  );
}

function DCAnalysis({ metrics }) {
  const m = metrics || {};
  return (
    <>
      <MetricGroup title="Power">
        <Metric label="IT Load" value={m.it_load_mw} unit="MW" />
        <Metric label="Total Facility" value={m.total_facility_mw} unit="MW" />
        <Metric label="PUE" value={m.pue} unit="" color={m.pue <= 1.3 ? C.go : C.goldDark} />
        <Metric label="Cooling" value={m.cooling_mw} unit="MW" />
      </MetricGroup>
      <MetricGroup title="Redundancy">
        <Metric label="Tier" value={m.tier ? `Tier ${m.tier}` : "---"} />
        <Metric label="Config" value={m.redundancy} />
        <Metric label="Generators" value={m.generator_count} />
        <Metric label="Gen Capacity" value={m.generator_total_mw} unit="MW" />
        <Metric label="Fuel Storage" value={m.fuel_autonomy_hours} unit="hr" />
        <Metric label="Fuel Volume" value={m.fuel_storage_litres ? fmt(m.fuel_storage_litres) : "---"} unit="L" />
      </MetricGroup>
      <MetricGroup title="Financial">
        <Metric label="Build Cost" value={m.build_cost_gbp ? `£${fmt(m.build_cost_gbp)}` : "---"} wide />
        <Metric label="Revenue" value={m.revenue_per_mw_yr_gbp ? `£${fmt(m.revenue_per_mw_yr_gbp)}` : "---"} unit="/MW/yr" />
        <Metric label="Grid Cost" value={m.grid_connection_cost_gbp ? `£${fmt(m.grid_connection_cost_gbp)}` : "---"} />
      </MetricGroup>
      <MetricGroup title="Site">
        <Metric label="Halls" value={m.hall_count} />
        <Metric label="Total Area" value={m.site_area_ha} unit="ha" />
        <Metric label="Grid Voltage" value={m.grid_connection_voltage} />
        <Metric label="Timeline" value={m.grid_connection_timeline_months} unit="mo" />
      </MetricGroup>
    </>
  );
}

export default function AnalysisPanel({ mode, metrics, objects = [] }) {
  return (
    <div style={{
      height: "100%", overflowY: "auto", background: C.card,
      borderLeft: `1px solid ${C.border}`, padding: 16,
    }}>
      <div style={{
        fontSize: 13, fontWeight: 700, color: C.ink, marginBottom: 16,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={C.gold} strokeWidth="1.5">
          <path d="M3 3v10h10" strokeLinecap="round" />
          <path d="M6 10l3-5 3 2 3-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Analysis
        <span style={{
          fontSize: 9, fontWeight: 600, color: C.goldDark, background: C.goldSurface,
          padding: "2px 8px", borderRadius: 10, marginLeft: "auto",
        }}>
          {mode === "bess" ? "BESS" : "DC"}
        </span>
      </div>

      {mode === "bess" ? <BESSAnalysis metrics={metrics} /> : <DCAnalysis metrics={metrics} />}

      {/* Object count summary */}
      <div style={{
        marginTop: 16, padding: "10px 12px",
        background: C.goldSurface, borderRadius: 8,
        border: `1px solid ${C.border}`,
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: C.secondary, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
          Placed Objects
        </div>
        <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "var(--mono), monospace", color: C.ink }}>
          {objects.length}
        </div>
        <div style={{ fontSize: 10, color: C.tertiary, marginTop: 2 }}>
          {new Set(objects.map(o => o.type)).size} types
        </div>
      </div>
    </div>
  );
}
