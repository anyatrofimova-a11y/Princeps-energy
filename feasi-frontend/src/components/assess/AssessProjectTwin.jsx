import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer, ScatterplotLayer, PathLayer, LineLayer } from "@deck.gl/layers";
import AssessTwinToolbar from "./AssessTwinToolbar";
import AssessTwinLegend from "./AssessTwinLegend";
import useProjectTwinLayers from "../../hooks/useProjectTwinLayers";
import { fetchProjectTwinContext, isMockMode } from "../../api/projectTwin";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

const GOLD_RGB = [245, 183, 49];
const GOLD_HEX = "#F5B731";
const IVORY = "#FBF8F2";

const VOLTAGE_COLOR = (kv) => {
  if (kv >= 400) return [128, 90, 180];
  if (kv >= 275) return [190, 60, 120];
  if (kv >= 132) return [70, 130, 220];
  if (kv >= 66)  return [40, 170, 200];
  if (kv >= 33)  return [60, 180, 140];
  return [150, 150, 150];
};

function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLon = ((b[0] - a[0]) * Math.PI) / 180;
  const la1 = (a[1] * Math.PI) / 180;
  const la2 = (b[1] * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function polygonBbox(feature) {
  if (!feature?.geometry?.coordinates) return null;
  const rings = feature.geometry.type === "Polygon"
    ? feature.geometry.coordinates
    : (feature.geometry.type === "MultiPolygon" ? feature.geometry.coordinates.flat() : null);
  if (!rings) return null;
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  for (const ring of rings) {
    for (const [lon, lat] of ring) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
  }
  if (!Number.isFinite(west)) return null;
  return [west, south, east, north];
}

function polygonCentroid(feature) {
  const bb = polygonBbox(feature);
  if (!bb) return null;
  return [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2];
}

function expandBbox(bbox, padRatio = 0.25) {
  if (!bbox) return null;
  const [w, s, e, n] = bbox;
  const dx = (e - w) * padRatio;
  const dy = (n - s) * padRatio;
  return [w - dx, s - dy, e + dx, n + dy];
}

// Buildable mask: shrink polygon inward (~30% inset) as a coarse visual stand-in.
function buildableMask(feature) {
  if (!feature?.geometry?.coordinates?.length) return null;
  const ring = feature.geometry.coordinates[0];
  if (!ring || ring.length < 4) return null;
  let cx = 0, cy = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    cx += ring[i][0];
    cy += ring[i][1];
  }
  cx /= (ring.length - 1);
  cy /= (ring.length - 1);
  const inset = 0.7;
  const shrunk = ring.map(([lon, lat]) => [cx + (lon - cx) * inset, cy + (lat - cy) * inset]);
  return {
    type: "Feature",
    properties: { _buildable: true },
    geometry: { type: "Polygon", coordinates: [shrunk] },
  };
}

function cameraPresetToView(preset, bbox) {
  const c = bbox ? [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2] : [0, 52];
  switch (preset) {
    case "plan":    return { center: c, pitch: 0,  bearing: 0,  zoom: 14.0 };
    case "side":    return { center: c, pitch: 75, bearing: 0,  zoom: 14.5 };
    case "orbit":   return { center: c, pitch: 55, bearing: 0,  zoom: 14.5, orbit: true };
    case "oblique":
    default:        return { center: c, pitch: 45, bearing: -25, zoom: 14.3 };
  }
}

/**
 * AssessProjectTwin — focused 3D project twin embedded inline in the Assess tab.
 *
 * Props:
 *   projectId:    string (required)
 *   polygon_wkt:  string (optional override — WKT polygon; else uses twin-context)
 *   tech:         "solar" | "wind" | "bess" | "dc"
 *   capacity_mw:  number
 *   onOpenFull:   () => void (optional — defaults to routing to /grid-twin?project=<id>)
 *
 * Renders a 600px-tall Mapbox + deck.gl embed with:
 *   satellite-streets base · terrain · DynamicWorld · buildable mask ·
 *   project polygon · POC substation + line · 5km grid lines.
 */
