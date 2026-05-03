/**
 * projectTwin.js — client for the Assess-tab project twin context.
 *
 * Live backend: GET /api/project/{id}/twin-context
 *   (mock-project-twin.json removed 2026-04-29)
 *
 * Response shape:
 *   {
 *     polygon:            GeoJSON Feature<Polygon>,
 *     poc_substation:     { id, name, voltage_kv, lon, lat, headroom_mw, distance_km },
 *     nearest_grid_lines: [{ id, voltage_kv, geometry:LineString }, …],
 *     terrain_bbox:       [west, south, east, north],
 *     tech:               "solar" | "wind" | "bess" | "dc",
 *     capacity_mw:        number
 *   }
 *
 * All failures swallowed — callers get `null` and render the empty state.
 */

function parseWktPolygon(wkt) {
  if (!wkt || typeof wkt !== "string") return null;
  const m = wkt.match(/POLYGON\s*\(\(([^)]+)\)\)/i);
  if (!m) return null;
  const coords = m[1]
    .split(",")
    .map((pair) => pair.trim().split(/\s+/).map(Number))
    .filter((p) => p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]));
  if (!coords.length) return null;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [coords] },
  };
}

export async function fetchProjectTwinContext(projectId, overrides = {}) {
  if (!projectId) return null;
  const overridePolygon = parseWktPolygon(overrides.polygon_wkt);
  try {
    const res = await fetch(`/api/project/${encodeURIComponent(projectId)}/twin-context`);
    if (!res.ok) return null;
    const data = await res.json();
    return {
      ...data,
      project_id: projectId,
      polygon: overridePolygon || data.polygon,
      tech: overrides.tech || data.tech,
      capacity_mw: Number.isFinite(overrides.capacity_mw) ? overrides.capacity_mw : data.capacity_mw,
    };
  } catch {
    return null;
  }
}

export const isMockMode = false;
