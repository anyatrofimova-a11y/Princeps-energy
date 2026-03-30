import React, { useState, useMemo } from "react";

/**
 * ConstraintTimeline — Area-by-area grid headroom analysis.
 *
 * Shows real substation data grouped by region/DNO with:
 *   - Available headroom (MW) at each connection point
 *   - Utilisation bar with RAG status
 *   - Nearest connection points ranked by available capacity
 *   - Regional summary (total capacity, demand, headroom)
 *
 * Props:
 *   gridState  — live grid twin state with substations[]
 *   visible    — whether panel is shown
 *   onFlyTo    — callback to fly camera to { lon, lat }
 */

/* ── Region definitions — group substations geographically ── */
const REGIONS = [
  { id: "london_se", label: "London & South East", latMin: 51.0, latMax: 51.8, lonMin: -1.5, lonMax: 1.5 },
  { id: "south_west", label: "South West", latMin: 50.0, latMax: 51.5, lonMin: -6.0, lonMax: -2.0 },
  { id: "east_anglia", label: "East Anglia", latMin: 51.8, latMax: 53.0, lonMin: 0.0, lonMax: 2.0 },
  { id: "midlands", label: "Midlands", latMin: 52.0, latMax: 53.5, lonMin: -3.0, lonMax: 0.0 },
  { id: "north_west", label: "North West", latMin: 53.0, latMax: 55.0, lonMin: -3.5, lonMax: -1.5 },
  { id: "north_east", label: "North East & Yorkshire", latMin: 53.0, latMax: 56.0, lonMin: -1.5, lonMax: 0.5 },
  { id: "wales", label: "Wales", latMin: 51.3, latMax: 53.5, lonMin: -5.5, lonMax: -2.5 },
  { id: "scotland_central", label: "Central Scotland", latMin: 55.5, latMax: 57.0, lonMin: -5.5, lonMax: -2.0 },
  { id: "scotland_north", label: "Northern Scotland", latMin: 57.0, latMax: 59.0, lonMin: -6.0, lonMax: -1.5 },
];

