import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const DIMENSIONS_15 = [
  { key: "power_capacity", label: "Power Capacity" },
  { key: "grid_headroom", label: "Grid Headroom" },
  { key: "cfe_score", label: "CFE%" },
  { key: "cooling_climate", label: "Cooling" },
  { key: "constraint_clear", label: "Constraints" },
  { key: "water_stress", label: "Water" },
  { key: "fibre_proximity", label: "Fibre" },
  { key: "ixp_proximity", label: "IXP" },
  { key: "latency", label: "Latency" },
  { key: "land_planning", label: "Land" },
  { key: "resilience", label: "Resilience" },
  { key: "connection_speed", label: "Speed" },
  { key: "incentives", label: "Incentives" },
  { key: "regulatory_pathway", label: "Regulatory" },
];

const SITE_COLORS = ["#D4A018", "#0f62fe", "#24a148", "#f1c21b", "#da1e28", "#00bcd4"];

const GOOGLE_UK_SITES = [
  { name: "Waltham Cross", lat: 51.6862, lon: -0.0137 },
  { name: "North Weald", lat: 51.7237, lon: 0.1577 },
  { name: "Purfleet", lat: 51.4811, lon: 0.2385 },
  { name: "Teesside", lat: 54.5973, lon: -1.0580 },
];

const PROFILES = [
  { value: "google_hyperscale", label: "Google Hyperscale" },
  { value: "colocation", label: "Colocation" },
  { value: "edge", label: "Edge / On-Prem" },
  { value: "sovereign", label: "Sovereign Cloud" },
];

function verdictColor(v) {
  if (v === "GO") return "#24a148";
  if (v === "CAUTION") return "#f1c21b";
  return "#da1e28";
}

function scoreColor(s) {
  if (s >= 70) return "#24a148";
  if (s >= 45) return "#f1c21b";
  return "#da1e28";
}

function fmtNum(v, dec = 1) {
  if (v == null) return "--";
  return typeof v === "number" ? v.toFixed(dec) : String(v);
}

/* ─── 15-Axis Radar Chart (SVG) ──────────────────────────────────────── */

function RadarChart15({ scores, size = 260, color = "#D4A018" }) {
  const cx = size / 2, cy = size / 2, r = size / 2 - 35;
  const n = DIMENSIONS_15.length;
  const step = (2 * Math.PI) / n;

  const point = (i, val) => {
    const angle = -Math.PI / 2 + i * step;
    const d = (val / 100) * r;
    return [cx + d * Math.cos(angle), cy + d * Math.sin(angle)];
  };

  const rings = [20, 40, 60, 80, 100];

  return (
    <svg width={size} height={size} style={{ display: "block", margin: "0 auto" }}>
      {/* Grid rings */}
      {rings.map((v) => {
        const pts = Array.from({ length: n }, (_, i) => point(i, v).join(",")).join(" ");
        return (
          <polygon
            key={v}
            points={pts}
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={1}
          />
        );
      })}
      {/* Axis lines + labels */}
      {DIMENSIONS_15.map((dim, i) => {
        const [ex, ey] = point(i, 100);
        const [lx, ly] = point(i, 120);
        return (
          <g key={dim.key}>
            <line x1={cx} y1={cy} x2={ex} y2={ey} stroke="rgba(255,255,255,0.12)" strokeWidth={1} />
            <text
              x={lx}
              y={ly}
              textAnchor="middle"
              dominantBaseline="middle"
              fill="#999"
              fontSize={8}
              fontFamily="Inter, sans-serif"
            >
              {dim.label}
            </text>
          </g>
        );
      })}
      {/* Data polygon */}
      {(() => {
        const pts = DIMENSIONS_15.map((dim, i) => {
          const val = scores[dim.key] ?? 0;
          return point(i, val).join(",");
        }).join(" ");
        return (
          <>
            <polygon points={pts} fill={color} fillOpacity={0.2} stroke={color} strokeWidth={2} />
            {DIMENSIONS_15.map((dim, i) => {
              const val = scores[dim.key] ?? 0;
              const [px, py] = point(i, val);
              return <circle key={dim.key} cx={px} cy={py} r={3} fill={color} />;
            })}
          </>
        );
      })()}
    </svg>
  );
}

