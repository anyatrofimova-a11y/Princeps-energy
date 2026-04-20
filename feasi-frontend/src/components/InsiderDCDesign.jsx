import React, { useEffect, useMemo, useState, useCallback } from "react";

/**
 * InsiderDCDesign — the pre-FID DC Twin that stops pretending to be
 * Cadence Reality / ETAP / an Uptime certificate.
 *
 * D1 grid-anchored capacity envelope · D2 cooling decision engine
 * D3 hourly 24/7 CFE binder · D5 power-chain with real sizing
 * D4 "Download Feasibility Pack" produces JSON (PDF render follow-up)
 *
 * Mounts where the blocky 3D Canvas used to sit on the Design view mode.
 */

const C = {
  bg: "#F7F8FA",
  panel: "#FFFFFF",
  ink: "#1A1714",
  sec: "#6B6560",
  hint: "#9C9590",
  gold: "#F5B731",
  goldDark: "#E8A012",
  border: "#E8E5DF",
  green: "#10b981",
  red: "#ef4444",
  amber: "#F59E0B",
  blue: "#3b82f6",
  mono: "'JetBrains Mono', ui-monospace, monospace",
};

function Num({ v, unit, mono = true, color }) {
  return (
    <span style={{ fontFamily: mono ? C.mono : undefined, fontWeight: 700, color: color || C.ink }}>
      {v}{unit && <span style={{ fontSize: 10, color: C.hint, marginLeft: 3, fontWeight: 500 }}>{unit}</span>}
    </span>
  );
}

function Row({ label, children }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "4px 0", fontSize: 12 }}>
      <span style={{ color: C.sec }}>{label}</span>
      <span>{children}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   D1 — Grid-anchored capacity envelope
   ═══════════════════════════════════════════════════════════════════════ */
/* ── Site placement (D0) ──────────────────────────────────────────────────
   Glint-style spatial context for the DC twin Design tab. Renders a small
   Mapbox satellite image at the picked lat/lon with a building footprint
   overlay sized to the IT load (rule-of-thumb 600 m² / MW for a 2-storey
   hyperscale shell). CTA opens the full Site Designer for polygon editing. */
function SitePlacementCard({ lat, lon, itLoadMw }) {
  const hasCoords = lat != null && lon != null;
  // Footprint sizing: 600 m² per MW of IT load. Hectares for display.
  const footprintHa = itLoadMw > 0 ? (itLoadMw * 600) / 10000 : 0;
  const sideMeters = Math.round(Math.sqrt(footprintHa * 10000));
  // Mapbox static tile — pulled from Vite env (same source as GridTwin).
  const token = (import.meta.env.VITE_MAPBOX_TOKEN
                 || (typeof window !== "undefined" && window.__MAPBOX_TOKEN__)
                 || "");
  const staticUrl = hasCoords && token
    ? `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/`
      + `pin-l-building+f5b731(${lon},${lat})/`
      + `${lon},${lat},14,0/520x180@2x?access_token=${token}`
    : null;

  const openSiteDesigner = () => {
    // Two events fire in order: close any full-screen twin overlay, then ask
    // RedesignLayout/DiscoverTab to open DesignCanvas seeded with the picked
    // coords. App.jsx owns dcTwinOpen so it listens for the close event and
    // unmounts DataCentreTwin before the navigation lands.
    try {
      window.dispatchEvent(new CustomEvent("princeps-close-overlays"));
      window.dispatchEvent(new CustomEvent("princeps-open-site-designer", {
        detail: { lat, lon, it_load_mw: itLoadMw, technology: "data_centre" },
      }));
    } catch {}
  };

  return (
    <section className="idc-card idc-place">
      <header className="idc-card-head">
        <span className="idc-eyebrow">D0 · Site placement</span>
        <span className="idc-citation">Polygon editing in Discover · DesignCanvas</span>
      </header>
      <div className="idc-place-row">
        <div className="idc-place-map">
          {staticUrl ? (
            <img src={staticUrl} alt="Site location" className="idc-place-img"
                 onError={(e) => { e.currentTarget.style.display = "none"; }} />
          ) : (
            <div className="idc-place-empty">
              {hasCoords ? "Map preview unavailable — set MAPBOX_TOKEN" : "No location selected"}
            </div>
          )}
        </div>
        <div className="idc-place-meta">
          <div className="idc-place-coord">
            {hasCoords ? `${lat.toFixed(4)}°, ${lon.toFixed(4)}°` : "Pick a parcel on the Map"}
          </div>
          <div className="idc-place-stats">
            <div><span className="idc-lbl">Building shell</span><Num v={footprintHa} unit="ha" /></div>
            <div><span className="idc-lbl">Side ≈</span><Num v={sideMeters} unit="m" /></div>
            <div><span className="idc-lbl">Rule</span><span className="idc-place-rule">600 m²/MW</span></div>
          </div>
          <button className="idc-place-cta" onClick={openSiteDesigner}>
            Draw polygon in Site Designer →
          </button>
        </div>
      </div>
    </section>
  );
}

