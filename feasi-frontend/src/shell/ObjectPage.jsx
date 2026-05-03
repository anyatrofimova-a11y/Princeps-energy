import {useEffect, lazy, Suspense} from 'react';
import {useParams} from 'react-router-dom';
import {useSelection} from '../workshop/useSelection.jsx';
import {useOntologyObject} from '../hooks/queries/index.js';

import {I} from './RegisterIcons.jsx';

const TwinScene = lazy(() => import('../twin-explorer/TwinScene.jsx'));
const SituationalAwarenessGrid = lazy(() => import('../workshop/SituationalAwarenessGrid.jsx').then(m => ({default: m.SituationalAwarenessGrid})));
const TrendChartTableSync = lazy(() => import('../workshop/TrendChartTableSync.jsx').then(m => ({default: m.TrendChartTableSync})));

/**
 * Universal Object Page — every URL `/v2/object/:type/:rid` lands here.
 * Modules are picked by object type. Layout JSON drives ordering in W2;
 * D1 hardcodes the DataCentre + BESSUnit module sets.
 */
export default function ObjectPage() {
  const {type, rid: locator} = useParams();
  const fullRid = locatorToRid(type, locator);
  const {setSelectedAssetRid} = useSelection();
  const {data: obj, isLoading} = useOntologyObject(fullRid);

  useEffect(() => { setSelectedAssetRid(fullRid); }, [fullRid, setSelectedAssetRid]);

  if (isLoading) return <div className="px2-page-loading">loading {type}…</div>;
  if (!obj) return <div className="px2-page-empty">No object at <code>{fullRid}</code>.</div>;

  return (
    <div className="px2-object-page">
      <ObjectHeader obj={obj} type={type} locator={locator} />
      <ModuleStack type={type} obj={obj} fullRid={fullRid} />
    </div>
  );
}


function ObjectHeader({obj, type}) {
  const props = obj.properties ?? {};
  return (
    <header className="px2-object-header">
      <div className="px2-object-id">
        <span className="px2-object-type">{type}</span>
        <h1>{obj.name ?? obj.rid}</h1>
      </div>
      <div className="px2-object-stats">
        {STATS_FOR_TYPE[type]?.(props).map(({label, value, danger, highlight}, i) => (
          <span key={i} className={`px2-stat${danger ? ' is-danger' : ''}${highlight ? ' is-highlight' : ''}`}>
            <span className="px2-stat-label">{label}</span>
            <span className="px2-stat-value">{value}</span>
          </span>
        ))}
      </div>
    </header>
  );
}


function ModuleStack({type, obj, fullRid}) {
  const modules = MODULES_FOR_TYPE[type] ?? MODULES_FOR_TYPE.default;
  return (
    <div className="px2-modules">
      {modules.map(({id, label, render}) => (
        <section key={id} className={`px2-module px2-module-${id}`}>
          <header className="px2-module-head">{label}</header>
          <div className="px2-module-body">
            <Suspense fallback={<div className="px2-module-loading">loading…</div>}>
              {render(obj, fullRid)}
            </Suspense>
          </div>
        </section>
      ))}
    </div>
  );
}


// ───────────────────────── Module registry (D1 hardcoded) ─────────────────────────
//
// W2 will replace this with JSON layout templates per (type × stage).

const MODULES_FOR_TYPE = {
  data_centre: [
    {id: '3d',         label: '3D building',      render: (o, rid) => <TwinScene rid={rid} />},
    {id: 'registers',  label: 'Registers',        render: (o)      => <SituationalAwarenessGrid title={null} tiles={dcRegisters(o.properties)} columns={4} />},
    {id: 'trend',      label: 'Trends · 24 h',    render: (o)      => <TrendChartTableSync rows={dcTrendRows(o.properties)} series={dcTrendSeries(o.properties)} columns={trendCols} />},
  ],
  bess_unit: [
    {id: '3d',        label: '3D plant',         render: (o, rid) => <TwinScene rid={rid} />},
    {id: 'registers', label: 'Registers',        render: (o)      => <SituationalAwarenessGrid title={null} tiles={bessRegisters(o.properties)} columns={4} />},
    {id: 'trend',     label: 'Trends · 24 h',    render: (o)      => <TrendChartTableSync rows={bessTrendRows(o.properties)} series={bessTrendSeries(o.properties)} columns={trendCols} />},
  ],
  default: [
    {id: 'json', label: 'Properties (raw)', render: (o) => <pre className="px2-raw">{JSON.stringify(o.properties, null, 2)}</pre>},
  ],
};


