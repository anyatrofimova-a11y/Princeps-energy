/**
 * OSM overhead line (OHL) catenary layer — draws `power=line` ways as
 * catenary-sagged conductor polylines between consecutive pylon nodes
 * rather than straight line segments.
 *
 * Data source: OpenStreetMap, © OpenStreetMap contributors, ODbL 1.0.
 *
 * Input shape (ctx.lines):
 *   [{ id, voltage_kv, towers: [[lon,lat], [lon,lat], ...], attach_height_m? }]
 *
 * Each tower coordinate is the pylon XY position; per-span catenary
 * sag is computed in utils/catenary.js. For multi-circuit OHL we draw
 * one path per circuit (upstream data should split circuits).
 */

import { PathLayer } from "@deck.gl/layers";
import { buildOHLSpans } from "../utils/catenary.js";

const VOLTAGE_COLOUR = {
  400: [196, 124, 255],
  275: [138, 112, 230],
  132: [86, 164, 210],
  66: [102, 200, 170],
  33: [220, 176, 90],
  11: [210, 120, 80],
};
const DEFAULT_COLOUR = [170, 170, 170];

function pickVoltageColour(v) {
  if (!v) return DEFAULT_COLOUR;
  let best = 11;
  for (const k of Object.keys(VOLTAGE_COLOUR)) {
    const kv = Number(k);
    if (v >= kv && kv >= best) best = kv;
  }
  return VOLTAGE_COLOUR[best] || DEFAULT_COLOUR;
}

const ATTACH_BY_VOLTAGE = {
  400: 45,
  275: 41,
  132: 23,
  66: 17,
  33: 13,
  11: 10,
};

function explode(lines, opts) {
  const out = [];
  for (const ln of lines || []) {
    const towers = ln.towers || [];
    if (towers.length < 2) continue;
    const attach = ln.attach_height_m || ATTACH_BY_VOLTAGE[ln.voltage_kv] || 15;
    const spans = buildOHLSpans(towers, {
      attachHeight: attach,
      sagRatio: opts.sagRatio,
      samples: opts.samples,
    });
    for (const s of spans) {
      out.push({
        lineId: ln.id,
        voltage_kv: ln.voltage_kv,
        path: s.path,
        spanIndex: s.index,
      });
    }
  }
  return out;
}

function makeOsmOhlCatenaryLayer(ctx = {}) {
  const {
    lines = [],
    visible = true,
    sagRatio = 0.025,
    samples = 14,
    voltageFilter = null,
    onHover,
    onClick,
    widthMinPixels = 1.2,
  } = ctx;

  let source = lines;
  if (voltageFilter && voltageFilter.length) {
    const set = new Set(voltageFilter.map(Number));
    source = source.filter((l) => set.has(Number(l.voltage_kv)));
  }

  const spans = explode(source, { sagRatio, samples });

  return new PathLayer({
    id: "osm_ohl_catenary",
    data: spans,
    visible,
    pickable: true,
    widthUnits: "pixels",
    widthMinPixels,
    getWidth: (d) => (d.voltage_kv >= 275 ? 2.2 : d.voltage_kv >= 132 ? 1.8 : 1.3),
    getColor: (d) => [...pickVoltageColour(d.voltage_kv), 225],
    getPath: (d) => d.path,
    capRounded: true,
    jointRounded: true,
    billboard: false,
    onHover,
    onClick,
    parameters: { depthTest: true },
    updateTriggers: {
      getPath: [sagRatio, samples],
      getColor: [voltageFilter && voltageFilter.join(",")],
    },
  });
}

export default {
  id: "osm_ohl_catenary",
  menuLabel: "OSM OHL (catenary)",
  defaultVisible: true,
  attribution: "© OpenStreetMap contributors (ODbL 1.0)",
  licence: "ODbL 1.0",
  layerFactory: makeOsmOhlCatenaryLayer,
  dataHook: null,
};
