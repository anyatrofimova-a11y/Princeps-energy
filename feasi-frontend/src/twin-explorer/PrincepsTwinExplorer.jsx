import {useEffect, useRef, useState, useMemo} from 'react';
import {useSelection} from '../workshop/useSelection.jsx';

/**
 * Princeps Twin Explorer (Swarm 11).
 *
 * Cytoscape-based interactive graph viewer for the DTDL-modelled twin
 * instance/relationship graph. Mirrors patterns from
 * Azure-Samples/digital-twins-explorer (MIT) but adapted to:
 *   • Princeps RIDs (not DTDL's $dtId)
 *   • our SelectionContext (clicking a node fires global selection)
 *   • Apache AGE backend graph (data shape from /api/twin/graph)
 *
 * Optional dep: react-cytoscapejs (and cytoscape) — install via:
 *   cd feasi-frontend && npm install react-cytoscapejs cytoscape cytoscape-fcose
 *
 * If the dep is missing the component renders a clear instructional panel
 * instead of crashing.
 *
 * Props:
 *   graphSource: () => Promise<{nodes:[...], edges:[...]}>
 *   layout:      'fcose'|'dagre'|'cose'|'circle'  (default 'fcose')
 *   onNodeSelect(rid)
 */
export function PrincepsTwinExplorer({graphSource, layout = 'fcose', onNodeSelect}) {
  const {selectedAssetRid, setSelectedAssetRid} = useSelection();
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState(null);
  const [cytoscapeAvailable, setCytoscapeAvailable] = useState(null); // null=checking
  const cyRef = useRef(null);

  // Probe for the optional cytoscape dep without crashing if it's missing.
  useEffect(() => {
    let cancelled = false;
    Promise.all([import('react-cytoscapejs'), import('cytoscape')])
      .then(([rc, cy]) => {
        if (cancelled) return;
        try {
          // Optional fcose layout — best for force-directed twin graphs.
          import('cytoscape-fcose').then((fc) => cy.default.use(fc.default)).catch(() => {});
        } catch { /* layout already registered */ }
        setCytoscapeAvailable({CytoscapeComponent: rc.default});
      })
      .catch(() => { if (!cancelled) setCytoscapeAvailable(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!graphSource) return;
    let cancelled = false;
    setError(null);
    graphSource()
      .then((g) => { if (!cancelled) setGraph(g); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [graphSource]);

  const elements = useMemo(() => {
    if (!graph) return [];
    return [
      ...(graph.nodes ?? []).map((n) => ({data: {id: n.rid, label: n.label ?? n.name ?? n.rid, type: n.type}})),
      ...(graph.edges ?? []).map((e) => ({data: {
        id: e.rid ?? `${e.from_rid}|${e.to_rid}|${e.rel_name}`,
        source: e.from_rid, target: e.to_rid, label: e.rel_name,
      }})),
    ];
  }, [graph]);

  if (cytoscapeAvailable === null) return <div className="px-twin-explorer">Loading graph engine…</div>;
  if (cytoscapeAvailable === false) {
    return (
      <div className="px-twin-explorer px-twin-explorer-no-dep">
        <p>Twin Explorer needs <code>react-cytoscapejs</code>. Install with:</p>
        <pre>cd feasi-frontend && npm install react-cytoscapejs cytoscape cytoscape-fcose</pre>
      </div>
    );
  }
  if (error) return <div className="px-twin-explorer-error">Error: {error}</div>;
  if (!graph) return <div className="px-twin-explorer">Loading twin graph…</div>;

  const {CytoscapeComponent} = cytoscapeAvailable;
  return (
    <div className="px-twin-explorer">
      <CytoscapeComponent
        elements={elements}
        layout={{name: layout, animate: true, fit: true}}
        style={{width: '100%', height: '100%'}}
        cy={(cy) => {
          cyRef.current = cy;
          cy.on('tap', 'node', (evt) => {
            const rid = evt.target.id();
            setSelectedAssetRid(rid);
            onNodeSelect?.(rid);
          });
        }}
        stylesheet={[
          {selector: 'node',
           style: {label: 'data(label)', 'background-color': '#D4A018',
                   'text-valign': 'bottom', 'text-margin-y': 4,
                   'font-size': 10, 'border-width': 1, 'border-color': '#0F1318'}},
          {selector: `node[id="${selectedAssetRid}"]`,
           style: {'background-color': '#0F6BFF', 'border-color': '#0F1318', 'border-width': 2}},
          {selector: 'edge',
           style: {'curve-style': 'bezier', 'target-arrow-shape': 'triangle',
                   'line-color': '#94A3B8', 'target-arrow-color': '#94A3B8',
                   label: 'data(label)', 'font-size': 8, 'text-rotation': 'autorotate',
                   'text-margin-y': -6}},
        ]}
      />
    </div>
  );
}
