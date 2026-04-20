/**
 * GridAssetDrawer — full-height right-side drawer for Grid Graph.
 *
 * For substation selections, fetches /api/grid/substation/{id}/detail and
 * renders 8 dense sections (identity, electrical, capacity, connections,
 * queue, regulatory, environment, engineering). Honours `_explanation`
 * fallbacks when upstream data is sparse and renders `—` for null values.
 *
 * For non-substation selections (ECR, GSP, licence area), falls back to a
 * basic key/value view of the feature properties.
 */
import React, { useState, useMemo, useEffect, useCallback } from "react";
import api from "../../services/api";
import { useSite } from "../../SiteContext";

const PALETTE = {
  gold:       "#C9A64B",
  goldDark:   "#A88732",
  goldLight:  "#F5E9C8",
  goldSoft:   "rgba(201,166,75,0.10)",
  ink:        "#1a1a1a",
  inkMuted:   "#4a4a4a",
  inkDim:     "#6b6560",
  inkFaint:   "#9c9590",
  border:     "#e8e5df",
  borderSoft: "#f0ece4",
  surface:    "#ffffff",
  surfaceAlt: "#faf9f6",
  ok:         "#2f8f5e",
  warn:       "#b88512",
  bad:        "#b03a3a",
};

const KIND_COLOR = {
  substation:    PALETTE.gold,
  ecr:           "#7c3aed",
  gsp:           "#2563eb",
  licence_area:  "#16a34a",
};

const TABS = [
  { id: "overview",    label: "Overview"    },
  { id: "electrical",  label: "Electrical"  },
  { id: "capacity",    label: "Capacity"    },
  { id: "connections", label: "Connections" },
  { id: "queue",       label: "Queue"       },
  { id: "regulatory",  label: "Regulatory"  },
  { id: "environment", label: "Environment" },
  { id: "engineering", label: "Engineering" },
];

/* ── Hook: fetch enriched detail when a substation id changes ─────────── */
function useSubstationDetail(id) {
  const [state, setState] = useState({ data: null, loading: false, error: null });

  useEffect(() => {
    if (!id) { setState({ data: null, loading: false, error: null }); return; }
    let cancelled = false;
    setState(s => ({ ...s, loading: true, error: null }));
    api.grid.substationDetail(id)
      .then(data => { if (!cancelled) setState({ data, loading: false, error: null }); })
      .catch(err => { if (!cancelled) setState({ data: null, loading: false, error: err?.message || String(err) }); });
    return () => { cancelled = true; };
  }, [id]);

  return state;
}

/* ── Primitives ─────────────────────────────────────────────────────────── */
function fmtNum(v, opts = {}) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const { dp = 0, suffix = "" } = opts;
  return `${n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}${suffix}`;
}

function KV({ label, value, mono = true, muted = false }) {
  const display = value == null || value === "" ? "—" : value;
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      gap: 12,
      padding: "6px 0",
      borderBottom: `1px dashed ${PALETTE.borderSoft}`,
      fontSize: 12,
    }}>
      <span style={{
        color: PALETTE.inkFaint,
        fontSize: 10,
        letterSpacing: 0.5,
        textTransform: "uppercase",
        flexShrink: 0,
      }}>{label}</span>
      <span style={{
        fontFamily: mono ? "'JetBrains Mono', monospace" : "inherit",
        fontWeight: 600,
        color: muted ? PALETTE.inkDim : PALETTE.ink,
        fontSize: 13,
        textAlign: "right",
        wordBreak: "break-word",
      }}>{display}</span>
    </div>
  );
}

function SectionHead({ children }) {
  return (
    <div style={{
      fontSize: 10,
      fontWeight: 700,
      letterSpacing: 0.7,
      textTransform: "uppercase",
      color: PALETTE.inkFaint,
      marginTop: 16,
      marginBottom: 8,
    }}>{children}</div>
  );
}

function Explanation({ text }) {
  if (!text) return null;
  return (
    <div style={{
      padding: "10px 12px",
      background: PALETTE.surfaceAlt,
      border: `1px dashed ${PALETTE.border}`,
      borderRadius: 6,
      fontSize: 11,
      color: PALETTE.inkDim,
      fontStyle: "italic",
      lineHeight: 1.45,
    }}>{text}</div>
  );
}

