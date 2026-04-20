import React, { useEffect, useState } from "react";

const MOCK = {
  verdict: "GO",
  owner: "Example Estates Ltd",
  area_ha: 42.8,
  buildable_ha: 29.5,
  alc_grade: "3b",
  exclusions: ["flood zone 2 (2.1 ha)", "SSSI buffer (1.4 ha)", "slope >10° (9.8 ha)"],
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

export default function LandCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [s, setS] = useState({ loading: true, data: null });

  useEffect(() => {
    let alive = true;
    fetch(`/api/land/parcel?id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setS({ loading: false, data: d }))
      .catch(() => alive && setS({ loading: false, data: MOCK }));
    return () => { alive = false; };
  }, [id]);

  if (s.loading) return <div className="pc-card"><h3 className="pc-card-title">Land</h3><div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div></div>;
  const d = s.data || {};
  const pct = d.area_ha ? Math.round((100 * (d.buildable_ha ?? 0)) / d.area_ha) : 0;
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Land & Ownership</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ fontSize: 13, margin: "8px 0" }}>
        <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Owner</div>
        <div style={{ fontWeight: 500 }}>{d.owner || "Unknown"}</div>
      </div>
      <div style={{ display: "flex", gap: 16, margin: "8px 0" }}>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Area</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{(d.area_ha ?? 0).toFixed(1)} ha</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Buildable</div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#caa24a" }}>
            {(d.buildable_ha ?? 0).toFixed(1)} ha
          </div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>{pct}%</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>ALC</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{d.alc_grade || "—"}</div>
        </div>
      </div>
      {d.exclusions?.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 6 }}>
          <div style={{ fontWeight: 500, color: "var(--ink)", marginBottom: 2 }}>Exclusions</div>
          {d.exclusions.map((e, i) => (
            <div key={i}>· {e}</div>
          ))}
        </div>
      )}
      {d.stub && <div style={{ fontSize: 10, color: "var(--ink-soft)", fontStyle: "italic", marginTop: 4 }}>mock data</div>}
    </div>
  );
}
