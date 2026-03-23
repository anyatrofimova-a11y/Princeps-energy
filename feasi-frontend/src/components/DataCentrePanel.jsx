import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Facility profiles ─────────────────────────────────────────────── */
const PROFILES = [
  { key: "google_hyperscale", label: "Google Hyperscale", range: "100-500+ MW", icon: "G" },
  { key: "hyperscale", label: "Hyperscale", range: "30-200+ MW", icon: "H" },
  { key: "colocation", label: "Colocation", range: "5-30 MW", icon: "C" },
  { key: "edge", label: "Edge", range: "<5 MW", icon: "E" },
  { key: "custom", label: "Custom", range: "Any", icon: "*" },
];

const DIMENSIONS_9 = [
  { key: "power_capacity", label: "Power" },
  { key: "grid_headroom", label: "Headroom" },
  { key: "fibre_proximity", label: "Fibre" },
  { key: "ixp_proximity", label: "IXP" },
  { key: "water_cooling", label: "Water" },
  { key: "latency", label: "Latency" },
  { key: "land_planning", label: "Land" },
  { key: "resilience", label: "Resilience" },
  { key: "connection_speed", label: "Speed" },
];

const DIMENSIONS_EXT = [
  { key: "cfe_score", label: "CFE%" },
  { key: "cooling_climate", label: "Cooling" },
  { key: "constraint_clear", label: "Constraints" },
  { key: "water_stress", label: "Water Stress" },
  { key: "incentives", label: "Incentives" },
  { key: "regulatory_pathway", label: "Regulatory" },
];

function verdictColor(v) {
  if (v === "GO") return "#24a148";
  if (v === "CAUTION") return "#f1c21b";
  return "#da1e28";
}

function ratingColor(r) {
  if (r === "Excellent") return "#24a148";
  if (r === "Good") return "#D4A018";
  if (r === "Moderate") return "#f1c21b";
  return "#da1e28";
}