function GridEnvelopeCard({ envelope, itLoadMw, onClampLoad }) {
  if (!envelope) return <div className="idc-loading">Loading grid envelope…</div>;
  if (envelope.warning) return <div className="idc-warn">{envelope.warning}</div>;

  const over = envelope.envelope_shortfall_mw > 0;
  const pct = itLoadMw > 0 ? Math.min(100, (envelope.designable_envelope_mw / itLoadMw) * 100) : 100;

  return (
    <section className="idc-card">
      <header className="idc-card-head">
        <span className="idc-eyebrow">D1 · Grid envelope</span>
        <span className="idc-citation">{envelope.citation}</span>
      </header>

      <div className="idc-grid-3">
        <div>
          <div className="idc-lbl">Firm headroom</div>
          <Num v={envelope.firm_import_mw} unit="MW" />
          <div className="idc-hint">N-1 checked · {envelope.primary?.voltage_kv} kV</div>
        </div>
        <div>
          <div className="idc-lbl">Non-firm</div>
          <Num v={envelope.non_firm_mw} unit="MW" />
          <div className="idc-hint">Flexible connection</div>
        </div>
        <div>
          <div className="idc-lbl">Designable envelope</div>
          <Num v={envelope.designable_envelope_mw} unit="MW" color={over ? C.amber : C.green} />
          <div className="idc-hint">{over ? `${envelope.envelope_shortfall_mw} MW short of ${itLoadMw} MW target` : "Fully served"}</div>
        </div>
      </div>

      <div className="idc-bar">
        <div className="idc-bar-fill" style={{ width: `${pct}%`, background: over ? C.amber : C.green }} />
        <div className="idc-bar-label">
          {envelope.primary?.name} ({envelope.primary?.dno?.toUpperCase()}) · {envelope.primary?.distance_km} km
        </div>
      </div>

      <div className="idc-grid-3" style={{ marginTop: 10 }}>
        <Row label="Queue position">
          <Num v={envelope.queue_position} /> <span style={{ color: C.hint, fontSize: 11 }}>of local pipeline</span>
        </Row>
        <Row label="MW ahead in queue">
          <Num v={envelope.mw_ahead} unit="MW" />
        </Row>
        <Row label="ECR P50 energisation">
          <Num v={envelope.ecr_quarter_p50} mono={true} />
        </Row>
      </div>
      <div className="idc-ecr-bands">
        <span>P10 {envelope.ecr_quarter_p10}</span>
        <span>P50 {envelope.ecr_quarter_p50}</span>
        <span>P90 {envelope.ecr_quarter_p90}</span>
      </div>
      {envelope.connection_cost_gbp && (
        <div className="idc-cost-row">
          Connection cost P50: <b>£{((envelope.connection_cost_gbp.p50 || 0) / 1_000_000).toFixed(2)}M</b>
          <span className="idc-hint">
            &nbsp;(P10 £{((envelope.connection_cost_gbp.p10 || 0) / 1_000_000).toFixed(2)}M · P90 £{((envelope.connection_cost_gbp.p90 || 0) / 1_000_000).toFixed(2)}M)
          </span>
        </div>
      )}
      {over && (
        <button className="idc-clamp-btn" onClick={() => onClampLoad?.(envelope.designable_envelope_mw)}>
          Clamp IT load to {envelope.designable_envelope_mw} MW →
        </button>
      )}
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   D5 — Single-line schematic with real sizing
   ═══════════════════════════════════════════════════════════════════════ */
function SingleLineDiagram({ chain }) {
  if (!chain) return <div className="idc-loading">Sizing power chain…</div>;
  const eq = chain.sized_equipment || {};
  const t = eq.transformer || {}; const u = eq.ups || {};
  const g = eq.genset || {}; const sw = eq.switchgear || {};

  return (
    <section className="idc-card">
      <header className="idc-card-head">
        <span className="idc-eyebrow">D5 · Single-line (pre-FID sizing)</span>
        <span className="idc-citation">
          Sized from IT load × PF × diversity × redundancy — feed ETAP for coordination / arc-flash
        </span>
      </header>

      <svg viewBox="0 0 820 220" style={{ width: "100%", height: 220, background: "#FAF9F6", borderRadius: 6 }}>
        {/* Utility feed */}
        <g transform="translate(20,90)">
          <circle cx="20" cy="20" r="16" fill="#fff" stroke={C.ink} strokeWidth="1.5" />
          <text x="20" y="25" textAnchor="middle" fontSize="12" fontFamily="monospace" fill={C.ink}>U</text>
          <text x="20" y="-6" textAnchor="middle" fontSize="10" fill={C.sec}>Utility</text>
          <text x="20" y="50" textAnchor="middle" fontSize="10" fill={C.hint}>33/132 kV</text>
        </g>
        <line x1="56" y1="110" x2="130" y2="110" stroke={C.ink} strokeWidth="1.5" />
        {/* HV switchgear */}
        <g transform="translate(130,90)">
          <rect x="0" y="0" width="90" height="40" fill="#fff" stroke={C.ink} strokeWidth="1.5" rx="2" />
          <text x="45" y="24" textAnchor="middle" fontSize="10" fontWeight="700" fill={C.ink}>HV SGR</text>
          <text x="45" y="-6" textAnchor="middle" fontSize="10" fill={C.sec}>{sw.main_panels_count} panels</text>
          <text x="45" y="56" textAnchor="middle" fontSize="10" fill={C.hint}>bus {sw.bus_arrangement}</text>
        </g>
        <line x1="220" y1="110" x2="280" y2="110" stroke={C.ink} strokeWidth="1.5" />
        {/* Transformers */}
        <g transform="translate(280,80)">
          <rect x="0" y="0" width="110" height="60" fill={C.gold} fillOpacity="0.12" stroke={C.goldDark} strokeWidth="1.5" rx="2" />
          <text x="55" y="20" textAnchor="middle" fontSize="10" fontWeight="700" fill={C.ink}>TRANSFORMERS</text>
          <text x="55" y="36" textAnchor="middle" fontSize="11" fontFamily="monospace" fontWeight="700" fill={C.ink}>{t.count}× {t.mva_each} MVA</text>
          <text x="55" y="50" textAnchor="middle" fontSize="9" fill={C.sec}>total {t.total_mva} MVA</text>
        </g>
        <line x1="390" y1="110" x2="450" y2="110" stroke={C.ink} strokeWidth="1.5" />
        {/* Main LV switchboard A/B */}
        <g transform="translate(450,80)">
          <rect x="0" y="0" width="90" height="60" fill="#fff" stroke={C.ink} strokeWidth="1.5" rx="2" />
          <text x="45" y="18" textAnchor="middle" fontSize="10" fontWeight="700" fill={C.ink}>MSB A/B</text>
          <text x="45" y="34" textAnchor="middle" fontSize="9" fill={C.sec}>dual bus</text>
          <text x="45" y="48" textAnchor="middle" fontSize="9" fill={C.hint}>{sw.main_panels_count}× panels</text>
        </g>
        <line x1="540" y1="110" x2="590" y2="110" stroke={C.ink} strokeWidth="1.5" />
        {/* UPS */}
        <g transform="translate(590,80)">
          <rect x="0" y="0" width="100" height="60" fill={C.green} fillOpacity="0.10" stroke={C.green} strokeWidth="1.5" rx="2" />
          <text x="50" y="20" textAnchor="middle" fontSize="10" fontWeight="700" fill={C.ink}>UPS</text>
          <text x="50" y="36" textAnchor="middle" fontSize="11" fontFamily="monospace" fontWeight="700" fill={C.ink}>{u.modules_required}× {u.module_kva} kVA</text>
          <text x="50" y="50" textAnchor="middle" fontSize="9" fill={C.sec}>{u.autonomy_minutes} min · {u.total_kva / 1000} MVA</text>
        </g>
        <line x1="690" y1="110" x2="740" y2="110" stroke={C.ink} strokeWidth="1.5" />
        {/* Racks */}
        <g transform="translate(740,90)">
          <rect x="0" y="0" width="60" height="40" fill={C.ink} rx="2" />
          <text x="30" y="24" textAnchor="middle" fontSize="10" fontWeight="700" fill="#fff">IT LOAD</text>
        </g>
        {/* Genset branch */}
        <line x1="175" y1="130" x2="175" y2="180" stroke={C.ink} strokeWidth="1.5" strokeDasharray="3 3" />
        <g transform="translate(140,180)">
          <rect x="0" y="0" width="70" height="30" fill={C.red} fillOpacity="0.10" stroke={C.red} strokeWidth="1.5" rx="2" />
          <text x="35" y="12" textAnchor="middle" fontSize="9" fontWeight="700" fill={C.ink}>GENSETS</text>
          <text x="35" y="24" textAnchor="middle" fontSize="10" fontFamily="monospace" fontWeight="700" fill={C.ink}>{g.count}× {g.kw_each}kW</text>
        </g>
        <text x="215" y="200" fontSize="9" fill={C.sec}>{g.fuel_hours}h · {(g.fuel_litres / 1000).toFixed(0)}k L</text>
      </svg>

      <div className="idc-checks">
        <div className="idc-check-head">
          <span>Uptime: claimed <b>{chain.uptime_tier_claimed}</b></span>
          <span className={`idc-tier-pill ${chain.uptime_tier_met}`}>met {chain.uptime_tier_met}</span>
        </div>
        {(chain.checks || []).map((c, i) => (
          <div key={i} className={`idc-check ${c.pass ? "ok" : "fail"}`}>
            <span className="idc-check-dot" />
            <span className="idc-check-name">{c.name}</span>
            <span className="idc-check-reason">{c.reason}</span>
          </div>
        ))}
      </div>
      <div className="idc-caveat">{chain.caveat}</div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   D2 — Cooling topology decision engine (compact inline table)
   ═══════════════════════════════════════════════════════════════════════ */
function CoolingDecisionCard({ cooling, selected, onSelect }) {
  if (!cooling) return <div className="idc-loading">Ranking cooling topologies…</div>;
  const rec = cooling.recommended_topology;
  return (
    <section className="idc-card">
      <header className="idc-card-head">
        <span className="idc-eyebrow">D2 · Cooling topology</span>
        <span className="idc-citation">{cooling.caveat}</span>
      </header>
      <table className="idc-table">
        <thead>
          <tr>
            <th>Topology</th>
            <th>PUE<sub>mech</sub></th>
            <th>WUE</th>
            <th>ASHRAE h-out</th>
            <th>Water risk</th>
            <th>2050 UKCP18 Δ</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(cooling.topologies || []).map((t) => (
            <tr key={t.key}
                className={`${t.key === (selected || rec) ? "sel" : ""} ${t.key === rec ? "rec" : ""}`}
                onClick={() => onSelect?.(t.key)}>
              <td>
                <b>{t.label}</b>
                <span className="idc-row-hint">{t.note}</span>
              </td>
              <td><span style={{ fontFamily: C.mono }}>{t.pue_mech_ref}</span></td>
              <td><span style={{ fontFamily: C.mono }}>{t.wue_l_per_kwh}</span> <span className="idc-hint">L/kWh</span></td>
              <td><span style={{ fontFamily: C.mono }}>{t.ashrae_hours_out_envelope_a3}</span> h/yr</td>
              <td>
                <span className={`idc-risk-pill ${t.water_abstraction_risk}`}>{t.water_abstraction_risk}</span>
              </td>
              <td style={{ color: t.ukcp18_2050_pue_delta < 0 ? C.red : C.sec }}>
                {t.ukcp18_2050_pue_delta > 0 ? "+" : ""}{t.ukcp18_2050_pue_delta.toFixed(2)}
              </td>
              <td>{t.key === rec && <span className="idc-rec-tag">rec</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="idc-citations">
        {cooling.citations.map((c, i) => <span key={i}>{c}</span>)}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   D3 — Hourly 24/7 CFE binder (summary chip + sparkline)
   ═══════════════════════════════════════════════════════════════════════ */
function CfeBinderCard({ cfe }) {
  if (!cfe) return <div className="idc-loading">Computing hourly-matched CFE…</div>;
  const badge = cfe.google_procurement_badge;
  const badgeColor = badge === "PASS" ? C.green : badge === "CAUTION" ? C.amber : C.red;
  return (
    <section className="idc-card">
      <header className="idc-card-head">
        <span className="idc-eyebrow">D3 · Hourly 24/7 CFE</span>
        <span className="idc-citation">{cfe.citation}</span>
      </header>
      <div className="idc-grid-3">
        <div>
          <div className="idc-lbl">Hourly-matched CFE</div>
          <Num v={cfe.cfe_247_pct} unit="%" color={badgeColor} />
          <div className="idc-hint">EnergyTag T-EAC method</div>
        </div>
        <div>
          <div className="idc-lbl">Residual carbon</div>
          <Num v={cfe.residual_gco2_per_kwh} unit="gCO₂/kWh" />
          <div className="idc-hint">Demand-weighted</div>
        </div>
        <div>
          <div className="idc-lbl">Google procurement</div>
          <span className="idc-badge" style={{ background: badgeColor }}>{badge}</span>
          <div className="idc-hint">{cfe.hours_above_90pct_cfe} h/yr ≥ 90%</div>
        </div>
      </div>
      <div className="idc-monthly">
        {(cfe.monthly_cfe_pct || []).map((v, i) => (
          <div key={i} className="idc-mbar"
               style={{ height: `${v}%`, background: v >= 90 ? C.green : v >= 70 ? C.amber : C.red }}
               title={`M${i + 1}: ${v}% CFE`} />
        ))}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   Main component
   ═══════════════════════════════════════════════════════════════════════ */
export default function InsiderDCDesign({
  lat, lon, itLoadMw, tier, redundancy, pvMw = 0, bessMwh = 0,
  onClampIt, onSelectCooling, projectId,
}) {
  const [envelope, setEnvelope] = useState(null);
  const [cooling, setCooling] = useState(null);
  const [cfe, setCfe] = useState(null);
  const [chain, setChain] = useState(null);
  const [selectedCoolingKey, setSelectedCoolingKey] = useState(null);
  const [packDownloading, setPackDownloading] = useState(false);

  useEffect(() => {
    if (lat == null || lon == null) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/dc/grid-envelope", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat, lon, target_it_load_mw: itLoadMw }),
        });
        if (r.ok && !cancelled) setEnvelope(await r.json());
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [lat, lon, itLoadMw]);

  useEffect(() => {
    if (lat == null || lon == null) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/dc/cooling-topology", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat, lon, it_load_mw: itLoadMw }),
        });
        if (r.ok && !cancelled) setCooling(await r.json());
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [lat, lon, itLoadMw]);

  useEffect(() => {
    if (lat == null || lon == null) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch("/api/dc/hourly-cfe-247", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat, lon, it_load_mw: itLoadMw, pv_mw: pvMw, bess_mwh: bessMwh, demand_flex_pct: 5 }),
        });
        if (r.ok && !cancelled) setCfe(await r.json());
      } catch { /* silent */ }
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [lat, lon, itLoadMw, pvMw, bessMwh]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/dc/power-chain-sized", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ it_load_mw: itLoadMw, tier, redundancy, pf: 0.9, diversity_factor: 1.0, genset_fuel_hours: 72 }),
        });
        if (r.ok && !cancelled) setChain(await r.json());
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [itLoadMw, tier, redundancy]);

  const downloadPack = useCallback(async () => {
    setPackDownloading(true);
    try {
      const r = await fetch("/api/dc/feasibility-pack", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId, lat, lon, it_load_mw: itLoadMw, tier, redundancy,
          cooling_topology: selectedCoolingKey || cooling?.recommended_topology,
          pv_mw: pvMw, bess_mwh: bessMwh,
        }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const data = await r.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `princeps-feasibility-pack-${Date.now()}.json`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Pack download failed: ${e.message || e}`);
    } finally {
      setPackDownloading(false);
    }
  }, [projectId, lat, lon, itLoadMw, tier, redundancy, selectedCoolingKey, cooling, pvMw, bessMwh]);

  return (
    <div className="idc-root">
      <div className="idc-header-band">
        <div className="idc-header-l">
          <span className="idc-title">Pre-FID DC Feasibility</span>
          <span className="idc-subtitle">Not a CFD / protection study — feeds Cadence Reality + ETAP downstream</span>
        </div>
        <button className="idc-pack-btn" onClick={downloadPack} disabled={packDownloading}>
          {packDownloading ? "Generating…" : "Download Feasibility Pack ↓"}
        </button>
      </div>

      <SitePlacementCard lat={lat} lon={lon} itLoadMw={itLoadMw} />
      <GridEnvelopeCard envelope={envelope} itLoadMw={itLoadMw} onClampLoad={onClampIt} />
      <SingleLineDiagram chain={chain} />
      <CoolingDecisionCard
        cooling={cooling}
        selected={selectedCoolingKey}
        onSelect={(k) => { setSelectedCoolingKey(k); onSelectCooling?.(k); }}
      />
      <CfeBinderCard cfe={cfe} />

      <style>{`
        .idc-root {
          display: flex; flex-direction: column; gap: 12px;
          padding: 14px 16px; overflow-y: auto; height: 100%;
          background: ${C.bg}; font-family: "DM Sans", -apple-system, sans-serif;
        }
        .idc-header-band {
          display: flex; justify-content: space-between; align-items: center;
          padding: 10px 14px; border-radius: 10px;
          background: ${C.panel}; border: 1px solid ${C.border};
        }
        .idc-header-l { display: flex; flex-direction: column; gap: 2px; }
        .idc-title { font-size: 14px; font-weight: 700; color: ${C.ink}; }
        .idc-subtitle { font-size: 11px; color: ${C.sec}; }
        .idc-pack-btn {
          padding: 8px 14px; background: ${C.gold}; color: #fff; border: none;
          border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer;
          font-family: inherit;
        }
        .idc-pack-btn:hover:not(:disabled) { background: ${C.goldDark}; }
        .idc-pack-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .idc-card {
          background: ${C.panel}; border: 1px solid ${C.border};
          border-radius: 10px; padding: 14px 16px;
        }
        .idc-place-row { display: flex; gap: 14px; align-items: stretch; }
        .idc-place-map {
          flex: 1.2; min-height: 140px; max-height: 180px;
          border-radius: 8px; overflow: hidden;
          background: linear-gradient(135deg, #e2e8f0, #f1f5f9);
          display: flex; align-items: center; justify-content: center;
        }
        .idc-place-img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .idc-place-empty { color: ${C.hint}; font-size: 11px; padding: 16px; text-align: center; }
        .idc-place-meta {
          flex: 1; display: flex; flex-direction: column; gap: 8px;
          padding: 4px 0;
        }
        .idc-place-coord {
          font-family: "JetBrains Mono", monospace; font-size: 12px; color: ${C.ink};
          font-weight: 600;
        }
        .idc-place-stats {
          display: grid; grid-template-columns: 1fr 1fr 1fr;
          gap: 10px; padding: 8px 0;
        }
        .idc-place-stats > div { display: flex; flex-direction: column; gap: 2px; }
        .idc-place-rule {
          font-family: "JetBrains Mono", monospace; font-size: 11px; color: ${C.sec};
        }
        .idc-place-cta {
          margin-top: auto; align-self: flex-start;
          padding: 7px 13px; background: ${C.ink}; color: #fff; border: none;
          border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer;
          font-family: inherit;
        }
        .idc-place-cta:hover { background: #1e293b; }
        .idc-card-head {
          display: flex; justify-content: space-between; align-items: baseline;
          margin-bottom: 10px; gap: 12px;
        }
        .idc-eyebrow {
          font-size: 10px; font-weight: 800; letter-spacing: 0.08em;
          text-transform: uppercase; color: ${C.ink};
        }
        .idc-citation {
          font-size: 10px; color: ${C.hint}; font-style: italic; text-align: right;
        }
        .idc-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }
        .idc-lbl {
          font-size: 10px; color: ${C.sec}; text-transform: uppercase;
          letter-spacing: 0.06em; font-weight: 600; margin-bottom: 3px;
        }
        .idc-hint { font-size: 10px; color: ${C.hint}; margin-top: 2px; }
        .idc-bar {
          position: relative; margin-top: 10px;
          height: 14px; background: ${C.border}; border-radius: 3px; overflow: hidden;
        }
        .idc-bar-fill { height: 100%; transition: width 0.3s; }
        .idc-bar-label {
          position: absolute; left: 10px; top: 0; line-height: 14px;
          font-size: 10px; color: ${C.ink}; font-weight: 600;
        }
        .idc-ecr-bands {
          display: flex; justify-content: space-between; gap: 10px;
          font-family: ${C.mono}; font-size: 11px; color: ${C.sec};
          margin-top: 8px; padding: 6px 10px;
          background: ${C.bg}; border-radius: 6px;
        }
        .idc-cost-row {
          margin-top: 8px; font-size: 12px; color: ${C.ink};
        }
        .idc-clamp-btn {
          margin-top: 8px; padding: 6px 10px;
          background: rgba(245,183,49,0.12); border: 1px solid rgba(245,183,49,0.3);
          color: ${C.goldDark}; border-radius: 6px;
          font-size: 11px; font-weight: 700; cursor: pointer; font-family: inherit;
        }
        .idc-clamp-btn:hover { background: rgba(245,183,49,0.22); }

        .idc-checks { margin-top: 12px; display: flex; flex-direction: column; gap: 4px; }
        .idc-check-head {
          display: flex; justify-content: space-between; font-size: 11px;
          color: ${C.sec}; margin-bottom: 6px;
        }
        .idc-tier-pill {
          padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 800;
          background: ${C.green}; color: #fff;
        }
        .idc-check {
          display: grid; grid-template-columns: 14px 1fr 2fr; gap: 8px;
          align-items: baseline;
          font-size: 11px; padding: 4px 0;
        }
        .idc-check.ok .idc-check-dot {
          background: ${C.green}; box-shadow: 0 0 0 2px rgba(16,185,129,0.15);
        }
        .idc-check.fail .idc-check-dot {
          background: ${C.red}; box-shadow: 0 0 0 2px rgba(239,68,68,0.15);
        }
        .idc-check-dot {
          width: 8px; height: 8px; border-radius: 50%; display: inline-block;
        }
        .idc-check-name { font-weight: 600; color: ${C.ink}; }
        .idc-check-reason { color: ${C.sec}; }
        .idc-caveat {
          margin-top: 10px; font-size: 10px; color: ${C.hint};
          font-style: italic; padding-top: 8px; border-top: 1px solid ${C.border};
        }

        .idc-table { width: 100%; border-collapse: collapse; font-size: 11px; }
        .idc-table th {
          text-align: left; font-weight: 700; font-size: 10px;
          letter-spacing: 0.04em; text-transform: uppercase;
          color: ${C.sec}; padding: 6px 8px; border-bottom: 1px solid ${C.border};
        }
        .idc-table td {
          padding: 8px 8px; border-bottom: 1px solid ${C.border};
          vertical-align: top;
        }
        .idc-table tr { cursor: pointer; transition: background 0.15s; }
        .idc-table tr:hover { background: ${C.bg}; }
        .idc-table tr.sel { background: rgba(245,183,49,0.08); }
        .idc-table tr.rec td:first-child { border-left: 2px solid ${C.gold}; }
        .idc-row-hint { display: block; font-size: 10px; color: ${C.hint}; margin-top: 2px; font-weight: 400; }
        .idc-risk-pill {
          padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 700;
          text-transform: uppercase; letter-spacing: 0.04em;
        }
        .idc-risk-pill.high { background: rgba(239,68,68,0.15); color: #b91c1c; }
        .idc-risk-pill.low { background: rgba(16,185,129,0.12); color: #047857; }
        .idc-rec-tag {
          background: ${C.gold}; color: #fff; padding: 2px 6px;
          border-radius: 3px; font-size: 9px; font-weight: 800;
          text-transform: uppercase;
        }
        .idc-citations {
          margin-top: 10px; padding-top: 8px; border-top: 1px solid ${C.border};
          display: flex; flex-wrap: wrap; gap: 12px;
          font-size: 10px; color: ${C.hint}; font-style: italic;
        }

        .idc-badge {
          padding: 3px 10px; border-radius: 4px; color: #fff;
          font-size: 11px; font-weight: 800; letter-spacing: 0.04em;
        }
        .idc-monthly {
          display: grid; grid-template-columns: repeat(12, 1fr);
          align-items: end; gap: 3px;
          height: 60px; margin-top: 10px; padding: 6px;
          background: ${C.bg}; border-radius: 6px;
        }
        .idc-mbar { border-radius: 2px; min-height: 2px; opacity: 0.8; }

        .idc-loading, .idc-warn {
          padding: 14px 16px; font-size: 12px; color: ${C.hint};
          background: ${C.panel}; border: 1px dashed ${C.border}; border-radius: 8px;
        }
        .idc-warn { color: ${C.red}; border-color: ${C.red}; }
      `}</style>
    </div>
  );
}
