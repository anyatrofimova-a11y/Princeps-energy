// ModuleRuntime.jsx — renders a Workshop Module Builder manifest as a
// 12-column CSS grid. Mounted at /v2/modules/:id.
//
// Princeps tokens — cream + gold, NOT Foundry-dark:
//   bg     : #FBF8F2
//   accent : #F5B731
//   text   : #0F1318
//   font   : DM Sans (UI), JetBrains Mono (numbers)
//   shadow : 0 4px 24px rgba(15,19,24,0.08)
//
// Widget kinds: ObjectCard | ObjectTable | Chart | Map | Markdown | ActionButton
// Bindings use ${variable.field} template syntax — resolved without eval().

import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

const TOKENS = {
  bg: "#FBF8F2",
  card: "#FFFFFF",
  accent: "#F5B731",
  text: "#0F1318",
  muted: "#5B6470",
  border: "rgba(15,19,24,0.08)",
  shadow: "0 4px 24px rgba(15,19,24,0.08)",
  fontUi: "'DM Sans', -apple-system, sans-serif",
  fontMono: "'JetBrains Mono', ui-monospace, monospace",
};

// ── ${var.path} template parser — no eval, just regex + dotted lookup. ──
const TPL_RX = /\$\{([^}]+)\}/g;
function lookup(scope, path) {
  if (!path) return undefined;
  return path.split(".").reduce((acc, k) => (acc == null ? acc : acc[k]), scope);
}
function resolveTpl(tpl, scope) {
  if (typeof tpl !== "string") return tpl;
  const matches = [...tpl.matchAll(TPL_RX)];
  if (!matches.length) return tpl;
  // Single-token bindings keep their typed value. Multi-token = stringified.
  if (matches.length === 1 && matches[0][0] === tpl) {
    const v = lookup(scope, matches[0][1].trim());
    return v === undefined ? tpl : v;
  }
  return tpl.replace(TPL_RX, (_, k) => {
    const v = lookup(scope, k.trim());
    return v === undefined ? "" : String(v);
  });
}
function resolveBindings(bindings, scope) {
  const out = {};
  for (const [k, v] of Object.entries(bindings || {})) out[k] = resolveTpl(v, scope);
  return out;
}

