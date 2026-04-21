/**
 * Princeps 3D Twin — AssetSpecDrawer
 * ----------------------------------------------------------------------
 * 420-px right drawer that slides in when `selectedAssetId !== null`.
 * Four tabs: Spec / Cost / Install / Compliance.
 *
 * Data source: `registry.js` sibling file (sibling agent will ship it).
 * Registry shape expected:
 *   export const REGISTRY = {
 *     megapack_2xl: { name, spec, cost, install, compliance, ... }, ...
 *   };
 *   export function lookupAsset(assetId) -> { type, meta }
 * We fail gracefully if registry is absent — the drawer still renders
 * with a minimal fallback card containing just the asset id.
 *
 * Footer actions emit window CustomEvents the app shell/renderer
 * listens to: `princeps:twin:respec`, `princeps:twin:clone`,
 * `princeps:twin:delete`.
 */

import React, { useMemo, useState, useEffect } from 'react';
import { useTwinStore } from './stores/twinStore';

// Registry import — sibling agent owns `./assets/registry.js`.
// We try to load it lazily so this file keeps building when the module
// is absent or temporarily broken.
let getAssetDefFn = null;
let registryLoaded = false;

async function loadRegistry() {
  if (registryLoaded) return;
  try {
    const mod = await import('./assets/registry.js');
    getAssetDefFn = mod.getAssetDef || null;
  } catch (err) {
    // Registry not yet available — fall back to FALLBACK map.
  } finally {
    registryLoaded = true;
  }
}

// Asset metadata that enriches the registry entry (cost / install / compliance).
// Sibling agent ships structural dims in registry.js; we overlay commercial
// + delivery metadata here keyed by registry id. Add more entries as the
// bid-of-materials library grows.
const ASSET_META = {
  'bess.tesla_megapack_2xl': {
    name: 'Tesla Megapack 2XL',
    type: 'BESS container',
    spec: {
      dimensions: '7.25 \u00D7 1.69 \u00D7 2.57 m',
      energy: '3.9 MWh',
      weight: '28 t',
      summary:
        'Tesla Megapack 2XL \u00B7 7.25 \u00D7 1.69 \u00D7 2.57 m \u00B7 3.9 MWh \u00B7 28 t. Standards: BS 8629:2019, NFPA 855.',
    },
    cost: {
      unit: '\u00A31.2M/container',
      per_kwh: '\u00A3310/kWh',
      source: 'Modo Mar 2026 range \u00A3280\u2013370',
      summary: '\u00A31.2M/container \u00B7 \u00A3310/kWh (Modo Mar 2026 range \u00A3280\u2013370)',
    },
    install: {
      lead_time: '52 weeks',
      trade: 'HV contractor',
      critical_path: true,
      summary: 'Lead time 52 weeks \u00B7 Trade: HV contractor \u00B7 Critical-path: yes',
    },
    compliance: {
      items: [
        'G99 Annex C',
        'DSEAR zoning required',
        'CDM notification needed',
        '8 m firebreak per BS 8629',
      ],
      summary:
        'G99 Annex C \u00B7 DSEAR zoning required \u00B7 CDM notification needed \u00B7 8 m firebreak per BS 8629',
    },
  },
  'bess.fluence_gridstack': {
    name: 'Fluence Gridstack',
    type: 'BESS container (20 ft)',
    cost: { summary: '20 ft container \u00B7 0.72 MWh / 0.36 MW unit' },
    install: { summary: 'Lead time 34 weeks \u00B7 Trade: HV contractor' },
  },
  'bess.wartsila_quantum': {
    name: 'W\u00E4rtsil\u00E4 Quantum',
    type: 'BESS container',
    cost: { summary: '5.3 MWh / 2.65 MW per unit' },
  },
  'bess.pcs_skid': {
    name: 'PCS skid 2.5 MW',
    type: 'Power conversion',
  },
  'bess.aux_tx': { name: 'Auxiliary transformer', type: 'Transformer' },
  'solar.pv_table_4h': { name: 'PV table (4-high)', type: 'Fixed-tilt table' },
  'solar.central_inverter_3mva': {
    name: 'Central inverter 3 MVA',
    type: 'Inverter',
  },
  'solar.pad_tx': { name: 'Pad-mount transformer', type: 'Transformer' },
  'dc.it_hall_shell': { name: 'IT hall shell', type: 'Data centre shell' },
  'dc.crac': { name: 'CRAC unit', type: 'Cooling' },
  'dc.genset_3mw': { name: 'Backup genset 3 MW', type: 'Standby generator' },
  'dc.ups_room': { name: 'UPS room', type: 'UPS / power' },
};

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';
const SURFACE = '#FFFFFF';
const DANGER = '#B91C1C';

const TABS = [
  { id: 'spec', label: 'Spec' },
  { id: 'cost', label: 'Cost' },
  { id: 'install', label: 'Install' },
  { id: 'compliance', label: 'Compliance' },
];

