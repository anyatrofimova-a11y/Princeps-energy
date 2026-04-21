/**
 * useGridNeighbourhood — fetches the electrical + geo neighbourhood of a
 * root substation and caches the result in sessionStorage so that chip
 * re-rooting and depth-toggle round-trips are instant.
 *
 * Backend contract (BOT-CN-D):
 *   GET /api/grid/substation/{id}/neighbourhood?depth=N&radius_km=M
 *   → {
 *       root:  { id, name, voltage_kv, lat, lon, ... },
 *       nodes: [{ id, name, lat, lon, voltage_kv, hop, electrical,
 *                 headroom_mw?, firm_capacity_mw?, dno? }],
 *       edges: [{ id, from_id, to_id, voltage_kv, length_km,
 *                 is_path_to_root }],
 *       queue_at_root?: { accepted, applied },
 *       _truncated?: boolean,
 *     }
 *
 * Returns `{ data, loading, error }`. `data` is `null` when the id is
 * falsy (lets parent bail early without branching on `loading`).
 *
 * Cache keyed by `${id}|${depth}|${radiusKm}` in sessionStorage; a tiny
 * in-memory LRU (capacity 50) backs it so repeat hover cycles don't even
 * touch JSON.parse. Cache is cleared on full-page reload (sessionStorage
 * lifetime).
 *
 * OWNED by BOT-CN-M. BOT-CN-D owns the endpoint; if the payload shape
 * drifts, patch `_normalise()` below rather than leaking shape details
 * into the rail / layer builders.
 */
import { useEffect, useRef, useState } from "react";

const CACHE_PREFIX = "grid:nbh:";
const LRU_CAPACITY = 50;

/** Tiny in-memory LRU so hover pulses don't re-parse JSON from sessionStorage. */
const lru = new Map();
function lruGet(key) {
  if (!lru.has(key)) return undefined;
  const v = lru.get(key);
  lru.delete(key);
  lru.set(key, v); // re-insert → most-recent
  return v;
}
function lruSet(key, value) {
  if (lru.has(key)) lru.delete(key);
  lru.set(key, value);
  if (lru.size > LRU_CAPACITY) {
    const oldest = lru.keys().next().value;
    lru.delete(oldest);
  }
}

/** Read-through cache: memory first, then sessionStorage. */
function cacheGet(key) {
  const mem = lruGet(key);
  if (mem !== undefined) return mem;
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    lruSet(key, parsed);
    return parsed;
  } catch {
    return null;
  }
}
function cacheSet(key, value) {
  lruSet(key, value);
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value));
  } catch {
    // quota exceeded — drop silently; LRU still has it
  }
}

/** Defensive normaliser — shields callers from backend field drift. */
function _normalise(raw) {
  if (!raw || typeof raw !== "object") return null;
  const root = raw.root || null;
  const nodes = Array.isArray(raw.nodes) ? raw.nodes : [];
  const edges = Array.isArray(raw.edges) ? raw.edges : [];
  return {
    root,
    nodes: nodes.map((n) => ({
      id: n.id,
      name: n.name || "",
      lat: n.lat ?? n.latitude ?? null,
      lon: n.lon ?? n.longitude ?? null,
      voltage_kv: Number(n.voltage_kv || 0),
      hop: Number(n.hop ?? 0),
      electrical: n.electrical !== false, // default true if omitted
      headroom_mw: n.headroom_mw ?? n.demand_headroom_mw ?? null,
      firm_capacity_mw: n.firm_capacity_mw ?? n.rated_mva ?? null,
      dno: n.dno || null,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      from_id: e.from_id,
      to_id: e.to_id,
      voltage_kv: Number(e.voltage_kv || 0),
      length_km: Number(e.length_km || 0),
      is_path_to_root: !!e.is_path_to_root,
    })),
    queue_at_root: raw.queue_at_root || null,
    _truncated: !!raw._truncated,
  };
}

export function useGridNeighbourhood(substationId, { depth = 2, radiusKm = 20 } = {}) {
  const [state, setState] = useState({ data: null, loading: false, error: null });
  // AbortController for the in-flight request so rapid re-rooting cancels
  // stale fetches before they commit state.
  const abortRef = useRef(null);

  useEffect(() => {
    if (!substationId) {
      setState({ data: null, loading: false, error: null });
      return;
    }

    const key = `${substationId}|${depth}|${radiusKm}`;
    const cached = cacheGet(key);
    if (cached) {
      setState({ data: cached, loading: false, error: null });
      return;
    }

    // Cancel any prior in-flight request
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setState({ data: null, loading: true, error: null });

    const url = `/api/grid/substation/${encodeURIComponent(substationId)}/neighbourhood?depth=${depth}&radius_km=${radiusKm}`;
    fetch(url, { signal: ctrl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`neighbourhood ${r.status}`);
        return r.json();
      })
      .then((raw) => {
        const data = _normalise(raw);
        if (data) cacheSet(key, data);
        setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState({ data: null, loading: false, error: err });
      });

    return () => ctrl.abort();
  }, [substationId, depth, radiusKm]);

  return state;
}

export default useGridNeighbourhood;