function fmtGbp(val) {
  if (val == null) return "--";
  if (val >= 1_000_000) return `\u00A3${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1000) return `\u00A3${(val / 1000).toFixed(0)}k`;
  return `\u00A3${val.toFixed(0)}`;
}

/* ── Radar chart (dynamic axis count) ──────────────────────────────── */
function RadarChart({ scores, dimensions, size = 240 }) {
  const cx = size / 2, cy = size / 2, r = size / 2 - 32;
  const n = dimensions.length;
  const step = (2 * Math.PI) / n;

  const pts = (vals) =>
    vals
      .map((v, i) => {
        const a = -Math.PI / 2 + i * step;
        const d = (v / 100) * r;
        return `${cx + d * Math.cos(a)},${cy + d * Math.sin(a)}`;
      })
      .join(" ");

  const vals = dimensions.map((d) => scores?.[d.key]?.score ?? 0);
  const rings = [25, 50, 75, 100];

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: "block", margin: "0 auto" }}>
      {rings.map((pct) => (
        <polygon
          key={pct}
          points={dimensions.map((_, i) => {
            const a = -Math.PI / 2 + i * step;
            const d = (pct / 100) * r;
            return `${cx + d * Math.cos(a)},${cy + d * Math.sin(a)}`;
          }).join(" ")}
          fill="none" stroke="#333" strokeWidth={0.5} opacity={0.4}
        />
      ))}
      {dimensions.map((d, i) => {
        const a = -Math.PI / 2 + i * step;
        return (
          <g key={d.key}>
            <line x1={cx} y1={cy} x2={cx + r * Math.cos(a)} y2={cy + r * Math.sin(a)} stroke="#444" strokeWidth={0.5} />
            <text
              x={cx + (r + 18) * Math.cos(a)}
              y={cy + (r + 18) * Math.sin(a)}
              textAnchor="middle" dominantBaseline="central"
              fill="#aaa" fontSize={n > 10 ? 7 : 9}
            >
              {d.label}
            </text>
          </g>
        );
      })}
      <polygon points={pts(vals)} fill="rgba(108,92,231,0.25)" stroke="#D4A018" strokeWidth={2} />
      {vals.map((v, i) => {
        const a = -Math.PI / 2 + i * step;
        const d = (v / 100) * r;
        return <circle key={i} cx={cx + d * Math.cos(a)} cy={cy + d * Math.sin(a)} r={2.5} fill="#D4A018" />;
      })}
    </svg>
  );
}

/* ── CFE Gauge ─────────────────────────────────────────────────────── */
function CFEGauge({ cfeData }) {
  if (!cfeData) return null;
  const pct = cfeData.achievable_cfe_pct || 0;
  const target = cfeData.target_cfe_pct || 90;
  const color = pct >= target ? "#24a148" : pct >= 60 ? "#f1c21b" : "#da1e28";
  return (
    <div style={{ padding: 8, background: "rgba(15,98,254,0.06)", borderRadius: 6, border: "1px solid rgba(15,98,254,0.2)", marginTop: 10 }}>
      <div style={{ fontSize: 11, color: "#888", fontWeight: 600, marginBottom: 6 }}>24/7 Carbon-Free Energy</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 28, fontWeight: 700, color }}>{pct.toFixed(0)}%</div>
          <div style={{ fontSize: 9, color: "#888" }}>Achievable CFE</div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ height: 8, background: "#222", borderRadius: 4, position: "relative", overflow: "hidden" }}>
            <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color, borderRadius: 4 }} />
            <div style={{ position: "absolute", left: `${target}%`, top: 0, width: 2, height: "100%", background: "#fff", opacity: 0.6 }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#666", marginTop: 2 }}>
            <span>Grid: {(cfeData.grid_cfe_pct || 0).toFixed(0)}%</span>
            <span>Target: {target}%</span>
          </div>
        </div>
      </div>
      {cfeData.path_to_target && (
        <div style={{ fontSize: 10, color: "#aaa", marginTop: 4 }}>{cfeData.path_to_target}</div>
      )}
      {cfeData.region && (
        <div style={{ fontSize: 9, color: "#666", marginTop: 2 }}>Region: {cfeData.region}</div>
      )}
    </div>
  );
}

/* ── Cooling Dials ─────────────────────────────────────────────────── */
function CoolingSection({ coolingData }) {
  if (!coolingData) return null;
  const pueColor = coolingData.pue_estimate <= 1.2 ? "#24a148" : coolingData.pue_estimate <= 1.4 ? "#f1c21b" : "#da1e28";
  return (
    <div style={{ padding: 8, background: "rgba(0,188,212,0.06)", borderRadius: 6, border: "1px solid rgba(0,188,212,0.2)", marginTop: 10 }}>
      <div style={{ fontSize: 11, color: "#888", fontWeight: 600, marginBottom: 6 }}>Cooling Analysis</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: pueColor }}>{coolingData.pue_estimate?.toFixed(2)}</div>
          <div style={{ fontSize: 9, color: "#888" }}>PUE</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#00bcd4" }}>{coolingData.wue_estimate_l_kwh?.toFixed(1)}</div>
          <div style={{ fontSize: 9, color: "#888" }}>WUE (L/kWh)</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#e0e0e0" }}>{coolingData.free_cooling_pct?.toFixed(0)}%</div>
          <div style={{ fontSize: 9, color: "#888" }}>Free Cooling</div>
        </div>
      </div>
      {coolingData.free_cooling_hours && (
        <div style={{ fontSize: 10, color: "#aaa", marginTop: 4, textAlign: "center" }}>
          {coolingData.free_cooling_hours.toLocaleString()} free cooling hrs/yr
        </div>
      )}
      {coolingData.future_pue && (
        <div style={{ display: "flex", justifyContent: "center", gap: 12, marginTop: 6 }}>
          {Object.entries(coolingData.future_pue).map(([yr, pue]) => (
            <div key={yr} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: "#666" }}>{yr}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#e0e0e0" }}>{pue.toFixed(2)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Constraint Badge ──────────────────────────────────────────────── */
function ConstraintBadge({ constraintData }) {
  if (!constraintData) return null;
  const clear = constraintData.is_clear;
  return (
    <div style={{
      padding: 8, borderRadius: 6, marginTop: 10,
      background: clear ? "rgba(36,161,72,0.06)" : "rgba(218,30,40,0.08)",
      border: `1px solid ${clear ? "rgba(36,161,72,0.3)" : "rgba(218,30,40,0.3)"}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 11, color: "#888", fontWeight: 600 }}>Constraint Check</div>
        <span style={{
          padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700,
          background: clear ? "rgba(36,161,72,0.15)" : "rgba(218,30,40,0.15)",
          color: clear ? "#24a148" : "#da1e28",
        }}>
          {clear ? "CLEAR" : "BLOCKED"}
        </span>
      </div>
      {constraintData.hard_constraints?.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {constraintData.hard_constraints.map((c, i) => (
            <div key={i} style={{ fontSize: 10, color: "#da1e28", marginTop: 2 }}>
              {c.type?.toUpperCase()}: {c.name} ({c.distance_m?.toFixed(0)}m)
            </div>
          ))}
        </div>
      )}
      {constraintData.soft_constraints?.length > 0 && (
        <div style={{ marginTop: 4 }}>
          {constraintData.soft_constraints.map((c, i) => (
            <div key={i} style={{ fontSize: 10, color: "#f1c21b", marginTop: 2 }}>
              {c.type?.replace(/_/g, " ")}: {c.name} ({c.penalty} pts)
            </div>
          ))}
        </div>
      )}
      {constraintData.green_belt && <div style={{ fontSize: 10, color: "#da1e28", marginTop: 2 }}>Green Belt</div>}
      {constraintData.flood_zone && <div style={{ fontSize: 10, color: "#f1c21b", marginTop: 2 }}>Flood Zone: {constraintData.flood_zone}</div>}
    </div>
  );
}

