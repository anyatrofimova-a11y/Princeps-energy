import React, { useState, useEffect } from "react";
import api from "../../services/api";

function fmt(v, unit = "") {
  if (v == null || isNaN(v)) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}${unit}` : `${v.toFixed(v < 10 ? 2 : 1)}${unit}`;
}

export default function LiveMarketBar() {
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await api.liveGrid?.snapshot?.();
        if (d) setData(d);
      } catch {}
    };
    fetch();
    const iv = setInterval(fetch, 30000);
    return () => clearInterval(iv);
  }, []);

  const freq = data?.frequency ?? 50.0;
  const freqColor = Math.abs(freq - 50) > 0.05 ? "#dc2626" : "#22c55e";
  const carbon = data?.carbon_intensity;
  const carbonColor = carbon > 250 ? "#dc2626" : carbon > 150 ? "#d97706" : "#22c55e";

  return (
    <div className="pd2-market-bar">
      <div className="pd2-live-dot" />
      <span style={{ fontWeight: 600, color: "#374151", fontSize: 11 }}>LIVE</span>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span>GB Demand</span>
        <span className="pd2-market-value">{fmt(data?.demand_gw || data?.demand_mw / 1000)} GW</span>
      </div>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span>Wind</span>
        <span className="pd2-market-value">{fmt(data?.wind_gw || data?.wind_mw / 1000)} GW</span>
        {data?.wind_pct != null && <span style={{ color: "#22c55e" }}>({data.wind_pct.toFixed(0)}%)</span>}
      </div>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span>Solar</span>
        <span className="pd2-market-value">{fmt(data?.solar_gw || data?.solar_mw / 1000)} GW</span>
      </div>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span>CO₂</span>
        <span className="pd2-market-value" style={{ color: carbonColor }}>{carbon?.toFixed(0) ?? "—"}</span>
        <span>gCO₂/kWh</span>
      </div>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span className="pd2-market-value" style={{ color: freqColor }}>{freq.toFixed(2)}</span>
        <span>Hz</span>
      </div>
      <div className="pd2-market-sep" />

      <div className="pd2-market-item">
        <span>Price</span>
        <span className="pd2-market-value">£{data?.price_gbp_mwh?.toFixed(0) ?? "—"}</span>
        <span>/MWh</span>
      </div>
    </div>
  );
}
