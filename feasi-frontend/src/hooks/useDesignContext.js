/**
 * useDesignContext — constraint-overlay data fetcher for the Site Designer
 * (BOT-SDB, 2026-04-21).
 *
 * Mirrors the shape + semantics of `useDCContext` but trimmed to what the
 * Design canvas cares about: the five constraint classes Glint-style users
 * expect to see on an aerial — plus a glint-cone payload (used for the
 * solar-adjacent Sun-path overlay).
 *
 * Returned shape:
 *   {
 *     buildableMask: { type, features, meta } | null,  // /api/design/buildable-mask
 *     floodZones:    { type, features }         | null, // EA Flood Zone 3
 *     environment:   { flood, environmental, heritage, overall_risk_level } | null,
 *     glintCones:    { surfaces, cones, receptor_hits } | null, // /api/dc/glint-screen
 *     loading: bool,
 *     sources: string[]
 *   }
 *
 * Debounced by the rounded centroid (~500 m grid) so small drags don't
 * thrash the network. Every fetcher is defensive — any 404/500 returns
 * `null` rather than throwing — so an offline backend still renders a
 * basemap without blowing the designer up.
 */
import { useEffect, useState, useMemo } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

const INITIAL = {
  buildableMask: null,
  floodZones: null,
  environment: null,
  glintCones: null,
  loading: false,
  sources: [],
};

async function safeJson(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export function useDesignContext({
  lat,
  lon,
  enabled = true,
  radiusM = 1500,
} = {}) {
  const [state, setState] = useState(INITIAL);

  // Debounce by snapping to ~500 m grid (0.005°)
  const keyLat = useMemo(() => Math.round((lat ?? 0) * 200) / 200, [lat]);
  const keyLon = useMemo(() => Math.round((lon ?? 0) * 200) / 200, [lon]);

  useEffect(() => {
    if (!enabled || lat == null || lon == null) return undefined;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));

    const bbox = (() => {
      const halfDegLat = radiusM / 111_320;
      const halfDegLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
      return [
        lon - halfDegLon,
        lat - halfDegLat,
        lon + halfDegLon,
        lat + halfDegLat,
      ];
    })();
    const bboxStr = encodeURIComponent(bbox.join(","));

    (async () => {
      const [buildableMask, floodZones, environment, glintCones] =
        await Promise.all([
          safeJson(
            `${API_BASE}/api/design/buildable-mask?lat=${lat}&lon=${lon}&radius_m=${radiusM}`,
          ),
          safeJson(`${API_BASE}/api/ea/flood/3?bbox=${bboxStr}`),
          safeJson(
            `${API_BASE}/api/environment/constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`,
          ),
          safeJson(
            `${API_BASE}/api/dc/glint-screen?lat=${lat}&lon=${lon}`,
          ),
        ]);

      if (cancelled) return;

      const sources = [];
      if (buildableMask?.features?.length) sources.push("buildableMask");
      if (floodZones?.features?.length) sources.push("floodZones");
      if (environment) sources.push("environment");
      if (glintCones?.cones?.length) sources.push("glintCones");

      setState({
        buildableMask,
        floodZones,
        environment,
        glintCones,
        loading: false,
        sources,
      });
    })().catch(() => {
      if (!cancelled) setState((s) => ({ ...s, loading: false }));
    });

    return () => {
      cancelled = true;
    };
  }, [keyLat, keyLon, enabled, radiusM]); // eslint-disable-line

  return state;
}

export default useDesignContext;
