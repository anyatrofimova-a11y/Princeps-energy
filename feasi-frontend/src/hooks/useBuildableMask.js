/**
 * useBuildableMask — fetches + caches the buildable-area mask for a site.
 *
 * Backend: GET /api/design/buildable-mask?lat&lon&radius_m
 *   -> GeoJSON FeatureCollection of RESTRICTED polygons (classes:
 *      restricted_slope | restricted_flood | restricted_alc |
 *      restricted_protected | restricted_land). The "buildable" area is the
 *      complement within the circular site buffer.
 *
 * Returns:
 *   {
 *     mask,                  // raw FeatureCollection (restricted polys)
 *     buildablePolygon,      // GeoJSON Polygon (outer ring = radius buffer,
 *                            //   inner rings = restricted features punched out)
 *     parcelPolygon,         // GeoJSON Polygon of the outer circle (proxy for parcel
 *                            //   until BOT-G wires real INSPIRE geometry)
 *     buildableCentroid,     // [lon, lat] — centroid of largest buildable component
 *     isBuildable(lon, lat), // true if point is inside circle AND NOT in any restriction
 *     parcelContains(lon, lat), // true if point inside the circle
 *     restrictionAt(lon, lat),  // { class, source, name } or null
 *     nearestFloodBufferM(lon, lat), // metres to nearest restricted_flood edge (+inf if none)
 *     loading, error, radiusM,
 *   }
 *
 * The mask is cached by rounded lat/lon (~500 m grid) so drags don't thrash
 * the API. The frontend-side point-in-polygon uses the browser-bundled
 * @turf/boolean-point-in-polygon which is already a dep of the app.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { point as turfPoint, polygon as turfPolygon } from "@turf/helpers";
import distance from "@turf/distance";
import nearestPointOnLine from "@turf/nearest-point-on-line";

const M_PER_DEG_LAT = 111_320;
const mPerDegLon = (lat) => M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);

/** Build an approximate circle polygon as a [lon,lat] ring with 64 segments. */
function circlePolygon(lat, lon, radiusM, segments = 64) {
  const ring = [];
  const dLat = radiusM / M_PER_DEG_LAT;
  const dLon = radiusM / mPerDegLon(lat);
  for (let i = 0; i <= segments; i++) {
    const t = (i / segments) * 2 * Math.PI;
    ring.push([lon + dLon * Math.cos(t), lat + dLat * Math.sin(t)]);
  }
  return ring; // closed ring (first == last)
}

/** Extract every Polygon ring from a Feature (handles Polygon + MultiPolygon). */
function extractPolygons(feature) {
  const g = feature?.geometry;
  if (!g) return [];
  if (g.type === "Polygon") return [g.coordinates];
  if (g.type === "MultiPolygon") return g.coordinates;
  return [];
}

const cacheRef = { current: new Map() };

function cacheKey(lat, lon, radiusM) {
  const latK = Math.round(lat * 200) / 200;   // ~500 m grid
  const lonK = Math.round(lon * 200) / 200;
  return `${latK}|${lonK}|${radiusM}`;
}

