/**
 * React Query key factory (Stage B4 — analysis cache layer).
 *
 * Single source of truth for query identity. Components import from here
 * instead of hard-coding tuples; this lets us invalidate cleanly via
 * `queryClient.invalidateQueries({queryKey: queryKeys.solarYield(parcelId)})`.
 *
 * Naming convention: kebab-case slice name, then bind args (most-specific
 * last) so prefix-invalidation works. Example:
 *   ['solar-yield']                               → invalidates ALL solar-yield queries
 *   ['solar-yield', 'parcel-42']                  → just this parcel
 *   ['solar-yield', 'parcel-42', {capacity: 100}] → this parcel + these params
 */

export const queryKeys = {
  // Site-context analysis slices (the 17 that today live as useState in SiteContext).
  heightmap:       (parcelId) => ['heightmap', parcelId],
  explain:         (parcelId) => ['explain', parcelId],
  slopeStats:      (parcelId) => ['slope-stats', parcelId],
  solarYield:      (parcelId, params) => ['solar-yield', parcelId, params ?? null],
  solarHourly:     (parcelId, params) => ['solar-hourly', parcelId, params ?? null],
  mlSolar:         (parcelId, params) => ['ml-solar', parcelId, params ?? null],
  deferral:        (parcelId, params) => ['deferral', parcelId, params ?? null],
  energyPrice:     (parcelId) => ['energy-price', parcelId],
  gridContext:     (parcelId) => ['grid-context', parcelId],
  planningApps:    (parcelId, radiusKm) => ['planning-apps', parcelId, radiusKm ?? null],
  energySystem:    (parcelId) => ['energy-system', parcelId],
  siteBom:         (parcelId) => ['site-bom', parcelId],
  bomAvail:        (parcelId) => ['bom-avail', parcelId],
  agentResult:     (parcelId, intent) => ['agent-result', parcelId, intent ?? 'feasibility'],
  demandForecast:  (parcelId) => ['demand-forecast', parcelId],
  agilePricing:    () => ['agile-pricing'],
  stabilityData:   (parcelId) => ['stability-data', parcelId],

  // GeeFlow / EO
  geeflow:         (parcelId, jobId) => ['geeflow', parcelId, jobId ?? null],

  // Workshop chrome (already wired via /api/workshop/*).
  ontologyTree:    () => ['ontology-tree'],
  ontologyObject:  (rid) => ['ontology-object', rid],

  // Industrial graph (Swarm 6).
  entity:          (rid) => ['entity', rid],
  entityRelations: (rid, direction) => ['entity-relations', rid, direction ?? 'out'],
};
