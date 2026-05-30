import {useState} from 'react';
import {SelectionProvider, useSelection} from './useSelection.jsx';
import {AssetHierarchyTree} from './AssetHierarchyTree.jsx';
import {SituationalAwarenessGrid} from './SituationalAwarenessGrid.jsx';
import {AssetWorkspace} from './AssetWorkspace.jsx';
import {ToolCallStream} from './ToolCallStream.jsx';
import {PnidOverlay} from './PnidOverlay.jsx';
import {TriggerBuilder} from './TriggerBuilder.jsx';
import {ShiftHandover} from './ShiftHandover.jsx';
import {RiskVisualization} from './RiskVisualization.jsx';
import {PtmConfigurator} from './PtmConfigurator.jsx';
import {TrendChartTableSync} from './TrendChartTableSync.jsx';
import {
  ASSET_TREE, REGISTER_TILES, TOOL_CALL_EVENTS,
  RISK_DATASETS, RISK_TREE, RISK_ROWS,
  SHIFT, PNID_TAGS, PTM_TAGS, PTM_CONFIGURATIONS, SAVED_VIEWS,
  TREND_SERIES, TREND_ROWS, TREND_COLUMNS,
  TRIGGER_TAG_OPTIONS, TRIGGER_PARENT_GROUPS,
} from './fixtures.jsx';

/**
 * Demo route at /workshop. Mounts every Swarm-10 component against
 * fixture data so the patterns can be seen end-to-end without backend
 * wiring. When real /api/registers/... endpoints land, swap the
 * `fixtures.js` imports for fetch calls — same shapes.
 */
export default function WorkshopDemo() {
  return (
    <SelectionProvider>
      <div className="px-workshop-page">
        <header className="px-workshop-header">
          <h1>Princeps Workshop · Operations Cockpit</h1>
          <p>Kognitwin-pattern demo · onshore UK · fixtures only</p>
          <PaneTabs />
        </header>
      </div>
    </SelectionProvider>
  );
}

const PANES = [
  {id: 'cockpit', label: 'Situational Awareness'},
  {id: 'risk',    label: 'Risk Visualization'},
  {id: 'ptm',     label: 'PTM Configurator'},
  {id: 'trigger', label: 'Configure Trigger'},
  {id: 'shift',   label: 'Shift Handover'},
  {id: 'pnid',    label: 'P&ID Overlay'},
  {id: 'trend',   label: 'Trend ↔ Table'},
  {id: 'agent',   label: 'AI Assistant'},
];

function PaneTabs() {
  const [active, setActive] = useState('cockpit');
  return (
    <>
      <nav className="px-workshop-tabs" role="tablist">
        {PANES.map((p) => (
          <button
            key={p.id}
            role="tab"
            aria-selected={active === p.id}
            className={`px-workshop-tab${active === p.id ? ' is-active' : ''}`}
            onClick={() => setActive(p.id)}
          >{p.label}</button>
        ))}
      </nav>
      <main className="px-workshop-main" role="tabpanel">
        {active === 'cockpit' && <CockpitPane />}
        {active === 'risk' && <RiskPane />}
        {active === 'ptm' && <PtmPane />}
        {active === 'trigger' && <TriggerPane />}
        {active === 'shift' && <ShiftPane />}
        {active === 'pnid' && <PnidPane />}
        {active === 'trend' && <TrendPane />}
        {active === 'agent' && <AgentPane />}
      </main>
    </>
  );
}

function CockpitPane() {
  return (
    <div className="px-cockpit-pane">
      <aside className="px-cockpit-tree">
        <h3>Asset hierarchy</h3>
        <AssetHierarchyTree nodes={ASSET_TREE} />
      </aside>
      <section className="px-cockpit-grid">
        <SituationalAwarenessGrid title="Situational Awareness Cockpit · Registers" tiles={REGISTER_TILES} />
      </section>
      <aside className="px-cockpit-workspace">
        <AssetWorkspace
          mapSlot={(rid) => <PlaceholderView label="Map" rid={rid} />}
          sldSlot={(rid) => <PlaceholderView label="Single-line" rid={rid} />}
          threeDSlot={(rid) => <PlaceholderView label="3D" rid={rid} />}
          docSlot={(rid) => <PlaceholderView label="Document" rid={rid} />}
        />
      </aside>
    </div>
  );
}

function RiskPane() {
  return (
    <RiskVisualization
      datasets={RISK_DATASETS}
      getTreeForDataset={() => RISK_TREE}
      getRowsForDataset={() => RISK_ROWS}
      threeDSlot={(_d, rid) => <PlaceholderView label="3D · Risk markers" rid={rid} />}
    />
  );
}

function PtmPane() {
  return (
    <PtmConfigurator
      configurations={PTM_CONFIGURATIONS}
      savedViews={SAVED_VIEWS}
      tags={PTM_TAGS}
      onApplySavedView={(id) => console.log('apply saved view', id)}
      onSaveCurrentView={(name, view) => console.log('save', name, view)}
    />
  );
}

function TriggerPane() {
  return (
    <div className="px-trigger-pane">
      <TriggerBuilder
        tagOptions={TRIGGER_TAG_OPTIONS}
        parentGroups={TRIGGER_PARENT_GROUPS}
        onSubmit={(t) => console.log('submit trigger', t)}
        onCancel={() => console.log('cancel')}
      />
    </div>
  );
}

function ShiftPane() {
  return <ShiftHandover {...SHIFT} onAddComment={(t) => console.log('comment', t)} />;
}

function PnidPane() {
  return (
    <div className="px-pnid-pane">
      <p style={{padding: 12, color: '#64748b'}}>
        Replace the <code>svgUrl</code> with a real P&amp;ID drawing path.
        Tag bubbles render at each tag's percent coordinate within the SVG.
      </p>
      <PnidOverlay
        svgUrl="/static/sample-pnid.svg"
        tags={PNID_TAGS}
        coordinateMode="percent"
        onTagClick={(id) => console.log('tag click', id)}
      />
    </div>
  );
}

function TrendPane() {
  return <TrendChartTableSync rows={TREND_ROWS} series={TREND_SERIES} columns={TREND_COLUMNS} />;
}

function AgentPane() {
  return (
    <div className="px-agent-pane">
      <ToolCallStream events={TOOL_CALL_EVENTS} />
    </div>
  );
}

function PlaceholderView({label, rid}) {
  return (
    <div style={{padding: 24, color: '#64748b', fontSize: 13}}>
      {label} view for <code>{rid ?? '—'}</code>. Wire the real component here.
    </div>
  );
}
