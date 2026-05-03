/**
 * Fetchers paired with queryKeys (Stage B4).
 *
 * Each fetcher calls a known FastAPI endpoint via the existing `api`
 * service module where one is wired, falling back to a raw fetch otherwise.
 *
 * Goal: keep fetchers thin — no transformations beyond unwrapping the
 * response envelope. Components apply slice-specific shaping.
 */

import api from '../../services/api.js';

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`);
  return r.json();
}

export const fetchers = {

  // ─── Workshop chrome ─────────────────────────────────────────────
  ontologyTree:   () => get('/api/workshop/tree'),
  ontologyObject: (rid) => get(`/api/workshop/object/${encodeURIComponent(rid)}`),

  // ─── Industrial graph (Swarm 6) ─────────────────────────────────
  entity:          (rid) => get(`/api/industrial/entities/${encodeURIComponent(rid)}`),
  entityRelations: (rid, direction = 'out') =>
    get(`/api/industrial/entities/${encodeURIComponent(rid)}/relationships?direction=${direction}`),

  // ─── Site-context analysis slices ────────────────────────────────
  // Each fetcher calls api.X.Y() if it exists; otherwise raw fetch.
  // TODO: wire each to its concrete endpoint as components migrate.
  heightmap:      (parcelId) =>
    api.heightmap?.(parcelId) ?? get(`/api/site/heightmap?parcel=${parcelId}`),
  explain:        (parcelId) =>
    api.explain?.(parcelId) ?? get(`/api/site/explain?parcel=${parcelId}`),
  slopeStats:     (parcelId) =>
    api.slopeStats?.(parcelId) ?? get(`/api/site/slope?parcel=${parcelId}`),
  solarYield:     ({parcelId, samCapacity, samDay, loadMw, genMw}) =>
    api.solar?.yield?.({parcelId, samCapacity, samDay, loadMw, genMw}) ??
    get(`/api/sam/yield?parcel=${parcelId}&capacity=${samCapacity}&day=${samDay}&load=${loadMw}&gen=${genMw}`),
  solarHourly:    ({parcelId, ...params}) =>
    api.solar?.hourly?.({parcelId, ...params}) ??
    get(`/api/sam/hourly?parcel=${parcelId}`),
  mlSolar:        ({parcelId, ...params}) =>
    api.ml?.solar?.({parcelId, ...params}) ??
    get(`/api/ml/solar?parcel=${parcelId}`),
  deferral:       ({parcelId, ...params}) =>
    api.deferral?.({parcelId, ...params}) ?? get(`/api/deferral?parcel=${parcelId}`),
  energyPrice:    () => api.energyPrice?.() ?? get('/api/market/energy-price'),
  gridContext:    (parcelId) =>
    api.grid?.context?.(parcelId) ?? get(`/api/grid/context?parcel=${parcelId}`),
  planningApps:   (parcelId, radiusKm = 5) =>
    api.planning?.apps?.(parcelId, radiusKm) ??
    get(`/api/planning/apps?parcel=${parcelId}&radius_km=${radiusKm}`),
  energySystem:   (parcelId) =>
    api.energy?.system?.(parcelId) ?? get(`/api/energy/system?parcel=${parcelId}`),
  siteBom:        (parcelId) =>
    api.bom?.site?.(parcelId) ?? get(`/api/bom/site?parcel=${parcelId}`),
  bomAvail:       (parcelId) =>
    api.bom?.avail?.(parcelId) ?? get(`/api/bom/avail?parcel=${parcelId}`),
  agentResult:    (parcelId, intent) =>
    api.agent?.run?.(parcelId, intent) ??
    get(`/api/agent/run?parcel=${parcelId}&intent=${intent}`),
  demandForecast: (parcelId) =>
    api.demand?.forecast?.(parcelId) ?? get(`/api/demand/forecast?parcel=${parcelId}`),
  agilePricing:   () => api.agilePricing?.() ?? get('/api/market/agile'),
  stabilityData:  (parcelId) =>
    api.stability?.(parcelId) ?? get(`/api/grid/stability?parcel=${parcelId}`),
  geeflow:        (parcelId, jobId) => {
    const q = jobId ? `&job=${jobId}` : '';
    return api.geeflow?.(parcelId, jobId) ?? get(`/api/geeflow?parcel=${parcelId}${q}`);
  },
};
