/**
 * Cesium configuration and initialization.
 *
 * Provides Cesium Ion token setup, imagery providers (Cesium World Terrain,
 * Google Photorealistic 3D Tiles, NASA GIBS WMTS layers), and shared constants.
 */
import * as Cesium from "cesium";

/* ── Ion Token ─────────────────────────────────────────────────────────── */
const ION_TOKEN = import.meta.env.VITE_CESIUM_ION_TOKEN || "";
const GOOGLE_KEY = import.meta.env.VITE_GOOGLE_MAPS_KEY || "";

if (ION_TOKEN) {
  Cesium.Ion.defaultAccessToken = ION_TOKEN;
}

/* ── Terrain provider ──────────────────────────────────────────────────── */
export async function createWorldTerrain() {
  if (ION_TOKEN) {
    return await Cesium.CesiumTerrainProvider.fromIonAssetId(1, {
      requestVertexNormals: true,
      requestWaterMask: true,
    });
  }
  // Fallback: ellipsoid (flat)
  return new Cesium.EllipsoidTerrainProvider();
}

/* ── Google Photorealistic 3D Tiles ───────────────────────────────────── */
export function googlePhotorealistic3DTilesUrl() {
  if (!GOOGLE_KEY) return null;
  return `https://tile.googleapis.com/v1/3dtiles/root.json?key=${GOOGLE_KEY}`;
}

/* ── Cesium OSM Buildings (Ion asset 96188) ───────────────────────────── */
export async function createOSMBuildings() {
  if (!ION_TOKEN) return null;
  return await Cesium.createOsmBuildingsAsync();
}

/* ── NASA GIBS WMTS Layers ────────────────────────────────────────────── */
const GIBS_BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best";

/**
 * Available NASA GIBS imagery layers relevant to energy site assessment.
 * Each can be added as a Cesium ImageryLayer.
 */
export const GIBS_LAYERS = {
  modis_truecolor: {
    id: "MODIS_Terra_CorrectedReflectance_TrueColor",
    label: "MODIS True Color",
    format: "image/jpeg",
    tileMatrixSetID: "250m",
    maxLevel: 8,
    category: "imagery",
  },
  viirs_truecolor: {
    id: "VIIRS_SNPP_CorrectedReflectance_TrueColor",
    label: "VIIRS True Color",
    format: "image/jpeg",
    tileMatrixSetID: "250m",
    maxLevel: 8,
    category: "imagery",
  },
  viirs_nightlights: {
    id: "VIIRS_SNPP_DayNightBand_At_Sensor_Radiance",
    label: "Night Lights",
    format: "image/png",
    tileMatrixSetID: "500m",
    maxLevel: 8,
    category: "assessment",
  },
  landsat_truecolor: {
    id: "Landsat_WELD_CorrectedReflectance_TrueColor_Global_Annual",
    label: "Landsat Annual",
    format: "image/jpeg",
    tileMatrixSetID: "31.25m",
    maxLevel: 12,
    category: "imagery",
  },
  ndvi: {
    id: "MODIS_Terra_NDVI_8Day",
    label: "Vegetation (NDVI)",
    format: "image/png",
    tileMatrixSetID: "250m",
    maxLevel: 8,
    category: "assessment",
  },
  land_surface_temp: {
    id: "MODIS_Terra_Land_Surface_Temp_Day_8Day",
    label: "Land Surface Temp",
    format: "image/png",
    tileMatrixSetID: "1km",
    maxLevel: 7,
    category: "assessment",
  },
  snow_cover: {
    id: "MODIS_Terra_NDSI_Snow_Cover",
    label: "Snow Cover",
    format: "image/png",
    tileMatrixSetID: "500m",
    maxLevel: 8,
    category: "weather",
  },
  cloud_fraction: {
    id: "MODIS_Terra_Cloud_Fraction_Day",
    label: "Cloud Fraction",
    format: "image/png",
    tileMatrixSetID: "1km",
    maxLevel: 6,
    category: "weather",
  },
  fire_thermal: {
    id: "MODIS_Terra_Thermal_Anomalies_Day",
    label: "Fire / Thermal",
    format: "image/png",
    tileMatrixSetID: "1km",
    maxLevel: 7,
    category: "assessment",
  },
};

