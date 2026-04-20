import { useCallback, useRef, useState } from "react";
import { streamQuery } from "../api/alerts";

/**
 * useDocumentQuery — SSE-backed "ask across documents" hook.
 * Mirrors the /chat streaming contract (text_delta + citation + done).
 *
 * Each citation is stored as { n, doc_id, title, source, date, label, score }.
 * `firstDocId` is the doc_id of citation n=1, exposed so the right rail can
 * switch to the top-cited doc as soon as citations arrive.
 */
export default function useDocumentQuery() {
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const ask = useCallback(async (question, scope = {}) => {
    if (!question || streaming) return;
    setAnswer("");
    setCitations([]);
    setError(null);
    setStreaming(true);
    abortRef.current = new AbortController();
    await streamQuery({
      question,
      scope,
      signal: abortRef.current.signal,
      onDelta: (t) => setAnswer((prev) => prev + (t ?? "")),
      onCitation: (c) => setCitations((prev) => {
        // Dedupe by n (backend may re-emit); replace-in-place to keep order stable.
        const next = prev.filter((x) => x.n !== c.n);
        next.push(c);
        next.sort((a, b) => (a.n ?? 0) - (b.n ?? 0));
        return next;
      }),
      onDone: () => setStreaming(false),
      onError: (m) => { setError(m); setStreaming(false); },
    });
    setStreaming(false);
  }, [streaming]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setAnswer("");
    setCitations([]);
    setError(null);
    setStreaming(false);
  }, []);

  const firstDocId = citations.length > 0 ? (citations[0].doc_id || null) : null;

  return { answer, citations, streaming, error, ask, cancel, reset, firstDocId };
}
