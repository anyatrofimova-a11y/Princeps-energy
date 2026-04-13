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
import LandParcelLayer from "./LandParcelLayer";
import LandClassificationLayer from "./LandClassificationLayer";
import LayerControlPanel from "./LayerControlPanel";
import ParcelDetailPanel from "./ParcelDetailPanel";
import api from "../services/api";
import {
  GIBS_LAYERS,
  voltageColorCesium,
  utilisationColorCesium,
  ASSET_STYLES,
  createDEFRALidarHillshade,
  createGIBSProvider,
} from "../lib/cesium-config";

/* ── Rendering / Vision Modes ──────────────────────────────────────────── */
const VISION_MODES = [
  { id: "normal", label: "Normal", icon: "N", color: "#fff" },
  { id: "thermal", label: "Thermal", icon: "T", color: "#f5222d" },
  { id: "grid_stress", label: "Grid Stress", icon: "S", color: "#fa8c16" },
  { id: "queue_depth", label: "Queue Depth", icon: "Q", color: "#e040fb" },
  { id: "planning_risk", label: "Planning Risk", icon: "P", color: "#1890ff" },
  { id: "nightlights", label: "Night Lights", icon: "NL", color: "#ffd60a" },
  { id: "god_mode", label: "God Mode", icon: "\u26A1", color: "#D4A018" },
];

