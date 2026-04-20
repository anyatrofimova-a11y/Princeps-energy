import React, { useState } from "react";
import { useUpdateSubstation } from "../../hooks/useTracker";

/* ─────────────────────────────────────────────────────────────────
   ReviewModal — full-form edit for one substation.
   Every editable field is laid out in a scrollable form. On Save we
   call PATCH /api/tracker/substations/{id} via the hook layer.

   NOTE: the backend PATCH endpoint is not live yet — see
   api/tracker.js::updateSubstation. The mock path logs to console
   and returns a stubbed success response so the UI flow works
   end-to-end. TODO: replace the stub once the backend lands.
   ──────────────────────────────────────────────────────────────── */

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldBorder: "rgba(245,183,49,0.32)",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#FFFFFF",
  err: "#D64545",
};

const STATUS_OPTIONS = ["planned", "under_construction", "complete", "cancelled"];
const UPGRADE_OPTIONS = ["new", "upgrade", "replacement"];
const STATION_TYPES = ["substation", "switching_station"];
const SOURCE_TYPES = ["RIIO_ET", "RIIO_ED", "NOA", "CSNP", "S37", "NSIP", "LTDS", "LPA", "OFTO"];
const COUNTRIES = ["England", "Scotland", "Wales", "Northern Ireland"];

// ── Input primitives ──────────────────────────────────────────
const labelStyle = { fontSize: 11, color: C.tertiary, fontWeight: 600, marginBottom: 4, display: "block" };
const fieldStyle = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.bg,
  fontSize: 12,
  fontFamily: "'DM Sans', sans-serif",
  color: C.ink,
  boxSizing: "border-box",
};

function Text({ label, value, onChange, multiline, type = "text" }) {
  const Tag = multiline ? "textarea" : "input";
  return (
    <label>
      <span style={labelStyle}>{label}</span>
      <Tag
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        style={{ ...fieldStyle, minHeight: multiline ? 70 : undefined, resize: multiline ? "vertical" : undefined }}
      />
    </label>
  );
}

function NumberField({ label, value, onChange, step = "any" }) {
  return (
    <label>
      <span style={labelStyle}>{label}</span>
      <input
        type="number"
        value={value ?? ""}
        step={step}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? null : Number(v));
        }}
        style={fieldStyle}
      />
    </label>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <label>
      <span style={labelStyle}>{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        style={fieldStyle}
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
        ))}
      </select>
    </label>
  );
}

function Toggle({ label, value, onChange }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: C.ink, cursor: "pointer" }}>
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

