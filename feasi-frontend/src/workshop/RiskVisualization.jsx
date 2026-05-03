import {useState, useMemo} from 'react';
import {AssetHierarchyTree} from './AssetHierarchyTree.jsx';
import {useSelection} from './useSelection.jsx';

/**
 * Pattern (h) — Risk Visualization with FSR Deviations.
 *
 * Layout: dataset-filter dropdown + asset hierarchy tree (left) + 3D/map
 * slot (top-right) + risk table (bottom-right). All four panels read the
 * same filtered dataset so a category change ripples instantly through
 * tree counts, 3D markers, and the table.
 *
 * Props:
 *   datasets:   [{id, label}]   — e.g. [{id:'fsr_deviations',label:'FSR Deviations'}]
 *   getTreeForDataset(datasetId) → tree nodes (rid, name, children, badges)
 *   getRowsForDataset(datasetId) → row records {id, source, risk, title, status, fromDate, moc, tags, owner}
 *   threeDSlot(datasetId, selectedRid) → React node
 */
export function RiskVisualization({
  datasets = [],
  getTreeForDataset,
  getRowsForDataset,
  threeDSlot,
}) {
  const [datasetId, setDatasetId] = useState(datasets[0]?.id);
  const {selectedAssetRid} = useSelection();

  const tree = useMemo(() => (datasetId ? getTreeForDataset(datasetId) : []), [datasetId, getTreeForDataset]);
  const rows = useMemo(() => (datasetId ? getRowsForDataset(datasetId) : []), [datasetId, getRowsForDataset]);

  return (
    <div className="px-risk-vis">
      <div className="px-risk-vis-left">
        <label className="px-field">
          <span>Dataset</span>
          <select value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value)}>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
          </select>
        </label>
        <AssetHierarchyTree nodes={tree} defaultExpandDepth={1} />
      </div>

      <div className="px-risk-vis-right">
        <div className="px-risk-vis-3d">
          {threeDSlot ? threeDSlot(datasetId, selectedAssetRid) : <DefaultThreeDPlaceholder />}
        </div>
        <RiskTable rows={rows} />
      </div>
    </div>
  );
}

function RiskTable({rows}) {
  if (!rows?.length) {
    return <div className="px-empty px-risk-empty">No records for this dataset.</div>;
  }
  return (
    <div className="px-risk-table-wrap">
      <table className="px-risk-table">
        <thead>
          <tr>
            <th>ID</th><th>Source</th><th>Risk</th><th>Title</th>
            <th>Status</th><th>From date</th><th>MOC</th><th>Tags</th><th>Owner</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={`px-risk-row px-risk-${(r.risk ?? '').toLowerCase()}`}>
              <td>{r.id}</td>
              <td>{r.source}</td>
              <td><span className={`px-risk-dot px-risk-${(r.risk ?? '').toLowerCase()}`} aria-label={r.risk} /></td>
              <td>{r.title}</td>
              <td>{r.status}</td>
              <td>{r.fromDate}</td>
              <td>{r.moc}</td>
              <td>{r.tags}</td>
              <td>{r.owner}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DefaultThreeDPlaceholder() {
  return (
    <div className="px-3d-placeholder">
      <p>3D view slot — wire a deck.gl / Cesium / IFC viewer here.</p>
    </div>
  );
}