// ── Widget renderers ─────────────────────────────────────────────────────
function ObjectCard({ widget, resolved }) {
  const { props } = widget;
  const fields = Array.isArray(props?.fields) ? props.fields : [];
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{props?.title || widget.id}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
        {fields.slice(0, 4).map((f, i) => (
          <div key={i} style={{ padding: 12, background: TOKENS.bg, borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: TOKENS.muted, marginBottom: 4, fontFamily: TOKENS.fontUi }}>
              {f.label || f.key}
            </div>
            <div style={{ fontSize: 18, color: TOKENS.text, fontFamily: TOKENS.fontMono, fontWeight: 500 }}>
              {fmt(resolved[f.key] ?? f.fallback ?? "—")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ObjectTable({ widget, resolved }) {
  const { props } = widget;
  const cols = Array.isArray(props?.columns) ? props.columns : [];
  const rows = Array.isArray(resolved.rows) ? resolved.rows : [];
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{props?.title || widget.id}</div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: TOKENS.fontUi, fontSize: 13 }}>
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th key={i} style={{ textAlign: "left", padding: "8px 10px", borderBottom: `1px solid ${TOKENS.border}`, color: TOKENS.muted, fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>
                  {c.label || c.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={cols.length} style={{ padding: 16, color: TOKENS.muted, textAlign: "center" }}>No rows</td></tr>
            ) : rows.map((r, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${TOKENS.border}` }}>
                {cols.map((c, j) => (
                  <td key={j} style={{ padding: "8px 10px", color: TOKENS.text, fontFamily: c.mono ? TOKENS.fontMono : TOKENS.fontUi }}>
                    {fmt(r?.[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Chart({ widget }) {
  const series = Array.isArray(widget.props?.series) ? widget.props.series : [];
  const points = series.length ? series : [10, 14, 12, 18, 22, 19, 26, 31, 28, 35];
  const max = Math.max(...points, 1);
  const w = 320, h = 80, step = w / Math.max(points.length - 1, 1);
  const path = points.map((v, i) => `${i ? "L" : "M"}${i * step},${h - (v / max) * h}`).join(" ");
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 80 }}>
        <path d={path} fill="none" stroke={TOKENS.accent} strokeWidth="2" />
      </svg>
      <span style={{ fontSize: 10, color: TOKENS.muted, fontFamily: TOKENS.fontUi }}>TODO: live data follows</span>
    </div>
  );
}

function MapWidget({ widget, resolved }) {
  const center = resolved.center || widget.props?.center || "—";
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <div style={{
        height: 180, borderRadius: 8, position: "relative", overflow: "hidden",
        background: `${TOKENS.bg} repeating-linear-gradient(0deg, transparent 0 23px, ${TOKENS.border} 23px 24px), repeating-linear-gradient(90deg, transparent 0 23px, ${TOKENS.border} 23px 24px)`,
      }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: TOKENS.muted, fontFamily: TOKENS.fontUi, fontSize: 12 }}>
          Map: {String(center)}
        </div>
      </div>
    </div>
  );
}

function Markdown({ widget, resolved }) {
  const text = resolved.text || widget.props?.text || "";
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <pre style={{ whiteSpace: "pre-wrap", fontFamily: TOKENS.fontUi, fontSize: 13, color: TOKENS.text, margin: 0 }}>{text}</pre>
    </div>
  );
}

function ActionButton({ widget, resolved }) {
  const onClick = async () => {
    try {
      const aid = widget.props?.action_id || "noop";
      await fetch(`/api/actions/${encodeURIComponent(aid)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bindings: resolved }),
      });
    } catch (e) { console.warn("action failed", e); }
  };
  return (
    <div style={{ ...cardBase(), display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button onClick={onClick} style={{
        padding: "10px 24px", border: "none", borderRadius: 8, cursor: "pointer",
        background: TOKENS.accent, color: TOKENS.text, fontFamily: TOKENS.fontUi,
        fontSize: 13, fontWeight: 600,
      }}>
        {widget.props?.label || widget.id}
      </button>
    </div>
  );
}

// ─── Slate-equivalent composable widgets — each fetches its own data ──
// All data-fetching widgets accept either:
//   - props.set_slug → /api/object-sets/{slug}/items   (single source of truth)
//   - props.type + filters → /api/objects/{type}        (inline filter spec)
function _itemsUrl(p) {
  if (p?.set_slug) {
    return `/api/object-sets/${encodeURIComponent(p.set_slug)}/items?limit=${p.limit || 200}`;
  }
  if (p?.type) {
    const qs = new URLSearchParams({ limit: String(p.limit || 200) });
    for (const k of ['status', 'technology', 'capacity_min', 'voltage_min', 'q', 'sector']) {
      if (p[k] != null && p[k] !== '') qs.set(k, String(p[k]));
    }
    return `/api/objects/${encodeURIComponent(p.type)}?${qs}`;
  }
  return null;
}

// ─── useObjectEvents — live re-fetch when matching ObjectMutated fires ──
// Returns a `tick` integer that increments on every relevant event so
// callers can include it in their useEffect dep array.
function useObjectEvents({ label, rid, enabled = true }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const qs = new URLSearchParams();
    if (label) qs.set('label', label);
    if (rid)   qs.set('rid', rid);
    let es;
    try {
      es = new EventSource(`/api/events/object-mutated/stream?${qs}`);
    } catch (e) {
      // EventSource unsupported; widgets stay on poll-only.
      return;
    }
    es.onmessage = () => setTick(t => t + 1);
    es.onerror = () => {
      // Browser will auto-reconnect — we just close to avoid duplicate streams
      // when the route changes. Tick stays put; widgets will not re-fetch on
      // a transient network blip.
    };
    return () => { try { es.close(); } catch {} };
  }, [label, rid, enabled]);
  return tick;
}

function QuiverChart({ widget }) {
  const p = widget.props || {};
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const liveTick = useObjectEvents({ label: p.type, enabled: !!p.type });
  useEffect(() => {
    const url = _itemsUrl(p);
    if (!url) { setLoading(false); return; }
    setLoading(true);
    fetch(url)
      .then(r => r.json())
      .then(d => setItems(d.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [p.set_slug, p.type, p.x_field, p.y_field, p.status, p.technology, p.capacity_min, p.voltage_min, p.limit, liveTick]);

  const xs = items.map(it => it.properties?.[p.x_field]).filter(v => typeof v === 'number');
  const ys = items.map(it => it.properties?.[p.y_field]).filter(v => typeof v === 'number');
  const xMin = Math.min(...xs, 0), xMax = Math.max(...xs, 1) || 1;
  const yMin = Math.min(...ys, 0), yMax = Math.max(...ys, 1) || 1;
  const W = 400, H = 240, P = 36;
  const sx = (x) => P + ((x - xMin) / (xMax - xMin || 1)) * (W - 2 * P);
  const sy = (y) => H - P - ((y - yMin) / (yMax - yMin || 1)) * (H - 2 * P);

  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>
        {p.title || `${p.type} — ${p.x_field} × ${p.y_field}`}
      </div>
      {loading ? <div style={{ color: TOKENS.muted, fontSize: 12 }}>loading…</div> : (
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 240 }}>
          <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="#CBD5E1" />
          <line x1={P} y1={P} x2={P} y2={H - P} stroke="#CBD5E1" />
          {items.map((it, i) => {
            const x = it.properties?.[p.x_field], y = it.properties?.[p.y_field];
            if (typeof x !== 'number' || typeof y !== 'number') return null;
            return <circle key={it.id || i} cx={sx(x)} cy={sy(y)} r={3} fill="#7C3AED" stroke="#0F1318" strokeWidth={0.5} opacity={0.85}>
              <title>{`${it.label}: ${p.x_field}=${x} ${p.y_field}=${y}`}</title>
            </circle>;
          })}
          <text x={W / 2} y={H - 6} textAnchor="middle" style={{ fontSize: 10, fill: '#5A5F66' }}>{p.x_field}</text>
          <text x={10} y={H / 2} textAnchor="middle" transform={`rotate(-90 10 ${H/2})`} style={{ fontSize: 10, fill: '#5A5F66' }}>{p.y_field}</text>
        </svg>
      )}
      <div style={{ fontSize: 10, color: TOKENS.muted, marginTop: 4 }}>{items.length} points · /api/objects/{p.type}</div>
    </div>
  );
}

function ObjectList({ widget }) {
  const p = widget.props || {};
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const liveTick = useObjectEvents({ label: p.type, enabled: !!p.type });
  useEffect(() => {
    const url = _itemsUrl(p);
    if (!url) { setLoading(false); return; }
    setLoading(true);
    fetch(url)
      .then(r => r.json())
      .then(d => setItems(d.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [p.set_slug, p.type, p.status, p.technology, p.capacity_min, p.voltage_min, p.limit, p.q, liveTick]);

  const sourceLabel = p.set_slug ? `set:${p.set_slug}` : p.type;
  const cols = p.columns || ['label', ...Object.keys(items[0]?.properties || {}).slice(0, 3)];
  return (
    <div style={cardBase()}>
      <div style={{...cardTitle(), display: 'flex', alignItems: 'center', gap: 6}}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#22C55E', boxShadow: '0 0 6px #22C55E', display: 'inline-block' }} title="live — re-fetches on ObjectMutated" />
        {p.title || `${sourceLabel} list`}
      </div>
      {loading ? <div style={{ color: TOKENS.muted, fontSize: 12 }}>loading…</div> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
          <thead>
            <tr>{cols.map(c => (
              <th key={c} style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${TOKENS.border}`, color: TOKENS.muted, textTransform: 'uppercase', fontSize: 9.5, letterSpacing: 0.6 }}>{c}</th>
            ))}</tr>
          </thead>
          <tbody>
            {items.map(it => (
              <tr key={it.id} style={{ borderBottom: '1px dashed rgba(15,19,24,0.06)' }}>
                {cols.map(c => (
                  <td key={c} style={{ padding: '6px 8px', fontFamily: c === 'label' ? TOKENS.fontUi : 'JetBrains Mono, monospace' }}>
                    {c === 'label' ? (
                      <a href={`/v2/object/${p.type}/${encodeURIComponent(it.id)}`} style={{ color: '#0F1318', textDecoration: 'none', fontWeight: 500 }}>
                        {it[c] ?? it.properties?.[c] ?? '—'}
                      </a>
                    ) : fmt(it.properties?.[c] ?? it[c])}
                  </td>
                ))}
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={cols.length} style={{ padding: 14, textAlign: 'center', color: TOKENS.muted }}>No matches</td></tr>}
          </tbody>
        </table>
      )}
      <div style={{ fontSize: 10, color: TOKENS.muted, marginTop: 6 }}>
        {items.length} rows · {p.set_slug ? `/api/object-sets/${p.set_slug}/items` : `/api/objects/${p.type}`}
      </div>
    </div>
  );
}

function NotesFeed({ widget }) {
  const p = widget.props || {};
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const url = p.rid
      ? `/api/notes?rid=${encodeURIComponent(p.rid)}&limit=${p.limit || 8}`
      : `/api/notes/recent?limit=${p.limit || 8}`;
    setLoading(true);
    fetch(url + (p.tag ? `&tag=${encodeURIComponent(p.tag)}` : ''))
      .then(r => r.json())
      .then(d => setNotes(d.notes || []))
      .catch(() => setNotes([]))
      .finally(() => setLoading(false));
  }, [p.rid, p.tag, p.limit]);

  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{p.title || (p.rid ? 'Notes' : 'Recent notes')}</div>
      {loading ? <div style={{ color: TOKENS.muted, fontSize: 12 }}>loading…</div> : (
        notes.length === 0
          ? <div style={{ color: TOKENS.muted, fontSize: 12 }}>None.</div>
          : notes.map(n => (
            <div key={n.id} style={{ padding: '8px 0', borderBottom: '1px dashed rgba(15,19,24,0.06)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                {n.pinned && <span title="pinned">📌</span>}
                <strong style={{ fontSize: 12 }}>{n.title || n.body_md.slice(0, 60)}</strong>
                <span style={{ marginLeft: 'auto', fontSize: 10, color: TOKENS.muted, fontFamily: 'JetBrains Mono' }}>{(n.created_at || '').slice(0, 19)}</span>
              </div>
              {n.title && <div style={{ fontSize: 11.5, color: TOKENS.text, marginTop: 4, lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>{n.body_md.slice(0, 220)}{n.body_md.length > 220 ? '…' : ''}</div>}
              {n.tags && n.tags.length > 0 && (
                <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {n.tags.map(t => <span key={t} style={{ fontSize: 9.5, padding: '1px 6px', borderRadius: 999, background: 'rgba(245,183,49,0.18)', color: '#4A3208' }}>#{t}</span>)}
                </div>
              )}
            </div>
          ))
      )}
    </div>
  );
}

function KPI({ widget }) {
  const p = widget.props || {};
  const [val, setVal] = useState(null);
  const [loading, setLoading] = useState(true);

  // Resolve which URL to call:
  //   set_slug → /api/object-sets/{slug}/resolve   (value = count)
  //   endpoint + value_path (legacy) → arbitrary URL
  const url = p.set_slug
    ? `/api/object-sets/${encodeURIComponent(p.set_slug)}/resolve?limit=1`
    : p.endpoint;
  const valuePath = p.set_slug ? 'count' : (p.value_path || '');
  // For set-backed KPIs we don't yet know the type, so listen broadly.
  // The hook is cheap (single SSE; widget tick fires on every event).
  const liveTick = useObjectEvents({ label: p.live_label || null, enabled: !!p.set_slug || !!p.live_label });

  useEffect(() => {
    if (!url) { setLoading(false); return; }
    setLoading(true);
    fetch(url)
      .then(r => r.json())
      .then(d => {
        let v = d;
        for (const k of valuePath.split('.').filter(Boolean)) v = v?.[k];
        setVal(v);
      })
      .catch(() => setVal(null))
      .finally(() => setLoading(false));
  }, [url, valuePath, liveTick]);

  const sourceTag = p.set_slug ? `set:${p.set_slug}` : url;
  return (
    <div style={cardBase()}>
      <div style={{ fontSize: 9.5, letterSpacing: 0.10, textTransform: 'uppercase', color: TOKENS.muted, fontWeight: 600 }}>{p.label || widget.id}</div>
      <div style={{ fontSize: 32, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#0F1318', fontVariantNumeric: 'tabular-nums', marginTop: 4 }}>
        {loading ? '…' : (val == null ? '—' : (typeof val === 'number' ? Number(val).toLocaleString() : String(val)))}
        {p.unit && <span style={{ fontSize: 14, color: TOKENS.muted, marginLeft: 6 }}>{p.unit}</span>}
      </div>
      {sourceTag && <div style={{ fontSize: 10, color: TOKENS.muted, marginTop: 6, fontFamily: 'JetBrains Mono' }}>{sourceTag}</div>}
    </div>
  );
}

function DatasetHealth({ widget }) {
  const p = widget.props || {};
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    fetch('/api/datasets')
      .then(r => r.json())
      .then(d => setDatasets(d.datasets || d || []))
      .catch(() => setDatasets([]))
      .finally(() => setLoading(false));
  }, []);
  const dot = (s) => ({ green: '#22C55E', yellow: '#F5B731', red: '#EF4444' }[s] || '#94A3B8');
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{p.title || 'Connector health'}</div>
      {loading ? <div style={{ color: TOKENS.muted, fontSize: 12 }}>loading…</div> : (
        datasets.map(d => (
          <div key={d.slug} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot(d.health_status), display: 'inline-block' }} />
            <span style={{ fontFamily: 'JetBrains Mono', flex: 1 }}>{d.slug}</span>
            <span style={{ color: TOKENS.muted, fontFamily: 'JetBrains Mono', fontSize: 11 }}>
              {d.last_row_count != null ? Number(d.last_row_count).toLocaleString() : '—'}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

// ─── TimeSeriesChart — binned sensor history with min/max band + sparkline ──
// Hits /api/timeseries; re-fetches on any ObjectMutated event tagged
// label='TimeSeries' (or whatever caller-supplied label) so live ingestion
// pipelines can refresh the chart without poll churn.
function TimeSeriesChart({ widget }) {
  const p = widget.props || {};
  const sensorId = p.sensor_id;
  const bin = p.bin || '1h';
  const limit = p.limit || 500;
  const height = p.height || 120;
  const liveLabel = p.live_label || 'TimeSeries';

  const [data, setData] = useState({ points: [], count: 0, from: null, to: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const liveTick = useObjectEvents({ label: liveLabel, enabled: !!liveLabel });

  useEffect(() => {
    if (!sensorId) { setLoading(false); setError('sensor_id required'); return; }
    const qs = new URLSearchParams({ sensor_id: sensorId, bin, limit: String(limit) });
    if (p.from) qs.set('from', p.from);
    if (p.to)   qs.set('to', p.to);
    setLoading(true); setError(null);
    fetch(`/api/timeseries?${qs}`)
      .then(r => r.ok ? r.json() : r.json().then(j => Promise.reject(j)))
      .then(d => { setData(d); setError(null); })
      .catch(e => setError(e?.detail || e?.message || 'fetch failed'))
      .finally(() => setLoading(false));
  }, [sensorId, bin, p.from, p.to, limit, liveTick]);

  const pts = Array.isArray(data.points) ? data.points : [];
  const W = 360, H = height, P = 4;
  let svgBody = null;
  if (pts.length >= 2) {
    const vals = pts.flatMap(pt => [pt.value, pt.min, pt.max].filter(v => v != null));
    const vMin = Math.min(...vals), vMax = Math.max(...vals);
    const span = (vMax - vMin) || 1;
    const sx = (i) => P + (i / (pts.length - 1)) * (W - 2 * P);
    const sy = (v) => H - P - ((v - vMin) / span) * (H - 2 * P);
    const linePath = pts.map((pt, i) =>
      `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(pt.value).toFixed(1)}`
    ).join(' ');
    // Min/max band — closed polygon: forward along max, back along min
    const bandPath =
      pts.map((pt, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(pt.max).toFixed(1)}`).join(' ') +
      ' ' +
      pts.slice().reverse().map((pt, i) => {
        const idx = pts.length - 1 - i;
        return `L${sx(idx).toFixed(1)},${sy(pt.min).toFixed(1)}`;
      }).join(' ') +
      ' Z';
    svgBody = (
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height, display: 'block' }} preserveAspectRatio="none">
        <path d={bandPath} fill={TOKENS.accent} fillOpacity={0.16} stroke="none" />
        <path d={linePath} fill="none" stroke={TOKENS.accent} strokeWidth={1.6} />
      </svg>
    );
  }

  const last = pts.length ? pts[pts.length - 1] : null;
  const first = pts.length ? pts[0] : null;
  const delta = last && first && first.value ? ((last.value - first.value) / first.value) * 100 : null;

  return (
    <div style={cardBase()}>
      <div style={{ ...cardTitle(), display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#22C55E', boxShadow: '0 0 6px #22C55E', display: 'inline-block' }} title="live — re-fetches on ObjectMutated" />
        {p.title || sensorId || widget.id}
      </div>
      {loading ? (
        <div style={{ color: TOKENS.muted, fontSize: 12 }}>loading…</div>
      ) : error ? (
        <div style={{ color: '#900', fontSize: 12 }}>{String(error)}</div>
      ) : pts.length === 0 ? (
        <div style={{ color: TOKENS.muted, fontSize: 12 }}>No points in window.</div>
      ) : (
        <>
          {svgBody}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 8 }}>
            <span style={{ fontFamily: TOKENS.fontMono, fontSize: 22, fontWeight: 600, color: TOKENS.text }}>
              {fmt(last.value)}
            </span>
            {delta != null && (
              <span style={{
                fontFamily: TOKENS.fontMono, fontSize: 11,
                color: delta >= 0 ? '#22C55E' : '#EF4444',
              }}>
                {delta >= 0 ? '+' : ''}{delta.toFixed(1)}%
              </span>
            )}
          </div>
        </>
      )}
      <div style={{ fontSize: 10, color: TOKENS.muted, marginTop: 6, fontFamily: TOKENS.fontMono }}>
        {pts.length} pts · bin={bin} · /api/timeseries
      </div>
    </div>
  );
}

const RENDERERS = {
  ObjectCard, ObjectTable, Chart, Map: MapWidget, Markdown, ActionButton,
  // Slate widgets
  QuiverChart, ObjectList, NotesFeed, KPI, DatasetHealth, TimeSeriesChart,
};

function fmt(v) {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(2);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function cardBase() {
  return { background: TOKENS.card, borderRadius: 12, padding: 16, boxShadow: TOKENS.shadow, border: `1px solid ${TOKENS.border}` };
}
function cardTitle() {
  return { fontSize: 13, fontWeight: 600, color: TOKENS.text, fontFamily: TOKENS.fontUi, marginBottom: 12, letterSpacing: 0.2 };
}

// ── Public helper: render a manifest inline (used by ComposeDemo). ──
export function renderManifest(manifest) {
  if (!manifest || !Array.isArray(manifest.widgets)) {
    return <div style={{ padding: 24, color: TOKENS.muted, fontFamily: TOKENS.fontUi }}>No manifest.</div>;
  }
  const scope = manifest.bindings_scope || {}; // future: hydrate from /api/objects
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 12 }}>
      {manifest.widgets.map((w) => {
        const Renderer = RENDERERS[w.kind];
        const resolved = resolveBindings(w.bindings || {}, scope);
        const style = { gridColumn: `span ${Math.min(Math.max(w.w || 6, 1), 12)}` };
        if (w.row) style.gridRow = String(w.row);
        return (
          <div key={w.id} style={style}>
            {Renderer ? <Renderer widget={w} resolved={resolved} /> : (
              <div style={cardBase()}>Unknown widget: {w.kind}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Publish-to-marketplace modal ──
// Small overlay so a user can republish the currently-loaded module
// without leaving the page. POSTs to /api/solutions/publish.
function PublishModal({ moduleSlug, defaultTitle, onClose }) {
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("BESS");
  const [visibility, setVisibility] = useState("public");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!description.trim()) { setError("Description required."); return; }
    setBusy(true); setError(null);
    try {
      const r = await fetch("/api/solutions/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          module_slug: moduleSlug,
          title: defaultTitle,
          description, category, visibility,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      setDone(j);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const lbl = { display: "grid", gap: 4, fontSize: 10, color: TOKENS.muted, fontWeight: 600, letterSpacing: 0.6 };
  const fld = { padding: 6, border: `1px solid ${TOKENS.border}`, borderRadius: 4, fontFamily: TOKENS.fontUi, fontSize: 12 };
  const btnPri = { padding: "8px 14px", border: "none", borderRadius: 6, cursor: "pointer", background: TOKENS.accent, color: TOKENS.text, fontWeight: 600, fontSize: 12, fontFamily: TOKENS.fontUi };
  const btnGhost = { padding: "8px 14px", border: `1px solid ${TOKENS.border}`, borderRadius: 6, background: "#FFF", color: TOKENS.text, cursor: "pointer", fontSize: 12, fontFamily: TOKENS.fontUi };

  return (
    <div role="dialog" aria-modal="true" style={{
      position: "fixed", inset: 0, background: "rgba(15,19,24,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
    }} onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} style={{
        background: TOKENS.card, padding: 20, borderRadius: 10, width: 440,
        boxShadow: TOKENS.shadow, fontFamily: TOKENS.fontUi, display: "grid", gap: 12,
      }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>Publish "{defaultTitle}" to marketplace</div>
        {done ? (
          <>
            <div style={{ fontSize: 12, color: TOKENS.text, padding: 10, background: TOKENS.bg, borderRadius: 6 }}>
              Published as <code style={{ fontFamily: TOKENS.fontMono }}>{done.slug}</code>.
            </div>
            <button type="button" onClick={onClose} style={btnPri}>Done</button>
          </>
        ) : (
          <>
            <label style={lbl}>
              DESCRIPTION
              <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                rows={2} placeholder="What does this module do?" style={fld} />
            </label>
            <div style={{ display: "flex", gap: 10 }}>
              <label style={{ ...lbl, flex: 1 }}>
                CATEGORY
                <select value={category} onChange={(e) => setCategory(e.target.value)} style={fld}>
                  {["BESS","Data Centre","Ops","Grid","Risk","Other"].map(c =>
                    <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label style={{ ...lbl, flex: 1 }}>
                VISIBILITY
                <select value={visibility} onChange={(e) => setVisibility(e.target.value)} style={fld}>
                  <option value="public">public</option>
                  <option value="tenant">tenant</option>
                  <option value="private">private</option>
                </select>
              </label>
            </div>
            {error && <div style={{ fontSize: 11, color: "#B91C1C" }}>{error}</div>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" onClick={onClose} style={btnGhost}>Cancel</button>
              <button type="submit" disabled={busy} style={{ ...btnPri, opacity: busy ? 0.6 : 1 }}>
                {busy ? "publishing…" : "Publish"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

export default function ModuleRuntime() {
  const { id } = useParams();
  const [manifest, setManifest] = useState(null);
  const [error, setError] = useState(null);
  const [publishOpen, setPublishOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    setError(null); setManifest(null);
    fetch(`/api/workshop/modules/${encodeURIComponent(id)}`)
      .then((r) => r.ok ? r.json() : r.json().then((j) => Promise.reject(j)))
      .then((row) => alive && setManifest(row.manifest || row))
      .catch((e) => alive && setError(e?.detail || e?.message || "Failed to load module"));
    return () => { alive = false; };
  }, [id]);

  const titleLine = useMemo(() => manifest ? (manifest.title || id) : "Loading…", [manifest, id]);

  return (
    <div style={{ background: TOKENS.bg, minHeight: "100vh", padding: "32px 40px", fontFamily: TOKENS.fontUi, color: TOKENS.text }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 4 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{titleLine}</h1>
          {manifest?.target_type && (
            <span style={{ fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6 }}>{manifest.target_type}</span>
          )}
        </div>
        {manifest && (
          <div style={{ marginBottom: 20 }}>
            <button
              type="button"
              onClick={() => setPublishOpen(true)}
              style={{
                background: "transparent", border: "none", padding: 0, cursor: "pointer",
                color: TOKENS.muted, fontFamily: TOKENS.fontUi, fontSize: 11,
                textDecoration: "underline", textUnderlineOffset: 2,
              }}
              title="Publish this module as an installable marketplace package">
              ▸ Publish to marketplace
            </button>
          </div>
        )}
        {error && (
          <div style={{ padding: 16, background: "#FEE", border: "1px solid #F99", borderRadius: 8, color: "#900" }}>
            {String(error)}
          </div>
        )}
        {!error && manifest && renderManifest(manifest)}
        {!error && !manifest && <div style={{ color: TOKENS.muted }}>Loading…</div>}
      </div>
      {publishOpen && (
        <PublishModal
          moduleSlug={id}
          defaultTitle={manifest?.title || id}
          onClose={() => setPublishOpen(false)}
        />
      )}
    </div>
  );
}
