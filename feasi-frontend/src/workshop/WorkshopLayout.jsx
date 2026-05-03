/**
 * Workshop 3-region layout (Swarm 9).
 *
 *   ┌──────────────────────────────────────────────────────┐
 *   │ header (breadcrumbs + parameter bar)                │
 *   ├────────────┬──────────────────────────┬─────────────┤
 *   │ left:      │ center:                  │ right:      │
 *   │ Object     │ Object View              │ Object      │
 *   │ List /     │ (canvas, twin, table,    │ Inspector   │
 *   │ tree       │  whatever fits the type) │             │
 *   └────────────┴──────────────────────────┴─────────────┘
 *
 * Slots are passed as render-props or React nodes. Layout owns nothing
 * except the grid + responsive collapse.
 */
export function WorkshopLayout({header, leftSlot, centerSlot, rightSlot,
                                leftWidth = 280, rightWidth = 360}) {
  return (
    <div className="px-workshop-layout"
         style={{
           display: 'grid',
           gridTemplateColumns: `${leftWidth}px minmax(0, 1fr) ${rightWidth}px`,
           gridTemplateRows: header ? 'auto 1fr' : '1fr',
           height: '100%',
           minHeight: 0,
         }}>
      {header ? <header className="px-workshop-layout-header" style={{gridColumn: '1 / -1'}}>{header}</header> : null}
      <aside className="px-workshop-layout-left">{leftSlot}</aside>
      <main className="px-workshop-layout-center">{centerSlot}</main>
      <aside className="px-workshop-layout-right">{rightSlot}</aside>
    </div>
  );
}

/**
 * Parameter bar — typed parameters scoped to a workshop view. Replaces the
 * SiteContext god-bag for view-local state. Parent owns the parameter values
 * and passes them in; this component just renders.
 */
export function ParameterBar({params, onChange}) {
  return (
    <div className="px-parameter-bar">
      {params.map((p) => (
        <label key={p.name} className="px-param-field">
          <span>{p.label ?? p.name}</span>
          {p.type === 'select' ? (
            <select value={p.value ?? ''} onChange={(e) => onChange?.(p.name, e.target.value)}>
              {p.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label ?? o.value}</option>
              ))}
            </select>
          ) : p.type === 'date' ? (
            <input type="date" value={p.value ?? ''}
                   onChange={(e) => onChange?.(p.name, e.target.value)} />
          ) : p.type === 'number' ? (
            <input type="number" value={p.value ?? ''}
                   onChange={(e) => onChange?.(p.name, e.target.value)} />
          ) : (
            <input type="text" value={p.value ?? ''}
                   onChange={(e) => onChange?.(p.name, e.target.value)} />
          )}
        </label>
      ))}
    </div>
  );
}
