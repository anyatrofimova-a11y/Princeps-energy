import {useState} from 'react';

/**
 * Pattern (d) — "Configure Trigger" formula UI from the PTM Configurator.
 *
 * Lets a user pick up to 4 real-time tags as variables (x, y, z, w) and
 * write a free-form formula like ``x > 10 && y < 50``. The formula is
 * evaluated by a SAFE evaluator: input is regex-validated to a whitelist
 * (numbers, the four var names, arithmetic + comparison + logical ops,
 * parens, whitespace), so the Function-constructor build cannot reach
 * out to globals.
 *
 * For richer expressions (sin/cos, etc.) swap safeEval for mathjs once
 * mathjs is added to package.json.
 *
 * onSubmit fires with: {name, parentGroup, vars: {x,y,z,w}, formula}.
 */
export function TriggerBuilder({tagOptions = [], parentGroups = [], onSubmit, onCancel}) {
  const [name, setName] = useState('');
  const [parentGroup, setParentGroup] = useState(parentGroups[0] ?? '');
  const [vars, setVars] = useState({x: '', y: '', z: '', w: ''});
  const [formula, setFormula] = useState('x > 10');
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState(null);

  const handleVarChange = (key) => (e) => setVars((v) => ({...v, [key]: e.target.value}));

  const handleTest = () => {
    setError(null);
    setTestResult(null);
    try {
      // Stub values — in a real wire-up, fetch the latest measured value for each tag.
      const sample = {x: 15, y: 30, z: 0, w: 0};
      const result = safeEval(formula, sample);
      setTestResult({sample, result});
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit?.({name, parentGroup, vars, formula});
  };

  return (
    <form className="px-trigger-builder" onSubmit={handleSubmit}>
      <header>Add new subgroup</header>

      <label className="px-field">
        <span>Subgroup name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      <label className="px-field">
        <span>Parent group</span>
        <select value={parentGroup} onChange={(e) => setParentGroup(e.target.value)}>
          {parentGroups.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
      </label>

      {(['x', 'y', 'z', 'w']).map((k) => (
        <label key={k} className="px-field">
          <span>Search trigger tag-{k}</span>
          <input
            list={`px-trigger-tags-${k}`}
            value={vars[k]}
            onChange={handleVarChange(k)}
            placeholder={`real-time tag (${k})`}
          />
          <datalist id={`px-trigger-tags-${k}`}>
            {tagOptions.map((t) => <option key={t} value={t} />)}
          </datalist>
        </label>
      ))}

      <label className="px-field">
        <span>Define formula (e.g. <code>x &gt; 10</code>)</span>
        <input value={formula} onChange={(e) => setFormula(e.target.value)} />
      </label>

      <div className="px-trigger-actions">
        <button type="button" onClick={handleTest}>Test trigger</button>
        <button type="button" onClick={onCancel}>Cancel</button>
        <button type="submit">Add</button>
      </div>

      {testResult ? (
        <div className="px-trigger-result">
          With sample {JSON.stringify(testResult.sample)} → <strong>{String(testResult.result)}</strong>
        </div>
      ) : null}
      {error ? <div className="px-trigger-error">Formula error: {error}</div> : null}
    </form>
  );
}

/**
 * Safe expression evaluator: only allows numbers, our 4 whitelisted var
 * names (x, y, z, w), arithmetic + comparison + logical operators, parens,
 * whitespace. Anything outside that whitelist is rejected before the
 * Function constructor builds the expression.
 *
 * Cannot reach globals: no identifier other than x/y/z/w can pass the regex.
 */
export function safeEval(expr, vars) {
  if (typeof expr !== 'string' || expr.length === 0) {
    throw new Error('formula is empty');
  }
  if (expr.length > 256) {
    throw new Error('formula too long');
  }
  // Strip an identifier check first — only x, y, z, w allowed.
  const idents = expr.match(/[a-zA-Z_][a-zA-Z0-9_]*/g) ?? [];
  for (const id of idents) {
    if (!['x', 'y', 'z', 'w'].includes(id)) {
      throw new Error(`unknown identifier: ${id}`);
    }
  }
  // Whole-expression character whitelist.
  if (!/^[\sxyzw0-9.+\-*/()<>=!&|]+$/.test(expr)) {
    throw new Error('formula contains disallowed characters');
  }
  // eslint-disable-next-line no-new-func
  const fn = new Function('x', 'y', 'z', 'w', `return (${expr});`);
  return fn(numOr0(vars.x), numOr0(vars.y), numOr0(vars.z), numOr0(vars.w));
}

function numOr0(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
