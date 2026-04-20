import { useEffect, useState } from "react";
import { getDigest, openDigestStream } from "../api/alerts";

/**
 * useDigest — fetches the roll-up digest feed grouped by day, and
 * subscribes to the SSE stream so new entries slot in live.
 */
export default function useDigest({ since = null, alertId = null } = {}) {
  const [digests, setDigests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await getDigest({ since, alertId });
        if (!cancelled) {
          setDigests(data.digests || []);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [since, alertId]);

  useEffect(() => {
    const stream = openDigestStream((ev) => {
      // Prepend new entries as they arrive. Contract: { date, entry }.
      if (!ev?.entry) return;
      setDigests((prev) => {
        const dayIdx = prev.findIndex((d) => d.date === ev.date);
        if (dayIdx >= 0) {
          const copy = [...prev];
          copy[dayIdx] = { ...copy[dayIdx], entries: [ev.entry, ...copy[dayIdx].entries] };
          return copy;
        }
        return [{ date: ev.date, entries: [ev.entry] }, ...prev];
      });
    });
    return () => stream.close();
  }, []);

  return { digests, loading, error };
}