export default function AssessProjectTwin({
  projectId,
  polygon_wkt = null,
  tech = null,
  capacity_mw = null,
  onOpenFull = null,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const orbitRafRef = useRef(null);

  const [ctx, setCtx] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mapReady, setMapReady] = useState(false);
  const [error, setError] = useState(null);

  const {
    layers, toggleLayer, setAllLayers,
    cameraPreset, setCameraPreset,
  } = useProjectTwinLayers(projectId);

  const hasToken = !!mapboxgl.accessToken;

  /* ── Fetch twin context ─────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchProjectTwinContext(projectId, { polygon_wkt, tech, capacity_mw })
      .then((data) => {
        if (cancelled) return;
        if (!data) setError("No twin context available for this project.");
        setCtx(data);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId, polygon_wkt, tech, capacity_mw]);

  const bbox = useMemo(() => polygonBbox(ctx?.polygon), [ctx]);
  const paddedBbox = useMemo(() => expandBbox(bbox, 0.35), [bbox]);
  const centroid = useMemo(() => polygonCentroid(ctx?.polygon), [ctx]);
  const buildable = useMemo(() => buildableMask(ctx?.polygon), [ctx]);

  const scaleKm = useMemo(() => {
    if (!paddedBbox) return null;
    const [w, s, e] = paddedBbox;
    return haversineKm([w, s], [e, s]);
  }, [paddedBbox]);

  /* ── Init Mapbox ─────────────────────────────────────────────────────── */
  useEffect(() => {
    if (!hasToken || !containerRef.current || mapRef.current) return undefined;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [0, 52],
      zoom: 12,
      pitch: 45,
      bearing: -25,
      attributionControl: false,
      preserveDrawingBuffer: true, // required for canvas.toBlob() export
    });

    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-right");

    const overlay = new MapboxOverlay({ layers: [] });
    map.addControl(overlay);

    map.on("load", () => {
      try {
        // NASADEM terrain (terrain-rgb)
        if (!map.getSource("mapbox-dem")) {
          map.addSource("mapbox-dem", {
            type: "raster-dem",
            url: "mapbox://mapbox.mapbox-terrain-dem-v1",
            tileSize: 512,
            maxzoom: 14,
          });
        }
      } catch { /* noop */ }
      setMapReady(true);
    });

    mapRef.current = map;
    overlayRef.current = overlay;

    return () => {
      if (orbitRafRef.current) cancelAnimationFrame(orbitRafRef.current);
      try { map.remove(); } catch { /* noop */ }
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, [hasToken]);

  /* ── Terrain toggle ──────────────────────────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    try {
      if (layers.terrain) {
        map.setTerrain({ source: "mapbox-dem", exaggeration: 1.5 });
      } else {
        map.setTerrain(null);
      }
    } catch { /* noop — style may not be fully loaded */ }
  }, [layers.terrain, mapReady]);

  /* ── Auto-frame to project bbox on first load ────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !paddedBbox) return;
    const [w, s, e, n] = paddedBbox;
    try {
      map.fitBounds([[w, s], [e, n]], {
        padding: 60,
        pitch: 45,
        bearing: -25,
        duration: 900,
        maxZoom: 15.5,
      });
    } catch { /* noop */ }
  }, [paddedBbox, mapReady]);

  /* ── Camera presets ──────────────────────────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !bbox) return undefined;
    const view = cameraPresetToView(cameraPreset, bbox);

    // Cancel any in-flight orbit.
    if (orbitRafRef.current) {
      cancelAnimationFrame(orbitRafRef.current);
      orbitRafRef.current = null;
    }

    map.easeTo({
      center: view.center,
      pitch: view.pitch,
      bearing: view.bearing,
      zoom: view.zoom,
      duration: 650,
    });

    if (view.orbit) {
      let bearing = view.bearing;
      const tick = () => {
        bearing = (bearing + 0.12) % 360;
        map.setBearing(bearing);
        orbitRafRef.current = requestAnimationFrame(tick);
      };
      orbitRafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (orbitRafRef.current) {
        cancelAnimationFrame(orbitRafRef.current);
        orbitRafRef.current = null;
      }
    };
  }, [cameraPreset, bbox, mapReady]);

  /* ── deck.gl layer stack ─────────────────────────────────────────────── */
  const deckLayers = useMemo(() => {
    if (!ctx) return [];
    const out = [];

    // DynamicWorld land-use overlay — synthetic gradient cover (10% alpha)
    // rendered as a pale green wash across the padded bbox so the toggle is
    // always visible even without the GEE pipeline wired.
    if (layers.landuse && paddedBbox) {
      const [w, s, e, n] = paddedBbox;
      out.push(new GeoJsonLayer({
        id: "assess-landuse-bg",
        data: {
          type: "Feature",
          geometry: {
            type: "Polygon",
            coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
          },
          properties: {},
        },
        stroked: false,
        filled: true,
        getFillColor: [140, 180, 100, 26], // ~10% alpha
        pickable: false,
      }));
    }

    // Buildable mask (30% gold inset)
    if (layers.buildable && buildable) {
      out.push(new GeoJsonLayer({
        id: "assess-buildable",
        data: buildable,
        stroked: true,
        filled: true,
        getFillColor: [...GOLD_RGB, 77],
        getLineColor: [...GOLD_RGB, 180],
        lineWidthMinPixels: 1,
        getDashArray: [4, 3],
        pickable: false,
      }));
    }

    // Project polygon outline (gold, 2px stroke)
    if (layers.polygon && ctx.polygon) {
      out.push(new GeoJsonLayer({
        id: "assess-polygon",
        data: ctx.polygon,
        stroked: true,
        filled: false,
        getLineColor: [...GOLD_RGB, 230],
        lineWidthMinPixels: 2,
        pickable: true,
      }));
    }

    // Grid lines within 5km of centroid (thin blue / voltage-coloured)
    if (layers.grid_lines && Array.isArray(ctx.nearest_grid_lines) && centroid) {
      const paths = [];
      for (const ln of ctx.nearest_grid_lines) {
        const coords = ln?.geometry?.coordinates;
        if (!Array.isArray(coords) || coords.length < 2) continue;
        const near = coords.some((c) => haversineKm(c, centroid) <= 5);
        if (!near) continue;
        paths.push({
          path: coords,
          color: [...VOLTAGE_COLOR(ln.voltage_kv || 0), 200],
          kv: ln.voltage_kv,
        });
      }
      if (paths.length) {
        out.push(new PathLayer({
          id: "assess-grid-lines",
          data: paths,
          getPath: (d) => d.path,
          getColor: (d) => d.color,
          getWidth: 2,
          widthMinPixels: 1.5,
          widthMaxPixels: 4,
          pickable: true,
          capRounded: true,
          jointRounded: true,
        }));
      }
    }

    // POC line from centroid → substation
    if (layers.substation && ctx.poc_substation && centroid) {
      const sub = ctx.poc_substation;
      const subPt = [sub.lon, sub.lat];
      out.push(new LineLayer({
        id: "assess-poc-line",
        data: [{ from: centroid, to: subPt }],
        getSourcePosition: (d) => d.from,
        getTargetPosition: (d) => d.to,
        getColor: [...GOLD_RGB, 220],
        getWidth: 3,
        widthMinPixels: 2,
      }));
      out.push(new ScatterplotLayer({
        id: "assess-poc-pin",
        data: [sub],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: 120,
        radiusMinPixels: 7,
        radiusMaxPixels: 14,
        getFillColor: [43, 127, 255, 230],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
      }));
    }

    return out;
  }, [ctx, layers, paddedBbox, centroid, buildable]);

  useEffect(() => {
    if (!overlayRef.current) return;
    overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  /* ── Export PNG ──────────────────────────────────────────────────────── */
  const handleExportPNG = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    try {
      const canvas = map.getCanvas();
      canvas.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `princeps-project-twin-${projectId || "export"}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1200);
      }, "image/png");
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("[AssessProjectTwin] export failed", e);
    }
  }, [projectId]);

  /* ── Open full twin ──────────────────────────────────────────────────── */
  const handleOpenFull = useCallback(() => {
    if (typeof onOpenFull === "function") {
      onOpenFull();
      return;
    }
    if (typeof window !== "undefined") {
      window.location.href = `/grid-twin?project=${encodeURIComponent(projectId || "")}`;
    }
  }, [onOpenFull, projectId]);

  /* ── Render ──────────────────────────────────────────────────────────── */
  const empty = !hasToken || (!loading && !ctx);

  return (
    <div className="apt-root">
      <div ref={containerRef} className="apt-map" />

      {mapReady && !empty && (
        <>
          <AssessTwinToolbar
            layers={layers}
            onToggleLayer={toggleLayer}
            onSetAllLayers={setAllLayers}
            cameraPreset={cameraPreset}
            onCameraPreset={setCameraPreset}
            onExportPNG={handleExportPNG}
            onOpenFullTwin={handleOpenFull}
          />
          <AssessTwinLegend
            layers={layers}
            scaleKm={scaleKm}
            tech={ctx?.tech || tech}
          />
        </>
      )}

      {empty && (
        <div className="apt-empty">
          <div className="apt-empty-title">
            {!hasToken ? "Mapbox token missing" : "No twin context"}
          </div>
          <div className="apt-empty-sub">
            {!hasToken
              ? "Set VITE_MAPBOX_TOKEN to render the project twin."
              : (error || "Select a project to load its twin context.")}
          </div>
          {isMockMode && hasToken && (
            <div className="apt-empty-mock">mock mode active — fixture missing for this id</div>
          )}
        </div>
      )}

      {loading && <LoadingSkeleton />}

      <style>{`
        .apt-root {
          position: relative;
          width: 100%;
          height: 600px;
          border-radius: 12px;
          overflow: hidden;
          background: #0F1318;
          border: 1px solid rgba(245, 183, 49, 0.25);
          box-shadow: 0 4px 14px rgba(20, 18, 10, 0.12);
          font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
        }
        .apt-map {
          position: absolute;
          inset: 0;
        }
        .apt-empty {
          position: absolute;
          inset: 0;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          text-align: center;
          background: linear-gradient(135deg, #1A1D23 0%, #0F1318 100%);
          color: rgba(251, 248, 242, 0.85);
          padding: 24px;
          z-index: 5;
        }
        .apt-empty-title {
          font-size: 15px; font-weight: 600;
          color: ${IVORY};
          margin-bottom: 6px;
        }
        .apt-empty-sub {
          font-size: 12px;
          color: rgba(251, 248, 242, 0.55);
          max-width: 420px;
          line-height: 1.5;
        }
        .apt-empty-mock {
          margin-top: 12px;
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 10.5px;
          color: ${GOLD_HEX};
          background: rgba(245, 183, 49, 0.12);
          padding: 3px 8px; border-radius: 4px;
        }
      `}</style>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="apt-skel">
      <div className="apt-skel-bar">
        <span className="apt-skel-dot" />
        <span>Loading project twin…</span>
      </div>
      <style>{`
        .apt-skel {
          position: absolute;
          left: 0; right: 0; bottom: 0;
          z-index: 8;
          display: flex; justify-content: center;
          padding: 10px;
          pointer-events: none;
        }
        .apt-skel-bar {
          display: inline-flex; align-items: center; gap: 10px;
          background: rgba(251, 248, 242, 0.92);
          border: 1px solid rgba(245, 183, 49, 0.5);
          border-radius: 6px;
          padding: 6px 12px;
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 11px;
          color: #2A2317;
          box-shadow: 0 2px 6px rgba(20, 18, 10, 0.12);
        }
        .apt-skel-dot {
          width: 8px; height: 8px; border-radius: 50%;
          background: #F5B731;
          animation: apt-pulse 1.2s ease-in-out infinite;
        }
        @keyframes apt-pulse {
          0%, 100% { opacity: 0.4; transform: scale(0.85); }
          50% { opacity: 1; transform: scale(1.15); }
        }
      `}</style>
    </div>
  );
}
