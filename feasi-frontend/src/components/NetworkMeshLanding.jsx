/**
 * NetworkMeshLanding — Animated network graph landing with centered chat input.
 * Ported from g99 repo (cprinceps/g99) chat page pattern.
 * Shows when no site is picked (welcome state).
 */
import React, { useState, useRef, useEffect, useCallback } from "react";

export default function NetworkMeshLanding({ onSend, onPickMode, streaming }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(0);
  const [input, setInput] = useState("");

  /* ── Build grid graph with jittered nodes + probabilistic edges ── */
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

  /* ── Render loop ── */
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

    // Spawn new pulses to maintain target count
    const deficit = targetCount - pulses.length;
    for (let i = 0; i < Math.min(deficit, 5); i++) spawn();

    // Advance pulses
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

    // Draw edges
    ctx.strokeStyle = "rgba(150,158,172,0.25)";
    ctx.lineWidth = 1;
    for (const e of edges) {
      const na = nodes[e.a], nb = nodes[e.b];
      ctx.beginPath(); ctx.moveTo(na.x, na.y); ctx.lineTo(nb.x, nb.y); ctx.stroke();
    }

    // Draw pulses with golden glow
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

    // Draw nodes
    ctx.fillStyle = "rgba(90,100,120,0.5)";
    for (const n of nodes) { ctx.beginPath(); ctx.arc(n.x, n.y, 3, 0, Math.PI * 2); ctx.fill(); }

    animRef.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    initGrid();
    animRef.current = requestAnimationFrame(draw);
    const onResize = () => initGrid();
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(animRef.current); window.removeEventListener("resize", onResize); };
  }, [initGrid, draw]);

  const handleSend = () => {
    if (!input.trim() || streaming) return;
    onSend?.(input.trim());
    setInput("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", zIndex: 10, pointerEvents: "auto" }}>
      {/* Animated canvas */}
      <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, zIndex: 0 }} />
      {/* Radial vignette overlay */}
      <div style={{ position: "absolute", inset: 0, zIndex: 1, pointerEvents: "none", background: "radial-gradient(ellipse at center, transparent 20%, rgba(242,243,245,0.5) 100%)" }} />

      {/* PRINCEPS logo */}
      <div style={{ position: "absolute", top: 22, left: 26, zIndex: 10, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 28, fontWeight: 800, color: "#0F1318", letterSpacing: "-0.02em", lineHeight: 1 }}>PRINCEPS</span>
        <svg width="36" height="36" viewBox="0 0 48 48" fill="none">
          <polygon points="4,4 36,4 28,16 12,16" fill="#F5B731" />
          <polygon points="12,20 28,20 36,32 4,32" fill="#F5B731" />
          <rect x="28" y="14" width="16" height="8" fill="#F5B731" />
          <rect x="4" y="36" width="24" height="8" fill="#F5B731" />
        </svg>
      </div>

      {/* Centered chat input */}
      <div style={{
        position: "absolute", inset: 0, zIndex: 5,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "80px 24px 24px", pointerEvents: "none",
      }}>
        <div style={{ width: "100%", maxWidth: 680, display: "flex", flexDirection: "column", pointerEvents: "auto" }}>
          {/* Chat input card */}
          <div style={{
            background: "rgba(255,255,255,0.95)",
            backdropFilter: "blur(24px)",
            borderRadius: 18,
            border: "1px solid rgba(0,0,0,0.08)",
            boxShadow: "0 4px 24px rgba(0,0,0,0.06), 0 1px 4px rgba(0,0,0,0.04)",
            padding: "16px 20px 14px",
            display: "flex", flexDirection: "column", gap: 10,
          }}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Welcome to Princeps — what can I help you with?"
              rows={2}
              style={{
                width: "100%", border: "none", outline: "none", resize: "none",
                fontSize: 15, lineHeight: 1.55, color: "#1A1D23", background: "transparent",
                padding: 0, fontFamily: "inherit",
              }}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              {/* Pick-on-map button */}
              <button onClick={onPickMode} style={{
                width: 36, height: 36, borderRadius: 10, border: "none",
                background: "transparent", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "#9CA3AF", transition: "color 0.2s",
              }} title="Pick site on map">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                  <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" />
                  <circle cx="12" cy="9" r="2.5" />
                </svg>
              </button>
              {/* Send button */}
              <button
                onClick={handleSend}
                disabled={!input.trim() || streaming}
                style={{
                  width: 40, height: 40, borderRadius: 12, border: "none",
                  background: input.trim() ? "#1A1D23" : "#E5E7EB",
                  cursor: input.trim() ? "pointer" : "default",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  transition: "all 0.2s",
                }}
              >
                <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
                  <path d="M4 10L16 4L12 16L10 11L4 10Z"
                    fill={input.trim() ? "#fff" : "#9CA3AF"}
                    stroke={input.trim() ? "#fff" : "#9CA3AF"}
                    strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </div>

          {/* Footer tagline */}
          <div style={{
            textAlign: "center", marginTop: 10,
            fontSize: 10, color: "rgba(100,110,130,0.45)",
            letterSpacing: "0.06em", fontFamily: "monospace",
          }}>
            PRINCEPS AI &bull; Grid connection, feasibility and asset compliance
          </div>
        </div>
      </div>

      <style>{`
        textarea::placeholder { color: #9CA3AF; }
        textarea::-webkit-scrollbar { display: none; }
      `}</style>
    </div>
  );
}
