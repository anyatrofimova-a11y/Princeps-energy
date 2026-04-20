/**
 * Domain layer pack — BESS.
 *
 * Answers: "What does a battery project need to care about on the map?"
 *
 * Sub-layers:
 *   1. bess_revenue      — composite revenue stack £/kW/yr heatmap (BMRS + arb + FFR)
 *   2. bess_buffers      — 100m thermal / fire blast buffers from residential
 *   3. bess_comah        — HSE COMAH upper/lower tier flagged sites
 *   4. bess_curtailment  — curtailment-risk by zone (NESO constraint payments)
 *   5. bess_precedents   — BESS planning approvals/refusals/pendings
 *   6. bess_exclusions   — AONB / National Park crosshatch
 *
 * Data: src/data/domain-fixtures/bess-revenue-stack.json (MOCK per-zone).
 */

import { ScatterplotLayer, PolygonLayer, IconLayer } from "@deck.gl/layers";
import bessFixture from "../../../data/domain-fixtures/bess-revenue-stack.json";

export const BESS_SUBLAYERS = [
  { id: "bess_revenue",     label: "Revenue stack (£/kW/yr)",  color: "#21918C", defaultOn: true  },
  { id: "bess_buffers",     label: "Thermal / fire buffers",    color: "#DC2626", defaultOn: false },
  { id: "bess_comah",       label: "COMAH sites (HSE)",         color: "#F97316", defaultOn: false },
  { id: "bess_curtailment", label: "Curtailment risk",          color: "#9333EA", defaultOn: true  },
  { id: "bess_precedents",  label: "BESS precedents",           color: "#24a148", defaultOn: true  },
  { id: "bess_exclusions",  label: "AONB / National Park",      color: "#ef4444", defaultOn: true  },
];

export const BESS_ACCENT = "#9333EA"; // violet accent within Princeps palette

/* Viridis ramp for revenue 0-1 */
function viridis(t) {
  const t01 = Math.max(0, Math.min(1, t));
  if (t01 < 0.25) return [68, 1, 84];
  if (t01 < 0.40) return [59, 82, 139];
  if (t01 < 0.55) return [33, 145, 140];
  if (t01 < 0.75) return [94, 201, 98];
  return [253, 231, 37];
}

function revenueColour(total) {
  // range ~80-185 £/kW/yr in fixture
  const t = (total - 80) / (185 - 80);
  return [...viridis(t), 200];
}

function curtailmentColour(risk) {
  const t = Math.max(0, Math.min(1, risk));
  if (t < 0.25) return [82, 196, 126, 150];
  if (t < 0.50) return [253, 231, 37, 170];
  if (t < 0.75) return [245, 158, 11, 200];
  return [200, 28, 32, 220];
}

function precedentColour(status) {
  if (status === "approved") return [36, 161, 72, 220];
  if (status === "refused")  return [220, 38, 38, 220];
  return [245, 158, 11, 220];
}

export function makeBessLayers({ active = {}, onHover, onClick } = {}) {
  const zones = bessFixture.zones || [];
  const layers = [];

  // 1. Revenue stack heatmap
  if (active.bess_revenue !== false) {
    layers.push(new ScatterplotLayer({
      id: "bess_revenue",
      data: zones,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => revenueColour(d.total),
      getRadius: (d) => 10000 + 80 * (d.total || 0),
      radiusUnits: "meters",
      stroked: false,
      opacity: 0.5,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 2. 100m "blast radius" buffers — synthetic residential proxies
  //    (real version would query OS AddressBase residential parcels + NFPA 855)
  if (active.bess_buffers) {
    const buffers = zones.slice(0, 12).map((z) => ({
      ...z,
      // NB: 100m real BESS-to-residential — visualised as 1km ring for visibility at GB zoom
      radius_m: 1000,
    }));
    layers.push(new ScatterplotLayer({
      id: "bess_buffers",
      data: buffers,
      getPosition: (d) => [d.lon + 0.03, d.lat - 0.01],
      getFillColor: [220, 38, 38, 55],
      getLineColor: [200, 28, 32, 220],
      lineWidthMinPixels: 1.2,
      stroked: true,
      getRadius: (d) => d.radius_m,
      radiusUnits: "meters",
      pickable: false,
    }));
  }

  // 3. COMAH hazards — icons not available; use flagged scatter + outer halo
  if (active.bess_comah) {
    const sites = bessFixture.comah_sites || [];
    layers.push(new ScatterplotLayer({
      id: "bess_comah_halo",
      data: sites,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => d.tier === "upper" ? [249, 115, 22, 60] : [249, 115, 22, 40],
      getRadius: (d) => d.tier === "upper" ? 4000 : 2500,
      radiusUnits: "meters",
      stroked: false,
      pickable: false,
    }));
    layers.push(new ScatterplotLayer({
      id: "bess_comah",
      data: sites,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => d.tier === "upper" ? [220, 38, 38, 240] : [249, 115, 22, 230],
      getLineColor: [255, 248, 232, 240],
      lineWidthMinPixels: 1.5,
      stroked: true,
      getRadius: 1500,
      radiusUnits: "meters",
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 4. Curtailment risk (violet ramp)
  if (active.bess_curtailment !== false) {
    layers.push(new ScatterplotLayer({
      id: "bess_curtailment",
      data: zones,
      getPosition: (d) => [d.lon + 0.02, d.lat + 0.02],
      getFillColor: (d) => curtailmentColour(d.curtailment_risk),
      getRadius: (d) => 3500 + 8000 * (d.curtailment_risk || 0),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [147, 51, 234, 200],
      lineWidthMinPixels: 0.8,
      opacity: 0.75,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 5. BESS precedents
  if (active.bess_precedents !== false) {
    const precedents = bessFixture.bess_precedents || [];
    layers.push(new ScatterplotLayer({
      id: "bess_precedents",
      data: precedents,
      getPosition: (d) => [d.lon, d.lat],
      getFillColor: (d) => precedentColour(d.status),
      getRadius: (d) => 2500 + 10 * Math.sqrt(d.capacity_mw || 1),
      radiusUnits: "meters",
      stroked: true,
      getLineColor: [255, 248, 232, 230],
      lineWidthMinPixels: 1.2,
      pickable: !!(onHover || onClick),
      onHover,
      onClick,
    }));
  }

  // 6. AONB exclusion
  if (active.bess_exclusions !== false) {
    const aonb = bessFixture.aonb_exclusions || [];
    layers.push(new PolygonLayer({
      id: "bess_exclusions",
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

export const BESS_PACK = {
  id: "bess",
  label: "BESS",
  accent: BESS_ACCENT,
  sublayers: BESS_SUBLAYERS,
  build: makeBessLayers,
};

export default BESS_PACK;
