import React, { useState, useEffect, useCallback, useRef } from "react";
import { useSite } from "../SiteContext";
import { injectDemoData, DEMO_AGENT_RESULT, DEMO_SOLAR_YIELD, DEMO_GEEFLOW_DATA, DEMO_GRID_CONTEXT } from "../data/demoData";
import ScoreCard from "./cards/ScoreCard";
import SolarCard from "./cards/SolarCard";
import GridContextCard from "./cards/GridContextCard";

const MB_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";
// Bicester demo site: 51.88N, -1.16W — satellite imagery
const SAT_IMG = MB_TOKEN ? `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/-1.16,51.88,14.5,0/600x450@2x?access_token=${MB_TOKEN}` : "";
const MAP_IMG = MB_TOKEN ? `https://api.mapbox.com/styles/v1/mapbox/dark-v11/static/pin-s+0f62fe(-1.16,51.88),pin-s+f1c21b(-1.145,51.882)/-1.152,51.881,13.5,0/500x320@2x?access_token=${MB_TOKEN}` : "";

const SLIDES = [
  { id: "hero", label: "PRINCEPS" },
  { id: "dc-opportunity", label: "OPPORTUNITY" },
  { id: "dc-problem", label: "PROBLEM" },
  { id: "dc-solution", label: "SOLUTION" },
  { id: "dc-engine", label: "15D ENGINE" },
  { id: "dc-cfe", label: "24/7 CFE%" },
  { id: "dc-demo", label: "LIVE DEMO" },
  { id: "dc-comparison", label: "COMPARE" },
  { id: "dc-google-sites", label: "GOOGLE UK" },
  { id: "dc-competitive", label: "VS OTHERS" },
  { id: "dc-data", label: "DATA STACK" },
  { id: "architecture", label: "TECH ARCH" },
  { id: "traction", label: "TRACTION" },
  { id: "business", label: "BUSINESS" },
  { id: "team", label: "TEAM / ASK" },
];

