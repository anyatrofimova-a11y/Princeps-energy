import {useState, useMemo} from 'react';

/**
 * Pattern (j) — PTM Configurator.
 *
 * Workspace for engineers to author / browse triggers and equipment-status
 * thresholds. Mirrors the Kongsberg "PTM Configurator" UX:
 *   • Configuration dropdown (Operations / Reliability / All pumps / HH and LL / etc.)
 *   • Grouped-by selector (System / Equipment / Discipline / Tag prefix)
 *   • Filter input (substring on tag id / description / unit)
 *   • Saved configurations dropdown — apply preset filters
 *   • Tabular tag list with green/red dots for inside/outside operating range
 *
 * Props:
 *   configurations: [{id, label}]
 *   savedViews:     [{id, label}]
 *   tags:           [{id, description, unit, value, low, high, state, last24hPct, document}]
 *   onApplySavedView(viewId)
 *   onSaveCurrentView(name, {configurationId, groupBy, filter})
 */
export function PtmConfigurator({
  configurations = [],
  savedViews = [],
  tags = [],
  onApplySavedView,
  onSaveCurrentView,
}) {
  const [configurationId, setConfigurationId] = useState(configurations[0]?.id);
  const [groupBy, setGroupBy] = useState('System');
  const [filter, setFilter] = useState('');

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return tags;
    return tags.filter((t) =>
      [t.id, t.description, t.unit].some((v) => (v ?? '').toLowerCase().includes(f))
    );
  }, [tags, filter]);

  const groups = useMemo(() => groupTags(visible, groupBy), [visible, groupBy]);

  const handleSave = () => {
    const name = window.prompt('Name this view:');
    if (name) onSaveCurrentView?.(name, {configurationId, groupBy, filter});
  };

  return (
    <div className="px-ptm">
      <header className="px-ptm-controls">
        <label className="px-field">
          <span>Configuration</span>
          <select value={configurationId ?? ''} onChange={(e) => setConfigurationId(e.target.value)}>
            {configurations.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </label>
        <label className="px-field">
          <span>Grouped by</span>
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
            <option>System</option>
            <option>Equipment</option>
            <option>Discipline</option>
            <option>Tag prefix</option>
          </select>
        </label>
        <label className="px-field">
          <span>Filter</span>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="tag id, description, unit…" />
        </label>
        <label className="px-field">
          <span>Saved views</span>
          <select onChange={(e) => onApplySavedView?.(e.target.value)} defaultValue="">
            <option value="" disabled>Apply…</option>
            {savedViews.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </label>
        <button type="button" onClick={handleSave}>Save current</button>
      </header>

      <table className="px-ptm-table">
        <thead>
          <tr>
            <th>ID</th><th>Description</th><th>Last value</th><th>Unit</th>
            <th>Low</th><th>High</th><th>State</th><th>Outside % (24h)</th><th>Document</th>
          </tr>
        </thead>
        <tbody>
          {groups.map(({groupKey, items}) => (
            <GroupRows key={groupKey} groupKey={groupKey} items={items} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({groupKey, items}) {
  return (
    <>
      <tr className="px-ptm-group-header">
        <td colSpan={9}>{groupKey} <span className="px-ptm-group-count">({items.length})</span></td>
      </tr>
      {items.map((t) => (
        <tr key={t.id} className={`px-ptm-row px-state-${t.state ?? 'unknown'}`}>
          <td>{t.id}</td>
          <td>{t.description ?? '—'}</td>
          <td>{fmt(t.value)}</td>
          <td>{t.unit ?? '—'}</td>
          <td>{fmt(t.low)}</td>
          <td>{fmt(t.high)}</td>
          <td><span className={`px-state-dot px-state-${t.state ?? 'unknown'}`} aria-label={t.state} /></td>
          <td>{t.last24hPct ?? 0}%</td>
          <td>{t.document ?? ''}</td>
        </tr>
      ))}
    </>
  );
}

function groupTags(tags, groupBy) {
  const buckets = new Map();
  for (const t of tags) {
    const key = bucketKey(t, groupBy);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(t);
  }
  return [...buckets.entries()].map(([groupKey, items]) => ({groupKey, items}));
}

function bucketKey(tag, groupBy) {
  if (groupBy === 'System') return tag.system ?? '—';
  if (groupBy === 'Equipment') return tag.equipment ?? '—';
  if (groupBy === 'Discipline') return tag.discipline ?? '—';
  // Tag prefix — first 4 chars or up to first dash/colon.
  const id = tag.id ?? '';
  const m = id.match(/^([A-Za-z0-9]{1,4})/);
  return m ? m[1] : '—';
}

function fmt(v) {
  if (v == null) return '—';
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
  return String(v);
}
