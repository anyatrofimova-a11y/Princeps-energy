/**
 * Princeps 3D Twin — glTF asset loader
 * ----------------------------------------------------------------------
 * Soft-loads a compressed GLB from the public asset library shipped under
 * `/assets/twin3d/{workload}/{asset_id}.glb`. When a model is missing
 * (404, network error, or corrupt) the loader returns `null` so the caller
 * can fall back to the parametric box / cylinder defined by the registry
 * entry's `fallback` field. This keeps the twin renderable during the
 * CC-BY legal-review window when many MANIFEST rows are still
 * placeholder-only.
 *
 * The Three.js GLTFLoader is a runtime dependency — it is already pulled
 * in by `@react-three/drei` which the twin uses. If the import ever
 * fails at startup (e.g. during SSR), `loadAssetGLB` gracefully returns
 * `null` rather than crashing the bundle.
 *
 * Attribution / licensing is NOT enforced here — the registry + LICENSES.md
 * are the source of truth. `AttributionFooter.jsx` renders the credits at
 * render time.
 */

import { getAssetDef } from './registry';

// ----- Manifest (raw CSV import) ------------------------------------------
// The MANIFEST.csv ships from `feasi-frontend/public/assets/twin3d/`. Vite
// serves static JSON/CSV from there — we fetch it at module init and build
// an in-memory index. We keep a synchronous fallback table for the 12
// priority assets so `hasAssetGLB` returns deterministic truths even before
// the CSV fetch resolves.
let MANIFEST_INDEX = new Map();
let MANIFEST_READY = false;

const FALLBACK_MANIFEST = [
  { asset_id: 'bess.megapack_2xl',          target_path: 'bess/megapack_2xl.glb',   licence: 'CC-BY-4.0' },
  { asset_id: 'bess.container_generic',     target_path: 'bess/container_generic.glb', licence: 'CC0' },
  { asset_id: 'bess.pcs_skid',              target_path: 'bess/pcs_skid.glb',       licence: 'CC-BY-4.0' },
  { asset_id: 'bess.aux_tx_2_5mva',         target_path: 'bess/aux_tx.glb',         licence: 'CC-BY-4.0' },
  { asset_id: 'solar.table_4h_portrait',    target_path: 'solar/pv_table.glb',      licence: 'CC-BY-4.0' },
  { asset_id: 'solar.central_inverter_3mva',target_path: 'solar/inverter.glb',      licence: 'CC0' },
  { asset_id: 'dc.it_hall_shell',           target_path: 'data_centre/hall.glb',    licence: 'CC0' },
  { asset_id: 'dc.crac_unit',               target_path: 'data_centre/crac.glb',    licence: 'CC0' },
  { asset_id: 'dc.chiller_500kw',           target_path: 'data_centre/chiller.glb', licence: 'CC0' },
  { asset_id: 'dc.genset_enclosure_3mw',    target_path: 'data_centre/genset.glb',  licence: 'CC0' },
  { asset_id: 'wind.turbine_v172',          target_path: 'wind/turbine_v172.glb',   licence: 'CC-BY-4.0' },
  { asset_id: 'common.hgv_truck',           target_path: 'common/hgv.glb',          licence: 'CC0' },
];

// Seed with fallback table (so `hasAssetGLB` works pre-fetch)
for (const row of FALLBACK_MANIFEST) {
  MANIFEST_INDEX.set(row.asset_id, row);
  // Registry also uses variant ids — seed aliases where obvious:
  if (row.asset_id === 'bess.megapack_2xl') {
    MANIFEST_INDEX.set('bess.tesla_megapack_2xl', row);
  }
}

// Kick off the async CSV fetch (non-blocking). If the fetch fails we keep the
// seed table — the twin still renders.
async function hydrateManifest() {
  if (MANIFEST_READY) return;
  try {
    const res = await fetch('/assets/twin3d/MANIFEST.csv', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    const lines = text.split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) return;
    const header = lines[0].split(',').map((h) => h.trim());
    const idx = {
      asset_id: header.indexOf('asset_id'),
      vendor: header.indexOf('vendor'),
      source_url: header.indexOf('source_url'),
      licence: header.indexOf('licence'),
      target_path: header.indexOf('target_path'),
      status: header.indexOf('status'),
      notes: header.indexOf('notes'),
    };
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(',');
      const id = parts[idx.asset_id]?.trim();
      if (!id) continue;
      MANIFEST_INDEX.set(id, {
        asset_id: id,
        vendor: parts[idx.vendor]?.trim() ?? '',
        source_url: parts[idx.source_url]?.trim() ?? '',
        licence: parts[idx.licence]?.trim() ?? '',
        target_path: parts[idx.target_path]?.trim() ?? '',
        status: idx.status >= 0 ? parts[idx.status]?.trim() ?? '' : '',
        notes: idx.notes >= 0 ? parts.slice(idx.notes).join(',').trim() : '',
      });
    }
    MANIFEST_READY = true;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[gltfLoader] Could not hydrate MANIFEST.csv — using seed:', err?.message);
  }
}

