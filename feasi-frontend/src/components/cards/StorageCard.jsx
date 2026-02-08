import React, { useState } from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";

export default function StorageCard() {
  const { agilePricing, demandForecast } = useSite();
  const [batteryKwh, setBatteryKwh] = useState(13.5); // Tesla Powerwall default

  const cheapest = agilePricing?.cheapest_windows?.[0];
  const peak = agilePricing?.peak_windows?.[0];

  // Client-side arbitrage calc
  const arbitrage = cheapest && peak ? {
    buyPrice: cheapest.avg_price_pence,
    sellPrice: peak.avg_price_pence,
    spreadPence: (peak.avg_price_pence - cheapest.avg_price_pence).toFixed(1),
    dailyProfit: ((peak.avg_price_pence - cheapest.avg_price_pence) * batteryKwh / 100).toFixed(2),
    annualProfit: (((peak.avg_price_pence - cheapest.avg_price_pence) * batteryKwh / 100) * 365).toFixed(0),
  } : null;

  const heroValue = cheapest ? `Charge at ${cheapest.avg_price_pence}p` : null;

  const storageOpt = demandForecast?.storage_optimization;

  return (
    <MetricCard
      title="Storage Intelligence"
      accentColor="#00bcd4"
      headerValue={heroValue}
    >
      {/* Arbitrage Calculator */}
      {arbitrage && (
        <>
          <div className="section-label">Battery Arbitrage</div>
          <div className="inline-controls">
            <label>Battery <input type="number" value={batteryKwh} onChange={e => setBatteryKwh(Number(e.target.value))} style={{ width: 50 }} min={1} /> kWh</label>
          </div>
          <div className="stat-grid">
            <div>Buy: <strong style={{ color: "#4caf50" }}>{arbitrage.buyPrice}p</strong> ({cheapest.start?.slice(11, 16)})</div>
            <div>Sell: <strong style={{ color: "#f44336" }}>{arbitrage.sellPrice}p</strong> ({peak.start?.slice(11, 16)})</div>
          </div>
          <div className="stat-grid">
            <div>Spread: <strong>{arbitrage.spreadPence}p/kWh</strong></div>
            <div>Daily: <strong style={{ color: "#4caf50" }}>GBP {arbitrage.dailyProfit}</strong></div>
          </div>
          <div className="stat-inline">Annual estimate: <strong>GBP {arbitrage.annualProfit}</strong></div>
        </>
      )}

      {/* Charge/Export Timeline — 24h with cheap (green) and peak (red) zones */}
      {agilePricing?.prices && (
        <>
          <div className="section-label">24h Price Timeline</div>
          <BarChart
            data={agilePricing.prices.slice(-48).map(p => Math.max(p.price_pence, 0))}
            height="small"
            colors={(_, i) => {
              const p = agilePricing.prices.slice(-48)[i];
              if (!p) return "#666";
              return p.price_pence < 10 ? "#4caf50" : p.price_pence < 20 ? "#8bc34a" : p.price_pence < 30 ? "#ff9800" : "#f44336";
            }}
            tooltip={(_, i) => {
              const p = agilePricing.prices.slice(-48)[i];
              return p ? `${p.valid_from?.slice(11, 16)} ${p.price_pence}p/kWh` : "";
            }}
          />
        </>
      )}

      {/* 2050 Storage Optimization */}
      {storageOpt && (
        <>
          <div className="layer-divider" />
          <div className="section-label">2050 Storage Optimization</div>
          <div className="stat-grid">
            <div>Optimal: <strong>{storageOpt.optimal.renewable_gw} GW</strong></div>
            <div>Adequacy: <strong style={{ color: storageOpt.optimal.adequacy_pct >= 99 ? "#4caf50" : "#ff9800" }}>{storageOpt.optimal.adequacy_pct}%</strong></div>
          </div>
          <div className="stat-grid">
            <div>Cost: <strong>GBP {storageOpt.optimal.cost_bn_gbp_yr} bn/yr</strong></div>
            <div>LCOE: <strong>{storageOpt.optimal.lcoe_gbp_mwh} GBP/MWh</strong></div>
          </div>
          <BarChart
            data={storageOpt.scenarios?.map(s => s.cost_bn_gbp_yr) || []}
            labels={storageOpt.scenarios?.map(s => String(s.renewable_gw)) || []}
            height="small"
            colors={(_, i) => {
              const s = storageOpt.scenarios?.[i];
              if (!s) return "#666";
              const isOptimal = s.renewable_gw === storageOpt.optimal.renewable_gw;
              return isOptimal ? "#4caf50" : s.adequacy_pct < 99 ? "#f44336" : "#7c4dff";
            }}
            tooltip={(_, i) => {
              const s = storageOpt.scenarios?.[i];
              return s ? `${s.renewable_gw}GW: GBP${s.cost_bn_gbp_yr}bn, ${s.adequacy_pct}% adequate` : "";
            }}
          />
        </>
      )}

      {!arbitrage && !storageOpt && <span className="muted">Loading storage data...</span>}
    </MetricCard>
  );
}
