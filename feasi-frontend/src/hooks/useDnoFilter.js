/**
 * useDnoFilter — DNO licence-area filter store (Task #19).
 *
 * Zustand is not installed in this project; we reuse the vanilla-store +
 * useSyncExternalStore pattern established by useMapTime.js so callers look
 * identical.
 *
 * State shape
 * ───────────
 *   activeDnos   — Set<slug>          Which DNO top-level slugs are active.
 *                                     A filter of ∅ means "show all"
 *                                     (equivalent to the "All" pill).
 *   mode         — 'all' | 'filter' | 'solo'
 *                                     UX hint for the pill rail; derived but
 *                                     stored so shift-click multi-select and
 *                                     double-click solo stay distinguishable.
 *   lastProject  — string | null      Project id that inferFromProject last
 *                                     resolved — used to avoid redundant
 *                                     lookups when a project loads twice.
 *
 * Actions
 * ───────
 *   setActive(slugs)          Replace the set. Accepts array/Set.
 *   toggle(slug)              Shift-click semantics — flip one slug in/out.
 *   clear()                   Back to "all".
 *   solo(slug)                Double-click — active = {slug}, mode='solo'.
 *   inferFromProject(pid)     GET /api/projects/{pid} and pick the DNO from
 *                             either an explicit `dno_slug` or the site
 *                             centroid via /api/dno/by-point.
 *
 * Persistence
 * ───────────
 *   The active set + mode are persisted to localStorage (per-origin, survives
 *   reload) under ``princeps:dno-filter:v1``.
 */

import { useSyncExternalStore, useCallback } from "react";

// ── Known top-level DNO slugs (used by setActive() + pill rail) ─────────────
export const DNO_SLUGS = Object.freeze([
  "ukpn",
  "ssen",
  "spen",
  "nged",
  "npg",
  "enwl",
  "nie",
]);

// localStorage key (bump v-suffix if the shape changes)
const LS_KEY = "princeps:dno-filter:v1";

// ── Persistence helpers ─────────────────────────────────────────────────────
function readLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const slugs = Array.isArray(parsed.activeDnos) ? parsed.activeDnos : [];
    const mode  = ["all", "filter", "solo"].includes(parsed.mode) ? parsed.mode : "all";
    return { activeDnos: new Set(slugs.filter((s) => DNO_SLUGS.includes(s))), mode };
  } catch {
    return null;
  }
}

function writeLocal(next) {
  try {
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({
        activeDnos: Array.from(next.activeDnos || []),
        mode:       next.mode,
      }),
    );
  } catch {
    /* quota / private mode — silent */
  }
}

// ── Store (vanilla, outside React) ──────────────────────────────────────────
const _bootstrap = readLocal();

let state = {
  activeDnos:  _bootstrap?.activeDnos ?? new Set(),
  mode:        _bootstrap?.mode       ?? "all",
  lastProject: null,
};

const listeners = new Set();
function emit() { for (const l of listeners) l(); }

function setState(patch) {
  state = { ...state, ...patch };
  writeLocal(state);
  emit();
}

// ── Pure helpers ────────────────────────────────────────────────────────────
function _normaliseSlugs(input) {
  const src = input instanceof Set ? Array.from(input) : Array.isArray(input) ? input : [];
  const cleaned = src
    .filter((s) => typeof s === "string")
    .map((s) => s.toLowerCase().trim())
    .filter((s) => DNO_SLUGS.includes(s));
  return new Set(cleaned);
}

function _deriveMode(activeDnos, previousMode) {
  if (activeDnos.size === 0)  return "all";
  if (activeDnos.size === 1 && previousMode === "solo") return "solo";
  return "filter";
}

