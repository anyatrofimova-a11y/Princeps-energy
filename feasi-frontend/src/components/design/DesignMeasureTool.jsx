/**
 * DesignMeasureTool — ruler + area tool that runs on top of a Mapbox map.
 *
 * Two modes:
 *   - "distance": click points, double-click to finish, shows running total
 *     + per-segment length + midpoint labels.
 *   - "area":     click to build a polygon, double-click to close, shows
 *                 area in m² / ha at centroid.
 *
 * Keyboard: Esc cancels, Enter commits the current path.
 *
 * Implementation: we add a dedicated GeoJSON source + 3 layers
 * (measure-line, measure-points, measure-labels) and maintain a vertex
 * array in local state. Cleaned up on unmount or mode switch.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";

const SRC_ID = "design-measure";
const LINE_LAYER = "design-measure-line";
const FILL_LAYER = "design-measure-fill";
const POINTS_LAYER = "design-measure-points";
const LABELS_LAYER = "design-measure-labels";

/**
 * Haversine distance in metres between two [lon, lat] pairs.
 */
function haversine(a, b) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/**
 * Shoelace area for a lon/lat polygon, converted to m² using a local
 * equirectangular approximation at the polygon centroid. Good enough for
 * site-scale features (<< 1 km²).
 */
function polygonAreaM2(ring) {
  if (ring.length < 3) return 0;
  const lat0 = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  const mPerDegLat = 111_320;
  const mPerDegLon = 111_320 * Math.cos((lat0 * Math.PI) / 180);
  let area2 = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    area2 += (x1 * mPerDegLon) * (y2 * mPerDegLat) - (x2 * mPerDegLon) * (y1 * mPerDegLat);
  }
  return Math.abs(area2 / 2);
}

