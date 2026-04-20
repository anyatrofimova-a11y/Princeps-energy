import React, { useEffect, useRef, useState } from "react";
import * as Plot from "@observablehq/plot";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const MOCK = {
  verdict: "GO",
  annual_mwh: 18500,
  capacity_factor: 0.108,
  dc_ac_ratio: 1.3,
  p50_mwh: 18500,
  p90_mwh: 16200,
  monthly_mwh: [520, 820, 1320, 1780, 2150, 2280, 2260, 2020, 1570, 1080, 600, 480],
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

export default function YieldCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [s, setS] = useState({ loading: true, data: null });
  const plotRef = useRef(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/yield/sam?site_id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => alive && setS({ loading: false, data: d }))
      .catch(() => alive && setS({ loading: false, data: MOCK }));
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    if (!plotRef.current || !s.data?.monthly_mwh) return;
    const rows = s.data.monthly_mwh.map((v, i) => ({ month: MONTHS[i], mwh: v }));
    plotRef.current.innerHTML = "";
    const fig = Plot.plot({
      height: 160,
      marginLeft: 50,
      x: { label: null },
      y: { label: "MWh" },
      marks: [
        Plot.areaY(rows, { x: "month", y: "mwh", fill: "#caa24a", fillOpacity: 0.3 }),
        Plot.lineY(rows, { x: "month", y: "mwh", stroke: "#caa24a", strokeWidth: 2 }),
        Plot.ruleY([0]),
      ],
    });
    plotRef.current.append(fig);
    return () => fig.remove();
  }, [s.data]);

  if (s.loading) return <div className="pc-card"><h3 className="pc-card-title">Yield</h3><div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div></div>;
  const d = s.data || {};
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Yield (SAM)</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ display: "flex", gap: 16, margin: "8px 0" }}>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Annual</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{Math.round((d.annual_mwh ?? 0) / 1000)}k MWh</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>CF</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{((d.capacity_factor ?? 0) * 100).toFixed(1)}%</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>DC:AC</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{(d.dc_ac_ratio ?? 0).toFixed(2)}</div>
        </div>
      </div>
      <div ref={plotRef} />
      <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 4 }}>
        P50 {Math.round((d.p50_mwh ?? 0) / 1000)}k · P90 {Math.round((d.p90_mwh ?? 0) / 1000)}k
      </div>
      {d.stub && <div style={{ fontSize: 10, color: "var(--ink-soft)", fontStyle: "italic", marginTop: 4 }}>mock data</div>}
    </div>
  );
}
