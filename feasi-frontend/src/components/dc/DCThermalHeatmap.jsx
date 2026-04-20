/**
 * DCThermalHeatmap — hall-level thermal layer over the building shell.
 *
 * Pattern: we consume the building shell polygon from DCDesignTwin (a square
 * aligned N/S) and lay a grid of small coloured squares inside it, driven by
 * the `grid` matrix returned from /api/dc/thermal-field (or its client-side
 * mock fallback). Hot aisles / row-end recirculation zones render red; cool
 * intakes near CRAC units render blue.
 *
 * Pickable + hotspots ping with an extra red "HOT" marker so the eye lands
 * on the trouble spots immediately. Airflow arrows (cold → hot) are drawn
 * as PathLayer segments between each CRAC column and the row centreline,
 * which is the pitch-deck moment the GTM briefing asked for.
 */
import React, { useEffect, useState, useMemo } from "react";
import { PolygonLayer, PathLayer, IconLayer, TextLayer } from "@deck.gl/layers";
import { fetchThermalField } from "../../api/dcOps";

const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }

function tempToRgba(t, minT = 18, maxT = 35) {
  const f = Math.max(0, Math.min(1, (t - minT) / (maxT - minT)));
  // blue (0,120,255) → green (40,200,120) → yellow (250,200,40) → red (239,68,68)
  if (f < 0.33) {
    const k = f / 0.33;
    return [Math.round(0 + 40 * k), Math.round(120 + 80 * k), Math.round(255 - 135 * k), 180];
  } else if (f < 0.66) {
    const k = (f - 0.33) / 0.33;
    return [Math.round(40 + 210 * k), Math.round(200 + 0 * k), Math.round(120 - 80 * k), 200];
  } else {
    const k = (f - 0.66) / 0.34;
    return [Math.round(250 - 11 * k), Math.round(200 - 132 * k), Math.round(40 + 28 * k), 220];
  }
}

/**
 * Hook — fetch thermal field keyed on IT load + shell geometry.
 * Returns { loading, field } where field is the API response.
 */
