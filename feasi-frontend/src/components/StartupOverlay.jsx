import React, { useEffect, useState, useRef, useCallback } from "react";

/* ── Recent sites from localStorage ── */
function loadRecentSites() {
  try {
    const raw = localStorage.getItem("princeps_recent_sites");
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return [];
}

export function saveRecentSite(site) {
  try {
    const existing = loadRecentSites().filter(s => s.id !== site.id);
    const updated = [site, ...existing].slice(0, 8);
    localStorage.setItem("princeps_recent_sites", JSON.stringify(updated));
  } catch { /* ignore */ }
}

const INTENT_CARDS = [
  {
    id: "find",
    title: "Find a Site",
    desc: "Search by postcode, coordinates, or browse the map",
    color: "#D4A018",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
      </svg>
    ),
  },
  {
    id: "assess",
    title: "Assess a Site",
    desc: "Run AI feasibility study with solar, grid, and planning analysis",
    color: "#16a34a",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        <path d="M9 14l2 2 4-4" />
      </svg>
    ),
  },
  {
    id: "grid",
    title: "Grid Connection Study",
    desc: "Assess connection feasibility, capacity, and cost estimates",
    color: "#0891b2",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
      </svg>
    ),
  },
  {
    id: "portfolio",
    title: "Review Portfolio",
    desc: "View project pipeline, verdicts, and portfolio analytics",
    color: "#7c3aed",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
      </svg>
    ),
  },
];

const VERDICT_COLORS = {
  GO: "#16a34a",
  CAUTION: "#d97706",
  "NO-GO": "#dc2626",
};

export default function StartupOverlay({ onReady, onIntent }) {
  const [readiness, setReadiness] = useState(null);
  const [coreReady, setCoreReady] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [recentSites, setRecentSites] = useState([]);
  const abortRef = useRef(null);

  // Load recent sites
  useEffect(() => {
    setRecentSites(loadRecentSites());
  }, []);

  // Poll backend readiness in background
  useEffect(() => {
    const ac = new AbortController();
    abortRef.current = ac;

    const poll = async () => {
      if (ac.signal.aborted) return;
      try {
        const res = await fetch("/api/readiness", { signal: ac.signal });
        if (res.ok) {
          const data = await res.json();
          setReadiness(data);
          if (data.core_ready) {
            setCoreReady(true);
            return; // stop polling
          }
        }
      } catch (err) {
        if (err.name === "AbortError") return;
      }
      setTimeout(poll, 1500);
    };

    poll();
    return () => ac.abort();
  }, []);

  const handleIntentClick = useCallback((intentId) => {
    if (!coreReady) return;
    setDismissed(true);
    onReady?.(readiness);
    // Small delay to let overlay fade out
    setTimeout(() => {
      onIntent?.(intentId);
    }, 100);
  }, [coreReady, readiness, onReady, onIntent]);

  const handleRecentSiteClick = useCallback((site) => {
    if (!coreReady) return;
    setDismissed(true);
    onReady?.(readiness);
    setTimeout(() => {
      onIntent?.("recent", site);
    }, 100);
  }, [coreReady, readiness, onReady, onIntent]);

  if (dismissed) return null;

  return (
    <div className="startup-overlay">
      <div className="startup-card">
        {/* Logo */}
        <div className="startup-logo-row">
          <div className="startup-logo-mark">P</div>
          <span className="startup-logo-text">PRINCEPS</span>
        </div>

        {/* Heading */}
        <h1 className="startup-heading">What would you like to do?</h1>

        {/* Loading state indicator */}
        {!coreReady && (
          <div className="startup-loading-hint">
            <div className="startup-spinner" />
            <span>Connecting to backend...</span>
          </div>
        )}

        {/* Intent cards 2x2 */}
        <div className="startup-intent-grid">
          {INTENT_CARDS.map(card => (
            <button
              key={card.id}
              className={`startup-intent-card${!coreReady ? " startup-intent-disabled" : ""}`}
              onClick={() => handleIntentClick(card.id)}
              disabled={!coreReady}
              style={{ "--intent-color": card.color }}
            >
              <div className="startup-intent-icon" style={{ color: card.color }}>
                {card.icon}
              </div>
              <div className="startup-intent-body">
                <div className="startup-intent-title">{card.title}</div>
                <div className="startup-intent-desc">{card.desc}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Recent Sites */}
        {recentSites.length > 0 && (
          <div className="startup-recent">
            <div className="startup-recent-label">Recent Sites</div>
            <div className="startup-recent-row">
              {recentSites.slice(0, 4).map((site, i) => (
                <button
                  key={site.id || i}
                  className={`startup-recent-card${!coreReady ? " startup-intent-disabled" : ""}`}
                  onClick={() => handleRecentSiteClick(site)}
                  disabled={!coreReady}
                >
                  <div className="startup-recent-name">{site.name || "Unnamed Site"}</div>
                  {site.verdict && (
                    <span
                      className="startup-verdict-badge"
                      style={{ background: VERDICT_COLORS[site.verdict] || "#666" }}
                    >
                      {site.verdict}
                    </span>
                  )}
                  <div className="startup-recent-meta">
                    {site.lastModified || ""}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Keyboard hint */}
        <div className="startup-hint">
          Press <kbd>&#8984;K</kbd> anytime for search
        </div>
      </div>

      <style>{`
        @keyframes startup-fadeIn {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes startup-spin {
          to { transform: rotate(360deg); }
        }
        @keyframes startup-cardIn {
          from { opacity: 0; transform: scale(0.96) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
      `}</style>
    </div>
  );
}