function KpiTile({ label, value, suffix = "", tone = "ink" }) {
  const colorMap = { ink: PALETTE.ink, ok: PALETTE.ok, warn: PALETTE.warn, bad: PALETTE.bad };
  return (
    <div style={{
      flex: 1,
      minWidth: 0,
      padding: "10px 12px",
      background: PALETTE.surfaceAlt,
      border: `1px solid ${PALETTE.border}`,
      borderRadius: 6,
    }}>
      <div style={{
        fontSize: 9,
        letterSpacing: 0.6,
        textTransform: "uppercase",
        color: PALETTE.inkFaint,
        marginBottom: 4,
        whiteSpace: "nowrap",
        overflow: "hidden",
        textOverflow: "ellipsis",
      }}>{label}</div>
      <div style={{
        fontSize: 18,
        fontWeight: 700,
        fontFamily: "'JetBrains Mono', monospace",
        color: colorMap[tone] || PALETTE.ink,
        lineHeight: 1.1,
      }}>
        {value == null ? "—" : value}
        {value != null && suffix && <span style={{ fontSize: 11, color: PALETTE.inkDim, marginLeft: 3 }}>{suffix}</span>}
      </div>
    </div>
  );
}

function ListRow({ children, onClick, action }) {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 8,
      padding: "8px 10px",
      borderBottom: `1px solid ${PALETTE.borderSoft}`,
      fontSize: 12,
      cursor: onClick ? "pointer" : "default",
    }}
      onClick={onClick}
      onMouseEnter={onClick ? (e) => { e.currentTarget.style.background = PALETTE.goldSoft; } : undefined}
      onMouseLeave={onClick ? (e) => { e.currentTarget.style.background = "transparent"; } : undefined}
    >
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
      {action}
    </div>
  );
}

function MapAction({ onClick, label = "Map" }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      style={{
        background: "transparent",
        border: `1px solid ${PALETTE.border}`,
        color: PALETTE.goldDark,
        fontSize: 10,
        padding: "3px 8px",
        borderRadius: 4,
        cursor: "pointer",
        fontWeight: 600,
        letterSpacing: 0.3,
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        fontFamily: "inherit",
      }}>{label}</button>
  );
}

function SkeletonBlock({ height = 14, width = "100%", mb = 6 }) {
  return (
    <div style={{
      height, width, marginBottom: mb,
      background: `linear-gradient(90deg, ${PALETTE.borderSoft} 0%, ${PALETTE.border} 50%, ${PALETTE.borderSoft} 100%)`,
      borderRadius: 4,
      backgroundSize: "200% 100%",
      animation: "princeps-shimmer 1.4s linear infinite",
    }} />
  );
}

