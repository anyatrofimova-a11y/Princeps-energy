import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
} from "d3-force";

/* ── Constants ──────────────────────────────────────────────────────────── */

const NODE_TYPES = {
  GridSupplyPoint:      { color: "#f44336", radius: 18, label: "GSP (400/275 kV)",  voltage: 400 },
  BulkSupplyPoint:      { color: "#ff9800", radius: 13, label: "BSP (132 kV)",      voltage: 132 },
  PrimarySubstation:    { color: "#4caf50", radius: 9,  label: "Primary (33/66 kV)", voltage: 33  },
  SecondarySubstation:  { color: "#D4A018", radius: 5,  label: "Secondary (11 kV)",  voltage: 11  },
};

const EDGE_VOLTAGE_COLORS = {
  400: "#f44336",
  275: "#f44336",
  132: "#ff9800",
  66:  "#4caf50",
  33:  "#4caf50",
  11:  "#D4A018",
};

function edgeColor(voltage_kv) {
  if (voltage_kv >= 275) return "#f44336";
  if (voltage_kv >= 132) return "#ff9800";
  if (voltage_kv >= 33)  return "#4caf50";
  if (voltage_kv >= 11)  return "#D4A018";
  return "#555";
}

function nodeConfig(type) {
  return NODE_TYPES[type] || { color: "#555", radius: 6, label: type, voltage: 0 };
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${v.toFixed(1)} MW`;
}

/* ── Styles ─────────────────────────────────────────────────────────────── */

const S = {
  root: {
    position: "relative",
    width: "100%",
    height: "100%",
    display: "flex",
    flexDirection: "column",
    background: "#F2F3F5",
    color: "var(--cds-text-primary, #1A1D23)",
    fontFamily: "'Roboto', -apple-system, BlinkMacSystemFont, sans-serif",
    overflow: "hidden",
  },
  topBar: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "8px 14px",
    background: "var(--cds-layer-01, #ffffff)",
    borderBottom: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    zIndex: 20,
    flexShrink: 0,
  },
  searchInput: {
    flex: 1,
    maxWidth: 320,
    padding: "6px 12px",
    borderRadius: 6,
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    background: "var(--cds-layer-02, #F7F8FA)",
    color: "var(--cds-text-primary, #1A1D23)",
    fontSize: 13,
    outline: "none",
  },
  badge: {
    padding: "3px 10px",
    borderRadius: 12,
    background: "var(--cds-interactive, #D4A018)",
    color: "#fff",
    fontSize: 11,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  zoomBtn: {
    width: 28,
    height: 28,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    background: "var(--cds-layer-02, #F7F8FA)",
    color: "var(--cds-text-primary, #1A1D23)",
    cursor: "pointer",
    fontSize: 16,
    fontWeight: 700,
    lineHeight: 1,
  },
  body: {
    display: "flex",
    flex: 1,
    overflow: "hidden",
  },
  svgContainer: {
    flex: 3,
    position: "relative",
    overflow: "hidden",
    cursor: "grab",
  },
  panel: {
    width: 320,
    flexShrink: 0,
    background: "var(--cds-layer-01, #ffffff)",
    borderLeft: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    overflowY: "auto",
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  panelTitle: {
    fontSize: 15,
    fontWeight: 600,
    marginBottom: 4,
    color: "var(--cds-text-primary, #1A1D23)",
  },
  panelSection: {
    fontSize: 12,
    color: "var(--cds-text-secondary, #4B5563)",
    lineHeight: 1.7,
  },
  propRow: {
    display: "flex",
    justifyContent: "space-between",
    padding: "4px 0",
    borderBottom: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
  },
  propLabel: {
    color: "var(--cds-text-secondary, #4B5563)",
    fontSize: 12,
  },
  propValue: {
    color: "var(--cds-text-primary, #1A1D23)",
    fontSize: 12,
    fontWeight: 500,
    textAlign: "right",
  },
  connItem: {
    padding: "5px 8px",
    borderRadius: 4,
    background: "var(--cds-layer-02, #F7F8FA)",
    cursor: "pointer",
    fontSize: 12,
    marginBottom: 4,
    transition: "background 0.15s",
  },
  legend: {
    position: "absolute",
    bottom: 12,
    left: 12,
    display: "flex",
    gap: 14,
    padding: "6px 14px",
    borderRadius: 8,
    background: "rgba(255, 255, 255, 0.92)",
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    zIndex: 15,
    fontSize: 11,
    alignItems: "center",
  },
  legendDot: (color, size) => ({
    width: size,
    height: size,
    borderRadius: "50%",
    background: color,
    display: "inline-block",
    marginRight: 5,
    verticalAlign: "middle",
  }),
  minimap: {
    position: "absolute",
    bottom: 48,
    right: 12,
    width: 160,
    height: 120,
    borderRadius: 8,
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    background: "rgba(255, 255, 255, 0.95)",
    overflow: "hidden",
    zIndex: 15,
  },
  loading: {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "column",
    gap: 12,
    zIndex: 30,
    background: "rgba(255, 255, 255, 0.92)",
  },
  spinner: {
    width: 36,
    height: 36,
    border: "3px solid rgba(0,0,0,0.1)",
    borderTopColor: "#D4A018",
    borderRadius: "50%",
    animation: "ggv-spin 0.8s linear infinite",
  },
  tooltip: {
    position: "absolute",
    pointerEvents: "none",
    padding: "6px 10px",
    borderRadius: 6,
    background: "rgba(255, 255, 255, 0.95)",
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    color: "#1A1D23",
    fontSize: 12,
    whiteSpace: "nowrap",
    zIndex: 25,
    boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
  },
  errorBanner: {
    padding: "10px 16px",
    background: "rgba(244, 67, 54, 0.12)",
    borderRadius: 6,
    border: "1px solid rgba(244, 67, 54, 0.3)",
    color: "#f44336",
    fontSize: 13,
    textAlign: "center",
    margin: "20px auto",
    maxWidth: 400,
  },
  emptyPanel: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    flex: 1,
    color: "var(--cds-text-secondary, #4B5563)",
    fontSize: 13,
    textAlign: "center",
    padding: 20,
  },
  searchResults: {
    position: "absolute",
    top: 44,
    left: 14,
    width: 300,
    maxHeight: 240,
    overflowY: "auto",
    borderRadius: 8,
    background: "var(--cds-layer-01, #ffffff)",
    border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
    zIndex: 25,
  },
  searchItem: {
    padding: "8px 12px",
    cursor: "pointer",
    fontSize: 13,
    borderBottom: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
    transition: "background 0.15s",
  },
};

/* ── Keyframe injection (once) ──────────────────────────────────────────── */
if (typeof document !== "undefined" && !document.getElementById("ggv-keyframes")) {
  const style = document.createElement("style");
  style.id = "ggv-keyframes";
  style.textContent = `
    @keyframes ggv-spin { to { transform: rotate(360deg); } }
    @keyframes ggv-pulse { 0%,100% { opacity: .5; } 50% { opacity: 1; } }
  `;
  document.head.appendChild(style);
}

/* ═══════════════════════════════════════════════════════════════════════════
   GridGraphView — Azure Digital Twins Explorer-style force-directed graph
   ═══════════════════════════════════════════════════════════════════════════ */
export default function GridGraphView({ lat, lon, onNodeClick }) {
  /* ── Refs ── */
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const simRef = useRef(null);
  const dragRef = useRef(null);
  const panRef = useRef({ dragging: false, startX: 0, startY: 0, ox: 0, oy: 0 });

  /* ── State ── */
  const [nodes, setNodes] = useState([]);
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const [hoverPos, setHoverPos] = useState(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [tick, setTick] = useState(0);

  /* ── Derived ── */
  const nodeMap = useMemo(() => {
    const m = new Map();
    nodes.forEach(n => m.set(n.id, n));
    return m;
  }, [nodes, tick]);

  const selectedNode = selectedId ? nodeMap.get(selectedId) : null;

  const connectedNodes = useMemo(() => {
    if (!selectedId) return [];
    const set = new Set();
    links.forEach(l => {
      const sid = typeof l.source === "object" ? l.source.id : l.source;
      const tid = typeof l.target === "object" ? l.target.id : l.target;
      if (sid === selectedId) set.add(tid);
      if (tid === selectedId) set.add(sid);
    });
    return Array.from(set).map(id => nodeMap.get(id)).filter(Boolean);
  }, [selectedId, links, nodeMap]);

  /* ── Fetch topology ── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({ max_nodes: "300", radius_km: "50" });
    if (lat != null) params.set("lat", lat);
    if (lon != null) params.set("lon", lon);

    fetch(`/api/graph/topology?${params}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        if (cancelled) return;
        const rawNodes = (data.nodes || []).map(n => ({
          ...n,
          id: n.id || n.name,
          x: undefined,
          y: undefined,
        }));
        const rawLinks = (data.edges || data.links || []).map(e => ({
          source: e.source,
          target: e.target,
          voltage_kv: e.voltage_kv || e.voltage || 0,
          length_km: e.length_km || e.length || 10,
        }));

        // Validate link references
        const nodeIds = new Set(rawNodes.map(n => n.id));
        const validLinks = rawLinks.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target));

        setNodes(rawNodes);
        setLinks(validLinks);
        setLoading(false);
      })
      .catch(err => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [lat, lon]);

  /* ── Force simulation ── */
  useEffect(() => {
    if (nodes.length === 0) return;

    const sim = forceSimulation(nodes)
      .force("link", forceLink(links).id(d => d.id).distance(d => {
        const km = d.length_km || 10;
        return Math.max(30, Math.min(200, km * 3));
      }).strength(0.6))
      .force("charge", forceManyBody().strength(-120).distanceMax(400))
      .force("center", forceCenter(0, 0).strength(0.05))
      .force("collide", forceCollide(d => nodeConfig(d.type).radius + 4))
      .force("x", forceX(0).strength(0.02))
      .force("y", forceY(0).strength(0.02))
      .alphaDecay(0.02)
      .velocityDecay(0.3)
      .on("tick", () => {
        setTick(t => t + 1);
      });

    simRef.current = sim;

    return () => { sim.stop(); };
  }, [nodes.length, links.length]);

  /* ── Container size ── */
  const [containerSize, setContainerSize] = useState({ w: 800, h: 600 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setContainerSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* ── Auto-fit on first load ── */
  const didFit = useRef(false);
  useEffect(() => {
    if (didFit.current || nodes.length === 0 || loading) return;
    // Wait for simulation to settle a bit
    const timer = setTimeout(() => {
      if (didFit.current) return;
      didFit.current = true;
      fitToView();
    }, 1200);
    return () => clearTimeout(timer);
  }, [nodes, loading, containerSize]);

  const fitToView = useCallback(() => {
    if (nodes.length === 0) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(n => {
      if (n.x != null && n.y != null) {
        minX = Math.min(minX, n.x);
        maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y);
        maxY = Math.max(maxY, n.y);
      }
    });
    if (!isFinite(minX)) return;
    const pad = 60;
    const gw = maxX - minX || 1;
    const gh = maxY - minY || 1;
    const k = Math.min(
      (containerSize.w - pad * 2) / gw,
      (containerSize.h - pad * 2) / gh,
      2
    );
    setTransform({
      k: Math.max(0.05, k),
      x: containerSize.w / 2 - (minX + gw / 2) * k,
      y: containerSize.h / 2 - (minY + gh / 2) * k,
    });
  }, [nodes, containerSize]);

  /* ── Zoom ── */
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const rect = containerRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    setTransform(t => {
      const nk = Math.max(0.02, Math.min(10, t.k * factor));
      return {
        k: nk,
        x: mx - (mx - t.x) * (nk / t.k),
        y: my - (my - t.y) * (nk / t.k),
      };
    });
  }, []);

  /* ── Pan ── */
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    // Check if we clicked on a node (handled by node events)
    if (e.target.closest("[data-node-id]")) return;
    panRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, ox: transform.x, oy: transform.y };
    containerRef.current.style.cursor = "grabbing";
  }, [transform]);

  const handleMouseMove = useCallback((e) => {
    // Dragging a node
    if (dragRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const node = dragRef.current;
      node.fx = (mx - transform.x) / transform.k;
      node.fy = (my - transform.y) / transform.k;
      if (simRef.current) simRef.current.alpha(0.3).restart();
      return;
    }
    // Panning
    const p = panRef.current;
    if (!p.dragging) return;
    setTransform(t => ({
      ...t,
      x: p.ox + (e.clientX - p.startX),
      y: p.oy + (e.clientY - p.startY),
    }));
  }, [transform]);

  const handleMouseUp = useCallback(() => {
    panRef.current.dragging = false;
    if (containerRef.current) containerRef.current.style.cursor = "grab";
    if (dragRef.current) {
      dragRef.current.fx = null;
      dragRef.current.fy = null;
      dragRef.current = null;
      if (simRef.current) simRef.current.alpha(0.1).restart();
    }
  }, []);

  /* ── Node drag ── */
  const handleNodeMouseDown = useCallback((e, node) => {
    e.stopPropagation();
    dragRef.current = node;
    node.fx = node.x;
    node.fy = node.y;
    if (simRef.current) simRef.current.alphaTarget(0.3).restart();
    containerRef.current.style.cursor = "grabbing";
  }, []);

  /* ── Node click ── */
  const handleNodeClick = useCallback((e, node) => {
    e.stopPropagation();
    setSelectedId(prev => prev === node.id ? null : node.id);
    onNodeClick?.(node);
  }, [onNodeClick]);

  /* ── Node hover ── */
  const handleNodeEnter = useCallback((e, node) => {
    setHoveredId(node.id);
    const rect = containerRef.current.getBoundingClientRect();
    setHoverPos({ x: e.clientX - rect.left + 14, y: e.clientY - rect.top - 10 });
  }, []);

  const handleNodeLeave = useCallback(() => {
    setHoveredId(null);
    setHoverPos(null);
  }, []);

  /* ── Search ── */
  const searchTimer = useRef(null);
  const handleSearch = useCallback((e) => {
    const q = e.target.value;
    setSearchQuery(q);

    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!q.trim()) {
      setSearchResults([]);
      setSearchOpen(false);
      return;
    }

    searchTimer.current = setTimeout(() => {
      // First try local filter
      const lower = q.toLowerCase();
      const local = nodes.filter(n =>
        (n.name || n.id || "").toLowerCase().includes(lower)
      ).slice(0, 10);

      if (local.length > 0) {
        setSearchResults(local);
        setSearchOpen(true);
      }

      // Also hit the API
      fetch(`/api/graph/search?q=${encodeURIComponent(q)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data?.results?.length) {
            // Merge with local
            const ids = new Set(local.map(n => n.id));
            const merged = [...local];
            data.results.forEach(r => {
              if (!ids.has(r.id)) merged.push(r);
            });
            setSearchResults(merged.slice(0, 12));
            setSearchOpen(true);
          }
        })
        .catch(() => {});
    }, 250);
  }, [nodes]);

  const navigateToNode = useCallback((node) => {
    const found = nodeMap.get(node.id);
    if (found && found.x != null && found.y != null) {
      setTransform({
        k: 1.5,
        x: containerSize.w / 2 - found.x * 1.5,
        y: containerSize.h / 2 - found.y * 1.5,
      });
      setSelectedId(found.id);
    }
    setSearchOpen(false);
    setSearchQuery(node.name || node.id || "");
  }, [nodeMap, containerSize]);

  /* ── Zoom controls ── */
  const zoomIn = () => setTransform(t => {
    const nk = Math.min(10, t.k * 1.3);
    return { k: nk, x: containerSize.w / 2 - (containerSize.w / 2 - t.x) * (nk / t.k), y: containerSize.h / 2 - (containerSize.h / 2 - t.y) * (nk / t.k) };
  });
  const zoomOut = () => setTransform(t => {
    const nk = Math.max(0.02, t.k / 1.3);
    return { k: nk, x: containerSize.w / 2 - (containerSize.w / 2 - t.x) * (nk / t.k), y: containerSize.h / 2 - (containerSize.h / 2 - t.y) * (nk / t.k) };
  });

  /* ── Show labels when zoomed in ── */
  const showLabels = transform.k > 0.6;

  /* ── Minimap ── */
  const minimapData = useMemo(() => {
    if (nodes.length === 0) return null;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(n => {
      if (n.x != null && n.y != null) {
        minX = Math.min(minX, n.x);
        maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y);
        maxY = Math.max(maxY, n.y);
      }
    });
    if (!isFinite(minX)) return null;
    const pad = 20;
    const gw = (maxX - minX) || 1;
    const gh = (maxY - minY) || 1;
    const mw = 160;
    const mh = 120;
    const scale = Math.min((mw - pad * 2) / gw, (mh - pad * 2) / gh);
    // Viewport rect in minimap coords
    const vx = (-transform.x / transform.k - minX) * scale + pad;
    const vy = (-transform.y / transform.k - minY) * scale + pad;
    const vw = (containerSize.w / transform.k) * scale;
    const vh = (containerSize.h / transform.k) * scale;
    return { minX, minY, scale, pad, vx, vy, vw, vh, mw, mh };
  }, [nodes, tick, transform, containerSize]);

  /* ── Render ── */
  const hoveredNode = hoveredId ? nodeMap.get(hoveredId) : null;

  return (
    <div style={S.root}>
      {/* ── Top bar ── */}
      <div style={S.topBar}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
          <circle cx="6" cy="6" r="3" /><circle cx="18" cy="6" r="3" />
          <circle cx="6" cy="18" r="3" /><circle cx="18" cy="18" r="3" />
          <line x1="9" y1="6" x2="15" y2="6" /><line x1="6" y1="9" x2="6" y2="15" />
          <line x1="18" y1="9" x2="18" y2="15" /><line x1="9" y1="18" x2="15" y2="18" />
          <line x1="9" y1="8" x2="15" y2="16" opacity="0.4" />
        </svg>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Grid Topology</span>
        <div style={{ position: "relative", flex: 1, maxWidth: 320 }}>
          <input
            style={S.searchInput}
            placeholder="Search nodes..."
            value={searchQuery}
            onChange={handleSearch}
            onFocus={() => searchResults.length > 0 && setSearchOpen(true)}
            onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
          />
          {searchOpen && searchResults.length > 0 && (
            <div style={S.searchResults}>
              {searchResults.map(n => (
                <div
                  key={n.id}
                  style={S.searchItem}
                  onMouseDown={() => navigateToNode(n)}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--cds-layer-02, #F7F8FA)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  <span style={{ ...S.legendDot(nodeConfig(n.type).color, 8), marginRight: 8 }} />
                  <span style={{ fontWeight: 500 }}>{n.name || n.id}</span>
                  {n.type && (
                    <span style={{ marginLeft: 8, color: "var(--cds-text-secondary, #4B5563)", fontSize: 11 }}>
                      {nodeConfig(n.type).label}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        <span style={S.badge}>{nodes.length} nodes</span>
        <span style={{ ...S.badge, background: "rgba(212,160,24,0.2)", color: "#D4A018" }}>{links.length} edges</span>
        <button style={S.zoomBtn} onClick={zoomIn} title="Zoom in">+</button>
        <button style={S.zoomBtn} onClick={zoomOut} title="Zoom out">&minus;</button>
        <button style={{ ...S.zoomBtn, fontSize: 12 }} onClick={fitToView} title="Fit to view">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="4,14 4,20 10,20" /><polyline points="20,10 20,4 14,4" />
            <line x1="14" y1="10" x2="21" y2="3" /><line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
      </div>

      <div style={S.body}>
        {/* ── SVG canvas ── */}
        <div
          ref={containerRef}
          style={S.svgContainer}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          {loading && (
            <div style={S.loading}>
              <div style={S.spinner} />
              <span style={{ color: "var(--cds-text-secondary, #4B5563)", fontSize: 13 }}>
                Loading grid topology...
              </span>
            </div>
          )}

          {error && !loading && (
            <div style={{ ...S.loading, background: "rgba(255,255,255,0.95)" }}>
              <div style={S.errorBanner}>Failed to load topology: {error}</div>
              <button
                style={{ ...S.zoomBtn, padding: "6px 16px", width: "auto", fontSize: 13, marginTop: 4 }}
                onClick={() => { setError(null); setLoading(true); /* re-trigger via useEffect */ }}
              >
                Retry
              </button>
            </div>
          )}

          <svg
            ref={svgRef}
            width={containerSize.w}
            height={containerSize.h}
            style={{ display: "block" }}
          >
            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
              {/* ── Edges ── */}
              {links.map((l, i) => {
                const s = typeof l.source === "object" ? l.source : nodeMap.get(l.source);
                const t = typeof l.target === "object" ? l.target : nodeMap.get(l.target);
                if (!s || !t || s.x == null || t.x == null) return null;
                const isHighlighted = selectedId && (
                  (s.id || s) === selectedId || (t.id || t) === selectedId
                );
                return (
                  <line
                    key={`e-${i}`}
                    x1={s.x} y1={s.y}
                    x2={t.x} y2={t.y}
                    stroke={edgeColor(l.voltage_kv)}
                    strokeWidth={isHighlighted ? 2.5 / transform.k : 1.2 / transform.k}
                    strokeOpacity={selectedId ? (isHighlighted ? 0.9 : 0.15) : 0.5}
                    strokeLinecap="round"
                  />
                );
              })}

              {/* ── Nodes ── */}
              {nodes.map(n => {
                if (n.x == null || n.y == null) return null;
                const cfg = nodeConfig(n.type);
                const r = cfg.radius / transform.k;
                const isSelected = n.id === selectedId;
                const isHovered = n.id === hoveredId;
                const isConnected = selectedId && connectedNodes.some(c => c?.id === n.id);
                const dimmed = selectedId && !isSelected && !isConnected;

                return (
                  <g
                    key={n.id}
                    data-node-id={n.id}
                    style={{ cursor: "pointer" }}
                    onMouseDown={e => handleNodeMouseDown(e, n)}
                    onClick={e => handleNodeClick(e, n)}
                    onMouseEnter={e => handleNodeEnter(e, n)}
                    onMouseLeave={handleNodeLeave}
                  >
                    {/* Glow ring on selection */}
                    {isSelected && (
                      <circle
                        cx={n.x} cy={n.y}
                        r={r + 6 / transform.k}
                        fill="none"
                        stroke="#D4A018"
                        strokeWidth={2 / transform.k}
                        strokeOpacity={0.7}
                        style={{ animation: "ggv-pulse 1.5s ease-in-out infinite" }}
                      />
                    )}
                    {/* Node circle */}
                    <circle
                      cx={n.x} cy={n.y} r={r}
                      fill={cfg.color}
                      fillOpacity={dimmed ? 0.2 : (isHovered ? 1 : 0.85)}
                      stroke={isSelected ? "#1A1D23" : isHovered ? "#374151" : "rgba(0,0,0,0.2)"}
                      strokeWidth={(isSelected ? 2 : 1) / transform.k}
                    />
                    {/* Label when zoomed */}
                    {showLabels && !dimmed && cfg.radius >= 9 && (
                      <text
                        x={n.x}
                        y={n.y - r - 4 / transform.k}
                        textAnchor="middle"
                        fill="var(--cds-text-primary, #1A1D23)"
                        fontSize={Math.min(11, 11 / transform.k)}
                        fontWeight={isSelected ? 600 : 400}
                        opacity={isSelected ? 1 : 0.75}
                        style={{ pointerEvents: "none", userSelect: "none" }}
                      >
                        {(n.name || n.id || "").slice(0, 24)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>

          {/* ── Tooltip ── */}
          {hoveredNode && hoverPos && !dragRef.current && (
            <div style={{ ...S.tooltip, left: hoverPos.x, top: hoverPos.y }}>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>{hoveredNode.name || hoveredNode.id}</div>
              <div style={{ fontSize: 11, color: "#4B5563" }}>
                {nodeConfig(hoveredNode.type).label}
                {hoveredNode.voltage_kv ? ` - ${hoveredNode.voltage_kv} kV` : ""}
              </div>
              {hoveredNode.demand_mw != null && (
                <div style={{ fontSize: 11, marginTop: 2 }}>
                  Demand: {fmtMw(hoveredNode.demand_mw)}
                </div>
              )}
            </div>
          )}

          {/* ── Legend ── */}
          <div style={S.legend}>
            {Object.entries(NODE_TYPES).map(([type, cfg]) => (
              <span key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={S.legendDot(cfg.color, Math.max(6, cfg.radius * 0.6))} />
                <span style={{ color: "var(--cds-text-secondary, #4B5563)" }}>{cfg.label}</span>
              </span>
            ))}
          </div>

          {/* ── Minimap ── */}
          {minimapData && nodes.length > 5 && (
            <div style={S.minimap}>
              <svg width={minimapData.mw} height={minimapData.mh}>
                {/* Mini edges */}
                {links.map((l, i) => {
                  const s = typeof l.source === "object" ? l.source : nodeMap.get(l.source);
                  const t = typeof l.target === "object" ? l.target : nodeMap.get(l.target);
                  if (!s || !t || s.x == null || t.x == null) return null;
                  return (
                    <line
                      key={`me-${i}`}
                      x1={(s.x - minimapData.minX) * minimapData.scale + minimapData.pad}
                      y1={(s.y - minimapData.minY) * minimapData.scale + minimapData.pad}
                      x2={(t.x - minimapData.minX) * minimapData.scale + minimapData.pad}
                      y2={(t.y - minimapData.minY) * minimapData.scale + minimapData.pad}
                      stroke="#444"
                      strokeWidth={0.5}
                    />
                  );
                })}
                {/* Mini nodes */}
                {nodes.map(n => {
                  if (n.x == null || n.y == null) return null;
                  return (
                    <circle
                      key={`mn-${n.id}`}
                      cx={(n.x - minimapData.minX) * minimapData.scale + minimapData.pad}
                      cy={(n.y - minimapData.minY) * minimapData.scale + minimapData.pad}
                      r={1.5}
                      fill={nodeConfig(n.type).color}
                      fillOpacity={0.8}
                    />
                  );
                })}
                {/* Viewport rect */}
                <rect
                  x={minimapData.vx}
                  y={minimapData.vy}
                  width={Math.max(4, minimapData.vw)}
                  height={Math.max(4, minimapData.vh)}
                  fill="rgba(212,160,24,0.1)"
                  stroke="#D4A018"
                  strokeWidth={1}
                  rx={2}
                />
              </svg>
            </div>
          )}
        </div>

        {/* ── Right panel ── */}
        <div style={S.panel}>
          {selectedNode ? (
            <>
              {/* Header */}
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={S.legendDot(nodeConfig(selectedNode.type).color, 12)} />
                  <span style={S.panelTitle}>{selectedNode.name || selectedNode.id}</span>
                </div>
                <span style={{
                  display: "inline-block",
                  padding: "2px 8px",
                  borderRadius: 4,
                  background: nodeConfig(selectedNode.type).color + "22",
                  color: nodeConfig(selectedNode.type).color,
                  fontSize: 11,
                  fontWeight: 600,
                }}>
                  {nodeConfig(selectedNode.type).label}
                </span>
              </div>

              {/* Properties */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-secondary, #4B5563)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                  Properties
                </div>
                {[
                  ["Type", selectedNode.type],
                  ["Voltage", selectedNode.voltage_kv ? `${selectedNode.voltage_kv} kV` : "--"],
                  ["DNO", selectedNode.dno || "--"],
                  ["Demand", fmtMw(selectedNode.demand_mw)],
                  ["Generation", fmtMw(selectedNode.generation_mw)],
                ].map(([label, value]) => (
                  <div key={label} style={S.propRow}>
                    <span style={S.propLabel}>{label}</span>
                    <span style={S.propValue}>{value}</span>
                  </div>
                ))}
              </div>

              {/* Headroom */}
              {(selectedNode.demand_mw != null || selectedNode.generation_mw != null) && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-secondary, #4B5563)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                    Headroom
                  </div>
                  {(() => {
                    const cap = selectedNode.capacity_mw || selectedNode.rated_mw;
                    const dem = selectedNode.demand_mw || 0;
                    const gen = selectedNode.generation_mw || 0;
                    const demHead = cap ? cap - dem : null;
                    const genHead = cap ? cap - gen : null;
                    return (
                      <>
                        <div style={S.propRow}>
                          <span style={S.propLabel}>Rated capacity</span>
                          <span style={S.propValue}>{cap ? fmtMw(cap) : "--"}</span>
                        </div>
                        {demHead != null && (
                          <div style={S.propRow}>
                            <span style={S.propLabel}>Demand headroom</span>
                            <span style={{ ...S.propValue, color: demHead > 0 ? "#4caf50" : "#f44336" }}>
                              {fmtMw(demHead)}
                            </span>
                          </div>
                        )}
                        {genHead != null && (
                          <div style={S.propRow}>
                            <span style={S.propLabel}>Generation headroom</span>
                            <span style={{ ...S.propValue, color: genHead > 0 ? "#4caf50" : "#f44336" }}>
                              {fmtMw(genHead)}
                            </span>
                          </div>
                        )}
                      </>
                    );
                  })()}
                </div>
              )}

              {/* Connected nodes */}
              {connectedNodes.length > 0 && (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-secondary, #4B5563)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                    Connected ({connectedNodes.length})
                  </div>
                  <div style={{ maxHeight: 200, overflowY: "auto" }}>
                    {connectedNodes.map(cn => (
                      <div
                        key={cn.id}
                        style={S.connItem}
                        onClick={() => navigateToNode(cn)}
                        onMouseEnter={e => e.currentTarget.style.background = "var(--cds-interactive, #D4A018)22"}
                        onMouseLeave={e => e.currentTarget.style.background = "var(--cds-layer-02, #F7F8FA)"}
                      >
                        <span style={{ ...S.legendDot(nodeConfig(cn.type).color, 8), marginRight: 6 }} />
                        <span style={{ fontWeight: 500 }}>{cn.name || cn.id}</span>
                        <span style={{ float: "right", color: "var(--cds-text-secondary, #4B5563)", fontSize: 11 }}>
                          {cn.voltage_kv ? `${cn.voltage_kv} kV` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Deselect */}
              <button
                style={{
                  marginTop: "auto",
                  padding: "7px 0",
                  borderRadius: 6,
                  border: "1px solid var(--cds-border-subtle, rgba(0,0,0,0.1))",
                  background: "transparent",
                  color: "var(--cds-text-secondary, #4B5563)",
                  cursor: "pointer",
                  fontSize: 12,
                }}
                onClick={() => setSelectedId(null)}
              >
                Deselect
              </button>
            </>
          ) : (
            <div style={S.emptyPanel}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="rgba(0,0,0,0.15)" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="3" />
                <line x1="12" y1="2" x2="12" y2="5" /><line x1="12" y1="19" x2="12" y2="22" />
                <line x1="2" y1="12" x2="5" y2="12" /><line x1="19" y1="12" x2="22" y2="12" />
              </svg>
              <div style={{ fontWeight: 500, marginBottom: 2 }}>No node selected</div>
              <div style={{ fontSize: 12 }}>
                Click a node in the graph to inspect its properties, connections, and headroom.
              </div>
              {nodes.length > 0 && (
                <div style={{ marginTop: 16, width: "100%" }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-secondary, #4B5563)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
                    Summary
                  </div>
                  {Object.entries(NODE_TYPES).map(([type, cfg]) => {
                    const count = nodes.filter(n => n.type === type).length;
                    if (count === 0) return null;
                    return (
                      <div key={type} style={S.propRow}>
                        <span style={{ ...S.propLabel, display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={S.legendDot(cfg.color, 8)} />
                          {cfg.label}
                        </span>
                        <span style={S.propValue}>{count}</span>
                      </div>
                    );
                  })}
                  <div style={{ ...S.propRow, borderBottom: "none", fontWeight: 600, marginTop: 4 }}>
                    <span style={S.propLabel}>Total</span>
                    <span style={S.propValue}>{nodes.length} nodes, {links.length} edges</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
