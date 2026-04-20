import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";

/**
 * BuildableAreaPlayground
 *
 * Customer-visible filter playground (Glint-parity moat).
 * Left: exclusion layer toggles (AONB, SSSI, flood, green belt, ALC, slope,
 * land use, distance-to-substation). Right: live map preview of remaining
 * buildable polygons, running buildable_ha total, top-5 candidate parcels.
 *
 * Calls GET /api/analysis/buildable_area?object_id=<projectId>&<filters>
 * (BOT-I's endpoint). Debounces filter changes 250ms.
 *
 * Renders a friendly skeleton when the endpoint is not live yet.
 */

const LIGHT_GOLD = "#F5E9C8";
const GOLD = "#C9A64B";
const INK = "#1a1a1a";

// Exclusion layers — the toggles on the left panel.
// Each has: id (query param), label, help text, default enabled.
const EXCLUSION_LAYERS = [
  { id: "aonb",            label: "AONB",                     help: "Area of Outstanding Natural Beauty",   defaultOn: true  },
  { id: "sssi",            label: "SSSI",                     help: "Sites of Special Scientific Interest", defaultOn: true  },
  { id: "flood_zone_3",    label: "Flood zone 3",             help: "EA high-risk flood zones",             defaultOn: true  },
  { id: "flood_zone_2",    label: "Flood zone 2",             help: "EA medium-risk flood zones",           defaultOn: false },
  { id: "green_belt",      label: "Green belt",               help: "MHCLG designated green belt",          defaultOn: true  },
  { id: "alc_grade_1_2",   label: "ALC grade 1 and 2",        help: "Best-and-most-versatile farmland",     defaultOn: true  },
  { id: "alc_grade_3a",    label: "ALC grade 3a",             help: "Upper sub-tier of good farmland",      defaultOn: false },
  { id: "slope_gt_10pct",  label: "Slope more than 10%",      help: "Terrain steeper than 10%",             defaultOn: true  },
  { id: "urban_land_use",  label: "Urban/residential land",   help: "Dynamic World built/urban classes",    defaultOn: true  },
  { id: "woodland",        label: "Ancient woodland",         help: "Natural England ancient woodland",     defaultOn: true  },
];

// Range filters rendered below the toggle list.
const RANGE_FILTERS = [
  { id: "max_distance_to_substation_km", label: "Max distance to substation (km)", min: 0, max: 20, step: 0.5, defaultValue: 5 },
  { id: "min_parcel_ha",                 label: "Min parcel size (ha)",            min: 0, max: 100, step: 1,  defaultValue: 5 },
];