/* ── Section renderers ─────────────────────────────────────────────────── */
function OverviewSection({ detail, onSwapSubstation, onFlyTo }) {
  const id = detail?.identity || {};
  const cap = detail?.capacity_state || {};
  const elec = detail?.electrical || {};
  const reg = detail?.regulatory || {};

  const headroomPct = (() => {
    const dh = cap.demand_headroom_mw;
    const total = elec.system_capacity_mw;
    if (dh == null || !total) return null;
    return Math.round((dh / total) * 100);
  })();
  const headroomTone = headroomPct == null ? "ink"
    : headroomPct > 30 ? "ok" : headroomPct > 10 ? "warn" : "bad";

  const queueDepth = cap.accepted_queue_mw != null && cap.in_progress_queue_mw != null
    ? cap.accepted_queue_mw + cap.in_progress_queue_mw : null;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
        <KpiTile label="Firm MVA" value={fmtNum(elec.firm_capacity_mw, { dp: 1 })} suffix="MW" />
        <KpiTile label="Headroom" value={headroomPct} suffix="%" tone={headroomTone} />
        <KpiTile label="Queue MW" value={fmtNum(queueDepth, { dp: 1 })} />
      </div>

      <SectionHead>Identity</SectionHead>
      <KV label="Operator"   value={id.operator || id.ownership} mono={false} />
      <KV label="DNO"        value={reg.dno} />
      <KV label="GSP / BSP"  value={id.gsp_bsp_primary} />
      <KV label="Licence"    value={reg.licensed_area} />
      <KV label="Voltage"    value={elec.voltage_kv_primary != null ? `${elec.voltage_kv_primary} kV` : null} />
      <KV label="OS Grid Ref" value={id.osgb_ref} />
      <KV label="Lat / Lon"  value={id.lat != null && id.lon != null ? `${id.lat.toFixed(4)}, ${id.lon.toFixed(4)}` : null} />
      <KV label="Asset Code" value={id.asset_code_dno} />
      <KV label="NESO MRID"  value={id.asset_code_neso} />
      <KV label="Commissioned" value={id.commissioning_year} />

      {id.alt_names?.length > 0 && (
        <>
          <SectionHead>Alt names</SectionHead>
          <div style={{ fontSize: 12, color: PALETTE.inkDim, fontFamily: "'JetBrains Mono', monospace" }}>
            {id.alt_names.join(" · ")}
          </div>
        </>
      )}

      <SectionHead>Provenance</SectionHead>
      <KV label="Source"        value={id.data_provenance} mono={false} muted />
      <KV label="Last refreshed" value={id.last_refreshed_utc} muted />
      <KV label="Stale (days)"  value={id.stale_days} muted />

      {(id.lat != null && id.lon != null) && (
        <div style={{ marginTop: 14 }}>
          <button
            onClick={() => onFlyTo(id.lat, id.lon)}
            style={{
              width: "100%",
              padding: "8px",
              background: PALETTE.gold,
              color: "#fff",
              border: "none",
              borderRadius: 6,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: 0.4,
              textTransform: "uppercase",
              cursor: "pointer",
              fontFamily: "inherit",
            }}>Centre map on substation</button>
        </div>
      )}
    </div>
  );
}

function ElectricalSection({ detail }) {
  const e = detail?.electrical || {};
  return (
    <div>
      {e._explanation && <><Explanation text={e._explanation} /><div style={{ height: 12 }} /></>}
      <SectionHead>Voltage</SectionHead>
      <KV label="Primary"    value={e.voltage_kv_primary != null ? `${e.voltage_kv_primary} kV` : null} />
      <KV label="Secondary"  value={e.voltage_kv_secondary != null ? `${e.voltage_kv_secondary} kV` : null} />
      <KV label="Levels"     value={e.voltage_levels_present?.length ? e.voltage_levels_present.map(v => `${v}kV`).join(" · ") : null} />

      <SectionHead>Transformers</SectionHead>
      <KV label="Count"      value={e.transformer_count} />
      <KV label="Total MVA"  value={fmtNum(e.total_mva, { dp: 1 })} />
      <KV label="Firm (N-1)" value={fmtNum(e.firm_capacity_mw, { dp: 1, suffix: " MW" })} />
      <KV label="System"     value={fmtNum(e.system_capacity_mw, { dp: 1, suffix: " MW" })} />
      {e.transformer_mva_ratings?.length > 0 && (
        <KV label="Ratings"  value={e.transformer_mva_ratings.map(r => `${r}MVA`).join(" · ")} />
      )}

      <SectionHead>Fault Levels</SectionHead>
      <KV label="3-phase"    value={fmtNum(e.fault_level_3ph_ka, { dp: 2, suffix: " kA" })} />
      <KV label="1-phase"    value={fmtNum(e.fault_level_1ph_ka, { dp: 2, suffix: " kA" })} />

      <SectionHead>Layout</SectionHead>
      <KV label="Bus arrangement" value={e.bus_arrangement} mono={false} />
      <KV label="Reactive comp"   value={e.reactive_compensation} mono={false} />
      <KV label="Protection"      value={e.protection_scheme} mono={false} />
    </div>
  );
}

