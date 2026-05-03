/**
 * useCouncilDispatch — chat-rail glue between classification and the
 * Council surface.
 *
 * Lifecycle:
 *   1. dispatch(query, projectRid?) classifies via POST /api/chat/classify-council.
 *   2. If needs_council → POST /api/council/session, then attach an
 *      EventSource on /api/council/session/<rid>/stream and stream into
 *      the same `events` + `state` shape useCouncilSession would yield.
 *   3. If !needs_council → returns {needs_council:false} so the rail
 *      proceeds with the regular chat code path.
 *   4. reset() closes any open stream and clears the in-memory timeline.
 *
 * Errors during classification fall back to needs_council:false so the
 * user is never blocked by a misbehaving classifier — regular chat wins.
 */

import { useCallback, useEffect, useRef, useState } from "react";

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
      return { ...state, pod_errors: [...(state.pod_errors || []), evt.error] };
    case "adjudication":
      return {
        ...state,
        adjudication: { stage: evt.stage, result: evt.result || state.adjudication?.result },
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
      return { ...state, final: evt.result };
    case "error":
      return { ...state, error: evt.message };
    case "done":
      return { ...state, done: true };
    default:
      return state;
  }
}

export default function useCouncilDispatch() {
  const [classifying, setClassifying] = useState(false);
  const [classification, setClassification] = useState(null);
  const [sessionRid, setSessionRid] = useState(null);
  const [events, setEvents] = useState([]);
  const [state, setState] = useState({ pods: {} });
  const [error, setError] = useState(null);
  const esRef = useRef(null);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      try { esRef.current.close(); } catch { /* ignore */ }
      esRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    closeStream();
    setEvents([]);
    setState({ pods: {} });
    setSessionRid(null);
    setClassification(null);
    setError(null);
  }, [closeStream]);

  useEffect(() => () => closeStream(), [closeStream]);

  const dispatch = useCallback(async (query, projectRid = null) => {
    if (!query || !query.trim()) return { needs_council: false };
    setError(null);
    setClassifying(true);
    let cls = null;
    try {
      const r = await fetch(`${API_BASE}/api/chat/classify-council`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
      });
      if (r.ok) cls = await r.json();
    } catch (e) {
      // Classification failure → fall back to regular chat. Don't block.
      cls = { needs_council: false, domains: [], reason: "classify_error", source: "fallback" };
    } finally {
      setClassifying(false);
    }
    if (!cls) cls = { needs_council: false, domains: [] };
    setClassification(cls);

    if (!cls.needs_council) return cls;

    // Multi-domain → open a Council session and attach SSE stream.
    closeStream();
    setEvents([]);
    setState({ pods: {} });
    let rid;
    try {
      const r = await fetch(`${API_BASE}/api/council/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), project_rid: projectRid || null }),
      });
      if (!r.ok) throw new Error(`session create failed: ${r.status}`);
      const j = await r.json();
      rid = j.session_rid;
      setSessionRid(rid);
    } catch (e) {
      setError(e.message || "council session failed");
      return { ...cls, needs_council: false, _failed: true };
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
      setState((prev) => prev.done ? prev : { ...prev, error: "stream_error" });
    };

    return { ...cls, session_rid: rid };
  }, [closeStream]);

  return {
    dispatch,
    classifying,
    classification,
    sessionRid,
    events,
    state,
    finalVerdict: state.final || null,
    error,
    reset,
  };
}
