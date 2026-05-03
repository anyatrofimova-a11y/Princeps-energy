import {useEffect, useRef, useState, useMemo} from 'react';

/**
 * PipelineCanvas — drag-drop SVG node editor for a pipeline manifest.
 *
 * Props:
 *   manifest:         {nodes, edges, layout?: {positions: {nodeId: {x,y}}}}
 *   onChange(next):   called with the new manifest on every mutation
 *
 * Pure-SVG, native pointer events. No react-flow / d3 dep.
 */

const NODE_W = 200;
const NODE_H = 80;
const PORT_R = 6;
const GRID = 20;

const KIND_COLOURS = {
  connector_source: '#3B82F6',
  sql_transform:    '#F5B731',
  set_filter:       '#8B5CF6',
  dataset_sink:     '#22C55E',
};

const PALETTE = [
  {kind: 'connector_source', label: 'Connector', defaultProps: {slug: 'bmrs_settlement_prices'}},
  {kind: 'sql_transform',    label: 'SQL Transform', defaultProps: {sql: 'SELECT * FROM bmrs_settlement_prices LIMIT 10'}},
  {kind: 'set_filter',       label: 'Set Filter',    defaultProps: {set_slug: 'repd-operational'}},
  {kind: 'dataset_sink',     label: 'Dataset Sink',  defaultProps: {table: 'my_output', if_exists: 'replace'}},
];

