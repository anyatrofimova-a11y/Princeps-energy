import React, { useEffect, useMemo, useRef, useState } from "react";

/**
 * LiveBessRevenue — customer-facing live BESS revenue widget for /v2.
 *
 * Reads the last 30 days of hourly snapshots from
 *   GET  /api/bess/revenue-snapshot?rid=<rid>
 * then upgrades to
 *   WS   /ws/bess-live-revenue?rid=<rid>
 * for live appends. Renders a stacked SVG bar chart (one bar per day,
 * stacked by revenue stream — wholesale / DM / DC / DR / FFR / capacity)
 * with the Modo Energy P50 forward overlay as a dashed line.
 *
 * Princeps aesthetic: light card, gold accent, glass shadow, DM Sans for
 * copy and JetBrains Mono (tabular-nums) for numbers. NOT Foundry-dark.
 *
 * Backend contract: app/routers/bess_live.py + migrations/2026_05_01_bess_live_revenue.sql.
 * Hourly cron writer: app/cron/bess_revenue_cron.py.
 *
 * Note: Modo overlay is a STUB (annual/365 with seasonal sinusoid) until a
 * real Modo feed is wired — labelled "Modo P50 (mock)" so demo viewers can
 * see what's real and what isn't. See bess_revenue_cron.py:_modo_p50_forecast_gbp.
 */

// Stream colours — keyed to revenue stream names from
// utils/bess_revenue_stacker.py:REVENUE_STREAMS. Gold-anchored palette so
// the chart blends with the Princeps tokens.
const STREAM_COLOURS = {
  wholesale_arbitrage: "#F5B731", // gold (the headline stream)
  balancing_mechanism: "#E8A012", // gold-dark
  dynamic_containment: "#5B7FE8", // cool blue
  capacity_market:     "#3F4754", // ink-grey (passive, slate)
  ffr_static:          "#8E94A0", // muted grey
  tnuos_triad:         "#C9A36B", // bronze
};

const STREAM_LABELS = {
  wholesale_arbitrage: "Wholesale",
  balancing_mechanism: "BM",
  dynamic_containment: "DC / DM / DR",
  capacity_market:     "Capacity",
  ffr_static:          "FFR",
  tnuos_triad:         "TNUoS",
};

const STREAM_ORDER = [
  "wholesale_arbitrage",
  "balancing_mechanism",
  "dynamic_containment",
  "capacity_market",
  "ffr_static",
  "tnuos_triad",
];

// ── helpers ────────────────────────────────────────────────────────────────

function fmtGbp(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `£${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)     return `£${(v / 1_000).toFixed(1)}k`;
  return `£${Math.round(v)}`;
}

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

function fmtDayShort(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${d.getDate()}/${d.getMonth() + 1}`;
  } catch { return ""; }
}

function timeAgo(iso) {
  if (!iso) return "—";
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 60_000) return "just now";
    const m = Math.floor(ms / 60_000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return "—"; }
}

// Group snapshots into one bar per day (using the latest snapshot per day
// since each snapshot is the rolling-30d projection — taking the latest
// gives the most up-to-date market state per day on the x-axis).
function groupByDay(snapshots) {
  const byDay = new Map();
  for (const s of snapshots || []) {
    const d = new Date(s.ts);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    const existing = byDay.get(key);
    if (!existing || new Date(s.ts) > new Date(existing.ts)) {
      byDay.set(key, s);
    }
  }
  return Array.from(byDay.values()).sort(
    (a, b) => new Date(a.ts) - new Date(b.ts),
  );
}

// ── chart primitive ────────────────────────────────────────────────────────

