import {useEffect, useMemo, useState} from 'react';
import {useNavigate, useParams, useSearchParams, Link} from 'react-router-dom';
import './quiver.css';

/**
 * Quiver — cross-filter charts over a typed ObjectSet.
 *
 *   /v2/quiver/:type
 *
 * Pick X + Y axes from numeric properties; filter by status/technology;
 * render an SVG scatter (or bar when one axis is categorical) inline.
 * Click a point → navigate to that object's detail page. No chart lib.
 */

const TYPE_OPTIONS = [
  {value: 'Project',       label: 'Projects'},
  {value: 'REPDProject',   label: 'REPD Projects'},
  {value: 'Substation',    label: 'Substations'},
  {value: 'NSIPProject',   label: 'NSIP / DCO'},
  {value: 'TecQueueEntry', label: 'TEC Queue'},
];

export default function QuiverPage() {
  const {type: typeParam} = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const [type, setType] = useState(typeParam || 'REPDProject');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    status: params.get('status') || '',
    technology: params.get('technology') || '',
    capacity_min: params.get('capacity_min') || '',
    voltage_min: params.get('voltage_min') || '',
  });
  const [xField, setXField] = useState(null);
  const [yField, setYField] = useState(null);
  const [hover, setHover] = useState(null);

  // Sync URL when type changes
  useEffect(() => {
    if (typeParam !== type) navigate(`/v2/quiver/${type}`, {replace: true});
  }, [type, typeParam, navigate]);

  // Fetch
  useEffect(() => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (filters.status) qs.set('status', filters.status);
    if (filters.technology) qs.set('technology', filters.technology);
    if (filters.capacity_min) qs.set('capacity_min', filters.capacity_min);
    if (filters.voltage_min) qs.set('voltage_min', filters.voltage_min);
    qs.set('limit', '500');
    fetch(`/api/objects/${encodeURIComponent(type)}?${qs}`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData({items: [], error: 'fetch failed'}))
      .finally(() => setLoading(false));
  }, [type, JSON.stringify(filters)]);

  const items = data?.items || [];

  // Discover numeric + categorical fields by sampling
  const fields = useMemo(() => {
    if (!items.length) return {numeric: [], categorical: []};
    const numeric = new Set();
    const categorical = new Set();
    for (const it of items.slice(0, 50)) {
      for (const [k, v] of Object.entries(it.properties || {})) {
        if (typeof v === 'number' && Number.isFinite(v)) numeric.add(k);
        else if (typeof v === 'string' && v.length < 60) categorical.add(k);
      }
    }
    return {numeric: [...numeric].sort(), categorical: [...categorical].sort()};
  }, [items]);

  // Default axes when fields change
  useEffect(() => {
    if (!fields.numeric.length) return;
    if (!xField || !fields.numeric.includes(xField)) {
      setXField(fields.numeric[0]);
    }
    if (!yField || (!fields.numeric.includes(yField) && !fields.categorical.includes(yField))) {
      setYField(fields.numeric[1] || fields.numeric[0]);
    }
  }, [fields.numeric.join(','), fields.categorical.join(',')]);

  const yIsCategorical = fields.categorical.includes(yField);

  // Compute chart data
  const chart = useMemo(() => {
    if (!xField || !yField) return null;
    if (!yIsCategorical) {
      // Scatter
      const points = items
        .map(it => {
          const x = it.properties?.[xField];
          const y = it.properties?.[yField];
          if (typeof x !== 'number' || typeof y !== 'number') return null;
          return {id: it.id, label: it.label, x, y};
        })
        .filter(Boolean);
      if (!points.length) return {kind: 'empty'};
      const xs = points.map(p => p.x), ys = points.map(p => p.y);
      return {
        kind: 'scatter',
        points,
        xMin: Math.min(...xs), xMax: Math.max(...xs),
        yMin: Math.min(...ys), yMax: Math.max(...ys),
      };
    }
    // Bar — group items by yField (categorical), count or sum xField
    const buckets = new Map();
    for (const it of items) {
      const k = it.properties?.[yField];
      const x = it.properties?.[xField];
      if (k == null) continue;
      const b = buckets.get(k) || {key: k, count: 0, sum: 0, items: []};
      b.count += 1;
      if (typeof x === 'number') b.sum += x;
      b.items.push({id: it.id, label: it.label});
      buckets.set(k, b);
    }
    const bars = [...buckets.values()].sort((a, b) => b.sum - a.sum).slice(0, 12);
    return {kind: 'bar', bars};
  }, [items, xField, yField, yIsCategorical]);

  return (
    <div className="qv-page">
      <header className="qv-head">
        <Link to="/v2" className="qv-crumb">← Mission Control</Link>
        <h1 className="qv-title">Quiver — Charts on Typed Objects</h1>
        <div className="qv-sub">
          {loading ? 'loading…' : `${items.length} ${type} objects`}
        </div>
      </header>

      {/* Controls */}
      <section className="qv-controls">
        <div className="qv-ctl">
          <label>Object Type</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div className="qv-ctl">
          <label>X Axis</label>
          <select value={xField || ''} onChange={(e) => setXField(e.target.value)}>
            {fields.numeric.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div className="qv-ctl">
          <label>Y Axis</label>
          <select value={yField || ''} onChange={(e) => setYField(e.target.value)}>
            <optgroup label="Numeric (scatter)">
              {fields.numeric.map(f => <option key={`n-${f}`} value={f}>{f}</option>)}
            </optgroup>
            <optgroup label="Categorical (bar)">
              {fields.categorical.map(f => <option key={`c-${f}`} value={f}>{f}</option>)}
            </optgroup>
          </select>
        </div>

        <div className="qv-filters">
          <input
            type="text"
            placeholder="status filter…"
            value={filters.status}
            onChange={(e) => setFilters({...filters, status: e.target.value})}
          />
          <input
            type="text"
            placeholder="technology filter…"
            value={filters.technology}
            onChange={(e) => setFilters({...filters, technology: e.target.value})}
          />
          <input
            type="number"
            placeholder="min capacity (MW)"
            value={filters.capacity_min}
            onChange={(e) => setFilters({...filters, capacity_min: e.target.value})}
          />
          {type === 'Substation' && (
            <input
              type="number"
              placeholder="min voltage (kV)"
              value={filters.voltage_min}
              onChange={(e) => setFilters({...filters, voltage_min: e.target.value})}
            />
          )}
        </div>
      </section>

      {/* Chart canvas */}
      <section className="qv-canvas-wrap">
        {!chart && <div className="qv-empty">Pick axes to render.</div>}
        {chart?.kind === 'empty' && (
          <div className="qv-empty">No items have both <code>{xField}</code> and <code>{yField}</code>.</div>
        )}
        {chart?.kind === 'scatter' && (
          <ScatterPlot
            chart={chart} xField={xField} yField={yField}
            hover={hover} setHover={setHover}
            onPick={(id) => navigate(`/v2/object/${encodeURIComponent(type)}/${encodeURIComponent(id)}`)}
          />
        )}
        {chart?.kind === 'bar' && (
          <BarChart
            chart={chart} xField={xField} yField={yField}
            onPick={(itemId) => navigate(`/v2/object/${encodeURIComponent(type)}/${encodeURIComponent(itemId)}`)}
          />
        )}
      </section>

      {/* Hover preview */}
      {hover && (
        <aside className="qv-hover-card">
          <div className="qv-hover-label">{hover.label}</div>
          <div className="qv-hover-vals">
            <span><b>{xField}</b>: {fmtNum(hover.x)}</span>
            <span><b>{yField}</b>: {fmtNum(hover.y)}</span>
          </div>
          <div className="qv-hover-id">{hover.id}</div>
        </aside>
      )}
    </div>
  );
}

