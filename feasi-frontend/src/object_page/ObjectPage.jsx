import {useEffect, useState, useCallback} from 'react';
import {useNavigate, useParams, useSearchParams, Link} from 'react-router-dom';
import SpatialObjectMap, {isSpatialType} from './SpatialObjectMap';
import AmbientCouncilPanel from './AmbientCouncilPanel';
import HealthBadge from './HealthBadge';
import './object-page.css';

/**
 * ObjectPage — Foundry-style typed object detail OR list view.
 *
 *   /v2/object/:type             → list (filters from query params)
 *   /v2/object/:type/:id         → detail (header + properties + links + history + actions)
 *
 * Driven by /api/objects/:type[/:id]. Aesthetic: Princeps cream/gold/glass.
 */

export default function ObjectPage() {
  const {type, id} = useParams();
  const [searchParams] = useSearchParams();

  if (id) return <ObjectDetail type={type} id={id} />;
  return <ObjectList type={type} initialFilters={Object.fromEntries(searchParams.entries())} />;
}

// ─────────────────────────────────────────────────────────────────────────
// LIST VIEW
// ─────────────────────────────────────────────────────────────────────────
function ObjectList({type, initialFilters}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState(initialFilters || {});
  const [selectedId, setSelectedId] = useState(null);
  const navigate = useNavigate();
  const isSpatial = isSpatialType(type);

  const fetchList = useCallback(() => {
    const qs = new URLSearchParams(filters).toString();
    setLoading(true);
    fetch(`/api/objects/${encodeURIComponent(type)}?${qs}`)
      .then(r => r.json())
      .then(setData)
      .catch(err => setData({error: String(err)}))
      .finally(() => setLoading(false));
  }, [type, JSON.stringify(filters)]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const items = data?.items || [];

  return (
    <div className="opx-page">
      <header className="opx-head">
        <Link to="/v2" className="opx-crumb">← Mission Control</Link>
        <h1 className="opx-title">{type}</h1>
        <div className="opx-sub">
          {loading ? 'Loading…' : `${items.length} object${items.length === 1 ? '' : 's'}`}
          {data?.filters && Object.values(data.filters).some(Boolean) && (
            <span className="opx-filter-strip">
              {Object.entries(data.filters)
                .filter(([_, v]) => v != null && v !== '')
                .map(([k, v]) => (
                  <span key={k} className="opx-filter-chip">{k}: {String(v)}</span>
                ))}
            </span>
          )}
        </div>
      </header>

      {data?.error && <div className="opx-err">Error: {data.error}</div>}

      {isSpatial ? (
        <div className="opx-spatial-split">
          <SpatialObjectMap
            objectType={type}
            filters={filters}
            selectedId={selectedId}
            onSelectFeature={(fid) => {
              const id = fid.split(':', 2)[1];
              setSelectedId(id);
              const row = document.querySelector(`[data-row-id="${CSS.escape(id || '')}"]`);
              if (row) row.scrollIntoView({behavior: 'smooth', block: 'center'});
            }}
          />
          <div className="opx-spatial-list">
            {items.map(item => (
              <button
                key={item.id || item.rid}
                data-row-id={item.id}
                className={`opx-list-row ${selectedId === String(item.id) ? 'is-selected' : ''}`}
                onClick={() => navigate(`/v2/object/${encodeURIComponent(type)}/${encodeURIComponent(item.id)}`)}
                onMouseEnter={() => setSelectedId(String(item.id))}>
                <div className="opx-list-main">
                  <span className="opx-list-label">{item.label}</span>
                  <span className="opx-list-id">{item.id?.toString().slice(0, 12)}…</span>
                </div>
                <div className="opx-list-props">
                  {Object.entries(item.properties || {})
                    .filter(([_, v]) => v != null && v !== '')
                    .slice(0, 2)
                    .map(([k, v]) => (
                      <span key={k} className="opx-mini-prop">
                        <span className="opx-mini-prop-key">{k}</span>
                        <span className="opx-mini-prop-val">{formatVal(v)}</span>
                      </span>
                    ))}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="opx-list">
          {items.map(item => (
            <button
              key={item.id || item.rid}
              className="opx-list-row"
              onClick={() => navigate(`/v2/object/${encodeURIComponent(type)}/${encodeURIComponent(item.id)}`)}>
              <div className="opx-list-main">
                <span className="opx-list-label">{item.label}</span>
                <span className="opx-list-id">{item.id?.toString().slice(0, 12)}…</span>
              </div>
              <div className="opx-list-props">
                {Object.entries(item.properties || {})
                  .filter(([_, v]) => v != null && v !== '')
                  .slice(0, 3)
                  .map(([k, v]) => (
                    <span key={k} className="opx-mini-prop">
                      <span className="opx-mini-prop-key">{k}</span>
                      <span className="opx-mini-prop-val">{formatVal(v)}</span>
                    </span>
                  ))}
              </div>
              <span className="opx-list-arr">→</span>
            </button>
          ))}
        </div>
      )}

      {data?.provenance && (
        <footer className="opx-prov">Source: {data.provenance.table}</footer>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// DETAIL VIEW
// ─────────────────────────────────────────────────────────────────────────
function ObjectDetail({type, id}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('properties');
  const [asOf, setAsOf] = useState('');  // YYYY-MM-DD; empty = current

  useEffect(() => {
    setLoading(true);
    const url = asOf
      ? `/api/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}?as_of=${encodeURIComponent(asOf)}`
      : `/api/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}`;
    fetch(url)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(setData)
      .catch(err => setData({error: String(err)}))
      .finally(() => setLoading(false));
  }, [type, id, asOf]);

  if (loading && !data) return <div className="opx-page"><div className="opx-loading">Loading {type} {id}…</div></div>;
  if (data?.error) return <div className="opx-page"><div className="opx-err">{data.error}</div></div>;
  if (!data) return null;

  const {properties = {}, links = [], history = [], actions_available = [], provenance = {}, version_history = [], diff_from_previous} = data;
  const isTimeTraveled = !!data.as_of;

  return (
    <div className="opx-page opx-page-with-rail">
      <div className="opx-main-col">
      <header className="opx-head">
        <Link to={`/v2/object/${encodeURIComponent(type)}`} className="opx-crumb">← {type} list</Link>
        <div className="opx-detail-head">
          <span className="opx-type-chip">{type}</span>
          <h1 className="opx-title">{data.label}</h1>
          <HealthBadge rid={data.rid} />
          <div className="opx-asof">
            <label className="opx-asof-label">as of</label>
            <input
              type="date"
              className="opx-asof-input"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              max={new Date().toISOString().slice(0, 10)}
            />
            {asOf && (
              <button className="opx-asof-clear" onClick={() => setAsOf('')} title="back to current">✕</button>
            )}
          </div>
        </div>
        {isTimeTraveled && (
          <div className="opx-asof-banner">
            ▸ time-traveled snapshot — version active at {data.valid_from?.slice(0, 19)}
            {diff_from_previous && Object.keys(diff_from_previous).length > 0 && (
              <span> · diff from prior: {Object.keys(diff_from_previous).join(', ')}</span>
            )}
          </div>
        )}
        <div className="opx-rid">{data.rid}</div>
      </header>

      {/* Tabs */}
      <div className="opx-tabs">
        {[
          ['properties', `Properties (${Object.keys(properties).length})`],
          ['links',      `Links (${links.length})`],
          ['history',    `History (${history.length})`],
          ['actions',    `Actions (${actions_available.length})`],
          ['pending',    `Pending`],
          ['branches',   `Branches`],
          ['notes',      `Notes`],
        ].map(([k, l]) => (
          <button
            key={k}
            className={`opx-tab ${tab === k ? 'is-active' : ''}`}
            onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {/* Body */}
      <div className="opx-body">
        {tab === 'properties' && (
          <table className="opx-prop-table">
            <tbody>
              {Object.entries(properties).map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{formatVal(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'links' && (
          <div className="opx-links">
            {links.length === 0 && <div className="opx-empty">No outbound links recorded.</div>}
            {links.map((l, i) => (
              <Link
                key={i}
                to={`/v2/object/${encodeURIComponent(l.target_type)}/${encodeURIComponent(l.target_id)}`}
                className="opx-link-row">
                <span className="opx-rel">{l.rel}</span>
                <span className="opx-arrow">→</span>
                <span className="opx-target-type">{l.target_type}</span>
                <span className="opx-target-label">{l.target_label}</span>
                {l.target_summary && <span className="opx-target-sub">{l.target_summary}</span>}
              </Link>
            ))}
          </div>
        )}

        {tab === 'history' && (
          <div className="opx-history">
            {history.length === 0 && <div className="opx-empty">No actions logged for this RID.</div>}
            {history.map(h => (
              <div key={h.log_id} className={`opx-hist-row ${h.ok ? 'ok' : 'err'}`}>
                <span className="opx-hist-action">{h.action}</span>
                <span className="opx-hist-actor">{h.actor}</span>
                <span className="opx-hist-time">{(h.completed_utc || h.started_utc || '').slice(0, 19)}</span>
                {!h.ok && h.error && <span className="opx-hist-err-msg">{h.error}</span>}
              </div>
            ))}
          </div>
        )}

        {tab === 'actions' && (
          <div className="opx-actions">
            {actions_available.length === 0 && <div className="opx-empty">No actions registered for {type}.</div>}
            {actions_available.map(a => (
              <ActionButton key={a.id} action={a} rid={data.rid} type={type} id={id} />
            ))}
          </div>
        )}

        {tab === 'pending' && <PendingApprovalsTab rid={data.rid} />}
        {tab === 'branches' && <BranchesTab rid={data.rid} type={type} id={id} />}
        {tab === 'notes' && <NotesTab rid={data.rid} />}
      </div>

      <footer className="opx-prov">
        <span>Source: <code>{provenance.table}</code></span>
        <span>·</span>
        <span>Class: <code>{provenance.ontology_class}</code></span>
        <button
          type="button"
          className="opx-lineage-btn"
          onClick={() => window.dispatchEvent(new CustomEvent('princeps:lineage', {detail: {root: data.rid}}))}>
          View lineage →
        </button>
      </footer>
      </div>
      <div className="opx-rail-col">
        <AmbientCouncilPanel
          rid={data.rid}
          type={type}
          label={data.label}
          properties={properties}
        />
      </div>
    </div>
  );
}

function BranchesTab({rid, type, id}) {
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [diffOpen, setDiffOpen] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/branches?rid=${encodeURIComponent(rid)}&limit=20`)
      .then(r => r.json())
      .then(d => setBranches(d.branches || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [rid, tick]);

  const create = async () => {
    if (!newName.trim()) { setError('name required'); return; }
    setCreating(true); setError(null);
    try {
      const r = await fetch('/api/branches', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rid, name: newName.trim(), actor: 'ui'}),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        throw new Error(e?.detail || `HTTP ${r.status}`);
      }
      setNewName('');
      setTick(t => t + 1);
    } catch (e) {
      setError(String(e.message || e));
    } finally { setCreating(false); }
  };

  const merge = async (bid) => {
    if (!confirm(`Merge this branch into main? It will overwrite the live ${type} state.`)) return;
    try {
      const r = await fetch(`/api/branches/${bid}/merge`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({actor: 'ui'}),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setTick(t => t + 1);
    } catch (e) { alert(`merge failed: ${e.message || e}`); }
  };

  const discard = async (bid) => {
    if (!confirm('Discard this branch?')) return;
    await fetch(`/api/branches/${bid}`, {method: 'DELETE'});
    setTick(t => t + 1);
  };

  return (
    <div className="opx-branches">
      <div className="opx-branch-create">
        <input
          type="text"
          placeholder="branch name (e.g. what-if-fid-2026Q3)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className="opx-branch-input"
        />
        <button className="opx-branch-btn" disabled={creating} onClick={create}>
          {creating ? 'creating…' : 'fork branch'}
        </button>
      </div>
      {error && <div className="opx-err">{error}</div>}
      {loading && <div className="opx-empty">Loading branches…</div>}
      {!loading && branches.length === 0 && (
        <div className="opx-empty">No branches yet — fork one to explore a what-if scenario.</div>
      )}
      <div className="opx-branch-list">
        {branches.map(b => (
          <div key={b.branch_id} className={`opx-branch-row ${b.status}`}>
            <div className="opx-branch-main">
              <span className="opx-branch-name">{b.name}</span>
              <span className={`opx-branch-status px-h-${b.status === 'merged' ? 'g' : b.status === 'discarded' ? 'r' : 'y'}`}>
                {b.status}
              </span>
              {b.description && <span className="opx-branch-desc">{b.description}</span>}
            </div>
            <div className="opx-branch-meta">
              <span>by {b.created_by || '—'}</span>
              <span>·</span>
              <span>{(b.created_at || '').slice(0, 19)}</span>
              {b.merged_at && <><span>·</span><span>merged {b.merged_at.slice(0, 19)}</span></>}
            </div>
            <div className="opx-branch-actions">
              <button className="opx-branch-act-discard" onClick={() => setDiffOpen(b.branch_id)}>view diff</button>
              {b.status === 'open' && (
                <>
                  <button className="opx-branch-act-merge" onClick={() => merge(b.branch_id)}>merge to main</button>
                  <button className="opx-branch-act-discard" onClick={() => discard(b.branch_id)}>discard</button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {diffOpen && <BranchDiffOverlay branchId={diffOpen} onClose={() => setDiffOpen(null)} />}
    </div>
  );
}

function BranchDiffOverlay({branchId, onClose}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`/api/branches/${branchId}/diff`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(setData)
      .catch(e => setError(String(e)));
  }, [branchId]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="opx-diff-backdrop" onClick={onClose} />
      <aside className="opx-diff-panel" role="dialog" aria-label="Branch diff">
        <header className="opx-diff-head">
          <div>
            <div className="opx-diff-eyebrow">BRANCH DIFF</div>
            <div className="opx-diff-title">{data?.branch_name || branchId.slice(0, 8)}</div>
            <div className="opx-diff-rid">{data?.rid}</div>
          </div>
          <button className="opx-diff-close" onClick={onClose} aria-label="close">×</button>
        </header>

        {!data && !error && <div className="opx-empty">Loading diff…</div>}
        {error && <div className="opx-err">{error}</div>}

        {data && (
          <div className="opx-diff-body">
            <div className="opx-diff-summary">
              <span className="opx-diff-pill px-h-g">+{data.field_count.added}</span>
              <span className="opx-diff-pill px-h-y">~{data.field_count.changed}</span>
              <span className="opx-diff-pill px-h-r">-{data.field_count.removed}</span>
              <span className="opx-diff-meta">{data.edit_count} edit{data.edit_count === 1 ? '' : 's'} · status={data.status}</span>
            </div>

            {data.field_count.changed > 0 && (
              <section className="opx-diff-section">
                <h3>Changed</h3>
                {Object.entries(data.changed).map(([k, v]) => (
                  <div key={k} className="opx-diff-row opx-diff-changed">
                    <span className="opx-diff-key">{k}</span>
                    <div className="opx-diff-vals">
                      <span className="opx-diff-before">{formatVal(v.before)}</span>
                      <span className="opx-diff-arrow">→</span>
                      <span className="opx-diff-after">{formatVal(v.after)}</span>
                    </div>
                  </div>
                ))}
              </section>
            )}

            {data.field_count.added > 0 && (
              <section className="opx-diff-section">
                <h3>Added on branch</h3>
                {Object.entries(data.added).map(([k, v]) => (
                  <div key={k} className="opx-diff-row opx-diff-added">
                    <span className="opx-diff-key">{k}</span>
                    <span className="opx-diff-after">{formatVal(v)}</span>
                  </div>
                ))}
              </section>
            )}

            {data.field_count.removed > 0 && (
              <section className="opx-diff-section">
                <h3>Missing on branch (would be removed on merge)</h3>
                {Object.entries(data.removed).map(([k, v]) => (
                  <div key={k} className="opx-diff-row opx-diff-removed">
                    <span className="opx-diff-key">{k}</span>
                    <span className="opx-diff-before">{formatVal(v)}</span>
                  </div>
                ))}
              </section>
            )}

            {data.field_count.added === 0 && data.field_count.changed === 0 && data.field_count.removed === 0 && (
              <div className="opx-empty">No diff — branch matches main.</div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}

function NotesTab({rid}) {
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [draft, setDraft] = useState({title: '', body: '', tags: ''});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/notes?rid=${encodeURIComponent(rid)}&limit=50`)
      .then(r => r.json())
      .then(d => setNotes(d.notes || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [rid, tick]);

  const create = async () => {
    if (!draft.body.trim()) { setError('body required'); return; }
    setSaving(true); setError(null);
    try {
      const r = await fetch('/api/notes', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          rid,
          title: draft.title.trim() || null,
          body_md: draft.body,
          tags: draft.tags.split(',').map(s => s.trim()).filter(Boolean),
          author: 'ui',
        }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        throw new Error(e?.detail || `HTTP ${r.status}`);
      }
      setDraft({title: '', body: '', tags: ''});
      setTick(t => t + 1);
    } catch (e) {
      setError(String(e.message || e));
    } finally { setSaving(false); }
  };

  const togglePin = async (n) => {
    await fetch(`/api/notes/${n.id}/pin`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pinned: !n.pinned}),
    });
    setTick(t => t + 1);
  };

  const remove = async (n) => {
    if (!confirm('Delete this note?')) return;
    await fetch(`/api/notes/${n.id}`, {method: 'DELETE'});
    setTick(t => t + 1);
  };

  return (
    <div className="opx-notes">
      <div className="opx-note-create">
        <input
          type="text"
          placeholder="title (optional)"
          value={draft.title}
          onChange={(e) => setDraft({...draft, title: e.target.value})}
          className="opx-note-title-input"
        />
        <textarea
          placeholder="markdown body — supports **bold**, headings, lists…"
          value={draft.body}
          onChange={(e) => setDraft({...draft, body: e.target.value})}
          rows={5}
          className="opx-note-body-input"
        />
        <div className="opx-note-create-bottom">
          <input
            type="text"
            placeholder="tags (comma-separated, e.g. grid, dno, finance)"
            value={draft.tags}
            onChange={(e) => setDraft({...draft, tags: e.target.value})}
            className="opx-note-tags-input"
          />
          <button className="opx-note-save" disabled={saving} onClick={create}>
            {saving ? 'saving…' : 'save note'}
          </button>
        </div>
      </div>
      {error && <div className="opx-err">{error}</div>}
      {loading && <div className="opx-empty">Loading notes…</div>}
      {!loading && notes.length === 0 && (
        <div className="opx-empty">No notes yet. Drop the first one above.</div>
      )}
      <div className="opx-note-list">
        {notes.map(n => (
          <article key={n.id} className={`opx-note-card ${n.pinned ? 'is-pinned' : ''}`}>
            <header className="opx-note-head">
              {n.pinned && <span className="opx-note-pin-mark">📌</span>}
              {n.title && <h3 className="opx-note-title">{n.title}</h3>}
              <div className="opx-note-meta">
                {n.author && <span>{n.author}</span>}
                <span>·</span>
                <span>{(n.created_at || '').slice(0, 19)}</span>
                {n.updated_at !== n.created_at && (
                  <><span>·</span><span>edited {(n.updated_at || '').slice(0, 19)}</span></>
                )}
              </div>
              <div className="opx-note-actions">
                <button className="opx-note-act" onClick={() => togglePin(n)}>
                  {n.pinned ? 'unpin' : 'pin'}
                </button>
                <button className="opx-note-act opx-note-act-del" onClick={() => remove(n)}>delete</button>
              </div>
            </header>
            <div className="opx-note-body">{renderMarkdown(n.body_md)}</div>
            {n.tags && n.tags.length > 0 && (
              <footer className="opx-note-tags">
                {n.tags.map(t => <span key={t} className="opx-note-tag">#{t}</span>)}
              </footer>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

// Tiny markdown subset — preserves line breaks, ## H2, **bold**, * list items.
// No third-party dep; safe-ish (no html injection — we escape first then re-apply).
function renderMarkdown(src) {
  if (!src) return null;
  const escape = (s) => s.replace(/[&<>]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]));
  const lines = src.split(/\r?\n/);
  const out = [];
  let listBuf = null;
  const flushList = () => {
    if (listBuf && listBuf.length) {
      out.push(<ul key={`ul-${out.length}`}>{listBuf.map((item, i) => <li key={i} dangerouslySetInnerHTML={{__html: item}} />)}</ul>);
    }
    listBuf = null;
  };
  for (const raw of lines) {
    const line = escape(raw);
    if (/^\s*##\s+/.test(raw)) { flushList(); out.push(<h3 key={`h-${out.length}`}>{raw.replace(/^\s*##\s+/, '')}</h3>); continue; }
    if (/^\s*#\s+/.test(raw)) { flushList(); out.push(<h2 key={`h-${out.length}`}>{raw.replace(/^\s*#\s+/, '')}</h2>); continue; }
    if (/^\s*[-*]\s+/.test(raw)) {
      const item = line.replace(/^\s*[-*]\s+/, '').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      if (!listBuf) listBuf = [];
      listBuf.push(item);
      continue;
    }
    flushList();
    if (raw.trim() === '') { out.push(<br key={`br-${out.length}`} />); continue; }
    out.push(<p key={`p-${out.length}`} dangerouslySetInnerHTML={{__html: line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}} />);
  }
  flushList();
  return out;
}

function ActionButton({action, rid, type, id}) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [stageMode, setStageMode] = useState(true);  // default: safer 2-phase

  const fire = async () => {
    setRunning(true);
    setResult(null);
    try {
      if (stageMode) {
        // 2-phase: stage in pending_actions, requires separate approval
        const res = await fetch('/api/pending-actions', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            object_type: type.toLowerCase(),
            object_id: id,
            action_name: action.id,
            args: {},
            requested_by: 'ui',
          }),
        });
        const j = await res.json();
        setResult({ok: res.ok, status: res.status, body: res.ok
          ? `staged · ${j.pending_id?.slice(0,8)}… — open Pending tab to approve`
          : (j.detail || JSON.stringify(j))});
      } else {
        // legacy direct dispatch
        const res = await fetch(`/api/actions/${encodeURIComponent(action.id)}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({rid, type, id}),
        });
        const txt = await res.text();
        setResult({ok: res.ok, status: res.status, body: txt.slice(0, 240)});
      }
    } catch (err) {
      setResult({ok: false, body: String(err)});
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="opx-action">
      <button className="opx-action-btn" disabled={running} onClick={fire}>
        {running ? '…' : (stageMode ? `Stage: ${action.label}` : action.label)}
      </button>
      <label className="opx-action-mode">
        <input type="checkbox" checked={stageMode} onChange={(e) => setStageMode(e.target.checked)} />
        require approval
      </label>
      {result && (
        <span className={`opx-action-result ${result.ok ? 'ok' : 'err'}`}>
          [{result.status || 'err'}] {result.body}
        </span>
      )}
    </div>
  );
}

function PendingApprovalsTab({rid}) {
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/pending-actions?rid=${encodeURIComponent(rid)}&status=all&limit=50`)
      .then(r => r.json())
      .then(d => setPending(d.pending || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [rid, tick]);

  const approve = async (p) => {
    if (!confirm(`Approve ${p.action_name} on ${p.object_type} ${p.object_id}?`)) return;
    try {
      const res = await fetch(`/api/pending-actions/${p.pending_id}/approve`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({actor: 'ui-approver'}),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTick(t => t + 1);
    } catch (e) { alert(`approve failed: ${e.message || e}`); }
  };

  const reject = async (p) => {
    const note = prompt('Rejection reason (optional)?') || '';
    try {
      await fetch(`/api/pending-actions/${p.pending_id}/reject`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({actor: 'ui-approver', note}),
      });
      setTick(t => t + 1);
    } catch (e) { alert(`reject failed: ${e.message || e}`); }
  };

  return (
    <div className="opx-pending">
      {loading && <div className="opx-empty">Loading pending actions…</div>}
      {error && <div className="opx-err">{error}</div>}
      {!loading && pending.length === 0 && (
        <div className="opx-empty">No pending actions for this object.</div>
      )}
      {pending.map(p => (
        <article key={p.pending_id} className={`opx-pending-row ${p.status}`}>
          <header className="opx-pending-head">
            <span className="opx-pending-action">{p.action_name}</span>
            <span className={`px-h-${p.status === 'approved' ? 'g' : p.status === 'rejected' ? 'r' : 'y'} opx-pending-status`}>{p.status}</span>
            <span className="opx-pending-by">by {p.requested_by}</span>
            <span className="opx-pending-at">{(p.requested_at || '').slice(0, 19)}</span>
          </header>
          {p.preview?.summary && <div className="opx-pending-summary">{p.preview.summary}</div>}
          {p.resolution_note && <div className="opx-pending-note">⚠️ {p.resolution_note}</div>}
          {p.status === 'pending' && (
            <div className="opx-pending-actions">
              <button className="opx-branch-act-merge" onClick={() => approve(p)}>approve & run</button>
              <button className="opx-branch-act-discard" onClick={() => reject(p)}>reject</button>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function formatVal(v) {
  if (v == null) return '—';
  if (typeof v === 'number') return Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
