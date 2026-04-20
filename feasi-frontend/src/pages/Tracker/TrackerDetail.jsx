import React, { useMemo, useState } from "react";
import { useTrackerDetail } from "../../hooks/useTracker";
import ReviewModal from "./ReviewModal";

/* ─────────────────────────────────────────────────────────────────
   TrackerDetail — right-rail drawer that renders all 38 fields for
   one substation, grouped by section. Gold confidence chip;
   external source links open in a new tab.

   Props:
     id       — project_id to load (null closes the drawer)
     onClose  — callback from parent
     admin    — if true, shows the Edit button
   ──────────────────────────────────────────────────────────────── */

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#FFFFFF",
  ok: "#2FA84F",
  warn: "#D4A018",
  err: "#D64545",
};

const STATUS_COLORS = {
  planned: { bg: "#FDF2D1", fg: "#8B6A00", border: "#E8C75A" },
  under_construction: { bg: "#FCEAB8", fg: "#7A5A00", border: C.gold },
  complete: { bg: "#D8F0DC", fg: "#1C6B3A", border: "#8DCEA0" },
  cancelled: { bg: "#FBD8D5", fg: "#8E1E1E", border: "#E89A94" },
};

function confidenceChip(c) {
  if (c == null) return { bg: "#EEE", fg: "#666", label: "—" };
  if (c >= 0.75) return { bg: "#D8F0DC", fg: "#1C6B3A", label: c.toFixed(2) };
  if (c >= 0.5) return { bg: "#FDF2D1", fg: "#8B6A00", label: c.toFixed(2) };
  return { bg: "#FBD8D5", fg: "#8E1E1E", label: c.toFixed(2) };
}

// ── Field groups ───────────────────────────────────────────────
const GROUPS = [
  {
    label: "Identity",
    fields: [
      ["project_id", "Project ID"],
      ["substation_name", "Substation name"],
      ["external_ids", "External IDs"],
      ["tags", "Tags"],
    ],
  },
  {
    label: "Project",
    fields: [
      ["station_type", "Station type"],
      ["parent_project", "Parent project"],
      ["project_description", "Description"],
      ["upgrade_or_new", "Upgrade / new"],
    ],
  },
  {
    label: "Location",
    fields: [
      ["region", "Region"],
      ["lpa", "LPA"],
      ["county", "County"],
      ["country", "Country"],
      ["geom_wkt", "Geometry WKT"],
      ["osgb_easting", "OSGB easting"],
      ["osgb_northing", "OSGB northing"],
    ],
  },
  {
    label: "Developer",
    fields: [
      ["parent_company", "Parent company"],
      ["developer", "Developer"],
    ],
  },
  {
    label: "Electrical",
    fields: [
      ["voltage_kv_primary", "Primary voltage"],
      ["voltage_kv_secondary", "Secondary voltage"],
      ["voltage_description", "Voltage description"],
      ["equipment_description", "Equipment description"],
      ["equipment_capacity_mva", "Equipment capacity (MVA)"],
    ],
  },
  {
    label: "Timeline",
    fields: [
      ["construction_year", "Construction year"],
      ["construction_date_detail", "Construction detail"],
      ["construction_status", "Construction status"],
      ["operation_year", "Operation year"],
      ["operation_date_detail", "Operation detail"],
    ],
  },
  {
    label: "Finance",
    fields: [
      ["capex_gbp_millions", "Capex (£m)"],
      ["capex_description", "Capex description"],
      ["capex_price_base_year", "Price base year"],
      ["financial_description", "Financial description"],
    ],
  },
  {
    label: "Provenance",
    fields: [
      ["source_type", "Source type"],
      ["source_docket_id", "Source docket ID"],
      ["docket_profile_url", "Docket profile URL"],
      ["source_links", "Source links"],
      ["capex_source_link", "Capex source link"],
      ["last_updated", "Last updated"],
      ["first_seen", "First seen"],
      ["change_log", "Change log"],
      ["confidence", "Confidence"],
      ["sme_reviewed", "SME reviewed"],
      ["sme_reviewer", "SME reviewer"],
    ],
  },
];

const URL_KEYS = new Set(["docket_profile_url", "capex_source_link"]);

