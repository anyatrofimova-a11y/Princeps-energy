/**
 * Fixture data for the /workshop demo route.
 *
 * Pattern: every fixture mimics the shape the production endpoint will
 * return so swapping the demo to a real /api/... call is a one-line
 * change at the call site.
 */

export const ASSET_TREE = [
  {
    rid: 'rid.princeps.demo.site.midlands-solar-150',
    name: 'Midlands Solar 150 MW',
    badges: {red: 1, yellow: 3, blue: 0, green: 12},
    children: [
      {
        rid: 'rid.princeps.demo.solar_farm.midlands-150-array-a',
        name: 'Array A (75 MW DC)',
        badges: {red: 1, yellow: 1, blue: 0, green: 4},
        children: [
          {rid: 'rid.princeps.demo.inverter.midlands-150-INV01', name: 'INV-01', badges: {red: 1, yellow: 0, blue: 0, green: 0}},
          {rid: 'rid.princeps.demo.inverter.midlands-150-INV02', name: 'INV-02', badges: {red: 0, yellow: 1, blue: 0, green: 1}},
        ],
      },
      {
        rid: 'rid.princeps.demo.solar_farm.midlands-150-array-b',
        name: 'Array B (75 MW DC)',
        badges: {red: 0, yellow: 2, blue: 0, green: 8},
      },
    ],
  },
  {
    rid: 'rid.princeps.demo.site.essex-bess-100',
    name: 'Essex BESS 100 MW / 200 MWh',
    badges: {red: 0, yellow: 0, blue: 2, green: 14},
    children: [
      {rid: 'rid.princeps.demo.bess_unit.essex-100', name: 'BESS Block 1', badges: {red: 0, yellow: 0, blue: 1, green: 7}},
      {rid: 'rid.princeps.demo.bess_unit.essex-100b', name: 'BESS Block 2', badges: {red: 0, yellow: 0, blue: 1, green: 7}},
    ],
  },
];

export const REGISTER_TILES = [
  {id: 'safeguarding', title: 'Safeguarding overrides', count: 1, severity: 'high', icon: '⚠', trend: 0},
  {id: 'alarm-overrides', title: 'Alarm overrides', count: 0, severity: 'low', icon: '🔔', trend: -0.2},
  {id: 'critical-alarms', title: 'Critical alarms', count: 0, severity: 'low', icon: '🛑', trend: 0},
  {id: 'design-exceedences', title: 'Design exceedences', count: 0, severity: 'low', icon: '📐', trend: 0},
  {id: 'iow-exceedences', title: 'IOW exceedences', count: 0, severity: 'low', icon: '↔', trend: 0},
  {id: 'standard-alarms', title: 'Standard alarms', count: 0, severity: 'low', icon: '🔔', trend: 0},
  {id: 'target-alarms', title: 'Target alarms', count: 0, severity: 'low', icon: '🎯', trend: 0},
  {id: 'ptm-alarms', title: 'PTM alarms', count: 15, severity: 'medium', icon: '📈', trend: 0.12},
  {id: 'process-targets', title: 'Process targets', count: 0, severity: 'low', icon: '◎', trend: 0},
  {id: 'leaks', title: 'Leaks', count: 26, severity: 'high', icon: '💧', trend: 0.08},
  {id: 'temporary-hoses', title: 'Temporary hoses', count: 15, severity: 'medium', icon: '〜', trend: 0},
  {id: 'lock-open-closed', title: 'Lock open/closed', count: 7, severity: 'medium', icon: '🔒', trend: 0},
  {id: 'passing-valves', title: 'Passing valves', count: 12, severity: 'medium', icon: '◐', trend: 0.04},
  {id: 'temporary-equipment', title: 'Temporary equipment', count: 11, severity: 'medium', icon: '🔧', trend: 0},
  {id: 'open-bypass-valves', title: 'Open bypass valves', count: 9, severity: 'medium', icon: '⤥', trend: 0},
  {id: 'sap-z1-notifications', title: 'SAP Z1 notifications', count: 0, severity: 'low', icon: '📋', trend: 0},
];

