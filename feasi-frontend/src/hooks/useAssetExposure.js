import { useEffect, useState } from "react";

/**
 * useAssetExposure — fetch the portfolio-wide financial exposure payload
 * for a given connected asset (substation / GSP).
 *
 * Hits GET /api/portfolio/asset-exposure/{substation_id}. Returns
 * { loading, error, data } and refetches whenever substation_id changes.
 */
export default function useAssetExposure({ substation_id, portfolio_id = null }) {
  const [state, setState] = useState({ loading: false, error: null, data: null });

  useEffect(() => {
    if (!substation_id) {
      setState({ loading: false, error: null, data: null });
      return () => {};
    }
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    const qs = portfolio_id ? `?portfolio_id=${encodeURIComponent(portfolio_id)}` : "";
    fetch(`/api/portfolio/asset-exposure/${encodeURIComponent(substation_id)}${qs}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => { if (!cancelled) setState({ loading: false, error: null, data }); })
      .catch((e) => { if (!cancelled) setState({ loading: false, error: e.message || "Load failed", data: null }); });
    return () => { cancelled = true; };
  }, [substation_id, portfolio_id]);

  return state;
}
