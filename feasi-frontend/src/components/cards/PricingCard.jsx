import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";
import AgileSlotGrid from "./AgileSlotGrid";

export default function PricingCard() {
  const { demandForecast, agilePricing, energyPrice } = useSite();

  const currentPrice = agilePricing?.current_price_pence;
  const heroValue = currentPrice != null ? `${currentPrice}p/kWh` :
    demandForecast?.current_demand_mw ? `${demandForecast.current_demand_mw.toLocaleString()} MW` : null;

  return (
    <MetricCard
      title="Price & Demand"
      accentColor="#7c4dff"
      headerValue={heroValue}
    >
      {/* Demand Forecast */}
      {demandForecast && (
        <>
          <div className="stat-grid">
            <div>Now: <strong style={{ color: demandForecast.current_status === "red" ? "#f44336" : demandForecast.current_status === "amber" ? "#ff9800" : "#4caf50" }}>{demandForecast.current_demand_mw?.toLocaleString()} MW</strong></div>
            <div>Status: <strong style={{ color: demandForecast.current_status === "red" ? "#f44336" : demandForecast.current_status === "amber" ? "#ff9800" : "#4caf50" }}>{demandForecast.current_status?.toUpperCase()}</strong></div>
          </div>
          <div className="section-label">24h Demand Forecast</div>
          <BarChart
            data={demandForecast.forecast_24h?.hourly?.map(h => h.demand_mw) || []}
            height="small"
            colors={(_, i) => {
              const h = demandForecast.forecast_24h?.hourly?.[i];
              if (!h) return "#7c4dff";
              return h.status === "red" ? "#f44336" : h.status === "amber" ? "#ff9800" : h.is_actual ? "#2196f3" : "#7c4dff";
            }}
            opacity={(_, i) => {
              const h = demandForecast.forecast_24h?.hourly?.[i];
              return h?.is_actual ? 1 : 0.7;
            }}
            tooltip={(_, i) => {
              const h = demandForecast.forecast_24h?.hourly?.[i];
              return h ? `${h.hour}:00 ${h.demand_mw.toLocaleString()} MW ${h.is_actual ? "(actual)" : "(forecast)"}` : "";
            }}
          />
          <div className="stat-grid">
            <div>Peak: <strong>{demandForecast.forecast_24h?.peak_mw?.toLocaleString()} MW</strong> at {demandForecast.forecast_24h?.peak_hour}:00</div>
            <div>Trough: <strong>{demandForecast.forecast_24h?.trough_mw?.toLocaleString()} MW</strong></div>
          </div>
          <div className="section-label">7-Day Forecast</div>
          <BarChart
            data={demandForecast.forecast_7d?.daily?.map(d => d.peak_mw) || []}
            labels={demandForecast.forecast_7d?.daily?.map(d => d.day_name?.slice(0, 2)) || []}
            colors={(_, i) => {
              const d = demandForecast.forecast_7d?.daily?.[i];
              return d?.status === "red" ? "#f44336" : d?.status === "amber" ? "#ff9800" : "#7c4dff";
            }}
            tooltip={(_, i) => {
              const d = demandForecast.forecast_7d?.daily?.[i];
              return d ? `${d.day_name}: peak ${d.peak_mw.toLocaleString()} MW` : "";
            }}
          />
        </>
      )}

      {/* Agile Pricing */}
      {agilePricing && (
        <>
          <div className="layer-divider" />
          <div className="section-label">Octopus Agile — {agilePricing.region_name}</div>
          <div className="stat-grid">
            <div>Now: <strong style={{ color: currentPrice > 30 ? "#f44336" : currentPrice < 15 ? "#4caf50" : "#ff9800" }}>{currentPrice}p/kWh</strong></div>
            <div>Avg: <strong>{agilePricing.stats?.avg_pence}p</strong></div>
          </div>

          {/* Octopus-style slot grid */}
          {agilePricing.heatmap && <AgileSlotGrid heatmap={agilePricing.heatmap} />}

          <div className="stat-grid">
            <div>Min: <strong style={{ color: "#4caf50" }}>{agilePricing.stats?.min_pence}p</strong></div>
            <div>Max: <strong style={{ color: "#f44336" }}>{agilePricing.stats?.max_pence}p</strong></div>
          </div>
          {agilePricing.cheapest_windows?.[0] && (
            <div className="stat-inline">Best charge: <strong>{agilePricing.cheapest_windows[0].avg_price_pence}p</strong> at {agilePricing.cheapest_windows[0].start?.slice(11, 16)}</div>
          )}
          {agilePricing.peak_windows?.[0] && (
            <div className="stat-inline">Best export: <strong>{agilePricing.peak_windows[0].avg_price_pence}p</strong> at {agilePricing.peak_windows[0].start?.slice(11, 16)}</div>
          )}
        </>
      )}

      {/* Site Revenue */}
      {energyPrice && (
        <>
          <div className="layer-divider" />
          <div className="section-label">Site Revenue Estimate</div>
          <div className="stat-grid">
            <div>Avg: <strong>{energyPrice.price?.daily_avg}</strong> GBP/MWh</div>
            <div>Peak: <strong>{energyPrice.price?.peak_price}</strong> at {energyPrice.price?.peak_hour}:00</div>
          </div>
          {energyPrice.revenue && (
            <>
              <div className="stat-grid">
                <div>Market: <strong>GBP {energyPrice.revenue.market_revenue_gbp}</strong>/day</div>
                <div>Fixed: <strong>GBP {energyPrice.revenue.fixed_tariff_revenue_gbp}</strong>/day</div>
              </div>
              <div className="stat-inline">Market premium: <strong>{energyPrice.revenue.premium_pct}%</strong> vs fixed SEG</div>
              <div className="stat-grid" style={{ marginTop: 6 }}>
                <div>Annual (market): <strong>GBP {energyPrice.revenue.annual_market_estimate_gbp?.toLocaleString()}</strong></div>
                <div>Annual (fixed): <strong>GBP {energyPrice.revenue.annual_fixed_estimate_gbp?.toLocaleString()}</strong></div>
              </div>
            </>
          )}
        </>
      )}

      {!demandForecast && !agilePricing && !energyPrice && <span className="muted">Loading pricing data...</span>}
    </MetricCard>
  );
}