function CapacitySection({ detail }) {
  const c = detail?.capacity_state || {};
  const ha = c.headroom_analysis || {};
  return (
    <div>
      {c._explanation && <><Explanation text={c._explanation} /><div style={{ height: 12 }} /></>}
      <SectionHead>Headroom (firm)</SectionHead>
      <KV label="Demand"            value={fmtNum(c.demand_headroom_mw, { dp: 1, suffix: " MW" })} />
      <KV label="Generation firm"   value={fmtNum(c.generation_headroom_firm_mw, { dp: 1, suffix: " MW" })} />
      <KV label="Generation non-firm" value={fmtNum(c.generation_headroom_non_firm_mw, { dp: 1, suffix: " MW" })} />

      <SectionHead>Probabilistic headroom</SectionHead>
      <KV label="P50"        value={fmtNum(ha.value, { dp: 1, suffix: " MW" })} />
      <KV label="P10"        value={fmtNum(ha.p10, { dp: 1, suffix: " MW" })} />
      <KV label="P90"        value={fmtNum(ha.p90, { dp: 1, suffix: " MW" })} />
      <KV label="Confidence" value={ha.confidence != null ? `${(ha.confidence * 100).toFixed(0)}%` : null} />

      <SectionHead>Queue</SectionHead>
      <KV label="Accepted"    value={fmtNum(c.accepted_queue_mw, { dp: 1, suffix: " MW" })} />
      <KV label="In-progress" value={fmtNum(c.in_progress_queue_mw, { dp: 1, suffix: " MW" })} />

      <SectionHead>Utilisation (12m)</SectionHead>
      <KV label="Peak summer" value={c.utilisation_pct_peak_summer != null ? `${c.utilisation_pct_peak_summer}%` : null} />
      <KV label="Peak winter" value={c.utilisation_pct_peak_winter != null ? `${c.utilisation_pct_peak_winter}%` : null} />
      <KV label="Average"     value={c.utilisation_pct_avg != null ? `${c.utilisation_pct_avg}%` : null} />

      <SectionHead>Congestion (12m)</SectionHead>
      <KV label="Episodes"           value={c.congestion_episodes_12m} />
      <KV label="P28 voltage events" value={c.voltage_p28_exceedances_12m} />
      <KV label="Curtailment cost"   value={c.curtailment_cost_12m_gbp != null ? `£${c.curtailment_cost_12m_gbp.toLocaleString()}` : null} />
    </div>
  );
}

