import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import useAlerts from "../../hooks/useAlerts";

/**
 * HeadroomTicker — Bloomberg-style 24px scrolling bar of DNO headroom deltas.
 * Godmode direction #1: the live pulse of the UK grid visible from every screen.
 * Additionally hosts a gold "ALERTS · N new" pill on the right, which navigates
 * to /intelligence/alerts when clicked.
 */
function AlertsPill() {
  const { unreadCount } = useAlerts();
  const navigate = useNavigate();
  if (!unreadCount) return null;
  return (
    <button
      onClick={() => navigate("/intelligence/alerts")}
      title="Open Alerts"
      className="ht-alerts-pill"
      aria-label={`${unreadCount} new alerts`}
    >
      <span className="ht-alerts-dot" />
      ALERTS · {unreadCount} NEW
    </button>
  );
}

export default function HeadroomTicker() {
  const [deltas, setDeltas] = useState([]);
  const [error, setError] = useState(false);
  const tickRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const fetchDeltas = async () => {
      try {
        const r = await fetch("/api/grid/headroom-deltas?window_h=24&limit=40");
        if (!r.ok) throw new Error(String(r.status));
        const data = await r.json();
        if (!cancelled) {
          setDeltas(data.deltas || []);
          setError(false);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    };
    fetchDeltas();
    const t = setInterval(fetchDeltas, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (error || deltas.length === 0) {
    // Render nothing while connecting — a half-populated ticker just produces
    // visual noise like "HEADROOMconnecting…" at the top of the page. The
    // bar re-mounts with content as soon as the first batch of deltas lands.
    if (!error) return null;
    return (
      <div className="headroom-ticker headroom-ticker-empty">
        <span className="ht-label">HEADROOM</span>
        <span className="ht-muted">offline</span>
        <span className="ht-spacer" />
        <AlertsPill />
      </div>
    );
  }

  // Duplicate the list so the scroll loop is seamless.
  const doubled = [...deltas, ...deltas];

  return (
    <div className="headroom-ticker">
      <span className="ht-label">HEADROOM</span>
      <div className="ht-track" ref={tickRef}>
        <div className="ht-scroll">
          {doubled.map((d, i) => {
            const sign = d.delta_mw > 0 ? "+" : "";
            const cls = d.delta_mw > 0 ? "ht-chip ht-chip-up" :
                        d.delta_mw < 0 ? "ht-chip ht-chip-down" : "ht-chip";
            const title = `${d.dno || ""} ${d.region || ""} · ${d.event_type || "baseline"}`;
            return (
              <span key={i} className={cls} title={title}>
                <span className="ht-chip-sub">{d.substation}</span>
                <span className="ht-chip-mw">{sign}{d.delta_mw} MW</span>
              </span>
            );
          })}
        </div>
      </div>
      <AlertsPill />
      <style>{`
        .headroom-ticker {
          display: flex; align-items: center;
          height: 26px;
          background: #1A1714;
          color: #E8E5DF;
          border-bottom: 1px solid #3a332a;
          overflow: hidden;
          flex-shrink: 0;
          font-family: var(--mono, "JetBrains Mono"), monospace;
        }
        .headroom-ticker-empty { justify-content: flex-start; gap: 12px; }
        .ht-label {
          flex-shrink: 0;
          padding: 0 12px;
          height: 100%;
          display: flex; align-items: center;
          background: #F5B731;
          color: #1A1714;
          font-size: 10px; font-weight: 800;
          letter-spacing: 0.08em;
        }
        .ht-muted { padding: 0 12px; font-size: 11px; color: #9C9590; letter-spacing: 0.04em; }
        .ht-track {
          flex: 1; overflow: hidden;
          position: relative; height: 100%;
          mask-image: linear-gradient(90deg, transparent 0, #000 3%, #000 97%, transparent 100%);
          -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 3%, #000 97%, transparent 100%);
        }
        .ht-scroll {
          display: inline-flex; align-items: center;
          gap: 18px;
          padding: 0 16px;
          height: 100%;
          white-space: nowrap;
          animation: ht-scroll 90s linear infinite;
        }
        @keyframes ht-scroll {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
        .ht-chip {
          display: inline-flex; gap: 6px; align-items: baseline;
          font-size: 10px;
        }
        .ht-chip-sub { color: #E8E5DF; font-weight: 600; }
        .ht-chip-mw  { color: #9C9590; font-weight: 700; }
        .ht-chip-up .ht-chip-mw  { color: #10b981; }
        .ht-chip-down .ht-chip-mw { color: #ef4444; }
        .ht-scroll:hover { animation-play-state: paused; }
        .ht-spacer { flex: 1; }
        .ht-alerts-pill {
          flex-shrink: 0;
          display: inline-flex; align-items: center; gap: 6px;
          height: 20px;
          margin: 0 10px 0 0;
          padding: 0 10px;
          border: none;
          border-radius: 10px;
          background: #F5B731;
          color: #0F1318;
          font-family: var(--mono, "JetBrains Mono"), monospace;
          font-size: 10px;
          font-weight: 800;
          letter-spacing: 0.08em;
          cursor: pointer;
          transition: transform 120ms ease, box-shadow 120ms ease;
        }
        .ht-alerts-pill:hover {
          transform: translateY(-1px);
          box-shadow: 0 2px 6px rgba(245,183,49,0.35);
        }
        .ht-alerts-dot {
          width: 6px; height: 6px; border-radius: 3px;
          background: #0F1318;
          animation: ht-alerts-blink 2s infinite;
        }
        @keyframes ht-alerts-blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
