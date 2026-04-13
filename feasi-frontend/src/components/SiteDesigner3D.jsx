/**
 * SiteDesigner3D — Cesium-based 3D site design tool for solar PV, BESS, and
 * hybrid energy infrastructure on real terrain.
 *
 * Overlays on CesiumGlobe with:
 *   - Solar PV panel rows (blue-purple terrain-following rectangles)
 *   - BESS containers (grey 3D boxes with transformer units)
 *   - Noise contour rings (green gradient)
 *   - Exclusion zones, access roads, perimeter fences, tree screens
 *   - Area labels, elevation markers
 *   - Design configuration sidebar
 *   - Drawing toolbar for polygon/road/point placement
 *   - Camera presets (overview, street level, bird's eye)
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import * as Cesium from "cesium";
import CesiumGlobe from "./CesiumGlobe";
import SiteDesignToolbar from "./SiteDesignToolbar";
import api from "../services/api";

/* ── Design tokens ──────────────────────────────────────────────────────── */
const T = {
  panel:        "rgba(20, 22, 30, 0.92)",
  panelBorder:  "1px solid rgba(212, 160, 24, 0.25)",
  accent:       "#D4A018",
  accentDim:    "rgba(212, 160, 24, 0.6)",
  text:         "#E8E6E1",
  textSec:      "#9CA3AF",
  bg:           "#0F1117",
  green:        "#24a148",
  red:          "#da1e28",
  blue:         "#4da6ff",
  orange:       "#fa8c16",
};

/* ── Cesium colors ──────────────────────────────────────────────────────── */
const COLORS = {
  solarPanel:     Cesium.Color.fromCssColorString("rgba(100, 120, 220, 0.72)"),
  solarOutline:   Cesium.Color.fromCssColorString("rgba(140, 160, 255, 0.9)"),
  bessContainer:  Cesium.Color.fromCssColorString("rgba(200, 205, 210, 0.92)"),
  bessEdge:       Cesium.Color.fromCssColorString("rgba(120, 125, 130, 1.0)"),
  transformer:    Cesium.Color.fromCssColorString("rgba(180, 160, 120, 0.9)"),
  exclusion:      Cesium.Color.fromCssColorString("rgba(218, 30, 40, 0.25)"),
  exclusionLine:  Cesium.Color.fromCssColorString("rgba(218, 30, 40, 0.7)"),
  road:           Cesium.Color.fromCssColorString("rgba(212, 180, 80, 0.7)"),
  fence:          Cesium.Color.fromCssColorString("rgba(140, 140, 140, 0.85)"),
  treeScreen:     Cesium.Color.fromCssColorString("rgba(40, 160, 60, 0.45)"),
  boundary:       Cesium.Color.fromCssColorString("rgba(0, 220, 255, 0.8)"),
  fireBreak:      Cesium.Color.fromCssColorString("rgba(250, 140, 22, 0.2)"),
  noise45:        Cesium.Color.fromCssColorString("rgba(200, 220, 50, 0.18)"),
  noise40:        Cesium.Color.fromCssColorString("rgba(120, 200, 80, 0.14)"),
  noise35:        Cesium.Color.fromCssColorString("rgba(80, 180, 100, 0.10)"),
  noiseLine45:    Cesium.Color.fromCssColorString("rgba(200, 220, 50, 0.6)"),
  noiseLine40:    Cesium.Color.fromCssColorString("rgba(120, 200, 80, 0.5)"),
  noiseLine35:    Cesium.Color.fromCssColorString("rgba(80, 180, 100, 0.4)"),
  substation:     Cesium.Color.fromCssColorString("rgba(120, 130, 140, 0.9)"),
  inverter:       Cesium.Color.fromCssColorString("rgba(100, 140, 170, 0.9)"),
  gate:           Cesium.Color.fromCssColorString("rgba(180, 180, 60, 0.9)"),
  drawVertex:     Cesium.Color.fromCssColorString("rgba(212, 160, 24, 1.0)"),
  drawLine:       Cesium.Color.fromCssColorString("rgba(212, 160, 24, 0.8)"),
  drawFill:       Cesium.Color.fromCssColorString("rgba(212, 160, 24, 0.15)"),
  label:          Cesium.Color.fromCssColorString("rgba(255, 255, 255, 0.95)"),
};

