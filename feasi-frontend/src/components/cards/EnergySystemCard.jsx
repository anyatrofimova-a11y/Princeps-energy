import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";

export default function EnergySystemCard() {
  const { energySystem } = useSite();

  if (!energySystem) {
    return (
      <MetricCard title="2050 System" accentColor="#795548">
        <span className="muted">Click Analyse</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="2050 System"
      accentColor="#795548"
      headerValue={`${energySystem.site?.annual_generation_mwh?.toLocaleString()} MWh/yr`}
    >
      <div className="stat-grid">
        <div>Generation: <strong>{energySystem.site?.annual_generation_mwh?.toLocaleString()} MWh/yr</strong></div>
        <div>CF: <strong>{(energySystem.site?.capacity_factor * 100)?.toFixed(1)}%</strong></div>
      </div>
      <div className="stat-grid">
        <div>Homes powered: <strong>{energySystem.national_context?.homes_powered}</strong></div>
        <div>CO2 avoided: <strong>{energySystem.national_context?.co2_avoided_tonnes_yr} t/yr</strong></div>
      </div>
      <div className="section-label">Economics</div>
      <div className="stat-grid">
        <div>Solar LCOE: <strong>{energySystem.economics?.solar_lcoe_gbp_mwh}</strong> GBP/MWh</div>
        <div>System LCOE: <strong>{energySystem.economics?.system_lcoe_gbp_mwh}</strong> GBP/MWh</div>
      </div>
      <div className="stat-inline">
        Solar is <strong>{energySystem.economics?.solar_vs_system_lcoe_pct}%</strong> of system avg |
        Annual value: <strong>GBP {energySystem.economics?.annual_value_at_system_lcoe_gbp?.toLocaleString()}</strong>
      </div>
      <div className="section-label">2050 Scenario ({energySystem.scenario_summary?.renewable_capacity_gw} GW renewables)</div>
      <div className="stat-grid">
        <div>Demand: <strong>{energySystem.scenario_summary?.demand_twh} TWh</strong></div>
        <div>Generation: <strong>{energySystem.scenario_summary?.total_generation_twh} TWh</strong></div>
      </div>
      <div className="stat-inline">Total system cost: <strong>GBP {energySystem.scenario_summary?.total_cost_bn} bn/yr</strong></div>
    </MetricCard>
  );
}
