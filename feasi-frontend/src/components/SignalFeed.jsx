/**
 * SignalFeed — Site-contextual energy intelligence signal stream.
 *
 * Right-side panel showing live energy signals. When a site/entity is
 * inspected, signals are filtered to that location. Real grid data
 * (demand, generation, frequency, constraints, congestion) is shown
 * separately from synthetic/simulated signals (weather, queue).
 *
 * Props:
 *   gridState       — current grid state
 *   inspected       — currently inspected entity { type, data }
 *   onFlyTo(loc)    — callback to fly camera to {lon, lat, zoom}
 *   onDispatchAgent(intent, context) — trigger AI analysis
 */
import React, { useState, useEffect, useRef, useCallback } from "react";

/* Signal types with icons and colors */
const SIGNAL_TYPES = {
  demand:     { icon: "D", color: "#D4A018", label: "Demand", source: "grid" },
  generation: { icon: "G", color: "#52c41a", label: "Generation", source: "grid" },
  frequency:  { icon: "F", color: "#1890ff", label: "Frequency", source: "grid" },
  constraint: { icon: "!", color: "#f5222d", label: "Constraint", source: "grid" },
  congestion: { icon: "C", color: "#fa8c16", label: "Congestion", source: "grid" },
  queue:      { icon: "Q", color: "#e040fb", label: "Queue", source: "sim" },
  weather:    { icon: "W", color: "#00b4d8", label: "Weather", source: "sim" },
  planning:   { icon: "P", color: "#8c8c8c", label: "Planning", source: "sim" },
  agent:      { icon: "A", color: "#D4A018", label: "AI Agent", source: "grid" },
};

const SOURCE_TABS = [
  { id: "all", label: "All" },
  { id: "grid", label: "Grid Data" },
  { id: "sim", label: "Simulated" },
  { id: "site", label: "This Site" },
];

function fmtAgo(ms) {
  if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
  return `${Math.floor(ms / 3600000)}h ago`;
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Math.round(v)} MW`;
}

/* Check if a signal is near an inspected entity */
function isNearSite(signal, inspected) {
  if (!inspected || !signal.location) return false;
  const d = inspected.data;
  if (!d) return false;
  const sLat = d.lat ?? d.from_coords?.[1];
  const sLon = d.lon ?? d.from_coords?.[0];
  if (sLat == null || sLon == null) return false;
  const dlat = Math.abs(signal.location.lat - sLat);
  const dlon = Math.abs(signal.location.lon - sLon);
  return dlat < 0.3 && dlon < 0.4; // ~30km radius
}

export default function SignalFeed({ gridState, inspected, onFlyTo, onDispatchAgent }) {
  const [signals, setSignals] = useState([]);
  const [sourceTab, setSourceTab] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
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
            title: `${l.from} \u2192 ${l.to} congested`,
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

  /* ── Periodic synthetic signals (weather, queue) — labelled as simulated ── */
  useEffect(() => {
    const interval = setInterval(() => {
      const ts = Date.now();
      if (Math.random() < 0.3) {
        setSignals(prev => [{
          id: signalIdRef.current++,
          type: "weather",
          severity: "info",
          title: `Solar irradiance ${(300 + Math.random() * 500).toFixed(0)} W/m\u00B2`,
          detail: `Cloud cover ${(Math.random() * 80).toFixed(0)}%, wind ${(3 + Math.random() * 12).toFixed(1)} m/s`,
          ts,
          simulated: true,
        }, ...prev].slice(0, 100));
      }
      if (Math.random() < 0.15) {
        const gsp = ["Bramley", "Beddington", "Manchester South", "Cambridge", "Norwich"][Math.floor(Math.random() * 5)];
        const gspCoords = { Bramley: [-1.06,51.33], Beddington: [-0.14,51.37], "Manchester South": [-2.24,53.47], Cambridge: [0.14,52.19], Norwich: [1.30,52.62] };
        const coords = gspCoords[gsp] || [0, 52];
        setSignals(prev => [{
          id: signalIdRef.current++,
          type: "queue",
          severity: "info",
          title: `ECR update: ${gsp}`,
          detail: `${Math.floor(2 + Math.random() * 8)} new applications, ${(10 + Math.random() * 50).toFixed(0)} MW queued`,
          location: { lon: coords[0], lat: coords[1] },
          ts,
          simulated: true,
        }, ...prev].slice(0, 100));
      }
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  /* ── Auto-switch to "This Site" when inspecting ── */
  useEffect(() => {
    if (inspected && sourceTab !== "site") {
      setSourceTab("site");
    }
  }, [inspected]);

  /* ── Filtering ── */
  const filtered = signals.filter(sig => {
    // Source tab filter
    if (sourceTab === "grid" && sig.simulated) return false;
    if (sourceTab === "sim" && !sig.simulated) return false;
    if (sourceTab === "site") {
      if (!inspected) return true; // show all if nothing inspected
      return isNearSite(sig, inspected) || !sig.location; // system-level + nearby
    }
    // Type filter
    if (typeFilter !== "all" && sig.type !== typeFilter) return false;
    return true;
  });

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
          <span className="sf-count">{filtered.length}</span>
          {inspected && sourceTab === "site" && (
            <span className="sf-site-indicator">
              {inspected.data?.name || inspected.type}
            </span>
          )}
        </div>
        <button className="sf-collapse-btn" onClick={() => setCollapsed(true)}>&lsaquo;</button>
      </div>

      {/* Source tabs — Grid Data / Simulated / This Site */}
      <div className="sf-source-tabs">
        {SOURCE_TABS.map(tab => (
          <button
            key={tab.id}
            className={`sf-source-tab ${sourceTab === tab.id ? "active" : ""}`}
            onClick={() => setSourceTab(tab.id)}
          >
            {tab.label}
            {tab.id === "site" && inspected && (
              <span className="sf-source-dot" />
            )}
          </button>
        ))}
      </div>

      {/* Type filters */}
      <div className="sf-filters">
        <button className={`sf-filter ${typeFilter === "all" ? "active" : ""}`} onClick={() => setTypeFilter("all")}>All</button>
        {Object.entries(SIGNAL_TYPES).map(([key, t]) => (
          <button key={key}
            className={`sf-filter ${typeFilter === key ? "active" : ""}`}
            onClick={() => setTypeFilter(key)}
            style={typeFilter === key ? { borderColor: t.color } : {}}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Signal list */}
      <div className="sf-list">
        {filtered.length === 0 && (
          <div className="sf-empty">
            {sourceTab === "site" && inspected
              ? `No signals near ${inspected.data?.name || "selected site"}`
              : "No signals"}
          </div>
        )}
        {filtered.map(sig => {
          const typeInfo = SIGNAL_TYPES[sig.type] || SIGNAL_TYPES.demand;
          return (
            <div
              key={sig.id}
              className={`sf-signal sf-signal-${sig.severity} ${sig.simulated ? "sf-signal-sim" : ""}`}
              onClick={() => {
                if (sig.location) onFlyTo?.(sig.location);
              }}
            >
              <div className="sf-signal-icon" style={{ background: typeInfo.color + "22", color: typeInfo.color }}>
                {typeInfo.icon}
              </div>
              <div className="sf-signal-body">
                <div className="sf-signal-title">
                  {sig.title}
                  {sig.simulated && <span className="sf-sim-tag">SIM</span>}
                </div>
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
