import React, { useState, useEffect, useRef, useCallback } from "react";

/* ── Animated counter hook ──────────────────────────────────── */
function useAnimatedValue(target, duration = 800) {
  const [display, setDisplay] = useState(0);
  const rafRef = useRef(null);
  const startRef = useRef(null);
  const fromRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = typeof target === "number" ? target : parseFloat(target) || 0;
    startRef.current = performance.now();

    const tick = (now) => {
      const elapsed = now - startRef.current;
      const t = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const val = from + (to - from) * eased;
      setDisplay(val);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);

  return display;
}

/* ── Interactive sparkline ──────────────────────────────────── */
function Sparkline({ data, width = 88, height = 24, color = "var(--gold)" }) {
  const [hoverIdx, setHoverIdx] = useState(null);
  const points = (data || Array.from({ length: 10 }, () => Math.random())).map(
    (v, i, arr) => ({
      x: (i / (arr.length - 1)) * (width - 8) + 4,
      y: 3 + (1 - v) * (height - 6),
    })
  );
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  const areaPath = `${linePath} L${points[points.length - 1].x},${height} L${points[0].x},${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block", marginTop: 6, cursor: "crosshair" }}
      onMouseLeave={() => setHoverIdx(null)}
    >
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#spark-fill)" />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={hoverIdx === i ? 3 : 1.5}
          fill={hoverIdx === i ? "#fff" : color}
          stroke={hoverIdx === i ? color : "none"}
          strokeWidth={hoverIdx === i ? 2 : 0}
          style={{ transition: "r 0.15s, fill 0.15s" }}
          onMouseEnter={() => setHoverIdx(i)}
        />
      ))}
    </svg>
  );
}

/* ── Metric card ────────────────────────────────────────────── */
function MetricCard({ label, value, unit, delta, deltaPositive, icon, delay = 0 }) {
  const animVal = useAnimatedValue(typeof value === "number" ? value : parseFloat(value) || 0);
  const isFloat = String(value).includes(".");
  const displayVal = isFloat ? animVal.toFixed(1) : Math.round(animVal);

  return (
    <div
      className="pd3-enter-1"
      style={{
        flex: 1,
        minWidth: 0,
        padding: "4px 0",
        animationDelay: `${delay}ms`,
      }}
    >
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: 8,
      }}>
        {icon && (
          <div style={{
            width: 24,
            height: 24,
            borderRadius: 6,
            background: "rgba(245,183,49,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            {icon}
          </div>
        )}
        <span style={{
          fontSize: 10,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--muted)",
        }}>
          {label}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 2 }}>
        <span
          className="pd3-metric-value"
          style={{ fontSize: 38, color: "var(--ink)" }}
        >
          {displayVal}
        </span>
        <span style={{
          fontSize: 16,
          fontWeight: 500,
          color: "var(--muted-light)",
          fontFamily: "var(--mono), monospace",
        }}>
          {unit}
        </span>
      </div>

      <Sparkline />

      {delta && (
        <div
          className={`pd3-delta ${deltaPositive ? "pd3-delta-up" : "pd3-delta-down"}`}
          style={{ marginTop: 8 }}
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d={deltaPositive ? "M5 2L8 6H2L5 2Z" : "M5 8L2 4H8L5 8Z"}
              fill="currentColor"
            />
          </svg>
          {delta}
        </div>
      )}
    </div>
  );
}

/* ── Health dial with animated ring ─────────────────────────── */
function HealthDial({ avgScore, goCount, cautionCount, nogoCount }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { requestAnimationFrame(() => setMounted(true)); }, []);

  const pct = Math.min(avgScore, 100) / 100;
  const r = 54;
  const circ = 2 * Math.PI * r;
  const offset = mounted ? circ * (1 - pct) : circ;
  const ringColor = avgScore >= 65 ? "#16a34a" : avgScore >= 40 ? "var(--gold)" : "#dc2626";
  const glowColor = avgScore >= 65
    ? "rgba(22,163,74,0.2)"
    : avgScore >= 40
      ? "rgba(245,183,49,0.2)"
      : "rgba(220,38,38,0.2)";

  const animScore = useAnimatedValue(avgScore, 1200);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <div style={{ position: "relative" }}>
        <svg width="130" height="130" viewBox="0 0 130 130">
          {/* Track */}
          <circle
            cx="65" cy="65" r={r}
            fill="none"
            stroke="var(--cds-layer-03, #EBEDF0)"
            strokeWidth="8"
          />
          {/* Glow behind ring */}
          <circle
            cx="65" cy="65" r={r}
            fill="none"
            stroke={glowColor}
            strokeWidth="14"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 65 65)"
            style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)", filter: "blur(6px)" }}
          />
          {/* Main ring */}
          <circle
            cx="65" cy="65" r={r}
            fill="none"
            stroke={ringColor}
            strokeWidth="8"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 65 65)"
            style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)" }}
          />
          {/* Score */}
          <text
            x="65" y="60"
            textAnchor="middle"
            fill="var(--ink)"
            fontSize="30"
            fontWeight="800"
            fontFamily="var(--mono), monospace"
          >
            {Math.round(animScore)}
          </text>
          <text
            x="65" y="78"
            textAnchor="middle"
            fill="var(--muted)"
            fontSize="9"
            fontWeight="600"
            letterSpacing="0.06em"
          >
            PORTFOLIO
          </text>
        </svg>
      </div>

      {/* Verdict pills */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
        <span className="pd3-verdict pd3-verdict-go">{goCount} GO</span>
        <span className="pd3-verdict pd3-verdict-caution">{cautionCount} CAUTION</span>
        {nogoCount > 0 && (
          <span className="pd3-verdict pd3-verdict-nogo">{nogoCount} NO-GO</span>
        )}
      </div>

      {/* Top issue — compact */}
      <div style={{
        width: "100%",
        borderLeft: "3px solid #dc2626",
        background: "rgba(220,38,38,0.04)",
        borderRadius: 8,
        padding: "8px 12px",
      }}>
        <div style={{
          fontSize: 9,
          fontWeight: 700,
          color: "#dc2626",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 2,
        }}>
          Top Issue
        </div>
        <div style={{ fontSize: 11, color: "var(--ink)", lineHeight: 1.4 }}>
          Slough DC — grid offer expires 15 Apr
        </div>
      </div>
    </div>
  );
}

/* ── Insight bar ────────────────────────────────────────────── */
function InsightBar({ text }) {
  return (
    <div style={{
      position: "relative",
      marginTop: 20,
      background: "rgba(245,183,49,0.04)",
      borderLeft: "3px solid var(--gold)",
      borderRadius: 8,
      padding: "10px 16px",
      fontSize: 12,
      color: "var(--ink)",
      lineHeight: 1.5,
      overflow: "hidden",
    }}>
      <div className="pd3-scan-line" />
      <span style={{
        fontSize: 9,
        fontWeight: 700,
        color: "var(--gold-dark)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        marginRight: 8,
      }}>
        AI Insight
      </span>
      {text}
    </div>
  );
}

/* ── Main component ─────────────────────────────────────────── */
export default function PortfolioHero({
  totalMw, annualGwh, irr, avgScore,
  goCount, cautionCount, nogoCount, projectCount,
}) {
  return (
    <div
      className="pd3-hero-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 280px",
        gap: 16,
        padding: "0 24px",
        marginBottom: 16,
      }}
    >
      {/* LEFT — Portfolio performance */}
      <div className="pd3-card pd3-enter-1" style={{ padding: 24 }}>
        <div className="pd3-metrics-row" style={{ display: "flex", gap: 28 }}>
          <MetricCard
            label="IT Load"
            value={totalMw}
            unit="MW"
            delta="+12% vs quarter"
            deltaPositive
            delay={50}
            icon={
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <rect x="2" y="3" width="8" height="6" rx="1" stroke="var(--gold)" strokeWidth="1.2" />
                <path d="M4 6h4M6 9v1.5" stroke="var(--gold)" strokeWidth="1" strokeLinecap="round" />
              </svg>
            }
          />
          <div style={{ width: 1, background: "var(--border)", margin: "8px 0", flexShrink: 0 }} />
          <MetricCard
            label="Grid Headroom"
            value={annualGwh}
            unit="MVA"
            delta="across portfolio"
            deltaPositive
            delay={100}
            icon={
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M6.5 1L2 7h4l-.5 4L10 5H6l.5-4z" stroke="var(--gold)" strokeWidth="1.2" fill="none" />
              </svg>
            }
          />
          <div style={{ width: 1, background: "var(--border)", margin: "8px 0", flexShrink: 0 }} />
          <MetricCard
            label="Portfolio IRR"
            value={typeof irr === "number" ? irr.toFixed(1) : irr}
            unit="%"
            delta="+1.2pp vs target"
            deltaPositive
            delay={150}
            icon={
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <circle cx="6" cy="6" r="4.5" stroke="var(--gold)" strokeWidth="1.5" />
                <path d="M6 3.5v5M4.5 5.5l1.5-2 1.5 2" stroke="var(--gold)" strokeWidth="1" strokeLinecap="round" />
              </svg>
            }
          />
        </div>

        <InsightBar text="Slough DC grid headroom at 38 MW — below 40 MW threshold. 2 sites have connection offers expiring within 30 days. Kent BESS co-location could reduce reinforcement cost by 35%." />
      </div>

      {/* RIGHT — Health dial */}
      <div className="pd3-card pd3-enter-2" style={{ padding: 20, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <HealthDial
          avgScore={avgScore}
          goCount={goCount}
          cautionCount={cautionCount}
          nogoCount={nogoCount}
        />
      </div>
    </div>
  );
}
