import React, { useState } from "react";
import { COLOURS, SANS } from "./tokens";

// Left rail — filters + saved views. Controlled component: parent owns
// the `filters` object; we fire `onChange(nextFilters)`.
const FILTER_GROUPS = [
  {
    key: "case_type",
    label: "Case type",
    options: [
      { v: "NSIP_DCO", l: "NSIP DCO" },
      { v: "LPA_PLANNING", l: "LPA major planning" },
      { v: "OFGEM_CODE_MOD", l: "Ofgem code modification" },
      { v: "NESO", l: "NESO methodology" },
      { v: "APPEAL", l: "Appeal" },
      { v: "CMA", l: "CMA" },
      { v: "AR_ROUND", l: "AR round" },
      { v: "CAPACITY_MARKET", l: "Capacity Market" },
    ],
  },
  {
    key: "publisher",
    label: "Publisher",
    options: [
      { v: "PINS", l: "PINS" },
      { v: "Ofgem", l: "Ofgem" },
      { v: "NESO / DESNZ", l: "NESO / DESNZ" },
      { v: "DESNZ", l: "DESNZ" },
      { v: "Cambridgeshire CC", l: "Cambridgeshire CC" },
      { v: "North Yorkshire C", l: "North Yorkshire C" },
    ],
  },
  {
    key: "status",
    label: "Status",
    options: [
      { v: "open", l: "Open" },
      { v: "closed", l: "Closed" },
      { v: "decided", l: "Decided" },
      { v: "withdrawn", l: "Withdrawn" },
    ],
  },
  {
    key: "region",
    label: "Region",
    options: [
      { v: "East of England", l: "East of England" },
      { v: "Yorkshire & The Humber", l: "Yorkshire & The Humber" },
      { v: "GB", l: "GB-wide" },
    ],
  },
  {
    key: "industry",
    label: "Industry",
    options: [
      { v: "energy", l: "Energy" },
      { v: "transmission", l: "Transmission" },
      { v: "data_centre", l: "Data centre" },
    ],
  },
  {
    key: "technology",
    label: "Technology",
    options: [
      { v: "solar", l: "Solar" },
      { v: "bess", l: "BESS" },
      { v: "transmission", l: "Transmission" },
      { v: "grid", l: "Grid" },
      { v: "mixed", l: "Mixed" },
    ],
  },
  {
    key: "capacity_band",
    label: "Capacity band",
    options: [
      { v: "sub_50", l: "< 50 MW" },
      { v: "50_to_100", l: "50-100 MW" },
      { v: "100_to_500", l: "100-500 MW" },
      { v: "500_plus", l: "≥ 500 MW" },
      { v: "n_a", l: "Not applicable" },
    ],
  },
];

const SAVED_VIEWS = [
  { id: "watched", label: "Watched" },
  { id: "pinned", label: "Pinned" },
  { id: "next14", label: "Deadlines ≤ 14 d" },
  { id: "nsip_in_exam", label: "NSIP in examination" },
];