/* ── Water Stress Indicator ────────────────────────────────────────── */
function WaterStressBadge({ waterData }) {
  if (!waterData) return null;
  const statusColor = {
    available: "#24a148", moderate_stress: "#f1c21b", stress: "#ff6b35", serious_stress: "#da1e28",
  }[waterData.status] || "#888";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, padding: "6px 8px", background: "rgba(255,255,255,0.03)", borderRadius: 6, border: "1px solid var(--cds-border-subtle)" }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: statusColor }} />
      <div>
        <div style={{ fontSize: 11, color: "#e0e0e0" }}>{waterData.catchment}: <span style={{ color: statusColor, fontWeight: 600 }}>{waterData.status?.replace(/_/g, " ")}</span></div>
        <div style={{ fontSize: 9, color: "#888" }}>{waterData.cooling_recommendation?.replace(/_/g, " ")}</div>
      </div>
      {waterData.google_water_positive && (
        <span style={{ marginLeft: "auto", fontSize: 9, color: "#24a148", fontWeight: 600 }}>Water+</span>
      )}
    </div>
  );
}

/* ── Incentive Summary ─────────────────────────────────────────────── */
function IncentiveSummary({ incentiveData }) {
  if (!incentiveData || !incentiveData.zones?.length) return null;
  return (
    <div style={{ marginTop: 10, padding: 8, background: "rgba(241,194,27,0.06)", borderRadius: 6, border: "1px solid rgba(241,194,27,0.2)" }}>
      <div style={{ fontSize: 11, color: "#888", fontWeight: 600, marginBottom: 4 }}>Incentives</div>
      {incentiveData.zones.map((z, i) => (
        <div key={i} style={{ fontSize: 10, color: "#e0e0e0", marginBottom: 2 }}>
          <span style={{ fontWeight: 600 }}>{z.name}</span> ({z.type?.replace(/_/g, " ")}) — {z.distance_km?.toFixed(1)}km
          {z.rates_relief_5yr > 0 && <span style={{ color: "#f1c21b" }}> {fmtGbp(z.rates_relief_5yr)}/5yr</span>}
        </div>
      ))}
      {incentiveData.ai_growth_zone && (
        <div style={{ fontSize: 10, color: "#24a148", marginTop: 4, fontWeight: 600 }}>AI Growth Zone — Streamlined Planning</div>
      )}
    </div>
  );
}

