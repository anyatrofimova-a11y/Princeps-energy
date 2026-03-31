import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function fmtNum(v, dp = 0) { return v != null ? Number(v).toFixed(dp) : "--"; }
function fmtPct(v) { return v != null ? `${Number(v).toFixed(1)}%` : "--"; }

const ASPECT_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const SLOPE_BINS = [
  { label: "0-5\u00b0",  min: 0, max: 5,  color: "#16A34A" },
  { label: "5-10\u00b0", min: 5, max: 10, color: "#84cc16" },
  { label: "10-15\u00b0",min: 10, max: 15, color: "#F5B731" },
  { label: "15-20\u00b0",min: 15, max: 20, color: "#f97316" },
  { label: "20-25\u00b0",min: 20, max: 25, color: "#ef4444" },
  { label: "25-30\u00b0",min: 25, max: 30, color: "#DC2626" },
];

const TECH_SLOPE_LIMITS = {
  solar: { max: 15, label: "Solar PV" },
  wind:  { max: 20, label: "Wind" },
  bess:  { max: 10, label: "BESS" },
};

const FLOOD_ZONES = [
  { zone: "1", label: "Zone 1 (Low)",     color: "#16A34A", risk: "Low probability (<0.1% annual)" },
  { zone: "2", label: "Zone 2 (Medium)",   color: "#F5B731", risk: "0.1-1% annual probability" },
  { zone: "3a",label: "Zone 3a (High)",    color: "#ef4444", risk: "1% fluvial / 0.5% tidal annual" },
  { zone: "3b",label: "Zone 3b (Functional)",color: "#991b1b", risk: "Active floodplain" },
];

/* ── Slope Histogram (SVG) ────────────────────────────────────────────────── */
function SlopeHistogram({ distribution, width = 340, height = 150 }) {
  if (!distribution || distribution.length === 0) return null;
  const pad = { l: 40, r: 12, t: 8, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...distribution.map(d => d.pct || 0), 1);
  const barW = w / distribution.length - 4;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {distribution.map((d, i) => {
        const x = pad.l + i * (barW + 4);
        const barH = ((d.pct || 0) / maxVal) * h;
        return (
          <g key={i}>
            <rect x={x} y={pad.t + h - barH} width={barW} height={barH} rx={2}
              fill={d.color || "#F5B731"} opacity={0.85} />
            <text x={x + barW / 2} y={pad.t + h - barH - 4} textAnchor="middle"
              fill="var(--cds-text-primary)" fontSize="9" fontFamily="JetBrains Mono, monospace" fontWeight="600">
              {fmtPct(d.pct)}
            </text>
            <text x={x + barW / 2} y={height - 4} textAnchor="middle"
              fill="var(--cds-text-helper)" fontSize="8" fontFamily="DM Sans, sans-serif">
              {d.label}
            </text>
          </g>
        );
      })}
      <text x={2} y={pad.t + 10} fill="var(--cds-text-helper)" fontSize="8" fontFamily="DM Sans, sans-serif">%</text>
    </svg>
  );
}

