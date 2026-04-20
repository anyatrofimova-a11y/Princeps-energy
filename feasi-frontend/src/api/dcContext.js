/**
 * dcContext — aggregates the various data fetchers needed to layer real
 * site context on top of the DC Twin.
 *
 * Sources wired:
 *   - /api/grid/nearest-substation         (POC selection + headroom)
 *   - /api/grid/substation/{id}/detail     (enriched sub detail for drawer)
 *   - /api/environment/constraints         (SSSI / AONB / flood / heritage)
 *   - /api/design/buildable-mask           (FC of restricted-area polygons)
 *   - /api/ea/flood/{2|3}                  (EA Flood Zones where ingested)
 *   - /grid/osm/substations                (bbox ambient sub context)
 *
 * Heuristic fallbacks (flagged `_heuristic: true` on the returned block):
 *   - Fiber route  — no real carrier map in backend. Heuristic: nearest
 *                    settlement from Overpass API (place=town|city) within
 *                    25 km. Flagged as follow-up.
 *   - Water intake — no OSM waterway endpoint in backend. Heuristic: direct
 *                    Overpass API call for waterway=river|canal nearest to
 *                    lat/lon. Flagged as follow-up.
 *   - Gas main     — no ingester anywhere. Heuristic: Overpass API for
 *                    man_made=pipeline with substance=gas in bbox, else None.
 *                    Flagged as follow-up.
 *
 * All fetchers are defensive — any 404/500 returns `null` rather than throw.
 */

const API_BASE = import.meta.env.VITE_API_BASE || "";
const OVERPASS_URL = "https://overpass-api.de/api/interpreter";

