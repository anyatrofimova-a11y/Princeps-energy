/**
 * SignalFeed — Real-time energy intelligence signal stream.
 *
 * Right-side panel showing live energy OSINT signals:
 *   - BMRS demand/generation updates
 *   - Grid frequency deviations
 *   - Constraint alerts (thermal, voltage)
 *   - Connection queue changes (ECR)
 *   - Weather/solar conditions
 *   - Planning alerts
 *
 * Each signal is clickable to fly the camera to the relevant location.
 *
 * Props:
 *   gridState       — current grid state
 *   onFlyTo(loc)    — callback to fly camera to {lon, lat, zoom}
 *   onDispatchAgent(intent, context) — trigger AI analysis
 */
import React, { useState, useEffect, useRef, useCallback } from "react";

/* Signal types with icons and colors */
const SIGNAL_TYPES = {
  demand:     { icon: "D", color: "#D4A018", label: "Demand" },
  generation: { icon: "G", color: "#52c41a", label: "Generation" },
  frequency:  { icon: "F", color: "#1890ff", label: "Frequency" },
  constraint: { icon: "!", color: "#f5222d", label: "Constraint" },
  congestion: { icon: "C", color: "#fa8c16", label: "Congestion" },
  queue:      { icon: "Q", color: "#e040fb", label: "Queue" },
  weather:    { icon: "W", color: "#00b4d8", label: "Weather" },
  planning:   { icon: "P", color: "#8c8c8c", label: "Planning" },
  agent:      { icon: "A", color: "#D4A018", label: "AI Agent" },
};

