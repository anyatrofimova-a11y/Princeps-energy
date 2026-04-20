import React, { useEffect, useRef, useState } from "react";
import * as Plot from "@observablehq/plot";

const MOCK = {
  verdict: "CAUTION",
  approval_probability: 0.62,
  lpa_speed_days: 98,
  lpa_name: "South Bucks",
  similar_cases: [
    { ref: "PP/22/0412", outcome: "approved", size_mw: 12 },
    { ref: "PP/21/1188", outcome: "approved", size_mw: 18 },
    { ref: "PP/23/0099", outcome: "refused", size_mw: 40 },
    { ref: "PP/22/0821", outcome: "approved", size_mw: 25 },
  ],
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

export default function PlanningCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [s, setS] = useState({ loading: true, data: null });
  const plotRef = useRef(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/planning/ml/predict?site_id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setS({ loading: false, data: d }))
      .catch(() => alive && setS({ loading: false, data: MOCK }));
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    if (!plotRef.current || !s.data?.similar_cases) return;
    plotRef.current.innerHTML = "";
    const fig = Plot.plot({
      height: 160,
      marginLeft: 60,
      x: { label: "Size MW" },
      y: { label: null },
      color: { domain: ["approved", "refused"], range: ["#3a7", "#c33"] },
      marks: [
        Plot.dot(s.data.similar_cases, {
          x: "size_mw",
          y: "ref",
          fill: "outcome",
          r: 6,
        }),
      ],
    });
    plotRef.current.append(fig);
    return () => fig.remove();
  }, [s.data]);

  if (s.loading) return <div className="pc-card"><h3 className="pc-card-title">Planning</h3><div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div></div>;
  const d = s.data || {};
  const pct = Math.round((d.approval_probability ?? 0) * 100);
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Planning Likelihood</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ display: "flex", gap: 16, margin: "8px 0" }}>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Approval</div>
          <div style={{ fontSize: 22, fontWeight: 600 }}>{pct}%</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>LPA</div>
          <div style={{ fontWeight: 500 }}>{d.lpa_name || "—"}</div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>{d.lpa_speed_days} d median</div>
        </div>
      </div>
      <div ref={plotRef} />
      {d.stub && <div style={{ fontSize: 10, color: "var(--ink-soft)", fontStyle: "italic", marginTop: 4 }}>mock data</div>}
    </div>
  );
}
