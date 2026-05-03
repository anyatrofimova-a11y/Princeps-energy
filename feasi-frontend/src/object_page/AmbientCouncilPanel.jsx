import {useState, useMemo} from 'react';
import useCouncilSession from '../hooks/useCouncilSession';
import './ambient-council.css';

/**
 * AmbientCouncilPanel — slim docked rail on every Object Page.
 *
 * Counters Kongsberg's Asset Copilot but with our 3-pod (GRID + BESS + DC)
 * + Adjudicator deliberation pattern. Type-aware suggested questions
 * pre-grounded in the open object's RID + properties.
 *
 * Props:
 *   rid:         ontology rid of the open object
 *   type:        Project | Substation | REPDProject | NSIPProject | TecQueueEntry | Entity
 *   label:       human-readable display name (e.g. "Drax Biomass Power Station - Unit 3")
 *   properties:  full props bag (capacity_mw, voltage_kv, status, etc.)
 */

const SUGGESTIONS_BY_TYPE = {
  Project: [
    "What's the biggest blocker for this project?",
    "Should we advance to the next stage?",
    "Compare risk vs other prospect projects.",
  ],
  Substation: [
    "What's the connection headroom here?",
    "Which queue entries are competing for this substation?",
    "Estimate cost and timeline for a 50MW connection.",
  ],
  REPDProject: [
    "How does this project compare to nearby REPDs?",
    "What planning risks should we watch?",
    "Is the operator credible — what else have they built?",
  ],
  NSIPProject: [
    "What stage is this NSIP at and what's next in the DCO process?",
    "Compare timeline to similar nuclear / DC NSIPs.",
    "Who are the major objectors / consultees?",
  ],
  TecQueueEntry: [
    "When is this likely to be energised?",
    "What's the queue position trend?",
    "Should we apply for non-firm or firm?",
  ],
  Entity: [
    "What's this entity's capacity exposure?",
    "Sanctions / counterparty risk?",
    "Pipeline of upcoming projects under their name?",
  ],
};

export default function AmbientCouncilPanel({rid, type, label, properties}) {
  const [collapsed, setCollapsed] = useState(false);
  const [draft, setDraft] = useState('');
  const {state, start, creating, events} = useCouncilSession();

  const suggestions = SUGGESTIONS_BY_TYPE[type] || ["What should I know about this object?"];

  const groundedQuery = useMemo(() => {
    if (!draft.trim()) return '';
    const lines = [draft.trim(), ''];
    lines.push(`Context — ${type}: ${label}`);
    lines.push(`RID: ${rid}`);
    if (properties && Object.keys(properties).length) {
      const k = ['stage','verdict','status','capacity_mw','voltage_kv','technology','sector','dno']
        .map(x => properties[x] != null ? `${x}=${properties[x]}` : null)
        .filter(Boolean);
      if (k.length) lines.push(`Key props: ${k.join(' · ')}`);
    }
    return lines.join('\n');
  }, [draft, rid, type, label, properties]);

  const fire = async (q) => {
    if (!q.trim()) return;
    try {
      await start({query: q, project_rid: rid});
    } catch (e) {
      console.warn('council start failed', e);
    }
  };

  if (collapsed) {
    return (
      <button className="ac-tab-collapsed" onClick={() => setCollapsed(false)} title="Open Council rail">
        <span className="ac-tab-bullet">●</span>
        <span className="ac-tab-label">Council</span>
      </button>
    );
  }

  const podKeys = ['grid', 'bess', 'dc'];
  const haveAnyPodEvent = Object.keys(state.pods || {}).length > 0;

  return (
    <aside className="ac-panel" role="complementary" aria-label="Council">
      <header className="ac-head">
        <div>
          <div className="ac-eyebrow">PRINCEPS · COUNCIL</div>
          <div className="ac-sub">3-pod deliberation grounded in this {type}</div>
        </div>
        <button className="ac-collapse-btn" onClick={() => setCollapsed(true)} title="Collapse rail">→</button>
      </header>

      {!state.done && !haveAnyPodEvent && !creating && (
        <div className="ac-suggestions">
          <div className="ac-suggestions-eyebrow">SUGGESTED QUESTIONS</div>
          {suggestions.map((s, i) => (
            <button key={i} className="ac-suggestion" onClick={() => fire(s)}>{s}</button>
          ))}
        </div>
      )}

      <div className="ac-prompt">
        <textarea
          rows={3}
          placeholder="Ask the council… (Cmd+Enter to send)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              fire(groundedQuery);
              setDraft('');
            }
          }}
          className="ac-prompt-input"
        />
        <button
          className="ac-send-btn"
          disabled={!draft.trim() || creating}
          onClick={() => { fire(groundedQuery); setDraft(''); }}>
          {creating ? '…' : '▸ deliberate'}
        </button>
      </div>

      {(haveAnyPodEvent || state.done || state.error) && (
        <div className="ac-pods">
          <div className="ac-pods-eyebrow">PODS</div>
          {podKeys.map(k => {
            const pod = state.pods?.[k];
            const status = pod?.verdict ? 'done' : (pod ? 'running' : 'idle');
            const verdict = pod?.verdict;
            const conf = pod?.confidence;
            return (
              <div key={k} className={`ac-pod ${status}`}>
                <span className="ac-pod-name">{k.toUpperCase()}</span>
                <span className="ac-pod-status">{status}</span>
                {verdict && <span className={`ac-pod-verdict v-${verdict.toLowerCase().replace('-','_')}`}>{verdict}</span>}
                {conf != null && <span className="ac-pod-conf">@{Number(conf).toFixed(2)}</span>}
              </div>
            );
          })}
        </div>
      )}

      {state.adjudication && (
        <div className="ac-adj">
          <div className="ac-adj-eyebrow">ADJUDICATION</div>
          <div className="ac-adj-summary">{state.adjudication.summary || state.adjudication.message || '—'}</div>
        </div>
      )}

      {state.final && (
        <div className={`ac-final v-${(state.final.verdict || '').toLowerCase().replace('-','_')}`}>
          <div className="ac-final-eyebrow">FINAL VERDICT</div>
          <div className="ac-final-verdict">{state.final.verdict || '—'}</div>
          {state.final.confidence != null && (
            <div className="ac-final-conf">confidence: {Number(state.final.confidence).toFixed(2)}</div>
          )}
          {state.final.summary && <div className="ac-final-summary">{state.final.summary}</div>}
          {state.session_rid && (
            <a className="ac-final-link" href={`/v2/council`} title="open full session">
              session: {state.session_rid.slice(0, 8)}…
            </a>
          )}
        </div>
      )}

      {state.error && (
        <div className="ac-err">stream error — {state.error}</div>
      )}
    </aside>
  );
}
