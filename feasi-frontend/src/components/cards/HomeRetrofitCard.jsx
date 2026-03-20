import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";

const HOUSE_TYPES = [
  { value: "victorian_terrace_mid", label: "Victorian Mid-Terrace" },
  { value: "victorian_terrace_end", label: "Victorian End-Terrace" },
  { value: "edwardian_semi", label: "Edwardian Semi" },
  { value: "1930s_semi", label: "1930s Semi" },
  { value: "1930s_detached", label: "1930s Detached" },
  { value: "1950s_semi", label: "1950s Semi" },
  { value: "1960s_detached", label: "1960s Detached" },
  { value: "1970s_bungalow", label: "1970s Bungalow" },
  { value: "1980s_semi", label: "1980s Semi" },
  { value: "1990s_detached", label: "1990s Detached" },
  { value: "2000s_townhouse", label: "2000s Townhouse" },
  { value: "modern_newbuild", label: "Modern New-Build" },
];

const EPC_RATINGS = ["A", "B", "C", "D", "E", "F", "G"];
const HEATING_TYPES = [
  { value: "gas_boiler", label: "Gas Boiler" },
  { value: "gas_combi", label: "Gas Combi" },
  { value: "oil_boiler", label: "Oil Boiler" },
  { value: "electric_storage", label: "Electric Storage" },
  { value: "ashp", label: "ASHP" },
  { value: "gshp", label: "GSHP" },
  { value: "lpg", label: "LPG" },
];

function epcColor(rating) {
  const colors = { A: "#00c853", B: "#64dd17", C: "#aeea00", D: "#ffd600", E: "#ff9100", F: "#ff3d00", G: "#d50000" };
  return colors[rating] || "#607d8b";
}

function planBadge(route) {
  const map = {
    none_required: { label: "No Planning", color: "#4caf50" },
    permitted_development: { label: "PD", color: "#2196f3" },
    prior_approval: { label: "Prior Approval", color: "#ff9800" },
    full_planning: { label: "Full Planning", color: "#e91e63" },
    listed_building_consent: { label: "Listed", color: "#f44336" },
  };
  return map[route] || { label: route, color: "#607d8b" };
}

const themeColor = "#8e24aa";

