import React, { useState, useCallback, useMemo, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useGridModel } from "../../contexts/GridModelContext";
import api from "../../services/api";

// Custom node components (promoted from CIMCircuitCard)
const nodeBase = {
  padding: "8px 12px",
  borderRadius: 6,
  fontSize: 11,
  textAlign: "center",
  minWidth: 90,
  border: "2px solid",
  color: "#fff",
  fontWeight: 600,
  fontFamily: "'IBM Plex Mono', monospace",
};

function SubstationNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#1565c0", borderColor: "#0d47a1" }}>
      <div style={{ fontSize: 8, opacity: 0.7, textTransform: "uppercase", letterSpacing: 1 }}>Substation</div>
      <div>{data.label}</div>
      {data.voltageKv != null && <div style={{ fontSize: 9, opacity: 0.8 }}>{data.voltageKv} kV</div>}
    </div>
  );
}

function TransformerNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#6a1b9a", borderColor: "#4a148c" }}>
      <div style={{ fontSize: 8, opacity: 0.7, textTransform: "uppercase", letterSpacing: 1 }}>Transformer</div>
      <div>{data.label}</div>
      {data.ratedMva != null && <div style={{ fontSize: 9, opacity: 0.8 }}>{data.ratedMva} MVA</div>}
    </div>
  );
}

function LineNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#e65100", borderColor: "#bf360c" }}>
      <div style={{ fontSize: 8, opacity: 0.7, textTransform: "uppercase", letterSpacing: 1 }}>Line</div>
      <div>{data.label}</div>
      {data.lengthKm != null && <div style={{ fontSize: 9, opacity: 0.8 }}>{data.lengthKm} km</div>}
    </div>
  );
}

function ConsumerNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#2e7d32", borderColor: "#1b5e20" }}>
      <div style={{ fontSize: 8, opacity: 0.7, textTransform: "uppercase", letterSpacing: 1 }}>Consumer</div>
      <div>{data.label}</div>
      {data.pMw != null && <div style={{ fontSize: 9, opacity: 0.8 }}>{data.pMw} MW</div>}
    </div>
  );
}

function BusbarNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#455a64", borderColor: "#263238", minWidth: 60, borderRadius: 12 }}>
      <div style={{ fontSize: 7, opacity: 0.6 }}>BUS</div>
      <div>{data.label}</div>
    </div>
  );
}

const nodeTypes = {
  substation: SubstationNode,
  transformer: TransformerNode,
  line: LineNode,
  consumer: ConsumerNode,
  busbar: BusbarNode,
};

// BFS hierarchical layout
function bfsLayout(nodes, edges) {
  if (!nodes.length) return nodes;
  const adj = {};
  for (const e of edges) {
    (adj[e.source] ||= []).push(e.target);
    (adj[e.target] ||= []).push(e.source);
  }
  const levels = {};
  const visited = new Set();
  const queue = [];
  const root = nodes.find(n => n.type === "substation") || nodes[0];
  queue.push(root.id);
  visited.add(root.id);
  levels[root.id] = 0;
  while (queue.length) {
    const curr = queue.shift();
    for (const neighbor of adj[curr] || []) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        levels[neighbor] = levels[curr] + 1;
        queue.push(neighbor);
      }
    }
  }
  const byLevel = {};
  for (const n of nodes) {
    const lvl = levels[n.id] ?? 0;
    (byLevel[lvl] ||= []).push(n);
  }
  const xGap = 200;
  const yGap = 120;
  return nodes.map(n => {
    const lvl = levels[n.id] ?? 0;
    const siblings = byLevel[lvl];
    const idx = siblings.indexOf(n);
    const totalWidth = (siblings.length - 1) * xGap;
    return { ...n, position: { x: idx * xGap - totalWidth / 2, y: lvl * yGap } };
  });
}

