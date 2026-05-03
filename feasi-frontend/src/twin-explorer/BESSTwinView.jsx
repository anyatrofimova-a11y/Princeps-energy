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
 * Kongsberg-grade BESS twin view.
 *
 * Composes existing Workshop primitives:
 *   • header        — ParameterBar (window selector)
 *   • center top    — AssetWorkspace tabs (Map / SLD / 3D / Doc)
 *   • center mid    — SituationalAwarenessGrid (BESS-specific registers)
 *   • center bottom — TrendChartTableSync (live SoC / P / Tmax)
 *
 * The right-side ObjectInspector and left-side ontology tree are provided
 * by the surrounding WorkshopShell — clicking the BESS in the tree updates
 * `selectedAssetRid`, which auto-populates the inspector.
 *
 * Route: /twin/bess/:rid (e.g. /twin/bess/essex-100)
 */
export default function BESSTwinView() {
  const {rid} = useParams();
  const fullRid = `rid.princeps.production.bess_unit.${rid}`;
  const {setSelectedAssetRid} = useSelection();
  const {data: bess, isLoading} = useOntologyObject(fullRid);

  useEffect(() => { setSelectedAssetRid(fullRid); }, [fullRid, setSelectedAssetRid]);

  const tiles = useMemo(() => buildBessTiles(bess?.properties), [bess]);
  const trend = useMemo(() => buildBessTrend(bess?.properties), [bess]);

  return (
    <div className="px-twin-view">
      <header className="px-twin-header">
        <div className="px-twin-title">
          <span className="px-twin-eyebrow">BESS Twin</span>
          <h1>{bess?.properties?.name ?? `Loading ${rid}…`}</h1>
          {bess?.properties && (
            <div className="px-twin-meta">
              <Stat label="Rated" v={`${bess.properties.ratedPowerMw} MW`} />
              <Stat label="Capacity" v={`${bess.properties.energyCapacityMwh} MWh`} />
              <Stat label="Chemistry" v={bess.properties.chemistry} />
              <Stat label="SoC" v={fmt(bess.properties.stateOfChargePct, '%')} highlight />
              <Stat label="P" v={fmt(bess.properties.activePowerMw, ' MW')} highlight />
              <Stat label="SoH" v={fmt(bess.properties.stateOfHealthPct, '%')} />
              <Stat label="Max cell T" v={fmt(bess.properties.maxCellTempC, '°C')}
                    danger={bess.properties.maxCellTempC > 35} />
              <Stat label="V imbalance" v={fmt(bess.properties.cellVoltageImbalancePct, '%')}
                    danger={bess.properties.cellVoltageImbalancePct > 3} />
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
            mapSlot={(r) => <Placeholder label="Map" rid={r} />}
            sldSlot={(r) => <BessSLDPlaceholder rid={r} />}
            threeDSlot={(r) => (
              <Suspense fallback={<div className="px-twin-placeholder">Loading 3D scene…</div>}>
                <TwinScene rid={fullRid} />
              </Suspense>
            )}
            docSlot={(r) => <Placeholder label="Datasheet" rid={r} />}
            defaultTab="3d"
          />
        </section>

        <section className="px-twin-registers">
          <SituationalAwarenessGrid title="Registers · BESS health" tiles={tiles} columns={4} />
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

function buildBessTiles(p) {
  if (!p) {
    return [
      {id:'cell-imbalance', title:'Cell V imbalance', count:0, severity:'low', icon:'⚡'},
      {id:'thermal-warn', title:'Thermal warnings', count:0, severity:'low', icon:'🌡'},
    ];
  }
  return [
    {id:'cell-imbalance', title:'Cell V imbalance', count: p.cellVoltageImbalancePct > 3 ? 1 : 0,
      severity: p.cellVoltageImbalancePct > 3 ? 'high' : 'low', icon:'⚡', trend: 0.04},
    {id:'thermal-warn', title:'Thermal warnings', count: p.maxCellTempC > 35 ? 1 : 0,
      severity: p.maxCellTempC > 35 ? 'high' : 'low', icon:'🌡', trend: 0.0},
    {id:'ground-fault', title:'Ground fault current', count: p.groundFaultCurrentA > 0.1 ? 1 : 0,
      severity: p.groundFaultCurrentA > 0.5 ? 'critical' : 'low', icon:'⏚'},
    {id:'contactor-stuck', title:'Contactor anomalies', count: 0, severity:'low', icon:'🔌'},
    {id:'bms-fault', title:'BMS faults', count: p.bmsState === 'fault' ? 1 : 0,
      severity: p.bmsState === 'fault' ? 'critical' : 'low', icon:'🛡'},
    {id:'capacity-test', title:'Capacity tests due', count: 3, severity:'medium', icon:'🔋'},
    {id:'firmware', title:'Firmware updates', count: 5, severity:'low', icon:'⬆'},
    {id:'work-orders', title:'Open work orders', count: 7, severity:'medium', icon:'🔧', trend:0.15},
    {id:'cycles-today', title:'Cycles today', count: 1.4, severity:'info', icon:'🔄'},
    {id:'soh-decline', title:'SoH decline /yr', count: '0.6%', severity:'info', icon:'📉'},
    {id:'fire-detector', title:'Fire detectors OK', count: p.fireDetectorOk ? '✓' : '✗',
      severity: p.fireDetectorOk ? 'low' : 'critical', icon:'🔥'},
    {id:'gas-detector', title:'H₂ vent ppm', count: 0, severity:'low', icon:'💨'},
    {id:'isolation-locks', title:'LOTO active', count: 0, severity:'info', icon:'🔒'},
    {id:'pcs-thd', title:'PCS THD', count:'2.1%', severity:'info', icon:'🌊'},
    {id:'curtailment', title:'Curtailment events', count: 2, severity:'medium', icon:'✂'},
    {id:'arbitrage', title:'Arbitrage £/MWh', count:'£24', severity:'info', icon:'£'},
  ];
}

function buildBessTrend(p) {
  // Synthetic 60-tick traces seeded by the current SCADA snapshot. Replace
  // with real timeseries from /api/twin/telemetry once wired.
  const soc = p?.stateOfChargePct ?? 50;
  const power = p?.activePowerMw ?? 0;
  const tmax = p?.maxCellTempC ?? 28;
  const f = (i, fn) => Array.from({length: 60}, (_, k) => [k, fn(k, i)]);
  return {
    series: [
      {id: 'soc', label: 'SoC %',  points: f(0, k => soc + Math.sin(k/8)*15)},
      {id: 'p',   label: 'P (MW)', points: f(1, k => power + Math.sin(k/6)*8)},
      {id: 'tmax', label: 'Max cell T °C', points: f(2, k => tmax + Math.cos(k/10)*1.5)},
    ],
    rows: [
      {id:'r-soc', seriesId:'soc', tag:'SoC', value: soc, unit:'%', low:10, high:90, state:'ok'},
      {id:'r-p', seriesId:'p', tag:'P', value: power, unit:'MW', low:-100, high:100, state:'ok'},
      {id:'r-tmax', seriesId:'tmax', tag:'Tmax', value: tmax, unit:'°C', low:10, high:35,
        state: tmax > 35 ? 'alarm' : 'ok'},
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

function BessSLDPlaceholder({rid}) {
  return (
    <div className="px-twin-sld">
      <pre style={{fontFamily:'JetBrains Mono, monospace', fontSize:11, color:'#CBD5E1', margin:0}}>
{`  Grid (132 kV)
   │
   ▼
  ┌─────────────┐
  │ Step-up Tx  │   33 / 0.69 kV, 110 MVA
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │ MV Switch   │   33 kV, AIS
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  PCS bank   │   12 × Power Electronics SDC
  └──────┬──────┘
         ▼ DC bus 1300 V
  ╔═══════════════════════════════════════╗
  ║  Block 1 (50 MW)        Block 2 (50 MW) ║
  ║  ┌─R01 R02 R03 R04┐    ┌─R01 R02 R03 R04┐ ║
  ║  │ R05 R06 R07 R08│    │ R05 R06 R07 R08│ ║
  ║  └─R09 R10 R11 R12┘    └─R09 R10 R11 R12┘ ║
  ╚═══════════════════════════════════════╝
            ${rid}`}
      </pre>
    </div>
  );
}

function fmt(v, unit) {
  if (v == null || Number.isNaN(v)) return '—';
  if (typeof v === 'number') {
    const n = Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1);
    return `${n}${unit ?? ''}`;
  }
  return `${v}${unit ?? ''}`;
}
