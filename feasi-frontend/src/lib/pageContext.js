/**
 * pageContext.js — one-place collector for the page_context block that the
 * ChatRail ships with every message to the backend.
 *
 * Contract (keep in sync with app/chat.py build_system_prompt):
 *   {
 *     workspace,           // "home" | "analyse" | …   (from WorkspaceContext)
 *     viewMode,            // "map" | "projects" | …   (from WorkspaceContext)
 *     route,               // window.location.pathname
 *     url_params,          // { project, parcel, … }  (allow-listed)
 *     project: {           // null when no project is loaded
 *       id, name, lat, lon, tech, capacity_mw, stage, dno, tec_mw,
 *     } | null,
 *     lifecycle_tab,       // "overview" | "discover" | "assess" | …
 *     selected_asset: {    // window.__gridGraphHover | picked_location | null
 *       kind, id, name, lat, lon
 *     } | null,
 *     pathway,             // FES pathway (useMapTime)
 *     as_of_year,          // int year extracted from useMapTime.asOf
 *   }
 *
 * The collector is a pure function — it reads whatever state you pass in and
 * layers globals (window.__gridGraphHover, URL params). Callers own wiring up
 * the reactive sources (WorkspaceContext, useMapTime, event listeners).
 */

const URL_PARAM_ALLOWLIST = [
  "project", "parcel", "dno", "tab", "subtab",
  "portfolio", "candidate", "pathway", "asof",
];

/**
 * Extract allow-listed query params from the current URL.
 * Keeps the payload tight and stops arbitrary tracking params leaking to the
 * LLM (see COUNCIL-CH appendix note).
 */
export function collectUrlParams() {
  try {
    const sp = new URLSearchParams(window.location.search);
    const out = {};
    for (const k of URL_PARAM_ALLOWLIST) {
      const v = sp.get(k);
      if (v) out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * Pull the currently-selected-asset hint that other panels (GridTwin hover,
 * DC twin click-to-inspect) stash on window. Falls back to null.
 */
export function readSelectedAsset() {
  try {
    const h = window.__gridGraphHover || window.__princepsSelectedAsset || null;
    if (!h) return null;
    return {
      kind: h.kind || h.type || "unknown",
      id: h.id || h.substation_id || h.asset_id || null,
      name: h.name || h.label || null,
      lat: h.lat ?? null,
      lon: h.lon ?? null,
    };
  } catch {
    return null;
  }
}

/**
 * Extract year from an ISO date string (YYYY-MM-DD) — used by as_of_year so
 * the backend doesn't have to parse the scrubber date.
 */
export function yearFromIso(iso) {
  if (!iso || typeof iso !== "string") return null;
  const m = iso.match(/^(\d{4})/);
  return m ? parseInt(m[1], 10) : null;
}

/**
 * Normalise a project record (from /api/v1/projects/{id}) into the wire
 * subset we ship with every chat turn. Defensive about shape drift: handles
 * UK/US lat-lon aliases and deep metadata.* (stage/dno/tec live on different
 * rows depending on ingestion path — see projects.py::_row_to_dict).
 */
export function normaliseProject(p) {
  if (!p) return null;
  const id = p.project_id || p.id || null;
  if (!id) return null;
  const meta = p.metadata || {};
  return {
    id,
    name: p.name || null,
    lat: p.lat ?? p.latitude ?? null,
    lon: p.lon ?? p.longitude ?? null,
    tech: p.technology || p.tech || null,
    capacity_mw: p.capacity_mw ?? p.capacity ?? null,
    stage: p.stage || null,
    dno: p.dno || meta.dno || null,
    tec_mw: p.tec_mw ?? meta.tec_mw ?? meta.tec_capacity_mw ?? null,
    verdict: p.verdict || null,
  };
}

/**
 * Build the full page_context envelope. Pure — all reactive state is passed
 * in so the caller can wire it to whatever hooks are in scope.
 */
export function buildPageContext({
  workspace = null,
  viewMode = null,
  project = null,
  lifecycleTab = null,
  pathway = null,
  asOf = null,
} = {}) {
  return {
    workspace,
    viewMode,
    route: typeof window !== "undefined" ? window.location.pathname : "/",
    url_params: collectUrlParams(),
    project: normaliseProject(project),
    lifecycle_tab: lifecycleTab,
    selected_asset: readSelectedAsset(),
    pathway,
    as_of_year: yearFromIso(asOf),
  };
}

export default buildPageContext;
