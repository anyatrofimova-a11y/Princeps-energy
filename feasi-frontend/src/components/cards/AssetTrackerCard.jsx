import React, { useEffect, useState } from "react";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";

/**
 * Asset Tracker Card — Combined ESO TEC + REPD pipeline overview.
 * Shows total projects/GW, technology breakdown, and status pipeline.
 */
export default function AssetTrackerCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("combined"); // combined | tec | repd

  useEffect(() => {
    setLoading(true);
    api.repd.pipeline()
      .then(d => { if (d) setData(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <MetricCard title="Asset Pipeline" accentColor="#0277bd">
        <span className="muted">Loading pipeline data...</span>
      </MetricCard>
    );
  }

  if (!data) {
    return (
      <MetricCard title="Asset Pipeline" accentColor="#0277bd">
        <span className="muted">No pipeline data — seeding may still be in progress.</span>
      </MetricCard>
    );
  }

  const tabStyle = (t) => ({
    padding: "4px 10px", fontSize: 11, fontWeight: tab === t ? 700 : 400,
    background: tab === t ? "rgba(2,119,189,0.25)" : "transparent",
    border: "1px solid rgba(255,255,255,0.15)", borderRadius: 4, cursor: "pointer",
    color: tab === t ? "#4fc3f7" : "rgba(255,255,255,0.6)",
  });

  // Determine which status list to show
  const statusList = tab === "tec" ? data.tec_by_status
    : tab === "repd" ? data.repd_by_status
    : [...(data.tec_by_status || []), ...(data.repd_by_status || [])];

  // Aggregate status for combined view
  const statusMap = {};
  for (const s of statusList) {
    const key = s.status || "Unknown";
    if (!statusMap[key]) statusMap[key] = { status: key, count: 0, total_mw: 0 };
    statusMap[key].count += s.count;
    statusMap[key].total_mw += s.total_mw;
  }
  const statuses = Object.values(statusMap).sort((a, b) => b.count - a.count);

  // Tech breakdown
  const techData = tab === "combined" ? data.by_technology
    : tab === "tec" ? (data.by_technology || []).map(t => ({ ...t, total_mw: t.tec_mw, count: t.tec_n }))
    : (data.by_technology || []).map(t => ({ ...t, total_mw: t.repd_mw, count: t.repd_n }));

  const maxMw = Math.max(...(techData || []).map(t => (t.tec_mw || 0) + (t.repd_mw || 0) || t.total_mw || 0), 1);

  // Header stats
  const headerProjects = tab === "tec" ? data.tec?.total_projects
    : tab === "repd" ? data.repd?.total_projects
    : data.combined?.total_projects;
  const headerGw = tab === "tec" ? data.tec?.total_gw
    : tab === "repd" ? data.repd?.total_gw
    : data.combined?.total_gw;

  const STATUS_COLORS = {
    "Operational": "#4caf50", "Under Construction": "#ff9800", "Approved": "#2196f3",
    "Submitted": "#90caf9", "Refused": "#f44336", "Withdrawn": "#9e9e9e",
    "Appeal": "#ce93d8", "Decommissioned": "#757575",
  };

  const TECH_COLORS = {
    "solar": "#fdd835", "wind": "#00b0ff", "battery": "#7cb342", "gas": "#ff8f00",
    "nuclear": "#e53935", "hydro": "#1565c0", "biomass": "#8d6e63",
    "solar photovoltaics": "#fdd835", "wind onshore": "#00b0ff", "wind offshore": "#0277bd",
    "interconnector": "#ab47bc", "small hydro": "#1565c0", "large hydro": "#0d47a1",
  };

  return (
    <MetricCard
      title="Asset Pipeline"
      accentColor="#0277bd"
      headerValue={`${(headerProjects || 0).toLocaleString()} projects / ${headerGw || 0} GW`}
    >
      {/* Tab bar */}
      <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
        <button style={tabStyle("combined")} onClick={() => setTab("combined")}>Combined</button>
        <button style={tabStyle("tec")} onClick={() => setTab("tec")}>TEC</button>
        <button style={tabStyle("repd")} onClick={() => setTab("repd")}>REPD</button>
      </div>

      {/* Technology breakdown bars */}
      {techData && techData.length > 0 && (
        <>
          <div className="section-label">By Technology</div>
          {techData.slice(0, 8).map(t => {
            const mw = tab === "combined" ? ((t.tec_mw || 0) + (t.repd_mw || 0)) : (t.total_mw || 0);
            const pct = Math.max((mw / maxMw) * 100, 2);
            const color = TECH_COLORS[(t.label || "").toLowerCase()] || "#0277bd";
            return (
              <div key={t.label} style={{ marginBottom: 3 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, opacity: 0.8, marginBottom: 1 }}>
                  <span>{t.label}</span>
                  <span>{Math.round(mw).toLocaleString()} MW</span>
                </div>
                <div style={{ height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
                </div>
              </div>
            );
          })}
        </>
      )}

      {/* Status pipeline */}
      {statuses.length > 0 && (
        <>
          <div className="section-label" style={{ marginTop: 8 }}>Status Pipeline</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
            {statuses.slice(0, 6).map(s => (
              <div key={s.status} style={{
                flex: "1 1 auto", minWidth: 70, background: STATUS_COLORS[s.status] || "#666",
                color: "#fff", borderRadius: 4, padding: "3px 6px", textAlign: "center", fontSize: 10,
              }}>
                <div style={{ fontWeight: 700 }}>{s.count.toLocaleString()}</div>
                <div style={{ fontSize: 9, opacity: 0.9 }}>{s.status}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Source info */}
      <div style={{ fontSize: 9, opacity: 0.4, marginTop: 6 }}>
        {tab === "combined" ? "Sources: ESO TEC Register + BEIS REPD"
          : tab === "tec" ? "Source: ESO TEC Register (transmission >50 MW)"
          : "Source: BEIS REPD (renewables >150 kW)"}
      </div>
    </MetricCard>
  );
}
