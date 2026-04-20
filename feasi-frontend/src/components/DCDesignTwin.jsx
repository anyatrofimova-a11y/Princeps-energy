/**
 * DCDesignTwin — Real-terrain 3D simulation of a Pre-FID Data Centre design.
 *
 * Replaces the abstract "racks floating in white void" view that DCPhysicalTwin
 * showed on the Plan/Design tab. Renders the proposed DC building shell, cooling
 * yard, on-site substation pad, cable corridor and access road as deck.gl
 * extrusions on top of Mapbox satellite + 3D buildings + raster-DEM terrain at
 * the user's picked lat/lon.
 *
 * Engineering rules of thumb used (deterministic — no backend round-trip
 * required for first paint; refine via /api/dc/site-design/{id} when wired):
 *   • Building footprint: 600 m² per MW IT load (2-storey shell, GFA 1,200 m²/MW)
 *   • Building height: 12 m base + 0.4 m per MW (capped 24 m); UK B8 typical
 *   • Cooling yard: 35% of building footprint, height 5 m, placed south of shell
 *   • On-site substation pad: 0.6 ha for ≤50 MW, 1.2 ha for ≤200 MW
 *   • Cable corridor: straight line shell-edge → substation pad (cost-of-rights
 *     calc would route around obstacles; out of scope for first paint)
 *   • Access road: 60 m spur from nearest mapped road (placeholder NE of site)
 *   • Perimeter fence: 5 m offset from building shell
 *
 * The geometry is meant to be DIRECTIONALLY CORRECT for engineer review at
 * Pre-FID — not survey-grade. Polygon refinement happens in DesignCanvas.
 */
import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PolygonLayer, PathLayer, ScatterplotLayer, TextLayer, IconLayer } from "@deck.gl/layers";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

const C = {
  shell:       [147, 51, 234, 230],   // purple — building shell
  shellEdge:   [88, 28, 135, 255],
  cooling:     [16, 185, 129, 220],   // green — cooling yard
  coolingEdge: [4, 120, 87, 255],
  substation:  [217, 119, 6, 230],    // amber — substation pad
  subEdge:     [120, 53, 15, 255],
  cable:       [239, 68, 68, 255],    // red — cable corridor
  road:        [100, 116, 139, 255],  // slate — access road
  fence:       [156, 163, 175, 200],  // grey — perimeter fence
};

/* Geo helpers — flat-earth approximation; fine for a few km at this latitude. */
const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }
function offsetMeters(lat, lon, dxMeters, dyMeters) {
  return [lon + dxMeters / mPerDegLon(lat), lat + dyMeters / M_PER_DEG_LAT];
}
function rectanglePolygon(lat, lon, widthM, depthM, rotationDeg = 0) {
  const cosR = Math.cos((rotationDeg * Math.PI) / 180);
  const sinR = Math.sin((rotationDeg * Math.PI) / 180);
  const corners = [
    [-widthM / 2, -depthM / 2],
    [+widthM / 2, -depthM / 2],
    [+widthM / 2, +depthM / 2],
    [-widthM / 2, +depthM / 2],
  ];
  const ring = corners.map(([x, y]) => {
    const rx = x * cosR - y * sinR;
    const ry = x * sinR + y * cosR;
    return offsetMeters(lat, lon, rx, ry);
  });
  ring.push(ring[0]);
  return ring;
}

/* Derive site geometry deterministically from IT load + a parcel area hint.
 * Cooling yard sits south, substation pad east, cable corridor connects them.
 * Access road is a 60 m spur off the NE corner. */
