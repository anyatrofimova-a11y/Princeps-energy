/**
 * Princeps 3D Twin v1 — PBR material library
 * ----------------------------------------------------------------------
 * Lightweight PBR descriptors consumed by deck.gl SimpleMeshLayer and
 * (in v2) react-three-fiber custom layers. Each material exposes the
 * minimum set of properties that both rendering paths understand:
 *   - colour   : hex string, used for the base albedo
 *   - metalness: 0..1 (PBR standard)
 *   - roughness: 0..1 (PBR standard)
 *   - emissive : hex string (usually '#000000' for non-emissive assets)
 *
 * deck.gl SimpleMeshLayer today ignores metalness/roughness and uses
 * only colour + basic ambient, which is fine for v1 "opaque silhouette"
 * renders. Sibling agents will swap this into ScenegraphLayer or a
 * custom R3F overlay in v2 with identical material keys — so DO NOT
 * rename existing entries.
 */

export const MATERIALS = {
  painted_metal_grey: {
    colour: '#2f3540',
    metalness: 0.35,
    roughness: 0.55,
    emissive: '#000000',
    description: 'Painted steel (BESS containers, UPS rooms)',
  },
  pv_blue: {
    colour: '#1a2a5c',
    metalness: 0.1,
    roughness: 0.35,
    emissive: '#000000',
    description: 'Antireflective PV glass on mono-Si module',
  },
  concrete_pad: {
    colour: '#c8c8c8',
    metalness: 0.0,
    roughness: 0.9,
    emissive: '#000000',
    description: 'Poured concrete slab / DC shell cladding',
  },
  galvanised_steel: {
    colour: '#9fa4ad',
    metalness: 0.8,
    roughness: 0.35,
    emissive: '#000000',
    description: 'Hot-dip galvanised steel (inverters, CRAC, skids)',
  },
  oxide_red: {
    colour: '#7a2c24',
    metalness: 0.3,
    roughness: 0.55,
    emissive: '#000000',
    description: 'Oxide red — gensets, fire-rated enclosures',
  },
  substation_white: {
    colour: '#e3e6eb',
    metalness: 0.2,
    roughness: 0.6,
    emissive: '#000000',
    description: 'Substation / transformer cream-white enclosure',
  },
  earth_tarmac: {
    colour: '#2e2c2a',
    metalness: 0.0,
    roughness: 0.95,
    emissive: '#000000',
    description: 'Internal roads, hardstanding',
  },
};

/**
 * Parse '#rrggbb' to [r, g, b, 255] (uint8) — the format deck.gl's
 * SimpleMeshLayer getColor prop expects.
 */
export function hexToRgba(hex, alpha = 255) {
  if (!hex || typeof hex !== 'string') return [200, 200, 200, alpha];
  const h = hex.startsWith('#') ? hex.slice(1) : hex;
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  if (full.length !== 6) return [200, 200, 200, alpha];
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) return [200, 200, 200, alpha];
  return [r, g, b, alpha];
}

export function getMaterial(key) {
  return MATERIALS[key] || MATERIALS.painted_metal_grey;
}

export default MATERIALS;
