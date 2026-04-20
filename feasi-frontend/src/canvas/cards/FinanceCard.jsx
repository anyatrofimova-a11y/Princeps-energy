import React, { useEffect, useState } from "react";

const MOCK = {
  verdict: "GO",
  npv_m: 12.4,
  irr: 0.118,
  lcoe_mwh: 48.2,
  payback_years: 7.8,
  capex_m: 28.5,
  stub: true,
};

function VerdictChip({ v }) {
  const c = v === "GO" ? "#3a7" : v === "NO-GO" ? "#c33" : v === "CAUTION" ? "#c80" : "#888";
  return (
    <span style={{ background: c, color: "#fff", padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600 }}>
      {v || "—"}
    </span>
  );
}

function Metric({ label, value, unit, big }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>{label}</div>
      <div style={{ fontSize: big ? 24 : 18, fontWeight: 600 }}>
        {value}
        {unit && <span style={{ fontSize: 12, color: "var(--ink-soft)", marginLeft: 3 }}>{unit}</span>}
      </div>
    </div>
  );
}

export default function FinanceCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [s, setS] = useState({ loading: true, data: null });

  useEffect(() => {
    let alive = true;
    fetch(`/api/finance/project?site_id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setS({ loading: false, data: d }))
      .catch(() => alive && setS({ loading: false, data: MOCK }));
    return () => { alive = false; };
  }, [id]);

  if (s.loading) return <div className="pc-card"><h3 className="pc-card-title">Finance</h3><div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div></div>;
  const d = s.data || {};
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Finance</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ display: "flex", gap: 10, margin: "10px 0" }}>
        <Metric label="NPV" value={`£${(d.npv_m ?? 0).toFixed(1)}`} unit="m" big />
        <Metric label="IRR" value={`${((d.irr ?? 0) * 100).toFixed(1)}%`} big />
      </div>
      <div style={{ display: "flex", gap: 10, margin: "10px 0" }}>
        <Metric label="LCOE" value={`£${(d.lcoe_mwh ?? 0).toFixed(0)}`} unit="/MWh" />
        <Metric label="Payback" value={(d.payback_years ?? 0).toFixed(1)} unit="yr" />
        <Metric label="CapEx" value={`£${(d.capex_m ?? 0).toFixed(1)}`} unit="m" />
      </div>
      {d.stub && <div style={{ fontSize: 10, color: "var(--ink-soft)", fontStyle: "italic", marginTop: 4 }}>mock data</div>}
    </div>
  );
}
