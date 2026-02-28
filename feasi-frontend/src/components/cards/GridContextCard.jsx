import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";
import ImageryBadge from "../ui/ImageryBadge";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export default function GridContextCard() {
  const { gridContext, visionData } = useSite();

  if (!gridContext) {
    return (
      <MetricCard title="Grid" accentColor="#00bcd4">
        <span className="muted">Click Analyse</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Grid"
      accentColor="#00bcd4"
      headerValue={`${gridContext.demand?.daily_avg?.toLocaleString()} MW avg`}
    >
      {visionData?.findings?.existing_infrastructure >= 60 && (
        <div style={{ marginBottom: 8 }}>
          <ImageryBadge text="HV line detected nearby" />
        </div>
      )}
      <div className="stat-grid">
        <div>Records: <strong>{gridContext.summary?.records?.toLocaleString()}</strong></div>
        <div>Range: <strong>{gridContext.summary?.date_range?.[0]} to {gridContext.summary?.date_range?.[1]}</strong></div>
      </div>
      <div className="stat-grid">
        <div>Avg demand: <strong>{gridContext.demand?.daily_avg?.toLocaleString()} MW</strong></div>
        <div>Peak: <strong>{gridContext.demand?.peak_demand?.toLocaleString()} MW</strong> at {gridContext.demand?.peak_hour}:00</div>
      </div>

      <div className="section-label">24h Demand (MW)</div>
      <BarChart
        data={gridContext.demand?.hourly_demand_mw || []}
        height="small"
        colors="#00bcd4"
        tooltip={(v, i) => `${i}:00 ${v.toLocaleString()} MW`}
      />

      <div className="section-label">Embedded Solar (avg MW/h)</div>
      <BarChart
        data={gridContext.solar_generation?.hourly?.avg_solar_mw || []}
        height="small"
        colors="#ff9800"
        tooltip={(v, i) => `${i}:00 ${v} MW`}
      />

      <div className="section-label">Curtailment Risk</div>
      <BarChart
        data={gridContext.curtailment?.hourly_risk || []}
        height="small"
        colors={(v) => v > 0.5 ? "#f44336" : v > 0.25 ? "#ff9800" : "#4caf50"}
        tooltip={(v, i) => `${i}:00 risk ${(v * 100).toFixed(1)}%`}
      />
      <div className="stat-grid">
        <div>Avg risk: <strong>{(gridContext.curtailment?.avg_risk * 100)?.toFixed(1)}%</strong></div>
        <div>Peak: <strong>{(gridContext.curtailment?.peak_risk * 100)?.toFixed(1)}%</strong> at {gridContext.curtailment?.peak_risk_hour}:00</div>
      </div>

      {gridContext.weather && (
        <>
          <div className="section-label">Weather</div>
          <div className="stat-grid three">
            <div>Temp: {gridContext.weather.temp_avg}C</div>
            <div>Cloud: {gridContext.weather.cloud_cover}%</div>
            <div>Solar: {gridContext.weather.solar_radiation} W/m2</div>
          </div>
        </>
      )}

      {gridContext.solar_generation?.monthly?.avg_solar_mw && (
        <>
          <div className="section-label">Monthly Solar (avg MW)</div>
          <BarChart
            data={gridContext.solar_generation.monthly.avg_solar_mw}
            labels={MONTHS.map(m => m[0])}
            colors="#ff9800"
            tooltip={(v, i) => `${MONTHS[i]}: ${v} MW`}
          />
        </>
      )}
    </MetricCard>
  );
}