function ConnectionsSection({ detail, onSwapSubstation, onFlyTo }) {
  const c = detail?.connections || {};
  const circuits = c.circuits || [];
  const adjacent = c.adjacent_substations || [];
  const generators = c.generators_connected || [];
  const demands = c.large_demands_connected || [];

  return (
    <div>
      {c._explanation && <><Explanation text={c._explanation} /><div style={{ height: 12 }} /></>}

      <SectionHead>Circuits ({circuits.length})</SectionHead>
      {circuits.length === 0 ? <Explanation text="No circuits in grid_lines for this substation." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {circuits.map((c, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: 600, color: PALETTE.ink }}>{c.name}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11 }}>
                  {c.length_km != null ? `${c.length_km.toFixed(1)}km` : "—"}
                </span>
              </div>
              {c.to_substation && (
                <div style={{ fontSize: 10, color: PALETTE.inkFaint, marginTop: 2 }}>→ {c.to_substation}</div>
              )}
            </ListRow>
          ))}
        </div>
      )}

      <SectionHead>Adjacent substations ({adjacent.length})</SectionHead>
      {adjacent.length === 0 ? <Explanation text="No substations within 20 km." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {adjacent.map((a, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: 600, color: PALETTE.ink }}>{a.name}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11 }}>
                  {a.distance_km != null ? `${a.distance_km}km` : "—"}
                </span>
              </div>
              <div style={{ fontSize: 10, color: PALETTE.inkFaint, marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
                {a.voltage_kv != null ? `${a.voltage_kv}kV` : ""}
                {a.capacity_mva != null ? ` · ${a.capacity_mva}MVA` : ""}
              </div>
            </ListRow>
          ))}
        </div>
      )}

      <SectionHead>Generators connected ({generators.length})</SectionHead>
      {generators.length === 0 ? <Explanation text="No generators in ECR/TEC for this substation." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {generators.map((g, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: 600, color: PALETTE.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.name || "Unnamed"}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11, flexShrink: 0 }}>
                  {g.mw != null ? `${g.mw}MW` : "—"}
                </span>
              </div>
              <div style={{ fontSize: 10, color: PALETTE.inkFaint, marginTop: 2 }}>
                {g.technology || ""}{g.energised_date ? ` · ${g.energised_date}` : ""}
              </div>
            </ListRow>
          ))}
        </div>
      )}

      {demands.length > 0 && (
        <>
          <SectionHead>Large demands ({demands.length})</SectionHead>
          <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
            {demands.map((d, i) => (
              <ListRow key={i}>
                <div>{d.name}</div>
              </ListRow>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function QueueSection({ detail, onFlyTo }) {
  const q = detail?.queue || {};
  const accepted = q.accepted || [];
  const applied = q.applied || [];
  const summary = q.summary || {};

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
        <KpiTile label="Accepted" value={summary.accepted_count} />
        <KpiTile label="Applied"  value={summary.applied_count} />
        <KpiTile label="Earliest" value={summary.earliest_viable_year} />
      </div>

      {q._explanation && <><div style={{ height: 12 }} /><Explanation text={q._explanation} /></>}

      <SectionHead>Accepted ({accepted.length})</SectionHead>
      {accepted.length === 0 ? <Explanation text="No accepted queue entries." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {accepted.map((p, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: 600, color: PALETTE.ink, overflow: "hidden", textOverflow: "ellipsis" }}>{p.project_name || "Unnamed"}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11 }}>
                  {p.mw != null ? `${p.mw}MW` : "—"}
                </span>
              </div>
              <div style={{ fontSize: 10, color: PALETTE.inkFaint, marginTop: 2 }}>
                {p.technology || ""}{p.energisation_year ? ` · ${p.energisation_year}` : ""}{p.dev_status ? ` · ${p.dev_status}` : ""}
              </div>
            </ListRow>
          ))}
        </div>
      )}

      <SectionHead>Applied ({applied.length})</SectionHead>
      {applied.length === 0 ? <Explanation text="No applied queue entries." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {applied.map((p, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ fontWeight: 600, color: PALETTE.ink, overflow: "hidden", textOverflow: "ellipsis" }}>{p.project_name || "Unnamed"}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11 }}>
                  {p.mw != null ? `${p.mw}MW` : "—"}
                </span>
              </div>
              <div style={{ fontSize: 10, color: PALETTE.inkFaint, marginTop: 2 }}>
                {p.technology || ""}{p.energisation_year ? ` · ${p.energisation_year}` : ""}{p.dev_status ? ` · ${p.dev_status}` : ""}
              </div>
            </ListRow>
          ))}
        </div>
      )}

      {summary.queue_depth_ratio != null && (
        <>
          <SectionHead>Depth ratio</SectionHead>
          <KV label="Applied / Firm" value={summary.queue_depth_ratio.toFixed(2)} />
        </>
      )}
    </div>
  );
}

