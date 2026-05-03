import {useEffect, useMemo} from 'react';
import {useParams} from 'react-router-dom';
import {useSelection} from '../workshop/useSelection.jsx';
import {AssetWorkspace} from '../workshop/AssetWorkspace.jsx';
import {SituationalAwarenessGrid} from '../workshop/SituationalAwarenessGrid.jsx';
import {TrendChartTableSync} from '../workshop/TrendChartTableSync.jsx';
import {ParameterBar} from '../workshop/WorkshopLayout.jsx';
import {useOntologyObject} from '../hooks/queries/index.js';
import {lazy, Suspense} from 'react';
import './twin-view.css';

const TwinScene = lazy(() => import('./TwinScene.jsx'));

/**
 * Kongsberg-grade Data Centre twin view.
 *
 * Same composition pattern as BESSTwinView — DC-specific tiles + trend.
 * Route: /twin/dc/:rid (e.g. /twin/dc/slough-50)
 */
export default function DCTwinView() {
  const {rid} = useParams();
  const fullRid = `rid.princeps.production.data_centre.${rid}`;
  const {setSelectedAssetRid} = useSelection();
  const {data: dc, isLoading} = useOntologyObject(fullRid);

  useEffect(() => { setSelectedAssetRid(fullRid); }, [fullRid, setSelectedAssetRid]);

  const tiles = useMemo(() => buildDcTiles(dc?.properties), [dc]);
  const trend = useMemo(() => buildDcTrend(dc?.properties), [dc]);

  return (
    <div className="px-twin-view">
      <header className="px-twin-header">
        <div className="px-twin-title">
          <span className="px-twin-eyebrow">Data Centre Twin</span>
          <h1>{dc?.properties?.name ?? `Loading ${rid}…`}</h1>
          {dc?.properties && (
            <div className="px-twin-meta">
              <Stat label="Tier" v={dc.properties.tier} />
              <Stat label="IT Load" v={fmt(dc.properties.itLoadMw, ' MW')} />
              <Stat label="Total" v={fmt(dc.properties.totalGridDrawMw, ' MW')} />
              <Stat label="PUE" v={fmt(dc.properties.currentPue)} highlight
                    danger={dc.properties.currentPue > dc.properties.puEDesign + 0.05} />
              <Stat label="WUE" v={fmt(dc.properties.waterUsageM3PerMwh, ' m³/MWh')} />
              <Stat label="UPS health" v={fmt(dc.properties.upsBatteryHealthPct, '%')}
                    danger={dc.properties.upsBatteryHealthPct < 90} />
              <Stat label="CW supply" v={fmt(dc.properties.chilledWaterSupplyTempC, '°C')} highlight />
              <Stat label="ΔT" v={fmt((dc.properties.chilledWaterReturnTempC ?? 0) - (dc.properties.chilledWaterSupplyTempC ?? 0), '°C')} />
            </div>
          )}
        </div>
        <ParameterBar
          params={[
            {name: 'window', label: 'Window', type: 'select', value: '24h',
              options: [{value:'1h', label:'1h'}, {value:'24h', label:'24h'}, {value:'7d', label:'7d'}]},
          ]}
        />
      </header>

      <main className="px-twin-grid">
        <section className="px-twin-workspace">
          <AssetWorkspace
            mapSlot={(r) => <Placeholder label="Site map" rid={r} />}
            sldSlot={(r) => <DcCoolingPlaceholder rid={r} />}
            threeDSlot={(r) => (
              <Suspense fallback={<div className="px-twin-placeholder">Loading 3D scene…</div>}>
                <TwinScene rid={fullRid} />
              </Suspense>
            )}
            docSlot={(r) => <Placeholder label="Tier III certificate" rid={r} />}
            defaultTab="3d"
          />
        </section>

        <section className="px-twin-registers">
          <SituationalAwarenessGrid title="Registers · DC operations" tiles={tiles} columns={4} />
        </section>

        <section className="px-twin-trend">
          <TrendChartTableSync
            rows={trend.rows}
            series={trend.series}
            columns={[
              {key:'tag', label:'Tag'},
              {key:'value', label:'Value', render: r => fmt(r.value, r.unit)},
              {key:'low', label:'Low'},
              {key:'high', label:'High'},
              {key:'state', label:'State', render: r => <span className={`px-state-dot px-state-${r.state}`} />},
            ]}
          />
        </section>
      </main>

      {isLoading && <div className="px-twin-loading">loading twin…</div>}
    </div>
  );
}


// ────────────────────── helpers ──────────────────────

