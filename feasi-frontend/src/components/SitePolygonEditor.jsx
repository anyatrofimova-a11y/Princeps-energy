/**
 * SitePolygonEditor — deck.gl-native polygon drawing & editing on Mapbox GL.
 *
 * Modes: draw_polygon, draw_rect, draw_line, draw_point, select, translate, rotate.
 * Features stored as GeoJSON FeatureCollection, color-coded by type.
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer, ScatterplotLayer, PathLayer } from "@deck.gl/layers";
import SiteDesignToolbarV2 from "./SiteDesignToolbarV2";

const TYPE_COLORS = {
  site_boundary:  [0, 220, 255],
  exclusion_zone: [218, 30, 40],
  solar_array:    [100, 120, 220],
  bess_pad:       [36, 161, 72],
  dc_building:    [147, 51, 234],
  access_road:    [212, 160, 24],
  substation:     [120, 144, 156],
};

function featureColor(f) {
  return TYPE_COLORS[f?.properties?.featureType] || [200, 200, 200];
}

function centroid(coords) {
  if (!coords?.length) return [0, 0];
  const ring = coords[0] || coords;
  const pts = Array.isArray(ring[0]) ? ring : [ring];
  let sx = 0, sy = 0;
  for (const p of pts) { sx += p[0]; sy += p[1]; }
  return [sx / pts.length, sy / pts.length];
}

function rotateCoords(coords, angleDeg, origin) {
  const rad = (angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return coords.map((ring) =>
    (Array.isArray(ring[0]) ? ring : [ring]).map(([x, y]) => {
      const dx = x - origin[0], dy = y - origin[1];
      return [origin[0] + dx * cos - dy * sin, origin[1] + dx * sin + dy * cos];
    })
  );
}

export default function SitePolygonEditor({ map, features: controlledFeatures, onFeaturesChange, visible = true }) {
  const [features, setFeaturesLocal] = useState({ type: "FeatureCollection", features: [] });
  const [mode, setMode] = useState("view");
  const [featureType, setFeatureType] = useState("site_boundary");
  const [drawingCoords, setDrawingCoords] = useState([]);
  const [cursorPos, setCursorPos] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [dragStart, setDragStart] = useState(null);
  const [rotateStart, setRotateStart] = useState(null);
  const [undoStack, setUndoStack] = useState([]);
  const overlayRef = useRef(null);

  // Controlled or uncontrolled
  const fc = controlledFeatures || features;
  const setFC = useCallback((next) => {
    const val = typeof next === "function" ? next(fc) : next;
    setUndoStack((s) => [...s.slice(-20), fc]);
    if (onFeaturesChange) onFeaturesChange(val);
    else setFeaturesLocal(val);
  }, [fc, onFeaturesChange]);

  // --- Overlay setup ---
  useEffect(() => {
    if (!map || !visible) return;
    const overlay = new MapboxOverlay({ layers: [] });
    map.addControl(overlay);
    overlayRef.current = overlay;
    return () => { try { map.removeControl(overlay); } catch {} };
  }, [map, visible]);

  // --- Build layers ---
  const layers = useMemo(() => {
    if (!visible) return [];
    const out = [];

    // Existing features
    out.push(new GeoJsonLayer({
      id: "site-editor-features",
      data: fc,
      getFillColor: (f) => [...featureColor(f), 50],
      getLineColor: (f) => {
        const c = featureColor(f);
        const idx = fc.features.indexOf(f);
        return idx === selectedIdx ? [212, 160, 24, 255] : [...c, 200];
      },
      getLineWidth: (f) => fc.features.indexOf(f) === selectedIdx ? 3 : 1.5,
      lineWidthUnits: "pixels",
      getPointRadius: 6,
      pointRadiusUnits: "pixels",
      pickable: mode === "select" || mode === "translate" || mode === "rotate",
      onClick: ({ index }) => {
        if (mode === "select" || mode === "translate" || mode === "rotate") {
          setSelectedIdx(index >= 0 ? index : null);
        }
      },
    }));

    // Drawing preview
    if (drawingCoords.length > 0 && cursorPos) {
      const previewCoords = [...drawingCoords, cursorPos];
      if (mode === "draw_polygon" && previewCoords.length >= 3) {
        out.push(new GeoJsonLayer({
          id: "site-editor-preview",
          data: { type: "Feature", geometry: { type: "Polygon", coordinates: [[...previewCoords, previewCoords[0]]] }, properties: {} },
          getFillColor: [...(TYPE_COLORS[featureType] || [200, 200, 200]), 30],
          getLineColor: [212, 160, 24, 180],
          getLineWidth: 2,
          lineWidthUnits: "pixels",
        }));
      } else if (mode === "draw_rect" && previewCoords.length >= 1) {
        const [a, b] = [drawingCoords[0], cursorPos];
        if (a && b) {
          out.push(new GeoJsonLayer({
            id: "site-editor-preview-rect",
            data: { type: "Feature", geometry: { type: "Polygon", coordinates: [[[a[0],a[1]], [b[0],a[1]], [b[0],b[1]], [a[0],b[1]], [a[0],a[1]]]] }, properties: {} },
            getFillColor: [...(TYPE_COLORS[featureType] || [200, 200, 200]), 30],
            getLineColor: [212, 160, 24, 180],
            getLineWidth: 2,
            lineWidthUnits: "pixels",
          }));
        }
      } else if ((mode === "draw_line" || mode === "draw_polygon") && previewCoords.length >= 2) {
        out.push(new PathLayer({
          id: "site-editor-preview-line",
          data: [{ path: previewCoords }],
          getPath: (d) => d.path,
          getColor: [212, 160, 24, 180],
          getWidth: 2,
          widthUnits: "pixels",
        }));
      }

      // Vertices
      out.push(new ScatterplotLayer({
        id: "site-editor-vertices",
        data: previewCoords.map((c) => ({ position: c })),
        getPosition: (d) => d.position,
        getRadius: 5,
        radiusUnits: "pixels",
        getFillColor: [212, 160, 24, 255],
        getLineColor: [0, 0, 0, 255],
        getLineWidth: 1,
        lineWidthUnits: "pixels",
        stroked: true,
      }));
    }

    // Selected feature vertices (for vertex editing)
    if (selectedIdx != null && fc.features[selectedIdx]) {
      const sel = fc.features[selectedIdx];
      const coords = sel.geometry?.type === "Polygon" ? sel.geometry.coordinates[0] :
                     sel.geometry?.type === "LineString" ? sel.geometry.coordinates : [];
      if (coords.length) {
        out.push(new ScatterplotLayer({
          id: "site-editor-sel-vertices",
          data: coords.map((c, i) => ({ position: c, idx: i })),
          getPosition: (d) => d.position,
          getRadius: 5,
          radiusUnits: "pixels",
          getFillColor: [255, 255, 255, 255],
          getLineColor: [212, 160, 24, 255],
          getLineWidth: 2,
          lineWidthUnits: "pixels",
          stroked: true,
          pickable: true,
        }));
      }
    }

    return out;
  }, [fc, mode, drawingCoords, cursorPos, selectedIdx, featureType, visible]);

  // Update overlay
  useEffect(() => {
    if (overlayRef.current) overlayRef.current.setProps({ layers });
  }, [layers]);

  // --- Map event handlers ---
  useEffect(() => {
    if (!map || !visible) return;

    const onClick = (e) => {
      const lngLat = [e.lngLat.lng, e.lngLat.lat];

      if (mode === "draw_polygon" || mode === "draw_line") {
        setDrawingCoords((prev) => [...prev, lngLat]);
      } else if (mode === "draw_rect") {
        if (drawingCoords.length === 0) {
          setDrawingCoords([lngLat]);
        } else {
          const [a, b] = [drawingCoords[0], lngLat];
          const ring = [[a[0],a[1]], [b[0],a[1]], [b[0],b[1]], [a[0],b[1]], [a[0],a[1]]];
          const feat = { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { featureType, id: Date.now() } };
          setFC((prev) => ({ ...prev, features: [...prev.features, feat] }));
          setDrawingCoords([]);
        }
      } else if (mode === "draw_point") {
        const feat = { type: "Feature", geometry: { type: "Point", coordinates: lngLat }, properties: { featureType, id: Date.now() } };
        setFC((prev) => ({ ...prev, features: [...prev.features, feat] }));
      }
    };

    const onDblClick = (e) => {
      if (mode === "draw_polygon" && drawingCoords.length >= 3) {
        e.preventDefault();
        const ring = [...drawingCoords, drawingCoords[0]];
        const feat = { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { featureType, id: Date.now() } };
        setFC((prev) => ({ ...prev, features: [...prev.features, feat] }));
        setDrawingCoords([]);
      } else if (mode === "draw_line" && drawingCoords.length >= 2) {
        e.preventDefault();
        const feat = { type: "Feature", geometry: { type: "LineString", coordinates: drawingCoords }, properties: { featureType, id: Date.now() } };
        setFC((prev) => ({ ...prev, features: [...prev.features, feat] }));
        setDrawingCoords([]);
      }
    };

    const onMouseMove = (e) => {
      setCursorPos([e.lngLat.lng, e.lngLat.lat]);
    };

    const onMouseDown = (e) => {
      if (mode === "translate" && selectedIdx != null) {
        setDragStart([e.lngLat.lng, e.lngLat.lat]);
        map.dragPan.disable();
      } else if (mode === "rotate" && selectedIdx != null) {
        setRotateStart([e.lngLat.lng, e.lngLat.lat]);
        map.dragPan.disable();
      }
    };

    const onMouseUp = () => {
      if (dragStart || rotateStart) {
        map.dragPan.enable();
        setDragStart(null);
        setRotateStart(null);
      }
    };

    const onDrag = (e) => {
      const pos = [e.lngLat.lng, e.lngLat.lat];
      if (mode === "translate" && dragStart && selectedIdx != null) {
        const dx = pos[0] - dragStart[0];
        const dy = pos[1] - dragStart[1];
        setFC((prev) => {
          const updated = { ...prev, features: [...prev.features] };
          const f = { ...updated.features[selectedIdx] };
          const g = { ...f.geometry };
          if (g.type === "Polygon") {
            g.coordinates = g.coordinates.map((ring) => ring.map(([x, y]) => [x + dx, y + dy]));
          } else if (g.type === "LineString") {
            g.coordinates = g.coordinates.map(([x, y]) => [x + dx, y + dy]);
          } else if (g.type === "Point") {
            g.coordinates = [g.coordinates[0] + dx, g.coordinates[1] + dy];
          }
          f.geometry = g;
          updated.features[selectedIdx] = f;
          return updated;
        });
        setDragStart(pos);
      } else if (mode === "rotate" && rotateStart && selectedIdx != null) {
        const f = fc.features[selectedIdx];
        const c = centroid(f.geometry.coordinates);
        const a1 = Math.atan2(rotateStart[1] - c[1], rotateStart[0] - c[0]);
        const a2 = Math.atan2(pos[1] - c[1], pos[0] - c[0]);
        const angleDeg = ((a2 - a1) * 180) / Math.PI;
        setFC((prev) => {
          const updated = { ...prev, features: [...prev.features] };
          const feat = { ...updated.features[selectedIdx] };
          const g = { ...feat.geometry };
          if (g.type === "Polygon") {
            g.coordinates = rotateCoords(g.coordinates, angleDeg, c);
          } else if (g.type === "LineString") {
            g.coordinates = rotateCoords([g.coordinates], angleDeg, c)[0];
          }
          feat.geometry = g;
          updated.features[selectedIdx] = feat;
          return updated;
        });
        setRotateStart(pos);
      }
    };

    map.on("click", onClick);
    map.on("dblclick", onDblClick);
    map.on("mousemove", onMouseMove);
    map.on("mousedown", onMouseDown);
    map.on("mouseup", onMouseUp);
    map.on("mousemove", onDrag);

    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDblClick);
      map.off("mousemove", onMouseMove);
      map.off("mousedown", onMouseDown);
      map.off("mouseup", onMouseUp);
      map.off("mousemove", onDrag);
    };
  }, [map, mode, drawingCoords, selectedIdx, dragStart, rotateStart, featureType, visible, fc, setFC]);

  // Keyboard
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        setMode("view");
        setDrawingCoords([]);
        setSelectedIdx(null);
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selectedIdx != null) {
        setFC((prev) => ({
          ...prev,
          features: prev.features.filter((_, i) => i !== selectedIdx),
        }));
        setSelectedIdx(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedIdx, setFC]);

  // Cursor style
  useEffect(() => {
    if (!map) return;
    const canvas = map.getCanvas();
    if (mode.startsWith("draw")) canvas.style.cursor = "crosshair";
    else if (mode === "translate") canvas.style.cursor = "move";
    else if (mode === "rotate") canvas.style.cursor = "grab";
    else canvas.style.cursor = "";
    return () => { canvas.style.cursor = ""; };
  }, [map, mode]);

  const handleUndo = useCallback(() => {
    if (undoStack.length === 0) return;
    const prev = undoStack[undoStack.length - 1];
    setUndoStack((s) => s.slice(0, -1));
    if (onFeaturesChange) onFeaturesChange(prev);
    else setFeaturesLocal(prev);
  }, [undoStack, onFeaturesChange]);

  const handleDelete = useCallback(() => {
    if (selectedIdx == null) return;
    setFC((prev) => ({
      ...prev,
      features: prev.features.filter((_, i) => i !== selectedIdx),
    }));
    setSelectedIdx(null);
  }, [selectedIdx, setFC]);

  if (!visible) return null;

  return (
    <SiteDesignToolbarV2
      mode={mode}
      onModeChange={(m) => { setMode(m); setDrawingCoords([]); setSelectedIdx(null); }}
      featureType={featureType}
      onFeatureTypeChange={setFeatureType}
      featureCount={fc.features.length}
      onDelete={handleDelete}
      onUndo={handleUndo}
    />
  );
}