function midpoint(a, b) {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

function formatDistance(m) {
  if (m < 10) return `${m.toFixed(1)} m`;
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(2)} km`;
}

function formatArea(m2) {
  if (m2 < 10_000) return `${Math.round(m2)} m²`;
  return `${(m2 / 10_000).toFixed(2)} ha`;
}

export default function DesignMeasureTool({
  mapRef,
  active = false,
  mode = "distance",              // "distance" | "area"
  onDeactivate = () => {},
  onModeChange = () => {},
}) {
  const [points, setPoints] = useState([]); // [[lng, lat], ...]
  const [finished, setFinished] = useState(false);
  const pointsRef = useRef(points);
  pointsRef.current = points;

  /* ── Lazily add the measure source + layers once map is ready. ──────── */
  useEffect(() => {
    const map = mapRef?.current;
    if (!map) return;
    const setup = () => {
      if (!map || map._removed) return;
      if (map.getSource(SRC_ID)) return;
      map.addSource(SRC_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: FILL_LAYER,
        type: "fill",
        source: SRC_ID,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#F5B731", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: LINE_LAYER,
        type: "line",
        source: SRC_ID,
        filter: ["in", ["geometry-type"], ["literal", ["LineString", "Polygon"]]],
        paint: {
          "line-color": "#F5B731",
          "line-width": 2.4,
          "line-dasharray": [1.8, 1.2],
        },
      });
      map.addLayer({
        id: POINTS_LAYER,
        type: "circle",
        source: SRC_ID,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 4.5,
          "circle-color": "#F5B731",
          "circle-stroke-color": "#1c1912",
          "circle-stroke-width": 1.4,
        },
      });
      map.addLayer({
        id: LABELS_LAYER,
        type: "symbol",
        source: SRC_ID,
        filter: ["has", "label"],
        layout: {
          "text-field": ["get", "label"],
          "text-size": 12,
          "text-offset": [0, -1.1],
          "text-anchor": "bottom",
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "#1c1912",
          "text-halo-width": 1.5,
        },
      });
    };
    if (map.isStyleLoaded()) setup();
    else map.once("load", setup);
  }, [mapRef]);

  /* ── Write current vertex list to the Mapbox source. ────────────────── */
  useEffect(() => {
    const map = mapRef?.current;
    if (!map) return;
    const src = map.getSource?.(SRC_ID);
    if (!src) return;

    const features = [];
    // Vertex points
    points.forEach((p, i) => {
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: p },
        properties: { idx: i },
      });
    });

    if (points.length >= 2) {
      if (mode === "distance") {
        features.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: points },
          properties: {},
        });
        // Per-segment midpoint labels
        let total = 0;
        for (let i = 0; i < points.length - 1; i++) {
          const seg = haversine(points[i], points[i + 1]);
          total += seg;
          const mid = midpoint(points[i], points[i + 1]);
          features.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: mid },
            properties: { label: formatDistance(seg) },
          });
        }
        if (finished || points.length >= 2) {
          const last = points[points.length - 1];
          features.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: last },
            properties: { label: `Σ ${formatDistance(total)}` },
          });
        }
      } else {
        // Area mode — close ring only once finished
        const ring = finished ? [...points, points[0]] : points;
        if (finished && ring.length >= 4) {
          features.push({
            type: "Feature",
            geometry: { type: "Polygon", coordinates: [ring] },
            properties: {},
          });
        } else {
          features.push({
            type: "Feature",
            geometry: { type: "LineString", coordinates: ring },
            properties: {},
          });
        }
        if (points.length >= 3) {
          const area = polygonAreaM2(points);
          const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
          const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
          features.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: [cx, cy] },
            properties: { label: formatArea(area) },
          });
        }
      }
    }

    try { src.setData({ type: "FeatureCollection", features }); } catch { /* ignore */ }
  }, [points, finished, mode, mapRef]);

  /* ── Mouse + key wiring while active. ───────────────────────────────── */
  const commit = useCallback(() => {
    setFinished(true);
  }, []);

  const cancel = useCallback(() => {
    setPoints([]);
    setFinished(false);
    onDeactivate();
  }, [onDeactivate]);

  useEffect(() => {
    const map = mapRef?.current;
    if (!map || !active) return;

    // Reset on (re)activation.
    setPoints([]);
    setFinished(false);

    const prevCursor = map.getCanvas().style.cursor;
    map.getCanvas().style.cursor = "crosshair";

    const handleClick = (e) => {
      if (finished) return;
      const p = [e.lngLat.lng, e.lngLat.lat];
      setPoints((prev) => [...prev, p]);
    };
    const handleDblClick = (e) => {
      e.preventDefault?.();
      if (pointsRef.current.length >= (mode === "area" ? 3 : 2)) commit();
    };
    const handleKey = (e) => {
      if (e.key === "Escape") { cancel(); }
      else if (e.key === "Enter") {
        if (pointsRef.current.length >= (mode === "area" ? 3 : 2)) commit();
      }
    };

    map.on("click", handleClick);
    map.on("dblclick", handleDblClick);
    // Mapbox default double-click zoom — disable while active
    try { map.doubleClickZoom.disable(); } catch { /* ignore */ }
    window.addEventListener("keydown", handleKey);

    return () => {
      map.off("click", handleClick);
      map.off("dblclick", handleDblClick);
      window.removeEventListener("keydown", handleKey);
      try { map.doubleClickZoom.enable(); } catch { /* ignore */ }
      map.getCanvas().style.cursor = prevCursor;
    };
  }, [active, mode, commit, cancel, mapRef, finished]);

  /* ── Clear overlay when deactivated. ────────────────────────────────── */
  useEffect(() => {
    if (active) return;
    setPoints([]);
    setFinished(false);
    const map = mapRef?.current;
    const src = map?.getSource?.(SRC_ID);
    if (src) { try { src.setData({ type: "FeatureCollection", features: [] }); } catch { /* ignore */ } }
  }, [active, mapRef]);

  if (!active) return null;

  const total = points.length >= 2
    ? points.slice(1).reduce((s, p, i) => s + haversine(points[i], p), 0)
    : 0;
  const area = mode === "area" && points.length >= 3 ? polygonAreaM2(points) : 0;

  return (
    <div className="dc-measure-hud" role="status">
      <div className="dc-measure-modes">
        <button
          className={"dc-measure-mode" + (mode === "distance" ? " dc-measure-mode-active" : "")}
          onClick={() => onModeChange("distance")}
        >Distance</button>
        <button
          className={"dc-measure-mode" + (mode === "area" ? " dc-measure-mode-active" : "")}
          onClick={() => onModeChange("area")}
        >Area</button>
      </div>
      <div className="dc-measure-readout">
        {mode === "distance"
          ? <span>Σ {formatDistance(total)}{points.length < 2 ? " — click to start" : ""}</span>
          : <span>{formatArea(area)}{points.length < 3 ? " — need ≥ 3 vertices" : ""}</span>}
      </div>
      <div className="dc-measure-hint">
        Click to add · double-click or Enter to finish · Esc to cancel
      </div>
      <div className="dc-measure-actions">
        <button className="dc-measure-btn" onClick={commit} disabled={points.length < 2}>Finish</button>
        <button className="dc-measure-btn dc-measure-btn-ghost" onClick={cancel}>Close</button>
      </div>
    </div>
  );
}
