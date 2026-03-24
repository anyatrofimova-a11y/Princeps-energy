import React, { useState, useCallback, useEffect, useRef } from "react";
import api from "../services/api";

/* ── Constants ────────────────────────────────────────────────────────── */
const PROFILES = [
  { key: "google_hyperscale", label: "Google Hyperscale", range: "100-300 MW", icon: "G" },
  { key: "hyperscale", label: "Hyperscale", range: "30-200 MW", icon: "H" },
  { key: "colocation", label: "Colocation", range: "5-30 MW", icon: "C" },
  { key: "edge", label: "Edge", range: "<5 MW", icon: "E" },
];

const PRESCORED_SITES = [
  { name: "Waltham Cross", lat: 51.6945, lon: -0.0334, status: "Operational", capacity: "100 MW", region: "Hertfordshire", score: 82, grid: 88, cfe: 71, cooling: 85, env: 76, financial: 84 },
  { name: "North Weald", lat: 51.7246, lon: 0.1544, status: "Approved", capacity: "150 MW", region: "Essex", score: 78, grid: 82, cfe: 68, cooling: 80, env: 73, financial: 79 },
  { name: "Teesside", lat: 54.5973, lon: -1.0737, status: "In Negotiation", capacity: "200 MW", region: "Tees Valley", score: 74, grid: 91, cfe: 77, cooling: 82, env: 68, financial: 71 },
  { name: "Bicester", lat: 51.8998, lon: -1.1517, status: "Planning", capacity: "80 MW", region: "Oxfordshire", score: 71, grid: 75, cfe: 65, cooling: 78, env: 81, financial: 72 },
];

const CAPABILITY_CARDS = [
  {
    key: "grid",
    title: "Grid Connection",
    stat: "500+ substations",
    items: ["Real-time headroom from 6 DNOs", "Queue position & wait time", "Connection cost P10/P50/P90", "Power flow N-1 contingency"],
    color: "#3B82F6",
    gradient: "linear-gradient(135deg, #1e3a5f 0%, #0f2744 100%)",
  },
  {
    key: "cfe",
    title: "Carbon-Free Energy",
    stat: "24/7 CFE%",
    items: ["Hour-by-hour renewable matching", "Gap to 90% CFE target", "PPA opportunity mapping", "BESS sizing optimisation"],
    color: "#10B981",
    gradient: "linear-gradient(135deg, #134e3a 0%, #0a2f25 100%)",
  },
  {
    key: "cooling",
    title: "Cooling Analysis",
    stat: "7 technologies",
    items: ["ASHRAE climate classification", "PUE & WUE modelling", "Rack density up to 50kW", "Free cooling hours/year"],
    color: "#06B6D4",
    gradient: "linear-gradient(135deg, #164e63 0%, #0c3547 100%)",
  },
  {
    key: "heat",
    title: "Heat Reuse",
    stat: "Revenue model",
    items: ["District heating feasibility", "Revenue & payback period", "CO2 savings quantified", "Heat network proximity"],
    color: "#F59E0B",
    gradient: "linear-gradient(135deg, #78350f 0%, #451a03 100%)",
  },
  {
    key: "env",
    title: "Environmental",
    stat: "Full ESA scope",
    items: ["Planning constraints overlay", "BNG cost estimation", "Community sentiment scoring", "Flood risk & water stress"],
    color: "#8B5CF6",
    gradient: "linear-gradient(135deg, #3b1f6e 0%, #1e1145 100%)",
  },
  {
    key: "financial",
    title: "Financial Model",
    stat: "Full IRR model",
    items: ["CapEx & OpEx breakdown", "IRR & payback period", "Enterprise zone incentives", "Sensitivity analysis"],
    color: "#D4A018",
    gradient: "linear-gradient(135deg, #6b4c02 0%, #3d2c01 100%)",
  },
];

const RADAR_DIMENSIONS = [
  { key: "grid", label: "Grid" },
  { key: "cfe", label: "CFE" },
  { key: "cooling", label: "Cooling" },
  { key: "env", label: "Environ" },
  { key: "financial", label: "Financial" },
  { key: "water", label: "Water" },
];

