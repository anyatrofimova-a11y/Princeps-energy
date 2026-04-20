/**
 * twinData.js — helpers for the project-context twin embed.
 * Fetching, geometry, persistence.
 */

export const LS_KEY = "princeps.assess.twin.layers";
export const DEFAULT_LAYERS = {
  boundary: true,
  substation: true,
  designations: true,
  flood: true,
  slope: false,
  landuse: false,
  queue: true,
};

export async function safeJson(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// 10 ha circle fallback (≈ 178.4 m radius)
export function circlePolygon(lat, lon, radiusM = 178.4, n = 64) {
  const coords = [];
  const R = 6378137;
  for (let i = 0; i <= n; i++) {
    const theta = (i / n) * 2 * Math.PI;
    const dLat = (radiusM * Math.cos(theta)) / R;
    const dLon = (radiusM * Math.sin(theta)) / (R * Math.cos((lat * Math.PI) / 180));
    coords.push([lon + (dLon * 180) / Math.PI, lat + (dLat * 180) / Math.PI]);
  }
  return {
    type: "Feature",
    properties: { _fallback: true },
    geometry: { type: "Polygon", coordinates: [coords] },
  };
}

export function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLon = ((b[0] - a[0]) * Math.PI) / 180;
  const la1 = (a[1] * Math.PI) / 180;
  const la2 = (b[1] * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function loadPrefs() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return { ...DEFAULT_LAYERS };
    return { ...DEFAULT_LAYERS, ...(JSON.parse(raw) || {}) };
  } catch { return { ...DEFAULT_LAYERS }; }
}

export function savePrefs(layers) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(layers)); } catch { /* noop */ }
}

/**
 * Fetch all overlay feeds for a project at (lat, lon).
 * Returns { boundary, substation, designations, flood, landuse, queue, statuses }.
 * Every field has a graceful fallback; never throws.
 */
export async function fetchTwinFeeds({ pid, lat, lon, sitePolygon }) {
  const statuses = {};
  const result = { statuses };

  // Boundary
  let b = pid ? await safeJson(`/api/projects/${pid}/site-boundary`) : null;
  if (!b && sitePolygon) {
    b = { type: "Feature", geometry: sitePolygon, properties: {} };
    statuses.boundary = "live";
  }
  if (!b) {
    b = circlePolygon(lat, lon);
    statuses.boundary = "pending";
  } else if (!statuses.boundary) {
    statuses.boundary = "live";
  }
  result.boundary = b;

  // Nearest substation (from 10 km radius scan)
  const subs = await safeJson(`/api/grid/substations?lat=${lat}&lon=${lon}&radius_km=10`);
  if (Array.isArray(subs) && subs.length) {
    const scored = subs.map((s) => {
      const sLat = s.lat ?? s.latitude;
      const sLon = s.lon ?? s.longitude;
      const d = sLat != null && sLon != null ? haversineKm([lon, lat], [sLon, sLat]) : 999;
      return { ...s, _lat: sLat, _lon: sLon, _dist_km: d };
    }).filter((s) => s._lat != null && s._lon != null)
      .sort((a, b) => a._dist_km - b._dist_km);
    result.substation = scored[0] || null;
    statuses.substation = scored[0] ? "live" : "empty";
  } else {
    result.substation = null;
    statuses.substation = "pending";
  }

  // Environmental constraints (designations + flood)
  const env = await safeJson(
    `/api/grid/environmental-constraints?lat=${lat}&lon=${lon}&radius_m=500`
  );
  const designFeats = [];
  if (env?.constraints && Array.isArray(env.constraints)) {
    env.constraints.forEach((c) => {
      if (c.geometry) designFeats.push({ type: "Feature", geometry: c.geometry, properties: c });
    });
  }
  result.designations = designFeats.length ? { type: "FeatureCollection", features: designFeats } : null;
  statuses.designations = env == null ? "pending" : (designFeats.length ? "live" : "empty");

  const floodFeats = [];
  if (env?.flood_zones && Array.isArray(env.flood_zones)) {
    env.flood_zones.forEach((f) => {
      if (f.geometry) floodFeats.push({ type: "Feature", geometry: f.geometry, properties: f });
    });
  }
  result.flood = floodFeats.length ? { type: "FeatureCollection", features: floodFeats } : null;
  statuses.flood = env == null ? "pending" : (floodFeats.length ? "live" : "empty");

  // Land use (GeeFlow)
  const lu = await safeJson(`/api/geeflow/landuse?lat=${lat}&lon=${lon}&radius_m=500`);
  result.landuse = lu && lu.geojson ? lu.geojson : null;
  statuses.landuse = lu ? (lu.geojson ? "live" : "empty") : "pending";

  // Adjacent queue projects
  const q = await safeJson(`/api/grid/queue-depth/near?lat=${lat}&lon=${lon}&radius_km=10`);
  if (Array.isArray(q) && q.length) {
    result.queue = q;
    statuses.queue = "live";
  } else if (q?.features) {
    result.queue = q.features;
    statuses.queue = q.features.length ? "live" : "empty";
  } else {
    result.queue = null;
    statuses.queue = "pending";
  }

  // Slope — no endpoint wired
  statuses.slope = "pending";

  return result;
}