// ── Value renderer ─────────────────────────────────────────────
function formatValue(key, val) {
  if (val == null || val === "") return <span style={{ color: C.tertiary }}>—</span>;
  if (key === "source_links" && Array.isArray(val)) {
    return (
      <ul style={{ margin: 0, padding: "0 0 0 16px", display: "grid", gap: 4 }}>
        {val.map((u, i) => (
          <li key={i} style={{ fontSize: 11, wordBreak: "break-all" }}>
            <a href={u} target="_blank" rel="noreferrer" style={{ color: C.goldSoft }}>{u}</a>
          </li>
        ))}
      </ul>
    );
  }
  if (URL_KEYS.has(key)) {
    return (
      <a href={val} target="_blank" rel="noreferrer" style={{ color: C.goldSoft, wordBreak: "break-all" }}>
        {val}
      </a>
    );
  }
  if (key === "external_ids" && typeof val === "object") {
    return (
      <div style={{ display: "grid", gap: 4 }}>
        {Object.entries(val).map(([k, v]) => (
          <div key={k} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
            <span style={{ color: C.tertiary }}>{k}:</span>{" "}
            <span style={{ color: C.ink }}>{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }
  if (key === "change_log" && Array.isArray(val)) {
    if (!val.length) return <span style={{ color: C.tertiary }}>No changes logged</span>;
    return (
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 6 }}>
        {val.map((c, i) => (
          <li key={i} style={{ fontSize: 11, display: "grid", gap: 2 }}>
            <span style={{ color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>{c.date}</span>
            <span style={{ color: C.ink }}>
              <code style={{ fontSize: 10, color: C.goldSoft }}>{c.field}</code>:{" "}
              {String(c.from)} → <strong>{String(c.to)}</strong>
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (key === "tags" && Array.isArray(val)) {
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {val.map((t) => (
          <span
            key={t}
            style={{
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 10,
              background: C.goldSurface,
              color: C.goldSoft,
              border: `1px solid ${C.goldBorder}`,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {t}
          </span>
        ))}
      </div>
    );
  }
  if (key === "construction_status") {
    const s = STATUS_COLORS[val] || { bg: "#EEE", fg: "#333", border: "#CCC" };
    return (
      <span
        style={{
          display: "inline-block",
          padding: "3px 10px",
          borderRadius: 12,
          background: s.bg,
          color: s.fg,
          border: `1px solid ${s.border}`,
          fontSize: 11,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {String(val).replace(/_/g, " ")}
      </span>
    );
  }
  if (key === "confidence") {
    const c = confidenceChip(val);
    return (
      <span
        style={{
          display: "inline-block",
          padding: "3px 10px",
          borderRadius: 12,
          background: c.bg,
          color: c.fg,
          fontSize: 11,
          fontWeight: 700,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {c.label}
      </span>
    );
  }
  if (key === "sme_reviewed") {
    return (
      <span style={{ color: val ? C.ok : C.warn, fontWeight: 600 }}>
        {val ? "Reviewed" : "Pending review"}
      </span>
    );
  }
  if (typeof val === "number") {
    return (
      <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
        {Number.isInteger(val) ? val : val.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </span>
    );
  }
  if (typeof val === "boolean") return val ? "Yes" : "No";
  return <span style={{ wordBreak: "break-word" }}>{String(val)}</span>;
}

// ── Component ──────────────────────────────────────────────────
export default function TrackerDetail({ id, onClose, admin = false }) {
  const { row, loading, error } = useTrackerDetail(id);
  const [editOpen, setEditOpen] = useState(false);

  const fieldCount = useMemo(
    () => GROUPS.reduce((n, g) => n + g.fields.length, 0),
    []
  );

  if (!id) return null;

  return (
    <>
      <aside
        role="dialog"
        aria-label="Substation detail"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 480,
          maxWidth: "96vw",
          background: C.ivory,
          borderLeft: `1px solid ${C.border}`,
          boxShadow: "-12px 0 32px rgba(15,19,24,0.12)",
          display: "flex",
          flexDirection: "column",
          zIndex: 90,
          fontFamily: "'DM Sans', sans-serif",
          color: C.ink,
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "20px 22px 14px",
            borderBottom: `1px solid ${C.border}`,
            background: C.bg,
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: C.tertiary, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Substation Tracker · {fieldCount} fields
            </div>
            <h2 style={{ margin: "6px 0 4px", fontSize: 18, fontWeight: 800, letterSpacing: "-0.01em" }}>
              {loading ? "Loading…" : row?.substation_name || "—"}
            </h2>
            {row && (
              <div style={{ fontSize: 12, color: C.secondary, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{row.project_id}</span>
                <span style={{ color: C.tertiary }}>·</span>
                <span>{row.region}</span>
                <span style={{ color: C.tertiary }}>·</span>
                <span>{row.voltage_kv_primary ? `${row.voltage_kv_primary} kV` : "—"}</span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close detail"
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
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: "auto", padding: "16px 22px 80px" }}>
          {error && (
            <div style={{ padding: 12, background: "#FBD8D5", border: `1px solid #E89A94`, borderRadius: 6, color: "#8E1E1E", fontSize: 12 }}>
              Failed to load: {error}
            </div>
          )}
          {loading && <div style={{ color: C.tertiary, fontSize: 12 }}>Loading substation…</div>}
          {row && GROUPS.map((g) => (
            <section key={g.label} style={{ marginBottom: 22 }}>
              <h3
                style={{
                  margin: "0 0 10px",
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: C.goldSoft,
                  fontWeight: 700,
                  borderBottom: `1px solid ${C.goldBorder}`,
                  paddingBottom: 6,
                }}
              >
                {g.label}
              </h3>
              <div style={{ display: "grid", gap: 10 }}>
                {g.fields.map(([key, label]) => (
                  <div
                    key={key}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "160px 1fr",
                      gap: 12,
                      alignItems: "start",
                      fontSize: 12,
                    }}
                  >
                    <div style={{ color: C.tertiary, fontSize: 11 }}>{label}</div>
                    <div style={{ color: C.ink, minWidth: 0 }}>
                      {formatValue(key, row[key])}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>

        {/* Footer */}
        {row && (
          <div
            style={{
              position: "sticky",
              bottom: 0,
              padding: "12px 22px",
              background: C.bg,
              borderTop: `1px solid ${C.border}`,
              display: "flex",
              gap: 8,
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontSize: 10, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
              last_updated {row.last_updated?.slice(0, 10)}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              {row.docket_profile_url && (
                <a
                  href={row.docket_profile_url}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    fontSize: 12,
                    padding: "7px 12px",
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    color: C.secondary,
                    textDecoration: "none",
                    background: "transparent",
                  }}
                >
                  Open docket
                </a>
              )}
              {admin && (
                <button
                  type="button"
                  onClick={() => setEditOpen(true)}
                  style={{
                    fontSize: 12,
                    padding: "7px 14px",
                    borderRadius: 6,
                    border: `1px solid ${C.gold}`,
                    background: C.gold,
                    color: C.ink,
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Edit
                </button>
              )}
            </div>
          </div>
        )}
      </aside>

      {editOpen && row && (
        <ReviewModal
          substation={row}
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false);
            // The detail hook will refetch next time the drawer opens.
          }}
        />
      )}
    </>
  );
}
