import React, { useState, useEffect, useRef } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const COLOR_MAP = { green: "#16a34a", amber: "#d97706", red: "#dc2626" };

function SummaryRow({ label, value, color }) {
  return (
    <div className="sd2-row">
      <span className="sd2-row-label">{label}</span>
      <span
        className="sd2-row-value"
        style={color ? { color: COLOR_MAP[color] } : undefined}
      >
        {value || "\u2014"}
      </span>
    </div>
  );
}

function Section({ title, icon, data, loading, children, detailContent }) {
  const [expanded, setExpanded] = useState(false);
  if (!data && !loading) return null;
  return (
    <div className="sd2-section">
      <div className="sd2-section-header" onClick={() => setExpanded(!expanded)}>
        <span className="sd2-section-icon">{icon}</span>
        <span className="sd2-section-title">{title}</span>
        {loading ? (
          <span className="sd2-spinner" />
        ) : (
          <span className="sd2-chevron">{expanded ? "\u25BE" : "\u25B8"}</span>
        )}
      </div>
      {!expanded && data && <div className="sd2-section-summary">{children}</div>}
      {expanded && data && (
        <div className="sd2-section-detail">
          {children}
          {detailContent}
        </div>
      )}
    </div>
  );
}

export default function SiteDashboardV2({ onClose }) {
  const {
    pickedLocation,
    parcelId,
    solarYield,
    gridContext,
    explain,
    agentResult,
    workflowStage,
    samCapacity,
  } = useSite();

  // Local data state
  const [solarData, setSolarData] = useState(null);
  const [windData, setWindData] = useState(null);
  const [planningData, setPlanningData] = useState(null);
  const [ppaData, setPpaData] = useState(null);
  const [envData, setEnvData] = useState(null);
  const [bessData, setBessData] = useState(null);
  const [cableData, setCableData] = useState(null);
  const [queueData, setQueueData] = useState(null);
  const [dispatchData, setDispatchData] = useState(null);

  // Loading states
  const [loadingSolar, setLoadingSolar] = useState(false);
  const [loadingWind, setLoadingWind] = useState(false);
  const [loadingPlanning, setLoadingPlanning] = useState(false);
  const [loadingPpa, setLoadingPpa] = useState(false);
  const [loadingEnv, setLoadingEnv] = useState(false);
  const [loadingBess, setLoadingBess] = useState(false);
  const [loadingCable, setLoadingCable] = useState(false);
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [loadingDispatch, setLoadingDispatch] = useState(false);

  const fetchRef = useRef(0);

  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon ?? pickedLocation?.lng;
  const capacityMw = (samCapacity || 5000) / 1000;

  useEffect(() => {
    if (lat == null || lon == null) return;

    const fetchId = ++fetchRef.current;

    // Reset all data
    setSolarData(null);
    setWindData(null);
    setPlanningData(null);
    setPpaData(null);
    setEnvData(null);
    setBessData(null);
    setCableData(null);
    setQueueData(null);
    setDispatchData(null);

    // Solar yield
    setLoadingSolar(true);
    api.yield.solar(lat, lon, capacityMw).then(d => {
      if (fetchRef.current === fetchId) setSolarData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingSolar(false); });

    // Wind yield
    setLoadingWind(true);
    api.yield.wind(lat, lon, capacityMw).then(d => {
      if (fetchRef.current === fetchId) setWindData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingWind(false); });

    // Planning prediction
    setLoadingPlanning(true);
    api.planning.predict(lat, lon, capacityMw).then(d => {
      if (fetchRef.current === fetchId) setPlanningData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingPlanning(false); });

    // PPA match
    setLoadingPpa(true);
    api.ppa.match(lat, lon, "solar", capacityMw).then(d => {
      if (fetchRef.current === fetchId) setPpaData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingPpa(false); });

    // Environment assessment
    setLoadingEnv(true);
    api.environment.assess(lat, lon, capacityMw).then(d => {
      if (fetchRef.current === fetchId) setEnvData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingEnv(false); });

    // BESS revenue stack
    setLoadingBess(true);
    api.bessRevenue.stack(capacityMw, 2, "Midlands", "2026").then(d => {
      if (fetchRef.current === fetchId) setBessData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingBess(false); });

    // Cable route
    setLoadingCable(true);
    api.cableRoute.bestRoute(lat, lon, capacityMw).then(d => {
      if (fetchRef.current === fetchId) setCableData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingCable(false); });

    // Grid queue prediction
    setLoadingQueue(true);
    api.gridQueue.predict(lat, lon, capacityMw, "solar").then(d => {
      if (fetchRef.current === fetchId) setQueueData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingQueue(false); });

    // Dispatch impact
    setLoadingDispatch(true);
    api.dispatchModel.siteImpact(lat, lon, capacityMw, "solar").then(d => {
      if (fetchRef.current === fetchId) setDispatchData(d);
    }).catch(() => {}).finally(() => { if (fetchRef.current === fetchId) setLoadingDispatch(false); });

  }, [lat, lon, capacityMw]);

  if (lat == null || lon == null) return null;

  // Derived values — solar
  const p50 = solarData?.annual_yield_mwh_p50 ?? solarData?.annual_yield_mwh ?? solarData?.p50;
  const cf = solarData?.capacity_factor_pct ?? solarData?.capacity_factor;
  const lcoe = solarData?.lcoe_gbp_mwh ?? solarData?.lcoe;

  // Derived values — grid / cable / queue
  const bestRoute = cableData?.best_route ?? cableData?.routes?.[0] ?? cableData;
  const subName = bestRoute?.substation_name ?? bestRoute?.substation ?? gridContext?.nearest_substation?.name ?? "\u2014";
  const dist = bestRoute?.distance_km ?? gridContext?.nearest_substation?.distance_km;
  const cableCost = bestRoute?.total_cost_gbp ?? bestRoute?.cost_gbp;
  const queueDepth = queueData?.queue_depth ?? queueData?.projects_ahead ?? queueData?.total_projects;
  const waitMonths = queueData?.estimated_wait_months ?? queueData?.wait_months;

  // Derived values — planning
  const prob = planningData?.approval_probability_pct ?? planningData?.approval_probability ?? planningData?.probability;
  const planMonths = planningData?.estimated_months ?? planningData?.timeline_months;

  // Derived values — PPA
  const buyers = ppaData?.buyers ?? ppaData?.matches ?? [];
  const topBuyer = buyers[0];
  const ppaP10 = ppaData?.price_range?.p10 ?? ppaData?.p10;
  const ppaP90 = ppaData?.price_range?.p90 ?? ppaData?.p90;

  // Derived values — BESS
  const bessTotal = bessData?.total_revenue_gbp_mw_yr ?? bessData?.total_annual ?? bessData?.total;
  const bessDur = bessData?.optimal_duration_hours ?? bessData?.duration_hours ?? 2;
  const bessIrr = bessData?.irr_pct ?? bessData?.irr;

  // Derived values — environment
  const hardConstraints = envData?.hard_constraints ?? envData?.constraints?.hard ?? 0;
  const softConstraints = envData?.soft_constraints ?? envData?.constraints?.soft ?? 0;
  const floodLevel = envData?.flood_risk ?? envData?.flood_zone ?? "\u2014";
  const co2Tonnes = envData?.co2_offset_tonnes_yr ?? envData?.carbon_offset;

  // Derived values — dispatch
  const smp = dispatchData?.marginal_price_gbp_mwh ?? dispatchData?.system_marginal_price;
  const curtail = dispatchData?.curtailment_pct ?? dispatchData?.curtailment_risk;
  const rev = dispatchData?.annual_revenue_gbp_k ?? dispatchData?.revenue_estimate_k;

  // Format helpers
  const fmt = (v, dp = 0) => v != null ? Number(v).toFixed(dp) : null;
  const fmtk = (v) => v != null ? (Number(v) / 1000).toFixed(0) : null;
  const fmtGbp = (v) => {
    if (v == null) return null;
    const n = Number(v);
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
    return n.toFixed(0);
  };

  return (
    <div className="sd2-panel">
      <div className="sd2-header">
        <div className="sd2-site-name">
          {explain?.location_name || explain?.name || "Selected Site"}
        </div>
        <button className="sd2-close" onClick={onClose}>&times;</button>
        <div className="sd2-coords">
          {lat.toFixed(4)}N, {Math.abs(lon).toFixed(4)}{lon < 0 ? "W" : "E"}
        </div>
        {agentResult && (
          <div className="sd2-verdict" data-verdict={agentResult.verdict}>
            {agentResult.verdict}
          </div>
        )}
      </div>

      <div className="sd2-sections">
        {/* Solar Yield */}
        <Section title="Solar Yield" icon={"\u2600\uFE0F"} data={solarData} loading={loadingSolar}>
          <SummaryRow label="Annual Yield" value={p50 != null ? `${fmt(p50, 0)} MWh (P50)` : null} />
          <SummaryRow label="Capacity Factor" value={cf != null ? `${fmt(cf, 1)}%` : null} />
          <SummaryRow label="LCOE" value={lcoe != null ? `\u00A3${fmt(lcoe, 1)}/MWh` : null} />
        </Section>

        {/* Grid Connection */}
        <Section
          title="Grid Connection"
          icon={"\u26A1"}
          data={cableData || gridContext}
          loading={loadingCable || loadingQueue}
        >
          <SummaryRow label="Nearest" value={dist != null ? `${subName} (${fmt(dist, 1)}km)` : subName} />
          <SummaryRow label="Cable Cost" value={cableCost != null ? `\u00A3${fmtGbp(cableCost)} (P50)` : null} />
          <SummaryRow
            label="Queue"
            value={
              queueDepth != null
                ? `${queueDepth} projects${waitMonths != null ? `, ~${fmt(waitMonths, 0)}mo` : ""}`
                : null
            }
          />
        </Section>

        {/* Planning */}
        <Section title="Planning" icon={"\uD83D\uDCCB"} data={planningData} loading={loadingPlanning}>
          <SummaryRow
            label="Approval Probability"
            value={prob != null ? `${fmt(prob, 0)}%` : null}
            color={prob != null ? (prob > 70 ? "green" : prob > 40 ? "amber" : "red") : undefined}
          />
          <SummaryRow label="Est. Timeline" value={planMonths != null ? `${fmt(planMonths, 0)} months` : null} />
          <SummaryRow label="LPA" value={planningData?.authority ?? planningData?.local_authority} />
        </Section>

        {/* PPA & Revenue */}
        <Section title="PPA & Revenue" icon={"\uD83D\uDCB0"} data={ppaData} loading={loadingPpa}>
          <SummaryRow label="Top Buyer" value={topBuyer?.name ?? topBuyer?.buyer_name} />
          <SummaryRow
            label="Price Range"
            value={ppaP10 != null && ppaP90 != null ? `\u00A3${fmt(ppaP10, 0)}-${fmt(ppaP90, 0)}/MWh` : null}
          />
          <SummaryRow
            label="Match Score"
            value={topBuyer?.match_score != null ? `${fmt(topBuyer.match_score, 0)}/100` : null}
          />
        </Section>

        {/* BESS Revenue */}
        <Section title="BESS Revenue" icon={"\uD83D\uDD0B"} data={bessData} loading={loadingBess}>
          <SummaryRow
            label="Annual Revenue"
            value={bessTotal != null ? `\u00A3${fmtGbp(bessTotal)}/MW/yr` : null}
          />
          <SummaryRow label="Optimal Duration" value={bessDur != null ? `${bessDur}h` : null} />
          <SummaryRow label="IRR" value={bessIrr != null ? `${fmt(bessIrr, 1)}%` : null} />
        </Section>

        {/* Environment */}
        <Section title="Environment" icon={"\uD83C\uDF3F"} data={envData} loading={loadingEnv}>
          <SummaryRow
            label="Constraints"
            value={
              hardConstraints != null || softConstraints != null
                ? `${hardConstraints ?? 0} hard, ${softConstraints ?? 0} soft`
                : null
            }
          />
          <SummaryRow label="Flood Risk" value={floodLevel} />
          <SummaryRow label="CO2 Offset" value={co2Tonnes != null ? `${fmt(co2Tonnes, 0)}t/yr` : null} />
        </Section>

        {/* Dispatch Impact */}
        <Section title="Dispatch Impact" icon={"\uD83D\uDCCA"} data={dispatchData} loading={loadingDispatch}>
          <SummaryRow label="Marginal Price" value={smp != null ? `\u00A3${fmt(smp, 1)}/MWh` : null} />
          <SummaryRow label="Curtailment Risk" value={curtail != null ? `${fmt(curtail, 1)}%` : null} />
          <SummaryRow label="Revenue Est." value={rev != null ? `\u00A3${fmt(rev, 0)}k/yr` : null} />
        </Section>
      </div>
    </div>
  );
}
