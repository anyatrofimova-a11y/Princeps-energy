import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ────────────────────────────────────────────────────────── */
const PROFILES = [
  { key: "google_hyperscale", label: "Google Hyperscale", range: "100-300 MW", icon: "🔷" },
  { key: "hyperscale", label: "Hyperscale", range: "30-200 MW", icon: "🏗️" },
  { key: "colocation", label: "Colocation", range: "5-30 MW", icon: "🏢" },
  { key: "edge", label: "Edge", range: "<5 MW", icon: "📡" },
];

const METHODS = [
  { key: "score", label: "Score a Site", desc: "Enter lat/lon to score a specific location" },
  { key: "prospect", label: "Find Sites", desc: "AI-powered natural language site discovery" },
  { key: "compare", label: "Compare Sites", desc: "Multi-site head-to-head comparison" },
];

const GOOGLE_REFERENCE_SITES = [
  { name: "Waltham Cross", lat: 51.6945, lon: -0.0334, status: "Operational", capacity: "100 MW", region: "Hertfordshire" },
  { name: "North Weald", lat: 51.7246, lon: 0.1544, status: "Approved", capacity: "150 MW", region: "Essex" },
  { name: "Purfleet", lat: 51.4810, lon: 0.2310, status: "Acquired", capacity: "80 MW", region: "Thurrock" },
  { name: "Teesside", lat: 54.5973, lon: -1.0737, status: "In Negotiation", capacity: "200 MW", region: "Tees Valley" },
];

const METRICS = [
  { value: "6", label: "DNOs Integrated", sub: "All UK distribution network operators" },
  { value: "15", label: "Scoring Dimensions", sub: "Power, grid, fibre, water, planning..." },
  { value: "48+", label: "Enterprise Zones", sub: "Tax incentives & fast-track planning" },
  { value: "500+", label: "Substations Mapped", sub: "Real-time headroom from DNO feeds" },
];

const DIFFERENTIATORS = [
  {
    title: "Real Grid Data",
    icon: "⚡",
    desc: "REAL MW headroom sourced live from all 6 UK DNOs — UKPN, SSEN, NGED, NPg, Electricity NW, SP Energy. No estimates, no guesswork.",
  },
  {
    title: "24/7 CFE% Scoring",
    icon: "🌱",
    desc: "Carbon-free energy matching aligned with Google's 24/7 CFE targets. Hour-by-hour renewable generation vs. facility demand profiles.",
  },
  {
    title: "AI Site Prospecting",
    icon: "🤖",
    desc: "Natural language site discovery powered by geospatial AI. Describe what you need, get ranked candidates with full scoring breakdown.",
  },
];

function statusColor(status) {
  if (status === "Operational") return "#24a148";
  if (status === "Approved") return "#0f62fe";
  if (status === "Acquired") return "#6c5ce7";
  return "#f1c21b";
}

