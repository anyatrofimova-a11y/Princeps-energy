/**
 * Princeps 3D Twin v1 — AssetInstancedLayer
 * ----------------------------------------------------------------------
 * Factory that turns a list of asset instances into one deck.gl
 * SimpleMeshLayer per asset-type, so that N identical containers cost
 * exactly one draw call each type. v2 will swap to ScenegraphLayer with
 * real glTF meshes under the same assets contract.
 *
 * Inputs:
 *   createAssetInstancedLayers({ assets, registry, visible, onClick, pickable })
 *     assets  : [{ id, assetType, position:[lng,lat,alt?], rotation?, scale?, colour? }]
 *     registry: result of getAssetRegistry() (see ../assets/registry.js)
 *
 * Returns:
 *   Array<SimpleMeshLayer> — one per unique asset-type, already wired
 *   with geometry + per-instance position/colour/size.
 *
 * Geometry selection: registry entry `fallback` drives the mesh
 *   'box'      -> three BoxGeometry(dims.l, dims.h, dims.w)
 *   'cylinder' -> three CylinderGeometry(dims.w/2, dims.w/2, dims.h)
 *
 * Coordinate convention: deck.gl expects positions in lng/lat for
 * geographic layers and metres for the Z channel. TwinRoot passes
 * positions already projected to lng/lat via turf; this layer only
 * handles the per-instance transform.
 */

import { SimpleMeshLayer } from '@deck.gl/mesh-layers';
import { COORDINATE_SYSTEM } from '@deck.gl/core';
import { BoxGeometry, CylinderGeometry } from 'three';

import { getAssetDef } from '../assets/registry.js';
import { hexToRgba } from '../assets/materials.js';

// ------------------------------------------------------------------
// Geometry cache — don't rebuild meshes every render
// ------------------------------------------------------------------

const GEOMETRY_CACHE = new Map();

function cacheKey(def) {
  return `${def.fallback || 'box'}:${def.dims.l}:${def.dims.w}:${def.dims.h}`;
}

function buildGeometry(def) {
  const key = cacheKey(def);
  if (GEOMETRY_CACHE.has(key)) return GEOMETRY_CACHE.get(key);
  const { l, w, h } = def.dims;
  let geom;
  if (def.fallback === 'cylinder') {
    // three's cylinder: (radiusTop, radiusBottom, height, radialSegments)
    geom = new CylinderGeometry(Math.min(l, w) / 2, Math.min(l, w) / 2, h, 24);
  } else {
    // three's box: (width, height, depth) — we map l->x, h->y (up), w->z
    geom = new BoxGeometry(l, h, w);
    // deck.gl SimpleMeshLayer treats +Z as up. three BoxGeometry has +Y up
    // by default. Rotate so the resulting mesh sits on the ground plane
    // with the asset "height" running along Z.
    geom.rotateX(Math.PI / 2);
  }
  GEOMETRY_CACHE.set(key, geom);
  return geom;
}

// ------------------------------------------------------------------
// Factory
// ------------------------------------------------------------------

/**
 * @param {Object} opts
 * @param {Array}  opts.assets    List of asset instances.
 * @param {Object} opts.registry  Result of getAssetRegistry().
 * @param {boolean} [opts.visible=true]
 * @param {Function} [opts.onClick] Receives {id, assetType, def, instance}.
 * @param {boolean}  [opts.pickable=true]
 * @param {string}   [opts.idPrefix='twin-assets'] Base layer id.
 * @param {number}   [opts.selectedAssetId] Highlight this asset id.
 * @returns {SimpleMeshLayer[]}
 */
export function createAssetInstancedLayers(opts) {
  const {
    assets = [],
    registry,
    visible = true,
    onClick,
    pickable = true,
    idPrefix = 'twin-assets',
    selectedAssetId = null,
  } = opts || {};

  if (!registry) {
    console.warn('[AssetInstancedLayer] no registry provided');
    return [];
  }
  if (!Array.isArray(assets) || assets.length === 0) return [];

  // group assets by registry def (id first, then type fallback)
  const groups = new Map();
  for (const inst of assets) {
    const def = getAssetDef(inst.assetType) || getAssetDef(inst.type);
    if (!def) continue;
    if (!groups.has(def.id)) groups.set(def.id, { def, instances: [] });
    groups.get(def.id).instances.push(inst);
  }

  const layers = [];
  for (const [defId, { def, instances }] of groups) {
    const geometry = buildGeometry(def);
    const defaultRgba = hexToRgba(def.colour_hex, 255);

    const layer = new SimpleMeshLayer({
      id: `${idPrefix}-${defId}`,
      data: instances,
      mesh: geometry,
      coordinateSystem: COORDINATE_SYSTEM.LNGLAT,
      visible,
      pickable,
      sizeScale: 1,
      // per-instance accessors
      getPosition: (d) => {
        const p = d.position || [0, 0, 0];
        return p.length >= 3 ? p : [p[0], p[1], 0];
      },
      getOrientation: (d) => {
        // deck.gl SimpleMeshLayer: [pitch-x, yaw-z, roll-y] degrees
        const yaw = Number(d.rotation || 0);
        return [0, yaw, 0];
      },
      getScale: (d) => {
        const s = d.scale;
        if (Array.isArray(s)) return s;
        if (typeof s === 'number' && Number.isFinite(s) && s > 0) return [s, s, s];
        return [1, 1, 1];
      },
      getColor: (d) => {
        const highlight =
          selectedAssetId && d.id && d.id === selectedAssetId ? 1 : 0;
        if (highlight) return [255, 210, 100, 255]; // gold highlight
        if (d.colour) return hexToRgba(d.colour, 255);
        return defaultRgba;
      },
      wireframe: false,
      material: {
        ambient: 0.35,
        diffuse: 0.75,
        shininess: 32,
        specularColor: [60, 60, 60],
      },
      onClick: (info) => {
        if (!onClick || !info || !info.object) return;
        onClick({
          id: info.object.id,
          assetType: info.object.assetType || def.id,
          def,
          instance: info.object,
          coordinate: info.coordinate,
          pickInfo: info,
        });
      },
      updateTriggers: {
        getColor: [selectedAssetId],
      },
    });
    layers.push(layer);
  }
  return layers;
}

export default createAssetInstancedLayers;
