import {useEffect, useState} from 'react';
import {Link, useParams, useNavigate} from 'react-router-dom';
import PipelineCanvas from './PipelineCanvas.jsx';
import './pipelines.css';

/**
 * /v2/pipelines        — list view + new-pipeline form
 * /v2/pipelines/:slug  — detail: manifest, Run button, run history
 */
export default function PipelinesPage() {
  const {slug} = useParams();
  if (slug) return <PipelineDetail slug={slug} />;
  return <PipelinesList />;
}

function PipelinesList() {
  const [pipes, setPipes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({
    slug: '',
    title: '',
    manifest: JSON.stringify({
      nodes: [
        {id: "src",  kind: "connector_source", props: {slug: "bmrs_settlement_prices"}},
        {id: "sum",  kind: "sql_transform",    props: {sql: "SELECT settlement_date, AVG(system_buy_price)::numeric(10,2) AS avg_buy FROM bmrs_settlement_prices WHERE settlement_date > NOW() - INTERVAL '7 days' GROUP BY settlement_date"}},
        {id: "sink", kind: "dataset_sink",     props: {table: "my_pipeline_output", if_exists: "replace"}}
      ],
      edges: [
        {from: "src", to: "sum"},
        {from: "sum", to: "sink"}
      ]
    }, null, 2),
  });
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    fetch('/api/pipelines?limit=100')
      .then(r => r.json())
      .then(d => setPipes(d.pipelines || []))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tick]);

  const create = async () => {
    let manifest;
    try { manifest = JSON.parse(draft.manifest); }
    catch { setError('manifest must be valid JSON'); return; }
    setCreating(true); setError(null);
    try {
      const r = await fetch('/api/pipelines', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          slug: draft.slug.trim(),
          title: draft.title.trim() || draft.slug.trim(),
          manifest,
          created_by: 'ui',
        }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => null);
        throw new Error(e?.detail || `HTTP ${r.status}`);
      }
      setDraft({...draft, slug: '', title: ''});
      setTick(t => t + 1);
    } catch (e) {
      setError(String(e.message || e));
    } finally { setCreating(false); }
  };

  const del = async (slug) => {
    if (!confirm(`Delete pipeline "${slug}"?`)) return;
    await fetch(`/api/pipelines/${encodeURIComponent(slug)}`, {method: 'DELETE'});
    setTick(t => t + 1);
  };

  return (
    <div className="pipe-page">
      <header className="pipe-head">
        <Link to="/v2" className="pipe-crumb">← Mission Control</Link>
        <h1 className="pipe-title">Pipeline Builder</h1>
        <div className="pipe-sub">
          {loading ? 'loading…' : `${pipes.length} pipeline${pipes.length === 1 ? '' : 's'}`}
        </div>
      </header>

      <details className="pipe-create" open={pipes.length === 0}>
        <summary>+ Create new pipeline</summary>
        <div className="pipe-create-body">
          <div className="pipe-row">
            <input
              type="text" placeholder="slug (e.g. nightly-bess-summary)"
              value={draft.slug} onChange={(e) => setDraft({...draft, slug: e.target.value})}
              className="pipe-input"
            />
            <input
              type="text" placeholder="display title"
              value={draft.title} onChange={(e) => setDraft({...draft, title: e.target.value})}
              className="pipe-input"
            />
          </div>
          <textarea
            className="pipe-manifest-input"
            value={draft.manifest}
            onChange={(e) => setDraft({...draft, manifest: e.target.value})}
            rows={20}
          />
          <button className="pipe-create-btn" disabled={creating} onClick={create}>
            {creating ? 'creating…' : 'create pipeline'}
          </button>
        </div>
      </details>

      {error && <div className="pipe-err">{error}</div>}

      <section className="pipe-list">
        {!loading && pipes.length === 0 && <div className="pipe-empty">No pipelines yet — create one above.</div>}
        {pipes.map(p => (
          <article key={p.slug} className="pipe-card">
            <div className="pipe-card-head">
              <Link to={`/v2/pipelines/${encodeURIComponent(p.slug)}`} className="pipe-card-title">{p.title}</Link>
              <span className={`pipe-status ${p.last_run_ok === true ? 'ok' : p.last_run_ok === false ? 'err' : 'pending'}`}>
                {p.last_run_ok === true ? '✓ ok' : p.last_run_ok === false ? '✕ err' : '— never run'}
              </span>
              <span className="pipe-cadence">{p.cadence || 'on_demand'}</span>
            </div>
            <div className="pipe-card-meta">
              <span className="pipe-slug">{p.slug}</span>
              {p.last_run_at && <><span>·</span><span>last: {p.last_run_at.slice(0, 19)}</span></>}
              <span>·</span>
              <span>{(p.manifest?.nodes || []).length} nodes</span>
            </div>
            {p.description && <div className="pipe-card-desc">{p.description}</div>}
            <div className="pipe-card-actions">
              <Link to={`/v2/pipelines/${encodeURIComponent(p.slug)}`} className="pipe-btn">open</Link>
              <button className="pipe-btn pipe-btn-del" onClick={() => del(p.slug)}>delete</button>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}

function PipelineDetail({slug}) {
  const navigate = useNavigate();
  const [pipe, setPipe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [running, setRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [editingManifest, setEditingManifest] = useState(null);
  const [savingManifest, setSavingManifest] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/pipelines/${encodeURIComponent(slug)}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(setPipe)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [slug, tick]);

  // Live poll the active run while running
  useEffect(() => {
    if (!activeRunId || !running) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const r = await fetch(`/api/pipelines/runs/${activeRunId}`);
          const d = await r.json();
          if (cancelled) return;
          setRunDetail(d);
          if (d.completed_at) {
            setRunning(false);
            setTick(t => t + 1);
            return;
          }
        } catch {}
        await new Promise(r => setTimeout(r, 800));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [activeRunId, running]);

  const run = async () => {
    setRunning(true);
    setRunDetail(null);
    try {
      const r = await fetch(`/api/pipelines/${encodeURIComponent(slug)}/run`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({triggered_by: 'ui'}),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      setActiveRunId(j.run_id);
      // Fetch detail once after the synchronous run completes
      const detail = await fetch(`/api/pipelines/runs/${j.run_id}`).then(x => x.json());
      setRunDetail(detail);
      setRunning(false);
      setTick(t => t + 1);
    } catch (e) {
      alert(`run failed: ${e.message || e}`);
      setRunning(false);
    }
  };

  if (loading && !pipe) return <div className="pipe-page"><div className="pipe-empty">Loading…</div></div>;
  if (error) return <div className="pipe-page"><div className="pipe-err">{error}</div></div>;
  if (!pipe) return null;

  const nodes = pipe.manifest?.nodes || [];
  const edges = pipe.manifest?.edges || [];

  return (
    <div className="pipe-page">
      <header className="pipe-head">
        <Link to="/v2/pipelines" className="pipe-crumb">← Pipelines</Link>
        <h1 className="pipe-title">{pipe.title}</h1>
        <div className="pipe-sub">
          <span className="pipe-slug">{pipe.slug}</span>
          {pipe.cadence && <><span>·</span><span>{pipe.cadence}</span></>}
          {pipe.last_run_at && <><span>·</span><span>last run {pipe.last_run_at.slice(0, 19)}</span></>}
        </div>
      </header>

      <section className="pipe-detail-actions">
        <button className="pipe-run-btn" disabled={running} onClick={run}>
          {running ? '⏵ running…' : '▶ run pipeline'}
        </button>
        {editingManifest && (
          <button
            className="pipe-run-btn"
            style={{background: 'linear-gradient(180deg, #DCFCE7 0%, #22C55E 100%)', borderColor: '#16A34A'}}
            disabled={savingManifest}
            onClick={async () => {
              setSavingManifest(true);
              try {
                const r = await fetch(`/api/pipelines/${encodeURIComponent(slug)}`, {
                  method: 'PATCH',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({manifest: editingManifest}),
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                setEditingManifest(null);
                setTick(t => t + 1);
              } catch (e) { alert(`save failed: ${e.message || e}`); }
              finally { setSavingManifest(false); }
            }}>
            {savingManifest ? 'saving…' : '✓ save canvas changes'}
          </button>
        )}
        {editingManifest && (
          <button className="pipe-btn" onClick={() => setEditingManifest(null)}>discard edits</button>
        )}
        <button className="pipe-btn" onClick={() => navigate('/v2/pipelines')}>back to list</button>
      </section>

      <section className="pipe-dag">
        <div className="pipe-section-head">
          DAG · {(editingManifest || pipe.manifest)?.nodes?.length || 0} nodes · {(editingManifest || pipe.manifest)?.edges?.length || 0} edges
          {editingManifest && <span style={{color: '#F5B731', marginLeft: 12, fontSize: 10}}>UNSAVED</span>}
        </div>
        <PipelineCanvas
          manifest={editingManifest || pipe.manifest}
          onChange={setEditingManifest}
        />
      </section>

      <section>
        <div className="pipe-section-head">Recent runs</div>
        <table className="pipe-runs-table">
          <thead>
            <tr>
              <th>started</th>
              <th>status</th>
              <th>rows</th>
              <th>duration</th>
              <th>by</th>
              <th>error</th>
            </tr>
          </thead>
          <tbody>
            {(pipe.recent_runs || []).map(r => (
              <tr key={r.run_id}>
                <td>{(r.started_at || '').slice(0, 19)}</td>
                <td><span className={`pipe-status ${r.ok ? 'ok' : 'err'}`}>{r.ok ? '✓ ok' : '✕ err'}</span></td>
                <td className="pipe-num">{r.rows_processed?.toLocaleString() || 0}</td>
                <td className="pipe-num">{r.duration_ms}ms</td>
                <td>{r.triggered_by}</td>
                <td className="pipe-err-cell">{r.error || ''}</td>
              </tr>
            ))}
            {(pipe.recent_runs || []).length === 0 && (
              <tr><td colSpan={6} style={{textAlign: 'center', padding: 16, color: '#94A3B8'}}>No runs yet — click ▶ above.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
