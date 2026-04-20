/**
 * EA 1 m LiDAR Composite DTM terrain layer.
 *
 * Data source: Environment Agency — "LIDAR Composite Digital Terrain
 * Model (DTM) — 1 m" (latest 2022 revision).
 *   https://environment.data.gov.uk/dataset/LIDAR-Composite-DTM-2022-1m
 *
 * Licence: Open Government Licence v3.0.
 * Attribution: "Contains public sector information licensed under the
 * Open Government Licence v3.0 — Environment Agency LIDAR Composite
 * DTM (2022)."
 *
 * Tile source: the EA publishes the composite as an ArcGIS Image
 * Service. deck.gl's TerrainLayer expects elevation as a URL template
 * returning an image whose RGB channels encode height. Mapbox-RGB
 * style encoding is the simplest interop — the EA service exposes a
 * "ExportImage" endpoint but not a pre-computed RGB tile pyramid, so
 * by default we go through a thin Princeps backend proxy at
 * /api/twin/ea-lidar/{z}/{x}/{y}.png that handles RGB encoding and
 * OGL attribution headers. The proxy endpoint is optional — if the
 * environment variable VITE_EA_LIDAR_URL is set to a direct RGB-PNG
 * template it is used verbatim.
 *
 * See app/routers/twin_tiles.py for the default proxy implementation
 * (only needed because ArcGIS ExportImage returns JPEG/PNG with raw
 * elevation bytes, not Mapbox-RGB).
 */

import { TerrainLayer } from "@deck.gl/geo-layers";

const ENV = (typeof import.meta !== "undefined" && import.meta.env) || {};
const DIRECT_URL = ENV.VITE_EA_LIDAR_URL || "";
const PROXY_URL = ENV.VITE_EA_LIDAR_PROXY || "/api/twin/ea-lidar/{z}/{x}/{y}.png";

// Mapbox-RGB elevation decoder: height = -10000 + (R*65536 + G*256 + B) * 0.1.
// This matches the default TerrainLayer ELEVATION_DECODER.
const MAPBOX_DECODER = {
  rScaler: 256 * 0.1,
  gScaler: 0.1,
  bScaler: 0.1 / 256,
  offset: -10000,
};

// UK-only bounds — clip terrain tile requests to GB extent so we never
// pound the EA endpoint asking for e.g. mid-Atlantic tiles.
const UK_BBOX = [-8.8, 49.8, 2.0, 61.0]; // lon/lat approx

function makeEaLidarLayer(ctx = {}) {
  const {
    tileUrl = DIRECT_URL || PROXY_URL,
    visible = true,
    minZoom = 8,
    maxZoom = 15,
    meshMaxError = 6,
    opacity = 1,
    color = [230, 224, 210],
    onError,
  } = ctx;

  return new TerrainLayer({
    id: "ea_lidar_terrain",
    visible,
    minZoom,
    maxZoom,
    strategy: "no-overlap",
    elevationDecoder: MAPBOX_DECODER,
    elevationData: tileUrl,
    texture: null, // let the map basemap show through; terrain only shapes geometry
    meshMaxError,
    bounds: UK_BBOX,
    color,
    opacity,
    loadOptions: {
      image: { type: "data" },
    },
    onTileError: onError,
    // Ensure deck.gl draws terrain below extruded buildings (depth buffer
    // already handles this, but making it explicit avoids z-fighting on
    // flat fen terrain where footprints are sub-metre thick).
    material: {
      ambient: 0.5,
      diffuse: 0.6,
      shininess: 6,
      specularColor: [40, 40, 40],
    },
  });
}

export default {
  id: "ea_lidar_terrain",
  menuLabel: "EA LiDAR DTM (1 m)",
  defaultVisible: true,
  attribution:
    "Contains public sector information licensed under the Open Government Licence v3.0 — EA LIDAR Composite DTM (2022)",
  licence: "Open Government Licence v3.0",
  layerFactory: makeEaLidarLayer,
  dataHook: null,
};
