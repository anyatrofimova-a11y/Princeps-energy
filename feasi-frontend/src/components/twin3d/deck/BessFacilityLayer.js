/**
 * BessFacilityLayer.js — Deck.gl layer factory for a fully engineered
 * BESS facility produced by /api/twin/bess-design.
 *
 * Returns:
 *   - SimpleMeshLayer instances for every placed asset (containers, PCS,
 *     transformers, switchgear, control building, fire tanks, cabinets)
 *   - PathLayer for cable runs (colour by voltage class)
 *   - PolygonLayer for the perimeter fence keep-out
 *   - PathLayer for the access road
 *
 * The backend payload (design) carries metric offsets from a centroid
 * lon/lat. We project to lng/lat once per renderable item.
 */

import { PathLayer, PolygonLayer } from '@deck.gl/layers';
import { createAssetInstancedLayers } from './AssetInstancedLayer.js';
import { enuMetresToLngLat } from '../../../api/bessDesign.js';

// Map backend primitive_id → frontend registry assetType.
// All entries below were added to the registry seed; this map is here so
// any future renames stay isolated to one file.
const PRIMITIVE_TO_REGISTRY = {
  'bess.megapack_2xl': 'bess.megapack_2xl',
  'bess.catl_energy_tensor': 'bess.catl_energy_tensor',
  'bess.pcs_2mva_skid': 'bess.pcs_2mva_skid',
  'bess.auxiliary_transformer': 'bess.auxiliary_transformer',
  'bess.hv_transformer': 'bess.hv_transformer',
  'bess.gis_132kv_bay': 'bess.gis_132kv_bay',
  'bess.control_building': 'bess.control_building',
  'bess.fire_tank': 'bess.fire_tank',
  'bess.auxiliary_cabinet': 'bess.auxiliary_cabinet',
};

// Voltage → cable colour. RGB triplets (deck.gl expects 0..255).
function cableColour(voltageKv) {
  if (!Number.isFinite(voltageKv)) return [180, 180, 180];
  if (voltageKv >= 132) return [212, 162, 64];   // gold — HV
  if (voltageKv >= 33)  return [80, 140, 220];   // blue — MV
  if (voltageKv >= 1)   return [120, 180, 130];  // green — embedded MV
  return [200, 200, 205];                        // light grey — LV
}

function cableWidthPx(voltageKv) {
  if (voltageKv >= 132) return 3.5;
  if (voltageKv >= 33)  return 2.4;
  return 1.4;
}

/**
 * @param {Object} opts
 * @param {Object} opts.design        Payload from /api/twin/bess-design
 * @param {Array}  [opts.centroid]    [lng,lat] centre — overrides
 *                                    design.centroid_lonlat if provided
 * @param {Object} opts.registry      Result of getAssetRegistry()
 * @param {boolean} [opts.visible=true]
 * @param {boolean} [opts.pickable=true]
 * @param {boolean} [opts.showCables=true]
 * @param {boolean} [opts.showFence=true]
 * @param {boolean} [opts.showRoad=true]
 * @param {string|null} [opts.selectedAssetId]
 * @param {Function} [opts.onAssetClick]
 * @returns {Array} deck.gl layers
 */
export function createBessFacilityLayers(opts) {
  const {
    design,
    centroid: centroidOverride = null,
    registry,
    visible = true,
    pickable = true,
    showCables = true,
    showFence = true,
    showRoad = true,
    selectedAssetId = null,
    onAssetClick = null,
  } = opts || {};

  if (!design || !design.placed_assets) return [];

  const centroid =
    centroidOverride ||
    design.centroid_lonlat ||
    [-0.1276, 51.5074]; // London fallback — exists only when designer fails to project

  // ── 1. Placed assets via existing instanced-mesh layer factory ────────
  const assets = (design.placed_assets || [])
    .map((p, i) => {
      const assetType = PRIMITIVE_TO_REGISTRY[p.primitive_id] || p.primitive_id;
      const [eastM, northM, upM] = p.xyz || [0, 0, 0];
      const [lng, lat] = enuMetresToLngLat(centroid, eastM, northM);
      return {
        id: `${p.primitive_id}-${i}`,
        assetType,
        position: [lng, lat, upM || 0],
        rotation: p.rotation_deg || 0,
        scale: 1.0,
        meta: { ...(p.metadata || {}), role: p.role || '' },
      };
    });

  const meshLayers = visible
    ? createAssetInstancedLayers({
        assets,
        registry,
        visible: true,
        pickable,
        selectedAssetId,
        idPrefix: 'bess-facility',
        onClick: (payload) => {
          if (typeof onAssetClick === 'function') onAssetClick(payload);
        },
      })
    : [];

  const layers = [...meshLayers];

  // ── 2. Cable runs ─────────────────────────────────────────────────────
  if (showCables && Array.isArray(design.cable_runs) && design.cable_runs.length) {
    // group by voltage class so width / colour stays consistent per layer
    const cablePaths = design.cable_runs
      .filter((c) => Array.isArray(c.polyline_xy) && c.polyline_xy.length >= 2)
      .map((c, i) => ({
        id: `cable-${i}`,
        path: c.polyline_xy.map(([ex, ny]) => enuMetresToLngLat(centroid, ex, ny)),
        voltage: Number(c.voltage_kv) || 0,
        meta: c,
      }));
    layers.push(
      new PathLayer({
        id: 'bess-facility-cables',
        data: cablePaths,
        getPath: (d) => d.path,
        getColor: (d) => cableColour(d.voltage),
        getWidth: (d) => cableWidthPx(d.voltage),
        widthUnits: 'pixels',
        rounded: true,
        billboard: false,
        capRounded: true,
        jointRounded: true,
        opacity: 0.95,
        pickable: true,
      }),
    );
  }

  // ── 3. Perimeter fence as a hollow polygon ────────────────────────────
  if (showFence && Array.isArray(design.fence_polygon_xy) && design.fence_polygon_xy.length >= 3) {
    const ring = design.fence_polygon_xy.map(([ex, ny]) =>
      enuMetresToLngLat(centroid, ex, ny),
    );
    layers.push(
      new PolygonLayer({
        id: 'bess-facility-fence',
        data: [{ polygon: ring }],
        getPolygon: (d) => d.polygon,
        stroked: true,
        filled: true,
        getFillColor: [255, 195, 85, 18],
        getLineColor: [255, 195, 85, 200],
        lineWidthMinPixels: 2,
        getLineWidth: 0.6,
        pickable: false,
      }),
    );
  }

  // ── 4. Access road ────────────────────────────────────────────────────
  if (showRoad && Array.isArray(design.access_road_xy) && design.access_road_xy.length >= 2) {
    const road = design.access_road_xy.map(([ex, ny]) =>
      enuMetresToLngLat(centroid, ex, ny),
    );
    layers.push(
      new PathLayer({
        id: 'bess-facility-access-road',
        data: [{ path: road }],
        getPath: (d) => d.path,
        getColor: [120, 110, 95, 220],
        getWidth: 3.0,
        widthUnits: 'meters',
        widthMinPixels: 3,
        rounded: true,
        capRounded: true,
        pickable: false,
      }),
    );
  }

  return layers;
}

export default createBessFacilityLayers;