export default function useBuildableMask({ lat, lon, radiusM = 1500, enabled = true } = {}) {
  const [mask, setMask] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  // Server-computed positive-buildable polygon (BOT-B1). When the new
  // /api/design/buildable endpoint returns 200, we use its single
  // class=buildable polygon directly and skip the client-side subtract
  // step below. Falls back silently to the restricted-mask flow if the
  // endpoint 404s / 5xxs so older deployments keep working.
  const [positive, setPositive] = useState(null);

  useEffect(() => {
    if (!enabled || lat == null || lon == null) return;
    const key = cacheKey(lat, lon, radiusM);
    const cached = cacheRef.current.get(key);
    if (cached) {
      setMask(cached.mask || null);
      setPositive(cached.positive || null);
      return;
    }

    const ctrl = new AbortController();
    abortRef.current?.abort();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);

    (async () => {
      let maskData = null;
      let positiveData = null;
      try {
        // 1. Try the new positive endpoint first.
        try {
          const posUrl = `/api/design/buildable?lat=${lat}&lon=${lon}&radius_m=${radiusM}`;
          const posRes = await fetch(posUrl, { signal: ctrl.signal });
          if (posRes.ok) positiveData = await posRes.json();
        } catch (e) {
          if (e.name === "AbortError") throw e;
          // swallow — fall through to mask
        }

        // 2. Always fetch the restricted-mask so we keep flood-distance,
        // restriction-at, etc. working even when the positive endpoint is up.
        const url = `/api/design/buildable-mask?lat=${lat}&lon=${lon}&radius_m=${radiusM}`;
        const res = await fetch(url, { signal: ctrl.signal });
        if (!res.ok && !positiveData) throw new Error(`HTTP ${res.status}`);
        if (res.ok) maskData = await res.json();

        const payload = { mask: maskData, positive: positiveData };
        cacheRef.current.set(key, payload);
        if (cacheRef.current.size > 40) {
          const first = cacheRef.current.keys().next().value;
          cacheRef.current.delete(first);
        }
        setMask(maskData);
        setPositive(positiveData);
      } catch (e) {
        if (e.name !== "AbortError") setError(e);
      } finally {
        setLoading(false);
      }
    })();

    return () => ctrl.abort();
  }, [lat, lon, radiusM, enabled]);

  const derived = useMemo(() => {
    if (lat == null || lon == null) return null;
    const outerRing = circlePolygon(lat, lon, radiusM);

    const restrictedRings = [];
    const flaggedFeatures = [];
    if (mask?.features) {
      for (const f of mask.features) {
        const polys = extractPolygons(f);
        for (const p of polys) {
          if (!p?.[0]?.length) continue;
          restrictedRings.push({ ring: p[0], feature: f });
          flaggedFeatures.push(f);
        }
      }
    }

    const buildablePolygon = {
      type: "Polygon",
      coordinates: [outerRing, ...restrictedRings.map(r => r.ring)],
    };
    const parcelPolygon = { type: "Polygon", coordinates: [outerRing] };

    // Find the largest buildable sub-region by sampling a 16x16 grid and taking
    // the mean of buildable samples. This is a coarse proxy for centroid — the
    // user gets a sensible initial position and can drag from there.
    const samples = [];
    const N = 16;
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const dx = ((i + 0.5) / N - 0.5) * 2 * radiusM;
        const dy = ((j + 0.5) / N - 0.5) * 2 * radiusM;
        const pLon = lon + dx / mPerDegLon(lat);
        const pLat = lat + dy / M_PER_DEG_LAT;
        // inside outer circle?
        const d2 = dx * dx + dy * dy;
        if (d2 > radiusM * radiusM) continue;
        // in any restriction?
        let blocked = false;
        const pt = turfPoint([pLon, pLat]);
        for (const { ring } of restrictedRings) {
          try {
            if (booleanPointInPolygon(pt, turfPolygon([ring]))) { blocked = true; break; }
          } catch { /* skip invalid ring */ }
        }
        if (!blocked) samples.push([pLon, pLat]);
      }
    }
    let buildableCentroid = [lon, lat];
    if (samples.length) {
      let sx = 0, sy = 0;
      for (const [x, y] of samples) { sx += x; sy += y; }
      buildableCentroid = [sx / samples.length, sy / samples.length];
    }

    const isBuildable = (plon, plat) => {
      // inside radius?
      const dxm = (plon - lon) * mPerDegLon(lat);
      const dym = (plat - lat) * M_PER_DEG_LAT;
      if (dxm * dxm + dym * dym > radiusM * radiusM) return false;
      const pt = turfPoint([plon, plat]);
      for (const { ring } of restrictedRings) {
        try {
          if (booleanPointInPolygon(pt, turfPolygon([ring]))) return false;
        } catch { /* skip */ }
      }
      return true;
    };
    const parcelContains = (plon, plat) => {
      const dxm = (plon - lon) * mPerDegLon(lat);
      const dym = (plat - lat) * M_PER_DEG_LAT;
      return dxm * dxm + dym * dym <= radiusM * radiusM;
    };
    const restrictionAt = (plon, plat) => {
      const pt = turfPoint([plon, plat]);
      for (const { ring, feature } of restrictedRings) {
        try {
          if (booleanPointInPolygon(pt, turfPolygon([ring]))) {
            return {
              class: feature?.properties?.class || "restricted",
              source: feature?.properties?.source || "unknown",
              name: feature?.properties?.name || "designation",
            };
          }
        } catch { /* skip */ }
      }
      return null;
    };

    // Distance (m) from a point to the nearest flood-zone edge, across all
    // restricted_flood features. +Infinity if none present.
    const floodLines = restrictedRings
      .filter(r => r.feature?.properties?.class === "restricted_flood")
      .map(r => ({ type: "Feature", geometry: { type: "LineString", coordinates: r.ring }, properties: {} }));
    const nearestFloodBufferM = (plon, plat) => {
      if (!floodLines.length) return Infinity;
      const p = turfPoint([plon, plat]);
      let best = Infinity;
      for (const line of floodLines) {
        try {
          const np = nearestPointOnLine(line, p, { units: "kilometers" });
          const km = distance(p, np, { units: "kilometers" });
          if (km * 1000 < best) best = km * 1000;
        } catch { /* skip */ }
      }
      return best;
    };

    return {
      outerRing,
      restrictedRings,
      flaggedFeatures,
      buildablePolygon,
      parcelPolygon,
      buildableCentroid,
      isBuildable,
      parcelContains,
      restrictionAt,
      nearestFloodBufferM,
    };
  }, [mask, lat, lon, radiusM]);

  // Prefer the server-computed positive polygon when present. It's already the
  // buffer minus restrictions with holes punched out, so we can render it
  // directly as a single fill layer instead of making the frontend do geometry.
  const serverBuildable = positive?.features?.[0]?.geometry || null;
  const serverAreaHa = positive?.buildable_area_ha ?? null;

  return {
    mask,
    positive,                    // full server payload (provenance, explanation)
    loading,
    error,
    radiusM,
    buildablePolygon: serverBuildable || derived?.buildablePolygon || null,
    buildableAreaHa: serverAreaHa,
    parcelPolygon: derived?.parcelPolygon || null,
    buildableCentroid: derived?.buildableCentroid || null,
    isBuildable: derived?.isBuildable || (() => true),
    parcelContains: derived?.parcelContains || (() => true),
    restrictionAt: derived?.restrictionAt || (() => null),
    nearestFloodBufferM: derived?.nearestFloodBufferM || (() => Infinity),
    source: serverBuildable ? "server_positive" : (mask ? "client_subtract" : "none"),
  };
}

export { M_PER_DEG_LAT, mPerDegLon };