/* ── Regulatory Pathway ────────────────────────────────────────────── */
function RegulatoryBadge({ regData }) {
  if (!regData) return null;
  return (
    <div style={{ marginTop: 10, padding: 8, background: "rgba(108,92,231,0.06)", borderRadius: 6, border: "1px solid rgba(108,92,231,0.2)" }}>
      <div style={{ fontSize: 11, color: "#888", fontWeight: 600, marginBottom: 4 }}>Regulatory Pathway</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {regData.nsip_eligible && (
          <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600, background: "rgba(36,161,72,0.15)", color: "#24a148", border: "1px solid #24a148" }}>
            NSIP Eligible
          </span>
        )}
        {regData.dc_precedent && (
          <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600, background: "rgba(108,92,231,0.15)", color: "#D4A018", border: "1px solid #D4A018" }}>
            DC Precedent
          </span>
        )}
        <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600, background: "rgba(255,255,255,0.05)", color: "#e0e0e0" }}>
          {regData.planning_authority} — {((regData.approval_rate || 0) * 100).toFixed(0)}% approval
        </span>
      </div>
      {regData.nsip_pathway && (
        <div style={{ fontSize: 10, color: "#aaa", marginTop: 4 }}>Pathway: {regData.nsip_pathway?.replace(/_/g, " ")}</div>
      )}
      {regData.avg_determination_months && (
        <div style={{ fontSize: 10, color: "#aaa" }}>Avg determination: {regData.avg_determination_months} months</div>
      )}
    </div>
  );
}

