import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ColumnLayer, PolygonLayer, TextLayer, ScatterplotLayer, LineLayer } from "@deck.gl/layers";
import { TerrainLayer } from "@deck.gl/geo-layers";

const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";
mapboxgl.accessToken = TOKEN;

/* ── Asset type colours ─────────────────────────────────────────────── */
const ASSET_COLORS = {
  solar:   [30, 136, 229, 220],
  pv:      [30, 136, 229, 220],
  wind:    [76, 175, 80, 220],
  battery: [255, 152, 0, 220],
  bess:    [255, 152, 0, 220],
  inverter:[255, 193, 7, 220],
  transformer: [158, 158, 158, 220],
  substation:  [244, 67, 54, 220],
  default: [171, 71, 188, 220],
};

function assetColor(type) {
  if (!type) return ASSET_COLORS.default;
  const key = type.toLowerCase().replace(/[^a-z]/g, "");
  for (const [k, v] of Object.entries(ASSET_COLORS)) {
    if (key.includes(k)) return v;
  }
  return ASSET_COLORS.default;
}

function assetLabel(a) {
  const parts = [];
  if (a.name) parts.push(a.name);
  else if (a.type) parts.push(a.type);
  if (a.capacity_mw != null) parts.push(`${a.capacity_mw} MW`);
  return parts.join("\n") || "Asset";
}

