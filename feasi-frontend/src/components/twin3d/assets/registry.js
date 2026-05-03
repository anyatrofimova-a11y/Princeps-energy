/**
 * Princeps 3D Twin v1 — Asset registry
 * ----------------------------------------------------------------------
 * Canonical catalogue of parametric asset primitives rendered by the
 * deck.gl AssetInstancedLayer. v1 ships box/cylinder fallbacks; sibling
 * agents will extend with glTF/GLB models later without breaking the
 * `{id, type, dims, material, colour_hex, fallback, parametric_rule,
 * standards}` contract.
 *
 * Units: metres. Colour: HTML hex string. Materials are keys into
 * `materials.js`.
 *
 * If `app/data/asset_catalogue.json` is shipped to the frontend (e.g.
 * via /api/assets/catalogue) at runtime, use `hydrateRegistry(data)` to
 * merge overrides. Until then we ship the seed below.
 */

// 12-primitive seed covering BESS, Solar, and Data Centre
export const ASSET_SEED = [
  // ---------------- BESS ----------------
  {
    id: 'bess.tesla_megapack_2xl',
    type: 'bess_container',
    dims: { l: 8.8, w: 1.8, h: 2.9 }, // Tesla Megapack 2XL 3.9 MWh
    material: 'painted_metal_grey',
    colour_hex: '#2f3540',
    fallback: 'box',
    parametric_rule: 'energy_mwh_per_unit=3.9;power_mw_per_unit=1.9',
    standards: ['IEC 62933', 'NFPA 855', 'UK FRS G59'],
  },
  {
    id: 'bess.fluence_gridstack',
    type: 'bess_container',
    dims: { l: 6.1, w: 2.44, h: 2.9 }, // 20ft Fluence Gridstack
    material: 'painted_metal_grey',
    colour_hex: '#3a4150',
    fallback: 'box',
    parametric_rule: 'energy_mwh_per_unit=0.72;power_mw_per_unit=0.36',
    standards: ['IEC 62933', 'UL 9540', 'NFPA 855'],
  },
  {
    id: 'bess.wartsila_quantum',
    type: 'bess_container',
    dims: { l: 6.6, w: 2.4, h: 2.9 }, // Wärtsilä Quantum (approx)
    material: 'painted_metal_grey',
    colour_hex: '#2b3040',
    fallback: 'box',
    parametric_rule: 'energy_mwh_per_unit=5.3;power_mw_per_unit=2.65',
    standards: ['IEC 62933', 'NFPA 855'],
  },
  {
    id: 'bess.pcs_skid',
    type: 'bess_pcs',
    dims: { l: 3.0, w: 1.2, h: 2.2 }, // inverter / PCS skid
    material: 'painted_metal_grey',
    colour_hex: '#4a5260',
    fallback: 'box',
    parametric_rule: 'power_mw_per_unit=2.5',
    standards: ['G99', 'IEC 62109'],
    glb_path: '/assets/twin3d/bess/pcs_skid.glb',
  },
  {
    id: 'bess.aux_tx',
    type: 'transformer',
    dims: { l: 2.6, w: 2.0, h: 2.8 }, // auxiliary pad-mount transformer
    material: 'substation_white',
    colour_hex: '#e3e6eb',
    fallback: 'box',
    parametric_rule: 'rating_mva_per_unit=3.15',
    standards: ['IEC 60076', 'ENA TS 35-1'],
  },

  // ---- Backend-canonical IDs (utils/bess_engineering.py) ----
  {
    id: 'bess.megapack_2xl',
    type: 'bess_container',
    dims: { l: 8.99, w: 1.66, h: 2.89 },
    material: 'painted_metal_grey',
    colour_hex: '#2d3340',
    fallback: 'box',
    parametric_rule: 'energy_mwh_per_unit=3.916;power_mw_per_unit=1.927',
    standards: ['IEC 62933-5-2', 'NFPA 855', 'BS 8629', 'IFC 1207'],
    glb_path: '/assets/twin3d/bess/megapack_2xl.glb',
  },
  {
    id: 'bess.catl_energy_tensor',
    type: 'bess_container',
    dims: { l: 6.10, w: 2.44, h: 2.90 },
    material: 'painted_metal_grey',
    colour_hex: '#363c4d',
    fallback: 'box',
    parametric_rule: 'energy_mwh_per_unit=6.25;power_mw_per_unit=3.125',
    standards: ['IEC 62933-5-2', 'NFPA 855', 'UL 9540'],
    glb_path: '/assets/twin3d/bess/container_generic.glb',
  },
  {
    id: 'bess.pcs_2mva_skid',
    type: 'bess_pcs',
    dims: { l: 6.10, w: 2.44, h: 2.75 },
    material: 'painted_metal_grey',
    colour_hex: '#3f4654',
    fallback: 'box',
    parametric_rule: 'rating_kva_per_unit=2200',
    standards: ['G99', 'IEC 62109'],
    glb_path: '/assets/twin3d/bess/pcs_skid.glb',
  },
  {
    id: 'bess.auxiliary_transformer',
    type: 'transformer',
    dims: { l: 5.50, w: 2.20, h: 2.40 }, // LV-MV pad-mount 4.4 MVA 0.69/33 kV
    material: 'substation_white',
    colour_hex: '#dee2eb',
    fallback: 'box',
    parametric_rule: 'rating_mva_per_unit=4.4',
    standards: ['IEC 60076', 'ENA TS 35-1'],
    glb_path: '/assets/twin3d/bess/aux_tx.glb',
  },
  {
    id: 'bess.hv_transformer',
    type: 'transformer',
    dims: { l: 7.50, w: 4.50, h: 5.20 }, // Main 60 MVA 33/132 kV ONAF
    material: 'substation_white',
    colour_hex: '#cfd5e0',
    fallback: 'box',
    parametric_rule: 'rating_mva_per_unit=60',
    standards: ['IEC 60076-7', 'ENA TS 35-1'],
  },
  {
    id: 'bess.gis_132kv_bay',
    type: 'switchgear',
    dims: { l: 8.0, w: 3.5, h: 4.5 },
    material: 'galvanised_steel',
    colour_hex: '#a7adb8',
    fallback: 'box',
    parametric_rule: 'voltage_kv_per_unit=132',
    standards: ['IEC 62271', 'ENA EREC G99'],
  },
  {
    id: 'bess.control_building',
    type: 'building',
    dims: { l: 12.0, w: 6.0, h: 3.5 },
    material: 'concrete_pad',
    colour_hex: '#dad6cf',
    fallback: 'box',
    parametric_rule: 'standard_size',
    standards: ['BS EN 1991-1-1'],
  },
  {
    id: 'bess.fire_tank',
    type: 'fire_water',
    dims: { l: 4.5, w: 4.5, h: 3.0 },
    material: 'painted_metal_grey',
    colour_hex: '#7a3f3a',
    fallback: 'cylinder',
    parametric_rule: 'capacity_m3_per_unit=50',
    standards: ['BS 8629', 'BS EN 13565-1'],
  },
  {
    id: 'bess.auxiliary_cabinet',
    type: 'cabinet',
    dims: { l: 2.0, w: 1.0, h: 2.2 },
    material: 'painted_metal_grey',
    colour_hex: '#4d5260',
    fallback: 'box',
    parametric_rule: 'standard_size',
    standards: ['IEC 61439'],
  },

  // ---------------- Solar ----------------
  {
    id: 'solar.pv_table_4h',
    type: 'pv_table',
    dims: { l: 12.0, w: 4.0, h: 2.2 }, // fixed-tilt 4-high portrait table
    material: 'pv_blue',
    colour_hex: '#1a2a5c',
    fallback: 'box',
    parametric_rule: 'capacity_kwp_per_unit=23;row_spacing_m=6',
    standards: ['IEC 61215', 'IEC 61730'],
  },
  {
    id: 'solar.central_inverter_3mva',
    type: 'inverter',
    dims: { l: 3.5, w: 1.5, h: 2.4 },
    material: 'galvanised_steel',
    colour_hex: '#9fa4ad',
    fallback: 'box',
    parametric_rule: 'ac_rating_mva_per_unit=3.0;coverage_mwdc=3.6',
    standards: ['G99', 'IEC 62109', 'IEC 61683'],
    glb_path: '/assets/twin3d/solar/inverter.glb',
  },
  {
    id: 'solar.pad_tx',
    type: 'transformer',
    dims: { l: 3.2, w: 2.4, h: 2.6 }, // pad-mount MV transformer
    material: 'substation_white',
    colour_hex: '#dfe2e8',
    fallback: 'box',
    parametric_rule: 'rating_mva_per_unit=3.15',
    standards: ['IEC 60076'],
  },

  // ---------------- Data Centre ----------------
  {
    id: 'dc.it_hall_shell',
    type: 'dc_shell',
    dims: { l: 100.0, w: 60.0, h: 24.0 }, // IT hall
    material: 'concrete_pad',
    colour_hex: '#c8c8c8',
    fallback: 'box',
    parametric_rule: 'it_mw_per_unit=40;pue_target=1.2',
    standards: ['Uptime Tier III', 'EN 50600', 'BREEAM'],
    glb_path: '/assets/twin3d/data_centre/hall.glb',
  },
  {
    id: 'dc.crac',
    type: 'dc_crac',
    dims: { l: 1.5, w: 1.0, h: 2.2 }, // precision CRAC
    material: 'galvanised_steel',
    colour_hex: '#b0b5bc',
    fallback: 'box',
    parametric_rule: 'cooling_kw_per_unit=80',
    standards: ['ASHRAE TC9.9'],
  },
  {
    id: 'dc.genset_3mw',
    type: 'dc_genset',
    dims: { l: 12.0, w: 2.5, h: 3.5 }, // containerised 3 MW diesel genset
    material: 'oxide_red',
    colour_hex: '#7a2c24',
    fallback: 'box',
    parametric_rule: 'rating_mw_per_unit=3.0;tank_hours=48',
    standards: ['ISO 8528', 'MCPD (Tier V)'],
  },
  {
    id: 'dc.ups_room',
    type: 'dc_ups',
    dims: { l: 10.0, w: 6.0, h: 4.0 },
    material: 'painted_metal_grey',
    colour_hex: '#3d4250',
    fallback: 'box',
    parametric_rule: 'rating_mw_per_unit=2.5;autonomy_min=10',
    standards: ['IEC 62040'],
  },
];

