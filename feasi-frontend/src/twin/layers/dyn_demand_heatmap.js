/**
 * dyn_demand_heatmap — GSP polygons coloured by current utilisation %
 * (demand / firm_capacity).
 *
 * Data model (ctx.data):
 *   { gsps: [{ id, name, polygon: [[lon,lat],...] or GeoJSON ring,
 *              demand_mw, capacity_mw, utilisation }], timestamp }
 *
 * Refresh cadence: host should poll `/api/demand/summary` at most every
 * 30 minutes (BMRS settlement cadence). Time-aware — when the scrubber
 * sits in a past year the host should supply historical values; for
 * future years, pathway-projected values.
 *
 * Colour ramp: green (<0.6) → amber (0.6-0.8) → red (>0.8).
 * Registry contract: docs/audits/twin_layer_registry_contract.md.
 */

import { PolygonLayer } from "@deck.gl/layers";

function utilisationColour(u) {
  const util = Math.max(0, Math.min(1.2, Number(u) || 0));
  if (util >= 0.95) return [200, 28, 32];        // deep red
  if (util >= 0.80) return [245, 60, 45];        // red
  if (util >= 0.65) return [250, 140, 22];       // amber
  if (util >= 0.40) return [220, 200, 80];       // yellow
  if (util >= 0.20) return [140, 200, 80];       // pale green
  return [82, 196, 126];                         // green
}

/** Normalise a polygon entry — accept either `polygon` as [[lon,lat]...]
 *  (closed ring) OR GeoJSON-style coordinates wrapped one deeper. */
function normalisePolygon(g) {
  if (!g) return null;
  if (Array.isArray(g.polygon) && g.polygon.length >= 3) {
    // Accept [[lon,lat]...] or [[[lon,lat]...]] (with holes)
    const first = g.polygon[0];
    if (Array.isArray(first) && typeof first[0] === "number") return g.polygon;
    return g.polygon; // let deck.gl handle holes
  }
  if (g.geojson && g.geojson.coordinates) return g.geojson.coordinates;
  return null;
}

function makeDynDemandHeatmapLayer(ctx = {}) {
  const {
    visible = true,
    data = { gsps: [] },
    opacity = 0.55,
    extruded = false,
    showStroke = true,
    onHover,
    onClick,
  } = ctx;

  const rows = (data.gsps || []).map((g) => {
    const poly = normalisePolygon(g);
    if (!poly) return null;
    const util = (g.utilisation != null)
      ? Number(g.utilisation)
      : (Number(g.demand_mw) || 0) / Math.max(Number(g.capacity_mw) || 1, 1);
    return {
      id: g.id,
      name: g.name || g.gsp_name || g.id,
      polygon: poly,
      utilisation: util,
      demand_mw: Number(g.demand_mw) || null,
      capacity_mw: Number(g.capacity_mw) || null,
    };
  }).filter(Boolean);

  return new PolygonLayer({
    id: "dyn_demand_heatmap",
    data: rows,
    visible,
    pickable: Boolean(onHover || onClick),
    stroked: showStroke,
    filled: true,
    extruded,
    wireframe: false,
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => {
      const [r, g, b] = utilisationColour(d.utilisation);
      return [r, g, b, Math.round(opacity * 255)];
    },
    getLineColor: [40, 40, 40, 180],
    getElevation: (d) => (extruded ? Math.min(d.utilisation || 0, 1.2) * 6000 : 0),
    lineWidthMinPixels: 0.6,
    onHover,
    onClick,
    updateTriggers: {
      getFillColor: [data && data.timestamp, opacity],
      getElevation: [data && data.timestamp, extruded],
    },
  });
}

export default {
  id: "dyn_demand_heatmap",
  menuLabel: "GSP demand heatmap",
  defaultVisible: false,
  category: "dynamic",
  attribution: "NESO / DNO GSP polygons · demand via BMRS settlement",
  licence: "NESO Open Data Licence",
  timeAware: true,
  layerFactory: makeDynDemandHeatmapLayer,
  dataHook: null,
};
