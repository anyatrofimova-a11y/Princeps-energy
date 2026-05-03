/**
 * BessEngineeringPanel.jsx — Right-side drawer surfacing the BESS
 * engineering pack returned by /api/twin/bess-design.
 *
 * Sections:
 *   - Hero summary (capacity, MWh BoL, vendor, RTE, LCOS, $/kWh)
 *   - Single-line diagram (SVG)
 *   - Augmentation schedule + SoH curve
 *   - CapEx breakdown bars
 *   - Bill of Quantities (collapsible by category)
 *   - Cable schedule (sortable)
 *   - Notes / standards cited
 */

import React, { useMemo, useState } from 'react';
import SingleLineDiagram from './SingleLineDiagram.jsx';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';

const usd = (v) => {
  if (!Number.isFinite(v)) return '—';
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
};
const num = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const pct = (v, d = 1) => (Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : '—');

const CATEGORY_LABEL = {
  battery: 'Battery containers',
  pcs: 'Power conversion',
  transformer: 'Transformers',
  switchgear: 'Switchgear & GIS',
  cabling: 'Cabling',
  civil: 'Civil works',
  fire: 'Fire & safety',
  scada: 'SCADA & control',
  balance_of_plant: 'Balance of plant',
  interconnect: 'Grid interconnect',
  epc: 'EPC + soft costs',
};

function CategoryBar({ label, value, max, colour }) {
  const w = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: IVORY, marginBottom: 2 }}>
        <span>{label}</span>
        <span style={{ color: GOLD, fontWeight: 600 }}>{usd(value)}</span>
      </div>
      <div style={{ background: '#22252e', borderRadius: 3, height: 6 }}>
        <div style={{ width: `${w}%`, height: '100%', background: colour, borderRadius: 3 }} />
      </div>
    </div>
  );
}

