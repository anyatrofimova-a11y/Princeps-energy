import React, { useEffect, useState } from "react";

/**
 * AssessWorkloadPanel — renders the workload-specific Assess sub-tab content
 * with real endpoint calls. Replaces the static placeholder card from the
 * first redesign pass with actual data fetched from existing utilities.
 *
 * Workload → endpoint:
 *   dc      → GET  /api/dc/site-suitability?project_id=
 *   solar   → POST /api/analysis/pvlib-simulate (stubbed payload)
 *   bess    → POST /api/finance/dispatch (stubbed payload)
 *   wind    → no endpoint yet, helpful placeholder
 */
export default function AssessWorkloadPanel({ project, workload }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasRun, setHasRun] = useState(false);

  const run = async () => {
    if (!project?.project_id) { setError("No project selected"); return; }
    setLoading(true); setError(null); setData(null);
    try {
      let res;
      if (workload === "dc") {
        const mw = project?.capacity_mw || 50;
        res = await fetch(`/api/dc/site-suitability?project_id=${project.project_id}&it_load_mw=${mw}`);
      } else if (workload === "solar") {
        const firstSite = project?.sites?.[0];
        const lat = firstSite?.lat ?? 52.5;
        const lon = firstSite?.lon ?? -1.5;
        res = await fetch("/api/analysis/pvlib-simulate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat, lon, capacity_mw: project?.capacity_mw || 50, tilt: 30, azimuth: 180 }),
        });
      } else if (workload === "bess") {
        res = await fetch("/api/finance/dispatch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            capacity_mw: project?.capacity_mw || 50,
            duration_hours: 2,
            efficiency: 0.88,
            region: "South",
          }),
        });
      } else {
        setError("Wind dispatch / turbine selection wires next sprint.");
        setLoading(false); return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setHasRun(true);
    } catch (e) {
      setError(e.message || "Request failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (workload === "dc" && project?.project_id && !hasRun) {
      run();
    }
    // eslint-disable-next-line
  }, [workload, project?.project_id]);

  const titles = {
    dc: { label: "DC siting", h: "Cooling · water · fibre · grid carbon",
          lede: "Composite siting score with thermal load, water stress, fibre proximity, and grid carbon intensity." },
    solar: { label: "Solar yield", h: "PvLib simulation",
             lede: "Annual yield, capacity factor, and P50/P90 generation for this parcel." },
    bess: { label: "BESS dispatch", h: "Revenue-stack dispatch",
            lede: "Day-ahead + balancing-mechanism dispatch optimisation against current power prices." },
    wind: { label: "Wind", h: "Turbine selection + wake",
            lede: "Wake-loss modelling and turbine selection — wires next sprint." },
  };
  const t = titles[workload] || { label: workload, h: workload, lede: "" };

  return (
    <div className="awp">
      <header className="awp-head">
        <div className="awp-eyebrow">{t.label}</div>
        <h3 className="awp-title">{t.h}</h3>
        <p className="awp-lede">{t.lede}</p>
      </header>

      <div className="awp-actions">
        <button className="awp-cta" onClick={run} disabled={loading || !project?.project_id}>
          {loading ? "Running…" : hasRun ? "Re-run" : "Run analysis"}
        </button>
        {error && <span className="awp-err">{error}</span>}
      </div>

      {data && workload === "dc" && (
        <section className="awp-grid">
          <Cell label="Composite score" value={data.composite_score} unit="/100" big />
          <Cell label="Cooling load"     value={data.cooling?.load_mw} unit="MW" />
          <Cell label="Cooling tons"     value={data.cooling?.tons} unit="tons" />
          <Cell label="Water flow"       value={data.water?.evaporative_l_per_min} unit="L/min" />
          <Cell label="Water stress"     value={data.water?.stress_index} unit="/100" />
          <Cell label="Grid carbon"      value={data.grid_carbon?.intensity_gco2_kwh} unit="gCO₂/kWh" />
          <Cell label="Region"           value={data.region} unit="" />
          <Cell label="Total load"       value={data.total_load_mw} unit="MW" />
        </section>
      )}

      {data && workload === "solar" && (
        <section className="awp-grid">
          <Cell label="Annual yield" value={data.annual_yield_mwh ?? data.energy_mwh ?? "—"} unit="MWh" big />
          <Cell label="Capacity factor" value={data.capacity_factor_pct ?? data.capacity_factor ?? "—"} unit="%" />
          <Cell label="Specific yield" value={data.specific_yield_kwh_per_kwp ?? "—"} unit="kWh/kWp" />
          <Cell label="P50 / P90" value={`${data.p50 ?? "—"} / ${data.p90 ?? "—"}`} unit="MWh" />
        </section>
      )}

      {data && workload === "bess" && (
        <section className="awp-grid">
          <Cell label="Annual revenue" value={data.annual_revenue_gbp ?? data.revenue ?? "—"} unit="£" big />
          <Cell label="Cycles per year" value={data.cycles_per_year ?? "—"} unit="cycles" />
          <Cell label="Avg cycle £/MWh" value={data.avg_cycle_margin ?? "—"} unit="£/MWh" />
          <Cell label="Capacity factor" value={data.capacity_factor ?? "—"} unit="%" />
        </section>
      )}

      {data && (
        <details className="awp-raw">
          <summary>Raw response</summary>
          <pre>{JSON.stringify(data, null, 2).slice(0, 2000)}</pre>
        </details>
      )}

      <style>{`
        .awp { padding: 24px 40px; max-width: 1100px; }
        .awp-head { margin-bottom: 18px; }
        .awp-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 6px; }
        .awp-title { font-size: 22px; font-weight: 600; color: var(--ink); margin: 0 0 8px 0;
          letter-spacing: -0.3px; }
        .awp-lede { font-size: 13px; line-height: 1.5; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .awp-actions { display: flex; gap: 12px; align-items: center; margin: 20px 0; }
        .awp-cta { background: var(--gold); color: #fff; border: none; border-radius: 8px;
          padding: 9px 18px; font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
        .awp-cta:hover:not(:disabled) { background: var(--gold-dark); }
        .awp-cta:disabled { opacity: 0.4; cursor: not-allowed; }
        .awp-err { font-size: 12px; color: #c0392b; font-family: var(--mono); }
        .awp-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
          margin-top: 16px; }
        .awp-cell { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 8px; padding: 14px 16px; }
        .awp-cell-big { grid-column: span 2; padding: 18px 20px; }
        .awp-cell-label { font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 6px; }
        .awp-cell-value { font-size: 22px; font-weight: 600; color: var(--ink); line-height: 1.1;
          font-family: var(--mono); }
        .awp-cell-big .awp-cell-value { font-size: 32px; color: var(--gold); }
        .awp-cell-unit { font-size: 12px; color: var(--cds-text-helper); margin-left: 6px; font-weight: 400; }
        .awp-raw { margin-top: 24px; font-size: 12px; }
        .awp-raw summary { cursor: pointer; color: var(--cds-text-helper);
          letter-spacing: 1px; text-transform: uppercase; font-size: 10px; font-weight: 600; }
        .awp-raw pre { background: #FAFAFA; padding: 12px; border-radius: 6px; margin-top: 8px;
          overflow: auto; max-height: 300px; font-size: 11px; }
      `}</style>
    </div>
  );
}

function Cell({ label, value, unit, big }) {
  return (
    <div className={"awp-cell" + (big ? " awp-cell-big" : "")}>
      <div className="awp-cell-label">{label}</div>
      <div className="awp-cell-value">
        {value ?? "—"}{unit && <span className="awp-cell-unit">{unit}</span>}
      </div>
    </div>
  );
}
