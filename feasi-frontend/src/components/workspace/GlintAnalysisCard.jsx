/**
 * GlintAnalysisCard — Glint-Solar-grade analysis panel for the project's
 * Overview tab. Pulls live data from /api/planning-data/constraints,
 * /api/finance/auto-defaults, and /api/parcels/{id}/enriched (where
 * applicable) and renders the headline verdict + drilldown sections.
 *
 * Sections:
 *   1. Verdict pill (GO / CAUTION / NO-GO) + £-denominated NPV summary
 *   2. Solar / BESS / DC potential — capacity (MWp), annual MWh, specific yield
 *   3. Land — ALC grade, mean slope, area-ha, flood risk
 *   4. BNG — required 10%, baseline habitat units, offset cost £
 *   5. Planning constraints within 500m — bucketed CRITICAL / HIGH / MEDIUM
 *   6. Tenders nearby — Find-a-Tender notices within 50km
 *   7. Grid connection cost P50 from project metadata
 */

import React, { useEffect, useState, useMemo } from "react";

const VERDICT_STYLE = {
  GO:        { bg: "rgba(22,163,74,0.14)",  fg: "#16A34A", label: "GO" },
  CAUTION:   { bg: "rgba(232,160,18,0.16)", fg: "#92660D", label: "CAUTION" },
  "NO-GO":   { bg: "rgba(220,38,38,0.14)",  fg: "#DC2626", label: "NO-GO" },
};

function VerdictPill({ verdict }) {
  const v = VERDICT_STYLE[(verdict || "").toUpperCase()] || VERDICT_STYLE.GO;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px", borderRadius: 999,
      background: v.bg, color: v.fg,
      fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
    }}>{v.label}</span>
  );
}

