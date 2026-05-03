import {useEffect, useState} from 'react';
import {ActionButton} from './ActionButton.jsx';
import {useSelection} from './useSelection.jsx';

/**
 * Workshop pattern (Swarm 9) — the ONE generic right-rail inspector.
 *
 * Replaces the 6+ hand-rolled inspectors (AssetInspector, GridConnectionPanel,
 * DemandForecastPanel, BESSPanel, DataCentrePanel, FinancialModelPanel, …) with
 * a single component driven by ontology metadata fetched from
 * `/api/ontology/object/{rid}`.
 *
 * Slots: summary | properties | relationships | timeline | actions
 *
 * Props:
 *   slots        ⊆ ['summary','properties','relationships','timeline','actions']
 *   actions      [{actionId, label, paramsForRid}]   — buttons surfaced inline
 */
export function ObjectInspector({slots = ['summary', 'properties', 'relationships', 'actions'],
                                  actions = []}) {
  const {selectedAssetRid} = useSelection();
  const [obj, setObj] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!selectedAssetRid) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetch(`/api/workshop/object/${encodeURIComponent(selectedAssetRid)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((data) => { if (!cancelled) setObj(data); })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selectedAssetRid]);

  if (!selectedAssetRid) {
    return <aside className="px-inspector px-inspector-empty">Select an object to inspect.</aside>;
  }
  if (loading && !obj) return <aside className="px-inspector">Loading…</aside>;
  if (err) return <aside className="px-inspector px-inspector-error">Error: {err}</aside>;
  if (!obj) return <aside className="px-inspector">No data.</aside>;

  return (
    <aside className="px-inspector">
      <header className="px-inspector-header">
        <span className="px-inspector-type">{obj.type}</span>
        <span className="px-inspector-name">{obj.legal_name ?? obj.name ?? selectedAssetRid}</span>
      </header>

      {slots.includes('summary') && obj.summary ? (
        <Section title="Summary"><p>{obj.summary}</p></Section>
      ) : null}

      {slots.includes('properties') ? (
        <Section title="Properties">
          <PropertyList properties={obj.properties ?? obj} />
        </Section>
      ) : null}

      {slots.includes('relationships') && Array.isArray(obj.relationships) ? (
        <Section title="Relationships">
          <ul className="px-rels">
            {obj.relationships.map((r) => (
              <li key={r.rid} className="px-rel">
                <span className="px-rel-type">{r.rel_type}</span>
                <code className="px-rel-target">{r.to_rid}</code>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {slots.includes('timeline') && Array.isArray(obj.timeline) ? (
        <Section title="Timeline">
          <ul className="px-timeline">
            {obj.timeline.map((e) => (
              <li key={e.id}>
                <time>{e.at}</time>
                <span>{e.label}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {slots.includes('actions') && actions.length > 0 ? (
        <Section title="Actions">
          <div className="px-inspector-actions">
            {actions.map((a) => (
              <ActionButton
                key={a.actionId}
                actionId={a.actionId}
                params={a.paramsForRid ? a.paramsForRid(selectedAssetRid) : {}}
                label={a.label}
                icon={a.icon}
                previewFirst={a.previewFirst}
              />
            ))}
          </div>
        </Section>
      ) : null}
    </aside>
  );
}

function Section({title, children}) {
  return (
    <section className="px-inspector-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function PropertyList({properties}) {
  const skip = new Set(['type', 'rid', 'relationships', 'timeline', 'summary', 'properties']);
  const entries = Object.entries(properties).filter(([k]) => !skip.has(k));
  if (!entries.length) return <p className="px-empty">No properties.</p>;
  return (
    <dl className="px-prop-list">
      {entries.map(([k, v]) => (
        <div key={k} className="px-prop-row">
          <dt>{k}</dt>
          <dd>{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatValue(v) {
  if (v == null) return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