export default function GridCircuitView() {
  const { selectedSubstation, selectSubstation, cimData } = useGridModel();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [depth, setDepth] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const searchTimer = React.useRef(null);

  const rfNodeTypes = useMemo(() => nodeTypes, []);

  // Load circuit when CIM data or substation changes
  useEffect(() => {
    if (!cimData) {
      setNodes([]);
      setEdges([]);
      return;
    }
    if (cimData.error) {
      setError(cimData.error);
      return;
    }
    const laid = bfsLayout(cimData.nodes || [], cimData.edges || []);
    setNodes(laid);
    setEdges((cimData.edges || []).map(e => ({
      ...e,
      style: { stroke: e.type === "CONTAINED_IN" ? "#90a4ae" : "#42a5f5", strokeWidth: 1.5 },
      animated: e.type === "CONNECTS",
    })));
    setError(null);
  }, [cimData, setNodes, setEdges]);

  // Search substations
  const handleSearch = useCallback((e) => {
    const q = e.target.value;
    setSearchQuery(q);
    clearTimeout(searchTimer.current);
    if (q.length < 2) { setSuggestions([]); return; }
    searchTimer.current = setTimeout(async () => {
      const results = await api.grid.circuitSearch(q);
      setSuggestions(results || []);
    }, 300);
  }, []);

  const handleSelectSuggestion = useCallback(async (sub) => {
    setSuggestions([]);
    setSearchQuery(sub.name);
    setLoading(true);
    setError(null);
    try {
      const data = await api.grid.circuit(sub.id, depth);
      if (!data) throw new Error("No data returned");
      if (data.error) throw new Error(data.error);
      const laid = bfsLayout(data.nodes || [], data.edges || []);
      setNodes(laid);
      setEdges((data.edges || []).map(e => ({
        ...e,
        style: { stroke: e.type === "CONTAINED_IN" ? "#90a4ae" : "#42a5f5", strokeWidth: 1.5 },
        animated: e.type === "CONNECTS",
      })));
      // Also select in grid model context
      selectSubstation({ id: sub.id, name: sub.name, voltageKv: sub.voltage_kv });
    } catch (err) {
      setError(err.message);
      setNodes([]); setEdges([]);
    } finally {
      setLoading(false);
    }
  }, [depth, setNodes, setEdges, selectSubstation]);

  // Update search when selected substation changes externally
  useEffect(() => {
    if (selectedSubstation?.name) {
      setSearchQuery(selectedSubstation.name);
    }
  }, [selectedSubstation]);

  return (
    <div className="grid-circuit-view">
      {/* Toolbar */}
      <div className="gcv-toolbar">
        <div className="gcv-search-wrap">
          <input
            type="text"
            value={searchQuery}
            onChange={handleSearch}
            placeholder="Search substation for circuit..."
            className="gcv-search"
          />
          {suggestions.length > 0 && (
            <div className="gcv-suggestions">
              {suggestions.map(s => (
                <button key={s.id} className="gcv-suggestion" onClick={() => handleSelectSuggestion(s)}>
                  <strong>{s.name}</strong>
                  {s.region && <span className="gcv-suggestion-dim">{s.region}</span>}
                  {s.voltage_kv != null && <span className="gcv-suggestion-dim">{s.voltage_kv}kV</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <select className="gcv-depth" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
          {[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>{d} hop{d > 1 ? "s" : ""}</option>)}
        </select>
        {cimData?.stats && (
          <div className="gcv-stats">
            <span>{cimData.stats.assetCount} assets</span>
            <span>{cimData.stats.busbarCount} busbars</span>
            {cimData.stats.totalMva > 0 && <span>{cimData.stats.totalMva} MVA</span>}
          </div>
        )}
      </div>

      {/* Error */}
      {error && <div className="gcv-error">{error}</div>}

      {/* Loading */}
      {loading && <div className="gcv-loading">Loading circuit diagram...</div>}

      {/* React Flow full-screen */}
      {!loading && nodes.length > 0 ? (
        <div className="gcv-flow-container">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={rfNodeTypes}
            fitView
            minZoom={0.1}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="rgba(255,255,255,0.03)" gap={24} />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={(n) => {
                if (n.type === "substation") return "#1565c0";
                if (n.type === "transformer") return "#6a1b9a";
                if (n.type === "line") return "#e65100";
                if (n.type === "consumer") return "#2e7d32";
                return "#455a64";
              }}
              maskColor="rgba(22, 22, 22, 0.8)"
              style={{ background: "var(--cds-layer-01)" }}
            />
          </ReactFlow>
        </div>
      ) : (
        !loading && !error && (
          <div className="gcv-empty">
            <div className="gcv-empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <div>Search for a substation or select one from the tree</div>
            <div style={{ fontSize: 10, marginTop: 4, color: "var(--cds-text-helper)" }}>
              The circuit diagram shows CIM topology with transformers, lines, and busbars
            </div>
          </div>
        )
      )}
    </div>
  );
}
