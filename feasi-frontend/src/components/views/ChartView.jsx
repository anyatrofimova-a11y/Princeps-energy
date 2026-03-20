import React from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";

// Simple SVG bar chart
function BarChart({ data, label, color = "var(--cds-interactive)", height = 200 }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data.map(d => d.value));
  const barW = Math.min(40, Math.floor(600 / data.length) - 4);

  return (
    <div className="cv-chart-block">
      <div className="cv-chart-label">{label}</div>
      <svg width="100%" height={height} viewBox={`0 0 ${data.length * (barW + 4) + 20} ${height}`}>
        {data.map((d, i) => {
          const barH = max > 0 ? (d.value / max) * (height - 30) : 0;
          return (
            <g key={i}>
              <rect
                x={i * (barW + 4) + 10}
                y={height - 20 - barH}
                width={barW}
                height={barH}
                fill={color}
                opacity={0.8}
                rx={2}
              />
              <text
                x={i * (barW + 4) + 10 + barW / 2}
                y={height - 6}
                textAnchor="middle"
                fill="var(--cds-text-helper)"
                fontSize="8"
                fontFamily="var(--mono)"
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default function ChartView() {
  const { activeWorkspace } = useWorkspace();
  const { solarHourly, solarYield, demandForecast } = useSite();

  const charts = [];

  // Solar hourly production
  if ((activeWorkspace === "analyse" || activeWorkspace === "home") && solarHourly?.hours) {
    const data = solarHourly.hours.map((h, i) => ({
      label: `${i}`,
      value: h.generation_kwh || 0,
    }));
    charts.push(
      <BarChart key="solar-hourly" data={data} label="Hourly Solar Generation (kWh)" color="#f59e0b" height={180} />
    );
  }

  // Monthly yield
  if ((activeWorkspace === "analyse" || activeWorkspace === "home") && solarYield?.monthly_kwh) {
    const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
    const data = solarYield.monthly_kwh.map((v, i) => ({
      label: months[i],
      value: v,
    }));
    charts.push(
      <BarChart key="solar-monthly" data={data} label="Monthly Solar Yield (kWh)" color="var(--cds-interactive)" />
    );
  }

  // Demand forecast
  if ((activeWorkspace === "analyse" || activeWorkspace === "home") && demandForecast?.forecast) {
    const data = demandForecast.forecast.slice(0, 48).map((v, i) => ({
      label: i % 6 === 0 ? `${i}` : "",
      value: v.demand_mw || 0,
    }));
    charts.push(
      <BarChart key="demand" data={data} label="Demand Forecast (MW)" color="#fa8c16" height={160} />
    );
  }

  if (charts.length === 0) {
    return (
      <div className="chart-view">
        <div className="cv-empty">No chart data available. Select a site to view charts.</div>
      </div>
    );
  }

  return (
    <div className="chart-view">
      {charts}
    </div>
  );
}
