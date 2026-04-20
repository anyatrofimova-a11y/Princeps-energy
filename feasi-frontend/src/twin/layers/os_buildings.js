/**
 * OS Buildings layer — UK building footprints extruded to their
 * approximate height.
 *
 * Data source: OS Open Zoomstack — "Building" layer, free under Open
 * Government Licence v3.0. Served as vector tiles via the OS Maps API
 * Open Zoomstack endpoint when an OS API key is available, otherwise
 * falls back to OpenMapTiles-compatible footprints if the caller
 * supplies an alternative `tileUrl` in opts.
 *
 * Licence attribution (must be shown in UI): "Contains OS data ©
 * Crown copyright and database rights {year} OS (OGL)."
 *
 * Env keys checked: VITE_OS_API_KEY (OS Data Hub), falls back to the
 * public demo tile server. No OS/Ordnance keys are currently set in
 * the repo .env — layer will operate in fallback mode until keys land.
 *
 * TODO(registry): migrate to COUNCIL-3 registry contract shape once
 *   /docs/audits/twin_layer_registry_contract.md lands.
 */

import { MVTLayer } from "@deck.gl/geo-layers";

const OS_KEY = (typeof import.meta !== "undefined" && import.meta.env)
  ? (import.meta.env.VITE_OS_API_KEY || import.meta.env.VITE_ORDNANCE_API_KEY || "")
  : "";

// OS Open Zoomstack Buildings (vector tiles, Open Government Licence).
// Endpoint form documented at https://osdatahub.os.uk/docs/wmts/
const DEFAULT_TILE_URL = OS_KEY
  ? `https://api.os.uk/maps/vector/v1/vts/tile/{z}/{y}/{x}.pbf?srs=3857&key=${OS_KEY}`
  : null;

// Minimum zoom where we start drawing (Zoomstack buildings appear from ~z13).
const MIN_ZOOM = 13;

function heightForZoom(zoom, props) {
  // OS Open Zoomstack exposes `height` (m) on building features when
  // using the 3D-enriched style; fall back to a per-importance default.
  if (props && typeof props.render_height === "number") return props.render_height;
  if (props && typeof props.height === "number") return props.height;
  if (zoom < 15) return 6; // low-zoom: everything looks uniformly tiny
  return 8;
}

function fillForProps(props) {
  // Slight tint per use class if Zoomstack sends it; neutral cool grey
  // otherwise (Princeps palette-friendly).
  const cls = props && (props.use || props.class);
  if (cls === "industrial") return [120, 110, 96, 230];
  if (cls === "retail") return [140, 120, 104, 230];
  return [168, 160, 148, 220];
}

function makeOsBuildingsLayer(ctx = {}) {
  const {
    tileUrl = DEFAULT_TILE_URL,
    visible = true,
    minZoom = MIN_ZOOM,
    opacity = 1,
    onError,
  } = ctx;

  if (!tileUrl) {
    // No API key and no override — return a disabled no-op layer so the
    // barrel stays stable and deck.gl does not throw.
    return new MVTLayer({
      id: "os_buildings_disabled",
      data: [],
      visible: false,
    });
  }

  return new MVTLayer({
    id: "os_buildings",
    data: tileUrl,
    minZoom,
    maxZoom: 20,
    visible,
    opacity,
    binary: false,
    // Only keep the building sub-layer from Zoomstack.
    loadOptions: { mvt: { layers: ["Building", "building"] } },
    getFillColor: (f) => fillForProps(f.properties),
    getLineColor: [60, 55, 48, 255],
    lineWidthMinPixels: 0.4,
    extruded: true,
    wireframe: false,
    getElevation: (f) => heightForZoom(f.tile ? f.tile.index.z : 15, f.properties),
    pickable: true,
    onTileError: onError,
    updateTriggers: {
      getElevation: [minZoom],
    },
  });
}

export default {
  id: "os_buildings",
  menuLabel: "OS Buildings",
  defaultVisible: true,
  attribution: "Contains OS data © Crown copyright and database rights (OGL v3.0)",
  licence: "Open Government Licence v3.0",
  layerFactory: makeOsBuildingsLayer,
  dataHook: null,
};
