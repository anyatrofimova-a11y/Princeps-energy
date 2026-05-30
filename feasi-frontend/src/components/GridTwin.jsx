import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ColumnLayer, ArcLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { Tile3DLayer } from "@deck.gl/geo-layers";
import { Tiles3DLoader } from "@loaders.gl/3d-tiles";
import api from "../services/api";
import { createParticleLayer } from "./GridParticleFlow";
import GridCameraChoreography from "./GridCameraChoreography";
// OpenInfraMap overlay (BSD-3-Clause code, CC-BY 4.0 style — see footer).
import { attachOimOverlay, OIM_ATTRIBUTION } from "../lib/oimOverlay";

const GOOGLE_3D_TILES_KEY = import.meta.env.VITE_GOOGLE_MAPS_KEY || "";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

/* ── Constants ──────────────────────────────────────────────────────────── */
const SCENARIOS = [
  { id: "baseline", label: "Baseline", color: "#D4A018" },
  { id: "leading_the_way", label: "Leading the Way", color: "#f5222d" },
  { id: "consumer_transformation", label: "Consumer Transform.", color: "#fa8c16" },
  { id: "system_transformation", label: "System Transform.", color: "#1890ff" },
  { id: "falling_short", label: "Falling Short", color: "#8c8c8c" },
];

const VOLTAGE_COLORS = {
  400: [255, 60, 60],
  275: [255, 165, 0],
  132: [30, 136, 229],
  66: [76, 175, 80],
  33: [156, 39, 176],
  11: [158, 158, 158],
};

function voltageColor(kv) {
  if (kv >= 400) return VOLTAGE_COLORS[400];
  if (kv >= 275) return VOLTAGE_COLORS[275];
  if (kv >= 132) return VOLTAGE_COLORS[132];
  if (kv >= 66) return VOLTAGE_COLORS[66];
  if (kv >= 33) return VOLTAGE_COLORS[33];
  return VOLTAGE_COLORS[11];
}