/**
 * Create a GIBS WMTS imagery provider for CesiumJS.
 */
export function createGIBSProvider(layerKey, date) {
  const layer = GIBS_LAYERS[layerKey];
  if (!layer) return null;

  const dateStr = date || new Date().toISOString().slice(0, 10);

  return new Cesium.WebMapTileServiceImageryProvider({
    url: `${GIBS_BASE}/${layer.id}/default/${dateStr}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.${layer.format === "image/jpeg" ? "jpg" : "png"}`,
    layer: layer.id,
    style: "default",
    tileMatrixSetID: layer.tileMatrixSetID,
    format: layer.format,
    maximumLevel: layer.maxLevel,
    credit: "NASA GIBS",
    tilingScheme: new Cesium.GeographicTilingScheme(),
  });
}

/* ── Voltage colour mapping (shared with GridTwin) ────────────────────── */
export const VOLTAGE_COLORS = {
  400: Cesium.Color.fromCssColorString("#ff3c3c"),
  275: Cesium.Color.fromCssColorString("#ffa500"),
  132: Cesium.Color.fromCssColorString("#1e88e5"),
  66: Cesium.Color.fromCssColorString("#4caf50"),
  33: Cesium.Color.fromCssColorString("#9c27b0"),
  11: Cesium.Color.fromCssColorString("#9e9e9e"),
};

export function voltageColorCesium(kv) {
  if (kv >= 400) return VOLTAGE_COLORS[400];
  if (kv >= 275) return VOLTAGE_COLORS[275];
  if (kv >= 132) return VOLTAGE_COLORS[132];
  if (kv >= 66) return VOLTAGE_COLORS[66];
  if (kv >= 33) return VOLTAGE_COLORS[33];
  return VOLTAGE_COLORS[11];
}

export function utilisationColorCesium(u) {
  if (u >= 0.9) return Cesium.Color.fromCssColorString("rgba(245,34,45,0.86)");
  if (u >= 0.7) return Cesium.Color.fromCssColorString("rgba(250,140,22,0.78)");
  return Cesium.Color.fromCssColorString("rgba(82,196,26,0.7)");
}

/* ── DEFRA LiDAR (Environment Agency) ─────────────────────────────────── */
export function createDEFRALidarHillshade() {
  return new Cesium.WebMapServiceImageryProvider({
    url: "https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wms",
    layers: "Lidar_Composite_Hillshade_DTM_1m",
    parameters: {
      format: "image/png",
      transparent: true,
    },
    credit: "Environment Agency DEFRA",
    maximumLevel: 20,
  });
}

export function createDEFRALidarElevation() {
  return new Cesium.WebMapServiceImageryProvider({
    url: "https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wms",
    layers: "Lidar_Composite_Elevation_DTM_1m",
    parameters: {
      format: "image/png",
      transparent: true,
    },
    credit: "Environment Agency DEFRA",
    maximumLevel: 20,
  });
}

/* ── Energy asset type styling ────────────────────────────────────────── */
export const ASSET_STYLES = {
  nuclear:         { color: "#e53935", icon: "N", scale: 1.4 },
  gas:             { color: "#ff8f00", icon: "G", scale: 1.2 },
  biomass:         { color: "#8d6e63", icon: "B", scale: 1.0 },
  wind:            { color: "#00b0ff", icon: "W", scale: 1.1 },
  solar:           { color: "#fdd835", icon: "S", scale: 1.0 },
  hydro:           { color: "#1565c0", icon: "H", scale: 1.0 },
  battery:         { color: "#7cb342", icon: "Bt", scale: 1.0 },
  interconnector:  { color: "#ab47bc", icon: "IC", scale: 1.1 },
  substation:      { color: "#78909c", icon: "Sb", scale: 0.8 },
};

/* ── UK default view ──────────────────────────────────────────────────── */
export const UK_CENTER = Cesium.Cartesian3.fromDegrees(-0.12, 51.5, 800000);
export const UK_ORIENTATION = {
  heading: Cesium.Math.toRadians(0),
  pitch: Cesium.Math.toRadians(-60),
  roll: 0,
};
