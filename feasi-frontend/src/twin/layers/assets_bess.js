/**
 * Twin layer plugin — BESS sites (REPD + user projects).
 *
 * Renders each BESS as a ColumnLayer cylinder whose height tracks MWh
 * (preferred) or MW * 2h fallback, and whose colour tracks status_bucket.
 * A thin IconLayer overlay places the battery glyph on top for readability
 * when zoomed out.
 */

import { ColumnLayer, IconLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/bess";
const MWH_TO_M = 0.4;   // 100 MWh => 40 m column; tweakable

async function fetchBess({ bbox, minMw = 0, limit = 2000, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&min_mw=${minMw}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`bess fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, minMw = 0, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchBess({ bbox, minMw, signal });
}

function elevationFor(props) {
  const mwh = props.battery_mwh;
  const mw = props.capacity_mw;
  if (mwh && mwh > 0) return Math.min(mwh * MWH_TO_M, 200);
  if (mw && mw > 0) return Math.min(mw * 2 * MWH_TO_M, 200);
  return 18;
}

function layerFactory(ctx = {}) {
  const {
    data,
    visible = true,
    onClick = () => {},
    pickable = true,
    radiusMeters = 60,
  } = ctx;

  if (!data || !data.features) return null;

  const column = new ColumnLayer({
    id: "twin-assets-bess-columns",
    data: data.features,
    visible,
    pickable,
    diskResolution: 12,
    radius: radiusMeters,
    extruded: true,
    getPosition: f => f.geometry.coordinates,
    getElevation: f => elevationFor(f.properties),
    getFillColor: f => statusColor(f.properties.status_bucket),
    getLineColor: [20, 20, 20, 200],
    elevationScale: 1,
    material: { ambient: 0.5, diffuse: 0.6, shininess: 20 },
    onClick,
    updateTriggers: {
      getElevation: [data.features.length],
      getFillColor: [data.features.length],
    },
  });

  const icons = new IconLayer({
    id: "twin-assets-bess-icons",
    data: data.features,
    visible,
    pickable: false,
    getIcon: () => iconDef("bess"),
    getPosition: f => {
      const c = f.geometry.coordinates;
      return [c[0], c[1], elevationFor(f.properties) + 4];
    },
    getSize: 28,
    sizeUnits: "pixels",
  });

  return [column, icons];
}

export default {
  id: "assets_bess",
  menuLabel: "Battery storage (BESS)",
  defaultVisible: true,
  category: "storage",
  icon: "bess",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  legend: [
    { label: "Operational",       bucket: "operational" },
    { label: "Under construction",bucket: "under_construction" },
    { label: "Consented",         bucket: "consented" },
    { label: "In planning",       bucket: "application_submitted" },
  ],
};
