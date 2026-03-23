import React, { useState, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/**
 * SiteDashboardV2 — Clean right-panel site analysis.
 *
 * Shows ONLY sections that have data. Each section is a compact card
 * with key metrics + a "Run" button for analyses not yet performed.
 * No emojis, no dashes, no clutter.
 */

function MetricRow({ label, value, unit, color }) {
  if (!value && value !== 0) return null;
  return (
    <div className="sd2-metric">
      <span className="sd2-metric-label">{label}</span>
      <span className="sd2-metric-value" style={color ? { color } : undefined}>
        {typeof value === "number" ? value.toLocaleString() : value}
        {unit && <span className="sd2-metric-unit">{unit}</span>}
      </span>
    </div>
  );
}

function ActionCard({ title, status, children, onRun, running }) {
  return (
    <div className={`sd2-card ${status || ""}`}>
      <div className="sd2-card-header">
        <span className="sd2-card-title">{title}</span>
        {status === "done" && <span className="sd2-badge sd2-badge-done">Done</span>}
        {status === "warning" && <span className="sd2-badge sd2-badge-warn">Issue</span>}
        {!status && onRun && (
          <button className="sd2-run-btn" onClick={onRun} disabled={running}>
            {running ? "..." : "Run"}
          </button>
        )}
      </div>
      {children && <div className="sd2-card-body">{children}</div>}
    </div>
  );
}

export default function SiteDashboardV2({ onClose }) {
  const {
    pickedLocation, explain, solarYield, gridContext, slopeStats,
    energyPrice, agentResult,
  } = useSite();

  const [envData, setEnvData] = useState(null);
  const [envLoading, setEnvLoading] = useState(false);
  const [terrainData, setTerrainData] = useState(null);
  const [terrainLoading, setTerrainLoading] = useState(false);
  const [planningData, setPlanningData] = useState(null);
  const [planningLoading, setPlanningLoading] = useState(false);

  const lat = pickedLocation?.lat || explain?.lat || explain?.location?.lat;
  const lon = pickedLocation?.lon || explain?.lon || explain?.location?.lon;

  // Auto-fetch environmental constraints
  useEffect(() => {
    if (!lat || envData) return;
    setEnvLoading(true);
    api.environment?.constraints(lat, lon, 2000)
      .then(d => { if (d) setEnvData(d); })
      .catch(() => {})
      .finally(() => setEnvLoading(false));
  }, [lat, lon]);

  const runTerrain = async () => {
    if (!lat) return;
    setTerrainLoading(true);
    try {
      const d = await api.terrain?.analyse(lat, lon, 500);
      if (d) setTerrainData(d);
    } catch {}
    setTerrainLoading(false);
  };

  const runPlanning = async () => {
    if (!lat) return;
    setPlanningLoading(true);
    try {
      const d = await api.planning?.predictApproval(lat, lon, 50, "solar");
      if (d) setPlanningData(d);
    } catch {}
    setPlanningLoading(false);
  };

  if (!lat) return null;

  const cf = solarYield?.capacity_factor_pct;
  const annualMwh = solarYield?.annual_energy_kwh ? (solarYield.annual_energy_kwh / 1000).toFixed(0) : null;
  const nearest = gridContext?.nearest_substation;
  const headroom = nearest?.headroom_mw;
  const gridDist = nearest?.distance_km;
  const verdict = agentResult?.verdict;

  return (
    <div className="sd2-panel">
      <div className="sd2-header">
        <div>
          <div className="sd2-site-name">{explain?.name || explain?.location_name || "Selected Site"}</div>
          <div className="sd2-coords">{lat?.toFixed(4)}N, {Math.abs(lon)?.toFixed(4)}{lon < 0 ? "W" : "E"}</div>
        </div>
        <button className="sd2-close" onClick={onClose}>&times;</button>
      </div>

      {/* Verdict banner — only if analysis has run */}
      {verdict && (
        <div className={`sd2-verdict sd2-verdict-${verdict.toLowerCase().replace("-","")}`}>
          {verdict}
        </div>
      )}

      <div className="sd2-cards">
        {/* Solar — show if data exists */}
        {cf && (
          <ActionCard title="Solar Resource" status="done">
            <MetricRow label="Capacity Factor" value={`${cf.toFixed(1)}%`} />
            <MetricRow label="Annual Yield" value={annualMwh} unit="MWh" />
            {solarYield?.lcoe_gbp_mwh && <MetricRow label="LCOE" value={`£${solarYield.lcoe_gbp_mwh.toFixed(0)}`} unit="/MWh" />}
          </ActionCard>
        )}

        {/* Grid — show if data exists */}
        {nearest && (
          <ActionCard title="Grid Connection" status={headroom > 20 ? "done" : headroom > 0 ? "warning" : "warning"}>
            <MetricRow label="Nearest" value={nearest.name} />
            <MetricRow label="Distance" value={gridDist?.toFixed(1)} unit="km" />
            <MetricRow label="Headroom" value={headroom?.toFixed(0)} unit="MW" color={headroom > 20 ? "#16a34a" : headroom > 0 ? "#d97706" : "#dc2626"} />
            {nearest.voltage_kv && <MetricRow label="Voltage" value={nearest.voltage_kv} unit="kV" />}
          </ActionCard>
        )}

        {/* Environment — auto-fetched */}
        <ActionCard
          title="Environmental"
          status={envData ? (envData.risk_level === "low" ? "done" : "warning") : null}
          onRun={() => { setEnvLoading(true); api.environment?.constraints(lat, lon, 2000).then(d => { if (d) setEnvData(d); }).finally(() => setEnvLoading(false)); }}
          running={envLoading}
        >
          {envData && (
            <>
              <MetricRow label="Risk" value={envData.risk_level?.toUpperCase()} color={envData.risk_level === "low" ? "#16a34a" : envData.risk_level === "high" ? "#dc2626" : "#d97706"} />
              <MetricRow label="Constraints" value={envData.total || envData.constraints?.length || 0} />
              {envData.constraints?.slice(0, 3).map((c, i) => (
                <div key={i} className="sd2-constraint">{c.type}: {c.name} ({c.distance_m?.toFixed(0)}m)</div>
              ))}
            </>
          )}
        </ActionCard>

        {/* Terrain — on demand */}
        <ActionCard
          title="Terrain Analysis"
          status={terrainData ? "done" : null}
          onRun={runTerrain}
          running={terrainLoading}
        >
          {terrainData && (
            <>
              <MetricRow label="Terrain Score" value={terrainData.terrain_score} unit="/100" />
              <MetricRow label="Mean Slope" value={terrainData.slope_stats?.mean_deg?.toFixed(1)} unit="deg" />
              <MetricRow label="Flatness" value={terrainData.flatness_score?.toFixed(0)} unit="/100" />
              <MetricRow label="Elevation Range" value={terrainData.elevation_range_m?.toFixed(0)} unit="m" />
            </>
          )}
        </ActionCard>

        {/* Planning — on demand */}
        <ActionCard
          title="Planning Approval"
          status={planningData ? (planningData.approval_probability > 0.6 ? "done" : "warning") : null}
          onRun={runPlanning}
          running={planningLoading}
        >
          {planningData && (
            <>
              <MetricRow label="Probability" value={`${(planningData.approval_probability * 100).toFixed(0)}%`}
                color={planningData.approval_probability > 0.7 ? "#16a34a" : planningData.approval_probability > 0.4 ? "#d97706" : "#dc2626"} />
              <MetricRow label="Verdict" value={planningData.verdict} />
              <MetricRow label="Model" value={`${planningData.model_stats?.training_samples?.toLocaleString()} projects`} />
            </>
          )}
        </ActionCard>

        {/* Slope — show if data exists */}
        {slopeStats && (
          <ActionCard title="Slope" status="done">
            <MetricRow label="Mean" value={slopeStats.mean_slope?.toFixed(1)} unit="deg" />
            <MetricRow label="Max" value={slopeStats.max_slope?.toFixed(1)} unit="deg" />
            <MetricRow label="Usable (&lt;10°)" value={`${(slopeStats.pct_under_10deg || 0).toFixed(0)}%`} />
          </ActionCard>
        )}

        {/* Price — show if data exists */}
        {energyPrice && (
          <ActionCard title="Energy Price" status="done">
            <MetricRow label="Current" value={`£${energyPrice.current_price?.toFixed(0)}`} unit="/MWh" />
            {energyPrice.avg_price && <MetricRow label="Average" value={`£${energyPrice.avg_price?.toFixed(0)}`} unit="/MWh" />}
          </ActionCard>
        )}
      </div>
    </div>
  );
}
