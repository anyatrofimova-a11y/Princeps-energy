/**
 * Domain layer pack — EV CHARGING.
 *
 * Answers: "What does an EV charging hub need on the map?"
 *
 * Sub-layers:
 *   1. ev_chargers       — public + rapid + ultra-rapid chargepoint density
 *   2. ev_grid           — LV/HV headroom proxy (site-level)
 *   3. ev_traffic        — DfT AADF traffic flow
 *   4. ev_amenity        — shops/services within 1km (OSM)
 *   5. ev_motorway       — motorway / A-road corridor proximity
 *   6. ev_precedents     — EV Make-Ready + hub planning precedents
 *
 * Data: src/data/domain-fixtures/ev-chargepoint-density.json (MOCK).
 */

import { ScatterplotLayer, PolygonLayer } from "@deck.gl/layers";
import evFixture from "../../../data/domain-fixtures/ev-chargepoint-density.json";

export const EV_SUBLAYERS = [
  { id: "ev_chargers",    label: "Chargepoint density",    color: "#21918C", defaultOn: true  },
  { id: "ev_grid",        label: "LV/HV headroom",         color: "#D4A018", defaultOn: true  },
  { id: "ev_traffic",     label: "Traffic flow (AADF)",    color: "#F59E0B", defaultOn: true  },
  { id: "ev_amenity",     label: "Amenity density (1km)",  color: "#4285F4", defaultOn: false },
  { id: "ev_motorway",    label: "Motorway corridors",     color: "#9333EA", defaultOn: true  },
  { id: "ev_precedents",  label: "EV MR precedents",       color: "#24a148", defaultOn: true  },
];

export const EV_ACCENT = "#21918C"; // teal — aligns with siting-suitability wind pack for twin family

function viridis(t) {
  const t01 = Math.max(0, Math.min(1, t));
  if (t01 < 0.25) return [68, 1, 84];
  if (t01 < 0.40) return [59, 82, 139];
  if (t01 < 0.55) return [33, 145, 140];
  if (t01 < 0.75) return [94, 201, 98];
  return [253, 231, 37];
}

function chargerDensity(d) {
  // Composite (public + 2×rapid + 3×ultra) normalised 0-1
  return Math.min(1, (d.public + 2 * d.rapid + 3 * d.ultra) / 120);
}

function chargerColour(t) {
  return [...viridis(t), 210];
}

function aadfColour(aadf) {
  // 10k-62k range
  const t = (aadf - 10000) / (62000 - 10000);
  if (t < 0.25) return [94, 201, 98, 180];
  if (t < 0.50) return [253, 231, 37, 200];
  if (t < 0.75) return [245, 158, 11, 220];
  return [249, 115, 22, 230];
}

function headroomColour(mva) {
  // inverse — higher headroom = greener
  if (mva >= 9)  return [36, 161, 72, 220];
  if (mva >= 6)  return [212, 160, 24, 220];
  if (mva >= 4)  return [245, 158, 11, 220];
  return [220, 38, 38, 220];
}

function precedentColour(status) {
  if (status === "approved") return [36, 161, 72, 230];
  if (status === "refused")  return [220, 38, 38, 230];
  return [245, 158, 11, 230];
}

export function makeEvLayers({ active = {}, onHover, onClick } = {}) {
  const points = evFixture.points || [];
  const layers = [];

  // 5. Motorway corridors (draw first)
  if (active.ev_motorway !== false) {
    const motorways = evFixture.motorway_corridors || [];
    layers.push(new PolygonLayer({
      id: "ev_motorway",
      data: motorways,
      getPolygon: (d) => d.polygon,
      getFillColor: [147, 51, 234, 45],
      getLineColor: [147, 51, 234, 200],
      lineWidthMinPixels: 1.2,
      stroked: true,
      filled: true,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 1. Chargepoint density heatmap
  if (active.ev_chargers !== false) {
    layers.push(new ScatterplotLayer({
      id: "ev_chargers",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => chargerColour(chargerDensity(d)),
      getRadius: (d) => 5000 + 14000 * chargerDensity(d),
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.5,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 2. Grid headroom
  if (active.ev_grid !== false) {
    layers.push(new ScatterplotLayer({
      id: "ev_grid",
      data: points,
      getPosition: (d) => [d.lon + 0.02, d.lat - 0.02],
      getFillColor: (d) => headroomColour(d.hv_headroom_mva),
      getRadius: (d) => 2500 + 600 * (d.hv_headroom_mva || 0),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [20, 20, 20, 180],
      lineWidthMinPixels: 0.6,
      opacity: 0.75,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 3. Traffic flow AADF
  if (active.ev_traffic !== false) {
    layers.push(new ScatterplotLayer({
      id: "ev_traffic",
      data: points,
      getPosition: (d) => [d.lon - 0.02, d.lat + 0.02],
      getFillColor: (d) => aadfColour(d.aadf),
      getRadius: (d) => 2500 + 0.08 * (d.aadf || 0),
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.55,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 4. Amenity density
  if (active.ev_amenity) {
    layers.push(new ScatterplotLayer({
      id: "ev_amenity",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => [66, 133, 244, Math.min(220, 40 + 0.3 * (d.amenity_count || 0))],
      getRadius: (d) => 1800 + 10 * Math.sqrt(d.amenity_count || 0),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [66, 133, 244, 200],
      lineWidthMinPixels: 0.6,
      opacity: 0.6,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 6. EV precedents
  if (active.ev_precedents !== false) {
    const precedents = evFixture.ev_precedents || [];
    layers.push(new ScatterplotLayer({
      id: "ev_precedents",
      data: precedents,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => precedentColour(d.status),
      getRadius: (d) => 2000 + 150 * Math.sqrt(d.chargers || 1),
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

export const EV_PACK = {
  id: "ev",
  label: "EV Charging",
  accent: EV_ACCENT,
  sublayers: EV_SUBLAYERS,
  build: makeEvLayers,
};

export default EV_PACK;
