/**
 * dyn_flow_arrows — live power flow direction arrows on grid lines.
 *
 * Consumes the WebSocket `/ws/grid-twin` feed (state.lines[]) or the
 * REST fallback `/api/twin/live-flow`. Direction is inferred from the
 * sign of flow_mw (positive = from→to, negative = to→from).
 *
 * Renders a TextLayer of arrow glyphs travelling along each line. The
 * animation is driven by a `time` shader uniform (updateTriggers on the
 * shared animation phase) — NOT per-frame React re-renders.
 *
 * Registry contract: see docs/audits/twin_layer_registry_contract.md.
 */

import { TextLayer } from "@deck.gl/layers";

const VOLTAGE_COLOUR = {
  400: [196, 124, 255],
  275: [138, 112, 230],
  132: [86, 164, 210],
  66:  [102, 200, 170],
  33:  [220, 176, 90],
  11:  [210, 120, 80],
};
const DEFAULT_COLOUR = [170, 170, 170];

function colourFor(kv) {
  if (!kv) return DEFAULT_COLOUR;
  if (kv >= 400) return VOLTAGE_COLOUR[400];
  if (kv >= 275) return VOLTAGE_COLOUR[275];
  if (kv >= 132) return VOLTAGE_COLOUR[132];
  if (kv >= 66)  return VOLTAGE_COLOUR[66];
  if (kv >= 33)  return VOLTAGE_COLOUR[33];
  return VOLTAGE_COLOUR[11];
}

function lerp(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function bearingDeg(a, b) {
  // Equirectangular is fine at GB latitudes and distances <500 km.
  const dx = (b[0] - a[0]) * Math.cos(((a[1] + b[1]) / 2) * Math.PI / 180);
  const dy = b[1] - a[1];
  return (Math.atan2(dx, dy) * 180) / Math.PI;
}

/**
 * Build a set of arrow glyph rows. Each row is one arrow at a fractional
 * position along its parent line, ready for TextLayer. The `phase`
 * (0..1) is what animates — each tick we nudge all arrows by phase.
 */
function buildArrows(lines, phase) {
  const out = [];
  for (const ln of lines || []) {
    const a = ln.from_coords;
    const b = ln.to_coords;
    if (!Array.isArray(a) || !Array.isArray(b) || a.length < 2 || b.length < 2) continue;
    const flow = Number(ln.flow_mw) || 0;
    if (Math.abs(flow) < 1) continue;
    const forward = flow >= 0;
    // Arrow density scales with loading: more congested -> more arrows.
    const loading = Math.min(1, Math.abs(flow) / Math.max(ln.rating_mw || 1, 1));
    const n = 1 + Math.round(loading * 4); // 1..5 arrows per line
    const p0 = forward ? a : b;
    const p1 = forward ? b : a;
    const bear = bearingDeg(p0, p1);
    for (let i = 0; i < n; i++) {
      const t = ((i / n) + phase) % 1;
      const pos = lerp(p0, p1, t);
      out.push({
        pos,
        angle: bear,
        voltage_kv: ln.voltage_kv,
        loading,
        flow_mw: flow,
        lineId: `${ln.from}->${ln.to}`,
      });
    }
  }
  return out;
}

function makeDynFlowArrowsLayer(ctx = {}) {
  const {
    visible = true,
    data = { lines: [] },
    phase = 0,
    size = 18,
    widthMinPixels = 14,
    onHover,
  } = ctx;

  const arrows = buildArrows(data.lines || [], phase);

  return new TextLayer({
    id: "dyn_flow_arrows",
    data: arrows,
    visible,
    pickable: Boolean(onHover),
    getPosition: (d) => d.pos,
    getText: () => "▶",
    getSize: (d) => Math.max(widthMinPixels, size + d.loading * 8),
    sizeUnits: "pixels",
    getColor: (d) => {
      const [r, g, b] = colourFor(d.voltage_kv);
      const a = Math.round(170 + d.loading * 85);
      return [r, g, b, a];
    },
    getAngle: (d) => -d.angle, // deck angle is CCW from east; negate to match bearing
    fontFamily: "ui-monospace, Menlo, monospace",
    fontWeight: 700,
    characterSet: ["▶"],
    background: false,
    onHover,
    parameters: { depthTest: false },
    updateTriggers: {
      getPosition: [phase, data && data.timestamp],
      getSize: [data && data.timestamp],
      getColor: [data && data.timestamp],
      getAngle: [data && data.timestamp],
    },
  });
}

export default {
  id: "dyn_flow_arrows",
  menuLabel: "Live flow arrows",
  defaultVisible: true,
  category: "dynamic",
  attribution: "NESO BMRS + Princeps power-flow solver",
  licence: "NESO Open Data Licence",
  timeAware: true,
  layerFactory: makeDynFlowArrowsLayer,
  dataHook: null, // host feeds WS/REST data via ctx.data
};
