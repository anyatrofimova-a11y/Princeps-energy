/**
 * bessDesign.js — API client for the backend BESS engineering designer.
 *
 * Backend endpoints:
 *   GET  /api/twin/bess-catalogue   — vendor + PCS + transformer metadata
 *   POST /api/twin/bess-design      — full engineering pass
 *
 * Returns the raw payload from utils/bess_engineering.design_to_dict, with
 * an additional `centroid_lonlat` populated when a site_polygon_wkt was
 * provided. The frontend uses centroid_lonlat to translate the metre-offset
 * placed_assets / cable_runs / fence_polygon into lng/lat for deck.gl.
 */

const DEFAULT_TIMEOUT_MS = 12000;

function abortable(timeoutMs) {
  if (typeof AbortController === 'undefined') return { signal: undefined, cancel: () => {} };
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  return { signal: ctl.signal, cancel: () => clearTimeout(t) };
}

export async function fetchBessCatalogue() {
  const { signal, cancel } = abortable(DEFAULT_TIMEOUT_MS);
  try {
    const r = await fetch('/api/twin/bess-catalogue', { signal });
    if (!r.ok) throw new Error(`bess-catalogue ${r.status}`);
    return await r.json();
  } finally {
    cancel();
  }
}

/**
 * @param {Object} brief
 * @param {number} brief.capacity_mw           AC export rating MW
 * @param {number} brief.duration_h            Storage duration (hours)
 * @param {string} [brief.vendor_id]
 * @param {string} [brief.pcs_id]
 * @param {string} [brief.main_tx_id]
 * @param {number} [brief.grid_voltage_kv]
 * @param {string} [brief.augmentation]        none|annual|biennial|year_5_only
 * @param {number} [brief.project_life_y]
 * @param {number} [brief.target_dod]
 * @param {number} [brief.cycles_per_year]
 * @param {string} [brief.climate_zone]
 * @param {number} [brief.fence_setback_m]
 * @param {number} [brief.region_factor]
 * @param {number} [brief.discount_rate]
 * @param {number} [brief.poc_distance_m]
 * @param {string} [brief.site_polygon_wkt]    Required for centroid georef
 * @returns {Promise<Object|null>}
 */
export async function fetchBessDesign(brief) {
  if (!brief || !Number.isFinite(brief.capacity_mw)) return null;
  const { signal, cancel } = abortable(DEFAULT_TIMEOUT_MS);
  try {
    const r = await fetch('/api/twin/bess-design', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(brief),
      signal,
    });
    if (!r.ok) {
      // eslint-disable-next-line no-console
      console.warn('[bessDesign] non-200', r.status);
      return null;
    }
    return await r.json();
  } catch (err) {
    if (err?.name !== 'AbortError') {
      // eslint-disable-next-line no-console
      console.warn('[bessDesign] fetch failed', err);
    }
    return null;
  } finally {
    cancel();
  }
}

/**
 * Convert an (east_m, north_m) offset against `[centreLng, centreLat]` into
 * a deck.gl-compatible [lng, lat] pair. Identical to the helper in
 * TwinRoot — duplicated here so layer factories can stay self-contained.
 */
export function enuMetresToLngLat([centreLng, centreLat], eastM, northM) {
  const mPerDegLng = 111320 * Math.cos((centreLat * Math.PI) / 180);
  const mPerDegLat = 110540;
  const lng = centreLng + eastM / (mPerDegLng || 1);
  const lat = centreLat + northM / mPerDegLat;
  return [lng, lat];
}
