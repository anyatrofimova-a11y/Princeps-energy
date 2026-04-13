import React, { useState, useCallback } from "react";

const TECH_CHIPS = [
  { key: "all", label: "All" },
  { key: "solar", label: "Solar" },
  { key: "wind", label: "Wind" },
  { key: "bess", label: "BESS" },
  { key: "dc", label: "DC" },
];

const verdictColors = {
  GO: { bg: "#dcfce7", text: "#15803d", border: "#bbf7d0" },
  CAUTION: { bg: "#fef3c7", text: "#92400e", border: "#fde68a" },
  "NO-GO": { bg: "#fee2e2", text: "#991b1b", border: "#fecaca" },
};

const st = {
  container: {
    background: "var(--cds-layer-01, #ffffff)",
    borderRadius: "var(--radius-md, 12px)",
  },
  filterRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "14px 20px 12px",
    flexWrap: "wrap",
  },
  chip: (active) => ({
    padding: "5px 14px",
    fontSize: 12,
    fontWeight: active ? 600 : 400,
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: 20,
    border: "none",
    cursor: "pointer",
    transition: "all 0.15s",
    background: active ? "var(--gold, #F5B731)" : "var(--cds-layer-03, #EBEDF0)",
    color: active ? "#ffffff" : "var(--muted, #6B7280)",
    userSelect: "none",
  }),
  constraintChip: (active) => ({
    padding: "5px 14px",
    fontSize: 12,
    fontWeight: 500,
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: 20,
    border: active ? "1px solid var(--gold, #F5B731)" : "1px solid var(--border, #E8EAED)",
    cursor: "pointer",
    transition: "all 0.15s",
    background: active ? "var(--accent-surface, rgba(245,183,49,0.06))" : "var(--cds-layer-01, #ffffff)",
    color: active ? "var(--gold-dark, #E8A012)" : "var(--muted, #6B7280)",
    userSelect: "none",
  }),
  divider: {
    width: 1,
    height: 20,
    background: "var(--border, #E8EAED)",
    margin: "0 4px",
  },
  numericInput: {
    width: 80,
    padding: "5px 10px",
    fontSize: 12,
    fontFamily: "'DM Sans', sans-serif",
    border: "1px solid var(--border, #E8EAED)",
    borderRadius: 8,
    outline: "none",
    background: "var(--cds-layer-02, #F7F8FA)",
    color: "var(--ink, #0F1318)",
  },
  inputLabel: {
    fontSize: 10,
    fontWeight: 600,
    color: "var(--muted, #6B7280)",
    textTransform: "uppercase",
    letterSpacing: "0.03em",
    marginRight: 4,
  },
  searchBtn: {
    padding: "6px 20px",
    fontSize: 12,
    fontWeight: 600,
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: 8,
    border: "none",
    cursor: "pointer",
    background: "var(--gold, #F5B731)",
    color: "#ffffff",
    transition: "background 0.15s",
  },
  drawBtn: {
    padding: "6px 16px",
    fontSize: 12,
    fontWeight: 500,
    fontFamily: "'DM Sans', sans-serif",
    borderRadius: 8,
    border: "1px solid var(--border, #E8EAED)",
    cursor: "pointer",
    background: "var(--cds-layer-01, #ffffff)",
    color: "var(--ink, #0F1318)",
    transition: "background 0.15s",
  },
  tableWrap: {
    overflowX: "auto",
    overflowY: "auto",
    maxHeight: 380,
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13,
    fontFamily: "'DM Sans', sans-serif",
  },
  th: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    color: "var(--muted, #6B7280)",
    padding: "10px 16px",
    borderBottom: "1px solid var(--border, #E8EAED)",
    textAlign: "left",
    position: "sticky",
    top: 0,
    background: "var(--cds-layer-01, #ffffff)",
    zIndex: 1,
  },
  td: {
    padding: "12px 16px",
    borderBottom: "1px solid var(--cds-layer-03, #EBEDF0)",
    verticalAlign: "middle",
  },
  row: (hover) => ({
    transition: "background 0.12s",
    background: hover ? "var(--accent-surface, rgba(245,183,49,0.06))" : "transparent",
    cursor: "pointer",
  }),
  verdict: (v) => {
    const c = verdictColors[v] || verdictColors.CAUTION;
    return {
      display: "inline-block",
      padding: "3px 10px",
      fontSize: 11,
      fontWeight: 600,
      borderRadius: 12,
      background: c.bg,
      color: c.text,
      border: `1px solid ${c.border}`,
    };
  },
  empty: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "48px 24px",
    gap: 8,
    color: "var(--muted, #6B7280)",
    fontSize: 12,
  },
  resultCount: {
    fontSize: 11,
    color: "var(--muted-light, #9CA3AF)",
    padding: "6px 20px 2px",
  },
};

