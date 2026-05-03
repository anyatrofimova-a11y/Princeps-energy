import {useState} from 'react';

/**
 * Workshop pattern (Swarm 9) — typed action button.
 *
 * Replaces the ~30 hand-rolled `<button onClick={fetch(...)}>` calls scattered
 * across panels with a single primitive that talks to the Action Registry
 * backend (app/actions/registry.py).
 *
 * Lifecycle:
 *   1. User clicks → `params` are validated server-side via the action's
 *      Pydantic schema.
 *   2. If `previewFirst`, server returns a preview string and we render a
 *      confirm dialog before commit.
 *   3. On commit, the server returns ActionResult; we render the summary
 *      + side-effect badges and call `onComplete`.
 *
 * Props:
 *   actionId      — registered id (e.g. "run_feasibility")
 *   params        — payload to send (must satisfy the action's pydantic schema)
 *   label         — button text
 *   icon?         — optional icon
 *   previewFirst  — show preview + confirm before commit (default false)
 *   onComplete(result) — fires after a successful execute
 *   disabled
 */
export function ActionButton({actionId, params, label, icon, previewFirst = false,
                              onComplete, disabled}) {
  const [state, setState] = useState('idle'); // idle | previewing | running | done | error
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const run = async ({withPreview}) => {
    setError(null);
    try {
      if (withPreview) {
        setState('previewing');
        const r = await fetch(`/api/actions/${actionId}/preview`, {
          method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify(params),
        });
        if (!r.ok) throw new Error(await r.text());
        setPreview((await r.json()).preview);
        return;
      }
      setState('running');
      const r = await fetch(`/api/actions/${actionId}`, {
        method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify(params),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setResult(data);
      setState('done');
      onComplete?.(data);
    } catch (e) {
      setError(String(e?.message ?? e));
      setState('error');
    }
  };

  if (state === 'previewing' && preview) {
    return (
      <div className="px-action-preview">
        <p>{preview}</p>
        <div className="px-action-preview-buttons">
          <button onClick={() => { setPreview(null); setState('idle'); }}>Cancel</button>
          <button onClick={() => run({withPreview: false})}>Confirm</button>
        </div>
      </div>
    );
  }

  return (
    <div className={`px-action-button px-action-${state}`}>
      <button
        type="button"
        disabled={disabled || state === 'running'}
        onClick={() => run({withPreview: previewFirst})}
      >
        {icon ? <span className="px-action-icon">{icon}</span> : null}
        <span>{label}</span>
        {state === 'running' ? <span className="px-action-spinner" aria-label="running">…</span> : null}
      </button>
      {state === 'done' && result ? (
        <div className="px-action-result px-action-result-ok">
          <span>{result.summary}</span>
          {(result.side_effects ?? []).map((se) => (
            <span key={se} className="px-action-side-effect">{se}</span>
          ))}
        </div>
      ) : null}
      {state === 'error' && error ? (
        <div className="px-action-result px-action-result-error">{error}</div>
      ) : null}
    </div>
  );
}
