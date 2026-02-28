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
  { id: "problem", label: "PROBLEM" },
  { id: "solution", label: "SOLUTION" },
  { id: "product", label: "PRODUCT" },
  { id: "engine", label: "AI ENGINE" },
  { id: "stack", label: "DATA & AI" },
  { id: "chat", label: "CHAT AI" },
  { id: "compliance", label: "COMPLIANCE" },
  { id: "gridprocess", label: "GRID" },
  { id: "financial", label: "FINANCIALS" },
  { id: "competitive", label: "LANDSCAPE" },
  { id: "architecture", label: "TECH ARCH" },
  { id: "traction", label: "TRACTION" },
  { id: "market", label: "MARKET" },
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
            {slide === 1 && <SlideProblem />}
            {slide === 2 && <SlideSolution />}
            {slide === 3 && <SlideProduct />}
            {slide === 4 && <SlideEngine />}
            {slide === 5 && <SlideStack />}
            {slide === 6 && <SlideChat />}
            {slide === 7 && <SlideCompliance />}
            {slide === 8 && <SlideGridProcess />}
            {slide === 9 && <SlideFinancial />}
            {slide === 10 && <SlideCompetitive />}
            {slide === 11 && <SlideArchitecture />}
            {slide === 12 && <SlideTraction />}
            {slide === 13 && <SlideMarket />}
            {slide === 14 && <SlideBusiness />}
            {slide === 15 && <SlideTeam />}
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
    { label: "CF", value: cf ? `${cf.toFixed(1)}%` : "--", color: "#00e5ff" },
    { label: "SCORE", value: score != null ? `${score}/120` : "--", color: "#00ff88" },
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
          <polygon points="160,100 340,90 350,230 170,240" fill="rgba(15,98,254,0.12)" stroke="#0f62fe" strokeWidth="1.5" strokeDasharray="4,2" />
          <line x1="345" y1="160" x2="400" y2="145" stroke="#f1c21b" strokeWidth="1" strokeDasharray="3,3" opacity="0.6" />
          <text x="250" y="175" textAnchor="middle" fill="#0f62fe" fontSize="9" fontWeight="700">5 MW SOLAR SITE</text>
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
        <span className="pf-kpi-value" style={{ color: "#0f62fe" }}>10.95%</span>
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

/** 9-domain radar using inline SVG */
function DomainRadar() {
  const domains = DEMO_AGENT_RESULT.domains;
  const keys = Object.keys(domains);
  const n = keys.length;
  const cx = 100, cy = 100, r = 80;

  const points = keys.map((k, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    const val = domains[k].score / 100;
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
      <polygon points={polyPoints} fill="rgba(15,98,254,0.15)" stroke="#0f62fe" strokeWidth="1.5" />
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
    grass: "#24a148", crops: "#f1c21b", built: "#da1e28", trees: "#0f62fe",
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
   SLIDE COMPONENTS (with live embeds)
   ══════════════════════════════════════════════════ */

function SlideHero() {
  return (
    <div className="pitch-slide pitch-slide-hero">
      <div className="pitch-hero-glow" />
      <div className="pitch-hero-grid-bg" />
      <span className="pitch-hero-eyebrow">THE INTELLIGENCE LAYER FOR RENEWABLE ENERGY</span>
      <h1 className="pitch-hero-title">PRINCEPS</h1>
      <p className="pitch-hero-sub">
        The first AI platform that fuses satellite imagery, grid topology, planning data and financial models into a single site feasibility verdict — replacing months of consultancy with a 5-minute automated assessment.
      </p>
      <div className="pitch-hero-tagline">Site intelligence. Automated. Institutional-grade.</div>
      <div className="pitch-hero-stats">
        <StatBox label="FASTER" value="1000x" color="var(--pg-green)" />
        <StatBox label="CHEAPER" value="10-30x" color="var(--pg-blue)" />
        <StatBox label="DATA SOURCES" value="20+" color="var(--pg-accent)" />
        <StatBox label="AI MODELS" value="12" color="var(--pg-purple)" />
      </div>
    </div>
  );
}

function SlideProblem() {
  return (
    <div className="pitch-slide">
      <SlideTitle num="02" title="THE PROBLEM" accent="var(--pg-red)" />
      <div className="pitch-cols">
        <div className="pitch-col">
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-accent)" }}>50 GW</span>
            <span className="pitch-big-label">UK Government target — solar + storage capacity by 2035. Requires assessing tens of thousands of candidate sites.</span>
          </div>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-red)" }}>4-8 weeks</span>
            <span className="pitch-big-label">Current timeline to assess a single site. Involves grid consultants, environmental surveys, planning reviews and financial modelling — all sequential.</span>
          </div>
          <div className="pitch-big-stat">
            <span className="pitch-big-num" style={{ color: "var(--pg-red)" }}>&pound;5-15K</span>
            <span className="pitch-big-label">Per-site consultancy cost before any planning application. Most developers assess 10-50 sites for every one that proceeds.</span>
          </div>
        </div>
        <div className="pitch-col">
          <div className="pitch-pain-list">
            <PainPoint icon="01" text="Manual site surveys" detail="Physical helicopter flyovers, weeks-long ground visits, Agricultural Land Classification soil surveys — all before any planning decision" />
            <PainPoint icon="02" text="Fragmented data" detail="Grid headroom data from DNOs, planning applications from local authorities, EA flood maps, Defra environmental designations — none integrated" />
            <PainPoint icon="03" text="Regulatory maze" detail="G99, CDM, BNG, EIA, NPPF, ALC \u2014 all manual" />
            <PainPoint icon="04" text="Blind bidding" detail="Developers bid on tenders without understanding how their portfolio sites match — no similarity search, no embedding-based ranking" />
            <PainPoint icon="05" text="No portfolio view" detail="Each site in isolation; no similarity search" />
          </div>
        </div>
      </div>
      <div className="pitch-callout pitch-callout-danger">
        Over 70% of assessed sites never proceed to planning. The UK energy sector wastes an estimated &pound;500M+ annually on failed due diligence — a problem that scales linearly with the 50 GW pipeline.
      </div>
    </div>
  );
}

function SlideSolution() {
  const replaces = [
    "Site survey consultants", "Grid connection consultants", "Planning consultants",
    "Environmental consultants", "Financial modelers", "Procurement advisors",
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="03" title="THE SOLUTION" accent="var(--pg-green)" />
      <div className="pitch-cols">
        <div className="pitch-col">
          <p className="pitch-lead">
            Princeps ingests <strong>20+ live data sources</strong> — satellite imagery, grid network topology, regulatory databases, terrain models, and financial benchmarks — then applies 12 deep learning models and NREL's PvWattsv8 engine to deliver a structured GO / CAUTION / NO-GO verdict with calibrated confidence scoring. One platform replaces an entire consultancy team.
          </p>
          <div className="pitch-verdict-row">
            <VerdictBadge verdict="GO" color="var(--pg-green)" />
            <VerdictBadge verdict="CAUTION" color="var(--pg-accent)" />
            <VerdictBadge verdict="NO-GO" color="var(--pg-red)" />
          </div>
          <div className="pitch-replaces">
            <span className="pitch-replaces-label">ONE PLATFORM REPLACES:</span>
            <div className="pitch-replaces-grid">
              {replaces.map(r => (
                <div key={r} className="pitch-replaces-item">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--pg-green)" strokeWidth="3"><path d="M20 6L9 17l-5-5"/></svg>
                  {r}
                </div>
              ))}
            </div>
          </div>
          <div className="pitch-flow-row">
            <FlowStep label="SITE" active /><FlowArrow />
            <FlowStep label="STUDY" /><FlowArrow />
            <FlowStep label="PLAN" /><FlowArrow />
            <FlowStep label="ACT" />
          </div>
        </div>
        <div className="pitch-col">
          <ProductFrame title="princeps.app \u2014 Verdict">
            <div className="pitch-live-component">
              <StaticVerdict />
            </div>
          </ProductFrame>
        </div>
      </div>
    </div>
  );
}

