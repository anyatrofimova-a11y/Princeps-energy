import {SOURCE_COLORS} from './GridQueueLayer';

/**
 * D4 — voltage + source filter chips for the queue overlay.
 *
 *   <QueueFilterBar
 *      voltageMin={value}
 *      onVoltageMin={setValue}
 *      sources={['tec','ecr','repd']}
 *      onSourcesToggle={(src) => ...}
 *      counts={{queue: 1240, lines: 87}}
 *   />
 */
const VOLTAGE_OPTIONS = [
  {label: 'All',     value: 0},
  {label: '≥33 kV',  value: 33},
  {label: '≥66 kV',  value: 66},
  {label: '≥132 kV', value: 132},
  {label: '≥275 kV', value: 275},
  {label: '400 kV',  value: 400},
];

const SOURCE_OPTIONS = [
  {key: 'tec',  label: 'TEC',  hint: 'NESO transmission queue'},
  {key: 'ecr',  label: 'ECR',  hint: 'DNO embedded register'},
  {key: 'repd', label: 'REPD', hint: 'Renewables planning'},
];

export default function QueueFilterBar({
  voltageMin = 0,
  onVoltageMin,
  sources = ['tec', 'ecr', 'repd'],
  onSourcesToggle,
  showLines = true,
  onShowLinesToggle,
  counts,
}) {
  const toggle = (k) => {
    if (sources.includes(k)) onSourcesToggle?.(sources.filter(s => s !== k));
    else onSourcesToggle?.([...sources, k]);
  };

  return (
    <div className="px-queue-filterbar">
      <div className="px-fb-group">
        <span className="px-fb-label">Voltage</span>
        {VOLTAGE_OPTIONS.map(o => (
          <button
            key={o.value}
            className={`px-fb-chip ${voltageMin === o.value ? 'is-active' : ''}`}
            onClick={() => onVoltageMin?.(o.value)}>
            {o.label}
          </button>
        ))}
      </div>

      <div className="px-fb-group">
        <span className="px-fb-label">Source</span>
        {SOURCE_OPTIONS.map(o => {
          const on = sources.includes(o.key);
          return (
            <button
              key={o.key}
              title={o.hint}
              className={`px-fb-chip ${on ? 'is-active' : ''}`}
              onClick={() => toggle(o.key)}
              style={on ? {borderColor: SOURCE_COLORS[o.key], boxShadow: `inset 0 -2px 0 ${SOURCE_COLORS[o.key]}`} : null}>
              {o.label}
            </button>
          );
        })}
      </div>

      <div className="px-fb-group">
        <button
          className={`px-fb-chip ${showLines ? 'is-active' : ''}`}
          onClick={() => onShowLinesToggle?.(!showLines)}>
          Lines {showLines ? '✓' : '✗'}
        </button>
      </div>

      {counts && (
        <div className="px-fb-counts">
          <span>{counts.queue ?? 0} projects</span>
          <span>·</span>
          <span>{counts.lines ?? 0} lines</span>
        </div>
      )}
    </div>
  );
}
