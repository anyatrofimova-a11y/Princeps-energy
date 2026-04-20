/**
 * dcContext — aggregates the various data fetchers needed to layer real
 * site context on top of the DC Twin.
 *
 * Primary endpoints (real DB data):
 *   - /api/grid/nearest-substation
 *   - /api/grid/substation/{id}/detail
 *   - /api/environment/constraints
 *   - /api/design/buildable-mask
 *   - /api/ea/flood/{2|3}
 *   - /grid/osm/substations
 *
 * Utility layers (BOT-B3, 2026-04-20) — previously browser-direct Overpass:
 *   - /api/utilities/waterways  — rivers / canals / streams
 *   - /api/utilities/roads      — highway network with access_class
 *   - /api/utilities/gas        — gas pipelines
 *   - /api/utilities/fibre      — carrier POP seed
 *
 * The nearest-X helpers below prefer the backend routes. If backend returns
 * no features (empty DB for that bbox → lazy ingest fires server-side), they
 * fall back to a direct Overpass browser call so the twin still renders
 * something immediately. Each returned object carries a `_source` and a
 * `fallbacks: [...]` list so we can surface observability (e.g. "fibre POP
 * is stubbed — not a real carrier map") in the UI.
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

/* ── Utility layers — backend-first, Overpass as fallback ─────────────── */

const _bboxStr = (lat, lon, radiusM) => {
  // Convert a (lat, lon, radiusM) ask into a coarse WGS84 bbox.
  const dLat = radiusM / 111_320;
  const dLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
  const w = lon - dLon, e = lon + dLon;
  const s = lat - dLat, n = lat + dLat;
  return `${w},${s},${e},${n}`;
};

