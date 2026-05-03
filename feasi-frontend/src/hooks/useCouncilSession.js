/**
 * useCouncilSession — drive a Council multi-pod adjudication via SSE.
 *
 * Lifecycle:
 *   1. start({ query, project_rid }) — POST /api/council/session, then open
 *      EventSource on /api/council/session/<rid>/stream.
 *   2. yields events into `events` (append-only timeline) and a `state`
 *      reducer ({pods: {grid, bess, dc}, adjudication, clarification, final}).
 *   3. clarify(answer) — POST /api/council/session/<rid>/clarify when the
 *      stream emits `clarification_needed`.
 *   4. close() — abort the EventSource.
 *
 * Returned events are passed through unchanged for the demo timeline
 * renderer; the `state` shape exists so callers don't have to re-derive
 * it from the raw stream.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API_BASE = ""; // proxied by Vite

function reduce(state, evt) {
  if (!evt || !evt.type) return state;
  switch (evt.type) {
    case "session_started":
      return {
        ...state,
        session_rid: evt.session_rid,
        project_rid: evt.project_rid,
        query: evt.query,
        pods_expected: evt.pods || [],
      };
    case "pod_started":
      return {
        ...state,
        pods: {
          ...state.pods,
          [evt.pod]: {
            status: "running",
            tools_bound: evt.tools_bound || [],
            tools_stubbed: evt.tools_stubbed || [],
          },
        },
      };
    case "pod_verdict":
      return {
        ...state,
        pods: {
          ...state.pods,
          [evt.pod]: {
            ...(state.pods?.[evt.pod] || {}),
            status: "complete",
            verdict: evt.verdict,
            trace: evt.trace,
          },
        },
      };
    case "pod_error":
      return {
        ...state,
        pod_errors: [...(state.pod_errors || []), evt.error],
      };
    case "adjudication":
      return {
        ...state,
        adjudication: {
          stage: evt.stage,
          result: evt.result || (state.adjudication?.result),
        },
      };
    case "clarification_needed":
      return {
        ...state,
        clarification: {
          question: evt.question,
          options: evt.options || [],
          conflicts: evt.conflicts || [],
          pending: true,
        },
      };
    case "final_verdict":
      return {
        ...state,
        final: evt.result,
        clarification: state.clarification
          ? { ...state.clarification, pending: false }
          : null,
      };
    case "error":
      return { ...state, error: evt.message };
    case "done":
      return { ...state, done: true };
    default:
      return state;
  }
}

export function useCouncilSession() {
  const [events, setEvents] = useState([]);
  const [state, setState] = useState({ pods: {} });
  const [creating, setCreating] = useState(false);
  const esRef = useRef(null);
  const sessionRef = useRef(null);

  const close = useCallback(() => {
    if (esRef.current) {
      try { esRef.current.close(); } catch { /* ignore */ }
      esRef.current = null;
    }
  }, []);

  useEffect(() => () => close(), [close]);

  const start = useCallback(async ({ query, project_rid = null } = {}) => {
    if (!query || !query.trim()) {
      throw new Error("query is required");
    }
    close();
    setEvents([]);
    setState({ pods: {} });
    setCreating(true);

    let rid;
    try {
      const r = await fetch(`${API_BASE}/api/council/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), project_rid }),
      });
      if (!r.ok) throw new Error(`session create failed: ${r.status}`);
      const j = await r.json();
      rid = j.session_rid;
      sessionRef.current = rid;
    } finally {
      setCreating(false);
    }

    const es = new EventSource(`${API_BASE}/api/council/session/${encodeURIComponent(rid)}/stream`);
    esRef.current = es;

    es.onmessage = (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }
      setEvents((prev) => [...prev, evt]);
      setState((prev) => reduce(prev, evt));
      if (evt && evt.type === "done") {
        try { es.close(); } catch { /* ignore */ }
      }
    };
    es.onerror = () => {
      // Browser EventSource auto-reconnects; only surface if the server
      // closed the connection cleanly with no `done` event.
      setState((prev) => prev.done ? prev : { ...prev, error: "stream_error" });
    };

    return rid;
  }, [close]);

  const clarify = useCallback(async (answer) => {
    const rid = sessionRef.current;
    if (!rid) throw new Error("no active session");
    const r = await fetch(`${API_BASE}/api/council/session/${encodeURIComponent(rid)}/clarify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    if (!r.ok) throw new Error(`clarify failed: ${r.status}`);
    return r.json();
  }, []);

  const summary = useMemo(() => ({
    session_rid: state.session_rid,
    pods: state.pods || {},
    adjudication: state.adjudication?.result || null,
    final: state.final || null,
    clarification: state.clarification || null,
    done: !!state.done,
    error: state.error || null,
  }), [state]);

  return {
    events,
    state: summary,
    start,
    clarify,
    close,
    creating,
  };
}

export default useCouncilSession;
