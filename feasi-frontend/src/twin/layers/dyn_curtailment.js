/**
 * dyn_curtailment — flashing red halos on currently-curtailed generators.
 *
 * Data model (ctx.data.assets):
 *   [{ id, lon, lat, capacity_mw, curtailed_mw, reason, boundary }]
 *
 * Source priority:
 *   1. BMRS Bid/Offer accepted (bid-level, per BMU). When available the
 *      host should pass curtailed_mw > 0 and reason="bmrs_bid".
 *   2. Fallback heuristic: if the asset sits behind a constrained boundary
 *      (e.g. B6 Scotland→England), flag it curtailed with reason="boundary".
 *
 * The flash is driven by a `phase` uniform so we animate on the GPU via
 * `updateTriggers` rather than re-rendering React every frame.
 *
 * Registry contract: docs/audits/twin_layer_registry_contract.md.
 */

import { ScatterplotLayer } from "@deck.gl/layers";

function flashAlpha(phase) {
  // sine in 0..1 -> two pulses per cycle
  return 110 + 125 * Math.max(0, Math.sin(phase * Math.PI * 4));
}

function haloRadius(baseM, phase) {
  return baseM * (1 + 0.35 * Math.max(0, Math.sin(phase * Math.PI * 4)));
}

function curtailmentFraction(a) {
  const cap = Number(a.capacity_mw) || 0;
  const curt = Number(a.curtailed_mw) || 0;
  if (cap <= 0) return 0;
  return Math.max(0, Math.min(1, curt / cap));
}

function filterCurtailed(assets) {
  return (assets || []).filter((a) => {
    if (!a || typeof a.lat !== "number" || typeof a.lon !== "number") return false;
    if (Number(a.curtailed_mw) > 0) return true;
    // Heuristic: asset marked behind constrained boundary
    if (a.reason === "boundary" || a.constraint === "behind_constrained_boundary") return true;
    if (a.curtailed === true) return true;
    return false;
  });
}

function makeDynCurtailmentLayer(ctx = {}) {
  const {
    visible = true,
    data = { assets: [] },
    phase = 0,
    baseRadiusM = 3500,
    onHover,
    onClick,
  } = ctx;

  const rows = filterCurtailed(data.assets);
  const alpha = flashAlpha(phase);

  // Two stacked layers: outer flashing halo + inner solid dot.
  const halo = new ScatterplotLayer({
    id: "dyn_curtailment_halo",
    data: rows,
    visible,
    pickable: Boolean(onHover || onClick),
    getPosition: (d) => [d.lon, d.lat],
    getRadius: (d) => haloRadius(baseRadiusM * (0.6 + 0.4 * curtailmentFraction(d)), phase),
    radiusUnits: "meters",
    radiusMinPixels: 10,
    radiusMaxPixels: 60,
    getFillColor: [245, 34, 45, Math.round(alpha * 0.55)],
    getLineColor: [245, 34, 45, 230],
    lineWidthMinPixels: 1.2,
    stroked: true,
    filled: true,
    onHover,
    onClick,
    parameters: { depthTest: false },
    updateTriggers: {
      getRadius: [phase, data && data.timestamp],
      getFillColor: [phase],
    },
  });

  const core = new ScatterplotLayer({
    id: "dyn_curtailment_core",
    data: rows,
    visible,
    pickable: false,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: baseRadiusM * 0.3,
    radiusUnits: "meters",
    radiusMinPixels: 4,
    radiusMaxPixels: 12,
    getFillColor: [255, 120, 110, 240],
    stroked: false,
    filled: true,
    parameters: { depthTest: false },
  });

  return [halo, core];
}

export default {
  id: "dyn_curtailment",
  menuLabel: "Curtailment (live)",
  defaultVisible: false,
  category: "dynamic",
  attribution: "Derived from NESO BMRS Bid/Offer + boundary constraints",
  licence: "NESO Open Data Licence",
  timeAware: true,
  layerFactory: makeDynCurtailmentLayer,
  dataHook: null,
};
