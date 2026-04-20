import { useEffect, useState } from "react";
import { getKpis } from "../api/projectMemo.js";

export function useProjectKpis(projectId, { pollMs = 60000 } = {}) {
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!projectId) return;
    let timer;
    async function tick() {
      try {
        const k = await getKpis(projectId);
        if (!cancelled) { setKpis(k); setError(null); }
      } catch (e) {
        if (!cancelled) setError(e);
      } finally {
        if (!cancelled) setLoading(false);
        if (!cancelled && pollMs > 0) timer = setTimeout(tick, pollMs);
      }
    }
    tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [projectId, pollMs]);

  return { kpis, loading, error };
}
