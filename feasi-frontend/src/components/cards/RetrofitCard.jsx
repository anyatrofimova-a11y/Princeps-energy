import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";

const INFRA_TYPES = [
  { value: "hydropower_dam", label: "Hydropower Dam" },
  { value: "coal_power_plant", label: "Coal Power Plant" },
  { value: "gas_power_plant", label: "Gas Power Plant" },
  { value: "industrial_facility", label: "Industrial Facility" },
  { value: "coal_mine", label: "Coal Mine" },
  { value: "oil_gas_infrastructure", label: "Oil & Gas Infra" },
  { value: "old_substation", label: "Old Substation" },
  { value: "decommissioned_wind_farm", label: "Decom Wind Farm" },
  { value: "quarry", label: "Quarry" },
  { value: "military_base", label: "Military Base" },
];

const STORAGE_TECHS = [
  { value: "pumped_hydro", label: "Pumped Hydro" },
  { value: "compressed_air", label: "Compressed Air (CAES)" },
  { value: "gravity_storage", label: "Gravity Storage" },
  { value: "li_ion_bess", label: "Li-ion BESS" },
  { value: "flow_battery", label: "Flow Battery" },
  { value: "thermal_storage", label: "Thermal Storage" },
  { value: "hydrogen", label: "Hydrogen" },
  { value: "flywheel", label: "Flywheel" },
];

const ACCENT = "#607d8b";

function verdictColor(v) {
  if (v === "GO") return "#4caf50";
  if (v === "CAUTION") return "#ff9800";
  return "#f44336";
}

function scoreBar(score, max, label) {
  const pct = max > 0 ? (score / max) * 100 : 0;
  const color = pct >= 70 ? "#4caf50" : pct >= 45 ? "#ff9800" : "#f44336";
  return (
    <div style={{ marginBottom: 4 }} key={label}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-dim)" }}>
        <span>{label}</span>
        <span>{score}/{max}</span>
      </div>
      <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 3, height: 6 }}>
        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 3, background: color, transition: "width 0.3s" }} />
      </div>
    </div>
  );
}

