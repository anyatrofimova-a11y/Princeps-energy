import React, { useState, useEffect, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/**
 * FinancialStrip — persistent bottom strip on the map showing live economics.
 * Updates whenever capacity, technology, or site changes.
 * Inspired by Aurora Solar's real-time metrics during design.
 */

const TECH_LABELS = { solar: "Solar", wind: "Wind", bess: "BESS", offshore_wind: "Offshore" };

function fmtGbp(v) {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return `£${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
}

export default function FinancialStrip() {
  const { samCapacity, solarYield, gridContext, parcelId, placedAssets } = useSite();
  const [data, setData] = useState(null);
  const [tech, setTech] = useState("solar");

  const capacityMw = useMemo(() => {
    // Use placed assets total if available, else SAM capacity
    const assetMw = placedAssets?.reduce((s, a) => s + (a.mw || 0), 0) || 0;
    return assetMw > 0 ? assetMw : (samCapacity || 100) / 1000;
  }, [samCapacity, placedAssets]);

  // Auto-detect technology from placed assets
  useEffect(() => {
    if (!placedAssets?.length) return;
    const types = placedAssets.map(a => a.assetType);
    if (types.includes("wind_turbine")) setTech("wind");
    else if (types.includes("bess") && !types.includes("solar_array")) setTech("bess");
    else setTech("solar");
  }, [placedAssets]);

  useEffect(() => {
    if (capacityMw <= 0) return;
    api.energy.npv(capacityMw, tech).then(d => { if (d) setData(d); });
  }, [capacityMw, tech]);

  if (!parcelId && !placedAssets?.length) return null;
  if (!data) return null;

  const irr = data.irr_pct;
  const irrColor = irr >= 10 ? "#16a34a" : irr >= 6 ? "#D4A018" : "#8B3A3A";
  const gridDist = gridContext?.nearest_substation?.distance_km;
  const gridCost = gridDist ? gridDist * 150000 : null;

  return (
    <div className="financial-strip">
      {/* Tech toggle */}
      <div className="fstrip-tech">
        {Object.entries(TECH_LABELS).map(([id, label]) => (
          <button
            key={id}
            className={`fstrip-tech-btn ${tech === id ? "active" : ""}`}
            onClick={() => setTech(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="fstrip-divider" />

      {/* Capacity */}
      <div className="fstrip-metric">
        <span className="fstrip-value">{capacityMw.toFixed(0)}</span>
        <span className="fstrip-label">MW</span>
      </div>

      {/* IRR */}
      <div className="fstrip-metric fstrip-hero">
        <span className="fstrip-value" style={{ color: irrColor }}>{irr?.toFixed(1)}%</span>
        <span className="fstrip-label">IRR</span>
      </div>

      {/* NPV */}
      <div className="fstrip-metric">
        <span className="fstrip-value" style={{ color: data.npv_gbp > 0 ? "#16a34a" : "#8B3A3A" }}>
          {fmtGbp(data.npv_gbp)}
        </span>
        <span className="fstrip-label">NPV</span>
      </div>

      {/* LCOE */}
      <div className="fstrip-metric">
        <span className="fstrip-value" style={{ color: "#D4A018" }}>£{data.lcoe_gbp_mwh?.toFixed(0)}</span>
        <span className="fstrip-label">LCOE</span>
      </div>

      {/* Payback */}
      <div className="fstrip-metric">
        <span className="fstrip-value">{data.payback_years?.toFixed(1)}</span>
        <span className="fstrip-label">Payback yr</span>
      </div>

      <div className="fstrip-divider" />

      {/* Generation */}
      <div className="fstrip-metric">
        <span className="fstrip-value">{data.annual_yield_mwh ? `${(data.annual_yield_mwh / 1000).toFixed(1)}` : "—"}</span>
        <span className="fstrip-label">GWh/yr</span>
      </div>

      {/* CF */}
      <div className="fstrip-metric">
        <span className="fstrip-value">{data.capacity_factor_pct?.toFixed(1)}%</span>
        <span className="fstrip-label">CF</span>
      </div>

      {/* Grid cost */}
      {gridCost && (
        <div className="fstrip-metric">
          <span className="fstrip-value" style={{ color: "#0891b2" }}>{fmtGbp(gridCost)}</span>
          <span className="fstrip-label">Grid</span>
        </div>
      )}

      {/* CAPEX */}
      <div className="fstrip-metric">
        <span className="fstrip-value">{fmtGbp(data.total_capex_gbp)}</span>
        <span className="fstrip-label">CAPEX</span>
      </div>
    </div>
  );
}