// ── Public vanilla API ──────────────────────────────────────────────────────
export const dnoFilterStore = {
  getState: () => state,
  subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },

  setActive: (slugs) => {
    const nextActive = _normaliseSlugs(slugs);
    const mode = _deriveMode(nextActive, state.mode === "solo" ? "filter" : state.mode);
    setState({ activeDnos: nextActive, mode });
  },

  toggle: (slug) => {
    if (!DNO_SLUGS.includes(slug)) return;
    const nextActive = new Set(state.activeDnos);
    if (nextActive.has(slug)) nextActive.delete(slug);
    else                      nextActive.add(slug);
    const mode = _deriveMode(nextActive, "filter");
    setState({ activeDnos: nextActive, mode });
  },

  clear: () => {
    if (state.activeDnos.size === 0 && state.mode === "all") return;
    setState({ activeDnos: new Set(), mode: "all" });
  },

  solo: (slug) => {
    if (!DNO_SLUGS.includes(slug)) return;
    setState({ activeDnos: new Set([slug]), mode: "solo" });
  },

  /**
   * inferFromProject — ask the backend which DNO hosts this project.
   *
   * Strategy:
   *   1. GET /api/projects/{id}. If response has `dno_slug` or a nested site
   *      with `dno_slug`, snap a top-level slug from that.
   *   2. Else if the project has lng/lat, call GET /api/dno/by-point?lng&lat
   *      and snap from that.
   *   3. Update store in 'solo' mode so the map zooms onto just that DNO.
   *
   * Gracefully no-ops if either endpoint 404s or the project has no usable
   * geometry — Princeps has a lot of draft projects without sites.
   */
  inferFromProject: async (projectId) => {
    if (!projectId || state.lastProject === projectId) return;
    setState({ lastProject: projectId });

    // Resolve via top-level slug metadata first.
    let slug = null;
    let lng = null;
    let lat = null;
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
        credentials: "include",
      });
      if (res.ok) {
        const j = await res.json();
        slug = j?.dno_slug || j?.site?.dno_slug || null;
        lng  = Number.isFinite(j?.lng) ? j.lng : j?.site?.lng ?? null;
        lat  = Number.isFinite(j?.lat) ? j.lat : j?.site?.lat ?? null;
      }
    } catch { /* network — ignore, fall through */ }

    // Normalise nested slug to a top-level DNO slug.
    const _toTopLevel = (s) => {
      if (!s) return null;
      const base = s.toLowerCase().split("-")[0];
      return DNO_SLUGS.includes(base) ? base : null;
    };
    const topLevel = _toTopLevel(slug);
    if (topLevel) {
      dnoFilterStore.solo(topLevel);
      return;
    }

    // Fall back to point lookup.
    if (Number.isFinite(lng) && Number.isFinite(lat)) {
      try {
        const res = await fetch(
          `/api/dno/by-point?lng=${encodeURIComponent(lng)}&lat=${encodeURIComponent(lat)}`,
          { credentials: "include" },
        );
        if (res.ok) {
          const j = await res.json();
          const byPoint = _toTopLevel(j?.dno_slug);
          if (byPoint) dnoFilterStore.solo(byPoint);
        }
      } catch { /* ignore */ }
    }
  },
};

// ── React hook ──────────────────────────────────────────────────────────────
export function useDnoFilter() {
  const snap = useSyncExternalStore(
    dnoFilterStore.subscribe,
    dnoFilterStore.getState,
    dnoFilterStore.getState,
  );

  const setActive = useCallback((s) => dnoFilterStore.setActive(s), []);
  const toggle    = useCallback((s) => dnoFilterStore.toggle(s), []);
  const clear     = useCallback(() => dnoFilterStore.clear(), []);
  const solo      = useCallback((s) => dnoFilterStore.solo(s), []);
  const inferFromProject = useCallback(
    (id) => dnoFilterStore.inferFromProject(id),
    [],
  );

  return {
    activeDnos: snap.activeDnos,
    mode:       snap.mode,
    lastProject: snap.lastProject,
    setActive,
    toggle,
    clear,
    solo,
    inferFromProject,
  };
}

export default useDnoFilter;
