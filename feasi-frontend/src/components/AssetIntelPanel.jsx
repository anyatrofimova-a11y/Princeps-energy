/**
 * AssetIntelPanel.jsx — rich slide-in panel for any clicked energy asset.
 *
 * Props:
 *   target:  { lat: number, lon: number, name?: string, tech?: string,
 *              radius_km?: number } | null
 *   onClose: () => void
 *
 * Fetches /api/asset-intel and renders tabbed content sourced from PlanIt
 * (LPA + nearby applications), Wikidata (biography), REPD (renewable assets
 * within radius), NESO TEC, the closest grid substation, Companies House
 * (when CH key configured), and live GB carbon intensity.
 *
 * Self-contained — no external chart libs, no extra deps.
 */

import React, { useEffect, useMemo, useState } from 'react';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';

const num = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const fmt = (v) => (v === null || v === undefined || v === '') ? '—' : v;

async function fetchIntel(t) {
  const params = new URLSearchParams({
    lat: String(t.lat), lon: String(t.lon),
    radius_km: String(t.radius_km || 5),
  });
  if (t.name) params.set('name', t.name);
  if (t.tech) params.set('tech', t.tech);
  const r = await fetch(`/api/asset-intel?${params}`);
  if (!r.ok) throw new Error(`asset-intel ${r.status}`);
  return r.json();
}

function Tab({ active, label, count, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'transparent', border: 'none',
        color: active ? GOLD : '#cbd1dc',
        fontSize: 11.5, fontWeight: active ? 600 : 500,
        padding: '8px 10px', cursor: 'pointer',
        borderBottom: `2px solid ${active ? GOLD : 'transparent'}`,
        textTransform: 'uppercase', letterSpacing: 0.6,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
      {Number.isFinite(count) && (
        <span style={{ marginLeft: 5, color: '#778093', fontWeight: 500 }}>· {count}</span>
      )}
    </button>
  );
}

