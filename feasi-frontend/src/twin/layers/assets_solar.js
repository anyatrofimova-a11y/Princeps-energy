/**
 * Twin layer plugin — Solar farms from REPD.
 *
 * Renders one IconLayer for each solar project in the current viewport.
 * Icon size tracks installed capacity (sqrt scaling, capped at 500 MW);
 * colour tracks status_bucket server-side (operational / consented / etc.).
 *
 * Data is fetched lazily per-viewport via /api/twin/assets/solar and
 * cached by bbox+filters.
 */

import { IconLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip,
  capacityToPixelSize, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/solar";

async function fetchSolar({ bbox, minMw = 0, limit = 2000, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&min_mw=${minMw}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`solar fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, minMw = 0, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchSolar({ bbox, minMw, signal });
}

function layerFactory(ctx = {}) {
  const {
    data,                         // FeatureCollection from dataHook
    visible = true,
    onClick = () => {},
    pickable = true,
    capacityScale = { min: 14, max: 48, cap: 500 },
  } = ctx;

  if (!data || !data.features) return null;

  return new IconLayer({
    id: "twin-assets-solar",
    data: data.features,
    visible,
    pickable,
    getIcon: () => iconDef("solar"),
    getPosition: f => f.geometry.coordinates,
    getSize: f => capacityToPixelSize(f.properties.capacity_mw, capacityScale),
    sizeUnits: "pixels",
    getColor: f => statusColor(f.properties.status_bucket),
    onClick,
    updateTriggers: {
      getSize: [capacityScale.min, capacityScale.max, capacityScale.cap],
      getColor: [data.features.length],
    },
  });
}

export default {
  id: "assets_solar",
  menuLabel: "Solar farms (REPD)",
  defaultVisible: true,
  category: "generation",
  icon: "solar",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  legend: [
    { label: "Operational",       bucket: "operational" },
    { label: "Under construction",bucket: "under_construction" },
    { label: "Consented",         bucket: "consented" },
    { label: "In planning",       bucket: "application_submitted" },
    { label: "Refused",           bucket: "refused" },
  ],
};