function SlideProduct() {
  const stages = [
    { stage: "1", title: "SITE", subtitle: "Discovery & Selection", color: "var(--pg-blue)",
      items: ["NOM Explorer \u2014 search 1,000+ UK substations by headroom, voltage, distance", "Interactive map \u2014 click, postcode, or coordinate search with real-time grid overlay", "Site Prospector \u2014 AI scores 25 candidates across 5 dimensions (resource, terrain, land use, grid, planning)", "Similarity search \u2014 NASA Prithvi EO 2.0 embeddings find sites with matching characteristics"] },
    { stage: "2", title: "STUDY", subtitle: "Deep Feasibility Analysis", color: "var(--pg-green)",
      items: ["9-domain AI engine with 11 analysis intents \u2014 each returns a structured verdict", "Claude AI synthesises GO / CAUTION / NO-GO with calibrated confidence (0-100%)", "Full-stack: DNO grid study, PvWatts yield, financial IRR, planning risk, environmental screening", "Satellite computer vision \u2014 12 DL models analyse land cover, terrain, shading, infrastructure"] },
    { stage: "3", title: "PLAN", subtitle: "Design & Layout", color: "var(--pg-accent)",
      items: ["70+ component catalogue \u2014 drag-and-drop panels, inverters, BESS, transformers onto site", "3D Digital Twin with real sun path simulation, inter-row shading analysis, terrain following", "Auto-generated BOM with live supplier stock levels and cost estimates", "BiPV rooftop designer for commercial and residential solar installations"] },
    { stage: "4", title: "ACT", subtitle: "Procure & Execute", color: "var(--pg-purple)",
      items: ["Procurement intelligence \u2014 live tender pipeline with AI bid viability scoring (0-100)", "Cost benchmarks by technology \u2014 solar, BESS, wind, EV charging with regional adjustments", "Tender-to-site matching \u2014 automatically ranks portfolio sites against each tender requirement", "Legacy asset lifecycle \u2014 repowering economics, decommissioning cost, compliance calendar"] },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="04" title="4-STAGE WORKFLOW" accent="var(--pg-blue)" />
      <div className="pitch-stages-grid">
        {stages.map(s => (
          <div key={s.stage} className="pitch-stage-card" style={{ borderTopColor: s.color }}>
            <div className="pitch-stage-num" style={{ color: s.color }}>{s.stage}</div>
            <div className="pitch-stage-title">{s.title}</div>
            <div className="pitch-stage-sub">{s.subtitle}</div>
            <ul className="pitch-stage-items">
              {s.items.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          </div>
        ))}
      </div>
      {/* Live product embed: static analytics strip */}
      <ProductFrame title="princeps.app \u2014 Live Metrics" className="pf-chrome-wide">
        <div className="pitch-live-component">
          <StaticAnalytics />
        </div>
      </ProductFrame>
    </div>
  );
}

function SlideEngine() {
  const domains = DEMO_AGENT_RESULT.domains;
  const domainList = [
    { key: "dno_infrastructure", name: "DNO Infrastructure", color: "var(--pg-blue)" },
    { key: "topography", name: "Topography", color: "var(--pg-green)" },
    { key: "solar_resource", name: "Solar Resource", color: "var(--pg-accent)" },
    { key: "agricultural_land", name: "Agricultural Land", color: "#e36209" },
    { key: "administrative", name: "Administrative", color: "var(--cds-text-secondary)" },
    { key: "neighbouring_projects", name: "Neighbouring Projects", color: "var(--pg-purple)" },
    { key: "flood_zones", name: "Flood Zones", color: "#1e90ff" },
    { key: "protected_areas", name: "Protected Areas", color: "#ff6b6b" },
    { key: "vision_ai", name: "Vision AI", color: "#00e5ff" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="05" title="9-DOMAIN AI ENGINE" accent="var(--pg-blue)" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 55%" }}>
          <div className="pitch-domains-grid pitch-domains-compact">
            {domainList.map((d, i) => {
              const data = domains[d.key];
              return (
                <div key={i} className="pitch-domain-card">
                  <div className="pitch-domain-header">
                    <span className="pitch-domain-num" style={{ color: d.color }}>{String(i + 1).padStart(2, "0")}</span>
                    <span className={`pitch-domain-status pitch-domain-${data.status.toLowerCase()}`}>{data.status}</span>
                  </div>
                  <div className="pitch-domain-name">{d.name}</div>
                  <div className="pitch-domain-score-bar">
                    <div className="pitch-domain-score-fill" style={{ width: `${data.score}%`, background: d.color }} />
                  </div>
                  <div className="pitch-domain-detail">{data.detail}</div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 40%", alignItems: "center", justifyContent: "center" }}>
          <ProductFrame title="princeps.app \u2014 Score">
            <div className="pitch-live-component">
              <ScoreCard />
            </div>
          </ProductFrame>
          <DomainRadar />
          <div style={{ textAlign: "center", marginTop: 4 }}>
            <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>LIVE 9-DOMAIN SCORE</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideStack() {
  const satSources = [
    { source: "DynamicWorld", res: "10m", what: "Land cover classification", color: "#00e5ff" },
    { source: "NASADEM", res: "30m", what: "Elevation & terrain", color: "#24a148" },
    { source: "ERA5-Land", res: "9km", what: "Solar GHI/DHI", color: "#f1c21b" },
    { source: "Sentinel-2", res: "10m", what: "NDVI & change detection", color: "#a56eff" },
    { source: "Sentinel-1 SAR", res: "10m", what: "Soil moisture", color: "#ff6b6b" },
    { source: "JRC Water", res: "30m", what: "Flood risk mapping", color: "#1e90ff" },
  ];
  const models = [
    { name: "Prithvi EO 2.0", org: "NASA/IBM", cap: "Site similarity embeddings", orgColor: "#00e5ff" },
    { name: "GroundedSAM", org: "Meta", cap: "Infrastructure detection", orgColor: "#ff6b6b" },
    { name: "DINOv3", org: "Meta", cap: "Terrain fingerprinting", orgColor: "#ff6b6b" },
    { name: "Moondream VLM", org: "vikhyatk", cap: "Natural language captions", orgColor: "#a56eff" },
    { name: "SAM", org: "Meta", cap: "Building extraction", orgColor: "#ff6b6b" },
    { name: "torchange", org: "open", cap: "Change detection", orgColor: "#24a148" },
    { name: "OmniCloudMask", org: "open", cap: "Cloud assessment", orgColor: "#24a148" },
    { name: "OpenSR", org: "ESA", cap: "4x super-resolution", orgColor: "#1e90ff" },
  ];
  const layers = [
    { label: "Satellite Imagery", color: "#00e5ff" },
    { label: "Terrain Analysis", color: "#f1c21b" },
    { label: "Grid Network", color: "#e36209" },
    { label: "Environmental", color: "#24a148" },
    { label: "Land Cover", color: "#a56eff" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="06" title="Multi-modal Data" subtitle="Satellite + Deep Learning + Energy Simulation" accent="var(--pg-purple)" badge="DATA & AI STACK" />
      <div className="ps-stack-layout">
        {/* Left — Satellite Sources */}
        <div className="ps-stack-col">
          <div className="ps-stack-col-header">
            <div className="ps-stack-icon" style={{ borderColor: "#00e5ff" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#00e5ff" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z"/></svg>
            </div>
            <div>
              <div className="ps-stack-col-title">Satellite Intelligence</div>
              <div className="ps-stack-col-sub">Google Earth Engine</div>
            </div>
          </div>
          <div className="ps-source-cards">
            {satSources.map(s => (
              <div key={s.source} className="ps-source-card">
                <div className="ps-source-top">
                  <span className="ps-source-dot" style={{ background: s.color }} />
                  <span className="ps-source-name">{s.source}</span>
                  <span className="ps-res-badge" style={{ borderColor: s.color, color: s.color }}>{s.res}</span>
                </div>
                <div className="ps-source-desc">{s.what}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Center — Satellite Imagery Preview */}
        <div className="ps-stack-center">
          <div className="ps-sat-preview">
            <div className="ps-sat-image">
              {SAT_IMG ? (
                <img src={SAT_IMG} alt="Satellite view — Bicester demo site" className="ps-sat-img" />
              ) : (
                <div className="ps-sat-fallback" />
              )}
              {/* Site boundary overlay */}
              <svg className="ps-sat-overlay" viewBox="0 0 600 450" preserveAspectRatio="xMidYMid slice">
                <polygon points="220,150 380,140 390,310 230,320" fill="rgba(15,98,254,0.12)" stroke="#0f62fe" strokeWidth="2" strokeDasharray="6,3" />
                <text x="305" y="240" textAnchor="middle" fill="#0f62fe" fontSize="11" fontWeight="700">5 MW SITE</text>
              </svg>
            </div>
            <div className="ps-sat-layers">
              {layers.map((l, i) => (
                <div key={l.label} className="ps-layer-row" style={{ borderColor: l.color, opacity: 1 - i * 0.12 }}>
                  <span className="ps-layer-dot" style={{ background: l.color }} />
                  <span className="ps-layer-label">{l.label}</span>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={l.color} strokeWidth="1.5" style={{ marginLeft: "auto" }}><path d="M12 2C6.48 2 2 6 2 10s10 12 10 12 10-8 10-12-4.48-8-10-8z"/></svg>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right — Deep Learning Models */}
        <div className="ps-stack-col">
          <div className="ps-stack-col-header">
            <div className="ps-stack-icon" style={{ borderColor: "#a56eff" }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a56eff" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
            </div>
            <div>
              <div className="ps-stack-col-title">Deep Learning</div>
              <div className="ps-stack-col-sub">12 specialized models</div>
            </div>
          </div>
          <div className="ps-source-cards">
            {models.slice(0, 6).map(m => (
              <div key={m.name} className="ps-source-card">
                <div className="ps-source-top">
                  <span className="ps-source-name">{m.name}</span>
                  <span className="ps-org-badge" style={{ borderColor: m.orgColor, color: m.orgColor }}>{m.org}</span>
                </div>
                <div className="ps-source-desc">{m.cap}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideChat() {
  return (
    <div className="pitch-slide">
      <SlideTitle num="07" title="CONVERSATIONAL AI" accent="var(--pg-blue)" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 55%" }}>
          <ProductFrame title="princeps.app \u2014 Chat">
            <MockChat />
          </ProductFrame>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 40%" }}>
          <h3 className="pitch-section-head">30+ CALLABLE TOOLS</h3>
          <div className="pitch-feature-list">
            <Feature icon=">" text="Natural language site analysis" detail="Ask complex questions: 'What's the grid connection cost for a 5MW site here?' — AI orchestrates the right tools automatically" />
            <Feature icon=">" text="Transparent tool execution" detail="Watch in real-time as the AI calls grid study, SAM simulation, planning search, and financial models — full auditability" />
            <Feature icon=">" text="Dynamic map layers" detail="AI generates GeoJSON layers on-the-fly — flood zones, grid networks, site boundaries rendered directly onto the map" />
            <Feature icon=">" text="Portfolio file upload" detail="Upload CSV/Excel with hundreds of site coordinates — bulk feasibility screening with parallel AI assessment" />
            <Feature icon=">" text="Server-sent event streaming" detail="Sub-second response streaming with intermediate tool results — no waiting for the full analysis to complete" />
          </div>
          <h3 className="pitch-section-head" style={{ marginTop: 12 }}>11 AGENT INTENTS</h3>
          <div className="pitch-intent-grid">
            {["feasibility", "grid_study", "financial", "planning", "environmental", "satellite", "legacy", "procurement", "grid_eff", "prospecting", "BESS"].map(i => (
              <span key={i} className="pitch-intent-chip">{i}</span>
            ))}
          </div>
          <ProductFrame title="princeps.app \u2014 Grid" className="pitch-grid-card-frame">
            <div className="pitch-live-component">
              <GridContextCard />
            </div>
          </ProductFrame>
        </div>
      </div>
    </div>
  );
}

function SlideCompliance() {
  const frameworks = [
    { code: "G99/G100", what: "Determines grid connection application route — G99 for >16A, G100 for type-tested inverters. Auto-selects based on site capacity." },
    { code: "CDM 2015", what: "Construction Design and Management — identifies Principal Designer obligations, pre-construction information requirements." },
    { code: "BNG", what: "Biodiversity Net Gain — calculates 10% mandatory uplift requirement, identifies offset opportunities and habitat creation costs." },
    { code: "EIA", what: "Environmental Impact Assessment screening — automatic threshold check (>5 MW), scoping opinion requirements." },
    { code: "NPPF", what: "National Planning Policy Framework alignment — checks paragraphs relevant to renewable energy and agricultural land protection." },
    { code: "ALC", what: "Agricultural Land Classification — flags BMV (Best and Most Versatile) Grade 1-3a land, triggers detailed soil survey requirement." },
    { code: "Flood Test", what: "EA Sequential and Exception Test — checks Flood Zone designation, surface water risk, JRC water occurrence data." },
    { code: "NSIP", what: "Nationally Significant Infrastructure Projects — >50 MW solar triggers DCO route via Planning Inspectorate." },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="08" title="UK REGULATORY COMPLIANCE" accent="var(--pg-accent)" />
      <div className="pitch-cols">
        <div className="pitch-col" style={{ flex: "0 0 55%" }}>
          <p className="pitch-lead">Princeps automatically screens every site against 8 UK regulatory frameworks, flagging compliance risks and generating the checklist of required applications — work that typically takes a planning consultant 2-3 weeks per site.</p>
          <div className="pitch-compliance-grid">
            {frameworks.map(f => (
              <div key={f.code} className="pitch-compliance-card">
                <span className="pitch-compliance-code">{f.code}</span>
                <span className="pitch-compliance-what">{f.what}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="pitch-col" style={{ flex: "0 0 40%" }}>
          <h3 className="pitch-section-head">ASSET LIFECYCLE TRACKING</h3>
          <div className="pitch-lifecycle-bar">
            <div className="pitch-lifecycle-items pitch-lifecycle-vertical">
              <LifecycleItem label="Solar Design Life" years="25 years" />
              <LifecycleItem label="BESS Design Life" years="15 years" />
              <LifecycleItem label="Degradation Model" years="0.5%/yr curve" />
              <LifecycleItem label="Compliance Calendar" years="Automated" />
              <LifecycleItem label="Decommissioning" years="Cost provisioned" />
            </div>
          </div>
          <ProductFrame title="princeps.app \u2014 Agent Verdict">
            <div className="pitch-live-component">
              <StaticVerdict />
            </div>
          </ProductFrame>
        </div>
      </div>
    </div>
  );
}

function SlideGridProcess() {
  /* Traditional steps positioned along a tangled cable path */
  const tradNodes = [
    { x: 30,  y: 60,  label: "Site ID",        time: "2-4wk" },
    { x: 80,  y: 120, label: "Desktop Study",   time: "2-3wk" },
    { x: 40,  y: 185, label: "DNO Pre-App",     time: "4-6wk" },
    { x: 110, y: 235, label: "G99 Filing",       time: "11-13wk" },
    { x: 55,  y: 295, label: "Feasibility",      time: "6-12wk" },
    { x: 105, y: 350, label: "Offer",            time: "4-8wk" },
    { x: 60,  y: 405, label: "Build",            time: "3-12mo" },
  ];
  /* Princeps steps positioned along a clean glowing cable */
  const fastNodes = [
    { x: 605, y: 75,  label: "AI Discovery",    time: "30s",  color: "#3b82f6" },
    { x: 605, y: 155, label: "Grid Analysis",   time: "2min", color: "#34c759" },
    { x: 605, y: 235, label: "9-Domain AI",     time: "5min", color: "#f4b700" },
    { x: 605, y: 315, label: "G99 Pack",        time: "10min",color: "#a78bfa" },
    { x: 605, y: 395, label: "Submit",           time: "1day", color: "#00e5ff" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="09" title="GRID CONNECTION PROCESS" accent="var(--pg-cyan)" badge="BEFORE & AFTER" />
      <div className="pitch-wire-graphic">
        <svg viewBox="0 0 750 470" className="pitch-wire-svg">
          <defs>
            {/* Glow filters */}
            <filter id="gCyan"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="gGold"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="gRed"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="gGreen"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            {/* Animated dash for energy flow */}
            <linearGradient id="cableGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00e5ff" stopOpacity="0.9"/>
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.7"/>
            </linearGradient>
          </defs>

          {/* ═══ LEFT: TANGLED CABLE MESS ═══ */}
          {/* Main tangled cable path — chaotic beziers */}
          <path d="M70,30 C120,35 30,80 70,60 S130,90 80,120 C30,150 110,160 40,185 S-10,210 110,235 C160,250 20,270 55,295 S140,320 105,350 C70,380 110,390 60,405 S40,430 80,445"
            fill="none" stroke="rgba(255,69,58,0.35)" strokeWidth="6" strokeLinecap="round"/>
          {/* Secondary tangled wires for visual noise */}
          <path d="M90,25 C140,50 10,70 95,95 S20,130 65,155 C110,170 15,200 85,220 S130,260 40,280 C-10,300 120,330 80,360"
            fill="none" stroke="rgba(255,69,58,0.15)" strokeWidth="3" strokeLinecap="round" strokeDasharray="8 6"/>
          <path d="M50,45 C-10,70 130,100 60,130 S-20,170 90,195 C140,210 30,245 100,270 S20,310 75,340 C120,365 40,390 70,420"
            fill="none" stroke="rgba(255,69,58,0.12)" strokeWidth="2.5" strokeLinecap="round"/>
          {/* Stray broken wires */}
          <path d="M25,100 C10,95 0,110 15,115" fill="none" stroke="rgba(255,69,58,0.2)" strokeWidth="2"/>
          <path d="M130,175 C145,170 150,185 140,192" fill="none" stroke="rgba(255,69,58,0.2)" strokeWidth="2"/>
          <path d="M20,260 C5,255 -5,270 10,278" fill="none" stroke="rgba(255,69,58,0.2)" strokeWidth="2"/>
          <path d="M135,310 C150,305 155,320 142,325" fill="none" stroke="rgba(255,69,58,0.2)" strokeWidth="1.5"/>
          {/* Small X marks for failures/delays */}
          {[[15,140],[125,205],[25,330],[115,380]].map(([cx,cy],i) => (
            <g key={`x${i}`} opacity="0.4">
              <line x1={cx-4} y1={cy-4} x2={cx+4} y2={cy+4} stroke="#ff453a" strokeWidth="1.5"/>
              <line x1={cx+4} y1={cy-4} x2={cx-4} y2={cy+4} stroke="#ff453a" strokeWidth="1.5"/>
            </g>
          ))}
          {/* Traditional step nodes */}
          {tradNodes.map((n, i) => (
            <g key={`t${i}`}>
              <circle cx={n.x} cy={n.y} r="12" fill="rgba(255,69,58,0.1)" stroke="#ff453a" strokeWidth="1.2" filter="url(#gRed)"/>
              <text x={n.x} y={n.y + 3.5} textAnchor="middle" fill="#ff453a" fontSize="8" fontWeight="800" fontFamily="monospace">{i + 1}</text>
              <text x={n.x + 18} y={n.y - 3} fill="rgba(255,255,255,0.75)" fontSize="8.5" fontWeight="600" fontFamily="Inter, sans-serif">{n.label}</text>
              <text x={n.x + 18} y={n.y + 8} fill="#ff453a" fontSize="7" fontWeight="700" fontFamily="monospace">{n.time}</text>
            </g>
          ))}
          {/* "6-18 MONTHS" header label */}
          <text x="75" y="18" textAnchor="middle" fill="#ff453a" fontSize="10" fontWeight="800" fontFamily="monospace" letterSpacing="1.5">6-18 MONTHS</text>
          {/* Unplugged socket icon at bottom-left */}
          <g transform="translate(60,440)">
            <rect x="-12" y="-6" width="24" height="12" rx="2" fill="none" stroke="rgba(255,69,58,0.4)" strokeWidth="1.5"/>
            <line x1="-4" y1="-3" x2="-4" y2="3" stroke="rgba(255,69,58,0.5)" strokeWidth="2" strokeLinecap="round"/>
            <line x1="4" y1="-3" x2="4" y2="3" stroke="rgba(255,69,58,0.5)" strokeWidth="2" strokeLinecap="round"/>
            <text x="0" y="22" textAnchor="middle" fill="rgba(255,69,58,0.5)" fontSize="7" fontFamily="monospace" fontWeight="700">DISCONNECTED</text>
          </g>

          {/* ═══ CENTER: PRINCEPS HUB ═══ */}
          {/* Hub glow aura */}
          <circle cx="340" cy="235" r="52" fill="rgba(244,183,0,0.04)" stroke="none">
            <animate attributeName="r" values="48;56;48" dur="3s" repeatCount="indefinite"/>
            <animate attributeName="opacity" values="0.5;1;0.5" dur="3s" repeatCount="indefinite"/>
          </circle>
          <circle cx="340" cy="235" r="40" fill="rgba(244,183,0,0.06)" stroke="rgba(244,183,0,0.15)" strokeWidth="1" filter="url(#gGold)"/>
          {/* Hub hexagon */}
          <polygon points="340,198 370,215 370,255 340,272 310,255 310,215" fill="rgba(10,14,26,0.9)" stroke="#f4b700" strokeWidth="1.5" filter="url(#gGold)"/>
          {/* Lightning bolt icon */}
          <path d="M336,218 L344,218 L340,232 L348,232 L334,252 L338,238 L332,238 Z" fill="#f4b700" opacity="0.9"/>
          {/* Hub label */}
          <text x="340" y="282" textAnchor="middle" fill="#f4b700" fontSize="9" fontWeight="800" fontFamily="monospace" letterSpacing="2">PRINCEPS AI</text>

          {/* Tangled cables entering hub (left side) */}
          <path d="M80,445 C120,440 200,400 280,320 S310,270 310,235" fill="none" stroke="rgba(255,69,58,0.2)" strokeWidth="4" strokeLinecap="round"/>
          <path d="M80,445 C130,430 220,380 290,310 S320,265 315,240" fill="none" stroke="rgba(255,69,58,0.1)" strokeWidth="2" strokeDasharray="6 4"/>

          {/* Clean cable exiting hub (right side) */}
          <path d="M370,235 C400,235 460,120 605,75" fill="none" stroke="url(#cableGrad)" strokeWidth="3" strokeLinecap="round" filter="url(#gCyan)" opacity="0.8"/>
          <path d="M370,235 C410,240 480,235 605,235" fill="none" stroke="url(#cableGrad)" strokeWidth="3" strokeLinecap="round" filter="url(#gCyan)" opacity="0.6"/>
          <path d="M370,245 C410,280 480,350 605,395" fill="none" stroke="url(#cableGrad)" strokeWidth="3" strokeLinecap="round" filter="url(#gCyan)" opacity="0.7"/>
          {/* Animated energy particles on clean cable */}
          <circle r="2.5" fill="#00e5ff" filter="url(#gCyan)">
            <animateMotion dur="2.5s" repeatCount="indefinite" path="M370,235 C400,235 460,120 605,75"/>
          </circle>
          <circle r="2" fill="#34c759" filter="url(#gGreen)">
            <animateMotion dur="3s" repeatCount="indefinite" path="M370,235 C410,240 480,235 605,235"/>
          </circle>
          <circle r="2.5" fill="#a78bfa">
            <animateMotion dur="2.8s" repeatCount="indefinite" path="M370,245 C410,280 480,350 605,395"/>
          </circle>

          {/* ═══ RIGHT: CLEAN PROCESS ═══ */}
          {/* "UNDER 1 DAY" header */}
          <text x="660" y="18" textAnchor="middle" fill="#34c759" fontSize="10" fontWeight="800" fontFamily="monospace" letterSpacing="1.5">UNDER 1 DAY</text>
          {/* Clean vertical cable backbone */}
          <line x1="605" y1="75" x2="605" y2="395" stroke="rgba(0,229,255,0.12)" strokeWidth="1.5"/>
          {/* Fast step nodes */}
          {fastNodes.map((n, i) => (
            <g key={`f${i}`}>
              <circle cx={n.x} cy={n.y} r="12" fill="rgba(0,229,255,0.06)" stroke={n.color} strokeWidth="1.5" filter="url(#gCyan)"/>
              <text x={n.x} y={n.y + 3.5} textAnchor="middle" fill={n.color} fontSize="8" fontWeight="800" fontFamily="monospace">{i + 1}</text>
              <text x={n.x + 18} y={n.y - 3} fill="rgba(255,255,255,0.85)" fontSize="8.5" fontWeight="600" fontFamily="Inter, sans-serif">{n.label}</text>
              <text x={n.x + 18} y={n.y + 8} fill={n.color} fontSize="7" fontWeight="700" fontFamily="monospace">{n.time}</text>
            </g>
          ))}
          {/* Connected plug icon at bottom-right */}
          <g transform="translate(605,440)">
            <rect x="-14" y="-7" width="28" height="14" rx="3" fill="rgba(52,199,89,0.12)" stroke="#34c759" strokeWidth="1.5" filter="url(#gGreen)"/>
            <line x1="-5" y1="-3" x2="-5" y2="3" stroke="#34c759" strokeWidth="2.5" strokeLinecap="round"/>
            <line x1="5" y1="-3" x2="5" y2="3" stroke="#34c759" strokeWidth="2.5" strokeLinecap="round"/>
            <text x="0" y="22" textAnchor="middle" fill="#34c759" fontSize="7" fontFamily="monospace" fontWeight="700">CONNECTED</text>
          </g>

          {/* ═══ BOTTOM STATS BAR ═══ */}
          {/* Divider line */}
          <line x1="160" y1="458" x2="590" y2="458" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5"/>
        </svg>

        {/* Stats overlay at bottom */}
        <div className="pitch-wire-stats">
          <div className="pitch-wire-stat">
            <span className="pitch-wire-stat-val" style={{ color: "#34c759" }}>97%</span>
            <span className="pitch-wire-stat-label">faster pre-application</span>
          </div>
          <div className="pitch-wire-stat">
            <span className="pitch-wire-stat-val" style={{ color: "#f4b700" }}>90%</span>
            <span className="pitch-wire-stat-label">cost reduction</span>
          </div>
          <div className="pitch-wire-stat">
            <span className="pitch-wire-stat-val" style={{ color: "#3b82f6" }}>10x</span>
            <span className="pitch-wire-stat-label">more sites screened</span>
          </div>
          <div className="pitch-wire-stat">
            <span className="pitch-wire-stat-val" style={{ color: "#ff453a" }}>739GW</span>
            <span className="pitch-wire-stat-label">UK grid queue backlog</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideFinancial() {
  const bessRevenue = [
    { stream: "FFR Dynamic", revenue: 65, display: "55-75K" },
    { stream: "Dynamic Containment", revenue: 42, display: "35-48K" },
    { stream: "Capacity Market", revenue: 12.5, display: "12.5K" },
    { stream: "Wholesale Arbitrage", revenue: 22, display: "18-25K" },
    { stream: "DNO Peak Shaving", revenue: 22, display: "22K" },
  ];
  const costs = [
    { tech: "Solar PV", range: "450-950", unit: "/kW" },
    { tech: "Battery", range: "300-700", unit: "/kW" },
    { tech: "Wind", range: "900-1,800", unit: "/kW" },
    { tech: "EV Charging", range: "800-2,000", unit: "/kW" },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="10" title="FINANCIAL MODEL" accent="var(--pg-green)" />
      <div className="pitch-cols">
        <div className="pitch-col">
          <h3 className="pitch-section-head">BESS REVENUE STACKING (&pound;/MW/yr)</h3>
          <div className="pitch-revenue-stack">
            {bessRevenue.map((r, i) => (
              <div key={i} className="pitch-revenue-bar">
                <span className="pitch-revenue-label">{r.stream}</span>
                <div className="pitch-revenue-fill" style={{ width: `${(r.revenue / 75) * 100}%` }} />
                <span className="pitch-revenue-value">&pound;{r.display}</span>
              </div>
            ))}
          </div>
          <div className="pitch-revenue-total">
            Total: <strong style={{ color: "var(--pg-green)" }}>&pound;142-183K</strong> per MW/yr
          </div>
        </div>
        <div className="pitch-col">
          <h3 className="pitch-section-head">SOLAR YIELD (LIVE DATA)</h3>
          <ProductFrame title="princeps.app \u2014 Solar Analysis">
            <div className="pitch-live-component">
              <SolarCard />
            </div>
          </ProductFrame>
          <h3 className="pitch-section-head" style={{ marginTop: 12 }}>COST BENCHMARKS (2024)</h3>
          <div className="pitch-cost-grid">
            {costs.map(c => (
              <div key={c.tech} className="pitch-cost-item">
                <span className="pitch-cost-tech">{c.tech}</span>
                <span className="pitch-cost-range">&pound;{c.range}<span className="pitch-cost-unit">{c.unit}</span></span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function SlideCompetitive() {
  const competitors = [
    { name: "RatedPower", sub: "by Enverus", focus: "Utility-scale PV design & layout automation", strength: "Automated engineering design, financial modelling, bankable reports", gap: "No AI reasoning, no satellite CV, no UK regulatory engine, no site discovery", color: "var(--pg-blue)" },
    { name: "PVcase Prospect", sub: "f. Anderson Optimization", focus: "GIS-based site prospecting & constraint mapping", strength: "Land parcel search near substations, slope analysis, buildable acreage", gap: "US-focused, no energy simulation, no AI verdicts, no computer vision", color: "var(--pg-purple)" },
    { name: "Terabase Energy", sub: "$130M Series C", focus: "Full-lifecycle solar platform + construction robotics", strength: "PlantPredict simulation, Design Pro, construction automation", gap: "No AI feasibility engine, no satellite analysis, no regulatory compliance", color: "var(--pg-cyan)" },
    { name: "Solargis Prospect", sub: "Irradiance leader", focus: "Solar resource data & pre-feasibility yield estimates", strength: "Best-in-class irradiance data, 30+ map layers, site comparison", gap: "Data only — no design, no AI, no grid analysis, no regulatory", color: "var(--pg-accent)" },
    { name: "Traditional Consultants", sub: "WSP, Stantec, etc.", focus: "Manual feasibility studies & environmental impact assessment", strength: "Deep domain expertise, regulatory relationships, bankable reports", gap: "4-8 weeks per site, \u00a35-15K cost, not scalable, no software platform", color: "var(--pg-red)" },
  ];
  const capabilities = [
    { cap: "AI feasibility verdict", us: true, rp: false, pv: false, tb: false, sg: false, tc: false },
    { cap: "Satellite computer vision", us: true, rp: false, pv: false, tb: false, sg: false, tc: false },
    { cap: "Energy simulation (SAM)", us: true, rp: true, pv: false, tb: true, sg: false, tc: false },
    { cap: "Site prospecting / discovery", us: true, rp: false, pv: true, tb: false, sg: false, tc: false },
    { cap: "Grid & DNO analysis", us: true, rp: false, pv: false, tb: false, sg: false, tc: true },
    { cap: "UK regulatory compliance", us: true, rp: false, pv: false, tb: false, sg: false, tc: false },
    { cap: "Conversational AI interface", us: true, rp: false, pv: false, tb: false, sg: false, tc: false },
    { cap: "3D Digital Twin", us: true, rp: true, pv: false, tb: true, sg: false, tc: false },
    { cap: "Earth Engine satellite data", us: true, rp: false, pv: false, tb: false, sg: true, tc: false },
    { cap: "5-min full assessment", us: true, rp: false, pv: false, tb: false, sg: false, tc: false },
  ];
  const Dot = ({ on }) => (
    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: on ? "var(--pg-green)" : "rgba(255,255,255,0.08)", border: on ? "none" : "1px solid rgba(255,255,255,0.12)" }} />
  );
  return (
    <div className="pitch-slide">
      <SlideTitle num="11" title="COMPETITIVE LANDSCAPE" accent="var(--pg-green)" badge="MARKET MAP" />
      <div className="pitch-cols" style={{ gap: 16 }}>
        {/* Left: Named competitor cards */}
        <div className="pitch-col" style={{ flex: "0 0 42%", gap: 6 }}>
          {competitors.map(c => (
            <div key={c.name} className="pitch-competitor-card">
              <div className="pitch-competitor-head">
                <span className="pitch-competitor-dot" style={{ background: c.color }} />
                <span className="pitch-competitor-name">{c.name}</span>
                <span className="pitch-competitor-sub">{c.sub}</span>
              </div>
              <div className="pitch-competitor-focus">{c.focus}</div>
              <div className="pitch-competitor-gap">{c.gap}</div>
            </div>
          ))}
        </div>
        {/* Right: Capability matrix */}
        <div className="pitch-col" style={{ flex: 1 }}>
          <div className="pitch-cap-matrix">
            <div className="pitch-cap-header">
              <span className="pitch-cap-label">CAPABILITY</span>
              <span className="pitch-cap-col" style={{ color: "var(--pg-green)" }}>US</span>
              <span className="pitch-cap-col">RP</span>
              <span className="pitch-cap-col">PV</span>
              <span className="pitch-cap-col">TB</span>
              <span className="pitch-cap-col">SG</span>
              <span className="pitch-cap-col">TC</span>
            </div>
            {capabilities.map(r => (
              <div key={r.cap} className="pitch-cap-row">
                <span className="pitch-cap-label">{r.cap}</span>
                <span className="pitch-cap-col"><Dot on={r.us} /></span>
                <span className="pitch-cap-col"><Dot on={r.rp} /></span>
                <span className="pitch-cap-col"><Dot on={r.pv} /></span>
                <span className="pitch-cap-col"><Dot on={r.tb} /></span>
                <span className="pitch-cap-col"><Dot on={r.sg} /></span>
                <span className="pitch-cap-col"><Dot on={r.tc} /></span>
              </div>
            ))}
            <div className="pitch-cap-legend">
              RP = RatedPower &middot; PV = PVcase &middot; TB = Terabase &middot; SG = Solargis &middot; TC = Trad. Consultants
            </div>
          </div>
        </div>
      </div>
      <div className="pitch-callout pitch-callout-accent" style={{ marginTop: 8 }}>
        <strong>Only Princeps</strong> fuses NREL energy simulation, Earth Engine satellite intelligence, 12 GeoAI computer vision models, and Claude AI reasoning into one platform — purpose-built for UK regulatory requirements. No competitor covers all four layers.
      </div>
    </div>
  );
}

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
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00e5ff" strokeWidth="1.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
              <span>3D DIGITAL TWIN</span>
              <span className="ps-twin-live">LIVE</span>
            </div>
            <div className="ps-twin-body">
              <svg viewBox="0 0 480 280" className="ps-twin-svg">
                <defs>
                  {/* Isometric grid pattern */}
                  <pattern id="isoGrid" width="24" height="14" patternUnits="userSpaceOnUse">
                    <path d="M0 14 L12 7 L24 14 M12 7 L12 0" fill="none" stroke="rgba(0,229,255,0.06)" strokeWidth="0.3" />
                  </pattern>
                  {/* Energy flow animation */}
                  <filter id="glow"><feGaussianBlur stdDeviation="2" result="g" /><feMerge><feMergeNode in="g" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
                  {/* Panel gradient */}
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

                {/* Ground plane */}
                <polygon points="240,240 480,160 240,80 0,160" fill="rgba(15,25,35,0.8)" stroke="rgba(0,229,255,0.1)" strokeWidth="0.5" />
                <rect x="0" y="80" width="480" height="160" fill="url(#isoGrid)" />

                {/* Ground contour lines */}
                {[0,1,2,3].map(i => (
                  <ellipse key={`c${i}`} cx="240" cy={160 + i * 8} rx={200 - i * 20} ry={30 - i * 3} fill="none" stroke="rgba(36,161,72,0.08)" strokeWidth="0.5" />
                ))}

                {/* === SOLAR ARRAY (3 rows x 4 panels) === */}
                {[0,1,2].map(row => (
                  [0,1,2,3].map(col => {
                    const bx = 60 + col * 42 + row * 18;
                    const by = 130 + row * 22 - col * 10;
                    return (
                      <g key={`p${row}${col}`}>
                        {/* Panel face (tilted) */}
                        <polygon points={`${bx},${by - 16} ${bx + 36},${by - 26} ${bx + 36},${by - 18} ${bx},${by - 8}`} fill="url(#panelFace)" stroke="#00bcd4" strokeWidth="0.6" opacity="0.9" />
                        {/* Panel cell grid lines */}
                        <line x1={bx + 12} y1={by - 19.3} x2={bx + 12} y2={by - 11.3} stroke="rgba(0,229,255,0.2)" strokeWidth="0.3" />
                        <line x1={bx + 24} y1={by - 22.6} x2={bx + 24} y2={by - 14.6} stroke="rgba(0,229,255,0.2)" strokeWidth="0.3" />
                        <line x1={bx} y1={by - 12} x2={bx + 36} y2={by - 22} stroke="rgba(0,229,255,0.15)" strokeWidth="0.3" />
                        {/* Support post */}
                        <line x1={bx + 18} y1={by - 12} x2={bx + 18} y2={by} stroke="#3a5a6a" strokeWidth="1" />
                      </g>
                    );
                  })
                ))}

                {/* === INVERTER CABINETS (2x) === */}
                {[0,1].map(i => {
                  const ix = 260 + i * 30, iy = 165 + i * 14;
                  return (
                    <g key={`inv${i}`}>
                      <polygon points={`${ix},${iy} ${ix + 14},${iy - 6} ${ix + 14},${iy + 10} ${ix},${iy + 16}`} fill="#2a3a5a" stroke="#4a6a8a" strokeWidth="0.5" />
                      <polygon points={`${ix + 14},${iy - 6} ${ix + 22},${iy - 2} ${ix + 22},${iy + 14} ${ix + 14},${iy + 10}`} fill="#1a2a4a" stroke="#4a6a8a" strokeWidth="0.5" />
                      <polygon points={`${ix},${iy} ${ix + 14},${iy - 6} ${ix + 22},${iy - 2} ${ix + 8},${iy + 4}`} fill="#3a4a6a" stroke="#4a6a8a" strokeWidth="0.5" />
                      {/* Status LED */}
                      <circle cx={ix + 4} cy={iy + 5} r="1.5" fill="#24a148" filter="url(#glow)" />
                      <text x={ix + 11} y={iy + 24} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="4">INV</text>
                    </g>
                  );
                })}

                {/* === BATTERY STORAGE (BESS container) === */}
                <g>
                  <polygon points="340,145 380,128 380,158 340,175" fill="url(#battGrad)" stroke="#24a148" strokeWidth="0.6" />
                  <polygon points="380,128 410,140 410,170 380,158" fill="#153020" stroke="#24a148" strokeWidth="0.6" />
                  <polygon points="340,145 380,128 410,140 370,157" fill="#1a4030" stroke="#24a148" strokeWidth="0.6" />
                  {/* Battery cells inside */}
                  {[0,1,2,3].map(c => (
                    <rect key={`bc${c}`} x={345 + c * 8} y={152 + c * 0.5} width="5" height="12" rx="0.5" fill={c < 3 ? "#24a148" : "#1a3a2a"} opacity="0.7" transform={`skewY(-8)`} />
                  ))}
                  {/* Charge indicator */}
                  <circle cx="350" cy="150" r="2" fill="#24a148" filter="url(#glow)" />
                  <text x="375" y="182" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="5">BESS 5MWh</text>
                </g>

                {/* === SUBSTATION / TRANSFORMER === */}
                <g>
                  {/* Base */}
                  <polygon points="400,155 430,142 455,154 425,167" fill="#2a2a1a" stroke="#f1c21b" strokeWidth="0.5" />
                  {/* Transformer body */}
                  <polygon points="410,135 430,126 430,152 410,161" fill="#3a3a2a" stroke="#f1c21b" strokeWidth="0.5" />
                  <polygon points="430,126 445,133 445,159 430,152" fill="#2a2a1a" stroke="#f1c21b" strokeWidth="0.5" />
                  <polygon points="410,135 430,126 445,133 425,142" fill="#4a4a2a" stroke="#f1c21b" strokeWidth="0.5" />
                  {/* HV bushings */}
                  <line x1="420" y1="135" x2="420" y2="120" stroke="#f1c21b" strokeWidth="1.5" />
                  <circle cx="420" cy="118" r="2.5" fill="none" stroke="#f1c21b" strokeWidth="0.8" />
                  <line x1="438" y1="130" x2="438" y2="118" stroke="#f1c21b" strokeWidth="1.5" />
                  <circle cx="438" cy="116" r="2.5" fill="none" stroke="#f1c21b" strokeWidth="0.8" />
                  <text x="428" y="174" textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="5">33kV Tx</text>
                </g>

                {/* === POWER LINES / CABLES === */}
                {/* Panels → Inverters */}
                <path d="M220,160 Q240,155 258,168" fill="none" stroke="#00e5ff" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                {/* Inverters → BESS */}
                <path d="M310,178 Q325,165 338,155" fill="none" stroke="#24a148" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                {/* BESS → Substation */}
                <path d="M395,160 L400,158" fill="none" stroke="#f1c21b" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.5" />
                {/* Grid export line */}
                <path d="M450,135 L470,125 L470,90" fill="none" stroke="#f1c21b" strokeWidth="1" strokeDasharray="4,3" />
                <text x="470" y="86" textAnchor="middle" fill="#f1c21b" fontSize="5" fontWeight="700">GRID</text>

                {/* === ENERGY FLOW PARTICLES === */}
                <circle r="2" fill="#00e5ff" filter="url(#glow)" opacity="0.9">
                  <animateMotion dur="3s" repeatCount="indefinite" path="M180,155 Q240,150 270,170 Q320,165 350,155 L420,140" />
                </circle>
                <circle r="1.5" fill="#24a148" filter="url(#glow)" opacity="0.8">
                  <animateMotion dur="4s" repeatCount="indefinite" begin="1s" path="M180,160 Q240,155 270,175 Q320,168 350,158 L420,143" />
                </circle>
                <circle r="1.5" fill="#f1c21b" filter="url(#glow)" opacity="0.7">
                  <animateMotion dur="2.5s" repeatCount="indefinite" begin="0.5s" path="M420,140 L450,130 L470,100" />
                </circle>

                {/* === SUN + PATH === */}
                <path d="M30,50 Q150,8 380,25 Q440,30 460,50" fill="none" stroke="rgba(241,194,27,0.2)" strokeWidth="0.8" strokeDasharray="4,3" />
                <circle cx="240" cy="18" r="12" fill="rgba(241,194,27,0.15)" />
                <circle cx="240" cy="18" r="7" fill="rgba(241,194,27,0.6)" filter="url(#glow)" />
                {/* Sun rays */}
                {[0,1,2,3,4,5].map(i => {
                  const angle = (i * 60) * Math.PI / 180;
                  return <line key={`ray${i}`} x1={240 + 10 * Math.cos(angle)} y1={18 + 10 * Math.sin(angle)} x2={240 + 16 * Math.cos(angle)} y2={18 + 16 * Math.sin(angle)} stroke="rgba(241,194,27,0.3)" strokeWidth="0.5" />;
                })}

                {/* === FLOATING KPI BADGES === */}
                {/* Power output */}
                <g>
                  <rect x="5" y="5" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(0,229,255,0.3)" strokeWidth="0.5" />
                  <text x="12" y="16" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">OUTPUT</text>
                  <text x="12" y="28" fill="#00e5ff" fontSize="10" fontWeight="800">4.8 MW</text>
                </g>
                {/* Storage */}
                <g>
                  <rect x="5" y="40" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(36,161,72,0.3)" strokeWidth="0.5" />
                  <text x="12" y="51" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">BESS SOC</text>
                  <text x="12" y="63" fill="#24a148" fontSize="10" fontWeight="800">78%</text>
                </g>
                {/* Grid export */}
                <g>
                  <rect x="403" y="78" width="72" height="30" rx="5" fill="rgba(10,15,30,0.85)" stroke="rgba(241,194,27,0.3)" strokeWidth="0.5" />
                  <text x="410" y="89" fill="rgba(255,255,255,0.5)" fontSize="5" fontWeight="600">GRID EXPORT</text>
                  <text x="410" y="101" fill="#f1c21b" fontSize="10" fontWeight="800">3.2 MW</text>
                </g>

                {/* === COMPONENT LABELS === */}
                <text x="130" y="210" textAnchor="middle" fill="rgba(0,229,255,0.5)" fontSize="5.5" fontWeight="600">SOLAR ARRAY</text>
                <text x="130" y="218" textAnchor="middle" fill="rgba(255,255,255,0.25)" fontSize="4">12 \u00D7 450W panels per string</text>

                {/* Access road */}
                <path d="M0,200 Q80,190 160,210 Q240,230 320,220 Q400,210 480,220" fill="none" stroke="rgba(120,120,100,0.2)" strokeWidth="4" />
                <path d="M0,200 Q80,190 160,210 Q240,230 320,220 Q400,210 480,220" fill="none" stroke="rgba(120,120,100,0.08)" strokeWidth="8" />

                {/* Fence perimeter */}
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
    { label: "API surface", value: "120+", sub: "Production-ready REST endpoints covering sites, grid, planning, finance, satellite, and procurement", color: "var(--pg-accent)" },
    { label: "Analysis intents", value: "11", sub: "Specialised AI assessments: feasibility, grid, financial, planning, environmental, satellite, legacy, procurement, grid efficiency, prospecting, BESS", color: "var(--pg-purple)" },
    { label: "Chat tools", value: "30+", sub: "Claude AI orchestrates 30+ callable tools — grid study, SAM simulation, GeoJSON generation, planning search, financial modelling", color: "var(--pg-blue)" },
    { label: "Fused data sources", value: "20+", sub: "Google Earth Engine, NREL SAM, OS data, EA flood maps, BEIS grid data, Mapbox, planning APIs — all integrated", color: "var(--pg-green)" },
    { label: "CV models deployed", value: "12", sub: "Prithvi EO, GroundedSAM, DINOv3, Moondream VLM, torchange, OmniCloudMask, OpenSR — production inference", color: "#ff6b6b" },
    { label: "Regulatory checks", value: "8", sub: "G99/G100, CDM, BNG, EIA, NPPF, ALC, Flood Test, NSIP — automated compliance screening", color: "var(--pg-accent)" },
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

function SlideMarket() {
  return (
    <div className="pitch-slide">
      <SlideTitle num="14" title="MARKET SIZE" accent="var(--pg-accent)" />
      <div className="pitch-market-stack">
        <div className="pitch-market-ring pitch-market-tam">
          <div className="pitch-market-inner">
            <span className="pitch-market-value">&pound;2B+</span>
            <span className="pitch-market-label">TAM</span>
            <span className="pitch-market-desc">UK energy infrastructure consultancy, planning, and due diligence services</span>
          </div>
        </div>
        <div className="pitch-market-ring pitch-market-sam-ring">
          <div className="pitch-market-inner">
            <span className="pitch-market-value">&pound;500M</span>
            <span className="pitch-market-label">SAM</span>
            <span className="pitch-market-desc">Solar, BESS, and wind site feasibility assessments and grid connection studies</span>
          </div>
        </div>
        <div className="pitch-market-ring pitch-market-som">
          <div className="pitch-market-inner">
            <span className="pitch-market-value">&pound;50M</span>
            <span className="pitch-market-label">SOM</span>
            <span className="pitch-market-desc">UK solar developers, IPPs, and asset managers actively assessing sites today</span>
          </div>
        </div>
      </div>
      <div className="pitch-market-pipeline">
        <div className="pitch-market-pipe-item">
          <span className="pitch-market-pipe-val" style={{ color: "var(--pg-accent)" }}>50+ GW</span>
          <span>UK solar pipeline by 2035</span>
        </div>
        <div className="pitch-market-pipe-item">
          <span className="pitch-market-pipe-val" style={{ color: "var(--pg-blue)" }}>25+ GW</span>
          <span>Battery storage planned</span>
        </div>
        <div className="pitch-market-pipe-item">
          <span className="pitch-market-pipe-val" style={{ color: "var(--pg-green)" }}>10,000s</span>
          <span>Sites to assess per year</span>
        </div>
      </div>
    </div>
  );
}

function SlideBusiness() {
  const models = [
    { model: "Per-site fee", range: "&pound;500-2,000/site", desc: "Pay-per-assessment — instant feasibility reports replace &pound;5-15K consultancy. 10-30x cost reduction drives adoption." },
    { model: "SaaS subscription", range: "&pound;2-5K/mo per seat", desc: "Monthly subscription for unlimited assessments, portfolio management, and real-time monitoring. Land-and-expand within organisations." },
    { model: "Enterprise API", range: "&pound;25-100K/yr", desc: "Volume licensing for large developers and DNOs managing 100+ site portfolios. White-label integration into existing workflows." },
    { model: "Revenue share", range: "0.5-2% of connection value", desc: "Success-based upside on grid connections facilitated through the platform. Aligns incentives — we earn when sites succeed." },
  ];
  return (
    <div className="pitch-slide">
      <SlideTitle num="15" title="BUSINESS MODEL" accent="var(--pg-blue)" />
      <div className="pitch-business-grid">
        {models.map(m => (
          <div key={m.model} className="pitch-business-card">
            <span className="pitch-business-model">{m.model}</span>
            <span className="pitch-business-range" dangerouslySetInnerHTML={{ __html: m.range }} />
            <span className="pitch-business-desc">{m.desc}</span>
          </div>
        ))}
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
        Building the intelligence layer for the UK's energy transition. We are seeking pre-seed investment to scale the platform, build the team, and capture the first-mover advantage in AI-powered site feasibility.
      </p>
      <div className="pitch-team-cta">
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">RAISING</span>
          <span className="pitch-team-cta-value">Pre-seed</span>
        </div>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">USE OF FUNDS</span>
          <span className="pitch-team-cta-value">Engineering, data partnerships, first enterprise pilots</span>
        </div>
        <div className="pitch-team-cta-item">
          <span className="pitch-team-cta-label">TIMELINE</span>
          <span className="pitch-team-cta-value">12 months to revenue</span>
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