function Field({ label, value, mono = false }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', padding: '4px 0', borderBottom: '1px dashed #1f222b' }}>
      <span style={{ fontSize: 10.5, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>{label}</span>
      <span style={{ fontSize: 12, color: IVORY, fontFamily: mono ? 'monospace' : 'inherit' }}>{fmt(value)}</span>
    </div>
  );
}

function Pill({ children, color = '#3a3f4b' }) {
  return (
    <span style={{
      display: 'inline-block', background: color, color: IVORY,
      fontSize: 10.5, padding: '2px 7px', borderRadius: 10, marginRight: 6, marginBottom: 4,
    }}>{children}</span>
  );
}

function StatusPill({ s }) {
  const k = (s || '').toLowerCase();
  let bg = '#3a3f4b';
  if (k.includes('operational') || k.includes('permitted') || k.includes('approved')) bg = '#1f5236';
  else if (k.includes('reject') || k.includes('refused') || k.includes('abandon')) bg = '#5b2424';
  else if (k.includes('undecided') || k.includes('pending') || k.includes('submitted')) bg = '#3f3a14';
  else if (k.includes('expired') || k.includes('withdraw')) bg = '#3a3a3a';
  else if (k.includes('condition')) bg = '#23425b';
  return <Pill color={bg}>{fmt(s)}</Pill>;
}

function OverviewTab({ data }) {
  const bio = data.biography || {};
  const sub = data.nearest_substation || {};
  const planning = data.planning?.summary || {};
  const repdCount = (data.repd_nearby || []).length;
  const ci = data.carbon_intensity?.intensity || {};
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {bio.image_url && (
          <img
            src={bio.image_url}
            alt={bio.label || ''}
            style={{ width: 110, height: 80, objectFit: 'cover', borderRadius: 6, border: '1px solid #2a2e38' }}
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, color: GOLD, fontWeight: 600 }}>
            {bio.label || data.query?.name || 'Asset'}
          </div>
          <div style={{ fontSize: 11.5, color: '#cbd1dc', marginTop: 2 }}>
            {bio.description || ''}
          </div>
          <div style={{ marginTop: 6 }}>
            {(bio.instance_of || []).map((t) => <Pill key={t} color="#23425b">{t}</Pill>)}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <Field label="Capacity" value={Number.isFinite(bio.capacity_mw) ? `${bio.capacity_mw} MW` : null} />
        <Field label="Owner" value={bio.owner} />
        <Field label="Operator" value={bio.operator} />
        <Field label="OEM" value={bio.oem} />
        <Field label="Commissioned" value={bio.commission_year} />
        <Field label="Wikipedia" value={bio.en_wikipedia_url ? <a href={bio.en_wikipedia_url} target="_blank" rel="noopener noreferrer" style={{ color: GOLD }}>open</a> : null} />
      </div>

      <div style={{ marginTop: 16, fontSize: 11, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>
        Quick stats
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, marginTop: 6 }}>
        <Stat label="Nearest substation" value={sub.name ? `${sub.name}` : '—'}
              sub={sub.name ? `${sub.dno || ''} · ${sub.voltage_kv || '?'} kV · ${sub.distance_km || '?'} km` : ''} />
        <Stat label="Demand headroom"
              value={Number.isFinite(sub.demand_headroom_mw) ? `${sub.demand_headroom_mw} MW` : '—'}
              sub={`gen ${num(sub.gen_headroom_mw, 1)} MW`} />
        <Stat label="Planning apps in 5 km"
              value={planning.total ?? '—'}
              sub={Object.keys(planning.by_authority || {}).slice(0, 2).join(' · ')} />
        <Stat label="Adjacent REPD assets" value={repdCount}
              sub={`within ${data.query?.radius_km || 5} km`} />
        <Stat label="GB carbon now"
              value={Number.isFinite(ci.actual) ? `${ci.actual} gCO₂/kWh` : (Number.isFinite(ci.forecast) ? `${ci.forecast}*` : '—')}
              sub={ci.index || 'index ?'} />
        <Stat label="Source latency" value={`${data.query?.elapsed_ms ?? '?'} ms`} sub="7 sources fanned out" />
      </div>
    </div>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div style={{ background: '#171a22', border: '1px solid #2a2e38', borderRadius: 6, padding: 8 }}>
      <div style={{ fontSize: 10.5, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>{label}</div>
      <div style={{ fontSize: 14, color: GOLD, fontWeight: 600, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 10.5, color: '#cbd1dc', marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function PlanningTab({ data }) {
  const apps = data.planning?.applications || [];
  const summary = data.planning?.summary || {};
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Field label="Total apps" value={summary.total} />
        <Field label="By authority" value={Object.entries(summary.by_authority || {}).slice(0, 4).map(([k, v]) => `${k} (${v})`).join(' · ')} />
        <Field label="By state" value={Object.entries(summary.by_state || {}).slice(0, 5).map(([k, v]) => `${k} (${v})`).join(' · ')} />
        <Field label="Energy-related" value={`${(summary.energy_related_uids || []).length} apps`} />
        <Field label="Date span" value={`${summary.earliest_start || '—'} → ${summary.latest_decision || '—'}`} />
      </div>
      <div style={{ borderTop: '1px solid #22252e', maxHeight: 460, overflowY: 'auto' }}>
        {apps.slice(0, 80).map((a) => (
          <div key={a.uid + a.start_date} style={{ borderBottom: '1px dashed #1c1f27', padding: '6px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <span style={{ fontSize: 11.5, color: GOLD, fontFamily: 'monospace' }}>{a.uid}</span>
              <span style={{ fontSize: 10.5, color: '#778093' }}>
                {Number.isFinite(a.distance_km) ? `${a.distance_km.toFixed(2)} km` : ''}
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: IVORY, marginTop: 2 }}>{a.name || a.description || '—'}</div>
            <div style={{ fontSize: 10.5, color: '#cbd1dc', marginTop: 2 }}>
              {a.authority_name || '—'} · {a.app_type || ''} · {a.start_date || ''}
              {a.decided_date ? ` → ${a.decided_date}` : ''}
            </div>
            <div style={{ marginTop: 3 }}>
              <StatusPill s={a.app_state} />
              {a.decision && a.decision !== a.app_state && <StatusPill s={a.decision} />}
              {a.associated_url && (
                <a href={a.associated_url} target="_blank" rel="noopener noreferrer"
                   style={{ fontSize: 10.5, color: GOLD, marginLeft: 4 }}>portal ↗</a>
              )}
              {a.planit_url && (
                <a href={a.planit_url} target="_blank" rel="noopener noreferrer"
                   style={{ fontSize: 10.5, color: '#9aa1ad', marginLeft: 8 }}>planit ↗</a>
              )}
            </div>
          </div>
        ))}
        {apps.length === 0 && (
          <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
            No planning applications within {data.query?.radius_km} km.
          </div>
        )}
      </div>
    </div>
  );
}

function RepdTab({ data }) {
  const repd = data.repd_nearby || [];
  return (
    <div style={{ maxHeight: 600, overflowY: 'auto' }}>
      {repd.length === 0 && (
        <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
          No REPD assets within {data.query?.radius_km} km.
        </div>
      )}
      {repd.map((r) => (
        <div key={r.repd_id} style={{ borderBottom: '1px dashed #22252e', padding: '6px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 11.5, color: GOLD, fontFamily: 'monospace' }}>{r.repd_id}</span>
            <span style={{ fontSize: 10.5, color: '#778093' }}>{num(r.distance_km, 2)} km</span>
          </div>
          <div style={{ fontSize: 12, color: IVORY, marginTop: 2 }}>{r.site_name || '—'}</div>
          <div style={{ fontSize: 10.5, color: '#cbd1dc', marginTop: 2 }}>
            {r.technology} · {r.capacity_mw ?? '—'} MW
            {r.battery_mwh ? ` · ${r.battery_mwh} MWh` : ''}
            {r.turbines ? ` · ${r.turbines} turbines` : ''}
          </div>
          <div style={{ fontSize: 10.5, color: '#9aa1ad', marginTop: 1 }}>
            {r.planning_authority || ''} {r.planning_ref ? `· ${r.planning_ref}` : ''}
            {r.developer ? ` · ${r.developer}` : ''}
          </div>
          <div style={{ marginTop: 3 }}>
            <StatusPill s={r.status} />
            {r.date_decided && <Pill color="#23425b">decided {r.date_decided}</Pill>}
            {r.date_operational && <Pill color="#1f5236">live {r.date_operational}</Pill>}
            {r.planning_url && (
              <a href={r.planning_url} target="_blank" rel="noopener noreferrer"
                 style={{ fontSize: 10.5, color: GOLD }}>portal ↗</a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TecTab({ data }) {
  const tec = data.tec_nearby || [];
  if (tec.length === 0) {
    return (
      <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
        No NESO TEC register entries within {data.query?.radius_km} km.<br/>
        <span style={{ fontSize: 10.5, color: '#5a6172' }}>
          (TEC table needs geometry backfill — most rows lack coordinates yet.)
        </span>
      </div>
    );
  }
  return (
    <div style={{ maxHeight: 600, overflowY: 'auto' }}>
      {tec.map((t) => (
        <div key={t.tec_id} style={{ borderBottom: '1px dashed #22252e', padding: '6px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 11.5, color: GOLD, fontFamily: 'monospace' }}>{t.tec_id}</span>
            <span style={{ fontSize: 10.5, color: '#778093' }}>{num(t.distance_km, 2)} km</span>
          </div>
          <div style={{ fontSize: 12, color: IVORY, marginTop: 2 }}>
            {t.customer_name || t.spv_name || '—'}
          </div>
          <div style={{ fontSize: 10.5, color: '#cbd1dc' }}>
            {t.connection_site || ''} · {t.fuel_type || ''} · {t.tec_mw} MW (DNC {t.dnc_mw} MW)
          </div>
          <div style={{ marginTop: 3 }}>
            <StatusPill s={t.status} />
            {t.connection_date && <Pill color="#23425b">connect {t.connection_date}</Pill>}
            {t.queue_position && <Pill color="#3a3f4b">queue #{t.queue_position}</Pill>}
          </div>
        </div>
      ))}
    </div>
  );
}

function GridTab({ data }) {
  const sub = data.nearest_substation || {};
  return (
    <div>
      <Field label="Substation" value={sub.name} />
      <Field label="DNO" value={sub.dno} />
      <Field label="Region" value={sub.region} />
      <Field label="Voltage" value={sub.voltage_kv ? `${sub.voltage_kv} kV` : null} />
      <Field label="Site type" value={sub.site_type} />
      <Field label="Distance" value={sub.distance_km ? `${sub.distance_km} km` : null} />
      <Field label="Demand" value={Number.isFinite(sub.demand_mw) ? `${sub.demand_mw} MW` : null} />
      <Field label="Generation" value={Number.isFinite(sub.generation_mw) ? `${sub.generation_mw} MW` : null} />
      <Field label="Demand headroom"
             value={Number.isFinite(sub.demand_headroom_mw) ? `${sub.demand_headroom_mw} MW (${sub.rag_demand || '?'})` : null} />
      <Field label="Gen headroom"
             value={Number.isFinite(sub.gen_headroom_mw) ? `${sub.gen_headroom_mw} MW (${sub.rag_generation || '?'})` : null} />
      <Field label="Tx rating" value={Number.isFinite(sub.transformer_rating_mva) ? `${sub.transformer_rating_mva} MVA` : null} />
      <Field label="Fault level" value={Number.isFinite(sub.fault_level_ka) ? `${sub.fault_level_ka} kA` : null} />
      <Field label="Postcode" value={sub.postcode} />
      <Field label="Town" value={sub.town} />
      <Field label="County" value={sub.county} />
    </div>
  );
}

function DispatchTab({ data }) {
  const d = data.bmrs_dispatch;
  if (!d || !d.summaries?.length) {
    return (
      <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
        No BMU dispatch data — could not resolve a BMU from the asset name.
      </div>
    );
  }
  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Field label="Resolved by" value={(d.queries || []).join(' · ')} />
        <Field label="Candidates" value={d.n_candidates} />
      </div>
      {d.summaries.map((s, i) => {
        const b = s.bmu || {};
        const dx = s.dispatch || {};
        const r = s.rated || {};
        return (
          <div key={s.bmu?.bmu_id || i} style={{ marginBottom: 14, paddingTop: 8, borderTop: '1px solid #22252e' }}>
            <div style={{ fontSize: 13, color: GOLD, fontWeight: 600 }}>{b.bmu_id}</div>
            <div style={{ fontSize: 11, color: '#cbd1dc', marginBottom: 6 }}>
              {b.lead_party} · {b.fuel_type || '—'}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <Stat label="Mean MW (14d)" value={Number.isFinite(dx.mean_mw) ? num(dx.mean_mw, 0) : '—'}
                    sub={`peak ${num(dx.max_mw, 0)} · floor ${num(dx.min_mw, 0)}`} />
              <Stat label="Capacity factor" value={Number.isFinite(dx.capacity_factor) ? `${(dx.capacity_factor * 100).toFixed(1)}%` : '—'}
                    sub={`${dx.n_periods || 0} half-hours`} />
              <Stat label="Total MWh" value={Number.isFinite(dx.total_mwh) ? num(dx.total_mwh, 0) : '—'}
                    sub={`${dx.settlement_from} → ${dx.settlement_to}`} />
              <Stat label="Rated MELS" value={Number.isFinite(r.rated_export_max_mw) ? `${num(r.rated_export_max_mw, 0)} MW` : '—'}
                    sub={`typical ${num(r.rated_export_typical_mw, 0)} MW`} />
            </div>
            <div style={{ fontSize: 10.5, color: '#9aa1ad', marginTop: 4 }}>
              Last period: {dx.last_period || '—'} · {dx.last_mw} MW
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CapacityMarketTab({ data }) {
  const d = data.capacity_market;
  if (!d || !d.cmus?.length) {
    return (
      <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
        No Capacity Market record matched.
      </div>
    );
  }
  return (
    <div>
      <Field label="Query" value={d.query_used} />
      <Field label="CMUs" value={d.n_cmus} />
      <Field label="Latest delivery year" value={d.latest_delivery_year} />
      <Field label="Σ de-rated MW" value={d.sum_de_rated_capacity_mw} />
      <div style={{ marginTop: 10 }}>
        {d.cmus.map((c, i) => (
          <div key={c.cmu?.cmu_id || i} style={{ borderTop: '1px solid #22252e', padding: '8px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, color: GOLD, fontFamily: 'monospace' }}>{c.cmu?.cmu_id}</span>
              <span style={{ fontSize: 10.5, color: '#778093' }}>
                {c.cmu?.type} · delivery {c.cmu?.delivery_year}
              </span>
            </div>
            <div style={{ fontSize: 11, color: '#cbd1dc' }}>{c.cmu?.cmu_technology}</div>
            <div style={{ fontSize: 10.5, color: '#9aa1ad' }}>
              {c.cmu?.applicant} · {c.n_components} comp · de-rated {c.sum_de_rated_capacity_mw} MW
              {Number.isFinite(c.sum_connection_capacity_mw) && c.sum_connection_capacity_mw > 0
                ? ` · conn ${c.sum_connection_capacity_mw} MW` : ''}
            </div>
            <div style={{ marginTop: 3 }}>
              <StatusPill s={c.cmu?.prequal_decision || 'Approved'} />
              {c.cmu?.primary_fuel && <Pill color="#3a3f4b">{c.cmu.primary_fuel}</Pill>}
              {c.cmu?.transmission_or_distribution && <Pill color="#3a3f4b">{c.cmu.transmission_or_distribution}</Pill>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmissionsTab({ data }) {
  const d = data.ea_pollution_inventory;
  if (!d) {
    return (
      <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
        No Environment Agency Pollution Inventory match.
      </div>
    );
  }
  return (
    <div>
      <Field label="Permit" value={d.permit_number} mono />
      <Field label="Operator" value={d.operator} />
      <Field label="Address" value={d.address} />
      <Field label="Postcode" value={d.postcode} />
      <Field label="Activity" value={d.activity} />
      <Field label="Site type" value={d.site_type} />
      <Field label="Year" value={d.year} />
      {Object.entries(d.totals_kg || {}).map(([medium, total]) => (
        <div key={medium} style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>
            {medium} — Σ {Number(total).toLocaleString()} kg
          </div>
          {(d.by_medium[medium] || []).map((sub) => (
            <div key={medium + sub.substance} style={{
              display: 'grid', gridTemplateColumns: '1fr 90px 90px',
              fontSize: 11, color: '#cbd1dc', padding: '2px 0',
              borderBottom: '1px dashed #1c1f27',
            }}>
              <span>{sub.substance}</span>
              <span style={{ textAlign: 'right', color: IVORY }}>
                {sub.quantity_kg !== null ? Number(sub.quantity_kg).toLocaleString() : '—'} kg
              </span>
              <span style={{ textAlign: 'right', color: '#778093' }}>
                thr {sub.threshold_kg !== null ? Number(sub.threshold_kg).toLocaleString() : '—'}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function NewsTab({ data }) {
  const items = data.news || [];
  if (items.length === 0) {
    return (
      <div style={{ color: '#778093', fontSize: 12, padding: 18, textAlign: 'center' }}>
        No recent news mentioning the asset across the configured feeds.
      </div>
    );
  }
  return (
    <div>
      {items.map((it, i) => (
        <div key={it.link + i} style={{ borderBottom: '1px solid #22252e', padding: '8px 0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 10.5, color: GOLD, textTransform: 'uppercase', letterSpacing: 0.6 }}>
              {it.feed_label}
            </span>
            <span style={{ fontSize: 10.5, color: '#778093' }}>
              {it.published_iso ? it.published_iso.slice(0, 10) : ''}
            </span>
          </div>
          <a href={it.link} target="_blank" rel="noopener noreferrer"
             style={{ fontSize: 12, color: IVORY, fontWeight: 600, marginTop: 2, display: 'block', textDecoration: 'none' }}>
            {it.title}
          </a>
          {it.summary && (
            <div style={{ fontSize: 10.5, color: '#cbd1dc', marginTop: 3, lineHeight: 1.3 }}>
              {it.summary.slice(0, 240)}{it.summary.length > 240 ? '…' : ''}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SourcesTab({ data }) {
  const s = data.sources || {};
  const ci = data.carbon_intensity?.intensity || {};
  const ch = data.companies_house || null;
  return (
    <div>
      <div style={{ fontSize: 11, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
        Sources fanned
      </div>
      {Object.entries(s).map(([k, v]) => (
        <Field key={k} label={k} value={v} mono />
      ))}
      <div style={{ marginTop: 12, fontSize: 11, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>
        GB grid context
      </div>
      <Field label="Carbon now" value={Number.isFinite(ci.actual) ? `${ci.actual} gCO₂/kWh (${ci.index})` : null} />
      <Field label="Forecast" value={Number.isFinite(ci.forecast) ? `${ci.forecast} gCO₂/kWh` : null} />
      <Field label="Window" value={data.carbon_intensity?.from ? `${data.carbon_intensity.from} → ${data.carbon_intensity.to}` : null} />

      <div style={{ marginTop: 12, fontSize: 11, color: '#9aa1ad', textTransform: 'uppercase', letterSpacing: 0.6 }}>
        Companies House
      </div>
      {ch ? (
        <>
          <Field label="Company" value={ch.title} />
          <Field label="No." value={ch.company_number} mono />
          <Field label="Status" value={ch.company_status} />
          <Field label="Type" value={ch.company_type} />
          <Field label="Incorp." value={ch.date_of_creation} />
          <Field label="Address" value={ch.address_snippet} />
          <Field label="SIC" value={(ch.sic_codes || []).join(', ')} />
        </>
      ) : (
        <div style={{ color: '#778093', fontSize: 11.5, padding: 6 }}>
          Skipped — set <code>COMPANIES_HOUSE_API_KEY</code> env var (free at developer.company-information.service.gov.uk) to enable.
        </div>
      )}
    </div>
  );
}

// SSE label → existing data-shape key (so the existing tab renderers don't
// have to change). Each source merges into `data` as it arrives.
const SSE_KEY_MAP = {
  wd_nearest: 'wikidata_nearest',
  biography: 'biography',
  planning: 'planning',
  repd: 'repd_nearby',
  tec: 'tec_nearby',
  substation: 'nearest_substation',
  carbon: 'carbon_intensity',
  bmrs: 'bmrs_dispatch',
  capacity_market: 'capacity_market',
  news: 'news',
  ea_pollution_inventory: 'ea_pollution_inventory',
};

const SSE_LABEL_PRETTY = {
  wd_nearest: 'Wikidata',
  biography: 'Biography',
  planning: 'PlanIt',
  repd: 'REPD',
  tec: 'NESO TEC',
  substation: 'Grid',
  carbon: 'Carbon',
  bmrs: 'BMRS',
  capacity_market: 'Capacity Mkt',
  news: 'News',
  ea_pollution_inventory: 'EA pollution',
};

export default function AssetIntelPanel({ target, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('overview');
  const [sourceStatus, setSourceStatus] = useState({});  // {label: 'pending'|'ok'|'error'|'empty'}
  const [doneAt, setDoneAt] = useState(null);

  useEffect(() => {
    if (!target) {
      setData(null); setError(null); setSourceStatus({}); setDoneAt(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData({});  // start with empty object so partial renders work
    setSourceStatus({});
    setDoneAt(null);
    setTab('overview');

    const params = new URLSearchParams({
      lat: String(target.lat), lon: String(target.lon),
      radius_km: String(target.radius_km || 5),
    });
    if (target.name) params.set('name', target.name);
    if (target.tech) params.set('tech', target.tech);

    const es = new EventSource(`/api/asset-intel/stream?${params}`);

    es.onmessage = (e) => {
      if (cancelled) return;
      let payload;
      try { payload = JSON.parse(e.data); } catch { return; }

      if (payload.event === 'started') {
        const initial = {};
        for (const s of payload.sources || []) initial[s] = 'pending';
        setSourceStatus(initial);
        setData((prev) => ({ ...(prev || {}), query: payload.query, sources: payload.sources }));
      } else if (payload.event === 'source') {
        const sseKey = payload.label;
        const dataKey = SSE_KEY_MAP[sseKey] || sseKey;
        const ok = payload.ok && payload.data !== null && payload.data !== undefined &&
                   !(Array.isArray(payload.data) && payload.data.length === 0);
        setSourceStatus((prev) => ({
          ...prev,
          [sseKey]: payload.ok ? (ok ? 'ok' : 'empty') : 'error',
        }));
        // Special-case: planning is normally {summary, applications} — wrap raw apps list.
        let merged = payload.data;
        if (sseKey === 'planning' && Array.isArray(payload.data)) {
          merged = {
            applications: payload.data,
            summary: { total: payload.data.length },
          };
        }
        setData((prev) => ({ ...(prev || {}), [dataKey]: merged }));
      } else if (payload.event === 'done') {
        setLoading(false);
        setDoneAt(payload.elapsed_ms);
        es.close();
      }
    };
    es.onerror = () => {
      if (cancelled) return;
      setError('stream error');
      setLoading(false);
      es.close();
    };

    return () => { cancelled = true; try { es.close(); } catch {} };
  }, [target?.lat, target?.lon, target?.name, target?.tech, target?.radius_km]);

  useEffect(() => {
    if (!target) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [target, onClose]);

  const tabs = useMemo(() => {
    if (!data) return [];
    return [
      { id: 'overview', label: 'Overview' },
      { id: 'dispatch', label: 'Dispatch', count: data.bmrs_dispatch?.summaries?.length },
      { id: 'capacity_market', label: 'CM', count: data.capacity_market?.n_cmus },
      { id: 'emissions', label: 'Emissions', count: data.ea_pollution_inventory ? 1 : 0 },
      { id: 'planning', label: 'Planning', count: data.planning?.summary?.total },
      { id: 'repd', label: 'REPD', count: (data.repd_nearby || []).length },
      { id: 'grid', label: 'Grid' },
      { id: 'tec', label: 'TEC', count: (data.tec_nearby || []).length },
      { id: 'news', label: 'News', count: (data.news || []).length },
      { id: 'sources', label: 'Sources' },
    ];
  }, [data]);

  if (!target) return null;

  return (
    <>
    <style>{`@keyframes px-pulse { 0%,100% { opacity: 0.55 } 50% { opacity: 1 } }`}</style>
    <div
      role="dialog"
      aria-label="Asset intelligence"
      style={{
        position: 'fixed', top: 0, right: 0, height: '100vh',
        width: 460, maxWidth: '46vw', zIndex: 1500,
        background: 'rgba(11,12,15,0.96)', borderLeft: '1px solid #2a2e38',
        boxShadow: '-12px 0 32px rgba(0,0,0,0.45)',
        backdropFilter: 'blur(10px)',
        color: IVORY, fontFamily: 'system-ui, sans-serif',
        display: 'flex', flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderBottom: '1px solid #22252e' }}>
        <div>
          <div style={{ fontSize: 13, color: GOLD, fontWeight: 600, letterSpacing: 0.6 }}>
            ASSET INTEL
          </div>
          <div style={{ fontSize: 10.5, color: '#778093', marginTop: 1 }}>
            {target.lat.toFixed(4)}, {target.lon.toFixed(4)} · {target.radius_km || 5} km radius
          </div>
        </div>
        <button onClick={onClose} aria-label="close"
                style={{ background: 'transparent', color: '#9aa1ad', border: 'none', cursor: 'pointer', fontSize: 18 }}>
          ×
        </button>
      </div>
      <div style={{ display: 'flex', overflowX: 'auto', borderBottom: '1px solid #22252e' }}>
        {tabs.map((t) => (
          <Tab key={t.id} active={tab === t.id} label={t.label} count={t.count}
               onClick={() => setTab(t.id)} />
        ))}
      </div>
      {/* Live source-status strip — pills flip green as each stream chunk arrives. */}
      {Object.keys(sourceStatus).length > 0 && (
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 4,
          padding: '8px 12px', borderBottom: '1px solid #22252e',
          background: 'rgba(245,183,49,0.05)',
          fontSize: 10, fontFamily: 'monospace',
        }}>
          {Object.entries(sourceStatus).map(([sseKey, status]) => {
            const dot = status === 'ok' ? '#22C55E'
              : status === 'empty' ? '#6B7280'
              : status === 'error' ? '#EF4444'
              : '#F5B731';  // pending
            const pulsing = status === 'pending';
            return (
              <span key={sseKey} style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '2px 6px', borderRadius: 4,
                background: 'rgba(255,255,255,0.04)',
                color: status === 'pending' ? '#cbd1dc' : '#9aa1ad',
                opacity: status === 'pending' ? 0.85 : 1,
                animation: pulsing ? 'px-pulse 1.2s ease-in-out infinite' : undefined,
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: dot,
                  boxShadow: status === 'ok' ? '0 0 6px #22C55E' : 'none',
                }} />
                {SSE_LABEL_PRETTY[sseKey] || sseKey}
              </span>
            );
          })}
          {doneAt != null && (
            <span style={{ marginLeft: 'auto', color: '#5a6172', fontSize: 9.5 }}>
              {doneAt}ms
            </span>
          )}
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
        {error && (
          <div style={{ color: '#d57272', fontSize: 12, padding: 24, textAlign: 'center' }}>
            {error}
          </div>
        )}
        {!error && data && (
          <>
            {tab === 'overview' && <OverviewTab data={data} />}
            {tab === 'dispatch' && <DispatchTab data={data} />}
            {tab === 'capacity_market' && <CapacityMarketTab data={data} />}
            {tab === 'emissions' && <EmissionsTab data={data} />}
            {tab === 'planning' && <PlanningTab data={data} />}
            {tab === 'repd'     && <RepdTab data={data} />}
            {tab === 'grid'     && <GridTab data={data} />}
            {tab === 'tec'      && <TecTab data={data} />}
            {tab === 'news'     && <NewsTab data={data} />}
            {tab === 'sources'  && <SourcesTab data={data} />}
          </>
        )}
      </div>
    </div>
    </>
  );
}
