/**
 * useDesignPlacements — state for user-placed equipment on DesignCanvas.
 *
 * A placement is:
 *   { id, type_id, category, name, lng, lat, rotation_deg, scale, footprint_m: [w, h], placed_at }
 *
 * Persisted to sessionStorage keyed by project/site id so a tab refresh keeps
 * the layout. Backend persistence can layer on later via saveLayout().
 *
 * API:
 *   const {
 *     placements, selectedId, select, add, remove, clone, update,
 *     phase, setPhase, byCategory, countByType, clearAll,
 *   } = useDesignPlacements({ scopeId });
 */
import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_PREFIX = "princeps_design_placements::";

function storageKey(scopeId) {
  return `${STORAGE_PREFIX}${scopeId || "default"}`;
}

function readInitial(scopeId) {
  try {
    const raw = sessionStorage.getItem(storageKey(scopeId));
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function makeId() {
  return `pl_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export default function useDesignPlacements({ scopeId } = {}) {
  const [placements, setPlacements] = useState(() => readInitial(scopeId));
  const [selectedId, setSelectedId] = useState(null);
  const [phase, setPhase] = useState(3); // 1=shell, 2=equipment, 3=commissioning

  // Re-hydrate when scope changes (e.g. site switched).
  useEffect(() => {
    setPlacements(readInitial(scopeId));
    setSelectedId(null);
  }, [scopeId]);

  // Persist on every change.
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey(scopeId), JSON.stringify(placements));
    } catch { /* quota / private mode — ignore */ }
  }, [placements, scopeId]);

  const add = useCallback((item, lngLat) => {
    if (!item || !lngLat) return null;
    const id = makeId();
    const next = {
      id,
      type_id: item.type_id,
      category: item.category,
      name: item.name,
      lng: lngLat.lng,
      lat: lngLat.lat,
      rotation_deg: 0,
      scale: 1,
      footprint_m: item.footprint_m,
      phase: item.phase || 2,
      placed_at: Date.now(),
    };
    setPlacements((list) => [...list, next]);
    setSelectedId(id);
    return id;
  }, []);

  const remove = useCallback((id) => {
    setPlacements((list) => list.filter((p) => p.id !== id));
    setSelectedId((sel) => (sel === id ? null : sel));
  }, []);

  const clone = useCallback((id) => {
    setPlacements((list) => {
      const src = list.find((p) => p.id === id);
      if (!src) return list;
      const lonOffset = 0.00012; // ~10m east
      const copy = { ...src, id: makeId(), lng: src.lng + lonOffset, placed_at: Date.now() };
      return [...list, copy];
    });
  }, []);

  const update = useCallback((id, patch) => {
    setPlacements((list) => list.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }, []);

  const select = useCallback((id) => setSelectedId(id), []);
  const clearAll = useCallback(() => { setPlacements([]); setSelectedId(null); }, []);

  const byCategory = useMemo(() => {
    const out = {};
    for (const p of placements) {
      if (!out[p.category]) out[p.category] = [];
      out[p.category].push(p);
    }
    return out;
  }, [placements]);

  const countByType = useMemo(() => {
    const out = {};
    for (const p of placements) {
      out[p.type_id] = (out[p.type_id] || 0) + 1;
    }
    return out;
  }, [placements]);

  return {
    placements, selectedId, select,
    add, remove, clone, update,
    phase, setPhase,
    byCategory, countByType, clearAll,
  };
}