/* ── Haversine distance (metres) ────────────────────────────────────── */
function haversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/* ── Midpoint between two lnglat ────────────────────────────────────── */
function midpoint(a, b) {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

/* ═══════════════════════════════════════════════════════════════════════
   TerrainTwin — Satellite-textured 3D terrain via deck.gl TerrainLayer
   over Mapbox GL with asset overlays and measurement tools
   ═══════════════════════════════════════════════════════════════════════ */
export default function TerrainTwin({
  lat = 52.0,
  lon = -1.5,
  zoom: initialZoom = 14,
  placedAssets = [],
  boundaries = [],
  onClose,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);

  /* ── State ── */
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [mapReady, setMapReady] = useState(false);
  const [exaggeration, setExaggeration] = useState(1.5);
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState([]);
  const [measureResult, setMeasureResult] = useState(null);
  const [inspected, setInspected] = useState(null);
  const [activeLayers, setActiveLayers] = useState({
    terrain: true,
    assets: true,
    boundaries: true,
    labels: true,
  });

  /* ── Terrain bounds (viewport-based) ── */
  const terrainBounds = useMemo(() => {
    // ~2km extent around the site at zoom 14
    const span = 0.025;
    return [lon - span, lat - span, lon + span, lat + span];
  }, [lat, lon]);

  /* ── Build deck.gl layers ── */
  const deckLayers = useMemo(() => {
    const layers = [];

    // ── Satellite-textured 3D terrain ──
    if (activeLayers.terrain) {
      layers.push(new TerrainLayer({
        id: "tt-terrain",
        minZoom: 0,
        maxZoom: 15,
        elevationDecoder: {
          rScaler: 6553.6,
          gScaler: 25.6,
          bScaler: 0.1,
          offset: -10000,
        },
        elevationData: `https://api.mapbox.com/v4/mapbox.terrain-rgb/{z}/{x}/{y}.pngraw?access_token=${TOKEN}`,
        texture: `https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.png?access_token=${TOKEN}`,
        meshMaxError: 4.0,
        operation: "terrain+draw",
      }));
    }

    // ── Site boundary polygons ──
    if (activeLayers.boundaries && boundaries.length > 0) {
      const boundaryData = boundaries.map((b, i) => {
        // Accept GeoJSON Feature or raw coordinate rings
        const coords = b.geometry?.coordinates?.[0] || b.coordinates?.[0] || b.ring || b;
        if (!Array.isArray(coords) || coords.length < 3) return null;
        return {
          id: `boundary-${i}`,
          polygon: coords,
          name: b.properties?.name || b.name || `Boundary ${i + 1}`,
        };
      }).filter(Boolean);

      if (boundaryData.length > 0) {
        layers.push(new PolygonLayer({
          id: "tt-boundaries",
          data: boundaryData,
          getPolygon: d => d.polygon,
          getFillColor: [76, 175, 80, 40],
          getLineColor: [76, 175, 80, 200],
          getLineWidth: 3,
          lineWidthUnits: "pixels",
          filled: true,
          stroked: true,
          extruded: false,
          pickable: true,
          onClick: ({ object }) => object && setInspected({
            type: "boundary",
            name: object.name,
          }),
        }));
      }
    }

    // ── Placed assets as columns ──
    if (activeLayers.assets && placedAssets.length > 0) {
      layers.push(new ColumnLayer({
        id: "tt-asset-columns",
        data: placedAssets,
        getPosition: d => [d.lon ?? d.lng ?? d.longitude ?? lon, d.lat ?? d.latitude ?? lat],
        getElevation: d => Math.max((d.capacity_mw || d.mw || 1) * 3, 5),
        getFillColor: d => assetColor(d.type || d.asset_type),
        radius: 15,
        elevationScale: 1,
        extruded: true,
        pickable: true,
        opacity: 0.9,
        material: {
          ambient: 0.4,
          diffuse: 0.6,
          shininess: 32,
          specularColor: [200, 200, 200],
        },
        onClick: ({ object }) => object && setInspected({
          type: "asset",
          name: object.name || object.type || "Asset",
          capacity_mw: object.capacity_mw || object.mw,
          asset_type: object.type || object.asset_type,
          details: object,
        }),
      }));

      // Asset base markers (so they are visible even at low zoom)
      layers.push(new ScatterplotLayer({
        id: "tt-asset-markers",
        data: placedAssets,
        getPosition: d => [d.lon ?? d.lng ?? d.longitude ?? lon, d.lat ?? d.latitude ?? lat],
        getRadius: d => Math.max((d.capacity_mw || d.mw || 1) * 2, 8),
        getFillColor: d => assetColor(d.type || d.asset_type),
        getLineColor: [255, 255, 255, 180],
        lineWidthMinPixels: 1,
        stroked: true,
        filled: true,
        radiusUnits: "meters",
        pickable: false,
      }));
    }

    // ── Asset labels ──
    if (activeLayers.labels && placedAssets.length > 0) {
      layers.push(new TextLayer({
        id: "tt-asset-labels",
        data: placedAssets,
        getPosition: d => [d.lon ?? d.lng ?? d.longitude ?? lon, d.lat ?? d.latitude ?? lat],
        getText: d => assetLabel(d),
        getSize: 12,
        getColor: [255, 255, 255, 220],
        getTextAnchor: "middle",
        getAlignmentBaseline: "bottom",
        getPixelOffset: [0, -25],
        fontFamily: "'IBM Plex Mono', monospace",
        fontWeight: 600,
        outlineColor: [0, 0, 0, 220],
        outlineWidth: 2,
        billboard: true,
      }));
    }

    // ── Measurement line ──
    if (measurePoints.length === 2) {
      layers.push(new LineLayer({
        id: "tt-measure-line",
        data: [{ from: measurePoints[0], to: measurePoints[1] }],
        getSourcePosition: d => d.from,
        getTargetPosition: d => d.to,
        getColor: [0, 229, 255, 255],
        getWidth: 3,
        widthUnits: "pixels",
      }));

      // Endpoints
      layers.push(new ScatterplotLayer({
        id: "tt-measure-dots",
        data: measurePoints.map(p => ({ position: p })),
        getPosition: d => d.position,
        getRadius: 6,
        getFillColor: [0, 229, 255, 255],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        radiusUnits: "pixels",
      }));

      // Distance label at midpoint
      const mid = midpoint(measurePoints[0], measurePoints[1]);
      const dist = haversineM(
        measurePoints[0][1], measurePoints[0][0],
        measurePoints[1][1], measurePoints[1][0],
      );
      layers.push(new TextLayer({
        id: "tt-measure-label",
        data: [{ position: mid, text: dist >= 1000 ? `${(dist / 1000).toFixed(2)} km` : `${dist.toFixed(1)} m` }],
        getPosition: d => d.position,
        getText: d => d.text,
        getSize: 14,
        getColor: [0, 229, 255, 255],
        fontFamily: "'IBM Plex Mono', monospace",
        fontWeight: 700,
        outlineColor: [0, 0, 0, 240],
        outlineWidth: 3,
        billboard: true,
        getPixelOffset: [0, -16],
      }));
    }

    // Single measure point indicator
    if (measurePoints.length === 1) {
      layers.push(new ScatterplotLayer({
        id: "tt-measure-start",
        data: [{ position: measurePoints[0] }],
        getPosition: d => d.position,
        getRadius: 8,
        getFillColor: [0, 229, 255, 200],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        radiusUnits: "pixels",
      }));
    }

    return layers;
  }, [activeLayers, placedAssets, boundaries, lat, lon, measurePoints, terrainBounds, exaggeration]);

  /* ── Init Mapbox + deck.gl overlay ── */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    if (!TOKEN) {
      setError("Mapbox token not found. Set VITE_MAPBOX_TOKEN in your environment.");
      setLoading(false);
      return;
    }

    let map;
    try {
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: "mapbox://styles/mapbox/satellite-streets-v12",
        center: [lon, lat],
        zoom: initialZoom,
        pitch: 60,
        bearing: -20,
        antialias: true,
        maxPitch: 85,
      });
    } catch (e) {
      setError(`Failed to initialise Mapbox: ${e.message}`);
      setLoading(false);
      return;
    }

    map.on("load", () => {
      // Native Mapbox terrain for base terrain shading
      map.addSource("mapbox-dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
      map.setTerrain({ source: "mapbox-dem", exaggeration: 1.5 });

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

      // 3D buildings where available
      const labelLayer = map.getStyle().layers.find(l => l.type === "symbol" && l.layout?.["text-field"]);
      map.addLayer({
        id: "3d-buildings",
        source: "composite",
        "source-layer": "building",
        filter: ["==", "extrude", "true"],
        type: "fill-extrusion",
        minzoom: 12,
        paint: {
          "fill-extrusion-color": "#2a2a3e",
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": ["get", "min_height"],
          "fill-extrusion-opacity": 0.7,
        },
      }, labelLayer?.id);

      // deck.gl overlay
      const overlay = new MapboxOverlay({ layers: [] });
      map.addControl(overlay);
      overlayRef.current = overlay;

      // Navigation control
      map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");

      setMapReady(true);
      setLoading(false);
    });

    map.on("error", (e) => {
      console.warn("Mapbox error:", e.error?.message || e);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  /* ── Sync deck.gl layers ── */
  useEffect(() => {
    if (overlayRef.current) {
      overlayRef.current.setProps({ layers: deckLayers });
    }
  }, [deckLayers]);

  /* ── Terrain exaggeration ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    try {
      map.setTerrain({ source: "mapbox-dem", exaggeration });
    } catch {}
  }, [exaggeration, mapReady]);

  /* ── Measurement click handler ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const handler = (e) => {
      if (!measureMode) return;

      const lngLat = [e.lngLat.lng, e.lngLat.lat];

      setMeasurePoints(prev => {
        if (prev.length === 0) {
          setMeasureResult(null);
          return [lngLat];
        } else if (prev.length === 1) {
          const dist = haversineM(prev[0][1], prev[0][0], lngLat[1], lngLat[0]);
          setMeasureResult(dist >= 1000
            ? `${(dist / 1000).toFixed(2)} km`
            : `${dist.toFixed(1)} m`);
          return [prev[0], lngLat];
        } else {
          // Reset and start new measurement
          setMeasureResult(null);
          return [lngLat];
        }
      });
    };

    map.on("click", handler);
    return () => map.off("click", handler);
  }, [measureMode]);

  /* ── Keyboard shortcuts ── */
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") {
        if (measureMode) {
          setMeasureMode(false);
          setMeasurePoints([]);
          setMeasureResult(null);
        } else if (onClose) {
          onClose();
        }
      }
      if (e.key === "m" || e.key === "M") {
        setMeasureMode(prev => !prev);
        setMeasurePoints([]);
        setMeasureResult(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [measureMode, onClose]);

  /* ── Fly to site on props change ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    map.flyTo({
      center: [lon, lat],
      zoom: initialZoom,
      pitch: 60,
      bearing: -20,
      duration: 1500,
    });
  }, [lat, lon, mapReady]);

  /* ── Render ────────────────────────────────────────────────────────── */
  return (
    <div className="digital-twin-overlay">
      {/* ── Toolbar ── */}
      <div className="twin-toolbar" style={{ background: "rgba(10, 12, 18, 0.95)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="twin-close-btn" onClick={onClose} title="Close (Esc)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
          <span style={{ fontWeight: 700, fontSize: 13, color: "#D4A018", letterSpacing: 1 }}>
            TERRAIN TWIN
          </span>
          <span style={{ fontSize: 11, color: "#9CA3AF" }}>
            {lat.toFixed(4)}N, {Math.abs(lon).toFixed(4)}{lon < 0 ? "W" : "E"}
          </span>
          {placedAssets.length > 0 && (
            <span style={{ fontSize: 10, color: "#6B7280", marginLeft: 4 }}>
              {placedAssets.length} asset{placedAssets.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* Terrain exaggeration slider */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 10, color: "#6B7280", fontWeight: 600 }}>TERRAIN</span>
            <input
              type="range" min="1" max="3" step="0.1" value={exaggeration}
              onChange={(e) => setExaggeration(parseFloat(e.target.value))}
              style={{ width: 80, accentColor: "#D4A018" }}
            />
            <span style={{ fontSize: 11, color: "#9CA3AF", minWidth: 28, fontFamily: "'IBM Plex Mono', monospace" }}>
              {exaggeration.toFixed(1)}x
            </span>
          </div>

          {/* Layer toggles */}
          <div style={{ display: "flex", gap: 3 }}>
            {Object.entries(activeLayers).map(([key, on]) => (
              <button
                key={key}
                onClick={() => setActiveLayers(prev => ({ ...prev, [key]: !prev[key] }))}
                title={key.charAt(0).toUpperCase() + key.slice(1)}
                style={{
                  padding: "3px 8px",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  border: `1px solid ${on ? "rgba(212,160,24,0.4)" : "rgba(255,255,255,0.1)"}`,
                  borderRadius: 3,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  background: on ? "rgba(212,160,24,0.15)" : "transparent",
                  color: on ? "#D4A018" : "#6B7280",
                  transition: "all 0.15s",
                }}
              >
                {key.slice(0, 4)}
              </button>
            ))}
          </div>

          {/* Measure tool */}
          <button
            onClick={() => {
              setMeasureMode(!measureMode);
              setMeasurePoints([]);
              setMeasureResult(null);
            }}
            title="Measure distance (M)"
            style={{
              padding: "4px 10px",
              fontSize: 10,
              fontWeight: 700,
              border: `1px solid ${measureMode ? "#00e5ff" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 3,
              cursor: "pointer",
              fontFamily: "inherit",
              background: measureMode ? "rgba(0,229,255,0.15)" : "transparent",
              color: measureMode ? "#00e5ff" : "#6B7280",
              display: "flex",
              alignItems: "center",
              gap: 4,
              transition: "all 0.15s",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M2 12h4m4 0h4m4 0h4" />
              <path d="M6 8v8M14 8v8" />
            </svg>
            MEASURE
          </button>

          {/* Screenshot */}
          <button
            onClick={() => {
              const map = mapRef.current;
              if (!map) return;
              const canvas = map.getCanvas();
              const url = canvas.toDataURL("image/png");
              const a = document.createElement("a");
              a.href = url;
              a.download = `terrain-twin-${lat.toFixed(4)}-${lon.toFixed(4)}.png`;
              a.click();
            }}
            title="Screenshot"
            style={{
              padding: "4px 8px",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 3,
              cursor: "pointer",
              background: "transparent",
              color: "#6B7280",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Map container ── */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          cursor: measureMode ? "crosshair" : "grab",
        }}
      />

      {/* ── Loading overlay ── */}
      {loading && (
        <div style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "rgba(10, 12, 18, 0.9)",
          zIndex: 20,
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{
              width: 40, height: 40, border: "3px solid rgba(212,160,24,0.3)",
              borderTopColor: "#D4A018", borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 16px",
            }} />
            <div style={{ color: "#D4A018", fontSize: 13, fontWeight: 600, letterSpacing: 1 }}>
              LOADING TERRAIN
            </div>
            <div style={{ color: "#6B7280", fontSize: 11, marginTop: 4 }}>
              Fetching satellite imagery and elevation data...
            </div>
          </div>
        </div>
      )}

      {/* ── Error overlay ── */}
      {error && (
        <div style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "rgba(10, 12, 18, 0.95)",
          zIndex: 20,
        }}>
          <div style={{ textAlign: "center", maxWidth: 400 }}>
            <div style={{ color: "#f5222d", fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              Terrain Load Error
            </div>
            <div style={{ color: "#9CA3AF", fontSize: 12, lineHeight: 1.5 }}>
              {error}
            </div>
            <button
              onClick={onClose}
              style={{
                marginTop: 16, padding: "8px 20px", background: "rgba(245,34,45,0.15)",
                border: "1px solid rgba(245,34,45,0.3)", borderRadius: 4,
                color: "#f5222d", cursor: "pointer", fontSize: 12, fontWeight: 600,
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* ── Measurement HUD ── */}
      {measureMode && (
        <div style={{
          position: "absolute",
          top: 60,
          left: "50%",
          transform: "translateX(-50%)",
          background: "rgba(0, 20, 30, 0.85)",
          backdropFilter: "blur(10px)",
          border: "1px solid rgba(0, 229, 255, 0.3)",
          borderRadius: 6,
          padding: "8px 16px",
          zIndex: 15,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}>
          <div style={{
            width: 8, height: 8, borderRadius: "50%",
            background: "#00e5ff",
            boxShadow: "0 0 8px rgba(0,229,255,0.6)",
          }} />
          <span style={{ color: "#00e5ff", fontSize: 12, fontWeight: 600 }}>
            {measurePoints.length === 0
              ? "Click to set start point"
              : measurePoints.length === 1
                ? "Click to set end point"
                : `Distance: ${measureResult} -- click to start new measurement`}
          </span>
          <button
            onClick={() => {
              setMeasureMode(false);
              setMeasurePoints([]);
              setMeasureResult(null);
            }}
            style={{
              background: "none", border: "none", color: "#6B7280",
              cursor: "pointer", fontSize: 14, padding: "0 4px",
            }}
          >
            x
          </button>
        </div>
      )}

      {/* ── Inspect panel ── */}
      {inspected && (
        <div style={{
          position: "absolute",
          bottom: 16,
          left: 16,
          background: "rgba(10, 12, 18, 0.9)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 8,
          padding: "12px 16px",
          minWidth: 220,
          maxWidth: 320,
          zIndex: 15,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span style={{
              fontSize: 10, fontWeight: 700, color: "#D4A018",
              letterSpacing: 1, textTransform: "uppercase",
            }}>
              {inspected.type}
            </span>
            <button
              onClick={() => setInspected(null)}
              style={{
                background: "none", border: "none", color: "#6B7280",
                cursor: "pointer", fontSize: 14, padding: 0,
              }}
            >
              x
            </button>
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#E5E7EB", marginBottom: 4 }}>
            {inspected.name}
          </div>
          {inspected.capacity_mw != null && (
            <div style={{ fontSize: 11, color: "#9CA3AF" }}>
              Capacity: {inspected.capacity_mw} MW
            </div>
          )}
          {inspected.asset_type && (
            <div style={{ fontSize: 11, color: "#9CA3AF" }}>
              Type: {inspected.asset_type}
            </div>
          )}
        </div>
      )}

      {/* ── Coordinate display / scale bar ── */}
      <div style={{
        position: "absolute",
        bottom: 8,
        right: 8,
        background: "rgba(10, 12, 18, 0.7)",
        borderRadius: 4,
        padding: "4px 10px",
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}>
        <span style={{ fontSize: 10, color: "#6B7280", fontFamily: "'IBM Plex Mono', monospace" }}>
          {lat.toFixed(5)}, {lon.toFixed(5)}
        </span>
        <span style={{ fontSize: 10, color: "#4B5563" }}>|</span>
        <span style={{ fontSize: 10, color: "#6B7280" }}>
          Terrain {exaggeration.toFixed(1)}x
        </span>
      </div>

      {/* ── Spinner keyframe (injected once) ── */}
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
