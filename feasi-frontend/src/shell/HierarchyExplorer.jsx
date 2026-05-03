import {useState, useMemo, useCallback} from 'react';
import {useNavigate} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {useSelection} from '../workshop/useSelection.jsx';

const AXES = [
  {id: 'stage',    label: 'Lifecycle'},
  {id: 'workflow', label: 'Workflow'},
  {id: 'type',     label: 'Type'},
];

const TYPE_FILTERS = ['all', 'data_centre', 'bess_unit', 'site', 'substation', 'counterparty'];

/**
 * Left rail — drillable hierarchy of every object in the ontology, grouped
 * by the active axis (lifecycle stage / workflow stage / type).
 *
 * Backend: GET /api/workshop/hierarchy?axis=stage&type=all
 *   → [{bucket_id, label, count, items: [{rid, type, name, badges}]}]
 */
export function HierarchyExplorer() {
  const [axis, setAxis] = useState('stage');
  const [typeFilter, setTypeFilter] = useState('all');
  const [filterText, setFilterText] = useState('');

  const {data, isLoading} = useQuery({
    queryKey: ['hierarchy', axis, typeFilter],
    queryFn: async () => {
      const r = await fetch(`/api/workshop/hierarchy?axis=${axis}&type=${typeFilter}`);
      if (!r.ok) throw new Error(`hierarchy ${r.status}`);
      return r.json();
    },
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = filterText.trim().toLowerCase();
    if (!q) return data;
    return data.map((bucket) => ({
      ...bucket,
      items: bucket.items.filter((it) => (it.name ?? '').toLowerCase().includes(q)
                                       || (it.rid ?? '').toLowerCase().includes(q)),
    })).filter((b) => b.items.length > 0);
  }, [data, filterText]);

  return (
    <div className="px2-explorer-inner">
      <div className="px2-axis-switcher" role="tablist">
        {AXES.map((a) => (
          <button
            key={a.id}
            role="tab"
            aria-selected={axis === a.id}
            className={`px2-axis-tab${axis === a.id ? ' is-active' : ''}`}
            onClick={() => setAxis(a.id)}
          >{a.label}</button>
        ))}
      </div>

      <div className="px2-explorer-controls">
        <input
          className="px2-explorer-filter"
          placeholder="filter…"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
        <select
          className="px2-explorer-typefilter"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          {TYPE_FILTERS.map((t) => <option key={t} value={t}>{t === 'all' ? 'all types' : t}</option>)}
        </select>
      </div>

      <nav className="px2-buckets" aria-busy={isLoading}>
        {isLoading && <div className="px2-explorer-empty">loading…</div>}
        {!isLoading && filtered.length === 0 && <div className="px2-explorer-empty">no matches</div>}
        {filtered.map((bucket) => (
          <Bucket key={bucket.bucket_id} bucket={bucket} />
        ))}
      </nav>
    </div>
  );
}


function Bucket({bucket}) {
  const [open, setOpen] = useState(true);
  const {selectedAssetRid, setSelectedAssetRid} = useSelection();
  const navigate = useNavigate();

  const click = useCallback((item) => {
    setSelectedAssetRid(item.rid);
    navigate(`/v2/object/${item.type}/${ridLocator(item.rid)}`);
  }, [setSelectedAssetRid, navigate]);

  return (
    <div className={`px2-bucket${open ? ' is-open' : ''}`}>
      <button className="px2-bucket-header" onClick={() => setOpen((v) => !v)}>
        <span className="px2-bucket-disclosure">{open ? '▾' : '▸'}</span>
        <span className="px2-bucket-label">{bucket.label}</span>
        <span className="px2-bucket-count">{bucket.count}</span>
      </button>
      {open && (
        <ul className="px2-bucket-items" role="group">
          {bucket.items.map((item) => (
            <li key={item.rid}>
              <button
                className={`px2-item${selectedAssetRid === item.rid ? ' is-selected' : ''}`}
                onClick={() => click(item)}
                title={item.rid}
              >
                <span className={`px2-item-glyph px2-type-${item.type}`}>{typeGlyph(item.type)}</span>
                <span className="px2-item-name">{item.name}</span>
                {item.badges && Object.entries(item.badges).map(([k, n]) => (
                  n > 0 ? <span key={k} className={`px2-item-badge px2-badge-${k}`}>{n}</span> : null
                ))}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function ridLocator(rid) {
  // rid.princeps.production.data_centre.slough-50 → slough-50
  if (!rid) return '';
  const parts = rid.split('.');
  return parts.length >= 5 ? parts.slice(4).join('.') : rid;
}

function typeGlyph(type) {
  switch (type) {
    case 'data_centre':  return '▦';
    case 'bess_unit':    return '◧';
    case 'bess_block':   return '▣';
    case 'bess_rack':    return '▢';
    case 'dc_hall':      return '▤';
    case 'dc_aisle':     return '▥';
    case 'substation':   return '⏚';
    case 'site':         return '⌖';
    case 'counterparty': return '◯';
    default:             return '◇';
  }
}