/* ── Cross-Section Profile (SVG) ──────────────────────────────────────────── */
function CrossSectionChart({ profile, width = 340, height = 120 }) {
  if (!profile || profile.length < 2) return null;
  const pad = { l: 44, r: 12, t: 12, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const minE = Math.min(...profile.map(p => p.elevation));
  const maxE = Math.max(...profile.map(p => p.elevation));
  const range = maxE - minE || 1;

  const points = profile.map((p, i) => {
    const x = pad.l + (i / (profile.length - 1)) * w;
    const y = pad.t + h - ((p.elevation - minE) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  const areaPoints = points + ` ${pad.l + w},${pad.t + h} ${pad.l},${pad.t + h}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      <polygon points={areaPoints} fill="url(#ta-elev-grad)" opacity={0.3} />
      <polyline points={points} fill="none" stroke="#F5B731" strokeWidth={1.5} />
      <text x={2} y={pad.t + 8} fill="var(--cds-text-helper)" fontSize="8">{fmtNum(maxE, 0)}m</text>
      <text x={2} y={pad.t + h} fill="var(--cds-text-helper)" fontSize="8">{fmtNum(minE, 0)}m</text>
      <text x={pad.l} y={height - 2} fill="var(--cds-text-helper)" fontSize="8">0m</text>
      <text x={pad.l + w} y={height - 2} fill="var(--cds-text-helper)" fontSize="8" textAnchor="end">
        {fmtNum(profile[profile.length - 1]?.distance, 0)}m
      </text>
      <defs>
        <linearGradient id="ta-elev-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#F5B731" />
          <stop offset="100%" stopColor="#F5B731" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/* ── Aspect Rose (SVG) ────────────────────────────────────────────────────── */
function AspectRose({ aspects, width = 160, height = 160 }) {
  if (!aspects) return null;
  const cx = width / 2, cy = height / 2, r = Math.min(cx, cy) - 20;
  const maxVal = Math.max(...Object.values(aspects), 1);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", maxWidth: 160, height: "auto" }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--cds-border-subtle)" strokeWidth={0.5} opacity={0.4} />
      <circle cx={cx} cy={cy} r={r * 0.5} fill="none" stroke="var(--cds-border-subtle)" strokeWidth={0.5} opacity={0.3} />
      {ASPECT_LABELS.map((label, i) => {
        const angle = (i * 45 - 90) * (Math.PI / 180);
        const val = aspects[label] || 0;
        const pctR = (val / maxVal) * r;
        const x = cx + Math.cos(angle) * pctR;
        const y = cy + Math.sin(angle) * pctR;
        const lx = cx + Math.cos(angle) * (r + 12);
        const ly = cy + Math.sin(angle) * (r + 12);
        return (
          <g key={label}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#F5B731" strokeWidth={2} opacity={0.7} />
            <circle cx={x} cy={y} r={3} fill="#F5B731" />
            <text x={lx} y={ly + 3} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8" fontWeight="600">{label}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ════════════════════════════════════════════════════════════════════════════ */
/*  TerrainAnalysisPanel                                                      */
/* ════════════════════════════════════════════════════════════════════════════ */
export default function TerrainAnalysisPanel({ onClose, embedded }) {
  const { lat, lon } = useSite();
  const [tab, setTab] = useState("terrain");
  const [loading, setLoading] = useState(false);

  // ── Terrain state ──
  const [terrainData, setTerrainData] = useState(null);
  const [slopeThreshold, setSlopeThreshold] = useState(15);
  const [technology, setTechnology] = useState("solar");

  // ── Viewshed state ──
  const [viewshedData, setViewshedData] = useState(null);
  const [obsLat, setObsLat] = useState("");
  const [obsLon, setObsLon] = useState("");
  const [obsHeight, setObsHeight] = useState(1.7);
  const [targetHeight, setTargetHeight] = useState(3.5);
  const [viewRadius, setViewRadius] = useState(5);

  // ── Hydrology state ──
  const [hydroData, setHydroData] = useState(null);

  /* ── Terrain analysis ──────────────────────────────────────────────────── */
  const analyseTerrain = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    try {
      const data = await api.terrain.analyse(lat, lon, slopeThreshold, technology);
      setTerrainData(data);
    } catch (e) { console.warn("[TerrainPanel] analyse error:", e); }
    setLoading(false);
  }, [lat, lon, slopeThreshold, technology]);

  /* ── Viewshed ──────────────────────────────────────────────────────────── */
  const calculateViewshed = useCallback(async () => {
    const oLat = obsLat || lat;
    const oLon = obsLon || lon;
    if (!oLat || !oLon) return;
    setLoading(true);
    try {
      const data = await api.terrain.viewshed(oLat, oLon, obsHeight, targetHeight, viewRadius);
      setViewshedData(data);
    } catch (e) { console.warn("[TerrainPanel] viewshed error:", e); }
    setLoading(false);
  }, [lat, lon, obsLat, obsLon, obsHeight, targetHeight, viewRadius]);

  /* ── Hydrology ─────────────────────────────────────────────────────────── */
  const analyseHydrology = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    try {
      const data = await api.terrain.hydrology(lat, lon);
      setHydroData(data);
    } catch (e) { console.warn("[TerrainPanel] hydrology error:", e); }
    setLoading(false);
  }, [lat, lon]);

  /* ── Computed: slope distribution for histogram ────────────────────────── */
  const slopeDistribution = useMemo(() => {
    if (!terrainData?.slope_distribution) {
      return SLOPE_BINS.map(b => ({ ...b, pct: 0 }));
    }
    return SLOPE_BINS.map(b => ({
      ...b,
      pct: terrainData.slope_distribution[b.label] || 0,
    }));
  }, [terrainData]);

  /* ── Suitability verdict ───────────────────────────────────────────────── */
  const suitability = useMemo(() => {
    if (!terrainData) return null;
    const buildable = terrainData.buildable_pct ?? 0;
    if (buildable >= 80) return { verdict: "Suitable", color: "#16A34A", cls: "ta-v-go" };
    if (buildable >= 50) return { verdict: "Marginal", color: "#F5B731", cls: "ta-v-caution" };
    return { verdict: "Unsuitable", color: "#DC2626", cls: "ta-v-nogo" };
  }, [terrainData]);

  /* ── Visual impact verdict ─────────────────────────────────────────────── */
  const vizImpact = useMemo(() => {
    if (!viewshedData) return null;
    const pct = viewshedData.visibility_pct ?? 0;
    if (pct <= 15) return { level: "Low", color: "#16A34A" };
    if (pct <= 40) return { level: "Medium", color: "#F5B731" };
    return { level: "High", color: "#DC2626" };
  }, [viewshedData]);

  /* ── Flood verdict ─────────────────────────────────────────────────────── */
  const floodVerdict = useMemo(() => {
    if (!hydroData) return null;
    const zone = hydroData.flood_zone || "1";
    if (zone === "1") return { level: "Low Risk", color: "#16A34A", note: "No flood mitigation required" };
    if (zone === "2") return { level: "Medium Risk", color: "#F5B731", note: "Sequential test required; FRA recommended" };
    return { level: "High Risk", color: "#DC2626", note: "Exception test required; CEMP and drainage plan mandatory" };
  }, [hydroData]);

  const TABS = [
    { id: "terrain",   label: "Terrain" },
    { id: "viewshed",  label: "Viewshed" },
    { id: "hydrology", label: "Hydrology" },
  ];

  return (
    <div className={`ta-panel${embedded ? " ta-embedded" : ""}`}>
      {!embedded && (
        <div className="ta-header">
          <span className="ta-title">Terrain and Environmental Analysis</span>
          <button className="ta-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="ta-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`ta-tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="ta-body">
        {/* ════════════════════════ TAB 1: TERRAIN ════════════════════════ */}
        {tab === "terrain" && (
          <div className="ta-section">
            <div className="ta-input-row">
              <label className="ta-label">Technology</label>
              <select className="ta-select" value={technology} onChange={e => setTechnology(e.target.value)}>
                {Object.entries(TECH_SLOPE_LIMITS).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Slope Threshold</label>
              <div className="ta-slider-wrap">
                <input type="range" min="5" max="30" value={slopeThreshold}
                  onChange={e => setSlopeThreshold(+e.target.value)} className="ta-slider" />
                <span className="ta-slider-val">{slopeThreshold}&deg;</span>
              </div>
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Location</label>
              <span className="ta-coord">{lat ? `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}` : "Select a site"}</span>
            </div>
            <button className="ta-btn" onClick={analyseTerrain} disabled={loading || !lat}>
              {loading && tab === "terrain" ? "Analysing..." : "Analyse Terrain"}
            </button>

            {terrainData && (
              <>
                {/* Elevation stats */}
                <div className="ta-stats-grid">
                  <div className="ta-stat">
                    <span className="ta-stat-label">Min Elevation</span>
                    <span className="ta-stat-val">{fmtNum(terrainData.elevation_min, 1)}m</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Max Elevation</span>
                    <span className="ta-stat-val">{fmtNum(terrainData.elevation_max, 1)}m</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Mean Elevation</span>
                    <span className="ta-stat-val">{fmtNum(terrainData.elevation_mean, 1)}m</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Relief</span>
                    <span className="ta-stat-val">{fmtNum((terrainData.elevation_max || 0) - (terrainData.elevation_min || 0), 1)}m</span>
                  </div>
                </div>

                {/* Slope distribution */}
                <div className="ta-subsection">
                  <h4 className="ta-sub-title">Slope Distribution</h4>
                  <SlopeHistogram distribution={slopeDistribution} />
                </div>

                {/* Aspect rose */}
                {terrainData.aspects && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Dominant Aspect</h4>
                    <div className="ta-aspect-wrap">
                      <AspectRose aspects={terrainData.aspects} />
                      <div className="ta-aspect-info">
                        <span className="ta-aspect-dominant">{terrainData.dominant_aspect || "--"}</span>
                        <span className="ta-aspect-note">Primary facing direction</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Buildable area */}
                <div className="ta-subsection">
                  <h4 className="ta-sub-title">Buildable Area (slope &lt; {slopeThreshold}&deg;)</h4>
                  <div className="ta-buildable-bar">
                    <div className="ta-buildable-fill" style={{ width: `${Math.min(terrainData.buildable_pct || 0, 100)}%` }} />
                    <span className="ta-buildable-pct">{fmtPct(terrainData.buildable_pct)}</span>
                  </div>
                </div>

                {/* Cross-section */}
                {terrainData.cross_section && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Cross-Section Profile</h4>
                    <CrossSectionChart profile={terrainData.cross_section} />
                  </div>
                )}

                {/* Suitability verdict */}
                {suitability && (
                  <div className={`ta-verdict ${suitability.cls}`}>
                    <span className="ta-verdict-dot" style={{ background: suitability.color }} />
                    <span className="ta-verdict-text">{suitability.verdict} for {TECH_SLOPE_LIMITS[technology]?.label}</span>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ════════════════════════ TAB 2: VIEWSHED ════════════════════════ */}
        {tab === "viewshed" && (
          <div className="ta-section">
            <div className="ta-input-row">
              <label className="ta-label">Observer Lat</label>
              <input className="ta-input" type="number" step="0.0001" placeholder={lat || "52.0"}
                value={obsLat} onChange={e => setObsLat(e.target.value)} />
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Observer Lon</label>
              <input className="ta-input" type="number" step="0.0001" placeholder={lon || "-1.0"}
                value={obsLon} onChange={e => setObsLon(e.target.value)} />
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Observer Height</label>
              <div className="ta-inline-btns">
                {[{ v: 1.7, l: "Person (1.7m)" }, { v: 2.0, l: "Road (2.0m)" }, { v: 10, l: "Building (10m)" }].map(o => (
                  <button key={o.v} className={`ta-chip${obsHeight === o.v ? " active" : ""}`}
                    onClick={() => setObsHeight(o.v)}>{o.l}</button>
                ))}
              </div>
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Target Height (m)</label>
              <input className="ta-input" type="number" step="0.5" value={targetHeight}
                onChange={e => setTargetHeight(+e.target.value)} />
            </div>
            <div className="ta-input-row">
              <label className="ta-label">Radius (km)</label>
              <input className="ta-input" type="number" step="0.5" min="1" max="20" value={viewRadius}
                onChange={e => setViewRadius(+e.target.value)} />
            </div>
            <button className="ta-btn" onClick={calculateViewshed} disabled={loading}>
              {loading && tab === "viewshed" ? "Calculating..." : "Calculate ZTV"}
            </button>

            {viewshedData && (
              <>
                <div className="ta-stats-grid">
                  <div className="ta-stat">
                    <span className="ta-stat-label">Visibility</span>
                    <span className="ta-stat-val">{fmtPct(viewshedData.visibility_pct)}</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">ZTV Area</span>
                    <span className="ta-stat-val">{fmtNum(viewshedData.ztv_area_km2, 2)} km2</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Buildings in ZTV</span>
                    <span className="ta-stat-val">{fmtNum(viewshedData.receptors_buildings)}</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Roads in ZTV</span>
                    <span className="ta-stat-val">{fmtNum(viewshedData.receptors_roads)}</span>
                  </div>
                </div>

                {viewshedData.ztv_summary && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">ZTV Summary</h4>
                    <p className="ta-desc">{viewshedData.ztv_summary}</p>
                  </div>
                )}

                {vizImpact && (
                  <div className="ta-verdict" style={{ borderColor: vizImpact.color }}>
                    <span className="ta-verdict-dot" style={{ background: vizImpact.color }} />
                    <span className="ta-verdict-text">{vizImpact.level} Visual Impact</span>
                  </div>
                )}

                {viewshedData.mitigation && viewshedData.mitigation.length > 0 && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Mitigation Measures</h4>
                    <ul className="ta-list">
                      {viewshedData.mitigation.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ════════════════════════ TAB 3: HYDROLOGY ════════════════════════ */}
        {tab === "hydrology" && (
          <div className="ta-section">
            <div className="ta-input-row">
              <label className="ta-label">Location</label>
              <span className="ta-coord">{lat ? `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}` : "Select a site"}</span>
            </div>
            <button className="ta-btn" onClick={analyseHydrology} disabled={loading || !lat}>
              {loading && tab === "hydrology" ? "Analysing..." : "Analyse Hydrology"}
            </button>

            {hydroData && (
              <>
                {/* Flood zone */}
                <div className="ta-subsection">
                  <h4 className="ta-sub-title">Flood Zone Classification</h4>
                  <div className="ta-flood-zones">
                    {FLOOD_ZONES.map(fz => (
                      <div key={fz.zone} className={`ta-flood-zone${hydroData.flood_zone === fz.zone ? " active" : ""}`}>
                        <span className="ta-fz-dot" style={{ background: fz.color }} />
                        <div className="ta-fz-info">
                          <span className="ta-fz-label">{fz.label}</span>
                          <span className="ta-fz-risk">{fz.risk}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Water features */}
                <div className="ta-stats-grid">
                  <div className="ta-stat">
                    <span className="ta-stat-label">Nearest Watercourse</span>
                    <span className="ta-stat-val">{hydroData.nearest_watercourse_name || "--"}</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Distance</span>
                    <span className="ta-stat-val">{fmtNum(hydroData.watercourse_distance_m, 0)}m</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Surface Water Pooling</span>
                    <span className="ta-stat-val">{hydroData.surface_water_risk || "--"}</span>
                  </div>
                  <div className="ta-stat">
                    <span className="ta-stat-label">Drainage Required</span>
                    <span className="ta-stat-val">{hydroData.drainage_required ? "Yes" : "No"}</span>
                  </div>
                </div>

                {/* Flow accumulation */}
                {hydroData.flow_accumulation_summary && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Surface Water Flow</h4>
                    <p className="ta-desc">{hydroData.flow_accumulation_summary}</p>
                  </div>
                )}

                {/* Drainage estimate */}
                {hydroData.drainage_estimate && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Drainage Requirements</h4>
                    <div className="ta-kv-list">
                      {Object.entries(hydroData.drainage_estimate).map(([k, v]) => (
                        <div key={k} className="ta-kv">
                          <span className="ta-kv-key">{k.replace(/_/g, " ")}</span>
                          <span className="ta-kv-val">{typeof v === "number" ? fmtNum(v, 0) : String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Flood verdict */}
                {floodVerdict && (
                  <div className="ta-verdict" style={{ borderColor: floodVerdict.color }}>
                    <span className="ta-verdict-dot" style={{ background: floodVerdict.color }} />
                    <div>
                      <span className="ta-verdict-text">{floodVerdict.level}</span>
                      <span className="ta-verdict-note">{floodVerdict.note}</span>
                    </div>
                  </div>
                )}

                {/* Mitigation */}
                {hydroData.mitigation && hydroData.mitigation.length > 0 && (
                  <div className="ta-subsection">
                    <h4 className="ta-sub-title">Mitigation Recommendations</h4>
                    <ul className="ta-list">
                      {hydroData.mitigation.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
