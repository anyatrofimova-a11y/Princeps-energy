import {useMemo} from 'react';
import {useSelection} from './useSelection.jsx';

/**
 * Pattern (k) — Trend chart synchronised to an alarms / measurements table.
 *
 * Click a table row → that row's series is highlighted in the chart.
 * Hover a series → the corresponding row is highlighted.
 *
 * Both directions go through the global SelectionContext's focusedSeriesId,
 * so any other component can also drive the highlight (AI assistant click,
 * 3D pick, etc.).
 *
 * Series shape: {id, label, points: [[t, v], ...], color?}
 * Row shape:    {id, seriesId, ...arbitrary fields the table renders}
 *
 * The chart is intentionally vanilla SVG to avoid a uPlot/Plotly dep here;
 * swap for the project's preferred chart lib at integration time.
 */
export function TrendChartTableSync({rows = [], series = [], columns = []}) {
  const {focusedSeriesId, setFocusedSeriesId} = useSelection();

  return (
    <div className="px-trend-sync">
      <div className="px-trend-table-wrap">
        <table className="px-trend-table">
          <thead>
            <tr>
              {columns.map((c) => <th key={c.key}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                className={`px-trend-row${focusedSeriesId === r.seriesId ? ' is-focused' : ''}`}
                onClick={() => setFocusedSeriesId(r.seriesId)}
                onMouseEnter={() => setFocusedSeriesId(r.seriesId)}
              >
                {columns.map((c) => <td key={c.key}>{c.render ? c.render(r) : r[c.key]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-trend-chart-wrap">
        <SvgTrendChart series={series} focusedSeriesId={focusedSeriesId} onFocus={setFocusedSeriesId} />
      </div>
    </div>
  );
}

function SvgTrendChart({series, focusedSeriesId, onFocus}) {
  const W = 640;
  const H = 240;
  const pad = {top: 16, right: 16, bottom: 28, left: 48};
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;

  const {xMin, xMax, yMin, yMax} = useMemo(() => bounds(series), [series]);
  const xScale = (x) => pad.left + ((x - xMin) / Math.max(1, xMax - xMin)) * chartW;
  const yScale = (y) => pad.top + chartH - ((y - yMin) / Math.max(1, yMax - yMin)) * chartH;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="px-trend-chart" role="img">
      <rect x={pad.left} y={pad.top} width={chartW} height={chartH} className="px-trend-bg" />
      <line x1={pad.left} y1={pad.top + chartH} x2={pad.left + chartW} y2={pad.top + chartH} className="px-axis" />
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + chartH} className="px-axis" />
      {series.map((s) => {
        const isFocused = focusedSeriesId === s.id;
        const path = polyline(s.points, xScale, yScale);
        return (
          <path
            key={s.id}
            d={path}
            className={`px-trend-line${isFocused ? ' is-focused' : ''}`}
            stroke={s.color ?? defaultColor(s.id)}
            onMouseEnter={() => onFocus(s.id)}
          >
            <title>{s.label}</title>
          </path>
        );
      })}
    </svg>
  );
}

function bounds(series) {
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  for (const s of series) {
    for (const [t, v] of s.points ?? []) {
      if (t < xMin) xMin = t;
      if (t > xMax) xMax = t;
      if (v < yMin) yMin = v;
      if (v > yMax) yMax = v;
    }
  }
  if (!Number.isFinite(xMin)) return {xMin: 0, xMax: 1, yMin: 0, yMax: 1};
  return {xMin, xMax, yMin, yMax};
}

function polyline(points, xScale, yScale) {
  if (!points?.length) return '';
  return points
    .map(([t, v], i) => `${i === 0 ? 'M' : 'L'}${xScale(t).toFixed(1)},${yScale(v).toFixed(1)}`)
    .join('');
}

function defaultColor(id) {
  // Stable per-id hash → HSL.
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return `hsl(${Math.abs(h) % 360}, 65%, 45%)`;
}
