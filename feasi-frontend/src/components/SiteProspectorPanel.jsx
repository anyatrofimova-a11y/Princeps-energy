import React, { useState, useCallback, useEffect, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────── */
const SCORING_AXES = [
  { key: "resource",    label: "Resource",    color: "#F5B731" },
  { key: "terrain",     label: "Terrain",     color: "#3b82f6" },
  { key: "land_use",    label: "Land Use",    color: "#10b981" },
  { key: "grid",        label: "Grid",        color: "#8b5cf6" },
  { key: "planning",    label: "Planning",    color: "#f59e0b" },
  { key: "environmental", label: "Environmental", color: "#ef4444" },
];

const UK_REGIONS = [
  "south_west", "south_east", "london", "east_of_england", "east_midlands",
  "west_midlands", "yorkshire", "north_west", "north_east", "wales", "scotland",
];

const TECH_OPTIONS = [
  { id: "solar", label: "Solar PV" },
  { id: "wind", label: "Wind" },
  { id: "bess", label: "BESS" },
  { id: "hybrid", label: "Hybrid" },
];

/* ── Formatters ────────────────────────────────────────────────────────── */
function fmtScore(v) {
  if (v == null) return "--";
  return Math.round(v);
}

function verdictClass(score) {
  if (score >= 70) return "go";
  if (score >= 40) return "caution";
  return "no-go";
}

function verdictLabel(score) {
  if (score >= 70) return "GO";
  if (score >= 40) return "CAUTION";
  return "NO-GO";
}

function regionLabel(r) {
  return r.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

/* ── Ring Gauge SVG ────────────────────────────────────────────────────── */
function RingGauge({ score, size = 100 }) {
  const r = (size - 10) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score || 0)) / 100;
  const offset = circumference * (1 - pct);
  const color = score >= 70 ? "#16A34A" : score >= 40 ? "#F5B731" : "#DC2626";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="sp-ring-gauge">
      <circle cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={6} />
      <circle cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke={color} strokeWidth={6}
        strokeDasharray={circumference} strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)" }}
      />
      <text x={size / 2} y={size / 2 - 4} textAnchor="middle" dominantBaseline="central"
        fill={color} fontSize={size * 0.28} fontWeight="800" fontFamily="var(--mono)">
        {fmtScore(score)}
      </text>
      <text x={size / 2} y={size / 2 + 14} textAnchor="middle"
        fill="rgba(255,255,255,0.5)" fontSize="9" fontWeight="600">
        / 100
      </text>
    </svg>
  );
}