function statusColor(status) {
  if (status === "Operational") return "#10B981";
  if (status === "Approved") return "#3B82F6";
  if (status === "Acquired") return "#D4A018";
  if (status === "Planning") return "#8B5CF6";
  return "#F59E0B";
}

/* ── Mini Radar Chart (SVG) ──────────────────────────────────────────── */
function RadarChart({ scores, size = 200 }) {
  const cx = size / 2, cy = size / 2, r = size * 0.38;
  const n = RADAR_DIMENSIONS.length;
  const angleStep = (2 * Math.PI) / n;

  const pointAt = (i, val) => {
    const a = -Math.PI / 2 + i * angleStep;
    const dist = (val / 100) * r;
    return [cx + dist * Math.cos(a), cy + dist * Math.sin(a)];
  };

  const gridLevels = [25, 50, 75, 100];
  const dataPoints = RADAR_DIMENSIONS.map((d, i) => pointAt(i, scores?.[d.key] ?? 50));
  const polygon = dataPoints.map((p) => p.join(",")).join(" ");

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* Grid rings */}
      {gridLevels.map((lv) => (
        <polygon
          key={lv}
          points={RADAR_DIMENSIONS.map((_, i) => pointAt(i, lv).join(",")).join(" ")}
          fill="none"
          stroke="#334155"
          strokeWidth={lv === 100 ? 1 : 0.5}
          opacity={0.6}
        />
      ))}
      {/* Axes */}
      {RADAR_DIMENSIONS.map((_, i) => {
        const [ex, ey] = pointAt(i, 100);
        return <line key={i} x1={cx} y1={cy} x2={ex} y2={ey} stroke="#334155" strokeWidth={0.5} opacity={0.4} />;
      })}
      {/* Data polygon */}
      <polygon points={polygon} fill="rgba(212, 160, 24, 0.15)" stroke="#D4A018" strokeWidth={2} />
      {/* Data dots */}
      {dataPoints.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py} r={3.5} fill="#D4A018" />
      ))}
      {/* Labels */}
      {RADAR_DIMENSIONS.map((d, i) => {
        const [lx, ly] = pointAt(i, 120);
        return (
          <text key={d.key} x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fill="#94A3B8" fontSize={10} fontWeight={600}>
            {d.label}
          </text>
        );
      })}
    </svg>
  );
}

