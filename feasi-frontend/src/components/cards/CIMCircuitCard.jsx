import React, { useState, useCallback, useRef, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import api from "../../services/api";

// ---------------------------------------------------------------------------
// Custom node components
// ---------------------------------------------------------------------------

const nodeBase = {
  padding: "6px 10px",
  borderRadius: 6,
  fontSize: 11,
  textAlign: "center",
  minWidth: 80,
  border: "2px solid",
  color: "#fff",
  fontWeight: 600,
};

function SubstationNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#1565c0", borderColor: "#0d47a1" }}>
      <div style={{ fontSize: 9, opacity: 0.8 }}>Substation</div>
      <div>{data.label}</div>
      {data.voltageKv != null && <div style={{ fontSize: 9 }}>{data.voltageKv} kV</div>}
    </div>
  );
}

function TransformerNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#6a1b9a", borderColor: "#4a148c" }}>
      <div style={{ fontSize: 9, opacity: 0.8 }}>Transformer</div>
      <div>{data.label}</div>
      {data.ratedMva != null && <div style={{ fontSize: 9 }}>{data.ratedMva} MVA</div>}
    </div>
  );
}

function LineNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#e65100", borderColor: "#bf360c" }}>
      <div style={{ fontSize: 9, opacity: 0.8 }}>Line</div>
      <div>{data.label}</div>
      {data.lengthKm != null && <div style={{ fontSize: 9 }}>{data.lengthKm} km</div>}
    </div>
  );
}

function ConsumerNode({ data }) {
  return (
    <div style={{ ...nodeBase, background: "#2e7d32", borderColor: "#1b5e20" }}>
      <div style={{ fontSize: 9, opacity: 0.8 }}>Consumer</div>
      <div>{data.label}</div>
      {data.pMw != null && <div style={{ fontSize: 9 }}>{data.pMw} MW</div>}
    </div>
  );
}

