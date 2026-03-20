import React, { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { useGridModel } from "../../contexts/GridModelContext";

// Voltage-level color scheme (matching Squid but extended)
const VOLTAGE_COLORS = {
  400: "#e53935",  // red
  275: "#ff8f00",  // orange
  132: "#fdd835",  // yellow
  66:  "#7cb342",  // green
  33:  "#00bcd4",  // cyan
  11:  "#1565c0",  // blue
};

function getVoltageColor(kv) {
  if (kv >= 400) return VOLTAGE_COLORS[400];
  if (kv >= 275) return VOLTAGE_COLORS[275];
  if (kv >= 132) return VOLTAGE_COLORS[132];
  if (kv >= 66) return VOLTAGE_COLORS[66];
  if (kv >= 33) return VOLTAGE_COLORS[33];
  return VOLTAGE_COLORS[11];
}

function ragColor(rag) {
  if (rag === "Red") return "#e53935";
  if (rag === "Amber") return "#ff8f00";
  if (rag === "Green") return "#4caf50";
  return "#78909c";
}

// Build nodes + edges from substation data for force-directed layout
function buildGraph(substations) {
  const nodes = substations.map((s, i) => ({
    id: s.id,
    name: s.name,
    voltageKv: s.voltageKv || 33,
    rag: s.demandRag || "Green",
    headroom: s.demandHeadroomMw,
    genHeadroom: s.genHeadroomMw,
    licenceArea: s.licenceArea,
    gsp: s.gsp,
    lat: s.lat,
    lon: s.lon,
    radius: Math.max(4, Math.min(16, (s.demandHeadroomMw || 5) * 0.6)),
    _sub: s,
    x: 0,
    y: 0,
  }));

  // Build edges between substations in same GSP group
  const edges = [];
  const byGsp = {};
  for (const n of nodes) {
    if (n.gsp) (byGsp[n.gsp] ||= []).push(n);
  }
  for (const [, group] of Object.entries(byGsp)) {
    // Star topology: first node in group is "GSP hub", connect all others to it
    if (group.length < 2) continue;
    const hub = group[0];
    for (let i = 1; i < group.length; i++) {
      edges.push({ source: hub.id, target: group[i].id });
    }
  }

  return { nodes, edges };
}

export default function GridNetworkView() {
  const { filteredSubstations, selectedSubstation, selectSubstation, filters, updateFilter } = useGridModel();
  const canvasRef = useRef(null);
  const simRef = useRef(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [voltageFilter, setVoltageFilter] = useState(new Set());
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);

  const graph = useMemo(() => buildGraph(filteredSubstations), [filteredSubstations]);

  // Run force simulation
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || graph.nodes.length === 0) return;

    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    canvas.width = w * 2;
    canvas.height = h * 2;

    const nodes = graph.nodes.map(n => ({ ...n }));
    const links = graph.edges.map(e => ({ source: e.source, target: e.target }));

    nodesRef.current = nodes;
    edgesRef.current = links;

    const sim = forceSimulation(nodes)
      .force("link", forceLink(links).id(d => d.id).distance(40).strength(0.3))
      .force("charge", forceManyBody().strength(-60))
      .force("center", forceCenter(w / 2, h / 2))
      .force("collide", forceCollide(d => d.radius + 2))
      .alphaDecay(0.03);

    simRef.current = sim;

    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);

    sim.on("tick", () => {
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(transform.x, transform.y);
      ctx.scale(transform.k, transform.k);

      // Draw edges
      ctx.lineWidth = 0.5;
      for (const link of links) {
        if (typeof link.source !== "object") continue;
        ctx.strokeStyle = "rgba(255,255,255,0.08)";
        ctx.beginPath();
        ctx.moveTo(link.source.x, link.source.y);
        ctx.lineTo(link.target.x, link.target.y);
        ctx.stroke();
      }

      // Draw nodes
      for (const node of nodes) {
        if (voltageFilter.size > 0 && !voltageFilter.has(node.voltageKv)) continue;

        const isSelected = selectedSubstation?.id === node.id;
        const isHovered = hoveredNode === node.id;
        const color = getVoltageColor(node.voltageKv);
        const r = node.radius * (isSelected ? 1.6 : isHovered ? 1.3 : 1);

        // Glow for selected
        if (isSelected) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 12;
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.globalAlpha = isSelected ? 1 : 0.85;
        ctx.fill();
        ctx.globalAlpha = 1;

        // RAG border
        ctx.strokeStyle = ragColor(node.rag);
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.stroke();

        ctx.shadowColor = "transparent";
        ctx.shadowBlur = 0;

        // Label for selected/hovered
        if (isSelected || isHovered) {
          ctx.font = "10px 'IBM Plex Mono', monospace";
          ctx.fillStyle = "#f4f4f4";
          ctx.textAlign = "center";
          ctx.fillText(node.name, node.x, node.y - r - 4);
        }
      }

      ctx.restore();
    });

    return () => sim.stop();
  }, [graph, transform, selectedSubstation, hoveredNode, voltageFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle canvas click
  const handleClick = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - transform.x) / transform.k;
    const my = (e.clientY - rect.top - transform.y) / transform.k;

    for (const node of nodesRef.current) {
      const dx = mx - node.x;
      const dy = my - node.y;
      if (dx * dx + dy * dy < (node.radius + 3) ** 2) {
        selectSubstation(node._sub);
        return;
      }
    }
  }, [transform, selectSubstation]);

  // Handle mouse move for hover
  const handleMouseMove = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (e.clientX - rect.left - transform.x) / transform.k;
    const my = (e.clientY - rect.top - transform.y) / transform.k;

    let found = null;
    for (const node of nodesRef.current) {
      const dx = mx - node.x;
      const dy = my - node.y;
      if (dx * dx + dy * dy < (node.radius + 3) ** 2) {
        found = node.id;
        break;
      }
    }
    setHoveredNode(found);
    canvas.style.cursor = found ? "pointer" : "default";
  }, [transform]);

  // Zoom / pan with wheel
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      // Zoom
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      setTransform(t => ({
        ...t,
        k: Math.max(0.1, Math.min(5, t.k * factor)),
      }));
    } else {
      // Pan
      setTransform(t => ({
        ...t,
        x: t.x - e.deltaX,
        y: t.y - e.deltaY,
      }));
    }
  }, []);

  const toggleVoltage = (kv) => {
    setVoltageFilter(prev => {
      const next = new Set(prev);
      if (next.has(kv)) next.delete(kv);
      else next.add(kv);
      return next;
    });
  };

  return (
    <div className="grid-network-view">
      {/* Voltage legend / filter */}
      <div className="gnv-legend">
        {Object.entries(VOLTAGE_COLORS).map(([kv, color]) => (
          <button
            key={kv}
            className={`gnv-legend-item ${voltageFilter.size === 0 || voltageFilter.has(Number(kv)) ? "active" : "dimmed"}`}
            onClick={() => toggleVoltage(Number(kv))}
          >
            <span className="gnv-legend-dot" style={{ background: color }} />
            <span>{kv}kV</span>
          </button>
        ))}
        {voltageFilter.size > 0 && (
          <button className="gnv-legend-clear" onClick={() => setVoltageFilter(new Set())}>
            Clear
          </button>
        )}
      </div>

      {/* Stats strip */}
      <div className="gnv-stats">
        <span>{filteredSubstations.length} nodes</span>
        <span>{graph.edges.length} connections</span>
        {selectedSubstation && <span className="gnv-stats-selected">Selected: {selectedSubstation.name}</span>}
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        className="gnv-canvas"
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onWheel={handleWheel}
      />

      {/* Tooltip for hovered node */}
      {hoveredNode && (() => {
        const node = nodesRef.current.find(n => n.id === hoveredNode);
        if (!node) return null;
        return (
          <div className="gnv-tooltip" style={{ left: node.x * transform.k + transform.x + 12, top: node.y * transform.k + transform.y - 8 }}>
            <div className="gnv-tooltip-name">{node.name}</div>
            <div className="gnv-tooltip-detail">{node.voltageKv}kV | {node.licenceArea}</div>
            {node.headroom != null && (
              <div className="gnv-tooltip-detail">Headroom: {node.headroom.toFixed(1)} MW</div>
            )}
          </div>
        );
      })()}
    </div>
  );
}
