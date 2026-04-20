import React, { useEffect, useState } from "react";

const MOCK = {
  verdict: "CAUTION",
  glint_risk: "low",
  noise_db: 42,
  noise_receptor_m: 280,
  bng_pct: 12.4,
  flood_zone: "1",
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

function Row({ label, value, warn }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "4px 0", borderBottom: "1px solid var(--mist)" }}>
      <span style={{ color: "var(--ink-soft)" }}>{label}</span>
      <span style={{ fontWeight: 500, color: warn ? "#c80" : "var(--ink)" }}>{value}</span>
    </div>
  );
}

export default function EnvironmentCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [s, setS] = useState({ loading: true, data: null });

  useEffect(() => {
    let alive = true;
    fetch(`/api/environment/assessment?site_id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setS({ loading: false, data: d }))
      .catch(() => alive && setS({ loading: false, data: MOCK }));
    return () => { alive = false; };
  }, [id]);

  if (s.loading) return <div className="pc-card"><h3 className="pc-card-title">Environment</h3><div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div></div>;
  const d = s.data || {};
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Environment</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ marginTop: 10 }}>
        <Row label="Glint / glare" value={d.glint_risk || "—"} warn={d.glint_risk === "high"} />
        <Row
          label={`Noise @ ${d.noise_receptor_m ?? 0} m`}
          value={`${d.noise_db ?? 0} dB`}
          warn={(d.noise_db ?? 0) > 45}
        />
        <Row label="Flood zone" value={d.flood_zone || "—"} warn={["3","3a","3b"].includes(d.flood_zone)} />
        <Row label="BNG uplift" value={`${(d.bng_pct ?? 0).toFixed(1)}%`} warn={(d.bng_pct ?? 0) < 10} />
      </div>
      {d.stub && <div style={{ fontSize: 10, color: "var(--ink-soft)", fontStyle: "italic", marginTop: 8 }}>mock data</div>}
    </div>
  );
}