// Per-asset id resolver. Accepts either a raw registry id (e.g.
// 'bess.tesla_megapack_2xl') or an instance id whose `assetDefId` is
// encoded as a prefix (e.g. 'bess.tesla_megapack_2xl#7'). Callers that
// pass full instance objects should set `selectedAssetId` to the
// instance's defId so this resolver can look up the template.
function resolveDefId(assetId) {
  if (!assetId) return null;
  const raw = String(assetId);
  // strip instance index suffix if present
  const hashIdx = raw.indexOf('#');
  return hashIdx > 0 ? raw.slice(0, hashIdx) : raw;
}

function deriveAssetRecord(assetId) {
  const defId = resolveDefId(assetId);
  if (!defId) return null;

  let def = null;
  if (getAssetDefFn) {
    try { def = getAssetDefFn(defId); } catch {}
  }
  const meta = ASSET_META[defId] || {};

  // If neither side yields anything, return null so EmptyState renders.
  if (!def && !meta.name) return null;

  // Fold the registry definition into the shape the drawer expects.
  const dims = def?.dims || null;
  const standards = def?.standards || [];
  const specFromDef = dims
    ? {
        dimensions: `${dims.l} \u00D7 ${dims.w} \u00D7 ${dims.h} m`,
        standards,
      }
    : { standards };

  const merged = {
    name: meta.name || def?.id || defId,
    type: meta.type || def?.type || null,
    spec: {
      ...specFromDef,
      ...(meta.spec || {}),
    },
    cost: meta.cost || null,
    install: meta.install || null,
    compliance: meta.compliance || (standards.length
      ? { items: standards, summary: `Standards: ${standards.join(', ')}` }
      : null),
  };
  return merged;
}