function deriveSiteGeometry({ lat, lon, itLoadMw, parcelHa }) {
  const safeMw = Math.max(1, itLoadMw || 50);
  const shellArea = safeMw * 600;            // m²
  const shellSide = Math.sqrt(shellArea);     // square shell (a hyperscale hall is closer to 100×120 m, but square is fine for visualisation)
  const shellWidth = shellSide;
  const shellDepth = shellSide;
  const shellHeight = Math.min(24, 12 + 0.4 * safeMw);

  const coolingArea = shellArea * 0.35;
  const coolingWidth = Math.sqrt(coolingArea * 1.4);
  const coolingDepth = coolingArea / coolingWidth;
  // cooling yard sits south of shell, with 8 m corridor between
  const [coolLon, coolLat] = offsetMeters(lat, lon, 0, -(shellDepth / 2 + 8 + coolingDepth / 2));

  const subSide = safeMw <= 50 ? 78 : safeMw <= 200 ? 110 : 140;   // m
  // substation pad sits east of shell, 25 m gap
  const [subLon, subLat] = offsetMeters(lat, lon, shellWidth / 2 + 25 + subSide / 2, 0);

  // perimeter fence: shell + 12 m offset
  const fenceWidth = shellWidth + 24;
  const fenceDepth = shellDepth + 24 + coolingDepth + 16;
  const [fenceLon, fenceLat] = offsetMeters(lat, lon, 0, -(coolingDepth + 16) / 2);

  // access road spur: from NE fence corner outward 60 m
  const fenceNE = offsetMeters(fenceLat, fenceLon, fenceWidth / 2, fenceDepth / 2);
  const roadEnd = offsetMeters(fenceNE[1], fenceNE[0], 60, 60);

  // cable corridor: from shell east edge mid → sub west edge mid
  const cableStart = offsetMeters(lat, lon, shellWidth / 2, 0);
  const cableEnd   = offsetMeters(subLat, subLon, -subSide / 2, 0);

  return {
    parcelArea: parcelHa ? parcelHa * 10000 : null,
    shell: {
      polygon: rectanglePolygon(lat, lon, shellWidth, shellDepth, 0),
      heightM: shellHeight,
      widthM: shellWidth, depthM: shellDepth, areaM2: shellArea,
      lat, lon,
    },
    cooling: {
      polygon: rectanglePolygon(coolLat, coolLon, coolingWidth, coolingDepth, 0),
      heightM: 5,
      widthM: coolingWidth, depthM: coolingDepth, areaM2: coolingArea,
    },
    substation: {
      polygon: rectanglePolygon(subLat, subLon, subSide, subSide, 0),
      heightM: 8,
      sideM: subSide,
    },
    fence: {
      polygon: rectanglePolygon(fenceLat, fenceLon, fenceWidth, fenceDepth, 0),
      widthM: fenceWidth, depthM: fenceDepth,
    },
    cable: { start: cableStart, end: cableEnd },
    road:  { start: fenceNE, end: roadEnd },
  };
}

function fmtArea(m2) {
  if (m2 == null) return "—";
  if (m2 >= 10_000) return `${(m2 / 10_000).toFixed(2)} ha`;
  return `${Math.round(m2).toLocaleString()} m²`;
}