export default function BuildableAreaPlayground() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  // Filter state — map of filter_id -> enabled (for toggles) or number (for ranges).
  const [toggles, setToggles] = useState(() => {
    const init = {};
    for (const l of EXCLUSION_LAYERS) init[l.id] = l.defaultOn;
    return init;
  });
  const [ranges, setRanges] = useState(() => {
    const init = {};
    for (const r of RANGE_FILTERS) init[r.id] = r.defaultValue;
    return init;
  });

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [feedOk, setFeedOk] = useState(true); // false after a 404
  const [errorMsg, setErrorMsg] = useState(null);

  const abortRef = useRef(null);
  const debounceRef = useRef(null);

  // Build query string from current filter state.
  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (projectId) params.set("object_id", projectId);
    const excl = EXCLUSION_LAYERS.filter(l => toggles[l.id]).map(l => l.id).join(",");
    if (excl) params.set("exclude", excl);
    for (const r of RANGE_FILTERS) params.set(r.id, String(ranges[r.id]));
    return params.toString();
  }, [projectId, toggles, ranges]);

  // Debounced fetch with AbortController.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort();
      abortRef.current = new AbortController();
      setLoading(true);
      setErrorMsg(null);
      fetch(`/api/analysis/buildable_area?${queryString}`, { signal: abortRef.current.signal })
        .then(async (res) => {
          if (res.status === 404) {
            setFeedOk(false);
            return null;
          }
          if (!res.ok) {
            setErrorMsg(`Server returned ${res.status}`);
            return null;
          }
          setFeedOk(true);
          return res.json();
        })
        .then((data) => {
          if (data) setResult(data);
          setLoading(false);
        })
        .catch((err) => {
          if (err.name !== "AbortError") {
            setErrorMsg(err.message || "Network error");
            setLoading(false);
          }
        });
    }, 250);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [queryString]);

  // Clean up abort on unmount.
  useEffect(() => {
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, []);

  const handleToggle = useCallback((id) => {
    setToggles(prev => ({ ...prev, [id]: !prev[id] }));
  }, []);
  const handleRange = useCallback((id, value) => {
    setRanges(prev => ({ ...prev, [id]: Number(value) }));
  }, []);

  const buildableHa = result?.buildable_ha ?? result?.buildable_area_ha ?? null;
  const totalHa     = result?.total_ha ?? result?.total_area_ha ?? null;
  const excludedHa  = (totalHa != null && buildableHa != null) ? (totalHa - buildableHa) : null;
  const candidates  = Array.isArray(result?.top_candidates) ? result.top_candidates.slice(0, 5) : [];

  const activeToggleCount = Object.values(toggles).filter(Boolean).length;

  return (
    <div style={styles.root}>
      {/* Header */}
      <header style={styles.header}>
        <button onClick={() => navigate(-1)} style={styles.backBtn} aria-label="Back">
          &larr; Back
        </button>
        <div>
          <div style={styles.title}>Buildable area playground</div>
          <div style={styles.subtitle}>
            {projectId ? <>Project <span style={styles.mono}>{projectId}</span></> : "No project selected"}
            {" · "}
            {activeToggleCount} of {EXCLUSION_LAYERS.length} exclusions active
          </div>
        </div>
        <div style={styles.headerRight}>
          {loading && <span style={styles.loadingPill}>Recomputing…</span>}
          {!feedOk && <span style={styles.warnPill}>Data feed not yet wired</span>}
        </div>
      </header>

      <div style={styles.body}>
        {/* ───────────────── Left panel: filter toggles ───────────────── */}
        <aside style={styles.leftPanel}>
          <div style={styles.sectionTitle}>Exclusion layers</div>
          <ul style={styles.list}>
            {EXCLUSION_LAYERS.map((layer) => (
              <li key={layer.id} style={styles.listItem}>
                <label style={styles.toggleRow}>
                  <input
                    type="checkbox"
                    checked={!!toggles[layer.id]}
                    onChange={() => handleToggle(layer.id)}
                    style={styles.checkbox}
                  />
                  <span style={styles.toggleLabel}>{layer.label}</span>
                </label>
                <div style={styles.toggleHelp}>{layer.help}</div>
              </li>
            ))}
          </ul>

          <div style={{ ...styles.sectionTitle, marginTop: 20 }}>Thresholds</div>
          <ul style={styles.list}>
            {RANGE_FILTERS.map((r) => (
              <li key={r.id} style={styles.listItem}>
                <div style={styles.rangeLabel}>
                  <span>{r.label}</span>
                  <span style={styles.rangeValue}>{ranges[r.id]}</span>
                </div>
                <input
                  type="range"
                  min={r.min} max={r.max} step={r.step}
                  value={ranges[r.id]}
                  onChange={(e) => handleRange(r.id, e.target.value)}
                  style={styles.range}
                />
              </li>
            ))}
          </ul>
        </aside>

        {/* ───────────────── Right panel: map + metrics ───────────────── */}
        <section style={styles.rightPanel}>
          {/* Running-total strip */}
          <div style={styles.metricStrip}>
            <MetricCard label="Buildable area" value={fmtHa(buildableHa)} accent />
            <MetricCard label="Excluded"       value={fmtHa(excludedHa)} />
            <MetricCard label="Total site"     value={fmtHa(totalHa)} />
            <MetricCard label="Candidates"     value={candidates.length ? String(candidates.length) : "—"} />
          </div>

          {/* Map preview */}
          <div style={styles.mapArea}>
            {feedOk ? (
              <MapPreview result={result} loading={loading} />
            ) : (
              <FeedOfflineState />
            )}
            {errorMsg && <div style={styles.errorBar}>{errorMsg}</div>}
          </div>

          {/* Top-5 candidate parcels */}
          <div style={styles.candidatesPanel}>
            <div style={styles.sectionTitle}>Top 5 candidate parcels</div>
            {candidates.length > 0 ? (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Parcel</th>
                    <th style={styles.th}>Area (ha)</th>
                    <th style={styles.th}>Score</th>
                    <th style={styles.th}>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c, i) => (
                    <tr key={c.parcel_id || c.id || i}>
                      <td style={styles.td}><span style={styles.mono}>{c.parcel_id || c.id || `#${i + 1}`}</span></td>
                      <td style={styles.td}>{fmtNum(c.area_ha ?? c.buildable_ha, 1)}</td>
                      <td style={styles.td}>{fmtNum(c.score, 2)}</td>
                      <td style={styles.td}>{c.note || c.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={styles.emptyState}>
                {feedOk
                  ? "No candidate parcels returned yet. Adjust filters to widen the search."
                  : "Candidates will appear here once the buildable_area endpoint is live."}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

function MetricCard({ label, value, accent }) {
  return (
    <div style={{ ...styles.metricCard, ...(accent ? styles.metricCardAccent : null) }}>
      <div style={styles.metricLabel}>{label}</div>
      <div style={styles.metricValue}>{value}</div>
    </div>
  );
}

function MapPreview({ result, loading }) {
  // Lightweight SVG preview of buildable polygons when endpoint returns
  // a GeoJSON-like `buildable_geojson`. We bbox-normalise coordinates so
  // this renders without a full MapView dependency.
  const features = result?.buildable_geojson?.features || [];

  if (features.length === 0) {
    return (
      <div style={styles.mapPlaceholder}>
        <div style={styles.mapPlaceholderTitle}>
          {loading ? "Loading buildable polygons…" : "No buildable polygons yet"}
        </div>
        <div style={styles.mapPlaceholderSub}>
          When the endpoint returns a <span style={styles.mono}>buildable_geojson</span>,
          the remaining developable area will be drawn here.
        </div>
      </div>
    );
  }

  const bbox = computeBbox(features);
  if (!bbox) return <div style={styles.mapPlaceholder}>Unable to compute bounding box</div>;
  const [minLon, minLat, maxLon, maxLat] = bbox;
  const w = 800, h = 500;
  const pad = 20;
  const scaleX = (w - pad * 2) / Math.max(1e-9, (maxLon - minLon));
  const scaleY = (h - pad * 2) / Math.max(1e-9, (maxLat - minLat));
  const proj = ([lon, lat]) => [
    pad + (lon - minLon) * scaleX,
    h - pad - (lat - minLat) * scaleY,
  ];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={styles.mapSvg} preserveAspectRatio="xMidYMid meet">
      <rect x={0} y={0} width={w} height={h} fill={LIGHT_GOLD} fillOpacity={0.35} />
      {features.map((f, i) => {
        const geom = f.geometry;
        if (!geom) return null;
        const rings = geom.type === "Polygon" ? geom.coordinates
                    : geom.type === "MultiPolygon" ? geom.coordinates.flat() : [];
        return rings.map((ring, j) => (
          <polygon
            key={`${i}-${j}`}
            points={ring.map(proj).map(([x, y]) => `${x},${y}`).join(" ")}
            fill={GOLD} fillOpacity={0.55}
            stroke={INK} strokeWidth={0.8}
          />
        ));
      })}
    </svg>
  );
}

function FeedOfflineState() {
  return (
    <div style={styles.feedOffline}>
      <div style={styles.feedOfflineTitle}>Data feed not yet wired</div>
      <div style={styles.feedOfflineBody}>
        The endpoint <span style={styles.mono}>GET /api/analysis/buildable_area</span>{" "}
        is not yet responding for this project. The layout and controls are live —
        toggles will trigger the endpoint once BOT-I ships it.
      </div>
      <div style={styles.feedOfflineHint}>
        Waiting on: <span style={styles.mono}>GET /api/analysis/buildable_area?object_id=…</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function fmtHa(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Number(v).toFixed(1)} ha`;
}
function fmtNum(v, d = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toFixed(d);
}

function computeBbox(features) {
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity;
  const walk = (coords) => {
    if (typeof coords[0] === "number") {
      const [lon, lat] = coords;
      if (lon < minLon) minLon = lon;
      if (lat < minLat) minLat = lat;
      if (lon > maxLon) maxLon = lon;
      if (lat > maxLat) maxLat = lat;
    } else {
      for (const c of coords) walk(c);
    }
  };
  for (const f of features) {
    if (f?.geometry?.coordinates) walk(f.geometry.coordinates);
  }
  if (!isFinite(minLon)) return null;
  return [minLon, minLat, maxLon, maxLat];
}

// ─────────────────────────────────────────────────────────────
// Styles — light-gold palette, reuse CSS vars where sensible.
// ─────────────────────────────────────────────────────────────
const styles = {
  root: {
    position: "fixed", inset: 0, zIndex: 50,
    display: "flex", flexDirection: "column",
    background: "var(--bg, #F2F3F5)",
    color: INK,
    fontFamily: "var(--font-sans, 'DM Sans'), -apple-system, sans-serif",
    overflow: "hidden",
  },
  header: {
    display: "flex", alignItems: "center", gap: 16,
    padding: "14px 24px",
    borderBottom: "1px solid var(--cds-border-subtle, #E8EAED)",
    background: "#fff",
    flexShrink: 0,
  },
  backBtn: {
    background: "transparent", border: `1px solid ${GOLD}`, color: INK,
    padding: "6px 12px", borderRadius: 6, cursor: "pointer",
    fontSize: 13, fontWeight: 500, fontFamily: "inherit",
  },
  title: { fontSize: 18, fontWeight: 700, color: INK, lineHeight: 1.2 },
  subtitle: { fontSize: 12, color: "var(--muted, #6B7280)", marginTop: 2 },
  headerRight: { marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" },
  loadingPill: {
    fontSize: 11, fontWeight: 600, color: INK,
    background: LIGHT_GOLD, padding: "4px 10px", borderRadius: 999,
    border: `1px solid ${GOLD}`,
  },
  warnPill: {
    fontSize: 11, fontWeight: 600, color: "#92400E",
    background: "#FEF3C7", padding: "4px 10px", borderRadius: 999,
    border: "1px solid #F59E0B",
  },

  body: { flex: 1, display: "flex", overflow: "hidden" },

  leftPanel: {
    width: 320, padding: 20, overflowY: "auto",
    background: "#fff",
    borderRight: "1px solid var(--cds-border-subtle, #E8EAED)",
    flexShrink: 0,
  },
  sectionTitle: {
    fontSize: 11, fontWeight: 700, color: INK,
    textTransform: "uppercase", letterSpacing: 0.8,
    marginBottom: 10,
  },
  list: { listStyle: "none", padding: 0, margin: 0 },
  listItem: { marginBottom: 12 },
  toggleRow: { display: "flex", alignItems: "center", gap: 10, cursor: "pointer", userSelect: "none" },
  checkbox: { accentColor: GOLD, width: 16, height: 16, cursor: "pointer" },
  toggleLabel: { fontSize: 13, fontWeight: 500, color: INK },
  toggleHelp: { fontSize: 11, color: "var(--muted, #6B7280)", marginLeft: 26, marginTop: 2 },
  rangeLabel: { display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 500, color: INK, marginBottom: 6 },
  rangeValue: { fontFamily: "var(--mono, monospace)", color: GOLD, fontWeight: 700 },
  range: { width: "100%", accentColor: GOLD },

  rightPanel: {
    flex: 1, padding: 20, overflowY: "auto",
    display: "flex", flexDirection: "column", gap: 16,
  },

  metricStrip: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 },
  metricCard: {
    background: "#fff", borderRadius: 8, padding: "12px 16px",
    border: "1px solid var(--cds-border-subtle, #E8EAED)",
  },
  metricCardAccent: { background: LIGHT_GOLD, borderColor: GOLD },
  metricLabel: { fontSize: 11, color: "var(--muted, #6B7280)", textTransform: "uppercase", letterSpacing: 0.6, fontWeight: 600 },
  metricValue: { fontSize: 22, fontWeight: 700, color: INK, marginTop: 4, fontFamily: "var(--mono, monospace)" },

  mapArea: {
    position: "relative",
    minHeight: 360, flex: 1,
    background: "#fff", borderRadius: 8,
    border: "1px solid var(--cds-border-subtle, #E8EAED)",
    overflow: "hidden",
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  mapSvg: { width: "100%", height: "100%", display: "block" },
  mapPlaceholder: { textAlign: "center", padding: 40, maxWidth: 420 },
  mapPlaceholderTitle: { fontSize: 14, fontWeight: 600, color: INK, marginBottom: 6 },
  mapPlaceholderSub: { fontSize: 12, color: "var(--muted, #6B7280)", lineHeight: 1.5 },

  errorBar: {
    position: "absolute", bottom: 12, left: 12, right: 12,
    background: "#FEE2E2", border: "1px solid #FCA5A5", color: "#991B1B",
    padding: "8px 12px", borderRadius: 6, fontSize: 12,
  },

  feedOffline: { textAlign: "center", maxWidth: 440, padding: 40 },
  feedOfflineTitle: { fontSize: 15, fontWeight: 700, color: INK, marginBottom: 8 },
  feedOfflineBody: { fontSize: 13, color: "var(--muted, #6B7280)", lineHeight: 1.55, marginBottom: 12 },
  feedOfflineHint: {
    fontSize: 11, color: INK, background: LIGHT_GOLD, display: "inline-block",
    padding: "6px 12px", borderRadius: 6, border: `1px solid ${GOLD}`,
  },

  candidatesPanel: {
    background: "#fff", borderRadius: 8, padding: 16,
    border: "1px solid var(--cds-border-subtle, #E8EAED)",
  },
  table: { width: "100%", borderCollapse: "collapse", marginTop: 8 },
  th: {
    textAlign: "left", padding: "8px 10px",
    fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
    color: "var(--muted, #6B7280)", fontWeight: 600,
    borderBottom: `2px solid ${LIGHT_GOLD}`,
  },
  td: { padding: "8px 10px", fontSize: 13, color: INK, borderBottom: "1px solid #F3F4F6" },
  emptyState: { fontSize: 13, color: "var(--muted, #6B7280)", padding: "12px 4px" },

  mono: { fontFamily: "var(--mono, 'JetBrains Mono', monospace)", fontSize: "0.92em" },
};
