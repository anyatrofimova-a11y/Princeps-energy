/**
 * SubstrateLayers — precision basemap layers powered by BOT-CC substrate.
 *
 * Produces deck.gl layers that render:
 *   - OS topography (buildings / roads / water / woodland) as MVT fills/lines
 *   - OSM pylons and overhead lines (ScatterplotLayer + PathLayer)
 *   - EA LiDAR 1 m DTM (TerrainLayer, lazy-loaded for the current viewport)
 *
 * Backed by:
 *   GET /api/substrate/tiles/{layer}/{z}/{x}/{y}.mvt
 *   GET /api/substrate/lidar/{tile_id}/dtm.tif
 *
 * The factory functions are pure — they read the active-layers map out of
 * SiteContext (passed via `layers`) and return a list of deck.gl layer
 * instances. The caller (e.g. MapView or DigitalTwin) appends them to the
 * deck overlay.
 */

import { MVTLayer, TerrainLayer } from "@deck.gl/geo-layers";
import { ScatterplotLayer, PathLayer } from "@deck.gl/layers";

// ---------------------------------------------------------------------------
// Palette — Princeps-friendly neutral tones. Buildings ivory, roads ink,
// water cool blue, woodland muted green.
// ---------------------------------------------------------------------------
const COLOURS = {
  building_fill:   [244, 238, 224, 220],   // ivory
  building_line:   [168, 156, 128, 180],
  road_fill:       [40, 38, 36, 220],      // ink
  road_minor_fill: [120, 112, 100, 200],
  water_fill:      [170, 198, 222, 210],   // cool blue
  water_line:      [96, 142, 184, 230],
  woodland_fill:   [168, 186, 148, 190],   // muted green
  pylon_fill:      [40, 40, 44, 230],
  line_400kv:      [212, 160, 24, 230],    // Princeps gold — top-tier
  line_275kv:      [195, 120, 24, 230],
  line_132kv:      [155, 80, 40, 230],
  line_33kv:       [100, 70, 55, 220],
  line_11kv:       [85, 85, 90, 220],
  line_default:    [90, 90, 95, 220],
};


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function tileUrl(layer) {
  return `/api/substrate/tiles/${layer}/{z}/{x}/{y}.mvt`;
}

function voltageColour(v) {
  if (!v || Number.isNaN(+v)) return COLOURS.line_default;
  const kv = +v;
  if (kv >= 380) return COLOURS.line_400kv;
  if (kv >= 220) return COLOURS.line_275kv;
  if (kv >= 110) return COLOURS.line_132kv;
  if (kv >= 30)  return COLOURS.line_33kv;
  if (kv >= 1)   return COLOURS.line_11kv;
  return COLOURS.line_default;
}

function voltageLineWidth(v) {
  if (!v || Number.isNaN(+v)) return 1.5;
  const kv = +v;
  if (kv >= 380) return 4;
  if (kv >= 220) return 3;
  if (kv >= 110) return 2.2;
  if (kv >= 30)  return 1.6;
  return 1.2;
}

function voltagePylonRadius(v) {
  if (!v || Number.isNaN(+v)) return 2;
  const kv = +v;
  if (kv >= 380) return 5;
  if (kv >= 220) return 4;
  if (kv >= 110) return 3;
  return 2;
}


// ---------------------------------------------------------------------------
// Individual layer factories (pure — deck.gl layer instances)
// ---------------------------------------------------------------------------

export function makeBuildingsLayer({ visible = true, opacity = 1 } = {}) {
  return new MVTLayer({
    id: "substrate_buildings",
    data: tileUrl("buildings"),
    minZoom: 12,
    maxZoom: 20,
    visible,
    opacity,
    pickable: true,
    stroked: true,
    filled: true,
    getFillColor: COLOURS.building_fill,
    getLineColor: COLOURS.building_line,
    lineWidthMinPixels: 0.4,
    extruded: false,
    binary: false,
  });
}

export function makeRoadsLayer({ visible = true, opacity = 1 } = {}) {
  return new MVTLayer({
    id: "substrate_roads",
    data: tileUrl("roads"),
    minZoom: 10,
    maxZoom: 20,
    visible,
    opacity,
    pickable: true,
    stroked: true,
    filled: false,
    getLineColor: (f) => {
      const cls = (f?.properties?.road_class || "").toLowerCase();
      if (cls === "motorway" || cls === "a_road") return COLOURS.road_fill;
      return COLOURS.road_minor_fill;
    },
    getLineWidth: (f) => {
      const cls = (f?.properties?.road_class || "").toLowerCase();
      if (cls === "motorway") return 6;
      if (cls === "a_road") return 4;
      if (cls === "b_road") return 2.5;
      return 1.2;
    },
    lineWidthMinPixels: 0.8,
    lineWidthUnits: "meters",
    binary: false,
  });
}

export function makeWaterLayer({ visible = true, opacity = 1 } = {}) {
  return new MVTLayer({
    id: "substrate_water",
    data: tileUrl("water"),
    minZoom: 8,
    maxZoom: 20,
    visible,
    opacity,
    pickable: false,
    stroked: true,
    filled: true,
    getFillColor: COLOURS.water_fill,
    getLineColor: COLOURS.water_line,
    lineWidthMinPixels: 0.5,
    binary: false,
  });
}

export function makeWoodlandLayer({ visible = true, opacity = 1 } = {}) {
  return new MVTLayer({
    id: "substrate_woodland",
    data: tileUrl("woodland"),
    minZoom: 10,
    maxZoom: 20,
    visible,
    opacity,
    pickable: false,
    stroked: false,
    filled: true,
    getFillColor: COLOURS.woodland_fill,
    binary: false,
  });
}