/* CSS filter matrices for vision modes */
const VISION_FILTERS = {
  normal: null,
  thermal: { hue: 0, saturation: 0.6, brightness: 0.8, contrast: 1.4, postClass: "gt-thermal" },
  grid_stress: { hue: 0, saturation: 1.2, brightness: 1.0, contrast: 1.1, postClass: "gt-stress" },
  queue_depth: null,
  planning_risk: null,
  nightlights: { hue: 0, saturation: 0.3, brightness: 0.5, contrast: 1.6, postClass: "gt-nightvision" },
  god_mode: { hue: 0, saturation: 1.0, brightness: 1.0, contrast: 1.2, postClass: "gt-godmode" },
};

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
  const [hovered, setHovered] = useState(null);
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
  const [showProjects, setShowProjects] = useState(true);
  const [projects, setProjects] = useState([]);
  const [visionMode, setVisionMode] = useState("normal");
  const [visionMenuOpen, setVisionMenuOpen] = useState(false);
  const [layerPanelOpen, setLayerPanelOpen] = useState(false);
  const [gibsPanelOpen, setGibsPanelOpen] = useState(false);
  const [overlayData, setOverlayData] = useState({
    gridStress: null,    // substation utilisation zones
    queueDepth: null,    // ECR queue data per GSP
    planningRisk: null,  // planning probability data
  });
  /* ── Land parcel + classification state ── */
  const [showLandParcels, setShowLandParcels] = useState(true);
  const [showLandClassification, setShowLandClassification] = useState(false);
  const [selectedParcels, setSelectedParcels] = useState([]);
  const [parcelFilters, setParcelFilters] = useState({});
  const [filterVersion, setFilterVersion] = useState(0);
  const [gisLayers, setGisLayers] = useState({
    landParcels: { visible: true, opacity: 0.3 },
    landClassification: { visible: false, opacity: 0.6 },
    gridInfra: { visible: true, opacity: 1 },
    energyAssets: { visible: true, opacity: 1 },
    floodZones: { visible: false, opacity: 0.5 },
    protectedAreas: { visible: false, opacity: 0.5 },
    alcGrades: { visible: false, opacity: 0.5 },
    slopeAnalysis: { visible: false, opacity: 0.5 },
    constraintPins: { visible: false, opacity: 0.8 },
    satellite: { visible: false, opacity: 0.7 },
    buildings: { visible: false, opacity: 1 },
  });

  const handleGisLayerChange = useCallback((key, state) => {
    setGisLayers(prev => ({ ...prev, [key]: state }));
    // Sync with existing toggles
    if (key === "landParcels") setShowLandParcels(state.visible);
    if (key === "landClassification") setShowLandClassification(state.visible);
    if (key === "gridInfra") setTwinLayers(p => ({ ...p, substations: state.visible, lines: state.visible }));
    if (key === "energyAssets") setShowAssets(state.visible);
    if (key === "buildings") setShowBuildings(state.visible);
  }, []);

  const handleParcelClick = useCallback((parcel) => {
    setSelectedParcels([parcel]);
  }, []);

  const handleParcelSelectionChange = useCallback((parcels) => {
    setSelectedParcels(parcels);
  }, []);

  const handleCopyToProject = useCallback((parcels) => {
    console.log("[Twin] Copy parcels to project:", parcels.length);
  }, []);

  const handleSaveToProject = useCallback(({ projectName, parcels }) => {
    api.parcels?.selectForProject?.({ project_name: projectName, parcels })
      .then(() => console.log(`[Twin] Saved ${parcels.length} parcels to "${projectName}"`))
      .catch(e => console.warn("[Twin] Save parcels error:", e));
  }, []);

  const lidarLayerRef = useRef(null);
  const assetDsRef = useRef(null);
  const projectDsRef = useRef(null);
  const hoverRef = useRef(null);
  const tooltipPosRef = useRef({ x: 0, y: 0 });
  const overlayDsRef = useRef(null);
  const nightlightsLayerRef = useRef(null);

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

    // Hover handler — tooltip on mouse move
    handler.setInputAction((movement) => {
      const picked = viewer.scene.pick(movement.endPosition);
      if (picked && picked.id && picked.id._princepsData) {
        const d = picked.id._princepsData;
        if (!hoverRef.current || hoverRef.current.data !== d.data) {
          hoverRef.current = d;
          tooltipPosRef.current = { x: movement.endPosition.x, y: movement.endPosition.y };
          setHovered({ ...d, x: movement.endPosition.x, y: movement.endPosition.y });
          viewer.scene.canvas.style.cursor = "pointer";
        } else {
          tooltipPosRef.current = { x: movement.endPosition.x, y: movement.endPosition.y };
          setHovered(prev => prev ? { ...prev, x: movement.endPosition.x, y: movement.endPosition.y } : null);
        }
      } else if (hoverRef.current) {
        hoverRef.current = null;
        setHovered(null);
        viewer.scene.canvas.style.cursor = "";
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    // Project data source
    const projectDs = new Cesium.CustomDataSource("projects");
    viewer.dataSources.add(projectDs);
    projectDsRef.current = projectDs;

    // Overlay data source (for vision mode entities)
    const overlayDs = new Cesium.CustomDataSource("vision-overlays");
    viewer.dataSources.add(overlayDs);
    overlayDsRef.current = overlayDs;

    // Energy assets data source
    const assetDs = new Cesium.CustomDataSource("energy-assets");
    viewer.dataSources.add(assetDs);
    assetDsRef.current = assetDs;

    // Load ALL energy assets from backend
    fetch("/analytics/energy-assets")
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
      lon: -0.12, lat: 51.5, height: 800000, heading: 0, pitch: -60,
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

  /* ── Load pipeline projects ── */
  useEffect(() => {
    fetch("/api/v1/projects")
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        const list = Array.isArray(data) ? data : data.projects || [];
        setProjects(list);
      })
      .catch(() => {});
  }, []);

  /* ── Render project entities ── */
  useEffect(() => {
    const ds = projectDsRef.current;
    if (!ds) return;
    ds.entities.removeAll();
    if (!showProjects) return;

    const STAGE_COLORS = {
      prospect: "#8c8c8c", screened: "#D4A018", grid_applied: "#fa8c16",
      grid_offer: "#1890ff", planning: "#e040fb", fid: "#52c41a",
      construction: "#00b4d8", energised: "#52c41a",
    };
    const VERDICT_ICONS = { GO: "\u2714", CAUTION: "\u26A0", "NO-GO": "\u2718" };

    for (const p of projects) {
      if (!p.lat || !p.lon) continue;
      const color = STAGE_COLORS[p.stage] || "#D4A018";

      const entity = ds.entities.add({
        position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 100),
        billboard: {
          image: (() => {
            const c = document.createElement("canvas");
            c.width = 32; c.height = 40;
            const ctx = c.getContext("2d");
            // Pin shape
            ctx.beginPath();
            ctx.moveTo(16, 38);
            ctx.bezierCurveTo(16, 38, 4, 24, 4, 14);
            ctx.arc(16, 14, 12, Math.PI, 0, false);
            ctx.bezierCurveTo(28, 24, 16, 38, 16, 38);
            ctx.fillStyle = color;
            ctx.fill();
            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 1.5;
            ctx.stroke();
            // Inner dot
            ctx.beginPath();
            ctx.arc(16, 14, 5, 0, Math.PI * 2);
            ctx.fillStyle = "#fff";
            ctx.fill();
            return c.toDataURL();
          })(),
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          scale: 1.0,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          scaleByDistance: new Cesium.NearFarScalar(5e3, 1.2, 1e6, 0.4),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        },
        label: {
          text: `${p.name}\n${p.stage?.replace(/_/g, " ").toUpperCase() || ""} ${p.capacity_mw ? p.capacity_mw + " MW" : ""}`,
          font: "11px 'DM Sans', sans-serif",
          fillColor: Cesium.Color.fromCssColorString(color),
          outlineColor: Cesium.Color.BLACK.withAlpha(0.8),
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.TOP,
          pixelOffset: new Cesium.Cartesian2(0, 6),
          scaleByDistance: new Cesium.NearFarScalar(1e4, 1.0, 5e5, 0),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      entity._princepsData = {
        type: "project",
        data: { ...p, color },
      };
    }
  }, [projects, showProjects]);

  /* ── Project visibility toggle ── */
  useEffect(() => {
    if (projectDsRef.current) {
      projectDsRef.current.show = showProjects;
    }
  }, [showProjects]);

  /* ── Vision mode rendering ── */
  useEffect(() => {
    const viewer = viewerRef.current;
    const ds = overlayDsRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    // Remove nightlights layer if switching away
    if (visionMode !== "nightlights" && visionMode !== "god_mode" && nightlightsLayerRef.current) {
      viewer.imageryLayers.remove(nightlightsLayerRef.current, true);
      nightlightsLayerRef.current = null;
    }

    // Clear overlay entities
    if (ds) ds.entities.removeAll();

    // Apply CSS filter to Cesium canvas for vision mode atmosphere
    const canvas = viewer.scene.canvas;
    const vf = VISION_FILTERS[visionMode];
    if (vf) {
      const filters = [];
      if (vf.brightness !== 1.0) filters.push(`brightness(${vf.brightness})`);
      if (vf.contrast !== 1.0) filters.push(`contrast(${vf.contrast})`);
      if (vf.saturation !== 1.0) filters.push(`saturate(${vf.saturation})`);
      if (vf.hue) filters.push(`hue-rotate(${vf.hue}deg)`);
      canvas.style.filter = filters.join(" ");
    } else {
      canvas.style.filter = "";
    }

    // Add nightlights GIBS layer for nightlights + god mode
    if ((visionMode === "nightlights" || visionMode === "god_mode") && !nightlightsLayerRef.current) {
      const provider = createGIBSProvider("viirs_nightlights", gibsDate);
      if (provider) {
        nightlightsLayerRef.current = viewer.imageryLayers.addImageryProvider(provider);
        nightlightsLayerRef.current.alpha = visionMode === "god_mode" ? 0.3 : 0.7;
      }
    }

    // Grid stress mode: pulse rings around high-utilisation substations
    if ((visionMode === "grid_stress" || visionMode === "god_mode") && gridState && ds) {
      for (const s of gridState.substations || []) {
        if (s.utilisation < 0.7) continue;
        const severity = s.utilisation >= 0.9 ? 1.0 : s.utilisation >= 0.8 ? 0.6 : 0.3;
        const pulseColor = s.utilisation >= 0.9
          ? Cesium.Color.fromCssColorString("rgba(245,34,45,0.4)")
          : s.utilisation >= 0.8
            ? Cesium.Color.fromCssColorString("rgba(250,140,22,0.3)")
            : Cesium.Color.fromCssColorString("rgba(250,200,22,0.15)");

        ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
          ellipse: {
            semiMajorAxis: 5000 + severity * 15000,
            semiMinorAxis: 5000 + severity * 15000,
            material: pulseColor,
            outline: true,
            outlineColor: pulseColor.withAlpha(0.8),
            outlineWidth: 2,
            height: 5,
          },
        });

        // Outer warning ring
        if (s.utilisation >= 0.85) {
          ds.entities.add({
            position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
            ellipse: {
              semiMajorAxis: 15000 + severity * 25000,
              semiMinorAxis: 15000 + severity * 25000,
              fill: false,
              outline: true,
              outlineColor: Cesium.Color.fromCssColorString("rgba(245,34,45,0.25)"),
              outlineWidth: 1.5,
              height: 5,
            },
          });
        }
      }
    }

    // Queue depth mode: show ECR queue as sized circles at substations
    if ((visionMode === "queue_depth" || visionMode === "god_mode") && gridState && ds) {
      for (const s of gridState.substations || []) {
        const queued = s.ecr_queued || 0;
        const queuedMw = s.ecr_mw || 0;
        if (queued <= 0 && queuedMw <= 0) continue;
        const radius = 3000 + Math.min(queuedMw, 500) * 20;
        ds.entities.add({
          position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat),
          ellipse: {
            semiMajorAxis: radius,
            semiMinorAxis: radius,
            material: Cesium.Color.fromCssColorString("rgba(224,64,251,0.2)"),
            outline: true,
            outlineColor: Cesium.Color.fromCssColorString("rgba(224,64,251,0.6)"),
            outlineWidth: 2,
            height: 5,
          },
          label: {
            text: `${queued} apps\n${Math.round(queuedMw)} MW`,
            font: "10px 'JetBrains Mono', monospace",
            fillColor: Cesium.Color.fromCssColorString("#e040fb"),
            outlineColor: Cesium.Color.BLACK.withAlpha(0.8),
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new Cesium.NearFarScalar(1e4, 1.0, 1e6, 0.3),
          },
        });
      }
    }

    // Planning risk mode: fetch and display planning probability data
    if ((visionMode === "planning_risk" || visionMode === "god_mode") && ds) {
      fetch("/api/planning/risk-map?region=UK")
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data?.zones || !overlayDsRef.current) return;
          for (const z of data.zones) {
            const risk = z.risk_score || 0.5;
            const color = risk > 0.7
              ? Cesium.Color.fromCssColorString("rgba(245,34,45,0.25)")
              : risk > 0.4
                ? Cesium.Color.fromCssColorString("rgba(250,140,22,0.2)")
                : Cesium.Color.fromCssColorString("rgba(82,196,26,0.1)");
            overlayDsRef.current.entities.add({
              position: Cesium.Cartesian3.fromDegrees(z.lon, z.lat),
              ellipse: {
                semiMajorAxis: z.radius || 10000,
                semiMinorAxis: z.radius || 10000,
                material: color,
                outline: true,
                outlineColor: color.withAlpha(0.6),
                outlineWidth: 1,
                height: 5,
              },
            });
          }
        })
        .catch(() => {});
    }

    // Thermal mode: add land surface temp GIBS layer
    if (visionMode === "thermal") {
      const provider = createGIBSProvider("land_surface_temp", gibsDate);
      if (provider) {
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = 0.5;
        // Store so we can remove on mode change
        return () => {
          if (!viewer.isDestroyed()) viewer.imageryLayers.remove(layer, true);
        };
      }
    }

    // God mode: highlight every entity — make all assets glow
    if (visionMode === "god_mode" && assetDsRef.current) {
      const entities = assetDsRef.current.entities.values;
      for (const e of entities) {
        if (e.point) {
          e.point.outlineWidth = 3;
          e.point.outlineColor = Cesium.Color.fromCssColorString("#D4A018").withAlpha(0.9);
          e.point.pixelSize = (e.point.pixelSize?.getValue?.() || 8) * 1.3;
        }
      }
      // Restore on cleanup
      return () => {
        if (assetDsRef.current) {
          for (const e of assetDsRef.current.entities.values) {
            if (e.point) {
              e.point.outlineWidth = 1.5;
              e.point.outlineColor = Cesium.Color.WHITE.withAlpha(0.6);
            }
          }
        }
      };
    }
  }, [visionMode, gridState, gibsDate]);

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
    <div className={`gt-overlay ${VISION_FILTERS[visionMode]?.postClass || ""}`}>

      {/* ═══ TOP BAR — slim, essential info only ═══ */}
      <div className="gt2-topbar">
        <div className="gt2-topbar-left">
          <span className="gt2-logo">PRINCEPS</span>
          <span className="gt2-badge">DIGITAL TWIN</span>
          {sys && (
            <span className="gt2-freq" style={{ color: Math.abs(sys.frequency_hz - 50) > 0.05 ? "#f5222d" : "#52c41a" }}>
              {sys.frequency_hz.toFixed(3)} Hz
            </span>
          )}
        </div>
        <div className="gt2-topbar-center">
          <button className={`gt2-live ${liveMode ? "active" : ""}`} onClick={() => setLiveMode(!liveMode)}>
            <span className={`gt2-live-dot ${liveMode ? "pulsing" : ""}`} />
            {liveMode ? "LIVE" : "STATIC"}
          </button>
          {sys && <>
            <div className="gt2-stat"><span>{fmtMw(sys.total_demand_mw)}</span><label>demand</label></div>
            <div className="gt2-stat"><span style={{ color: "#52c41a" }}>{fmtMw(sys.total_generation_mw)}</span><label>gen</label></div>
            <div className="gt2-stat"><span style={{
              color: sys.system_utilisation >= 0.85 ? "#f5222d" : sys.system_utilisation >= 0.65 ? "#fa8c16" : "#52c41a"
            }}>{(sys.system_utilisation * 100).toFixed(1)}%</span><label>util</label></div>
          </>}
        </div>
        <div className="gt2-topbar-right">
          <select className="gt2-scenario" value={scenario}
            onChange={e => { setScenario(e.target.value); setLiveMode(false); }}>
            {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          {!liveMode && (
            <div className="gt2-year">
              <input type="range" min={2024} max={2050} value={scenarioYear}
                onChange={e => setScenarioYear(Number(e.target.value))} />
              <span>{scenarioYear}</span>
            </div>
          )}
          <button className="gt2-close" onClick={onClose}>&times;</button>
        </div>
      </div>

      {/* ═══ LEFT RAIL — vertical icon strip with flyout panels ═══ */}
      <div className="gt2-rail">
        {/* Layers */}
        <button className={`gt2-rail-btn ${layerPanelOpen ? "active" : ""}`}
          onClick={() => { setLayerPanelOpen(!layerPanelOpen); setGibsPanelOpen(false); setVisionMenuOpen(false); }}
          title="Layers">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>
          </svg>
        </button>
        {/* Vision */}
        <button className={`gt2-rail-btn ${visionMode !== "normal" ? "active" : ""}`}
          onClick={() => { setVisionMenuOpen(!visionMenuOpen); setLayerPanelOpen(false); setGibsPanelOpen(false); }}
          title="Vision Mode"
          style={visionMode !== "normal" ? { color: VISION_MODES.find(m => m.id === visionMode)?.color } : {}}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
          </svg>
        </button>
        {/* Satellite / GIBS */}
        <button className={`gt2-rail-btn ${gibsPanelOpen ? "active" : ""}`}
          onClick={() => { setGibsPanelOpen(!gibsPanelOpen); setLayerPanelOpen(false); setVisionMenuOpen(false); }}
          title="Satellite Imagery">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
          </svg>
        </button>

        <div className="gt2-rail-sep" />

        {/* AI Tour */}
        <button className={`gt2-rail-btn ${choreographyActive ? "active" : ""}`}
          onClick={() => setChoreographyActive(!choreographyActive)}
          title="AI Tour"
          style={choreographyActive ? { color: "#D4A018" } : {}}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
        </button>
        {/* UK View */}
        <button className="gt2-rail-btn" title="UK Overview"
          onClick={() => viewerRef.current?.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(-0.12, 51.5, 800000),
            orientation: { heading: Cesium.Math.toRadians(0), pitch: Cesium.Math.toRadians(-60), roll: 0 },
            duration: 1.5,
          })}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"/>
          </svg>
        </button>
        {/* Zoom close */}
        <button className="gt2-rail-btn" title="Close-up"
          onClick={() => viewerRef.current?.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(-1.5, 52.5, 200000),
            orientation: { heading: Cesium.Math.toRadians(350), pitch: Cesium.Math.toRadians(-35), roll: 0 },
            duration: 1.5,
          })}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
          </svg>
        </button>
      </div>

      {/* ═══ LAYER PANEL — flyout from left rail ═══ */}
      {layerPanelOpen && (
        <div className="gt2-flyout" style={{ top: 52 }}>
          <div className="gt2-flyout-title">Layers</div>
          <div className="gt2-flyout-section">Grid</div>
          {[
            { key: "substations", label: "Substations", active: twinLayers.substations, toggle: () => setTwinLayers(p => ({ ...p, substations: !p.substations })) },
            { key: "lines", label: "Transmission Lines", active: twinLayers.lines, toggle: () => setTwinLayers(p => ({ ...p, lines: !p.lines })) },
            { key: "labels", label: "Labels", active: twinLayers.labels, toggle: () => setTwinLayers(p => ({ ...p, labels: !p.labels })) },
            { key: "particles", label: "Flow Particles", active: twinLayers.particles, toggle: () => setTwinLayers(p => ({ ...p, particles: !p.particles })) },
            { key: "constraints", label: "Constraint Zones", active: constraintHeatmap, toggle: () => setConstraintHeatmap(!constraintHeatmap) },
          ].map(l => (
            <label key={l.key} className="gt2-layer-row">
              <input type="checkbox" checked={l.active} onChange={l.toggle} />
              <span>{l.label}</span>
            </label>
          ))}
          <div className="gt2-flyout-section">Land</div>
          {[
            { key: "landParcels", label: "Land Parcels", active: showLandParcels, toggle: () => { setShowLandParcels(p => !p); setGisLayers(prev => ({ ...prev, landParcels: { ...prev.landParcels, visible: !showLandParcels } })); }, color: "#c040ff" },
            { key: "landClass", label: "Land Classification", active: showLandClassification, toggle: () => { setShowLandClassification(p => !p); setGisLayers(prev => ({ ...prev, landClassification: { ...prev.landClassification, visible: !showLandClassification } })); }, color: "#34a853" },
          ].map(l => (
            <label key={l.key} className="gt2-layer-row">
              <input type="checkbox" checked={l.active} onChange={l.toggle} />
              <span style={l.color ? { color: l.color } : {}}>{l.label}</span>
            </label>
          ))}
          <div className="gt2-flyout-section">Data</div>
          {[
            { key: "assets", label: "Energy Assets", active: showAssets, toggle: () => setShowAssets(!showAssets) },
            { key: "projects", label: "Pipeline Projects", active: showProjects, toggle: () => setShowProjects(!showProjects), color: "#D4A018" },
            { key: "lidar", label: "DEFRA LiDAR", active: showLidar, toggle: () => setShowLidar(!showLidar) },
          ].map(l => (
            <label key={l.key} className="gt2-layer-row">
              <input type="checkbox" checked={l.active} onChange={l.toggle} />
              <span style={l.color ? { color: l.color } : {}}>{l.label}</span>
            </label>
          ))}
          <div className="gt2-flyout-section">Environment</div>
          {[
            { key: "buildings", label: "OSM Buildings", active: showBuildings, toggle: () => setShowBuildings(!showBuildings) },
            { key: "3dtiles", label: "Google 3D Tiles", active: show3DTiles, toggle: () => setShow3DTiles(!show3DTiles) },
          ].map(l => (
            <label key={l.key} className="gt2-layer-row">
              <input type="checkbox" checked={l.active} onChange={l.toggle} />
              <span>{l.label}</span>
            </label>
          ))}
        </div>
      )}

      {/* ═══ VISION MODE PANEL — flyout ═══ */}
      {visionMenuOpen && (
        <div className="gt2-flyout" style={{ top: 92 }}>
          <div className="gt2-flyout-title">Vision Mode</div>
          {VISION_MODES.map(m => (
            <button
              key={m.id}
              className={`gt2-vision-row ${visionMode === m.id ? "active" : ""}`}
              onClick={() => { setVisionMode(m.id); setVisionMenuOpen(false); }}
            >
              <span className="gt2-vision-dot" style={{ background: m.color }} />
              <span>{m.label}</span>
              {m.id === "god_mode" && <span className="gt2-vision-all">ALL</span>}
            </button>
          ))}
        </div>
      )}

      {/* ═══ GIBS PANEL — flyout ═══ */}
      {gibsPanelOpen && (
        <div className="gt2-flyout" style={{ top: 132 }}>
          <div className="gt2-flyout-title">Satellite Imagery</div>
          <input type="date" value={gibsDate} onChange={e => setGibsDate(e.target.value)}
            className="gt2-date-input" />
          {Object.entries(GIBS_LAYERS).map(([key, layer]) => (
            <label key={key} className="gt2-layer-row">
              <input type="checkbox" checked={showGIBS.includes(key)} onChange={() => toggleGIBS(key)} />
              <span>{layer.label}</span>
            </label>
          ))}
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
        initialView={{ lon: -0.12, lat: 51.5, height: 800000, heading: 0, pitch: -60 }}
        className="gt-map"
      />

      {/* ── Land Parcel Layer ── */}
      <LandParcelLayer
        viewer={viewerRef.current}
        visible={showLandParcels}
        opacity={gisLayers.landParcels?.opacity ?? 0.3}
        filters={parcelFilters}
        filterVersion={filterVersion}
        onParcelClick={handleParcelClick}
        onSelectionChange={handleParcelSelectionChange}
      />

      {/* ── Land Classification Layer ── */}
      <LandClassificationLayer
        viewer={viewerRef.current}
        visible={showLandClassification}
        opacity={gisLayers.landClassification?.opacity ?? 0.6}
      />

      {/* ── GIS Layer Control Panel (top-right) ── */}
      <LayerControlPanel
        layers={gisLayers}
        onLayerChange={handleGisLayerChange}
        filters={parcelFilters}
        onFilterChange={setParcelFilters}
        onApplyFilters={() => setFilterVersion(v => v + 1)}
      />

      {/* ── Parcel Detail Panel (right side) ── */}
      <ParcelDetailPanel
        selectedParcels={selectedParcels}
        onClose={() => setSelectedParcels([])}
        onCopyToProject={handleCopyToProject}
        onSaveToProject={handleSaveToProject}
      />

      {/* ── Loading overlay ── */}
      {loading && (
        <div className="gt-loading">
          <div className="gt-loading-spinner" />
          Initialising Cesium grid twin...
        </div>
      )}

      {/* ── Hover tooltip ── */}
      {hovered && !inspected && (
        <div className="gt-hover-tooltip" style={{
          left: Math.min(hovered.x + 16, window.innerWidth - 280),
          top: Math.max(hovered.y - 10, 8),
        }}>
          {hovered.type === "substation" && (() => {
            const s = hovered.data;
            return (<>
              <div className="gt-tt-name">{s.name}</div>
              <div className="gt-tt-sub">{s.voltage_kv} kV {s.type} &middot; {s.dno || ""}</div>
              <div className="gt-tt-row"><span>Demand</span><span>{fmtMw(s.demand_mw)}</span></div>
              <div className="gt-tt-row"><span>Capacity</span><span>{fmtMw(s.capacity_mw)}</span></div>
              <div className="gt-tt-row"><span>Headroom</span><span>{fmtMw(s.headroom_mw)}</span></div>
              <div className="gt-tt-bar">
                <div style={{ width: `${Math.min(s.utilisation * 100, 100)}%`, background: s.utilisation >= 0.9 ? "#f5222d" : s.utilisation >= 0.7 ? "#fa8c16" : "#52c41a" }} />
              </div>
              <div className="gt-tt-util">{(s.utilisation * 100).toFixed(1)}% utilisation</div>
            </>);
          })()}
          {hovered.type === "line" && (() => {
            const l = hovered.data;
            return (<>
              <div className="gt-tt-name">{l.from} &rarr; {l.to}</div>
              <div className="gt-tt-sub">{l.voltage_kv} kV</div>
              <div className="gt-tt-row"><span>Flow</span><span>{fmtMw(Math.abs(l.flow_mw))}</span></div>
              <div className="gt-tt-row"><span>Loading</span><span style={{ color: l.congested ? "#f5222d" : "inherit" }}>{l.loading_pct?.toFixed(1)}%</span></div>
              {l.congested && <div className="gt-tt-alert">Congested</div>}
            </>);
          })()}
          {hovered.type === "asset" && (() => {
            const a = hovered.data;
            return (<>
              <div className="gt-tt-name" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: a.color }} />
                {a.name}
              </div>
              <div className="gt-tt-sub">{a.asset_type} &middot; {a.status}</div>
              {a.capacity_mw > 0 && <div className="gt-tt-row"><span>Capacity</span><span>{fmtMw(a.capacity_mw)}</span></div>}
              {a.operator && <div className="gt-tt-row"><span>Operator</span><span>{a.operator}</span></div>}
            </>);
          })()}
          {hovered.type === "project" && (() => {
            const p = hovered.data;
            return (<>
              <div className="gt-tt-name" style={{ color: p.color }}>{p.name}</div>
              <div className="gt-tt-sub">{p.technology || "—"} &middot; {p.stage?.replace(/_/g, " ")}</div>
              {p.capacity_mw && <div className="gt-tt-row"><span>Capacity</span><span>{p.capacity_mw} MW</span></div>}
              {p.verdict && <div className="gt-tt-row"><span>Verdict</span><span style={{ color: p.verdict === "GO" ? "#52c41a" : p.verdict === "NO-GO" ? "#f5222d" : "#fa8c16" }}>{p.verdict}</span></div>}
              {p.blocker && <div className="gt-tt-alert">{p.blocker}</div>}
            </>);
          })()}
        </div>
      )}

      {/* ── Inspector panel ── */}
      {inspected && (
        <div className="gt-inspector">
          <div className="gt-inspector-header">
            <span className="gt-inspector-type">
              {inspected.type === "substation" ? "Substation" : inspected.type === "asset" ? "Energy Asset" : inspected.type === "project" ? "Pipeline Project" : "Transmission Line"}
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

          {inspected.type === "project" && (() => {
            const p = inspected.data;
            return (
              <div className="gt-inspector-body">
                <div className="gt-inspector-name" style={{ color: p.color }}>{p.name}</div>
                <div className="gt-inspector-id">
                  {p.technology || "—"} &middot; {p.stage?.replace(/_/g, " ")} {p.verdict ? `&middot; ${p.verdict}` : ""}
                </div>
                <div className="gt-inspector-grid">
                  {p.capacity_mw && <div><span className="gt-insp-label">Capacity</span><span className="gt-insp-value">{p.capacity_mw} MW</span></div>}
                  <div><span className="gt-insp-label">Stage</span><span className="gt-insp-value">{p.stage?.replace(/_/g, " ")}</span></div>
                  {p.verdict && (
                    <div><span className="gt-insp-label">Verdict</span><span className="gt-insp-value" style={{
                      color: p.verdict === "GO" ? "#52c41a" : p.verdict === "NO-GO" ? "#f5222d" : "#fa8c16"
                    }}>{p.verdict}</span></div>
                  )}
                  {p.blocker && <div><span className="gt-insp-label">Blocker</span><span className="gt-insp-value" style={{ color: "#f5222d" }}>{p.blocker}</span></div>}
                  {p.description && <div style={{ gridColumn: "1/-1" }}><span className="gt-insp-label">Notes</span><span className="gt-insp-value">{p.description}</span></div>}
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
        inspected={inspected}
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
