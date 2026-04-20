// SWR-style hook for BOT-FF parcel dossier.
// ---------------------------------------------------------------
// * 5-minute module-level cache keyed by inspire_id
// * dedupes in-flight requests so two simultaneous openings only fetch once
// * abortable — if the drawer closes mid-fetch, the request is cancelled
//
// Usage:
//   const { dossier, loading, error, reload } = useParcelDossier(inspireId);

import { useCallback, useEffect, useRef, useState } from "react";
import { getParcelDossier } from "../api/parcel";

const CACHE_TTL_MS = 5 * 60 * 1000;

const _cache = new Map();       // inspire_id -> { data, ts }
const _inflight = new Map();    // inspire_id -> Promise

function readCache(id) {
  const entry = _cache.get(id);
  if (!entry) return null;
  if (Date.now() - entry.ts > CACHE_TTL_MS) {
    _cache.delete(id);
    return null;
  }
  return entry.data;
}

function writeCache(id, data) {
  _cache.set(id, { data, ts: Date.now() });
}

async function fetchWithDedupe(id, { signal }) {
  if (_inflight.has(id)) return _inflight.get(id);
  const p = getParcelDossier(id, { signal })
    .then((data) => {
      writeCache(id, data);
      return data;
    })
    .finally(() => {
      _inflight.delete(id);
    });
  _inflight.set(id, p);
  return p;
}

export default function useParcelDossier(inspireId) {
  const [dossier, setDossier] = useState(() =>
    inspireId ? readCache(inspireId) : null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const load = useCallback(
    async (id, { force = false } = {}) => {
      if (!id) return;
      if (!force) {
        const cached = readCache(id);
        if (cached) {
          setDossier(cached);
          setError(null);
          return;
        }
      }

      // Abort any previous request.
      if (abortRef.current) abortRef.current.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setLoading(true);
      setError(null);
      try {
        const data = await fetchWithDedupe(id, { signal: ctrl.signal });
        if (ctrl.signal.aborted) return;
        setDossier(data);
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setError(e?.message || String(e));
        setDossier(null);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!inspireId) {
      setDossier(null);
      setError(null);
      return;
    }
    load(inspireId);
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, [inspireId, load]);

  const reload = useCallback(
    () => (inspireId ? load(inspireId, { force: true }) : undefined),
    [inspireId, load],
  );

  return { dossier, loading, error, reload };
}

// Expose cache controls for integration / tests.
export function clearParcelCache(id) {
  if (id) _cache.delete(id);
  else _cache.clear();
}
