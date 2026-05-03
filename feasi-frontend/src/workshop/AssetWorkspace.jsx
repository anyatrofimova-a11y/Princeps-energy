import {useState} from 'react';
import {useSelection} from './useSelection.jsx';

/**
 * Kognitwin-pattern asset workspace — one asset, four toggleable views:
 *   • Map        (geospatial context — Mapbox/Cesium snippet)
 *   • Single-line (electrical SLD or P&ID drawing)
 *   • 3D         (deck.gl twin / IFC viewer / Cesium 3D-Tiles)
 *   • Document   (planning docs, DNO offers, datasheets)
 *
 * Each view is passed in as a slot (function of selected RID). The workspace
 * doesn't know what's inside; it owns the tab state, the empty state when
 * no asset is selected, and reads the global selection context so any
 * upstream tree/table/3D click drives the same view.
 */
export function AssetWorkspace({mapSlot, sldSlot, threeDSlot, docSlot, defaultTab = 'map'}) {
  const {selectedAssetRid} = useSelection();
  const [active, setActive] = useState(defaultTab);

  const tabs = [
    {id: 'map', label: 'Map', slot: mapSlot},
    {id: 'sld', label: 'Single-line', slot: sldSlot},
    {id: '3d', label: '3D', slot: threeDSlot},
    {id: 'doc', label: 'Document', slot: docSlot},
  ].filter((t) => Boolean(t.slot));

  const activeTab = tabs.find((t) => t.id === active) ?? tabs[0];

  if (!selectedAssetRid) {
    return (
      <div className="px-asset-workspace px-asset-workspace-empty">
        <p>Select an asset to inspect.</p>
      </div>
    );
  }

  return (
    <div className="px-asset-workspace">
      <header className="px-asset-tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={active === t.id}
            className={`px-asset-tab${active === t.id ? ' is-active' : ''}`}
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
        <span className="px-asset-rid" title={selectedAssetRid}>
          {shortRid(selectedAssetRid)}
        </span>
      </header>
      <div className="px-asset-view" role="tabpanel">
        {activeTab ? activeTab.slot(selectedAssetRid) : null}
      </div>
    </div>
  );
}

function shortRid(rid) {
  // rid.princeps.production.substation.7e1c4a3a... → substation:7e1c4a3a
  if (!rid) return '';
  const parts = rid.split('.');
  if (parts.length < 5) return rid;
  const type = parts[3];
  const locator = parts.slice(4).join('.');
  return `${type}:${locator.slice(0, 8)}`;
}
