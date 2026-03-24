import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";

const FONT = "'DM Sans', 'Inter', -apple-system, sans-serif";
const MONO = "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace";
const BORDER = "#E8EAED";
const GOLD = "#D4A017";
const GOLD_BG = "rgba(212, 160, 23, 0.06)";
const GREEN = "#059669";
const GREEN_BG = "rgba(5, 150, 105, 0.08)";
const RED = "#DC2626";
const RED_BG = "rgba(220, 38, 38, 0.08)";
const HEADER_BG = "#F9FAFB";
const MUTED = "#6B7280";

const LS_KEY = "princeps_site_comparison";

/* ── metric definitions ────────────────────────────────────── */

const METRICS = [
  { key: "headroom_mw",   label: "Grid Headroom",         unit: "MW",     fmt: v => v?.toFixed(1),   higher: true  },
  { key: "distance_km",   label: "Distance to Substation", unit: "km",     fmt: v => v?.toFixed(2),   higher: false },
  { key: "cost_gbp",      label: "Connection Cost",        unit: "\u00a3k",    fmt: v => v != null ? Math.round(v / 1000).toLocaleString() : null, higher: false },
  { key: "queue_depth",   label: "Queue Depth",            unit: "",       fmt: v => v?.toString(),   higher: false },
  { key: "voltage_kv",    label: "Voltage",                unit: "kV",     fmt: v => v?.toFixed(0),   higher: true  },
  { key: "env_risk",      label: "Environmental Risk",     unit: "",       fmt: v => v,               higher: false, categorical: true, order: ["Low", "Medium", "High", "Critical"] },
  { key: "planning_rate", label: "Planning Approval Rate", unit: "%",      fmt: v => v?.toFixed(1),   higher: true  },
  { key: "land_value",    label: "Land Value",             unit: "\u00a3/acre", fmt: v => v != null ? Math.round(v).toLocaleString() : null, higher: false },
  { key: "bng_cost",      label: "BNG Cost",               unit: "\u00a3k",    fmt: v => v != null ? Math.round(v).toLocaleString() : null, higher: false },
  { key: "cfe_pct",       label: "CFE%",                   unit: "%",      fmt: v => v?.toFixed(1),   higher: true  },
  { key: "verdict",       label: "Verdict",                unit: "",       fmt: v => v,               higher: true,  categorical: true, order: ["NO-GO", "CAUTION", "GO"] },
  { key: "score",         label: "Overall Score",          unit: "/100",   fmt: v => v?.toFixed(0),   higher: true  },
];

/* ── helpers ───────────────────────────────────────────────── */

function numericVal(metric, v) {
  if (v == null) return null;
  if (metric.categorical && metric.order) return metric.order.indexOf(v);
  if (typeof v === "number") return v;
  return null;
}

function bestWorst(metric, values) {
  const nums = values.map(v => numericVal(metric, v)).filter(n => n != null);
  if (nums.length < 2) return { best: null, worst: null };
  const best = metric.higher ? Math.max(...nums) : Math.min(...nums);
  const worst = metric.higher ? Math.min(...nums) : Math.max(...nums);
  return { best, worst };
}

function verdictColor(v) {
  if (v === "GO") return GREEN;
  if (v === "CAUTION") return "#D97706";
  if (v === "NO-GO") return RED;
  return "#111827";
}

