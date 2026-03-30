/**
 * GridTwinCesium — Full-screen 3D digital twin on CesiumJS globe.
 *
 * Replaces Mapbox GL + deck.gl with native CesiumJS for:
 *   - Photorealistic terrain (Cesium World Terrain)
 *   - Google 3D Tiles / OSM Buildings
 *   - NASA GIBS satellite imagery overlays
 *   - Substation cylinders (height = demand, color = utilisation)
 *   - Transmission arc polylines (color = voltage, width = loading)
 *   - Animated particle flow along arcs
 *   - Constraint heatmap (GeoJSON)
 *   - AI camera choreography (flyTo stops)
 *   - NESO FES scenario projections (2024-2050)
 *   - Live WebSocket grid state updates
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import * as Cesium from "cesium";
import CesiumGlobe from "./CesiumGlobe";
import TimelineScrubber from "./TimelineScrubber";
import SignalFeed from "./SignalFeed";
import AgentDispatcher from "./AgentDispatcher";
import TwinSiteFinder from "./TwinSiteFinder";
import api from "../services/api";
import {
  GIBS_LAYERS,
  voltageColorCesium,
  utilisationColorCesium,
  ASSET_STYLES,
  createDEFRALidarHillshade,
} from "../lib/cesium-config";

/* ── Constants ──────────────────────────────────────────────────────────── */
const SCENARIOS = [
  { id: "baseline", label: "Baseline", color: "#D4A018" },
  { id: "leading_the_way", label: "Leading the Way", color: "#f5222d" },
  { id: "consumer_transformation", label: "Consumer Transform.", color: "#fa8c16" },
  { id: "system_transformation", label: "System Transform.", color: "#1890ff" },
  { id: "falling_short", label: "Falling Short", color: "#8c8c8c" },
];