export default function AssetSpecDrawer() {
  const selectedAssetId = useTwinStore((s) => s.selectedAssetId);
  const clearSelection = useTwinStore((s) => s.clearSelection);
  const [tab, setTab] = useState('spec');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    loadRegistry().finally(() => setReady(true));
  }, []);

  // Reset to spec tab each time a new asset is selected
  useEffect(() => {
    setTab('spec');
  }, [selectedAssetId]);

  const record = useMemo(
    () => (ready ? deriveAssetRecord(selectedAssetId) : null),
    [ready, selectedAssetId]
  );

  const open = selectedAssetId !== null && selectedAssetId !== undefined;

  const act = (name) => {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent(name, { detail: { assetId: selectedAssetId } })
      );
    }
  };

  return (
    <aside
      aria-hidden={!open}
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: 420,
        background: IVORY,
        borderLeft: `1px solid ${BORDER}`,
        boxShadow: open ? '-8px 0 24px rgba(15, 19, 24, 0.10)' : 'none',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 220ms ease',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 30,
        fontFamily: "'DM Sans', system-ui, sans-serif",
        color: INK,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '16px 20px 12px',
          borderBottom: `1px solid ${BORDER}`,
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 10, color: MUTED, letterSpacing: 1, textTransform: 'uppercase' }}>
            {record?.type || 'Asset'}
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 2, lineHeight: 1.25 }}>
            {record?.name || selectedAssetId || '\u2014'}
          </div>
          <div
            style={{
              fontSize: 10,
              color: MUTED,
              marginTop: 4,
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            }}
          >
            {selectedAssetId || '\u2014'}
          </div>
        </div>
        <button
          aria-label="Close"
          onClick={clearSelection}
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            color: INK,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <IconClose />
        </button>
      </div>

      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Asset detail tabs"
        style={{
          display: 'flex',
          padding: '0 20px',
          borderBottom: `1px solid ${BORDER}`,
          background: IVORY,
        }}
      >
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              style={{
                appearance: 'none',
                border: 'none',
                background: 'transparent',
                padding: '10px 14px',
                fontSize: 12,
                fontWeight: active ? 600 : 500,
                color: active ? INK : MUTED,
                cursor: 'pointer',
                position: 'relative',
                marginRight: 4,
              }}
            >
              {t.label}
              {active && (
                <span
                  style={{
                    position: 'absolute',
                    left: 12,
                    right: 12,
                    bottom: -1,
                    height: 2,
                    background: GOLD,
                    borderRadius: 2,
                  }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
        {!open ? null : !record ? (
          <EmptyState id={selectedAssetId} />
        ) : (
          <TabBody tab={tab} record={record} />
        )}
      </div>

      {/* Footer actions */}
      <div
        style={{
          padding: 16,
          borderTop: `1px solid ${BORDER}`,
          display: 'flex',
          gap: 8,
          background: IVORY,
        }}
      >
        <FooterButton primary onClick={() => act('princeps:twin:respec')}>
          Re-spec
        </FooterButton>
        <FooterButton onClick={() => act('princeps:twin:clone')}>Clone</FooterButton>
        <FooterButton danger onClick={() => act('princeps:twin:delete')}>
          Delete
        </FooterButton>
      </div>
    </aside>
  );
}

function TabBody({ tab, record }) {
  if (tab === 'spec') return <SpecTab data={record.spec} />;
  if (tab === 'cost') return <CostTab data={record.cost} />;
  if (tab === 'install') return <InstallTab data={record.install} />;
  if (tab === 'compliance') return <ComplianceTab data={record.compliance} />;
  return null;
}

function SpecTab({ data }) {
  if (!data) return <EmptyTab />;
  return (
    <Section>
      {data.summary && <Summary>{data.summary}</Summary>}
      <KV k="Dimensions" v={data.dimensions} mono />
      <KV k="Energy" v={data.energy} mono />
      <KV k="Weight" v={data.weight} mono />
      {data.standards && (
        <KV k="Standards" v={Array.isArray(data.standards) ? data.standards.join(', ') : data.standards} />
      )}
    </Section>
  );
}

function CostTab({ data }) {
  if (!data) return <EmptyTab />;
  return (
    <Section>
      {data.summary && <Summary>{data.summary}</Summary>}
      <KV k="Unit cost" v={data.unit} mono />
      <KV k="Per-kWh" v={data.per_kwh} mono />
      <KV k="Source" v={data.source} />
    </Section>
  );
}

function InstallTab({ data }) {
  if (!data) return <EmptyTab />;
  return (
    <Section>
      {data.summary && <Summary>{data.summary}</Summary>}
      <KV k="Lead time" v={data.lead_time} mono />
      <KV k="Trade" v={data.trade} />
      <KV k="Critical path" v={data.critical_path ? 'Yes' : 'No'} badge={data.critical_path ? 'gold' : null} />
    </Section>
  );
}

function ComplianceTab({ data }) {
  if (!data) return <EmptyTab />;
  const items = data.items || (data.summary ? data.summary.split(/\s*\u00B7\s*/) : []);
  return (
    <Section>
      {data.summary && <Summary>{data.summary}</Summary>}
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {items.map((it, i) => (
          <li
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 0',
              borderBottom: i < items.length - 1 ? `1px dashed ${BORDER}` : 'none',
              fontSize: 12,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: GOLD,
                flexShrink: 0,
              }}
            />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Section({ children }) {
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{children}</div>;
}

function Summary({ children }) {
  return (
    <div
      style={{
        background: SURFACE,
        border: `1px solid ${BORDER}`,
        borderRadius: 8,
        padding: '10px 12px',
        fontSize: 12,
        lineHeight: 1.5,
        color: INK,
        marginBottom: 4,
      }}
    >
      {children}
    </div>
  );
}

function KV({ k, v, mono, badge }) {
  if (v == null || v === '') return null;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 0',
        borderBottom: `1px dashed ${BORDER}`,
        gap: 12,
      }}
    >
      <span style={{ fontSize: 11, color: MUTED }}>{k}</span>
      <span
        style={{
          fontSize: 12,
          color: INK,
          fontFamily: mono ? "'JetBrains Mono', ui-monospace, monospace" : undefined,
          fontWeight: 500,
          textAlign: 'right',
          maxWidth: '70%',
        }}
      >
        {badge === 'gold' ? (
          <span
            style={{
              background: GOLD,
              color: INK,
              padding: '2px 8px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.3,
              textTransform: 'uppercase',
            }}
          >
            {v}
          </span>
        ) : (
          v
        )}
      </span>
    </div>
  );
}

function EmptyState({ id }) {
  return (
    <div style={{ color: MUTED, fontSize: 12, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 600, color: INK, marginBottom: 4 }}>No registry entry</div>
      Asset <code style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>{id}</code> has no record in
      <code style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}> registry.js</code>.
      The drawer will populate once the sibling agent ships the registry module.
    </div>
  );
}

function EmptyTab() {
  return <div style={{ color: MUTED, fontSize: 12 }}>Nothing captured yet.</div>;
}

function FooterButton({ children, onClick, primary, danger }) {
  const base = {
    flex: 1,
    height: 36,
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    border: `1px solid ${BORDER}`,
    background: SURFACE,
    color: INK,
    fontFamily: "'DM Sans', system-ui, sans-serif",
    transition: 'background 120ms, color 120ms',
  };
  const primaryStyle = {
    ...base,
    background: GOLD,
    border: `1px solid ${GOLD}`,
    color: INK,
  };
  const dangerStyle = {
    ...base,
    color: DANGER,
    borderColor: 'rgba(185, 28, 28, 0.3)',
  };
  const style = primary ? primaryStyle : danger ? dangerStyle : base;
  return (
    <button onClick={onClick} style={style}>
      {children}
    </button>
  );
}

function IconClose({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M6 6l12 12M6 18L18 6" />
    </svg>
  );
}