function exportCSV(sites) {
  const header = ["Metric", "Unit", ...sites.map(s => s.name)];
  const rows = [header.join(",")];
  for (const m of METRICS) {
    const cells = [
      `"${m.label}"`,
      `"${m.unit}"`,
      ...sites.map(s => {
        const v = s.metrics?.[m.key];
        if (v == null) return "";
        if (m.key === "cost_gbp") return v;
        return typeof v === "number" ? v : `"${v}"`;
      }),
    ];
    rows.push(cells.join(","));
  }
  // site metadata rows
  rows.push(["Latitude", "", ...sites.map(s => s.lat)].join(","));
  rows.push(["Longitude", "", ...sites.map(s => s.lon)].join(","));
  rows.push(["Capacity (MW)", "", ...sites.map(s => s.capacity_mw ?? "")].join(","));
  rows.push(["Technology", "", ...sites.map(s => `"${s.technology ?? ""}"`)].join(","));

  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `princeps_site_comparison_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ── Add-site modal (coordinates entry) ────────────────────── */

function AddSiteModal({ onAdd, onCancel }) {
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!name.trim() || !lat || !lon) return;
    onAdd({ name: name.trim(), lat: parseFloat(lat), lon: parseFloat(lon) });
  };

  const inputStyle = {
    width: "100%", padding: "8px 10px", border: `1px solid ${BORDER}`, borderRadius: 6,
    fontFamily: MONO, fontSize: 13, outline: "none", boxSizing: "border-box",
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 9999,
    }} onClick={onCancel}>
      <form onClick={e => e.stopPropagation()} onSubmit={handleSubmit} style={{
        background: "#fff", borderRadius: 12, padding: 24, width: 340,
        boxShadow: "0 20px 60px rgba(0,0,0,0.15)", fontFamily: FONT,
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16, color: "#111827" }}>
          Add Site to Comparison
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: MUTED, display: "block", marginBottom: 4 }}>SITE NAME</label>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Greenfield Alpha" style={inputStyle} autoFocus />
        </div>
        <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: MUTED, display: "block", marginBottom: 4 }}>LATITUDE</label>
            <input type="number" step="any" value={lat} onChange={e => setLat(e.target.value)} placeholder="52.4862" style={inputStyle} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: MUTED, display: "block", marginBottom: 4 }}>LONGITUDE</label>
            <input type="number" step="any" value={lon} onChange={e => setLon(e.target.value)} placeholder="-1.8904" style={inputStyle} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" onClick={onCancel} style={{
            padding: "8px 16px", borderRadius: 6, border: `1px solid ${BORDER}`, background: "#fff",
            fontFamily: FONT, fontSize: 13, cursor: "pointer", color: MUTED,
          }}>Cancel</button>
          <button type="submit" style={{
            padding: "8px 16px", borderRadius: 6, border: "none", background: "#111827", color: "#fff",
            fontFamily: FONT, fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>Add Site</button>
        </div>
      </form>
    </div>
  );
}

/* ── Main component ────────────────────────────────────────── */

export default function SiteComparison({ sites: propSites = [], onAddSite, onRemoveSite, onClose }) {
  const [sites, setSites] = useState(() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {}
    return propSites;
  });

  const [sortKey, setSortKey] = useState(null);
  const [sortAsc, setSortAsc] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [hoveredCol, setHoveredCol] = useState(null);
  const scrollRef = useRef(null);

  // Sync prop sites in
  useEffect(() => {
    if (propSites.length > 0) {
      setSites(prev => {
        const existingIds = new Set(prev.map(s => s.id));
        const merged = [...prev];
        for (const s of propSites) {
          if (!existingIds.has(s.id)) merged.push(s);
          else {
            const idx = merged.findIndex(x => x.id === s.id);
            if (idx !== -1) merged[idx] = s;
          }
        }
        return merged;
      });
    }
  }, [propSites]);

  // Persist to localStorage
  useEffect(() => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(sites)); } catch {}
  }, [sites]);

  const handleRemove = useCallback((id) => {
    setSites(prev => prev.filter(s => s.id !== id));
    onRemoveSite?.(id);
  }, [onRemoveSite]);

  const handleAddManual = useCallback((siteData) => {
    const newSite = {
      id: `manual_${Date.now()}`,
      ...siteData,
      capacity_mw: null,
      technology: null,
      metrics: {},
    };
    setSites(prev => [...prev, newSite]);
    onAddSite?.(newSite);
    setShowAddModal(false);
  }, [onAddSite]);

  // Sorting
  const sortedSites = useMemo(() => {
    if (!sortKey) return sites;
    const metric = METRICS.find(m => m.key === sortKey);
    if (!metric) return sites;
    return [...sites].sort((a, b) => {
      const va = numericVal(metric, a.metrics?.[sortKey]);
      const vb = numericVal(metric, b.metrics?.[sortKey]);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return sortAsc ? va - vb : vb - va;
    });
  }, [sites, sortKey, sortAsc]);

  // Winner (highest overall score)
  const winnerId = useMemo(() => {
    let best = null, bestScore = -Infinity;
    for (const s of sites) {
      const sc = s.metrics?.score;
      if (sc != null && sc > bestScore) { bestScore = sc; best = s.id; }
    }
    return sites.length >= 2 ? best : null;
  }, [sites]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(prev => !prev);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const LABEL_COL_W = 180;
  const SITE_COL_W = 160;

  /* ── render ──────────────────────────────────────────────── */

  if (sites.length === 0) {
    return (
      <div style={{
        fontFamily: FONT, padding: 40, textAlign: "center", background: "#fff",
        border: `1px solid ${BORDER}`, borderRadius: 12,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#111827", marginBottom: 8 }}>
          Site Comparison
        </div>
        <div style={{ fontSize: 13, color: MUTED, marginBottom: 20 }}>
          No sites added yet. Click a site on the map or add one manually.
        </div>
        <button onClick={() => setShowAddModal(true)} style={{
          padding: "10px 20px", borderRadius: 8, border: "none", background: "#111827",
          color: "#fff", fontFamily: FONT, fontSize: 13, fontWeight: 600, cursor: "pointer",
        }}>
          + Add Site Manually
        </button>
        {showAddModal && <AddSiteModal onAdd={handleAddManual} onCancel={() => setShowAddModal(false)} />}
      </div>
    );
  }

  return (
    <div style={{
      fontFamily: FONT, background: "#fff", border: `1px solid ${BORDER}`,
      borderRadius: 12, overflow: "hidden", display: "flex", flexDirection: "column",
      maxHeight: "100%",
    }}>
      {/* ── toolbar ─────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px", borderBottom: `1px solid ${BORDER}`, background: HEADER_BG,
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "#111827", letterSpacing: "-0.01em" }}>
            Site Comparison
          </span>
          <span style={{
            fontSize: 11, fontWeight: 600, color: MUTED, background: "#F3F4F6",
            padding: "2px 8px", borderRadius: 10,
          }}>
            {sites.length} site{sites.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setShowAddModal(true)} style={{
            padding: "6px 12px", borderRadius: 6, border: `1px solid ${BORDER}`, background: "#fff",
            fontFamily: FONT, fontSize: 12, cursor: "pointer", color: "#111827", fontWeight: 600,
          }}>
            + Add Site
          </button>
          <button onClick={() => exportCSV(sortedSites)} style={{
            padding: "6px 12px", borderRadius: 6, border: `1px solid ${BORDER}`, background: "#fff",
            fontFamily: FONT, fontSize: 12, cursor: "pointer", color: "#111827", fontWeight: 500,
          }}>
            Export CSV
          </button>
          {onClose && (
            <button onClick={onClose} style={{
              padding: "6px 10px", borderRadius: 6, border: `1px solid ${BORDER}`, background: "#fff",
              fontFamily: FONT, fontSize: 14, cursor: "pointer", color: MUTED, lineHeight: 1,
            }}>
              \u00d7
            </button>
          )}
        </div>
      </div>

      {/* ── table ───────────────────────────────────────────── */}
      <div ref={scrollRef} style={{ overflow: "auto", flex: 1 }}>
        <table style={{ borderCollapse: "collapse", minWidth: "100%" }}>
          <thead>
            {/* ── site name header row ──────────────────────── */}
            <tr>
              <th style={{
                position: "sticky", left: 0, zIndex: 3, background: HEADER_BG,
                minWidth: LABEL_COL_W, width: LABEL_COL_W, padding: "10px 14px",
                textAlign: "left", borderBottom: `1px solid ${BORDER}`, borderRight: `1px solid ${BORDER}`,
                fontSize: 11, fontWeight: 600, color: MUTED, textTransform: "uppercase", letterSpacing: "0.04em",
              }}>
                Metric
              </th>
              {sortedSites.map((site, ci) => {
                const isWinner = site.id === winnerId;
                return (
                  <th
                    key={site.id}
                    onMouseEnter={() => setHoveredCol(ci)}
                    onMouseLeave={() => setHoveredCol(null)}
                    style={{
                      minWidth: SITE_COL_W, width: SITE_COL_W, padding: "8px 12px",
                      textAlign: "center", borderBottom: `1px solid ${BORDER}`,
                      borderRight: ci < sortedSites.length - 1 ? `1px solid ${BORDER}` : "none",
                      background: isWinner ? GOLD_BG : HEADER_BG,
                      position: "relative",
                      borderTop: isWinner ? `3px solid ${GOLD}` : "3px solid transparent",
                    }}
                  >
                    {/* remove button */}
                    <button
                      onClick={() => handleRemove(site.id)}
                      style={{
                        position: "absolute", top: 4, right: 4, width: 18, height: 18,
                        borderRadius: "50%", border: "none", background: hoveredCol === ci ? "#F3F4F6" : "transparent",
                        color: MUTED, cursor: "pointer", fontSize: 12, lineHeight: "18px", padding: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}
                    >
                      \u00d7
                    </button>
                    {/* winner badge */}
                    {isWinner && (
                      <div style={{
                        fontSize: 9, fontWeight: 800, color: GOLD, letterSpacing: "0.1em",
                        textTransform: "uppercase", marginBottom: 2,
                      }}>
                        WINNER
                      </div>
                    )}
                    <div style={{
                      fontSize: 13, fontWeight: 700, color: "#111827",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      maxWidth: SITE_COL_W - 30,
                    }}>
                      {site.name}
                    </div>
                    <div style={{ fontSize: 10, color: MUTED, fontFamily: MONO, marginTop: 2 }}>
                      {site.lat?.toFixed(4)}, {site.lon?.toFixed(4)}
                    </div>
                    {site.capacity_mw != null && (
                      <div style={{ fontSize: 10, color: MUTED, marginTop: 1 }}>
                        {site.capacity_mw} MW {site.technology ?? ""}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {METRICS.map((metric, ri) => {
              const values = sortedSites.map(s => s.metrics?.[metric.key] ?? null);
              const { best, worst } = bestWorst(metric, values);

              return (
                <tr key={metric.key}>
                  {/* ── metric label (sticky) ─────────────── */}
                  <td
                    onClick={() => handleSort(metric.key)}
                    style={{
                      position: "sticky", left: 0, zIndex: 2,
                      background: ri % 2 === 0 ? "#fff" : "#FAFBFC",
                      minWidth: LABEL_COL_W, width: LABEL_COL_W, padding: "9px 14px",
                      borderBottom: `1px solid ${BORDER}`, borderRight: `1px solid ${BORDER}`,
                      fontSize: 12, fontWeight: 600, color: "#374151", cursor: "pointer",
                      userSelect: "none", whiteSpace: "nowrap",
                    }}
                  >
                    <span>{metric.label}</span>
                    {metric.unit && (
                      <span style={{ fontSize: 10, color: MUTED, marginLeft: 4, fontWeight: 400 }}>
                        {metric.unit}
                      </span>
                    )}
                    {sortKey === metric.key && (
                      <span style={{ marginLeft: 4, fontSize: 10, color: MUTED }}>
                        {sortAsc ? "\u25b2" : "\u25bc"}
                      </span>
                    )}
                  </td>
                  {/* ── values ────────────────────────────── */}
                  {sortedSites.map((site, ci) => {
                    const raw = site.metrics?.[metric.key] ?? null;
                    const nv = numericVal(metric, raw);
                    const isBest = nv != null && nv === best && best !== worst;
                    const isWorst = nv != null && nv === worst && best !== worst;
                    const isWinner = site.id === winnerId;

                    let bg = ri % 2 === 0 ? "#fff" : "#FAFBFC";
                    let fg = "#111827";
                    if (isBest) { bg = GREEN_BG; fg = GREEN; }
                    else if (isWorst) { bg = RED_BG; fg = RED; }
                    if (isWinner && !isBest && !isWorst) bg = GOLD_BG;

                    // special verdict rendering
                    if (metric.key === "verdict" && raw) {
                      fg = verdictColor(raw);
                    }

                    const formatted = raw != null ? metric.fmt(raw) : "\u2014";

                    return (
                      <td
                        key={site.id}
                        style={{
                          minWidth: SITE_COL_W, width: SITE_COL_W, padding: "9px 12px",
                          textAlign: "center", borderBottom: `1px solid ${BORDER}`,
                          borderRight: ci < sortedSites.length - 1 ? `1px solid ${BORDER}` : "none",
                          background: bg, color: fg,
                          fontFamily: metric.categorical ? FONT : MONO,
                          fontSize: 13, fontWeight: isBest ? 700 : 500,
                          transition: "background 0.15s",
                        }}
                      >
                        {metric.key === "verdict" && raw ? (
                          <span style={{
                            display: "inline-block", padding: "2px 10px", borderRadius: 4,
                            fontSize: 11, fontWeight: 800, letterSpacing: "0.05em",
                            background: raw === "GO" ? GREEN_BG : raw === "NO-GO" ? RED_BG : "rgba(217, 119, 6, 0.08)",
                            color: verdictColor(raw),
                          }}>
                            {raw}
                          </span>
                        ) : metric.key === "score" && raw != null ? (
                          <span style={{ fontWeight: 700 }}>
                            {formatted}
                            <span style={{ fontSize: 10, fontWeight: 400, color: MUTED, marginLeft: 1 }}>/100</span>
                          </span>
                        ) : (
                          formatted
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showAddModal && <AddSiteModal onAdd={handleAddManual} onCancel={() => setShowAddModal(false)} />}
    </div>
  );
}
