/**
 * Twin layer plugin — Wind (onshore + offshore, selectable via sub-option).
 *
 * Renders each turbine/farm as an IconLayer glyph at 3D position
 * (hub-height from height_m when available). Offshore farms use a
 * distinct icon with a water-wave backdrop; the sub-option controls
 * which subset is fetched from the backend.
 */

import { IconLayer, ScatterplotLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip,
  capacityToPixelSize, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/wind";

async function fetchWind({ bbox, offshore = "all", minMw = 0, limit = 2500, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&offshore=${offshore}&min_mw=${minMw}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`wind fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, offshore = "all", minMw = 0, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchWind({ bbox, offshore, minMw, signal });
}

function hubHeightFor(props) {
  if (props.height_m && props.height_m > 0) return Math.min(props.height_m, 300);
  // Sensible defaults: offshore ~150 m, onshore ~90 m
  return props.is_offshore ? 150 : 90;
}

function layerFactory(ctx = {}) {
  const {
    data,
    visible = true,
    onClick = () => {},
    pickable = true,
    showHalo = true,
  } = ctx;

  if (!data || !data.features) return null;

  const layers = [];

  // Optional halo so large farms pop even when icons cluster
  if (showHalo) {
    layers.push(new ScatterplotLayer({
      id: "twin-assets-wind-halo",
      data: data.features,
      visible,
      pickable: false,
      getPosition: f => f.geometry.coordinates,
      getRadius: f => {
        const n = Math.max(1, f.properties.turbines || 1);
        return Math.min(200 + 40 * Math.sqrt(n), 1400);
      },
      radiusUnits: "meters",
      getFillColor: f => {
        const c = statusColor(f.properties.status_bucket);
        return [c[0], c[1], c[2], 30];
      },
      stroked: false,
    }));
  }

  layers.push(new IconLayer({
    id: "twin-assets-wind-icons",
    data: data.features,
    visible,
    pickable,
    getIcon: f => iconDef(f.properties.is_offshore ? "wind_offshore" : "wind_onshore"),
    getPosition: f => {
      const c = f.geometry.coordinates;
      return [c[0], c[1], hubHeightFor(f.properties)];
    },
    getSize: f => capacityToPixelSize(f.properties.capacity_mw, { min: 18, max: 54, cap: 400 }),
    sizeUnits: "pixels",
    getColor: f => statusColor(f.properties.status_bucket),
    onClick,
    updateTriggers: {
      getSize: [data.features.length],
      getColor: [data.features.length],
      getIcon: [data.features.length],
    },
  }));

  return layers;
}

export default {
  id: "assets_wind",
  menuLabel: "Wind (onshore + offshore)",
  defaultVisible: true,
  category: "generation",
  icon: "wind_onshore",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  subOptions: [
    { key: "offshore", label: "Scope",
      options: [
        { value: "all",      label: "All" },
        { value: "onshore",  label: "Onshore only" },
        { value: "offshore", label: "Offshore only" },
      ],
    },
  ],
  legend: [
    { label: "Operational",       bucket: "operational" },
    { label: "Under construction",bucket: "under_construction" },
    { label: "Consented",         bucket: "consented" },
    { label: "In planning",       bucket: "application_submitted" },
  ],
};
