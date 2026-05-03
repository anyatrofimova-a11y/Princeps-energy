import {useEffect, useState} from 'react';
import {useSelection} from '../workshop/useSelection.jsx';
import {ActionButton} from '../workshop/ActionButton.jsx';
import {useOntologyObject} from '../hooks/queries/index.js';

/**
 * Always-visible right rail. Reads the focused object via
 * `/api/workshop/object/:rid`. Collapsible to a thin spine on narrow
 * viewports — never an overlay.
 */
export function Inspector() {
  const {selectedAssetRid} = useSelection();
  const [collapsed, setCollapsed] = useState(false);
  const {data: obj, isLoading, error} = useOntologyObject(selectedAssetRid);

  // Auto-collapse on small viewports.
  useEffect(() => {
    const onResize = () => setCollapsed(window.innerWidth < 1100);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  if (collapsed) {
    return (
      <div className="px2-inspector-spine" onClick={() => setCollapsed(false)}>
        <button className="px2-inspector-expand" aria-label="expand inspector">◧</button>
      </div>
    );
  }

  return (
    <div className="px2-inspector-panel">
      <header className="px2-inspector-head">
        <span className="px2-inspector-eyebrow">Inspector</span>
        <button className="px2-inspector-collapse" onClick={() => setCollapsed(true)} aria-label="collapse">⟩</button>
      </header>

      {!selectedAssetRid && <div className="px2-inspector-empty">Select an object in the explorer to inspect.</div>}
      {selectedAssetRid && isLoading && <div className="px2-inspector-empty">Loading…</div>}
      {selectedAssetRid && error && <div className="px2-inspector-empty">Error: {String(error)}</div>}

      {obj && (
        <>
          <section className="px2-inspector-id">
            <span className="px2-inspector-type">{obj.type}</span>
            <span className="px2-inspector-name">{obj.name ?? selectedAssetRid}</span>
          </section>

          <Section title="Properties">
            <PropertyList properties={obj.properties} />
          </Section>

          {Array.isArray(obj.relationships) && obj.relationships.length > 0 && (
            <Section title="Relationships">
              <ul className="px2-rels">
                {obj.relationships.slice(0, 12).map((r) => (
                  <li key={r.rid}><span className="px2-rel-type">{r.rel_type}</span> <code>{shortRid(r.to_rid === selectedAssetRid ? r.from_rid : r.to_rid)}</code></li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Actions">
            <div className="px2-actions">
              <ActionButton
                actionId="run_feasibility"
                params={{site_rid: selectedAssetRid, scenario: 'base'}}
                label="Run feasibility"
                icon="▶"
                previewFirst
              />
              <ActionButton
                actionId="screen_counterparty"
                params={{legal_name: obj.name ?? ''}}
                label="Screen sanctions"
                icon="⚖"
              />
            </div>
          </Section>
        </>
      )}
    </div>
  );
}


function Section({title, children}) {
  return (
    <section className="px2-inspector-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function PropertyList({properties}) {
  if (!properties) return <p className="px2-empty">—</p>;
  const skip = new Set(['type', 'rid', 'relationships', 'timeline', 'summary']);
  const entries = Object.entries(properties).filter(([k]) => !skip.has(k));
  return (
    <dl className="px2-props">
      {entries.map(([k, v]) => (
        <div key={k} className="px2-prop">
          <dt>{prettyKey(k)}</dt>
          <dd>{formatVal(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function prettyKey(k) {
  return k.replace(/([A-Z])/g, ' $1').replace(/_/g, ' ').replace(/^\s+/, '').replace(/\b\w/g, (m) => m.toUpperCase());
}

function formatVal(v) {
  if (v == null) return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function shortRid(rid) {
  if (!rid) return '';
  const p = rid.split('.');
  return p.length >= 5 ? `${p[3]}:${p.slice(4).join('.').slice(0, 16)}` : rid;
}
