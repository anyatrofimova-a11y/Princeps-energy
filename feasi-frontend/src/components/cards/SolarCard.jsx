import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export default function SolarCard() {
  const { solarYield, solarHourly, mlSolar, samDay } = useSite();

  if (!solarYield) {
    return (
      <MetricCard title="Solar" accentColor="#ff9800">
        <span className="muted">No solar data</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Solar"
      accentColor="#ff9800"
      headerValue={`${solarYield.annual_energy_kwh?.toLocaleString()} kWh/yr`}
    >
      <div className="stat-grid">
        <div><strong>{solarYield.annual_energy_kwh?.toLocaleString()}</strong> kWh/yr</div>
        <div><strong>{solarYield.capacity_factor_pct}%</strong> CF</div>
      </div>
      {solarYield.monthly_energy_kwh && (
        <BarChart
          data={solarYield.monthly_energy_kwh}
          labels={MONTHS.map(m => m[0])}
          colors="#4caf50"
          tooltip={(v, i) => `${MONTHS[i]}: ${v.toLocaleString()} kWh`}
        />
      )}
      {solarHourly?.hourly_kw && (
        <>
          <div className="section-label">SAM 24h (day {samDay})</div>
          <BarChart
            data={solarHourly.hourly_kw}
            height="small"
            colors={(v) => v > 0 ? "#ff9800" : "#ddd"}
            tooltip={(v, i) => `${i}:00 ${v.toFixed(1)} kW`}
          />
          <div className="stat-inline">Daily: <strong>{solarHourly.daily_total_kwh} kWh</strong></div>
        </>
      )}
      {mlSolar?.hourly_kwh && (
        <>
          <div className="section-label">ML 24h (GBM)</div>
          <BarChart
            data={mlSolar.hourly_kwh}
            height="small"
            colors={(v) => v > 0 ? "#9c27b0" : "#ddd"}
            tooltip={(v, i) => `${i}:00 ${v.toFixed(2)} kWh`}
          />
          <div className="stat-inline">ML daily: <strong>{mlSolar.daily_total_kwh} kWh</strong> | annual est: {mlSolar.annual_estimate_kwh?.toLocaleString()} kWh</div>
        </>
      )}
    </MetricCard>
  );
}