// Fire-and-forget the hydration on module load (browser only)
if (typeof window !== 'undefined' && typeof fetch === 'function') {
  hydrateManifest();
}

// ----- Path resolution -----------------------------------------------------
/**
 * Resolve an asset id to a public-relative glTF path.
 * Priority:
 *   1. `registry[id].glb_path`  (authoritative)
 *   2. `manifest[id].target_path` (prefixed with `/assets/twin3d/`)
 *   3. `null` (no model — caller uses parametric fallback)
 */
export function asset_path_from_registry(assetId) {
  if (!assetId) return null;
  const def = getAssetDef(assetId);
  if (def?.glb_path) {
    return def.glb_path.startsWith('/') ? def.glb_path : `/${def.glb_path}`;
  }
  const m = MANIFEST_INDEX.get(assetId);
  if (m?.target_path) {
    return `/assets/twin3d/${m.target_path.replace(/^\/+/, '')}`;
  }
  return null;
}

/**
 * True when the registry or manifest knows about a GLB for this asset.
 * Does NOT guarantee the file is on disk — just that we will attempt the
 * fetch. Callers can use this to decide whether to try glTF mode vs jump
 * straight to the parametric path.
 */
export function hasAssetGLB(assetId) {
  const def = getAssetDef(assetId);
  if (def?.glb_path) return true;
  return MANIFEST_INDEX.has(assetId);
}

/**
 * Return the licence string recorded in the manifest for this asset id.
 * Used by `AttributionFooter` to assemble the credit line.
 */
export function licenceFor(assetId) {
  const m = MANIFEST_INDEX.get(assetId);
  return m?.licence ?? null;
}

/**
 * List every asset id we have attribution metadata for — used by the
 * footer to render a summary and the modal's full table.
 */
export function listManifestEntries() {
  return Array.from(MANIFEST_INDEX.values()).filter(
    (e, i, arr) => arr.findIndex((x) => x.target_path === e.target_path) === i,
  );
}

// ----- Loader --------------------------------------------------------------
// Lazy-import GLTFLoader so we don't pay the cost on module init and so
// we can tolerate the case where three/drei isn't available (SSR, tests).
let _loaderPromise = null;
async function getLoader() {
  if (_loaderPromise) return _loaderPromise;
  _loaderPromise = (async () => {
    try {
      const mod = await import('three/examples/jsm/loaders/GLTFLoader.js');
      return new mod.GLTFLoader();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[gltfLoader] GLTFLoader unavailable — all loads will return null:', err?.message);
      return null;
    }
  })();
  return _loaderPromise;
}

// Cache loaded scenes by path so instancing doesn't re-fetch + re-parse.
const _sceneCache = new Map();

/**
 * Load the glTF scene for an asset id. Returns the three.js scene object
 * (or a clone-safe copy) on success, or `null` on any failure.
 *
 * Usage in AssetInstancedLayer:
 *   const scene = await loadAssetGLB(entry.id);
 *   if (scene) { // use SimpleMeshLayer.mesh = scene }
 *   else         { // fall back to parametric box via entry.fallback }
 */
export async function loadAssetGLB(assetId) {
  const path = asset_path_from_registry(assetId);
  if (!path) return null;

  if (_sceneCache.has(path)) {
    const cached = _sceneCache.get(path);
    return cached?.clone?.() ?? cached;
  }

  const loader = await getLoader();
  if (!loader) return null;

  try {
    const gltf = await loader.loadAsync(path);
    const scene = gltf?.scene ?? null;
    if (scene) _sceneCache.set(path, scene);
    return scene?.clone?.() ?? scene;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(`[gltfLoader] ${assetId} missing or invalid at ${path} — fallback to parametric`);
    return null;
  }
}

/** Clear the internal scene cache (useful in tests and hot-reload). */
export function _resetGLTFCache() {
  _sceneCache.clear();
  _loaderPromise = null;
}

export default loadAssetGLB;
