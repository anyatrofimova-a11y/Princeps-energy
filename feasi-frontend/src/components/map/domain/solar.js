/**
 * Domain layer pack — SOLAR.
 *
 * Answers: "What does a solar project need to care about on the map?"
 *
 * Sub-layers (all toggleable via DomainLayerToggle):
 *   1. solar_irradiance    — GHI heatmap (viridis, scatter approximation)
 *   2. solar_slope         — slope angle heatmap 0-45 deg
 *   3. solar_aspect        — south-facing bias halo (aspect within ±45 of 180 deg)
 *   4. solar_suitability   — composite panel siting score (precomputed per point)
 *   5. solar_precedents    — REPD approved/refused solar sites
 *   6. solar_exclusions    — AONB / Green Belt red crosshatch overlay
 *
 * Data: src/data/domain-fixtures/solar-irradiance-grid.json (MOCK GB grid).
 * Palette: Princeps ivory/gold/ink + viridis ramp for irradiance.
 */

import { ScatterplotLayer, PolygonLayer } from "@deck.gl/layers";
import solarFixture from "../../../data/domain-fixtures/solar-irradiance-grid.json";

export const SOLAR_SUBLAYERS = [
  { id: "solar_irradiance",  label: "Irradiance (kWh/m²/yr)", color: "#FDE725", defaultOn: true  },
  { id: "solar_slope",       label: "Slope angle (0-45°)",    color: "#3B528B", defaultOn: false },
  { id: "solar_aspect",      label: "South-facing aspect",    color: "#D4A018", defaultOn: false },
  { id: "solar_suitability", label: "Siting suitability",     color: "#21918C", defaultOn: true  },
  { id: "solar_precedents",  label: "REPD precedents",        color: "#24a148", defaultOn: true  },
  { id: "solar_exclusions",  label: "AONB / Green Belt",      color: "#ef4444", defaultOn: true  },
];

export const SOLAR_ACCENT = "#D4A018"; // Princeps gold

/* ── Viridis ramp 0-1 (colour-blind safe) ── */
function viridis(t) {
  const t01 = Math.max(0, Math.min(1, t));
  if (t01 < 0.25) return [68, 1, 84];
  if (t01 < 0.40) return [59, 82, 139];
  if (t01 < 0.55) return [33, 145, 140];
  if (t01 < 0.75) return [94, 201, 98];
  return [253, 231, 37];
}

/* Normalise GHI across fixture range (roughly 800-1200) */
function ghiColour(ghi) {
  const t = (ghi - 800) / (1200 - 800);
  return [...viridis(t), 190];
}

/* Slope: 0-45 deg; higher = redder (inverse of suitability) */
function slopeColour(slope_deg) {
  const t = Math.max(0, Math.min(1, slope_deg / 20));
  if (t < 0.2) return [94, 201, 98, 180];
  if (t < 0.4) return [253, 231, 37, 180];
  if (t < 0.6) return [250, 140, 22, 190];
  if (t < 0.8) return [245, 60, 45, 200];
  return [200, 28, 32, 210];
}

/* Aspect: gold halo when within ±45° of due south (180°) */
function aspectAlpha(aspect_deg) {
  const diff = Math.abs(((aspect_deg - 180 + 540) % 360) - 180);
  if (diff > 90) return 0;
  return Math.round(220 * (1 - diff / 90));
}

/* Suitability score 0-1 → green→gold→red */
function suitabilityColour(score) {
  const s = Math.max(0, Math.min(1, score));
  if (s >= 0.80) return [36, 161, 72,  200];
  if (s >= 0.65) return [212, 160, 24, 200];
  if (s >= 0.50) return [245, 158, 11, 200];
  if (s >= 0.35) return [239, 68, 68,  200];
  return [127, 29, 29, 200];
}

/* Precedent marker colour by status */
function precedentColour(status) {
  if (status === "approved") return [36, 161, 72, 220];
  if (status === "refused")  return [220, 38, 38, 220];
  return [245, 158, 11, 220]; // pending
}

export function makeSolarLayers({ active = {}, onHover, onClick } = {}) {
  const points = solarFixture.points || [];
  const layers = [];

  // 1. Irradiance heatmap — large faded discs
  if (active.solar_irradiance !== false) {
    layers.push(new ScatterplotLayer({
      id: "solar_irradiance",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => ghiColour(d.ghi),
      getRadius: 18000,
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.35,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
      updateTriggers: { getFillColor: [points.length] },
    }));
  }

  // 2. Slope
  if (active.solar_slope) {
    layers.push(new ScatterplotLayer({
      id: "solar_slope",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => slopeColour(d.slope_deg),
      getRadius: 9000,
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [30, 30, 30, 140],
      lineWidthMinPixels: 0.5,
      opacity: 0.55,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 3. Aspect halo (gold, south-facing bias)
  if (active.solar_aspect) {
    layers.push(new ScatterplotLayer({
      id: "solar_aspect",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => [212, 160, 24, aspectAlpha(d.aspect_deg)],
      getRadius: 7000,
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.7,
      pickable: false,
    }));
  }

  // 4. Suitability composite
  if (active.solar_suitability !== false) {
    layers.push(new ScatterplotLayer({
      id: "solar_suitability",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => suitabilityColour(d.score),
      getRadius: (d) => 4000 + 6000 * (d.score || 0),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [20, 20, 20, 180],
      lineWidthMinPixels: 0.8,
      opacity: 0.85,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 5. REPD precedents
  if (active.solar_precedents !== false) {
    const precedents = solarFixture.repd_precedents || [];
    layers.push(new ScatterplotLayer({
      id: "solar_precedents",
      data: precedents,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => precedentColour(d.status),
      getRadius: (d) => 2500 + 15 * Math.sqrt(d.capacity_mw || 1),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [255, 248, 232, 230],
      lineWidthMinPixels: 1.2,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 6. AONB / Green Belt exclusion (red crosshatch — solid red at 25% opacity
  //    since deck.gl doesn't support true hatch without extension)
  if (active.solar_exclusions !== false) {
    const aonb = solarFixture.aonb_exclusions || [];
    layers.push(new PolygonLayer({
      id: "solar_exclusions",
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

export const SOLAR_PACK = {
  id: "solar",
  label: "Solar",
  accent: SOLAR_ACCENT,
  sublayers: SOLAR_SUBLAYERS,
  build: makeSolarLayers,
};

export default SOLAR_PACK;
