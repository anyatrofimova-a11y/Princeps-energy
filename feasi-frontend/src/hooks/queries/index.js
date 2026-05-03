/**
 * React Query hooks — Stage B4 analysis cache layer.
 *
 * Replaces the 17 useState slices in SiteContext with cache-keyed queries
 * that auto-fetch when their inputs change. Migration is gradual:
 *
 *   • Old code keeps using `const {solarYield} = useSite()` — works.
 *   • New code uses `const {data: solarYield, isLoading} = useSolarYield(parcelId, params)`.
 *
 * Aggregate hook `useSiteAnalysis` mirrors what the old `loadSite()`
 * orchestration produced: a single object with all slices as queries.
 */

import {useQuery} from '@tanstack/react-query';
import {queryKeys} from './keys.js';
import {fetchers} from './fetchers.js';

const ENABLED_IF = (parcelId) => Boolean(parcelId);

// ─── Site-context analysis hooks (all 17 wired) ──────────────────

export function useHeightmap(parcelId) {
  return useQuery({
    queryKey: queryKeys.heightmap(parcelId),
    queryFn: () => fetchers.heightmap(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useExplain(parcelId) {
  return useQuery({
    queryKey: queryKeys.explain(parcelId),
    queryFn: () => fetchers.explain(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useSlopeStats(parcelId) {
  return useQuery({
    queryKey: queryKeys.slopeStats(parcelId),
    queryFn: () => fetchers.slopeStats(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useSolarYield(parcelId, params) {
  return useQuery({
    queryKey: queryKeys.solarYield(parcelId, params),
    queryFn: () => fetchers.solarYield({parcelId, ...(params || {})}),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useSolarHourly(parcelId, params) {
  return useQuery({
    queryKey: queryKeys.solarHourly(parcelId, params),
    queryFn: () => fetchers.solarHourly({parcelId, ...(params || {})}),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useMlSolar(parcelId, params) {
  return useQuery({
    queryKey: queryKeys.mlSolar(parcelId, params),
    queryFn: () => fetchers.mlSolar({parcelId, ...(params || {})}),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useDeferral(parcelId, params) {
  return useQuery({
    queryKey: queryKeys.deferral(parcelId, params),
    queryFn: () => fetchers.deferral({parcelId, ...(params || {})}),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useEnergyPrice() {
  return useQuery({
    queryKey: queryKeys.energyPrice(null),
    queryFn: () => fetchers.energyPrice(),
  });
}

export function useGridContext(parcelId) {
  return useQuery({
    queryKey: queryKeys.gridContext(parcelId),
    queryFn: () => fetchers.gridContext(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function usePlanningApps(parcelId, radiusKm) {
  return useQuery({
    queryKey: queryKeys.planningApps(parcelId, radiusKm),
    queryFn: () => fetchers.planningApps(parcelId, radiusKm),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useEnergySystem(parcelId) {
  return useQuery({
    queryKey: queryKeys.energySystem(parcelId),
    queryFn: () => fetchers.energySystem(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useSiteBom(parcelId) {
  return useQuery({
    queryKey: queryKeys.siteBom(parcelId),
    queryFn: () => fetchers.siteBom(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useBomAvail(parcelId) {
  return useQuery({
    queryKey: queryKeys.bomAvail(parcelId),
    queryFn: () => fetchers.bomAvail(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useAgentResult(parcelId, intent = 'feasibility') {
  return useQuery({
    queryKey: queryKeys.agentResult(parcelId, intent),
    queryFn: () => fetchers.agentResult(parcelId, intent),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useDemandForecast(parcelId) {
  return useQuery({
    queryKey: queryKeys.demandForecast(parcelId),
    queryFn: () => fetchers.demandForecast(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useAgilePricing() {
  return useQuery({
    queryKey: queryKeys.agilePricing(),
    queryFn: () => fetchers.agilePricing(),
  });
}

export function useStabilityData(parcelId) {
  return useQuery({
    queryKey: queryKeys.stabilityData(parcelId),
    queryFn: () => fetchers.stabilityData(parcelId),
    enabled: ENABLED_IF(parcelId),
  });
}

export function useGeeflow(parcelId, jobId) {
  return useQuery({
    queryKey: queryKeys.geeflow(parcelId, jobId),
    queryFn: () => fetchers.geeflow(parcelId, jobId),
    enabled: ENABLED_IF(parcelId),
  });
}

// ─── Workshop chrome hooks (already wired backend-side) ─────────

export function useOntologyTree() {
  return useQuery({
    queryKey: queryKeys.ontologyTree(),
    queryFn: fetchers.ontologyTree,
  });
}

export function useOntologyObject(rid) {
  return useQuery({
    queryKey: queryKeys.ontologyObject(rid),
    queryFn: () => fetchers.ontologyObject(rid),
    enabled: Boolean(rid),
  });
}

// ─── Industrial graph hooks ──────────────────────────────────────

export function useEntity(rid) {
  return useQuery({
    queryKey: queryKeys.entity(rid),
    queryFn: () => fetchers.entity(rid),
    enabled: Boolean(rid),
  });
}

export function useEntityRelations(rid, direction) {
  return useQuery({
    queryKey: queryKeys.entityRelations(rid, direction),
    queryFn: () => fetchers.entityRelations(rid, direction),
    enabled: Boolean(rid),
  });
}

// ─── Aggregate: useSiteAnalysis ─────────────────────────────────
//
// Mirrors what the old `loadSite()` orchestration produced. Returns the
// individual UseQueryResult objects so callers can show per-slice loading
// states + errors instead of hiding everything behind a single spinner.

export function useSiteAnalysis(parcelId, params = {}) {
  return {
    heightmap:      useHeightmap(parcelId),
    explain:        useExplain(parcelId),
    slopeStats:     useSlopeStats(parcelId),
    solarYield:     useSolarYield(parcelId, params),
    solarHourly:    useSolarHourly(parcelId, params),
    mlSolar:        useMlSolar(parcelId, params),
    deferral:       useDeferral(parcelId, params),
    energyPrice:    useEnergyPrice(),
    gridContext:    useGridContext(parcelId),
    planningApps:   usePlanningApps(parcelId, params.radiusKm),
    energySystem:   useEnergySystem(parcelId),
    siteBom:        useSiteBom(parcelId),
    bomAvail:       useBomAvail(parcelId),
    agentResult:    useAgentResult(parcelId, params.intent),
    demandForecast: useDemandForecast(parcelId),
    agilePricing:   useAgilePricing(),
    stabilityData:  useStabilityData(parcelId),
  };
}

export {queryKeys, fetchers};
