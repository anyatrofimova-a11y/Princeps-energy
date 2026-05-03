import {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import './sets.css';

/**
 * SetsBrowser — Foundry's ObjectSets surface at /v2/sets.
 * Browse saved typed queries, see their resolved counts, and create new
 * sets via inline JSON filter spec.
 */

const TYPE_OPTIONS = ['REPDProject', 'NSIPProject', 'Substation', 'TecQueueEntry', 'Project', 'Entity'];

export default function SetsBrowser() {
  const [sets, setSets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [filter, setFilter] = useState({type: '', q: ''});
  const [counts, setCounts] = useState({});  // slug → count
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({slug: '', name: '', object_type: 'REPDProject', filters: '{"capacity_min": 50}', tags: ''});

  // Load list
  useEffect(() => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (filter.type) qs.set('type', filter.type);
    if (filter.q) qs.set('q', filter.q);
    fetch(`/api/object-sets?${qs}`)
      .then(r => r.json())
      .then(d => setSets(d.sets || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [filter.type, filter.q, tick]);

  // Resolve counts in parallel for visible sets
  useEffect(() => {
    if (!sets.length) return;
    sets.forEach(s => {
      if (counts[s.slug] != null) return;
      fetch(`/api/object-sets/${encodeURIComponent(s.slug)}/resolve?limit=2000`)
        .then(r => r.ok ? r.json() : null)
        .then(d => d && setCounts(prev => ({...prev, [s.slug]: d.count})))
        .catch(() => {});
    });
  }, [sets, counts]);

  const create = async () => {
    let parsed;
    try { parsed = JSON.parse(draft.filters); }
    catch { setError('filters must be valid JSON'); return; }
    setCreating(true); setError(null);
    try {
      const r = await fetch('/api/object-sets', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          slug: draft.slug.trim(),
          name: draft.name.trim(),
          object_type: draft.object_type,
          filters: parsed,
          tags: draft.tags.split(',').map(s => s.trim()).filter(Boolean),
          created_by: 'ui',
        }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        throw new Error(e?.detail || `HTTP ${r.status}`);
      }
      setDraft({slug: '', name: '', object_type: draft.object_type, filters: '{}', tags: ''});
      setTick(t => t + 1);
    } catch (e) {
      setError(String(e.message || e));
    } finally { setCreating(false); }
  };

  const del = async (slug) => {
    if (!confirm(`Delete set "${slug}"?`)) return;
    await fetch(`/api/object-sets/${encodeURIComponent(slug)}`, {method: 'DELETE'});
    setTick(t => t + 1);
  };

  const pin = async (s) => {
    await fetch(`/api/object-sets/${encodeURIComponent(s.slug)}/pin`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pinned: !s.pinned}),
    });
    setTick(t => t + 1);
  };

  return (
    <div className="oset-page">
      <header className="oset-head">
        <Link to="/v2" className="oset-crumb">← Mission Control</Link>
        <h1 className="oset-title">Object Sets — Saved Queries</h1>
        <div className="oset-sub">
          {loading ? 'loading…' : `${sets.length} set${sets.length === 1 ? '' : 's'}`}
        </div>
      </header>

      <section className="oset-controls">
        <input
          type="text"
          placeholder="search…"
          value={filter.q}
          onChange={(e) => setFilter({...filter, q: e.target.value})}
          className="oset-search"
        />
        <select
          value={filter.type}
          onChange={(e) => setFilter({...filter, type: e.target.value})}
          className="oset-select">
          <option value="">All types</option>
          {TYPE_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </section>

      <details className="oset-create" open={!sets.length}>
        <summary>+ Create a new set</summary>
        <div className="oset-create-body">
          <div className="oset-row">
            <input
              type="text" placeholder="slug (e.g. operational-bess-50mw)" className="oset-input"
              value={draft.slug} onChange={(e) => setDraft({...draft, slug: e.target.value})}
            />
            <input
              type="text" placeholder="display name" className="oset-input"
              value={draft.name} onChange={(e) => setDraft({...draft, name: e.target.value})}
            />
            <select
              value={draft.object_type} className="oset-select"
              onChange={(e) => setDraft({...draft, object_type: e.target.value})}>
              {TYPE_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <textarea
            className="oset-filters-input"
            value={draft.filters}
            onChange={(e) => setDraft({...draft, filters: e.target.value})}
            placeholder='filters JSON, e.g. {"capacity_min": 50, "status": "Operational"}'
            rows={3}
          />
          <div className="oset-row">
            <input
              type="text" placeholder="tags, comma-separated" className="oset-input"
              value={draft.tags} onChange={(e) => setDraft({...draft, tags: e.target.value})}
            />
            <button className="oset-create-btn" disabled={creating} onClick={create}>
              {creating ? 'creating…' : 'create set'}
            </button>
          </div>
        </div>
      </details>

      {error && <div className="oset-err">{error}</div>}

      <section className="oset-grid">
        {!loading && sets.length === 0 && (
          <div className="oset-empty">No sets yet. Create one above.</div>
        )}
        {sets.map(s => (
          <article key={s.slug} className={`oset-card ${s.pinned ? 'is-pinned' : ''} ${s.op ? 'is-derived' : ''}`}>
            <header className="oset-card-head">
              {s.pinned && <span title="pinned">📌</span>}
              <span className="oset-type">{s.object_type}</span>
              {s.op && <span className="oset-op">{s.op.toUpperCase()}</span>}
              <span className="oset-count">
                {counts[s.slug] != null ? `${Number(counts[s.slug]).toLocaleString()} matches` : '—'}
              </span>
            </header>
            <h3 className="oset-card-title">{s.name}</h3>
            <div className="oset-slug">{s.slug}</div>
            {s.description && <p className="oset-desc">{s.description}</p>}
            <pre className="oset-filters">{JSON.stringify(s.filters, null, 2)}</pre>
            {s.member_set_ids?.length > 0 && (
              <div className="oset-members">
                <span className="oset-mlabel">members:</span> {s.member_set_ids.length} set{s.member_set_ids.length === 1 ? '' : 's'}
              </div>
            )}
            {s.tags?.length > 0 && (
              <div className="oset-tags">
                {s.tags.map(t => <span key={t} className="oset-tag">#{t}</span>)}
              </div>
            )}
            <footer className="oset-card-foot">
              <button className="oset-btn" onClick={() => pin(s)}>{s.pinned ? 'unpin' : 'pin'}</button>
              <button className="oset-btn oset-btn-del" onClick={() => del(s.slug)}>delete</button>
              <span className="oset-by">by {s.created_by || '—'}</span>
            </footer>
          </article>
        ))}
      </section>
    </div>
  );
}
