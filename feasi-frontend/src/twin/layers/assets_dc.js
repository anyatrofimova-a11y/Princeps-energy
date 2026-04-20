/**
 * Twin layer plugin — Data centres.
 *
 * Renders a squared ColumnLayer footprint extruded by IT_load_mw (or a
 * default 30 m for OSM reference points with no MW estimate). Colour
 * encodes PUE target when available, otherwise falls back to status bucket.
 */

import { ColumnLayer, IconLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/dc";

async function fetchDc({ bbox, limit = 1000, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`dc fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchDc({ bbox, signal });
}

function elevationFor(props) {
  const mw = props.it_load_mw || props.capacity_mw;
  if (mw && mw > 0) return Math.max(20, Math.min(mw * 1.2, 300));
  return 30;
}

// PUE → colour (lower is better; green <= 1.25, amber 1.25-1.45, red > 1.45)
function pueColor(pue) {
  if (pue == null) return null;
  if (pue <= 1.25) return [76, 175, 80, 220];
  if (pue <= 1.45) return [255, 165, 0, 220];
  return [198, 40, 40, 220];
}

function layerFactory(ctx = {}) {
  const {
    data,
    visible = true,
    onClick = () => {},
    pickable = true,
    colorBy = "status",   // "status" or "pue"
    radiusMeters = 90,
  } = ctx;

  if (!data || !data.features) return null;

  const column = new ColumnLayer({
    id: "twin-assets-dc-columns",
    data: data.features,
    visible,
    pickable,
    diskResolution: 4,        // square footprint
    radius: radiusMeters,
    angle: 45,
    extruded: true,
    getPosition: f => f.geometry.coordinates,
    getElevation: f => elevationFor(f.properties),
    getFillColor: f => {
      if (colorBy === "pue") {
        const c = pueColor(f.properties.pue);
        if (c) return c;
      }
      return statusColor(f.properties.status_bucket);
    },
    getLineColor: [10, 10, 10, 220],
    material: { ambient: 0.45, diffuse: 0.6, shininess: 30 },
    onClick,
    updateTriggers: {
      getElevation: [data.features.length, colorBy],
      getFillColor: [data.features.length, colorBy],
    },
  });

  const icons = new IconLayer({
    id: "twin-assets-dc-icons",
    data: data.features,
    visible,
    pickable: false,
    getIcon: () => iconDef("dc"),
    getPosition: f => {
      const c = f.geometry.coordinates;
      return [c[0], c[1], elevationFor(f.properties) + 6];
    },
    getSize: 30,
    sizeUnits: "pixels",
  });

  return [column, icons];
}

export default {
  id: "assets_dc",
  menuLabel: "Data centres",
  defaultVisible: true,
  category: "load",
  icon: "dc",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  legend: [
    { label: "PUE ≤ 1.25 (best)", color: [76, 175, 80, 220] },
    { label: "PUE 1.25–1.45",     color: [255, 165, 0, 220] },
    { label: "PUE > 1.45",        color: [198, 40, 40, 220] },
    { label: "Status fallback",   bucket: "operational" },
  ],
};
