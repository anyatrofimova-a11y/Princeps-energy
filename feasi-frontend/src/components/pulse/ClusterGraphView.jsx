/**
 * ClusterGraphView — raw d3-force + canvas force-directed graph.
 *
 * Renders the cluster dependency graph from /api/cluster/graph/{study_id}.geojson
 * using d3-force for layout and a Canvas 2D context for draw (no React Flow —
 * the user specified raw d3-force + canvas for 1000+ node performance).
 *
 * Interactions:
 *   • Hover → tooltip with project details
 *   • Click → emits `princeps-cluster-node-click` event with the project_id
 *   • "Simulate withdrawal" → calls POST /api/cluster/{project_id}/withdraw,
 *     animates affected edges thickening with cost-delta labels above siblings
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  forceSimulation, forceManyBody, forceLink, forceCenter, forceCollide,
} from "d3-force";
import api from "../../services/api";

const DARK = {
  bg:        "#0b0e13",
  panel:     "#12151c",
  border:    "rgba(255,255,255,0.1)",
  text:      "#e2e8f0",
  textDim:   "#94a3b8",
  gold:      "#f5b731",
  green:     "#10b981",
  amber:     "#f59e0b",
  red:       "#ef4444",
  blue:      "#3b82f6",
  purple:    "#a855f7",
};

const ST = {
  root: {
    position: "relative",
    width: "100%",
    height: "100%",
    minHeight: 320,
    background: DARK.panel,
    borderRadius: 10,
    overflow: "hidden",
  },
  canvas: { display: "block", width: "100%", height: "100%" },
  tooltip: {
    position: "absolute",
    background: "rgba(11, 14, 19, 0.96)",
    color: DARK.text,
    border: `1px solid ${DARK.border}`,
    borderRadius: 6,
    padding: "8px 10px",
    fontSize: 11,
    fontFamily: "'DM Sans', sans-serif",
    pointerEvents: "none",
    minWidth: 160,
    zIndex: 10,
    boxShadow: "0 4px 12px rgba(0,0,0,0.6)",
  },
  toolbar: {
    position: "absolute",
    top: 10,
    left: 10,
    right: 10,
    display: "flex",
    gap: 8,
    alignItems: "center",
    zIndex: 8,
    pointerEvents: "none",
  },
  button: {
    padding: "5px 10px",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.4,
    background: "rgba(245, 183, 49, 0.12)",
    color: DARK.gold,
    border: `1px solid ${DARK.gold}55`,
    borderRadius: 5,
    cursor: "pointer",
    pointerEvents: "auto",
    textTransform: "uppercase",
  },
  select: {
    padding: "5px 8px",
    fontSize: 10,
    background: "rgba(255,255,255,0.04)",
    color: DARK.text,
    border: `1px solid ${DARK.border}`,
    borderRadius: 5,
    fontFamily: "'DM Sans', sans-serif",
    pointerEvents: "auto",
    minWidth: 180,
  },
  stats: {
    marginLeft: "auto",
    fontSize: 10,
    color: DARK.textDim,
    fontFamily: "'JetBrains Mono', monospace",
    pointerEvents: "none",
  },
  empty: {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: DARK.textDim,
    fontSize: 12,
    flexDirection: "column",
    gap: 10,
  },
};


export default function ClusterGraphView() {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const simRef = useRef(null);
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  const pulseRef = useRef({});   // edge_id → { until: timestamp, delta_gbp }
  const hoverRef = useRef(null);
  const animRef = useRef(null);

  const [studies, setStudies] = useState([]);
  const [selectedStudy, setSelectedStudy] = useState("");
  const [tooltip, setTooltip] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  // Load studies list on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api.cluster.studies();
        if (cancelled) return;
        setStudies(list);
        if (list.length && !selectedStudy) {
          setSelectedStudy(list[0].study_id);
        } else if (list.length === 0) {
          setMessage("No cluster studies yet. Run POST /api/cluster/ingest first.");
        }
      } catch (e) {
        setMessage(`Failed to load studies: ${e.message || e}`);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load + lay out a study
  const loadStudy = useCallback(async (studyId) => {
    if (!studyId) return;
    setLoading(true);
    setMessage("");
    try {
      const fc = await api.cluster.graphGeojson(studyId);
      const features = fc.features || [];

      // Extract nodes (projects + upgrades) and edges
      const projects = features.filter(f => f.properties?.kind === "project");
      const upgrades = features.filter(f => f.properties?.kind === "upgrade");
      const edgesRaw = features.filter(f => f.properties?.kind === "edge");

      const nodes = [
        ...projects.map(p => ({
          id: `p:${p.properties.project_id}`,
          kind: "project",
          project_id: p.properties.project_id,
          cost: p.properties.allocated_cost_gbp || 0,
          upgrade_count: p.properties.upgrade_count || 0,
          x: Math.random() * 500,
          y: Math.random() * 400,
        })),
        ...upgrades.map(u => ({
          id: `u:${u.properties.upgrade_id}`,
          kind: "upgrade",
          upgrade_id: u.properties.upgrade_id,
          description: u.properties.description,
          cost: u.properties.cost_gbp || 0,
          voltage_kv: u.properties.voltage_kv,
          x: Math.random() * 500,
          y: Math.random() * 400,
        })),
      ];
      const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
      const edges = edgesRaw
        .map(e => ({
          id: `e:${e.properties.from}:${e.properties.to}`,
          source: nodeById[`p:${e.properties.from}`],
          target: nodeById[`p:${e.properties.to}`],
          shared_cost: e.properties.shared_cost_gbp || 0,
          strength: e.properties.strength || 0,
          project_from: e.properties.from,
          project_to: e.properties.to,
        }))
        .filter(e => e.source && e.target);

      nodesRef.current = nodes;
      edgesRef.current = edges;

      // (Re)start the simulation
      if (simRef.current) simRef.current.stop();
      simRef.current = forceSimulation(nodes)
        .force("charge", forceManyBody().strength(-140))
        .force("link", forceLink(edges).id(n => n.id).distance(70).strength(0.4))
        .force("center", forceCenter((canvasRef.current?.width || 600) / 2, (canvasRef.current?.height || 400) / 2))
        .force("collide", forceCollide(14))
        .alphaDecay(0.035)
        .on("tick", draw);
    } catch (e) {
      setMessage(`Failed to load graph: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (selectedStudy) loadStudy(selectedStudy); }, [selectedStudy, loadStudy]);

  // Resize canvas to container
  useEffect(() => {
    const handleResize = () => {
      const c = canvasRef.current;
      const box = containerRef.current?.getBoundingClientRect();
      if (!c || !box) return;
      const dpr = window.devicePixelRatio || 1;
      c.width = box.width * dpr;
      c.height = box.height * dpr;
      c.style.width = `${box.width}px`;
      c.style.height = `${box.height}px`;
      const ctx = c.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Canvas draw — called on every simulation tick + animation frame
  const draw = useCallback(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = c.width / dpr, h = c.height / dpr;
    ctx.clearRect(0, 0, w, h);

    // Background gradient
    const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h));
    g.addColorStop(0, "rgba(245, 183, 49, 0.03)");
    g.addColorStop(1, "rgba(11, 14, 19, 0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    const now = Date.now();

    // Edges
    for (const e of edgesRef.current) {
      if (!e.source?.x || !e.target?.x) continue;
      const pulse = pulseRef.current[e.id];
      const pulseActive = pulse && pulse.until > now;
      const alpha = 0.2 + (e.strength || 0) * 0.5 + (pulseActive ? 0.4 : 0);
      const width = 0.8 + (e.strength || 0) * 3.5 + (pulseActive ? 3 : 0);
      ctx.strokeStyle = pulseActive ? DARK.gold : `rgba(148, 163, 184, ${Math.min(1, alpha)})`;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.stroke();
    }

    // Nodes
    for (const n of nodesRef.current) {
      if (n.x == null) continue;
      const isHover = hoverRef.current === n;
      if (n.kind === "project") {
        const r = 6 + Math.min(10, (n.cost || 0) / 5_000_000);
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        const nodeColour = pulseRef.current[`node:${n.id}`]?.until > now
          ? DARK.amber
          : DARK.blue;
        ctx.fillStyle = nodeColour;
        ctx.fill();
        ctx.strokeStyle = isHover ? DARK.gold : "rgba(255,255,255,0.4)";
        ctx.lineWidth = isHover ? 2.5 : 1;
        ctx.stroke();
      } else {
        // Upgrade diamond
        const r = 8;
        ctx.save();
        ctx.translate(n.x, n.y);
        ctx.rotate(Math.PI / 4);
        ctx.fillStyle = DARK.purple;
        ctx.fillRect(-r, -r, r * 2, r * 2);
        ctx.strokeStyle = isHover ? DARK.gold : "rgba(255,255,255,0.4)";
        ctx.lineWidth = isHover ? 2.5 : 1;
        ctx.strokeRect(-r, -r, r * 2, r * 2);
        ctx.restore();
      }
    }

    // Delta labels above pulsing nodes
    ctx.font = "bold 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    for (const key in pulseRef.current) {
      const p = pulseRef.current[key];
      if (!p || p.until < now) continue;
      if (!key.startsWith("node:")) continue;
      const nodeId = key.slice(5);
      const n = nodesRef.current.find(x => x.id === nodeId);
      if (!n) continue;
      const deltaText = p.delta_gbp >= 0
        ? `+£${(p.delta_gbp / 1e6).toFixed(2)}m`
        : `-£${(Math.abs(p.delta_gbp) / 1e6).toFixed(2)}m`;
      ctx.fillStyle = p.delta_gbp > 0 ? DARK.red : DARK.green;
      ctx.fillText(deltaText, n.x, n.y - 18);
    }
  }, []);

  // Animation loop — keeps pulses ticking after the d3 simulation settles
  useEffect(() => {
    const loop = () => {
      draw();
      animRef.current = requestAnimationFrame(loop);
    };
    animRef.current = requestAnimationFrame(loop);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [draw]);

  // Mouse interaction
  const handleMouseMove = (e) => {
    const c = canvasRef.current;
    if (!c) return;
    const rect = c.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    let hit = null;
    for (const n of nodesRef.current) {
      if (n.x == null) continue;
      const dx = n.x - mx, dy = n.y - my;
      const r = n.kind === "project" ? 8 + (n.cost || 0) / 5_000_000 : 10;
      if (dx * dx + dy * dy <= r * r + 10) { hit = n; break; }
    }
    hoverRef.current = hit;
    if (hit) {
      setTooltip({
        x: e.clientX - rect.left + 14,
        y: e.clientY - rect.top + 14,
        node: hit,
      });
    } else {
      setTooltip(null);
    }
  };

  const handleClick = async () => {
    const hit = hoverRef.current;
    if (!hit || hit.kind !== "project") return;
    window.dispatchEvent(new CustomEvent("princeps-cluster-node-click", {
      detail: { project_id: hit.project_id },
    }));
  };

  const simulateWithdrawal = useCallback(async () => {
    const hit = hoverRef.current;
    if (!hit || hit.kind !== "project") {
      setMessage("Hover over a project node first, then press Simulate withdrawal");
      return;
    }
    setLoading(true);
    setMessage(`Simulating withdrawal of ${hit.project_id}…`);
    try {
      const res = await api.cluster.withdraw(hit.project_id);
      // Pulse the affected project nodes + edges
      const until = Date.now() + 5000;
      for (const [sibling_id, delta] of Object.entries(res.cost_delta_by_project || {})) {
        pulseRef.current[`node:p:${sibling_id}`] = { until, delta_gbp: delta };
      }
      // Pulse affected edges
      for (const e of edgesRef.current) {
        if (res.affected_projects?.includes(e.project_from) || res.affected_projects?.includes(e.project_to)) {
          pulseRef.current[e.id] = { until };
        }
      }
      setMessage(`${res.affected_projects?.length || 0} siblings repriced · ${res.events?.length || 0} events emitted`);
      // Reload after 2 seconds to reflect the new allocations
      setTimeout(() => loadStudy(selectedStudy), 2200);
    } catch (e) {
      setMessage(`Withdraw failed: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  }, [selectedStudy, loadStudy]);

  return (
    <div ref={containerRef} style={ST.root}>
      <canvas
        ref={canvasRef}
        style={ST.canvas}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => { hoverRef.current = null; setTooltip(null); }}
        onClick={handleClick}
      />

      <div style={ST.toolbar}>
        <select
          style={ST.select}
          value={selectedStudy}
          onChange={(e) => setSelectedStudy(e.target.value)}
        >
          {studies.length === 0 && <option value="">No studies yet</option>}
          {studies.map(s => (
            <option key={s.study_id} value={s.study_id}>
              {s.study_id} · {s.project_count}p / {s.upgrade_count}u · £{Math.round((s.total_upgrade_cost_gbp || 0) / 1e6)}M
            </option>
          ))}
        </select>
        <button style={ST.button} onClick={simulateWithdrawal} disabled={loading}>
          Simulate withdrawal
        </button>
        <button style={ST.button} onClick={() => loadStudy(selectedStudy)} disabled={loading}>
          Reload
        </button>
        <div style={ST.stats}>
          {nodesRef.current.length} nodes · {edgesRef.current.length} edges
        </div>
      </div>

      {message && (
        <div style={{
          position: "absolute",
          bottom: 10,
          left: 10,
          right: 10,
          fontSize: 10,
          color: DARK.textDim,
          fontStyle: "italic",
          fontFamily: "'JetBrains Mono', monospace",
          pointerEvents: "none",
        }}>{message}</div>
      )}

      {tooltip && (
        <div style={{ ...ST.tooltip, left: tooltip.x, top: tooltip.y }}>
          {tooltip.node.kind === "project" ? (
            <>
              <div style={{ fontWeight: 700, color: DARK.gold, marginBottom: 4 }}>
                {tooltip.node.project_id}
              </div>
              <div>Exposure: £{((tooltip.node.cost || 0) / 1e6).toFixed(2)}m</div>
              <div>Upgrades: {tooltip.node.upgrade_count}</div>
              <div style={{ marginTop: 4, color: DARK.textDim, fontSize: 9 }}>
                Click to select · Hover + button to simulate
              </div>
            </>
          ) : (
            <>
              <div style={{ fontWeight: 700, color: DARK.purple, marginBottom: 4 }}>
                Upgrade #{tooltip.node.upgrade_id}
              </div>
              <div style={{ fontSize: 10 }}>{tooltip.node.description}</div>
              <div>£{((tooltip.node.cost || 0) / 1e6).toFixed(2)}m · {tooltip.node.voltage_kv || "—"} kV</div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
