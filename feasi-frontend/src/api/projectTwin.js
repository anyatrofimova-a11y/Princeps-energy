/**
 * projectTwin.js — client for the Assess-tab project twin context.
 *
 * Live mode  : GET /api/project/{id}/twin-context
 * Mock mode  : VITE_MOCK_TWIN (default "true") — returns a fixture from
 *              src/data/mock-project-twin.json based on projectId lookup.
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
 * All failures are swallowed — callers get `null` and render the empty state.
 */

import mockFixture from "../data/mock-project-twin.json";

const MOCK_FLAG = (import.meta.env.VITE_MOCK_TWIN ?? "true").toString().toLowerCase();
const USE_MOCK = MOCK_FLAG !== "false" && MOCK_FLAG !== "0";

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

function firstMockKey() {
  const keys = Object.keys(mockFixture || {});
  return keys.length ? keys[0] : null;
}

function pickMock(projectId) {
  if (!mockFixture) return null;
  if (projectId && mockFixture[projectId]) return mockFixture[projectId];
  const fallbackKey = firstMockKey();
  return fallbackKey ? mockFixture[fallbackKey] : null;
}

/**
 * Fetch project twin context. Returns null on error.
 * @param {string} projectId
 * @param {{ polygon_wkt?: string, tech?: string, capacity_mw?: number }} overrides
 */
export async function fetchProjectTwinContext(projectId, overrides = {}) {
  const overridePolygon = parseWktPolygon(overrides.polygon_wkt);

  if (USE_MOCK) {
    const fixture = pickMock(projectId);
    if (!fixture) return null;
    return {
      ...fixture,
      project_id: projectId || fixture.project_id,
      polygon: overridePolygon || fixture.polygon,
      tech: overrides.tech || fixture.tech,
      capacity_mw: Number.isFinite(overrides.capacity_mw) ? overrides.capacity_mw : fixture.capacity_mw,
    };
  }

  if (!projectId) return null;
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

/** True when running against mock fixture data. */
export const isMockMode = USE_MOCK;

/** Exposed for tests / debugging. */
export const __mockFixture = mockFixture;
