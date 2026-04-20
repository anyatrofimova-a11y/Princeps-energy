/**
 * useDomainLayers — stateful hook wrapping pack selection + sub-layer toggles.
 *
 *   const {
 *     activePack,           // current pack id ('solar' | 'bess' | 'dc' | 'wind' | 'ev' | 'co-located')
 *     setActivePack,        // user override
 *     sublayerToggles,      // { [sublayerId]: bool }
 *     toggleSublayer,       // (id) => void
 *     setSublayerToggles,   // bulk setter
 *     resetToDefaults,      // back to pack defaults
 *     layers,               // deck.gl layer array for current pack/toggles
 *     sublayers,            // metadata for current pack's sublayers
 *   } = useDomainLayers({ projectTech: 'solar', onHover, onClick });
 *
 * Persists:
 *   - `princeps_domain_pack`        → last user-selected pack id
 *   - `princeps_domain_toggles`     → { [packId]: { [sublayerId]: bool } }
 *
 * Auto-activates the pack matching the active project's technology unless the
 * user has explicitly overridden it in this session (tracked by localStorage).
 */

import { useState, useEffect, useMemo, useCallback } from "react";
import {
  DOMAIN_PACKS,
  normaliseTech,
  getDomainLayerPack,
  getDomainSublayers,
} from "../components/map/domain";

const LS_PACK_KEY     = "princeps_domain_pack";
const LS_OVERRIDE_KEY = "princeps_domain_pack_override";
const LS_TOGGLES_KEY  = "princeps_domain_toggles";

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function saveJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
}

/** Build the default toggle map for a pack id (co-located = union). */
function defaultsForPack(packId) {
  const subs = getDomainSublayers(packId);
  const out = {};
  for (const s of subs) out[s.id] = s.defaultOn !== false;
  return out;
}

export default function useDomainLayers({
  projectTech = null,
  onHover = null,
  onClick = null,
  coLocatedTechs = null,
} = {}) {
  // ── Pack selection ──
  // If user has overridden in this session we respect that; otherwise we follow
  // whatever tech the active project is.
  const normProject = normaliseTech(projectTech);
  const storedPack  = loadJSON(LS_PACK_KEY, null);
  const hasOverride = loadJSON(LS_OVERRIDE_KEY, false);

  const initialPack = hasOverride && storedPack
    ? storedPack
    : (normProject && DOMAIN_PACKS[normProject] ? normProject : (normProject === "co-located" ? "co-located" : "solar"));

  const [activePack, setActivePackState] = useState(initialPack);

  // Follow project tech changes unless user has overridden
  useEffect(() => {
    if (!hasOverride && normProject && normProject !== activePack) {
      setActivePackState(normProject);
      saveJSON(LS_PACK_KEY, normProject);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normProject]);

  const setActivePack = useCallback((packId) => {
    setActivePackState(packId);
    saveJSON(LS_PACK_KEY, packId);
    saveJSON(LS_OVERRIDE_KEY, true);
  }, []);

  const clearOverride = useCallback(() => {
    saveJSON(LS_OVERRIDE_KEY, false);
    if (normProject) {
      setActivePackState(normProject);
      saveJSON(LS_PACK_KEY, normProject);
    }
  }, [normProject]);

  // ── Sublayer toggles (persisted per pack) ──
  const [togglesByPack, setTogglesByPack] = useState(() => {
    const stored = loadJSON(LS_TOGGLES_KEY, {});
    // hydrate defaults for any missing pack so consumers always have a map
    const hydrated = { ...stored };
    for (const id of ["solar", "bess", "dc", "wind", "ev", "co-located"]) {
      if (!hydrated[id]) hydrated[id] = defaultsForPack(id);
    }
    return hydrated;
  });

  useEffect(() => { saveJSON(LS_TOGGLES_KEY, togglesByPack); }, [togglesByPack]);

  const sublayerToggles = togglesByPack[activePack] || defaultsForPack(activePack);

  const toggleSublayer = useCallback((sublayerId) => {
    setTogglesByPack((prev) => {
      const current = prev[activePack] || defaultsForPack(activePack);
      return { ...prev, [activePack]: { ...current, [sublayerId]: !current[sublayerId] } };
    });
  }, [activePack]);

  const setSublayerToggles = useCallback((next) => {
    setTogglesByPack((prev) => ({ ...prev, [activePack]: { ...(prev[activePack] || {}), ...next } }));
  }, [activePack]);

  const resetToDefaults = useCallback(() => {
    setTogglesByPack((prev) => ({ ...prev, [activePack]: defaultsForPack(activePack) }));
  }, [activePack]);

  // ── Build deck.gl layers for current selection ──
  const layers = useMemo(() => {
    return getDomainLayerPack(activePack, {
      active_layer_toggles: sublayerToggles,
      onHover,
      onClick,
      coLocatedTechs,
    });
  // layers are rebuilt when pack or toggles change; viewport-independent for now
  }, [activePack, sublayerToggles, onHover, onClick, coLocatedTechs]);

  const sublayers = useMemo(() => getDomainSublayers(activePack), [activePack]);

  return {
    activePack,
    setActivePack,
    clearOverride,
    sublayerToggles,
    toggleSublayer,
    setSublayerToggles,
    resetToDefaults,
    layers,
    sublayers,
    isOverridden: hasOverride,
    projectTech: normProject,
  };
}