/* ── Main panel ──────────────────────────────────────────────────────── */
export default function DataCentrePanel({ onClose, onOpenComparison }) {
  const { explain, selectedParcel, samCapacity } = useSite();
  const [profile, setProfile] = useState("google_hyperscale");
  const [capacityMw, setCapacityMw] = useState(100);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showWeights, setShowWeights] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [extended, setExtended] = useState(null);
  const [extLoading, setExtLoading] = useState(false);
  // New dimension data
  const [cfeData, setCfeData] = useState(null);
  const [coolingData, setCoolingData] = useState(null);
  const [constraintData, setConstraintData] = useState(null);
  const [waterData, setWaterData] = useState(null);
  const [incentiveData, setIncentiveData] = useState(null);
  const [regData, setRegData] = useState(null);

  useEffect(() => {
    if (samCapacity) setCapacityMw(Math.max(1, samCapacity / 1000));
  }, [samCapacity]);

  const getLat = () => explain?.lat ?? explain?.location?.lat ?? selectedParcel?.lat ?? 51.5;
  const getLon = () => explain?.lon ?? explain?.location?.lon ?? selectedParcel?.lon ?? -0.1;

  const assess = useCallback(async () => {
    setLoading(true);
    setError(null);
    const lat = getLat(), lon = getLon();
    try {
      const params = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, profile });
      const res = await fetch(`/api/dc/score?${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());

      // Fetch extended dimensions in parallel
      const isExtended = profile === "google_hyperscale" || profile === "hyperscale";
      if (isExtended) {
        const [cfe, cooling, constraints, water, incentives, reg] = await Promise.allSettled([
          api.dc.cfe(lat, lon, capacityMw),
          api.dc.cooling(lat, lon, capacityMw),
          api.dc.constraints(lat, lon),
          api.dc.waterStress(lat, lon, capacityMw),
          api.dc.incentives(lat, lon, capacityMw),
          api.dc.regulatory(lat, lon, capacityMw),
        ]);
        if (cfe.status === "fulfilled") setCfeData(cfe.value);
        if (cooling.status === "fulfilled") setCoolingData(cooling.value);
        if (constraints.status === "fulfilled") setConstraintData(constraints.value);
        if (water.status === "fulfilled") setWaterData(water.value);
        if (incentives.status === "fulfilled") setIncentiveData(incentives.value);
        if (reg.status === "fulfilled") setRegData(reg.value);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [explain, selectedParcel, capacityMw, profile]);

  const assessExtended = useCallback(async () => {
    setExtLoading(true);
    const lat = getLat(), lon = getLon();
    try {
      const ext = await api.dc.scoreExtended(lat, lon, capacityMw, profile);
      setExtended(ext);
    } catch (e) {
      setError(e?.message || "Extended scoring failed");
    } finally {
      setExtLoading(false);
    }
  }, [explain, selectedParcel, capacityMw, profile]);

  const scan = useCallback(async () => {
    setScanLoading(true);
    try {
      const params = new URLSearchParams({ profile, capacity_mw: capacityMw, limit: 20 });
      const res = await fetch(`/api/dc/scan?${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setScanResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setScanLoading(false);
    }
  }, [profile, capacityMw]);

  const generateReport = useCallback(async () => {
    const lat = getLat(), lon = getLon();
    try {
      const blob = await api.dc.report(lat, lon, "Site Assessment", capacityMw, profile);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "dc-site-report.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError("Report generation failed: " + e.message);
    }
  }, [explain, selectedParcel, capacityMw, profile]);

  const r = result;
  const isExtProfile = profile === "google_hyperscale" || profile === "hyperscale";
  const allDimensions = isExtProfile && (cfeData || extended)
    ? [...DIMENSIONS_9, ...DIMENSIONS_EXT]
    : DIMENSIONS_9;

  // Merge extended scores into the radar if available
  const mergedScores = r ? { ...r.scores } : {};
  if (cfeData) mergedScores.cfe_score = { score: cfeData.cfe_score || 0 };
  if (coolingData) mergedScores.cooling_climate = { score: coolingData.cooling_score || 0 };
  if (constraintData) mergedScores.constraint_clear = { score: constraintData.constraint_score || 0 };
  if (waterData) mergedScores.water_stress = { score: waterData.water_score || 0 };
  if (incentiveData) mergedScores.incentives = { score: incentiveData.incentive_score || 0 };
  if (regData) mergedScores.regulatory_pathway = { score: regData.regulatory_score || 0 };

  return (
    <div className="detail-panel-inner" style={{ padding: "12px 16px", overflowY: "auto", maxHeight: "100%" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15, color: "#e0e0e0" }}>
          Data Centre {isExtProfile ? "15D" : "9D"} Assessment
        </h3>
        {onClose && (
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#888", cursor: "pointer", fontSize: 18 }}>
            x
          </button>
        )}
      </div>

      {/* Profile selector */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 4, marginBottom: 12 }}>
        {PROFILES.map((p) => (
          <button
            key={p.key}
            onClick={() => setProfile(p.key)}
            style={{
              padding: "6px 2px", borderRadius: 6,
              border: profile === p.key ? "2px solid #D4A018" : "1px solid rgba(255,255,255,0.08)",
              background: profile === p.key ? "rgba(108,92,231,0.15)" : "transparent",
              color: "#e0e0e0", cursor: "pointer", textAlign: "center", fontSize: 10,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 700, color: profile === p.key ? "#D4A018" : "#888" }}>{p.icon}</div>
            <div style={{ fontWeight: 600, fontSize: 9 }}>{p.label}</div>
            <div style={{ fontSize: 8, color: "#666" }}>{p.range}</div>
          </button>
        ))}
      </div>

      {/* Capacity + Assess */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
        <label style={{ fontSize: 11, color: "#888", whiteSpace: "nowrap" }}>IT Load</label>
        <input
          type="range" min={1} max={500} value={capacityMw}
          onChange={(e) => setCapacityMw(+e.target.value)}
          style={{ flex: 1 }}
        />
        <span style={{ fontSize: 12, color: "#e0e0e0", minWidth: 52, textAlign: "right" }}>{capacityMw} MW</span>
        <button
          onClick={assess} disabled={loading}
          style={{
            padding: "6px 14px", borderRadius: 4, border: "none",
            background: "#D4A018", color: "#fff", fontWeight: 600, fontSize: 12,
            cursor: loading ? "wait" : "pointer", opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "..." : "Assess"}
        </button>
      </div>

      {error && <div style={{ color: "#da1e28", fontSize: 12, marginBottom: 8 }}>{error}</div>}

      {r && (
        <>
          {/* DC-SCORE hero */}
          <div style={{ textAlign: "center", marginBottom: 14 }}>
            <div style={{ fontSize: 42, fontWeight: 700, color: verdictColor(r.verdict) }}>
              {r.dc_score}
            </div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>DC-SCORE ({isExtProfile ? "15D" : "9D"})</div>
            <span style={{
              padding: "3px 12px", borderRadius: 12, fontSize: 12, fontWeight: 700,
              color: "#fff", background: verdictColor(r.verdict),
            }}>
              {r.verdict}
            </span>
            <span style={{ fontSize: 11, color: "#888", marginLeft: 8 }}>{(r.confidence * 100).toFixed(0)}% conf.</span>
          </div>

          {/* Radar chart */}
          <RadarChart scores={mergedScores} dimensions={allDimensions} size={isExtProfile ? 280 : 240} />

          {/* Weights toggle */}
          <div style={{ marginTop: 10 }}>
            <button
              onClick={() => setShowWeights(!showWeights)}
              style={{ background: "none", border: "none", color: "#D4A018", cursor: "pointer", fontSize: 11, padding: 0 }}
            >
              {showWeights ? "Hide weights" : "Show weights"}
            </button>
            {showWeights && (
              <div style={{ marginTop: 6 }}>
                {allDimensions.map((d) => (
                  <div key={d.key} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                    <span style={{ fontSize: 10, color: "#888", width: 65 }}>{d.label}</span>
                    <div style={{ flex: 1, height: 4, background: "#222", borderRadius: 2 }}>
                      <div style={{
                        width: `${r.weights?.[d.key] ?? 0}%`, height: "100%",
                        background: "#D4A018", borderRadius: 2,
                      }} />
                    </div>
                    <span style={{ fontSize: 10, color: "#aaa", width: 24, textAlign: "right" }}>{Math.round(r.weights?.[d.key] ?? 0)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Gates */}
          {r.gates && Object.keys(r.gates).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: "#888", marginBottom: 4, fontWeight: 600 }}>Gate Thresholds</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {Object.entries(r.gates).map(([k, g]) => (
                  <span key={k} style={{
                    padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
                    background: g.passed ? "rgba(36,161,72,0.15)" : "rgba(218,30,40,0.15)",
                    color: g.passed ? "#24a148" : "#da1e28",
                    border: `1px solid ${g.passed ? "#24a148" : "#da1e28"}`,
                  }}>
                    {g.passed ? "\u2713" : "\u2717"} {k.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* NEW: CFE%, Cooling, Constraints, Water, Incentives, Regulatory */}
          {isExtProfile && (
            <>
              <CFEGauge cfeData={cfeData} />
              <CoolingSection coolingData={coolingData} />
              <ConstraintBadge constraintData={constraintData} />
              <WaterStressBadge waterData={waterData} />
              <IncentiveSummary incentiveData={incentiveData} />
              <RegulatoryBadge regData={regData} />
            </>
          )}

          {/* Proximity matrix */}
          {r.proximity && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: "#888", marginBottom: 4, fontWeight: 600 }}>Proximity Matrix</div>
              <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                    <th style={{ textAlign: "left", padding: "3px 4px", color: "#888" }}>Asset</th>
                    <th style={{ textAlign: "left", padding: "3px 4px", color: "#888" }}>Name</th>
                    <th style={{ textAlign: "right", padding: "3px 4px", color: "#888" }}>Dist</th>
                    <th style={{ textAlign: "center", padding: "3px 4px", color: "#888" }}>Rating</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(r.proximity).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                      <td style={{ padding: "3px 4px", color: "#ccc", textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</td>
                      <td style={{ padding: "3px 4px", color: "#e0e0e0", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {v?.name || "--"}
                      </td>
                      <td style={{ padding: "3px 4px", color: "#e0e0e0", textAlign: "right" }}>
                        {v?.distance_km != null ? `${v.distance_km.toFixed(1)} km` : "--"}
                      </td>
                      <td style={{ padding: "3px 4px", textAlign: "center" }}>
                        {v?.rating && <span style={{ color: ratingColor(v.rating), fontWeight: 600 }}>{v.rating}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Grid headroom */}
          {r.grid_connection && (
            <div style={{ marginTop: 12, padding: 8, background: "rgba(255,255,255,0.03)", borderRadius: 6, border: "1px solid var(--cds-border-subtle)" }}>
              <div style={{ fontSize: 11, color: "#888", marginBottom: 6, fontWeight: 600 }}>Grid Headroom (REAL DATA)</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: "#666" }}>Available</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: r.grid_connection.headroom_mw != null ? "#24a148" : "#666" }}>
                    {r.grid_connection.headroom_mw != null ? `${r.grid_connection.headroom_mw} MW` : "N/A"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#666" }}>RAG Status</div>
                  <div style={{
                    fontSize: 14, fontWeight: 700,
                    color: r.grid_connection.rag_demand === "Green" ? "#24a148" :
                           r.grid_connection.rag_demand === "Amber" ? "#f1c21b" : "#da1e28",
                  }}>
                    {r.grid_connection.rag_demand || "--"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#666" }}>Queue Depth</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0" }}>{r.grid_connection.queue_depth ?? "--"}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "#666" }}>Substation</div>
                  <div style={{ fontSize: 11, color: "#e0e0e0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.grid_connection.substation || "--"}
                  </div>
                </div>
              </div>
              {r.grid_connection.cost_estimate && (
                <div style={{ marginTop: 8, display: "flex", gap: 12, justifyContent: "center" }}>
                  {["p10_gbp", "p50_gbp", "p90_gbp"].map((k) => (
                    <div key={k} style={{ textAlign: "center" }}>
                      <div style={{ fontSize: 9, color: "#666" }}>{k.split("_")[0].toUpperCase()}</div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#e0e0e0" }}>{fmtGbp(r.grid_connection.cost_estimate[k])}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Risks & Opportunities */}
          {(r.risks?.length > 0 || r.opportunities?.length > 0) && (
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {r.risks?.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: "#da1e28", fontWeight: 600, marginBottom: 4 }}>Risks</div>
                  {r.risks.map((risk, i) => (
                    <div key={i} style={{ fontSize: 10, color: "#ccc", marginBottom: 3, paddingLeft: 8, borderLeft: "2px solid #da1e28" }}>{risk}</div>
                  ))}
                </div>
              )}
              {r.opportunities?.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: "#24a148", fontWeight: 600, marginBottom: 4 }}>Opportunities</div>
                  {r.opportunities.map((opp, i) => (
                    <div key={i} style={{ fontSize: 10, color: "#ccc", marginBottom: 3, paddingLeft: 8, borderLeft: "2px solid #24a148" }}>{opp}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div style={{ marginTop: 14, display: "flex", gap: 6 }}>
            {onOpenComparison && (
              <button
                onClick={() => onOpenComparison([{ lat: getLat(), lon: getLon(), name: r.grid_connection?.substation || "Current Site" }])}
                style={{
                  flex: 1, padding: 8, borderRadius: 4,
                  border: "1px solid #D4A018", background: "transparent",
                  color: "#D4A018", fontWeight: 600, fontSize: 11, cursor: "pointer",
                }}
              >
                Compare with...
              </button>
            )}
            <button
              onClick={generateReport}
              style={{
                flex: 1, padding: 8, borderRadius: 4,
                border: "1px solid #0f62fe", background: "transparent",
                color: "#0f62fe", fontWeight: 600, fontSize: 11, cursor: "pointer",
              }}
            >
              Generate Report
            </button>
          </div>

          {/* Batch scan */}
          <div style={{ marginTop: 10, borderTop: "1px solid rgba(255,255,255,0.05)", paddingTop: 10 }}>
            <button
              onClick={scan} disabled={scanLoading}
              style={{
                width: "100%", padding: 8, borderRadius: 4,
                border: "1px solid #D4A018", background: "transparent",
                color: "#D4A018", fontWeight: 600, fontSize: 12,
                cursor: scanLoading ? "wait" : "pointer",
              }}
            >
              {scanLoading ? "Scanning..." : "Scan Region for DC Sites"}
            </button>
          </div>

          {/* Ranked sites table */}
          {scanResult?.sites?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, color: "#888", marginBottom: 4, fontWeight: 600 }}>
                Top Sites ({scanResult.count})
              </div>
              <div style={{ maxHeight: 200, overflowY: "auto" }}>
                <table style={{ width: "100%", fontSize: 10, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.08)", position: "sticky", top: 0, background: "var(--cds-layer-02)" }}>
                      <th style={{ textAlign: "left", padding: "3px 4px", color: "#888" }}>#</th>
                      <th style={{ textAlign: "left", padding: "3px 4px", color: "#888" }}>Substation</th>
                      <th style={{ textAlign: "right", padding: "3px 4px", color: "#888" }}>Score</th>
                      <th style={{ textAlign: "right", padding: "3px 4px", color: "#888" }}>Headroom</th>
                      <th style={{ textAlign: "center", padding: "3px 4px", color: "#888" }}>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scanResult.sites.map((s, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                        <td style={{ padding: "3px 4px", color: "#666" }}>{i + 1}</td>
                        <td style={{ padding: "3px 4px", color: "#e0e0e0", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {s.substation_name || `${s.lat.toFixed(2)}, ${s.lon.toFixed(2)}`}
                        </td>
                        <td style={{ padding: "3px 4px", color: verdictColor(s.verdict), textAlign: "right", fontWeight: 600 }}>
                          {s.dc_score}
                        </td>
                        <td style={{ padding: "3px 4px", color: "#e0e0e0", textAlign: "right" }}>
                          {s.grid_connection?.headroom_mw != null ? `${s.grid_connection.headroom_mw} MW` : "--"}
                        </td>
                        <td style={{ padding: "3px 4px", textAlign: "center" }}>
                          <span style={{
                            padding: "1px 6px", borderRadius: 8, fontSize: 9, fontWeight: 700,
                            color: "#fff", background: verdictColor(s.verdict),
                          }}>
                            {s.verdict}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!r && !loading && (
        <div style={{ textAlign: "center", padding: "40px 0", color: "#555" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>DC</div>
          <div style={{ fontSize: 12 }}>Select a profile and assess a site</div>
          <div style={{ fontSize: 10, marginTop: 4, color: "#444" }}>
            {isExtProfile ? "15-dimension AI scoring with 24/7 CFE%" : "9-dimension scoring"} | REAL grid headroom from all 6 UK DNOs
          </div>
        </div>
      )}
    </div>
  );
}