/**
 * Pylons — we serve the MVT first because it scales to any zoom, but we
 * also expose a ScatterplotLayer variant when the caller has a pre-loaded
 * GeoJSON handy (e.g. from site-prospector queries). The MVT path is the
 * default; ScatterplotLayer is only used when `pointFeatures` is provided.
 */
export function makePylonsLayer({
  visible = true,
  opacity = 1,
  pointFeatures = null,
} = {}) {
  if (pointFeatures && pointFeatures.length) {
    return new ScatterplotLayer({
      id: "substrate_pylons_points",
      data: pointFeatures,
      visible,
      opacity,
      pickable: true,
      stroked: false,
      filled: true,
      getPosition: (d) => d.geometry?.coordinates || [0, 0],
      getRadius: (d) => voltagePylonRadius(d.properties?.voltage_kv),
      getFillColor: COLOURS.pylon_fill,
      radiusUnits: "meters",
      radiusMinPixels: 2,
      radiusMaxPixels: 8,
    });
  }

  return new MVTLayer({
    id: "substrate_pylons",
    data: tileUrl("pylons"),
    minZoom: 11,
    maxZoom: 20,
    visible,
    opacity,
    pickable: true,
    stroked: false,
    filled: true,
    pointType: "circle",
    getPointRadius: (f) => voltagePylonRadius(f?.properties?.voltage_kv),
    getFillColor: COLOURS.pylon_fill,
    pointRadiusUnits: "meters",
    pointRadiusMinPixels: 2,
    pointRadiusMaxPixels: 8,
    binary: false,
  });
}

export function makeOverheadLinesLayer({
  visible = true,
  opacity = 1,
  lineFeatures = null,
} = {}) {
  if (lineFeatures && lineFeatures.length) {
    return new PathLayer({
      id: "substrate_overhead_lines_features",
      data: lineFeatures,
      visible,
      opacity,
      pickable: true,
      getPath: (d) => d.geometry?.coordinates || [],
      getColor: (d) => voltageColour(d.properties?.voltage_kv),
      getWidth: (d) => voltageLineWidth(d.properties?.voltage_kv),
      widthUnits: "meters",
      widthMinPixels: 1,
    });
  }

  return new MVTLayer({
    id: "substrate_overhead_lines",
    data: tileUrl("overhead_lines"),
    minZoom: 8,
    maxZoom: 20,
    visible,
    opacity,
    pickable: true,
    stroked: true,
    filled: false,
    getLineColor: (f) => voltageColour(f?.properties?.voltage_kv),
    getLineWidth: (f) => voltageLineWidth(f?.properties?.voltage_kv),
    lineWidthUnits: "meters",
    lineWidthMinPixels: 1,
    binary: false,
  });
}

/**
 * LiDAR TerrainLayer — lazy-loaded for the current viewport. The backend
 * exposes per-tile DTM GeoTIFFs at /api/substrate/lidar/{tile_id}/dtm.tif.
 * For a generic XYZ template we rely on an optional proxy env var
 * (VITE_SUBSTRATE_LIDAR_TILES) that rasterises the DTM to Mapbox-RGB
 * PNG tiles. Without that proxy this returns an inert no-op layer so
 * the frontend degrades gracefully.
 */
export function makeLidarTerrainLayer({
  visible = true,
  opacity = 1,
  tileUrl: override = null,
} = {}) {
  const envTileUrl =
    (typeof import.meta !== "undefined" && import.meta.env && import.meta.env.VITE_SUBSTRATE_LIDAR_TILES) ||
    override;

  if (!envTileUrl) {
    return new TerrainLayer({
      id: "substrate_lidar_disabled",
      data: [],
      visible: false,
    });
  }

  return new TerrainLayer({
    id: "substrate_lidar_dtm",
    elevationData: envTileUrl,
    texture: null,
    minZoom: 10,
    maxZoom: 16,
    visible,
    opacity,
    elevationDecoder: {
      rScaler: 256 * 0.1,
      gScaler: 0.1,
      bScaler: 0.1 / 256,
      offset: -10000,
    },
    color: [230, 224, 210],
    wireframe: false,
  });
}


// ---------------------------------------------------------------------------
// Convenience: build the full set from a ``layers`` toggle map
// ---------------------------------------------------------------------------
/**
 * Build substrate layers from SiteContext `layers` toggle map.
 *
 * Expected keys (matching LayerRail):
 *   substrateBuildings, substrateRoads, substrateWater, substrateWoodland,
 *   substratePylons, substrateOverheadLines, substrateLidar
 */
export function buildSubstrateLayers(layers = {}) {
  const out = [];
  if (layers.substrateWater)        out.push(makeWaterLayer());
  if (layers.substrateWoodland)     out.push(makeWoodlandLayer());
  if (layers.substrateRoads)        out.push(makeRoadsLayer());
  if (layers.substrateBuildings)    out.push(makeBuildingsLayer());
  if (layers.substratePylons)       out.push(makePylonsLayer());
  if (layers.substrateOverheadLines) out.push(makeOverheadLinesLayer());
  if (layers.substrateLidar)        out.push(makeLidarTerrainLayer());
  return out;
}

export default {
  makeBuildingsLayer,
  makeRoadsLayer,
  makeWaterLayer,
  makeWoodlandLayer,
  makePylonsLayer,
  makeOverheadLinesLayer,
  makeLidarTerrainLayer,
  buildSubstrateLayers,
};