function RegulatorySection({ detail }) {
  const r = detail?.regulatory || {};
  const ltds = r.ltds_citation;
  return (
    <div>
      <SectionHead>Network operator</SectionHead>
      <KV label="DNO"          value={r.dno} mono={false} />
      <KV label="Area code"    value={r.dno_area_code} />
      <KV label="Licensed"     value={r.licensed_area} mono={false} />

      <SectionHead>Charging methodology</SectionHead>
      <KV label="CCCM zone"    value={r.cccm_zone} />
      <KV label="CCCM version" value={r.cccm_version} />
      <KV label="BSUoS zone"   value={r.bsuos_zone} mono={false} />
      <KV label="TNUoS zone"   value={r.tnuos_zone_tl_code} mono={false} />

      <SectionHead>LTDS citation</SectionHead>
      {!ltds ? <Explanation text={r._explanation || "No LTDS citation available."} /> : (
        <div style={{
          padding: 10,
          border: `1px solid ${PALETTE.border}`,
          borderRadius: 6,
          background: PALETTE.surfaceAlt,
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: PALETTE.ink, marginBottom: 4 }}>{ltds.publication}</div>
          <div style={{ fontSize: 11, color: PALETTE.inkDim, marginBottom: 2 }}>{ltds.date}</div>
          <div style={{ fontSize: 11, color: PALETTE.inkDim, marginBottom: 6 }}>{ltds.table_ref}{ltds.page_ref ? ` · p.${ltds.page_ref}` : ""}</div>
          {ltds.url && (
            <a href={ltds.url} target="_blank" rel="noreferrer"
              style={{ fontSize: 10, color: PALETTE.goldDark, textDecoration: "underline", letterSpacing: 0.3 }}>
              Source ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function EnvironmentSection({ detail }) {
  const e = detail?.environment || {};
  const designations = e.designations_within_500m || [];
  return (
    <div>
      {e._explanation && <><Explanation text={e._explanation} /><div style={{ height: 12 }} /></>}

      <SectionHead>Distance to nearest</SectionHead>
      <KV label="AONB"  value={e.aonb_distance_km != null ? `${e.aonb_distance_km} km` : null} />
      <KV label="SSSI"  value={e.sssi_distance_km != null ? `${e.sssi_distance_km} km` : null} />

      <SectionHead>Within 500 m ({designations.length})</SectionHead>
      {designations.length === 0 ? <Explanation text="No designations within 500 m." /> : (
        <div style={{ border: `1px solid ${PALETTE.border}`, borderRadius: 6, overflow: "hidden" }}>
          {designations.map((d, i) => (
            <ListRow key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>
                  <span style={{
                    fontSize: 9, fontWeight: 700, letterSpacing: 0.4,
                    padding: "2px 5px", borderRadius: 3, marginRight: 6,
                    background: PALETTE.goldSoft, color: PALETTE.goldDark,
                    textTransform: "uppercase",
                  }}>{d.type}</span>
                  <span style={{ fontWeight: 600, color: PALETTE.ink }}>{d.name || "Unnamed"}</span>
                </span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, fontSize: 11 }}>
                  {d.distance_m != null ? `${d.distance_m}m` : "—"}
                </span>
              </div>
            </ListRow>
          ))}
        </div>
      )}

      <SectionHead>Flood risk (500 m)</SectionHead>
      <KV label="Zone 2 nearby" value={e.flood_zone_2_within_500m ? "Yes" : "No"} />
      <KV label="Zone 3 nearby" value={e.flood_zone_3_within_500m ? "Yes" : "No"} />

      <SectionHead>Land</SectionHead>
      <KV label="ALC grade"   value={e.alc_grade_dominant} />
      <KV label="Land use"    value={e.land_use_nearby} mono={false} />
      <KV label="Receptors"   value={e.noise_sensitive_receptor_count} />
      <KV label="Access road" value={e.access_road_class} mono={false} />
    </div>
  );
}

function EngineeringSection({ detail }) {
  const e = detail?.engineering || {};
  const upgrades = e.upgrade_options || [];
  return (
    <div>
      {e._explanation && <><Explanation text={e._explanation} /><div style={{ height: 12 }} /></>}

      <SectionHead>Asset condition</SectionHead>
      <KV label="Health index"    value={e.asset_condition_hi} />
      <KV label="Defects (12m)"   value={e.known_defects_12m} />
      <KV label="Outages (12m)"   value={e.scheduled_outages_next_12m} />
      <KV label="Equipment age"   value={e.equipment_age_years != null ? `${e.equipment_age_years} yr` : null} />
      <KV label="Insulation"      value={e.insulation_type} mono={false} />

      <SectionHead>Reinforcement</SectionHead>
      {!e.reinforcement_planned ? (
        <Explanation text="No reinforcement planned in raw data." />
      ) : (
        <div style={{ fontSize: 12, color: PALETTE.ink, padding: 8, background: PALETTE.surfaceAlt, border: `1px solid ${PALETTE.border}`, borderRadius: 6 }}>
          {typeof e.reinforcement_planned === "string"
            ? e.reinforcement_planned
            : <pre style={{ margin: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, whiteSpace: "pre-wrap" }}>{JSON.stringify(e.reinforcement_planned, null, 2)}</pre>}
        </div>
      )}

      <SectionHead>Upgrade options ({upgrades.length})</SectionHead>
      {upgrades.length === 0 ? <Explanation text="No upgrade scenarios modelled." /> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {upgrades.map((u, i) => (
            <div key={i} style={{ padding: 10, border: `1px solid ${PALETTE.border}`, borderRadius: 6, background: PALETTE.surfaceAlt }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: PALETTE.ink, marginBottom: 6 }}>{u.option}</div>
              <div style={{ display: "flex", gap: 12, fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: PALETTE.inkDim, marginBottom: 6 }}>
                <span>Reach: <span style={{ color: PALETTE.ink, fontWeight: 600 }}>{u.to_reach_mw}MW</span></span>
                <span>CAPEX: <span style={{ color: PALETTE.ink, fontWeight: 600 }}>£{u.capex_gbp_m}m</span></span>
                <span>Payback: <span style={{ color: PALETTE.ink, fontWeight: 600 }}>{u.payback_years}yr</span></span>
              </div>
              {u.notes && <div style={{ fontSize: 11, color: PALETTE.inkDim, fontStyle: "italic", lineHeight: 1.45 }}>{u.notes}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Loading + error + non-substation fallback ─────────────────────────── */
function LoadingBody() {
  return (
    <div>
      <SkeletonBlock height={56} mb={8} />
      <SkeletonBlock height={20} width="40%" mb={10} />
      {Array.from({ length: 7 }).map((_, i) => <SkeletonBlock key={i} height={14} width={i % 2 ? "70%" : "100%"} />)}
    </div>
  );
}

function ErrorBody({ error, id }) {
  return (
    <div style={{
      padding: "14px 16px",
      background: "#fef3f3",
      border: `1px solid #f3c5c5`,
      borderRadius: 6,
      fontSize: 12,
      color: "#7a2424",
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6, letterSpacing: 0.3, textTransform: "uppercase", fontSize: 10 }}>Detail fetch failed</div>
      <div style={{ marginBottom: 6 }}>Substation {id}</div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{error}</div>
    </div>
  );
}

function FallbackKVs({ properties }) {
  const present = Object.entries(properties || {}).filter(([, v]) => v != null && v !== "");
  if (present.length === 0) {
    return <Explanation text="No properties on this feature." />;
  }
  return (
    <div>
      {present.map(([k, v]) => (
        <KV key={k} label={k.replace(/_/g, " ")} value={String(v)} />
      ))}
    </div>
  );
}

/* ── Main component ─────────────────────────────────────────────────────── */
export default function GridAssetDrawer({ selection, onClose, slots = {}, width = 380 }) {
  const [tab, setTab] = useState("overview");
  const [overrideSubstationId, setOverrideSubstationId] = useState(null);
  const { setPickedLocation } = useSite() || {};

  const props = selection?.feature?.properties || {};
  const kind = selection?.kind || "substation";
  const isSubstation = kind === "substation";

  const featureSubstationId = props.id;
  const substationId = isSubstation ? (overrideSubstationId ?? featureSubstationId) : null;
  const { data: detail, loading, error } = useSubstationDetail(substationId);

  // Reset internal state when the parent selection changes.
  useEffect(() => { setOverrideSubstationId(null); setTab("overview"); }, [featureSubstationId]);

  const kindLabel = useMemo(() => ({
    substation:   "Substation",
    ecr:          "ECR Project",
    gsp:          "GSP",
    licence_area: "Licence Area",
  }[kind] || kind), [kind]);

  const headerName = detail?.identity?.name || props.name || props.external_id || props.id || "Unnamed";
  const subtitle = isSubstation
    ? [
        detail?.regulatory?.dno || props.dno,
        detail?.electrical?.voltage_kv_primary != null ? `${Math.round(detail.electrical.voltage_kv_primary)} kV` : (props.voltage_kv != null ? `${Math.round(props.voltage_kv)} kV` : null),
        detail?.identity?.osgb_ref || props.site_type,
      ].filter(Boolean).join(" \u00B7 ")
    : [props.dno, props.site_type].filter(Boolean).join(" \u00B7 ");

  const onFlyTo = useCallback((lat, lon) => {
    if (typeof setPickedLocation === "function" && lat != null && lon != null) {
      setPickedLocation({ lat, lon });
    }
  }, [setPickedLocation]);

  const onSwapSubstation = useCallback((newId) => {
    if (newId != null) { setOverrideSubstationId(newId); setTab("overview"); }
  }, []);

  const renderBody = () => {
    if (!isSubstation) {
      const slotFn = slots[tab];
      if (typeof slotFn === "function") return slotFn({ selection, props });
      if (slotFn) return slotFn;
      return <FallbackKVs properties={props} />;
    }
    if (loading && !detail) return <LoadingBody />;
    if (error && !detail) return <ErrorBody error={error} id={substationId} />;
    if (!detail) return <FallbackKVs properties={props} />;

    switch (tab) {
      case "overview":    return <OverviewSection    detail={detail} onFlyTo={onFlyTo} onSwapSubstation={onSwapSubstation} />;
      case "electrical":  return <ElectricalSection  detail={detail} />;
      case "capacity":    return <CapacitySection    detail={detail} />;
      case "connections": return <ConnectionsSection detail={detail} onSwapSubstation={onSwapSubstation} onFlyTo={onFlyTo} />;
      case "queue":       return <QueueSection       detail={detail} onFlyTo={onFlyTo} />;
      case "regulatory":  return <RegulatorySection  detail={detail} />;
      case "environment": return <EnvironmentSection detail={detail} />;
      case "engineering": return <EngineeringSection detail={detail} />;
      default:            return <OverviewSection    detail={detail} onFlyTo={onFlyTo} onSwapSubstation={onSwapSubstation} />;
    }
  };

  const tabsToShow = isSubstation ? TABS : TABS.slice(0, 1);

  return (
    <aside
      className="grid-asset-drawer"
      aria-label={`${kindLabel} detail`}
      style={{
        width,
        flexShrink: 0,
        height: "100%",
        background: PALETTE.surface,
        borderLeft: `1px solid ${PALETTE.border}`,
        display: "flex",
        flexDirection: "column",
        fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
        color: PALETTE.ink,
      }}
    >
      <style>{`@keyframes princeps-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>

      <header style={{
        padding: "14px 18px 12px",
        borderBottom: `1px solid ${PALETTE.border}`,
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={{
            padding: "2px 8px",
            borderRadius: 10,
            fontSize: 9,
            fontWeight: 700,
            background: KIND_COLOR[kind] || PALETTE.gold,
            color: "#fff",
            letterSpacing: 0.4,
            textTransform: "uppercase",
          }}>{kindLabel}</span>
          {loading && (
            <span style={{
              fontSize: 9, color: PALETTE.inkFaint, letterSpacing: 0.4, textTransform: "uppercase",
            }}>loading…</span>
          )}
          <div style={{ flex: 1 }} />
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: 24, height: 24, borderRadius: 12,
              background: "transparent",
              border: `1px solid ${PALETTE.border}`,
              color: PALETTE.inkDim,
              cursor: "pointer",
              fontSize: 14,
              lineHeight: 1,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>&times;</button>
        </div>
        <div style={{
          fontSize: 16,
          fontWeight: 700,
          color: PALETTE.ink,
          lineHeight: 1.25,
          letterSpacing: "-0.01em",
        }}>{headerName}</div>
        {subtitle && (
          <div style={{
            fontSize: 11,
            color: PALETTE.inkDim,
            marginTop: 4,
            fontFamily: "'JetBrains Mono', monospace",
          }}>{subtitle}</div>
        )}
      </header>

      <nav style={{
        display: "flex",
        gap: 0,
        padding: "0 18px",
        borderBottom: `1px solid ${PALETTE.border}`,
        flexShrink: 0,
        overflowX: "auto",
        overflowY: "hidden",
      }}>
        {tabsToShow.map(t => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: "10px 0",
                marginRight: 16,
                background: "transparent",
                border: "none",
                borderBottom: active ? `2px solid ${PALETTE.gold}` : "2px solid transparent",
                color: active ? PALETTE.ink : PALETTE.inkDim,
                fontSize: 10.5,
                fontWeight: active ? 700 : 500,
                letterSpacing: 0.3,
                cursor: "pointer",
                textTransform: "uppercase",
                whiteSpace: "nowrap",
                fontFamily: "inherit",
              }}>{t.label}</button>
          );
        })}
      </nav>

      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "16px 18px 24px",
        background: PALETTE.surface,
      }}>
        {renderBody()}
      </div>
    </aside>
  );
}