function scoreColor(score) {
  if (score >= 65) return "var(--cds-support-success, #16A34A)";
  if (score >= 40) return "var(--gold-dark, #E8A012)";
  return "#dc2626";
}

export default function SiteSearchPanel({ onSiteSelect, onSearchRegion }) {
  const [technology, setTechnology] = useState("all");
  const [excludeFlood, setExcludeFlood] = useState(true);
  const [excludeBMV, setExcludeBMV] = useState(true);
  const [minArea, setMinArea] = useState("5");
  const [maxGridDist, setMaxGridDist] = useState("20");
  const [minScore, setMinScore] = useState("50");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [hoverIdx, setHoverIdx] = useState(null);

  const runSearch = useCallback(async () => {
    setSearching(true);
    try {
      const r = await fetch("/api/parcels/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bbox: [-2.5, 51.0, 0.5, 53.0],
          technology: technology !== "all" ? technology : undefined,
          min_area_ha: parseFloat(minArea) || 0,
          max_distance_to_substation_km: parseFloat(maxGridDist) || 50,
          exclude_flood_zone_3: excludeFlood,
          exclude_bmv_land: excludeBMV,
          min_score: parseFloat(minScore) || 0,
          limit: 20,
        }),
      });
      if (r.ok) {
        const data = await r.json();
        setResults(data.parcels || []);
      }
    } catch {
      /* silent */
    }
    setSearching(false);
  }, [technology, minArea, maxGridDist, excludeFlood, excludeBMV, minScore]);

  return (
    <div style={st.container}>
      {/* Filters */}
      <div style={st.filterRow}>
        {TECH_CHIPS.map((c) => (
          <button
            key={c.key}
            style={st.chip(technology === c.key)}
            onClick={() => setTechnology(c.key)}
          >
            {c.label}
          </button>
        ))}

        <div style={st.divider} />

        <button
          style={st.constraintChip(excludeFlood)}
          onClick={() => setExcludeFlood((v) => !v)}
        >
          Excl. Flood Zone 3 {excludeFlood ? "\u2713" : ""}
        </button>
        <button
          style={st.constraintChip(excludeBMV)}
          onClick={() => setExcludeBMV((v) => !v)}
        >
          Excl. BMV {excludeBMV ? "\u2713" : ""}
        </button>

        <div style={st.divider} />

        <span style={st.inputLabel}>Min Area</span>
        <input
          type="number"
          value={minArea}
          onChange={(e) => setMinArea(e.target.value)}
          style={st.numericInput}
          placeholder="ha"
        />

        <span style={st.inputLabel}>Max Grid</span>
        <input
          type="number"
          value={maxGridDist}
          onChange={(e) => setMaxGridDist(e.target.value)}
          style={st.numericInput}
          placeholder="km"
        />

        <span style={st.inputLabel}>Min Score</span>
        <input
          type="number"
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
          style={st.numericInput}
          placeholder="0-100"
        />

        <div style={st.divider} />

        <button style={st.searchBtn} onClick={runSearch} disabled={searching}>
          {searching ? "Searching..." : "Search"}
        </button>
        <button style={st.drawBtn} onClick={() => onSearchRegion?.()}>
          Draw Region
        </button>
      </div>

      {/* Results */}
      {results.length > 0 && (
        <>
          <div style={st.resultCount}>{results.length} sites found</div>
          <div style={st.tableWrap}>
            <table style={st.table}>
              <thead>
                <tr>
                  <th style={st.th}>Parcel</th>
                  <th style={st.th}>Area</th>
                  <th style={st.th}>Grid Distance</th>
                  <th style={st.th}>Score</th>
                  <th style={st.th}>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr
                    key={i}
                    style={st.row(hoverIdx === i)}
                    onMouseEnter={() => setHoverIdx(i)}
                    onMouseLeave={() => setHoverIdx(null)}
                    onClick={() => onSiteSelect?.(r)}
                  >
                    <td style={{ ...st.td, fontWeight: 600 }}>
                      {r.parcel_id?.slice(0, 12) || `Site ${i + 1}`}
                    </td>
                    <td style={st.td}>{r.area_ha?.toFixed(1)} ha</td>
                    <td style={st.td}>{r.grid_distance_km?.toFixed(1)} km</td>
                    <td
                      style={{
                        ...st.td,
                        fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
                        fontWeight: 700,
                        color: scoreColor(r.score),
                      }}
                    >
                      {r.score}
                    </td>
                    <td style={st.td}>
                      <span style={st.verdict(r.verdict)}>{r.verdict}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {results.length === 0 && !searching && (
        <div style={st.empty}>
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink, #0F1318)" }}>
            Site Search
          </span>
          <span>Set constraints above and click Search to find candidate parcels.</span>
        </div>
      )}
    </div>
  );
}