export const TOOL_CALL_EVENTS = [
  {type: 'message', role: 'user', content: 'Show me the trend of the suction temperature for the 2nd stage compressor on April 18.'},
  {type: 'thinking', content: 'querying the BMRS-equivalent process historian for tag 24-PA001:SuctionT'},
  {type: 'tool_call', id: 'c1', tool: 'BMRS Fetcher', args: {tag: '24-PA001:SuctionT', from: '2024-04-18', to: '2024-04-19'}, status: 'pending'},
  {type: 'tool_result', toolCallId: 'c1', result: {points: [['10:30', 36.55], ['10:00', 36.54], ['09:30', 36.60], ['09:00', 36.57]]}},
  {type: 'message', role: 'assistant', content: 'Suction temperature ranged 35.3 – 36.6 °C across the day. The valve dropped below limit at 22:05 — recommend (1) validate transmitter, (2) check for heating-source loss, (3) cross-check against the K-1131 booster compressor incident from Reference ID 117377.'},
  {type: 'tool_call', id: 'c2', tool: 'REPD Search', args: {q: 'similar incident booster compressor 2023'}, status: 'pending'},
  {type: 'tool_result', toolCallId: 'c2', result: {hits: 1, top: 'Ref 117377 — K-1131 Booster Compressor, suction valve temp dropped below alarm limit'}},
];

export const RISK_DATASETS = [{id: 'fsr_deviations', label: 'FSR Deviations'}];
export const RISK_TREE = [
  {
    rid: 'rid.princeps.demo.site.midlands-solar-150',
    name: 'HUL',
    badges: {red: 2, yellow: 5, blue: 1, green: 3},
    children: [
      {rid: 'inspection', name: 'Inspection', badges: {red: 1, yellow: 2, blue: 0, green: 1}},
      {rid: 'instrumentation', name: 'Instrumentation', badges: {red: 0, yellow: 2, blue: 1, green: 1}},
      {rid: 'mechanical', name: 'Mechanical', badges: {red: 1, yellow: 1, blue: 0, green: 1}},
    ],
  },
];
export const RISK_ROWS = [
  {id: '20657F', source: 'deferral', risk: 'red', title: 'avut', status: 'DRAFT', fromDate: '2025-09-01 15:09', moc: '304884', tags: '64-2997TC', owner: 'VAMOS'},
  {id: '281677', source: 'deferral', risk: 'red', title: 'Piping class selection', status: 'CLOSED', fromDate: '2025-02-19 11:14', moc: '476547', tags: '40-77200A', owner: 'VAMOS'},
  {id: '699429', source: 'deferral', risk: 'red', title: 'mollit consectetur deserunt non', status: 'APPROVED', fromDate: '2025-06-15 15:09', moc: '177764', tags: '20-2000VT', owner: 'VAMOS'},
  {id: '746846', source: 'deferral', risk: 'yellow', title: 'aliqua', status: 'WITHDRAWN', fromDate: '2025-06-22 19:03', moc: '800679', tags: '20-VA50', owner: 'VAMOS'},
  {id: '850175', source: 'deferral', risk: 'blue', title: 'aliqua', status: 'DRAFT', fromDate: '2025-06-22 15:09', moc: '551767', tags: '42-2027CC', owner: 'VAMOS'},
];

export const SHIFT = {
  shift: {operator: 'Anya Trofimova', role: 'Field Operator', startsAt: '2024-08-16T02:00:00Z', endsAt: '2024-08-16T14:00:00Z'},
  rounds: [{id: 'r1', time: '2024-08-16T03:30:00Z', location: 'Array A inverter row', status: 'pending'}],
  handovers: [
    {id: 'h1', time: '2024-08-16T02:00:00Z', role: 'Field Operator', with: 'night shift'},
    {id: 'h2', time: '2024-08-16T14:00:00Z', role: 'Field Operator', with: 'day shift'},
  ],
  mitigations: [{id: 'm1', label: 'Manual valve open while controller in maintenance', status: 'active'}],
  instructions: [{id: 'i1', label: 'Avoid INV-01 export ramp until firmware patch lands', urgency: 'high'}],
  comments: [
    {id: 'c1', author: 'Endre Nisja', postedAt: '2024-08-16T12:31:00Z', severity: 'warn', content: 'Wind 24 m/s, expected to increase until 18:00.', pinned: true},
    {id: 'c2', author: 'Endre Nisja', postedAt: '2024-08-16T12:30:00Z', severity: 'info', content: 'Low pressure compressor out for maintenance.'},
  ],
};

export const PNID_TAGS = [
  {id: '24-PI2159', x: 32, y: 38, value: 0.10, unit: 'bar', alarmState: 'ok', label: '24-PA001 BARRIER FLUID PRESSURE'},
  {id: '24-FT2000', x: 18, y: 52, value: 14.54, unit: 'm³/h', alarmState: 'warn', label: '20-PA001 FLOW'},
  {id: '24-PT2018', x: 64, y: 30, value: 17.32, unit: 'bara', alarmState: 'ok'},
  {id: '24-LT2005', x: 75, y: 60, value: 1.00, unit: 'm', alarmState: 'alarm'},
];