/* ─── Site Pill ──────────────────────────────────────────────────────── */

function SitePill({ site, idx, onRemove }) {
  const c = SITE_COLORS[idx % SITE_COLORS.length];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        background: `${c}22`,
        border: `1px solid ${c}`,
        borderRadius: 16,
        padding: "4px 12px",
        fontSize: 13,
        color: "#e0e0e0",
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: c, flexShrink: 0 }} />
      {site.name}
      <span
        onClick={() => onRemove(idx)}
        style={{ cursor: "pointer", marginLeft: 2, opacity: 0.6, fontWeight: 700 }}
      >
        x
      </span>
    </span>
  );
}

/* ─── Site Card ──────────────────────────────────────────────────────── */

function SiteCard({ site, idx }) {
  const c = SITE_COLORS[idx % SITE_COLORS.length];
  const s = site.dc_score ?? site.score ?? 0;
  const v = site.verdict || "CAUTION";
  const dims = site.dimensions || site.dimension_scores || {};

  return (
    <div
      style={{
        background: "#262637",
        borderRadius: 12,
        border: `1px solid ${c}44`,
        padding: 20,
        minWidth: 280,
        flex: "1 1 280px",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />
          <span style={{ fontWeight: 600, fontSize: 15, color: "#e0e0e0" }}>{site.name}</span>
        </div>
        <span
          style={{
            padding: "2px 10px",
            borderRadius: 10,
            fontSize: 11,
            fontWeight: 700,
            background: `${verdictColor(v)}22`,
            color: verdictColor(v),
            border: `1px solid ${verdictColor(v)}55`,
          }}
        >
          {v}
        </span>
      </div>

      {/* DC-SCORE */}
      <div style={{ textAlign: "center", margin: "8px 0 12px" }}>
        <div style={{ fontSize: 11, color: "#888", textTransform: "uppercase", letterSpacing: 1 }}>DC-Score</div>
        <div style={{ fontSize: 42, fontWeight: 800, color: scoreColor(s), lineHeight: 1.1 }}>
          {fmtNum(s, 0)}
        </div>
      </div>

      {/* Radar */}
      <RadarChart15 scores={dims} size={240} color={c} />

      {/* Key Metrics */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
          marginTop: 14,
          fontSize: 12,
        }}
      >
        {[
          { label: "Headroom MW", val: fmtNum(site.headroom_mw ?? site.grid_headroom_mw) },
          { label: "CFE%", val: fmtNum(site.cfe_pct ?? dims.cfe_score) },
          { label: "PUE", val: fmtNum(site.pue ?? site.estimated_pue, 2) },
          { label: "Incentive Value", val: site.incentive_value != null ? `£${(site.incentive_value / 1e6).toFixed(1)}M` : "--" },
        ].map((m) => (
          <div key={m.label} style={{ background: "#1a1a2e", borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>{m.label}</div>
            <div style={{ color: "#e0e0e0", fontWeight: 600 }}>{m.val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Dimension Bars ─────────────────────────────────────────────────── */

function DimensionBars({ siteResults }) {
  if (!siteResults || siteResults.length === 0) return null;

  return (
    <div style={{ background: "#262637", borderRadius: 12, padding: 20 }}>
      <h3 style={{ color: "#e0e0e0", fontSize: 15, fontWeight: 600, margin: "0 0 16px" }}>
        Dimension-by-Dimension Comparison
      </h3>
      {DIMENSIONS_15.map((dim) => {
        const values = siteResults.map((s) => {
          const dims = s.dimensions || s.dimension_scores || {};
          return dims[dim.key] ?? 0;
        });
        const maxVal = Math.max(...values);

        return (
          <div key={dim.key} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, color: "#999", marginBottom: 4 }}>{dim.label}</div>
            {siteResults.map((s, idx) => {
              const dims = s.dimensions || s.dimension_scores || {};
              const val = dims[dim.key] ?? 0;
              const c = SITE_COLORS[idx % SITE_COLORS.length];
              const isWinner = val === maxVal && val > 0;

              return (
                <div
                  key={idx}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    marginBottom: 2,
                    height: 20,
                  }}
                >
                  <span style={{ width: 80, fontSize: 10, color: "#aaa", flexShrink: 0, textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                    {s.name}
                  </span>
                  <div style={{ flex: 1, height: 14, background: "#1a1a2e", borderRadius: 4, position: "relative" }}>
                    <div
                      style={{
                        width: `${val}%`,
                        height: "100%",
                        background: c,
                        borderRadius: 4,
                        transition: "width 0.5s ease",
                      }}
                    />
                  </div>
                  <span style={{ fontSize: 10, color: "#ccc", width: 28, textAlign: "right" }}>{fmtNum(val, 0)}</span>
                  {isWinner && (
                    <span style={{ fontSize: 12, color: "#f1c21b", width: 16, textAlign: "center" }} title="Winner">
                      *
                    </span>
                  )}
                  {!isWinner && <span style={{ width: 16 }} />}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Ranking Table ──────────────────────────────────────────────────── */

function RankingTable({ siteResults }) {
  if (!siteResults || siteResults.length === 0) return null;

  const ranked = [...siteResults].sort((a, b) => (b.dc_score ?? b.score ?? 0) - (a.dc_score ?? a.score ?? 0));

  return (
    <div style={{ background: "#262637", borderRadius: 12, padding: 20, overflowX: "auto" }}>
      <h3 style={{ color: "#e0e0e0", fontSize: 15, fontWeight: 600, margin: "0 0 14px" }}>
        Site Rankings
      </h3>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #444" }}>
            <th style={thStyle}>#</th>
            <th style={{ ...thStyle, textAlign: "left" }}>Site</th>
            <th style={thStyle}>Score</th>
            <th style={thStyle}>Verdict</th>
            {DIMENSIONS_15.map((d) => (
              <th key={d.key} style={thStyle} title={d.label}>
                {d.label.slice(0, 6)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ranked.map((s, rank) => {
            const sc = s.dc_score ?? s.score ?? 0;
            const dims = s.dimensions || s.dimension_scores || {};
            const origIdx = siteResults.indexOf(s);
            const c = SITE_COLORS[origIdx % SITE_COLORS.length];
            return (
              <tr key={rank} style={{ borderBottom: "1px solid #333" }}>
                <td style={tdStyle}>{rank + 1}</td>
                <td style={{ ...tdStyle, textAlign: "left" }}>
                  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: c, marginRight: 6, verticalAlign: "middle" }} />
                  {s.name}
                </td>
                <td style={{ ...tdStyle, fontWeight: 700, color: scoreColor(sc) }}>{fmtNum(sc, 0)}</td>
                <td style={tdStyle}>
                  <span style={{ color: verdictColor(s.verdict || "CAUTION"), fontWeight: 600, fontSize: 11 }}>
                    {s.verdict || "--"}
                  </span>
                </td>
                {DIMENSIONS_15.map((d) => (
                  <td key={d.key} style={tdStyle}>{fmtNum(dims[d.key], 0)}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const thStyle = {
  padding: "6px 6px",
  color: "#999",
  fontWeight: 600,
  fontSize: 10,
  textTransform: "uppercase",
  textAlign: "center",
  whiteSpace: "nowrap",
};

const tdStyle = {
  padding: "6px 6px",
  color: "#e0e0e0",
  textAlign: "center",
  whiteSpace: "nowrap",
};

/* ═══════════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════════ */

export default function DCComparisonDashboard({ onClose, initialSites }) {
  const { selectedParcel } = useSite();

  const [sites, setSites] = useState(() => {
    if (initialSites && initialSites.length > 0) return initialSites;
    return [];
  });
  const [profile, setProfile] = useState("google_hyperscale");
  const [capacityMw, setCapacityMw] = useState(100);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Add-site form
  const [addName, setAddName] = useState("");
  const [addLat, setAddLat] = useState("");
  const [addLon, setAddLon] = useState("");

  const addSite = useCallback(
    (s) => {
      if (sites.length >= 6) return;
      if (sites.some((x) => x.name === s.name)) return;
      setSites((prev) => [...prev, s]);
      setResult(null);
    },
    [sites],
  );

  const removeSite = useCallback(
    (idx) => {
      setSites((prev) => prev.filter((_, i) => i !== idx));
      setResult(null);
    },
    [],
  );

  const addCustomSite = useCallback(() => {
    const lat = parseFloat(addLat);
    const lon = parseFloat(addLon);
    if (isNaN(lat) || isNaN(lon)) return;
    const name = addName.trim() || `Site (${lat.toFixed(3)}, ${lon.toFixed(3)})`;
    addSite({ name, lat, lon });
    setAddName("");
    setAddLat("");
    setAddLon("");
  }, [addName, addLat, addLon, addSite]);

  const runComparison = useCallback(async () => {
    if (sites.length < 2) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = sites.map((s) => ({ name: s.name, lat: s.lat, lon: s.lon }));
      const res = await api.dc.compare(payload, capacityMw, profile);
      if (!res) throw new Error("No response from comparison API");
      setResult(res);
    } catch (e) {
      setError(e.message || "Comparison failed");
    } finally {
      setLoading(false);
    }
  }, [sites, capacityMw, profile]);

  const siteResults = useMemo(() => {
    if (!result) return [];
    return result.sites || result.results || result.site_results || [];
  }, [result]);

  const recommendation = result?.recommendation || result?.summary || null;

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "#1a1a2e",
        color: "#e0e0e0",
        display: "flex",
        flexDirection: "column",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 24px",
          borderBottom: "1px solid #333",
          background: "#262637",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700 }}>Multi-Site Comparison</span>
          <span
            style={{
              background: "#D4A01822",
              color: "#D4A018",
              borderRadius: 10,
              padding: "2px 10px",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {sites.length} site{sites.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button onClick={() => window.print()} style={btnSecondary} title="Export PDF">
            Export PDF
          </button>
          <button onClick={onClose} style={btnClose}>
            Close
          </button>
        </div>
      </div>

      {/* ── Controls ─────────────────────────────────────────────────── */}
      <div
        style={{
          padding: "14px 24px",
          borderBottom: "1px solid #333",
          background: "#20203a",
          display: "flex",
          flexWrap: "wrap",
          gap: 14,
          alignItems: "flex-end",
          flexShrink: 0,
        }}
      >
        {/* Google reference sites */}
        <div>
          <div style={labelStyle}>Google UK Reference Sites</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {GOOGLE_UK_SITES.map((gs) => {
              const alreadyAdded = sites.some((s) => s.name === gs.name);
              return (
                <button
                  key={gs.name}
                  onClick={() => addSite(gs)}
                  disabled={alreadyAdded || sites.length >= 6}
                  style={{
                    ...btnSmall,
                    opacity: alreadyAdded ? 0.4 : 1,
                    cursor: alreadyAdded ? "default" : "pointer",
                  }}
                >
                  + {gs.name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Custom lat/lon */}
        <div>
          <div style={labelStyle}>Add Custom Site</div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              placeholder="Name"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              style={{ ...inputStyle, width: 100 }}
            />
            <input
              placeholder="Lat"
              value={addLat}
              onChange={(e) => setAddLat(e.target.value)}
              style={{ ...inputStyle, width: 72 }}
              type="number"
              step="0.001"
            />
            <input
              placeholder="Lon"
              value={addLon}
              onChange={(e) => setAddLon(e.target.value)}
              style={{ ...inputStyle, width: 72 }}
              type="number"
              step="0.001"
            />
            <button onClick={addCustomSite} disabled={sites.length >= 6} style={btnSmall}>
              Add Site
            </button>
          </div>
        </div>

        {/* Profile */}
        <div>
          <div style={labelStyle}>Profile</div>
          <select value={profile} onChange={(e) => setProfile(e.target.value)} style={selectStyle}>
            {PROFILES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        {/* Capacity slider */}
        <div>
          <div style={labelStyle}>Capacity: {capacityMw} MW</div>
          <input
            type="range"
            min={10}
            max={500}
            step={10}
            value={capacityMw}
            onChange={(e) => setCapacityMw(Number(e.target.value))}
            style={{ width: 160, accentColor: "#D4A018" }}
          />
        </div>

        {/* Compare button */}
        <button
          onClick={runComparison}
          disabled={sites.length < 2 || loading}
          style={{
            ...btnPrimary,
            opacity: sites.length < 2 || loading ? 0.5 : 1,
          }}
        >
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>

      {/* ── Selected sites pills ─────────────────────────────────────── */}
      {sites.length > 0 && (
        <div
          style={{
            padding: "10px 24px",
            borderBottom: "1px solid #333",
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 12, color: "#888", marginRight: 4 }}>Selected:</span>
          {sites.map((s, i) => (
            <SitePill key={s.name} site={s} idx={i} onRemove={removeSite} />
          ))}
        </div>
      )}

      {/* ── Error ────────────────────────────────────────────────────── */}
      {error && (
        <div style={{ padding: "10px 24px", background: "#da1e2822", color: "#da1e28", fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* ── Loading ──────────────────────────────────────────────────── */}
      {loading && (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ textAlign: "center" }}>
            <div style={spinnerStyle} />
            <div style={{ color: "#888", fontSize: 14, marginTop: 14 }}>
              Running {sites.length}-site comparison across 15 dimensions...
            </div>
          </div>
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────── */}
      {!loading && !result && (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ fontSize: 48, marginBottom: 12, opacity: 0.3 }}>&#9878;</div>
            <div style={{ fontSize: 16, color: "#999", marginBottom: 8 }}>
              Select at least 2 sites and click Compare
            </div>
            <div style={{ fontSize: 13, color: "#666" }}>
              The comparison evaluates 15 dimensions including power capacity, grid headroom, CFE%,
              cooling, connectivity, planning, resilience and incentives.
            </div>
          </div>
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────── */}
      {!loading && result && siteResults.length > 0 && (
        <div style={{ flex: 1, overflow: "auto", padding: 24 }}>
          {/* Recommendation */}
          {recommendation && (
            <div
              style={{
                background: "#D4A01811",
                border: "1px solid #D4A01844",
                borderRadius: 10,
                padding: "14px 18px",
                marginBottom: 20,
                fontSize: 14,
                lineHeight: 1.6,
                color: "#ccc",
              }}
            >
              <span style={{ fontWeight: 700, color: "#D4A018", marginRight: 8 }}>Recommendation:</span>
              {recommendation}
            </div>
          )}

          {/* Side-by-side cards */}
          <div
            style={{
              display: "flex",
              gap: 16,
              flexWrap: "wrap",
              marginBottom: 24,
            }}
          >
            {siteResults.map((s, i) => (
              <SiteCard key={s.name || i} site={s} idx={i} />
            ))}
          </div>

          {/* Dimension bars */}
          <div style={{ marginBottom: 24 }}>
            <DimensionBars siteResults={siteResults} />
          </div>

          {/* Ranking table */}
          <RankingTable siteResults={siteResults} />
        </div>
      )}
    </div>
  );
}

/* ─── Shared inline styles ───────────────────────────────────────────── */

const labelStyle = {
  fontSize: 11,
  color: "#888",
  marginBottom: 4,
  textTransform: "uppercase",
  letterSpacing: 0.5,
};

const inputStyle = {
  background: "#1a1a2e",
  border: "1px solid #444",
  borderRadius: 6,
  color: "#e0e0e0",
  padding: "6px 10px",
  fontSize: 13,
  outline: "none",
};

const selectStyle = {
  background: "#1a1a2e",
  border: "1px solid #444",
  borderRadius: 6,
  color: "#e0e0e0",
  padding: "6px 10px",
  fontSize: 13,
  outline: "none",
  cursor: "pointer",
};

const btnSmall = {
  background: "#D4A01822",
  border: "1px solid #D4A01855",
  borderRadius: 6,
  color: "#b8b0f0",
  padding: "5px 12px",
  fontSize: 12,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const btnPrimary = {
  background: "#D4A018",
  border: "none",
  borderRadius: 8,
  color: "#fff",
  padding: "8px 24px",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const btnSecondary = {
  background: "transparent",
  border: "1px solid #555",
  borderRadius: 6,
  color: "#ccc",
  padding: "6px 14px",
  fontSize: 13,
  cursor: "pointer",
};

const btnClose = {
  background: "transparent",
  border: "1px solid #555",
  borderRadius: 6,
  color: "#e0e0e0",
  padding: "6px 16px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

const spinnerStyle = {
  width: 36,
  height: 36,
  border: "3px solid #333",
  borderTopColor: "#D4A018",
  borderRadius: "50%",
  margin: "0 auto",
  animation: "spin 0.8s linear infinite",
};