export default function DocketLibrary({ filters = {}, onChange, onSavedView, onCreate }) {
  const [openGroups, setOpenGroups] = useState(() =>
    FILTER_GROUPS.reduce((acc, g) => ({ ...acc, [g.key]: true }), {})
  );
  const setVal = (key, v) => onChange({ ...filters, [key]: filters[key] === v ? undefined : v });

  return (
    <aside
      style={{
        width: 320,
        minWidth: 320,
        background: "#FFFFFF",
        borderRight: `1px solid ${COLOURS.border}`,
        display: "flex",
        flexDirection: "column",
        height: "100%",
        fontFamily: SANS,
      }}
    >
      {/* Search */}
      <div style={{ padding: "16px 16px 12px", borderBottom: `1px solid ${COLOURS.border}` }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
          Dockets
        </div>
        <input
          type="search"
          placeholder="Search dockets, applicant, number…"
          value={filters.q || ""}
          onChange={(e) => onChange({ ...filters, q: e.target.value || undefined })}
          style={{
            width: "100%",
            padding: "8px 10px",
            border: `1px solid ${COLOURS.border}`,
            borderRadius: 6,
            fontSize: 13,
            fontFamily: SANS,
            outline: "none",
            color: COLOURS.ink,
          }}
        />
        <button
          onClick={onCreate}
          style={{
            marginTop: 8,
            width: "100%",
            padding: "8px 10px",
            border: `1px solid ${COLOURS.gold}`,
            background: COLOURS.gold,
            color: COLOURS.ink,
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: SANS,
          }}
        >
          + New custom docket
        </button>
      </div>

      {/* Filters */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {FILTER_GROUPS.map((group) => {
          const open = openGroups[group.key];
          return (
            <div key={group.key} style={{ borderBottom: `1px solid ${COLOURS.border}` }}>
              <button
                onClick={() => setOpenGroups({ ...openGroups, [group.key]: !open })}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "10px 16px",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: SANS,
                  fontSize: 12,
                  fontWeight: 600,
                  color: COLOURS.ink,
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                }}
              >
                <span>{group.label}</span>
                <span style={{ color: COLOURS.muted, fontSize: 10 }}>{open ? "−" : "+"}</span>
              </button>
              {open && (
                <div style={{ padding: "2px 12px 10px" }}>
                  {group.options.map((o) => {
                    const active = filters[group.key] === o.v;
                    return (
                      <button
                        key={o.v}
                        onClick={() => setVal(group.key, o.v)}
                        style={{
                          display: "flex",
                          width: "100%",
                          alignItems: "center",
                          gap: 8,
                          padding: "5px 8px",
                          background: active ? "rgba(245,183,49,.12)" : "transparent",
                          border: "none",
                          borderRadius: 4,
                          cursor: "pointer",
                          fontFamily: SANS,
                          fontSize: 12.5,
                          color: active ? COLOURS.ink : COLOURS.inkSoft,
                          textAlign: "left",
                          fontWeight: active ? 600 : 400,
                        }}
                      >
                        <span
                          style={{
                            width: 12,
                            height: 12,
                            borderRadius: 2,
                            border: `1.5px solid ${active ? COLOURS.gold : COLOURS.mutedLight}`,
                            background: active ? COLOURS.gold : "transparent",
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                          }}
                        >
                          {active && (
                            <svg width="8" height="8" viewBox="0 0 10 10" fill="none" stroke={COLOURS.ink} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M2 5 L4 7 L8 3" />
                            </svg>
                          )}
                        </span>
                        <span>{o.l}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        <div style={{ padding: "10px 16px", marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Date opened
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type="date"
              value={filters.date_from || ""}
              onChange={(e) => onChange({ ...filters, date_from: e.target.value || undefined })}
              style={{ flex: 1, padding: "6px 8px", border: `1px solid ${COLOURS.border}`, borderRadius: 4, fontSize: 12, fontFamily: SANS }}
            />
            <input
              type="date"
              value={filters.date_to || ""}
              onChange={(e) => onChange({ ...filters, date_to: e.target.value || undefined })}
              style={{ flex: 1, padding: "6px 8px", border: `1px solid ${COLOURS.border}`, borderRadius: 4, fontSize: 12, fontFamily: SANS }}
            />
          </div>
        </div>
      </div>

      {/* Saved views */}
      <div style={{ padding: "10px 16px 16px", borderTop: `1px solid ${COLOURS.border}`, background: COLOURS.ivory }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
          Saved views
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {SAVED_VIEWS.map((sv) => (
            <button
              key={sv.id}
              onClick={() => onSavedView && onSavedView(sv.id)}
              style={{
                padding: "5px 10px",
                fontSize: 11.5,
                border: `1px solid ${COLOURS.gold}`,
                background: "#FFFFFF",
                color: COLOURS.ink,
                borderRadius: 12,
                cursor: "pointer",
                fontFamily: SANS,
              }}
            >
              {sv.label}
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
