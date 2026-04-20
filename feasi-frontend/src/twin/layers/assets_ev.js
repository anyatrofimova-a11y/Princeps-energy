/**
 * Twin layer plugin — EV charging hubs.
 *
 * Data source is not yet wired in the ingest pipeline: the backend
 * endpoint returns an empty FeatureCollection with an `available: false`
 * flag and a note. We render nothing in that state but surface a
 * human-readable badge via the plugin's `statusNote` so the layer menu
 * can show "not wired" next to the toggle.
 *
 * Once OSM amenity=charging_station is ingested, the backend will start
 * serving features; this layer's IconLayer will then automatically
 * populate without any frontend change needed.
 */

import { IconLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/ev";

async function fetchEv({ bbox, limit = 2000, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [], available: false };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`ev fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchEv({ bbox, signal });
}

function layerFactory(ctx = {}) {
  const {
    data,
    visible = true,
    onClick = () => {},
    pickable = true,
  } = ctx;

  if (!data || !data.features || data.features.length === 0) return null;

  return new IconLayer({
    id: "twin-assets-ev",
    data: data.features,
    visible,
    pickable,
    getIcon: () => iconDef("ev"),
    getPosition: f => f.geometry.coordinates,
    getSize: 28,
    sizeUnits: "pixels",
    getColor: f => statusColor(f.properties.status_bucket || "operational"),
    onClick,
    updateTriggers: {
      getColor: [data.features.length],
    },
  });
}

export default {
  id: "assets_ev",
  menuLabel: "EV charging hubs",
  defaultVisible: false,
  category: "load",
  icon: "ev",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  statusNote: data => {
    if (!data) return null;
    if (data.available === false) return "Not wired — ingest OSM charging_station";
    if ((data.features || []).length === 0) return "No charging hubs in view";
    return null;
  },
  legend: [
    { label: "Operational", bucket: "operational" },
  ],
};