/* ── Radar Chart SVG ───────────────────────────────────────────────────── */
function RadarChart({ scores, comparisons, size = 260 }) {
  const cx = size / 2, cy = size / 2;
  const maxR = size / 2 - 30;
  const n = SCORING_AXES.length;
  const angleStep = (2 * Math.PI) / n;

  const getPoint = (i, val) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const r = (val / 100) * maxR;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  const gridLevels = [20, 40, 60, 80, 100];

  const makePolygon = (values) => {
    return SCORING_AXES.map((_, i) => {
      const val = values[SCORING_AXES[i].key] || 0;
      const pt = getPoint(i, val);
      return `${pt.x},${pt.y}`;
    }).join(" ");
  };

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="sp-radar" style={{ width: "100%", maxWidth: size, height: "auto" }}>
      {/* Grid */}
      {gridLevels.map(level => (
        <polygon key={level}
          points={SCORING_AXES.map((_, i) => {
            const pt = getPoint(i, level);
            return `${pt.x},${pt.y}`;
          }).join(" ")}
          fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={0.5}
        />
      ))}

      {/* Axis lines + labels */}
      {SCORING_AXES.map((axis, i) => {
        const pt = getPoint(i, 100);
        const labelPt = getPoint(i, 115);
        return (
          <g key={axis.key}>
            <line x1={cx} y1={cy} x2={pt.x} y2={pt.y} stroke="rgba(255,255,255,0.08)" strokeWidth={0.5} />
            <text x={labelPt.x} y={labelPt.y} textAnchor="middle" dominantBaseline="central"
              fill={axis.color} fontSize="8" fontWeight="600">
              {axis.label}
            </text>
          </g>
        );
      })}

      {/* Comparison polygons */}
      {comparisons?.map((comp, ci) => (
        <polygon key={ci}
          points={makePolygon(comp.scores)}
          fill={`rgba(${ci === 0 ? "59,130,246" : ci === 1 ? "139,92,246" : "239,68,68"},0.08)`}
          stroke={ci === 0 ? "#3b82f6" : ci === 1 ? "#8b5cf6" : "#ef4444"}
          strokeWidth={1} strokeDasharray="4 2" opacity={0.6}
        />
      ))}

      {/* Main polygon */}
      {scores && (
        <polygon
          points={makePolygon(scores)}
          fill="rgba(245, 183, 49, 0.12)"
          stroke="#F5B731"
          strokeWidth={1.5}
        />
      )}

      {/* Score dots */}
      {scores && SCORING_AXES.map((axis, i) => {
        const val = scores[axis.key] || 0;
        const pt = getPoint(i, val);
        return (
          <g key={axis.key + "-dot"}>
            <circle cx={pt.x} cy={pt.y} r={3.5} fill={axis.color} stroke="#fff" strokeWidth={1} />
            <text x={pt.x} y={pt.y - 8} textAnchor="middle" fill={axis.color} fontSize="8" fontWeight="700" fontFamily="var(--mono)">
              {fmtScore(val)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   SiteProspectorPanel — right slide-in panel
   ══════════════════════════════════════════════════════════════════════════ */
export default function SiteProspectorPanel({ onClose }) {
  const { selectedParcel, explain, mapRef } = useSite();

  const [activeTab, setActiveTab] = useState("score");
  const [technology, setTechnology] = useState("solar");

  // Score tab state
  const [scoreLat, setScoreLat] = useState(() => explain?.lat ?? explain?.location?.lat ?? 52.0);
  const [scoreLon, setScoreLon] = useState(() => explain?.lon ?? explain?.location?.lon ?? -1.5);
  const [scoreResult, setScoreResult] = useState(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState(null);
  const [expandedFactor, setExpandedFactor] = useState(null);

  // Scan tab state
  const [scanRegion, setScanRegion] = useState("south_west");
  const [scanMinScore, setScanMinScore] = useState(40);
  const [scanMinArea, setScanMinArea] = useState(5);
  const [scanGridPoints, setScanGridPoints] = useState(25);
  const [scanResult, setScanResult] = useState(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState(null);

  // Compare tab state
  const [compareItems, setCompareItems] = useState([]);
  const [compareLoading, setCompareLoading] = useState(false);

  // Sync lat/lon from site context
  useEffect(() => {
    const lat = explain?.lat ?? explain?.location?.lat;
    const lon = explain?.lon ?? explain?.location?.lon;
    if (lat) setScoreLat(lat);
    if (lon) setScoreLon(lon);
  }, [explain]);

  /* ── Score site ─────────────────────────────────────────────────────── */
  const scoreSite = useCallback(async () => {
    setScoreLoading(true);
    setScoreError(null);
    try {
      const res = await fetch(`/prospector/score?lat=${scoreLat}&lon=${scoreLon}&technology=${technology}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setScoreResult(data);
    } catch (e) {
      setScoreError(e.message);
    }
    setScoreLoading(false);
  }, [scoreLat, scoreLon, technology]);

  // Auto-score on mount if coords available
  const autoScoreRef = React.useRef(false);
  useEffect(() => {
    if (autoScoreRef.current) return;
    if (scoreLat && scoreLon && !scoreResult && !scoreLoading) {
      autoScoreRef.current = true;
      const t = setTimeout(() => scoreSite(), 300);
      return () => clearTimeout(t);
    }
  }, [scoreLat, scoreLon, scoreResult, scoreLoading, scoreSite]);

  /* ── Scan region ────────────────────────────────────────────────────── */
  const scanSites = useCallback(async () => {
    setScanLoading(true);
    setScanError(null);
    try {
      const res = await fetch(`/prospector/scan?region=${scanRegion}&technology=${technology}&grid_points=${scanGridPoints}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // Filter by minimum score and area if present
      if (data?.candidates) {
        data.candidates = data.candidates.filter(c =>
          (c.overall_score || c.score || 0) >= scanMinScore
        );
        data.candidates.sort((a, b) => (b.overall_score || b.score || 0) - (a.overall_score || a.score || 0));
      }
      setScanResult(data);
    } catch (e) {
      setScanError(e.message);
    }
    setScanLoading(false);
  }, [scanRegion, technology, scanGridPoints, scanMinScore]);

  /* ── Add site to comparison ─────────────────────────────────────────── */
  const addToCompare = useCallback((site) => {
    setCompareItems(prev => {
      if (prev.length >= 4) return prev;
      if (prev.find(s => s.lat === site.lat && s.lon === site.lon)) return prev;
      return [...prev, site];
    });
  }, []);

  const removeFromCompare = useCallback((idx) => {
    setCompareItems(prev => prev.filter((_, i) => i !== idx));
  }, []);

  /* ── Fly to site on map ─────────────────────────────────────────────── */
  const flyToSite = useCallback((lat, lon) => {
    if (mapRef?.current?.flyTo) {
      mapRef.current.flyTo({ center: [lon, lat], zoom: 13, duration: 1500 });
    }
  }, [mapRef]);

  /* ── Export CSV ──────────────────────────────────────────────────────── */
  const exportCsv = useCallback(() => {
    if (!scanResult?.candidates?.length) return;
    const headers = ["Rank", "Lat", "Lon", "Score", "Technology", "Region"];
    const rows = scanResult.candidates.map((c, i) => [
      i + 1, c.lat?.toFixed(4), c.lon?.toFixed(4),
      c.overall_score || c.score || 0, technology, scanRegion,
    ]);
    const csv = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `princeps-scan-${scanRegion}-${technology}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [scanResult, technology, scanRegion]);

  /* ── Factor detail data ─────────────────────────────────────────────── */
  const getFactorDetail = (key) => {
    if (!scoreResult) return null;
    const factors = scoreResult.factors || scoreResult.breakdown || {};
    const detail = factors[key];
    if (!detail) return null;
    return typeof detail === "object" ? detail : { score: detail };
  };

  const scoreBreakdown = useMemo(() => {
    if (!scoreResult) return {};
    const factors = scoreResult.factors || scoreResult.breakdown || {};
    const result = {};
    SCORING_AXES.forEach(axis => {
      const val = factors[axis.key];
      result[axis.key] = typeof val === "object" ? (val.score ?? val.value ?? 0) : (val ?? 0);
    });
    return result;
  }, [scoreResult]);

  return (
    <div className="gc-panel sp-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          Site Prospector
        </div>
        <button className="gc-close" onClick={onClose} title="Close">&times;</button>
      </div>

      {/* Tech selector */}
      <div className="sp-tech-bar">
        {TECH_OPTIONS.map(t => (
          <button key={t.id}
            className={`sp-tech-btn ${technology === t.id ? "active" : ""}`}
            onClick={() => setTechnology(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="df-tabs sp-tabs">
        {[
          { id: "score", label: "Score" },
          { id: "scan", label: "Scan" },
          { id: "compare", label: "Compare" },
        ].map(tab => (
          <button key={tab.id}
            className={`df-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}>
            {tab.label}
            {tab.id === "compare" && compareItems.length > 0 && (
              <span className="sp-compare-badge">{compareItems.length}</span>
            )}
          </button>
        ))}
      </div>

      <div className="gc-panel-body">
        {/* ═══════════════════════════════════════════════════════════
            TAB 1: Score
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "score" && (
          <>
            {/* Location input */}
            <div className="gc-section">
              <div className="sp-location-row">
                <div className="fm-field">
                  <label>Latitude</label>
                  <input type="number" value={scoreLat} step={0.001}
                    onChange={e => setScoreLat(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Longitude</label>
                  <input type="number" value={scoreLon} step={0.001}
                    onChange={e => setScoreLon(+e.target.value)} />
                </div>
                <button onClick={scoreSite} disabled={scoreLoading}
                  className={`gc-assess-btn sp-score-btn${scoreLoading ? " gc-assess-btn--loading" : ""}`}>
                  {scoreLoading ? "Scoring..." : "Score Site"}
                </button>
              </div>
            </div>

            {scoreError && <div className="gc-section" style={{ color: "#DC2626", fontSize: 11 }}>{scoreError}</div>}

            {scoreResult && (
              <>
                {/* Overall Score Ring */}
                <div className="sp-score-hero">
                  <RingGauge score={scoreResult.overall_score ?? scoreResult.score ?? 0} size={110} />
                  <div className="sp-score-info">
                    <div className={`gc-verdict-badge gc-verdict-badge--${verdictClass(scoreResult.overall_score ?? scoreResult.score)}`}
                      style={{ width: "auto", height: "auto", padding: "4px 12px", borderRadius: 4, fontSize: 11 }}>
                      {verdictLabel(scoreResult.overall_score ?? scoreResult.score)}
                    </div>
                    <div className="sp-score-coords">
                      {scoreLat?.toFixed(4)}, {scoreLon?.toFixed(4)}
                    </div>
                    {scoreResult.region && (
                      <div className="sp-score-region">{regionLabel(scoreResult.region)}</div>
                    )}
                  </div>
                </div>

                {/* Radar Chart */}
                <div className="gc-section">
                  <div className="gc-section-header">
                    <span className="gc-section-title">Factor Breakdown</span>
                  </div>
                  <div className="sp-radar-wrap">
                    <RadarChart scores={scoreBreakdown} />
                  </div>
                </div>

                {/* Expandable factor detail */}
                <div className="gc-section">
                  {SCORING_AXES.map(axis => {
                    const val = scoreBreakdown[axis.key] || 0;
                    const expanded = expandedFactor === axis.key;
                    const detail = getFactorDetail(axis.key);
                    const isBlocking = val < 20;
                    return (
                      <div key={axis.key}
                        className={`sp-factor-row ${expanded ? "expanded" : ""} ${isBlocking ? "sp-blocking" : ""}`}
                        onClick={() => setExpandedFactor(expanded ? null : axis.key)}>
                        <div className="sp-factor-header">
                          <div className="sp-factor-dot" style={{ background: axis.color }} />
                          <span className="sp-factor-name">{axis.label}</span>
                          <div className="sp-factor-bar-wrap">
                            <div className="sp-factor-bar" style={{
                              width: `${val}%`,
                              background: val >= 70 ? "#16A34A" : val >= 40 ? "#F5B731" : "#DC2626",
                            }} />
                          </div>
                          <span className="sp-factor-val" style={{ color: axis.color }}>{fmtScore(val)}</span>
                          {isBlocking && <span className="sp-blocking-badge">BLOCKING</span>}
                        </div>
                        {expanded && detail && (
                          <div className="sp-factor-detail">
                            {typeof detail === "object" && Object.entries(detail).filter(([k]) => k !== "score" && k !== "value").map(([k, v]) => (
                              <div key={k} className="sp-detail-row">
                                <span className="sp-detail-key">{k.replace(/_/g, " ")}</span>
                                <span className="sp-detail-val">
                                  {typeof v === "number" ? v.toFixed(2) : String(v)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Notes / constraints */}
                {(scoreResult.constraints?.length > 0 || scoreResult.notes?.length > 0) && (
                  <div className="gc-section">
                    <div className="gc-section-header">
                      <span className="gc-section-title">Constraints</span>
                    </div>
                    {scoreResult.constraints?.map((c, i) => (
                      <div key={i} className="gc-risk-item">
                        <span className="gc-risk-dot gc-risk-dot--risk" />
                        <span>{typeof c === "string" ? c : c.description || c.name}</span>
                      </div>
                    ))}
                    {scoreResult.notes?.map((n, i) => (
                      <div key={i} className="gc-risk-item">
                        <span className="gc-risk-dot gc-risk-dot--note" />
                        <span>{n}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Add to compare button */}
                <div className="gc-section" style={{ textAlign: "center" }}>
                  <button className="sp-add-compare-btn"
                    onClick={() => {
                      addToCompare({
                        lat: scoreLat, lon: scoreLon,
                        score: scoreResult.overall_score ?? scoreResult.score,
                        scores: scoreBreakdown,
                        region: scoreResult.region,
                        label: `${scoreLat?.toFixed(3)}, ${scoreLon?.toFixed(3)}`,
                      });
                    }}>
                    Add to Comparison
                  </button>
                </div>
              </>
            )}

            {!scoreResult && !scoreLoading && !scoreError && (
              <div className="gc-empty">
                <div className="gc-empty-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cds-interactive)" strokeWidth="1.5">
                    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                </div>
                <div className="gc-empty-text">
                  Enter coordinates or click on the map,<br />then click <strong>Score Site</strong>
                </div>
              </div>
            )}
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════
            TAB 2: Scan
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "scan" && (
          <>
            <div className="gc-section">
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>Region</label>
                  <select value={scanRegion} onChange={e => setScanRegion(e.target.value)}>
                    {UK_REGIONS.map(r => (
                      <option key={r} value={r}>{regionLabel(r)}</option>
                    ))}
                  </select>
                </div>
                <div className="fm-field">
                  <label>Grid Points</label>
                  <input type="number" value={scanGridPoints} min={4} max={100}
                    onChange={e => setScanGridPoints(+e.target.value)} />
                </div>
              </div>
              <div className="sp-slider-row">
                <label>Min Score: <strong>{scanMinScore}</strong></label>
                <input type="range" min={0} max={100} value={scanMinScore}
                  onChange={e => setScanMinScore(+e.target.value)} className="fm-slider" />
              </div>
              <button onClick={scanSites} disabled={scanLoading}
                className={`gc-assess-btn sp-scan-btn${scanLoading ? " gc-assess-btn--loading" : ""}`}
                style={{ width: "100%", marginTop: 8 }}>
                {scanLoading ? "Scanning..." : "Scan Region"}
              </button>
            </div>

            {scanError && <div className="gc-section" style={{ color: "#DC2626", fontSize: 11 }}>{scanError}</div>}

            {scanResult?.candidates?.length > 0 && (
              <div className="gc-section">
                <div className="gc-section-header">
                  <span className="gc-section-title">Candidate Sites</span>
                  <span className="gc-section-badge">{scanResult.candidates.length}</span>
                </div>

                {/* Header row */}
                <div className="sp-scan-header">
                  <span>#</span><span>Location</span><span>Score</span><span>Grid</span>
                </div>

                {scanResult.candidates.map((c, i) => {
                  const score = c.overall_score || c.score || 0;
                  const vClass = verdictClass(score);
                  return (
                    <div key={i} className="sp-scan-row"
                      onClick={() => {
                        flyToSite(c.lat, c.lon);
                        setScoreLat(c.lat);
                        setScoreLon(c.lon);
                      }}>
                      <span className="sp-scan-rank">{i + 1}</span>
                      <div className="sp-scan-loc">
                        <span className="sp-scan-coords">{c.lat?.toFixed(3)}, {c.lon?.toFixed(3)}</span>
                        {c.region && <span className="sp-scan-region">{regionLabel(c.region || scanRegion)}</span>}
                      </div>
                      <div className={`sp-scan-score sp-scan-score--${vClass}`}>{fmtScore(score)}</div>
                      <div className="sp-scan-grid">
                        {c.nearest_substation_km != null ? `${c.nearest_substation_km.toFixed(1)} km` :
                         c.grid_distance_km != null ? `${c.grid_distance_km.toFixed(1)} km` : "--"}
                      </div>
                      <button className="sp-scan-compare-btn" title="Add to comparison"
                        onClick={(e) => {
                          e.stopPropagation();
                          addToCompare({
                            lat: c.lat, lon: c.lon, score,
                            scores: c.factors || {},
                            region: c.region || scanRegion,
                            label: `Site ${i + 1}`,
                          });
                        }}>+</button>
                    </div>
                  );
                })}

                {/* Export CSV */}
                <button className="sp-export-btn" onClick={exportCsv}>
                  Export CSV
                </button>
              </div>
            )}

            {scanResult && (!scanResult.candidates || scanResult.candidates.length === 0) && (
              <div className="gc-empty">
                <div className="gc-empty-text">
                  No sites above minimum score threshold ({scanMinScore}).<br />
                  Try lowering the threshold or changing the region.
                </div>
              </div>
            )}
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════
            TAB 3: Compare
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "compare" && (
          <>
            {compareItems.length === 0 ? (
              <div className="gc-empty">
                <div className="gc-empty-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cds-interactive)" strokeWidth="1.5">
                    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
                    <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
                  </svg>
                </div>
                <div className="gc-empty-text">
                  Score or scan sites, then add them to comparison.<br />
                  Supports 2-4 sites side-by-side.
                </div>
              </div>
            ) : (
              <>
                {/* Radar overlay */}
                <div className="gc-section">
                  <div className="gc-section-header">
                    <span className="gc-section-title">Radar Overlay</span>
                    <span className="gc-section-badge">{compareItems.length} sites</span>
                  </div>
                  <div className="sp-radar-wrap">
                    <RadarChart
                      scores={compareItems[0]?.scores}
                      comparisons={compareItems.slice(1).map(c => ({ scores: c.scores }))}
                    />
                  </div>
                  <div className="sp-compare-legend">
                    {compareItems.map((item, i) => (
                      <div key={i} className="sp-compare-legend-item">
                        <span className="sp-compare-legend-dot" style={{
                          background: i === 0 ? "#F5B731" : i === 1 ? "#3b82f6" : i === 2 ? "#8b5cf6" : "#ef4444"
                        }} />
                        <span>{item.label}</span>
                        <span className="sp-compare-legend-score">{fmtScore(item.score)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Side-by-side cards */}
                <div className="sp-compare-cards">
                  {compareItems.map((item, idx) => {
                    const isWinner = compareItems.every(c => (c.score || 0) <= (item.score || 0));
                    return (
                      <div key={idx} className={`sp-compare-card ${isWinner ? "sp-compare-winner" : ""}`}>
                        <div className="sp-compare-card-header">
                          <span className="sp-compare-card-label">{item.label}</span>
                          <button className="sp-compare-remove" onClick={() => removeFromCompare(idx)} title="Remove">&times;</button>
                        </div>
                        <div className="sp-compare-card-score">
                          <span className={`sp-compare-score-val sp-score-${verdictClass(item.score)}`}>
                            {fmtScore(item.score)}
                          </span>
                          <span className="sp-compare-verdict">{verdictLabel(item.score)}</span>
                        </div>
                        {item.region && <div className="sp-compare-card-region">{regionLabel(item.region)}</div>}

                        {/* Factor bars */}
                        <div className="sp-compare-factors">
                          {SCORING_AXES.map(axis => {
                            const val = item.scores?.[axis.key] || 0;
                            const isBest = compareItems.every(c => (c.scores?.[axis.key] || 0) <= val);
                            return (
                              <div key={axis.key} className="sp-compare-factor">
                                <div className="sp-compare-factor-label">
                                  {axis.label}
                                  {isBest && compareItems.length > 1 && <span className="sp-compare-best">BEST</span>}
                                </div>
                                <div className="sp-factor-bar-wrap">
                                  <div className="sp-factor-bar" style={{
                                    width: `${val}%`,
                                    background: axis.color,
                                  }} />
                                </div>
                                <span className="sp-compare-factor-val">{fmtScore(val)}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Recommendation */}
                {compareItems.length >= 2 && (
                  <div className="gc-section">
                    <div className="gc-section-header">
                      <span className="gc-section-title">Recommendation</span>
                    </div>
                    <div className="sp-recommendation">
                      {(() => {
                        const sorted = [...compareItems].sort((a, b) => (b.score || 0) - (a.score || 0));
                        const best = sorted[0];
                        const bestAxes = SCORING_AXES.filter(axis =>
                          compareItems.every(c => (c.scores?.[axis.key] || 0) <= (best.scores?.[axis.key] || 0))
                        );
                        return (
                          <span>
                            <strong>{best.label}</strong> is recommended with an overall score of{" "}
                            <strong>{fmtScore(best.score)}/100</strong>
                            {bestAxes.length > 0 && (
                              <>, leading in {bestAxes.map(a => a.label.toLowerCase()).join(", ")}</>
                            )}
                            .
                          </span>
                        );
                      })()}
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="fm-footer">
        <span>Princeps Site Prospector</span>
        <span>{TECH_OPTIONS.find(t => t.id === technology)?.label}</span>
      </div>
    </div>
  );
}
