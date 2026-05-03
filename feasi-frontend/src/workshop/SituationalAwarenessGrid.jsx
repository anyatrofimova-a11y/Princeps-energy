/**
 * Kognitwin-pattern Situational Awareness Cockpit register grid.
 *
 * Renders a configurable grid (typically 4x4 = 16 tiles) of "register" cards.
 * Each tile shows: title, current count, severity colour, optional 24h trend.
 * Click → fires onTileClick(tileId) so the parent can push the selection
 * into the workspace (table view, P&ID overlay, 3D filter, etc).
 *
 * Tile shape:
 *   {id, title, count, severity ('critical'|'high'|'medium'|'low'|'info'),
 *    trend (-1..1), icon (emoji or string), href (optional drill-down)}
 *
 * Designed to be data-driven from any `/api/registers/...` endpoint that
 * returns this shape; no register-specific logic in the component.
 */
export function SituationalAwarenessGrid({tiles, columns = 4, onTileClick, title}) {
  return (
    <section className="px-sa-grid-section">
      {title ? <header className="px-sa-grid-title">{title}</header> : null}
      <div className="px-sa-grid" style={{gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`}}>
        {tiles.map((t) => (
          <RegisterTile key={t.id} tile={t} onClick={() => onTileClick?.(t.id, t)} />
        ))}
      </div>
    </section>
  );
}

function RegisterTile({tile, onClick}) {
  const {title, count, severity = 'info', trend, icon, unit} = tile;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-register-tile px-severity-${severity}`}
      aria-label={`${title}: ${count}${unit ? ' ' + unit : ''}`}
    >
      <header className="px-register-head">
        <span className="px-register-icon" aria-hidden>{icon}</span>
        <span className="px-register-title">{title}</span>
      </header>
      <div className="px-register-value">
        <span className="px-register-count">{count}</span>
        {unit ? <span className="px-register-unit">{unit}</span> : null}
        {Number.isFinite(trend) ? <TrendArrow value={trend} /> : null}
      </div>
    </button>
  );
}

function TrendArrow({value}) {
  if (value > 0.05) {
    return <span className="px-trend px-trend-up" title={`+${(value * 100).toFixed(0)}% 24h`}>▲</span>;
  }
  if (value < -0.05) {
    return <span className="px-trend px-trend-down" title={`${(value * 100).toFixed(0)}% 24h`}>▼</span>;
  }
  return <span className="px-trend px-trend-flat" title="flat 24h">●</span>;
}