function ScatterPlot({chart, xField, yField, hover, setHover, onPick}) {
  const W = 720, H = 440, P = 50;
  const {points, xMin, xMax, yMin, yMax} = chart;
  const xR = xMax - xMin || 1;
  const yR = yMax - yMin || 1;
  const sx = (x) => P + ((x - xMin) / xR) * (W - 2 * P);
  const sy = (y) => H - P - ((y - yMin) / yR) * (H - 2 * P);
  const xTicks = niceTicks(xMin, xMax, 5);
  const yTicks = niceTicks(yMin, yMax, 5);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="qv-svg">
      {/* axes */}
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="#CBD5E1" strokeWidth="1" />
      <line x1={P} y1={P} x2={P} y2={H - P} stroke="#CBD5E1" strokeWidth="1" />

      {/* x ticks */}
      {xTicks.map((t, i) => (
        <g key={`xt-${i}`}>
          <line x1={sx(t)} y1={H - P} x2={sx(t)} y2={H - P + 4} stroke="#CBD5E1" />
          <text x={sx(t)} y={H - P + 18} textAnchor="middle" className="qv-tick">{fmtNum(t)}</text>
        </g>
      ))}
      <text x={W / 2} y={H - 8} textAnchor="middle" className="qv-axis-label">{xField}</text>

      {/* y ticks */}
      {yTicks.map((t, i) => (
        <g key={`yt-${i}`}>
          <line x1={P - 4} y1={sy(t)} x2={P} y2={sy(t)} stroke="#CBD5E1" />
          <text x={P - 8} y={sy(t) + 4} textAnchor="end" className="qv-tick">{fmtNum(t)}</text>
        </g>
      ))}
      <text x={14} y={H / 2} textAnchor="middle" className="qv-axis-label"
            transform={`rotate(-90 14 ${H / 2})`}>{yField}</text>

      {/* points */}
      {points.map((p) => (
        <circle
          key={p.id}
          cx={sx(p.x)} cy={sy(p.y)}
          r={hover?.id === p.id ? 7 : 4}
          fill={hover?.id === p.id ? '#F5B731' : '#7C3AED'}
          stroke="#0F1318"
          strokeWidth={hover?.id === p.id ? 1.6 : 0.8}
          opacity={0.85}
          style={{cursor: 'pointer', transition: 'r 100ms'}}
          onMouseEnter={() => setHover(p)}
          onMouseLeave={() => setHover(null)}
          onClick={() => onPick(p.id)}>
          <title>{`${p.label}\n${xField}=${fmtNum(p.x)} ${yField}=${fmtNum(p.y)}`}</title>
        </circle>
      ))}
    </svg>
  );
}

