import { useCallback, useEffect, useMemo, useState } from "react";

/**
 * useProjectTwinLayers — stateful hook for the Assess-tab project twin.
 *
 *   { layers, toggleLayer, setAllLayers,
 *     cameraPreset, setCameraPreset,
 *     reset }
 *
 * Layer visibility + camera preset are persisted to localStorage, keyed per
 * project so that different projects don't overwrite each other's settings.
 */

export const LAYER_KEYS = [
  "satellite",       // Mapbox satellite-streets style flag (always-on indicator)
  "terrain",         // NASADEM terrain-rgb
  "landuse",         // DynamicWorld land-use 10% alpha
  "buildable",       // Buildable mask (gold fill)
  "polygon",         // Project polygon outline
  "substation",      // Nearest substation pin + POC line
  "grid_lines",      // Grid lines within 5km
];

export const DEFAULT_LAYERS = {
  satellite: true,
  terrain: true,
  landuse: true,
  buildable: true,
  polygon: true,
  substation: true,
  grid_lines: true,
};

export const CAMERA_PRESETS = ["plan", "oblique", "side", "orbit"];
export const DEFAULT_PRESET = "oblique";

const LS_PREFIX = "princeps.assess.twin";

function keyFor(projectId) {
  return `${LS_PREFIX}:${projectId || "_default"}`;
}

function loadState(projectId) {
  if (typeof window === "undefined") {
    return { layers: { ...DEFAULT_LAYERS }, cameraPreset: DEFAULT_PRESET };
  }
  try {
    const raw = window.localStorage.getItem(keyFor(projectId));
    if (!raw) return { layers: { ...DEFAULT_LAYERS }, cameraPreset: DEFAULT_PRESET };
    const parsed = JSON.parse(raw) || {};
    return {
      layers: { ...DEFAULT_LAYERS, ...(parsed.layers || {}) },
      cameraPreset: CAMERA_PRESETS.includes(parsed.cameraPreset) ? parsed.cameraPreset : DEFAULT_PRESET,
    };
  } catch {
    return { layers: { ...DEFAULT_LAYERS }, cameraPreset: DEFAULT_PRESET };
  }
}

function persist(projectId, next) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(keyFor(projectId), JSON.stringify(next));
  } catch {
    /* quota exceeded or disabled — ignore */
  }
}

export default function useProjectTwinLayers(projectId) {
  const [state, setState] = useState(() => loadState(projectId));

  // Re-hydrate when the project changes.
  useEffect(() => {
    setState(loadState(projectId));
  }, [projectId]);

  // Persist every change.
  useEffect(() => {
    persist(projectId, state);
  }, [projectId, state]);

  const toggleLayer = useCallback((key) => {
    setState((prev) => ({
      ...prev,
      layers: { ...prev.layers, [key]: !prev.layers[key] },
    }));
  }, []);

  const setAllLayers = useCallback((value) => {
    setState((prev) => ({
      ...prev,
      layers: Object.fromEntries(LAYER_KEYS.map((k) => [k, !!value])),
    }));
  }, []);

  const setCameraPreset = useCallback((preset) => {
    if (!CAMERA_PRESETS.includes(preset)) return;
    setState((prev) => ({ ...prev, cameraPreset: preset }));
  }, []);

  const reset = useCallback(() => {
    setState({ layers: { ...DEFAULT_LAYERS }, cameraPreset: DEFAULT_PRESET });
  }, []);

  return useMemo(
    () => ({
      layers: state.layers,
      cameraPreset: state.cameraPreset,
      toggleLayer,
      setAllLayers,
      setCameraPreset,
      reset,
    }),
    [state, toggleLayer, setAllLayers, setCameraPreset, reset]
  );
}