const safeJson = async (url, opts = {}) => {
  try {
    const res = await fetch(url, opts);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
};

/* ── Primary endpoints (real DB data) ─────────────────────────────────── */

export async function fetchNearestSubstation(lat, lon, availableFraction = 0.3) {
  return safeJson(
    `${API_BASE}/api/grid/nearest-substation?lat=${lat}&lon=${lon}&available_fraction=${availableFraction}`
  );
}

export async function fetchSubstationDetail(id) {
  if (id == null) return null;
  return safeJson(`${API_BASE}/api/grid/substation/${encodeURIComponent(id)}/detail`);
}

export async function fetchEnvironmentConstraints(lat, lon, radiusM = 2000) {
  return safeJson(
    `${API_BASE}/api/environment/constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`
  );
}

export async function fetchBuildableMask(lat, lon, radiusM = 1500) {
  return safeJson(
    `${API_BASE}/api/design/buildable-mask?lat=${lat}&lon=${lon}&radius_m=${radiusM}`
  );
}

export async function fetchFloodZones(bbox, zone = 3) {
  // bbox: [west, south, east, north]
  if (!bbox || bbox.length !== 4) return null;
  const bboxStr = bbox.join(",");
  return safeJson(`${API_BASE}/api/ea/flood/${zone}?bbox=${encodeURIComponent(bboxStr)}`);
}

export async function fetchOsmSubstations(bbox) {
  if (!bbox || bbox.length !== 4) return null;
  const [w, s, e, n] = bbox;
  return safeJson(`${API_BASE}/grid/osm/substations?west=${w}&south=${s}&east=${e}&north=${n}`);
}

/* ── Heuristic fallbacks (flagged as follow-up) ───────────────────────── */

const overpassQuery = async (body) => {
  try {
    const res = await fetch(OVERPASS_URL, {
      method: "POST",
      body,
      headers: { "Content-Type": "text/plain" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
};

/** Nearest waterway (river/canal/stream) — Overpass, 5 km search radius. */
export async function fetchNearestWaterway(lat, lon, radiusM = 5000) {
  const query = `
    [out:json][timeout:15];
    (
      way(around:${radiusM},${lat},${lon})["waterway"~"river|canal|stream"];
    );
    out geom 12;
  `;
  const data = await overpassQuery(query);
  if (!data?.elements?.length) return null;

  // Pick the element with the closest point to (lat, lon) as the "intake".
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const dLat = (pt.lat - lat) * 111_320;
      const dLon = (pt.lon - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
      const d = Math.hypot(dLat, dLon);
      if (!best || d < best.distanceM) {
        best = {
          distanceM: d,
          lat: pt.lat,
          lon: pt.lon,
          name: el.tags?.name || el.tags?.waterway || "unnamed waterway",
          waterway: el.tags?.waterway || null,
          osmId: el.id,
        };
      }
    }
  }
  return best ? { ...best, _heuristic: true, _source: "overpass" } : null;
}

/** Nearest settlement centroid — heuristic proxy for "fiber meet-me-room".
 *  Carrier-neutral data centre POPs cluster near large towns/cities in the
 *  UK; a 25 km search for place=city|town is a conservative fallback until
 *  a real carrier-map ingester lands.
 */
export async function fetchNearestFiberPOP(lat, lon, radiusM = 25000) {
  const query = `
    [out:json][timeout:15];
    (
      node(around:${radiusM},${lat},${lon})["place"~"city|town"]["name"];
    );
    out 8;
  `;
  const data = await overpassQuery(query);
  if (!data?.elements?.length) return null;

  let best = null;
  for (const el of data.elements) {
    const dLat = (el.lat - lat) * 111_320;
    const dLon = (el.lon - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
    const d = Math.hypot(dLat, dLon);
    if (!best || d < best.distanceM) {
      best = {
        distanceM: d,
        lat: el.lat,
        lon: el.lon,
        name: el.tags?.name || "City centre",
        place: el.tags?.place || null,
        osmId: el.id,
      };
    }
  }
  return best
    ? {
        ...best,
        _heuristic: true,
        _source: "overpass/place-as-fiber-proxy",
        _note: "No carrier meet-me-room dataset ingested — using nearest city centre as a conservative proxy for the fibre POP.",
      }
    : null;
}

/** Nearest gas main — Overpass man_made=pipeline + substance=gas. Coverage
 *  in OSM is patchy; often returns null, in which case the overlay renders
 *  an "unavailable" pill rather than a fake line. */
export async function fetchNearestGasMain(lat, lon, radiusM = 5000) {
  const query = `
    [out:json][timeout:15];
    (
      way(around:${radiusM},${lat},${lon})["man_made"="pipeline"]["substance"="gas"];
    );
    out geom 10;
  `;
  const data = await overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const dLat = (pt.lat - lat) * 111_320;
      const dLon = (pt.lon - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
      const d = Math.hypot(dLat, dLon);
      if (!best || d < best.distanceM) {
        best = {
          distanceM: d,
          lat: pt.lat,
          lon: pt.lon,
          name: el.tags?.name || "Gas pipeline",
          operator: el.tags?.operator || null,
          osmId: el.id,
        };
      }
    }
  }
  return best ? { ...best, _heuristic: true, _source: "overpass" } : null;
}

/** Nearest road — access road heuristic. */
export async function fetchNearestRoad(lat, lon, radiusM = 800) {
  const query = `
    [out:json][timeout:10];
    (
      way(around:${radiusM},${lat},${lon})["highway"~"primary|secondary|tertiary|unclassified|residential|service"];
    );
    out geom 6;
  `;
  const data = await overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const dLat = (pt.lat - lat) * 111_320;
      const dLon = (pt.lon - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
      const d = Math.hypot(dLat, dLon);
      if (!best || d < best.distanceM) {
        best = {
          distanceM: d,
          lat: pt.lat,
          lon: pt.lon,
          name: el.tags?.name || el.tags?.ref || "road",
          highway: el.tags?.highway || null,
          osmId: el.id,
        };
      }
    }
  }
  return best ? { ...best, _heuristic: true, _source: "overpass" } : null;
}