function utilisationColor(u) {
  if (u >= 0.9) return [245, 34, 45, 220];
  if (u >= 0.7) return [250, 140, 22, 200];
  return [82, 196, 26, 180];
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Math.round(v)} MW`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   GridTwin — Full-screen 3D digital twin of the GB transmission grid
   deck.gl ColumnLayer + ArcLayer + ScatterplotLayer over Mapbox GL
   ═══════════════════════════════════════════════════════════════════════════ */
export default function GridTwin({ onClose }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const oimRef = useRef(null);          // attachOimOverlay handle
  const wsRef = useRef(null);
  const animFrameRef = useRef(0);

  /* ── State ── */
  const [gridState, setGridState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scenario, setScenario] = useState("baseline");
  const [scenarioYear, setScenarioYear] = useState(2024);
  const [liveMode, setLiveMode] = useState(true);
  const [inspected, setInspected] = useState(null);
  const [twinLayers, setTwinLayers] = useState({
    substations: true,
    lines: true,
    labels: true,
    generators: true,
  });
  const [animPhase, setAnimPhase] = useState(0);
  const [choreographyActive, setChoreographyActive] = useState(false);
  const [particlesEnabled, setParticlesEnabled] = useState(true);
  const [constraintHeatmap, setConstraintHeatmap] = useState(false);
  const [google3d, setGoogle3d] = useState(false);
  const [oimEnabled, setOimEnabled] = useState(true); // OIM power overlay (default ON per task #16)

  /* ── Animate flow arrows ── */
  const rafRef = useRef(null);
  useEffect(() => {
    const tick = () => {
      setAnimPhase(p => (p + 0.008) % 1);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  /* ── Fetch initial state ── */
  useEffect(() => {
    (async () => {
      try {
        const data = await (await fetch("/api/grid-twin/state")).json();
        setGridState(data);
      } catch (e) {
        console.warn("Grid twin initial fetch:", e);
      }
      setLoading(false);
    })();
  }, []);

  /* ── WebSocket live updates with reconnection ── */
  const wsRetryRef = useRef(0);
  const wsTimerRef = useRef(null);
  useEffect(() => {
    if (!liveMode) {
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      clearTimeout(wsTimerRef.current);
      wsRetryRef.current = 0;
      return;
    }
    let unmounted = false;
    const connect = () => {
      if (unmounted) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/grid-twin`);
      ws.onopen = () => { wsRetryRef.current = 0; };
      ws.onmessage = (e) => {
        try { setGridState(JSON.parse(e.data)); }
        catch (err) { console.warn("GridTwin WS parse error:", err); }
      };
      ws.onclose = () => {
        if (unmounted) return;
        const delay = Math.min(2000 * Math.pow(2, wsRetryRef.current), 30000);
        wsRetryRef.current += 1;
        console.info(`GridTwin WS closed, reconnecting in ${delay}ms (attempt ${wsRetryRef.current})`);
        wsTimerRef.current = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
      wsRef.current = ws;
    };
    connect();
    return () => {
      unmounted = true;
      clearTimeout(wsTimerRef.current);
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    };
  }, [liveMode]);

  /* ── Apply scenario projection ── */
  useEffect(() => {
    if (scenario === "baseline" && scenarioYear === 2024) return;
    if (liveMode) return;
    const controller = new AbortController();
    (async () => {
      try {
        const resp = await fetch(
          `/api/grid-twin/scenario/${scenario}?year=${scenarioYear}`,
          { signal: controller.signal }
        );
        const data = await resp.json();
        if (!controller.signal.aborted) setGridState(data);
      } catch (e) {
        if (e.name !== "AbortError") console.warn("Scenario fetch:", e);
      }
    })();
    return () => controller.abort();
  }, [scenario, scenarioYear, liveMode]);

  /* ── Build deck.gl layers ── */
  const deckLayers = useMemo(() => {
    if (!gridState) return [];
    const substations = gridState?.substations || [];
    const lines = gridState?.lines || [];
    try {
    const layers = [];

    // ── Substation columns (height = demand, color = utilisation) ──
    if (twinLayers.substations) {
      layers.push(new ColumnLayer({
        id: "gt-substation-columns",
        data: substations,
        getPosition: d => [d.lon, d.lat],
        getElevation: d => Math.max(d.demand_mw * 10, 500),
        getFillColor: d => utilisationColor(d.utilisation),
        radius: 2500,
        elevationScale: 1,
        extruded: true,
        pickable: true,
        opacity: 0.85,
        material: {
          ambient: 0.4,
          diffuse: 0.6,
          shininess: 32,
          specularColor: [200, 200, 200],
        },
        onClick: ({ object }) => object && setInspected({ type: "substation", data: object }),
        updateTriggers: {
          getElevation: [gridState.timestamp],
          getFillColor: [gridState.timestamp],
        },
      }));

      // Capacity ring (wireframe-style ring showing max capacity)
      layers.push(new ScatterplotLayer({
        id: "gt-capacity-rings",
        data: substations,
        getPosition: d => [d.lon, d.lat],
        getRadius: d => 3000 + d.capacity_mw * 3,
        getFillColor: [0, 0, 0, 0],
        getLineColor: d => [...voltageColor(d.voltage_kv), 100],
        lineWidthMinPixels: 1,
        stroked: true,
        filled: false,
        pickable: false,
      }));
    }

    // ── Power flow arcs (color = voltage, width = flow, height = loading) ──
    if (twinLayers.lines) {
      layers.push(new ArcLayer({
        id: "gt-power-arcs",
        data: lines,
        getSourcePosition: d => d.from_coords,
        getTargetPosition: d => d.to_coords,
        getSourceColor: d => d.congested ? [245, 34, 45, 220] : [...voltageColor(d.voltage_kv), 180],
        getTargetColor: d => d.congested ? [245, 34, 45, 220] : [...voltageColor(d.voltage_kv), 140],
        getWidth: d => Math.max(2, Math.abs(d.flow_mw) / 40),
        getHeight: d => 0.3 + d.loading_pct / 200,
        greatCircle: false,
        numSegments: 50,
        pickable: true,
        onClick: ({ object }) => object && setInspected({ type: "line", data: object }),
        updateTriggers: {
          getSourceColor: [gridState.timestamp],
          getTargetColor: [gridState.timestamp],
          getWidth: [gridState.timestamp],
          getHeight: [gridState.timestamp],
        },
      }));

      // GPU particle flow system — thousands of particles along transmission arcs
      if (particlesEnabled) {
        layers.push(createParticleLayer(lines, animPhase));
      } else {
        // Fallback: original dash-animated arc layer
        layers.push(new ArcLayer({
          id: "gt-flow-particles",
          data: lines.filter(l => Math.abs(l.flow_mw) > 10),
          getSourcePosition: d => d.flow_mw >= 0 ? d.from_coords : d.to_coords,
          getTargetPosition: d => d.flow_mw >= 0 ? d.to_coords : d.from_coords,
          getSourceColor: [255, 255, 255, 200],
          getTargetColor: [255, 255, 255, 40],
          getWidth: 1.5,
          getHeight: 0.35,
          greatCircle: false,
          numSegments: 50,
          getDashArray: [4, 12],
          dashJustified: true,
          dashGapPickable: false,
          extensions: [],
          updateTriggers: {
            getSourcePosition: [animPhase],
            getTargetPosition: [animPhase],
          },
        }));
      }
    }

    // ── Labels ──
    if (twinLayers.labels) {
      layers.push(new TextLayer({
        id: "gt-substation-labels",
        data: gridState.substations,
        getPosition: d => [d.lon, d.lat],
        getText: d => `${d.name}\n${Math.round(d.demand_mw)}/${d.capacity_mw} MW`,
        getSize: 11,
        getColor: [255, 255, 255, 200],
        getTextAnchor: "middle",
        getAlignmentBaseline: "bottom",
        getPixelOffset: [0, -20],
        fontFamily: "'IBM Plex Mono', monospace",
        fontWeight: 600,
        outlineColor: [0, 0, 0, 200],
        outlineWidth: 2,
        billboard: true,
      }));
    }

    // Google Photorealistic 3D Tiles (requires VITE_GOOGLE_MAPS_KEY)
    if (google3d && GOOGLE_3D_TILES_KEY) {
      layers.unshift(new Tile3DLayer({
        id: "gt-google-3d-tiles",
        data: `https://tile.googleapis.com/v1/3dtiles/root.json?key=${GOOGLE_3D_TILES_KEY}`,
        loader: Tiles3DLoader,
        loadOptions: {
          "3d-tiles": { loadGLTF: true },
          fetch: { headers: {} },
        },
        onTilesetLoad: (tileset) => {
          // Auto-fit view to loaded tileset
          if (tileset.boundingVolume) {
            const { center } = tileset.boundingVolume;
            if (center) {
              console.log("[GridTwin] Google 3D Tiles loaded, center:", center);
            }
          }
        },
        opacity: 0.9,
        pickable: false,
      }));
    }

    return layers;
    } catch (err) {
      console.error("GridTwin layer creation failed:", err);
      return [];
    }
  }, [gridState, twinLayers, animPhase, particlesEnabled, google3d]);

  /* ── Init Mapbox + deck.gl overlay ── */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-1.5, 53.0], // Centre of GB
      zoom: 6,
      pitch: 55,
      bearing: -10,
      antialias: true,
    });

    map.on("load", () => {
      // 3D terrain
      map.addSource("mapbox-dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
      map.setTerrain({ source: "mapbox-dem", exaggeration: 2.5 });

      // Atmospheric sky
      map.addLayer({
        id: "sky",
        type: "sky",
        paint: {
          "sky-type": "atmosphere",
          "sky-atmosphere-sun": [0, 45],
          "sky-atmosphere-sun-intensity": 5,
        },
      });

      // 3D buildings
      const labelLayer = map.getStyle().layers.find(l => l.type === "symbol" && l.layout?.["text-field"]);
      map.addLayer({
        id: "3d-buildings",
        source: "composite",
        "source-layer": "building",
        filter: ["==", "extrude", "true"],
        type: "fill-extrusion",
        minzoom: 12,
        paint: {
          "fill-extrusion-color": "#1a1a2e",
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": ["get", "min_height"],
          "fill-extrusion-opacity": 0.6,
        },
      }, labelLayer?.id);

      // Constraint heatmap source + layers
      map.addSource("gt-constraints", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "gt-constraint-heat",
        type: "fill",
        source: "gt-constraints",
        paint: {
          "fill-color": [
            "interpolate", ["linear"],
            ["coalesce", ["get", "constraint_prob"], 0],
            0, "rgba(76,175,80,0.05)",
            0.3, "rgba(255,152,0,0.25)",
            0.6, "rgba(244,67,54,0.4)",
            1.0, "rgba(183,28,28,0.6)",
          ],
          "fill-opacity": 0.7,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "gt-constraint-pulse",
        type: "line",
        source: "gt-constraints",
        paint: {
          "line-color": [
            "match", ["get", "risk_level"],
            "HIGH", "#f44336", "MEDIUM", "#ff9800", "LOW", "#4caf50", "#888",
          ],
          "line-width": 3,
          "line-dasharray": [2, 2],
          "line-opacity": 0.8,
        },
        layout: { visibility: "none" },
      });

      // deck.gl overlay
      const overlay = new MapboxOverlay({ layers: [] });
      map.addControl(overlay);
      overlayRef.current = overlay;

      // OpenInfraMap power overlay (toggleable; default ON per task #16).
      // BSD-3-Clause code + CC-BY 4.0 style — attribution shown in footer.
      try {
        if (oimEnabled) {
          oimRef.current = attachOimOverlay(map);
        }
        // Register CC-BY 4.0 attribution against an empty source so it shows
        // in the AttributionControl alongside Mapbox's own credits.
        if (!map.getSource("oim-attribution")) {
          map.addSource("oim-attribution", {
            type: "geojson",
            data: { type: "FeatureCollection", features: [] },
            attribution: OIM_ATTRIBUTION,
          });
        }
      } catch (e) {
        console.warn("[GridTwin] OIM overlay attach failed:", e);
      }
    });

    mapRef.current = map;

    return () => {
      try { oimRef.current?.detach?.(); } catch {}
      oimRef.current = null;
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── OIM overlay toggle ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    if (oimEnabled && !oimRef.current) {
      try { oimRef.current = attachOimOverlay(map); } catch (e) {
        console.warn("[GridTwin] OIM toggle on failed:", e);
      }
    } else if (!oimEnabled && oimRef.current) {
      try { oimRef.current.detach(); } catch {}
      oimRef.current = null;
    }
  }, [oimEnabled]);

  /* ── Sync deck.gl layers ── */
  useEffect(() => {
    if (overlayRef.current) {
      overlayRef.current.setProps({ layers: deckLayers });
    }
  }, [deckLayers]);

  /* ── Constraint heatmap toggle ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const vis = constraintHeatmap ? "visible" : "none";
    if (map.getLayer("gt-constraint-heat")) map.setLayoutProperty("gt-constraint-heat", "visibility", vis);
    if (map.getLayer("gt-constraint-pulse")) map.setLayoutProperty("gt-constraint-pulse", "visibility", vis);

    if (constraintHeatmap) {
      fetch("/api/grid/constraints?hours_ahead=48")
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) return;
          const src = map.getSource("gt-constraints");
          if (src) src.setData({ type: "FeatureCollection", features: data.features || [] });
        })
        .catch(() => {});
    }
  }, [constraintHeatmap]);

  /* ── System metrics bar ── */
  const sys = gridState?.system;

  return (
    <div className="gt-overlay">
      {/* ── Top toolbar ── */}
      <div className="gt-toolbar">
        <div className="gt-toolbar-left">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
            <line x1="12" y1="22.08" x2="12" y2="12"/>
          </svg>
          <span className="gt-title">Grid Digital Twin</span>
          {sys && (
            <span className="gt-freq" style={{ color: Math.abs(sys.frequency_hz - 50) > 0.05 ? "#f5222d" : "#52c41a" }}>
              {sys.frequency_hz.toFixed(3)} Hz
            </span>
          )}
        </div>

        <div className="gt-toolbar-center">
          {/* Live toggle */}
          <button
            className={`gt-pill ${liveMode ? "active" : ""}`}
            onClick={() => setLiveMode(!liveMode)}
          >
            <span className={`gt-live-dot ${liveMode ? "pulsing" : ""}`} />
            {liveMode ? "LIVE" : "STATIC"}
          </button>

          {/* Scenario selector */}
          <select
            className="gt-select"
            value={scenario}
            onChange={e => { setScenario(e.target.value); setLiveMode(false); }}
          >
            {SCENARIOS.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>

          {/* Year slider */}
          {!liveMode && (
            <div className="gt-year-slider">
              <input
                type="range" min={2024} max={2050} value={scenarioYear}
                onChange={e => setScenarioYear(Number(e.target.value))}
                className="gt-slider"
              />
              <span className="gt-year-label">{scenarioYear}</span>
            </div>
          )}
        </div>

        <div className="gt-toolbar-right">
          {/* Layer toggles */}
          {Object.entries(twinLayers).map(([key, on]) => (
            <button key={key}
              className={`gt-layer-btn ${on ? "active" : ""}`}
              onClick={() => setTwinLayers(prev => ({ ...prev, [key]: !prev[key] }))}
              title={key}
            >
              {key[0].toUpperCase()}
            </button>
          ))}

          {/* Particles toggle */}
          <button
            className={`gt-layer-btn ${particlesEnabled ? "active" : ""}`}
            onClick={() => setParticlesEnabled(!particlesEnabled)}
            title="GPU Particle Flow"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="4" cy="12" r="2"/><circle cx="12" cy="6" r="2"/><circle cx="20" cy="12" r="2"/><circle cx="12" cy="18" r="2"/>
            </svg>
          </button>

          {/* Constraint heatmap */}
          <button
            className={`gt-layer-btn ${constraintHeatmap ? "active" : ""}`}
            onClick={() => setConstraintHeatmap(!constraintHeatmap)}
            title="Constraint Heatmap"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/>
              <path d="M8 12l4 4 4-4"/>
            </svg>
          </button>

          {/* Google 3D Tiles */}
          {GOOGLE_3D_TILES_KEY && (
            <button
              className={`gt-layer-btn ${google3d ? "active" : ""}`}
              onClick={() => setGoogle3d(!google3d)}
              title="Google Photorealistic 3D"
              style={google3d ? { background: "#4285f4", color: "#fff" } : {}}
            >
              3D
            </button>
          )}

          {/* Grid layer (OpenInfraMap) — task #16. */}
          <button
            className={`gt-layer-btn ${oimEnabled ? "active" : ""}`}
            onClick={() => setOimEnabled((v) => !v)}
            title="Grid layer (OpenInfraMap voltage-banded power lines, substations, plants)"
            style={oimEnabled ? { background: "#D4A018", color: "#000" } : {}}
          >
            Grid
          </button>

          {/* AI Tour */}
          <button
            className={`gt-layer-btn ${choreographyActive ? "active" : ""}`}
            onClick={() => setChoreographyActive(!choreographyActive)}
            title="AI Flythrough Tour"
            style={choreographyActive ? { background: "#D4A018", color: "#000" } : {}}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
          </button>

          <div style={{ width: 1, height: 16, background: "rgba(255,255,255,0.12)" }} />

          {/* View presets */}
          <button className="gt-view-btn" title="Top-down view"
            onClick={() => mapRef.current?.flyTo({ pitch: 0, bearing: 0, duration: 800 })}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="12" x2="16" y2="12"/>
            </svg>
          </button>
          <button className="gt-view-btn" title="3D perspective"
            onClick={() => mapRef.current?.flyTo({ pitch: 55, bearing: -10, duration: 800 })}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8"/>
            </svg>
          </button>

          <button className="gt-close" onClick={onClose}>&times;</button>
        </div>
      </div>

      {/* ── System metrics strip ── */}
      {sys && (
        <div className="gt-metrics">
          <div className="gt-metric">
            <span className="gt-metric-label">Demand</span>
            <span className="gt-metric-value">{fmtMw(sys.total_demand_mw)}</span>
          </div>
          <div className="gt-metric">
            <span className="gt-metric-label">Generation</span>
            <span className="gt-metric-value" style={{ color: "#52c41a" }}>{fmtMw(sys.total_generation_mw)}</span>
          </div>
          <div className="gt-metric">
            <span className="gt-metric-label">Capacity</span>
            <span className="gt-metric-value">{fmtMw(sys.total_capacity_mw)}</span>
          </div>
          <div className="gt-metric">
            <span className="gt-metric-label">Utilisation</span>
            <span className="gt-metric-value" style={{
              color: sys.system_utilisation >= 0.85 ? "#f5222d" : sys.system_utilisation >= 0.65 ? "#fa8c16" : "#52c41a"
            }}>
              {(sys.system_utilisation * 100).toFixed(1)}%
            </span>
          </div>
          {gridState?.scenario && (
            <div className="gt-metric gt-metric-scenario">
              <span className="gt-metric-label">Scenario</span>
              <span className="gt-metric-value">{gridState.scenario.name.replace(/_/g, " ")} {gridState.scenario.year}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Map container ── */}
      <div ref={containerRef} className="gt-map" />

      {/* ── Loading overlay ── */}
      {loading && (
        <div className="gt-loading">
          <div className="gt-loading-spinner" />
          Initialising grid twin...
        </div>
      )}

      {/* ── Inspector panel ── */}
      {inspected && (
        <div className="gt-inspector">
          <div className="gt-inspector-header">
            <span className="gt-inspector-type">{inspected.type === "substation" ? "Substation" : "Transmission Line"}</span>
            <button className="gt-inspector-close" onClick={() => setInspected(null)}>&times;</button>
          </div>

          {inspected.type === "substation" && (() => {
            const s = inspected.data;
            return (
              <div className="gt-inspector-body">
                <div className="gt-inspector-name">{s.name}</div>
                <div className="gt-inspector-id">{s.id} &middot; {s.voltage_kv} kV &middot; {s.type}</div>
                <div className="gt-inspector-grid">
                  <div><span className="gt-insp-label">Demand</span><span className="gt-insp-value">{fmtMw(s.demand_mw)}</span></div>
                  <div><span className="gt-insp-label">Generation</span><span className="gt-insp-value">{fmtMw(s.generation_mw)}</span></div>
                  <div><span className="gt-insp-label">Capacity</span><span className="gt-insp-value">{fmtMw(s.capacity_mw)}</span></div>
                  <div><span className="gt-insp-label">Headroom</span><span className="gt-insp-value">{fmtMw(s.headroom_mw)}</span></div>
                </div>
                <div className="gt-insp-util-bar">
                  <div className="gt-insp-util-fill" style={{
                    width: `${Math.min(s.utilisation * 100, 100)}%`,
                    background: s.utilisation >= 0.9 ? "#f5222d" : s.utilisation >= 0.7 ? "#fa8c16" : "#52c41a",
                  }} />
                </div>
                <div className="gt-insp-util-text">{(s.utilisation * 100).toFixed(1)}% utilisation</div>
              </div>
            );
          })()}

          {inspected.type === "line" && (() => {
            const l = inspected.data;
            return (
              <div className="gt-inspector-body">
                <div className="gt-inspector-name">{l.from} &rarr; {l.to}</div>
                <div className="gt-inspector-id">{l.voltage_kv} kV &middot; Rating: {fmtMw(l.rating_mw)}</div>
                <div className="gt-inspector-grid">
                  <div><span className="gt-insp-label">Flow</span><span className="gt-insp-value">{fmtMw(Math.abs(l.flow_mw))}</span></div>
                  <div><span className="gt-insp-label">Loading</span><span className="gt-insp-value" style={{ color: l.congested ? "#f5222d" : "inherit" }}>{l.loading_pct.toFixed(1)}%</span></div>
                </div>
                {l.congested && <div className="gt-insp-alert">Congested — loading &gt; 80%</div>}
              </div>
            );
          })()}
        </div>
      )}

      {/* ── AI Camera Choreography ── */}
      <GridCameraChoreography
        map={mapRef.current}
        gridState={gridState}
        active={choreographyActive}
        onStop={() => setChoreographyActive(false)}
      />

      {/* ── Legend ── */}
      <div className="gt-legend">
        <div className="gt-legend-title">Voltage</div>
        {Object.entries(VOLTAGE_COLORS).map(([kv, rgb]) => (
          <div key={kv} className="gt-legend-item">
            <span className="gt-legend-dot" style={{ background: `rgb(${rgb.join(",")})` }} />
            <span>{kv} kV</span>
          </div>
        ))}
        <div className="gt-legend-title" style={{ marginTop: 8 }}>Utilisation</div>
        <div className="gt-legend-item"><span className="gt-legend-dot" style={{ background: "#52c41a" }} /><span>&lt; 70%</span></div>
        <div className="gt-legend-item"><span className="gt-legend-dot" style={{ background: "#fa8c16" }} /><span>70-90%</span></div>
        <div className="gt-legend-item"><span className="gt-legend-dot" style={{ background: "#f5222d" }} /><span>&gt; 90%</span></div>
      </div>

      {/* OIM attribution footer (mandatory under CC-BY 4.0). */}
      <div
        style={{
          position: "absolute", bottom: 6, left: 8, zIndex: 5,
          fontSize: 10, lineHeight: 1.3, color: "rgba(255,255,255,0.78)",
          textShadow: "0 1px 2px rgba(0,0,0,0.6)", pointerEvents: "auto",
        }}
      >
        © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer"
             style={{ color: "rgba(255,255,255,0.9)", textDecoration: "underline" }}>OpenStreetMap contributors</a>
        {" · "}
        Open Infrastructure Map style (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer"
             style={{ color: "rgba(255,255,255,0.9)", textDecoration: "underline" }}>CC-BY 4.0</a>)
      </div>
    </div>
  );
}