function assignRegion(sub) {
  for (const r of REGIONS) {
    if (sub.lat >= r.latMin && sub.lat < r.latMax && sub.lon >= r.lonMin && sub.lon < r.lonMax) {
      return r.id;
    }
  }
  return "other";
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Math.round(v)} MW`;
}

function ragColor(util) {
  if (util >= 0.9) return "#e53935";
  if (util >= 0.75) return "#fa8c16";
  if (util >= 0.6) return "#D4A018";
  return "#52c41a";
}

function ragLabel(util) {
  if (util >= 0.9) return "CONSTRAINED";
  if (util >= 0.75) return "LIMITED";
  if (util >= 0.6) return "MODERATE";
  return "AVAILABLE";
}

export default function ConstraintTimeline({ gridState, visible, onFlyTo }) {
  const [expandedRegion, setExpandedRegion] = useState(null);
  const [sortBy, setSortBy] = useState("headroom"); // headroom | utilisation | capacity

  const regionData = useMemo(() => {
    if (!gridState?.substations) return [];

    // Group substations by region
    const groups = {};
    for (const s of gridState.substations) {
      const rId = assignRegion(s);
      if (!groups[rId]) groups[rId] = [];
      groups[rId].push(s);
    }

    // Build region summaries
    return REGIONS.map(r => {
      const subs = groups[r.id] || [];
      if (subs.length === 0) return null;

      const totalCapacity = subs.reduce((a, s) => a + (s.capacity_mw || 0), 0);
      const totalDemand = subs.reduce((a, s) => a + (s.demand_mw || 0), 0);
      const totalHeadroom = subs.reduce((a, s) => a + (s.headroom_mw || 0), 0);
      const avgUtil = totalCapacity > 0 ? totalDemand / totalCapacity : 0;
      const constrained = subs.filter(s => (s.utilisation || 0) >= 0.9).length;

      // Sort substations
      const sorted = [...subs].sort((a, b) => {
        if (sortBy === "headroom") return (b.headroom_mw || 0) - (a.headroom_mw || 0);
        if (sortBy === "utilisation") return (b.utilisation || 0) - (a.utilisation || 0);
        return (b.capacity_mw || 0) - (a.capacity_mw || 0);
      });

      return {
        ...r,
        subs: sorted,
        totalCapacity,
        totalDemand,
        totalHeadroom,
        avgUtil,
        constrained,
        count: subs.length,
      };
    }).filter(Boolean).sort((a, b) => b.totalHeadroom - a.totalHeadroom);
  }, [gridState, sortBy]);

  if (!visible || !gridState) return null;

  const totalSubs = regionData.reduce((a, r) => a + r.count, 0);
  const totalConstrained = regionData.reduce((a, r) => a + r.constrained, 0);
  const totalHeadroom = regionData.reduce((a, r) => a + r.totalHeadroom, 0);

  return (
    <div className="ct2-panel">
      {/* Header */}
      <div className="ct2-header">
        <div className="ct2-header-top">
          <span className="ct2-title">Grid Headroom Analysis</span>
          <span className="ct2-subtitle">{totalSubs} connection points</span>
        </div>
        <div className="ct2-summary">
          <div className="ct2-summary-stat">
            <span className="ct2-summary-value">{fmtMw(totalHeadroom)}</span>
            <label>total headroom</label>
          </div>
          <div className="ct2-summary-stat">
            <span className="ct2-summary-value" style={{ color: totalConstrained > 0 ? "#e53935" : "#52c41a" }}>
              {totalConstrained}
            </span>
            <label>constrained</label>
          </div>
          <div className="ct2-summary-stat">
            <span className="ct2-summary-value">{regionData.length}</span>
            <label>regions</label>
          </div>
        </div>
      </div>

      {/* Sort controls */}
      <div className="ct2-sort">
        <span>Sort by</span>
        {[
          { id: "headroom", label: "Headroom" },
          { id: "utilisation", label: "Utilisation" },
          { id: "capacity", label: "Capacity" },
        ].map(s => (
          <button key={s.id} className={`ct2-sort-btn ${sortBy === s.id ? "active" : ""}`}
            onClick={() => setSortBy(s.id)}>{s.label}</button>
        ))}
      </div>

      {/* Region list */}
      <div className="ct2-regions">
        {regionData.map(r => {
          const isExpanded = expandedRegion === r.id;
          return (
            <div key={r.id} className={`ct2-region ${isExpanded ? "expanded" : ""}`}>
              {/* Region header — click to expand */}
              <button className="ct2-region-header" onClick={() => setExpandedRegion(isExpanded ? null : r.id)}>
                <div className="ct2-region-left">
                  <span className="ct2-region-rag" style={{ background: ragColor(r.avgUtil) }} />
                  <div>
                    <div className="ct2-region-name">{r.label}</div>
                    <div className="ct2-region-meta">{r.count} substations &middot; {ragLabel(r.avgUtil)}</div>
                  </div>
                </div>
                <div className="ct2-region-right">
                  <div className="ct2-region-headroom">
                    <span className="ct2-region-hw-value">{fmtMw(r.totalHeadroom)}</span>
                    <label>headroom</label>
                  </div>
                  <div className="ct2-region-util-bar">
                    <div style={{ width: `${Math.min(r.avgUtil * 100, 100)}%`, background: ragColor(r.avgUtil) }} />
                  </div>
                  <span className="ct2-region-util-pct">{(r.avgUtil * 100).toFixed(0)}%</span>
                  <svg className={`ct2-chevron ${isExpanded ? "open" : ""}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
              </button>

              {/* Expanded: individual substations */}
              {isExpanded && (
                <div className="ct2-subs">
                  <div className="ct2-subs-header">
                    <span>Connection Point</span>
                    <span>kV</span>
                    <span>Demand</span>
                    <span>Capacity</span>
                    <span>Headroom</span>
                    <span>Util</span>
                  </div>
                  {r.subs.map(s => (
                    <button
                      key={s.id}
                      className="ct2-sub-row"
                      onClick={() => onFlyTo?.({ lon: s.lon, lat: s.lat, height: 50000 })}
                      title={`Click to fly to ${s.name}`}
                    >
                      <span className="ct2-sub-name">
                        <span className="ct2-sub-dot" style={{ background: ragColor(s.utilisation || 0) }} />
                        {s.name}
                      </span>
                      <span className="ct2-sub-kv">{s.voltage_kv}</span>
                      <span className="ct2-sub-val">{fmtMw(s.demand_mw)}</span>
                      <span className="ct2-sub-val">{fmtMw(s.capacity_mw)}</span>
                      <span className="ct2-sub-val" style={{
                        color: (s.headroom_mw || 0) < 10 ? "#e53935" : (s.headroom_mw || 0) < 30 ? "#fa8c16" : "#52c41a",
                        fontWeight: 600,
                      }}>
                        {fmtMw(s.headroom_mw)}
                      </span>
                      <span className="ct2-sub-util">
                        <div className="ct2-sub-util-bar">
                          <div style={{ width: `${Math.min((s.utilisation || 0) * 100, 100)}%`, background: ragColor(s.utilisation || 0) }} />
                        </div>
                        <span style={{ color: ragColor(s.utilisation || 0) }}>{((s.utilisation || 0) * 100).toFixed(0)}%</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