export default function PipelineCanvas({manifest, onChange}) {
  const svgRef = useRef(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [edgeDrag, setEdgeDrag] = useState(null);   // {fromId, fromPt, mouse}
  const [draggingId, setDraggingId] = useState(null);
  const [dragOffset, setDragOffset] = useState({x: 0, y: 0});

  // Resolve node positions — manifest.layout.positions OR auto-layout
  const positions = useMemo(() => {
    const stored = manifest?.layout?.positions || {};
    const out = {};
    const nodes = manifest?.nodes || [];
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (stored[n.id]) {
        out[n.id] = stored[n.id];
      } else {
        // Auto-layout: spread horizontally
        out[n.id] = {x: 80 + (i % 4) * (NODE_W + 60), y: 80 + Math.floor(i / 4) * (NODE_H + 80)};
      }
    }
    return out;
  }, [manifest]);

  const updateManifest = (mutator) => {
    const next = JSON.parse(JSON.stringify(manifest));
    mutator(next);
    next.layout = next.layout || {};
    next.layout.positions = next.layout.positions || {...positions};
    onChange(next);
  };

  const persistPosition = (id, x, y) => {
    const snapX = Math.round(x / GRID) * GRID;
    const snapY = Math.round(y / GRID) * GRID;
    updateManifest(m => {
      m.layout = m.layout || {};
      m.layout.positions = {...(m.layout.positions || {}), [id]: {x: snapX, y: snapY}};
    });
  };

  const onPaletteDrag = (e, kind, label, defaultProps) => {
    e.dataTransfer.setData('application/json', JSON.stringify({kind, label, defaultProps}));
    e.dataTransfer.effectAllowed = 'copy';
  };

  const onCanvasDrop = (e) => {
    e.preventDefault();
    let payload;
    try { payload = JSON.parse(e.dataTransfer.getData('application/json')); }
    catch { return; }
    if (!payload?.kind) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left - NODE_W / 2;
    const y = e.clientY - rect.top - NODE_H / 2;
    const idBase = payload.kind.replace('_', '').slice(0, 3);
    const existing = (manifest?.nodes || []).map(n => n.id);
    let n = 1;
    while (existing.includes(`${idBase}${n}`)) n++;
    const newId = `${idBase}${n}`;
    updateManifest(m => {
      m.nodes = m.nodes || [];
      m.nodes.push({id: newId, kind: payload.kind, props: {...payload.defaultProps}});
      m.layout = m.layout || {};
      m.layout.positions = {...(m.layout.positions || {}), [newId]: {
        x: Math.round(x / GRID) * GRID,
        y: Math.round(y / GRID) * GRID,
      }};
    });
    setSelectedNodeId(newId);
  };

  const onNodeDown = (e, id) => {
    if (e.target.dataset?.port) return; // port click handled separately
    e.stopPropagation();
    const pos = positions[id];
    setDraggingId(id);
    setDragOffset({x: e.clientX - (svgRef.current.getBoundingClientRect().left + pos.x),
                   y: e.clientY - (svgRef.current.getBoundingClientRect().top + pos.y)});
    setSelectedNodeId(id);
  };

  const onSvgMove = (e) => {
    if (draggingId) {
      const rect = svgRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left - dragOffset.x;
      const y = e.clientY - rect.top - dragOffset.y;
      persistPosition(draggingId, x, y);
    }
    if (edgeDrag) {
      const rect = svgRef.current.getBoundingClientRect();
      setEdgeDrag({...edgeDrag, mouse: {x: e.clientX - rect.left, y: e.clientY - rect.top}});
    }
  };

  const onSvgUp = (e) => {
    if (edgeDrag) {
      // Find target port under cursor
      const rect = svgRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      for (const n of manifest?.nodes || []) {
        if (n.id === edgeDrag.fromId) continue;
        const p = positions[n.id];
        const inX = p.x;
        const inY = p.y + NODE_H / 2;
        if (Math.hypot(mx - inX, my - inY) <= PORT_R + 5) {
          // Avoid duplicates
          const exists = (manifest.edges || []).some(e2 => e2.from === edgeDrag.fromId && e2.to === n.id);
          if (!exists) {
            updateManifest(m => {
              m.edges = m.edges || [];
              m.edges.push({from: edgeDrag.fromId, to: n.id});
            });
          }
          break;
        }
      }
      setEdgeDrag(null);
    }
    setDraggingId(null);
  };

  const onPortDown = (e, fromId) => {
    e.stopPropagation();
    const rect = svgRef.current.getBoundingClientRect();
    const p = positions[fromId];
    setEdgeDrag({
      fromId,
      fromPt: {x: p.x + NODE_W, y: p.y + NODE_H / 2},
      mouse: {x: e.clientX - rect.left, y: e.clientY - rect.top},
    });
  };

  const removeNode = (id) => {
    updateManifest(m => {
      m.nodes = (m.nodes || []).filter(n => n.id !== id);
      m.edges = (m.edges || []).filter(e => e.from !== id && e.to !== id);
      if (m.layout?.positions) delete m.layout.positions[id];
    });
    if (selectedNodeId === id) setSelectedNodeId(null);
  };

  const removeEdge = (idx) => {
    updateManifest(m => {
      m.edges = (m.edges || []).filter((_, i) => i !== idx);
    });
  };

  const updateNodeProp = (id, propsPatch) => {
    updateManifest(m => {
      const n = (m.nodes || []).find(x => x.id === id);
      if (n) n.props = {...(n.props || {}), ...propsPatch};
    });
  };

  const renameNode = (oldId, newId) => {
    if (!newId.match(/^[a-zA-Z0-9_]+$/)) return;
    updateManifest(m => {
      const n = (m.nodes || []).find(x => x.id === oldId);
      if (!n) return;
      n.id = newId;
      m.edges = (m.edges || []).map(e => ({
        from: e.from === oldId ? newId : e.from,
        to:   e.to   === oldId ? newId : e.to,
      }));
      if (m.layout?.positions?.[oldId]) {
        m.layout.positions[newId] = m.layout.positions[oldId];
        delete m.layout.positions[oldId];
      }
    });
    setSelectedNodeId(newId);
  };

  const selectedNode = manifest?.nodes?.find(n => n.id === selectedNodeId);
  const W = 1100, H = 600;

  return (
    <div className="pipe-canvas-wrap">
      {/* Left: palette */}
      <aside className="pc-palette">
        <div className="pc-palette-head">DRAG TO CANVAS</div>
        {PALETTE.map(p => (
          <div
            key={p.kind}
            className="pc-palette-item"
            draggable
            onDragStart={(e) => onPaletteDrag(e, p.kind, p.label, p.defaultProps)}
            style={{borderLeftColor: KIND_COLOURS[p.kind]}}>
            <div className="pc-palette-label">{p.label}</div>
            <div className="pc-palette-kind">{p.kind}</div>
          </div>
        ))}
        <div className="pc-palette-help">
          • drag from here onto canvas<br/>
          • drag node to move<br/>
          • drag <span style={{color:'#F5B731'}}>output dot</span> → input dot to connect<br/>
          • click node to edit props
        </div>
      </aside>

      {/* Centre: SVG canvas */}
      <div
        className="pc-canvas-host"
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }}
        onDrop={onCanvasDrop}
      >
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="pc-canvas-svg"
          onMouseMove={onSvgMove}
          onMouseUp={onSvgUp}
          onMouseLeave={onSvgUp}
          onClick={() => setSelectedNodeId(null)}
        >
          {/* Grid pattern */}
          <defs>
            <pattern id="pc-grid" width={GRID} height={GRID} patternUnits="userSpaceOnUse">
              <path d={`M ${GRID} 0 L 0 0 0 ${GRID}`} fill="none" stroke="#E2E8F0" strokeWidth="0.5"/>
            </pattern>
            <marker id="pc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#94A3B8" />
            </marker>
          </defs>
          <rect width={W} height={H} fill="url(#pc-grid)" />

          {/* Edges */}
          {(manifest?.edges || []).map((e, i) => {
            const a = positions[e.from], b = positions[e.to];
            if (!a || !b) return null;
            const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
            const x2 = b.x,           y2 = b.y + NODE_H / 2;
            const cx = (x1 + x2) / 2;
            return (
              <g key={i}>
                <path
                  d={`M ${x1},${y1} C ${cx},${y1} ${cx},${y2} ${x2},${y2}`}
                  stroke="#94A3B8" strokeWidth="1.6" fill="none"
                  markerEnd="url(#pc-arrow)"
                />
                <circle
                  cx={(x1 + x2) / 2} cy={(y1 + y2) / 2} r={6}
                  fill="#FFFFFF" stroke="#94A3B8"
                  style={{cursor: 'pointer'}}
                  onClick={(ev) => { ev.stopPropagation(); if (confirm(`Remove ${e.from} → ${e.to}?`)) removeEdge(i); }}>
                  <title>Click to remove edge</title>
                </circle>
                <text
                  x={(x1 + x2) / 2} y={(y1 + y2) / 2 + 3} textAnchor="middle"
                  fontSize={9} fill="#5A5F66" pointerEvents="none">×</text>
              </g>
            );
          })}

          {/* Edge being dragged */}
          {edgeDrag && (
            <path
              d={`M ${edgeDrag.fromPt.x},${edgeDrag.fromPt.y} C ${(edgeDrag.fromPt.x + edgeDrag.mouse.x) / 2},${edgeDrag.fromPt.y} ${(edgeDrag.fromPt.x + edgeDrag.mouse.x) / 2},${edgeDrag.mouse.y} ${edgeDrag.mouse.x},${edgeDrag.mouse.y}`}
              stroke="#F5B731" strokeWidth="1.8" strokeDasharray="4 3" fill="none"
            />
          )}

          {/* Nodes */}
          {(manifest?.nodes || []).map(n => {
            const p = positions[n.id];
            if (!p) return null;
            const colour = KIND_COLOURS[n.kind] || '#94A3B8';
            const isSel = selectedNodeId === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                onMouseDown={(e) => onNodeDown(e, n.id)}
                style={{cursor: draggingId === n.id ? 'grabbing' : 'grab'}}>
                <rect
                  x={0} y={0} width={NODE_W} height={NODE_H}
                  rx={8}
                  fill="#FFFFFF"
                  stroke={isSel ? '#F5B731' : 'rgba(15,19,24,0.10)'}
                  strokeWidth={isSel ? 2 : 1}
                  style={{filter: isSel ? 'drop-shadow(0 4px 12px rgba(245,183,49,0.20))' : 'drop-shadow(0 1px 3px rgba(15,19,24,0.08))'}}
                />
                <rect x={0} y={0} width={6} height={NODE_H} fill={colour} rx={3} />
                <text x={16} y={22} fontSize={13} fontWeight={700} fill="#0F1318" fontFamily="JetBrains Mono">{n.id}</text>
                <text x={16} y={38} fontSize={10} fill="#5A5F66" letterSpacing="0.06em" textTransform="uppercase">{n.kind}</text>
                <text x={16} y={56} fontSize={10.5} fill="#94A3B8" fontFamily="JetBrains Mono">
                  {Object.keys(n.props || {}).slice(0, 2).join(' · ')}
                </text>
                {/* Input port (left) */}
                <circle
                  cx={0} cy={NODE_H / 2} r={PORT_R}
                  fill="#FFFFFF" stroke={colour} strokeWidth={2}
                  data-port="in"
                  style={{cursor: 'crosshair'}}>
                  <title>input</title>
                </circle>
                {/* Output port (right) */}
                <circle
                  cx={NODE_W} cy={NODE_H / 2} r={PORT_R}
                  fill={colour} stroke="#0F1318" strokeWidth={1}
                  data-port="out"
                  style={{cursor: 'crosshair'}}
                  onMouseDown={(e) => onPortDown(e, n.id)}>
                  <title>output — drag to another node's input</title>
                </circle>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Right: inspector */}
      <aside className="pc-inspector">
        {selectedNode ? (
          <NodeInspector
            key={selectedNode.id}
            node={selectedNode}
            onRename={(newId) => renameNode(selectedNode.id, newId)}
            onPropsChange={(patch) => updateNodeProp(selectedNode.id, patch)}
            onDelete={() => removeNode(selectedNode.id)}
          />
        ) : (
          <div className="pc-inspector-empty">
            <div className="pc-inspector-eyebrow">SELECT A NODE</div>
            <div style={{fontSize: 12, color: '#5A5F66', marginTop: 8}}>
              Click any node on the canvas to edit its props.
              <br/><br/>
              <strong>{(manifest?.nodes || []).length} nodes · {(manifest?.edges || []).length} edges</strong>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function NodeInspector({node, onRename, onPropsChange, onDelete}) {
  const [idDraft, setIdDraft] = useState(node.id);
  return (
    <div>
      <div className="pc-inspector-eyebrow" style={{borderLeftColor: KIND_COLOURS[node.kind]}}>
        {node.kind.toUpperCase().replace('_', ' ')}
      </div>
      <div className="pc-insp-row">
        <label>id</label>
        <div style={{display: 'flex', gap: 4}}>
          <input
            type="text"
            value={idDraft}
            onChange={(e) => setIdDraft(e.target.value)}
            className="pc-insp-input"
          />
          {idDraft !== node.id && (
            <button className="pc-insp-mini-btn" onClick={() => onRename(idDraft)}>rename</button>
          )}
        </div>
      </div>
      {Object.entries(node.props || {}).map(([k, v]) => (
        <div key={k} className="pc-insp-row">
          <label>{k}</label>
          {(typeof v === 'string' && v.length > 60) ? (
            <textarea
              value={v}
              onChange={(e) => onPropsChange({[k]: e.target.value})}
              className="pc-insp-input"
              rows={4}
            />
          ) : (
            <input
              type="text"
              value={v == null ? '' : String(v)}
              onChange={(e) => onPropsChange({[k]: e.target.value})}
              className="pc-insp-input"
            />
          )}
        </div>
      ))}
      <button className="pc-insp-del-btn" onClick={onDelete}>delete node</button>
    </div>
  );
}