export default function HomeRetrofitCard() {
  const { pickedLocation, parcelId } = useSite();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [view, setView] = useState("input"); // input | results | precedents

  // Form state
  const [houseType, setHouseType] = useState("1930s_semi");
  const [plotWidth, setPlotWidth] = useState(8);
  const [plotDepth, setPlotDepth] = useState(25);
  const [storeys, setStoreys] = useState(2);
  const [epc, setEpc] = useState("D");
  const [heating, setHeating] = useState("gas_boiler");
  const [conservation, setConservation] = useState(false);
  const [budget, setBudget] = useState("");

  const lat = pickedLocation?.lat || 52.5;
  const lon = pickedLocation?.lon || -1.5;

  const runAssess = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = {
        house_type: houseType,
        plot_width_m: parseFloat(plotWidth) || 8,
        plot_depth_m: parseFloat(plotDepth) || 25,
        storeys: parseInt(storeys) || 2,
        epc_rating: epc,
        heating,
        conservation,
        lat, lon,
      };
      if (budget) body.budget_gbp = parseFloat(budget);
      if (parcelId) body.parcel_id = parcelId;

      const res = await fetch("/home-retrofit/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      setView("results");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [houseType, plotWidth, plotDepth, storeys, epc, heating, conservation, budget, lat, lon, parcelId]);

  const tabBtn = (v, label) => (
    <button
      key={v}
      onClick={() => setView(v)}
      style={{
        padding: "4px 10px", fontSize: 12, border: "none", borderRadius: 4, cursor: "pointer",
        background: view === v ? themeColor : "#333", color: "#fff",
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: themeColor, flex: 1 }}>Home Retrofit</h3>
        {tabBtn("input", "Input")}
        {tabBtn("results", "Results")}
        {tabBtn("precedents", "Precedents")}
      </div>

      {error && <div style={{ color: "#f44336", fontSize: 12, marginBottom: 8 }}>{error}</div>}

      {view === "input" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
          <label style={{ gridColumn: "1/-1" }}>
            House Type
            <select value={houseType} onChange={e => setHouseType(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }}>
              {HOUSE_TYPES.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <label>
            Plot Width (m)
            <input type="number" value={plotWidth} onChange={e => setPlotWidth(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }} />
          </label>
          <label>
            Plot Depth (m)
            <input type="number" value={plotDepth} onChange={e => setPlotDepth(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }} />
          </label>
          <label>
            Storeys
            <input type="number" value={storeys} min={1} max={4} onChange={e => setStoreys(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }} />
          </label>
          <label>
            EPC Rating
            <select value={epc} onChange={e => setEpc(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }}>
              {EPC_RATINGS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label style={{ gridColumn: "1/-1" }}>
            Heating
            <select value={heating} onChange={e => setHeating(e.target.value)}
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }}>
              {HEATING_TYPES.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
            </select>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={conservation} onChange={e => setConservation(e.target.checked)} />
            Conservation Area
          </label>
          <label>
            Budget (£)
            <input type="number" value={budget} onChange={e => setBudget(e.target.value)} placeholder="Optional"
              style={{ width: "100%", padding: 4, marginTop: 2, background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 4 }} />
          </label>
          <button
            onClick={runAssess}
            disabled={loading}
            style={{
              gridColumn: "1/-1", padding: "8px 16px", fontSize: 13, fontWeight: 600,
              background: loading ? "#555" : themeColor, color: "#fff",
              border: "none", borderRadius: 6, cursor: loading ? "wait" : "pointer", marginTop: 4,
            }}
          >
            {loading ? "Assessing..." : "Assess Retrofit Options"}
          </button>
        </div>
      )}

      {view === "results" && result && (
        <div style={{ fontSize: 12 }}>
          <div style={{ marginBottom: 8, padding: 6, background: "#F7F8FA", borderRadius: 6 }}>
            <strong>{result.archetype}</strong>
            <span style={{ float: "right", opacity: 0.7 }}>{result.matched_cases?.length || 0} similar cases found</span>
          </div>

          {result.options?.map((opt, i) => {
            const en = opt.energy || {};
            const pl = opt.planning || {};
            const pb = planBadge(pl.route);
            const savingPct = en.energy_saving_pct || 0;
            return (
              <div key={i} style={{ marginBottom: 8, padding: 8, background: "#F7F8FA", borderRadius: 6, borderLeft: `3px solid ${themeColor}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <strong>{opt.name}</strong>
                  <span style={{
                    padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                    background: pb.color, color: "#fff",
                  }}>
                    {pb.label}
                  </span>
                </div>
                <div style={{ opacity: 0.8, marginBottom: 6 }}>{opt.description}</div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 4 }}>
                  <span><strong>£{(opt.total_cost_gbp || 0).toLocaleString()}</strong></span>
                  <span>
                    EPC: <span style={{ color: epcColor(en.epc_before), fontWeight: 600 }}>{en.epc_before}</span>
                    {" → "}
                    <span style={{ color: epcColor(en.epc_after), fontWeight: 600 }}>{en.epc_after}</span>
                  </span>
                  <span>-{en.energy_saving_kwh?.toLocaleString() || 0} kWh/yr</span>
                  <span>-{en.co2_saving_kg?.toLocaleString() || 0} kg CO₂/yr</span>
                </div>
                {/* Energy saving bar */}
                <div style={{ background: "#333", borderRadius: 3, height: 6, marginBottom: 4 }}>
                  <div style={{ width: `${Math.min(savingPct, 100)}%`, height: "100%", borderRadius: 3, background: `linear-gradient(90deg, ${themeColor}, #4caf50)` }} />
                </div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {opt.interventions?.map((intv, j) => (
                    <span key={j} style={{ padding: "1px 6px", background: "#333", borderRadius: 8, fontSize: 10 }}>
                      {intv.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
                {opt.provenance?.length > 0 && (
                  <div style={{ marginTop: 4, fontSize: 10, opacity: 0.7 }}>
                    Precedent: {opt.provenance[0].planning_ref} ({opt.provenance[0].planning_authority}) — {opt.provenance[0].planning_outcome}
                  </div>
                )}
              </div>
            );
          })}

          {/* Solar & Heat Pump summary */}
          {result.solar_potential && (
            <div style={{ padding: 6, background: "#F7F8FA", borderRadius: 6, marginBottom: 6 }}>
              <strong>Solar PV Potential:</strong> {result.solar_potential.capacity_kw} kWp, {result.solar_potential.annual_kwh?.toLocaleString()} kWh/yr,
              payback {result.solar_potential.payback_years} yrs
            </div>
          )}
          {result.heat_pump_assessment && (
            <div style={{ padding: 6, background: "#F7F8FA", borderRadius: 6 }}>
              <strong>Heat Pump:</strong> Recommended: <span style={{ color: themeColor, fontWeight: 600 }}>
                {result.heat_pump_assessment.recommendation?.toUpperCase() || "None"}
              </span>
              {result.heat_pump_assessment.ashp && (
                <span> | ASHP {result.heat_pump_assessment.ashp.recommended_kw}kW, net £{result.heat_pump_assessment.ashp.net_cost_gbp?.toLocaleString()} (after BUS grant)</span>
              )}
            </div>
          )}
        </div>
      )}

      {view === "results" && !result && (
        <div style={{ fontSize: 12, opacity: 0.6, padding: 16, textAlign: "center" }}>
          No assessment yet — fill in property details and click Assess.
        </div>
      )}

      {view === "precedents" && result?.matched_cases && (
        <div style={{ fontSize: 12 }}>
          <div style={{ marginBottom: 6, fontWeight: 600 }}>Matched Cases ({result.matched_cases.length})</div>
          {result.matched_cases.map((c, i) => (
            <div key={i} style={{ padding: 6, marginBottom: 4, background: "#F7F8FA", borderRadius: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>{c.case_ref}</strong>
                <span style={{ opacity: 0.7 }}>{(c.similarity * 100).toFixed(0)}% match</span>
              </div>
              <div style={{ opacity: 0.8 }}>
                {c.house_type?.replace(/_/g, " ")} | {c.era} | {c.planning_authority}
              </div>
              <div>
                <span style={{ color: epcColor(c.epc_before) }}>{c.epc_before}</span>
                {" → "}
                <span style={{ color: epcColor(c.epc_after) }}>{c.epc_after}</span>
                {" | "}
                {c.planning_ref} — <span style={{ color: c.planning_outcome === "approved" ? "#4caf50" : "#ff9800" }}>{c.planning_outcome}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {view === "precedents" && !result?.matched_cases && (
        <div style={{ fontSize: 12, opacity: 0.6, padding: 16, textAlign: "center" }}>
          Run an assessment first to see matched precedents.
        </div>
      )}
    </div>
  );
}
