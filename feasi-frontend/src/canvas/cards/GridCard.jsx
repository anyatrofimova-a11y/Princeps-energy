import React, { useEffect, useRef, useState } from "react";
import * as Plot from "@observablehq/plot";

const MOCK = {
  verdict: "CAUTION",
  headroom_mw: 14.2,
  capacity_mw: 45,
  demand_mw: 30.8,
  nearest_substation: "Iver 132kV",
  distance_km: 2.4,
  cost_p10: 1.8,
  cost_p50: 3.1,
  cost_p90: 5.4,
  stub: true,
};

function VerdictChip({ v }) {
  const c =
    v === "GO" ? "#3a7" : v === "NO-GO" ? "#c33" : v === "CAUTION" ? "#c80" : "#888";
  return (
    <span
      style={{
        background: c,
        color: "#fff",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.3,
      }}
    >
      {v || "—"}
    </span>
  );
}

export default function GridCard({ polygon, projectId, assetClass, siteId, onExpand }) {
  const id = siteId || projectId;
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const plotRef = useRef(null);

  useEffect(() => {
    let alive = true;
    setState({ loading: true, data: null, error: null });
    fetch(`/api/grid/connection/assessment?site_id=${id || ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("not ok"))))
      .then((d) => alive && setState({ loading: false, data: d, error: null }))
      .catch(() => alive && setState({ loading: false, data: MOCK, error: null }));
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    if (!plotRef.current || !state.data) return;
    const d = state.data;
    const chartData = [
      { label: "Capacity", mw: d.capacity_mw ?? 0 },
      { label: "Demand", mw: d.demand_mw ?? 0 },
      { label: "Headroom", mw: d.headroom_mw ?? 0 },
    ];
    plotRef.current.innerHTML = "";
    const fig = Plot.plot({
      height: 180,
      marginLeft: 70,
      x: { label: "MW" },
      y: { label: null },
      marks: [
        Plot.barX(chartData, {
          y: "label",
          x: "mw",
          fill: (x) => (x.label === "Headroom" ? "#caa24a" : "#888"),
        }),
        Plot.ruleX([0]),
      ],
    });
    plotRef.current.append(fig);
    return () => fig.remove();
  }, [state.data]);

  if (state.loading) {
    return (
      <div className="pc-card">
        <h3 className="pc-card-title">Grid Connection</h3>
        <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>Loading…</div>
      </div>
    );
  }
  const d = state.data || {};
  return (
    <div className="pc-card" onClick={onExpand} style={{ cursor: onExpand ? "pointer" : "default" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 className="pc-card-title">Grid Connection</h3>
        <VerdictChip v={d.verdict} />
      </div>
      <div style={{ display: "flex", gap: 16, margin: "8px 0", fontSize: 13 }}>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Headroom</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{(d.headroom_mw ?? 0).toFixed(1)} MW</div>
        </div>
        <div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>Nearest</div>
          <div style={{ fontWeight: 500 }}>{d.nearest_substation || "—"}</div>
          <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>
            {d.distance_km != null ? `${d.distance_km.toFixed(1)} km` : ""}
          </div>
        </div>
      </div>
      <div ref={plotRef} />
      <div style={{ fontSize: 12, color: "var(--ink-soft)", marginTop: 8 }}>
        Connection cost £m — P10 {(d.cost_p10 ?? 0).toFixed(1)} · P50{" "}
        <strong>{(d.cost_p50 ?? 0).toFixed(1)}</strong> · P90 {(d.cost_p90 ?? 0).toFixed(1)}
      </div>
      {d.stub && (
        <div style={{ fontSize: 10, color: "var(--ink-soft)", marginTop: 4, fontStyle: "italic" }}>
          mock data — live endpoint unavailable
        </div>
      )}
    </div>
  );
}
