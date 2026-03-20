import React, { useState, useEffect, useCallback } from "react";
import api from "../services/api";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export default function BIPVPanel({ parcelId, samCapacity }) {
  const [catalogue, setCatalogue] = useState(null);
  const [moduleType, setModuleType] = useState("mono_roof_tile");
  const [surfaceType, setSurfaceType] = useState("pitched_roof_south");
  const [area, setArea] = useState(100);
  const [annual, setAnnual] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [date, setDate] = useState("2025-06-21");

  // Fetch catalogue on mount
  useEffect(() => {
    api.bipv.catalogue()
      .then((d) => { if (d) setCatalogue(d); })
      .catch(() => {});
  }, []);

  const runAnalysis = useCallback(async () => {
    if (!parcelId) return;
    setLoading(true);
    try {
      const [annRes, profRes] = await Promise.allSettled([
        api.bipv.annual(parcelId, area, moduleType, surfaceType),
        api.bipv.profile(parcelId, date, area, moduleType, surfaceType),
      ]);
      if (annRes.status === "fulfilled" && annRes.value)
        setAnnual(annRes.value);
      if (profRes.status === "fulfilled" && profRes.value)
        setProfile(profRes.value);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [parcelId, area, moduleType, surfaceType, date]);

  const mod = catalogue?.modules?.[moduleType];

  return (
    <div>
      {/* Controls */}
      <div className="bipv-controls">
        <div className="bipv-ctrl-row">
          <label>
            Module
            <select value={moduleType} onChange={(e) => setModuleType(e.target.value)}>
              {catalogue &&
                Object.entries(catalogue.modules).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.name} ({(v.efficiency * 100).toFixed(0)}%)
                  </option>
                ))}
            </select>
          </label>
          <label>
            Surface
            <select value={surfaceType} onChange={(e) => setSurfaceType(e.target.value)}>
              {catalogue &&
                Object.entries(catalogue.surface_types).map(([k, v]) => (
                  <option key={k} value={k}>
                    {k.replace(/_/g, " ")} ({v.tilt_deg}° tilt)
                  </option>
                ))}
            </select>
          </label>
        </div>
        <div className="bipv-ctrl-row">
          <label>
            Area
            <input
              type="number"
              value={area}
              onChange={(e) => setArea(Number(e.target.value))}
              min={1}
              style={{ width: 60 }}
            />
            m²
          </label>
          <label>
            Date
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              style={{ width: 110 }}
            />
          </label>
          <button onClick={runAnalysis} disabled={loading || !parcelId}>
            {loading ? "..." : "Analyse"}
          </button>
        </div>
      </div>

      {/* Module info */}
      {mod && (
        <div className="bipv-module-info">
          <span className="bipv-module-name">{mod.name}</span>
          <span className="bipv-module-meta">
            {(mod.efficiency * 100).toFixed(0)}% eff | GBP {mod.cost_gbp_m2}/m² |{" "}
            {mod.weight_kg_m2} kg/m²
          </span>
          <span className="bipv-module-desc">{mod.description}</span>
        </div>
      )}

      {/* Annual results */}
      {annual && (
        <>
          <div className="section-label">Annual Estimate</div>
          <div className="stat-grid">
            <div>
              Generation: <strong>{annual.annual_kwh?.toLocaleString()} kWh/yr</strong>
            </div>
            <div>
              Peak: <strong>{annual.peak_capacity_kw} kWp</strong>
            </div>
          </div>
          <div className="stat-grid">
            <div>
              Install: <strong>GBP {annual.install_cost_gbp?.toLocaleString()}</strong>
            </div>
            <div>
              Payback: <strong>{annual.payback_years} yrs</strong>
            </div>
          </div>
          <div className="stat-grid">
            <div>
              Export: <strong>GBP {annual.annual_export_revenue_gbp}/yr</strong>
            </div>
            <div>
              Self-use: <strong>GBP {annual.annual_self_consumption_savings_gbp}/yr</strong>
            </div>
          </div>
          <div className="stat-inline">
            CO₂ avoided: <strong>{annual.co2_avoided_kg_yr?.toLocaleString()} kg/yr</strong> |
            Total benefit: <strong>GBP {annual.total_annual_benefit_gbp}/yr</strong>
          </div>

          {/* Monthly bar chart */}
          {annual.monthly_kwh && (
            <>
              <div className="section-label">Monthly Generation (kWh)</div>
              <div className="bar-chart">
                {annual.monthly_kwh.map((v, i) => {
                  const max = Math.max(...annual.monthly_kwh) || 1;
                  return (
                    <div
                      key={i}
                      className="bar"
                      title={`${MONTHS[i]}: ${v.toLocaleString()} kWh`}
                      style={{
                        height: `${(v / max) * 100}%`,
                        background: "#00bcd4",
                      }}
                    />
                  );
                })}
              </div>
              <div className="bar-labels">
                {MONTHS.map((m) => (
                  <span key={m}>{m[0]}</span>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* 24h profile */}
      {profile && (
        <>
          <div className="section-label">
            24h Power Profile — {date} (peak: {profile.peak_power_w}W at{" "}
            {profile.peak_hour}:00)
          </div>
          <div className="bar-chart small">
            {profile.hourly_power_w?.map((v, i) => {
              const max = Math.max(...profile.hourly_power_w) || 1;
              return (
                <div
                  key={i}
                  className="bar"
                  title={`${i}:00 ${v.toFixed(1)}W`}
                  style={{
                    height: `${(v / max) * 100}%`,
                    background: v > 0 ? "#00bcd4" : "#ddd",
                    minHeight: v > 0 ? 2 : 1,
                  }}
                />
              );
            })}
          </div>
          <div className="stat-inline">
            Daily: <strong>{profile.daily_energy_kwh} kWh</strong>
          </div>
        </>
      )}

      {!annual && !loading && (
        <span className="muted">Configure BIPV parameters and click Analyse</span>
      )}
    </div>
  );
}
