import {Outlet} from 'react-router-dom';
import {SelectionProvider} from './useSelection.jsx';
import {CollapsibleDrawer} from './CollapsibleDrawer.jsx';
import {OntologyTree} from './OntologyTree.jsx';
import {ObjectInspector} from './ObjectInspector.jsx';
import './shell.css';

/**
 * Workshop chrome — Foundry-style overlay drawers wrapping every app
 * route (defined as a layout route in main.jsx).
 *
 * Left drawer  : ontology tree (collapsed by default)
 * Right drawer : ObjectInspector for selectedAssetRid (expanded by default
 *                so users see context the moment they click anything)
 *
 * No grid / no displacement — drawers are position:fixed overlays so
 * existing absolute-positioned panels in LegacyApp / canvas / design
 * keep working unchanged.
 */
export function WorkshopShell() {
  return (
    <SelectionProvider>
      <div className="px-shell-mount">
        <CollapsibleDrawer side="left" title="Ontology" icon="≡" defaultExpanded={false}>
          <OntologyTree />
        </CollapsibleDrawer>

        <Outlet />

        <CollapsibleDrawer side="right" title="Inspector" icon="◧" defaultExpanded>
          <ObjectInspector
            slots={['summary', 'properties', 'relationships', 'actions']}
            actions={DEFAULT_ACTIONS}
          />
        </CollapsibleDrawer>
      </div>
    </SelectionProvider>
  );
}

// Default action shelf — surfaced at the bottom of every ObjectInspector.
// Add more by appending here once new ActionTypes register.
const DEFAULT_ACTIONS = [
  {actionId: 'run_feasibility', label: 'Run feasibility',
   paramsForRid: (rid) => ({site_rid: rid, scenario: 'base'}),
   previewFirst: true, icon: '▶'},
  {actionId: 'screen_counterparty', label: 'Screen sanctions',
   paramsForRid: (rid) => ({legal_name: rid.split('.').pop()}),
   icon: '⚖'},
];
