import React, { Suspense } from "react";

/**
 * TwinLazy — lazy + error-bounded wrapper around the heavy TwinRoot bundle.
 *
 * Purpose
 * -------
 * The Princeps 3D Twin v1 ("TwinRoot") is the heaviest React bundle in the
 * app — deck.gl, Mapbox GL, glTF loaders, asset instancing, shadow polygon
 * layers. Every page that renders the twin must go through this wrapper so:
 *
 *   1. The TwinRoot chunk is loaded on demand (React.lazy code-split).
 *   2. A gold-pulsing skeleton is shown while the JS loads.
 *   3. Any runtime failure (missing glTF, missing Mapbox token, deck.gl
 *      init throw, …) falls back gracefully to an inline error card
 *      offering a retry button — never the whole app crashes.
 *
 * Pages NEVER import TwinRoot directly — always go via this file. That is
 * what keeps the main bundle split clean.
 *
 * Props — forwarded verbatim to TwinRoot:
 *   projectId:    string (required)
 *   polygon_wkt:  string (optional — WKT polygon)
 *   tech:         "solar" | "wind" | "bess" | "dc"
 *   capacity_mw:  number
 *   mode:         "oblique" | "plan" | "side" | "orbit"  (default "oblique")
 *   fallback2D:   ReactNode — optional 2D map to render if TwinRoot fails
 *   onError:      (err) => void  — optional error hook for telemetry
 */

// Lazy import lives at module scope so React can memoise the chunk promise.
// If the module resolution itself fails (e.g. file missing on disk), we'll
// catch that in the error boundary below.
const TwinRoot = React.lazy(() =>
  import("./TwinRoot").catch((err) => {
    // Resolve to a component that throws during render — the boundary below
    // catches it and shows the graceful-fallback UI. This avoids the naked
    // "Failed to fetch dynamically imported module" console error.
    console.error("[TwinLazy] Failed to load TwinRoot bundle:", err);
    return {
      default: function TwinRootLoadFailed() {
        throw new Error("TwinRoot bundle failed to load");
      },
    };
  }),
);

/* ── Gold-pulsing skeleton ring while the bundle loads ────────────────────── */
function TwinLoadingSkeleton() {
  return (
    <div className="tl-skel" role="status" aria-live="polite">
      <div className="tl-skel-ring" />
      <div className="tl-skel-msg">Loading construction kit…</div>
      <style>{`
        .tl-skel {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 18px;
          background: linear-gradient(135deg, #1A1D23 0%, #0F1318 100%);
          color: rgba(251, 248, 242, 0.85);
          font-family: "DM Sans", -apple-system, sans-serif;
          z-index: 2;
        }
        .tl-skel-ring {
          width: 44px;
          height: 44px;
          border-radius: 50%;
          border: 3px solid rgba(245, 183, 49, 0.18);
          border-top-color: #F5B731;
          box-shadow: 0 0 24px rgba(245, 183, 49, 0.35);
          animation: tl-spin 1.05s linear infinite, tl-pulse 1.8s ease-in-out infinite;
        }
        .tl-skel-msg {
          font-size: 12px;
          font-weight: 500;
          letter-spacing: 0.04em;
          color: rgba(251, 248, 242, 0.72);
        }
        @keyframes tl-spin { to { transform: rotate(360deg); } }
        @keyframes tl-pulse {
          0%, 100% { box-shadow: 0 0 18px rgba(245, 183, 49, 0.25); }
          50%      { box-shadow: 0 0 32px rgba(245, 183, 49, 0.55); }
        }
      `}</style>
    </div>
  );
}

