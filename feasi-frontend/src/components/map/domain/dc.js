/**
 * Domain layer pack — DATA CENTRE.
 *
 * Answers: "What does a hyperscale / colo DC need to care about?"
 *
 * Sub-layers:
 *   1. dc_grid_proximity   — 132kV+ substation density / 5km buffers (mocked via fibre_points metric)
 *   2. dc_water            — EA CAMS stress zones
 *   3. dc_fibre            — Openreach + alt-net fibre density
 *   4. dc_hyperscaler      — Google / AWS / MS / Meta / Oracle UK sites
 *   5. dc_latency          — isochrones to London LINX (2/5/10/20 ms)
 *   6. dc_precedents       — DC planning approvals/refusals
 *
 * Data: src/data/domain-fixtures/dc-fibre-coverage.json (MOCK).
 */

import { ScatterplotLayer, PolygonLayer, TextLayer } from "@deck.gl/layers";
import dcFixture from "../../../data/domain-fixtures/dc-fibre-coverage.json";

export const DC_SUBLAYERS = [
  { id: "dc_grid_proximity", label: "Grid proximity (132kV+)",  color: "#D4A018", defaultOn: true  },
  { id: "dc_water",          label: "Water stress (EA CAMS)",    color: "#2563EB", defaultOn: true  },
  { id: "dc_fibre",          label: "Fibre density",             color: "#21918C", defaultOn: true  },
  { id: "dc_hyperscaler",    label: "Hyperscaler estate",        color: "#4285F4", defaultOn: true  },
  { id: "dc_latency",        label: "Latency to LINX",           color: "#A56EFF", defaultOn: false },
  { id: "dc_precedents",     label: "DC planning precedents",    color: "#24a148", defaultOn: true  },
];

export const DC_ACCENT = "#4285F4"; // cloud-blue accent

function fibreColour(score) {
  const s = Math.max(0, Math.min(1, score));
  if (s >= 0.85) return [33, 145, 140, 220];   // teal
  if (s >= 0.70) return [94, 201, 98, 210];
  if (s >= 0.55) return [253, 231, 37, 200];
  if (s >= 0.40) return [245, 158, 11, 190];
  return [180, 60, 60, 180];
}

function gridProximityColour(latency_ms) {
  // Use latency as proxy — tight to London where 400kV SHETL/NGET spines concentrate
  if (latency_ms <= 3)  return [212, 160, 24, 230];
  if (latency_ms <= 6)  return [245, 158, 11, 210];
  if (latency_ms <= 12) return [253, 231, 37, 180];
  return [200, 200, 200, 120];
}

function waterColour(stress) {
  if (stress === "serious")  return [220, 38, 38, 80];
  if (stress === "moderate") return [245, 158, 11, 60];
  return [37, 99, 235, 40];
}

function hyperscalerColour(op) {
  const map = {
    AWS:       [255, 153, 0,   235],
    Microsoft: [0, 120, 212,   235],
    Google:    [66, 133, 244,  235],
    Meta:      [24, 119, 242,  235],
    Oracle:    [248, 0, 0,     235],
    Equinix:   [239, 18, 36,   235],
    Virtus:    [139, 92, 246,  235],
  };
  return map[op] || [128, 128, 128, 220];
}

function latencyColour(ms) {
  if (ms <= 2)  return [165, 110, 255, 90];
  if (ms <= 5)  return [165, 110, 255, 60];
  if (ms <= 10) return [165, 110, 255, 40];
  return [165, 110, 255, 25];
}

function precedentColour(status) {
  if (status === "approved") return [36, 161, 72, 230];
  if (status === "refused")  return [220, 38, 38, 230];
  return [245, 158, 11, 230];
}

export function makeDcLayers({ active = {}, onHover, onClick } = {}) {
  const points = dcFixture.fibre_points || [];
  const layers = [];

  // 2. Water stress zones (drawn first so other layers sit on top)
  if (active.dc_water !== false) {
    const cams = dcFixture.ea_cams_zones || [];
    layers.push(new PolygonLayer({
      id: "dc_water",
      data: cams,
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => waterColour(d.stress),
      getLineColor: [37, 99, 235, 180],
      lineWidthMinPixels: 1.0,
      stroked: true,
      filled: true,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 5. Latency isochrones to LINX (draw below point layers)
  if (active.dc_latency) {
    const iso = dcFixture.linx_isochrones || [];
    // draw widest first so narrowest is on top
    const sorted = [...iso].sort((a, b) => b.latency_ms - a.latency_ms);
    layers.push(new PolygonLayer({
      id: "dc_latency",
      data: sorted,
      getPolygon: (d) => d.polygon,
      getFillColor: (d) => latencyColour(d.latency_ms),
      getLineColor: [165, 110, 255, 180],
      lineWidthMinPixels: 0.8,
      stroked: true,
      filled: true,
      pickable: false,
    }));
  }

  // 1. Grid proximity — gold halo around high-fibre / low-latency nodes (proxy)
  if (active.dc_grid_proximity !== false) {
    layers.push(new ScatterplotLayer({
      id: "dc_grid_proximity",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => gridProximityColour(d.latency_ms),
      getRadius: 5000,
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.4,
      pickable: false,
    }));
  }

  // 3. Fibre density
  if (active.dc_fibre !== false) {
    layers.push(new ScatterplotLayer({
      id: "dc_fibre",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => fibreColour(d.fibre_score),
      getRadius: (d) => 3000 + 5000 * (d.fibre_score || 0),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: (d) => d.dark_fibre ? [33, 145, 140, 230] : [60, 60, 60, 150],
      lineWidthMinPixels: (d) => d.dark_fibre ? 1.5 : 0.4,
      opacity: 0.8,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 4. Hyperscaler estate
  if (active.dc_hyperscaler !== false) {
    const hs = dcFixture.hyperscaler_sites || [];
    layers.push(new ScatterplotLayer({
      id: "dc_hyperscaler",
      data: hs,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => hyperscalerColour(d.operator),
      getRadius: (d) => d.status === "live" ? 3500 : 2500,
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [255, 248, 232, 240],
      lineWidthMinPixels: 2,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
    layers.push(new TextLayer({
      id: "dc_hyperscaler_labels",
      data: hs,
      getPosition: (d) => [d.lon, d.lat],
      getText: (d) => d.operator,
      getSize: 11,
      getColor: [30, 30, 30, 230],
      getPixelOffset: [0, -18],
      fontFamily: "Inter, system-ui, sans-serif",
      fontWeight: 600,
      background: true,
      backgroundPadding: [4, 2],
      getBackgroundColor: [255, 248, 232, 220],
      pickable: false,
    }));
  }

  // 6. DC precedents
  if (active.dc_precedents !== false) {
    const precedents = dcFixture.dc_precedents || [];
    layers.push(new ScatterplotLayer({
      id: "dc_precedents",
      data: precedents,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => precedentColour(d.status),
      getRadius: (d) => 2500 + 12 * Math.sqrt(d.capacity_mw || 1),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [255, 248, 232, 230],
      lineWidthMinPixels: 1.2,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  return layers;
}

export const DC_PACK = {
  id: "dc",
  label: "Data Centre",
  accent: DC_ACCENT,
  sublayers: DC_SUBLAYERS,
  build: makeDcLayers,
};

export default DC_PACK;