const NOISE_COLORS = {
  45: { fill: COLORS.noise45, line: COLORS.noiseLine45 },
  40: { fill: COLORS.noise40, line: COLORS.noiseLine40 },
  35: { fill: COLORS.noise35, line: COLORS.noiseLine35 },
};

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function haversine(lon1, lat1, lon2, lat2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function polygonArea(coords) {
  // Shoelace in approximate metres
  if (coords.length < 3) return 0;
  const cy = coords.reduce((s, c) => s + c[1], 0) / coords.length;
  const mLat = 111132;
  const mLon = 111412 * Math.cos(cy * Math.PI / 180);
  let area = 0;
  for (let i = 0; i < coords.length; i++) {
    const j = (i + 1) % coords.length;
    const xi = coords[i][0] * mLon, yi = coords[i][1] * mLat;
    const xj = coords[j][0] * mLon, yj = coords[j][1] * mLat;
    area += xi * yj - xj * yi;
  }
  return Math.abs(area) / 2;
}

function centroid(coords) {
  const n = coords.length;
  return [
    coords.reduce((s, c) => s + c[0], 0) / n,
    coords.reduce((s, c) => s + c[1], 0) / n,
  ];
}

function fmtNum(v) {
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return v.toFixed(1);
}

/* ── Camera presets ──────────────────────────────────────────────────────── */
const CAMERA_PRESETS = [
  { id: "overview",  label: "Overview",     height: 2000, pitch: -45, heading: 0 },
  { id: "street",    label: "Street Level", height: 15,   pitch: -5,  heading: 30 },
  { id: "bird",      label: "Bird's Eye",   height: 800,  pitch: -88, heading: 0 },
  { id: "oblique",   label: "Oblique",      height: 500,  pitch: -35, heading: 45 },
];


/* ═══════════════════════════════════════════════════════════════════════════
   SiteDesigner3D
   ═══════════════════════════════════════════════════════════════════════════ */
export default function SiteDesigner3D({ onClose, initialBoundary, initialLocation }) {
  const viewerRef = useRef(null);
  const designEntitiesRef = useRef([]);
  const drawEntitiesRef = useRef([]);
  const drawCoordsRef = useRef([]);

  /* ── Design state ── */
  const [technology, setTechnology] = useState("solar");
  const [designResult, setDesignResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  /* ── Solar parameters ── */
  const [tilt, setTilt] = useState(25);
  const [azimuth, setAzimuth] = useState(180);
  const [rowSpacing, setRowSpacing] = useState(7);
  const [gcr, setGcr] = useState(0.4);
  const [panelWp, setPanelWp] = useState(580);

  /* ── BESS parameters ── */
  const [containerSize, setContainerSize] = useState("40ft");
  const [mwhPerContainer, setMwhPerContainer] = useState(5);
  const [totalMwh, setTotalMwh] = useState(100);
  const [sourceNoise, setSourceNoise] = useState(85);

  /* ── Hybrid parameters ── */
  const [solarFraction, setSolarFraction] = useState(0.7);

  /* ── Drawing state ── */
  const [activeTool, setActiveTool] = useState(null);
  const activeToolRef = useRef(null);
  useEffect(() => { activeToolRef.current = activeTool; }, [activeTool]);
  const [pointType, setPointType] = useState("substation");
  const pointTypeRef = useRef("substation");
  useEffect(() => { pointTypeRef.current = pointType; }, [pointType]);
  const [drawnBoundary, setDrawnBoundary] = useState(initialBoundary || null);
  const [drawnExclusions, setDrawnExclusions] = useState([]);
  const [drawnRoads, setDrawnRoads] = useState([]);
  const [drawnPoints, setDrawnPoints] = useState([]);
  const [drawingCoords, setDrawingCoords] = useState([]);
  const [measurement, setMeasurement] = useState(null);
  const [undoStack, setUndoStack] = useState([]);

  /* ── Camera ── */
  const [cameraPreset, setCameraPreset] = useState("oblique");

  /* ── Globe ready ── */
  const handleGlobeReady = useCallback((viewer) => {
    viewerRef.current = viewer;
    viewer.scene.globe.depthTestAgainstTerrain = true;

    // If we have an initial location, fly there
    const loc = initialLocation || (drawnBoundary ? centroid(drawnBoundary) : null);
    if (loc) {
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(loc[0], loc[1], 1500),
        orientation: {
          heading: Cesium.Math.toRadians(45),
          pitch: Cesium.Math.toRadians(-35),
          roll: 0,
        },
        duration: 1.5,
      });
    }

    // Click handler for drawing
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click) => handleMapClick(click, viewer), Cesium.ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction((click) => handleMapDoubleClick(click, viewer), Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
  }, [initialLocation, drawnBoundary]);

  /* ── Map click handler ── */
  const handleMapClick = useCallback((click, viewer) => {
    if (!viewer) return;
    const ray = viewer.camera.getPickRay(click.position);
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
    if (!cartesian) return;

    const carto = Cesium.Cartographic.fromCartesian(cartesian);
    const lon = Cesium.Math.toDegrees(carto.longitude);
    const lat = Cesium.Math.toDegrees(carto.latitude);

    const tool = activeToolRef.current;
    if (!tool) return;

    if (tool === "polygon" || tool === "exclusion") {
      setDrawingCoords((prev) => [...prev, [lon, lat]]);
      drawCoordsRef.current = [...drawCoordsRef.current, [lon, lat]];
      _renderDrawingPreview(viewer, [...drawCoordsRef.current, [lon, lat]]);
    } else if (tool === "road") {
      setDrawingCoords((prev) => [...prev, [lon, lat]]);
      drawCoordsRef.current = [...drawCoordsRef.current, [lon, lat]];
      _renderRoadPreview(viewer, drawCoordsRef.current);
    } else if (tool === "point") {
      setDrawnPoints((prev) => [...prev, { lon, lat, type: pointTypeRef.current }]);
      setUndoStack((prev) => [...prev, { action: "add_point" }]);
    } else if (tool === "measure_d") {
      if (drawCoordsRef.current.length === 0) {
        drawCoordsRef.current = [[lon, lat]];
        setDrawingCoords([[lon, lat]]);
      } else {
        const p1 = drawCoordsRef.current[0];
        const dist = haversine(p1[0], p1[1], lon, lat);
        setMeasurement({ type: "distance", value: dist });
        _renderMeasureLine(viewer, p1, [lon, lat], dist);
        drawCoordsRef.current = [];
        setDrawingCoords([]);
      }
    } else if (tool === "measure_a") {
      drawCoordsRef.current = [...drawCoordsRef.current, [lon, lat]];
      setDrawingCoords([...drawCoordsRef.current]);
      if (drawCoordsRef.current.length >= 3) {
        const area = polygonArea(drawCoordsRef.current);
        setMeasurement({ type: "area", value: area });
      }
    }
  }, []);

  /* ── Double-click to close polygon ── */
  const handleMapDoubleClick = useCallback((click, viewer) => {
    const coords = drawCoordsRef.current;
    if (coords.length < 3) return;

    const tool = activeToolRef.current;
    if (tool === "polygon") {
      setDrawnBoundary([...coords]);
      setUndoStack((prev) => [...prev, { action: "set_boundary" }]);
      _clearDrawPreview(viewer);
      drawCoordsRef.current = [];
      setDrawingCoords([]);
      setActiveTool(null);
    } else if (tool === "exclusion") {
      setDrawnExclusions((prev) => [...prev, [...coords]]);
      setUndoStack((prev) => [...prev, { action: "add_exclusion" }]);
      _clearDrawPreview(viewer);
      drawCoordsRef.current = [];
      setDrawingCoords([]);
    } else if (tool === "road") {
      setDrawnRoads((prev) => [...prev, [...coords]]);
      setUndoStack((prev) => [...prev, { action: "add_road" }]);
      _clearDrawPreview(viewer);
      drawCoordsRef.current = [];
      setDrawingCoords([]);
    } else if (tool === "measure_a") {
      drawCoordsRef.current = [];
      setDrawingCoords([]);
    }
  }, []);

  /* ── Drawing preview helpers ── */
  function _renderDrawingPreview(viewer, coords) {
    _clearDrawPreview(viewer);
    if (coords.length < 2) return;

    const positions = coords.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));

    // Polyline
    drawEntitiesRef.current.push(
      viewer.entities.add({
        polyline: {
          positions: [...positions, positions[0]],
          width: 2,
          material: COLORS.drawLine,
          clampToGround: true,
        },
      })
    );

    // Fill
    if (coords.length >= 3) {
      drawEntitiesRef.current.push(
        viewer.entities.add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: COLORS.drawFill,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        })
      );
    }

    // Vertices
    coords.forEach(([lon, lat]) => {
      drawEntitiesRef.current.push(
        viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: {
            pixelSize: 8,
            color: COLORS.drawVertex,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
        })
      );
    });
  }

  function _renderRoadPreview(viewer, coords) {
    _clearDrawPreview(viewer);
    if (coords.length < 2) return;
    const positions = coords.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
    drawEntitiesRef.current.push(
      viewer.entities.add({
        polyline: {
          positions,
          width: 4,
          material: COLORS.road,
          clampToGround: true,
        },
      })
    );
  }

  function _renderMeasureLine(viewer, p1, p2, dist) {
    _clearDrawPreview(viewer);
    const positions = [
      Cesium.Cartesian3.fromDegrees(p1[0], p1[1]),
      Cesium.Cartesian3.fromDegrees(p2[0], p2[1]),
    ];
    drawEntitiesRef.current.push(
      viewer.entities.add({
        polyline: { positions, width: 2, material: Cesium.Color.WHITE, clampToGround: true },
      })
    );
    const mid = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
    drawEntitiesRef.current.push(
      viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(mid[0], mid[1]),
        label: {
          text: `${dist.toFixed(1)} m`,
          font: "13px JetBrains Mono, monospace",
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          pixelOffset: new Cesium.Cartesian2(0, -16),
        },
      })
    );
  }

  function _clearDrawPreview(viewer) {
    drawEntitiesRef.current.forEach((e) => viewer.entities.remove(e));
    drawEntitiesRef.current = [];
  }

  /* ── Tool selection ── */
  const handleToolSelect = useCallback((tool) => {
    setActiveTool(tool);
    drawCoordsRef.current = [];
    setDrawingCoords([]);
    setMeasurement(null);
  }, []);

  /* ── Undo ── */
  const handleUndo = useCallback(() => {
    const stack = [...undoStack];
    const last = stack.pop();
    if (!last) return;
    setUndoStack(stack);

    if (last.action === "set_boundary") setDrawnBoundary(null);
    if (last.action === "add_exclusion") setDrawnExclusions((prev) => prev.slice(0, -1));
    if (last.action === "add_road") setDrawnRoads((prev) => prev.slice(0, -1));
    if (last.action === "add_point") setDrawnPoints((prev) => prev.slice(0, -1));
  }, [undoStack]);

  /* ── Clear all ── */
  const handleClear = useCallback(() => {
    setDrawnBoundary(null);
    setDrawnExclusions([]);
    setDrawnRoads([]);
    setDrawnPoints([]);
    setDesignResult(null);
    setMeasurement(null);
    setUndoStack([]);
    const viewer = viewerRef.current;
    if (viewer) {
      _clearDrawPreview(viewer);
      designEntitiesRef.current.forEach((e) => viewer.entities.remove(e));
      designEntitiesRef.current = [];
    }
  }, []);

  /* ── Auto-design ── */
  const handleAutoDesign = useCallback(async () => {
    if (!drawnBoundary || drawnBoundary.length < 3) return;
    setLoading(true);

    const boundary_geojson = {
      type: "Polygon",
      coordinates: [[...drawnBoundary, drawnBoundary[0]]],
    };

    const params = {};
    if (technology === "solar" || technology === "hybrid") {
      params.tilt = tilt;
      params.azimuth = azimuth;
      params.row_spacing = rowSpacing;
      params.gcr = gcr;
      params.panel_wp = panelWp;
    }
    if (technology === "bess" || technology === "hybrid") {
      params.container_size = containerSize;
      params.mwh_per_container = mwhPerContainer;
      params.total_mwh = totalMwh;
      params.source_noise_dba = sourceNoise;
    }
    if (technology === "hybrid") {
      params.solar_fraction = solarFraction;
    }

    try {
      const result = await api.design.autoLayout(boundary_geojson, technology, params);
      if (result) setDesignResult(result);
    } catch (e) {
      console.warn("[SiteDesigner3D] Auto-design error:", e);
    } finally {
      setLoading(false);
    }
  }, [drawnBoundary, technology, tilt, azimuth, rowSpacing, gcr, panelWp,
      containerSize, mwhPerContainer, totalMwh, sourceNoise, solarFraction]);

  /* ── Render design result onto Cesium globe ── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    // Clear previous design entities
    designEntitiesRef.current.forEach((e) => viewer.entities.remove(e));
    designEntitiesRef.current = [];

    if (!designResult) return;

    const add = (opts) => {
      const e = viewer.entities.add(opts);
      designEntitiesRef.current.push(e);
      return e;
    };

    // ── Site boundary ──
    if (designResult.boundary) {
      const bCoords = designResult.boundary.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
      add({
        polyline: {
          positions: [...bCoords, bCoords[0]],
          width: 2.5,
          material: new Cesium.PolylineDashMaterialProperty({
            color: COLORS.boundary,
            dashLength: 12,
          }),
          clampToGround: true,
        },
      });

      // Area label
      const bc = centroid(designResult.boundary);
      const areaHa = designResult.metrics?.area_total_ha || 0;
      add({
        position: Cesium.Cartesian3.fromDegrees(bc[0], bc[1]),
        label: {
          text: `Total Lease Area \u2014 ${areaHa.toFixed(2)} ha`,
          font: "bold 14px DM Sans, sans-serif",
          fillColor: COLORS.label,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          pixelOffset: new Cesium.Cartesian2(0, -24),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }

    // ── Solar panels ──
    if (designResult.panels?.length) {
      designResult.panels.forEach((panel, i) => {
        const positions = panel.polygon.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));

        // Panel fill — terrain-following
        add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: COLORS.solarPanel,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });

        // Panel outline
        add({
          polyline: {
            positions,
            width: 1,
            material: COLORS.solarOutline,
            clampToGround: true,
          },
        });

        // Label every 5th row
        if (i % 5 === 0) {
          const pc = centroid(panel.polygon.slice(0, -1));
          add({
            position: Cesium.Cartesian3.fromDegrees(pc[0], pc[1]),
            label: {
              text: `${panel.label} \u2014 ${panel.capacity_kwp} kWp`,
              font: "11px JetBrains Mono, monospace",
              fillColor: Cesium.Color.fromCssColorString("rgba(200, 210, 255, 0.85)"),
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
              pixelOffset: new Cesium.Cartesian2(0, -10),
              scaleByDistance: new Cesium.NearFarScalar(200, 1, 3000, 0.3),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        }
      });

      // PV area label
      if (designResult.panels.length > 0) {
        const allPanelCoords = designResult.panels.flatMap((p) => p.polygon.slice(0, -1));
        const pvCenter = centroid(allPanelCoords);
        const pvAreaHa = designResult.metrics?.area_used_ha || 0;
        add({
          position: Cesium.Cartesian3.fromDegrees(pvCenter[0], pvCenter[1]),
          label: {
            text: `PV Area \u2014 ${pvAreaHa.toFixed(2)} ha \u2014 ${designResult.metrics?.total_capacity_mwp?.toFixed(1) || "?"} MWp`,
            font: "bold 13px DM Sans, sans-serif",
            fillColor: Cesium.Color.fromCssColorString("rgba(140, 160, 255, 0.95)"),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            pixelOffset: new Cesium.Cartesian2(0, 20),
            scaleByDistance: new Cesium.NearFarScalar(300, 1, 5000, 0.4),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      }
    }

    // ── BESS containers ──
    if (designResult.containers?.length) {
      designResult.containers.forEach((container) => {
        const [cx, cy] = container.center;
        const [len, wid, hgt] = container.dimensions || [12.2, 2.44, 2.59];
        const isTx = container.type === "transformer";

        add({
          position: Cesium.Cartesian3.fromDegrees(cx, cy, hgt / 2),
          box: {
            dimensions: new Cesium.Cartesian3(len, wid, hgt),
            material: isTx ? COLORS.transformer : COLORS.bessContainer,
            outline: true,
            outlineColor: COLORS.bessEdge,
            outlineWidth: 1.5,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          },
          label: {
            text: container.label || "",
            font: "10px JetBrains Mono, monospace",
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
            pixelOffset: new Cesium.Cartesian2(0, -20),
            scaleByDistance: new Cesium.NearFarScalar(100, 1, 2000, 0),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      });

      // BESS area label
      const bessContainers = designResult.containers.filter((c) => c.type === "battery");
      if (bessContainers.length > 0) {
        const bessCenters = bessContainers.map((c) => c.center);
        const bessCenter = centroid(bessCenters);
        add({
          position: Cesium.Cartesian3.fromDegrees(bessCenter[0], bessCenter[1], 8),
          label: {
            text: `BESS \u2014 ${designResult.metrics?.total_capacity_mwh || "?"} MWh \u2014 ${bessContainers.length} containers`,
            font: "bold 13px DM Sans, sans-serif",
            fillColor: Cesium.Color.fromCssColorString("rgba(200, 210, 220, 0.95)"),
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
            pixelOffset: new Cesium.Cartesian2(0, -30),
            scaleByDistance: new Cesium.NearFarScalar(200, 1, 3000, 0.4),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      }
    }

    // ── Perimeter fence ──
    if (designResult.fence) {
      const fencePositions = designResult.fence.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
      add({
        polyline: {
          positions: fencePositions,
          width: 2,
          material: COLORS.fence,
          clampToGround: true,
        },
      });

      // Fence posts
      designResult.fence.slice(0, -1).forEach(([lon, lat]) => {
        add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat, 1.2),
          box: {
            dimensions: new Cesium.Cartesian3(0.15, 0.15, 2.4),
            material: COLORS.fence,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          },
        });
      });
    }

    // ── Tree screen ──
    if (designResult.tree_screen) {
      const tsPositions = designResult.tree_screen.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
      add({
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(tsPositions),
          material: COLORS.treeScreen,
          classificationType: Cesium.ClassificationType.TERRAIN,
        },
      });

      // Tree billboards along perimeter
      const treeCoords = designResult.tree_screen.slice(0, -1);
      for (let i = 0; i < treeCoords.length - 1; i++) {
        const [x1, y1] = treeCoords[i];
        const [x2, y2] = treeCoords[i + 1];
        const dist = haversine(x1, y1, x2, y2);
        const nTrees = Math.max(1, Math.floor(dist / 4)); // tree every 4m
        for (let t = 0; t < nTrees; t++) {
          const frac = (t + 0.5) / nTrees;
          const tx = x1 + (x2 - x1) * frac;
          const ty = y1 + (y2 - y1) * frac;
          add({
            position: Cesium.Cartesian3.fromDegrees(tx, ty, 3),
            ellipsoid: {
              radii: new Cesium.Cartesian3(2, 2, 3),
              material: Cesium.Color.fromCssColorString("rgba(34, 120, 50, 0.7)"),
              heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
            },
          });
        }
      }
    }

    // ── Noise contours ──
    if (designResult.noise_contours?.length) {
      designResult.noise_contours.forEach((contour) => {
        const positions = contour.polygon.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
        const dba = contour.dba_level;
        const colors = NOISE_COLORS[dba] || NOISE_COLORS[40];

        // Fill
        add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: colors.fill,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });

        // Outline
        add({
          polyline: {
            positions: [...positions, positions[0]],
            width: 1.5,
            material: colors.line,
            clampToGround: true,
          },
        });

        // Label
        const nc = centroid(contour.polygon);
        const labelAngle = Math.PI / 4; // 45 degrees
        const labelR = contour.radius_m * 0.008; // approximate degree offset
        add({
          position: Cesium.Cartesian3.fromDegrees(
            nc[0] + labelR * Math.cos(labelAngle),
            nc[1] + labelR * Math.sin(labelAngle)
          ),
          label: {
            text: `${dba} dBA`,
            font: "bold 11px JetBrains Mono, monospace",
            fillColor: colors.line,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            scaleByDistance: new Cesium.NearFarScalar(300, 1, 5000, 0.3),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      });
    }

    // ── Exclusion zones / fire breaks ──
    if (designResult.exclusions?.length) {
      designResult.exclusions.forEach((exc) => {
        const coords = exc.polygon || exc.inner;
        if (!coords) return;
        const positions = coords.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));

        add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: exc.reason?.includes("Fire") ? COLORS.fireBreak : COLORS.exclusion,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });

        add({
          polyline: {
            positions: [...positions, positions[0]],
            width: 1.5,
            material: COLORS.exclusionLine,
            clampToGround: true,
          },
        });

        // Reason label
        if (exc.reason) {
          const ec = centroid(coords);
          add({
            position: Cesium.Cartesian3.fromDegrees(ec[0], ec[1]),
            label: {
              text: exc.reason,
              font: "10px DM Sans, sans-serif",
              fillColor: Cesium.Color.fromCssColorString("rgba(218, 30, 40, 0.8)"),
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
              scaleByDistance: new Cesium.NearFarScalar(200, 1, 2000, 0),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        }
      });
    }

    // ── Access roads ──
    if (designResult.roads?.length) {
      designResult.roads.forEach((road) => {
        const coords = road.line || road;
        const positions = coords.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
        add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: COLORS.road,
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });
      });
    }

    // ── Infrastructure points ──
    if (designResult.infrastructure?.length) {
      designResult.infrastructure.forEach((inf) => {
        const [lon, lat] = inf.point;
        const boxSize = inf.type === "substation" ? [8, 6, 4] : inf.type === "inverter" ? [3, 2, 2] : [2, 2, 3];
        const color = inf.type === "substation" ? COLORS.substation
                    : inf.type === "inverter" ? COLORS.inverter
                    : COLORS.gate;

        add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat, boxSize[2] / 2),
          box: {
            dimensions: new Cesium.Cartesian3(boxSize[0], boxSize[1], boxSize[2]),
            material: color,
            outline: true,
            outlineColor: Cesium.Color.BLACK.withAlpha(0.5),
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          },
          label: {
            text: inf.label || inf.type,
            font: "11px DM Sans, sans-serif",
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
            pixelOffset: new Cesium.Cartesian2(0, -24),
            scaleByDistance: new Cesium.NearFarScalar(100, 1, 2000, 0.3),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      });
    }

    // ── Drawn points (user-placed) ──
    drawnPoints.forEach((pt) => {
      const boxSize = pt.type === "substation" ? [8, 6, 4] : pt.type === "transformer" ? [4, 3, 3] : [3, 2, 2];
      const color = pt.type === "substation" ? COLORS.substation
                  : pt.type === "transformer" ? COLORS.transformer
                  : pt.type === "inverter" ? COLORS.inverter
                  : COLORS.gate;
      add({
        position: Cesium.Cartesian3.fromDegrees(pt.lon, pt.lat, boxSize[2] / 2),
        box: {
          dimensions: new Cesium.Cartesian3(boxSize[0], boxSize[1], boxSize[2]),
          material: color,
          outline: true,
          outlineColor: Cesium.Color.BLACK.withAlpha(0.5),
          heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        },
        label: {
          text: pt.type,
          font: "11px DM Sans, sans-serif",
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          pixelOffset: new Cesium.Cartesian2(0, -24),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    });

    // ── Fly camera to design ──
    if (designResult.boundary) {
      const bc = centroid(designResult.boundary);
      flyToPreset(viewer, bc, "oblique");
    }
  }, [designResult, drawnPoints]);

  /* ── Camera presets ── */
  function flyToPreset(viewer, center, presetId) {
    if (!viewer || !center) return;
    const preset = CAMERA_PRESETS.find((p) => p.id === presetId) || CAMERA_PRESETS[3];
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(center[0], center[1], preset.height),
      orientation: {
        heading: Cesium.Math.toRadians(preset.heading),
        pitch: Cesium.Math.toRadians(preset.pitch),
        roll: 0,
      },
      duration: 1.5,
    });
  }

  const handleCameraPreset = useCallback((presetId) => {
    setCameraPreset(presetId);
    const viewer = viewerRef.current;
    const center = designResult?.boundary
      ? centroid(designResult.boundary)
      : drawnBoundary
        ? centroid(drawnBoundary)
        : initialLocation;
    if (center) flyToPreset(viewer, center, presetId);
  }, [designResult, drawnBoundary, initialLocation]);

  /* ── Metrics summary ── */
  const metrics = designResult?.metrics || {};

  /* ── Export KML (basic) ── */
  const handleExportKML = useCallback(() => {
    if (!designResult) return;
    const bc = centroid(designResult.boundary || []);
    let kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>Site Design Export</name>`;

    if (designResult.boundary) {
      const ring = designResult.boundary.map(([lon, lat]) => `${lon},${lat},0`).join(" ");
      kml += `
<Placemark>
  <name>Site Boundary</name>
  <Polygon><outerBoundaryIs><LinearRing><coordinates>${ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark>`;
    }

    kml += `\n</Document>\n</kml>`;
    const blob = new Blob([kml], { type: "application/vnd.google-earth.kml+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "site-design.kml";
    a.click();
    URL.revokeObjectURL(url);
  }, [designResult]);

  /* ── Render ── */
  return (
    <div className="sd-root">
      {/* Cesium Globe (non-dark for satellite imagery) */}
      <CesiumGlobe
        onReady={handleGlobeReady}
        darkMode={false}
        showTerrain={true}
        showBuildings={true}
        show3DTiles={false}
        initialView={initialLocation ? { lon: initialLocation[0], lat: initialLocation[1], height: 1500, heading: 45, pitch: -35 } : undefined}
        className="sd-globe"
      />

      {/* Close button */}
      <button className="sd-close" onClick={onClose} title="Close Site Designer">
        &#x2715;
      </button>

      {/* Camera presets — top right */}
      <div className="sd-camera-bar">
        {CAMERA_PRESETS.map((p) => (
          <button
            key={p.id}
            className={`sd-camera-btn ${cameraPreset === p.id ? "sd-camera-active" : ""}`}
            onClick={() => handleCameraPreset(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Design Configuration Sidebar */}
      {sidebarOpen && (
        <div className="sd-sidebar">
          <div className="sd-sidebar-header">
            <h3 className="sd-sidebar-title">Site Design</h3>
            <button className="sd-sidebar-toggle" onClick={() => setSidebarOpen(false)}>&#x25C0;</button>
          </div>

          {/* Technology selector */}
          <div className="sd-section">
            <label className="sd-label">Technology</label>
            <div className="sd-btn-group">
              {["solar", "bess", "hybrid"].map((t) => (
                <button
                  key={t}
                  className={`sd-tech-btn ${technology === t ? "sd-tech-active" : ""}`}
                  onClick={() => setTechnology(t)}
                >
                  {t === "solar" ? "Solar PV" : t === "bess" ? "BESS" : "Hybrid"}
                </button>
              ))}
            </div>
          </div>

          {/* Solar parameters */}
          {(technology === "solar" || technology === "hybrid") && (
            <div className="sd-section">
              <label className="sd-label">Solar Parameters</label>
              <div className="sd-param">
                <span>Tilt</span>
                <input type="range" min={0} max={45} value={tilt} onChange={(e) => setTilt(+e.target.value)} />
                <span className="sd-param-val">{tilt}deg</span>
              </div>
              <div className="sd-param">
                <span>Azimuth</span>
                <input type="range" min={90} max={270} value={azimuth} onChange={(e) => setAzimuth(+e.target.value)} />
                <span className="sd-param-val">{azimuth}deg</span>
              </div>
              <div className="sd-param">
                <span>Row Spacing</span>
                <input type="range" min={4} max={15} step={0.5} value={rowSpacing} onChange={(e) => setRowSpacing(+e.target.value)} />
                <span className="sd-param-val">{rowSpacing}m</span>
              </div>
              <div className="sd-param">
                <span>GCR</span>
                <input type="range" min={0.2} max={0.6} step={0.05} value={gcr} onChange={(e) => setGcr(+e.target.value)} />
                <span className="sd-param-val">{gcr.toFixed(2)}</span>
              </div>
              <div className="sd-param">
                <span>Panel Wp</span>
                <input type="number" min={300} max={800} value={panelWp} onChange={(e) => setPanelWp(+e.target.value)} className="sd-input-num" />
              </div>
            </div>
          )}

          {/* BESS parameters */}
          {(technology === "bess" || technology === "hybrid") && (
            <div className="sd-section">
              <label className="sd-label">BESS Parameters</label>
              <div className="sd-param">
                <span>Container</span>
                <select value={containerSize} onChange={(e) => setContainerSize(e.target.value)} className="sd-select">
                  <option value="20ft">20ft (2-5 MWh)</option>
                  <option value="40ft">40ft (5-10 MWh)</option>
                </select>
              </div>
              <div className="sd-param">
                <span>MWh/unit</span>
                <input type="number" min={1} max={15} step={0.5} value={mwhPerContainer} onChange={(e) => setMwhPerContainer(+e.target.value)} className="sd-input-num" />
              </div>
              <div className="sd-param">
                <span>Total MWh</span>
                <input type="number" min={10} max={1000} step={10} value={totalMwh} onChange={(e) => setTotalMwh(+e.target.value)} className="sd-input-num" />
              </div>
              <div className="sd-param">
                <span>Noise (dBA)</span>
                <input type="range" min={70} max={100} value={sourceNoise} onChange={(e) => setSourceNoise(+e.target.value)} />
                <span className="sd-param-val">{sourceNoise}</span>
              </div>
            </div>
          )}

          {/* Hybrid fraction */}
          {technology === "hybrid" && (
            <div className="sd-section">
              <label className="sd-label">Hybrid Split</label>
              <div className="sd-param">
                <span>Solar %</span>
                <input type="range" min={0.3} max={0.9} step={0.05} value={solarFraction} onChange={(e) => setSolarFraction(+e.target.value)} />
                <span className="sd-param-val">{(solarFraction * 100).toFixed(0)}%</span>
              </div>
            </div>
          )}

          {/* Boundary status */}
          <div className="sd-section">
            <label className="sd-label">Boundary</label>
            {drawnBoundary ? (
              <div className="sd-boundary-status sd-boundary-ok">
                {drawnBoundary.length} vertices — {(polygonArea(drawnBoundary) / 10000).toFixed(2)} ha
              </div>
            ) : (
              <div className="sd-boundary-status sd-boundary-none">
                Use the toolbar to draw a site boundary
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="sd-section">
            <button
              className="sd-btn-primary"
              onClick={handleAutoDesign}
              disabled={!drawnBoundary || loading}
            >
              {loading ? "Generating..." : "Auto-Design"}
            </button>
            <button className="sd-btn-secondary" onClick={handleExportKML} disabled={!designResult}>
              Export KML
            </button>
          </div>

          {/* Metrics */}
          {designResult && (
            <div className="sd-section sd-metrics">
              <label className="sd-label">Design Metrics</label>
              {metrics.total_capacity_mwp > 0 && (
                <div className="sd-metric-row">
                  <span>Solar Capacity</span>
                  <span className="sd-metric-val">{metrics.total_capacity_mwp?.toFixed(1)} MWp</span>
                </div>
              )}
              {metrics.total_capacity_mwh > 0 && (
                <div className="sd-metric-row">
                  <span>Storage Capacity</span>
                  <span className="sd-metric-val">{metrics.total_capacity_mwh} MWh</span>
                </div>
              )}
              <div className="sd-metric-row">
                <span>Total Area</span>
                <span className="sd-metric-val">{metrics.area_total_ha?.toFixed(2)} ha</span>
              </div>
              <div className="sd-metric-row">
                <span>Usable Area</span>
                <span className="sd-metric-val">{metrics.area_used_ha?.toFixed(2)} ha</span>
              </div>
              {metrics.panel_count > 0 && (
                <div className="sd-metric-row">
                  <span>Panels</span>
                  <span className="sd-metric-val">{fmtNum(metrics.panel_count)}</span>
                </div>
              )}
              {metrics.container_count > 0 && (
                <div className="sd-metric-row">
                  <span>Containers</span>
                  <span className="sd-metric-val">{metrics.container_count}</span>
                </div>
              )}
              {metrics.string_count > 0 && (
                <div className="sd-metric-row">
                  <span>Strings</span>
                  <span className="sd-metric-val">{metrics.string_count}</span>
                </div>
              )}
              {metrics.row_count > 0 && (
                <div className="sd-metric-row">
                  <span>Rows</span>
                  <span className="sd-metric-val">{metrics.row_count}</span>
                </div>
              )}
              {metrics.noise_45dba_radius_m > 0 && (
                <>
                  <div className="sd-metric-divider" />
                  <div className="sd-metric-row">
                    <span>45 dBA radius</span>
                    <span className="sd-metric-val">{metrics.noise_45dba_radius_m} m</span>
                  </div>
                  <div className="sd-metric-row">
                    <span>40 dBA radius</span>
                    <span className="sd-metric-val">{metrics.noise_40dba_radius_m} m</span>
                  </div>
                  <div className="sd-metric-row">
                    <span>35 dBA radius</span>
                    <span className="sd-metric-val">{metrics.noise_35dba_radius_m} m</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Collapsed sidebar toggle */}
      {!sidebarOpen && (
        <button className="sd-sidebar-show" onClick={() => setSidebarOpen(true)}>
          &#x25B6; Design
        </button>
      )}

      {/* Drawing Toolbar */}
      <SiteDesignToolbar
        activeTool={activeTool}
        onToolSelect={handleToolSelect}
        onUndo={handleUndo}
        onClear={handleClear}
        pointType={pointType}
        onPointTypeChange={setPointType}
        measurement={measurement}
      />

      {/* Loading overlay */}
      {loading && (
        <div className="sd-loading">
          <div className="sd-spinner" />
          <span>Generating {technology} layout...</span>
        </div>
      )}
    </div>
  );
}
