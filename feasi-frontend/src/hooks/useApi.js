import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Lightweight fetch hook with loading/error/abort.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useApi(() => api.site.explain(id), [id]);
 *
 * The fetcher function should return a promise resolving to JSON or null.
 * Pass `null` as fetcher to skip fetching.
 */
export default function useApi(fetcher, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!!fetcher);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);
  const callId = useRef(0);

  const execute = useCallback(async () => {
    if (!fetcher) return;
    const id = ++callId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      if (mountedRef.current && id === callId.current) {
        setData(result);
      }
    } catch (err) {
      if (mountedRef.current && id === callId.current) {
        setError(err);
      }
    } finally {
      if (mountedRef.current && id === callId.current) {
        setLoading(false);
      }
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    execute();
  }, [execute]);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  return { data, loading, error, refetch: execute };
}