function HeroCard({ label, value, sub }) {
  return (
    <div style={{
      background: '#171a22', border: '1px solid #2a2e38',
      borderRadius: 6, padding: 10, minWidth: 0,
    }}>
      <div style={{ fontSize: 10.5, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>{label}</div>
      <div style={{ fontSize: 18, color: GOLD, fontWeight: 600, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: '#cbd1dc', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function SectionTitle({ children, right }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      margin: '18px 0 8px', fontSize: 11, color: '#9aa1ad',
      textTransform: 'uppercase', letterSpacing: 0.8,
    }}>
      <span>{children}</span>
      {right ? <span style={{ color: GOLD }}>{right}</span> : null}
    </div>
  );
}

function CategoryGroup({ title, lines, total, openByDefault }) {
  const [open, setOpen] = useState(!!openByDefault);
  return (
    <div style={{ borderTop: '1px solid #22252e' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          width: '100%', padding: '6px 4px', cursor: 'pointer',
          background: 'transparent', border: 'none', color: IVORY, fontSize: 12.5,
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: GOLD, fontFamily: 'monospace' }}>{open ? '▾' : '▸'}</span>
          {title}
          <span style={{ color: '#778093', fontSize: 11 }}>· {lines.length}</span>
        </span>
        <span style={{ color: GOLD, fontWeight: 600 }}>{usd(total)}</span>
      </button>
      {open && (
        <div style={{ padding: '4px 6px 8px 18px' }}>
          {lines.map((l) => (
            <div key={l.code} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr 60px 70px',
              fontSize: 11, color: '#cbd1dc', padding: '2px 0',
              borderBottom: '1px dashed #1c1f27',
            }}>
              <span style={{ color: '#778093', fontFamily: 'monospace' }}>{l.code}</span>
              <span>{l.label}</span>
              <span style={{ textAlign: 'right' }}>{num(l.qty, 0)} {l.unit}</span>
              <span style={{ textAlign: 'right', color: IVORY }}>{usd(l.total_usd)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SohSparkline({ rte_curve, soh_curve, augmentation_schedule, height = 110 }) {
  if (!Array.isArray(soh_curve) || soh_curve.length < 2) return null;
  const W = 320;
  const H = height;
  const padX = 26, padY = 14;
  const xs = soh_curve.map(([y]) => y);
  const ys = soh_curve.map(([, s]) => s);
  const maxY = Math.max(...ys, 100);
  const minY = Math.min(...ys, 70);
  const xMax = Math.max(...xs);
  const sx = (y) => padX + (y / xMax) * (W - 2 * padX);
  const sy = (s) => padY + (1 - (s - minY) / (maxY - minY)) * (H - 2 * padY);
  const path = soh_curve.map(([y, s], i) =>
    `${i === 0 ? 'M' : 'L'} ${sx(y).toFixed(1)} ${sy(s).toFixed(1)}`,
  ).join(' ');
  const rtePath = (rte_curve || [])
    .map(([y, r], i) => {
      const v = r * 100; // overlay RTE on same scale (× 100 to share % range)
      return `${i === 0 ? 'M' : 'L'} ${sx(y).toFixed(1)} ${sy(v).toFixed(1)}`;
    }).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
      <rect x={padX} y={padY} width={W - 2 * padX} height={H - 2 * padY} fill="#0c0e12" stroke="#22252e" />
      <path d={path} fill="none" stroke={GOLD} strokeWidth={1.5} />
      {rtePath && <path d={rtePath} fill="none" stroke="#508cdc" strokeDasharray="4 3" strokeWidth={1.2} />}
      {(augmentation_schedule || []).map((a, i) => (
        <line
          key={`aug-${i}`}
          x1={sx(a.year)} x2={sx(a.year)}
          y1={padY} y2={H - padY}
          stroke="#76b582" strokeOpacity={0.6} strokeDasharray="2 4"
        />
      ))}
      <text x={padX + 4} y={padY + 12} fontSize={10} fill={GOLD}>SoH %</text>
      <text x={W - padX - 4} y={padY + 12} fontSize={10} fill="#508cdc" textAnchor="end">RTE × 100</text>
      <text x={padX + 4} y={H - 4} fontSize={9.5} fill="#778093">y0</text>
      <text x={W - padX - 4} y={H - 4} fontSize={9.5} fill="#778093" textAnchor="end">y{xMax}</text>
    </svg>
  );
}

export default function BessEngineeringPanel({ design, open = true, onClose }) {
  if (!open || !design) return null;

  const summary = design.summary || {};
  const cap = design.capex_breakdown || {};
  const total = cap.total_usd || 0;

  const bomByCategory = useMemo(() => {
    const out = {};
    for (const l of design.bom || []) {
      out[l.category] ||= [];
      out[l.category].push(l);
    }
    return out;
  }, [design]);

  const categoriesOrdered = [
    'battery', 'pcs', 'transformer', 'switchgear',
    'cabling', 'civil', 'fire', 'scada',
    'balance_of_plant', 'interconnect', 'epc',
  ];

  const maxCapex = Math.max(
    ...categoriesOrdered.map((c) => cap[c] || 0), 1,
  );

  return (
    <div style={{
      position: 'absolute', top: 0, right: 0, height: '100%',
      width: 380, maxWidth: '40vw',
      background: 'rgba(11,12,15,0.96)', borderLeft: '1px solid #2a2e38',
      color: IVORY, fontFamily: 'system-ui, sans-serif',
      overflowY: 'auto', padding: '12px 14px',
      backdropFilter: 'blur(10px)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 13, color: GOLD, fontWeight: 600, letterSpacing: 0.6 }}>
          BESS ENGINEERING PACK
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'transparent', color: '#9aa1ad', border: 'none', cursor: 'pointer', fontSize: 14 }}
            aria-label="close"
          >×</button>
        )}
      </div>
      <div style={{ fontSize: 10.5, color: '#778093', marginTop: 2, marginBottom: 12 }}>
        {(summary.standards || []).slice(0, 4).join(' · ')}
      </div>

      {/* Hero strip */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <HeroCard label="Capacity" value={`${num(summary.capacity_mw, 0)} MW · ${num(summary.duration_h, 1)} h`}
                  sub={`${num(summary.energy_mwh_bol, 1)} MWh @ BoL`} />
        <HeroCard label="LCOS" value={`$${num(summary.lcos_usd_per_mwh, 0)}/MWh`}
                  sub={`${usd(summary.capex_total_usd)} CapEx · $${num(summary.capex_per_kwh_usd, 0)}/kWh`} />
        <HeroCard label="Battery" value={summary.vendor?.label || '—'}
                  sub={`${num(summary.vendor?.energy_kwh, 0)} kWh · ${summary.vendor?.chemistry} · ${num(summary.vendor?.cycle_life_to_80pct, 0)} cyc`} />
        <HeroCard label="Round-trip η" value={pct(summary.vendor?.rte_bol)}
                  sub={`→ ${pct(summary.vendor?.rte_eol)} EoL`} />
        <HeroCard label="Containers" value={`${summary.n_containers ?? '—'}`}
                  sub={`${num(summary.block_dimensions_m?.w, 0)} × ${num(summary.block_dimensions_m?.d, 0)} m block`} />
        <HeroCard label="PCS / Main TX" value={`${summary.pcs?.count ?? '—'} · ${summary.main_tx?.count ?? '—'}`}
                  sub={`${num(summary.pcs?.rating_kw, 0)} kW / ${num(summary.main_tx?.rating_mva, 0)} MVA`} />
      </div>

      {/* Single-line */}
      <SectionTitle right={`${(design.single_line?.nodes || []).length} nodes`}>
        Single-line diagram
      </SectionTitle>
      <SingleLineDiagram design={design} />

      {/* SoH curve + augmentation timeline */}
      <SectionTitle right={`${(design.augmentation_schedule || []).length} augmentation events`}>
        Health & augmentation
      </SectionTitle>
      <div style={{ background: '#0c0e12', border: '1px solid #22252e', borderRadius: 6, padding: 6 }}>
        <SohSparkline
          rte_curve={design.rte_curve}
          soh_curve={design.soh_curve}
          augmentation_schedule={design.augmentation_schedule}
        />
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: '#cbd1dc' }}>
        {(design.augmentation_schedule || []).slice(0, 6).map((a) => (
          <div key={`aug-row-${a.year}`} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px dashed #22252e', padding: '2px 0' }}>
            <span>Y{a.year} · SoH {num(a.soh_before_pct, 1)}%</span>
            <span style={{ color: '#76b582' }}>+{a.units_added} ctn</span>
            <span style={{ color: GOLD }}>{usd(a.capex_usd)}</span>
          </div>
        ))}
        {(design.augmentation_schedule || []).length > 6 && (
          <div style={{ color: '#778093', fontSize: 10.5, textAlign: 'center', marginTop: 4 }}>
            +{design.augmentation_schedule.length - 6} more …
          </div>
        )}
      </div>

      {/* CapEx breakdown */}
      <SectionTitle right={usd(total)}>CapEx breakdown</SectionTitle>
      {categoriesOrdered.map((c) => (
        <CategoryBar
          key={c}
          label={CATEGORY_LABEL[c] || c}
          value={cap[c] || 0}
          max={maxCapex}
          colour={c === 'battery' ? GOLD : (c === 'pcs' ? '#508cdc' : (c === 'transformer' ? '#76b582' : '#7d6ec5'))}
        />
      ))}

      {/* BoQ */}
      <SectionTitle right={`${(design.bom || []).length} lines`}>Bill of quantities</SectionTitle>
      {categoriesOrdered.map((c) => {
        const lines = bomByCategory[c] || [];
        if (!lines.length) return null;
        const t = lines.reduce((s, l) => s + (l.total_usd || 0), 0);
        return (
          <CategoryGroup
            key={c}
            title={CATEGORY_LABEL[c] || c}
            lines={lines}
            total={t}
            openByDefault={c === 'battery'}
          />
        );
      })}

      {/* Cable schedule */}
      <SectionTitle right={`${(design.cable_runs || []).length} runs`}>Cable schedule</SectionTitle>
      <div style={{ fontSize: 11, color: '#cbd1dc', maxHeight: 220, overflowY: 'auto', borderTop: '1px solid #22252e' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '70px 70px 60px 60px 50px',
          padding: '4px 0', color: '#778093', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.6,
        }}>
          <span>From</span><span>To</span><span style={{ textAlign: 'right' }}>kV</span>
          <span style={{ textAlign: 'right' }}>L (m)</span><span style={{ textAlign: 'right' }}>mm²</span>
        </div>
        {(design.cable_runs || []).slice(0, 80).map((c, i) => (
          <div key={`cable-${i}`} style={{
            display: 'grid', gridTemplateColumns: '70px 70px 60px 60px 50px',
            padding: '2px 0', borderBottom: '1px dashed #1c1f27',
          }}>
            <span style={{ color: '#cbd1dc' }}>{c.from_role}</span>
            <span style={{ color: '#cbd1dc' }}>{c.to_role}</span>
            <span style={{ textAlign: 'right', color: GOLD }}>{num(c.voltage_kv, 1)}</span>
            <span style={{ textAlign: 'right' }}>{num(c.length_m, 0)}</span>
            <span style={{ textAlign: 'right', color: IVORY }}>{c.conductor_mm2}</span>
          </div>
        ))}
        {(design.cable_runs || []).length > 80 && (
          <div style={{ color: '#778093', fontSize: 10.5, textAlign: 'center', padding: 4 }}>
            +{design.cable_runs.length - 80} runs …
          </div>
        )}
      </div>

      {/* Notes */}
      <SectionTitle>Engineering notes</SectionTitle>
      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: '#cbd1dc' }}>
        {(design.notes || []).map((n, i) => (
          <li key={`note-${i}`} style={{ marginBottom: 2 }}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