// ───────────────────────── Stats / register builders ─────────────────────────

const STATS_FOR_TYPE = {
  data_centre: (p) => [
    {label: 'Tier', value: p.tier ?? '—'},
    {label: 'IT Load', value: fmt(p.itLoadMw, ' MW')},
    {label: 'Total', value: fmt(p.totalGridDrawMw, ' MW')},
    {label: 'PUE', value: fmt(p.currentPue), highlight: true,
      danger: (p.currentPue ?? 0) > (p.puEDesign ?? 0) + 0.05},
    {label: 'WUE', value: fmt(p.waterUsageM3PerMwh, ' m³/MWh')},
    {label: 'CW supply', value: fmt(p.chilledWaterSupplyTempC, '°C')},
    {label: 'UPS', value: fmt(p.upsBatteryHealthPct, '%'),
      danger: (p.upsBatteryHealthPct ?? 100) < 90},
  ],
  bess_unit: (p) => [
    {label: 'Rated', value: fmt(p.ratedPowerMw, ' MW')},
    {label: 'Capacity', value: fmt(p.energyCapacityMwh, ' MWh')},
    {label: 'Chemistry', value: p.chemistry ?? '—'},
    {label: 'SoC', value: fmt(p.stateOfChargePct, '%'), highlight: true},
    {label: 'P', value: fmt(p.activePowerMw, ' MW'), highlight: true},
    {label: 'SoH', value: fmt(p.stateOfHealthPct, '%')},
    {label: 'Max cell T', value: fmt(p.maxCellTempC, '°C'),
      danger: (p.maxCellTempC ?? 0) > 35},
    {label: 'V imbalance', value: fmt(p.cellVoltageImbalancePct, '%'),
      danger: (p.cellVoltageImbalancePct ?? 0) > 3},
  ],
};

// Short SCADA-style labels — fit in narrow tiles.
function dcRegisters(p = {}) {
  const pueDelta = (p.currentPue ?? 0) - (p.puEDesign ?? 0);
  return [
    {id:'pue-deviation', title:'PUE Δ', count: pueDelta > 0.05 ? '+0.05' : '0.00',
      severity: pueDelta > 0.1 ? 'high' : pueDelta > 0.05 ? 'medium' : 'low', icon: <I.pueDeviation/>},
    {id:'hotspots', title:'Hotspots', count: 1, severity:'medium', icon: <I.hotspots/>},
    {id:'ups-health', title:'UPS <90%', count: (p.upsBatteryHealthPct ?? 100) < 90 ? 1 : 0,
      severity: (p.upsBatteryHealthPct ?? 100) < 80 ? 'high' : 'low', icon: <I.upsHealth/>},
    {id:'genset-test', title:'Genset due', count: (p.gensetTestDueDays ?? 99) < 30 ? 1 : 0,
      severity:'low', icon: <I.gensetTest/>},
    {id:'water-leaks', title:'Water leaks', count: 0, severity:'low', icon: <I.waterLeaks/>},
    {id:'cooling-overrides', title:'Cool override', count: 0, severity:'low', icon: <I.coolingOverride/>},
    {id:'free-cooling', title:'Free cooling', count: 14, unit:'h/d', severity:'info', icon: <I.freeCooling/>},
    {id:'tti', title:'TTI YTD', count: (p.ttiTotalMinutesYtd ?? 0).toFixed(1), unit:'min', severity:'low', icon: <I.tti/>},
    {id:'work-orders', title:'Work orders', count: 12, severity:'medium', icon: <I.workOrders/>},
    {id:'security', title:'Security', count: 0, severity:'low', icon: <I.security/>},
    {id:'bms-overrides', title:'BMS override', count: 2, severity:'medium', icon: <I.bmsOverrides/>},
    {id:'cfe', title:'24/7 CFE', count: 18, unit:'h/d', severity:'info', icon: <I.cfeHours/>},
  ];
}

