import React, { useEffect, useState } from "react";
import { useParcelDossier } from "../../hooks/useParcelDossier.js";

const GOLD = "#F5B731";
const IVORY = "#FBF8F2";
const INK = "#0F1318";

export default function ParcelDrawer() {
  const [inspireId, setInspireId] = useState(null);
  const { data, loading, error } = useParcelDossier(inspireId);

  useEffect(() => {
    const open = (e) => setInspireId(e.detail?.inspire_id || null);
    const close = () => setInspireId(null);
    window.addEventListener("princeps-open-parcel", open);
    window.addEventListener("princeps-close-parcel", close);
    const esc = (e) => { if (e.key === "Escape") setInspireId(null); };
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("princeps-open-parcel", open);
      window.removeEventListener("princeps-close-parcel", close);
      window.removeEventListener("keydown", esc);
    };
  }, []);

  if (!inspireId) return null;

  return (
    <>
      <div
        onClick={() => setInspireId(null)}
        style={{
          position: "fixed", inset: 0, background: "rgba(15,19,24,0.28)",
          zIndex: 9998,
        }}
      />
      <aside
        style={{
          position: "fixed", top: 0, right: 0, bottom: 0, width: 480,
          background: IVORY, borderLeft: `1px solid rgba(15,19,24,0.08)`,
          boxShadow: "-8px 0 24px rgba(15,19,24,0.12)",
          zIndex: 9999, overflowY: "auto",
          fontFamily: "'DM Sans', sans-serif", color: INK,
        }}
      >
        <header style={{
          padding: "16px 20px", borderBottom: `1px solid rgba(15,19,24,0.08)`,
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          position: "sticky", top: 0, background: IVORY, zIndex: 2,
        }}>
          <div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
              color: "#6B7280",
            }}>{inspireId}</div>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "4px 0 0" }}>
              {loading ? "Loading parcel…" : data?.display_name || "Parcel dossier"}
            </h2>
          </div>
          <button
            onClick={() => setInspireId(null)}
            style={{
              background: "transparent", border: "none", fontSize: 20,
              cursor: "pointer", color: INK, padding: 4,
            }}
            aria-label="Close"
          >×</button>
        </header>

        {error && (
          <div style={{ padding: 20, color: "#B84A4A", fontSize: 13 }}>
            Failed to load parcel: {String(error)}
          </div>
        )}

        {data && (
          <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
            <Section title="At a glance">
              <KV k="Area" v={fmtHa(data.area_ha)} />
              <KV k="LPA" v={data.lpa || "—"} />
              <KV k="Parish" v={data.parish || "—"} />
              <KV k="DNO" v={data.dno_slug || "—"} pill />
              <KV k="Country" v={data.country || "—"} />
            </Section>

            <Section title="Ownership">
              <KV k="Title number" v={data.hmlr_title_number || "— (paid tier)"} />
              <KV k="Proprietor" v={data.hmlr_proprietor || "— (paid tier)"} />
              <KV k="Charges" v={(data.charges || []).length ? `${data.charges.length} filings` : "None"} />
            </Section>

            <Section title="Planning (5y)">
              {(data.planning_history_5y || []).slice(0, 5).map((p, i) => (
                <Row key={i} label={p.decision_date || "—"} value={p.description || p.status}
                     pill={p.status} pillColour={statusColour(p.status)} />
              ))}
              {(!data.planning_history_5y || data.planning_history_5y.length === 0) &&
                <Empty>No planning history in range.</Empty>}
            </Section>

            <Section title="REPD overlap">
              {(data.repd_overlap_projects || []).slice(0, 5).map((p, i) => (
                <Row key={i} label={p.tech} value={p.name}
                     pill={p.status} pillColour={statusColour(p.status)} />
              ))}
              {(!data.repd_overlap_projects || data.repd_overlap_projects.length === 0) &&
                <Empty>No REPD projects overlap.</Empty>}
            </Section>

            <Section title="Constraints">
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {Object.entries(data.constraints || {}).map(([k, v]) => (
                  <div key={k} style={{
                    padding: "6px 8px",
                    border: `1px solid ${v?.triggered ? "#B84A4A" : "rgba(15,19,24,0.15)"}`,
                    borderRadius: 6,
                    background: v?.triggered ? "rgba(184,74,46,0.06)" : "transparent",
                    fontSize: 11,
                  }}>
                    <div style={{ fontWeight: 600, textTransform: "capitalize" }}>
                      {k.replace(/_/g, " ")}
                    </div>
                    <div style={{ color: "#6B7280", marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
                      {v?.triggered ? `Yes · ${v.distance_m || 0}m` : "Clear"}
                    </div>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Grid">
              <KV k="Nearest POC" v={data.nearest_poc_substation?.name || "—"} />
              <KV k="Voltage" v={data.nearest_poc_substation?.voltage_kv ? `${data.nearest_poc_substation.voltage_kv} kV` : "—"} />
              <KV k="Distance" v={data.nearest_poc_substation?.distance_m ? `${data.nearest_poc_substation.distance_m}m` : "—"} />
              <KV k="Firm headroom" v={data.nearest_poc_substation?.firm_headroom_mw != null ? `${data.nearest_poc_substation.firm_headroom_mw} MW` : "—"} pill />
            </Section>

            <Section title="Buildable mask">
              <KV k="Buildable" v={fmtHa(data.buildable_mask_result?.buildable_ha)} pill />
              {(data.buildable_mask_result?.exclusion_reasons || []).map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: "#6B7280" }}>· {r}</div>
              ))}
            </Section>

            {(data.similar_parcels || []).length > 0 && (
              <Section title="Similar parcels">
                {(data.similar_parcels || []).slice(0, 5).map((s, i) => (
                  <Row key={i} label={`#${i + 1}`} value={s.inspire_id}
                       pill={`${(s.cosine_distance * 100).toFixed(0)}%`} />
                ))}
              </Section>
            )}
          </div>
        )}

        <footer style={{
          padding: 16, borderTop: `1px solid rgba(15,19,24,0.08)`,
          display: "flex", gap: 8, position: "sticky", bottom: 0, background: IVORY,
        }}>
          <Btn primary>Pin to project ◆</Btn>
          <Btn>Shortlist ⭐</Btn>
          {data?.hmlr_url && (
            <a href={data.hmlr_url} target="_blank" rel="noreferrer noopener"
               style={{ textDecoration: "none" }}>
              <Btn>HMLR ↗</Btn>
            </a>
          )}
        </footer>
      </aside>
    </>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <div style={{
        fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
        textTransform: "uppercase", color: "#6B7280", marginBottom: 8,
      }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {children}
      </div>
    </section>
  );
}
function KV({ k, v, pill }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13 }}>
      <span style={{ color: "#6B7280" }}>{k}</span>
      <span style={pill ? {
        fontFamily: "'JetBrains Mono', monospace", fontWeight: 600,
        padding: "2px 8px", borderRadius: 999,
        background: `${GOLD}22`, color: "#7A5820",
      } : { fontFamily: "'JetBrains Mono', monospace" }}>{v}</span>
    </div>
  );
}
function Row({ label, value, pill, pillColour }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12,
      padding: "4px 0", borderBottom: "1px dashed rgba(15,19,24,0.06)" }}>
      <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#6B7280", minWidth: 80 }}>{label}</span>
      <span style={{ flex: 1 }}>{value}</span>
      {pill && <span style={{
        fontSize: 10, padding: "2px 6px", borderRadius: 999,
        background: (pillColour || "#6B7280") + "22", color: pillColour || "#6B7280", fontWeight: 600,
      }}>{pill}</span>}
    </div>
  );
}
function Empty({ children }) {
  return <div style={{ fontSize: 12, color: "#9CA3AF", fontStyle: "italic" }}>{children}</div>;
}
function Btn({ children, primary }) {
  return (
    <button style={{
      padding: "8px 12px", fontSize: 12, fontWeight: 600, borderRadius: 6,
      border: primary ? "none" : `1px solid rgba(15,19,24,0.2)`,
      background: primary ? GOLD : "transparent",
      color: primary ? INK : INK, cursor: "pointer", fontFamily: "inherit",
    }}>{children}</button>
  );
}
function fmtHa(ha) {
  if (ha == null) return "—";
  return `${Number(ha).toFixed(1)} ha`;
}
function statusColour(s) {
  const v = (s || "").toLowerCase();
  if (v.includes("approved") || v === "granted") return "#3B8A5A";
  if (v.includes("refused") || v === "rejected") return "#B84A4A";
  if (v === "pending" || v === "submitted") return "#E89A2A";
  return "#6B7280";
}
