/**
 * OSM pylon lattice layer — renders `power=tower` nodes as 3D lattice
 * pylons using SimpleMeshLayer with a single shared procedural mesh
 * (see ../data/pylon_mesh.js).
 *
 * Data source: OpenStreetMap, © OpenStreetMap contributors, ODbL 1.0.
 * Attribution: "© OpenStreetMap contributors (ODbL)".
 *
 * Data delivery: the caller passes an array of tower features via
 * ctx.towers (preferred) — that way the existing Princeps OSM
 * ingester (utils/grid_data_ingester.py, Overpass adapter) stays the
 * single source of truth. If no data is supplied the layer renders
 * nothing and emits a console warning once.
 *
 * Feature shape:
 *   { id, lon, lat, voltage_kv, height_m?, ref? }
 *
 * Voltage colouring matches the rest of the Princeps twin palette
 * (matches GridTwin.jsx arc voltages).
 */

import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { getPylonMesh } from "../data/pylon_mesh.js";

// UK OHL voltage palette. Keys in kV.
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

// Typical UK pylon heights by voltage (m). Used when OSM is silent.
const HEIGHT_BY_VOLTAGE = {
  400: 50,
  275: 46,
  132: 27,
  66: 20,
  33: 15,
  11: 12,
};

function heightFor(t) {
  if (t.height_m && t.height_m > 0) return t.height_m;
  return HEIGHT_BY_VOLTAGE[t.voltage_kv] || 20;
}

let _warnedEmpty = false;

function makeOsmPylonLatticeLayer(ctx = {}) {
  const {
    towers = [],
    visible = true,
    voltageFilter = null, // array of kV to show, or null for all
    maxInstances = 5000,
    onHover,
    onClick,
  } = ctx;

  let source = towers;
  if (voltageFilter && voltageFilter.length) {
    const set = new Set(voltageFilter.map(Number));
    source = source.filter((t) => set.has(Number(t.voltage_kv)));
  }
  if (source.length > maxInstances) {
    // Deterministic decimation — keep high-voltage first, then tail of list.
    source = [...source].sort((a, b) => (b.voltage_kv || 0) - (a.voltage_kv || 0)).slice(0, maxInstances);
  }

  if (!source.length && !_warnedEmpty) {
    _warnedEmpty = true;
    // eslint-disable-next-line no-console
    console.warn("[twin/osm_pylon_lattice] no towers supplied — layer idle");
  }

  return new SimpleMeshLayer({
    id: "osm_pylon_lattice",
    data: source,
    visible,
    mesh: getPylonMesh(),
    getPosition: (t) => [t.lon, t.lat, 0],
    getColor: (t) => [...pickVoltageColour(t.voltage_kv), 235],
    getOrientation: (t) => [0, (t.bearing_deg || 0), 0],
    // Scale Y by actual tower height (mesh is normalised to 45 m nominal).
    getScale: (t) => {
      const h = heightFor(t) / 45;
      return [1, h, 1];
    },
    sizeScale: 1,
    pickable: true,
    onHover,
    onClick,
    parameters: { depthTest: true },
    _instanced: true,
    updateTriggers: {
      getColor: [voltageFilter && voltageFilter.join(",")],
    },
  });
}

export default {
  id: "osm_pylon_lattice",
  menuLabel: "OSM Pylons (lattice)",
  defaultVisible: true,
  attribution: "© OpenStreetMap contributors (ODbL 1.0)",
  licence: "ODbL 1.0",
  layerFactory: makeOsmPylonLatticeLayer,
  dataHook: null,
};
