import {useEffect, useState} from 'react';
import {VOLTAGE_COLORS, SOURCE_COLORS} from './GridQueueLayer';

/**
 * D4 — slide-in card surfacing a queue project.
 *
 *   <ProjectInfoCard featureId="repd:9427" onClose={...} />
 *
 * Calls GET /api/grid-overlay/project/:source/:id and renders a
 * MeanderX-style summary: header chip (source + voltage band),
 * 4 KPI tiles (capacity / status / in-service / DNO or LPA),
 * full attribute table, planning ref + URL where present.
 */
export default function ProjectInfoCard({featureId, onClose}) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!featureId) return;
    const [source, id] = featureId.split(':', 2);
    setLoading(true); setErr(null); setData(null);
    fetch(`/api/grid-overlay/project/${source}/${encodeURIComponent(id)}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(setData)
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [featureId]);

  if (!featureId) return null;

  const [source] = featureId.split(':', 1);
  const r = data?.record ?? {};
  const name = r.site_name || r.connection_site || r.substation_name || '—';
  const submitter = r.developer || r.customer_name || r.operator || '—';
  const tech = r.tech_category || r.technology || r.fuel_type || '—';
  const capacity = r.capacity_mw ?? r.tec_mw ?? null;
  const voltage = r.voltage_kv ?? null;
  const status = r.status || '—';
  const inService = r.date_operational || r.connection_date || r.date_decided || r.date_submitted;
  const dno = r.dno || r.planning_authority || '—';

  const voltageBand = _voltageBand(voltage);
  const sourceLabel = {tec: 'NESO TEC', ecr: 'DNO ECR', repd: 'REPD'}[source] ?? source.toUpperCase();

  return (
    <aside className="px-card-overlay" role="dialog" aria-label={`Project ${name}`}>
      <header className="px-card-head">
        <div className="px-card-chips">
          <span className="px-card-chip" style={{background: SOURCE_COLORS[source], color: '#0F1318'}}>
            {sourceLabel}
          </span>
          {voltage != null && (
            <span className="px-card-chip" style={{background: VOLTAGE_COLORS[voltageBand], color: '#FFF'}}>
              {voltageBand}
            </span>
          )}
          <StatusPill status={status} />
        </div>
        <button className="px-card-close" onClick={onClose} aria-label="Close">×</button>
      </header>

      <h2 className="px-card-title">{name}</h2>
      <div className="px-card-sub">{submitter} · {tech}</div>

      {loading && <div className="px-card-loading">Loading…</div>}
      {err && <div className="px-card-err">Failed to load: {err}</div>}

      {!loading && !err && (
        <>
          <div className="px-card-kpis">
            <Kpi label="Capacity"    value={capacity != null ? `${_fmt(capacity)} MW` : '—'} />
            <Kpi label="Voltage"     value={voltage != null ? `${voltage} kV` : '—'} />
            <Kpi label="In-service"  value={_fmtDate(inService)} />
            <Kpi label={source === 'ecr' ? 'DNO' : 'LPA'} value={dno} />
          </div>

          <details className="px-card-attrs" open>
            <summary>All attributes</summary>
            <table>
              <tbody>
                {Object.entries(r).map(([k, v]) => (
                  <tr key={k}>
                    <th>{k}</th>
                    <td>{_fmtVal(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          {r.planning_url && (
            <a href={r.planning_url} target="_blank" rel="noreferrer" className="px-card-link">
              Planning record ↗
            </a>
          )}
        </>
      )}
    </aside>
  );
}

function Kpi({label, value}) {
  return (
    <div className="px-card-kpi">
      <div className="px-card-kpi-l">{label}</div>
      <div className="px-card-kpi-v">{value}</div>
    </div>
  );
}

function StatusPill({status}) {
  const s = (status || '').toLowerCase();
  let cls = 'neutral';
  if (s.includes('approved') || s.includes('operational') || s.includes('built')) cls = 'good';
  else if (s.includes('refused') || s.includes('withdrawn') || s.includes('abandoned')) cls = 'bad';
  else if (s.includes('submitted') || s.includes('progress') || s.includes('scoping')) cls = 'pending';
  return <span className={`px-card-chip px-status-${cls}`}>{status || '—'}</span>;
}

function _voltageBand(v) {
  if (v == null) return 'unknown';
  if (v >= 400) return '400kV+';
  if (v >= 275) return '275kV';
  if (v >= 132) return '132kV';
  if (v >= 66) return '66kV';
  if (v >= 33) return '33kV';
  return '≤22kV';
}
function _fmt(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString(undefined, {maximumFractionDigits: 1});
}
function _fmtDate(d) {
  if (!d) return '—';
  return String(d).slice(0, 10);
}
function _fmtVal(v) {
  if (v == null) return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
