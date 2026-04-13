import React, { useEffect, useRef } from "react";

export default function CapabilitiesPage({ onExit }) {
  const canvasRef = useRef(null);
  const animRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let animFrame = 0;
    let state = null;

    function easeInOut(t) { return 0.5 - 0.5 * Math.cos(t * Math.PI); }

    function initGrid() {
      const dpr = window.devicePixelRatio || 1;
      const w = window.innerWidth, h = window.innerHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + "px"; canvas.style.height = h + "px";
      const spacing = 72, jitter = 12;
      const cols = Math.ceil(w / spacing) + 2, rows = Math.ceil(h / spacing) + 2;
      const ox = -spacing * 0.5, oy = -spacing * 0.5;
      const nodes = [];
      for (let r = 0; r < rows; r++)
        for (let c = 0; c < cols; c++)
          nodes.push({ x: c * spacing + ox + (Math.random() - 0.5) * jitter * 2, y: r * spacing + oy + (Math.random() - 0.5) * jitter * 2, neighbors: [] });
      const idx = (r, c) => (r < 0 || r >= rows || c < 0 || c >= cols ? -1 : r * cols + c);
      const edges = [], seen = new Set();
      const add = (a, b) => {
        const k = Math.min(a, b) + ":" + Math.max(a, b);
        if (seen.has(k)) return; seen.add(k); edges.push({ a, b });
        nodes[a].neighbors.push(b); nodes[b].neighbors.push(a);
      };
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const i = idx(r, c);
        const rt = idx(r, c + 1); if (rt !== -1 && Math.random() < 0.92) add(i, rt);
        const dn = idx(r + 1, c); if (dn !== -1 && Math.random() < 0.92) add(i, dn);
        if (Math.random() < 0.2) { const dr = idx(r + 1, c + 1); if (dr !== -1) add(i, dr); }
        if (Math.random() < 0.15) { const dl = idx(r + 1, c - 1); if (dl !== -1) add(i, dl); }
      }
      const pulses = [];
      const spawn = () => {
        let src, tries = 0;
        do { src = Math.floor(Math.random() * nodes.length); tries++; } while (!nodes[src].neighbors.length && tries < 20);
        if (!nodes[src].neighbors.length) return;
        const tgt = nodes[src].neighbors[Math.floor(Math.random() * nodes[src].neighbors.length)];
        pulses.push({ from: src, to: tgt, t: 0, baseSpeed: 0.004 + Math.random() * 0.006, life: 1, hops: 0, maxHops: 2 + Math.floor(Math.random() * 5) });
      };
      const targetCount = Math.floor(cols * rows * 0.10);
      for (let i = 0; i < targetCount; i++) { spawn(); pulses[pulses.length - 1].t = Math.random(); }
      state = { nodes, edges, pulses, spawn, w, h, dpr, targetCount };
    }

    function draw() {
      if (!state) return;
      const ctx = canvas.getContext("2d");
      const { nodes, edges, pulses, spawn, w, h, dpr, targetCount } = state;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#F2F3F5"; ctx.fillRect(0, 0, w, h);
      const deficit = targetCount - pulses.length;
      for (let i = 0; i < Math.min(deficit, 5); i++) spawn();
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i]; p.t += p.baseSpeed;
        if (p.t >= 1) {
          p.hops++;
          if (p.hops >= p.maxHops) { pulses.splice(i, 1); continue; }
          const arrived = nodes[p.to], next = arrived.neighbors.filter(n => n !== p.from);
          if (!next.length) { pulses.splice(i, 1); continue; }
          p.from = p.to; p.to = next[Math.floor(Math.random() * next.length)]; p.t = 0; p.life *= 0.88;
        }
      }
      ctx.strokeStyle = "rgba(150,158,172,0.22)"; ctx.lineWidth = 1;
      for (const e of edges) { ctx.beginPath(); ctx.moveTo(nodes[e.a].x, nodes[e.a].y); ctx.lineTo(nodes[e.b].x, nodes[e.b].y); ctx.stroke(); }
      for (const p of pulses) {
        const na = nodes[p.from], nb = nodes[p.to], et = easeInOut(p.t);
        const px = na.x + (nb.x - na.x) * et, py = na.y + (nb.y - na.y) * et;
        const g = ctx.createRadialGradient(px, py, 0, px, py, 10);
        g.addColorStop(0, `rgba(232,160,18,${0.3 * p.life})`);
        g.addColorStop(0.5, `rgba(232,160,18,${0.08 * p.life})`);
        g.addColorStop(1, "rgba(232,160,18,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, 10, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(px, py, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(245,192,74,${0.9 * p.life})`; ctx.fill();
      }
      ctx.fillStyle = "rgba(90,100,120,0.45)";
      for (const n of nodes) { ctx.beginPath(); ctx.arc(n.x, n.y, 3, 0, Math.PI * 2); ctx.fill(); }
      animFrame = requestAnimationFrame(draw);
    }

    initGrid();
    animFrame = requestAnimationFrame(draw);

    const onResize = () => { cancelAnimationFrame(animFrame); initGrid(); animFrame = requestAnimationFrame(draw); };
    window.addEventListener("resize", onResize);
    animRef.current = animFrame;

    return () => {
      cancelAnimationFrame(animFrame);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const cards = [
    { cls: "cap-c1", tag: "Advanced GIS", tagColor: "cap-tag-cyan", img: "/princeps-slides-assets/gis-tools.png", imgStyle: {}, name: "Geospatial Intelligence & Site Analysis", desc: "Satellite imagery, boundary drawing, exclusion zones, buffer analysis, terrain, 10+ constraint layers" },
    { cls: "cap-c2", tag: "AI Copilot", tagColor: "cap-tag-purple", img: "/princeps-slides-assets/copilot-feasibility.png", imgStyle: {}, name: "AI-Powered Rapid Feasibility", desc: "Drop a pin, instant 5-point assessment — grid, solar yield, constraints, planning, GO/CAUTION verdict" },
    { cls: "cap-c3", tag: "Grid Connection", tagColor: "cap-tag-orange", img: "/princeps-slides-assets/grid-connection.png", imgStyle: { objectPosition: "100% 5%", transform: "scale(1.35)", transformOrigin: "100% 5%" }, name: "Grid Connection Feasibility", desc: "P10/P50/P90 cost estimates, connection timeline, candidate substations, cost breakdown" },
    { cls: "cap-c4", tag: "Site Analysis", tagColor: "cap-tag-blue", img: "/princeps-slides-assets/grid-substations.png", imgStyle: {}, name: "Grid Network & Substation Intelligence", desc: "Voltage-coded transmission lines, substation headroom, rated capacity, match scoring" },
    { cls: "cap-c6", tag: "DC Twin", tagColor: "cap-tag-red", img: "/princeps-slides-assets/dc-twin.png", imgStyle: {}, name: "Data Centre Digital Twin", desc: "3D auto-design 1\u2013500MW — racks, cooling, UPS, switchgear, power chain, ASHRAE monitoring" },
    { cls: "cap-c7", tag: "Pipeline", tagColor: "cap-tag-orange", img: "/princeps-slides-assets/pipeline.png", imgStyle: { objectPosition: "left top" }, name: "Project Pipeline & Command Centre", desc: "26 sites, 21.7GW — 8-stage kanban, GO/CAUTION verdicts, live grid metrics, REPD market import" },
    { cls: "cap-c8", tag: "Site Design", tagColor: "cap-tag-green", img: "/princeps-slides-assets/3d-solar.png", imgStyle: {}, name: "3D Hybrid Site Designer", desc: "Auto-layout solar + BESS on 3D terrain — tilt, spacing, azimuth, hybrid split, export KML" },
  ];

  return (
    <div className="cap-page">
      <canvas ref={canvasRef} className="cap-grid-canvas" />
      <div className="cap-slide">
        <div className="cap-header">
          <div className="cap-header-left">
            <h1 className="cap-htitle">PLATFORM <em>CAPABILITIES</em></h1>
            <div className="cap-subtitle">The AI copilot for energy development — site selection to grid connection in minutes, not months</div>
          </div>
          {onExit && (
            <button className="cap-back-btn" onClick={onExit} title="Back to Princeps">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          )}
        </div>

        <div className="cap-bento">
          {cards.map((c, i) => (
            <div key={i} className={`cap-card ${c.cls}`}>
              <div className={`cap-card-tag ${c.tagColor}`}>{c.tag}</div>
              <img src={c.img} alt={c.tag} style={c.imgStyle} />
              <div className="cap-card-label">
                <div className="cap-card-name">{c.name}</div>
                <div className="cap-card-desc">{c.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="cap-bottom-strip">
          <div className="cap-stat"><div className="cap-stat-val"><em>3-6 months</em> &rarr; minutes</div><div className="cap-stat-lbl">Time to feasibility verdict</div></div>
          <div className="cap-stat-div" />
          <div className="cap-stat"><div className="cap-stat-val"><em>&pound;150k+</em> displaced</div><div className="cap-stat-lbl">Consultant cost per project</div></div>
          <div className="cap-stat-div" />
          <div className="cap-stat"><div className="cap-stat-val"><em>6</em> DNOs &middot; <em>600+</em> substations</div><div className="cap-stat-lbl">Real grid data coverage</div></div>
          <div className="cap-stat-div" />
          <div className="cap-stat"><div className="cap-stat-val"><em>1</em> platform</div><div className="cap-stat-lbl">Replaces 8+ siloed tools</div></div>
        </div>
      </div>
    </div>
  );
}