export default function PitchPage({ onExit }) {
  const [slide, setSlide] = useState(0);
  const [direction, setDirection] = useState(1); // 1=forward, -1=back
  const ctx = useSite();
  const prevDataRef = useRef(null);

  // Inject demo data on mount, restore on unmount
  useEffect(() => {
    prevDataRef.current = {
      parcelId: ctx.parcelId,
      agentResult: ctx.agentResult,
      workflowStage: ctx.workflowStage,
    };
    injectDemoData(ctx);
    return () => {
      // Restore previous state
      if (prevDataRef.current) {
        ctx.setParcelId(prevDataRef.current.parcelId);
        ctx.setAgentResult(prevDataRef.current.agentResult);
        if (ctx.setWorkflowStage) ctx.setWorkflowStage(prevDataRef.current.workflowStage);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const next = useCallback(() => { setDirection(1); setSlide(s => Math.min(s + 1, SLIDES.length - 1)); }, []);
  const prev = useCallback(() => { setDirection(-1); setSlide(s => Math.max(s - 1, 0)); }, []);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
      if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      if (e.key === "Escape") onExit();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev, onExit]);

  return (
    <div className="pitch-page">
      {/* Header */}
      <div className="pitch-header">
        <button className="pitch-back-btn" onClick={onExit}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          ESC
        </button>
        <div className="pitch-slide-nav">
          {SLIDES.map((s, i) => (
            <button
              key={s.id}
              className={`pitch-dot${i === slide ? " active" : ""}${i < slide ? " visited" : ""}`}
              onClick={() => { setDirection(i > slide ? 1 : -1); setSlide(i); }}
              title={s.label}
            />
          ))}
        </div>
        <span className="pitch-slide-counter">{slide + 1} / {SLIDES.length}</span>
      </div>

      {/* 16:9 slide frame */}
      <div className="pitch-stage-area">
        <div className="pitch-frame-16x9">
          <div key={slide} className={`pitch-slide-transition ${direction > 0 ? "pitch-enter-right" : "pitch-enter-left"}`}>
            {slide === 0 && <SlideHero />}
            {slide === 1 && <SlideDCOpportunity />}
            {slide === 2 && <SlideDCProblem />}
            {slide === 3 && <SlideDCSolution />}
            {slide === 4 && <SlideDCEngine />}
            {slide === 5 && <SlideDCCFE />}
            {slide === 6 && <SlideDCDemo />}
            {slide === 7 && <SlideDCComparison />}
            {slide === 8 && <SlideDCGoogleSites />}
            {slide === 9 && <SlideDCCompetitive />}
            {slide === 10 && <SlideDCData />}
            {slide === 11 && <SlideArchitecture />}
            {slide === 12 && <SlideTraction />}
            {slide === 13 && <SlideBusiness />}
            {slide === 14 && <SlideTeam />}
          </div>
        </div>
      </div>

      {/* Navigation arrows — bottom center */}
      <div className="pitch-nav">
        <button className="pitch-nav-btn" onClick={prev} disabled={slide === 0}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="pitch-slide-label">{SLIDES[slide].label}</span>
        <button className="pitch-nav-btn" onClick={next} disabled={slide === SLIDES.length - 1}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
        </button>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════
   PRODUCT FRAME — browser chrome mockup
   ══════════════════════════════════════════════════ */

function ProductFrame({ title, children, className }) {
  return (
    <div className={`pf-chrome ${className || ""}`}>
      <div className="pf-titlebar">
        <div className="pf-dots">
          <span className="pf-dot-r" /><span className="pf-dot-y" /><span className="pf-dot-g" />
        </div>
        <span className="pf-url">{title || "princeps.app"}</span>
        <div className="pf-dots" style={{ visibility: "hidden" }}>
          <span className="pf-dot-r" /><span className="pf-dot-y" /><span className="pf-dot-g" />
        </div>
      </div>
      <div className="pf-viewport">
        {children}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════
   STATIC DISPLAY COMPONENTS (no side effects)
   ══════════════════════════════════════════════════ */

/** Static verdict display — reads agentResult from context, no API calls */
function StaticVerdict() {
  const { agentResult } = useSite();
  if (!agentResult) return null;
  const cls = agentResult.verdict === "GO" ? "verdict-go"
    : agentResult.verdict === "CAUTION" ? "verdict-caution" : "verdict-nogo";
  return (
    <div className="pitch-static-verdict">
      <div className="pitch-verdict-hero-row">
        <span className={`pitch-verdict-live-badge ${cls}`}>{agentResult.verdict}</span>
        <span className="pitch-verdict-conf">
          {Math.round((agentResult.confidence || 0) * 100)}% confidence
        </span>
      </div>
      <div className="pitch-verdict-summary">{agentResult.summary}</div>
      {agentResult.risks?.length > 0 && (
        <div className="pitch-verdict-section">
          <span className="pitch-verdict-section-label">RISKS</span>
          {agentResult.risks.slice(0, 2).map((r, i) => (
            <div key={i} className="pitch-verdict-item pitch-verdict-risk">{r}</div>
          ))}
        </div>
      )}
      {agentResult.opportunities?.length > 0 && (
        <div className="pitch-verdict-section">
          <span className="pitch-verdict-section-label">OPPORTUNITIES</span>
          {agentResult.opportunities.slice(0, 2).map((o, i) => (
            <div key={i} className="pitch-verdict-item pitch-verdict-opp">{o}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Static analytics strip — same metrics as AnalyticsStrip but no setInterval */
function StaticAnalytics() {
  const { agentResult, solarYield, gridContext, explain, parcelId, pickedLocation } = useSite();

  const verdict = agentResult?.verdict;
  const verdictColor = verdict === "GO" ? "#4caf50" : verdict === "CAUTION" ? "#ff9800" : verdict === "NO-GO" ? "#f44336" : "#546e7a";

  const cf = solarYield?.capacity_factor_pct;
  const annualKwh = solarYield?.annual_energy_kwh;
  const score = explain?.score_total;
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const confidence = agentResult?.confidence;

  const metrics = [
    { label: "YIELD", value: annualKwh ? `${(annualKwh / 1000).toFixed(1)} MWh/yr` : "--", color: "#ff9800" },
    { label: "CF", value: cf ? `${cf.toFixed(1)}%` : "--", color: "#D4A018" },
    { label: "SCORE", value: score != null ? `${score}/120` : "--", color: "#22c55e" },
    { label: "GRID", value: gridDist ? `${gridDist.toFixed(1)} km` : "--", color: "#2196f3" },
    { label: "CONF", value: confidence ? `${Math.round(confidence * 100)}%` : "--", color: "#7c4dff" },
  ];

  return (
    <div className="analytics-area analytics-strip" style={{ pointerEvents: "none" }}>
      <div className="analytics-status">
        <span className="analytics-dot" style={{ background: verdictColor, boxShadow: `0 0 8px ${verdictColor}` }} />
        <span className="analytics-verdict" style={{ color: verdictColor }}>
          {verdict || "STANDBY"}
        </span>
      </div>
      <div className="analytics-metrics">
        {metrics.map((m) => (
          <div key={m.label} className="analytics-metric">
            <span className="analytics-metric-label">{m.label}</span>
            <span className="analytics-metric-value" style={{ color: m.color }}>{m.value}</span>
          </div>
        ))}
      </div>
      <div className="analytics-meta">
        {pickedLocation && (
          <span className="analytics-coord">
            {pickedLocation.lat.toFixed(3)}N {Math.abs(pickedLocation.lon).toFixed(3)}{pickedLocation.lon < 0 ? "W" : "E"}
          </span>
        )}
        {parcelId && <span className="analytics-pid">{parcelId.slice(0, 8)}</span>}
        <span className="analytics-time">12:00:00Z</span>
      </div>
    </div>
  );
}

/** Mock chat messages showing product capability */
function MockChat() {
  const messages = [
    { role: "user", text: "What's the grid connection cost for this 5MW solar site?" },
    { role: "tool", name: "grid_study", text: "Querying DNO headroom for Bicester 33kV..." },
    { role: "assistant", text: "The nearest connection point is Bicester 33kV Primary, 1.8km from your site. With 12.5MW headroom available, a 5MW connection is feasible. Estimated connection cost: \u00A3285,000-\u00A3340,000 via G99 application to SSEN. No reinforcement works required at this capacity." },
    { role: "user", text: "Run a full feasibility assessment" },
    { role: "tool", name: "feasibility_engine", text: "Running 9-domain analysis..." },
    { role: "tool", name: "satellite_cv", text: "Processing Sentinel-2 + DynamicWorld..." },
    { role: "tool", name: "sam_simulation", text: "PvWattsv8 hourly yield \u2014 5,475 MWh/yr" },
    { role: "assistant", text: "GO \u2014 87% confidence. Site scores well across all domains. Grade 3b agricultural land, Flood Zone 1, no protected area constraints. Capacity factor 10.95%. See full verdict in the Agent panel." },
  ];
  return (
    <div className="pf-chat">
      {messages.map((m, i) => (
        <div key={i} className={`pf-chat-msg pf-chat-${m.role}`}>
          {m.role === "tool" && (
            <div className="pf-chat-tool">
              <span className="pf-chat-tool-icon">&#9881;</span>
              <span className="pf-chat-tool-name">{m.name}</span>
              <span className="pf-chat-tool-text">{m.text}</span>
            </div>
          )}
          {m.role !== "tool" && (
            <div className="pf-chat-bubble">
              <span className="pf-chat-role">{m.role === "user" ? "YOU" : "PRINCEPS"}</span>
              <span className="pf-chat-text">{m.text}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Map viewport with real Mapbox imagery + overlays */
function MockMapView() {
  return (
    <div className="pf-map">
      <div className="pf-map-bg">
        {MAP_IMG ? (
          <img src={MAP_IMG} alt="Map — Bicester site" className="pf-map-real-img" />
        ) : (
          <div className="pf-map-fallback" />
        )}
        {/* Site boundary + substation overlay */}
        <svg className="pf-map-overlay" viewBox="0 0 500 320" preserveAspectRatio="xMidYMid slice">
          <polygon points="160,100 340,90 350,230 170,240" fill="rgba(212,160,24,0.12)" stroke="#D4A018" strokeWidth="1.5" strokeDasharray="4,2" />
          <line x1="345" y1="160" x2="400" y2="145" stroke="#f1c21b" strokeWidth="1" strokeDasharray="3,3" opacity="0.6" />
          <text x="250" y="175" textAnchor="middle" fill="#D4A018" fontSize="9" fontWeight="700">5 MW SOLAR SITE</text>
          <text x="400" y="135" textAnchor="middle" fill="#f1c21b" fontSize="7">33kV PRIMARY</text>
          <text x="375" y="165" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="6">1.8km</text>
        </svg>
      </div>
      {/* Floating KPI cards */}
      <div className="pf-map-kpi pf-map-kpi-tl">
        <span className="pf-kpi-label">VERDICT</span>
        <span className="pf-kpi-value" style={{ color: "#24a148" }}>GO</span>
      </div>
      <div className="pf-map-kpi pf-map-kpi-tr">
        <span className="pf-kpi-label">CF</span>
        <span className="pf-kpi-value" style={{ color: "#D4A018" }}>10.95%</span>
      </div>
      <div className="pf-map-kpi pf-map-kpi-bl">
        <span className="pf-kpi-label">YIELD</span>
        <span className="pf-kpi-value" style={{ color: "#f1c21b" }}>5,475 MWh/yr</span>
      </div>
      <div className="pf-map-kpi pf-map-kpi-br">
        <span className="pf-kpi-label">HEADROOM</span>
        <span className="pf-kpi-value" style={{ color: "#a56eff" }}>12.5 MW</span>
      </div>
    </div>
  );
}

/** Domain radar using inline SVG — supports custom domains/keys or defaults to DEMO data */
function DomainRadar({ domains: customDomains, keys: customKeys }) {
  const defaultDomains = DEMO_AGENT_RESULT.domains;
  const domains = customDomains || defaultDomains;
  const keys = customKeys || Object.keys(domains);
  const n = keys.length;
  const cx = 100, cy = 100, r = 80;

  const points = keys.map((k, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    const val = (domains[k].score || 0) / 100;
    return {
      x: cx + r * val * Math.cos(angle),
      y: cy + r * val * Math.sin(angle),
      lx: cx + (r + 18) * Math.cos(angle),
      ly: cy + (r + 18) * Math.sin(angle),
      label: k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
      score: domains[k].score,
      status: domains[k].status,
    };
  });

  const polyPoints = points.map(p => `${p.x},${p.y}`).join(" ");

  return (
    <svg viewBox="0 0 200 200" className="pitch-radar-svg">
      {/* Background rings */}
      {[0.25, 0.5, 0.75, 1].map(s => (
        <polygon key={s} points={keys.map((_, i) => {
          const angle = (2 * Math.PI * i) / n - Math.PI / 2;
          return `${cx + r * s * Math.cos(angle)},${cy + r * s * Math.sin(angle)}`;
        }).join(" ")} fill="none" stroke="rgba(82,82,82,0.2)" strokeWidth="0.5" />
      ))}
      {/* Axis lines */}
      {keys.map((_, i) => {
        const angle = (2 * Math.PI * i) / n - Math.PI / 2;
        return <line key={i} x1={cx} y1={cy} x2={cx + r * Math.cos(angle)} y2={cy + r * Math.sin(angle)} stroke="rgba(82,82,82,0.15)" strokeWidth="0.5" />;
      })}
      {/* Data polygon */}
      <polygon points={polyPoints} fill="rgba(212,160,24,0.15)" stroke="#D4A018" strokeWidth="1.5" />
      {/* Data points */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="2.5" fill={p.status === "GO" ? "#24a148" : p.status === "CAUTION" ? "#f1c21b" : "#da1e28"} />
      ))}
      {/* Labels */}
      {points.map((p, i) => (
        <text key={i} x={p.lx} y={p.ly} textAnchor="middle" dominantBaseline="middle" fill="var(--text-dim)" fontSize="4.5" fontFamily="var(--mono)">
          {p.label.length > 12 ? p.label.slice(0, 11) + ".." : p.label}
        </text>
      ))}
    </svg>
  );
}

/** Monthly solar generation bar chart */
function MonthlyYieldChart() {
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  const data = DEMO_SOLAR_YIELD.monthly_energy_kwh;
  const max = Math.max(...data);
  return (
    <div className="pitch-mini-chart">
      {data.map((v, i) => (
        <div key={i} className="pitch-chart-col">
          <div className="pitch-chart-bar" style={{ height: `${(v / max) * 100}%` }} />
          <span className="pitch-chart-label">{months[i]}</span>
        </div>
      ))}
    </div>
  );
}

/** Land use donut from GeeFlow data */
function LandUseDonut() {
  const classes = DEMO_GEEFLOW_DATA.extractions.land_use.class_percentages;
  const colors = {
    grass: "#24a148", crops: "#f1c21b", built: "#da1e28", trees: "#D4A018",
    shrub_and_scrub: "#a56eff", bare: "#8d8d8d", water: "#1e90ff",
    flooded_vegetation: "#00bcd4", snow_and_ice: "#e0e0e0",
  };
  const entries = Object.entries(classes).filter(([, v]) => v > 0.5).sort((a, b) => b[1] - a[1]);
  let cumulative = 0;
  const segments = entries.map(([cls, pct]) => {
    const start = cumulative;
    cumulative += pct;
    return { cls, pct, start, color: colors[cls] || "#525252" };
  });

  return (
    <div className="pitch-donut-wrap">
      <svg viewBox="0 0 100 100" className="pitch-donut-svg">
        {segments.map((s, i) => {
          const r = 35, circ = 2 * Math.PI * r;
          return (
            <circle key={i} cx="50" cy="50" r={r} fill="none"
              stroke={s.color} strokeWidth="10"
              strokeDasharray={`${(s.pct / 100) * circ} ${circ}`}
              strokeDashoffset={`${-(s.start / 100) * circ}`}
              transform="rotate(-90 50 50)" />
          );
        })}
        <text x="50" y="48" textAnchor="middle" fill="var(--text-bright)" fontSize="10" fontFamily="var(--mono)" fontWeight="800">
          {DEMO_GEEFLOW_DATA.extractions.land_use.developable_pct}%
        </text>
        <text x="50" y="58" textAnchor="middle" fill="var(--text-dim)" fontSize="5" fontFamily="var(--mono)">
          DEVELOPABLE
        </text>
      </svg>
      <div className="pitch-donut-legend">
        {entries.slice(0, 4).map(([cls, pct]) => (
          <div key={cls} className="pitch-donut-leg-item">
            <span className="pitch-donut-swatch" style={{ background: colors[cls] }} />
            <span>{cls.replace(/_/g, " ")}</span>
            <span className="pitch-donut-pct">{pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Terrain stats from GeeFlow data */
function TerrainStats() {
  const t = DEMO_GEEFLOW_DATA.extractions.terrain;
  const stats = [
    { label: "ELEVATION", value: `${t.elevation.mean_m}m`, sub: `${t.elevation.min_m}-${t.elevation.max_m}m range` },
    { label: "SLOPE", value: `${t.slope.mean_deg}\u00B0`, sub: `P90: ${t.slope.p90_deg}\u00B0` },
    { label: "ASPECT", value: t.aspect.dominant_direction, sub: `${t.aspect.south_facing_pct}% south-facing` },
    { label: "ROUGHNESS", value: t.roughness.mean.toFixed(2), sub: "Surface index" },
  ];
  return (
    <div className="pitch-terrain-stats">
      {stats.map(s => (
        <div key={s.label} className="pitch-terrain-stat">
          <span className="pitch-terrain-label">{s.label}</span>
          <span className="pitch-terrain-value">{s.value}</span>
          <span className="pitch-terrain-sub">{s.sub}</span>
        </div>
      ))}
    </div>
  );
}

/** Score gauge bar — simple inline */
function ScoreGaugeBar() {
  const sc = DEMO_GEEFLOW_DATA.site_score;
  const pct = (sc.total_score / sc.max_score) * 100;
  return (
    <div className="pitch-score-gauge">
      <div className="pitch-score-gauge-header">
        <span className="pitch-score-gauge-label">SATELLITE SCORE</span>
        <span className="pitch-score-gauge-value">{sc.total_score}/{sc.max_score}</span>
      </div>
      <div className="pitch-score-gauge-track">
        <div className="pitch-score-gauge-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="pitch-score-gauge-components">
        {Object.entries(sc.components).map(([k, v]) => (
          <div key={k} className="pitch-score-gauge-comp">
            <span>{k}</span>
            <span>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════
   SLIDE COMPONENTS
   ══════════════════════════════════════════════════ */

function SlideHero() {
  return (
    <div className="pitch-slide pitch-slide-hero">
      <div className="pitch-hero-glow" />
      <div className="pitch-hero-grid-bg" />
      <span className="pitch-hero-eyebrow">THE UK'S MOST INTELLIGENT DATA CENTRE SITE SELECTION ENGINE</span>
      <h1 className="pitch-hero-title">PRINCEPS</h1>
      <p className="pitch-hero-sub">
        15-dimension AI scoring with real grid capacity data from all 6 UK DNOs, 24/7 CFE% modelling, and integrated environmental intelligence. No competitor platform does this.
      </p>
      <div className="pitch-hero-tagline">Data centre site intelligence. Automated. Institutional-grade.</div>
      <div className="pitch-hero-stats">
        <StatBox label="UK DNOs" value="6" color="var(--pg-green)" />
        <StatBox label="DIMENSIONS" value="15" color="var(--pg-blue)" />
        <StatBox label="CFE MODEL" value="24/7" color="var(--pg-accent)" />
        <StatBox label="SUBSTATIONS" value="500+" color="var(--pg-purple)" />
      </div>
    </div>
  );
}

/* ── DC-FOCUSED SLIDES ── */

function SlideDCOpportunity() {
  const sites = [
    { name: "Waltham Cross", status: "Operational", statusColor: "#24a148", mw: "30 MW", detail: "UKPN network, Enfield substation cluster" },
    { name: "North Weald", status: "Approved", statusColor: "#3b82f6", mw: "50 MW", detail: "Planning consent granted 2024, UKPN 132kV feed" },
    { name: "Purfleet", status: "Acquired", statusColor: "#f1c21b", mw: "80 MW", detail: "Thames Enterprise Park, National Grid 275kV proximity" },
    { name: "Teesside", status: "Negotiation", statusColor: "#a56eff", mw: "100 MW", detail: "Freeport zone, NPG network, offshore wind CFE advantage" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="02" title="THE OPPORTUNITY" accent="var(--pg-green)" />
      <div className="pitch-cols">
        <div className="pitch-col">
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-green)" }}>&pound;5B+</span>
            <span className="pitch-big-label">Google's planned investment in UK data centre infrastructure. Hyperscalers are racing to secure power-ready sites with grid capacity, clean energy access, and planning certainty.</span>
          </div>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-blue)" }}>6+ GW</span>
            <span className="pitch-big-label">UK data centre power pipeline. The grid queue is 739 GW deep. Finding sites with actual available capacity is the bottleneck.</span>
          </div>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-accent)" }}>95%</span>
            <span className="pitch-big-label">Google's 24/7 Carbon-Free Energy target by 2030. Every new site must demonstrate achievable CFE% from day one.</span>
          </div>
        </div>
        <div className="pitch-col">
          <h3 className="pitch-section-head">GOOGLE UK DC PORTFOLIO</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sites.map(s => (
              <div key={s.name} className="pitch-competitor-card" style={{ borderLeftColor: s.statusColor }}>
                <div className="pitch-competitor-head">
                  <span className="pitch-competitor-dot" style={{ background: s.statusColor }} />
                  <span className="pitch-competitor-name">{s.name}</span>
                  <span className="pitch-intent-chip" style={{ borderColor: s.statusColor, color: s.statusColor }}>{s.status}</span>
                </div>
                <div className="pitch-competitor-focus">{s.mw} &mdash; {s.detail}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="pitch-callout pitch-callout-accent">
        <strong>The challenge:</strong> No platform integrates grid capacity + CFE% + PUE + constraints + financial TCO into a single automated DC site verdict. Site selection remains manual, fragmented, and slow.
      </div>
    </div>
  );
}

function SlideDCProblem() {
  return (
    <div className="pitch-slide">
      <SlideTitle num="03" title="WHAT'S BROKEN" accent="var(--pg-red)" />
      <div className="pitch-cols">
        <div className="pitch-col">
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-red)" }}>12-18 mo</span>
            <span className="pitch-big-label">Typical DC site selection cycle. By the time you have grid confirmation, competitors have secured the site.</span>
          </div>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-red)" }}>&pound;M+</span>
            <span className="pitch-big-label">Annual spend on consultant fees for grid studies, environmental assessments, planning due diligence, and CFE analysis per hyperscaler.</span>
          </div>
        </div>
        <div className="pitch-col">
          <h3 className="pitch-section-head">CURRENT DC SITE SELECTION IS FRAGMENTED</h3>
          <div className="pitch-pain-list">
            <PainPoint icon="01" text="Grid data is locked in DNO portals" detail="Each of 6 UK DNOs publishes capacity data in different formats, update cycles, and portals. No single view of real headroom. Most show 'N/A'." />
            <PainPoint icon="02" text="CFE% is manual spreadsheet work" detail="Modelling 24/7 carbon-free energy requires hourly generation profiles, PPA matching, grid carbon intensity data, and storage optimisation. Currently done by hand." />
            <PainPoint icon="03" text="Constraint checks take weeks" detail="Flood zones, SSSI/AONB buffers, aviation height limits, telecoms interference zones, water stress — each checked separately via different agencies." />
            <PainPoint icon="04" text="No PUE-aware site scoring" detail="Power Usage Effectiveness varies by climate zone, water availability, and altitude. No platform models this alongside grid and CFE constraints." />
            <PainPoint icon="05" text="Financial TCO is a black box" detail="Grid connection costs, reinforcement charges, PPA rates, and incentives vary wildly by location. No way to compare TCO across candidate sites." />
          </div>
        </div>
      </div>
      <div className="pitch-callout pitch-callout-danger">
        Result: 12-18 month site selection cycles, missed opportunities, and millions in consultant fees. Google needs a faster, data-driven approach.
      </div>
    </div>
  );
}

function SlideDCSolution() {
  const differentiators = [
    { title: "Real Grid Data", desc: "Live headroom from all 6 UK DNOs. Not estimates \u2014 actual available capacity at every substation.", color: "var(--pg-green)" },
    { title: "24/7 CFE% Model", desc: "Hourly generation profiles matched against Carbon Intensity API. PPA overlay from nearby REPD wind/solar assets.", color: "var(--pg-blue)" },
    { title: "15D AI Scoring", desc: "Grid, CFE, PUE, cooling, water, constraints, planning, environment, connectivity, land, finance, incentives, regulatory, security, resilience.", color: "var(--pg-accent)" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="04" title="THE PRINCEPS ANSWER" accent="var(--pg-green)" />
      <p className="pitch-lead" style={{ textAlign: "center", maxWidth: 700, margin: "0 auto 16px" }}>
        <strong>One platform. 15 dimensions. Real data. Instant verdict.</strong>
      </p>
      <div className="pitch-flow-row" style={{ justifyContent: "center", marginBottom: 20 }}>
        <FlowStep label="PICK SITE" active /><FlowArrow />
        <FlowStep label="AI SCORE (15D)" /><FlowArrow />
        <FlowStep label="COMPARE" /><FlowArrow />
        <FlowStep label="REPORT" /><FlowArrow />
        <FlowStep label="GO / NO-GO" />
      </div>
      <div className="pitch-cols" style={{ gap: 16 }}>
        {differentiators.map(d => (
          <div key={d.title} className="pitch-col">
            <div className="pitch-stage-card" style={{ borderTopColor: d.color, flex: 1 }}>
              <div className="pitch-stage-title" style={{ color: d.color }}>{d.title}</div>
              <div className="pitch-stage-sub">{d.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="pitch-cols" style={{ marginTop: 16 }}>
        <div className="pitch-col" style={{ flex: 1 }}>
          <ProductFrame title="princeps.app \u2014 DC Verdict">
            <div className="pitch-live-component">
              <StaticVerdict />
            </div>
          </ProductFrame>
        </div>
      </div>
    </div>
  );
}

function SlideDCEngine() {
  const dimensions = [
    { num: "01", name: "Grid Capacity", desc: "Real DNO headroom (MW)", icon: "\u26A1", isNew: false },
    { num: "02", name: "Grid Distance", desc: "km to nearest HV substation", icon: "\uD83D\uDCCD", isNew: false },
    { num: "03", name: "Grid Voltage", desc: "132kV/275kV/400kV access", icon: "\uD83D\uDD0C", isNew: false },
    { num: "04", name: "CFE%", desc: "24/7 carbon-free energy score", icon: "\u2600", isNew: true },
    { num: "05", name: "PUE Potential", desc: "Climate-adjusted efficiency", icon: "\u2744", isNew: true },
    { num: "06", name: "Cooling", desc: "Free cooling hours, wet bulb temp", icon: "\uD83D\uDCA8", isNew: true },
    { num: "07", name: "Flood Risk", desc: "EA zones + JRC surface water", icon: "\uD83C\uDF0A", isNew: false },
    { num: "08", name: "Constraints", desc: "SSSI, AONB, aviation, telecoms", icon: "\uD83D\uDEE1", isNew: true },
    { num: "09", name: "Planning", desc: "Local plan zoning, precedent", icon: "\uD83D\uDCCB", isNew: false },
    { num: "10", name: "Connectivity", desc: "IXP distance, fibre routes", icon: "\uD83C\uDF10", isNew: false },
    { num: "11", name: "Water Stress", desc: "EA water availability zones", icon: "\uD83D\uDCA7", isNew: true },
    { num: "12", name: "Land Use", desc: "DynamicWorld classification", icon: "\uD83C\uDF3F", isNew: false },
    { num: "13", name: "Financial TCO", desc: "Connection + PPA + rates", icon: "\uD83D\uDCB7", isNew: false },
    { num: "14", name: "Incentives", desc: "Freeport, EZ, UKIB zones", icon: "\uD83C\uDFC6", isNew: true },
    { num: "15", name: "Regulatory", desc: "NSIP thresholds, DCO route", icon: "\uD83D\uDCDC", isNew: false },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="05" title="15-DIMENSION DC SCORING" accent="var(--pg-blue)" badge="ENGINE" />
      <div className="pitch-domains-grid pitch-domains-compact" style={{ gridTemplateColumns: "repeat(5, 1fr)", gap: 6 }}>
        {dimensions.map(d => (
          <div key={d.num} className="pitch-domain-card" style={{ position: "relative" }}>
            <div className="pitch-domain-header">
              <span className="pitch-domain-num" style={{ color: d.isNew ? "#f1c21b" : "var(--pg-blue)" }}>{d.num}</span>
              {d.isNew && <span className="pitch-intent-chip" style={{ borderColor: "#f1c21b", color: "#f1c21b", fontSize: 7, padding: "1px 4px" }}>NEW</span>}
            </div>
            <div className="pitch-domain-name" style={{ fontSize: 10 }}>{d.icon} {d.name}</div>
            <div className="pitch-domain-detail" style={{ fontSize: 8 }}>{d.desc}</div>
          </div>
        ))}
      </div>
      <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 10 }}>
        <strong>6 new DC-specific dimensions</strong> (highlighted) added to the 9 existing energy infrastructure dimensions. Weighted scoring with Google-specific gates: CFE% &gt; 70% required, grid headroom &gt; 50 MW minimum.
      </div>
    </div>
  );
}

function SlideDCCFE() {
  const regions = [
    { name: "Scotland (North)", cfe: 92, color: "#24a148", note: "Abundant onshore wind + hydro" },
    { name: "Scotland (South)", cfe: 85, color: "#34c759", note: "Wind-dominant, good grid export" },
    { name: "North East", cfe: 78, color: "#3b82f6", note: "Offshore wind PPAs available" },
    { name: "North West", cfe: 72, color: "#3b82f6", note: "Onshore wind + nuclear baseload" },
    { name: "Yorkshire", cfe: 68, color: "#f1c21b", note: "Mixed wind/solar, Drax biomass" },
    { name: "Midlands", cfe: 58, color: "#ff9800", note: "Solar-dominant, limited wind" },
    { name: "East England", cfe: 62, color: "#f1c21b", note: "Offshore wind proximity" },
    { name: "London / SE", cfe: 42, color: "#ff453a", note: "Grid-dependent, minimal local RE" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="06" title="24/7 CARBON-FREE ENERGY" accent="var(--pg-green)" badge="CFE%" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 45%" }}>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-green)" }}>95%</span>
            <span className="pitch-big-label">Google's 24/7 CFE target by 2030. CFE% measures how much of your hourly electricity consumption is matched by carbon-free sources.</span>
          </div>
          <h3 className="pitch-section-head" style={{ marginTop: 12 }}>HOW PRINCEPS MODELS CFE%</h3>
          <div className="pitch-feature-list">
            <Feature icon="1" text="Hourly grid carbon intensity" detail="Carbon Intensity API data for each UK region, half-hourly resolution, 48-hour forecast" />
            <Feature icon="2" text="Local RE generation profiles" detail="REPD database: every consented wind/solar project within PPA range of the site" />
            <Feature icon="3" text="PPA overlay modelling" detail="Match site demand profile against nearby wind/solar output curves to calculate achievable CFE%" />
            <Feature icon="4" text="Storage optimisation" detail="BESS co-location shifts surplus RE hours to deficit hours, boosting effective CFE%" />
          </div>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 50%" }}>
          <h3 className="pitch-section-head">UK REGIONAL CFE% (ACHIEVABLE)</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {regions.map(r => (
              <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 9, fontFamily: "var(--mono)", color: "var(--text-dim)", width: 100, flexShrink: 0 }}>{r.name}</span>
                <div style={{ flex: 1, height: 14, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden", position: "relative" }}>
                  <div style={{ width: `${r.cfe}%`, height: "100%", background: r.color, borderRadius: 3, opacity: 0.8 }} />
                </div>
                <span style={{ fontSize: 11, fontFamily: "var(--mono)", fontWeight: 700, color: r.color, width: 32, textAlign: "right" }}>{r.cfe}%</span>
                <span style={{ fontSize: 7, color: "var(--text-dim)", width: 140, flexShrink: 0 }}>{r.note}</span>
              </div>
            ))}
          </div>
          <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 10, fontSize: 9 }}>
            <strong>Key insight:</strong> London sites achieve only ~42% CFE%. Moving 200 miles north to Teesside nearly doubles CFE% to 78%. Princeps quantifies this trade-off against latency, connectivity, and grid costs.
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideDCDemo() {
  const dcDimensions = {
    grid_capacity: { score: 82, status: "GO" },
    grid_distance: { score: 90, status: "GO" },
    cfe_percent: { score: 65, status: "CAUTION" },
    pue_potential: { score: 78, status: "GO" },
    cooling: { score: 72, status: "GO" },
    flood_risk: { score: 95, status: "GO" },
    constraints: { score: 88, status: "GO" },
    planning: { score: 70, status: "CAUTION" },
    connectivity: { score: 92, status: "GO" },
    water_stress: { score: 55, status: "CAUTION" },
    land_use: { score: 85, status: "GO" },
    financial_tco: { score: 68, status: "CAUTION" },
    incentives: { score: 40, status: "NO-GO" },
    regulatory: { score: 75, status: "GO" },
    resilience: { score: 80, status: "GO" },
  };
  const dcKeys = Object.keys(dcDimensions);
  return (
    <div className="pitch-slide">
      <SlideTitle num="07" title="LIVE DEMO" accent="var(--pg-accent)" badge="WALTHAM CROSS" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 55%" }}>
          <ProductFrame title="princeps.app \u2014 DC Site Score: Waltham Cross">
            <div style={{ padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <span style={{ fontSize: 32, fontWeight: 800, fontFamily: "var(--mono)", color: "var(--pg-green)" }}>78</span>
                  <span style={{ fontSize: 8, fontFamily: "var(--mono)", color: "var(--text-dim)" }}>DC-SCORE</span>
                </div>
                <div className="pitch-verdict-badge" style={{ borderColor: "var(--pg-green)", color: "var(--pg-green)", fontSize: 14, padding: "4px 12px" }}>GO</div>
                <div style={{ marginLeft: "auto", textAlign: "right" }}>
                  <div style={{ fontSize: 8, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>GRID HEADROOM</div>
                  <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--pg-blue)" }}>87 MW</div>
                  <div style={{ fontSize: 7, color: "var(--text-dim)" }}>UKPN Enfield 132kV</div>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 4, marginBottom: 8 }}>
                {[
                  { label: "CFE%", value: "52%", color: "#f1c21b" },
                  { label: "PUE", value: "1.18", color: "#24a148" },
                  { label: "IXP", value: "25km", color: "#3b82f6" },
                  { label: "FLOOD", value: "Zone 1", color: "#24a148" },
                  { label: "TCO", value: "\u00a318M", color: "#a56eff" },
                ].map(k => (
                  <div key={k.label} style={{ textAlign: "center", padding: "4px 0", background: "rgba(255,255,255,0.02)", borderRadius: 4 }}>
                    <div style={{ fontSize: 7, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>{k.label}</div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--mono)", color: k.color }}>{k.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </ProductFrame>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 40%", alignItems: "center" }}>
          <DomainRadar domains={dcDimensions} keys={dcKeys} />
          <div style={{ textAlign: "center", marginTop: 4 }}>
            <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>15-DIMENSION RADAR</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideDCComparison() {
  const sites = [
    {
      name: "Waltham Cross",
      score: 78, verdict: "GO", verdictColor: "#24a148",
      metrics: { "Grid Headroom": "87 MW", "CFE%": "52%", "PUE": "1.18", "IXP Distance": "25 km", "Flood Risk": "Zone 1", "Grid Voltage": "132 kV", "TCO (10yr)": "\u00a318M", "Planning": "Precedent" },
      radarData: {
        grid: { score: 85, status: "GO" }, cfe: { score: 52, status: "CAUTION" }, pue: { score: 78, status: "GO" },
        connectivity: { score: 75, status: "GO" }, constraints: { score: 88, status: "GO" }, financial: { score: 68, status: "CAUTION" },
      }
    },
    {
      name: "Teesside",
      score: 82, verdict: "GO", verdictColor: "#24a148",
      metrics: { "Grid Headroom": "120 MW", "CFE%": "74%", "PUE": "1.14", "IXP Distance": "50 km", "Flood Risk": "Zone 1", "Grid Voltage": "275 kV", "TCO (10yr)": "\u00a315M", "Planning": "Freeport EZ" },
      radarData: {
        grid: { score: 92, status: "GO" }, cfe: { score: 74, status: "GO" }, pue: { score: 85, status: "GO" },
        connectivity: { score: 50, status: "CAUTION" }, constraints: { score: 90, status: "GO" }, financial: { score: 80, status: "GO" },
      }
    },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="08" title="MULTI-SITE COMPARISON" accent="var(--pg-purple)" badge="HEAD-TO-HEAD" />
      <div className="pitch-cols" style={{ gap: 20 }}>
        {sites.map(s => (
          <div key={s.name} className="pitch-col">
            <div className="pitch-stage-card" style={{ borderTopColor: s.verdictColor, padding: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 24, fontWeight: 800, fontFamily: "var(--mono)", color: s.verdictColor }}>{s.score}</span>
                <div className="pitch-verdict-badge" style={{ borderColor: s.verdictColor, color: s.verdictColor }}>{s.verdict}</div>
                <span style={{ fontSize: 13, fontWeight: 700, marginLeft: "auto" }}>{s.name}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
                {Object.entries(s.metrics).map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "2px 4px", background: "rgba(255,255,255,0.02)", borderRadius: 3 }}>
                    <span style={{ fontSize: 8, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>{k}</span>
                    <span style={{ fontSize: 9, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--text-bright)" }}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
            <DomainRadar domains={s.radarData} keys={Object.keys(s.radarData)} />
          </div>
        ))}
      </div>
      <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 6 }}>
        <strong>Key deltas:</strong> Teesside wins on CFE% (+22%), grid headroom (+33 MW), PUE (1.14 vs 1.18), and TCO (-&pound;3M). Waltham Cross wins on connectivity (-25km IXP distance) and existing planning precedent.
      </div>
    </div>
  );
}

function SlideDCGoogleSites() {
  const googleSites = [
    { name: "Waltham Cross", lat: 51.69, lon: -0.03, score: 78, verdict: "GO", verdictColor: "#24a148", headroom: "87 MW", cfe: "52%", pue: "1.18" },
    { name: "North Weald", lat: 51.72, lon: 0.16, score: 74, verdict: "GO", verdictColor: "#24a148", headroom: "65 MW", cfe: "48%", pue: "1.20" },
    { name: "Purfleet", lat: 51.48, lon: 0.24, score: 71, verdict: "CAUTION", verdictColor: "#f1c21b", headroom: "110 MW", cfe: "45%", pue: "1.22" },
    { name: "Teesside", lat: 54.60, lon: -1.07, score: 82, verdict: "GO", verdictColor: "#24a148", headroom: "120 MW", cfe: "74%", pue: "1.14" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="09" title="GOOGLE UK SITES" accent="var(--pg-blue)" badge="PRE-SCORED" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 45%" }}>
          {/* Simplified UK map with site pins */}
          <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: 12, border: "1px solid rgba(255,255,255,0.06)", position: "relative", height: 320 }}>
            <svg viewBox="0 0 200 320" style={{ width: "100%", height: "100%" }}>
              {/* Simplified UK outline */}
              <path d="M80,20 C90,15 110,18 115,25 C120,35 125,45 120,60 C118,70 122,80 125,90 C130,105 135,115 130,130 C125,140 128,150 132,160 C138,175 140,185 135,200 C130,210 125,220 120,230 C115,240 110,248 105,255 C100,262 95,268 90,275 C85,280 80,285 78,290 C75,295 72,298 70,300 C68,295 65,285 68,275 C70,265 72,255 68,245 C65,235 60,225 62,215 C64,205 68,195 70,185 C72,175 70,165 68,155 C65,145 62,135 65,125 C68,115 72,105 70,95 C68,85 65,75 68,65 C70,55 75,45 78,35 C79,28 80,24 80,20Z"
                fill="rgba(212,160,24,0.06)" stroke="rgba(212,160,24,0.2)" strokeWidth="1" />
              {/* Site markers */}
              {googleSites.map(s => {
                // Map lat/lon to SVG coordinates (approximate)
                const x = 85 + (s.lon + 1.5) * 30;
                const y = 320 - ((s.lat - 50) * 55);
                return (
                  <g key={s.name}>
                    <circle cx={x} cy={y} r="6" fill={s.verdictColor} opacity="0.3" />
                    <circle cx={x} cy={y} r="3" fill={s.verdictColor} />
                    <text x={x + 10} y={y + 3} fill="var(--text-bright)" fontSize="7" fontWeight="600">{s.name}</text>
                    <text x={x + 10} y={y + 11} fill={s.verdictColor} fontSize="6" fontFamily="var(--mono)">{s.score} {s.verdict}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 50%" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {googleSites.map(s => (
              <div key={s.name} className="pitch-stage-card" style={{ borderTopColor: s.verdictColor, padding: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: 20, fontWeight: 800, fontFamily: "var(--mono)", color: s.verdictColor }}>{s.score}</span>
                  <div className="pitch-verdict-badge" style={{ borderColor: s.verdictColor, color: s.verdictColor, fontSize: 10, padding: "2px 8px" }}>{s.verdict}</div>
                  <span style={{ fontWeight: 700, fontSize: 12 }}>{s.name}</span>
                </div>
                <div style={{ display: "flex", gap: 12 }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 7, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>HEADROOM</div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--pg-blue)" }}>{s.headroom}</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 7, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>CFE%</div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--pg-green)" }}>{s.cfe}</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 7, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>PUE</div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--pg-accent)" }}>{s.pue}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 10, fontSize: 9 }}>
            <strong>Pre-scored and ready for your team.</strong> Each site assessed across all 15 dimensions with real DNO data. Export as PDF, share via API, or explore interactively.
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideDCCompetitive() {
  const features = [
    { cap: "Real Grid Headroom (MW)", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
    { cap: "24/7 CFE% Modelling", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
    { cap: "PUE Modelling", us: true, athena: false, romonet: true, cbre: false, peaknode: false },
    { cap: "Constraint Overlay", us: true, athena: false, romonet: false, cbre: true, peaknode: false },
    { cap: "Financial TCO", us: true, athena: true, romonet: false, cbre: true, peaknode: false },
    { cap: "AI Prospecting", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
    { cap: "Multi-site Compare", us: true, athena: true, romonet: false, cbre: true, peaknode: true },
    { cap: "15-Dimension Scoring", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
    { cap: "All 6 UK DNOs", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
    { cap: "Satellite Intelligence", us: true, athena: false, romonet: false, cbre: false, peaknode: false },
  ];
  const Dot = ({ on }) => (
    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: on ? "var(--pg-green)" : "rgba(255,69,58,0.4)", border: on ? "none" : "1px solid rgba(255,69,58,0.3)" }} />
  );
  const competitors = [
    { code: "ATH", name: "Athena (Compass)", gap: "No real grid data, no CFE%, proprietary only", color: "#ff6b6b" },
    { code: "ROM", name: "Romonet (Vertiv)", gap: "PUE modelling only, no site selection or grid", color: "#f1c21b" },
    { code: "CBRE", name: "CBRE DataSite", gap: "Advisory service, not automated, weeks per report", color: "#3b82f6" },
    { code: "PEAK", name: "Peaknode", gap: "Headroom shows N/A, no CFE%, no constraints", color: "#a56eff" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="10" title="VS COMPETITORS" accent="var(--pg-green)" badge="DC MARKET MAP" />
      <div className="pitch-cols" style={{ gap: 16 }}>
        <div className="pitch-col" style={{ flex: "0 0 40%", gap: 6 }}>
          {competitors.map(c => (
            <div key={c.code} className="pitch-competitor-card">
              <div className="pitch-competitor-head">
                <span className="pitch-competitor-dot" style={{ background: c.color }} />
                <span className="pitch-competitor-name">{c.name}</span>
              </div>
              <div className="pitch-competitor-gap">{c.gap}</div>
            </div>
          ))}
        </div>
        <div className="pitch-col" style={{ flex: 1 }}>
          <div className="pitch-cap-matrix">
            <div className="pitch-cap-header">
              <span className="pitch-cap-label">CAPABILITY</span>
              <span className="pitch-cap-col" style={{ color: "var(--pg-green)" }}>US</span>
              <span className="pitch-cap-col">ATH</span>
              <span className="pitch-cap-col">ROM</span>
              <span className="pitch-cap-col">CBRE</span>
              <span className="pitch-cap-col">PEAK</span>
            </div>
            {features.map(r => (
              <div key={r.cap} className="pitch-cap-row">
                <span className="pitch-cap-label">{r.cap}</span>
                <span className="pitch-cap-col"><Dot on={r.us} /></span>
                <span className="pitch-cap-col"><Dot on={r.athena} /></span>
                <span className="pitch-cap-col"><Dot on={r.romonet} /></span>
                <span className="pitch-cap-col"><Dot on={r.cbre} /></span>
                <span className="pitch-cap-col"><Dot on={r.peaknode} /></span>
              </div>
            ))}
            <div className="pitch-cap-legend">
              ATH = Athena/Compass &middot; ROM = Romonet/Vertiv &middot; CBRE = CBRE DataSite &middot; PEAK = Peaknode
            </div>
          </div>
        </div>
      </div>
      <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 8 }}>
        <strong>No competitor integrates real grid headroom + 24/7 CFE% + PUE + constraint overlay + financial TCO + AI prospecting.</strong> Princeps is the only platform that does all six.
      </div>
    </div>
  );
}

function SlideDCData() {
  const dataSources = [
    { category: "Grid (6 UK DNOs)", sources: ["UKPN", "NGED", "NPG", "SPEN", "ENWL", "SSEN"], color: "var(--pg-blue)", icon: "\u26A1" },
    { category: "Carbon & Energy", sources: ["Carbon Intensity API", "REPD", "TEC Register", "BMRS Demand"], color: "var(--pg-green)", icon: "\u2600" },
    { category: "Environmental", sources: ["Natural England (SSSI/AONB/ALC)", "EA Flood Data", "EA Water Resources"], color: "#24a148", icon: "\uD83C\uDF3F" },
    { category: "Connectivity", sources: ["PeeringDB", "Ofcom", "OS MasterMap"], color: "var(--pg-purple)", icon: "\uD83C\uDF10" },
    { category: "Satellite (GeeFlow)", sources: ["DynamicWorld", "ERA5-Land", "Sentinel-2", "NASADEM"], color: "#D4A018", icon: "\uD83D\uDEF0" },
    { category: "Planning & Land", sources: ["Planning Portal", "Land Registry", "INSPIRE WMS"], color: "var(--pg-accent)", icon: "\uD83D\uDCCB" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="11" title="DATA STACK" accent="var(--pg-purple)" badge="20+ SOURCES" />
      <div className="pitch-domains-grid pitch-domains-compact" style={{ gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        {dataSources.map(d => (
          <div key={d.category} className="pitch-stage-card" style={{ borderTopColor: d.color, padding: 10 }}>
            <div className="pitch-stage-title" style={{ fontSize: 11 }}>
              <span style={{ marginRight: 6 }}>{d.icon}</span>{d.category}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
              {d.sources.map(s => (
                <span key={s} className="pitch-intent-chip" style={{ fontSize: 8 }}>{s}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="pitch-cols" style={{ marginTop: 12 }}>
        <div className="pitch-col">
          <div className="pitch-callout pitch-callout-accent">
            <strong>20+ data sources, all free or open, all real-time.</strong> No manual data entry. No stale spreadsheets. Princeps pulls live data from every UK DNO, government agency, and satellite platform on every assessment.
          </div>
        </div>
      </div>
      <div className="pitch-hero-stats" style={{ marginTop: 12 }}>
        <StatBox label="DATA SOURCES" value="20+" color="var(--pg-blue)" />
        <StatBox label="UK DNOs" value="6/6" color="var(--pg-green)" />
        <StatBox label="SUBSTATIONS" value="500+" color="var(--pg-accent)" />
        <StatBox label="REPD ASSETS" value="12K+" color="var(--pg-purple)" />
      </div>
    </div>
  );
}

/* ── KEPT SLIDES (architecture, traction, business, team) ── */

function SlideArchitecture() {
  return (
    <div className="pitch-slide">
      <SlideTitle num="12" title="Platform Architecture" accent="var(--pg-purple)" badge="TECH STACK" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 36%", gap: 14 }}>
          {/* Architecture vertical flow */}
          <div className="pitch-arch-flow">
            <ArchNode label="FRONTEND" color="var(--pg-blue)" chips={["React + Vite", "Mapbox GL", "3D Twin"]} />
            <div className="pitch-arch-conn" />
            <ArchNode label="API LAYER" color="var(--pg-green)" chips={["FastAPI", "120+ endpoints", "Claude AI"]} />
            <div className="pitch-arch-conn" />
            <ArchNode label="AI + SIMULATION" color="var(--pg-accent)" chips={["NREL SAM", "12 DL models", "GeoAI"]} />
            <div className="pitch-arch-conn" />
            <ArchNode label="DATA" color="var(--pg-purple)" chips={["Earth Engine", "PostGIS", "pgvector"]} />
          </div>
          {/* Simulation capabilities */}
          <div className="pitch-sim-strip">
            <div className="pitch-sim-strip-label">SIMULATIONS</div>
            <div className="pitch-sim-row"><span className="pitch-sim-dot" style={{ background: "#22d3ee" }} /><span className="pitch-sim-name">3D Digital Twin</span><span className="pitch-sim-detail">Sun path + shading</span></div>
            <div className="pitch-sim-row"><span className="pitch-sim-dot" style={{ background: "#f4b700" }} /><span className="pitch-sim-name">PvWattsv8</span><span className="pitch-sim-detail">Hourly energy yield</span></div>
            <div className="pitch-sim-row"><span className="pitch-sim-dot" style={{ background: "#a78bfa" }} /><span className="pitch-sim-name">Grid Flow</span><span className="pitch-sim-detail">Demand + curtailment</span></div>
            <div className="pitch-sim-row"><span className="pitch-sim-dot" style={{ background: "#34c759" }} /><span className="pitch-sim-name">Financial</span><span className="pitch-sim-detail">25-yr IRR + LCOE</span></div>
          </div>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 60%" }}>
          {/* 3D Digital Twin */}
          <div className="ps-twin-preview ps-twin-large">
            <div className="ps-twin-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
              <span>3D DIGITAL TWIN</span>
              <span className="ps-twin-live">LIVE</span>
            </div>
            <div className="ps-twin-body">
              <svg viewBox="0 0 480 280" className="ps-twin-svg">
                <defs>
                  <pattern id="isoGrid" width="24" height="14" patternUnits="userSpaceOnUse">
                    <path d="M0 14 L12 7 L24 14 M12 7 L12 0" fill="none" stroke="rgba(0,229,255,0.06)" strokeWidth="0.3" />
                  </pattern>
                  <filter id="glow"><feGaussianBlur stdDeviation="2" result="g" /><feMerge><feMergeNode in="g" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
                  <linearGradient id="panelFace" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#1a6b8a" /><stop offset="100%" stopColor="#0d3a4a" />
                  </linearGradient>
                  <linearGradient id="panelSide" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0a2a3a" /><stop offset="100%" stopColor="#061a25" />
                  </linearGradient>
                  <linearGradient id="battGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2a5a3a" /><stop offset="100%" stopColor="#1a3a2a" />
                  </linearGradient>
                </defs>

                <polygon points="240,240 480,160 240,80 0,160" fill="rgba(15,25,35,0.8)" stroke="rgba(0,229,255,0.1)" strokeWidth="0.5" />
                <rect x="0" y="80" width="480" height="160" fill="url(#isoGrid)" />

                {[0,1,2,3].map(i => (
                  <ellipse key={`c${i}`} cx="240" cy={160 + i * 8} rx={200 - i * 20} ry={30 - i * 3} fill="none" stroke="rgba(36,161,72,0.08)" strokeWidth="0.5" />
                ))}

                {[0,1,2].map(row => (
                  [0,1,2,3].map(col => {
                    const bx = 60 + col * 42 + row * 18;
                    const by = 130 + row * 22 - col * 10;
                    return (
                      <g key={`p${row}${col}`}>
                        <polygon points={`${bx},${by - 16} ${bx + 36},${by - 26} ${bx + 36},${by - 18} ${bx},${by - 8}`} fill="url(#panelFace)" stroke="#00bcd4" strokeWidth="0.6" opacity="0.9" />
                        <line x1={bx + 12} y1={by - 19.3} x2={bx + 12} y2={by - 11.3} stroke="rgba(0,229,255,0.2)" strokeWidth="0.3" />
                        <line x1={bx + 24} y1={by - 22.6} x2={bx + 24} y2={by - 14.6} stroke="rgba(0,229,255,0.2)" strokeWidth="0.3" />
                        <line x1={bx} y1={by - 12} x2={bx + 36} y2={by - 22} stroke="rgba(0,229,255,0.15)" strokeWidth="0.3" />
                        <line x1={bx + 18} y1={by - 12} x2={bx + 18} y2={by} stroke="#3a5a6a" strokeWidth="1" />
                      </g>
                    );
                  })
                ))}

                {[0,1].map(i => {
                  const ix = 260 + i * 30, iy = 165 + i * 14;
                  return (
                    <g key={`inv${i}`}>
                      <polygon points={`${ix},${iy} ${ix + 14},${iy - 6} ${ix + 14},${iy + 10} ${ix},${iy + 16}`} fill="#2a3a5a" stroke="#4a6a8a" strokeWidth="0.5" />
                      <polygon points={`${ix + 14},${iy - 6} ${ix + 22},${iy - 2} ${ix + 22},${iy + 14} ${ix + 14},${iy + 10}`} fill="#1a2a4a" stroke="#4a6a8a" strokeWidth="0.5" />
                      <polygon points={`${ix},${iy} ${ix + 14},${iy - 6} ${ix + 22},${iy - 2} ${ix + 8},${iy + 4}`} fill="#3a4a6a" stroke="#4a6a8a" strokeWidth="0.5" />
                      <circle cx={ix + 4} cy={iy + 5} r="1.5" fill="#24a148" filter="url(#glow)" />
                      <text x={ix + 11} y={iy + 24} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="4">INV</text>
                    </g>
                  );
                })}

                <g>
                  <polygon points="340,145 380,128 380,158 340,175" fill="url(#battGrad)" stroke="#24a148" strokeWidth="0.6" />
                  <polygon points="380,128 410,140 410,170 380,158" fill="#153020" stroke="#24a148" strokeWidth="0.6" />
                  <polygon points="340,145 380,128 410,140 370,157" fill="#1a4030" stroke="#24a148" strokeWidth="0.6" />
                  {[0,1,2,3].map(c => (
                    <rect key={`bc${c}`} x={345 + c * 8} y={152 + c * 0.5} width="5" height="12" rx="0.5" fill={c < 3 ? "#24a148" : "#1a3a2a"} opacity="0.7" transform={`skewY(-8)`} />
                  ))}
                  <circle cx="350" cy="150" r="2" fill="#24a148" filter="url(#glow)" />
                  <text x="375" y="182" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="5">BESS 5MWh</text>
                </g>

                <g>
                  <polygon points="400,155 430,142 455,154 425,167" fill="#2a2a1a" stroke="#f1c21b" strokeWidth="0.5" />
                  <polygon points="410,135 430,126 430,152 410,161" fill="#3a3a2a" stroke="#f1c21b" strokeWidth="0.5" />
                  <polygon points="430,126 445,133 445,159 430,152" fill="#2a2a1a" stroke="#f1c21b" strokeWidth="0.5" />
                  <polygon points="410,135 430,126 445,133 425,142" fill="#4a4a2a" stroke="#f1c21b" strokeWidth="0.5" />
                  <line x1="420" y1="135" x2="420" y2="120" stroke="#f1c21b" strokeWidth="1.5" />
                  <circle cx="420" cy="118" r="2.5" fill="none" stroke="#f1c21b" strokeWidth="0.8" />
                  <line x1="438" y1="130" x2="438" y2="118" stroke="#f1c21b" strokeWidth="1.5" />
                  <circle cx="438" cy="116" r="2.5" fill="none" stroke="#f1c21b" strokeWidth="0.8" />
                  <text x="428" y="174" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="5">33kV Tx</text>
                </g>

                <path d="M220,160 Q240,155 258,168" fill="none" stroke="#D4A018" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                <path d="M310,178 Q325,165 338,155" fill="none" stroke="#24a148" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                <path d="M395,160 L400,158" fill="none" stroke="#f1c21b" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                <path d="M450,135 L470,125 L470,90" fill="none" stroke="#f1c21b" strokeWidth="1" strokeDasharray="4,3" />
                <text x="470" y="86" textAnchor="middle" fill="#f1c21b" fontSize="5" fontWeight="700">GRID</text>

                <circle r="2" fill="#D4A018" filter="url(#glow)" opacity="0.9">
                  <animateMotion dur="3s" repeatCount="indefinite" path="M180,155 Q240,150 270,170 Q320,165 350,155 L420,140" />
                </circle>
                <circle r="1.5" fill="#24a148" filter="url(#glow)" opacity="0.8">
                  <animateMotion dur="4s" repeatCount="indefinite" begin="1s" path="M180,160 Q240,155 270,175 Q320,168 350,158 L420,143" />
                </circle>
                <circle r="1.5" fill="#f1c21b" filter="url(#glow)" opacity="0.7">
                  <animateMotion dur="2.5s" repeatCount="indefinite" begin="0.5s" path="M420,140 L450,130 L470,100" />
                </circle>

                <path d="M30,50 Q150,8 380,25 Q440,30 460,50" fill="none" stroke="rgba(241,194,27,0.2)" strokeWidth="0.8" strokeDasharray="4,3" />
                <circle cx="240" cy="18" r="12" fill="rgba(241,194,27,0.15)" />
                <circle cx="240" cy="18" r="7" fill="rgba(241,194,27,0.6)" filter="url(#glow)" />
                {[0,1,2,3,4,5].map(i => {
                  const angle = (i * 60) * Math.PI / 180;
                  return <line key={`ray${i}`} x1={240 + 10 * Math.cos(angle)} y1={18 + 10 * Math.sin(angle)} x2={240 + 16 * Math.cos(angle)} y2={18 + 16 * Math.sin(angle)} stroke="rgba(241,194,27,0.3)" strokeWidth="0.5" />;
                })}

                <g>
                  <rect x="5" y="5" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(0,229,255,0.3)" strokeWidth="0.5" />
                  <text x="12" y="16" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">OUTPUT</text>
                  <text x="12" y="28" fill="#D4A018" fontSize="10" fontWeight="800">4.8 MW</text>
                </g>
                <g>
                  <rect x="5" y="40" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(36,161,72,0.3)" strokeWidth="0.5" />
                  <text x="12" y="51" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">BESS SOC</text>
                  <text x="12" y="63" fill="#24a148" fontSize="10" fontWeight="800">78%</text>
                </g>
                <g>
                  <rect x="403" y="78" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(241,194,27,0.3)" strokeWidth="0.5" />
                  <text x="410" y="89" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">GRID EXPORT</text>
                  <text x="410" y="101" fill="#f1c21b" fontSize="10" fontWeight="800">3.2 MW</text>
                </g>

                <text x="130" y="210" textAnchor="middle" fill="rgba(0,229,255,0.5)" fontSize="5.5" fontWeight="600">SOLAR ARRAY</text>
                <text x="130" y="218" textAnchor="middle" fill="rgba(255,255,255,0.25)" fontSize="4">12 \u00D7 450W panels per string</text>

                <path d="M0,200 Q80,190 160,210 Q240,230 320,220 Q400,210 480,220" fill="none" stroke="rgba(120,120,100,0.2)" strokeWidth="4" />
                <path d="M0,200 Q80,190 160,210 Q240,230 320,220 Q400,210 480,220" fill="none" stroke="rgba(120,120,100,0.08)" strokeWidth="8" />

                <polygon points="30,200 240,100 460,190 240,250" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" strokeDasharray="6,4" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideTraction() {
  const metrics = [
    { label: "Assessment speed", value: "1000x", sub: "Full feasibility in 5 minutes vs. 4-8 weeks with traditional consultants", color: "var(--pg-green)" },
    { label: "Cost per site", value: "10-30x", sub: "~&pound;500 per assessment vs. &pound;5-15K consultancy — dramatically lowers the bar for site screening", color: "var(--pg-blue)" },
    { label: "Customer discovery", value: "100+", sub: "Interviews with UK developers, IPPs, asset managers, DNOs. Validated pain points, pricing, and workflow integration requirements.", color: "var(--pg-accent)" },
    { label: "Analysis intents", value: "18", sub: "Feasibility, grid study, grid connection, demand forecast, financial, planning, environmental, satellite, legacy, procurement, grid efficiency, prospecting, BESS +5 more", color: "var(--pg-purple)" },
    { label: "Pilot pipeline", value: "Active", sub: "Discussions with major UK data centre company. Early adopter program designed for 5 developers with active grid applications.", color: "var(--pg-green)" },
    { label: "Fused data sources", value: "20+", sub: "Google Earth Engine, NREL SAM, 6 UK DNO APIs, BMRS demand data, EA flood maps, Mapbox, planning APIs — all integrated", color: "var(--pg-blue)" },
    { label: "CV models deployed", value: "12", sub: "Prithvi EO, GroundedSAM, DINOv3, Moondream VLM, torchange, OmniCloudMask, OpenSR — production inference", color: "#ff6b6b" },
    { label: "Platform maturity", value: "120+", sub: "Production REST endpoints. Full-stack: PostGIS + FastAPI + React + Claude AI + PySAM + pandapower + deck.gl 3D twin", color: "var(--pg-accent)" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="13" title="TRACTION & METRICS" accent="var(--pg-green)" />
      <div className="pitch-metrics-grid">
        {metrics.map(m => (
          <div key={m.label} className="pitch-metric-card">
            <span className="pitch-metric-value" style={{ color: m.color }}>{m.value}</span>
            <span className="pitch-metric-label">{m.label}</span>
            <span className="pitch-metric-sub" dangerouslySetInnerHTML={{ __html: m.sub }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SlideBusiness() {
  const models = [
    { model: "Platform subscription", range: "&pound;50-60K ACV", desc: "Per-developer account with unlimited site assessments, portfolio dashboard, and AI chat. Each project slots underneath. Primary revenue driver.", primary: true },
    { model: "Volume-based fee", range: "5-10% of assessment value", desc: "Variable fee on advanced analyses — Tier 2 power flow, demand forecasts, connection cost estimates. Scales with usage, aligns with value delivered." },
    { model: "Enterprise API", range: "&pound;25-100K/yr", desc: "White-label integration for DNOs, grid operators, and large IPPs. Embed Princeps intelligence into their existing Salesforce/Oracle workflows." },
    { model: "Success fee", range: "0.5-2% of connection value", desc: "Upside on grid connections facilitated through the platform. Aligns incentives — we earn when sites get energised." },
  ];
  const unitEcon = [
    { label: "Gross margin", value: "85%+", color: "var(--pg-green)" },
    { label: "CAC target", value: "\u00a35-8K", color: "var(--pg-blue)" },
    { label: "LTV:CAC", value: ">10x", color: "var(--pg-accent)" },
    { label: "Payback", value: "<3 months", color: "var(--pg-purple)" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="14" title="BUSINESS MODEL" accent="var(--pg-blue)" badge="MARKET-AS-A-SERVICE" />
      <div className="pitch-cols" style={{ gap: 16 }}>
        <div className="pitch-col" style={{ flex: "0 0 55%" }}>
          <div className="pitch-business-grid">
            {models.map(m => (
              <div key={m.model} className={`pitch-business-card${m.primary ? " pitch-business-primary" : ""}`}>
                <span className="pitch-business-model">{m.model}</span>
                <span className="pitch-business-range" dangerouslySetInnerHTML={{ __html: m.range }} />
                <span className="pitch-business-desc">{m.desc}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="pitch-col" style={{ flex: 1 }}>
          <h3 className="pitch-section-head">UNIT ECONOMICS</h3>
          <div className="pitch-terrain-stats">
            {unitEcon.map(u => (
              <div key={u.label} className="pitch-terrain-stat">
                <span className="pitch-terrain-label">{u.label}</span>
                <span className="pitch-terrain-value" style={{ color: u.color }}>{u.value}</span>
              </div>
            ))}
          </div>
          <h3 className="pitch-section-head" style={{ marginTop: 14 }}>WHY THIS WORKS</h3>
          <div className="pitch-feature-list">
            <Feature icon=">" text="Replaces \u00a35-15K consultancy per site" detail="Developers currently pay external firms for each grid feasibility study. At \u00a3500-2K per AI assessment, adoption is a no-brainer." />
            <Feature icon=">" text="Power doubling in price from grid" detail="Co-location with renewables is now the cheapest form of new generation. Princeps helps developers find and validate these opportunities." />
            <Feature icon=">" text="Flexibility as revenue" detail="Behind-the-meter batteries, demand-side response, local renewable generation — all require the site intelligence that Princeps provides." />
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideTeam() {
  return (
    <div className="pitch-slide pitch-slide-hero">
      <div className="pitch-hero-glow" />
      <div className="pitch-hero-grid-bg" />
      <span className="pitch-hero-eyebrow">INVESTMENT OPPORTUNITY</span>
      <h1 className="pitch-hero-title" style={{ fontSize: 48 }}>THE ASK</h1>
      <p className="pitch-hero-sub" style={{ maxWidth: 560 }}>
        Building the intelligence layer for energy infrastructure. Seeking pre-seed investment to run an early adopter program with 5 UK developers, build the advisory board, and capture first-mover advantage.
      </p>
      <div className="pitch-team-cta">
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">RAISING</span>
          <span className="pitch-team-cta-value">Pre-seed</span>
        </div>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">USE OF FUNDS</span>
          <span className="pitch-team-cta-value">Engineering, early adopter pilots, data partnerships</span>
        </div>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">TIMELINE</span>
          <span className="pitch-team-cta-value">12 months to revenue</span>
        </div>
      </div>
      <div className="pitch-team-cta" style={{ marginTop: 16 }}>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">ADVISORY BOARD</span>
          <span className="pitch-team-cta-value" style={{ fontSize: 11 }}>Senior DNO engineering, offshore (Orsted, Enel), grid operator perspective</span>
        </div>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">ACCELERATORS</span>
          <span className="pitch-team-cta-value" style={{ fontSize: 11 }}>Free Electron, KIC (Horizon Europe)</span>
        </div>
      </div>
    </div>
  );
}

/* ── SHARED MICRO-COMPONENTS ── */

function SlideTitle({ num, title, accent, subtitle, badge }) {
  return (
    <div className="pitch-slide-title">
      {badge ? (
        <div className="pitch-badge-pill" style={{ borderColor: accent, color: accent }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2C6.48 2 2 6 2 10s10 12 10 12 10-8 10-12-4.48-8-10-8z"/></svg>
          {badge}
        </div>
      ) : (
        <span className="pitch-slide-num" style={{ color: accent }}>{num}</span>
      )}
      <h2 className="pitch-title-text">{title}</h2>
      {subtitle && <p className="pitch-title-subtitle">{subtitle}</p>}
    </div>
  );
}

function StatBox({ label, value, color }) {
  return (
    <div className="pitch-stat-box">
      <span className="pitch-stat-value" style={{ color }}>{value}</span>
      <span className="pitch-stat-label">{label}</span>
    </div>
  );
}

function PainPoint({ icon, text, detail }) {
  return (
    <div className="pitch-pain">
      <span className="pitch-pain-icon">{icon}</span>
      <div>
        <div className="pitch-pain-text">{text}</div>
        <div className="pitch-pain-detail">{detail}</div>
      </div>
    </div>
  );
}

function VerdictBadge({ verdict, color }) {
  return <div className="pitch-verdict-badge" style={{ borderColor: color, color }}>{verdict}</div>;
}

function FlowStep({ label, active }) {
  return <div className={`pitch-flow-step${active ? " active" : ""}`}>{label}</div>;
}

function FlowArrow() {
  return <span className="pitch-flow-arrow">&rarr;</span>;
}

function Feature({ icon, text, detail }) {
  return (
    <div className="pitch-feature">
      <span className="pitch-feature-icon">{icon}</span>
      <div>
        <div className="pitch-feature-text">{text}</div>
        <div className="pitch-feature-detail">{detail}</div>
      </div>
    </div>
  );
}

function LifecycleItem({ label, years }) {
  return (
    <div className="pitch-lifecycle-item">
      <span className="pitch-lifecycle-label">{label}</span>
      <span className="pitch-lifecycle-years">{years}</span>
    </div>
  );
}

function ArchNode({ label, color, chips }) {
  return (
    <div className="pitch-arch-node" style={{ borderColor: color }}>
      <span className="pitch-arch-node-label" style={{ color }}>{label}</span>
      <div className="pitch-arch-node-chips">
        {chips.map(c => <span key={c}>{c}</span>)}
      </div>
    </div>
  );
}