export default function RetrofitCard() {
  const { pickedLocation } = useSite();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("assessment");
  const [infraType, setInfraType] = useState("coal_power_plant");
  const [storageTech, setStorageTech] = useState("li_ion_bess");
  const [capacityMw, setCapacityMw] = useState(50);
  const [durationHours, setDurationHours] = useState(4);

  const [assessment, setAssessment] = useState(null);
  const [storageMatch, setStorageMatch] = useState(null);
  const [disruptionPlan, setDisruptionPlan] = useState(null);
  const [circularity, setCircularity] = useState(null);

  const lat = pickedLocation?.lat || 52.5;
  const lon = pickedLocation?.lon || -1.5;

  const runAssessment = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/retrofit/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          infrastructure_type: infraType,
          storage_technology: storageTech,
          capacity_mw: capacityMw,
          duration_hours: durationHours,
          lat, lon,
        }),
      });
      setAssessment(await res.json());
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [infraType, storageTech, capacityMw, durationHours, lat, lon]);

  const runStorageMatch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/retrofit/match-storage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          infrastructure_type: infraType,
          capacity_mw: capacityMw,
          duration_hours: durationHours,
          site_area_m2: 50000,
        }),
      });
      setStorageMatch(await res.json());
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [infraType, capacityMw, durationHours]);

  const runDisruptionPlan = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/retrofit/disruption-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          infrastructure_type: infraType,
          storage_technology: storageTech,
          capacity_mw: capacityMw,
        }),
      });
      setDisruptionPlan(await res.json());
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [infraType, storageTech, capacityMw]);

  const runCircularity = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/retrofit/circularity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          infrastructure_type: infraType,
          storage_technology: storageTech,
          capacity_mw: capacityMw,
        }),
      });
      setCircularity(await res.json());
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [infraType, storageTech, capacityMw]);

  return (
    <div className="retrofit-card">
      <div className="section-label" style={{ borderLeft: `3px solid ${ACCENT}`, paddingLeft: 8 }}>
        Infrastructure Retrofit & Energy Storage
      </div>

      {/* Controls */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, margin: "8px 0" }}>
        <select value={infraType} onChange={e => setInfraType(e.target.value)}
          style={{ fontSize: 11, padding: "4px 6px", background: "var(--bg-card)", color: "var(--text-bright)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4 }}>
          {INFRA_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select value={storageTech} onChange={e => setStorageTech(e.target.value)}
          style={{ fontSize: 11, padding: "4px 6px", background: "var(--bg-card)", color: "var(--text-bright)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4 }}>
          {STORAGE_TECHS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input type="number" value={capacityMw} onChange={e => setCapacityMw(Number(e.target.value))} min={1} max={2000}
            style={{ width: 60, fontSize: 11, padding: "4px 6px", background: "var(--bg-card)", color: "var(--text-bright)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4 }} />
          <span style={{ fontSize: 10, color: "var(--text-dim)" }}>MW</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input type="number" value={durationHours} onChange={e => setDurationHours(Number(e.target.value))} min={0.1} max={720} step={0.5}
            style={{ width: 60, fontSize: 11, padding: "4px 6px", background: "var(--bg-card)", color: "var(--text-bright)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4 }} />
          <span style={{ fontSize: 10, color: "var(--text-dim)" }}>hours</span>
        </div>
      </div>

      {/* Tab toggle */}
      <div className="legacy-view-toggle">
        {[
          { id: "assessment", label: "Assessment" },
          { id: "storage", label: "Storage Match" },
          { id: "disruption", label: "Disruption" },
          { id: "circularity", label: "Circularity" },
        ].map(v => (
          <button
            key={v.id}
            className={`legacy-view-btn${activeTab === v.id ? " active" : ""}`}
            style={activeTab === v.id ? { background: ACCENT, borderColor: ACCENT } : { borderColor: ACCENT, color: ACCENT }}
            onClick={() => setActiveTab(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Assessment tab */}
      {activeTab === "assessment" && (
        <div>
          <button className="legacy-action-btn" onClick={runAssessment} disabled={loading}
            style={{ borderColor: ACCENT, color: loading ? "var(--text-dim)" : ACCENT }}>
            {loading ? "Assessing..." : "Run Feasibility Assessment"}
          </button>
          {assessment && !assessment.error && (
            <div style={{ marginTop: 8 }}>
              {/* Verdict badge */}
              <div style={{
                display: "inline-block", padding: "4px 14px", borderRadius: 4, fontWeight: 700, fontSize: 13,
                background: verdictColor(assessment.verdict), color: "#fff", marginBottom: 8,
              }}>
                {assessment.verdict} — {assessment.total_score}/100
              </div>

              {/* Score breakdown */}
              <div style={{ marginTop: 6 }}>
                {assessment.scores && Object.entries(assessment.scores).map(([key, val]) =>
                  scoreBar(val.score, val.max, key.replace(/_/g, " "))
                )}
              </div>

              {/* Cost comparison */}
              {assessment.cost_estimate && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Cost Comparison</div>
                  <div className="stat-grid">
                    <div>Retrofit: <strong style={{ color: "#4caf50" }}>
                      £{(assessment.cost_estimate.retrofit_total_gbp / 1e6).toFixed(1)}M
                    </strong></div>
                    <div>Greenfield: <strong>
                      £{(assessment.cost_estimate.greenfield_total_gbp / 1e6).toFixed(1)}M
                    </strong></div>
                    <div>Saving: <strong style={{ color: "#4caf50" }}>
                      {assessment.cost_estimate.saving_pct}%
                    </strong></div>
                    <div>£/kW: <strong>{assessment.cost_estimate.gbp_per_kw}</strong></div>
                  </div>
                </>
              )}

              {/* Recommendations */}
              {assessment.recommendations?.length > 0 && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Recommendations</div>
                  {assessment.recommendations.map((r, i) => (
                    <div key={i} className="legacy-check-issue" style={{ color: "var(--text-bright)" }}>→ {r}</div>
                  ))}
                </>
              )}
            </div>
          )}
          {assessment?.error && (
            <div style={{ color: "#f44336", fontSize: 11, marginTop: 8 }}>{assessment.error}</div>
          )}
        </div>
      )}

      {/* Storage Match tab */}
      {activeTab === "storage" && (
        <div>
          <button className="legacy-action-btn" onClick={runStorageMatch} disabled={loading}
            style={{ borderColor: ACCENT, color: loading ? "var(--text-dim)" : ACCENT }}>
            {loading ? "Matching..." : "Match Storage Technologies"}
          </button>
          {storageMatch?.technologies && (
            <div style={{ marginTop: 8 }}>
              {storageMatch.technologies.map((t, i) => (
                <div key={i} className="legacy-asset-row" onClick={() => { setStorageTech(t.storage_technology); setActiveTab("assessment"); }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div className="legacy-asset-name" style={{ fontSize: 11 }}>
                      {STORAGE_TECHS.find(s => s.value === t.storage_technology)?.label || t.storage_technology}
                    </div>
                    <span style={{
                      fontSize: 11, fontWeight: 700,
                      color: t.compatibility_score >= 70 ? "#4caf50" : t.compatibility_score >= 45 ? "#ff9800" : "#f44336",
                    }}>{t.compatibility_score}/100</span>
                  </div>
                  <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 3, height: 5, margin: "3px 0" }}>
                    <div style={{
                      width: `${t.compatibility_score}%`, height: "100%", borderRadius: 3,
                      background: t.compatibility_score >= 70 ? "#4caf50" : t.compatibility_score >= 45 ? "#ff9800" : "#f44336",
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)" }}>{t.rationale}</div>
                  <div className="legacy-asset-meta" style={{ marginTop: 2 }}>
                    <span>TRL {t.trl}</span>
                    <span>η {t.round_trip_efficiency_pct}%</span>
                    <span>£{(t.capex_estimate.retrofit_gbp / 1e6).toFixed(1)}M</span>
                    <span style={{ color: "#4caf50" }}>-{t.capex_estimate.saving_pct}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Disruption Plan tab */}
      {activeTab === "disruption" && (
        <div>
          <button className="legacy-action-btn" onClick={runDisruptionPlan} disabled={loading}
            style={{ borderColor: ACCENT, color: loading ? "var(--text-dim)" : ACCENT }}>
            {loading ? "Planning..." : "Generate Disruption Plan"}
          </button>
          {disruptionPlan && (
            <div style={{ marginTop: 8 }}>
              <div className="stat-grid">
                <div>Duration: <strong>{disruptionPlan.total_duration_months} mo</strong></div>
                <div>Disruption: <strong style={{
                  color: disruptionPlan.disruption_score > 60 ? "#f44336" : disruptionPlan.disruption_score > 30 ? "#ff9800" : "#4caf50",
                }}>{disruptionPlan.disruption_score}/100</strong></div>
                <div>Op. impact: <strong>{disruptionPlan.operational_disruption_pct}%</strong></div>
              </div>

              {/* Phase timeline */}
              {disruptionPlan.phases?.map((p, i) => (
                <div key={i} style={{ margin: "6px 0", padding: "4px 8px", background: "rgba(255,255,255,0.03)", borderRadius: 4, borderLeft: `3px solid ${ACCENT}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontWeight: 600, color: "var(--text-bright)" }}>
                    <span>Phase {p.phase}: {p.name}</span>
                    <span>{p.duration_months} mo</span>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2 }}>
                    {p.impact}
                  </div>
                  {/* Duration bar */}
                  <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 3, height: 4, margin: "3px 0" }}>
                    <div style={{
                      width: `${(p.duration_months / disruptionPlan.total_duration_months) * 100}%`,
                      height: "100%", borderRadius: 3, background: ACCENT,
                    }} />
                  </div>
                </div>
              ))}

              {/* Mitigations */}
              {disruptionPlan.mitigation_measures?.length > 0 && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Mitigation Measures</div>
                  {disruptionPlan.mitigation_measures.map((m, i) => (
                    <div key={i} className="legacy-check-issue" style={{ fontSize: 10 }}>→ {m}</div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Circularity tab */}
      {activeTab === "circularity" && (
        <div>
          <button className="legacy-action-btn" onClick={runCircularity} disabled={loading}
            style={{ borderColor: ACCENT, color: loading ? "var(--text-dim)" : ACCENT }}>
            {loading ? "Analysing..." : "Run Circularity & Impact Assessment"}
          </button>
          {circularity && (
            <div style={{ marginTop: 8 }}>
              {/* Circularity scores */}
              {circularity.circularity && (
                <>
                  <div className="section-label">Circularity</div>
                  <div className="stat-grid">
                    <div>Score: <strong style={{ color: circularity.circularity.circularity_score >= 60 ? "#4caf50" : "#ff9800" }}>
                      {circularity.circularity.circularity_score}/100
                    </strong></div>
                    <div>Reuse: <strong>{circularity.circularity.material_reuse_pct}%</strong></div>
                    <div>Recyclable: <strong>{circularity.circularity.recyclability_pct}%</strong></div>
                    <div>CO2 saving: <strong style={{ color: "#4caf50" }}>{circularity.circularity.co2_vs_greenfield_saving_pct}%</strong></div>
                  </div>
                  {circularity.circularity.critical_minerals?.length > 0 && (
                    <div style={{ fontSize: 10, color: "#ff9800", marginTop: 4 }}>
                      Critical minerals: {circularity.circularity.critical_minerals.join(", ")}
                    </div>
                  )}
                  {circularity.circularity.eu_taxonomy_4_10_aligned && (
                    <div style={{ fontSize: 10, color: "#4caf50", marginTop: 2 }}>EU Taxonomy 4.10 aligned</div>
                  )}
                </>
              )}

              {/* Socioeconomic */}
              {circularity.socioeconomic && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Socioeconomic Impact</div>
                  <div className="stat-grid">
                    <div>Construction: <strong>{circularity.socioeconomic.construction_jobs} jobs</strong></div>
                    <div>Permanent: <strong>{circularity.socioeconomic.permanent_jobs} jobs</strong></div>
                    <div>CBF: <strong>£{(circularity.socioeconomic.community_benefit_fund_gbp_yr / 1000).toFixed(0)}k/yr</strong></div>
                    {circularity.socioeconomic.brownfield_remediation && (
                      <div>Remediation: <strong>£{(circularity.socioeconomic.remediation_value_gbp / 1000).toFixed(0)}k</strong></div>
                    )}
                  </div>
                  {circularity.socioeconomic.just_transition_aligned && (
                    <div style={{ fontSize: 10, color: "#4caf50", marginTop: 2 }}>Just Transition aligned</div>
                  )}
                </>
              )}

              {/* Security */}
              {circularity.security && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Security (NIS2)</div>
                  <div className="stat-grid">
                    <div>Score: <strong>{circularity.security.security_score}/100</strong></div>
                    <div>NIS2: <strong style={{ color: circularity.security.nis2_compliance?.essential_entity ? "#ff9800" : "#4caf50" }}>
                      {circularity.security.nis2_compliance?.essential_entity ? "Essential Entity" : "Standard"}
                    </strong></div>
                  </div>
                </>
              )}

              {/* Grid flexibility */}
              {circularity.grid_flexibility && (
                <>
                  <div className="section-label" style={{ marginTop: 8 }}>Grid Flexibility</div>
                  <div className="stat-grid">
                    <div>Flex score: <strong>{circularity.grid_flexibility.flexibility_score}/100</strong></div>
                    <div>Revenue: <strong style={{ color: "#4caf50" }}>
                      £{(circularity.grid_flexibility.total_estimated_revenue_gbp_yr / 1000).toFixed(0)}k/yr
                    </strong></div>
                    <div>Services: <strong>{circularity.grid_flexibility.grid_services?.length || 0}</strong></div>
                  </div>
                  {circularity.grid_flexibility.grid_services?.map((s, i) => (
                    <span key={i} style={{
                      display: "inline-block", fontSize: 9, padding: "2px 6px", margin: "2px 3px 2px 0",
                      background: "rgba(96,125,139,0.15)", borderRadius: 8, color: ACCENT,
                    }}>{s.replace(/_/g, " ")}</span>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
