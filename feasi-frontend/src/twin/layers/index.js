/**
 * Princeps Digital Twin — layer registry barrel.
 *
 * Each module exports a default registration descriptor:
 *   { id, menuLabel, defaultVisible, layerFactory(ctx), dataHook }
 *
 * The barrel exports a flat array. Consumers (GridTwin / ProjectTwinEmbed)
 * import this array, call `layerFactory(ctx)` per descriptor, and merge
 * the returned deck.gl layer into their scene composition.
 *
 * TODO(registry): if /docs/audits/twin_layer_registry_contract.md lands,
 *   reconcile field names (this uses the default shape described in the
 *   BOT-CC mission brief).
 *
 * Swarm bots: append your descriptor to TWIN_LAYERS below. Do not remove
 * or reorder other bots' entries.
 */

// BOT-CC substrate layers.
import osBuildings from "./os_buildings.js";
import eaLidarTerrain from "./ea_lidar_terrain.js";
import osmPylonLattice from "./osm_pylon_lattice.js";
import osmOhlCatenary from "./osm_ohl_catenary.js";

// BOT-DD / BOT-EE asset layers.
import assetsSolar from "./assets_solar.js";
import assetsBess from "./assets_bess.js";
import assetsDc from "./assets_dc.js";
import assetsWind from "./assets_wind.js";
import assetsEv from "./assets_ev.js";
import assetsHydrogen from "./assets_hydrogen.js";

export const TWIN_LAYERS = [
  eaLidarTerrain,   // bottom — sets elevation for everything above
  osBuildings,      // extruded on top of terrain
  osmOhlCatenary,   // OHL conductors (draw before pylons so pylons occlude)
  osmPylonLattice,  // pylon lattice meshes
  assetsSolar,      // REPD solar projects
  assetsBess,       // REPD BESS projects
  assetsDc,         // Data centres
  assetsWind,       // REPD wind (onshore + offshore via sub-option)
  assetsEv,         // EV charging hubs (empty until OSM ingest wired)
  assetsHydrogen,   // Hydrogen / electrolyser (gu_hydrogen + REPD other)
];

export function findTwinLayer(id) {
  return TWIN_LAYERS.find((l) => l.id === id) || null;
}

export default TWIN_LAYERS;