// ── Modal ──────────────────────────────────────────────────────
export default function ReviewModal({ substation, onClose, onSaved }) {
  const [form, setForm] = useState({ ...substation });
  const { save, saving, error } = useUpdateSubstation();
  const [toast, setToast] = useState(null);

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const onSubmit = async (e) => {
    e.preventDefault();
    // Diff vs. the seed so we don't PATCH unchanged fields.
    const patch = {};
    Object.keys(form).forEach((k) => {
      if (JSON.stringify(form[k]) !== JSON.stringify(substation[k])) patch[k] = form[k];
    });
    try {
      const res = await save(substation.project_id, patch);
      setToast({
        kind: "ok",
        msg: res?.stub
          ? `Stub save — ${Object.keys(patch).length} fields queued (backend PATCH not wired yet)`
          : `Saved ${Object.keys(patch).length} fields`,
      });
      setTimeout(() => {
        setToast(null);
        onSaved?.(form);
      }, 1400);
    } catch (err) {
      setToast({ kind: "err", msg: err.message || String(err) });
    }
  };

  return (
    <div
      role="dialog"
      aria-label="Edit substation"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,19,24,0.45)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: 32,
        zIndex: 100,
        fontFamily: "'DM Sans', sans-serif",
        color: C.ink,
      }}
      onClick={onClose}
    >
      <form
        onSubmit={onSubmit}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: C.ivory,
          borderRadius: 12,
          width: "100%",
          maxWidth: 860,
          maxHeight: "92vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 60px rgba(15,19,24,0.35)",
          border: `1px solid ${C.goldBorder}`,
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "16px 24px",
            borderBottom: `1px solid ${C.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: C.bg,
            borderTopLeftRadius: 12,
            borderTopRightRadius: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 10, color: C.tertiary, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Edit substation · SME Review
            </div>
            <h2 style={{ margin: "4px 0 0", fontSize: 16, fontWeight: 800, letterSpacing: "-0.01em" }}>
              {substation.substation_name}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: "transparent",
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              padding: "6px 10px",
              cursor: "pointer",
              fontSize: 14,
              color: C.secondary,
            }}
          >
            ×
          </button>
        </header>

        {/* Body */}
        <div style={{ flex: 1, overflow: "auto", padding: "16px 24px", display: "grid", gap: 20 }}>
          {/* Identity */}
          <section>
            <h3 style={sectionTitle}>Identity</h3>
            <div style={grid2}>
              <Text label="Project ID" value={form.project_id} onChange={set("project_id")} />
              <Text label="Substation name" value={form.substation_name} onChange={set("substation_name")} />
            </div>
          </section>

          {/* Project */}
          <section>
            <h3 style={sectionTitle}>Project</h3>
            <div style={grid2}>
              <Select label="Station type" value={form.station_type} onChange={set("station_type")} options={STATION_TYPES} />
              <Select label="Upgrade / new" value={form.upgrade_or_new} onChange={set("upgrade_or_new")} options={UPGRADE_OPTIONS} />
              <Text label="Parent project" value={form.parent_project} onChange={set("parent_project")} />
            </div>
            <div style={{ marginTop: 10 }}>
              <Text label="Description" value={form.project_description} onChange={set("project_description")} multiline />
            </div>
          </section>

          {/* Location */}
          <section>
            <h3 style={sectionTitle}>Location</h3>
            <div style={grid3}>
              <Text label="Region" value={form.region} onChange={set("region")} />
              <Text label="LPA" value={form.lpa} onChange={set("lpa")} />
              <Text label="County" value={form.county} onChange={set("county")} />
              <Select label="Country" value={form.country} onChange={set("country")} options={COUNTRIES} />
              <NumberField label="Longitude" value={form.longitude} onChange={set("longitude")} />
              <NumberField label="Latitude" value={form.latitude} onChange={set("latitude")} />
              <NumberField label="OSGB easting" value={form.osgb_easting} onChange={set("osgb_easting")} />
              <NumberField label="OSGB northing" value={form.osgb_northing} onChange={set("osgb_northing")} />
              <Text label="Geometry WKT" value={form.geom_wkt} onChange={set("geom_wkt")} />
            </div>
          </section>

          {/* Developer */}
          <section>
            <h3 style={sectionTitle}>Developer</h3>
            <div style={grid2}>
              <Text label="Parent company" value={form.parent_company} onChange={set("parent_company")} />
              <Text label="Developer" value={form.developer} onChange={set("developer")} />
            </div>
          </section>

          {/* Electrical */}
          <section>
            <h3 style={sectionTitle}>Electrical</h3>
            <div style={grid3}>
              <NumberField label="Primary voltage (kV)" value={form.voltage_kv_primary} onChange={set("voltage_kv_primary")} />
              <NumberField label="Secondary voltage (kV)" value={form.voltage_kv_secondary} onChange={set("voltage_kv_secondary")} />
              <NumberField label="Capacity (MVA)" value={form.equipment_capacity_mva} onChange={set("equipment_capacity_mva")} />
            </div>
            <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
              <Text label="Voltage description" value={form.voltage_description} onChange={set("voltage_description")} />
              <Text label="Equipment description" value={form.equipment_description} onChange={set("equipment_description")} multiline />
            </div>
          </section>

          {/* Timeline */}
          <section>
            <h3 style={sectionTitle}>Timeline</h3>
            <div style={grid3}>
              <NumberField label="Construction year" value={form.construction_year} onChange={set("construction_year")} step={1} />
              <Text label="Construction detail" value={form.construction_date_detail} onChange={set("construction_date_detail")} />
              <Select label="Construction status" value={form.construction_status} onChange={set("construction_status")} options={STATUS_OPTIONS} />
              <NumberField label="Operation year" value={form.operation_year} onChange={set("operation_year")} step={1} />
              <Text label="Operation detail" value={form.operation_date_detail} onChange={set("operation_date_detail")} />
            </div>
          </section>

          {/* Finance */}
          <section>
            <h3 style={sectionTitle}>Finance</h3>
            <div style={grid3}>
              <NumberField label="Capex (£m)" value={form.capex_gbp_millions} onChange={set("capex_gbp_millions")} />
              <NumberField label="Price base year" value={form.capex_price_base_year} onChange={set("capex_price_base_year")} step={1} />
            </div>
            <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
              <Text label="Capex description" value={form.capex_description} onChange={set("capex_description")} />
              <Text label="Financial description" value={form.financial_description} onChange={set("financial_description")} multiline />
            </div>
          </section>

          {/* Provenance */}
          <section>
            <h3 style={sectionTitle}>Provenance</h3>
            <div style={grid2}>
              <Select label="Source type" value={form.source_type} onChange={set("source_type")} options={SOURCE_TYPES} />
              <Text label="Source docket ID" value={form.source_docket_id} onChange={set("source_docket_id")} />
              <Text label="Docket profile URL" value={form.docket_profile_url} onChange={set("docket_profile_url")} />
              <Text label="Capex source link" value={form.capex_source_link} onChange={set("capex_source_link")} />
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 16, alignItems: "center" }}>
              <NumberField label="Confidence (0–1)" value={form.confidence} onChange={set("confidence")} />
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={labelStyle}>Review</span>
                <Toggle label="SME reviewed" value={form.sme_reviewed} onChange={set("sme_reviewed")} />
              </div>
              <Text label="SME reviewer" value={form.sme_reviewer} onChange={set("sme_reviewer")} />
            </div>
          </section>

          {error && (
            <div style={{ background: "#FBD8D5", border: `1px solid #E89A94`, color: "#8E1E1E", padding: 10, borderRadius: 6, fontSize: 12 }}>
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer
          style={{
            padding: "12px 24px",
            borderTop: `1px solid ${C.border}`,
            background: C.bg,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottomLeftRadius: 12,
            borderBottomRightRadius: 12,
          }}
        >
          <span style={{ fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
            PATCH /api/tracker/substations/{substation.project_id}
          </span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {toast && (
              <span style={{
                fontSize: 12,
                color: toast.kind === "ok" ? "#1C6B3A" : "#8E1E1E",
                background: toast.kind === "ok" ? "#D8F0DC" : "#FBD8D5",
                padding: "4px 10px",
                borderRadius: 6,
              }}>
                {toast.msg}
              </span>
            )}
            <button
              type="button"
              onClick={onClose}
              style={{
                fontSize: 12,
                padding: "7px 14px",
                borderRadius: 6,
                border: `1px solid ${C.border}`,
                background: "transparent",
                color: C.secondary,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              style={{
                fontSize: 12,
                padding: "7px 18px",
                borderRadius: 6,
                border: `1px solid ${C.gold}`,
                background: saving ? "#f3d98a" : C.gold,
                color: C.ink,
                fontWeight: 700,
                cursor: saving ? "wait" : "pointer",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}

const sectionTitle = {
  margin: "0 0 10px",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: C.goldSoft,
  fontWeight: 700,
  borderBottom: `1px solid ${C.goldBorder}`,
  paddingBottom: 6,
};

const grid2 = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 };
const grid3 = { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 };
