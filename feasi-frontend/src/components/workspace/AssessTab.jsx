import React, { useMemo, useState, useEffect, lazy, Suspense } from "react";
import GridTab from "./GridTab";
import AssessWorkloadPanel from "./AssessWorkloadPanel";
import { matchesWorkload } from "../../lib/workload";

const DemandForecastPanel = lazy(() => import("../DemandForecastPanel"));
const PlanningIntelligencePanel = lazy(() => import("../PlanningIntelligencePanel"));
// Lazy-loaded so deck.gl + Mapbox bundles only hydrate when Assess is active.
const AssessProjectTwin = lazy(() => import("../assess/AssessProjectTwin"));

const BASE_SUBTABS = [
  { key: "grid",     label: "Grid" },
  { key: "demand",   label: "Demand" },
  { key: "planning", label: "Planning" },
];

const WORKLOAD_SUBTAB = {
  bess:  { key: "dispatch", label: "Dispatch", title: "BESS dispatch model",
           body: "Wires to ", endpoint: "/api/finance/dispatch" },
  solar: { key: "yield",    label: "Yield",    title: "PV yield assessment",
           body: "Wires to ", endpoint: "/api/analysis/pvlib-simulate" },
  dc:    { key: "cooling",  label: "Cooling",  title: "ASHRAE / PUE / cooling load",
           body: "Wires to ", endpoint: "/api/dc/site-suitability" },
  wind:  { key: "turbines", label: "Turbines", title: "Turbine selection + wake",
           body: "Coming next sprint.", endpoint: null },
};

/**
 * AssessTab — engineering deep-dive on a chosen site/project.
 * Consolidates Grid, Demand, Planning, Environmental into one tab with sub-nav.
 * Existing panels are reused as-is (nothing is deleted; everything is surfaced).
 */
export default function AssessTab({ project, onPopOutTwin = () => {}, subTabHint = null }) {
  const [active, setActive] = useState("grid");

  const wl = project?.workload_type;
  const wlExtra = useMemo(() => {
    for (const key of Object.keys(WORKLOAD_SUBTAB)) {
      if (matchesWorkload(wl, key)) return WORKLOAD_SUBTAB[key];
    }
    return null;
  }, [wl]);

  const subtabs = useMemo(
    () => (wlExtra ? [...BASE_SUBTABS, { key: wlExtra.key, label: wlExtra.label }] : BASE_SUBTABS),
    [wlExtra]
  );

  // Sidebar / ActionsMenu can request a specific sub-tab via subTabHint
  // (e.g. "Grid Connection" → subTabHint="grid"). Respect it whenever it
  // changes to a valid sub-tab key for the current workload.
  useEffect(() => {
    if (!subTabHint) return;
    const valid = subtabs.some((t) => t.key === subTabHint);
    if (valid && subTabHint !== active) setActive(subTabHint);
  }, [subTabHint, subtabs]); // eslint-disable-line

  return (
    <div className="as-tab">
      <header className="as-head">
        <div className="as-eyebrow">Engineering deep-dive</div>
        <h2 className="as-title">Assess</h2>
        <p className="as-lede">
          Grid headroom, demand forecast, planning probability, and environmental
          screening for {project?.name || "this project"}.
        </p>
      </header>

      <section className="as-twin-wrap" aria-label="Project twin">
        <Suspense fallback={<div className="as-loading">Loading project twin…</div>}>
          <AssessProjectTwin
            projectId={project?.project_id || project?.id}
            polygon_wkt={project?.polygon_wkt || project?.metadata?.polygon_wkt || null}
            tech={project?.workload_type || project?.tech || null}
            capacity_mw={project?.capacity_mw || project?.target_capacity_mw || null}
          />
        </Suspense>
      </section>

      <nav className="as-subnav" role="tablist">
        {subtabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            className={"as-subtab" + (active === t.key ? " as-subtab-active" : "")}
            onClick={() => setActive(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="as-body">
        {active === "grid" && <GridTab project={project} onPopOut={onPopOutTwin} />}
        {active === "demand" && (
          <Suspense fallback={<div className="as-loading">Loading demand…</div>}>
            <div className="as-panel-wrap"><DemandForecastPanel /></div>
          </Suspense>
        )}
        {active === "planning" && (
          <Suspense fallback={<div className="as-loading">Loading planning…</div>}>
            <div className="as-panel-wrap"><PlanningIntelligencePanel /></div>
          </Suspense>
        )}
        {wlExtra && active === wlExtra.key && (
          <AssessWorkloadPanel project={project} workload={project?.workload_type} />
        )}
      </main>

      <style>{`
        .as-tab { display: flex; flex-direction: column; flex: 1; min-height: 0; }
        .as-head { padding: 32px 40px 16px 40px; }
        .as-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .as-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .as-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .as-twin-wrap { padding: 8px 40px 16px 40px; }
        .as-subnav { display: flex; gap: 2px; padding: 0 40px;
          border-bottom: 1px solid var(--cds-border-subtle); }
        .as-subtab { background: none; border: none; padding: 10px 14px;
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 12px; font-weight: 600; color: var(--cds-text-secondary);
          cursor: pointer; border-bottom: 2px solid transparent; transition: all 120ms;
          margin-bottom: -1px; letter-spacing: 0.3px; }
        .as-subtab:hover { color: var(--ink); }
        .as-subtab-active { color: var(--ink); border-bottom-color: var(--gold); }
        .as-body { flex: 1; min-height: 0; overflow: auto; }
        .as-loading { padding: 40px; color: var(--cds-text-helper);
          font-family: var(--mono); font-size: 13px; text-align: center; }
        .as-panel-wrap { padding: 20px 40px; min-height: 100%; }
        .as-panel-wrap > * {
          position: relative !important;
          inset: auto !important;
          width: 100% !important;
          height: auto !important;
          max-width: none !important;
          box-shadow: none !important;
        }
        .as-wl-card { background: var(--cds-layer-01); border: 1px dashed var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .as-wl-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 8px; }
        .as-wl-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
        .as-wl-body { font-size: 12px; color: var(--cds-text-secondary); line-height: 1.5; }
        .as-wl-mono { font-family: var(--mono); font-size: 11px; color: var(--cds-text-secondary); }
      `}</style>
    </div>
  );
}