function BusbarNode({ data }) {
  return (
    <div
      style={{
        ...nodeBase,
        background: "#455a64",
        borderColor: "#263238",
        minWidth: 50,
        borderRadius: 12,
      }}
    >
      <div style={{ fontSize: 8, opacity: 0.7 }}>Bus</div>
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

// ---------------------------------------------------------------------------
// BFS hierarchical layout (no dagre dependency)
// ---------------------------------------------------------------------------

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

  // Start from the first substation, or first node
  const root = nodes.find((n) => n.type === "substation") || nodes[0];
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

  // Assign positions: group by level, spread horizontally
  const byLevel = {};
  for (const n of nodes) {
    const lvl = levels[n.id] ?? 0;
    (byLevel[lvl] ||= []).push(n);
  }

  const xGap = 180;
  const yGap = 100;
  const laid = nodes.map((n) => {
    const lvl = levels[n.id] ?? 0;
    const siblings = byLevel[lvl];
    const idx = siblings.indexOf(n);
    const totalWidth = (siblings.length - 1) * xGap;
    return {
      ...n,
      position: {
        x: idx * xGap - totalWidth / 2,
        y: lvl * yGap,
      },
    };
  });

  return laid;
}

// ---------------------------------------------------------------------------
// CIMCircuitCard
// ---------------------------------------------------------------------------

export default function CIMCircuitCard() {
  const [searchQuery, setSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [selectedSub, setSelectedSub] = useState(null);
  const [depth, setDepth] = useState(3);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const debounceRef = useRef(null);

  // Debounced substation search
  const handleSearch = useCallback((e) => {
    const q = e.target.value;
    setSearchQuery(q);
    clearTimeout(debounceRef.current);
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const results = await api.grid.circuitSearch(q);
      setSuggestions(results || []);
    }, 300);
  }, []);

  const selectSubstation = useCallback(
    async (sub) => {
      setSelectedSub(sub);
      setSuggestions([]);
      setSearchQuery(sub.name);
      setLoading(true);
      setError(null);
      try {
        const data = await api.grid.circuit(sub.id, depth);
        if (!data) throw new Error("No data returned");
        if (data.error) throw new Error(data.error);
        const laidOut = bfsLayout(data.nodes || [], data.edges || []);
        setNodes(laidOut);
        setEdges(
          (data.edges || []).map((e) => ({
            ...e,
            style: { stroke: e.type === "CONTAINED_IN" ? "#90a4ae" : "#42a5f5" },
            animated: e.type === "CONNECTS",
          }))
        );
        setStats(data.stats);
      } catch (err) {
        setError(err.message);
        setNodes([]);
        setEdges([]);
        setStats(null);
      } finally {
        setLoading(false);
      }
    },
    [depth, setNodes, setEdges]
  );

  // Reload when depth changes with existing selection
  const changeDepth = useCallback(
    (newDepth) => {
      setDepth(newDepth);
      if (selectedSub) selectSubstation(selectedSub);
    },
    [selectedSub, selectSubstation]
  );

  const rfNodeTypes = useMemo(() => nodeTypes, []);

  return (
    <div className="card" style={{ borderLeft: "3px solid #1565c0" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: "#1565c0", flex: 1 }}>CIM Circuit Topology</h3>
        <select
          value={depth}
          onChange={(e) => changeDepth(Number(e.target.value))}
          style={{ fontSize: 11, padding: "2px 4px" }}
        >
          {[1, 2, 3, 4, 5].map((d) => (
            <option key={d} value={d}>
              {d} hop{d > 1 ? "s" : ""}
            </option>
          ))}
        </select>
      </div>

      {/* Search */}
      <div style={{ position: "relative", marginBottom: 8 }}>
        <input
          type="text"
          value={searchQuery}
          onChange={handleSearch}
          placeholder="Search substation…"
          style={{
            width: "100%",
            padding: "6px 8px",
            fontSize: 12,
            border: "1px solid #ccc",
            borderRadius: 4,
            boxSizing: "border-box",
          }}
        />
        {suggestions.length > 0 && (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              right: 0,
              background: "#fff",
              border: "1px solid #ccc",
              borderTop: "none",
              borderRadius: "0 0 4px 4px",
              maxHeight: 180,
              overflowY: "auto",
              zIndex: 10,
            }}
          >
            {suggestions.map((s) => (
              <div
                key={s.id}
                onClick={() => selectSubstation(s)}
                style={{
                  padding: "6px 8px",
                  fontSize: 11,
                  cursor: "pointer",
                  borderBottom: "1px solid #eee",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#e3f2fd")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "#fff")}
              >
                <strong>{s.name}</strong>
                {s.region && (
                  <span style={{ color: "#888", marginLeft: 6 }}>{s.region}</span>
                )}
                {s.voltage_kv != null && (
                  <span style={{ color: "#888", marginLeft: 6 }}>{s.voltage_kv} kV</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            color: "#c62828",
            background: "#ffebee",
            padding: "6px 8px",
            borderRadius: 4,
            fontSize: 11,
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: 20, color: "#888", fontSize: 12 }}>
          Loading circuit diagram…
        </div>
      )}

      {/* React Flow diagram */}
      {!loading && nodes.length > 0 && (
        <div style={{ height: 340, border: "1px solid #e0e0e0", borderRadius: 4 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={rfNodeTypes}
            fitView
            minZoom={0.3}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#e0e0e0" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && nodes.length === 0 && !selectedSub && (
        <div style={{ textAlign: "center", padding: 20, color: "#999", fontSize: 12 }}>
          Search for a substation to view its circuit topology
        </div>
      )}

      {/* Stats footer */}
      {stats && (
        <div
          style={{
            display: "flex",
            gap: 12,
            marginTop: 8,
            fontSize: 11,
            color: "#666",
            flexWrap: "wrap",
          }}
        >
          <span>
            <strong>{stats.assetCount}</strong> assets
          </span>
          <span>
            <strong>{stats.busbarCount}</strong> busbars
          </span>
          {stats.totalMva > 0 && (
            <span>
              <strong>{stats.totalMva}</strong> MVA
            </span>
          )}
          {stats.totalMw > 0 && (
            <span>
              <strong>{stats.totalMw}</strong> MW load
            </span>
          )}
        </div>
      )}
    </div>
  );
}
