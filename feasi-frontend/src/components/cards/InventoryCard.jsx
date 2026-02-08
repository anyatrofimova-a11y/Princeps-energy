import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";

export default function InventoryCard() {
  const { siteBom, bomAvail, layoutMode, customBom } = useSite();

  if (layoutMode && customBom) {
    return (
      <MetricCard title="BOM" accentColor="#e65100" headerValue={`GBP ${customBom.totals?.total_cost_gbp?.toLocaleString()}`}>
        <div className="section-label">Custom Layout — {customBom.layout_item_count} placed, {customBom.unique_components} types</div>
        <div className="stat-grid">
          <div>Total cost: <strong>GBP {customBom.totals?.total_cost_gbp?.toLocaleString()}</strong></div>
          <div>Weight: <strong>{(customBom.totals?.total_weight_kg / 1000)?.toFixed(1)} t</strong></div>
        </div>
        {customBom.bom?.map(item => (
          <div key={item.component_id} className="stat-inline">
            {item.name}: <strong>{item.quantity}</strong> {item.unit} — GBP {item.total_cost_gbp?.toLocaleString()}
          </div>
        ))}
      </MetricCard>
    );
  }

  if (!siteBom) {
    return (
      <MetricCard title="BOM" accentColor="#e65100">
        <span className="muted">Click Analyse</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="BOM"
      accentColor="#e65100"
      headerValue={`GBP ${siteBom.totals?.total_cost_gbp?.toLocaleString()}`}
    >
      <div className="section-label">Site BOM — {siteBom.capacity_kw} kW</div>
      <div className="stat-grid">
        <div>Panels: <strong>{siteBom.num_panels}</strong></div>
        <div>Inverters: <strong>{siteBom.num_inverters}</strong></div>
      </div>
      <div className="stat-grid">
        <div>Total cost: <strong>GBP {siteBom.totals?.total_cost_gbp?.toLocaleString()}</strong></div>
        <div>Cost/kW: <strong>GBP {siteBom.totals?.cost_per_kw_gbp}</strong></div>
      </div>
      {bomAvail && (
        <>
          <div className="section-label">Supply Chain</div>
          <div className="stat-grid">
            <div>Fulfilment: <strong>{bomAvail.summary?.fulfilment_pct}%</strong></div>
            <div>Nearest: <strong>{bomAvail.nearest_distance_km} km</strong></div>
          </div>
        </>
      )}
    </MetricCard>
  );
}
