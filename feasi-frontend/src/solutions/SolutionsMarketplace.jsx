import {useEffect, useState} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import './solutions.css';

/**
 * SolutionsMarketplace — Foundry-style packaged Slate dashboards.
 *
 *   /v2/solutions
 *
 * Browse → install → opens cloned module at /v2/modules/<slug>.
 */

const CAT_COLOURS = {
  'BESS':       '#8B5CF6',
  'Data Centre':'#0EA5E9',
  'Ops':        '#F5B731',
  'Grid':       '#10B981',
  'Risk':       '#EF4444',
};

export default function SolutionsMarketplace() {
  const [packages, setPackages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(null);
  const [filter, setFilter] = useState({category: '', q: '', featured_only: false});
  const [reloadTick, setReloadTick] = useState(0);
  const [publishOpen, setPublishOpen] = useState(false);
  const [modules, setModules] = useState([]);
  const [pubForm, setPubForm] = useState({
    module_slug: '', description: '', category: 'BESS', visibility: 'public',
  });
  const [publishing, setPublishing] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (filter.category) qs.set('category', filter.category);
    if (filter.q) qs.set('q', filter.q);
    if (filter.featured_only) qs.set('featured_only', 'true');
    fetch(`/api/solutions/marketplace?${qs}`)
      .then(r => r.json())
      .then(d => setPackages(d.packages || []))
      .catch(() => setPackages([]))
      .finally(() => setLoading(false));
  }, [filter.category, filter.q, filter.featured_only, reloadTick]);

  // Lazy-load workshop modules only when the publish form opens — avoids
  // an extra request on every marketplace visit.
  useEffect(() => {
    if (!publishOpen) return;
    fetch('/api/workshop/modules')
      .then(r => r.json())
      .then(d => setModules(d.modules || []))
      .catch(() => setModules([]));
  }, [publishOpen]);

  const submitPublish = async (e) => {
    e?.preventDefault?.();
    if (!pubForm.module_slug || !pubForm.description.trim()) {
      alert('Pick a module and write a short description.');
      return;
    }
    setPublishing(true);
    try {
      const r = await fetch('/api/solutions/publish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(pubForm),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      setPublishOpen(false);
      setPubForm({module_slug: '', description: '', category: 'BESS', visibility: 'public'});
      setReloadTick(t => t + 1);
    } catch (err) {
      alert(`publish failed: ${err.message || err}`);
    } finally {
      setPublishing(false);
    }
  };

  const install = async (pkg) => {
    setInstalling(pkg.slug);
    try {
      const r = await fetch(`/api/solutions/${encodeURIComponent(pkg.slug)}/install`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({installed_by: 'ui'}),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      navigate(j.open_at);
    } catch (e) {
      alert(`install failed: ${e.message || e}`);
    } finally {
      setInstalling(null);
    }
  };

  const categories = [...new Set(packages.map(p => p.category).filter(Boolean))].sort();

  return (
    <div className="sol-page">
      <header className="sol-head">
        <Link to="/v2" className="sol-crumb">← Mission Control</Link>
        <h1 className="sol-title">Solutions Marketplace</h1>
        <div className="sol-sub">
          {loading ? 'loading…' : `${packages.length} package${packages.length === 1 ? '' : 's'} available`}
        </div>
        <button
          type="button"
          className="sol-publish-cta"
          onClick={() => setPublishOpen(o => !o)}
          style={{
            marginTop: 12, padding: '6px 14px', border: '1px solid rgba(15,19,24,0.15)',
            background: publishOpen ? '#F5B731' : '#FFF', color: '#0F1318',
            borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
            fontWeight: 600,
          }}>
          {publishOpen ? '× Cancel' : '+ Publish your own module'}
        </button>
        {publishOpen && (
          <form onSubmit={submitPublish} className="sol-publish-form" style={{
            marginTop: 12, padding: 16, background: '#FFF',
            border: '1px solid rgba(15,19,24,0.10)', borderRadius: 8,
            display: 'grid', gap: 10, maxWidth: 560,
          }}>
            <label style={{display: 'grid', gap: 4, fontSize: 11, color: '#5B6470'}}>
              MODULE
              <select
                value={pubForm.module_slug}
                onChange={(e) => setPubForm({...pubForm, module_slug: e.target.value})}
                style={{padding: 6, border: '1px solid rgba(15,19,24,0.15)', borderRadius: 4}}>
                <option value="">— pick a saved module —</option>
                {modules.map(m => (
                  <option key={m.slug} value={m.slug}>{m.title || m.slug} ({m.slug})</option>
                ))}
              </select>
            </label>
            <label style={{display: 'grid', gap: 4, fontSize: 11, color: '#5B6470'}}>
              DESCRIPTION
              <textarea
                value={pubForm.description}
                onChange={(e) => setPubForm({...pubForm, description: e.target.value})}
                rows={2}
                placeholder="What does this module do?"
                style={{padding: 6, border: '1px solid rgba(15,19,24,0.15)', borderRadius: 4, fontFamily: 'inherit', fontSize: 12}}
              />
            </label>
            <div style={{display: 'flex', gap: 12}}>
              <label style={{display: 'grid', gap: 4, fontSize: 11, color: '#5B6470', flex: 1}}>
                CATEGORY
                <select
                  value={pubForm.category}
                  onChange={(e) => setPubForm({...pubForm, category: e.target.value})}
                  style={{padding: 6, border: '1px solid rgba(15,19,24,0.15)', borderRadius: 4}}>
                  {['BESS','Data Centre','Ops','Grid','Risk','Other'].map(c =>
                    <option key={c} value={c}>{c}</option>
                  )}
                </select>
              </label>
              <label style={{display: 'grid', gap: 4, fontSize: 11, color: '#5B6470', flex: 1}}>
                VISIBILITY
                <select
                  value={pubForm.visibility}
                  onChange={(e) => setPubForm({...pubForm, visibility: e.target.value})}
                  style={{padding: 6, border: '1px solid rgba(15,19,24,0.15)', borderRadius: 4}}>
                  <option value="public">public</option>
                  <option value="tenant">tenant</option>
                  <option value="private">private</option>
                </select>
              </label>
            </div>
            <button type="submit" disabled={publishing} style={{
              padding: '8px 14px', border: 'none', borderRadius: 6,
              background: '#F5B731', color: '#0F1318', cursor: 'pointer',
              fontFamily: 'inherit', fontWeight: 600, fontSize: 12,
              opacity: publishing ? 0.6 : 1,
            }}>
              {publishing ? 'publishing…' : 'Publish to marketplace'}
            </button>
          </form>
        )}
      </header>

      <section className="sol-controls">
        <input
          type="text"
          placeholder="search…"
          value={filter.q}
          onChange={(e) => setFilter({...filter, q: e.target.value})}
          className="sol-search"
        />
        <div className="sol-cat-row">
          <button
            className={`sol-cat-pill ${!filter.category ? 'is-active' : ''}`}
            onClick={() => setFilter({...filter, category: ''})}>All</button>
          {categories.map(c => (
            <button
              key={c}
              className={`sol-cat-pill ${filter.category === c ? 'is-active' : ''}`}
              style={filter.category === c ? {background: CAT_COLOURS[c] || '#94A3B8', color: '#FFF'} : null}
              onClick={() => setFilter({...filter, category: c})}>
              {c}
            </button>
          ))}
        </div>
        <label className="sol-featured-toggle">
          <input
            type="checkbox"
            checked={filter.featured_only}
            onChange={(e) => setFilter({...filter, featured_only: e.target.checked})}
          />
          featured only
        </label>
      </section>

      <section className="sol-grid">
        {!loading && packages.length === 0 && (
          <div className="sol-empty">No packages match your filters.</div>
        )}
        {packages.map(p => (
          <article key={p.slug} className={`sol-card ${p.featured ? 'is-featured' : ''}`}>
            {p.featured && <div className="sol-feat-badge">FEATURED</div>}
            <div className="sol-card-head">
              <span className="sol-cat" style={{background: CAT_COLOURS[p.category] || '#94A3B8'}}>
                {p.category || '—'}
              </span>
              <span className="sol-version">v{p.version}</span>
            </div>
            <h3 className="sol-card-title">{p.title}</h3>
            <p className="sol-card-desc">{p.description}</p>

            <div className="sol-card-meta">
              <span><b>{(p.manifest?.widgets || []).length}</b> widgets</span>
              <span>·</span>
              <span><b>{p.install_count}</b> installs</span>
              {p.required_connectors?.length > 0 && (
                <>
                  <span>·</span>
                  <span title={p.required_connectors.join(', ')}>{p.required_connectors.length} connector req</span>
                </>
              )}
            </div>

            <div className="sol-card-tags">
              {(p.required_object_types || []).slice(0, 4).map(t => (
                <span key={t} className="sol-tag">{t}</span>
              ))}
            </div>

            <button
              className="sol-install-btn"
              disabled={installing === p.slug}
              onClick={() => install(p)}>
              {installing === p.slug ? 'installing…' : '+ Install dashboard'}
            </button>
            <div className="sol-author">by {p.published_by || p.author}</div>
          </article>
        ))}
      </section>
    </div>
  );
}
