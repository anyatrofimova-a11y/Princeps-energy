/**
 * useMapTime — time scrubber store for the Princeps map.
 *
 * Zustand is NOT installed in this project, so we implement a zustand-like
 * global store using React's useSyncExternalStore + a vanilla pub/sub store.
 * The shape mirrors what a Zustand hook would return so call sites can be
 * swapped later with zero churn.
 *
 * State:
 *   asOf         — ISO date string (yyyy-mm-dd)
 *   isPlaying    — boolean
 *   speed        — playback multiplier (0.5 | 1 | 2 | 4)
 *   range        — { start, end } hard bounds for the scrubber
 *   fesPathway   — one of the 4 FES 2024 scenarios
 *
 * Actions:
 *   setAsOf(iso)
 *   play() / pause() / toggle()
 *   setSpeed(n)
 *   setFesPathway(name)
 *
 * Persistence:
 *   `asOf` + `fesPathway` are persisted to sessionStorage (per-tab).
 */

import { useSyncExternalStore, useCallback } from "react";

// ─── Constants ───────────────────────────────────────────────────────────────
export const TIME_RANGE = Object.freeze({
  start: "2020-01-01",
  end:   "2050-12-31",
});

export const FES_PATHWAYS = Object.freeze([
  "Leading the Way",
  "Consumer Transformation",
  "System Transformation",
  "Falling Short",
]);

export const PLAYBACK_SPEEDS = Object.freeze([0.5, 1, 2, 4]);

const SS_KEY_ASOF     = "princeps:map:asOf";
const SS_KEY_PATHWAY  = "princeps:map:fesPathway";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function todayIso() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function clampIso(iso) {
  if (!iso) return todayIso();
  if (iso < TIME_RANGE.start) return TIME_RANGE.start;
  if (iso > TIME_RANGE.end)   return TIME_RANGE.end;
  return iso;
}

function readSession(key, fallback) {
  try {
    const v = sessionStorage.getItem(key);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

function writeSession(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* ignore quota/private */ }
}

// ─── Store (vanilla, outside React) ──────────────────────────────────────────
const DEFAULT_ASOF_TODAY = clampIso(todayIso());

let state = {
  asOf:       clampIso(readSession(SS_KEY_ASOF, DEFAULT_ASOF_TODAY)),
  isPlaying:  false,
  speed:      1,
  range:      TIME_RANGE,
  fesPathway: readSession(SS_KEY_PATHWAY, FES_PATHWAYS[1]),
};

const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

function setState(patch) {
  state = { ...state, ...patch };
  emit();
}

// ─── Public vanilla API (useful outside React too) ───────────────────────────
export const mapTimeStore = {
  getState: () => state,
  subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  setAsOf: (iso) => {
    const next = clampIso(iso);
    if (next === state.asOf) return;
    writeSession(SS_KEY_ASOF, next);
    setState({ asOf: next });
  },
  play:  () => { if (!state.isPlaying) setState({ isPlaying: true }); },
  pause: () => { if (state.isPlaying)  setState({ isPlaying: false }); },
  toggle: () => setState({ isPlaying: !state.isPlaying }),
  setSpeed: (n) => {
    const s = PLAYBACK_SPEEDS.includes(n) ? n : 1;
    if (s !== state.speed) setState({ speed: s });
  },
  setFesPathway: (name) => {
    if (!FES_PATHWAYS.includes(name) || name === state.fesPathway) return;
    writeSession(SS_KEY_PATHWAY, name);
    setState({ fesPathway: name });
  },
};

// ─── React hook ──────────────────────────────────────────────────────────────
/**
 * useMapTime — subscribe to the scrubber store.
 * Returns the current slice plus stable action callbacks.
 */
export function useMapTime() {
  const snap = useSyncExternalStore(
    mapTimeStore.subscribe,
    mapTimeStore.getState,
    mapTimeStore.getState,
  );

  const setAsOf        = useCallback((iso) => mapTimeStore.setAsOf(iso), []);
  const play           = useCallback(() => mapTimeStore.play(), []);
  const pause          = useCallback(() => mapTimeStore.pause(), []);
  const toggle         = useCallback(() => mapTimeStore.toggle(), []);
  const setSpeed       = useCallback((n) => mapTimeStore.setSpeed(n), []);
  const setFesPathway  = useCallback((p) => mapTimeStore.setFesPathway(p), []);

  return {
    asOf:       snap.asOf,
    isPlaying:  snap.isPlaying,
    speed:      snap.speed,
    range:      snap.range,
    fesPathway: snap.fesPathway,
    setAsOf,
    play,
    pause,
    toggle,
    setSpeed,
    setFesPathway,
  };
}

// Convenience: read just the current date without subscribing.
export function getCurrentAsOf() {
  return state.asOf;
}

export default useMapTime;