function buildDcTiles(p) {
  if (!p) return [];
  const pueDelta = (p.currentPue ?? 0) - (p.puEDesign ?? 0);
  return [
    {id:'pue-deviation', title:'PUE deviation', count: pueDelta > 0.05 ? 1 : 0,
      severity: pueDelta > 0.1 ? 'high' : pueDelta > 0.05 ? 'medium' : 'low', icon:'📊', trend:0.02},
    {id:'hotspots', title:'Aisle hotspots', count: 1, severity: 'medium', icon:'🌡', trend:0.0},
    {id:'ups-health', title:'UPS modules <90%', count: p.upsBatteryHealthPct < 90 ? 1 : 0,
      severity: p.upsBatteryHealthPct < 80 ? 'high' : p.upsBatteryHealthPct < 90 ? 'medium' : 'low', icon:'🔋'},
    {id:'genset-test', title:'Genset test due', count: p.gensetTestDueDays < 30 ? 1 : 0,
      severity: p.gensetTestDueDays < 7 ? 'high' : 'low', icon:'⚙'},
    {id:'water-leaks', title:'Water leak alarms', count: 0, severity:'low', icon:'💧'},
    {id:'cooling-overrides', title:'Cooling overrides', count: 0, severity:'low', icon:'❄'},
    {id:'chiller-load', title:'Chiller load', count: '78%', severity:'info', icon:'🌀'},
    {id:'free-cooling', title:'Free-cooling hours/day', count: 14, severity:'info', icon:'🌬'},
    {id:'pdr-inverter', title:'PDR inverter alerts', count: 0, severity:'low', icon:'⚡'},
    {id:'redundancy', title:'2N redundancy intact', count:'✓', severity:'low', icon:'🔁'},
    {id:'tti', title:'TTI YTD (min)', count: p.ttiTotalMinutesYtd ?? 0,
      severity: (p.ttiTotalMinutesYtd ?? 0) > 5 ? 'high' : 'low', icon:'⏱'},
    {id:'work-orders', title:'Open work orders', count: 12, severity:'medium', icon:'🔧'},
    {id:'security-incidents', title:'Security incidents', count: 0, severity:'low', icon:'🔐'},
    {id:'bms-overrides', title:'BMS overrides', count: 2, severity:'medium', icon:'🛡'},
    {id:'curtailment', title:'Curtailment hours', count: 6, severity:'medium', icon:'✂'},
    {id:'cfe-hours', title:'24/7 CFE hours', count: 18, severity:'info', icon:'☘'},
  ];
}

function buildDcTrend(p) {
  const pue = p?.currentPue ?? 1.4;
  const itMw = p?.currentItLoadMw ?? 0;
  const cwT = p?.chilledWaterSupplyTempC ?? 12;
  const f = (fn) => Array.from({length: 60}, (_, k) => [k, fn(k)]);
  return {
    series: [
      {id: 'pue',  label: 'PUE',           points: f(k => pue + Math.sin(k/9)*0.04)},
      {id: 'it',   label: 'IT Load (MW)',  points: f(k => itMw + Math.sin(k/7)*1.5)},
      {id: 'cwt',  label: 'CW supply (°C)', points: f(k => cwT + Math.cos(k/12)*0.8)},
    ],
    rows: [
      {id:'r-pue', seriesId:'pue', tag:'PUE',     value: pue, unit:'',
        low: p?.puEDesign ?? 1.3, high: (p?.puEDesign ?? 1.3) + 0.1,
        state: pue > (p?.puEDesign ?? 1.3) + 0.1 ? 'alarm' : 'ok'},
      {id:'r-it',  seriesId:'it',  tag:'IT Load', value: itMw, unit:'MW',
        low: 0, high: p?.itLoadMw ?? 50, state: 'ok'},
      {id:'r-cwt', seriesId:'cwt', tag:'CW supply', value: cwT, unit:'°C',
        low: 10, high: 14, state: cwT > 14 ? 'alarm' : 'ok'},
    ],
  };
}

function Stat({label, v, highlight, danger}) {
  return (
    <span className={`px-twin-stat${highlight ? ' is-highlight' : ''}${danger ? ' is-danger' : ''}`}>
      <span className="px-twin-stat-label">{label}</span>
      <span className="px-twin-stat-value">{v ?? '—'}</span>
    </span>
  );
}

function Placeholder({label, rid}) {
  return <div className="px-twin-placeholder">{label} for <code>{rid}</code> — wire viewer here.</div>;
}

function DcCoolingPlaceholder({rid}) {
  return (
    <div className="px-twin-sld">
      <pre style={{fontFamily:'JetBrains Mono, monospace', fontSize:11, color:'#CBD5E1', margin:0}}>
{`  Cooling Tower Bank   ←─ Outdoor WB
   │   │   │  (free-cooling when WB < 14°C)
   ▼   ▼   ▼
  ┌──────────────┐
  │  Chillers    │   N+1, water-cooled, 12 MW total
  └──────┬───────┘
         ▼  Chilled water 12°C → Halls
  ╔═══════════════════════════════════════╗
  ║  Hall 1 (24.5 MW)      Hall 2 (25.5 MW) ║
  ║  Pod 1.1 ┃ 1.2 ┃ 1.3 ┃ 1.4              ║
  ║   ┝aisles 3 × 24-rack rows               ║
  ║  Pod 2.1 ┃ 2.2 ┃ 2.3 ┃ 2.4              ║
  ╚═══════════════════════════════════════╝
         ▲
  ┌──────┴───────┐
  │  CRAH/CDU    │   per aisle, ΔT 6°C nominal
  └──────────────┘
            ${rid}`}
      </pre>
    </div>
  );
}

function fmt(v, unit) {
  if (v == null || Number.isNaN(v)) return '—';
  if (typeof v === 'number') {
    const n = Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
    return `${n}${unit ?? ''}`;
  }
  return `${v}${unit ?? ''}`;
}
