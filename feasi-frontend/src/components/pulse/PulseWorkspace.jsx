/**
 * PulseWorkspace — dark "live intelligence command center".
 *
 * Six-panel grid (Bloomberg-inspired dark palette, deliberately distinct
 * from the rest of Princeps which is light). Panels:
 *   • PulseHeader (top strip — live counts, connection status)
 *   • EventStream (live ticker)
 *   • ClusterGraphView (planned — placeholder for now)
 *   • PriceCurveExplorer (planned — placeholder)
 *   • RegulatoryRadar (planned — placeholder)
 *   • PortfolioDeltaStrip (planned — placeholder)
 *
 * The WebSocket / data layer connects to /api/events/ws and all stats
 * endpoints for live values.
 */
import React, { useEffect, useState, useRef, useCallback } from "react";
import api from "../../services/api";
import ClusterGraphView from "./ClusterGraphView";

const DARK = {
  bg:         "#0b0e13",
  panel:      "#12151c",
  panelSoft:  "#161a23",
  border:     "rgba(255,255,255,0.06)",
  borderHi:   "rgba(255,255,255,0.12)",
  text:       "#e2e8f0",
  textDim:    "#94a3b8",
  textMuted:  "#64748b",
  gold:       "#f5b731",
  goldSoft:   "#f5b7311a",
  green:      "#10b981",
  amber:      "#f59e0b",
  red:        "#ef4444",
  blue:       "#3b82f6",
};

const SEVERITY_COLOURS = { info: DARK.blue, warn: DARK.amber, critical: DARK.red };