function BarChart({chart, xField, yField, onPick}) {
  const W = 720, H = 440, P = 50;
  const {bars} = chart;
  const max = Math.max(...bars.map(b => b.sum)) || 1;
  const barW = (W - 2 * P) / Math.max(1, bars.length) - 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="qv-svg">
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="#CBD5E1" strokeWidth="1" />
      <line x1={P} y1={P} x2={P} y2={H - P} stroke="#CBD5E1" strokeWidth="1" />
      {bars.map((b, i) => {
        const h = (b.sum / max) * (H - 2 * P);
        const x = P + i * (barW + 8);
        const y = H - P - h;
        return (
          <g key={b.key} style={{cursor: 'pointer'}} onClick={() => b.items[0] && onPick(b.items[0].id)}>
            <rect x={x} y={y} width={barW} height={h} fill="#F5B731" stroke="#E8A012" />
            <text x={x + barW / 2} y={y - 4} textAnchor="middle" className="qv-tick">{fmtNum(b.sum)}</text>
            <text x={x + barW / 2} y={H - P + 14} textAnchor="middle" className="qv-tick"
                  transform={`rotate(-30 ${x + barW / 2} ${H - P + 14})`}>
              {String(b.key).slice(0, 18)}
            </text>
            <title>{`${b.key}\nΣ${xField} = ${fmtNum(b.sum)}\ncount = ${b.count}`}</title>
          </g>
        );
      })}
      <text x={W / 2} y={H - 4} textAnchor="middle" className="qv-axis-label">{yField}</text>
      <text x={14} y={H / 2} textAnchor="middle" className="qv-axis-label"
            transform={`rotate(-90 14 ${H / 2})`}>Σ {xField}</text>
    </svg>
  );
}

function fmtNum(n) {
  if (n == null) return '—';
  if (Math.abs(n) >= 1000) return Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
  return Number(n).toLocaleString(undefined, {maximumFractionDigits: 2});
}

function niceTicks(min, max, count) {
  if (min === max) return [min];
  const range = max - min;
  const step = Math.pow(10, Math.floor(Math.log10(range / count)));
  const err = (count * step) / range;
  let m = step;
  if (err <= 0.15) m = step * 10;
  else if (err <= 0.35) m = step * 5;
  else if (err <= 0.75) m = step * 2;
  const start = Math.ceil(min / m) * m;
  const out = [];
  for (let v = start; v <= max; v += m) out.push(v);
  return out;
}
