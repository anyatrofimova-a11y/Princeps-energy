/**
 * Princeps 3D Twin v1 — Zustand store
 * ----------------------------------------------------------------------
 * Single source of truth for TwinRoot shell:
 *   - view mode (plan / oblique / construction / drone)
 *   - selection
 *   - active tool (measure / annotate / section / sun / snapshot)
 *   - layer visibility toggles
 *   - sun date (for ShadowPolygonLayer)
 *   - construction timeMonth (0..24)
 *   - annotations
 *
 * Persistence: localStorage under `princeps.twin.{projectId}.{key}`.
 * `projectId` is injected via `bindStoreToProject(projectId)` called by
 * TwinRoot on mount; defaults to 'default' so the store works standalone.
 *
 * Sibling agents in v2 will extend this (measurement tool state, scene
 * graph, annotation schemas, PBR/shadow intensity, etc.). Keep this file
 * additive — do not rename existing keys.
 */

import { create } from 'zustand';

// ------------------------------------------------------------------
// Persistence helpers
// ------------------------------------------------------------------

let CURRENT_PROJECT_ID = 'default';
const NAMESPACE = 'princeps.twin';

const storageKey = (key) => `${NAMESPACE}.${CURRENT_PROJECT_ID}.${key}`;

const readPersisted = (key, fallback) => {
  if (typeof window === 'undefined' || !window.localStorage) return fallback;
  try {
    const raw = window.localStorage.getItem(storageKey(key));
    if (raw == null) return fallback;
    return JSON.parse(raw);
  } catch (err) {
    console.warn('[twinStore] readPersisted failed', key, err);
    return fallback;
  }
};

const writePersisted = (key, value) => {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    window.localStorage.setItem(storageKey(key), JSON.stringify(value));
  } catch (err) {
    console.warn('[twinStore] writePersisted failed', key, err);
  }
};

// ------------------------------------------------------------------
// Defaults
// ------------------------------------------------------------------

const DEFAULT_LAYER_VISIBILITY = {
  site: true,
  assets: true,
  electrical: true,
  civil: true,
  grid: true,
  context: false,
  constraints: false,
  environment: false,
  overlays: false,
  weather: false,
};

const DEFAULT_VIEW_MODE = 'oblique';

// ISO string for sun date; Date objects don't survive JSON.stringify round-trip cleanly
const DEFAULT_SUN_DATE_ISO = new Date(2026, 5, 21, 12, 0, 0).toISOString(); // summer solstice noon

// ------------------------------------------------------------------
// Store
// ------------------------------------------------------------------

export const useTwinStore = create((set, get) => ({
  // ---- view mode ----
  viewMode: readPersisted('viewMode', DEFAULT_VIEW_MODE),
  setViewMode: (mode) => {
    if (!['plan', 'oblique', 'construction', 'drone'].includes(mode)) {
      console.warn('[twinStore] invalid viewMode', mode);
      return;
    }
    writePersisted('viewMode', mode);
    set({ viewMode: mode });
  },

  // ---- selection ----
  selectedAssetId: null,
  setSelected: (id) => set({ selectedAssetId: id }),
  clearSelection: () => set({ selectedAssetId: null }),

  // ---- active tool ----
  activeTool: null,
  setTool: (tool) => {
    const allowed = [null, 'measure', 'annotate', 'section', 'sun', 'snapshot'];
    if (!allowed.includes(tool)) {
      console.warn('[twinStore] invalid tool', tool);
      return;
    }
    set({ activeTool: tool });
  },

  // ---- layer visibility ----
  layerVisibility: {
    ...DEFAULT_LAYER_VISIBILITY,
    ...readPersisted('layerVisibility', {}),
  },
  toggleLayer: (layerKey) => {
    const current = get().layerVisibility;
    if (!(layerKey in current)) {
      console.warn('[twinStore] unknown layer', layerKey);
      return;
    }
    const next = { ...current, [layerKey]: !current[layerKey] };
    writePersisted('layerVisibility', next);
    set({ layerVisibility: next });
  },
  setLayer: (layerKey, visible) => {
    const current = get().layerVisibility;
    if (!(layerKey in current)) {
      console.warn('[twinStore] unknown layer', layerKey);
      return;
    }
    const next = { ...current, [layerKey]: Boolean(visible) };
    writePersisted('layerVisibility', next);
    set({ layerVisibility: next });
  },

  // ---- sun date (for ShadowPolygonLayer) ----
  sunDate: new Date(readPersisted('sunDateIso', DEFAULT_SUN_DATE_ISO)),
  setSunDate: (dateOrIso) => {
    const d = dateOrIso instanceof Date ? dateOrIso : new Date(dateOrIso);
    if (Number.isNaN(d.getTime())) {
      console.warn('[twinStore] invalid sunDate', dateOrIso);
      return;
    }
    writePersisted('sunDateIso', d.toISOString());
    set({ sunDate: d });
  },

  // ---- construction phase slider (months 0..24) ----
  timeMonth: readPersisted('timeMonth', 0),
  setTimeMonth: (month) => {
    const m = Math.max(0, Math.min(24, Math.round(month)));
    writePersisted('timeMonth', m);
    set({ timeMonth: m });
  },

  // ---- annotations ----
  annotations: readPersisted('annotations', []),
  addAnnotation: (annotation) => {
    if (!annotation || typeof annotation !== 'object') return;
    const id =
      annotation.id || `anno_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const next = [...get().annotations, { ...annotation, id, createdAt: Date.now() }];
    writePersisted('annotations', next);
    set({ annotations: next });
    return id;
  },
  removeAnnotation: (id) => {
    const next = get().annotations.filter((a) => a.id !== id);
    writePersisted('annotations', next);
    set({ annotations: next });
  },
}));

// ------------------------------------------------------------------
// Project scoping
// ------------------------------------------------------------------

/**
 * Rebind persistence namespace to a given project id and refresh
 * store fields from localStorage under the new namespace. Call once
 * from TwinRoot on mount (or whenever projectId changes).
 */
export function bindStoreToProject(projectId) {
  const pid = projectId && String(projectId).trim() ? String(projectId) : 'default';
  if (pid === CURRENT_PROJECT_ID) return;
  CURRENT_PROJECT_ID = pid;
  // re-hydrate persisted slices
  useTwinStore.setState({
    viewMode: readPersisted('viewMode', DEFAULT_VIEW_MODE),
    layerVisibility: {
      ...DEFAULT_LAYER_VISIBILITY,
      ...readPersisted('layerVisibility', {}),
    },
    sunDate: new Date(readPersisted('sunDateIso', DEFAULT_SUN_DATE_ISO)),
    timeMonth: readPersisted('timeMonth', 0),
    annotations: readPersisted('annotations', []),
  });
}

export function getBoundProjectId() {
  return CURRENT_PROJECT_ID;
}

export default useTwinStore;
