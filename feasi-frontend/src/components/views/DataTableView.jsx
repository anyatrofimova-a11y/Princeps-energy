import React from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";

export default function DataTableView() {
  const { activeWorkspace } = useWorkspace();
  const {
    solarYield, gridContext, explain, planningApps,
    energyPrice, deferral, slopeStats,
  } = useSite();

  // Collect available data rows based on workspace
  const rows = [];

  if (activeWorkspace === "feasibility" || activeWorkspace === "home") {
    if (explain) {
      rows.push({ label: "Site Score", value: explain.score_total?.toFixed(1) || "--", unit: "/100" });
      rows.push({ label: "Latitude", value: explain.lat?.toFixed(5) || "--" });
      rows.push({ label: "Longitude", value: explain.lon?.toFixed(5) || "--" });
    }
    if (solarYield) {
      rows.push({ label: "Annual Energy", value: solarYield.annual_energy_kwh ? `${(solarYield.annual_energy_kwh / 1000).toFixed(0)}` : "--", unit: "MWh" });
      rows.push({ label: "Capacity Factor", value: solarYield.capacity_factor_pct?.toFixed(1) || "--", unit: "%" });
    }
    if (slopeStats) {
      rows.push({ label: "Mean Slope", value: slopeStats.mean_slope_deg?.toFixed(1) || "--", unit: "deg" });
      rows.push({ label: "Max Slope", value: slopeStats.max_slope_deg?.toFixed(1) || "--", unit: "deg" });
    }
  }

  if (activeWorkspace === "grid" || activeWorkspace === "home") {
    if (gridContext?.nearest_substation) {
      const sub = gridContext.nearest_substation;
      rows.push({ label: "Nearest Substation", value: sub.name || "--" });
      rows.push({ label: "Grid Distance", value: sub.distance_km?.toFixed(1) || "--", unit: "km" });
      rows.push({ label: "Voltage", value: sub.voltage || "--", unit: "kV" });
    }
  }

  if ((activeWorkspace === "feasibility" || activeWorkspace === "home") && energyPrice) {
    rows.push({ label: "Revenue (yr 1)", value: energyPrice.annual_revenue ? `${(energyPrice.annual_revenue).toFixed(0)}` : "--", unit: "GBP" });
    rows.push({ label: "LCOE", value: energyPrice.lcoe?.toFixed(1) || "--", unit: "p/kWh" });
  }

  if (activeWorkspace === "environment" && planningApps?.applications) {
    rows.push({ label: "Planning Apps", value: planningApps.applications.length || "0" });
  }

  if (rows.length === 0) {
    return (
      <div className="data-table-view">
        <div className="dtv-empty">No site data loaded. Select a site to view data.</div>
      </div>
    );
  }

  return (
    <div className="data-table-view">
      <table className="dtv-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Value</th>
            <th>Unit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>{row.label}</td>
              <td className="dtv-value">{row.value}</td>
              <td className="dtv-unit">{row.unit || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