/* ── Component ────────────────────────────────────────────────────────── */
export default function DCLandingPage({ onClose, onScoreSite, onCompareSites, onOpenPanel }) {
  const [profile, setProfile] = useState("google_hyperscale");
  const [method, setMethod] = useState(null);
  const [scoreLat, setScoreLat] = useState("");
  const [scoreLon, setScoreLon] = useState("");
  const [capacityMw, setCapacityMw] = useState(100);
  const [prospectQuery, setProspectQuery] = useState("");
  const [googleSites, setGoogleSites] = useState(GOOGLE_REFERENCE_SITES);
  const [loading, setLoading] = useState(false);
  const [prospectResults, setProspectResults] = useState(null);

  /* Load Google reference sites from API on mount */
  useEffect(() => {
    let cancelled = false;
    api.dc.googleSites(capacityMw, profile)
      .then((data) => {
        if (!cancelled && data?.sites?.length) setGoogleSites(data.sites);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleScoreGoogleSite = useCallback((site) => {
    onScoreSite?.(site.lat, site.lon, capacityMw, profile);
  }, [onScoreSite, capacityMw, profile]);

  const handleScoreSite = useCallback(() => {
    const lat = parseFloat(scoreLat);
    const lon = parseFloat(scoreLon);
    if (isNaN(lat) || isNaN(lon)) return;
    onScoreSite?.(lat, lon, capacityMw, profile);
  }, [onScoreSite, scoreLat, scoreLon, capacityMw, profile]);

  const handleProspect = useCallback(async () => {
    if (!prospectQuery.trim()) return;
    setLoading(true);
    try {
      const result = await api.dc.prospect(prospectQuery, capacityMw, profile);
      setProspectResults(result?.candidates || result?.sites || []);
    } catch (e) {
      setProspectResults([]);
    }
    setLoading(false);
  }, [prospectQuery, capacityMw, profile]);

  const handleCompare = useCallback(() => {
    const sites = googleSites.map((s) => ({ lat: s.lat, lon: s.lon, name: s.name }));
    onCompareSites?.(sites, capacityMw, profile);
  }, [onCompareSites, googleSites, capacityMw, profile]);

  /* ── Styles ───────────────────────────────────────────────────────── */
  const overlay = {
    position: "fixed", inset: 0, zIndex: 1000,
    background: "#1a1a2e", color: "#e0e0e0",
    overflowY: "auto", fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
  };

  const header = {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "14px 28px", borderBottom: "1px solid #2a2a4a",
    background: "linear-gradient(90deg, #0d0d1a 0%, #1a1a2e 100%)",
  };

  const headerTitle = {
    fontSize: 14, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
    color: "#0f62fe",
  };

  const closeBtn = {
    background: "none", border: "1px solid #444", borderRadius: 6,
    color: "#e0e0e0", padding: "6px 16px", cursor: "pointer", fontSize: 13,
  };

  const hero = {
    textAlign: "center", padding: "64px 28px 40px",
    background: "linear-gradient(180deg, #0d0d1a 0%, #1a1a2e 40%, #16213e 100%)",
  };

  const heroH1 = {
    fontSize: 42, fontWeight: 800, lineHeight: 1.15, margin: 0,
    background: "linear-gradient(135deg, #0f62fe, #6c5ce7, #0f62fe)",
    WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
    maxWidth: 780, marginLeft: "auto", marginRight: "auto",
  };

  const heroSub = {
    fontSize: 17, color: "#999", marginTop: 18, maxWidth: 640,
    marginLeft: "auto", marginRight: "auto", lineHeight: 1.6,
  };

  const section = { padding: "32px 28px", maxWidth: 1100, margin: "0 auto" };

  const sectionTitle = {
    fontSize: 20, fontWeight: 700, marginBottom: 20, color: "#fff",
    borderLeft: "3px solid #0f62fe", paddingLeft: 12,
  };

  const card = {
    background: "#22223a", border: "1px solid #333360", borderRadius: 10,
    padding: 20, transition: "border-color 0.2s, transform 0.2s",
    cursor: "pointer",
  };

  const cardHover = { borderColor: "#0f62fe", transform: "translateY(-2px)" };

  return (
    <div style={overlay}>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div style={header}>
        <span style={headerTitle}>PRINCEPS &nbsp;|&nbsp; Data Centre Site Selection Engine</span>
        <button style={closeBtn} onClick={onClose} onMouseOver={(e) => (e.target.style.borderColor = "#0f62fe")} onMouseOut={(e) => (e.target.style.borderColor = "#444")}>
          Close
        </button>
      </div>

      {/* ── Hero ───────────────────────────────────────────────────── */}
      <div style={hero}>
        <h1 style={heroH1}>The UK's Most Intelligent Data Centre Site Selection Engine</h1>
        <p style={heroSub}>
          15-dimension AI scoring fusing real DNO headroom, 24/7 carbon-free energy matching,
          fibre proximity, water stress, planning constraints and enterprise zone incentives
          — purpose-built for hyperscale site acquisition teams.
        </p>
      </div>

      {/* ── Metrics strip ──────────────────────────────────────────── */}
      <div style={{ ...section, paddingTop: 0 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {METRICS.map((m) => (
            <div key={m.label} style={{ ...card, textAlign: "center", cursor: "default" }}>
              <div style={{ fontSize: 36, fontWeight: 800, color: "#0f62fe" }}>{m.value}</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#fff", marginTop: 4 }}>{m.label}</div>
              <div style={{ fontSize: 12, color: "#777", marginTop: 4 }}>{m.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Quick-start workflow ───────────────────────────────────── */}
      <div style={section}>
        <div style={sectionTitle}>Quick-Start Workflow</div>

        {/* Step 1: Profile */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#888", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
            Step 1 &mdash; Select Profile
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {PROFILES.map((p) => (
              <button
                key={p.key}
                onClick={() => setProfile(p.key)}
                style={{
                  background: profile === p.key ? "#0f62fe" : "#22223a",
                  border: `1px solid ${profile === p.key ? "#0f62fe" : "#444"}`,
                  color: "#fff", borderRadius: 8, padding: "10px 18px",
                  cursor: "pointer", fontSize: 13, fontWeight: 600,
                  transition: "all 0.15s",
                }}
              >
                {p.icon} {p.label} <span style={{ color: profile === p.key ? "#cde" : "#666", marginLeft: 6, fontSize: 11 }}>{p.range}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Step 2: Method */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#888", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
            Step 2 &mdash; Choose Method
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {METHODS.map((m) => (
              <div
                key={m.key}
                onClick={() => setMethod(m.key)}
                style={{
                  ...card,
                  borderColor: method === m.key ? "#0f62fe" : "#333360",
                  background: method === m.key ? "#1a2a4e" : "#22223a",
                }}
                onMouseOver={(e) => { e.currentTarget.style.borderColor = "#0f62fe"; e.currentTarget.style.transform = "translateY(-2px)"; }}
                onMouseOut={(e) => { e.currentTarget.style.borderColor = method === m.key ? "#0f62fe" : "#333360"; e.currentTarget.style.transform = "none"; }}
              >
                <div style={{ fontSize: 15, fontWeight: 700, color: "#fff" }}>{m.label}</div>
                <div style={{ fontSize: 12, color: "#888", marginTop: 6 }}>{m.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Capacity slider */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#888", marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
            IT Load: <span style={{ color: "#0f62fe" }}>{capacityMw} MW</span>
          </div>
          <input
            type="range" min={5} max={300} step={5} value={capacityMw}
            onChange={(e) => setCapacityMw(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#0f62fe" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#555" }}>
            <span>5 MW</span><span>300 MW</span>
          </div>
        </div>

        {/* Step 3: Action */}
        {method && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#888", marginBottom: 10, textTransform: "uppercase", letterSpacing: 1 }}>
              Step 3 &mdash; {method === "score" ? "Enter Coordinates" : method === "prospect" ? "Describe Your Ideal Site" : "Select Sites to Compare"}
            </div>

            {method === "score" && (
              <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
                <div>
                  <label style={{ fontSize: 11, color: "#777", display: "block", marginBottom: 4 }}>Latitude</label>
                  <input
                    value={scoreLat} onChange={(e) => setScoreLat(e.target.value)}
                    placeholder="51.5074" type="number" step="0.0001"
                    style={{ background: "#16162a", border: "1px solid #444", borderRadius: 6, color: "#e0e0e0", padding: "8px 12px", width: 140, fontSize: 14 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, color: "#777", display: "block", marginBottom: 4 }}>Longitude</label>
                  <input
                    value={scoreLon} onChange={(e) => setScoreLon(e.target.value)}
                    placeholder="-0.1278" type="number" step="0.0001"
                    style={{ background: "#16162a", border: "1px solid #444", borderRadius: 6, color: "#e0e0e0", padding: "8px 12px", width: 140, fontSize: 14 }}
                  />
                </div>
                <button
                  onClick={handleScoreSite}
                  style={{
                    background: "#0f62fe", color: "#fff", border: "none", borderRadius: 8,
                    padding: "10px 24px", fontWeight: 700, fontSize: 13, cursor: "pointer",
                  }}
                >
                  Score Site
                </button>
              </div>
            )}

            {method === "prospect" && (
              <div>
                <div style={{ display: "flex", gap: 10 }}>
                  <input
                    value={prospectQuery} onChange={(e) => setProspectQuery(e.target.value)}
                    placeholder="e.g. 100MW hyperscale near M25 corridor with 50MW+ grid headroom and fibre access"
                    onKeyDown={(e) => e.key === "Enter" && handleProspect()}
                    style={{
                      flex: 1, background: "#16162a", border: "1px solid #444", borderRadius: 6,
                      color: "#e0e0e0", padding: "10px 14px", fontSize: 14,
                    }}
                  />
                  <button
                    onClick={handleProspect} disabled={loading}
                    style={{
                      background: loading ? "#333" : "#0f62fe", color: "#fff", border: "none",
                      borderRadius: 8, padding: "10px 24px", fontWeight: 700, fontSize: 13,
                      cursor: loading ? "wait" : "pointer", minWidth: 120,
                    }}
                  >
                    {loading ? "Searching..." : "Find Sites"}
                  </button>
                </div>

                {/* Prospect results */}
                {prospectResults && prospectResults.length > 0 && (
                  <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
                    {prospectResults.map((site, i) => (
                      <div
                        key={i}
                        style={{ ...card, display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "default" }}
                      >
                        <div>
                          <div style={{ fontWeight: 700, fontSize: 14, color: "#fff" }}>
                            #{i + 1} {site.name || site.label || `Candidate ${i + 1}`}
                          </div>
                          <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
                            {site.lat?.toFixed(4)}, {site.lon?.toFixed(4)}
                            {site.headroom_mw != null && <span style={{ marginLeft: 12, color: "#24a148" }}>{site.headroom_mw} MW headroom</span>}
                            {site.overall_score != null && <span style={{ marginLeft: 12, color: "#6c5ce7" }}>Score: {site.overall_score}/100</span>}
                          </div>
                        </div>
                        <button
                          onClick={() => onScoreSite?.(site.lat, site.lon, capacityMw, profile)}
                          style={{
                            background: "#0f62fe", color: "#fff", border: "none", borderRadius: 6,
                            padding: "6px 16px", fontWeight: 600, fontSize: 12, cursor: "pointer",
                          }}
                        >
                          Score
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {prospectResults && prospectResults.length === 0 && (
                  <div style={{ marginTop: 12, color: "#888", fontSize: 13 }}>No candidates found. Try a broader query.</div>
                )}
              </div>
            )}

            {method === "compare" && (
              <div>
                <div style={{ fontSize: 13, color: "#888", marginBottom: 10 }}>
                  Compare all {googleSites.length} Google reference sites head-to-head:
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
                  {googleSites.map((s) => (
                    <span key={s.name} style={{ background: "#16162a", border: "1px solid #444", borderRadius: 6, padding: "4px 10px", fontSize: 12, color: "#ccc" }}>
                      {s.name}
                    </span>
                  ))}
                </div>
                <button
                  onClick={handleCompare}
                  style={{
                    background: "#6c5ce7", color: "#fff", border: "none", borderRadius: 8,
                    padding: "10px 24px", fontWeight: 700, fontSize: 13, cursor: "pointer",
                  }}
                >
                  Compare {googleSites.length} Sites
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Google UK Sites ────────────────────────────────────────── */}
      <div style={section}>
        <div style={sectionTitle}>Google UK Sites</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {googleSites.map((site) => (
            <div
              key={site.name}
              style={{ ...card }}
              onMouseOver={(e) => { e.currentTarget.style.borderColor = "#0f62fe"; e.currentTarget.style.transform = "translateY(-2px)"; }}
              onMouseOut={(e) => { e.currentTarget.style.borderColor = "#333360"; e.currentTarget.style.transform = "none"; }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                <div style={{ fontWeight: 700, fontSize: 15, color: "#fff" }}>{site.name}</div>
                <span style={{
                  fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
                  background: statusColor(site.status) + "22", color: statusColor(site.status),
                  padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap",
                }}>
                  {site.status}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
                {site.region || "UK"}
              </div>
              <div style={{ fontSize: 12, color: "#666", marginBottom: 4 }}>
                {site.lat.toFixed(4)}, {site.lon.toFixed(4)}
              </div>
              <div style={{ fontSize: 13, color: "#0f62fe", fontWeight: 600, marginBottom: 12 }}>
                {site.capacity || "TBC"}
              </div>
              <button
                onClick={() => handleScoreGoogleSite(site)}
                style={{
                  width: "100%", background: "transparent", border: "1px solid #0f62fe",
                  color: "#0f62fe", borderRadius: 6, padding: "7px 0", fontWeight: 700,
                  fontSize: 12, cursor: "pointer", transition: "all 0.15s",
                }}
                onMouseOver={(e) => { e.target.style.background = "#0f62fe"; e.target.style.color = "#fff"; }}
                onMouseOut={(e) => { e.target.style.background = "transparent"; e.target.style.color = "#0f62fe"; }}
              >
                Score Site
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* ── Differentiators ────────────────────────────────────────── */}
      <div style={{ ...section, paddingBottom: 64 }}>
        <div style={sectionTitle}>Why Princeps</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} style={{ ...card, cursor: "default" }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>{d.icon}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", marginBottom: 8 }}>{d.title}</div>
              <div style={{ fontSize: 13, color: "#888", lineHeight: 1.6 }}>{d.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
