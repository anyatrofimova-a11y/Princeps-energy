import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";

const BUILDING_TYPES = [
  { value: "office", label: "Office" },
  { value: "institute", label: "Institute" },
  { value: "institute_large", label: "Institute (Large)" },
  { value: "detached_house", label: "Detached House" },
  { value: "terraced_house", label: "Terraced House" },
  { value: "apartment_block", label: "Apartment Block" },
];

const EPC_COLORS = { A: "#00b050", B: "#4dc26b", C: "#99d98c", D: "#ffcc00", E: "#ff9933", F: "#ff5050", G: "#cc0000" };

function fmtN(v, d = 0) {
  if (v == null) return "--";
  return v.toLocaleString("en-GB", { maximumFractionDigits: d });
}

function BarChart({ data, valueKey, label, color = "#7c5cfc", maxVal }) {
  const max = maxVal || Math.max(...data.map(d => d[valueKey] || 0), 1);
  return (
    <div style={{ display: "flex", gap: 1, alignItems: "end", height: 60 }}>
      {data.map((d, i) => {
        const v = d[valueKey] || 0;
        const h = (v / max) * 56;
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{
              width: "100%", maxWidth: 14, height: h, borderRadius: "2px 2px 0 0",
              background: v > 0 ? color : "transparent", minHeight: v > 0 ? 2 : 0,
            }} title={`${d.hour}:00 — ${v.toFixed(1)} kW`} />
            {i % 4 === 0 && (
              <div style={{ fontSize: 8, color: "var(--cds-text-helper, #a8a8a8)", marginTop: 2 }}>
                {d.hour}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ZoneCard({ zone, expanded, onToggle }) {
  const uc = zone.use_conditions;
  return (
    <div style={{
      background: "var(--cds-layer-01, #262626)", borderRadius: 8,
      border: "1px solid var(--cds-border-subtle, #393939)",
      padding: "8px 12px", marginBottom: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }} onClick={onToggle}>
        <div style={{
          width: 8, height: 8, borderRadius: "50%",
          background: uc?.with_heating ? "#f59e0b" : "#525252",
        }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)" }}>
            {zone.name}
          </div>
          <div style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)" }}>
            {fmtN(zone.area_m2)} m² &middot; {fmtN(zone.volume_m3)} m³
          </div>
        </div>
        <div style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)" }}>
          WWR {(zone.window_to_wall_ratio * 100).toFixed(0)}%
        </div>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--cds-border-subtle, #393939)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "4px 8px", fontSize: 10 }}>
            <D label="Outer Wall" value={`${fmtN(zone.outer_wall_area_m2)} m²`} />
            <D label="Windows" value={`${fmtN(zone.window_area_m2)} m²`} />
            <D label="Roof" value={`${fmtN(zone.roof_area_m2)} m²`} />
            <D label="Floor" value={`${fmtN(zone.ground_floor_area_m2)} m²`} />
            <D label="Inner Wall" value={`${fmtN(zone.inner_wall_area_m2)} m²`} />
            <D label="WWR" value={`${(zone.window_to_wall_ratio * 100).toFixed(1)}%`} />
          </div>
          {uc && (
            <div style={{ marginTop: 6, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 8px", fontSize: 10 }}>
              <D label="Usage" value={uc.usage} />
              <D label="Persons" value={`${uc.persons_per_m2}/m²`} />
              <D label="Equipment" value={`${uc.machines_w_m2} W/m²`} />
              <D label="Lighting" value={`${uc.lighting_w_m2} W/m²`} />
              <D label="Infiltration" value={`${uc.base_infiltration_1_h} /h`} />
              <D label="Heat threshold" value={`${uc.T_threshold_heating_C}°C`} />
            </div>
          )}
          {zone.rc_model && (
            <div style={{ marginTop: 6, fontSize: 9, color: "var(--cds-text-helper, #a8a8a8)" }}>
              RC: R₁ᵢ={zone.rc_model.r1_inner_wall_K_W.toFixed(6)} K/W, C₁ᵢ={fmtN(zone.rc_model.c1_inner_wall_J_K)} J/K,
              R₁ₒ={zone.rc_model.r1_outer_wall_K_W.toFixed(6)} K/W, C₁ₒ={fmtN(zone.rc_model.c1_outer_wall_J_K)} J/K
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RetrofitTable({ scenarios }) {
  if (!scenarios?.length) return null;
  const baseline = scenarios[0];
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--cds-border-subtle, #393939)" }}>
            <th style={{ textAlign: "left", padding: "6px 8px", color: "var(--cds-text-secondary, #c6c6c6)" }}>Scenario</th>
            <th style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-secondary, #c6c6c6)" }}>kWh/m²/yr</th>
            <th style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-secondary, #c6c6c6)" }}>Cost/yr</th>
            <th style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-secondary, #c6c6c6)" }}>CO₂ t/yr</th>
            <th style={{ textAlign: "right", padding: "6px 8px", color: "var(--cds-text-secondary, #c6c6c6)" }}>Saving</th>
          </tr>
        </thead>
        <tbody>
          {scenarios.map((s, i) => (
            <tr key={i} style={{ borderBottom: "1px solid var(--cds-border-subtle, #393939)" }}>
              <td style={{ padding: "6px 8px", color: "var(--cds-text-primary, #f4f4f4)", fontWeight: i === 0 ? 600 : 400 }}>
                {s.name}
                <span style={{ fontSize: 9, color: "var(--cds-text-helper, #a8a8a8)", marginLeft: 4 }}>({s.year_equivalent})</span>
              </td>
              <td style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-primary, #f4f4f4)" }}>
                {fmtN(s.total_kwh_m2_yr, 1)}
              </td>
              <td style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-primary, #f4f4f4)" }}>
                \u00A3{fmtN(s.annual_cost_gbp)}
              </td>
              <td style={{ textAlign: "right", padding: "6px 4px", color: "var(--cds-text-primary, #f4f4f4)" }}>
                {fmtN(s.co2_tonnes_yr, 1)}
              </td>
              <td style={{
                textAlign: "right", padding: "6px 8px", fontWeight: 600,
                color: s.saving_pct > 0 ? "#10b981" : "var(--cds-text-secondary, #c6c6c6)",
              }}>
                {s.saving_pct > 0 ? `-${s.saving_pct}%` : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function D({ label, value }) {
  return (
    <div>
      <span style={{ color: "var(--cds-text-helper, #a8a8a8)" }}>{label}: </span>
      <span style={{ color: "var(--cds-text-primary, #f4f4f4)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

export default function ThermalModelPanel({ onClose }) {
  const { explain, samCapacity } = useSite();
  const [buildingType, setBuildingType] = useState("office");
  const [year, setYear] = useState(2000);
  const [floors, setFloors] = useState(3);
  const [floorHeight, setFloorHeight] = useState(3.5);
  const [area, setArea] = useState(2000);
  const [model, setModel] = useState(null);
  const [retrofit, setRetrofit] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("model"); // model | retrofit | zones
  const [expandedZone, setExpandedZone] = useState(null);

  const lat = explain?.lat ?? explain?.location?.lat ?? 52.5;

  const fetchModel = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        building_type: buildingType, year_of_construction: year,
        number_of_floors: floors, height_of_floors: floorHeight,
        net_leased_area: area, lat,
      });
      const [mRes, rRes] = await Promise.all([
        fetch(`/teaser/model?${params}`),
        fetch(`/teaser/retrofit?${params}`),
      ]);
      if (mRes.ok) setModel(await mRes.json());
      if (rRes.ok) setRetrofit(await rRes.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [buildingType, year, floors, floorHeight, area, lat]);

  useEffect(() => { fetchModel(); }, [fetchModel]);

  const ed = model?.energy_demand;

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0,
      width: 420, background: "var(--cds-background, #161616)",
      borderLeft: "1px solid var(--cds-border-subtle, #393939)",
      display: "flex", flexDirection: "column",
      zIndex: 1200, boxShadow: "-4px 0 24px rgba(0,0,0,0.5)",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: "#f59e0b22", color: "#f59e0b",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, fontWeight: 700,
        }}>{"\u2302"}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--cds-text-primary, #f4f4f4)" }}>
            Thermal Model
          </div>
          <div style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)" }}>
            TEASER building energy simulation
          </div>
        </div>
        <button onClick={onClose} style={{
          background: "none", border: "none", color: "var(--cds-text-secondary, #c6c6c6)",
          fontSize: 20, cursor: "pointer", padding: "0 4px",
        }}>&times;</button>
      </div>

      {/* Inputs */}
      <div style={{
        padding: "8px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, flexShrink: 0,
      }}>
        <div style={{ gridColumn: "1 / -1" }}>
          <Label>Building Type</Label>
          <select value={buildingType} onChange={e => setBuildingType(e.target.value)} style={inputStyle}>
            {BUILDING_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <Label>Year Built</Label>
          <input type="number" value={year} min={1850} max={2025} onChange={e => setYear(+e.target.value)} style={inputStyle} />
        </div>
        <div>
          <Label>Area (m²)</Label>
          <input type="number" value={area} min={10} step={100} onChange={e => setArea(+e.target.value)} style={inputStyle} />
        </div>
        <div>
          <Label>Floors</Label>
          <input type="number" value={floors} min={1} max={50} onChange={e => setFloors(+e.target.value)} style={inputStyle} />
        </div>
      </div>

      {/* Summary strip */}
      {ed && (
        <div style={{
          padding: "8px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
          display: "flex", gap: 12, flexShrink: 0, background: "var(--cds-layer-01, #262626)",
          alignItems: "center",
        }}>
          <Stat label="Heating" value={`${fmtN(ed.heating_kwh_m2_yr, 1)}`} unit="kWh/m²" color="#f59e0b" />
          <Stat label="Cooling" value={`${fmtN(ed.cooling_kwh_m2_yr, 1)}`} unit="kWh/m²" color="#3b82f6" />
          <Stat label="Total" value={`${fmtN(ed.total_kwh_m2_yr, 1)}`} unit="kWh/m²" />
          <Stat label="Cost" value={`\u00A3${fmtN(ed.annual_cost_gbp)}`} unit="/yr" />
          <div style={{
            background: EPC_COLORS[ed.epc_band_estimate] || "#888",
            color: "#000", fontWeight: 800, fontSize: 14,
            width: 28, height: 28, borderRadius: 4,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {ed.epc_band_estimate}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--cds-border-subtle, #393939)", flexShrink: 0 }}>
        {[
          { key: "model", label: "Energy" },
          { key: "zones", label: "Zones" },
          { key: "retrofit", label: "Retrofit" },
        ].map(tab => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  style={{
                    flex: 1, padding: "8px 0", fontSize: 11, fontWeight: 600,
                    background: "none", border: "none", cursor: "pointer",
                    color: activeTab === tab.key ? "#f59e0b" : "var(--cds-text-secondary, #c6c6c6)",
                    borderBottom: activeTab === tab.key ? "2px solid #f59e0b" : "2px solid transparent",
                  }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
        {loading && (
          <div style={{ textAlign: "center", padding: 40, color: "var(--cds-text-secondary, #c6c6c6)", fontSize: 12 }}>
            Generating thermal model...
          </div>
        )}

        {/* Energy tab */}
        {activeTab === "model" && model && !loading && (
          <>
            {/* Building info */}
            <Section title="Building">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", fontSize: 10 }}>
                <D label="Type" value={model.building.description} />
                <D label="Year" value={model.building.year_of_construction} />
                <D label="Area" value={`${fmtN(model.building.total_zone_area_m2)} m²`} />
                <D label="Volume" value={`${fmtN(model.building.total_volume_m3)} m³`} />
                <D label="Region" value={model.region.name} />
                <D label="HDD/CDD" value={`${model.region.hdd} / ${model.region.cdd}`} />
              </div>
            </Section>

            {/* Energy demand */}
            <Section title="Annual Energy Demand">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", fontSize: 10 }}>
                <D label="Heating" value={`${fmtN(ed.heating_kwh_yr)} kWh`} />
                <D label="Cooling" value={`${fmtN(ed.cooling_kwh_yr)} kWh`} />
                <D label="HLC" value={`${fmtN(ed.heat_loss_coefficient_W_K, 1)} W/K`} />
                <D label="Int. Gains" value={`${fmtN(ed.internal_gains_W)} W`} />
                <D label="Heating cost" value={`\u00A3${fmtN(ed.heating_cost_gbp)}/yr`} />
                <D label="Cooling cost" value={`\u00A3${fmtN(ed.cooling_cost_gbp)}/yr`} />
                <D label="CO₂" value={`${fmtN(ed.co2_tonnes_yr, 1)} tonnes/yr`} />
                <D label="EPC Band" value={ed.epc_band_estimate} />
              </div>
            </Section>

            {/* Hourly profile */}
            {model.hourly_profile && (
              <Section title="Typical Day Profile">
                <div style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 10, color: "#f59e0b", marginBottom: 2 }}>Heating (kW)</div>
                  <BarChart data={model.hourly_profile} valueKey="heating_kw" color="#f59e0b" />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#3b82f6", marginBottom: 2 }}>Cooling (kW)</div>
                  <BarChart data={model.hourly_profile} valueKey="cooling_kw" color="#3b82f6" />
                </div>
              </Section>
            )}
          </>
        )}

        {/* Zones tab */}
        {activeTab === "zones" && model && !loading && (
          <>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-secondary, #c6c6c6)", marginBottom: 8 }}>
              {model.zones?.length} Thermal Zones
            </div>
            {model.zones?.map((z, i) => (
              <ZoneCard key={i} zone={z}
                expanded={expandedZone === i}
                onToggle={() => setExpandedZone(expandedZone === i ? null : i)}
              />
            ))}
          </>
        )}

        {/* Retrofit tab */}
        {activeTab === "retrofit" && retrofit && !loading && (
          <>
            <Section title="Retrofit Scenario Comparison">
              <RetrofitTable scenarios={retrofit.scenarios} />
            </Section>

            {/* Savings chart */}
            {retrofit.scenarios?.length > 1 && (
              <Section title="Energy Reduction">
                {retrofit.scenarios.slice(1).map((s, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <div style={{ width: 100, fontSize: 10, color: "var(--cds-text-primary, #f4f4f4)" }}>
                      {s.name}
                    </div>
                    <div style={{ flex: 1, height: 16, background: "var(--cds-layer-01, #262626)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{
                        width: `${Math.min(100, s.saving_pct)}%`, height: "100%",
                        background: "linear-gradient(90deg, #10b981, #059669)",
                        borderRadius: 3, transition: "width 0.5s",
                      }} />
                    </div>
                    <div style={{ width: 50, textAlign: "right", fontSize: 11, fontWeight: 600, color: "#10b981" }}>
                      -{s.saving_pct}%
                    </div>
                  </div>
                ))}
              </Section>
            )}

            {/* Cost savings */}
            {retrofit.scenarios?.length > 1 && (
              <Section title="Annual Savings">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                  {retrofit.scenarios.slice(1).map((s, i) => (
                    <div key={i} style={{
                      background: "var(--cds-layer-01, #262626)", borderRadius: 6,
                      padding: 8, textAlign: "center",
                    }}>
                      <div style={{ fontSize: 9, color: "var(--cds-text-helper, #a8a8a8)", marginBottom: 2 }}>{s.name}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "#10b981" }}>
                        \u00A3{fmtN(s.saving_gbp_yr)}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--cds-text-secondary, #c6c6c6)" }}>
                        {fmtN(s.saving_co2_tonnes_yr, 1)}t CO₂
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-secondary, #c6c6c6)", marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, unit, color }) {
  return (
    <div style={{ textAlign: "center", flex: 1 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: color || "var(--cds-text-primary, #f4f4f4)" }}>
        {value}<span style={{ fontSize: 9, fontWeight: 400, color: "var(--cds-text-helper, #a8a8a8)" }}>{unit}</span>
      </div>
      <div style={{ fontSize: 9, color: "var(--cds-text-helper, #a8a8a8)" }}>{label}</div>
    </div>
  );
}

function Label({ children }) {
  return <div style={{ fontSize: 10, color: "var(--cds-text-helper, #a8a8a8)", marginBottom: 2 }}>{children}</div>;
}

const inputStyle = {
  width: "100%", background: "var(--cds-layer-01, #262626)",
  border: "1px solid var(--cds-border-subtle, #393939)",
  borderRadius: 4, color: "var(--cds-text-primary, #f4f4f4)",
  padding: "5px 8px", fontSize: 11,
};
