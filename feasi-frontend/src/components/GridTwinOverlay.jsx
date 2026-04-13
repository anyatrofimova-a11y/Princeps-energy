/**
 * GridTwinOverlay — Drop-in 3D grid digital twin for any Mapbox GL map.
 *
 * Renders deck.gl ColumnLayer (substations), ArcLayer (power flow),
 * TextLayer (labels), GPU particles, and Google 3D Tiles as a MapboxOverlay
 * on the host map instance. Manages its own WebSocket feed and scenario state.
 *
 * Props:
 *   map       — mapbox-gl Map instance (required)
 *   enabled   — show/hide the overlay (default false)
 *   onInspect — callback({ type, data }) when user clicks substation/line
 */
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ColumnLayer, ArcLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";

const SCENARIOS = [
  { id: "baseline", label: "Baseline", color: "#D4A018" },
  { id: "leading_the_way", label: "Leading the Way", color: "#f5222d" },
  { id: "consumer_transformation", label: "Consumer Transform.", color: "#fa8c16" },
  { id: "system_transformation", label: "System Transform.", color: "#1890ff" },
  { id: "falling_short", label: "Falling Short", color: "#8c8c8c" },
];

const V_COLORS = { 400: [255,60,60], 275: [255,165,0], 132: [30,136,229], 66: [76,175,80], 33: [156,39,176], 11: [158,158,158] };
function vColor(kv) {
  if (kv >= 400) return V_COLORS[400];
  if (kv >= 275) return V_COLORS[275];
  if (kv >= 132) return V_COLORS[132];
  if (kv >= 66) return V_COLORS[66];
  if (kv >= 33) return V_COLORS[33];
  return V_COLORS[11];
}
function uColor(u) { return u >= 0.9 ? [245,34,45,220] : u >= 0.7 ? [250,140,22,200] : [82,196,26,180]; }
function fmtMw(v) { return v == null ? "--" : v >= 1000 ? `${(v/1000).toFixed(1)} GW` : `${Math.round(v)} MW`; }

/* ── Metrics strip (top bar) ─────────────────────────────────────────── */
function MetricsStrip({ gridState, scenario, scenarioYear, liveMode }) {
  if (!gridState) return null;
  const subs = gridState.substations || [];
  const totalDemand = subs.reduce((s, d) => s + (d.demand_mw || 0), 0);
  const totalGen = subs.reduce((s, d) => s + (d.generation_mw || 0), 0);
  const totalCap = subs.reduce((s, d) => s + (d.capacity_mw || 0), 0);
  const util = totalCap > 0 ? totalDemand / totalCap : 0;
  const freq = gridState.frequency ?? 50.0;
  const freqColor = Math.abs(freq - 50) > 0.05 ? "#f5222d" : "#52c41a";

  return (
    <div style={{
      position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)",
      display: "flex", gap: 16, padding: "6px 16px", borderRadius: 8,
      background: "rgba(15,17,23,0.88)", backdropFilter: "blur(8px)",
      border: "1px solid rgba(212,160,24,0.2)", zIndex: 10, fontSize: 12,
      fontFamily: "'IBM Plex Mono', monospace", color: "#E8E6E1",
    }}>
      <span style={{ color: freqColor, fontWeight: 700 }}>{freq.toFixed(2)} Hz</span>
      <span>Demand <strong>{fmtMw(totalDemand)}</strong></span>
      <span>Gen <strong>{fmtMw(totalGen)}</strong></span>
      <span>Cap <strong>{fmtMw(totalCap)}</strong></span>
      <span>Util <strong style={{ color: util > 0.85 ? "#f5222d" : util > 0.7 ? "#fa8c16" : "#52c41a" }}>{(util*100).toFixed(1)}%</strong></span>
      {!liveMode && <span style={{ color: "#D4A018" }}>{scenario} {scenarioYear}</span>}
    </div>
  );
}

