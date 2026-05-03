import {useEffect, useState} from 'react';
import {AssetHierarchyTree} from './AssetHierarchyTree.jsx';

/**
 * Reads /api/ontology/tree (server-rolled, no client-side aggregation)
 * and renders via the existing AssetHierarchyTree primitive.
 *
 * Empty state: shows a hint pointing at the seed scripts.
 */
export function OntologyTree({onSelect, refreshKey}) {
  const [state, setState] = useState({status: 'loading', data: null, error: null});

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({...s, status: 'loading'}));
    fetch('/api/workshop/tree')
      .then((r) => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then((data) => { if (!cancelled) setState({status: 'ready', data, error: null}); })
      .catch((e) => { if (!cancelled) setState({status: 'error', data: null, error: String(e)}); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (state.status === 'loading') {
    return <div className="px-tree-empty">Loading ontology…</div>;
  }
  if (state.status === 'error') {
    return <div className="px-tree-empty px-tree-error">Tree unavailable: {state.error}</div>;
  }
  if (!state.data || state.data.length === 0) {
    return (
      <div className="px-tree-empty">
        <p>No objects yet.</p>
        <p>Seed entities or substations to populate this tree.</p>
      </div>
    );
  }
  return <AssetHierarchyTree nodes={state.data} onSelect={onSelect} />;
}