function fmtAgo(ms) {
  if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  return `${Math.floor(ms / 3600000)}h ago`;
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Math.round(v)} MW`;
}

export default function SignalFeed({ gridState, onFlyTo, onDispatchAgent }) {
  const [signals, setSignals] = useState([]);
  const [filter, setFilter] = useState("all");
  const [collapsed, setCollapsed] = useState(false);
  const prevStateRef = useRef(null);
  const signalIdRef = useRef(0);

  /* ── Generate signals from grid state changes ── */
  useEffect(() => {
    if (!gridState) return;
    const prev = prevStateRef.current;
    const newSignals = [];
    const ts = Date.now();

    // System-level signals
    const sys = gridState.system;
    if (sys) {
      // Frequency deviation
      if (Math.abs(sys.frequency_hz - 50) > 0.05) {
        newSignals.push({
          id: signalIdRef.current++,
          type: "frequency",
          severity: Math.abs(sys.frequency_hz - 50) > 0.1 ? "critical" : "warning",
          title: `Grid frequency ${sys.frequency_hz.toFixed(3)} Hz`,
          detail: `${Math.abs(sys.frequency_hz - 50) > 0.1 ? "Critical" : "Warning"}: ${(Math.abs(sys.frequency_hz - 50) * 1000).toFixed(0)} mHz deviation`,
          ts,
        });
      }

      // Demand update
      if (!prev || Math.abs((prev.system?.total_demand_mw || 0) - sys.total_demand_mw) > 50) {
        const delta = prev ? sys.total_demand_mw - prev.system.total_demand_mw : 0;
        newSignals.push({
          id: signalIdRef.current++,
          type: "demand",
          severity: "info",
          title: `System demand ${fmtMw(sys.total_demand_mw)}`,
          detail: delta ? `${delta > 0 ? "+" : ""}${fmtMw(delta)} since last update` : "Initial reading",
          ts,
        });
      }

      // Generation
      if (!prev || Math.abs((prev.system?.total_generation_mw || 0) - sys.total_generation_mw) > 50) {
        newSignals.push({
          id: signalIdRef.current++,
          type: "generation",
          severity: "info",
          title: `Generation ${fmtMw(sys.total_generation_mw)}`,
          detail: `Utilisation ${(sys.system_utilisation * 100).toFixed(1)}%`,
          ts,
        });
      }
    }

    // Substation-level signals
    for (const s of gridState.substations || []) {
      if (s.utilisation >= 0.9) {
        // Check if this is new/worsened
        const prevSub = prev?.substations?.find(ps => ps.id === s.id);
        if (!prevSub || prevSub.utilisation < 0.9) {
          newSignals.push({
            id: signalIdRef.current++,
            type: "constraint",
            severity: s.utilisation >= 0.95 ? "critical" : "warning",
            title: `${s.name} at ${(s.utilisation * 100).toFixed(0)}%`,
            detail: `${fmtMw(s.demand_mw)} demand, ${fmtMw(s.headroom_mw)} headroom remaining`,
            location: { lon: s.lon, lat: s.lat },
            context: { substation: s },
            ts,
          });
        }
      }
    }

    // Line congestion
    for (const l of gridState.lines || []) {
      if (l.congested) {
        const prevLine = prev?.lines?.find(pl => pl.from === l.from && pl.to === l.to);
        if (!prevLine || !prevLine.congested) {
          newSignals.push({
            id: signalIdRef.current++,
            type: "congestion",
            severity: l.loading_pct > 90 ? "critical" : "warning",
            title: `${l.from} → ${l.to} congested`,
            detail: `${l.loading_pct.toFixed(0)}% loading, ${fmtMw(Math.abs(l.flow_mw))} flow on ${l.voltage_kv} kV`,
            location: {
              lon: (l.from_coords[0] + l.to_coords[0]) / 2,
              lat: (l.from_coords[1] + l.to_coords[1]) / 2,
            },
            context: { line: l },
            ts,
          });
        }
      }
    }

    if (newSignals.length > 0) {
      setSignals(prev => [...newSignals, ...prev].slice(0, 100));
    }
    prevStateRef.current = gridState;
  }, [gridState]);

  /* ── Periodic synthetic signals (weather, queue) ── */
  useEffect(() => {
    const interval = setInterval(() => {
      const ts = Date.now();
      // Simulate weather update
      if (Math.random() < 0.3) {
        setSignals(prev => [{
          id: signalIdRef.current++,
          type: "weather",
          severity: "info",
          title: `Solar irradiance ${(300 + Math.random() * 500).toFixed(0)} W/m²`,
          detail: `Cloud cover ${(Math.random() * 80).toFixed(0)}%, wind ${(3 + Math.random() * 12).toFixed(1)} m/s`,
          ts,
        }, ...prev].slice(0, 100));
      }
      // Simulate queue update
      if (Math.random() < 0.15) {
        const gsp = ["Bramley", "Beddington", "Manchester South", "Cambridge", "Norwich"][Math.floor(Math.random() * 5)];
        setSignals(prev => [{
          id: signalIdRef.current++,
          type: "queue",
          severity: "info",
          title: `ECR update: ${gsp}`,
          detail: `${Math.floor(2 + Math.random() * 8)} new applications, ${(10 + Math.random() * 50).toFixed(0)} MW queued`,
          ts,
        }, ...prev].slice(0, 100));
      }
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  const filtered = filter === "all" ? signals : signals.filter(s => s.type === filter);

  if (collapsed) {
    return (
      <div className="sf-collapsed" onClick={() => setCollapsed(false)}>
        <div className="sf-collapsed-badge">
          {signals.filter(s => s.severity === "critical").length > 0 && (
            <span className="sf-badge sf-badge-critical">{signals.filter(s => s.severity === "critical").length}</span>
          )}
          {signals.filter(s => s.severity === "warning").length > 0 && (
            <span className="sf-badge sf-badge-warning">{signals.filter(s => s.severity === "warning").length}</span>
          )}
        </div>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
      </div>
    );
  }

  return (
    <div className="sf-panel">
      {/* Header */}
      <div className="sf-header">
        <div className="sf-header-left">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
          </svg>
          <span className="sf-title">Signal Feed</span>
          <span className="sf-count">{signals.length}</span>
        </div>
        <button className="sf-collapse-btn" onClick={() => setCollapsed(true)}>&lsaquo;</button>
      </div>

      {/* Filters */}
      <div className="sf-filters">
        <button className={`sf-filter ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>All</button>
        {Object.entries(SIGNAL_TYPES).map(([key, t]) => (
          <button key={key}
            className={`sf-filter ${filter === key ? "active" : ""}`}
            onClick={() => setFilter(key)}
            style={filter === key ? { borderColor: t.color } : {}}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Signal list */}
      <div className="sf-list">
        {filtered.length === 0 && (
          <div className="sf-empty">No signals</div>
        )}
        {filtered.map(sig => {
          const typeInfo = SIGNAL_TYPES[sig.type] || SIGNAL_TYPES.demand;
          return (
            <div
              key={sig.id}
              className={`sf-signal sf-signal-${sig.severity}`}
              onClick={() => {
                if (sig.location) onFlyTo?.(sig.location);
              }}
            >
              <div className="sf-signal-icon" style={{ background: typeInfo.color + "22", color: typeInfo.color }}>
                {typeInfo.icon}
              </div>
              <div className="sf-signal-body">
                <div className="sf-signal-title">{sig.title}</div>
                <div className="sf-signal-detail">{sig.detail}</div>
                <div className="sf-signal-meta">
                  <span className="sf-signal-time">{fmtAgo(Date.now() - sig.ts)}</span>
                  {sig.location && <span className="sf-signal-loc">Click to locate</span>}
                </div>
              </div>
              {/* AI dispatch button */}
              {sig.context && (
                <button
                  className="sf-dispatch-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDispatchAgent?.(sig.type === "constraint" ? "grid_connection" : "grid_study", sig.context);
                  }}
                  title="Dispatch AI analysis"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/><path d="M8 12h8M12 8v8"/>
                  </svg>
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
