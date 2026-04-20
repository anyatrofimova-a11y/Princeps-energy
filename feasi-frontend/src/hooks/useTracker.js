import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  listSubstations,
  getSubstation,
  getStats,
  triggerRefresh,
  approveSubstation,
  rejectSubstation,
  batchApprove,
  updateSubstation,
} from "../api/tracker";

/**
 * Fetch hooks for the Substation Tracker.
 * Mirrors the useAlerts pattern — each hook owns its loading/error state
 * and exposes a stable `reload` callback so parents can invalidate on
 * admin actions (refresh, review approvals).
 */

// ── List with filters + cursor pagination ───────────────────────
export function useTrackerList(filters = {}) {
  const [state, setState] = useState({ rows: [], total: 0, next_cursor: null, loading: true, error: null });
  const keyRef = useRef();
  const key = JSON.stringify(filters || {});

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await listSubstations(filters);
      setState({
        rows: res.rows || [],
        total: res.total ?? (res.rows || []).length,
        next_cursor: res.next_cursor ?? null,
        loading: false,
        error: null,
      });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e.message || String(e) }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    keyRef.current = key;
    let cancelled = false;
    (async () => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const res = await listSubstations(filters);
        if (cancelled || keyRef.current !== key) return;
        setState({
          rows: res.rows || [],
          total: res.total ?? (res.rows || []).length,
          next_cursor: res.next_cursor ?? null,
          loading: false,
          error: null,
        });
      } catch (e) {
        if (cancelled || keyRef.current !== key) return;
        setState((s) => ({ ...s, loading: false, error: e.message || String(e) }));
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { ...state, reload };
}

// ── Single detail ───────────────────────────────────────────────
export function useTrackerDetail(id) {
  const [row, setRow] = useState(null);
  const [loading, setLoading] = useState(!!id);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!id) { setRow(null); return; }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const r = await getSubstation(id);
        if (!cancelled) { setRow(r); setError(null); }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  return { row, loading, error };
}

// ── Stats (header count etc.) ───────────────────────────────────
export function useTrackerStats() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const s = await getStats();
      setStats(s);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return { stats, loading, error, reload };
}

// ── Review queue (low-confidence, not-yet-reviewed) ─────────────
export function useReviewQueue({ threshold = 0.75 } = {}) {
  const filters = useMemo(
    () => ({ confidence_lt: threshold, sme_reviewed: false, sort: "confidence:asc" }),
    [threshold]
  );
  const base = useTrackerList(filters);

  const approveOne = useCallback(async (id) => {
    await approveSubstation(id);
    await base.reload();
  }, [base]);

  const rejectOne = useCallback(async (id) => {
    await rejectSubstation(id);
    await base.reload();
  }, [base]);

  const approveMany = useCallback(async (ids) => {
    if (!ids?.length) return;
    await batchApprove(ids);
    await base.reload();
  }, [base]);

  return { ...base, approveOne, rejectOne, approveMany };
}

// ── Admin refresh trigger ───────────────────────────────────────
export function useRefreshTracker(onAfter) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await triggerRefresh();
      setResult(r);
      onAfter?.(r);
      return r;
    } catch (e) {
      setError(e.message || String(e));
      throw e;
    } finally {
      setRunning(false);
    }
  }, [onAfter]);

  return { run, running, result, error };
}

// ── Mutation: update one row ────────────────────────────────────
export function useUpdateSubstation() {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const save = useCallback(async (id, patch) => {
    setSaving(true);
    setError(null);
    try {
      return await updateSubstation(id, patch);
    } catch (e) {
      setError(e.message || String(e));
      throw e;
    } finally {
      setSaving(false);
    }
  }, []);

  return { save, saving, error };
}