const _distMeters = (lat, lon, lat2, lon2) => {
  const dLat = (lat2 - lat) * 111_320;
  const dLon = (lon2 - lon) * 111_320 * Math.cos((lat * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
};

const _featureLineNearest = (feature, lat, lon) => {
  const geom = feature?.geometry;
  if (!geom) return null;
  const rings = geom.type === "MultiLineString" ? geom.coordinates : [geom.coordinates || []];
  let best = null;
  for (const ring of rings) {
    for (const [lo, la] of ring || []) {
      const d = _distMeters(lat, lon, la, lo);
      if (!best || d < best.distanceM) best = { distanceM: d, lat: la, lon: lo };
    }
  }
  return best;
};

const _overpassQuery = async (body) => {
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

/** Nearest waterway (river/canal/stream). Backend first, Overpass fallback. */
export async function fetchNearestWaterway(lat, lon, radiusM = 5000) {
  const fallbacks = [];

  // 1) Backend /api/utilities/waterways
  const fc = await safeJson(
    `${API_BASE}/api/utilities/waterways?bbox=${encodeURIComponent(_bboxStr(lat, lon, radiusM))}&limit=1000`
  );
  if (fc?.features?.length) {
    let best = null;
    for (const f of fc.features) {
      const near = _featureLineNearest(f, lat, lon);
      if (near && (!best || near.distanceM < best.distanceM)) {
        best = {
          ...near,
          name: f.properties?.name || f.properties?.waterway || "unnamed waterway",
          waterway: f.properties?.waterway || null,
          osmId: f.properties?.osm_id || f.id,
        };
      }
    }
    if (best) return { ...best, _source: "backend/utility_waterways", fallbacks };
  }
  fallbacks.push("backend:empty");

  // 2) Overpass direct (legacy)
  const query = `
    [out:json][timeout:15];
    (
      way(around:${radiusM},${lat},${lon})["waterway"~"river|canal|stream"];
    );
    out geom 12;
  `;
  const data = await _overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const d = _distMeters(lat, lon, pt.lat, pt.lon);
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
  return best
    ? { ...best, _heuristic: true, _source: "overpass", fallbacks: [...fallbacks, "overpass"] }
    : null;
}

/** Nearest fibre POP. Backend carrier seed first, Overpass city fallback. */
export async function fetchNearestFiberPOP(lat, lon, radiusM = 25000) {
  const fallbacks = [];

  // 1) Backend /api/utilities/fibre
  const fc = await safeJson(
    `${API_BASE}/api/utilities/fibre?bbox=${encodeURIComponent(_bboxStr(lat, lon, radiusM))}&limit=50`
  );
  if (fc?.features?.length) {
    let best = null;
    for (const f of fc.features) {
      const [lo, la] = f.geometry?.coordinates || [];
      if (lo == null || la == null) continue;
      const d = _distMeters(lat, lon, la, lo);
      if (!best || d < best.distanceM) {
        best = {
          distanceM: d,
          lat: la,
          lon: lo,
          name: f.properties?.name || "POP",
          carrier: f.properties?.carrier || null,
          popClass: f.properties?.pop_class || null,
          osmId: null,
        };
      }
    }
    if (best) {
      return {
        ...best,
        _source: "backend/fibre_pops",
        _stubbed: fc._stubbed === true,
        _note: fc._note,
        fallbacks,
      };
    }
  }
  fallbacks.push("backend:empty");

  // 2) Overpass fallback (nearest town/city — conservative fibre proxy)
  const query = `
    [out:json][timeout:15];
    (
      node(around:${radiusM},${lat},${lon})["place"~"city|town"]["name"];
    );
    out 8;
  `;
  const data = await _overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    const d = _distMeters(lat, lon, el.lat, el.lon);
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
        _note: "No backend POP in radius — using nearest city centre as a conservative proxy.",
        fallbacks: [...fallbacks, "overpass"],
      }
    : null;
}

/** Nearest gas main. Backend first, Overpass fallback. */
export async function fetchNearestGasMain(lat, lon, radiusM = 5000) {
  const fallbacks = [];

  const fc = await safeJson(
    `${API_BASE}/api/utilities/gas?bbox=${encodeURIComponent(_bboxStr(lat, lon, radiusM))}&limit=500`
  );
  if (fc?.features?.length) {
    let best = null;
    for (const f of fc.features) {
      const near = _featureLineNearest(f, lat, lon);
      if (near && (!best || near.distanceM < best.distanceM)) {
        best = {
          ...near,
          name: f.properties?.name || "Gas pipeline",
          operator: f.properties?.operator || null,
          osmId: f.properties?.osm_id || f.id,
        };
      }
    }
    if (best) return { ...best, _source: "backend/utility_gas_pipelines", fallbacks };
  }
  fallbacks.push("backend:empty");

  const query = `
    [out:json][timeout:15];
    (
      way(around:${radiusM},${lat},${lon})["man_made"="pipeline"]["substance"="gas"];
    );
    out geom 10;
  `;
  const data = await _overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const d = _distMeters(lat, lon, pt.lat, pt.lon);
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
  return best
    ? {
        ...best,
        _heuristic: true,
        _source: "overpass",
        fallbacks: [...fallbacks, "overpass"],
      }
    : null;
}

/** Nearest road. Backend first, Overpass fallback. */
export async function fetchNearestRoad(lat, lon, radiusM = 800) {
  const fallbacks = [];

  const fc = await safeJson(
    `${API_BASE}/api/utilities/roads?bbox=${encodeURIComponent(_bboxStr(lat, lon, radiusM))}&limit=500`
  );
  if (fc?.features?.length) {
    let best = null;
    for (const f of fc.features) {
      const near = _featureLineNearest(f, lat, lon);
      if (near && (!best || near.distanceM < best.distanceM)) {
        best = {
          ...near,
          name: f.properties?.name || f.properties?.ref || "road",
          highway: f.properties?.highway || null,
          accessClass: f.properties?.access_class || null,
          osmId: f.properties?.osm_id || f.id,
        };
      }
    }
    if (best) return { ...best, _source: "backend/utility_roads", fallbacks };
  }
  fallbacks.push("backend:empty");

  const query = `
    [out:json][timeout:10];
    (
      way(around:${radiusM},${lat},${lon})["highway"~"primary|secondary|tertiary|unclassified|residential|service"];
    );
    out geom 6;
  `;
  const data = await _overpassQuery(query);
  if (!data?.elements?.length) return null;
  let best = null;
  for (const el of data.elements) {
    if (!el.geometry?.length) continue;
    for (const pt of el.geometry) {
      const d = _distMeters(lat, lon, pt.lat, pt.lon);
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
  return best
    ? {
        ...best,
        _heuristic: true,
        _source: "overpass",
        fallbacks: [...fallbacks, "overpass"],
      }
    : null;
}
