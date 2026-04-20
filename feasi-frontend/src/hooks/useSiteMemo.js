import { useEffect, useState, useCallback } from "react";
import { getMemoHistory, generateMemoStream } from "../api/projectMemo.js";

export function useSiteMemo(projectId) {
  const [latest, setLatest] = useState(null);
  const [past, setPast] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(null);

  useEffect(() => {
    let cancelled = false;
    if (!projectId) return;
    (async () => {
      try {
        const r = await getMemoHistory(projectId);
        if (!cancelled) {
          setLatest(r.latest);
          setPast(r.past);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  const generate = useCallback(() => {
    setGenerating(true);
    setProgress(null);
    const close = generateMemoStream(projectId, (evt) => {
      if (evt.type === "progress") setProgress(evt);
      if (evt.type === "done") {
        setLatest(evt.memo);
        setGenerating(false);
        setProgress(null);
      }
    });
    return close;
  }, [projectId]);

  return { latest, past, loading, generating, progress, generate };
}