// ------------------------------------------------------------------
// Build lookups
// ------------------------------------------------------------------

function buildRegistry(entries) {
  const byId = new Map();
  const byType = new Map();
  for (const entry of entries) {
    byId.set(entry.id, entry);
    if (!byType.has(entry.type)) byType.set(entry.type, []);
    byType.get(entry.type).push(entry);
  }
  return { entries, byId, byType };
}

let REGISTRY = buildRegistry(ASSET_SEED);

export function getAssetRegistry() {
  return REGISTRY;
}

export function getAssetDef(idOrType) {
  if (!idOrType) return null;
  if (REGISTRY.byId.has(idOrType)) return REGISTRY.byId.get(idOrType);
  // fall back: first entry matching that type
  if (REGISTRY.byType.has(idOrType)) return REGISTRY.byType.get(idOrType)[0];
  return null;
}

/**
 * Merge an externally loaded catalogue (shape: array of entries) on
 * top of the seed. Returns the hydrated registry.
 */
export function hydrateRegistry(externalEntries) {
  if (!Array.isArray(externalEntries) || externalEntries.length === 0) {
    return REGISTRY;
  }
  const merged = [...ASSET_SEED];
  const idIndex = new Map(merged.map((e, i) => [e.id, i]));
  for (const ext of externalEntries) {
    if (!ext || !ext.id) continue;
    if (idIndex.has(ext.id)) {
      merged[idIndex.get(ext.id)] = { ...merged[idIndex.get(ext.id)], ...ext };
    } else {
      merged.push(ext);
    }
  }
  REGISTRY = buildRegistry(merged);
  return REGISTRY;
}

export default getAssetRegistry;