/* ── Score Ring ──────────────────────────────────────────────────────── */
function ScoreRing({ score, size = 100, label }) {
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  const color = score >= 75 ? "#10B981" : score >= 50 ? "#D4A018" : "#EF4444";

  return (
    <div style={{ textAlign: "center" }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1E293B" strokeWidth={5} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={5}
          strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease" }}
        />
      </svg>
      <div style={{ marginTop: -size * 0.65, fontSize: size * 0.28, fontWeight: 800, color }}>
        {score}
      </div>
      <div style={{ fontSize: 10, color: "#64748B", marginTop: size * 0.32 }}>{label}</div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────────────────────── */
export default function DCLandingPage({ onClose, onScoreSite, onCompareSites, onOpenPanel }) {
  const [profile, setProfile] = useState("google_hyperscale");
  const [scoreLat, setScoreLat] = useState("");
  const [scoreLon, setScoreLon] = useState("");
  const [capacityMw, setCapacityMw] = useState(100);
  const [quickResult, setQuickResult] = useState(null);
  const [quickLoading, setQuickLoading] = useState(false);
  const [prescored, setPrescored] = useState(PRESCORED_SITES);
  const [hoveredCard, setHoveredCard] = useState(null);
  const [hoveredSite, setHoveredSite] = useState(null);
  const [reportLoading, setReportLoading] = useState(null);
  const quickRef = useRef(null);

  /* Load reference sites from API on mount */
  useEffect(() => {
    let cancelled = false;
    api.dc.googleSites(capacityMw, profile)
      .then((data) => {
        if (!cancelled && data?.sites?.length) {
          const merged = PRESCORED_SITES.map((ps) => {
            const live = data.sites.find((s) => s.name === ps.name);
            return live ? { ...ps, ...live } : ps;
          });
          setPrescored(merged);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  /* Quick Score handler */
  const handleQuickScore = useCallback(async () => {
    const lat = parseFloat(scoreLat);
    const lon = parseFloat(scoreLon);
    if (isNaN(lat) || isNaN(lon)) return;
    setQuickLoading(true);
    setQuickResult(null);
    try {
      const result = await api.dc.scoreExtended(lat, lon, capacityMw, profile);
      setQuickResult(result);
    } catch (e) {
      try {
        const fallback = await api.dc.score(lat, lon, capacityMw, profile);
        setQuickResult(fallback);
      } catch {
        setQuickResult({ error: true });
      }
    }
    setQuickLoading(false);
  }, [scoreLat, scoreLon, capacityMw, profile]);

  /* Score & navigate */
  const handleScoreSite = useCallback((site) => {
    onScoreSite?.(site.lat, site.lon, capacityMw, profile);
  }, [onScoreSite, capacityMw, profile]);

  /* Compare all pre-scored sites */
  const handleCompareAll = useCallback(() => {
    const sites = prescored.map((s) => ({ lat: s.lat, lon: s.lon, name: s.name }));
    onCompareSites?.(sites, capacityMw, profile);
  }, [onCompareSites, prescored, capacityMw, profile]);

  /* Generate PDF report */
  const handleGenerateReport = useCallback(async (site) => {
    setReportLoading(site.name);
    try {
      const blob = await api.dc.report(site.lat, site.lon, site.name, capacityMw, profile);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${site.name.replace(/\s+/g, "_")}_DC_Report.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Report generation failed:", e);
    }
    setReportLoading(null);
  }, [capacityMw, profile]);

  /* Scroll to Quick Score section */
  const scrollToQuickScore = () => {
    quickRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  /* ── Render ──────────────────────────────────────────────────────── */
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "#FAFBFC", color: "#1E293B",
      overflowY: "auto", fontFamily: "'Inter', 'SF Pro Display', -apple-system, system-ui, sans-serif",
    }}>
      {/* ── Sticky Header ─────────────────────────────────────────── */}
      <div style={{
        position: "sticky", top: 0, zIndex: 10,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 32px",
        background: "rgba(255,255,255,0.92)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid #E2E8F0",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "linear-gradient(135deg, #D4A018, #B8860B)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontWeight: 800, color: "#fff",
          }}>P</div>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: "#64748B" }}>
            PRINCEPS
          </span>
          <span style={{ fontSize: 13, color: "#CBD5E1" }}>|</span>
          <span style={{ fontSize: 13, fontWeight: 500, color: "#94A3B8" }}>Data Centre Intelligence</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={scrollToQuickScore}
            style={{
              background: "#D4A018", color: "#fff", border: "none", borderRadius: 8,
              padding: "8px 20px", fontWeight: 600, fontSize: 13, cursor: "pointer",
              transition: "background 0.15s",
            }}
            onMouseOver={(e) => (e.target.style.background = "#B8860B")}
            onMouseOut={(e) => (e.target.style.background = "#D4A018")}
          >
            Score a Site
          </button>
          <button
            onClick={onClose}
            style={{
              background: "#F1F5F9", border: "1px solid #E2E8F0", borderRadius: 8,
              color: "#64748B", padding: "8px 20px", cursor: "pointer", fontSize: 13, fontWeight: 500,
            }}
            onMouseOver={(e) => (e.target.style.borderColor = "#D4A018")}
            onMouseOut={(e) => (e.target.style.borderColor = "#E2E8F0")}
          >
            Close
          </button>
        </div>
      </div>

      {/* ── Hero Section ──────────────────────────────────────────── */}
      <div style={{
        padding: "80px 32px 60px",
        background: "linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%)",
        textAlign: "center",
      }}>
        {/* Pill badge */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          background: "#FEF3C7", border: "1px solid #FDE68A", borderRadius: 100,
          padding: "6px 16px", marginBottom: 24,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#D4A018", display: "inline-block" }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: "#92400E", letterSpacing: 0.5 }}>
            125 GW demand queue since Nov 2024
          </span>
        </div>

        <h1 style={{
          fontSize: 52, fontWeight: 800, lineHeight: 1.1, margin: 0,
          color: "#0F172A", maxWidth: 800, marginLeft: "auto", marginRight: "auto",
          letterSpacing: -1.5,
        }}>
          Data Centre{" "}
          <span style={{
            background: "linear-gradient(135deg, #D4A018, #92400E)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>
            Site Intelligence
          </span>
        </h1>

        <p style={{
          fontSize: 20, color: "#64748B", marginTop: 20, maxWidth: 640,
          marginLeft: "auto", marginRight: "auto", lineHeight: 1.6, fontWeight: 400,
        }}>
          125 GW new demand connections, mainly data centres.
          <br />Find your next site in seconds with 15-dimension AI scoring.
        </p>

        {/* Hero metrics */}
        <div style={{
          display: "flex", justifyContent: "center", gap: 48, marginTop: 48,
        }}>
          {[
            { value: "15D", label: "Scoring Dimensions" },
            { value: "6", label: "DNOs Integrated" },
            { value: "500+", label: "Substations Mapped" },
            { value: "<30s", label: "Time to Score" },
          ].map((m) => (
            <div key={m.label}>
              <div style={{ fontSize: 32, fontWeight: 800, color: "#D4A018" }}>{m.value}</div>
              <div style={{ fontSize: 12, color: "#94A3B8", marginTop: 4, fontWeight: 500 }}>{m.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Quick Score Section ───────────────────────────────────── */}
      <div ref={quickRef} style={{
        maxWidth: 1100, margin: "0 auto", padding: "48px 32px",
      }}>
        <div style={{
          background: "#FFFFFF", borderRadius: 16, border: "1px solid #E2E8F0",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.04)",
          padding: 40,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 32 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: "#D4A018", marginBottom: 8 }}>
                Quick Score
              </div>
              <div style={{ fontSize: 24, fontWeight: 700, color: "#0F172A" }}>
                Score any location instantly
              </div>
              <div style={{ fontSize: 14, color: "#64748B", marginTop: 6 }}>
                Enter coordinates and capacity for a full 15-dimension feasibility score with radar breakdown.
              </div>
            </div>
          </div>

          {/* Profile selector */}
          <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
            {PROFILES.map((p) => (
              <button
                key={p.key}
                onClick={() => setProfile(p.key)}
                style={{
                  background: profile === p.key ? "#0F172A" : "#F8FAFC",
                  border: `1px solid ${profile === p.key ? "#0F172A" : "#E2E8F0"}`,
                  color: profile === p.key ? "#fff" : "#475569",
                  borderRadius: 8, padding: "8px 16px",
                  cursor: "pointer", fontSize: 13, fontWeight: 600,
                  transition: "all 0.15s", display: "flex", alignItems: "center", gap: 8,
                }}
              >
                <span style={{
                  width: 22, height: 22, borderRadius: 6,
                  background: profile === p.key ? "#D4A018" : "#E2E8F0",
                  color: profile === p.key ? "#fff" : "#64748B",
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 800,
                }}>{p.icon}</span>
                {p.label}
                <span style={{ fontSize: 11, color: profile === p.key ? "#94A3B8" : "#94A3B8" }}>{p.range}</span>
              </button>
            ))}
          </div>

          {/* Input row */}
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div style={{ flex: "0 0 160px" }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#94A3B8", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Latitude</label>
              <input
                value={scoreLat} onChange={(e) => setScoreLat(e.target.value)}
                placeholder="51.6945" type="number" step="0.0001"
                style={{
                  width: "100%", background: "#F8FAFC", border: "1px solid #E2E8F0", borderRadius: 8,
                  color: "#1E293B", padding: "10px 14px", fontSize: 14, outline: "none",
                  transition: "border-color 0.15s", boxSizing: "border-box",
                }}
                onFocus={(e) => (e.target.style.borderColor = "#D4A018")}
                onBlur={(e) => (e.target.style.borderColor = "#E2E8F0")}
              />
            </div>
            <div style={{ flex: "0 0 160px" }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#94A3B8", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>Longitude</label>
              <input
                value={scoreLon} onChange={(e) => setScoreLon(e.target.value)}
                placeholder="-0.0334" type="number" step="0.0001"
                style={{
                  width: "100%", background: "#F8FAFC", border: "1px solid #E2E8F0", borderRadius: 8,
                  color: "#1E293B", padding: "10px 14px", fontSize: 14, outline: "none",
                  transition: "border-color 0.15s", boxSizing: "border-box",
                }}
                onFocus={(e) => (e.target.style.borderColor = "#D4A018")}
                onBlur={(e) => (e.target.style.borderColor = "#E2E8F0")}
              />
            </div>
            <div style={{ flex: "0 0 200px" }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: "#94A3B8", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
                IT Load: <span style={{ color: "#D4A018" }}>{capacityMw} MW</span>
              </label>
              <input
                type="range" min={5} max={300} step={5} value={capacityMw}
                onChange={(e) => setCapacityMw(Number(e.target.value))}
                style={{ width: "100%", accentColor: "#D4A018", height: 40 }}
              />
            </div>
            <button
              onClick={handleQuickScore}
              disabled={quickLoading}
              style={{
                background: quickLoading ? "#94A3B8" : "#D4A018",
                color: "#fff", border: "none", borderRadius: 10,
                padding: "12px 32px", fontWeight: 700, fontSize: 14,
                cursor: quickLoading ? "wait" : "pointer",
                transition: "all 0.2s", minWidth: 140,
                boxShadow: quickLoading ? "none" : "0 2px 8px rgba(212,160,24,0.3)",
              }}
              onMouseOver={(e) => !quickLoading && (e.target.style.background = "#B8860B")}
              onMouseOut={(e) => !quickLoading && (e.target.style.background = "#D4A018")}
            >
              {quickLoading ? "Scoring..." : "Score Site"}
            </button>
          </div>

          {/* Quick Score Result */}
          {quickResult && !quickResult.error && (
            <div style={{
              marginTop: 32, padding: 28, background: "#F8FAFC", borderRadius: 12,
              border: "1px solid #E2E8F0",
              display: "flex", gap: 40, alignItems: "center", flexWrap: "wrap",
            }}>
              {/* Radar chart */}
              <div style={{ flex: "0 0 auto" }}>
                <RadarChart
                  scores={{
                    grid: quickResult.grid_score ?? quickResult.scores?.grid ?? 65,
                    cfe: quickResult.cfe_score ?? quickResult.scores?.cfe ?? 55,
                    cooling: quickResult.cooling_score ?? quickResult.scores?.cooling ?? 70,
                    env: quickResult.environmental_score ?? quickResult.scores?.environmental ?? 60,
                    financial: quickResult.financial_score ?? quickResult.scores?.financial ?? 68,
                    water: quickResult.water_score ?? quickResult.scores?.water ?? 72,
                  }}
                  size={200}
                />
              </div>

              {/* Score breakdown */}
              <div style={{ flex: 1, minWidth: 300 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
                  <ScoreRing
                    score={quickResult.overall_score ?? quickResult.score ?? 0}
                    size={80}
                    label="Overall"
                  />
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: "#0F172A" }}>
                      {quickResult.verdict || (quickResult.overall_score >= 70 ? "GO" : quickResult.overall_score >= 50 ? "CAUTION" : "NO-GO")}
                    </div>
                    <div style={{ fontSize: 13, color: "#64748B", marginTop: 2 }}>
                      15-dimension feasibility assessment
                    </div>
                  </div>
                </div>

                {/* Dimension bars */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 24px" }}>
                  {[
                    { label: "Grid Connection", val: quickResult.grid_score ?? quickResult.scores?.grid ?? 0 },
                    { label: "Carbon-Free Energy", val: quickResult.cfe_score ?? quickResult.scores?.cfe ?? 0 },
                    { label: "Cooling", val: quickResult.cooling_score ?? quickResult.scores?.cooling ?? 0 },
                    { label: "Environmental", val: quickResult.environmental_score ?? quickResult.scores?.environmental ?? 0 },
                    { label: "Financial", val: quickResult.financial_score ?? quickResult.scores?.financial ?? 0 },
                    { label: "Water Stress", val: quickResult.water_score ?? quickResult.scores?.water ?? 0 },
                  ].map((d) => (
                    <div key={d.label}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                        <span style={{ color: "#475569", fontWeight: 500 }}>{d.label}</span>
                        <span style={{ color: "#0F172A", fontWeight: 700 }}>{d.val}</span>
                      </div>
                      <div style={{ height: 6, background: "#E2E8F0", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{
                          height: "100%", borderRadius: 3,
                          width: `${d.val}%`,
                          background: d.val >= 75 ? "#10B981" : d.val >= 50 ? "#D4A018" : "#EF4444",
                          transition: "width 0.8s ease",
                        }} />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Action buttons */}
                <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
                  <button
                    onClick={() => onScoreSite?.(parseFloat(scoreLat), parseFloat(scoreLon), capacityMw, profile)}
                    style={{
                      background: "#0F172A", color: "#fff", border: "none", borderRadius: 8,
                      padding: "10px 20px", fontWeight: 600, fontSize: 13, cursor: "pointer",
                    }}
                  >
                    Full Analysis
                  </button>
                  <button
                    onClick={() => handleGenerateReport({ lat: parseFloat(scoreLat), lon: parseFloat(scoreLon), name: "Custom Site" })}
                    style={{
                      background: "#fff", color: "#0F172A", border: "1px solid #E2E8F0", borderRadius: 8,
                      padding: "10px 20px", fontWeight: 600, fontSize: 13, cursor: "pointer",
                    }}
                  >
                    Generate PDF Report
                  </button>
                </div>
              </div>
            </div>
          )}

          {quickResult?.error && (
            <div style={{ marginTop: 20, padding: 16, background: "#FEF2F2", borderRadius: 8, border: "1px solid #FECACA", color: "#991B1B", fontSize: 13 }}>
              Scoring failed. Check coordinates are within the UK and try again.
            </div>
          )}
        </div>
      </div>

      {/* ── Capability Cards ──────────────────────────────────────── */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 32px 48px" }}>
        <div style={{ marginBottom: 32 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: "#D4A018", marginBottom: 8 }}>
            Platform Capabilities
          </div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#0F172A" }}>
            Every dimension of DC site feasibility
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {CAPABILITY_CARDS.map((c) => (
            <div
              key={c.key}
              style={{
                background: hoveredCard === c.key ? c.gradient : "#FFFFFF",
                border: `1px solid ${hoveredCard === c.key ? c.color + "44" : "#E2E8F0"}`,
                borderRadius: 14, padding: 28,
                transition: "all 0.25s ease",
                cursor: "default",
                transform: hoveredCard === c.key ? "translateY(-3px)" : "none",
                boxShadow: hoveredCard === c.key
                  ? `0 8px 24px ${c.color}22`
                  : "0 1px 2px rgba(0,0,0,0.03)",
              }}
              onMouseEnter={() => setHoveredCard(c.key)}
              onMouseLeave={() => setHoveredCard(null)}
            >
              <div style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 40, height: 40, borderRadius: 10,
                background: hoveredCard === c.key ? c.color + "33" : c.color + "15",
                marginBottom: 16,
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: "50%", background: c.color,
                }} />
              </div>

              <div style={{ fontSize: 17, fontWeight: 700, color: hoveredCard === c.key ? "#fff" : "#0F172A", marginBottom: 4 }}>
                {c.title}
              </div>
              <div style={{
                fontSize: 12, fontWeight: 600,
                color: hoveredCard === c.key ? c.color : c.color,
                marginBottom: 16, letterSpacing: 0.3,
              }}>
                {c.stat}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {c.items.map((item, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                    <span style={{
                      width: 4, height: 4, borderRadius: "50%",
                      background: hoveredCard === c.key ? "#94A3B8" : "#CBD5E1",
                      marginTop: 6, flexShrink: 0,
                    }} />
                    <span style={{
                      fontSize: 13, lineHeight: 1.5,
                      color: hoveredCard === c.key ? "#CBD5E1" : "#64748B",
                    }}>
                      {item}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Pre-Scored UK Sites ───────────────────────────────────── */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 32px 48px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 24 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: "#D4A018", marginBottom: 8 }}>
              Pre-Scored Sites
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: "#0F172A" }}>
              UK reference sites
            </div>
            <div style={{ fontSize: 14, color: "#64748B", marginTop: 4 }}>
              Google and hyperscale-grade locations with live scoring data.
            </div>
          </div>
          <button
            onClick={handleCompareAll}
            style={{
              background: "#0F172A", color: "#fff", border: "none", borderRadius: 10,
              padding: "12px 28px", fontWeight: 700, fontSize: 13, cursor: "pointer",
              display: "flex", alignItems: "center", gap: 8,
              boxShadow: "0 2px 8px rgba(15,23,42,0.15)",
              transition: "all 0.15s",
            }}
            onMouseOver={(e) => (e.currentTarget.style.background = "#1E293B")}
            onMouseOut={(e) => (e.currentTarget.style.background = "#0F172A")}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="1" width="5" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="10" y="1" width="5" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="5.5" y="9" width="5" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            Compare All {prescored.length} Sites
          </button>
        </div>

        {/* Sites table */}
        <div style={{
          background: "#FFFFFF", borderRadius: 14, border: "1px solid #E2E8F0",
          overflow: "hidden",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
        }}>
          {/* Table header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "200px 100px 80px 80px 80px 80px 80px 80px 1fr",
            padding: "14px 24px", background: "#F8FAFC",
            borderBottom: "1px solid #E2E8F0",
            fontSize: 11, fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: 0.5,
          }}>
            <span>Site</span>
            <span>Status</span>
            <span style={{ textAlign: "center" }}>Overall</span>
            <span style={{ textAlign: "center" }}>Grid</span>
            <span style={{ textAlign: "center" }}>CFE</span>
            <span style={{ textAlign: "center" }}>Cooling</span>
            <span style={{ textAlign: "center" }}>Environ</span>
            <span style={{ textAlign: "center" }}>Financial</span>
            <span style={{ textAlign: "right" }}>Actions</span>
          </div>

          {/* Table rows */}
          {prescored.map((site) => {
            const isHovered = hoveredSite === site.name;
            return (
              <div
                key={site.name}
                style={{
                  display: "grid",
                  gridTemplateColumns: "200px 100px 80px 80px 80px 80px 80px 80px 1fr",
                  padding: "16px 24px",
                  borderBottom: "1px solid #F1F5F9",
                  alignItems: "center",
                  background: isHovered ? "#FFFBEB" : "#fff",
                  transition: "background 0.15s",
                }}
                onMouseEnter={() => setHoveredSite(site.name)}
                onMouseLeave={() => setHoveredSite(null)}
              >
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0F172A" }}>{site.name}</div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 2 }}>{site.region} &middot; {site.capacity}</div>
                </div>
                <div>
                  <span style={{
                    fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
                    background: statusColor(site.status) + "15",
                    color: statusColor(site.status),
                    padding: "3px 8px", borderRadius: 4,
                  }}>
                    {site.status}
                  </span>
                </div>
                {/* Score cells */}
                {[site.score, site.grid, site.cfe, site.cooling, site.env, site.financial].map((val, i) => {
                  const color = val >= 75 ? "#10B981" : val >= 50 ? "#D4A018" : "#EF4444";
                  return (
                    <div key={i} style={{ textAlign: "center" }}>
                      <span style={{ fontSize: 16, fontWeight: 800, color }}>{val}</span>
                    </div>
                  );
                })}
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                  <button
                    onClick={() => handleScoreSite(site)}
                    style={{
                      background: "#D4A018", color: "#fff", border: "none", borderRadius: 6,
                      padding: "6px 14px", fontWeight: 600, fontSize: 11, cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseOver={(e) => (e.target.style.background = "#B8860B")}
                    onMouseOut={(e) => (e.target.style.background = "#D4A018")}
                  >
                    Score
                  </button>
                  <button
                    onClick={() => handleGenerateReport(site)}
                    disabled={reportLoading === site.name}
                    style={{
                      background: "#F8FAFC", color: "#475569", border: "1px solid #E2E8F0", borderRadius: 6,
                      padding: "6px 14px", fontWeight: 600, fontSize: 11, cursor: reportLoading === site.name ? "wait" : "pointer",
                      transition: "all 0.15s",
                    }}
                    onMouseOver={(e) => (e.target.style.borderColor = "#D4A018")}
                    onMouseOut={(e) => (e.target.style.borderColor = "#E2E8F0")}
                  >
                    {reportLoading === site.name ? "..." : "PDF"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Why Princeps ──────────────────────────────────────────── */}
      <div style={{
        background: "#0F172A", padding: "64px 32px",
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: 48 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: "#D4A018", marginBottom: 8 }}>
              Why Princeps
            </div>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#fff" }}>
              The unfair advantage for site acquisition teams
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 }}>
            {[
              {
                title: "Real Grid Data",
                desc: "Live MW headroom from all 6 UK DNOs. No estimates, no proxies. UKPN, SSEN, NGED, NPg, ENW, SPEN data feeds updated continuously.",
                stat: "6 DNOs",
              },
              {
                title: "24/7 CFE Scoring",
                desc: "Hour-by-hour renewable generation matching against facility demand profiles. Aligned with Google's 24/7 Carbon-Free Energy methodology.",
                stat: "90% target",
              },
              {
                title: "AI Site Discovery",
                desc: "Natural language queries to geospatial AI. Describe your ideal site in plain English, get ranked candidates with full 15D scoring breakdown.",
                stat: "15 dimensions",
              },
            ].map((d) => (
              <div
                key={d.title}
                style={{
                  background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 14, padding: 28,
                }}
              >
                <div style={{ fontSize: 24, fontWeight: 800, color: "#D4A018", marginBottom: 12 }}>
                  {d.stat}
                </div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", marginBottom: 8 }}>{d.title}</div>
                <div style={{ fontSize: 13, color: "#94A3B8", lineHeight: 1.7 }}>{d.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── CTA Footer ────────────────────────────────────────────── */}
      <div style={{
        background: "#FFFFFF", padding: "48px 32px 64px",
        textAlign: "center", borderTop: "1px solid #E2E8F0",
      }}>
        <div style={{ fontSize: 28, fontWeight: 700, color: "#0F172A", marginBottom: 12 }}>
          Ready to find your next site?
        </div>
        <div style={{ fontSize: 15, color: "#64748B", marginBottom: 32, maxWidth: 500, margin: "0 auto 32px" }}>
          Score any UK location in under 30 seconds with the most comprehensive DC feasibility engine available.
        </div>
        <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
          <button
            onClick={scrollToQuickScore}
            style={{
              background: "#D4A018", color: "#fff", border: "none", borderRadius: 10,
              padding: "14px 36px", fontWeight: 700, fontSize: 15, cursor: "pointer",
              boxShadow: "0 4px 12px rgba(212,160,24,0.3)",
              transition: "all 0.15s",
            }}
            onMouseOver={(e) => (e.target.style.background = "#B8860B")}
            onMouseOut={(e) => (e.target.style.background = "#D4A018")}
          >
            Score a Site
          </button>
          <button
            onClick={handleCompareAll}
            style={{
              background: "#F8FAFC", color: "#0F172A", border: "1px solid #E2E8F0", borderRadius: 10,
              padding: "14px 36px", fontWeight: 700, fontSize: 15, cursor: "pointer",
              transition: "all 0.15s",
            }}
            onMouseOver={(e) => (e.target.style.borderColor = "#D4A018")}
            onMouseOut={(e) => (e.target.style.borderColor = "#E2E8F0")}
          >
            Compare Sites
          </button>
        </div>

        <div style={{ marginTop: 40, fontSize: 11, color: "#CBD5E1", letterSpacing: 1 }}>
          PRINCEPS &middot; DATA CENTRE SITE INTELLIGENCE &middot; POWERED BY REAL-TIME DNO DATA
        </div>
      </div>
    </div>
  );
}