function StackedBarChart({ snapshots, width = 720, height = 260 }) {
  const padL = 56, padR = 16, padT = 12, padB = 30;
  const innerW = Math.max(60, width - padL - padR);
  const innerH = Math.max(40, height - padT - padB);
  const days = useMemo(() => groupByDay(snapshots), [snapshots]);

  const yMax = useMemo(() => {
    let m = 0;
    for (const s of days) {
      const total = STREAM_ORDER.reduce(
        (acc, k) => acc + ((s.stack_breakdown?.streams || {})[k] || 0),
        0,
      );
      const modo = s.modo_p50_forecast || 0;
      m = Math.max(m, total, modo);
    }
    return m * 1.10 || 1;
  }, [days]);

  if (!days.length) {
    return (
      <div style={{
        height,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#6E747E",
        fontFamily: "DM Sans, sans-serif",
        fontSize: 13,
        background: "rgba(245,183,49,0.04)",
        borderRadius: 8,
      }}>
        Waiting for first snapshot…
      </div>
    );
  }

  const barGap = 2;
  const barW = Math.max(2, (innerW / days.length) - barGap);
  const yScale = (v) => innerH - (v / yMax) * innerH;

  // Y-axis ticks (4 ticks plus zero).
  const ticks = [0, 0.25, 0.5, 0.75, 1.0].map((p) => p * yMax);

  // Modo overlay path.
  const modoPath = days
    .map((s, i) => {
      const x = padL + i * (barW + barGap) + barW / 2;
      const y = padT + yScale(s.modo_p50_forecast || 0);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label="BESS revenue stack — last 30 days"
      style={{ display: "block" }}
    >
      {/* gridlines + y-axis labels */}
      {ticks.map((t, i) => {
        const y = padT + yScale(t);
        return (
          <g key={i}>
            <line
              x1={padL} x2={width - padR}
              y1={y} y2={y}
              stroke="rgba(15,19,24,0.06)"
              strokeDasharray={i === 0 ? "" : "2 3"}
              strokeWidth="1"
            />
            <text
              x={padL - 6} y={y + 4}
              textAnchor="end"
              fontSize="10"
              fontFamily="JetBrains Mono, monospace"
              fill="#6E747E"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {fmtGbp(t)}
            </text>
          </g>
        );
      })}

      {/* stacked bars */}
      {days.map((s, i) => {
        const x = padL + i * (barW + barGap);
        const streams = s.stack_breakdown?.streams || {};
        let cumY = innerH;
        return (
          <g key={s.snapshot_id || i}>
            {STREAM_ORDER.map((k) => {
              const v = streams[k] || 0;
              if (v <= 0) return null;
              const h = (v / yMax) * innerH;
              cumY -= h;
              return (
                <rect
                  key={k}
                  x={x.toFixed(1)} y={(padT + cumY).toFixed(1)}
                  width={barW.toFixed(1)} height={h.toFixed(1)}
                  fill={STREAM_COLOURS[k] || "#999"}
                  opacity="0.92"
                >
                  <title>{`${STREAM_LABELS[k]}: ${fmtGbp(v)}`}</title>
                </rect>
              );
            })}
          </g>
        );
      })}

      {/* modo overlay */}
      {days.length > 1 && (
        <path
          d={modoPath}
          fill="none"
          stroke="#0F1318"
          strokeWidth="1.5"
          strokeDasharray="4 3"
          opacity="0.75"
        />
      )}

      {/* x-axis tick labels — first, middle, last */}
      {[0, Math.floor(days.length / 2), days.length - 1]
        .filter((i, idx, arr) => arr.indexOf(i) === idx && i >= 0 && i < days.length)
        .map((i) => {
          const x = padL + i * (barW + barGap) + barW / 2;
          return (
            <text
              key={i}
              x={x} y={height - 10}
              textAnchor="middle"
              fontSize="10"
              fontFamily="JetBrains Mono, monospace"
              fill="#6E747E"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {fmtDayShort(days[i].ts)}
            </text>
          );
        })}

      {/* baseline */}
      <line
        x1={padL} x2={width - padR}
        y1={padT + innerH} y2={padT + innerH}
        stroke="#0F1318"
        strokeWidth="1"
      />
    </svg>
  );
}

// ── main widget ────────────────────────────────────────────────────────────

export default function LiveBessRevenue({ rid: ridProp }) {
  const [snapshots, setSnapshots] = useState([]);
  const [meta, setMeta] = useState({ rid: null, site_name: null, latest_ts: null });
  const [breakdown, setBreakdown] = useState(null);
  const [wsState, setWsState] = useState("connecting"); // connecting | live | reconnecting | error
  const [error, setError] = useState(null);
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  const rid = ridProp || meta.rid;

  // Bootstrap: fetch last 30d.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const url = ridProp
          ? `/api/bess/revenue-snapshot?rid=${encodeURIComponent(ridProp)}`
          : "/api/bess/revenue-snapshot";
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (cancelled) return;
        setSnapshots(d.snapshots || []);
        setMeta({ rid: d.rid, site_name: d.site_name, latest_ts: d.latest_ts });
      } catch (e) {
        if (!cancelled) setError(`bootstrap failed: ${e.message}`);
      }
    })();
    return () => { cancelled = true; };
  }, [ridProp]);

  // Bootstrap: today's breakdown for the side panel.
  useEffect(() => {
    if (!rid) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`/api/bess/revenue-stack-breakdown?rid=${encodeURIComponent(rid)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setBreakdown(d);
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, [rid, snapshots.length]);

  // WebSocket lifecycle.
  useEffect(() => {
    if (!rid) return;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${window.location.host}/ws/bess-live-revenue?rid=${encodeURIComponent(rid)}`;
      let ws;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        setWsState("error");
        return;
      }
      wsRef.current = ws;
      setWsState("connecting");

      ws.onopen = () => setWsState("live");
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data);
          if (m.event === "snapshot" && m.data) {
            setSnapshots((prev) => {
              if (prev.some((p) => p.snapshot_id === m.data.snapshot_id)) return prev;
              const next = [...prev, m.data];
              if (next.length > 720) next.splice(0, next.length - 720); // ~30d * 24h
              return next;
            });
            setMeta((mm) => ({ ...mm, latest_ts: m.data.ts }));
          }
        } catch { /* ignore */ }
      };
      ws.onerror = () => setWsState("error");
      ws.onclose = () => {
        if (stopped) return;
        setWsState("reconnecting");
        // Exponential-ish backoff, capped at 8s.
        reconnectRef.current = setTimeout(connect, 4000);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* ignore */ }
      }
    };
  }, [rid]);

  const latest = snapshots.length ? snapshots[snapshots.length - 1] : null;

  // ── render ────────────────────────────────────────────────────────────
  const liveDot = (
    <span
      aria-label={`status: ${wsState}`}
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background:
          wsState === "live" ? "#16A34A" :
          wsState === "connecting" ? "#F5B731" :
          wsState === "reconnecting" ? "#E8A012" : "#DC2626",
        boxShadow:
          wsState === "live"
            ? "0 0 0 3px rgba(22,163,74,0.18)"
            : "0 0 0 3px rgba(245,183,49,0.18)",
        marginRight: 6,
        verticalAlign: "middle",
        animation: wsState === "live" ? "pulse-live 2s ease-in-out infinite" : undefined,
      }}
    />
  );

  return (
    <article className="lbr-card" data-testid="live-bess-revenue">
      <header className="lbr-head">
        <div className="lbr-head-left">
          <span className="lbr-kicker">Live BESS revenue</span>
          <h3 className="lbr-title">
            {meta.site_name || "Loading…"}
          </h3>
        </div>
        <div className="lbr-head-right">
          <span className="lbr-status">
            {liveDot}
            <span className="lbr-status-label">
              {wsState === "live" ? "Live" :
               wsState === "connecting" ? "Connecting" :
               wsState === "reconnecting" ? "Reconnecting" : "Offline"}
            </span>
          </span>
          <span className="lbr-updated" title={meta.latest_ts || ""}>
            Updated {timeAgo(meta.latest_ts)}
          </span>
        </div>
      </header>

      {error && (
        <div className="lbr-err">{error}</div>
      )}

      <div className="lbr-body">
        <div className="lbr-chart-wrap">
          <StackedBarChart snapshots={snapshots} width={720} height={260} />
          <div className="lbr-legend">
            {STREAM_ORDER.map((k) => (
              <span key={k} className="lbr-legend-chip">
                <i style={{ background: STREAM_COLOURS[k] }} />
                {STREAM_LABELS[k]}
              </span>
            ))}
            <span className="lbr-legend-chip lbr-legend-modo">
              <i className="lbr-legend-dash" />
              Modo P50 <em>(mock)</em>
            </span>
          </div>
        </div>

        <aside className="lbr-side">
          <div className="lbr-side-section">
            <span className="lbr-side-label">Today (30d rolling, P50)</span>
            <span className="lbr-side-big">
              {fmtGbp(latest?.p50_rev_gbp)}
            </span>
            {breakdown?.delta_vs_yesterday_pct != null && (
              <span
                className="lbr-side-delta"
                data-positive={breakdown.delta_vs_yesterday_pct >= 0 ? "1" : "0"}
              >
                {fmtPct(breakdown.delta_vs_yesterday_pct)} vs yesterday
              </span>
            )}
          </div>

          <div className="lbr-side-row">
            <span className="lbr-side-label">P10</span>
            <span className="lbr-side-num">{fmtGbp(latest?.p10_rev_gbp)}</span>
          </div>
          <div className="lbr-side-row">
            <span className="lbr-side-label">P90</span>
            <span className="lbr-side-num">{fmtGbp(latest?.p90_rev_gbp)}</span>
          </div>
          <div className="lbr-side-row">
            <span className="lbr-side-label">Modo P50</span>
            <span className="lbr-side-num">{fmtGbp(latest?.modo_p50_forecast)}</span>
          </div>

          {latest?.stack_breakdown && (
            <div className="lbr-side-streams">
              <span className="lbr-side-label" style={{ marginBottom: 4 }}>Stack split</span>
              {STREAM_ORDER.map((k) => {
                const v = (latest.stack_breakdown.streams || {})[k];
                if (!v) return null;
                const total = latest.p50_rev_gbp || 1;
                const pct = (v / total) * 100;
                return (
                  <div key={k} className="lbr-stream-row">
                    <i style={{ background: STREAM_COLOURS[k] }} />
                    <span className="lbr-stream-label">{STREAM_LABELS[k]}</span>
                    <span className="lbr-stream-num">{fmtGbp(v)}</span>
                    <span className="lbr-stream-pct">{pct.toFixed(0)}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </aside>
      </div>

      <footer className="lbr-foot">
        <span>
          Snapshot {fmtTime(meta.latest_ts)} · cron-stacker-v1 ·
          {" "}{snapshots.length} obs · 30d window
        </span>
        <span className="lbr-foot-cite">
          Modo overlay is a mock until the live feed is wired.
        </span>
      </footer>

      <style>{lbrCss}</style>
    </article>
  );
}

// ── styles (DM Sans + JetBrains Mono, gold accent, glass card) ────────────
const lbrCss = `
@keyframes pulse-live {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.55; }
}

.lbr-card {
  background: #FFFFFF;
  border: 1px solid rgba(15,19,24,0.06);
  border-radius: 12px;
  padding: 18px 20px 14px;
  box-shadow: 0 4px 24px rgba(15,19,24,0.08);
  font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
  color: #0F1318;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.lbr-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.lbr-head-left { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.lbr-kicker {
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: #6E747E;
}
.lbr-title {
  font-size: 18px; font-weight: 700; margin: 0;
  color: #0F1318;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 380px;
}
.lbr-head-right { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 12px; }
.lbr-status { display: inline-flex; align-items: center; font-weight: 600; }
.lbr-status-label { font-size: 12px; color: #0F1318; }
.lbr-updated {
  color: #6E747E; font-size: 11px;
  font-family: "JetBrains Mono", "SF Mono", monospace;
  font-variant-numeric: tabular-nums;
}

.lbr-err {
  background: rgba(220,38,38,0.08);
  color: #DC2626;
  padding: 8px 10px;
  font-size: 12px;
  border-radius: 6px;
}

.lbr-body { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 18px; align-items: stretch; }
.lbr-chart-wrap { min-width: 0; display: flex; flex-direction: column; gap: 8px; }

.lbr-legend {
  display: flex; flex-wrap: wrap; gap: 10px;
  font-size: 11px; color: #3F4754;
}
.lbr-legend-chip {
  display: inline-flex; align-items: center; gap: 4px;
}
.lbr-legend-chip i {
  display: inline-block; width: 10px; height: 10px;
  border-radius: 2px;
}
.lbr-legend-modo i.lbr-legend-dash {
  width: 14px; height: 0;
  border-top: 2px dashed #0F1318;
  border-radius: 0;
}
.lbr-legend-modo em { font-style: italic; color: #6E747E; }

.lbr-side {
  display: flex; flex-direction: column; gap: 8px;
  border-left: 1px solid rgba(15,19,24,0.06);
  padding-left: 14px;
}
.lbr-side-section { display: flex; flex-direction: column; gap: 2px; padding-bottom: 8px;
  border-bottom: 1px solid rgba(15,19,24,0.06); }
.lbr-side-label {
  font-size: 11px; color: #6E747E; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.lbr-side-big {
  font-family: "JetBrains Mono", monospace;
  font-variant-numeric: tabular-nums;
  font-size: 22px; font-weight: 700; color: #0F1318;
}
.lbr-side-delta {
  font-size: 12px; font-weight: 600;
  font-family: "JetBrains Mono", monospace;
  font-variant-numeric: tabular-nums;
}
.lbr-side-delta[data-positive="1"] { color: #16A34A; }
.lbr-side-delta[data-positive="0"] { color: #DC2626; }

.lbr-side-row {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 12px;
}
.lbr-side-num {
  font-family: "JetBrains Mono", monospace;
  font-variant-numeric: tabular-nums;
  color: #0F1318; font-weight: 600;
}

.lbr-side-streams {
  display: flex; flex-direction: column; gap: 4px;
  margin-top: 6px; padding-top: 8px;
  border-top: 1px solid rgba(15,19,24,0.06);
}
.lbr-stream-row {
  display: grid; grid-template-columns: 10px 1fr auto auto;
  align-items: center; gap: 6px;
  font-size: 11px;
}
.lbr-stream-row i {
  width: 8px; height: 8px; border-radius: 2px; display: inline-block;
}
.lbr-stream-label { color: #3F4754; }
.lbr-stream-num {
  font-family: "JetBrains Mono", monospace;
  font-variant-numeric: tabular-nums;
  color: #0F1318;
}
.lbr-stream-pct {
  font-family: "JetBrains Mono", monospace;
  font-variant-numeric: tabular-nums;
  color: #6E747E; min-width: 28px; text-align: right;
}

.lbr-foot {
  display: flex; justify-content: space-between; align-items: center;
  gap: 12px; padding-top: 6px;
  font-size: 11px; color: #6E747E;
  border-top: 1px solid rgba(15,19,24,0.04);
}
.lbr-foot-cite { font-style: italic; }

@media (max-width: 880px) {
  .lbr-body { grid-template-columns: 1fr; }
  .lbr-side { border-left: none; border-top: 1px solid rgba(15,19,24,0.06); padding-left: 0; padding-top: 12px; }
}
`;