function bessRegisters(p = {}) {
  return [
    {id:'cell-imbalance', title:'Cell V imb',  count: ((p.cellVoltageImbalancePct ?? 0)).toFixed(1), unit:'%',
      severity: (p.cellVoltageImbalancePct ?? 0) > 3 ? 'high' : 'low', icon: <I.cellImbalance/>},
    {id:'thermal-warn',   title:'Thermal',     count: (p.maxCellTempC ?? 0) > 35 ? 1 : 0, severity:'high', icon: <I.thermalWarn/>},
    {id:'ground-fault',   title:'Gnd fault',   count: (p.groundFaultCurrentA ?? 0) > 0.1 ? 1 : 0, severity:'critical', icon: <I.groundFault/>},
    {id:'bms-fault',      title:'BMS fault',   count: p.bmsState === 'fault' ? 1 : 0, severity:'critical', icon: <I.bmsFault/>},
    {id:'capacity-test',  title:'Cap test',    count: 3, severity:'medium', icon: <I.capacityTest/>},
    {id:'firmware',       title:'Firmware',    count: 5, severity:'low', icon: <I.firmware/>},
    {id:'work-orders',    title:'Work orders', count: 7, severity:'medium', icon: <I.workOrders/>},
    {id:'cycles',         title:'Cycles',      count: 1.4, severity:'info', icon: <I.cycles/>},
    {id:'fire-detector',  title:'Fire det.',   count: p.fireDetectorOk ? 'OK' : 'FAULT',
      severity: p.fireDetectorOk ? 'low' : 'critical', icon: <I.fireDetector/>},
    {id:'isolation-locks',title:'LOTO',        count: 0, severity:'info', icon: <I.isolationLocks/>},
    {id:'curtailment',    title:'Curtail.',    count: 2, severity:'medium', icon: <I.curtailment/>},
    {id:'arbitrage',      title:'Arbitrage',   count: 24, unit:'£/MWh', severity:'info', icon: <I.arbitrage/>},
  ];
}

const trendCols = [
  {key:'tag', label:'Tag'},
  {key:'value', label:'Value', render: r => fmt(r.value, r.unit)},
  {key:'low', label:'Low'},
  {key:'high', label:'High'},
];

function dcTrendSeries(p) {
  const pue = p?.currentPue ?? 1.4;
  const itMw = p?.currentItLoadMw ?? 0;
  const cwT = p?.chilledWaterSupplyTempC ?? 12;
  const f = (fn) => Array.from({length: 60}, (_, k) => [k, fn(k)]);
  return [
    {id: 'pue', label:'PUE',           points: f(k => pue + Math.sin(k/9)*0.04)},
    {id: 'it',  label:'IT (MW)',       points: f(k => itMw + Math.sin(k/7)*1.5)},
    {id: 'cwt', label:'CW supply (°C)', points: f(k => cwT + Math.cos(k/12)*0.8)},
  ];
}
function dcTrendRows(p) {
  const pueDes = p?.puEDesign ?? 1.3;
  return [
    {id:'r-pue', seriesId:'pue', tag:'PUE',       value: p?.currentPue ?? 0, unit:'',
      low: round2(pueDes), high: round2(pueDes + 0.1)},
    {id:'r-it',  seriesId:'it',  tag:'IT Load',   value: p?.currentItLoadMw ?? 0, unit:'MW',
      low: 0, high: p?.itLoadMw ?? 50},
    {id:'r-cwt', seriesId:'cwt', tag:'CW Supply', value: p?.chilledWaterSupplyTempC ?? 0, unit:'°C',
      low: 10, high: 14},
  ];
}

function round2(x) { return Math.round(x * 100) / 100; }

function bessTrendSeries(p) {
  const soc = p?.stateOfChargePct ?? 50, pw = p?.activePowerMw ?? 0, t = p?.maxCellTempC ?? 28;
  const f = (fn) => Array.from({length: 60}, (_, k) => [k, fn(k)]);
  return [
    {id: 'soc',  label:'SoC %',        points: f(k => soc + Math.sin(k/8)*15)},
    {id: 'p',    label:'P (MW)',       points: f(k => pw + Math.sin(k/6)*8)},
    {id: 'tmax', label:'Max T °C',     points: f(k => t + Math.cos(k/10)*1.5)},
  ];
}
function bessTrendRows(p) {
  return [
    {id:'r-soc',  seriesId:'soc',  tag:'SoC',  value: p?.stateOfChargePct ?? 0, unit:'%',  low: 10, high: 90},
    {id:'r-p',    seriesId:'p',    tag:'P',    value: p?.activePowerMw ?? 0, unit:'MW', low: -100, high: 100},
    {id:'r-tmax', seriesId:'tmax', tag:'Tmax', value: p?.maxCellTempC ?? 0, unit:'°C', low: 10, high: 35},
  ];
}


function locatorToRid(type, locator) {
  return `rid.princeps.production.${type}.${locator}`;
}

function fmt(v, unit) {
  if (v == null || Number.isNaN(v)) return '—';
  if (typeof v === 'number') {
    const n = Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2);
    return `${n}${unit ?? ''}`;
  }
  return `${v}${unit ?? ''}`;
}
