/**
 * Domain layer pack — WIND.
 *
 * Answers: "What does a wind project need to care about on the map?"
 *
 * Sub-layers:
 *   1. wind_speed        — 100m hub-height wind speed m/s heatmap
 *   2. wind_turbulence   — turbulence intensity (IEC classes)
 *   3. wind_aviation     — CAA CTR + MoD safeguarding buffers
 *   4. wind_radar        — NATS/DRA radar interference zones
 *   5. wind_precedents   — REPD onshore + offshore wind
 *   6. wind_exclusions   — AONB / National Park crosshatch
 *
 * Data: src/data/domain-fixtures/wind-dwpt-grid.json (MOCK GB + offshore).
 */

import { ScatterplotLayer, PolygonLayer } from "@deck.gl/layers";
import windFixture from "../../../data/domain-fixtures/wind-dwpt-grid.json";

export const WIND_SUBLAYERS = [
  { id: "wind_speed",       label: "Wind speed 100m (m/s)",  color: "#21918C", defaultOn: true  },
  { id: "wind_turbulence",  label: "Turbulence intensity",    color: "#F59E0B", defaultOn: false },
  { id: "wind_aviation",    label: "Aviation (CAA / MoD)",    color: "#DC2626", defaultOn: true  },
  { id: "wind_radar",       label: "Radar interference",      color: "#9333EA", defaultOn: false },
  { id: "wind_precedents",  label: "Wind precedents",         color: "#24a148", defaultOn: true  },
  { id: "wind_exclusions",  label: "AONB / National Park",    color: "#ef4444", defaultOn: true  },
];

export const WIND_ACCENT = "#21918C"; // teal

function viridis(t) {
  const t01 = Math.max(0, Math.min(1, t));
  if (t01 < 0.25) return [68, 1, 84];
  if (t01 < 0.40) return [59, 82, 139];
  if (t01 < 0.55) return [33, 145, 140];
  if (t01 < 0.75) return [94, 201, 98];
  return [253, 231, 37];
}

function windSpeedColour(ws) {
  // range ~6-12 m/s in fixture
  const t = (ws - 6) / (12 - 6);
  return [...viridis(t), 200];
}

function turbulenceColour(ti) {
  // IEC classes: <0.14 low (III), <0.16 med (II), <0.18 high (I), >0.20 extreme (urban)
  if (ti < 0.12) return [94, 201, 98, 180];
  if (ti < 0.15) return [253, 231, 37, 190];
  if (ti < 0.18) return [245, 158, 11, 210];
  if (ti < 0.20) return [249, 115, 22, 220];
  return [220, 38, 38, 230];
}

function aviationColour(type) {
  if (type === "CTR") return [220, 38, 38, 55];
  if (type === "MoD") return [127, 29, 29, 70];
  return [220, 38, 38, 55];
}

function precedentColour(status) {
  if (status === "approved") return [36, 161, 72, 230];
  if (status === "refused")  return [220, 38, 38, 230];
  return [245, 158, 11, 230];
}

/** Convert (lon,lat, radius_km) into an approx polygon ring for deck.gl PolygonLayer.
 *  Rough equirectangular conversion — fine at GB zoom. */
function circlePolygon(lon, lat, radius_km, n = 48) {
  const coords = [];
  const kmPerDegLat = 111.32;
  const kmPerDegLon = 111.32 * Math.cos((lat * Math.PI) / 180);
  for (let i = 0; i <= n; i++) {
    const theta = (i / n) * 2 * Math.PI;
    coords.push([
      lon + (radius_km * Math.cos(theta)) / kmPerDegLon,
      lat + (radius_km * Math.sin(theta)) / kmPerDegLat,
    ]);
  }
  return coords;
}

export function makeWindLayers({ active = {}, onHover, onClick } = {}) {
  const points = windFixture.points || [];
  const layers = [];

  // 1. Wind speed heatmap
  if (active.wind_speed !== false) {
    layers.push(new ScatterplotLayer({
      id: "wind_speed",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => windSpeedColour(d.ws100),
      getRadius: (d) => 10000 + 4000 * (d.ws100 || 7),
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.45,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 2. Turbulence intensity
  if (active.wind_turbulence) {
    layers.push(new ScatterplotLayer({
      id: "wind_turbulence",
      data: points,
      getPosition: (d) => [d.lon + 0.02, d.lat + 0.02],
      getFillColor: (d) => turbulenceColour(d.tc_intensity),
      getRadius: 7500,
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [40, 40, 40, 160],
      lineWidthMinPixels: 0.4,
      opacity: 0.6,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 3. Aviation buffers
  if (active.wind_aviation !== false) {
    const buffers = (windFixture.aviation_buffers || []).map((b) => ({
      ...b,
      polygon: circlePolygon(b.lon, b.lat, b.radius_km),
    }));
    layers.push(new PolygonLayer({
      id: "wind_aviation",
      data: buffers,
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => aviationColour(d.type),
      getLineColor: [220, 38, 38, 220],
      lineWidthMinPixels: 1.2,
      stroked: true,
      filled: true,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 4. Radar interference
  if (active.wind_radar) {
    const radar = (windFixture.radar_interference || []).map((r) => ({
      ...r,
      polygon: circlePolygon(r.lon, r.lat, r.radius_km),
    }));
    layers.push(new PolygonLayer({
      id: "wind_radar",
      data: radar,
      getPolygon: (d) => d.polygon,
      getFillColor: [147, 51, 234, 50],
      getLineColor: [147, 51, 234, 200],
      lineWidthMinPixels: 1.0,
      stroked: true,
      filled: true,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 5. Precedents — onshore (filled) vs offshore (stroked ring)
  if (active.wind_precedents !== false) {
    const precedents = windFixture.wind_precedents || [];
    layers.push(new ScatterplotLayer({
      id: "wind_precedents",
      data: precedents,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) =>
        d.sub === "offshore"
          ? [...precedentColour(d.status).slice(0, 3), 100]
          : precedentColour(d.status),
      getRadius: (d) => 3000 + 8 * Math.sqrt(d.capacity_mw || 1),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: (d) => precedentColour(d.status),
      lineWidthMinPixels: 2,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 6. AONB / NP exclusion
  if (active.wind_exclusions !== false) {
    const aonb = windFixture.aonb_exclusions || [];
    layers.push(new PolygonLayer({
      id: "wind_exclusions",
      data: aonb,
      getPolygon: (d) => d.polygon,
      getFillColor: [239, 68, 68, 64],
      getLineColor: [200, 28, 32, 220],
      lineWidthMinPixels: 1.5,
      stroked: true,
      filled: true,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  return layers;
}

export const WIND_PACK = {
  id: "wind",
  label: "Wind",
  accent: WIND_ACCENT,
  sublayers: WIND_SUBLAYERS,
  build: makeWindLayers,
};

export default WIND_PACK;
