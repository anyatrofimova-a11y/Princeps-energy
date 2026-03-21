import React, { useEffect, useState, useRef, useCallback } from "react";

/* ── Animated network mesh background (extracted from NetworkMeshLanding) ── */
function NetworkMeshBg() {
  const canvasRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(0);

  const initGrid = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";

    const spacing = 72;
    const jitter = 12;
    const cols = Math.ceil(w / spacing) + 2;
    const rows = Math.ceil(h / spacing) + 2;
    const ox = -spacing * 0.5;
    const oy = -spacing * 0.5;

    const nodes = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        nodes.push({
          x: c * spacing + ox + (Math.random() - 0.5) * jitter * 2,
          y: r * spacing + oy + (Math.random() - 0.5) * jitter * 2,
          neighbors: [],
        });
      }
    }

    const idx = (r, c) => (r < 0 || r >= rows || c < 0 || c >= cols ? -1 : r * cols + c);
    const edges = [];
    const seen = new Set();
    const add = (a, b) => {
      const k = Math.min(a, b) + ":" + Math.max(a, b);
      if (seen.has(k)) return;
      seen.add(k);
      edges.push({ a, b });
      nodes[a].neighbors.push(b);
      nodes[b].neighbors.push(a);
    };

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const i = idx(r, c);
        const rt = idx(r, c + 1);
        if (rt !== -1 && Math.random() < 0.92) add(i, rt);
        const dn = idx(r + 1, c);
        if (dn !== -1 && Math.random() < 0.92) add(i, dn);
        if (Math.random() < 0.2) { const dr = idx(r + 1, c + 1); if (dr !== -1) add(i, dr); }
        if (Math.random() < 0.15) { const dl = idx(r + 1, c - 1); if (dl !== -1) add(i, dl); }
      }
    }

    const pulses = [];
    const spawn = () => {
      let src, tries = 0;
      do { src = Math.floor(Math.random() * nodes.length); tries++; } while (nodes[src].neighbors.length === 0 && tries < 20);
      if (nodes[src].neighbors.length === 0) return;
      const tgt = nodes[src].neighbors[Math.floor(Math.random() * nodes[src].neighbors.length)];
      pulses.push({ from: src, to: tgt, t: 0, baseSpeed: 0.004 + Math.random() * 0.006, life: 1, hops: 0, maxHops: 2 + Math.floor(Math.random() * 5) });
    };

    const targetCount = Math.floor((cols * rows) * 0.10);
    for (let i = 0; i < targetCount; i++) {
      spawn();
      pulses[pulses.length - 1].t = Math.random();
    }

    stateRef.current = { nodes, edges, pulses, spawn, w, h, dpr, targetCount };
  }, []);

  const easeInOut = (t) => 0.5 - 0.5 * Math.cos(t * Math.PI);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const S = stateRef.current;
    if (!canvas || !S) return;
    const ctx = canvas.getContext("2d");
    const { nodes, edges, pulses, spawn, w, h, dpr, targetCount } = S;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#F2F3F5";
    ctx.fillRect(0, 0, w, h);

    const deficit = targetCount - pulses.length;
    for (let i = 0; i < Math.min(deficit, 5); i++) spawn();

    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.t += p.baseSpeed;
      if (p.t >= 1) {
        p.hops++;
        if (p.hops >= p.maxHops) { pulses.splice(i, 1); continue; }
        const arrived = nodes[p.to];
        const next = arrived.neighbors.filter((n) => n !== p.from);
        if (!next.length) { pulses.splice(i, 1); continue; }
        p.from = p.to;
        p.to = next[Math.floor(Math.random() * next.length)];
        p.t = 0;
        p.life *= 0.88;
      }
    }

    ctx.strokeStyle = "rgba(150,158,172,0.18)";
    ctx.lineWidth = 1;
    for (const e of edges) {
      const na = nodes[e.a], nb = nodes[e.b];
      ctx.beginPath(); ctx.moveTo(na.x, na.y); ctx.lineTo(nb.x, nb.y); ctx.stroke();
    }

    for (const p of pulses) {
      const na = nodes[p.from], nb = nodes[p.to];
      const easedT = easeInOut(p.t);
      const px = na.x + (nb.x - na.x) * easedT;
      const py = na.y + (nb.y - na.y) * easedT;
      const gr = 10;
      const g = ctx.createRadialGradient(px, py, 0, px, py, gr);
      g.addColorStop(0, `rgba(232,160,18,${0.3 * p.life})`);
      g.addColorStop(0.5, `rgba(232,160,18,${0.08 * p.life})`);
      g.addColorStop(1, "rgba(232,160,18,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, gr, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(px, py, 2.2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(245,192,74,${0.9 * p.life})`; ctx.fill();
    }

    ctx.fillStyle = "rgba(90,100,120,0.4)";
    for (const n of nodes) { ctx.beginPath(); ctx.arc(n.x, n.y, 2.5, 0, Math.PI * 2); ctx.fill(); }

    animRef.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    initGrid();
    animRef.current = requestAnimationFrame(draw);
    const onResize = () => initGrid();
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(animRef.current); window.removeEventListener("resize", onResize); };
  }, [initGrid, draw]);

  return (
    <>
      <canvas ref={canvasRef} className="startup-mesh-canvas" />
      <div className="startup-mesh-vignette" />
    </>
  );
}

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