export default function DCDesignTwin({
  lat = 51.4974,
  lon = -0.5683,
  itLoadMw = 50,
  parcelHa = null,
  tier = 3,
  redundancy = "N+1",
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [hoverInfo, setHoverInfo] = useState(null);
  const [showFence, setShowFence] = useState(true);
  const [showLabels, setShowLabels] = useState(true);

  const geom = useMemo(
    () => deriveSiteGeometry({ lat, lon, itLoadMw, parcelHa }),
    [lat, lon, itLoadMw, parcelHa]
  );

  /* ── Mount Mapbox ── */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) {
      console.warn("[DCDesignTwin] VITE_MAPBOX_TOKEN missing — skipping map init");
      return;
    }

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [lon, lat],
      zoom: 16.5,
      pitch: 60,
      bearing: -25,
      antialias: true,
    });

    map.on("load", () => {
      // 3D terrain
      map.addSource("dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
      map.setTerrain({ source: "dem", exaggeration: 1.4 });

      // Sky
      map.addLayer({
        id: "sky", type: "sky",
        paint: { "sky-type": "atmosphere", "sky-atmosphere-sun": [0, 45], "sky-atmosphere-sun-intensity": 5 },
      });

      // Existing 3D buildings (greyed out so the new design reads as the hero)
      const labelLayer = map.getStyle().layers.find(l => l.type === "symbol" && l.layout?.["text-field"]);
      map.addLayer({
        id: "3d-buildings-context",
        source: "composite",
        "source-layer": "building",
        filter: ["==", "extrude", "true"],
        type: "fill-extrusion",
        minzoom: 14,
        paint: {
          "fill-extrusion-color": "#cbd5e1",
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": ["get", "min_height"],
          "fill-extrusion-opacity": 0.55,
        },
      }, labelLayer?.id);

      const overlay = new MapboxOverlay({ layers: [] });
      map.addControl(overlay);
      overlayRef.current = overlay;
      setMapReady(true);
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; overlayRef.current = null; };
  }, []); // eslint-disable-line

  /* ── Recentre when lat/lon change without remounting ── */
  useEffect(() => {
    if (mapRef.current && mapReady) {
      mapRef.current.flyTo({ center: [lon, lat], zoom: 16.5, pitch: 60, duration: 1200 });
    }
  }, [lat, lon, mapReady]);

  /* ── Build deck.gl layers from derived geometry ── */
  const deckLayers = useMemo(() => {
    if (!mapReady) return [];
    const layers = [];

    // Building shell — extruded purple polygon
    layers.push(new PolygonLayer({
      id: "dc-shell",
      data: [{ polygon: geom.shell.polygon, ...geom.shell }],
      getPolygon: d => d.polygon,
      getElevation: () => geom.shell.heightM,
      getFillColor: C.shell,
      getLineColor: C.shellEdge,
      lineWidthMinPixels: 2,
      extruded: true,
      pickable: true,
      onHover: ({ object, x, y }) => setHoverInfo(object ? {
        x, y,
        title: "Building shell",
        rows: [
          ["Footprint", fmtArea(geom.shell.areaM2)],
          ["Height", `${geom.shell.heightM.toFixed(1)} m`],
          ["IT load", `${itLoadMw} MW`],
          ["GFA (2-storey)", fmtArea(geom.shell.areaM2 * 2)],
        ],
      } : null),
    }));

    // Cooling yard
    layers.push(new PolygonLayer({
      id: "dc-cooling",
      data: [{ polygon: geom.cooling.polygon }],
      getPolygon: d => d.polygon,
      getElevation: () => geom.cooling.heightM,
      getFillColor: C.cooling,
      getLineColor: C.coolingEdge,
      lineWidthMinPixels: 1.5,
      extruded: true,
      pickable: true,
      onHover: ({ object, x, y }) => setHoverInfo(object ? {
        x, y,
        title: "Cooling yard",
        rows: [
          ["Area", fmtArea(geom.cooling.areaM2)],
          ["Height", `${geom.cooling.heightM} m`],
          ["Modules", redundancy === "2N" || redundancy === "2N+1" ? "Dual-side, redundant" : "Single-side, N+1"],
        ],
      } : null),
    }));

    // Substation pad
    layers.push(new PolygonLayer({
      id: "dc-substation",
      data: [{ polygon: geom.substation.polygon }],
      getPolygon: d => d.polygon,
      getElevation: () => geom.substation.heightM,
      getFillColor: C.substation,
      getLineColor: C.subEdge,
      lineWidthMinPixels: 1.5,
      extruded: true,
      pickable: true,
      onHover: ({ object, x, y }) => setHoverInfo(object ? {
        x, y,
        title: "On-site substation",
        rows: [
          ["Pad", `${geom.substation.sideM} × ${geom.substation.sideM} m`],
          ["Plant", "GIS switchgear · 33/132 kV"],
          ["Tier path", tier >= 3 ? "Dual feed" : "Single feed"],
        ],
      } : null),
    }));

    // Cable corridor
    layers.push(new PathLayer({
      id: "dc-cable",
      data: [{ path: [geom.cable.start, geom.cable.end] }],
      getPath: d => d.path,
      getColor: C.cable,
      widthMinPixels: 4,
      capRounded: true,
      jointRounded: true,
    }));

    // Access road
    layers.push(new PathLayer({
      id: "dc-road",
      data: [{ path: [geom.road.start, geom.road.end] }],
      getPath: d => d.path,
      getColor: C.road,
      widthMinPixels: 8,
      capRounded: true,
    }));

    // Perimeter fence as polygon outline
    if (showFence) {
      layers.push(new PolygonLayer({
        id: "dc-fence",
        data: [{ polygon: geom.fence.polygon }],
        getPolygon: d => d.polygon,
        getFillColor: [0, 0, 0, 0],
        getLineColor: C.fence,
        lineWidthMinPixels: 2,
        getDashArray: [6, 4],
        extruded: false,
        stroked: true,
        filled: false,
      }));
    }

    // Labels
    if (showLabels) {
      layers.push(new TextLayer({
        id: "dc-labels",
        data: [
          { lon: geom.shell.lon, lat: geom.shell.lat, text: "Building shell" },
          { lon: geom.cooling.polygon[0][0], lat: geom.cooling.polygon[0][1], text: "Cooling yard" },
          { lon: geom.substation.polygon[0][0], lat: geom.substation.polygon[0][1], text: "On-site sub" },
        ],
        getPosition: d => [d.lon, d.lat],
        getText: d => d.text,
        getSize: 13,
        getColor: [255, 255, 255, 240],
        getPixelOffset: [0, -8],
        background: true,
        getBackgroundColor: [15, 23, 42, 200],
        backgroundPadding: [4, 2],
        fontFamily: '"DM Sans", sans-serif',
        fontWeight: 700,
      }));
    }

    return layers;
  }, [geom, mapReady, showFence, showLabels, itLoadMw, redundancy, tier]);

  useEffect(() => {
    if (overlayRef.current) overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", minHeight: 480, background: "#0f172a" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

      {!mapboxgl.accessToken && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          background: "rgba(15,23,42,0.92)", color: "#cbd5e1", textAlign: "center",
          fontFamily: '"DM Sans", sans-serif', padding: 32,
        }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>Mapbox token missing</div>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>
              Add <code>VITE_MAPBOX_TOKEN=pk.…</code> to <code>feasi-frontend/.env</code> and restart Vite.
            </div>
          </div>
        </div>
      )}

      {/* Layer toggle chip */}
      <div style={{
        position: "absolute", top: 12, left: 12, display: "flex", gap: 6,
        background: "rgba(15,23,42,0.85)", padding: "6px 8px", borderRadius: 8,
        fontFamily: '"DM Sans", sans-serif', fontSize: 11, color: "#e2e8f0",
        backdropFilter: "blur(6px)",
      }}>
        <button onClick={() => setShowFence(s => !s)} style={chipBtn(showFence)}>Fence</button>
        <button onClick={() => setShowLabels(s => !s)} style={chipBtn(showLabels)}>Labels</button>
      </div>

      {/* Legend */}
      <div style={{
        position: "absolute", bottom: 12, left: 12,
        background: "rgba(15,23,42,0.88)", padding: "10px 12px", borderRadius: 8,
        fontFamily: '"DM Sans", sans-serif', fontSize: 11, color: "#e2e8f0",
        backdropFilter: "blur(6px)", lineHeight: 1.6,
      }}>
        <div style={{ fontWeight: 700, marginBottom: 4, letterSpacing: 0.4, textTransform: "uppercase", fontSize: 9, color: "#94a3b8" }}>
          Pre-FID layout · {itLoadMw} MW · Tier {tier} · {redundancy}
        </div>
        <Swatch c={C.shell} label={`Shell ${(geom.shell.areaM2 / 10_000).toFixed(2)} ha · ${geom.shell.heightM.toFixed(0)} m`} />
        <Swatch c={C.cooling} label={`Cooling ${(geom.cooling.areaM2 / 10_000).toFixed(2)} ha`} />
        <Swatch c={C.substation} label={`On-site sub ${geom.substation.sideM} × ${geom.substation.sideM} m`} />
        <Swatch c={C.cable} label="Cable corridor" />
        <Swatch c={C.road} label="Access road" />
      </div>

      {/* Hover tip */}
      {hoverInfo && (
        <div style={{
          position: "absolute", left: hoverInfo.x + 12, top: hoverInfo.y + 12,
          background: "rgba(15,23,42,0.94)", color: "#f1f5f9",
          padding: "10px 12px", borderRadius: 8, fontFamily: '"DM Sans", sans-serif',
          fontSize: 11, pointerEvents: "none", boxShadow: "0 6px 24px rgba(0,0,0,0.4)",
          zIndex: 5,
        }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 4 }}>{hoverInfo.title}</div>
          {hoverInfo.rows.map((r, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
              <span style={{ color: "#94a3b8" }}>{r[0]}</span>
              <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>{r[1]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Swatch({ c, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 10, height: 10, borderRadius: 2,
        background: `rgba(${c[0]},${c[1]},${c[2]},${(c[3] || 255) / 255})`,
        display: "inline-block",
      }} />
      <span>{label}</span>
    </div>
  );
}

function chipBtn(active) {
  return {
    padding: "4px 9px", borderRadius: 5, border: "none",
    background: active ? "#f5b731" : "rgba(255,255,255,0.08)",
    color: active ? "#0f172a" : "#e2e8f0",
    fontWeight: 700, fontSize: 10, cursor: "pointer",
    fontFamily: '"DM Sans", sans-serif',
  };
}