export const PTM_TAGS = [
  {id: '20FT2000:MeasuredValue', description: 'Flow', unit: 'm³/h', value: 17.152, low: 50, high: 80, state: 'alarm', last24hPct: 0, document: 'C025-V-HB20-P-_E-001-01', system: 'Operations', equipment: '20-PA001'},
  {id: '20PT2019:MeasuredValue', description: 'Pressure', unit: 'bara', value: 14.684, low: 10, high: 50, state: 'ok', last24hPct: 0, document: 'C025-W-H020-P-_E-001-01', system: 'Operations', equipment: '20-PA001'},
  {id: '20TT2010:MeasuredValue', description: 'Temperature', unit: '°C', value: 55.238, low: 50, high: 70, state: 'ok', last24hPct: 0, document: 'C025-W-H020-P-_E-001-01', system: 'Operations', equipment: '20-PA001'},
  {id: '20-PA001_m:MachineONstatus', description: 'Machine on/off', unit: '-', value: 1, low: 0.5, high: null, state: 'ok', last24hPct: 0, system: 'Operations', equipment: '20-PA001'},
  {id: '20FT2000:MeasuredValue', description: 'Flow (HH)', unit: 'm³/h', value: 17.152, low: 29, high: null, state: 'alarm', last24hPct: 0, document: 'C025-V-HB20-P-_E-001-01', system: 'Reliability', equipment: '20-PA001'},
];

export const TREND_SERIES = [
  {id: 's1', label: '20PT2016 Pressure', points: Array.from({length: 60}, (_, i) => [i, 25 + Math.sin(i / 6) * 4 + (i % 9 === 0 ? 2 : 0)])},
  {id: 's2', label: '20FT2000 Flow', points: Array.from({length: 60}, (_, i) => [i, 90 + Math.cos(i / 5) * 6])},
  {id: 's3', label: '20TT2010 Temperature', points: Array.from({length: 60}, (_, i) => [i, 56 + Math.sin(i / 8) * 3])},
];

export const TREND_ROWS = [
  {id: 't1', seriesId: 's1', tag: '20PT2016', value: 26.55, unit: 'bara', low: 25, high: 30, state: 'ok'},
  {id: 't2', seriesId: 's2', tag: '20FT2000', value: 92.02, unit: 'm³/h', low: 40, high: 75, state: 'alarm'},
  {id: 't3', seriesId: 's3', tag: '20TT2010', value: 57.68, unit: '°C', low: 42, high: 56, state: 'alarm'},
];

export const TREND_COLUMNS = [
  {key: 'tag', label: 'Tag'},
  {key: 'value', label: 'Value', render: (r) => r.value?.toFixed(2)},
  {key: 'unit', label: 'Unit'},
  {key: 'low', label: 'Low'},
  {key: 'high', label: 'High'},
  {key: 'state', label: 'State', render: (r) => <span className={`px-state-dot px-state-${r.state}`} aria-label={r.state} />},
];

export const WORK_ORDERS = [
  {id: 'wo1', position: [-0.45, 52.78], count: 8, severity: 'alarm', label: 'Array A inverter row'},
  {id: 'wo2', position: [-0.41, 52.79], count: 3, severity: 'warn', label: 'DC combiner box C-3'},
  {id: 'wo3', position: [-0.49, 52.77], count: 1, severity: 'ok', label: 'Met station'},
  {id: 'wo4', position: [0.62, 51.78], count: 12, severity: 'warn', label: 'Essex BESS Block 1'},
];

export const PTM_CONFIGURATIONS = [
  {id: 'operations', label: 'Operations'},
  {id: 'reliability', label: 'Reliability'},
  {id: 'all-pumps', label: 'All pumps'},
  {id: 'hh-ll', label: 'HH and LL'},
  {id: 'h-l', label: 'H and L'},
];

export const SAVED_VIEWS = [
  {id: 'sv1', label: 'FT2000-2 limits'},
  {id: 'sv2', label: 'Pump bank — daytime'},
];

export const TRIGGER_TAG_OPTIONS = ['20FT2000:MeasuredValue', '20PT2018:MeasuredValue', '20TT2010:MeasuredValue', '20-PA001_m:MachineONstatus'];

export const TRIGGER_PARENT_GROUPS = ['Operations', 'Reliability', 'NewDiscipline', 'Industrial Work Services - Filter'];
