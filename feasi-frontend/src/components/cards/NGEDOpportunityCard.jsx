import React, { useEffect, useState } from "react";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";

/**
 * NGED Distribution Network Opportunity Card
 * Shows regional summary stats, RAG breakdown, and top connection opportunities.
 */
export default function NGEDOpportunityCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.grid.ngedSummary()
      .then(d => { if (d) setData(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <MetricCard title="NGED Network" accentColor="#1b5e20">
        <span className="muted">Loading NGED data...</span>
      </MetricCard>
    );
  }

  if (!data) {
    return (
      <MetricCard title="NGED Network" accentColor="#1b5e20">
        <span className="muted">No NGED data available — seeding may still be in progress.</span>
      </MetricCard>
    );
  }

  const { rag } = data;

  return (
    <MetricCard
      title="NGED Network"
      accentColor="#1b5e20"
      headerValue={`${data.total_substations} substations`}
    >
      {/* Summary stats */}
      <div className="stat-grid">
        <div>Geo-matched: <strong>{data.geo_matched}</strong> ({data.match_pct}%)</div>
        <div>Total headroom: <strong>{data.total_headroom_mw?.toLocaleString()} MW</strong></div>
      </div>
      <div className="stat-grid">
        <div>Rated capacity: <strong>{data.total_rated_mva?.toLocaleString()} MVA</strong></div>
        <div>Connected load: <strong>{data.total_load_mw?.toLocaleString()} MW</strong></div>
      </div>

      {/* RAG breakdown */}
      {rag && (
        <>
          <div className="section-label">Headroom RAG</div>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <div style={{ flex: 1, background: "#4caf50", color: "#fff", borderRadius: 4, padding: "4px 8px", textAlign: "center", fontSize: 12 }}>
              <div style={{ fontWeight: 700 }}>{rag.green}</div>
              <div>&gt;5 MW</div>
            </div>
            <div style={{ flex: 1, background: "#ff9800", color: "#fff", borderRadius: 4, padding: "4px 8px", textAlign: "center", fontSize: 12 }}>
              <div style={{ fontWeight: 700 }}>{rag.amber}</div>
              <div>1-5 MW</div>
            </div>
            <div style={{ flex: 1, background: "#f44336", color: "#fff", borderRadius: 4, padding: "4px 8px", textAlign: "center", fontSize: 12 }}>
              <div style={{ fontWeight: 700 }}>{rag.red}</div>
              <div>&lt;1 MW</div>
            </div>
          </div>
        </>
      )}

      {/* Regional breakdown */}
      {data.regions && data.regions.length > 0 && (
        <>
          <div className="section-label">By Region</div>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.15)" }}>
                <th style={{ textAlign: "left", padding: "2px 4px" }}>Region</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>Subs</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>Matched</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>Headroom</th>
              </tr>
            </thead>
            <tbody>
              {data.regions.map(r => (
                <tr key={r.region} style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                  <td style={{ padding: "2px 4px", textTransform: "capitalize" }}>{r.region?.replace(/_/g, " ")}</td>
                  <td style={{ textAlign: "right", padding: "2px 4px" }}>{r.substations}</td>
                  <td style={{ textAlign: "right", padding: "2px 4px" }}>{r.match_pct}%</td>
                  <td style={{ textAlign: "right", padding: "2px 4px" }}>{r.total_headroom_mw} MW</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {/* Top opportunities */}
      {data.top_opportunities && data.top_opportunities.length > 0 && (
        <>
          <div className="section-label" style={{ marginTop: 8 }}>Top Opportunities</div>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.15)" }}>
                <th style={{ textAlign: "left", padding: "2px 4px" }}>Substation</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>Region</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>MVA</th>
                <th style={{ textAlign: "right", padding: "2px 4px" }}>Headroom</th>
              </tr>
            </thead>
            <tbody>
              {data.top_opportunities.map(o => (
                <tr key={o.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                  <td style={{ padding: "2px 4px", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.name}</td>
                  <td style={{ textAlign: "right", padding: "2px 4px", textTransform: "capitalize", fontSize: 10 }}>{o.region?.replace(/_/g, " ")}</td>
                  <td style={{ textAlign: "right", padding: "2px 4px" }}>{o.rated_mva}</td>
                  <td style={{ textAlign: "right", padding: "2px 4px", fontWeight: 600, color: o.headroom_mw > 5 ? "#4caf50" : o.headroom_mw >= 1 ? "#ff9800" : "#f44336" }}>{o.headroom_mw} MW</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </MetricCard>
  );
}