/* ── Scenario controls (bottom bar) ──────────────────────────────────── */
function ScenarioBar({ scenario, setScenario, scenarioYear, setScenarioYear, liveMode, setLiveMode, particlesEnabled, setParticlesEnabled }) {
  return (
    <div style={{
      position: "absolute", bottom: 8, left: "50%", transform: "translateX(-50%)",
      display: "flex", gap: 8, padding: "6px 12px", borderRadius: 8,
      background: "rgba(15,17,23,0.88)", backdropFilter: "blur(8px)",
      border: "1px solid rgba(212,160,24,0.2)", zIndex: 10, fontSize: 11,
      fontFamily: "Inter, system-ui, sans-serif", color: "#E8E6E1", alignItems: "center",
    }}>
      <button onClick={() => setLiveMode(!liveMode)} style={{
        padding: "3px 8px", borderRadius: 4, border: "1px solid rgba(212,160,24,0.3)",
        background: liveMode ? "rgba(82,196,26,0.2)" : "transparent",
        color: liveMode ? "#52c41a" : "#9CA3AF", cursor: "pointer", fontSize: 11,
      }}>{liveMode ? "● LIVE" : "○ Scenario"}</button>

      {!liveMode && (
        <>
          <select value={scenario} onChange={e => setScenario(e.target.value)} style={{
            background: "rgba(15,17,23,0.9)", color: "#E8E6E1", border: "1px solid rgba(212,160,24,0.3)",
            borderRadius: 4, padding: "2px 6px", fontSize: 11, cursor: "pointer",
          }}>
            {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <input type="range" min={2024} max={2050} value={scenarioYear} onChange={e => setScenarioYear(+e.target.value)}
            style={{ width: 100 }} />
          <span style={{ minWidth: 32 }}>{scenarioYear}</span>
        </>
      )}

      <button onClick={() => setParticlesEnabled(!particlesEnabled)} style={{
        padding: "3px 8px", borderRadius: 4, border: "1px solid rgba(212,160,24,0.3)",
        background: particlesEnabled ? "rgba(212,160,24,0.15)" : "transparent",
        color: particlesEnabled ? "#D4A018" : "#666", cursor: "pointer", fontSize: 11,
      }}>Particles</button>
    </div>
  );
}

/* ── Inspector popup ─────────────────────────────────────────────────── */
function Inspector({ inspected, onClose }) {
  if (!inspected) return null;
  const d = inspected.data;
  return (
    <div style={{
      position: "absolute", top: 60, right: 12, width: 260, padding: 12, borderRadius: 8,
      background: "rgba(15,17,23,0.92)", border: "1px solid rgba(212,160,24,0.25)",
      backdropFilter: "blur(8px)", zIndex: 20, fontSize: 12, color: "#E8E6E1",
      fontFamily: "Inter, system-ui, sans-serif",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <strong>{d.name || "Transmission Line"}</strong>
        <span onClick={onClose} style={{ cursor: "pointer", color: "#666" }}>&times;</span>
      </div>
      {inspected.type === "substation" && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Demand</span><span>{fmtMw(d.demand_mw)}</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Generation</span><span>{fmtMw(d.generation_mw)}</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Capacity</span><span>{fmtMw(d.capacity_mw)}</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Voltage</span><span>{d.voltage_kv} kV</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Utilisation</span>
            <span style={{ color: d.utilisation >= 0.9 ? "#f5222d" : d.utilisation >= 0.7 ? "#fa8c16" : "#52c41a" }}>{(d.utilisation*100).toFixed(1)}%</span>
          </div>
        </>
      )}
      {inspected.type === "line" && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Flow</span><span>{fmtMw(d.flow_mw)}</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Loading</span><span>{d.loading_pct?.toFixed(1)}%</span></div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}><span style={{color:"#9CA3AF"}}>Voltage</span><span>{d.voltage_kv} kV</span></div>
          {d.congested && <div style={{ color: "#f5222d", fontWeight: 600, marginTop: 4 }}>CONGESTED</div>}
        </>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Main Overlay Component
   ═══════════════════════════════════════════════════════════════════════════ */
export default function GridTwinOverlay({ map, enabled = false, onInspect }) {
  const overlayRef = useRef(null);
  const wsRef = useRef(null);

  const [gridState, setGridState] = useState(null);
  const [scenario, setScenario] = useState("baseline");
  const [scenarioYear, setScenarioYear] = useState(2024);
  const [liveMode, setLiveMode] = useState(true);
  const [inspected, setInspected] = useState(null);
  const [animPhase, setAnimPhase] = useState(0);
  const [particlesEnabled, setParticlesEnabled] = useState(false); // off by default in merged view
  const [showLabels, setShowLabels] = useState(true);

  // Animation loop
  useEffect(() => {
    if (!enabled) return;
    let raf;
    const tick = () => { setAnimPhase(p => (p + 0.008) % 1); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [enabled]);

  // Initial fetch
  useEffect(() => {
    if (!enabled) return;
    (async () => {
      try {
        const data = await (await fetch("/api/grid-twin/state")).json();
        setGridState(data);
      } catch {}
    })();
  }, [enabled]);

  // WebSocket
  useEffect(() => {
    if (!enabled || !liveMode) { if (wsRef.current) { wsRef.current.close(); wsRef.current = null; } return; }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/grid-twin`);
    ws.onmessage = (e) => { try { setGridState(JSON.parse(e.data)); } catch {} };
    ws.onerror = () => ws.close();
    wsRef.current = ws;
    return () => { ws.close(); wsRef.current = null; };
  }, [enabled, liveMode]);

  // Scenario
  useEffect(() => {
    if (!enabled || liveMode || (scenario === "baseline" && scenarioYear === 2024)) return;
    let c = false;
    (async () => {
      try {
        const data = await (await fetch(`/api/grid-twin/scenario/${scenario}?year=${scenarioYear}`)).json();
        if (!c) setGridState(data);
      } catch {}
    })();
    return () => { c = true; };
  }, [enabled, scenario, scenarioYear, liveMode]);

  // Build deck.gl layers
  const deckLayers = useMemo(() => {
    if (!enabled || !gridState) return [];
    const layers = [];

    layers.push(new ColumnLayer({
      id: "gt-substation-columns",
      data: gridState.substations || [],
      getPosition: d => [d.lon, d.lat],
      getElevation: d => Math.max(d.demand_mw * 10, 500),
      getFillColor: d => uColor(d.utilisation),
      radius: 2500, elevationScale: 1, extruded: true, pickable: true, opacity: 0.85,
      material: { ambient: 0.4, diffuse: 0.6, shininess: 32, specularColor: [200, 200, 200] },
      onClick: ({ object }) => { if (object) { setInspected({ type: "substation", data: object }); onInspect?.({ type: "substation", data: object }); } },
      updateTriggers: { getElevation: [gridState.timestamp], getFillColor: [gridState.timestamp] },
    }));

    layers.push(new ScatterplotLayer({
      id: "gt-capacity-rings",
      data: gridState.substations || [],
      getPosition: d => [d.lon, d.lat],
      getRadius: d => 3000 + (d.capacity_mw || 0) * 3,
      getFillColor: [0, 0, 0, 0],
      getLineColor: d => [...vColor(d.voltage_kv || 33), 100],
      lineWidthMinPixels: 1, stroked: true, filled: false,
    }));

    layers.push(new ArcLayer({
      id: "gt-power-arcs",
      data: gridState.lines || [],
      getSourcePosition: d => d.from_coords,
      getTargetPosition: d => d.to_coords,
      getSourceColor: d => d.congested ? [245, 34, 45, 220] : [...vColor(d.voltage_kv || 132), 180],
      getTargetColor: d => d.congested ? [245, 34, 45, 220] : [...vColor(d.voltage_kv || 132), 140],
      getWidth: d => Math.max(2, Math.abs(d.flow_mw || 0) / 40),
      getHeight: d => 0.3 + (d.loading_pct || 0) / 200,
      greatCircle: false, numSegments: 50, pickable: true,
      onClick: ({ object }) => { if (object) { setInspected({ type: "line", data: object }); onInspect?.({ type: "line", data: object }); } },
      updateTriggers: { getSourceColor: [gridState.timestamp], getWidth: [gridState.timestamp] },
    }));

    if (showLabels) {
      layers.push(new TextLayer({
        id: "gt-substation-labels",
        data: gridState.substations || [],
        getPosition: d => [d.lon, d.lat],
        getText: d => `${d.name}\n${Math.round(d.demand_mw || 0)}/${d.capacity_mw || 0} MW`,
        getSize: 11, getColor: [255, 255, 255, 200],
        getTextAnchor: "middle", getAlignmentBaseline: "bottom",
        getPixelOffset: [0, -20],
        fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
        outlineColor: [0, 0, 0, 200], outlineWidth: 2, billboard: true,
      }));
    }

    return layers;
  }, [enabled, gridState, animPhase, particlesEnabled, showLabels]);

  // Attach/detach overlay
  useEffect(() => {
    if (!map) return;
    if (enabled && !overlayRef.current) {
      const overlay = new MapboxOverlay({ layers: [], interleaved: false });
      map.addControl(overlay);
      overlayRef.current = overlay;
    }
    if (!enabled && overlayRef.current) {
      try { map.removeControl(overlayRef.current); } catch {}
      overlayRef.current = null;
    }
    return () => {
      if (overlayRef.current) {
        try { map.removeControl(overlayRef.current); } catch {}
        overlayRef.current = null;
      }
    };
  }, [map, enabled]);

  // Sync layers
  useEffect(() => {
    if (overlayRef.current) overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  if (!enabled) return null;

  return (
    <>
      <MetricsStrip gridState={gridState} scenario={scenario} scenarioYear={scenarioYear} liveMode={liveMode} />
      <ScenarioBar
        scenario={scenario} setScenario={setScenario}
        scenarioYear={scenarioYear} setScenarioYear={setScenarioYear}
        liveMode={liveMode} setLiveMode={setLiveMode}
        particlesEnabled={particlesEnabled} setParticlesEnabled={setParticlesEnabled}
      />
      <Inspector inspected={inspected} onClose={() => setInspected(null)} />
    </>
  );
}