/* ── Graceful fallback when TwinRoot throws ──────────────────────────────── */
function TwinErrorFallback({ error, onRetry, fallback2D }) {
  return (
    <div className="tl-err">
      {fallback2D ? (
        <div className="tl-err-2d">{fallback2D}</div>
      ) : (
        <div className="tl-err-empty">
          <div className="tl-err-title">3D twin unavailable</div>
          <div className="tl-err-sub">
            Falling back to 2D. {error?.message ? `(${error.message})` : ""}
          </div>
        </div>
      )}

      <div className="tl-err-toast" role="alert">
        <span className="tl-err-dot" />
        <span className="tl-err-toast-msg">3D twin unavailable — 2D view shown.</span>
        <button className="tl-err-retry" onClick={onRetry}>Retry</button>
      </div>

      <style>{`
        .tl-err { position: absolute; inset: 0; }
        .tl-err-2d { position: absolute; inset: 0; }
        .tl-err-empty {
          position: absolute; inset: 0;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          background: linear-gradient(135deg, #1A1D23 0%, #0F1318 100%);
          color: rgba(251, 248, 242, 0.85);
          font-family: "DM Sans", -apple-system, sans-serif;
          padding: 24px;
        }
        .tl-err-title { font-size: 15px; font-weight: 600; color: #FBF8F2; }
        .tl-err-sub {
          font-size: 12px;
          color: rgba(251, 248, 242, 0.55);
          margin-top: 6px; max-width: 420px; line-height: 1.5;
          text-align: center;
        }
        .tl-err-toast {
          position: absolute;
          left: 50%;
          bottom: 16px;
          transform: translateX(-50%);
          display: inline-flex;
          align-items: center;
          gap: 10px;
          background: rgba(15, 19, 24, 0.92);
          border: 1px solid rgba(245, 183, 49, 0.55);
          color: #FBF8F2;
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 12px;
          padding: 7px 13px;
          border-radius: 8px;
          box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
          z-index: 6;
          backdrop-filter: blur(10px);
        }
        .tl-err-dot {
          width: 8px; height: 8px;
          border-radius: 50%; background: #F5B731;
          box-shadow: 0 0 8px rgba(245, 183, 49, 0.8);
        }
        .tl-err-toast-msg { opacity: 0.85; }
        .tl-err-retry {
          margin-left: 4px;
          background: rgba(245, 183, 49, 0.18);
          border: 1px solid rgba(245, 183, 49, 0.55);
          color: #F5B731;
          padding: 3px 10px;
          border-radius: 5px;
          font-size: 11px; font-weight: 700;
          cursor: pointer;
          font-family: inherit;
          transition: all 120ms;
        }
        .tl-err-retry:hover { background: #F5B731; color: #0F1318; }
      `}</style>
    </div>
  );
}

/* ── Error boundary specialised for TwinRoot mount failures ───────────── */
class TwinErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, nonce: 0 };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Never let this bubble — it crashes the parent page.
    // eslint-disable-next-line no-console
    console.error("[TwinLazy] TwinRoot threw:", error, info);
    if (typeof this.props.onError === "function") {
      try { this.props.onError(error); } catch { /* silent */ }
    }
  }

  handleRetry = () => {
    // Bump nonce → remount the child tree. Also reset the error state so
    // Suspense will re-try the lazy import.
    this.setState((s) => ({ error: null, nonce: s.nonce + 1 }));
  };

  render() {
    if (this.state.error) {
      return (
        <TwinErrorFallback
          error={this.state.error}
          onRetry={this.handleRetry}
          fallback2D={this.props.fallback2D}
        />
      );
    }
    // The `key` bump forces Suspense/lazy to remount on retry.
    return (
      <React.Fragment key={this.state.nonce}>
        {this.props.children}
      </React.Fragment>
    );
  }
}

/**
 * TwinLazy — default export. Wraps <TwinRoot> in Suspense + ErrorBoundary.
 * Pass through any additional props you want the sibling agent's TwinRoot
 * to consume (projectId, polygon_wkt, tech, capacity_mw, mode).
 *
 * The TwinRoot shell reads viewMode from the twinStore (zustand) rather
 * than via prop; to honour the `mode` prop we set the store on mount via
 * a tiny effect child. This keeps the sibling TwinRoot untouched.
 */
function ModeSyncer({ mode }) {
  // Lazy-load the store only on the 3D path so we don't pay the zustand
  // import cost when the page never renders the twin. If the import fails
  // (e.g. in tests), we just skip the sync silently.
  React.useEffect(() => {
    if (!mode) return;
    let cancelled = false;
    (async () => {
      try {
        const mod = await import("./stores/twinStore");
        const store = mod.useTwinStore;
        if (!cancelled && store && typeof store.getState === "function") {
          const { setViewMode, viewMode } = store.getState();
          if (typeof setViewMode === "function" && mode !== viewMode) {
            setViewMode(mode);
          }
        }
      } catch { /* silent — store not available */ }
    })();
    return () => { cancelled = true; };
  }, [mode]);
  return null;
}

export default function TwinLazy({ fallback2D = null, onError = null, mode = "oblique", ...twinProps }) {
  return (
    <TwinErrorBoundary fallback2D={fallback2D} onError={onError}>
      <Suspense fallback={<TwinLoadingSkeleton />}>
        <ModeSyncer mode={mode} />
        <TwinRoot mode={mode} {...twinProps} />
      </Suspense>
    </TwinErrorBoundary>
  );
}
