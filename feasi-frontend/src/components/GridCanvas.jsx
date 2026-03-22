/**
 * GridCanvas — Animated electricity node network background.
 *
 * Renders a responsive canvas with:
 * - Grid of nodes with slight jitter
 * - Edges connecting neighbors (random topology)
 * - Gold pulses traveling along edges (electricity flow effect)
 * - Vignette overlay
 *
 * Adapted from the Princeps brand chat page design.
 * Use as a background layer behind any content.
 */
import React, { useRef, useEffect } from "react";

function easeInOut(t) {
  return 0.5 - 0.5 * Math.cos(t * Math.PI);
}

export default function GridCanvas({ className = "", style = {}, dark = false }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    function initGrid() {
      const dpr = window.devicePixelRatio || 1;
      const parent = canvas.parentElement;
      const rect = parent?.getBoundingClientRect() || { width: window.innerWidth, height: window.innerHeight };
      const w = rect.width;
      // Use scrollHeight to cover full scrollable content, not just viewport
      const h = Math.max(rect.height, parent?.scrollHeight || 0, window.innerHeight);
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
          if (Math.random() < 0.2) {
            const dr = idx(r + 1, c + 1);
            if (dr !== -1) add(i, dr);
          }
          if (Math.random() < 0.15) {
            const dl = idx(r + 1, c - 1);
            if (dl !== -1) add(i, dl);
          }
        }
      }

      const pulses = [];
      const spawn = () => {
        let src;
        let tries = 0;
        do {
          src = Math.floor(Math.random() * nodes.length);
          tries++;
        } while (!nodes[src].neighbors.length && tries < 20);
        if (!nodes[src].neighbors.length) return;
        const tgt = nodes[src].neighbors[Math.floor(Math.random() * nodes[src].neighbors.length)];
        pulses.push({
          from: src,
          to: tgt,
          t: 0,
          baseSpeed: 0.004 + Math.random() * 0.006,
          life: 1,
          hops: 0,
          maxHops: 2 + Math.floor(Math.random() * 5),
        });
      };

      const targetCount = Math.floor(cols * rows * 0.1);
      for (let i = 0; i < targetCount; i++) {
        spawn();
        if (pulses.length) pulses[pulses.length - 1].t = Math.random();
      }

      stateRef.current = { nodes, edges, pulses, spawn, w, h, dpr, targetCount };
    }

    function draw() {
      const s = stateRef.current;
      if (!s) return;
      const ctx = canvas.getContext("2d");
      const { nodes, edges, pulses, spawn, w, h, dpr, targetCount } = s;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // Background
      ctx.fillStyle = dark ? "#0F1318" : "#F2F3F5";
      ctx.fillRect(0, 0, w, h);

      // Spawn new pulses
      const deficit = targetCount - pulses.length;
      for (let i = 0; i < Math.min(deficit, 5); i++) spawn();

      // Update pulses
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.t += p.baseSpeed;
        if (p.t >= 1) {
          p.hops++;
          if (p.hops >= p.maxHops) {
            pulses.splice(i, 1);
            continue;
          }
          const arrived = nodes[p.to];
          const next = arrived.neighbors.filter((n) => n !== p.from);
          if (!next.length) {
            pulses.splice(i, 1);
            continue;
          }
          p.from = p.to;
          p.to = next[Math.floor(Math.random() * next.length)];
          p.t = 0;
          p.life *= 0.88;
        }
      }

      // Draw edges
      ctx.strokeStyle = dark ? "rgba(80,90,110,0.25)" : "rgba(150,158,172,0.25)";
      ctx.lineWidth = 1;
      for (const e of edges) {
        ctx.beginPath();
        ctx.moveTo(nodes[e.a].x, nodes[e.a].y);
        ctx.lineTo(nodes[e.b].x, nodes[e.b].y);
        ctx.stroke();
      }

      // Draw pulses (gold electricity)
      for (const p of pulses) {
        const na = nodes[p.from];
        const nb = nodes[p.to];
        const et = easeInOut(p.t);
        const px = na.x + (nb.x - na.x) * et;
        const py = na.y + (nb.y - na.y) * et;

        // Glow
        const g = ctx.createRadialGradient(px, py, 0, px, py, 10);
        g.addColorStop(0, `rgba(232,160,18,${0.3 * p.life})`);
        g.addColorStop(0.5, `rgba(232,160,18,${0.08 * p.life})`);
        g.addColorStop(1, "rgba(232,160,18,0)");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(px, py, 10, 0, Math.PI * 2);
        ctx.fill();

        // Core
        ctx.beginPath();
        ctx.arc(px, py, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(245,192,74,${0.9 * p.life})`;
        ctx.fill();
      }

      // Draw nodes
      ctx.fillStyle = dark ? "rgba(80,90,110,0.5)" : "rgba(90,100,120,0.5)";
      for (const n of nodes) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, 3, 0, Math.PI * 2);
        ctx.fill();
      }

      animRef.current = requestAnimationFrame(draw);
    }

    initGrid();
    animRef.current = requestAnimationFrame(draw);

    const handleResize = () => {
      cancelAnimationFrame(animRef.current);
      initGrid();
      animRef.current = requestAnimationFrame(draw);
    };
    window.addEventListener("resize", handleResize);

    // Watch parent for content size changes (scrollHeight)
    let resizeObs;
    if (canvas.parentElement && typeof ResizeObserver !== "undefined") {
      resizeObs = new ResizeObserver(handleResize);
      resizeObs.observe(canvas.parentElement);
    }

    return () => {
      cancelAnimationFrame(animRef.current);
      window.removeEventListener("resize", handleResize);
      resizeObs?.disconnect();
    };
  }, [dark]);

  return (
    <>
      <canvas
        ref={canvasRef}
        className={className}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          zIndex: 0,
          pointerEvents: "none",
          ...style,
        }}
      />
      {/* Vignette overlay */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          zIndex: 1,
          pointerEvents: "none",
          background: dark
            ? "radial-gradient(ellipse at center, transparent 30%, rgba(15,19,24,0.35) 100%)"
            : "radial-gradient(ellipse at center, transparent 40%, rgba(242,243,245,0.3) 100%)",
        }}
      />
    </>
  );
}