export function useThermalField({ itLoadMw, containment = "hot_aisle", supplyTempC = 18, enabled = true }) {
  const [field, setField] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setLoading(true);
    fetchThermalField({ itLoadMw, containment, supplyTempC })
      .then(f => { if (!cancelled) setField(f); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [itLoadMw, containment, supplyTempC, enabled]);
  return { field, loading };
}

/**
 * Build deck.gl layers that tile the shell with temperature-coloured cells,
 * overlay airflow arrows and mark hotspots.
 *
 *   shell = { polygon, widthM, depthM, lat, lon }
 *   field = { grid, grid_x, grid_y, hotspots }
 */
export function thermalHeatmapLayers({ shell, field, visible = true, showArrows = true }) {
  if (!visible || !shell || !field?.grid || !field.grid_x || !field.grid_y) return [];
  const { widthM, depthM, lat, lon } = shell;
  const { grid, grid_x: nx, grid_y: ny, hotspots = [] } = field;
  const cellW = widthM / nx;
  const cellD = depthM / ny;

  const cells = [];
  for (let y = 0; y < ny; y++) {
    for (let x = 0; x < nx; x++) {
      const t = grid[y]?.[x];
      if (t == null) continue;
      // Cell centre in metres from shell centre — shell origin is [lon,lat].
      const cx = (x + 0.5) * cellW - widthM / 2;
      const cy = depthM / 2 - (y + 0.5) * cellD;   // flip so y=0 is "north" end
      const centreLat = lat + cy / M_PER_DEG_LAT;
      const centreLon = lon + cx / mPerDegLon(lat);
      const half = [cellW / 2, cellD / 2];
      const corners = [
        [centreLon - half[0] / mPerDegLon(lat), centreLat - half[1] / M_PER_DEG_LAT],
        [centreLon + half[0] / mPerDegLon(lat), centreLat - half[1] / M_PER_DEG_LAT],
        [centreLon + half[0] / mPerDegLon(lat), centreLat + half[1] / M_PER_DEG_LAT],
        [centreLon - half[0] / mPerDegLon(lat), centreLat + half[1] / M_PER_DEG_LAT],
      ];
      corners.push(corners[0]);
      cells.push({ polygon: corners, temp: t, x, y, isHotAisle: y % 2 === 1 });
    }
  }

  const layers = [
    new PolygonLayer({
      id: "dc-thermal-cells",
      data: cells,
      getPolygon: d => d.polygon,
      getFillColor: d => tempToRgba(d.temp),
      getLineColor: [0, 0, 0, 0],
      stroked: false,
      filled: true,
      extruded: true,
      getElevation: d => d.isHotAisle ? 6 : 2,   // hot aisles extrude slightly so the eye reads heat vertically
      pickable: true,
      updateTriggers: { getFillColor: [grid] },
    }),
  ];

  // Airflow arrows — from each CRAC column (end of cool rows) into the hall
  // and hot-to-cool mixing arrows at the end of each hot aisle.
  if (showArrows) {
    const arrows = [];
    for (let y = 0; y < ny; y += 2) {
      // Cold supply arrow into each cold row from the west edge.
      const row = y / 2;
      const yOff = depthM / 2 - (y + 0.5) * cellD;
      const startLat = lat + yOff / M_PER_DEG_LAT;
      const startLon = lon + (-widthM / 2 - 3) / mPerDegLon(lat);
      const endLon = lon + (widthM / 2 - 2) / mPerDegLon(lat);
      arrows.push({ path: [[startLon, startLat], [endLon, startLat]], kind: "cold", row });
    }
    // Hot return arrows — from end-of-row to the CRAC (drawn as short red strokes at east edge).
    for (let y = 1; y < ny; y += 2) {
      const yOff = depthM / 2 - (y + 0.5) * cellD;
      const startLat = lat + yOff / M_PER_DEG_LAT;
      const startLon = lon + (widthM / 2 - 2) / mPerDegLon(lat);
      const endLon = lon + (widthM / 2 + 6) / mPerDegLon(lat);
      arrows.push({ path: [[startLon, startLat], [endLon, startLat]], kind: "hot", row: (y - 1) / 2 });
    }
    layers.push(new PathLayer({
      id: "dc-thermal-arrows",
      data: arrows,
      getPath: d => d.path,
      getColor: d => d.kind === "cold" ? [80, 180, 255, 220] : [239, 80, 80, 220],
      getWidth: 2,
      widthMinPixels: 2,
      capRounded: true,
    }));
  }

  // Hotspot pins — explicit red marker over any cell flagged as warm/critical.
  if (hotspots.length > 0) {
    const pins = hotspots.map(h => {
      const cx = (h.col + 0.5) * cellW - widthM / 2;
      const cy = depthM / 2 - (h.row * 2 + 0.5) * cellD;
      return {
        lon: lon + cx / mPerDegLon(lat),
        lat: lat + cy / M_PER_DEG_LAT,
        severity: h.severity,
        temp: h.inlet_temp_c,
      };
    });
    layers.push(new IconLayer({
      id: "dc-thermal-hotspot-pins",
      data: pins,
      getPosition: d => [d.lon, d.lat],
      getSize: d => d.severity === "CRITICAL" ? 26 : 20,
      sizeUnits: "pixels",
      getColor: d => d.severity === "CRITICAL" ? [239, 68, 68, 255] : [245, 183, 49, 255],
      // Inline SVG "!" disc as a data: URL so we don't ship a new asset.
      getIcon: () => ({
        url: "data:image/svg+xml;utf8," + encodeURIComponent(
          `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>
            <circle cx='16' cy='16' r='14' fill='currentColor' stroke='white' stroke-width='2'/>
            <text x='16' y='22' text-anchor='middle' font-family='sans-serif'
                  font-size='20' font-weight='700' fill='white'>!</text>
          </svg>`),
        width: 32, height: 32,
      }),
      pickable: true,
    }));
    layers.push(new TextLayer({
      id: "dc-thermal-hotspot-labels",
      data: pins,
      getPosition: d => [d.lon, d.lat],
      getText: d => `${d.temp}°`,
      getSize: 10,
      getColor: [255, 255, 255, 230],
      getPixelOffset: [0, 14],
      background: true,
      getBackgroundColor: [31, 41, 55, 200],
      backgroundPadding: [3, 1],
      fontFamily: '"JetBrains Mono", monospace',
      fontWeight: 700,
    }));
  }

  return layers;
}

export default function DCThermalHeatmap() {
  // Rendered purely through `thermalHeatmapLayers` + `useThermalField` above;
  // this default export exists so the file is a valid React component module.
  return null;
}