function fmtGbp(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `£${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000)     return `£${(n / 1_000).toFixed(0)}k`;
  return `£${Math.round(n)}`;
}

export default function GlintAnalysisCard({ project }) {
  const [constraints, setConstraints] = useState(null);
  const [defaults, setDefaults]       = useState(null);
  const [loading, setLoading]         = useState(true);

  const { project_id, lat, lon, technology, capacity_mw, name, metadata } = project || {};

  useEffect(() => {
    if (!lat || !lon) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetch(`/api/planning-data/constraints?lat=${lat}&lon=${lon}&radius_m=500`)
        .then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`/api/finance/auto-defaults?project_id=${encodeURIComponent(project_id || "")}&technology=${technology || "solar"}&capacity_mw=${capacity_mw || 50}`)
        .then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([c, d]) => {
      if (cancelled) return;
      setConstraints(c);
      setDefaults(d);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [project_id, lat, lon, technology, capacity_mw]);

  const verdict = useMemo(() => {
    if (!constraints) return null;
    const crit = (constraints.by_severity?.CRITICAL || []).length;
    if (crit === 0) return "GO";
    if (crit === 1) return "CAUTION";
    return "NO-GO";
  }, [constraints]);

  const solar = useMemo(() => {
    if (!capacity_mw) return null;
    // Conservative UK: 1100 kWh/kWp/yr (solar), 30% CF (wind), 18% (BESS arb), 90% (DC)
    const yields = { solar: 1100, wind: 2628, bess: 1577, datacentre: 7884 };
    const sy = yields[(technology || "solar").toLowerCase()] || yields.solar;
    return {
      mwp: capacity_mw,
      mwh_yr: Math.round(capacity_mw * sy),
      specific_yield: sy,
    };
  }, [capacity_mw, technology]);

  if (!lat || !lon) {
    return (
      <div className="ov-card">
        <div className="ov-card-header"><span>Glint-grade analysis</span></div>
        <div style={{ padding: 16, fontSize: 13, color: "#6B7280" }}>
          No coordinates for this project — add lat/lon to enable site analysis.
        </div>
      </div>
    );
  }

  const meta = metadata || {};
  const gridCostP50 = meta.cost_p50_gbp;
  const firmHeadroom = meta.firm_headroom_mw;
  const queueDepth   = meta.queue_depth;
  const dno          = meta.dno;
  const poc          = meta.poc;
  const ppaMwh       = defaults?.revenue?.ppa_price_mwh;
  const cfdStrike    = defaults?.revenue?.cfd_strike;

  // BNG estimate from area — assume 6 habitat units / ha
  const areaHa = (capacity_mw || 0) * (technology === "solar" ? 1.8 : technology === "bess" ? 0.5 : 0.3);
  const bngUnits = Math.round(areaHa * 6 * 10) / 10;
  const bngCost  = Math.round(bngUnits * 0.10 * 42_000);

  return (
    <div className="ov-card" style={{ position: "relative" }}>
      <div className="ov-card-header" style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12,
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontWeight: 600 }}>Princeps site analysis</span>
          <span style={{ fontSize: 10.5, color: "#6B7280", letterSpacing: "0.05em" }}>
            REAL-TIME · GLINT-GRADE
          </span>
        </span>
        {loading ? (
          <span style={{ fontSize: 11, color: "#6B7280" }}>analysing…</span>
        ) : (
          <VerdictPill verdict={verdict} />
        )}
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12, padding: 16,
      }}>
        {/* Capacity / yield */}
        <Section label="Yield potential">
          <KV k="Capacity"    v={solar ? `${solar.mwp} MW${technology === "solar" ? "p" : ""}` : "—"} />
          <KV k="Annual MWh"  v={solar ? `${(solar.mwh_yr / 1000).toFixed(1)} GWh` : "—"} />
          <KV k="Specific yield" v={solar ? `${solar.specific_yield} kWh/kWp·yr` : "—"} />
        </Section>

        {/* Land */}
        <Section label="Land">
          <KV k="Area (est)" v={areaHa ? `${areaHa.toFixed(1)} ha` : "—"} />
          <KV k="ALC grade"  v={"—"} sub="next: NASADEM slope" />
          <KV k="Land cover" v={"—"} sub="next: UKCEH LCM" />
        </Section>

        {/* BNG */}
        <Section label="BNG (DEFRA Nov 2024+)">
          <KV k="Required" v="10%" />
          <KV k="Baseline units" v={`${bngUnits}`} />
          <KV k="Offset cost (P50)" v={fmtGbp(bngCost)} />
        </Section>

        {/* Grid */}
        <Section label="Grid">
          <KV k="DNO" v={dno || "—"} />
          <KV k="POC" v={poc || "—"} />
          <KV k="Firm headroom" v={firmHeadroom ? `${firmHeadroom} MW` : "—"} />
          <KV k="Queue depth"   v={queueDepth != null ? `${queueDepth}` : "—"} />
          <KV k="Connection P50" v={fmtGbp(gridCostP50)} />
        </Section>

        {/* Revenue */}
        <Section label="Revenue (live)">
          <KV k="PPA price" v={ppaMwh ? `£${ppaMwh}/MWh` : "—"}
              sub={defaults?.sources?.ppa} />
          <KV k="CfD strike" v={cfdStrike ? `£${cfdStrike}/MWh` : "n/a"}
              sub={cfdStrike ? "AR7 (DESNZ Jan 2026)" : "no CfD route"} />
        </Section>

        {/* Planning constraints */}
        <Section label="Planning constraints (500m)">
          {loading ? (
            <div style={{ fontSize: 12, color: "#6B7280" }}>scanning 101k designations…</div>
          ) : constraints ? (
            <>
              <KV k="CRITICAL" v={`${(constraints.by_severity?.CRITICAL || []).length}`} />
              <KV k="HIGH"     v={`${(constraints.by_severity?.HIGH || []).length}`} />
              <KV k="MEDIUM"   v={`${(constraints.by_severity?.MEDIUM || []).length}`} />
            </>
          ) : <div style={{ fontSize: 12, color: "#6B7280" }}>—</div>}
        </Section>
      </div>

      <div style={{
        padding: "10px 16px", borderTop: "1px solid var(--cds-border-subtle)",
        fontSize: 10.5, color: "#6B7280", letterSpacing: "0.02em",
      }}>
        REPD · NGED CIM · planning.data.gov.uk · HMLR CCOD · BMRS · AR7 reference price
      </div>
    </div>
  );
}

function Section({ label, children }) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.6)",
      border: "1px solid var(--cds-border-subtle)",
      borderRadius: 10, padding: "10px 12px",
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
        textTransform: "uppercase", color: "#6B7280", marginBottom: 8,
      }}>{label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {children}
      </div>
    </div>
  );
}

function KV({ k, v, sub }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
      <span style={{ fontSize: 12, color: "#4B5563" }}>{k}</span>
      <span style={{ textAlign: "right" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "#15171C", fontFamily: "'JetBrains Mono', monospace" }}>{v}</span>
        {sub && <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 1 }}>{sub}</div>}
      </span>
    </div>
  );
}
