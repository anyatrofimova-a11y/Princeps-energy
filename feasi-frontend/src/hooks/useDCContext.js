/**
 * useDCContext — single hook that aggregates every data source the DC Twin
 * utility + context overlays need. Debounces by the rounded site centroid
 * so small shell-drags don't thrash the network.
 *
 * Returned shape:
 *   {
 *     substation: { name, distance_km, voltage_kv, headroom_mw, sub_id, ... } | null,
 *     substationDetail: { ... enriched 8-section payload ... } | null,
 *     environment:  { flood, environmental, heritage, overall_risk_level } | null,
 *     buildableMask: { type, features, meta } | null,
 *     floodZones:   { type, features } | null,
 *     waterway:     { lat, lon, distanceM, name, _heuristic: true } | null,
 *     fiberPop:     { lat, lon, distanceM, name, _heuristic: true } | null,
 *     gasMain:      { lat, lon, distanceM, name, _heuristic: true } | null,
 *     road:         { lat, lon, distanceM, name, _heuristic: true } | null,
 *     loading: bool,
 *     sources:  ['substation', 'environment', ...]   // which came back non-null
 *     fallbacks: ['fiber', 'water', 'gas']            // which used heuristic
 *   }
 */
import { useEffect, useState, useMemo } from "react";
import {
  fetchNearestSubstation,
  fetchSubstationDetail,
  fetchEnvironmentConstraints,
  fetchBuildableMask,
  fetchFloodZones,
  fetchNearestWaterway,
  fetchNearestFiberPOP,
  fetchNearestGasMain,
  fetchNearestRoad,
} from "../api/dcContext";

const INITIAL = {
  substation: null,
  substationDetail: null,
  environment: null,
  buildableMask: null,
  floodZones: null,
  waterway: null,
  fiberPop: null,
  gasMain: null,
  road: null,
  loading: false,
  sources: [],
  fallbacks: [],
};

export function useDCContext({ lat, lon, enabled = true, radiusM = 2000 } = {}) {
  const [state, setState] = useState(INITIAL);

  // Debounce by snapping to ~500 m grid (0.005°) so drag doesn't thrash.
  const keyLat = useMemo(() => Math.round(lat * 200) / 200, [lat]);
  const keyLon = useMemo(() => Math.round(lon * 200) / 200, [lon]);

  useEffect(() => {
    if (!enabled || lat == null || lon == null) return undefined;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));

    const bbox = (() => {
      const halfDegLat = radiusM / 111_320;
      const halfDegLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
      return [lon - halfDegLon, lat - halfDegLat, lon + halfDegLon, lat + halfDegLat];
    })();

    (async () => {
      // Phase 1 — primary backend endpoints in parallel.
      const [substation, environment, buildableMask, floodZones] = await Promise.all([
        fetchNearestSubstation(lat, lon),
        fetchEnvironmentConstraints(lat, lon, radiusM),
        fetchBuildableMask(lat, lon, Math.max(radiusM, 1500)),
        fetchFloodZones(bbox, 3),
      ]);
      if (cancelled) return;

      // Phase 2 — enriched substation detail (depends on id from phase 1).
      let substationDetail = null;
      if (substation?.sub_id) {
        substationDetail = await fetchSubstationDetail(substation.sub_id);
      }
      if (cancelled) return;

      // Phase 3 — heuristic fallbacks (Overpass; slower, non-blocking for UI).
      const [waterway, fiberPop, gasMain, road] = await Promise.all([
        fetchNearestWaterway(lat, lon),
        fetchNearestFiberPOP(lat, lon),
        fetchNearestGasMain(lat, lon),
        fetchNearestRoad(lat, lon),
      ]);
      if (cancelled) return;

      const sources = [];
      const fallbacks = [];
      if (substation) sources.push("substation");
      if (substationDetail) sources.push("substationDetail");
      if (environment) sources.push("environment");
      if (buildableMask?.features?.length) sources.push("buildableMask");
      if (floodZones?.features?.length) sources.push("floodZones");
      if (waterway) { sources.push("waterway"); if (waterway._heuristic) fallbacks.push("water"); }
      if (fiberPop) { sources.push("fiberPop"); if (fiberPop._heuristic) fallbacks.push("fiber"); }
      if (gasMain)  { sources.push("gasMain");  if (gasMain._heuristic)  fallbacks.push("gas"); }
      if (road)     { sources.push("road");     if (road._heuristic)     fallbacks.push("road"); }

      setState({
        substation,
        substationDetail,
        environment,
        buildableMask,
        floodZones,
        waterway,
        fiberPop,
        gasMain,
        road,
        loading: false,
        sources,
        fallbacks,
      });
    })().catch(() => {
      if (!cancelled) setState((s) => ({ ...s, loading: false }));
    });

    return () => { cancelled = true; };
  }, [keyLat, keyLon, enabled, radiusM]); // eslint-disable-line

  return state;
}