const VOLTAGE_COLORS_RGB = {
  400: [255, 60, 60],
  275: [255, 165, 0],
  132: [30, 136, 229],
  66: [76, 175, 80],
  33: [156, 39, 176],
  11: [158, 158, 158],
};

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Math.round(v)} MW`;
}

/* ── Easing ──────────────────────────────────────────────────────────────── */
const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/* ═══════════════════════════════════════════════════════════════════════════
   GridTwinCesium Component
   ═══════════════════════════════════════════════════════════════════════════ */
export default function GridTwinCesium({ onClose }) {
  const viewerRef = useRef(null);
  const entitiesRef = useRef(null);
  const particleEntitiesRef = useRef(null);
  const wsRef = useRef(null);
  const animFrameRef = useRef(null);

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
    particles: true,
  });
  const [showBuildings, setShowBuildings] = useState(false);
  const [show3DTiles, setShow3DTiles] = useState(!!import.meta.env.VITE_GOOGLE_MAPS_KEY);
  const [showGIBS, setShowGIBS] = useState([]);
  const [gibsDate, setGibsDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [constraintHeatmap, setConstraintHeatmap] = useState(false);
  const [choreographyActive, setChoreographyActive] = useState(false);
  const [choreoNarration, setChoreoNarration] = useState(null);
  const [choreoStops, setChoreoStops] = useState([]);
  const [choreoIdx, setChoreoIdx] = useState(0);

  /* ── Agent dispatcher state ── */
  const [agentDispatch, setAgentDispatch] = useState(null);
  const [contextMenu, setContextMenu] = useState(null);
  const [timelineTime, setTimelineTime] = useState(null);
  const [timelineMode, setTimelineMode] = useState("live");
  const [showLidar, setShowLidar] = useState(false);
  const [showAssets, setShowAssets] = useState(true);
  const lidarLayerRef = useRef(null);
  const assetDsRef = useRef(null);

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

  /* ── WebSocket live updates ── */
  useEffect(() => {
    if (!liveMode) {
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/grid-twin`);
    ws.onmessage = (e) => {
      try { setGridState(JSON.parse(e.data)); } catch {}
    };
    ws.onerror = () => ws.close();
    wsRef.current = ws;
    return () => { ws.close(); wsRef.current = null; };
  }, [liveMode]);

  /* ── Apply scenario projection ── */
  useEffect(() => {
    if (scenario === "baseline" && scenarioYear === 2024) return;
    if (liveMode) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await (await fetch(
          `/api/grid-twin/scenario/${scenario}?year=${scenarioYear}`
        )).json();
        if (!cancelled) setGridState(data);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [scenario, scenarioYear, liveMode]);

  /* ── Cesium viewer ready callback ── */
  const handleViewerReady = useCallback((viewer) => {
    viewerRef.current = viewer;

    // Create entity collections
    entitiesRef.current = new Cesium.CustomDataSource("grid-entities");
    viewer.dataSources.add(entitiesRef.current);

    particleEntitiesRef.current = new Cesium.CustomDataSource("grid-particles");
    viewer.dataSources.add(particleEntitiesRef.current);

    // Enable click picking
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click) => {
      const picked = viewer.scene.pick(click.position);
      if (picked && picked.id && picked.id._princepsData) {
        setInspected(picked.id._princepsData);
        setContextMenu(null);
      } else {
        setInspected(null);
        setContextMenu(null);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    // Energy assets data source
    const assetDs = new Cesium.CustomDataSource("energy-assets");
    viewer.dataSources.add(assetDs);
    assetDsRef.current = assetDs;

    // Load ALL energy assets from backend
    fetch("/api/analytics/energy-assets")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.features || !assetDsRef.current) return;
        for (const f of data.features) {
          const [lon, lat] = f.geometry.coordinates;
          const p = f.properties;
          const style = ASSET_STYLES[p.asset_type] || { color: "#888", icon: "?", scale: 0.8 };
          const capMw = p.capacity_mw || 0;

          const entity = assetDsRef.current.entities.add({
            position: Cesium.Cartesian3.fromDegrees(lon, lat, 20),
            point: {
              pixelSize: 6 + Math.min(capMw, 500) / 50,
              color: Cesium.Color.fromCssColorString(style.color).withAlpha(0.9),
              outlineColor: Cesium.Color.WHITE.withAlpha(0.6),
              outlineWidth: 1.5,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              scaleByDistance: new Cesium.NearFarScalar(5e3, 1.2, 1e6, 0.25),
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: `${p.name || p.asset_type}\n${capMw > 0 ? capMw + " MW" : ""}`,
              font: "10px 'DM Sans', sans-serif",
              fillColor: Cesium.Color.WHITE.withAlpha(0.9),
              outlineColor: Cesium.Color.BLACK.withAlpha(0.7),
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.TOP,
              pixelOffset: new Cesium.Cartesian2(0, 8),
              scaleByDistance: new Cesium.NearFarScalar(1e4, 1.0, 5e5, 0),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
          entity._princepsData = {
            type: "asset",
            data: {
              name: p.name || "Unknown",
              asset_type: p.asset_type,
              capacity_mw: capMw,
              dno: p.dno || "",
              operator: p.operator || "",
              status: p.status || "operational",
              fuel: p.fuel || p.asset_type,
              lat, lon,
              echelon: p.echelon || "",
              color: style.color,
            },
          };
        }
        console.log(`[Twin] Loaded ${data.features.length} energy assets`);
      })
      .catch(e => console.warn("Asset load:", e));

    // Enable mouse rotate: right-drag rotates (Cesium default), make middle-click also rotate
    viewer.scene.screenSpaceCameraController.tiltEventTypes = [
      Cesium.CameraEventType.RIGHT_DRAG,
      Cesium.CameraEventType.MIDDLE_DRAG,
      { eventType: Cesium.CameraEventType.LEFT_DRAG, modifier: Cesium.KeyboardEventModifier.CTRL },
    ];
    viewer.scene.screenSpaceCameraController.zoomEventTypes = [
      Cesium.CameraEventType.WHEEL,
      Cesium.CameraEventType.PINCH,
    ];

    // Right-click for AI agent dispatch context menu
    handler.setInputAction((click) => {
      const picked = viewer.scene.pick(click.position);
      if (picked && picked.id && picked.id._princepsData) {
        setContextMenu({
          x: click.position.x,
          y: click.position.y,
          data: picked.id._princepsData,
        });
      } else {
        setContextMenu(null);
      }
    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
  }, []);

  /* ── Update Cesium entities when grid state changes ── */
  useEffect(() => {
    const ds = entitiesRef.current;
    if (!ds || !gridState) return;

    ds.entities.removeAll();

    // ── Substation cylinders ──
    if (twinLayers.substations) {
      for (const s of gridState.substations || []) {
        const height = Math.max(s.demand_mw * 20, 500); // meters
        const utilColor = utilisationColorCesium(s.utilisation);
        const vColor = voltageColorCesium(s.voltage_kv);

        const entity = ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat, height / 2),
          cylinder: {
            length: height,
            topRadius: 400,
            bottomRadius: 600,
            material: utilColor.withAlpha(0.85),
            outline: true,
            outlineColor: utilColor.withAlpha(0.4),
            outlineWidth: 1,
            shadows: Cesium.ShadowMode.DISABLED,
          },
          label: twinLayers.labels ? {
            text: `${s.name}\n${Math.round(s.demand_mw)}/${s.capacity_mw} MW`,
            font: "12px 'JetBrains Mono', monospace",
            fillColor: Cesium.Color.WHITE.withAlpha(0.9),
            outlineColor: Cesium.Color.BLACK.withAlpha(0.8),
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -10),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new Cesium.NearFarScalar(1e4, 1.0, 2e6, 0.3),
          } : undefined,
        });

        // Store data for click inspection
        entity._princepsData = { type: "substation", data: s };

        // Capacity ring on ground
        ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
          ellipse: {
            semiMajorAxis: 3000 + s.capacity_mw * 3,
            semiMinorAxis: 3000 + s.capacity_mw * 3,
            fill: false,
            outline: true,
            outlineColor: vColor.withAlpha(0.4),
            outlineWidth: 2,
            height: 10,
          },
        });
      }
    }

    // ── Transmission line polylines ──
    if (twinLayers.lines) {
      for (const l of gridState.lines || []) {
        const vColor = voltageColorCesium(l.voltage_kv);
        const lineColor = l.congested
          ? Cesium.Color.fromCssColorString("rgba(245,34,45,0.86)")
          : vColor.withAlpha(0.7);
        const width = Math.max(2, Math.abs(l.flow_mw) / 30);
        const arcHeight = 5000 + (l.loading_pct || 0) * 200;

        // Build arc positions (parabolic)
        const arcPositions = [];
        const segments = 40;
        for (let i = 0; i <= segments; i++) {
          const t = i / segments;
          const lon = l.from_coords[0] + (l.to_coords[0] - l.from_coords[0]) * t;
          const lat = l.from_coords[1] + (l.to_coords[1] - l.from_coords[1]) * t;
          const elev = arcHeight * 4 * t * (1 - t);
          arcPositions.push(lon, lat, elev);
        }

        const entity = ds.entities.add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(arcPositions),
            width: width,
            material: new Cesium.PolylineGlowMaterialProperty({
              glowPower: 0.15,
              color: lineColor,
            }),
            clampToGround: false,
          },
        });

        entity._princepsData = { type: "line", data: l };
      }
    }
  }, [gridState, twinLayers]);

  /* ── Animated particles along transmission arcs ── */
  useEffect(() => {
    const ds = particleEntitiesRef.current;
    const viewer = viewerRef.current;
    if (!ds || !viewer || !gridState || !twinLayers.particles) {
      if (ds) ds.entities.removeAll();
      return;
    }

    let running = true;

    function animate() {
      if (!running || !viewerRef.current || viewerRef.current.isDestroyed()) return;

      ds.entities.removeAll();
      const phase = (Date.now() % 10000) / 10000;

      for (const line of gridState.lines || []) {
        const flow = Math.abs(line.flow_mw || 0);
        if (flow < 5) continue;

        const from = line.flow_mw >= 0 ? line.from_coords : line.to_coords;
        const to = line.flow_mw >= 0 ? line.to_coords : line.from_coords;
        const arcH = 5000 + (line.loading_pct || 0) * 200;
        const vColor = voltageColorCesium(line.voltage_kv);
        const count = Math.min(12, Math.max(3, Math.floor(flow / 20)));
        const speed = 0.3 + flow / 500;

        for (let i = 0; i < count; i++) {
          const t = ((i / count + phase * speed) % 1);
          const lon = from[0] + (to[0] - from[0]) * t;
          const lat = from[1] + (to[1] - from[1]) * t;
          const elev = arcH * 4 * t * (1 - t);
          const edgeFade = Math.min(t * 6, (1 - t) * 6, 1);
          const size = (40 + flow * 0.2) * (0.6 + 0.4 * Math.sin(t * Math.PI));

          ds.entities.add({
            position: Cesium.Cartesian3.fromDegrees(lon, lat, elev),
            point: {
              pixelSize: Math.max(2, size / 15),
              color: vColor.withAlpha(0.8 * edgeFade),
              outlineColor: vColor.withAlpha(0.3 * edgeFade),
              outlineWidth: 1,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              scaleByDistance: new Cesium.NearFarScalar(1e4, 1.5, 2e6, 0.4),
            },
          });
        }
      }

      animFrameRef.current = requestAnimationFrame(animate);
    }

    animate();

    return () => {
      running = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      ds.entities.removeAll();
    };
  }, [gridState, twinLayers.particles]);

  /* ── Constraint heatmap ── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    // Remove existing constraint data source
    const existing = viewer.dataSources.getByName("constraints");
    if (existing.length) viewer.dataSources.remove(existing[0], true);

    if (!constraintHeatmap) return;

    fetch("/api/grid/constraints?hours_ahead=48")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data || !data.features) return;
        const ds = Cesium.GeoJsonDataSource.load(data, {
          stroke: Cesium.Color.ORANGE.withAlpha(0.8),
          fill: Cesium.Color.RED.withAlpha(0.25),
          strokeWidth: 3,
          clampToGround: true,
        });
        return ds;
      })
      .then(ds => {
        if (ds && viewerRef.current && !viewerRef.current.isDestroyed()) {
          ds.name = "constraints";
          viewerRef.current.dataSources.add(ds);
        }
      })
      .catch(() => {});
  }, [constraintHeatmap]);

  /* ── AI Camera Choreography ── */
  useEffect(() => {
    if (!choreographyActive || !gridState) return;

    const stops = [];

    // Overview
    stops.push({
      type: "overview", label: "GB Transmission Grid — Live Overview",
      sublabel: `${(gridState.system?.total_demand_mw / 1000).toFixed(1)} GW demand`,
      lon: -1.5, lat: 53.5, height: 1200000, heading: 350, pitch: -55,
      duration: 5, color: "#D4A018",
    });

    // High-utilisation substations
    for (const s of (gridState.substations || []).filter(s => s.utilisation >= 0.85).slice(0, 4)) {
      stops.push({
        type: "substation", label: `${s.name} — ${(s.utilisation * 100).toFixed(0)}% utilisation`,
        sublabel: `${Math.round(s.demand_mw)} MW demand, ${Math.round(s.headroom_mw)} MW headroom`,
        lon: s.lon, lat: s.lat, height: 50000, heading: -30, pitch: -35,
        duration: 4, color: s.utilisation >= 0.95 ? "#f5222d" : "#fa8c16",
      });
    }

    // Congested lines
    for (const l of (gridState.lines || []).filter(l => l.loading_pct > 75).slice(0, 3)) {
      const midLon = (l.from_coords[0] + l.to_coords[0]) / 2;
      const midLat = (l.from_coords[1] + l.to_coords[1]) / 2;
      stops.push({
        type: "line", label: `${l.from} → ${l.to} — ${l.loading_pct.toFixed(0)}% loaded`,
        sublabel: `${Math.abs(l.flow_mw).toFixed(0)} MW on ${l.voltage_kv} kV`,
        lon: midLon, lat: midLat, height: 80000, heading: 0, pitch: -40,
        duration: 3.5, color: l.loading_pct > 90 ? "#f5222d" : "#fa8c16",
      });
    }

    setChoreoStops(stops);
    setChoreoIdx(0);
  }, [choreographyActive, gridState]);

  useEffect(() => {
    if (!choreographyActive || !choreoStops.length) return;
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const stop = choreoStops[choreoIdx];
    if (!stop) {
      setChoreographyActive(false);
      setChoreoNarration(null);
      return;
    }

    setChoreoNarration(stop);

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(stop.lon, stop.lat, stop.height),
      orientation: {
        heading: Cesium.Math.toRadians(stop.heading),
        pitch: Cesium.Math.toRadians(stop.pitch),
        roll: 0,
      },
      duration: stop.duration,
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
    });

    const timer = setTimeout(() => {
      if (choreoIdx < choreoStops.length - 1) {
        setChoreoIdx(i => i + 1);
      } else {
        setChoreographyActive(false);
        setChoreoNarration(null);
      }
    }, (stop.duration + 2) * 1000);

    return () => clearTimeout(timer);
  }, [choreographyActive, choreoStops, choreoIdx]);

  /* ── System metrics ── */
  const sys = gridState?.system;

  /* ── DEFRA LiDAR toggle ── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    if (showLidar && !lidarLayerRef.current) {
      const provider = createDEFRALidarHillshade();
      lidarLayerRef.current = viewer.imageryLayers.addImageryProvider(provider);
      lidarLayerRef.current.alpha = 0.5;
    } else if (!showLidar && lidarLayerRef.current) {
      viewer.imageryLayers.remove(lidarLayerRef.current, true);
      lidarLayerRef.current = null;
    }
  }, [showLidar]);

  /* ── Asset visibility toggle ── */
  useEffect(() => {
    if (assetDsRef.current) {
      assetDsRef.current.show = showAssets;
    }
  }, [showAssets]);

  /* ── Fly camera to location (from signal feed / agent) ── */
  const handleFlyTo = useCallback((loc) => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(loc.lon, loc.lat, loc.height || 80000),
      orientation: {
        heading: Cesium.Math.toRadians(loc.heading || 350),
        pitch: Cesium.Math.toRadians(loc.pitch || -40),
        roll: 0,
      },
      duration: 1.5,
    });
  }, []);

  /* ── Dispatch AI agent from context menu or signal feed ── */
  const handleDispatchAgent = useCallback((intent, context) => {
    setAgentDispatch({ intent, context });
    setContextMenu(null);
  }, []);

  /* ── GIBS layer controls ── */
  const toggleGIBS = (key) => {
    setShowGIBS(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

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
          <span className="gt-title-engine">Cesium</span>
          {sys && (
            <span className="gt-freq" style={{ color: Math.abs(sys.frequency_hz - 50) > 0.05 ? "#f5222d" : "#52c41a" }}>
              {sys.frequency_hz.toFixed(3)} Hz
            </span>
          )}
        </div>

        <div className="gt-toolbar-center">
          <button className={`gt-pill ${liveMode ? "active" : ""}`} onClick={() => setLiveMode(!liveMode)}>
            <span className={`gt-live-dot ${liveMode ? "pulsing" : ""}`} />
            {liveMode ? "LIVE" : "STATIC"}
          </button>

          <select className="gt-select" value={scenario}
            onChange={e => { setScenario(e.target.value); setLiveMode(false); }}>
            {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>

          {!liveMode && (
            <div className="gt-year-slider">
              <input type="range" min={2024} max={2050} value={scenarioYear}
                onChange={e => setScenarioYear(Number(e.target.value))} className="gt-slider" />
              <span className="gt-year-label">{scenarioYear}</span>
            </div>
          )}
        </div>

        <div className="gt-toolbar-right">
          {/* Layer toggles — labelled */}
          <button className={`gt-layer-btn-label ${twinLayers.substations ? "active" : ""}`}
            onClick={() => setTwinLayers(prev => ({ ...prev, substations: !prev.substations }))}>Substations</button>
          <button className={`gt-layer-btn-label ${twinLayers.lines ? "active" : ""}`}
            onClick={() => setTwinLayers(prev => ({ ...prev, lines: !prev.lines }))}>Lines</button>
          <button className={`gt-layer-btn-label ${twinLayers.labels ? "active" : ""}`}
            onClick={() => setTwinLayers(prev => ({ ...prev, labels: !prev.labels }))}>Labels</button>
          <button className={`gt-layer-btn-label ${twinLayers.particles ? "active" : ""}`}
            onClick={() => setTwinLayers(prev => ({ ...prev, particles: !prev.particles }))}>Flow</button>

          <div style={{ width: 1, height: 16, background: "rgba(255,255,255,0.12)" }} />

          <button className={`gt-layer-btn-label ${showBuildings ? "active" : ""}`}
            onClick={() => setShowBuildings(!showBuildings)}>Buildings</button>
          <button className={`gt-layer-btn-label ${show3DTiles ? "active" : ""}`}
            onClick={() => setShow3DTiles(!show3DTiles)}
            style={show3DTiles ? { background: "#4285f4", color: "#fff" } : {}}>3D Tiles</button>
          <button className={`gt-layer-btn-label ${showAssets ? "active" : ""}`}
            onClick={() => setShowAssets(!showAssets)}>Assets</button>
          <button className={`gt-layer-btn-label ${showLidar ? "active" : ""}`}
            onClick={() => setShowLidar(!showLidar)}>LiDAR</button>
          <button className={`gt-layer-btn-label ${constraintHeatmap ? "active" : ""}`}
            onClick={() => setConstraintHeatmap(!constraintHeatmap)}>Constraints</button>
          <button className={`gt-layer-btn-label ${choreographyActive ? "active" : ""}`}
            onClick={() => setChoreographyActive(!choreographyActive)}
            style={choreographyActive ? { background: "#D4A018", color: "#000" } : {}}>AI Tour</button>

          <div style={{ width: 1, height: 16, background: "rgba(255,255,255,0.12)" }} />

          {/* View presets */}
          <button className="gt-layer-btn-label"
            onClick={() => viewerRef.current?.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(-1.5, 53.0, 1200000),
              orientation: { heading: Cesium.Math.toRadians(350), pitch: Cesium.Math.toRadians(-55), roll: 0 },
              duration: 1.5,
            })}>UK View</button>
          <button className="gt-layer-btn-label"
            onClick={() => viewerRef.current?.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(-1.5, 52.5, 200000),
              orientation: { heading: Cesium.Math.toRadians(350), pitch: Cesium.Math.toRadians(-35), roll: 0 },
              duration: 1.5,
            })}>Close-up</button>

          <button className="gt-close" onClick={onClose}>&times;</button>
        </div>
      </div>

      {/* ── GIBS satellite layer panel ── */}
      <div className="gt-gibs-panel">
        <div className="gt-gibs-title">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
          </svg>
          NASA GIBS
        </div>
        <div className="gt-gibs-date">
          <input type="date" value={gibsDate} onChange={e => setGibsDate(e.target.value)}
            className="gt-gibs-date-input" />
        </div>
        {Object.entries(GIBS_LAYERS).map(([key, layer]) => (
          <button key={key}
            className={`gt-gibs-btn ${showGIBS.includes(key) ? "active" : ""}`}
            onClick={() => toggleGIBS(key)}
            title={layer.label}>
            <span className={`gt-gibs-cat gt-gibs-cat-${layer.category}`} />
            {layer.label}
          </button>
        ))}
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
          {gridState.scenario && (
            <div className="gt-metric gt-metric-scenario">
              <span className="gt-metric-label">Scenario</span>
              <span className="gt-metric-value">{gridState.scenario.name.replace(/_/g, " ")} {gridState.scenario.year}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Site Finder ── */}
      <TwinSiteFinder
        viewer={viewerRef.current}
        onSiteSelected={(site) => {
          console.log("[Twin] Site selected:", site);
        }}
      />

      {/* ── Cesium Globe ── */}
      <CesiumGlobe
        onReady={handleViewerReady}
        darkMode={false}
        showTerrain={true}
        showBuildings={showBuildings}
        show3DTiles={show3DTiles}
        gibsLayers={showGIBS}
        gibsDate={gibsDate}
        initialView={{ lon: -2.0, lat: 54.0, height: 1500000, heading: 350, pitch: -50 }}
        className="gt-map"
      />

      {/* ── Loading overlay ── */}
      {loading && (
        <div className="gt-loading">
          <div className="gt-loading-spinner" />
          Initialising Cesium grid twin...
        </div>
      )}

      {/* ── Inspector panel ── */}
      {inspected && (
        <div className="gt-inspector">
          <div className="gt-inspector-header">
            <span className="gt-inspector-type">
              {inspected.type === "substation" ? "Substation" : inspected.type === "asset" ? "Energy Asset" : "Transmission Line"}
            </span>
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

          {inspected.type === "asset" && (() => {
            const a = inspected.data;
            return (
              <div className="gt-inspector-body">
                <div className="gt-inspector-name" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{
                    display: "inline-block", width: 10, height: 10, borderRadius: "50%",
                    background: a.color, flexShrink: 0,
                  }} />
                  {a.name}
                </div>
                <div className="gt-inspector-id">
                  {a.asset_type} &middot; {a.status} {a.dno ? `&middot; ${a.dno}` : ""}
                </div>
                <div className="gt-inspector-grid">
                  <div><span className="gt-insp-label">Capacity</span><span className="gt-insp-value">{fmtMw(a.capacity_mw)}</span></div>
                  <div><span className="gt-insp-label">Fuel</span><span className="gt-insp-value">{a.fuel}</span></div>
                  <div><span className="gt-insp-label">Operator</span><span className="gt-insp-value">{a.operator || "—"}</span></div>
                  <div><span className="gt-insp-label">Location</span><span className="gt-insp-value">{a.lat.toFixed(4)}, {a.lon.toFixed(4)}</span></div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ── AI Choreography narration ── */}
      {choreographyActive && choreoNarration && (
        <div className="gc-choreo-narration">
          <div className="gc-choreo-progress">
            {choreoStops.map((_, i) => (
              <div key={i} className={`gc-choreo-dot ${i === choreoIdx ? "active" : ""} ${i < choreoIdx ? "done" : ""}`} />
            ))}
          </div>
          <div className="gc-choreo-label" style={{ borderLeftColor: choreoNarration.color }}>
            <div className="gc-choreo-type">{choreoNarration.type.toUpperCase()}</div>
            <div className="gc-choreo-text">{choreoNarration.label}</div>
            <div className="gc-choreo-sub">{choreoNarration.sublabel}</div>
          </div>
          <button className="gc-choreo-stop" onClick={() => { setChoreographyActive(false); setChoreoNarration(null); }}>
            Stop Tour
          </button>
        </div>
      )}

      {/* ── Signal Feed (right panel) ── */}
      <SignalFeed
        gridState={gridState}
        onFlyTo={handleFlyTo}
        onDispatchAgent={handleDispatchAgent}
      />

      {/* ── Timeline Scrubber (bottom bar) ── */}
      <TimelineScrubber
        gridState={gridState}
        liveMode={liveMode}
        onLiveModeChange={setLiveMode}
        onTimeChange={setTimelineTime}
        onModeChange={setTimelineMode}
      />

      {/* ── Right-click context menu for AI dispatch ── */}
      {contextMenu && (
        <div
          className="gt-ctx-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onMouseLeave={() => setContextMenu(null)}
        >
          <div className="gt-ctx-header">
            {contextMenu.data.type === "substation"
              ? contextMenu.data.data.name
              : `${contextMenu.data.data.from} → ${contextMenu.data.data.to}`}
          </div>
          {[
            { intent: "grid_connection", label: "Grid Connection Analysis" },
            { intent: "grid_study", label: "Grid Study" },
            { intent: "demand_forecast", label: "Demand Forecast" },
            { intent: "feasibility", label: "Site Feasibility" },
            { intent: "grid_efficiency", label: "Grid Efficiency" },
            { intent: "planning", label: "Planning Risk" },
          ].map(a => (
            <button
              key={a.intent}
              className="gt-ctx-item"
              onClick={() => handleDispatchAgent(a.intent, contextMenu.data.type === "substation" ? { substation: contextMenu.data.data } : { line: contextMenu.data.data })}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/><path d="M8 12h8M12 8v8"/>
              </svg>
              {a.label}
            </button>
          ))}
        </div>
      )}

      {/* ── AI Agent Dispatcher panel ── */}
      {agentDispatch && (
        <AgentDispatcher
          intent={agentDispatch.intent}
          context={agentDispatch.context}
          onClose={() => setAgentDispatch(null)}
          onFlyTo={handleFlyTo}
        />
      )}

      {/* ── Legend ── */}
      <div className="gt-legend">
        <div className="gt-legend-title">Voltage</div>
        {Object.entries(VOLTAGE_COLORS_RGB).map(([kv, rgb]) => (
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
    </div>
  );
}
