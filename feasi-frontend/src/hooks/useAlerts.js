import { useCallback, useEffect, useState } from "react";
import { getAlertLibrary, subscribeAlert, unsubscribeAlert } from "../api/alerts";

/**
 * useAlerts — thin wrapper over the alert library.
 * Exposes the loaded list, subscribe/unsubscribe helpers, and an
 * aggregate unreadCount derived from subscribed alerts only.
 */
export default function useAlerts() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAlertLibrary();
      setAlerts(data.alerts || []);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getAlertLibrary();
        if (!cancelled) {
          setAlerts(data.alerts || []);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const subscribe = useCallback(async (alertId) => {
    // Optimistic — flip the subscribed flag locally first.
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, subscribed: true } : a))
    );
    try {
      await subscribeAlert(alertId);
    } catch (e) {
      // Rollback on failure.
      setAlerts((prev) =>
        prev.map((a) => (a.id === alertId ? { ...a, subscribed: false } : a))
      );
      throw e;
    }
  }, []);

  const unsubscribe = useCallback(async (alertId) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === alertId ? { ...a, subscribed: false } : a))
    );
    try {
      await unsubscribeAlert(alertId);
    } catch (e) {
      setAlerts((prev) =>
        prev.map((a) => (a.id === alertId ? { ...a, subscribed: true } : a))
      );
      throw e;
    }
  }, []);

  const subscribedCount = alerts.filter((a) => a.subscribed).length;
  const unreadCount = alerts
    .filter((a) => a.subscribed)
    .reduce((sum, a) => sum + (a.unread || 0), 0);

  return {
    alerts,
    loading,
    error,
    reload,
    subscribe,
    unsubscribe,
    subscribedCount,
    unreadCount,
  };
}
