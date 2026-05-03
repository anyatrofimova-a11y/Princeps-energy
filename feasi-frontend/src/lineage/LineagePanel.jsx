import {useEffect, useMemo, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import './lineage-panel.css';

/**
 * LineagePanel — Foundry-style slide-over showing the connector → table →
 * class → derived view trace for any node. Open globally via:
 *
 *   window.dispatchEvent(new CustomEvent("princeps:lineage", {detail: {root: "..."}}))
 *
 * Closes on ✕ / Esc / backdrop click. Renders a left→right layered SVG DAG
 * (no D3 dep) with click-to-navigate.
 */
export default function LineagePanel() {
  const [root, setRoot] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  // Listen for global open events
  useEffect(() => {
    const onOpen = (e) => {
      const r = e.detail?.root;
      if (r) setRoot(r);
    };
    window.addEventListener('princeps:lineage', onOpen);
    return () => window.removeEventListener('princeps:lineage', onOpen);
  }, []);

  // Fetch data when root changes
  useEffect(() => {
    if (!root) { setData(null); setError(null); return; }
    setLoading(true);
    setError(null);
    fetch(`/api/lineage?root=${encodeURIComponent(root)}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(setData)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [root]);

  // Esc to close
  useEffect(() => {
    if (!root) return;
    const onKey = (e) => { if (e.key === 'Escape') setRoot(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [root]);

  if (!root) return null;

  const layout = useMemo(() => data ? layoutGraph(data) : null, [data]);

  const onNodeClick = (node) => {
    if (node.kind === 'object') {
      // rid.princeps.<type>.<id>
      const parts = node.id.split('.');
      const typeMap = {project: 'Project', substation: 'Substation', repd: 'REPDProject',
                       nsip: 'NSIPProject', tec: 'TecQueueEntry', entity: 'Entity'};
      const type = typeMap[parts[2]?.toLowerCase()];
      const id = parts.slice(3).join('.');
      if (type && id) navigate(`/v2/object/${encodeURIComponent(type)}/${encodeURIComponent(id)}`);
    } else if (node.kind === 'connector') {
      navigate('/v2/datasets');
    } else if (node.kind === 'derived') {
      const raw = node.id.replace(/^view:|^mc:/, '');
      if (node.id.startsWith('mc:')) navigate('/v2');
      else navigate(`/v2/modules/${encodeURIComponent(raw)}`);
    } else if (node.kind === 'table' || node.kind === 'ontology_class') {
      // Re-root the lineage on this node so the user can keep walking
      setRoot(node.id);
    }
  };

  return (
    <>
      <div className="lin-backdrop" onClick={() => setRoot(null)} />
      <aside className="lin-panel" role="dialog" aria-label="Lineage">
        <header className="lin-head">
          <div>
            <div className="lin-eyebrow">LINEAGE</div>
            <div className="lin-title">{labelFor(root, data)}</div>
            <div className="lin-rid">{root}</div>
          </div>
          <button className="lin-close" onClick={() => setRoot(null)} aria-label="close">×</button>
        </header>

        {loading && <div className="lin-loading">Tracing provenance…</div>}
        {error && <div className="lin-err">{error}</div>}

        {data && layout && (
          <div className="lin-canvas-wrap">
            <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="lin-svg" preserveAspectRatio="xMinYMin meet">
              {/* defs for arrowhead */}
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" fill="#94A3B8" />
                </marker>
                <marker id="arrowGold" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">
                  <path d="M0,0 L10,5 L0,10 z" fill="#F5B731" />
                </marker>
              </defs>

              {/* Edges */}
              {layout.edges.map((e, i) => {
                const isRoot = e.from === data.root || e.to === data.root;
                return (
                  <g key={i} className="lin-edge">
                    <path
                      d={pathD(e)}
                      stroke={isRoot ? '#F5B731' : '#CBD5E1'}
                      strokeWidth={isRoot ? 1.6 : 1.0}
                      fill="none"
                      markerEnd={isRoot ? 'url(#arrowGold)' : 'url(#arrow)'}
                    />
                    <text
                      x={(e.fromXY.x + e.toXY.x) / 2}
                      y={(e.fromXY.y + e.toXY.y) / 2 - 4}
                      textAnchor="middle"
                      className="lin-edge-label">
                      {e.rel}
                    </text>
                  </g>
                );
              })}

              {/* Nodes */}
              {layout.nodes.map((n) => {
                const isRoot = n.id === data.root;
                return (
                  <g
                    key={n.id}
                    className={`lin-node lin-kind-${n.kind} ${isRoot ? 'is-root' : ''}`}
                    transform={`translate(${n.x},${n.y})`}
                    onClick={() => onNodeClick(n)}>
                    <rect
                      x={0} y={0} width={n.w} height={n.h}
                      rx={8} ry={8}
                      fill={fillFor(n.kind, isRoot)}
                      stroke={isRoot ? '#F5B731' : strokeFor(n.kind)}
                      strokeWidth={isRoot ? 1.8 : 1.0}
                    />
                    <text x={10} y={16} className="lin-node-kind">{n.kind.toUpperCase().replace('_', ' ')}</text>
                    <text x={10} y={36} className="lin-node-label">{trim(n.label || n.id, 28)}</text>
                    {n.kind === 'connector' && n.health_status && (
                      <circle cx={n.w - 14} cy={16} r={5} fill={healthDot(n.health_status)} />
                    )}
                  </g>
                );
              })}
            </svg>

            <footer className="lin-footer">
              <span>{data.stats.n_nodes} nodes · {data.stats.n_edges} edges · root_kind={data.root_kind}</span>
              <span className="lin-legend">
                {[
                  ['connector', 'Connector'],
                  ['table', 'Table'],
                  ['ontology_class', 'Class'],
                  ['derived', 'Derived'],
                  ['object', 'Object'],
                  ['external', 'External'],
                ].map(([k, label]) => (
                  <span key={k} className="lin-legend-pill">
                    <span className="lin-legend-dot" style={{background: fillFor(k, false)}} />
                    {label}
                  </span>
                ))}
              </span>
            </footer>
          </div>
        )}
      </aside>
    </>
  );
}

// ─── Layout helpers ─────────────────────────────────────────────────────────
const KIND_COLUMN = {
  external: 0,
  connector: 1,
  table: 2,
  ontology_class: 3,
  derived: 4,
  object: 5,
};
const COL_W = 220;
const NODE_W = 200;
const NODE_H = 52;
const ROW_GAP = 14;

function layoutGraph(data) {
  const cols = {};
  for (const n of data.nodes) {
    const c = KIND_COLUMN[n.kind] ?? 5;
    if (!cols[c]) cols[c] = [];
    cols[c].push(n);
  }
  const colKeys = Object.keys(cols).map(Number).sort();
  const out = {nodes: [], edges: [], width: 0, height: 0};

  const rows = Math.max(...colKeys.map(c => cols[c].length), 1);
  const height = 60 + rows * (NODE_H + ROW_GAP);
  const width = (Math.max(...colKeys) + 1) * COL_W + 40;

  const positions = {};
  for (const c of colKeys) {
    const list = cols[c];
    const totalH = list.length * (NODE_H + ROW_GAP) - ROW_GAP;
    const startY = 50 + (height - 100 - totalH) / 2;
    list.forEach((n, i) => {
      const x = 20 + c * COL_W;
      const y = startY + i * (NODE_H + ROW_GAP);
      const node = {...n, x, y, w: NODE_W, h: NODE_H};
      positions[n.id] = {x: x + NODE_W, y: y + NODE_H / 2, xLeft: x};
      out.nodes.push(node);
    });
  }

  for (const e of data.edges) {
    const a = positions[e.from];
    const b = positions[e.to];
    if (!a || !b) continue;
    out.edges.push({
      ...e,
      fromXY: {x: a.x, y: a.y},
      toXY: {x: b.xLeft, y: b.y},
    });
  }

  out.width = width;
  out.height = height;
  return out;
}

function pathD(e) {
  const {fromXY: a, toXY: b} = e;
  const cx = (a.x + b.x) / 2;
  return `M ${a.x},${a.y} C ${cx},${a.y} ${cx},${b.y} ${b.x},${b.y}`;
}

function fillFor(kind, isRoot) {
  if (isRoot) return '#FFE8A8';
  return {
    connector: '#FBF8F2',
    table: '#FFFFFF',
    ontology_class: '#F1F5F9',
    derived: '#EFF6FF',
    object: '#F5F3FF',
    external: '#FAFAF6',
  }[kind] || '#FFFFFF';
}
function strokeFor(kind) {
  return {
    connector: '#F5B731',
    table: '#CBD5E1',
    ontology_class: '#475569',
    derived: '#3B82F6',
    object: '#7C3AED',
    external: '#94A3B8',
  }[kind] || '#CBD5E1';
}
function healthDot(s) {
  return {green: '#22C55E', yellow: '#F5B731', red: '#EF4444'}[s] || '#94A3B8';
}
function trim(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
function labelFor(root, data) {
  if (!data) return root;
  const n = data.nodes.find(x => x.id === root);
  return n?.label || root;
}
