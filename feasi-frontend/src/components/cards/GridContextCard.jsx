import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";
import ImageryBadge from "../ui/ImageryBadge";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fmt = (v, fallback = "—") => v != null && !isNaN(v) ? v.toLocaleString() : fallback;
const pct = (v) => v != null && !isNaN(v) ? `${(v * 100).toFixed(1)}%` : "—";

export default function GridContextCard() {
  const { gridContext, visionData } = useSite();

  if (!gridContext) {
    return (
      <MetricCard title="Grid" accentColor="#00bcd4">
        <span className="muted">Select a site to see grid data</span>
      </MetricCard>
    );
  }

  const demand = gridContext.demand || {};
  const solar = gridContext.solar_generation || {};
  const curtail = gridContext.curtailment || {};
  const weather = gridContext.weather || {};
  const summary = gridContext.summary || {};
  const sub = gridContext.nearest_substation || {};

  return (
    <MetricCard
      title="Grid"
      accentColor="#00bcd4"
      headerValue={demand.daily_avg ? `${fmt(demand.daily_avg)} MW avg` : sub.name || ""}
    >
      {visionData?.findings?.existing_infrastructure >= 60 && (
        <div style={{ marginBottom: 8 }}>
          <ImageryBadge text="HV line detected nearby" />
        </div>
      )}

      {/* Nearest substation (from grid connection analysis) */}
      {sub.name && (
        <div className="stat-grid">
          <div>Substation: <strong>{sub.name}</strong></div>
          <div>Distance: <strong>{fmt(sub.distance_km)} km</strong> at {fmt(sub.voltage_kv)}kV</div>
          {sub.headroom_mw != null && <div>Headroom: <strong>{fmt(sub.headroom_mw)} MW</strong></div>}
        </div>
      )}

      {/* Demand stats */}
      {demand.daily_avg != null && (
        <div className="stat-grid">
          <div>Avg demand: <strong>{fmt(demand.daily_avg)} MW</strong></div>
          <div>Peak: <strong>{fmt(demand.peak_demand)} MW</strong>{demand.peak_hour != null ? ` at ${demand.peak_hour}:00` : ""}</div>
        </div>
      )}

      {/* 24h demand chart */}
      {demand.hourly_demand_mw?.length > 0 && (
        <>
          <div className="section-label">24h Demand (MW)</div>
          <BarChart
            data={demand.hourly_demand_mw}
            height="small"
            colors="#00bcd4"
            tooltip={(v, i) => `${i}:00 ${fmt(v)} MW`}
          />
        </>
      )}

      {/* Embedded solar */}
      {solar.hourly?.avg_solar_mw?.length > 0 && (
        <>
          <div className="section-label">Embedded Solar (avg MW/h)</div>
          <BarChart
            data={solar.hourly.avg_solar_mw}
            height="small"
            colors="#ff9800"
            tooltip={(v, i) => `${i}:00 ${fmt(v)} MW`}
          />
        </>
      )}

      {/* Curtailment */}
      {curtail.hourly_risk?.length > 0 && (
        <>
          <div className="section-label">Curtailment Risk</div>
          <BarChart
            data={curtail.hourly_risk}
            height="small"
            colors={(v) => v > 0.5 ? "#f44336" : v > 0.25 ? "#ff9800" : "#4caf50"}
            tooltip={(v, i) => `${i}:00 risk ${pct(v)}`}
          />
          <div className="stat-grid">
            <div>Avg risk: <strong>{pct(curtail.avg_risk)}</strong></div>
            <div>Peak: <strong>{pct(curtail.peak_risk)}</strong>{curtail.peak_risk_hour != null ? ` at ${curtail.peak_risk_hour}:00` : ""}</div>
          </div>
        </>
      )}

      {/* Weather */}
      {(weather.temp_avg != null || weather.cloud_cover != null) && (
        <>
          <div className="section-label">Weather</div>
          <div className="stat-grid three">
            {weather.temp_avg != null && <div>Temp: {weather.temp_avg}°C</div>}
            {weather.cloud_cover != null && <div>Cloud: {weather.cloud_cover}%</div>}
            {weather.solar_radiation != null && <div>Solar: {weather.solar_radiation} W/m²</div>}
          </div>
        </>
      )}

      {/* Monthly solar */}
      {solar.monthly?.avg_solar_mw?.length > 0 && (
        <>
          <div className="section-label">Monthly Solar (avg MW)</div>
          <BarChart
            data={solar.monthly.avg_solar_mw}
            labels={MONTHS.map(m => m[0])}
            colors="#ff9800"
            tooltip={(v, i) => `${MONTHS[i]}: ${fmt(v)} MW`}
          />
        </>
      )}
    </MetricCard>
  );
}
