import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";
import api from "../../services/api";

const ASSET_TYPES = [
  { value: "solar_farm", label: "Solar Farm" },
  { value: "wind_farm", label: "Wind Farm" },
  { value: "battery_storage", label: "Battery Storage" },
  { value: "substation", label: "Substation" },
];

function conditionColor(score) {
  if (score >= 70) return "#4caf50";
  if (score >= 40) return "#ff9800";
  return "#f44336";
}

function statusBadge(status) {
  const colors = {
    OPERATIONAL: "#4caf50",
    DEGRADED: "#ff9800",
    END_OF_LIFE: "#f44336",
    COMPLIANT: "#4caf50",
    REQUIRES_ATTENTION: "#ff9800",
    "NON-COMPLIANT": "#f44336",
  };
  return colors[status] || "#607d8b";
}

export default function LegacyAssetCard() {
  const { pickedLocation } = useSite();
  const [loading, setLoading] = useState(false);
  const [assets, setAssets] = useState(null);
  const [lifecycle, setLifecycle] = useState(null);
  const [compliance, setCompliance] = useState(null);
  const [geoaiResult, setGeoaiResult] = useState(null);
  const [activeView, setActiveView] = useState("assets");

  const lat = pickedLocation?.lat || 52.0;
  const lon = pickedLocation?.lon || -1.5;

  const loadAssets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/legacy/assets?lat=${lat}&lon=${lon}&radius_km=25`);
      const data = await res.json();
      setAssets(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  const loadLifecycle = useCallback(async (assetType = "solar_farm", commDate = "2015-01-01", cap = 5000) => {
    try {
      const res = await fetch(`/api/legacy/lifecycle?asset_type=${assetType}&commissioning_date=${commDate}&capacity_kw=${cap}`);
      setLifecycle(await res.json());
    } catch (err) { console.error(err); }
  }, []);

  const loadCompliance = useCallback(async (assetType = "solar_farm", cap = 5000) => {
    try {
      const res = await fetch(`/api/legacy/compliance?asset_type=${assetType}&capacity_kw=${cap}`);
      setCompliance(await res.json());
    } catch (err) { console.error(err); }
  }, []);

  const runGeoAI = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/geoai/analyse?lat=${lat}&lon=${lon}&mode=asset_condition&radius_km=2`);
      setGeoaiResult(await res.json());
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [lat, lon]);

  return (
    <div className="legacy-card">
      <div className="section-label">Legacy Asset Planning & Compliance</div>

      {/* View toggle */}
      <div className="legacy-view-toggle">
        {[
          { id: "assets", label: "Assets" },
          { id: "lifecycle", label: "Lifecycle" },
          { id: "compliance", label: "Compliance" },
          { id: "geoai", label: "GeoAI" },
        ].map(v => (
          <button
            key={v.id}
            className={`legacy-view-btn${activeView === v.id ? " active" : ""}`}
            onClick={() => setActiveView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Assets view */}
      {activeView === "assets" && (
        <div>
          <button className="legacy-action-btn" onClick={loadAssets} disabled={loading}>
            {loading ? "Scanning..." : "Find Legacy Assets"}
          </button>
          {assets && (
            <div style={{ marginTop: 8 }}>
              <div className="stat-inline">
                Found <strong>{assets.count}</strong> legacy assets within 25 km
              </div>
              {assets.assets?.map((a, i) => (
                <div key={i} className="legacy-asset-row" onClick={() => {
                  loadLifecycle(a.asset_type, a.commissioning, a.capacity_kw);
                  loadCompliance(a.asset_type, a.capacity_kw);
                  setActiveView("lifecycle");
                }}>
                  <div className="legacy-asset-name">{a.name}</div>
                  <div className="legacy-asset-meta">
                    <span>{a.asset_type.replace(/_/g, " ")}</span>
                    <span>{(a.capacity_kw / 1000).toFixed(1)} MW</span>
                    <span style={{ color: conditionColor(a.condition_score) }}>
                      {a.condition_score?.toFixed(0)}/100
                    </span>
                    <span className="legacy-status-badge" style={{ background: statusBadge(a.status?.toUpperCase()) }}>
                      {a.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Lifecycle view */}
      {activeView === "lifecycle" && (
        <div>
          {!lifecycle ? (
            <div className="muted">Select an asset or run lifecycle assessment</div>
          ) : (
            <>
              <div className="stat-grid">
                <div>Age: <strong>{lifecycle.age_years} yr</strong></div>
                <div>Remaining: <strong>{lifecycle.remaining_life_years} yr</strong></div>
                <div>Output: <strong>{lifecycle.current_output_pct}%</strong></div>
                <div>Condition: <strong style={{ color: conditionColor(lifecycle.condition_score) }}>
                  {lifecycle.condition_score}/100
                </strong></div>
              </div>
              <div className="section-label" style={{ marginTop: 6 }}>
                Status: <span style={{ color: statusBadge(lifecycle.status) }}>{lifecycle.status}</span>
              </div>

              {/* Progress bar */}
              <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 3, height: 8, margin: "6px 0" }}>
                <div style={{
                  width: `${lifecycle.lifecycle_pct}%`,
                  height: "100%",
                  borderRadius: 3,
                  background: lifecycle.lifecycle_pct > 80 ? "#f44336" : lifecycle.lifecycle_pct > 50 ? "#ff9800" : "#4caf50",
                }} />
              </div>
              <div className="stat-inline">{lifecycle.lifecycle_pct}% through design life</div>

              {/* Repowering */}
              {lifecycle.repowering && (
                <>
                  <div className="section-label">Repowering Opportunity</div>
                  <div className="stat-grid">
                    <div>New capacity: <strong>{(lifecycle.repowering.new_capacity_kw / 1000).toFixed(1)} MW</strong></div>
                    <div>Gain: <strong>+{lifecycle.repowering.capacity_gain_pct}%</strong></div>
                    <div>Cost: <strong>£{(lifecycle.repowering.estimated_cost_gbp / 1000).toFixed(0)}k</strong></div>
                    <div>ROI: <strong>{lifecycle.repowering.estimated_roi_years || "N/A"} yr</strong></div>
                  </div>
                  <div className="stat-inline" style={{
                    color: lifecycle.repowering.recommended ? "#4caf50" : "#607d8b"
                  }}>
                    {lifecycle.repowering.recommended ? "Repowering recommended" : "Repowering not yet urgent"} — urgency: {lifecycle.repowering.urgency}
                  </div>
                </>
              )}

              {/* Milestones */}
              {lifecycle.milestones?.length > 0 && (
                <>
                  <div className="section-label">Compliance Milestones</div>
                  {lifecycle.milestones.slice(0, 6).map((m, i) => (
                    <div key={i} className="legacy-milestone">
                      <span className={`legacy-milestone-status ${m.status}`}>
                        {m.status === "passed" ? "✓" : m.status === "overdue" ? "!" : "○"}
                      </span>
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-bright)" }}>{m.event}</div>
                        <div style={{ fontSize: 10, color: "var(--text-dim)" }}>{m.date} — {m.action}</div>
                      </div>
                    </div>
                  ))}
                </>
              )}

              {/* Decommissioning */}
              {lifecycle.decommissioning && (
                <>
                  <div className="section-label">Decommissioning</div>
                  <div className="stat-grid">
                    <div>Est. cost: <strong>£{(lifecycle.decommissioning.estimated_cost_gbp / 1000).toFixed(0)}k</strong></div>
                    <div>Duration: <strong>{lifecycle.decommissioning.typical_duration_months} mo</strong></div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* Compliance view */}
      {activeView === "compliance" && (
        <div>
          {!compliance ? (
            <div className="muted">Select an asset to view compliance status</div>
          ) : (
            <>
              <div className="section-label">
                Overall: <span style={{ color: statusBadge(compliance.overall_status) }}>
                  {compliance.overall_status}
                </span>
              </div>
              <div className="stat-inline">{compliance.total_issues} issue(s) found</div>
              {compliance.checks?.map((c, i) => (
                <div key={i} className="legacy-compliance-check">
                  <div className="legacy-check-header">
                    <span style={{ color: statusBadge(c.status.toUpperCase()) }}>●</span>
                    <strong>{c.framework}</strong>
                    <span className="legacy-status-badge" style={{ background: statusBadge(c.status.toUpperCase()) }}>
                      {c.status}
                    </span>
                  </div>
                  {c.issues.map((issue, j) => (
                    <div key={j} className="legacy-check-issue">• {issue}</div>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* GeoAI view */}
      {activeView === "geoai" && (
        <div>
          <button className="legacy-action-btn" onClick={runGeoAI} disabled={loading}>
            {loading ? "Analysing..." : "Run GeoAI Asset Condition Scan"}
          </button>
          {geoaiResult && (
            <div style={{ marginTop: 8 }}>
              <div className="section-label">
                Condition: <span style={{ color: conditionColor(geoaiResult.condition_score) }}>
                  {geoaiResult.condition_rating} ({geoaiResult.condition_score}/100)
                </span>
              </div>
              {geoaiResult.flags?.length > 0 && (
                <>
                  <div className="section-label">Flags</div>
                  {geoaiResult.flags.map((f, i) => (
                    <div key={i} className="legacy-check-issue" style={{ color: "#ff9800" }}>⚠ {f}</div>
                  ))}
                </>
              )}
              {geoaiResult.recommendations?.length > 0 && (
                <>
                  <div className="section-label">Recommendations</div>
                  {geoaiResult.recommendations.map((r, i) => (
                    <div key={i} className="legacy-check-issue">→ {r}</div>
                  ))}
                </>
              )}
              {geoaiResult.components?.changes && (
                <>
                  <div className="section-label">Change Detection ({geoaiResult.components.changes.period})</div>
                  <div className="stat-grid">
                    <div>Changed: <strong>{geoaiResult.components.changes.change_pct}%</strong></div>
                    <div>Area: <strong>{geoaiResult.components.changes.changed_area_km2} km²</strong></div>
                  </div>
                </>
              )}
              {geoaiResult.components?.canopy && (
                <>
                  <div className="section-label">Canopy Height</div>
                  <div className="stat-grid">
                    <div>Mean: <strong>{geoaiResult.components.canopy.mean_height_m}m</strong></div>
                    <div>Cover: <strong>{geoaiResult.components.canopy.canopy_cover_pct}%</strong></div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
