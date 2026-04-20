import { useEffect, useState, useCallback } from "react";
import { getGridConnection, runTier2PowerFlow } from "../api/gridConnection.js";

/**
 * useGridConnection — fetches Tier 1 grid-connection assessment for a project.
 *
 * Matches useProjectKpis hook shape: { data, loading, error, refetch }.
 *
 * When VITE_MOCK_GRID is unset or "true", a realistic Slough-DC fixture
 * is returned; otherwise the call hits POST /api/grid/assess and
 * /api/grid/connection-forecast and normalises the response.
 */
export function useGridConnection(projectId, opts = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const optsKey = JSON.stringify({
    lat: opts?.lat, lon: opts?.lon,
    capacity_mw: opts?.capacity_mw,
    technology: opts?.technology,
  });

  const fetchIt = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await getGridConnection(projectId, opts);
      setData(res);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, optsKey]);

  useEffect(() => { fetchIt(); }, [fetchIt]);

  return { data, loading, error, refetch: fetchIt };
}

/**
 * useTier2PowerFlow — imperative handle for the "Run power flow" button.
 * Returns { run, data, loading, error, reset }.
 *
 * Not auto-fetched (expensive). Caller invokes `run(substation_id)` when the
 * operator clicks the Tier-2 button.
 */
export function useTier2PowerFlow(projectId, opts = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = useCallback(async (substation_id) => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await runTier2PowerFlow(projectId, {
        ...opts, substation_id,
      });
      setData(res);
      return res;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, [projectId, opts]);

  const reset = useCallback(() => {
    setData(null); setError(null); setLoading(false);
  }, []);

  return { run, data, loading, error, reset };
}