const ST = {
  page: {
    height: "100%",
    background: `radial-gradient(ellipse at top, #131822 0%, ${DARK.bg} 70%)`,
    color: DARK.text,
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  },
  header: {
    flexShrink: 0,
    padding: "12px 20px",
    background: `linear-gradient(180deg, ${DARK.panelSoft}cc 0%, transparent 100%)`,
    borderBottom: `1px solid ${DARK.border}`,
    display: "flex",
    alignItems: "center",
    gap: 24,
  },
  brand: {
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: 2,
    color: DARK.gold,
    textTransform: "uppercase",
  },
  title: { fontSize: 14, fontWeight: 700, color: DARK.text, marginRight: "auto" },
  kpi: { display: "flex", gap: 18, alignItems: "center" },
  kpiItem: { display: "flex", flexDirection: "column", alignItems: "flex-end" },
  kpiValue: {
    fontSize: 16,
    fontWeight: 800,
    fontFamily: "'JetBrains Mono', monospace",
    lineHeight: 1,
  },
  kpiLabel: {
    fontSize: 9,
    color: DARK.textMuted,
    marginTop: 3,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  connDot: (ok) => ({
    width: 7, height: 7, borderRadius: 7,
    background: ok ? DARK.green : DARK.amber,
    boxShadow: ok ? `0 0 8px ${DARK.green}aa` : "none",
    marginRight: 6,
  }),
  grid: {
    flex: 1,
    display: "grid",
    gridTemplateColumns: "1.3fr 1fr 1fr",
    gridTemplateRows: "1fr 1fr",
    gap: 12,
    padding: 14,
    minHeight: 0,
  },
  panel: {
    background: DARK.panel,
    border: `1px solid ${DARK.border}`,
    borderRadius: 10,
    padding: 14,
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    overflow: "hidden",
  },
  panelTitle: {
    fontSize: 10,
    fontWeight: 700,
    color: DARK.textDim,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 10,
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  livePulse: {
    width: 6, height: 6, borderRadius: 6,
    background: DARK.green,
    animation: "pulse 1.6s ease-in-out infinite",
  },
  eventRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "8px 0",
    borderBottom: `1px solid ${DARK.border}`,
    fontSize: 11,
  },
  eventTime: {
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 10,
    color: DARK.textMuted,
    minWidth: 48,
  },
  sevPill: (sev) => ({
    padding: "2px 7px",
    borderRadius: 10,
    background: `${SEVERITY_COLOURS[sev] || DARK.blue}25`,
    color: SEVERITY_COLOURS[sev] || DARK.blue,
    fontSize: 9,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  }),
  empty: { padding: 20, color: DARK.textMuted, fontSize: 11, textAlign: "center" },
  scroll: { flex: 1, overflowY: "auto", minHeight: 0 },
};


export default function PulseWorkspace() {
  const [stats, setStats] = useState(null);
  const [events, setEvents] = useState([]);
  const [headroomStats, setHeadroomStats] = useState(null);
  const [ecrStats, setEcrStats] = useState(null);
  const [curtailmentStats, setCurtailmentStats] = useState(null);
  const [clusterStats, setClusterStats] = useState(null);
  const [deltas, setDeltas] = useState([]);
  const [scenario] = useState("base");
  const [wsOpen, setWsOpen] = useState(false);
  const wsRef = useRef(null);

  // Bulk load stats
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [ev, nged, ecr, curt, cl, dl] = await Promise.allSettled([
        api.events.stats(),
        api.nged.headroomStats(),
        api.nged.ecrStats(),
        api.curtailment.stats(),
        api.cluster.stats(),
        api.portfolioDelta.latest(20),
      ]);
      if (cancelled) return;
      if (ev.status === "fulfilled") setStats(ev.value);
      if (nged.status === "fulfilled") setHeadroomStats(nged.value);
      if (ecr.status === "fulfilled") setEcrStats(ecr.value);
      if (curt.status === "fulfilled") setCurtailmentStats(curt.value);
      if (cl.status === "fulfilled") setClusterStats(cl.value);
      if (dl.status === "fulfilled") setDeltas(dl.value);
    })();
    return () => { cancelled = true; };
  }, []);

  // Initial events
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ev = await api.events.list({ limit: 50 });
        if (!cancelled) setEvents(ev);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  // WebSocket live stream
  useEffect(() => {
    const url = api.events.wsUrl();
    let ws;
    let reconnectTimer;
    const connect = () => {
      try {
        ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => setWsOpen(true);
        ws.onclose = () => {
          setWsOpen(false);
          reconnectTimer = setTimeout(connect, 4000);
        };
        ws.onerror = () => {};
        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.kind === "grid_event" && msg.event) {
              setEvents(prev => [msg.event, ...prev].slice(0, 200));
            }
          } catch {}
        };
      } catch {}
    };
    connect();
    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, []);

  const runDiff = useCallback(async () => {
    try {
      await api.events.runDiff();
      const ev = await api.events.list({ limit: 50 });
      setEvents(ev);
    } catch {}
  }, []);

  const [takingSnapshot, setTakingSnapshot] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  const takeSnapshotNow = useCallback(async () => {
    setTakingSnapshot(true);
    setSnapshotError("");
    try {
      await api.portfolioDelta.snapshot();
      const dl = await api.portfolioDelta.latest(20);
      setDeltas(dl || []);
    } catch (e) {
      setSnapshotError(e?.message || String(e));
    } finally {
      setTakingSnapshot(false);
    }
  }, []);

  return (
    <div style={ST.page}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.3); }
        }
        .pulse-scroll::-webkit-scrollbar { width: 4px; }
        .pulse-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
      `}</style>

      {/* HEADER */}
      <div style={ST.header}>
        <div style={ST.brand}>PULSE</div>
        <div style={ST.title}>Live grid intelligence</div>
        <div style={{ display: "flex", alignItems: "center", fontSize: 10, color: DARK.textDim }}>
          <div style={ST.connDot(wsOpen)} />
          {wsOpen ? "WebSocket live" : "Reconnecting…"}
        </div>
        <div style={ST.kpi}>
          <KpiTile value={stats?.critical_24h ?? 0} label="Critical 24h" colour={DARK.red} />
          <KpiTile value={stats?.events_24h ?? 0} label="Events 24h" colour={DARK.blue} />
          <KpiTile value={headroomStats?.n_substations ?? 0} label="Substations" colour={DARK.gold} />
          <KpiTile value={ecrStats?.total_records ?? 0} label="ECR Sites" colour={DARK.green} />
          <KpiTile
            value={`${Math.round((headroomStats?.total_demand_headroom_mw ?? 0) / 1000)}k`}
            label="MW Headroom"
            colour={DARK.green}
          />
          <KpiTile value={clusterStats?.studies ?? 0} label="Clusters" colour={DARK.amber} />
        </div>
        <button
          onClick={runDiff}
          style={{
            marginLeft: 12,
            padding: "6px 12px",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 0.5,
            background: DARK.goldSoft,
            color: DARK.gold,
            border: `1px solid ${DARK.gold}44`,
            borderRadius: 6,
            cursor: "pointer",
            textTransform: "uppercase",
          }}
        >Run diff cycle</button>
      </div>

      {/* 6-PANEL GRID */}
      <div style={ST.grid}>
        {/* 1 — Event Stream */}
        <div style={{ ...ST.panel, gridRow: "span 2" }}>
          <div style={ST.panelTitle}>
            <div style={ST.livePulse} /> Event Stream
            <span style={{ marginLeft: "auto", color: DARK.textMuted, fontSize: 9 }}>
              {events.length} shown
            </span>
          </div>
          <div style={ST.scroll} className="pulse-scroll">
            {events.length === 0 ? (
              <div style={ST.empty}>No events yet. Press <b>Run diff cycle</b> to populate.</div>
            ) : (
              events.map((e, i) => (
                <EventRow key={e.event_id || i} event={e} />
              ))
            )}
          </div>
        </div>

        {/* 2 — Cluster Graph (d3-force + canvas) */}
        <div style={{ ...ST.panel, padding: 0, position: "relative" }}>
          <div style={{ ...ST.panelTitle, position: "absolute", top: 12, left: 14, right: 14, zIndex: 5 }}>
            Cluster Graph
          </div>
          <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
            <ClusterGraphView />
          </div>
        </div>

        {/* 3 — Price Curve placeholder */}
        <div style={ST.panel}>
          <div style={ST.panelTitle}>Curtailment Intelligence</div>
          <div style={ST.scroll} className="pulse-scroll">
            {curtailmentStats ? (
              <>
                <StatLine label="Historical actions" value={curtailmentStats.historical_actions} />
                <StatLine label="Sensitivity rows" value={curtailmentStats.sensitivity_rows} />
                <StatLine label="Generator profiles" value={curtailmentStats.generator_profiles} />
                <StatLine label="Scenarios" value={curtailmentStats.scenarios} />
              </>
            ) : <div style={ST.empty}>Loading…</div>}
          </div>
        </div>

        {/* 4 — Regulatory Radar placeholder */}
        <div style={ST.panel}>
          <div style={ST.panelTitle}>NGED ECR</div>
          <div style={ST.scroll} className="pulse-scroll">
            {ecrStats ? (
              <>
                <StatLine label="Total records" value={ecrStats.total_records?.toLocaleString()} />
                <StatLine label="Connected" value={ecrStats.connected?.toLocaleString()} />
                <StatLine label="In queue" value={ecrStats.in_queue?.toLocaleString()} />
                <StatLine label="Total MW connected" value={`${Math.round(ecrStats.total_connected_mw || 0).toLocaleString()}`} />
                {ecrStats.by_technology?.slice(0, 5).map((t, i) => (
                  <StatLine key={i} label={t.tech || "—"} value={`${Math.round(t.total_mw)} MW`} />
                ))}
              </>
            ) : <div style={ST.empty}>Loading…</div>}
          </div>
        </div>

        {/* 5 — Portfolio Delta */}
        <div style={ST.panel}>
          <div style={ST.panelTitle}>Portfolio Deltas</div>
          <div style={ST.scroll} className="pulse-scroll">
            {deltas.length === 0 ? (
              <div style={{
                ...ST.empty,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 10,
                padding: "24px 16px",
              }}>
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: "50%",
                    border: `1px solid ${DARK.gold}55`,
                    background: "rgba(245, 183, 49, 0.08)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: DARK.gold,
                    fontSize: 14,
                    fontWeight: 700,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                  aria-hidden
                >
                  Δ
                </div>
                <div style={{ fontSize: 11, color: DARK.text, fontWeight: 600 }}>
                  No portfolio movements yet
                </div>
                <div style={{ fontSize: 10, color: DARK.textMuted, lineHeight: 1.5, maxWidth: 220 }}>
                  Take a portfolio snapshot to start tracking day-over-day
                  verdict, score, and capacity changes.
                </div>
                <button
                  onClick={takeSnapshotNow}
                  disabled={takingSnapshot}
                  style={{
                    padding: "6px 12px",
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: 0.5,
                    background: DARK.goldSoft,
                    color: DARK.gold,
                    border: `1px solid ${DARK.gold}44`,
                    borderRadius: 6,
                    cursor: takingSnapshot ? "progress" : "pointer",
                    textTransform: "uppercase",
                    opacity: takingSnapshot ? 0.7 : 1,
                  }}
                >
                  {takingSnapshot ? "Taking snapshot…" : "Take snapshot"}
                </button>
                {snapshotError && (
                  <div style={{ fontSize: 10, color: DARK.red, fontStyle: "italic", maxWidth: 220, textAlign: "center" }}>
                    {snapshotError}
                  </div>
                )}
              </div>
            ) : (
              deltas.slice(0, 10).map((d, i) => (
                <div key={i} style={ST.eventRow}>
                  <span style={{ ...ST.eventTime, color: d.delta > 0 ? DARK.green : DARK.red }}>
                    {d.delta > 0 ? "↑" : "↓"} {d.delta?.toFixed?.(1) ?? "—"}
                  </span>
                  <span style={{ flex: 1, fontSize: 11 }}>{d.project_id?.substring(0, 20)}</span>
                  <span style={{ fontSize: 10, color: DARK.textMuted }}>{d.metric}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


function KpiTile({ value, label, colour }) {
  return (
    <div style={ST.kpiItem}>
      <div style={{ ...ST.kpiValue, color: colour }}>{value}</div>
      <div style={ST.kpiLabel}>{label}</div>
    </div>
  );
}


function StatLine({ label, value }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      padding: "7px 0",
      borderBottom: `1px solid ${DARK.border}`,
      fontSize: 11,
    }}>
      <span style={{ color: DARK.textDim }}>{label}</span>
      <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: DARK.text }}>
        {value}
      </span>
    </div>
  );
}


function EventRow({ event }) {
  const time = event.detected_at
    ? new Date(event.detected_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : "—";
  return (
    <div style={ST.eventRow}>
      <span style={ST.eventTime}>{time}</span>
      <span style={ST.sevPill(event.severity || "info")}>{event.severity || "info"}</span>
      <span style={{ flex: 1, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        <b style={{ color: DARK.text }}>{event.event_type?.replace(/_/g, " ")}</b>
        {event.project_id && (
          <span style={{ color: DARK.textMuted, marginLeft: 6 }}>
            · {event.project_id.substring(0, 18)}
          </span>
        )}
      </span>
    </div>
  );
}
